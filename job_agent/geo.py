"""Location text -> country code, using the place lists in packs/countries/*.yml."""
from __future__ import annotations

import re
from functools import lru_cache

from .config import load_pack
from .text import fold

# Same-named places elsewhere (kept from the digest, where each one caused a bad match).
EXCLUDE = ["province de luxembourg", "province of luxembourg", "luxembourg province", "luxembourg, belgium",
           "new south wales", "new england", "london, ontario", "london, on, canada", "london, canada"]
_US = re.compile(r",\s*(AL|AK|AZ|AR|CA|CO|CT|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV"
                 r"|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b|united states|\busa\b")


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern]]:
    out = []
    for cc, pack in load_pack("countries").items():
        words = sorted((fold(p) for p in pack.get("places", [])), key=len, reverse=True)
        rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in words) + r")(?![\w-])")
        out.append((pack["code"], rx))
    return out


def country_of(location: str) -> str | None:
    """'Amsterdam, Netherlands' -> 'NL'. The earliest mention wins ('Belfast, Northern Ireland' -> UK)."""
    t = fold(location)
    if not t or _US.search(location or "") or any(x in t for x in EXCLUDE):
        return None
    best = None
    for cc, rx in _patterns():
        m = rx.search(t)
        if m and (best is None or m.start() < best[1] or (m.start() == best[1] and len(m.group()) > best[2])):
            best = (cc, m.start(), len(m.group()))
    return best[0] if best else None


def country_name(cc: str) -> str:
    pack = load_pack("countries").get((cc or "").lower())
    return pack["name"] if pack else cc


def country_rank(order: list[list[str]], cc: str) -> int:
    """Index of the policy `country_order` group holding cc; unlisted countries go last."""
    return next((i for i, group in enumerate(order) if cc in group), len(order))
