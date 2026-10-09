"""check.py — skill-064 deterministic Quality Score distribution, spend exposure and alert planning.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-064-quality-score-distribution-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #93 Low Quality Score Alert (Brainlabs) — clean-room reimplementation of the "QS <= threshold
         with enough impressions" alert as request-only Info alert candidates (no labels, no pausing).
         index #103 Keyword Performance Report (Google) — clean-room reimplementation of the per-QS-bucket
         impressions/clicks/CTR/avg CPC/cost summary as descriptive observations.
rules:   Universe = enabled Search keywords in enabled ad groups/campaigns from keywords+ad_groups+campaigns,
         never metric rows; paused/removed/other-channel keywords are counted separately.
         QS valid only as integer 1..10; empty → N/A, anything else → invalid; never 0.
         keyword_metrics joins on (campaign_id, ad_group_id, keyword_id|criterion_id|id); duplicate rows at the
         criterion(+date) grain are excluded, not summed. Unmatched keywords cost 0 only when the keyword_metrics
         manifest certifies completeness; otherwise unknown and the exposure check is partial.
         Cost is CURRENT-SNAPSHOT exposure (period cost × current rating), never savings or a CPC multiplier.
         Warning only for the Thresholds rows (QS 1-3 ≥ spend_significant, QS 4-5 ≥ spend_material, Below
         Average component ≥ spend_significant), thresholds resolved per campaign. One Warning per keyword
         (a weak-component Warning is not added where a QS Warning already exists). No Critical path.
         Business-outcome comparisons need ctx.mature True and ≥ min_conversions; observations only.
         Historical declines are routed to skill-066 as observations, never duplicated as findings.
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

SKILL = "skill-064-quality-score-distribution-analysis"
VERSION = "1.0.0"

BUCKETS = ("1-3", "4-5", "6-7", "8-10", "N/A")
COMPONENTS = ("expected_ctr", "ad_relevance", "landing_page_experience")
_KM_ID = ("keyword_id", "criterion_id", "id")


def _up(v) -> str:
    return str(v or "").strip().upper()


def _qs(v) -> tuple[int | None, str]:
    """(score, state) with state valid|na|invalid."""
    if V.num(v) is None:
        return (None, "na") if str(v or "").strip().lower() in V.MISSING_TOKENS else (None, "invalid")
    i = V.integer(v)
    return (i, "valid") if i is not None and 1 <= i <= 10 else (None, "invalid")


def _bucket(score: int | None) -> str:
    if score is None:
        return "N/A"
    return "1-3" if score <= 3 else "4-5" if score <= 5 else "6-7" if score <= 7 else "8-10"


def _km_id(ctx) -> str:
    t = ctx.table("keyword_metrics")
    return next((c for c in _KM_ID if t is not None and c in t.columns), _KM_ID[0])


def _universe(ctx) -> tuple[dict, dict, list[str]]:
    """(eligible keywords by key, excluded counts, notes). Key = (campaign_id, ad_group_id, keyword_id)."""
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns")}
    groups = {str(r.get("id")): r for r in ctx.rows("ad_groups")}
    eligible, excluded, notes = {}, {}, []
    for k in sorted(ctx.rows("keywords"), key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("id")))):
        cid, gid = str(k.get("campaign_id")), str(k.get("ad_group_id"))
        key = (cid, gid, str(k.get("id")))
        camp, grp = camps.get(cid), groups.get(gid)
        if camp is None or grp is None:
            reason = "parent campaign/ad group not in inventory"
        elif _up(camp.get("channel_type")) != "SEARCH":
            reason = f"channel {camp.get('channel_type') or 'unknown'} (QS applies to Search keywords)"
        elif _up(k.get("status")) != "ENABLED" or _up(grp.get("status")) != "ENABLED" or _up(camp.get("status")) != "ENABLED":
            reason = "paused/removed keyword, ad group or campaign"
        else:
            eligible[key] = k
            continue
        excluded[reason] = excluded.get(reason, 0) + 1
    if excluded.get("parent campaign/ad group not in inventory"):
        notes.append(f"{excluded['parent campaign/ad group not in inventory']} keywords have no parent in "
                     "campaigns/ad_groups; their eligibility is unknown")
    return eligible, excluded, notes


def _costs(ctx) -> tuple[dict, list[str]]:
    """Per-criterion summed metrics {key: {impressions, clicks, cost, conversions, value}} and problems."""
    idc = _km_id(ctx)
    t = ctx.table("keyword_metrics")
    has_date = "date" in t.columns
    seen, dup, out, problems = set(), set(), {}, []
    for r in t.rows:
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get(idc)))
        grain = key + ((str(r.get("date")),) if has_date else ())
        if grain in seen:
            dup.add(key)
        seen.add(grain)
        acc = out.setdefault(key, {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0,
                                   "conversion_value": 0.0, "unknown": []})
        for col in ("impressions", "clicks", "cost", "conversions", "conversion_value"):
            v = ctx.money(r.get(col)) if col in ("cost", "conversion_value") else V.num(r.get(col))
            if v is None:
                acc["unknown"].append(col)
            else:
                acc[col] += v
    for key in sorted(dup):
        out.pop(key, None)
        problems.append(f"keyword_metrics duplicate rows at criterion grain {key}; cost excluded, not summed")
    return out, problems


def run(ctx) -> None:
    """Run keyword universe, QS buckets, spend exposure, low-QS/weak-component priority, outcomes and alert checks.

    Rules:   Missing campaigns/ad_groups/keywords inventory skips all checks. Warning only when period cost ≥
             spend_significant (QS 1-3, Below Average component) or spend_material (QS 4-5) per campaign; one per
             keyword. N/A QS and min_impressions alert candidates → Info. Outcomes need ctx.mature True and
             min_conversions, observations only; QS history declines route to skill-066. No ai_review, no Critical.
    """
    # -- step 1: keyword universe
    uni = ctx.check("keyword_universe", "Eligible Search keyword universe from inventory",
                    {"campaigns": ["id", "status", "channel_type"], "ad_groups": ["id", "campaign_id", "status"],
                     "keywords": ["id", "campaign_id", "ad_group_id", "status"]})
    dependent = (("qs_buckets", "QS bucket counts and availability"),
                 ("spend_exposure", "Current-snapshot spend exposure by QS bucket"),
                 ("low_qs_priority", "Low-QS spend-priority review"),
                 ("weak_component_exposure", "Weak component with significant spend"),
                 ("business_outcomes", "Low-QS keyword business outcomes (mature samples)"),
                 ("alert_plan", "Request-only low-QS alert candidates and history routing"))
    if not uni.runnable:
        for cid, title in dependent:
            ctx.check(cid, title).skip("keyword universe unavailable", uni.missing)
        return
    eligible, excluded, notes = _universe(ctx)
    for n in notes:
        uni.partial(n)
    uni.observe("Keyword universe", eligible_enabled_search=len(eligible), excluded=excluded,
                keywords_total=len(ctx.rows("keywords")))

    # -- steps 2-3: buckets
    bk = ctx.check("qs_buckets", "QS bucket counts and availability", {"keywords": ["quality_score"]})
    scores: dict = {}
    if bk.runnable:
        counts = {b: 0 for b in BUCKETS}
        invalid = []
        for key, k in eligible.items():
            s, state = _qs(k.get("quality_score"))
            if state == "invalid":
                invalid.append(key[2])
            scores[key] = s
            counts[_bucket(s)] += 1
        total, rated = len(eligible), len(eligible) - counts["N/A"]
        bk.observe("QS bucket distribution (all eligible keywords incl. N/A)", denominator_all=total,
                   denominator_rated=rated, counts=counts,
                   share_all={b: V.ratio(counts[b], total) for b in BUCKETS},
                   share_rated={b: V.ratio(counts[b], rated) for b in BUCKETS if b != "N/A"},
                   availability=V.ratio(rated, total), invalid_source_values=invalid)
        if counts["N/A"]:
            na_ids = sorted(k[2] for k, s in scores.items() if s is None)
            bk.finding("qs_unavailable", "Info", {"account_id": ctx.account_id, "bucket": "N/A"},
                       f"{counts['N/A']} of {total} eligible keywords have no valid current QS",
                       evidence={"keyword_ids": na_ids, "invalid_source_values": invalid},
                       calculation={"numerator": counts["N/A"], "denominator": total},
                       recommendation="Keep N/A separate; low-volume or new keywords may not have a rating.",
                       uncertainty="Unavailable is not zero and not low quality.")

    # -- step 4: exposure
    idc = _km_id(ctx)
    ex = ctx.check("spend_exposure", "Current-snapshot spend exposure by QS bucket",
                   {"keywords": ["quality_score"],
                    "keyword_metrics": ["campaign_id", "ad_group_id", idc, "impressions", "clicks", "cost"]})
    metrics: dict = {}
    if ex.runnable:
        metrics, problems = _costs(ctx)
        for p in problems:
            ex.partial(p)
        km_complete = ctx.table("keyword_metrics").complete is True
        agg = {b: {"keywords": 0, "impressions": 0.0, "clicks": 0.0, "cost": 0.0} for b in BUCKETS}
        unknown_cost = []
        for key in eligible:
            m = metrics.get(key)
            if m is None:
                if not km_complete:
                    unknown_cost.append(key[2])
                    continue
                m = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "unknown": []}
                metrics[key] = m
            if "cost" in m["unknown"]:
                unknown_cost.append(key[2])
                continue
            a = agg[_bucket(scores.get(key))]
            a["keywords"] += 1
            for col in ("impressions", "clicks", "cost"):
                a[col] += m[col]
        if unknown_cost:
            ex.partial(f"{len(unknown_cost)} eligible keywords with unknown cost (no complete metric row)")
        total_cost = sum(a["cost"] for a in agg.values())
        for b in BUCKETS:
            a = agg[b]
            ex.observe(f"QS bucket {b}: CURRENT-SNAPSHOT exposure", bucket=b, keywords=a["keywords"],
                       cost=a["cost"], cost_share=V.ratio(a["cost"], total_cost), impressions=a["impressions"],
                       clicks=a["clicks"], ctr=V.ratio(a["clicks"], a["impressions"]),
                       avg_cpc=V.ratio(a["cost"], a["clicks"]), window=[ctx.period_start, ctx.period_end],
                       snapshot=ctx.snapshot, currency=ctx.currency)
        paused_cost = sum(m["cost"] for k, m in metrics.items() if k not in eligible)
        ex.observe("Spend of non-eligible (paused/removed/other) criteria in the window", cost=paused_cost,
                   denominator_eligible_cost=total_cost, unknown_cost_keywords=sorted(unknown_cost))

    # -- step 5: prioritization
    pr = ctx.check("low_qs_priority", "Low-QS spend-priority review",
                   {"keywords": ["quality_score"],
                    "keyword_metrics": ["campaign_id", "ad_group_id", idc, "cost"]})
    flagged: set = set()
    if pr.runnable and ex.runnable:
        unresolved = set()
        for key in sorted(eligible):
            s, m = scores.get(key), metrics.get(key)
            if s is None or s > 5 or m is None or "cost" in m["unknown"]:
                continue
            pname = "spend_significant" if s <= 3 else "spend_material"
            p = ctx.params.get(pname, key[0])
            if p.value is None:
                unresolved.add(f"{pname} for campaign {key[0]}: {p.reason}")
                continue
            if m["cost"] < p.value:
                continue
            k = eligible[key]
            weak = [c for c in COMPONENTS if _up(k.get(c)) == "BELOW_AVERAGE"]
            flagged.add(key)
            pr.finding("low_qs_" + ("1_3" if s <= 3 else "4_5") + "_cost", "Warning",
                       {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]},
                       f"Keyword {key[2]} '{k.get('text')}' has current QS {s} and {m['cost']:.2f} {ctx.currency} "
                       f"period cost >= {pname} {p.value:g}",
                       evidence={"quality_score": s, "cost": m["cost"], "window": [ctx.period_start, ctx.period_end],
                                 "snapshot": ctx.snapshot, "weak_components": weak,
                                 "components": {c: k.get(c) for c in COMPONENTS}},
                       calculation={"threshold": pname, "threshold_value": p.value, "threshold_source": p.source,
                                    "basis": "CURRENT-SNAPSHOT rating × period cost"},
                       recommendation="Open a diagnostic review (components via skill-065; CTR/relevance/LP via "
                                      "067/068/069). Do not pause to raise the score.",
                       uncertainty="Current rating joined to period cost; exposure is not savings or lost profit.")
        for u in sorted(unresolved):
            pr.partial(u)
    elif pr.runnable:
        pr.skip("spend exposure unavailable", ex.missing)

    wc = ctx.check("weak_component_exposure", "Weak component with significant spend",
                   {"keywords": list(COMPONENTS), "keyword_metrics": ["campaign_id", "ad_group_id", idc, "cost"]})
    if wc.runnable and ex.runnable:
        unresolved = set()
        for key in sorted(eligible):
            k, m = eligible[key], metrics.get(key)
            weak = [c for c in COMPONENTS if _up(k.get(c)) == "BELOW_AVERAGE"]
            if not weak or key in flagged or m is None or "cost" in m["unknown"]:
                continue
            p = ctx.params.get("spend_significant", key[0])
            if p.value is None:
                unresolved.add(f"spend_significant for campaign {key[0]}: {p.reason}")
                continue
            if m["cost"] >= p.value:
                flagged.add(key)
                wc.finding("weak_component_cost", "Warning",
                           {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]},
                           f"Keyword {key[2]} has Below Average {', '.join(weak)} with {m['cost']:.2f} "
                           f"{ctx.currency} period cost >= spend_significant {p.value:g}",
                           evidence={"weak_components": weak, "quality_score": scores.get(key), "cost": m["cost"]},
                           calculation={"threshold_value": p.value, "threshold_source": p.source},
                           recommendation="Route the component review to skill-065.",
                           uncertainty="Component ratings are diagnostic, not causal weights.")
        for u in sorted(unresolved):
            wc.partial(u)
    elif wc.runnable:
        wc.skip("spend exposure unavailable", ex.missing)

    # -- step 6: business outcomes for flagged keywords
    bo = ctx.check("business_outcomes", "Low-QS keyword business outcomes (mature samples)",
                   {"keyword_metrics": ["campaign_id", "ad_group_id", idc, "cost", "conversions"]})
    if bo.runnable:
        if ctx.mature is not True:
            bo.partial(f"conversion maturity not established ({ctx.maturity_note}); no outcome comparison")
        else:
            min_conv = ctx.params.get("min_conversions")
            insufficient = []
            for key in sorted(flagged):
                m = metrics.get(key) or {}
                conv = m.get("conversions")
                if conv is None or "conversions" in m.get("unknown", []) or conv < (min_conv.value or 0):
                    insufficient.append(key[2])
                    continue
                cpa = V.ratio(m["cost"], conv)
                target, tsrc = ctx.params.target_cpa(key[0])
                bo.observe(f"Keyword {key[2]}: flagged low-QS keyword outcome", keyword_id=key[2], cpa=cpa,
                           conversions=conv, target_cpa=target, target_source=tsrc,
                           within_target=(cpa <= target) if cpa is not None and target else None)
            bo.observe("Flagged keywords below min_conversions (no outcome comparison)", keyword_ids=insufficient,
                       min_conversions=min_conv.value, source=min_conv.source)

    # -- step 7: alert plan (#93) and history routing
    al = ctx.check("alert_plan", "Request-only low-QS alert candidates and history routing",
                   {"keywords": ["quality_score"], "keyword_metrics": ["campaign_id", "ad_group_id", idc, "impressions"]})
    if al.runnable and bk.runnable:
        mi = ctx.params.get("min_impressions")
        low_uncorroborated = []
        for key in sorted(eligible):
            s, m = scores.get(key), metrics.get(key)
            if s is None or s > 3 or key in flagged:
                continue
            low_uncorroborated.append(key[2])
            if m and "impressions" not in m["unknown"] and m["impressions"] >= mi.value:
                al.finding("low_qs_alert_candidate", "Info",
                           {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]},
                           f"Keyword {key[2]} QS {s} with {m['impressions']:g} impressions >= min_impressions "
                           f"{mi.value}: open a diagnostic review",
                           evidence={"quality_score": s, "impressions": m["impressions"], "cost": m["cost"]},
                           calculation={"min_impressions": mi.value, "source": mi.source},
                           recommendation="Request-only alert: owner, weekly snapshot cadence, reset when QS >= 4. "
                                          "Never an automatic bid/pause rule.",
                           uncertainty="Score-only signal without corroborating cost.")
        if low_uncorroborated:
            n_all = len(eligible)
            al.finding("low_qs_share", "Info", {"account_id": ctx.account_id, "bucket": "1-3"},
                       f"{len(low_uncorroborated)} of {n_all} eligible keywords have QS 1-3 without spend corroboration",
                       evidence={"keyword_ids": low_uncorroborated},
                       calculation={"numerator": len(low_uncorroborated), "denominator": n_all,
                                    "share": V.ratio(len(low_uncorroborated), n_all)},
                       recommendation="Monitor; prioritize only if cost or business evidence corroborates.",
                       uncertainty="Count/share only; no economic impact established.")
        hist = ctx.table("custom/quality_score_history")
        need = ["campaign_id", "ad_group_id", "criterion_id", "date", "historical_quality_score"]
        if hist is None or hist.missing(need):
            miss = [f"custom/quality_score_history:{c}" for c in (need if hist is None else hist.missing(need))]
            al.partial("optional QS history absent: historical-decline alerts not evaluated (skill-066)", miss)
        else:
            series: dict = {}
            for r in hist.rows:
                d, s = V.parse_date(r.get("date")), _qs(r.get("historical_quality_score"))[0]
                if d and s is not None:
                    series.setdefault((str(r["campaign_id"]), str(r["ad_group_id"]), str(r["criterion_id"])), []).append((d, s))
            declines = []
            for key in sorted(series):
                pts = sorted(series[key])
                peak = max(s for _, s in pts)
                if peak - pts[-1][1] >= 2:
                    declines.append({"keyword_id": key[2], "peak": peak, "latest": pts[-1][1], "latest_date": pts[-1][0]})
            al.observe("Historical QS declines >= 2 points routed to skill-066 (not duplicated here)",
                       declines=declines, keywords_with_history=len(series))
    elif al.runnable:
        al.skip("QS buckets unavailable", bk.missing)


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
