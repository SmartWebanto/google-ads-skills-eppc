"""check.py — skill-123 deterministic MTD pacing, cap reconciliation and weekday cohorts for bounded allocation proposals.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-123-budget-pacing-daily-allocation-scripts/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #36 Flexible Budgets (Google developers) — clean-room reimplementation of remaining-budget / remaining
         planned-day arithmetic as a request-only daily-budget observation; no budget is set
rules:   Complete days only: date <= min(ctx.as_of, snapshot - 1 day); the snapshot day is incomplete.
         Daily spend is summed once per campaign/date (duplicates ignored) and grouped by the row's own budget_id,
         so shared budgets and caps are never multiplied by member campaigns. Current daily budget x days is never used.
         MTD ratio = actual complete MTD cost / approved planned-to-date spend (plan rows dated month start..last
         complete day). Zero/unknown planned-to-date → ratio unknown. Warning iff ratio > 1.10 or < 0.80 with complete MTD
         coverage; these are triage heuristics, not billing-limit breaches.
         Critical only for a verified breach: complete MTD cost > approved_monthly_cap by >= spend_floor. A smaller or
         floor-unresolved breach is a provisional Info plus review whose Critical outcome requires proposal.evidence_ref.
         Weekday efficiency uses mature days only (date + lag <= snapshot), full Mon-Sun weeks, same goal group, and
         min_conversions per weekday cohort. Weekday differences never become fixed multipliers.
         verify(): a bounded experiment must keep every weekday shift within maximum_change, must not increase planned
         remaining spend, and must name monitoring and rollback.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
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

SKILL = "skill-123-budget-pacing-daily-allocation-scripts"
VERSION = "1.0.0"

DAILY = "custom/allocation_daily"
HISTORY = "custom/budget_history"
PLAN = "external/allocation_plan"
OVER, UNDER = 1.10, 0.80
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _last_complete(ctx) -> date | None:
    cands = [d for d in (ctx.as_of, ctx.snapshot - timedelta(days=1) if ctx.snapshot else None) if d]
    return min(cands) if cands else None


def _daily_rows(ctx, chk, last: date | None) -> list[dict]:
    """Complete-day rows, one per campaign/date."""
    seen, out, dupes, late, bad = set(), [], 0, 0, 0
    for r in sorted(ctx.rows(DAILY), key=lambda r: (str(r.get("campaign_id")), str(r.get("date")))):
        d = V.parse_date(r.get("date"))
        if d is None:
            bad += 1
            continue
        if last is None or d > last:
            late += 1
            continue
        key = (str(r.get("campaign_id")), d)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        out.append({"campaign_id": key[0], "date": d, "budget_id": str(r.get("budget_id") or ""),
                    "cost": ctx.money(r.get("cost")), "conversions": V.num(r.get("conversions")),
                    "conversion_value": ctx.money(r.get("conversion_value")),
                    "goal": str(r.get("goal_id") or "") or None})
    if dupes:
        chk.partial(f"{dupes} duplicate campaign/date rows ignored")
    if bad:
        chk.partial(f"{bad} rows with unparseable dates ignored")
    if late:
        chk.observe("Incomplete/after-report days excluded", rows=late, last_complete_day=last)
    return out


def _history(ctx) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in ctx.rows(HISTORY):
        out.setdefault(str(r.get("budget_id")), []).append(
            {"from": V.parse_date(r.get("effective_from")), "to": V.parse_date(r.get("effective_to")),
             "amount": ctx.money(r.get("amount")), "currency": (r.get("currency") or "").upper() or None,
             "campaigns": set(V.split_list(r.get("campaign_ids"), (";", "|", ",")))})
    return out


def _effective(hist: list[dict], d: date) -> dict | None:
    rows = [h for h in hist if h["from"] and h["from"] <= d and (h["to"] is None or d <= h["to"])]
    return rows[0] if len(rows) == 1 else None


def run(ctx) -> None:
    """Run budget-join, MTD pacing/cap, daily-overdelivery, weekday-cohort and allocation-proposal checks.

    Rules:   Unknown last complete day skips join/pacing/weekday/daily_cap; cap breach is Critical only when
             excess >= params spend_floor, else Info + ai_review; pacing ratio outside 1.10/0.80 → Warning.
             Weekday cohorts need ctx.lag_days + snapshot and params min_conversions over >= 2 full weeks; a pattern
             without plan marginal_response_assumptions → Info, with them → ai_review experiment (never a multiplier).
             Daily overdelivery vs budget_history amount and flexible-budget arithmetic are observe-only, never findings.
    """
    last = _last_complete(ctx)
    join = ctx.check("daily_join", "Join dated spend to budget memberships",
                     {DAILY: ["campaign_id", "date", "budget_id", "cost"],
                      HISTORY: ["budget_id", "effective_from", "effective_to", "amount", "campaign_ids"]})
    pacing = ctx.check("mtd_pacing", "MTD pacing against the approved plan and cap",
                       {DAILY: ["campaign_id", "date", "budget_id", "cost"],
                        PLAN: ["plan_id", "budget_id", "date", "monthly_cap_id", "approved_monthly_cap",
                               "planned_daily_spend"]})
    weekday = ctx.check("weekday_efficiency", "Weekly and weekday efficiency by goal group",
                        {DAILY: ["campaign_id", "date", "cost", "conversions", "goal_id"]})
    daily_cap = ctx.check("daily_vs_cap", "Platform daily overdelivery versus client cap",
                          {DAILY: ["campaign_id", "date", "budget_id", "cost"],
                           HISTORY: ["budget_id", "effective_from", "effective_to", "amount", "campaign_ids"]})
    proposal = ctx.check("allocation_proposal", "Bounded allocation experiment proposal",
                         {DAILY: ["campaign_id", "date", "cost", "conversions", "goal_id"]})
    plan_cols = ["plan_id", "budget_id", "date", "goal_group", "maximum_change", "marginal_response_assumptions", "owner"]
    plan_t = ctx.table(PLAN)
    if proposal.runnable and (plan_t is None or plan_t.missing(plan_cols)):
        proposal.partial("no approved allocation plan assumptions: experiments cannot be proposed",
                         [f"{PLAN} (file)"] if plan_t is None else [f"{PLAN}:{c}" for c in plan_t.missing(plan_cols)])
    if last is None:
        for c in (join, pacing, weekday, daily_cap):
            if c.runnable:
                c.skip("last complete account-local day unknown (account period end/snapshot missing)", ["account:date_range_end"])
    rows = _daily_rows(ctx, join if join.runnable else pacing, last) if ctx.table(DAILY) is not None and last else []
    hist = _history(ctx) if ctx.table(HISTORY) is not None else {}
    camp_status = {str(c.get("id")): str(c.get("status") or "").upper() for c in ctx.rows("campaigns")}

    # -- step 1: membership as of each day; shared budgets counted once
    budget_day: dict[tuple, float | None] = {}
    for r in rows:
        k = (r["budget_id"], r["date"])
        prev = budget_day.get(k, 0.0)
        budget_day[k] = None if prev is None or r["cost"] is None else prev + r["cost"]
    if join.runnable:
        no_hist = mismatch = 0
        for r in rows:
            h = _effective(hist.get(r["budget_id"], []), r["date"])
            if h is None:
                no_hist += 1
            elif h["campaigns"] and r["campaign_id"] not in h["campaigns"]:
                mismatch += 1
        currencies = sorted({h["currency"] for hs in hist.values() for h in hs if h["currency"]})
        if currencies and currencies != [ctx.currency]:
            join.partial(f"budget_history currencies {currencies} differ from account {ctx.currency}")
        if no_hist:
            join.partial(f"{no_hist} spend rows without exactly one effective budget_history row")
        if mismatch:
            join.partial(f"{mismatch} spend rows whose campaign is not in the budget's campaign_ids that day")
        dates = sorted({r["date"] for r in rows})
        if len(dates) < 90:
            join.partial(f"{len(dates)} complete days < 90 required")
        shared = sorted({b for b, d in budget_day if len({r["campaign_id"] for r in rows
                                                            if r["budget_id"] == b and r["date"] == d}) > 1})
        inactive = sorted({r["campaign_id"] for r in rows if camp_status.get(r["campaign_id"]) != "ENABLED"})
        join.observe("Daily spend joined to budgets as of each day", days=len(dates),
                     first_day=dates[0] if dates else None, last_complete_day=last, campaigns=len({r["campaign_id"] for r in rows}),
                     budgets=len({b for b, _ in budget_day}), shared_budgets=shared,
                     historical_or_inactive_campaigns=inactive, rows_without_history=no_hist,
                     membership_mismatches=mismatch,
                     total_cost=None if any(r["cost"] is None for r in rows) else sum(r["cost"] for r in rows))

    # -- step 2 + 4: MTD pacing, cap, remaining-day arithmetic (index #36)
    plan_rows = ctx.rows(PLAN)
    if pacing.runnable and last:
        month_start = last.replace(day=1)
        caps: dict[str, list[dict]] = {}
        for p in plan_rows:
            d = V.parse_date(p.get("date"))
            if d and d.year == last.year and d.month == last.month:
                caps.setdefault(str(p.get("monthly_cap_id")), []).append({**p, "_d": d})
        if not caps:
            pacing.partial(f"no allocation_plan rows for {month_start:%Y-%m}")
        first_day = min((r["date"] for r in rows), default=None)
        floor = ctx.params.get("spend_floor")
        for cap_id, prs in sorted(caps.items()):
            cap_vals = {ctx.money(p.get("approved_monthly_cap")) for p in prs}
            cap = next(iter(cap_vals)) if len(cap_vals) == 1 else None
            budgets = sorted({str(p.get("budget_id")) for p in prs})
            seen, dupes = {}, 0
            for p in prs:
                k = (str(p.get("budget_id")), p["_d"])
                if k in seen:
                    dupes += 1
                    continue
                seen[k] = ctx.money(p.get("planned_daily_spend"))
            if dupes:
                pacing.partial(f"cap {cap_id}: {dupes} duplicate budget/date plan rows ignored")
            planned_vals = [v for (b, d), v in seen.items() if d <= last]
            planned = None if any(v is None for v in planned_vals) else sum(planned_vals)
            mtd_rows = [r for r in rows if r["budget_id"] in budgets and month_start <= r["date"] <= last]
            covered = first_day is not None and first_day <= month_start
            actual = None if not covered or any(r["cost"] is None for r in mtd_rows) else sum(r["cost"] for r in mtd_rows)
            remaining_days = sorted({d for (b, d), v in seen.items() if d > last and (v or 0) > 0})
            remaining = None if cap is None or actual is None else cap - actual
            ratio = V.ratio(actual, planned)
            ev = {"monthly_cap_id": cap_id, "budget_ids": budgets, "window": [month_start, last],
                  "actual_mtd_cost": actual, "planned_to_date": planned, "pacing_ratio": ratio,
                  "approved_monthly_cap": cap, "remaining_budget": remaining,
                  "remaining_planned_active_days": len(remaining_days),
                  "required_remaining_daily_average": V.ratio(remaining, len(remaining_days)) if remaining is not None else None,
                  "owner": sorted({str(p.get("owner")) for p in prs if p.get("owner")}),
                  "mtd_rows": len(mtd_rows), "source": f"{DAILY} + {PLAN}"}
            entity = {"monthly_cap_id": cap_id}
            if cap is None:
                pacing.partial(f"cap {cap_id}: approved_monthly_cap missing or inconsistent ({sorted(map(str, cap_vals))})")
            if not covered:
                pacing.partial(f"cap {cap_id}: daily spend does not cover {month_start}; MTD unknown")
            pacing.observe(f"Cap {cap_id}: MTD pacing arithmetic", **ev)
            if cap is not None and actual is not None and actual > cap:
                excess = actual - cap
                material = floor.value is not None and excess >= floor.value
                f = pacing.finding("approved_cap_breach", "Critical" if material else "Info", entity,
                                   f"Complete MTD cost {actual:.2f} {ctx.currency} exceeds approved cap {cap:.2f} "
                                   f"by {excess:.2f}", evidence={**ev, "excess": excess, "materiality_floor": floor.value,
                                                                  "materiality_source": floor.source or floor.reason},
                                   calculation={"excess": "actual_mtd_cost - approved_monthly_cap"},
                                   recommendation="Escalate to the cap owner; any budget change is a request-only proposal.",
                                   uncertainty="Complete days only; billing adjustments and invalid-click credits not included.")
                if not material:
                    pacing.review("approved_cap_breach", entity,
                                  f"Is the {excess:.2f} {ctx.currency} breach of cap {cap_id} a material client-cap failure?",
                                  evidence=ev, provisional=f,
                                  outcomes={"material_breach": {"severity": "Critical", "recommendation":
                                                                "Escalate; cite the client's cap policy (proposal.evidence_ref)."},
                                            "immaterial": {"severity": "Info", "recommendation": "Record; monitor next days."}},
                                  guidance="Critical needs proposal.evidence_ref to the client cap policy/materiality rule.")
            if ratio is not None and (ratio > OVER or ratio < UNDER):
                pacing.finding("mtd_pacing_deviation", "Warning", entity,
                               f"Cap {cap_id}: MTD cost is {ratio:.0%} of approved planned-to-date spend",
                               evidence={**ev, "screen": f"ratio > {OVER} or < {UNDER}"},
                               calculation={"pacing_ratio": "actual_mtd_cost / planned_to_date",
                                            "required_remaining_daily_average": "remaining_budget / remaining planned active days"},
                               recommendation="Review with the plan owner; a remaining-day daily average is a request-only "
                                              "proposal, not an automatic budget change.",
                               uncertainty="Triage heuristic; late-month plan shape and shared pools can explain deviation.")
            elif ratio is None:
                pacing.partial(f"cap {cap_id}: pacing ratio unknown (actual or planned-to-date unknown/zero)")
            # index #36: remaining-day average versus the budgets' amounts effective on the last complete day
            if remaining is not None and remaining_days:
                amounts = {b: (_effective(hist.get(b, []), last) or {}).get("amount") for b in budgets}
                current = None if any(v is None for v in amounts.values()) else sum(amounts.values())
                pacing.observe(f"Cap {cap_id}: flexible-budget arithmetic (request-only)", monthly_cap_id=cap_id,
                               required_remaining_daily_average=remaining / len(remaining_days),
                               current_daily_budget_total=current, budget_amounts=amounts,
                               note="Budget history amounts per budget_id, counted once; no change is applied.")

    # -- step 4: platform daily overdelivery is distinct from the client cap
    if daily_cap.runnable and rows:
        over, unknown = [], 0
        for (b, d), cost in sorted(budget_day.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            h = _effective(hist.get(b, []), d)
            if h is None or h["amount"] is None or cost is None:
                unknown += 1
            elif cost > h["amount"]:
                over.append({"budget_id": b, "date": d, "cost": cost, "daily_amount": h["amount"]})
        if unknown:
            daily_cap.partial(f"{unknown} budget/days without a known historical amount or cost")
        daily_cap.observe("Budget/days above the historical daily amount (platform overdelivery, not a cap breach)",
                          days_over=len(over), examples=over[:10], budget_days=len(budget_day))

    # -- step 3: weekday cohorts on mature, full weeks, per goal group
    cohorts: dict[str, dict] = {}
    if weekday.runnable and rows:
        if ctx.lag_days is None or ctx.snapshot is None:
            weekday.partial("conversion lag or snapshot unknown: no mature efficiency days")
            mature_end = None
        else:
            mature_end = min(last, ctx.snapshot - timedelta(days=ctx.lag_days))
        min_conv = ctx.params.get("min_conversions")
        if mature_end is not None:
            dates = sorted({r["date"] for r in rows if r["date"] <= mature_end})
            start = dates[0] + timedelta(days=(7 - dates[0].weekday()) % 7) if dates else None
            end = mature_end - timedelta(days=(mature_end.weekday() + 1) % 7) if dates else None
            for r in rows:
                if start is None or not (start <= r["date"] <= end):
                    continue
                g = r["goal"] or "unknown_goal"
                wd = WEEKDAYS[r["date"].weekday()]
                c = cohorts.setdefault(g, {}).setdefault(wd, {"cost": 0.0, "conversions": 0.0, "value": 0.0,
                                                               "weeks": set(), "unknown": 0, "value_unknown": 0})
                if r["cost"] is None or r["conversions"] is None:
                    c["unknown"] += 1
                    continue
                c["cost"] += r["cost"]
                c["conversions"] += r["conversions"]
                if r["conversion_value"] is None:
                    c["value_unknown"] += 1
                else:
                    c["value"] += r["conversion_value"]
                c["weeks"].add(r["date"] - timedelta(days=r["date"].weekday()))
            if any(r["goal"] is None for r in rows):
                weekday.partial("rows without goal_id grouped as unknown_goal; not compared with named goals")
            for g, wds in sorted(cohorts.items()):
                for wd in WEEKDAYS:
                    c = wds.get(wd)
                    if not c:
                        continue
                    c["weeks"] = len(c["weeks"])
                    c["sample_ok"] = min_conv.value is not None and c["conversions"] >= min_conv.value and c["weeks"] >= 2
                    c["cpa"] = V.ratio(c["cost"], c["conversions"])
                    c["roas"] = None if c["value_unknown"] else V.ratio(c["value"], c["cost"])
                weekday.observe(f"Goal group {g}: weekday cohorts over full mature weeks", goal_group=g,
                                window=[start, end], min_conversions=min_conv.value,
                                cohorts={wd: wds[wd] for wd in WEEKDAYS if wd in wds})

    # -- step 5: bounded experiment only with approved assumptions
    if proposal.runnable:
        for g, wds in sorted(cohorts.items()):
            ok = sorted(wd for wd, c in wds.items() if c.get("sample_ok"))
            cpas = {wds[wd]["cpa"] for wd in ok}
            if len(ok) < 2 or g == "unknown_goal" or None in cpas or len(cpas) < 2:
                proposal.observe(f"Goal group {g}: no comparable weekday pattern", qualifying_weekdays=ok)
                continue
            prs = [p for p in plan_rows if str(p.get("goal_group") or "") == g]
            assumptions = sorted({str(p.get("marginal_response_assumptions")) for p in prs
                                  if p.get("marginal_response_assumptions")})
            pattern = {wd: wds[wd]["cpa"] for wd in ok}
            entity = {"goal_group": g}
            if not assumptions:
                proposal.finding("weekday_pattern_without_assumptions", "Info", entity,
                                 f"Goal group {g}: weekday CPA differs across {len(ok)} qualifying weekdays; no approved "
                                 f"marginal-response assumptions",
                                 evidence={"weekday_cpa": pattern, "qualifying_weekdays": ok, "plan_rows": len(prs)},
                                 recommendation="Historical weekday averages do not establish marginal returns; request "
                                                "approved response assumptions before any allocation experiment.",
                                 uncertainty="Observational weekday averages; no fixed multiplier.")
                continue
            max_change = sorted({ctx.rate(p.get("maximum_change")) for p in prs} - {None})
            proposal.review("bounded_allocation_experiment", entity,
                            f"Should a bounded weekday allocation experiment be proposed for goal group {g}?",
                            evidence={"weekday_cpa": pattern, "assumptions": assumptions, "maximum_change": max_change,
                                      "owners": sorted({str(p.get("owner")) for p in prs if p.get("owner")}),
                                      "monthly_cap_ids": sorted({str(p.get("monthly_cap_id")) for p in prs})},
                            outcomes={"propose_bounded_experiment": {"severity": "Info", "recommendation":
                                      "Request-only experiment within the approved envelope with monitoring/rollback."},
                                      "no_experiment": {"severity": None, "recommendation": "Keep the current plan."}},
                            guidance="proposal = {weekday_shifts: {Mon: 0.1, ...} as fractions of planned daily spend, "
                                     "monitoring, rollback}. Shifts must stay within maximum_change and not raise "
                                     "planned remaining spend.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical breach needs evidence_ref; experiments are bounded and envelope-neutral."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_breach":
        return [] if proposal.get("evidence_ref") else ["material breach needs proposal.evidence_ref (client cap policy)"]
    if outcome != "propose_bounded_experiment":
        return []
    problems = []
    shifts = proposal.get("weekday_shifts")
    if not isinstance(shifts, dict) or not shifts:
        return ["proposal.weekday_shifts {weekday: fraction} required"]
    limits = item.evidence.get("maximum_change") or []
    limit = min(limits) if limits else None
    if limit is None:
        problems.append("no approved maximum_change for this goal group")
    last = _last_complete(ctx)
    planned: dict[str, float] = {}
    for p in ctx.rows(PLAN):
        d = V.parse_date(p.get("date"))
        v = ctx.money(p.get("planned_daily_spend"))
        if str(p.get("goal_group") or "") == item.entity["goal_group"] and d and last and d > last and v:
            planned[WEEKDAYS[d.weekday()]] = planned.get(WEEKDAYS[d.weekday()], 0.0) + v
    delta = 0.0
    for wd, s in sorted(shifts.items()):
        f = V.num(s)
        if wd not in WEEKDAYS or f is None:
            problems.append(f"invalid shift {wd}={s!r}")
            continue
        if limit is not None and abs(f) > limit + 1e-9:
            problems.append(f"{wd} shift {f:+.2%} exceeds maximum_change {limit:.2%}")
        delta += f * planned.get(wd, 0.0)
    if delta > 1e-6:
        problems.append(f"shifts raise planned remaining spend by {delta:.2f}; experiment must stay within the envelope")
    for k in ("monitoring", "rollback"):
        if not str(proposal.get(k) or "").strip():
            problems.append(f"proposal.{k} required")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
