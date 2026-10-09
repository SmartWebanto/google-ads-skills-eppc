"""check.py — skill-071 deterministic conversion reconciliation against owner rules, with direct cross-device evidence.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-071-conversion-tracking-accuracy/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Only rules whose currency, timezone and date basis match the account are comparable; others are
         Info 'incomparable_cohort' and excluded. Business events count only at the rule's source_event stage,
         deduplicated by deduplication_key_token (else event_token) inside the account period; stages are never merged.
         Variance = (Ads - expected) / expected; zero/unknown denominators are undefined (Info), never 0%.
         tolerance_count_pct / tolerance_value_pct are PERCENT numbers (10 = 10%). Missing tolerance → partial.
         Residual Warning needs ctx.mature True, every daily row reporting_mature, snapshot - period_end >= the
         rule's maturity_days, and an expected count >= min_conversions. Its cause is AI judgment; Critical only via
         ai_review with proposal.evidence_ref AND proposal.corroboration_ref (Ads excess alone is not Critical).
         A local send ledger beyond tolerance is a deterministic Warning; its materiality (Critical) is reviewed.
         Cross-device: only measured, unsuppressed numerators <= denominators; modeled data is disclosed, not concluded.
         Never use all_conversions, device splits or Enhanced Conversions absence as cross-device proxies.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial deterministic check
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

SKILL = "skill-071-conversion-tracking-accuracy"
VERSION = "1.0.0"

RULES = "external/reconciliation_rules"
EVENTS = "external/business_events"
LEDGER = "external/ads_event_reconciliation"
DAILY = "custom/ads_reconciliation_daily"
XDEV = "external/cross_device_measured"
RULE_NEEDS = ["action_id", "business_event_id", "source_event", "counting_unit", "date_basis", "timezone", "currency",
              "maturity_days", "tolerance_count_pct", "tolerance_value_pct"]
EVENT_NEEDS = ["event_token", "action_id", "event_timestamp", "stage", "deduplication_key_token", "expected_value",
               "currency"]
DAILY_NEEDS = ["action_id", "date", "conversions", "conversion_value", "currency", "reporting_mature"]


def _s(v) -> str:
    return str(v or "").strip()


def _n(v) -> str:
    return "_".join(_s(v).lower().replace("-", " ").split())


def _alnum(v) -> str:
    return "".join(ch for ch in _s(v) if ch.isalnum()).lower()


def _account_rows(ctx, key) -> list[dict]:
    acct = _alnum(ctx.account_id)
    return [r for r in ctx.rows(key)
            if not (acct and _s(r.get("account_id")) and _alnum(r.get("account_id")) != acct)]


def _pct(v) -> float | None:
    f = V.num(v)
    return f / 100 if f is not None and f >= 0 else None


def _in_period(ctx, v) -> bool:
    d = V.parse_date(_s(v)[:10])
    return d is not None and ctx.period_start is not None and ctx.period_end is not None and \
        ctx.period_start <= d <= ctx.period_end


def run(ctx) -> None:
    """Run cohort alignment, business-event dedup, send-ledger and aggregate variance and direct cross-device checks.

    Rules:   Mismatched currency/timezone/date basis → Info 'incomparable_cohort', excluded. Zero/unknown expected →
             Info undefined. Ledger residual beyond tolerance → deterministic Warning; aggregate residual Warning needs
             ctx.mature True, mature daily rows, maturity_days elapsed and expected >= min_conversions; missing
             tolerance → partial. Cause is ai_review; Critical only via review outcomes. Modeled or proxy cross-device
             data never becomes a finding.
    """
    # -- step 1: alignment
    al = ctx.check("cohort_alignment", "Align currency, timezone, date basis and attribution per rule", {RULES: RULE_NEEDS})
    later = (("business_event_dedup", "Deduplicated comparable business events"),
             ("ledger_compare", "Local send/upload ledger versus expected events"),
             ("aggregate_variance", "Mature count/value variance versus owner tolerance"))
    if not al.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("reconciliation rules unavailable: no comparable cohort", al.missing)
        _cross_device(ctx)
        return
    actions = {_s(a.get("id")): a for a in ctx.rows("conversion_actions")}
    acct_basis = _n(ctx.account.get("conversion_date_basis"))
    acct_tz = _s(ctx.account.get("time_zone"))
    rules: dict[str, dict] = {}
    for r in sorted(_account_rows(ctx, RULES), key=lambda r: (_s(r.get("action_id")), _s(r.get("business_event_id")))):
        aid = _s(r.get("action_id"))
        issues = []
        if _s(r.get("currency")).upper() != (ctx.currency or ""):
            issues.append(f"currency {r.get('currency')} vs account {ctx.currency}")
        if _s(r.get("timezone")) != acct_tz:
            issues.append(f"timezone {r.get('timezone')} vs account {acct_tz or 'unknown'}")
        if _n(r.get("date_basis")) != acct_basis:
            issues.append(f"date basis {r.get('date_basis')} vs account {acct_basis or 'unknown'}")
        a = actions.get(aid) or {}
        attribution = {"rule_model": r.get("attribution_model"), "action_model": a.get("attribution_model"),
                       "rule_lookback_days": r.get("lookback_days"), "action_click_window_days": a.get("click_window_days"),
                       "rule_counting_unit": r.get("counting_unit"), "action_counting": a.get("counting")}
        explained = [k for k, x, y in (("attribution_model", "rule_model", "action_model"),
                                       ("lookback", "rule_lookback_days", "action_click_window_days"))
                     if _s(attribution[x]) and _s(attribution[y]) and _n(attribution[x]) != _n(attribution[y])]
        rules[aid] = {**r, "_issues": issues, "_attribution": attribution, "_explained": explained}
        ent = {"action_id": aid, "business_event_id": _s(r.get("business_event_id"))}
        if issues:
            al.finding("incomparable_cohort", "Info", ent, f"Rule for action {aid} is not comparable: {'; '.join(issues)}",
                       evidence={"issues": issues, **attribution},
                       recommendation="Align currency/timezone/date basis with the owner before any variance.",
                       uncertainty="No residual is derived for this cohort.")
        al.observe(f"Rule alignment for action {aid}", **ent, comparable=not issues, issues=issues,
                   attribution_differences=explained, **attribution)
    comparable = {a: r for a, r in rules.items() if not r["_issues"]}

    # -- step 2: business event dedup
    ev_chk = ctx.check("business_event_dedup", "Deduplicated comparable business events", {EVENTS: EVENT_NEEDS})
    expected: dict[str, dict] = {}
    if ev_chk.runnable:
        by_action: dict[str, list] = {}
        for e in _account_rows(ctx, EVENTS):
            by_action.setdefault(_s(e.get("action_id")), []).append(e)
        for aid, r in sorted(comparable.items()):
            stage = _n(r.get("source_event"))
            keys, dup, other_stage, outside, fx, unknown_value = {}, 0, 0, 0, 0, 0
            for e in sorted(by_action.get(aid, []), key=lambda e: (_s(e.get("event_timestamp")), _s(e.get("event_token")))):
                if _n(e.get("stage")) != stage:
                    other_stage += 1
                    continue
                if not _in_period(ctx, e.get("event_timestamp")):
                    outside += 1
                    continue
                if _s(e.get("currency")).upper() not in ("", ctx.currency or ""):
                    fx += 1
                    continue
                k = _s(e.get("deduplication_key_token")) or _s(e.get("event_token"))
                if k in keys:
                    dup += 1
                    continue
                keys[k] = e
            vals = [V.num(e.get("expected_value")) for e in keys.values()]
            unknown_value = sum(1 for v in vals if v is None)
            refunds = sum(V.num(e.get("refund_value_to_snapshot")) or 0 for e in keys.values())
            expected[aid] = {"count": len(keys), "value": None if unknown_value else sum(vals),
                             "unknown_value_events": unknown_value}
            if fx:
                ev_chk.partial(f"action {aid}: {fx} events in another currency excluded")
            ev_chk.observe(f"Comparable business events for action {aid}", action_id=aid, source_event=stage,
                           window=[ctx.period_start, ctx.period_end], distinct_events=len(keys),
                           duplicates_removed=dup, other_stage_events=other_stage, outside_window=outside,
                           expected_value=expected[aid]["value"], unknown_value_events=unknown_value,
                           refund_value_to_snapshot=refunds, value_basis=r.get("value_basis"),
                           refund_treatment=r.get("refund_treatment"))

    # -- step 3: local ledger
    lg = ctx.check("ledger_compare", "Local send/upload ledger versus expected events",
                   {LEDGER: ["event_token", "action_id", "expected_send_count", "observed_send_count", "accepted_count",
                             "rejected_count"]})
    if lg.runnable:
        by_action: dict[str, dict] = {}
        for e in _account_rows(ctx, LEDGER):
            a = by_action.setdefault(_s(e.get("action_id")), {"expected": 0.0, "observed": 0.0, "accepted": 0.0,
                                                              "rejected": 0.0, "duplicate_tokens": [], "missing_tokens": [],
                                                              "unknown": 0})
            ex, ob = V.num(e.get("expected_send_count")), V.num(e.get("observed_send_count"))
            if ex is None or ob is None:
                a["unknown"] += 1
                continue
            a["expected"] += ex
            a["observed"] += ob
            a["accepted"] += V.num(e.get("accepted_count")) or 0
            a["rejected"] += V.num(e.get("rejected_count")) or 0
            if ob > ex:
                a["duplicate_tokens"].append(_s(e.get("event_token")))
            elif ob < ex:
                a["missing_tokens"].append(_s(e.get("event_token")))
        for aid in sorted(by_action):
            a = by_action[aid]
            rate = V.ratio(a["observed"] - a["expected"], a["expected"])
            tol = _pct((comparable.get(aid) or {}).get("tolerance_count_pct"))
            ent = {"action_id": aid}
            ev = {"expected_sends": a["expected"], "observed_sends": a["observed"], "accepted": a["accepted"],
                  "rejected": a["rejected"], "duplicate_tokens": len(a["duplicate_tokens"]),
                  "missing_tokens": len(a["missing_tokens"]), "unknown_rows": a["unknown"],
                  "signed_residual": a["observed"] - a["expected"], "residual_rate": rate, "tolerance": tol,
                  "note": "ledger proves sends, not individual Ads attribution"}
            lg.observe(f"Send ledger for action {aid}", **ent, **ev)
            if aid not in comparable:
                lg.partial(f"action {aid}: no comparable rule, ledger tolerance unknown")
                continue
            if tol is None or rate is None:
                lg.partial(f"action {aid}: tolerance or expected sends unavailable")
                continue
            if abs(rate) > tol:
                lg.finding("ledger_residual_exceeds_tolerance", "Warning", ent,
                           f"Action {aid}: observed sends {a['observed']:g} vs expected {a['expected']:g} "
                           f"({rate:+.1%}) exceed tolerance {tol:.1%}", evidence=ev,
                           calculation={"formula": "(observed - expected) / expected", "tolerance_source": RULES},
                           recommendation="Owner review of duplicate/missing sends; tag diagnostics → 072/073.",
                           uncertainty="Materiality not established by the ledger alone.")
                lg.review("ledger_residual_material", ent,
                          f"Is there independent evidence that the ledger discrepancy for {aid} is MATERIAL "
                          f"(bidding or reporting decisions affected)?",
                          evidence=ev, outcomes={"material_confirmed": {"severity": "Critical", "recommendation":
                                                                        "Prioritize fix; cite corroborating evidence."},
                                                 "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
                          guidance="Critical requires proposal.evidence_ref and proposal.corroboration_ref.")

    # -- steps 4-6: aggregate variance
    agg = ctx.check("aggregate_variance", "Mature count/value variance versus owner tolerance",
                    {RULES: RULE_NEEDS, EVENTS: EVENT_NEEDS, DAILY: DAILY_NEEDS})
    if agg.runnable:
        cols = ctx.table(DAILY).columns
        grain = [c for c in ("account_id", "campaign_id", "action_id", "date", "date_basis") if c in cols]
        seen: dict[tuple, dict | None] = {}
        for r in _account_rows(ctx, DAILY):
            g = tuple(_s(r.get(c)) for c in grain)
            if g in seen:
                if seen[g] is not None and seen[g] != r:
                    seen[g] = None
                continue
            seen[g] = r
        conflicts = sum(1 for v in seen.values() if v is None)
        if conflicts:
            agg.partial(f"{conflicts} conflicting daily rows at {grain} excluded")
        mv = ctx.params.get("min_conversions").value
        gap = (ctx.snapshot - ctx.period_end).days if ctx.snapshot and ctx.period_end else None
        for aid, rule in sorted(comparable.items()):
            rows = [r for r in seen.values() if r is not None and _s(r.get("action_id")) == aid
                    and _in_period(ctx, r.get("date"))]
            fx = [r for r in rows if _s(r.get("currency")).upper() not in ("", ctx.currency or "")]
            rows = [r for r in rows if r not in fx]
            counts = [V.num(r.get("conversions")) for r in rows]
            values = [ctx.money(r.get("conversion_value")) for r in rows]
            immature = sum(1 for r in rows if V.boolean(r.get("reporting_mature")) is not True)
            modeled = sorted({_s(r.get("modeled_included")) for r in rows if _s(r.get("modeled_included"))})
            ads_n = None if None in counts else sum(counts)
            ads_v = None if None in values else sum(values)
            exp = expected.get(aid) or {"count": None, "value": None}
            mdays = V.integer(rule.get("maturity_days"))
            mature = (ctx.mature is True and immature == 0 and rows != [] and gap is not None
                      and mdays is not None and gap >= mdays)
            ent = {"action_id": aid, "business_event_id": _s(rule.get("business_event_id"))}
            cvar = V.ratio(None if ads_n is None or exp["count"] is None else ads_n - exp["count"], exp["count"])
            vvar = V.ratio(None if ads_v is None or exp["value"] is None else ads_v - exp["value"], exp["value"])
            tol_c, tol_v = _pct(rule.get("tolerance_count_pct")), _pct(rule.get("tolerance_value_pct"))
            ev = {"ads_count": ads_n, "expected_count": exp["count"], "count_variance": cvar,
                  "signed_count_difference": None if cvar is None else ads_n - exp["count"],
                  "ads_value": ads_v, "expected_value": exp["value"], "value_variance": vvar,
                  "signed_value_difference": None if vvar is None else ads_v - exp["value"],
                  "tolerance_count": tol_c, "tolerance_value": tol_v, "window": [ctx.period_start, ctx.period_end],
                  "daily_rows": len(rows), "other_currency_rows": len(fx), "immature_rows": immature,
                  "modeled_included": modeled, "attribution_differences": rule["_explained"],
                  "maturity_days": mdays, "snapshot_gap_days": gap, "currency": ctx.currency}
            agg.observe(f"Reconciliation for action {aid}", **ent, **ev)
            if exp["count"] == 0:
                agg.finding("zero_denominator", "Info", ent,
                            f"Action {aid}: no comparable business events; relative variance unavailable",
                            evidence=ev, recommendation="Confirm the event mapping and window with the owner.",
                            uncertainty="Absolute Ads count reported; no percentage derived.")
                continue
            if not mature:
                agg.partial(f"action {aid}: not mature (ctx {ctx.mature}, immature rows {immature}, "
                            f"gap {gap}d vs maturity_days {mdays})")
                continue
            if exp["count"] is None or exp["count"] < mv:
                agg.partial(f"action {aid}: expected count {exp['count']} below min_conversions {mv}")
                continue
            if tol_c is None and tol_v is None:
                agg.partial(f"action {aid}: owner tolerances missing; residual not classified")
                continue
            breaches = [n for n, var, tol in (("count", cvar, tol_c), ("value", vvar, tol_v))
                        if var is not None and tol is not None and abs(var) > tol]
            if not breaches:
                continue
            prov = agg.finding("residual_exceeds_tolerance", "Warning", ent,
                               f"Action {aid}: mature {'/'.join(breaches)} residual exceeds owner tolerance "
                               f"(count {cvar if cvar is None else f'{cvar:+.1%}'}, value "
                               f"{vvar if vvar is None else f'{vvar:+.1%}'})",
                               evidence=ev, calculation={"formula": "(Ads - expected) / expected",
                                                         "tolerance_source": RULES, "min_conversions": mv},
                               recommendation="Identify attribution/modeling/consent/window differences with the owner "
                                              "before diagnosing a fault; policy → 107, refunds → 112, settings → 076.",
                               uncertainty="Cause and materiality uncertain; CRM totals need not equal Ads-attributed.")
            agg.review("residual_exceeds_tolerance", ent,
                       f"Is the residual for action {aid} explained by attribution/modeling/consent/window/counting "
                       f"differences, or independently corroborated as duplicate/missing/wrong-value events?",
                       evidence=ev, provisional=prov,
                       outcomes={"explained_difference": {"severity": "Info", "recommendation": "Document the explanation."},
                                 "unexplained_residual": {"severity": "Warning", "recommendation":
                                                          "Owner investigation of the residual."},
                                 "confirmed_fault_material": {"severity": "Critical", "recommendation":
                                                              "Prioritize the fix; cite corroboration."},
                                 "uncertain": {"severity": "Warning", "recommendation": "Keep as unexplained residual."}},
                       guidance="Ads excess alone is not Critical. confirmed_fault_material requires proposal.evidence_ref "
                                "and proposal.corroboration_ref (independent duplicate/missing/wrong-value evidence).")
    _cross_device(ctx)


def _cross_device(ctx) -> None:
    """Steps 7-8: direct measured cross-device contribution only."""
    xd = ctx.check("cross_device_direct", "Direct measured cross-device contribution",
                   {XDEV: ["action_id", "source_metric_name", "measured_cross_device_conversions",
                           "comparable_total_conversions", "modeled_included", "suppression_status"]})
    if not xd.runnable:
        return
    for r in sorted(_account_rows(ctx, XDEV), key=lambda r: (_s(r.get("action_id")), _s(r.get("window_start")))):
        aid = _s(r.get("action_id"))
        num, den = V.num(r.get("measured_cross_device_conversions")), V.num(r.get("comparable_total_conversions"))
        ent = {"action_id": aid, "window": [r.get("window_start"), r.get("window_end")]}
        ev = {"source_metric_name": r.get("source_metric_name"), "measured": num, "total": den,
              "total_metric_definition": r.get("total_metric_definition"), "modeled_included": r.get("modeled_included"),
              "suppression_status": r.get("suppression_status"), "method": r.get("method"),
              "source_reference": r.get("source_reference")}
        supp = _s(r.get("suppression_status")).lower()
        if supp and supp not in ("none", "no", "false", "not_suppressed", "unsuppressed"):
            xd.partial(f"action {aid}: suppressed direct measurement ({supp})")
            xd.observe(f"Cross-device measurement suppressed for {aid}", **ent, **ev)
            continue
        if V.boolean(r.get("modeled_included")) is not False:
            xd.partial(f"action {aid}: modeled data included or unknown; measured-only conclusion skipped")
            xd.observe(f"Cross-device metric for {aid} includes modeling (disclosed)", **ent, **ev)
            continue
        if num is None or den is None or den <= 0 or num < 0 or num > den:
            xd.partial(f"action {aid}: numerator is not a measured subset of a positive denominator")
            continue
        xd.finding("direct_cross_device_contribution", "Info", ent,
                   f"Action {aid}: {num:g} of {den:g} conversions directly measured as cross-device",
                   evidence={**ev, "share": V.ratio(num, den)},
                   recommendation="Context only; no device bid change or gap/uplift estimate.",
                   uncertainty="Scope is the source report's; not an estimate of missing paths.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes need proposal.evidence_ref and proposal.corroboration_ref."""
    if decision.get("outcome") not in ("confirmed_fault_material", "material_confirmed"):
        return []
    p = decision.get("proposal") or {}
    return [f"proposal.{f} required for Critical" for f in ("evidence_ref", "corroboration_ref") if not _s(p.get(f))]


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
