"""check.py — skill-089 deterministic PMax asset-group inventory, diagnostics and product-selection reconciliation.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str] | resolve_trees(ctx, key)
used_by: skills/skill-089-pmax-asset-group-structure/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #69 PMax Campaign Settings Alerts (nilsrooijmans.com) — clean-room: asset-group status/primary_status
         diagnostics become a serving review (Critical only via evidence_ref); campaign URL-expansion alerts live in 092.
         index #123 Build SPAGs from product IDs (Frederic Harnois, GitHub) — clean-room: item-ID (offer_id)
         listing subdivisions are resolved like any tree; building SPAGs/groups is NOT integrated (mutation and
         split-for-count, which the recipe forbids).
         skill-085 check.py carries the same private listing-tree resolver (keep semantics identical).
rules:   PMax = campaigns.channel_type PERFORMANCE_MAX (key campaigns.id, alternative campaigns.campaign_id).
         Absence claims (zero groups, zero associations) need a manifest-complete parent/child inventory;
         otherwise partial. Paused/removed/ineligible groups stay distinct in the inventory.
         Listing trees: custom/pmax_listing_rules, group column asset_group_id; inclusion column inclusion |
         inclusion_exclusion | included_excluded | status; level column level | dimension_level; root scope
         merchant_id, feed_label, target_country|country, channel, language. Unsupported dimensions
         (category, unknown) leave products UNRESOLVED (partial), never "all products".
         Intent: external/pmax_group_intent.intended_product_keys lists offer_ids (V.split_list); a
         product_predicate without keys is not machine-evaluated (partial). permitted_overlap false/none =
         overlap explicitly not permitted. business_critical_inventory lists offer_ids.
         Deterministic Warning only for intended offers not selected / forbidden overlap with complete
         resolution; theme/offer contradictions and extra products are reviews; Critical only via review with
         proposal.evidence_ref equal to one of the item's evidence_refs (the reviewed group's pmax_groups/
         pmax_listing_rules/pmax_group_intent rows and pmax_group_daily window, as supplied); no ref-bearing
         evidence column is declared. Group counts and Ad Strength are descriptive only (never findings).
         verify(): selection/theme Warning outcomes need proposal {old_intended_keys, new_intended_keys,
         protected_inventory}; new keys must exist in the feed; protected_inventory must keep the group's
         business-critical offers.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | Critical evidence_ref restricted to item evidence_refs
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

SKILL = "skill-089-pmax-asset-group-structure"
VERSION = "1.0.0"

PRODUCTS = "external/merchant_products"
GROUPS = "custom/pmax_groups"
ASSOC = "custom/pmax_group_assets"
RULES = "custom/pmax_listing_rules"
INTENT = "external/pmax_group_intent"
DAILY = "custom/pmax_group_daily"
PMAX = "PERFORMANCE_MAX"
SLOTS = tuple(f"custom_label_{i}" for i in range(5))
KEY_COLS = ("merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country")
BLOCKING = {"not_eligible", "ineligible", "disapproved", "suspended", "not_serving", "removed_by_policy"}
LIMITED = {"limited", "eligible_limited", "learning"}
TEXT_FIELDS = {"headline", "long_headline", "description", "business_name"}
PROPOSAL_FIELDS = ("old_intended_keys", "new_intended_keys", "protected_inventory")
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
def _key_col(ctx) -> str:
    t = ctx.table("campaigns")
    return "campaign_id" if t is not None and "id" not in t.columns and "campaign_id" in t.columns else "id"


def _pmax(ctx) -> dict[str, dict]:
    kc = _key_col(ctx)
    return {str(r.get(kc)): r for r in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get(kc)))
            if str(r.get("channel_type") or "").upper() == PMAX}


def _status(v) -> str:
    return V.norm_text(v).replace(" ", "_")


def _groups(ctx, pmax) -> dict[tuple, dict]:
    return {(str(r.get("campaign_id")), str(r.get("asset_group_id"))): r
            for r in sorted(ctx.rows(GROUPS), key=lambda r: (str(r.get("campaign_id")), str(r.get("asset_group_id"))))
            if str(r.get("campaign_id")) in pmax}


def _intent(ctx) -> dict[tuple, dict]:
    return {(str(r.get("campaign_id")), str(r.get("asset_group_id"))): r for r in ctx.rows(INTENT)}


def _group_cost(ctx, key) -> dict | None:
    t = ctx.table(DAILY)
    if t is None or t.missing(["campaign_id", "asset_group_id", "date", "cost"]):
        return None
    seen, cost, n = set(), 0.0, 0
    for r in t.rows:
        if (str(r.get("campaign_id")), str(r.get("asset_group_id"))) != key:
            continue
        g = (r.get("date"), r.get("goal_set_id"))
        if g in seen:
            continue
        seen.add(g)
        c = ctx.money(r.get("cost"))
        if c is not None:
            cost += c
            n += 1
    return {"cost": cost, "days": n, "note": "historical exposure, not savings"}


def _group_refs(ctx, key, tables: tuple[str, ...]) -> list[str]:
    """Stable refs for the supplied evidence rows of one group: row tables by key, DAILY by report window."""
    cid, gid = key
    refs = []
    for table in tables:
        if table == DAILY:
            cost = _group_cost(ctx, key)
            if cost and cost["days"]:
                refs.append(f"{DAILY}.csv {cid}/{gid} {ctx.period_start}..{ctx.period_end}")
        elif table == RULES or any((str(r.get("campaign_id")), str(r.get("asset_group_id"))) == key
                                   for r in ctx.rows(table)):
            refs.append(f"{table}.csv {cid}/{gid}")
    return refs


def run(ctx) -> None:
    """Run PMax asset-group inventory, serving diagnostics, theme, listing-tree resolution and selection checks.

    Rules:   Absence claims need a manifest-complete inventory; unsupported listing dimensions leave products unresolved
             (partial). Deterministic Warning only for intended offers not selected or forbidden overlap under complete
             resolution; serving diagnostics and extra products are Info + ai_review; theme/offer contradictions are
             review-only. Critical only via review with proposal.evidence_ref; group counts and Ad Strength never become
             findings.
    """
    kc = _key_col(ctx)
    inv = ctx.check("group_inventory", "Complete campaign/group inventory with associations",
                    {"campaigns": [kc, "channel_type"], GROUPS: ["campaign_id", "asset_group_id", "status"]})
    camps = ctx.table("campaigns")
    pmax = _pmax(ctx) if camps is not None and not camps.missing([kc, "channel_type"]) else {}
    groups = _groups(ctx, pmax)
    no_pmax = inv.runnable and not pmax
    if no_pmax:
        inv.not_applicable("no Performance Max campaigns in the campaign inventory")
    elif inv.runnable:
        _inventory(ctx, inv, pmax, groups)
    if no_pmax:
        for cid, title in (("serving_diagnostics", "Group serving diagnostics"),
                           ("theme_consistency", "Theme vs assets, landing pages and intended offer"),
                           ("listing_resolution", "Resolve listing trees against the complete feed"),
                           ("selection_vs_intent", "Resolved selection vs approved intent and overlap"),
                           ("asset_summary", "Descriptive asset and Ad Strength summary"),
                           ("structure_proposal", "Evidence-bound structural proposals")):
            ctx.check(cid, title).not_applicable("no Performance Max campaigns")
        return

    diag = ctx.check("serving_diagnostics", "Group serving diagnostics",
                     {"campaigns": [kc, "channel_type"],
                      GROUPS: ["campaign_id", "asset_group_id", "status", "primary_status", "platform_diagnostic"]})
    if diag.runnable:
        _diagnostics(ctx, diag, pmax, groups)

    theme = ctx.check("theme_consistency", "Theme vs assets, landing pages and intended offer",
                      {GROUPS: ["campaign_id", "asset_group_id", "status", "final_urls"],
                       INTENT: ["campaign_id", "asset_group_id", "theme", "landing_page_evidence", "business_objective"]})
    if theme.runnable:
        _themes(ctx, theme, pmax, groups)

    res_needs = {PRODUCTS: ["merchant_id", "offer_id", "target_country"],
                 RULES: ["campaign_id", "asset_group_id", "node_id", "parent_node_id", "dimension", "value",
                         "other_case"]}
    lr = ctx.check("listing_resolution", "Resolve listing trees against the complete feed", res_needs)
    trees, products = {}, {}
    if lr.runnable:
        t = ctx.table(RULES)
        if not _col(t, "inclusion", "inclusion_exclusion", "included_excluded", "status"):
            lr.partial("no inclusion column: every unit unresolved", [f"{RULES}:inclusion"])
        trees, notes, meta = resolve_trees(ctx, RULES)
        products = meta["products"]
        trees = {k: v for k, v in trees.items() if k[0] in pmax}
        for n in notes:
            lr.partial(n)
        for gkey, res in sorted(trees.items()):
            lr.observe(f"Group {gkey[0]}/{gkey[1]} resolved product selection", campaign_id=gkey[0],
                       asset_group_id=gkey[1], catalog_products=len(products), included=len(res["included"]),
                       excluded=len(res["excluded"]), unresolved=len(res["unresolved"]), no_path=len(res["no_path"]))
        feed_campaigns = sorted({k[0] for k in trees})
        lr.observe("Feed-based PMax campaigns (listing trees supplied)", campaign_ids=feed_campaigns,
                   non_feed_campaigns=sorted(set(pmax) - set(feed_campaigns)))

    sel = ctx.check("selection_vs_intent", "Resolved selection vs approved intent and overlap",
                    {**res_needs, INTENT: ["campaign_id", "asset_group_id", "intended_product_keys",
                                           "permitted_overlap", "business_critical_inventory"]})
    if sel.runnable and lr.runnable:
        _selection(ctx, sel, trees, products, groups)
    elif sel.runnable:
        sel.skip("listing resolution unavailable", lr.missing)

    summ = ctx.check("asset_summary", "Descriptive asset and Ad Strength summary",
                     {ASSOC: ["campaign_id", "asset_group_id", "asset_id", "field_type", "association_status",
                              "approval_status"]})
    if summ.runnable:
        _assets(ctx, summ, groups)

    prop = ctx.check("structure_proposal", "Evidence-bound structural proposals")
    eligible = [r for r in ctx.result.reviews if r.condition_key in (
        "theme_offer_contradiction", "unintended_products_selected", "intended_products_not_selected")]
    eligible_f = [f for f in ctx.result.findings if f.condition_key in (
        "intended_products_not_selected", "overlap_contradicts_intent")]
    if not (theme.runnable or sel.runnable):
        prop.skip("theme and selection checks unavailable; no evidenced problem can be assessed",
                  sorted(set(theme.missing) | set(sel.missing)))
    elif not eligible and not eligible_f:
        prop.not_applicable("no evidenced theme/selection problem; no structural proposal (never split for count)")
    else:
        prop.observe("Structural proposals allowed only for these evidenced problems",
                     reviews=sorted(r.id for r in eligible), findings=sorted(f.id for f in eligible_f),
                     required_proposal_fields=list(PROPOSAL_FIELDS))


def _inventory(ctx, chk, pmax, groups) -> None:
    gt = ctx.table(GROUPS)
    complete = gt.complete is True
    orphans = sorted({str(r.get("campaign_id")) for r in gt.rows} - set(pmax) -
                     {str(r.get(_key_col(ctx))) for r in ctx.rows("campaigns")})
    if orphans:
        chk.partial(f"groups reference campaigns missing from the inventory: {orphans}")
    at = ctx.table(ASSOC)
    assoc: dict = {}
    if at is not None and not at.missing(["campaign_id", "asset_group_id", "asset_id"]):
        for r in at.rows:
            assoc.setdefault((str(r.get("campaign_id")), str(r.get("asset_group_id"))), set()).add(str(r.get("asset_id")))
    else:
        chk.partial("association export missing: asset coverage not assessed",
                    [f"{ASSOC}:campaign_id", f"{ASSOC}:asset_group_id", f"{ASSOC}:asset_id"])
    assoc_complete = at is not None and at.complete is True
    for cid, camp in sorted(pmax.items()):
        rows = {k: g for k, g in groups.items() if k[0] == cid}
        by_status: dict = {}
        for k, g in rows.items():
            by_status.setdefault(_status(g.get("status")) or "unknown", []).append(k[1])
        zero_assoc = sorted(k[1] for k in rows if not assoc.get(k)) if assoc_complete else None
        chk.observe(f"PMax {cid}: asset-group inventory", campaign_id=cid, campaign_status=camp.get("status"),
                    groups=len(rows), groups_by_status=by_status,
                    zero_association_groups=zero_assoc if assoc_complete else "unknown (associations not complete)",
                    zero_groups=(not rows) if complete else "unknown (group inventory not complete)")
        if _status(camp.get("status")) in ("paused", "removed"):
            live = sorted(k[1] for k, g in rows.items() if _status(g.get("status")) == "enabled")
            if live:
                chk.observe(f"PMax {cid}: enabled groups under a {camp.get('status')} campaign cannot serve",
                            campaign_id=cid, asset_group_ids=live)
    if not complete:
        chk.partial(f"{gt.filename}: completeness not certified; zero-group campaigns not provable")


def _diagnostics(ctx, chk, pmax, groups) -> None:
    n = 0
    for (cid, gid), g in sorted(groups.items()):
        ps, diag = _status(g.get("primary_status")), g.get("platform_diagnostic")
        live = _status(g.get("status")) == "enabled" and _status(pmax[cid].get("status")) in ("enabled", "")
        if ps in LIMITED and live:
            chk.observe(f"Group {cid}/{gid} limited: {ps}", campaign_id=cid, asset_group_id=gid,
                        platform_diagnostic=diag)
        if not live or ps not in BLOCKING:
            continue
        n += 1
        entity = {"campaign_id": cid, "asset_group_id": gid}
        ev = {"status": g.get("status"), "primary_status": g.get("primary_status"), "platform_diagnostic": diag,
              "campaign_status": pmax[cid].get("status"), "exposure": _group_cost(ctx, (cid, gid)),
              "business_critical_inventory": (_intent(ctx).get((cid, gid)) or {}).get("business_critical_inventory")}
        prov = chk.finding("group_serving_diagnostic", "Info", entity,
                           f"Enabled asset group {gid} reports primary status '{g.get('primary_status')}'",
                           evidence=ev, recommendation="Resolve the named diagnostic with the account owner.",
                           uncertainty="Materiality depends on whether the group carries intended inventory.")
        chk.review("group_serving_diagnostic", entity,
                   f"Does the diagnostic on group {gid} block MATERIAL intended product/group delivery?",
                   evidence={**ev, "evidence_refs": _group_refs(ctx, (cid, gid), (GROUPS, INTENT, DAILY))},
                   provisional=prov,
                   outcomes={"material_intended_blocked": {"severity": "Critical", "recommendation":
                                                           "Fix the diagnostic first; cite the intent/materiality evidence."},
                             "blocked_not_material": {"severity": "Info", "recommendation": "Fix when convenient."},
                             "intended_or_resolved": {"severity": None, "recommendation": "No action."},
                             "uncertain": {"severity": "Info", "recommendation": "Ask the account owner."}},
                   guidance="material_intended_blocked needs proposal.evidence_ref from evidence.evidence_refs "
                            "(supplied intent/delivery evidence).")
    chk.observe("Groups with blocking primary status", count=n, blocking_statuses=sorted(BLOCKING))


def _themes(ctx, chk, pmax, groups) -> None:
    intents = _intent(ctx)
    texts: dict = {}
    for r in ctx.rows(ASSOC):
        if V.norm_text(r.get("field_type")).replace(" ", "_") in TEXT_FIELDS and \
                _status(r.get("association_status")) in ("enabled", "active", ""):
            texts.setdefault((str(r.get("campaign_id")), str(r.get("asset_group_id"))), []).append(
                str(r.get("text_or_media_reference") or ""))
    missing = []
    for key, g in sorted(groups.items()):
        if _status(g.get("status")) != "enabled":
            continue
        it = intents.get(key)
        if it is None:
            missing.append(f"{key[0]}/{key[1]}")
            continue
        entity = {"campaign_id": key[0], "asset_group_id": key[1]}
        chk.review("theme_offer_contradiction", entity,
                   f"Do group {key[1]}'s assets, final URLs and products specifically contradict its approved offer/theme?",
                   evidence={"declared_theme": g.get("theme"), "intended_theme": it.get("theme"),
                             "business_objective": it.get("business_objective"),
                             "landing_page_evidence": it.get("landing_page_evidence"),
                             "final_urls": V.split_list(g.get("final_urls")),
                             "text_assets": sorted(texts.get(key, []))[:30],
                             "target_market": it.get("target_market")},
                   outcomes={"offer_contradiction": {"severity": "Warning", "recommendation":
                                                     "Correct the contradicting asset/URL/selection (proposal)."},
                             "consistent": {"severity": None, "recommendation": "No change; mixed themes are allowed."},
                             "uncertain": {"severity": "Info", "recommendation": "Ask the group owner."}},
                   guidance="A mixed theme or single group is not a defect; name the specific contradiction. "
                            "offer_contradiction needs proposal {" + ", ".join(PROPOSAL_FIELDS) + "}.")
    if missing:
        chk.partial(f"{len(missing)} enabled groups lack an approved intent row: {missing[:20]}")


def _selection(ctx, chk, trees, products, groups) -> None:
    intents = _intent(ctx)
    feed_complete = ctx.table(PRODUCTS).complete is True
    by_offer: dict = {}
    for k, p in products.items():
        by_offer.setdefault(str(p.get("offer_id")), set()).add(k)
    offer = {k: str(p.get("offer_id")) for k, p in products.items()}
    included = {g: {offer[k] for k in r["included"]} for g, r in trees.items()}
    for gkey, res in sorted(trees.items()):
        it = intents.get(gkey)
        entity = {"campaign_id": gkey[0], "asset_group_id": gkey[1]}
        if it is None:
            chk.partial(f"{gkey[0]}/{gkey[1]}: no approved intent row")
            continue
        keys = set(V.split_list(it.get("intended_product_keys"), (" | ", ";", "|", ",")))
        if not keys:
            if it.get("product_predicate"):
                chk.partial(f"{gkey[0]}/{gkey[1]}: product_predicate not machine-evaluated")
            continue
        critical = set(V.split_list(it.get("business_critical_inventory"), (" | ", ";", "|", ",")))
        unresolved_offers = {offer[k] for k in res["unresolved"]}
        not_in_feed = sorted(keys - set(by_offer))
        uncovered = sorted(keys - included[gkey] - unresolved_offers - set(not_in_feed))
        extra = sorted(included[gkey] - keys)
        calc = {"intended": len(keys), "selected": len(included[gkey]), "uncovered": len(uncovered),
                "unresolved_intended": len(keys & unresolved_offers), "not_in_feed": len(not_in_feed),
                "selected_not_intended": len(extra)}
        if keys & unresolved_offers:
            chk.partial(f"{gkey[0]}/{gkey[1]}: {len(keys & unresolved_offers)} intended offers on unresolved branches")
        if not_in_feed:
            chk.observe(f"{gkey[0]}/{gkey[1]}: intended offers absent from the feed snapshot (see 083)",
                        offers=not_in_feed[:50], count=len(not_in_feed), feed_manifest_complete=feed_complete)
        if uncovered:
            ev = {"uncovered_offers": uncovered[:100], "intended_product_keys": sorted(keys)[:100],
                  "business_critical_uncovered": sorted(set(uncovered) & critical),
                  "exposure": _group_cost(ctx, gkey), "owner": it.get("owner")}
            f = chk.finding("intended_products_not_selected", "Warning", entity,
                            f"{len(uncovered)} of {len(keys)} approved intended offers are not selected by group "
                            f"{gkey[1]}'s resolved listing tree", evidence=ev, calculation=calc,
                            recommendation="Correct the listing tree for the named offers; keep protected inventory.",
                            uncertainty="Resolution uses the supplied feed snapshot; timing differences are possible.")
            if ev["business_critical_uncovered"]:
                chk.review("intended_products_not_selected", entity,
                           f"Does the missing selection of business-critical offers in group {gkey[1]} block "
                           f"material intended delivery?",
                           evidence={**ev, "evidence_refs": _group_refs(ctx, gkey, (RULES, INTENT, DAILY))},
                           provisional=f,
                           outcomes={"material_block": {"severity": "Critical", "recommendation":
                                                        "Prioritize the tree correction."},
                                     "confirmed_not_material": {"severity": "Warning", "recommendation":
                                                                "Correct in the next change window."},
                                     "covered_elsewhere": {"severity": None, "recommendation":
                                                           "Document where the offers serve."}},
                           guidance="material_block needs proposal.evidence_ref from evidence.evidence_refs; Warning "
                                    "outcomes need proposal {" + ", ".join(PROPOSAL_FIELDS) + "}.")
        if extra:
            ev = {"selected_not_intended": extra[:100], "count": len(extra),
                  "permitted_overlap": it.get("permitted_overlap"), "theme": it.get("theme")}
            prov = chk.finding("unintended_products_selected", "Info", entity,
                               f"Group {gkey[1]} selects {len(extra)} offers outside its intended keys",
                               evidence=ev, calculation=calc,
                               recommendation="Confirm whether the extra offers are an intended shared offer.",
                               uncertainty="Intended keys may be a partial list of an allowed predicate.")
            chk.review("unintended_products_selected", entity,
                       f"Do the extra offers selected by group {gkey[1]} contradict its approved intent?",
                       evidence=ev, provisional=prov,
                       outcomes={"selection_contradiction": {"severity": "Warning", "recommendation":
                                                             "Narrow the tree via a proposal with protected inventory."},
                                 "acceptable": {"severity": None, "recommendation": "Keep."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the group owner."}},
                       guidance="selection_contradiction needs proposal {" + ", ".join(PROPOSAL_FIELDS) + "}.")
        chk.observe(f"{gkey[0]}/{gkey[1]}: intended vs resolved selection", **calc)
    keys = sorted(trees)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            inter = sorted(included[a] & included[b])
            if not inter:
                continue
            pa, pb = ((intents.get(x) or {}).get("permitted_overlap") for x in (a, b))
            forbidden = [x for x, p in ((a, pa), (b, pb))
                         if p is not None and (V.boolean(p) is False or V.norm_text(p) in ("none", "not_permitted"))]
            data = {"group_a": list(a), "group_b": list(b), "intersection": len(inter),
                    "a_selected": len(included[a]), "b_selected": len(included[b]),
                    "share_of_a": V.ratio(len(inter), len(included[a])), "offers": inter[:50]}
            if forbidden and not (trees[a]["unresolved"] or trees[b]["unresolved"]):
                chk.finding("overlap_contradicts_intent", "Warning",
                            {"group_a": f"{a[0]}/{a[1]}", "group_b": f"{b[0]}/{b[1]}"},
                            f"{len(inter)} offers are selected by both groups although approved intent forbids overlap",
                            evidence={"permitted_overlap": {f"{a[0]}/{a[1]}": pa, f"{b[0]}/{b[1]}": pb}},
                            calculation=data,
                            recommendation="Request rationale; if confirmed, adjust one tree via a proposal.",
                            uncertainty="Eligibility overlap is not simultaneous auction competition.")
            else:
                chk.observe("Overlapping product eligibility (descriptive; not auction competition)", **data)


def _assets(ctx, chk, groups) -> None:
    counts: dict = {}
    for r in ctx.rows(ASSOC):
        key = (str(r.get("campaign_id")), str(r.get("asset_group_id")))
        if key not in groups:
            continue
        c = counts.setdefault(key, {})
        ft = V.norm_text(r.get("field_type")) or "unknown"
        st = _status(r.get("approval_status")) or "unknown"
        c.setdefault(ft, {}).setdefault(st, 0)
        c[ft][st] += 1
    strength: dict = {}
    for key, g in groups.items():
        strength[_status(g.get("ad_strength")) or "unknown"] = strength.get(_status(g.get("ad_strength")) or "unknown", 0) + 1
    for key in sorted(groups):
        chk.observe(f"Group {key[0]}/{key[1]} associations by field type and approval (descriptive)",
                    campaign_id=key[0], asset_group_id=key[1], associations=counts.get(key, {}),
                    ad_strength=groups[key].get("ad_strength"))
    chk.observe("Ad Strength distribution (descriptive; creative quality owned by 162, video by 093)",
                distribution=dict(sorted(strength.items())), groups=len(groups))


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   Critical outcomes (material_intended_blocked, material_block) require proposal.evidence_ref equal to one
             of item.evidence.evidence_refs (the reviewed group's supplied rows/window); unknown or other-group refs
             are rejected. Warning structural outcomes need proposal {old_intended_keys, new_intended_keys,
             protected_inventory} with new keys in the feed and every business-critical offer protected.
    """
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome in ("material_intended_blocked", "material_block"):
        ref = str(proposal.get("evidence_ref") or "").strip()
        if not ref:
            return [f"{outcome} needs proposal.evidence_ref"]
        allowed = sorted((item.evidence or {}).get("evidence_refs") or [])
        return [] if ref in allowed else [f"evidence_ref {ref} not among the reviewed evidence refs {allowed}"]
    if outcome not in ("offer_contradiction", "selection_contradiction", "confirmed_not_material"):
        return []
    problems = [f"proposal.{k} required" for k in PROPOSAL_FIELDS if not proposal.get(k)]
    if problems:
        return problems
    t = ctx.table(PRODUCTS)
    feed = {str(r.get("offer_id")) for r in (t.rows if t else [])}
    new = [str(x) for x in proposal.get("new_intended_keys") or []]
    problems += [f"new intended offer {o} not in the feed snapshot" for o in new if feed and o not in feed]
    it = _intent(ctx).get((str(item.entity.get("campaign_id")), str(item.entity.get("asset_group_id")))) or {}
    critical = set(V.split_list(it.get("business_critical_inventory"), (" | ", ";", "|", ",")))
    protected = {str(x) for x in proposal.get("protected_inventory") or []}
    problems += [f"business-critical offer {o} missing from protected_inventory" for o in sorted(critical - protected)]
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
