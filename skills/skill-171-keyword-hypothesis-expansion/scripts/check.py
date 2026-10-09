"""check.py — skill-171 deterministic evidence assembly and verification for keyword hypotheses.

exports: SKILL | VERSION | SEED_CAP | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-171-keyword-hypothesis-expansion/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #15 Automated GPT Keyword Suggestions (nilsrooijmans.com) — clean-room reimplementation of
         "seed from top converting keywords, suggest only keywords not already in the account"; the AI proposes,
         verify() enforces the not-already-present rule plus negatives/brand-policy/excluded-term screens.
         index #109 Amazon Autocomplete keyword opportunities — REFUSED: querying a third-party autocomplete
         service with account seeds violates DATA_CONTRACT rule 8 (no third-party queries during analysis).
rules:   First-party evidence only: seeds come from search_terms, keyword_metrics (joined by keyword ID),
         profile taxonomy/themes and locally saved page text (HTTP 200, evidence_ref, exact final_url link).
         Never fetch pages or suggestion services; never rank by CPA; immature windows keep seeds descriptive.
         Hypotheses are reviewed only for active SEARCH campaigns with a declared profile
         campaign_objectives[id].brand_policy in POLICIES; brand_only/nonbrand_only also need profile.brand_terms,
         competitor_only needs profile.competitor_terms. Unknown policy → partial, never permissive.
         profile.excluded_intent_terms (account) + campaign_objectives[id].excluded_intent_terms are LITERAL
         phrases (PHRASE containment); profile.excluded_intents descriptions are review guidance only.
         verify() rejects: duplicate normalized text+match in the same ad group (inventory or proposal),
         text equal to a reported query in the campaign (skill-013 owns it), effective-negative blocks or
         undecidable literal matches, brand-policy violations, excluded terms, unknown ad group, uncited or
         unknown evidence_ref, operators in text, and any volume/uplift forecast keys.
         Theme coverage absence is reviewed only when the keywords manifest certifies completeness.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes5 | initial recipe script
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402
from adsrun.negatives import blocks, effective_negatives, normalize_match, tokens  # noqa: E402

SKILL = "skill-171-keyword-hypothesis-expansion"
VERSION = "1.0.0"
SEED_CAP = 25
POLICIES = ("brand_only", "nonbrand_only", "competitor_only", "mixed")
SOURCES = ("seed_query", "seed_keyword", "taxonomy", "page")
FORECAST_KEYS = ("expected_clicks", "expected_impressions", "expected_conversions", "expected_volume",
                 "incremental_volume", "search_volume", "uplift", "forecast")
_OPERATOR = re.compile(r"[\[\]\"+]")
_INACTIVE = ("REMOVED", "DELETED", "PAUSED")
KW_COLS = ["id", "campaign_id", "ad_group_id", "text", "match_type", "status"]


def _active(row) -> bool:
    return str(row.get("status") or "").upper() not in _INACTIVE


def _objective(ctx, cid: str) -> dict:
    objectives = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objectives, dict):
        return {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None)
    return obj if isinstance(obj, dict) else {}


def _terms(values) -> list[str]:
    return sorted({V.norm_text(t) for t in (values or []) if V.norm_text(t)})


def _contains(term: str, text: str) -> bool:
    """Literal contiguous phrase containment (same semantics as a PHRASE negative)."""
    return blocks(term, "PHRASE", text) is True


def _url(v) -> str:
    return str(v or "").strip().lower().rstrip("/")


def _excluded_terms(ctx, cid: str) -> list[str]:
    return _terms(list(ctx.profile.get("excluded_intent_terms") or [])
                  + list(_objective(ctx, cid).get("excluded_intent_terms") or []))


def _scope(ctx):
    """Active SEARCH campaigns → sorted active ad group ids; plus policy gaps per campaign."""
    groups: dict[str, list[dict]] = {}
    for g in ctx.rows("ad_groups"):
        if _active(g):
            groups.setdefault(str(g.get("campaign_id")), []).append({"id": str(g.get("id")), "name": g.get("name")})
    camps = {}
    for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
        if str(c.get("channel_type") or "").upper() == "SEARCH" and _active(c):
            cid = str(c.get("id"))
            camps[cid] = sorted(groups.get(cid, []), key=lambda g: g["id"])
    return camps


def _policy_gap(ctx, cid: str) -> tuple[str | None, list[str]]:
    policy = str(_objective(ctx, cid).get("brand_policy") or "").lower()
    if policy not in POLICIES:
        return f"campaign {cid}: brand_policy unknown", [f"profile.campaign_objectives[{cid}].brand_policy"]
    if policy in ("brand_only", "nonbrand_only") and not _terms(ctx.profile.get("brand_terms")):
        return f"campaign {cid}: {policy} needs brand_terms", ["profile.brand_terms"]
    if policy == "competitor_only" and not _terms(ctx.profile.get("competitor_terms")):
        return f"campaign {cid}: competitor_only needs competitor_terms", ["profile.competitor_terms"]
    return None, []


def run(ctx) -> None:
    """Run first-party seed collection, brand-policy scoping and keyword hypothesis / theme-coverage reviews.

    Rules:   Seeds only from local first-party evidence; never fetch pages or rank by CPA; immature windows stay
             descriptive. Hypotheses reviewed only for active SEARCH campaigns with a declared brand_policy (unknown →
             partial). All outcomes are Info; theme gaps reviewed only with a completeness-certified keywords manifest.
             verify() rejects duplicates, reported queries, negative-blocked, policy-violating or forecast-bearing
             proposals.
    """
    scope = ctx.check("campaign_scope", "Active Search campaigns, ad groups and brand policy",
                      {"campaigns": ["id", "channel_type", "status"], "ad_groups": ["id", "campaign_id", "status"]})
    dependents = (("query_seeds", "Converting reported-query seeds"),
                  ("keyword_seeds", "Converting keyword seeds"),
                  ("page_seeds", "Saved landing-page seeds"),
                  ("theme_coverage", "Taxonomy theme keyword coverage"),
                  ("hypothesis_review", "Evidence-cited keyword hypotheses"))
    if not scope.runnable:
        for cid, title in dependents:
            ctx.check(cid, title).skip("campaign scope unavailable", scope.missing)
        return
    camps = _scope(ctx)
    if not camps:
        for cid, title in dependents:
            ctx.check(cid, title, applicable=False, na_reason="no active SEARCH campaign in the export")
        scope.observe("No active SEARCH campaigns; keyword hypotheses not applicable")
        return
    eligible = []
    for cid in sorted(camps):
        gap, missing = _policy_gap(ctx, cid)
        if gap:
            scope.partial(f"{gap}; hypotheses not reviewed", missing)
        elif not camps[cid]:
            scope.partial(f"campaign {cid}: no active ad groups")
        else:
            eligible.append(cid)
    scope.observe("Search campaigns in scope", campaigns=sorted(camps), eligible_for_review=eligible,
                  brand_terms=len(_terms(ctx.profile.get("brand_terms"))),
                  competitor_terms=len(_terms(ctx.profile.get("competitor_terms"))),
                  maturity=ctx.mature, maturity_note=ctx.maturity_note)

    # -- step 2: converting reported queries
    query_seeds: dict[str, list[dict]] = {}
    qs = ctx.check("query_seeds", "Converting reported-query seeds",
                   {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "conversions"]})
    if qs.runnable:
        agg: dict[tuple, list] = {}
        unknown = 0
        for r in ctx.rows("search_terms"):
            cid = str(r.get("campaign_id"))
            if cid not in camps:
                continue
            conv = V.num(r.get("conversions"))
            if conv is None:
                unknown += 1
                continue
            key = (cid, str(r.get("ad_group_id") or ""), V.norm_text(r.get("search_term")))
            acc = agg.setdefault(key, [0.0, 0.0])
            acc[0] += conv
            acc[1] += V.num(r.get("clicks")) or 0
        for (cid, gid, q), (conv, clicks) in agg.items():
            if conv > 0:
                query_seeds.setdefault(cid, []).append({"search_term": q, "ad_group_id": gid,
                                                        "conversions": conv, "clicks": clicks})
        for cid in sorted(camps):
            rows = sorted(query_seeds.get(cid, []), key=lambda s: (-s["conversions"], s["search_term"], s["ad_group_id"]))
            query_seeds[cid] = rows[:SEED_CAP]
            qs.observe(f"Campaign {cid}: converting query seeds", campaign_id=cid, converting_queries=len(rows),
                       passed_to_review=len(query_seeds[cid]), seed_cap=SEED_CAP,
                       seed_conversions=sum(s["conversions"] for s in rows))
        if unknown:
            qs.partial(f"{unknown} query rows with unknown conversions excluded from seeds")
        if ctx.mature is not True:
            qs.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): seeds descriptive only, conversions may be incomplete")
        qs.partial("privacy-limited query reporting: unreported queries are unobserved, not absent")

    # -- step 3: converting keywords (index #15 seed input)
    keyword_seeds: dict[str, list[dict]] = {}
    ks = ctx.check("keyword_seeds", "Converting keyword seeds",
                   {"keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "conversions"], "keywords": KW_COLS})
    if ks.runnable:
        inv = {str(k.get("id")): k for k in ctx.rows("keywords") if _active(k)}
        conv_by: dict[str, float] = {}
        rows_by: dict[str, int] = {}
        unknown = orphan = 0
        for m in ctx.rows("keyword_metrics"):
            kid = str(m.get("keyword_id"))
            k = inv.get(kid)
            if k is None or str(k.get("campaign_id")) != str(m.get("campaign_id")):
                orphan += 1
                continue
            conv = V.num(m.get("conversions"))
            if conv is None:
                unknown += 1
                continue
            conv_by[kid] = conv_by.get(kid, 0.0) + conv
            rows_by[kid] = rows_by.get(kid, 0) + 1
        multi = sorted(k for k, n in rows_by.items() if n > 1)
        if multi:
            ks.partial(f"{len(multi)} keywords have several metric rows (summed); certify no total+segment mixing")
        for kid in sorted(conv_by, key=lambda x: (-conv_by[x], x)):
            k = inv[kid]
            cid = str(k.get("campaign_id"))
            if cid in camps and conv_by[kid] > 0:
                keyword_seeds.setdefault(cid, []).append({"keyword_id": kid, "text": V.norm_text(k.get("text")),
                                                          "match_type": normalize_match(k.get("match_type")),
                                                          "ad_group_id": str(k.get("ad_group_id")),
                                                          "conversions": conv_by[kid]})
        for cid in sorted(camps):
            total = len(keyword_seeds.get(cid, []))
            keyword_seeds[cid] = keyword_seeds.get(cid, [])[:SEED_CAP]
            ks.observe(f"Campaign {cid}: converting keyword seeds", campaign_id=cid, converting_keywords=total,
                       passed_to_review=len(keyword_seeds[cid]), seed_cap=SEED_CAP)
        if unknown or orphan:
            ks.partial(f"{unknown} rows with unknown conversions, {orphan} rows not joinable to active keywords by ID")
        if ctx.mature is not True:
            ks.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): seeds descriptive only")

    # -- step 4: saved landing-page text
    page_seeds: dict[str, list[dict]] = {}
    ps = ctx.check("page_seeds", "Saved landing-page seeds",
                   {"external/landing_page_content": ["url", "captured_at", "http_status", "title",
                                                      "main_content_excerpt", "evidence_ref"]})
    if ps.runnable:
        links: dict[str, set] = {}
        kw_t, ads_t = ctx.table("keywords"), ctx.table("ads")
        sources = [t for t in (kw_t, ads_t) if t is not None and "final_url" in t.columns and "campaign_id" in t.columns]
        if not sources:
            ps.partial("no keywords/ads final_url with campaign_id: pages cannot be linked to campaigns",
                       ["keywords:final_url", "ads:final_url"])
        for t in sources:
            for r in t.rows:
                if _active(r) and _url(r.get("final_url")):
                    links.setdefault(_url(r.get("final_url")), set()).add(str(r.get("campaign_id")))
        failed = unlinked = 0
        for p in sorted(ctx.rows("external/landing_page_content"), key=lambda r: (_url(r.get("url")), str(r.get("evidence_ref")))):
            if V.integer(p.get("http_status")) != 200 or not str(p.get("evidence_ref") or "").strip():
                failed += 1
                continue
            cids = sorted(c for c in links.get(_url(p.get("url")), set()) if c in camps)
            if not cids:
                unlinked += 1
                continue
            entry = {"evidence_ref": str(p.get("evidence_ref")).strip(), "url": p.get("url"),
                     "captured_at": p.get("captured_at"), "title": p.get("title"),
                     "excerpt": str(p.get("main_content_excerpt") or "")[:600]}
            for cid in cids:
                page_seeds.setdefault(cid, []).append(entry)
        ps.observe("Landing-page evidence linked by exact final URL", linked={c: len(v) for c, v in page_seeds.items()},
                   failed_or_uncited=failed, unlinked=unlinked)
        if failed:
            ps.partial(f"{failed} captures without HTTP 200 or evidence_ref are not evidence")

    # -- step 5: taxonomy theme coverage
    themes = _terms(ctx.profile.get("product_service_taxonomy"))
    tc = ctx.check("theme_coverage", "Taxonomy theme keyword coverage", {"keywords": KW_COLS})
    if tc.runnable and not themes:
        tc.skip("profile taxonomy missing", ["profile.product_service_taxonomy"])
    if tc.runnable:
        active_groups = {(cid, g["id"]) for cid, gs in camps.items() for g in gs}
        kws = [k for k in ctx.rows("keywords") if _active(k)
               and (str(k.get("campaign_id")), str(k.get("ad_group_id"))) in active_groups]
        complete = ctx.table("keywords").complete is True
        for theme in themes:
            need = set(tokens(theme))
            hits = sorted(str(k.get("id")) for k in kws if need <= set(tokens(k.get("text"))))
            tc.observe(f"Theme '{theme}': literal keyword coverage", theme=theme, covering_keywords=len(hits),
                       keyword_ids=hits[:10], inventory_complete=complete)
            if hits or not complete:
                continue
            tc.review("theme_without_keyword_coverage", {"theme": theme},
                      f"Taxonomy theme '{theme}' has no active Search keyword containing all its tokens. "
                      "Is it an untested gap, or already covered/intentionally unserved?",
                      evidence={"theme": theme, "active_search_keywords": len(kws),
                                "keyword_sample": sorted({V.norm_text(k.get("text")) for k in kws})[:40],
                                "campaign_objectives": {c: _objective(ctx, c) for c in sorted(camps)}},
                      outcomes={
                          "untested_gap": {"severity": "Info", "recommendation":
                                           "Draft verified hypotheses for this theme in the owning campaign."},
                          "covered_or_intentional": {"severity": None, "recommendation":
                                                     "No action; variants/synonyms cover it or it is not served."},
                          "uncertain": {"severity": "Info", "recommendation":
                                        "Ask the client whether and where this theme is sold."},
                      },
                      guidance="Literal token screen only: plurals, synonyms and close variants may already cover it. "
                               "Use profile objectives/service_area; unknown intent → uncertain.")
        if not complete:
            tc.partial("keywords manifest does not certify completeness: absent themes are unknown, not gaps")

    # -- step 6: hypothesis review per eligible campaign
    hr = ctx.check("hypothesis_review", "Evidence-cited keyword hypotheses",
                   {"keywords": KW_COLS, "ad_groups": ["id", "campaign_id"],
                    "negative_keywords": ["text", "match_type", "level", "campaign_id"]})
    if not hr.runnable:
        return
    _, gaps = effective_negatives(ctx)
    for g in gaps:
        hr.partial(g)
    for cid in sorted(set(camps) - set(eligible)):
        hr.partial(f"campaign {cid} not reviewed (see campaign_scope)")
    for cid in eligible:
        obj = _objective(ctx, cid)
        cthemes = _terms(obj.get("themes")) or themes
        ev = {"campaign_id": cid, "brand_policy": str(obj.get("brand_policy")).lower(), "role": obj.get("role"),
              "ad_groups": camps[cid], "query_seeds": query_seeds.get(cid, []),
              "keyword_seeds": keyword_seeds.get(cid, []), "taxonomy_themes": cthemes,
              "pages": page_seeds.get(cid, []), "brand_terms": _terms(ctx.profile.get("brand_terms")),
              "competitor_terms": _terms(ctx.profile.get("competitor_terms")),
              "excluded_intent_terms": _excluded_terms(ctx, cid),
              "excluded_intents": ctx.profile.get("excluded_intents") or [],
              "maturity": {"mature": ctx.mature, "note": ctx.maturity_note}}
        if not (ev["query_seeds"] or ev["keyword_seeds"] or ev["pages"] or cthemes):
            hr.partial(f"campaign {cid}: no first-party seed evidence; no hypotheses requested")
            continue
        hr.review("keyword_hypotheses", {"campaign_id": cid},
                  f"Which new keyword hypotheses for campaign {cid} are grounded in the supplied first-party evidence?",
                  evidence=ev,
                  outcomes={
                      "hypotheses_proposed": {"severity": "Info", "recommendation":
                                              "Test the verified candidates as hypotheses; no guaranteed incremental volume."},
                      "no_supported_hypothesis": {"severity": None, "recommendation": "No candidates proposed."},
                      "uncertain": {"severity": "Info", "recommendation":
                                    "Request taxonomy, page text or campaign intent before drafting candidates."},
                  },
                  guidance="proposal.candidates = [{text, match_type EXACT|PHRASE|BROAD, ad_group_id, "
                           "source seed_query|seed_keyword|taxonomy|page, evidence_ref (seed text, theme or page "
                           "evidence_ref from this item)}]. Unobserved variants only: reported queries belong to "
                           "skill-013. Respect brand_policy and excluded_intents. No volume or uplift estimates.")
    hr.observe("Hypothesis reviews queued", campaigns=[x.entity["campaign_id"] for x in ctx.result.reviews
                                                         if x.condition_key == "keyword_hypotheses"])


def _refs(ev: dict, source: str) -> set[str]:
    if source == "seed_query":
        return {s["search_term"] for s in ev.get("query_seeds") or []}
    if source == "seed_keyword":
        return {s["text"] for s in ev.get("keyword_seeds") or []}
    if source == "taxonomy":
        return set(ev.get("taxonomy_themes") or [])
    return {p["evidence_ref"] for p in ev.get("pages") or []}


def _candidate_problems(ev: dict, cand, scopes, existing, reported, seen) -> list[str]:
    if not isinstance(cand, dict):
        return ["candidate must be an object"]
    raw = str(cand.get("text") or "")
    text, match = V.norm_text(raw), normalize_match(cand.get("match_type"))
    gid, cid = str(cand.get("ad_group_id") or ""), ev["campaign_id"]
    label = f"'{text}' ({match or cand.get('match_type')})"
    out = []
    if not text:
        return ["candidate text empty"]
    if _OPERATOR.search(raw) or text.startswith("-"):
        out.append(f"{label}: match operators in text; declare match_type explicitly")
    if match is None:
        out.append(f"{label}: match_type must be EXACT, PHRASE or BROAD")
    if gid not in {g["id"] for g in ev["ad_groups"]}:
        out.append(f"{label}: ad group {gid!r} is not an active ad group of campaign {cid}")
    forecast = sorted(k for k in cand if k in FORECAST_KEYS)
    if forecast:
        out.append(f"{label}: forecast fields {forecast} not allowed (hypothesis, no guaranteed volume)")
    source = str(cand.get("source") or "")
    ref = str(cand.get("evidence_ref") or "").strip()
    if source not in SOURCES:
        out.append(f"{label}: source must be one of {list(SOURCES)}")
    elif (V.norm_text(ref) if source != "page" else ref) not in _refs(ev, source):
        out.append(f"{label}: evidence_ref {ref!r} is not a {source} reference in the reviewed evidence")
    key = (gid, text, match)
    if key in seen:
        out.append(f"{label}: duplicated within the proposal for ad group {gid}")
    seen.add(key)
    if (cid, gid, text, match) in existing:
        out.append(f"{label}: already a keyword with the same match type in ad group {gid}")
    if text in reported.get(cid, set()):
        out.append(f"{label}: equals a reported query in campaign {cid}; route to skill-013")
    for n in scopes.get((cid, gid), []):
        hit = blocks(n.text, n.match, text)
        if hit is None:
            out.append(f"{label}: literal negative rules cannot decide '{n.text}' ({n.match}, {n.ref})")
        elif hit:
            out.append(f"{label}: blocked by {n.match} negative '{n.text}' ({n.ref})")
    brand = [b for b in ev["brand_terms"] if _contains(b, text)]
    comp = [c for c in ev["competitor_terms"] if _contains(c, text)]
    policy = ev["brand_policy"]
    if policy == "nonbrand_only" and brand:
        out.append(f"{label}: brand term {brand} in a nonbrand_only campaign")
    if policy == "brand_only" and not brand:
        out.append(f"{label}: no brand term in a brand_only campaign")
    if comp and policy != "competitor_only":
        out.append(f"{label}: competitor term {comp} outside a competitor_only campaign")
    if policy == "competitor_only" and not comp:
        out.append(f"{label}: no competitor term in a competitor_only campaign")
    if policy == "competitor_only" and brand:
        out.append(f"{label}: brand term {brand} in a competitor_only campaign")
    excluded = [t for t in ev["excluded_intent_terms"] if _contains(t, text)]
    if excluded:
        out.append(f"{label}: contains excluded-intent term {excluded}")
    return out


def verify(ctx, item, decision) -> list[str]:
    """Rules: only 'hypotheses_proposed' carries candidates; every candidate must pass all module-rule screens."""
    if item.condition_key != "keyword_hypotheses" or decision.get("outcome") != "hypotheses_proposed":
        return []
    cands = (decision.get("proposal") or {}).get("candidates")
    if not isinstance(cands, list) or not cands:
        return ["proposal.candidates must be a non-empty list"]
    scopes, _ = effective_negatives(ctx)
    existing = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), V.norm_text(k.get("text")),
                 normalize_match(k.get("match_type")))
                for k in ctx.rows("keywords") if str(k.get("status") or "").upper() not in ("REMOVED", "DELETED")}
    reported: dict[str, set] = {}
    for r in ctx.rows("search_terms"):
        reported.setdefault(str(r.get("campaign_id")), set()).add(V.norm_text(r.get("search_term")))
    problems, seen = [], set()
    for cand in cands:
        problems += _candidate_problems(item.evidence, cand, scopes, existing, reported, seen)
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
