"""check.py — skill-002 deterministic brand/non-brand classification and routing-vs-approved-role review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-002-brand-nonbrand-split/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #68 PMax Brand Traffic Analyzer (nilsrooijmans.com / smec) — clean-room reimplementation of
         brand-share measurement on visible PMax query rows; PMax without query rows stays partial, never a pass.
         index #107 Add keywords from campaigns/ad groups as negatives to others (Ritwik GA) — clean-room
         reimplementation of cross-campaign query sculpting as verified negative PROPOSALS only (verify()).
rules:   Brand = contiguous-token phrase hit of profile.brand_terms (+ optional profile.brand_aliases); applied
         BEFORE profile.competitor_terms (a text hitting both stays Brand and is recorded as a collision).
         No misspellings, no inference from account.brand_terms or the account/campaign name. Without profile
         brand_terms every classification-dependent check is skipped with 'profile:brand_terms'.
         Intended routing comes only from profile.campaign_objectives[id].brand_policy
         (brand_only | nonbrand_only; anything else = no routing constraint). Names are never roles.
         Routing Warning is deterministic only when the approved role is contradicted by visible, currently
         UNBLOCKED query cost >= spend_floor for THAT campaign; blocked queries predate the negative (observe).
         Brand share >5% needs campaign clicks >= min_clicks; it stays Info pending intent review.
         verify(): a proposed negative must block a reviewed contradicting text and must not block any desired
         text in scope (non-brand keywords/converting queries for nonbrand_only; brand terms/keywords/queries
         for brand_only). The script never adds negatives.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial deterministic check
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
from adsrun.negatives import blocks, effective_negatives, normalize_match, tokens  # noqa: E402

SKILL = "skill-002-brand-nonbrand-split"
VERSION = "1.0.0"

BRAND, COMPETITOR, NONBRAND, UNKNOWN = "Brand", "Competitor", "Non-brand", "Unknown"
SHARE_SCREEN = 0.05
ST_NEEDS = ["search_term", "campaign_id", "ad_group_id", "clicks", "cost", "conversions"]
KW_NEEDS = ["id", "campaign_id", "ad_group_id", "text", "status"]
_CONSTRAINED = ("brand_only", "nonbrand_only")


def _phrase_in(term: str, text: str) -> bool:
    n, q = tokens(term), tokens(text)
    return bool(n) and any(q[i:i + len(n)] == n for i in range(len(q) - len(n) + 1))


def _terms(ctx) -> tuple[list[str], list[str]]:
    brand = [V.norm_text(t) for t in (ctx.profile.get("brand_terms") or []) if str(t or "").strip()]
    brand += [V.norm_text(t) for t in (ctx.profile.get("brand_aliases") or []) if str(t or "").strip()]
    comp = [V.norm_text(t) for t in (ctx.profile.get("competitor_terms") or []) if str(t or "").strip()]
    return sorted(set(brand)), sorted(set(comp))


def classify(text, brand: list[str], comp: list[str]) -> tuple[str, bool]:
    """(class, collision). Rules: brand before competitor; empty/operator text → Unknown."""
    t = V.norm_text(text)
    if not t or any(ch in t for ch in '[]"+'):
        return UNKNOWN, False
    b = any(_phrase_in(x, t) for x in brand)
    c = any(_phrase_in(x, t) for x in comp)
    if b:
        return BRAND, c
    if c:
        return COMPETITOR, False
    return NONBRAND, False


def _objective(ctx, cid) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objs, dict):
        return {}
    obj = next((v for k, v in objs.items() if str(k) == str(cid)), None)
    return obj if isinstance(obj, dict) else {}


def _policy(ctx, cid) -> str | None:
    p = str(_objective(ctx, cid).get("brand_policy") or "").strip().lower()
    return p or None


def _active(row) -> bool:
    return str(row.get("status") or "ENABLED").upper() in ("ENABLED", "ACTIVE")


def _campaign_totals(ctx, chk) -> dict[str, dict]:
    """campaign_id → {clicks, cost}; duplicated campaign rows (fan-out/segments) are excluded, never summed."""
    rows: dict[str, list[dict]] = {}
    for r in ctx.rows("campaign_metrics"):
        rows.setdefault(str(r.get("campaign_id")), []).append(r)
    out = {}
    for cid in sorted(rows):
        if len(rows[cid]) > 1:
            chk.partial(f"campaign_metrics has {len(rows[cid])} rows for campaign {cid}: segment/fan-out, not summed")
            continue
        r = rows[cid][0]
        out[cid] = {"clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost"))}
    return out


def _unwanted(policy: str | None, cls: str) -> bool:
    if policy == "nonbrand_only":
        return cls == BRAND
    if policy == "brand_only":
        return cls in (NONBRAND, COMPETITOR)
    return False


def run(ctx) -> None:
    """Run brand/non-brand classification, mixed inventory, brand share, PMax, protection and routing checks.

    Rules:   Without profile.brand_terms every classification-dependent check skips with 'profile:brand_terms'; brand is
             never inferred from account/campaign names or account.brand_terms. Only routing_contradicts_role (approved
             brand_policy contradicted by UNBLOCKED query cost >= that campaign's spend_floor) is a Warning; mixed
             keywords, brand share and absent protection stay Info. Negative proposals are Info review outcomes checked
             by verify(); the script never adds negatives.
    """
    brand, comp = _terms(ctx)
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    channel = {cid: str(c.get("channel_type") or "").upper() for cid, c in camps.items()}

    # -- step 1/5: reporting coverage of visible queries against campaign totals
    cov = ctx.check("query_coverage", "Reconcile visible query clicks/cost with campaign totals",
                    {"search_terms": ST_NEEDS, "campaign_metrics": ["campaign_id", "clicks", "cost"]})
    totals: dict[str, dict] = {}
    if cov.runnable:
        totals = _campaign_totals(ctx, cov)
        q: dict[str, list[float]] = {}
        for r in ctx.rows("search_terms"):
            acc = q.setdefault(str(r.get("campaign_id")), [0.0, 0.0])
            acc[0] += V.num(r.get("clicks")) or 0
            acc[1] += ctx.money(r.get("cost")) or 0
        for cid in sorted(q):
            t = totals.get(cid, {})
            cov.observe(f"Campaign {cid}: visible query coverage", campaign_id=cid, query_clicks=q[cid][0],
                        campaign_clicks=t.get("clicks"), click_coverage=V.ratio(q[cid][0], t.get("clicks")),
                        query_cost=q[cid][1], campaign_cost=t.get("cost"), cost_coverage=V.ratio(q[cid][1], t.get("cost")),
                        window=[ctx.period_start, ctx.period_end])
        cov.partial("privacy-limited query reporting: hidden terms preclude a complete leakage estimate")

    # -- step 2: approved term rules
    rules = ctx.check("term_rules", "Normalize approved brand/competitor terms and flag collisions")
    if not brand:
        rules.skip("profile brand_terms missing: brand classification unknown (account name is not used)",
                   ["profile:brand_terms"])
    else:
        clashes = sorted({f"{b} ~ {c}" for b in brand for c in comp if _phrase_in(b, c) or _phrase_in(c, b)})
        rules.observe("Approved classification terms", brand_terms=brand, competitor_terms=comp,
                      term_collisions=clashes, precedence="brand before competitor")
        if clashes:
            rules.partial(f"{len(clashes)} brand/competitor term collisions: texts hitting both stay Brand, owner review")

    # -- step 3: classify keywords and queries
    cls = ctx.check("classification", "Classify keywords and visible queries",
                    {"keywords": KW_NEEDS, "search_terms": ST_NEEDS})
    kw_class: dict[str, str] = {}
    st_class: list[tuple[dict, str]] = []
    classified = False
    if cls.runnable and not brand:
        cls.skip("profile brand_terms missing", ["profile:brand_terms"])
    elif cls.runnable:
        classified = True
        counts: dict[str, int] = {}
        collisions = []
        for k in sorted(ctx.rows("keywords"), key=lambda r: str(r.get("id"))):
            c, hit = classify(k.get("text"), brand, comp)
            kw_class[str(k.get("id"))] = c
            counts[f"keyword_{c}"] = counts.get(f"keyword_{c}", 0) + 1
            if hit:
                collisions.append(f"keyword {k.get('id')} '{k.get('text')}'")
        for r in sorted(ctx.rows("search_terms"), key=lambda r: (str(r.get("campaign_id")), str(r.get("search_term")))):
            c, hit = classify(r.get("search_term"), brand, comp)
            st_class.append((r, c))
            counts[f"query_{c}"] = counts.get(f"query_{c}", 0) + 1
            if hit:
                collisions.append(f"query '{r.get('search_term')}' ({r.get('campaign_id')})")
        cls.observe("Classification counts", **counts, collisions=collisions)
        if counts.get("keyword_Unknown") or counts.get("query_Unknown"):
            cls.partial("some texts contain operators or are empty: classification Unknown")

    # -- step 4: mixed inventory (Info only, no prescription)
    mix = ctx.check("mixed_inventory", "Ad groups mixing brand and non-brand keywords", {"keywords": KW_NEEDS})
    if mix.runnable and not classified:
        mix.skip("keyword classification unavailable", ["profile:brand_terms"] if not brand else cls.missing)
    elif mix.runnable:
        groups: dict[tuple, dict[str, list]] = {}
        for k in ctx.rows("keywords"):
            if not _active(k):
                continue
            key = (str(k.get("campaign_id")), str(k.get("ad_group_id")))
            groups.setdefault(key, {}).setdefault(kw_class.get(str(k.get("id")), UNKNOWN), []).append(str(k.get("id")))
        n = 0
        for (cid, gid), by in sorted(groups.items()):
            if by.get(BRAND) and (by.get(NONBRAND) or by.get(COMPETITOR)):
                n += 1
                mix.finding("mixed_keywords", "Info", {"campaign_id": cid, "ad_group_id": gid},
                            f"Ad group {gid} holds {len(by[BRAND])} brand and "
                            f"{len(by.get(NONBRAND, [])) + len(by.get(COMPETITOR, []))} non-brand/competitor active keywords",
                            evidence={"brand_keyword_ids": sorted(by[BRAND]), "nonbrand_keyword_ids": sorted(by.get(NONBRAND, [])),
                                      "competitor_keyword_ids": sorted(by.get(COMPETITOR, [])), "brand_terms": brand,
                                      "intended_brand_policy": _policy(ctx, cid)},
                            recommendation="Review whether separate reporting/budget control is needed; no split is prescribed.",
                            uncertainty="Mixed inventory does not prove bidding distortion or leakage.")
        mix.observe("Ad groups with mixed brand/non-brand keywords", count=n, ad_groups=len(groups))

    # -- step 5: brand click share per Search campaign
    share = ctx.check("brand_share", "Brand clicks / campaign clicks per Search campaign",
                      {"search_terms": ST_NEEDS, "campaign_metrics": ["campaign_id", "clicks"], "campaigns": ["id", "channel_type"]})
    if share.runnable and not classified:
        share.skip("query classification unavailable", ["profile:brand_terms"] if not brand else cls.missing)
    elif share.runnable:
        _share(ctx, share, st_class, totals or _campaign_totals(ctx, share), channel, brand, "SEARCH")
        share.partial("visible queries only: brand clicks are a lower bound")

    # -- #68: PMax brand traffic on visible query rows
    pmax_ids = sorted(cid for cid, ch in channel.items() if ch == "PERFORMANCE_MAX")
    pm = ctx.check("pmax_brand_traffic", "Brand share of visible Performance Max queries",
                   {"search_terms": ST_NEEDS, "campaign_metrics": ["campaign_id", "clicks"], "campaigns": ["id", "channel_type"]},
                   applicable=bool(pmax_ids) or not camps, na_reason="no Performance Max campaigns in inventory")
    if pm.runnable and not brand:
        pm.skip("profile brand_terms missing", ["profile:brand_terms"])
    elif pm.runnable:
        seen = {str(r.get("campaign_id")) for r, _ in st_class}
        for cid in pmax_ids:
            if cid not in seen:
                pm.partial(f"PMax campaign {cid}: no visible query rows; brand share unobserved (supply PMax search terms)")
        _share(ctx, pm, st_class, totals or _campaign_totals(ctx, pm), channel, brand, "PERFORMANCE_MAX")

    # -- step 6: effective negative protection for nonbrand_only campaigns
    prot = ctx.check("negative_protection", "Brand-term protection from effective negatives (017 semantics)",
                     {"negative_keywords": ["text", "match_type", "level", "campaign_id"], "ad_groups": ["id", "campaign_id"],
                      "shared_negative_lists": ["list_id"]})
    scopes: dict | None = None
    if prot.runnable and not brand:
        prot.skip("profile brand_terms missing", ["profile:brand_terms"])
    elif prot.runnable:
        scopes, gaps = effective_negatives(ctx)
        for g in gaps:
            prot.partial(g)
        nb = sorted(cid for cid in camps if _policy(ctx, cid) == "nonbrand_only")
        for cid in nb:
            groups = sorted(gid for (c, gid) in scopes if c == cid)
            if not groups:
                prot.partial(f"campaign {cid}: no ad groups in inventory; protection unknown")
                continue
            unprotected = sorted({f"{gid}:{b}" for gid in groups for b in brand
                                  if not any(blocks(n.text, n.match, b) for n in scopes[(cid, gid)])})
            if unprotected:
                prot.finding("brand_protection_absent", "Info", {"campaign_id": cid},
                             f"nonbrand_only campaign {cid}: {len(unprotected)} ad-group/brand-term pairs not blocked by any "
                             f"effective negative",
                             evidence={"unprotected": unprotected, "brand_terms": brand, "ad_groups": groups,
                                       "intended_brand_policy": "nonbrand_only"},
                             recommendation="Consider a brand negative (verify against desired queries first) or document why not.",
                             uncertainty="Absence of protection alone is not observed leakage.")
            else:
                prot.observe(f"Campaign {cid}: every brand term blocked in every ad group", campaign_id=cid)
        if not nb:
            prot.observe("No nonbrand_only campaign roles approved; protection not evaluated against intent")

    # -- step 7: observed routing vs approved role
    route = ctx.check("routing_vs_role", "Observed routing vs approved campaign brand role",
                      {"search_terms": ST_NEEDS, "keywords": KW_NEEDS, "campaigns": ["id", "channel_type"]})
    contradictions: dict[str, dict] = {}
    if route.runnable and not classified:
        route.skip("classification unavailable", ["profile:brand_terms"] if not brand else cls.missing)
    elif route.runnable:
        if scopes is None:
            route.partial("negative scopes unavailable: current protection unknown, visible cost treated as unblocked")
        constrained = sorted(cid for cid in camps if _policy(ctx, cid) in _CONSTRAINED and channel.get(cid) == "SEARCH")
        unknown_role = sorted(cid for cid in camps if channel.get(cid) == "SEARCH" and _policy(ctx, cid) is None)
        if unknown_role:
            route.partial(f"Search campaigns without approved brand_policy: {unknown_role}")
        for cid in constrained:
            pol = _policy(ctx, cid)
            q_hits, blocked, kw_hits = [], [], []
            for r, c in st_class:
                if str(r.get("campaign_id")) != cid or not _unwanted(pol, c):
                    continue
                if str(r.get("added_excluded") or "").upper() in ("EXCLUDED", "ADDED_EXCLUDED"):
                    blocked.append(r.get("search_term"))
                    continue
                key = (cid, str(r.get("ad_group_id") or ""))
                negs = [n for n in (scopes or {}).get(key, []) if blocks(n.text, n.match, r.get("search_term"))]
                if negs:
                    blocked.append(f"{r.get('search_term')} (now blocked by {negs[0].text} {negs[0].match}, {negs[0].ref})")
                    continue
                q_hits.append({"search_term": r.get("search_term"), "ad_group_id": key[1], "class": c,
                               "clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")),
                               "conversions": V.num(r.get("conversions")), "matched_keyword_id": r.get("matched_keyword_id")})
            for k in sorted(ctx.rows("keywords"), key=lambda r: str(r.get("id"))):
                if str(k.get("campaign_id")) == cid and _active(k) and _unwanted(pol, kw_class.get(str(k.get("id")))):
                    kw_hits.append({"keyword_id": str(k.get("id")), "ad_group_id": str(k.get("ad_group_id")),
                                    "text": k.get("text"), "class": kw_class.get(str(k.get("id")))})
            if blocked:
                route.observe(f"Campaign {cid}: contradicting queries already excluded/blocked (traffic predates control)",
                              campaign_id=cid, queries=blocked)
            if not q_hits and not kw_hits:
                route.observe(f"Campaign {cid}: visible routing consistent with {pol}", campaign_id=cid)
                continue
            exposure = sum(h["cost"] or 0 for h in q_hits)
            unknown_cost = sum(1 for h in q_hits if h["cost"] is None)
            floor = ctx.params.get("spend_floor", cid)
            ev = {"intended_brand_policy": pol, "contradicting_queries": q_hits, "contradicting_keywords": kw_hits,
                  "visible_exposure_cost": exposure, "unknown_cost_rows": unknown_cost, "spend_floor": floor.value,
                  "spend_floor_source": floor.source or floor.reason, "brand_terms": brand, "competitor_terms": comp,
                  "campaign_cost": (totals.get(cid) or {}).get("cost"), "window": [ctx.period_start, ctx.period_end]}
            contradictions[cid] = ev
            entity = {"campaign_id": cid}
            if floor.value is None:
                route.partial(f"spend_floor unresolved for campaign {cid}: {floor.reason}")
            elif exposure >= floor.value:
                route.finding("routing_contradicts_role", "Warning", entity,
                              f"{pol} campaign {cid}: {len(q_hits)} visible unblocked contradicting queries cost "
                              f"{exposure:.2f} {ctx.currency} >= spend_floor {floor.value:g}",
                              evidence=ev, calculation={"exposure": "sum(cost of unblocked contradicting visible queries)",
                                                        "threshold": floor.value},
                              recommendation="Review routing controls in this campaign (see exclusion proposal review).",
                              uncertainty="Visible queries only; historical cost is exposure, not savings.")
            for kh in kw_hits:
                route.finding("keyword_contradicts_role", "Info",
                              {"campaign_id": cid, "ad_group_id": kh["ad_group_id"], "keyword_id": kh["keyword_id"]},
                              f"Active {kh['class']} keyword '{kh['text']}' in {pol} campaign {cid}",
                              evidence={"intended_brand_policy": pol, "keyword": kh, "brand_terms": brand},
                              recommendation="Confirm with the owner whether this keyword belongs to another campaign role.",
                              uncertainty="A keyword's presence is inventory; material exposure is not established here.")
            if floor.value is not None and exposure < floor.value:
                route.observe(f"Campaign {cid}: contradicting visible exposure below spend_floor", campaign_id=cid,
                              exposure=exposure, spend_floor=floor.value, queries=len(q_hits))

    # -- step 8 (+ #107): verified exclusion proposals, review only
    prop = ctx.check("exclusion_proposals", "Owner-reviewed exclusion/sculpting proposals",
                     {"search_terms": ST_NEEDS, "keywords": KW_NEEDS})
    if prop.runnable and not route.runnable:
        prop.skip("routing comparison unavailable", route.missing)
    elif prop.runnable:
        for cid in sorted(contradictions):
            ev = contradictions[cid]
            prop.review("exclusion_proposal", {"campaign_id": cid},
                        f"Should campaign {cid} ({ev['intended_brand_policy']}) receive a narrow negative for the "
                        f"contradicting texts, or is separate reporting/routing preferred?",
                        evidence=ev,
                        outcomes={"negative_proposed": {"severity": "Info", "recommendation":
                                                        "Owner reviews the verified negative before any change."},
                                  "separate_reporting": {"severity": "Info", "recommendation":
                                                         "Keep traffic; add reporting separation instead of exclusion."},
                                  "intentional": {"severity": None, "recommendation": "Document the approved exception."}},
                        guidance="negative_proposed needs proposal {negative, match_type EXACT|PHRASE|BROAD, level "
                                 "campaign|ad_group, campaign_id[, ad_group_id]} that blocks a listed contradicting text "
                                 "and no desired text in scope. Brand traffic intentional elsewhere → prefer narrower scope.")
        prop.observe("Exclusion proposal reviews queued", campaigns=sorted(contradictions))


def _share(ctx, chk, st_class, totals, channel, brand, want: str) -> None:
    by: dict[str, dict[str, float]] = {}
    for r, c in st_class:
        cid = str(r.get("campaign_id"))
        if channel.get(cid) != want:
            continue
        acc = by.setdefault(cid, {"brand": 0.0, "all": 0.0, "brand_cost": 0.0})
        clk = V.num(r.get("clicks")) or 0
        acc["all"] += clk
        if c == BRAND:
            acc["brand"] += clk
            acc["brand_cost"] += ctx.money(r.get("cost")) or 0
    min_clicks = ctx.params.get("min_clicks")
    for cid in sorted(by):
        a = by[cid]
        camp_clicks = (totals.get(cid) or {}).get("clicks")
        s_camp, s_query = V.ratio(a["brand"], camp_clicks), V.ratio(a["brand"], a["all"])
        pol = _policy(ctx, cid)
        data = {"campaign_id": cid, "brand_clicks": a["brand"], "campaign_clicks": camp_clicks,
                "brand_share_of_campaign": s_camp, "reported_query_clicks": a["all"], "brand_share_of_queries": s_query,
                "brand_cost": a["brand_cost"], "intended_brand_policy": pol, "min_clicks": min_clicks.value,
                "window": [ctx.period_start, ctx.period_end]}
        chk.observe(f"Campaign {cid}: brand click share", **data)
        if pol == "brand_only" or str(_objective(ctx, cid).get("role") or "").lower() == "brand":
            continue
        if camp_clicks is None or s_camp is None:
            chk.partial(f"campaign {cid}: campaign clicks unknown/zero; share undefined")
            continue
        if camp_clicks < (min_clicks.value or 0) or s_camp <= SHARE_SCREEN:
            continue
        prov = chk.finding("brand_click_share", "Info", {"campaign_id": cid},
                           f"Brand queries are {s_camp:.1%} of campaign {cid} clicks ({a['brand']:g}/{camp_clicks:g}), "
                           f"pending intent review", evidence=data,
                           calculation={"numerator": "visible brand query clicks", "denominator": "campaign clicks",
                                        "screen": SHARE_SCREEN},
                           recommendation="Confirm whether brand traffic is intended in this campaign.",
                           uncertainty="Visible queries only; share is a lower bound and not proof of leakage.")
        chk.review("brand_click_share", {"campaign_id": cid},
                   f"Is brand traffic ({s_camp:.1%} of clicks) intended in campaign {cid} (policy {pol or 'unknown'})?",
                   evidence=data, provisional=prov,
                   outcomes={"unintended_or_unknown": {"severity": "Info", "recommendation":
                                                       "Owner confirms the intended brand role before any routing change."},
                             "intended": {"severity": None, "recommendation": "No action; brand traffic is approved here."}},
                   guidance="Use only approved profile roles/objectives; names are hints, not roles.")


def _normalize(p: dict) -> tuple[dict | None, str]:
    text, match = str(p.get("negative") or "").strip(), normalize_match(p.get("match_type"))
    level = str(p.get("level") or "").lower()
    cid = str(p.get("campaign_id") or "")
    gid = str(p.get("ad_group_id") or "")
    if not text or match is None or level not in ("campaign", "ad_group") or not cid or (level == "ad_group" and not gid):
        return None, ("proposal needs negative, match_type EXACT|PHRASE|BROAD, level campaign|ad_group, campaign_id "
                      "and (for ad_group) ad_group_id")
    return {"text": text, "match": match, "campaign_id": cid, "ad_group_id": gid if level == "ad_group" else None}, ""


def verify(ctx, item, decision) -> list[str]:
    """Rules: negative_proposed must hit a reviewed contradicting text and no desired text in its scope."""
    if item.condition_key != "exclusion_proposal" or decision.get("outcome") != "negative_proposed":
        return []
    n, err = _normalize(decision.get("proposal") or {})
    if n is None:
        return [err]
    cid, pol = item.entity["campaign_id"], item.evidence.get("intended_brand_policy")
    if n["campaign_id"] != cid:
        return [f"proposal campaign {n['campaign_id']} differs from reviewed campaign {cid}"]
    in_scope = lambda gid: n["ad_group_id"] is None or str(gid) == n["ad_group_id"]
    targets = [q["search_term"] for q in item.evidence.get("contradicting_queries", []) if in_scope(q["ad_group_id"])]
    targets += [k["text"] for k in item.evidence.get("contradicting_keywords", []) if in_scope(k["ad_group_id"])]
    problems = []
    if not any(blocks(n["text"], n["match"], t) for t in targets):
        problems.append(f"'{n['text']}' ({n['match']}) blocks none of the reviewed contradicting texts in scope")
    brand, comp = _terms(ctx)
    for k in ctx.rows("keywords"):
        if str(k.get("campaign_id")) == cid and in_scope(k.get("ad_group_id")) and _active(k):
            c, _ = classify(k.get("text"), brand, comp)
            if not _unwanted(pol, c) and blocks(n["text"], n["match"], k.get("text")):
                problems.append(f"would block desired active keyword {k.get('id')} '{k.get('text')}'")
    for r in ctx.rows("search_terms"):
        if str(r.get("campaign_id")) == cid and in_scope(r.get("ad_group_id")):
            c, _ = classify(r.get("search_term"), brand, comp)
            desired = not _unwanted(pol, c) and ((V.num(r.get("conversions")) or 0) > 0 or pol == "brand_only")
            if desired and blocks(n["text"], n["match"], r.get("search_term")):
                problems.append(f"would block desired query '{r.get('search_term')}'")
    if pol == "brand_only":
        problems += [f"would block brand term '{b}'" for b in brand if blocks(n["text"], n["match"], b)]
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
