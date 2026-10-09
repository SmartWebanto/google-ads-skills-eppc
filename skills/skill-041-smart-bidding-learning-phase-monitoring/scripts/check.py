"""check.py — skill-041 deterministic Smart Bidding learning interval, change and baseline monitoring.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-041-smart-bidding-learning-phase-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Learning only from documented_learning_state tokens (learning/true vs not_learning/false/stable);
         raw_status alone (e.g. LIMITED) never means learning; other values are unknown.
         Duration is observational: minimum = first→last learning observation of the current run with no
         non-learning/unknown observation between; upper bound only from a prior confirmed non-learning row.
         Change counts = unique change_id within the 30 days ending ctx.as_of; coverage from the manifest period.
         Baseline = same count of whole weeks immediately before first learning observation; both sides lag-mature,
         one goal cohort and >= min_conversions; weekly volatility uses complete non-overlapping 7-day sums.
         >21-day learning and repeated changes are review heuristics (provisional Info); Warning only via review.
         verify(): repeated_discretionary needs >= 2 proposal.discretionary_change_ids from the reviewed list.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import statistics
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

SKILL = "skill-041-smart-bidding-learning-phase-monitoring"
VERSION = "1.0.0"

STATUS = "custom/learning_status_history"
CHANGES = "custom/learning_changes"
DAILY = "custom/learning_daily"
STATUS_COLS = ["campaign_id", "observed_at", "raw_status", "raw_reason", "documented_learning_state"]
CHANGE_COLS = ["change_id", "changed_at", "campaign_id", "field"]
DAILY_COLS = ["campaign_id", "date", "cost", "conversions", "conversion_value", "lag_mature"]
SMART = {"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"}
LEARNING = {"learning", "true", "yes", "in_learning", "learning_new", "learning_setting_change",
            "learning_budget_change", "learning_composition_change", "learning_conversion_type_change"}
NOT_LEARNING = {"not_learning", "false", "no", "stable", "eligible", "none", "learning_complete", "not learning"}
RELEVANT_FIELDS = ("target", "budget", "strategy", "bidding", "goal", "conversion", "status", "pause", "enable")
LONG_DAYS = 21
WINDOW_DAYS = 30


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _state(v) -> bool | None:
    t = V.norm_text(v).replace(" ", "_") if _s(v) else ""
    if t in LEARNING:
        return True
    if t in NOT_LEARNING or t.replace("_", " ") in NOT_LEARNING:
        return False
    return None


def _interval(obs: list[tuple]) -> dict | None:
    """obs sorted [(date, state)] → current learning run facts, or None when the latest known state is not learning."""
    if not obs or obs[-1][1] is not True:
        return None
    i = len(obs) - 1
    while i > 0 and obs[i - 1][1] is True:
        i -= 1
    run = obs[i:]
    prior = obs[i - 1] if i > 0 else None
    dates = [d for d, _ in run]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    return {"first_learning": dates[0], "last_learning": dates[-1],
            "min_observed_days": (dates[-1] - dates[0]).days,
            "prior_state": None if prior is None else ("unknown" if prior[1] is None else "not_learning"),
            "prior_observed_at": prior[0] if prior else None,
            "upper_bound_days": (dates[-1] - prior[0]).days if prior and prior[1] is False else None,
            "max_gap_days": max(gaps) if gaps else 0, "observations": len(run)}


def _daily(ctx) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in ctx.rows(DAILY):
        cid, d = _s(r.get("campaign_id")), V.parse_date(r.get("date"))
        if cid and d:
            out.setdefault(cid, {}).setdefault(d, []).append(r)
    return out


def _agg(ctx, days: dict, dates: list) -> dict | None:
    """Summed outcomes; None when any day is missing, immature or unknown."""
    tot = {"cost": 0.0, "conversions": 0.0, "value": 0.0, "cohorts": set()}
    for d in dates:
        rows = days.get(d)
        if not rows or any(V.boolean(r.get("lag_mature")) is not True for r in rows):
            return None
        for r in rows:
            c, n, v = ctx.money(r.get("cost")), V.num(r.get("conversions")), ctx.money(r.get("conversion_value"))
            if c is None or n is None:
                return None
            tot["cost"] += c
            tot["conversions"] += n
            tot["value"] = None if v is None or tot["value"] is None else tot["value"] + v
            tot["cohorts"].add(_s(r.get("goal_cohort")))
    tot["cpa"] = V.ratio(tot["cost"], tot["conversions"])
    tot["roas"] = V.ratio(tot["value"], tot["cost"])
    return tot


def run(ctx) -> None:
    """Run learning-status mapping, interval, 30-day change timeline, baseline, volatility and review checks.

    Rules:   Only Smart Bidding campaigns (SMART set) count; undocumented learning state stays unknown, never learning.
             Baseline CPA/ROAS and weekly volatility need lag-mature days, one goal cohort and >= min_conversions.
             >=2 relevant changes and >21-day learning emit provisional Info only; Warning only via ai_review
             (repeated_discretionary / sustained_performance_concern). Monitoring basis is never an exit date.
    """
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}
    smart = {cid for cid, r in camps.items() if _s(r.get("bidding_strategy_type")).upper() in SMART}
    min_conv = ctx.params.get("min_conversions")

    # step 1 — status mapping
    mp = ctx.check("learning_status_mapping", "Documented learning status mapping (step 1)", {STATUS: STATUS_COLS})
    series: dict[str, list] = {}
    if mp.runnable:
        if not camps:
            mp.partial("campaign inventory missing: Smart Bidding applicability unverified", ["campaigns (file)"])
        counts = {"learning": 0, "not_learning": 0, "unknown": 0, "out_of_scope": 0}
        for r in sorted(ctx.rows(STATUS), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("observed_at")))):
            cid, d = _s(r.get("campaign_id")), V.parse_date(r.get("observed_at"))
            if not cid or d is None:
                counts["unknown"] += 1
                continue
            if camps and cid not in smart:
                counts["out_of_scope"] += 1
                continue
            st = _state(r.get("documented_learning_state"))
            counts["learning" if st else "not_learning" if st is False else "unknown"] += 1
            series.setdefault(cid, []).append((d, st))
        mp.observe("Status observations mapped (raw status alone never counts as learning)", **counts)
        if counts["unknown"]:
            mp.partial(f"{counts['unknown']} observations without a documented learning state")

    # step 2 — interval
    itv = ctx.check("learning_interval", "Observed learning interval and gaps (step 2)", {STATUS: STATUS_COLS})
    runs: dict[str, dict] = {}
    if itv.runnable:
        for cid, obs in sorted(series.items()):
            # collapse same-day duplicates: conflicting states on one day → unknown
            by_day: dict = {}
            for d, st in obs:
                by_day[d] = st if d not in by_day or by_day[d] == st else None
            ordered = sorted(by_day.items())
            iv = _interval(ordered)
            if iv is None:
                itv.observe(f"Campaign {cid}: latest documented state is not learning", campaign_id=cid,
                            latest=ordered[-1][0], latest_state=ordered[-1][1])
                continue
            runs[cid] = iv
            itv.observe(f"Campaign {cid}: learning observed {iv['first_learning']}..{iv['last_learning']} "
                        f"(minimum {iv['min_observed_days']}d, bounded not exact)", campaign_id=cid, **iv)
            if iv["prior_state"] != "not_learning":
                itv.partial(f"campaign {cid}: no prior confirmed non-learning observation; start is a lower bound")

    # step 3 — change timeline
    end = ctx.as_of
    start = end - timedelta(days=WINDOW_DAYS - 1) if end else None
    tl = ctx.check("change_timeline", "Unique relevant changes in the 30-day window (step 3)", {CHANGES: CHANGE_COLS})
    changes: dict[str, list] = {}
    if tl.runnable:
        t = ctx.table(CHANGES)
        mstart = V.parse_date((t.manifest or {}).get("period_start")) if t.manifest else None
        if start is None or mstart is None or mstart > start:
            tl.partial(f"change history coverage of {start}..{end} not certified by the manifest period")
        seen: set = set()
        for r in sorted(ctx.rows(CHANGES), key=lambda r: (_s(r.get("changed_at")), _s(r.get("change_id")))):
            d, chid = V.parse_date(r.get("changed_at")), _s(r.get("change_id"))
            if d is None or not chid or start is None or not (start <= d <= end):
                continue
            field = V.norm_text(r.get("field"))
            if not any(w in field for w in RELEVANT_FIELDS):
                continue
            targets = set()
            for cid, c in camps.items():
                if (_s(r.get("campaign_id")) == cid
                        or (_s(r.get("strategy_id")) and _s(r.get("strategy_id")) == _s(c.get("bidding_strategy_id") or c.get("strategy_id")))
                        or (_s(r.get("budget_id")) and _s(r.get("budget_id")) == _s(c.get("budget_id")))):
                    targets.add(cid)
            if not camps and _s(r.get("campaign_id")):
                targets.add(_s(r.get("campaign_id")))
            for cid in sorted(targets):
                if (cid, chid) in seen:
                    continue
                seen.add((cid, chid))
                changes.setdefault(cid, []).append({"change_id": chid, "changed_at": d, "field": r.get("field"),
                                                    "old_value": r.get("old_value"), "new_value": r.get("new_value"),
                                                    "reason": r.get("reason"), "source_ref": r.get("source_ref")})
        for cid, lst in sorted(changes.items()):
            tl.observe(f"Campaign {cid}: {len(lst)} unique relevant changes {start}..{end}", campaign_id=cid,
                       unique_changes=len(lst), window=[start, end])

    # step 5 — baseline (computed before reviews)
    bl = ctx.check("baseline_comparison", "Matched pre-learning baseline vs learning outcomes (step 5)",
                   {DAILY: DAILY_COLS, STATUS: STATUS_COLS})
    daily = _daily(ctx) if ctx.table(DAILY) else {}
    baselines: dict[str, dict] = {}
    if bl.runnable:
        if min_conv.value is None:
            bl.partial(f"min_conversions unresolved: {min_conv.reason}")
        for cid, iv in sorted(runs.items()):
            days = daily.get(cid, {})
            learn = sorted(d for d in days if iv["first_learning"] <= d <= iv["last_learning"]
                           and all(V.boolean(r.get("lag_mature")) is True for r in days[d]))
            n = len(learn) // 7 * 7
            if n < 7:
                bl.partial(f"campaign {cid}: fewer than 7 mature learning days")
                continue
            lw = learn[-n:]
            bw = [iv["first_learning"] - timedelta(days=i) for i in range(n, 0, -1)]
            la, ba = _agg(ctx, days, lw), _agg(ctx, days, bw)
            if la is None or ba is None:
                bl.partial(f"campaign {cid}: baseline or learning window incomplete/immature ({n} days each)")
                continue
            if len(la["cohorts"] | ba["cohorts"]) > 1:
                bl.partial(f"campaign {cid}: goal cohorts differ across windows {sorted(la['cohorts'] | ba['cohorts'])}")
                continue
            ok = min_conv.value is not None and min(la["conversions"], ba["conversions"]) >= min_conv.value
            res = {"window_days": n, "learning_window": [lw[0], lw[-1]], "baseline_window": [bw[0], bw[-1]],
                   "learning": {k: la[k] for k in ("cost", "conversions", "value", "cpa", "roas")},
                   "baseline": {k: ba[k] for k in ("cost", "conversions", "value", "cpa", "roas")},
                   "both_qualify": ok, "min_conversions": min_conv.value}
            if ok and la["cpa"] is not None and ba["cpa"] is not None:
                res["cpa_change"] = V.ratio(la["cpa"] - ba["cpa"], ba["cpa"])
            elif not ok:
                bl.partial(f"campaign {cid}: a cohort is below min_conversions; CPA/ROAS not compared")
            baselines[cid] = res
            bl.observe(f"Campaign {cid}: matched {n}-day baseline vs learning", campaign_id=cid, **res)

    # step 6 — weekly volatility
    vol = ctx.check("weekly_volatility", "Non-overlapping weekly CPA volatility (step 6)", {DAILY: DAILY_COLS, STATUS: STATUS_COLS})
    volatility: dict[str, dict] = {}
    if vol.runnable:
        for cid, iv in sorted(runs.items()):
            days = daily.get(cid, {})
            mature = sorted(d for d in days if iv["first_learning"] <= d <= iv["last_learning"])
            if not mature:
                vol.partial(f"campaign {cid}: no daily rows in the learning interval")
                continue
            weeks, cpas = [], []
            e = mature[-1]
            while e - timedelta(days=6) >= iv["first_learning"]:
                block = [e - timedelta(days=i) for i in range(6, -1, -1)]
                a = _agg(ctx, days, block)
                if a is not None and min_conv.value is not None and a["conversions"] >= min_conv.value:
                    weeks.append([block[0], block[-1]])
                    cpas.append(a["cpa"])
                e -= timedelta(days=7)
            res = {"valid_weeks": len(cpas), "weekly_cpa": cpas, "weeks": weeks}
            if len(cpas) >= 2 and statistics.mean(cpas) > 0:
                res.update({"cpa_range": [min(cpas), max(cpas)], "cv": statistics.pstdev(cpas) / statistics.mean(cpas)})
            else:
                vol.partial(f"campaign {cid}: fewer than 2 qualifying complete weeks; volatility unavailable")
            volatility[cid] = res
            vol.observe(f"Campaign {cid}: weekly CPA volatility", campaign_id=cid, **res)

    # step 4 — discretionary changes review
    dis = ctx.check("discretionary_changes", "Repeated discretionary changes review (step 4)", {CHANGES: CHANGE_COLS})
    if dis.runnable:
        for cid, lst in sorted(changes.items()):
            if len(lst) < 2:
                continue
            entity = {"campaign_id": cid}
            prov = dis.finding("repeated_changes_screen", "Info", entity,
                               f"Campaign {cid}: {len(lst)} unique target/budget/strategy/goal/status changes in {WINDOW_DAYS} days",
                               evidence={"changes": lst, "window": [start, end]},
                               recommendation="Separate incident repairs and planned tests from discretionary churn.",
                               uncertainty="A change during learning does not prove it restarted learning.")
            dis.review("repeated_discretionary_changes", entity,
                       f"Are the changes on campaign {cid} repeated discretionary churn with documented instability?",
                       evidence={"changes": lst, "window": [start, end], "volatility": volatility.get(cid),
                                 "baseline": baselines.get(cid), "learning_run": runs.get(cid)},
                       outcomes={"repeated_discretionary": {"severity": "Warning", "recommendation":
                                                            "Defer elective changes; keep urgent repairs; set an owner review date."},
                                 "necessary_or_planned": {"severity": None, "recommendation": "No finding; document the rationale."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request change reasons/owners."}},
                       guidance="repeated_discretionary needs proposal.discretionary_change_ids (>=2, from evidence) and "
                                "documented instability (volatility/baseline). Associations are hypotheses.",
                       provisional=prov)

    # step 7 — long learning review
    lng = ctx.check("learning_duration_review", "Observed learning over 21 days (step 7)", {STATUS: STATUS_COLS})
    if lng.runnable:
        for cid, iv in sorted(runs.items()):
            if iv["min_observed_days"] <= LONG_DAYS:
                continue
            entity = {"campaign_id": cid}
            prov = lng.finding("learning_over_21_days", "Info", entity,
                               f"Campaign {cid}: learning observed for at least {iv['min_observed_days']} days "
                               f"({iv['first_learning']}..{iv['last_learning']})",
                               evidence={**iv, "threshold_days": LONG_DAYS},
                               recommendation="Check lag, tracking, traffic, eligibility and constraints before acting.",
                               uncertainty="Observed interval is bounded by snapshot cadence; no promised exit date.")
            lng.review("learning_over_21_days", entity,
                       f"Is campaign {cid}'s long observed learning accompanied by a corroborated, sustained "
                       f"business-performance concern?",
                       evidence={**iv, "baseline": baselines.get(cid), "volatility": volatility.get(cid),
                                 "changes_30d": changes.get(cid, [])},
                       outcomes={"sustained_performance_concern": {"severity": "Warning", "recommendation":
                                                                   "Owner review of tracking/target/budget causes; no blanket freeze."},
                                 "learning_only": {"severity": "Info", "recommendation": "Monitor through the next conversion cycle."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request baseline/tracking evidence."}},
                       guidance="Warning needs a qualified baseline comparison or documented business impact; "
                                "learning alone or low volume stays Info.",
                       provisional=prov)

    # step 8 — monitoring plan basis
    mon = ctx.check("monitoring_plan", "Observation window basis from conversion cycles (step 8)")
    cycle = V.integer(ctx.profile.get("sales_cycle_days"))
    basis = max(x for x in (ctx.lag_days, cycle, 7) if x is not None)
    if ctx.lag_days is None and cycle is None:
        mon.partial("conversion lag and sales cycle unknown: observation window basis defaults to one week only")
    for cid, iv in sorted(runs.items()):
        mon.observe(f"Campaign {cid}: observation window basis {basis} days (not an exit date)", campaign_id=cid,
                    lag_days=ctx.lag_days, sales_cycle_days=cycle, basis_days=basis,
                    next_review=(end + timedelta(days=basis)) if end else None)


def verify(ctx, item, decision) -> list[str]:
    """Rules: repeated_discretionary cites >= 2 reviewed change ids."""
    if item.condition_key == "repeated_discretionary_changes" and decision.get("outcome") == "repeated_discretionary":
        listed = {c["change_id"] for c in item.evidence.get("changes") or []}
        ids = [str(x) for x in (decision.get("proposal") or {}).get("discretionary_change_ids") or []]
        bad = [x for x in ids if x not in listed]
        if len(set(ids) - set(bad)) < 2 or bad:
            return [f"need >=2 discretionary_change_ids from {sorted(listed)}; unknown {bad}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
