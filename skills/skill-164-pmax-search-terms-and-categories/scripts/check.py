"""check.py — skill-164 deterministic PMax search-term insight (category/term) review with verified control proposals.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-164-pmax-search-terms-and-categories/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #72 PMax Non-Converting Search Term Alerts (nilsrooijmans.com) — clean-room reimplementation of
         clicks-above-threshold / zero-conversion insight-term screening, gated by maturity, goal tracking and spend
         index #77 PMax Trending Search Categories (nilsrooijmans.com) — clean-room reimplementation of
         period-over-period category impression change, gated on both halves reaching min_impressions
rules:   Scope = campaigns.channel_type PERFORMANCE_MAX joined on campaign_id; category key = category_id when
         exported, else the normalized category_label. Duplicate (campaign, key, date) rows are dropped and reported.
         Insight exports often lack cost: 'cost' is optional; without a known cost the zero-conversion review
         reaches Info at most (spend_floor cannot be checked). Zero conversions = literal 0 only; unknown stays None.
         Zero-conversion reviews need ctx.mature is True AND ctx.tracking_for_campaign(cid) is True; else partial.
         Brand/competitor matching uses profile.brand_terms / profile.competitor_terms only (literal PHRASE via
         adsrun.negatives.blocks) — never hardcoded lists. Brand rows are never negative candidates.
         Brand mismatch review only when the documented brand_policy is nonbrand_only (profile, then campaigns).
         Proposals: control in {account_negative, brand_exclusion, search_theme}; verify() enforces blocking of the
         reviewed term, no collision with converting PMax/Search terms, active keyword texts or brand terms, and
         Critical 'must_not_serve_evidenced' requires proposal.evidence_ref.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes1 | initial deterministic check for new recipe
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402
from adsrun.negatives import blocks, normalize_match  # noqa: E402

SKILL = "skill-164-pmax-search-terms-and-categories"
VERSION = "1.0.0"

CATS = "custom/pmax_search_categories"
TERMS = "custom/pmax_search_terms"
_PMAX = "PERFORMANCE_MAX"
_CAT_NEEDS = ["campaign_id", "category_label", "impressions", "clicks", "conversions"]
_TERM_NEEDS = ["campaign_id", "search_term", "impressions", "clicks", "conversions"]
_CONTROLS = ("account_negative", "brand_exclusion", "search_theme")
_GROWTH, _DECLINE = 0.5, -0.3
_STEPS = (("nonconverting_categories", "Zero-conversion PMax search categories"),
          ("nonconverting_terms", "Zero-conversion PMax insight terms"),
          ("brand_competitor_presence", "Brand and competitor presence in PMax insights"),
          ("category_trends", "Period-over-period PMax category trends"),
          ("control_inventory", "Existing negatives applicable to PMax"))


# ----------------------------------------------------------------------------- helpers
def _contains(text: str, term: str) -> bool:
    return blocks(term, "PHRASE", text) is True


def _terms(ctx, name: str) -> list[str]:
    return sorted({str(t) for t in (ctx.profile.get(name) or []) if str(t or "").strip()})


def _objective(ctx, cid: str) -> dict:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    return obj if isinstance(obj, dict) else {}


def _brand_policy(ctx, cid: str) -> tuple[str | None, str]:
    p = _objective(ctx, cid).get("brand_policy")
    if p:
        return str(p).lower(), f"profile.campaign_objectives[{cid}].brand_policy"
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None) or {}
    if row.get("brand_policy"):
        return str(row["brand_policy"]).lower(), f"campaigns.brand_policy[{cid}]"
    return None, "brand policy undocumented"


def _sum(values):
    total = 0.0
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _agg(rows: list[dict]) -> dict:
    return {m: _sum(r[m] for r in rows) for m in ("imp", "clk", "cost", "conv", "val")} | {"rows": len(rows)}


def _load(ctx, key: str, text_col: str, pmax: set, all_camps: set) -> dict:
    """PMax-scoped, window-filtered, de-duplicated insight rows plus exclusion counters."""
    t = ctx.table(key)
    has_date, has_cost = "date" in t.columns, "cost" in t.columns
    use_id = text_col == "category_label" and "category_id" in t.columns
    start, end = ctx.period_start, ctx.period_end
    stats = {"non_pmax": set(), "unknown_campaigns": set(), "duplicates": 0, "outside_period": 0,
             "bad_rows": 0, "cost_unknown_rows": 0}
    seen, rows = set(), []
    for r in sorted(t.rows, key=lambda r: tuple(str(r.get(c) or "") for c in
                                                 ("campaign_id", "category_id", text_col, "date"))):
        cid, text = str(r.get("campaign_id") or ""), " ".join(str(r.get(text_col) or "").split())
        ident = str(r.get("category_id") or "").strip() if use_id else ""
        k = ident or V.norm_text(text)
        if not cid or not k:
            stats["bad_rows"] += 1
            continue
        if cid not in all_camps:
            stats["unknown_campaigns"].add(cid)
            continue
        if cid not in pmax:
            stats["non_pmax"].add(cid)
            continue
        d = V.parse_date(r.get("date")) if has_date else None
        if has_date and d is None:
            stats["bad_rows"] += 1
            continue
        if d and start and end and not (start <= d <= end):
            stats["outside_period"] += 1
            continue
        grain = (cid, k, d, str(r.get("category_id") or "") if text_col == "search_term" else "")
        if grain in seen:
            stats["duplicates"] += 1
            continue
        seen.add(grain)
        cost = ctx.money(r.get("cost")) if has_cost else None
        if has_cost and cost is None:
            stats["cost_unknown_rows"] += 1
        rows.append({"cid": cid, "key": k, "text": text, "category_id": r.get("category_id"), "date": d,
                     "imp": V.num(r.get("impressions")), "clk": V.num(r.get("clicks")), "cost": cost,
                     "conv": V.num(r.get("conversions")), "val": ctx.money(r.get("conversion_value"))})
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["cid"], r["key"]), []).append(r)
    return {"rows": rows, "groups": groups, "stats": stats, "has_date": has_date,
            "cost_supplied": has_cost and any(r["cost"] is not None for r in rows)}


def _pmax_negatives(ctx, cid: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """(text, match, ref) negatives applicable to a PMax campaign: account + campaign + attached shared lists."""
    out, gaps = [], []
    neg = ctx.table("negative_keywords")
    if neg is None:
        return [], ["negative_keywords missing: existing protection unknown"]
    account_rows = 0
    for r in neg.rows:
        if str(r.get("status") or "").upper() in ("REMOVED", "DELETED"):
            continue
        m = normalize_match(r.get("match_type"))
        level = str(r.get("level") or "").lower()
        if m is None:
            gaps.append(f"negative '{r.get('text')}' has no explicit match type")
            continue
        if level == "account":
            account_rows += 1
            out.append((str(r.get("text") or ""), m, "account"))
        elif level == "campaign" and str(r.get("campaign_id") or "") == cid:
            out.append((str(r.get("text") or ""), m, f"campaign {cid}"))
    if not account_rows and neg.complete is not True:
        gaps.append("negative_keywords not certified complete: account-level scope unknown")
    lists = ctx.table("shared_negative_lists")
    if lists is None:
        gaps.append("shared_negative_lists missing: shared-list coverage unknown")
    else:
        for r in lists.rows:
            applied_raw = r.get("campaigns_applied") if "campaigns_applied" in lists.columns else r.get("campaign_ids")
            if cid not in V.split_list(applied_raw, (";", "|", ",")):
                continue
            if "member_text" in lists.columns:
                m = normalize_match(r.get("member_match_type"))
                if m and r.get("member_text"):
                    out.append((str(r["member_text"]), m, f"shared list {r.get('list_id')}"))
            else:
                for raw in V.split_list(r.get("keywords"), (";",)):
                    text, _, rest = raw.rpartition("(")
                    m = normalize_match(rest.rstrip(")"))
                    if m and text.strip():
                        out.append((text.strip(), m, f"shared list {r.get('list_id')}"))
                    else:
                        gaps.append(f"list {r.get('list_id')} member '{raw}' has no explicit match type")
    return sorted(out), sorted(set(gaps))


# ----------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run PMax insight scope, zero-conversion category/term, brand/competitor, trend and control-inventory checks.

    Rules:   Not applicable without PMax campaigns and insight rows; unavailable scope skips analysis but still
             inventories negatives. Zero-conversion reviews need literal 0 conversions, ctx.mature and tracking True,
             else partial; unknown cost → Info at most. Brand rows are never negative candidates; brand mismatch review
             only for nonbrand_only policy. Critical 'must_not_serve_evidenced' needs proposal.evidence_ref.
    """
    camps = ctx.table("campaigns")
    pmax = {str(r.get("id")) for r in ctx.rows("campaigns") if str(r.get("channel_type") or "").upper() == _PMAX}
    cat_table = ctx.table(CATS)
    if camps is not None and "channel_type" in camps.columns and not pmax and not (cat_table and cat_table.rows):
        reason = "no PERFORMANCE_MAX campaigns in the campaign inventory and no insight rows"
        ctx.check("insight_scope", "PMax insight report scope", applicable=False, na_reason=reason)
        for cid, title in _STEPS:
            ctx.check(cid, title, applicable=False, na_reason=reason)
        return
    needs = {CATS: _CAT_NEEDS, "campaigns": ["id", "channel_type"]}
    scope = ctx.check("insight_scope", "PMax insight report scope", needs)
    negs = {cid: _pmax_negatives(ctx, cid) for cid in sorted(pmax)}
    if not scope.runnable:
        for cid, title in _STEPS[:-1]:
            ctx.check(cid, title).skip("insight scope unavailable", scope.missing)
        _inventory(ctx, ctx.check("control_inventory", "Existing negatives applicable to PMax",
                                  {"negative_keywords": ["text", "match_type", "level"],
                                   "campaigns": ["id", "channel_type"]}), negs)
        return
    all_camps = {str(r.get("id")) for r in ctx.rows("campaigns")}
    cats = _load(ctx, CATS, "category_label", pmax, all_camps)
    terms = _load(ctx, TERMS, "search_term", pmax, all_camps) if (
        ctx.table(TERMS) is not None and not ctx.table(TERMS).missing(_TERM_NEEDS)) else None
    _scope(ctx, scope, cats, terms)
    brand, competitors = _terms(ctx, "brand_terms"), _terms(ctx, "competitor_terms")
    _nonconverting(ctx, ctx.check("nonconverting_categories", "Zero-conversion PMax search categories", needs),
                   cats, "category", brand, competitors, negs)
    tchk = ctx.check("nonconverting_terms", "Zero-conversion PMax insight terms",
                     {TERMS: _TERM_NEEDS, "campaigns": ["id", "channel_type"]})
    if terms is not None:
        _nonconverting(ctx, tchk, terms, "term", brand, competitors, negs)
    _presence(ctx, ctx.check("brand_competitor_presence", "Brand and competitor presence in PMax insights", needs),
              cats, terms, brand, competitors)
    _trends(ctx, ctx.check("category_trends", "Period-over-period PMax category trends",
                           {CATS: _CAT_NEEDS + ["date"], "campaigns": ["id", "channel_type"]}), cats, negs)
    _inventory(ctx, ctx.check("control_inventory", "Existing negatives applicable to PMax",
                              {"negative_keywords": ["text", "match_type", "level"],
                               "campaigns": ["id", "channel_type"]}), negs)


