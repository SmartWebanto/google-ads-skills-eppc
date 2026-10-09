"""check.py — skill-172 deterministic external-signal bucket cohorts, gated rate differences and rule checks.

exports: SKILL | VERSION | SMART_BIDDING | MODIFIER_RANGE | bucket(value, bounds, labels) -> str
         run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-172-external-signal-demand-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #32 Weather-based Campaign and Bid Management (Google) — clean-room reimplementation of
         "map weather conditions to per-campaign/location bid rules"; here the client supplies the series and
         rules, and the script only measures whether qualified cohorts support or contradict them.
         index #31 TV Schedule Bid Coordination (Google) — clean-room reimplementation of "raise bids during
         airing windows"; airing windows arrive as a 0/1 hourly signal and are analysed at the hourly grain.
         Both scripts' live fetching and bid mutation are NOT integrated: proposals are request-only.
rules:   No live weather/TV fetch; signals come only from export/external/external_signals.csv with a source.
         Buckets come ONLY from profile.external_signals.<name> {bounds, labels, baseline, min_relative_difference};
         no default thresholds. Hourly signals are never averaged to days; a daily signal may apply to its hours.
         Performance rows outside the account period, complete_day false, unknown metrics or duplicate
         campaign/region/period keys are excluded (reported), never zero-filled. Regions are pooled by summing.
         Rates are ratios of sums (V.ratio); both cohorts must pass min_impressions (CTR), min_clicks (CVR),
         min_conversions (CPA/ROAS). Conversion metrics also need ctx.mature True and
         ctx.tracking_for_campaign True; otherwise descriptive only. Primary metric = ROAS for ROAS objectives else CPA.
         A qualified |relative difference| >= declared tolerance → provisional Info + review; never causal.
         Rule contradiction (raise on unfavorable / cut or pause on favorable bucket) → Info + review (Warning outcome).
         verify(): proposals must match the reviewed scope, carry metric/duration/stop rule/owner, no forecasts;
         bid modifiers must follow the observed direction, lie in MODIFIER_RANGE and are rejected for SMART_BIDDING
         or unknown strategies (Smart Bidding ignores these adjustments).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes5 | initial recipe script
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

SKILL = "skill-172-external-signal-demand-analysis"
VERSION = "1.0.0"
SMART_BIDDING = ("TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE")
MODIFIER_RANGE = (-0.9, 9.0)
FORECAST_KEYS = ("expected_uplift", "uplift", "forecast", "expected_conversions", "expected_revenue", "savings")
SIGNAL_COLS = ["date", "region", "signal_name", "value", "source"]
PERF_COLS = ["campaign_id", "date", "region", "impressions", "clicks", "cost", "conversions"]
GRAINS = (("daily_alignment", "Daily signal/performance alignment", "custom/campaign_geo_daily", False),
          ("hourly_alignment", "Hourly signal/performance alignment", "custom/campaign_geo_hourly", True))
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def bucket(value: float, bounds: list[float], labels: list[str]) -> str:
    """Rules: value < bounds[0] → labels[0]; bounds[i-1] <= value < bounds[i] → labels[i]; >= last → last."""
    for i, b in enumerate(bounds):
        if value < b:
            return labels[i]
    return labels[-1]


def _hour(v):
    h = V.integer(v)
    return h if h is not None and 0 <= h <= 23 else None


def _configs(ctx, chk) -> dict:
    """Validated bucket definitions per normalized signal name."""
    raw = ctx.profile.get("external_signals")
    out = {}
    if not isinstance(raw, dict) or not raw:
        chk.skip("no bucket definitions", ["profile.external_signals"])
        return out
    for name in sorted(raw, key=str):
        spec = raw[name] if isinstance(raw[name], dict) else {}
        bounds = [V.num(b) for b in (spec.get("bounds") or [])]
        labels = [str(x) for x in (spec.get("labels") or [])]
        base = str(spec.get("baseline") or "")
        tol = V.num(spec.get("min_relative_difference"))
        key = V.norm_text(name)
        problem = None
        if not bounds or None in bounds or any(b >= c for b, c in zip(bounds, bounds[1:])):
            problem = "bounds must be strictly increasing numbers"
        elif len(labels) != len(bounds) + 1 or len(set(labels)) != len(labels):
            problem = "labels must be unique and one more than bounds"
        elif base not in labels:
            problem = "baseline must be one of labels"
        if problem:
            chk.partial(f"signal '{name}': {problem}; not analysed", [f"profile.external_signals.{name}"])
            continue
        if tol is None or tol <= 0:
            chk.partial(f"signal '{name}': min_relative_difference undeclared; comparisons descriptive only",
                        [f"profile.external_signals.{name}.min_relative_difference"])
            tol = None
        out[key] = {"name": str(name), "bounds": bounds, "labels": labels, "baseline": base, "tolerance": tol}
        chk.observe(f"Signal '{name}' buckets", signal=str(name), bounds=bounds, labels=labels, baseline=base,
                    min_relative_difference=tol, source=f"profile.external_signals.{name}")
    return out


def _series(ctx, chk, configs) -> dict:
    """(signal, region, date, hour|None) → value; conflicts excluded."""
    vals: dict[tuple, set] = {}
    bad = nosource = 0
    for r in ctx.rows("external/external_signals"):
        d, v = V.parse_date(r.get("date")), V.num(r.get("value"))
        raw_h = r.get("hour")
        h = _hour(raw_h) if raw_h not in (None, "") else None
        if d is None or v is None or (raw_h not in (None, "") and h is None):
            bad += 1
            continue
        if not str(r.get("source") or "").strip():
            nosource += 1
            continue
        key = (V.norm_text(r.get("signal_name")), V.norm_text(r.get("region")), d, h)
        vals.setdefault(key, set()).add(v)
    conflicts = sorted(k for k, s in vals.items() if len(s) > 1)
    series = {k: next(iter(s)) for k, s in vals.items() if len(s) == 1}
    if bad or nosource:
        chk.partial(f"{bad} rows with unparseable date/hour/value and {nosource} rows without source excluded")
    if conflicts:
        chk.partial(f"{len(conflicts)} signal/region/period keys with conflicting values excluded")
    unconfigured = sorted({k[0] for k in series} - set(configs))
    names = sorted({k[0] for k in series})
    for n in names:
        keys = [k for k in series if k[0] == n]
        dates = sorted({k[2] for k in keys})
        chk.observe(f"Signal '{n}' series", signal=n, periods=len(keys), regions=sorted({k[1] for k in keys}),
                    hourly_periods=sum(1 for k in keys if k[3] is not None), first=dates[0], last=dates[-1],
                    configured=n in configs)
    if unconfigured:
        chk.partial(f"signals without profile buckets not analysed: {unconfigured}")
    return series


def _new_cohort():
    return {"rows": 0, "periods": set(), "impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0,
            "value": 0.0, "value_known": True, "weekday": {}}


def _rates(c: dict) -> dict:
    return {"ctr": V.ratio(c["clicks"], c["impressions"]), "cvr": V.ratio(c["conversions"], c["clicks"]),
            "cpa": V.ratio(c["cost"], c["conversions"]),
            "roas": V.ratio(c["value"], c["cost"]) if c["value_known"] else None}


def _roas_objective(ctx, cid) -> bool:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    if isinstance(obj, dict) and V.num(obj.get("target_roas")):
        return True
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None)
    return bool(row and V.num(row.get("target_roas")))


def _compare(base: dict, other: dict, gates: dict, conv_ok: bool, roas_primary: bool) -> dict:
    rb, ro = _rates(base), _rates(other)
    out = {}
    specs = (("ctr", "impressions", "min_impressions", True), ("cvr", "clicks", "min_clicks", False),
             ("cpa", "conversions", "min_conversions", False), ("roas", "conversions", "min_conversions", False))
    for metric, count, gate, descriptive in specs:
        g = gates[gate]
        reason = None
        if g.value is None:
            reason = f"{gate} unresolved: {g.reason}"
        elif base[count] < g.value or other[count] < g.value:
            reason = f"{count} below {gate} {g.value} on at least one side"
        elif not descriptive and not conv_ok:
            reason = "conversion comparison blocked: maturity or tracking not evidenced"
        elif rb[metric] is None or ro[metric] is None:
            reason = "undefined rate (zero/unknown denominator or value)"
        rel = None if reason else V.ratio(ro[metric] - rb[metric], rb[metric])
        if rel is None and not reason:
            reason = "baseline rate is zero"
        out[metric] = {"baseline": rb[metric], "bucket": ro[metric], "relative_difference": rel, "gated_out": reason}
    primary = "roas" if roas_primary else "cpa"
    out["primary_metric"] = primary
    return out


def _direction(cmp: dict) -> tuple[str | None, str | None, float | None]:
    """(favorable|unfavorable|None, metric, rel) from primary metric if gated, else CVR."""
    for metric in (cmp["primary_metric"], "cvr"):
        rel = cmp[metric]["relative_difference"]
        if rel is not None:
            better = rel < 0 if metric == "cpa" else rel > 0
            return ("favorable" if better else "unfavorable") if rel != 0 else None, metric, rel
    return None, None, None


def _align(ctx, chk, table_key, hourly, series, configs, gates, qualified) -> None:
    unknown = excluded_window = incomplete = 0
    seen: dict[tuple, int] = {}
    rows = []
    t = ctx.table(table_key)
    has_value = "conversion_value" in t.columns
    for r in t.rows:
        d = V.parse_date(r.get("date"))
        h = _hour(r.get("hour")) if hourly else None
        m = {k: (ctx.money(r.get(k)) if k == "cost" else V.num(r.get(k)))
             for k in ("impressions", "clicks", "cost", "conversions")}
        if d is None or (hourly and h is None) or None in m.values():
            unknown += 1
            continue
        if "complete_day" in t.columns and V.boolean(r.get("complete_day")) is False:
            incomplete += 1
            continue
        if ctx.period_start and ctx.period_end and not (ctx.period_start <= d <= ctx.period_end):
            excluded_window += 1
            continue
        key = (str(r.get("campaign_id")), V.norm_text(r.get("region")), d, h)
        seen[key] = seen.get(key, 0) + 1
        val = ctx.money(r.get("conversion_value")) if has_value else None
        rows.append((key, m, val))
    dups = {k for k, n in seen.items() if n > 1}
    if ctx.period_start is None or ctx.period_end is None:
        chk.partial("account period unknown: window and maturity cannot be enforced")
    for n, why in ((unknown, "unparseable key or unknown metric"), (incomplete, "complete_day false"),
                   (excluded_window, "outside the account report period"), (len(dups), "duplicate key (all copies)")):
        if n:
            chk.partial(f"{n} performance rows excluded: {why}")
    cohorts: dict[tuple, dict] = {}
    unmatched: dict[str, int] = {}
    for key, m, val in sorted(rows, key=lambda x: (x[0][0], x[0][1], x[0][2], -1 if x[0][3] is None else x[0][3])):
        if key in dups:
            continue
        cid, region, d, h = key
        for sig, cfg in sorted(configs.items()):
            v = series.get((sig, region, d, h)) if hourly else None
            if v is None:
                v = series.get((sig, region, d, None))
            if v is None:
                unmatched[sig] = unmatched.get(sig, 0) + 1
                continue
            c = cohorts.setdefault((cid, sig, bucket(v, cfg["bounds"], cfg["labels"])), _new_cohort())
            c["rows"] += 1
            c["periods"].add((d, h))
            for k in ("impressions", "clicks", "cost", "conversions"):
                c[k] += m[k]
            if val is None:
                c["value_known"] = False
            else:
                c["value"] += val
            wd = WEEKDAYS[d.weekday()]
            c["weekday"][wd] = c["weekday"].get(wd, 0) + 1
    for sig, n in sorted(unmatched.items()):
        chk.partial(f"signal '{sig}': {n} performance rows without a signal value (unmatched, not neutral)")
    grain = "hourly" if hourly else "daily"
    for cid in sorted({k[0] for k in cohorts}):
        track, tnote = ctx.tracking_for_campaign(cid)
        conv_ok = ctx.mature is True and track is True
        if not conv_ok:
            chk.partial(f"campaign {cid}: conversion comparisons descriptive only "
                        f"(maturity {ctx.mature}: {ctx.maturity_note}; {tnote})")
        roas_primary = _roas_objective(ctx, cid)
        for sig, cfg in sorted(configs.items()):
            base = cohorts.get((cid, sig, cfg["baseline"]))
            for label in cfg["labels"]:
                c = cohorts.get((cid, sig, label))
                if c is None:
                    continue
                summary = {k: c[k] for k in ("rows", "impressions", "clicks", "cost", "conversions")}
                summary.update(periods=len(c["periods"]), weekday=c["weekday"],
                               value=c["value"] if c["value_known"] else None, **_rates(c))
                if label == cfg["baseline"] or base is None:
                    chk.observe(f"Campaign {cid} {sig} [{grain}] bucket '{label}'", campaign_id=cid, signal=sig,
                                bucket=label, baseline=cfg["baseline"], grain=grain, cohort=summary,
                                note=None if base else "baseline bucket has no data: no comparison")
                    continue
                cmp = _compare(base, c, gates, conv_ok, roas_primary)
                bsum = {k: base[k] for k in ("rows", "impressions", "clicks", "cost", "conversions")}
                bsum.update(periods=len(base["periods"]), weekday=base["weekday"])
                ev = {"campaign_id": cid, "signal": sig, "grain": grain, "bucket": label, "baseline": cfg["baseline"],
                      "bucket_cohort": summary, "baseline_cohort": bsum, "comparison": cmp,
                      "window": [ctx.period_start, ctx.period_end], "maturity": ctx.mature, "tracking": tnote,
                      "tolerance": cfg["tolerance"],
                      "gates": {k: {"value": g.value, "source": g.source} for k, g in gates.items()}}
                chk.observe(f"Campaign {cid} {sig} [{grain}] '{label}' vs '{cfg['baseline']}'", **ev)
                direction, metric, rel = _direction(cmp)
                if cfg["tolerance"] is None or direction is None or abs(rel) < cfg["tolerance"]:
                    continue
                ev.update(direction=direction, decisive_metric=metric, relative_difference=rel)
                entity = {"campaign_id": cid, "signal": sig, "bucket": label, "grain": grain}
                qualified[(cid, sig, label)] = qualified.get((cid, sig, label)) or ev
                prov = chk.finding("signal_bucket_difference", "Info", entity,
                                   f"Campaign {cid}: {metric} in {sig} bucket '{label}' differs {rel:+.1%} from "
                                   f"baseline '{cfg['baseline']}' ({grain}, tolerance {cfg['tolerance']:g})",
                                   evidence=ev, calculation={"formula": f"{metric}_bucket / {metric}_baseline - 1",
                                                             "relative_difference": rel},
                                   recommendation="Treat as a hypothesis; consider a controlled experiment before any rule.",
                                   uncertainty="Observational, non-randomized periods: weekday, promotion, seasonality "
                                               "and region mix may confound; correlation is not causation.")
                chk.review("signal_bucket_difference", entity,
                           f"Is the {direction} {metric} difference in {sig} bucket '{label}' for campaign {cid} worth "
                           "a request-only controlled test or schedule rule, or is it confounded?",
                           evidence=ev, provisional=prov,
                           outcomes={
                               "test_worth_proposing": {"severity": "Info", "recommendation":
                                                        "Request the verified experiment/schedule-rule proposal."},
                               "confounded_or_not_actionable": {"severity": None, "recommendation":
                                                                "No proposal; record the confounder."},
                               "uncertain": {"severity": "Info", "recommendation":
                                             "Collect more comparable periods before proposing anything."},
                           },
                           guidance="Compare weekday mix, periods and region mix; check promotions/seasonality. "
                                    "proposal = {type: experiment|schedule_rule, campaign_id, signal, bucket, "
                                    "primary_metric, duration_days, stop_rule, approval_owner, and allocation "
                                    "(experiment) or action bid_modifier|ad_schedule with modifier}. No uplift forecast.")


def run(ctx) -> None:
    """Run external-signal series, profile bucket definitions and signal-rule consistency checks.

    Rules:   Buckets only from profile.external_signals (no defaults); excluded rows are reported, never zero-filled.
             Both cohorts must pass min_impressions/min_clicks/min_conversions; conversion metrics also ctx.mature True
             and tracking. A qualified difference >= declared tolerance → provisional Info + ai_review, never causal.
             Rule contradictions → Info + review (Warning outcome 'rule_contradicted'). No live signal fetches.
    """
    sig_chk = ctx.check("signal_series", "Supplied external signal series", {"external/external_signals": SIGNAL_COLS})
    cfg_chk = ctx.check("bucket_definitions", "Profile bucket definitions per signal")
    configs = _configs(ctx, cfg_chk)
    series = _series(ctx, sig_chk, configs) if sig_chk.runnable else {}
    gates = {k: ctx.params.get(k) for k in ("min_impressions", "min_clicks", "min_conversions")}
    qualified: dict[tuple, dict] = {}
    for cid, title, key, hourly in GRAINS:
        cols = PERF_COLS + (["hour"] if hourly else [])
        chk = ctx.check(cid, title, {key: cols, "external/external_signals": SIGNAL_COLS})
        if not chk.runnable:
            continue
        if not configs:
            chk.skip("no valid bucket definitions", cfg_chk.missing or ["profile.external_signals"])
            continue
        _align(ctx, chk, key, hourly, series, configs, gates, qualified)

    rules = ctx.check("signal_rule_consistency", "Existing signal rules vs qualified differences",
                      {"external/signal_rules": ["rule_id", "signal_name", "bucket", "campaign_id", "action",
                                                 "modifier", "status"]})
    if not rules.runnable:
        return
    if not any(c.id in ("daily_alignment", "hourly_alignment") and c.runnable for c in ctx.result.checks):
        rules.skip("no alignment grain ran", ["custom/campaign_geo_daily (file)", "custom/campaign_geo_hourly (file)"])
        return
    for r in sorted(ctx.rows("external/signal_rules"), key=lambda r: str(r.get("rule_id"))):
        if str(r.get("status") or "").upper() not in ("ENABLED", "ACTIVE"):
            continue
        cid, sig, label = str(r.get("campaign_id")), V.norm_text(r.get("signal_name")), str(r.get("bucket"))
        action = str(r.get("action") or "").lower()
        mod = V.num(r.get("modifier"))
        ev = qualified.get((cid, sig, label))
        base = {"rule_id": r.get("rule_id"), "campaign_id": cid, "signal": sig, "bucket": label,
                "action": action, "modifier": mod}
        if ev is None:
            rules.observe(f"Rule {r.get('rule_id')}: no qualified difference to compare", **base)
            continue
        raise_ = action == "bid_modifier" and mod is not None and mod > 0
        cut = (action == "bid_modifier" and mod is not None and mod < 0) or action == "pause"
        contradicted = (raise_ and ev["direction"] == "unfavorable") or (cut and ev["direction"] == "favorable")
        rules.observe(f"Rule {r.get('rule_id')} vs {ev['direction']} bucket", contradicted=contradicted, **base)
        if not contradicted:
            continue
        entity = {"campaign_id": cid, "signal": sig, "bucket": label, "rule_id": str(r.get("rule_id"))}
        rev = {**base, "difference": {k: ev[k] for k in ("direction", "decisive_metric", "relative_difference",
                                                         "grain", "bucket_cohort", "baseline_cohort", "tolerance")}}
        prov = rules.finding("signal_rule_contradicted", "Info", entity,
                             f"Rule {r.get('rule_id')} ({action} {mod}) acts against the {ev['direction']} "
                             f"{ev['decisive_metric']} difference ({ev['relative_difference']:+.1%}) in bucket '{label}'",
                             evidence=rev, recommendation="Confirm the rule's intent before any change request.",
                             uncertainty="Observational cohorts; the rule itself may have shaped the bucket's results.")
        rules.review("signal_rule_contradicted", entity,
                     f"Is rule {r.get('rule_id')} ({action} {mod}) an unintended contradiction of the qualified "
                     f"{ev['direction']} difference, or a deliberate trade-off (e.g. volume over efficiency)?",
                     evidence=rev, provisional=prov,
                     outcomes={"rule_contradicted": {"severity": "Warning", "recommendation":
                                                     "Request a controlled review of this rule; do not auto-invert it."},
                               "intentional_tradeoff": {"severity": None, "recommendation": "Keep; document the intent."},
                               "uncertain": {"severity": "Info", "recommendation": "Ask the rule owner for its objective."}},
                     guidance="Use profile objectives and the rule's documented purpose; unknown intent → uncertain.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: only 'test_worth_proposing' carries a proposal; it must match scope and controls."""
    if item.condition_key != "signal_bucket_difference" or decision.get("outcome") != "test_worth_proposing":
        return []
    p = decision.get("proposal") or {}
    ent, ev = item.entity, item.evidence
    problems = []
    for k in ("campaign_id", "signal", "bucket"):
        if str(p.get(k) or "") != str(ent[k]):
            problems.append(f"proposal.{k} must equal reviewed {k} {ent[k]!r}")
    kind = str(p.get("type") or "")
    if kind not in ("experiment", "schedule_rule"):
        problems.append("proposal.type must be experiment or schedule_rule")
    if p.get("primary_metric") not in ("ctr", "cvr", "cpa", "roas"):
        problems.append("proposal.primary_metric must be ctr, cvr, cpa or roas")
    days = V.num(p.get("duration_days"))
    if days is None or days <= 0:
        problems.append("proposal.duration_days must be a positive number")
    for k in ("stop_rule", "approval_owner"):
        if not str(p.get(k) or "").strip():
            problems.append(f"proposal.{k} required")
    forecast = sorted(k for k in p if k in FORECAST_KEYS)
    if forecast:
        problems.append(f"forecast fields {forecast} not allowed: correlation is a hypothesis")
    if kind == "experiment" and not str(p.get("allocation") or "").strip():
        problems.append("experiment needs proposal.allocation")
    if kind == "schedule_rule":
        action = str(p.get("action") or "")
        if action not in ("bid_modifier", "ad_schedule"):
            problems.append("schedule_rule action must be bid_modifier or ad_schedule")
        if action == "ad_schedule" and ent.get("grain") != "hourly":
            problems.append("ad_schedule proposals need an hourly-grain difference")
        if action == "bid_modifier":
            mod = V.num(p.get("modifier"))
            row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == str(ent["campaign_id"])), None)
            strategy = str((row or {}).get("bidding_strategy_type") or "").upper()
            if mod is None or not (MODIFIER_RANGE[0] <= mod <= MODIFIER_RANGE[1]) or mod == 0:
                problems.append(f"modifier must be a nonzero fraction within {MODIFIER_RANGE}")
            elif (mod > 0) != (ev.get("direction") == "favorable"):
                problems.append(f"modifier sign contradicts the observed {ev.get('direction')} difference")
            if not strategy:
                problems.append("campaign bidding_strategy_type unknown: bid-modifier support unverifiable")
            elif strategy in SMART_BIDDING:
                problems.append(f"{strategy} is Smart Bidding: location/schedule bid modifiers are ignored; propose an experiment")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
