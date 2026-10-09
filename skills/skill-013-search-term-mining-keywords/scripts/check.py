"""check.py — skill-013 deterministic search-term mining for keyword candidates with verified proposals.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-013-search-term-mining-keywords/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #15 Automated GPT Keyword Suggestions (nilsrooijmans.com) — NOT integrated: LLM/network ideation
         outside reported queries (DATA_CONTRACT invariant 8: no third-party queries during analysis)
         index #109 Amazon Autocomplete keyword opportunities (Derek Martin) — NOT integrated: third-party
         autocomplete fetches; this recipe mines only already-reported queries
rules:   Queries are normalised with values.norm_text and aggregated per (campaign_id, ad_group_id, query);
         identical full-grain rows are dropped once; same-trigger duplicates without a segment column are
         fan-out → excluded + partial. Trigger mappings (matched_keyword_id) are preserved, never merged away.
         Existing coverage = an active keyword in the SAME campaign whose normalised text equals the query;
         reported added_excluded is only a hint. Close-variant/semantic coverage is left to review.
         Candidates = uncovered queries with conversions > 0 or clicks >= min_clicks. Every outcome is Info
         (recipe table); 'add_for_documented_control' is offered ONLY when mature, tracking True, a target
         CPA applies (ctx.params.target_cpa), conversions >= min_conversions and CPA <= target.
         verify(): proposal keyword must literally cover the query in its reviewed scope, must not be blocked by
         an effective negative there, must not duplicate an active keyword, and no CPC bid under Smart Bidding.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
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
from adsrun.negatives import blocks, effective_negatives, normalize_match  # noqa: E402

SKILL = "skill-013-search-term-mining-keywords"
VERSION = "1.0.0"

NEEDS = {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]}
SEGMENT_COLS = ("date", "day", "week", "month", "device", "network", "ad_network_type", "segment", "hour")
MANUAL = ("MANUAL_CPC",)


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion maturity",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature, maturity_note=ctx.maturity_note,
              conversion_date_basis=ctx.account.get("conversion_date_basis"))


def _dedupe(ctx) -> tuple[list[dict], list[str]]:
    t = ctx.table("search_terms")
    segs = [c for c in SEGMENT_COLS if c in t.columns]
    seen, keyed, notes, out = set(), {}, [], []
    dup = 0
    for r in t.rows:
        sig = tuple(sorted((k, str(v)) for k, v in r.items()))
        if sig in seen:
            dup += 1
            continue
        seen.add(sig)
        grain = (str(r.get("campaign_id")), str(r.get("ad_group_id")), V.norm_text(r.get("search_term")),
                 str(r.get("matched_keyword_id") or r.get("matched_keyword") or ""), str(r.get("match_type") or ""),
                 *(str(r.get(s)) for s in segs))
        keyed.setdefault(grain, []).append(r)
    for grain in sorted(keyed):
        rs = keyed[grain]
        if len(rs) > 1:
            notes.append(f"'{grain[2]}' ({grain[0]}/{grain[1]}): {len(rs)} conflicting rows at one grain (fan-out); excluded")
            continue
        out.append(rs[0])
    if dup:
        notes.append(f"{dup} identical duplicate query rows dropped")
    return out, notes


def run(ctx) -> None:
    """Run query aggregation, same-campaign literal keyword coverage and candidate relevance review.

    Rules:   Candidates = uncovered queries with conversions > 0 or clicks >= min_clicks → Info only (never
             Warning/Critical). 'add_for_documented_control' is offered only when ctx.mature, tracking True,
             ctx.params.target_cpa set, conversions >= min_conversions and CPA <= target. Fan-out duplicates are
             excluded + partial, never summed. Close-variant/semantic coverage and relevance are left to ai_review;
             reported added_excluded is only a hint.
    """
    _scope(ctx)

    # step 2 — reconcile reported queries with campaign totals
    cov = ctx.check("query_coverage", "Reconcile reported-query clicks/cost with campaign totals",
                    {**NEEDS, "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if cov.runnable:
        by_c: dict[str, list[float]] = {}
        for r in ctx.rows("search_terms"):
            acc = by_c.setdefault(str(r.get("campaign_id")), [0.0, 0.0])
            acc[0] += V.num(r.get("clicks")) or 0
            acc[1] += ctx.money(r.get("cost")) or 0
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid in by_c:
                cc, ccost = V.num(m.get("clicks")), ctx.money(m.get("cost"))
                cov.observe(f"Campaign {cid}: reported queries cover part of campaign traffic", campaign_id=cid,
                            query_clicks=by_c[cid][0], campaign_clicks=cc, click_share=V.ratio(by_c[cid][0], cc),
                            query_cost=by_c[cid][1], campaign_cost=ccost, cost_share=V.ratio(by_c[cid][1], ccost))
        cov.partial("privacy-limited query reporting: unreported traffic is unobserved, not zero")

    # step 3 — normalise and aggregate
    agg = ctx.check("query_aggregation", "Normalise, deduplicate at full grain, aggregate per ad group", NEEDS)
    if not agg.runnable:
        for cid, title in (("keyword_coverage", "Existing keyword coverage by ID/text/match/scope"),
                           ("relevance_review", "Relevance and control-need review of candidates"),
                           ("goal_relative_outcomes", "Mature goal-relative outcomes per candidate"),
                           ("control_benefit", "Observed trigger routing per candidate"),
                           ("negative_conflicts", "Effective negatives that block candidates"),
                           ("match_type_context", "Match-type and bidding control context")):
            ctx.check(cid, title).skip("search_terms unavailable", agg.missing)
        return
    rows, notes = _dedupe(ctx)
    for n in notes:
        agg.partial(n)
    queries: dict[tuple, dict] = {}
    unknown = 0
    for r in rows:
        if str(r.get("added_excluded") or "").upper() in ("EXCLUDED", "ADDED_EXCLUDED"):
            continue
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id")), V.norm_text(r.get("search_term")))
        q = queries.setdefault(key, {"clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0,
                                     "impressions": 0.0, "triggers": set(), "report_match": set(), "added_hint": False,
                                     "unknown": False})
        for f in ("clicks", "cost", "conversions", "conversion_value", "impressions"):
            v = ctx.money(r.get(f)) if f == "cost" else V.num(r.get(f))
            if v is None:
                q["unknown"] = q["unknown"] or f in ("clicks", "cost", "conversions")
                continue
            q[f] += v
        q["triggers"].add(str(r.get("matched_keyword_id") or r.get("matched_keyword") or "?"))
        if r.get("match_type"):
            q["report_match"].add(str(r.get("match_type")).upper())
        q["added_hint"] |= str(r.get("added_excluded") or "").upper() == "ADDED"
    unknown = sum(1 for q in queries.values() if q["unknown"])
    if unknown:
        agg.partial(f"{unknown} aggregated queries with unknown clicks/cost/conversions")
    if "matched_keyword_id" not in ctx.table("search_terms").columns:
        agg.partial("matched_keyword_id missing: ad-group-level candidates only", ["search_terms:matched_keyword_id"])
    agg.observe("Aggregated queries", source_rows=len(rows), aggregated=len(queries),
                distinct_normalized=len({k[2] for k in queries}))

    # step 4 — existing keyword coverage
    kc = ctx.check("keyword_coverage", "Existing keyword coverage by ID/text/match/scope",
                   {"keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type", "status"]})
    active = [k for k in ctx.rows("keywords") if str(k.get("status") or "").upper() in ("ENABLED", "")]
    covered: dict[tuple, list[str]] = {}
    if kc.runnable:
        for key in sorted(queries):
            ids = sorted(str(k.get("id")) for k in active if str(k.get("campaign_id")) == key[0]
                         and V.norm_text(k.get("text")) == key[2])
            if ids:
                covered[key] = ids
        hint_only = sum(1 for k, q in queries.items() if q["added_hint"] and k not in covered)
        kc.observe("Query coverage by existing keyword text", exact_text_existing=len(covered),
                   added_hint_without_active_text=hint_only, uncovered=len(queries) - len(covered))
    else:
        agg.partial("keyword inventory missing: candidates not screened for existing coverage")

    mk = ctx.params.get("min_clicks")
    mc = ctx.params.get("min_conversions")
    brand = [b for b in ctx.profile.get("brand_terms") or [] if b]
    candidates = sorted(k for k, q in queries.items() if kc.runnable and k not in covered and not q["unknown"]
                        and (q["conversions"] > 0 or (mk.value is not None and q["clicks"] >= mk.value)))

    # data for steps 6-8 (checks declared below in step order)
    scopes, neg_gaps = ({}, ["negative inventory missing"])
    if ctx.table("negative_keywords") is not None and ctx.table("ad_groups") is not None:
        scopes, neg_gaps = effective_negatives(ctx)
    blocked = {k: [f"{n.text} ({n.match}) [{n.ref}]" for n in scopes.get((k[0], k[1]), []) if blocks(n.text, n.match, k[2])]
               for k in candidates}
    outcomes_for: dict[tuple, dict] = {}
    for k in candidates:
        q = queries[k]
        target, src = ctx.params.target_cpa(k[0])
        tracking, t_note = ctx.tracking_for_campaign(k[0])
        cpa = V.ratio(q["cost"], q["conversions"])
        gated = ctx.mature is True and tracking is True and mc.value is not None and q["conversions"] >= mc.value
        favorable = gated and target is not None and cpa is not None and cpa <= target
        outcomes_for[k] = {"target_cpa": target, "target_source": src, "cpa": cpa, "favorable": favorable,
                           "gate": {"mature": ctx.mature, "tracking": tracking, "tracking_note": t_note,
                                    "conversions": q["conversions"], "min_conversions": mc.value}}

    # step 5 — relevance / control-need review
    rel = ctx.check("relevance_review", "Relevance and control-need review of candidates", NEEDS)
    if not kc.runnable:
        rel.skip("keyword inventory missing: existing coverage unknown", kc.missing)
    else:
        for k in candidates:
            q, o = queries[k], outcomes_for[k]
            entity = {"campaign_id": k[0], "ad_group_id": k[1], "normalized_query": k[2]}
            ev = {"clicks": q["clicks"], "cost": q["cost"], "conversions": q["conversions"],
                  "conversion_value": q["conversion_value"], "triggers": sorted(q["triggers"]),
                  "report_match_types": sorted(q["report_match"]), "added_hint": q["added_hint"],
                  "brand_query": any(blocks(b, "PHRASE", k[2]) for b in brand),
                  "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(k[0]),
                  "blocked_by_current_negatives": blocked.get(k) or [], **o,
                  "window": [ctx.period_start, ctx.period_end]}
            prov = rel.finding("converting_or_high_volume_query", "Info", entity,
                               f"Reported query '{k[2]}' ({q['conversions']:g} conv, {q['clicks']:g} clicks) has no "
                               f"keyword with the same text in campaign {k[0]}", evidence=ev,
                               recommendation="Review relevance and control need before proposing a keyword.",
                               uncertainty="The query already served; adding it does not create reach or fix routing.")
            outcomes = {"no_control_benefit": {"severity": "Info", "recommendation": "Keep observing; no addition."},
                        "not_relevant": {"severity": None, "recommendation": "No addition; consider 014 review."},
                        "uncertain": {"severity": "Info", "recommendation": "Ask the owner about intent."}}
            if o["favorable"]:
                outcomes["add_for_documented_control"] = {"severity": "Info", "recommendation":
                                                          "Owner-reviewed keyword addition per verified proposal."}
            else:
                outcomes["relevant_insufficient_evidence"] = {"severity": "Info", "recommendation":
                                                              "Monitor; sample/target/maturity insufficient for ranking."}
            rel.review("keyword_candidate", entity,
                       f"Is '{k[2]}' relevant to the approved offer for campaign {k[0]}, and is there a specific "
                       f"control benefit (reporting, message/landing alignment, routing) in adding it?",
                       evidence=ev, outcomes=outcomes, provisional=prov,
                       guidance="Conversions alone do not establish desirability. For add_for_documented_control "
                                "supply proposal {keyword, match_type, campaign_id, ad_group_id, control_need}; "
                                "negatives blocking the query need owner resolution first.")
        rel.observe("Candidate totals", candidates=len(candidates),
                    below_volume=len([k for k in queries if k not in covered]) - len(candidates))

    # step 6 — goal-relative outcomes
    gro = ctx.check("goal_relative_outcomes", "Mature goal-relative outcomes per candidate", NEEDS)
    if gro.runnable:
        if ctx.mature is not True:
            gro.partial(f"conversions not lag-mature ({ctx.maturity_note}): no economic ranking")
        for note in sorted({o["gate"]["tracking_note"] for o in outcomes_for.values() if o["gate"]["tracking"] is not True}):
            gro.partial(f"tracking not evidenced, no favorable ranking: {note}")
        gro.observe("Goal-relative screening", favorable=sum(1 for o in outcomes_for.values() if o["favorable"]),
                    without_target=sum(1 for o in outcomes_for.values() if o["target_cpa"] is None),
                    below_min_conversions=sum(1 for k in candidates if queries[k]["conversions"] < (mc.value or 0)))

    # step 7 — control benefit (observed trigger routing)
    cb = ctx.check("control_benefit", "Observed trigger routing per candidate", NEEDS)
    if cb.runnable:
        multi = sum(1 for k in candidates if len(queries[k]["triggers"]) > 1)
        loose = sum(1 for k in candidates if queries[k]["report_match"] - {"EXACT", "EXACT (CLOSE VARIANT)"})
        cb.observe("Candidate trigger routing", candidates=len(candidates), multi_trigger=multi,
                   served_by_non_exact=loose)

    # step 8 — effective negative conflicts
    nc = ctx.check("negative_conflicts", "Effective negatives that block candidates",
                   {"negative_keywords": ["text", "match_type", "level", "campaign_id"], "ad_groups": ["id", "campaign_id"]})
    if nc.runnable:
        for g in neg_gaps:
            nc.partial(g)
        nc.observe("Candidates blocked by a current negative (owner resolution before any addition)",
                   count=sum(1 for v in blocked.values() if v))

    # step 9 — match-type/bidding context
    mt = ctx.check("match_type_context", "Match-type and bidding control context",
                   {"campaigns": ["id", "bidding_strategy_type"]})
    if mt.runnable:
        for cid in sorted({k[0] for k in candidates}):
            camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), {}) or {}
            st = str(camp.get("bidding_strategy_type") or "").upper()
            mt.observe(f"Campaign {cid}: bidding control", campaign_id=cid, strategy=st, keyword_cpc_control=st in MANUAL)


def verify(ctx, item, decision) -> list[str]:
    """Rules: keyword proposals are literal, in scope, unblocked and not duplicates."""
    if decision.get("outcome") != "add_for_documented_control":
        return []
    p = decision.get("proposal") or {}
    text, match = str(p.get("keyword") or "").strip(), normalize_match(p.get("match_type"))
    cid, gid = str(p.get("campaign_id") or ""), str(p.get("ad_group_id") or "")
    if not text or match is None or not cid or not gid or not str(p.get("control_need") or "").strip():
        return ["proposal needs keyword, match_type EXACT|PHRASE|BROAD, campaign_id, ad_group_id and control_need"]
    problems = []
    if (cid, gid) != (item.entity["campaign_id"], item.entity["ad_group_id"]):
        problems.append("proposal scope differs from the reviewed campaign/ad group")
    if blocks(text, match, item.entity["normalized_query"]) is not True:
        problems.append(f"'{text}' ({match}) does not literally cover '{item.entity['normalized_query']}'")
    for k in ctx.rows("keywords"):
        if (str(k.get("campaign_id")), str(k.get("ad_group_id"))) == (cid, gid) and \
                str(k.get("status") or "").upper() in ("ENABLED", "") and V.norm_text(k.get("text")) == V.norm_text(text) \
                and normalize_match(k.get("match_type")) == match:
            problems.append(f"duplicates active keyword {k.get('id')}")
    if ctx.table("negative_keywords") is not None and ctx.table("ad_groups") is not None:
        scopes, _ = effective_negatives(ctx)
        for n in scopes.get((cid, gid), []):
            if blocks(n.text, n.match, text):
                problems.append(f"blocked by effective negative '{n.text}' ({n.match}) [{n.ref}]")
    else:
        problems.append("negative inventory missing: cannot verify the keyword is unblocked")
    if p.get("cpc_bid") is not None:
        camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), {}) or {}
        if str(camp.get("bidding_strategy_type") or "").upper() not in MANUAL:
            problems.append("keyword CPC bids are unsupported under automated bidding")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
