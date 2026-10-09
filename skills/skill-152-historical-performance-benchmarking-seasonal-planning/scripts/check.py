"""check.py — skill-152 deterministic seasonal benchmarks, YoY comparability and cap-bounded scenarios.

exports: SKILL | VERSION | PLAN | DAILY | BUDGETS | ADVERSE | run(ctx) -> None
used_by: skills/skill-152-historical-performance-benchmarking-seasonal-planning/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Plan = external/seasonal_forecast_plan; upcoming = end_at unknown or >= ctx.as_of. Prior occurrences are past
         plan rows sharing the SAME event_id (actual moving-holiday dates, newest = Y-1, next = Y-2); missing ones fall
         back to a 364-day weekday-aligned shift flagged as partial. Never join events or campaigns by name.
         Pooled campaigns = event campaign_id ∪ historical_campaign_mapping IDs (split on ';' '|' ','), each
         (campaign_id, date) row counted once; duplicate grain invalidates that window.
         Rates come from pooled sums with gates: CTR min_impressions, CVR/CPC min_clicks, CPA/ROAS min_conversions,
         applied to BOTH sides. YoY only when both windows are date-complete, duplicate-free, same non-empty goal_id set,
         same single conversion_date_basis, every row mature (maturity column and date <= snapshot - lag) and
         ctx.mature is True. Unknown cells make that sum unknown (None), never 0.
         Client goal metric: ROAS when profile.campaign_objectives[cid].target_roas or campaigns.target_roas > 0, else
         CPA when ctx.params.target_cpa(cid) resolves; otherwise no efficiency verdict (partial).
         ADVERSE = 0.20 (recipe heuristic): CPA +>20% or ROAS ->20% on comparable windows → Warning; declared
         structural_breaks/tracking_basis_changes route to ai_review with a provisional Info instead.
         Forecast: clicks = Y-1 pooled event clicks × (1 + numeric growth_assumptions); spend/conv/value from supplied
         low;base;high marginal_cpc_range / marginal_cvr_range / marginal_value_range (value per conversion). Base spend
         > proposed_cap on an approved row → Warning. Plan money is in account currency units (V.num, not micros).
         Missing growth model or ranges on a plan row → Info; absent columns → skipped/partial, never a finding.
         Budget utilization only for days with exactly one covering benchmark_budget_history row and a known cost row
         for EVERY member campaign; each campaign-day cost is counted once per budget. Lost IS is reported, not pooled.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
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

SKILL = "skill-152-historical-performance-benchmarking-seasonal-planning"
VERSION = "1.0.0"

PLAN = "external/seasonal_forecast_plan"
DAILY = "custom/seasonal_benchmark_daily"
BUDGETS = "custom/benchmark_budget_history"
ADVERSE = 0.20
PLAN_KEY = ["event_id", "campaign_id", "start_at", "end_at", "approval_status"]
DAILY_NEEDS = ["campaign_id", "date", "goal_id", "impressions", "clicks", "cost", "conversions", "conversion_value",
               "conversion_date_basis", "maturity"]
FORECAST_COLS = ["proposed_cap", "growth_assumptions", "marginal_cpc_range", "marginal_cvr_range",
                 "marginal_value_range"]
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
_MATURE = {"mature", "true", "yes", "complete", "final"}
_IMMATURE = {"immature", "false", "no", "pending", "provisional", "incomplete"}


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _ranges(v) -> list[tuple] | None:
    out = []
    for part in V.split_list(v, (";", "|", ",")):
        bits = part.split("..") if ".." in part else part.split("/")
        a, b = (V.parse_date(bits[0].strip()), V.parse_date(bits[1].strip())) if len(bits) == 2 else (None, None)
        if a is None or b is None or b < a:
            return None
        out.append((a, b))
    return out


def _triple(v, parse) -> tuple | None:
    """low;base;high (or low..base..high) → ordered 3-tuple, else None."""
    parts = V.split_list(v, (";", "|"))
    if len(parts) == 1 and ".." in parts[0]:
        parts = [p.strip() for p in parts[0].split("..")]
    vals = [parse(p) for p in parts]
    if len(vals) != 3 or any(x is None or x < 0 for x in vals) or not vals[0] <= vals[1] <= vals[2]:
        return None
    return tuple(vals)


def _win(w) -> str:
    return f"{w[0]}..{w[1]}"


class _Plan:
    """Parsed plan rows and aligned windows."""

    def __init__(self, ctx):
        t = ctx.table(PLAN)
        self.has_mapping = "historical_campaign_mapping" in t.columns
        self.rows = []
        for i, r in enumerate(t.rows):
            self.rows.append({"line": i + 2, "event_id": _s(r.get("event_id")), "campaign_id": _s(r.get("campaign_id")),
                              "start": V.parse_date(r.get("start_at")), "end": V.parse_date(r.get("end_at")),
                              "approved": _s(r.get("approval_status")).lower() == "approved", "raw": r})
        self.rows.sort(key=lambda e: (e["event_id"], e["campaign_id"], str(e["start"]), e["line"]))
        self.upcoming = [e for e in self.rows if e["end"] is None or e["end"] >= ctx.as_of]
        for e in self.upcoming:
            e["camps"] = sorted({e["campaign_id"]} | set(V.split_list(e["raw"].get("historical_campaign_mapping"),
                                                                       (";", "|", ","))))
            e["priors"], e["method"] = self._priors(e)
            e["normal"] = _ranges(e["raw"].get("normal_baseline_dates"))

    def _priors(self, e) -> tuple[list[tuple], str]:
        if e["start"] is None or e["end"] is None:
            return [], "event dates unknown"
        past = sorted({(p["start"], p["end"]) for p in self.rows if p["event_id"] == e["event_id"] and p["start"]
                       and p["end"] and p["end"] < e["start"]}, reverse=True)[:2]
        method = "actual prior dates of the same event_id"
        while len(past) < 2:
            ref = past[-1] if past else (e["start"], e["end"])
            past.append((ref[0] - timedelta(days=364), ref[1] - timedelta(days=364)))
            method = "364-day weekday-aligned shift for missing prior occurrence(s); moving-holiday alignment unverified"
        return past, method


class _Daily:
    """Index of benchmark daily rows by (campaign_id, date)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.idx: dict = {}
        self.cutoff = ctx.snapshot - timedelta(days=ctx.lag_days) if ctx.snapshot and ctx.lag_days is not None else None
        for r in ctx.rows(DAILY):
            d = V.parse_date(r.get("date"))
            if d is not None:
                self.idx.setdefault((_s(r.get("campaign_id")), d), []).append(r)
        self.cache: dict = {}

    def pool(self, camps, w) -> dict:
        key = (tuple(camps), w)
        if key in self.cache:
            return self.cache[key]
        ctx = self.ctx
        p = {"window": _win(w), "campaigns": list(camps), "rows": 0, "duplicates": 0, "days_total": (w[1] - w[0]).days + 1,
             "goals": set(), "bases": set(), "strategies": set(), "immature_rows": 0, "unknown_maturity_rows": 0,
             "inactive_campaign_rows": 0, **{m: 0.0 for m in METRICS}}
        days = set()
        d = w[0]
        while d <= w[1]:
            for cid in camps:
                rows = self.idx.get((cid, d), [])
                if len(rows) > 1:
                    p["duplicates"] += 1
                for r in rows[:1]:
                    p["rows"] += 1
                    days.add(d)
                    p["goals"].add(_s(r.get("goal_id")) or "(blank)")
                    p["bases"].add(_s(r.get("conversion_date_basis")).lower() or "(blank)")
                    if r.get("strategy_id"):
                        p["strategies"].add(_s(r.get("strategy_id")))
                    if _s(r.get("active_status")).upper() in ("PAUSED", "REMOVED", "INACTIVE", "ENDED"):
                        p["inactive_campaign_rows"] += 1
                    mat = _s(r.get("maturity")).lower()
                    if mat in _IMMATURE or (self.cutoff is not None and d > self.cutoff):
                        p["immature_rows"] += 1
                    elif mat not in _MATURE or self.cutoff is None:
                        p["unknown_maturity_rows"] += 1
                    for m in METRICS:
                        val = (ctx.money if m in ("cost", "conversion_value") else V.num)(r.get(m))
                        p[m] = None if val is None or p[m] is None else p[m] + val
            d += timedelta(days=1)
        p["days_covered"] = len(days)
        p["date_complete"] = len(days) == p["days_total"]
        p["mature"] = p["rows"] > 0 and not p["immature_rows"] and not p["unknown_maturity_rows"]
        for k in ("goals", "bases", "strategies"):
            p[k] = sorted(p[k])
        self.cache[key] = p
        return p


