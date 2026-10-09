"""check.py — skill-136 deterministic geographic delivery, service-area and regional efficiency review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-136-geographic-competitive-intelligence/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   User-location and matched-location rows are never summed together; unknown geography is preserved.
         Hierarchy: a row whose location_id is another row's country_id/region_id (same campaign/basis) is a parent
         total and is excluded from sums (no double counting of country + region rows).
         Delivery into a region is evidenced only by user-location basis rows (location_basis containing
         'user' or 'physical'); matched/interest rows cannot prove physical delivery.
         service_available = 'prohibited' + user-location cost >= spend_material (campaign) inside effective_range
         → deterministic Critical; below spend_material → Info. service_available false/no/unavailable → Info
         provisional + review (Critical only via review with proposal.evidence_ref equal to the review's
         evidence_refs entry 'external/regional_business:<campaign_id>:<location_id>:<effective_range>').
         Regional efficiency Warning needs ctx.mature True, an explicit maximum_cpa_or_minimum_roas parseable as
         'cpa<=X'/'max_cpa X' or 'roas>=X'/'min_roas X' (or a number with objective naming cpa/roas), and
         min_conversions at the region/campaign/goal/device/network/basis cohort. Zero-conversion regions reach a
         review only with ctx.tracking_for_campaign True and cost >= spend_floor; otherwise Info/partial.
         No regional impression share, competition matrix or automatic location bid percentages are produced.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | Critical evidence_ref must be the in-window service-plan row ref
"""
from __future__ import annotations

import re
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

SKILL = "skill-136-geographic-competitive-intelligence"
VERSION = "1.0.0"

GEO = "custom/geographic_daily"
RB = "external/regional_business"
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})?\s*(?:\.\.|/|through|to)\s*(\d{4}-\d{2}-\d{2})?", re.I)
_TOL = re.compile(r"^(max_?cpa|cpa|min_?roas|roas)\s*(<=|>=|<|>|=|:)?\s*([-+]?\d+(?:\.\d+)?)$", re.I)
_SMART = ("TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE")
_METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _presence(basis) -> bool:
    b = _s(basis).lower()
    return "user" in b or "physical" in b


def _eff_range(v) -> tuple[date | None, date | None] | None:
    """'A..B', 'A/B', 'A to B', open ends allowed; empty → (None, None) (always effective); junk → None."""
    s = _s(v)
    if not s:
        return (None, None)
    m = _RANGE.fullmatch(s)
    if not m:
        return None
    return V.parse_date(m.group(1)), V.parse_date(m.group(2))


def _in_range(d: date, rng) -> bool:
    lo, hi = rng
    return (lo is None or d >= lo) and (hi is None or d <= hi)


def _tolerance(rb: dict) -> tuple[str, float] | None:
    s = _s(rb.get("maximum_cpa_or_minimum_roas")).lower().replace(" ", "")
    m = _TOL.match(s)
    if m:
        kind = "cpa" if "cpa" in m.group(1) else "roas"
        return kind, float(m.group(3))
    f = V.num(s)
    obj = _s(rb.get("objective")).lower()
    if f is not None and ("cpa" in obj) != ("roas" in obj):
        return ("cpa" if "cpa" in obj else "roas"), f
    return None


def _leaf_rows(ctx) -> tuple[list[dict], int]:
    """Geo rows minus parent-level totals whose children are also present (same campaign/basis)."""
    rows = ctx.rows(GEO)
    parents: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        key = (_s(r.get("campaign_id")), _s(r.get("location_basis")).lower())
        for col in ("country_id", "region_id"):
            p = _s(r.get(col))
            if p and p != _s(r.get("location_id")):
                parents.setdefault(key, set()).add(p)
    out, dropped = [], 0
    for r in rows:
        key = (_s(r.get("campaign_id")), _s(r.get("location_basis")).lower())
        if _s(r.get("location_id")) in parents.get(key, set()):
            dropped += 1
            continue
        out.append(r)
    return out, dropped


