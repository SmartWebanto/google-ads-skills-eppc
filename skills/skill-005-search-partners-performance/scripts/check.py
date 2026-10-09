"""check.py — skill-005 deterministic Search Partners vs Google Search comparison per campaign.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-005-search-partners-performance/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #58 Search Partner Performance Alerts (nilsrooijmans.com) — clean-room reimplementation of the
         per-campaign partner-vs-Google CPA/CPC comparison; the recipe's 2x CPA screen, min_clicks/min_conversions
         on BOTH sides, maturity and objective benchmark replace the script's 50-click/20% alert. No email/sheet.
rules:   Network metrics come only from custom/network_daily (campaign_id/date/ad_network_type grain) restricted to
         the export window; duplicate grain rows exclude that campaign (never summed). Networks are SEARCH,
         SEARCH_PARTNERS, CONTENT (optional profile.network_map {raw: canonical}); other values stay separate.
         Conversion metrics use only lag-mature days (snapshot - date >= lag); unknown lag → no economic verdict.
         Rates are ratios of sums (V.ratio); zero/unknown denominators are undefined.
         Warning (CPA) is deterministic only if: ctx.mature True, both sides clicks >= min_clicks and conversions
         >= min_conversions, single identical goal_scope, partner CPA > 2x Google CPA AND > applicable target CPA
         (ctx.params target precedence). Value-led objectives (target_roas) go to ai_review, never CPA.
         Zero partner conversions: cost >= spend_floor(campaign), ctx.mature True and ctx.tracking_for_campaign True,
         then relevance ai_review (Warning outcome) with provisional Info; otherwise partial. Exposure ≠ savings.
         No ref-bearing evidence is declared: review items carry evidence_refs naming the reviewed campaign/network
         slices of custom/network_daily for the window; Warning outcomes must cite one of them as proposal.evidence_ref.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | Warning evidence_ref restricted to item evidence_refs
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

SKILL = "skill-005-search-partners-performance"
VERSION = "1.0.0"

ND = "custom/network_daily"
NET = ["campaign_id", "date", "ad_network_type", "impressions", "clicks", "cost", "conversions"]
ECON = ["conversion_value", "goal_scope", "conversion_date_basis"]
CANON = ("SEARCH", "SEARCH_PARTNERS", "CONTENT")
CPA_RATIO = 2.0
RECONCILE_TOL = 0.01
G, P = "SEARCH", "SEARCH_PARTNERS"


def _objective(ctx, cid) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objs.items() if str(k) == str(cid)), None) if isinstance(objs, dict) else None
    return obj if isinstance(obj, dict) else {}


def _canon(ctx, raw) -> str:
    m = ctx.profile.get("network_map") or {}
    s = str(raw or "").strip()
    s = str(m.get(s, s)).strip().upper().replace(" ", "_")
    return s if s in CANON else f"OTHER:{s or 'UNKNOWN'}"


def load_network(ctx, chk) -> dict[str, dict[str, dict]]:
    """campaign → network → sums. Rules: window-bounded, duplicate grain excludes the campaign, mature subtotals."""
    start, end, snap, lag = ctx.period_start, ctx.period_end, ctx.snapshot, ctx.lag_days
    seen, dup, outside, bad_date = set(), set(), 0, 0
    data: dict[str, dict[str, dict]] = {}
    for r in sorted(ctx.rows(ND), key=lambda r: (str(r.get("campaign_id")), str(r.get("date")), str(r.get("ad_network_type")))):
        cid, d, net = str(r.get("campaign_id")), V.parse_date(r.get("date")), _canon(ctx, r.get("ad_network_type"))
        if d is None:
            bad_date += 1
            continue
        if start and end and not (start <= d <= end):
            outside += 1
            continue
        key = (str(r.get("account_id") or ""), cid, d, net)
        if key in seen:
            dup.add(cid)
            continue
        seen.add(key)
        a = data.setdefault(cid, {}).setdefault(net, {
            "impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0,
            "m_clicks": 0.0, "m_cost": 0.0, "m_conversions": 0.0, "m_value": 0.0, "days": set(), "mature_days": set(),
            "unknown_cells": 0, "goal_scopes": set(), "bases": set(), "value_known": True})
        a["days"].add(d)
        mature = None if (lag is None or snap is None) else (snap - d).days >= lag
        vals = {"impressions": V.num(r.get("impressions")), "clicks": V.num(r.get("clicks")),
                "cost": ctx.money(r.get("cost")), "conversions": V.num(r.get("conversions")),
                "conversion_value": ctx.money(r.get("conversion_value"))}
        for f, v in vals.items():
            if v is None:
                if f == "conversion_value":
                    a["value_known"] = False
                else:
                    a["unknown_cells"] += 1
                continue
            a[f] += v
        if r.get("goal_scope") is not None:
            a["goal_scopes"].add(str(r.get("goal_scope")))
        if r.get("conversion_date_basis") is not None:
            a["bases"].add(str(r.get("conversion_date_basis")))
        if mature:
            a["mature_days"].add(d)
            a["m_clicks"] += vals["clicks"] or 0
            a["m_cost"] += vals["cost"] or 0
            a["m_conversions"] += vals["conversions"] or 0
            a["m_value"] += vals["conversion_value"] or 0
    for cid in sorted(dup):
        chk.partial(f"campaign {cid}: duplicate campaign/date/network rows (fan-out) — campaign excluded")
        data.pop(cid, None)
    if outside:
        chk.partial(f"{outside} network rows outside export window {start}..{end} excluded")
    if bad_date:
        chk.partial(f"{bad_date} network rows with unparseable date excluded", [f"{ND}:date"])
    if lag is None or snap is None:
        chk.partial(f"day maturity unknown ({ctx.maturity_note}): conversion metrics descriptive only")
    return data


def _rates(a: dict) -> dict:
    return {"clicks": a["clicks"], "cost": a["cost"], "conversions": a["conversions"],
            "cpc": V.ratio(a["cost"], a["clicks"]),
            "mature_clicks": a["m_clicks"], "mature_cost": a["m_cost"], "mature_conversions": a["m_conversions"],
            "mature_value": a["m_value"] if a["value_known"] else None,
            "cvr": V.ratio(a["m_conversions"], a["m_clicks"]), "cpa": V.ratio(a["m_cost"], a["m_conversions"]),
            "roas": V.ratio(a["m_value"], a["m_cost"]) if a["value_known"] else None,
            "days": len(a["days"]), "mature_days": len(a["mature_days"]), "unknown_cells": a["unknown_cells"],
            "goal_scopes": sorted(a["goal_scopes"]), "conversion_date_basis": sorted(a["bases"])}


def _search_campaigns(ctx) -> dict[str, dict]:
    return {str(c.get("id")): c for c in ctx.rows("campaigns") if str(c.get("channel_type") or "").upper() == "SEARCH"}


def _slice_refs(ctx, cid: str, networks) -> list[str]:
    """Stable refs for the reviewed custom/network_daily campaign/network slices over the export window."""
    return [f"{ND}.csv {cid}/{n} {ctx.period_start}..{ctx.period_end}" for n in networks]


def run(ctx) -> None:
    """Run partner-setting inventory, network loading/reconciliation, rates, CPA/ROAS and zero-conversion screens.

    Rules:   Without custom/network_daily all dependent checks skip. CPA Warning needs ctx.mature True, both sides >=
             min_clicks/min_conversions, identical single goal_scope, CPA ratio > 2 and partner CPA > target_cpa;
             failed gates → Info only above spend_floor. ROAS-only objectives and zero-conversion traffic (needs
             tracking_for_campaign True) reach Warning only via ai_review; no target → Info, no verdict.
    """
    window = [ctx.period_start, ctx.period_end]
    search = _search_campaigns(ctx)

    # -- settings inventory (retained even without segmented metrics)
    inv = ctx.check("partner_settings", "Search campaign partner-network setting inventory",
                    {"campaigns": ["id", "channel_type", "search_partners"]})
    if inv.runnable:
        states = {cid: V.boolean(c.get("search_partners")) for cid, c in sorted(search.items())}
        inv.observe("Search Partners setting per Search campaign", enabled=sorted(k for k, v in states.items() if v is True),
                    disabled=sorted(k for k, v in states.items() if v is False),
                    unknown=sorted(k for k, v in states.items() if v is None), snapshot=ctx.snapshot)
        if any(v is None for v in states.values()):
            inv.partial("some partner settings unknown (not treated as disabled)")

    # -- step 1: segmented network evidence
    scope = ctx.check("network_scope", "Load day/network metrics bounded to the export window", {ND: NET})
    data: dict[str, dict[str, dict]] = {}
    if scope.runnable:
        missing_econ = ctx.table(ND).missing(ECON)
        if missing_econ:
            scope.partial("economic scope columns missing: value/goal/basis comparisons limited",
                          [f"{ND}:{c}" for c in missing_econ])
        data = load_network(ctx, scope)
        scope.observe("Network rows loaded", campaigns=sorted(data), window=window, mature=ctx.mature,
                      maturity_note=ctx.maturity_note)
    dependents = ("network_reconciliation", "network_rates", "partner_cpa_comparison", "partner_zero_conversions",
                  "control_applicability", "retain_useful_partners")
    if not scope.runnable:
        for cid in dependents:
            ctx.check(cid, cid.replace("_", " ")).skip("segmented network metrics unavailable", scope.missing)
        return

    # -- step 2: reconcile network sums to campaign totals
    rec = ctx.check("network_reconciliation", "Summed network clicks/cost vs campaign totals",
                    {"campaign_metrics": ["campaign_id", "clicks", "cost"]})
    if rec.runnable:
        cm: dict[str, list] = {}
        for r in ctx.rows("campaign_metrics"):
            cm.setdefault(str(r.get("campaign_id")), []).append(r)
        for cid in sorted(data):
            rows = cm.get(cid, [])
            if len(rows) != 1:
                rec.partial(f"campaign {cid}: {len(rows)} campaign_metrics rows; cannot reconcile")
                continue
            nets = data[cid]
            clicks = sum(a["clicks"] for a in nets.values())
            cost = sum(a["cost"] for a in nets.values())
            tc, tcost = V.num(rows[0].get("clicks")), ctx.money(rows[0].get("cost"))
            dc = V.ratio(abs(clicks - (tc or 0)), tc)
            dcost = V.ratio(abs(cost - (tcost or 0)), tcost)
            ok = dc is not None and dcost is not None and dc <= RECONCILE_TOL and dcost <= RECONCILE_TOL
            rec.observe(f"Campaign {cid}: network sums vs campaign totals", campaign_id=cid, network_clicks=clicks,
                        campaign_clicks=tc, network_cost=cost, campaign_cost=tcost, click_gap=dc, cost_gap=dcost,
                        networks=sorted(nets), other_networks=sorted(n for n in nets if n.startswith("OTHER:")),
                        reconciled=ok, tolerance=RECONCILE_TOL)
            if not ok:
                rec.partial(f"campaign {cid}: network sums do not reconcile within {RECONCILE_TOL:.0%} (omitted networks/days?)")

    # -- step 3: per-campaign network rates from sums
    rates = ctx.check("network_rates", "Cost/click, conversions/click, CPA and ROAS per network", {ND: NET})
    table: dict[str, dict[str, dict]] = {}
    for cid in sorted(data):
        table[cid] = {n: _rates(a) for n, a in sorted(data[cid].items())}
        rates.observe(f"Campaign {cid} network metric table", campaign_id=cid, networks=table[cid], window=window)

    # -- steps 4-5 (+ #58): mature CPA / ROAS comparison against objective
    cmp_ = ctx.check("partner_cpa_comparison", "Mature partner vs Google Search CPA/ROAS against objective", {ND: NET})
    mcl, mco = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
    for cid in sorted(table):
        if cid not in search or G not in table[cid] or P not in table[cid]:
            continue
        g, p = table[cid][G], table[cid][P]
        obj = _objective(ctx, cid)
        tcpa, tsrc = ctx.params.target_cpa(cid)
        troas = V.num(obj.get("target_roas"))
        ev = {"google": g, "partners": p, "cpc_ratio": V.ratio(p["cpc"], g["cpc"]), "cvr_ratio": V.ratio(p["cvr"], g["cvr"]),
              "cpa_ratio": V.ratio(p["cpa"], g["cpa"]), "roas_ratio": V.ratio(p["roas"], g["roas"]),
              "target_cpa": tcpa, "target_cpa_source": tsrc, "target_roas": troas, "objective": obj,
              "min_clicks": mcl.value, "min_conversions": mco.value, "window": window}
        entity = {"campaign_id": cid, "network": P}
        gates = []
        if ctx.mature is not True:
            gates.append(f"maturity {ctx.mature}")
        for side, s in (("google", g), ("partners", p)):
            if s["mature_clicks"] < (mcl.value or 0):
                gates.append(f"{side} mature clicks {s['mature_clicks']:g} < {mcl.value}")
            if s["mature_conversions"] < (mco.value or 0):
                gates.append(f"{side} mature conversions {s['mature_conversions']:g} < {mco.value}")
        scopes = set(g["goal_scopes"]) | set(p["goal_scopes"])
        if len(scopes) != 1 or g["goal_scopes"] != p["goal_scopes"]:
            gates.append(f"goal_scope not single/identical across networks: {sorted(scopes)}")
        ev["gates_failed"] = gates
        floor = ctx.params.get("spend_floor", cid)
        if gates:
            if floor.value is not None and p["cost"] >= floor.value:
                cmp_.finding("partner_comparison_insufficient", "Info", entity,
                             f"Campaign {cid}: partner cost {p['cost']:.2f} {ctx.currency} but comparison gates fail",
                             evidence={**ev, "spend_floor": floor.value}, recommendation="Monitor; no network verdict.",
                             uncertainty="Insufficient sample/maturity or mixed goals: no economic comparison.")
            else:
                cmp_.observe(f"Campaign {cid}: comparison gated", campaign_id=cid, gates=gates)
            continue
        if troas is not None and tcpa is None:
            if ev["roas_ratio"] is not None and ev["roas_ratio"] < 1 / CPA_RATIO and p["roas"] is not None and p["roas"] < troas:
                prov = cmp_.finding("partner_value_underperformance", "Info", entity,
                                    f"Campaign {cid}: partner ROAS {p['roas']:.2f} < half Google ROAS {g['roas']:.2f} "
                                    f"and below target ROAS {troas:g}", evidence=ev,
                                    recommendation="Review value quality before any network change.",
                                    uncertainty="Value definitions/lag can differ by network.")
                cmp_.review("partner_value_underperformance", entity,
                            f"Is partner value quality in campaign {cid} genuinely worse against the ROAS objective?",
                            evidence={**ev, "evidence_refs": _slice_refs(ctx, cid, (P, G))}, provisional=prov,
                            outcomes={"sustained_underperformance": {"severity": "Warning", "recommendation":
                                                                     "Monitor or propose an owner-approved network test."},
                                      "acceptable": {"severity": None, "recommendation": "Retain partner traffic."},
                                      "uncertain": {"severity": "Info", "recommendation": "Collect more mature data."}},
                            guidance="Value-led objective: judge ROAS and value quality; never CVR alone. "
                                     "sustained_underperformance needs proposal.evidence_ref from evidence.evidence_refs.")
            continue
        if tcpa is None:
            cmp_.finding("partner_comparison_no_benchmark", "Info", entity,
                         f"Campaign {cid}: no applicable target; partner CPA ratio {ev['cpa_ratio']} is context only",
                         evidence=ev, recommendation="Supply an approved CPA/ROAS objective before judging partners.",
                         uncertainty=tsrc)
            continue
        if ev["cpa_ratio"] is not None and ev["cpa_ratio"] > CPA_RATIO and p["cpa"] > tcpa:
            cmp_.finding("partner_cpa_above_2x", "Warning", entity,
                         f"Campaign {cid}: mature partner CPA {p['cpa']:.2f} = {ev['cpa_ratio']:.2f}x Google CPA "
                         f"{g['cpa']:.2f} and above target CPA {tcpa:g}",
                         evidence=ev, calculation={"partner_cpa": "mature partner cost / mature partner conversions",
                                                   "google_cpa": "mature Google cost / mature Google conversions",
                                                   "screen": CPA_RATIO, "benchmark": tsrc},
                         recommendation="Monitor or propose an owner-approved partner-setting test; check lead quality/lag.",
                         uncertainty="Historical partner cost is exposure, not savings; network mix may shift.")
        elif ev["cvr_ratio"] is not None and ev["cvr_ratio"] < 1:
            cmp_.finding("partner_lower_cvr_only", "Info", entity,
                         f"Campaign {cid}: partner CVR lower (ratio {ev['cvr_ratio']:.2f}) but CPA screen not met",
                         evidence=ev, recommendation="No action on CVR alone.", uncertainty="CVR is not profitability.")
        else:
            cmp_.observe(f"Campaign {cid}: partner economics within screen", campaign_id=cid, cpa_ratio=ev["cpa_ratio"])

    # -- step 6: zero partner conversions
    zero = ctx.check("partner_zero_conversions", "Zero partner conversions at spend_floor", {ND: NET})
    for cid in sorted(table):
        p = table[cid].get(P)
        if cid not in search or p is None or p["mature_conversions"] != 0:
            continue
        if p["unknown_cells"]:
            zero.partial(f"campaign {cid}: {p['unknown_cells']} unknown partner metric cells; zero conversions unproven")
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            zero.partial(f"spend_floor unresolved for campaign {cid}: {floor.reason}")
            continue
        if p["mature_cost"] < floor.value:
            continue
        tracking, note = ctx.tracking_for_campaign(cid)
        entity = {"campaign_id": cid, "network": P}
        ev = {"partners": p, "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": tracking,
              "tracking_note": note, "mature": ctx.mature, "objective": _objective(ctx, cid), "window": window}
        if ctx.mature is not True or tracking is not True:
            zero.partial(f"campaign {cid}: zero-conversion Warning path disabled (maturity {ctx.mature}; {note})")
            zero.observe(f"Campaign {cid}: zero partner conversions at spend_floor, unverified", **ev)
            continue
        prov = zero.finding("partner_zero_conversions", "Info", entity,
                            f"Campaign {cid}: partner mature cost {p['mature_cost']:.2f} {ctx.currency} with 0 conversions "
                            f"(spend_floor {floor.value:g})", evidence=ev,
                            recommendation="Investigate lead quality, lag and network mix; not an automatic exclusion.",
                            uncertainty="Exposure, not savings; tracking verified only at goal level.")
        zero.review("partner_zero_conversions", entity,
                    f"After tracking/maturity checks, is zero-conversion partner traffic in campaign {cid} relevant but failing?",
                    evidence={**ev, "evidence_refs": _slice_refs(ctx, cid, (P,))}, provisional=prov,
                    outcomes={"confirmed_after_review": {"severity": "Warning", "recommendation":
                                                         "Monitor or propose an owner-approved partner-setting test."},
                              "explained": {"severity": None, "recommendation": "Lag/lead-quality explains it; retain."},
                              "uncertain": {"severity": "Info", "recommendation": "Collect more evidence."}},
                    guidance="Relevance and lead quality only from supplied evidence; exposure is not savings. "
                             "confirmed_after_review needs proposal.evidence_ref from evidence.evidence_refs.")

    # -- step 7: control applicability / temporal change
    ctl = ctx.check("control_applicability", "Partner control applies to the campaign; temporal changes separated",
                    {"campaigns": ["id", "search_partners"]})
    if ctl.runnable:
        for cid in sorted(table):
            if cid not in search or P not in table[cid]:
                continue
            state = V.boolean(search[cid].get("search_partners"))
            if state is False:
                ctl.observe(f"Campaign {cid}: partner traffic in window but setting now disabled (temporal change, "
                            f"not a test)", campaign_id=cid, partner_clicks=table[cid][P]["clicks"])
            elif state is None:
                ctl.partial(f"campaign {cid}: current partner setting unknown")

    # -- step 8: retain useful partner traffic
    keep = ctx.check("retain_useful_partners", "Partner traffic meeting the objective is retained", {ND: NET})
    for cid in sorted(table):
        p = table[cid].get(P)
        if cid not in search or p is None:
            continue
        tcpa, _ = ctx.params.target_cpa(cid)
        if p["cpa"] is not None and tcpa is not None and p["cpa"] <= tcpa:
            keep.observe(f"Campaign {cid}: partner CPA within target — retain", campaign_id=cid, cpa=p["cpa"], target_cpa=tcpa)
    keep.observe("Campaigns without partner traffic are not defects",
                 campaigns=sorted(c for c in search if c not in table or P not in table.get(c, {})))


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   Warning outcomes (sustained_underperformance, confirmed_after_review) require proposal.evidence_ref
             equal to one of item.evidence.evidence_refs (the reviewed campaign/network slices of custom/network_daily
             for the export window); unknown or other-campaign refs are rejected. Other outcomes need no proposal.
    """
    if decision.get("outcome") not in ("sustained_underperformance", "confirmed_after_review"):
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return ["Warning outcome needs proposal.evidence_ref (lead-quality/relevance evidence reviewed)"]
    allowed = sorted((item.evidence or {}).get("evidence_refs") or [])
    if ref not in allowed:
        return [f"evidence_ref {ref} not among the reviewed evidence refs {allowed}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
