"""Which role pack fits a job. Roles are data (packs/roles/*.yml), not code: add a YAML file
to support a new career direction."""
from __future__ import annotations

import re

from ..text import fold


def classify(title: str, jd: str, packs: dict[str, dict]) -> tuple[str, float, dict[str, float]]:
    """(best role, its score, all scores). Title hits weigh 3x description hits."""
    t, d = fold(title), fold(jd)[:6000]
    scores: dict[str, float] = {}
    titled: set[str] = set()
    for name, pack in packs.items():
        s = 0.0
        for kw in pack.get("title_keywords", []):
            if re.search(rf"(?<!\w){re.escape(fold(kw))}(?!\w)", t):
                s += 3
                titled.add(name)
        for kw in pack.get("jd_keywords", []):
            if re.search(rf"(?<!\w){re.escape(fold(kw))}(?!\w)", d):
                s += 1
        scores[name] = s
    # The title says what the job is; the JD only breaks ties ("Compliance Intern" with a
    # project-heavy description is still compliance).
    pool = {k: v for k, v in scores.items() if k in titled} or scores
    best = max(pool, key=pool.get) if pool else "unknown"
    if not scores or scores[best] == 0:
        return "unknown", 0.0, scores
    return best, scores[best], scores
