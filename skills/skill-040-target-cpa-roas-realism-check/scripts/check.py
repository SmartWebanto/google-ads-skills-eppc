"""check.py — skill-040 deterministic target CPA/ROAS direction and realism screening.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-040-target-cpa-roas-realism-check/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #120 Set Target CPA bids for Shopping Product Groups (Frederick Vallaeys) — clean-room
         reimplementation of target-CPA → CPC arithmetic (target_cpa × conversion rate) at campaign grain only;
         product-group bids are out of the recipe's declared evidence and nothing is ever set.
rules:   Platform target = campaigns.target_cpa/target_roas (standalone or embedded in Maximize*) or the linked
         portfolio (campaigns.bidding_strategy_id|strategy_id, else bidding_strategies.campaign_ids); differing
         sources are a conflict → campaign partial, never arbitrary precedence. Profile objectives are the
         APPROVED business constraint, never the platform target.
         Direction: lower tCPA / higher tROAS = more restrictive. CPA r = 1 - target/achieved; ROAS
         r = target/achieved - 1; achieved = sums over one stable mature window (never averaged daily ratios).
         Achieved outcomes: custom/target_daily (last 30 complete lag_mature days inside one strategy/budget/
         goal/target regime) else campaign_metrics aggregate (needs ctx.mature True; no trend/change claims).
         Both need min_conversions; zero/unknown denominators → unavailable.
         r > 0.20 → provisional Info + review (Warning only when corroborated delivery/economic concern).
         Relaxed platform target beyond the profile's approved CPA/ROAS with window cost >= spend_floor → Warning.
         verify(): Warning needs proposal.corroboration; any proposal.test_target must move toward the
         achieved outcome, stay within the approved business bound and never equal achieved CPA/ROAS.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-040-target-cpa-roas-realism-check"
VERSION = "1.0.0"

HEURISTIC = 0.20
DAILY = "custom/target_daily"
HISTORY = "custom/target_history"
BUDGETS = "custom/budget_history"
DAILY_COLS = ["campaign_id", "date", "cost", "conversions", "conversion_value", "lag_mature"]
HISTORY_COLS = ["entity_type", "entity_id", "effective_from", "effective_to", "target_type", "target_value"]
BUDGET_COLS = ["budget_id", "effective_from", "effective_to", "amount", "member_campaign_ids"]
SEPS = (";", "|", ",")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _pos(v) -> float | None:
    f = V.num(v)
    return f if f is not None and f > 0 else None


def _kind(v) -> str | None:
    t = _s(v).upper()
    return "ROAS" if "ROAS" in t or "VALUE" in t else "CPA" if "CPA" in t or "CONVERSIONS" in t else None


def _has(ctx, key: str, cols: list[str]) -> bool:
    t = ctx.table(key)
    return t is not None and not t.missing(cols)


def _missing(ctx, key: str, cols: list[str]) -> list[str]:
    t = ctx.table(key)
    return [f"{key} (file)"] if t is None else [f"{key}:{c}" for c in t.missing(cols)]


# ---------------------------------------------------------------- step 1: platform target
def _strategy_for(ctx, row) -> dict | None:
    strategies = ctx.rows("bidding_strategies")
    sid = _s(row.get("bidding_strategy_id") or row.get("strategy_id"))
    if sid:
        hit = next((s for s in strategies if _s(s.get("id")) == sid), None)
        if hit:
            return hit
    cid = _s(row.get("id"))
    return next((s for s in sorted(strategies, key=lambda s: _s(s.get("id")))
                 if cid in V.split_list(s.get("campaign_ids"), SEPS)), None)


def _platform_targets(ctx) -> dict[str, dict]:
    """campaign_id -> {kind, value, source, strategy_id, conflict}. Only campaigns with some configured target."""
    out = {}
    for row in sorted(ctx.rows("campaigns"), key=lambda r: _s(r.get("id"))):
        cid = _s(row.get("id"))
        if not cid:
            continue
        stype = _s(row.get("bidding_strategy_type")).upper()
        cands = []
        label = "embedded" if stype.startswith("MAXIMIZE") else "standalone"
        for kind, col in (("CPA", "target_cpa"), ("ROAS", "target_roas")):
            v = _pos(row.get(col))
            if v is not None:
                cands.append((kind, v, f"campaigns.{col}[{cid}] ({label})"))
        strat = _strategy_for(ctx, row)
        sid = _s(strat.get("id")) if strat else _s(row.get("bidding_strategy_id") or row.get("strategy_id"))
        if strat:
            for kind, col in (("CPA", "target_cpa"), ("ROAS", "target_roas")):
                v = _pos(strat.get(col))
                if v is not None:
                    cands.append((kind, v, f"bidding_strategies.{col}[{sid}] (portfolio)"))
        if not cands:
            continue
        kinds = {k for k, _, _ in cands}
        values = {(k, round(v, 6)) for k, v, _ in cands}
        conflict = None
        if len(kinds) > 1:
            conflict = "both CPA and ROAS targets configured"
        elif len(values) > 1:
            conflict = "configured target sources disagree: " + "; ".join(f"{s}={v:g}" for _, v, s in cands)
        k, v, src = next((c for c in cands if c[2].endswith("(portfolio)")), cands[0])
        out[cid] = {"kind": k, "value": v, "source": src, "strategy_id": sid or None, "conflict": conflict,
                    "sources": [f"{s}={val:g}" for _, val, s in cands], "strategy_type": stype or None}
    return out


def _approved(ctx, cid: str, kind: str) -> tuple[float | None, str]:
    """Approved business CPA ceiling / ROAS floor from the profile (never the platform target)."""
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    col = "target_cpa" if kind == "CPA" else "target_roas"
    if isinstance(obj, dict) and _pos(obj.get(col)) is not None:
        return _pos(obj.get(col)), f"profile.campaign_objectives[{cid}].{col}"
    if not objectives and _pos(ctx.profile.get(col)) is not None:
        return _pos(ctx.profile.get(col)), f"profile.{col}"
    return None, f"no approved {kind} constraint for campaign {cid}"


# ---------------------------------------------------------------- step 2: regimes
def _target_regime_start(ctx, cid: str, t: dict):
    """Effective_from of the dated target covering period end, or (None, reason)."""
    end = ctx.period_end
    rows = []
    for r in ctx.rows(HISTORY):
        et, eid = _s(r.get("entity_type")).lower(), _s(r.get("entity_id"))
        own = (et.startswith("camp") and eid == cid) or (
            et.startswith(("strat", "portfolio")) and t["strategy_id"] and eid == t["strategy_id"])
        if own and _kind(r.get("target_type")) == t["kind"]:
            rows.append(r)
    if not rows:
        return None, None, f"no dated {t['kind']} target history for campaign {cid}"
    cover = [r for r in rows if V.parse_date(r.get("effective_from")) and end
             and V.parse_date(r.get("effective_from")) <= end
             and (V.parse_date(r.get("effective_to")) is None or V.parse_date(r.get("effective_to")) >= end)]
    if len(cover) != 1:
        return None, None, f"{len(cover)} dated target rows cover period end for campaign {cid}"
    r = cover[0]
    return V.parse_date(r.get("effective_from")), V.num(r.get("target_value")), ""


def _daily_by_campaign(ctx) -> tuple[dict, list[str]]:
    """campaign -> {date: row-aggregate}; cost is taken once per campaign/date (goal-cohort rows repeat it)."""
    out: dict[str, dict] = {}
    issues = []
    for r in ctx.rows(DAILY):
        cid, d = _s(r.get("campaign_id")), V.parse_date(r.get("date"))
        if not cid or d is None:
            continue
        day = out.setdefault(cid, {}).setdefault(d, {"rows": []})
        day["rows"].append(r)
    for cid in sorted(out):
        for d in sorted(out[cid]):
            rows = out[cid][d]["rows"]
            cohorts = sorted({_s(r.get("goal_cohort")) for r in rows})
            costs = {ctx.money(r.get("cost")) for r in rows}
            agg = out[cid][d]
            agg["cohorts"] = cohorts
            agg["strategy"] = sorted({_s(r.get("strategy_id")) for r in rows if _s(r.get("strategy_id"))})
            agg["budget"] = sorted({_s(r.get("budget_id")) for r in rows if _s(r.get("budget_id"))})
            agg["mature"] = all(V.boolean(r.get("lag_mature")) is True for r in rows)
            agg["cost"] = costs.pop() if len(costs) == 1 else None
            if len(costs) > 1:
                issues.append(f"campaign {cid} {d}: goal-cohort rows disagree on cost")
            convs = [V.num(r.get("conversions")) for r in rows]
            vals = [ctx.money(r.get("conversion_value")) for r in rows]
            agg["conversions"] = None if None in convs else sum(convs)
            agg["value"] = None if None in vals else sum(vals)
            agg["clicks"] = V.num(rows[0].get("clicks")) if len(rows) == 1 else None
    return out, issues


def _stable_window(days: dict, regime_start):
    """Last 30 consecutive complete mature days inside one strategy/budget/goal regime → (dates, reason)."""
    mature = sorted(d for d, a in days.items() if a["mature"] and (regime_start is None or d >= regime_start))
    if not mature:
        return [], "no lag-mature days in the current regime"
    last = mature[-1]
    window = [last - timedelta(days=i) for i in range(29, -1, -1)]
    present = [d for d in window if d in days and days[d]["mature"] and (regime_start is None or d >= regime_start)]
    if len(present) < 30:
        return [], f"stable mature window has {len(present)} of 30 days ending {last}"
    sig = {(tuple(days[d]["strategy"]), tuple(days[d]["budget"]), tuple(days[d]["cohorts"])) for d in window}
    if len(sig) > 1:
        return [], f"strategy/budget/goal regime changes inside the 30 days ending {last}"
    if len(days[last]["cohorts"]) > 1:
        return [], f"mixed goal cohorts {days[last]['cohorts']} in one campaign/day"
    return window, ""


def _sum(days: dict, dates) -> dict:
    tot = {"cost": 0.0, "conversions": 0.0, "value": 0.0, "clicks": 0.0}
    for d in dates:
        for k in tot:
            v = days[d].get(k)
            tot[k] = None if v is None or tot[k] is None else tot[k] + v
    return tot


# ---------------------------------------------------------------- step 6: pool utilization
def _amount(ctx, r) -> float | None:
    unit = _s(r.get("amount_unit")).lower()
    if unit in ("micros", "micro"):
        return V.money(r.get("amount"), "micros")
    if unit in ("", "currency", ctx.currency.lower() if ctx.currency else "currency"):
        return ctx.money(r.get("amount")) if unit == "" else V.num(r.get("amount"))
    return None


def _utilization(ctx, daily: dict) -> tuple[dict, list[str]]:
    """budget_id -> {utilization, pool_cost, planned, days, members}; amounts counted once per budget/day."""
    hist: dict[str, list] = {}
    for r in ctx.rows(BUDGETS):
        bid = _s(r.get("budget_id"))
        if bid:
            hist.setdefault(bid, []).append(r)
    all_dates = sorted({d for days in daily.values() for d in days})
    out, gaps = {}, []
    for bid in sorted(hist):
        cost = planned = 0.0
        n = 0
        members_seen: set[str] = set()
        for d in all_dates:
            rows = [r for r in hist[bid] if V.parse_date(r.get("effective_from")) and V.parse_date(r.get("effective_from")) <= d
                    and (V.parse_date(r.get("effective_to")) is None or V.parse_date(r.get("effective_to")) >= d)]
            if len(rows) != 1:
                continue
            amt = _amount(ctx, rows[0])
            members = V.split_list(rows[0].get("member_campaign_ids"), SEPS)
            day_costs = [daily.get(m, {}).get(d, {}).get("cost") for m in members]
            if amt is None or not members or any(c is None for c in day_costs):
                continue
            members_seen.update(members)
            cost += sum(day_costs)
            planned += amt
            n += 1
        if n == 0:
            gaps.append(f"budget {bid}: no day with one dated amount and complete member cost")
            continue
        out[bid] = {"pool_cost": round(cost, 2), "planned_budget": round(planned, 2), "days": n,
                    "utilization": V.ratio(cost, planned), "members": sorted(members_seen)}
    return out, gaps


def run(ctx) -> None:
    """Run effective-target resolution, achieved-outcome windows, restrictiveness and business-guardrail checks.

    Rules:   Conflicting platform target sources → campaign partial, never a precedence pick. Achieved outcomes need
             min_conversions (campaign_metrics fallback also ctx.mature True); zero/unknown denominators → unavailable.
             r > 0.20 → provisional Info + ai_review (Warning only 'corroborated_concern'). Relaxed target beyond the
             profile's approved CPA/ROAS with window cost >= spend_floor → deterministic Warning. Nothing is Critical.
    """
    min_conv = ctx.params.get("min_conversions")
    tgt = ctx.check("effective_target", "Resolve current platform target and source (step 1)",
                    {"campaigns": ["id", "bidding_strategy_type"]})
    if not tgt.runnable:
        for cid, title in (("target_regimes", "Stable strategy/target/goal/budget regimes (step 2)"),
                           ("achieved_outcomes", "Achieved CPA/ROAS over a stable mature window (step 3)"),
                           ("restrictiveness", "Signed target restrictiveness and >0.20 review (steps 4-5)"),
                           ("budget_utilization", "Dated pool budget utilization (step 6)"),
                           ("business_guardrails", "Targets against approved business economics (step 7)"),
                           ("bounded_test", "Bounded target test envelope (step 8)")):
            ctx.check(cid, title).skip("campaign inventory unavailable", tgt.missing)
        return
    if ctx.table("bidding_strategies") is None:
        tgt.partial("portfolio targets unknown", ["bidding_strategies (file)"])
    targets = _platform_targets(ctx)
    usable = {}
    for cid, t in sorted(targets.items()):
        tgt.observe(f"Campaign {cid}: current {t['kind']} target {t['value']:g} from {t['source']}",
                    campaign_id=cid, target_type=t["kind"], target_value=t["value"], source=t["source"],
                    sources=t["sources"], strategy_type=t["strategy_type"], conflict=t["conflict"])
        if t["conflict"]:
            tgt.partial(f"campaign {cid}: {t['conflict']} — verify before any comparison")
        else:
            usable[cid] = t
    tgt.observe("Campaigns with an explicitly configured CPA/ROAS target", count=len(targets), usable=len(usable))
    if not targets:
        tgt.observe("No explicit CPA/ROAS target configured; realism check not applicable to any campaign")

    # step 2 — regimes
    reg = ctx.check("target_regimes", "Stable strategy/target/goal/budget regimes (step 2)",
                    {DAILY: DAILY_COLS, HISTORY: HISTORY_COLS})
    have_daily = _has(ctx, DAILY, DAILY_COLS)
    daily, daily_issues = _daily_by_campaign(ctx) if have_daily else ({}, [])
    regime_start: dict[str, object] = {}
    if reg.runnable:
        for cid, t in sorted(usable.items()):
            start, hval, why = _target_regime_start(ctx, cid, t)
            if start is None:
                reg.partial(why)
                continue
            if hval is not None and abs(hval - t["value"]) > 1e-6:
                reg.partial(f"campaign {cid}: dated target {hval:g} differs from snapshot {t['value']:g}")
                continue
            regime_start[cid] = start
            reg.observe(f"Campaign {cid}: current {t['kind']} target regime since {start}", campaign_id=cid,
                        regime_start=start, target_value=t["value"])
    elif have_daily:
        reg.observe("Daily evidence without target history: strategy/budget/goal regimes only, no target-change claims")

    # step 3 — achieved outcomes
    if have_daily:
        ach = ctx.check("achieved_outcomes", "Achieved CPA/ROAS over a stable mature window (step 3)", {DAILY: DAILY_COLS})
        for i in daily_issues:
            ach.partial(i)
        if not _has(ctx, HISTORY, HISTORY_COLS):
            ach.partial("target history missing: snapshot target vs aggregate outcomes only; no recent-change claims",
                        _missing(ctx, HISTORY, HISTORY_COLS))
    else:
        ach = ctx.check("achieved_outcomes", "Achieved CPA/ROAS over a stable mature window (step 3)",
                        {"campaign_metrics": ["campaign_id", "cost", "conversions", "conversion_value"]})
        if ach.runnable:
            ach.partial("daily history missing: aggregate mature outcomes only; no trend/learning/change claims",
                        _missing(ctx, DAILY, DAILY_COLS))
    outcomes: dict[str, dict] = {}
    if ach.runnable and usable:
        if have_daily:
            for cid, t in sorted(usable.items()):
                days = daily.get(cid)
                if not days:
                    ach.partial(f"campaign {cid}: no rows in {DAILY}")
                    continue
                window, why = _stable_window(days, regime_start.get(cid))
                if not window:
                    ach.partial(f"campaign {cid}: {why}")
                    continue
                tot = _sum(days, window)
                outcomes[cid] = {**tot, "window": [window[0], window[-1]], "window_days": 30, "source": DAILY}
                for n in (7, 14):
                    sub = _sum(days, window[-n:])
                    if sub["conversions"] is not None and sub["conversions"] >= (min_conv.value or 0) > 0:
                        ach.observe(f"Campaign {cid}: last {n}-day window qualifies", campaign_id=cid, days=n,
                                    cost=sub["cost"], conversions=sub["conversions"], value=sub["value"],
                                    cpa=V.ratio(sub["cost"], sub["conversions"]), roas=V.ratio(sub["value"], sub["cost"]))
        else:
            if ctx.mature is not True:
                ach.partial(f"aggregate outcomes not mature: {ctx.maturity_note}")
            else:
                rows: dict[str, list] = {}
                for r in ctx.rows("campaign_metrics"):
                    rows.setdefault(_s(r.get("campaign_id")), []).append(r)
                for cid, t in sorted(usable.items()):
                    rs = rows.get(cid, [])
                    if len(rs) != 1:
                        ach.partial(f"campaign {cid}: {len(rs)} campaign_metrics rows (need exactly one aggregate)")
                        continue
                    r = rs[0]
                    start = V.parse_date(r.get("date_range_start")) or ctx.period_start
                    end = V.parse_date(r.get("date_range_end")) or ctx.period_end
                    outcomes[cid] = {"cost": ctx.money(r.get("cost")), "conversions": V.num(r.get("conversions")),
                                     "value": ctx.money(r.get("conversion_value")), "clicks": V.num(r.get("clicks")),
                                     "window": [start, end],
                                     "window_days": (end - start).days + 1 if start and end else None,
                                     "source": "campaign_metrics (aggregate)"}
        for cid, o in sorted(outcomes.items()):
            o["cpa"] = V.ratio(o["cost"], o["conversions"])
            o["roas"] = V.ratio(o["value"], o["cost"])
            ach.observe(f"Campaign {cid}: achieved outcomes {o['window'][0]}..{o['window'][1]}", campaign_id=cid,
                        cost=o["cost"], conversions=o["conversions"], conversion_value=o["value"],
                        achieved_cpa=o["cpa"], achieved_roas=o["roas"], source=o["source"], window_days=o["window_days"])

    # step 6 — utilization (computed before restrictiveness so reviews carry it)
    util = ctx.check("budget_utilization", "Dated pool budget utilization (step 6)",
                     {BUDGETS: BUDGET_COLS, DAILY: ["campaign_id", "date", "cost"]})
    pools: dict[str, dict] = {}
    if util.runnable:
        pools, gaps = _utilization(ctx, daily)
        for g in gaps:
            util.partial(g)
        for bid, p in sorted(pools.items()):
            util.observe(f"Budget {bid}: planning utilization (not billing-cap compliance)", budget_id=bid, **p)

    def pool_of(cid):
        return next(({"budget_id": b, **p} for b, p in sorted(pools.items()) if cid in p["members"]), None)

    # steps 4-5 — restrictiveness
    res = ctx.check("restrictiveness", "Signed target restrictiveness and >0.20 review (steps 4-5)")
    if min_conv.value is None:
        res.partial(f"min_conversions unresolved: {min_conv.reason}")
    if not outcomes:
        res.partial("no qualifying achieved outcomes: restrictiveness not computed")
    signed: dict[str, dict] = {}
    for cid, o in sorted(outcomes.items()):
        t = usable[cid]
        conv = o["conversions"]
        if conv is None or min_conv.value is None or conv < min_conv.value:
            res.partial(f"campaign {cid}: conversions {conv} below min_conversions {min_conv.value}; target gap not compared")
            continue
        achieved = o["cpa"] if t["kind"] == "CPA" else o["roas"]
        if achieved is None or achieved <= 0:
            res.partial(f"campaign {cid}: achieved {t['kind']} unavailable (zero/unknown denominator or value)")
            continue
        r = 1 - t["value"] / achieved if t["kind"] == "CPA" else t["value"] / achieved - 1
        direction = "tighter_than_achieved" if r > 0 else "looser_than_achieved" if r < 0 else "equal_to_achieved"
        cvr = V.ratio(conv, o["clicks"])
        calc = {"formula": "1 - target_CPA/achieved_CPA" if t["kind"] == "CPA" else "target_ROAS/achieved_ROAS - 1",
                "target": t["value"], "achieved": achieved, "restrictiveness": r, "heuristic": HEURISTIC,
                "numerator_cost": o["cost"], "conversions": conv, "conversion_value": o["value"],
                "window": o["window"], "window_source": o["source"],
                "min_conversions": min_conv.value, "min_conversions_source": min_conv.source}
        if t["kind"] == "CPA" and cvr is not None:
            calc["implied_cpc_at_target"] = t["value"] * cvr
            calc["achieved_avg_cpc"] = V.ratio(o["cost"], o["clicks"])
        signed[cid] = {"r": r, "achieved": achieved, "calc": calc, "direction": direction}
        entity = {"campaign_id": cid, "target_type": t["kind"], "target_source": t["source"]}
        if r > HEURISTIC:
            prov = res.finding("restrictive_target_gap", "Info", entity,
                               f"Campaign {cid}: {t['kind']} target {t['value']:g} is tighter than the achieved "
                               f"{t['kind']} {achieved:.2f} (restrictiveness {r:.2f} > {HEURISTIC})",
                               evidence={"direction": direction, "target_source": t["source"]}, calculation=calc,
                               recommendation="Review volume, budget utilization, tracking, demand and dated changes "
                                              "before associating the gap with the target; consider a bounded test via 051.",
                               uncertainty="A target gap is a diagnostic, not causal proof of lost volume.")
            res.review("restrictive_target_concern", entity,
                       f"Is the tight {t['kind']} target of campaign {cid} corroborated by a delivery or economic "
                       f"concern (falling volume, low budget utilization with demand, approved economics allowing more)?",
                       evidence={**calc, "budget_pool": pool_of(cid), "approved_constraint": _approved(ctx, cid, t["kind"])[0],
                                 "campaign_objective": next((v for k, v in (ctx.profile.get("campaign_objectives") or {}).items()
                                                             if str(k) == cid), None)},
                       outcomes={"corroborated_concern": {"severity": "Warning", "recommendation":
                                                          "Propose a bounded, owner-approved target test within approved economics."},
                                 "target_gap_only": {"severity": "Info", "recommendation": "Monitor; no change justified by the gap alone."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request volume/budget/tracking evidence."}},
                       guidance="Correlation is not causation. corroborated_concern needs proposal.corroboration (list of "
                                "evidence keys used); an optional proposal.test_target must loosen toward the achieved "
                                "outcome, stay within the approved business bound and differ from the achieved value.",
                       provisional=prov)
        else:
            res.observe(f"Campaign {cid}: {t['kind']} target {direction} (restrictiveness {r:.2f})",
                        campaign_id=cid, **calc)

    # step 7 — business guardrails
    biz = ctx.check("business_guardrails", "Targets against approved business economics (step 7)")
    for cid, t in sorted(usable.items()):
        bound, bsrc = _approved(ctx, cid, t["kind"])
        if bound is None:
            biz.partial(f"{bsrc}: no target sizing or relaxed-target verdict")
            continue
        loose = t["value"] > bound if t["kind"] == "CPA" else t["value"] < bound
        o = outcomes.get(cid) or {}
        floor = ctx.params.get("spend_floor", cid)
        ev = {"platform_target": t["value"], "platform_source": t["source"], "approved_bound": bound,
              "approved_source": bsrc, "window_cost": o.get("cost"), "window": o.get("window"),
              "spend_floor": floor.value, "spend_floor_source": floor.source or floor.reason}
        if not loose:
            biz.observe(f"Campaign {cid}: platform {t['kind']} target within approved economics", campaign_id=cid, **ev)
            continue
        if floor.value is None or o.get("cost") is None:
            biz.partial(f"campaign {cid}: target beyond approved bound but exposure unknown "
                        f"({floor.reason or 'no mature window cost'})")
            continue
        if o["cost"] < floor.value:
            biz.observe(f"Campaign {cid}: target beyond approved bound with exposure below spend_floor", campaign_id=cid, **ev)
            continue
        biz.finding("relaxed_target_beyond_business_constraint", "Warning",
                    {"campaign_id": cid, "target_type": t["kind"], "target_source": t["source"]},
                    f"Campaign {cid}: platform {t['kind']} target {t['value']:g} is looser than the approved "
                    f"{t['kind']} {bound:g} ({bsrc}); window spend {o['cost']:.2f} {ctx.currency}",
                    evidence=ev, calculation={"exposure_cost": o["cost"], "window": o.get("window")},
                    recommendation="Owner review: realign the target to approved acquisition economics or document the exception.",
                    uncertainty="Window spend is exposure, not savings; a looser target may deliberately trade efficiency for volume.")

    # step 8 — bounded test envelope
    env = ctx.check("bounded_test", "Bounded target test envelope (step 8)")
    for cid, s in sorted(signed.items()):
        t = usable[cid]
        bound, bsrc = _approved(ctx, cid, t["kind"])
        env.observe(f"Campaign {cid}: test envelope (current target, achieved, approved bound)", campaign_id=cid,
                    current_target=t["value"], achieved=s["achieved"], approved_bound=bound, approved_source=bsrc,
                    note="achieved outcome is not a proposed target; sizing via 051 simulator")
        if bound is None:
            env.partial(f"campaign {cid}: no approved bound; test sizing unavailable")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning needs corroboration; test targets stay within approved bounds and never equal achieved."""
    if item.condition_key != "restrictive_target_concern":
        return []
    proposal = decision.get("proposal") or {}
    problems = []
    if decision.get("outcome") == "corroborated_concern" and not proposal.get("corroboration"):
        problems.append("corroborated_concern needs proposal.corroboration listing the evidence used")
    test = proposal.get("test_target")
    if test is None:
        return problems
    test = V.num(test)
    kind, current, achieved = item.entity["target_type"], item.evidence.get("target"), item.evidence.get("achieved")
    bound = item.evidence.get("approved_constraint")
    if test is None or test <= 0:
        return problems + ["proposal.test_target must be a positive number"]
    if kind == "CPA" and not test > current or kind == "ROAS" and not test < current:
        problems.append(f"test_target {test:g} does not loosen the restrictive {kind} target {current:g}")
    if bound is None:
        problems.append("no approved business bound: target sizing is not allowed")
    elif kind == "CPA" and test > bound or kind == "ROAS" and test < bound:
        problems.append(f"test_target {test:g} crosses the approved {kind} bound {bound:g}")
    if achieved is not None and round(test, 2) == round(achieved, 2):
        problems.append("test_target equals the historical achieved outcome; not a reasoned target")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
