"""check.py — skill-001 deterministic campaign architecture inventory against approved objectives.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-001-campaign-type-separation/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #78 Account Structure Auditor (Google Ads scripts solutions) — clean-room reimplementation of
         per-campaign ad-group / enabled-ad counts as inventory observations (no count thresholds).
         index #112 Google Ads account structure improvement opportunities (google/ads-account-structure-script) —
         clean-room reimplementation of Search spend share by bidding strategy and low-conversion campaigns in
         compatible groups as consolidation REVIEW items; min_conversions (PARAMETERS.md) replaces 10/week.
rules:   Features, objectives and roles never come from names or bidding; roles only from
         profile.campaign_objectives, features only from custom/campaign_features.
         Cost is taken once per campaign: duplicated campaign_metrics rows are excluded (fan-out), never summed.
         Budgets: shared amounts deduplicated by budget_id; without budgets table a shared flag blocks summing.
         Channel mix, share and optional-feature absence are observations; Info only for unknown objectives and
         Shopping+PMax coexistence (overlap unknown). Warning 'setting contradicts approved objective/control' is
         an ai_review outcome (provisional Info) — bidding type vs approved goal is a hypothesis, not proof.
         Consolidation reviews need ctx.mature True and identical channel/role/goal_ids/strategy/geo/language;
         verify() rejects consolidation of campaigns outside the reviewed group.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial deterministic check
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

SKILL = "skill-001-campaign-type-separation"
VERSION = "1.0.0"

CAMP = ["id", "name", "status", "channel_type", "bidding_strategy_type"]
FEAT = ["account_id", "campaign_id", "feature_name", "status", "source", "snapshot_date"]
CONV_BIDDING = {"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"}
VALUE_BIDDING = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
COUNT_BIDDING = {"TARGET_CPA", "MAXIMIZE_CONVERSIONS"}


def _objective(ctx, cid) -> dict | None:
    objs = ctx.profile.get("campaign_objectives")
    if not isinstance(objs, dict):
        return None
    obj = next((v for k, v in objs.items() if str(k) == str(cid)), None)
    return obj if isinstance(obj, dict) else None


def _live(ctx) -> dict[str, dict]:
    return {str(c.get("id")): c for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id")))
            if str(c.get("status") or "").upper() in ("ENABLED", "PAUSED")}


def _cost(ctx, chk) -> dict[str, dict]:
    rows: dict[str, list[dict]] = {}
    for r in ctx.rows("campaign_metrics"):
        rows.setdefault(str(r.get("campaign_id")), []).append(r)
    out = {}
    for cid in sorted(rows):
        if len(rows[cid]) > 1:
            chk.partial(f"campaign {cid}: {len(rows[cid])} metric rows (segments/fan-out) — excluded, not summed")
            continue
        r = rows[cid][0]
        out[cid] = {"cost": ctx.money(r.get("cost")), "conversions": V.num(r.get("conversions")),
                    "clicks": V.num(r.get("clicks")), "conversion_value": ctx.money(r.get("conversion_value"))}
    return out


def run(ctx) -> None:
    """Run scope, inventory, channel-share, objective, consolidation, feature, routing and prerequisite checks.

    Rules:   Without profile.campaign_objectives objective_coverage and separation_rationale skip (inventory only);
             bidding-vs-objective conflicts are provisional Info + ai_review 'setting_contradicts_objective' (Warning
             only on 'contradicts'); consolidation reviews need ctx.mature True and a campaign below min_conversions;
             Info only for objective_unknown/product_overlap_unknown; shares and budgets are observations.
    """
    camps = _live(ctx)
    objs_supplied = isinstance(ctx.profile.get("campaign_objectives"), dict) and bool(ctx.profile.get("campaign_objectives"))

    # -- step 1: scope, window, maturity, metric grain
    scope = ctx.check("scope", "Account window, maturity and campaign metric grain",
                      {"campaign_metrics": ["campaign_id", "cost"], "campaigns": ["id"]})
    metrics: dict[str, dict] = {}
    if scope.runnable:
        metrics = _cost(ctx, scope)
        scope.observe("Scope", currency=ctx.currency, window=[ctx.period_start, ctx.period_end], snapshot=ctx.snapshot,
                      conversion_date_basis=ctx.account.get("conversion_date_basis"), mature=ctx.mature,
                      maturity_note=ctx.maturity_note, campaigns_with_metrics=len(metrics))
        orphans = sorted(set(metrics) - {str(c.get("id")) for c in ctx.rows("campaigns")})
        if orphans:
            scope.partial(f"metrics for campaigns absent from inventory: {orphans}")

    # -- step 2 (+ #78): inventory by explicit type, objective, market, budget, strategy
    inv = ctx.check("inventory", "Enabled/paused campaign inventory by explicit settings", {"campaigns": CAMP})
    if inv.runnable:
        for t, why in (("budgets", "budget IDs/amounts"), ("bidding_strategies", "portfolio strategies")):
            if ctx.table(t) is None:
                inv.partial(f"{t} missing: {why} unknown", [f"{t} (file)"])
        ag = {}
        for g in ctx.rows("ad_groups"):
            if str(g.get("status") or "ENABLED").upper() != "REMOVED":
                ag.setdefault(str(g.get("campaign_id")), set()).add(str(g.get("id")))
        ads = {}
        for a in ctx.rows("ads"):
            if str(a.get("status") or "").upper() == "ENABLED":
                ads.setdefault(str(a.get("campaign_id")), set()).add(str(a.get("id")))
        for cid, c in camps.items():
            obj = _objective(ctx, cid)
            inv.observe(f"Campaign {cid} inventory", campaign_id=cid, status=c.get("status"), channel=c.get("channel_type"),
                        sub_type=c.get("advertising_channel_sub_type"), strategy=c.get("bidding_strategy_type"),
                        strategy_id=c.get("bidding_strategy_id"), budget_id=c.get("budget_id"),
                        daily_budget=ctx.money(c.get("daily_budget")), shared_budget=V.boolean(c.get("shared_budget")),
                        markets=c.get("geo_targets"), objective=obj,
                        ad_groups=len(ag.get(cid, ())) if ctx.table("ad_groups") else None,
                        enabled_ads=len(ads.get(cid, ())) if ctx.table("ads") else None)

    # -- step 3: cost once per campaign, channel share within objectives; budgets deduplicated
    mix = ctx.check("channel_share", "Channel cost share within comparable objectives",
                    {"campaign_metrics": ["campaign_id", "cost"], "campaigns": ["id", "channel_type"]})
    if mix.runnable:
        by_role: dict[str, dict[str, float]] = {}
        unknown_cost = []
        for cid, m in metrics.items():
            c = camps.get(cid)
            if c is None:
                continue
            if m["cost"] is None:
                unknown_cost.append(cid)
                continue
            role = str((_objective(ctx, cid) or {}).get("role") or "unknown_objective")
            ch = str(c.get("channel_type") or "UNKNOWN").upper()
            by_role.setdefault(role, {}).setdefault(ch, 0.0)
            by_role[role][ch] += m["cost"]
        for role in sorted(by_role):
            total = sum(by_role[role].values())
            mix.observe(f"Objective '{role}': channel cost share", objective=role, total_cost=total,
                        shares={ch: V.ratio(v, total) for ch, v in sorted(by_role[role].items())},
                        costs=by_role[role], window=[ctx.period_start, ctx.period_end])
        if unknown_cost:
            mix.partial(f"unknown cost for campaigns {unknown_cost}")
        budgets = ctx.table("budgets")
        daily, note = 0.0, ""
        if budgets is not None and not budgets.missing(["id", "amount"]):
            daily = sum(ctx.money(b.get("amount")) or 0 for b in {str(b.get("id")): b for b in budgets.rows}.values())
            note = "budgets deduplicated by budget id"
        elif any(V.boolean(c.get("shared_budget")) is not False for c in camps.values()):
            daily, note = None, "shared/unknown budget flags without budgets table: not summed"
            mix.partial(note, ["budgets (file)"])
        else:
            daily = sum(ctx.money(c.get("daily_budget")) or 0 for c in camps.values() if str(c.get("status")).upper() == "ENABLED")
            note = "sum of non-shared enabled campaign daily budgets"
        mix.observe("Daily budget total (descriptive, not an optimum)", daily_budget_total=daily, method=note)
        # #112: Search spend share by bidding strategy type
        search = {cid: m for cid, m in metrics.items() if cid in camps and str(camps[cid].get("channel_type")).upper() == "SEARCH"
                  and m["cost"] is not None}
        s_total = sum(m["cost"] for m in search.values())
        by_strat: dict[str, float] = {}
        for cid, m in search.items():
            k = str(camps[cid].get("bidding_strategy_type") or "UNKNOWN").upper()
            by_strat[k] = by_strat.get(k, 0.0) + m["cost"]
        mix.observe("Search cost share by bidding strategy (context, no adoption target)",
                    shares={k: V.ratio(v, s_total) for k, v in sorted(by_strat.items())},
                    conversion_based_share=V.ratio(sum(v for k, v in by_strat.items() if k in CONV_BIDDING), s_total))

    # -- step 4: objectives vs coverage and settings
    obj = ctx.check("objective_coverage", "Approved objectives vs campaign coverage and settings", {"campaigns": CAMP})
    if obj.runnable and not objs_supplied:
        obj.skip("no approved campaign objectives: inventory only", ["profile:campaign_objectives"])
    elif obj.runnable:
        for cid, c in camps.items():
            o = _objective(ctx, cid)
            if o is None:
                if str(c.get("status")).upper() == "ENABLED":
                    obj.finding("objective_unknown", "Info", {"campaign_id": cid},
                                f"Enabled campaign {cid} has no approved objective in the profile",
                                evidence={"channel": c.get("channel_type"), "strategy": c.get("bidding_strategy_type")},
                                recommendation="Ask the owner for this campaign's objective; do not infer it from name or bidding.",
                                uncertainty="Unknown objective, not a defect.")
                continue
            strat = str(c.get("bidding_strategy_type") or "").upper()
            conflict = None
            if o.get("target_roas") is not None and strat in COUNT_BIDDING:
                conflict = f"approved ROAS objective but count-based strategy {strat}"
            elif o.get("target_cpa") is not None and strat in VALUE_BIDDING:
                conflict = f"approved CPA objective but value-based strategy {strat}"
            else:
                for k in ("target_cpa", "target_roas"):
                    want, have = V.num(o.get(k)), V.num(c.get(k))
                    if want is not None and have is not None and abs(want - have) > 1e-9:
                        conflict = f"campaign {k} {have:g} differs from approved {want:g}"
            if conflict:
                ev = {"objective": o, "strategy": strat, "campaign_target_cpa": c.get("target_cpa"),
                      "campaign_target_roas": c.get("target_roas"), "conflict": conflict}
                prov = obj.finding("objective_setting_unverified", "Info", {"campaign_id": cid},
                                   f"Campaign {cid}: {conflict}", evidence=ev,
                                   recommendation="Owner confirms whether the setting is intentional.",
                                   uncertainty="Bidding setup alone does not establish the goal.")
                obj.review("setting_contradicts_objective", {"campaign_id": cid},
                           f"Does campaign {cid}'s setting contradict its approved objective ({conflict})?",
                           evidence=ev, provisional=prov,
                           outcomes={"contradicts": {"severity": "Warning", "recommendation":
                                                     "Owner reviews the setting against the approved objective."},
                                     "intentional": {"severity": None, "recommendation": "Document the reason."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}},
                           guidance="Use approved objectives/constraints only; a learning-phase strategy can be intentional.")
        stated = [str(x) for x in ctx.profile.get("objectives") or []]
        if stated:
            roles = {cid: (_objective(ctx, cid) or {}).get("role") for cid in camps}
            obj.review("objective_coverage_gap", {"batch": "business_objectives"},
                       "Is every stated business objective covered by an eligible campaign, and does any uncovered "
                       "objective belong in paid media per the owner?",
                       evidence={"objectives": stated, "campaign_roles": roles,
                                 "approved_constraints": ctx.profile.get("approved_constraints")},
                       outcomes={"all_covered": {"severity": None, "recommendation": "No gap."},
                                 "owner_confirmed_gap": {"severity": "Info", "recommendation":
                                                         "Optional opportunity with prerequisites; no mandatory launch."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}},
                       guidance="An uncovered objective is an opportunity only if the owner confirms it belongs in paid media.")
        else:
            obj.partial("profile objectives list missing: coverage mapping limited", ["profile:objectives"])

    # -- step 5 (+ #112): separation rationale / consolidation candidates
    sep = ctx.check("separation_rationale", "Compatible campaigns and consolidation review",
                    {"campaigns": CAMP + ["geo_targets", "languages"], "campaign_metrics": ["campaign_id", "conversions"]})
    if sep.runnable and not objs_supplied:
        sep.skip("no approved objectives: compatibility unknown", ["profile:campaign_objectives"])
    elif sep.runnable:
        groups: dict[tuple, list[str]] = {}
        for cid, c in camps.items():
            o = _objective(ctx, cid)
            if o is None or str(c.get("status")).upper() != "ENABLED":
                continue
            key = (str(c.get("channel_type")).upper(), str(o.get("role")), tuple(sorted(map(str, o.get("goal_ids") or []))),
                   str(c.get("bidding_strategy_type")).upper(), V.norm_text(c.get("geo_targets")), V.norm_text(c.get("languages")))
            groups.setdefault(key, []).append(cid)
        mc = ctx.params.get("min_conversions")
        compat = {k: v for k, v in groups.items() if len(v) > 1}
        sep.observe("Compatible campaign groups (same channel/role/goals/strategy/geo/language)",
                    groups=[{"key": list(k), "campaigns": v} for k, v in sorted(compat.items())])
        if ctx.mature is not True:
            sep.partial(f"maturity {ctx.mature}: no performance-driven consolidation review ({ctx.maturity_note})")
        else:
            for key, ids in sorted(compat.items()):
                conv = {cid: (metrics.get(cid) or {}).get("conversions") for cid in ids}
                low = sorted(cid for cid, v in conv.items() if v is not None and v < (mc.value or 0))
                if not low:
                    continue
                sep.review("consolidation_candidate", {"campaigns": ids},
                           f"Do independent budgets, goals, markets or governance justify keeping {ids} separate?",
                           evidence={"compatibility_key": list(key), "conversions": conv, "below_min_conversions": low,
                                     "min_conversions": mc.value, "window": [ctx.period_start, ctx.period_end]},
                           outcomes={"consolidation_review": {"severity": "Info", "recommendation":
                                                              "Owner reviews a consolidation proposal with tradeoffs."},
                                     "keep_separate": {"severity": None, "recommendation": "Separation justified."},
                                     "uncertain": {"severity": "Info", "recommendation": "Collect governance evidence."}},
                           guidance="consolidation_review needs proposal.campaigns ⊆ the reviewed group (>=2). "
                                    "No claim of improved bidding signals.")

    # -- step 6: optional feature context (former Power Pack)
    feat = ctx.check("feature_context", "Optional PMax/Demand Gen/Search-feature context", {"custom/campaign_features": FEAT})
    if feat.runnable:
        by: dict[str, dict] = {}
        for r in ctx.rows("custom/campaign_features"):
            by.setdefault(str(r.get("campaign_id")), {})[str(r.get("feature_name"))] = r.get("status")
        feat.observe("Feature settings evidence (no adoption requirement)", features={k: by[k] for k in sorted(by)})
    rsa = {}
    for a in ctx.rows("ads"):
        if str(a.get("type") or "").upper() == "RESPONSIVE_SEARCH_AD" and str(a.get("status") or "").upper() == "ENABLED":
            rsa[str(a.get("campaign_id"))] = rsa.get(str(a.get("campaign_id")), 0) + 1
    if ctx.table("ads") is not None:
        ctx.check("rsa_inventory", "Enabled RSA inventory (context)", {"ads": ["campaign_id", "type", "status"]}).observe(
            "Enabled RSAs per campaign", counts=dict(sorted(rsa.items())))

    # -- step 7: routing and Shopping/PMax coexistence
    route = ctx.check("routing", "Route network/naming/brand topics; coexistence ≠ overlap",
                      {"campaigns": ["id", "channel_type", "status"]})
    if route.runnable:
        enabled = {cid: c for cid, c in camps.items() if str(c.get("status")).upper() == "ENABLED"}
        route.observe("Routed topics", network_optins_to_005_006=sorted(
            cid for cid, c in enabled.items() if V.boolean(c.get("search_partners")) or V.boolean(c.get("display_network"))),
            naming_to_003=True, brand_routing_to_002=True)
        shop = sorted(cid for cid, c in enabled.items() if str(c.get("channel_type")).upper() == "SHOPPING")
        pmax = sorted(cid for cid, c in enabled.items() if str(c.get("channel_type")).upper() == "PERFORMANCE_MAX")
        if shop and pmax:
            route.finding("product_overlap_unknown", "Info", {"campaigns": shop + pmax},
                          f"Standard Shopping {shop} and Performance Max {pmax} both enabled; product overlap unknown",
                          evidence={"shopping": shop, "pmax": pmax},
                          recommendation="Supply listing-group/product evidence before judging overlap or competition.",
                          uncertainty="Coexistence does not establish product overlap.")

    # -- step 8: business-led alternatives and prerequisites
    alt = ctx.check("alternatives_prerequisites", "Missing prerequisites before any test proposal")
    missing = [n for n, ok in (("profile:campaign_objectives", objs_supplied),
                               ("custom/campaign_features (file)", ctx.table("custom/campaign_features") is not None),
                               ("budgets (file)", ctx.table("budgets") is not None),
                               ("bidding_strategies (file)", ctx.table("bidding_strategies") is not None)) if not ok]
    if missing:
        alt.partial("alternatives limited by missing prerequisites", missing)
    alt.observe("Alternatives are tradeoff proposals; no mandatory mix, quota or adoption score", missing=missing)


def verify(ctx, item, decision) -> list[str]:
    """Rules: consolidation proposals must stay within the reviewed compatible group."""
    if item.condition_key == "consolidation_candidate" and decision.get("outcome") == "consolidation_review":
        prop = {str(x) for x in (decision.get("proposal") or {}).get("campaigns") or []}
        allowed = set(item.entity["campaigns"])
        if len(prop) < 2 or not prop <= allowed:
            return [f"proposal.campaigns must be >=2 campaigns within the reviewed group {sorted(allowed)}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
