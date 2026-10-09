"""check.py — skill-066 deterministic historical Quality Score transitions on a stable matched keyword cohort.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-066-historical-quality-score-trend/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #92 Alert keywords that fall from 10/10 quality score (dougwithseismic/ppc-scripts) — clean-room
         reimplementation of "keyword that held QS 10 no longer does" as the Info check perfect_qs_lost,
         computed from native daily history instead of a script-maintained spreadsheet of past scores.
rules:   Source is custom/quality_score_history (source=native_historical) OR, only when it is absent,
         custom/quality_score_snapshots (source=current_snapshot) — never mixed; snapshot comparisons are labeled.
         Entity key = account_id/campaign_id/ad_group_id/criterion_id; joins never use keyword text.
         Identical duplicate key/date rows are deduplicated; conflicting ones are excluded and reported (Info).
         Windows: profile.quality_trend_windows {baseline: [start, end], comparison: [start, end]} else two equal
         halves of the observed native date span (snapshots: first vs last snapshot date). Each side uses the
         keyword's LAST non-null rating inside the window; no fill, no carry-over across gaps.
         Warning only for a matched >=2 point decline or Average/Above→Below Average component with
         comparison-window cost >= spend_significant resolved for THAT campaign; otherwise Info. Never Critical.
         Averages compare the SAME matched cohort, unweighted by impressions. Change history is a hypothesis only.
         CTR/CVR/CPA side comparisons need both sides to pass min_impressions/min_clicks/min_conversions;
         CVR/CPA additionally need ctx.mature True.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial deterministic check
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

SKILL = "skill-066-historical-quality-score-trend"
VERSION = "1.0.0"

KEY = ("account_id", "campaign_id", "ad_group_id", "criterion_id")
COMPONENTS = ("historical_expected_ctr", "historical_ad_relevance", "historical_landing_page_experience")
RATINGS = ("BELOW_AVERAGE", "AVERAGE", "ABOVE_AVERAGE")
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
_IGNORED_FOR_DUPES = ("extracted_at", "captured_at")


def _rating(v) -> str | None:
    s = "_".join(str(v or "").strip().upper().replace("-", " ").split())
    return s if s in RATINGS else None


def _qs(v) -> int | None:
    n = V.num(v)
    return int(n) if n is not None and n == int(n) and 1 <= n <= 10 else None


def _digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isalnum()).lower()


def _windows(ctx, dates: list, snapshots: bool):
    """Return ((b_start, b_end), (c_start, c_end), basis) or (None, None, reason)."""
    w = ctx.profile.get("quality_trend_windows")
    if isinstance(w, dict) and w.get("baseline") and w.get("comparison"):
        try:
            b = tuple(V.parse_date(x) for x in w["baseline"])
            c = tuple(V.parse_date(x) for x in w["comparison"])
        except TypeError:
            return None, None, "profile.quality_trend_windows must be {baseline: [start, end], comparison: [start, end]}"
        if len(b) != 2 or len(c) != 2 or None in b + c or b[0] > b[1] or c[0] > c[1] or b[1] >= c[0]:
            return None, None, "profile.quality_trend_windows invalid: need ordered, non-overlapping date pairs"
        return b, c, "profile.quality_trend_windows"
    distinct = sorted(set(dates))
    if len(distinct) < 2:
        return None, None, f"only {len(distinct)} distinct observation date(s): no trend"
    if snapshots:
        return (distinct[0], distinct[0]), (distinct[-1], distinct[-1]), "first vs last snapshot date"
    d0, d1 = distinct[0], distinct[-1]
    n = ((d1 - d0).days + 1) // 2
    return (d0, d0 + timedelta(days=n - 1)), (d1 - timedelta(days=n - 1), d1), f"equal {n}-day halves of {d0}..{d1}"


def _side(rows: list[dict], ctx) -> dict:
    """Last non-null ratings and summed metrics for one entity inside one window (rows sorted by date)."""
    out = {"rows": len(rows), "qs": None, "qs_date": None, "status": None}
    for r in rows:
        q = _qs(r.get("historical_quality_score"))
        if q is not None:
            out["qs"], out["qs_date"] = q, r["_date"]
        for comp in COMPONENTS:
            rt = _rating(r.get(comp))
            if rt is not None:
                out[comp], out[comp + "_date"] = rt, r["_date"]
        if r.get("keyword_status") is not None:
            out["status"] = str(r.get("keyword_status")).upper()
    for m in METRICS:
        vals = [ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m)) for r in rows]
        known = [v for v in vals if v is not None]
        out[m] = sum(known) if known else None
        out[m + "_unknown_rows"] = len(vals) - len(known)
    return out


def run(ctx) -> None:
    """Run matched-cohort Quality Score and component trend checks between baseline and comparison windows.

    Rules:   Native history OR snapshots, never mixed; joins by criterion keys, never keyword text; conflicting rows →
             Info. Warning only for a matched >= 2-point decline or component falling to Below Average with comparison
             cost >= spend_significant of THAT campaign; otherwise Info. Never Critical. CTR/CVR/CPA sides need min
             samples; CVR/CPA also need ctx.mature True. Change history is a hypothesis only.
    """
    hist, snap = ctx.table("custom/quality_score_history"), ctx.table("custom/quality_score_snapshots")
    snapshots = hist is None and snap is not None
    key = "custom/quality_score_snapshots" if snapshots else "custom/quality_score_history"
    date_col = "snapshot_date" if snapshots else "date"
    want = "current_snapshot" if snapshots else "native_historical"
    base_cols = [*KEY, date_col, "historical_quality_score", "source"]
    src = ctx.check("history_source", "Validate QS history source, dates and entity/date key uniqueness",
                    {key: base_cols})
    downstream = (("window_selection", "Baseline and comparison windows"),
                  ("matched_cohort", "Matched cohort with entrants, exits and null transitions"),
                  ("qs_point_transitions", "Matched keyword QS point declines"),
                  ("component_transitions", "Component transitions to Below Average"),
                  ("perfect_qs_lost", "Keywords that lost a 10/10 Quality Score"),
                  ("cohort_breakdown", "Transition counts and coverage by campaign, match type and ad group"),
                  ("current_inventory", "History entities versus current keyword inventory"),
                  ("change_history_context", "Change history near transitions (hypotheses only)"),
                  ("business_metric_comparison", "Gated CTR/CVR/CPA comparison for flagged keywords"))
    if not src.runnable:
        for cid, title in downstream:
            ctx.check(cid, title).skip("QS history unavailable: no trend (use 064/065 for current diagnostics)",
                                       src.missing)
        return
    label = "current_snapshot (captured current values, not native history)" if snapshots else "native_historical"
    if hist is not None and snap is not None:
        src.partial("custom/quality_score_snapshots ignored: native history and snapshots are never mixed")

    acct = _digits(ctx.account_id)
    missing_ids = wrong_source = bad_date = other_account = 0
    grouped: dict[tuple, list[dict]] = {}
    for r in ctx.rows(key):
        ids = tuple(str(r.get(k) or "").strip() for k in KEY)
        if not all(ids):
            missing_ids += 1
            continue
        if acct and _digits(ids[0]) != acct:
            other_account += 1
            continue
        if str(r.get("source") or "").strip().lower() != want:
            wrong_source += 1
            continue
        d = V.parse_date(r.get(date_col))
        if d is None:
            bad_date += 1
            continue
        grouped.setdefault((ids, d), []).append(r)
    by_entity: dict[tuple, list[dict]] = {}
    conflicts: list[dict] = []
    dupes = 0
    for (ids, d), rows in sorted(grouped.items()):
        sigs = {tuple(sorted((k, str(v)) for k, v in r.items() if k not in _IGNORED_FOR_DUPES)) for r in rows}
        if len(sigs) > 1:
            conflicts.append({"campaign_id": ids[1], "ad_group_id": ids[2], "criterion_id": ids[3], "date": d})
            continue
        dupes += len(rows) - 1
        by_entity.setdefault(ids, []).append({**rows[0], "_date": d})
    src.observe("History rows validated", source=label, entities=len(by_entity), identical_duplicates_dropped=dupes,
                conflicting_key_dates=len(conflicts), rows_missing_ids=missing_ids, rows_wrong_source=wrong_source,
                rows_bad_date=bad_date, rows_other_account=other_account)
    if wrong_source:
        src.partial(f"{wrong_source} rows excluded: source is not '{want}'")
    if bad_date:
        src.partial(f"{bad_date} rows excluded: unparseable {date_col}")
    if other_account:
        src.partial(f"{other_account} rows excluded: account_id differs from account.customer_id")
    if missing_ids:
        src.finding("history_missing_ids", "Info", {"table": key},
                    f"{missing_ids} history rows lack account/campaign/ad-group/criterion IDs and were excluded",
                    evidence={"rows_missing_ids": missing_ids, "table": key},
                    recommendation="Re-export with all four IDs; text-only joins are not used.",
                    uncertainty="Excluded rows may hold transitions that are not assessed.")
    if conflicts:
        src.finding("history_conflicting_rows", "Info", {"table": key},
                    f"{len(conflicts)} entity/date keys have conflicting values and were excluded",
                    evidence={"conflicts": conflicts},
                    recommendation="Reconcile the source export for these keys before comparing them.",
                    uncertainty="Excluded dates may contain the observation that defines a transition.")

    # -- step 2: windows
    win = ctx.check("window_selection", "Baseline and comparison windows")
    all_dates = [r["_date"] for rows in by_entity.values() for r in rows]
    base_w, comp_w, basis = _windows(ctx, all_dates, snapshots)
    if base_w is None:
        win.skip(basis)
        for cid, title in downstream[1:]:
            ctx.check(cid, title).skip(f"no comparable windows: {basis}")
        return
    win.observe("Comparison windows", baseline=list(base_w), comparison=list(comp_w), basis=basis, source=label)

    sides: dict[tuple, dict] = {}
    for ids, rows in sorted(by_entity.items()):
        rows.sort(key=lambda r: r["_date"])
        b = [r for r in rows if base_w[0] <= r["_date"] <= base_w[1]]
        c = [r for r in rows if comp_w[0] <= r["_date"] <= comp_w[1]]
        last = rows[-1]
        sides[ids] = {"b": _side(b, ctx) if b else None, "c": _side(c, ctx) if c else None,
                      "text": last.get("keyword_text"), "match": str(last.get("match_type") or "").upper() or None}

    # -- step 3: matched cohort
    coh = ctx.check("matched_cohort", "Matched cohort with entrants, exits and null transitions")
    groups = {"entrants": [], "exits": [], "null_to_rated": [], "rated_to_null": [], "unrated_both": [],
              "paused_or_removed": []}
    matched: list[tuple] = []
    for ids, s in sorted(sides.items()):
        ref = "/".join(ids[1:])
        b, c = s["b"], s["c"]
        if b is None and c is None:
            continue
        if b is None:
            groups["entrants"].append(ref)
        elif c is None:
            groups["exits"].append(ref)
        elif b["qs"] is None and c["qs"] is not None:
            groups["null_to_rated"].append(ref)
        elif b["qs"] is not None and c["qs"] is None:
            groups["rated_to_null"].append(ref)
        elif b["qs"] is None:
            groups["unrated_both"].append(ref)
        else:
            matched.append(ids)
        if c is not None and c["status"] not in (None, "ENABLED"):
            groups["paused_or_removed"].append(ref)
    universe = sum(1 for s in sides.values() if s["b"] is not None or s["c"] is not None)
    coh.observe("Matched cohort coverage", matched=len(matched), entities_in_windows=universe,
                matched_share=V.ratio(len(matched), universe), **{k: len(v) for k, v in groups.items()})
    unmatched = {k: v for k, v in groups.items() if v and k != "paused_or_removed"}
    if unmatched:
        coh.finding("cohort_unmatched", "Info", {"cohort": f"{base_w[0]}..{comp_w[1]}"},
                    f"{sum(len(v) for v in unmatched.values())} keywords are outside the matched cohort "
                    f"({', '.join(f'{k}={len(v)}' for k, v in sorted(unmatched.items()))})",
                    evidence={"source": label, "baseline": list(base_w), "comparison": list(comp_w),
                              "matched": len(matched), "denominator": universe,
                              **{k: v for k, v in sorted(unmatched.items())}},
                    recommendation="Report these separately; they cannot show a within-keyword transition.",
                    uncertainty="Entrants/exits are cohort changes, not quality deterioration.")

    # -- step 4: QS point and component transitions
    pts = ctx.check("qs_point_transitions", "Matched keyword QS point declines", {key: [*KEY, date_col, "cost"]})
    comp_chk = ctx.check("component_transitions", "Component transitions to Below Average",
                         {key: [*KEY, date_col, "cost"]})
    tbl = ctx.table(key)
    present_components = [c for c in COMPONENTS if c in tbl.columns]
    if comp_chk.runnable and len(present_components) < len(COMPONENTS):
        comp_chk.partial("missing component columns block only those components' transitions",
                         [f"{key}:{c}" for c in COMPONENTS if c not in tbl.columns])
    flagged: dict[tuple, list[str]] = {}
    unresolved: set[str] = set()
    counts = {"decline_2plus": 0, "decline_1": 0, "stable": 0, "improved": 0}
    comp_counts = {c: 0 for c in present_components}

    def _materiality(ids, cost):
        thr = ctx.params.get("spend_significant", ids[1])
        if thr.value is None:
            unresolved.add(f"{ids[1]}: {thr.reason}")
        material = cost is not None and thr.value is not None and cost >= thr.value
        return thr, material

    def _entity(ids):
        return {"account_id": ids[0], "campaign_id": ids[1], "ad_group_id": ids[2], "criterion_id": ids[3]}

    for ids in matched:
        s = sides[ids]
        b, c = s["b"], s["c"]
        cost = c["cost"]
        delta = c["qs"] - b["qs"]
        common = {"source": label, "keyword_text": s["text"], "match_type": s["match"],
                  "baseline_window": list(base_w), "comparison_window": list(comp_w),
                  "comparison_window_cost": cost, "cost_unknown_rows": c["cost_unknown_rows"],
                  "matched_cohort_denominator": len(matched), "maturity": ctx.mature}
        if pts.runnable:
            if delta <= -2:
                counts["decline_2plus"] += 1
                thr, material = _materiality(ids, cost)
                flagged.setdefault(ids, []).append(f"qs {b['qs']}->{c['qs']}")
                sev = "Warning" if material else "Info"
                pts.finding("qs_point_decline", sev, _entity(ids),
                            f"Keyword '{s['text']}' ({s['match']}) QS {b['qs']} on {b['qs_date']} → {c['qs']} on "
                            f"{c['qs_date']} ({delta:+d} points); comparison-window cost {cost}",
                            evidence={**common, "baseline_qs": b["qs"], "baseline_date": b["qs_date"],
                                      "comparison_qs": c["qs"], "comparison_date": c["qs_date"],
                                      "from_perfect_qs": b["qs"] == 10},
                            calculation={"delta_points": delta, "threshold": "spend_significant",
                                         "threshold_value": thr.value, "threshold_source": thr.source or thr.reason,
                                         "cost_basis": f"sum of comparison-window cost {comp_w[0]}..{comp_w[1]}"},
                            recommendation="Investigate via 067/068/069 and change history; no automatic bid, "
                                           "pause or score-uplift forecast.",
                            uncertainty="QS is diagnostic; a decline does not prove CTR/CPA/ROAS decline or cause. "
                                        + ("" if material else "Materiality not met or unresolved."))
            elif delta == -1:
                counts["decline_1"] += 1
            elif delta == 0:
                counts["stable"] += 1
            else:
                counts["improved"] += 1
        if comp_chk.runnable:
            for comp in present_components:
                bb, cc = b.get(comp), c.get(comp)
                if bb in ("AVERAGE", "ABOVE_AVERAGE") and cc == "BELOW_AVERAGE":
                    comp_counts[comp] += 1
                    thr, material = _materiality(ids, cost)
                    flagged.setdefault(ids, []).append(f"{comp} {bb}->{cc}")
                    comp_chk.finding("component_became_below_average", "Warning" if material else "Info",
                                     {**_entity(ids), "component": comp},
                                     f"Keyword '{s['text']}' {comp} {bb} on {b[comp + '_date']} → BELOW_AVERAGE on "
                                     f"{c[comp + '_date']}; comparison-window cost {cost}",
                                     evidence={**common, "baseline_rating": bb, "baseline_date": b[comp + "_date"],
                                               "comparison_rating": cc, "comparison_date": c[comp + "_date"]},
                                     calculation={"threshold": "spend_significant", "threshold_value": thr.value,
                                                  "threshold_source": thr.source or thr.reason},
                                     recommendation="Route to 067 (expected CTR), 068 (ad relevance) or 069 "
                                                    "(landing page) for owner-reviewed diagnostics.",
                                     uncertainty="Component ratings are relative diagnostics, not causal evidence.")
    for u in sorted(unresolved):
        for chk in (pts, comp_chk):
            if chk.runnable:
                chk.partial(f"spend_significant unresolved for campaign {u}; declines reported as Info")
    if pts.runnable:
        pts.observe("QS point transitions on the matched cohort", matched=len(matched), **counts)
    if comp_chk.runnable:
        comp_chk.observe("Component transitions to Below Average on matched ratings", **comp_counts)

    # -- index #92: keywords that lost a 10/10 QS (1-point cases; >=2 already carry from_perfect_qs)
    perf = ctx.check("perfect_qs_lost", "Keywords that lost a 10/10 Quality Score")
    lost = 0
    for ids in matched:
        s = sides[ids]
        b, c = s["b"], s["c"]
        if b["qs"] == 10 and c["qs"] == 9:
            lost += 1
            perf.finding("perfect_qs_lost", "Info", _entity(ids),
                         f"Keyword '{s['text']}' held QS 10 on {b['qs_date']} and QS 9 on {c['qs_date']}",
                         evidence={"source": label, "baseline_qs": 10, "baseline_date": b["qs_date"],
                                   "comparison_qs": 9, "comparison_date": c["qs_date"],
                                   "comparison_window_cost": c["cost"]},
                         recommendation="Monitor; check recent ad/landing-page changes before acting.",
                         uncertainty="A 1-point change is below the recipe's 2-point review cutoff.")
    perf.observe("Matched keywords rated 10 at baseline", rated_10=sum(1 for i in matched if sides[i]["b"]["qs"] == 10),
                 lost_to_9=lost)

    # -- step 5: breakdowns on the SAME matched cohort
    brk = ctx.check("cohort_breakdown", "Transition counts and coverage by campaign, match type and ad group")
    for dim, pick in (("campaign_id", lambda i: i[1]), ("ad_group_id", lambda i: f"{i[1]}/{i[2]}"),
                      ("match_type", lambda i: sides[i]["match"] or "unknown")):
        agg: dict[str, dict] = {}
        for ids, s in sides.items():
            if s["b"] is None and s["c"] is None:
                continue
            a = agg.setdefault(pick(ids), {"entities": 0, "matched": 0, "declines_2plus": 0, "flagged": 0,
                                           "sum_b": 0, "sum_c": 0})
            a["entities"] += 1
            if ids in matched:
                a["matched"] += 1
                a["sum_b"] += s["b"]["qs"]
                a["sum_c"] += s["c"]["qs"]
                a["declines_2plus"] += int(s["c"]["qs"] - s["b"]["qs"] <= -2)
                a["flagged"] += int(ids in flagged)
        for k in sorted(agg):
            a = agg[k]
            brk.observe(f"{dim} {k}: matched-cohort QS transitions", dimension=dim, value=k, entities=a["entities"],
                        matched=a["matched"], coverage=V.ratio(a["matched"], a["entities"]),
                        declines_2plus=a["declines_2plus"], flagged=a["flagged"],
                        mean_qs_baseline=V.ratio(a["sum_b"], a["matched"]),
                        mean_qs_comparison=V.ratio(a["sum_c"], a["matched"]))

    # -- inventory context
    inv = ctx.check("current_inventory", "History entities versus current keyword inventory",
                    {"keywords": ["id", "campaign_id", "ad_group_id", "status"]})
    if inv.runnable:
        cur = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in ctx.rows("keywords")}
        absent, inactive, differs = [], [], 0
        for ids in sorted(sides):
            k = cur.get(ids[1:])
            if k is None:
                absent.append("/".join(ids[1:]))
                continue
            if str(k.get("status") or "").upper() not in ("ENABLED", ""):
                inactive.append("/".join(ids[1:]))
            last = sides[ids]["c"]["qs"] if sides[ids]["c"] else None
            if last is not None and _qs(k.get("quality_score")) not in (None, last):
                differs += 1
        inv.observe("History entities joined to current inventory by IDs", history_entities=len(sides),
                    absent_from_inventory=absent, paused_or_removed_now=inactive,
                    current_qs_differs_from_last_history=differs,
                    note="current quality_info is a snapshot, not historical QS")

    # -- step 6: change history hypotheses
    chg = ctx.check("change_history_context", "Change history near transitions (hypotheses only)",
                    {"custom/quality_change_history": ["campaign_id", "ad_group_id", "criterion_id_or_ad_id",
                                                       "changed_at", "field"]})
    if chg.runnable:
        changes = ctx.rows("custom/quality_change_history")
        for ids in sorted(flagged):
            b, c = sides[ids]["b"], sides[ids]["c"]
            lo, hi = b["qs_date"] or base_w[0], c["qs_date"] or comp_w[1]
            near = []
            for r in changes:
                d = V.parse_date(str(r.get("changed_at") or "")[:10])
                if (str(r.get("campaign_id")) == ids[1] and str(r.get("ad_group_id") or ids[2]) == ids[2]
                        and d is not None and lo < d <= hi):
                    near.append({"changed_at": r.get("changed_at"), "field": r.get("field"),
                                 "entity": r.get("criterion_id_or_ad_id"), "previous_value": r.get("previous_value"),
                                 "new_value": r.get("new_value")})
            chg.observe(f"Changes between rated dates for {'/'.join(ids[1:])} (hypothesis, not cause)",
                        campaign_id=ids[1], ad_group_id=ids[2], criterion_id=ids[3], transitions=flagged[ids],
                        interval=[lo, hi], changes=sorted(near, key=lambda x: str(x["changed_at"])))

    # -- step 7: gated business metrics
    bus = ctx.check("business_metric_comparison", "Gated CTR/CVR/CPA comparison for flagged keywords",
                    {key: [*KEY, date_col, "impressions", "clicks", "cost", "conversions"]})
    if bus.runnable:
        mi, mc, mv = (ctx.params.get(n).value for n in ("min_impressions", "min_clicks", "min_conversions"))
        if ctx.mature is not True:
            bus.partial(f"CVR/CPA not compared: maturity={ctx.mature} ({ctx.maturity_note})")
        for ids in sorted(flagged):
            b, c = sides[ids]["b"], sides[ids]["c"]
            out = {"campaign_id": ids[1], "ad_group_id": ids[2], "criterion_id": ids[3]}
            if (b["impressions"] or 0) >= mi and (c["impressions"] or 0) >= mi:
                out["ctr"] = [V.ratio(b["clicks"], b["impressions"]), V.ratio(c["clicks"], c["impressions"])]
            else:
                out["ctr"] = f"not compared: impressions below {mi} on a side"
            if ctx.mature is True and (b["clicks"] or 0) >= mc and (c["clicks"] or 0) >= mc:
                out["cvr"] = [V.ratio(b["conversions"], b["clicks"]), V.ratio(c["conversions"], c["clicks"])]
            if ctx.mature is True and (b["conversions"] or 0) >= mv and (c["conversions"] or 0) >= mv:
                out["cpa"] = [V.ratio(b["cost"], b["conversions"]), V.ratio(c["cost"], c["conversions"])]
            bus.observe(f"Baseline vs comparison metrics for {'/'.join(ids[1:])} (QS decline alone proves no KPI decline)",
                        **out, gates={"min_impressions": mi, "min_clicks": mc, "min_conversions": mv})


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
