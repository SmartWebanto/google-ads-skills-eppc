"""check.py — skill-023 deterministic query-to-keyword mapping, lexical classes and guarded relevance review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-023-close-variant-query-expansion-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #65 Monitor Close Variants (nilsrooijmans.com) — clean-room reimplementation of per-keyword variant
         (non-literal) query monitoring with click/cost shares against the keyword's reported total
         index #60 Convert close variants into negative keywords (Klientboost) — clean-room reimplementation as an
         optional EXACT/PHRASE negative PROPOSAL inside the relevance review, collision-verified; never applied
         index #62 Make Phrase match Exact (Brainlabs) — clean-room reimplementation, opt-in via
         profile.exact_only_keyword_ids only: per listed ENABLED keyword, the reported non-literal queries it
         matched become one PROPOSAL of ad-group EXACT negatives, finalize-verified (EXACT, reviewed ad group,
         listed query only, never the keyword literal, a converting query or another active keyword); refused:
         the script's automatic creation of negatives in the account and its scheduled re-runs
rules:   Join queries to keywords ONLY by matched_keyword_id within the same campaign/ad group; keyword match type
         and the report's query-match classification (search_terms.match_type) stay separate fields.
         Lexical class on NFKC+casefold \\w+ tokens: Literal = equal sequence, Reorder = equal multiset,
         Other = everything else. Misspelling/plural/synonym labels are never inferred.
         Relevance (Supported/Excluded/Ambiguous/Unknown) is ai_review only. Warning outcomes exist only for
         queries with cost >= spend_floor of THEIR campaign; the zero-conversion Warning outcome additionally
         needs ctx.mature True and ctx.tracking_for_campaign(cid) True.
         Info findings: per ad group, keywords whose variant click share > 0.5; converting unadded variants.
         verify(): a proposed negative must be EXACT/PHRASE/BROAD at campaign/ad_group scope of the reviewed
         query, block it, and block no converting query, active positive keyword or brand term in scope; it is
         refused when shared-list links are unavailable. Canonical owner of negatives is skill-014.
         Hidden (privacy-omitted) terms are unknown, never zero; exposure is not savings.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx062 | opt-in exact_only_restriction review + verify (index #62)
"""
from __future__ import annotations

import re
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
from adsrun.negatives import blocks, effective_negatives, normalize_match, tokens  # noqa: E402

SKILL = "skill-023-close-variant-query-expansion-monitoring"
VERSION = "1.1.0"

ST_COLS = ["search_term", "campaign_id", "ad_group_id", "matched_keyword_id", "clicks", "cost", "conversions"]
KW_COLS = ["id", "campaign_id", "ad_group_id", "text", "match_type"]
_TOKEN = re.compile(r"\w+", re.UNICODE)
_ADDED = ("ADDED", "EXCLUDED", "ADDED_EXCLUDED")


def _toks(v) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize("NFKC", str(v or "")).casefold())


def lexical_class(query, keyword) -> str | None:
    q, k = _toks(query), _toks(keyword)
    if not q or not k:
        return None
    if q == k:
        return "Literal"
    if sorted(q) == sorted(k):
        return "Reorder"
    return "Other"


def _brand(ctx, text) -> bool:
    return any(blocks(b, "PHRASE", text) is True for b in (ctx.profile.get("brand_terms") or []) if b)


def _shared_links_known(ctx) -> bool:
    t = ctx.table("shared_negative_lists")
    return t is not None and any(c in t.columns for c in ("campaigns_applied", "campaign_ids"))


