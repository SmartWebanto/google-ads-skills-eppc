"""check.py — skill-147 deterministic seasonal budget cap, schedule and restoration review.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-147-seasonal-budget-adjustment-scheduling/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #38 Pause campaigns that have spent all-time budget (kaugesaar/adwords-scripts) — clean-room
         reimplementation of cumulative spend versus a total budget cap, as a request-only stop-control proposal;
         index #40 Pause labelled campaigns at total budget limit (camiltang) — clean-room reimplementation of
         pooled total-cap tracking, keyed by budget ID instead of labels; neither pauses anything here.
rules:   Pools are keyed by budget_id; a pool's approved_total_cap must be one value per event (conflicts → no verdict).
         Event spend = sum of custom/seasonal_budget_daily cost at unique (campaign_id, budget_id, date) grain within
         the event window; conflicting duplicate rows void the pool total. Observed spend is a lower bound, so a
         breach is proven even when the daily table is incomplete; "no breach" needs manifest-complete daily rows.
         Critical only for a breach whose overage >= spend_floor (resolved per campaign for single-campaign pools,
         account level otherwise); smaller breaches are Info. Plan money (caps/budgets) is read in account currency.
         Performance comparisons need both cohorts mature, same goal_id and min_clicks/min_conversions each.
         Schedule conflicts are judged only at a dated snapshot: inside the event window versus proposed_event_budget,
         at least one day after end_at versus post_event_budget. Automatic reversion is not required when
         manual_override_owner is named. Never schedules, pauses or applies budgets.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-147-seasonal-budget-adjustment-scheduling"
VERSION = "1.0.0"

PLAN = "external/seasonal_budget_plan"
DAILY = "custom/seasonal_budget_daily"
RULES = "custom/seasonal_budget_rules"
_APPROVED = ("APPROVED", "ACTIVE", "SIGNED_OFF")
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:\.\.|/|to|–|—)\s*(\d{4}-\d{2}-\d{2})")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _approved(r) -> bool:
    return _s(r.get("approval_status")).upper() in _APPROVED


def _col(ctx, key: str, *names: str) -> str:
    t = ctx.table(key)
    return next((n for n in names if t is not None and n in t.columns), names[0])


def _ranges(v) -> list[tuple[date, date]] | None:
    """Parse 'YYYY-MM-DD..YYYY-MM-DD' ranges (';' or '|' separated). None when any part is unparseable."""
    out = []
    for part in V.split_list(v):
        m = _RANGE.fullmatch(part.strip())
        if not m:
            return None
        a, b = V.parse_date(m.group(1)), V.parse_date(m.group(2))
        if a is None or b is None or b < a:
            return None
        out.append((a, b))
    return out or None


def _daily_index(ctx) -> tuple[dict, set]:
    """Unique (campaign_id, budget_id, date) → row; returns conflicting grains separately."""
    idx: dict[tuple, dict] = {}
    conflicts: set = set()
    for r in ctx.rows(DAILY):
        d = V.parse_date(r.get("date"))
        if d is None:
            continue
        g = (_s(r.get("campaign_id")), _s(r.get("budget_id")), d)
        if g in idx and idx[g] != r:
            conflicts.add(g)
        idx[g] = r
    return idx, conflicts


def _data_end(ctx, idx) -> date | None:
    days = [g[2] for g in idx]
    return max(days) if days else ctx.period_end


def _pool_members(ctx) -> dict[str, set]:
    bid = _col(ctx, "budgets", "budget_id", "id")
    out: dict[str, set] = {}
    for b in ctx.rows("budgets"):
        out.setdefault(_s(b.get(bid)), set()).update(V.split_list(b.get("campaign_ids")))
    for c in ctx.rows("campaigns"):
        if _s(c.get("budget_id")):
            out.setdefault(_s(c.get("budget_id")), set()).add(_s(c.get("id")))
    return out


def _budget_amount(ctx, budget_id: str) -> float | None:
    bid = _col(ctx, "budgets", "budget_id", "id")
    vals = {ctx.money(b.get("amount")) for b in ctx.rows("budgets") if _s(b.get(bid)) == budget_id}
    return vals.pop() if len(vals) == 1 else None


def _latest_rules(ctx, budget_id: str) -> list[dict]:
    rows = [r for r in ctx.rows(RULES) if _s(r.get("budget_id")) == budget_id]
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (_s(r.get("rule_id")), _s(r.get("snapshot_at")))):
        latest[_s(r.get("rule_id"))] = r
    return [latest[k] for k in sorted(latest)]


def _events(ctx) -> dict[tuple, list[dict]]:
    ev: dict[tuple, list[dict]] = {}
    for r in ctx.rows(PLAN):
        ev.setdefault((_s(r.get("event_id")), _s(r.get("budget_id"))), []).append(r)
    return ev


def run(ctx) -> None:
    """Run seasonal pool cap, event spend, performance cohort and budget-schedule conflict checks.

    Rules:   Pools keyed by budget_id; conflicting caps or duplicate daily rows → no verdict. Observed spend is a lower
             bound: breach provable on incomplete data, 'no breach' needs manifest-complete rows. Critical only for a
             breach with overage >= spend_floor; smaller breaches Info. Performance needs both cohorts mature, same
             goal_id and min samples. Schedule conflicts judged at dated snapshots only; never applies budgets.
    """
    pool = ctx.check("budget_pool_cap", "Event spend versus approved total cap per budget pool",
                     {PLAN: ["event_id", "campaign_id", "budget_id", "start_at", "end_at", "approved_total_cap"],
                      DAILY: ["campaign_id", "date", "budget_id", "cost"],
                      "budgets": [_col(ctx, "budgets", "budget_id", "id"), "amount", "campaign_ids"]})
    idx, conflicts = (_daily_index(ctx) if ctx.table(DAILY) else ({}, set()))
    if pool.runnable:
        _pool_cap(ctx, pool, idx, conflicts)

    perf = ctx.check("event_vs_normal", "Prior event versus normal-period outcomes",
                     {PLAN: ["event_id", "campaign_id", "start_at", "end_at", "normal_baseline_dates"],
                      DAILY: ["campaign_id", "date", "goal_id", "impressions", "clicks", "cost", "conversions",
                              "conversion_value", "maturity"]})
    if perf.runnable:
        _event_vs_normal(ctx, perf, idx)

    resp = ctx.check("response_scenarios", "Marginal-response assumptions for proposed increases",
                     {PLAN: ["event_id", "campaign_id", "budget_id", "start_at", "end_at", "baseline_daily_budget",
                             "proposed_event_budget", "response_assumptions", "economic_target"]})
    if resp.runnable:
        _response(ctx, resp)

    conf = ctx.check("schedule_conformance", "Approved temporary schedule and restoration versus configuration",
                     {PLAN: ["event_id", "budget_id", "start_at", "end_at", "timezone", "approval_status",
                             "proposed_event_budget", "post_event_budget"],
                      RULES: ["budget_id", "rule_id", "snapshot_at", "current_amount", "action", "scheduled_at",
                              "timezone", "enabled", "reversion_amount", "manual_override_owner"]})
    if conf.runnable:
        _conformance(ctx, conf)

    draft = ctx.check("schedule_draft", "Request-only bounded budget schedule",
                      {PLAN: ["event_id", "campaign_id", "budget_id", "start_at", "end_at", "approved_total_cap",
                              "proposed_event_budget", "post_event_budget", "owner", "approval_status",
                              "approval_ref"]})
    if draft.runnable:
        _draft(ctx, draft)


def _pool_cap(ctx, chk, idx, conflicts) -> None:
    daily_t = ctx.table(DAILY)
    complete = daily_t.complete is True and not daily_t.truncated
    members = _pool_members(ctx)
    rules_known = ctx.table(RULES) is not None and not ctx.table(RULES).missing(
        ["budget_id", "enabled", "action", "manual_override_owner"])
    for (eid, bid), rows in sorted(_events(ctx).items()):
        caps = {V.num(r.get("approved_total_cap")) for r in rows}
        starts = {V.parse_date(r.get("start_at")) for r in rows}
        ends = {V.parse_date(r.get("end_at")) for r in rows}
        ent = {"event_id": eid, "budget_id": bid}
        if not bid:
            chk.partial(f"event {eid}: plan rows without budget_id; pool unknown")
            continue
        if len(caps) != 1 or None in caps or len(starts) != 1 or None in starts or len(ends) != 1 or None in ends:
            chk.partial(f"event {eid} budget {bid}: cap/start/end missing or inconsistent across plan rows")
            continue
        cap, start, end = caps.pop(), starts.pop(), ends.pop()
        plan_camps = sorted({_s(r.get("campaign_id")) for r in rows})
        pool_camps = sorted(members.get(bid, set()))
        if pool_camps and set(plan_camps) - set(pool_camps):
            chk.partial(f"event {eid}: plan campaigns {sorted(set(plan_camps) - set(pool_camps))} not in budget {bid}")
        grains = [g for g in idx if g[1] == bid and start <= g[2] <= end]
        if any(g in conflicts for g in grains):
            chk.partial(f"budget {bid}: conflicting duplicate daily rows; pool total not computed")
            continue
        unknown = [g for g in grains if ctx.money(idx[g].get("cost")) is None]
        spend = sum(ctx.money(idx[g].get("cost")) or 0.0 for g in grains)
        last = max((g[2] for g in grains), default=None)
        single = (pool_camps or plan_camps)[0] if len(pool_camps or plan_camps) == 1 else None
        floor = ctx.params.get("spend_floor", single) if single else ctx.params.get("spend_floor")
        calc = {"event_window": [start, end], "observed_through": last, "observed_spend": round(spend, 2),
                "approved_total_cap": cap, "overage": round(spend - cap, 2), "days_observed": len({g[2] for g in grains}),
                "unknown_cost_rows": len(unknown), "daily_table_complete": complete, "pool_campaigns": pool_camps,
                "spend_floor": floor.value, "spend_floor_source": floor.source or floor.reason}
        chk.observe(f"Budget {bid} event {eid}: observed spend versus approved cap", **ent, **calc)
        if spend > cap:
            if floor.value is None:
                chk.partial(f"budget {bid}: breach observed but spend_floor unresolved ({floor.reason}); materiality unknown")
                sev = "Info"
            else:
                sev = "Critical" if spend - cap >= floor.value else "Info"
            chk.finding("approved_cap_breach", sev, ent,
                        f"Budget pool {bid} spent {spend:.2f} {ctx.currency} in event {eid} window {start}..{end}, "
                        f"{spend - cap:.2f} above the approved total cap {cap:g}",
                        evidence={"plan_approval_refs": sorted({_s(r.get('approval_ref')) for r in rows}),
                                  "owners": sorted({_s(r.get('owner')) for r in rows})},
                        calculation=calc,
                        recommendation="Escalate to the budget owner; request-only stop/reduction per the approved cap.",
                        uncertainty="Observed rows are a lower bound; overage is spend above cap, not recoverable savings.")
            continue
        if unknown or not complete:
            chk.partial(f"budget {bid}: daily rows not certified complete or unknown cost; no-breach not provable")
        headroom = cap - spend
        amount = _budget_amount(ctx, bid)
        ref = min(filter(None, (last, ctx.as_of))) if (last or ctx.as_of) else None
        if ref is None or ref >= end or amount is None:
            continue
        remaining_days = (end - ref).days
        nominal = amount * remaining_days
        chk.observe(f"Budget {bid} event {eid}: remaining headroom versus nominal daily amount", **ent,
                    headroom=round(headroom, 2), current_daily_amount=amount, remaining_days=remaining_days,
                    nominal_remaining_spend=round(nominal, 2), reference_date=ref)
        if nominal <= headroom:
            continue
        if not rules_known:
            chk.partial(f"budget {bid}: stop-control evidence ({RULES}) unavailable; headroom control unknown")
            continue
        rules = _latest_rules(ctx, bid)
        controls = [r for r in rules if V.boolean(r.get("enabled")) is True and _s(r.get("action"))]
        manual = sorted({_s(r.get("manual_override_owner")) for r in rules if _s(r.get("manual_override_owner"))})
        if controls or manual:
            continue
        chk.finding("cap_headroom_without_stop_control", "Info", ent,
                    f"Nominal remaining spend {nominal:.2f} at the current daily amount exceeds cap headroom "
                    f"{headroom:.2f} and no enabled rule or manual override owner is recorded for budget {bid}",
                    calculation={**calc, "headroom": round(headroom, 2), "current_daily_amount": amount,
                                 "remaining_days": remaining_days, "nominal_remaining_spend": round(nominal, 2)},
                    recommendation="Request an accountable stop control (owner-run check or rule) at the approved cap.",
                    uncertainty="Nominal spend assumes full daily delivery; actual delivery may be lower or up to "
                                "platform daily overdelivery limits.")


def _cohort(ctx, idx, cid, windows, fallback_mature) -> dict:
    acc = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0,
           "days": 0, "immature_rows": 0, "unknown_cells": 0, "goals": set()}
    for g in sorted(idx):
        if g[0] != cid or not any(a <= g[2] <= b for a, b in windows):
            continue
        r = idx[g]
        mat = _s(r.get("maturity")).lower()
        ok = mat in ("mature", "true", "yes") or (not mat and fallback_mature is True and ctx.period_end is not None
                                                   and g[2] <= ctx.period_end)
        if not ok:
            acc["immature_rows"] += 1
            continue
        acc["days"] += 1
        acc["goals"].add(_s(r.get("goal_id")))
        for k in ("impressions", "clicks", "conversions", "conversion_value"):
            v = V.num(r.get(k))
            acc["unknown_cells"] += v is None
            acc[k] += v or 0.0
        c = ctx.money(r.get("cost"))
        acc["unknown_cells"] += c is None
        acc["cost"] += c or 0.0
    return acc


def _event_vs_normal(ctx, chk, idx) -> None:
    min_clicks, min_conv = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
    end = _data_end(ctx, idx)
    for r in sorted(ctx.rows(PLAN), key=lambda r: (_s(r.get("event_id")), _s(r.get("campaign_id")))):
        eid, cid = _s(r.get("event_id")), _s(r.get("campaign_id"))
        s, e = V.parse_date(r.get("start_at")), V.parse_date(r.get("end_at"))
        if s is None or e is None or end is None or e > end:
            continue  # upcoming/current events have no completed outcome window
        normal = _ranges(r.get("normal_baseline_dates"))
        if normal is None:
            chk.partial(f"event {eid} campaign {cid}: normal_baseline_dates missing or unparseable")
            continue
        ev = _cohort(ctx, idx, cid, [(s, e)], ctx.mature)
        nm = _cohort(ctx, idx, cid, normal, ctx.mature)
        data = {"event_id": eid, "campaign_id": cid, "event_window": [s, e], "normal_windows": normal,
                "min_clicks": min_clicks.value, "min_conversions": min_conv.value}
        for name, c in (("event", ev), ("normal", nm)):
            data[name] = {k: (sorted(v) if isinstance(v, set) else v) for k, v in c.items()}
            data[name].update(ctr=V.ratio(c["clicks"], c["impressions"]), cvr=V.ratio(c["conversions"], c["clicks"]),
                              cpa=V.ratio(c["cost"], c["conversions"]), roas=V.ratio(c["conversion_value"], c["cost"]),
                              daily_cost=V.ratio(c["cost"], c["days"]))
        comparable = (ev["goals"] == nm["goals"] and len(ev["goals"]) == 1 and "" not in ev["goals"]
                      and not ev["immature_rows"] and not nm["immature_rows"])
        data["cvr_comparable"] = comparable and all(c["clicks"] >= (min_clicks.value or float("inf")) for c in (ev, nm))
        data["cpa_roas_comparable"] = comparable and all(
            c["conversions"] >= (min_conv.value or float("inf")) for c in (ev, nm))
        if not comparable:
            chk.partial(f"event {eid} campaign {cid}: goal mismatch or immature rows; descriptive only")
        chk.observe(f"Event {eid} campaign {cid}: event versus normal cohorts", **data)


def _response(ctx, chk) -> None:
    ref = ctx.as_of
    for r in sorted(ctx.rows(PLAN), key=lambda r: (_s(r.get("event_id")), _s(r.get("campaign_id")))):
        eid, cid = _s(r.get("event_id")), _s(r.get("campaign_id"))
        e = V.parse_date(r.get("end_at"))
        if ref is None or e is None or e < ref:
            continue
        base, prop = V.num(r.get("baseline_daily_budget")), V.num(r.get("proposed_event_budget"))
        ent = {"event_id": eid, "campaign_id": cid, "budget_id": _s(r.get("budget_id"))}
        if base is None or prop is None:
            chk.partial(f"event {eid} campaign {cid}: baseline/proposed budget unknown")
            continue
        chk.observe(f"Event {eid} campaign {cid}: proposed versus baseline daily budget", **ent, baseline=base,
                    proposed=prop, change=V.ratio(prop - base, base))
        if prop <= base:
            continue  # flat or lower is a valid decision
        if not _s(r.get("response_assumptions")) or not _s(r.get("economic_target")):
            chk.finding("missing_response_model", "Info", ent,
                        f"Event {eid}: proposed budget {prop:g} > baseline {base:g} without explicit response "
                        f"assumptions and economic target",
                        evidence={"response_assumptions": r.get("response_assumptions"),
                                  "economic_target": r.get("economic_target"), "rationale": r.get("rationale")},
                        recommendation="Request marginal-response scenarios and cash/capacity limits before any increase.",
                        uncertainty="Lost IS or past event demand alone does not show profitable incremental demand.")


def _conformance(ctx, chk) -> None:
    for (eid, bid), rows in sorted(_events(ctx).items()):
        appr = [r for r in rows if _approved(r)]
        if not appr or not bid:
            continue
        r0 = appr[0]
        s, e = V.parse_date(r0.get("start_at")), V.parse_date(r0.get("end_at"))
        prop, post = V.num(r0.get("proposed_event_budget")), V.num(r0.get("post_event_budget"))
        ent = {"event_id": eid, "budget_id": bid}
        rules = _latest_rules(ctx, bid)
        if s is None or e is None:
            chk.partial(f"event {eid}: start/end unknown")
            continue
        snaps = sorted({V.parse_date(r.get("snapshot_at")) for r in rules} - {None})
        amounts = {ctx.money(r.get("current_amount")) for r in rules} - {None}
        snap = snaps[-1] if snaps else None
        amount = amounts.pop() if len(amounts) == 1 else None
        base_ev = {"plan": {"proposed_event_budget": prop, "post_event_budget": post, "window": [s, e],
                            "timezone": r0.get("timezone"), "approval_ref": r0.get("approval_ref")},
                   "config_snapshot": snap, "current_amount": amount, "rule_ids": [_s(r.get("rule_id")) for r in rules]}
        if snap is not None and amount is not None:
            if s <= snap <= e and prop is not None and abs(amount - prop) > 0.005:
                chk.finding("schedule_conflict", "Warning", ent,
                            f"Budget {bid} amount {amount:g} at {snap} differs from the approved event budget {prop:g}",
                            evidence=base_ev, recommendation="Confirm with the budget owner and correct (request-only).",
                            uncertainty="Snapshot-level evidence; intraday changes after the snapshot are unknown.")
            elif snap >= e + timedelta(days=1) and post is not None and abs(amount - post) > 0.005:
                chk.finding("restoration_conflict", "Warning", ent,
                            f"Budget {bid} amount {amount:g} at {snap} differs from the approved post-event budget {post:g}",
                            evidence=base_ev, recommendation="Restore per the approved plan after owner confirmation.",
                            uncertainty="A newer approved change may exist outside the supplied plan.")
        elif not rules:
            chk.partial(f"budget {bid}: no rule/config snapshot rows; actual configuration unknown")
            continue
        if snap is not None and snap > e:
            continue
        manual = sorted({_s(r.get("manual_override_owner")) for r in rules if _s(r.get("manual_override_owner"))})
        revert = [r for r in rules if V.num(r.get("reversion_amount")) is not None]
        for r in revert:
            rv, en = V.num(r.get("reversion_amount")), V.boolean(r.get("enabled"))
            rid = _s(r.get("rule_id"))
            if post is not None and abs(rv - post) > 0.005:
                chk.finding("restoration_conflict", "Warning", {**ent, "rule_id": rid},
                            f"Rule {rid} reverts budget {bid} to {rv:g}, not the approved post-event {post:g}",
                            evidence=base_ev, recommendation="Align the reversion amount with the approved plan (request-only).",
                            uncertainty="The approved plan may have been superseded; confirm with the owner.")
            elif en is False and not manual:
                chk.finding("restoration_conflict", "Warning", {**ent, "rule_id": rid},
                            f"Reversion rule {rid} for budget {bid} is disabled and no manual override owner is named",
                            evidence=base_ev, recommendation="Name an accountable manual owner or confirm the rule.",
                            uncertainty="Restoration may be handled outside the supplied evidence.")
            tz_rule, tz_plan = _s(r.get("timezone")), _s(r0.get("timezone"))
            if tz_rule and tz_plan and tz_rule != tz_plan:
                chk.review("rule_timezone_mismatch", {**ent, "rule_id": rid},
                           f"Rule {rid} runs in {tz_rule} while the event is defined in {tz_plan}. Does scheduled_at "
                           f"{_s(r.get('scheduled_at'))} still hit the approved restoration time?",
                           evidence={**base_ev, "scheduled_at": r.get("scheduled_at")},
                           outcomes={"conflicts": {"severity": "Warning", "recommendation": "Correct the schedule time."},
                                     "consistent": {"severity": None, "recommendation": "No change."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask the rule owner."}},
                           guidance="Convert scheduled_at between the two zones; account time zone governs Ads dates.")
        if not revert and not manual:
            chk.finding("restoration_control_unknown", "Info", ent,
                        f"No reversion rule or manual override owner recorded for budget {bid} after event {eid}",
                        evidence=base_ev, recommendation="Request the accountable restoration owner and date.",
                        uncertainty="Manual control may exist outside the supplied evidence.")


def _draft(ctx, chk) -> None:
    need = ("approved_total_cap", "proposed_event_budget", "post_event_budget", "owner", "approval_ref")
    for (eid, bid), rows in sorted(_events(ctx).items()):
        appr = [r for r in rows if _approved(r)]
        if not appr:
            chk.observe(f"Event {eid}: no approved temporary change; no schedule drafted", event_id=eid, budget_id=bid)
            continue
        r0 = appr[0]
        gaps = [c for c in need if not _s(r0.get(c))]
        ent = {"event_id": eid, "budget_id": bid}
        if gaps:
            chk.finding("incomplete_schedule_inputs", "Info", ent,
                        f"Approved event {eid} lacks {gaps} for a bounded budget schedule",
                        evidence={c: r0.get(c) for c in need}, recommendation="Request the missing plan fields.",
                        uncertainty="Schedule cannot be drafted without the named values.")
            continue
        chk.observe(f"Request-only schedule for budget {bid} event {eid}", **ent, start_at=r0.get("start_at"),
                    end_at=r0.get("end_at"), timezone=r0.get("timezone"),
                    event_budget=V.num(r0.get("proposed_event_budget")),
                    approved_total_cap=V.num(r0.get("approved_total_cap")),
                    post_event_budget=V.num(r0.get("post_event_budget")), owner=r0.get("owner"),
                    approval_ref=r0.get("approval_ref"), campaigns=sorted({_s(r.get("campaign_id")) for r in appr}))


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