def _add(acc: dict, ctx, r) -> None:
    for k in _METRICS:
        v = ctx.money(r.get(k)) if k in ("cost", "conversion_value") else V.num(r.get(k))
        if v is None:
            acc["unknown_cells"] = acc.get("unknown_cells", 0) + 1
        else:
            acc[k] = acc.get(k, 0.0) + v


def run(ctx) -> None:
    """Run location-basis, prohibited-delivery, regional-efficiency, weekly-trend and location-modifier checks.

    Rules:   Critical only for user-location cost >= spend_material in a 'prohibited' region; unavailable regions are
             Info + ai_review. Efficiency Warning needs ctx.mature True, a parseable regional tolerance and
             min_conversions; zero-conversion regions reach ai_review only when tracked and cost >= spend_floor.
             regional_share_guard is always not_applicable; weekly trends and modifiers are observe-only.
    """
    _basis(ctx)
    _prohibited(ctx)
    _efficiency(ctx)
    ctx.check("regional_share_guard", "Regional impression share / competition claims",
              applicable=False,
              na_reason="no eligible-impression denominator in regional evidence: regional IS, dominance and "
                        "competition are not calculated")
    _weekly(ctx)
    _modifiers(ctx)


def _basis(ctx) -> None:
    """Step 1: separate bases, preserve unknown geography, avoid overlapping hierarchy sums."""
    chk = ctx.check("location_basis", "Location basis separation and unknown geography",
                    {GEO: ["campaign_id", "date", "location_id", "location_basis", "country_id", "region_id",
                           "unknown_location_flag", "impressions", "clicks", "cost"]})
    if not chk.runnable:
        return
    rows, dropped = _leaf_rows(ctx)
    if dropped:
        chk.partial(f"{dropped} parent-level rows (country/region totals with child rows) excluded from sums")
    agg: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (_s(r.get("campaign_id")), _s(r.get("location_basis")) or "unknown_basis")
        a = agg.setdefault(key, {"locations": set(), "unknown_cost": 0.0, "unknown_rows": 0})
        _add(a, ctx, r)
        unknown = V.boolean(r.get("unknown_location_flag")) is True or not _s(r.get("location_id"))
        if unknown:
            a["unknown_rows"] += 1
            a["unknown_cost"] += ctx.money(r.get("cost")) or 0
        else:
            a["locations"].add(_s(r.get("location_id")))
    for (cid, basis) in sorted(agg):
        a = agg[(cid, basis)]
        share = V.ratio(a["unknown_cost"], a.get("cost"))
        chk.observe(f"Campaign {cid} basis {basis}: geographic totals (bases never summed together)",
                    campaign_id=cid, location_basis=basis, locations=len(a["locations"]),
                    **{k: a.get(k) for k in _METRICS}, unknown_location_cost=a["unknown_cost"],
                    unknown_location_cost_share=share, unknown_cells=a.get("unknown_cells", 0))
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is not None and a["unknown_cost"] >= floor.value:
            chk.finding("unknown_geography", "Info", {"campaign_id": cid, "location_basis": basis},
                        f"Campaign {cid} ({basis}): {a['unknown_cost']:.2f} {ctx.currency} cost with unknown "
                        f"location ({share:.1%} of basis cost)" if share is not None else
                        f"Campaign {cid} ({basis}): unknown-location cost {a['unknown_cost']:.2f}",
                        evidence={"unknown_cost": a["unknown_cost"], "basis_cost": a.get("cost"),
                                  "unknown_rows": a["unknown_rows"], "spend_floor": floor.value,
                                  "spend_floor_source": floor.source, "window": [ctx.period_start, ctx.period_end]},
                        recommendation="Keep unknown geography separate; do not reallocate it to regions.",
                        uncertainty="Unknown location is not evidence of out-of-area delivery.")


