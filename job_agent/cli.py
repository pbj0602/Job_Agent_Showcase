"""job-agent command line. Every command reads/writes only the vault (JOB_VAULT or --vault).

    job-agent ingest --queue <dir>              import job records (queue/<date>/<id>.json) from any collector
    job-agent scan                              poll companies.yml ATS feeds (needs network)
    job-agent route                             decide skip / manual / confirm / auto
    job-agent reroute                           re-apply changed rules to jobs no human has decided yet
    job-agent tracker [--file tracker.xlsx]     read the user's edits from the sheet, then rewrite it
    job-agent list [--status S]                 what's in the pipeline
    job-agent mark <id> <status> [--note ..] [--dir applications/<slug>]   record what happened
    job-agent export <file.csv>                 spreadsheet view of everything
    job-agent pick                              the agent picks tonight's 自动投 / 精投 (the user vetoes in the tracker)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .config import load_pack, load_vault
from .enrich.sponsorship import Register
from .geo import country_of
from .route import decide
from .sources import ats, digest_queue
from .store import STATES, Store
from .text import slug

AFTER_APPLY = ("applied", "oa", "interview", "offer", "rejected")


def _registers(vault) -> dict[str, Register]:
    regs = {}
    for r in vault.yaml("registers.yml", []) or []:
        p = vault.path(r["path"])
        if p.exists():
            regs[r["name"]] = Register.from_csv(r["name"], p, r["column"])
    return regs


def cmd_ingest(vault, store, a):
    n_new = 0
    for job in digest_queue.read(Path(a.queue)):
        _, new = store.add(job, actor="digest")
        n_new += new
    print(f"ingest: {n_new} new job(s)")


def cmd_scan(vault, store, a):
    n_new = 0
    for entry in vault.yaml("companies.yml", []) or []:
        try:
            jobs = ats.scan_company(entry)
        except Exception as e:
            print(f"  {entry.get('name')}: {e}")
            continue
        for j in jobs:
            cc = country_of(j["location"])
            if not cc:
                continue
            j.update(country_code=cc, id=slug(j["company"], j["title"], cc))
            _, new = store.add(j, actor="scan")
            n_new += new
    print(f"scan: {n_new} new job(s)")


def cmd_route(vault, store, a):
    countries = (vault.yaml("work_authorization.yml", {}) or {}).get("countries", {})
    policy = {**(vault.yaml("policy.yml", {}) or {}), "dream_companies": (vault.yaml("dream_companies.yml", {}) or {}).get("companies", [])}
    roles, regs = load_pack("roles"), _registers(vault)
    done = sum(store.counts().get(s, 0) for s in AFTER_APPLY)
    tally: dict[str, int] = {}
    for job in store.by_status("discovered"):
        d = decide(job, countries=countries, roles=roles, policy=policy, registers=regs, applied_so_far=done)
        store.update(job["id"], route_reason=d.reason, **d.fields)
        store.move(job["id"], d.status, actor="route", note=d.reason)
        tally[d.status] = tally.get(d.status, 0) + 1
    print("route:", ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) or "nothing to route")


def cmd_reroute(vault, store, a):
    """Re-run the routing rules on awaiting_confirm / approved / manual jobs that only the machine has decided."""
    countries = (vault.yaml("work_authorization.yml", {}) or {}).get("countries", {})
    policy = {**(vault.yaml("policy.yml", {}) or {}), "dream_companies": (vault.yaml("dream_companies.yml", {}) or {}).get("companies", [])}
    roles, regs = load_pack("roles"), _registers(vault)
    done = sum(store.counts().get(s, 0) for s in AFTER_APPLY)
    tally: dict[str, int] = {}
    for job in store.by_status("awaiting_confirm", "approved", "manual"):
        if job.get("apply_status") == "submitted" or any(e["actor"] not in ("route", "digest", "scan") for e in store.events(job["id"])):
            continue
        cc = country_of(job.get("location", "")) or job.get("country_code", "")
        d = decide({**job, "country_code": cc}, countries=countries, roles=roles, policy=policy,
                   registers=regs, applied_so_far=done)
        if d.status == job["status"] and d.reason == job.get("route_reason"):
            continue
        store.update(job["id"], country_code=cc, route_reason=d.reason, **d.fields)
        store.move(job["id"], d.status, actor="route", note="reroute: " + d.reason, force=True)
        key = f"{job['status']}->{d.status}"
        tally[key] = tally.get(key, 0) + 1
    print("reroute:", ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) or "no changes")


def cmd_tracker(vault, store, a):
    from . import tracker
    print(tracker.sync(store, Path(a.file), (vault.yaml("policy.yml", {}) or {}).get("country_order")))


def cmd_prepare(vault, store, a):
    from . import tracker
    from .prepare import prepare
    order = (vault.yaml("policy.yml", {}) or {}).get("country_order")
    tracker.read_back(store, Path(a.file))
    for line in prepare(vault, store):
        print("prepare:", line)
    print(tracker.sync(store, Path(a.file), order))


def cmd_list(vault, store, a):
    rows = store.by_status(*a.status) if a.status else store.all()
    for r in rows:
        print(f"{r['status']:<16} {r.get('country_code', ''):<3} {r['company'][:22]:<22} {r['title'][:48]:<48} "
              f"{(r.get('route_reason') or '')[:60]}")
    print(f"-- {len(rows)} job(s); by status: {store.counts()}")


def cmd_mark(vault, store, a):
    job = store.move(a.id, a.status, actor="human", note=a.note or "", force=a.force)
    if a.status == "applied" and not job.get("applied_on"):
        store.update(a.id, applied_on=str(date.today()))
    if a.dir:
        store.update(a.id, app_dir=a.dir)
    print(f"{job['id']}: {job['status']}")


def _policy(vault) -> dict:
    return {**(vault.yaml("policy.yml", {}) or {}),
            "dream_companies": (vault.yaml("dream_companies.yml", {}) or {}).get("companies", [])}


def cmd_pick(vault, store, a):
    from . import tracker
    from .pick import message, pick
    from .prepare import prepare
    policy = _policy(vault)
    tracker.read_back(store, Path(a.file))
    print(message(pick(store, policy, policy["dream_companies"])) or "pick: nothing new to pick")
    for line in prepare(vault, store):
        print("prepare:", line)
    print(tracker.sync(store, Path(a.file), policy.get("country_order")))


def cmd_export(vault, store, a):
    print(f"export: {store.export_csv(Path(a.file))} row(s) -> {a.file}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="job-agent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", help="vault directory (default: $JOB_VAULT, else the demo vault)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("--queue", required=True); p.set_defaults(fn=cmd_ingest)
    sub.add_parser("scan").set_defaults(fn=cmd_scan)
    sub.add_parser("route").set_defaults(fn=cmd_route)
    sub.add_parser("reroute").set_defaults(fn=cmd_reroute)
    p = sub.add_parser("tracker"); p.add_argument("--file", default="tracker.xlsx"); p.set_defaults(fn=cmd_tracker)
    p = sub.add_parser("prepare"); p.add_argument("--file", default="tracker.xlsx"); p.set_defaults(fn=cmd_prepare)
    p = sub.add_parser("list"); p.add_argument("--status", nargs="*", choices=STATES); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("mark"); p.add_argument("id"); p.add_argument("status", choices=STATES)
    p.add_argument("--note"); p.add_argument("--force", action="store_true")
    p.add_argument("--dir", help="the application folder, relative to vault/resume (applications/<slug>)")
    p.set_defaults(fn=cmd_mark)
    p = sub.add_parser("export"); p.add_argument("file"); p.set_defaults(fn=cmd_export)
    p = sub.add_parser("pick"); p.add_argument("--file", default="tracker.xlsx"); p.set_defaults(fn=cmd_pick)
    try:  # optional local commands, registered only when their module is installed
        from .cli_personal import register
        register(sub)
    except ImportError:
        pass
    a = ap.parse_args(argv)
    vault = load_vault(a.vault)
    if vault.is_demo:
        print("(demo vault — set JOB_VAULT to use your own)", file=sys.stderr)
    a.fn(vault, Store(vault.db), a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
