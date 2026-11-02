import json
import sys
from pathlib import Path

from job_agent.sources import ats

GREENHOUSE = {"jobs": [
    {"title": "Software Engineer Intern 2027", "location": {"name": "Amsterdam"},
     "absolute_url": "https://job-boards.greenhouse.io/x/jobs/1", "content": "&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;"},
    {"title": "Senior Engineer", "location": {"name": "Amsterdam"}, "absolute_url": "u2", "content": ""},
]}
LEVER = [{"text": "Product Intern", "categories": {"location": "Stockholm", "allLocations": ["Stockholm", "Remote"]},
          "hostedUrl": "https://jobs.lever.co/x/1", "applyUrl": "https://jobs.lever.co/x/1/apply",
          "descriptionPlain": "Own the roadmap.", "lists": [{"text": "You have", "content": "<li>SQL</li>"}]}]


def test_parsers_and_intern_filter():
    jobs = ats.scan_company({"name": "X", "ats": "greenhouse", "slug": "x"}, fetch=lambda u: GREENHOUSE)
    assert [j["title"] for j in jobs] == ["Software Engineer Intern 2027"]
    assert jobs[0]["jd"] == "Build & ship"
    lv = ats.parse("lever", "X", LEVER)[0]
    assert lv["location"] == "Stockholm; Remote" and "SQL" in lv["jd"] and lv["apply_url"].endswith("/apply")


def test_cli_end_to_end(vault, samples, tmp_path, capsys):
    from job_agent.cli import main
    q = tmp_path / "queue" / "2026-10-17"
    q.mkdir(parents=True)
    for r in samples:
        (q / f"{r['id']}.json").write_text(json.dumps(r))
    main(["--vault", str(vault.root), "ingest", "--queue", str(tmp_path / "queue")])
    main(["--vault", str(vault.root), "ingest", "--queue", str(tmp_path / "queue")])  # idempotent
    main(["--vault", str(vault.root), "route"])
    main(["--vault", str(vault.root), "export", str(tmp_path / "all.csv")])
    out = capsys.readouterr().out
    assert f"ingest: {len(samples)} new" in out and "ingest: 0 new" in out
    assert "skipped" in out  # the three UK JDs that refuse sponsorship
    import csv
    rows = list(csv.DictReader(open(tmp_path / "all.csv", encoding="utf-8-sig")))
    assert len(rows) == len(samples) and all(r["status"] for r in rows)


def test_leak_scan_catches_personal_data(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import leak_scan
    phone, email = "+46 76 " + "123 45 67", "jane.doe" + "@" + "gmail.com"  # split so this file passes the scan
    (tmp_path / "a.md").write_text(f"Call me at {phone} or {email}. Works at Acme Widgets.")
    (tmp_path / "b.md").write_text("Demo: alex.morgan@example.com, +46 70 000 00 00")
    monkeypatch.setattr(leak_scan, "ROOT", tmp_path)
    hits = leak_scan.scan(["a.md", "b.md", ".env"], ["acme widgets"])
    assert len([h for h in hits if h.startswith("a.md")]) == 3
    assert not [h for h in hits if h.startswith("b.md")]
    assert any(h.startswith(".env") for h in hits)


TEAMTAILOR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations"><channel><title>Jobs</title>
<item><title>Summer Internship 2027</title><link>https://x.teamtailor.com/jobs/1-summer</link>
<description>&lt;p&gt;Build things&lt;/p&gt;</description>
<tt:locations><tt:location><tt:city>Stockholm</tt:city></tt:location></tt:locations></item>
<item><title>Senior Backend Engineer</title><link>https://x.teamtailor.com/jobs/2</link><description></description></item>
</channel></rss>"""


def test_teamtailor_rss():
    jobs = ats.scan_company({"ats": "teamtailor", "slug": "x", "name": "X"}, fetch=lambda url: TEAMTAILOR_RSS)
    assert [j["title"] for j in jobs] == ["Summer Internship 2027"]  # interns only
    assert jobs[0]["location"] == "Stockholm" and jobs[0]["url"].endswith("1-summer")
    assert "Build things" in jobs[0]["jd"]
