"""check.py — skill-018 deterministic duplicate-keyword inventory and observed query-to-trigger routing map.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-018-duplicate-keyword-detection/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #107 Add keywords from campaigns/ad groups as negatives to others (Ritwik GA) — clean-room
         reimplementation of cross-negative query sculpting as VERIFIED proposals on routing reviews: the
         negative must block the routed query only in a non-approved trigger scope and must not block that
         scope's active keywords, other converting queries or brand terms (017 literal semantics)
rules:   Keywords group on (values.norm_text(text), explicit match_type); same text across match types is a
         variant set (observation), not a duplicate. Duplicate sets / multi-trigger queries alone are Info.
         Context comparison uses IDs only: campaign geo/language/schedule/strategy, ctx.goal_ids, keyword
         final_url and effective-negative texts; missing audiences/bid_adjustments → partial (restrictions unknown).
         Warning is reachable ONLY via review: 'duplicate_control_burden' (verify needs proposal.requirement_ref)
         and 'routing_contradiction' (needs profile.intended_routing {normalized_query: {campaign_id, ad_group_id}}).
         Profile owner exceptions: profile.duplicate_keyword_exceptions [keyword_id]. Query CPA = query cost /
         query conversions; comparisons need ctx.mature True and min_conversions on both triggers.
         Exposure is the union of distinct search_term row keys across sets/queries; never summed twice.
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

SKILL = "skill-018-duplicate-keyword-detection"
VERSION = "1.0.0"

KW = {"keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type", "status"]}
QUERIES = {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]}
CONTEXT_FIELDS = ("geo_targets", "languages", "ad_schedule", "bidding_strategy_type")


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion maturity",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature,
              conversion_date_basis=ctx.account.get("conversion_date_basis"))


def _active(r) -> bool:
    return str(r.get("status") or "").upper() in ("ENABLED", "")


def _row_key(r) -> str:
    return "|".join(str(r.get(k) or "") for k in ("campaign_id", "ad_group_id", "matched_keyword_id", "search_term",
                                                  "match_type", "date", "device"))


def _routing(ctx) -> dict:
    return {V.norm_text(k): v for k, v in (ctx.profile.get("intended_routing") or {}).items() if isinstance(v, dict)}


def run(ctx) -> None:
    """Run duplicate-set, context, query-coverage, trigger-map, CPA, QS, consolidation and exposure checks.

    Rules:   Duplicate sets (minus profile.duplicate_keyword_exceptions) and multi-trigger queries are Info only;
             Warning only via ai_review 'duplicate_control_burden' (identical context) or 'routing_contradiction'
             (profile.intended_routing). Per-trigger CPA is observation-only and comparable only with ctx.mature
             True and every trigger >= min_conversions; QS and exposure cost never become findings.
    """
    _scope(ctx)
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    exceptions = {str(x) for x in ctx.profile.get("duplicate_keyword_exceptions") or []}

    # step 2 — duplicate / variant sets
    ds = ctx.check("duplicate_sets", "Same normalized text + explicit match type across locations", KW)
    sets: dict[tuple, list[dict]] = {}
    set_findings: dict[tuple, object] = {}
    if ds.runnable:
        unknown = 0
        by_text: dict[str, set] = {}
        for k in sorted(ctx.rows("keywords"), key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("id")))):
            if not _active(k):
                continue
            m = normalize_match(k.get("match_type"))
            if m is None:
                unknown += 1
                continue
            t = V.norm_text(k.get("text"))
            sets.setdefault((t, m), []).append(k)
            by_text.setdefault(t, set()).add(m)
        if unknown:
            ds.partial(f"{unknown} keywords without explicit match type excluded from sets")
        sets = {key: v for key, v in sets.items() if len(v) > 1}
        for key in sorted(sets):
            members = sets[key]
            ids = [str(k.get("id")) for k in members]
            if set(ids) <= exceptions:
                ds.observe(f"Duplicate set '{key[0]}' ({key[1]}) is an approved owner exception", keyword_ids=ids)
                continue
            entity = {"duplicate_set": f"{key[0]}|{key[1]}", "keyword_ids": ids}
            set_findings[key] = ds.finding(
                "duplicate_keyword_set", "Info", entity,
                f"'{key[0]}' ({key[1]}) exists {len(members)} times: "
                + ", ".join(f"{k.get('campaign_id')}/{k.get('ad_group_id')}/{k.get('id')}" for k in members),
                evidence={"locations": [{f: k.get(f) for f in ("campaign_id", "ad_group_id", "id", "quality_score")}
                                        for k in members]},
                recommendation="Compare targeting/goal context before any consolidation.",
                uncertainty="Duplicates do not prove internal competition, wasted cost or a wrong auction winner.")
        variants = sorted(t for t, ms in by_text.items() if len(ms) > 1)
        ds.observe("Keyword set inventory", exact_duplicate_sets=len(sets), variant_sets=len(variants),
                   variant_texts=variants[:50])

    # step 3 — context comparison
    cc = ctx.check("context_compare", "Targeting, goal, landing and negative context per duplicate set",
                   {**KW, "campaigns": ["id", "geo_targets", "languages", "ad_schedule"]})
    identical: list[tuple] = []
    scopes, neg_gaps = ({}, [])
    if ctx.table("negative_keywords") is not None and ctx.table("ad_groups") is not None:
        scopes, neg_gaps = effective_negatives(ctx)
    if cc.runnable:
        for t in ("audiences", "bid_adjustments"):
            if ctx.table(t) is None:
                cc.partial(f"{t} missing: audience/bid restrictions unknown", [f"{t} (file)"])
        if not scopes:
            cc.partial("negative inventory missing: negative context unknown", ["negative_keywords (file)", "ad_groups (file)"])
        for key in sorted(set_findings):
            ctxs = []
            for k in sets[key]:
                cid, gid = str(k.get("campaign_id")), str(k.get("ad_group_id"))
                c = camps.get(cid, {})
                ctxs.append({**{f: c.get(f) for f in CONTEXT_FIELDS}, "goal_ids": sorted(ctx.goal_ids(cid)),
                             "final_url": k.get("final_url"),
                             "negatives": sorted({f"{n.text}|{n.match}" for n in scopes.get((cid, gid), [])})})
            diff = sorted(f for f in ctxs[0] if any(x[f] != ctxs[0][f] for x in ctxs[1:]))
            cc.observe(f"Duplicate set '{key[0]}' ({key[1]}): context differences", duplicate_set=f"{key[0]}|{key[1]}",
                       differing=diff, contexts=ctxs)
            if not diff:
                identical.append(key)

    # step 4 — reconcile queries
    qc = ctx.check("query_coverage", "Reconcile reported-query clicks/cost with campaign totals",
                   {**QUERIES, "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if qc.runnable:
        by_c: dict[str, list[float]] = {}
        for r in ctx.rows("search_terms"):
            acc = by_c.setdefault(str(r.get("campaign_id")), [0.0, 0.0])
            acc[0] += V.num(r.get("clicks")) or 0
            acc[1] += ctx.money(r.get("cost")) or 0
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid in by_c:
                ccl, ccost = V.num(m.get("clicks")), ctx.money(m.get("cost"))
                qc.observe(f"Campaign {cid}: reported queries cover part of campaign traffic", campaign_id=cid,
                           query_clicks=by_c[cid][0], campaign_clicks=ccl, click_share=V.ratio(by_c[cid][0], ccl),
                           query_cost=by_c[cid][1], campaign_cost=ccost, cost_share=V.ratio(by_c[cid][1], ccost))
        qc.partial("privacy-limited query reporting: unreported traffic is unobserved, not zero")

    # step 5 — query → trigger map
    mt = ctx.check("multi_trigger_map", "Normalized query → observed keyword/ad group/campaign triggers", QUERIES)
    qmap: dict[str, dict[tuple, dict]] = {}
    row_keys: dict[str, set] = {}
    if mt.runnable:
        has_kid = "matched_keyword_id" in ctx.table("search_terms").columns
        if not has_kid:
            mt.partial("matched_keyword_id missing: ad-group-level mapping only", ["search_terms:matched_keyword_id"])
        seen = set()
        for r in ctx.rows("search_terms"):
            rk = _row_key(r)
            if rk in seen:
                continue
            seen.add(rk)
            qn = V.norm_text(r.get("search_term"))
            trig = (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("matched_keyword_id") or "") if has_kid else "")
            acc = qmap.setdefault(qn, {}).setdefault(trig, {"cost": 0.0, "clicks": 0.0, "conversions": 0.0, "unknown": False})
            for f in ("cost", "clicks", "conversions"):
                v = ctx.money(r.get(f)) if f == "cost" else V.num(r.get(f))
                if v is None:
                    acc["unknown"] = True
                else:
                    acc[f] += v
            row_keys.setdefault(qn, set()).add(rk)
        routing = _routing(ctx)
        for qn in sorted(qmap):
            trig = qmap[qn]
            tl = [{"campaign_id": t[0], "ad_group_id": t[1], "keyword_id": t[2], **v} for t, v in sorted(trig.items())]
            if len(trig) > 1:
                mt.finding("multi_trigger_query", "Info", {"normalized_query": qn},
                           f"'{qn}' was served by {len(trig)} triggers in the window", evidence={"triggers": tl},
                           recommendation="Context only; check routing intent before any cross-negative.",
                           uncertainty="Historical triggers do not establish simultaneous auction eligibility.")
            want = routing.get(qn)
            if want:
                wrong = [x for x in tl if (x["campaign_id"], x["ad_group_id"]) !=
                         (str(want.get("campaign_id")), str(want.get("ad_group_id") or x["ad_group_id"]))]
                if wrong:
                    mt.review("routing_contradiction", {"normalized_query": qn},
                              f"Observed triggers for '{qn}' differ from the approved routing "
                              f"{want}. In compatible context, does this contradict the approved routing?",
                              evidence={"triggers": tl, "approved": want, "non_approved_triggers": wrong},
                              outcomes={"contradicts_routing": {"severity": "Warning", "recommendation":
                                                                "Owner-reviewed routing fix; verified cross-negative optional."},
                                        "compatible_exception": {"severity": None, "recommendation": "Document the exception."},
                                        "uncertain": {"severity": "Info", "recommendation": "Confirm targeting context."}},
                              guidance="Consider geo/language/schedule/audience differences. Optional proposal.negatives: "
                                       "[{negative, match_type, level: campaign|ad_group, campaign_id, ad_group_id}] placed "
                                       "only in non-approved trigger scopes.")
        mt.observe("Query-to-trigger map", queries=len(qmap), multi_trigger=sum(1 for v in qmap.values() if len(v) > 1),
                   routed_queries=len(routing))

    # step 6 — compatible performance
    cp = ctx.check("compatible_performance", "Mature query CPA per trigger (query-grain, gated)", QUERIES)
    if cp.runnable:
        mc = ctx.params.get("min_conversions")
        if ctx.mature is not True:
            cp.partial(f"conversions not lag-mature ({ctx.maturity_note}): no comparison")
        for qn in sorted(q for q, v in qmap.items() if len(v) > 1):
            trig = qmap[qn]
            ok = ctx.mature is True and mc.value is not None and all(v["conversions"] >= mc.value and not v["unknown"]
                                                                     for v in trig.values())
            cp.observe(f"'{qn}': per-trigger query CPA" + ("" if ok else " (sample/maturity gate not met)"),
                       normalized_query=qn, comparable=ok, min_conversions=mc.value,
                       cpa={"/".join(t): V.ratio(v["cost"], v["conversions"]) for t, v in sorted(trig.items())})

    # step 7 — QS as context
    qs = ctx.check("qs_context", "Quality Score differences inside duplicate sets (context only)",
                   {"keywords": KW["keywords"] + ["quality_score"]})
    if qs.runnable:
        for key in sorted(set_findings):
            scores = {str(k.get("id")): V.num(k.get("quality_score")) for k in sets[key]}
            qs.observe(f"'{key[0]}' ({key[1]}) Quality Scores", duplicate_set=f"{key[0]}|{key[1]}", scores=scores,
                       note="QS is diagnostic, not an auction input; never keep an instance for QS alone")

    # step 8 — consolidation review
    cr = ctx.check("consolidation_review", "Redundant duplicates with identical context", KW)
    if cr.runnable:
        if not cc.runnable:
            cr.skip("context comparison unavailable", cc.missing)
        for key in identical:
            f = set_findings[key]
            cr.review("duplicate_control_burden", f.entity,
                      f"Duplicate set '{key[0]}' ({key[1]}) shows no targeting/goal/landing/negative difference. Is there a "
                      f"documented operational requirement that makes it an unexplained control burden?",
                      evidence={**f.evidence, "context": "identical on compared fields"}, provisional=f,
                      outcomes={"redundant_documented": {"severity": "Warning", "recommendation":
                                                         "Owner consolidation/routing review; preserve valid coverage."},
                                "deliberate_copy": {"severity": None, "recommendation": "Document the reason."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask the owner for the copy's purpose."}},
                      guidance="Warning needs proposal.requirement_ref citing the documented requirement.")

    # step 9 — cross-negative conflicts + non-additive exposure
    xn = ctx.check("cross_negative_conflicts", "017-style conflict screen and distinct exposure",
                   {**QUERIES, "negative_keywords": ["text", "match_type", "level", "campaign_id"],
                    "ad_groups": ["id", "campaign_id"]})
    if xn.runnable:
        for g in neg_gaps:
            xn.partial(g)
        flagged_q = {q for q, v in qmap.items() if len(v) > 1}
        set_texts = {key[0] for key in set_findings}
        keys = set().union(*(row_keys.get(q, set()) for q in flagged_q | (set_texts & set(qmap))))
        cost = sum(ctx.money(r.get("cost")) or 0 for r in {_row_key(r): r for r in ctx.rows("search_terms")}.values()
                   if _row_key(r) in keys)
        xn.observe("Distinct query-row exposure across duplicate/multi-trigger findings (not savings)",
                   rows=len(keys), cost=cost)


def verify(ctx, item, decision) -> list[str]:
    """Rules: requirement_ref for redundancy; scoped, conflict-free cross-negatives for routing."""
    outcome, p = decision.get("outcome"), decision.get("proposal") or {}
    if item.condition_key == "duplicate_control_burden" and outcome == "redundant_documented":
        return [] if str(p.get("requirement_ref") or "").strip() else ["proposal.requirement_ref required"]
    if item.condition_key != "routing_contradiction" or outcome != "contradicts_routing":
        return []
    qn = item.entity["normalized_query"]
    wrong = {(x["campaign_id"], x["ad_group_id"]) for x in item.evidence["non_approved_triggers"]}
    problems = []
    scopes = effective_negatives(ctx)[0] if ctx.table("ad_groups") is not None and ctx.table("negative_keywords") is not None else {}
    for n in p.get("negatives") or []:
        text, match = str(n.get("negative") or "").strip(), normalize_match(n.get("match_type"))
        level, cid, gid = str(n.get("level") or "").lower(), str(n.get("campaign_id") or ""), str(n.get("ad_group_id") or "")
        if not text or match is None or level not in ("campaign", "ad_group") or not cid or (level == "ad_group" and not gid):
            problems.append("each negative needs negative, match_type, level campaign|ad_group, campaign_id (+ad_group_id)")
            continue
        targets = {w for w in wrong if w[0] == cid and (level == "campaign" or w[1] == gid)}
        if not targets:
            problems.append(f"negative scope {cid}/{gid or '*'} is not a non-approved trigger scope")
        approved = item.evidence["approved"]
        if level == "campaign" and cid == str(approved.get("campaign_id")):
            problems.append("campaign-level negative would also block the approved ad group")
        if blocks(text, match, qn) is not True:
            problems.append(f"'{text}' ({match}) does not block '{qn}'")
        in_scope = lambda r: str(r.get("campaign_id")) == cid and (level == "campaign" or str(r.get("ad_group_id")) == gid)
        for k in ctx.rows("keywords"):
            if in_scope(k) and _active(k) and blocks(text, match, k.get("text")):
                problems.append(f"would block keyword text '{k.get('text')}' ({k.get('id')})")
        for r in ctx.rows("search_terms"):
            q2 = V.norm_text(r.get("search_term"))
            if in_scope(r) and q2 != qn and (V.num(r.get("conversions")) or 0) > 0 and blocks(text, match, q2):
                problems.append(f"would block converting query '{q2}'")
        for b in ctx.profile.get("brand_terms") or []:
            if blocks(text, match, b) and V.norm_text(b) != qn:
                problems.append(f"would block brand term '{b}'")
        if scopes and not any(scopes.get(w) is not None for w in targets):
            problems.append("target ad group not in ad_groups inventory")
    return sorted(set(problems))


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
