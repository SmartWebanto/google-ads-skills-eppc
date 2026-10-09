"""check.py — skill-169 deterministic multi-account portfolio KPIs, offline detection and dated-rate rollup.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-169-account-portfolio-summary/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #94 Account Summary Report (Google) — clean-room reimplementation of per-account period KPIs; email/sheet refused
         index #95 Four simple charts per account (Aaron Weiner) — daily series feed deltas/offline here; chart rendering refused
         index #96 Kratu KPIs per account in MCC (Google) — per-account KPI rows; composite score and fixed flag thresholds refused
         index #97 Large Manager Report Tool (Google) — multi-account KPI rows; BigQuery/Sheets transfer refused
         index #98/#99 MCC spend converted to a default currency (Corey Jansen) — conversion only with supplied dated rates; live FX fetch refused
         index #55 IS metrics for all accounts in MCC (martididonato) — eligible-weighted IS/lost IS and top lost campaigns; '--' kept unknown, never 0
         index #19 Alert when account is down (Frederick Vallaeys) — zero-serving complete days vs the account's own baseline; hourly polling/email refused
rules:   Money is NEVER summed across currencies or periods. Conversion uses only external/exchange_rates rows with
         date == the account's report end, from == account currency, to == profile.portfolio.reporting_currency,
         one positive rate and a non-empty source; a converted total needs EVERY account converted and equal periods.
         Multi-account: adsrun.cli partitions per account, so per-account checks use ctx only; portfolio_totals and
         currency_conversion reload the unpartitioned export read-only and run ONLY in the lowest customer ID's result
         (others not_applicable pointing there). Files read that way are hashed into inputs.portfolio_files (fingerprint).
         Offline: known impressions == 0 AND cost == 0 on consecutive complete days ending at the latest complete day
         <= ctx.as_of. Warning only if run >= portfolio.offline_min_days (default 1), run > longest zero run in a complete
         portfolio.offline_baseline_days baseline (default 28) and baseline impressions >= min_impressions; else Info.
         Missing day rows are unknown, never zero. Critical ('unplanned_stop_evidenced') or 'planned_pause' only via
         review with proposal.evidence_ref naming a row of external/account_status_evidence.csv (evidence_ref,
         customer_id, status_type unplanned_stop|planned_pause, cause, from_date, to_date, source) for THIS account whose
         status_type matches the outcome, window overlaps the zero run, and cause+source are non-empty. Campaign status
         rows prove status only, never intent or cause.
         CPA/ROAS only when every converting campaign shares one declared goal set (ctx.goal_ids); conversion deltas need
         ctx.mature True; rate deltas need BOTH periods to pass min_impressions / min_clicks / min_conversions.
         IS: eligible = impressions / IS per row; withheld/censored IS stays unknown and marks the summary partial.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes4 | new recipe: portfolio summary check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | offline evidence_ref must be the reviewed account's status row
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | status proof only from owner/billing/policy evidence rows
"""
from __future__ import annotations

import math
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
from adsrun.context import account_ids  # noqa: E402
from adsrun.evidence import load_evidence  # noqa: E402

SKILL = "skill-169-account-portfolio-summary"
VERSION = "1.0.0"

METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
KPI_NEEDS = {"campaign_metrics": ["campaign_id", "impressions", "clicks", "cost", "conversions"]}
DAILY = "custom/account_daily_metrics"
RATES = "external/exchange_rates"
RATE_COLS = ["date", "from", "to", "rate", "source"]
_SEGMENTS = ("date", "device", "ad_network_type", "network", "segment", "month", "week")
_LOST = {"budget": ("search_budget_lost_is", "search_budget_lost_impression_share"),
         "rank": ("search_rank_lost_is", "search_rank_lost_impression_share")}
_EVIDENCE_OUTCOMES = ("unplanned_stop_evidenced", "planned_pause")


# ----------------------------------------------------------------------------- shared helpers
def _cust_col(columns) -> str | None:
    return next((c for c in ("customer_id", "account_id") if c in columns), None)


def _money(v, unit) -> float | None:
    return V.money(v, unit or "currency")


