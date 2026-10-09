"""check.py — skill-135 deterministic top/absolute-top prominence rate and share review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-135-top-of-page-rate-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #25 Bid to Impression Share (Google Ads scripts solution) — clean-room reimplementation of the
         "observed share vs target share" comparison only; its bid raising/lowering is NOT reproduced (no IS-target
         bid logic: top-rate gaps never justify bid changes in this recipe).
rules:   Served prominence rates (top_impression_rate, absolute_top_impression_rate) and eligible-opportunity
         shares (search_top_impression_share, search_absolute_top_impression_share) stay separate fields — never
         relabelled, averaged across days or weighted by campaign/ordinary impressions.
         Only rows whose network is Google Search (GOOGLE_SEARCH|SEARCH) are analysed; partner/unknown rows excluded.
         Weekly comparisons use ONLY custom/search_prominence_weekly native rows of complete 7-day weeks at the same
         campaign/ad_group/network grain, both sides >= min_impressions; differences in percentage points,
         relative change reported separately.
         Warning path needs ctx.mature True, a declared tolerance (profile.visibility_tolerance_percentage_points or
         profile.campaign_objectives[cid].visibility_tolerance_percentage_points) AND an AI review that the decline
         conflicts with a stated visibility goal. No tolerance/goal → Info.
         #25 targets are profile-supplied: profile.campaign_objectives[cid].target_search_top_impression_share /
         target_search_absolute_top_impression_share (fractions). Below target → Info only, never a bid proposal.
         Position outcomes come only from custom/position_outcomes; campaign rate tiers are never position segments.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
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

SKILL = "skill-135-top-of-page-rate-monitoring"
VERSION = "1.0.0"

DAILY = "custom/search_prominence_daily"
WEEKLY = "custom/search_prominence_weekly"
POSITION = "custom/position_outcomes"
RATES = ("top_impression_rate", "absolute_top_impression_rate")
SHARES = ("search_top_impression_share", "search_absolute_top_impression_share")
METRICS = RATES + SHARES
_SEARCH = ("GOOGLE_SEARCH", "SEARCH")
_TARGETS = {"search_top_impression_share": "target_search_top_impression_share",
            "search_absolute_top_impression_share": "target_search_absolute_top_impression_share"}


def _network_ok(row) -> bool:
    return str(row.get("network") or "").strip().upper().replace(" ", "_") in _SEARCH


def _campaign_objective(ctx, cid: str) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objs, dict):
        return {}
    obj = next((v for k, v in objs.items() if str(k) == cid), None)
    return obj if isinstance(obj, dict) else {}


def _tolerance(ctx, cid: str) -> tuple[float | None, str]:
    """Client tolerance in percentage points; campaign value wins over account value."""
    v = V.num(_campaign_objective(ctx, cid).get("visibility_tolerance_percentage_points"))
    if v is not None and v >= 0:
        return v, f"profile.campaign_objectives[{cid}].visibility_tolerance_percentage_points"
    v = V.num(ctx.profile.get("visibility_tolerance_percentage_points"))
    if v is not None and v >= 0:
        return v, "profile.visibility_tolerance_percentage_points"
    return None, "no visibility tolerance declared"


def run(ctx) -> None:
    """Run native daily prominence, counting-basis, weekly comparison, target-gap and position-outcome checks.

    Rules:   Rates and impression shares are never mixed or averaged; only Google Search rows. Weekly comparisons only
             from native custom/search_prominence_weekly rows with both sides >= min_impressions, else Info unsupported.
             Declines are Info; Warning only via ai_review with ctx.mature True and a declared tolerance in percentage
             points. Below profile visibility targets → Info, never a bid proposal.
    """
    daily_needs = {DAILY: ["campaign_id", "ad_group_id", "date", "network", "impressions", *METRICS,
                           "rate_counting_basis", "share_censoring"]}
    _daily_native(ctx, daily_needs)
    _counting_basis(ctx, daily_needs)
    weekly = _weekly_comparison(ctx)
    _target_gap(ctx, weekly)
    _goal_context(ctx)
    _position_outcomes(ctx)


def _search_daily(ctx) -> tuple[dict, int]:
    by_c: dict[str, list[dict]] = {}
    excluded = 0
    for r in ctx.rows(DAILY):
        if not _network_ok(r):
            excluded += 1
            continue
        by_c.setdefault(str(r.get("campaign_id")), []).append(r)
    for rows in by_c.values():
        rows.sort(key=lambda r: (str(r.get("date")), str(r.get("ad_group_id"))))
    return by_c, excluded


def _daily_native(ctx, needs) -> None:
    """Step 1: native daily served rates and eligible shares, reported separately."""
    chk = ctx.check("daily_native_metrics", "Native daily prominence rates vs eligible top shares", needs)
    if not chk.runnable:
        return
    by_c, excluded = _search_daily(ctx)
    if excluded:
        chk.partial(f"{excluded} non-Google-Search or unknown-network rows excluded (partner position data unsupported)")
    invalid = 0
    for cid in sorted(by_c):
        rows = by_c[cid]
        dates = sorted({V.parse_date(r.get("date")) for r in rows} - {None})
        summary = {}
        for m in METRICS:
            vals = [ctx.rate(r.get(m)) for r in rows]
            known = [v for v in vals if v is not None]
            summary[m] = {"known_days": len(known), "unknown_or_censored": len(vals) - len(known),
                          "min": min(known) if known else None, "max": max(known) if known else None}
        for r in rows:
            top, abs_top = ctx.rate(r.get("top_impression_rate")), ctx.rate(r.get("absolute_top_impression_rate"))
            ts, ats = ctx.rate(r.get("search_top_impression_share")), ctx.rate(r.get("search_absolute_top_impression_share"))
            vals = [v for v in (top, abs_top, ts, ats) if v is not None]
            if any(v < 0 or v > 1 for v in vals) or (top is not None and abs_top is not None and abs_top > top) \
                    or (ts is not None and ats is not None and ats > ts):
                invalid += 1
        chk.observe(f"Campaign {cid}: native daily rates and shares (not averaged, not weighted)", campaign_id=cid,
                    days=len(dates), first_date=dates[0] if dates else None, last_date=dates[-1] if dates else None,
                    rows=len(rows), metrics=summary,
                    note="rates = served-impression prominence; shares = estimated eligible top opportunities")
    if invalid:
        chk.partial(f"{invalid} rows with out-of-range values or absolute-top above top; values kept as supplied")


def _counting_basis(ctx, needs) -> None:
    """Step 2: native counting conventions; daily rows cannot build weekly rates without compatible weights."""
    chk = ctx.check("counting_basis", "Native counting basis and weekly aggregation support", needs)
    if not chk.runnable:
        return
    by_c, _ = _search_daily(ctx)
    weekly_present = ctx.table(WEEKLY) is not None
    for cid in sorted(by_c):
        rows = by_c[cid]
        bases = sorted({str(r.get("rate_counting_basis")) for r in rows if r.get("rate_counting_basis")})
        censoring = sorted({str(r.get("share_censoring")) for r in rows if r.get("share_censoring")})
        entity = {"campaign_id": cid}
        if len(bases) > 1:
            chk.finding("incompatible_counting_bases", "Info", entity,
                        f"Campaign {cid} mixes {len(bases)} rate counting bases across daily rows; rates are not comparable",
                        evidence={"rate_counting_basis": bases, "share_censoring": censoring, "file": DAILY},
                        recommendation="Re-export with one native counting convention before comparing periods.",
                        uncertainty="Differences may reflect counting conventions, not visibility changes.")
        weeks = sorted({V.parse_date(r.get("date")).isocalendar()[:2] for r in rows if V.parse_date(r.get("date"))})
        if not weekly_present and len(weeks) >= 2:
            dates = sorted({V.parse_date(r.get("date")) for r in rows} - {None})
            chk.finding("weekly_aggregate_unsupported", "Info", entity,
                        f"Campaign {cid}: {len(dates)} daily native rows span {len(weeks)} weeks, but no native weekly "
                        f"report or compatible counting-basis weights were supplied; weekly rates/shares are unavailable "
                        f"and daily rates were not averaged or weighted by campaign impressions",
                        evidence={"rate_counting_basis": bases, "share_censoring": censoring, "daily_days": len(dates),
                                  "window": [dates[0], dates[-1]], "weeks_spanned": len(weeks),
                                  "weekly_file_present": False, "compatible_weights_supplied": False,
                                  "missing": f"{WEEKLY}:period_start,period_end,{','.join(METRICS)}"},
                        recommendation="Export each complete comparison week natively from Ads "
                                       f"({WEEKLY}) before any weekly trend statement; keep daily rates descriptive.",
                        uncertainty="No weekly decline or improvement is established from daily rows.")
        chk.observe(f"Campaign {cid}: counting bases recorded", campaign_id=cid, rate_counting_basis=bases,
                    share_censoring=censoring, weekly_file_present=weekly_present)
    chk.partial("source-compatible numerator/denominator weights are not a declared input; daily→weekly aggregation unsupported")


def _week_rows(ctx) -> tuple[dict, int]:
    """(campaign, ad_group, network) → {period_start: row} for complete native 7-day weeks."""
    grains: dict[tuple, dict] = {}
    rejected = 0
    for r in ctx.rows(WEEKLY):
        if not _network_ok(r):
            rejected += 1
            continue
        s, e = V.parse_date(r.get("period_start")), V.parse_date(r.get("period_end"))
        if s is None or e is None or (e - s).days != 6 or (ctx.snapshot and e >= ctx.snapshot):
            rejected += 1
            continue
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id") or ""), str(r.get("network")).upper())
        if s in grains.setdefault(key, {}):
            rejected += 1
            continue
        grains[key][s] = r
    return grains, rejected


def _weekly_comparison(ctx) -> dict:
    """Step 3+4: latest vs preceding native complete week; decline vs declared tolerance."""
    chk = ctx.check("weekly_comparison", "Native complete-week prominence comparison",
                    {WEEKLY: ["campaign_id", "ad_group_id", "network", "period_start", "period_end", "impressions",
                              *METRICS]})
    latest: dict = {}
    if not chk.runnable:
        return latest
    mi = ctx.params.get("min_impressions")
    grains, rejected = _week_rows(ctx)
    if rejected:
        chk.partial(f"{rejected} weekly rows excluded (non-Search network, not a complete 7-day week, "
                    f"not ended before snapshot, or duplicate grain)")
    if ctx.mature is not True:
        chk.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): decline Warning path disabled, descriptive only")
    for key in sorted(grains):
        weeks = grains[key]
        starts = sorted(weeks)
        cid, gid, net = key
        latest[key] = weeks[starts[-1]]
        if len(starts) < 2:
            chk.observe(f"{cid}/{gid}: only one complete native week", campaign_id=cid, ad_group_id=gid, network=net)
            continue
        cur_s, prev_s = starts[-1], starts[-2]
        if (cur_s - prev_s).days != 7:
            chk.observe(f"{cid}/{gid}: latest weeks not adjacent; no comparison", campaign_id=cid, ad_group_id=gid,
                        weeks=[prev_s, cur_s])
            continue
        cur, prev = weeks[cur_s], weeks[prev_s]
        ci, pi = V.num(cur.get("impressions")), V.num(prev.get("impressions"))
        entity = {"campaign_id": cid, "ad_group_id": gid, "network": net}
        base_ev = {"current_week": [cur_s, V.parse_date(cur.get("period_end"))],
                   "previous_week": [prev_s, V.parse_date(prev.get("period_end"))],
                   "current_impressions": ci, "previous_impressions": pi,
                   "min_impressions": mi.value, "min_impressions_source": mi.source}
        if ci is None or pi is None or mi.value is None or ci < mi.value or pi < mi.value:
            chk.observe(f"{cid}/{gid}: week comparison below min_impressions on at least one side", **entity, **base_ev)
            continue
        diffs = {}
        for m in METRICS:
            c, p = ctx.rate(cur.get(m)), ctx.rate(prev.get(m))
            if c is None or p is None:
                diffs[m] = {"current": c, "previous": p, "pp_change": None, "relative_change": None}
                continue
            diffs[m] = {"current": c, "previous": p, "pp_change": round((c - p) * 100, 6),
                        "relative_change": V.ratio(c - p, p)}
        chk.observe(f"{cid}/{gid}: native weekly change (percentage points; relative separate)", **entity,
                    **base_ev, changes=diffs)
        declines = {m: -d["pp_change"] for m, d in diffs.items() if d["pp_change"] is not None and d["pp_change"] < 0}
        if not declines:
            continue
        tol, tol_src = _tolerance(ctx, cid)
        ev = {**base_ev, "changes": diffs, "decline_pp": declines, "tolerance_pp": tol, "tolerance_source": tol_src,
              "mature": ctx.mature, "maturity_note": ctx.maturity_note}
        if tol is None:
            chk.finding("prominence_decline_no_tolerance", "Info", entity,
                        f"{cid}/{gid}: native prominence declined week over week "
                        f"({', '.join(f'{m} -{v:.2f}pp' for m, v in sorted(declines.items()))}) but no client "
                        f"visibility tolerance is declared", evidence=ev,
                        recommendation="Declare a visibility tolerance and goal before judging the decline.",
                        uncertainty="Visibility is not profitability; decline alone is not a defect.")
            continue
        over = {m: v for m, v in declines.items() if v > tol}
        if not over or ctx.mature is not True:
            continue
        prov = chk.finding("prominence_decline_exceeds_tolerance", "Info", entity,
                           f"{cid}/{gid}: native weekly decline exceeds tolerance {tol:g}pp "
                           f"({', '.join(f'{m} -{v:.2f}pp' for m, v in sorted(over.items()))})",
                           evidence=ev,
                           recommendation="Confirm the stated visibility goal before any investigation or test.",
                           uncertainty="Rates/shares do not diagnose competitors or justify bid increases.")
        obj = _campaign_objective(ctx, cid)
        chk.review("prominence_decline_exceeds_tolerance", entity,
                   f"Does the {cid}/{gid} prominence decline beyond {tol:g}pp conflict with a stated client "
                   f"visibility goal for this campaign?",
                   evidence={**ev, "profile_objectives": ctx.profile.get("objectives"), "campaign_objective": obj,
                             "brand_terms": ctx.profile.get("brand_terms")},
                   outcomes={
                       "conflicts_visibility_goal": {"severity": "Warning", "recommendation":
                                                     "Investigate via skill-121/skill-039; propose a controlled "
                                                     "visibility/economics test only if the goal requires it."},
                       "no_goal_conflict": {"severity": None, "recommendation": "Record descriptively; no action."},
                       "uncertain": {"severity": "Info", "recommendation": "Ask the client for the visibility goal."},
                   },
                   guidance="Only an explicit profile/client visibility goal counts; no universal 80% brand rule. "
                            "Visibility is not profitable performance.",
                   provisional=prov)
    return latest


def _target_gap(ctx, latest: dict) -> None:
    """#25 (clean-room, read-only): latest native weekly share vs profile target share; no bid logic."""
    chk = ctx.check("visibility_target_gap", "Native share vs client-declared visibility target (#25, no bids)",
                    {WEEKLY: ["campaign_id", "ad_group_id", "network", "period_start", "period_end", "impressions",
                              *SHARES]})
    if not chk.runnable:
        return
    targets = {}
    for (cid, gid, net) in sorted(latest):
        obj = _campaign_objective(ctx, cid)
        for m, key in _TARGETS.items():
            t = V.num(obj.get(key))
            if t is not None and 0 < t <= 1:
                targets[(cid, gid, net, m)] = (t, f"profile.campaign_objectives[{cid}].{key}")
    if not targets:
        chk.skip("no profile visibility share targets declared",
                 ["profile.campaign_objectives[*].target_search_top_impression_share"])
        return
    mi = ctx.params.get("min_impressions")
    for (cid, gid, net, m) in sorted(targets):
        t, src = targets[(cid, gid, net, m)]
        row = latest[(cid, gid, net)]
        imp, share = V.num(row.get("impressions")), ctx.rate(row.get(m))
        entity = {"campaign_id": cid, "ad_group_id": gid, "network": net, "metric": m}
        ev = {"week": [V.parse_date(row.get("period_start")), V.parse_date(row.get("period_end"))],
              "impressions": imp, "share": share, "target": t, "target_source": src,
              "min_impressions": mi.value, "share_censoring": row.get("share_censoring")}
        if share is None or imp is None or mi.value is None or imp < mi.value:
            chk.observe(f"{cid}/{gid} {m}: share unknown/censored or below min_impressions", **entity, **ev)
            continue
        gap = round((t - share) * 100, 6)
        if gap > 0:
            chk.finding("below_visibility_target", "Info", entity,
                        f"{cid}/{gid}: native {m} {share:.2%} is {gap:.2f}pp below the declared target {t:.2%}",
                        evidence={**ev, "gap_pp": gap},
                        recommendation="Investigate lost share via skill-121; no automatic bid change "
                                       "(the #25 bid-to-share logic is intentionally not applied).",
                        uncertainty="A share gap does not establish profitability or competitor behaviour.")
        else:
            chk.observe(f"{cid}/{gid} {m} meets declared target", **entity, **ev, gap_pp=gap)


