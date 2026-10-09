"""check.py — skill-151 deterministic seasonal product-descriptor and promotional-title review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-151-product-feed-seasonal-keyword-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Product identity = (merchant_id, feed_label, language, item_id); latest snapshot_at per key. A source row
         lacking feed_label/language resolves ONLY when (merchant_id, item_id) maps to exactly one feed key;
         otherwise it stays ambiguous (Info) and is NEVER fanned out across labels/languages.
         Deterministic Warning only when client descriptor evidence says genuine_attribute=false AND that
         descriptor literally appears (word-boundary, case-insensitive) in the current title.
         profile.promotional_title_terms (list, optional) is a client-supplied screen: a literal hit is an
         ai_review, never a deterministic finding; no built-in promotional vocabulary.
         Query-product evidence prioritizes descriptors only when mapped to a unique full key AND ctx.mature
         is True; product-title reports are never treated as search-query reports.
         verify(): proposed titles must keep the reviewed key, stay <= 150 characters (Merchant Center title
         limit), keep the feed brand when known, and contain no non-genuine descriptor or profile promo term.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
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

SKILL = "skill-151-product-feed-seasonal-keyword-optimization"
VERSION = "1.0.0"

FEED = "external/seasonal_feed"
DESC = "external/product_descriptor_evidence"
QPE = "custom/query_product_evidence"
TITLE_MAX = 150  # Merchant Center title attribute limit (support.google.com/merchants/answer/6324415)
_PRODUCT_CHANNELS = ("SHOPPING", "PERFORMANCE_MAX")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _contains(text, phrase) -> bool:
    """Case-insensitive literal phrase containment on word boundaries."""
    t, p = V.norm_text(text), V.norm_text(phrase)
    if not t or not p:
        return False
    return re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", t) is not None


def _key(r) -> tuple:
    return (_s(r.get("merchant_id")), _s(r.get("feed_label")), _s(r.get("language")), _s(r.get("item_id")))


def _entity(key: tuple) -> dict:
    return {"merchant_id": key[0], "feed_label": key[1], "language": key[2], "item_id": key[3]}


def _feed_index(ctx) -> tuple[dict, list[str]]:
    """Latest snapshot per full key. Rules: two rows at the same key and snapshot are a conflict, not a merge."""
    best: dict[tuple, dict] = {}
    conflicts = []
    for r in ctx.rows(FEED):
        k = _key(r)
        if not all(k):
            conflicts.append(f"feed row with incomplete key {k}")
            continue
        old = best.get(k)
        if old is None or _s(r.get("snapshot_at")) > _s(old.get("snapshot_at")):
            best[k] = r
        elif _s(r.get("snapshot_at")) == _s(old.get("snapshot_at")) and r != old:
            conflicts.append(f"duplicate feed rows for {k} at snapshot {_s(r.get('snapshot_at')) or 'unknown'}")
    return best, sorted(set(conflicts))


def _resolve(r, feed: dict) -> tuple[tuple | None, list[tuple]]:
    """Map a source row to one full feed key. Returns (key, candidates); key None means unresolved/ambiguous."""
    m, item = _s(r.get("merchant_id")), _s(r.get("item_id"))
    fl, lang = _s(r.get("feed_label")), _s(r.get("language"))
    cands = sorted(k for k in feed if k[0] == m and k[3] == item
                   and (not fl or k[1] == fl) and (not lang or k[2] == lang))
    return (cands[0] if len(cands) == 1 else None), cands


def _promo_terms(ctx) -> list[str]:
    terms = ctx.profile.get("promotional_title_terms")
    if isinstance(terms, str):
        terms = V.split_list(terms)
    return sorted({_s(t) for t in (terms or []) if _s(t)})


def run(ctx) -> None:
    """Run product-key join, descriptor, query-evidence, promotional-title, identity and title-proposal checks.

    Rules:   Ambiguous product keys → Info, never fanned out across labels/languages. Deterministic Warning only when a
             genuine_attribute=false descriptor literally appears in the current title; profile.promotional_title_terms
             hits and keyword stuffing are ai_review. Query evidence prioritizes only on unique full keys with
             ctx.mature True, else descriptive; title proposals are request-only reviews.
    """
    ids = ("product_key_join", "descriptor_evidence", "query_mapping", "promotional_title_text",
           "title_identity", "title_proposals")
    titles = {"product_key_join": "Join descriptor evidence to full product keys",
              "descriptor_evidence": "Genuine seasonal descriptors versus current titles",
              "query_mapping": "Query-to-product evidence for descriptor prioritization",
              "promotional_title_text": "Promotional or misleading text in current titles",
              "title_identity": "Brand, variant and keyword-repetition preservation",
              "title_proposals": "Request-only before/after title proposals"}

    scope = ctx.check("product_scope", "Shopping/PMax product campaigns in scope", {"campaigns": ["id", "channel_type"]})
    if scope.runnable:
        prod = sorted(_s(c.get("id")) for c in ctx.rows("campaigns")
                      if _s(c.get("channel_type")).upper() in _PRODUCT_CHANNELS)
        scope.observe("Product campaigns (Shopping/PMax) in the export", campaign_ids=prod, count=len(prod))
        if not prod and ctx.table("campaigns").complete is True:
            for cid in ids:
                ctx.check(cid, titles[cid], applicable=False,
                          na_reason="complete campaign inventory has no Shopping/PMax campaign")
            return

    join = ctx.check("product_key_join", titles["product_key_join"],
                     {FEED: ["merchant_id", "feed_label", "language", "item_id", "snapshot_at", "title"],
                      DESC: ["merchant_id", "item_id", "descriptor", "genuine_attribute"]})
    if not join.runnable:
        for cid in ids[1:]:
            ctx.check(cid, titles[cid]).skip("product key join unavailable", join.missing)
        return
    feed, conflicts = _feed_index(ctx)
    for c in conflicts:
        join.partial(c)
    desc_by_key: dict[tuple, list[dict]] = {}
    ambiguous: dict[tuple, list] = {}
    unmatched = 0
    for r in sorted(ctx.rows(DESC), key=lambda r: (_key(r), _s(r.get("descriptor")))):
        k, cands = _resolve(r, feed)
        if k is not None:
            desc_by_key.setdefault(k, []).append(r)
        elif cands:
            ambiguous.setdefault((_s(r.get("merchant_id")), _s(r.get("item_id"))), []).append(
                {"descriptor": r.get("descriptor"), "candidates": [_entity(c) for c in cands]})
        else:
            unmatched += 1
    for (m, item), rows in sorted(ambiguous.items()):
        join.finding("ambiguous_product_key", "Info", {"merchant_id": m, "item_id": item, "source": DESC},
                     f"Descriptor evidence for {m}/{item} lacks feed_label/language and matches "
                     f"{len(rows[0]['candidates'])} feed products; variant/language attribution skipped",
                     evidence={"descriptor_rows": rows, "mapping": "merchant_id+item_id only; not unique"},
                     recommendation="Ask the catalog owner for feed_label and language on each descriptor row.",
                     uncertainty="Descriptor may apply to one, several or none of the candidate products.")
        join.partial(f"{m}/{item}: descriptor evidence ambiguous across feed labels/languages; not attributed")
    if unmatched:
        join.partial(f"{unmatched} descriptor rows match no feed product key")
    join.observe("Product keys resolved", feed_products=len(feed), products_with_descriptor_evidence=len(desc_by_key),
                 ambiguous_sources=len(ambiguous), unmatched_descriptor_rows=unmatched)

    # -- step 2: genuine descriptors
    desc = ctx.check("descriptor_evidence", titles["descriptor_evidence"])
    opportunities: dict[tuple, list[str]] = {}
    unknown_genuine = 0
    for k in sorted(desc_by_key):
        f = feed[k]
        for r in desc_by_key[k]:
            g = V.boolean(r.get("genuine_attribute"))
            if g is None:
                unknown_genuine += 1
                continue
            if g and not _contains(f.get("title"), r.get("descriptor")):
                opportunities.setdefault(k, []).append(_s(r.get("descriptor")))
                desc.finding("truthful_descriptor_opportunity", "Info", {**_entity(k), "descriptor": _s(r.get("descriptor"))},
                             f"Genuine descriptor '{_s(r.get('descriptor'))}' is evidenced but absent from title "
                             f"'{_s(f.get('title'))}'",
                             evidence={"title": f.get("title"), "snapshot_at": f.get("snapshot_at"),
                                       "product_page_snapshot_ref": r.get("product_page_snapshot_ref"),
                                       "applicable_season_or_event": r.get("applicable_season_or_event"),
                                       "truthful_use_rationale": r.get("truthful_use_rationale"), "owner": r.get("owner")},
                             recommendation="Consider the descriptor in a controlled feed test; no automatic seasonal prefix.",
                             uncertainty="Descriptor presence does not guarantee visibility or uplift.")
    if unknown_genuine:
        desc.partial(f"{unknown_genuine} descriptor rows with unknown genuine_attribute not evaluated")
    desc.observe("Genuine descriptors absent from titles", products=len(opportunities),
                 descriptors=sum(len(v) for v in opportunities.values()))

    # -- step 3: query-product mapping (optional)
    q = ctx.check("query_mapping", titles["query_mapping"],
                  {QPE: ["query", "merchant_id", "item_id", "impressions", "clicks", "conversions", "mapping_method",
                         "coverage"]})
    if q.runnable:
        if ctx.mature is not True:
            q.partial(f"query evidence descriptive only: maturity={ctx.mature} ({ctx.maturity_note})")
        min_impr = ctx.params.get("min_impressions")
        mapped: dict[tuple, dict] = {}
        amb_rows = []
        for r in sorted(ctx.rows(QPE), key=lambda r: (_key(r), _s(r.get("query")), _s(r.get("date")))):
            k, cands = _resolve(r, feed)
            if k is None:
                amb_rows.append((r, cands))
                continue
            acc = mapped.setdefault(k, {"queries": set(), "impressions": 0.0, "clicks": 0.0, "conversions": 0.0,
                                        "unknown_cells": 0, "rows": 0})
            acc["queries"].add(_s(r.get("query")))
            acc["rows"] += 1
            for col in ("impressions", "clicks", "conversions"):
                v = V.num(r.get(col))
                if v is None:
                    acc["unknown_cells"] += 1
                else:
                    acc[col] += v
        for r, cands in amb_rows:
            ent = {"merchant_id": _s(r.get("merchant_id")), "item_id": _s(r.get("item_id")), "query": _s(r.get("query")),
                   "source": QPE}
            q.finding("ambiguous_query_product_mapping", "Info", ent,
                      f"Query '{_s(r.get('query'))}' maps to {len(cands)} feed products for "
                      f"{ent['merchant_id']}/{ent['item_id']}; product-specific query attribution skipped",
                      evidence={"candidates": [_entity(c) for c in cands], "mapping_method": r.get("mapping_method"),
                                "coverage": r.get("coverage"), "source_report": r.get("source_report"),
                                "impressions": V.num(r.get("impressions")), "clicks": V.num(r.get("clicks")),
                                "conversions": V.num(r.get("conversions")), "date": r.get("date")},
                      recommendation="Request a query-product report keyed by feed_label and language.",
                      uncertainty="Metrics are not split across candidate products; no product-specific opportunity claimed.")
        if amb_rows:
            q.partial(f"{len(amb_rows)} query rows without a unique full product key were not attributed")
        for k in sorted(mapped):
            acc = mapped[k]
            gate = min_impr.value is not None and acc["impressions"] >= min_impr.value
            hits = sorted(d for d in opportunities.get(k, []) if any(_contains(qq, d) for qq in acc["queries"]))
            q.observe(f"Mapped query evidence for {'/'.join(k)}", **_entity(k), queries=sorted(acc["queries"]),
                      impressions=acc["impressions"], clicks=acc["clicks"], conversions=acc["conversions"],
                      unknown_cells=acc["unknown_cells"], min_impressions=min_impr.value,
                      min_impressions_source=min_impr.source, sample_gate=gate,
                      descriptors_seen_in_queries=hits, window=[ctx.period_start, ctx.period_end])
            if hits and gate and ctx.mature is True:
                q.finding("query_supported_descriptor", "Info", {**_entity(k), "descriptors": hits},
                          f"Mapped queries mention genuine descriptor(s) {hits} absent from the title "
                          f"({acc['impressions']:g} impressions >= min_impressions {min_impr.value})",
                          evidence={"queries": sorted(acc["queries"]), "impressions": acc["impressions"],
                                    "clicks": acc["clicks"], "conversions": acc["conversions"],
                                    "min_impressions": min_impr.value, "source": min_impr.source},
                          recommendation="Prioritize this descriptor in a controlled feed title test.",
                          uncertainty="Observed query language is correlational; no visibility uplift is implied.")

    # -- step 4: promotional/misleading title text
    promo = ctx.check("promotional_title_text", titles["promotional_title_text"])
    terms = _promo_terms(ctx)
    if not terms:
        promo.partial("profile.promotional_title_terms not supplied: unevidenced promotional-term screen skipped")
    warned: dict[tuple, dict] = {}
    for k in sorted(feed):
        f = feed[k]
        fields = [("title", f.get("title"))]
        if f.get("structured_title_if_used"):
            fields.append(("structured_title_if_used", f.get("structured_title_if_used")))
        bad = [r for r in desc_by_key.get(k, []) if V.boolean(r.get("genuine_attribute")) is False]
        for field, text in fields:
            for r in bad:
                if not _contains(text, r.get("descriptor")):
                    continue
                d = _s(r.get("descriptor"))
                ent = {**_entity(k), "field": field}
                fnd = promo.finding("promotional_title_text", "Warning", ent,
                                    f"{field} '{_s(text)}' contains '{d}', which client evidence marks as not a genuine "
                                    f"product attribute",
                                    evidence={field: text, "descriptor": d, "genuine_attribute": False,
                                              "truthful_use_rationale": r.get("truthful_use_rationale"),
                                              "product_page_snapshot_ref": r.get("product_page_snapshot_ref"),
                                              "applicable_season_or_event": r.get("applicable_season_or_event"),
                                              "owner": r.get("owner"), "promotion_ids": f.get("promotion_ids"),
                                              "approval_status": f.get("approval_status"), "snapshot_at": f.get("snapshot_at")},
                                    recommendation="Remove the promotional text from the title; use an eligible Merchant "
                                                   "promotion or price field instead (request-only).",
                                    uncertainty="Visibility/approval impact of the change is not estimated.")
                warned[(k, field)] = {"finding": fnd, "descriptor": d, "text": _s(text)}
            known = {V.norm_text(r.get("descriptor")) for r in desc_by_key.get(k, [])}
            for t in terms:
                if not _contains(text, t) or V.norm_text(t) in known or (k, field) in warned:
                    continue
                promo.review("promotional_title_text", {**_entity(k), "field": field, "term": t},
                             f"{field} '{_s(text)}' contains the client-listed promotional term '{t}'. Is it "
                             f"promotional/misleading text or a genuine product descriptor?",
                             evidence={field: text, "term": t, "brand": f.get("brand"),
                                       "description": f.get("description"), "product_url": f.get("product_url"),
                                       "promotion_ids": f.get("promotion_ids")},
                             outcomes={"promotional_text": {"severity": "Warning", "recommendation":
                                                            "Remove from title; supply proposal.proposed_title."},
                                       "genuine_descriptor": {"severity": None, "recommendation": "Keep."},
                                       "uncertain": {"severity": "Info", "recommendation":
                                                     "Ask the catalog owner for product evidence."}},
                             guidance="Judge only from the item evidence; a term that is part of the brand or product "
                                      "name is genuine. For promotional_text supply proposal {proposed_title, owner}.")
    promo.observe("Titles screened for promotional text", products=len(feed), evidenced_warnings=len(warned),
                  profile_terms=terms)

    # -- step 5: identity preservation
    ident = ctx.check("title_identity", titles["title_identity"])
    no_brand = []
    for k in sorted(feed):
        f = feed[k]
        title = f.get("title")
        brand = _s(f.get("brand"))
        if brand and not _contains(title, brand):
            no_brand.append("/".join(k))
        tokens = [t for t in re.findall(r"\w+", V.norm_text(title)) if len(t) > 2]
        repeats = sorted({t for t in tokens if tokens.count(t) >= 3})
        if repeats:
            ident.review("keyword_repetition", _entity(k),
                         f"Title '{_s(title)}' repeats {repeats} three or more times. Is this keyword stuffing?",
                         evidence={"title": title, "repeated_tokens": repeats, "brand": brand},
                         outcomes={"misleading_stuffing": {"severity": "Warning", "recommendation":
                                                           "Rewrite the title descriptively; supply proposal.proposed_title."},
                                   "legitimate": {"severity": None, "recommendation": "Keep."},
                                   "uncertain": {"severity": "Info", "recommendation": "Ask the catalog owner."}},
                         guidance="Repeated brand/model tokens can be legitimate; judge descriptive accuracy only.")
        variants = V.split_list(f.get("variant_attributes"))
        missing_variants = sorted(v for v in variants if not _contains(title, v))
        if missing_variants:
            ident.observe(f"Variant attributes not in title for {'/'.join(k)}", **_entity(k),
                          variant_attributes_absent=missing_variants)
    ident.observe("Brand literally absent from title", products=no_brand, count=len(no_brand))

    # -- step 6: request-only proposals for evidenced Warnings
    prop = ctx.check("title_proposals", titles["title_proposals"])
    for (k, field), w in sorted(warned.items()):
        prop.review("promotional_title_text", {**_entity(k), "field": field},
                    f"Draft a truthful replacement for {field} '{w['text']}' without '{w['descriptor']}'.",
                    evidence={"current": w["text"], "remove": w["descriptor"], "brand": feed[k].get("brand"),
                              "description": feed[k].get("description"),
                              "variant_attributes": feed[k].get("variant_attributes")},
                    outcomes={"proposal_drafted": {"severity": "Warning", "recommendation":
                                                   "Request-only: controlled feed test with the verified title."},
                              "owner_input_needed": {"severity": "Warning", "recommendation":
                                                     "Remove the promotional text; catalog owner drafts the title."}},
                    guidance="proposal_drafted needs proposal {proposed_title, owner, test_plan}; the script verifies it.",
                    provisional=w["finding"])
    prop.observe("Title proposals requested", count=len(warned))


def verify(ctx, item, decision) -> list[str]:
    """Rules: proposed titles are checked against the item's non-genuine descriptors."""
    outcome = decision.get("outcome")
    if outcome not in ("proposal_drafted", "promotional_text", "misleading_stuffing"):
        return []
    p = decision.get("proposal") or {}
    title = _s(p.get("proposed_title"))
    if not title:
        return ["proposal.proposed_title required"]
    problems = []
    if outcome == "proposal_drafted" and not _s(p.get("owner")):
        problems.append("proposal.owner required")
    if len(title) > TITLE_MAX:
        problems.append(f"proposed title has {len(title)} characters > {TITLE_MAX}")
    e = item.entity
    key = (_s(e.get("merchant_id")), _s(e.get("feed_label")), _s(e.get("language")), _s(e.get("item_id")))
    feed, _ = _feed_index(ctx)
    f = feed.get(key)
    if f is None:
        return problems + [f"reviewed product {key} not in feed"]
    current = _s(f.get(e.get("field") or "title"))
    if V.norm_text(title) == V.norm_text(current):
        problems.append("proposed title equals the current title")
    brand = _s(f.get("brand"))
    if brand and _contains(current, brand) and not _contains(title, brand):
        problems.append(f"proposed title drops brand '{brand}'")
    for r in ctx.rows(DESC):
        k, _c = _resolve(r, feed)
        if k == key and V.boolean(r.get("genuine_attribute")) is False and _contains(title, r.get("descriptor")):
            problems.append(f"proposed title still contains non-genuine '{_s(r.get('descriptor'))}'")
    for t in _promo_terms(ctx):
        if _contains(title, t) and not (brand and _contains(brand, t)):
            problems.append(f"proposed title contains profile promotional term '{t}'")
    return sorted(set(problems))


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