def _totals(rows: list[dict], columns: list[str], unit) -> tuple[dict | None, list[str]]:
    """Sum rows once per grain (campaign_id + explicit segment columns).

    Rules:   duplicate grain → (None, problem): a segmented or repeated export would double count.
             A metric with any unknown cell is None (unknown), never a lower bound presented as a total.
    """
    seg = [c for c in _SEGMENTS if c in columns]
    seen, problems = set(), []
    sums = {m: 0.0 for m in METRICS}
    unknown = {m: 0 for m in METRICS}
    for r in rows:
        key = (str(r.get("campaign_id") or ""),) + tuple(str(r.get(c) or "") for c in seg)
        if key in seen:
            return None, [f"duplicate campaign_metrics grain {key}: segmented or repeated rows would double count"]
        seen.add(key)
        for m in METRICS:
            if m not in columns:
                unknown[m] += 1
                continue
            v = _money(r.get(m), unit) if m in ("cost", "conversion_value") else V.num(r.get(m))
            if v is None:
                unknown[m] += 1
            else:
                sums[m] += v
    out = {m: (None if unknown[m] else sums[m]) for m in METRICS}
    for m in METRICS:
        if unknown[m] and m in columns:
            problems.append(f"{unknown[m]} campaign_metrics rows with unknown {m}: total unknown")
        elif m not in columns:
            problems.append(f"campaign_metrics:{m} not supplied")
    out["rows"] = len(seen)
    return out, problems


def _goal_basis(ctx, rows) -> tuple[list[str] | None, str]:
    """Single declared goal set shared by every converting campaign, else (None, reason)."""
    sets = {}
    for r in rows:
        conv, val = V.num(r.get("conversions")), V.num(r.get("conversion_value"))
        if not ((conv or 0) > 0 or (val or 0) > 0):
            continue
        cid = str(r.get("campaign_id"))
        sets[cid] = tuple(sorted(ctx.goal_ids(cid)))
    if not sets:
        return None, "no converting campaigns"
    undeclared = sorted(c for c, g in sets.items() if not g)
    if undeclared:
        return None, f"goal_ids undeclared for converting campaigns {undeclared}"
    distinct = sorted(set(sets.values()))
    if len(distinct) > 1:
        return None, f"converting campaigns use different goal sets {[list(g) for g in distinct]}"
    return list(distinct[0]), "every converting campaign shares one declared goal set"


def _portfolio_profile(ctx) -> dict:
    p = ctx.profile.get("portfolio")
    return p if isinstance(p, dict) else {}


def _int_setting(ctx, key: str, default: int, minimum: int) -> tuple[int | None, str]:
    raw = _portfolio_profile(ctx).get(key)
    if raw is None:
        return default, f"recipe default {default}"
    f = V.num(raw)
    if f is None or not math.isfinite(f) or f != int(f) or f < minimum:
        return None, f"invalid portfolio.{key} {raw!r} (integer >= {minimum} required)"
    return int(f), f"profile.portfolio.{key}"


def _daily_days(ctx, check) -> dict | None:
    """date → row for this account's complete days; None when the grain is unusable."""
    t = ctx.table(DAILY)
    col = _cust_col(t.columns)
    days, bad_dates, incomplete = {}, 0, []
    for r in t.rows:
        if col and ctx.account_id and str(r.get(col) or "") != str(ctx.account_id):
            continue
        d = V.parse_date(r.get("date"))
        if d is None:
            bad_dates += 1
            continue
        if "complete_day" in t.columns and V.boolean(r.get("complete_day")) is not True:
            incomplete.append(d)
            continue
        if d in days:
            check.partial(f"{t.filename}: duplicate rows for {d}; remove segments (one account/date row)")
            return None
        days[d] = r
    if bad_dates:
        check.partial(f"{t.filename}: {bad_dates} rows with unparseable date ignored")
    if incomplete:
        check.partial(f"{t.filename}: {len(incomplete)} days not marked complete_day=true excluded "
                      f"({min(incomplete)}..{max(incomplete)})")
    return days


def _window_sums(ctx, days: dict, start, end) -> tuple[dict | None, list]:
    n = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(n)]
    missing = [d for d in dates if d not in days]
    if missing:
        return None, missing
    sums = {}
    for m in METRICS:
        vals = [(ctx.money(days[d].get(m)) if m in ("cost", "conversion_value") else V.num(days[d].get(m)))
                for d in dates]
        sums[m] = None if any(v is None for v in vals) else sum(vals)
    sums["days"] = n
    return sums, []


