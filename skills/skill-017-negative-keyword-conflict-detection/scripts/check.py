"""check.py — skill-017 deterministic negative keyword conflict detection.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-017-negative-keyword-conflict-detection/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #90 Negative Keyword Conflicts (Google) and #85 Negative Keyword Conflicts — Updated (N. Rooijmans) —
           clean-room: effective-scope literal conflicts incl. shared lists; alerts become findings/review items.
rules:   Literal semantics only (adsrun.negatives.blocks); undecidable queries are reported as coverage, not blocks.
         Whether blocked text is DESIRED traffic is a business judgment → ai_review, never inferred here.
         A same-text negative/positive pair proves a literal block, not total suppression of the keyword.
         Critical only when a supplied diagnosis confirms the block AND the AI confirms evidenced material impact.
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
from adsrun.negatives import blocks, effective_negatives  # noqa: E402

SKILL = "skill-017-negative-keyword-conflict-detection"
VERSION = "1.0.0"

_ACTIVE = ("ENABLED", "ACTIVE", "")


def _active(row) -> bool:
    return str(row.get("status") or "").upper() in _ACTIVE


def run(ctx) -> None:
    """Run effective-negative resolution and literal block checks against keywords, served queries and diagnoses.

    Rules:   Literal adsrun.negatives.blocks only; undecidable pairs and unknown conversions → partial, never blocks.
             Negative-vs-keyword text blocks are Info + ai_review (Warning 'desired_blocked'); converting blocked
             queries are review-only. A supplied custom/query_eligibility diagnosis (blocked + intended_eligible) is a
             Warning; Critical only via its review outcome 'material_impact_evidenced'. Desired-traffic intent is never
             inferred here.
    """
    scope = ctx.check("effective_scope", "Resolve effective negatives per ad group",
                      {"ad_groups": ["id", "campaign_id"],
                       "negative_keywords": ["text", "match_type", "level", "campaign_id"]})
    if not scope.runnable:
        for cid, title in (("positive_text_conflicts", "Negatives blocking positive keyword text"),
                           ("observed_query_blocks", "Current negatives blocking observed queries"),
                           ("diagnosis_blocks", "Supplied eligibility diagnosis")):
            ctx.check(cid, title).skip("effective negative scope unavailable", scope.missing)
        return
    scopes, gaps = effective_negatives(ctx)
    for g in gaps:
        scope.partial(g)
    scope.observe("Effective negative scopes resolved", ad_groups=len(scopes),
                  negatives=sum(len(v) for v in scopes.values()))

    # -- literal conflicts with positive keyword text (step 7/8)
    pos = ctx.check("positive_text_conflicts", "Negatives blocking positive keyword text",
                    {"keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type"]})
    if pos.runnable:
        undecided = 0
        checked = 0
        for kw in ctx.rows("keywords"):
            if not _active(kw):
                continue
            key = (str(kw.get("campaign_id") or ""), str(kw.get("ad_group_id") or ""))
            for neg in scopes.get(key, []):
                checked += 1
                hit = blocks(neg.text, neg.match, kw.get("text"))
                if hit is None:
                    undecided += 1
                    continue
                if not hit:
                    continue
                entity = {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": kw.get("id"),
                          "negative": f"{neg.text} ({neg.match})", "negative_scope": neg.ref}
                ev = {"keyword_text": kw.get("text"), "keyword_match": kw.get("match_type"),
                      "rule": f"{neg.match} negative contained in literal keyword text"}
                prov = pos.finding("negative_blocks_positive_text", "Info", entity,
                            f"{neg.match} negative '{neg.text}' ({neg.ref}) blocks the literal query "
                            f"'{kw.get('text')}' of keyword {kw.get('id')}",
                            evidence=ev,
                            recommendation="Confirm whether this literal query is desired before narrowing or removing the negative.",
                            uncertainty="Literal text only: the keyword may still serve other queries; no lost-impression estimate.")
                pos.review("negative_blocks_positive_text", entity,
                           f"Is the literal query '{kw.get('text')}' desired traffic for campaign {key[0]}, "
                           f"or does '{neg.text}' intentionally route it elsewhere?",
                           evidence={**ev, "profile_objectives": ctx.profile.get("objectives"),
                                     "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(key[0])},
                           outcomes={
                               "desired_blocked": {"severity": "Warning", "recommendation":
                                                   "Narrow the negative scope/match type after checking every affected campaign."},
                               "intentional_routing": {"severity": None, "recommendation": "Keep; document the routing."},
                               "uncertain": {"severity": "Info", "recommendation": "Ask the client which intent owns this query."},
                           },
                           guidance="Use only approved profile intents/objectives; unknown intent → uncertain.",
                           provisional=prov)
        if undecided:
            pos.partial(f"{undecided} keyword/negative pairs beyond literal rules (operators or >16 words)")
        pos.observe("Positive keyword texts evaluated against effective negatives", pairs=checked, undecided=undecided)

    # -- observed queries that current negatives would now block (step 6/10)
    obs = ctx.check("observed_query_blocks", "Current negatives blocking observed queries",
                    {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "conversions"]})
    if obs.runnable:
        n = unknown_conv = 0
        for st in ctx.rows("search_terms"):
            key = (str(st.get("campaign_id") or ""), str(st.get("ad_group_id") or ""))
            conv = V.num(st.get("conversions"))
            if conv is None:
                unknown_conv += 1
                continue
            for neg in scopes.get(key, []):
                if blocks(neg.text, neg.match, st.get("search_term")) and conv > 0:
                    n += 1
                    entity = {"campaign_id": key[0], "ad_group_id": key[1], "search_term": st.get("search_term"),
                              "negative": f"{neg.text} ({neg.match})", "negative_scope": neg.ref}
                    obs.review("negative_blocks_converting_query", entity,
                               f"The current negative '{neg.text}' blocks '{st.get('search_term')}', which converted "
                               f"{conv:g} times in the window. Was the negative added deliberately after this traffic?",
                               evidence={"clicks": V.num(st.get("clicks")), "conversions": conv,
                                         "cost": ctx.money(st.get("cost"))},
                               outcomes={
                                   "desired_blocked": {"severity": "Warning", "recommendation":
                                                       "Review the negative; the query converted before it was blocked."},
                                   "intentional": {"severity": None, "recommendation": "Keep; note the decision date."},
                                   "uncertain": {"severity": "Info", "recommendation": "Check change history (skill-131)."},
                               },
                               guidance="Historical served metrics cannot measure traffic the negative now prevents.")
        if unknown_conv:
            obs.partial(f"{unknown_conv} query rows with unknown conversions not evaluated")
        obs.observe("Converting observed queries blocked by a current negative", count=n)

    # -- supplied diagnosis (optional)
    diag = ctx.check("diagnosis_blocks", "Supplied eligibility diagnosis",
                     {"custom/query_eligibility": ["query", "campaign_id", "diagnosis", "intended_eligible"]})
    if diag.runnable:
        for r in ctx.rows("custom/query_eligibility"):
            if "block" in str(r.get("diagnosis") or "").lower() and V.boolean(r.get("intended_eligible")):
                entity = {"campaign_id": r.get("campaign_id"), "ad_group_id": r.get("ad_group_id"),
                          "query": r.get("query"), "negative_id": r.get("negative_id")}
                diag.finding("diagnosis_confirms_block", "Warning", entity,
                             f"Diagnosis at {r.get('checked_at')} confirms '{r.get('query')}' is blocked although intended eligible",
                             evidence={"evidence_ref": r.get("evidence_ref"), "checked_at": r.get("checked_at")},
                             recommendation="Adjust the blocking negative after reviewing all scopes it protects.",
                             uncertainty="Diagnosis is valid only for the checked query, time and scope.")
                diag.review("diagnosis_confirms_block", entity,
                            "Is there independent evidence of MATERIAL impact (e.g. lost conversions/revenue) for this blocked query?",
                            evidence={"evidence_ref": r.get("evidence_ref")},
                            outcomes={"material_impact_evidenced": {"severity": "Critical", "recommendation":
                                                                    "Prioritize the fix; cite the impact evidence."},
                                      "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}})


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'material_impact_evidenced' requires an evidence reference in the decision."""
    if decision.get("outcome") == "material_impact_evidenced" and not (decision.get("proposal") or {}).get("evidence_ref"):
        return ["material impact needs proposal.evidence_ref pointing at supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
