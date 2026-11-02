#!/usr/bin/env python3
"""Block personal data from reaching this (public) repository.

Two lists, both kept out of git (private/ is ignored; CI gets them from Secrets):
  * PII list -- private/pii_denylist.txt or $PII_DENYLIST: e-mail, phones, LinkedIn, address.
    Checked in EVERY tracked file, vault/ and state/ included: contact details never enter git.
  * engine list -- private/leak_denylist.txt, $JOB_VAULT/leak_denylist.txt or $LEAK_DENYLIST:
    names, employers, amounts. Checked only where the public showcase will copy from.
Also, outside the private areas:
  * generic patterns: phone numbers, e-mail addresses outside example.com/.org,
    and any path that looks like a vault file (base.md with real content, .env, jobs.db).

Run by the pre-commit hook (scripts/install_hooks.sh) and in CI. Exit 1 on any hit.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_EMAIL = re.compile(r"@(example\.(com|org)|users\.noreply\.github\.com|anthropic\.com)$", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<![\w.])\+\d{1,3}[ -]?\(?\d{1,4}\)?([ -]?\d{2,4}){2,4}(?![\w.])")
DEMO_PHONE = re.compile(r"\+46 70 000 00 00")
FORBIDDEN_FILES = re.compile(r"(^|/)(\.env|jobs\.db|leak_denylist\.txt|pii_denylist\.txt|contact\.yml)$|^private/")
SKIP = re.compile(r"(^|/)(\.git|__pycache__|\.pytest_cache)/|\.(png|jpg|pdf|db)$")
# vault/, state/, .claude/ (private tooling) and CLAUDE.md hold the candidate's own data. They are never
# copied to the public showcase, so the scan covers everything except them.
PRIVATE_DIRS = re.compile(r"^((vault|state|\.claude)/|CLAUDE\.md$)")


def files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [f for f in out.splitlines() if f]
    except Exception:
        return [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]


def _terms(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if len(line) >= 3:
            out.append(line.lower())
    return out


def _load(env: str, *files: Path) -> list[str]:
    if os.environ.get(env):
        return _terms(os.environ[env])
    for f in files:
        if f.exists():
            return _terms(f.read_text(encoding="utf-8"))
    return []


def denylist() -> list[str]:
    vault = os.environ.get("JOB_VAULT")
    extra = [Path(vault).expanduser() / "leak_denylist.txt"] if vault else []
    return _load("LEAK_DENYLIST", ROOT / "private" / "leak_denylist.txt", *extra)


def pii_list() -> list[str]:
    return _load("PII_DENYLIST", ROOT / "private" / "pii_denylist.txt")


def scan(paths: list[str], terms: list[str], pii: list[str] | None = None) -> list[str]:
    hits = []
    for rel in paths:
        if SKIP.search(rel):
            continue
        if pii:
            try:
                low = (ROOT / rel).read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
                low = ""
            for t in pii:
                if t in low:
                    hits.append(f"{rel}: contains personal contact data (line {low[:low.index(t)].count(chr(10)) + 1})")
        if PRIVATE_DIRS.match(rel):
            continue
        if FORBIDDEN_FILES.search(rel):
            hits.append(f"{rel}: this file must never be in the public repo")
            continue
        p = ROOT / rel
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        low = text.lower()
        for t in terms:
            if t in low:
                hits.append(f"{rel}: contains a denylisted term (line {low[:low.index(t)].count(chr(10)) + 1})")
        if rel.startswith("tests/fixtures/"):
            continue  # public job ads quote employers' HR addresses; the denylist still applies
        for m in EMAIL.finditer(text):
            if not ALLOWED_EMAIL.search(m.group()) and not m.group().startswith("noreply@"):
                hits.append(f"{rel}: e-mail address {m.group()!r}")
        for m in PHONE.finditer(text):
            if not DEMO_PHONE.fullmatch(m.group().strip()):
                hits.append(f"{rel}: phone-number-like string {m.group()!r}")
    return hits


def main() -> int:
    terms, pii = denylist(), pii_list()
    if not (terms and pii):
        print(f"leak_scan: missing list(s) — engine: {len(terms)} terms, PII: {len(pii)} terms "
              "(private/*.txt locally, LEAK_DENYLIST / PII_DENYLIST secrets in CI)", file=sys.stderr)
    hits = scan(files(), terms, pii)
    for h in hits:
        print("LEAK", h)
    if hits:
        print(f"leak_scan: {len(hits)} problem(s) — nothing personal may be committed here.")
        return 1
    print(f"leak_scan: clean ({len(terms)} engine + {len(pii)} PII terms checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