def _scope(ctx, scope, cats: dict, terms: dict | None) -> None:
    for label, data in (("categories", cats), ("terms", terms)):
        if data is None:
            continue
        st = data["stats"]
        if st["unknown_campaigns"]:
            scope.partial(f"{label}: rows for campaigns absent from inventory {sorted(st['unknown_campaigns'])}")
        if st["duplicates"] or st["bad_rows"]:
            scope.partial(f"{label}: {st['duplicates']} duplicate and {st['bad_rows']} keyless/undated rows dropped")
        if not data["has_date"]:
            scope.partial(f"{label}: no date column; rows assumed to cover the manifest period")
        scope.observe(f"PMax insight {label} rows in scope", rows=len(data["rows"]), groups=len(data["groups"]),
                      cost_supplied=data["cost_supplied"], cost_unknown_rows=st["cost_unknown_rows"],
                      non_pmax_campaigns=sorted(st["non_pmax"]), outside_period=st["outside_period"])
    clicks = {}
    cm = ctx.table("campaign_metrics")
    if cm is None or cm.missing(["campaign_id", "clicks"]):
        scope.partial("campaign_metrics campaign_id/clicks missing: visible click share not computed",
                      ["campaign_metrics:campaign_id", "campaign_metrics:clicks"])
    else:
        for m in cm.rows:
            k, c = str(m.get("campaign_id")), V.num(m.get("clicks"))
            clicks[k] = None if (c is None or (k in clicks and clicks[k] is None)) else clicks.get(k, 0.0) + c
    by_c: dict[str, list] = {}
    for r in cats["rows"]:
        by_c.setdefault(r["cid"], []).append(r)
    for cid in sorted(by_c):
        a = _agg(by_c[cid])
        scope.observe(f"Campaign {cid}: visible insight categories", campaign_id=cid,
                      categories=len({r["key"] for r in by_c[cid]}), impressions=a["imp"], clicks=a["clk"],
                      conversions=a["conv"], campaign_clicks=clicks.get(cid),
                      visible_click_share=V.ratio(a["clk"], clicks.get(cid)), window=[ctx.period_start, ctx.period_end])