def run(ctx) -> None:
    """Run query-to-keyword joins, lexical classing, variant-share screens and guarded relevance review.

    Rules:   Joins only by matched_keyword_id inside campaign/ad group; unjoined rows → partial. Deterministic findings
             are Info only (variant click share > 0.5, converting unadded variant, zero-conversion variant). Relevance
             is ai_review; Warning outcomes need cost >= spend_floor of the query's campaign, and the zero-conversion
             path also ctx.mature True and ctx.tracking_for_campaign(cid) True. Hidden terms stay unknown, never
             savings. exact_only_restriction is not_applicable unless profile.exact_only_keyword_ids is a non-empty
             list and needs keywords:status; it only queues one review per listed ENABLED keyword.
    """
    ws = ctx.check("window_scope", "Account, window, snapshot and maturity",
                   {"account": ["currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if ws.runnable:
        ws.observe("Scope", currency=ctx.currency, period=[ctx.period_start, ctx.period_end], snapshot=ctx.snapshot,
                   conversion_date_basis=ctx.account.get("conversion_date_basis"), mature=ctx.mature,
                   maturity_note=ctx.maturity_note)
        if ctx.mature is not True:
            ws.partial(f"conversions not mature: {ctx.maturity_note}")

    cov = ctx.check("query_coverage", "Reported query totals vs campaign totals",
                    {"search_terms": ["search_term", "campaign_id", "clicks", "cost"],
                     "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if cov.runnable:
        acc: dict[str, list] = {}
        for r in ctx.rows("search_terms"):
            a = acc.setdefault(str(r.get("campaign_id")), [0.0, 0.0, 0])
            c, k = V.num(r.get("clicks")), ctx.money(r.get("cost"))
            if c is None or k is None:
                a[2] += 1
                continue
            a[0] += c
            a[1] += k
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid not in acc:
                continue
            cc, ck = V.num(m.get("clicks")), ctx.money(m.get("cost"))
            cov.observe(f"Campaign {cid} reported-query coverage", campaign_id=cid, query_clicks=acc[cid][0],
                        campaign_clicks=cc, click_share=V.ratio(acc[cid][0], cc), query_cost=acc[cid][1],
                        campaign_cost=ck, cost_share=V.ratio(acc[cid][1], ck), rows_unknown_metrics=acc[cid][2])
        cov.partial("privacy-limited query reporting: unreported traffic is unknown, not zero")

    join = ctx.check("keyword_join", "Join queries to triggering keywords by ID", {"search_terms": ST_COLS,
                                                                                  "keywords": KW_COLS})
    later = (("lexical_class", "Reproducible lexical relation per query"),
             ("relevance_review", "Business relevance of variant queries"),
             ("variant_labels", "Supplied platform classifications"),
             ("class_aggregates", "Mature metrics by lexical class with sample gates"),
             ("zero_conversion_screen", "Mature zero-conversion variant exposure"),
             ("negative_routing", "Negative proposal scope and routing"),
             ("narrowing_hypothesis", "Controlled narrowing hypotheses"))
    eo_ids = ctx.profile.get("exact_only_keyword_ids")
    eo = ctx.check("exact_only_restriction", "Opt-in literal-only restriction of listed keywords (index #62)",
                   {"search_terms": ST_COLS, "keywords": KW_COLS + ["status"]}, applicable=bool(eo_ids),
                   na_reason="profile.exact_only_keyword_ids not set: no keyword was requested literal-only")
    if not join.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("query-to-keyword join unavailable (trigger IDs keep analysis ad-group level)",
                                       join.missing)
        return
    kws = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in ctx.rows("keywords")}
    seen, dup_rows, unjoined = set(), 0, 0
    rows = []
    for r in sorted(ctx.rows("search_terms"), key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")),
                                                              str(r.get("matched_keyword_id")), str(r.get("search_term")))):
        full = tuple(sorted((k, str(v)) for k, v in r.items()))
        if full in seen:
            dup_rows += 1
            continue
        seen.add(full)
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("matched_keyword_id")))
        kw = kws.get(key)
        if kw is None:
            unjoined += 1
            continue
        rows.append({"row": r, "kw": kw, "cid": key[0], "gid": key[1], "kid": key[2], "q": str(r.get("search_term")),
                     "clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")),
                     "conv": V.num(r.get("conversions")), "value": V.num(r.get("conversion_value")),
                     "impr": V.num(r.get("impressions")),
                     "class": lexical_class(r.get("search_term"), kw.get("text"))})
    join.observe("Query-to-keyword join", joined=len(rows), unjoined=unjoined, duplicate_source_rows=dup_rows)
    if unjoined:
        join.partial(f"{unjoined} query rows without a keyword match on campaign/ad group/matched_keyword_id")

    lex = ctx.check("lexical_class", "Reproducible lexical relation per query", {"search_terms": ST_COLS,
                                                                                  "keywords": KW_COLS})
    per_kw: dict[tuple, dict] = {}
    for x in rows:
        a = per_kw.setdefault((x["cid"], x["gid"], x["kid"]), {"kw": x["kw"], "clicks": 0.0, "variant_clicks": 0.0,
                                                               "cost": 0.0, "variant_cost": 0.0, "variants": [],
                                                               "unknown": 0})
        if x["clicks"] is None or x["cost"] is None or x["class"] is None:
            a["unknown"] += 1
            continue
        a["clicks"] += x["clicks"]
        a["cost"] += x["cost"]
        if x["class"] != "Literal":
            a["variant_clicks"] += x["clicks"]
            a["variant_cost"] += x["cost"]
            a["variants"].append({"search_term": x["q"], "class": x["class"], "clicks": x["clicks"], "cost": x["cost"],
                                  "conversions": x["conv"], "report_match": x["row"].get("match_type")})
        if x["class"] != "Literal" and (x["conv"] or 0) > 0 and \
                str(x["row"].get("added_excluded") or "").upper() not in _ADDED:
            lex.finding("converting_unadded_variant", "Info",
                        {"campaign_id": x["cid"], "ad_group_id": x["gid"], "keyword_id": x["kid"], "search_term": x["q"]},
                        f"Variant query '{x['q']}' converted {x['conv']:g} time(s) and is not added as a keyword",
                        evidence={"lexical_class": x["class"], "keyword_text": x["kw"].get("text"),
                                  "keyword_match": x["kw"].get("match_type"), "report_match": x["row"].get("match_type"),
                                  "clicks": x["clicks"], "cost": x["cost"], "conversions": x["conv"],
                                  "window": [ctx.period_start, ctx.period_end]},
                        recommendation="Candidate for keyword-addition review (owner skill-013).",
                        uncertainty="Observed conversions; adding the query does not guarantee incremental volume.")
    high: dict[tuple, list] = {}
    for (cid, gid, kid), a in sorted(per_kw.items()):
        share = V.ratio(a["variant_clicks"], a["clicks"])
        lex.observe(f"Keyword {kid} variant exposure", campaign_id=cid, ad_group_id=gid, keyword_id=kid,
                    keyword_text=a["kw"].get("text"), keyword_match=a["kw"].get("match_type"),
                    reported_clicks=a["clicks"], variant_clicks=a["variant_clicks"], variant_click_share=share,
                    reported_cost=a["cost"], variant_cost=a["variant_cost"],
                    variant_cost_share=V.ratio(a["variant_cost"], a["cost"]), variants=a["variants"])
        if share is not None and share > 0.5:
            high.setdefault((cid, gid), []).append({
                "keyword_id": kid, "keyword_text": a["kw"].get("text"), "keyword_match": a["kw"].get("match_type"),
                "variant_clicks": a["variant_clicks"], "reported_clicks": a["clicks"], "variant_click_share": share,
                "variant_cost": a["variant_cost"], "reported_cost": a["cost"]})
    for (cid, gid), kwl in sorted(high.items()):
        lex.finding("variant_share_over_half", "Info", {"campaign_id": cid, "ad_group_id": gid},
                    f"Ad group {gid}: {len(kwl)} keyword(s) get more than 50% of reported clicks from variant queries",
                    evidence={"keywords": kwl, "window": [ctx.period_start, ctx.period_end]},
                    calculation={"share": "variant (Reorder+Other) clicks / reported clicks of each keyword"},
                    recommendation="Review relevance of the variants (see variant exposure observations); a high share "
                                   "alone is not a defect.",
                    uncertainty="Reported queries only; privacy-omitted queries are unknown.")
    unknown = sum(a["unknown"] for a in per_kw.values())
    if unknown:
        lex.partial(f"{unknown} joined rows with unknown clicks/cost or empty tokens not classified")

    # -- steps 5 + 8: relevance review with zero-conversion gate
    rel = ctx.check("relevance_review", "Business relevance of variant queries", {"search_terms": ST_COLS,
                                                                                   "keywords": KW_COLS})
    zc = ctx.check("zero_conversion_screen", "Mature zero-conversion variant exposure", {"search_terms": ST_COLS,
                                                                                          "keywords": KW_COLS})
    excluded = ctx.profile.get("excluded_intents") or []
    objectives = ctx.profile.get("campaign_objectives") or {}
    has_context = bool(excluded or ctx.profile.get("objectives") or objectives)
    if not has_context:
        rel.partial("no excluded_intents/objectives in profile: relevance stays Unknown",
                    ["profile:excluded_intents", "profile:campaign_objectives"])
    if ctx.mature is not True:
        zc.partial(f"zero-conversion Warning path disabled: maturity {ctx.mature} ({ctx.maturity_note})")
    shared_ok = _shared_links_known(ctx)
    sub_floor, unresolved, tracking_notes = [], set(), set()
    for x in rows:
        if x["class"] in (None, "Literal") or x["cost"] is None:
            continue
        floor = ctx.params.get("spend_floor", x["cid"])
        if floor.value is None:
            unresolved.add(f"{x['cid']}: {floor.reason}")
            continue
        entity = {"campaign_id": x["cid"], "ad_group_id": x["gid"], "keyword_id": x["kid"], "search_term": x["q"]}
        ev = {"lexical_class": x["class"], "keyword_text": x["kw"].get("text"), "keyword_match": x["kw"].get("match_type"),
              "report_match": x["row"].get("match_type"), "clicks": x["clicks"], "cost": x["cost"],
              "conversions": x["conv"], "spend_floor": floor.value, "spend_floor_source": floor.source,
              "brand_query": _brand(ctx, x["q"]), "excluded_intents": excluded,
              "campaign_objective": next((v for k, v in objectives.items() if str(k) == x["cid"]), None)
              if isinstance(objectives, dict) else None, "window": [ctx.period_start, ctx.period_end],
              "negative_owner": "skill-014", "shared_list_links_known": shared_ok}
        if x["cost"] < floor.value:
            sub_floor.append({"search_term": x["q"], "campaign_id": x["cid"], "ad_group_id": x["gid"],
                              "keyword_id": x["kid"], "cost": x["cost"], "conversions": x["conv"], "class": x["class"]})
            continue
        prov = None
        zero_ok = False
        if x["conv"] == 0 and ctx.mature is True:
            tracked, note = ctx.tracking_for_campaign(x["cid"])
            if tracked is True:
                zero_ok = True
                ev["tracking"] = note
                prov = zc.finding("zero_conversion_variant", "Info", entity,
                                  f"Variant '{x['q']}' spent {x['cost']:.2f} {ctx.currency} with 0 conversions in a "
                                  f"mature window (spend_floor {floor.value:g})", evidence=ev,
                                  recommendation="Relevance review before any exclusion; exposure is not savings.",
                                  uncertainty="Zero conversions can reflect lag, sales cycle or assisted value.")
            else:
                tracking_notes.add(note)
        outcomes = {"supported": {"severity": None, "recommendation": "Keep serving."},
                    "ambiguous": {"severity": "Info", "recommendation": "Several plausible tasks; monitor."},
                    "unknown": {"severity": "Info", "recommendation": "Supply relevance context."}}
        if has_context:
            outcomes["excluded_intent"] = {"severity": "Warning", "recommendation":
                                           "Route a verified negative proposal to skill-014 after skill-017 scope review."}
            if zero_ok:
                outcomes["irrelevant_zero_conversion"] = {"severity": "Warning", "recommendation":
                                                          "Investigate; exclude only with evidence of irrelevance."}
        rel.review("variant_query_relevance", entity,
                   f"Is variant query '{x['q']}' (keyword '{x['kw'].get('text')}', {x['kw'].get('match_type')}) "
                   f"Supported, Excluded, Ambiguous or Unknown for campaign {x['cid']}?",
                   evidence=ev, outcomes=outcomes, provisional=prov,
                   guidance="Judge only against profile excluded_intents/objectives; record the evidence phrase. "
                            "Lexical similarity is not intent. Optional proposal {negative, match_type, level, "
                            "campaign_id, ad_group_id} is collision-verified.")
    if sub_floor:
        rel.review("sub_floor_variant_relevance", {"batch": "sub_floor_variants"},
                   "Which of these below-floor variant queries match an explicit excluded intent?",
                   evidence={"queries": sub_floor, "excluded_intents": excluded},
                   outcomes={"some_excluded": {"severity": "Info", "recommendation":
                                               "Optional hygiene negatives via skill-014; exposure below materiality."},
                             "none_excluded": {"severity": None, "recommendation": "No action."}},
                   guidance="List proposal.queries with exact texts from the evidence.")
    for u in sorted(unresolved):
        rel.partial(f"spend_floor unresolved for campaign {u}")
        zc.partial(f"spend_floor unresolved for campaign {u}")
    for n in sorted(tracking_notes):
        zc.partial(f"tracking not evidenced: {n}")
    zc.observe("Zero-conversion variants screened", provisional=sum(1 for f in ctx.result.findings
                                                                   if f.condition_key == "zero_conversion_variant"))

    lab = ctx.check("variant_labels", "Supplied platform classifications", {"search_terms": ST_COLS})
    plat: dict[str, int] = {}
    for x in rows:
        p = str(x["row"].get("match_type") or "UNREPORTED").upper()
        plat[p] = plat.get(p, 0) + 1
    lab.observe("Report query-match classifications preserved; misspelling/plural labels not inferred",
                classifications=plat, supplied_variant_label_column="close_variant_type" in
                (ctx.table("search_terms").columns if ctx.table("search_terms") else []))

    agg = ctx.check("class_aggregates", "Mature metrics by lexical class with sample gates",
                    {"search_terms": ST_COLS, "keywords": KW_COLS})
    if ctx.mature is not True:
        agg.partial(f"maturity {ctx.mature}: descriptive totals only")
    min_clk, min_conv = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
    classes: dict[tuple, list] = {}
    for x in rows:
        if x["class"] is None or None in (x["clicks"], x["cost"], x["conv"]):
            continue
        a = classes.setdefault((x["cid"], x["class"]), [0.0, 0.0, 0.0])
        a[0] += x["clicks"]
        a[1] += x["cost"]
        a[2] += x["conv"]
    for cid in sorted({c for c, _ in classes}):
        data = {}
        for cls in ("Literal", "Reorder", "Other"):
            clk, cost, conv = classes.get((cid, cls), [0.0, 0.0, 0.0])
            data[cls] = {"clicks": clk, "cost": cost, "conversions": conv,
                         "cvr": V.ratio(conv, clk) if ctx.mature is True and clk >= min_clk.value else None,
                         "cpa": V.ratio(cost, conv) if ctx.mature is True and conv >= min_conv.value else None}
        comparable = data["Literal"]["cvr"] is not None and data["Other"]["cvr"] is not None
        agg.observe(f"Campaign {cid} lexical-class aggregates", campaign_id=cid, classes=data,
                    cvr_comparable=comparable, min_clicks=min_clk.value, min_conversions=min_conv.value,
                    note="irrelevant share needs accepted relevance decisions; lower CVR alone is not a defect")

    neg = ctx.check("negative_routing", "Negative proposal scope and routing",
                    {"negative_keywords": ["text", "match_type", "level", "campaign_id"],
                     "ad_groups": ["id", "campaign_id"], "shared_negative_lists": ["list_id"]})
    if neg.runnable:
        if not shared_ok:
            neg.partial("shared-list campaign links missing: negative proposals blocked",
                        ["shared_negative_lists:campaigns_applied"])
        scopes, gaps = effective_negatives(ctx)
        for g in gaps:
            neg.partial(g)
        already = []
        for x in rows:
            hit = next((n for n in scopes.get((x["cid"], x["gid"]), []) if blocks(n.text, n.match, x["q"])), None)
            if hit:
                already.append({"search_term": x["q"], "campaign_id": x["cid"], "negative": hit.text, "scope": hit.ref})
        neg.observe("Variant queries already blocked by a current negative (served before it or bypassed)",
                    queries=already, owner="skill-014 (negatives), skill-013 (additions), skill-015 (patterns)")

    nar = ctx.check("narrowing_hypothesis", "Controlled narrowing hypotheses", {"search_terms": ST_COLS,
                                                                               "keywords": KW_COLS})
    for (cid, gid, kid), a in sorted(per_kw.items()):
        match = str(a["kw"].get("match_type") or "").upper()
        if not a["variants"]:
            continue
        nar.observe(f"Keyword {kid} narrowing option", campaign_id=cid, keyword_id=kid, match_type=match,
                    variant_cost_share=V.ratio(a["variant_cost"], a["cost"]),
                    option="controlled relevance hypothesis (skill-032)" if match in ("BROAD", "PHRASE")
                    else "EXACT cannot be narrowed further and still serves close variants")

    if eo.runnable:
        _exact_only_restriction(ctx, eo, eo_ids)


