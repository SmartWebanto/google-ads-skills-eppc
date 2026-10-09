"""check.py — skill-082 deterministic Merchant Center title screening with verified revision proposals.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-082-product-feed-title-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-083-product-feed-attribute-completeness/scripts/check.py — same product-key, reference and
         diagnostics joins (non-title attribute defects are owned there)
         skills/skill-151-product-feed-seasonal-keyword-optimization/scripts/check.py — seasonal/promotional
         merchandising owner; shares the profile.promotional_title_terms screen
rules:   Product key = (merchant_id, channel, content_language, feed_label, offer_id, target_country, destination);
         merchant_id/offer_id/target_country/destination required, absent optional parts → partial "key incomplete".
         Titles are judged per product unit (key without destination); destination rows only add scope.
         Effective title = first non-empty of effective_title, structured_title, submitted_title, title (the
         column used is recorded); structured_title wins over title when both are submitted.
         Deterministic Warning only for a title column longer than 150 characters (Merchant Center 1–150 limit,
         support.google.com/merchants/answer/6324415). Empty cells are unknown, never a zero-length title.
         profile.promotional_title_terms (list, optional) is a client-supplied screen: a literal word-boundary hit
         is an ai_review, never a deterministic finding; no built-in promotional vocabulary.
         Repeated words, identical titles across products/variants and reference-title differences are ai_review
         only; Brand + Type + Attributes ordering is never mandated; verified brand absent from the title is Info.
         Reference columns: authoritative_title, verified_brand, evidence_reference, updated_at,
         intended_destinations (list) and variant attributes under their plain names.
         Critical only via ai_review on a CURRENT blocking title diagnostic; verify() demands proposal.evidence_ref.
         verify(): every Warning correction outcome needs proposal.proposed_title of 1–150 characters and
         proposal.fact_reference; it must not contain a sibling variant's distinguishing value or a profile promo
         term; proposal.ai_generated=true requires attribute structured_title with digital_source_type
         trained_algorithmic_media.
         Title CTR cohorts are descriptive only: ctx.mature True, same category+country, both cohorts >=
         min_impressions (ctx.params), else partial; never causal lift, never savings.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
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

SKILL = "skill-082-product-feed-title-optimization"
VERSION = "1.0.0"

MP = "external/merchant_products"
MD = "external/merchant_diagnostics"
REF = "external/product_reference"
TR = "external/title_requirements"
PD = "custom/product_daily"
KEY_ORDER = ("merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country", "destination")
KEY_REQ = ["merchant_id", "offer_id", "target_country", "destination"]
KEY_OPT = ("channel", "content_language", "feed_label")
TITLE_COLS = ("effective_title", "structured_title", "submitted_title", "title")
TITLE_MAX = 150
PRODUCT_CHANNELS = {"SHOPPING", "PERFORMANCE_MAX"}
VARIANT_ATTRS = ("color", "size", "material", "pattern", "gender", "age_group")
NA_TOKENS = {"n/a", "na", "not_applicable", "not applicable"}
WILDCARD = {"*", "all", "any"}
BLOCKING = {"disapproved", "not_eligible", "ineligible"}
DEMOTED = {"demoted", "limited"}
NO_ISSUE = {"no_issue", "no issue", "no issues", "none"}
TR_COLS = ["market", "destination", "product_category", "rule_id", "requirement_or_recommendation",
           "requirement_text", "source_url", "checked_at"]
MD_COLS = ["offer_id", "target_country", "destination", "issue_code", "attribute", "eligibility_status", "observed_at"]
PD_COLS = ["campaign_id", "offer_id", "date", "impressions", "clicks"]
AI_SOURCE_TYPE = "trained_algorithmic_media"
PROPOSAL_KEYS = {"variant_distinction_missing", "variant_title_mismatch", "promotional_title_text",
                 "repeated_title_terms", "shared_title_across_products", "title_differs_from_reference"}
CHECKS = (("catalog_join", "Product-key join, scope counts and unresolved joins"),
          ("effective_title", "Effective title and variant correspondence"),
          ("title_spec", "Merchant Center title specification and promotional text"),
          ("title_clarity", "Repeated keywords and ambiguous shared titles"),
          ("revision_support", "Title versus verified catalog facts"),
          ("title_cohort_ctr", "Descriptive CTR of screened vs unscreened titles"),
          ("title_disapprovals", "Current title-related Merchant diagnostics"))
EDIT_OUTCOMES = {"editorial_issue": {"severity": "Warning", "recommendation":
                                     "Propose a fact-supported title (proposal.proposed_title, fact_reference)."},
                 "clarity_opportunity": {"severity": "Info", "recommendation": "Optional clarity revision."},
                 "keep": {"severity": None, "recommendation": "Keep: legitimate model/brand/business wording."},
                 "uncertain": {"severity": "Info", "recommendation": "Ask the catalog owner for product facts."}}


# ---------------------------------------------------------------- helpers (private; mirrored in skill-083)
def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _low(v) -> str:
    return " ".join(_s(v).lower().split())


def _key(r) -> tuple:
    return tuple(_s(r.get(c)) for c in KEY_ORDER)


def _ent(key: tuple, **extra) -> dict:
    return {**{c: v for c, v in zip(KEY_ORDER, key) if v}, **extra}


def _proj(key: tuple, cols) -> tuple:
    return tuple(key[KEY_ORDER.index(c)] for c in cols)


def _contains(text, phrase) -> bool:
    """Case-insensitive literal phrase containment on word boundaries."""
    t, p = _low(text), _low(phrase)
    return bool(t and p) and re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", t) is not None


def _pick(row: dict, cols, attr: str) -> str | None:
    for c in (f"effective_{attr}", attr, f"submitted_{attr}"):
        if c in cols:
            v = _s(row.get(c))
            return v if v and v.lower() not in NA_TOKENS else None
    return None


def _title(row: dict, cols) -> tuple[str | None, str | None]:
    for c in TITLE_COLS:
        if c in cols and _s(row.get(c)):
            return _s(row.get(c)), c
    return None, None


def _title_col(ctx) -> str:
    t = ctx.table(MP)
    return next((c for c in TITLE_COLS if t is not None and c in t.columns), "effective_title")


def _applicability(ctx) -> tuple[bool | None, str]:
    t = ctx.table("campaigns")
    if t is None or "channel_type" not in t.columns:
        return None, "campaigns:channel_type unavailable; Shopping/PMax scope unknown"
    types = {_s(r.get("channel_type")).upper() for r in t.rows}
    if types & PRODUCT_CHANNELS:
        return True, "SHOPPING/PERFORMANCE_MAX campaigns present: " + ", ".join(sorted(types & PRODUCT_CHANNELS))
    if t.complete is True:
        return False, "no SHOPPING or PERFORMANCE_MAX campaign in the complete campaigns inventory"
    return None, "no product campaign in an uncertified campaigns inventory; scope unknown"


def _catalog(ctx, chk) -> tuple[dict, list[str], dict]:
    """Deduplicated catalog {key: row}: identical rows dedupe, differing rows at the latest snapshot conflict."""
    t = ctx.table(MP)
    absent = [c for c in KEY_OPT if c not in t.columns]
    if absent:
        chk.partial("product key incomplete: rows from different channels/languages/feed labels may share a key",
                    [f"{MP}:{c}" for c in absent])
    grouped: dict[tuple, list[dict]] = {}
    bad = 0
    for r in t.rows:
        if not all(_s(r.get(c)) for c in KEY_REQ):
            bad += 1
            continue
        grouped.setdefault(_key(r), []).append(r)
    cat, conflicts, dupes = {}, 0, 0
    for k in sorted(grouped):
        rows = grouped[k]
        latest = max(_s(r.get("snapshot_at")) for r in rows)
        top = {tuple(sorted((a, _s(b)) for a, b in r.items())): r for r in rows if _s(r.get("snapshot_at")) == latest}
        if len(top) > 1:
            conflicts += 1
            continue
        dupes += len(rows) - 1
        cat[k] = next(iter(top.values()))
    if bad:
        chk.partial(f"{bad} merchant_products rows lack a required key part; excluded")
    if conflicts:
        chk.partial(f"{conflicts} product keys have conflicting rows at the same snapshot; excluded from decisions")
    return cat, t.columns, {"incomplete_key_rows": bad, "conflicting_keys": conflicts, "identical_duplicates": dupes}


def _ref_index(ctx, mp_cols) -> tuple[dict, list[str] | None]:
    t = ctx.table(REF)
    if t is None or t.missing(["offer_id", "target_country"]) or not {"offer_id", "target_country"} <= set(mp_cols):
        return {}, None
    shared = [c for c in KEY_ORDER if c != "destination" and c in t.columns and c in mp_cols]
    idx: dict[tuple, list[dict]] = {}
    for r in t.rows:
        idx.setdefault(tuple(_s(r.get(c)) for c in shared), []).append(r)
    return idx, shared


def _ref_row(idx, shared, key) -> tuple[dict | None, str]:
    if shared is None:
        return None, "unavailable"
    rows = idx.get(_proj(key, shared), [])
    if len(rows) == 1:
        return rows[0], "matched"
    return None, "ambiguous" if rows else "unmatched"


def _items(cat, cols) -> tuple[list[dict], int]:
    """Title items: one per (product unit, effective title) with its destination keys."""
    by: dict[tuple, dict[str, list[tuple]]] = {}
    src: dict[tuple, str] = {}
    unknown = 0
    for k in sorted(cat):
        t, c = _title(cat[k], cols)
        if t is None:
            unknown += 1
            continue
        by.setdefault(k[:-1], {}).setdefault(t, []).append(k)
        src[(k[:-1], t)] = c
    items = []
    for u in sorted(by):
        for t in sorted(by[u]):
            keys = by[u][t]
            ent = _ent(u, **({"destinations": [k[6] for k in keys]} if len(by[u]) > 1 else {}))
            items.append({"unit": u, "title": t, "source": src[(u, t)], "keys": keys, "row": cat[keys[0]],
                          "entity": ent})
    return items, unknown


def _variant_context(items, cols) -> dict:
    """unit → {'own': {attr: value}, 'siblings': sorted sibling values that differ from own, 'group': id|None}."""
    groups: dict[tuple, list[dict]] = {}
    for it in items:
        g = _s(it["row"].get("item_group_id"))
        if g:
            u = it["unit"]
            groups.setdefault((u[0], u[1], u[2], u[3], u[5], g), []).append(it)
    out = {}
    for it in items:
        own = {a: _pick(it["row"], cols, a) for a in VARIANT_ATTRS if _pick(it["row"], cols, a)}
        out[it["unit"]] = {"own": own, "siblings": [], "group": _s(it["row"].get("item_group_id")) or None}
    for members in groups.values():
        for it in members:
            own = out[it["unit"]]["own"]
            sib = {_pick(o["row"], cols, a) for o in members if o["unit"] != it["unit"] for a in VARIANT_ATTRS
                   if a in own and _pick(o["row"], cols, a) and _low(_pick(o["row"], cols, a)) != _low(own[a])}
            out[it["unit"]]["siblings"] = sorted(sib)
    return out


def _terms(ctx) -> list[str] | None:
    terms = ctx.profile.get("promotional_title_terms")
    if terms is None:
        return None
    if isinstance(terms, str):
        terms = V.split_list(terms)
    return sorted({_s(t) for t in terms if _s(t)})


def _match(rule, value) -> bool | None:
    r = _low(rule)
    if not r:
        return None
    if r in WILDCARD:
        return True
    v = _low(value)
    return None if not v else (v == r or v.startswith(r + " > "))


# ---------------------------------------------------------------- run
def run(ctx) -> None:
    """Gate on product campaigns, join the Merchant catalog, then run title, clarity, revision, cohort, diagnostic checks.

    Rules:   No Shopping/PMax campaign → all 7 checks not applicable; unknown scope or missing title column → partial.
             Deterministic Warning only for titles > 150 chars and current demoted/blocking title diagnostics (else Info);
             promo terms, repeats, shared/variant titles, reference mismatches → ai_review; Critical only via ai_review.
             CTR cohorts need ctx.mature and min_impressions, are descriptive only and never produce a finding.
    """
    applicable, why = _applicability(ctx)
    if applicable is False:
        for cid, title in CHECKS:
            ctx.check(cid, title, applicable=False, na_reason=why)
        return
    tcol = _title_col(ctx)
    join = ctx.check(*CHECKS[0], {MP: KEY_REQ})
    if applicable is None:
        join.partial(why, ["campaigns:channel_type"])
    cat, cols, items, flagged = {}, [], [], set()
    if join.runnable:
        cat, cols, stats = _catalog(ctx, join)
        items, _ = _items(cat, cols)
        _join(ctx, join, cat, cols, stats)
    vctx = _variant_context(items, cols)
    title_needs = {MP: KEY_REQ + [tcol]}
    title_checks = [ctx.check(*CHECKS[i], title_needs) for i in (1, 2, 3)]
    title_checks.append(ctx.check(*CHECKS[4], {**title_needs, REF: ["offer_id", "target_country",
                                                                    "evidence_reference"]}))
    title_checks.append(ctx.check(*CHECKS[5], {**title_needs, PD: PD_COLS}))
    if ctx.table(MP) is not None and tcol not in ctx.table(MP).columns:
        for c in title_checks:
            c.partial("no title column; accepted: " + ", ".join(TITLE_COLS))
    _effective(ctx, title_checks[0], items, cols, vctx, cat)
    _spec(ctx, title_checks[1], items, cols, vctx, flagged)
    _clarity(ctx, title_checks[2], items, vctx, flagged)
    _revision(ctx, title_checks[3], items, cols, vctx, flagged)
    _cohorts(ctx, title_checks[4], items, cols, flagged)
    _disapprovals(ctx, ctx.check(*CHECKS[6], {MD: MD_COLS}), cat, cols)


def _join(ctx, chk, cat, cols, stats) -> None:
    units = {k[:-1] for k in cat}
    scopes: dict[tuple, set] = {}
    for k in cat:
        scopes.setdefault((k[5], k[6]), set()).add(k[4])
    complete = ctx.table(MP).complete is True
    ref_status = None
    idx, shared = _ref_index(ctx, cols)
    if shared is not None:
        ref_status = {"matched": 0, "ambiguous": 0, "unmatched": 0}
        for u in sorted(units):
            ref_status[_ref_row(idx, shared, u + ("",))[1]] += 1
        if ref_status["ambiguous"] or ref_status["unmatched"]:
            chk.partial(f"{ref_status['unmatched']} products without and {ref_status['ambiguous']} with ambiguous "
                        f"catalog reference rows (joined on {', '.join(shared)})")
    else:
        chk.partial("catalog reference unavailable: title facts cannot be verified",
                    [f"{REF} (file)"] if ctx.table(REF) is None else
                    [f"{REF}:{c}" for c in ctx.table(REF).missing(["offer_id", "target_country"])])
    chk.observe("Product-key join", destination_rows=len(cat), unique_products=len(units), **stats,
                offers_per_scope={f"{c}/{d}": len(v) for (c, d), v in sorted(scopes.items())},
                reference_joins=ref_status, reference_join_columns=shared, catalog_complete=complete,
                denominator="complete catalog" if complete else "supplied product sample only; no catalog percentages")


def _effective(ctx, chk, items, cols, vctx, cat) -> None:
    if not chk.runnable:
        return
    unknown = sum(1 for k in cat if _title(cat[k], cols)[0] is None)
    if unknown:
        chk.partial(f"{unknown} destination rows without any title value (unknown, not zero-length)")
    sources: dict[str, int] = {}
    for it in items:
        sources[it["source"]] = sources.get(it["source"], 0) + 1
    if "structured_title" in cols and "digital_source_type" not in cols:
        chk.partial("structured_title provenance unknown", [f"{MP}:digital_source_type"])
    if "item_group_id" not in cols:
        chk.partial("variant correspondence not evaluable", [f"{MP}:item_group_id"])
    groups: dict[tuple, list[dict]] = {}
    for it in items:
        if vctx[it["unit"]]["group"]:
            u = it["unit"]
            groups.setdefault((u[0], u[1], u[2], u[3], u[5], vctx[u]["group"]), []).append(it)
    screened = 0
    for g in sorted(groups):
        members = groups[g]
        by_title: dict[str, list[dict]] = {}
        for it in members:
            by_title.setdefault(_low(it["title"]), []).append(it)
        for t in sorted(by_title):
            same = by_title[t]
            differing = sorted({a for x in same for y in same for a in VARIANT_ATTRS
                                if a in vctx[x["unit"]]["own"] and a in vctx[y["unit"]]["own"]
                                and _low(vctx[x["unit"]]["own"][a]) != _low(vctx[y["unit"]]["own"][a])})
            if len(same) < 2 or not differing:
                continue
            screened += 1
            ent = {"merchant_id": g[0], "target_country": g[4], "item_group_id": g[5],
                   "offer_ids": sorted(x["unit"][4] for x in same)}
            ev = {"title": same[0]["title"], "variant_values": {x["unit"][4]: vctx[x["unit"]]["own"] for x in same},
                  "differing_attributes": differing, "sibling_variant_values": sorted(
                      {v for x in same for v in vctx[x["unit"]]["siblings"]}), "title_source": same[0]["source"]}
            prov = chk.finding("variant_distinction_missing", "Info", ent,
                               f"{len(same)} variants of group {g[5]} ({g[4]}) share one title although they differ "
                               f"in {', '.join(differing)}", evidence=ev,
                               recommendation="Consider adding the distinguishing variant value to each title.",
                               uncertainty="Clarity opportunity; whether the distinction is required needs review.")
            chk.review("variant_distinction_missing", ent,
                       "Do these variant titles need the distinguishing attribute to identify the product correctly?",
                       evidence=ev,
                       outcomes={"variant_distinction_missing": {"severity": "Warning", "recommendation":
                                 "Propose per-variant titles with fact_reference; keep each variant's own values."},
                                 "acceptable": {"severity": None, "recommendation": "Keep the shared title."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the catalog owner."}},
                       guidance="Use feed/catalog variant facts only; do not invent attributes.", provisional=prov)
        for it in members:
            own, title = vctx[it["unit"]]["own"], it["title"]
            others = [v for v in vctx[it["unit"]]["siblings"] if _contains(title, v)]
            if others and not any(_contains(title, v) for v in own.values()):
                chk.review("variant_title_mismatch", it["entity"],
                           f"Title '{title}' names sibling variant value(s) {others} but not its own "
                           f"{own}. Is this a product/variant mismatch?",
                           evidence={"title": title, "title_source": it["source"], "own_variant_values": own,
                                     "sibling_variant_values": vctx[it["unit"]]["siblings"],
                                     "item_group_id": vctx[it["unit"]]["group"]},
                           outcomes={"documented_mismatch": {"severity": "Warning", "recommendation":
                                     "Propose a corrected title citing the variant facts."},
                                     "not_mismatch": {"severity": None, "recommendation": "Keep."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask the catalog owner."}},
                           guidance="A sibling value can be a legitimate descriptor (e.g. a pattern name).")
    chk.observe("Effective titles resolved", title_items=len(items), title_sources=sources,
                variant_groups=len(groups), shared_variant_titles=screened)


def _spec(ctx, chk, items, cols, vctx, flagged) -> None:
    if not chk.runnable:
        return
    tr = ctx.table(TR)
    reqs = []
    if tr is None or tr.missing(TR_COLS):
        chk.partial("title requirement matrix unavailable: only the recipe-cited 150-character limit applies",
                    [f"{TR} (file)"] if tr is None else [f"{TR}:{c}" for c in tr.missing(TR_COLS)])
    else:
        reqs = ctx.rows(TR)
    terms = _terms(ctx)
    if terms is None:
        chk.partial("profile.promotional_title_terms not supplied: promotional-text screen not run",
                    ["profile:promotional_title_terms"])
    over = hits = 0
    for it in items:
        row, u = it["row"], it["unit"]
        lengths = {c: len(_s(row.get(c))) for c in TITLE_COLS if c in cols and _s(row.get(c))}
        long_cols = sorted(c for c, n in lengths.items() if n > TITLE_MAX)
        applicable = [{c: r.get(c) for c in TR_COLS} for r in reqs
                      if _match(r.get("market"), u[5]) is not False
                      and any(_match(r.get("destination"), k[6]) is not False for k in it["keys"])
                      and _match(r.get("product_category"), _pick(row, cols, "google_product_category")) is not False]
        if long_cols:
            over += 1
            flagged.add(u)
            chk.finding("title_over_150_chars", "Warning", it["entity"],
                        f"Offer {u[4]} ({u[5]}) title exceeds {TITLE_MAX} characters in {', '.join(long_cols)}",
                        evidence={"lengths": lengths, "title": it["title"], "title_source": it["source"],
                                  "requirement": "support.google.com/merchants/answer/6324415",
                                  "applicable_title_requirements": applicable},
                        calculation={"limit": TITLE_MAX, "max_length": max(lengths[c] for c in long_cols)},
                        recommendation="Ask the feed owner for a fact-based title within 150 characters; keep "
                                       "the variant identity.",
                        uncertainty="Truncation is certain; business impact is not estimated.")
        for term in terms or []:
            if not _contains(it["title"], term):
                continue
            hits += 1
            flagged.add(u)
            chk.review("promotional_title_text", {**it["entity"], "term": term},
                       f"Is '{term}' in title '{it['title']}' promotional sale/shipping text rather than a genuine "
                       f"product descriptor?",
                       evidence={"title": it["title"], "title_source": it["source"], "term_source":
                                 "profile.promotional_title_terms", "applicable_title_requirements": applicable,
                                 "sibling_variant_values": vctx[u]["siblings"]},
                       outcomes={"promotional_text": {"severity": "Warning", "recommendation":
                                 "Propose a title without the promotional text (fact_reference required)."},
                                 "legitimate_descriptor": {"severity": None, "recommendation": "Keep."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the catalog owner."}},
                       guidance="Seasonal merchandising belongs to skill-151; brand or model names are legitimate.")
    chk.observe("Title specification screened", title_items=len(items), over_150=over, promotional_hits=hits,
                requirement_rows=len(reqs), promotional_terms=terms)


def _clarity(ctx, chk, items, vctx, flagged) -> None:
    if not chk.runnable:
        return
    repeated = shared = 0
    for it in items:
        words = re.findall(r"[^\W\d_]{3,}", it["title"].lower())
        dup = sorted({w for w in words if words.count(w) > 1})
        if dup:
            repeated += 1
            flagged.add(it["unit"])
            chk.review("repeated_title_terms", it["entity"],
                       f"Title '{it['title']}' repeats {dup}. Is this keyword repetition an editorial issue?",
                       evidence={"title": it["title"], "repeated_words": dup, "title_source": it["source"],
                                 "sibling_variant_values": vctx[it["unit"]]["siblings"]},
                       outcomes=EDIT_OUTCOMES,
                       guidance="Brand, model numbers and required business wording may legitimately repeat.")
    scopes: dict[tuple, list[dict]] = {}
    for it in items:
        u = it["unit"]
        scopes.setdefault((u[0], u[1], u[2], u[3], u[5], _low(it["title"])), []).append(it)
    for s in sorted(scopes):
        same = scopes[s]
        groups = {vctx[x["unit"]]["group"] for x in same}
        if len({x["unit"][4] for x in same}) < 2 or (len(groups) == 1 and None not in groups):
            continue  # same variant group: handled by effective_title
        shared += 1
        for x in same:
            flagged.add(x["unit"])
        ent = {"merchant_id": s[0], "target_country": s[4], "offer_ids": sorted(x["unit"][4] for x in same)}
        chk.review("shared_title_across_products", ent,
                   f"{len(same)} products outside one variant group share the title '{same[0]['title']}'. "
                   f"Is the wording too generic to tell them apart?",
                   evidence={"title": same[0]["title"], "item_group_ids": sorted(g or "" for g in groups),
                             "variant_values": {x["unit"][4]: vctx[x["unit"]]["own"] for x in same},
                             "sibling_variant_values": []},
                   outcomes=EDIT_OUTCOMES, guidance="Do not mandate Brand + Type + Attributes ordering.")
    chk.observe("Title clarity screened", title_items=len(items), repeated_word_titles=repeated,
                shared_title_sets=shared)


def _revision(ctx, chk, items, cols, vctx, flagged) -> None:
    if not chk.runnable:
        return
    rcols = ctx.table(REF).columns
    if "authoritative_title" not in rcols and "verified_brand" not in rcols:
        chk.partial("no reference title facts", [f"{REF}:authoritative_title", f"{REF}:verified_brand"])
    idx, shared = _ref_index(ctx, cols)
    status = {"matched": 0, "ambiguous": 0, "unmatched": 0, "unavailable": 0}
    for it in items:
        ref, st = _ref_row(idx, shared, it["keys"][0])
        status[st] += 1
        if ref is None:
            continue
        u, title = it["unit"], it["title"]
        facts = {"authoritative_title": ref.get("authoritative_title"), "verified_brand": ref.get("verified_brand"),
                 "evidence_reference": ref.get("evidence_reference"), "updated_at": ref.get("updated_at"),
                 **{a: ref.get(a) for a in VARIANT_ATTRS if a in rcols}}
        brand = _s(ref.get("verified_brand"))
        if brand and brand.lower() not in NA_TOKENS and not _contains(title, brand):
            chk.finding("verified_brand_absent_from_title", "Info", it["entity"],
                        f"Offer {u[4]} ({u[5]}) title does not contain the verified brand '{brand}'",
                        evidence={"title": title, "title_source": it["source"], **facts},
                        recommendation="Optional: add the brand where it helps identification; brand-first order "
                                       "is not required.",
                        uncertainty="Absent brand is a clarity opportunity without demonstrated harm.")
        auth = _s(ref.get("authoritative_title"))
        if auth and _low(auth) != _low(title):
            flagged.add(u)
            chk.review("title_differs_from_reference", it["entity"],
                       f"Feed title '{title}' differs from the authoritative catalog title '{auth}'. Is the feed "
                       f"title a product mismatch, a clarity opportunity or acceptable?",
                       evidence={"title": title, "title_source": it["source"], **facts,
                                 "own_variant_values": vctx[u]["own"], "sibling_variant_values": vctx[u]["siblings"]},
                       outcomes={"product_mismatch": {"severity": "Warning", "recommendation":
                                 "Propose the corrected title with fact_reference = evidence_reference."},
                                 "clarity_opportunity": {"severity": "Info", "recommendation": "Optional revision."},
                                 "no_issue": {"severity": None, "recommendation": "Keep the feed title."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the catalog owner."}},
                       guidance="Differences in wording/order/localization are not mismatches; only contradicting "
                                "product facts are.")
    if status["ambiguous"] or status["unmatched"]:
        chk.partial(f"{status['unmatched']} title items without and {status['ambiguous']} with ambiguous reference "
                    f"rows; no correction proposed for them")
    chk.observe("Titles compared with verified catalog facts", joins=status, join_columns=shared)


def _cohorts(ctx, chk, items, cols, flagged) -> None:
    if not chk.runnable:
        return
    pd = ctx.table(PD)
    pcols = [c for c in KEY_ORDER if c in pd.columns]
    if "target_country" not in pcols:
        chk.partial("product_daily key incomplete", [f"{PD}:target_country"])
    minimp = ctx.params.get("min_impressions")
    if minimp.value is None:
        chk.partial(f"min_impressions unresolved: {minimp.reason}")
    if ctx.mature is not True:
        chk.partial(f"window not mature ({ctx.maturity_note}): descriptive totals only")
    by_proj: dict[tuple, list[dict]] = {}
    for it in items:
        for k in it["keys"]:
            by_proj.setdefault(_proj(k, pcols), []).append(it)
    cells: dict[tuple, dict] = {}
    seen, unmatched, ambiguous, outside = set(), 0, 0, 0
    for r in pd.rows:
        d = V.parse_date(r.get("date"))
        if d is None or (ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end):
            outside += 1
            continue
        proj = tuple(_s(r.get(c)) for c in pcols)
        if (_s(r.get("campaign_id")), proj, d) in seen:
            continue
        seen.add((_s(r.get("campaign_id")), proj, d))
        cands = {it["unit"] for it in by_proj.get(proj, [])}
        if len(cands) != 1:
            unmatched += not cands
            ambiguous += len(cands) > 1
            continue
        it = by_proj[proj][0]
        imp, clk = V.num(r.get("impressions")), V.num(r.get("clicks"))
        if imp is None or clk is None:
            continue
        cell = (_pick(it["row"], cols, "google_product_category") or "(unknown)", it["unit"][5])
        side = "screened" if it["unit"] in flagged else "unscreened"
        c = cells.setdefault(cell, {"screened": [0.0, 0.0], "unscreened": [0.0, 0.0]})
        c[side][0] += imp
        c[side][1] += clk
    if unmatched or ambiguous:
        chk.partial(f"{unmatched} product rows unmatched and {ambiguous} ambiguous against the catalog")
    for (category, country), c in sorted(cells.items()):
        gated = (ctx.mature is True and minimp.value is not None and category != "(unknown)"
                 and all(c[s][0] >= minimp.value for s in ("screened", "unscreened")))
        chk.observe("Title cohort CTR (descriptive, not causal)", category=category, target_country=country,
                    window=f"{ctx.period_start}..{ctx.period_end}", min_impressions=minimp.value,
                    min_impressions_source=minimp.source, sample_gate_met=gated,
                    screened_impressions=c["screened"][0], unscreened_impressions=c["unscreened"][0],
                    screened_ctr=V.ratio(c["screened"][1], c["screened"][0]) if gated else None,
                    unscreened_ctr=V.ratio(c["unscreened"][1], c["unscreened"][0]) if gated else None)
    chk.observe("Title cohort inputs", rows=len(pd.rows), outside_window=outside, cells=len(cells))


def _disapprovals(ctx, chk, cat, cols) -> None:
    if not chk.runnable:
        return
    t = ctx.table(MD)
    dates = sorted({d for d in (V.parse_date(r.get("snapshot_at")) for r in cat.values()) if d})
    snap = dates[-1] if dates else ctx.snapshot
    if ctx.table(MP) is None:
        chk.partial("merchant_products absent: diagnostic coverage per product unknown", [f"{MP} (file)"])
    md_key = [c for c in KEY_ORDER if c in t.columns]
    idx, shared = _ref_index(ctx, cols)
    by_md: dict[tuple, list[tuple]] = {}
    for k in cat:
        by_md.setdefault(_proj(k, md_key), []).append(k)
    covered, delegated, counts = set(), 0, {"blocking": 0, "demoted": 0, "notice": 0, "no_issue": 0}
    for r in sorted(t.rows, key=lambda r: (tuple(_s(r.get(c)) for c in md_key), _s(r.get("issue_code")))):
        proj = tuple(_s(r.get(c)) for c in md_key)
        covered.add(proj)
        code, attr = _low(r.get("issue_code")), _low(r.get("attribute")).replace(" ", "_")
        if not code or code in NO_ISSUE:
            counts["no_issue"] += 1
            continue
        if attr not in ("title", "structured_title") and not (not attr and "title" in code):
            delegated += 1
            continue
        obs = V.parse_date(r.get("observed_at"))
        current = None if obs is None or snap is None else obs >= snap
        intended = None
        matches = by_md.get(proj, [])
        if len(matches) == 1:
            ref, _ = _ref_row(idx, shared, matches[0])
            if ref is not None and _s(ref.get("intended_destinations")):
                intended = _low(r.get("destination")) in {
                    _low(x) for x in V.split_list(ref.get("intended_destinations"), (";", "|", ","))}
        ent = {**_ent(_key(r)), "issue_code": r.get("issue_code"), "attribute": attr or "title"}
        ev = {"eligibility_status": r.get("eligibility_status"), "platform_severity": r.get("platform_severity"),
              "issue_text": r.get("issue_text"), "observed_at": r.get("observed_at"),
              "first_seen_at": r.get("first_seen_at"), "feed_snapshot": snap, "current": current,
              "intended_destination": intended, "source_reference": r.get("source_reference"),
              "effective_title": _title(cat[matches[0]], cols)[0] if len(matches) == 1 else None}
        status = {_low(r.get("eligibility_status")), _low(r.get("platform_severity"))}
        if status & BLOCKING:
            counts["blocking"] += 1
            base = "Warning" if current else "Info"
            prov = chk.finding("title_disapproval", base, ent,
                               f"Offer {ent.get('offer_id')} ({ent.get('target_country')}/{ent.get('destination')}) "
                               f"is {r.get('eligibility_status') or r.get('platform_severity')} for its title "
                               f"({r.get('issue_code')})", evidence=ev,
                               recommendation="Ask the feed owner for a fact-based title fix, then re-check the "
                                              "processed feed and diagnostics.",
                               uncertainty="Materiality needs business evidence." +
                                           ("" if current else " Diagnostic is not current at the feed snapshot."))
            chk.review("title_disapproval", ent,
                       "Does this title disapproval block delivery of a materially important product in an "
                       "intended destination?", evidence=ev,
                       outcomes={"material_intended_delivery_blocked": {"severity": "Critical", "recommendation":
                                 "Prioritize the title fix; cite the materiality evidence."},
                                 "not_material": {"severity": base, "recommendation": "Fix in normal feed hygiene."},
                                 "uncertain": {"severity": base, "recommendation": "Ask for product importance."}},
                       guidance="Critical needs a current diagnostic, an intended destination and "
                                "proposal.evidence_ref to business-importance evidence.", provisional=prov)
        elif status & DEMOTED and current:
            counts["demoted"] += 1
            chk.finding("title_diagnostic_issue", "Warning", ent,
                        f"Offer {ent.get('offer_id')} is demoted for its title ({r.get('issue_code')})", evidence=ev,
                        recommendation="Ask the feed owner for a fact-based title correction.",
                        uncertainty="Demotion limits but does not block delivery.")
        else:
            counts["notice"] += 1
            chk.finding("title_diagnostic_notice", "Info", ent,
                        f"Offer {ent.get('offer_id')} has a non-blocking title notice ({r.get('issue_code')})",
                        evidence=ev, recommendation="Optional title revision based on catalog facts.",
                        uncertainty="Non-blocking or non-current platform notice.")
    lacking = {_proj(k, md_key) for k in cat} - covered
    if lacking:
        chk.partial(f"{len(lacking)} catalog products have no diagnostics row; absence of issue rows is not approval")
    chk.observe("Title diagnostics screened", rows=len(t.rows), **counts, non_title_issues_delegated_to_083=delegated,
                products_without_diagnostics=len(lacking), feed_snapshot=snap)


# ---------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs evidence_ref/current/intended; Warning corrections need a
    fact-referenced 1–150 character proposed title that keeps the variant identity."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    prop = decision.get("proposal") or {}
    problems = []
    if spec.get("severity") == "Critical":
        if not _s(prop.get("evidence_ref")):
            problems.append("Critical needs proposal.evidence_ref pointing at supplied business-importance evidence")
        if item.evidence.get("current") is not True:
            problems.append("diagnostic is not current at the Merchant snapshot; Critical not allowed")
        if item.evidence.get("intended_destination") is False:
            problems.append("catalog reference lists this destination as not intended; Critical not allowed")
        return problems
    if spec.get("severity") != "Warning" or item.condition_key not in PROPOSAL_KEYS:
        return problems
    title = _s(prop.get("proposed_title"))
    if not 1 <= len(title) <= TITLE_MAX:
        problems.append(f"proposal.proposed_title must be 1–{TITLE_MAX} characters")
    if not _s(prop.get("fact_reference")):
        problems.append("proposal.fact_reference must cite the supporting product facts")
    for v in item.evidence.get("sibling_variant_values") or []:
        if title and _contains(title, v):
            problems.append(f"proposed title names sibling variant value '{v}'")
    for term in _terms(ctx) or []:
        if title and _contains(title, term):
            problems.append(f"proposed title contains promotional term '{term}'")
    if prop.get("ai_generated") is True and (_s(prop.get("attribute")) != "structured_title"
                                             or _s(prop.get("digital_source_type")) != AI_SOURCE_TYPE):
        problems.append(f"AI-generated titles go to structured_title with digital_source_type {AI_SOURCE_TYPE}")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
