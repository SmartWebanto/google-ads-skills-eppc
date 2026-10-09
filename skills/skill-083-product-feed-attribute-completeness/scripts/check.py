"""check.py — skill-083 deterministic product feed identifier and attribute completeness checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-083-product-feed-attribute-completeness/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #119 Disapproved Products Alerts (Nils Rooijmans public script page) — clean-room reimplementation of joining Merchant disapproved-product statuses with delivered product clicks to prioritize fixes; e-mail/sheet alerting replaced by provisional findings + ai_review
         index #70 PMax Disapproved Entities Alerts (Nils Rooijmans, reference only) — clean-room reimplementation limited to disapproved products delivered through PERFORMANCE_MAX campaigns (product_daily.campaign_id → campaigns.channel_type); asset/ad entities out of scope
         skills/skill-082-product-feed-title-optimization/scripts/check.py — same product-key, reference and diagnostics joins (title attribute issues are owned there)
rules:   Product key = (merchant_id, channel, content_language, feed_label, offer_id, target_country, destination);
         merchant_id/offer_id/target_country/destination required, absent optional parts → partial "key incomplete".
         Same key twice: identical rows dedupe, differing rows at the latest snapshot_at are a conflict and are
         excluded from per-product decisions. Other tables join on the key columns BOTH tables carry (never offer_id
         alone when target_country exists); an ambiguous projection is unresolved, never fanned out.
         Attribute value = first present column of effective_<attr>, <attr>, submitted_<attr>; empty cell = missing,
         'n/a'/'not_applicable' = explicit not-applicable, absent column = unknown (never a finding).
         GTIN cells are strings (leading zeros kept); numeric JSON cells are unresolved. Invalid = not 8/12/13/14
         ASCII digits or failed GS1 mod-10 check digit; syntax validity is never proof of ownership.
         Reference columns: verified_gtin, verified_mpn, verified_brand, identifier_assignment_status
         (unassigned|not_assigned|assigned), intended_destinations (list), evidence_reference, item_group_id and
         variant attributes color/size/material/pattern/gender/age_group under their plain names.
         Deterministic applicable_attribute_missing only when required_when ∈ {always, required, mandatory},
         exceptions empty, market/destination/category/condition all match ('*'|'all'|'any' wildcard; category
         equal or ' > ' descendant) and the processed value is empty; identifier_exists=false or other
         required_when values → ai_review. No universal checklist; product_type depth is never flagged.
         Critical only via ai_review on a CURRENT blocking attribute diagnostic; verify() demands
         proposal.evidence_ref, current diagnostics and a destination not excluded by reference intent.
         product_daily is a delivered sample: exposure only, never a catalog denominator, never savings;
         missing identifiers in an Ads report never imply missing feed attributes.
         index #116 (feed fetch trigger) refused: mutating/network collector, the Merchant snapshot is an input.
         index #118 (feed update frequency) refused: no schedule evidence in this recipe (skill-165 owns
         freshness); only the snapshot age is recorded as evidence currency.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
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

SKILL = "skill-083-product-feed-attribute-completeness"
VERSION = "1.0.0"

MP = "external/merchant_products"
MD = "external/merchant_diagnostics"
REF = "external/product_reference"
AR = "external/attribute_requirements"
PD = "custom/product_daily"
KEY_ORDER = ("merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country", "destination")
KEY_REQ = ["merchant_id", "offer_id", "target_country", "destination"]
KEY_OPT = ("channel", "content_language", "feed_label")
PRODUCT_CHANNELS = {"SHOPPING", "PERFORMANCE_MAX"}
VARIANT_ATTRS = ("color", "size", "material", "pattern", "gender", "age_group")
INV_ATTRS = ("brand", "gtin", "mpn", "identifier_exists", "condition", "google_product_category", "product_type",
             "color", "size", "gender", "age_group", "material", "pattern", "price", "availability", "link",
             "item_group_id")
NA_TOKENS = {"n/a", "na", "not_applicable", "not applicable"}
WILDCARD = {"*", "all", "any"}
STRICT_WHEN = {"always", "required", "mandatory"}
BLOCKING = {"disapproved", "not_eligible", "ineligible"}
DEMOTED = {"demoted", "limited"}
NO_ISSUE = {"no_issue", "no issue", "no issues", "none"}
UNASSIGNED = {"unassigned", "not_assigned"}
GTIN_LENGTHS = (8, 12, 13, 14)
# feed attribute, reference column, severity when the feed lacks a verified reference value
REF_PAIRS = (("gtin", "verified_gtin", "Warning"), ("mpn", "verified_mpn", "Info"), ("brand", "verified_brand", "Info"),
             ("item_group_id", "item_group_id", "Info")) + tuple((a, a, "Info") for a in VARIANT_ATTRS)
AR_COLS = ["market", "destination", "category", "condition", "attribute", "required_when", "exceptions",
           "source_url", "checked_at"]
MD_COLS = ["offer_id", "target_country", "destination", "issue_code", "attribute", "eligibility_status", "observed_at"]
PD_COLS = ["campaign_id", "offer_id", "date", "clicks", "cost"]
CHECKS = (("catalog_inventory", "Scoped catalog inventory and deduplicated product key"),
          ("identifier_syntax", "GTIN format, check digit and variant correspondence"),
          ("reference_match", "Feed identifiers and variant facts versus verified catalog"),
          ("requirement_applicability", "Applicable required attributes per market, destination and category"),
          ("attribute_coverage", "Populated / applicable coverage per attribute, category and destination"),
          ("diagnostic_blockers", "Current attribute-related Merchant diagnostics"),
          ("product_prioritization", "Delivered-product exposure (optional prioritization sample)"))


# ---------------------------------------------------------------- helpers (private; mirrored in skill-082)
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


def _window(ctx) -> str:
    return f"{ctx.period_start}..{ctx.period_end}"


def _pick(row: dict, cols, attr: str) -> tuple[str | None, str | None, str]:
    """(value, column, state) with state populated|missing|not_applicable|absent."""
    for c in (f"effective_{attr}", attr, f"submitted_{attr}"):
        if c in cols:
            raw = _s(row.get(c))
            if not raw:
                return None, c, "missing"
            if raw.lower() in NA_TOKENS:
                return raw, c, "not_applicable"
            return raw, c, "populated"
    return None, None, "absent"


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


def _catalog(ctx, chk) -> tuple[dict, list[str], int]:
    """Deduplicated catalog {key: row}. Rules: identical duplicates collapse; conflicting duplicates are excluded and counted, never merged."""
    t = ctx.table(MP)
    absent = [c for c in KEY_OPT if c not in t.columns]
    if absent:
        chk.partial("product key incomplete: rows from different channels/languages/feed labels may share a key",
                    [f"{MP}:{c}" for c in absent])
    grouped: dict[tuple, list[dict]] = {}
    bad = 0
    for r in t.rows:
        k = _key(r)
        if not all(_s(r.get(c)) for c in KEY_REQ):
            bad += 1
            continue
        grouped.setdefault(k, []).append(r)
    cat, conflicts, dupes = {}, [], 0
    for k in sorted(grouped):
        rows = grouped[k]
        latest = max(_s(r.get("snapshot_at")) for r in rows)
        top = {tuple(sorted((a, _s(b)) for a, b in r.items())): r for r in rows if _s(r.get("snapshot_at")) == latest}
        if len(top) > 1:
            conflicts.append(k)
            continue
        dupes += len(rows) - 1
        cat[k] = next(iter(top.values()))
    if bad:
        chk.partial(f"{bad} merchant_products rows lack a required key part; excluded")
    if conflicts:
        chk.partial(f"{len(conflicts)} product keys have conflicting rows at the same snapshot; excluded from decisions")
    return cat, t.columns, dupes


def _units(cat: dict) -> dict:
    """Product unit (key without destination) → sorted destination keys."""
    out: dict[tuple, list[tuple]] = {}
    for k in sorted(cat):
        out.setdefault(k[:-1], []).append(k)
    return out


def _ref_index(ctx, mp_cols) -> tuple[dict, list[str] | None]:
    """Reference rows by the key columns shared with merchant_products; shared None = join impossible."""
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


def _feed_snapshot(ctx, cat) -> tuple:
    dates = sorted({d for d in (V.parse_date(r.get("snapshot_at")) for r in cat.values()) if d})
    return (dates[-1] if dates else ctx.snapshot), dates


def _delivery(ctx) -> tuple[dict, list[str], dict]:
    """Aggregate product_daily inside the report window by the key columns it carries."""
    t = ctx.table(PD)
    cols = [c for c in KEY_ORDER if c in t.columns]
    agg: dict[tuple, dict] = {}
    seen: set = set()
    stats = {"rows": len(t.rows), "outside_window": 0, "duplicate_grain": 0, "no_offer_id": 0, "unknown_metrics": 0}
    for r in t.rows:
        d = V.parse_date(r.get("date"))
        if d is None or (ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end):
            stats["outside_window"] += 1
            continue
        proj = tuple(_s(r.get(c)) for c in cols)
        grain = (_s(r.get("campaign_id")), proj, d)
        if grain in seen:
            stats["duplicate_grain"] += 1
            continue
        seen.add(grain)
        if not _s(r.get("offer_id")):
            stats["no_offer_id"] += 1
            continue
        a = agg.setdefault(proj, {"clicks": 0.0, "cost": 0.0, "impressions": 0.0, "campaigns": set(),
                                  "unknown_rows": 0})
        a["campaigns"].add(_s(r.get("campaign_id")))
        clicks, cost = V.num(r.get("clicks")), ctx.money(r.get("cost"))
        if clicks is None or cost is None:
            a["unknown_rows"] += 1
            stats["unknown_metrics"] += 1
            continue
        a["clicks"] += clicks
        a["cost"] += cost
        a["impressions"] += V.num(r.get("impressions")) or 0.0
    return agg, cols, stats


def _channels(ctx) -> dict:
    return {_s(r.get("id") or r.get("campaign_id")): _s(r.get("channel_type")).upper() for r in ctx.rows("campaigns")}


def _gtin_problem(g: str) -> str | None:
    if not (g.isascii() and g.isdigit()):
        return "non-digit characters"
    if len(g) not in GTIN_LENGTHS:
        return f"length {len(g)} not in {GTIN_LENGTHS}"
    body, check = [int(c) for c in g[:-1]], int(g[-1])
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    expected = (10 - total % 10) % 10
    return None if expected == check else f"check digit {check} != expected {expected}"


def _norm_id(attr: str, v: str) -> str:
    if attr == "gtin" and v.isascii() and v.isdigit():
        return v.zfill(14)
    return _low(v)


def _match(rule, value) -> bool | None:
    r = _low(rule)
    if not r:
        return None
    if r in WILDCARD:
        return True
    v = _low(value)
    return None if not v else r == v


def _cat_match(rule, cat) -> bool | None:
    r = _low(rule)
    if not r:
        return None
    if r in WILDCARD:
        return True
    c = _low(cat)
    if not c:
        return None
    return c == r or c.startswith(r + " > ")


# ---------------------------------------------------------------- run
def run(ctx) -> None:
    """Run feed inventory, GTIN syntax, reference, requirement, coverage, diagnostic and prioritization checks.

    Rules:   Not applicable when a complete campaigns inventory has no SHOPPING/PERFORMANCE_MAX; unknown scope →
             partial. Deterministic applicable_attribute_missing only for always/required/mandatory rows matching
             market/destination/ category/condition; other cases are ai_review; absent columns are unknown, never
             findings. Critical only via ai_review on a current blocking diagnostic; product_daily is exposure only,
             never a denominator.
    """
    applicable, why = _applicability(ctx)
    if applicable is False:
        for cid, title in CHECKS:
            ctx.check(cid, title, applicable=False, na_reason=why)
        return
    mp_needs = {MP: KEY_REQ}
    inv = ctx.check(*CHECKS[0], mp_needs)
    cat, cols, dupes = {}, [], 0
    if applicable is None:
        inv.partial(why, ["campaigns:channel_type"])
    if inv.runnable:
        cat, cols, dupes = _catalog(ctx, inv)
        _inventory(ctx, inv, cat, cols, dupes)
    _identifier_syntax(ctx, ctx.check(*CHECKS[1], {MP: KEY_REQ + ["gtin"]}), cat, cols)
    _reference_match(ctx, ctx.check(*CHECKS[2], {MP: KEY_REQ, REF: ["offer_id", "target_country",
                                                                    "evidence_reference"]}), cat, cols)
    req = ctx.check(*CHECKS[3], {MP: KEY_REQ, AR: AR_COLS})
    covg = ctx.check(*CHECKS[4], {MP: KEY_REQ, AR: AR_COLS})
    if req.runnable:
        _requirements(ctx, req, covg, cat, cols)
    _diagnostics(ctx, ctx.check(*CHECKS[5], {MD: MD_COLS}), cat, cols)
    _prioritization(ctx, ctx.check(*CHECKS[6], {PD: PD_COLS}), cat)


def _inventory(ctx, chk, cat, cols, dupes) -> None:
    units = _units(cat)
    snap, dates = _feed_snapshot(ctx, cat)
    if "snapshot_at" not in cols:
        chk.partial("merchant_products snapshot time unknown", [f"{MP}:snapshot_at"])
    elif len(dates) > 1:
        chk.partial(f"mixed Merchant snapshots {dates[0]}..{dates[-1]}; attribute states may not be simultaneous")
    complete = ctx.table(MP).complete is True
    scopes: dict[tuple, set] = {}
    for k in cat:
        scopes.setdefault((k[5], k[6]), set()).add(k[4])
    states = {}
    for attr in INV_ATTRS:
        counts = {"populated": 0, "missing": 0, "not_applicable": 0, "absent": 0, "submitted_not_processed": 0}
        for k in sorted(cat):
            row = cat[k]
            _, col, state = _pick(row, cols, attr)
            counts[state] += 1
            if col == f"effective_{attr}" and state == "missing" and _s(row.get(f"submitted_{attr}")):
                counts["submitted_not_processed"] += 1
        states[attr] = counts
    unresolved_ids = sum(1 for k in cat if _pick(cat[k], cols, "gtin")[2] in ("missing", "absent")
                         and V.boolean(cat[k].get("identifier_exists")) is None)
    chk.observe("Catalog inventory (deduplicated product keys)",
                destination_rows=len(cat), unique_products=len(units), identical_duplicate_rows=dupes,
                offers_per_scope={f"{c}/{d}": len(v) for (c, d), v in sorted(scopes.items())},
                attribute_states=states, unresolved_identifier_assignments=unresolved_ids,
                catalog_complete=complete,
                denominator="complete catalog" if complete else "supplied product sample only; no catalog percentages",
                feed_snapshot=snap, account_snapshot=ctx.snapshot,
                feed_snapshot_age_days=(ctx.snapshot - snap).days if ctx.snapshot and snap else None)


def _identifier_syntax(ctx, chk, cat, cols) -> None:
    if not chk.runnable:
        return
    units = _units(cat)
    checked = invalid = unresolved = 0
    by_gtin: dict[tuple, list[tuple]] = {}
    for u in sorted(units):
        rows = [cat[k] for k in units[u]]
        raws = sorted({_s(r.get("gtin")) for r in rows if _s(r.get("gtin"))})
        if any(isinstance(r.get("gtin"), (int, float)) for r in rows):
            unresolved += 1
            continue
        if len(raws) > 1:
            unresolved += 1
            chk.partial(f"offer {u[4]} carries different GTINs across destinations")
            continue
        if not raws or raws[0].lower() in NA_TOKENS:
            continue
        g = raws[0]
        checked += 1
        problem = _gtin_problem(g)
        ent = _ent(u, attribute="gtin")
        if problem:
            invalid += 1
            chk.finding("invalid_gtin", "Warning", ent,
                        f"GTIN '{g}' of offer {u[4]} ({u[5]}) is not a valid GTIN: {problem}",
                        evidence={"gtin": g, "length": len(g), "destinations": [k[6] for k in units[u]],
                                  "snapshot_at": rows[0].get("snapshot_at"), "source": f"{MP}:gtin"},
                        calculation={"rule": "8/12/13/14 ASCII digits and GS1 mod-10 check digit", "problem": problem},
                        recommendation="Ask the feed owner for the manufacturer-assigned GTIN; never invent one or "
                                       "set identifier_exists=false to silence the issue.",
                        uncertainty="Syntax only; a valid GTIN still needs ownership evidence. Exporters that "
                                    "numeric-cast identifiers can strip leading zeros.")
            continue
        by_gtin.setdefault((u[0], u[5], g.zfill(14)), []).append(u)
    for (merchant, country, g14), group in sorted(by_gtin.items()):
        offers = sorted({u[4] for u in group})
        if len(offers) < 2:
            continue
        sigs = {u: {a: _low(_pick(cat[units[u][0]], cols, a)[0]) for a in VARIANT_ATTRS
                    if _pick(cat[units[u][0]], cols, a)[2] == "populated"} for u in group}
        differing = sorted({a for x in group for y in group for a in VARIANT_ATTRS
                            if a in sigs[x] and a in sigs[y] and sigs[x][a] != sigs[y][a]})
        if not differing:
            chk.observe("Same GTIN on several offers without a known variant difference (possible duplicate listing)",
                        merchant_id=merchant, target_country=country, gtin=g14, offer_ids=offers)
            continue
        chk.finding("gtin_shared_across_variants", "Warning",
                    {"merchant_id": merchant, "target_country": country, "gtin": g14, "offer_ids": offers},
                    f"GTIN {g14} is used by {len(offers)} offers in {country} that differ in {', '.join(differing)}",
                    evidence={"variant_values": {u[4]: sigs[u] for u in sorted(group)}, "source": f"{MP}:gtin"},
                    calculation={"offers": len(offers), "differing_attributes": differing},
                    recommendation="Ask the feed owner for each variant's own manufacturer GTIN; do not copy "
                                   "identifiers between variants.",
                    uncertainty="Variant values come from the feed; the correct GTIN per variant needs catalog evidence.")
    chk.observe("GTIN syntax screened", unique_products=len(units), gtins_checked=checked, invalid=invalid,
                unresolved=unresolved)


def _reference_match(ctx, chk, cat, cols) -> None:
    if not chk.runnable:
        return
    ref_cols = ctx.table(REF).columns
    pairs = [p for p in REF_PAIRS if p[1] in ref_cols and (p[0] in cols or f"effective_{p[0]}" in cols
                                                         or f"submitted_{p[0]}" in cols)]
    if not pairs:
        chk.partial("no comparable verified identifier or variant columns",
                    [f"{REF}:verified_gtin", f"{REF}:verified_mpn", f"{REF}:verified_brand"])
    idx, shared = _ref_index(ctx, cols)
    units = _units(cat)
    status = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    warnings = 0
    for u in sorted(units):
        row = cat[units[u][0]]
        ref, st = _ref_row(idx, shared, units[u][0])
        status[st] += 1
        if ref is None:
            continue
        eref = ref.get("evidence_reference")
        ident = V.boolean(row.get("identifier_exists"))
        assign = _low(ref.get("identifier_assignment_status"))
        for attr, rcol, absent_sev in pairs:
            fv, fcol, fstate = _pick(row, cols, attr)
            rv = _s(ref.get(rcol))
            if not rv or rv.lower() in NA_TOKENS or fstate == "absent":
                continue
            ent = _ent(u, attribute=attr)
            ev = {"feed_value": fv, "feed_column": fcol, "verified_value": rv, "reference_column": f"{REF}:{rcol}",
                  "evidence_reference": eref, "reference_updated_at": ref.get("updated_at"),
                  "destinations": [k[6] for k in units[u]]}
            if fstate == "populated" and _norm_id(attr, fv) != _norm_id(attr, rv):
                warnings += 1
                chk.finding("source_to_feed_mismatch", "Warning", ent,
                            f"Offer {u[4]} ({u[5]}) {attr} '{fv}' differs from verified catalog value '{rv}'",
                            evidence=ev, calculation={"comparison": "normalized equality", "equal": False},
                            recommendation="Ask the feed owner to correct the source value and re-check the "
                                           "processed feed and diagnostics after the next processing.",
                            uncertainty="Catalog value is authoritative only as of reference_updated_at.")
            elif fstate in ("missing", "not_applicable"):
                if attr == "gtin" and ident is False:
                    chk.finding("identifier_exists_false_with_assigned_gtin", "Warning", ent,
                                f"Offer {u[4]} ({u[5]}) sets identifier_exists=false although the catalog verifies "
                                f"GTIN {rv}", evidence=ev,
                                recommendation="Submit the verified GTIN and remove identifier_exists=false.",
                                uncertainty="Assignment evidence comes from the client catalog.")
                    continue
                warnings += 1 if absent_sev == "Warning" else 0
                chk.finding("verified_value_absent_in_feed", absent_sev, ent,
                            f"Offer {u[4]} ({u[5]}) has no processed {attr} although the catalog verifies '{rv}'",
                            evidence=ev,
                            recommendation="Ask the feed owner to submit the verified value." if absent_sev == "Warning"
                            else "Optional enrichment: submit the verified value if it applies to the destination.",
                            uncertainty="Applicability of non-identifier attributes depends on the requirement matrix.")
        if assign in UNASSIGNED and _pick(row, cols, "gtin")[2] in ("missing", "not_applicable") \
                and not _s(ref.get("verified_gtin")):
            chk.finding("identifier_legitimately_unassigned", "Info", _ent(u, attribute="gtin"),
                        f"Offer {u[4]} ({u[5]}) has no GTIN and the catalog records no assigned GTIN",
                        evidence={"identifier_assignment_status": ref.get("identifier_assignment_status"),
                                  "identifier_exists": row.get("identifier_exists"), "evidence_reference": eref},
                        recommendation="No GTIN change; keep brand/MPN per the product circumstances.",
                        uncertainty="Relies on the client catalog assignment record.")
    if status["ambiguous"] or status["unmatched"]:
        chk.partial(f"{status['unmatched']} products without and {status['ambiguous']} with ambiguous catalog "
                    f"reference rows (joined on {', '.join(shared)}); no correctness judgment for them")
    chk.observe("Feed values compared with verified catalog", join_columns=shared, joins=status,
                compared_attributes=[p[0] for p in pairs], warnings=warnings)


def _requirements(ctx, req, covg, cat, cols) -> None:
    ref_idx, ref_shared = _ref_index(ctx, cols)
    rows = sorted(ctx.rows(AR), key=lambda r: tuple(_low(r.get(c)) for c in AR_COLS[:5]))
    stats = {}
    complete = ctx.table(MP).complete is True
    total_unresolved = 0
    for r in rows:
        attr = _low(r.get("attribute")).replace(" ", "_")
        if not attr:
            req.partial("requirement row without attribute ignored")
            continue
        when, exc = _low(r.get("required_when")), _low(r.get("exceptions"))
        strict = when in STRICT_WHEN and exc in ("", "none", "-")
        scope = {c: r.get(c) for c in ("market", "destination", "category", "condition")}
        s = {"applicable": 0, "populated": 0, "missing": 0, "exempt": 0, "unresolved": 0}
        review_keys = []
        for k in sorted(cat):
            row = cat[k]
            m, d = _match(r.get("market"), k[5]), _match(r.get("destination"), k[6])
            if m is False or d is False:
                continue
            c = _cat_match(r.get("category"), _pick(row, cols, "google_product_category")[0])
            cond = _match(r.get("condition"), _pick(row, cols, "condition")[0])
            if c is False or cond is False:
                continue
            if None in (m, d, c, cond):
                s["unresolved"] += 1
                continue
            s["applicable"] += 1
            val, col, state = _pick(row, cols, attr)
            if state == "absent":
                s["unresolved"] += 1
                continue
            if state == "populated":
                s["populated"] += 1
                continue
            ref, _ = _ref_row(ref_idx, ref_shared, k)
            if attr == "gtin" and ref is not None and _low(ref.get("identifier_assignment_status")) in UNASSIGNED:
                s["exempt"] += 1
                continue
            if state == "not_applicable":
                s["exempt"] += 1
            else:
                s["missing"] += 1
            idf = V.boolean(row.get("identifier_exists"))
            if strict and state == "missing" and not (attr in ("gtin", "mpn", "brand") and idf is False):
                req.finding("applicable_attribute_missing", "Warning", _ent(k, attribute=attr),
                            f"Offer {k[4]} ({k[5]}/{k[6]}) lacks required {attr} "
                            f"({r.get('required_when')}, no exceptions)",
                            evidence={"column": col, "requirement": scope, "required_when": r.get("required_when"),
                                      "source_url": r.get("source_url"), "checked_at": r.get("checked_at"),
                                      "accepted_format": r.get("accepted_format"),
                                      "product_category": _pick(row, cols, "google_product_category")[0]},
                            recommendation="Ask the feed owner for the verified value; re-check the processed feed "
                                           "and diagnostics afterwards.",
                            uncertainty="Requirement matrix is valid as of checked_at; no material blockage established.")
            else:
                review_keys.append(k)
        if review_keys:
            req.review("requirement_applicability", {"market": r.get("market"), "destination": r.get("destination"),
                                                     "category": r.get("category"), "condition": r.get("condition"),
                                                     "attribute": attr},
                       f"Does the requirement '{attr}' ({r.get('required_when')}; exceptions: {r.get('exceptions')}) "
                       f"apply to these {len(review_keys)} products without a processed value?",
                       evidence={"product_keys": [_ent(k) for k in review_keys],
                                 "identifier_exists": {k[4]: cat[k].get("identifier_exists") for k in review_keys},
                                 "source_url": r.get("source_url"), "checked_at": r.get("checked_at"),
                                 "accepted_format": r.get("accepted_format")},
                       outcomes={"applicable_missing": {"severity": "Warning", "recommendation":
                                                        "Ask the feed owner for the verified values."},
                                 "not_applicable": {"severity": None, "recommendation":
                                                    "Record the exemption with its product circumstance."},
                                 "uncertain": {"severity": "Info", "recommendation":
                                               "Request manufacturer/catalog evidence before changing the feed."}},
                       guidance="Use only the requirement text, exceptions and product facts; GTIN may legitimately "
                                "be unassigned and identifier_exists=false needs assignment evidence.")
        total_unresolved += s["unresolved"]
        stats[f"{attr} | {r.get('market')} | {r.get('destination')} | {r.get('category')} | {r.get('condition')}"] = s
    if total_unresolved:
        req.partial(f"{total_unresolved} product/requirement pairs unresolved (unknown category, condition, "
                    f"market/destination rule or attribute column)")
    req.observe("Requirement rows evaluated", requirements=len(rows), products=len(cat))
    if covg.runnable:
        for label, s in stats.items():
            covg.observe("Attribute coverage per requirement scope", scope=label, **s,
                         populated_share=V.ratio(s["populated"], s["applicable"] - s["exempt"]) if complete else None)
        if not complete:
            covg.partial("catalog completeness not certified: counts describe the supplied sample, no percentages")
        if total_unresolved:
            covg.partial(f"{total_unresolved} product/requirement pairs unresolved")


def _diagnostics(ctx, chk, cat, cols) -> None:
    if not chk.runnable:
        return
    t = ctx.table(MD)
    snap, _ = _feed_snapshot(ctx, cat)
    if ctx.table(MP) is None:
        chk.partial("merchant_products absent: diagnostic coverage per product unknown", [f"{MP} (file)"])
    ref_idx, ref_shared = _ref_index(ctx, cols)
    md_key = [c for c in KEY_ORDER if c in t.columns]
    by_md: dict[tuple, list[tuple]] = {}
    for k in cat:
        by_md.setdefault(_proj(k, md_key), []).append(k)
    delivery = _delivery(ctx) if ctx.table(PD) is not None and not ctx.table(PD).missing(PD_COLS) else None
    channels = _channels(ctx)
    exp_idx: dict[tuple, list[dict]] = {}
    exp_shared: list[str] = []
    if delivery:
        agg, pcols, _ = delivery
        exp_shared = [c for c in pcols if c in md_key]
        for p, a in agg.items():
            exp_idx.setdefault(tuple(p[pcols.index(c)] for c in exp_shared), []).append(a)
    covered, no_issue, delegated, non_attr = set(), 0, 0, 0
    counts = {"blocking": 0, "demoted": 0, "notice": 0}
    for r in sorted(t.rows, key=lambda r: (tuple(_s(r.get(c)) for c in md_key), _s(r.get("issue_code")))):
        proj = tuple(_s(r.get(c)) for c in md_key)
        covered.add(proj)
        code = _low(r.get("issue_code"))
        if not code or code in NO_ISSUE:
            no_issue += 1
            continue
        attr = _low(r.get("attribute")).replace(" ", "_")
        if not attr or attr in NA_TOKENS:
            non_attr += 1
            continue
        if attr == "title":
            delegated += 1
            continue
        status = {_low(r.get("eligibility_status")), _low(r.get("platform_severity"))}
        obs = V.parse_date(r.get("observed_at"))
        current = None if obs is None or snap is None else obs >= snap
        first = V.parse_date(r.get("first_seen_at"))
        key_like = tuple(_s(r.get(c)) for c in KEY_ORDER)
        matches = by_md.get(proj, [])
        intended = None
        if ref_shared is not None and len(matches) == 1:
            ref, _ = _ref_row(ref_idx, ref_shared, matches[0])
            if ref is not None and _s(ref.get("intended_destinations")):
                intended = _low(r.get("destination")) in {_low(x) for x in
                                                          V.split_list(ref.get("intended_destinations"), (";", "|", ","))}
        exposure = None
        if delivery:
            hits = exp_idx.get(tuple(_s(r.get(c)) for c in exp_shared), [])
            camps = sorted({c for a in hits for c in a["campaigns"]})
            exposure = {"clicks": sum(a["clicks"] for a in hits), "cost_exposure": sum(a["cost"] for a in hits),
                        "campaign_ids": camps, "pmax_campaign_ids": [c for c in camps
                                                                     if channels.get(c) == "PERFORMANCE_MAX"],
                        "join_columns": exp_shared, "window": _window(ctx), "currency": ctx.currency}
        ent = {**_ent(key_like), "issue_code": r.get("issue_code"), "attribute": attr}
        ev = {"eligibility_status": r.get("eligibility_status"), "platform_severity": r.get("platform_severity"),
              "issue_text": r.get("issue_text"), "observed_at": r.get("observed_at"),
              "first_seen_at": r.get("first_seen_at"), "feed_snapshot": snap, "current": current,
              "age_days": (obs - first).days if obs and first else None, "intended_destination": intended,
              "source_reference": r.get("source_reference"), "delivered_exposure": exposure}
        if status & BLOCKING:
            counts["blocking"] += 1
            base = "Warning" if current else "Info"
            prov = chk.finding("attribute_disapproval", base, ent,
                               f"Offer {ent.get('offer_id')} ({ent.get('target_country')}/{ent.get('destination')}) "
                               f"is {r.get('eligibility_status') or r.get('platform_severity')} for {attr} "
                               f"({r.get('issue_code')})",
                               evidence=ev,
                               recommendation="Ask the feed owner for a verified correction, then re-check the "
                                              "processed feed and diagnostics; never edit the feed automatically.",
                               uncertainty="Materiality of the blocked product is a business judgment; delivered "
                                           "exposure is historical, not lost revenue."
                                           + ("" if current else " Diagnostic is not current at the feed snapshot."))
            chk.review("attribute_disapproval", ent,
                       f"Does this {attr} disapproval block delivery of a materially important product in an "
                       f"intended destination?", evidence=ev,
                       outcomes={"material_intended_delivery_blocked": {"severity": "Critical", "recommendation":
                                 "Prioritize the verified correction; cite the materiality evidence."},
                                 "not_material": {"severity": base, "recommendation": "Correct in normal feed hygiene."},
                                 "uncertain": {"severity": base, "recommendation":
                                               "Ask the client for product importance and intended destinations."}},
                       guidance="Critical needs a current diagnostic, an intended destination and proposal.evidence_ref "
                                "to business-importance evidence; delivered clicks alone do not prove materiality.",
                       provisional=prov)
        elif status & DEMOTED and current:
            counts["demoted"] += 1
            chk.finding("attribute_diagnostic_issue", "Warning", ent,
                        f"Offer {ent.get('offer_id')} is demoted for {attr} ({r.get('issue_code')})", evidence=ev,
                        recommendation="Ask the feed owner for a verified correction and a later diagnostic check.",
                        uncertainty="Demotion limits but does not block delivery; no material blockage established.")
        else:
            counts["notice"] += 1
            chk.finding("attribute_diagnostic_notice", "Info", ent,
                        f"Offer {ent.get('offer_id')} has a non-blocking {attr} notice ({r.get('issue_code')})",
                        evidence=ev, recommendation="Optional enrichment; verify against catalog facts first.",
                        uncertainty="Non-blocking or non-current platform notice.")
    lacking = sorted({_proj(k, md_key) for k in cat} - covered)
    if lacking:
        chk.partial(f"{len(lacking)} catalog products have no diagnostics row (issue or explicit no-issue); "
                    f"absence of issue rows is not approval")
    chk.observe("Merchant diagnostics screened", rows=len(t.rows), no_issue_rows=no_issue, **counts,
                title_issues_delegated_to_082=delegated, non_attribute_issues_not_owned=non_attr,
                products_without_diagnostics=len(lacking), feed_snapshot=snap,
                delivered_exposure_available=delivery is not None)


def _prioritization(ctx, chk, cat) -> None:
    if not chk.runnable:
        return
    agg, pcols, stats = _delivery(ctx)
    if "target_country" not in pcols:
        chk.partial("product_daily key incomplete: offers are not separated by target_country",
                    [f"{PD}:target_country"])
    if ctx.table(MP) is None:
        chk.partial("merchant_products absent: delivered offers cannot be matched to the catalog", [f"{MP} (file)"])
    matched = unmatched = None
    if ctx.table(MP) is not None:
        matched = unmatched = 0
        shared = [c for c in pcols if c in ctx.table(MP).columns]
        projections = {_proj(k, shared) for k in cat}
        for p in agg:
            if tuple(p[pcols.index(c)] for c in shared) in projections:
                matched += 1
            else:
                unmatched += 1
        if unmatched:
            chk.partial(f"{unmatched} delivered offers not found in the catalog snapshot")
    if stats["duplicate_grain"] or stats["unknown_metrics"]:
        chk.partial(f"{stats['duplicate_grain']} duplicate rows skipped, {stats['unknown_metrics']} rows with "
                    f"unknown clicks/cost")
    channels = _channels(ctx)
    top = sorted(agg.items(), key=lambda kv: (-kv[1]["cost"], kv[0]))[:10]
    chk.observe("Delivered-product exposure (historical sample, not a catalog denominator)",
                window=_window(ctx), currency=ctx.currency, mature=ctx.mature, maturity_note=ctx.maturity_note,
                key_columns=pcols, offers=len(agg), rows=stats["rows"], outside_window=stats["outside_window"],
                rows_without_offer_id=stats["no_offer_id"], matched_to_catalog=matched,
                unmatched_to_catalog=unmatched,
                clicks=sum(a["clicks"] for a in agg.values()), cost_exposure=sum(a["cost"] for a in agg.values()),
                top_offers_by_cost=[{**dict(zip(pcols, p)), "clicks": a["clicks"], "cost_exposure": a["cost"],
                                     "channels": sorted({channels.get(c) or "unknown" for c in a["campaigns"]})}
                                    for p, a in top])


# ---------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: a Critical outcome needs proposal.evidence_ref, a current diagnostic and no reference evidence that
    the destination is unintended."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") != "Critical":
        return []
    problems = []
    if not _s((decision.get("proposal") or {}).get("evidence_ref")):
        problems.append("Critical needs proposal.evidence_ref pointing at supplied business-importance evidence")
    if item.evidence.get("current") is not True:
        problems.append("diagnostic is not current at the Merchant snapshot; Critical not allowed")
    if item.evidence.get("intended_destination") is False:
        problems.append("catalog reference lists this destination as not intended; Critical not allowed")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
