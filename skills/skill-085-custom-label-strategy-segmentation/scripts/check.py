"""check.py — skill-085 deterministic custom label inventory, dictionary and listing-tree reconciliation.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-085-custom-label-strategy-segmentation/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #123 Build SPAGs from product IDs (Frederic Harnois, GitHub) — clean-room: the listing-tree
         resolver understands item-ID (offer_id) subdivisions so SPAG-built trees are audited like any tree;
         building SPAGs (an account mutation and a split-for-its-own-sake) is NOT integrated.
         skill-089 check.py carries the same private listing-tree resolver (keep semantics identical).
         index #115 Bulk Shopping Ad Group Creator (Google Ads Scripts solution) — clean-room: its "ad groups +
         product groups from a sheet" becomes the opt-in shopping_build_plan review; verify() proves the plan
         partitions the complete feed. REFUSED: creating ad groups/product groups, bids and statuses from a sheet
         (account mutation; bids have no approved inputs here). Owner 085 (not 010: its routing export lacks feed
         attributes; not 089: PMax asset groups, while #115 builds Standard Shopping ad groups).
rules:   Catalog denominator = distinct merchant_products keys (merchant_id, channel, content_language,
         feed_label, offer_id, target_country; absent key columns ignored); destination rows are deduplicated.
         Label meaning comes ONLY from external/label_strategy (label_slot 'custom_label_N' or 'N');
         names/prices never imply margin or season. >10 values is descriptive, never a finding.
         Listing trees: custom/listing_rules; group column asset_group_id else ad_group_id; inclusion column
         inclusion | inclusion_exclusion | included_excluded | status; level column dimension_level | level; root scope columns
         merchant_id, feed_label, country|target_country, channel, language filter the catalog when set.
         Children of a subdivision split its products by exact normalized value; other_case gets the rest;
         a product with an empty attribute falls to other_case. Unsupported dimensions (category, unknown)
         leave the branch UNRESOLVED (partial), never "all products".
         product_selection (optional) is the platform-resolved selection and overrides the local resolution
         for reconciliation; disagreements are reported as resolver coverage.
         Severity: Critical only via review + proposal.evidence_ref; Warning deterministic only for a
         product-level approved classification contradicting the feed in a slot with a current intended_use;
         undeclared meaning / expired values / label-driven exclusions are provisional Info + review.
         verify(): corrections must use current dictionary values; new segmentation proposals may only use
         an empty slot and need definitions, owner, cadence, control and decision reference; margin tiers need
         a label_strategy margin_basis.
         shopping_build_plan is OPT-IN (profile.shopping_build_plan_request {campaigns: {id: {priority}} | [id],
         scope: {feed key column: value}, routing: [{when: {dim: value}, campaign_id | priority}] first match
         wins, remainder_campaign_id}); otherwise not_applicable. Review only when the request is valid (campaigns
         exist as channel_type SHOPPING, routing dims/campaigns/priorities resolvable) AND the merchant_products
         manifest certifies completeness (exactly-once needs the full catalog); else partial, no review.
         Plan dims: item_id (offer_id), brand, product_type_lN (Nth ' > ' level), custom_label_0..4; a group key
         is an equality conjunction on normalized values. verify(): each in-scope offer in at most one keyed
         group, unmatched offers go to the explicit remainder ({campaign_id, ad_group} or {exclude: true});
         no empty or duplicate groups; key dims present in the feed and values present in scope; campaigns only
         from the request; routing rules and remainder_campaign_id respected per offer. Proposal only.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | #115 opt-in shopping_build_plan + verify
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

SKILL = "skill-085-custom-label-strategy-segmentation"
VERSION = "1.1.0"

PRODUCTS = "external/merchant_products"
STRATEGY = "external/label_strategy"
RULES = "custom/listing_rules"
SELECTION = "custom/product_selection"
DAILY = "custom/product_daily"
SLOTS = tuple(f"custom_label_{i}" for i in range(5))
KEY_COLS = ("merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country")
OFFER_EVIDENCE_CAP = 500
_PT_LEVEL = re.compile(r"product_type_l([1-9]\d*)")
PROPOSAL_FIELDS = ("slot", "definitions", "permitted_values", "owner", "refresh_cadence", "intended_control",
                   "decision_reference")
_INCLUDED = {"included", "include", "biddable", "positive", "true", "yes"}
_EXCLUDED = {"excluded", "exclude", "negative", "false", "no"}


# ---------------------------------------------------------------------------------------------- helpers
def _norm(v) -> str:
    return V.norm_text(v)


def _col(table, *names):
    return next((n for n in names if table is not None and n in table.columns), None)


def _products(ctx) -> tuple[dict, list[str]]:
    """Distinct products by key. Rules: conflicting label cells across destination rows → first sorted + note."""
    t = ctx.table(PRODUCTS)
    cols = [c for c in KEY_COLS if c in t.columns]
    out, notes = {}, []
    for r in sorted(t.rows, key=lambda r: tuple(str(r.get(c) or "") for c in cols + ["destination"])):
        key = tuple(str(r.get(c) or "") for c in cols)
        if key in out:
            if any(_norm(out[key].get(s)) != _norm(r.get(s)) for s in SLOTS if s in t.columns):
                notes.append(f"product {'/'.join(key)} has differing label cells across destination rows")
            continue
        out[key] = r
    return out, sorted(set(notes))


def _pkey(key: tuple) -> str:
    return "/".join(key)


def _slot(v) -> str | None:
    s = _norm(v).replace(" ", "_")
    m = re.fullmatch(r"(?:custom_label_?)?([0-4])", s)
    return f"custom_label_{m.group(1)}" if m else None


def _valid(row, day) -> bool | None:
    if day is None:
        return None
    a, b = V.parse_date(row.get("valid_from")), V.parse_date(row.get("valid_to"))
    return not ((a and a > day) or (b and b < day))


def _dictionary(ctx) -> dict:
    """(merchant_id, slot) -> {normalized value: [rows]}."""
    d: dict = {}
    for r in ctx.rows(STRATEGY):
        slot = _slot(r.get("label_slot"))
        if slot is None or r.get("allowed_value") is None:
            continue
        if "offer_id" in (ctx.table(STRATEGY).columns) and r.get("offer_id"):
            continue  # product-level classification rows are handled separately
        d.setdefault((str(r.get("merchant_id") or ""), slot), {}).setdefault(_norm(r.get("allowed_value")), []).append(r)
    return d


def _current_values(dictionary, merchant, slot, day) -> set:
    return {v for v, rows in (dictionary.get((merchant, slot)) or {}).items()
            if any(_valid(r, day) and r.get("approved_at") for r in rows)}


def _exposure(ctx, offer_ids: set) -> dict | None:
    t = ctx.table(DAILY)
    if t is None or t.missing(["offer_id", "cost"]):
        return None
    tot = {"cost": 0.0, "clicks": 0.0, "conversions": 0.0, "rows": 0}
    for r in t.rows:
        if str(r.get("offer_id")) in offer_ids:
            tot["rows"] += 1
            for m in ("cost", "clicks", "conversions"):
                v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
                tot[m] += v or 0
    tot["note"] = "delivered-product sample; historical exposure, not savings"
    return tot


# ---------------------------------------------------------------------------------------------- tree resolver
def _level(node, level_col) -> int | None:
    m = re.search(r"\d+", str(node.get(level_col) or "")) if level_col else None
    return int(m.group()) if m else None


def _attr(dimension: str, level: int | None, product: dict, columns) -> tuple[bool, str]:
    """(supported, normalized product value) for a listing dimension."""
    d = _norm(dimension).replace(" ", "_")
    m = re.fullmatch(r"custom_(?:label|attribute)_?([0-4])", d)
    slot = f"custom_label_{m.group(1)}" if m else None
    if d in ("custom_label", "custom_attribute") and level is not None and 0 <= level <= 4:
        slot = f"custom_label_{level}"
    if slot:
        return (slot in columns), _norm(product.get(slot))
    if d in ("item_id", "offer_id", "product_id", "id"):
        return ("offer_id" in columns), _norm(product.get("offer_id"))
    if d in ("brand", "condition", "channel"):
        return (d in columns), _norm(product.get(d))
    if d in ("product_type", "product_type_level") and level is not None and level >= 1:
        if "product_type" not in columns:
            return False, ""
        parts = [p.strip() for p in str(product.get("product_type") or "").split(">")]
        return True, _norm(parts[level - 1]) if len(parts) >= level else ""
    return False, ""


def resolve_trees(ctx, table_key: str) -> tuple[dict, list[str], dict]:
    """Resolve every group tree against the catalog.

    Rules:   returns ({(campaign_id, group_id): {"included", "excluded", "unresolved", "no_path": set(product keys),
             "nodes": {node_id: {"dimension", "value", "matched": set}}}}, notes, meta). Deterministic, sorted.
    """
    t = ctx.table(table_key)
    products, _ = _products(ctx)
    pcols = ctx.table(PRODUCTS).columns
    inc_col = _col(t, "inclusion", "inclusion_exclusion", "included_excluded", "status")
    lvl_col = _col(t, "dimension_level", "level")
    grp_cols = [c for c in ("asset_group_id", "ad_group_id") if c in t.columns]
    groups: dict = {}
    for r in t.rows:
        gid = next((str(r.get(c)) for c in grp_cols if r.get(c)), "")
        groups.setdefault((str(r.get("campaign_id")), gid), []).append(r)
    out, notes = {}, []
    for gkey in sorted(groups):
        nodes = {str(n.get("node_id")): n for n in groups[gkey]}
        kids: dict = {}
        roots = []
        for nid, n in sorted(nodes.items()):
            p = n.get("parent_node_id")
            (kids.setdefault(str(p), []) if p else roots).append(nid)
        res = {"included": set(), "excluded": set(), "unresolved": set(), "no_path": set(), "nodes": {}}
        out[gkey] = res
        if len(roots) != 1:
            notes.append(f"{gkey}: {len(roots)} root nodes; tree unresolved")
            res["unresolved"] = set(products)
            continue
        root = nodes[roots[0]]
        scope = set()
        for k, p in products.items():
            ok = True
            for rc, pc in (("merchant_id", "merchant_id"), ("feed_label", "feed_label"), ("country", "target_country"),
                           ("target_country", "target_country"), ("channel", "channel"), ("language", "content_language")):
                if rc in t.columns and root.get(rc) and pc in pcols and _norm(root.get(rc)) != _norm(p.get(pc)):
                    ok = False
            if ok:
                scope.add(k)
        stack = [(roots[0], scope)]
        while stack:
            nid, pset = stack.pop()
            node = nodes[nid]
            children = sorted(kids.get(nid, []))
            res["nodes"][nid] = {"dimension": node.get("dimension"), "value": node.get("value"),
                                 "other_case": V.boolean(node.get("other_case")), "matched": set(pset)}
            if not children:
                ntype = _norm(node.get("node_type") or node.get("unit_type"))
                flag = _norm(node.get(inc_col)) if inc_col else ""
                if "subdivision" in ntype:
                    res["unresolved"] |= pset
                    notes.append(f"{gkey}: subdivision {nid} has no exported children")
                elif flag in _INCLUDED:
                    res["included"] |= pset
                elif flag in _EXCLUDED:
                    res["excluded"] |= pset
                else:
                    res["unresolved"] |= pset
                    notes.append(f"{gkey}: unit {nid} inclusion status unknown")
                continue
            dims = {(_norm(nodes[c].get("dimension")), _level(nodes[c], lvl_col)) for c in children
                    if not V.boolean(nodes[c].get("other_case"))}
            if len(dims) > 1:
                res["unresolved"] |= pset
                notes.append(f"{gkey}: node {nid} children mix dimensions {sorted(map(str, dims))}")
                continue
            dim, lvl = next(iter(dims)) if dims else ("", None)
            remaining = set(pset)
            others = []
            for c in children:
                cn = nodes[c]
                if V.boolean(cn.get("other_case")) or cn.get("value") is None:
                    others.append(c)
                    continue
                matched = set()
                unsupported = False
                for k in sorted(remaining):
                    ok, val = _attr(dim, lvl, products[k], pcols)
                    if not ok:
                        unsupported = True
                        break
                    if val and val == _norm(cn.get("value")):
                        matched.add(k)
                if unsupported:
                    res["unresolved"] |= remaining
                    notes.append(f"{gkey}: dimension '{dim}' level {lvl} not resolvable from the feed")
                    remaining = set()
                    others = []
                    break
                remaining -= matched
                stack.append((c, matched))
            if len(others) > 1:
                res["unresolved"] |= remaining
                notes.append(f"{gkey}: node {nid} has {len(others)} other-case children")
            elif others:
                stack.append((others[0], remaining))
            else:
                res["no_path"] |= remaining
    return out, sorted(set(notes)), {"products": products}


# ---------------------------------------------------------------------------------------------- checks
def run(ctx) -> None:
    """Run catalog, custom-label dictionary, listing-tree resolution, segmentation and opt-in build-plan checks.

    Rules:   Label meaning only from external/label_strategy; names/prices never imply margin; > 10 values is not a
             finding. Unsupported listing dimensions leave branches UNRESOLVED (partial), never 'all products'. Warning
             only for a product-level approved classification contradicting the feed in a slot with current
             intended_use; undeclared/expired/exclusion issues → provisional Info + review; Critical only via review
             with proposal.evidence_ref. shopping_build_plan reviews exist only for a valid
             profile.shopping_build_plan_request over a manifest-complete feed (not_applicable when unset).
    """
    need_products = {PRODUCTS: ["merchant_id", "offer_id", "target_country", *SLOTS]}
    inv = ctx.check("label_inventory", "Label slot/value coverage over the complete feed", need_products)
    products, pnotes = (_products(ctx) if inv.runnable else ({}, []))
    for n in pnotes[:20]:
        inv.partial(n)
    if inv.runnable:
        total = len(products)
        for slot in SLOTS:
            vals: dict = {}
            for p in products.values():
                v = _norm(p.get(slot))
                if v:
                    vals[v] = vals.get(v, 0) + 1
            populated = sum(vals.values())
            inv.observe(f"{slot}: coverage over the catalog", slot=slot, catalog_products=total, populated=populated,
                        empty=total - populated, coverage=V.ratio(populated, total), distinct_values=len(vals),
                        more_than_ten_values=len(vals) > 10,
                        top_values=sorted(vals.items(), key=lambda kv: (-kv[1], kv[0]))[:20])

    day = ctx.snapshot or ctx.as_of
    dict_needs = {**need_products, STRATEGY: ["merchant_id", "label_slot", "allowed_value", "meaning", "valid_from",
                                              "valid_to", "approved_at"]}
    dct = ctx.check("dictionary_conformance", "Actual values vs approved label dictionary", dict_needs)
    dictionary = _dictionary(ctx) if dct.runnable else {}
    tree_ok = ctx.table(RULES) is not None and not ctx.table(RULES).missing(
        ["campaign_id", "node_id", "parent_node_id", "dimension", "value", "other_case"])
    trees, tnotes = (resolve_trees(ctx, RULES)[:2] if tree_ok and inv.runnable else ({}, []))
    used = _label_nodes(trees)
    if dct.runnable:
        _dictionary_check(ctx, dct, products, dictionary, used, day)

    pc = ctx.check("product_classification_conflicts", "Approved product-level classifications vs feed labels",
                   {**need_products, STRATEGY: ["merchant_id", "label_slot", "allowed_value", "offer_id",
                                                "valid_from", "valid_to", "approved_at"]})
    if pc.runnable:
        _classification_check(ctx, pc, products, dictionary, day)

    rule_needs = {**need_products, RULES: ["campaign_id", "node_id", "parent_node_id", "dimension", "value",
                                           "other_case"]}
    use = ctx.check("listing_label_use", "Resolve listing trees and trace label use", rule_needs)
    if use.runnable:
        t = ctx.table(RULES)
        if not _col(t, "inclusion", "inclusion_exclusion", "included_excluded", "status"):
            use.partial("no inclusion column", [f"{RULES}:inclusion"])
        if not any(c in t.columns for c in ("asset_group_id", "ad_group_id")):
            use.partial("no group column", [f"{RULES}:asset_group_id"])
        for n in tnotes:
            use.partial(n)
        for (slot, value), refs in sorted(used.items()):
            use.observe(f"{slot}='{value}' used for product selection", slot=slot, value=value,
                        nodes=[{"campaign_id": c, "group_id": g, "node_id": n, "matched_products": m}
                               for c, g, n, m in refs])
        intended = {}
        for (m, slot), vals in sorted(dictionary.items()):
            uses = sorted({str(r.get("intended_use")) for rows in vals.values() for r in rows if r.get("intended_use")})
            intended[f"{m}:{slot}"] = uses
        use.observe("Label use by channel", selection_slots=sorted({s for s, _ in used}),
                    dictionary_intended_uses=intended,
                    note="absent listing split does not prove a label unused for reporting or bidding")
        for gkey, res in sorted(trees.items()):
            use.observe(f"Group {gkey[0]}/{gkey[1]} resolved selection", campaign_id=gkey[0], group_id=gkey[1],
                        included=len(res["included"]), excluded=len(res["excluded"]),
                        unresolved=len(res["unresolved"]), no_path=len(res["no_path"]))
    rec = ctx.check("selection_reconciliation", "Planned vs resolved inclusion driven by labels", rule_needs)
    if rec.runnable:
        _reconcile(ctx, rec, trees, products, dictionary, day)
    else:
        rec.partial("reconciliation needs the complete listing tree and feed")

    prop = ctx.check("segmentation_proposal", "Business-led segmentation proposal gate", need_products)
    if prop.runnable:
        empty = [s for s in SLOTS if not any(_norm(p.get(s)) for p in products.values())]
        margin = sorted({str(r.get("margin_basis")) for r in ctx.rows(STRATEGY) if r.get("margin_basis")})
        if empty:
            prop.review("segmentation_proposal", {"batch": "empty_label_slots"},
                        "Does a documented business decision justify a new segmentation in one of the empty slots?",
                        evidence={"empty_slots": empty, "profile_objectives": ctx.profile.get("objectives"),
                                  "margin_basis_supplied": margin, "catalog_products": len(products)},
                        outcomes={"proposal_supported": {"severity": "Info", "recommendation":
                                                         "Propose the documented segmentation (request-only)."},
                                  "no_proposal": {"severity": None, "recommendation": "No change."}},
                        guidance="proposal needs " + ", ".join(PROPOSAL_FIELDS) + "; kind 'margin' needs a supplied "
                                 "margin_basis. Do not infer targets or split campaigns from labels alone.")
        prop.observe("Empty label slots available for optional segmentation", empty_slots=empty,
                     margin_basis_supplied=margin)
    mig = ctx.check("migration_safeguards", "Downstream-use inventory for label migration", need_products)
    if mig.runnable:
        for slot in SLOTS:
            populated = sum(1 for p in products.values() if _norm(p.get(slot)))
            mig.observe(f"{slot}: downstream uses before any migration", slot=slot, populated_products=populated,
                        listing_nodes=sum(len(v) for (s, _), v in used.items() if s == slot),
                        dictionary_uses=sorted({str(r.get("intended_use")) for (m, s), vals in dictionary.items()
                                                if s == slot for rows in vals.values() for r in rows
                                                if r.get("intended_use")}),
                        rule="never replace populated values without migration and rollback")
    _build_plan(ctx)


# ---------------------------------------------------------------------------------------------- #115 build plan
def _dim(dim) -> tuple[str, int | None] | None:
    """Plan key dimension → (resolver dimension, level) or None when unsupported."""
    d = str(dim or "").strip().lower()
    m = _PT_LEVEL.fullmatch(d)
    if m:
        return "product_type", int(m.group(1))
    return (d, None) if d in ("item_id", "brand", *SLOTS) else None


def _build_request(ctx) -> tuple[dict | None, list[str]]:
    """Parse and validate profile.shopping_build_plan_request against campaigns and feed columns."""
    raw = ctx.profile.get("shopping_build_plan_request")
    if not raw:
        return None, []
    if not isinstance(raw, dict):
        return None, ["shopping_build_plan_request must be a map"]
    problems: list[str] = []
    camps: dict[str, str | None] = {}
    c_raw = raw.get("campaigns")
    for k, v in (c_raw.items() if isinstance(c_raw, dict) else
                 ((x.get("campaign_id") if isinstance(x, dict) else x, x) for x in c_raw or [])
                 if isinstance(c_raw, list) else []):
        if k is not None:
            camps[str(k)] = _norm(v.get("priority")) or None if isinstance(v, dict) else None
    if not camps:
        problems.append("campaigns: list or map of existing Standard Shopping campaign ids required")
    ch = {str(c.get("id")): str(c.get("channel_type") or "").upper() for c in ctx.rows("campaigns")}
    for cid in sorted(camps):
        if ch.get(cid) != "SHOPPING":
            problems.append(f"campaign {cid} is not a Standard Shopping campaign in campaigns.csv ({ch.get(cid)})")
    pcols = ctx.table(PRODUCTS).columns
    scope = raw.get("scope") or {}
    if not isinstance(scope, dict) or any(k not in KEY_COLS or k not in pcols for k in scope):
        problems.append(f"scope must map feed key columns {[c for c in KEY_COLS if c in pcols]} to values")
        scope = {}
    rules = []
    for i, r in enumerate(raw.get("routing") or []):
        when = r.get("when") if isinstance(r, dict) else None
        conds = [(_dim(k), _norm(v)) for k, v in (when or {}).items()] if isinstance(when, dict) else []
        target = (str(r.get("campaign_id")) if r.get("campaign_id") is not None else None,
                  _norm(r.get("priority")) or None) if isinstance(r, dict) else (None, None)
        if not conds or any(d is None or not v or not _attr(d[0], d[1], {}, pcols)[0] for d, v in conds):
            problems.append(f"routing[{i}]: when needs supported dims present in the feed with non-empty values")
        elif (target[0] is None) == (target[1] is None):
            problems.append(f"routing[{i}]: set exactly one of campaign_id or priority")
        elif target[0] is not None and target[0] not in camps:
            problems.append(f"routing[{i}]: campaign {target[0]} not in the requested campaigns")
        elif target[1] is not None and target[1] not in camps.values():
            problems.append(f"routing[{i}]: no requested campaign declares priority '{target[1]}'")
        else:
            rules.append({"index": i, "conds": conds, "campaign_id": target[0], "priority": target[1]})
    rem = raw.get("remainder_campaign_id")
    rem = str(rem) if rem is not None else None
    if rem is not None and rem not in camps:
        problems.append(f"remainder_campaign_id {rem} not in the requested campaigns")
    return {"campaigns": camps, "scope": {k: _norm(v) for k, v in scope.items()}, "rules": rules,
            "remainder_campaign_id": rem}, problems


def _scope_offers(ctx, req: dict) -> dict:
    """In-scope catalog products (distinct key → row) matching every request scope filter."""
    products, _ = _products(ctx)
    return {k: p for k, p in products.items() if all(_norm(p.get(c)) == v for c, v in req["scope"].items())}


def _matches(conds, product, pcols) -> bool:
    return all(_attr(d[0], d[1], product, pcols)[1] == v for d, v in conds)


def _build_plan(ctx) -> None:
    """Opt-in #115: queue one shopping_build_plan review for a valid request over a certified-complete feed.

    Rules:   not_applicable without profile.shopping_build_plan_request; invalid request or a feed without manifest
             completeness → partial and no review (exactly-once is unprovable). Outcomes: plan_proposed (Info) |
             no_plan (none). Evidence carries dimension value counts and up to OFFER_EVIDENCE_CAP offers.
    """
    chk = ctx.check("shopping_build_plan", "Requested Standard Shopping ad-group/product-group plan (opt-in, #115)",
                    {PRODUCTS: ["merchant_id", "offer_id", "target_country"], "campaigns": ["id", "channel_type"]},
                    applicable=bool(ctx.profile.get("shopping_build_plan_request")),
                    na_reason="profile.shopping_build_plan_request not set (opt-in)")
    if not chk.runnable:
        return
    req, problems = _build_request(ctx)
    for p in problems:
        chk.partial(p, ["profile.shopping_build_plan_request"])
    t = ctx.table(PRODUCTS)
    if t.complete is not True or t.truncated:
        chk.partial("merchant_products not certified complete: exactly-once assignment not provable",
                    [f"{PRODUCTS} (manifest completeness)"])
        return
    if problems:
        return
    offers = _scope_offers(ctx, req)
    if not offers:
        chk.partial("no in-scope offers for the requested scope")
        return
    pcols = t.columns
    dims = {}
    depth = max(len(str(p.get("product_type") or "").split(">")) for p in offers.values()) \
        if "product_type" in pcols else 0
    for name in ["brand", *SLOTS, *(f"product_type_l{i}" for i in range(1, depth + 1))]:
        d = _dim(name)
        if not _attr(d[0], d[1], {}, pcols)[0]:
            continue
        counts: dict = {}
        for p in offers.values():
            v = _attr(d[0], d[1], p, pcols)[1]
            counts[v or "(empty)"] = counts.get(v or "(empty)", 0) + 1
        dims[name] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:200])
    cols = [c for c in ("offer_id", "brand", "product_type", *SLOTS) if c in pcols]
    rows = [{"product_key": _pkey(k), **{c: offers[k].get(c) for c in cols}} for k in sorted(offers)]
    ev = {"in_scope_offers": len(offers), "scope": req["scope"], "requested_campaigns": req["campaigns"],
          "routing": [{"index": r["index"], "when": {f"{d[0]}{'_l' + str(d[1]) if d[1] else ''}": v
                                                    for d, v in r["conds"]},
                       "campaign_id": r["campaign_id"], "priority": r["priority"]} for r in req["rules"]],
          "remainder_campaign_id": req["remainder_campaign_id"], "dimension_values": dims,
          "item_id_dimension": "item_id matches offer_id", "offers": rows[:OFFER_EVIDENCE_CAP],
          "offers_truncated": len(rows) > OFFER_EVIDENCE_CAP}
    chk.review("shopping_build_plan", {"request": "shopping_build_plan", "campaign_ids": sorted(req["campaigns"])},
               "Propose a Standard Shopping ad-group/product-group plan that partitions the in-scope offers across "
               "the requested campaigns, or decline.", evidence=ev,
               outcomes={"plan_proposed": {"severity": "Info", "recommendation":
                                           "Owner review of the validated build plan; nothing is created."},
                         "no_plan": {"severity": None, "recommendation":
                                     "No plan: state the missing business segmentation or routing decision."}},
               guidance="plan_proposed needs proposal {groups: [{campaign_id, ad_group, key: {dim: value}}], "
                        "remainder: {campaign_id, ad_group} | {exclude: true}}. dims: item_id, brand, "
                        "product_type_lN, custom_label_0..4 (equality on normalized values). Every in-scope offer in "
                        "at most one group; the rest go to the explicit remainder; no empty groups; respect routing "
                        "and remainder_campaign_id. No bids or statuses (no approved inputs).")
    chk.observe("Build-plan request", in_scope_offers=len(offers), campaigns=req["campaigns"],
                routing_rules=len(req["rules"]), dimensions=sorted(dims))


def _verify_build_plan(ctx, proposal) -> list[str]:
    """Deterministic partition/routing proof for a plan_proposed proposal (see module rules)."""
    req, problems = _build_request(ctx)
    if req is None or problems:
        return ["shopping_build_plan_request is missing or invalid: " + "; ".join(problems)]
    if not isinstance(proposal, dict) or not isinstance(proposal.get("groups"), list):
        return ["proposal must be {groups: [{campaign_id, ad_group, key}], remainder}"]
    pcols = ctx.table(PRODUCTS).columns
    offers = _scope_offers(ctx, req)
    camps = req["campaigns"]
    problems, dest, seen = [], {}, set()
    for gi, g in enumerate(proposal["groups"]):
        label = f"group {gi + 1}"
        if not isinstance(g, dict):
            problems.append(f"{label}: must be an object")
            continue
        cid, ag, key = str(g.get("campaign_id")), str(g.get("ad_group") or "").strip(), g.get("key")
        if cid not in camps:
            problems.append(f"{label}: campaign {cid} not in the requested campaigns {sorted(camps)}")
        if not ag:
            problems.append(f"{label}: ad_group name required")
        if not isinstance(key, dict) or not key:
            problems.append(f"{label}: key must be a non-empty {{dim: value}} map")
            continue
        conds, bad = [], False
        for k, v in sorted(key.items()):
            d, nv = _dim(k), _norm(v)
            if d is None or not _attr(d[0], d[1], {}, pcols)[0]:
                problems.append(f"{label}: key dimension '{k}' unsupported or absent from the feed")
                bad = True
            elif not nv or not any(_attr(d[0], d[1], p, pcols)[1] == nv for p in offers.values()):
                problems.append(f"{label}: key {k}='{v}' does not exist among in-scope offers")
                bad = True
            else:
                conds.append((d, nv))
        if bad:
            continue
        sig = (cid, _norm(ag), tuple(conds))
        if sig in seen:
            problems.append(f"{label}: duplicates another group")
        seen.add(sig)
        members = [k for k in sorted(offers) if _matches(conds, offers[k], pcols)]
        if not members:
            problems.append(f"{label}: key {key} matches no in-scope offer (empty group)")
        for k in members:
            dest.setdefault(k, []).append((gi + 1, cid))
    multi = {k: v for k, v in dest.items() if len(v) > 1}
    if multi:
        sample = [f"{_pkey(k)} in groups {[g for g, _ in v]}" for k, v in sorted(multi.items())[:5]]
        problems.append(f"{len(multi)} offers assigned more than once, e.g. {sample}")
    rem = proposal.get("remainder")
    rem_cid = None
    if not isinstance(rem, dict) or (rem.get("exclude") is True) == bool(rem.get("campaign_id")):
        problems.append("remainder ('everything else') must be explicit: {campaign_id, ad_group} or {exclude: true}")
    elif rem.get("exclude") is True:
        if req["remainder_campaign_id"]:
            problems.append(f"remainder must go to campaign {req['remainder_campaign_id']}, not be excluded")
    else:
        rem_cid = str(rem.get("campaign_id"))
        if rem_cid not in camps:
            problems.append(f"remainder campaign {rem_cid} not in the requested campaigns")
        if not str(rem.get("ad_group") or "").strip():
            problems.append("remainder needs an ad_group name")
        if req["remainder_campaign_id"] and rem_cid != req["remainder_campaign_id"]:
            problems.append(f"remainder must go to campaign {req['remainder_campaign_id']}, not {rem_cid}")
    breaches: dict = {}
    for k in sorted(offers):
        rule = next((r for r in req["rules"] if _matches(r["conds"], offers[k], pcols)), None)
        if rule is None:
            continue
        got = dest[k][0][1] if k in dest else rem_cid
        ok = got is not None and (got == rule["campaign_id"] if rule["campaign_id"] else camps.get(got) == rule["priority"])
        if not ok:
            breaches.setdefault(rule["index"], []).append(f"{_pkey(k)}→{got or 'excluded'}")
    for i, offs in sorted(breaches.items()):
        r = next(x for x in req["rules"] if x["index"] == i)
        want = f"campaign {r['campaign_id']}" if r["campaign_id"] else f"priority '{r['priority']}'"
        problems.append(f"routing[{i}] requires {want}; {len(offs)} offers violate it, e.g. {offs[:5]}")
    return problems


def _label_nodes(trees) -> dict:
    """(slot, normalized value) -> [(campaign, group, node_id, matched count)]."""
    out: dict = {}
    for (cid, gid), res in sorted(trees.items()):
        for nid, n in sorted(res["nodes"].items()):
            d = _norm(n["dimension"]).replace(" ", "_")
            m = re.fullmatch(r"custom_(?:label|attribute)_?([0-4])", d)
            if m and n["value"] is not None and not n["other_case"]:
                out.setdefault((f"custom_label_{m.group(1)}", _norm(n["value"])), []).append(
                    (cid, gid, nid, len(n["matched"])))
    return out


def _dictionary_check(ctx, chk, products, dictionary, used, day) -> None:
    by: dict = {}
    for k, p in products.items():
        m = str(p.get("merchant_id") or "")
        for slot in SLOTS:
            v = _norm(p.get(slot))
            if v:
                by.setdefault((m, slot), {}).setdefault(v, []).append(_pkey(k))
    outcomes = {"conflicts_current_rule": {"severity": "Warning", "recommendation":
                                           "Correct the label or the rule after checking downstream uses."},
                "intentionally_retained": {"severity": None, "recommendation": "Document the retained value."},
                "uncertain": {"severity": "Info", "recommendation": "Ask the label owner."}}
    for (m, slot), vals in sorted(by.items()):
        entries = dictionary.get((m, slot))
        entity = {"merchant_id": m, "slot": slot}
        if not entries:
            chk.finding("undeclared_label_meaning", "Info", entity,
                        f"{slot} holds {len(vals)} values for merchant {m} but the dictionary declares none",
                        evidence={"values": {v: len(k) for v, k in sorted(vals.items())}},
                        recommendation="Ask the owner to declare meanings before using the slot for decisions.",
                        uncertainty="Meaning unknown; values may be legitimate free-form reporting.")
            continue
        current = _current_values(dictionary, m, slot, day)
        undeclared = {v: k for v, k in vals.items() if v not in entries}
        for v in sorted(set(vals) & set(entries) - current):
            rows = entries[v]
            ent = {**entity, "value": v}
            in_rules = used.get((slot, v), [])
            ev = {"products": len(vals[v]), "product_keys": sorted(vals[v])[:50], "as_of": day,
                  "valid_windows": sorted({f"{r.get('valid_from')}..{r.get('valid_to')}" for r in rows}),
                  "approved_at": sorted({str(r.get("approved_at")) for r in rows}),
                  "intended_use": sorted({str(r.get("intended_use")) for r in rows if r.get("intended_use")}),
                  "listing_nodes": [list(x) for x in in_rules],
                  "seasonal_calendar_reference": sorted({str(r.get("seasonal_calendar_reference")) for r in rows
                                                         if r.get("seasonal_calendar_reference")})}
            prov = chk.finding("expired_label_value", "Info", ent,
                               f"{slot}='{v}' is outside its approved validity on {day} for {len(vals[v])} products",
                               evidence=ev, recommendation="Confirm with the owner whether the classification expired.",
                               uncertainty="Expired value alone does not show a selection or reporting conflict.")
            if in_rules or ev["intended_use"]:
                chk.review("expired_label_value", ent,
                           f"Does the expired value {slot}='{v}' conflict with an approved current selection or "
                           f"reporting rule?", evidence=ev, outcomes=outcomes, provisional=prov,
                           guidance="Use only the dictionary, validity dates and listing nodes; conflicts_current_rule "
                                    "needs proposal.corrections [{offer_id, slot, value}] using current values.")
        if undeclared:
            ent = {**entity, "batch": "undeclared_values"}
            norm_hint = {v: sorted(a for a in current if re.sub(r"[\W_]+", "", a) == re.sub(r"[\W_]+", "", v))
                         for v in undeclared}
            ev = {"undeclared": {v: len(k) for v, k in sorted(undeclared.items())},
                  "example_keys": {v: sorted(k)[:10] for v, k in sorted(undeclared.items())},
                  "current_dictionary_values": sorted(current), "punctuation_insensitive_matches": norm_hint,
                  "listing_nodes": {v: [list(x) for x in used.get((slot, v), [])] for v in sorted(undeclared)}}
            prov = chk.finding("undeclared_label_meaning", "Info", ent,
                               f"{len(undeclared)} {slot} values for merchant {m} are not in the approved dictionary",
                               evidence=ev, recommendation="Classify each value as misspelling, free-form or unknown.",
                               uncertainty="A value outside the dictionary may be legitimate free-form reporting.")
            chk.review("undeclared_label_meaning", ent,
                       f"Are the undeclared {slot} values misspellings that conflict with an approved rule, "
                       f"legitimate free-form reporting, or of unknown meaning?", evidence=ev,
                       outcomes={"misspelling_conflicts_rule": {"severity": "Warning", "recommendation":
                                                                "Correct the feed values to the approved value."},
                                 "free_form_reporting": {"severity": None, "recommendation": "Keep; document."},
                                 "unknown_meaning": {"severity": "Info", "recommendation": "Ask the owner."}},
                       provisional=prov,
                       guidance="misspelling_conflicts_rule needs proposal.corrections [{value, intended_value}] "
                                "with intended_value from current_dictionary_values.")
        chk.observe(f"{slot} dictionary conformance for merchant {m}", merchant_id=m, slot=slot,
                    distinct_values=len(vals), declared_current=len(set(vals) & current),
                    undeclared=len(undeclared), dictionary_values=len(entries))


def _classification_check(ctx, chk, products, dictionary, day) -> None:
    by_offer: dict = {}
    for k, p in products.items():
        by_offer.setdefault((str(p.get("merchant_id") or ""), str(p.get("offer_id"))), []).append((k, p))
    n = 0
    for r in sorted(ctx.rows(STRATEGY), key=lambda r: (str(r.get("merchant_id")), str(r.get("offer_id")),
                                                        str(r.get("label_slot")))):
        if not r.get("offer_id"):
            continue
        slot = _slot(r.get("label_slot"))
        if slot is None or not _valid(r, day) or not r.get("approved_at"):
            continue
        m, oid = str(r.get("merchant_id") or ""), str(r.get("offer_id"))
        expected = _norm(r.get("allowed_value"))
        for k, p in by_offer.get((m, oid), []):
            n += 1
            actual = _norm(p.get(slot))
            if actual == expected:
                continue
            rule_uses = sorted({str(x.get("intended_use")) for rows in (dictionary.get((m, slot)) or {}).values()
                                for x in rows if x.get("intended_use") and _valid(x, day)})
            sev = "Warning" if rule_uses else "Info"
            chk.finding("incorrect_label_value", sev, {"product_key": _pkey(k), "slot": slot},
                        f"Product {_pkey(k)} has {slot}='{actual}' but the approved classification is '{expected}'",
                        evidence={"approved_at": r.get("approved_at"), "valid_from": r.get("valid_from"),
                                  "valid_to": r.get("valid_to"), "current_intended_uses": rule_uses,
                                  "evidence_as_of": day},
                        recommendation="Ask the feed owner to correct the label; check downstream uses first.",
                        uncertainty="Classification date vs feed refresh may explain a transient difference.")
    chk.observe("Product-level classifications compared", comparisons=n, as_of=day)


def _reconcile(ctx, chk, trees, products, dictionary, day) -> None:
    sel = ctx.table(SELECTION)
    platform: dict = {}
    if sel is not None and not sel.missing(["campaign_id", "offer_id", "included"]):
        gcol = _col(sel, "asset_group_id", "ad_group_id", "group_id")
        for r in sel.rows:
            platform.setdefault((str(r.get("campaign_id")), str(r.get(gcol) or "") if gcol else ""), {})[
                str(r.get("offer_id"))] = V.boolean(r.get("included"))
    else:
        chk.partial("product_selection not supplied: local tree resolution only",
                    [f"{SELECTION}:campaign_id", f"{SELECTION}:offer_id", f"{SELECTION}:included"])
    for gkey, res in sorted(trees.items()):
        offer = {k: str(products[k].get("offer_id")) for k in products}
        if gkey in platform:
            local_inc = {offer[k] for k in res["included"]}
            disagree = sorted(o for o, inc in platform[gkey].items() if inc is not None and (o in local_inc) != inc)
            if disagree:
                chk.partial(f"{gkey}: platform selection disagrees with local resolution for {len(disagree)} offers")
                chk.observe(f"Group {gkey[0]}/{gkey[1]}: resolver vs platform selection", offers=disagree[:50],
                            count=len(disagree))
        # label-driven exclusions: products with a populated label value not listed by any sibling node
        for nid, n in sorted(res["nodes"].items()):
            d = _norm(n["dimension"]).replace(" ", "_")
            m = re.fullmatch(r"custom_(?:label|attribute)_?([0-4])", d)
            if not m or not n["other_case"]:
                continue
            slot = f"custom_label_{m.group(1)}"
            dropped = sorted(k for k in n["matched"] if _norm(products[k].get(slot)) and k in res["excluded"])
            if dropped:
                vals: dict = {}
                for k in dropped:
                    vals[_norm(products[k].get(slot))] = vals.get(_norm(products[k].get(slot)), 0) + 1
                _label_review(ctx, chk, products, gkey, nid, slot, dropped, vals, dictionary, day,
                              f"{len(dropped)} products with a populated {slot} fall into the EXCLUDED other-case "
                              f"node {nid}")
        for nid, n in sorted(res["nodes"].items()):
            d = _norm(n["dimension"]).replace(" ", "_")
            m = re.fullmatch(r"custom_(?:label|attribute)_?([0-4])", d)
            if m and n["value"] is not None and not n["other_case"] and not n["matched"] and ctx.table(PRODUCTS).complete:
                slot = f"custom_label_{m.group(1)}"
                _label_review(ctx, chk, products, gkey, nid, slot, [], {}, dictionary, day,
                              f"listing node {nid} selects {slot}='{n['value']}' but no catalog product carries it")


def _label_review(ctx, chk, products, gkey, nid, slot, keys, vals, dictionary, day, summary) -> None:
    entity = {"campaign_id": gkey[0], "group_id": gkey[1], "node_id": nid, "slot": slot}
    merchants = sorted({k[0] for k in keys}) if keys else []
    current = sorted({v for m in merchants for v in _current_values(dictionary, m, slot, day)}) if merchants else \
        sorted({v for (m, s) in dictionary if s == slot for v in _current_values(dictionary, m, s, day)})
    ev = {"product_keys": [_pkey(k) for k in keys[:50]], "products": len(keys), "values": vals,
          "current_dictionary_values": current,
          "exposure": _exposure(ctx, {str(products[k].get("offer_id")) for k in keys}) if keys else None}
    prov = chk.finding("label_rule_mismatch", "Info", entity, summary, evidence=ev,
                       recommendation="Confirm the intended selection before correcting labels or the tree.",
                       uncertainty="Whether these products are intended inventory is a business fact.")
    chk.review("label_rule_mismatch", entity,
               f"{summary}. Is this a label/rule mismatch against the approved selection?", evidence=ev,
               outcomes={"excludes_material_intended": {"severity": "Critical", "recommendation":
                                                        "Prioritize the correction; cite the intent evidence."},
                         "includes_prohibited": {"severity": "Critical", "recommendation":
                                                 "Prioritize removal; cite the prohibition evidence."},
                         "incorrect_label_conflict": {"severity": "Warning", "recommendation":
                                                      "Correct the labels or node values (feed/Ads owner)."},
                         "intentional": {"severity": None, "recommendation": "Keep; document the selection."},
                         "uncertain": {"severity": "Info", "recommendation": "Ask the selection owner."}},
               provisional=prov,
               guidance="Critical outcomes need proposal.evidence_ref to supplied intent/materiality evidence; "
                        "incorrect_label_conflict needs proposal.corrections [{value, intended_value}] using current "
                        "dictionary values. Overlap architecture belongs to 089.")


def verify(ctx, item, decision) -> list[str]:
    """Re-check label corrections, segmentation proposals and requested Shopping build plans.

    Rules:   evidence_ref for Critical, dictionary-valid corrections, empty-slot proposals; shopping_build_plan
             plan_proposed must partition the in-scope feed (exactly once incl. explicit remainder), use only
             existing non-empty keys and requested campaigns, and satisfy routing/remainder constraints.
    """
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if item.condition_key == "shopping_build_plan":
        return _verify_build_plan(ctx, decision.get("proposal")) if outcome == "plan_proposed" else []
    if outcome in ("excludes_material_intended", "includes_prohibited"):
        return [] if proposal.get("evidence_ref") else [f"{outcome} needs proposal.evidence_ref"]
    if outcome in ("incorrect_label_conflict", "misspelling_conflicts_rule", "conflicts_current_rule"):
        allowed = set(item.evidence.get("current_dictionary_values") or [])
        if not allowed:
            day = ctx.snapshot or ctx.as_of
            allowed = {v for (m, s) in _dictionary(ctx) if s == item.entity.get("slot")
                       for v in _current_values(_dictionary(ctx), m, s, day)}
        corr = proposal.get("corrections") or []
        if not corr:
            return ["proposal.corrections required"]
        bad = [c for c in corr if _norm((c or {}).get("intended_value") or (c or {}).get("value")) not in allowed]
        return [f"correction {c} does not use a current approved dictionary value" for c in bad]
    if item.condition_key == "segmentation_proposal" and outcome == "proposal_supported":
        problems = [f"proposal.{k} required" for k in PROPOSAL_FIELDS if not proposal.get(k)]
        slot = _slot(proposal.get("slot"))
        if proposal.get("slot") and slot not in (item.evidence.get("empty_slots") or []):
            problems.append(f"slot {proposal.get('slot')} is populated or invalid; never replace populated values")
        if str(proposal.get("kind") or "").lower() == "margin" and not item.evidence.get("margin_basis_supplied"):
            problems.append("margin tiers need a supplied label_strategy margin_basis")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
