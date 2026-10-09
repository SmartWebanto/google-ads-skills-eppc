"""check.py — skill-050 deterministic shared-budget regimes, HHI concentration and starvation evidence gates.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-050-shared-budget-appropriateness-check/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Pools are budgets with an explicit shared flag, keyed by budget ID; membership comes from
         custom/budget_history regimes clipped to the account period — never from campaign names.
         n = eligible members of the regime INCLUDING zero-spend members; any member without daily rows,
         unknown cost/eligibility, duplicate rows or non-member spend makes that regime's concentration
         unavailable (observation + partial), never a finding.
         HHI = sum(p_i^2) only for S>0; normalized = (HHI-1/n)/(1-1/n) only for n>1. normalized > 0.5 is an
         Info review cue; equal sharing (normalized 0) is never a finding. Low/high share is never "starved".
         Warning only via review when profile.budget_constraints documents a commitment for the pool or a member
         AND dated budget limitation exists; verify demands proposal.evidence_ref and a reviewed campaign_id.
         Efficiency comparisons need ctx.mature True, lag_mature rows and min_conversions on BOTH members,
         within one goal_cohort; they are descriptive observations, not severities.
         Separation gains come only from custom/shared_budget_response scenarios (verify checks scenario_id).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-050-shared-budget-appropriateness-check"
VERSION = "1.0.0"

_SEPS = (" | ", ";", "|", ",")
_ELIGIBLE = {"ELIGIBLE", "SERVING", "ENABLED", "LIMITED", "LIMITED_BY_BUDGET"}
_DAILY = "custom/shared_budget_daily"
_HIST = "custom/budget_history"
_RESP = "custom/shared_budget_response"
_LIMIT_NONE = {"", "NONE", "NO", "NOT_LIMITED", "UNLIMITED"}


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _ids(v) -> list[str]:
    return sorted({x for x in V.split_list(v, _SEPS) if x})


def _col(ctx, key: str, *names: str) -> str:
    """First documented alternative column present in the table (first name when absent → reported missing)."""
    t = ctx.table(key)
    if t is None:
        return names[0]
    return next((n for n in names if n in t.columns), names[0])


def _pools(ctx, inv) -> dict[str, dict]:
    bid = _col(ctx, "budgets", "budget_id", "id")
    flag = _col(ctx, "budgets", "shared", "explicitly_shared", "shared_flag")
    by_campaign: dict[str, list[str]] = {}
    for c in ctx.rows("campaigns"):
        b = _s(c.get("budget_id"))
        if b:
            by_campaign.setdefault(b, []).append(_s(c.get("id")))
    pools = {}
    for b in sorted(ctx.rows("budgets"), key=lambda r: _s(r.get(bid))):
        key = _s(b.get(bid))
        shared = V.boolean(b.get(flag))
        if not key:
            inv.partial("budget row without budget ID ignored")
            continue
        if shared is None:
            inv.partial(f"budget {key}: shared flag unknown; pool status not assumed")
            continue
        if not shared:
            continue
        listed = _ids(b.get("campaign_ids"))
        linked = sorted(set(by_campaign.get(key, [])))
        statuses = {_s(c.get("id")): _s(c.get("status")) or None for c in ctx.rows("campaigns")
                    if _s(c.get("budget_id")) == key or _s(c.get("id")) in listed}
        pools[key] = {"amount": ctx.money(b.get("amount")), "listed": listed, "linked": linked, "statuses": statuses}
        if listed != linked:
            inv.partial(f"budget {key}: budgets.campaign_ids {listed} differ from campaigns.budget_id links {linked}")
        inv.observe(f"Shared pool {key}: {len(set(listed) | set(linked))} member campaigns", budget_id=key,
                    amount=pools[key]["amount"], budgets_campaign_ids=listed, campaigns_budget_links=linked,
                    member_statuses=statuses, currency=ctx.currency)
    return pools


def _regimes(ctx, reg, pools) -> dict[str, list[dict]]:
    """Membership/amount regimes per pool clipped to the account period; gaps reported, never filled."""
    out: dict[str, list[dict]] = {}
    start, end = ctx.period_start, ctx.period_end
    if start is None or end is None:
        reg.partial("account period unknown: regimes cannot be clipped")
        return out
    rows = ctx.rows(_HIST)
    for pid in sorted(pools):
        hist = []
        for r in rows:
            if _s(r.get("budget_id")) != pid:
                continue
            f, t = V.parse_date(r.get("effective_from")), V.parse_date(r.get("effective_to")) or end
            if f is None:
                reg.partial(f"budget {pid}: history row without effective_from ignored")
                continue
            if t < start or f > end:
                continue
            hist.append({"from": max(f, start), "to": min(t, end), "members": _ids(r.get("member_campaign_ids")),
                         "amount": ctx.money(r.get("amount")), "source_ref": r.get("source_ref")})
        hist.sort(key=lambda h: h["from"])
        cursor, gaps, overlaps = start, [], []
        for h in hist:
            if h["from"] > cursor:
                gaps.append(f"{cursor}..{h['from'] - timedelta(days=1)}")
            if h["from"] < cursor:
                overlaps.append(str(h["from"]))
            cursor = max(cursor, h["to"] + timedelta(days=1))
        if cursor <= end:
            gaps.append(f"{cursor}..{end}")
        if gaps:
            reg.partial(f"budget {pid}: no membership history for {', '.join(gaps)}; those dates unevaluated")
        if overlaps:
            reg.partial(f"budget {pid}: overlapping history rows from {', '.join(overlaps)}; regimes ambiguous")
            continue
        out[pid] = hist
        for h in hist:
            reg.observe(f"Pool {pid} regime {h['from']}..{h['to']}", budget_id=pid, members=h["members"],
                        amount=h["amount"], source_ref=h["source_ref"])
        current = sorted(set(pools[pid]["listed"]) | set(pools[pid]["linked"]))
        if hist and hist[-1]["to"] == end and hist[-1]["members"] != current:
            reg.partial(f"budget {pid}: last history membership {hist[-1]['members']} differs from snapshot {current}")
    return out


def _regime_rows(ctx, pid: str, h: dict) -> list[dict]:
    return [r for r in ctx.rows(_DAILY) if _s(r.get("budget_id")) == pid
            and (d := V.parse_date(r.get("date"))) is not None and h["from"] <= d <= h["to"]]


def _members(ctx, pid: str, h: dict) -> dict:
    """Per-member daily aggregation for one regime with explicit blockers."""
    rows = _regime_rows(ctx, pid, h)
    days = (h["to"] - h["from"]).days + 1
    blockers, seen = [], set()
    per = {m: {"rows": [], "dates": set()} for m in h["members"]}
    for r in rows:
        cid = _s(r.get("campaign_id"))
        key = (cid, _s(r.get("date"))[:10])
        if key in seen:
            blockers.append(f"duplicate daily row {cid} {key[1]}")
            continue
        seen.add(key)
        if cid not in per:
            if (ctx.money(r.get("cost")) or 0) != 0:
                blockers.append(f"campaign {cid} spent from pool on {key[1]} but is not a regime member")
            continue
        per[cid]["rows"].append(r)
        per[cid]["dates"].add(key[1])
    eligible, excluded, cost = [], [], {}
    for m in sorted(per):
        info = per[m]
        if not info["rows"]:
            blockers.append(f"member {m} has no daily rows (eligibility and zero spend unknown)")
            continue
        states = {_s(r.get("eligibility_status")).upper() for r in info["rows"]}
        if any(s in _ELIGIBLE for s in states):
            eligible.append(m)
        elif "" in states:
            blockers.append(f"member {m} eligibility unknown")
            continue
        else:
            excluded.append(m)
            continue
        costs = [ctx.money(r.get("cost")) for r in info["rows"]]
        if any(c is None for c in costs):
            blockers.append(f"member {m} has unknown cost on some days")
            continue
        cost[m] = sum(costs)
        if len(info["dates"]) < days:
            blockers.append(f"member {m} covers {len(info['dates'])} of {days} regime days")
    return {"rows": rows, "per": per, "eligible": eligible, "excluded": excluded, "cost": cost,
            "blockers": sorted(set(blockers)), "days": days}


def _limited(ctx, r) -> bool | None:
    lost = ctx.rate(r.get("budget_lost_IS"))
    reason = _s(r.get("budget_specific_reason")).upper()
    if lost is None and r.get("budget_specific_reason") is None:
        return None
    return (lost is not None and lost > 0) or reason not in _LIMIT_NONE


def run(ctx) -> None:
    """Run shared-pool inventory, regimes, HHI concentration, shares, compatibility, starvation, efficiency, response.

    Rules:   No budgets/campaigns inventory skips all checks; no explicitly shared pool marks them not applicable.
             Regime blockers make concentration/shares/starvation unavailable (partial), never a finding.
             normalized HHI > 0.5, role mismatch and budget-limited low-share pools → Info only; Warning only via
             ai_review commitment_conflict_corroborated with profile.budget_constraints. CPA/ROAS stay observations.
    """
    inv = ctx.check("pool_inventory", "Inventory shared budget pools by budget ID (step 1)",
                    {"budgets": [_col(ctx, "budgets", "budget_id", "id"), "amount", "campaign_ids",
                                 _col(ctx, "budgets", "shared", "explicitly_shared", "shared_flag")],
                     "campaigns": ["id", "budget_id", "status"]})
    later = (("membership_regimes", "Segment pools at membership/amount changes (step 1)"),
             ("concentration", "Spend shares, HHI, 1/n baseline and normalized concentration (steps 2-4)"),
             ("member_shares", "Spend/conversion/value shares per member (step 4)"),
             ("compatibility", "Member goal/role compatibility (step 5)"),
             ("starvation_evidence", "Pool saturation plus low-share eligible member (step 6)"),
             ("cohort_efficiency", "Matched mature CPA/ROAS within goal cohorts (step 7)"),
             ("separation_response", "Separation scenarios from a supplied response model (step 8)"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("pool inventory unavailable", inv.missing)
        return
    pools = _pools(ctx, inv)
    if not pools:
        inv.observe("No explicitly shared budget in the inventory", budgets=len(ctx.rows("budgets")))
        for cid, title in later:
            ctx.check(cid, title, applicable=False, na_reason="no explicitly shared budget pool")
        return

    reg = ctx.check("membership_regimes", later[0][1],
                    {_HIST: ["budget_id", "effective_from", "effective_to", "amount", "member_campaign_ids"]})
    regimes = _regimes(ctx, reg, pools) if reg.runnable else {}

    daily_cols = ["budget_id", "campaign_id", "date", "cost", "eligibility_status"]
    conc = ctx.check("concentration", later[1][1], {_HIST: ["budget_id", "member_campaign_ids"], _DAILY: daily_cols})
    agg: dict[tuple, dict] = {}
    if conc.runnable:
        for pid in sorted(regimes):
            for h in regimes[pid]:
                m = _members(ctx, pid, h)
                agg[(pid, h["from"])] = m
                ent = {"budget_id": pid, "regime": f"{h['from']}..{h['to']}"}
                n, total = len(m["eligible"]), sum(m["cost"].values()) if m["cost"] else None
                if m["blockers"]:
                    conc.partial(f"budget {pid} {ent['regime']}: concentration unavailable")
                    conc.observe(f"Pool {pid} {ent['regime']}: concentration unavailable", **ent,
                                 blockers=m["blockers"], excluded_ineligible=m["excluded"])
                    continue
                if n == 0 or not total:
                    conc.observe(f"Pool {pid} {ent['regime']}: S=0 or no eligible member; concentration unavailable",
                                 **ent, eligible_members=m["eligible"], spend_total=total)
                    continue
                shares = {k: V.ratio(v, total) for k, v in sorted(m["cost"].items())}
                hhi = sum(p * p for p in shares.values())
                base = 1 / n
                norm = (hhi - base) / (1 - base) if n > 1 else None
                calc = {"n_eligible": n, "spend_total": total, "spend_by_member": m["cost"], "shares": shares,
                        "hhi": hhi, "equal_share_baseline": base, "normalized_concentration": norm,
                        "excluded_ineligible": m["excluded"], "window_days": m["days"], "currency": ctx.currency}
                conc.observe(f"Pool {pid} {ent['regime']}: HHI {hhi:.4f}, baseline 1/n {base:.4f}, normalized "
                             + ("n/a (single member)" if norm is None else f"{norm:.4f}"), **ent, **calc)
                if norm is not None and norm > 0.5:
                    conc.finding("concentration_review_cue", "Info", ent,
                                 f"Pool {pid} spend is concentrated (normalized {norm:.2f} > 0.50) in {ent['regime']}",
                                 evidence=calc, calculation={"hhi": "sum(p_i^2)", "normalized": "(HHI-1/n)/(1-1/n)"},
                                 recommendation="Review whether the asymmetric allocation is intended by goals/constraints; "
                                                "no separation implied.",
                                 uncertainty="Concentration can reflect demand, eligibility or deliberate priority, not starvation.")

    sh = ctx.check("member_shares", later[2][1], {_DAILY: daily_cols + ["conversions", "value"]})
    if sh.runnable:
        for (pid, _f), m in sorted(agg.items()):
            if m["blockers"] or not m["eligible"]:
                sh.partial(f"budget {pid} regime from {_f}: shares unavailable (membership incomplete)")
                continue
            conv, val = {}, {}
            for mid in m["eligible"]:
                cs = [V.num(r.get("conversions")) for r in m["per"][mid]["rows"]]
                vs = [V.num(r.get("value")) for r in m["per"][mid]["rows"]]
                conv[mid] = None if any(c is None for c in cs) else sum(cs)
                val[mid] = None if any(v is None for v in vs) else sum(vs)
            tc = None if any(v is None for v in conv.values()) else sum(conv.values())
            tv = None if any(v is None for v in val.values()) else sum(val.values())
            total = sum(m["cost"].values())
            sh.observe(f"Pool {pid} regime from {_f}: member shares", budget_id=pid,
                       spend_share={k: V.ratio(v, total) for k, v in m["cost"].items()},
                       conversion_share={k: V.ratio(v, tc) for k, v in conv.items()},
                       value_share={k: V.ratio(v, tv) for k, v in val.items()},
                       conversions=conv, value=val, note="Shares are descriptive; low share is not starvation.")

    comp = ctx.check("compatibility", later[3][1], {"campaigns": ["id"]})
    if comp.runnable:
        objectives = ctx.profile.get("campaign_objectives") or {}
        obj = {str(k): v for k, v in objectives.items()} if isinstance(objectives, dict) else {}
        for pid in sorted(pools):
            members = sorted(set(pools[pid]["listed"]) | set(pools[pid]["linked"]))
            unknown = [m for m in members if not isinstance(obj.get(m), dict)]
            if unknown:
                comp.partial(f"budget {pid}: profile.campaign_objectives missing for {unknown}; compatibility unknown")
                continue
            roles = {m: obj[m].get("role") for m in members}
            goals = {m: sorted(map(str, obj[m].get("goal_ids") or [])) for m in members}
            ev = {"roles": roles, "goal_ids": goals, "budget_constraints": _constraint(ctx, pid, members)}
            if len({str(r) for r in roles.values()}) <= 1 and len({tuple(g) for g in goals.values()}) <= 1:
                comp.observe(f"Pool {pid}: members share role and goal set", budget_id=pid, **ev)
                continue
            ent = {"budget_id": pid, "members": members}
            prov = comp.finding("differing_member_roles", "Info", ent,
                                f"Pool {pid} pools members with different roles or goal sets",
                                evidence=ev, recommendation="Confirm the pooling is intended for these roles/goals.",
                                uncertainty="Different roles can be pooled deliberately; no separation implied.")
            comp.review("differing_member_roles", ent,
                        f"Is pooling members with roles {roles} / goals {goals} in budget {pid} intended by the owner?",
                        evidence=ev, provisional=prov,
                        outcomes={"intentional_pooling": {"severity": None, "recommendation": "Retain pooling; document intent."},
                                  "needs_owner_review": {"severity": "Info", "recommendation":
                                                         "Ask the owner to confirm roles and priorities for this pool."},
                                  "uncertain": {"severity": "Info", "recommendation": "Request the allocation brief."}},
                        guidance="Use only profile campaign_objectives and budget_constraints; different goals are not "
                                 "automatically a conflict.")

    st = ctx.check("starvation_evidence", later[4][1],
                   {_DAILY: daily_cols + ["budget_lost_IS", "budget_specific_reason"]})
    if st.runnable:
        for (pid, _f), m in sorted(agg.items()):
            if m["blockers"] or len(m["eligible"]) < 2:
                st.partial(f"budget {pid} regime from {_f}: membership incomplete or single member; no starvation claim")
                continue
            flags = [(_s(r.get("date"))[:10], _limited(ctx, r)) for mid in m["eligible"] for r in m["per"][mid]["rows"]]
            limited_days = sorted({d for d, f in flags if f})
            unknown_days = sorted({d for d, f in flags if f is None})
            total = sum(m["cost"].values())
            base = 1 / len(m["eligible"])
            low = sorted(k for k, v in m["cost"].items() if (V.ratio(v, total) or 0) < base)
            ent = {"budget_id": pid, "regime_from": str(_f)}
            ev = {"budget_limited_days": limited_days, "limitation_unknown_days": unknown_days,
                  "below_equal_share_members": low, "equal_share_baseline": base,
                  "spend_share": {k: V.ratio(v, total) for k, v in m["cost"].items()},
                  "budget_constraints": _constraint(ctx, pid, m["eligible"])}
            if unknown_days:
                st.partial(f"budget {pid}: limitation unknown on {len(unknown_days)} days")
            if not limited_days:
                st.observe(f"Pool {pid}: no dated budget limitation; starvation not evidenced", **ent, **ev)
                continue
            if not low:
                st.observe(f"Pool {pid}: budget-limited days but no below-equal-share member", **ent, **ev)
                continue
            prov = st.finding("budget_constrained_pool", "Info", ent,
                              f"Pool {pid} was budget-limited on {len(limited_days)} days with below-equal-share members {low}",
                              evidence=ev, recommendation="Check unmet demand and economics of the low-share members "
                                                          "before any separation proposal.",
                              uncertainty="Low spend share can reflect low demand or ineligibility, not starvation.")
            if not ev["budget_constraints"]:
                st.partial(f"budget {pid}: no profile.budget_constraints commitment; Warning path unavailable")
                continue
            st.review("allocation_commitment_conflict", ent,
                      f"Does independent evidence show unmet demand with acceptable economics for {low} in pool {pid}, "
                      "conflicting with the documented allocation commitment?",
                      evidence=ev, provisional=prov,
                      outcomes={"commitment_conflict_corroborated": {"severity": "Warning", "recommendation":
                                "Propose a bounded allocation test or separation under approved constraints."},
                                "no_conflict": {"severity": None, "recommendation": "Retain pooling."},
                                "uncertain": {"severity": "Info", "recommendation": "Request demand/eligibility evidence."}},
                      guidance="commitment_conflict_corroborated needs proposal {campaign_id (from "
                               "below_equal_share_members), evidence_ref (unmet-demand evidence)}.")

    eff = ctx.check("cohort_efficiency", later[5][1],
                    {_DAILY: daily_cols + ["conversions", "value", "goal_cohort", "lag_mature"]})
    if eff.runnable:
        if ctx.mature is not True:
            eff.partial(f"conversion maturity not established ({ctx.maturity_note}); descriptive totals only")
        min_conv = ctx.params.get("min_conversions")
        for (pid, _f), m in sorted(agg.items()):
            cohorts: dict[str, dict] = {}
            immature = 0
            for mid in m["eligible"]:
                for r in m["per"][mid]["rows"]:
                    if V.boolean(r.get("lag_mature")) is not True:
                        immature += 1
                        continue
                    g = _s(r.get("goal_cohort")) or "?"
                    a = cohorts.setdefault(g, {}).setdefault(mid, [0.0, 0.0, 0.0, 0])
                    c, cv, vv = ctx.money(r.get("cost")), V.num(r.get("conversions")), V.num(r.get("value"))
                    if c is None or cv is None:
                        a[3] += 1
                        continue
                    a[0] += c
                    a[1] += cv
                    a[2] += vv or 0
            if immature:
                eff.partial(f"budget {pid}: {immature} member-days not lag-mature excluded")
            for g, mem in sorted(cohorts.items()):
                if g == "?":
                    eff.partial(f"budget {pid}: rows without goal_cohort not compared")
                    continue
                qual = {k: v for k, v in mem.items() if v[1] >= (min_conv.value or float("inf"))}
                eff.observe(f"Pool {pid} cohort {g}: member CPA/ROAS", budget_id=pid, goal_cohort=g,
                            cpa={k: V.ratio(v[0], v[1]) for k, v in sorted(mem.items())},
                            roas={k: V.ratio(v[2], v[0]) for k, v in sorted(mem.items())},
                            conversions={k: v[1] for k, v in sorted(mem.items())},
                            min_conversions=min_conv.value, min_conversions_source=min_conv.source,
                            comparable_members=sorted(qual) if ctx.mature is True and len(qual) >= 2 else [],
                            note="Comparison only between members that each meet min_conversions in the same cohort.")

    resp = ctx.check("separation_response", later[6][1],
                     {_RESP: ["model_id", "budget_id", "scenario_id", "source_type", "modeled_cost",
                              "modeled_conversions", "modeled_value", "period_start", "period_end", "source_ref"]})
    if resp.runnable:
        by_pool: dict[str, list[dict]] = {}
        for r in ctx.rows(_RESP):
            pid = _s(r.get("budget_id"))
            if pid in pools:
                by_pool.setdefault(pid, []).append(r)
        for pid in sorted(pools):
            rows = sorted(by_pool.get(pid, []), key=lambda r: (_s(r.get("model_id")), _s(r.get("scenario_id"))))
            if not rows:
                resp.partial(f"budget {pid}: no response model; no projected split gains")
                continue
            scen = [{"model_id": r.get("model_id"), "scenario_id": _s(r.get("scenario_id")),
                     "source_type": r.get("source_type"), "modeled_cost": ctx.money(r.get("modeled_cost")),
                     "modeled_conversions": V.num(r.get("modeled_conversions")),
                     "modeled_value": V.num(r.get("modeled_value")),
                     "modeled_cpa": V.ratio(ctx.money(r.get("modeled_cost")), V.num(r.get("modeled_conversions"))),
                     "modeled_roas": V.ratio(V.num(r.get("modeled_value")), ctx.money(r.get("modeled_cost"))),
                     "period": [r.get("period_start"), r.get("period_end")],
                     "uncertainty": [r.get("uncertainty_low"), r.get("uncertainty_high")],
                     "assumptions": r.get("assumptions"), "source_ref": r.get("source_ref")} for r in rows]
            resp.observe(f"Pool {pid}: {len(scen)} modeled scenarios", budget_id=pid, scenarios=scen)
            resp.review("separation_scenario", {"budget_id": pid},
                        f"Does a supplied scenario for pool {pid} show a response advantage within approved constraints?",
                        evidence={"scenarios": scen, "budget_constraints": _constraint(ctx, pid, pools[pid]["listed"])},
                        outcomes={"propose_bounded_test": {"severity": "Info", "recommendation":
                                                           "Propose a bounded experiment for the cited scenario; keep pooling meanwhile."},
                                  "retain_pooling": {"severity": None, "recommendation": "Retain pooling."},
                                  "uncertain": {"severity": "Info", "recommendation": "Request model assumptions/uncertainty."}},
                        guidance="propose_bounded_test needs proposal.scenario_id from evidence; do not extrapolate "
                                 "current average CPA.")


def _constraint(ctx, pid: str, members) -> dict:
    """profile.budget_constraints entries for the pool or its members (raw, owner-documented)."""
    bc = ctx.profile.get("budget_constraints") or {}
    if not isinstance(bc, dict):
        return {}
    keys = [pid] + list(members)
    return {k: v for k, v in sorted(bc.items(), key=lambda kv: str(kv[0])) if str(k) in keys and v}


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning needs evidence_ref + reviewed low-share campaign_id; test proposals cite a supplied scenario."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if item.condition_key == "allocation_commitment_conflict" and outcome == "commitment_conflict_corroborated":
        problems = []
        if not _s(proposal.get("evidence_ref")):
            problems.append("proposal.evidence_ref (unmet-demand evidence) required")
        if _s(proposal.get("campaign_id")) not in item.evidence.get("below_equal_share_members", []):
            problems.append("proposal.campaign_id must be a below-equal-share member from the evidence")
        return problems
    if item.condition_key == "separation_scenario" and outcome == "propose_bounded_test":
        ids = {s.get("scenario_id") for s in item.evidence.get("scenarios", [])}
        if _s(proposal.get("scenario_id")) not in ids:
            return [f"proposal.scenario_id must be one of {sorted(ids)}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
