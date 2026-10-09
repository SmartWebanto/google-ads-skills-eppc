"""check.py — skill-058 deterministic age/gender/income efficiency with bounded Manual CPC modifier tests.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-058-demographic-performance-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #27 Gender Bid Adjustment Suggestions (nilsrooijmans.com) — clean-room reimplementation of
         "segment CPA vs total CPA → suggested adjustment" generalized to age/gender/income: efficiency =
         conversion share / cost share vs the rest of the same campaign, both sides sample-gated, and the suggestion
         becomes a bounded 0.9–1.1 × current multiplier only for supported exported Manual CPC controls.
rules:   Dimensions stay separate (custom/demographic_age|gender|income); never summed across dimensions. A missing
         file blocks only that dimension. Rows outside the account period are excluded.
         Efficiency = (segment conv / campaign conv) / (segment cost / campaign cost) within ONE dimension table and
         campaign; requires ctx.mature True, positive campaign conv/cost, and segment AND rest each >= min_conversions
         and >= min_clicks. <0.7 → Warning, >1.3 → Info (non-Unknown segments only).
         Unknown/undetermined segments are their own observed segment: at most Info, never an exclusion proposal.
         Zero-conversion path: conv == 0, cost >= spend_floor (campaign), mature and ctx.tracking_for_campaign True →
         ai_review (Warning outcome) with provisional Info; otherwise partial with the tracking note.
         profile.policy_sensitive_categories (list) non-empty → Info policy finding and NO modifier proposals.
         Modifier proposals need custom/demographic_controls supported=true, positive current_value, MANUAL_CPC and
         conv > 0: proposed = clamp(efficiency, 0.9, 1.1) × current, clamped to [permitted_min, permitted_max].
         Smart Bidding campaigns never receive ordinary demographic modifier proposals.
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

SKILL = "skill-058-demographic-performance-analysis"
VERSION = "1.0.0"

DIMS = ("age", "gender", "income")
COLS = ["campaign_id", "ad_group_id", "criterion_id", "date", "segment_value", "impressions", "clicks", "cost",
        "conversions", "conversion_value", "reporting_completeness"]
CONTROLS = "custom/demographic_controls"
CONTROL_COLS = ["campaign_id", "ad_group_id", "dimension", "segment", "criterion_id", "control_type", "current_value",
                "permitted_min", "permitted_max", "supported"]
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
LOW, HIGH = 0.7, 1.3


def _up(v) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def _unknown(seg) -> bool:
    s = _up(seg)
    return "UNKNOWN" in s or "UNDETERMINED" in s


def _key(d) -> str:
    return f"custom/demographic_{d}"


def _missing(ctx, key, cols) -> list[str]:
    t = ctx.table(key)
    return [f"{key} (file)"] if t is None else [f"{key}:{c}" for c in t.missing(cols)]


def _aggregate(ctx, dim) -> tuple[dict, list[str]]:
    """{campaign_id: {segment: metrics}} for one dimension; notes about excluded/withheld rows."""
    out, notes, outside, withheld, incomplete = {}, [], 0, 0, set()
    for r in ctx.rows(_key(dim)):
        d = V.parse_date(r.get("date"))
        if d is None or (ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end):
            outside += 1
            continue
        comp = str(r.get("reporting_completeness") or "").lower()
        if "complete" not in comp or "incomplete" in comp:
            incomplete.add(str(r.get("campaign_id")))
        seg = out.setdefault(str(r.get("campaign_id")), {}).setdefault(str(r.get("segment_value")), {m: 0.0 for m in METRICS})
        for m in METRICS:
            v = ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))
            if v is None:
                withheld += 1
                seg.setdefault("unknown", set()).add(m)
            else:
                seg[m] += v
    if outside:
        notes.append(f"{dim}: {outside} rows outside the account period or undated excluded")
    if withheld:
        notes.append(f"{dim}: {withheld} withheld/unknown metric cells kept as unknown")
    if incomplete:
        notes.append(f"{dim}: reporting_completeness not complete for campaigns {sorted(incomplete)}")
    return out, notes


def _strategy(ctx, cid) -> str:
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == str(cid)), {})
    return _up(row.get("bidding_strategy_type"))


def run(ctx) -> None:
    """Run per-dimension demographic reconciliation, efficiency, unknown-segment and modifier-proposal checks.

    Rules:   Age/gender/income never mixed; efficiency needs ctx.mature True and segment AND rest >=
             min_conversions/min_clicks: < 0.7 → Warning, > 1.3 → Info; Unknown segments at most Info. Zero-conversion
             segments (cost >= spend_floor, mature, tracking True) → provisional Info + ai_review, else partial.
             policy_sensitive_categories → Info and no proposals; modifier proposals only for MANUAL_CPC with supported
             controls, never Smart Bidding.
    """
    el = ctx.check("eligibility", "Channel/market and policy eligibility", {"campaigns": ["id", "status", "channel_type"]})
    sensitive = [c for c in (ctx.profile.get("policy_sensitive_categories") or []) if c]
    available = {d: not _missing(ctx, _key(d), COLS) for d in DIMS}
    if el.runnable:
        controls = ctx.rows(CONTROLS)
        income_support = sorted({str(r.get("market")) + ":" + str(V.boolean(r.get("supported")))
                                 for r in controls if _up(r.get("dimension")) == "INCOME"})
        el.observe("Dimension availability and support", reports=available, income_support=income_support or None,
                   markets=ctx.profile.get("market"), note="no income report does not mean income targeting is off")
        if sensitive:
            el.finding("policy_uncertainty", "Info", {"account_id": ctx.account_id},
                       "Declared sensitive/restricted categories: demographic restriction and modifier proposals withheld",
                       evidence={"policy_sensitive_categories": sensitive},
                       recommendation="Specialist/owner policy review before any demographic targeting proposal.",
                       uncertainty="Reported segments are not permission to target.")

    # -- step 2: reconciliation
    rc = ctx.check("reconcile", "Per-dimension reconciliation to campaign totals",
                   {"campaign_metrics": ["campaign_id", "cost", "clicks", "conversions"]})
    data: dict = {}
    for d in DIMS:
        if not available[d]:
            rc.partial(f"{d} report unavailable: that dimension is not analysed", _missing(ctx, _key(d), COLS))
            continue
        data[d], notes = _aggregate(ctx, d)
        for n in notes:
            rc.partial(n)
    if not data:
        rc.skip("no demographic report supplied")
    if rc.runnable:
        cm = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
        for d in sorted(data):
            for cid in sorted(data[d]):
                segs = data[d][cid]
                cost = sum(s["cost"] for s in segs.values())
                unk = sum(s["cost"] for k, s in segs.items() if _unknown(k))
                camp_cost = ctx.money((cm.get(cid) or {}).get("cost"))
                rc.observe(f"{d} × campaign {cid}: reconciliation", dimension=d, campaign_id=cid, dimension_cost=cost,
                           campaign_cost=camp_cost, coverage=V.ratio(cost, camp_cost), unknown_cost_share=V.ratio(unk, cost),
                           segments=sorted(segs))

    # -- steps 3-4 (+ zero-conversion path)
    ef = ctx.check("efficiency", "Segment efficiency vs rest of campaign (per dimension)")
    results: list = []
    if not data:
        ef.skip("no demographic report supplied", [m for d in DIMS for m in _missing(ctx, _key(d), COLS)])
    else:
        mature = ctx.mature is True
        if not mature:
            ef.partial(f"conversion maturity not established ({ctx.maturity_note}); descriptive only")
        mc, mk = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
        sparse, tracking_notes = [], set()  # tracking_notes: partial reasons
        for d in sorted(data):
            comparisons = sum(len(v) for v in data[d].values())
            for cid in sorted(data[d]):
                segs = data[d][cid]
                if any(x.get("unknown", set()) & {"cost", "clicks", "conversions"} for x in segs.values()):
                    tracking_notes.add(f"{d} × campaign {cid}: withheld cost/clicks/conversions; campaign totals unknown")
                    continue
                tot = {m: sum(s[m] for s in segs.values()) for m in METRICS}
                for seg in sorted(segs):
                    s = segs[seg]
                    rest = {m: tot[m] - s[m] for m in METRICS}
                    eff = V.ratio(V.ratio(s["conversions"], tot["conversions"]), V.ratio(s["cost"], tot["cost"])) \
                        if tot["conversions"] > 0 and tot["cost"] > 0 and s["cost"] > 0 else None
                    entity = {"campaign_id": cid, "dimension": d, "segment": seg}
                    ev = {"segment": {m: s[m] for m in METRICS}, "rest": rest, "efficiency": eff,
                          "cpa": V.ratio(s["cost"], s["conversions"]), "rest_cpa": V.ratio(rest["cost"], rest["conversions"]),
                          "roas": V.ratio(s["conversion_value"], s["cost"]), "cvr": V.ratio(s["conversions"], s["clicks"]),
                          "window": [ctx.period_start, ctx.period_end], "comparisons_in_dimension": comparisons,
                          "unknown_cells": sorted(s.get("unknown", ()))}
                    if s["conversions"] == 0 and not _unknown(seg):
                        floor = ctx.params.get("spend_floor", cid)
                        track, note = ctx.tracking_for_campaign(cid)
                        if floor.value is None:
                            tracking_notes.add(f"spend_floor for {cid}: {floor.reason}")
                        elif s["cost"] >= floor.value:
                            if not (mature and track is True):
                                tracking_notes.add(f"campaign {cid}: zero-conversion path blocked (mature={ctx.mature}; {note})")
                            else:
                                prov = ef.finding("zero_conversion_segment", "Info", entity,
                                                  f"{d} segment {seg} spent {s['cost']:.2f} {ctx.currency} with 0 conversions "
                                                  f"(spend_floor {floor.value:g})",
                                                  evidence={**ev, "tracking": note, "spend_floor_source": floor.source},
                                                  recommendation="Investigate relevance/measurement; not an automatic exclusion.",
                                                  uncertainty="Lag, long cycles or inference error can explain zero conversions.")
                                ef.review("zero_conversion_segment", entity,
                                          f"Is the zero-conversion {d} segment {seg} in campaign {cid} a genuine mismatch "
                                          "(creative/landing relevance or offer), rather than inference error or lag?",
                                          evidence={**ev, "tracking": note, "business_type": ctx.profile.get("business_type")},
                                          outcomes={"investigate_warning": {"severity": "Warning", "recommendation":
                                                                            "Measurement and creative/LP review before any restriction."},
                                                    "explained": {"severity": None, "recommendation": "No action."},
                                                    "uncertain": {"severity": "Info", "recommendation": "Monitor."}},
                                          provisional=prov,
                                          guidance="Policy/owner review precedes any restriction; never infer individual traits.")
                        continue
                    gated = mature and eff is not None and min(s["conversions"], rest["conversions"]) >= mc.value \
                        and min(s["clicks"], rest["clicks"]) >= mk.value
                    if not gated:
                        if eff is not None:
                            sparse.append({"dimension": d, "campaign_id": cid, "segment": seg,
                                           "conversions": s["conversions"], "rest_conversions": rest["conversions"]})
                        continue
                    calc = {"efficiency": eff, "numerator": V.ratio(s["conversions"], tot["conversions"]),
                            "denominator": V.ratio(s["cost"], tot["cost"]), "min_conversions": mc.value,
                            "min_clicks": mk.value}
                    if _unknown(seg):
                        if eff < LOW:
                            ef.finding("unknown_segment_low_efficiency", "Info", entity,
                                       f"Unknown {d} segment efficiency {eff:.2f} in campaign {cid}",
                                       evidence=ev, calculation=calc,
                                       recommendation="Keep Unknown; not grounds for exclusion.",
                                       uncertainty="Unknown mixes valuable users with incomplete inference.")
                        continue
                    if eff < LOW:
                        f = ef.finding("low_efficiency_segment", "Warning", entity,
                                       f"{d} segment {seg} efficiency {eff:.2f} < {LOW} in campaign {cid}",
                                       evidence=ev, calculation=calc,
                                       recommendation="Measurement and creative/landing-page relevance review first; "
                                                      "a bounded modifier test only where supported.",
                                       uncertainty=f"Marginal report; {comparisons} comparisons in this dimension "
                                                   "(multiple-comparison risk); inferred demographics.")
                    elif eff > HIGH:
                        f = ef.finding("high_efficiency_segment", "Info", entity,
                                       f"{d} segment {seg} efficiency {eff:.2f} > {HIGH} in campaign {cid}",
                                       evidence=ev, calculation=calc, recommendation="Opportunity hypothesis only.",
                                       uncertainty="Observational; inferred demographics.")
                    else:
                        continue
                    results.append((f, entity, eff, s))
        if sparse:
            ef.finding("sparse_segments", "Info", {"account_id": ctx.account_id},
                       f"{len(sparse)} demographic segments lack comparable samples on both sides",
                       evidence={"segments": sparse}, calculation={"min_conversions": mc.value, "min_clicks": mk.value},
                       recommendation="No efficiency conclusion for these segments.",
                       uncertainty="Insufficient sample, not neutral performance.")
        for n in sorted(tracking_notes):
            ef.partial(n)

    # -- step 5: Unknown segment
    un = ctx.check("unknown_segment", "Unknown/withheld share per dimension")
    if not data:
        un.skip("no demographic report supplied", [m for d in DIMS for m in _missing(ctx, _key(d), COLS)])
    for d in sorted(data):
        for cid in sorted(data[d]):
            segs = data[d][cid]
            tot = sum(s["cost"] for s in segs.values())
            unk = [k for k in segs if _unknown(k)]
            un.observe(f"{d} × campaign {cid}: Unknown share", dimension=d, campaign_id=cid, unknown_segments=unk,
                       unknown_cost_share=V.ratio(sum(segs[k]["cost"] for k in unk), tot),
                       withheld_segments=sorted(k for k, s in segs.items() if s.get("unknown")))

    # -- step 6: modifier tests (#27)
    mt = ctx.check("modifier_tests", "Bounded Manual CPC demographic modifier tests",
                   {CONTROLS: CONTROL_COLS, "campaigns": ["id", "bidding_strategy_type"]})
    if mt.runnable:
        if sensitive:
            mt.not_applicable("policy-sensitive categories declared: proposals withheld pending specialist review")
    if mt.runnable:
        controls = ctx.rows(CONTROLS)
        proposals, skipped = [], []
        for f, entity, eff, s in results:
            cid = entity["campaign_id"]
            if _strategy(ctx, cid) != "MANUAL_CPC":
                skipped.append({"campaign_id": cid, "reason": f"strategy {_strategy(ctx, cid) or 'unknown'}"})
                continue
            rows = [r for r in controls if str(r.get("campaign_id")) == cid and _up(r.get("dimension")) == _up(entity["dimension"])
                    and _up(r.get("segment")) == _up(entity["segment"])]
            for r in sorted(rows, key=lambda r: str(r.get("ad_group_id"))):
                cur, lo, hi = V.num(r.get("current_value")), V.num(r.get("permitted_min")), V.num(r.get("permitted_max"))
                if V.boolean(r.get("supported")) is not True or cur is None or cur <= 0 or s["conversions"] <= 0:
                    skipped.append({"campaign_id": cid, "ad_group_id": r.get("ad_group_id"), "reason": "unsupported/unknown control"})
                    continue
                proposed = min(1.1, max(0.9, eff)) * cur
                if lo is not None:
                    proposed = max(lo, proposed)
                if hi is not None:
                    proposed = min(hi, proposed)
                proposals.append({"finding_id": f.id, "campaign_id": cid, "ad_group_id": r.get("ad_group_id"),
                                  "criterion_id": r.get("criterion_id"), "dimension": entity["dimension"],
                                  "segment": entity["segment"], "current": cur, "raw_multiplier": eff,
                                  "proposed": round(proposed, 4), "permitted": [lo, hi]})
        mt.observe("Bounded test proposals (request-only, owner-reviewed)", proposals=proposals, not_proposed=skipped)

    # -- step 7: restriction guard
    rg = ctx.check("restriction_guard", "Smart Bidding / restriction guard", {"campaigns": ["id", "bidding_strategy_type"]})
    if rg.runnable:
        smart = sorted({str(r.get("id")) for r in ctx.rows("campaigns") if _up(r.get("bidding_strategy_type")) not in ("MANUAL_CPC", "")})
        rg.observe("No ordinary demographic CPC modifiers outside Manual CPC; restrictions need owner intent and "
                   "policy review", non_manual_cpc_campaigns=smart)


def verify(ctx, item, decision) -> list[str]:
    """Rules: no accepted outcome may carry an exclusion/modifier proposal for Unknown or under policy sensitivity."""
    p = decision.get("proposal") or {}
    if (p.get("exclude") or p.get("bid_modifier") is not None) and (
            _unknown(item.entity.get("segment")) or ctx.profile.get("policy_sensitive_categories")):
        return ["no exclusion/modifier proposal for Unknown segments or policy-sensitive accounts"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