def _rates(ctx, p) -> dict:
    g = {n: ctx.params.get(n).value for n in ("min_impressions", "min_clicks", "min_conversions")}
    ok = lambda v, n: v is not None and g[n] is not None and v >= g[n]
    imp, clk, cost, conv, val = (p[m] for m in METRICS)
    return {"ctr": V.ratio(clk, imp) if ok(imp, "min_impressions") else None,
            "cvr": V.ratio(conv, clk) if ok(clk, "min_clicks") else None,
            "cpc": V.ratio(cost, clk) if ok(clk, "min_clicks") else None,
            "cpa": V.ratio(cost, conv) if ok(conv, "min_conversions") else None,
            "roas": V.ratio(val, cost) if ok(conv, "min_conversions") else None,
            "value_per_conversion": V.ratio(val, conv) if ok(conv, "min_conversions") else None}


def _incomparable(ctx, new, old) -> list[str]:
    why = []
    for side, p in (("new", new), ("old", old)):
        if p["rows"] == 0:
            why.append(f"{side} window {p['window']} has no rows")
            continue
        if not p["date_complete"]:
            why.append(f"{side} window covers {p['days_covered']}/{p['days_total']} days")
        if p["duplicates"]:
            why.append(f"{side} window has {p['duplicates']} duplicate campaign-days")
        if not p["mature"]:
            why.append(f"{side} window maturity not proven ({p['immature_rows']} immature, "
                       f"{p['unknown_maturity_rows']} unknown rows)")
    if not why:
        if new["goals"] != old["goals"] or "(blank)" in new["goals"]:
            why.append(f"goal_id sets differ or blank: {new['goals']} vs {old['goals']}")
        if new["bases"] != old["bases"] or len(new["bases"]) != 1 or "(blank)" in new["bases"]:
            why.append(f"conversion_date_basis differs: {new['bases']} vs {old['bases']}")
    if ctx.mature is not True:
        why.append(f"export maturity {ctx.mature}: {ctx.maturity_note}")
    return why