def _eo_variant_queries(ctx, cid: str, gid: str, kid: str, kw_text) -> dict:
    """Reported non-literal queries matched by one keyword, aggregated by EXACT-negative token key.

    Rules:   Recomputed from ctx.rows("search_terms") (run and verify share it); duplicate full source rows count once;
             a query is listed only when its lexical_class vs kw_text is Reorder/Other (never Literal/None); any row
             with unknown clicks/cost/conversions makes that aggregate unknown (None), never zero.
    """
    seen, out = set(), {}
    for r in sorted(ctx.rows("search_terms"), key=lambda r: tuple(sorted((k, str(v)) for k, v in r.items()))):
        full = tuple(sorted((k, str(v)) for k, v in r.items()))
        if full in seen or (str(r.get("campaign_id")), str(r.get("ad_group_id")),
                            str(r.get("matched_keyword_id"))) != (cid, gid, kid):
            continue
        seen.add(full)
        q = str(r.get("search_term") or "")
        cls = lexical_class(q, kw_text)
        if cls in (None, "Literal"):
            continue
        a = out.setdefault(" ".join(tokens(q)), {"search_term": q, "lexical_class": cls, "clicks": 0.0, "cost": 0.0,
                                                 "conversions": 0.0, "report_match": r.get("match_type")})
        for f, v in (("clicks", V.num(r.get("clicks"))), ("cost", ctx.money(r.get("cost"))),
                     ("conversions", V.num(r.get("conversions")))):
            a[f] = None if v is None or a[f] is None else a[f] + v
    return out


