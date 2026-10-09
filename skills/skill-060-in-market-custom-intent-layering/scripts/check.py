"""check.py — skill-060 deterministic in-market/custom segment inventory, descriptive metrics and exclusive-cohort tests.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-060-in-market-custom-intent-layering/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #23 Automate your in-market audience bidding (Brainlabs) and #24 Automatically apply modifiers to
         in-market audiences based on performance (Brainlabs) — clean-room reimplementation of "segment CPA vs
         campaign CPA → bid modifier": the campaign ratio is kept as a labelled NON-INDEPENDENT descriptive context
         only; modifier values are proposed solely from supplied mutually exclusive cohorts, Manual CPC campaigns,
         capped 0.9–1.1 × current modifier, and re-checked by verify(). Auto-adding audiences is not reproduced.
rules:   Associations: audiences with list_id|audience_id, campaign_id, ad_group_id, mode, type (alt audience_type).
         Type classes: IN_MARKET, AFFINITY, CUSTOM (CUSTOM_*), FIRST_PARTY, OTHER; PERFORMANCE_MAX/DEMAND_GEN → signal.
         Segment reports overlap: segment costs are never summed into audience spend or subtracted from campaign cost.
         Campaign CPA baseline includes the audience → descriptive context only, never a control, no severity.
         Severity only from custom/audience_exclusive_cohorts rows with overlap_resolved=true, compared per
         (campaign, ad group) cohort vs the union of its other cohorts; needs ctx.mature True and >= min_conversions
         on BOTH sides. CPA ratio > 1.5 or ROAS ratio < 0.7 → Warning; CPA ratio < 0.7 → Info.
         Relevance/intent contradictions and optional segment suggestions are ai_review only (profile intent).
         Modifier proposals: MANUAL_CPC only; raw = complement CPA / cohort CPA; proposal within [0.9, 1.1] × current
         audiences.bid_modifier (a multiplier, 1.0 = none; unknown current → rejected) and platform range 0.1..10.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial deterministic check
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

SKILL = "skill-060-in-market-custom-intent-layering"
VERSION = "1.0.0"

PERF = "custom/audience_segment_performance"
DEFS = "custom/custom_segment_definitions"
COH = "custom/audience_exclusive_cohorts"
SIGNAL_CHANNELS = ("PERFORMANCE_MAX", "DEMAND_GEN")
FIRST_PARTY = ("REMARKETING", "CUSTOMER_MATCH", "CRM_BASED", "USER_LIST", "RULE_BASED", "LOGICAL", "SIMILAR",
               "WEBSITE_VISITORS", "YOUTUBE_USERS", "APP_USERS", "COMBINED")
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def _up(v) -> str:
    return str(v or "").strip().upper().replace(" ", "_").replace("-", "_")


def _klass(t) -> str:
    t = _up(t)
    if "IN_MARKET" in t:
        return "IN_MARKET"
    if t.startswith("CUSTOM") and t not in ("CUSTOMER_MATCH",):
        return "CUSTOM"
    if "AFFINITY" in t:
        return "AFFINITY"
    return "FIRST_PARTY" if t in FIRST_PARTY else "OTHER"


def _mode(r) -> str:
    m = _up(r.get("mode"))
    if m in ("EXCLUSION", "EXCLUDE") or V.boolean(r.get("exclusion")) is True:
        return "EXCLUSION"
    return {"TARGETING": "TARGETING", "OBSERVATION": "OBSERVATION", "BID_ONLY": "OBSERVATION",
            "SIGNAL": "SIGNAL"}.get(m, "UNKNOWN")


def _cols(ctx) -> tuple[str, str]:
    t = ctx.table("audiences")
    cols = t.columns if t is not None else []
    lc = "audience_id" if "list_id" not in cols and "audience_id" in cols else "list_id"
    tc = "audience_type" if "type" not in cols and "audience_type" in cols else "type"
    return lc, tc


def _add(acc: dict, r, ctx) -> None:
    for m in METRICS:
        v = ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))
        if v is None:
            acc.setdefault("unknown", set()).add(m)
        else:
            acc[m] = acc.get(m, 0.0) + v


def _campaign_row(ctx, cid) -> dict:
    return next((r for r in ctx.rows("campaigns") if str(r.get("id")) == str(cid)), {})


def run(ctx) -> None:
    """Run audience inventory, segment overlap, exclusive-cohort, relevance review and modifier checks.

    Rules:   Segment costs are never summed; campaign CPA baseline is context without severity. Severity only from
             overlap_resolved exclusive cohorts with ctx.mature and >= min_conversions on BOTH sides: CPA ratio > 1.5 or
             ROAS ratio < 0.7 → Warning, CPA ratio < 0.7 → Info. Relevance contradictions are ai_review only. No
             exclusive cohort evidence → no bid proposal; modifiers only under MANUAL_CPC within [0.9, 1.1] × current.
    """
    lc, tc = _cols(ctx)
    inv = ctx.check("segment_inventory", "Campaign inventory × segment associations and mechanism",
                    {"campaigns": ["id", "status", "channel_type"], "audiences": [lc, "campaign_id", "ad_group_id", "mode", tc]})
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns") if _up(r.get("status")) in ("ENABLED", "PAUSED")}
    assoc: dict = {}
    if inv.runnable:
        seen = set()
        for r in ctx.rows("audiences"):
            cid = str(r.get("campaign_id") or "")
            if cid not in camps or _up(r.get("status")) not in ("ENABLED", "ACTIVE", ""):
                continue
            key = (str(r.get(lc)), cid, str(r.get("ad_group_id") or ""), _mode(r))
            if key in seen:
                continue
            seen.add(key)
            signal = _up(camps[cid].get("channel_type")) in SIGNAL_CHANNELS
            assoc.setdefault(cid, []).append({"audience_id": key[0], "ad_group_id": key[2] or None,
                                              "class": _klass(r.get(tc)), "mode": "SIGNAL" if signal else key[3],
                                              "bid_modifier": r.get("bid_modifier")})
        defs = ctx.table(DEFS)
        defined = {str(r.get("segment_id")) for r in (defs.rows if defs else [])}
        custom_ids = sorted({a["audience_id"] for al in assoc.values() for a in al if a["class"] == "CUSTOM"})
        undefined = [s for s in custom_ids if s not in defined]
        if undefined:
            inv.partial(f"custom segment definitions missing for {undefined}: relevance unknown",
                        [f"{DEFS} (file)"] if defs is None else [])
        inv.observe("Segment inventory", campaigns=len(camps),
                    by_campaign={c: sorted({(a["class"], a["mode"]) for a in assoc.get(c, [])}) for c in sorted(camps)},
                    without_in_market_or_custom=sorted(c for c in camps if not any(
                        a["class"] in ("IN_MARKET", "CUSTOM") for a in assoc.get(c, []))),
                    input_semantics="custom keyword/URL/app inputs describe interests, not exact searches by every member")

    # -- steps 2-3: overlap + descriptive metrics
    ov = ctx.check("overlap", "Non-additive segment overlap", {PERF: ["campaign_id", "audience_id", "cost"],
                                                               "campaign_metrics": ["campaign_id", "cost"]})
    if ov.runnable:
        seg_cost: dict = {}
        for r in ctx.rows(PERF):
            c = ctx.money(r.get("cost"))
            if c is not None:
                seg_cost[str(r.get("campaign_id"))] = seg_cost.get(str(r.get("campaign_id")), 0.0) + c
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid in seg_cost:
                ov.observe(f"Campaign {cid}: segment rows overlap (sum is not audience spend)", campaign_id=cid,
                           sum_of_segment_rows=seg_cost[cid], campaign_cost=ctx.money(m.get("cost")),
                           ratio=V.ratio(seg_cost[cid], ctx.money(m.get("cost"))))
    dm = ctx.check("descriptive_metrics", "Segment CPA/ROAS (contextual, non-independent)",
                   {PERF: ["campaign_id", "ad_group_id", "audience_id", "criterion_id", "date", "mode", *METRICS,
                           "audience_type", "reporting_completeness"]})
    if dm.runnable:
        incomplete = sorted({str(r.get("campaign_id")) for r in ctx.rows(PERF)
                             if "complete" not in str(r.get("reporting_completeness") or "").lower()
                             or "incomplete" in str(r.get("reporting_completeness") or "").lower()})
        if incomplete:
            dm.partial(f"segment rows not marked complete for campaigns {incomplete}")
        segs: dict = {}
        for r in ctx.rows(PERF):
            _add(segs.setdefault((str(r.get("campaign_id")), str(r.get("audience_id")), _up(r.get("mode"))), {}), r, ctx)
        cm = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
        for key in sorted(segs):
            s = segs[key]
            base = cm.get(key[0]) or {}
            camp_cpa = V.ratio(ctx.money(base.get("cost")), V.num(base.get("conversions")))
            cpa = V.ratio(s.get("cost"), s.get("conversions"))
            dm.observe(f"Campaign {key[0]} segment {key[1]} ({key[2]}): descriptive", campaign_id=key[0],
                       audience_id=key[1], mode=key[2], cost=s.get("cost"), conversions=s.get("conversions"),
                       cpa=cpa, roas=V.ratio(s.get("conversion_value"), s.get("cost")),
                       cvr=V.ratio(s.get("conversions"), s.get("clicks")), campaign_cpa_context=camp_cpa,
                       cpa_vs_campaign_context=V.ratio(cpa, camp_cpa), unknown=sorted(s.get("unknown", ())),
                       label="contextual non-independent comparison (campaign includes the segment)")

    # -- steps 4-5: exclusive cohorts
    ex = ctx.check("exclusive_comparison", "Mutually exclusive cohort comparison",
                   {COH: ["campaign_id", "ad_group_id", "cohort_id", "definition", "date", *METRICS,
                          "assignment_method", "overlap_resolved"]})
    comparisons = []
    if ex.runnable:
        mature_ok = ctx.mature is True
        if not mature_ok:
            ex.partial(f"conversion maturity not established ({ctx.maturity_note}); no comparative severity")
        mc = ctx.params.get("min_conversions")
        groups: dict = {}
        for r in ctx.rows(COH):
            g = groups.setdefault((str(r.get("campaign_id")), str(r.get("ad_group_id") or "")), {})
            c = g.setdefault(str(r.get("cohort_id")), {"definition": r.get("definition"),
                                                       "assignment_method": r.get("assignment_method"),
                                                       "resolved": set()})
            c["resolved"].add(V.boolean(r.get("overlap_resolved")))
            _add(c, r, ctx)
        for gkey in sorted(groups):
            cohorts = groups[gkey]
            if len(cohorts) < 2 or any(c["resolved"] != {True} for c in cohorts.values()):
                ex.partial(f"campaign {gkey[0]} ad group {gkey[1] or '-'}: <2 cohorts or overlap not resolved; skipped")
                continue
            for cid in sorted(cohorts):
                c = cohorts[cid]
                rest = {m: sum(o.get(m, 0.0) for k, o in cohorts.items() if k != cid) for m in METRICS}
                rest_unknown = set().union(*(o.get("unknown", set()) for k, o in cohorts.items() if k != cid))
                cpa, rcpa = V.ratio(c.get("cost"), c.get("conversions")), V.ratio(rest["cost"], rest["conversions"])
                roas = V.ratio(c.get("conversion_value"), c.get("cost"))
                rroas = V.ratio(rest["conversion_value"], rest["cost"])
                cpa_ratio = V.ratio(cpa, rcpa)
                roas_ratio = V.ratio(roas, rroas) if "conversion_value" not in c.get("unknown", set()) | rest_unknown else None
                gated = mature_ok and (c.get("conversions") or 0) >= mc.value and rest["conversions"] >= mc.value \
                    and not ({"cost", "conversions"} & (c.get("unknown", set()) | rest_unknown))
                data = {"campaign_id": gkey[0], "ad_group_id": gkey[1] or None, "cohort_id": cid,
                        "definition": c["definition"], "assignment_method": c["assignment_method"],
                        "cohort": {m: c.get(m) for m in METRICS}, "complement": rest, "cpa": cpa, "complement_cpa": rcpa,
                        "cpa_ratio": cpa_ratio, "roas_ratio": roas_ratio, "min_conversions": mc.value,
                        "window": [ctx.period_start, ctx.period_end]}
                ex.observe(f"Cohort {cid} vs complement in campaign {gkey[0]}", gated=gated, **data)
                if not gated:
                    continue
                entity = {"campaign_id": gkey[0], "ad_group_id": gkey[1] or None, "cohort_id": cid}
                calc = {"cpa_ratio": cpa_ratio, "roas_ratio": roas_ratio, "min_conversions": mc.value,
                        "min_conversions_source": mc.source}
                adverse = (cpa_ratio is not None and cpa_ratio > 1.5) or (roas_ratio is not None and roas_ratio < 0.7)
                if adverse:
                    ex.finding("adverse_exclusive_cohort", "Warning", entity,
                               f"Cohort {cid} ('{c['definition']}') CPA ratio {cpa_ratio} / ROAS ratio {roas_ratio} "
                               f"vs its exclusive complement",
                               evidence=data, calculation=calc,
                               recommendation="Review targeting/creative for this cohort; a bid test needs owner review.",
                               uncertainty="Observational cohorts differ by intent; not incremental lift.")
                elif cpa_ratio is not None and cpa_ratio < 0.7:
                    ex.finding("opportunity_exclusive_cohort", "Info", entity,
                               f"Cohort {cid} ('{c['definition']}') CPA ratio {cpa_ratio} vs its exclusive complement",
                               evidence=data, calculation=calc,
                               recommendation="Opportunity hypothesis; not automatic bid scaling.",
                               uncertainty="Observational; requires a controlled test for lift.")
                else:
                    continue
                comparisons.append((entity, data))

    # -- step 6: relevance/intent (AI)
    ir = ctx.check("intent_relevance", "Segment relevance vs documented business intent")
    intent = {k: ctx.profile.get(k) for k in ("business_type", "objectives", "excluded_intents", "competitor_terms")}
    if not inv.runnable:
        ir.skip("segment inventory unavailable", inv.missing)
    elif not (intent["business_type"] or intent["objectives"]):
        ir.partial("profile business_type/objectives missing: relevance not reviewable")
    else:
        defs_by = {}
        for r in ctx.rows(DEFS):
            defs_by.setdefault(str(r.get("segment_id")), []).append(
                {k: r.get(k) for k in ("input_type", "input_value", "interpretation", "channel_support")})
        for cid in sorted(assoc):
            for a in sorted(assoc[cid], key=lambda a: (a["audience_id"], str(a["ad_group_id"]))):
                if a["class"] not in ("IN_MARKET", "CUSTOM") or a["mode"] == "EXCLUSION":
                    continue
                if a["class"] == "CUSTOM" and a["audience_id"] not in defs_by:
                    continue
                entity = {"campaign_id": cid, "ad_group_id": a["ad_group_id"], "audience_id": a["audience_id"]}
                ir.review("segment_use_contradicts_intent", entity,
                          f"Does {a['class']} segment {a['audience_id']} used as {a['mode']} in campaign {cid} contradict "
                          "the documented business intent?",
                          evidence={**intent, "mode": a["mode"], "definition": defs_by.get(a["audience_id"]),
                                    "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(cid)},
                          outcomes={"contradicts_intent": {"severity": "Warning", "recommendation":
                                                           "Propose removal/mode change for owner review."},
                                    "consistent": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}},
                          guidance="Judge only against profile intent; input keywords are interests, not searches.")
        missing = sorted(c for c in camps if _up(camps[c].get("channel_type")) not in SIGNAL_CHANNELS and not any(
            a["class"] in ("IN_MARKET", "CUSTOM") for a in assoc.get(c, [])))
        if missing:
            ir.review("optional_segment_not_used", {"batch": "campaigns_without_segments"},
                      "Is there an optional, relevant, eligible in-market or custom segment worth observing for these "
                      "campaigns given the documented intent?",
                      evidence={**intent, "campaign_ids": missing},
                      outcomes={"optional_segment_suggested": {"severity": "Info", "recommendation":
                                                               "Suggest as optional Observation with a measurement question."},
                                "none_needed": {"severity": None, "recommendation": "No action; absence is not a defect."}},
                      guidance="Absence of in-market/competitor segments is not an issue; suggest only from explicit intent.")

    # -- step 7: bounded modifier tests
    mt = ctx.check("modifier_tests", "Bounded Manual CPC modifier test proposals", {"campaigns": ["bidding_strategy_type"]})
    if mt.runnable:
        if not ex.runnable:
            mt.skip("no exclusive cohort evidence: no bid value proposed", ex.missing)
    if mt.runnable:
        smart = []
        for entity, data in comparisons:
            if _up(_campaign_row(ctx, entity["campaign_id"]).get("bidding_strategy_type")) != "MANUAL_CPC":
                smart.append(entity["campaign_id"])
                continue
            raw = V.ratio(data["complement_cpa"], data["cpa"])
            capped = None if raw is None else min(1.1, max(0.9, raw))
            mt.review("bounded_modifier_test", entity,
                      f"Which audience criterion in campaign {entity['campaign_id']} corresponds to cohort "
                      f"{entity['cohort_id']} ('{data['definition']}'), and should a bounded test be proposed?",
                      evidence={**data, "raw_multiplier": raw, "capped_factor": capped,
                                "associations": assoc.get(entity["campaign_id"], [])},
                      outcomes={"propose_bounded_test": {"severity": None, "recommendation":
                                                         "Owner-reviewed test at the verified multiplier."},
                                "no_test": {"severity": None, "recommendation": "No bid value proposed."}},
                      guidance="proposal {audience_id, campaign_id, multiplier}; multiplier = current modifier × "
                               "capped_factor, within 0.9–1.1 × current. Record overlap with other modifiers.")
        mt.observe("Modifier test applicability", non_manual_cpc_campaigns=sorted(set(smart)),
                   candidates=len(comparisons) - len(smart))


def verify(ctx, item, decision) -> list[str]:
    """Rules: bounded modifier proposals are re-checked against strategy, association and the 0.9–1.1 cap."""
    if item.condition_key != "bounded_modifier_test" or decision.get("outcome") != "propose_bounded_test":
        return []
    p = decision.get("proposal") or {}
    cid, aid, mult = str(p.get("campaign_id") or ""), str(p.get("audience_id") or ""), V.num(p.get("multiplier"))
    problems = []
    if cid != item.entity["campaign_id"]:
        problems.append(f"proposal.campaign_id must be {item.entity['campaign_id']}")
    if _up(_campaign_row(ctx, cid).get("bidding_strategy_type")) != "MANUAL_CPC":
        problems.append("modifier tests only for MANUAL_CPC campaigns")
    lc, _ = _cols(ctx)
    rows = [r for r in ctx.rows("audiences") if str(r.get("campaign_id")) == cid and str(r.get(lc)) == aid
            and _mode(r) in ("OBSERVATION", "TARGETING")]
    if not rows:
        return problems + [f"audience {aid} is not a positive association of campaign {cid}"]
    current = V.num(rows[0].get("bid_modifier"))
    if current is None or current <= 0:
        return problems + ["current bid_modifier unknown: no bounded value can be verified"]
    if mult is None:
        return problems + ["proposal.multiplier required"]
    lo, hi = round(0.9 * current, 6), round(1.1 * current, 6)
    if not (lo <= mult <= hi) or not (0.1 <= mult <= 10):
        problems.append(f"multiplier {mult} outside [{lo}, {hi}] (0.9–1.1 × current {current}) or platform range")
    raw = item.evidence.get("raw_multiplier")
    if raw is not None and ((raw > 1 and mult < current) or (raw < 1 and mult > current)):
        problems.append("multiplier direction contradicts the exclusive-cohort evidence")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
