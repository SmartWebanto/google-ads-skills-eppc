"""check.py — skill-137 deterministic multi-cycle seasonal pattern description.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-137-seasonal-performance-pattern-tracking/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #100 Declining Ad Groups Report (Google Ads scripts solution) — clean-room reimplementation of
         "metric declined in each of N consecutive periods" at campaign/month grain (the recipe's evidence grain),
         CTR sample-gated per period and shown next to prior-year same months; weekly ad-group reporting and
         spreadsheet output are not reproduced.
rules:   A month is COMPARABLE only if: year_month parses, active_days == days in month, month end + lag <= snapshot
         (lag known), goal_id and tracking_basis equal the campaign's most recent month, and no supplied
         structural_change/tracking_change context overlaps it. Renames/new structures are breaks, not growth.
         Rates are pooled sums per year (never averages of monthly rates); CTR needs min_impressions, CVR
         min_clicks, CPA min_conversions — on BOTH compared sides.
         Complete cycle = a calendar year whose 12 months are all comparable; < 2 cycles → Info single_cycle.
         Recurring decline: month m vs the same year's pooled comparable NON-event months (event months from
         external/seasonal_context), decline = 1 - CVR_m / CVR_normal > 0.30 in >= 2 cycles → provisional Info +
         review for "material client goal risk" (Warning only via review). One qualifying cycle → Info.
         Without seasonal_context the normal baseline cannot exclude events → decline check partial, no review.
         Budget history is context only; spend/volume changes may reflect budgets, not demand. IS changes never
         establish competition; censored IS values are preserved raw, never converted to numbers.
         Routine monthly seasonality never yields bid-seasonality proposals (skill-146 owns short exceptions).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import calendar
import re
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

SKILL = "skill-137-seasonal-performance-pattern-tracking"
VERSION = "1.0.0"

MONTHLY = "custom/seasonal_monthly"
BUDGETS = "custom/seasonal_budget_history"
CONTEXT = "external/seasonal_context"
DECLINE = 0.30
_YM = re.compile(r"^(\d{4})-(\d{2})")
_DATES = re.compile(r"\d{4}-\d{2}-\d{2}")
_SEPS = (" | ", ";", "|", ",")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _ym(v) -> tuple[int, int] | None:
    m = _YM.match(_s(v))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return int(m.group(1)), int(m.group(2))


def _month_bounds(ym: tuple[int, int]) -> tuple[date, date]:
    return date(ym[0], ym[1], 1), date(ym[0], ym[1], calendar.monthrange(*ym)[1])


def _span(text) -> tuple[date, date] | None:
    ds = sorted(V.parse_date(x) for x in _DATES.findall(_s(text)))
    return (ds[0], ds[-1]) if ds else None


def _flag(v) -> bool:
    s = _s(v).lower()
    return bool(s) and V.boolean(s) is not False and s not in ("none", "no change", "n/a")


class _Model:
    """Per-campaign monthly series with comparability flags."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.series: dict[str, dict[tuple[int, int], dict]] = {}
        self.dupes = self.bad = 0
        for r in ctx.rows(MONTHLY):
            ym = _ym(r.get("year_month"))
            if ym is None:
                self.bad += 1
                continue
            cid = _s(r.get("campaign_id"))
            if ym in self.series.setdefault(cid, {}):
                self.dupes += 1
                continue
            self.series[cid][ym] = r
        self.context_present = ctx.table(CONTEXT) is not None
        self.events: dict[str, list[tuple[date, date, dict]]] = {}
        self.breaks: dict[str, list[tuple[date, date, dict]]] = {}
        for c in ctx.rows(CONTEXT):
            cid = _s(c.get("campaign_id"))
            for col in ("date_range", "promotion_dates"):
                sp = _span(c.get(col))
                if sp:
                    self.events.setdefault(cid, []).append((*sp, c))
            if _flag(c.get("structural_change")) or _flag(c.get("tracking_change")):
                sp = _span(c.get("date_range"))
                if sp:
                    self.breaks.setdefault(cid, []).append((*sp, c))

    def reasons(self, cid: str, ym) -> list[str]:
        """Empty list = comparable month."""
        ctx, r = self.ctx, self.series[cid][ym]
        start, end = _month_bounds(ym)
        out = []
        if V.integer(r.get("active_days")) != (end - start).days + 1:
            out.append(f"active_days {r.get('active_days')} of {(end - start).days + 1}")
        if ctx.lag_days is None or ctx.snapshot is None or (ctx.snapshot - end).days < ctx.lag_days:
            out.append("not lag-mature")
        latest = self.series[cid][max(self.series[cid])]
        for col in ("goal_id", "tracking_basis"):
            if _s(r.get(col)) != _s(latest.get(col)):
                out.append(f"{col} {r.get(col)} differs from current {latest.get(col)}")
        for a, b, c in self.breaks.get(cid, []):
            if a <= end and b >= start:
                out.append(f"context break {c.get('event_id')} ({c.get('event_type')})")
        return out

    def is_event(self, cid: str, ym) -> bool:
        start, end = _month_bounds(ym)
        return any(a <= end and b >= start for a, b, _ in self.events.get(cid, []))

    def totals(self, cid: str, months) -> dict:
        t = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0,
             "unknown_cells": 0, "months": len(months)}
        for ym in months:
            r = self.series[cid][ym]
            for k in ("impressions", "clicks", "cost", "conversions", "conversion_value"):
                v = self.ctx.money(r.get(k)) if k in ("cost", "conversion_value") else V.num(r.get(k))
                if v is None:
                    t["unknown_cells"] += 1
                else:
                    t[k] += v
        return t


