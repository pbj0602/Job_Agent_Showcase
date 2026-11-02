import pytest

from job_agent.store import title_key, url_key


def job(**kw):
    base = dict(id="j1", company="Adyen", title="Software Engineer Intern (m/f/d)", country="NL",
                url="https://job-boards.greenhouse.io/adyen/jobs/123?utm_source=x&gh_src=y")
    base.update(kw)
    return base


def test_url_key_drops_tracking_and_www():
    assert url_key("https://www.example.com/jobs/1/?utm_source=li&ref=abc") == "example.com/jobs/1"
    assert url_key("https://x.io/a?id=5&utm_medium=z") == "x.io/a?id=5"


def test_title_key_ignores_gender_tags_and_case():
    assert title_key("Adyen", "Software Engineer Intern (m/f/d)", "NL") == title_key("ADYEN", "software engineer intern", "nl")


def test_dedupe_by_url_and_by_title(store):
    assert store.add(job()) == ("j1", True)
    assert store.add(job(id="j2", url="https://job-boards.greenhouse.io/adyen/jobs/123")) == ("j1", False)
    assert store.add(job(id="j3", url="https://other.site/x")) == ("j1", False)  # same company/title/country
    assert store.add(job(id="j4", title="Data Intern", url="https://other.site/y"))[1] is True


def test_transitions_enforced_and_logged(store):
    store.add(job())
    store.move("j1", "awaiting_confirm", actor="route")
    with pytest.raises(ValueError):
        store.move("j1", "offer", actor="x")
    store.move("j1", "approved", actor="telegram")
    store.move("j1", "offer", actor="human", force=True)  # humans may correct history
    assert [e["to_status"] for e in store.events("j1")] == ["discovered", "awaiting_confirm", "approved", "offer"]


def test_update_keeps_extra_fields(store, tmp_path):
    store.add(job(jd="long text", role="swe"))
    store.update("j1", visa_verdict="likely", route_reason="big")
    j = store.get("j1")
    assert (j["jd"], j["role"], j["visa_verdict"], j["route_reason"]) == ("long text", "swe", "likely", "big")
    assert store.export_csv(tmp_path / "out.csv") == 1


def test_tracker_round_trip(store, tmp_path):
    from openpyxl import load_workbook

    from job_agent import tracker
    for i, (cc, status) in enumerate([("UK", "approved"), ("SE", "manual"), ("DE", "approved")]):
        store.add(dict(id=f"j{i}", company=f"Co{i}", title="SWE Intern", url=f"https://x/{i}", country_code=cc,
                       status=status))
    store.add(dict(id="done", company="Old", title="SWE Intern", url="https://x/d", status="applied"))
    f = tmp_path / "t.xlsx"
    assert tracker.export(store, f, [["SE"], ["DE"], ["UK"]]) == 4
    wb = load_workbook(f)
    ws = wb.active
    head = [c.value for c in ws[1]]
    ids = [r[head.index("id")] for r in ws.iter_rows(min_row=2, values_only=True)]
    assert ids == ["j1", "j2", "j0", "done"]  # waiting by country order, then history
    ws.cell(2, head.index("决定") + 1, "精投")
    ws.cell(3, head.index("决定") + 1, "不投")
    ws.cell(4, head.index("状态") + 1, "已投")
    ws.cell(5, head.index("备注") + 1, "recruiter called")
    wb.save(f)
    tracker.sync(store, f)
    assert store.get("j1")["decision"] == "careful"
    assert store.get("j2")["status"] == "skipped"
    assert store.get("j0")["status"] == "applied" and store.get("j0")["applied_on"]
    assert store.get("done")["notes"] == "recruiter called"
    wb = load_workbook(f)
    assert "j2" not in [r[head.index("id")] for r in wb["岗位"].iter_rows(min_row=2, values_only=True)]
    gone = [r for r in wb["不投"].iter_rows(min_row=2, values_only=True)]
    assert [(r[head.index("id")], r[head.index("决定")]) for r in gone] == [("j2", "不投")]  # dropped: own sheet
    wb["不投"].cell(2, head.index("决定") + 1, "精投")  # picked again from the 不投 sheet
    wb.save(f)
    tracker.sync(store, f)
    assert store.get("j2")["decision"] == "careful" and store.get("j2")["status"] == "approved"


def test_tracker_stale_sheet_loses_to_ledger(store, tmp_path):
    from openpyxl import load_workbook

    from job_agent import tracker
    store.add(dict(id="a", company="C", title="T", url="https://x/a", status="approved"))
    f = tmp_path / "t.xlsx"
    tracker.export(store, f)
    wb = load_workbook(f)
    wb["岗位"].cell(2, 4, "已投")                            # the user's edit on the sheet...
    wb["meta"]["B1"] = "2000-01-01T00:00:00+00:00"
    wb.save(f)
    store.update("a", decision="auto")                       # ...but the ledger changed after the export
    tracker.read_back(store, f)
    assert store.get("a")["status"] == "approved"
