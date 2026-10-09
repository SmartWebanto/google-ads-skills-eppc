"""check.py — skill-054 deterministic geographic coverage, within-campaign efficiency screens and guarded tests.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-054-geographic-performance-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #26 Extended Devices, Locations and Audiences Bidding (Brainlabs) — clean-room reimplementation of
         location CPA vs campaign baseline with sample gates; modifiers only as capped Manual CPC test proposals
         index #28 MCC Location Bid Modifier Script (fredericharnois) — clean-room reimplementation of high-CVR
         location detection (cvr_index in observations, CPA < 0.7x opportunity); adding locations / setting
         modifiers is never executed; MCC fan-out is handled by the runtime's per-account partitioning
rules:   Aggregate per (campaign, report_basis, geo_level, location_type, geo_criterion_id); user_location and
         matched_location bases and parent/child levels are NEVER summed together. Rows whose
         reporting_completeness is not complete are excluded (partial).
         Baseline = the rest of the SAME campaign, basis and level; both sides must pass min_conversions (CPA)
         or min_clicks (CVR). CPA > 1.5x or CVR < 0.5x → Warning; CPA < 0.7x → Info — only with ctx.mature True.
         Zero-conversion locations never enter the CVR/CPA screen; they use the separate spend-floor path.
         Zero-conversion screen: mature, ctx.tracking_for_campaign True, cost >= spend_floor(campaign) →
         provisional Info + review (Warning only after relevance review).
         Service mapping walks custom/geo_lookup parent_id to an exact normalized profile.service_area name;
         unmapped/withheld geography is unknown, never out-of-area. Out-of-area with cost >= spend_floor is
         reviewed (Warning = confirmed non-serviceable); campaigns with remote_buyers true are skipped.
         Modifier tests only for MANUAL_CPC: raw = baseline CPA / location CPA, incremental capped to [0.9, 1.1],
         multiplied by the existing LOCATION multiplier (unknown when not exported). Smart Bidding: none.
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

SKILL = "skill-054-geographic-performance-analysis"
VERSION = "1.0.0"

_GEO = "custom/geographic_performance"
_LOOKUP = "custom/geo_lookup"
_METRICS = ["impressions", "clicks", "cost", "conversions", "conversion_value"]
_ADVERSE_CPA, _ADVERSE_CVR, _GOOD_CPA = 1.5, 0.5, 0.7
_CAP = (0.9, 1.1)


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _objective(ctx, cid: str) -> dict:
    obj = ctx.profile.get("campaign_objectives") or {}
    o = next((v for k, v in obj.items() if str(k) == cid), None) if isinstance(obj, dict) else None
    return o if isinstance(o, dict) else {}


def _aggregate(ctx, chk) -> dict[tuple, dict]:
    """(campaign, basis, level, location_type) → {criterion: [imp, clicks, cost, conv, value]}."""
    groups: dict[tuple, dict] = {}
    excluded = unknown = 0
    for r in ctx.rows(_GEO):
        comp = _s(r.get("reporting_completeness")).lower()
        if comp and "complete" not in comp or any(w in comp for w in ("partial", "incomplete")):
            excluded += 1
            continue
        vals = [V.num(r.get("impressions")), V.num(r.get("clicks")), ctx.money(r.get("cost")),
                V.num(r.get("conversions")), V.num(r.get("conversion_value"))]
        if None in vals[:4]:
            unknown += 1
            continue
        key = (_s(r.get("campaign_id")), _s(r.get("report_basis")).lower() or "?", _s(r.get("geo_level")).upper(),
               _s(r.get("location_type")).upper())
        crit = _s(r.get("geo_criterion_id")) or "(unknown)"
        a = groups.setdefault(key, {}).setdefault(crit, [0.0, 0.0, 0.0, 0.0, 0.0, _s(r.get("location_name"))])
        for i in range(5):
            a[i] += vals[i] or 0
    if excluded:
        chk.partial(f"{excluded} geographic rows not marked complete excluded")
    if unknown:
        chk.partial(f"{unknown} geographic rows with unknown metrics excluded")
    return groups


def _served(ctx, crit: str, lookup: dict, service: list[str]) -> bool | None:
    """True in-area, False when the full parent chain to a root is known and unmatched, None when unresolvable."""
    seen, cur = [], crit
    while cur:
        if cur not in lookup or cur in seen:
            return None
        seen.append(cur)
        if V.norm_text(lookup[cur].get("name")) in service:
            return True
        cur = _s(lookup[cur].get("parent_id"))
    return False


def run(ctx) -> None:
    """Run geographic coverage, service-area mapping, efficiency, zero-conversion and Manual CPC test checks.

    Rules:   Missing custom/geographic_performance columns skip all five checks. Efficiency findings only with
             ctx.mature True and min_conversions/min_clicks on both sides (Warning adverse, Info CPA < 0.7x).
             Zero-conversion (tracking + spend_floor) and out-of-area (service_area + spend_floor) are ai_review;
             Warning only after review. Modifier values are observations for MANUAL_CPC only, never findings.
    """
    geo_cols = ["campaign_id", "date", "geo_level", "geo_criterion_id", "location_type", "report_basis"] + _METRICS
    rec = ctx.check("coverage_reconciliation", "Geographic totals vs campaign totals per basis/level (step 1)",
                    {_GEO: geo_cols, "campaign_metrics": ["campaign_id", "cost"]})
    later = (("service_area_mapping", "Map one level at a time to the service area (step 2)"),
             ("efficiency_comparison", "CPA/CVR vs rest of the same campaign (steps 3-4; index #26/#28)"),
             ("zero_conversion_screen", "Zero-conversion locations with tracking and spend floor (step 4)"),
             ("modifier_test_proposal", "Capped Manual CPC location test values (steps 6-7)"))
    geo_t = ctx.table(_GEO)
    if geo_t is None or geo_t.missing(geo_cols):
        missing = [f"{_GEO} (file)"] if geo_t is None else [f"{_GEO}:{c}" for c in geo_t.missing(geo_cols)]
        if rec.runnable:
            rec.skip("geographic report unavailable", missing)
        for cid, title in later:
            ctx.check(cid, title).skip("geographic report unavailable", missing)
        return
    groups = _aggregate(ctx, rec)
    if rec.runnable:
        totals = {_s(m.get("campaign_id")): ctx.money(m.get("cost")) for m in ctx.rows("campaign_metrics")}
        for key, crits in sorted(groups.items()):
            cost = sum(v[2] for v in crits.values())
            rec.observe(f"Campaign {key[0]} {key[1]} {key[2]}: geographic cost covers campaign cost",
                        campaign_id=key[0], report_basis=key[1], geo_level=key[2], location_type=key[3],
                        geo_cost=cost, campaign_cost=totals.get(key[0]), coverage=V.ratio(cost, totals.get(key[0])),
                        unknown_geography_cost=crits.get("(unknown)", [0, 0, 0])[2], currency=ctx.currency,
                        note="Bases and levels are reconciled separately, never summed.")
        if len({k[1] for k in groups}) > 1:
            rec.observe("Both user-location and matched-location bases present; reported separately",
                        bases=sorted({k[1] for k in groups}))

    service = [V.norm_text(x) for x in (ctx.profile.get("service_area") or []) if _s(x)]
    sm = ctx.check(later[0][0], later[0][1], {_LOOKUP: ["geo_criterion_id", "name", "parent_id", "geo_level"]})
    if sm.runnable:
        if not service:
            sm.skip("profile.service_area missing: relevance/exclusion claims skipped", ["profile:service_area"])
        else:
            _service(ctx, sm, groups, service)

    min_conv, min_clicks = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
    eff = ctx.check(later[1][0], later[1][1], {_GEO: geo_cols})
    signals: list[dict] = []
    if ctx.mature is not True:
        eff.partial(f"conversion maturity not established ({ctx.maturity_note}); descriptive totals only")
    for key, crits in sorted(groups.items()):
        cid = key[0]
        for crit, a in sorted(crits.items()):
            if crit == "(unknown)":
                continue
            b = [sum(v[i] for k, v in crits.items() if k != crit) for i in range(5)]
            cpa, bcpa = V.ratio(a[2], a[3]), V.ratio(b[2], b[3])
            cvr, bcvr = V.ratio(a[3], a[1]), V.ratio(b[3], b[1])
            cpa_ok = min_conv.value is not None and a[3] >= min_conv.value and b[3] >= min_conv.value
            cvr_ok = min_clicks.value is not None and a[1] >= min_clicks.value and b[1] >= min_clicks.value
            row = {"campaign_id": cid, "report_basis": key[1], "geo_level": key[2], "location_type": key[3],
                   "geo_criterion_id": crit, "location_name": a[5], "cost": a[2], "clicks": a[1], "conversions": a[3],
                   "value": a[4], "cpa": cpa, "cvr": cvr, "roas": V.ratio(a[4], a[2]),
                   "baseline_cost": b[2], "baseline_clicks": b[1], "baseline_conversions": b[3],
                   "baseline_cpa": bcpa, "baseline_cvr": bcvr,
                   "cpa_index": V.ratio(cpa, bcpa) if cpa_ok else None, "cvr_index": V.ratio(cvr, bcvr) if cvr_ok else None,
                   "min_conversions": min_conv.value, "min_clicks": min_clicks.value,
                   "window": [ctx.period_start, ctx.period_end], "currency": ctx.currency}
            signals.append(row)
            if not eff.runnable or ctx.mature is not True:
                continue
            ent = {"campaign_id": cid, "report_basis": key[1], "geo_level": key[2], "geo_criterion_id": crit}
            adverse = [m for m in (("cpa", row["cpa_index"], row["cpa_index"] is not None and row["cpa_index"] > _ADVERSE_CPA),
                                   ("cvr", row["cvr_index"], row["cvr_index"] is not None and a[3] > 0
                                    and row["cvr_index"] < _ADVERSE_CVR))
                       if m[2]]
            if adverse:
                eff.finding("adverse_location_efficiency", "Warning", ent,
                            f"Location {crit} ({a[5] or 'unnamed'}) in campaign {cid}: "
                            + ", ".join(f"{m[0].upper()} index {m[1]:.2f}" for m in adverse)
                            + " vs rest of campaign", evidence=row,
                            calculation={"cpa_index": "location CPA / rest-of-campaign CPA",
                                         "cvr_index": "location CVR / rest-of-campaign CVR",
                                         "thresholds": {"cpa": _ADVERSE_CPA, "cvr": _ADVERSE_CVR}},
                            recommendation="Review service fit and landing/tracking; Manual CPC may test a capped "
                                           "modifier (see modifier_test_proposal). No auto-exclusion.",
                            uncertainty="Small samples, modeled location and lag can explain differences; historical "
                                        "cost is exposure, not savings.")
            elif row["cpa_index"] is not None and row["cpa_index"] < _GOOD_CPA:
                eff.finding("location_efficiency_opportunity", "Info", ent,
                            f"Location {crit} ({a[5] or 'unnamed'}) in campaign {cid}: CPA index {row['cpa_index']:.2f}",
                            evidence=row, calculation={"cpa_index": "location CPA / rest-of-campaign CPA",
                                                       "threshold": _GOOD_CPA},
                            recommendation="Hypothesis only: consider a bounded test where the control is supported.",
                            uncertainty="Opportunity hypothesis; no uplift forecast.")
    eff.observe("Location comparisons evaluated", comparisons=len(signals),
                cpa_qualified=sum(1 for s in signals if s["cpa_index"] is not None),
                cvr_qualified=sum(1 for s in signals if s["cvr_index"] is not None),
                qualified_locations=[{k: s[k] for k in ("campaign_id", "report_basis", "geo_level", "geo_criterion_id",
                                                         "cpa_index", "cvr_index")}
                                     for s in signals if s["cpa_index"] is not None or s["cvr_index"] is not None])

    zc = ctx.check(later[2][0], later[2][1], {_GEO: geo_cols})
    _zero(ctx, zc, signals)

    mt = ctx.check(later[3][0], later[3][1], {"campaigns": ["id", "bidding_strategy_type"],
                                              "bid_adjustments": ["campaign_id", "dimension", "criterion_id", "modifier"]})
    if mt.runnable:
        _modifiers(ctx, mt, signals)


def _service(ctx, sm, groups, service) -> None:
    lookup = {_s(r.get("geo_criterion_id")): r for r in ctx.rows(_LOOKUP)}
    excl = {(_s(r.get("campaign_id")), _s(r.get("criterion_id"))) for r in ctx.rows("bid_adjustments")
            if _s(r.get("dimension")).upper() in ("LOCATION", "GEO") and V.boolean(r.get("excluded")) is True}
    unmapped = 0
    for key, crits in sorted(groups.items()):
        cid = key[0]
        remote = V.boolean(_objective(ctx, cid).get("remote_buyers"))
        floor = ctx.params.get("spend_floor", cid)
        for crit, a in sorted(crits.items()):
            served = _served(ctx, crit, lookup, service)
            if served is None:
                unmapped += 1
                continue
            if served:
                continue
            ent = {"campaign_id": cid, "report_basis": key[1], "geo_level": key[2], "geo_criterion_id": crit}
            ev = {"location_name": lookup[crit].get("name"), "country_code": lookup[crit].get("country_code"),
                  "cost": a[2], "conversions": a[3], "spend_floor": floor.value, "spend_floor_source": floor.source,
                  "service_area": service, "remote_buyers": _objective(ctx, cid).get("remote_buyers"),
                  "currently_excluded": (cid, crit) in excl, "mature": ctx.mature,
                  "window": [ctx.period_start, ctx.period_end]}
            if remote is True:
                sm.observe(f"Campaign {cid}: outside-area location {crit} intended (remote_buyers)", **ent, **ev)
                continue
            if floor.value is None or a[2] < floor.value or ctx.mature is not True:
                sm.observe(f"Campaign {cid}: outside-area location {crit} below floor or immature", **ent, **ev)
                continue
            sm.review("non_serviceable_traffic", ent,
                      f"Is location {crit} ({ev['location_name']}) traffic in campaign {cid} confirmed non-serviceable "
                      f"({key[1]})?", evidence=ev,
                      outcomes={"non_serviceable_confirmed": {"severity": "Warning", "recommendation":
                                                              "Owner reviews a geographic eligibility change with trade-offs."},
                                "intended_or_serviceable": {"severity": None, "recommendation": "Keep; document exception."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask about travelers/shipping coverage."}},
                      guidance="Matched-location traffic can be legitimate interest; check travelers, shipping and "
                               "existing exclusions. Exposure is not savings.")
    if unmapped:
        sm.partial(f"{unmapped} locations not resolvable in geo_lookup: unknown, not out-of-area")


def _zero(ctx, zc, signals) -> None:
    if ctx.mature is not True:
        zc.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    unresolved = set()
    for s in signals:
        if s["conversions"] != 0 or not s["cost"]:
            continue
        cid = s["campaign_id"]
        ok, note = ctx.tracking_for_campaign(cid)
        if ok is not True:
            unresolved.add(note)
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None or s["cost"] < floor.value:
            continue
        ent = {"campaign_id": cid, "report_basis": s["report_basis"], "geo_level": s["geo_level"],
               "geo_criterion_id": s["geo_criterion_id"]}
        ev = {**s, "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": note}
        prov = zc.finding("zero_conversion_location", "Info", ent,
                          f"Location {s['geo_criterion_id']} in campaign {cid} spent {s['cost']:.2f} {ctx.currency} with "
                          f"0 conversions (spend_floor {floor.value:g})", evidence=ev,
                          recommendation="Investigate relevance/tracking; no automatic pause or exclusion.",
                          uncertainty="Long sales cycles or modeled location can explain zero conversions.")
        zc.review("zero_conversion_location", ent,
                  f"After relevance review, does zero-conversion spend in location {s['geo_criterion_id']} (campaign "
                  f"{cid}) warrant investigation?", evidence=ev, provisional=prov,
                  outcomes={"investigate": {"severity": "Warning", "recommendation":
                                            "Investigate the location's relevance and economics before any change."},
                            "explained": {"severity": None, "recommendation": "Document the explanation."},
                            "uncertain": {"severity": "Info", "recommendation": "Keep monitoring."}})
    for n in sorted(unresolved):
        zc.partial(f"tracking not verified: {n}")


def _modifiers(ctx, mt, signals) -> None:
    strat = {_s(c.get("id")): _s(c.get("bidding_strategy_type")).upper() for c in ctx.rows("campaigns")}
    mods = {(_s(r.get("campaign_id")), _s(r.get("criterion_id"))): r for r in ctx.rows("bid_adjustments")
            if _s(r.get("dimension")).upper() in ("LOCATION", "GEO")}
    for s in signals:
        if s["cpa_index"] is None or not s["cpa"] or ctx.mature is not True:
            continue
        cid = s["campaign_id"]
        if strat.get(cid) != "MANUAL_CPC":
            continue
        cur_row = mods.get((cid, s["geo_criterion_id"]))
        cur = V.num(cur_row.get("modifier")) if cur_row else None
        excluded = cur_row is not None and V.boolean(cur_row.get("excluded")) is True
        raw = s["baseline_cpa"] / s["cpa"]
        inc = min(max(raw, _CAP[0]), _CAP[1])
        mt.observe(f"Campaign {cid} location {s['geo_criterion_id']}: capped Manual CPC test value",
                   campaign_id=cid, geo_criterion_id=s["geo_criterion_id"], raw_multiplier=raw,
                   capped_incremental=inc, current_multiplier=cur, excluded=excluded,
                   proposed_multiplier=None if cur is None or excluded else cur * inc,
                   note="Cautious test heuristic, not an optimum; verify platform range/interactions; owner approval.")
    smart = sorted({c for c, t in strat.items() if t and t != "MANUAL_CPC"})
    if smart:
        mt.observe("Smart Bidding campaigns: no ordinary location CPC adjustments proposed", campaigns=smart)


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
