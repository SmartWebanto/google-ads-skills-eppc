"""check.py — skill-043 deterministic daily budget-to-CPA descriptors at the correct budget scope.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-043-daily-budget-to-cpa-ratio-check/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Ratios are descriptors only (observations): no minimum multiple, no Smart Bidding eligibility, no required
         budget, no predicted daily conversions. Unavailable ratios are Info findings naming the missing input.
         Daily amount: standalone → campaigns.daily_budget; shared → budgets.amount deduplicated by budget ID with
         full membership (budgets.campaign_ids or campaigns.budget_id); never the whole pool per member.
         A budgets.period other than DAILY (total/lifetime) is never labeled daily.
         Target CPA via ctx.params.target_cpa (campaign → portfolio → compatible profile); ROAS campaigns
         (TARGET_ROAS/MAXIMIZE_CONVERSION_VALUE or ROAS objective) have no CPA-ratio equivalent.
         Achieved CPA needs ctx.mature True and >= min_conversions; zero conversions → unavailable, never infinity.
         Pool sums only across members with identical declared goal_ids; pool target ratio only for one shared target.
         Zero-conversion spend >= spend_floor needs mature window AND ctx.tracking_for_campaign True → provisional
         Info + relevance review (Warning only via review).
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

SKILL = "skill-043-daily-budget-to-cpa-ratio-check"
VERSION = "1.0.0"

ROAS_STRATEGIES = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
METRIC_COLS = ["campaign_id", "cost", "conversions"]
SEPS = (";", "|", ",")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _roas_campaign(ctx, row) -> bool:
    if _s(row.get("bidding_strategy_type")).upper() in ROAS_STRATEGIES:
        return True
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == _s(row.get("id"))), None) if isinstance(objectives, dict) else None
    return isinstance(obj, dict) and obj.get("target_roas") is not None and not obj.get("target_cpa")


def _scopes(ctx, camps: dict) -> tuple[dict, list[str]]:
    """scope key -> {type, budget_id, members, amount, amount_source}; plus notes for unavailable scopes."""
    budgets = {_s(b.get("id")): b for b in ctx.rows("budgets") if _s(b.get("id"))}
    by_budget: dict[str, set] = {}
    for bid, b in budgets.items():
        by_budget.setdefault(bid, set()).update(V.split_list(b.get("campaign_ids"), SEPS))
    for cid, r in camps.items():
        if _s(r.get("budget_id")):
            by_budget.setdefault(_s(r.get("budget_id")), set()).add(cid)
    member_of = {m: bid for bid, ms in by_budget.items() for m in ms}
    scopes, notes = {}, []
    for cid in sorted(camps):
        r = camps[cid]
        bid = member_of.get(cid)
        b = budgets.get(bid or "")
        shared = V.boolean(r.get("shared_budget"))
        if shared is None and b is not None:
            shared = V.boolean(b.get("shared") if b.get("shared") is not None else b.get("shared_flag"))
        period = _s((b or {}).get("period") or (b or {}).get("budget_period")).upper()
        if period and period != "DAILY":
            notes.append((cid, f"budget {bid} period {period}: not a daily budget"))
            continue
        members = sorted(by_budget.get(bid, {cid})) if bid else [cid]
        if shared or len(members) > 1:
            if not bid:
                notes.append((cid, "shared budget without a budget ID/membership: pool ratio unavailable"))
                continue
            key = f"budget:{bid}"
            if key in scopes:
                continue
            amt = ctx.money(b.get("amount")) if b else None
            src = f"budgets.amount[{bid}]"
            if amt is None:
                amounts = {ctx.money(camps[m].get("daily_budget")) for m in members if m in camps}
                if len(amounts) == 1 and None not in amounts:
                    amt, src = amounts.pop(), f"campaigns.daily_budget (identical across pool {bid}, counted once)"
            if amt is None:
                notes.append((cid, f"shared budget {bid}: amount unknown"))
                continue
            scopes[key] = {"type": "shared", "budget_id": bid, "members": members, "amount": amt, "amount_source": src}
        else:
            amt = ctx.money(r.get("daily_budget"))
            src = f"campaigns.daily_budget[{cid}]"
            if amt is None and b is not None:
                amt, src = ctx.money(b.get("amount")), f"budgets.amount[{bid}]"
            if amt is None:
                notes.append((cid, "daily budget amount unknown"))
                continue
            scopes[f"campaign:{cid}"] = {"type": "standalone", "budget_id": bid, "members": [cid], "amount": amt,
                                         "amount_source": src}
    return scopes, notes


def run(ctx) -> None:
    """Run daily-budget / target-CPA / achieved-CPA ratio descriptors and zero-conversion spend screen.

    Rules:   Ratios are observations only (no minimum multiple, no required budget); unavailable ratio → Info naming the
             input. Shared budgets dedupe by budget ID; non-DAILY periods are never labeled daily; ROAS campaigns get no
             CPA ratio. Achieved CPA needs ctx.mature True and min_conversions. Zero-conversion spend >= spend_floor
             needs mature window and ctx.tracking_for_campaign True → provisional Info + review; Warning only via
             review.
    """
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}
    min_conv = ctx.params.get("min_conversions")
    metrics: dict[str, list] = {}
    for m in ctx.rows("campaign_metrics"):
        metrics.setdefault(_s(m.get("campaign_id")), []).append(m)

    def outcome(cid):
        rows = metrics.get(cid, [])
        if len(rows) != 1:
            return None, None
        return ctx.money(rows[0].get("cost")), V.num(rows[0].get("conversions"))

    # step 1 — scope
    sc = ctx.check("budget_scope", "Daily budget type, ID and shared/standalone scope (step 1)",
                   {"campaigns": ["id", "daily_budget"]})
    scopes, notes = ({}, [])
    if sc.runnable:
        if ctx.table("budgets") is None:
            sc.partial("budgets inventory missing: shared membership from campaigns only", ["budgets (file)"])
        scopes, notes = _scopes(ctx, camps)
        for key, s in sorted(scopes.items()):
            sc.observe(f"Scope {key}: {s['type']} daily amount {s['amount']:g} {ctx.currency}", scope=key, **s)
        for cid, why in notes:
            sc.finding("ratio_unavailable", "Info", {"campaign_id": cid, "ratio": "budget_scope"},
                       f"Campaign {cid}: {why}", evidence={"reason": why},
                       recommendation="Supply the budget ID, period and full shared membership.",
                       uncertainty="Budget scope unresolved; no ratio computed.")

    def unavailable(chk, cid, ratio, why, ev=None):
        chk.finding("ratio_unavailable", "Info", {"campaign_id": cid, "ratio": ratio}, f"Campaign {cid}: {ratio} unavailable — {why}",
                    evidence={"reason": why, **(ev or {})}, recommendation="Supply the missing input; do not size budgets from it.",
                    uncertainty="Unavailable is not zero and not a defect.")

    # step 2 — standalone ratios
    st = ctx.check("standalone_ratios", "Standalone target and achieved budget-to-CPA ratios (step 2)",
                   {"campaigns": ["id", "daily_budget"], "campaign_metrics": METRIC_COLS})
    if st.runnable:
        if ctx.mature is not True:
            st.partial(f"achieved ratios need mature outcomes: {ctx.maturity_note}")
        for key, s in sorted(scopes.items()):
            if s["type"] != "standalone":
                continue
            cid = s["members"][0]
            if _roas_campaign(ctx, camps[cid]):
                st.observe(f"Campaign {cid}: ROAS campaign — no CPA-ratio equivalent", campaign_id=cid)
                continue
            tcpa, tsrc = ctx.params.target_cpa(cid)
            cost, conv = outcome(cid)
            ach = V.ratio(cost, conv) if ctx.mature is True and conv is not None and min_conv.value is not None \
                and conv >= min_conv.value else None
            data = {"daily_amount": s["amount"], "amount_source": s["amount_source"], "target_cpa": tcpa,
                    "target_source": tsrc, "cost": cost, "conversions": conv, "achieved_cpa": ach,
                    "target_ratio": V.ratio(s["amount"], tcpa), "achieved_ratio": V.ratio(s["amount"], ach),
                    "min_conversions": min_conv.value, "window": [ctx.period_start, ctx.period_end]}
            st.observe(f"Campaign {cid}: budget-to-CPA descriptors (not requirements)", campaign_id=cid, **data)
            if tcpa is None:
                unavailable(st, cid, "target_ratio", tsrc, data)
            if ach is None:
                why = (f"outcomes not mature ({ctx.maturity_note})" if ctx.mature is not True else
                       "zero conversions" if conv == 0 else f"conversions {conv} below min_conversions {min_conv.value}"
                       if conv is not None else "mature cost/conversions missing")
                unavailable(st, cid, "achieved_ratio", why, data)

    # steps 3-4 — shared pools
    sa = ctx.check("shared_pool_achieved", "Shared-pool achieved ratio across comparable goals (step 3)",
                   {"campaigns": ["id", "daily_budget"], "campaign_metrics": METRIC_COLS})
    stg = ctx.check("shared_pool_target", "Shared-pool target ratio only for one shared target (step 4)",
                    {"campaigns": ["id", "daily_budget"]})
    pools = {k: s for k, s in sorted(scopes.items()) if s["type"] == "shared"}
    for key, s in pools.items():
        members = s["members"]
        goals = {m: tuple(sorted(ctx.goal_ids(m))) for m in members}
        comparable = all(goals.values()) and len(set(goals.values())) == 1
        acq = [m for m in members if m in camps and not _roas_campaign(ctx, camps[m])]
        if sa.runnable:
            outs = {m: outcome(m) for m in members}
            if not comparable or len(acq) != len(members):
                unavailable(sa, members[0], "pool_achieved_ratio",
                            f"pool {s['budget_id']} members lack identical declared goals or mix ROAS campaigns",
                            {"members": members, "goal_ids": {m: list(g) for m, g in goals.items()}})
            elif ctx.mature is not True or any(c is None or n is None for c, n in outs.values()):
                unavailable(sa, members[0], "pool_achieved_ratio", "member outcomes immature or missing",
                            {"members": members})
            else:
                cost, conv = sum(c for c, _ in outs.values()), sum(n for _, n in outs.values())
                ach = V.ratio(cost, conv) if min_conv.value is not None and conv >= min_conv.value else None
                if ach is None:
                    unavailable(sa, members[0], "pool_achieved_ratio", f"pool conversions {conv} below min_conversions",
                                {"members": members})
                else:
                    sa.observe(f"Pool {s['budget_id']}: achieved ratio over summed member outcomes", budget_id=s["budget_id"],
                               members=members, amount=s["amount"], cost=cost, conversions=conv, achieved_cpa=ach,
                               achieved_ratio=V.ratio(s["amount"], ach))
        if stg.runnable:
            targets = {m: ctx.params.target_cpa(m) for m in members}
            values = {t for t, _ in targets.values()}
            if comparable and len(values) == 1 and None not in values:
                t = values.pop()
                stg.observe(f"Pool {s['budget_id']}: one shared target basis", budget_id=s["budget_id"], members=members,
                            amount=s["amount"], target_cpa=t, target_ratio=V.ratio(s["amount"], t),
                            sources={m: src for m, (_, src) in targets.items()})
            else:
                stg.observe(f"Pool {s['budget_id']}: member targets shown descriptively; no pool target ratio",
                            budget_id=s["budget_id"], amount=s["amount"],
                            member_targets={m: {"target_cpa": t, "source": src} for m, (t, src) in targets.items()})
                unavailable(stg, members[0], "pool_target_ratio", "members do not share one target/goal basis",
                            {"members": members})

    # step 5 — zero-conversion spend
    zc = ctx.check("zero_conversion_spend", "Mature zero-conversion spend above spend_floor (step 5)",
                   {"campaign_metrics": METRIC_COLS})
    if zc.runnable:
        for cid in sorted(metrics):
            cost, conv = outcome(cid)
            if conv != 0 or not cost:
                continue
            floor = ctx.params.get("spend_floor", cid)
            if floor.value is None:
                zc.partial(f"campaign {cid}: spend_floor unresolved ({floor.reason})")
                continue
            if cost < floor.value:
                continue
            tracking, note = ctx.tracking_for_campaign(cid)
            if ctx.mature is not True or tracking is not True:
                zc.partial(f"campaign {cid}: zero-conversion screen blocked (maturity={ctx.mature}; {note})")
                continue
            entity = {"campaign_id": cid}
            ev = {"cost": cost, "conversions": 0, "spend_floor": floor.value, "spend_floor_source": floor.source,
                  "tracking_note": note, "window": [ctx.period_start, ctx.period_end]}
            prov = zc.finding("zero_conversion_spend", "Info", entity,
                              f"Campaign {cid}: {cost:.2f} {ctx.currency} with 0 mature conversions (spend_floor {floor.value:g})",
                              evidence=ev, recommendation="Review relevance and conversion cycle; no automatic pause.",
                              uncertainty="Long sales cycles or assisted value can explain zero conversions; exposure is not savings.")
            zc.review("zero_conversion_spend", entity,
                      f"With tracking evidenced, is campaign {cid}'s zero-conversion spend a relevance/economics concern?",
                      evidence=ev, provisional=prov,
                      outcomes={"relevance_concern": {"severity": "Warning", "recommendation": "Investigate targeting/offer fit."},
                                "explained": {"severity": None, "recommendation": "No finding (e.g. awareness role, long cycle)."},
                                "uncertain": {"severity": "Info", "recommendation": "Request campaign role and cycle evidence."}},
                      guidance="Judge only against the campaign's approved role and profile objectives.")

    # step 7 — efficiency context
    ef = ctx.check("efficiency_context", "Business efficiency and budget-lost IS context (step 7)",
                   {"campaign_metrics": METRIC_COLS})
    if ef.runnable:
        for cid in sorted(metrics):
            cost, conv = outcome(cid)
            row = (metrics[cid] or [{}])[0]
            tcpa, tsrc = ctx.params.target_cpa(cid)
            ef.observe(f"Campaign {cid}: efficiency context (a high ratio is not performance; a low ratio is not failure)",
                       campaign_id=cid, achieved_cpa=V.ratio(cost, conv) if ctx.mature is True else None,
                       target_cpa=tcpa, target_source=tsrc, budget_lost_is=ctx.rate(row.get("search_budget_lost_is")),
                       route="042/045 for dated constraints and marginal analysis")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
