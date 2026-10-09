"""check.py — skill-057 deterministic joint day×hour heatmap, schedule eligibility states and bounded schedule tests.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-057-ad-schedule-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #22 Apply ad schedules to campaigns or Shopping campaigns and set bid modifiers (Said Tezel) —
         clean-room reimplementation of "per-slot schedule bid modifiers" as request-only bounded test proposals
         (Manual CPC only, 0.9–1.1 × current interval modifier, platform range 0.1..10); nothing is applied.
         index #67 PMax Ad Schedule Suggestions (nilsrooijmans.com, reference only) — clean-room reimplementation of
         day/hour efficiency screening for Performance Max: analysed like other campaigns, but only owner-reviewed
         eligibility (on/off) tests are suggested, never bid modifiers.
rules:   Heatmap only from custom/day_hour_performance (joint date × hour rows); marginal reports are never joined
         into a heatmap. Rows are kept only if: timezone equals account.time_zone, day_of_week (English name/3-letter
         abbreviation) matches the date, hour is 0..23, the date lies in a COMPLETE 7-day week of the account period
         (trailing partial week dropped), it is not a DST transition date (zoneinfo) and not inside
         profile.event_calendar [{start, end, name}]. Duplicate (campaign, date, hour, segment) rows are excluded.
         Day-of-week and hour marginals are derived from the SAME joint table. Excluded/unobserved hours are not zero.
         Efficiency = (unit conv / campaign conv) / (unit cost / campaign cost) per campaign, same conversion column;
         needs ctx.mature True, unit and rest each >= min_conversions and >= min_clicks, and >= 4 complete weeks.
         <0.75 → Warning, >1.25 → Info; failing gates → one aggregated sparse Info per campaign.
         Zero-conversion units (cost >= spend_floor, mature, ctx.tracking_for_campaign True) → ai_review Warning outcome
         with provisional Info; cells inside an already flagged marginal are not re-flagged.
         Schedule states from custom/schedule_history (effective intervals incl. explicit all-day defaults): eligible,
         partial, excluded, unknown (no interval effective). A true zero needs a manifest-complete joint table.
         Business-hours contradictions are ai_review (Warning outcome); proposals verified by verify().
         schedule_history.bid_modifier is a multiplier (1.0 = no adjustment); unknown current modifier → no bid value.
         Smart Bidding (TARGET_CPA/TARGET_ROAS/MAXIMIZE_*) never receives schedule CPC modifiers.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-057-ad-schedule-optimization"
VERSION = "1.0.0"

DH = "custom/day_hour_performance"
SH = "custom/schedule_history"
BH = "external/business_hours"
DH_COLS = ["campaign_id", "date", "day_of_week", "hour", "impressions", "clicks", "cost", "conversions",
           "conversion_value", "timezone"]
SH_COLS = ["campaign_id", "schedule_id", "effective_start", "effective_end", "day_of_week", "start_hour",
           "start_minute", "end_hour", "end_minute", "bid_modifier", "timezone"]
BH_COLS = ["campaign_id", "day_of_week", "opens_at", "closes_at", "timezone", "after_hours_handling", "valid_from",
           "valid_to"]
DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
SMART = ("TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE")
SEGMENT_COLS = ("device", "network", "channel", "ad_network_type")
LOW, HIGH, MIN_WEEKS = 0.75, 1.25, 4


def _up(v) -> str:
    return str(v or "").strip().upper()


def _dow(v) -> int | None:
    s = _up(v)
    for i, d in enumerate(DAYS):
        if s == d or (len(s) == 3 and d.startswith(s)):
            return i
    return None


def _minutes(v) -> int | None:
    s = str(v or "").strip()
    if ":" not in s:
        return None
    h, m = V.integer(s.split(":")[0]), V.integer(s.split(":")[1][:2])
    return None if h is None or m is None or not (0 <= h <= 24 and 0 <= m < 60) else h * 60 + m


def _dst_dates(tz: str | None, start: date, end: date) -> tuple[set, str]:
    if not tz:
        return set(), "account time_zone unknown: DST boundaries not checked"
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(tz)
    except Exception as e:  # noqa: BLE001 — missing tz database is a coverage gap, not a crash
        return set(), f"time zone {tz} not resolvable ({type(e).__name__}): DST boundaries not checked"
    out, d = set(), start
    while d <= end:
        a = datetime(d.year, d.month, d.day, tzinfo=z).utcoffset()
        n = d + timedelta(days=1)
        if a != datetime(n.year, n.month, n.day, tzinfo=z).utcoffset():
            out.add(d)
        d = n
    return out, ""


def _events(ctx) -> set:
    out = set()
    for e in ctx.profile.get("event_calendar") or []:
        s, t = V.parse_date((e or {}).get("start")), V.parse_date((e or {}).get("end"))
        while s and t and s <= t:
            out.add(s)
            s += timedelta(days=1)
    return out


def _intervals(ctx) -> dict:
    """campaign_id -> list of (eff_start, eff_end, dow, start_min, end_min, modifier)."""
    out: dict = {}
    for r in ctx.rows(SH):
        dow = _dow(r.get("day_of_week"))
        sh, sm, eh, em = (V.integer(r.get(k)) for k in ("start_hour", "start_minute", "end_hour", "end_minute"))
        if dow is None or None in (sh, sm, eh, em):
            continue
        out.setdefault(str(r.get("campaign_id")), []).append(
            (V.parse_date(r.get("effective_start")), V.parse_date(r.get("effective_end")), dow, sh * 60 + sm,
             eh * 60 + em, V.num(r.get("bid_modifier"))))
    return out


def _state(ivs: list, d: date, hour: int) -> tuple[str, float | None]:
    """(eligible|partial|excluded|unknown, modifier) for campaign intervals on date d, hour."""
    live = [i for i in ivs if i[0] and i[0] <= d and (i[1] is None or d <= i[1])]
    if not live:
        return "unknown", None
    lo, hi = hour * 60, hour * 60 + 60
    hits = [i for i in live if i[2] == d.weekday() and i[3] < hi and i[4] > lo]
    full = [i for i in hits if i[3] <= lo and i[4] >= hi]
    if full:
        return "eligible", full[0][5]
    return ("partial", None) if hits else ("excluded", None)


def _strategy(ctx, cid) -> str:
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == str(cid)), {})
    return _up(row.get("bidding_strategy_type"))


def _channel(ctx, cid) -> str:
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == str(cid)), {})
    return _up(row.get("channel_type"))


def _label(unit) -> str:
    grain, dow, hour = unit
    return {"cell": f"{DAYS[dow]} {hour:02d}h", "day": DAYS[dow], "hour": f"{hour:02d}h (all days)"}[grain]


def run(ctx) -> None:
    """Run day × hour heatmap, marginal efficiency, zero-conversion window and schedule-state checks.

    Rules:   Only joint custom/day_hour_performance rows in complete weeks, account timezone, non-DST, non-event dates
             count. Efficiency < 0.75 → Warning, > 1.25 → Info, only with ctx.mature True, >= 4 weeks and
             min_conversions/min_clicks on unit and rest; failing gates → one sparse Info per campaign. Zero-conversion
             windows and service-hour contradictions → ai_review Warning outcomes. Smart Bidding never receives schedule
             CPC modifiers.
    """
    ta = ctx.check("time_alignment", "Timezone, day/hour and complete-week alignment", {DH: DH_COLS})
    titles = (("heatmap", "Joint day×hour heatmap with marginals from the same table"),
              ("efficiency", "Efficiency ratio vs rest of campaign"),
              ("zero_conversion", "Zero-conversion time windows (guarded)"))
    rows, weeks = [], 0
    if ta.runnable:
        if ctx.period_start is None or ctx.period_end is None:
            ta.skip("account period unknown", ["account:date_range_start", "account:date_range_end"])
    if ta.runnable:
        weeks = ((ctx.period_end - ctx.period_start).days + 1) // 7
        last = ctx.period_start + timedelta(days=7 * weeks - 1)
        dst, dst_note = _dst_dates(ctx.account.get("time_zone"), ctx.period_start, ctx.period_end)
        if dst_note:
            ta.partial(dst_note)
        events = _events(ctx)
        if not ctx.profile.get("event_calendar"):
            ta.partial("profile.event_calendar not supplied: holidays/promotions not excluded")
        tz = str(ctx.account.get("time_zone") or "")
        seg_cols = [c for c in SEGMENT_COLS if c in ctx.table(DH).columns]
        drop = {"timezone": 0, "day_mismatch": 0, "bad_hour": 0, "outside_complete_weeks": 0, "dst": 0, "event": 0,
                "duplicate": 0}
        seen, dups = set(), set()
        for r in ctx.rows(DH):
            d, h, dw = V.parse_date(r.get("date")), V.integer(r.get("hour")), _dow(r.get("day_of_week"))
            if not tz or str(r.get("timezone") or "") != tz:
                drop["timezone"] += 1
            elif d is None or dw is None or d.weekday() != dw:
                drop["day_mismatch"] += 1
            elif h is None or not 0 <= h <= 23:
                drop["bad_hour"] += 1
            elif not (ctx.period_start <= d <= last):
                drop["outside_complete_weeks"] += 1
            elif d in dst:
                drop["dst"] += 1
            elif d in events:
                drop["event"] += 1
            else:
                key = (str(r.get("campaign_id")), d, h) + tuple(str(r.get(c)) for c in seg_cols)
                if key in seen:
                    dups.add(key)
                seen.add(key)
                rows.append((key, r, d, h))
        rows = [x for x in rows if x[0] not in dups]
        drop["duplicate"] = len(dups)
        for k, v in sorted(drop.items()):
            if v and k != "outside_complete_weeks":
                ta.partial(f"{v} rows excluded: {k}")
        ta.observe("Joint day×hour alignment", rows_used=len(rows), excluded=drop, complete_weeks=weeks,
                   window=[ctx.period_start, last], timezone=tz, dst_dates=sorted(dst), segments=seg_cols,
                   conversion_date_basis=ctx.account.get("conversion_date_basis"))
    if not ta.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("joint day×hour evidence unavailable", ta.missing)

    # -- step 2: eligibility states
    es = ctx.check("eligibility_states", "Schedule eligibility states per slot", {SH: SH_COLS})
    ivs = _intervals(ctx) if es.runnable else {}
    ref = ctx.snapshot or ctx.period_end
    if es.runnable:
        dh_complete = ctx.table(DH) is not None and ctx.table(DH).complete is True
        observed = {(x[0][0], x[2], x[3]) for x in rows if (V.num(x[1].get("impressions")) or 0) > 0}
        dates = sorted({x[2] for x in rows}) or ([ctx.period_start + timedelta(days=i) for i in range(weeks * 7)]
                                                  if ctx.period_start else [])
        for cid in sorted(ivs):
            counts = {"observed_eligible": 0, "eligible_zero": 0, "eligible_no_record": 0, "partial": 0,
                      "excluded": 0, "excluded_with_traffic": 0, "unknown": 0}
            for d in dates:
                for h in range(24):
                    st, _ = _state(ivs[cid], d, h)
                    if st == "eligible":
                        k = "observed_eligible" if (cid, d, h) in observed else \
                            "eligible_zero" if dh_complete else "eligible_no_record"
                    elif st == "excluded":
                        k = "excluded_with_traffic" if (cid, d, h) in observed else "excluded"
                    else:
                        k = st
                    counts[k] += 1
            current = sorted({(DAYS[dw], h) for dw in range(7) for h in range(24)
                              if ref and _state(ivs[cid], ref - timedelta(days=(ref.weekday() - dw) % 7), h)[0] == "excluded"})
            es.observe(f"Campaign {cid}: eligibility states (date×hour slots)", campaign_id=cid, **counts,
                       currently_excluded_slots=len(current), reference_date=ref)
            if counts["excluded_with_traffic"]:
                es.partial(f"campaign {cid}: traffic recorded in slots the history marks excluded; history incomplete")
            if current:
                es.finding("excluded_hours", "Info", {"campaign_id": cid},
                           f"Campaign {cid} currently excludes {len(current)} weekly hour slots; their performance is "
                           "unobserved, not zero",
                           evidence={"excluded_slots": [f"{d} {h:02d}h" for d, h in current], "reference_date": ref},
                           recommendation="If relevant, propose an owner-reviewed observation test; no counterfactual exists.",
                           uncertainty="Excluded periods have no measured historical performance.")
        missing_c = sorted({x[0][0] for x in rows} - set(ivs))
        if missing_c:
            es.partial(f"no schedule history for campaigns {missing_c}: eligibility unknown")

    # -- step 3: heatmap
    units: dict = {}
    camp_tot: dict = {}
    if ta.runnable:
        hm = ctx.check("heatmap", "Joint day×hour heatmap with marginals from the same table")
        unknown_cells = 0
        for (key, r, d, h) in rows:
            cid = key[0]
            wk = (d - ctx.period_start).days // 7
            for unit in (("cell", d.weekday(), h), ("day", d.weekday(), -1), ("hour", -1, h)):
                u = units.setdefault(cid, {}).setdefault(unit, {m: 0.0 for m in METRICS} | {"weeks": set(), "unknown": set()})
                for m in METRICS:
                    v = ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))
                    if v is None:
                        u["unknown"].add(m)
                    else:
                        u[m] += v
                u["weeks"].add(wk)
            t = camp_tot.setdefault(cid, {m: 0.0 for m in METRICS} | {"unknown": set()})
            for m in METRICS:
                v = ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))
                if v is None:
                    t["unknown"].add(m)
                    unknown_cells += 1
                else:
                    t[m] += v
        if unknown_cells:
            hm.partial(f"{unknown_cells} unknown metric cells kept as unknown")
        for cid in sorted(units):
            cells = {}
            for unit, u in sorted(units[cid].items()):
                states = None
                if ivs.get(cid) and unit[0] == "cell":
                    states = {}
                    for i in range(weeks):
                        d0 = ctx.period_start + timedelta(days=7 * i)
                        d = d0 + timedelta(days=(unit[1] - d0.weekday()) % 7)
                        s = _state(ivs[cid], d, unit[2])[0]
                        states[s] = states.get(s, 0) + 1
                cells[_label(unit)] = {"grain": unit[0], "cost": u["cost"], "conversions": u["conversions"],
                                       "clicks": u["clicks"], "observed_weeks": len(u["weeks"]), "states": states,
                                       "cpa": V.ratio(u["cost"], u["conversions"]),
                                       "roas": V.ratio(u["conversion_value"], u["cost"]),
                                       "cvr": V.ratio(u["conversions"], u["clicks"])}
            hm.observe(f"Campaign {cid}: joint heatmap and marginals", campaign_id=cid, complete_weeks=weeks,
                       totals={m: camp_tot[cid][m] for m in METRICS}, cells=cells)

    # -- steps 4-6: efficiency + bounded proposals
    flagged_marginals: set = set()
    if ta.runnable:
        ef = ctx.check("efficiency", "Efficiency ratio vs rest of campaign")
        zc = ctx.check("zero_conversion", "Zero-conversion time windows (guarded)")
        mature = ctx.mature is True
        if not mature:
            ef.partial(f"conversion maturity not established ({ctx.maturity_note}); descriptive heatmap only")
            zc.partial(f"conversion maturity not established ({ctx.maturity_note})")
        if weeks < MIN_WEEKS:
            ef.partial(f"only {weeks} complete weeks (< {MIN_WEEKS}): persistence not established")
        mc, mk = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
        for cid in sorted(units):
            tot = camp_tot[cid]
            if {"cost", "conversions", "clicks"} & tot["unknown"] or tot["conversions"] <= 0 or tot["cost"] <= 0:
                ef.partial(f"campaign {cid}: campaign conversions/cost not positive or unknown; efficiency undefined")
                continue
            strat, chan = _strategy(ctx, cid), _channel(ctx, cid)
            sparse = []
            for unit in sorted(units[cid], key=lambda u: ({"day": 0, "hour": 1, "cell": 2}[u[0]], u[1], u[2])):
                u = units[cid][unit]
                if u["cost"] <= 0 or {"cost", "conversions", "clicks"} & u["unknown"]:
                    continue
                rest = {m: tot[m] - u[m] for m in METRICS}
                entity = {"campaign_id": cid, "grain": unit[0], "day_of_week": DAYS[unit[1]] if unit[1] >= 0 else None,
                          "hour": unit[2] if unit[2] >= 0 else None}
                ev = {"unit": _label(unit), "cost": u["cost"], "conversions": u["conversions"], "clicks": u["clicks"],
                      "rest": rest, "observed_weeks": len(u["weeks"]), "complete_weeks": weeks,
                      "window": [ctx.period_start, ctx.period_end], "timezone": ctx.account.get("time_zone"),
                      "bidding_strategy": strat, "channel": chan}
                if u["conversions"] == 0:
                    covered = unit[0] == "cell" and ({("day", unit[1], -1), ("hour", -1, unit[2])} & flagged_marginals)
                    floor = ctx.params.get("spend_floor", cid)
                    if covered or floor.value is None or u["cost"] < floor.value:
                        if floor.value is None:
                            zc.partial(f"spend_floor for {cid}: {floor.reason}")
                        continue
                    track, note = ctx.tracking_for_campaign(cid)
                    if not (mature and track is True):
                        zc.partial(f"campaign {cid}: zero-conversion path blocked (mature={ctx.mature}; {note})")
                        continue
                    if unit[0] != "cell":
                        flagged_marginals.add(unit)
                    ev0 = {**ev, "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": note}
                    prov = zc.finding("zero_conversion_window", "Info", entity,
                                      f"{_label(unit)} in campaign {cid} spent {u['cost']:.2f} {ctx.currency} with 0 "
                                      f"conversions (spend_floor {floor.value:g})", evidence=ev0,
                                      recommendation="Review lead handling/intent before any schedule change.",
                                      uncertainty="Lag, attribution hour basis or lead-handling delay can explain zeros.")
                    zc.review("zero_conversion_window", entity,
                              f"Is the zero-conversion {_label(unit)} window in campaign {cid} a genuine schedule "
                              "problem (not lead-handling lag, holiday or tracking-hour basis)?",
                              evidence={**ev0, "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(cid)},
                              outcomes={"schedule_issue": {"severity": "Warning", "recommendation":
                                                           "Owner-reviewed bid/eligibility test; not an automatic pause."},
                                        "explained": {"severity": None, "recommendation": "No action."},
                                        "uncertain": {"severity": "Info", "recommendation": "Monitor more complete weeks."}},
                              provisional=prov, guidance="An unattended hour can still create valuable leads.")
                    continue
                eff = V.ratio(V.ratio(u["conversions"], tot["conversions"]), V.ratio(u["cost"], tot["cost"]))
                gated = mature and weeks >= MIN_WEEKS and min(u["conversions"], rest["conversions"]) >= mc.value \
                    and min(u["clicks"], rest["clicks"]) >= mk.value
                if not gated:
                    sparse.append(_label(unit))
                    continue
                if not (eff < LOW or eff > HIGH):
                    continue
                proposal = _proposal(ctx, cid, unit, eff, strat, chan, ivs.get(cid), ref)
                calc = {"efficiency": eff, "numerator": V.ratio(u["conversions"], tot["conversions"]),
                        "denominator": V.ratio(u["cost"], tot["cost"]), "min_conversions": mc.value,
                        "min_clicks": mk.value, "cpa": V.ratio(u["cost"], u["conversions"]),
                        "rest_cpa": V.ratio(rest["cost"], rest["conversions"])}
                adverse = eff < LOW
                ef.finding("adverse_time_window" if adverse else "opportunity_time_window",
                           "Warning" if adverse else "Info", entity,
                           f"{_label(unit)} efficiency {eff:.2f} {'<' if adverse else '>'} "
                           f"{LOW if adverse else HIGH} in campaign {cid}",
                           evidence={**ev, "proposal": proposal}, calculation=calc,
                           recommendation=proposal["note"],
                           uncertainty="Day/hour grains overlap (cell ⊂ day/hour marginals): never sum their exposure. "
                                       "Initial test, not an optimum.")
            if sparse:
                ef.finding("sparse_time_windows", "Info", {"campaign_id": cid},
                           f"{len(sparse)} day/hour units in campaign {cid} lack comparable samples",
                           evidence={"units": sparse}, calculation={"min_conversions": mc.value, "min_clicks": mk.value,
                                                                    "complete_weeks": weeks, "min_weeks": MIN_WEEKS},
                           recommendation="No efficiency conclusion; combine hours only with documented comparable intent.",
                           uncertainty="Insufficient sample is not neutral performance.")

    # -- step 7: business hours
    bh = ctx.check("business_hours", "Schedule vs confirmed service/lead-handling hours", {BH: BH_COLS, SH: SH_COLS})
    if bh.runnable:
        if ref is None:
            bh.skip("reference date unknown")
    if bh.runnable:
        hours: dict = {}
        for r in ctx.rows(BH):
            vf, vt = V.parse_date(r.get("valid_from")), V.parse_date(r.get("valid_to"))
            if (vf and vf > ref) or (vt and vt < ref):
                continue
            dw, o, c = _dow(r.get("day_of_week")), _minutes(r.get("opens_at")), _minutes(r.get("closes_at"))
            if dw is None or o is None or c is None:
                bh.partial(f"business_hours row for campaign {r.get('campaign_id')} unparsable")
                continue
            hours.setdefault(str(r.get("campaign_id")), []).append((dw, o, c, r.get("after_hours_handling"),
                                                                    r.get("owner_source")))
        for cid in sorted(hours):
            if cid not in ivs:
                bh.partial(f"campaign {cid}: no schedule history")
                continue
            open_wo, closed_on = [], []
            for dw in range(7):
                d = ref - timedelta(days=(ref.weekday() - dw) % 7)
                for h in range(24):
                    is_open = any(x[0] == dw and x[1] <= h * 60 and x[2] >= h * 60 + 60 for x in hours[cid])
                    st = _state(ivs[cid], d, h)[0]
                    if st == "eligible" and not is_open:
                        closed_on.append(f"{DAYS[dw]} {h:02d}h")
                    elif st == "excluded" and is_open:
                        open_wo.append(f"{DAYS[dw]} {h:02d}h")
            if not (open_wo or closed_on):
                bh.observe(f"Campaign {cid}: schedule consistent with business hours", campaign_id=cid)
                continue
            obj = (ctx.profile.get("campaign_objectives") or {})
            obj = next((v for k, v in obj.items() if str(k) == cid), None) if isinstance(obj, dict) else None
            if obj is None:
                bh.partial(f"campaign {cid}: profile campaign_objectives missing; availability not concluded")
            bh.review("schedule_contradicts_service_hours", {"campaign_id": cid},
                      f"Does campaign {cid}'s schedule contradict the confirmed service/lead-handling requirement?",
                      evidence={"eligible_while_closed": closed_on, "excluded_while_open": open_wo,
                                "after_hours_handling": sorted({str(x[3]) for x in hours[cid]}),
                                "owner_source": sorted({str(x[4]) for x in hours[cid]}), "campaign_objective": obj,
                                "bidding_strategy": _strategy(ctx, cid), "reference_date": ref},
                      outcomes={"contradicts_requirement": {"severity": "Warning", "recommendation":
                                                            "Owner-reviewed schedule change for the listed slots."},
                                "acceptable": {"severity": None, "recommendation": "No change (e.g. after-hours leads handled)."},
                                "uncertain": {"severity": "Info", "recommendation": "Confirm lead handling with the owner."}},
                      guidance="Judge only from after_hours_handling and objectives. For contradicts_requirement give "
                               "proposal {slots: [<slot from evidence>], action: exclude|include}.")

    # -- step 7: bid strategy guard
    bg = ctx.check("strategy_guard", "Schedule control applicability", {"campaigns": ["id", "bidding_strategy_type", "channel_type"]})
    if bg.runnable:
        bg.observe("Schedule control applicability", campaigns={
            str(r.get("id")): ("bid_modifier_test" if _up(r.get("bidding_strategy_type")) == "MANUAL_CPC" else
                               "eligibility_only_pmax" if _up(r.get("channel_type")) == "PERFORMANCE_MAX" else
                               "no_schedule_cpc_modifier")
            for r in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id")))})


def _proposal(ctx, cid, unit, eff, strat, chan, ivs, ref) -> dict:
    """Bounded request-only proposal (index #22 / #67 behaviour inside the recipe contract)."""
    if chan == "PERFORMANCE_MAX":
        return {"type": "eligibility_test_only", "note": "PMax: no schedule bid modifiers; propose an owner-reviewed "
                                                         "eligibility test only with business rationale."}
    if strat != "MANUAL_CPC":
        return {"type": "none", "note": f"{strat or 'unknown'} strategy: no ordinary schedule CPC modifier; review "
                                        "eligibility only with explicit business rationale."}
    if unit[0] == "hour" or ivs is None or ref is None:
        return {"type": "none", "note": "No current per-slot interval modifier evidenced; describe only."}
    d = ref - timedelta(days=(ref.weekday() - unit[1]) % 7)
    hours = [unit[2]] if unit[0] == "cell" else list(range(24))
    mods = {(_state(ivs, d, h)) for h in hours}
    if len(mods) != 1 or next(iter(mods))[0] != "eligible" or next(iter(mods))[1] is None:
        return {"type": "none", "note": "Current interval modifier unknown or mixed across the unit; no bid value."}
    cur = next(iter(mods))[1]
    factor = min(1.1, max(0.9, eff))
    return {"type": "bounded_bid_test", "current_modifier": cur, "raw_multiplier": eff, "capped_factor": factor,
            "proposed_modifier": round(min(10.0, max(0.1, cur * factor)), 4),
            "note": "Request-only initial test (0.9–1.1 × current); not an optimum."}


def verify(ctx, item, decision) -> list[str]:
    """Rules: contradicts_requirement proposals must name slots from the evidence and a supported action."""
    if decision.get("outcome") != "contradicts_requirement":
        return []
    p = decision.get("proposal") or {}
    allowed = set(item.evidence.get("eligible_while_closed") or []) | set(item.evidence.get("excluded_while_open") or [])
    slots = p.get("slots") or []
    problems = [f"slot {s!r} not among the evidenced contradictions" for s in slots if s not in allowed]
    if not slots:
        problems.append("proposal.slots required")
    if p.get("action") not in ("exclude", "include"):
        problems.append("proposal.action must be exclude or include")
    if p.get("bid_modifier") is not None and _strategy(ctx, item.entity["campaign_id"]) != "MANUAL_CPC":
        problems.append("no schedule bid modifier outside Manual CPC")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
