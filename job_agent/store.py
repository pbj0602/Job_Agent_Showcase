"""The job database: one SQLite file in the vault, one row per job, every status change logged.

Status flow (career-ops style, plus a human gate before anything is sent):

    discovered ─route→ awaiting_confirm ─👍→ approved ─tailor→ tailored ─apply→ applied
                   ├→ approved (small company, auto)                         ├→ oa
                   ├→ manual   (needs a human: language, visa unclear, ...)   ├→ interview
                   └→ skipped  (hard no: language required, no sponsorship)  ├→ offer
                                                                              └→ rejected
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from .text import fold

STATES = (
    "discovered", "awaiting_confirm", "approved", "manual", "skipped", "thesis",
    "tailored", "applied", "oa", "interview", "offer", "rejected", "withdrawn",
)
TRANSITIONS = {
    "discovered": {"awaiting_confirm", "approved", "manual", "skipped", "thesis"},
    "awaiting_confirm": {"approved", "skipped", "manual"},
    "manual": {"approved", "skipped", "applied"},
    "approved": {"tailored", "manual", "skipped"},
    "tailored": {"applied", "approved", "manual", "skipped"},  # approved = redo the CV
    "applied": {"oa", "interview", "offer", "rejected", "withdrawn"},
    "oa": {"interview", "rejected", "withdrawn"},
    "interview": {"interview", "offer", "rejected", "withdrawn"},
    "offer": {"withdrawn"},
    "skipped": {"approved", "manual"},  # a human can always overrule a skip
    "thesis": set(),
    "rejected": set(),
    "withdrawn": set(),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url_key TEXT,
    title_key TEXT,
    company TEXT, title TEXT, location TEXT, country TEXT,
    url TEXT, apply_url TEXT, ats TEXT, source TEXT,
    first_seen TEXT, updated_at TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    route_reason TEXT,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS jobs_url ON jobs(url_key);
CREATE INDEX IF NOT EXISTS jobs_title ON jobs(title_key);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS events (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL, at TEXT NOT NULL,
    from_status TEXT, to_status TEXT NOT NULL,
    actor TEXT NOT NULL, note TEXT
);
"""

_TRACKING = re.compile(r"^(utm_|gh_src|gh_jid$|source$|ref$|lever-|src$)")
_TAGS = re.compile(r"\((m|f|w|d|x|all genders?|[mfwdx]/[mfwdx](/[mfwdx])?)\)|\bm/w/d\b|\bm/f/d\b", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def url_key(url: str) -> str:
    """URL without scheme, www, trailing slash and tracking parameters."""
    if not url:
        return ""
    u = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if not _TRACKING.match(k.lower())]
    host = u.netloc.lower().removeprefix("www.")
    return f"{host}{u.path.rstrip('/')}" + (f"?{urllib.parse.urlencode(sorted(q))}" if q else "")


def title_key(company: str, title: str, country: str) -> str:
    t = _TAGS.sub(" ", title or "")
    return "|".join(re.sub(r"[^a-z0-9]+", " ", fold(x)).strip() for x in (company, t, country))


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        # TRUNCATE instead of the default DELETE journal: just as crash-safe, and works on
        # synced or sandboxed folders where deleting files is not allowed.
        self.db.execute("PRAGMA journal_mode=TRUNCATE")
        self.db.executescript(SCHEMA)

    # ---- reading ----

    def get(self, job_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row(r) if r else None

    def find_duplicate(self, job: dict) -> str | None:
        uk = url_key(job.get("url", ""))
        tk = title_key(job.get("company", ""), job.get("title", ""), job.get("country", ""))
        r = self.db.execute(
            "SELECT id FROM jobs WHERE (url_key = ? AND url_key != '') OR title_key = ? LIMIT 1", (uk, tk)
        ).fetchone()
        return r["id"] if r else None

    def by_status(self, *statuses: str) -> list[dict]:
        q = f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY first_seen"
        return [self._row(r) for r in self.db.execute(q, statuses)]

    def all(self) -> list[dict]:
        return [self._row(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY first_seen")]

    def events(self, job_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM events WHERE job_id = ? ORDER BY n", (job_id,))]

    def counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.db.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d.update(json.loads(d.pop("data") or "{}"))
        return d

    # ---- writing ----

    CORE = ("company", "title", "location", "country", "url", "apply_url", "ats", "source")

    def add(self, job: dict, actor: str = "scan") -> tuple[str, bool]:
        """Insert a job unless it is already known. Returns (id, is_new)."""
        dup = self.find_duplicate(job)
        if dup:
            return dup, False
        jid = job["id"]
        extra = {k: v for k, v in job.items() if k not in self.CORE and k not in ("id", "status")}
        ts = now()
        self.db.execute(
            "INSERT INTO jobs (id, url_key, title_key, company, title, location, country, url, apply_url,"
            " ats, source, first_seen, updated_at, status, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, url_key(job.get("url", "")),
             title_key(job.get("company", ""), job.get("title", ""), job.get("country", "")),
             *(job.get(k, "") for k in self.CORE), job.get("first_seen", ts), ts,
             job.get("status", "discovered"), json.dumps(extra, ensure_ascii=False)),
        )
        self.db.execute("INSERT INTO events (job_id, at, to_status, actor) VALUES (?,?,?,?)",
                        (jid, ts, job.get("status", "discovered"), actor))
        self.db.commit()
        return jid, True

    def update(self, job_id: str, **fields) -> None:
        cur = self.get(job_id)
        if cur is None:
            raise KeyError(job_id)
        core = {k: fields.pop(k) for k in list(fields) if k in self.CORE or k == "route_reason"}
        data = {k: v for k, v in cur.items()
                if k not in self.CORE and k not in ("id", "url_key", "title_key", "first_seen",
                                                    "updated_at", "status", "route_reason")}
        data.update(fields)
        sets = ", ".join(f"{k} = ?" for k in core)
        self.db.execute(
            f"UPDATE jobs SET {sets + ', ' if sets else ''}data = ?, updated_at = ? WHERE id = ?",
            (*core.values(), json.dumps(data, ensure_ascii=False), now(), job_id),
        )
        self.db.commit()

    def move(self, job_id: str, to: str, actor: str, note: str = "", force: bool = False) -> dict:
        """Change status, enforcing TRANSITIONS unless force (a human correcting history)."""
        if to not in STATES:
            raise ValueError(f"unknown status {to!r}")
        cur = self.get(job_id)
        if cur is None:
            raise KeyError(job_id)
        frm = cur["status"]
        if frm == to and to != "interview":
            return cur
        if not force and to not in TRANSITIONS[frm]:
            raise ValueError(f"{job_id}: {frm} → {to} is not allowed")
        ts = now()
        self.db.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (to, ts, job_id))
        self.db.execute("INSERT INTO events (job_id, at, from_status, to_status, actor, note) VALUES (?,?,?,?,?,?)",
                        (job_id, ts, frm, to, actor, note))
        self.db.commit()
        return self.get(job_id)

    # ---- export ----

    EXPORT_COLS = ("id", "first_seen", "status", "company", "title", "country", "role", "route_reason",
                   "visa_verdict", "visa_evidence", "apply_url", "cv_dir")

    def export_csv(self, path: Path) -> int:
        rows = self.all()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.EXPORT_COLS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in self.EXPORT_COLS})
        return len(rows)
