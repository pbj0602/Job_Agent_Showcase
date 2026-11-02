"""Find which ATS (and board slug) each candidate company uses, by trying the public feeds.

Run where job sites are reachable (GitHub Actions):

    python scripts/ats_probe.py vault/companies_candidates.yml --out state/ats_probe.yml

Each candidate is a name plus optional slug guesses. Every (ats, slug) pair is tried; a feed
that answers with at least one posting is a hit. The output lists hits as companies.yml
entries with total and internship counts, so the useful ones can be copied over.
"""
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from job_agent.sources import ats  # noqa: E402

TRY = ["greenhouse", "lever", "ashby", "teamtailor", "smartrecruiters", "recruitee"]


def guesses(c: dict) -> list[str]:
    base = c["name"].lower()
    auto = {re.sub(r"[^a-z0-9]", "", base), re.sub(r"[^a-z0-9]+", "-", base).strip("-")}
    return list(dict.fromkeys([*(c.get("slugs") or []), *sorted(auto)]))


def probe(name: str, kind: str, slug: str):
    try:
        jobs = ats.scan_company({"ats": kind, "slug": slug, "name": name}, interns_only=False)
    except Exception:
        return None
    if not jobs:
        return None
    interns = [j for j in jobs if ats.INTERN.search(j["title"])]
    return {"name": name, "ats": kind, "slug": slug, "jobs": len(jobs), "interns": len(interns),
            "sample": [j["title"] for j in interns[:3]]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--out", default="state/ats_probe.yml")
    a = ap.parse_args()
    cands = yaml.safe_load(Path(a.candidates).read_text()) or []
    tasks = [(c["name"], k, s) for c in cands for s in guesses(c) for k in TRY]
    with ThreadPoolExecutor(16) as pool:
        hits = [h for h in pool.map(lambda t: probe(*t), tasks) if h]
    best: dict[str, dict] = {}
    for h in hits:  # one entry per company: the feed with the most postings
        if h["name"] not in best or h["jobs"] > best[h["name"]]["jobs"]:
            best[h["name"]] = h
    found = sorted(best.values(), key=lambda h: (-h["interns"], h["name"]))
    missing = [c["name"] for c in cands if c["name"] not in best]
    Path(a.out).write_text(yaml.safe_dump({"found": found, "not_found": missing}, allow_unicode=True, sort_keys=False))
    for h in found:
        print(f"{h['name']:<24} {h['ats']:<16} {h['slug']:<24} jobs={h['jobs']:<4} interns={h['interns']} {h['sample']}")
    print(f"\n{len(found)} found, {len(missing)} not found: {', '.join(missing)}")


if __name__ == "__main__":
    main()