def _eo_collisions(ctx, cid: str, gid: str, kid: str, neg_text: str) -> list[str]:
    """Problems if an ad-group EXACT negative would block a converting query or another active keyword.

    Rules:   Scope is exactly (campaign_id, ad_group_id). A query row counts as converting when conversions > 0 or
             unknown; an active keyword is any keyword other than kid whose status is ENABLED or missing. blocks()
             returning None (undecidable) is a problem, never a pass.
    """
    problems = []
    for r in ctx.rows("search_terms"):
        if (str(r.get("campaign_id")), str(r.get("ad_group_id"))) != (cid, gid):
            continue
        conv = V.num(r.get("conversions"))
        hit = blocks(neg_text, "EXACT", r.get("search_term"))
        if (conv is None or conv > 0) and hit is not False:
            problems.append(f"'{neg_text}' EXACT would block converting (or unknown-conversion) query "
                            f"'{r.get('search_term')}' in ad group {gid}" + ("" if hit else " (undecidable)"))
    for k in ctx.rows("keywords"):
        if (str(k.get("campaign_id")), str(k.get("ad_group_id"))) != (cid, gid) or str(k.get("id")) == kid:
            continue
        if str(k.get("status") or "ENABLED").upper() != "ENABLED":
            continue
        hit = blocks(neg_text, "EXACT", k.get("text"))
        if hit is not False:
            problems.append(f"'{neg_text}' EXACT would block active keyword '{k.get('text')}' ({k.get('id')})"
                            + ("" if hit else " (undecidable)"))
    return sorted(set(problems))


