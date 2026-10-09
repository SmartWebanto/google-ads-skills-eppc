"""check.py — skill-014 deterministic search-term negative screening with verified negative proposals.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-014-search-term-mining-negatives/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #63 Search Query Report Analyses for Negative Keyword Suggestions (Google) — clean-room: query screening
           with per-campaign materiality; negatives are verified proposals, never applied.
         index #61 Exclude Keywords Based On Sentiment Analysis (F. Harnois) — partial: sentiment/intent is part of the
           AI relevance review against approved excluded_intents; no automatic exclusion from a sentiment score.
rules:   Business relevance / excluded intent is AI judgment (ai_review); the script never labels waste.
         Material = query cost >= spend_floor resolved for ITS campaign; sub-floor queries reach Info at most.
         Zero-conversion screening needs ctx.mature True and ctx.tracking_for_campaign(cid) True; else partial.
         Brand terms take precedence: brand queries are never negative candidates.
         verify(): an accepted negative proposal MUST block the reviewed query and MUST NOT block any
         converting query, positive keyword text or brand query in its effective scope.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | pilot deterministic check
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

SKILL = "skill-014-search-term-mining-negatives"
VERSION = "1.0.0"
NEEDS = {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]}


def _contains_term(query: str, term: str) -> bool:
    return blocks(term, "PHRASE", query) is True


def run(ctx) -> None:
    """Run query-coverage reconciliation and per-query negative-candidate screening against spend_floor.

    Rules:   Excluded, brand-containing and already-blocked queries never become candidates. Queries >= their
             campaign spend_floor go to ai_review 'query_negative_candidate' (Warning only on reviewed outcomes);
             zero-conversion Info + 'irrelevant_zero_conversion' need ctx.mature True and tracking_for_campaign True.
             Sub-floor queries reach Info at most (batch review); unresolved spend_floor → partial, no screening.
    """
    brand = [t for t in (ctx.profile.get("brand_terms") or []) if t]
    competitors = [t for t in (ctx.profile.get("competitor_terms") or []) if t]
    excluded = ctx.profile.get("excluded_intents") or []

    cov = ctx.check("query_coverage", "Reconcile reported queries with campaign totals",
                    {**NEEDS, "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if cov.runnable:
        by_c: dict[str, list[float]] = {}
        for r in ctx.rows("search_terms"):
            acc = by_c.setdefault(str(r["campaign_id"]), [0.0, 0.0])
            acc[0] += V.num(r.get("clicks")) or 0
            acc[1] += ctx.money(r.get("cost")) or 0
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid not in by_c:
                continue
            cc, ccost = V.num(m.get("clicks")), ctx.money(m.get("cost"))
            cov.observe(f"Campaign {cid}: reported queries cover part of campaign traffic", campaign_id=cid,
                        query_clicks=by_c[cid][0], campaign_clicks=cc, click_share=V.ratio(by_c[cid][0], cc),
                        query_cost=by_c[cid][1], campaign_cost=ccost, cost_share=V.ratio(by_c[cid][1], ccost))
        cov.partial("privacy-limited query reporting: unreported traffic is unobserved, not zero")

    screen = ctx.check("query_review", "Material and sub-floor query intent screening", NEEDS)
    if not screen.runnable:
        return
    if ctx.mature is not True:
        screen.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    tracking_gaps: dict[str, str] = {}
    scopes, gaps = effective_negatives(ctx) if ctx.table("negative_keywords") and ctx.table("ad_groups") else ({}, [
        "negative inventory missing: existing protection unknown"])
    for g in gaps:
        screen.partial(g)
    sub_floor: list[dict] = []
    unresolved_floor = set()
    for r in sorted(ctx.rows("search_terms"), key=lambda r: (str(r["campaign_id"]), str(r["search_term"]))):
        q, cid, gid = str(r["search_term"]), str(r["campaign_id"]), str(r.get("ad_group_id") or "")
        cost, conv, clicks = ctx.money(r.get("cost")), V.num(r.get("conversions")), V.num(r.get("clicks"))
        if str(r.get("added_excluded") or "").upper() in ("EXCLUDED", "ADDED_EXCLUDED"):
            continue
        if any(_contains_term(q, b) for b in brand):
            screen.observe(f"Brand query protected from negative proposals: '{q}'", campaign_id=cid, cost=cost)
            continue
        protected = [n for n in scopes.get((cid, gid), []) if blocks(n.text, n.match, q)]
        if protected:
            screen.observe(f"'{q}' is already blocked by current negative '{protected[0].text}' "
                           f"({protected[0].ref}); exposure predates or bypassed it", campaign_id=cid, cost=cost)
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            unresolved_floor.add(f"{cid}: {floor.reason}")
            continue
        entity = {"campaign_id": cid, "ad_group_id": gid, "search_term": q}
        ev = {"cost": cost, "clicks": clicks, "conversions": conv, "matched_keyword": r.get("matched_keyword"),
              "match_type": r.get("match_type"), "spend_floor": floor.value, "spend_floor_source": floor.source,
              "excluded_intents": excluded, "competitor_term": any(_contains_term(q, c) for c in competitors)}
        if cost is None or cost < floor.value:
            if cost:
                sub_floor.append({"search_term": q, "campaign_id": cid, "ad_group_id": gid, "cost": cost,
                                  "conversions": conv})
            continue
        tracking_ok, tracking_note = ctx.tracking_for_campaign(cid)
        if tracking_ok is not True:
            tracking_gaps[cid] = tracking_note
        zero_conv_ok = ctx.mature is True and tracking_ok is True
        ev["tracking"] = tracking_note
        prov = None
        if zero_conv_ok and conv == 0:
            prov = screen.finding("zero_conversion_query", "Info", entity,
                                  f"'{q}' spent {cost:.2f} {ctx.currency} with 0 conversions in a mature window "
                                  f"(spend_floor {floor.value:g})", evidence=ev,
                                  recommendation="Review relevance before any exclusion; exposure is not savings.",
                                  uncertainty="Zero conversions can reflect lag, long sales cycles or assisted value.")
        outcomes = {
            "business_excluded": {"severity": "Warning", "recommendation":
                                  "Add the verified negative proposal at the narrowest reviewed scope."},
            "relevant_keep": {"severity": None, "recommendation": "Keep serving; no negative."},
            "uncertain": {"severity": "Info", "recommendation": "Ask the client whether this intent is served."},
        }
        if zero_conv_ok and conv == 0:
            outcomes["irrelevant_zero_conversion"] = {"severity": "Warning", "recommendation":
                                                      "Exclude via the verified negative proposal; monitor adjacent queries."}
        screen.review("query_negative_candidate", entity,
                      f"Is '{q}' (campaign {cid}) business-excluded or irrelevant to the approved offer?",
                      evidence=ev, outcomes=outcomes, provisional=prov,
                      guidance="Judge only against profile excluded_intents, objectives and campaign role. Jobs, free, "
                               "DIY/how-to and competitor terms are not universal waste. For Warning outcomes supply "
                               "proposal {negative, match_type, level: campaign|ad_group, scope_id}.")
    if sub_floor:
        screen.review("sub_floor_excluded_intents", {"batch": "sub_floor_queries"},
                      "Which of these below-floor queries match an approved excluded intent?",
                      evidence={"queries": sub_floor, "excluded_intents": excluded},
                      outcomes={"some_excluded": {"severity": "Info", "recommendation":
                                                  "Optional hygiene negatives; exposure below materiality."},
                                "none_excluded": {"severity": None, "recommendation": "No action."}},
                      guidance="For some_excluded, list proposal.queries as {search_term, campaign_id, ad_group_id} entries from "
                               "evidence and proposal.negatives as {negative, match_type, level, campaign_id[, ad_group_id]}.")
    for cid, note in sorted(tracking_gaps.items()):
        screen.partial(f"zero-conversion Warning path disabled: {note}")
    for u in sorted(unresolved_floor):
        screen.partial(f"spend_floor unresolved for campaign {u}")
    screen.observe("Query screening totals", material_reviews=sum(1 for x in ctx.result.reviews
                                                                  if x.condition_key == "query_negative_candidate"),
                   sub_floor_queries=len(sub_floor))


def _normalize(proposal: dict) -> tuple[dict | None, str]:
    """Explicit {text, match, level, campaign_id, ad_group_id} or (None, problem)."""
    text, match = str(proposal.get("negative") or "").strip(), normalize_match(proposal.get("match_type"))
    level = str(proposal.get("level") or "").lower()
    cid = str(proposal.get("campaign_id") or (proposal.get("scope_id") if level == "campaign" else "") or "")
    gid = str(proposal.get("ad_group_id") or (proposal.get("scope_id") if level == "ad_group" else "") or "")
    if not text or match is None or level not in ("campaign", "ad_group") or not cid or (level == "ad_group" and not gid):
        return None, ("proposal needs negative, match_type EXACT|PHRASE|BROAD, level campaign|ad_group, "
                      "campaign_id and (for ad_group) ad_group_id")
    return {"text": text, "match": match, "level": level, "campaign_id": cid,
            "ad_group_id": gid if level == "ad_group" else None}, ""


def _collisions(ctx, n: dict) -> list[str]:
    """Converting queries, active positive keyword texts and brand terms the negative would block in scope."""
    in_scope = lambda r: str(r.get("campaign_id")) == n["campaign_id"] and (
        n["ad_group_id"] is None or str(r.get("ad_group_id")) == n["ad_group_id"])
    out = []
    for r in ctx.rows("search_terms"):
        if in_scope(r) and (V.num(r.get("conversions")) or 0) > 0 and blocks(n["text"], n["match"], r.get("search_term")):
            out.append(f"'{n['text']}' would block converting query '{r.get('search_term')}'")
    for k in ctx.rows("keywords"):
        if in_scope(k) and str(k.get("status") or "ENABLED").upper() == "ENABLED" and blocks(n["text"], n["match"], k.get("text")):
            out.append(f"'{n['text']}' would block positive keyword text '{k.get('text')}' ({k.get('id')})")
    for b in ctx.profile.get("brand_terms") or []:
        if blocks(n["text"], n["match"], b):
            out.append(f"'{n['text']}' would block brand term '{b}'")
    return out


def verify(ctx, item, decision) -> list[str]:
    """Rules: every proposed negative is scope-normalized and collision-checked."""
    outcome = decision.get("outcome")
    proposal = decision.get("proposal") or {}
    if item.condition_key == "sub_floor_excluded_intents":
        if outcome != "some_excluded":
            return []
        batch = {(q["search_term"], str(q["campaign_id"]), str(q["ad_group_id"])) for q in item.evidence["queries"]}
        problems, claimed = [], []
        for q in proposal.get("queries") or []:
            key = (str((q or {}).get("search_term") or ""), str((q or {}).get("campaign_id") or ""),
                   str((q or {}).get("ad_group_id") or "")) if isinstance(q, dict) else None
            if key is None or key not in batch:
                problems.append(f"query {q!r} is not a {{search_term, campaign_id, ad_group_id}} entry of the reviewed batch")
            else:
                claimed.append(key)
        if not claimed:
            problems.append("proposal.queries must list at least one reviewed query")
        negs = []
        for raw in proposal.get("negatives") or []:
            n, err = _normalize(raw)
            if n is None:
                problems.append(err)
            else:
                negs.append(n)
        if not negs:
            problems.append("proposal.negatives must contain at least one valid negative")
        covers = lambda n, q: q[1] == n["campaign_id"] and (n["ad_group_id"] is None or q[2] == n["ad_group_id"]) \
            and blocks(n["text"], n["match"], q[0]) is True
        for q in claimed:
            if negs and not any(covers(n, q) for n in negs):
                problems.append(f"claimed query '{q[0]}' ({q[1]}/{q[2]}) is blocked by none of the proposed negatives")
        for n in negs:
            if claimed and not any(covers(n, q) for q in claimed):
                problems.append(f"'{n['text']}' blocks none of the claimed queries in its scope")
            problems += _collisions(ctx, n)
        return problems
    if outcome not in ("business_excluded", "irrelevant_zero_conversion"):
        return []
    n, err = _normalize(proposal)
    if n is None:
        return [err]
    problems = []
    if n["campaign_id"] != item.entity["campaign_id"]:
        problems.append(f"proposal campaign {n['campaign_id']} differs from reviewed campaign {item.entity['campaign_id']}")
    if n["ad_group_id"] is not None and n["ad_group_id"] != item.entity["ad_group_id"]:
        problems.append(f"proposal ad group {n['ad_group_id']} differs from reviewed ad group {item.entity['ad_group_id']}")
    q = item.entity["search_term"]
    if blocks(n["text"], n["match"], q) is not True:
        problems.append(f"'{n['text']}' ({n['match']}) does not block the reviewed query '{q}'")
    return problems + _collisions(ctx, n)


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