def _outcomes(material: bool) -> dict:
    return {
        "unwanted_intent": {"severity": "Warning" if material else "Info", "recommendation":
                            "Apply the verified account-negative or brand-exclusion proposal after owner approval."},
        "must_not_serve_evidenced": {"severity": "Critical", "recommendation":
                                     "Escalate: documented must-not-serve intent served; apply the verified control."},
        "relevant_keep": {"severity": None, "recommendation": "Keep serving; no control."},
        "uncertain": {"severity": "Info", "recommendation": "Ask the client whether this intent is served."},
    }


def _nonconverting(ctx, chk, data: dict, kind: str, brand, competitors, negs) -> None:
    if not chk.runnable:
        return
    if ctx.mature is not True:
        chk.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    if not data["cost_supplied"]:
        chk.partial("report supplies no cost: exposure is clicks/impressions only; review reaches Info at most")
    minc = ctx.params.get("min_clicks")
    if minc.value is None:
        chk.partial(f"min_clicks unresolved: {minc.reason}")
        return
    counts = {"screened": 0, "blocked_by_gates": 0, "below_clicks_or_floor": 0, "brand": 0,
              "already_negated": 0, "unknown": 0}
    unresolved, gaps = set(), set()
    for (cid, key) in sorted(data["groups"]):
        rows = data["groups"][(cid, key)]
        a, text = _agg(rows), rows[0]["text"]
        if a["conv"] is None or a["clk"] is None:
            counts["unknown"] += 1
            continue
        if a["conv"] != 0:
            continue
        if a["clk"] < minc.value:
            counts["below_clicks_or_floor"] += 1
            continue
        if any(_contains(text, b) for b in brand):
            counts["brand"] += 1
            chk.observe(f"Brand {kind} '{text}' protected from negative proposals", campaign_id=cid, clicks=a["clk"])
            continue
        existing, g = negs.get(cid, ([], []))
        gaps.update(g)
        hit = [n for n in existing if blocks(n[0], n[1], text) is True] if kind == "term" else []
        if hit:
            counts["already_negated"] += 1
            chk.observe(f"'{text}' already blocked by {hit[0][2]} negative '{hit[0][0]}' ({hit[0][1]})",
                        campaign_id=cid, clicks=a["clk"])
            continue
        floor = None
        material = False
        if a["cost"] is not None:
            floor = ctx.params.get("spend_floor", cid)
            if floor.value is None:
                unresolved.add(f"{cid}: {floor.reason}")
            elif a["cost"] < floor.value:
                counts["below_clicks_or_floor"] += 1
                continue
            else:
                material = True
        tracking, tnote = ctx.tracking_for_campaign(cid)
        if ctx.mature is not True or tracking is not True:
            counts["blocked_by_gates"] += 1
            if tracking is not True:
                chk.partial(f"campaign {cid}: tracking not evidenced ({tnote}); no zero-conversion path")
            continue
        counts["screened"] += 1
        entity = {"campaign_id": cid, kind: text}
        if kind == "category":
            entity["category_id"] = rows[0]["category_id"]
        ev = {"impressions": a["imp"], "clicks": a["clk"], "conversions": 0, "cost": a["cost"],
              "cost_reported": a["cost"] is not None, "window": [ctx.period_start, ctx.period_end],
              "min_clicks": minc.value, "min_clicks_source": minc.source,
              "spend_floor": floor.value if floor else None, "spend_floor_source": floor.source if floor else None,
              "tracking": tnote, "competitor_term": any(_contains(text, c) for c in competitors),
              "excluded_intents": ctx.profile.get("excluded_intents") or []}
        exposure = (f"{a['cost']:.2f} {ctx.currency} over {a['clk']:g} clicks" if a["cost"] is not None
                    else f"{a['clk']:g} clicks and {a['imp'] or 0:g} impressions (no cost reported)")
        prov = chk.finding(f"zero_conversion_{kind}", "Info", entity,
                           f"PMax {kind} '{text}' in campaign {cid}: {exposure}, 0 conversions in a mature window",
                           evidence=ev, calculation={"numerator": "conversions=0", "denominator": f"clicks={a['clk']:g}"},
                           recommendation="Review intent before any control; exposure is not savings.",
                           uncertainty="Insight rows are privacy-limited; zero conversions can reflect assisted value.")
        chk.review(f"zero_conversion_{kind}", entity,
                   f"Is the PMax {kind} '{text}' (campaign {cid}) an unwanted intent for the approved offer?",
                   evidence=ev, outcomes=_outcomes(material), provisional=prov,
                   guidance="Judge against profile excluded_intents and objectives only. For unwanted/must-not-serve "
                            "supply proposal {control: account_negative, negative, match_type} or "
                            "{control: brand_exclusion, brand}; must-not-serve also needs proposal.evidence_ref.")
    for u in sorted(unresolved):
        chk.partial(f"spend_floor unresolved for campaign {u}; clicks-only path")
    for g in sorted(gaps):
        chk.partial(g)
    chk.observe(f"Zero-conversion {kind} screening totals", **counts, min_clicks=minc.value,
                cost_supplied=data["cost_supplied"])