def run(ctx) -> None:
    """Run comparability, monthly rate, normal baseline, recurring decline, CTR, budget and IS context checks.

    Rules:   Non-comparable months (incomplete, immature, goal/tracking change, structural break) are excluded; rates
             are pooled with min gates on both sides. Recurring >30% CVR decline in >= 2 cycles → provisional Info +
             review (Warning only via review); fewer cycles → Info; without seasonal_context the decline check is
             partial. Budget and IS are context only; no bid-seasonality proposals.
    """
    model = _Model(ctx) if ctx.table(MONTHLY) is not None else None
    _comparability(ctx, model)
    _monthly_rates(ctx, model)
    _normal_baseline(ctx, model)
    _recurring_decline(ctx, model)
    _consecutive_ctr(ctx, model)
    _budget_context(ctx, model)
    _is_context(ctx)


def _comparability(ctx, model) -> None:
    """Step 1: holidays/active days/maturity/goal alignment; structural breaks are marked, not growth."""
    chk = ctx.check("comparability", "Month comparability and structural breaks",
                    {MONTHLY: ["campaign_id", "year_month", "goal_id", "active_days", "tracking_basis"]})
    if not chk.runnable:
        return
    if model.dupes or model.bad:
        chk.partial(f"{model.dupes} duplicate campaign/year_month rows ignored; {model.bad} unparseable year_month")
    if not model.context_present:
        chk.partial("seasonal_context missing: structural/tracking breaks from client history unknown",
                    [f"{CONTEXT} (file)"])
    if ctx.lag_days is None:
        chk.partial("conversion lag unknown: no month is lag-mature")
    for cid in sorted(model.series):
        excluded = {f"{y}-{m:02d}": model.reasons(cid, (y, m)) for (y, m) in sorted(model.series[cid])}
        excluded = {k: v for k, v in excluded.items() if v}
        breaks = {k: v for k, v in excluded.items()
                  if any(x.startswith(("goal_id", "tracking_basis", "context break")) for x in v)}
        chk.observe(f"Campaign {cid}: comparability", campaign_id=cid, months=len(model.series[cid]),
                    comparable=len(model.series[cid]) - len(excluded), excluded=excluded)
        if breaks:
            chk.finding("structural_break", "Info", {"campaign_id": cid},
                        f"Campaign {cid}: {len(breaks)} months are structurally incomparable (goal/tracking basis/"
                        f"structural change)", evidence={"months": breaks},
                        recommendation="Compare only months on the current goal and tracking basis.",
                        uncertainty="Breaks are not growth or decline.")