def _change(new, old) -> float | None:
    r = V.ratio(new, old)
    return None if r is None else r - 1


def _pairs(e) -> list[tuple]:
    out = [("event", e["priors"][0], e["priors"][1])] if len(e["priors"]) == 2 else []
    for w in e["normal"] or []:
        out.append(("normal", w, (w[0] - timedelta(days=364), w[1] - timedelta(days=364))))
    return out


def _goal_metric(ctx, cid) -> tuple[str | None, str]:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    camp = next((r for r in ctx.rows("campaigns") if _s(r.get("id")) == cid), {})
    for src, v in ((f"profile.campaign_objectives[{cid}].target_roas", (obj or {}).get("target_roas")
                    if isinstance(obj, dict) else None), (f"campaigns.target_roas[{cid}]", camp.get("target_roas"))):
        f = V.num(v)
        if f is not None and f > 0:
            return "roas", src
    cpa, src = ctx.params.target_cpa(cid)
    return ("cpa", src) if cpa is not None else (None, src)


def run(ctx) -> None:
    """Run seasonal event benchmarking, YoY efficiency, forecast ranges and budget-utilization checks.

    Rules:   Prior occurrences by event_id only (364-day fallback flagged partial); never join by name. YoY only on
             complete, duplicate-free, same-goal, mature windows with gates on BOTH sides; CPA +>20% or ROAS ->20% →
             Warning, structural/tracking breaks → provisional Info + ai_review. Base spend > proposed_cap → Warning;
             missing growth model/ranges → Info; absent columns → skipped/partial. Unknown cells stay None, never 0.
    """
    align = ctx.check("event_alignment", "Align events by actual dates and comparable weekdays (step 1)",
                      {PLAN: PLAN_KEY})
    steps = (("pooled_benchmarks", "Pooled gated CTR/CVR/CPC/CPA/ROAS per window (step 2)", {DAILY: DAILY_NEEDS}),
             ("yoy_changes", "YoY changes on comparable nonzero baselines (step 3)", {DAILY: DAILY_NEEDS}),
             ("budget_utilization", "Historical budget utilization and reported lost IS (step 4)",
              {DAILY: ["campaign_id", "date", "budget_id", "cost"],
               BUDGETS: ["budget_id", "effective_from", "effective_to", "amount", "member_campaign_ids"]}),
             ("adverse_efficiency", ">20% adverse YoY efficiency against client goal (step 5)", {DAILY: DAILY_NEEDS}),
             ("forecast_scenarios", "Low/base/high scenarios against the approved cap (step 6)",
              {PLAN: ["approval_status"] + FORECAST_COLS}))
    if not align.runnable or ctx.as_of is None:
        if ctx.as_of is None:
            align.skip("as-of date unknown: upcoming vs past events undecidable", ["account:date_range_end"])
        for cid, title, needs in steps:
            ctx.check(cid, title, needs).skip("forecast plan or as-of date unavailable", align.missing)
        return
    plan = _Plan(ctx)
    if not plan.has_mapping:
        align.partial("structural campaign mapping not supplied; only the event campaign_id is pooled",
                      [f"{PLAN}:historical_campaign_mapping"])
    for c in ("normal_baseline_dates", "structural_breaks", "tracking_basis_changes", "evidence_ref"):
        if c not in ctx.table(PLAN).columns:
            align.partial("declared plan column absent", [f"{PLAN}:{c}"])
    for e in plan.upcoming:
        ent = {"event_id": e["event_id"], "campaign_id": e["campaign_id"]}
        if not e["method"].startswith("actual") and e["priors"]:
            align.partial(f"event {e['event_id']}/{e['campaign_id']}: {e['method']}")
        if not e["priors"]:
            align.partial(f"event {e['event_id']}/{e['campaign_id']}: start_at/end_at unknown; no windows aligned")
        if _s(e["raw"].get("normal_baseline_dates")) and e["normal"] is None:
            align.partial(f"event {e['event_id']}: normal_baseline_dates unparseable")
        align.observe(f"Event {e['event_id']} campaign {e['campaign_id']} aligned windows", **ent,
                      event_window=f"{e['start']}..{e['end']}", y1=_win(e["priors"][0]) if e["priors"] else None,
                      y2=_win(e["priors"][1]) if len(e["priors"]) > 1 else None, alignment=e["method"],
                      pooled_campaigns=e["camps"], normal=[_win(w) for w in e["normal"] or []],
                      weekday_match=bool(e["priors"]) and e["start"].weekday() == e["priors"][0][0].weekday())
    if not plan.upcoming:
        for cid, title, _ in steps:
            ctx.check(cid, title, applicable=False, na_reason="no upcoming events in the forecast plan")
        return
    checks = [ctx.check(cid, title, needs) for cid, title, needs in steps]
    t = ctx.table(DAILY)
    daily = _Daily(ctx) if t is not None and not t.missing(["campaign_id", "date"]) else None
    _pooled(ctx, checks[0], plan, daily)
    _yoy(ctx, checks[1], plan, daily)
    _budgets(ctx, checks[2], plan)
    _adverse(ctx, checks[3], plan, daily)
    _forecast(ctx, checks[4], plan, daily)


