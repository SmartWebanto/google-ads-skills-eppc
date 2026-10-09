"""check.py — skill-056 deterministic device shares, efficiency index, zero-conversion screen and control proposals.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-056-device-performance-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #26 Extended Devices, Locations and Audiences Bidding (Brainlabs) — clean-room reimplementation of
         device CPA vs campaign baseline; modifiers only as capped, bounds-checked Manual CPC test proposals
rules:   Device metrics from custom/device_performance summed per (campaign, device); shares use campaign
         device totals; rates only for positive denominators (zero-conversion CPA is N/A).
         Baseline = other comparable devices of the SAME campaign; CONNECTED_TV/TV and UNKNOWN/OTHER devices are
         reported in shares but not compared (_NONCOMPARABLE).
         Efficiency index = baseline CPA / device CPA - 1, only when device and baseline each have
         >= min_conversions and ctx.mature is True. index < -0.2 → Warning; > +0.2 → Info. Weekly persistence
         (complete Mon-Sun weeks inside the window) is attached as evidence, not a gate.
         Zero-conversion: mature + ctx.tracking_for_campaign True + cost >= spend_floor(campaign) → provisional
         Info + review (Warning only after tracking/relevance review); never automatic exclusion.
         Controls only from custom/device_controls: CPC_multiplier under MANUAL_CPC → raw 1+index capped to
         [0.9, 1.1] × current_value, clamped to [permitted_min, permitted_max]; CPA_target_adjustment → target
         effect description only; exclusion/unsupported/other strategies → no adjustment. Missing controls →
         diagnostic-only (partial).
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

SKILL = "skill-056-device-performance-analysis"
VERSION = "1.0.0"

_DEV = "custom/device_performance"
_CTRL = "custom/device_controls"
_COLS = ["campaign_id", "date", "device", "impressions", "clicks", "cost", "conversions", "conversion_value"]
_NONCOMPARABLE = {"CONNECTED_TV", "TV", "UNKNOWN", "OTHER", "UNSPECIFIED"}
_ADVERSE, _GOOD = -0.2, 0.2
_CAP = (0.9, 1.1)


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _mult(v) -> float | None:
    s = _s(v)
    if s.endswith("%"):
        f = V.num(s[:-1])
        return None if f is None else 1 + f / 100
    return V.num(v)


def _aggregate(ctx, chk) -> tuple[dict, dict]:
    """campaign → device → [imp, clicks, cost, conv, value]; plus campaign → device → date → [cost, conv]."""
    agg: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    unknown = 0
    for r in ctx.rows(_DEV):
        vals = [V.num(r.get("impressions")), V.num(r.get("clicks")), ctx.money(r.get("cost")),
                V.num(r.get("conversions")), V.num(r.get("conversion_value"))]
        d = V.parse_date(r.get("date"))
        if None in vals[:4] or d is None:
            unknown += 1
            continue
        cid, dev = _s(r.get("campaign_id")), _s(r.get("device")).upper() or "UNKNOWN"
        a = agg.setdefault(cid, {}).setdefault(dev, [0.0] * 5)
        for i in range(5):
            a[i] += vals[i] or 0
        dd = daily.setdefault(cid, {}).setdefault(dev, {}).setdefault(d, [0.0, 0.0])
        dd[0] += vals[2]
        dd[1] += vals[3]
    if unknown:
        chk.partial(f"{unknown} device rows with unknown metrics/date excluded")
    return agg, daily


def _weekly(ctx, daily_c: dict, dev: str) -> list[dict]:
    """Per complete Mon-Sun week inside the account window: device index vs other comparable devices."""
    if ctx.period_start is None or ctx.period_end is None:
        return []
    start = ctx.period_start + timedelta(days=(7 - ctx.period_start.weekday()) % 7)
    out = []
    while start + timedelta(days=6) <= ctx.period_end:
        days = [start + timedelta(days=i) for i in range(7)]
        mine = [sum(daily_c.get(dev, {}).get(d, [0, 0])[i] for d in days) for i in range(2)]
        rest = [sum(v.get(d, [0, 0])[i] for k, v in daily_c.items() if k != dev and k not in _NONCOMPARABLE
                    for d in days) for i in range(2)]
        cpa, bcpa = V.ratio(mine[0], mine[1]), V.ratio(rest[0], rest[1])
        idx = V.ratio(bcpa, cpa)
        out.append({"week_start": start, "index": None if idx is None else idx - 1,
                    "conversions": mine[1], "baseline_conversions": rest[1]})
        start += timedelta(days=7)
    return out


def run(ctx) -> None:
    """Run device share, efficiency index, zero-conversion and bid-control checks per campaign.

    Rules:   Missing device report skips all checks. Warning (index < -0.2) / Info (> +0.2) need ctx.mature and >=
             min_conversions on the device and its same-campaign baseline; TV/UNKNOWN/OTHER devices are never compared.
             Zero-conversion devices need maturity, tracking True and cost >= spend_floor → provisional Info + review.
             Without custom/device_controls the run is diagnostic-only (partial); multipliers only under MANUAL_CPC.
    """
    rec = ctx.check("device_reconciliation", "Device totals vs campaign totals (step 1)",
                    {_DEV: _COLS, "campaign_metrics": ["campaign_id", "cost"]})
    later = (("device_shares", "Cost/impression/click/conversion/value shares and rates (step 2)"),
             ("efficiency_index", "Device vs other devices of the same campaign (steps 3-4; index #26)"),
             ("zero_conversion_screen", "Zero-conversion devices with tracking and spend floor (step 4)"),
             ("control_proposal", "Supported control semantics and bounded test values (steps 5-7)"))
    dev_t = ctx.table(_DEV)
    if dev_t is None or dev_t.missing(_COLS):
        missing = [f"{_DEV} (file)"] if dev_t is None else [f"{_DEV}:{c}" for c in dev_t.missing(_COLS)]
        if rec.runnable:
            rec.skip("device report unavailable", missing)
        for cid, title in later:
            ctx.check(cid, title).skip("device report unavailable", missing)
        return
    agg, daily = _aggregate(ctx, rec)
    if rec.runnable:
        totals = {_s(m.get("campaign_id")): ctx.money(m.get("cost")) for m in ctx.rows("campaign_metrics")}
        for cid, devs in sorted(agg.items()):
            cost = sum(v[2] for v in devs.values())
            rec.observe(f"Campaign {cid}: device cost vs campaign cost", campaign_id=cid, device_cost=cost,
                        campaign_cost=totals.get(cid), coverage=V.ratio(cost, totals.get(cid)), currency=ctx.currency)
        rec.partial("strategy-change history not supplied: window assumed one strategy regime")

    sh = ctx.check(later[0][0], later[0][1], {_DEV: _COLS})
    for cid, devs in sorted(agg.items()):
        tot = [sum(v[i] for v in devs.values()) for i in range(5)]
        sh.observe(f"Campaign {cid}: device shares and rates", campaign_id=cid,
                   devices={d: {"cost_share": V.ratio(v[2], tot[2]), "impression_share": V.ratio(v[0], tot[0]),
                                "click_share": V.ratio(v[1], tot[1]), "conversion_share": V.ratio(v[3], tot[3]),
                                "value_share": V.ratio(v[4], tot[4]), "cpa": V.ratio(v[2], v[3]),
                                "cvr": V.ratio(v[3], v[1]), "roas": V.ratio(v[4], v[2]), "cost": v[2],
                                "conversions": v[3]} for d, v in sorted(devs.items())},
                   noncomparable=sorted(set(devs) & _NONCOMPARABLE))

    min_conv = ctx.params.get("min_conversions")
    eff = ctx.check(later[1][0], later[1][1], {_DEV: _COLS})
    if ctx.mature is not True:
        eff.partial(f"conversion maturity not established ({ctx.maturity_note}); no efficiency judgments")
    signals: list[dict] = []
    for cid, devs in sorted(agg.items()):
        for dev, a in sorted(devs.items()):
            if dev in _NONCOMPARABLE:
                continue
            b = [sum(v[i] for k, v in devs.items() if k != dev and k not in _NONCOMPARABLE) for i in range(5)]
            ok = min_conv.value is not None and a[3] >= min_conv.value and b[3] >= min_conv.value
            cpa, bcpa = V.ratio(a[2], a[3]), V.ratio(b[2], b[3])
            ratio = V.ratio(bcpa, cpa) if ok else None
            row = {"campaign_id": cid, "device": dev, "cost": a[2], "conversions": a[3], "cpa": cpa,
                   "baseline_cost": b[2], "baseline_conversions": b[3], "baseline_cpa": bcpa,
                   "index": None if ratio is None else ratio - 1, "sample_ok": ok,
                   "min_conversions": min_conv.value, "min_conversions_source": min_conv.source,
                   "window": [ctx.period_start, ctx.period_end], "currency": ctx.currency}
            signals.append(row)
            if row["index"] is None or ctx.mature is not True:
                continue
            ent = {"campaign_id": cid, "device": dev}
            ev = {**row, "weekly": _weekly(ctx, daily.get(cid, {}), dev)}
            if row["index"] < _ADVERSE:
                eff.finding("adverse_device_efficiency", "Warning", ent,
                            f"{dev} in campaign {cid}: efficiency index {row['index']:+.2f} vs other devices",
                            evidence=ev, calculation={"index": "baseline CPA / device CPA - 1", "threshold": _ADVERSE},
                            recommendation="Review tracking and device UX first; a bounded control test only where "
                                           "supported (control_proposal). No causal device claim.",
                            uncertainty="Acquisition mix, landing pages and lag can explain the gap; check weekly persistence.")
            elif row["index"] > _GOOD:
                eff.finding("device_efficiency_opportunity", "Info", ent,
                            f"{dev} in campaign {cid}: efficiency index {row['index']:+.2f} vs other devices",
                            evidence=ev, calculation={"index": "baseline CPA / device CPA - 1", "threshold": _GOOD},
                            recommendation="Opportunity hypothesis; consider a bounded test where supported.",
                            uncertainty="No uplift forecast.")
    eff.observe("Device comparisons evaluated", comparisons=len(signals),
                qualified=[{k: s[k] for k in ("campaign_id", "device", "index")} for s in signals if s["sample_ok"]])

    zc = ctx.check(later[2][0], later[2][1], {_DEV: _COLS})
    if ctx.mature is not True:
        zc.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    else:
        unresolved = set()
        for s in signals:
            if s["conversions"] != 0 or not s["cost"]:
                continue
            ok, note = ctx.tracking_for_campaign(s["campaign_id"])
            if ok is not True:
                unresolved.add(note)
                continue
            floor = ctx.params.get("spend_floor", s["campaign_id"])
            if floor.value is None or s["cost"] < floor.value:
                continue
            ent = {"campaign_id": s["campaign_id"], "device": s["device"]}
            ev = {**s, "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": note}
            prov = zc.finding("zero_conversion_device", "Info", ent,
                              f"{s['device']} in campaign {s['campaign_id']} spent {s['cost']:.2f} {ctx.currency} with "
                              f"0 conversions (spend_floor {floor.value:g})", evidence=ev,
                              recommendation="Tracking/relevance investigation; no automatic exclusion.",
                              uncertainty="Device-specific tracking or UX issues and lag can explain zero conversions.")
            zc.review("zero_conversion_device", ent,
                      f"After tracking/relevance review, does zero-conversion {s['device']} spend in campaign "
                      f"{s['campaign_id']} warrant investigation?", evidence=ev, provisional=prov,
                      outcomes={"investigate": {"severity": "Warning", "recommendation":
                                                "Investigate device tracking/UX before any eligibility restriction."},
                                "explained": {"severity": None, "recommendation": "Document the explanation."},
                                "uncertain": {"severity": "Info", "recommendation": "Resolve tracking evidence first."}})
        for n in sorted(unresolved):
            zc.partial(f"tracking not verified: {n}")

    cp = ctx.check(later[3][0], later[3][1], {_CTRL: ["campaign_id", "device", "snapshot_date", "control_type",
                                                      "current_value", "permitted_min", "permitted_max",
                                                      "strategy_type", "support_source_url"]})
    if cp.runnable:
        _controls(ctx, cp, signals)


def _controls(ctx, cp, signals) -> None:
    ctrl = {(_s(r.get("campaign_id")), _s(r.get("device")).upper()): r for r in ctx.rows(_CTRL)}
    for s in signals:
        if s["index"] is None or ctx.mature is not True or not (s["index"] < _ADVERSE or s["index"] > _GOOD):
            continue
        key = (s["campaign_id"], s["device"])
        r = ctrl.get(key)
        ent = {"campaign_id": key[0], "device": key[1]}
        if r is None:
            cp.partial(f"{key[0]} {key[1]}: control unknown; diagnostic only")
            continue
        ctype, strat = _s(r.get("control_type")).upper(), _s(r.get("strategy_type")).upper()
        cur = _mult(r.get("current_value"))
        lo, hi = _mult(r.get("permitted_min")), _mult(r.get("permitted_max"))
        base = {**ent, "control_type": ctype, "strategy_type": strat, "current_value": cur,
                "permitted_min": lo, "permitted_max": hi, "support_source_url": r.get("support_source_url"),
                "snapshot_date": r.get("snapshot_date"), "index": s["index"]}
        if ctype == "CPC_MULTIPLIER" and strat == "MANUAL_CPC":
            if cur is None or cur == 0:
                cp.observe(f"{key[1]} in {key[0]}: current multiplier unknown or excluded; no test value", **base)
                continue
            inc = min(max(1 + s["index"], _CAP[0]), _CAP[1])
            prop = cur * inc
            clamped = prop if lo is None or hi is None else min(max(prop, lo), hi)
            cp.observe(f"{key[1]} in {key[0]}: bounded Manual CPC test value", **base, raw_incremental=1 + s["index"],
                       capped_incremental=inc, proposed_value=clamped, clamped=clamped != prop,
                       bounds_known=lo is not None and hi is not None,
                       note="Bounded initial test heuristic, not optimal sizing; owner approval required.")
        elif ctype == "CPA_TARGET_ADJUSTMENT":
            tgt, src = ctx.params.target_cpa(key[0])
            cp.observe(f"{key[1]} in {key[0]}: tCPA device adjustment changes the device CPA target", **base,
                       base_target_cpa=tgt, base_target_source=src,
                       effective_device_target=None if tgt is None or cur is None else tgt * cur,
                       note="Describe the target effect; the CPC formula is not reused.")
        else:
            cp.observe(f"{key[1]} in {key[0]}: no adjustment proposed ({ctype or 'unknown'} under {strat or '?'})",
                       **base, note="Exclusion needs business necessity and owner intent; propose tracking/UX review.")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