def _exact_only_restriction(ctx, eo, eo_ids) -> None:
    """Queue one literal-only review per ENABLED keyword listed in profile.exact_only_keyword_ids.

    Rules:   The list is the owner's explicit request; non-list → skipped. Listed IDs absent from keywords → partial;
             status other than ENABLED → observation only; unknown status → partial. Evidence lists every reported
             non-literal query with collision flags; variant cost is exposure, never savings. Outcomes:
             restrict_to_literal (Info) and keep_variants (no finding). Nothing is applied.
    """
    if not isinstance(eo_ids, list):
        eo.skip("profile.exact_only_keyword_ids must be a list of keyword IDs", ["profile:exact_only_keyword_ids"])
        return
    wanted = sorted({str(x).strip() for x in eo_ids if str(x or "").strip()})
    by_id: dict[str, list] = {}
    for k in ctx.rows("keywords"):
        by_id.setdefault(str(k.get("id")), []).append(k)
    for kid in wanted:
        kws = sorted(by_id.get(kid, []), key=lambda k: (str(k.get("campaign_id")), str(k.get("ad_group_id"))))
        if not kws:
            eo.partial(f"listed keyword {kid} not found in keywords export", ["keywords:id"])
        for kw in kws:
            cid, gid, text = str(kw.get("campaign_id")), str(kw.get("ad_group_id")), kw.get("text")
            status = str(kw.get("status") or "").upper()
            if not status:
                eo.partial(f"listed keyword {kid} in ad group {gid} has unknown status", ["keywords:status"])
                continue
            if status != "ENABLED":
                eo.observe(f"Listed keyword {kid} is {status}: no literal-only proposal", campaign_id=cid,
                           ad_group_id=gid, keyword_id=kid, status=status)
                continue
            variants = _eo_variant_queries(ctx, cid, gid, kid, text)
            if not variants:
                eo.observe(f"Listed keyword {kid}: no reported non-literal queries", campaign_id=cid, ad_group_id=gid,
                           keyword_id=kid, note="privacy-omitted queries are unknown, not absent")
                continue
            listed, exp_clicks, exp_cost = [], 0.0, 0.0
            for key in sorted(variants):
                v = variants[key]
                col = _eo_collisions(ctx, cid, gid, kid, v["search_term"])
                if blocks(v["search_term"], "EXACT", text) is not False:
                    col.append("would block the keyword's own literal text")
                if blocks(v["search_term"], "EXACT", v["search_term"]) is not True:
                    col.append("query not expressible as an EXACT negative (operators or >16 words)")
                listed.append({**v, "proposable": not col, "blocked_reasons": col})
                exp_clicks = None if exp_clicks is None or v["clicks"] is None else exp_clicks + v["clicks"]
                exp_cost = None if exp_cost is None or v["cost"] is None else exp_cost + v["cost"]
            eo.review("exact_only_restriction", {"campaign_id": cid, "ad_group_id": gid, "keyword_id": kid},
                      f"Restrict keyword '{text}' ({kw.get('match_type')}, {kid}) to its literal text with ad-group "
                      f"EXACT negatives for {len(listed)} reported non-literal queries?",
                      evidence={"keyword_text": text, "keyword_match": kw.get("match_type"),
                                "requested_by": "profile.exact_only_keyword_ids", "variant_queries": listed,
                                "variant_exposure_clicks": exp_clicks, "variant_exposure_cost": exp_cost,
                                "currency": ctx.currency, "window": [ctx.period_start, ctx.period_end],
                                "exposure_note": "historical variant cost is exposure, not savings"},
                      outcomes={"restrict_to_literal": {"severity": "Info", "recommendation":
                                                        "Owner-requested literal-only restriction: add the verified "
                                                        "ad-group EXACT negatives (proposal only; skill-014 owns "
                                                        "negatives)."},
                                "keep_variants": {"severity": None, "recommendation": "Keep serving the variants."}},
                      guidance="restrict_to_literal needs proposal.negatives = [{text, match_type: EXACT, level: "
                               "ad_group, campaign_id, ad_group_id}] using only variant_queries with proposable true; "
                               "finalize rejects any other query, scope or match type.")


