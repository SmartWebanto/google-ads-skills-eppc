"""check.py — skill-068 deterministic ad-relevance inventory with AI-reviewed intent/copy mismatches.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-068-ad-relevance-gap-identification/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Keywords join ads/metrics/search terms on campaign/ad-group/criterion IDs only; non-SEARCH excluded.
         An ads settings join proves eligibility, not serving. Absent-ad findings need a manifest-complete ads table.
         Warning (deterministic) = BELOW_AVERAGE ad relevance AND keyword cost >= spend_material for ITS campaign;
         unresolved spend_material → Info + partial. Unavailable ratings are Info, never low relevance.
         Literal keyword presence in copy is an observation only; keyword counts never justify a split.
         Semantic mismatch Warning only via ai_review when the ad group's below-average exposure >=
         spend_material AND ctx.mature is True; verify() requires reviewed keyword ids, a quoted keyword/query
         from evidence, verbatim ad copy, an alternative interpretation, and for a split an owner rationale plus
         ad-group clicks >= min_clicks. Nothing is Critical.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial deterministic check
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

SKILL = "skill-068-ad-relevance-gap-identification"
VERSION = "1.0.0"

RATING_COL = "ad_relevance"
_RATINGS = ("BELOW_AVERAGE", "AVERAGE", "ABOVE_AVERAGE")
_BAD_APPROVAL = ("DISAPPROVED", "NOT_ELIGIBLE", "REJECTED")
_METRIC_COLS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def _s(v) -> str:
    return str(v or "").strip()


def _rating(v) -> str | None:
    s = "_".join(_s(v).upper().replace("-", " ").split())
    return s if s in _RATINGS else None


def _active(row) -> bool:
    return _s(row.get("status")).upper() in ("", "ENABLED", "ACTIVE")


def _keywords(ctx, with_metrics: bool) -> tuple[list[dict], int]:
    channel = {_s(c.get("id")): _s(c.get("channel_type")).upper() for c in ctx.rows("campaigns")}
    metrics: dict[tuple, dict] = {}
    if with_metrics:
        for m in ctx.rows("keyword_metrics"):
            k = (_s(m.get("campaign_id")), _s(m.get("ad_group_id")), _s(m.get("keyword_id")))
            acc = metrics.setdefault(k, {c: None for c in _METRIC_COLS})
            for col in _METRIC_COLS:
                v = ctx.money(m.get(col)) if col in ("cost", "conversion_value") else V.num(m.get(col))
                if v is not None:
                    acc[col] = (acc[col] or 0) + v
    out, non_search = [], 0
    for k in sorted(ctx.rows("keywords"), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("ad_group_id")), _s(r.get("id")))):
        if not _active(k):
            continue
        cid, gid, kid = _s(k.get("campaign_id")), _s(k.get("ad_group_id")), _s(k.get("id"))
        if channel.get(cid) not in (None, "", "SEARCH"):
            non_search += 1
            continue
        out.append({"campaign_id": cid, "ad_group_id": gid, "keyword_id": kid, "text": k.get("text"),
                    "match_type": k.get("match_type"), "rating": _rating(k.get(RATING_COL)),
                    "has_metrics": (cid, gid, kid) in metrics,
                    **(metrics.get((cid, gid, kid)) or {c: None for c in _METRIC_COLS})})
    return out, non_search


def _ads_by_group(ctx) -> dict[tuple, dict]:
    groups: dict[tuple, dict] = {}
    for a in sorted(ctx.rows("ads"), key=lambda r: _s(r.get("id"))):
        g = groups.setdefault((_s(a.get("campaign_id")), _s(a.get("ad_group_id"))),
                              {"eligible": [], "paused": [], "disapproved": []})
        if _s(a.get("approval_status")).upper() in _BAD_APPROVAL:
            g["disapproved"].append(_s(a.get("id")))
        elif not _active(a):
            g["paused"].append(_s(a.get("id")))
        else:
            g["eligible"].append({"ad_id": _s(a.get("id")), "headlines": V.split_list(a.get("headlines")),
                                  "descriptions": V.split_list(a.get("descriptions")),
                                  "pinned_positions": a.get("pinned_positions"), "final_url": a.get("final_url")})
    return groups


def run(ctx) -> None:
    """Run keyword/ad eligibility join, ad-relevance inventory, AI intent review, literal-token and split-volume checks.

    Rules:   no_eligible_ads Info only with a complete, untruncated ads table. Warning when BELOW_AVERAGE keyword cost
             ≥ spend_material for its campaign; unresolved threshold/cost or missing rating → Info. semantic_mismatch
             ai_review yields Warning only if ctx.mature True and group exposure ≥ spend_material, else Info.
             Literal-token presence and split volume gates are observations, never findings. Nothing is Critical.
    """
    # -- step 1: keyword ↔ eligible ad join
    join = ctx.check("ad_eligibility_join", "Keywords joined to eligible ads by IDs",
                     {"keywords": ["id", "campaign_id", "ad_group_id", "text"],
                      "ads": ["id", "campaign_id", "ad_group_id", "status"]})
    ads = _ads_by_group(ctx) if join.runnable else {}
    if join.runnable:
        kws_all, _ = _keywords(ctx, with_metrics=False)
        complete = ctx.table("ads").complete is True and not ctx.table("ads").truncated
        if not complete:
            join.partial("ads inventory not certified complete: missing ads not claimed")
        groups = sorted({(k["campaign_id"], k["ad_group_id"]) for k in kws_all})
        state = {"with_eligible_ads": 0, "only_paused_or_disapproved": 0, "no_ads": 0}
        for g in groups:
            a = ads.get(g)
            if a and a["eligible"]:
                state["with_eligible_ads"] += 1
                continue
            state["only_paused_or_disapproved" if a else "no_ads"] += 1
            if complete:
                join.finding("no_eligible_ads", "Info", {"campaign_id": g[0], "ad_group_id": g[1]},
                             f"Ad group {g[1]} has active keywords but no enabled, approved ad",
                             evidence={"paused": (a or {}).get("paused", []),
                                       "disapproved": (a or {}).get("disapproved", []),
                                       "active_keywords": sum(1 for k in kws_all if (k["campaign_id"], k["ad_group_id"]) == g)},
                             recommendation="Restore an eligible ad; semantic ad evaluation is blocked here.",
                             uncertainty="Settings snapshot; eligibility is not serving.")
        join.observe("Ad groups with active keywords by ad eligibility", ad_groups=len(groups), **state)

    # -- step 2: rating inventory
    inv = ctx.check("ad_relevance_inventory", "Ad relevance ratings ranked by cost exposure",
                    {"keywords": ["id", "campaign_id", "ad_group_id", "text", RATING_COL],
                     "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost"]})
    later = (("intent_theme_review", "Intent/theme versus eligible copy (analyst judgment)"),
             ("literal_token_presence", "Literal keyword presence in eligible copy (observation only)"),
             ("split_volume_gate", "Volume evidence for any proposed ad-group split"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("ad relevance ratings or keyword metrics unavailable", inv.missing)
        return
    kws, non_search = _keywords(ctx, with_metrics=True)
    weak = [k for k in kws if k["rating"] == "BELOW_AVERAGE"]
    unknown = [k for k in kws if k["rating"] is None]
    pending: dict[str, list] = {}
    unresolved: set[str] = set()
    ranked = []
    for k in sorted(weak, key=lambda k: (-(k["cost"] or 0), k["campaign_id"], k["keyword_id"])):
        thr = ctx.params.get("spend_material", k["campaign_id"])
        ent = {"campaign_id": k["campaign_id"], "ad_group_id": k["ad_group_id"], "keyword_id": k["keyword_id"]}
        ranked.append({**ent, "cost": k["cost"]})
        if thr.value is None or k["cost"] is None:
            if thr.value is None:
                unresolved.add(f"{k['campaign_id']}: {thr.reason}")
            pending.setdefault(k["campaign_id"], []).append(
                {**ent, "text": k["text"], "cost": k["cost"], "reason": thr.reason if thr.value is None else "cost unknown"})
        elif k["cost"] >= thr.value:
            inv.finding("below_average_ad_relevance_material", "Warning", ent,
                        f"Keyword '{k['text']}' has Below Average ad relevance with cost {k['cost']:.2f} "
                        f"{ctx.currency} >= spend_material {thr.value:g}",
                        evidence={"keyword_text": k["text"], "match_type": k["match_type"], "ad_relevance": "BELOW_AVERAGE",
                                  "cost": k["cost"], "impressions": k["impressions"], "clicks": k["clicks"],
                                  "conversions": k["conversions"], "window": [ctx.period_start, ctx.period_end],
                                  "rating_snapshot": ctx.snapshot,
                                  "rated_denominator": len(kws) - len(unknown), "total_denominator": len(kws)},
                        calculation={"threshold": "spend_material", "threshold_value": thr.value,
                                     "threshold_source": thr.source},
                        recommendation="Review intent themes against eligible copy (see ai_review); copy first, "
                                       "split only with owner-confirmed rationale and volume.",
                        uncertainty="A component rating prioritizes review; it does not prove mismatch for every query.")
    for u in sorted(unresolved):
        inv.partial(f"spend_material unresolved for campaign {u}")
    for cid in sorted(pending):
        inv.finding("below_average_ad_relevance_exposure_unresolved", "Info", {"campaign_id": cid},
                    f"{len(pending[cid])} Below Average ad-relevance keywords in campaign {cid} could not be "
                    f"classified against spend_material",
                    evidence={"keywords": pending[cid], "window": [ctx.period_start, ctx.period_end]},
                    recommendation="Resolve spend_material or supply keyword metrics to prioritize.",
                    uncertainty="Materiality not assessed; unknown is not low.")
    if unknown:
        inv.finding("ad_relevance_unavailable", "Info", {"rating": "unavailable"},
                    f"{len(unknown)} of {len(kws)} active Search keywords have no ad-relevance rating",
                    evidence={"keyword_ids": [f"{k['campaign_id']}/{k['ad_group_id']}/{k['keyword_id']}" for k in unknown]},
                    recommendation="Treat as unknown; do not infer low relevance.",
                    uncertainty="Ratings are withheld for low-volume keywords.")
    inv.observe("Ad relevance inventory", active_search_keywords=len(kws), rated=len(kws) - len(unknown),
                below_average=len(weak), average=sum(1 for k in kws if k["rating"] == "AVERAGE"),
                above_average=sum(1 for k in kws if k["rating"] == "ABOVE_AVERAGE"), unknown=len(unknown),
                excluded_non_search=non_search, ranked_by_cost=ranked,
                keywords_without_metrics=sum(1 for k in kws if not k["has_metrics"]))

    weak_groups = sorted({(k["campaign_id"], k["ad_group_id"]) for k in weak})
    mi, mc, mv = (ctx.params.get(n).value for n in ("min_impressions", "min_clicks", "min_conversions"))

    # -- steps 3-4: AI intent/theme review per weak ad group
    rev = ctx.check("intent_theme_review", "Intent/theme versus eligible copy (analyst judgment)",
                    {"ads": ["id", "campaign_id", "ad_group_id", "status", "headlines", "descriptions"]})
    group_volume: dict[tuple, dict] = {}
    for k in kws:
        v = group_volume.setdefault((k["campaign_id"], k["ad_group_id"]),
                                    {"keywords": 0, "impressions": 0.0, "clicks": 0.0, "conversions": 0.0, "cost": 0.0})
        v["keywords"] += 1
        for c in ("impressions", "clicks", "conversions", "cost"):
            v[c] += k[c] or 0
    if rev.runnable:
        if ctx.mature is not True:
            rev.partial(f"semantic-mismatch Warning disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        if not ctx.profile.get("campaign_objectives") and not ctx.profile.get("objectives"):
            rev.partial("owner objectives missing: desired intent uncertain")
        terms: dict[str, list] = {}
        st = ctx.table("search_terms")
        if st is not None and not st.missing(["search_term", "matched_keyword_id", "campaign_id", "ad_group_id"]):
            for r in ctx.rows("search_terms"):
                terms.setdefault("/".join((_s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                           _s(r.get("matched_keyword_id")))), []).append(
                    {"search_term": r.get("search_term"), "impressions": V.num(r.get("impressions")),
                     "clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")),
                     "conversions": V.num(r.get("conversions"))})
        else:
            rev.partial("search_terms with matched_keyword_id unavailable: query-level intent not observed")
        objectives = ctx.profile.get("campaign_objectives") or {}
        for g in weak_groups:
            pool = (ads.get(g) or {}).get("eligible") or []
            if not pool:
                rev.partial(f"ad group {g[0]}/{g[1]}: no eligible ads, semantic review blocked")
                continue
            members = [k for k in weak if (k["campaign_id"], k["ad_group_id"]) == g]
            exposure = sum(k["cost"] or 0 for k in members)
            thr = ctx.params.get("spend_material", g[0])
            if thr.value is None:
                rev.partial(f"ad group {g[0]}/{g[1]}: Warning outcome disabled, spend_material unresolved ({thr.reason})")
            material = ctx.mature is True and thr.value is not None and exposure >= thr.value
            rev.review("semantic_mismatch", {"campaign_id": g[0], "ad_group_id": g[1]},
                       f"Do the eligible ads in ad group {g[1]} fail to address the intent/offer of its Below Average "
                       f"ad-relevance keywords (not merely their literal wording)?",
                       evidence={"keywords": [{"keyword_id": k["keyword_id"], "text": k["text"],
                                               "match_type": k["match_type"], "cost": k["cost"],
                                               "search_terms": sorted(terms.get(f"{g[0]}/{g[1]}/{k['keyword_id']}", []),
                                                                      key=lambda t: (-(t["cost"] or 0), str(t["search_term"])))}
                                              for k in members],
                                 "other_keywords": [k["text"] for k in kws
                                                    if (k["campaign_id"], k["ad_group_id"]) == g and k["rating"] != "BELOW_AVERAGE"],
                                 "ads": pool, "below_average_exposure": exposure, "ad_group_volume": group_volume[g],
                                 "spend_material": thr.value, "spend_material_source": thr.source or thr.reason,
                                 "min_clicks": mc, "mature": ctx.mature,
                                 "objectives": ctx.profile.get("objectives"),
                                 "campaign_objective": objectives.get(g[0]) if isinstance(objectives, dict) else None,
                                 "brand_terms": ctx.profile.get("brand_terms"),
                                 "competitor_terms": ctx.profile.get("competitor_terms"),
                                 "excluded_intents": ctx.profile.get("excluded_intents")},
                       outcomes={
                           "semantic_mismatch_evidenced": {"severity": "Warning" if material else "Info",
                                                           "recommendation": "Owner-reviewed copy change first; split "
                                                           "only with independent offer/landing need and volume."},
                           "copy_improvement_possible": {"severity": "Info", "recommendation":
                                                         "Optional copy/theme improvement for owner confirmation."},
                           "valid_paraphrase_no_gap": {"severity": None, "recommendation": "No change."},
                           "uncertain": {"severity": "Info", "recommendation": "Ask the owner which intent is desired."},
                       },
                       guidance="Keyword counts and lexical similarity are discovery aids, not intent classes; synonyms "
                                "and paraphrases can fit. For mismatch/improvement supply proposal {keyword_ids, "
                                "quoted_keyword_or_query, quoted_copy: [verbatim ad texts], alternative_interpretation, "
                                "action: copy|split, owner_rationale (required for split)}.")

    # -- step 5: literal token observation (never adverse)
    lit = ctx.check("literal_token_presence", "Literal keyword presence in eligible copy (observation only)",
                    {"ads": ["id", "campaign_id", "ad_group_id", "headlines", "descriptions"]})
    if lit.runnable:
        for g in weak_groups:
            pool = (ads.get(g) or {}).get("eligible") or []
            text = V.norm_text(" ".join(t for a in pool for t in a["headlines"] + a["descriptions"]))
            members = [k for k in weak if (k["campaign_id"], k["ad_group_id"]) == g]
            lit.observe(f"Literal keyword text in eligible copy of {g[0]}/{g[1]} (not a relevance verdict)",
                        campaign_id=g[0], ad_group_id=g[1], eligible_ads=len(pool),
                        literal_present=[k["keyword_id"] for k in members if pool and V.norm_text(k["text"]) in text],
                        literal_absent=[k["keyword_id"] for k in members if pool and V.norm_text(k["text"]) not in text])

    # -- step 6: split evidence volume
    spl = ctx.check("split_volume_gate", "Volume evidence for any proposed ad-group split")
    if ctx.mature is not True:
        spl.partial(f"conversion volume not mature: {ctx.maturity_note}")
    for g in weak_groups:
        v = group_volume[g]
        spl.observe(f"Ad group {g[0]}/{g[1]} volume (keyword count is not a split reason)", campaign_id=g[0],
                    ad_group_id=g[1], **v, clicks_gate=v["clicks"] >= mc, impressions_gate=v["impressions"] >= mi,
                    conversions_gate=ctx.mature is True and v["conversions"] >= mv)


def verify(ctx, item, decision) -> list[str]:
    """Rules: quotes must come from the reviewed evidence; a split needs rationale and volume."""
    outcome = decision.get("outcome")
    if outcome not in ("semantic_mismatch_evidenced", "copy_improvement_possible"):
        return []
    p = decision.get("proposal") or {}
    ev = item.evidence
    problems = []
    reviewed = {k["keyword_id"] for k in ev.get("keywords", [])}
    ids = [str(x) for x in p.get("keyword_ids") or []]
    if not ids:
        problems.append("proposal.keyword_ids required")
    problems += [f"keyword {x} not in reviewed ad group" for x in ids if x not in reviewed]
    sources = {V.norm_text(k["text"]) for k in ev.get("keywords", [])} | {
        V.norm_text(t["search_term"]) for k in ev.get("keywords", []) for t in k.get("search_terms", [])}
    q = V.norm_text(p.get("quoted_keyword_or_query"))
    if not q or q not in sources:
        problems.append("proposal.quoted_keyword_or_query must be a reviewed keyword text or observed search term")
    copy = {V.norm_text(t) for a in ev.get("ads", []) for t in a["headlines"] + a["descriptions"]}
    quotes = p.get("quoted_copy") or []
    if not quotes:
        problems.append("proposal.quoted_copy required (verbatim reviewed ad texts)")
    problems += [f"quoted copy not found in reviewed ads: {x!r}" for x in quotes if V.norm_text(x) not in copy]
    if outcome == "semantic_mismatch_evidenced" and not _s(p.get("alternative_interpretation")):
        problems.append("proposal.alternative_interpretation required")
    if _s(p.get("action")).lower() == "split":
        if not _s(p.get("owner_rationale")):
            problems.append("split proposals need proposal.owner_rationale (owner-confirmed operational reason)")
        vol = ev.get("ad_group_volume") or {}
        if (vol.get("clicks") or 0) < (ev.get("min_clicks") or 0):
            problems.append(f"split rejected: ad-group clicks {vol.get('clicks')} < min_clicks {ev.get('min_clicks')}")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
