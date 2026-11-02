"""The one table the owner works in: tracker.xlsx, a view of the ledger the user can write back to.

    python -m job_agent tracker            # read the user's edits from tracker.xlsx, then rewrite it

The ledger (jobs.db) stays the only source of truth. The sheet is regenerated from it every
time; what the user types into the editable columns is read back first:

  * 决定 (decision) — 自动投 (template CV + prepared answers) / 精投 (tailored CV) / 不投 (skip)
                      / Link无效 (posting gone; skip);
  * 状态 (status)   — the user moves a job to 已投 / 笔试 / 面试 / offer / 拒 / 撤回;
  * 备注 (notes)    — free text, kept on the job.

Sheet 岗位: jobs waiting for a decision first (confirmed summer internships before unclear
ones, then policy `country_order`), then jobs being prepared, then everything already applied
to (newest first). Sheet 不投: the ones the user dropped (不投 / Link无效) — picking 自动投 / 精投
there brings the job back; internships the rules found not to run in summer are listed there too. 时间 shows when the internship runs, with the JD sentence.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .store import now

DECISIONS = {"自动投": "auto", "精投": "careful", "不投": "no", "Link无效": "dead"}
DECISION_CN = {v: k for k, v in DECISIONS.items()}
DROPPED = ("no", "dead")  # both leave the sheet; the job is skipped
# the user's status words -> ledger status (only moves made by hand)
STATUS_IN = {"已投": "applied", "笔试": "oa", "面试": "interview", "offer": "offer", "拒": "rejected", "撤回": "withdrawn"}
STATUS_OUT = {v: k for k, v in STATUS_IN.items()}
OPEN = ("awaiting_confirm", "approved", "manual")
DONE = tuple(STATUS_IN.values())
STATUS_CHOICES = ["待选", "准备中", "材料好了"] + list(STATUS_IN)

COLS = [  # (header, width, job -> value); editable ones are marked in EDITABLE
    ("#", 5), ("决定", 9), ("谁定的", 7), ("状态", 10), ("国家", 6), ("公司", 22), ("岗位", 44), ("时间", 40), ("大小", 7),
    ("表单", 12), ("链接", 40), ("说明", 50), ("简历文件夹", 30), ("投递日期", 11), ("备注", 30), ("id", 30),
]
EDITABLE = {"决定", "状态", "备注"}
SHEETS = ("岗位", "不投")
SEASON_CN = {"summer": "☀️ 暑期", "off": "✗ 非暑期", "unknown": "? 没写——打开看"}
SEASON_RANK = {"summer": 0, "unknown": 1, "off": 2}


def when(job: dict) -> str:
    k = job.get("season") or "unknown"
    ev = job.get("season_evidence") or ("" if job.get("jd") else "没抓到 JD")
    return SEASON_CN.get(k, k) + (f"：{ev}" if ev else "")


def status_cn(job: dict) -> str:
    s = job["status"]
    if job.get("decision") in DROPPED:
        return ""
    if s in STATUS_OUT:
        return STATUS_OUT[s]
    if s == "tailored" or (job.get("decision") in ("auto", "careful") and job.get("app_dir")):
        return "材料好了"
    if job.get("decision") in ("auto", "careful"):
        return "准备中"
    return "待选"


def rows(store, order: list[list[str]] | None = None) -> tuple[list[dict], list[dict]]:
    """(岗位 rows, 不投 rows)."""
    from .geo import country_rank
    every = store.all()
    focus = {c for group in order or [] for c in group}
    off = lambda j: (j["status"] == "skipped" and (j.get("route_reason") or "").startswith("not a summer")
                     and (not focus or j.get("country_code") in focus))
    dropped = [j for j in every if j.get("decision") in DROPPED or off(j)]  # 不投 tab: the user's + not-summer ones
    jobs = [j for j in every if j["status"] in OPEN + ("tailored",) + DONE and j.get("decision") not in DROPPED]
    waiting = [j for j in jobs if j["status"] in OPEN and not j.get("decision")]
    doing = [j for j in jobs if j not in waiting and j["status"] not in DONE]
    done = [j for j in jobs if j["status"] in DONE]
    for group in (waiting, doing):
        group.sort(key=lambda j: j.get("first_seen") or "", reverse=True)
        group.sort(key=lambda j: country_rank(order or [], j.get("country_code") or ""))
        group.sort(key=lambda j: SEASON_RANK.get(j.get("season") or "unknown", 1))
    done.sort(key=lambda j: j.get("applied_on") or j.get("updated_at") or "", reverse=True)
    dropped.sort(key=lambda j: j.get("updated_at") or "", reverse=True)
    return waiting + doing + done, dropped


def _why(job: dict, store=None) -> str:
    bits = []
    if job["status"] == "skipped":  # the real reason, so 时间 is not mistaken for it
        last = next((e for e in reversed(store.events(job["id"])) if e["to_status"] == "skipped"), None) if store else None
        who = {"human": "你在 tracker 标的", "link_check": "链接失效"}.get(last["actor"], "") if last else ""
        bits.append("不投原因: " + " · ".join(b for b in (who, (last or {}).get("note") or job.get("route_reason") or "") if b))
    if job["status"] == "manual" or job.get("apply_status") in ("blocked", "error"):
        bits.append(job.get("apply_detail") or job.get("route_reason") or "")
    if job.get("next_action"):
        bits.append("下一步: " + job["next_action"])
    return " · ".join(b for b in bits if b)[:300]


def export(store, path: Path, order: list[list[str]] | None = None) -> int:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    main, dropped = rows(store, order)
    for name, jobs in zip(SHEETS, (main, dropped)):
        _sheet(wb.create_sheet(name), jobs, grey=name == "不投", store=store)
    meta = wb.create_sheet("meta")  # read_back: ledger changes made after this time win over the sheet
    meta["A1"], meta["B1"] = "exported_at", now()
    meta.sheet_state = "hidden"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(main)


def _sheet(ws, jobs: list[dict], grey: bool, store=None) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    ws.append([c for c, _ in COLS])
    for i, (_, width) in enumerate(COLS):
        ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = width
    link = [c for c, _ in COLS].index("链接") + 1
    for n, j in enumerate(jobs, 1):
        url = j.get("apply_url") or j.get("url") or ""
        who = ("agent" if j.get("picked_by") == "agent" else "你") if j.get("decision") else ""
        ws.append([n, DECISION_CN.get(j.get("decision") or "", ""), who, status_cn(j), j.get("country_code") or "",
                   j["company"], j["title"], when(j), j.get("size") or "", j.get("ats") or "", url, _why(j, store),
                   j.get("app_dir") or "", j.get("applied_on") or "", j.get("notes") or "", j["id"]])
        if url:
            c = ws.cell(ws.max_row, link)
            c.hyperlink, c.style = url, "Hyperlink"
    last = max(ws.max_row, 2)
    for col, choices in ((2, list(DECISIONS)), (4, STATUS_CHOICES)):
        dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{ws.cell(2, col).column_letter}2:{ws.cell(last, col).column_letter}{last}")
    head, mine = PatternFill("solid", fgColor="DDEBF7"), PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]:
        c.font, c.fill = Font(bold=True), (mine if c.value in EDITABLE else head)
    wrap = {7, 8, 12}
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column in wrap)
            if grey:
                c.font = Font(color="A6A6A6")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions


def read_back(store, path: Path) -> dict[str, int]:
    """Apply the user's edits (决定 / 状态 / 备注) to the ledger. Returns a tally of what changed."""
    from openpyxl import load_workbook

    tally: dict[str, int] = {}
    if not path.exists():
        return tally
    wb = load_workbook(path, read_only=True)
    exported = str(wb["meta"]["B1"].value or "") if "meta" in wb.sheetnames else ""
    sheets = [wb[n] for n in SHEETS if n in wb.sheetnames] or [wb.active]
    bump = lambda k: tally.__setitem__(k, tally.get(k, 0) + 1)
    for ws in sheets:
        it = ws.iter_rows(values_only=True)
        head = [str(h or "") for h in next(it, [])]
        if "id" not in head:
            continue
        col = {h: i for i, h in enumerate(head)}
        for r in it:
            get = lambda h: str(r[col[h]] or "").strip() if h in col and col[h] < len(r) else ""
            job = store.get(get("id"))
            if not job or (exported and (job.get("updated_at") or "") > exported):
                continue  # changed in the ledger since this sheet was written: the sheet is stale for this row
            dec = DECISIONS.get(get("决定"), "")
            if dec != (job.get("decision") or ""):
                store.update(job["id"], decision=dec, picked_by="")  # the user's word now
                bump(f"决定→{get('决定') or '空'}")
                if dec in DROPPED and job["status"] in OPEN:
                    store.move(job["id"], "skipped", actor="human", note=f"tracker: {get('决定')}")
                elif dec in ("auto", "careful") and job["status"] == "skipped":
                    store.move(job["id"], "approved", actor="human", note="tracker: picked again", force=True)
            to = STATUS_IN.get(get("状态"))
            if to and to != job["status"]:
                store.move(job["id"], to, actor="human", note="tracker", force=True)
                if to == "applied" and not job.get("applied_on"):
                    store.update(job["id"], applied_on=str(date.today()))
                elif to != "applied" and not job.get("reply_on"):
                    store.update(job["id"], reply_on=str(date.today()))
                bump(f"状态→{get('状态')}")
            if get("备注") != (job.get("notes") or ""):
                store.update(job["id"], notes=get("备注"))
                bump("备注")
    return tally


def sync(store, path: Path, order: list[list[str]] | None = None) -> str:
    tally = read_back(store, path)
    n = export(store, path, order)
    changed = ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) or "no edits"
    return f"tracker: read back {changed}; wrote {n} row(s) -> {path}"
