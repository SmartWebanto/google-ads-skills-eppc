"""check.py — skill-052 deterministic goal mapping, value-setting inventory, policy ledger and reconciliation gates.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-052-conversion-value-based-bidding/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Optimizing set = ctx.goal_ids(campaign) (profile campaign_objectives, then campaigns.goal_ids);
         primary/include flags alone never establish it — missing goals → partial.
         Value-optimized = bidding_strategy_type TARGET_ROAS / MAXIMIZE_CONVERSION_VALUE (_VALUE_STRATEGIES).
         Configured value_settings are inventoried as dynamic/static/zero/unknown; settings never prove accuracy.
         Reconciliation Warning only on rows whose reconciliation_status is aligned (_ALIGNED), whose currency
         equals the account currency, whose period end + expected_lag <= snapshot, with a policy tolerance for
         the same action/cohort, and |Ads-business|/business > tolerance (business > 0; else absolute only).
         Critical only via review on such a Warning for an action in an active value-optimized goal, with
         verify() demanding proposal.evidence_ref (material corruption).
         Zero/equal/static values are reviewed in goal context (no-finding or Info), never auto-flagged.
         Lead value model = close_rate × contribution_per_closed_customer over the stated horizon; observation only.
         Value-bidding opportunity is an Info review only with mature rows and min_conversions per campaign.
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

SKILL = "skill-052-conversion-value-based-bidding"
VERSION = "1.0.0"

_DAILY = "custom/conversion_value_action_daily"
_POLICY = "external/business_value_policy"
_RECON = "external/business_value_reconciliation"
_VALUE_STRATEGIES = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
_ALIGNED = {"ALIGNED", "RECONCILED", "MATCHED", "COMPLETE", "COMPARABLE"}


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _col(ctx, key, *names) -> str:
    t = ctx.table(key)
    if t is None:
        return names[0]
    return next((n for n in names if n in t.columns), names[0])


def _value_kind(v) -> tuple[str, float | None]:
    s = _s(v).lower()
    if not s:
        return "unknown", None
    if any(w in s for w in ("transaction", "dynamic", "different", "specific")):
        return "dynamic", None
    n = V.num(s.split()[0]) if s.split() else None
    if n is None:
        return "unknown", None
    return ("zero" if n == 0 else "static"), n


def _period_end(v) -> date | None:
    s = _s(v)
    for sep in ("..", "/", " to "):
        if sep in s:
            return V.parse_date(s.split(sep)[-1].strip())
    if len(s) == 7 and s[4] == "-":
        d = V.parse_date(s + "-01")
        return None if d is None else (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return V.parse_date(s)


def _campaigns(ctx) -> list[dict]:
    out = []
    for c in sorted(ctx.rows("campaigns"), key=lambda r: _s(r.get("id"))):
        cid = _s(c.get("id"))
        strat = _s(c.get("bidding_strategy_type")).upper()
        out.append({"id": cid, "status": _s(c.get("status")).upper(), "strategy": strat,
                    "value_based": strat in _VALUE_STRATEGIES, "goals": ctx.goal_ids(cid)})
    return out


def run(ctx) -> None:
    """Run optimizing-goal, value-setting inventory, reconciliation, lead-value and value-bidding opportunity checks.

    Rules:   Optimizing set only from ctx.goal_ids; missing goals → partial. Settings are inventoried, never proof of
             accuracy. Reconciliation Warning only on aligned, same-currency, lag-mature rows with a policy tolerance
             exceeded; Critical only via review for an active value-optimized goal with proposal.evidence_ref.
             Zero/static values are reviewed in goal context, never auto-flagged; value-bidding opportunity is Info
             review with mature min_conversions.
    """
    gm = ctx.check("goal_mapping", "Strategy to optimizing goal/action set (step 1)",
                   {"campaigns": ["id", "bidding_strategy_type"], "conversion_actions": ["id", "status"]})
    later = (("value_settings_inventory", "Default/static/dynamic value settings per action (step 2)"),
             ("value_policy", "Approved value basis and population per action (step 3)"),
             ("reconciliation", "Aligned business vs Ads count/value reconciliation (step 4)"),
             ("zero_equal_values", "Zero/equal/static values in goal context (step 5)"),
             ("lead_value_model", "Expected contribution per lead from policy (step 6)"),
             ("value_bidding_opportunity", "Optional value-differentiation assessment (step 7)"))
    if not gm.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("goal mapping unavailable", gm.missing)
        return
    camps = _campaigns(ctx)
    actions = {_s(a.get("id")): a for a in ctx.rows("conversion_actions")}
    active_value_actions: dict[str, list[str]] = {}
    for c in camps:
        if c["status"] not in ("ENABLED", ""):
            continue
        if not c["goals"]:
            gm.partial(f"campaign {c['id']}: no declared goal_ids; optimizing action set unknown")
            continue
        mapped = [g for g in c["goals"] if g in actions]
        if len(mapped) != len(c["goals"]):
            gm.partial(f"campaign {c['id']}: goals {sorted(set(c['goals']) - set(mapped))} not mapped to action IDs")
        if c["value_based"]:
            for g in mapped:
                active_value_actions.setdefault(g, []).append(c["id"])
        gm.observe(f"Campaign {c['id']} ({c['strategy'] or 'strategy unknown'}) optimizes {mapped}", campaign_id=c["id"],
                   strategy=c["strategy"], value_based=c["value_based"], goal_ids=c["goals"], mapped_actions=mapped)

    inv = ctx.check(later[0][0], later[0][1], {"conversion_actions": ["id", "status", "value_settings"]})
    kinds: dict[str, tuple[str, float | None]] = {}
    if inv.runnable:
        for aid, a in sorted(actions.items()):
            kinds[aid] = _value_kind(a.get("value_settings"))
            inv.observe(f"Action {aid}: value setting {kinds[aid][0]}", action_id=aid, value_settings=a.get("value_settings"),
                        kind=kinds[aid][0], default_value=kinds[aid][1], status=a.get("status"),
                        primary_for_goal=a.get("primary_for_goal"),
                        used_by_value_bidding=active_value_actions.get(aid, []),
                        note="Configuration only; actual transaction values and accuracy need daily and business evidence.")
        if any(k[0] == "unknown" for k in kinds.values()):
            inv.partial("some value settings unparseable; kept unknown")

    pol_cols = ["action_id", "value_cohort", "effective_from", "business_objective", "value_basis",
                "static_or_dynamic_intent", "currency", "owner", "source_ref"]
    pol = ctx.check(later[1][0], later[1][1], {_POLICY: pol_cols})
    policies: dict[str, list[dict]] = {}
    if pol.runnable:
        for r in ctx.rows(_POLICY):
            f, t = V.parse_date(r.get("effective_from")), V.parse_date(r.get("effective_to"))
            if ctx.period_end and f and f > ctx.period_end or (t and ctx.period_start and t < ctx.period_start):
                continue
            policies.setdefault(_s(r.get("action_id")), []).append(r)
        for aid in sorted(set(actions) | set(policies)):
            rows = policies.get(aid, [])
            if not rows:
                if aid in active_value_actions:
                    pol.partial(f"action {aid}: no approved value policy; accuracy unknown (not a defect)")
                continue
            for r in rows:
                cur = _s(r.get("currency")).upper()
                if cur and ctx.currency and cur != ctx.currency:
                    pol.partial(f"action {aid}: policy currency {cur} differs from account {ctx.currency}")
                intent = _s(r.get("static_or_dynamic_intent")).lower()
                kind = kinds.get(aid, ("unknown", None))[0]
                pol.observe(f"Action {aid} cohort {r.get('value_cohort')}: approved basis {r.get('value_basis')}",
                            action_id=aid, value_cohort=r.get("value_cohort"),
                            business_objective=r.get("business_objective"), value_basis=r.get("value_basis"),
                            intent=intent, configured_kind=kind, owner=r.get("owner"), source_ref=r.get("source_ref"),
                            setting_matches_intent=None if kind == "unknown" or not intent else
                            (("dynamic" in intent) == (kind == "dynamic")))

    rc = ctx.check(later[2][0], later[2][1],
                   {_RECON: ["action_id", "value_cohort", "period", "business_event_count", "comparable_business_value",
                             _col(ctx, _RECON, "ads_count", "Ads_count"), _col(ctx, _RECON, "ads_value", "Ads_value"),
                             "expected_lag", "reconciliation_status", "source_ref"]})
    if rc.runnable:
        _reconcile(ctx, rc, policies, active_value_actions)

    ze = ctx.check(later[3][0], later[3][1], {_DAILY: ["campaign_id", "action_id", "date", "conversions",
                                                       "conversion_value", "lag_mature"]})
    per: dict[tuple, list[float]] = {}
    if ze.runnable:
        per = _zero_equal(ctx, ze, camps, kinds, policies)

    lm = ctx.check(later[4][0], later[4][1], {_POLICY: ["action_id", "value_cohort", "close_rate",
                                                        "contribution_per_closed_customer", "horizon"]})
    if lm.runnable:
        for r in sorted(ctx.rows(_POLICY), key=lambda r: (_s(r.get("action_id")), _s(r.get("value_cohort")))):
            cr, contrib = ctx.rate(r.get("close_rate")), ctx.money(r.get("contribution_per_closed_customer"))
            if cr is None or contrib is None:
                continue
            lm.observe(f"Action {r.get('action_id')} cohort {r.get('value_cohort')}: expected contribution per lead",
                       action_id=r.get("action_id"), value_cohort=r.get("value_cohort"), close_rate=cr,
                       contribution_per_closed_customer=contrib, expected_contribution_per_lead=cr * contrib,
                       horizon=r.get("horizon"), approved_value=ctx.money(r.get("approved_value")),
                       note="Proposal input only; requires cohort maturity and owner approval; no multiplier invented.")

    vb = ctx.check(later[5][0], later[5][1], {_DAILY: ["campaign_id", "action_id", "conversions", "conversion_value",
                                                       "lag_mature"], _POLICY: ["action_id", "static_or_dynamic_intent"]})
    if vb.runnable:
        if ctx.mature is not True:
            vb.partial(f"maturity not established ({ctx.maturity_note}); no opportunity assessment")
            return
        min_conv = ctx.params.get("min_conversions")
        for c in camps:
            if c["value_based"] or c["status"] not in ("ENABLED", "") or not c["goals"]:
                continue
            conv = sum(v[0] for (cid, aid), v in per.items() if cid == c["id"] and aid in c["goals"])
            dyn = [g for g in c["goals"] if any("dynamic" in _s(p.get("static_or_dynamic_intent")).lower()
                                                 for p in policies.get(g, []))]
            if not dyn:
                continue
            if min_conv.value is None or conv < min_conv.value:
                vb.observe(f"Campaign {c['id']}: below min_conversions for value-bidding assessment",
                           campaign_id=c["id"], conversions=conv, min_conversions=min_conv.value)
                continue
            vb.review("value_bidding_opportunity", {"campaign_id": c["id"]},
                      f"Would value differentiation on {dyn} better align campaign {c['id']} ({c['strategy']}) "
                      "with its approved objective?",
                      evidence={"strategy": c["strategy"], "goal_ids": c["goals"], "dynamic_policy_actions": dyn,
                                "mature_conversions": conv, "min_conversions": min_conv.value,
                                "min_conversions_source": min_conv.source},
                      outcomes={"evaluate_value_bidding": {"severity": "Info", "recommendation":
                                                           "Owner-reviewed controlled evaluation after reconciliation."},
                                "not_beneficial": {"severity": None, "recommendation": "Keep count-based bidding."},
                                "uncertain": {"severity": "Info", "recommendation": "Request value policy/reconciliation."}},
                      guidance="No forced migration, uplift forecast or new micro-conversion values.")


def _reconcile(ctx, rc, policies, active_value_actions) -> None:
    ac, av = _col(ctx, _RECON, "ads_count", "Ads_count"), _col(ctx, _RECON, "ads_value", "Ads_value")
    for r in sorted(ctx.rows(_RECON), key=lambda r: (_s(r.get("action_id")), _s(r.get("value_cohort")),
                                                      _s(r.get("period")))):
        aid, cohort = _s(r.get("action_id")), _s(r.get("value_cohort"))
        ent = {"action_id": aid, "value_cohort": cohort, "period": r.get("period")}
        bv, adv = ctx.money(r.get("comparable_business_value")), ctx.money(r.get(av))
        bc, adc = V.num(r.get("business_event_count")), V.num(r.get(ac))
        calc = {"business_value": bv, "ads_value": adv, "abs_value_diff": None if None in (bv, adv) else adv - bv,
                "value_variance": V.ratio(None if None in (bv, adv) else adv - bv, bv),
                "business_count": bc, "ads_count": adc, "abs_count_diff": None if None in (bc, adc) else adc - bc,
                "count_variance": V.ratio(None if None in (bc, adc) else adc - bc, bc),
                "exclusions": r.get("exclusions"), "source_ref": r.get("source_ref"), "currency": ctx.currency}
        status = _s(r.get("reconciliation_status")).upper()
        end = _period_end(r.get("period"))
        lag = V.integer(r.get("expected_lag"))
        mature = None if end is None or lag is None or ctx.snapshot is None else (ctx.snapshot - end).days >= lag
        tol_rows = [p for p in policies.get(aid, []) if _s(p.get("value_cohort")) in (cohort, "")]
        tol = next((ctx.rate(p.get("tolerance")) for p in tol_rows if ctx.rate(p.get("tolerance")) is not None), None)
        calc.update({"reconciliation_status": status, "period_end": end, "expected_lag_days": lag, "lag_mature": mature,
                     "tolerance": tol})
        blockers = []
        if status not in _ALIGNED:
            blockers.append(f"status {status or 'unknown'} not aligned")
        if mature is not True:
            blockers.append("lag maturity not established")
        if tol is None:
            blockers.append("no approved tolerance")
        if calc["value_variance"] is None:
            blockers.append("business value zero/unknown: percent variance unavailable")
        if blockers:
            rc.partial(f"action {aid} {cohort}: {'; '.join(blockers)}")
            rc.observe(f"Action {aid} {cohort}: reconciliation descriptive only", **ent, **calc, blockers=blockers)
            continue
        if abs(calc["value_variance"]) <= tol:
            rc.observe(f"Action {aid} {cohort}: value variance within approved tolerance", **ent, **calc)
            continue
        rc.finding("value_discrepancy_outside_tolerance", "Warning", ent,
                   f"Action {aid} ({cohort}) Ads value differs from business value by {calc['value_variance']:+.1%} "
                   f"(tolerance {tol:.1%}) for {r.get('period')}",
                   evidence=calc, calculation={"value_variance": "(ads_value - business_value) / business_value"},
                   recommendation="Reconcile value definitions with the owner (071/107 for transaction level).",
                   uncertainty="Aggregated comparison; timing, exclusions and attribution can explain part of the gap.")
        if aid in active_value_actions:
            rc.review("material_value_corruption", {**ent, "value_bidding_campaigns": active_value_actions[aid]},
                      f"Is the {calc['value_variance']:+.1%} value discrepancy on action {aid}, used by value bidding in "
                      f"{active_value_actions[aid]}, a verified MATERIAL corruption of the optimization signal?",
                      evidence=calc,
                      outcomes={"material_corruption_evidenced": {"severity": "Critical", "recommendation":
                                                                  "Prioritize value repair before any target change."},
                                "not_material": {"severity": None, "recommendation": "Keep the Warning reconciliation."}},
                      guidance="Critical needs proposal.evidence_ref to supplied business/finance evidence.")


def _zero_equal(ctx, ze, camps, kinds, policies) -> dict[tuple, list[float]]:
    if ctx.mature is not True:
        ze.partial(f"maturity not established ({ctx.maturity_note}); descriptive values only")
    per: dict[tuple, list[float]] = {}
    perconv: dict[tuple, set] = {}
    immature = unknown = 0
    for r in ctx.rows(_DAILY):
        if V.boolean(r.get("lag_mature")) is not True:
            immature += 1
            continue
        cv, val = V.num(r.get("conversions")), V.num(r.get("conversion_value"))
        if cv is None or val is None:
            unknown += 1
            continue
        key = (_s(r.get("campaign_id")), _s(r.get("action_id")))
        a = per.setdefault(key, [0.0, 0.0])
        a[0] += cv
        a[1] += val
        if cv > 0:
            perconv.setdefault(key, set()).add(round(val / cv, 4))
    if immature:
        ze.partial(f"{immature} action-days not lag-mature excluded")
    if unknown:
        ze.partial(f"{unknown} action-days with unknown conversions/value excluded")
    value_camps = {c["id"]: c for c in camps if c["value_based"]}
    for (cid, aid), (cv, val) in sorted(per.items()):
        if cid not in value_camps or aid not in value_camps[cid]["goals"] or cv <= 0:
            continue
        distinct = perconv.get((cid, aid), set())
        pattern = "zero" if val == 0 else "equal" if len(distinct) == 1 else None
        ent = {"campaign_id": cid, "action_id": aid}
        ev = {"conversions": cv, "conversion_value": val, "value_per_conversion": V.ratio(val, cv),
              "distinct_daily_value_per_conversion": sorted(distinct), "configured": kinds.get(aid, ("unknown",))[0],
              "strategy": value_camps[cid]["strategy"],
              "policy": [{k: p.get(k) for k in ("value_cohort", "value_basis", "static_or_dynamic_intent",
                                                "approved_value")} for p in policies.get(aid, [])]}
        if pattern is None:
            ze.observe(f"Campaign {cid} action {aid}: differentiated values", **ent, **ev)
            continue
        if ctx.mature is not True:
            ze.observe(f"Campaign {cid} action {aid}: {pattern} values (immature window)", **ent, **ev)
            continue
        ze.review("zero_or_equal_values_in_value_bidding", ent,
                  f"Are the {pattern} values of action {aid} valid for value bidding in campaign {cid} given the approved "
                  "value policy?", evidence=ev,
                  outcomes={"intentional_valid": {"severity": None, "recommendation": "Document the approved basis."},
                            "differentiation_opportunity": {"severity": "Info", "recommendation":
                                                            "Owner reviews value definitions before any change."},
                            "uncertain": {"severity": "Info", "recommendation": "Request the approved value policy."}},
                  guidance="Equal approved expected values and count-based goals can be valid; no forced dynamic values.")
    return per


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical material corruption needs proposal.evidence_ref."""
    if decision.get("outcome") == "material_corruption_evidenced" and not _s((decision.get("proposal") or {}).get(
            "evidence_ref")):
        return ["material corruption needs proposal.evidence_ref pointing at supplied business evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