def _cycles(model, cid) -> list[int]:
    years = sorted({y for y, _ in model.series[cid]})
    return [y for y in years if all((y, m) in model.series[cid] and not model.reasons(cid, (y, m))
                                    for m in range(1, 13))]


def _monthly_rates(ctx, model) -> None:
    """Step 2: pooled rates within each year; cycle count."""
    chk = ctx.check("monthly_rates", "Pooled yearly/monthly rates and complete-cycle count",
                    {MONTHLY: ["campaign_id", "year_month", "goal_id", "impressions", "clicks", "cost", "conversions",
                               "conversion_value", "active_days", "tracking_basis"]})
    if not chk.runnable:
        return
    mi, mcl, mc = (ctx.params.get(p) for p in ("min_impressions", "min_clicks", "min_conversions"))
    for cid in sorted(model.series):
        cycles = _cycles(model, cid)
        for y in sorted({y for y, _ in model.series[cid]}):
            months = [ym for ym in sorted(model.series[cid]) if ym[0] == y and not model.reasons(cid, ym)]
            t = model.totals(cid, months)
            chk.observe(f"Campaign {cid} {y}: pooled comparable-month totals", campaign_id=cid, year=y, **t,
                        ctr=V.ratio(t["clicks"], t["impressions"]) if mi.value and t["impressions"] >= mi.value else None,
                        cvr=V.ratio(t["conversions"], t["clicks"]) if mcl.value and t["clicks"] >= mcl.value else None,
                        cpa=V.ratio(t["cost"], t["conversions"]) if mc.value and t["conversions"] >= mc.value else None,
                        complete_cycle=y in cycles)
        if len(cycles) < 2:
            chk.finding("single_cycle", "Info", {"campaign_id": cid},
                        f"Campaign {cid}: {len(cycles)} complete comparable annual cycle(s); patterns are "
                        f"descriptive, not repeated seasonality",
                        evidence={"complete_cycles": cycles, "months_supplied": len(model.series[cid])},
                        recommendation="Supply 24-36 complete comparable months before calling a pattern seasonal.",
                        uncertainty="One cycle cannot separate seasonality from one-off events.")


def _normal_baseline(ctx, model) -> None:
    """Step 3: non-event normal months per year from client context."""
    chk = ctx.check("normal_baseline", "Non-event normal baseline per year",
                    {MONTHLY: ["campaign_id", "year_month", "clicks", "conversions"],
                     CONTEXT: ["campaign_id", "event_id", "date_range", "event_type", "promotion_dates",
                               "evidence_ref"]})
    if not chk.runnable:
        return
    mcl = ctx.params.get("min_clicks")
    for cid in sorted(model.series):
        for y in sorted({y for y, _ in model.series[cid]}):
            months = [ym for ym in sorted(model.series[cid]) if ym[0] == y and not model.reasons(cid, ym)]
            normal = [ym for ym in months if not model.is_event(cid, ym)]
            t = model.totals(cid, normal)
            chk.observe(f"Campaign {cid} {y}: normal baseline", campaign_id=cid, year=y,
                        normal_months=[f"{a}-{b:02d}" for a, b in normal],
                        event_months=[f"{a}-{b:02d}" for a, b in months if model.is_event(cid, (a, b))],
                        clicks=t["clicks"], conversions=t["conversions"],
                        cvr=V.ratio(t["conversions"], t["clicks"]) if mcl.value and t["clicks"] >= mcl.value else None)


