"""check.py — skill-016 deterministic negative-coverage governance: intent × campaign × effective protection.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
         upload_scope(ctx, level, cid, gid, lid) -> (list|None, str) | upload_conflicts(ctx, text, match, scope) -> (dict, list[str])
used_by: skills/skill-016-negative-keyword-list-completeness/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #54 Master Negative List (developers.google.com) — clean-room reimplementation of "a master list
         must be attached to its declared campaigns" as profile.master_negative_lists {list_id: [campaign_ids]};
         a missing association is Info, never an automatic sync
         index #59 Add negatives from Google Sheet to Campaigns in multiple accounts (Optmyzr) — PARTIALLY integrated:
         clean-room read-only pre-upload validation of a supplied external/negative_upload_list (check
         negative_upload_validation: match type, active target, duplicates, keyword/converting-query/brand
         blocks per account); the sheet read and the cross-account push itself stay refused (recommend-only)
rules:   Approved exclusions come ONLY from profile.excluded_intents; literal intent terms ONLY from
         profile.excluded_intent_terms {intent: [terms]}; campaign exceptions from profile.negative_exceptions
         {campaign_id: [intents]}. No universal waste list is hardcoded.
         Eligible campaigns: campaigns.channel_type SEARCH or SHOPPING. Protection = effective negatives
         (adsrun.negatives.effective_negatives) literally blocking the term; per campaign it is protected only
         when EVERY active ad group is protected.
         Warning 'approved_exclusion_unprotected' (deterministic) needs: approved intent with literal terms,
         term not protected in the campaign, and unblocked observed queries containing the term (PHRASE literal)
         whose summed cost >= spend_floor(campaign). Intents without terms go to a batch AI review whose
         Warning outcome verify() re-checks (listed queries in batch, cost >= floor, approved intent).
         Final new-negative recommendations are consolidated under 014; proposals are verified against
         converting queries, active keyword texts and brand terms in every proposed campaign.
         negative_upload_validation is opt-in: runs only when external/negative_upload_list is supplied; rows
         whose customer_id differs from this account are ignored (multi-account partitioning is adsrun's).
         Upload-row Warnings only for a literal block (adsrun.negatives.blocks True) of an ENABLED keyword text,
         a converting (conversions > 0) reported query or a profile.brand_terms term in the row's scope;
         invalid/missing-target/duplicate rows are Info; operators, > 10 words or blocks() None → partial.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx059 | opt-in negative_upload_validation (index #59)
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | upload scope fails closed on incomplete ad-group inventory
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

SKILL = "skill-016-negative-keyword-list-completeness"
VERSION = "1.1.0"

INV = {"negative_keywords": ["text", "match_type", "level", "campaign_id"], "shared_negative_lists": ["list_id"],
       "ad_groups": ["id", "campaign_id"]}
QUERIES = {"search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]}
ELIGIBLE = ("SEARCH", "SHOPPING")
UPLOAD = "external/negative_upload_list"
UPLOAD_NEEDS = {UPLOAD: ["campaign_id", "level", "text", "match_type"], "campaigns": ["id", "status"],
                "ad_groups": ["id", "campaign_id", "status"]}
UPLOAD_LEVELS = ("campaign", "ad_group", "shared_list")
MAX_NEGATIVE_WORDS = 10
_UPLOAD_OPERATOR = re.compile(r'[+\[\]"]|(?:^|\s)-')
_MEMBER = re.compile(r"^(?P<text>.+?)\s*\((?P<match>EXACT|PHRASE|BROAD)\)$", re.IGNORECASE)
REMOVED = ("REMOVED", "DELETED")


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion maturity",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature,
              conversion_date_basis=ctx.account.get("conversion_date_basis"))


def _by_key(mapping, key):
    return next((v for k, v in (mapping or {}).items() if str(k) == str(key)), None) if isinstance(mapping, dict) else None


def _applied(r, cols) -> list[str]:
    return V.split_list(r.get("campaigns_applied") if "campaigns_applied" in cols else r.get("campaign_ids"),
                        (";", "|", ","))


def _conflicts(ctx, text: str, match: str, cid: str) -> list[str]:
    out = []
    for r in ctx.rows("search_terms"):
        if str(r.get("campaign_id")) == cid and (V.num(r.get("conversions")) or 0) > 0 and blocks(text, match, r.get("search_term")):
            out.append(f"campaign {cid}: would block converting query '{r.get('search_term')}'")
    for k in ctx.rows("keywords"):
        if str(k.get("campaign_id")) == cid and str(k.get("status") or "").upper() in ("ENABLED", "") \
                and blocks(text, match, k.get("text")):
            out.append(f"campaign {cid}: would block keyword text '{k.get('text')}' ({k.get('id')})")
    policy = str((_by_key(ctx.profile.get("campaign_objectives"), cid) or {}).get("brand_policy") or "")
    if policy != "nonbrand_only":
        for b in ctx.profile.get("brand_terms") or []:
            if blocks(text, match, b):
                out.append(f"campaign {cid}: would block brand term '{b}'")
    return out


def run(ctx) -> None:
    """Run approved-exclusion protection, shared-list and brand-collision checks for SEARCH/SHOPPING campaigns.

    Rules:   Intents/terms/exceptions only from profile (excluded_intents, excluded_intent_terms, negative_exceptions);
             no hardcoded waste list. Warning approved_exclusion_unprotected only when unblocked query cost >=
             spend_floor of that campaign; intents without terms → batch ai_review (Warning outcome re-checked by
             verify()). Unattached/master-list gaps and brand collisions are Info; new negatives are consolidated under
             skill-014. Opt-in negative_upload_validation (only with external/negative_upload_list) validates rows
             without uploading: literal blocks of active keywords/converting queries/brand terms are Warning.
    """
    _scope(ctx)
    intents = [str(i) for i in ctx.profile.get("excluded_intents") or [] if i]
    terms_map = {str(k): [str(t) for t in v or [] if t] for k, v in (ctx.profile.get("excluded_intent_terms") or {}).items()}
    exceptions = ctx.profile.get("negative_exceptions") or {}
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    eligible = sorted(cid for cid, c in camps.items() if str(c.get("channel_type") or "").upper() in ELIGIBLE
                      and str(c.get("status") or "").upper() not in ("REMOVED",))

    def applies(cid, intent):
        return intent not in [str(x) for x in (_by_key(exceptions, cid) or [])]

    # step 2 — intent matrix
    im = ctx.check("intent_matrix", "Approved exclusion intents per eligible campaign", {"campaigns": ["id", "channel_type"]})
    if im.runnable:
        if not intents:
            im.skip("no approved exclusions: completeness verdict impossible", ["profile.excluded_intents"])
        else:
            no_terms = [i for i in intents if not terms_map.get(i)]
            if no_terms:
                im.partial(f"intents without literal terms (profile.excluded_intent_terms): {no_terms}")
            im.observe("Exclusion-intent matrix", intents=intents, eligible_campaigns=eligible,
                       exceptions={cid: _by_key(exceptions, cid) for cid in eligible if _by_key(exceptions, cid)},
                       terms={i: terms_map.get(i, []) for i in intents})

    # step 3 — brand before competitor
    bc = ctx.check("brand_competitor", "Brand terms precede competitor terms; collisions reviewed")
    brand = [str(b) for b in ctx.profile.get("brand_terms") or [] if b]
    comp = [str(c) for c in ctx.profile.get("competitor_terms") or [] if c]
    if not brand:
        bc.skip("profile.brand_terms missing: brand precedence not evaluable", ["profile.brand_terms"])
    else:
        collisions = sorted({(b, t, src) for b in brand for src, ts in (("competitor_terms", comp),
                             *((f"excluded_intent_terms[{i}]", terms_map.get(i, [])) for i in intents))
                             for t in ts if blocks(t, "PHRASE", b) or blocks(b, "PHRASE", t)})
        for b, t, src in collisions:
            bc.review("brand_term_collision", {"brand_term": b, "term": t, "source": src},
                      f"'{t}' ({src}) collides with brand term '{b}'. Which campaigns may exclude it?",
                      evidence={"brand_terms": brand, "competitor_terms": comp},
                      outcomes={"needs_owner_exception": {"severity": "Info", "recommendation":
                                                          "Scope exclusions per campaign; never a blanket account negative."},
                                "no_conflict": {"severity": None, "recommendation": "No action."}},
                      guidance="Brand precedence: brand queries stay eligible where the brand policy allows.")
        bc.observe("Brand/competitor precedence", brand_terms=brand, competitor_terms=comp, collisions=len(collisions))

    # step 4 — inventory
    inv = ctx.check("negative_inventory", "Campaign, ad-group, account and attached shared negatives", INV)
    scopes: dict = {}
    if inv.runnable:
        scopes, gaps = effective_negatives(ctx)
        for g in gaps:
            inv.partial(g)
        lists = ctx.table("shared_negative_lists")
        for r in sorted(lists.rows, key=lambda r: str(r.get("list_id"))):
            applied = _applied(r, lists.columns)
            if not applied:
                inv.finding("unattached_shared_list", "Info", {"list_id": r.get("list_id")},
                            f"Shared list {r.get('list_id')} ({r.get('name')}) is attached to no campaign",
                            evidence={"member_count": r.get("member_count")},
                            recommendation="Confirm whether the list is meant to protect any campaign.",
                            uncertainty="Unused lists can be intentional templates.")
        masters = ctx.profile.get("master_negative_lists") or {}
        for lid in sorted(masters, key=str):
            row = next((r for r in lists.rows if str(r.get("list_id")) == str(lid)), None)
            applied = set(_applied(row, lists.columns)) if row else set()
            for cid in sorted(str(c) for c in masters[lid] or []):
                if row is None or cid not in applied:
                    inv.finding("master_list_association_missing", "Info", {"list_id": str(lid), "campaign_id": cid},
                                f"Master list {lid} is {'absent' if row is None else 'not attached'} for campaign {cid}",
                                evidence={"declared_campaigns": masters[lid], "applied": sorted(applied)},
                                recommendation="Owner review of the list association (profile.master_negative_lists).",
                                uncertainty="Equivalent campaign-level negatives may already protect the campaign.")
        for cid in eligible:
            negs = [n for (c, _), ns in scopes.items() if c == cid for n in ns]
            inv.observe(f"Campaign {cid}: effective negatives", campaign_id=cid,
                        by_level={lv: len({(n.text, n.match, n.source_id) for n in negs if n.level == lv})
                                  for lv in ("account", "campaign", "ad_group", "shared_list")})

    # step 5 — literal coverage matrix
    lc = ctx.check("literal_coverage", "Literal protection of each intent term per campaign", {**INV, "campaigns": ["id"]})
    status: dict[tuple, str] = {}
    if lc.runnable:
        if not intents:
            lc.skip("no approved exclusions", ["profile.excluded_intents"])
        for cid in eligible:
            groups = [k for k in scopes if k[0] == cid]
            for i in intents:
                if not applies(cid, i):
                    continue
                for t in terms_map.get(i, []):
                    hits = [any(blocks(n.text, n.match, t) for n in scopes[g]) for g in groups]
                    status[(cid, i, t)] = ("unknown" if not groups else "protected" if all(hits)
                                           else "partial" if any(hits) else "unprotected")
        if intents and not status:
            lc.partial("no literal terms supplied: coverage matrix not computable")
        for (cid, i, t), s in sorted(status.items()):
            lc.observe(f"{cid} × {i} × '{t}': {s}", campaign_id=cid, intent=i, term=t, protection=s)

    # step 6 — reconcile queries
    qc = ctx.check("query_coverage", "Reconcile reported-query clicks/cost with campaign totals",
                   {**QUERIES, "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if qc.runnable:
        by_c: dict[str, list[float]] = {}
        for r in ctx.rows("search_terms"):
            acc = by_c.setdefault(str(r.get("campaign_id")), [0.0, 0.0])
            acc[0] += V.num(r.get("clicks")) or 0
            acc[1] += ctx.money(r.get("cost")) or 0
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            if cid in by_c:
                cc, ccost = V.num(m.get("clicks")), ctx.money(m.get("cost"))
                qc.observe(f"Campaign {cid}: reported queries cover part of campaign traffic", campaign_id=cid,
                           query_clicks=by_c[cid][0], campaign_clicks=cc, click_share=V.ratio(by_c[cid][0], cc),
                           query_cost=by_c[cid][1], campaign_cost=ccost, cost_share=V.ratio(by_c[cid][1], ccost))
        qc.partial("privacy-limited query reporting: unreported traffic is unobserved, not zero")

    # step 7 — observed exposure vs current protection
    ox = ctx.check("observed_exposure", "Observed excluded-intent exposure vs current effective protection",
                   {**QUERIES, **INV, "campaigns": ["id", "channel_type"]})
    if ox.runnable and not intents:
        ox.skip("no approved exclusions", ["profile.excluded_intents"])
    if ox.runnable:
        unblocked: dict[str, list[dict]] = {}
        for r in sorted(ctx.rows("search_terms"), key=lambda r: (str(r.get("campaign_id")), str(r.get("search_term")))):
            cid, gid, qtext = str(r.get("campaign_id")), str(r.get("ad_group_id")), V.norm_text(r.get("search_term"))
            if cid not in eligible or str(r.get("added_excluded") or "").upper() in ("EXCLUDED", "ADDED_EXCLUDED"):
                continue
            cost = ctx.money(r.get("cost"))
            if cost is None:
                ox.partial(f"'{qtext}' has unknown cost")
                continue
            if (cid, gid) not in scopes:
                ox.partial(f"'{qtext}': ad group {gid} not in inventory; protection unknown")
                continue
            if any(blocks(n.text, n.match, qtext) for n in scopes[(cid, gid)]):
                continue
            unblocked.setdefault(cid, []).append({"search_term": qtext, "ad_group_id": gid, "cost": cost,
                                                  "clicks": V.num(r.get("clicks")), "conversions": V.num(r.get("conversions"))})
        matched_terms: set = set()
        for cid in eligible:
            floor = ctx.params.get("spend_floor", cid)
            for i in intents:
                if not applies(cid, i):
                    continue
                for t in terms_map.get(i, []):
                    hits = [q for q in unblocked.get(cid, []) if blocks(t, "PHRASE", q["search_term"])]
                    matched_terms |= {(cid, q["search_term"]) for q in hits}
                    if not hits:
                        continue
                    exposure = sum(q["cost"] for q in hits)
                    prot = status.get((cid, i, t), "unknown")
                    ox.observe(f"{cid} × {i} × '{t}': unblocked observed exposure", campaign_id=cid, intent=i, term=t,
                               exposure=exposure, queries=len(hits), protection=prot, spend_floor=floor.value)
                    if floor.value is None:
                        ox.partial(f"spend_floor unresolved for campaign {cid}: {floor.reason}")
                    elif exposure >= floor.value and prot in ("unprotected", "partial"):
                        ox.finding("approved_exclusion_unprotected", "Warning",
                                   {"campaign_id": cid, "intent": i, "term": t},
                                   f"Approved exclusion '{i}' (term '{t}') lacks effective protection in campaign {cid}; "
                                   f"{len(hits)} unblocked queries cost {exposure:.2f} {ctx.currency} (>= {floor.value:g})",
                                   evidence={"queries": hits, "protection": prot, "spend_floor_source": floor.source,
                                             "window": [ctx.period_start, ctx.period_end]},
                                   calculation={"exposure": exposure, "threshold": floor.value},
                                   recommendation="Narrow owner-reviewed negative via 014; check 017 conflicts first.",
                                   uncertainty="Historical exposure may predate settings; exposure is not savings.")
        for cid in eligible:
            untermed = [i for i in intents if applies(cid, i) and not terms_map.get(i)]
            batch = sorted((q for q in unblocked.get(cid, []) if (cid, q["search_term"]) not in matched_terms),
                           key=lambda q: (-q["cost"], q["search_term"]))[:100]
            if not untermed or not batch:
                continue
            floor = ctx.params.get("spend_floor", cid)
            ox.review("excluded_intent_exposure", {"campaign_id": cid, "batch": "unblocked_queries"},
                      f"Which unblocked queries in campaign {cid} belong to the approved excluded intents {untermed}?",
                      evidence={"queries": batch, "intents": untermed, "spend_floor": floor.value,
                                "spend_floor_source": floor.source or floor.reason},
                      outcomes={"material_unprotected": {"severity": "Warning", "recommendation":
                                                         "Consolidate a narrow negative proposal under 014."},
                                "none_or_immaterial": {"severity": None, "recommendation": "No action."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask the owner to define the intent terms."}},
                      guidance="Only approved intents count; jobs/free/DIY are not universal waste. For "
                               "material_unprotected supply proposal {intent, queries: [exact texts from evidence], "
                               "negatives: [{negative, match_type, campaign_ids}]}; listed cost must reach spend_floor.")

    # step 8 — conflicts of shared protection
    sl = ctx.check("shared_list_conflicts", "Existing shared-list members vs desired queries and keywords",
                   {"shared_negative_lists": ["list_id"], "keywords": ["id", "campaign_id", "text", "status"],
                    **QUERIES})
    if sl.runnable and inv.runnable:
        hits = []
        for (cid, gid), negs in sorted(scopes.items()):
            for n in negs:
                if n.level == "shared_list":
                    hits += [f"{h} [{n.ref}]" for h in _conflicts(ctx, n.text, n.match, cid)]
        sl.observe("Shared-list members blocking desired text (route to 017)", conflicts=sorted(set(hits))[:50],
                   count=len(set(hits)))
    elif sl.runnable:
        sl.skip("negative inventory unavailable", inv.missing)

    # step 9 — proposal routing
    pr = ctx.check("proposal_routing", "Narrow owner-reviewed proposals consolidated under 014")
    pr.observe("Coverage proposals routed to 014 (no minimum count, no all-campaign list)",
               warnings=sum(1 for f in ctx.result.findings if f.severity == "Warning"),
               reviews=sum(1 for r in ctx.result.reviews if r.condition_key == "excluded_intent_exposure"))
    _upload_validation(ctx)


def _cell(r: dict, col: str) -> str:
    return str(r.get(col) or "").strip()


def _upload_level(v) -> str:
    s = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
    return "ad_group" if s in ("ad_group", "adgroup") else s


def _list_members(r: dict, cols) -> list[tuple[str, str]] | None:
    """Members of one shared-list row as (normalized text, match); None when a member lacks a match type."""
    if "member_text" in cols:
        m = normalize_match(r.get("member_match_type"))
        return [(" ".join(tokens(r.get("member_text"))), m)] if m and r.get("member_text") else None
    out = []
    for raw in str(r.get("keywords") or "").split(";"):
        raw = raw.strip()
        if not raw:
            continue
        mm = _MEMBER.match(raw)
        if not mm:
            return None
        out.append((" ".join(tokens(mm.group("text"))), mm.group("match").upper()))
    return out


def upload_scope(ctx, level: str, cid: str, gid: str, lid: str) -> tuple[list[tuple[str, str]] | None, str]:
    """Resolve one upload row's target to its (campaign_id, ad_group_id) scope in this account.

    Rules:   Joins on IDs only. Target missing = not found, REMOVED/DELETED, or an ad group whose campaign differs
             from the row's campaign_id → (None, reason). PAUSED targets are valid (the negative still applies).
             Campaign scope = its non-removed ad groups; ad_group = that group; shared_list = non-removed groups of
             the list's campaigns_applied plus the row's campaign_id when given; ad groups seen in keywords/search_terms
             of those campaigns are added. Empty scope → ([], note) = unevaluable, never passed; a non-empty scope from a
             non-manifest-complete ad_groups table returns a note so the caller marks coverage partial.
    """
    camps = {_cell(c, "id"): c for c in ctx.rows("campaigns")}
    groups = [g for g in ctx.rows("ad_groups") if _cell(g, "status").upper() not in REMOVED]

    def camp_ok(c):
        return c in camps and _cell(camps[c], "status").upper() not in REMOVED

    ag_table = ctx.table("ad_groups")
    inventory_note = "" if ag_table is not None and ag_table.complete is True else \
        "ad_groups not manifest-complete: campaign/list scope may miss ad groups"

    def groups_of(cs):
        found = {(_cell(g, "campaign_id"), _cell(g, "id")) for g in groups if _cell(g, "campaign_id") in cs}
        # keyword/query rows also prove an ad group exists in scope (guards incomplete ad_groups exports)
        for key in ("keywords", "search_terms"):
            for r in ctx.rows(key):
                if _cell(r, "campaign_id") in cs and _cell(r, "ad_group_id"):
                    found.add((_cell(r, "campaign_id"), _cell(r, "ad_group_id")))
        return sorted(found)

    if level == "campaign":
        if not camp_ok(cid):
            return None, f"campaign {cid} not found or removed"
        scope = groups_of({cid})
        return scope, inventory_note if scope else f"campaign {cid} has no exported ad groups"
    if level == "ad_group":
        row = next((g for g in ctx.rows("ad_groups") if _cell(g, "id") == gid), None)
        if row is None or _cell(row, "status").upper() in REMOVED:
            return None, f"ad group {gid} not found or removed"
        parent = _cell(row, "campaign_id")
        if cid and parent != cid:
            return None, f"ad group {gid} belongs to campaign {parent}, not {cid}"
        if not camp_ok(parent):
            return None, f"campaign {parent} of ad group {gid} not found or removed"
        return [(parent, gid)], ""
    lists = ctx.table("shared_negative_lists")
    row = next((r for r in lists.rows if _cell(r, "list_id") == lid), None) if lists else None
    if row is None or _cell(row, "status").upper() in REMOVED:
        return None, f"shared list {lid} not found or removed"
    if cid and not camp_ok(cid):
        return None, f"campaign {cid} not found or removed"
    applied = set(_applied(row, lists.columns)) | ({cid} if cid else set())
    scope = groups_of({c for c in applied if camp_ok(c)})
    return scope, inventory_note if scope else f"shared list {lid} applies to no active campaign or has no exported ad groups"


def upload_conflicts(ctx, text: str, match: str, scope: list[tuple[str, str]]) -> tuple[dict, list[str]]:
    """Literal blocks of one upload negative inside its scope: {'keyword'|'converting_query'|'brand': [evidence]}.

    Rules:   Only adsrun.negatives.blocks() True counts; None is returned as an undecidable note, never a pass
             or a block. Keywords: status ENABLED (blank = unknown → counted as active, as in _conflicts) in a
             scope ad group. Queries: search_terms with conversions > 0 in a scope ad group. Brand: profile
             brand_terms per scope campaign, skipped where campaign_objectives[cid].brand_policy = nonbrand_only.
    """
    hits: dict[str, list] = {"keyword": [], "converting_query": [], "brand": []}
    notes: list[str] = []
    in_scope, camps = set(scope), sorted({c for c, _ in scope})
    for k in sorted(ctx.rows("keywords"), key=lambda r: _cell(r, "id")):
        if (_cell(k, "campaign_id"), _cell(k, "ad_group_id")) not in in_scope \
                or _cell(k, "status").upper() not in ("ENABLED", ""):
            continue
        b = blocks(text, match, k.get("text"))
        if b is None:
            notes.append(f"keyword {k.get('id')} '{k.get('text')}' undecidable")
        elif b:
            hits["keyword"].append({"keyword_id": k.get("id"), "text": k.get("text"), "campaign_id": k.get("campaign_id"),
                                    "ad_group_id": k.get("ad_group_id"), "match_type": k.get("match_type")})
    for r in sorted(ctx.rows("search_terms"), key=lambda r: (_cell(r, "campaign_id"), _cell(r, "search_term"))):
        conv = V.num(r.get("conversions"))
        if (_cell(r, "campaign_id"), _cell(r, "ad_group_id")) not in in_scope or not conv or conv <= 0:
            continue
        b = blocks(text, match, r.get("search_term"))
        if b is None:
            notes.append(f"query '{r.get('search_term')}' undecidable")
        elif b:
            hits["converting_query"].append({"search_term": V.norm_text(r.get("search_term")),
                                             "campaign_id": r.get("campaign_id"), "ad_group_id": r.get("ad_group_id"),
                                             "conversions": conv, "cost": ctx.money(r.get("cost"))})
    brand = [str(b) for b in ctx.profile.get("brand_terms") or [] if b]
    for c in camps:
        policy = str((_by_key(ctx.profile.get("campaign_objectives"), c) or {}).get("brand_policy") or "")
        if policy == "nonbrand_only":
            continue
        for term in brand:
            b = blocks(text, match, term)
            if b is None:
                notes.append(f"brand term '{term}' undecidable")
            elif b:
                hits["brand"].append({"brand_term": term, "campaign_id": c})
    return hits, notes


def _upload_validation(ctx) -> None:
    """Step 10 (opt-in): validate a supplied negative upload list without pushing anything."""
    uv = ctx.check("negative_upload_validation", "Pre-upload validation of a supplied negative keyword list",
                   UPLOAD_NEEDS)
    if not uv.runnable:
        return
    t = ctx.table(UPLOAD)
    acct = str(ctx.account_id or "")
    own, ignored = [], 0
    for r in t.rows:
        if "customer_id" in t.columns and _cell(r, "customer_id") and _cell(r, "customer_id") != acct:
            ignored += 1
            continue
        own.append(r)
    counts: dict[tuple, int] = {}
    for r in own:
        key = (_upload_level(r.get("level")), _cell(r, "campaign_id"), _cell(r, "ad_group_id"), _cell(r, "list_id"),
               " ".join(tokens(r.get("text"))),
               normalize_match(r.get("match_type")) or str(r.get("match_type") or "").strip().upper())
        counts[key] = counts.get(key, 0) + 1
    if ctx.table("keywords") is None:
        uv.partial("keywords missing: active-keyword blocks unevaluated", ["keywords (file)"])
    if ctx.table("search_terms") is None:
        uv.partial("search_terms missing: converting-query blocks unevaluated", ["search_terms (file)"])
    if not ctx.profile.get("brand_terms"):
        uv.partial("profile.brand_terms missing: brand blocks unevaluated", ["profile.brand_terms"])
    scopes: dict = {}
    if ctx.table("negative_keywords") is None:
        uv.partial("negative_keywords missing: duplicates of existing negatives unevaluated", ["negative_keywords (file)"])
    else:
        scopes, gaps = effective_negatives(ctx)
        for g in gaps:
            uv.partial(f"existing-negative duplicates may be missed: {g}")
    tally: dict[str, int] = {}
    for key in sorted(counts):
        level, cid, gid, lid, text, raw_match = key
        entity = {"level": level or None, "campaign_id": cid or None, "ad_group_id": gid or None,
                  "list_id": lid or None, "text": text, "match_type": raw_match or None}

        def flag(cond, sev, summary, **kw):
            tally[cond] = tally.get(cond, 0) + 1
            uv.finding(cond, sev, entity, summary, **kw)

        if counts[key] > 1:
            flag("upload_duplicate_row", "Info", f"Upload row '{text}' appears {counts[key]} times for the same target",
                 evidence={"rows": counts[key]}, calculation={"duplicate_rows": counts[key] - 1},
                 recommendation="Keep one row per target, text and match type.")
        match = normalize_match(raw_match)
        if match is None:
            flag("upload_match_type_missing", "Info", f"Upload row '{text}' has no explicit match type ({raw_match!r})",
                 recommendation="Set match_type to EXACT, PHRASE or BROAD; never infer it from punctuation.")
            continue
        need = {"campaign": cid, "ad_group": gid, "shared_list": lid}.get(level)
        if not text or not need:
            flag("upload_row_invalid", "Info", f"Upload row '{text}' lacks text, a supported level or its target id",
                 evidence={"supported_levels": list(UPLOAD_LEVELS)},
                 recommendation="Fill level (campaign|ad_group|shared_list) and the matching target id.")
            continue
        if _UPLOAD_OPERATOR.search(text) or len(text.split()) > MAX_NEGATIVE_WORDS:
            uv.partial(f"'{text}': operators or > {MAX_NEGATIVE_WORDS} words; row not evaluated")
            continue
        scope, note = upload_scope(ctx, level, cid, gid, lid)
        if scope is None:
            flag("upload_target_missing", "Info", f"Upload target for '{text}' is not an active entity: {note}",
                 evidence={"reason": note}, recommendation="Correct the target id before any upload.")
            continue
        if not scope:
            uv.partial(f"'{text}': {note}; conflicts not evaluable")
        elif note:
            uv.partial(f"'{text}': {note}; a clean result is not proof of no conflict")
        if level == "shared_list":
            lists = ctx.table("shared_negative_lists")
            row = next(r for r in lists.rows if _cell(r, "list_id") == lid)
            members = _list_members(row, lists.columns)
            dup = members is not None and (text, match) in members
            if members is None:
                uv.partial(f"list {lid} members not parseable: duplicate of '{text}' unknown")
            sources = [f"shared list {lid}"] if dup else []
        else:
            per = [[n.ref for n in scopes.get(g, []) if " ".join(tokens(n.text)) == text and n.match == match]
                   for g in scope]
            dup = bool(scopes) and bool(per) and all(per)
            sources = sorted({s for p in per for s in p}) if dup else []
        if dup:
            flag("upload_duplicate_existing", "Info", f"'{text}' ({match}) is already an effective negative in its scope",
                 evidence={"existing": sources}, recommendation="Drop the row; it adds no protection.")
        hits, notes = upload_conflicts(ctx, text, match, scope)
        for n in notes:
            uv.partial(f"'{text}' ({match}): {n}")
        for cond, kind, label in (("upload_blocks_keyword", "keyword", "active keyword text"),
                                  ("upload_blocks_converting_query", "converting_query", "converting reported query"),
                                  ("upload_blocks_brand", "brand", "brand term")):
            if hits[kind]:
                flag(cond, "Warning", f"Upload negative '{text}' ({match}) would block {len(hits[kind])} {label}(s) "
                                      f"in its scope",
                     evidence={"blocked": hits[kind], "scope_ad_groups": len(scope),
                               "window": [ctx.period_start, ctx.period_end]},
                     calculation={"blocked": len(hits[kind]), "rule": "adsrun.negatives.blocks literal"},
                     recommendation="Narrow the negative or its scope before any upload; check 017 conflicts.",
                     uncertainty="Literal matching only; the owner decides whether the blocked text is desired.")
    uv.observe("Negative upload list validated (no upload performed)", rows_supplied=len(t.rows),
               rows_other_accounts=ignored, rows_this_account=len(own), unique_rows=len(counts),
               by_condition=dict(sorted(tally.items())))


def verify(ctx, item, decision) -> list[str]:
    """Rules: batch Warning proposals are re-checked for batch membership, floor and conflicts."""
    if item.condition_key != "excluded_intent_exposure" or decision.get("outcome") != "material_unprotected":
        return []
    p = decision.get("proposal") or {}
    problems = []
    if str(p.get("intent") or "") not in item.evidence["intents"]:
        problems.append(f"proposal.intent must be one of {item.evidence['intents']}")
    batch = {q["search_term"]: q for q in item.evidence["queries"]}
    listed = [str(x) for x in p.get("queries") or []]
    if not listed:
        problems.append("proposal.queries required")
    problems += [f"query not in reviewed batch: {x}" for x in listed if x not in batch]
    floor = item.evidence.get("spend_floor")
    cost = sum(batch[x]["cost"] for x in set(listed) if x in batch)
    if floor is None or cost < floor:
        problems.append(f"listed exposure {cost:.2f} below spend_floor {floor}: not material")
    for n in p.get("negatives") or []:
        text, match = str(n.get("negative") or "").strip(), normalize_match(n.get("match_type"))
        cids = [str(c) for c in n.get("campaign_ids") or []]
        if not text or match is None or not cids:
            problems.append("each negative needs negative, match_type and campaign_ids")
            continue
        if not any(blocks(text, match, x) for x in listed if x in batch):
            problems.append(f"'{text}' ({match}) blocks none of the listed queries")
        for cid in cids:
            problems += _conflicts(ctx, text, match, cid)
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
