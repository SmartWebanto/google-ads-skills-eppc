"""check.py — skill-020 deterministic low-performing keyword screening with guarded review hand-off.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-020-low-performing-keyword-pruning/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #103 Keyword Performance Report (developers.google.com) — clean-room reimplementation of the
         per-keyword performance/Quality Score summary as descriptive observations (never a pause signal)
rules:   Target CPA comes ONLY from ctx.params (campaign → portfolio → campaign objective → profile); the
         same resolved target feeds spend_floor via ctx.params.get("spend_floor", campaign_id).
         Target ROAS is resolved privately with the same precedence and is NEVER substituted for CPA.
         Keyword metrics join keywords on (campaign_id, ad_group_id, keyword_id); duplicate grain rows
         without a declared segment column are fan-out → the keyword is excluded and the check is partial.
         Performance prescriptions need ctx.mature True AND ctx.tracking_for_campaign(cid) True; otherwise
         the dependent check is partial and no Warning path is produced (exposure inventory only).
         Zero-conversion keywords reach Warning only through AI review (relevance/role); CPA > 2x target
         with >= min_conversions on the keyword is a deterministic Warning. QS/CTR never create findings.
         verify(): Warning outcomes need proposal.action in ACTIONS; 'bid_reduction' only under MANUAL_CPC.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
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

SKILL = "skill-020-low-performing-keyword-pruning"
VERSION = "1.0.0"

KM = {"keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"]}
QUERY_COLS = ["search_term", "campaign_id", "ad_group_id", "matched_keyword_id", "clicks", "cost", "conversions"]
SEGMENT_COLS = ("date", "day", "week", "month", "device", "network", "ad_network_type", "segment", "hour")
ACTIONS = ("monitor", "query_review", "messaging_review", "pause_trial", "bid_reduction")
MANUAL = ("MANUAL_CPC",)


def _pos(v):
    f = V.num(v)
    return f if f is not None and f > 0 else None


def _note(check, text: str) -> None:
    """Record a partial-coverage note once per check."""
    if text not in check.notes:
        check.partial(text)


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion maturity",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature, maturity_note=ctx.maturity_note,
              conversion_date_basis=ctx.account.get("conversion_date_basis"))


def _strategy(ctx, cid: str) -> dict | None:
    camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None)
    rows = ctx.rows("bidding_strategies")
    sid = (camp or {}).get("bidding_strategy_id") or (camp or {}).get("strategy_id")
    row = next((r for r in rows if sid and str(r.get("id")) == str(sid)), None)
    if row is None:
        row = next((r for r in sorted(rows, key=lambda r: str(r.get("id")))
                    if cid in V.split_list(r.get("campaign_ids"), (";", "|", ","))), None)
    return row


def _target_roas(ctx, cid: str) -> tuple[float | None, str]:
    """Campaign → portfolio → profile campaign objective → profile.target_roas; mirrors CPA precedence."""
    camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None) or {}
    t = _pos(camp.get("target_roas"))
    if t:
        return t, f"campaigns.target_roas[{cid}]"
    s = _strategy(ctx, cid)
    if s and _pos(s.get("target_roas")):
        return _pos(s.get("target_roas")), f"bidding_strategies.target_roas[{s.get('id')}]"
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    if isinstance(obj, dict) and _pos(obj.get("target_roas")):
        return _pos(obj.get("target_roas")), f"profile.campaign_objectives[{cid}].target_roas"
    if _pos(camp.get("target_cpa")) or (s and _pos(s.get("target_cpa"))) or (isinstance(obj, dict) and _pos(obj.get("target_cpa"))):
        return None, "campaign has a CPA objective"
    if _pos(ctx.profile.get("target_roas")):
        return _pos(ctx.profile.get("target_roas")), "profile.target_roas"
    return None, "no applicable target ROAS"


def _aggregate(ctx, rows: list[dict], columns: list[str]) -> tuple[dict, list[str]]:
    """Sum metric rows per (campaign, ad group, keyword); reject undeclared fan-out."""
    segs = [c for c in SEGMENT_COLS if c in columns]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (str(r.get("campaign_id") or ""), str(r.get("ad_group_id") or ""), str(r.get("keyword_id") or ""))
        groups.setdefault(key, []).append(r)
    out, notes = {}, []
    for key in sorted(groups):
        rs = groups[key]
        uniq = {tuple(sorted((k, str(v)) for k, v in r.items())) for r in rs}
        if len(rs) > 1 and len(uniq) < len(rs):
            notes.append(f"{key[2]}: {len(rs) - len(uniq)} identical duplicate row(s) dropped")
            rs = [dict(t) for t in sorted(uniq)]
        if len(rs) > 1 and not segs:
            notes.append(f"{key[2]}: {len(rs)} rows at one keyword without a segment column (fan-out); excluded")
            continue
        agg = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0}
        for r in rs:
            for m in agg:
                v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
                if v is None or agg[m] is None:
                    agg[m] = None
                else:
                    agg[m] += v
        agg["quality_score"] = V.num(rs[0].get("quality_score"))
        agg["rows"] = len(rs)
        out[key] = agg
    return out, notes


def run(ctx) -> None:
    """Run zero-conversion, CPA-vs-target and value screens on joined keyword metrics.

    Rules:   Every screen is partial with no Warning path unless ctx.mature True; tracking not True defers that
             campaign. CPA > 2x target CPA with keyword conversions >= min_conversions is the only deterministic
             Warning. Zero-conversion keywords at spend_floor are provisional Info + ai_review; ROAS below target is an
             Info review. Target ROAS never substitutes target CPA; Quality Score/CTR never create findings.
    """
    _scope(ctx)
    kw_inv = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in ctx.rows("keywords")}
    st = ctx.table("search_terms")
    queries_ok = st is not None and not st.missing(QUERY_COLS)
    queries: dict[tuple, list[dict]] = {}
    if queries_ok:
        for q in st.rows:
            key = (str(q.get("campaign_id")), str(q.get("ad_group_id")), str(q.get("matched_keyword_id")))
            queries.setdefault(key, []).append({"search_term": q.get("search_term"), "cost": ctx.money(q.get("cost")),
                                                "clicks": V.num(q.get("clicks")), "conversions": V.num(q.get("conversions"))})

    # step 2 — target resolution
    tgt = ctx.check("target_resolution", "Resolve applicable CPA/ROAS target and spend_floor per campaign",
                    {**KM, "campaigns": ["id"]})
    metrics: dict = {}
    targets: dict[str, dict] = {}
    if ctx.table("keyword_metrics") is not None and not ctx.table("keyword_metrics").missing(KM["keyword_metrics"]):
        metrics, fan = _aggregate(ctx, ctx.rows("keyword_metrics"), ctx.table("keyword_metrics").columns)
        for n in fan:
            tgt.partial(n)
    campaigns = sorted({k[0] for k in metrics})
    for cid in campaigns:
        cpa, cpa_src = ctx.params.target_cpa(cid)
        roas, roas_src = _target_roas(ctx, cid)
        floor = ctx.params.get("spend_floor", cid)
        mc = ctx.params.get("min_conversions")
        tracking, t_note = ctx.tracking_for_campaign(cid)
        s = _strategy(ctx, cid)
        camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), {}) or {}
        targets[cid] = {"cpa": cpa, "cpa_source": cpa_src, "roas": roas, "roas_source": roas_src,
                        "spend_floor": floor.value, "spend_floor_source": floor.source or floor.reason,
                        "min_conversions": mc.value, "tracking": tracking, "tracking_note": t_note,
                        "strategy_type": camp.get("bidding_strategy_type") or (s or {}).get("type"),
                        "portfolio_id": (s or {}).get("id")}
        if tgt.runnable:
            tgt.observe(f"Campaign {cid}: resolved target and spend_floor", campaign_id=cid, **targets[cid])
            if floor.value is None:
                tgt.partial(f"spend_floor unresolved for campaign {cid}: {floor.reason}")

    def base_ev(key, m, t):
        return {"keyword_text": (kw_inv.get(key) or {}).get("text"), "match_type": (kw_inv.get(key) or {}).get("match_type"),
                "status": (kw_inv.get(key) or {}).get("status"), "impressions": m["impressions"], "clicks": m["clicks"],
                "cost": m["cost"], "conversions": m["conversions"], "conversion_value": m["conversion_value"],
                "window": [ctx.period_start, ctx.period_end], "target_cpa": t["cpa"], "target_cpa_source": t["cpa_source"],
                "spend_floor": t["spend_floor"], "spend_floor_source": t["spend_floor_source"],
                "strategy_type": t["strategy_type"], "tracking": t["tracking_note"], "mature": ctx.mature,
                "queries": sorted(queries.get(key, []), key=lambda q: (-(q["cost"] or 0), str(q["search_term"])))[:10]
                if queries_ok else "search_terms unavailable"}

    outcomes_guidance = ("Judge relevance/funnel role from the query evidence and profile objectives only. For a Warning "
                         "outcome supply proposal {action: " + "|".join(ACTIONS) + "}; bid_reduction only under manual CPC. "
                         "Exposure is not savings; post-pause delivery is unknown.")
    screened: set = set()

    # step 3 — zero-conversion screen
    zero = ctx.check("zero_conversion_screen", "Mature zero-conversion keywords at spend_floor (tracking-gated)", KM)
    if zero.runnable:
        if ctx.mature is not True:
            zero.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        n = unknown = 0
        for key in sorted(metrics):
            m, t = metrics[key], targets[key[0]]
            if m["conversions"] is None or m["cost"] is None:
                unknown += 1
                continue
            if ctx.mature is not True or m["conversions"] != 0:
                continue
            if t["spend_floor"] is None or m["cost"] < t["spend_floor"]:
                continue
            if t["tracking"] is not True:
                _note(zero, f"campaign {key[0]}: tracking not evidenced ({t['tracking_note']}); no Warning path")
                zero.observe(f"Keyword {key[2]}: zero-conversion exposure at spend_floor (review deferred)",
                             campaign_id=key[0], keyword_id=key[2], cost=m["cost"], spend_floor=t["spend_floor"])
                continue
            n += 1
            screened.add(key)
            entity = {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]}
            ev = base_ev(key, m, t)
            prov = zero.finding("zero_conversion_keyword", "Info", entity,
                                f"Keyword {key[2]} spent {m['cost']:.2f} {ctx.currency} with 0 conversions in a mature "
                                f"window (spend_floor {t['spend_floor']:g}, {t['spend_floor_source']})",
                                evidence=ev, calculation={"numerator_cost": m["cost"], "conversions": 0,
                                                          "threshold": t["spend_floor"]},
                                recommendation="Review query relevance and funnel role before any pause trial.",
                                uncertainty="Zero conversions can reflect lag, low volume, assisted value or tracking scope.")
            zero.review("zero_conversion_keyword", entity,
                        f"After reviewing queries, tracking and funnel role, is keyword {key[2]} "
                        f"('{ev['keyword_text']}') a low performer that warrants owner review?",
                        evidence=ev, provisional=prov, guidance=outcomes_guidance,
                        outcomes={"low_performer_after_context": {"severity": "Warning", "recommendation":
                                                                  "Owner-reviewed action per proposal; monitor adjacent keywords."},
                                  "role_or_relevance_justified": {"severity": None, "recommendation": "Keep; document the role."},
                                  "uncertain": {"severity": "Info", "recommendation": "Collect query/role evidence first."}})
        if unknown:
            _note(zero, f"{unknown} keyword(s) with unknown cost/conversions not screened")
        zero.observe("Zero-conversion keywords at or above spend_floor", count=n, unknown_rows=unknown)

    # step 4 — CPA > 2x target
    cpa = ctx.check("cpa_screen", "Mature keyword CPA > 2x applicable target CPA", KM)
    if cpa.runnable:
        if ctx.mature is not True:
            cpa.partial(f"CPA screen disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        below_gate = flagged = 0
        for key in sorted(metrics):
            m, t = metrics[key], targets[key[0]]
            if ctx.mature is not True or t["cpa"] is None or not m["conversions"] or m["cost"] is None:
                continue
            if t["min_conversions"] is None or m["conversions"] < t["min_conversions"]:
                below_gate += 1
                continue
            kcpa = V.ratio(m["cost"], m["conversions"])
            ratio = V.ratio(kcpa, t["cpa"])
            if t["tracking"] is not True:
                _note(cpa, f"campaign {key[0]}: tracking not evidenced ({t['tracking_note']}); CPA screen deferred")
                cpa.observe(f"Keyword {key[2]} CPA (descriptive; screen deferred)", campaign_id=key[0], keyword_id=key[2],
                            cpa=kcpa, target_cpa=t["cpa"], target_source=t["cpa_source"], ratio_to_target=ratio)
                continue
            if kcpa is not None and kcpa > 2 * t["cpa"]:
                flagged += 1
                screened.add(key)
                entity = {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]}
                cpa.finding("cpa_over_2x_target", "Warning", entity,
                            f"Keyword {key[2]} CPA {kcpa:.2f} {ctx.currency} > 2x target {t['cpa']:g} ({t['cpa_source']})",
                            evidence=base_ev(key, m, t),
                            calculation={"cpa": kcpa, "numerator_cost": m["cost"], "denominator_conversions": m["conversions"],
                                         "threshold": 2 * t["cpa"], "ratio_to_target": ratio,
                                         "min_conversions": t["min_conversions"]},
                            recommendation="Review queries, messaging and funnel role; consider an owner-reviewed "
                                           "pause trial or (manual CPC only) a bid change. Route negatives to 014.",
                            uncertainty="Historical CPA; counterfactual delivery after a change is unknown. Not savings.")
            elif kcpa is not None:
                cpa.observe(f"Keyword {key[2]} CPA within 2x target", campaign_id=key[0], keyword_id=key[2], cpa=kcpa,
                            target_cpa=t["cpa"], target_source=t["cpa_source"], ratio_to_target=ratio)
        cpa.observe("CPA screen totals", flagged=flagged, below_min_conversions=below_gate)

    # step 5 — value objectives
    val = ctx.check("value_screen", "Mature keyword ROAS against applicable value target",
                    {"keyword_metrics": KM["keyword_metrics"] + ["conversion_value"]})
    if val.runnable:
        if ctx.mature is not True:
            val.partial(f"value screen disabled: maturity={ctx.mature}")
        for key in sorted(metrics):
            m, t = metrics[key], targets[key[0]]
            if ctx.mature is not True or t["roas"] is None or t["cpa"] is not None:
                continue
            if t["min_conversions"] is None or not m["conversions"] or m["conversions"] < t["min_conversions"]:
                continue
            roas = V.ratio(m["conversion_value"], m["cost"])
            if roas is None:
                continue
            if roas < t["roas"] and t["tracking"] is True:
                entity = {"campaign_id": key[0], "ad_group_id": key[1], "keyword_id": key[2]}
                ev = {**base_ev(key, m, t), "roas": roas, "target_roas": t["roas"], "target_roas_source": t["roas_source"]}
                val.review("roas_below_value_target", entity,
                           f"Keyword {key[2]} ROAS {roas:.2f} is below target {t['roas']:g}. Does value quality or "
                           f"funnel role explain it?", evidence=ev, guidance=outcomes_guidance,
                           outcomes={"review_value_quality": {"severity": "Info", "recommendation":
                                                              "Review value definition and query mix; no pause from ROAS alone."},
                                     "explained": {"severity": None, "recommendation": "Keep; document the role."}})
            val.observe(f"Keyword {key[2]} ROAS vs target", campaign_id=key[0], keyword_id=key[2], roas=roas,
                        target_roas=t["roas"], target_source=t["roas_source"])

    # step 6 — no target
    nt = ctx.check("no_target", "Campaigns without applicable target: relative flags omitted", KM)
    if nt.runnable:
        for cid in campaigns:
            t = targets[cid]
            if t["cpa"] is None and t["roas"] is None:
                exp = sum(m["cost"] or 0 for k, m in metrics.items() if k[0] == cid)
                nt.observe(f"Campaign {cid}: no applicable target; relative-performance flags omitted",
                           campaign_id=cid, cpa_reason=t["cpa_source"], roas_reason=t["roas_source"],
                           keywords=sum(1 for k in metrics if k[0] == cid), cost_exposure=exp)

    # step 7 — relevance/diagnostic context
    rel = ctx.check("relevance_context", "Query evidence per screened keyword; QS/CTR as context only",
                    {**KM, "search_terms": QUERY_COLS})
    if rel.runnable:
        if st.truncated or st.complete is not True:
            rel.partial("search_terms is privacy-limited/incomplete: unreported queries are unobserved, not zero")
        for key in sorted(screened):
            qcost = sum(q["cost"] or 0 for q in queries.get(key, []))
            rel.observe(f"Keyword {key[2]}: reported queries explain part of its cost", keyword_id=key[2],
                        query_cost=qcost, keyword_cost=metrics[key]["cost"], share=V.ratio(qcost, metrics[key]["cost"]),
                        distinct_queries=len(queries.get(key, [])))

    # index #103 — keyword performance report as descriptive context
    perf = ctx.check("keyword_performance_summary", "Keyword performance by Quality Score bucket (context only)",
                     {"keyword_metrics": KM["keyword_metrics"] + ["quality_score"]})
    if perf.runnable:
        buckets: dict[str, list[float]] = {}
        for key, m in metrics.items():
            qs = m["quality_score"]
            b = "unknown" if qs is None else "1-3" if qs <= 3 else "4-6" if qs <= 6 else "7-10"
            acc = buckets.setdefault(b, [0, 0.0, 0.0, 0.0, 0.0])
            acc[0] += 1
            for i, f in enumerate(("impressions", "clicks", "cost", "conversions"), 1):
                acc[i] += m[f] or 0
        for b in sorted(buckets):
            n, imp, clk, cost, conv = buckets[b]
            perf.observe(f"Quality Score bucket {b}: diagnostic context, not a pause signal", bucket=b, keywords=n,
                         impressions=imp, clicks=clk, cost=cost, conversions=conv, ctr=V.ratio(clk, imp),
                         cpc=V.ratio(cost, clk), cpa=V.ratio(cost, conv))

    # step 8 — action fit
    act = ctx.check("action_fit", "Allowed owner actions per bidding control", {"campaigns": ["id", "bidding_strategy_type"]})
    if act.runnable:
        for cid in sorted({k[0] for k in screened}):
            st_type = str(targets[cid]["strategy_type"] or "").upper()
            act.observe(f"Campaign {cid}: allowed actions under {st_type or 'unknown strategy'}", campaign_id=cid,
                        strategy_type=st_type, bid_changes_supported=st_type in MANUAL,
                        allowed=[a for a in ACTIONS if a != "bid_reduction" or st_type in MANUAL])

    # step 9 — exposure separation
    exp = ctx.check("exposure_separation", "Distinct screened exposure (not savings)", KM)
    if exp.runnable:
        total = sum(metrics[k]["cost"] or 0 for k in screened)
        exp.observe("Screened keyword exposure over distinct keyword IDs; exposure is not recoverable savings",
                    keywords=len(screened), cost_exposure=total, window=[ctx.period_start, ctx.period_end])


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning outcomes need a supported proposal.action; bid_reduction only under manual CPC."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") != "Warning":
        return []
    action = str((decision.get("proposal") or {}).get("action") or "")
    if action not in ACTIONS:
        return [f"proposal.action must be one of {list(ACTIONS)}"]
    if action == "bid_reduction":
        camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == str(item.entity.get("campaign_id"))), {}) or {}
        if str(camp.get("bidding_strategy_type") or "").upper() not in MANUAL:
            return [f"bid_reduction unsupported under {camp.get('bidding_strategy_type') or 'unknown'} bidding"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