def _in_scope(r, n) -> bool:
    return str(r.get("campaign_id")) == n["campaign_id"] and (
        n["ad_group_id"] is None or str(r.get("ad_group_id")) == n["ad_group_id"])


def _verify_exact_only(ctx, item, decision) -> list[str]:
    """Verify a literal-only proposal for one reviewed keyword against the supplied evidence rows.

    Rules:   Only restrict_to_literal is checked (keep_variants proposes nothing). Every negative must be EXACT, level
             ad_group, campaign_id/ad_group_id equal to the item entity, equal to a listed non-literal query of the
             same keyword recomputed from search_terms, not block the keyword's literal text, and pass
             _eo_collisions(); an absent keyword row or empty list rejects.
    """
    if decision.get("outcome") != "restrict_to_literal":
        return []
    cid, gid, kid = (str(item.entity.get(k)) for k in ("campaign_id", "ad_group_id", "keyword_id"))
    kw = next((k for k in ctx.rows("keywords") if (str(k.get("campaign_id")), str(k.get("ad_group_id")),
                                                   str(k.get("id"))) == (cid, gid, kid)), None)
    if kw is None:
        return [f"keyword {kid} not found in ad group {gid}: proposal cannot be verified"]
    negs = (decision.get("proposal") or {}).get("negatives")
    if not isinstance(negs, list) or not negs:
        return ["restrict_to_literal needs proposal.negatives: a non-empty list of ad-group EXACT negatives"]
    listed = [v["search_term"] for v in _eo_variant_queries(ctx, cid, gid, kid, kw.get("text")).values()]
    problems = []
    for n in negs:
        n = n if isinstance(n, dict) else {}
        text = str(n.get("text") or "").strip()
        if not text:
            problems.append("negative without text")
            continue
        if normalize_match(n.get("match_type")) != "EXACT":
            problems.append(f"'{text}' must be EXACT, got {n.get('match_type')!r}")
        if str(n.get("level") or "").lower() != "ad_group" or str(n.get("campaign_id")) != cid or \
                str(n.get("ad_group_id")) != gid:
            problems.append(f"'{text}' must be an ad_group negative at campaign {cid} / ad group {gid}")
        if not any(blocks(text, "EXACT", q) is True for q in listed):
            problems.append(f"'{text}' is not a reported non-literal query of keyword {kid}")
        if blocks(text, "EXACT", kw.get("text")) is not False:
            problems.append(f"'{text}' would block the keyword's own literal text '{kw.get('text')}'")
        problems += _eo_collisions(ctx, cid, gid, kid, text)
    return problems


