"""check.py — skill-163 deterministic item-level Shopping/PMax performance triage.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-163-product-performance-triage/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #76 PMax Trending Products (nilsrooijmans.com, reference only) — clean-room reimplementation of
         period-over-period item trend detection, gated on both halves reaching min_impressions
         index #117 Find Duplicate Shopping Targets (bitbucket fvallaeys) — clean-room reimplementation of
         same-item multi-target detection, limited to OBSERVED multi-campaign serving (listing trees not required)
         index #120 Set Target CPA bids for Shopping Product Groups (bitbucket fvallaeys) — partial: item CPA/ROAS
         versus the campaign's approved target is reported descriptively; per-group bid mutation is refused
rules:   Scope = campaigns.channel_type SHOPPING|PERFORMANCE_MAX joined on campaign_id; product key = offer_id
         (or the documented alternative item_id), normalized strip+lower-case because Ads reports item ids lower-case.
         Product rows outside the account period or duplicated at (campaign, offer, date, target_country) are dropped
         and reported; unknown metric cells stay None and propagate — never coerced to 0.
         Zero-conversion items: literal 0 conversions, cost >= spend_floor(campaign), clicks >= min_clicks,
         ctx.mature is True AND ctx.tracking_for_campaign(cid) is True → provisional Info + review (Warning path);
         otherwise partial, no finding. Target gaps need mature data, >= min_conversions and one goal set per campaign.
         Trends: two equal consecutive halves of the account period; growth >= +50% / decline <= -30% only when BOTH
         halves reach min_impressions; stopped serving (prior >= min_impressions, current 0) and non-serving absence
         need manifest-certified complete tables. Overlap is observed serving, never a cannibalization claim.
         Critical only via review outcome 'material_serving_failure' with proposal.evidence_ref (verify enforces).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes1 | initial deterministic check for new recipe
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import math
import sys
from datetime import timedelta
from itertools import combinations
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-163-product-performance-triage"
VERSION = "1.0.0"

PRODUCT = "custom/product_daily"
MERCHANT = "external/merchant_products"
_CHANNELS = ("SHOPPING", "PERFORMANCE_MAX")
_METRICS = ["campaign_id", "date", "impressions", "clicks", "cost", "conversions", "conversion_value"]
_ELIGIBLE = {"approved", "eligible"}
_IN_STOCK = {"in_stock", "in stock"}
_GROWTH, _DECLINE = 0.5, -0.3
_STEPS = (("spend_concentration", "Item spend concentration"),
          ("zero_conversion_items", "Gated zero-conversion item screening"),
          ("item_target_gap", "Item CPA/ROAS versus approved campaign target"),
          ("item_trends", "Period-over-period item impression trends"),
          ("item_overlap", "Items served by several Shopping/PMax campaigns"),
          ("non_serving_items", "Approved in-stock items without impressions"))


# ----------------------------------------------------------------------------- evidence helpers
def _key_col(ctx) -> str:
    t = ctx.table(PRODUCT)
    if t is not None and "offer_id" not in t.columns and "item_id" in t.columns:
        return "item_id"
    return "offer_id"


def _nid(v) -> str:
    return str(v or "").strip().lower()


def _complete(ctx, key: str) -> bool:
    t = ctx.table(key)
    return t is not None and t.complete is True and not t.truncated


def _sum(values) -> float | None:
    """Sum known values; any unknown cell makes the total unknown (never zero)."""
    total = 0.0
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _agg(rows: list[dict]) -> dict:
    return {m: _sum(r[m] for r in rows) for m in ("imp", "clk", "cost", "conv", "val")} | {"rows": len(rows)}


def _item_entity(cid: str | None, item: tuple[str, str]) -> dict:
    e = {"offer_id": item[0]}
    if cid is not None:
        e["campaign_id"] = cid
    if item[1]:
        e["target_country"] = item[1]
    return e


def _load(ctx, key: str) -> dict:
    """In-scope, window-filtered, de-duplicated product rows plus exclusion counters."""
    channel = {str(r.get("id")): str(r.get("channel_type") or "").upper() for r in ctx.rows("campaigns")}
    start, end = ctx.period_start, ctx.period_end
    seen, rows = set(), []
    stats = {"missing_key": 0, "bad_date": 0, "outside_period": 0, "duplicates": 0,
             "unknown_campaigns": set(), "out_of_scope_campaigns": set()}
    raw = sorted(ctx.rows(PRODUCT), key=lambda r: (str(r.get("campaign_id") or ""), _nid(r.get(key)),
                                                    str(r.get("date") or ""), str(r.get("target_country") or "")))
    for r in raw:
        cid, offer = str(r.get("campaign_id") or ""), _nid(r.get(key))
        if not cid or not offer:
            stats["missing_key"] += 1
            continue
        ch = channel.get(cid)
        if ch is None:
            stats["unknown_campaigns"].add(cid)
            continue
        if ch not in _CHANNELS:
            stats["out_of_scope_campaigns"].add(cid)
            continue
        d = V.parse_date(r.get("date"))
        if d is None:
            stats["bad_date"] += 1
            continue
        if start and end and not (start <= d <= end):
            stats["outside_period"] += 1
            continue
        country = str(r.get("target_country") or "").strip().upper()
        grain = (cid, offer, d, country)
        if grain in seen:
            stats["duplicates"] += 1
            continue
        seen.add(grain)
        rows.append({"cid": cid, "item": (offer, country), "date": d, "goal": r.get("goal_set_id"),
                     "imp": V.num(r.get("impressions")), "clk": V.num(r.get("clicks")),
                     "cost": ctx.money(r.get("cost")), "conv": V.num(r.get("conversions")),
                     "val": ctx.money(r.get("conversion_value"))})
    by_ci: dict[tuple, list] = {}
    for r in rows:
        by_ci.setdefault((r["cid"], r["item"]), []).append(r)
    return {"rows": rows, "by_ci": by_ci, "stats": stats, "channel": channel}


def _merchant_index(ctx) -> dict | None:
    t = ctx.table(MERCHANT)
    if t is None or t.missing(["offer_id", "availability", "processing_status"]):
        return None
    out: dict[str, list[dict]] = {}
    for r in t.rows:
        out.setdefault(_nid(r.get("offer_id")), []).append(
            {"target_country": r.get("target_country"), "availability": r.get("availability"),
             "processing_status": r.get("processing_status"), "snapshot_at": r.get("snapshot_at")})
    return out


def _merchant_context(merchant: dict | None, offer: str):
    if merchant is None:
        return "merchant snapshot not supplied"
    return merchant.get(offer) or "offer not in merchant snapshot"


def _target_roas(ctx, cid: str) -> tuple[float | None, str, str]:
    """(value, source, level) — level 'campaign' for campaign/portfolio targets, 'profile' for objectives."""
    def pos(v):
        f = V.num(v)
        return f if f is not None and f > 0 else None

    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None) or {}
    t = pos(row.get("target_roas"))
    if t:
        return t, f"campaigns.target_roas[{cid}]", "campaign"
    sid = str(row.get("bidding_strategy_id") or row.get("strategy_id") or "")
    for s in sorted(ctx.rows("bidding_strategies"), key=lambda s: str(s.get("id"))):
        members = V.split_list(s.get("campaign_ids"), (";", "|", ","))
        if (sid and str(s.get("id")) == sid) or cid in members:
            t = pos(s.get("target_roas"))
            if t:
                return t, f"bidding_strategies.target_roas[{s.get('id')}]", "campaign"
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    if isinstance(obj, dict):
        t = pos(obj.get("target_roas"))
        if t:
            return t, f"profile.campaign_objectives[{cid}].target_roas", "profile"
    return None, "no applicable target ROAS", ""


def _concentration(costs: list[float]) -> dict:
    vals = sorted(costs, reverse=True)
    total = sum(vals)
    spent = [v for v in vals if v > 0]
    decile = max(1, math.ceil(len(spent) / 10)) if spent else 0
    k80, cum = None, 0.0
    for i, v in enumerate(vals, 1):
        cum += v
        if total > 0 and cum >= 0.8 * total:
            k80 = i
            break
    return {"items": len(vals), "items_with_cost": len(spent), "total_cost": total,
            "top1_share": V.ratio(vals[0], total) if vals else None, "top5_share": V.ratio(sum(vals[:5]), total),
            "top_decile_items": decile, "top_decile_share": V.ratio(sum(vals[:decile]), total),
            "items_for_80pct_cost": k80}


# ----------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run product scope, concentration, zero-conversion, target-gap, trend, overlap and non-serving item checks.

    Rules:   No Shopping/PMax campaign and no product rows → all not_applicable; missing product scope skips all steps.
             Every deterministic finding is Info: zero-conversion ai_review needs ctx.mature, tracking, spend_floor and
             min_clicks; target gaps need maturity + min_conversions; serving-loss ai_review needs prior cost >=
             spend_significant; non-serving needs certified-complete product+merchant tables (Critical only via review).
    """
    key = _key_col(ctx)
    needs = {PRODUCT: [key] + _METRICS, "campaigns": ["id", "channel_type"]}
    camps = ctx.table("campaigns")
    in_scope = [r for r in ctx.rows("campaigns") if str(r.get("channel_type") or "").upper() in _CHANNELS]
    product = ctx.table(PRODUCT)
    if camps is not None and "channel_type" in camps.columns and not in_scope and not (product and product.rows):
        reason = "no Shopping or PERFORMANCE_MAX campaigns in the campaign inventory and no product rows"
        ctx.check("product_scope", "Product report scope and coverage", applicable=False, na_reason=reason)
        for cid, title in _STEPS:
            ctx.check(cid, title, applicable=False, na_reason=reason)
        return

    scope = ctx.check("product_scope", "Product report scope and coverage", needs)
    if not scope.runnable:
        if key == "offer_id" and product is not None:
            scope.notes.append("product key column offer_id (or documented alternative item_id) required")
        for cid, title in _STEPS:
            ctx.check(cid, title).skip("product scope unavailable", scope.missing)
        return
    data = _load(ctx, key)
    _scope(ctx, scope, data, key)
    merchant = _merchant_index(ctx)
    _spend_concentration(ctx, ctx.check("spend_concentration", "Item spend concentration", needs), data)
    _zero_conversion(ctx, ctx.check("zero_conversion_items", "Gated zero-conversion item screening", needs),
                     data, merchant)
    _target_gap(ctx, ctx.check("item_target_gap", "Item CPA/ROAS versus approved campaign target", needs), data)
    _trends(ctx, ctx.check("item_trends", "Period-over-period item impression trends", needs), data, merchant)
    _overlap(ctx, ctx.check("item_overlap", "Items served by several Shopping/PMax campaigns", needs), data)
    _non_serving(ctx, ctx.check("non_serving_items", "Approved in-stock items without impressions",
                                {**needs, MERCHANT: ["offer_id", "availability", "processing_status"]}), data)