# ----------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Declare and run steps 1-6 for ctx's account.

    Rules:   Per-account steps read only ctx (partitioned by cli); steps 5-6 follow _portfolio's anchor rule.
    """
    min_impr = ctx.params.get("min_impressions")
    min_clicks = ctx.params.get("min_clicks")
    min_conv = ctx.params.get("min_conversions")
    goal_basis = _account_kpis(ctx, min_impr, min_clicks, min_conv)
    _impression_share(ctx, min_impr)
    _offline(ctx, min_impr)
    _period_over_period(ctx, goal_basis, min_impr, min_clicks, min_conv)
    _portfolio(ctx)


def _account_kpis(ctx, min_impr, min_clicks, min_conv):
    chk = ctx.check("account_kpis", "Per-account KPIs in native currency", KPI_NEEDS)
    if not chk.runnable:
        return None
    t = ctx.table("campaign_metrics")
    rows = t.rows
    tot, problems = _totals(rows, t.columns, ctx.money_unit)
    for p in problems:
        chk.partial(p)
    if tot is None:
        return None
    basis, basis_note = _goal_basis(ctx, rows)
    if basis is None:
        chk.partial(f"CPA/ROAS not computed: {basis_note}")
    ctr = V.ratio(tot["clicks"], tot["impressions"])
    kpis = {
        "customer_id": ctx.account_id, "currency": ctx.currency, "period": [ctx.period_start, ctx.period_end],
        "campaign_rows": tot["rows"], **{m: tot[m] for m in METRICS},
        "ctr": ctr, "avg_cpc": V.ratio(tot["cost"], tot["clicks"]),
        "conversion_rate": V.ratio(tot["conversions"], tot["clicks"]),
        "cpa": V.ratio(tot["cost"], tot["conversions"]) if basis else None,
        "roas": V.ratio(tot["conversion_value"], tot["cost"]) if basis else None,
        "goal_basis": basis, "goal_note": basis_note,
        "maturity": {"mature": ctx.mature, "note": ctx.maturity_note},
        "samples": {"min_impressions": min_impr.value, "min_clicks": min_clicks.value,
                    "min_conversions": min_conv.value,
                    "impressions_ok": _gate(tot["impressions"], min_impr.value),
                    "clicks_ok": _gate(tot["clicks"], min_clicks.value),
                    "conversions_ok": _gate(tot["conversions"], min_conv.value)},
    }
    if ctx.mature is not True:
        chk.partial(f"conversion KPIs descriptive only: {ctx.maturity_note}")
    chk.observe(f"Account {ctx.account_id} KPIs ({ctx.currency}, {ctx.period_start}..{ctx.period_end})", **kpis)
    return basis


def _gate(value, threshold) -> bool | None:
    if value is None or threshold is None:
        return None
    return value >= threshold


def _impression_share(ctx, min_impr) -> None:
    chk = ctx.check("impression_share_summary", "Eligible-weighted Search impression share summary",
                    {"campaign_metrics": ["campaign_id", "impressions", "search_impression_share"]})
    if not chk.runnable:
        return
    t = ctx.table("campaign_metrics")
    lost_cols = {k: next((c for c in names if c in t.columns), None) for k, names in _LOST.items()}
    for k, c in lost_cols.items():
        if c is None:
            chk.partial(f"{k}-lost IS not supplied", [f"campaign_metrics:{_LOST[k][0]}"])
    channel = {str(r.get("id")): r.get("channel_type") for r in ctx.rows("campaigns")}
    groups: dict[str, dict] = {}
    censored, invalid, unknown_impr = [], [], []
    seg = [c for c in _SEGMENTS if c in t.columns]
    seen = set()
    for r in sorted(t.rows, key=lambda r: str(r.get("campaign_id"))):
        cid = str(r.get("campaign_id"))
        key = (cid,) + tuple(str(r.get(c) or "") for c in seg)
        if key in seen:
            chk.partial(f"duplicate campaign_metrics grain {key}: IS summary stopped")
            return
        seen.add(key)
        impr = V.num(r.get("impressions"))
        raw_is = r.get("search_impression_share")
        if raw_is is None and impr is not None:
            continue  # channel does not report Search IS
        share = ctx.rate(raw_is)
        if impr is None:
            unknown_impr.append(cid)
            continue
        if impr == 0:
            continue
        if share is None:
            censored.append(cid)
            continue
        if not (0 < share <= 1):
            invalid.append(cid)
            continue
        ch = str(r.get("channel_type") or channel.get(cid) or "UNKNOWN").upper()
        g = groups.setdefault(ch, {"impr": 0.0, "elig": 0.0, "budget": [0.0, 0.0], "rank": [0.0, 0.0], "rows": []})
        elig = impr / share
        g["impr"] += impr
        g["elig"] += elig
        row = {"campaign_id": cid, "impressions": impr, "search_impression_share": share}
        for k, col in lost_cols.items():
            lv = ctx.rate(r.get(col)) if col else None
            if lv is not None and 0 <= lv <= 1:
                g[k][0] += elig * lv
                g[k][1] += elig
                row[f"{k}_lost_is"] = lv
        g["rows"].append(row)
    if censored:
        chk.partial(f"withheld/censored impression share for campaigns {sorted(set(censored))}: summary covers reported rows only")
    if invalid:
        chk.partial(f"impression share outside (0,1] for campaigns {sorted(set(invalid))}: excluded")
    if unknown_impr:
        chk.partial(f"unknown impressions for campaigns {sorted(set(unknown_impr))}: excluded")
    if "UNKNOWN" in groups:
        chk.partial("channel_type unknown for some campaigns (campaign_metrics/campaigns:channel_type)")
    if not groups:
        chk.observe("No campaign with a reported impression share", customer_id=ctx.account_id)
        return
    for ch in sorted(groups):
        g = groups[ch]
        qualified = [x for x in g["rows"] if min_impr.value is not None and x["impressions"] >= min_impr.value]
        top = {}
        for k in ("budget", "rank"):
            cands = [x for x in qualified if x.get(f"{k}_lost_is") is not None]
            if cands:
                best = max(cands, key=lambda x: (x[f"{k}_lost_is"], x["campaign_id"]))
                top[k] = {"campaign_id": best["campaign_id"], "lost_is": best[f"{k}_lost_is"]}
        chk.observe(f"Account {ctx.account_id} {ch} impression share (eligible-weighted)",
                    customer_id=ctx.account_id, channel=ch, campaigns=len(g["rows"]),
                    impressions=g["impr"], eligible_impressions_est=g["elig"],
                    impression_share=V.ratio(g["impr"], g["elig"]),
                    budget_lost_is=V.ratio(g["budget"][0], g["budget"][1]),
                    rank_lost_is=V.ratio(g["rank"][0], g["rank"][1]),
                    sample_ok=_gate(g["impr"], min_impr.value), min_impressions=min_impr.value,
                    top_lost_campaigns=top,
                    formula="eligible = impressions / IS per campaign row; IS = sum(impr)/sum(eligible)")


# ----------------------------------------------------------------------------- offline (step 3)
def _status_evidence(ctx, run_start, run_end) -> list[dict]:
    """Owner/billing/policy status evidence rows for this account overlapping the zero run.

    Rules:   Only external/account_status_evidence rows with this customer_id, status_type in
             unplanned_stop|planned_pause, non-empty cause and source, and from_date <= run_end and
             (to_date empty or >= run_start). Campaign status rows are never status evidence.
    """
    out = []
    for r in ctx.rows("external/account_status_evidence"):
        if str(r.get("customer_id") or "") != str(ctx.account_id):
            continue
        kind = str(r.get("status_type") or "").strip().lower()
        start, end = V.parse_date(r.get("from_date")), V.parse_date(r.get("to_date"))
        if kind not in ("unplanned_stop", "planned_pause") or start is None or start > run_end:
            continue
        if end is not None and end < run_start:
            continue
        if not str(r.get("cause") or "").strip() or not str(r.get("source") or "").strip():
            continue
        out.append({"evidence_ref": str(r.get("evidence_ref") or ""), "status_type": kind,
                    "cause": r.get("cause"), "source": r.get("source"), "from_date": start, "to_date": end})
    return sorted((x for x in out if x["evidence_ref"]), key=lambda x: x["evidence_ref"])


def _offline(ctx, min_impr) -> None:
    chk = ctx.check("account_offline", "Zero-serving complete days vs own baseline",
                    {DAILY: ["date", "impressions", "cost"]})
    if not chk.runnable:
        return
    min_days, min_src = _int_setting(ctx, "offline_min_days", 1, 1)
    base_n, base_src = _int_setting(ctx, "offline_baseline_days", 28, 7)
    for v, src in ((min_days, min_src), (base_n, base_src)):
        if v is None:
            chk.partial(src)
    end = ctx.as_of or ctx.period_end
    if end is None or min_days is None or base_n is None or min_impr.value is None:
        chk.partial("report end, offline settings or min_impressions unresolved: no offline decision")
        return
    days = _daily_days(ctx, chk)
    if days is None:
        return
    days = {d: r for d, r in days.items() if d <= end}
    if not days:
        chk.partial(f"no complete day on or before {end}: offline status unknown")
        return
    last = max(days)
    if last != end:
        chk.partial(f"latest complete day {last} precedes report end {end}: later days unknown, not zero")
    run, d, stop = 0, last, ""
    while True:
        if d not in days:
            stop = f"no row for {d}"
            break
        impr, cost = V.num(days[d].get("impressions")), ctx.money(days[d].get("cost"))
        if impr is None or cost is None:
            stop = f"unknown impressions/cost on {d}"
            break
        if impr == 0 and cost == 0:
            run += 1
            d -= timedelta(days=1)
            continue
        break
    entity = {"customer_id": ctx.account_id}
    if run == 0:
        if stop:
            chk.partial(f"latest complete day {last}: {stop}")
            return
        chk.observe(f"Account {ctx.account_id} served on its latest complete day {last}", customer_id=ctx.account_id,
                    impressions=V.num(days[last].get("impressions")), cost=ctx.money(days[last].get("cost")))
        return
    run_start = last - timedelta(days=run - 1)
    b_end = run_start - timedelta(days=1)
    b_dates = [b_end - timedelta(days=i) for i in range(base_n)]
    b_missing = [x for x in b_dates if x not in days or V.num(days[x].get("impressions")) is None]
    b_impr = sum(V.num(days[x].get("impressions")) for x in b_dates if x not in b_missing)
    b_costs = [ctx.money(days[x].get("cost")) for x in b_dates if x not in b_missing]
    b_cost = None if any(c is None for c in b_costs) else sum(b_costs)
    longest = cur = 0
    for x in sorted(b_dates):
        if x in b_missing:
            cur = 0
            continue
        cur = cur + 1 if V.num(days[x].get("impressions")) == 0 else 0
        longest = max(longest, cur)
    ev = {"zero_run_days": run, "zero_run_start": run_start, "zero_run_end": last, "report_end": end,
          "run_bounded_by": stop or "serving day", "baseline_window": [b_dates[-1], b_end],
          "baseline_days_required": base_n, "baseline_days_missing": len(b_missing),
          "baseline_impressions": b_impr, "baseline_cost": b_cost,
          "longest_baseline_zero_run": longest, "min_impressions": min_impr.value,
          "min_impressions_source": min_impr.source, "offline_min_days": min_days,
          "offline_min_days_source": min_src, "offline_baseline_days_source": base_src,
          "currency": ctx.currency}
    if run < min_days:
        chk.observe(f"Account {ctx.account_id}: {run} zero-serving day(s) below offline_min_days {min_days}", **ev)
        return
    reasons = []
    if b_missing:
        reasons.append(f"baseline incomplete ({len(b_missing)} of {base_n} days missing/unknown)")
    if b_impr < min_impr.value:
        reasons.append(f"baseline impressions {b_impr:g} < min_impressions {min_impr.value}")
    if run <= longest:
        reasons.append(f"zero run {run}d not longer than baseline zero run {longest}d")
    if reasons:
        chk.finding("account_offline_unqualified", "Info", entity,
                    f"Account {ctx.account_id} had zero impressions and cost on {run} complete day(s) "
                    f"{run_start}..{last}, but its baseline does not qualify: {'; '.join(reasons)}",
                    evidence=ev, calculation={"rule": "run >= offline_min_days AND run > longest baseline zero run "
                                              "AND baseline impressions >= min_impressions", "failed": reasons},
                    recommendation="Confirm serving status with the account owner; supply a longer complete daily history.",
                    uncertainty="Sporadic or small accounts have normal zero days; not evidence of an outage.")
        return
    prov = chk.finding("account_offline", "Warning", entity,
                       f"Account {ctx.account_id} served zero impressions and zero cost on {run} consecutive complete "
                       f"day(s) {run_start}..{last} after a {base_n}-day baseline with {b_impr:g} impressions "
                       f"(longest baseline zero run {longest}d)",
                       evidence=ev, calculation={"rule": "run >= offline_min_days AND run > longest baseline zero run "
                                                 "AND baseline impressions >= min_impressions", "passed": True},
                       recommendation="Check account/campaign status, billing, policy and budget with the owner before any change.",
                       uncertainty="Zero serving is evidenced; whether the stop was planned is not.")
    chk.review("account_offline", entity,
               f"Account {ctx.account_id} stopped serving on {run_start} ({run} complete day(s)). Was this stop "
               f"unplanned, and is there cited evidence (billing, policy/suspension, status) of the cause?",
               evidence={**ev, "status_evidence": _status_evidence(ctx, run_start, last)},
               outcomes={
                   "unplanned_stop_evidenced": {"severity": "Critical", "recommendation":
                                                "Treat as a serving outage; resolve the cited cause with the owner."},
                   "planned_pause": {"severity": None, "recommendation": "No action; record the approved pause."},
                   "uncertain": {"severity": "Warning", "recommendation":
                                 "Ask the account owner whether the stop was intended."},
               },
               guidance="Critical needs proposal.evidence_ref of a status_evidence row with status_type unplanned_stop; "
                        "planned_pause needs one with status_type planned_pause (external/account_status_evidence). "
                        "Without such a row choose uncertain.",
               provisional=prov)


# ----------------------------------------------------------------------------- deltas (step 4)
def _period_over_period(ctx, goal_basis, min_impr, min_clicks, min_conv) -> None:
    chk = ctx.check("period_over_period", "Report period vs equal-length prior period",
                    {DAILY: ["date", "impressions", "clicks", "cost", "conversions"]})
    if not chk.runnable:
        return
    ps, pe = ctx.period_start, ctx.period_end
    if ps is None or pe is None or pe < ps:
        chk.partial("account report period unknown: no comparison")
        return
    days = _daily_days(ctx, chk)
    if days is None:
        return
    n = (pe - ps).days + 1
    prev_end = ps - timedelta(days=1)
    prev_start = prev_end - timedelta(days=n - 1)
    cur, cur_missing = _window_sums(ctx, days, ps, pe)
    prev, prev_missing = _window_sums(ctx, days, prev_start, prev_end)
    if cur is None or prev is None:
        miss = cur_missing + prev_missing
        chk.partial(f"{len(miss)} complete days missing ({min(miss)}..{max(miss)}): no period comparison",
                    [f"{DAILY}:date"])
        return
    if "conversion_value" not in ctx.table(DAILY).columns:
        chk.partial("conversion_value not supplied: value/ROAS deltas omitted", [f"{DAILY}:conversion_value"])
    mature = ctx.mature is True
    if not mature:
        chk.partial(f"conversion/value/CVR/CPA/ROAS deltas withheld: {ctx.maturity_note}")

    def delta(a, b):
        if a is None or b is None:
            return {"current": a, "previous": b, "delta": None, "delta_pct": None}
        return {"current": a, "previous": b, "delta": a - b, "delta_pct": V.ratio(a - b, b)}

    out = {m: delta(cur[m], prev[m]) for m in ("impressions", "clicks", "cost")}
    if mature:
        out["conversions"] = delta(cur["conversions"], prev["conversions"])
        out["conversion_value"] = delta(cur["conversion_value"], prev["conversion_value"])
    gates = {}
    both = lambda m, p: p.value is not None and all(x[m] is not None and x[m] >= p.value for x in (cur, prev))
    gates["ctr"] = both("impressions", min_impr)
    if gates["ctr"]:
        out["ctr"] = delta(V.ratio(cur["clicks"], cur["impressions"]), V.ratio(prev["clicks"], prev["impressions"]))
    gates["conversion_rate"] = mature and both("clicks", min_clicks)
    if gates["conversion_rate"]:
        out["conversion_rate"] = delta(V.ratio(cur["conversions"], cur["clicks"]),
                                       V.ratio(prev["conversions"], prev["clicks"]))
    gates["cpa_roas"] = mature and bool(goal_basis) and both("conversions", min_conv)
    if gates["cpa_roas"]:
        out["cpa"] = delta(V.ratio(cur["cost"], cur["conversions"]), V.ratio(prev["cost"], prev["conversions"]))
        out["roas"] = delta(V.ratio(cur["conversion_value"], cur["cost"]), V.ratio(prev["conversion_value"], prev["cost"]))
    chk.observe(f"Account {ctx.account_id} {ps}..{pe} vs {prev_start}..{prev_end}", customer_id=ctx.account_id,
                currency=ctx.currency, current_window=[ps, pe], previous_window=[prev_start, prev_end],
                deltas=out, gates_passed=gates, goal_basis=goal_basis,
                thresholds={"min_impressions": min_impr.value, "min_clicks": min_clicks.value,
                            "min_conversions": min_conv.value},
                note="Descriptive change between complete periods; not a cause or a forecast.")


# ----------------------------------------------------------------------------- portfolio (steps 5-6)
def _portfolio(ctx) -> None:
    full = load_evidence(ctx.evidence.root, ctx.profile.get("column_map"))
    ids = sorted(account_ids(full))
    anchor = ids[0] if ids else None
    titles = (("portfolio_totals", "Native-currency portfolio totals"),
              ("currency_conversion", "Reporting-currency conversion with dated rates"))
    if len(ids) > 1 and str(ctx.account_id) != anchor:
        for cid, title in titles:
            ctx.check(cid, title, applicable=False,
                      na_reason=f"portfolio rollup is reported once, in accounts/{anchor}/result.json")
        return
    tot_chk = ctx.check(*titles[0])
    conv_chk = ctx.check(*titles[1])
    acct_t, cm = full.get("account"), full.get("campaign_metrics")
    used = {t.filename: t.sha256 for t in (acct_t, cm, full.get(RATES)) if t is not None}
    ctx.result.inputs["portfolio_files"] = used
    missing = []
    if acct_t is None or not acct_t.rows:
        missing.append("account (file)")
    if cm is None:
        missing.append("campaign_metrics (file)")
    else:
        missing += [f"campaign_metrics:{c}" for c in cm.missing(KPI_NEEDS["campaign_metrics"])]
        if len(ids) > 1 and _cust_col(cm.columns) is None:
            missing.append("campaign_metrics:customer_id")
    if missing:
        tot_chk.skip("required evidence missing", missing)
        conv_chk.skip("portfolio totals unavailable", missing)
        return
    if cm.complete is not True:
        tot_chk.partial(f"{cm.filename}: manifest does not certify complete rows; totals cover supplied rows")
    acct_col = _cust_col(acct_t.columns)
    rows_col = _cust_col(cm.columns)
    accounts = []
    for aid in (ids or [None]):
        arow = next((r for r in acct_t.rows if aid is None or str(r.get(acct_col) or "") == aid), {})
        rows = [r for r in cm.rows if len(ids) <= 1 or str(r.get(rows_col) or "") == aid]
        tot, problems = _totals(rows, cm.columns, arow.get("money_unit"))
        for p in problems:
            tot_chk.partial(f"account {aid}: {p}")
        accounts.append({"customer_id": aid, "currency": (arow.get("currency_code") or "").upper() or None,
                         "period": (V.parse_date(arow.get("date_range_start")), V.parse_date(arow.get("date_range_end"))),
                         "totals": tot})
    groups: dict[tuple, list] = {}
    for a in accounts:
        if a["currency"] is None or None in a["period"]:
            tot_chk.partial(f"account {a['customer_id']}: currency or report period unknown; not grouped")
            continue
        groups.setdefault((a["currency"], *a["period"]), []).append(a)
    for (cur, ps, pe), members in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), str(kv[0][2]))):
        sums = {}
        for m in METRICS:
            vals = [x["totals"][m] if x["totals"] else None for x in members]
            sums[m] = None if any(v is None for v in vals) else sum(vals)
        tot_chk.observe(f"Portfolio total {cur} {ps}..{pe} ({len(members)} account(s))", currency=cur, period=[ps, pe],
                        accounts=[x["customer_id"] for x in members], totals=sums,
                        per_account={str(x["customer_id"]): x["totals"] for x in members},
                        note="conversions sum each account's own definitions; no portfolio CPA/ROAS")
    currencies = sorted({k[0] for k in groups})
    tot_chk.observe("Portfolio currency/period groups", groups=len(groups), currencies=currencies,
                    accounts=len(accounts), cross_currency_sum="never without dated rates")
    _conversion(ctx, conv_chk, full, accounts)


def _conversion(ctx, chk, full, accounts) -> None:
    target = str(_portfolio_profile(ctx).get("reporting_currency") or "").strip().upper()
    if not target:
        chk.not_applicable("profile.portfolio.reporting_currency not set: native-currency totals only")
        return
    rates_t = full.get(RATES)
    needs_rates = any(a["currency"] not in (None, target) for a in accounts)
    if needs_rates and (rates_t is None or rates_t.missing(RATE_COLS)):
        miss = [f"{RATES} (file)"] if rates_t is None else [f"{RATES}:{c}" for c in rates_t.missing(RATE_COLS)]
        chk.skip("dated exchange rates required for cross-currency conversion", miss)
        return
    converted, blocked = [], []
    for a in accounts:
        cur, (ps, pe), tot = a["currency"], a["period"], a["totals"]
        if cur is None or pe is None or tot is None or tot["cost"] is None:
            blocked.append(f"account {a['customer_id']}: currency, period or cost unknown")
            continue
        if cur == target:
            rate, rsrc, rdate = 1.0, "same currency", pe
        else:
            hits = [r for r in rates_t.rows if V.parse_date(r.get("date")) == pe
                    and str(r.get("from") or "").strip().upper() == cur and str(r.get("to") or "").strip().upper() == target]
            vals = {V.num(r.get("rate")) for r in hits}
            srcs = sorted({str(r.get("source") or "").strip() for r in hits} - {""})
            if not hits:
                blocked.append(f"{RATES}: no {cur}->{target} rate dated {pe} (account {a['customer_id']})")
                continue
            if len(vals) != 1 or None in vals or not math.isfinite(next(iter(vals))) or next(iter(vals)) <= 0:
                blocked.append(f"{RATES}: {cur}->{target} on {pe} not one positive rate {sorted(map(str, vals))}")
                continue
            if not srcs:
                blocked.append(f"{RATES}: {cur}->{target} on {pe} has no source")
                continue
            rate, rsrc, rdate = next(iter(vals)), "; ".join(srcs), pe
        conv = {"customer_id": a["customer_id"], "currency": cur, "period": [ps, pe], "rate": rate,
                "rate_date": rdate, "rate_source": rsrc, "cost_native": tot["cost"],
                "cost_converted": tot["cost"] * rate,
                "conversion_value_native": tot["conversion_value"],
                "conversion_value_converted": None if tot["conversion_value"] is None else tot["conversion_value"] * rate}
        converted.append(conv)
        chk.observe(f"Account {a['customer_id']} converted {cur}->{target} at {rate:g} ({rdate})", **conv)
    for b in blocked:
        chk.partial(b)
    periods = {tuple(c["period"]) for c in converted}
    if blocked or not converted:
        chk.partial("no converted portfolio total: not every account converts")
        return
    if len(periods) > 1:
        chk.partial(f"no converted portfolio total: accounts cover different periods {sorted(map(str, periods))}")
        return
    values = [c["conversion_value_converted"] for c in converted]
    chk.observe(f"Portfolio total converted to {target}", reporting_currency=target, period=list(next(iter(periods))),
                accounts=[c["customer_id"] for c in converted],
                cost=sum(c["cost_converted"] for c in converted),
                conversion_value=None if any(v is None for v in values) else sum(values),
                method="native period totals x one sourced rate dated at each account's report end")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   'unplanned_stop_evidenced' (Critical) needs proposal.evidence_ref of a reviewed status_evidence row with
             status_type unplanned_stop; 'planned_pause' needs one with status_type planned_pause. Rows come only from
             external/account_status_evidence for the reviewed account overlapping the zero run (see _status_evidence);
             unknown, foreign-account or mismatched-type refs are rejected. 'uncertain' needs no proposal.
    """
    outcome = decision.get("outcome")
    if item.condition_key != "account_offline" or outcome not in _EVIDENCE_OUTCOMES:
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return [f"{outcome} needs proposal.evidence_ref naming an account_status_evidence row"]
    rows = {r["evidence_ref"]: r for r in item.evidence.get("status_evidence") or []}
    want = "unplanned_stop" if outcome == "unplanned_stop_evidenced" else "planned_pause"
    if ref not in rows:
        return [f"evidence_ref {ref} is not status evidence of account {item.entity.get('customer_id')} "
                f"overlapping the zero run (available: {sorted(rows) or 'none; choose uncertain'})"]
    if rows[ref]["status_type"] != want:
        return [f"evidence_ref {ref} has status_type {rows[ref]['status_type']}, outcome {outcome} needs {want}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
