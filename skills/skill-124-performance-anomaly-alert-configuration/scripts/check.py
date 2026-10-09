"""check.py — skill-124 deterministic same-weekday anomaly screen and request-only alert configuration.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-124-performance-anomaly-alert-configuration/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #16 Account Anomaly Detector (Google developers) — clean-room reimplementation of the account-total
         same-weekday baseline comparison for impressions/clicks/cost/conversions
         index #19 Alert when account is down (Frederick Vallaeys) — clean-room reimplementation of the zero-delivery
         check (account/campaign with 0 impressions after a delivering same-weekday baseline) as a review, not a diagnosis
         index #42 Change in Campaign Spending Alert (Brainlabs) — clean-room reimplementation of campaign cost
         deviation versus its own baseline, inside the same 2-SD + relative screen
         index #75 PMax Shopping Spend Drop Alert (nilsrooijmans.com) — partial: PMax campaign cost drops use the campaign
         cost screen; the Shopping-channel split is not in this recipe's daily grain (see skill-128)
         index #100 Declining Ad Groups Report (Google developers) — clean-room reimplementation of three consecutive
         weekly pooled-CTR declines at the file's stable grain, Info only
rules:   Complete days only: date <= min(ctx.as_of, snapshot - 1). Candidates are the last 7 complete days. Each baseline
         uses the same weekday in the prior 8 weeks, minus dates covered by a documented anomaly_context event for the
         entity (each exclusion keeps its event id).
         Conversion metrics need a mature candidate (date + lag <= snapshot); unknown lag leaves them unevaluated.
         Grain: ad_group_id present → ad-group entities only; rows lacking it are dropped, grains are never mixed.
         Screen per count metric: |x-mean| > 2 x sample SD AND |x/mean-1| > relative threshold (policy, else 0.30) AND
         baseline n >= minimum_baseline_periods (policy, else 8). Warning only when a policy row for the entity/metric
         declares absolute_threshold and |x-mean| >= it. Otherwise Info.
         Zero mean or SD → degenerate: only the policy absolute threshold applies, Info. Sparse baseline → Info.
         CTR/CVR/CPA pool numerators/denominators and require min_impressions/min_clicks/min_conversions on both sides.
         Critical only via review: a context row with incident_confirmed true and evidence_ref for the entity/date;
         verify() demands that exact evidence_ref. Anomalies are not diagnoses; nothing is configured or sent.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

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

SKILL = "skill-124-performance-anomaly-alert-configuration"
VERSION = "1.0.0"

DAILY = "custom/anomaly_daily"
CONTEXT = "custom/anomaly_context"
POLICY = "external/alert_policy"
COUNTS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
CONV_METRICS = ("conversions", "conversion_value")
DEFAULT_REL, DEFAULT_MIN_BASELINE, SD_MULT = 0.30, 8, 2.0
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _ekey(entity: dict) -> str:
    return entity.get("ad_group_id") or entity.get("campaign_id") or "account"


def _entity(key: tuple) -> dict:
    if key[0] == "account":
        return {"scope": "account"}
    if key[0] == "campaign":
        return {"scope": "campaign", "campaign_id": key[1]}
    return {"scope": "ad_group", "campaign_id": key[1], "ad_group_id": key[2]}


def _load(ctx, chk, last: date) -> tuple[dict, str]:
    """{entity_key: {date: {metric: value|None}}}; account totals added under ('account',)."""
    t = ctx.table(DAILY)
    grain = "ad_group" if "ad_group_id" in t.columns and any(r.get("ad_group_id") for r in t.rows) else "campaign"
    series: dict[tuple, dict] = {}
    seen, dupes, dropped, late = set(), 0, 0, 0
    has_value = "conversion_value" in t.columns
    for r in sorted(t.rows, key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("date")))):
        d = V.parse_date(r.get("date"))
        if d is None or d > last:
            late += 1
            continue
        if grain == "ad_group" and not r.get("ad_group_id"):
            dropped += 1
            continue
        key = ("campaign", str(r.get("campaign_id"))) if grain == "campaign" else \
            ("ad_group", str(r.get("campaign_id")), str(r.get("ad_group_id")))
        if (key, d) in seen:
            dupes += 1
            continue
        seen.add((key, d))
        vals = {m: (ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))) for m in COUNTS
                if m != "conversion_value" or has_value}
        series.setdefault(key, {})[d] = vals
        acc = series.setdefault(("account",), {}).setdefault(d, {m: 0.0 for m in vals})
        for m, v in vals.items():
            acc[m] = None if acc.get(m) is None or v is None else acc[m] + v
    if dupes:
        chk.partial(f"{dupes} duplicate entity/date rows ignored")
    if dropped:
        chk.partial(f"{dropped} rows without ad_group_id dropped: grains are not mixed")
    if late:
        chk.observe("Incomplete or unparseable dates excluded", rows=late, last_complete_day=last)
    return series, grain


def _events(ctx) -> list[dict]:
    out = []
    for r in ctx.rows(CONTEXT):
        s, e = V.parse_date(r.get("start_at")), V.parse_date(r.get("end_at")) or V.parse_date(r.get("start_at"))
        if s is None:
            continue
        out.append({"event_id": r.get("event_id"), "entity_id": str(r.get("entity_id") or "").strip(), "start": s,
                    "end": e, "type": r.get("event_type"), "metrics": [m.lower() for m in V.split_list(r.get("affected_metrics"), (";", "|", ","))],
                    "confirmed": V.boolean(r.get("incident_confirmed")) is True, "evidence_ref": r.get("evidence_ref")})
    return out


def _applies(ev: dict, key: tuple, account_id) -> bool:
    ids = {"account", "*", "all", str(account_id or "")}
    if key[0] != "account":
        ids |= set(key[1:])
    return ev["entity_id"].lower() in {i.lower() for i in ids if i}


def _policy(ctx, key: tuple, metric: str) -> dict | None:
    rows = [p for p in ctx.rows(POLICY) if V.norm_text(p.get("metric")) == metric]
    scope = lambda p: str(p.get("entity_scope") or "").strip().lower()
    ident = key[-1] if key[0] != "account" else "account"
    exact = [p for p in rows if scope(p) == ident.lower()]
    generic = [p for p in rows if scope(p) in ("*", "all") or (key[0] == "account" and scope(p) == "account")]
    pick = sorted(exact or generic, key=lambda p: str(p.get("policy_id")))
    return pick[0] if pick else None


def _sd(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def run(ctx) -> None:
    """Run alert policy, baseline, count-metric screen, pooled-rate, zero-delivery and CTR-trend checks.

    Rules:   No daily series → skipped; missing anomaly_context or lag → partial and conversion metrics unscreened.
             Warning only when the 2-SD and relative screens pass AND an alert_policy absolute_threshold for that
             entity/metric is met; sparse/degenerate baselines, rate shifts and CTR trends stay Info. Critical only via
             review citing an incident_confirmed context evidence_ref; nothing is configured or sent.
    """
    last = min(d for d in (ctx.as_of, ctx.snapshot - timedelta(days=1) if ctx.snapshot else None) if d) \
        if (ctx.as_of or ctx.snapshot) else None
    needs = {DAILY: ["campaign_id", "date", "impressions", "clicks", "cost", "conversions"]}
    base = ctx.check("baseline_window", "Complete same-weekday 8-week baselines", needs)
    rates = ctx.check("pooled_rates", "Pooled CTR/CVR/CPA with both-side sample gates", needs)
    screen = ctx.check("deviation_screen", "2-SD and relative-change screen with policy floor", needs)
    ctxc = ctx.check("context_review", "Change, incident and lag context",
                     {CONTEXT: ["entity_id", "event_id", "start_at", "end_at", "event_type", "affected_metrics",
                                "incident_confirmed", "evidence_ref"]})
    zero = ctx.check("zero_delivery", "Zero delivery after a delivering baseline", needs)
    decline = ctx.check("weekly_decline", "Three consecutive weekly CTR declines", needs)
    config = ctx.check("alert_config", "Request-only alert configuration",
                       {POLICY: ["policy_id", "entity_scope", "metric", "relative_threshold", "absolute_threshold",
                                 "minimum_baseline_periods", "cadence", "cooldown", "recipient_role", "owner",
                                 "confirmation_required"]})
    policy_t = ctx.table(POLICY)
    policy_ok = policy_t is not None and not policy_t.missing(["policy_id", "entity_scope", "metric", "absolute_threshold"])
    if config.runnable:
        for p in sorted(ctx.rows(POLICY), key=lambda p: str(p.get("policy_id"))):
            missing = [c for c in ("cadence", "cooldown", "recipient_role", "owner", "absolute_threshold") if not p.get(c)]
            if missing:
                config.partial(f"policy {p.get('policy_id')}: missing {', '.join(missing)}")
            config.observe(f"Policy {p.get('policy_id')}: request-only alert specification", policy_id=p.get("policy_id"),
                           entity_scope=p.get("entity_scope"), metric=p.get("metric"),
                           time_basis=f"complete account-local days ({ctx.account.get('time_zone')})",
                           screen=f"|x-mean| > {SD_MULT:g} SD AND relative > {p.get('relative_threshold') or DEFAULT_REL} "
                                  f"AND |x-mean| >= {p.get('absolute_threshold')}",
                           minimum_baseline_periods=p.get("minimum_baseline_periods") or DEFAULT_MIN_BASELINE,
                           exclusions="documented anomaly_context events; immature conversion days",
                           cadence=p.get("cadence"), dedupe_cooldown=p.get("cooldown"), recipient_role=p.get("recipient_role"),
                           owner=p.get("owner"), approved_spend_cap=p.get("approved_spend_cap"),
                           confirmation_required=p.get("confirmation_required"),
                           recovery_condition="metric back inside the screen for one full cadence period",
                           action="alert only; no subscription, notification or account change is configured here")
    if not base.runnable or last is None:
        for c in (base, rates, screen, zero, decline):
            if c.runnable:
                c.skip("daily anomaly evidence unavailable", base.missing or ["account:date_range_end"])
        if ctxc.runnable:
            ctxc.skip("no daily series to cross-reference", base.missing or ["account:date_range_end"])
        return
    series, grain = _load(ctx, base, last)
    events = _events(ctx) if ctxc.runnable else []
    if not ctxc.runnable:
        base.partial("anomaly_context missing: incident/promotion exclusions and explanations unknown", ctxc.missing)
    lag = ctx.lag_days
    if lag is None or ctx.snapshot is None:
        base.partial("conversion lag or snapshot unknown: conversion metrics not screened")
    mature = lambda d: lag is not None and ctx.snapshot is not None and d + timedelta(days=lag) <= ctx.snapshot
    candidates = [last - timedelta(days=i) for i in range(6, -1, -1)]
    if not policy_ok:
        screen.partial("no usable alert_policy (policy_id/entity_scope/metric/absolute_threshold): Warning path disabled",
                       [f"{POLICY} (file)"] if policy_t is None else [f"{POLICY}:{c}" for c in
                                                                      policy_t.missing(["policy_id", "entity_scope", "metric", "absolute_threshold"])])

    # reconciliation with campaign_metrics over the account period
    if ctx.table("campaign_metrics") is not None and ctx.period_start and ctx.period_end:
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: str(r.get("campaign_id"))):
            cid = str(m.get("campaign_id"))
            daily = [v["cost"] for k, s in series.items() if k[0] != "account" and k[1] == cid
                     for d, v in s.items() if ctx.period_start <= d <= ctx.period_end]
            base.observe(f"Campaign {cid}: daily versus period cost", campaign_id=cid,
                         daily_cost=None if any(x is None for x in daily) else sum(daily),
                         period_cost=ctx.money(m.get("cost")), daily_rows=len(daily))

    min_impr, min_clicks, min_conv = (ctx.params.get(n) for n in ("min_impressions", "min_clicks", "min_conversions"))
    counts = {"screened": 0, "sparse": 0, "degenerate": 0, "no_baseline": 0}
    excluded_dates: dict[str, list] = {}
    for key in sorted(series):
        s = series[key]
        entity = _entity(key)
        ev_for = [e for e in events if _applies(e, key, ctx.account_id)]
        for d in candidates:
            if d not in s:
                continue
            base_days = []
            for k in range(1, 9):
                b = d - timedelta(days=7 * k)
                hit = next((e for e in ev_for if e["start"] <= b <= e["end"]), None)
                if hit:
                    excluded_dates.setdefault(_ekey(entity), []).append({"date": b, "event_id": hit["event_id"],
                                                                         "event_type": hit["type"]})
                elif b in s:
                    base_days.append(b)
            cand_events = [e for e in ev_for if e["start"] <= d <= e["end"]]
            # -- counts: 2-SD + relative screen
            for metric in [m for m in COUNTS if m in s[d]]:
                if metric in CONV_METRICS and not mature(d):
                    continue
                x = s[d][metric]
                vals = [s[b][metric] for b in base_days if s[b].get(metric) is not None]
                if x is None or not vals:
                    counts["no_baseline"] += 1
                    continue
                pol = _policy(ctx, key, metric) if policy_ok else None
                rel_t = ctx.rate(pol.get("relative_threshold")) if pol and pol.get("relative_threshold") else DEFAULT_REL
                min_n = V.integer(pol.get("minimum_baseline_periods")) if pol and pol.get("minimum_baseline_periods") else DEFAULT_MIN_BASELINE
                absolute = None
                if pol:
                    absolute = ctx.money(pol.get("absolute_threshold")) if metric in ("cost", "conversion_value") \
                        else V.num(pol.get("absolute_threshold"))
                mean = sum(vals) / len(vals)
                sd = _sd(vals)
                dev = x - mean
                rel = V.ratio(dev, mean)
                z = V.ratio(dev, sd)
                ev = {"date": d, "weekday": WEEKDAYS[d.weekday()], "metric": metric, "value": x, "baseline_dates": base_days,
                      "baseline_n": len(vals), "baseline_mean": mean, "baseline_sd": sd, "absolute_deviation": dev,
                      "relative_change": rel, "z": z, "relative_threshold": rel_t, "sd_multiple": SD_MULT,
                      "minimum_baseline_periods": min_n, "absolute_threshold": absolute,
                      "policy_id": pol.get("policy_id") if pol else None, "grain": grain,
                      "context_events": [{"event_id": e["event_id"], "type": e["type"], "confirmed": e["confirmed"]}
                                         for e in cand_events]}
                fent = {**entity, "metric": metric, "date": d}
                if len(vals) < min_n:
                    counts["sparse"] += 1
                    if rel is not None and abs(rel) > rel_t:
                        screen.finding("sparse_baseline_deviation", "Info", fent,
                                       f"{_ekey(entity)} {metric} on {d}: {rel:+.0%} versus {len(vals)} baseline days "
                                       f"(< {min_n}); sparse baseline", evidence={**ev, "branch": "sparse"},
                                       recommendation="Collect the full 8-week baseline before alerting on this metric.",
                                       uncertainty="Too few comparable weekdays; not an alert-worthy defect.")
                    continue
                if not mean or not sd:
                    counts["degenerate"] += 1
                    if absolute is not None and abs(dev) >= absolute:
                        screen.finding("degenerate_baseline_deviation", "Info", fent,
                                       f"{_ekey(entity)} {metric} on {d}: deviation {dev:+.2f} >= absolute {absolute:g} "
                                       f"with zero baseline {'mean' if not mean else 'SD'}",
                                       evidence={**ev, "branch": "degenerate_absolute"},
                                       recommendation="Review with the policy owner; relative/Z scores are undefined here.",
                                       uncertainty="Degenerate baseline; triage only.")
                    continue
                counts["screened"] += 1
                sd_hit, rel_hit = abs(z) > SD_MULT, abs(rel) > rel_t
                floor_hit = absolute is not None and abs(dev) >= absolute
                if sd_hit and rel_hit:
                    sev = "Warning" if floor_hit else "Info"
                    why = "policy impact floor met" if floor_hit else \
                        ("no policy absolute floor" if absolute is None else f"below policy floor {absolute:g}")
                    f = screen.finding("anomaly_screen_met", sev, fent,
                                       f"{_ekey(entity)} {metric} on {d} ({d:%a}): {x:g} vs mean {mean:.2f} "
                                       f"({rel:+.0%}, z {z:+.1f}); {why}", evidence={**ev, "branch": "two_screens"},
                                       calculation={"z": "(value - mean) / sample SD", "relative": "value / mean - 1"},
                                       recommendation="Check the listed context and change history; draft an alert-only "
                                                      "rule with the policy owner. Do not treat as a diagnosed failure.",
                                       uncertainty="Descriptive triage, not statistical significance or root cause.")
                    confirmed = [e for e in cand_events if e["confirmed"] and e["evidence_ref"]]
                    if confirmed:
                        ctxc.review("anomaly_screen_met", fent,
                                    f"Does confirmed incident {', '.join(str(e['event_id']) for e in confirmed)} make this "
                                    f"{metric} deviation a material delivery/measurement failure?",
                                    evidence={**ev, "confirmed_events": confirmed},
                                    outcomes={"confirmed_material_failure": {"severity": "Critical", "recommendation":
                                              "Escalate to the owner with the incident evidence; recovery check required."},
                                              "not_material": {"severity": None, "recommendation": f"Keep as {f.severity}."}},
                                    guidance="Critical requires proposal.evidence_ref equal to a confirmed event evidence_ref.")
                elif rel_hit and floor_hit:
                    screen.finding("anomaly_below_screen", "Info", fent,
                                   f"{_ekey(entity)} {metric} on {d}: {rel:+.0%} meets the relative and absolute floors "
                                   f"but not the {SD_MULT:g}-SD screen (z {z:+.1f})",
                                   evidence={**ev, "branch": "relative_only"},
                                   recommendation="Watch; unexplained movement below the alert screen.",
                                   uncertainty="Below the 2-SD screen; ordinary variance is plausible.")
            # -- pooled rates: both-side sample gates
            if rates.runnable:
                pool = lambda days, num, den: (sum(s[b][num] for b in days if s[b].get(num) is not None and s[b].get(den) is not None),
                                               sum(s[b][den] for b in days if s[b].get(num) is not None and s[b].get(den) is not None))
                for name, num, den, gate in (("ctr", "clicks", "impressions", min_impr), ("cvr", "conversions", "clicks", min_clicks),
                                             ("cpa", "cost", "conversions", min_conv)):
                    if num in CONV_METRICS or den in CONV_METRICS:
                        if not mature(d):
                            continue
                    bn, bd = pool(base_days, num, den)
                    cn, cd = s[d].get(num), s[d].get(den)
                    ok = gate.value is not None and cd is not None and bd >= gate.value and cd >= gate.value
                    br, cr = V.ratio(bn, bd), V.ratio(cn, cd)
                    change = V.ratio(None if cr is None or br is None else cr - br, br)
                    rp = _policy(ctx, key, name) if policy_ok else None
                    rate_t = ctx.rate(rp.get("relative_threshold")) if rp and rp.get("relative_threshold") else DEFAULT_REL
                    if ok and change is not None and abs(change) > rate_t:
                        rates.finding("pooled_rate_shift", "Info", {**entity, "metric": name, "date": d},
                                      f"{_ekey(entity)} {name.upper()} on {d}: {cr:.4g} vs pooled baseline {br:.4g} ({change:+.0%})",
                                      evidence={"date": d, "metric": name, "candidate": [cn, cd], "baseline_pooled": [bn, bd],
                                                "baseline_dates": base_days, "gate": gate.name, "gate_value": gate.value,
                                                "relative_change": change, "relative_threshold": rate_t},
                                      recommendation="Context review only; a rate shift is not a diagnosed failure.",
                                      uncertainty="Pooled ratio of sums; no SD screen for rates.")
    screen.observe("Screen totals", **counts, candidates=[candidates[0], candidates[-1]], entities=len(series), grain=grain)
    base.observe("Baseline construction", candidate_dates=[candidates[0], candidates[-1]], last_complete_day=last,
                 excluded_baseline_dates=excluded_dates, weeks=8, grain=grain)
    if ctxc.runnable:
        ctxc.observe("Context events available", events=len(events), confirmed=sum(1 for e in events if e["confirmed"]))

    # -- index #19: zero delivery after a delivering same-weekday baseline
    for key in sorted(k for k in series if k[0] != "ad_group"):
        s, entity = series[key], _entity(key)
        zero_days = [d for d in candidates if d in s and s[d].get("impressions") == 0]
        # explicit zero rows only: an omitted daily row is unknown, never zero
        zero_days = sorted(set(zero_days))
        if not zero_days:
            continue
        d = zero_days[0]
        prior = [s[d - timedelta(days=7 * k)].get("impressions") for k in range(1, 9) if d - timedelta(days=7 * k) in s]
        if not prior or any(p is None or p <= 0 for p in prior):
            continue
        ev_for = [e for e in events if _applies(e, key, ctx.account_id) and e["start"] <= zero_days[-1] and e["end"] >= d]
        ev = {"zero_impression_dates": zero_days, "baseline_impressions": prior, "context_events":
              [{"event_id": e["event_id"], "type": e["type"], "confirmed": e["confirmed"], "evidence_ref": e["evidence_ref"]}
               for e in ev_for]}
        fent = {**entity, "since": d}
        prov = zero.finding("zero_delivery", "Info", fent,
                            f"{_ekey(entity)} served 0 impressions from {d} after a delivering same-weekday baseline",
                            evidence=ev, recommendation="Check status/change history and billing before any escalation.",
                            uncertainty="Zero delivery can be an intentional pause, end date or schedule.")
        zero.review("zero_delivery", fent, f"Is the zero delivery of {_ekey(entity)} from {d} intentional, or a delivery failure?",
                    evidence=ev, provisional=prov,
                    outcomes={"confirmed_delivery_failure": {"severity": "Critical", "recommendation":
                              "Escalate with the confirmed incident evidence; recovery check after fix."},
                              "intentional_or_explained": {"severity": None, "recommendation": "Document the reason."},
                              "unconfirmed": {"severity": "Info", "recommendation": "Ask the owner; add a confirmed-incident log."}},
                    guidance="Critical requires proposal.evidence_ref equal to a confirmed anomaly_context evidence_ref "
                             "for this entity; enabled status alone proves nothing.")
    zero.observe("Zero-delivery scan", entities=len([k for k in series if k[0] != "ad_group"]), candidates=len(candidates))

    # -- index #100: three consecutive weekly CTR declines at the stable grain
    week_end = last - timedelta(days=(last.weekday() + 1) % 7)
    weeks = [(week_end - timedelta(days=7 * i + 6), week_end - timedelta(days=7 * i)) for i in range(3, -1, -1)]
    flagged = 0
    for key in sorted(k for k in series if k[0] != "account"):
        s, entity = series[key], _entity(key)
        pooled = []
        for ws, we in weeks:
            days = [d for d in s if ws <= d <= we and s[d].get("impressions") is not None and s[d].get("clicks") is not None]
            impr = sum(s[d]["impressions"] for d in days)
            pooled.append((impr, V.ratio(sum(s[d]["clicks"] for d in days), impr), len(days)))
        if any(p[1] is None or p[2] < 7 or min_impr.value is None or p[0] < min_impr.value for p in pooled):
            continue
        ctrs = [p[1] for p in pooled]
        if all(ctrs[i] > ctrs[i + 1] for i in range(3)):
            flagged += 1
            decline.finding("declining_ctr_trend", "Info", {**entity, "weeks_ending": week_end},
                            f"{_ekey(entity)} weekly CTR fell three weeks in a row: " + " > ".join(f"{c:.2%}" for c in ctrs),
                            evidence={"weeks": [[ws, we] for ws, we in weeks], "weekly_impressions": [p[0] for p in pooled],
                                      "weekly_ctr": ctrs, "min_impressions": min_impr.value},
                            recommendation="Review ads, queries and competition for this entity; trend only.",
                            uncertainty="Pooled weekly CTR; seasonality and mix shifts can explain the trend.")
    decline.observe("Weekly CTR trend scan", entities=len([k for k in series if k[0] != "account"]), flagged=flagged,
                    weeks=[[ws, we] for ws, we in weeks], grain=grain)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes need proposal.evidence_ref equal to a confirmed context evidence_ref for the entity."""
    if decision.get("outcome") not in ("confirmed_material_failure", "confirmed_delivery_failure"):
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return ["Critical needs proposal.evidence_ref from anomaly_context"]
    e = item.entity
    key = ("account",) if e.get("scope") == "account" else ("campaign", e["campaign_id"]) if e.get("scope") == "campaign" \
        else ("ad_group", e["campaign_id"], e["ad_group_id"])
    ok = [x for x in _events(ctx) if x["confirmed"] and str(x["evidence_ref"] or "").strip() == ref and _applies(x, key, ctx.account_id)]
    return [] if ok else [f"evidence_ref '{ref}' is not a confirmed incident for this entity in anomaly_context"]


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
