"""check.py — skill-128 deterministic PMax campaign/group/channel review with honest reporting coverage.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-128-performance-max-channel-performance/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #66 ChoppyMax Monitor (nilsrooijmans.com, reference only; code unverified) — clean-room reimplementation
         of the per-channel cost/impression share view, only from a supplied pmax_channels report; nothing is reconstructed
         index #75 PMax Shopping Spend Drop Alert (nilsrooijmans.com) — clean-room reimplementation of a last-7 versus
         prior-7 complete-day channel cost comparison; Info only and only with profile.pmax_channel_drop_threshold
rules:   PMax = campaigns.channel_type PERFORMANCE_MAX, paused campaigns included. Campaign totals from
         campaign_metrics are the authoritative layer; segmented reports are never summed into them.
         Groups are left-joined from custom/pmax_groups to custom/pmax_group_daily. Unreported (no rows), zero
         performance (rows with 0 impressions) and reporting groups stay distinct. Ad Strength is descriptive only.
         Channel rows are summed only when mutually exclusive (unique campaign/date|window/channel/format/goal key). Rows
         named total/all are excluded. Coverage = summed channel cost / campaign cost; unavailable segments stay unknown.
         Objective screen (groups and channels): ctx.mature True, a single goal_set_id per campaign, conversions >=
         min_conversions and a resolved target CPA (ctx.params.target_cpa) or target ROAS. Miss → Warning. Mixed goals →
         no ranking.
         Zero-conversion spend >= spend_floor: Warning only via review, offered when ctx.mature is True and
         ctx.tracking_for_campaign is True; otherwise Info naming the gate.
         PMax versus Search: an observation only when goal_set_id, market, segment_definition and the profile role match.
         Otherwise an Info finding with no verdict. Placement impressions are exposure only.
         Channel spend drop needs profile.pmax_channel_drop_threshold (0<t<1); no hardcoded tolerance.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
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

SKILL = "skill-128-performance-max-channel-performance"
VERSION = "1.0.0"

GROUPS = "custom/pmax_groups"
GDAILY = "custom/pmax_group_daily"
CHANNELS = "custom/pmax_channels"
PLACEMENTS = "custom/pmax_placements"
SEGMENTS = "custom/pmax_comparison_segments"
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
_TOTAL = ("total", "all", "all channels", "campaign total")


def _metrics(ctx, r) -> dict:
    return {m: (ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))) for m in METRICS}


def _add(acc: dict, vals: dict) -> None:
    for m in METRICS:
        v = vals.get(m)
        acc[m] = None if acc.get(m, 0.0) is None or v is None else acc.get(m, 0.0) + v


def _target_roas(ctx, cid: str) -> tuple[float | None, str]:
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None) or {}
    t = V.num(row.get("target_roas"))
    if t and t > 0:
        return t, f"campaigns.target_roas[{cid}]"
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    t = V.num(obj.get("target_roas")) if isinstance(obj, dict) else None
    return (t, f"profile.campaign_objectives[{cid}].target_roas") if t and t > 0 else (None, "no applicable target ROAS")


def _objective(ctx, cid: str) -> dict:
    cpa, csrc = ctx.params.target_cpa(cid)
    roas, rsrc = (None, "") if cpa is not None else _target_roas(ctx, cid)
    return {"target_cpa": cpa, "target_cpa_source": csrc, "target_roas": roas, "target_roas_source": rsrc}


def _role(ctx, cid: str):
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    return obj.get("role") if isinstance(obj, dict) else None


def run(ctx) -> None:
    """Run PMax campaign totals, group inventory, channel coverage/drop, outcome, Search-comparison and placement checks.

    Rules:   No PERFORMANCE_MAX campaign → all checks not_applicable. Objective-miss Warning needs ctx.mature True, one
             goal_set_id, params min_conversions and target CPA/ROAS; zero-conversion spend >= spend_floor goes to
             ai_review (Warning) only when mature and tracked, else Info. Channel drop is Info only with
             profile.pmax_channel_drop_threshold; coverage, Search comparison and placements are observe/Info, no verdict.
    """
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns")}
    pmax = sorted(c for c, r in camps.items() if str(r.get("channel_type") or "").upper() == "PERFORMANCE_MAX")
    applicable = bool(pmax) or ctx.table("campaigns") is None
    summary = ctx.check("campaign_summary", "PMax campaign outcomes (authoritative layer)",
                        {"campaigns": ["id", "channel_type"], "campaign_metrics": ["campaign_id", *METRICS]},
                        applicable=applicable, na_reason="no PERFORMANCE_MAX campaign in campaigns")
    ids = ("group_inventory", "channel_reconciliation", "outcome_screen", "search_comparison", "placement_exposure")
    if not applicable:
        for i in ids:
            ctx.check(i, i.replace("_", " ")).not_applicable("no PERFORMANCE_MAX campaign in campaigns")
        return
    totals: dict[str, dict] = {}
    if summary.runnable:
        for r in ctx.rows("campaign_metrics"):
            cid = str(r.get("campaign_id"))
            if cid in pmax:
                _add(totals.setdefault(cid, {}), _metrics(ctx, r))
        if ctx.mature is not True:
            summary.partial(f"maturity: {ctx.maturity_note}; outcomes descriptive only")
        for cid in pmax:
            t = totals.get(cid)
            if t is None:
                summary.partial(f"campaign {cid}: no campaign_metrics rows")
                continue
            summary.observe(f"PMax campaign {cid}: totals", campaign_id=cid, status=camps[cid].get("status"), **t,
                            cpa=V.ratio(t["cost"], t["conversions"]), roas=V.ratio(t["conversion_value"], t["cost"]),
                            window=[ctx.period_start, ctx.period_end], objective=_objective(ctx, cid),
                            goal_ids=ctx.goal_ids(cid), mature=ctx.mature)

    last = min(d for d in (ctx.as_of, ctx.snapshot - timedelta(days=1) if ctx.snapshot else None) if d) \
        if (ctx.as_of or ctx.snapshot) else None
    mature_day = (lambda d: ctx.lag_days is not None and ctx.snapshot is not None
                  and d + timedelta(days=ctx.lag_days) <= ctx.snapshot)

    # -- step 2: group inventory left-joined to metrics
    ginv = ctx.check("group_inventory", "Asset-group inventory left-joined to metrics",
                     {GROUPS: ["campaign_id", "asset_group_id", "status"],
                      GDAILY: ["campaign_id", "asset_group_id", "date", "goal_set_id", *METRICS]})
    units: list[dict] = []
    if ginv.runnable and last:
        start = last - timedelta(days=29)
        agg: dict[tuple, dict] = {}
        goals: dict[tuple, set] = {}
        immature = 0
        for r in ctx.rows(GDAILY):
            d = V.parse_date(r.get("date"))
            if d is None or not (start <= d <= last):
                continue
            if not mature_day(d):
                immature += 1
                continue
            k = (str(r.get("campaign_id")), str(r.get("asset_group_id")))
            _add(agg.setdefault(k, {}), _metrics(ctx, r))
            goals.setdefault(k, set()).add(str(r.get("goal_set_id") or ""))
        if immature:
            ginv.partial(f"{immature} group-day rows inside the conversion lag excluded")
        states = {"reporting": 0, "zero_performance": 0, "unreported": 0}
        strength: dict[str, int] = {}
        seen_c = set()
        for g in sorted(ctx.rows(GROUPS), key=lambda r: (str(r.get("campaign_id")), str(r.get("asset_group_id")))):
            k = (str(g.get("campaign_id")), str(g.get("asset_group_id")))
            seen_c.add(k[0])
            strength[str(g.get("ad_strength") or "unknown")] = strength.get(str(g.get("ad_strength") or "unknown"), 0) + 1
            m = agg.get(k)
            state = "unreported" if m is None else "zero_performance" if m.get("impressions") == 0 else "reporting"
            states[state] += 1
            ginv.observe(f"Group {k[1]} (campaign {k[0]}): {state}", campaign_id=k[0], asset_group_id=k[1],
                         status=g.get("status"), primary_status=g.get("primary_status"), ad_strength=g.get("ad_strength"),
                         state=state, metrics=m, goal_set_ids=sorted(goals.get(k, set())), window=[start, last])
            if m is not None:
                units.append({"kind": "group", "campaign_id": k[0], "id": k[1], "metrics": m, "goals": goals.get(k, set())})
        orphan = sorted(k for k in agg if k not in {(str(g.get("campaign_id")), str(g.get("asset_group_id"))) for g in ctx.rows(GROUPS)})
        if orphan:
            ginv.partial(f"{len(orphan)} metric groups missing from the pmax_groups inventory")
        no_groups = sorted(c for c in pmax if c not in seen_c)
        ginv.observe("Group inventory totals (Ad Strength descriptive only; structure → skill-089/162)", **states,
                     ad_strength=strength, pmax_campaigns_without_groups=no_groups,
                     inventory_certified=ctx.table(GROUPS).complete is True)
    elif ginv.runnable:
        ginv.skip("report end unknown", ["account:date_range_end"])

    # -- step 3: channel reconciliation, share (index #66) and spend drop (index #75)
    chan = ctx.check("channel_reconciliation", "Reported channels: exclusivity and coverage",
                     {CHANNELS: ["campaign_id", "reported_channel", "reported_format", "goal_set_id", "impressions",
                                 "cost", "conversions"]})
    if chan.runnable:
        t = ctx.table(CHANNELS)
        dated = "date" in t.columns
        if not dated and t.missing(["report_start", "report_end"]):
            chan.partial("channel rows have neither date nor report_start/report_end", [f"{CHANNELS}:date"])
        keys, dup, excluded = set(), 0, 0
        by_c: dict[str, dict] = {}
        by_unit: dict[tuple, dict] = {}
        goals_c: dict[str, set] = {}
        unavailable = 0
        daily_cost: dict[tuple, dict] = {}
        for r in sorted(t.rows, key=lambda r: tuple(str(r.get(c)) for c in ("campaign_id", "date", "reported_channel", "reported_format"))):
            cid = str(r.get("campaign_id"))
            if cid not in pmax:
                continue
            ch = V.norm_text(r.get("reported_channel"))
            if ch in _TOTAL:
                excluded += 1
                continue
            window = r.get("date") if dated else (r.get("report_start"), r.get("report_end"))
            k = (cid, str(window), ch, V.norm_text(r.get("reported_format")), str(r.get("goal_set_id") or ""))
            if k in keys:
                dup += 1
                continue
            keys.add(k)
            if str(r.get("metric_availability") or "available").lower() not in ("available", "complete", "full"):
                unavailable += 1
            vals = _metrics(ctx, r)
            d = V.parse_date(r.get("date")) if dated else None
            if d is not None and not mature_day(d):
                vals = {**vals, "conversions": None, "conversion_value": None}
            _add(by_c.setdefault(cid, {}), vals)
            _add(by_unit.setdefault((cid, ch), {}), vals)
            goals_c.setdefault(cid, set()).add(k[4])
            if d is not None:
                daily_cost.setdefault((cid, ch), {})[d] = (daily_cost.get((cid, ch), {}).get(d) or 0.0) + (vals["cost"] or 0.0)
        if dup:
            chan.partial(f"{dup} duplicate channel keys: rows not mutually exclusive, duplicates not summed")
        if excluded:
            chan.observe("Total/all-channel rows excluded from channel sums", rows=excluded)
        if unavailable:
            chan.partial(f"{unavailable} channel rows with metric_availability not available: retained as unknown")
        for cid in sorted(by_c):
            camp_cost = (totals.get(cid) or {}).get("cost")
            shares = {ch: V.ratio(u.get("cost"), by_c[cid].get("cost")) for (c, ch), u in sorted(by_unit.items()) if c == cid}
            chan.observe(f"PMax campaign {cid}: reported channel coverage and cost share (Info only)", campaign_id=cid,
                         channel_cost=by_c[cid].get("cost"), campaign_cost=camp_cost,
                         reported_coverage=V.ratio(by_c[cid].get("cost"), camp_cost), channel_cost_share=shares,
                         interaction_definitions=sorted({str(r.get("interaction_definition")) for r in t.rows
                                                         if str(r.get("campaign_id")) == cid and r.get("interaction_definition")}),
                         note="channels as the supplied report defines them; no reconstruction of missing segments")
        for (cid, ch), u in sorted(by_unit.items()):
            units.append({"kind": "channel", "campaign_id": cid, "id": ch, "metrics": u, "goals": goals_c.get(cid, set())})
        drop_t = V.num(ctx.profile.get("pmax_channel_drop_threshold"))
        drop_t = drop_t if drop_t is not None and 0 < drop_t < 1 else None
        if dated and last:
            if drop_t is None:
                chan.partial("channel spend-drop screen off: profile.pmax_channel_drop_threshold not declared")
            for (cid, ch), days in sorted(daily_cost.items()):
                cur = [days.get(last - timedelta(days=i)) for i in range(7)]
                pri = [days.get(last - timedelta(days=i)) for i in range(7, 14)]
                if any(v is None for v in cur + pri):
                    continue
                change = V.ratio(sum(cur) - sum(pri), sum(pri))
                chan.observe(f"{cid} {ch}: last-7 versus prior-7 reported cost", campaign_id=cid, channel=ch,
                             current=sum(cur), prior=sum(pri), change=change)
                if drop_t is not None and change is not None and change < -drop_t:
                    chan.finding("channel_spend_drop", "Info", {"campaign_id": cid, "channel": ch},
                                 f"PMax {cid} reported {ch} cost fell {change:+.0%} (last 7 vs prior 7 complete days)",
                                 evidence={"current_7d": sum(cur), "prior_7d": sum(pri), "threshold": drop_t,
                                           "threshold_source": "profile.pmax_channel_drop_threshold",
                                           "window": [last - timedelta(days=13), last]},
                                 recommendation="Check feed/product availability and serving changes; monitoring only.",
                                 uncertainty="Channel allocation is automated; a drop is not a failure by itself.")

    # -- step 4: outcome screen against the campaign objective
    screen = ctx.check("outcome_screen", "Group/channel outcomes against the economic objective")
    if not units:
        screen.skip("no group or channel outcome rows", [*ginv.missing, *chan.missing])
    min_conv = ctx.params.get("min_conversions")
    if units and ctx.mature is not True:
        screen.partial(f"maturity {ctx.mature}: objective screen and zero-conversion Warning path disabled")
    for u in sorted(units, key=lambda u: (u["kind"], u["campaign_id"], u["id"])):
        cid, m = u["campaign_id"], u["metrics"]
        goals = u["goals"] - {""}
        entity = {"campaign_id": cid, u["kind"]: u["id"]}
        obj = _objective(ctx, cid)
        ev = {**m, "kind": u["kind"], "goal_set_ids": sorted(goals), "objective": obj, "min_conversions": min_conv.value,
              "window": [ctx.period_start, ctx.period_end], "cpa": V.ratio(m.get("cost"), m.get("conversions")),
              "roas": V.ratio(m.get("conversion_value"), m.get("cost"))}
        if len(goals) > 1:
            screen.partial(f"campaign {cid} {u['kind']} {u['id']}: mixed goal sets {sorted(goals)}; not ranked by raw CPA")
            continue
        conv, cost = m.get("conversions"), m.get("cost")
        if conv == 0 and cost is not None:
            floor = ctx.params.get("spend_floor", cid)
            if floor.value is None or cost < floor.value:
                continue
            tracked, note = ctx.tracking_for_campaign(cid)
            ev.update({"spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": note})
            if ctx.mature is not True or tracked is not True:
                screen.finding("zero_conversion_spend_gated", "Info", entity,
                               f"PMax {cid} {u['kind']} {u['id']}: {cost:.2f} {ctx.currency} with 0 conversions; Warning "
                               f"path blocked (maturity {ctx.mature}, tracking {tracked})", evidence=ev,
                               recommendation="Establish maturity and goal tracking before any relevance review.",
                               uncertainty="Zero conversions can reflect tracking gaps, lag or assisted value.")
                continue
            prov = screen.finding("zero_conversion_spend", "Info", entity,
                                  f"PMax {cid} {u['kind']} {u['id']}: {cost:.2f} {ctx.currency} with 0 conversions "
                                  f"(floor {floor.value:g})", evidence=ev,
                                  recommendation="Relevance/business-role review; no automatic pause or allocation rule.",
                                  uncertainty="Historical spend is exposure, not savings.")
            screen.review("zero_conversion_spend", entity,
                          f"Is the zero-conversion {u['kind']} spend of PMax {cid} ({u['id']}) unexplained by its role?",
                          evidence=ev, provisional=prov,
                          outcomes={"unexplained_zero_conversion": {"severity": "Warning", "recommendation":
                                    "Investigate with the owner; route structure to skill-089, placements to skill-115."},
                                    "explained_by_role": {"severity": None, "recommendation": "Document the role."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask for the channel/group role."}},
                          guidance="Judge only with profile objectives and campaign role; no fixed allocation rules.")
            continue
        if ctx.mature is not True or min_conv.value is None or conv is None or conv < min_conv.value:
            continue
        miss = None
        if obj["target_cpa"] is not None and ev["cpa"] is not None and ev["cpa"] > obj["target_cpa"]:
            miss = f"CPA {ev['cpa']:.2f} > target {obj['target_cpa']:g}"
        elif obj["target_roas"] is not None and ev["roas"] is not None and ev["roas"] < obj["target_roas"]:
            miss = f"ROAS {ev['roas']:.2f} < target {obj['target_roas']:g}"
        elif obj["target_cpa"] is None and obj["target_roas"] is None:
            screen.partial(f"campaign {cid}: no approved economic objective ({obj['target_cpa_source']}; {obj['target_roas_source']})")
        if miss:
            screen.finding(f"{u['kind']}_objective_miss", "Warning", entity,
                           f"PMax {cid} {u['kind']} {u['id']}: {miss} with {conv:g} mature conversions", evidence=ev,
                           recommendation="Review with the owner; structural/creative follow-up belongs to skill-089/162, "
                                          "placements to skill-115. No per-channel bidding control is implied.",
                           uncertainty="Observational outcome; automated allocation means no marginal-return claim.")

    # -- step 5: PMax versus Search only within aligned segments
    comp = ctx.check("search_comparison", "PMax versus Search within aligned goals/markets/roles",
                     {"campaigns": ["id", "channel_type"], "campaign_metrics": ["campaign_id", "cost", "conversions"]})
    if comp.runnable:
        search = sorted(c for c, r in camps.items() if str(r.get("channel_type") or "").upper() == "SEARCH")
        seg_t = ctx.table(SEGMENTS)
        seg_cols = ["campaign_id", "goal_set_id", "market", "segment_definition", "cost", "conversions"]
        if seg_t is None or seg_t.missing(seg_cols):
            comp.partial("no comparable segment report: separate totals only, no performance verdict",
                         [f"{SEGMENTS} (file)"] if seg_t is None else [f"{SEGMENTS}:{c}" for c in seg_t.missing(seg_cols)])
            sums = {}
            for r in ctx.rows("campaign_metrics"):
                cid = str(r.get("campaign_id"))
                kind = "pmax" if cid in pmax else "search" if cid in search else None
                if kind:
                    _add(sums.setdefault(kind, {}), _metrics(ctx, r))
            comp.observe("Separate PMax and Search totals (no verdict)", **{k: v for k, v in sorted(sums.items())})
        else:
            segs: dict[tuple, dict] = {}
            for r in seg_t.rows:
                cid = str(r.get("campaign_id"))
                kind = "pmax" if cid in pmax else "search" if cid in search else None
                if kind:
                    k = (kind, cid, str(r.get("goal_set_id")), V.norm_text(r.get("market")), V.norm_text(r.get("segment_definition")))
                    _add(segs.setdefault(k, {}), _metrics(ctx, r))
            for pk, pm in sorted((k, v) for k, v in segs.items() if k[0] == "pmax"):
                for sk, sm in sorted((k, v) for k, v in segs.items() if k[0] == "search"):
                    aligned = pk[2:] == sk[2:] and _role(ctx, pk[1]) is not None and _role(ctx, pk[1]) == _role(ctx, sk[1])
                    sample = min_conv.value is not None and all((x.get("conversions") or 0) >= min_conv.value for x in (pm, sm))
                    ev = {"pmax_segment": list(pk[1:]), "search_segment": list(sk[1:]), "pmax": pm, "search": sm,
                          "pmax_cpa": V.ratio(pm.get("cost"), pm.get("conversions")),
                          "search_cpa": V.ratio(sm.get("cost"), sm.get("conversions")), "aligned": aligned,
                          "sample_ok": sample, "roles": [_role(ctx, pk[1]), _role(ctx, sk[1])]}
                    if aligned:
                        comp.observe(f"Aligned PMax {pk[1]} / Search {sk[1]} segment comparison (observational)", **ev,
                                     note="not incrementality or cannibalization; overlap hypotheses → skill-094")
                    elif sample and pk[3:] == sk[3:]:
                        comp.finding("pmax_search_unaligned_comparison", "Info",
                                     {"pmax_campaign_id": pk[1], "search_campaign_id": sk[1], "market": pk[3]},
                                     f"PMax {pk[1]} vs Search {sk[1]} CPA differs but goals/roles are not aligned",
                                     evidence=ev, recommendation="Show separate totals; no performance verdict.",
                                     uncertainty="Different goals, brand/customer mix or roles make CPA incomparable.")

    # -- step 6: placement exposure only
    plc = ctx.check("placement_exposure", "Placement impressions as exposure",
                    {PLACEMENTS: ["campaign_id", "placement_type", "impressions"]})
    if plc.runnable:
        agg: dict[tuple, float | None] = {}
        for r in ctx.rows(PLACEMENTS):
            k = (str(r.get("campaign_id")), str(r.get("placement_type")))
            v = V.num(r.get("impressions"))
            agg[k] = None if agg.get(k, 0.0) is None or v is None else agg.get(k, 0.0) + v
        for (cid, typ), v in sorted(agg.items()):
            plc.observe(f"PMax {cid} {typ}: placement impressions (exposure only; decisions → skill-115)",
                        campaign_id=cid, placement_type=typ, impressions=v,
                        note="no cost/conversion allocation from campaign totals")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
