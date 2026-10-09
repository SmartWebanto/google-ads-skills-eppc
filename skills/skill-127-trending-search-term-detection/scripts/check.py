"""check.py — skill-127 deterministic week-over-week search-term trend screen with coverage and confounder context.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-127-trending-search-term-detection/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #56 Trending Search Terms (nilsrooijmans.com) — clean-room reimplementation of the recent-versus-prior
         period query growth report, inside this recipe's maturity, sample and coverage gates
         index #77 PMax Trending Search Categories — refused: search-category insights are not search-term rows, and this
         recipe declares no search-category input
rules:   Periods: current = 7 days ending at the last mature complete day (min(as_of, snapshot-1, snapshot-lag)),
         prior = the 7 days before. They are equal, weekday-aligned and within the supplied 8-week history.
         Unknown lag → maturity unknown: impression trends only, no decline review.
         Grouping key = (campaign_id, V.norm_text(query)); raw variants, ad-group and matched-keyword IDs are kept.
         growth = current/prior - 1 only when prior > 0. Terms with no earlier row in history are first-reported: absolute
         counts plus earliest date, never infinite growth or proof of market novelty.
         Screen: growth > 0.50 or < -0.30, with impressions >= min_impressions in BOTH periods (strict).
         Growth → Info. Decline → Warning only via review outcome 'serving_risk_identified'. The review needs prior cost
         >= spend_significant for the campaign and unchanged reporting coverage. verify() requires the proposal to cite a
         listed change_id or a current negative that literally blocks the query.
         Existing coverage is literal (adsrun.negatives.blocks), for keywords and effective negatives; no literal keyword
         does not mean missing reach. Additions go to skill-013, negatives to skill-014; nothing is added here.
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
from adsrun.negatives import blocks, effective_negatives  # noqa: E402

SKILL = "skill-127-trending-search-term-detection"
VERSION = "1.0.0"

TREND = "custom/search_trend_daily"
CHANGES = "custom/search_trend_changes"
GROWTH, DECLINE = 0.50, -0.30
METRICS = ("impressions", "clicks", "cost", "conversions")


def _periods(ctx):
    cands = [d for d in (ctx.as_of, ctx.snapshot - timedelta(days=1) if ctx.snapshot else None) if d]
    if not cands:
        return None, "report end and snapshot unknown"
    end = min(cands)
    if ctx.lag_days is not None and ctx.snapshot is not None:
        end = min(end, ctx.snapshot - timedelta(days=ctx.lag_days))
        note = f"mature through {end} (lag {ctx.lag_days}d)"
    else:
        note = "conversion lag unknown: maturity unproven"
    cur = (end - timedelta(days=6), end)
    prior = (end - timedelta(days=13), end - timedelta(days=7))
    return (prior, cur), note


def _changes(ctx, cid: str, start, end) -> list[dict]:
    out = []
    for r in ctx.rows(CHANGES):
        d = V.parse_date(r.get("occurred_at"))
        if str(r.get("campaign_id")) == cid and d and start <= d <= end:
            out.append({"change_id": r.get("change_id"), "occurred_at": d, "changed_field": r.get("changed_field"),
                        "old_value": r.get("old_value"), "new_value": r.get("new_value"), "source": r.get("source")})
    return sorted(out, key=lambda x: (x["occurred_at"], str(x["change_id"])))


def run(ctx) -> None:
    """Run period alignment, growth screen, first-reported terms, confounder and literal coverage checks.

    Rules:   Growth only when prior > 0 and both periods >= min_impressions; first-reported terms are Info, never
             infinite growth. Growth, decline and reporting-coverage changes are Info; decline Warning only via
             ai_review 'serving_risk_identified', emitted when prior cost >= spend_significant and coverage is
             unchanged. Unknown lag → no decline review. Coverage is literal; nothing is added (additions → skill-013,
             negatives → skill-014).
    """
    needs = {TREND: ["campaign_id", "ad_group_id", "query", "date", "matched_keyword_id", "impressions"]}
    align = ctx.check("period_alignment", "Two complete weekday-aligned mature weeks", needs)
    growth = ctx.check("growth", "Growth or first-reported branch per normalized query", needs)
    screen = ctx.check("trend_screen", "Growth/decline screen with both-period impression gates",
                       {TREND: needs[TREND] + ["cost"]})
    conf = ctx.check("confounders", "Budget/serving/matching/reporting changes",
                     {CHANGES: ["campaign_id", "change_id", "occurred_at", "changed_field", "old_value", "new_value"]})
    cover = ctx.check("existing_coverage", "Existing keyword and negative coverage",
                      {"keywords": ["campaign_id", "ad_group_id", "text", "match_type"],
                       "negative_keywords": ["text", "match_type", "level", "campaign_id"], "ad_groups": ["id", "campaign_id"]})
    periods, pnote = _periods(ctx)
    if not align.runnable or periods is None:
        for c in (align, growth, screen, conf, cover):
            if c.runnable:
                c.skip("trend evidence or period end unavailable", align.missing or ["account:date_range_end"])
        return
    (ps, pe), (cs, ce) = periods
    if ctx.lag_days is None or ctx.snapshot is None:
        align.partial(pnote)
    rows = ctx.rows(TREND)
    dates = {V.parse_date(r.get("date")) for r in rows} - {None}
    earliest = min(dates) if dates else None
    missing_days = [ps + timedelta(days=i) for i in range(14) if ps + timedelta(days=i) not in dates]
    if missing_days:
        align.partial(f"{len(missing_days)} of 14 comparison days have no reported rows")
    if earliest is None or earliest > ce - timedelta(days=55):
        align.partial(f"history starts {earliest}; fewer than 8 complete weeks")
    has_cov = "reporting_coverage" in ctx.table(TREND).columns
    cov_by: dict[tuple, set] = {}
    groups: dict[tuple, dict] = {}
    first_seen: dict[tuple, object] = {}
    for r in sorted(rows, key=lambda r: (str(r.get("campaign_id")), str(r.get("date")), str(r.get("query")))):
        d = V.parse_date(r.get("date"))
        if d is None or d > ce:
            continue
        cid, q = str(r.get("campaign_id")), V.norm_text(r.get("query"))
        key = (cid, q)
        first_seen[key] = min(first_seen.get(key, d), d)
        side = "prior" if ps <= d <= pe else "current" if cs <= d <= ce else None
        if side is None:
            continue
        if has_cov:
            cov_by.setdefault((cid, side), set()).add(str(r.get("reporting_coverage") or ""))
        g = groups.setdefault(key, {"prior": {m: 0.0 for m in METRICS}, "current": {m: 0.0 for m in METRICS},
                                    "unknown": set(), "raw": set(), "ad_groups": set(), "keyword_ids": set()})
        g["raw"].add(str(r.get("query")))
        g["ad_groups"].add(str(r.get("ad_group_id")))
        g["keyword_ids"].add(str(r.get("matched_keyword_id")))
        for m in METRICS:
            v = (ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))) if m in r else None
            if v is None:
                g["unknown"].add(f"{side}:{m}")
            else:
                g[side][m] += v
    align.observe("Comparison weeks", prior=[ps, pe], current=[cs, ce], maturity=pnote, history_start=earliest,
                  missing_days=missing_days, groups=len(groups))
    changed_cov = sorted({cid for (cid, side) in cov_by if cov_by.get((cid, "prior")) != cov_by.get((cid, "current"))})
    if not has_cov:
        align.partial(f"{TREND}:reporting_coverage missing: coverage changes unknown")

    # existing coverage (step 5) prepared first so findings can cite it
    scopes, gaps = (effective_negatives(ctx) if cover.runnable else ({}, []))
    for gp in gaps:
        cover.partial(gp)
    kws = [k for k in ctx.rows("keywords") if str(k.get("status") or "ENABLED").upper() == "ENABLED"] if cover.runnable else []

    def coverage(key, g) -> dict:
        if not cover.runnable:
            return {"state": "unknown: " + ", ".join(cover.missing)}
        cid, q = key
        pos = sorted({f"{k.get('text')} ({k.get('match_type')}) kw {k.get('id')}" for k in kws
                      if str(k.get("campaign_id")) == cid and blocks(k.get("text"), k.get("match_type"), q) is True})
        negs = sorted({f"{n.text} ({n.match}) {n.ref}" for gid in g["ad_groups"] for n in scopes.get((cid, gid), [])
                       if blocks(n.text, n.match, q) is True})
        return {"literal_keyword_coverage": pos, "blocking_negatives": negs,
                "note": "literal semantics only; close variants and broad reach are not modelled"}

    min_impr = ctx.params.get("min_impressions")
    counts = {"growth": 0, "decline": 0, "first_reported": 0, "sparse": 0, "stable": 0}
    for key in sorted(groups):
        cid, q = key
        g = groups[key]
        pi, ci = g["prior"]["impressions"], g["current"]["impressions"]
        if "prior:impressions" in g["unknown"] or "current:impressions" in g["unknown"]:
            growth.partial(f"campaign {cid} '{q}': unknown impressions")
            continue
        first = first_seen[key] >= cs
        rate = V.ratio(ci - pi, pi) if pi > 0 else None
        branch = "first_reported" if first else "growth_ratio" if rate is not None else "reappeared_absolute"
        entity = {"campaign_id": cid, "query": q}
        ev = {"raw_queries": sorted(g["raw"]), "ad_group_ids": sorted(g["ad_groups"]),
              "matched_keyword_ids": sorted(g["keyword_ids"]), "prior": g["prior"], "current": g["current"],
              "prior_window": [ps, pe], "current_window": [cs, ce], "growth": rate, "branch": branch,
              "earliest_observed": first_seen[key], "min_impressions": min_impr.value,
              "reporting_coverage_changed": cid in changed_cov, "unknown_metrics": sorted(g["unknown"])}
        sample_ok = min_impr.value is not None and pi >= min_impr.value and ci >= min_impr.value
        if first:
            counts["first_reported"] += 1
            if min_impr.value is not None and ci >= min_impr.value:
                ev["existing_coverage"] = coverage(key, g)
                screen.finding("first_reported_term", "Info", entity,
                               f"'{q}' (campaign {cid}) first reported on {first_seen[key]} with {ci:g} impressions",
                               evidence=ev, recommendation="Relevance/coverage review; route additions to skill-013 and "
                                                           "exclusions to skill-014 with intent evidence.",
                               uncertainty="First observation in the supplied history is not proof of market novelty.")
            continue
        if rate is None or not sample_ok:
            counts["sparse"] += 1
            continue
        if rate > GROWTH:
            counts["growth"] += 1
            ev["existing_coverage"] = coverage(key, g)
            screen.finding("query_growth", "Info", entity,
                           f"'{q}' (campaign {cid}) impressions {pi:g} → {ci:g} ({rate:+.0%})", evidence=ev,
                           recommendation="Review relevance and existing coverage; hand additions to skill-013 or "
                                          "negatives to skill-014. Do not add keywords automatically.",
                           uncertainty="Observed ads query volume is not total market demand; privacy suppression applies.")
        elif rate < DECLINE:
            counts["decline"] += 1
            ev["existing_coverage"] = coverage(key, g)
            ev["changes_in_window"] = _changes(ctx, cid, ps, ce) if conf.runnable else "unknown: search_trend_changes missing"
            floor = ctx.params.get("spend_significant", cid)
            prior_cost = None if "prior:cost" in g["unknown"] else g["prior"]["cost"]
            material = floor.value is not None and prior_cost is not None and prior_cost >= floor.value
            ev.update({"prior_cost": prior_cost, "materiality_threshold": floor.value,
                       "materiality_source": floor.source or floor.reason, "material": material})
            gates_ok = material and cid not in changed_cov and ctx.mature is True
            prov = screen.finding("query_decline", "Info", entity,
                                  f"'{q}' (campaign {cid}) impressions {pi:g} → {ci:g} ({rate:+.0%})", evidence=ev,
                                  recommendation="Check budget, serving, matching and reporting changes before reading demand.",
                                  uncertainty="Decline can reflect demand, seasonality, reporting suppression or intentional changes.")
            if gates_ok:
                screen.review("query_decline", entity,
                              f"Is the {rate:+.0%} decline of '{q}' (campaign {cid}) explained by an identified serving risk "
                              f"(listed change or current blocking negative)?",
                              evidence=ev, provisional=prov,
                              outcomes={"serving_risk_identified": {"severity": "Warning", "recommendation":
                                        "Investigate the cited change/negative with the account owner; request-only fix."},
                                        "demand_or_seasonal": {"severity": "Info", "recommendation": "Monitor; no serving action."},
                                        "uncertain": {"severity": "Info", "recommendation": "Request the change history."}},
                              guidance="serving_risk_identified needs proposal.change_id from changes_in_window or "
                                       "proposal.negative equal to one of existing_coverage.blocking_negatives.")
        else:
            counts["stable"] += 1
    for cid in changed_cov:
        screen.finding("reporting_coverage_changed", "Info", {"campaign_id": cid},
                       f"Campaign {cid}: reporting_coverage differs between prior and current week",
                       evidence={"prior": sorted(cov_by.get((cid, "prior"), set())),
                                 "current": sorted(cov_by.get((cid, "current"), set()))},
                       recommendation="Compare only after coverage is aligned; trends here are not comparable.",
                       uncertainty="Changed query reporting coverage alters visible volumes.")
    if min_impr.value is None:
        screen.partial(f"min_impressions unresolved: {min_impr.reason}")
    if ctx.mature is not True:
        screen.partial(f"decline review disabled: maturity {ctx.mature} ({ctx.maturity_note})")
    growth.observe("Branch totals", **counts, thresholds={"growth": GROWTH, "decline": DECLINE})
    if conf.runnable:
        for cid in sorted({k[0] for k in groups}):
            ch = _changes(ctx, cid, ps, ce)
            conf.observe(f"Campaign {cid}: changes in comparison window", campaign_id=cid, changes=ch, count=len(ch))
    if cover.runnable:
        cover.observe("Coverage evaluated literally for flagged terms", keywords=len(kws),
                      negative_scopes=len(scopes), handoff={"additions": "skill-013", "negatives": "skill-014"})


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'serving_risk_identified' must cite a listed change_id or a listed blocking negative."""
    if decision.get("outcome") != "serving_risk_identified":
        return []
    p = decision.get("proposal") or {}
    ev = item.evidence
    changes = ev.get("changes_in_window") if isinstance(ev.get("changes_in_window"), list) else []
    ids = {str(c.get("change_id")) for c in changes}
    negs = set((ev.get("existing_coverage") or {}).get("blocking_negatives") or [])
    if str(p.get("change_id") or "") in ids or str(p.get("negative") or "") in negs:
        return []
    return [f"proposal must cite change_id in {sorted(ids)} or negative in {sorted(negs)}"]


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