def verify(ctx, item, decision) -> list[str]:
    """Re-check negative proposals deterministically; returns problems (non-empty → decision rejected, exit 4).

    Rules:   exact_only_restriction + restrict_to_literal: proposal.negatives must be a non-empty list; each entry is
             EXACT, level ad_group at the reviewed campaign/ad group, equals (blocks() EXACT) a reported non-literal
             query recomputed from search_terms for the reviewed keyword, does not block the keyword's literal text,
             and blocks no converting/unknown-conversion query or other active keyword in that ad group.
             variant relevance outcomes: an optional negative is EXACT/PHRASE/BROAD at campaign/ad_group scope of the
             query, blocks it, collides with no converting query, active keyword or brand term, and is refused
             without shared-list links.
    """
    if item.condition_key == "exact_only_restriction":
        return _verify_exact_only(ctx, item, decision)
    p = decision.get("proposal") or {}
    if decision.get("outcome") not in ("excluded_intent", "irrelevant_zero_conversion") or not p.get("negative"):
        return []
    if not _shared_links_known(ctx):
        return ["shared-list links unavailable: negative proposals cannot be scope-checked"]
    match, level = normalize_match(p.get("match_type")), str(p.get("level") or "").lower()
    cid = str(p.get("campaign_id") or "")
    gid = str(p.get("ad_group_id") or "") if level == "ad_group" else None
    if match is None or level not in ("campaign", "ad_group") or not cid or (level == "ad_group" and not gid):
        return ["proposal needs negative, match_type EXACT|PHRASE|BROAD, level campaign|ad_group, campaign_id "
                "and (ad_group) ad_group_id"]
    n = {"text": str(p["negative"]).strip(), "match": match, "campaign_id": cid, "ad_group_id": gid}
    problems = []
    if cid != item.entity["campaign_id"] or (gid is not None and gid != item.entity["ad_group_id"]):
        problems.append("proposal scope differs from the reviewed query's campaign/ad group")
    if blocks(n["text"], n["match"], item.entity["search_term"]) is not True:
        problems.append(f"'{n['text']}' ({match}) does not block '{item.entity['search_term']}'")
    for r in ctx.rows("search_terms"):
        conv = V.num(r.get("conversions"))
        if _in_scope(r, n) and (conv is None or conv > 0) and blocks(n["text"], match, r.get("search_term")):
            problems.append(f"would block converting (or unknown-conversion) query '{r.get('search_term')}'")
    for k in ctx.rows("keywords"):
        if _in_scope(k, n) and str(k.get("status") or "ENABLED").upper() == "ENABLED" and blocks(n["text"], match, k.get("text")):
            problems.append(f"would block active keyword '{k.get('text')}' ({k.get('id')})")
    for b in ctx.profile.get("brand_terms") or []:
        if blocks(n["text"], match, b):
            problems.append(f"would block brand term '{b}'")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
