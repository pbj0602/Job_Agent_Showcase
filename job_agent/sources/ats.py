"""Public job-board APIs of the common applicant tracking systems.

Reliable and allowed: these are the JSON feeds the companies' own careers pages use,
unauthenticated, one request per company. Configure companies in the vault's
companies.yml:

    - {name: Spotify, ats: lever, slug: spotify}
    - {name: Adyen, ats: greenhouse, slug: adyen}
    - {name: Klarna, ats: teamtailor, slug: klarna}       # https://<slug>.teamtailor.com
"""
from __future__ import annotations

import json
import re
import urllib.request

from ..text import html_to_text

UA = "job-agent/0.1 (+https://github.com/; personal job search, one request per company per day)"

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "teamtailor": "https://{slug}.teamtailor.com/jobs.rss",  # RSS: Teamtailor has no public JSON feed
}

INTERN = re.compile(r"\b(intern(ship)?s?|trainee|praktik(ant)?|stage|stagiair|werkstudent|summer|"
                    r"student|graduate|thesis|exjobb|masterarbeit|placement)\b", re.I)


def fetch_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return body if url.endswith(".rss") else json.loads(body)


def _rss_items(xml: str) -> list[dict]:
    """Teamtailor's jobs.rss: one <item> per job. Location sits in a namespaced tag whose name
    contains 'location' or 'city', so match on the local name rather than a fixed namespace."""
    import xml.etree.ElementTree as ET
    items = []
    for it in ET.fromstring(xml).iter("item"):
        row = {"locations": []}
        for el in it.iter():
            tag = el.tag.split("}")[-1].lower()
            text = (el.text or "").strip()
            if tag in ("title", "link", "description") and tag not in row:
                row[tag] = text
            elif ("location" in tag or tag == "city") and text:
                row["locations"].append(text)
        items.append(row)
    return items


def parse(ats: str, company: str, payload) -> list[dict]:
    """ATS payload -> listings. Unknown keys are ignored so feed changes degrade, not crash."""
    out = []
    if ats == "greenhouse":
        for j in payload.get("jobs", []):
            out.append(dict(title=j.get("title", ""), location=(j.get("location") or {}).get("name", ""),
                            url=j.get("absolute_url", ""), jd=html_to_text(j.get("content", ""))))
    elif ats == "lever":
        for j in payload if isinstance(payload, list) else []:
            cat = j.get("categories") or {}
            locs = cat.get("allLocations") or [cat.get("location", "")]
            jd = j.get("descriptionPlain") or html_to_text(j.get("description", ""))
            for lst in j.get("lists") or []:
                jd += "\n\n" + lst.get("text", "") + "\n" + html_to_text(lst.get("content", ""))
            out.append(dict(title=j.get("text", ""), location="; ".join(l for l in locs if l),
                            url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl", ""), jd=jd.strip()))
    elif ats == "ashby":
        for j in payload.get("jobs", []):
            locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
            out.append(dict(title=j.get("title", ""), location="; ".join(l for l in locs if l),
                            url=j.get("jobUrl", ""), apply_url=j.get("applyUrl", ""),
                            jd=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))))
    elif ats == "smartrecruiters":
        for j in payload.get("content", []):
            loc = j.get("location") or {}
            out.append(dict(title=j.get("name", ""),
                            location=", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                            url=f"https://jobs.smartrecruiters.com/{company}/{j.get('id', '')}", jd=""))
    elif ats == "recruitee":
        for j in payload.get("offers", []):
            out.append(dict(title=j.get("title", ""),
                            location=", ".join(x for x in (j.get("city"), j.get("country")) if x),
                            url=j.get("careers_url", ""),
                            jd=html_to_text((j.get("description") or "") + (j.get("requirements") or ""))))
    elif ats == "workable":
        for j in payload.get("jobs", []):
            out.append(dict(title=j.get("title", ""),
                            location=", ".join(x for x in (j.get("city"), j.get("country")) if x),
                            url=j.get("url") or j.get("shortlink", ""), jd=""))
    elif ats == "teamtailor":
        for j in _rss_items(payload):
            out.append(dict(title=j.get("title", ""), location="; ".join(dict.fromkeys(j["locations"])),
                            url=j.get("link", ""), jd=html_to_text(j.get("description", ""))))
    else:
        raise ValueError(f"unsupported ATS {ats!r}")
    for o in out:
        o.update(company=company, ats=ats, source=f"ats:{ats}", jd_source="ats" if o.get("jd") else "none")
    return out


def scan_company(entry: dict, fetch=fetch_json, interns_only: bool = True) -> list[dict]:
    ats, slug, name = entry["ats"], entry["slug"], entry.get("name") or entry["slug"]
    payload = fetch(ENDPOINTS[ats].format(slug=slug))
    jobs = parse(ats, name, payload)
    return [j for j in jobs if INTERN.search(j["title"])] if interns_only else jobs