def _goal_context(ctx) -> None:
    """Step 4: economics context for campaigns with prominence data; descriptive, sample-gated."""
    chk = ctx.check("goal_context", "Campaign goal CPA/ROAS context for prominence campaigns",
                    {"campaign_metrics": ["campaign_id", "clicks", "cost", "conversions", "conversion_value"]})
    if not chk.runnable:
        return
    scope = {str(r.get("campaign_id")) for r in ctx.rows(DAILY)} | {str(r.get("campaign_id")) for r in ctx.rows(WEEKLY)}
    if not scope:
        chk.skip("no prominence evidence to contextualize", [f"{DAILY} (file)", f"{WEEKLY} (file)"])
        return
    mc = ctx.params.get("min_conversions")
    if ctx.mature is not True:
        chk.partial(f"maturity {ctx.mature}: CPA/ROAS descriptive only")
    agg: dict[str, list] = {}
    for r in ctx.rows("campaign_metrics"):
        cid = str(r.get("campaign_id"))
        if cid not in scope:
            continue
        a = agg.setdefault(cid, [0.0, 0.0, 0.0, 0.0, 0])
        for i, (col, fn) in enumerate((("clicks", V.num), ("cost", ctx.money), ("conversions", V.num),
                                       ("conversion_value", ctx.money))):
            v = fn(r.get(col))
            if v is None:
                a[4] += 1
            else:
                a[i] += v
    for cid in sorted(agg):
        clicks, cost, conv, value, unknown = agg[cid]
        gated = mc.value is not None and conv >= mc.value
        cpa, cpa_src = ctx.params.target_cpa(cid)
        chk.observe(f"Campaign {cid}: economics context (visibility is not profitability)", campaign_id=cid,
                    clicks=clicks, cost=cost, conversions=conv, conversion_value=value, unknown_cells=unknown,
                    cpa=V.ratio(cost, conv) if gated else None, roas=V.ratio(value, cost) if gated else None,
                    min_conversions=mc.value, target_cpa=cpa, target_cpa_source=cpa_src,
                    visibility_tolerance=_tolerance(ctx, cid)[0])