def _plan_ref(rb: dict) -> str:
    """Stable ref of one regional_business row (campaign/location/effective_range grain)."""
    return f"{RB}:{_s(rb.get('campaign_id'))}:{_s(rb.get('location_id'))}:{_s(rb.get('effective_range'))}"


def _prohibited(ctx) -> None:
    """Critical row: observed material user-location delivery into a documented prohibited region."""
    chk = ctx.check("prohibited_delivery", "Delivery into documented prohibited/unavailable regions",
                    {GEO: ["campaign_id", "date", "location_id", "location_basis", "country_id", "region_id",
                           "impressions", "clicks", "cost"],
                     RB: ["campaign_id", "location_id", "effective_range", "service_available", "owner"]})
    if not chk.runnable:
        return
    rows, _ = _leaf_rows(ctx)
    presence = [r for r in rows if _presence(r.get("location_basis"))]
    if not presence:
        chk.partial("no user-location basis rows: delivery into regions cannot be evidenced")
    for rb in sorted(ctx.rows(RB), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("location_id")))):
        avail = _s(rb.get("service_available")).lower()
        prohibited = avail == "prohibited"
        unavailable = not prohibited and V.boolean(avail) is False or avail in ("unavailable", "not_available")
        if not (prohibited or unavailable):
            continue
        cid, loc = _s(rb.get("campaign_id")), _s(rb.get("location_id"))
        rng = _eff_range(rb.get("effective_range"))
        if rng is None:
            chk.partial(f"{cid}/{loc}: unparseable effective_range '{rb.get('effective_range')}'")
            continue
        acc: dict = {}
        days = set()
        for r in presence:
            d = V.parse_date(r.get("date"))
            if (_s(r.get("campaign_id")) == cid and d and _in_range(d, rng)
                    and loc in (_s(r.get("location_id")), _s(r.get("region_id")), _s(r.get("country_id")))):
                _add(acc, ctx, r)
                days.add(d)
        cost, clicks, imps = acc.get("cost", 0.0), acc.get("clicks", 0.0), acc.get("impressions", 0.0)
        if not (cost or clicks or imps):
            chk.observe(f"{cid}/{loc}: no user-location delivery into {avail} region", campaign_id=cid,
                        location_id=loc)
            continue
        material = ctx.params.get("spend_material", cid)
        entity = {"campaign_id": cid, "location_id": loc}
        ev = {"service_available": rb.get("service_available"), "effective_range": rb.get("effective_range"),
              "owner": rb.get("owner"), "impressions": imps, "clicks": clicks, "cost": cost,
              "delivery_days": len(days), "first_day": min(days), "last_day": max(days),
              "location_basis": "user location", "spend_material": material.value,
              "spend_material_source": material.source or material.reason}
        if prohibited and material.value is not None and cost >= material.value:
            chk.finding("prohibited_region_delivery", "Critical", entity,
                        f"Campaign {cid} delivered {cost:.2f} {ctx.currency} ({clicks:g} clicks) to users located in "
                        f"documented prohibited region {loc}", evidence=ev,
                        recommendation="Request an urgent location-exclusion review with the owner; no change made here.",
                        uncertainty="Based on supplied user-location report and service plan only.")
            continue
        prov = chk.finding("unavailable_region_delivery", "Info", entity,
                           f"Campaign {cid} delivered {cost:.2f} {ctx.currency} to users in region {loc} documented "
                           f"as '{rb.get('service_available')}'", evidence=ev,
                           recommendation="Confirm service-area settings with the owner.",
                           uncertainty="Unavailable is not necessarily prohibited; materiality "
                                       + ("unresolved" if material.value is None else f"below {material.value:g}"))
        if not prohibited:
            chk.review("unavailable_region_delivery", entity,
                       f"Is region {loc} a PROHIBITED service region for campaign {cid}, making this delivery a "
                       f"material failure?",
                       evidence={**ev, "evidence_refs": [_plan_ref(rb)]},
                       outcomes={"prohibited_material": {"severity": "Critical", "recommendation":
                                                         "Escalate exclusion review; cite the prohibition document."},
                                 "unserved_not_prohibited": {"severity": "Info", "recommendation":
                                                             "Review service-area targeting at the next audit."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the service owner."}},
                       guidance="Critical needs proposal.evidence_ref equal to one of evidence.evidence_refs "
                                "(the service-plan row documenting the prohibition).",
                       provisional=prov)


def _efficiency(ctx) -> None:
    """Steps 2-3: regional rates within campaign/goal/device/network/basis vs stated tolerance."""
    chk = ctx.check("regional_efficiency", "Mature regional outcomes vs client efficiency tolerance",
                    {GEO: ["campaign_id", "date", "location_id", "location_basis", "device", "network", "goal_id",
                           "impressions", "clicks", "cost", "conversions", "conversion_value"],
                     RB: ["campaign_id", "location_id", "effective_range", "objective", "maximum_cpa_or_minimum_roas",
                          "margin_basis_if_used", "owner"]})
    if not chk.runnable:
        return
    mature = ctx.mature is True
    if not mature:
        chk.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): regional rates descriptive only")
    mi, mcl, mc = (ctx.params.get(p) for p in ("min_impressions", "min_clicks", "min_conversions"))
    tol: dict[tuple[str, str], tuple] = {}
    for rb in ctx.rows(RB):
        cid, loc = _s(rb.get("campaign_id")), _s(rb.get("location_id"))
        t = _tolerance(rb)
        rng = _eff_range(rb.get("effective_range"))
        if t is None:
            if _s(rb.get("maximum_cpa_or_minimum_roas")):
                chk.partial(f"{cid}/{loc}: tolerance '{rb.get('maximum_cpa_or_minimum_roas')}' not parseable as CPA or ROAS")
            continue
        if rng is None or (ctx.period_start and ctx.period_end and not (_in_range(ctx.period_start, rng)
                                                                        and _in_range(ctx.period_end, rng))):
            chk.partial(f"{cid}/{loc}: effective_range does not cover the analysis period")
            continue
        tol[(cid, loc)] = (t, rb)
    rows, _ = _leaf_rows(ctx)
    cohorts: dict[tuple, dict] = {}
    for r in rows:
        if V.boolean(r.get("unknown_location_flag")) is True or not _s(r.get("location_id")):
            continue
        key = tuple(_s(r.get(k)) for k in ("campaign_id", "location_basis", "location_id", "goal_id", "device",
                                            "network"))
        _add(cohorts.setdefault(key, {}), ctx, r)
    no_tol = 0
    for key in sorted(cohorts):
        a = cohorts[key]
        cid, basis, loc, goal, device, net = key
        imp, clk, cost, conv, val = (a.get(k, 0.0) for k in _METRICS)
        rates = {"ctr": V.ratio(clk, imp) if mi.value and imp >= mi.value else None,
                 "cvr": V.ratio(conv, clk) if mature and mcl.value and clk >= mcl.value else None,
                 "cpa": V.ratio(cost, conv) if mature and mc.value and conv >= mc.value else None,
                 "roas": V.ratio(val, cost) if mature and mc.value and conv >= mc.value else None}
        entity = {"campaign_id": cid, "location_id": loc, "location_basis": basis, "goal_id": goal,
                  "device": device, "network": net}
        base_ev = {"impressions": imp, "clicks": clk, "cost": cost, "conversions": conv, "conversion_value": val,
                   **rates, "min_impressions": mi.value, "min_clicks": mcl.value, "min_conversions": mc.value,
                   "window": [ctx.period_start, ctx.period_end], "note": "ROAS is not ROI"}
        t = tol.get((cid, loc))
        if t is None:
            no_tol += 1
            chk.observe(f"{cid}/{loc} ({basis}, {goal}, {device}, {net}): regional rates", **entity, **base_ev)
            continue
        (kind, limit), rb = t
        ev = {**base_ev, "tolerance": f"{kind} {'<=' if kind == 'cpa' else '>='} {limit:g}",
              "tolerance_source": f"{RB}[{cid}/{loc}]", "owner": rb.get("owner"),
              "margin_basis_if_used": rb.get("margin_basis_if_used")}
        metric = rates[kind]
        if not mature:
            chk.observe(f"{cid}/{loc}: tolerance comparison withheld (immature)", **entity, **ev)
            continue
        if metric is not None:
            miss = metric > limit if kind == "cpa" else metric < limit
            if miss:
                chk.finding("regional_efficiency_miss", "Warning", entity,
                            f"{cid}/{loc} ({basis}): mature {kind.upper()} {metric:.2f} misses the stated tolerance "
                            f"{limit:g} ({conv:g} conversions, {cost:.2f} {ctx.currency})", evidence=ev,
                            calculation={"numerator": cost if kind == "cpa" else val,
                                         "denominator": conv if kind == "cpa" else cost},
                            recommendation="Review local availability/value mix, then propose a service/creative "
                                           "review or a bounded geography test; no automatic location bid change.",
                            uncertainty="Observational; regional mix and attribution can explain differences.")
            else:
                chk.observe(f"{cid}/{loc}: within tolerance", **entity, **ev)
            continue
        floor = ctx.params.get("spend_floor", cid)
        tracking, tnote = ctx.tracking_for_campaign(cid)
        if conv == 0 and kind == "cpa" and floor.value is not None and cost >= max(floor.value, limit) and tracking is True:
            ev.update({"spend_floor": floor.value, "tracking": tnote})
            prov = chk.finding("zero_conversion_region", "Info", entity,
                               f"{cid}/{loc}: {cost:.2f} {ctx.currency} with 0 mature conversions exceeds the stated "
                               f"max CPA {limit:g}", evidence=ev,
                               recommendation="Review regional relevance before any proposal; exposure is not savings.",
                               uncertainty="Lag, long sales cycle or assisted value can explain zero conversions.")
            chk.review("zero_conversion_region", entity,
                       f"Is region {loc} relevant to campaign {cid}'s served offer, making the zero-conversion "
                       f"exposure a miss of the stated tolerance?",
                       evidence=ev,
                       outcomes={"relevant_miss": {"severity": "Warning", "recommendation":
                                                   "Propose service/creative review or bounded geography test."},
                                 "not_comparable": {"severity": None, "recommendation": "No action."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the regional owner."}},
                       guidance="Use only the regional business plan and profile; availability/capacity first.",
                       provisional=prov)
            continue
        if floor.value is not None and cost >= floor.value:
            chk.finding("insufficient_regional_sample", "Info", entity,
                        f"{cid}/{loc}: {cost:.2f} {ctx.currency} spend but below min_conversions ({conv:g} < "
                        f"{mc.value}) to judge the stated {kind.upper()} tolerance"
                        + ("" if tracking is True else f"; tracking not evidenced ({tnote})"),
                        evidence={**ev, "spend_floor": floor.value, "tracking": tnote},
                        recommendation="Extend the window or aggregate comparable regions before judging.",
                        uncertainty="Sparse sample.")
    if no_tol:
        chk.partial(f"{no_tol} regional cohorts without an applicable stated tolerance (descriptive only)")


def _weekly(ctx) -> None:
    """Step 5: aligned complete weeks per region; descriptive only."""
    chk = ctx.check("weekly_trends", "Aligned complete-week regional trends (descriptive)",
                    {GEO: ["campaign_id", "date", "location_id", "location_basis", "impressions", "clicks",
                           "conversions"]})
    if not chk.runnable:
        return
    if ctx.period_start is None or ctx.period_end is None:
        chk.partial("report period unknown: weeks cannot be aligned")
        return
    first = ctx.period_start + timedelta(days=(7 - ctx.period_start.weekday()) % 7)
    weeks = []
    while first + timedelta(days=6) <= ctx.period_end:
        weeks.append(first)
        first += timedelta(days=7)
    if len(weeks) < 2:
        chk.partial(f"only {len(weeks)} complete Monday-Sunday weeks in the report period")
        return
    mi, mcl = ctx.params.get("min_impressions"), ctx.params.get("min_clicks")
    rows, _ = _leaf_rows(ctx)
    series: dict[tuple, dict] = {}
    for r in rows:
        d = V.parse_date(r.get("date"))
        if d is None or not _s(r.get("location_id")):
            continue
        wk = next((w for w in weeks if w <= d <= w + timedelta(days=6)), None)
        if wk is None:
            continue
        key = (_s(r.get("campaign_id")), _s(r.get("location_basis")), _s(r.get("location_id")))
        _add(series.setdefault(key, {}).setdefault(wk, {}), ctx, r)
    for key in sorted(series):
        pts = []
        for wk in weeks:
            a = series[key].get(wk, {})
            imp, clk, conv = a.get("impressions", 0.0), a.get("clicks", 0.0), a.get("conversions", 0.0)
            pts.append({"week_start": wk, "impressions": imp, "clicks": clk, "conversions": conv,
                        "ctr": V.ratio(clk, imp) if mi.value and imp >= mi.value else None,
                        "cvr": V.ratio(conv, clk) if ctx.mature is True and mcl.value and clk >= mcl.value else None})
        chk.observe(f"{key[0]}/{key[2]} ({key[1]}): weekly series", campaign_id=key[0], location_basis=key[1],
                    location_id=key[2], weeks=pts)


def _modifiers(ctx) -> None:
    """Step 5: location CPC modifiers are not a default under Smart Bidding; descriptive observation."""
    chk = ctx.check("location_modifiers", "Location bid modifiers vs bidding strategy",
                    {"bid_adjustments": ["campaign_id", "dimension", "modifier"],
                     "campaigns": ["id", "bidding_strategy_type"]})
    if not chk.runnable:
        return
    strat = {_s(c.get("id")): _s(c.get("bidding_strategy_type")).upper() for c in ctx.rows("campaigns")}
    n = 0
    for b in sorted(ctx.rows("bid_adjustments"), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("segment_value")))):
        if "location" not in _s(b.get("dimension")).lower():
            continue
        n += 1
        cid = _s(b.get("campaign_id"))
        chk.observe(f"Campaign {cid}: location modifier {b.get('modifier')} under {strat.get(cid) or 'unknown'}",
                    campaign_id=cid, segment_value=b.get("segment_value"), modifier=b.get("modifier"),
                    bidding_strategy_type=strat.get(cid),
                    smart_bidding=strat.get(cid) in _SMART,
                    note="manual location CPC modifiers need a supporting strategy; not a default under Smart Bidding")
    chk.observe("Location modifiers inventoried", count=n)


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   prohibited_material (Critical) requires proposal.evidence_ref equal to one of the reviewed item's
             evidence.evidence_refs: the external/regional_business row of this campaign_id/location_id whose
             effective_range contains the delivery days (built by _plan_ref). Unknown refs, refs of other
             campaigns/locations or other effective ranges are rejected. Other outcomes need no proposal.
    """
    if decision.get("outcome") != "prohibited_material":
        return []
    ref = _s((decision.get("proposal") or {}).get("evidence_ref"))
    if not ref:
        return ["prohibited_material needs proposal.evidence_ref to the documented prohibition"]
    allowed = item.evidence.get("evidence_refs") or []
    if ref not in allowed:
        return [f"evidence_ref {ref} is not the service-plan row of campaign {item.entity.get('campaign_id')} / "
                f"location {item.entity.get('location_id')} for the delivery window (allowed: {allowed or 'none'})"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
