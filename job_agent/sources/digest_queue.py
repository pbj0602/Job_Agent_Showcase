"""Import job records collected elsewhere into the job database.

Any collector (a scheduled job, a scraper you run yourself) can feed the agent by writing
queue/<date>/<id>.json, one posting per file with the full JD. This module pulls those in.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..geo import country_of

# The location text wins over the digest's country name, which comes from feed codes that
# are sometimes wrong ("Aarhus, Denmark" filed under Germany).

NAME_TO_CODE = {"Sweden": "SE", "Netherlands": "NL", "Ireland": "IE", "Germany": "DE",
                "Luxembourg": "LU", "United Kingdom": "UK"}


def read(queue_dir: Path) -> list[dict]:
    out = []
    for p in sorted(Path(queue_dir).glob("*/*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "id": r["id"], "company": r.get("company", ""), "title": r.get("title", ""),
            "location": r.get("location", ""), "country": r.get("country", ""),
            "country_code": country_of(r.get("location", "")) or NAME_TO_CODE.get(r.get("country", "")) or "",
            "url": r.get("listing_url", ""), "apply_url": r.get("apply_url", ""),
            "ats": r.get("apply_ats") or r.get("ats", ""), "source": "digest",
            "first_seen": r.get("date"), "jd": r.get("jd", ""), "jd_source": r.get("jd_source", ""),
            "questions": r.get("questions"), "fetch_error": r.get("error"),
        })
    return out