def _position_outcomes(ctx) -> None:
    """Step 5: only real position-segment reports; descriptive and non-causal."""
    chk = ctx.check("position_outcomes", "Supplied position-segment outcomes (descriptive)",
                    {POSITION: ["campaign_id", "date", "position_segment", "segment_definition", "impressions",
                                "clicks", "cost", "conversions", "conversion_value"]})
    if not chk.runnable:
        return
    mi, mcl, mc = (ctx.params.get(p) for p in ("min_impressions", "min_clicks", "min_conversions"))
    agg: dict[tuple, list] = {}
    for r in ctx.rows(POSITION):
        key = (str(r.get("campaign_id")), str(r.get("position_segment")))
        a = agg.setdefault(key, [0.0, 0.0, 0.0, 0.0, set()])
        a[0] += V.num(r.get("impressions")) or 0
        a[1] += V.num(r.get("clicks")) or 0
        a[2] += ctx.money(r.get("cost")) or 0
        a[3] += V.num(r.get("conversions")) or 0
        a[4].add(str(r.get("segment_definition")))
    for key in sorted(agg):
        imp, clk, cost, conv, defs = agg[key]
        chk.observe(f"Campaign {key[0]} segment {key[1]}: descriptive position outcome (not causal)",
                    campaign_id=key[0], position_segment=key[1], segment_definition=sorted(defs),
                    impressions=imp, clicks=clk, cost=cost, conversions=conv,
                    ctr=V.ratio(clk, imp) if mi.value and imp >= mi.value else None,
                    cvr=V.ratio(conv, clk) if mcl.value and clk >= mcl.value and ctx.mature is True else None,
                    cpa=V.ratio(cost, conv) if mc.value and conv >= mc.value and ctx.mature is True else None)


def verify(ctx, item, decision) -> list[str]:
    """Rules: a Warning decision must cite the stated visibility goal it conflicts with (proposal.goal_ref)."""
    if decision.get("outcome") == "conflicts_visibility_goal" and not (decision.get("proposal") or {}).get("goal_ref"):
        return ["conflicts_visibility_goal needs proposal.goal_ref naming the stated client visibility goal"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