def _gates(ctx) -> dict:
    return {n: {"value": r.value, "source": r.source} for n in ("min_impressions", "min_clicks", "min_conversions")
            for r in [ctx.params.get(n)]}


def _pooled(ctx, chk, plan, daily) -> None:
    if not chk.runnable:
        return
    for e in plan.upcoming:
        wins = list(zip(("y1_event", "y2_event"), e["priors"]))
        for kind, new_w, old_w in _pairs(e):
            if kind == "normal":
                wins += [("normal", new_w), ("normal_prior", old_w)]
        for label, w in wins:
            p = daily.pool(e["camps"], w)
            chk.observe(f"Event {e['event_id']} {label} benchmark {_win(w)}", event_id=e["event_id"],
                        campaign_id=e["campaign_id"], label=label, pooled={k: p[k] for k in sorted(p)},
                        rates=_rates(ctx, p), gates=_gates(ctx))
            if p["duplicates"]:
                chk.partial(f"event {e['event_id']} {label}: duplicate campaign-day rows; window excluded from YoY")


def _yoy(ctx, chk, plan, daily) -> None:
    if not chk.runnable:
        return
    complete = ctx.table(DAILY).complete is True
    for e in plan.upcoming:
        ent = {"event_id": e["event_id"], "campaign_id": e["campaign_id"]}
        if not e["priors"]:
            chk.partial(f"event {e['event_id']}: no aligned prior window")
            continue
        y1 = daily.pool(e["camps"], e["priors"][0])
        if y1["rows"] == 0:
            if complete:
                chk.finding("no_comparable_prior_period", "Info", ent,
                            f"No benchmark rows for campaigns {e['camps']} in prior event window {y1['window']}",
                            evidence={"window": y1["window"], "alignment": e["method"], "pooled_campaigns": e["camps"],
                                      "file": ctx.table(DAILY).filename},
                            recommendation="Plan from explicit assumptions and prerequisites only; history is unknown.",
                            uncertainty="No history means unknown performance, not a defect.")
            else:
                chk.partial(f"event {e['event_id']}: no rows in {y1['window']} but daily file not certified complete")
            continue
        for kind, new_w, old_w in _pairs(e):
            new, old = daily.pool(e["camps"], new_w), daily.pool(e["camps"], old_w)
            if kind == "event" and old["rows"] == 0:
                chk.observe(f"Event {e['event_id']}: single-year benchmark only (no {old['window']} rows)", **ent,
                            y1=new["window"])
                continue
            why = _incomparable(ctx, new, old)
            rn, ro = _rates(ctx, new), _rates(ctx, old)
            changes = {} if why else {m: _change(rn[m], ro[m]) for m in ("ctr", "cvr", "cpc", "cpa", "roas")}
            chk.observe(f"Event {e['event_id']} {kind} YoY {new['window']} vs {old['window']}", **ent, kind=kind,
                        comparable=not why, exclusions=why, changes=changes, new_rates=rn, old_rates=ro,
                        note="change = new/old - 1 on gated pooled rates; undefined when either side ungated or zero")