def _scope(ctx, scope, data: dict, key: str) -> None:
    st = data["stats"]
    if st["unknown_campaigns"]:
        scope.partial(f"product rows for campaigns absent from campaigns inventory: {sorted(st['unknown_campaigns'])}")
    if st["duplicates"]:
        scope.partial(f"{st['duplicates']} duplicate rows at (campaign, {key}, date, target_country) grain dropped")
    if st["missing_key"] or st["bad_date"]:
        scope.partial(f"{st['missing_key']} rows without campaign/{key}, {st['bad_date']} rows with unparseable date")
    if ctx.period_start is None or ctx.period_end is None:
        scope.partial("account period unknown: rows not window-filtered")
    metrics = {}
    cm = ctx.table("campaign_metrics")
    if cm is None or cm.missing(["campaign_id", "cost"]):
        scope.partial("campaign_metrics campaign_id/cost missing: product-report coverage share not computed",
                      ["campaign_metrics:campaign_id", "campaign_metrics:cost"])
    else:
        for m in cm.rows:
            c = ctx.money(m.get("cost"))
            k = str(m.get("campaign_id"))
            metrics[k] = None if (c is None or (k in metrics and metrics[k] is None)) else metrics.get(k, 0.0) + c
    by_c: dict[str, list] = {}
    for r in data["rows"]:
        by_c.setdefault(r["cid"], []).append(r)
    for cid in sorted(by_c):
        a = _agg(by_c[cid])
        items: dict[tuple, list] = {}
        for r in by_c[cid]:
            items.setdefault(r["item"], []).append(r["imp"])
        zero_imp = sum(1 for v in items.values() if _sum(v) == 0)
        scope.observe(f"Campaign {cid} ({data['channel'][cid]}): product report coverage", campaign_id=cid,
                      items=len(items), items_zero_impressions=zero_imp, rows=a["rows"], impressions=a["imp"],
                      clicks=a["clk"], item_cost=a["cost"], campaign_cost=metrics.get(cid),
                      cost_coverage_share=V.ratio(a["cost"], metrics.get(cid)),
                      window=[ctx.period_start, ctx.period_end])
    scope.observe("Product rows excluded from scope", outside_period=st["outside_period"],
                  out_of_scope_campaigns=sorted(st["out_of_scope_campaigns"]), duplicates=st["duplicates"],
                  in_scope_rows=len(data["rows"]))


