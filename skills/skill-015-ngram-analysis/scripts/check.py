"""check.py — skill-015 deterministic n-gram query pattern aggregation with guarded exclusion review.

exports: SKILL | VERSION | TOKENIZER | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-015-ngram-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #64 N-Gram Search Query Mining (nilsrooijmans.com, after Brainlabs) — clean-room reimplementation
         of 1-3 gram aggregation of query cost/conversions per campaign; the script's sheet output becomes
         observations + review items, and its implicit waste threshold is replaced by spend_floor + gates
rules:   TOKENIZER: NFKC, casefold, split on whitespace; punctuation stays attached; no stemming/stop words.
         Each source row contributes ONCE per distinct n-gram (set per row), after dropping identical rows;
         conflicting rows at one grain without a segment column are fan-out → excluded + partial.
         Aggregation is per campaign; overlapping n-grams are NEVER summed — combined exposure is the union of
         contributing row keys. N-grams with identical row sets collapse to the shortest (aliases kept).
         Zero-conversion Warning path needs ctx.mature True, ctx.tracking_for_campaign True, cost >=
         spend_floor(campaign) and AI relevance review; brand n-grams (profile.brand_terms) are never candidates.
         Favorable Info needs mature+tracking, conversions >= min_conversions, target CPA (ctx.params) and CPA <= it.
         verify(): proposals are literal negatives that block a contributing query and do not block converting
         queries, active keyword texts or brand terms in their scope (017 semantics via adsrun.negatives).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402
from adsrun.negatives import blocks, effective_negatives, normalize_match  # noqa: E402

SKILL = "skill-015-ngram-analysis"
VERSION = "1.0.0"
TOKENIZER = "NFKC + casefold + whitespace split; punctuation kept attached; no stemming or stop-word removal"

NEEDS = {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]}
SEGMENT_COLS = ("date", "day", "week", "month", "device", "network", "ad_network_type", "segment", "hour")
SUMS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def tokenize(text) -> list[str]:
    return unicodedata.normalize("NFKC", str(text or "")).casefold().split()


def ngrams(toks: list[str]) -> set[str]:
    return {" ".join(toks[i:i + n]) for n in (1, 2, 3) for i in range(len(toks) - n + 1)}


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


def _rows(ctx) -> tuple[list[tuple[str, dict]], list[str]]:
    """(row_key, row) after identical-row dedupe and fan-out rejection."""
    t = ctx.table("search_terms")
    segs = [c for c in SEGMENT_COLS if c in t.columns]
    seen, keyed, dup = set(), {}, 0
    for r in t.rows:
        sig = tuple(sorted((k, str(v)) for k, v in r.items()))
        if sig in seen:
            dup += 1
            continue
        seen.add(sig)
        grain = "|".join([str(r.get("campaign_id")), str(r.get("ad_group_id")), " ".join(tokenize(r.get("search_term"))),
                          str(r.get("matched_keyword_id") or r.get("matched_keyword") or ""),
                          str(r.get("match_type") or ""), *(str(r.get(s)) for s in segs)])
        keyed.setdefault(grain, []).append(r)
    notes = [f"{dup} identical duplicate rows dropped"] if dup else []
    out = []
    for k in sorted(keyed):
        if len(keyed[k]) > 1:
            notes.append(f"{k}: {len(keyed[k])} conflicting rows at one grain (fan-out); excluded")
        else:
            out.append((k, keyed[k][0]))
    return out, notes


def run(ctx) -> None:
    """Run per-campaign 1-3 gram aggregation, zero-conversion pattern and favorable pattern checks.

    Rules:   Missing search_terms skips every check; overlapping n-gram costs are never summed. Zero-conversion patterns
             need ctx.mature True, tracking True and cost >= spend_floor(campaign) → provisional Info; Warning only via
             ai_review 'irrelevant_pattern'. Brand n-grams (profile.brand_terms) are never candidates. Favorable Info
             needs conversions >= min_conversions, a resolved target CPA, tracking and CPA <= target; else observe.
    """
    _scope(ctx)
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

    tok = ctx.check("tokenization", "Declared tokenizer applied to original query text", NEEDS)
    later = (("ngram_generation", "Contiguous 1-3 token n-grams as a set per row"),
             ("dedupe_aggregate", "Full-grain dedupe and per-campaign aggregation"),
             ("exposure_union", "Non-additive exposure via union of row keys"),
             ("zero_conversion_patterns", "Mature zero-conversion patterns at spend_floor"),
             ("positive_patterns", "Mature patterns with favorable goal-relative outcomes"),
             ("phrase_proposal_conflicts", "Ordered containment conflicts for phrase proposals"))
    if not tok.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("search_terms unavailable", tok.missing)
        return
    rows, notes = _rows(ctx)
    tok.observe("Tokenizer rule", rule=TOKENIZER, rows=len(rows),
                tokens=sum(len(tokenize(r.get("search_term"))) for _, r in rows))

    gen = ctx.check("ngram_generation", later[0][1], NEEDS)
    grams_of = {k: ngrams(tokenize(r.get("search_term"))) for k, r in rows}
    gen.observe("N-grams generated (set per row)", rows=len(rows), memberships=sum(len(g) for g in grams_of.values()),
                distinct=len({g for s in grams_of.values() for g in s}))

    agg = ctx.check("dedupe_aggregate", later[1][1], NEEDS)
    for n in notes:
        agg.partial(n)
    pat: dict[tuple[str, str], dict] = {}
    row_data: dict[str, dict] = {}
    unknown = 0
    for k, r in rows:
        vals = {f: (ctx.money(r.get(f)) if f == "cost" else V.num(r.get(f))) for f in SUMS}
        if None in (vals["clicks"], vals["cost"], vals["conversions"]):
            unknown += 1
            continue
        cid = str(r.get("campaign_id"))
        row_data[k] = {"campaign_id": cid, "ad_group_id": str(r.get("ad_group_id")),
                       "query": " ".join(tokenize(r.get("search_term"))), **vals}
        for g in grams_of[k]:
            p = pat.setdefault((cid, g), {"rows": set(), "queries": set(), **dict.fromkeys(SUMS, 0.0)})
            p["rows"].add(k)
            p["queries"].add(row_data[k]["query"])
            for f in SUMS:
                p[f] += vals[f] or 0
    if unknown:
        agg.partial(f"{unknown} rows with unknown clicks/cost/conversions excluded from sums")
    by_campaign: dict[str, int] = {}
    for cid, _ in pat:
        by_campaign[cid] = by_campaign.get(cid, 0) + 1
    agg.observe("Per-campaign n-gram aggregation", campaigns=by_campaign, source_rows=len(row_data))

    # collapse identical row sets to the shortest n-gram (aliases retained)
    groups: dict[tuple, list[str]] = {}
    for (cid, g), p in pat.items():
        groups.setdefault((cid, tuple(sorted(p["rows"]))), []).append(g)
    reps = {}
    for (cid, _), gs in groups.items():
        gs = sorted(gs, key=lambda x: (len(x.split()), x))
        reps[(cid, gs[0])] = gs[1:]

    brand = [b for b in ctx.profile.get("brand_terms") or [] if b]
    have_inv = all(ctx.table(t) is not None for t in ("keywords", "negative_keywords", "ad_groups"))
    scopes, neg_gaps = effective_negatives(ctx) if have_inv else ({}, ["keyword/negative inventory missing"])
    kws = [k for k in ctx.rows("keywords") if str(k.get("status") or "").upper() in ("ENABLED", "")]

    def conflicts(cid: str, g: str) -> dict:
        conv_q = sorted({d["query"] for d in row_data.values() if d["campaign_id"] == cid and d["conversions"] > 0
                         and blocks(g, "PHRASE", d["query"])})
        kw_hits = sorted(f"{k.get('text')} ({k.get('id')})" for k in kws if str(k.get("campaign_id")) == cid
                         and blocks(g, "PHRASE", k.get("text")))
        return {"converting_queries_blocked": conv_q, "keyword_texts_blocked": kw_hits,
                "brand_terms_blocked": sorted(b for b in brand if blocks(g, "PHRASE", b))}

    def already_blocked(p) -> bool:
        return bool(p["rows"]) and all(any(blocks(n.text, n.match, row_data[k]["query"])
                                           for n in scopes.get((row_data[k]["campaign_id"], row_data[k]["ad_group_id"]), []))
                                       for k in p["rows"])

    exp = ctx.check("exposure_union", later[2][1], NEEDS)

    # step 7
    zc = ctx.check("zero_conversion_patterns", later[3][1], NEEDS)
    if ctx.mature is not True:
        zc.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    flagged_rows: set[str] = set()
    sub_floor = 0
    for (cid, g) in sorted(reps):
        p = pat[(cid, g)]
        if p["conversions"] != 0 or ctx.mature is not True:
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            if f"spend_floor unresolved for campaign {cid}: {floor.reason}" not in zc.notes:
                zc.partial(f"spend_floor unresolved for campaign {cid}: {floor.reason}")
            continue
        if p["cost"] < floor.value:
            sub_floor += 1
            continue
        tracking, t_note = ctx.tracking_for_campaign(cid)
        if tracking is not True:
            if t_note not in zc.notes:
                zc.partial(t_note)
            continue
        if any(blocks(b, "PHRASE", g) or blocks(g, "PHRASE", b) for b in brand):
            zc.observe(f"Brand n-gram '{g}' protected from exclusion", campaign_id=cid, cost=p["cost"])
            continue
        if have_inv and already_blocked(p):
            zc.observe(f"'{g}' rows already blocked by current negatives", campaign_id=cid, cost=p["cost"])
            continue
        flagged_rows |= p["rows"]
        entity = {"campaign_id": cid, "ngram": g}
        ev = {"tokenizer": TOKENIZER, "aliases": reps[(cid, g)], "cost": p["cost"], "clicks": p["clicks"],
              "conversions": 0, "distinct_queries": len(p["queries"]), "source_rows": len(p["rows"]),
              "contributing_queries": sorted(p["queries"]), "row_keys": sorted(p["rows"]),
              "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": t_note,
              "excluded_intents": ctx.profile.get("excluded_intents"),
              "phrase_conflicts": conflicts(cid, g) if have_inv else "inventory missing: no proposals",
              "window": [ctx.period_start, ctx.period_end]}
        prov = zc.finding("zero_conversion_pattern", "Info", entity,
                          f"N-gram '{g}' (campaign {cid}) spent {p['cost']:.2f} {ctx.currency} over {len(p['queries'])} "
                          f"queries with 0 conversions (spend_floor {floor.value:g})", evidence=ev,
                          calculation={"cost": p["cost"], "threshold": floor.value, "rows": len(p["rows"])},
                          recommendation="Inspect contributing queries; route final negatives to 014.",
                          uncertainty="Patterns overlap; exposure is non-additive and not savings.")
        zc.review("zero_conversion_pattern", entity,
                  f"Do the contributing queries of '{g}' share an irrelevant/business-excluded meaning for campaign {cid}?",
                  evidence=ev, provisional=prov,
                  outcomes={"irrelevant_pattern": {"severity": "Warning", "recommendation":
                                                   "Hand the verified phrase proposal to 014 for final decision."},
                            "mixed_meaning": {"severity": "Info", "recommendation": "Review individual queries in 014."},
                            "relevant_keep": {"severity": None, "recommendation": "No action."},
                            "uncertain": {"severity": "Info", "recommendation": "Ask the owner about the intent."}},
                  guidance="Judge only against profile excluded_intents/objectives. For irrelevant_pattern supply "
                           "proposal {negative, match_type, level: campaign|ad_group, campaign_id, ad_group_id}.")
    zc.observe("Zero-conversion pattern screening", reviewed=sum(1 for r in ctx.result.reviews
                                                                 if r.condition_key == "zero_conversion_pattern"),
               sub_floor_patterns=sub_floor)

    # step 8
    pp = ctx.check("positive_patterns", later[4][1], NEEDS)
    mc = ctx.params.get("min_conversions")
    if ctx.mature is not True:
        pp.partial("conversions not lag-mature: no favorable claims")
    else:
        for (cid, g) in sorted(reps):
            p = pat[(cid, g)]
            if mc.value is None or p["conversions"] < mc.value:
                continue
            target, src = ctx.params.target_cpa(cid)
            tracking, t_note = ctx.tracking_for_campaign(cid)
            cpa = V.ratio(p["cost"], p["conversions"])
            if target is None or tracking is not True or cpa is None:
                pp.observe(f"'{g}' (campaign {cid}) qualifies on volume but lacks target/tracking", campaign_id=cid,
                           ngram=g, cpa=cpa, target_reason=src, tracking=t_note)
                continue
            if cpa <= target:
                pp.finding("favorable_pattern", "Info", {"campaign_id": cid, "ngram": g},
                           f"N-gram '{g}' CPA {cpa:.2f} <= target {target:g} ({src}) on {p['conversions']:g} conversions",
                           evidence={"cost": p["cost"], "conversions": p["conversions"], "distinct_queries": len(p["queries"]),
                                     "aliases": reps[(cid, g)], "tokenizer": TOKENIZER},
                           calculation={"cpa": cpa, "target_cpa": target, "min_conversions": mc.value},
                           recommendation="Hypothesis for 013 keyword review; inspect mixed meanings.",
                           uncertainty="Overlapping pattern; not a causal driver.")

    # step 6 — union exposure of flagged patterns
    exp.observe("Union exposure of zero-conversion patterns under review (non-additive)",
                rows=len(flagged_rows), cost=sum(row_data[k]["cost"] for k in flagged_rows),
                note="exposure, not savings; n-gram totals overlap")

    # step 9
    pc = ctx.check("phrase_proposal_conflicts", later[5][1],
                   {**NEEDS, "keywords": ["id", "campaign_id", "ad_group_id", "text", "status"],
                    "negative_keywords": ["text", "match_type", "level", "campaign_id"], "ad_groups": ["id", "campaign_id"]})
    if pc.runnable:
        for gp in neg_gaps:
            pc.partial(gp)
        n = sum(1 for r in ctx.result.reviews if r.condition_key == "zero_conversion_pattern"
                and any(r.evidence["phrase_conflicts"].values()))
        pc.observe("Candidate patterns whose phrase negative would block desired text", count=n)


def verify(ctx, item, decision) -> list[str]:
    """Rules: phrase proposals are literal, scoped and conflict-free."""
    if decision.get("outcome") != "irrelevant_pattern":
        return []
    if not all(ctx.table(t) is not None for t in ("keywords", "negative_keywords", "ad_groups")):
        return ["keyword/negative inventory missing: exclusion proposals cannot be verified"]
    p = decision.get("proposal") or {}
    text, match = str(p.get("negative") or "").strip(), normalize_match(p.get("match_type"))
    level = str(p.get("level") or "").lower()
    cid, gid = str(p.get("campaign_id") or ""), str(p.get("ad_group_id") or "")
    if not text or match is None or level not in ("campaign", "ad_group") or not cid or (level == "ad_group" and not gid):
        return ["proposal needs negative, match_type, level campaign|ad_group, campaign_id (and ad_group_id)"]
    if cid != item.entity["campaign_id"]:
        return [f"proposal campaign {cid} differs from reviewed campaign {item.entity['campaign_id']}"]
    problems = []
    if not any(blocks(text, match, q) for q in item.evidence["contributing_queries"]):
        problems.append(f"'{text}' ({match}) blocks none of the contributing queries")
    in_scope = lambda r: str(r.get("campaign_id")) == cid and (level == "campaign" or str(r.get("ad_group_id")) == gid)
    for r in ctx.rows("search_terms"):
        if in_scope(r) and (V.num(r.get("conversions")) or 0) > 0 and blocks(text, match, " ".join(tokenize(r.get("search_term")))):
            problems.append(f"would block converting query '{r.get('search_term')}'")
    for k in ctx.rows("keywords"):
        if in_scope(k) and str(k.get("status") or "").upper() in ("ENABLED", "") and blocks(text, match, k.get("text")):
            problems.append(f"would block keyword text '{k.get('text')}' ({k.get('id')})")
    for b in ctx.profile.get("brand_terms") or []:
        if blocks(text, match, b):
            problems.append(f"would block brand term '{b}'")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
