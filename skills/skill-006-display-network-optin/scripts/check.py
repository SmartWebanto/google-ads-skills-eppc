"""check.py — skill-006 deterministic Search-campaign Display (CONTENT) opt-in review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-006-display-network-optin/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-005-search-partners-performance/scripts/check.py — same custom/network_daily loader
         (window-bounded, duplicate grain excluded, lag-mature days); kept private per runtime ownership.
rules:   Only SEARCH-channel campaigns are in scope; standalone Display campaigns are never opt-in defects.
         Opt-in comes only from campaigns.display_network (true/false/unknown); unknown ≠ disabled, and a separate
         Display campaign never implies opt-in. Setting timestamp = campaigns manifest exported_at or account snapshot.
         Approved delivery comes only from profile.campaign_objectives[id].search_only (true|false). search_only
         true + explicit opt-in → deterministic Warning; unknown intent → ai_review (Warning outcome needs
         proposal.evidence_ref to the approved requirement) with provisional Info 'enabled setting alone'.
         Display spend share = CONTENT cost / all-network cost of the SAME campaign and window, never daily budget;
         > 5% → Info. Economic comparisons need ctx.mature True and min gates on both sides (observations only).
         Zero CONTENT conversions: mature cost >= spend_floor(campaign), ctx.mature True and
         ctx.tracking_for_campaign True → relevance ai_review (Warning outcome) with provisional Info.
         No recovered-spend forecast; SEARCH_PARTNERS rows are routed to skill-005.
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

SKILL = "skill-006-display-network-optin"
VERSION = "1.0.0"

ND = "custom/network_daily"
NET = ["campaign_id", "date", "ad_network_type", "impressions", "clicks", "cost", "conversions"]
ECON = ["conversion_value", "goal_scope", "conversion_date_basis"]
CANON = ("SEARCH", "SEARCH_PARTNERS", "CONTENT")
SHARE_SCREEN = 0.05
RECONCILE_TOL = 0.01
C, G = "CONTENT", "SEARCH"


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
    seen, dup, outside, bad = set(), set(), 0, 0
    data: dict[str, dict[str, dict]] = {}
    for r in sorted(ctx.rows(ND), key=lambda r: (str(r.get("campaign_id")), str(r.get("date")), str(r.get("ad_network_type")))):
        cid, d, net = str(r.get("campaign_id")), V.parse_date(r.get("date")), _canon(ctx, r.get("ad_network_type"))
        if d is None:
            bad += 1
            continue
        if start and end and not (start <= d <= end):
            outside += 1
            continue
        key = (str(r.get("account_id") or ""), cid, d, net)
        if key in seen:
            dup.add(cid)
            continue
        seen.add(key)
        a = data.setdefault(cid, {}).setdefault(net, {"clicks": 0.0, "cost": 0.0, "conversions": 0.0, "m_clicks": 0.0,
                                                      "m_cost": 0.0, "m_conversions": 0.0, "days": set(),
                                                      "unknown_cells": 0, "goal_scopes": set()})
        a["days"].add(d)
        vals = {"clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")), "conversions": V.num(r.get("conversions"))}
        for f, v in vals.items():
            if v is None:
                a["unknown_cells"] += 1
            else:
                a[f] += v
        if r.get("goal_scope") is not None:
            a["goal_scopes"].add(str(r.get("goal_scope")))
        if lag is not None and snap is not None and (snap - d).days >= lag:
            a["m_clicks"] += vals["clicks"] or 0
            a["m_cost"] += vals["cost"] or 0
            a["m_conversions"] += vals["conversions"] or 0
    for cid in sorted(dup):
        chk.partial(f"campaign {cid}: duplicate campaign/date/network rows (fan-out) — campaign excluded")
        data.pop(cid, None)
    if outside:
        chk.partial(f"{outside} network rows outside export window {start}..{end} excluded")
    if bad:
        chk.partial(f"{bad} network rows with unparseable date excluded", [f"{ND}:date"])
    if lag is None or snap is None:
        chk.partial(f"day maturity unknown ({ctx.maturity_note}): conversion metrics descriptive only")
    return data


def _summ(a: dict) -> dict:
    return {"clicks": a["clicks"], "cost": a["cost"], "conversions": a["conversions"], "mature_clicks": a["m_clicks"],
            "mature_cost": a["m_cost"], "mature_conversions": a["m_conversions"],
            "cvr": V.ratio(a["m_conversions"], a["m_clicks"]), "cpa": V.ratio(a["m_cost"], a["m_conversions"]),
            "days": len(a["days"]), "unknown_cells": a["unknown_cells"], "goal_scopes": sorted(a["goal_scopes"])}


def _setting_time(ctx) -> str | None:
    t = ctx.table("campaigns")
    ts = (t.manifest or {}).get("exported_at") if t is not None else None
    return ts or (ctx.snapshot.isoformat() if ctx.snapshot else None)


def run(ctx) -> None:
    """Run Search-campaign Display opt-in intent, spend share, network outcome and zero-conversion checks.

    Rules:   Only SEARCH campaigns are in scope; display_network unknown is never 'disabled'. Deterministic Warning only
             for explicit opt-in on search_only true; unknown intent → provisional Info + ai_review. CONTENT spend share
             > 5% is Info; economics are observations gated on ctx.mature and min_clicks/min_conversions.
             Zero-CONTENT-conversion review needs cost >= spend_floor, ctx.mature True and tracking True, else partial.
    """
    window = [ctx.period_start, ctx.period_end]
    search = {str(c.get("id")): c for c in ctx.rows("campaigns") if str(c.get("channel_type") or "").upper() == "SEARCH"}
    ts = _setting_time(ctx)

    # -- step 2: explicit content-network settings on Search campaigns
    inv = ctx.check("optin_inventory", "Display opt-in setting per Search campaign",
                    {"campaigns": ["id", "channel_type", "display_network"]})
    optin: dict[str, bool | None] = {}
    if inv.runnable:
        optin = {cid: V.boolean(c.get("display_network")) for cid, c in sorted(search.items())}
        inv.observe("Display opt-in inventory", enabled=sorted(k for k, v in optin.items() if v is True),
                    disabled=sorted(k for k, v in optin.items() if v is False),
                    unknown=sorted(k for k, v in optin.items() if v is None), setting_timestamp=ts,
                    non_search_display_campaigns=sorted(str(c.get("id")) for c in ctx.rows("campaigns")
                                                         if str(c.get("channel_type") or "").upper() == "DISPLAY"))
        if any(v is None for v in optin.values()):
            inv.partial("some Search campaigns have unknown opt-in (not treated as disabled)")

    # -- step 3: approved intent
    intent = ctx.check("intent_review", "Opt-in vs approved Search-only delivery",
                       {"campaigns": ["id", "channel_type", "display_network"]})
    if intent.runnable:
        for cid in sorted(k for k, v in optin.items() if v is True):
            so = _objective(ctx, cid).get("search_only")
            so = V.boolean(so) if not isinstance(so, bool) else so
            entity = {"campaign_id": cid}
            ev = {"display_network": True, "setting_timestamp": ts, "search_only": so, "objective": _objective(ctx, cid),
                  "approved_constraints": ctx.profile.get("approved_constraints")}
            if so is True:
                intent.finding("optin_contradicts_search_only", "Warning", entity,
                               f"Search campaign {cid} has Display opt-in enabled but approved delivery is Search-only",
                               evidence=ev, recommendation="Owner reviews the network setting; no change is executed.",
                               uncertainty="Setting snapshot only; the contradiction is with the approved profile requirement.")
            elif so is False:
                intent.observe(f"Campaign {cid}: Display opt-in approved (search_only false)", campaign_id=cid)
            else:
                prov = intent.finding("optin_enabled_intent_unknown", "Info", entity,
                                      f"Search campaign {cid} has Display opt-in enabled; approved intent unknown",
                                      evidence=ev, recommendation="Ask the owner whether supplemental Display is intended.",
                                      uncertainty="Enabled by design is not a failure.")
                intent.review("optin_contradicts_search_only", entity,
                              f"Does the supplied business evidence require Search-only delivery for campaign {cid}?",
                              evidence=ev, provisional=prov,
                              outcomes={"search_only_required": {"severity": "Warning", "recommendation":
                                                                 "Owner reviews the Display opt-in setting."},
                                        "display_approved": {"severity": None, "recommendation": "Keep; document intent."},
                                        "unknown": {"severity": "Info", "recommendation": "Owner-review question."}},
                              guidance="search_only_required needs proposal.evidence_ref citing the approved requirement.")

    # -- step 1: segmented network evidence
    scope = ctx.check("network_scope", "Load day/network metrics bounded to the export window", {ND: NET})
    data: dict[str, dict[str, dict]] = {}
    if scope.runnable:
        miss = ctx.table(ND).missing(ECON)
        if miss:
            scope.partial("economic scope columns missing", [f"{ND}:{c}" for c in miss])
        data = {cid: v for cid, v in load_network(ctx, scope).items() if cid in search}
        scope.observe("Network rows loaded for Search campaigns", campaigns=sorted(data), window=window,
                      partner_rows_routed_to_005=sorted(c for c, v in data.items() if "SEARCH_PARTNERS" in v))
    deps = ("content_share", "network_outcomes", "content_zero_conversions")
    if not scope.runnable:
        for cid in deps:
            ctx.check(cid, cid.replace("_", " ")).skip("CONTENT metrics unavailable: no Display spend estimate", scope.missing)
        _no_forecast(ctx)
        return

    # -- step 4: CONTENT spend share, reconciled
    share = ctx.check("content_share", "CONTENT cost / total campaign cost", {ND: NET})
    if ctx.table("campaign_metrics") is None or ctx.table("campaign_metrics").missing(["campaign_id", "cost"]):
        share.partial("campaign_metrics cost unavailable: network totals not reconciled", ["campaign_metrics:cost"])
    cm: dict[str, list] = {}
    for r in ctx.rows("campaign_metrics"):
        cm.setdefault(str(r.get("campaign_id")), []).append(r)
    for cid in sorted(data):
        nets = data[cid]
        total = sum(a["cost"] for a in nets.values())
        content = nets.get(C, {}).get("cost", 0.0) if C in nets else 0.0
        rows = cm.get(cid, [])
        tcost = ctx.money(rows[0].get("cost")) if len(rows) == 1 else None
        gap = V.ratio(abs(total - (tcost or 0)), tcost)
        if tcost is not None and (gap is None or gap > RECONCILE_TOL):
            share.partial(f"campaign {cid}: network cost {total:.2f} does not reconcile with campaign cost {tcost}")
        s = V.ratio(content, total)
        data_ev = {"campaign_id": cid, "content_cost": content, "all_network_cost": total, "campaign_metrics_cost": tcost,
                   "reconcile_gap": gap, "content_share": s, "display_network": optin.get(cid), "setting_timestamp": ts,
                   "window": window, "unknown_cells": sum(a["unknown_cells"] for a in nets.values())}
        share.observe(f"Campaign {cid}: CONTENT share of campaign cost", **data_ev)
        if s is not None and s > SHARE_SCREEN and not data_ev["unknown_cells"]:
            share.finding("content_spend_share", "Info", {"campaign_id": cid},
                          f"CONTENT is {s:.1%} of campaign {cid} cost ({content:.2f}/{total:.2f} {ctx.currency})",
                          evidence=data_ev, calculation={"numerator": "CONTENT cost", "denominator": "all-network cost",
                                                         "screen": SHARE_SCREEN},
                          recommendation="Prioritize the intent review; share alone is not a defect.",
                          uncertainty="Exposure, not savings.")

    # -- step 5: mature network outcomes (observations only)
    out = ctx.check("network_outcomes", "Mature CONTENT vs Search outcomes with sample gates", {ND: NET})
    mcl, mco = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
    if ctx.mature is not True:
        out.partial(f"maturity {ctx.mature}: descriptive only ({ctx.maturity_note})")
    for cid in sorted(data):
        if C not in data[cid] or G not in data[cid]:
            continue
        c, g = _summ(data[cid][C]), _summ(data[cid][G])
        gated = ctx.mature is not True or any(s["mature_clicks"] < (mcl.value or 0) or s["mature_conversions"] < (mco.value or 0)
                                              for s in (c, g)) or c["goal_scopes"] != g["goal_scopes"]
        out.observe(f"Campaign {cid}: CONTENT vs SEARCH", campaign_id=cid, content=c, search=g, gated=gated,
                    cpa_ratio=None if gated else V.ratio(c["cpa"], g["cpa"]), min_clicks=mcl.value, min_conversions=mco.value)

    # -- step 6: zero CONTENT conversions at spend_floor
    zero = ctx.check("content_zero_conversions", "Zero CONTENT conversions at spend_floor", {ND: NET})
    for cid in sorted(data):
        a = data[cid].get(C)
        if a is None or a["m_conversions"] != 0:
            continue
        if a["unknown_cells"]:
            zero.partial(f"campaign {cid}: unknown CONTENT cells; zero conversions unproven")
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            zero.partial(f"spend_floor unresolved for campaign {cid}: {floor.reason}")
            continue
        if a["m_cost"] < floor.value:
            continue
        tracking, note = ctx.tracking_for_campaign(cid)
        ev = {"content": _summ(a), "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": tracking,
              "tracking_note": note, "mature": ctx.mature, "window": window, "objective": _objective(ctx, cid)}
        if ctx.mature is not True or tracking is not True:
            zero.partial(f"campaign {cid}: zero-conversion Warning path disabled (maturity {ctx.mature}; {note})")
            zero.observe(f"Campaign {cid}: zero CONTENT conversions at spend_floor, unverified", **ev)
            continue
        entity = {"campaign_id": cid, "network": C}
        prov = zero.finding("content_zero_conversions", "Info", entity,
                            f"Campaign {cid}: mature CONTENT cost {a['m_cost']:.2f} {ctx.currency} with 0 conversions",
                            evidence=ev, recommendation="Confirm relevance before proposing a setting review.",
                            uncertainty="Exposure, not recoverable spend.")
        zero.review("content_zero_conversions", entity,
                    f"Is zero-conversion Display traffic in campaign {cid} relevant but failing after tracking checks?",
                    evidence=ev, provisional=prov,
                    outcomes={"confirmed_after_review": {"severity": "Warning", "recommendation":
                                                         "Owner reviews the Display network setting."},
                              "explained": {"severity": None, "recommendation": "Assist/awareness role explains it; keep."},
                              "uncertain": {"severity": "Info", "recommendation": "Collect more evidence."}},
                    guidance="Relevance from supplied evidence only; no forecast of recovered spend.")
    _no_forecast(ctx)


def _no_forecast(ctx) -> None:
    # -- steps 7-8: proposals are owner reviews; no recovered-spend forecast; partner findings belong to 005
    chk = ctx.check("setting_review_scope", "Supported-control proposals without forecasts",
                    {"campaigns": ["id", "channel_type", "display_network"]})
    if chk.runnable:
        chk.observe("Proposals limited to owner review of the Display setting; no recovered spend or Search traffic "
                    "forecast; SEARCH_PARTNERS routed to skill-005")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning outcomes require proposal.evidence_ref to the approved requirement / relevance evidence."""
    if decision.get("outcome") in ("search_only_required", "confirmed_after_review") and \
            not (decision.get("proposal") or {}).get("evidence_ref"):
        return ["Warning outcome needs proposal.evidence_ref citing supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
