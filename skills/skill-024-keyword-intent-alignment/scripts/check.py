"""check.py — skill-024 deterministic destination mapping, page-evidence joins and guarded intent/page review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-024-keyword-intent-alignment/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Intent (transactional/navigational/informational/commercial, mixed/Unknown) is ai_review only; the script
         tags brand_term / competitor_term / other by literal PHRASE containment, brand precedence first.
         Destination precedence: keyword final_url override, else final URLs of ENABLED non-disapproved ads in the
         same ad group (all kept as candidates; the served page is never asserted).
         Page evidence joins external/landing_page_content on normalized url|final_url (fragment and trailing '/'
         dropped, scheme/host lowercased; path case kept). A URL is never a substitute for page content.
         Page contradiction Warning needs approved context (profile product_service_taxonomy, intended_offer or
         campaign_objectives[cid]); verify demands proposal.evidence_ref of a reviewed capture and a
         proposal.excerpt found verbatim (normalized) in that capture's text fields.
         Zero-conversion keyword screening: ctx.mature True, ctx.tracking_for_campaign(cid) True, cost >=
         spend_floor of THAT campaign, conversions == 0 → provisional Info + review; never a page diagnosis.
         Intent share is descriptive (no maximum); cohort rates only with both-sided sample gates.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import json
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
from adsrun.negatives import blocks  # noqa: E402

SKILL = "skill-024-keyword-intent-alignment"
VERSION = "1.0.0"

ST_COLS = ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]
KW_COLS = ["id", "campaign_id", "ad_group_id", "text"]
PAGE_COLS = ["url", "final_url", "captured_at", "http_status", "title", "main_content_excerpt", "evidence_ref"]
_PAGE_TEXT = ("title", "headings", "offer_text", "main_content_excerpt", "cta_text", "product_service",
              "supported_audience")


def _url(v) -> str:
    s = str(v or "").strip().split("#", 1)[0].rstrip("/")
    if "://" not in s:
        return s
    scheme, rest = s.split("://", 1)
    host, _, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower()}" + (f"/{path}" if path else "")


def _norm(v) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(v or "")).casefold().split())


def _urls(cell) -> list[str]:
    if cell is None:
        return []
    s = str(cell).strip()
    if s.startswith("["):
        try:
            return [str(u) for u in json.loads(s) if u]
        except ValueError:
            return []
    return V.split_list(s, (" | ", ";", "|", ","))


def _tag(ctx, q) -> str:
    if any(blocks(b, "PHRASE", q) is True for b in (ctx.profile.get("brand_terms") or []) if b):
        return "brand_term"
    if any(blocks(c, "PHRASE", q) is True for c in (ctx.profile.get("competitor_terms") or []) if c):
        return "competitor_term"
    return "other"


def _objective(ctx, cid):
    obj = ctx.profile.get("campaign_objectives") or {}
    return next((v for k, v in obj.items() if str(k) == cid), None) if isinstance(obj, dict) else None


def _context(ctx, cid) -> dict:
    return {k: v for k, v in (("product_service_taxonomy", ctx.profile.get("product_service_taxonomy")),
                              ("intended_offer", ctx.profile.get("intended_offer")),
                              ("excluded_intents", ctx.profile.get("excluded_intents")),
                              ("service_area", ctx.profile.get("service_area")),
                              ("campaign_objective", _objective(ctx, cid))) if v}


def run(ctx) -> None:
    """Run scope, intent, brand-precedence, coverage, destination, page-fit, cohort and zero-conversion checks.

    Rules:   Intent assignment is ai_review only (Info at most). Page 'contradicted' Warning is offered only with
             approved context and a landing_page_content capture; a URL alone is never evidence. Zero-conversion
             keywords need ctx.mature True, tracking_for_campaign True and cost >= campaign spend_floor → provisional
             Info + review; cohort rates need min_clicks/min_conversions; shares are observations.
    """
    ws = ctx.check("window_scope", "Account, window, snapshot and maturity",
                   {"account": ["currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if ws.runnable:
        ws.observe("Scope", currency=ctx.currency, period=[ctx.period_start, ctx.period_end], snapshot=ctx.snapshot,
                   conversion_date_basis=ctx.account.get("conversion_date_basis"), mature=ctx.mature,
                   maturity_note=ctx.maturity_note)
        if ctx.mature is not True:
            ws.partial(f"conversions not mature: {ctx.maturity_note}")

    terms = sorted(ctx.rows("search_terms"), key=lambda r: (str(r.get("campaign_id")), str(r.get("search_term"))))
    intent = ctx.check("intent_assignment", "Evidence-based intent assignment", {"search_terms": ST_COLS})
    if intent.runnable:
        by_c: dict[str, list] = {}
        for r in terms:
            by_c.setdefault(str(r.get("campaign_id")), []).append(
                {"search_term": r.get("search_term"), "clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")),
                 "conversions": V.num(r.get("conversions")), "literal_tag": _tag(ctx, r.get("search_term"))})
        for cid, qs in sorted(by_c.items()):
            intent.review("intent_assignment", {"campaign_id": cid, "batch": "reported_queries"},
                          f"Assign intent (transactional, navigational, informational, commercial investigation, "
                          f"mixed/Unknown) to campaign {cid}'s reported queries, citing the evidence phrase.",
                          evidence={"queries": qs, "campaign_objective": _objective(ctx, cid),
                                    "objectives": ctx.profile.get("objectives")},
                          outcomes={"assigned": {"severity": None, "recommendation": "Report intent shares descriptively."},
                                    "ambiguous_or_mixed_present": {"severity": "Info", "recommendation":
                                                                   "Keep ambiguous queries Unknown; no exclusion."}},
                          guidance="Inspect the full query, not generic waste tokens; informational traffic can be "
                                   "intentional. No maximum informational share applies.")

    prec = ctx.check("brand_competitor_precedence", "Brand over competitor term precedence", {"search_terms": ST_COLS})
    if prec.runnable:
        if not ctx.profile.get("brand_terms"):
            prec.partial("profile brand_terms missing: brand tagging incomplete", ["profile:brand_terms"])
        tags: dict[tuple, list] = {}
        both = 0
        for r in terms:
            q = r.get("search_term")
            t = _tag(ctx, q)
            if t == "brand_term" and any(blocks(c, "PHRASE", q) is True for c in ctx.profile.get("competitor_terms") or []):
                both += 1
            a = tags.setdefault((str(r.get("campaign_id")), t), [0, 0.0, 0])
            a[0] += 1
            c = ctx.money(r.get("cost"))
            if c is None:
                a[2] += 1
            else:
                a[1] += c
        prec.observe("Literal term tags (brand precedence)",
                     by_campaign_tag={f"{c}:{t}": {"queries": n, "cost": k, "unknown_cost_rows": u}
                                      for (c, t), (n, k, u) in sorted(tags.items())},
                     brand_and_competitor_queries=both)

    cov = ctx.check("query_coverage", "Reported query totals vs campaign totals",
                    {"search_terms": ["search_term", "campaign_id", "clicks", "cost"],
                     "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if cov.runnable:
        acc: dict[str, list] = {}
        for r in terms:
            a = acc.setdefault(str(r.get("campaign_id")), [0.0, 0.0, 0])
            c, k = V.num(r.get("clicks")), ctx.money(r.get("cost"))
            if c is None or k is None:
                a[2] += 1
                continue
            a[0] += c
            a[1] += k
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid in acc:
                cc, ck = V.num(m.get("clicks")), ctx.money(m.get("cost"))
                cov.observe(f"Campaign {cid} reported-query coverage", campaign_id=cid, query_clicks=acc[cid][0],
                            campaign_clicks=cc, click_share=V.ratio(acc[cid][0], cc), query_cost=acc[cid][1],
                            campaign_cost=ck, cost_share=V.ratio(acc[cid][1], ck), rows_unknown_metrics=acc[cid][2])
        cov.partial("privacy-limited query reporting: unreported traffic is unknown, not zero")

    # -- step 5: destinations
    dest = ctx.check("destination_mapping", "Keyword/ad destination candidates by URL precedence",
                     {"keywords": KW_COLS, "ads": ["id", "ad_group_id", "status"]})
    candidates: dict[tuple, dict] = {}  # (cid, gid) -> {url: [keyword ids]}
    kw_rows = sorted(ctx.rows("keywords"), key=lambda r: str(r.get("id")))
    if dest.runnable:
        url_col = next((c for c in ("final_url", "final_urls") if c in ctx.table("ads").columns), None)
        if url_col is None:
            dest.partial("ads final URLs missing", ["ads:final_url"])
        ad_urls: dict[str, list] = {}
        for a in ctx.rows("ads"):
            if str(a.get("status") or "").upper() != "ENABLED" or "DISAPPROVED" in str(a.get("approval_status") or "").upper():
                continue
            ad_urls.setdefault(str(a.get("ad_group_id")), []).extend(_urls(a.get(url_col)) if url_col else [])
        unmapped = []
        for k in kw_rows:
            if str(k.get("status") or "ENABLED").upper() == "REMOVED":
                continue
            key = (str(k.get("campaign_id")), str(k.get("ad_group_id")))
            override = _urls(k.get("final_url"))
            urls = override or ad_urls.get(key[1], [])
            if not urls:
                unmapped.append(str(k.get("id")))
            for u in urls:
                candidates.setdefault(key, {}).setdefault(_url(u), []).append(str(k.get("id")))
        dest.observe("Destination candidates per ad group", candidates={f"{c}:{g}": {u: len(ids) for u, ids in m.items()}
                                                                      for (c, g), m in sorted(candidates.items())},
                     keywords_without_destination=unmapped,
                     note="serving destination unknown where several candidates exist")
        if unmapped:
            dest.partial(f"{len(unmapped)} keywords without a destination candidate")

    # -- step 6: page fit
    fit = ctx.check("page_fit", "Actual page content vs product/task/audience",
                    {"keywords": KW_COLS, "external/landing_page_content": PAGE_COLS})
    pages: dict[str, list] = {}
    if fit.runnable:
        for p in ctx.rows("external/landing_page_content"):
            for u in {_url(p.get("url")), _url(p.get("final_url"))} - {""}:
                pages.setdefault(u, []).append(p)
        missing = []
        kw_text = {str(k.get("id")): k.get("text") for k in kw_rows}
        for (cid, gid), m in sorted(candidates.items()):
            ctx_ok = _context(ctx, cid)
            approved = {k: v for k, v in ctx_ok.items() if k in ("product_service_taxonomy", "intended_offer",
                                                                 "campaign_objective")}
            for u, kids in sorted(m.items()):
                caps = pages.get(u)
                if not caps:
                    missing.append(u)
                    continue
                cap_ev = [{c: p.get(c) for c in ("url", "final_url", "language", "device", "captured_at", "source",
                                                  "http_status", *_PAGE_TEXT, "evidence_ref")} for p in caps]
                outcomes = {"supported": {"severity": None, "recommendation": "No page change."},
                            "unknown": {"severity": "Info", "recommendation": "Collect a fuller page capture."}}
                if approved:
                    outcomes["contradicted"] = {"severity": "Warning", "recommendation":
                                                "Propose copy/page/routing review with the owner; no automatic negative."}
                fit.review("page_contradicts_requirement", {"campaign_id": cid, "ad_group_id": gid, "url": u},
                           f"Does the captured page at {u} support, contradict or leave unknown the product/task/"
                           f"audience of ad group {gid}'s keywords?",
                           evidence={"keywords": sorted({kw_text.get(i) or i for i in kids}), "keyword_ids": sorted(kids),
                                     "captures": cap_ev, "approved_context": ctx_ok},
                           outcomes=outcomes,
                           guidance="Cite page excerpt and capture time; a generic-looking URL or http code alone is not "
                                    "a contradiction. contradicted needs proposal.evidence_ref + proposal.excerpt.")
                if not approved:
                    fit.partial(f"campaign {cid}: no approved product/offer/objective; contradiction outcome withheld")
        if missing:
            fit.partial(f"no page capture for destination URLs {sorted(set(missing))} (URL is not page evidence)")

    # -- step 7: cohorts
    coh = ctx.check("intent_cohorts", "Cohort metrics within compatible campaign goals", {"search_terms": ST_COLS})
    if coh.runnable:
        coh.partial("semantic intent cohorts need accepted intent_assignment decisions; literal term cohorts shown")
        min_clk, min_conv = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
        agg: dict[tuple, list] = {}
        for r in terms:
            v = [V.num(r.get("clicks")), ctx.money(r.get("cost")), V.num(r.get("conversions"))]
            if None in v:
                continue
            a = agg.setdefault((str(r.get("campaign_id")), _tag(ctx, r.get("search_term"))), [0.0, 0.0, 0.0])
            for i, x in enumerate(v):
                a[i] += x
        for (cid, tag), (clk, cost, conv) in sorted(agg.items()):
            mature = ctx.mature is True
            coh.observe(f"Campaign {cid} cohort {tag}", campaign_id=cid, cohort=tag, clicks=clk, cost=cost,
                        conversions=conv if mature else None,
                        cvr=V.ratio(conv, clk) if mature and clk >= min_clk.value else None,
                        cpa=V.ratio(cost, conv) if mature and conv >= min_conv.value else None,
                        min_clicks=min_clk.value, min_conversions=min_conv.value,
                        note="compare cohorts only when both show a rate; shares are descriptive")

    # -- step 8: zero-conversion keywords
    zc = ctx.check("zero_conversion_screen", "Mature zero-conversion keyword exposure",
                   {"keywords": KW_COLS, "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "cost",
                                                             "conversions"]})
    if zc.runnable:
        if ctx.mature is not True:
            zc.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): zero-conversion screening disabled")
        else:
            kmap = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in kw_rows}
            seen, unresolved, untracked = set(), set(), set()
            for m in sorted(ctx.rows("keyword_metrics"), key=lambda r: (str(r.get("campaign_id")), str(r.get("keyword_id")))):
                key = (str(m.get("campaign_id")), str(m.get("ad_group_id")), str(m.get("keyword_id")))
                if key in seen:
                    zc.partial(f"duplicate metric rows for keyword {key[2]}; excluded")
                    continue
                seen.add(key)
                k = kmap.get(key)
                cost, conv = ctx.money(m.get("cost")), V.num(m.get("conversions"))
                if k is None or cost is None or conv != 0:
                    continue
                floor = ctx.params.get("spend_floor", key[0])
                if floor.value is None:
                    unresolved.add(f"{key[0]}: {floor.reason}")
                    continue
                if cost < floor.value:
                    continue
                tracked, note = ctx.tracking_for_campaign(key[0])
                if tracked is not True:
                    untracked.add(note)
                    continue
                entity = {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]}
                qs = [{"search_term": r.get("search_term"), "cost": ctx.money(r.get("cost")),
                       "conversions": V.num(r.get("conversions"))} for r in terms
                      if str(r.get("matched_keyword_id")) == key[2] and str(r.get("campaign_id")) == key[0]]
                cands = sorted(candidates.get(key[:2], {}))
                ev = {"keyword_text": k.get("text"), "match_type": k.get("match_type"), "cost": cost, "conversions": conv,
                      "clicks": V.num(m.get("clicks")), "spend_floor": floor.value, "spend_floor_source": floor.source,
                      "tracking": note, "queries": qs, "candidate_urls": cands,
                      "page_evidence_refs": sorted({str(p.get("evidence_ref")) for u in cands for p in pages.get(u, [])}),
                      "approved_context": _context(ctx, key[0]), "window": [ctx.period_start, ctx.period_end]}
                prov = zc.finding("zero_conversion_keyword", "Info", entity,
                                  f"Keyword {key[2]} ('{k.get('text')}') spent {cost:.2f} {ctx.currency} with 0 "
                                  f"conversions in a mature, tracked window (spend_floor {floor.value:g})",
                                  evidence=ev, recommendation="Contextual review: demand, offer, page, tracking, sales cycle.",
                                  uncertainty="Zero conversions do not diagnose the page; exposure is not savings.")
                zc.review("zero_conversion_keyword", entity,
                          f"After contextual checks, is keyword '{k.get('text')}' intent/page misaligned with the "
                          f"approved goal of campaign {key[0]}?",
                          evidence=ev, provisional=prov,
                          outcomes={"misaligned_after_context": {"severity": "Warning", "recommendation":
                                                                 "Copy/page/routing review; exclusions via skill-014."},
                                    "contextual_explanation": {"severity": None, "recommendation":
                                                               "Keep; document demand/sales-cycle explanation."},
                                    "uncertain": {"severity": "Info", "recommendation": "Monitor with more data."}},
                          guidance="Performance alone never proves a page defect; cite intent evidence and page capture.")
            for u in sorted(unresolved):
                zc.partial(f"spend_floor unresolved for campaign {u}")
            for n in sorted(untracked):
                zc.partial(f"tracking not evidenced: {n}")

    route = ctx.check("routing_proposals", "Proposal routing to owners", {"search_terms": ST_COLS})
    if route.runnable:
        route.observe("Routing", exclusions_owner="skill-014", additions_owner="skill-013",
                      page_reviews=sum(1 for x in ctx.result.reviews if x.condition_key == "page_contradicts_requirement"),
                      zero_conversion_reviews=sum(1 for x in ctx.result.reviews if x.condition_key == "zero_conversion_keyword"),
                      note="owner-approved informational campaigns preserved; no automatic funnel reassignment")


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'contradicted' cites a reviewed capture (evidence_ref) and an excerpt present in its text fields."""
    if decision.get("outcome") != "contradicted":
        return []
    p = decision.get("proposal") or {}
    caps = {str(c.get("evidence_ref")): c for c in item.evidence.get("captures") or [] if c.get("evidence_ref")}
    ref, excerpt = str(p.get("evidence_ref") or ""), _norm(p.get("excerpt"))
    if ref not in caps:
        return [f"proposal.evidence_ref must be one of the reviewed captures {sorted(caps)}"]
    if not excerpt:
        return ["proposal.excerpt required (quoted page text)"]
    text = " ".join(_norm(caps[ref].get(f)) for f in _PAGE_TEXT)
    return [] if excerpt in text else ["proposal.excerpt not found in the cited capture's text fields"]


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
