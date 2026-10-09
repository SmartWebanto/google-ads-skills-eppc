"""check.py — skill-039 deterministic bid strategy, legacy setting and first-page estimate review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-039-bid-strategy-appropriateness-audit/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #29 High CPC Bid Alerts (nilsrooijmans.com) — clean-room reimplementation of "keyword max CPC above
         a configured ceiling" using the effective manual base bid against external approved_max_cpc; report only.
rules:   Target sources: config standalone/embedded fields, campaigns targets and linked portfolio; disagreeing
         values are an Info conflict needing verification, never arbitrary precedence.
         Strategy/objective suitability and tracking/value fitness are AI judgment (ai_review). Critical only via
         the value/goal-failure outcome and verify() demands proposal.evidence_ref.
         Legacy Warning only when: flag explicitly enabled in a CURRENT config snapshot AND a notice row for that
         campaign says unsupported/deprecated for the same channel (and subtype when both given) with
         notice_effective_date <= snapshot_at and an official_source_url. Absent flag = unknown, never disabled.
         First-page subcheck only for MANUAL_CPC SEARCH campaigns. Effective base bid = explicit non-inherited
         keyword bid, else supplied ad-group default when inherited; unknown inheritance/estimate → skipped row.
         Bid below estimate is Info at most; reviewed only when estimate <= approved_max_cpc (economic headroom).
         verify(): proposed bids must exceed the current bid and stay <= approved_max_cpc; migration replacements
         must be listed in the campaign's applicable_strategy and carry rollback criteria.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
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

SKILL = "skill-039-bid-strategy-appropriateness-audit"
VERSION = "1.0.0"

CONFIG = "custom/bidding_configuration"
BIDS = "custom/manual_keyword_bids"
CONSTR = "external/bidding_constraints"
CONFIG_TARGETS = (("CPA", "standalone_target_cpa", "standalone"), ("ROAS", "standalone_target_roas", "standalone"),
                  ("CPA", "maximize_conversions_target_cpa", "embedded"),
                  ("ROAS", "maximize_value_target_roas", "embedded"))
SMART = {"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"}
VALUE_BASED = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
BID_COLS = ["campaign_id", "ad_group_id", "keyword_id", "keyword_cpc_bid", "keyword_bid_is_inherited",
            "ad_group_default_cpc", "first_page_estimate", "estimate_at", "estimate_status", "eligibility_status"]
SEPS = (";", "|", ",")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _pos(v) -> float | None:
    f = V.num(v)
    return f if f is not None and f > 0 else None


def _missing(ctx, key: str, cols: list[str]) -> list[str]:
    t = ctx.table(key)
    return [f"{key} (file)"] if t is None else [f"{key}:{c}" for c in t.missing(cols)]


def _latest_by_campaign(rows, date_col: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (_s(r.get("campaign_id")), _s(r.get(date_col)))):
        if _s(r.get("campaign_id")):
            out[_s(r.get("campaign_id"))] = r
    return out


def _constraints(ctx) -> dict[str, list[dict]]:
    """campaign_id -> latest row per constraint_id effective at the snapshot/as-of date."""
    cut = ctx.snapshot or ctx.as_of
    latest: dict[tuple, dict] = {}
    for r in sorted(ctx.rows(CONSTR), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("constraint_id")),
                                                      _s(r.get("effective_date")))):
        d = V.parse_date(r.get("effective_date"))
        if d is not None and cut is not None and d > cut:
            continue
        latest[(_s(r.get("campaign_id")), _s(r.get("constraint_id")))] = r
    out: dict[str, list[dict]] = {}
    for (cid, _), r in sorted(latest.items()):
        out.setdefault(cid, []).append(r)
    return out


def _field(rows: list[dict], col: str) -> tuple[str | None, str | None]:
    """Single non-null value across constraint rows, or (None, conflict note)."""
    vals = sorted({_s(r.get(col)) for r in rows if _s(r.get(col))})
    if len(vals) > 1:
        return None, f"{col} conflicts: {vals}"
    return (vals[0] if vals else None), None


def _strategy_for(ctx, row) -> dict | None:
    strategies = ctx.rows("bidding_strategies")
    sid = _s(row.get("bidding_strategy_id") or row.get("strategy_id"))
    hit = next((s for s in strategies if sid and _s(s.get("id")) == sid), None)
    if hit is None:
        hit = next((s for s in sorted(strategies, key=lambda s: _s(s.get("id")))
                    if _s(row.get("id")) in V.split_list(s.get("campaign_ids"), SEPS)), None)
    return hit


def _strategy_type(camp: dict, cfg: dict | None) -> str:
    return (_s(cfg.get("strategy_type")) if cfg else "").upper() or _s(camp.get("bidding_strategy_type")).upper()


def _objective(ctx, cid: str, rows: list[dict]) -> tuple[dict | None, str]:
    obj, conflict = _field(rows, "objective")
    prof = ctx.profile.get("campaign_objectives") or {}
    pobj = next((v for k, v in prof.items() if str(k) == cid), None) if isinstance(prof, dict) else None
    if conflict:
        return None, conflict
    if obj:
        return {"objective": obj, "source": f"{CONSTR}.objective"}, ""
    if isinstance(pobj, dict) and (pobj.get("role") or pobj.get("goal_ids")):
        return {"objective": pobj.get("role"), "goal_ids": pobj.get("goal_ids"),
                "source": f"profile.campaign_objectives[{cid}]"}, ""
    return None, f"campaign {cid}: no explicit objective ({CONSTR}:objective or profile.campaign_objectives)"


def _effective_bid(r) -> tuple[float | None, str]:
    inherited = V.boolean(r.get("keyword_bid_is_inherited"))
    if inherited is False:
        b = _pos(r.get("keyword_cpc_bid"))
        return (b, "keyword_cpc_bid") if b is not None else (None, "explicit keyword bid missing")
    if inherited is True:
        b = _pos(r.get("ad_group_default_cpc"))
        return (b, "ad_group_default_cpc (inherited)") if b is not None else (None, "ad-group default missing")
    return None, "inheritance unknown"


def _eligible(r) -> bool | None:
    t = V.norm_text(r.get("eligibility_status"))
    if not t:
        return None
    if any(w in t for w in ("not", "inelig", "disapproved", "paused", "removed", "limited")):
        return False
    return t in ("eligible", "enabled", "serving", "active")


def run(ctx) -> None:
    """Run bid-strategy target resolution, objective fit, value-goal, legacy-setting and first-page bid checks.

    Rules:   Disagreeing target sources → Info target_source_conflict, never picked by precedence. Strategy fit is
             ai_review (Info at most); Critical only via value_goal_configuration review with proposal.evidence_ref.
             Legacy Warning only for an explicitly enabled flag in a current snapshot plus a dated official notice; else
             Info. First-page check only for MANUAL_CPC SEARCH: below-estimate is Info, reviewed only when estimate <=
             approved_max_cpc.
    """
    constraints = _constraints(ctx)
    cfgs = _latest_by_campaign(ctx.rows(CONFIG), "snapshot_at") if ctx.table(CONFIG) else {}
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}

    # step 1 — target source ledger
    led = ctx.check("target_source_ledger", "Strategy links and actual target source (step 1)",
                    {"campaigns": ["id", "bidding_strategy_type"]})
    if led.runnable:
        if ctx.table(CONFIG) is None:
            led.partial("configuration export missing: embedded/standalone target fields unknown",
                        _missing(ctx, CONFIG, ["campaign_id", "strategy_type", "effective_target_source"]))
        if ctx.table("bidding_strategies") is None:
            led.partial("portfolio targets unknown", ["bidding_strategies (file)"])
        for cid in sorted(camps):
            row, cfg = camps[cid], cfgs.get(cid)
            cands = []
            for kind, col in (("CPA", "target_cpa"), ("ROAS", "target_roas")):
                if _pos(row.get(col)) is not None:
                    cands.append((kind, _pos(row.get(col)), f"campaigns.{col}"))
            strat = _strategy_for(ctx, row)
            if strat:
                for kind, col in (("CPA", "target_cpa"), ("ROAS", "target_roas")):
                    if _pos(strat.get(col)) is not None:
                        cands.append((kind, _pos(strat.get(col)), f"bidding_strategies.{col}[{strat.get('id')}]"))
            if cfg:
                for kind, col, label in CONFIG_TARGETS:
                    if _pos(cfg.get(col)) is not None:
                        cands.append((kind, _pos(cfg.get(col)), f"{CONFIG}.{col} ({label})"))
            values = sorted({(k, round(v, 6)) for k, v, _ in cands})
            ev = {"strategy_type": _strategy_type(row, cfg), "strategy_id": (strat or {}).get("id"),
                  "declared_source": (cfg or {}).get("effective_target_source"),
                  "sources": [f"{s}={v:g}" for _, v, s in cands], "snapshot_at": (cfg or {}).get("snapshot_at")}
            led.observe(f"Campaign {cid}: strategy {ev['strategy_type'] or 'unknown'}, targets {values or 'none'}",
                        campaign_id=cid, **ev)
            if len(values) > 1:
                led.finding("target_source_conflict", "Info", {"campaign_id": cid},
                            f"Campaign {cid}: target sources disagree ({'; '.join(ev['sources'])})", evidence=ev,
                            recommendation="Verify the effective target in the current platform settings before any proposal.",
                            uncertainty="Conflicting exports may reflect different snapshot times.")

    # step 2 — objective alignment
    obj = ctx.check("objective_alignment", "Strategy optimization vs explicit campaign goals (step 2)",
                    {"campaigns": ["id", "bidding_strategy_type"]})
    if obj.runnable:
        for cid in sorted(camps):
            o, why = _objective(ctx, cid, constraints.get(cid, []))
            stype = _strategy_type(camps[cid], cfgs.get(cid))
            if o is None or not stype:
                obj.partial(why or f"campaign {cid}: strategy type unknown")
                continue
            obj.review("strategy_objective_fit", {"campaign_id": cid},
                       f"Does strategy {stype} of campaign {cid} optimize toward its explicit objective "
                       f"({o.get('objective')}; goals {o.get('goal_ids') or ctx.goal_ids(cid)})?",
                       evidence={"strategy_type": stype, **o, "effective_goal_ids": ctx.goal_ids(cid),
                                 "channel_type": camps[cid].get("channel_type")},
                       outcomes={"aligned": {"severity": None, "recommendation": "Keep; no migration mandate."},
                                 "misaligned": {"severity": "Info", "recommendation":
                                                "Owner review of a supported, objective-aligned strategy with guardrails."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request the campaign objective/goal set."}},
                       guidance="Manual CPC, clicks and impression-share goals can be valid; low conversion count affects "
                                "confidence, not eligibility. Never force Smart Bidding or tROAS.")

    # step 3 — tracking readiness and value fitness
    trk = ctx.check("tracking_value_readiness", "Tracking readiness and business-value fitness (step 3)",
                    {"campaigns": ["id", "bidding_strategy_type"], "conversion_actions": ["id", "status", "value_settings"]})
    if trk.runnable:
        if ctx.table(CONSTR) is None:
            trk.partial("business value basis and tracking readiness unknown",
                        _missing(ctx, CONSTR, ["campaign_id", "tracking_readiness", "value_basis"]))
        actions = {_s(a.get("id")): a for a in ctx.rows("conversion_actions")}
        for cid in sorted(camps):
            stype = _strategy_type(camps[cid], cfgs.get(cid))
            if stype not in SMART:
                continue
            tracking, note = ctx.tracking_for_campaign(cid)
            readiness, c1 = _field(constraints.get(cid, []), "tracking_readiness")
            value_basis, c2 = _field(constraints.get(cid, []), "value_basis")
            goals = ctx.goal_ids(cid)
            vals = {g: (actions.get(g) or {}).get("value_settings") for g in goals}
            zero_value = stype in VALUE_BASED and goals and all(
                _s(v).lower() in ("", "0", "none", "no value", "no_value") for v in vals.values())
            not_ready = V.boolean(readiness) is False or V.norm_text(readiness) in ("not ready", "not_ready", "broken")
            ev = {"strategy_type": stype, "tracking": tracking, "tracking_note": note, "tracking_readiness": readiness,
                  "value_basis": value_basis, "goal_value_settings": vals, "conflicts": [c for c in (c1, c2) if c]}
            if tracking is False or not_ready or zero_value:
                trk.review("value_goal_configuration", {"campaign_id": cid},
                           f"Does the tracking/value configuration of campaign {cid} ({stype}) materially corrupt "
                           f"active optimization?", evidence=ev,
                           outcomes={"material_config_failure": {"severity": "Critical", "recommendation":
                                                                 "Repair measurement before any strategy change; cite evidence."},
                                     "readiness_gap": {"severity": "Info", "recommendation":
                                                       "Resolve tracking/value readiness before proposing strategy changes."},
                                     "ready": {"severity": None, "recommendation": "No action."},
                                     "uncertain": {"severity": "Info", "recommendation": "Request tracking diagnostics."}},
                           guidance="material_config_failure requires proposal.evidence_ref to supplied diagnostics "
                                    "showing the failure affects active bidding.")
            else:
                trk.observe(f"Campaign {cid}: readiness screen passed no failure signal", campaign_id=cid, **ev)
                if tracking is None:
                    trk.partial(note)

    # step 4 — legacy settings
    leg = ctx.check("legacy_setting_scope", "Channel-dated legacy setting inventory (step 4)",
                    {CONFIG: ["campaign_id", "channel", "legacy_ecpc_setting", "legacy_setting_source", "snapshot_at"]})
    confirmed: dict[str, dict] = {}
    if leg.runnable:
        notice_cols = ["campaign_id", "supported_state", "channel", "notice_effective_date", "official_source_url"]
        if ctx.table(CONSTR) is None or ctx.table(CONSTR).missing(notice_cols):
            leg.partial("platform notice scope unknown: enabled flags stay unverified", _missing(ctx, CONSTR, notice_cols))
        unknown = 0
        for cid, cfg in sorted(cfgs.items()):
            raw = V.norm_text(cfg.get("legacy_ecpc_setting"))
            flag = V.boolean(raw) if raw not in ("enabled", "disabled", "on", "off") else raw in ("enabled", "on")
            if flag is None:
                unknown += 1
                continue
            if not flag:
                continue
            snap = V.parse_date(cfg.get("snapshot_at"))
            channel, subtype = V.norm_text(cfg.get("channel")), V.norm_text(cfg.get("subtype"))
            current = snap is not None and (ctx.snapshot is None or snap >= ctx.snapshot)
            scoped = []
            for n in constraints.get(cid, []):
                state = V.norm_text(n.get("supported_state"))
                nd = V.parse_date(n.get("notice_effective_date"))
                nsub = V.norm_text(n.get("subtype"))
                if (("unsupported" in state or "deprecated" in state) and V.norm_text(n.get("channel")) == channel
                        and (not nsub or not subtype or nsub == subtype) and nd and snap and nd <= snap
                        and _s(n.get("official_source_url"))):
                    scoped.append(n)
            ev = {"legacy_ecpc_setting": cfg.get("legacy_ecpc_setting"), "legacy_setting_source": cfg.get("legacy_setting_source"),
                  "channel": cfg.get("channel"), "subtype": cfg.get("subtype"), "snapshot_at": cfg.get("snapshot_at"),
                  "export_snapshot": ctx.snapshot, "source_ref": cfg.get("source_ref")}
            entity = {"campaign_id": cid, "setting": "legacy_ecpc"}
            if scoped and current:
                n = scoped[0]
                ev.update({"notice_effective_date": n.get("notice_effective_date"), "official_source_url":
                           n.get("official_source_url"), "supported_state": n.get("supported_state"),
                           "checked_at": n.get("checked_at")})
                confirmed[cid] = ev
                leg.finding("deprecated_setting_in_scope", "Warning", entity,
                            f"Campaign {cid}: legacy ECPC enabled in the current {cfg.get('channel')} snapshot "
                            f"{cfg.get('snapshot_at')} after notice effective {n.get('notice_effective_date')}",
                            evidence=ev, recommendation="Request an owner-reviewed migration to a supported, objective-aligned control.",
                            uncertainty="Scope follows the supplied notice row; confirm current platform behavior.")
            else:
                leg.finding("legacy_setting_scope_unverified", "Info", entity,
                            f"Campaign {cid}: legacy ECPC flag enabled but no dated in-scope notice for "
                            f"{cfg.get('channel')} (or snapshot not current)", evidence=ev,
                            recommendation="Supply the channel-specific notice and current settings before any migration.",
                            uncertainty="Historical flags can describe past valid configurations.")
        if unknown:
            leg.partial(f"{unknown} campaigns with unknown legacy flag (unknown, not enabled/disabled)")

    # step 5 — migration review
    mig = ctx.check("migration_review", "Supported replacement for confirmed legacy settings (step 5)",
                    {CONFIG: ["campaign_id", "legacy_ecpc_setting"], CONSTR: ["campaign_id", "applicable_strategy"]})
    if mig.runnable:
        for cid, ev in sorted(confirmed.items()):
            allowed = sorted({s for r in constraints.get(cid, []) for s in V.split_list(r.get("applicable_strategy"), SEPS)})
            o, _ = _objective(ctx, cid, constraints.get(cid, []))
            mig.review("legacy_migration_plan", {"campaign_id": cid, "setting": "legacy_ecpc"},
                       f"Which supported replacement fits campaign {cid}'s objective, tracking/value readiness and risk?",
                       evidence={**ev, "applicable_strategies": allowed, "objective": o,
                                 "approved_max_cpc": _field(constraints.get(cid, []), "approved_max_cpc")[0]},
                       outcomes={"supported_replacement": {"severity": None, "recommendation":
                                                           "Owner-approved migration with rollback criteria and observation window."},
                                 "needs_business_input": {"severity": "Info", "recommendation":
                                                          "Collect objective/value readiness before choosing a replacement."}},
                       guidance="supported_replacement needs proposal.replacement from applicable_strategies and "
                                "proposal.rollback. No automatic Shopping Maximize Conversions.")
        mig.observe("Confirmed legacy settings needing migration review", count=len(confirmed))

    # steps 6-7 — manual CPC first-page estimate
    manual = sorted(cid for cid, r in camps.items() if _strategy_type(r, cfgs.get(cid)) == "MANUAL_CPC"
                    and _s(r.get("channel_type")).upper() == "SEARCH")
    eff = ctx.check("effective_keyword_bid", "Effective manual-CPC keyword base bid (step 6)",
                    {BIDS: BID_COLS, "campaigns": ["id", "bidding_strategy_type", "channel_type"]},
                    applicable=bool(manual) or not camps, na_reason="no manual-CPC Search campaigns in the inventory")
    below = ctx.check("below_first_page_estimate", "Base bid vs current first-page estimate (step 7)",
                      {BIDS: BID_COLS}, applicable=bool(manual) or not camps,
                      na_reason="no manual-CPC Search campaigns in the inventory")
    cap = ctx.check("high_cpc_bid_cap", "Effective bid above approved max CPC (index #29)",
                    {BIDS: BID_COLS, CONSTR: ["campaign_id", "approved_max_cpc"]}, applicable=bool(manual) or not camps,
                    na_reason="no manual-CPC Search campaigns in the inventory")
    resolved = []
    if eff.runnable:
        unknown = 0
        for r in sorted(ctx.rows(BIDS), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("keyword_id")))):
            if _s(r.get("campaign_id")) not in manual:
                continue
            bid, src = _effective_bid(r)
            if bid is None:
                unknown += 1
                continue
            resolved.append((r, bid, src))
        if unknown:
            eff.partial(f"{unknown} manual keywords skipped: explicit bid/inheritance/default unknown")
        eff.observe("Manual-CPC keyword base bids resolved", resolved=len(resolved), unresolved=unknown)
    if below.runnable and resolved:
        no_est = inelig = no_cap = 0
        for r, bid, src in resolved:
            cid = _s(r.get("campaign_id"))
            est = _pos(r.get("first_page_estimate"))
            status = V.norm_text(r.get("estimate_status"))
            if est is None or any(w in status for w in ("stale", "unavailable", "missing")):
                no_est += 1
                continue
            if _eligible(r) is not True:
                inelig += 1
                continue
            if bid >= est:
                continue
            max_cpc = _pos(_field(constraints.get(cid, []), "approved_max_cpc")[0])
            est_at = V.parse_date(r.get("estimate_at"))
            ev = {"effective_bid": bid, "bid_source": src, "first_page_estimate": est, "estimate_at": r.get("estimate_at"),
                  "estimate_age_days": (ctx.snapshot - est_at).days if ctx.snapshot and est_at else None,
                  "estimate_status": r.get("estimate_status"), "eligibility_status": r.get("eligibility_status"),
                  "approved_max_cpc": max_cpc, "source_ref": r.get("source_ref")}
            entity = {"campaign_id": cid, "ad_group_id": _s(r.get("ad_group_id")), "keyword_id": _s(r.get("keyword_id"))}
            if max_cpc is None:
                no_cap += 1
                continue
            if est > max_cpc:
                below.observe(f"Keyword {entity['keyword_id']}: estimate above approved max CPC; no economic headroom",
                              **entity, **ev)
                continue
            prov = below.finding("bid_below_first_page_estimate", "Info", entity,
                                 f"Keyword {entity['keyword_id']}: base bid {bid:.2f} below first-page estimate {est:.2f} "
                                 f"(approved max CPC {max_cpc:.2f})", evidence=ev,
                                 recommendation="Review relevance/demand; any bid exploration capped by approved max CPC.",
                                 uncertainty="An estimate is an indicative visibility constraint, not an auction floor or lost demand.")
            below.review("first_page_bid_relevance", entity,
                         f"Is keyword {entity['keyword_id']} relevant with real demand, so a capped bid test is worth review?",
                         evidence=ev, provisional=prov,
                         outcomes={"relevant_with_headroom": {"severity": "Info", "recommendation":
                                                              "Propose a capped bid test (proposal.proposed_bid)."},
                                   "not_relevant_or_no_demand": {"severity": None, "recommendation": "Keep the bid."},
                                   "uncertain": {"severity": "Info", "recommendation": "Request demand/relevance evidence."}},
                         guidance="proposal.proposed_bid, if given, must exceed the current bid and not exceed approved_max_cpc.")
        for n, why in ((no_est, "without a current first-page estimate"), (inelig, "not confirmed eligible"),
                       (no_cap, f"below estimate but economic headroom unknown ({CONSTR}:approved_max_cpc) — request business value")):
            if n:
                below.partial(f"{n} keywords {why}")
    if cap.runnable and resolved:
        n = 0
        for r, bid, src in resolved:
            cid = _s(r.get("campaign_id"))
            max_cpc = _pos(_field(constraints.get(cid, []), "approved_max_cpc")[0])
            if max_cpc is None or bid <= max_cpc:
                continue
            n += 1
            entity = {"campaign_id": cid, "ad_group_id": _s(r.get("ad_group_id")), "keyword_id": _s(r.get("keyword_id"))}
            cap.finding("manual_bid_above_approved_max_cpc", "Info", entity,
                        f"Keyword {entity['keyword_id']}: effective bid {bid:.2f} exceeds approved max CPC {max_cpc:.2f}",
                        evidence={"effective_bid": bid, "bid_source": src, "approved_max_cpc": max_cpc,
                                  "excess": round(bid - max_cpc, 2), "source_ref": r.get("source_ref")},
                        recommendation="Owner review: lower the bid to the approved ceiling or document the exception.",
                        uncertainty="Max CPC is a ceiling, not the actual CPC paid.")
        cap.observe("Manual bids compared with approved max CPC", above=n, compared=len(resolved))

    # step 8 — guardrails for proposals
    grd = ctx.check("proposal_guardrails", "Owner and economic guardrails for proposals (step 8)",
                    {CONSTR: ["campaign_id", "owner"]})
    if grd.runnable:
        for cid in sorted(camps):
            rows = constraints.get(cid, [])
            owner = _field(rows, "owner")[0]
            limits = {c: _field(rows, c)[0] for c in ("approved_max_cpa", "minimum_roas", "approved_max_cpc")}
            grd.observe(f"Campaign {cid}: proposal guardrails", campaign_id=cid, owner=owner, **limits)
            if not owner or not any(limits.values()):
                grd.partial(f"campaign {cid}: owner or approved economic limit missing; proposals stay requests")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs evidence_ref; bids capped by approved max CPC; replacements from applicable list."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_config_failure" and not proposal.get("evidence_ref"):
        return ["material_config_failure needs proposal.evidence_ref pointing at supplied diagnostics"]
    if item.condition_key == "first_page_bid_relevance" and proposal.get("proposed_bid") is not None:
        pb, cap, cur = V.num(proposal.get("proposed_bid")), item.evidence.get("approved_max_cpc"), item.evidence.get("effective_bid")
        if pb is None or cap is None or pb > cap or pb <= cur:
            return [f"proposed_bid must be > current {cur} and <= approved_max_cpc {cap}"]
    if item.condition_key == "legacy_migration_plan" and outcome == "supported_replacement":
        problems = []
        rep = _s(proposal.get("replacement")).upper()
        allowed = [a.upper() for a in item.evidence.get("applicable_strategies") or []]
        if rep not in allowed:
            problems.append(f"replacement {rep or '(none)'} not in applicable_strategies {allowed}")
        if not proposal.get("rollback"):
            problems.append("proposal.rollback criteria required")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