def _adverse(ctx, chk, plan, daily) -> None:
    if not chk.runnable:
        return
    if ctx.mature is not True:
        chk.partial(f"efficiency verdicts disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    min_conv = ctx.params.get("min_conversions")
    for e in plan.upcoming:
        metric, msrc = _goal_metric(ctx, e["campaign_id"])
        if metric is None:
            chk.partial(f"event {e['event_id']}/{e['campaign_id']}: client goal metric unresolved ({msrc})")
            continue
        breaks = {c: _s(e["raw"].get(c)) for c in ("structural_breaks", "tracking_basis_changes")
                  if _s(e["raw"].get(c))}
        for kind, new_w, old_w in _pairs(e):
            new, old = daily.pool(e["camps"], new_w), daily.pool(e["camps"], old_w)
            if new["rows"] == 0 or old["rows"] == 0:
                continue
            why = _incomparable(ctx, new, old)
            vn, vo = _rates(ctx, new)[metric], _rates(ctx, old)[metric]
            if why or vn is None or vo is None or vo == 0:
                chk.observe(f"Event {e['event_id']} {kind}: no {metric.upper()} verdict", event_id=e["event_id"],
                            campaign_id=e["campaign_id"], exclusions=why, new=vn, old=vo,
                            min_conversions=min_conv.value)
                continue
            change = _change(vn, vo)
            adverse = change > ADVERSE if metric == "cpa" else change < -ADVERSE
            ent = {"event_id": e["event_id"], "campaign_id": e["campaign_id"], "window": new["window"],
                   "baseline": old["window"]}
            ev = {"metric": metric, "metric_source": msrc, "new": vn, "old": vo, "change": change, "threshold": ADVERSE,
                  "new_pool": {m: new[m] for m in METRICS}, "old_pool": {m: old[m] for m in METRICS},
                  "goals": new["goals"], "basis": new["bases"], "min_conversions": min_conv.value,
                  "min_conversions_source": min_conv.source, "pooled_campaigns": e["camps"], "currency": ctx.currency,
                  "declared_breaks": breaks, "evidence_ref": e["raw"].get("evidence_ref")}
            chk.observe(f"Event {e['event_id']} {kind} {metric.upper()} YoY {change:+.4f}", **ent, adverse=adverse)
            if not adverse:
                continue
            summary = (f"{metric.upper()} moved {change:+.1%} ({vo:.4g} → {vn:.4g}) between {old['window']} and "
                       f"{new['window']} for campaigns {e['camps']}")
            rec = "Review drivers (auction, offer, mix) before planning; heuristic, not proof of market shift."
            unc = "Observational comparison; not causal."
            if not breaks:
                chk.finding("adverse_yoy_efficiency", "Warning", ent, summary, evidence=ev,
                            calculation={"change": f"{metric} new/old - 1", "gate": "conversions >= min_conversions"},
                            recommendation=rec, uncertainty=unc, owner=_s(e["raw"].get("owner")) or None)
                continue
            prov = chk.finding("adverse_yoy_efficiency", "Info", ent, summary + " (declared break pending review)",
                               evidence=ev, recommendation=rec, uncertainty=unc, owner=_s(e["raw"].get("owner")) or None)
            chk.review("adverse_yoy_efficiency", ent,
                       f"Do the declared structural/tracking changes {breaks} invalidate this {metric.upper()} comparison?",
                       evidence=ev,
                       outcomes={"comparable": {"severity": "Warning", "recommendation": rec},
                                 "break_invalidates": {"severity": "Info", "recommendation":
                                                       "Treat as no comparable prior period; use assumptions only."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the plan owner for dates."}},
                       guidance="Only declared break dates/scopes overlapping either window can invalidate it.",
                       provisional=prov)


def _budgets(ctx, chk, plan) -> None:
    if not chk.runnable:
        return
    hist: dict = {}
    for r in ctx.rows(BUDGETS):
        hist.setdefault(_s(r.get("budget_id")), []).append(r)
    idx: dict = {}
    for r in ctx.rows(DAILY):
        d = V.parse_date(r.get("date"))
        if d is not None:
            idx.setdefault((_s(r.get("campaign_id")), d), []).append(r)
    lost_col = "budget_lost_is_if_supported" in ctx.table(DAILY).columns
    if not lost_col:
        chk.partial("lost IS not reported", [f"{DAILY}:budget_lost_is_if_supported"])
    for e in plan.upcoming:
        for label, w in zip(("y1_event", "y2_event"), e["priors"]):
            budget_ids = set()
            lost = []
            d = w[0]
            while d <= w[1]:
                for cid in e["camps"]:
                    for r in idx.get((cid, d), [])[:1]:
                        if r.get("budget_id"):
                            budget_ids.add(_s(r.get("budget_id")))
                        v = ctx.rate(r.get("budget_lost_is_if_supported")) if lost_col else None
                        if v is not None:
                            lost.append(v)
                d += timedelta(days=1)
            for bid in sorted(budget_ids):
                spend = amount = 0.0
                used = uncovered = ambiguous = unknown = 0
                members_seen = set()
                d = w[0]
                while d <= w[1]:
                    cover = [h for h in hist.get(bid, []) if V.parse_date(h.get("effective_from"))
                             and V.parse_date(h.get("effective_from")) <= d
                             and (V.parse_date(h.get("effective_to")) is None or d <= V.parse_date(h.get("effective_to")))]
                    d, day = d + timedelta(days=1), d
                    if not cover:
                        uncovered += 1
                        continue
                    if len(cover) > 1:
                        ambiguous += 1
                        continue
                    amt = ctx.money(cover[0].get("amount"))
                    members = sorted(set(V.split_list(cover[0].get("member_campaign_ids"), (";", "|", ","))))
                    costs = []
                    for m in members:
                        rows = idx.get((m, day), [])
                        costs.append(ctx.money(rows[0].get("cost")) if len(rows) == 1 else None)
                    if amt is None or not members or any(c is None for c in costs):
                        unknown += 1
                        continue
                    members_seen.update(members)
                    spend += sum(costs)
                    amount += amt
                    used += 1
                days = (w[1] - w[0]).days + 1
                if used < days:
                    chk.partial(f"budget {bid} {label}: {days - used}/{days} days excluded "
                                f"(uncovered {uncovered}, overlapping {ambiguous}, unknown member cost/amount {unknown})")
                chk.observe(f"Event {e['event_id']} {label} budget {bid} utilization", event_id=e["event_id"],
                            campaign_id=e["campaign_id"], budget_id=bid, window=_win(w), days_used=used,
                            days_total=days, spend=spend if used else None, budget_amount=amount if used else None,
                            utilization=V.ratio(spend, amount) if used else None, members=sorted(members_seen),
                            note="each member campaign-day cost counted once; daily amounts from dated history")
            chk.observe(f"Event {e['event_id']} {label} reported budget-lost IS", event_id=e["event_id"],
                        window=_win(w), reported_days=len(lost), min=min(lost) if lost else None,
                        max=max(lost) if lost else None, note="reported values only; not pooled or averaged")


def _forecast(ctx, chk, plan, daily) -> None:
    if not chk.runnable:
        return
    if daily is None:
        chk.partial("historical volume unavailable: scenario clicks not computable",
                    [f"{DAILY} (file)"] if ctx.table(DAILY) is None
                    else [f"{DAILY}:{c}" for c in ctx.table(DAILY).missing(["campaign_id", "date"])])
    for e in plan.upcoming:
        r = e["raw"]
        ent = {"event_id": e["event_id"], "campaign_id": e["campaign_id"]}
        y1 = daily.pool(e["camps"], e["priors"][0]) if daily and e["priors"] else None
        hist = {"y1_window": y1["window"], "y1_pool": {m: y1[m] for m in METRICS}, "y1_rates": _rates(ctx, y1)} \
            if y1 else {}
        missing = [c for c in FORECAST_COLS[1:] if not _s(r.get(c))]
        if missing:
            chk.finding("unspecified_growth_model", "Info", ent,
                        f"Event {e['event_id']} plan lacks {', '.join(missing)}: no forecast produced",
                        evidence={"missing": missing, "proposed_cap": r.get("proposed_cap"), **hist},
                        recommendation="Supply growth and marginal CPC/CVR/value assumptions; until then use "
                                       "historical ranges and prerequisites only.",
                        uncertainty="Absent assumptions mean unknown response, not a rejected budget.",
                        owner=_s(r.get("owner")) or None)
            continue
        growth = V.rate(r.get("growth_assumptions"), "fraction")
        cpc = _triple(r.get("marginal_cpc_range"), V.num)
        cvr = _triple(r.get("marginal_cvr_range"), lambda x: V.rate(x, "fraction"))
        vpc = _triple(r.get("marginal_value_range"), V.num)
        bad = [n for n, v in (("growth_assumptions", growth), ("marginal_cpc_range", cpc),
                              ("marginal_cvr_range", cvr), ("marginal_value_range", vpc)) if v is None]
        if bad:
            chk.partial(f"event {e['event_id']}: {', '.join(bad)} not numeric/ordered low;base;high; no arithmetic")
            continue
        if y1 is None or not y1["date_complete"] or y1["duplicates"] or y1["clicks"] is None:
            chk.partial(f"event {e['event_id']}: Y-1 click volume not date-complete/known; scenarios not computed")
            continue
        clicks = y1["clicks"] * (1 + growth)
        scen = {name: {"clicks": clicks, "spend": clicks * cpc[i], "conversions": clicks * cvr[i],
                       "value": clicks * cvr[i] * vpc[i]} for i, name in enumerate(("low", "base", "high"))}
        cap = V.num(r.get("proposed_cap"))
        chk.observe(f"Event {e['event_id']} scenarios", **ent, scenarios=scen, cap=cap, growth=growth,
                    assumptions={"cpc": cpc, "cvr": cvr, "value_per_conversion": vpc}, **hist,
                    formula="clicks = Y-1 clicks × (1 + growth); spend = clicks × CPC; conv = clicks × CVR; "
                            "value = conv × value per conversion")
        if cap is None:
            chk.partial(f"event {e['event_id']}: proposed_cap blank; cap conflict not assessed")
            continue
        if scen["base"]["spend"] > cap and e["approved"]:
            chk.finding("forecast_exceeds_approved_cap", "Warning", ent,
                        f"Base scenario spend {scen['base']['spend']:.2f} {ctx.currency} exceeds the approved cap "
                        f"{cap:.2f} for event {e['event_id']}",
                        evidence={"scenarios": scen, "cap": cap, "approval_status": r.get("approval_status"),
                                  "evidence_ref": r.get("evidence_ref"), **hist},
                        calculation={"base_spend": "Y-1 clicks × (1 + growth) × base marginal CPC"},
                        recommendation="Reconcile the growth/CPC assumptions with the approved cap before any "
                                       "budget request; the cap binds, not the forecast.",
                        uncertainty="Scenario arithmetic from supplied assumptions; not a prediction.",
                        owner=_s(r.get("owner")) or None)
        elif scen["high"]["spend"] > cap or scen["base"]["spend"] > cap:
            chk.observe(f"Event {e['event_id']}: cap {cap:g} binds in the "
                        f"{'base' if scen['base']['spend'] > cap else 'high'} scenario", **ent,
                        approved=e["approved"])


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
