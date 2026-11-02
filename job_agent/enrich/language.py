"""Does the JD *require* a local language (not just like it)? Ported from the digest's jd.py."""
from __future__ import annotations

import re

from ..text import fold

LANGS = {
    "German": (r"german|deutsch", "und der die das mit fur wir sie ist ein eine zu von auf bei ihre"),
    "Swedish": (r"swedish|svenska", "och att det som en ett ar for med pa vi du av till har"),
    "Dutch": (r"dutch|nederlands", "en het de van een je wij jij voor met zijn op bij ons"),
    "French": (r"french|francais", "et le la les des une est pour vous nous avec dans sur"),
    "Danish": (r"danish|dansk", "og at det som en er til med pa vi du af har for"),
}
_PLUS = re.compile(r"plus|advantage|advantageous|nice to have|bonus|preferred|desirable|beneficial"
                   r"|preferabl|von vorteil|wunschenswert|meriterande|ein plus|pluspunt|un atout")
_MUST = re.compile(r"fluent|fluency|native|c1|c2|required|requirement|must|mandatory|excellent"
                   r"|very good|proficien|business level|professional level|fliessend"
                   r"|verhandlungssicher|sehr gut|sicher|flytande|vloeiend|uitstekend|courant")
_EN_WORDS = set("and the to of a in for with you we our is are on as be will your this".split())
_CONTEXT = re.compile(r"language|speak|spoken|written|fluen|proficien|native|level|skill|kenntnis"
                      r"|sprach|kommuni|communicat|command of|knowledge of|\b[abc][12]\b|svenska|deutsch")


def language_required(text: str, written_check: bool = True) -> list[tuple[str, str]]:
    """[(language, evidence)] for languages the JD requires.

    written_check: a JD written in the language requires it. Turn off for whole-page
    text, where a German cookie banner says nothing about the job.
    """
    t = fold(text)
    words = re.findall(r"[a-z]+", t)
    found: list[tuple[str, str]] = []
    counts = {lang: sum(w in set(stop.split()) for w in words) for lang, (_, stop) in LANGS.items()}
    top = max(counts, key=counts.get)
    if written_check and len(words) > 80 and counts[top] > sum(w in _EN_WORDS for w in words):
        found.append((top, "JD is written in " + top))
    for lang, (name_re, _) in LANGS.items():
        if any(l == lang for l, _ in found):
            continue
        for sentence in re.split(r"(?<=[.!?;\n])\s+|\n- ", t):
            if not re.search(rf"(?<!\w)({name_re})(?!\w)", sentence):
                continue
            if not _CONTEXT.search(sentence) or re.search(r"and/or|und/oder|or english|oder englisch", sentence):
                continue
            clause = next(c for c in re.split(r"[,()]", sentence) if re.search(rf"(?<!\w)({name_re})", c))
            if _PLUS.search(clause):
                continue
            if _MUST.search(sentence):
                found.append((lang, sentence.strip()[:160]))
                break
    return found
