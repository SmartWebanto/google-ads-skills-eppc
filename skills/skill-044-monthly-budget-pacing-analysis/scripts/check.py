"""check.py — skill-044 deterministic month-to-date pacing, forecasts and approved-cap checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-044-monthly-budget-pacing-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #34 Monthly Budget Target Email Alert (nilsrooijmans.com) — clean-room reimplementation of MTD spend vs
         approved monthly target/cap (report only, no email).
         index #35 Budget depletion warning (Brainlabs) — clean-room reimplementation of projected depletion date from
         the seven-day run rate against the remaining approved amount.
         index #38 Pause campaigns that have spent all-time budget (Kaugesaar) / #40 Pause labelled campaigns at total
         budget limit (Tang-Turcotte) — campaign-scope monthly cap breach only; pausing becomes an owner-reviewed
         recommendation; lifetime caps and label scopes are outside the recipe evidence.
         index #39 Pause campaigns when account budget is depleted (Thomas) — account-scope cap breach/forecast only.
rules:   Month = month of the last fully reported day (all rows complete_day True) <= ctx.as_of; partial days are
         excluded from pacing and shown as provisional spend. MTD needs a row for every day month-start..cutoff.
         Spend sums every campaign (no status filter), one row per campaign/date; duplicates or a foreign
         currency make the scope's MTD unavailable. Billed basis needs billed_cost_if_available on every row.
         Budget proxy = distinct dated budget amounts per day (budget ID counted once); it is never an approved cap.
         Expected E = sum(planned_spend through cutoff); otherwise approved_month_total × elapsed/days_in_month,
         labeled an assumption. Pacing outside 0.85–1.15 → provisional Info + intent review (Warning via review).
         Cap breach (cap_or_target=cap, matched basis): excess >= spend_significant → deterministic Critical;
         smaller excess → Info + review whose Critical outcome needs proposal.evidence_ref equal to the source_ref
         of an external/monthly_budget_plan cap row for the same scope and reviewed month.
         Without a plan: profile.monthly_budget comparisons are Info (basis unverified), never Critical/pacing pass.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | material_breach ref resolves to the scope's cap plan row
"""
from __future__ import annotations

import calendar
import math
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-044-monthly-budget-pacing-analysis"
VERSION = "1.0.0"

DAILY = "custom/monthly_spend_daily"
HISTORY = "custom/budget_history"
PLAN = "external/monthly_budget_plan"
DAILY_COLS = ["campaign_id", "date", "cost", "complete_day"]
HISTORY_COLS = ["budget_id", "effective_from", "effective_to", "amount", "member_campaign_ids"]
PLAN_COLS = ["scope_type", "scope_id", "month", "planned_spend", "approved_month_total", "cap_or_target", "spend_basis"]
BAND = (0.85, 1.15)
SEPS = (";", "|", ",")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _scope_type(v) -> str | None:
    t = V.norm_text(v)
    if t in ("account", "customer"):
        return "account"
    if t == "campaign":
        return "campaign"
    if t in ("budget", "pool", "shared_budget", "budget_pool", "shared budget", "budget pool"):
        return "pool"
    return None


def _amount(ctx, r) -> float | None:
    unit = _s(r.get("amount_unit")).lower()
    if unit in ("micros", "micro"):
        return V.money(r.get("amount"), "micros")
    if unit == "":
        return ctx.money(r.get("amount"))
    return V.num(r.get("amount")) if unit in ("currency", (ctx.currency or "").lower()) else None


def _dated(rows, d):
    hits = [r for r in rows if V.parse_date(r.get("effective_from")) and V.parse_date(r.get("effective_from")) <= d
            and (V.parse_date(r.get("effective_to")) is None or V.parse_date(r.get("effective_to")) >= d)]
    return hits[0] if len(hits) == 1 else None


