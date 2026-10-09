"""check.py — skill-051 deterministic simulator point metrics, period normalization, marginal deltas and constraints.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-051-bid-simulator-analysis-target-changes/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Points compare only inside ONE simulation_id with one scope/type/method/date range/target_type/currency;
         mixed points make the simulation incomparable (Info) — never one response curve across simulations.
         Target input (target_value) is never equated with modeled achieved CPA/ROAS. Achieved CPA = cost/conv,
         ROAS = value/cost only for positive denominators; missing metric fields skip only that metric.
         Seven-day equivalent = native × 7 / inclusive days, labeled a stationarity assumption.
         Points ordered by modeled_cost; marginal CPA = Δcost/Δconv only when both Δ > 0; marginal ROAS = Δvalue/Δcost
         only for Δcost > 0; nonpositive/nonmonotonic deltas are flagged, not forced into ratios.
         Business limits come from profile.budget_constraints[scope_id|campaign_id] keys max_marginal_cpa,
         min_marginal_roas, max_period_spend (native simulation period), else profile.campaign_objectives[id]
         target_cpa/target_roas labeled as the return limit. No limit → partial, no candidate outcome.
         Candidates never extrapolate beyond observed points. Warning only via review for a proposal that the
         model shows violating a documented limit; verify() recomputes feasibility of proposal.point_id.
         Simulated conversion counts are not sample sizes; no min_conversions gate on simulated points.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-051-bid-simulator-analysis-target-changes"
VERSION = "1.0.0"

_PTS = "custom/bid_simulation_points"
_CTX = "custom/bid_simulation_context"
_SHAPE = ("scope_type", "scope_id", "simulation_type", "modification_method", "simulation_start_date",
          "simulation_end_date", "target_type")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _money(ctx, r, col):
    unit = _s(r.get("unit")).lower()
    return V.money(r.get(col), "micros") if unit == "micros" else ctx.money(r.get(col))


def _simulations(ctx) -> dict[str, list[dict]]:
    sims: dict[str, list[dict]] = {}
    for r in ctx.rows(_PTS):
        sid = _s(r.get("simulation_id"))
        if sid:
            sims.setdefault(sid, []).append(r)
    return {k: sorted(v, key=lambda r: _s(r.get("point_id"))) for k, v in sorted(sims.items())}


def _points(ctx, rows) -> list[dict]:
    pts = []
    for r in rows:
        cost, conv, val = _money(ctx, r, "modeled_cost"), V.num(r.get("modeled_conversions")), \
            V.num(r.get("modeled_conversion_value"))
        pts.append({"point_id": _s(r.get("point_id")), "target_type": _s(r.get("target_type")).upper(),
                    "target_value": V.num(r.get("target_value")), "modeled_cost": cost, "modeled_conversions": conv,
                    "modeled_value": val, "achieved_cpa": V.ratio(cost, conv) if conv and conv > 0 else None,
                    "achieved_roas": V.ratio(val, cost) if cost and cost > 0 and val is not None else None,
                    "baseline": V.boolean(r.get("baseline_point_flag")) is True})
    return sorted(pts, key=lambda p: (p["modeled_cost"] is None, p["modeled_cost"] or 0, p["point_id"]))


def _delta(a: dict, b: dict) -> dict:
    """Marginal metrics from a → b (b has higher modeled cost). Rules: only between observed simulator points; no extrapolation; zero cost delta → undefined."""
    dc = None if None in (a["modeled_cost"], b["modeled_cost"]) else b["modeled_cost"] - a["modeled_cost"]
    dv = None if None in (a["modeled_conversions"], b["modeled_conversions"]) else \
        b["modeled_conversions"] - a["modeled_conversions"]
    dval = None if None in (a["modeled_value"], b["modeled_value"]) else b["modeled_value"] - a["modeled_value"]
    out = {"from": a["point_id"], "to": b["point_id"], "delta_cost": dc, "delta_conversions": dv, "delta_value": dval,
           "marginal_cpa": dc / dv if dc is not None and dv is not None and dc > 0 and dv > 0 else None,
           "marginal_roas": dval / dc if dc is not None and dval is not None and dc > 0 else None}
    out["needs_interpretation"] = bool(dc is None or dc <= 0 or (dv is not None and dv <= 0)
                                       or (dval is not None and dval <= 0))
    return out


def _limits(ctx, scope_id: str, campaign_id: str) -> dict:
    bc = ctx.profile.get("budget_constraints") or {}
    bc = {str(k): v for k, v in bc.items()} if isinstance(bc, dict) else {}
    ent = bc.get(scope_id) or bc.get(campaign_id) or {}
    ent = ent if isinstance(ent, dict) else {}
    out = {k: V.num(ent.get(k)) for k in ("max_marginal_cpa", "min_marginal_roas", "max_period_spend")
           if V.num(ent.get(k)) is not None}
    src = {k: f"profile.budget_constraints[{scope_id if scope_id in bc else campaign_id}].{k}" for k in out}
    obj = (ctx.profile.get("campaign_objectives") or {})
    obj = {str(k): v for k, v in obj.items()} if isinstance(obj, dict) else {}
    o = obj.get(campaign_id) or obj.get(scope_id) or {}
    if isinstance(o, dict):
        if "max_marginal_cpa" not in out and V.num(o.get("target_cpa")):
            out["max_marginal_cpa"] = V.num(o.get("target_cpa"))
            src["max_marginal_cpa"] = f"profile.campaign_objectives[{campaign_id or scope_id}].target_cpa"
        if "min_marginal_roas" not in out and V.num(o.get("target_roas")):
            out["min_marginal_roas"] = V.num(o.get("target_roas"))
            src["min_marginal_roas"] = f"profile.campaign_objectives[{campaign_id or scope_id}].target_roas"
    return {"limits": out, "sources": src}


def _feasible(point: dict, marg: dict | None, lim: dict) -> tuple[bool | None, list[str]]:
    """Is a candidate within documented limits? None = undecidable (needed metric undefined)."""
    reasons, unknown = [], False
    L = lim["limits"]
    if "max_period_spend" in L:
        if point["modeled_cost"] is None:
            unknown = True
        elif point["modeled_cost"] > L["max_period_spend"]:
            reasons.append(f"modeled_cost {point['modeled_cost']:g} > max_period_spend {L['max_period_spend']:g}")
    if marg is not None:
        if "max_marginal_cpa" in L:
            if marg["marginal_cpa"] is None:
                unknown = True
            elif marg["marginal_cpa"] > L["max_marginal_cpa"]:
                reasons.append(f"marginal CPA {marg['marginal_cpa']:.2f} > {L['max_marginal_cpa']:g}")
        if "min_marginal_roas" in L:
            if marg["marginal_roas"] is None:
                unknown = True
            elif marg["marginal_roas"] < L["min_marginal_roas"]:
                reasons.append(f"marginal ROAS {marg['marginal_roas']:.2f} < {L['min_marginal_roas']:g}")
    if reasons:
        return False, reasons
    return (None if unknown else True), reasons


def run(ctx) -> None:
    """Run simulator comparability, context staleness, metric, normalization, marginal and candidate checks.

    Rules:   No points → every check skipped; mixed points inside one simulation_id → Info incomparable. Candidates need
             a unique baseline, current context and a documented limit (profile.budget_constraints or
             campaign_objectives targets), else partial with no candidate outcome; nothing extrapolates beyond observed
             points. Warning only via review of a proposal exceeding the limit; no min_conversions gate on simulated
             points.
    """
    inv = ctx.check("simulation_inventory", "Available simulations, scope, method, dates and freshness (steps 1, 8)",
                    {_PTS: ["scope_type", "scope_id", "simulation_id", "point_id", "simulation_type",
                            "modification_method", "simulation_start_date", "simulation_end_date", "generated_at",
                            "target_type", "target_value"]})
    later = (("context_validation", "Goal/budget/strategy context and later material changes (step 2)"),
             ("point_metrics", "Target input vs modeled achieved CPA/ROAS per point (step 3)"),
             ("period_normalization", "Native period and seven-day equivalent (step 4)"),
             ("marginal_analysis", "Adjacent and baseline-to-candidate marginal deltas (step 5)"),
             ("business_constraints", "Candidates vs documented business limits (steps 6-7)"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("no simulator points: explicit unavailable outcome", inv.missing)
        return
    sims = _simulations(ctx)
    shape_ok: dict[str, bool] = {}
    for sid, rows in sims.items():
        shapes = {tuple(_s(r.get(c)).upper() for c in _SHAPE) for r in rows}
        cur = {_s(r.get("currency")).upper() for r in rows} - {""}
        gen = sorted({_s(r.get("generated_at"))[:10] for r in rows} - {""})
        ok = len(shapes) == 1 and (not cur or cur == {(ctx.currency or "").upper()})
        shape_ok[sid] = ok
        first = rows[0]
        ent = {"simulation_id": sid, "scope_type": first.get("scope_type"), "scope_id": first.get("scope_id")}
        age = (ctx.as_of - V.parse_date(gen[-1])).days if gen and ctx.as_of and V.parse_date(gen[-1]) else None
        inv.observe(f"Simulation {sid}: {len(rows)} points", **ent, simulation_type=first.get("simulation_type"),
                    modification_method=first.get("modification_method"),
                    window=[first.get("simulation_start_date"), first.get("simulation_end_date")],
                    generated_at=gen, age_days_at_as_of=age, currency=sorted(cur))
        if not ok:
            inv.finding("incomparable_simulation", "Info", ent,
                        f"Simulation {sid} mixes scopes/types/dates/target types or currency; points not one curve",
                        evidence={"distinct_shapes": len(shapes), "currencies": sorted(cur), "account_currency": ctx.currency},
                        recommendation="Re-export one simulation per scope/type/date range before interpretation.",
                        uncertainty="Incomparable simulator evidence; no candidate derived.")

    cx = ctx.check(later[0][0], later[0][1], {_CTX: ["simulation_id", "goal_action_ids", "value_basis", "budget_id",
                                                     "strategy_type", "current_target_at_simulation",
                                                     "material_changes_since"]})
    changed: set[str] = set()
    if cx.runnable:
        cmap = {_s(r.get("simulation_id")): r for r in ctx.rows(_CTX)}
        camps = {_s(c.get("id")): c for c in ctx.rows("campaigns")}
        for sid, rows in sims.items():
            c = cmap.get(sid)
            if c is None:
                cx.partial(f"simulation {sid}: no context row; goal/budget/strategy comparability unknown")
                continue
            ent = {"simulation_id": sid, "scope_id": rows[0].get("scope_id")}
            cur = camps.get(_s(rows[0].get("campaign_id")) or _s(rows[0].get("scope_id")))
            cur_strategy = _s((cur or {}).get("bidding_strategy_type")).upper() or None
            drift = []
            if _s(c.get("material_changes_since")) and _s(c.get("material_changes_since")).lower() not in ("none", "no"):
                drift.append(f"material changes since: {c.get('material_changes_since')}")
            if cur_strategy and _s(c.get("strategy_type")).upper() and cur_strategy != _s(c.get("strategy_type")).upper():
                drift.append(f"strategy now {cur_strategy}, simulated under {c.get('strategy_type')}")
            ev = {"goal_action_ids": c.get("goal_action_ids"), "value_basis": c.get("value_basis"),
                  "budget_id": c.get("budget_id"), "budget_amount": c.get("amount"),
                  "strategy_type": c.get("strategy_type"), "current_target_at_simulation":
                  c.get("current_target_at_simulation"), "drift": drift}
            if drift:
                changed.add(sid)
                cx.finding("stale_simulation_context", "Info", ent, f"Simulation {sid} context changed since generation",
                           evidence=ev, recommendation="Treat the curve as stale; request a fresh simulation.",
                           uncertainty="The model reflects the settings at generation time only.")
            else:
                cx.observe(f"Simulation {sid}: context matches current settings", **ent, **ev)

    pm = ctx.check(later[1][0], later[1][1], {_PTS: ["simulation_id", "point_id", "target_type", "target_value",
                                                     "modeled_cost", "modeled_conversions", "modeled_conversion_value"]})
    pts: dict[str, list[dict]] = {}
    if pm.runnable:
        for sid, rows in sims.items():
            pts[sid] = _points(ctx, rows)
            miss = sum(1 for p in pts[sid] if None in (p["modeled_cost"], p["modeled_conversions"], p["modeled_value"]))
            if miss:
                pm.partial(f"simulation {sid}: {miss} points missing a modeled metric; only that metric skipped")
            pm.observe(f"Simulation {sid}: per-point target input and modeled achieved metrics", simulation_id=sid,
                       points=pts[sid], currency=ctx.currency,
                       note="target_value is the input; achieved_cpa/roas are modeled outputs, not the target.")

    pn = ctx.check(later[2][0], later[2][1], {_PTS: ["simulation_id", "simulation_start_date", "simulation_end_date",
                                                     "modeled_cost", "modeled_conversions"]})
    days_by: dict[str, int] = {}
    if pn.runnable:
        for sid, rows in sims.items():
            s, e = V.parse_date(rows[0].get("simulation_start_date")), V.parse_date(rows[0].get("simulation_end_date"))
            if s is None or e is None or e < s or not shape_ok.get(sid):
                pn.partial(f"simulation {sid}: dates missing/invalid or incomparable; no normalization")
                continue
            days = (e - s).days + 1
            days_by[sid] = days
            weekly = [{"point_id": p["point_id"],
                       "cost_7d": None if p["modeled_cost"] is None else p["modeled_cost"] * 7 / days,
                       "conversions_7d": None if p["modeled_conversions"] is None else p["modeled_conversions"] * 7 / days,
                       "value_7d": None if p["modeled_value"] is None else p["modeled_value"] * 7 / days}
                      for p in pts.get(sid, [])]
            pn.observe(f"Simulation {sid}: {days} inclusive days", simulation_id=sid, days=days, seven_day=weekly,
                       assumption="stationarity: seven-day equivalent is not a weekly forecast")

    ma = ctx.check(later[3][0], later[3][1], {_PTS: ["simulation_id", "point_id", "modeled_cost",
                                                     "modeled_conversions", "baseline_point_flag"]})
    margins: dict[str, dict] = {}
    if ma.runnable:
        for sid, plist in sorted(pts.items()):
            if not shape_ok.get(sid):
                continue
            known = [p for p in plist if p["modeled_cost"] is not None]
            adj = [_delta(a, b) for a, b in zip(known, known[1:])]
            base = [p for p in known if p["baseline"]]
            from_base = {}
            if len(base) == 1:
                for p in known:
                    if p is not base[0] and p["modeled_cost"] > base[0]["modeled_cost"]:
                        from_base[p["point_id"]] = _delta(base[0], p)
            else:
                ma.partial(f"simulation {sid}: {len(base)} baseline points; baseline deltas unavailable")
            margins[sid] = {"base": base[0] if len(base) == 1 else None, "from_base": from_base, "known": known}
            ma.observe(f"Simulation {sid}: marginal deltas", simulation_id=sid, adjacent=adj,
                       baseline_to_candidate=list(from_base.values()),
                       needs_interpretation=[d["to"] for d in adj if d["needs_interpretation"]])

    bc = ctx.check(later[4][0], later[4][1], {_PTS: ["simulation_id", "scope_id", "modeled_cost"]})
    if bc.runnable:
        for sid, m in sorted(margins.items()):
            if m["base"] is None:
                bc.partial(f"simulation {sid}: no unique baseline; candidates not evaluated")
                continue
            if sid in changed:
                bc.partial(f"simulation {sid}: stale context; candidates not evaluated")
                continue
            first = sims[sid][0]
            lim = _limits(ctx, _s(first.get("scope_id")), _s(first.get("campaign_id")) or _s(first.get("scope_id")))
            if not lim["limits"]:
                bc.partial(f"simulation {sid}: no documented business limit; feasibility not assessed")
                continue
            evals = []
            for p in m["known"]:
                if p is m["base"]:
                    continue
                marg = m["from_base"].get(p["point_id"])
                ok, why = _feasible(p, marg, lim)
                evals.append({"point_id": p["point_id"], "target_type": p["target_type"],
                              "target_value": p["target_value"], "modeled_cost": p["modeled_cost"],
                              "marginal": marg, "feasible": ok, "reasons": why})
            feasible = [e["point_id"] for e in evals if e["feasible"] is True]
            ent = {"simulation_id": sid, "scope_id": first.get("scope_id")}
            bc.observe(f"Simulation {sid}: {len(feasible)} of {len(evals)} candidates within documented limits",
                       **ent, candidates=evals, limits=lim)
            bc.review("simulator_candidate", ent,
                      f"Which modeled point of simulation {sid}, if any, warrants a bounded approved test, or does a "
                      "proposed target change exceed the documented limits?",
                      evidence={"candidates": evals, "limits": lim, "baseline_point": m["base"]["point_id"],
                                "window_days": days_by.get(sid)},
                      outcomes={"evaluate_candidate": {"severity": "Info", "recommendation":
                                                       "Evaluate the feasible candidate in a bounded approved test."},
                                "proposed_change_exceeds_constraint": {"severity": "Warning", "recommendation":
                                                                       "Do not adopt the proposed target; it breaches a documented limit in the model."},
                                "no_candidate": {"severity": None, "recommendation": "Keep the current target."},
                                "uncertain": {"severity": "Info", "recommendation": "Request a fresh/complete simulation."}},
                      guidance="Give proposal.point_id from evidence. evaluate_candidate needs a feasible point; "
                               "proposed_change_exceeds_constraint needs an infeasible point. Never extrapolate.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: point_id must be in the reviewed model; feasibility must match the chosen outcome."""
    outcome = decision.get("outcome")
    if item.condition_key != "simulator_candidate" or outcome not in ("evaluate_candidate",
                                                                       "proposed_change_exceeds_constraint"):
        return []
    pid = _s((decision.get("proposal") or {}).get("point_id"))
    cand = {c["point_id"]: c for c in item.evidence.get("candidates", [])}
    if pid not in cand:
        return [f"proposal.point_id must be one of {sorted(cand)} (no extrapolation)"]
    if outcome == "evaluate_candidate" and cand[pid]["feasible"] is not True:
        return [f"point {pid} is not deterministically within limits: {cand[pid]['reasons'] or 'undecidable'}"]
    if outcome == "proposed_change_exceeds_constraint" and cand[pid]["feasible"] is not False:
        return [f"point {pid} does not breach a documented limit in the model"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
