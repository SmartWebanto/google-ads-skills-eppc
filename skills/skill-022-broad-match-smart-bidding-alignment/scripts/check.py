"""check.py — skill-022 deterministic strategy × objective × broad-match inventory and readiness gates.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-022-broad-match-smart-bidding-alignment/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Search campaigns only. Effective strategy = portfolio row (bidding_strategy_id|strategy_id or
         bidding_strategies.campaign_ids) over the campaign's bidding_strategy_type; unresolvable → Unknown.
         Classes: conversion Smart Bidding (TARGET_CPA/TARGET_ROAS/MAXIMIZE_CONVERSIONS/MAXIMIZE_CONVERSION_VALUE),
         non-conversion (MANUAL_CPC/MAXIMIZE_CLICKS/TARGET_SPEND/TARGET_IMPRESSION_SHARE/...), legacy ECPC.
         ECPC is historical evidence only: never recommend enabling it or assume current availability.
         Broad share, broad+manual and zero broad are Info/observations — never quota violations; no migration score.
         'Broad-triggered' = the matched keyword (search_terms.matched_keyword_id → keywords.id, same campaign/ad
         group) has match_type BROAD; the report's query-match column is not used for this.
         Relevance vs approved objectives is ai_review (Warning only for queries >= spend_floor of THEIR campaign,
         ctx.mature True and an approved objective); CPA differences across strategies are never causal.
         Measurement readiness = ctx.tracking_for_campaign(cid); a non-conversion campaign without True readiness
         gets Info (any conversion-optimization proposal lacks confirmed readiness). Tests are offered only for
         profile.match_type_test_needs[cid] (documented control/reach need); otherwise not applicable.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
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

SKILL = "skill-022-broad-match-smart-bidding-alignment"
VERSION = "1.0.0"

SMART = {"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"}
NON_CONVERSION = {"MANUAL_CPC", "MAXIMIZE_CLICKS", "TARGET_SPEND", "TARGET_IMPRESSION_SHARE", "MANUAL_CPM",
                  "MANUAL_CPV", "TARGET_CPM"}
KW_COLS = ["id", "campaign_id", "ad_group_id", "match_type", "status"]
ST_COLS = ["search_term", "campaign_id", "ad_group_id", "matched_keyword_id", "clicks", "cost", "conversions"]


def _objective(ctx, cid: str):
    obj = ctx.profile.get("campaign_objectives") or {}
    return next((v for k, v in obj.items() if str(k) == cid), None) if isinstance(obj, dict) else None


def _resolve(ctx, camp: dict) -> tuple[str, str | None, str, list[str]]:
    """→ (class, effective_type, source, gaps)."""
    cid = str(camp.get("id"))
    sid = camp.get("bidding_strategy_id") or camp.get("strategy_id")
    strategies = ctx.table("bidding_strategies")
    gaps = []
    row = None
    if strategies is not None:
        row = next((r for r in strategies.rows if sid and str(r.get("id")) == str(sid)), None) or next(
            (r for r in strategies.rows if cid in V.split_list(r.get("campaign_ids"), (";", "|", ","))), None)
    elif sid:
        gaps.append(f"campaign {cid}: portfolio {sid} not resolvable (bidding_strategies missing)")
    if row is not None and row.get("type"):
        typ, src = str(row.get("type")).upper(), f"bidding_strategies[{row.get('id')}]"
    else:
        typ, src = str(camp.get("bidding_strategy_type") or "").upper() or None, "campaigns.bidding_strategy_type"
    if typ is None:
        return "unknown", None, "no strategy type", gaps
    if typ == "ENHANCED_CPC" or (typ == "MANUAL_CPC" and V.boolean(camp.get("enhanced_cpc_enabled")) is True):
        return "legacy_ecpc", typ, src, gaps
    if typ in SMART:
        return "conversion_smart_bidding", typ, src, gaps
    if typ in NON_CONVERSION:
        return "non_conversion", typ, src, gaps
    return "unknown", typ, src, gaps


def run(ctx) -> None:
    """Run broad-match × effective bid-strategy alignment, query relevance and readiness checks for Search campaigns.

    Rules:   Broad share, broad+manual and zero broad are Info/observations, never quota violations; ECPC never
             recommended. Broad-triggered = matched keyword match_type BROAD via matched_keyword_id, never the
             query-match column. Relevance Warning only via ai_review for queries >= their campaign's spend_floor with
             ctx.mature True and an approved objective; sub-floor queries → Info batch review. CPA differences across
             strategies are never causal.
    """
    ws = ctx.check("window_scope", "Account, window, snapshot and maturity",
                   {"account": ["currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if ws.runnable:
        ws.observe("Scope", currency=ctx.currency, period=[ctx.period_start, ctx.period_end], snapshot=ctx.snapshot,
                   conversion_date_basis=ctx.account.get("conversion_date_basis"), mature=ctx.mature,
                   maturity_note=ctx.maturity_note)
        if ctx.mature is not True:
            ws.partial(f"conversions not mature: {ctx.maturity_note}")

    strat = ctx.check("strategy_resolution", "Effective strategy via portfolio membership",
                      {"campaigns": ["id", "channel_type", "bidding_strategy_type"]})
    later = (("non_conversion_objectives", "Non-conversion objectives with broad match"),
             ("legacy_ecpc", "Legacy ECPC as historical evidence"),
             ("broad_inventory", "Broad keyword count and spend per campaign"),
             ("broad_query_relevance", "Mature broad-triggered query relevance"),
             ("measurement_readiness", "Conversion measurement readiness"),
             ("optional_tests", "Optional pairing/match-type tests"))
    if not strat.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("campaign strategy inventory unavailable", strat.missing)
        return
    camps: dict[str, dict] = {}
    for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
        if str(c.get("channel_type") or "").upper() != "SEARCH" or str(c.get("status") or "").upper() == "REMOVED":
            continue
        cls, typ, src, gaps = _resolve(ctx, c)
        for g in gaps:
            strat.partial(g)
        obj = _objective(ctx, str(c.get("id")))
        camps[str(c.get("id"))] = {"row": c, "class": cls, "type": typ, "source": src, "objective": obj}
        strat.observe(f"Campaign {c.get('id')} effective strategy", campaign_id=str(c.get("id")), strategy_type=typ,
                      strategy_class=cls, source=src, objective=obj, status=c.get("status"))
    if ctx.table("bidding_strategies") is None:
        strat.partial("bidding_strategies not supplied: portfolio membership unverified", ["bidding_strategies (file)"])
    unknown = sorted(k for k, v in camps.items() if v["class"] == "unknown")
    if unknown:
        strat.partial(f"strategy Unknown for campaigns {unknown}")

    kw_t = ctx.table("keywords")
    kws = [k for k in (kw_t.rows if kw_t is not None and not kw_t.missing(KW_COLS) else [])
           if str(k.get("status") or "").upper() != "REMOVED"]
    broad_by_c: dict[str, list] = {}
    for k in kws:
        if str(k.get("match_type") or "").upper() == "BROAD":
            broad_by_c.setdefault(str(k.get("campaign_id")), []).append(str(k.get("id")))

    nc = ctx.check("non_conversion_objectives", "Non-conversion objectives with broad match", {"keywords": KW_COLS},
                   applicable=any(v["class"] == "non_conversion" for v in camps.values()),
                   na_reason="no Search campaign with a non-conversion strategy")
    if nc.runnable:
        for cid, c in sorted(camps.items()):
            if c["class"] != "non_conversion":
                continue
            broad = broad_by_c.get(cid, [])
            nc.observe(f"Campaign {cid}: {c['type']} objective", campaign_id=cid, objective=c["objective"],
                       broad_keywords=len(broad))
            if broad:
                nc.finding("broad_with_non_conversion_strategy", "Info", {"campaign_id": cid},
                           f"Campaign {cid} runs {len(broad)} broad keyword(s) under {c['type']}",
                           evidence={"strategy_type": c["type"], "strategy_source": c["source"],
                                     "broad_keyword_ids": sorted(broad), "objective": c["objective"]},
                           recommendation="Confirm the control/reach intent; this combination alone is not a defect.",
                           uncertainty="Non-conversion objectives are legitimate; no migration implied.")

    ecpc = [k for k, v in camps.items() if v["class"] == "legacy_ecpc"]
    ec = ctx.check("legacy_ecpc", "Legacy ECPC as historical evidence", {"campaigns": ["id", "bidding_strategy_type"]},
                   applicable=bool(ecpc), na_reason="no ECPC evidence in the export")
    if ec.runnable:
        for cid in ecpc:
            c = camps[cid]
            ec.observe(f"Campaign {cid} ECPC recorded as historical evidence", campaign_id=cid,
                       recorded_at=ctx.snapshot, channel=c["row"].get("channel_type"), strategy_type=c["type"],
                       control_status=c["row"].get("enhanced_cpc_enabled"),
                       note="no recommendation to enable ECPC; current availability not assumed")

    inv = ctx.check("broad_inventory", "Broad keyword count and spend per campaign",
                    {"keywords": KW_COLS, "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "cost"]})
    if inv.runnable:
        cost: dict[tuple, float | None] = {}
        dup = set()
        for m in ctx.rows("keyword_metrics"):
            key = (str(m.get("campaign_id")), str(m.get("ad_group_id")), str(m.get("keyword_id")))
            if key in cost:
                dup.add(key)
            cost[key] = ctx.money(m.get("cost"))
        if dup:
            inv.partial(f"{len(dup)} keywords with several metric rows (segments?) excluded from spend shares")
        for cid, c in sorted(camps.items()):
            ck = [k for k in kws if str(k.get("campaign_id")) == cid]
            if not ck:
                continue
            total = broad = 0.0
            unknown_cost = 0
            for k in ck:
                key = (cid, str(k.get("ad_group_id")), str(k.get("id")))
                v = cost.get(key)
                if key in dup or v is None:
                    unknown_cost += 1
                    continue
                total += v
                if str(k.get("match_type") or "").upper() == "BROAD":
                    broad += v
            nb = len(broad_by_c.get(cid, []))
            inv.observe(f"Campaign {cid} strategy × objective × match inventory", campaign_id=cid,
                        strategy_class=c["class"], strategy_type=c["type"], objective=c["objective"],
                        keywords=len(ck), broad_keywords=nb, broad_count_share=V.ratio(nb, len(ck)),
                        keyword_cost=total, broad_cost=broad, broad_cost_share=V.ratio(broad, total),
                        keywords_without_cost=unknown_cost, currency=ctx.currency,
                        window=[ctx.period_start, ctx.period_end],
                        note="distribution belongs to skill-012; no quota applies")

    rel = ctx.check("broad_query_relevance", "Mature broad-triggered query relevance",
                    {"search_terms": ST_COLS, "keywords": KW_COLS})
    if rel.runnable:
        if ctx.mature is not True:
            rel.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): relevance vs outcomes not prescribed")
        else:
            kmap = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in kws}
            sub, unresolved, no_obj, unjoined = [], set(), set(), 0
            for r in sorted(ctx.rows("search_terms"), key=lambda r: (str(r.get("campaign_id")), str(r.get("search_term")))):
                cid = str(r.get("campaign_id"))
                if cid not in camps:
                    continue
                k = kmap.get((cid, str(r.get("ad_group_id")), str(r.get("matched_keyword_id"))))
                if k is None:
                    unjoined += 1
                    continue
                if str(k.get("match_type") or "").upper() != "BROAD":
                    continue
                c_cost, conv = ctx.money(r.get("cost")), V.num(r.get("conversions"))
                if c_cost is None:
                    continue
                floor = ctx.params.get("spend_floor", cid)
                if floor.value is None:
                    unresolved.add(f"{cid}: {floor.reason}")
                    continue
                objective = camps[cid]["objective"] or ctx.profile.get("objectives")
                q = str(r.get("search_term"))
                ev = {"keyword_id": str(k.get("id")), "keyword_text": k.get("text"), "clicks": V.num(r.get("clicks")),
                      "cost": c_cost, "conversions": conv, "spend_floor": floor.value, "spend_floor_source": floor.source,
                      "strategy_class": camps[cid]["class"], "objective": objective,
                      "excluded_intents": ctx.profile.get("excluded_intents"),
                      "window": [ctx.period_start, ctx.period_end]}
                if c_cost < floor.value:
                    sub.append({"search_term": q, "campaign_id": cid, "keyword_id": str(k.get("id")), "cost": c_cost,
                                "conversions": conv})
                    continue
                outcomes = {"consistent": {"severity": None, "recommendation": "Keep; broad reach serves the objective."},
                            "uncertain": {"severity": "Info", "recommendation": "Clarify the approved objective."}}
                if objective:
                    outcomes["contradicts_objective"] = {"severity": "Warning", "recommendation":
                                                         "Review keyword/negative scope (skill-014) and targeting; "
                                                         "no automatic migration."}
                else:
                    no_obj.add(cid)
                rel.review("broad_query_contradicts_objective",
                           {"campaign_id": cid, "ad_group_id": str(r.get("ad_group_id")), "search_term": q},
                           f"Does broad-triggered query '{q}' (keyword '{k.get('text')}') contradict the approved "
                           f"relevance/objective of campaign {cid}?",
                           evidence=ev, outcomes=outcomes,
                           guidance="Judge against approved objectives/excluded intents only; CPA differences across "
                                    "strategies are confounded, not causal.")
            if sub:
                rel.review("broad_sub_floor_relevance", {"batch": "sub_floor_broad_queries"},
                           "Do any of these below-floor broad-triggered queries contradict approved objectives?",
                           evidence={"queries": sub, "excluded_intents": ctx.profile.get("excluded_intents")},
                           outcomes={"some_contradict": {"severity": "Info", "recommendation":
                                                         "Optional hygiene; exposure below materiality."},
                                     "none_contradict": {"severity": None, "recommendation": "No action."}})
            for u in sorted(unresolved):
                rel.partial(f"spend_floor unresolved for campaign {u}")
            for cid in sorted(no_obj):
                rel.partial(f"campaign {cid}: no approved objective; Warning outcome withheld",
                            ["profile:campaign_objectives"])
            if unjoined:
                rel.partial(f"{unjoined} query rows not joined to a keyword by matched_keyword_id")

    mr = ctx.check("measurement_readiness", "Conversion measurement readiness",
                   {"conversion_actions": ["id", "status"]})
    if mr.runnable:
        for cid, c in sorted(camps.items()):
            state, note = ctx.tracking_for_campaign(cid)
            mr.observe(f"Campaign {cid} measurement readiness", campaign_id=cid, strategy_class=c["class"],
                       readiness=state, note=note, goal_ids=ctx.goal_ids(cid))
            if state is None:
                mr.partial(f"readiness unknown: {note}")
            if c["class"] in ("non_conversion", "legacy_ecpc") and state is not True:
                mr.finding("conversion_optimization_readiness_unconfirmed", "Info", {"campaign_id": cid},
                           f"Campaign {cid} ({c['type']}): measurement readiness not confirmed for any conversion-"
                           f"optimization trial",
                           evidence={"readiness": state, "tracking_note": note, "goal_ids": ctx.goal_ids(cid)},
                           recommendation="Fix/verify goal tracking before proposing Smart Bidding; no trial implied.",
                           uncertainty="Readiness evidence is goal-specific; account-wide conversions are not proof.")

    needs = ctx.profile.get("match_type_test_needs") or {}
    ot = ctx.check("optional_tests", "Optional pairing/match-type tests",
                   applicable=bool(needs), na_reason="no documented control/reach need (profile.match_type_test_needs)")
    if ot.runnable:
        for cid, need in sorted(((str(k), v) for k, v in needs.items())):
            if cid not in camps:
                ot.partial(f"match_type_test_needs names unknown Search campaign {cid}")
                continue
            state, note = ctx.tracking_for_campaign(cid)
            ot.observe(f"Campaign {cid} optional test prerequisites", campaign_id=cid, documented_need=need,
                       strategy_class=camps[cid]["class"], mature=ctx.mature, readiness=state,
                       broad_keywords=len(broad_by_c.get(cid, [])),
                       prerequisites_met=ctx.mature is True and state is True,
                       note="controlled design via skill-032; no efficiency promise")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
