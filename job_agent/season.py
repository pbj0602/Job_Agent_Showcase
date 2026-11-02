"""When does the internship run? summer / off (starts outside summer, too long, part-time) / unknown.

Each verdict comes with the sentence it was read from. Off-cycle evidence wins over a mention of
"summer" (a 6-month internship starting in summer still runs into the autumn term). Ranges count
by their lower end: "3-6 months" fits a summer, "6 months" does not.
"""
from __future__ import annotations

import re

MAX_WEEKS = 16  # June to mid-September at most

_MONTHS_OFF = (r"jan(uary|uar)?|feb(ruary|ruar)?|m(ar(ch)?|ärz|aart)|apr(il)?|sep(tember)?|o[ck]t(ober)?|nov(ember)?"
               r"|de[cz](ember)?|januari|februari|oktober")
_START_OFF = re.compile(
    rf"\b(start(s|ing)?( date)?( is| in| on| from| between)?|begin(s|ning)?( in)?|from|as of|ab( dem)?|vanaf|per|commencing)"
    rf"\s+(the\s+)?(\d{{1,2}}(st|nd|rd|th)?\.?\s+(of\s+)?)?({_MONTHS_OFF})\b\.?\s*(/\s*\w+\s*)?(20)?(26|27)?", re.I)
_MONTH_YEAR_OFF = re.compile(rf"\b({_MONTHS_OFF})\.?\s+(20)?(26|27)\b[^.\n]{{0,40}}\b(for|für|voor)\b", re.I)
_ASAP = re.compile(r"\b(start(ing|s)?( date)?:?\s+(as soon as possible|asap|immediately)|available (from )?(asap|immediately)"
                   r"|ab sofort|immediate start|zum nächstmöglichen)", re.I)
_LONG = re.compile(r"\b(placement year|year[- ]in[- ]industry|industrial placement|sandwich|year[- ]long|"
                   r"one[- ]year (internship|placement|industrial)|twelve[- ]month|six[- ]month|sechs monate|zes maanden)\b", re.I)
_DURATION = re.compile(
    r"\b(\d{1,2})\s*(?:\+\s*)?(?:(?:-|–|to|or|bis|tot|oder|of)\s*(\d{1,2})\s*)?(months?|monate?n?|maanden|mois|månader|weeks?|wochen|weken)\b", re.I)
_PART_TIME = re.compile(r"\b(part[- ]time|teilzeit|deltid|(\d{1,2})\s*(hours?|stunden|std\.?|h)\s*(per|/|a|pro|in der)\s*(week|woche))\b", re.I)
_SUMMER = re.compile(r"\b(summer|sommar(praktik|jobb)?|sommer(praktikum)?|zomer(stage)?|été)\b"
                     r"|\b(june|july|juni|juli)\b[^.\n]{0,40}\b(20)?27\b|\b(may|june|july)\b[^.\n]{0,15}(-|–|to|until)[^.\n]{0,12}\b(august|september)\b", re.I)
_NOT_PERIOD = re.compile(r"retain|your data|personal data|experience|ago|cool|re-?apply|benefit|per month|monthly|salary|after the|within|"
                         r"notice|probation|older than|last \d|past \d|every|months? of|offer|reserve list|held for|purchase|interest|loan|"
                         r"scheme|jobs\b|\bftc\b|senior", re.I)


def _sentence(text: str, m: re.Match) -> str:
    a = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    b = min([i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i != -1] or [len(text)])
    return text[a:b].strip(" -•*\t")[:160]


def _weeks(n: int, unit: str) -> int:
    return n * 4 if unit.lower().startswith(("mon", "maan", "mois", "mån")) else n


def season(title: str, jd: str) -> tuple[str, str]:
    """('summer' | 'off' | 'unknown', evidence)."""
    text = f"{title}\n{jd or ''}"
    if _SUMMER.search(title):
        return "summer", title  # the title says so; JD boilerplate does not overrule it
    for rx in (_START_OFF, _MONTH_YEAR_OFF, _ASAP, _LONG):
        for m in rx.finditer(text):
            s = _sentence(text, m)
            if not _NOT_PERIOD.search(s):
                return "off", s
    m = next((m for m in _DURATION.finditer(title) if _weeks(int(m.group(1)), m.group(3)) <= MAX_WEEKS), None)
    if m:
        return "summer", title  # the title promises a short one
    by_sentence: dict[str, list[int]] = {}
    for m in _DURATION.finditer(text):
        s = _sentence(text, m)
        if not _NOT_PERIOD.search(s):
            by_sentence.setdefault(s, []).append(_weeks(int(m.group(1)), m.group(3)))
    for s, weeks in by_sentence.items():
        if min(weeks) > MAX_WEEKS:  # "3 or 12 months": the short option fits
            return "off", s
    fits = next(iter(by_sentence), "")  # a stated length that fits the summer
    for m in _PART_TIME.finditer(text):
        if m.group(2) and int(m.group(2)) >= 32:
            continue
        s = _sentence(text, m)
        if not re.search(r"full[- ]time|vollzeit|or part", s, re.I):
            return "off", s
    m = _SUMMER.search(text)
    if m:
        return "summer", _sentence(text, m)
    return ("summer", fits) if fits else ("unknown", "")
