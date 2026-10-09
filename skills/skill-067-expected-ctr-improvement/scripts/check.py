"""check.py — skill-067 deterministic expected-CTR triage with AI-reviewed contextual copy hypotheses.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-067-expected-ctr-improvement/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Expected CTR is Google's rating, never observed CTR; missing ratings are not low CTR.
         Keywords join metrics/ads/assets on campaign/ad-group/criterion IDs only; non-SEARCH campaigns excluded.
         Warning (deterministic) = BELOW_AVERAGE expected CTR AND keyword cost >= spend_high for ITS campaign;
         unresolved spend_high → Info + partial. Literal keyword absence is an observation, never adverse.
         Peer CTR verdicts need custom/keyword_ctr_context segments with BOTH sides >= min_impressions;
         without it CTR is descriptive only (partial).
         Copy-gap Warning only via ai_review when the ad group's below-average exposure >= spend_high AND
         ctx.mature is True; verify() requires quoted copy from the reviewed ads, reviewed keyword ids,
         a hypothesis and a success metric. Asset applicability comes from profile.expected_asset_types
         (list of asset types); without it no absence is claimed. Nothing is Critical.
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

SKILL = "skill-067-expected-ctr-improvement"
VERSION = "1.0.0"

RATING_COL = "expected_ctr"
KW_NEEDS = {"keywords": ["id", "campaign_id", "ad_group_id", "text", RATING_COL],
            "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost"]}
_RATINGS = ("BELOW_AVERAGE", "AVERAGE", "ABOVE_AVERAGE")
_BAD_APPROVAL = ("DISAPPROVED", "NOT_ELIGIBLE", "REJECTED")


def _rating(v) -> str | None:
    s = "_".join(str(v or "").strip().upper().replace("-", " ").split())
    return s if s in _RATINGS else None


def _s(v) -> str:
    return str(v or "").strip()


def _active(row) -> bool:
    return _s(row.get("status")).upper() in ("", "ENABLED", "ACTIVE")


def _keywords(ctx) -> tuple[list[dict], int]:
    """Active Search keywords with summed metrics joined by IDs. Returns (rows, excluded_non_search)."""
    channel = {_s(c.get("id")): _s(c.get("channel_type")).upper() for c in ctx.rows("campaigns")}
    metrics: dict[tuple, dict] = {}
    for m in ctx.rows("keyword_metrics"):
        k = (_s(m.get("campaign_id")), _s(m.get("ad_group_id")), _s(m.get("keyword_id")))
        acc = metrics.setdefault(k, {"impressions": None, "clicks": None, "cost": None, "conversions": None,
                                     "conversion_value": None, "metric_rows": 0})
        acc["metric_rows"] += 1
        for col in ("impressions", "clicks", "cost", "conversions", "conversion_value"):
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
        met = metrics.get((cid, gid, kid), {"metric_rows": 0})
        out.append({"campaign_id": cid, "ad_group_id": gid, "keyword_id": kid, "text": k.get("text"),
                    "match_type": k.get("match_type"), "rating": _rating(k.get(RATING_COL)),
                    "impressions": met.get("impressions"), "clicks": met.get("clicks"), "cost": met.get("cost"),
                    "conversions": met.get("conversions"), "metric_rows": met["metric_rows"]})
    return out, non_search


def _ads_by_group(ctx) -> dict[tuple, dict]:
    groups: dict[tuple, dict] = {}
    for a in sorted(ctx.rows("ads"), key=lambda r: _s(r.get("id"))):
        g = groups.setdefault((_s(a.get("campaign_id")), _s(a.get("ad_group_id"))),
                              {"eligible": [], "paused": [], "disapproved": []})
        approval = _s(a.get("approval_status")).upper()
        if approval in _BAD_APPROVAL:
            g["disapproved"].append(_s(a.get("id")))
        elif not _active(a):
            g["paused"].append(_s(a.get("id")))
        else:
            g["eligible"].append({"ad_id": _s(a.get("id")), "headlines": V.split_list(a.get("headlines")),
                                  "descriptions": V.split_list(a.get("descriptions")),
                                  "pinned_positions": a.get("pinned_positions"), "final_url": a.get("final_url")})
    return groups


def run(ctx) -> None:
    """Run expected-CTR inventory, peer CTR context, eligible ad pool, copy-gap and asset-applicability checks.

    Rules:   BELOW_AVERAGE rating with keyword cost >= spend_high (its campaign) → Warning; unresolved spend_high → Info
             + partial. Missing ratings are Info, never low CTR; non-SEARCH campaigns excluded. Peer CTR verdicts need
             both segments >= min_impressions, else descriptive. Copy gap (Warning) only via ai_review when exposure >=
             spend_high and ctx.mature True; asset absence only against profile.expected_asset_types. Nothing is
             Critical.
    """
    inv = ctx.check("ectr_inventory", "Below Average expected CTR ranked by cost exposure", KW_NEEDS)
    later = (("ctr_context", "Actual CTR and segmented peer context"),
             ("ad_pool", "Eligible ad pools for weak-rated keywords"),
             ("copy_review", "Contextual copy review (analyst judgment)"),
             ("asset_review", "Effective asset coverage for weak-rated ad groups"),
             ("comparison_readiness", "Sample readiness for an owner-reviewed comparison"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("keyword ratings or metrics unavailable", inv.missing)
        return
    kws, non_search = _keywords(ctx)
    weak = [k for k in kws if k["rating"] == "BELOW_AVERAGE"]
    unknown = [k for k in kws if k["rating"] is None]
    unresolved: set[str] = set()
    ranked = []
    pending: dict[str, list] = {}
    for k in sorted(weak, key=lambda k: (-(k["cost"] or 0), k["campaign_id"], k["keyword_id"])):
        thr = ctx.params.get("spend_high", k["campaign_id"])
        k["threshold"], k["threshold_source"] = thr.value, thr.source or thr.reason
        ent = {"campaign_id": k["campaign_id"], "ad_group_id": k["ad_group_id"], "keyword_id": k["keyword_id"]}
        ev = {"keyword_text": k["text"], "match_type": k["match_type"], "expected_ctr": "BELOW_AVERAGE",
              "cost": k["cost"], "impressions": k["impressions"], "clicks": k["clicks"],
              "actual_ctr": V.ratio(k["clicks"], k["impressions"]), "window": [ctx.period_start, ctx.period_end],
              "rating_snapshot": ctx.snapshot}
        calc = {"threshold": "spend_high", "threshold_value": thr.value, "threshold_source": k["threshold_source"]}
        ranked.append({**ent, "cost": k["cost"]})
        if thr.value is None or k["cost"] is None:
            if thr.value is None:
                unresolved.add(f"{k['campaign_id']}: {thr.reason}")
            pending.setdefault(k["campaign_id"], []).append({**ent, "text": k["text"], "cost": k["cost"],
                                                             "reason": "cost unknown" if thr.value is not None
                                                             else thr.reason})
        elif k["cost"] >= thr.value:
            inv.finding("below_average_ectr_high_cost", "Warning", ent,
                        f"Keyword '{k['text']}' has Below Average expected CTR with cost {k['cost']:.2f} "
                        f"{ctx.currency} >= spend_high {thr.value:g}",
                        evidence=ev, calculation=calc,
                        recommendation="Prioritize a contextual copy/asset review; no forced keyword insertion.",
                        uncertainty="Expected CTR is a diagnostic rating, not observed CTR or a CPC-savings formula.")
    for u in sorted(unresolved):
        inv.partial(f"spend_high unresolved for campaign {u}")
    for cid in sorted(pending):
        inv.finding("below_average_ectr_exposure_unresolved", "Info", {"campaign_id": cid},
                    f"{len(pending[cid])} Below Average expected-CTR keywords in campaign {cid} could not be "
                    f"classified against spend_high",
                    evidence={"keywords": pending[cid], "window": [ctx.period_start, ctx.period_end]},
                    recommendation="Resolve spend_high (30-day spend or override) or supply metrics to prioritize.",
                    uncertainty="Materiality not assessed; unknown is not low.")
    if unknown:
        inv.finding("ectr_rating_unavailable", "Info", {"rating": "unavailable"},
                    f"{len(unknown)} of {len(kws)} active Search keywords have no expected-CTR rating",
                    evidence={"keyword_ids": [f"{k['campaign_id']}/{k['ad_group_id']}/{k['keyword_id']}" for k in unknown]},
                    recommendation="Treat as unknown, not low CTR; re-check once volume accrues.",
                    uncertainty="Ratings are withheld for low-volume keywords.")
    inv.observe("Expected-CTR inventory", active_search_keywords=len(kws), rated=len(kws) - len(unknown),
                below_average=len(weak), average=sum(1 for k in kws if k["rating"] == "AVERAGE"),
                above_average=sum(1 for k in kws if k["rating"] == "ABOVE_AVERAGE"), unknown=len(unknown),
                excluded_non_search=non_search, ranked_by_cost=ranked,
                keywords_without_metrics=sum(1 for k in kws if k["metric_rows"] == 0))

    mi, mc, mv = (ctx.params.get(n).value for n in ("min_impressions", "min_clicks", "min_conversions"))

    # -- step 2: actual CTR, peer comparison only with segmented context
    ctr = ctx.check("ctr_context", "Actual CTR and segmented peer context")
    for k in weak:
        ctr.observe(f"Actual CTR for {k['campaign_id']}/{k['ad_group_id']}/{k['keyword_id']} (not expected CTR)",
                    keyword_id=k["keyword_id"], impressions=k["impressions"], clicks=k["clicks"],
                    actual_ctr=V.ratio(k["clicks"], k["impressions"]),
                    sample_ok=(k["impressions"] or 0) >= mi)
    seg = ctx.table("custom/keyword_ctr_context")
    seg_cols = ["campaign_id", "ad_group_id", "criterion_id", "device", "network", "impressions", "clicks"]
    if seg is None or seg.missing(seg_cols):
        ctr.partial("no segmented context: descriptive CTR only, no peer verdict",
                    ["custom/keyword_ctr_context (file)"] if seg is None
                    else [f"custom/keyword_ctr_context:{c}" for c in seg.missing(seg_cols)])
    else:
        cells: dict[tuple, list[float]] = {}
        for r in ctx.rows("custom/keyword_ctr_context"):
            i, c = V.num(r.get("impressions")), V.num(r.get("clicks"))
            if i is None or c is None:
                continue
            key = (_s(r.get("campaign_id")), _s(r.get("device")).upper(), _s(r.get("network")).upper(),
                   _s(r.get("ad_group_id")), _s(r.get("criterion_id")))
            acc = cells.setdefault(key, [0.0, 0.0])
            acc[0] += i
            acc[1] += c
        for k in weak:
            for key in sorted(x for x in cells if x[0] == k["campaign_id"] and x[3:] == (k["ad_group_id"], k["keyword_id"])):
                own = cells[key]
                peers = [v for x, v in cells.items() if x[:3] == key[:3] and x[3:] != key[3:]]
                pi, pc = sum(v[0] for v in peers), sum(v[1] for v in peers)
                ok = own[0] >= mi and pi >= mi
                ctr.observe(f"Segment CTR {k['keyword_id']} {key[1]}/{key[2]} vs same-campaign peers",
                            keyword_id=k["keyword_id"], device=key[1], network=key[2], impressions=own[0],
                            ctr=V.ratio(own[1], own[0]), peer_impressions=pi, peer_ctr=V.ratio(pc, pi),
                            comparable=ok, min_impressions=mi)

    # -- step 3: eligible ad pools
    pool = ctx.check("ad_pool", "Eligible ad pools for weak-rated keywords",
                     {"ads": ["id", "campaign_id", "ad_group_id", "status"]})
    ads = _ads_by_group(ctx) if pool.runnable else {}
    weak_groups = sorted({(k["campaign_id"], k["ad_group_id"]) for k in weak})
    if pool.runnable:
        ads_complete = ctx.table("ads").complete is True and not ctx.table("ads").truncated
        for g in weak_groups:
            a = ads.get(g, {"eligible": [], "paused": [], "disapproved": []})
            pool.observe(f"Ad pool for ad group {g[0]}/{g[1]} (eligibility, not serving)", campaign_id=g[0],
                         ad_group_id=g[1], eligible=[x["ad_id"] for x in a["eligible"]], paused=a["paused"],
                         disapproved=a["disapproved"],
                         pinned=[x["ad_id"] for x in a["eligible"] if _s(x["pinned_positions"])])
            if not a["eligible"] and ads_complete:
                pool.finding("no_eligible_ad_pool", "Info", {"campaign_id": g[0], "ad_group_id": g[1]},
                             f"Ad group {g[1]} has weak expected-CTR keywords but no enabled, approved ad",
                             evidence={"paused": a["paused"], "disapproved": a["disapproved"]},
                             recommendation="Restore an eligible ad before any copy review.",
                             uncertainty="Settings snapshot; eligibility is not serving.")
        if not ads_complete:
            pool.partial("ads inventory not certified complete: absent ad pools not claimed")

    # -- steps 4 + 6: AI copy review per weak ad group
    rev = ctx.check("copy_review", "Contextual copy review (analyst judgment)",
                    {"ads": ["id", "campaign_id", "ad_group_id", "status", "headlines", "descriptions"]})
    if rev.runnable:
        if ctx.mature is not True:
            rev.partial(f"copy-gap Warning disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        terms: dict[str, list] = {}
        st = ctx.table("search_terms")
        if st is not None and not st.missing(["search_term", "matched_keyword_id", "campaign_id", "ad_group_id"]):
            for r in ctx.rows("search_terms"):
                terms.setdefault("/".join((_s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                           _s(r.get("matched_keyword_id")))), []).append(
                    {"search_term": r.get("search_term"), "impressions": V.num(r.get("impressions")),
                     "clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost"))})
        else:
            rev.partial("search_terms with matched_keyword_id unavailable: query intent partially observed")
        objectives = ctx.profile.get("campaign_objectives") or {}
        for g in weak_groups:
            pool_ads = ads.get(g, {}).get("eligible") or []
            if not pool_ads:
                continue
            members = [k for k in weak if (k["campaign_id"], k["ad_group_id"]) == g]
            copy_text = V.norm_text(" ".join(h for a in pool_ads for h in a["headlines"] + a["descriptions"]))
            exposure = sum(k["cost"] or 0 for k in members)
            thr = ctx.params.get("spend_high", g[0])
            material = ctx.mature is True and thr.value is not None and exposure >= thr.value
            if thr.value is None:
                rev.partial(f"ad group {g[0]}/{g[1]}: copy-gap Warning outcome disabled, spend_high unresolved "
                            f"({thr.reason})")
            rev.review("contextual_copy_gap", {"campaign_id": g[0], "ad_group_id": g[1]},
                       f"Do the eligible ads in ad group {g[1]} miss the intent, benefit or differentiation of its "
                       f"Below Average expected-CTR keywords, beyond literal keyword wording?",
                       evidence={"keywords": [{"keyword_id": k["keyword_id"], "text": k["text"],
                                               "match_type": k["match_type"], "cost": k["cost"],
                                               "impressions": k["impressions"], "clicks": k["clicks"],
                                               "literal_text_in_copy": V.norm_text(k["text"]) in copy_text,
                                               "search_terms": sorted(terms.get(f"{g[0]}/{g[1]}/{k['keyword_id']}", []),
                                                                      key=lambda t: (-(t["cost"] or 0), str(t["search_term"])))}
                                              for k in members],
                                 "ads": pool_ads, "below_average_exposure": exposure,
                                 "spend_high": thr.value, "spend_high_source": thr.source or thr.reason,
                                 "mature": ctx.mature, "brand_terms": ctx.profile.get("brand_terms"),
                                 "objectives": ctx.profile.get("objectives"),
                                 "campaign_objective": objectives.get(g[0]) if isinstance(objectives, dict) else None,
                                 "excluded_intents": ctx.profile.get("excluded_intents")},
                       outcomes={
                           "documented_copy_gap": {"severity": "Warning" if material else "Info", "recommendation":
                                                   "Owner-reviewed creative hypothesis with a conversion-quality "
                                                   "guardrail and a mature review window."},
                           "untested_copy_hypothesis": {"severity": "Info", "recommendation":
                                                        "Optional copy test; not an account failure."},
                           "copy_relevant_no_gap": {"severity": None, "recommendation": "No copy change."},
                           "uncertain": {"severity": "Info", "recommendation": "Ask the owner which intent matters."},
                       },
                       guidance="Literal keyword absence is NOT a gap; synonyms, brand-led copy and paraphrases can fit. "
                                "For documented_copy_gap/untested_copy_hypothesis supply proposal {keyword_ids, "
                                "quoted_copy: [exact headline/description texts from evidence], hypothesis, "
                                "success_metric}. Label conclusions as analyst judgment.")

    # -- step 5: assets
    ast = ctx.check("asset_review", "Effective asset coverage for weak-rated ad groups")
    at = ctx.table("assets")
    id_col = next((c for c in ("asset_id", "id") if at is not None and c in at.columns), None)
    lvl_col = next((c for c in ("level", "association_level") if at is not None and c in at.columns), None)
    if at is None or id_col is None or lvl_col is None or at.missing(["type", "status"]):
        miss = ["assets (file)"] if at is None else (
            [f"assets:{c}" for c in at.missing(["type", "status"])]
            + (["assets:asset_id|id"] if id_col is None else []) + (["assets:level|association_level"] if lvl_col is None else []))
        ast.skip("asset associations unavailable: no absence claims", miss)
    else:
        expected = sorted({_s(t).upper() for t in (ctx.profile.get("expected_asset_types") or []) if _s(t)})
        complete = at.complete is True and not at.truncated
        if not expected:
            ast.partial("profile.expected_asset_types not supplied: applicable asset types not judged")
        if not complete:
            ast.partial("assets inventory not certified complete: absence not provable")
        for g in weak_groups:
            eff, disapproved = {}, []
            for r in ctx.rows("assets"):
                lvl = _s(r.get(lvl_col)).lower()
                ok = (lvl in ("account", "customer") or (lvl == "campaign" and _s(r.get("campaign_id")) == g[0])
                      or (lvl == "ad_group" and (_s(r.get("campaign_id")), _s(r.get("ad_group_id"))) == g))
                if not ok:
                    continue
                t = _s(r.get("type")).upper()
                if _s(r.get("approval_status")).upper() in _BAD_APPROVAL:
                    disapproved.append(f"{t}:{_s(r.get(id_col))}")
                elif _active(r):
                    eff.setdefault(t, []).append(f"{lvl}:{_s(r.get(id_col))}")
            ast.observe(f"Effective assets for {g[0]}/{g[1]} (inherited levels included)", campaign_id=g[0],
                        ad_group_id=g[1], eligible={t: sorted(v) for t, v in sorted(eff.items())},
                        disapproved=sorted(disapproved))
            absent = [t for t in expected if t not in eff]
            if expected and complete and absent:
                ast.finding("optional_asset_opportunity", "Info", {"campaign_id": g[0], "ad_group_id": g[1]},
                            f"Ad group {g[1]} (weak expected CTR) has no eligible {', '.join(absent)} asset at any level",
                            evidence={"absent_types": absent, "expected_asset_types": expected,
                                      "disapproved": sorted(disapproved)},
                            recommendation="Optional asset opportunity; add only relevant, policy-compliant assets.",
                            uncertainty="Asset absence is an opportunity, not a guaranteed CTR gain.")

    # -- step 7: comparison readiness
    rdy = ctx.check("comparison_readiness", "Sample readiness for an owner-reviewed comparison")
    if ctx.mature is not True:
        rdy.partial(f"conversion guardrails not assessable: maturity={ctx.mature} ({ctx.maturity_note})")
    short = []
    for k in weak:
        gaps = [n for n, v, gate in (("impressions", k["impressions"], mi), ("clicks", k["clicks"], mc),
                                     ("conversions", k["conversions"], mv)) if (v or 0) < gate]
        if gaps:
            short.append({"keyword_id": k["keyword_id"], "campaign_id": k["campaign_id"],
                          "ad_group_id": k["ad_group_id"], "below_gate": gaps})
    if short:
        rdy.finding("insufficient_comparison_sample", "Info", {"cohort": "below_average_expected_ctr"},
                    f"{len(short)} of {len(weak)} Below Average keywords lack the samples for a guarded comparison",
                    evidence={"keywords": short, "gates": {"min_impressions": mi, "min_clicks": mc,
                                                           "min_conversions": mv}},
                    recommendation="Evaluate copy changes at ad-group/campaign grain or over a longer mature window.",
                    uncertainty="Sample gates are count thresholds, not significance tests.")
    rdy.observe("Comparison readiness", below_average=len(weak), insufficient=len(short), mature=ctx.mature)


def verify(ctx, item, decision) -> list[str]:
    """Rules: gap/hypothesis outcomes need reviewed keyword ids, verbatim quoted copy, hypothesis and success metric."""
    if decision.get("outcome") not in ("documented_copy_gap", "untested_copy_hypothesis"):
        return []
    p = decision.get("proposal") or {}
    problems = []
    reviewed = {k["keyword_id"] for k in item.evidence.get("keywords", [])}
    ids = [str(x) for x in p.get("keyword_ids") or []]
    if not ids:
        problems.append("proposal.keyword_ids required")
    problems += [f"keyword {x} not in reviewed ad group" for x in ids if x not in reviewed]
    copy = {V.norm_text(t) for a in item.evidence.get("ads", []) for t in a["headlines"] + a["descriptions"]}
    quotes = p.get("quoted_copy") or []
    if not quotes:
        problems.append("proposal.quoted_copy required (exact reviewed headline/description texts)")
    problems += [f"quoted copy not found in reviewed ads: {q!r}" for q in quotes if V.norm_text(q) not in copy]
    for f in ("hypothesis", "success_metric"):
        if not _s(p.get(f)):
            problems.append(f"proposal.{f} required")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
