"""check.py — skill-045 deterministic goal-matched allocation ledger, constraint and marginal-response checks.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-045-budget-allocation-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Cohorts come only from external/allocation_constraints; a cohort whose rows disagree on objective,
         goal_action_ids, value_basis or traffic_role is mixed → Info, never pooled or ranked. No cross-cohort ranking.
         Pooled CPA/ROAS = sums over lag-mature allocation_daily rows whose goal_cohort equals the cohort_id,
         one row per campaign/date/cohort; min_conversions applies per cohort.
         Constraint Warning only for documented minimum/maximum/total_cap with fully covered effective dates:
         maximum/total_cap breaches may be judged mid-window; a minimum only after the window ends.
         Marginal CPA = delta_cost/delta_conversions (both > 0); marginal ROAS = delta_value/delta_cost (delta_cost > 0);
         value unit when value_basis is not a count basis. Only approved/validated response rows are used; scenarios
         must respect min/max/total_cap and never change one member of a multi-member shared pool.
         Modeled trade-offs meeting the approved limit are Info candidates; historical averages alone never are.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-045-budget-allocation-optimization"
VERSION = "1.0.0"

CONSTR = "external/allocation_constraints"
DAILY = "custom/allocation_daily"
HISTORY = "custom/budget_history"
RESP = "external/allocation_response"
CONSTR_COLS = ["cohort_id", "scope_id", "objective", "goal_action_ids", "value_basis", "traffic_role"]
DAILY_COLS = ["campaign_id", "date", "goal_cohort", "budget_id", "cost", "conversions", "value", "lag_mature"]
RESP_COLS = ["model_id", "scope_id", "scenario_id", "baseline_spend", "baseline_outcome", "scenario_spend",
             "scenario_outcome", "uncertainty_low", "uncertainty_high", "approved_state"]
LIMIT_COLS = ("approved_CPA_or_ROAS_limit", "approved_cpa_or_roas_limit")
COUNT_BASES = ("", "conversions", "count", "none", "no_value", "conversion count")
SEPS = (";", "|", ",")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _dates(v) -> tuple[date | None, date | None]:
    s = _s(v)
    for sep in ("..", " to ", "/"):
        if sep in s:
            a, b = s.split(sep, 1)
            return V.parse_date(a.strip()), V.parse_date(b.strip())
    return None, None


def _limit(r) -> float | None:
    for c in LIMIT_COLS:
        if r.get(c) is not None:
            f = V.num(r.get(c))
            return f if f is not None and f > 0 else None
    return None


def _cohorts(ctx) -> tuple[dict, dict]:
    """cohort_id -> {rows, consistent, unit, objective...}; scope_id -> cohort_id."""
    groups: dict[str, list] = {}
    for r in ctx.rows(CONSTR):
        if _s(r.get("cohort_id")):
            groups.setdefault(_s(r.get("cohort_id")), []).append(r)
    out, scope_of = {}, {}
    for cid, rows in sorted(groups.items()):
        sig = {(V.norm_text(r.get("objective")), tuple(sorted(V.split_list(r.get("goal_action_ids"), SEPS))),
                V.norm_text(r.get("value_basis")), V.norm_text(r.get("traffic_role"))) for r in rows}
        basis = V.norm_text(rows[0].get("value_basis"))
        caps = sorted({ctx.money(r.get("total_cap")) for r in rows if ctx.money(r.get("total_cap")) is not None})
        out[cid] = {"rows": rows, "consistent": len(sig) == 1, "signatures": sorted(sig),
                    "unit": "conversions" if basis in COUNT_BASES else "value",
                    "total_cap": caps[0] if len(caps) == 1 else None, "cap_conflict": len(caps) > 1,
                    "limit": _limit(rows[0]) if len({_limit(r) for r in rows}) == 1 else None,
                    "scopes": sorted({_s(r.get("scope_id")) for r in rows if _s(r.get("scope_id"))})}
        for r in rows:
            scope_of[_s(r.get("scope_id"))] = cid
    return out, scope_of


def _members(ctx, scope: str, daily_campaigns: set) -> list[str]:
    """Campaign IDs for a scope: a campaign ID itself, else budget members (history, budgets, daily budget_id)."""
    camps = {_s(r.get("id")) for r in ctx.rows("campaigns")} | daily_campaigns
    if scope in camps:
        return [scope]
    ms = {m for r in ctx.rows(HISTORY) if _s(r.get("budget_id")) == scope for m in V.split_list(r.get("member_campaign_ids"), SEPS)}
    ms |= {m for b in ctx.rows("budgets") if _s(b.get("id")) == scope for m in V.split_list(b.get("campaign_ids"), SEPS)}
    ms |= {_s(r.get("campaign_id")) for r in ctx.rows(DAILY) if _s(r.get("budget_id")) == scope}
    return sorted(m for m in ms if m)


def _pool_size(ctx, campaign: str) -> tuple[str | None, int]:
    """Shared pool containing a campaign and its member count (history, budgets or campaigns.budget_id)."""
    for r in sorted(ctx.rows(HISTORY), key=lambda r: _s(r.get("effective_from")), reverse=True):
        ms = V.split_list(r.get("member_campaign_ids"), SEPS)
        if campaign in ms:
            return _s(r.get("budget_id")), len(ms)
    for b in ctx.rows("budgets"):
        ms = V.split_list(b.get("campaign_ids"), SEPS)
        if campaign in ms:
            return _s(b.get("id")), len(ms)
    return None, 1


def run(ctx) -> None:
    """Run cohort, pooled-ledger, constraint, donor screen, marginal-response, net-scenario and candidate checks.

    Rules:   Mixed cohorts → Info, never pooled; CPA/ROAS only for lag-mature rows reaching min_conversions.
             Warning only allocation_violates_constraint: maximum/total_cap spend overrun, minimum only after the
             effective window ends. Info modeled_tradeoff_candidate needs approved/validated response rows, an
             approved limit, and no min/max or shared-pool breach. No ai_review; nothing is executed.
    """
    min_conv = ctx.params.get("min_conversions")

    # step 1 — cohorts
    ch = ctx.check("cohort_definition", "Goal/value/role cohorts from the allocation brief (step 1)", {CONSTR: CONSTR_COLS})
    cohorts, scope_of = _cohorts(ctx) if ch.runnable else ({}, {})
    for cid, c in sorted(cohorts.items()):
        if c["consistent"]:
            ch.observe(f"Cohort {cid}: comparable scopes {c['scopes']}", cohort_id=cid, scopes=c["scopes"], unit=c["unit"],
                       signature=c["signatures"][0], total_cap=c["total_cap"], limit=c["limit"])
        else:
            ch.finding("mixed_goal_cohort", "Info", {"cohort_id": cid},
                       f"Cohort {cid}: scopes disagree on objective/goal actions/value basis/traffic role; not pooled or ranked",
                       evidence={"signatures": c["signatures"], "scopes": c["scopes"]},
                       recommendation="Split the cohort or supply an explicit business value exchange rate.",
                       uncertainty="Brand capture and acquisition are not exchangeable because both report conversions.")

    # step 2 — pooled ledger
    daily_rows: dict[tuple, dict] = {}
    dup = 0
    for r in ctx.rows(DAILY):
        k = (_s(r.get("campaign_id")), V.parse_date(r.get("date")), _s(r.get("goal_cohort")))
        if not k[0] or k[1] is None:
            continue
        if k in daily_rows:
            dup += 1
            daily_rows[k] = None
        else:
            daily_rows[k] = r
    daily_campaigns = {k[0] for k in daily_rows}
    all_dates = sorted({k[1] for k in daily_rows})
    led = ctx.check("pool_ledger", "Pooled mature outcomes within comparable cohorts (step 2)", {DAILY: DAILY_COLS, CONSTR: CONSTR_COLS})
    pooled: dict[str, dict] = {}
    scope_spend: dict[str, dict] = {}
    if led.runnable:
        if dup:
            led.partial(f"{dup} duplicate campaign/date/cohort rows excluded")
        if len(all_dates) < 30:
            led.partial(f"allocation_daily covers {len(all_dates)} days (<30)")
        for cid, c in sorted(cohorts.items()):
            if not c["consistent"]:
                continue
            tot = {"cost": 0.0, "conversions": 0.0, "value": 0.0}
            immature = 0
            for scope in c["scopes"]:
                members = _members(ctx, scope, daily_campaigns)
                sc = {"cost": 0.0, "members": members, "by_date": {}}
                for (camp, d, coh), r in sorted(daily_rows.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
                    if camp not in members or coh != cid or r is None:
                        continue
                    cost = ctx.money(r.get("cost"))
                    if cost is not None:
                        sc["cost"] += cost
                        sc["by_date"][d] = sc["by_date"].get(d, 0.0) + cost
                    if V.boolean(r.get("lag_mature")) is not True:
                        immature += 1
                        continue
                    conv, val = V.num(r.get("conversions")), ctx.money(r.get("value"))
                    tot["cost"] += cost or 0
                    tot["conversions"] += conv or 0
                    tot["value"] += val or 0
                scope_spend[scope] = sc
            if immature:
                led.partial(f"cohort {cid}: {immature} immature rows excluded from outcomes")
            ok = min_conv.value is not None and tot["conversions"] >= min_conv.value
            pooled[cid] = {**tot, "cpa": V.ratio(tot["cost"], tot["conversions"]) if ok else None,
                           "roas": V.ratio(tot["value"], tot["cost"]) if ok else None, "qualifies": ok}
            led.observe(f"Cohort {cid}: pooled mature outcomes from summed rows", cohort_id=cid, **pooled[cid],
                        min_conversions=min_conv.value, window=[all_dates[0], all_dates[-1]] if all_dates else None)
            if not ok:
                led.partial(f"cohort {cid}: conversions {tot['conversions']} below min_conversions")

    # step 3 — constraints (+ Warning row)
    cs = ctx.check("constraint_inventory", "Documented minimum/maximum/total-cap compliance (step 3)",
                   {CONSTR: ["cohort_id", "scope_id", "minimum_spend", "maximum_spend", "total_cap", "effective_dates"],
                    DAILY: DAILY_COLS})
    if cs.runnable:
        first, last = (all_dates[0], all_dates[-1]) if all_dates else (None, None)
        for cid, c in sorted(cohorts.items()):
            if c["cap_conflict"]:
                cs.partial(f"cohort {cid}: conflicting total_cap values")
            window_spend = 0.0
            windows = set()
            for r in sorted(c["rows"], key=lambda r: _s(r.get("scope_id"))):
                scope = _s(r.get("scope_id"))
                a, b = _dates(r.get("effective_dates"))
                if a is None or b is None or first is None or a < first:
                    cs.partial(f"scope {scope}: effective_dates {r.get('effective_dates')} not covered by allocation_daily")
                    continue
                windows.add((a, b))
                seen_to = min(b, last)
                sp = sum(v for d, v in (scope_spend.get(scope) or {}).get("by_date", {}).items() if a <= d <= seen_to)
                window_spend += sp
                ended = b <= last
                lo, hi = ctx.money(r.get("minimum_spend")), ctx.money(r.get("maximum_spend"))
                entity = {"cohort_id": cid, "scope_id": scope}
                ev = {"actual_spend": sp, "window": [a, seen_to], "window_complete": ended, "minimum_spend": lo,
                      "maximum_spend": hi, "protected_commitment": r.get("protected_commitment"), "owner": r.get("owner"),
                      "source_ref": r.get("source_ref")}
                if hi is not None and sp > hi:
                    cs.finding("allocation_violates_constraint", "Warning", {**entity, "constraint": "maximum_spend"},
                               f"Scope {scope}: spend {sp:.2f} exceeds documented maximum {hi:.2f} ({a}..{seen_to})",
                               evidence={**ev, "exposure": sp - hi}, recommendation="Owner review of the scope's budget within approved limits.",
                               uncertainty="Exposure is spent money, not recoverable savings.")
                elif lo is not None and sp < lo and ended:
                    cs.finding("allocation_violates_constraint", "Warning", {**entity, "constraint": "minimum_spend"},
                               f"Scope {scope}: spend {sp:.2f} below documented minimum {lo:.2f} ({a}..{b})",
                               evidence={**ev, "shortfall": lo - sp}, recommendation="Owner review: check constraints/demand before raising budget.",
                               uncertainty="An unspent budget does not prove demand was available.")
                elif lo is not None and sp < lo:
                    cs.observe(f"Scope {scope}: minimum not yet reached; window still open", **entity, **ev)
                else:
                    cs.observe(f"Scope {scope}: within documented constraints", **entity, **ev)
            if c["total_cap"] is not None and len(windows) == 1 and window_spend > c["total_cap"]:
                cs.finding("allocation_violates_constraint", "Warning", {"cohort_id": cid, "constraint": "total_cap"},
                           f"Cohort {cid}: spend {window_spend:.2f} exceeds total cap {c['total_cap']:.2f}",
                           evidence={"actual_spend": window_spend, "total_cap": c["total_cap"], "window": sorted(windows)[0],
                                     "exposure": window_spend - c["total_cap"]},
                           recommendation="Owner review of the cohort allocation within the approved cap.",
                           uncertainty="Exposure is spent money, not recoverable savings.")

    # step 4 — recipient/donor screen
    rd = ctx.check("recipient_donor_screen", "Observed constraint and economics screen (step 4)",
                   {CONSTR: CONSTR_COLS, "campaign_metrics": ["campaign_id", "cost", "conversions", "search_budget_lost_is"]})
    if rd.runnable:
        metrics = {_s(m.get("campaign_id")): m for m in ctx.rows("campaign_metrics")}
        for cid, c in sorted(cohorts.items()):
            if not c["consistent"]:
                continue
            for scope in c["scopes"]:
                members = _members(ctx, scope, daily_campaigns)
                lost = [ctx.rate(metrics[m].get("search_budget_lost_is")) for m in members if m in metrics]
                rd.observe(f"Scope {scope}: screen facts (low volume or bottom quartile alone is not overfunded)",
                           cohort_id=cid, scope_id=scope, members=members, budget_lost_is=lost, limit=c["limit"],
                           protected=[r.get("protected_commitment") for r in c["rows"] if _s(r.get("scope_id")) == scope])

    # steps 5-6 — marginal response + scenario constraints
    mr = ctx.check("marginal_response", "Modeled marginal response vs approved limits (steps 5-6)", {RESP: RESP_COLS, CONSTR: CONSTR_COLS})
    rows_by_scenario: dict[str, list] = {}
    if mr.runnable:
        bounds = {_s(r.get("scope_id")): r for r in ctx.rows(CONSTR)}
        unapproved = 0
        for r in sorted(ctx.rows(RESP), key=lambda r: (_s(r.get("scenario_id")), _s(r.get("scope_id")), _s(r.get("model_id")))):
            if V.norm_text(r.get("approved_state")) not in ("approved", "validated"):
                unapproved += 1
                continue
            scope, sid = _s(r.get("scope_id")), _s(r.get("scenario_id"))
            cid = scope_of.get(scope)
            c = cohorts.get(cid or "")
            if c is None or not c["consistent"]:
                mr.partial(f"scenario {sid} scope {scope}: no comparable cohort")
                continue
            bs, bo, ss, so = (V.num(r.get(k)) for k in ("baseline_spend", "baseline_outcome", "scenario_spend", "scenario_outcome"))
            low = V.num(r.get("uncertainty_low"))
            if None in (bs, bo, ss, so):
                mr.partial(f"scenario {sid} scope {scope}: incomplete response values")
                continue
            dc, do = ss - bs, so - bo
            m = {"model_id": _s(r.get("model_id")), "scenario_id": sid, "scope_id": scope, "cohort_id": cid, "unit": c["unit"],
                 "delta_cost": dc, "delta_outcome": do, "uncertainty_low": low, "uncertainty_high": V.num(r.get("uncertainty_high")),
                 "response_method": r.get("response_method"), "validity_domain": r.get("validity_domain"),
                 "baseline_window": r.get("baseline_window"), "forecast_window": r.get("forecast_window"),
                 "source_ref": r.get("source_ref"), "limit": c["limit"]}
            rows_by_scenario.setdefault(sid, []).append(m)
            if dc < 0:
                mr.observe(f"Scenario {sid}: donor {scope} loses {-do:g} {c['unit']} for {-dc:.2f} less spend", **m)
                continue
            if c["unit"] == "conversions":
                marg = V.ratio(dc, do) if dc > 0 and do > 0 else None
                marg_low = V.ratio(dc, low - bo) if low is not None and dc > 0 and low - bo > 0 else None
                meets = lambda x: x is not None and c["limit"] is not None and x <= c["limit"]
                m["marginal_cpa"], m["marginal_cpa_at_low"] = marg, marg_low
            else:
                marg = V.ratio(do, dc) if dc > 0 else None
                marg_low = V.ratio(low - bo, dc) if low is not None and dc > 0 else None
                meets = lambda x: x is not None and c["limit"] is not None and x >= c["limit"]
                m["marginal_roas"], m["marginal_roas_at_low"] = marg, marg_low
            b = bounds.get(scope, {})
            problems = []
            hi, lo = ctx.money(b.get("maximum_spend")), ctx.money(b.get("minimum_spend"))
            if hi is not None and ss > hi:
                problems.append(f"scenario spend {ss:g} > maximum {hi:g}")
            if lo is not None and ss < lo:
                problems.append(f"scenario spend {ss:g} < minimum {lo:g}")
            pool, size = _pool_size(ctx, scope)
            if size > 1:
                problems.append(f"independent change to one member of shared pool {pool} ({size} members)")
            m["constraint_problems"] = problems
            m["robust_at_low_bound"] = meets(marg_low)
            if c["limit"] is None:
                mr.partial(f"cohort {cid}: approved CPA/ROAS limit missing; trade-off not assessable")
                continue
            if meets(marg) and not problems:
                mr.finding("modeled_tradeoff_candidate", "Info", {"scenario_id": sid, "scope_id": scope, "cohort_id": cid},
                           f"Scenario {sid} scope {scope}: modeled marginal {'CPA' if c['unit'] == 'conversions' else 'ROAS'} "
                           f"{marg:.2f} meets approved limit {c['limit']:g}", evidence=m,
                           calculation={"delta_cost": dc, "delta_outcome": do, "marginal": marg, "limit": c["limit"]},
                           recommendation="Controlled, owner-approved limited-budget test with rollback guardrails"
                                          + ("" if m["robust_at_low_bound"] else "; evidence weak at the lower bound — prefer a holdout"),
                           uncertainty="Modeled estimate within the stated validity domain; diminishing returns apply.")
            else:
                mr.observe(f"Scenario {sid} scope {scope}: not a candidate", **m)
        if unapproved:
            mr.partial(f"{unapproved} response rows not approved/validated")
        # cohort total_cap for each scenario
        for sid, ms in sorted(rows_by_scenario.items()):
            for cid in sorted({x["cohort_id"] for x in ms}):
                cap = cohorts[cid]["total_cap"]
                spend = sum(V.num(r.get("scenario_spend")) or 0 for r in ctx.rows(RESP)
                            if _s(r.get("scenario_id")) == sid and scope_of.get(_s(r.get("scope_id"))) == cid)
                if cap is not None and spend > cap:
                    mr.observe(f"Scenario {sid}: cohort {cid} proposed spend {spend:.2f} exceeds total cap {cap:.2f}; invalid",
                               scenario_id=sid, cohort_id=cid, proposed_spend=spend, total_cap=cap)

    # step 7 — net scenario
    ns = ctx.check("net_scenario", "Net scenario outcome where units and model scope match (step 7)", {RESP: RESP_COLS})
    if ns.runnable:
        for sid, ms in sorted(rows_by_scenario.items()):
            models, units, cohorts_ = {x["model_id"] for x in ms}, {x["unit"] for x in ms}, {x["cohort_id"] for x in ms}
            if len(models) == 1 and len(units) == 1 and len(cohorts_) == 1:
                ns.observe(f"Scenario {sid}: net modeled outcome (single model covering all scopes)", scenario_id=sid,
                           net_delta_cost=sum(x["delta_cost"] for x in ms), net_delta_outcome=sum(x["delta_outcome"] for x in ms),
                           unit=units.pop(), scopes=[x["scope_id"] for x in ms])
            else:
                ns.partial(f"scenario {sid}: mixed models/units/cohorts; net outcome unavailable")

    # step 8 — candidate selection
    sel = ctx.check("candidate_selection", "Review candidates and controlled-test proposals (step 8)")
    cands = [f for f in ctx.result.findings if f.condition_key == "modeled_tradeoff_candidate"]
    sel.observe("Allocation review candidates (nothing executed)", candidates=len(cands),
                robust=sum(1 for f in cands if f.evidence.get("robust_at_low_bound")))
    if not ctx.table(RESP):
        sel.partial("no marginal-response evidence: propose a constrained experiment, no quantified uplift",
                    [f"{RESP} (file)"])


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
