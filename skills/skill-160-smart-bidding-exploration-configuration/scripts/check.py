"""check.py — skill-160 deterministic Smart Bidding Exploration (tROAS tolerance) configuration review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-160-smart-bidding-exploration-configuration/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Scope = Search + target ROAS: campaigns.bidding_strategy_type TARGET_ROAS, or MAXIMIZE_CONVERSION_VALUE
         with a positive target_roas, directly or via a portfolio (campaigns.bidding_strategy_id|strategy_id or
         bidding_strategies.campaign_ids). Unknown channel/strategy → scope unknown (partial), never excluded.
         Settings come ONLY from custom/exploration_config (latest snapshot_at per strategy_id/campaign_id);
         empty cells are unknown, never disabled. Tolerance is the numeric configured_roas_tolerance_percent
         (percent units); outside documented 5–30% → Info unsupported, never re-labelled low/balanced/high.
         Planning effective target = target_roas*(1-tol/100), APPROXIMATE, never realized ROAS. ROAS cells are
         ratios; a trailing '%' is divided by 100. Warning only when planning or reported effective target
         < minimum_acceptable_roas from an APPROVED exploration_risk row valid at ctx.as_of; distinct floors → partial.
         Critical only via review 'material_failure_evidenced' with proposal.evidence_ref (verify).
         Experiment arms are evaluated only when every row has separately_reported_traffic_label, assignment is
         controlled (_CONTROLLED), goals match, ctx.mature True and both arms pass min_conversions.
         Tolerance-test proposals must keep target*(1-tol/100) >= approved floor and tol within 5–30 (verify).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-160-smart-bidding-exploration-configuration"
VERSION = "1.0.0"

CFG = "custom/exploration_config"
RISK = "external/exploration_risk"
EXP = "custom/exploration_experiment_daily"
TOL_MIN, TOL_MAX = 5.0, 30.0  # current Google guidance range (SKILL.md step 2); verify UI before proposals
_TRUE = {"true", "yes", "y", "1", "enabled", "on", "active", "eligible", "available", "limited", "budget_limited"}
_FALSE = {"false", "no", "n", "0", "disabled", "off", "inactive", "ineligible", "not_eligible", "unavailable",
          "not_available", "not_limited", "not limited", "unlimited"}
_CONTROLLED = {"randomized", "randomised", "random_split", "cookie_based", "search_based", "ads_experiment"}
_FAIL = "material_failure_evidenced"
_PROPOSAL_FIELDS = ("assignment", "primary_value_metric", "sample_plan", "stop_criteria", "owner")
_SEPS = (";", "|", ",")


def _id(v) -> str:
    return "" if v is None else str(v).strip()


def _flag(v) -> bool | None:
    s = V.norm_text(v)
    return True if s in _TRUE else False if s in _FALSE else None


def _pct(v) -> float | None:
    s = _id(v).rstrip("%").strip()
    return V.num(s)


def _roas(v) -> float | None:
    s = _id(v)
    if s.endswith("%"):
        f = V.num(s[:-1].strip())
        return f / 100 if f is not None else None
    f = V.num(s)
    return f if f is not None and f > 0 else None


def _latest(rows: list[dict]) -> tuple[dict, list]:
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((_id(r.get("strategy_id")), _id(r.get("campaign_id"))), []).append(r)
    out, conflicts = {}, []
    for key in sorted(groups):
        rs = groups[key]
        best = max(V.parse_date(r.get("snapshot_at")) or date.min for r in rs)
        top = [r for r in rs if (V.parse_date(r.get("snapshot_at")) or date.min) == best]
        if any(r != top[0] for r in top[1:]):
            conflicts.append(key)
            continue
        out[key] = top[0]
    return out, conflicts


def _entity(key: tuple) -> dict:
    return {k: v for k, v in (("strategy_id", key[0]), ("campaign_id", key[1])) if v}


class Scope:
    """Search + tROAS resolution for campaigns and portfolio config rows."""

    def __init__(self, ctx):
        self.camps = {_id(r.get("id")): r for r in ctx.rows("campaigns")
                      if str(r.get("status") or "").upper() != "REMOVED"}
        self.strats = {_id(r.get("id")): r for r in ctx.rows("bidding_strategies")}

    def _strategy_troas(self, sid: str) -> bool | None:
        s = self.strats.get(sid)
        if s is None:
            return None
        t = str(s.get("type") or "").upper()
        if not t:
            return None
        return t == "TARGET_ROAS" or (t == "MAXIMIZE_CONVERSION_VALUE" and _roas(s.get("target_roas")) is not None)

    def link(self, cid: str) -> str:
        c = self.camps.get(cid) or {}
        sid = _id(c.get("bidding_strategy_id") or c.get("strategy_id"))
        if not sid:
            sid = next((s for s in sorted(self.strats)
                        if cid in V.split_list(self.strats[s].get("campaign_ids"), _SEPS)), "")
        return sid

    def campaign(self, cid: str) -> bool | None:
        c = self.camps.get(cid)
        if c is None:
            return None
        ch = str(c.get("channel_type") or "").upper()
        if ch and ch != "SEARCH":
            return False
        t = str(c.get("bidding_strategy_type") or "").upper()
        troas = True if t == "TARGET_ROAS" or (t == "MAXIMIZE_CONVERSION_VALUE" and _roas(c.get("target_roas"))) else None
        if troas is None:
            sid = self.link(cid)
            troas = self._strategy_troas(sid) if sid else (False if t else None)
        if troas is False:
            return False
        return True if (ch == "SEARCH" and troas) else None

    def members(self, sid: str, row: dict | None) -> list[str]:
        m = set(V.split_list((row or {}).get("portfolio_members"), _SEPS))
        m |= set(V.split_list((self.strats.get(sid) or {}).get("campaign_ids"), _SEPS))
        m |= {c for c, r in self.camps.items() if _id(r.get("bidding_strategy_id") or r.get("strategy_id")) == sid}
        return sorted(x.strip() for x in m if x.strip())

    def row(self, key: tuple, row: dict) -> bool | None:
        sid, cid = key
        if cid:
            return self.campaign(cid)
        if not sid:
            return None
        mem = self.members(sid, row)
        states = [self.campaign(c) for c in mem]
        if not mem:
            return self._strategy_troas(sid)
        return False if False in states else True if all(s is True for s in states) else None

    def applicable(self) -> list[str]:
        return sorted(c for c in self.camps if self.campaign(c) is True)


def _in_scope(ctx, check, conf: dict, scope: Scope) -> list[tuple]:
    out = []
    for key, row in sorted(conf.items()):
        s = scope.row(key, row)
        if s is None:
            check.partial(f"config {key[0] or '-'}/{key[1] or '-'}: Search/tROAS scope unknown")
        elif s:
            out.append((key, row))
    return out


def _covers(rng, as_of) -> bool | None:
    s = _id(rng)
    if not s or as_of is None:
        return None
    for sep in ("..", " to ", "/"):
        if sep in s:
            a, b = (x.strip() for x in s.split(sep, 1))
            da, db = V.parse_date(a), V.parse_date(b)
            if (a and da is None) or (b and db is None):
                return None
            return (da is None or da <= as_of) and (db is None or as_of <= db)
    return None


def _floor(ctx, risk: list[dict], key: tuple) -> tuple[float | None, list[dict], str]:
    """Approved floor valid at as_of: exact (strategy, campaign) → campaign-only → strategy-only rows."""
    sid, cid = key
    approved = [r for r in risk if V.norm_text(r.get("approval_status")) == "approved"]
    tiers = ([r for r in approved if _id(r.get("strategy_id")) == sid and _id(r.get("campaign_id")) == cid],
             [r for r in approved if cid and _id(r.get("campaign_id")) == cid and not _id(r.get("strategy_id"))],
             [r for r in approved if sid and _id(r.get("strategy_id")) == sid and not _id(r.get("campaign_id"))])
    for rows in tiers:
        if not rows:
            continue
        dated = [r for r in rows if _covers(r.get("effective_range"), ctx.as_of) is True]
        chosen = dated or [r for r in rows if _covers(r.get("effective_range"), ctx.as_of) is None]
        floors = sorted({f for f in (_roas(r.get("minimum_acceptable_roas")) for r in chosen) if f is not None})
        if len(floors) == 1:
            note = "" if dated else "effective_range unknown/unparsed"
            return floors[0], [r for r in chosen if _roas(r.get("minimum_acceptable_roas")) == floors[0]], note
        if len(floors) > 1:
            return None, chosen, f"distinct approved floors {floors}"
        return None, chosen, "approved risk row without numeric minimum_acceptable_roas valid at as_of"
    return None, [], "no approved exploration_risk row"


def run(ctx) -> None:
    """Run tROAS scope, exploration tolerance, effective-target, budget/portfolio, experiment and proposal checks.

    Rules:   Settings only from custom/exploration_config latest snapshot; empty/conflicting cells are unknown, never
             disabled; tolerance outside 5–30% → Info unsupported. Warning only when the effective target <
             minimum_acceptable_roas of an APPROVED exploration_risk row valid at as_of; unresolved floor → partial, no
             proposal. Critical only via review with proposal.evidence_ref; experiment arms need controlled assignment,
             ctx.mature and min_conversions on both arms.
    """
    scope = Scope(ctx)
    cfg_t = ctx.table(CFG)
    conf, conflicts = _latest(cfg_t.rows) if cfg_t and not cfg_t.missing(["strategy_id", "campaign_id"]) else ({}, [])

    # -- step 1: applicability, availability and targeting eligibility ------------------------
    app = ctx.check("applicability_eligibility", "Search tROAS scope, availability and targeting eligibility",
                    {"campaigns": ["id", "channel_type", "bidding_strategy_type"],
                     CFG: ["strategy_id", "campaign_id", "snapshot_at", "availability", "enabled", "targeting_eligibility"]})
    if app.runnable:
        for key in conflicts:
            app.partial(f"{CFG}: differing rows at latest snapshot for {key}; state unknown")
        applicable = scope.applicable()
        unknown_scope = sorted(c for c in scope.camps if scope.campaign(c) is None)
        if unknown_scope:
            app.partial(f"Search/tROAS scope unknown for campaigns {unknown_scope}")
        out_of_scope = sorted(f"{k[0] or '-'}/{k[1] or '-'}" for k, r in conf.items() if scope.row(k, r) is False)
        if out_of_scope:
            app.observe("Config rows outside Search tROAS scope (feature not applicable)", rows=out_of_scope)
        if not applicable and not unknown_scope:
            app.not_applicable("no Search campaign/portfolio uses target ROAS")
        for cid in applicable:
            sid = scope.link(cid)
            key = (sid, cid) if (sid, cid) in conf else ("", cid) if ("", cid) in conf else (sid, "") if (sid, "") in conf else None
            if key is None:
                app.finding("exploration_settings_unverified", "Info", {"campaign_id": cid},
                            f"Search tROAS campaign {cid} has no exploration config row: availability and settings unknown",
                            evidence={"strategy_id": sid or None},
                            recommendation="Export the current bidding exploration settings (including disabled).",
                            uncertainty="Unknown is not disabled.")
                continue
            row = conf[key]
            avail, elig, enabled = _flag(row.get("availability")), _flag(row.get("targeting_eligibility")), _flag(row.get("enabled"))
            ev = {"availability": row.get("availability"), "targeting_eligibility": row.get("targeting_eligibility"),
                  "enabled": row.get("enabled"), "snapshot_at": row.get("snapshot_at"), "source_screen": row.get("source_screen"),
                  "config_scope": _entity(key)}
            app.observe(f"Campaign {cid} exploration availability/eligibility", campaign_id=cid, availability=avail,
                        targeting_eligibility=elig, enabled=enabled, config_scope=_entity(key))
            unknown = [n for n, v in (("availability", avail), ("targeting_eligibility", elig)) if v is None]
            if unknown:
                app.finding("exploration_settings_unverified", "Info", {"campaign_id": cid},
                            f"Campaign {cid}: exploration {', '.join(unknown)} unknown",
                            evidence={**ev, "unknown_fields": unknown},
                            recommendation="Verify availability and broad-targeting eligibility in the current UI.",
                            uncertainty="No forced broad-match adoption or conversion-count rule is implied.")
            elif enabled is True and (avail is False or elig is False):
                app.finding("unsupported_configuration", "Info", {"campaign_id": cid},
                            f"Campaign {cid}: exploration reported enabled while availability/eligibility is false",
                            evidence=ev, recommendation="Confirm the live state; the export may be inconsistent.",
                            uncertainty="Snapshot may lag the UI.")

    # -- step 2: numeric tolerance ---------------------------------------------------------------
    tol = ctx.check("tolerance_record", "Configured numeric ROAS tolerance",
                    {"campaigns": ["id", "channel_type", "bidding_strategy_type"],
                     CFG: ["strategy_id", "campaign_id", "enabled", "configured_roas_tolerance_percent"]})
    if tol.runnable:
        for key, row in _in_scope(ctx, tol, conf, scope):
            ent = _entity(key)
            enabled, t = _flag(row.get("enabled")), _pct(row.get("configured_roas_tolerance_percent"))
            ev = {"enabled": row.get("enabled"), "configured_roas_tolerance_percent": row.get("configured_roas_tolerance_percent"),
                  "documented_range_percent": [TOL_MIN, TOL_MAX], "current_help_url": row.get("current_help_url"),
                  "source_screen": row.get("source_screen"), "snapshot_at": row.get("snapshot_at")}
            tol.observe(f"Tolerance {ent}", **ent, enabled=enabled, tolerance_percent=t)
            if enabled is False:
                tol.finding("exploration_disabled", "Info", ent, f"Exploration disabled for {ent}", evidence=ev,
                            recommendation="No change is valid; consider only an optional, approved tolerance test.",
                            uncertainty="Disabled exploration is not a defect.")
            elif enabled is None:
                tol.finding("tolerance_unverified", "Info", ent, f"Exploration enabled state unknown for {ent}",
                            evidence=ev, recommendation="Re-export the setting; unknown is not disabled.",
                            uncertainty="Effective-target arithmetic cannot run.")
            elif t is None:
                tol.finding("tolerance_unverified", "Info", ent, f"Exploration enabled for {ent} but tolerance unknown",
                            evidence=ev, recommendation="Record the numeric tolerance from the UI.",
                            uncertainty="No intensity label is substituted.")
            elif not TOL_MIN <= t <= TOL_MAX:
                tol.finding("tolerance_outside_documented_range", "Info", ent,
                            f"Tolerance {t:g}% for {ent} is outside the documented {TOL_MIN:g}-{TOL_MAX:g}% range",
                            evidence=ev, recommendation="Verify the current UI range and the export unit before any proposal.",
                            uncertainty="Guidance range may change; the value may be exported in another unit.")

    # -- step 3: planning effective target vs approved floor ------------------------------------
    eff = ctx.check("effective_target_vs_floor", "Planning effective target versus approved ROAS floor",
                    {"campaigns": ["id", "channel_type", "bidding_strategy_type"],
                     CFG: ["strategy_id", "campaign_id", "enabled", "target_roas", "configured_roas_tolerance_percent"],
                     RISK: ["strategy_id", "campaign_id", "effective_range", "minimum_acceptable_roas", "approval_status"]})
    if eff.runnable:
        risk = sorted(ctx.rows(RISK), key=lambda r: (_id(r.get("strategy_id")), _id(r.get("campaign_id")),
                                                     _id(r.get("effective_range"))))
        for key, row in _in_scope(ctx, eff, conf, scope):
            ent = _entity(key)
            if _flag(row.get("enabled")) is not True:
                continue
            target, t = _roas(row.get("target_roas")), _pct(row.get("configured_roas_tolerance_percent"))
            if target is None or t is None:
                eff.partial(f"{ent}: target_roas or tolerance unknown; arithmetic not possible")
                continue
            planning = target * (1 - t / 100)
            reported = _roas(row.get("effective_target_if_reported"))
            floor, rows, note = _floor(ctx, risk, key)
            calc = {"target_roas": target, "tolerance_percent": t, "planning_effective_target": planning,
                    "formula": "target_roas*(1-tolerance/100) (approximate, not realized ROAS)",
                    "reported_effective_target": reported}
            if floor is None:
                eff.partial(f"{ent}: risk floor unresolved ({note})")
                eff.observe(f"Planning effective target {ent}", **ent, **calc)
                continue
            ev = {**calc, "minimum_acceptable_roas": floor, "floor_note": note, "as_of": ctx.as_of,
                  "risk_rows": [{k: r.get(k) for k in ("strategy_id", "campaign_id", "effective_range", "approved_budget_cap",
                                                       "maximum_drawdown", "value_quality_evidence_ref", "owner")} for r in rows]}
            breach = [n for n, v in (("planning", planning), ("reported", reported)) if v is not None and v < floor]
            if not breach:
                eff.observe(f"Effective target {ent} at or above approved floor", **ent, **calc, floor=floor)
                continue
            vq = any(r.get("value_quality_evidence_ref") for r in rows)
            eff.finding("effective_target_below_floor", "Warning", ent,
                        f"{ent}: {' and '.join(breach)} effective target "
                        f"({planning:.3g} planning{f', {reported:.3g} reported' if reported is not None else ''}) "
                        f"is below the approved minimum ROAS {floor:g}",
                        evidence=ev, calculation=calc,
                        recommendation="Request a lower tolerance (max "
                                       f"{max(0.0, 100 * (1 - floor / target)):.1f}% keeps the planning target at the floor) "
                                       "or no exploration; owner approval required.",
                        uncertainty="Planning target is approximate and not realized ROAS"
                                    + ("" if vq else "; value quality evidence missing") + ".")
            eff.review("effective_target_below_floor", ent,
                       f"Is there evidence of a MATERIAL live spending/safety failure for {ent} against the approved "
                       "guardrail (e.g. realized drawdown beyond maximum_drawdown or spend above approved_budget_cap)?",
                       evidence=ev,
                       outcomes={_FAIL: {"severity": "Critical", "recommendation":
                                         "Escalate to the guardrail owner with the cited evidence."},
                                 "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                       guidance=f"'{_FAIL}' needs proposal.evidence_ref to supplied realized-outcome evidence.")

    # -- step 4: budget limitation and portfolio coverage ----------------------------------------
    bud = ctx.check("budget_and_portfolio", "Budget-limited exploration and portfolio member coverage",
                    {"campaigns": ["id", "channel_type", "bidding_strategy_type"],
                     CFG: ["strategy_id", "campaign_id", "enabled", "budget_limited", "portfolio_members"]})
    if bud.runnable:
        risk_t = ctx.table(RISK)
        if risk_t is None:
            bud.partial("portfolio shared risk review not possible", [f"{RISK} (file)"])
        approved = [r for r in (risk_t.rows if risk_t else []) if V.norm_text(r.get("approval_status")) == "approved"]
        for key, row in _in_scope(ctx, bud, conf, scope):
            ent = _entity(key)
            enabled, limited = _flag(row.get("enabled")), _flag(row.get("budget_limited"))
            if limited is True and enabled is True:
                bud.finding("exploration_inactive_budget_limited", "Info", ent,
                            f"{ent} is budget-limited: guidance says the exploration mechanism is disabled",
                            evidence={"budget_limited": row.get("budget_limited"), "enabled": row.get("enabled")},
                            recommendation="Do not expect exploration while budget-limited; any budget change needs approval.",
                            uncertainty="Budget status is a snapshot.")
            elif limited is None and enabled is True:
                bud.partial(f"{ent}: budget_limited unknown; exploration activity undetermined")
            sid = key[0]
            if not sid or (key[1] and not row.get("portfolio_members")):
                continue
            listed = sorted(set(V.split_list(row.get("portfolio_members"), _SEPS)))
            members = scope.members(sid, row)
            no_row = [c for c in members if c not in scope.camps]
            no_risk = [c for c in members if risk_t is not None and not any(
                (_id(r.get("strategy_id")) == sid and not _id(r.get("campaign_id"))) or _id(r.get("campaign_id")) == c
                for r in approved)]
            bud.observe(f"Portfolio {sid} members", strategy_id=sid, members=members, listed_in_config=listed)
            gaps = {k: v for k, v in (("not_listed_in_config", sorted(set(members) - set(listed))),
                                      ("missing_campaign_rows", no_row), ("members_without_approved_risk", no_risk)) if v}
            if gaps:
                bud.finding("portfolio_member_coverage_gap", "Info", {"strategy_id": sid},
                            f"Portfolio {sid}: member coverage incomplete ({', '.join(sorted(gaps))})",
                            evidence={"members": members, **gaps},
                            recommendation="Supply every member's settings and a shared portfolio risk review.",
                            uncertainty="Portfolio exploration affects all members; partial coverage is not a pass.")

    # -- step 5: experiment arms -------------------------------------------------------------------
    _experiments(ctx)

    # -- step 6: optional tolerance test or no change --------------------------------------------
    prop = ctx.check("experiment_proposal", "Optional tolerance test or justified no change",
                     {"campaigns": ["id", "channel_type", "bidding_strategy_type"],
                      CFG: ["strategy_id", "campaign_id", "availability", "target_roas"],
                      RISK: ["strategy_id", "campaign_id", "effective_range", "minimum_acceptable_roas", "approval_status"]})
    if prop.runnable:
        risk = sorted(ctx.rows(RISK), key=lambda r: (_id(r.get("strategy_id")), _id(r.get("campaign_id")),
                                                     _id(r.get("effective_range"))))
        n = 0
        for key, row in _in_scope(ctx, prop, conf, scope):
            ent = _entity(key)
            target = _roas(row.get("target_roas"))
            if _flag(row.get("availability")) is not True or target is None:
                continue
            floor, rows, note = _floor(ctx, risk, key)
            if floor is None:
                prop.partial(f"{ent}: no proposal without an approved floor ({note})")
                continue
            n += 1
            prop.review("tolerance_test_or_no_change", ent,
                        f"Should {ent} run an optional, approved ROAS-tolerance test, or keep the current setting?",
                        evidence={"target_roas": target, "minimum_acceptable_roas": floor,
                                  "max_tolerance_keeping_floor_percent": min(TOL_MAX, max(0.0, 100 * (1 - floor / target))),
                                  "current_tolerance_percent": _pct(row.get("configured_roas_tolerance_percent")),
                                  "enabled": row.get("enabled"), "budget_limited": row.get("budget_limited"),
                                  "owner": [r.get("owner") for r in rows],
                                  "maturity": {"mature": ctx.mature, "note": ctx.maturity_note}},
                        outcomes={"propose_tolerance_test": {"severity": None, "recommendation":
                                                             "Request-only test within the approved floor; no uplift claim."},
                                  "no_change": {"severity": None, "recommendation": "Keep the current setting; document why."}},
                        guidance="propose_tolerance_test needs proposal {tolerance_percent, "
                                 + ", ".join(_PROPOSAL_FIELDS) + "}; target*(1-tol/100) must stay >= the floor.")
        prop.observe("Scopes offered a tolerance test/no-change decision", count=n)


def _experiments(ctx) -> None:
    exp = ctx.check("experiment_evaluation", "Randomized exploration experiment arms with separate outcomes",
                    {EXP: ["experiment_id", "arm_id", "campaign_id", "date", "assignment_method", "cost", "conversions",
                           "conversion_value", "goal_id", "separately_reported_traffic_label"]})
    if not exp.runnable:
        return
    if ctx.mature is not True:
        exp.partial(f"arm comparison disabled: maturity={ctx.mature} ({ctx.maturity_note}); descriptive totals only")
    gate = ctx.params.get("min_conversions")
    by_exp: dict[str, list] = {}
    excluded = 0
    for r in ctx.rows(EXP):
        d = V.parse_date(r.get("date"))
        if d is None or ctx.period_end is None or d > ctx.period_end:
            excluded += 1
            continue
        by_exp.setdefault(_id(r.get("experiment_id")), []).append(r)
    if excluded:
        exp.partial(f"{excluded} experiment rows with unknown date or after period end excluded")
    for eid in sorted(by_exp):
        rows = by_exp[eid]
        arms: dict[str, dict] = {}
        labels: dict[str, dict] = {}
        for r in rows:
            a = arms.setdefault(_id(r.get("arm_id")), {"cost": 0.0, "conversions": 0.0, "conversion_value": 0.0,
                                                       "unknown": set(), "goals": set(), "changed": set()})
            for k in ("cost", "conversions", "conversion_value"):
                v = ctx.money(r.get(k)) if k == "cost" else V.num(r.get(k))
                if v is None:
                    a["unknown"].add(k)
                else:
                    a[k] += v
            a["goals"].add(_id(r.get("goal_id")))
            if r.get("changed_setting"):
                a["changed"].add(_id(r.get("changed_setting")))
            lab = labels.setdefault(_id(r.get("arm_id")), {}).setdefault(_id(r.get("separately_reported_traffic_label")),
                                                                       [0.0, 0.0])
            lab[0] += ctx.money(r.get("cost")) or 0
            lab[1] += V.num(r.get("conversion_value")) or 0
        totals = {a: {k: (None if k in v["unknown"] else v[k]) for k in ("cost", "conversions", "conversion_value")}
                  for a, v in sorted(arms.items())}
        entity = {"experiment_id": eid}
        exp.observe(f"Experiment {eid} arm totals (descriptive)", experiment_id=eid, arms=totals)
        if any(not r.get("separately_reported_traffic_label") for r in rows):
            exp.finding("separate_outcomes_missing", "Info", entity,
                        f"Experiment {eid}: exploration/core traffic labels are not reported on every row",
                        evidence={"arms": totals, "rows_without_label": sum(1 for r in rows if not r.get("separately_reported_traffic_label"))},
                        recommendation="Do not claim an exploration traffic split or separate exploration ROI.",
                        uncertainty="Aggregate metrics cannot isolate exploration outcomes.")
            continue
        methods = sorted({V.norm_text(r.get("assignment_method")) for r in rows})
        goal_sets = {tuple(sorted(v["goals"])) for v in arms.values()}
        reasons = ([] if len(arms) >= 2 else ["fewer than two arms"]) + \
                  ([] if methods and all(m in _CONTROLLED for m in methods) else [f"assignment {methods} not controlled"]) + \
                  ([] if len(goal_sets) == 1 and all(all(g) for g in goal_sets) else ["arms use different or unknown goals"])
        if reasons:
            exp.finding("experiment_not_causal", "Info", entity,
                        f"Experiment {eid} cannot support a causal exploration claim: {'; '.join(reasons)}",
                        evidence={"arms": totals, "assignment_methods": methods},
                        recommendation="Treat results as descriptive; new audiences are not proven incremental.",
                        uncertainty="Allocation bias and concurrent changes are uncontrolled.")
            continue
        if ctx.mature is not True:
            continue
        conv = {a: t["conversions"] for a, t in totals.items()}
        if gate.value is None or any(c is None or c < gate.value for c in conv.values()):
            exp.finding("experiment_sparse", "Info", entity,
                        f"Experiment {eid}: not every arm reaches min_conversions {gate.value}",
                        evidence={"conversions": conv, "min_conversions": gate.value, "source": gate.source},
                        recommendation="Extend the test or keep no change; do not compare ROAS.",
                        uncertainty="Count gates are not significance tests.")
            continue
        roas = {a: V.ratio(t["conversion_value"], t["cost"]) for a, t in totals.items()}
        control = [a for a in sorted(arms) if not arms[a]["changed"]]
        rel = {}
        if len(control) == 1 and roas[control[0]]:
            c = control[0]
            rel = {a: V.ratio(roas[a] - roas[c], roas[c]) for a in roas if a != c and roas[a] is not None}
        exp.observe(f"Experiment {eid}: gated arm ROAS comparison", experiment_id=eid, roas=roas,
                    relative_to_control=rel, control_arm=control[0] if len(control) == 1 else None,
                    min_conversions=gate.value, label_breakdown={a: {lab: {"cost": v[0], "conversion_value": v[1]}
                                                                     for lab, v in sorted(ls.items())}
                                                                 for a, ls in sorted(labels.items())})


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref; tolerance proposals stay within 5–30% and above the floor."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == _FAIL and not str(proposal.get("evidence_ref") or "").strip():
        return ["material failure needs proposal.evidence_ref pointing at supplied realized-outcome evidence"]
    if outcome != "propose_tolerance_test":
        return []
    problems = []
    t = _pct(proposal.get("tolerance_percent"))
    target, floor = item.evidence.get("target_roas"), item.evidence.get("minimum_acceptable_roas")
    if t is None or not TOL_MIN <= t <= TOL_MAX:
        problems.append(f"proposal.tolerance_percent must be numeric within {TOL_MIN:g}-{TOL_MAX:g}")
    elif target is None or floor is None or target * (1 - t / 100) < floor:
        problems.append(f"planning effective target {target}*(1-{t:g}/100) falls below approved floor {floor}")
    missing = [f for f in _PROPOSAL_FIELDS if not str(proposal.get(f) or "").strip()]
    if missing:
        problems.append(f"proposal missing {missing}")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