def _recurring_decline(ctx, model) -> None:
    """Step 4: >30% recurring CVR decline vs same-year normal months, min_clicks on both cohorts."""
    chk = ctx.check("recurring_cvr_decline", "Recurring >30% same-season CVR decline",
                    {MONTHLY: ["campaign_id", "year_month", "goal_id", "clicks", "conversions", "active_days",
                               "tracking_basis"]})
    if not chk.runnable:
        return
    no_context = not model.context_present
    if no_context:
        chk.partial("seasonal_context missing: normal baseline cannot exclude event months; no Warning path",
                    [f"{CONTEXT} (file)"])
    mcl = ctx.params.get("min_clicks")
    budgets = _budgets_by_month(ctx)
    for cid in sorted(model.series):
        comparable = [ym for ym in sorted(model.series[cid]) if not model.reasons(cid, ym)]
        for m in range(1, 13):
            per_year = []
            for y in sorted({a for a, b in comparable if b == m}):
                normal = [ym for ym in comparable if ym[0] == y and ym[1] != m and not model.is_event(cid, ym)]
                season, base = model.totals(cid, [(y, m)]), model.totals(cid, normal)
                if mcl.value is None or season["clicks"] < mcl.value or base["clicks"] < mcl.value:
                    continue
                cs, cn = V.ratio(season["conversions"], season["clicks"]), V.ratio(base["conversions"], base["clicks"])
                if cs is None or not cn:
                    continue
                per_year.append({"year": y, "season_clicks": season["clicks"], "season_conversions": season["conversions"],
                                 "season_cvr": cs, "normal_clicks": base["clicks"],
                                 "normal_conversions": base["conversions"], "normal_cvr": cn,
                                 "normal_months": len(normal), "decline": 1 - cs / cn,
                                 "budget_amounts": budgets.get((cid, y, m))})
            hits = [p for p in per_year if p["decline"] > DECLINE]
            if not hits:
                continue
            entity = {"campaign_id": cid, "month": f"{m:02d}"}
            ev = {"cycles": per_year, "qualifying_cycles": [p["year"] for p in hits], "threshold": DECLINE,
                  "min_clicks": mcl.value, "min_clicks_source": mcl.source, "context_present": model.context_present}
            if len(hits) < 2 or no_context:
                chk.finding("single_cycle_decline", "Info", entity,
                            f"Campaign {cid} month {m:02d}: >30% CVR decline vs normal in {len(hits)} cycle(s)"
                            + ("" if model.context_present else "; event months not excluded"),
                            evidence=ev, recommendation="Treat as a hypothesis; gather another comparable cycle.",
                            uncertainty="One cycle or unfiltered baseline cannot establish recurrence.")
                continue
            prov = chk.finding("recurring_cvr_decline", "Info", entity,
                               f"Campaign {cid} month {m:02d}: CVR >30% below same-year normal in "
                               f"{len(hits)} comparable cycles ({', '.join(str(p['year']) for p in hits)})",
                               evidence=ev,
                               recommendation="Hand planning scenarios to skill-152/147; no automatic bid/budget change.",
                               uncertainty="Recurring association, not causal proof; budgets may explain volume.")
            chk.review("recurring_cvr_decline", entity,
                       f"Does the recurring month-{m:02d} CVR decline for campaign {cid} create material risk to a "
                       f"stated client goal?",
                       evidence={**ev, "objectives": ctx.profile.get("objectives"),
                                 "campaign_objective": next((v for k, v in (ctx.profile.get("campaign_objectives") or {}).items()
                                                            if str(k) == cid), None)},
                       outcomes={"material_goal_risk": {"severity": "Warning", "recommendation":
                                                        "Plan scenarios with the owner (skill-152/147)."},
                                 "routine_pattern": {"severity": "Info", "recommendation":
                                                     "Document as routine seasonality; no adjustment."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask for the goal tolerance."}},
                       guidance="Only stated client goals count. Routine monthly seasonality never merits bid "
                                "seasonality adjustments (skill-146 owns short exceptional deviations).",
                       provisional=prov)


def _consecutive_ctr(ctx, model) -> None:
    """#100 clean-room: CTR declined in each of the last 3 consecutive comparable months (campaign grain)."""
    chk = ctx.check("consecutive_ctr_decline", "Three consecutive monthly CTR declines (#100, descriptive)",
                    {MONTHLY: ["campaign_id", "year_month", "impressions", "clicks", "active_days", "goal_id",
                               "tracking_basis"]})
    if not chk.runnable:
        return
    mi = ctx.params.get("min_impressions")
    for cid in sorted(model.series):
        months = sorted(model.series[cid])
        if len(months) < 4:
            continue
        last = months[-4:]
        consecutive = all((b[0] * 12 + b[1]) - (a[0] * 12 + a[1]) == 1 for a, b in zip(last, last[1:]))
        if not consecutive or any(model.reasons(cid, ym) for ym in last):
            continue
        pts = []
        for ym in last:
            t = model.totals(cid, [ym])
            prior = (ym[0] - 1, ym[1])
            pt = model.totals(cid, [prior]) if prior in model.series[cid] and not model.reasons(cid, prior) else None
            pts.append({"year_month": f"{ym[0]}-{ym[1]:02d}", "impressions": t["impressions"],
                        "ctr": V.ratio(t["clicks"], t["impressions"]),
                        "prior_year_ctr": V.ratio(pt["clicks"], pt["impressions"])
                        if pt and mi.value and pt["impressions"] >= mi.value else None})
        if mi.value is None or any(p["impressions"] < mi.value or p["ctr"] is None for p in pts):
            continue
        if all(b["ctr"] < a["ctr"] for a, b in zip(pts, pts[1:])):
            chk.finding("consecutive_ctr_decline", "Info", {"campaign_id": cid},
                        f"Campaign {cid}: CTR declined in each of the last 3 comparable months "
                        f"({pts[0]['year_month']}..{pts[-1]['year_month']})",
                        evidence={"months": pts, "min_impressions": mi.value},
                        recommendation="Compare with prior-year same months before calling it a trend or seasonal.",
                        uncertainty="Descriptive; may be a routine seasonal pattern.")


def _budgets_by_month(ctx) -> dict:
    out: dict[tuple, list] = {}
    for b in ctx.rows(BUDGETS):
        start = V.parse_date(b.get("effective_from"))
        end = V.parse_date(b.get("effective_to"))
        amt = ctx.money(b.get("amount"))
        if start is None:
            continue
        for cid in V.split_list(b.get("member_campaign_ids"), _SEPS):
            y, m = start.year, start.month
            stop = end or ctx.snapshot or ctx.period_end or start
            while (y, m) <= (stop.year, stop.month):
                out.setdefault((cid, y, m), []).append({"budget_id": b.get("budget_id"), "amount": amt})
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _budget_context(ctx, model) -> None:
    """Steps 3/5: historical budget amounts per campaign month; flat budgets are legitimate."""
    chk = ctx.check("budget_context", "Historical budget context",
                    {BUDGETS: ["budget_id", "effective_from", "effective_to", "amount", "member_campaign_ids"]})
    if not chk.runnable:
        return
    by = _budgets_by_month(ctx)
    for cid in sorted(model.series if model else {}):
        amounts = [(f"{y}-{m:02d}", by.get((cid, y, m))) for (y, m) in sorted(model.series[cid])]
        changes = [a for a, b in zip(amounts, amounts[1:]) if a[1] != b[1]]
        missing = [k for k, v in amounts if not v]
        chk.observe(f"Campaign {cid}: budget amounts per month", campaign_id=cid, budget_changes=len(changes),
                    months_without_budget_history=missing,
                    note="spend/volume shifts may reflect budget or capacity, not demand")
        if missing:
            chk.partial(f"campaign {cid}: {len(missing)} months without budget history")


def _is_context(ctx) -> None:
    """Step 5: IS series with censoring preserved; not evidence of competition."""
    chk = ctx.check("is_context", "Impression share context (censoring preserved)",
                    {MONTHLY: ["campaign_id", "year_month", "search_is_if_available", "is_censoring"]})
    if not chk.runnable:
        return
    series: dict[str, list] = {}
    for r in sorted(ctx.rows(MONTHLY), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("year_month")))):
        raw = r.get("search_is_if_available")
        series.setdefault(_s(r.get("campaign_id")), []).append(
            {"year_month": r.get("year_month"), "search_is": ctx.rate(raw), "raw": raw,
             "is_censoring": r.get("is_censoring")})
    for cid in sorted(series):
        chk.observe(f"Campaign {cid}: IS series (not evidence of competition)", campaign_id=cid, series=series[cid])


def verify(ctx, item, decision) -> list[str]:
    """Rules: material_goal_risk must cite the stated goal (proposal.goal_ref)."""
    if decision.get("outcome") == "material_goal_risk" and not (decision.get("proposal") or {}).get("goal_ref"):
        return ["material_goal_risk needs proposal.goal_ref naming the stated client goal"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
