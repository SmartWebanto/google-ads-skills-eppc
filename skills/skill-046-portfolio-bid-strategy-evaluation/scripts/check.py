"""check.py — skill-046 deterministic portfolio membership, goal mapping, pooled outcomes and dispersion.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-046-portfolio-bid-strategy-evaluation/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Membership only from bidding_strategies.campaign_ids and campaigns.bidding_strategy_id|strategy_id — never
         from shared budgets or names; disagreeing sources or members outside the export → partial scope.
         Goals via ctx.goal_ids; unknown member goals → Info. Goal-set differences or a portfolio target looser than
         a member's approved profile target are review items (Warning only via review, never automatic Critical).
         Portfolio outcomes = sums; member shares carry numerator/denominator; missing member metrics are unknown.
         Dispersion: unweighted population stdev / positive mean of member CPA (ROAS for value strategies) over
         mature members with one shared goal set and >= min_conversions; n < 2 → unavailable.
         CV > 0.40, one member > 60% of conversions (portfolios with >= 2 members) and low member volume are Info only.
         verify(): Warning outcomes need proposal.documented_constraint citing the goal/guardrail source.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-046-portfolio-bid-strategy-evaluation"
VERSION = "1.0.0"

VALUE_TYPES = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
CV_LIMIT = 0.40
DOMINANCE = 0.60
SEPS = (";", "|", ",")
METRIC_COLS = ["campaign_id", "cost", "conversions", "conversion_value"]


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _pos(v) -> float | None:
    f = V.num(v)
    return f if f is not None and f > 0 else None


def _objective(ctx, cid: str) -> dict:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    return obj if isinstance(obj, dict) else {}


def run(ctx) -> None:
    """Run portfolio membership, goal-mix, outcome, dispersion/dominance, guardrail and separation checks.

    Rules:   Membership source disagreement or members outside the export → partial scope, never guessed. Unknown member
             goals, CV > 0.40, >60% conversion dominance and low member volume are Info; unknown outcomes are not zero.
             Goal conflicts and guardrail breaches (mature outcomes) are provisional Info reaching Warning only via
             review. No Critical path; split benefits are never sized without supplied separation evidence.
    """
    min_conv = ctx.params.get("min_conversions")
    names = [("member_goal_map", "Member goals, values and roles (step 2)"),
             ("portfolio_outcomes", "Summed portfolio outcomes and member shares (step 3)"),
             ("member_dispersion", "Comparable mature member dispersion (step 4)"),
             ("triage_heuristics", "CV, dominance and low-volume triage (step 5)"),
             ("guardrail_check", "Member guardrails vs pooled outcomes (step 6)"),
             ("split_evidence", "Evidence for split/retention proposals (step 7)")]

    # step 1 — inventory
    inv = ctx.check("portfolio_inventory", "Portfolio IDs, types, targets and linked campaigns (step 1)",
                    {"bidding_strategies": ["id", "type", "campaign_ids"], "campaigns": ["id"]})
    if not inv.runnable:
        for cid, title in names:
            ctx.check(cid, title).skip("portfolio inventory unavailable", inv.missing)
        return
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}
    portfolios: dict[str, dict] = {}
    for s in sorted(ctx.rows("bidding_strategies"), key=lambda r: _s(r.get("id"))):
        sid = _s(s.get("id"))
        listed = set(V.split_list(s.get("campaign_ids"), SEPS))
        linked = {cid for cid, r in camps.items() if _s(r.get("bidding_strategy_id") or r.get("strategy_id")) == sid}
        members = sorted(listed | linked)
        if not members:
            inv.observe(f"Strategy {sid}: no linked campaigns", strategy_id=sid)
            continue
        if listed and linked and listed != linked:
            inv.partial(f"strategy {sid}: membership sources disagree (strategy {sorted(listed)} vs campaigns {sorted(linked)})")
        outside = sorted(m for m in members if m not in camps)
        if outside:
            inv.partial(f"strategy {sid}: members {outside} outside the campaign export; partial scope")
        portfolios[sid] = {"type": _s(s.get("type")).upper(), "target_cpa": _pos(s.get("target_cpa")),
                           "target_roas": _pos(s.get("target_roas")), "members": members, "outside": outside}
        inv.observe(f"Portfolio {sid}: {len(members)} members", strategy_id=sid, **portfolios[sid])
    if not portfolios:
        inv.observe("No portfolio strategy with linked campaigns")

    # step 2 — goals
    gm = ctx.check("member_goal_map", names[0][1], {"bidding_strategies": ["id", "type", "campaign_ids"]})
    goals: dict[str, tuple] = {}
    for sid, p in sorted(portfolios.items()):
        unknown, conflicts = [], []
        for m in p["members"]:
            goals[m] = tuple(sorted(ctx.goal_ids(m)))
            if not goals[m]:
                unknown.append(m)
            o = _objective(ctx, m)
            if p["target_cpa"] and _pos(o.get("target_cpa")) and p["target_cpa"] > _pos(o.get("target_cpa")):
                conflicts.append(f"portfolio tCPA {p['target_cpa']:g} looser than member {m} approved CPA {_pos(o.get('target_cpa')):g}")
            if p["target_roas"] and _pos(o.get("target_roas")) and p["target_roas"] < _pos(o.get("target_roas")):
                conflicts.append(f"portfolio tROAS {p['target_roas']:g} looser than member {m} approved ROAS {_pos(o.get('target_roas')):g}")
        sets = sorted({g for m, g in goals.items() if m in p["members"] and g})
        if len(sets) > 1:
            conflicts.append(f"members declare different goal sets {[list(s) for s in sets]}")
        ledger = {m: {"goal_ids": list(goals[m]), "role": _objective(ctx, m).get("role"),
                      "approved_cpa": _objective(ctx, m).get("target_cpa"), "approved_roas": _objective(ctx, m).get("target_roas")}
                  for m in p["members"]}
        gm.observe(f"Portfolio {sid}: member goal ledger", strategy_id=sid, members=ledger)
        if unknown:
            gm.finding("unknown_member_goals", "Info", {"strategy_id": sid},
                       f"Portfolio {sid}: members {unknown} have no declared goals; compatibility not verifiable",
                       evidence={"members": unknown}, recommendation="Declare member goals/value definitions in the profile.",
                       uncertainty="Unknown goals are not evidence of conflict.")
        if conflicts:
            entity = {"strategy_id": sid}
            prov = gm.finding("portfolio_goal_conflict", "Info", entity,
                              f"Portfolio {sid}: potential goal/economic contradictions ({len(conflicts)})",
                              evidence={"conflicts": conflicts, "members": ledger},
                              recommendation="Owner review of goal/target configuration; pooling may be intentional.",
                              uncertainty="Different roles or values can be compatible by design.")
            gm.review("portfolio_goal_conflict", entity,
                      f"Do portfolio {sid}'s settings conflict with documented member goals or economic constraints?",
                      evidence={"conflicts": conflicts, "members": ledger, "portfolio": p},
                      outcomes={"confirmed_conflict": {"severity": "Warning", "recommendation":
                                                       "Targeted configuration/goal review or controlled portfolio experiment."},
                                "compatible_by_design": {"severity": None, "recommendation": "Keep pooling; document rationale."},
                                "uncertain": {"severity": "Info", "recommendation": "Request the owner's goal definitions."}},
                      guidance="confirmed_conflict needs proposal.documented_constraint citing the approved goal/guardrail.",
                      provisional=prov)

    # step 3 — outcomes
    po = ctx.check("portfolio_outcomes", names[1][1], {"campaign_metrics": METRIC_COLS})
    outcomes: dict[str, dict] = {}
    if po.runnable:
        metrics: dict[str, list] = {}
        for r in ctx.rows("campaign_metrics"):
            metrics.setdefault(_s(r.get("campaign_id")), []).append(r)
        for sid, p in sorted(portfolios.items()):
            rows, missing = {}, []
            for m in p["members"]:
                rs = metrics.get(m, [])
                vals = (ctx.money(rs[0].get("cost")), V.num(rs[0].get("conversions")), ctx.money(rs[0].get("conversion_value"))) \
                    if len(rs) == 1 else None
                if vals is None or vals[0] is None or vals[1] is None:
                    missing.append(m)
                else:
                    rows[m] = {"cost": vals[0], "conversions": vals[1], "value": vals[2]}
            if missing:
                po.partial(f"portfolio {sid}: member outcomes unknown for {missing} (not zero)")
            cost = sum(r["cost"] for r in rows.values())
            conv = sum(r["conversions"] for r in rows.values())
            val = None if any(r["value"] is None for r in rows.values()) else sum(r["value"] for r in rows.values())
            shares = {m: {"cost": r["cost"], "conversions": r["conversions"], "spend_share": V.ratio(r["cost"], cost),
                          "conversion_share": V.ratio(r["conversions"], conv)} for m, r in rows.items()}
            outcomes[sid] = {"members": rows, "missing": missing, "cost": cost, "conversions": conv, "value": val,
                             "cpa": V.ratio(cost, conv), "roas": V.ratio(val, cost), "shares": shares}
            po.observe(f"Portfolio {sid}: summed outcomes and member shares (dominance is not starvation)", strategy_id=sid,
                       cost=cost, conversions=conv, value=val, cpa=outcomes[sid]["cpa"], roas=outcomes[sid]["roas"],
                       shares=shares, coverage=f"{len(rows)}/{len(p['members'])} members")

    # step 4 — dispersion
    dp = ctx.check("member_dispersion", names[2][1], {"campaign_metrics": METRIC_COLS})
    dispersion: dict[str, dict] = {}
    if dp.runnable:
        if ctx.mature is not True:
            dp.partial(f"member outcomes not mature: {ctx.maturity_note}")
        for sid, o in sorted(outcomes.items()):
            if ctx.mature is not True:
                break
            metric = "roas" if portfolios[sid]["type"] in VALUE_TYPES else "cpa"
            by_goal: dict[tuple, list] = {}
            excluded = {}
            for m, r in sorted(o["members"].items()):
                if not goals.get(m):
                    excluded[m] = "unknown goals"
                elif min_conv.value is None or r["conversions"] < min_conv.value:
                    excluded[m] = f"conversions {r['conversions']} < min_conversions {min_conv.value}"
                else:
                    x = V.ratio(r["cost"], r["conversions"]) if metric == "cpa" else V.ratio(r["value"], r["cost"])
                    if x is None:
                        excluded[m] = f"{metric} unavailable"
                    else:
                        by_goal.setdefault(goals[m], []).append((m, x))
            for g, vals in sorted(by_goal.items()):
                xs = [x for _, x in vals]
                mean = statistics.mean(xs) if xs else 0
                cv = statistics.pstdev(xs) / mean if len(xs) >= 2 and mean > 0 else None
                res = {"metric": metric, "goal_ids": list(g), "included": [m for m, _ in vals], "values": xs,
                       "cv": cv, "method": "unweighted population stdev / mean", "excluded": excluded}
                dispersion.setdefault(sid, {})[g] = res
                dp.observe(f"Portfolio {sid}: {metric.upper()} dispersion for goal cohort {list(g)}", strategy_id=sid, **res)
                if cv is None:
                    dp.partial(f"portfolio {sid} cohort {list(g)}: fewer than 2 qualifying members; CV unavailable")
            if not by_goal:
                dp.partial(f"portfolio {sid}: no comparable qualifying members ({excluded})")

    # step 5 — triage
    tr = ctx.check("triage_heuristics", names[3][1], {"campaign_metrics": METRIC_COLS})
    if tr.runnable:
        for sid, o in sorted(outcomes.items()):
            for g, res in sorted(dispersion.get(sid, {}).items()):
                if res["cv"] is not None and res["cv"] > CV_LIMIT:
                    tr.finding("member_outcome_dispersion", "Info", {"strategy_id": sid, "goal_cohort": "|".join(g)},
                               f"Portfolio {sid}: member {res['metric'].upper()} CV {res['cv']:.2f} > {CV_LIMIT}",
                               evidence=res, recommendation="Review roles/values before any split; no automatic outlier removal.",
                               uncertainty="Heterogeneous outcomes may be intentional role/value differences.")
            if not o["missing"] and o["conversions"] > 0 and len(o["members"]) >= 2:
                for m, sh in sorted(o["shares"].items()):
                    if sh["conversion_share"] is not None and sh["conversion_share"] > DOMINANCE:
                        tr.finding("member_conversion_dominance", "Info", {"strategy_id": sid, "campaign_id": m},
                                   f"Portfolio {sid}: member {m} holds {sh['conversion_share']:.0%} of conversions "
                                   f"({sh['conversions']:g}/{o['conversions']:g})", evidence=sh,
                                   recommendation="Descriptive only; dominance is not starvation or signal dilution.",
                                   uncertainty="Pooling can legitimately concentrate volume.")
            elif o["missing"]:
                tr.partial(f"portfolio {sid}: dominance not computed with unknown member outcomes")
            low = sorted(m for m, r in o["members"].items() if min_conv.value is not None and r["conversions"] < min_conv.value)
            if low:
                tr.finding("low_member_volume", "Info", {"strategy_id": sid},
                           f"Portfolio {sid}: members {low} below {min_conv.value} conversions",
                           evidence={"members": {m: o["members"][m]["conversions"] for m in low}, "min_conversions": min_conv.value},
                           recommendation="No action implied; low-volume members are not harmful to the portfolio by themselves.",
                           uncertainty="Small samples only limit comparisons.")

    # step 6 — guardrails
    gc = ctx.check("guardrail_check", names[4][1], {"campaign_metrics": METRIC_COLS})
    if gc.runnable:
        if ctx.mature is not True:
            gc.partial(f"guardrail comparison needs mature outcomes: {ctx.maturity_note}")
        for sid, o in sorted(outcomes.items()):
            if ctx.mature is not True:
                break
            p = portfolios[sid]
            gc.observe(f"Portfolio {sid}: pooled outcome vs portfolio target", strategy_id=sid, pooled_cpa=o["cpa"],
                       pooled_roas=o["roas"], target_cpa=p["target_cpa"], target_roas=p["target_roas"])
            for m, r in sorted(o["members"].items()):
                obj = _objective(ctx, m)
                if min_conv.value is None or r["conversions"] < min_conv.value:
                    continue
                breach = None
                cpa, roas = V.ratio(r["cost"], r["conversions"]), V.ratio(r["value"], r["cost"])
                if _pos(obj.get("target_cpa")) and cpa is not None and cpa > _pos(obj.get("target_cpa")):
                    breach = {"metric": "CPA", "achieved": cpa, "guardrail": _pos(obj.get("target_cpa"))}
                elif _pos(obj.get("target_roas")) and roas is not None and roas < _pos(obj.get("target_roas")):
                    breach = {"metric": "ROAS", "achieved": roas, "guardrail": _pos(obj.get("target_roas"))}
                if breach is None:
                    continue
                entity = {"strategy_id": sid, "campaign_id": m}
                ev = {**breach, "guardrail_source": f"profile.campaign_objectives[{m}]", "cost": r["cost"],
                      "conversions": r["conversions"], "value": r["value"], "window": [ctx.period_start, ctx.period_end],
                      "role": obj.get("role")}
                prov = gc.finding("member_guardrail_breach", "Info", entity,
                                  f"Portfolio {sid}: member {m} {breach['metric']} {breach['achieved']:.2f} outside approved "
                                  f"{breach['guardrail']:g}", evidence=ev,
                                  recommendation="Owner review of member role/value before configuration change.",
                                  uncertainty="Pooled optimization can trade member efficiency for portfolio goals by design.")
                gc.review("member_guardrail_breach", entity,
                          f"Is member {m}'s guardrail miss a genuine conflict with documented economics, not an intentional role difference?",
                          evidence=ev, provisional=prov,
                          outcomes={"confirmed_conflict": {"severity": "Warning", "recommendation":
                                                           "Targeted goal/target review or controlled portfolio experiment."},
                                    "intentional_difference": {"severity": None, "recommendation": "Keep pooling; document."},
                                    "uncertain": {"severity": "Info", "recommendation": "Request the member's role/value definition."}},
                          guidance="confirmed_conflict needs proposal.documented_constraint citing the guardrail.")

    # step 7 — split evidence
    se = ctx.check("split_evidence", names[5][1])
    if portfolios:
        se.partial("no measured/modelled separation response in the recipe inputs: split benefits cannot be sized")
        se.observe("Retention benefits to weigh before any split: pooled signal, shared learning, fewer restarts",
                   portfolios=sorted(portfolios))


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning outcomes cite a documented constraint."""
    if decision.get("outcome") == "confirmed_conflict" and not (decision.get("proposal") or {}).get("documented_constraint"):
        return ["confirmed_conflict needs proposal.documented_constraint"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