def _spend_concentration(ctx, chk, data: dict) -> None:
    if not chk.runnable:
        return
    per_c: dict[str, dict[tuple, list]] = {}
    acct: dict[tuple, list] = {}
    for r in data["rows"]:
        per_c.setdefault(r["cid"], {}).setdefault(r["item"], []).append(r["cost"])
        acct.setdefault(r["item"], []).append(r["cost"])
    for label, items in [(cid, per_c[cid]) for cid in sorted(per_c)] + [("account", acct)]:
        costs = {i: _sum(v) for i, v in items.items()}
        unknown = sum(1 for v in costs.values() if v is None)
        if unknown:
            chk.partial(f"{label}: {unknown} items with unknown cost excluded from concentration")
        c = _concentration([v for v in costs.values() if v is not None])
        chk.observe(f"Spend concentration for {'campaign ' + label if label != 'account' else 'account'}",
                    scope=label, window=[ctx.period_start, ctx.period_end], currency=ctx.currency, **c)


def _zero_conversion(ctx, chk, data: dict, merchant) -> None:
    if not chk.runnable:
        return
    if ctx.mature is not True:
        chk.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    minc = ctx.params.get("min_clicks")
    if minc.value is None:
        chk.partial(f"min_clicks unresolved: {minc.reason}")
        return
    unresolved, blocked, below, unknown, screened = set(), [], 0, 0, 0
    for (cid, item) in sorted(data["by_ci"]):
        a = _agg(data["by_ci"][(cid, item)])
        if a["conv"] is None or a["cost"] is None or a["clk"] is None:
            unknown += 1
            continue
        if a["conv"] != 0:
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            unresolved.add(f"{cid}: {floor.reason}")
            continue
        if a["cost"] < floor.value or a["clk"] < minc.value:
            below += 1
            continue
        tracking, tnote = ctx.tracking_for_campaign(cid)
        if ctx.mature is not True or tracking is not True:
            blocked.append({"campaign_id": cid, "offer_id": item[0], "cost": a["cost"], "clicks": a["clk"],
                            "tracking": tnote})
            if tracking is not True:
                chk.partial(f"campaign {cid}: tracking not evidenced ({tnote}); no zero-conversion path")
            continue
        screened += 1
        entity = _item_entity(cid, item)
        ev = {"cost": a["cost"], "clicks": a["clk"], "impressions": a["imp"], "conversions": 0,
              "window": [ctx.period_start, ctx.period_end], "currency": ctx.currency,
              "spend_floor": floor.value, "spend_floor_source": floor.source,
              "min_clicks": minc.value, "min_clicks_source": minc.source, "tracking": tnote,
              "maturity": ctx.maturity_note, "merchant": _merchant_context(merchant, item[0])}
        prov = chk.finding("zero_conversion_item", "Info", entity,
                           f"Item {item[0]} in campaign {cid} spent {a['cost']:.2f} {ctx.currency} over "
                           f"{a['clk']:g} clicks with 0 conversions (spend_floor {floor.value:g})",
                           evidence=ev, calculation={"numerator": "conversions=0", "denominator": f"clicks={a['clk']:g}"},
                           recommendation="Review relevance, price and landing page before any selection change; "
                                          "exposure is not savings.",
                           uncertainty="Zero conversions can reflect assisted value, long cycles or attribution to "
                                       "another item.")
        chk.review("zero_conversion_item", entity,
                   f"Is item {item[0]} unwanted or uneconomic for campaign {cid} given its zero-conversion exposure?",
                   evidence={**ev, "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(cid)},
                   outcomes={
                       "unwanted_or_uneconomic": {"severity": "Warning", "recommendation":
                                                  "Investigate the item; any exclusion from product selection is a "
                                                  "separate request to the listing-tree/asset-group owner (085/089)."},
                       "keep_serving": {"severity": None, "recommendation": "Keep serving; no change."},
                       "uncertain": {"severity": "Info", "recommendation": "Ask the client about the item's role."},
                   }, provisional=prov,
                   guidance="Judge only against profile objectives, campaign role and merchant context; do not "
                            "treat zero conversions as proof of irrelevance.")
    for u in sorted(unresolved):
        chk.partial(f"spend_floor unresolved for campaign {u}")
    chk.observe("Zero-conversion item screening totals", screened=screened, blocked_by_gates=len(blocked),
                blocked_items=blocked, below_floor_or_clicks=below, unknown_metrics=unknown,
                min_clicks=minc.value)


def _target_gap(ctx, chk, data: dict) -> None:
    if not chk.runnable:
        return
    if ctx.mature is not True:
        chk.partial(f"target gaps need mature conversions: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    minconv = ctx.params.get("min_conversions")
    if minconv.value is None:
        chk.partial(f"min_conversions unresolved: {minconv.reason}")
        return
    by_c: dict[str, list[tuple]] = {}
    goal_sets: dict[str, set] = {}
    for (cid, item), rows in data["by_ci"].items():
        by_c.setdefault(cid, []).append(item)
        goal_sets.setdefault(cid, set()).update(str(r["goal"]) for r in rows if r["goal"] is not None)
    for cid in sorted(by_c):
        goals = goal_sets[cid]
        if len(goals) > 1:
            chk.partial(f"campaign {cid}: mixed goal sets {sorted(goals)}; item targets not comparable")
            continue
        roas, rsrc, level = _target_roas(ctx, cid)
        cpa, csrc = (None, "") if level == "campaign" else ctx.params.target_cpa(cid)
        if cpa is not None:
            roas = None
        if cpa is None and roas is None:
            chk.partial(f"campaign {cid}: no approved target CPA/ROAS ({csrc or rsrc})")
            continue
        evaluated = below = 0
        for item in sorted(by_c[cid]):
            a = _agg(data["by_ci"][(cid, item)])
            if a["conv"] is None or a["cost"] is None or a["conv"] < minconv.value:
                below += 1
                continue
            evaluated += 1
            ev = {"cost": a["cost"], "conversions": a["conv"], "conversion_value": a["val"],
                  "window": [ctx.period_start, ctx.period_end], "min_conversions": minconv.value,
                  "min_conversions_source": minconv.source, "currency": ctx.currency}
            entity = _item_entity(cid, item)
            if cpa is not None:
                item_cpa = V.ratio(a["cost"], a["conv"])
                if item_cpa is not None and item_cpa > cpa:
                    chk.finding("item_cpa_above_target", "Info", entity,
                                f"Item {item[0]} CPA {item_cpa:.2f} exceeds campaign {cid} target CPA {cpa:g}",
                                evidence={**ev, "item_cpa": item_cpa, "target_cpa": cpa, "target_source": csrc},
                                calculation={"numerator": f"cost={a['cost']:.2f}", "denominator": f"conversions={a['conv']:g}"},
                                recommendation="Descriptive gap: review product selection or segmentation with 085/089; "
                                               "Smart Bidding sets item bids, so no per-item bid is proposed.",
                                uncertainty="Item attribution and bidding-level balancing; not a causal loss.")
            else:
                item_roas = V.ratio(a["val"], a["cost"])
                if a["val"] is None:
                    chk.partial(f"campaign {cid}: unknown conversion_value for item {item[0]}")
                elif item_roas is not None and item_roas < roas:
                    chk.finding("item_roas_below_target", "Info", entity,
                                f"Item {item[0]} ROAS {item_roas:.2f} below campaign {cid} target ROAS {roas:g}",
                                evidence={**ev, "item_roas": item_roas, "target_roas": roas, "target_source": rsrc},
                                calculation={"numerator": f"conversion_value={a['val']:.2f}", "denominator": f"cost={a['cost']:.2f}"},
                                recommendation="Descriptive gap: review product selection or segmentation with 085/089; "
                                               "no per-item bid is proposed.",
                                uncertainty="Item attribution and bidding-level balancing; not a causal loss.")
        chk.observe(f"Campaign {cid}: items evaluated against target", campaign_id=cid, evaluated=evaluated,
                    below_min_conversions=below, target_cpa=cpa, target_roas=roas, target_source=csrc if cpa else rsrc)


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


def _trends(ctx, chk, data: dict, merchant) -> None:
    if not chk.runnable:
        return
    halves = _halves(ctx)
    if halves is None:
        chk.partial("account period unknown or too short for two equal halves")
        return
    (ps, pe), (cs, ce) = halves
    complete = _complete(ctx, PRODUCT)
    if not complete:
        chk.partial("product report not certified complete: stopped/new items not provable")
    min_imp, minconv = ctx.params.get("min_impressions"), ctx.params.get("min_conversions")
    if min_imp.value is None:
        chk.partial(f"min_impressions unresolved: {min_imp.reason}")
        return
    counts = {"growth": 0, "decline": 0, "stopped": 0, "new": 0, "below_sample": 0, "unknown": 0}
    unresolved = set()
    for (cid, item) in sorted(data["by_ci"]):
        rows = data["by_ci"][(cid, item)]
        p = _agg([r for r in rows if ps <= r["date"] <= pe])
        c = _agg([r for r in rows if cs <= r["date"] <= ce])
        if p["imp"] is None or c["imp"] is None:
            counts["unknown"] += 1
            continue
        ev = {"prior_window": [ps, pe], "current_window": [cs, ce], "prior_impressions": p["imp"],
              "current_impressions": c["imp"], "prior_clicks": p["clk"], "current_clicks": c["clk"],
              "prior_cost": p["cost"], "current_cost": c["cost"], "min_impressions": min_imp.value,
              "min_impressions_source": min_imp.source}
        if ctx.mature is True and minconv.value is not None and (p["conv"] or 0) >= minconv.value and (c["conv"] or 0) >= minconv.value:
            ev |= {"prior_cpa": V.ratio(p["cost"], p["conv"]), "current_cpa": V.ratio(c["cost"], c["conv"])}
        entity = _item_entity(cid, item)
        if p["imp"] >= min_imp.value and c["imp"] >= min_imp.value:
            change = V.ratio(c["imp"] - p["imp"], p["imp"])
            ev["impression_change"] = change
            if change >= _GROWTH:
                counts["growth"] += 1
                chk.finding("item_impression_growth", "Info", entity,
                            f"Item {item[0]} impressions grew {change:+.0%} in campaign {cid}", evidence=ev,
                            calculation={"numerator": "current-prior impressions", "denominator": "prior impressions"},
                            recommendation="Review relevance/stock coverage; no action implied.",
                            uncertainty="Observed serving change, not market demand or causal effect.")
            elif change <= _DECLINE:
                counts["decline"] += 1
                _decline(ctx, chk, cid, item, entity, ev, p, "item_impression_decline",
                         f"Item {item[0]} impressions fell {change:+.0%} in campaign {cid}", merchant, unresolved)
        elif p["imp"] >= min_imp.value and c["imp"] == 0:
            if complete:
                counts["stopped"] += 1
                _decline(ctx, chk, cid, item, entity, ev, p, "item_stopped_serving",
                         f"Item {item[0]} served {p['imp']:g} impressions in the prior half and none in the current "
                         f"half (campaign {cid})", merchant, unresolved)
        elif p["imp"] == 0 and c["imp"] >= min_imp.value:
            counts["new"] += int(complete)
        else:
            counts["below_sample"] += 1
    for u in sorted(unresolved):
        chk.partial(f"spend_significant unresolved for campaign {u}: declines stay Info without review")
    chk.observe("Item trend screen totals", prior_window=[ps, pe], current_window=[cs, ce], **counts,
                growth_threshold=_GROWTH, decline_threshold=_DECLINE, min_impressions=min_imp.value)


def _decline(ctx, chk, cid, item, entity, ev, prior, key, summary, merchant, unresolved) -> None:
    sig = ctx.params.get("spend_significant", cid)
    ev = {**ev, "spend_significant": sig.value, "spend_significant_source": sig.source,
          "merchant": _merchant_context(merchant, item[0])}
    prov = chk.finding(key, "Info", entity, summary, evidence=ev,
                       calculation={"numerator": "current-prior impressions", "denominator": "prior impressions"},
                       recommendation="Check stock, feed status, price and product selection before acting.",
                       uncertainty="Observed serving change; seasonality, stock or intended selection may explain it.")
    if sig.value is None:
        unresolved.add(f"{cid}: {sig.reason}")
        return
    if prior["cost"] is None or prior["cost"] < sig.value:
        return
    chk.review(key, entity, f"Is the serving loss of item {item[0]} in campaign {cid} unintended?", evidence=ev,
               outcomes={"unintended_serving_loss": {"severity": "Warning", "recommendation":
                                                     "Fix the evidenced cause (stock, feed status, selection) via its owner."},
                         "intended_or_explained": {"severity": None, "recommendation": "No action; document the reason."},
                         "uncertain": {"severity": "Info", "recommendation": "Ask the client about stock and selection."}},
               provisional=prov,
               guidance="Use merchant availability/status, profile objectives and seasonal context; discontinued, "
                        "sold-out or deliberately excluded items are intended.")


def _overlap(ctx, chk, data: dict) -> None:
    if not chk.runnable:
        return
    served: dict[tuple, dict[str, dict]] = {}
    for (cid, item), rows in data["by_ci"].items():
        a = _agg(rows)
        if a["imp"] is not None and a["imp"] > 0:
            served.setdefault(item, {})[cid] = a
    pairs: dict[tuple, list] = {}
    for item in sorted(served):
        for a, b in combinations(sorted(served[item]), 2):
            pairs.setdefault((a, b), []).append(item)
    for (a, b) in sorted(pairs):
        items = pairs[(a, b)]
        rows = [{"offer_id": i[0], "target_country": i[1] or None,
                 "impressions": [served[i][a]["imp"], served[i][b]["imp"]],
                 "cost": [served[i][a]["cost"], served[i][b]["cost"]]} for i in items]
        entity = {"campaign_ids": [a, b]}
        ev = {"channels": [data["channel"][a], data["channel"][b]], "items": rows, "item_count": len(items),
              "window": [ctx.period_start, ctx.period_end]}
        prov = chk.finding("multi_campaign_item_serving", "Info", entity,
                           f"{len(items)} items served in both campaign {a} and campaign {b}", evidence=ev,
                           recommendation="Confirm which campaign should own these items (085/089).",
                           uncertainty="Observed serving overlap only; no auction, cannibalization or incrementality claim.")
        chk.review("multi_campaign_item_serving", entity,
                   f"Is serving the same {len(items)} items in campaigns {a} and {b} unintended?", evidence=ev,
                   outcomes={"unintended_overlap": {"severity": "Warning", "recommendation":
                                                    "Propose selection changes so the owner campaign keeps the items."},
                             "intended_structure": {"severity": None, "recommendation": "Keep; document routing."},
                             "uncertain": {"severity": "Info", "recommendation": "Ask for the selection intent."}},
                   provisional=prov,
                   guidance="Use profile campaign roles/objectives only; for unintended_overlap supply "
                            "proposal.owner_campaign_id (one of the pair).")
    chk.observe("Multi-campaign item serving", overlapping_items=sum(1 for i in served if len(served[i]) > 1),
                campaign_pairs=len(pairs), served_items=len(served))


def _non_serving(ctx, chk, data: dict) -> None:
    if not chk.runnable:
        return
    mt = ctx.table(MERCHANT)
    use_country = "target_country" in mt.columns and "target_country" in ctx.table(PRODUCT).columns
    served, unknown = set(), set()
    per_item: dict[tuple, list] = {}
    for r in data["rows"]:
        k = r["item"] if use_country else (r["item"][0], "")
        per_item.setdefault(k, []).append(r["imp"])
    for k, imps in per_item.items():
        total = _sum(imps)
        if total is None:
            unknown.add(k)
        elif total > 0:
            served.add(k)
    eligible = set()
    for r in mt.rows:
        status = str(r.get("processing_status") or "").strip().lower()
        avail = str(r.get("availability") or "").strip().lower()
        if status in _ELIGIBLE and avail in _IN_STOCK:
            country = str(r.get("target_country") or "").strip().upper() if use_country else ""
            eligible.add((_nid(r.get("offer_id")), country))
    missing = sorted(eligible - served - unknown)
    certified = _complete(ctx, PRODUCT) and _complete(ctx, MERCHANT)
    chk.observe("Merchant approved in-stock items versus served items", eligible=len(eligible),
                served=len(eligible & served), unknown_impressions=len(eligible & unknown), not_served=len(missing),
                not_served_share=V.ratio(len(missing), len(eligible)), certified_complete=certified,
                join="offer_id+target_country" if use_country else "offer_id")
    if not certified:
        chk.partial("product report or merchant snapshot not certified complete: absence of impressions not provable")
        return
    if not missing:
        return
    offer_ids = [m[0] if not m[1] else f"{m[0]}|{m[1]}" for m in missing]
    entity = {"merchant_scope": "approved_in_stock"}
    ev = {"offer_ids": offer_ids, "not_served": len(missing), "eligible": len(eligible),
          "not_served_share": V.ratio(len(missing), len(eligible)), "window": [ctx.period_start, ctx.period_end],
          "merchant_snapshot": sorted({str(r.get("snapshot_at")) for r in mt.rows if r.get("snapshot_at")})}
    prov = chk.finding("eligible_items_not_serving", "Info", entity,
                       f"{len(missing)} of {len(eligible)} approved in-stock items had no Shopping/PMax impressions",
                       evidence=ev, calculation={"numerator": len(missing), "denominator": len(eligible)},
                       recommendation="Check product selection, listing groups and item priority before acting.",
                       uncertainty="Selection, bids, low demand or intended exclusion can explain non-serving.")
    chk.review("eligible_items_not_serving", entity,
               f"Were these {len(missing)} approved in-stock items intended to serve in the window?", evidence=ev,
               outcomes={"intended_items_not_serving": {"severity": "Warning", "recommendation":
                                                        "Review selection/listing trees for the listed items via 085/089."},
                         "material_serving_failure": {"severity": "Critical", "recommendation":
                                                      "Escalate the evidenced outage/exclusion of core inventory."},
                         "expected_not_serving": {"severity": None, "recommendation": "No action."},
                         "uncertain": {"severity": "Info", "recommendation": "Ask which items are priorities."}},
               provisional=prov,
               guidance="Warning/Critical outcomes need proposal.offer_ids (subset of evidence.offer_ids); Critical "
                        "also needs proposal.evidence_ref to a verified outage or exclusion of core inventory.")


# ----------------------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: overlap owners must be in the reviewed pair; non-serving proposals cite listed offers;
    Critical needs proposal.evidence_ref."""
    outcome = decision.get("outcome")
    proposal = decision.get("proposal") or {}
    problems: list[str] = []
    if item.condition_key == "multi_campaign_item_serving" and outcome == "unintended_overlap":
        owner = str(proposal.get("owner_campaign_id") or "")
        if owner not in item.entity["campaign_ids"]:
            problems.append(f"proposal.owner_campaign_id must be one of {item.entity['campaign_ids']}")
    if item.condition_key == "eligible_items_not_serving" and outcome in ("intended_items_not_serving",
                                                                         "material_serving_failure"):
        ids = proposal.get("offer_ids") or []
        if not ids:
            problems.append("proposal.offer_ids required")
        listed = set(item.evidence["offer_ids"])
        problems += [f"offer {i} not in the reviewed non-serving list" for i in ids if i not in listed]
        if outcome == "material_serving_failure" and not proposal.get("evidence_ref"):
            problems.append("material serving failure needs proposal.evidence_ref pointing at supplied evidence")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
