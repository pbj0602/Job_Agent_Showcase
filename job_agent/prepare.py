"""Materials for the jobs picked 自动投 in tracker.xlsx — the user submits them.

    python -m job_agent prepare            # read tracker.xlsx, prepare every new 自动投 pick, rewrite it

自动投 sends the unchanged template, so there is one PDF per template and country, rendered once
into vault/resume/applications/_templates/ (<First>-<Last>-Resume-<role>-<CC>.pdf; re-rendered when
the template changes). Per job, in vault/resume/applications/<slug>/ (ledger field app_dir), only:
  * jd.md      — the posting as captured (or a note to open the link when it was not);
  * answers.md — the link, the form, which CV to upload, copy-ready answers to the usual questions.
No resume.md in the folder: that is what marks a tailored (精投) application.
Contact details never go into these files (they are git-tracked); the PDF header carries them.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from .answers import plan
from .config import resume_dir

TEMPLATES = "applications/_templates"
from .tracker import OPEN

# usual form questions, answered from answers.yml / question_bank.yml / work_authorization.yml
QUESTIONS = [
    "Will you now or in the future require visa sponsorship?",
    "Are you legally authorized to work in this country?",
    "Earliest start date",
    "Duration / availability",
    "Can you commit to six months?",
    "University",
    "Degree",
    "Field of study",
    "Expected graduation",
    "Which languages do you speak?",
    "How did you hear about us?",
    "Willing to relocate?",
    "Gender", "Race / ethnicity", "Disability", "Veteran",
]
REGISTER = {"workday": "要注册账号（Workday 每家公司单独一个账号）", "smartrecruiters": "可以不注册，直接投",
            "linkedin": "LinkedIn：你自己投（不自动投）"}
_DURATION = re.compile(r"[^.\n]*\b(\d+\s*(?:-|–|to)?\s*\d*\s*(?:months?|monate?n?|weeks?))\b[^.\n]*", re.I)


def slug(job: dict) -> str:
    s = lambda t, n: re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:n].strip("-")
    return f"{date.today()}-{s(job['company'], 24)}-{(job.get('country_code') or 'xx').lower()}-{s(job['title'], 40)}"


def _visa_notes(cc: str, rule: dict) -> list[str]:
    notes = ["签证题按 answers.yml 答（她 10-30 定：以拿到面试为准）；进面试后主动说明实际走哪条路。"]
    if rule.get("employer_action") and rule.get("sponsor_needed"):
        notes.append(f"⚠️ {cc}：公司实际要办 {rule['employer_action']}（实习许可，不是 sponsor licence）——面试时说明。")
    elif rule.get("self_action"):
        notes.append(f"{cc}：公司不用担保，你自己办 {rule['self_action']}。")
    return notes


def template_pdf(rd: Path, tpl: str, cc: str, who: str = "CV") -> Path | None:
    """The shared PDF of template `tpl` for country `cc`, rendered when missing or older than the template."""
    md = rd / tpl
    name = Path(tpl).parent.name.split("-")[-1].upper()  # generic/2026-10-v10-swe -> SWE
    out = rd / TEMPLATES
    pdf = out / f"{who}-Resume-{name}-{cc.upper()}.pdf"
    if pdf.exists() and pdf.stat().st_mtime >= md.stat().st_mtime:
        return pdf
    if not (rd / "profiles" / f"{cc.lower()}.yml").exists():
        return None
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "render.py", str(md.resolve()), "--country", cc.lower(), "--out", str(out.resolve()),
                    "--pdf-name", pdf.stem], cwd=rd, capture_output=True, text=True)
    return pdf if pdf.exists() else None


def answers_md(job: dict, answers: dict, rule: dict | None, cv: str = "") -> str:
    cc = job.get("country_code") or ""
    steps = plan([{"label": q, "type": "input_text"} for q in QUESTIONS], answers, rule).steps
    for s in steps:
        if s.label.startswith("Will you now"):
            s.value = "No"  # the user's rule (answers.yml)
        s.value = s.value.split(" | ")[0]  # option lists: the first is what to pick
    url = job.get("apply_url") or job.get("url") or ""
    ats = job.get("ats") or "other"
    lines = [f"# {job['company']} — {job['title']}", "",
             f"- 链接：{url}", f"- 表单：{ats}" + (f" · {REGISTER[ats]}" if ats in REGISTER else ""),
             f"- 国家：{cc} · 简历：`{cv or '模板'}`（自动投，未改）", ""]
    dur = [m.group(0).strip()[:160] for m in _DURATION.finditer(job.get("jd") or "")][:2]
    if dur:
        lines += ["## 时长（JD 原文）", *[f"- {d.lstrip('-• ')}" for d in dur], ""]
    lines += ["## 常见题", "", "| 问题 | 答 |", "|---|---|"]
    lines += [f"| {s.label} | {s.value if s.value != 'NEEDS_HUMAN' else '（你决定）'} |" for s in steps]
    lines += ["", "## 签证", *[f"- {n}" for n in _visa_notes(cc, rule or {})], "",
              "## 开放题", "", "表单里有开放题（Why us 等）的话，把原题发给我，我按 JD + base.md 起草后补在这里。", ""]
    return "\n".join(lines)


def jd_md(job: dict) -> str:
    url = job.get("apply_url") or job.get("url") or ""
    body = job.get("jd") or f"（JD 没抓到——打开链接看：{url}）"
    return f"# {job['company']} — {job['title']}\n\n{job.get('location') or ''}\n{url}\n\n{body}\n"


def prepare(vault, store) -> list[str]:
    policy = vault.yaml("policy.yml", {}) or {}
    countries = (vault.yaml("work_authorization.yml", {}) or {}).get("countries", {})
    answers = vault.answers()
    rd = resume_dir(vault.root, policy)
    tpls = (policy.get("apply", {}) or {}).get("cv_templates") or {}
    prof = answers.get("profile", {})
    who = re.sub(r"[^A-Za-z0-9]+", "-", f"{prof.get('first_name', '')} {prof.get('last_name', '')}").strip("-") or "CV"
    log = []
    for job in store.all():
        if job.get("decision") != "auto" or job["status"] not in OPEN or job.get("app_dir"):
            continue
        tpl = tpls.get(job.get("role") or "") or tpls.get("swe")
        cc = job.get("country_code") or ""
        pdf = template_pdf(rd, tpl, cc, who)
        if not pdf:
            log.append(f"✗ {job['company']} — {job['title'][:50]}: no CV for {tpl} / {cc or '??'}")
            continue
        rel, n = f"applications/{slug(job)}", 2
        while (rd / rel).exists():  # same company, titles that only differ after 40 characters
            rel, n = f"applications/{slug(job)}-{n}", n + 1
        d = rd / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "jd.md").write_text(jd_md(job), encoding="utf-8")
        cv = str(pdf.relative_to(rd))
        (d / "answers.md").write_text(answers_md(job, answers, countries.get(cc), cv), encoding="utf-8")
        store.update(job["id"], app_dir=rel)
        log.append(f"✓ {job['company']} — {job['title'][:50]} → {rel}")
    return log
