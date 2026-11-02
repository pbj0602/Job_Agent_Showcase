"""The agent picks what to apply to; the user only vetoes.

    python -m job_agent pick            # tonight's picks: 自动投 / 精投, shown in tracker.xlsx and the evening message

Every open job the user has not decided on gets a decision the same night: dream companies
(vault/dream_companies.yml) -> 精投 (a tailored CV the user reviews first); target countries, summer (any
time in policy `any_time_countries`) and target directions -> 自动投; anything else -> 不投, with the reason in 备注.
At most `pick.per_company` live picks per company; the rest wait undecided (not 不投) and are picked
once a slot frees up. Applying is what is rationed: `pick.daily_auto` 自动投 a day, best first
(policy `role_order`, summer confirmed, country order, newest). Picks are applied from the next
day on, so the user has until then to change 决定 in tracker.xlsx — the user's choice always wins.
"""
from __future__ import annotations

import re
from datetime import date

from .geo import country_rank
from .text import fold

OPEN = ("awaiting_confirm", "approved", "manual")
SEASON_SCORE = {"summer": 0, "unknown": 1}


def rank(order: list[list[str]], roles: list[str] | None = None):
    """Sort key, best first: policy role_order, summer confirmed, then policy country_order
    (stable: callers sort newest first)."""
    roles = roles or []
    role = lambda j: roles.index(j.get("role")) if j.get("role") in roles else len(roles)
    return lambda j: (role(j), SEASON_SCORE.get(j.get("season") or "unknown", 1),
                      country_rank(order, j.get("country_code") or ""))


def is_dream(company: str, dream: list[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(fold(d))}(?!\w)", fold(company)) for d in dream)


def pick(store, policy: dict, dream: list[str], today: date | None = None) -> dict[str, list[dict]]:
    today = today or date.today()
    conf = policy.get("pick") or {}
    per_company = conf.get("per_company", 3)
    focus = policy.get("focus_countries") or []
    any_time = policy.get("any_time_countries") or []
    roles = policy.get("auto_tailor_roles") or []
    order = policy.get("country_order") or []
    every = store.all()
    open_picks: dict[str, int] = {}
    for j in every:
        if j.get("decision") in ("auto", "careful") and j["status"] not in ("skipped", "rejected", "withdrawn"):
            open_picks[fold(j["company"])] = open_picks.get(fold(j["company"]), 0) + 1
    pool = [j for j in every if j["status"] in OPEN and not j.get("decision")]
    pool.sort(key=lambda j: j.get("first_seen") or "", reverse=True)
    pool.sort(key=rank(order, policy.get("role_order")))
    out: dict[str, list[dict]] = {"careful": [], "auto": [], "no": []}
    for j in pool:
        key = fold(j["company"])
        why = ("" if not focus or j.get("country_code") in focus else f"{j.get('country_code') or '?'} 不在目标国家") or \
              ("" if j.get("season") != "off" or j.get("country_code") in any_time else "不是暑期实习") or \
              ("" if not roles or j.get("role") in roles else f"方向是 {j.get('role') or '未知'}，不在 {'/'.join(roles)}")
        if not why and open_picks.get(key, 0) >= per_company:
            continue  # company quota full: stays undecided and is picked when a slot frees up
        kind = "no" if why else ("careful" if is_dream(j["company"], dream) else "auto")
        store.update(j["id"], decision=kind, picked_by="agent", picked_on=str(today),
                     **({"notes": "agent: " + why} if why else {}))
        if kind == "no":
            store.move(j["id"], "skipped", actor="agent", note=why, force=True)
        else:
            open_picks[key] = open_picks.get(key, 0) + 1
        out[kind].append(j)
    return out


def ready_to_apply(job: dict, today: date | None = None) -> bool:
    """The user's own picks right away; the agent's from the day after it picked them (the veto window)."""
    if job.get("picked_by") != "agent":
        return True
    return (job.get("picked_on") or "") < str(today or date.today())


def message(picks: dict[str, list[dict]]) -> str:
    row = lambda j: f"• {j['company']} — {j['title'][:55]} ({j.get('country_code') or '?'})"
    out = []
    if picks["auto"]:
        out += [f"🗓 新定为自动投 {len(picks['auto'])} 个（从明天起每天投前 15 个；不想投的在 tracker 改成「不投」）"] + [row(j) for j in picks["auto"][:20]]
        if len(picks["auto"]) > 20:
            out.append(f"…另外 {len(picks['auto']) - 20} 个见 tracker")
    if picks["careful"]:
        out += ["", f"⭐ 梦想公司 → 精投 {len(picks['careful'])} 个（简历改好给你看了再投）"] + [row(j) for j in picks["careful"]]
    if picks.get("no"):
        out += ["", f"🚫 不投 {len(picks['no'])} 个（原因在 tracker 备注里）"]
    return "\n".join(out)
