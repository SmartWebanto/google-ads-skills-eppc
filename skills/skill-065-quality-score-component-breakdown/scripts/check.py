"""check.py — skill-065 deterministic QS component inventory, spend priority, pattern scope and routing.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-065-quality-score-component-breakdown/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Universe = enabled Search keywords in enabled ad groups/campaigns (keywords+ad_groups+campaigns).
         Ratings normalize to ABOVE_AVERAGE|AVERAGE|BELOW_AVERAGE; anything else is unavailable (never Below Average).
         keyword_metrics joins on (campaign_id, ad_group_id, keyword_id|criterion_id|id); duplicate rows at
         criterion(+date) grain are excluded; unmatched keywords cost 0 only with a complete manifest.
         Exposed spend is the UNION of keyword IDs — overlapping component views are never summed.
         Warning (a) Below Average + criterion cost >= spend_high resolved per campaign; (b) the same weak
         component on >50% of rated keywords in >=2 eligible campaigns AND union cost >= spend_material.
         When spend_high is unresolved, "below priority" Info is emitted only when cost < max(currency floor,
         5x target CPA), a proven lower bound of spend_high; otherwise the keyword is unknown (partial).
         No Critical path. Lead routing order expected_ctr→067, ad_relevance→068, landing_page→069 is a
         convention for one owner per keyword, not a causal ranking.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial deterministic check
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
from adsrun.params import EUR_DEFAULTS  # noqa: E402

SKILL = "skill-065-quality-score-component-breakdown"
VERSION = "1.0.0"

COMPONENTS = ("expected_ctr", "ad_relevance", "landing_page_experience")
ROUTE = {"expected_ctr": "skill-067", "ad_relevance": "skill-068", "landing_page_experience": "skill-069"}
RATINGS = ("ABOVE_AVERAGE", "AVERAGE", "BELOW_AVERAGE")
_KM_ID = ("keyword_id", "criterion_id", "id")
BA = "BELOW_AVERAGE"


def _up(v) -> str:
    return str(v or "").strip().upper()


def _rating(v) -> str:
    s = _up(v).replace("-", "_").replace(" ", "_")
    return s if s in RATINGS else "UNAVAILABLE"


def _km_id(ctx) -> str:
    t = ctx.table("keyword_metrics")
    return next((c for c in _KM_ID if t is not None and c in t.columns), _KM_ID[0])


def _universe(ctx) -> tuple[dict, dict]:
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns")}
    groups = {str(r.get("id")): r for r in ctx.rows("ad_groups")}
    eligible, excluded = {}, {}
    for k in sorted(ctx.rows("keywords"), key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("id")))):
        cid, gid = str(k.get("campaign_id")), str(k.get("ad_group_id"))
        camp, grp = camps.get(cid), groups.get(gid)
        if camp is None or grp is None:
            reason = "parent campaign/ad group not in inventory"
        elif _up(camp.get("channel_type")) != "SEARCH":
            reason = "non-Search channel"
        elif _up(k.get("status")) != "ENABLED" or _up(grp.get("status")) != "ENABLED" or _up(camp.get("status")) != "ENABLED":
            reason = "paused/removed keyword, ad group or campaign"
        else:
            eligible[(cid, gid, str(k.get("id")))] = k
            continue
        excluded[reason] = excluded.get(reason, 0) + 1
    return eligible, excluded


def _costs(ctx, eligible) -> tuple[dict, list[str], list[str]]:
    """({key: cost|None}, problems, unknown ids) for eligible keywords."""
    t, idc = ctx.table("keyword_metrics"), _km_id(ctx)
    has_date = "date" in t.columns
    seen, dup, sums, unknown_rows = set(), set(), {}, set()
    for r in t.rows:
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get(idc)))
        grain = key + ((str(r.get("date")),) if has_date else ())
        if grain in seen:
            dup.add(key)
        seen.add(grain)
        c = ctx.money(r.get("cost"))
        if c is None:
            unknown_rows.add(key)
        sums[key] = sums.get(key, 0.0) + (c or 0.0)
    problems = [f"keyword_metrics duplicate rows at criterion grain {k}; cost excluded" for k in sorted(dup)]
    complete = t.complete is True
    out, unknown = {}, []
    for key in eligible:
        if key in dup or key in unknown_rows or (key not in sums and not complete):
            out[key] = None
            unknown.append(key[2])
        else:
            out[key] = sums.get(key, 0.0)
    return out, problems, unknown


def _spend_high_lower_bound(ctx, cid) -> tuple[float | None, str]:
    """Proven lower bound of spend_high = max(currency floor, 5 x target CPA) when the full value is unresolved."""
    if ctx.currency == "EUR":
        floor, src = EUR_DEFAULTS["spend_high"], "EUR reference floor"
    else:
        floor = V.num((ctx.profile.get("currency_floors") or {}).get("spend_high"))
        src = f"profile.currency_floors ({ctx.currency})"
        if floor is None:
            return None, "no spend_high currency floor"
    cpa, csrc = ctx.params.target_cpa(cid)
    if cpa is not None and 5 * cpa > floor:
        return 5 * cpa, f"5x target CPA {cpa:g} ({csrc})"
    return floor, src


def run(ctx) -> None:
    """Run keyword universe, component rating, high-spend Below Average and widespread weak-component checks.

    Rules:   Missing universe or ratings skips downstream checks; unrated components are unavailable, never Below
             Average. Warning = Below Average + keyword cost >= resolved spend_high, or one weak component on >50% of
             rated keywords in >= 2 campaigns with union cost >= spend_material; unresolved thresholds → partial or
             bounded Info. No Critical path; overlapping component views are never summed.
    """
    uni = ctx.check("keyword_universe", "Keyword universe and metric join",
                    {"campaigns": ["id", "status", "channel_type"], "ad_groups": ["id", "campaign_id", "status"],
                     "keywords": ["id", "campaign_id", "ad_group_id", "status"]})
    titles = (("component_counts", "Per-component rating counts and denominators"),
              ("rating_combinations", "Mutually exclusive rating combinations and union spend"),
              ("high_spend_weak", "Below Average component vs spend_high"),
              ("widespread_pattern", "Cross-campaign weak-component pattern"),
              ("investigation_routing", "Lead/secondary investigation routing"))
    if not uni.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("keyword universe unavailable", uni.missing)
        return
    eligible, excluded = _universe(ctx)
    uni.observe("Keyword universe", eligible_enabled_search=len(eligible), excluded=excluded)
    idc = _km_id(ctx)
    km_needs = {"keyword_metrics": ["campaign_id", "ad_group_id", idc, "cost"]}
    km_missing = [f"keyword_metrics:{c}" for c in km_needs["keyword_metrics"]] if ctx.table("keyword_metrics") is None \
        else [f"keyword_metrics:{c}" for c in ctx.table("keyword_metrics").missing(km_needs["keyword_metrics"])]
    costs: dict = {}
    if km_missing:
        uni.partial("keyword metrics unavailable: spend-based classification skipped", km_missing)
    else:
        costs, problems, unknown = _costs(ctx, eligible)
        for p in problems:
            uni.partial(p)
        if unknown:
            uni.partial(f"{len(unknown)} eligible keywords with unknown period cost")
        by_c: dict = {}
        for key, c in costs.items():
            acc = by_c.setdefault(key[0], {"keywords": 0, "known_cost_keywords": 0, "cost": 0.0})
            acc["keywords"] += 1
            if c is not None:
                acc["known_cost_keywords"] += 1
                acc["cost"] += c
        for cid in sorted(by_c):
            uni.observe(f"Campaign {cid}: keyword cost coverage", campaign_id=cid, **by_c[cid],
                        window=[ctx.period_start, ctx.period_end])

    cc = ctx.check("component_counts", "Per-component rating counts and denominators",
                   {"keywords": list(COMPONENTS)})
    if not cc.runnable:
        for cid, title in titles[1:]:
            ctx.check(cid, title).skip("component ratings unavailable", cc.missing)
        return
    ratings = {key: {c: _rating(k.get(c)) for c in COMPONENTS} for key, k in eligible.items()}
    for comp in COMPONENTS:
        counts = {r: 0 for r in RATINGS + ("UNAVAILABLE",)}
        for rt in ratings.values():
            counts[rt[comp]] += 1
        rated = len(ratings) - counts["UNAVAILABLE"]
        cc.observe(f"Component {comp}: rating counts", component=comp, counts=counts, denominator_rated=rated,
                   denominator_all=len(ratings), below_average_share_rated=V.ratio(counts[BA], rated),
                   below_average_share_all=V.ratio(counts[BA], len(ratings)))

    # -- step 3: combinations + union spend
    rc = ctx.check("rating_combinations", "Mutually exclusive rating combinations and union spend", km_needs)
    combos: dict = {}
    for key in sorted(ratings):
        combo = "/".join(ratings[key][c] for c in COMPONENTS)
        g = combos.setdefault(combo, {"keywords": 0, "cost": 0.0, "unknown_cost": 0})
        g["keywords"] += 1
        c = costs.get(key)
        if c is None:
            g["unknown_cost"] += 1
        else:
            g["cost"] += c
    weak_ids = sorted(k for k, rt in ratings.items() if BA in rt.values())
    union = sum(costs.get(k) or 0.0 for k in weak_ids)
    rc.observe("Rating combinations (expected_ctr/ad_relevance/landing_page_experience)", combinations=combos,
               keywords=len(ratings))
    rc.observe("Union spend of keywords with any Below Average component", keywords=len(weak_ids),
               union_cost=union if rc.runnable else None,
               unknown_cost_keywords=sum(1 for k in weak_ids if costs.get(k) is None), currency=ctx.currency)

    # -- steps 4/6: spend priority
    hs = ctx.check("high_spend_weak", "Below Average component vs spend_high", km_needs)
    flagged: set = set()
    if hs.runnable:
        below: dict = {}
        unresolved = set()
        for key in weak_ids:
            cost = costs.get(key)
            weak = [c for c in COMPONENTS if ratings[key][c] == BA]
            if cost is None:
                continue
            p = ctx.params.get("spend_high", key[0])
            if p.value is not None:
                if cost >= p.value:
                    flagged.add(key)
                    hs.finding("below_average_high_spend", "Warning",
                               {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]},
                               f"Keyword {key[2]} has Below Average {', '.join(weak)} and {cost:.2f} {ctx.currency} "
                               f"period cost >= spend_high {p.value:g}",
                               evidence={"weak_components": weak, "cost": cost, "ratings": ratings[key],
                                         "window": [ctx.period_start, ctx.period_end], "snapshot": ctx.snapshot},
                               calculation={"threshold": "spend_high", "threshold_value": p.value, "source": p.source},
                               recommendation=f"Focused review led by {ROUTE[weak[0]]}; test a copy/page question, "
                                              "not a structural split.",
                               uncertainty="Ratings are current snapshots and not causal weights; cost is exposure.")
                    continue
                bound, bsrc = p.value, p.source
            else:
                bound, bsrc = _spend_high_lower_bound(ctx, key[0])
                if bound is None or cost >= bound:
                    unresolved.add(f"spend_high for campaign {key[0]}: {p.reason}")
                    continue
                bsrc = f"lower bound of spend_high ({bsrc}); full value unresolved: {p.reason}"
            below.setdefault(key[0], []).append({"keyword_id": key[2], "cost": cost, "weak": weak,
                                                "bound": bound, "bound_source": bsrc})
        for cid in sorted(below):
            items = below[cid]
            hs.finding("below_average_below_priority", "Info", {"campaign_id": cid},
                       f"{len(items)} keywords in campaign {cid} have a Below Average component below spend_high",
                       evidence={"keywords": items},
                       recommendation="Batch into routine copy/page reviews; no priority escalation.",
                       uncertainty="Below the spend-priority threshold; diagnostic only.")
        multi: dict = {}
        for key in weak_ids:
            n = sum(1 for c in COMPONENTS if ratings[key][c] == BA)
            if n >= 2 and key not in flagged:
                multi.setdefault(key[0], []).append({"keyword_id": key[2], "below_average_components": n})
        for cid in sorted(multi):
            hs.finding("multiple_below_average", "Info", {"campaign_id": cid},
                       f"{len(multi[cid])} keywords in campaign {cid} have two or three Below Average components",
                       evidence={"keywords": multi[cid]},
                       recommendation="Broader diagnostic scope; not Critical and not a restructure mandate.",
                       uncertainty="No corroborating business harm evaluated here.")
        for u in sorted(unresolved):
            hs.partial(u)

    # -- step 5: widespread pattern
    wp = ctx.check("widespread_pattern", "Cross-campaign weak-component pattern", km_needs)
    if wp.runnable:
        for comp in COMPONENTS:
            per_c: dict = {}
            for key, rt in ratings.items():
                if rt[comp] == "UNAVAILABLE":
                    continue
                acc = per_c.setdefault(key[0], {"rated": 0, "below_average": 0})
                acc["rated"] += 1
                acc["below_average"] += rt[comp] == BA
            hits = sorted(c for c, a in per_c.items() if V.ratio(a["below_average"], a["rated"]) > 0.5)
            scope = {c: {**per_c[c], "share": V.ratio(per_c[c]["below_average"], per_c[c]["rated"])} for c in sorted(per_c)}
            if len(hits) < 2:
                wp.observe(f"Component {comp}: no cross-campaign pattern", component=comp, campaigns_over_50pct=hits,
                           eligible_campaigns=len(per_c), scope=scope,
                           note="single-campaign >50% is a within-campaign pattern only" if hits else "")
                continue
            ids = [k for k in ratings if k[0] in hits and ratings[k][comp] == BA]
            exposure = sum(costs.get(k) or 0.0 for k in ids)
            unknown = sum(1 for k in ids if costs.get(k) is None)
            p = ctx.params.get("spend_material")
            if p.value is None:
                wp.partial(f"spend_material unresolved: {p.reason}")
                continue
            if exposure >= p.value:
                wp.finding("widespread_weak_component", "Warning", {"account_id": ctx.account_id, "component": comp},
                           f"Below Average {comp} on >50% of rated keywords in {len(hits)} campaigns; union exposure "
                           f"{exposure:.2f} {ctx.currency} >= spend_material {p.value:g}",
                           evidence={"campaigns": hits, "scope": scope, "keyword_ids": sorted(k[2] for k in ids),
                                     "unknown_cost_keywords": unknown},
                           calculation={"union_cost": exposure, "threshold_value": p.value, "source": p.source},
                           recommendation=f"Account-level review led by {ROUTE[comp]}.",
                           uncertainty="Triage convention (>50%, >=2 campaigns); not a causal diagnosis.")
            else:
                wp.observe(f"Component {comp}: cross-campaign pattern below material exposure", component=comp,
                           campaigns=hits, union_cost=exposure, spend_material=p.value, scope=scope)

    # -- step 7: routing
    rt_c = ctx.check("investigation_routing", "Lead/secondary investigation routing")
    routing = []
    for key in weak_ids:
        weak = [c for c in COMPONENTS if ratings[key][c] == BA]
        routing.append({"keyword_id": key[2], "campaign_id": key[0], "lead": ROUTE[weak[0]],
                        "secondary": [ROUTE[c] for c in weak[1:]]})
    rt_c.observe("One lead investigation per weak keyword (fixed convention, not causal)", routing=routing,
                 distribution_owner="skill-064", history_owner="skill-066")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
