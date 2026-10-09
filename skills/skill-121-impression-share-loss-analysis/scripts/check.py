"""check.py — skill-121 deterministic impression-share loss screening with goal-aligned economics.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-121-impression-share-loss-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #25 Bid to Impression Share (Google developers) — clean-room reimplementation of the observed-vs-client-target
         impression-share gap only; no bid logic, bid changes stay request-only
         index #55 Monitor Impression Share metrics for all accounts in MCC — clean-room reimplementation of the per-account
         eligible-impression-weighted IS monitor; cli partitions MCC exports per account, no cross-account totals
rules:   Search campaigns only (campaigns.channel_type SEARCH); shares parsed with ctx.rate. Censored/withheld cells
         ('< 10%', '--') and values outside 0..1 stay unknown, never 0.
         Screens are strict: budget-lost IS > 0.20, rank-lost IS > 0.30; both may fire on one campaign.
         Every screen needs impressions >= min_impressions. Rank-lost Warning needs only that sample.
         Budget-lost Warning ONLY when ctx.mature is True, conversions >= min_conversions and CPA <= resolved target CPA
         (ctx.params.target_cpa) or ROAS >= target ROAS; otherwise Info naming the failed gate (no target, low sample,
         immature, economics above target).
         Multi-row campaigns combine shares by eligible-impression weights (impressions / IS); rows are never averaged.
         Daily saturation only from custom/is_daily historical_budget_amount; a shared budget's spend is summed once per
         budget/day. Current daily budget x days is never used.
         Eligible impressions (impressions / IS) and external/is_scenarios arithmetic are diagnostics. They are never
         recoverable impressions, savings or guaranteed gains.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
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

SKILL = "skill-121-impression-share-loss-analysis"
VERSION = "1.0.0"

BUDGET_SCREEN = 0.20
RANK_SCREEN = 0.30
SHARE_COLS = ("search_impression_share", "search_budget_lost_is", "search_rank_lost_is")
IS_TARGET_METRICS = ("search_impression_share", "impression_share", "search_is")


def _share(ctx, raw) -> tuple[float | None, str]:
    """Return (fraction, state). state: ok | missing | censored | out_of_range."""
    if raw is None:
        return None, "missing"
    v = ctx.rate(raw)
    if v is None:
        return None, "censored"
    if not 0 <= v <= 1:
        return None, "out_of_range"
    return v, "ok"


def _search_ids(ctx) -> dict[str, dict]:
    return {str(r.get("id")): r for r in ctx.rows("campaigns")
            if str(r.get("channel_type") or "").upper() == "SEARCH" and r.get("id") is not None}


def _combine(ctx, rows: list[dict]) -> dict:
    """Campaign totals; shares combined by eligible-impression weights (impressions / IS)."""
    out = {"rows": len(rows), "states": {}}
    for k in ("impressions", "clicks", "cost", "conversions", "conversion_value"):
        vals = [ctx.money(r.get(k)) if k in ("cost", "conversion_value") else V.num(r.get(k)) for r in rows]
        out[k] = None if any(v is None for v in vals) else sum(vals)
    parsed = [{c: _share(ctx, r.get(c)) for c in SHARE_COLS} | {"impr": V.num(r.get("impressions"))} for r in rows]
    for c in SHARE_COLS:
        states = sorted({p[c][1] for p in parsed})
        out["states"][c] = states[0] if len(states) == 1 else "+".join(states)
    if len(rows) == 1:
        p = parsed[0]
        for c in SHARE_COLS:
            out[c] = p[c][0]
        return out
    eligible = []
    for p in parsed:
        share, impr = p["search_impression_share"][0], p["impr"]
        eligible.append(V.ratio(impr, share) if impr is not None and share else None)
    if any(e is None for e in eligible):
        for c in SHARE_COLS:
            out[c] = None
            out["states"][c] = "unweightable"
        return out
    total = sum(eligible)
    out["search_impression_share"] = V.ratio(sum(p["impr"] for p in parsed), total)
    for c in ("search_budget_lost_is", "search_rank_lost_is"):
        vals = [p[c][0] for p in parsed]
        out[c] = None if any(v is None for v in vals) else V.ratio(sum(e * v for e, v in zip(eligible, vals)), total)
    return out


def _target_roas(ctx, cid: str) -> tuple[float | None, str]:
    def pos(v):
        f = V.num(v)
        return f if f is not None and f > 0 else None

    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None) or {}
    t = pos(row.get("target_roas"))
    if t:
        return t, f"campaigns.target_roas[{cid}]"
    sid = row.get("bidding_strategy_id") or row.get("strategy_id")
    if sid:
        srow = next((r for r in ctx.rows("bidding_strategies") if str(r.get("id")) == str(sid)), None)
        t = pos(srow.get("target_roas")) if srow else None
        if t:
            return t, f"bidding_strategies.target_roas[{sid}]"
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    t = pos(obj.get("target_roas")) if isinstance(obj, dict) else None
    if t:
        return t, f"profile.campaign_objectives[{cid}].target_roas"
    return None, "no applicable target ROAS"


def _economics(ctx, cid: str, m: dict, min_conv: int | None) -> dict:
    """Goal-aligned economics verdict for the budget-lost Warning gate."""
    cpa_t, cpa_src = ctx.params.target_cpa(cid)
    roas_t, roas_src = (None, "not needed") if cpa_t is not None else _target_roas(ctx, cid)
    e = {"target_cpa": cpa_t, "target_cpa_source": cpa_src, "target_roas": roas_t, "target_roas_source": roas_src,
         "conversions": m.get("conversions"), "cost": m.get("cost"), "conversion_value": m.get("conversion_value"),
         "min_conversions": min_conv, "mature": ctx.mature, "maturity_note": ctx.maturity_note,
         "cpa": V.ratio(m.get("cost"), m.get("conversions")), "roas": V.ratio(m.get("conversion_value"), m.get("cost"))}
    if cpa_t is None and roas_t is None:
        e["aligned"], e["gate"] = None, f"no target: economic suitability unknown ({cpa_src}; {roas_src})"
    elif ctx.mature is not True:
        e["aligned"], e["gate"] = None, f"conversion maturity not established ({ctx.maturity_note})"
    elif min_conv is None or m.get("conversions") is None or m["conversions"] < min_conv:
        e["aligned"], e["gate"] = None, f"low sample: conversions {m.get('conversions')} < min_conversions {min_conv}"
    elif cpa_t is not None:
        e["aligned"] = e["cpa"] is not None and e["cpa"] <= cpa_t
        e["gate"] = f"CPA {e['cpa']:.2f} {'<=' if e['aligned'] else '>'} target CPA {cpa_t:g}" if e["cpa"] is not None \
            else "CPA undefined"
    else:
        e["aligned"] = e["roas"] is not None and e["roas"] >= roas_t
        e["gate"] = f"ROAS {e['roas']:.2f} {'>=' if e['aligned'] else '<'} target ROAS {roas_t:g}" if e["roas"] is not None \
            else "ROAS undefined (conversion_value or cost unknown)"
    return e


def _daily_saturation(ctx, chk) -> dict[str, dict]:
    """Per campaign: complete days whose budget (deduplicated per budget/day) spent >= its historical amount."""
    end, snap = ctx.as_of, ctx.snapshot
    seen, dupes, rows = set(), 0, []
    for r in sorted(ctx.rows("custom/is_daily"), key=lambda r: (str(r.get("campaign_id")), str(r.get("date")))):
        d = V.parse_date(r.get("date"))
        if d is None or (end and d > end) or (snap and d >= snap):
            continue
        key = (str(r.get("campaign_id")), d)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        rows.append((key[0], d, str(r.get("budget_id") or ""), ctx.money(r.get("cost")),
                     ctx.money(r.get("historical_budget_amount"))))
    if dupes:
        chk.partial(f"{dupes} duplicate campaign/date rows in custom/is_daily ignored")
    groups: dict[tuple, dict] = {}
    for cid, d, bid, cost, amount in rows:
        g = groups.setdefault((bid or f"campaign:{cid}", d), {"cost": 0.0, "amounts": set(), "unknown": False, "cids": []})
        g["cids"].append(cid)
        if cost is None:
            g["unknown"] = True
        else:
            g["cost"] += cost
        g["amounts"].add(amount)
    per: dict[str, dict] = {}
    conflicts = 0
    for (bid, d), g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        amounts = g["amounts"]
        amount = next(iter(amounts)) if len(amounts) == 1 else None
        if len(amounts) > 1:
            conflicts += 1
        state = None if g["unknown"] or amount is None or amount <= 0 else g["cost"] >= amount
        for cid in g["cids"]:
            p = per.setdefault(cid, {"complete_days": 0, "saturated_days": 0, "unknown_days": 0, "budget_ids": set(),
                                     "first_date": d, "last_date": d})
            p["complete_days"] += 1
            p["budget_ids"].add(bid)
            p["first_date"], p["last_date"] = min(p["first_date"], d), max(p["last_date"], d)
            if state is None:
                p["unknown_days"] += 1
            elif state:
                p["saturated_days"] += 1
    if conflicts:
        chk.partial(f"{conflicts} budget/day groups with conflicting historical_budget_amount left unknown")
    for cid, p in sorted(per.items()):
        p["saturated_share"] = V.ratio(p["saturated_days"], p["complete_days"] - p["unknown_days"])
        if p["complete_days"] < 56:
            chk.partial(f"campaign {cid}: {p['complete_days']} complete days < 8 complete weeks")
        chk.observe(f"Campaign {cid}: daily budget saturation from historical budgets", campaign_id=cid,
                    rule="budget-level cost (shared budgets summed once per day) >= historical_budget_amount", **p)
    return per


def run(ctx) -> None:
    """Run Search impression-share budget-lost / rank-lost screens and daily saturation checks.

    Rules:   Censored or out-of-range IS stays unknown → Info is_censored_or_unavailable, never 0. Every screen needs
             impressions >= min_impressions; rank-lost IS > 0.30 is Warning with that sample only. Budget-lost IS > 0.20
             is Warning only with ctx.mature True, min_conversions and CPA/ROAS at target; else Info naming the failed
             gate. Eligible impressions and scenarios are diagnostics, never recoverable gains.
    """
    min_impr = ctx.params.get("min_impressions")
    min_conv = ctx.params.get("min_conversions")
    search = _search_ids(ctx)

    # -- step 1: units, censoring, sample; account IS monitor (index #55)
    units = ctx.check("share_units", "Normalize impression-share units and censoring",
                      {"campaigns": ["id", "channel_type"],
                       "campaign_metrics": ["campaign_id", "impressions", *SHARE_COLS]})
    later = (("loss_screen", "Budget/rank-lost IS triage screen"),
             ("economics", "CPA/ROAS against target with mature sample"))
    if not units.runnable:
        for cid_, title in later:
            ctx.check(cid_, title).skip("impression-share inputs unavailable", units.missing)
        metrics = {}
    else:
        by_c: dict[str, list[dict]] = {}
        for r in ctx.rows("campaign_metrics"):
            by_c.setdefault(str(r.get("campaign_id")), []).append(r)
        metrics = {cid: _combine(ctx, rows) for cid, rows in sorted(by_c.items()) if cid in search}
        others = sorted(c for c in by_c if c not in search)
        if others:
            units.observe("Non-Search campaigns excluded from IS screening", campaign_ids=others)
        if not ctx.rates_format:
            units.partial("account.rates_format unknown: shares read as fractions; values outside 0..1 left unknown")
        acc_impr = acc_elig = 0.0
        acc_budget = acc_rank = 0.0
        weighted = []
        for cid, m in metrics.items():
            if m["rows"] > 1:
                units.partial(f"campaign {cid}: {m['rows']} metric rows combined by eligible-impression weights")
            bad = {c: s for c, s in m["states"].items() if s != "ok"}
            units.observe(f"Campaign {cid}: impression-share inputs", campaign_id=cid, impressions=m["impressions"],
                          min_impressions=min_impr.value, sample_ok=(m["impressions"] or 0) >= (min_impr.value or 0),
                          search_impression_share=m["search_impression_share"],
                          budget_lost_is=m["search_budget_lost_is"], rank_lost_is=m["search_rank_lost_is"],
                          share_states=m["states"], unknown_shares=sorted(bad))
            share = m["search_impression_share"]
            if m["impressions"] and share and m["search_budget_lost_is"] is not None and m["search_rank_lost_is"] is not None:
                elig = m["impressions"] / share
                acc_impr += m["impressions"]
                acc_elig += elig
                acc_budget += elig * m["search_budget_lost_is"]
                acc_rank += elig * m["search_rank_lost_is"]
                weighted.append(cid)
        units.observe("Account Search IS monitor (eligible-impression weighted)", campaigns=weighted,
                      impressions=acc_impr, eligible_impressions_estimate=acc_elig,
                      search_impression_share=V.ratio(acc_impr, acc_elig),
                      budget_lost_is=V.ratio(acc_budget, acc_elig), rank_lost_is=V.ratio(acc_rank, acc_elig),
                      window=[ctx.period_start, ctx.period_end])

    # -- step 4 (computed first so screens can cite it): daily saturation from historical budgets
    sat = ctx.check("daily_saturation", "Daily budget saturation from historical budgets",
                    {"custom/is_daily": ["campaign_id", "date", "budget_id", "cost", "historical_budget_amount"]})
    saturation = _daily_saturation(ctx, sat) if sat.runnable else {}

    if units.runnable:
        # -- step 3: economics
        econ = ctx.check("economics", "CPA/ROAS against target with mature sample",
                         {"campaign_metrics": ["campaign_id", "cost", "conversions"]})
        verdicts: dict[str, dict] = {}
        if econ.runnable:
            if min_conv.value is None:
                econ.partial(f"min_conversions unresolved: {min_conv.reason}")
            if ctx.mature is not True:
                econ.partial(f"maturity: {ctx.maturity_note}")
            for cid, m in metrics.items():
                e = _economics(ctx, cid, m, min_conv.value)
                verdicts[cid] = e
                econ.observe(f"Campaign {cid}: economics gate — {e['gate']}", campaign_id=cid, **e)
            if any(e["aligned"] is None and e["target_cpa"] is None and e["target_roas"] is None
                   for e in verdicts.values()):
                econ.partial("some Search campaigns have no applicable target; economic suitability unknown")

        # -- step 2: screens
        screen = ctx.check("loss_screen", "Budget/rank-lost IS triage screen", applicable=bool(metrics),
                           na_reason="no Search campaign with campaign_metrics rows")
        if min_impr.value is None:
            screen.partial(f"min_impressions unresolved: {min_impr.reason}")
        for cid, m in metrics.items():
            impr = m["impressions"]
            sample_ok = impr is not None and min_impr.value is not None and impr >= min_impr.value
            bl, rl = m["search_budget_lost_is"], m["search_rank_lost_is"]
            name = search[cid].get("name")
            entity = {"campaign_id": cid}
            base_ev = {"campaign_name": name, "impressions": impr, "min_impressions": min_impr.value,
                       "min_impressions_source": min_impr.source, "search_impression_share": m["search_impression_share"],
                       "budget_lost_is": bl, "rank_lost_is": rl, "share_states": m["states"],
                       "window": [ctx.period_start, ctx.period_end], "metric_rows": m["rows"],
                       "source": "campaign_metrics"}
            unknown = [c for c in ("search_budget_lost_is", "search_rank_lost_is") if m[c] is None]
            if unknown and sample_ok:
                screen.finding("is_censored_or_unavailable", "Info", entity,
                               f"Campaign {cid}: {', '.join(unknown)} censored/unavailable; loss screen undecidable",
                               evidence=base_ev,
                               recommendation="Request uncensored campaign-level shares for the same window before any budget/rank review.",
                               uncertainty="Censored or withheld shares are unknown, not zero.")
            if bl is not None and bl > BUDGET_SCREEN:
                e = verdicts.get(cid) or {"aligned": None, "gate": "economics check unavailable"}
                s = saturation.get(cid)
                ev = {**base_ev, "screen": f"budget_lost_is > {BUDGET_SCREEN}", "economics": e,
                      "daily_saturation": s or "unconfirmed: custom/is_daily with historical_budget_amount not supplied"}
                calc = {"budget_lost_is": bl, "threshold": BUDGET_SCREEN, "economics_gate": e.get("gate"),
                        "eligible_impressions_estimate": V.ratio(impr, m["search_impression_share"])}
                warn = sample_ok and e.get("aligned") is True
                gate = e.get("gate") if sample_ok else f"low sample: impressions {impr} < min_impressions {min_impr.value}"
                screen.finding("budget_lost_is_constraint", "Warning" if warn else "Info", entity,
                               f"Campaign {cid} lost {bl:.0%} of eligible Search impressions to budget "
                               f"({'goal-aligned economics' if warn else gate})",
                               evidence=ev, calculation=calc,
                               recommendation=("Investigate the budget constraint with the budget owner; any increase is a "
                                               "request-only proposal within the approved cap, with monitoring and rollback."
                                               if warn else "Report as a reported constraint only; resolve the named gate "
                                               "before proposing budget changes."),
                               uncertainty=("Reported budget-lost IS is not certain lost profitable sales; marginal CPA of "
                                            "extra traffic is unknown" + ("" if s else "; daily saturation unconfirmed")))
            if rl is not None and rl > RANK_SCREEN:
                screen.finding("rank_lost_is_constraint", "Warning" if sample_ok else "Info", entity,
                               f"Campaign {cid} lost {rl:.0%} of eligible Search impressions to rank"
                               + ("" if sample_ok else f" (low sample: impressions {impr} < {min_impr.value})"),
                               evidence={**base_ev, "screen": f"rank_lost_is > {RANK_SCREEN}"},
                               calculation={"rank_lost_is": rl, "threshold": RANK_SCREEN},
                               recommendation="Assign a rank investigation (bids/targets, ad relevance, landing page, "
                                              "competition); do not treat Quality Score as the proven cause.",
                               uncertainty="Rank loss has multiple causes; no recoverable-impression or revenue estimate.")
            if not (bl is not None and bl > BUDGET_SCREEN) and not (rl is not None and rl > RANK_SCREEN) and not unknown:
                screen.observe(f"Campaign {cid}: below both loss screens", campaign_id=cid, budget_lost_is=bl,
                               rank_lost_is=rl, impressions=impr)

    # -- step 5: rank diagnostics joined by IDs
    diag = ctx.check("rank_diagnostics", "Keyword diagnostics for rank-limited campaigns",
                     {"keywords": ["id", "campaign_id", "ad_group_id"],
                      "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions"]})
    if diag.runnable and not units.runnable:
        diag.skip("impression-share inputs unavailable: rank-limited campaigns unknown", units.missing)
    if diag.runnable:
        limited = sorted(c for c, m in metrics.items() if (m["search_rank_lost_is"] or 0) > RANK_SCREEN)
        kws = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in ctx.rows("keywords")}
        comps = [c for c in ("expected_ctr", "ad_relevance", "landing_page_experience")
                 if c in (ctx.table("keywords").columns if ctx.table("keywords") else [])]
        for cid in limited:
            joined = unmatched = 0
            impr_total = impr_qs = 0.0
            qs_weighted = 0.0
            below = {c: 0.0 for c in comps}
            for r in ctx.rows("keyword_metrics"):
                if str(r.get("campaign_id")) != cid:
                    continue
                k = kws.get((cid, str(r.get("ad_group_id")), str(r.get("keyword_id"))))
                if k is None:
                    unmatched += 1
                    continue
                joined += 1
                impr = V.num(r.get("impressions")) or 0.0
                impr_total += impr
                qs = V.num(k.get("quality_score"))
                if qs is not None:
                    impr_qs += impr
                    qs_weighted += qs * impr
                for c in comps:
                    if str(k.get(c) or "").upper() == "BELOW_AVERAGE":
                        below[c] += impr
            diag.observe(f"Campaign {cid}: keyword diagnostics (descriptive, not root cause)", campaign_id=cid,
                         joined_keywords=joined, unmatched_metric_rows=unmatched, impressions=impr_total,
                         impression_weighted_quality_score=V.ratio(qs_weighted, impr_qs),
                         below_average_impression_share={c: V.ratio(v, impr_total) for c, v in below.items()},
                         note="Quality Score is a diagnostic, not an auction input; it does not prove the rank-loss cause.")
            if unmatched:
                diag.partial(f"campaign {cid}: {unmatched} keyword_metrics rows without an ID match in keywords")
        if not limited:
            diag.observe("No rank-limited Search campaign above the 30% screen", campaigns=len(metrics))

    # -- step 6: eligible-impression diagnostic and assumption-led scenarios
    est = ctx.check("eligible_estimate", "Eligible-impression rough diagnostic",
                    applicable=bool(metrics) or not units.runnable, na_reason="no Search campaign with campaign_metrics rows")
    if not units.runnable:
        est.skip("impression-share inputs unavailable", units.missing)
    for cid, m in metrics.items():
        share, impr = m["search_impression_share"], m["impressions"]
        elig = V.ratio(impr, share) if impr is not None and share else None
        est.observe(f"Campaign {cid}: eligible impressions = impressions / IS (rough, not recoverable)",
                    campaign_id=cid, impressions=impr, search_impression_share=share, eligible_impressions_estimate=elig,
                    unserved_estimate=None if elig is None else elig - impr,
                    state="undefined: IS censored, unknown or zero" if elig is None else "estimated")

    scen = ctx.check("scenarios", "Assumption-led recovery scenarios",
                     {"external/is_scenarios": ["scenario_id", "campaign_id", "allowable_spend", "marginal_cpc",
                                                "marginal_cvr", "marginal_value", "assumptions", "approval_owner"]})
    if scen.runnable:
        for r in sorted(ctx.rows("external/is_scenarios"), key=lambda r: (str(r.get("campaign_id")), str(r.get("scenario_id")))):
            spend, cpc = ctx.money(r.get("allowable_spend")), ctx.money(r.get("marginal_cpc"))
            cvr, val = ctx.rate(r.get("marginal_cvr")), ctx.money(r.get("marginal_value"))
            clicks = V.ratio(spend, cpc)
            conv = None if clicks is None or cvr is None else clicks * cvr
            missing = [k for k, v in (("allowable_spend", spend), ("marginal_cpc", cpc), ("marginal_cvr", cvr),
                                      ("marginal_value", val), ("assumptions", r.get("assumptions")),
                                      ("approval_owner", r.get("approval_owner"))) if v is None]
            if missing:
                scen.partial(f"scenario {r.get('scenario_id')}: missing {', '.join(missing)}")
            scen.observe(f"Scenario {r.get('scenario_id')} (campaign {r.get('campaign_id')}): assumption-led, not a forecast",
                         scenario_id=r.get("scenario_id"), campaign_id=r.get("campaign_id"), allowable_spend=spend,
                         marginal_cpc=cpc, marginal_cvr=cvr, marginal_value=val, scenario_clicks=clicks,
                         scenario_conversions=conv, scenario_value=None if conv is None or val is None else conv * val,
                         assumptions=r.get("assumptions"), approval_owner=r.get("approval_owner"),
                         formula="clicks = allowable_spend / marginal_cpc; conversions = clicks x marginal_cvr; "
                                 "value = conversions x marginal_value")

    # -- index #25: observed IS versus client-approved IS target (no bid logic)
    gap = ctx.check("is_target_gap", "Observed IS versus client-approved IS target",
                    {"external/is_scenarios": ["scenario_id", "campaign_id", "target_metric", "target_value"]})
    if gap.runnable:
        rows = [r for r in ctx.rows("external/is_scenarios")
                if V.norm_text(r.get("target_metric")).replace(" ", "_") in IS_TARGET_METRICS]
        if not rows:
            gap.not_applicable("no scenario declares an impression-share target_metric")
        for r in sorted(rows, key=lambda r: (str(r.get("campaign_id")), str(r.get("scenario_id")))):
            cid = str(r.get("campaign_id"))
            target, _ = _share(ctx, r.get("target_value"))
            observed = (metrics.get(cid) or {}).get("search_impression_share")
            gap.observe(f"Campaign {cid}: observed IS versus approved target (request-only; no bid changes)",
                        campaign_id=cid, scenario_id=r.get("scenario_id"), target_is=target, observed_is=observed,
                        gap_points=None if target is None or observed is None else target - observed,
                        approval_owner=r.get("approval_owner"))
            if target is None or observed is None:
                gap.partial(f"campaign {cid}: target or observed IS unknown")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
