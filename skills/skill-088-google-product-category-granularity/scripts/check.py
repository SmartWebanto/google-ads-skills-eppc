"""check.py — skill-088 deterministic Google product category accuracy.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-088-google-product-category-granularity/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-083-product-feed-attribute-completeness — owns missing/category-specific attribute findings
         skills/skill-085-custom-label-strategy-segmentation — owns merchant label design
rules:   Catalog denominator = distinct product keys (merchant_id, channel, content_language, feed_label, offer_id,
         target_country) of external/merchant_products; destination rows collapse into one product. A category cell
         that differs across destination rows of one key is ambiguous → excluded and counted, never picked.
         Category columns: submitted_google_product_category / effective_google_product_category (no alternatives).
         Numeric value joins google_taxonomy.category_id; text joins full_path lower-cased with whitespace and ' > '
         spacing normalized, in the product's content_language primary subtag. Taxonomy without that language, or
         without any language column, cannot prove a text path invalid → 'undecidable', never a finding.
         Empty submitted = automatic categorization (GPC optional) → never a finding. Empty effective = unknown.
         Depth distribution is descriptive only: never a finding, never recommend L4+ or automatic overrides.
         Product function, specificity, variant equivalence and materiality are ai_review; the script never judges them.
         invalid_current_mapping Warning only when the table_manifest certifies google_taxonomy complete (not truncated);
         otherwise partial + observation. It asks for platform-translation review, never declares invalid delivery.
         Category diagnostic = attribute google_product_category (case/space/hyphen-insensitive) or issue_code containing
         'category'; blocking = eligibility_status disapproved|not_eligible|excluded. Other diagnostics → skill-083.
         Critical only via requirement_trace 'material_blockage' with proposal.evidence_ref.
         Category proposals (wrong_function, more_specific_available, wrong_assignment) need proposal.category_id in the
         taxonomy, proposal.override_purpose in _PURPOSES and proposal.evidence_reference; function_accuracy proposals
         must differ from the current category; more_specific_available must be a strict descendant of it.
         product_reference joins on offer_id + target_country; duplicate rows with different product_function →
         ambiguous, excluded. Optional product_reference.intended_destinations is passed to review evidence only.
         custom/product_daily is historical exposure (never savings): rows deduped on campaign_id+offer_id+
         target_country+date, filtered to the account period, joined on offer_id (+target_country when present).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
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

SKILL = "skill-088-google-product-category-granularity"
VERSION = "1.0.0"

MP = "external/merchant_products"
TAX = "external/google_taxonomy"
REF = "external/product_reference"
DIAG = "external/merchant_diagnostics"
USE = "external/category_usage"
DAILY = "custom/product_daily"
KEY_COLS = ["merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country"]
SUB = "submitted_google_product_category"
EFF = "effective_google_product_category"
TAX_COLS = ["category_id", "full_path"]
REF_COLS = ["offer_id", "target_country", "product_function", "evidence_reference"]
DIAG_COLS = ["offer_id", "target_country", "destination", "issue_code", "attribute", "eligibility_status"]
USE_COLS = ["usage_id", "category_id"]
_BLOCKING = {"disapproved", "not_eligible", "excluded"}
_PURPOSES = ("correct_inaccurate_category", "more_specific_accurate_category",
             "category_specific_requirement", "policy_restricted_category")
_CAP = 25
_KEY_FORMAT = "merchant_id|channel|content_language|feed_label|offer_id|target_country"
_TITLES = {
    "category_inventory": "Catalog category inventory and taxonomy join",
    "override_applicability": "Automatic vs manual category assignment",
    "function_accuracy": "Main-function category accuracy and specificity",
    "taxonomy_validity": "Invalid or obsolete category mappings",
    "variant_consistency": "Category consistency within item groups",
    "requirement_trace": "Category-dependent diagnostics and listing usage",
}


# ---------------------------------------------------------------- taxonomy
def _norm_path(v) -> str:
    return " > ".join(" ".join(p.lower().split()) for p in str(v or "").split(">") if p.strip())


def _lang(v) -> str:
    return str(v or "").strip().lower().replace("_", "-").split("-")[0]


def _tax_id(v) -> str | None:
    s = str(v if v is not None else "").strip()
    if not s or s.lower() in V.MISSING_TOKENS:
        return None
    return str(int(s)) if s.isdigit() else s


class _Taxonomy:
    """Current Google taxonomy index. Rules: first row per category_id (sorted) wins; parent from parent_id else path."""

    def __init__(self, table):
        self.table = table
        self.by_id: dict[str, dict] = {}
        self.by_path: dict[tuple[str, str], str] = {}
        self.langs: set[str] = set()
        self.bad_rows = 0
        rows = sorted(table.rows, key=lambda r: (str(r.get("category_id") or ""), str(r.get("language") or ""),
                                                 str(r.get("full_path") or "")))
        for r in rows:
            cid, norm = _tax_id(r.get("category_id")), _norm_path(r.get("full_path"))
            if cid is None or not norm:
                self.bad_rows += 1
                continue
            lang = _lang(r.get("language"))
            if lang:
                self.langs.add(lang)
            self.by_path.setdefault((lang, norm), cid)
            if cid not in self.by_id:
                self.by_id[cid] = {"path": r.get("full_path"), "segs": tuple(norm.split(" > ")), "language": lang,
                                   "parent": _tax_id(r.get("parent_id"))}
        self.children: dict[str, list[str]] = {}
        for cid in sorted(self.by_id):
            node = self.by_id[cid]
            if node["parent"] is None and len(node["segs"]) > 1:
                node["parent"] = self.by_path.get((node["language"], " > ".join(node["segs"][:-1])))
            if node["parent"]:
                self.children.setdefault(node["parent"], []).append(cid)

    @property
    def complete(self) -> bool:
        return self.table.complete is True and not self.table.truncated

    def provenance(self) -> dict:
        def distinct(col):
            return sorted({str(r.get(col)) for r in self.table.rows if r.get(col) is not None})[:5]
        return {"file": self.table.filename, "categories": len(self.by_id), "languages": sorted(self.langs),
                "source_url": distinct("source_url"), "fetched_at": distinct("fetched_at"),
                "published_version": distinct("published_version"), "content_hash": distinct("content_hash"),
                "manifest_complete": self.complete}

    def resolve(self, value, content_language=None) -> tuple[str, str | None]:
        """Return (empty|resolved|unresolved|undecidable, category_id)."""
        s = str(value if value is not None else "").strip()
        if not s or s.lower() in V.MISSING_TOKENS:
            return "empty", None
        if s.isdigit():
            cid = str(int(s))
            return ("resolved", cid) if cid in self.by_id else ("unresolved", None)
        norm = _norm_path(s)
        if not self.langs:
            cid = self.by_path.get(("", norm))
            return ("resolved", cid) if cid else ("undecidable", None)
        lang = _lang(content_language)
        if not lang or lang not in self.langs:
            return "undecidable", None
        cid = self.by_path.get((lang, norm))
        return ("resolved", cid) if cid else ("unresolved", None)

    def depth(self, cid) -> int | None:
        node = self.by_id.get(cid)
        return len(node["segs"]) if node else None

    def is_descendant(self, cid, ancestor) -> bool:
        seen, cur = set(), (self.by_id.get(cid) or {}).get("parent")
        while cur and cur not in seen:
            if cur == ancestor:
                return True
            seen.add(cur)
            cur = (self.by_id.get(cur) or {}).get("parent")
        return False

    def descendants(self, cid) -> list[str]:
        out, stack, seen = [], list(self.children.get(cid, [])), {cid}
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
            stack.extend(self.children.get(c, []))
        return sorted(out)


def _taxonomy_gaps(ctx) -> list[str]:
    t = ctx.table(TAX)
    return [f"{TAX} (file)"] if t is None else [f"{TAX}:{c}" for c in t.missing(TAX_COLS)]


def _taxonomy(ctx) -> _Taxonomy | None:
    return None if _taxonomy_gaps(ctx) else _Taxonomy(ctx.table(TAX))


# ---------------------------------------------------------------- products
def _products(ctx) -> tuple[dict, int]:
    """Collapse merchant rows to product keys. Rules: keep every distinct non-empty value per field."""
    prods: dict[tuple, dict] = {}
    bad = 0
    for r in ctx.rows(MP):
        if not str(r.get("offer_id") or "").strip():
            bad += 1
            continue
        key = tuple(str(r.get(c) or "").strip() for c in KEY_COLS)
        p = prods.setdefault(key, {"rows": 0, "destination": set(), SUB: set(), EFF: set(), "item_group_id": set(),
                                   "title": set(), "product_type": set()})
        p["rows"] += 1
        for c in ("destination", SUB, EFF, "item_group_id", "title", "product_type"):
            v = r.get(c)
            if v is not None and str(v).strip() and str(v).strip().lower() not in V.MISSING_TOKENS:
                p[c].add(str(v).strip())
    return prods, bad


def _one(p: dict, col: str) -> tuple[str | None, bool]:
    vals = p.get(col) or set()
    return (next(iter(vals)), False) if len(vals) == 1 else (None, len(vals) > 1)


def _kstr(key: tuple) -> str:
    return "|".join(key)


def _cap(items) -> list:
    return sorted(items)[:_CAP]


def _ambiguous_join(rows: list[dict], col: str) -> bool:
    return len({V.norm_text(r.get(col)) for r in rows if r.get(col) is not None}) > 1


# ---------------------------------------------------------------- exposure
def _exposure(ctx) -> tuple[dict | None, dict]:
    """Historical product exposure. Rules: exposure, never savings; dedupe grain; period filter when known."""
    t = ctx.table(DAILY)
    if t is None:
        return None, {"note": f"{DAILY} not supplied: no exposure prioritization"}
    miss = t.missing(["campaign_id", "offer_id", "date", "cost"])
    if miss:
        return None, {"note": "exposure unavailable, missing " + ", ".join(f"{DAILY}:{c}" for c in miss)}
    has_country = "target_country" in t.columns
    seen, out = set(), {}
    dup = outside = 0
    for r in t.rows:
        d = V.parse_date(r.get("date"))
        if ctx.period_start and ctx.period_end and (d is None or not ctx.period_start <= d <= ctx.period_end):
            outside += 1
            continue
        offer = str(r.get("offer_id") or "").strip()
        country = str(r.get("target_country") or "").strip() if has_country else None
        grain = (str(r.get("campaign_id") or ""), offer, country, d)
        if grain in seen:
            dup += 1
            continue
        seen.add(grain)
        e = out.setdefault((offer, country), {"cost": 0.0, "clicks": 0.0, "impressions": 0.0, "conversions": 0.0,
                                              "rows": 0, "unknown_cells": 0})
        e["rows"] += 1
        for m in ("cost", "clicks", "impressions", "conversions"):
            if m not in t.columns:
                continue
            v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
            if v is None:
                e["unknown_cells"] += 1
            else:
                e[m] += v
    meta = {"label": "historical exposure, not savings", "window": [ctx.period_start, ctx.period_end],
            "currency": ctx.currency, "mature": ctx.mature, "duplicates_skipped": dup,
            "rows_outside_window": outside, "country_split": has_country, "manifest_complete": t.complete}
    return out, meta


def _exposure_for(exp: dict | None, meta: dict, pairs) -> dict | None:
    if exp is None:
        return None
    tot = {"cost": 0.0, "clicks": 0.0, "impressions": 0.0, "conversions": 0.0, "rows": 0, "unknown_cells": 0}
    keys = sorted({(o, c if meta["country_split"] else None) for o, c in pairs}, key=str)
    for k in keys:
        for m, v in (exp.get(k) or {}).items():
            tot[m] += v
    return {**tot, "currency": meta["currency"], "window": meta["window"], "label": meta["label"],
            "matched_product_keys": sum(1 for k in keys if k in exp)}


# ---------------------------------------------------------------- run
def _skip_rest(ctx, ids, reason, missing):
    for cid in ids:
        ctx.check(cid, _TITLES[cid]).skip(reason, missing)


def run(ctx) -> None:
    """Six checks, one per recipe step. Rules: Warning invalid mapping only with a manifest-complete taxonomy; function accuracy is ai_review; Critical only via evidence_ref."""
    inv = ctx.check("category_inventory", _TITLES["category_inventory"], {MP: KEY_COLS})
    tax = _taxonomy(ctx)
    tax_gaps = _taxonomy_gaps(ctx)
    exp, exp_meta = _exposure(ctx)
    if not inv.runnable:
        _skip_rest(ctx, [c for c in _TITLES if c not in ("category_inventory", "requirement_trace")],
                   "complete Merchant Center product snapshot unavailable", inv.missing)
        _trace(ctx, {}, {}, tax, tax_gaps, exp, exp_meta, catalog_missing=inv.missing)
        return
    mp = ctx.table(MP)
    prods, bad = _products(ctx)
    derived = {}
    for key in sorted(prods):
        p = prods[key]
        d = {}
        for tag, col in (("sub", SUB), ("eff", EFF)):
            val, conflict = _one(p, col)
            status, cid = ("conflict", None) if conflict else (tax.resolve(val, key[2]) if tax else
                                                               (("empty", None) if val is None else ("unknown", None)))
            d[tag], d[tag + "_status"], d[tag + "_id"] = val, status, cid
        derived[key] = d
    _inventory(ctx, inv, mp, prods, derived, bad, tax, tax_gaps)
    _override(ctx, mp, prods, derived, tax)
    _function(ctx, prods, derived, tax, exp, exp_meta)
    _validity(ctx, mp, derived, tax)
    _variants(ctx, prods, derived, tax)
    _trace(ctx, prods, derived, tax, tax_gaps, exp, exp_meta)


def _inventory(ctx, inv, mp, prods, derived, bad, tax, tax_gaps) -> None:
    if bad:
        inv.partial(f"{bad} merchant_products rows without offer_id excluded from the catalog denominator")
    missing_cats = [f"{MP}:{c}" for c in (SUB, EFF) if c not in mp.columns]
    if missing_cats:
        inv.partial("category column(s) absent: those assignments are unknown", missing_cats)
    if tax is None:
        inv.partial("taxonomy unavailable: category IDs/paths not joined, depth unknown", tax_gaps)
    elif not any(tax.provenance()[k] for k in ("published_version", "content_hash")):
        inv.partial("taxonomy version/hash not supplied: taxonomy version unknown",
                    [f"{TAX}:published_version|content_hash"])
    counts = {tag: {} for tag in ("sub", "eff")}
    depth = {"sub": {}, "eff": {}}
    differs = same = undetermined = 0
    for key in sorted(derived):
        d = derived[key]
        for tag in ("sub", "eff"):
            counts[tag][d[tag + "_status"]] = counts[tag].get(d[tag + "_status"], 0) + 1
            if tax and d[tag + "_id"]:
                dep = str(tax.depth(d[tag + "_id"]))
                depth[tag][dep] = depth[tag].get(dep, 0) + 1
        if d["sub"] is None or d["eff"] is None:
            continue
        if d["sub_id"] and d["eff_id"]:
            same, differs = (same + 1, differs) if d["sub_id"] == d["eff_id"] else (same, differs + 1)
        elif not tax and _norm_path(d["sub"]) == _norm_path(d["eff"]):
            same += 1
        else:
            undetermined += 1
    eff_unknown = counts["eff"].get("empty", 0)
    if EFF in mp.columns and eff_unknown:
        inv.partial(f"{eff_unknown} products with empty effective category (unknown, not absent)")
    inv.observe("Catalog category inventory", products=len(prods), merchant_rows=sum(p["rows"] for p in prods.values()),
                destination_rows_collapsed=sum(p["rows"] - 1 for p in prods.values()),
                submitted_status=counts["sub"], effective_status=counts["eff"],
                submitted_equals_effective=same, submitted_differs_effective=differs,
                submitted_vs_effective_undetermined=undetermined, product_key_format=_KEY_FORMAT,
                manifest_complete=mp.complete)
    if tax:
        inv.observe("Taxonomy source and depth distribution (descriptive only, not a quality score)",
                    taxonomy=tax.provenance(), effective_depth_distribution=depth["eff"],
                    submitted_depth_distribution=depth["sub"], taxonomy_rows_unusable=tax.bad_rows)


def _override(ctx, mp, prods, derived, tax) -> None:
    chk = ctx.check("override_applicability", _TITLES["override_applicability"], {MP: KEY_COLS + [SUB]})
    if not chk.runnable:
        return
    auto = manual = conflict = manual_same = manual_diff = manual_eff_unknown = 0
    for key in sorted(derived):
        d = derived[key]
        if d["sub_status"] == "conflict":
            conflict += 1
        elif d["sub"] is None:
            auto += 1
        else:
            manual += 1
            if d["eff"] is None:
                manual_eff_unknown += 1
            elif d["sub_id"] and d["eff_id"]:
                manual_same += d["sub_id"] == d["eff_id"]
                manual_diff += d["sub_id"] != d["eff_id"]
    if conflict:
        chk.partial(f"{conflict} products with conflicting submitted category across destination rows")
    chk.observe("Category assignment basis (GPC is optional; automatic categorization is not a defect)",
                products=len(derived), automatic_submitted_empty=auto, manual_submitted=manual,
                manual_matches_effective=manual_same, manual_differs_effective=manual_diff,
                manual_effective_unknown=manual_eff_unknown, submitted_conflicts=conflict,
                supported_override_purposes=list(_PURPOSES),
                rule="Any proposed override must state proposal.override_purpose and proposal.evidence_reference")


def _function(ctx, prods, derived, tax, exp, exp_meta) -> None:
    chk = ctx.check("function_accuracy", _TITLES["function_accuracy"],
                    {MP: KEY_COLS + [EFF], TAX: TAX_COLS, REF: REF_COLS})
    if not chk.runnable:
        return
    ref_t = ctx.table(REF)
    refs: dict[tuple, list[dict]] = {}
    for r in ref_t.rows:
        refs.setdefault((str(r.get("offer_id") or "").strip(), str(r.get("target_country") or "").strip()), []).append(r)
    excluded = {"effective_empty": 0, "effective_conflict": 0, "effective_not_in_taxonomy": 0,
                "no_product_reference": 0, "ambiguous_reference": 0, "function_unknown": 0}
    groups: dict[tuple, dict] = {}
    for key in sorted(derived):
        d = derived[key]
        st = d["eff_status"]
        if st != "resolved":
            excluded["effective_empty" if st == "empty" else "effective_conflict" if st == "conflict"
                     else "effective_not_in_taxonomy"] += 1
            continue
        rows = refs.get((key[4], key[5]), [])
        if not rows:
            excluded["no_product_reference"] += 1
            continue
        if _ambiguous_join(rows, "product_function"):
            excluded["ambiguous_reference"] += 1
            continue
        func = next((r.get("product_function") for r in rows if r.get("product_function")), None)
        if not V.norm_text(func) or V.norm_text(func) in V.MISSING_TOKENS:
            excluded["function_unknown"] += 1
            continue
        g = groups.setdefault((d["eff_id"], V.norm_text(func)), {"function": func, "keys": [], "refs": set(),
                                                                 "auto": 0, "manual": 0, "titles": set(),
                                                                 "product_types": set(), "pairs": set()})
        g["keys"].append(_kstr(key))
        g["pairs"].add((key[4], key[5]))
        g["refs"] |= {str(r.get("evidence_reference")) for r in rows if r.get("evidence_reference")}
        g["auto" if d["sub"] is None else "manual"] += 1
        g["titles"] |= prods[key]["title"]
        g["product_types"] |= prods[key]["product_type"]
    reasons = {k: v for k, v in excluded.items() if v}
    if reasons:
        chk.partial("products not judgeable for function accuracy: " + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    for (cid, fnorm), g in sorted(groups.items()):
        node = tax.by_id[cid]
        kids = tax.children.get(cid, [])
        evidence = {
            "current_category_id": cid, "current_path": node["path"], "current_depth": tax.depth(cid),
            "product_function": g["function"], "product_count": len(g["keys"]), "product_keys": _cap(g["keys"]),
            "product_key_format": _KEY_FORMAT, "function_evidence_references": _cap(g["refs"]),
            "automatic_assignments": g["auto"], "manual_assignments": g["manual"],
            "sample_titles": sorted(g["titles"])[:10], "sample_product_types": sorted(g["product_types"])[:10],
            "direct_children": [{"category_id": k, "path": tax.by_id[k]["path"]} for k in sorted(kids)[:50]],
            "descendant_count": len(tax.descendants(cid)),
            "taxonomy": {k: v for k, v in tax.provenance().items() if k != "languages"},
            "exposure": _exposure_for(exp, exp_meta, g["pairs"]),
        }
        entity = {"effective_category_id": cid, "product_function": fnorm}
        chk.review("category_function_fit", entity,
                   f"Does category {cid} '{node['path']}' accurately describe the main function "
                   f"'{g['function']}' of these {len(g['keys'])} products?",
                   evidence=evidence,
                   outcomes={
                       "wrong_function": {"severity": "Warning", "recommendation":
                                          "Request a feed override to the source-supported category (proposal.category_id, "
                                          "override_purpose, evidence_reference); category-specific attributes → skill-083."},
                       "more_specific_available": {"severity": "Info", "recommendation":
                                                   "Optional: a more specific accurate descendant exists; submit it only if "
                                                   "an override purpose applies. Depth is not a quality target."},
                       "accurate": {"severity": None, "recommendation": "Keep; accurate (automatic) assignment needs no override."},
                       "uncertain": {"severity": "Info", "recommendation":
                                     "Request verified product-function evidence; consider merchant product_type "
                                     "rather than fabricating a category."},
                   },
                   guidance="Judge the MAIN function from product_reference evidence (bundles by main item; cite "
                            "category-specific exceptions). Choose the most specific ACCURATE category, never a deeper "
                            "branch of an unrelated category. No category fits or weak evidence → uncertain.")
    chk.observe("Category/function pairs queued for review", pairs=len(groups),
                products_judgeable=sum(len(g["keys"]) for g in groups.values()), excluded=excluded)


def _validity(ctx, mp, derived, tax) -> None:
    chk = ctx.check("taxonomy_validity", _TITLES["taxonomy_validity"], {MP: KEY_COLS, TAX: TAX_COLS})
    if not chk.runnable:
        return
    cols = [(tag, col) for tag, col in (("sub", SUB), ("eff", EFF)) if col in mp.columns]
    if not cols:
        chk.skip("no category column to validate", [f"{MP}:{SUB}", f"{MP}:{EFF}"])
        return
    if len(cols) == 1:
        chk.partial("one category column absent", [f"{MP}:{c}" for c in (SUB, EFF) if c not in mp.columns])
    unresolved: dict[tuple, list[str]] = {}
    undecidable = 0
    for key in sorted(derived):
        d = derived[key]
        for tag, col in cols:
            if d[tag + "_status"] == "unresolved":
                unresolved.setdefault((col, d[tag].strip()), []).append(_kstr(key))
            elif d[tag + "_status"] == "undecidable":
                undecidable += 1
    if undecidable:
        chk.partial(f"{undecidable} text category values in a language absent from the supplied taxonomy: validity undecidable")
    prov = tax.provenance()
    if not tax.complete:
        chk.partial("taxonomy completeness not certified by table_manifest: unresolved values are observations, not findings")
        chk.observe("Category values not found in the supplied taxonomy (Info, taxonomy completeness unproven)",
                    values=[{"field": c, "category_value": v, "products": len(k), "product_keys": _cap(k)}
                            for (c, v), k in sorted(unresolved.items())], taxonomy=prov)
    else:
        for (col, val), keys in sorted(unresolved.items()):
            chk.finding("invalid_current_mapping", "Warning", {"field": col, "category_value": val},
                        f"{col} value '{val}' is not in the current taxonomy for {len(keys)} product(s)",
                        evidence={"products": len(keys), "product_keys": _cap(keys), "product_key_format": _KEY_FORMAT,
                                  "taxonomy": prov},
                        calculation={"numerator": len(keys), "denominator": len(derived),
                                     "basis": "products whose single category value has no category_id/full_path match"},
                        recommendation="Review the platform translation of this older/obsolete value before declaring "
                                       "invalid delivery; if no category describes the product keep the uncertainty and "
                                       "rely on product_type rather than fabricating a category.",
                        uncertainty="Google may translate older taxonomy IDs; delivery impact is not evidenced here.")
    chk.observe("Taxonomy validity screen", distinct_unresolved_values=len(unresolved),
                products_with_unresolved=len({k for ks in unresolved.values() for k in ks}), undecidable_values=undecidable,
                taxonomy_complete=tax.complete)


def _variants(ctx, prods, derived, tax) -> None:
    chk = ctx.check("variant_consistency", _TITLES["variant_consistency"], {MP: KEY_COLS + ["item_group_id", EFF]})
    if not chk.runnable:
        return
    fn_by = {}
    if ctx.table(REF) is not None and not ctx.table(REF).missing(["offer_id", "target_country", "product_function"]):
        for r in ctx.rows(REF):
            fn_by.setdefault((str(r.get("offer_id") or "").strip(), str(r.get("target_country") or "").strip()),
                             set()).add(str(r.get("product_function") or ""))
    groups: dict[tuple, list] = {}
    group_conflict = 0
    for key in sorted(prods):
        gid, conflict = _one(prods[key], "item_group_id")
        if conflict:
            group_conflict += 1
        if gid:
            groups.setdefault((key[0], key[5], gid), []).append(key)
    compared = divergent = incomparable = 0
    for gkey, members in sorted(groups.items()):
        by_cat: dict[str, list] = {}
        unknown = []
        for key in members:
            d = derived[key]
            if d["eff_id"]:
                canon = d["eff_id"]
            elif d["eff_status"] in ("unresolved", "undecidable", "unknown") and d["eff"]:
                canon = ("id:" + str(int(d["eff"]))) if d["eff"].isdigit() else ("path:" + _norm_path(d["eff"]))
            else:
                unknown.append(_kstr(key))
                continue
            by_cat.setdefault(canon, []).append(key)
        if sum(len(v) for v in by_cat.values()) < 2:
            continue
        kinds = {c.split(":", 1)[0] for c in by_cat if ":" in c}
        if "path" in kinds and (len(kinds) > 1 or any(":" not in c for c in by_cat)):
            incomparable += 1
            continue
        compared += 1
        if len(by_cat) < 2:
            continue
        divergent += 1
        entity = {"merchant_id": gkey[0], "target_country": gkey[1], "item_group_id": gkey[2]}
        cats = []
        for canon, keys in sorted(by_cat.items()):
            node = tax.by_id.get(canon) if tax else None
            cats.append({"category": canon, "path": node["path"] if node else derived[keys[0]]["eff"],
                         "products": len(keys), "product_keys": _cap(_kstr(k) for k in keys),
                         "product_functions": sorted({f for k in keys for f in fn_by.get((k[4], k[5]), set()) if f})})
        ev = {"categories": cats, "members": len(members), "members_effective_unknown": _cap(unknown),
              "product_key_format": _KEY_FORMAT,
              "sample_titles": sorted({t for k in members for t in prods[k]["title"]})[:10]}
        prov = chk.finding("variant_category_divergence", "Info", entity,
                           f"Item group {gkey[2]} ({gkey[1]}) spans {len(by_cat)} effective categories",
                           evidence=ev, calculation={"distinct_categories": len(by_cat), "members_compared":
                                                     sum(len(v) for v in by_cat.values())},
                           recommendation="Confirm whether variants share the same main function before aligning categories.",
                           uncertainty="An inconsistent-looking path alone is not an error; variants may differ in function.")
        chk.review("variant_category_divergence", entity,
                   f"Do the variants of item group {gkey[2]} share one main function, so that one category is wrong?",
                   evidence=ev, provisional=prov,
                   outcomes={
                       "wrong_assignment": {"severity": "Warning", "recommendation":
                                            "Request the source-supported category for the misassigned variants "
                                            "(proposal.category_id, override_purpose, evidence_reference)."},
                       "legitimately_different": {"severity": None, "recommendation": "Keep; variants differ in function."},
                       "uncertain": {"severity": "Info", "recommendation": "Request variant-level product-function evidence."},
                   },
                   guidance="Compare only genuinely equivalent functions and variant contexts; product_reference "
                            "functions and cited evidence decide, not path similarity.")
    if group_conflict:
        chk.partial(f"{group_conflict} products with conflicting item_group_id across destination rows")
    if incomparable:
        chk.partial(f"{incomparable} item groups mix unresolved text paths and IDs: not comparable without taxonomy")
    chk.observe("Item-group category consistency", item_groups=len(groups), groups_compared=compared,
                groups_divergent=divergent)


def _manual_gaps(ctx, key, cols) -> list[str]:
    t = ctx.table(key)
    return [f"{key} (file)"] if t is None else [f"{key}:{c}" for c in t.missing(cols)]


def _norm_token(v) -> str:
    return V.norm_text(v).replace("-", "_").replace(" ", "_")


def _trace(ctx, prods, derived, tax, tax_gaps, exp, exp_meta, catalog_missing=()) -> None:
    chk = ctx.check("requirement_trace", _TITLES["requirement_trace"])
    dgaps, ugaps = _manual_gaps(ctx, DIAG, DIAG_COLS), _manual_gaps(ctx, USE, USE_COLS)
    if dgaps and ugaps:
        chk.skip("no diagnostics or category usage evidence to trace", dgaps + ugaps)
        return
    if catalog_missing:
        chk.partial("product snapshot unavailable: issues not joined to catalog categories or usage scopes",
                    list(catalog_missing))
    for key, gaps in ((DIAG, dgaps), (USE, ugaps)):
        if gaps:
            chk.partial(f"{key} unavailable: that trace not run", gaps)
            continue
        t = ctx.table(key)
        if t.complete is not True or t.truncated:
            chk.partial(f"{t.filename}: manifest does not certify complete coverage; absence not provable")
    by_offer: dict[tuple, list] = {}
    for key in sorted(prods):
        by_offer.setdefault((key[4], key[5]), []).append(key)
    if not dgaps:
        _trace_diagnostics(ctx, chk, by_offer, derived, tax, exp, exp_meta)
    if not ugaps:
        _trace_usage(ctx, chk, derived, tax, tax_gaps)
    if exp is None:
        chk.observe("Exposure prioritization unavailable", note=exp_meta.get("note"))


def _trace_diagnostics(ctx, chk, by_offer, derived, tax, exp, exp_meta) -> None:
    ref_t = ctx.table(REF)
    intended = {}
    if ref_t is not None and "intended_destinations" in ref_t.columns:
        for r in ref_t.rows:
            intended[(str(r.get("offer_id") or "").strip(), str(r.get("target_country") or "").strip())] = \
                V.split_list(r.get("intended_destinations"))
    seen = set()
    delegated = nonblocking = blocking = dup = 0
    for r in sorted(ctx.rows(DIAG), key=lambda r: tuple(str(r.get(c) or "") for c in ["merchant_id"] + DIAG_COLS)):
        is_cat = _norm_token(r.get("attribute")) == "google_product_category" or "category" in V.norm_text(r.get("issue_code"))
        if not is_cat:
            delegated += 1
            continue
        if _norm_token(r.get("eligibility_status")) not in _BLOCKING:
            nonblocking += 1
            continue
        offer, country = str(r.get("offer_id") or "").strip(), str(r.get("target_country") or "").strip()
        entity = {"offer_id": offer, "target_country": country, "destination": r.get("destination"),
                  "issue_code": r.get("issue_code")}
        if r.get("merchant_id"):
            entity["merchant_id"] = str(r.get("merchant_id"))
        ident = tuple(sorted(entity.items()))
        if ident in seen:
            dup += 1
            continue
        seen.add(ident)
        blocking += 1
        keys = by_offer.get((offer, country), [])
        cats = sorted({(derived[k]["eff"] or "", derived[k]["eff_id"] or "") for k in keys})
        ev = {"attribute": r.get("attribute"), "eligibility_status": r.get("eligibility_status"),
              "platform_severity": r.get("platform_severity"), "issue_text": r.get("issue_text"),
              "source_reference": r.get("source_reference"), "observed_at": r.get("observed_at"),
              "product_keys": _cap(_kstr(k) for k in keys), "product_in_snapshot": bool(keys),
              "effective_categories": [{"value": v or None, "category_id": i or None,
                                        "path": tax.by_id[i]["path"] if tax and i in tax.by_id else None} for v, i in cats],
              "intended_destinations": intended.get((offer, country)),
              "exposure": _exposure_for(exp, exp_meta, [(offer, country)])}
        chk.finding("category_diagnostic_blockage", "Warning", entity,
                    f"Offer {offer} ({country}) is {r.get('eligibility_status')} for {r.get('destination')} with "
                    f"category issue {r.get('issue_code')}",
                    evidence=ev, calculation={"basis": "platform diagnostic row; exposure is historical, not savings"},
                    recommendation="Review the category assignment behind this platform issue and request the "
                                   "source-supported correction; missing category-specific attributes → skill-083.",
                    uncertainty="The diagnostic evidences a category-related issue, not that the category is wrong or "
                                "that the blockage is material.")
        chk.review("category_diagnostic_blockage", entity,
                   f"Does this category issue block MATERIAL intended delivery (or an evidenced safety failure) for "
                   f"offer {offer} in {country}?",
                   evidence=ev,
                   outcomes={
                       "material_blockage": {"severity": "Critical", "recommendation":
                                             "Prioritize the category correction; cite the delivery evidence."},
                       "not_material": {"severity": None, "recommendation": "Keep as Warning."},
                       "uncertain": {"severity": None, "recommendation":
                                     "Keep as Warning; request intended-destination and business-priority evidence."},
                   },
                   guidance="Material needs cited evidence that the destination/market is intended and the blockage "
                            "affects delivery (proposal.evidence_ref). Do not infer CTR or revenue uplift.")
    if dup:
        chk.partial(f"{dup} duplicate diagnostic rows ignored")
    chk.observe("Diagnostics traced to category", blocking_category_issues=blocking,
                non_blocking_category_issues=nonblocking, other_attribute_issues_delegated_to_skill_083=delegated)


def _trace_usage(ctx, chk, derived, tax, tax_gaps) -> None:
    if tax is None:
        chk.partial("category_usage IDs not validated: taxonomy unavailable", tax_gaps)
    elif not tax.complete:
        chk.partial("category_usage validity is observation only: taxonomy completeness not certified")
    scopes, unresolved_obs, overrides = [], [], 0
    for r in sorted(ctx.rows(USE), key=lambda r: (str(r.get("usage_id") or ""), str(r.get("category_id") or ""))):
        uid, raw = str(r.get("usage_id") or ""), r.get("category_id")
        if r.get("override_reason"):
            overrides += 1
        if tax is None:
            continue
        status, cid = tax.resolve(raw)
        entity = {"usage_id": uid, "campaign_id": r.get("campaign_id"), "category_id": raw}
        if status == "resolved":
            n = sum(1 for d in derived.values() if d["eff_id"] and (d["eff_id"] == cid or tax.is_descendant(d["eff_id"], cid)))
            scopes.append({"usage_id": uid, "category_id": cid, "products_in_scope": n})
            continue
        if status != "unresolved":
            unresolved_obs.append({**entity, "status": status})
            continue
        if not tax.complete:
            unresolved_obs.append({**entity, "status": status})
            continue
        chk.finding("invalid_current_mapping", "Warning", entity,
                    f"Category usage {uid} references category '{raw}', absent from the current taxonomy",
                    evidence={k: r.get(k) for k in ("market", "destination", "listing_rule_reference", "override_reason",
                                                    "source_reference", "snapshot_at")} | {"taxonomy": tax.provenance()},
                    calculation={"basis": "category_id not found in google_taxonomy.category_id/full_path"},
                    recommendation="Review the platform translation of this category in the listing rule or requirement "
                                   "before changing it; label-based selection design → skill-085.",
                    uncertainty="The platform may translate older IDs; selection impact is not evidenced here.")
    chk.observe("Category usage traced to catalog", usage_rows=len(ctx.rows(USE)), usage_scopes=scopes[:50],
                unvalidated_usage=unresolved_obs[:50], usage_rows_with_override_reason=overrides)


# ---------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Re-check AI proposals deterministically.

    Rules:   material_blockage needs proposal.evidence_ref. Category proposals need category_id in the taxonomy,
             override_purpose in _PURPOSES and evidence_reference; function proposals must differ from the current
             category; more_specific_available must be a strict descendant of the current category.
    """
    outcome = decision.get("outcome")
    prop = decision.get("proposal") or {}
    if item.check == "requirement_trace" and outcome == "material_blockage":
        return [] if str(prop.get("evidence_ref") or "").strip() else \
            ["material_blockage needs proposal.evidence_ref pointing at supplied delivery evidence"]
    if (item.check, outcome) not in (("function_accuracy", "wrong_function"),
                                     ("function_accuracy", "more_specific_available"),
                                     ("variant_consistency", "wrong_assignment")):
        return []
    problems = []
    tax = _taxonomy(ctx)
    cid = _tax_id(prop.get("category_id"))
    if tax is None:
        problems.append("taxonomy unavailable: proposed category cannot be validated")
    elif cid is None or cid not in tax.by_id:
        problems.append(f"proposal.category_id {prop.get('category_id')!r} not in the current taxonomy")
    current = (item.evidence or {}).get("current_category_id")
    if item.check == "function_accuracy" and cid is not None and cid == current:
        problems.append("proposed category equals the current category")
    if (outcome == "more_specific_available" and tax is not None and cid in tax.by_id and cid != current
            and not tax.is_descendant(cid, current)):
        problems.append(f"category {cid} is not a descendant of current category {current}")
    if prop.get("override_purpose") not in _PURPOSES:
        problems.append(f"proposal.override_purpose must be one of {list(_PURPOSES)}")
    if not str(prop.get("evidence_reference") or "").strip():
        problems.append("proposal.evidence_reference required (source evidence for the product function)")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