class Month:
    """Reporting month facts derived from the daily table."""

    def __init__(self, ctx):
        self.rows: dict[tuple, list] = {}
        for r in ctx.rows(DAILY):
            cid, d = _s(r.get("campaign_id")), V.parse_date(r.get("date"))
            if cid and d:
                self.rows.setdefault((cid, d), []).append(r)
        by_day: dict[date, list] = {}
        for (cid, d), rs in self.rows.items():
            by_day.setdefault(d, []).extend(rs)
        cap = ctx.as_of
        complete = sorted(d for d, rs in by_day.items() if (cap is None or d <= cap)
                          and all(V.boolean(r.get("complete_day")) is True for r in rs))
        self.partial_days = sorted(d for d in by_day if d not in complete)
        self.cutoff = complete[-1] if complete else None
        self.by_day = by_day
        if self.cutoff:
            self.start = self.cutoff.replace(day=1)
            self.days_in_month = calendar.monthrange(self.cutoff.year, self.cutoff.month)[1]
            self.end = self.cutoff.replace(day=self.days_in_month)
            self.elapsed = (self.cutoff - self.start).days + 1
            self.remaining = self.days_in_month - self.elapsed
            span = [self.start + timedelta(days=i) for i in range(self.elapsed)]
            self.gaps = [d for d in span if d not in by_day or d in self.partial_days]
        self.duplicates = sorted(k for k, rs in self.rows.items() if len(rs) > 1)


def _scope_spend(ctx, m: Month, hist: dict, stype: str, sid: str, basis: str, days: list[date]):
    """Sum spend for a scope over days → (value, None) or (None, reason)."""
    total = 0.0
    col = "billed_cost_if_available" if basis == "billed" else "cost"
    for (cid, d), rs in sorted(m.rows.items()):
        if d not in days:
            continue
        r = rs[0]
        if stype == "campaign" and cid != sid:
            continue
        if stype == "pool":
            bid = _s(r.get("budget_id"))
            if not bid:
                h = _dated(hist.get(sid, []), d)
                if h is None:
                    return None, f"{cid} {d}: budget membership unknown"
                if cid not in V.split_list(h.get("member_campaign_ids"), SEPS):
                    continue
            elif bid != sid:
                continue
        if len(rs) > 1:
            return None, f"duplicate rows for campaign {cid} on {d}"
        cur = _s(r.get("currency")).upper()
        if cur and ctx.currency and cur != ctx.currency:
            return None, f"row currency {cur} differs from account {ctx.currency}"
        v = ctx.money(r.get(col))
        if v is None:
            return None, f"{DAILY}:{col} missing for {cid} {d}"
        total += v
    return total, None


def _plans(ctx, month_key: str) -> tuple[dict, list[str]]:
    groups: dict[tuple, list] = {}
    problems = []
    for r in ctx.rows(PLAN):
        st = _scope_type(r.get("scope_type"))
        if st is None or _s(r.get("month"))[:7] != month_key:
            continue
        groups.setdefault((st, _s(r.get("scope_id")) if st != "account" else "account"), []).append(r)
    out = {}
    for key, rows in sorted(groups.items()):
        def one(col):
            vals = sorted({_s(x.get(col)) for x in rows if _s(x.get(col))})
            return vals
        totals, kinds, bases, curs = one("approved_month_total"), one("cap_or_target"), one("spend_basis"), one("currency")
        if len(totals) > 1 or len(kinds) > 1 or len(bases) > 1:
            problems.append(f"plan {key}: conflicting total/cap_or_target/spend_basis {totals}/{kinds}/{bases}")
            continue
        if curs and ctx.currency and any(c.upper() != ctx.currency for c in curs):
            problems.append(f"plan {key}: currency {curs} differs from account {ctx.currency}")
            continue
        daily = {}
        for x in rows:
            d, p = V.parse_date(x.get("date")), ctx.money(x.get("planned_spend"))
            if d is not None and p is not None:
                daily[d] = daily.get(d, 0.0) + p
        basis = V.norm_text(bases[0]) if bases else None
        out[key] = {"total": ctx.money(totals[0]) if totals else None, "kind": V.norm_text(kinds[0]) if kinds else None,
                    "basis": "billed" if basis and "bill" in basis else "cost" if basis else None, "daily": daily,
                    "owner": sorted({_s(x.get("owner")) for x in rows if _s(x.get("owner"))}),
                    "approved_at": sorted({_s(x.get("approved_at")) for x in rows if _s(x.get("approved_at"))}),
                    "source_ref": sorted({_s(x.get("source_ref")) for x in rows if _s(x.get("source_ref"))})}
    return out, problems


