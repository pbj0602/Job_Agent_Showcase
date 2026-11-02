"""Visa / sponsorship verdict: does the candidate need the employer to do something, and will it?

Two independent questions, answered from different evidence:

1. Does the candidate need it here?  -> the vault's work_authorization.yml (per country,
   researched from official sources, with confidence labels).
2. Will this employer do it?          -> the JD's own words, public sponsor registers
   (UK licensed sponsors, NL IND recognised sponsors), and company size.

Verdicts:
    not_needed  candidate can work there without the employer doing anything special
    likely      needed, and there is positive evidence the employer does it
    unclear     needed, no evidence either way -> a human decides
    no          the JD rules it out, or the country route is closed
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..text import company_key, fold

_NO = re.compile(
    r"(unable|not able|cannot|can ?not|can't|do not|don't|does not|doesn't|will not|won't|are not able)"
    r"( to)? (offer|provide|support|sponsor|consider)[^.\n]{0,60}(visa|sponsor|work permit|immigration)"
    r"|no (visa |work )?sponsorship|sponsorship (is )?not (available|provided|offered)"
    r"|without (the need for |requiring )?(visa )?sponsorship"
    r"|(must|need to|required to|should) (already )?(have|hold|possess)[^.\n]{0,50}"
    r"(right to work|work permit|working rights|eligib\w+ to work)"
    r"|(existing|full|unrestricted|valid) (right to work|work permit)"
    r"|(eu|eea) (citizens?|nationals?|passport) only"
)
_YES = re.compile(
    r"(visa )?sponsorship (is |can be |will be )?(available|provided|offered|possible)"
    r"|(we|will|can|able to|happy to) (offer|provide|support|sponsor)[^.\n]{0,40}(visa|sponsorship|relocation and visa)"
    r"|sponsor(ing)? (your |a |the )?visa|government authorised exchange|\bgae\b|temporary work visa"
    r"|visa (support|assistance)|immigration support|kennismigrant|highly skilled migrant"
    r"|recognised sponsor|recognized sponsor|blue card"
)
_UNPAID = re.compile(r"\bunpaid\b|no (salary|compensation|remuneration)|unbezahlt|onbetaald")
_DURATION = re.compile(r"(\d{1,2})\s*(?:-|–|to)?\s*(\d{1,2})?\s*(weeks?|months?|wochen|monate|maanden|månader)")


def jd_signal(text: str) -> tuple[str | None, str]:
    """('no' | 'yes' | None, the sentence that decided it)."""
    t = fold(text)
    for verdict, rx in (("no", _NO), ("yes", _YES)):
        m = rx.search(t)
        if m:
            return verdict, " ".join(t[max(0, m.start() - 60): m.end() + 40].split())
    return None, ""


def duration_days(text: str) -> int | None:
    """Longest internship length the JD mentions, in days ('10-12 weeks' -> 84)."""
    best = None
    for a, b, unit in _DURATION.findall(fold(text)):
        n = int(b or a)
        days = n * 7 if unit.startswith(("week", "woche")) else n * 30
        if 14 <= days <= 400:
            best = max(best or 0, days)
    return best


class Register:
    """A public list of employers that sponsor (UK licensed sponsors CSV, NL IND register ...).

    Load with the column holding the organisation name; lookups are by normalised name.
    """

    def __init__(self, name: str, companies: set[str]):
        self.name = name
        self.keys = companies

    @classmethod
    def from_csv(cls, name: str, path: Path, column: str) -> "Register":
        keys = set()
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            for row in csv.DictReader(f):
                k = company_key(row.get(column) or "")
                if k:
                    keys.add(k)
        return cls(name, keys)

    def has(self, company: str) -> bool:
        k = company_key(company)
        if not k:
            return False
        if k in self.keys:
            return True
        # "Bloomberg" should match "Bloomberg Finance": the register name starts with ours.
        return len(k) >= 4 and any(r.startswith(k + " ") for r in self.keys)


@dataclass
class Verdict:
    verdict: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    confidence: str = "unverified"


def judge(country_code: str, rules: dict, jd_text: str, company: str, big: bool,
          registers: dict[str, Register] | None = None) -> Verdict:
    """Combine the country rule with employer evidence. rules = work_authorization.yml['countries']."""
    rule = rules.get(country_code)
    if not rule:
        return Verdict("unclear", f"{country_code}: no work-authorisation rule in vault")
    conf = rule.get("confidence", "unverified")
    tier = rule.get("tier")
    if tier == "skip":
        return Verdict("no", f"{country_code}: route closed — {rule.get('reason', 'see doc')}", confidence=conf)

    signal, evidence = jd_signal(jd_text)
    ev = [f"JD: “{evidence}”"] if evidence else []
    if rule.get("paid_only") and _UNPAID.search(fold(jd_text)):
        return Verdict("no", f"{country_code}: only paid internships qualify, JD says unpaid", ev, conf)
    max_days = rule.get("max_days")
    days = duration_days(jd_text)
    if max_days and days and days > max_days:
        return Verdict("unclear", f"{country_code}: JD mentions ~{days} days, route allows {max_days}",
                       ev + [f"duration ≈ {days} days"], conf)

    if not rule.get("sponsor_needed", True):
        if signal == "no" and re.search(r"citizen|passport|national", evidence):
            return Verdict("no", f"{country_code}: JD restricts to citizens", ev, conf)
        # "must have the right to work" is fine here: the candidate has it without the employer.
        return Verdict("not_needed", f"{country_code}: {rule.get('self_action') or 'no employer action'}", ev, conf)

    if signal == "no":
        return Verdict("no", f"{country_code}: JD rules out sponsorship", ev, conf)
    if signal == "yes":
        return Verdict("likely", f"{country_code}: JD says it sponsors", ev, conf)
    hits = [r.name for r in (registers or {}).values() if r.has(company)]
    if hits:
        return Verdict("likely", f"{country_code}: on {', '.join(hits)}", ev + [f"register: {h}" for h in hits], conf)
    if big:
        return Verdict("likely" if tier in ("big_programme_only", "feasible") else "unclear",
                       f"{country_code}: big company, JD silent on sponsorship", ev, conf)
    return Verdict("unclear", f"{country_code}: sponsorship needed, no evidence the employer does it", ev, conf)
