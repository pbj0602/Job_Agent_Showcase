"""Decide what happens to a job: the one place where all the enrichers meet.

Order matters: hard stops first (thesis, language, visa), then anything that needs a
human, then big vs small company. The candidate's own policy (vault policy.yml) decides
which roles get tailored automatically and how many applications are reviewed before
small companies go fully automatic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import PACKS
from .enrich.language import language_required
from .enrich.role import classify as classify_role
from .enrich.sponsorship import Register, judge
from .season import season as season_of
from .text import fold

MIN_JD_CHARS = 200
_THESIS = re.compile(r"thesis|degree project|exjobb|examensarbete|master'?s project|masterarbeit"
                     r"|abschlussarbeit|bachelorarbeit|diplomarbeit|afstudeer|graduation project", re.I)
_NOT_THESIS = re.compile(r"\b(no|non|without)[- ]thesis", re.I)
_WERKSTUDENT = re.compile(r"werkstudent|working student|studentische", re.I)
# Only open to students whose own programme requires the internship (DE Pflichtpraktikum,
# FR stage obligatoire ...). A programme without credit-bearing internships cannot certify that.
_MANDATORY = re.compile(r"mandatory internship|compulsory internship|pflichtpraktikum|curricular internship"
                        r"|stage obligatoire|verplichte stage|obligatory internship", re.I)
_YEAR = re.compile(r"\b20(2[4-9])\b")
# Full-time roles for people finishing their degree; a title that also says intern/placement stays.
_NEW_GRAD = re.compile(r"new[- ]?grad|graduate|early[- ]career|entry[- ]level|junior", re.I)
_INTERN = re.compile(r"intern|placement|summer|stage\b|praktik|trainee", re.I)


def is_thesis(title: str) -> bool:
    return bool(_THESIS.search(title or "")) and not _NOT_THESIS.search(title or "")


_BIG: list[str] | None = None
# Careers sites only large employers pay for.
_ENTERPRISE_ATS = re.compile(r"myworkday(jobs|site)\.com|oraclecloud\.com|taleo\.net|successfactors|icims\.com"
                             r"|jobs\.sap\.com|eightfold\.ai|phenompeople|avature\.net", re.I)
_LEGAL_BIG = re.compile(r"\b(ag|se|plc|kgaa|n\.?v|inc|corporation|holding|stiftung)\b\.?", re.I)
_AGENCY = re.compile(r"recruit|staffing|talent|job ?board|careers?-?quest|internhunt|personnel|headhunt", re.I)
_JD_BIG = re.compile(r"fortune 500|ftse ?100|\bdax\b|nasdaq|nyse|publicly (listed|traded)|stock exchange"
                     r"|global leader|world'?s (largest|leading)|in (over |more than )?\d{2,} countries"
                     r"|subsidiary of|part of the \w+ group", re.I)
_JD_SMALL = re.compile(r"\bstart-?up\b|scale-?up|\bseed\b|series [abc]\b|early[- ]stage|small team|founding team", re.I)
_HEADCOUNT = re.compile(r"(\d[\d,.]*)\s*\+?\s*(employees|people|colleagues|team members|staff|mitarbeit)", re.I)


def _headcount(jd: str) -> int | None:
    sizes = []
    for m in _HEADCOUNT.finditer(jd):
        n = m.group(1).replace(",", "").replace(".", "")
        if n.isdigit() and 2 <= int(n) < 10_000_000:
            sizes.append(int(n))
    return max(sizes) if sizes else None


def company_size(company: str, url: str, jd: str = "") -> tuple[str, str]:
    """big | small | unknown | agency. Small needs positive evidence; unknown waits for an OK
    like big does (defaulting to small let Tesla, PepsiCo and MongoDB through)."""
    global _BIG
    if _BIG is None:
        _BIG = []
        for line in (PACKS / "big_companies.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                _BIG.append(" ".join(re.sub(r"[^a-z0-9]+", " ", fold(line)).split()))
    c = " " + " ".join(re.sub(r"[^a-z0-9]+", " ", fold(company)).split()) + " "
    for name in _BIG:
        if f" {name} " in c:
            return "big", f"on list: {name}"
    m = _ENTERPRISE_ATS.search(url or "") or _ENTERPRISE_ATS.search(company or "")
    if m:
        return "big", f"enterprise ATS ({m.group(0)})"
    if _AGENCY.search(company or ""):
        return "agency", "recruiter / job board, not the employer"
    head = _headcount(jd or "")
    if head and head >= 500:
        return "big", f"JD: {head}+ employees"
    m = _JD_BIG.search(jd or "")
    if m:
        return "big", f"JD: {m.group(0)}"
    if _LEGAL_BIG.search(company or ""):
        return "big", "legal form (AG/SE/plc/Inc …)"
    if head and head < 200:
        return "small", f"JD: {head} employees"
    m = _JD_SMALL.search(jd or "")
    if m:
        return "small", f"JD: {m.group(0)}"
    return "unknown", "no size evidence"


_REQ = re.compile(r"requir|\bmust\b|strong|solid|proficien|expert|fluen|deep|extensive|hands-on|experience (in|with)"
                  r"|knowledge of|skilled|\d\+? years", re.I)
_SOFT = re.compile(r"\bplus\b|nice[- ]to[- ]have|bonus|preferred|desirable|advantage|ideally|familiar|exposure"
                   r"|or similar|one of|any of|such as|e\.g\.|\betc\b|\bor\b|and/or|at least one", re.I)
_OTHER_LANGS = re.compile(r"\b(python|java|javascript|typescript|go|golang|rust|kotlin|scala|ruby|swift|php|c#)\b", re.I)
_HARD_HEAD = re.compile(r"requirement|qualification|must have|you have|you bring|you'll need|what we('re| are) looking for"
                        r"|about you|who you are", re.I)


def _lang_re(lang: str) -> re.Pattern:
    if lang.upper() == "C":  # bare C: not C#, C++, Series C, C-level, Objective-C, (c), C.F.R.
        return re.compile(r"(?<![\w#+/(-])(?<!series )(?<!objective-)C(?![\w#+)-])(?!\.\w)(?!\s*-?level)|\bC/C\+\+", re.I)
    return re.compile(rf"(?<![\w#+]){re.escape(lang)}(?![\w#+])", re.I)


def required_language(jd: str, langs: list[str]) -> str:
    """The first of `langs` the JD *requires*: on a line that reads as a requirement (or under a
    requirements heading) and not softened ("a plus", "one of", "Python or C++")."""
    if not jd or not langs:
        return ""
    pats = [(lang, _lang_re(lang)) for lang in langs]
    section = ""  # "hard" | "soft" | ""
    for raw in re.split(r"\n|(?<=[.;•])\s+", jd):
        line = raw.strip(" -*•\t")
        if not line:
            continue
        if len(line) < 70 and not any(p.search(line) for _, p in pats):
            if _SOFT.search(line):
                section = "soft"
            elif _HARD_HEAD.search(line):
                section = "hard"
            continue
        if _SOFT.search(line) or section == "soft" or len(set(m.lower() for m in _OTHER_LANGS.findall(line))) >= 2:
            continue  # softened, or a menu of languages ("Java, Python, C/C++")
        for lang, p in pats:
            if p.search(line) and (section == "hard" or _REQ.search(line)):
                return lang
    return ""


def skip_reason(title: str, jd: str, role: str, skip: dict) -> str:
    """Her standing "never these" list (policy.yml `skip`): roles, title and JD patterns, languages."""
    if role in (skip.get("roles") or []):
        return f"role '{role}'"
    for pat in skip.get("titles") or []:
        m = re.search(pat, title or "", re.I)
        if m:
            return f"title: {m.group(0)}"
    for pat in skip.get("jd") or []:
        m = re.search(pat, jd or "", re.I)
        if m:
            return f"JD: {m.group(0)}"
    lang = required_language(jd, skip.get("required_languages") or [])
    return f"JD requires {lang}" if lang else ""


def is_big(company: str, url: str, jd: str = "") -> tuple[bool, str]:
    size, why = company_size(company, url, jd)
    return size == "big", why


@dataclass
class Decision:
    status: str                 # next status in store.STATES
    reason: str
    fields: dict = field(default_factory=dict)


def decide(job: dict, *, countries: dict, roles: dict, policy: dict,
           registers: dict[str, Register] | None = None, applied_so_far: int = 0) -> Decision:
    title, company = job.get("title", ""), job.get("company", "")
    jd = job.get("jd") or ""
    cc = job.get("country_code") or ""
    size, why_big = company_size(company, job.get("apply_url") or job.get("url", ""), jd)
    big = size == "big"
    role, role_score, _ = classify_role(title, jd, roles)
    langs = language_required(jd, written_check=job.get("jd_source") != "page-text")
    visa = judge(cc, countries, jd, company, big, registers)
    f = {
        "size": size, "size_reason": why_big,
        "role": role, "role_score": role_score,
        "lang_required": [l for l, _ in langs], "lang_evidence": [e for _, e in langs],
        "visa_verdict": visa.verdict, "visa_reason": visa.reason,
        "visa_evidence": " | ".join(visa.evidence), "visa_confidence": visa.confidence,
        "country_tier": (countries.get(cc) or {}).get("tier", "unknown"),
    }
    f["season"], f["season_evidence"] = season_of(title, jd)

    def out(status: str, reason: str) -> Decision:
        return Decision(status, reason, f)

    if is_thesis(title):
        return out("thesis", "degree project — FYI only")
    grad = policy.get("graduation_year")
    if grad and _NEW_GRAD.search(title) and not _INTERN.search(title):
        return out("skipped", f"new-grad / full-time role — graduating {grad}, looking for internships")
    if policy.get("exclude_werkstudent", True) and _WERKSTUDENT.search(title):
        return out("skipped", "Werkstudent (part-time during semester)")
    focus = policy.get("focus_countries")
    if focus and cc and cc not in focus:
        return out("skipped", f"{cc}: not a target country ({'/'.join(focus)})")
    if policy.get("summer_only") and cc not in (policy.get("any_time_countries") or []) and f["season"] == "off":
        return out("skipped", "not a summer internship: " + f["season_evidence"])
    why = skip_reason(title, jd, role, policy.get("skip") or {})
    if why:
        return out("skipped", "not a fit: " + why)
    for rule in (policy.get("skip") or {}).get("only_in") or []:
        if (role in (rule.get("roles") or []) or re.search(rule.get("match") or "(?!)", title or "", re.I)
                or re.search(rule.get("company") or "(?!)", company or "", re.I)) \
                and cc not in (rule.get("countries") or []):
            return out("skipped", f"not a fit: {rule.get('match')} only in {'/'.join(rule.get('countries') or [])}")
    jd_mandatory = _MANDATORY.search(jd[:3000]) and not re.search(r"freiwillig|voluntary|optional", jd[:3000], re.I)
    if policy.get("no_mandatory_internships", True) and (_MANDATORY.search(title) or jd_mandatory):
        return out("skipped", "mandatory/curricular internship — only for programmes that require one")
    if langs:
        return out("skipped", "requires " + "/".join(f["lang_required"]))
    season = policy.get("season_year")
    years = {int("20" + y) for y in _YEAR.findall(title)}
    if season and years and season not in years:
        return out("manual", f"title says {'/'.join(map(str, sorted(years)))}, target season is {season} — check it is still open")
    if visa.verdict == "no":
        return out("skipped", visa.reason)
    tier = f["country_tier"]
    if tier in ("manual", "pending", "unknown"):
        return out("manual", f"{cc or '??'}: country route {tier} — check docs before applying")
    if tier == "big_programme_only" and not big:  # small ones never sponsor in practice
        return out("skipped", f"{cc}: only big employers with intern programmes sponsor here")
    if visa.verdict == "unclear":
        return out("manual", visa.reason)
    if job.get("ats") == "linkedin" and "linkedin.com" in (job.get("apply_url") or "linkedin.com"):
        return out("manual", "LinkedIn only — no company-site link (never auto-apply on LinkedIn)")
    if len(jd) < MIN_JD_CHARS:
        return out("manual", "job description not fetched")
    if role not in policy.get("auto_tailor_roles", []):
        return out("manual", f"role '{role}' is not in auto_tailor_roles")
    if size == "agency":
        return out("manual", f"posted by a recruiter / job board ({company}) — find the employer's own link")
    # "big" = a well-known name (list, enterprise ATS, JD says 500+ people): the user tailors and applies by hand.
    # Unknown size counts as small (big means a household name).
    dream = policy.get("dream_companies") or []
    if any(re.search(rf"(?<!\w){re.escape(fold(d))}(?!\w)", fold(company)) for d in dream):
        return out("awaiting_confirm", "dream company — 精投 (tailored CV, reviewed before it goes out)")
    if size == "big" and not policy.get("auto_apply_big"):
        return out("awaiting_confirm", f"big company ({why_big}) — applied to by hand")
    if size == "big":
        return out("approved", f"big company ({why_big}) — auto (policy auto_apply_big)")
    if applied_so_far < policy.get("calibration_reviews", 20):
        return out("awaiting_confirm",
                   f"small company — calibration {applied_so_far + 1}/{policy.get('calibration_reviews', 20)}")
    return out("approved", f"{'small' if size == 'small' else 'not a well-known'} company — auto")