def run(ctx) -> None:
    """Run reporting cutoff, month-to-date spend, budget proxy, pacing, forecast and approved-cap checks.

    Rules:   Missing days, duplicate rows or foreign currency make the scope's MTD unavailable (partial), never a pass.
             Pacing outside 0.85–1.15 → provisional Info + ai_review (Warning only 'unintentional_deviation'). Approved
             cap breach on a matched basis: excess >= spend_significant → deterministic Critical, smaller → Info +
             review. profile.monthly_budget without a plan is Info only (basis unverified); the budget proxy is never an
             approved cap.
    """
    hist: dict[str, list] = {}
    for r in ctx.rows(HISTORY):
        if _s(r.get("budget_id")):
            hist.setdefault(_s(r.get("budget_id")), []).append(r)
    names = [("mtd_spend", "Month-to-date spend across all campaigns (step 2)"),
             ("budget_proxy", "Deduplicated dated daily-budget proxy (step 3)"),
             ("pacing", "Pacing against the approved plan (steps 4, 8)"),
             ("forecasts", "Linear, seven-day and plan-scenario forecasts (steps 5-6)"),
             ("remaining_arithmetic", "Remaining approved amount arithmetic (step 7)"),
             ("cap_breach", "Actual spend vs explicit approved cap (Critical row)")]

    # step 1 — cutoff
    cut = ctx.check("reporting_cutoff", "Reporting month and last complete day (step 1)", {DAILY: DAILY_COLS})
    m = Month(ctx) if cut.runnable else None
    if m is None or m.cutoff is None:
        if cut.runnable:
            cut.partial("no fully reported day on or before the as-of date")
        own = {"budget_proxy": {HISTORY: HISTORY_COLS}, "pacing": {PLAN: PLAN_COLS}, "cap_breach": {PLAN: PLAN_COLS}}
        for cid, title in names:
            c = ctx.check(cid, title, own.get(cid))
            c.skip("reporting cutoff unavailable", cut.missing or [f"{DAILY}:complete_day"])
        return
    provisional = sum(ctx.money(r.get("cost")) or 0 for d in m.partial_days if d > m.cutoff for r in m.by_day[d])
    cut.observe(f"Reporting month {m.start:%Y-%m}, last complete day {m.cutoff}", month=f"{m.start:%Y-%m}",
                cutoff=m.cutoff, elapsed_complete_days=m.elapsed, days_in_month=m.days_in_month,
                remaining_days=m.remaining, provisional_days=[d for d in m.partial_days if d > m.cutoff],
                provisional_spend=provisional, as_of=ctx.as_of)
    days = [m.start + timedelta(days=i) for i in range(m.elapsed)]
    mtd_ok = not m.gaps
    if m.gaps:
        cut.partial(f"missing/incomplete days in month-to-date {m.gaps[:5]}{'…' if len(m.gaps) > 5 else ''}: no MTD claims")

    # step 2 — MTD
    mtd = ctx.check("mtd_spend", names[0][1], {DAILY: DAILY_COLS})
    acct_cost, why = _scope_spend(ctx, m, hist, "account", "", "cost", days) if mtd_ok else (None, "month-to-date gaps")
    has_billed = ctx.table(DAILY) is not None and "billed_cost_if_available" in ctx.table(DAILY).columns
    acct_billed, bwhy = (_scope_spend(ctx, m, hist, "account", "", "billed", days) if mtd_ok and has_billed
                         else (None, f"{DAILY}:billed_cost_if_available missing"))
    if acct_cost is None:
        mtd.partial(f"account MTD unavailable: {why}")
    if acct_billed is None:
        mtd.partial(f"billed MTD unavailable ({bwhy}): no billing-limit claims")
    mtd.observe("Account month-to-date spend (all campaigns incl. paused/removed)", cost=acct_cost, billed=acct_billed,
                window=[m.start, m.cutoff], campaigns=len({c for c, d in m.rows if d in days}))

    # step 3 — budget proxy
    bp = ctx.check("budget_proxy", names[1][1], {HISTORY: HISTORY_COLS})
    if bp.runnable:
        month_days = [m.start + timedelta(days=i) for i in range(m.days_in_month)]
        proxy, unknown = 0.0, []
        for bid, rows in sorted(hist.items()):
            for d in month_days:
                h = _dated(rows, d)
                if h is None:
                    continue
                a = _amount(ctx, h)
                if a is None:
                    unknown.append(bid)
                    break
                proxy += a
        if unknown:
            bp.partial(f"budget amounts unknown for {sorted(set(unknown))}")
        bp.observe("Daily-budget proxy for the month (planning proxy, not an approved cap)", proxy=proxy,
                   budgets=sorted(hist), month=f"{m.start:%Y-%m}")

    # plans
    plans, problems = _plans(ctx, f"{m.start:%Y-%m}") if ctx.table(PLAN) is not None else ({}, [])
    have_plan = ctx.table(PLAN) is not None and not ctx.table(PLAN).missing(PLAN_COLS)
    overlap = sorted(k for k in plans if k[0] == "campaign" and any(
        p[0] == "pool" and k[1] in {m_ for r in hist.get(p[1], []) for m_ in V.split_list(r.get("member_campaign_ids"), SEPS)}
        for p in plans))

    def spend(key, plan):
        basis = plan["basis"] or "cost"
        if not mtd_ok:
            return None, "month-to-date gaps"
        return _scope_spend(ctx, m, hist, key[0], key[1], basis, days)

    # step 4/8 — pacing
    pc = ctx.check("pacing", names[2][1], {PLAN: PLAN_COLS})
    ledger: dict[tuple, dict] = {}
    if pc.runnable:
        for p in problems:
            pc.partial(p)
        if overlap:
            pc.observe("Campaign plans nested inside pool plans are reported separately, never added", scopes=overlap)
        if not plans:
            pc.partial(f"no approved plan rows for {m.start:%Y-%m}")
        for key, plan in sorted(plans.items()):
            a, why = spend(key, plan)
            planned_to_date = sum(v for d, v in plan["daily"].items() if d <= m.cutoff)
            if plan["daily"]:
                e, e_src = planned_to_date, "sum(planned_spend through cutoff)"
            elif plan["total"] is not None:
                e, e_src = plan["total"] * m.elapsed / m.days_in_month, "ASSUMPTION uniform daily weighting of approved_month_total"
            else:
                e, e_src = None, "no planned_spend or approved_month_total"
            entry = {"scope_type": key[0], "scope_id": key[1], "actual": a, "expected": e, "expected_source": e_src,
                     "pacing": V.ratio(a, e) if e and e > 0 else None, "spend_basis": plan["basis"],
                     "approved_month_total": plan["total"], "cap_or_target": plan["kind"], "cutoff": m.cutoff,
                     "owner": plan["owner"], "source_ref": plan["source_ref"]}
            ledger[key] = {**entry, "plan": plan}
            if a is None:
                pc.partial(f"scope {key}: actual spend unavailable ({why})")
                continue
            if plan["basis"] is None:
                pc.partial(f"scope {key}: spend_basis unknown; cost used for pacing only")
            p_ = entry["pacing"]
            if p_ is None:
                pc.partial(f"scope {key}: expected spend unavailable or zero ({e_src})")
                continue
            entity = {"scope_type": key[0], "scope_id": key[1], "month": f"{m.start:%Y-%m}"}
            if BAND[0] <= p_ <= BAND[1]:
                pc.observe(f"Scope {key[0]} {key[1]}: pacing {p_:.2f} inside {BAND}", **entry)
                continue
            prov = pc.finding("pacing_outside_band", "Info", entity,
                              f"{key[0]} {key[1]}: pacing {p_:.2f} (actual {a:.2f} / expected {e:.2f}) outside {BAND[0]}–{BAND[1]}",
                              evidence=entry, calculation={"formula": "A/E", "A": a, "E": e, "E_source": e_src},
                              recommendation="Check dated budget/status/event changes; owner-reviewed correction with pool scope.",
                              uncertainty="Pacing is a review heuristic; intentional deviations are legitimate.")
            pc.review("pacing_deviation", entity,
                      f"Is the {'under' if p_ < BAND[0] else 'over'}-pacing of {key[0]} {key[1]} an unintentional deviation from the approved plan?",
                      evidence=entry, provisional=prov,
                      outcomes={"unintentional_deviation": {"severity": "Warning", "recommendation":
                                                            "Propose an owner-reviewed budget correction at the correct pool scope."},
                                "intentional_deviation": {"severity": None, "recommendation": "Document the intent; no finding."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask the plan owner."}},
                      guidance="Use dated budget/status/event evidence and the plan owner record only.")
    elif ctx.profile.get("monthly_budget") is not None:
        pc.observe("No approved plan file: profile.monthly_budget used only for Info comparisons (basis unverified)",
                   monthly_budget=ctx.money(ctx.profile.get("monthly_budget")))

    # steps 5-6 — forecasts
    fc = ctx.check("forecasts", names[3][1], {DAILY: DAILY_COLS})
    scopes = dict(ledger)
    if not scopes and acct_cost is not None:
        prof_cap = ctx.money(ctx.profile.get("monthly_budget"))
        scopes[("account", "account")] = {"scope_type": "account", "scope_id": "account", "actual": acct_cost,
                                          "approved_month_total": prof_cap, "cap_or_target": "cap" if prof_cap else None,
                                          "spend_basis": None, "profile_cap": True,
                                          "plan": {"basis": None, "daily": {}, "total": prof_cap, "kind": "cap"}}
    forecasts: dict[tuple, dict] = {}
    for key, s in sorted(scopes.items()):
        a = s["actual"]
        if a is None:
            continue
        last7 = [m.cutoff - timedelta(days=i) for i in range(7)]
        run7, why7 = (_scope_spend(ctx, m, hist, key[0], key[1], s["plan"]["basis"] or "cost", last7)
                      if all(d in m.by_day and d not in m.partial_days for d in last7) else (None, "fewer than 7 complete days"))
        mean7 = run7 / 7 if run7 is not None else None
        f = {"linear": a / m.elapsed * m.days_in_month, "seven_day": a + mean7 * m.remaining if mean7 is not None else None,
             "seven_day_mean": mean7, "plan_scenario": (a + sum(v for d, v in s["plan"]["daily"].items() if d > m.cutoff))
             if s["plan"]["daily"] else None, "remaining_days": m.remaining}
        if mean7 is None:
            fc.partial(f"scope {key}: seven-day forecast unavailable ({why7})")
        total = s.get("approved_month_total")
        if total is not None and mean7 and mean7 > 0 and total > a:
            days_left = math.ceil((total - a) / mean7)
            f["projected_depletion_date"] = m.cutoff + timedelta(days=days_left) if days_left <= m.remaining else None
        forecasts[key] = f
        fc.observe(f"Scope {key[0]} {key[1]}: forecasts (assumptions, not predictions)", scope_type=key[0], scope_id=key[1], **f)
        risky = [n for n in ("linear", "seven_day", "plan_scenario") if f.get(n) is not None and total is not None and f[n] > total]
        if total is not None and s.get("cap_or_target") == "cap" and risky and a <= total:
            fc.finding("forecast_cap_risk", "Info", {"scope_type": key[0], "scope_id": key[1], "month": f"{m.start:%Y-%m}"},
                       f"{key[0]} {key[1]}: {', '.join(risky)} forecast exceeds the {'profile' if s.get('profile_cap') else 'approved'} "
                       f"cap {total:.2f}", evidence={**f, "actual": a, "cap": total,
                                                     "cap_source": "profile.monthly_budget (basis unverified)" if s.get("profile_cap") else PLAN},
                       recommendation="Owner review of remaining daily budgets at the correct pool scope; no automatic pause.",
                       uncertainty="Forecasts are arithmetic scenarios; demand and budget changes alter them.")

    # step 7 — remaining arithmetic
    ra = ctx.check("remaining_arithmetic", names[4][1])
    for key, s in sorted(scopes.items()):
        total, a = s.get("approved_month_total"), s["actual"]
        if total is None or a is None:
            ra.partial(f"scope {key}: approved total or actual unavailable")
            continue
        rem = total - a
        ra.observe(f"Scope {key[0]} {key[1]}: remaining approved amount", scope_type=key[0], scope_id=key[1],
                   approved_month_total=total, actual=a, remaining_amount=rem, remaining_days=m.remaining,
                   required_avg_daily=rem / m.remaining if m.remaining > 0 and rem > 0 else None,
                   note="arithmetic planning, not a safe daily-budget setting")
    if not scopes:
        ra.partial("no scope with an approved total")

    # Critical row — cap breach
    cb = ctx.check("cap_breach", names[5][1])
    if not have_plan:
        cb.partial("no approved plan: cap breach not assessable", [f"{PLAN}:{c}" for c in PLAN_COLS] if ctx.table(PLAN) is None
                   else [f"{PLAN}:{c}" for c in ctx.table(PLAN).missing(PLAN_COLS)])
    for key, s in sorted(scopes.items()):
        total, plan = s.get("approved_month_total"), s["plan"]
        if s.get("cap_or_target") != "cap" or total is None:
            continue
        entity = {"scope_type": key[0], "scope_id": key[1], "month": f"{m.start:%Y-%m}"}
        if s.get("profile_cap"):
            if acct_cost is not None and acct_cost > total:
                cb.finding("profile_cap_exceeded_basis_unverified", "Info", entity,
                           f"Account MTD cost {acct_cost:.2f} exceeds profile.monthly_budget {total:.2f} (spend basis unverified)",
                           evidence={"actual_cost": acct_cost, "monthly_budget": total, "cutoff": m.cutoff},
                           recommendation="Supply the approved plan with spend basis before any cap claim.",
                           uncertainty="Profile cap basis (cost vs billed) is unknown.")
            continue
        if plan["basis"] is None:
            cb.partial(f"scope {key}: spend_basis unknown; no cap-breach claim")
            continue
        a, why = spend(key, plan)
        if a is None:
            cb.partial(f"scope {key}: matched-basis spend unavailable ({why})")
            continue
        if a <= total:
            cb.observe(f"Scope {key[0]} {key[1]}: within approved cap", actual=a, cap=total, basis=plan["basis"])
            continue
        mat = ctx.params.get("spend_significant", key[1] if key[0] == "campaign" else None)
        ev = {"actual": a, "cap": total, "excess": a - total, "spend_basis": plan["basis"], "cutoff": m.cutoff,
              "materiality": mat.value, "materiality_source": mat.source or mat.reason, "owner": plan["owner"],
              "approved_at": plan["approved_at"], "source_ref": plan["source_ref"]}
        rec = ("Owner-reviewed stop/pause or budget reduction proposal at this scope; reconcile billing before any "
               "credit claim. No automatic change.")
        if mat.value is not None and a - total >= mat.value:
            cb.finding("approved_cap_exceeded", "Critical", entity,
                       f"{key[0]} {key[1]}: {plan['basis']} spend {a:.2f} exceeds approved cap {total:.2f} by {a - total:.2f}",
                       evidence=ev, calculation={"excess": a - total, "materiality_threshold": mat.value},
                       recommendation=rec, uncertainty="Overage is spent exposure, not recoverable savings.")
            continue
        prov = cb.finding("approved_cap_exceeded", "Info", entity,
                          f"{key[0]} {key[1]}: {plan['basis']} spend {a:.2f} exceeds approved cap {total:.2f} by {a - total:.2f} "
                          f"(below materiality {mat.value})", evidence=ev, recommendation=rec,
                          uncertainty="Small overages can be normal delivery variance.")
        cb.review("approved_cap_exceeded", entity, f"Is the {a - total:.2f} overage of {key[0]} {key[1]} a material cap breach?",
                  evidence=ev, provisional=prov,
                  outcomes={"material_breach": {"severity": "Critical", "recommendation": rec},
                            "immaterial_overage": {"severity": "Info", "recommendation": "Note; monitor remaining days."}},
                  guidance="material_breach needs proposal.evidence_ref to the approved cap/billing evidence.")


def _cap_plan_refs(ctx, entity: dict) -> set[str]:
    """source_refs of monthly_budget_plan cap rows for the entity's scope and month."""
    stype, month = entity.get("scope_type"), str(entity.get("month") or "")
    sid = "account" if stype == "account" else str(entity.get("scope_id"))
    refs = set()
    for r in ctx.rows(PLAN):
        st = _scope_type(r.get("scope_type"))
        if st != stype or (_s(r.get("scope_id")) if st != "account" else "account") != sid \
                or _s(r.get("month"))[:7] != month or V.norm_text(r.get("cap_or_target")) != "cap":
            continue
        if _s(r.get("source_ref")):
            refs.add(_s(r.get("source_ref")))
    return refs


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   material_breach (Critical) requires proposal.evidence_ref equal to the source_ref of an
             external/monthly_budget_plan row with cap_or_target=cap for the item's scope_type/scope_id and month;
             refs of other scopes, months or target rows are rejected. immaterial_overage needs no proposal.
    """
    if decision.get("outcome") != "material_breach":
        return []
    ref = _s((decision.get("proposal") or {}).get("evidence_ref"))
    if not ref:
        return ["material_breach needs proposal.evidence_ref"]
    if ref not in _cap_plan_refs(ctx, item.entity):
        return [f"evidence_ref {ref} is not a {PLAN} cap row source_ref for {item.entity.get('scope_type')} "
                f"{item.entity.get('scope_id')} in {item.entity.get('month')}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
