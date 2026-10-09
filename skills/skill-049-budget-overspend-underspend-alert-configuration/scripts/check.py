"""check.py — skill-049 deterministic budget pacing, cap breach, daily overdelivery and alert-log checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-049-budget-overspend-underspend-alert-configuration/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #33 Daily Budget Overdelivery Alerts (nilsrooijmans.com) — clean-room reimplementation of
         day-level cost vs daily budget overdelivery detection (Info only; alert = local proposal, never e-mail)
         index #37 Stable budgets (fredericharnois) — clean-room reimplementation of overspend-vs-daily-budget
         detection only; the pause/reactivate actions are refused (recommend-only library)
         index #41 Report campaigns reaching % of daily budget (inbiz.de) — clean-room reimplementation of
         daily budget utilization ratios with an owner-supplied reach ratio (profile.budget_alert_reach_ratio)
rules:   Only complete_day=true rows count; missing MTD dates → no monthly status (partial), never a pass.
         Expected MTD = sum(dated plan planned_spend); NEVER daily budget × days. ratio only for expected > 0.
         Pacing Warning needs APPROVED warning_lower/upper_ratio in the plan; 0.85/1.15 are unapproved triage
         defaults → observation only.
         Critical = actual matched-basis MTD spend exceeds an approved hard cap (cap_or_target = cap/hard_cap)
         by >= spend_floor; a smaller excess is Warning; plan-based projection above cap is Info forecast risk.
         Campaign daily amounts are average delivery budgets: daily overdelivery (cost > dated amount ×
         profile.budget_overdelivery_ratio, default 1.0) is Info only. Shared pools are evaluated once per pool.
         Weekday anomaly (|change| > 0.30 vs 4 same-weekday complete days) needs 30 prior complete days, a
         positive baseline and |delta| >= spend_floor; "unexplained" is AI review (Warning), never automatic.
         Absent monitoring (Info) only when the rule inventory is manifest-complete. Nothing is configured,
         sent, paused or transmitted; verify() requires rule proposals to be notify-only.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

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

SKILL = "skill-049-budget-overspend-underspend-alert-configuration"
VERSION = "1.0.0"

_DAILY = "custom/budget_alert_daily"
_HIST = "custom/budget_history"
_PLAN = "external/budget_alert_plan"
_LOG = "custom/budget_alert_history"
_RULES = "external/budget_alert_rules"
_SEPS = (" | ", ";", "|", ",")
_CAP = {"CAP", "HARD_CAP", "HARD CAP"}
_DEFAULT_BOUNDS = (0.85, 1.15)
_ANOMALY = 0.30
_MUTATING = ("pause", "enable", "set_budget", "change_budget", "remove", "mutate")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _scope_rows(rows: list[dict], scope_type: str, scope_id: str) -> list[dict] | None:
    t = scope_type.lower()
    if t in ("account", "customer"):
        return rows
    if t == "campaign":
        return [r for r in rows if _s(r.get("campaign_id")) == scope_id]
    if t in ("budget", "pool", "shared_budget", "budget_pool"):
        return [r for r in rows if _s(r.get("budget_id")) == scope_id]
    return None


def _days(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)] if a and b and a <= b else []


class _Daily:
    """Complete-day cost per (campaign, date) with explicit incomplete/duplicate/unknown tracking."""

    def __init__(self, ctx):
        self.rows, self.incomplete, self.dupes, self.unknown = [], set(), [], set()
        seen = set()
        for r in ctx.rows(_DAILY):
            d = V.parse_date(r.get("date"))
            cid = _s(r.get("campaign_id"))
            if d is None or not cid:
                continue
            if (cid, d) in seen:
                self.dupes.append(f"{cid} {d}")
                continue
            seen.add((cid, d))
            if V.boolean(r.get("complete_day")) is not True:
                self.incomplete.add(d)
                continue
            cost = ctx.money(r.get("cost"))
            if cost is None:
                self.unknown.add(d)
                continue
            self.rows.append({"campaign_id": cid, "budget_id": _s(r.get("budget_id")), "date": d, "cost": cost,
                              "billed": ctx.money(r.get("billed_cost_if_available"))})

    def dates(self, rows) -> set[date]:
        return {r["date"] for r in rows}


def _plans(ctx) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = {}
    for r in ctx.rows(_PLAN):
        key = (_s(r.get("scope_type")).lower(), _s(r.get("scope_id")))
        if key[1]:
            out.setdefault(key, []).append(r)
    return {k: sorted(v, key=lambda r: _s(r.get("date"))) for k, v in sorted(out.items())}


def _one(rows, col, conv) -> tuple[object, bool]:
    vals = {conv(r.get(col)) for r in rows if r.get(col) is not None}
    vals.discard(None)
    return (next(iter(vals)) if len(vals) == 1 else None), len(vals) > 1


def run(ctx) -> None:
    """Run daily reconstruction, MTD pacing, weekday anomaly, utilization, alert history and rule-inventory checks.

    Rules:   Only complete_day rows; missing MTD dates → partial. Pacing Warning only against APPROVED plan ratio bounds
             (0.85/1.15 defaults = observation). Matched-basis hard-cap excess >= spend_floor → Critical, smaller →
             Warning; projections and daily overdelivery are Info. Anomalies need 30 prior complete days + |delta| >=
             spend_floor and are 'unexplained' only via ai_review. 'monitoring_absent' needs a manifest-complete rule
             inventory.
    """
    plan_cols = ["scope_id", "scope_type", "date", "approved_month_total", "planned_spend", "cap_or_target",
                 "spend_basis", "timezone", "owner"]
    daily_cols = ["campaign_id", "date", "budget_id", "cost", "complete_day"]

    scope = ctx.check("scope_resolution", "Monitored scopes, approved caps and spend basis (step 1)", {_PLAN: plan_cols})
    plans = _plans(ctx) if scope.runnable else {}
    if scope.runnable:
        tz = ctx.account.get("time_zone")
        types = sorted({k[0] for k in plans})
        for (st, sid), rows in plans.items():
            ptz, _ = _one(rows, "timezone", _s)
            if tz and ptz and ptz != tz:
                scope.partial(f"scope {st}:{sid} plan timezone {ptz} differs from account {tz}")
            scope.observe(f"Plan scope {st}:{sid}", scope_type=st, scope_id=sid, plan_rows=len(rows),
                          cap_or_target=_one(rows, "cap_or_target", _s)[0], spend_basis=_one(rows, "spend_basis", _s)[0],
                          owner=_one(rows, "owner", _s)[0], approved_at=_one(rows, "approved_at", _s)[0])
        if "account" in types and len(types) > 1:
            scope.observe("Overlapping account and sub-account scopes: exposure is never summed across scopes",
                          scope_types=types)

    rec = ctx.check("daily_reconstruction", "Complete-day spend reconstruction (step 2)", {_DAILY: daily_cols})
    daily = _Daily(ctx) if rec.runnable else None
    if daily:
        if daily.dupes:
            rec.partial(f"duplicate campaign-day rows ignored: {sorted(daily.dupes)[:5]}")
        if daily.incomplete:
            rec.partial(f"{len(daily.incomplete)} dates with incomplete-day rows excluded")
        if daily.unknown:
            rec.partial(f"{len(daily.unknown)} dates with unknown cost excluded")
        ds = sorted(daily.dates(daily.rows))
        rec.observe("Complete-day spend reconstructed", rows=len(daily.rows), first=ds[0] if ds else None,
                    last=ds[-1] if ds else None, cost=sum(r["cost"] for r in daily.rows), currency=ctx.currency,
                    campaigns=len({r["campaign_id"] for r in daily.rows}))

    pace = ctx.check("mtd_pacing", "MTD actual vs dated plan and approved caps (steps 3-4)",
                     {_PLAN: plan_cols, _DAILY: daily_cols})
    end = ctx.as_of
    if pace.runnable and daily:
        if end is None:
            pace.skip("report end date unknown")
        else:
            _pacing(ctx, pace, plans, daily, end)

    anom = ctx.check("weekday_anomaly", "Last complete day vs same-weekday baseline (step 5)", {_DAILY: daily_cols})
    if anom.runnable and daily and end is not None:
        _anomaly(ctx, anom, daily, end)

    util = ctx.check("daily_budget_utilization", "Daily spend vs dated average daily budget (index #33/#37/#41)",
                     {_DAILY: daily_cols, _HIST: ["budget_id", "effective_from", "effective_to", "amount",
                                                  "member_campaign_ids"]})
    if util.runnable and daily:
        _utilization(ctx, util, daily)

    log = ctx.check("alert_history", "Trigger duration, delivery and resolution from logs (step 6)",
                    {_LOG: ["scope_id", "rule_id", "evaluated_at", "condition", "observed_value", "threshold",
                            "triggered", "notification_status", "resolved_at"]})
    if log.runnable:
        _history(ctx, log, end)

    rules = ctx.check("rule_inventory", "Current local rule inventory and rule proposal (step 7)",
                      {_RULES: ["scope_id", "rule_id", "version", "enabled", "cadence", "timezone", "lookback",
                                "data_lag", "condition", "severity", "dedupe_key", "cooldown", "owner_role",
                                "approved_state"], _PLAN: plan_cols})
    if rules.runnable:
        _rules(ctx, rules, plans)

    back = ctx.check("rule_backtest", "Proposed pacing rule evaluated on historical rows (step 8)",
                     {_PLAN: plan_cols, _DAILY: daily_cols})
    if back.runnable and daily:
        _backtest(ctx, back, plans, daily)


def _pacing(ctx, pace, plans, daily, end) -> None:
    start = end.replace(day=1)
    mtd = _days(start, end)
    floor = ctx.params.get("spend_floor")
    for (st, sid), prow in plans.items():
        ent = {"scope_type": st, "scope_id": sid, "month": start.isoformat()[:7]}
        srows = _scope_rows(daily.rows, st, sid)
        if srows is None:
            pace.partial(f"scope {st}:{sid}: unsupported scope_type")
            continue
        month_plan = [r for r in prow if (d := V.parse_date(r.get("date"))) and d.replace(day=1) == start]
        plan_mtd = [r for r in month_plan if V.parse_date(r.get("date")) <= end]
        planned = [ctx.money(r.get("planned_spend")) for r in plan_mtd]
        plan_days = {V.parse_date(r.get("date")) for r in plan_mtd}
        if not plan_mtd or None in planned or plan_days != set(mtd):
            pace.partial(f"scope {st}:{sid}: dated plan does not cover every MTD day {start}..{end}")
            continue
        basis = (_one(prow, "spend_basis", _s)[0] or "").lower()
        key = "billed" if basis.startswith("bill") else "cost" if basis in ("cost", "ads_cost", "") else None
        if key is None:
            pace.partial(f"scope {st}:{sid}: unknown spend_basis {basis!r}")
            continue
        in_mtd = [r for r in srows if start <= r["date"] <= end]
        missing = [d for d in mtd if d in daily.incomplete or d in daily.unknown or d not in daily.dates(in_mtd)]
        if missing:
            pace.partial(f"scope {st}:{sid}: {len(missing)} MTD dates incomplete/missing; no monthly status",
                         [f"{_DAILY}:date {d}" for d in missing[:5]])
            continue
        vals = [r[key] for r in in_mtd]
        if None in vals:
            pace.partial(f"scope {st}:{sid}: {basis} basis values missing; matched-basis spend unknown")
            continue
        actual, expected = sum(vals), sum(planned)
        ratio = V.ratio(actual, expected)
        lo, lo_amb = _one(prow, "warning_lower_ratio", V.num)
        hi, hi_amb = _one(prow, "warning_upper_ratio", V.num)
        calc = {"actual_mtd": actual, "expected_mtd": expected, "ratio": ratio, "spend_basis": key,
                "window": [start, end], "days": len(mtd), "currency": ctx.currency,
                "approved_lower_ratio": lo, "approved_upper_ratio": hi, "owner": _one(prow, "owner", _s)[0]}
        pace.observe(f"Scope {st}:{sid}: MTD {actual:.2f} vs plan {expected:.2f}", **ent, **calc)
        if lo_amb or hi_amb:
            pace.partial(f"scope {st}:{sid}: conflicting approved ratios across plan rows")
        elif ratio is not None and lo is not None and hi is not None and not (lo <= ratio <= hi):
            pace.finding("pacing_outside_approved_bounds", "Warning", ent,
                         f"Scope {st}:{sid} MTD pacing ratio {ratio:.2f} outside approved [{lo:g}, {hi:g}]",
                         evidence=calc, calculation={"ratio": "actual_mtd / sum(dated planned_spend)"},
                         recommendation="Owner reviews pacing against the plan; any budget change needs approval.",
                         uncertainty="Pacing ratio is a plan comparison, not a forecast of month-end spend.",
                         owner=calc["owner"])
        elif ratio is not None and (lo is None or hi is None):
            pace.observe(f"Scope {st}:{sid}: no approved ratios; unapproved triage defaults shown", **ent,
                         default_bounds=_DEFAULT_BOUNDS,
                         outside_defaults=not (_DEFAULT_BOUNDS[0] <= ratio <= _DEFAULT_BOUNDS[1]))
        kind = (_one(prow, "cap_or_target", _s)[0] or "").upper()
        cap, cap_amb = _one(month_plan, "approved_month_total", ctx.money)
        if kind not in _CAP or cap is None or cap_amb:
            if kind in _CAP:
                pace.partial(f"scope {st}:{sid}: hard cap amount missing or ambiguous")
            continue
        excess = actual - cap
        cap_calc = {**calc, "approved_hard_cap": cap, "excess": excess, "spend_floor": floor.value,
                    "spend_floor_source": floor.source}
        if excess > 0:
            if floor.value is None:
                pace.partial(f"scope {st}:{sid}: spend_floor unresolved ({floor.reason}); cap materiality unknown")
                sev = "Warning"
            else:
                sev = "Critical" if excess >= floor.value else "Warning"
            pace.finding("hard_cap_breach", sev, ent,
                         f"Scope {st}:{sid} {key} MTD {actual:.2f} exceeds approved hard cap {cap:.2f} by {excess:.2f}",
                         evidence=cap_calc, calculation={"excess": "actual_mtd - approved_month_total"},
                         recommendation="Escalate to the plan owner; any budget/pause action requires approval.",
                         uncertainty="Matched-basis spend through the last complete day; later adjustments/credits unknown.",
                         owner=calc["owner"])
            continue
        remaining = [ctx.money(r.get("planned_spend")) for r in month_plan if V.parse_date(r.get("date")) > end]
        if remaining and None not in remaining and actual + sum(remaining) > cap:
            pace.finding("forecast_cap_risk", "Info", ent,
                         f"Scope {st}:{sid}: actual MTD plus remaining planned spend exceeds hard cap {cap:.2f}",
                         evidence={**cap_calc, "remaining_planned": sum(remaining)},
                         calculation={"projection": "actual_mtd + sum(remaining dated planned_spend)"},
                         recommendation="Review the plan before month end; this is a forecast, not a breach.",
                         uncertainty="Assumes remaining days spend exactly as planned.", owner=calc["owner"])


def _anomaly(ctx, anom, daily, end) -> None:
    by_c: dict[str, dict[date, float]] = {}
    for r in daily.rows:
        by_c.setdefault(r["campaign_id"], {})[r["date"]] = r["cost"]
    hist_changes = sorted({_s(h.get("effective_from")) for h in ctx.rows(_HIST) if h.get("effective_from")})
    for cid in sorted(by_c):
        days = by_c[cid]
        target = max(days)
        prior = _days(target - timedelta(days=30), target - timedelta(days=1))
        gaps = [d for d in prior if d not in days]
        if gaps:
            anom.partial(f"campaign {cid}: {len(gaps)} of 30 prior complete days missing; no baseline")
            continue
        same = [days[target - timedelta(days=7 * k)] for k in range(1, 5)]
        base = sum(same) / 4
        change = V.ratio(days[target] - base, base)
        ent = {"campaign_id": cid, "date": target.isoformat()}
        calc = {"cost": days[target], "baseline_same_weekday_mean": base, "baseline_days": 4, "change": change,
                "screen": _ANOMALY, "currency": ctx.currency}
        if change is None:
            anom.observe(f"Campaign {cid}: zero baseline; change undefined", **ent, **calc)
            continue
        floor = ctx.params.get("spend_floor", cid)
        delta = abs(days[target] - base)
        if abs(change) <= _ANOMALY:
            anom.observe(f"Campaign {cid}: {target} within ±30% of weekday baseline", **ent, **calc)
            continue
        if floor.value is None or delta < floor.value:
            anom.observe(f"Campaign {cid}: {change:+.0%} vs weekday baseline below materiality", **ent, **calc,
                         spend_floor=floor.value, spend_floor_reason=floor.reason)
            continue
        anom.review("unexplained_spend_anomaly", ent,
                    f"Is the {change:+.0%} change in campaign {cid} spend on {target} vs its weekday baseline unexplained?",
                    evidence={**calc, "abs_delta": delta, "spend_floor": floor.value, "spend_floor_source": floor.source,
                              "budget_history_change_dates": hist_changes,
                              "budget_constraints": ctx.profile.get("budget_constraints") or {}},
                    outcomes={"unexplained_material": {"severity": "Warning", "recommendation":
                                                       "Investigate the cause with the owner; no automatic escalation."},
                              "explained": {"severity": None, "recommendation": "Document the seasonality/change."},
                              "uncertain": {"severity": "Info", "recommendation": "Request the change/seasonality log."}},
                    guidance="Only documented seasonality, promotions or budget changes explain a deviation; "
                             "no fraud implication.")


def _utilization(ctx, util, daily) -> None:
    thr = V.num(ctx.profile.get("budget_overdelivery_ratio")) or 1.0
    reach = V.num(ctx.profile.get("budget_alert_reach_ratio"))
    hist: dict[str, list[dict]] = {}
    for h in ctx.rows(_HIST):
        bid = _s(h.get("budget_id"))
        f = V.parse_date(h.get("effective_from"))
        if bid and f:
            hist.setdefault(bid, []).append({"from": f, "to": V.parse_date(h.get("effective_to")),
                                             "amount": ctx.money(h.get("amount")),
                                             "members": sorted(set(V.split_list(h.get("member_campaign_ids"), _SEPS)))})
    for bid in sorted(hist):
        cost_by_day: dict[date, float] = {}
        mem_by_day: dict[date, set] = {}
        for r in daily.rows:
            if r["budget_id"] == bid:
                cost_by_day[r["date"]] = cost_by_day.get(r["date"], 0.0) + r["cost"]
                mem_by_day.setdefault(r["date"], set()).add(r["campaign_id"])
        over, reached, evaluated, gaps = [], [], 0, 0
        for d in sorted(cost_by_day):
            regs = [h for h in hist[bid] if h["from"] <= d and (h["to"] is None or d <= h["to"])]
            if len(regs) != 1 or not regs[0]["amount"]:
                gaps += 1
                continue
            h = regs[0]
            if h["members"] and not set(h["members"]) <= mem_by_day[d]:
                gaps += 1  # member rows missing that day: pool spend unknown
                continue
            evaluated += 1
            ratio = cost_by_day[d] / h["amount"]
            if ratio > thr:
                over.append({"date": d, "cost": cost_by_day[d], "daily_amount": h["amount"], "ratio": ratio})
            if reach is not None and ratio >= reach:
                reached.append(d)
        if gaps:
            util.partial(f"budget {bid}: {gaps} days without a unique dated amount or complete member rows")
        util.observe(f"Budget {bid}: daily utilization evaluated on {evaluated} complete days", budget_id=bid,
                     overdelivery_days=len(over), overdelivery_ratio=thr, reach_ratio=reach,
                     reach_days=len(reached) if reach is not None else None,
                     reach_ratio_source="profile.budget_alert_reach_ratio" if reach is not None else "not supplied")
        if over:
            top = max(over, key=lambda x: x["ratio"])
            util.finding("daily_overdelivery", "Info", {"budget_id": bid},
                         f"Budget {bid} spent above {thr:g}x its dated daily amount on {len(over)} of {evaluated} days "
                         f"(max {top['ratio']:.2f}x on {top['date']})",
                         evidence={"days": over, "evaluated_days": evaluated, "ratio_threshold": thr,
                                   "ratio_source": "profile.budget_overdelivery_ratio" if ctx.profile.get(
                                       "budget_overdelivery_ratio") is not None else "definition (cost > amount)"},
                         calculation={"ratio": "pool complete-day cost / dated daily amount"},
                         recommendation="Daily amounts are average delivery budgets; compare with the monthly cap "
                                        "(mtd_pacing) before any action. No pausing is proposed.",
                         uncertainty="Daily overdelivery alone is expected platform behaviour, not a cap breach.")


def _history(ctx, log, end) -> None:
    rows = ctx.rows(_LOG)
    stamps = sorted(d for r in rows if (d := V.parse_date(r.get("evaluated_at"))))
    if end is not None and (not stamps or stamps[0] > end - timedelta(days=29)):
        log.partial("logs do not reach back 30 days; trigger durations are lower bounds")
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((_s(r.get("scope_id")), _s(r.get("rule_id"))), []).append(r)
    for (sid, rid), g in sorted(groups.items()):
        g.sort(key=lambda r: _s(r.get("evaluated_at")))
        trig = [r for r in g if V.boolean(r.get("triggered")) is True]
        failed = [_s(r.get("evaluated_at")) for r in trig
                  if _s(r.get("notification_status")).upper() not in ("SENT", "DELIVERED", "ACKNOWLEDGED")]
        last = g[-1]
        active = V.boolean(last.get("triggered")) is True and last.get("resolved_at") is None
        log.observe(f"Rule {rid} on {sid}: {len(trig)} triggers", scope_id=sid, rule_id=rid, evaluations=len(g),
                    first_trigger=_s(trig[0].get("evaluated_at")) if trig else None,
                    last_trigger=_s(trig[-1].get("evaluated_at")) if trig else None,
                    currently_active=active, undelivered_notifications=len(failed),
                    note="First observed trigger lower-bounds duration.")
        if failed:
            log.finding("alert_notification_undelivered", "Info", {"scope_id": sid, "rule_id": rid},
                        f"Rule {rid} triggered on {sid} without a delivered notification {len(failed)} time(s)",
                        evidence={"evaluated_at": failed, "currently_active": active},
                        recommendation="Fix the notification route/owner acknowledgement locally.",
                        uncertainty="Delivery status as logged; recipient receipt not otherwise evidenced.")


def _rules(ctx, rules, plans) -> None:
    inv = ctx.table(_RULES)
    certified = inv is not None and inv.complete is True and not inv.truncated
    by_scope: dict[str, list[dict]] = {}
    for r in ctx.rows(_RULES):
        by_scope.setdefault(_s(r.get("scope_id")), []).append(r)
    tz = ctx.account.get("time_zone")
    for (st, sid), prow in plans.items():
        active = [r for r in by_scope.get(sid, []) if V.boolean(r.get("enabled")) is True
                  and _s(r.get("approved_state")).upper() in ("APPROVED", "ACTIVE")]
        lo, _ = _one(prow, "warning_lower_ratio", V.num)
        hi, _ = _one(prow, "warning_upper_ratio", V.num)
        proposal = {"scope_type": st, "scope_id": sid, "condition": "mtd_actual / sum(dated planned_spend) outside "
                    f"[{lo if lo is not None else 'owner lower'}, {hi if hi is not None else 'owner upper'}]",
                    "window": "month to last complete day", "data_lag": "complete days only", "timezone": tz,
                    "cadence": "daily after complete-day close", "dedupe_key": f"{sid}:pacing:month",
                    "cooldown": "until resolved or month end", "recipient_role": _one(prow, "owner", _s)[0],
                    "action": "notify_only", "approval": "owner approval required before implementation"}
        if not active:
            if not certified:
                rules.partial(f"scope {st}:{sid}: rule inventory not manifest-complete; absence not provable")
            else:
                rules.finding("monitoring_absent", "Info", {"scope_type": st, "scope_id": sid},
                              f"No enabled approved budget alert rule covers plan scope {st}:{sid}",
                              evidence={"rules_for_scope": len(by_scope.get(sid, [])), "proposal": proposal},
                              recommendation="Review the proposed notify-only rule with the owner; nothing is configured.",
                              uncertainty="Monitoring outside the supplied inventory is unknown.")
        gaps = sorted({f for r in active for f in ("dedupe_key", "cooldown", "owner_role", "timezone")
                       if not _s(r.get(f))} | ({"timezone_mismatch"} if any(
                           tz and _s(r.get("timezone")) and _s(r.get("timezone")) != tz for r in active) else set()))
        rules.observe(f"Scope {st}:{sid}: {len(active)} enabled approved rules", scope_id=sid,
                      rule_ids=sorted(_s(r.get("rule_id")) for r in active), rule_gaps=gaps, proposal=proposal)


def _backtest(ctx, back, plans, daily) -> None:
    for (st, sid), prow in plans.items():
        lo, _ = _one(prow, "warning_lower_ratio", V.num)
        hi, _ = _one(prow, "warning_upper_ratio", V.num)
        bounds, src = ((lo, hi), "approved plan") if lo is not None and hi is not None else (_DEFAULT_BOUNDS,
                                                                                            "unapproved triage default")
        srows = _scope_rows(daily.rows, st, sid)
        if srows is None:
            continue
        cost = {}
        for r in srows:
            cost[r["date"]] = cost.get(r["date"], 0.0) + r["cost"]
        plan = {V.parse_date(r.get("date")): ctx.money(r.get("planned_spend")) for r in prow}
        cum_a = cum_e = 0.0
        month, triggers, missing, evaluated = None, [], [], 0
        for d in sorted(k for k in plan if k):
            if d.replace(day=1) != month:
                month, cum_a, cum_e = d.replace(day=1), 0.0, 0.0
            if d not in cost or d in daily.incomplete or plan[d] is None:
                missing.append(d)
                month = None  # cumulative chain broken until next month
                continue
            if month is None:
                continue
            cum_a += cost[d]
            cum_e += plan[d]
            ratio = V.ratio(cum_a, cum_e)
            evaluated += 1
            if ratio is not None and not (bounds[0] <= ratio <= bounds[1]):
                triggers.append(d)
        if missing:
            back.partial(f"scope {st}:{sid}: {len(missing)} plan dates without complete spend")
        back.observe(f"Scope {st}:{sid}: proposed pacing rule would trigger on {len(triggers)} of {evaluated} days",
                     scope_id=sid, bounds=bounds, bounds_source=src, trigger_dates=triggers[:31],
                     missing_dates=[str(d) for d in missing[:31]],
                     note="Not activated; early-month ratios are volatile (false-positive risk).")


def verify(ctx, item, decision) -> list[str]:
    """Rules: proposals must stay notify-only; no pause/budget mutation text is accepted."""
    text = str(decision.get("proposal") or "").lower()
    hits = [w for w in _MUTATING if w in text]
    return [f"proposal must be notify-only; found mutating action {hits}"] if hits else []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