def _presence(ctx, chk, cats: dict, terms, brand, competitors) -> None:
    if not chk.runnable:
        return
    if not brand:
        chk.partial("profile.brand_terms missing: brand presence not measurable")
    if not competitors:
        chk.partial("profile.competitor_terms missing: competitor presence not measurable")
    if not (brand or competitors):
        return
    sources = [("category", cats)] + ([("term", terms)] if terms is not None else [])
    for kind, data in sources:
        by_c: dict[str, list] = {}
        for (cid, key), rows in data["groups"].items():
            by_c.setdefault(cid, []).append((rows[0]["text"], _agg(rows)))
        for cid in sorted(by_c):
            groups = sorted(by_c[cid], key=lambda g: g[0])
            tot_imp, tot_clk = _sum(a["imp"] for _, a in groups), _sum(a["clk"] for _, a in groups)
            b_rows = [(t, a) for t, a in groups if any(_contains(t, b) for b in brand)]
            c_rows = [(t, a) for t, a in groups if any(_contains(t, c) for c in competitors)]
            b_imp, b_clk = _sum(a["imp"] for _, a in b_rows), _sum(a["clk"] for _, a in b_rows)
            policy, psrc = _brand_policy(ctx, cid)
            chk.observe(f"Campaign {cid}: brand/competitor {kind} presence (visible-report share)", campaign_id=cid,
                        brand_rows=len(b_rows), brand_impression_share=V.ratio(b_imp, tot_imp),
                        brand_click_share=V.ratio(b_clk, tot_clk), competitor_rows=len(c_rows),
                        competitor_labels=[t for t, _ in c_rows],
                        competitor_click_share=V.ratio(_sum(a["clk"] for _, a in c_rows), tot_clk),
                        brand_policy=policy, brand_policy_source=psrc)
            if policy != "nonbrand_only" or not b_rows or not (b_clk or 0) > 0:
                continue
            entity = {"campaign_id": cid, "source": kind}
            ev = {"brand_rows": [{"text": t, "impressions": a["imp"], "clicks": a["clk"]} for t, a in b_rows],
                  "brand_clicks": b_clk, "visible_clicks": tot_clk, "brand_click_share": V.ratio(b_clk, tot_clk),
                  "brand_policy": policy, "brand_policy_source": psrc, "brand_terms": brand,
                  "window": [ctx.period_start, ctx.period_end]}
            prov = chk.finding("brand_traffic_in_nonbrand_pmax", "Info", entity,
                               f"{len(b_rows)} brand {kind} rows with {b_clk:g} clicks in nonbrand_only PMax campaign {cid}",
                               evidence=ev, calculation={"numerator": b_clk, "denominator": tot_clk},
                               recommendation="Confirm whether a brand exclusion is intended (route routing to 002).",
                               uncertainty="Visible-report share only; brand exclusions do not remove every brand match.")
            chk.review("brand_traffic_in_nonbrand_pmax", entity,
                       f"Is brand traffic in PMax campaign {cid} a mismatch with its nonbrand_only policy?", evidence=ev,
                       outcomes={"policy_mismatch": {"severity": "Warning", "recommendation":
                                                     "Propose the verified brand exclusion for this campaign."},
                                 "intended_brand_participation": {"severity": None, "recommendation":
                                                                  "Keep; update the documented policy."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the brand-policy owner."}},
                       provisional=prov,
                       guidance="policy_mismatch needs proposal {control: brand_exclusion, brand: <profile brand term>}.")


def _halves(ctx):
    start, end = ctx.period_start, ctx.period_end
    if start is None or end is None:
        return None
    half = ((end - start).days + 1) // 2
    if half < 1:
        return None
    cur_start = end - timedelta(days=half - 1)
    prior_end = cur_start - timedelta(days=1)
    return (prior_end - timedelta(days=half - 1), prior_end), (cur_start, end)


def _trends(ctx, chk, cats: dict, negs) -> None:
    if not chk.runnable:
        return
    halves = _halves(ctx)
    min_imp = ctx.params.get("min_impressions")
    if halves is None or min_imp.value is None:
        chk.partial("account period unknown/too short or min_impressions unresolved")
        return
    (ps, pe), (cs, ce) = halves
    t = ctx.table(CATS)
    complete = t.complete is True and not t.truncated
    if not complete:
        chk.partial("category report not certified complete: new/vanished categories not provable")
    counts = {"growth": 0, "decline": 0, "new": 0, "vanished": 0, "below_sample": 0, "unknown": 0}
    for (cid, key) in sorted(cats["groups"]):
        rows = cats["groups"][(cid, key)]
        p = _agg([r for r in rows if r["date"] and ps <= r["date"] <= pe])
        c = _agg([r for r in rows if r["date"] and cs <= r["date"] <= ce])
        if p["imp"] is None or c["imp"] is None:
            counts["unknown"] += 1
            continue
        text = rows[0]["text"]
        entity = {"campaign_id": cid, "category": text, "category_id": rows[0]["category_id"]}
        ev = {"prior_window": [ps, pe], "current_window": [cs, ce], "prior_impressions": p["imp"],
              "current_impressions": c["imp"], "prior_clicks": p["clk"], "current_clicks": c["clk"],
              "prior_conversions": p["conv"], "current_conversions": c["conv"],
              "min_impressions": min_imp.value, "min_impressions_source": min_imp.source}
        both = p["imp"] >= min_imp.value and c["imp"] >= min_imp.value
        change = V.ratio(c["imp"] - p["imp"], p["imp"]) if both else None
        ev["impression_change"] = change
        if both and change >= _GROWTH:
            kind = "category_growth"
        elif both and change <= _DECLINE:
            kind = "category_decline"
        elif complete and p["imp"] == 0 and c["imp"] >= min_imp.value:
            kind = "category_new"
        elif complete and p["imp"] >= min_imp.value and c["imp"] == 0:
            kind = "category_vanished"
        else:
            counts["below_sample"] += 1
            continue
        counts[kind.split("_", 1)[1]] += 1
        prov = chk.finding(kind, "Info", entity,
                           f"PMax category '{text}' ({kind.split('_', 1)[1]}) in campaign {cid}: "
                           f"{p['imp']:g} → {c['imp']:g} impressions", evidence=ev,
                           calculation={"numerator": "current-prior impressions", "denominator": "prior impressions"},
                           recommendation="Review relevance before any control; no action implied.",
                           uncertainty="Observed matching change; not market demand, causality or complete coverage.")
        if kind in ("category_growth", "category_new"):
            chk.review(kind, entity, f"Is the rising PMax category '{text}' (campaign {cid}) relevant to the offer?",
                       evidence={**ev, "existing_negatives": [n[0] for n in negs.get(cid, ([], []))[0]]},
                       outcomes={"relevant_opportunity": {"severity": "Info", "recommendation":
                                                          "Optional verified search-theme proposal for the asset group."},
                                 "off_target_matching": {"severity": "Info", "recommendation":
                                                         "Optional verified account-negative proposal; review assets."},
                                 "no_action": {"severity": None, "recommendation": "No action."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the client."}},
                       provisional=prov,
                       guidance="Proposals are optional: relevant_opportunity → {control: search_theme, theme}; "
                                "off_target_matching → {control: account_negative, negative, match_type}.")
    chk.observe("Category trend screen totals", prior_window=[ps, pe], current_window=[cs, ce], **counts,
                growth_threshold=_GROWTH, decline_threshold=_DECLINE, min_impressions=min_imp.value)


def _inventory(ctx, chk, negs) -> None:
    if not chk.runnable:
        return
    for cid in sorted(negs):
        existing, gaps = negs[cid]
        for g in gaps:
            chk.partial(f"campaign {cid}: {g}")
        chk.observe(f"PMax campaign {cid}: applicable negatives", campaign_id=cid,
                    account=sum(1 for n in existing if n[2] == "account"),
                    campaign=sum(1 for n in existing if n[2].startswith("campaign")),
                    shared_list=sum(1 for n in existing if n[2].startswith("shared list")))


# ----------------------------------------------------------------------------- verify
def _collisions(ctx, text: str, match: str) -> list[str]:
    """Account-level scope: converting PMax/Search terms, active keyword texts and brand terms it would block."""
    out = []
    for key, col in (("search_terms", "search_term"), (TERMS, "search_term")):
        for r in ctx.rows(key):
            if (V.num(r.get("conversions")) or 0) > 0 and blocks(text, match, r.get(col)) is True:
                out.append(f"'{text}' would block converting {key} query '{r.get(col)}' (campaign {r.get('campaign_id')})")
    for k in ctx.rows("keywords"):
        if str(k.get("status") or "ENABLED").upper() == "ENABLED" and blocks(text, match, k.get("text")) is True:
            out.append(f"'{text}' would block positive keyword text '{k.get('text')}' ({k.get('id')})")
    for b in _terms(ctx, "brand_terms"):
        if blocks(text, match, b) is True:
            out.append(f"'{text}' would block brand term '{b}'")
    return sorted(set(out))


def _check_proposal(ctx, item, p: dict, allowed: tuple) -> list[str]:
    control = str(p.get("control") or "")
    if control not in _CONTROLS:
        return [f"proposal.control must be one of {list(_CONTROLS)} (controls PMax supports)"]
    if control not in allowed:
        return [f"control {control} does not fit outcome; allowed {list(allowed)}"]
    cid = str(item.entity.get("campaign_id") or "")
    if control == "account_negative":
        text, match = str(p.get("negative") or "").strip(), normalize_match(p.get("match_type"))
        if not text or match is None:
            return ["account_negative needs negative and match_type EXACT|PHRASE|BROAD"]
        problems = []
        if "term" in item.entity and blocks(text, match, item.entity["term"]) is not True:
            problems.append(f"'{text}' ({match}) does not block the reviewed term '{item.entity['term']}'")
        return problems + _collisions(ctx, text, match)
    if control == "brand_exclusion":
        name = V.norm_text(p.get("brand"))
        brands = {V.norm_text(b) for b in _terms(ctx, "brand_terms")}
        known = brands | {V.norm_text(c) for c in _terms(ctx, "competitor_terms")}
        if name not in known:
            return ["brand_exclusion.brand must be a profile brand_terms/competitor_terms entry"]
        policy, _ = _brand_policy(ctx, cid)
        if name in brands and policy != "nonbrand_only":
            return [f"own-brand exclusion conflicts with campaign {cid} brand policy '{policy}'"]
        return []
    theme = str(p.get("theme") or "").strip()
    if not theme:
        return ["search_theme needs proposal.theme"]
    problems = [f"theme '{theme}' contains competitor term '{c}'" for c in _terms(ctx, "competitor_terms")
                if _contains(theme, c)]
    existing, _ = _pmax_negatives(ctx, cid)
    problems += [f"theme '{theme}' is blocked by existing {n[2]} negative '{n[0]}'" for n in existing
                 if blocks(n[0], n[1], theme) is True]
    return problems


def verify(ctx, item, decision) -> list[str]:
    """Rules: proposals use only supported PMax controls and are collision-checked."""
    outcome = decision.get("outcome")
    p = decision.get("proposal") or {}
    problems: list[str] = []
    key = item.condition_key
    if key.startswith("zero_conversion_"):
        if outcome in ("unwanted_intent", "must_not_serve_evidenced"):
            material = item.outcomes[outcome]["severity"] in ("Warning", "Critical")
            if p or material:
                problems += _check_proposal(ctx, item, p, ("account_negative", "brand_exclusion"))
            if outcome == "must_not_serve_evidenced" and not p.get("evidence_ref"):
                problems.append("must-not-serve needs proposal.evidence_ref pointing at supplied evidence")
    elif key == "brand_traffic_in_nonbrand_pmax" and outcome == "policy_mismatch":
        problems += _check_proposal(ctx, item, p, ("brand_exclusion",))
        if not problems and V.norm_text(p.get("brand")) not in {V.norm_text(b) for b in _terms(ctx, "brand_terms")}:
            problems.append("policy_mismatch brand exclusion must name an own brand term")
    elif key in ("category_growth", "category_new") and p:
        allowed = {"relevant_opportunity": ("search_theme",), "off_target_matching": ("account_negative",)}
        if outcome not in allowed:
            problems.append(f"outcome {outcome} takes no proposal")
        else:
            problems += _check_proposal(ctx, item, p, allowed[outcome])
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
