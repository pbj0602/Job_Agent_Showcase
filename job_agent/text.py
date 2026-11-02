"""Small text helpers shared by sources and enrichers."""
from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser


def fold(text: str) -> str:
    """Lowercase, strip accents: 'München' -> 'munchen'."""
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "tr", "section"}
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(markup: str) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) -> plain text."""
    if "&lt;" in (markup or ""):
        markup = html.unescape(markup)
    p = _Text()
    p.feed(markup or "")
    text = "".join(p.out)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


_SUFFIX = re.compile(
    r"\b(gmbh|ag|se|ab|bv|b\.v\.|nv|inc|ltd|limited|plc|llc|group|holding|holdings|co|kg|sa|sarl"
    r"|uk|europe|international)\b\.?"
)


def company_key(name: str) -> str:
    """Normalise a company name for matching against registers: 'Optiver B.V.' -> 'optiver'."""
    t = fold(name).replace("&", " and ")
    t = _SUFFIX.sub(" ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def slug(*parts: str) -> str:
    s = "-".join(re.sub(r"[^a-z0-9]+", "-", fold(p)).strip("-") for p in parts if p)
    return s[:80].strip("-") or "job"
