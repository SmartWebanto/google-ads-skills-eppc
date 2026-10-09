"""check.py — skill-117 deterministic time-of-week heatmap, service-conflict and schedule-waste screening.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-117-ad-schedule-waste-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Hourly rows are read in account.time_zone (Ads reporting zone). A business_hours campaign whose timezone
         differs from account.time_zone is NOT converted (no offset evidence) → its hours stay unclassified (partial).
         Retained hours: inside the manifest window, date <= period_end, date < snapshot, mature per date
         ((snapshot - date) >= lag) and not a DST transition date of account.time_zone (zoneinfo; unknown zone → partial).
         Duplicate account/campaign/date/hour/device/network grain: identical rows kept once, conflicting rows dropped.
         Off-hours = hour fully outside every documented open interval for that date (weekday row whose
         effective_range contains the date; holiday_override 'YYYY-MM-DD', '=closed' or '=HH:MM-HH:MM' wins).
         Missing weekday rows, overlapping rows, partial-hour boundaries and bare holiday dates are unclassified,
         never off-hours; midnight is not inherently off-hours.
         Off-hours share denominator = the same retained hourly rows of the campaign (all hours), never a budget.
         Recurring block = weekday×hour cell (or campaign off-hours aggregate) with delivery in
         >= max(2, ceil(complete_weeks/2)) distinct ISO weeks. Comparisons are per campaign × goal_id and only for
         goal_ids declared by ctx.goal_ids(cid); unknown goals are excluded from comparisons.
         Efficiency tolerance: profile.campaign_objectives[cid].schedule_efficiency_tolerance, else
         profile.schedule_efficiency_tolerance (positive fraction). CPA miss = block CPA > comparison CPA × (1+tol);
         ROAS campaigns (objective/campaign target_roas > 0; tol < 1) miss = block ROAS < comparison ROAS × (1−tol).
         Absent tolerance → partial, no finding. Needs ctx.mature True and min_conversions on BOTH sides.
         Conflict Warning: delivery (cost > 0 or clicks > 0) in a closed hour whose handling is explicitly live-only
         (live|live_only|none|unavailable) AND whose approved_schedule excludes it. Asynchronous or unknown handling
         is never a conflict.
         Zero-conversion blocks: ctx.mature True, ctx.tracking_for_campaign(cid) True, recurring, cost >=
         spend_floor(cid) → provisional Info + relevance review; never a pause/exclusion by itself.
         verify(): experiment proposals need campaign_id, reviewed block ids, outcome_metric, guardrails and
         rollback_owner; control bid_modifier only for MANUAL_CPC/ENHANCED_CPC — never fixed modifiers on Smart Bidding.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-117-ad-schedule-waste-analysis"
VERSION = "1.0.0"

HOURLY = "custom/schedule_hourly"
BH = "external/business_hours"
HOURLY_COLS = ["campaign_id", "date", "hour", "device", "network", "impressions", "clicks", "cost", "conversions",
               "goal_id"]
BH_TIME_COLS = ["campaign_id", "weekday", "effective_range", "timezone", "open_at", "close_at", "holiday_override"]
BH_SERVICE_COLS = BH_TIME_COLS + ["live_or_asynchronous_handling", "approved_schedule", "owner"]
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FULL_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SMART = frozenset({"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"})
MANUAL = frozenset({"MANUAL_CPC", "ENHANCED_CPC"})
CONTROLS = ("schedule_exclusion", "bid_modifier", "operations_change")
ASYNC = frozenset({"asynchronous", "async", "live_and_asynchronous", "both"})
LIVE_ONLY = frozenset({"live", "live_only", "none", "unavailable"})


# ---------------------------------------------------------------------------------------------- parsing helpers
def _weekday(v) -> int | None:
    s = V.norm_text(v)
    n = V.integer(s) if s else None
    if n is not None:
        return n if 1 <= n <= 7 else None
    for i, (short, full) in enumerate(zip(DAYS, FULL_DAYS), 1):
        if s in (short, full):
            return i
    return None


def _minutes(v) -> int | None:
    parts = str(v or "").strip().split(":")
    if len(parts) not in (1, 2) or not all(p.isdigit() for p in parts):
        return None
    h, m = int(parts[0]), int(parts[1]) if len(parts) == 2 else 0
    if m >= 60 or h > 24 or (h == 24 and m):
        return None
    return h * 60 + m


def _interval(token: str) -> list[tuple[int, int]] | None:
    """'HH:MM-HH:MM' → same-day minute intervals (a wrap splits into two same-day pieces)."""
    a, sep, b = token.partition("-")
    s, e = _minutes(a), _minutes(b)
    if not sep or s is None or e is None or s == e:
        return None
    return [(s, e)] if s < e else [(s, 1440)] + ([(0, e)] if e else [])


def _range(v) -> tuple[date, date] | None:
    s = str(v or "").strip()
    for sep in ("..", "/", " to "):
        if sep in s:
            a, b = (x.strip() for x in s.split(sep, 1))
            break
    else:
        return None
    da = V.parse_date(a) if a else date.min
    db = V.parse_date(b) if b else date.max
    if da is None or db is None or da > db:
        return None
    return da, db


def _handling(v) -> str | None:
    s = V.norm_text(v).replace(" ", "_").replace("-", "_")
    return "async" if s in ASYNC else "live_only" if s in LIVE_ONLY else None


def _approved(v):
    """('open_hours'|'all'|'none', None) or ('intervals', [...]); None when undocumented/unparseable."""
    s = V.norm_text(v).replace(" ", "_")
    if not s:
        return None
    if s in ("open_hours", "business_hours"):
        return ("open_hours", None)
    if s in ("all_day", "24/7", "always"):
        return ("all", None)
    if s in ("closed", "paused", "no_serving"):
        return ("none", None)
    iv: list = []
    for tok in V.split_list(v, (";", "|", ",", "+")):
        piece = _interval(tok)
        if piece is None:
            return None
        iv += piece
    return ("intervals", iv) if iv else None


def _merge(iv) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _cover(iv, h: int) -> int:
    lo, hi = h * 60, h * 60 + 60
    return sum(max(0, min(hi, e) - max(lo, s)) for s, e in _merge(iv))


_UNKNOWN = object()


class _Schedule:
    """Documented business hours of one campaign (single timezone equal to account.time_zone)."""

    def __init__(self, cid: str):
        self.cid = cid
        self.rows: list[dict] = []
        self.overrides: dict = {}
        self.has_spill = False

    def row(self, d: date) -> dict | None:
        hits = [r for r in self.rows if r["weekday"] == d.isoweekday() and r["start"] <= d <= r["end"]]
        return hits[0] if len(hits) == 1 else None

    def open_intervals(self, d: date):
        if d in self.overrides:
            v = self.overrides[d]
            return None if v is _UNKNOWN or v is None else v
        r = self.row(d)
        if r is None:
            return None
        iv = list(r["today"])
        prev = d - timedelta(days=1)
        if self.has_spill and prev not in self.overrides:
            pr = self.row(prev)
            if pr is None:
                return None
            iv += pr["spill"]
        return iv

    def state(self, d: date, h: int) -> str | None:
        iv = self.open_intervals(d)
        if iv is None:
            return None
        c = _cover(iv, h)
        return "open" if c >= 60 else "closed" if c == 0 else "boundary"

    def service(self, d: date, h: int) -> str | None:
        """'conflict' | 'async' | 'permitted' | 'open' | None (undecidable)."""
        st = self.state(d, h)
        if st is None:
            return None
        if st != "closed":
            return "open"
        r = self.row(d)
        if r is None:
            return None
        if r["handling"] == "async":
            return "async"
        if r["handling"] is None or r["approved"] is None:
            return None
        kind, iv = r["approved"]
        excluded = kind in ("open_hours", "none") or (kind == "intervals" and _cover(iv, h) == 0)
        return "conflict" if excluded else "permitted"


class _Agg:
    __slots__ = ("sums", "unknown", "weeks", "rows")

    def __init__(self):
        self.sums = dict.fromkeys(METRICS, 0.0)
        self.unknown: set = set()
        self.weeks: set = set()
        self.rows = 0

    def add(self, r: dict) -> None:
        self.rows += 1
        for m in METRICS:
            if r[m] is None:
                self.unknown.add(m)
            else:
                self.sums[m] += r[m]
        if any((r[m] or 0) > 0 for m in ("impressions", "clicks", "cost")):
            self.weeks.add(r["week"])

    def get(self, m: str):
        return None if m in self.unknown else self.sums[m]

    def minus(self, other: "_Agg") -> "_Agg":
        out = _Agg()
        out.rows = self.rows - other.rows
        out.unknown = self.unknown | other.unknown
        out.sums = {m: self.sums[m] - other.sums[m] for m in METRICS}
        return out

    def as_dict(self) -> dict:
        d = {m: self.get(m) for m in METRICS}
        d.update(ctr=V.ratio(d["clicks"], d["impressions"]), cvr=V.ratio(d["conversions"], d["clicks"]),
                 cpa=V.ratio(d["cost"], d["conversions"]), roas=V.ratio(d["conversion_value"], d["cost"]),
                 weeks_with_delivery=len(self.weeks), rows=self.rows)
        return d


def _dst_dates(tz_name, dates) -> set | None:
    try:
        z = ZoneInfo(str(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        return None
    noon = lambda d: datetime.combine(d, time(12), tzinfo=z).utcoffset()  # noqa: E731
    return {d for d in dates if noon(d - timedelta(days=1)) != noon(d)}


def _block_name(key) -> str:
    return key if isinstance(key, str) else f"{DAYS[key[0] - 1]}-{key[1]:02d}"


# ---------------------------------------------------------------------------------------------- step 1
def _load_hourly(ctx, chk) -> tuple[list[dict], dict]:
    t = ctx.table(HOURLY)
    man = t.manifest or {}
    w_start, w_end = V.parse_date(man.get("period_start")), V.parse_date(man.get("period_end"))
    if w_start is None or w_end is None:
        chk.partial(f"{t.filename}: manifest period_start/period_end absent; window taken from retained dates")
    last_mature = ctx.snapshot - timedelta(days=ctx.lag_days) if ctx.snapshot and ctx.lag_days is not None else None
    if last_mature is None:
        chk.partial(f"per-date maturity unknown ({ctx.maturity_note}): immature hours cannot be removed")
    if ctx.period_end is None:
        chk.partial("account.date_range_end unknown: incomplete trailing dates cannot be removed")
    dropped = dict.fromkeys(("invalid", "outside_window", "after_period_end", "snapshot_or_later", "immature",
                             "dst_transition", "duplicate_conflict", "duplicate_identical"), 0)
    parsed = []
    for r in ctx.rows(HOURLY):
        d, h, cid = V.parse_date(r.get("date")), V.integer(r.get("hour")), r.get("campaign_id")
        if d is None or h is None or not 0 <= h <= 23 or cid is None:
            dropped["invalid"] += 1
            continue
        if (w_start and d < w_start) or (w_end and d > w_end):
            dropped["outside_window"] += 1
        elif ctx.period_end and d > ctx.period_end:
            dropped["after_period_end"] += 1
        elif ctx.snapshot and d >= ctx.snapshot:
            dropped["snapshot_or_later"] += 1
        elif last_mature and d > last_mature:
            dropped["immature"] += 1
        else:
            parsed.append((r, d, h, str(cid)))
    tz = ctx.account.get("time_zone")
    dst = _dst_dates(tz, sorted({p[1] for p in parsed}))
    if dst is None:
        chk.partial(f"account time zone {tz!r} not resolvable: DST-ambiguous dates not removed")
        dst = set()
    grains: dict = {}
    for r, d, h, cid in parsed:
        if d in dst:
            dropped["dst_transition"] += 1
            continue
        row = {"campaign_id": cid, "goal": r.get("goal_id"), "date": d, "hour": h, "weekday": d.isoweekday(),
               "week": tuple(d.isocalendar())[:2], "impressions": V.num(r.get("impressions")),
               "clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")),
               "conversions": V.num(r.get("conversions")), "conversion_value": ctx.money(r.get("conversion_value"))}
        key = (r.get("account_id"), cid, d, h, r.get("device"), r.get("network"))
        grains.setdefault(key, []).append(row)
    rows = []
    for key in sorted(grains, key=lambda k: tuple(str(x) for x in k)):
        group = grains[key]
        if len(group) > 1:
            sigs = {tuple(g[m] for m in ("goal",) + METRICS) for g in group}
            if len(sigs) > 1:
                dropped["duplicate_conflict"] += len(group)
                continue
            dropped["duplicate_identical"] += len(group) - 1
        rows.append(group[0])
    if dropped["duplicate_conflict"]:
        chk.partial(f"{dropped['duplicate_conflict']} rows share a campaign/date/hour/device/network grain with "
                    "different values: dropped to avoid one-to-many double counting")
    kept = sorted({r["date"] for r in rows})
    start = w_start or (kept[0] if kept else None)
    ends = [x for x in (w_end or (kept[-1] if kept else None), ctx.period_end,
                        ctx.snapshot - timedelta(days=1) if ctx.snapshot else None, last_mature) if x]
    end = min(ends) if ends else None
    weeks = 0
    if start and end:
        monday = start + timedelta(days=(7 - start.isoweekday() + 1) % 7)
        while monday + timedelta(days=6) <= end:
            weeks, monday = weeks + 1, monday + timedelta(days=7)
    if weeks < 8:
        chk.partial(f"retained hourly window has {weeks} complete weeks; recipe requires 8 complete mature weeks")
    win = {"start": start, "end": end, "complete_weeks": weeks, "recurring_min_weeks": max(2, math.ceil(weeks / 2)),
           "dst_dates_removed": sorted(d for d in dst if any(p[1] == d for p in parsed)), "dropped_rows": dropped,
           "retained_rows": len(rows), "time_zone": tz}
    chk.observe("Hourly window aligned to account time zone, completeness and maturity", **win)
    return rows, win


def _load_schedules(ctx, chk, hourly_rows) -> dict:
    tz = V.norm_text(ctx.account.get("time_zone"))
    by_c: dict[str, _Schedule] = {}
    bad: dict[str, list[str]] = {}
    for i, r in enumerate(sorted(ctx.rows(BH), key=lambda r: (str(r.get("campaign_id")), str(r.get("weekday")),
                                                               str(r.get("effective_range"))))):
        cid = str(r.get("campaign_id") or "")
        if not cid:
            chk.partial(f"business_hours row {i + 1} has no campaign_id: ignored")
            continue
        s = by_c.setdefault(cid, _Schedule(cid))
        btz = V.norm_text(r.get("timezone"))
        if not btz or btz != tz:
            bad.setdefault(cid, []).append(f"timezone {r.get('timezone')!r} != account {ctx.account.get('time_zone')!r}"
                                           " without offset evidence")
            continue
        wd, rng = _weekday(r.get("weekday")), _range(r.get("effective_range"))
        o, c = str(r.get("open_at") or "").strip().lower(), str(r.get("close_at") or "").strip().lower()
        if "closed" in (o, c):
            today, spill = [], []
        else:
            om, cm = _minutes(o), _minutes(c)
            if om is None or cm is None or om == cm:
                today = None
            elif om < cm:
                today, spill = [(om, cm)], []
            else:
                today, spill = [(om, 1440)], [(0, cm)] if cm else []
        if wd is None or rng is None or today is None:
            bad.setdefault(cid, []).append(f"row weekday={r.get('weekday')!r} range={r.get('effective_range')!r} "
                                           f"open/close={r.get('open_at')!r}/{r.get('close_at')!r} unparseable")
            continue
        s.has_spill = s.has_spill or bool(spill)
        s.rows.append({"weekday": wd, "start": rng[0], "end": rng[1], "today": today, "spill": spill,
                       "handling": _handling(r.get("live_or_asynchronous_handling")),
                       "approved": _approved(r.get("approved_schedule")), "owner": r.get("owner")})
        for tok in V.split_list(r.get("holiday_override"), (";", "|", ",")):
            ds, sep, spec = tok.partition("=")
            d = V.parse_date(ds.strip()) if len(ds.strip()) == 10 else None
            if d is None:
                bad.setdefault(cid, []).append(f"holiday_override token {tok!r} unparseable")
                continue
            if not sep:
                val = None
            elif spec.strip().lower() == "closed":
                val = []
            else:
                pieces = [_interval(p.strip()) for p in spec.split("+")]
                val = None if any(p is None for p in pieces) else [x for p in pieces for x in p]
            if d in s.overrides and s.overrides[d] != val:
                val = _UNKNOWN
            s.overrides[d] = val
    usable = {}
    for cid in sorted(by_c):
        if cid in bad:
            chk.partial(f"campaign {cid}: business hours unusable — {'; '.join(sorted(set(bad[cid])))}")
        elif by_c[cid].rows:
            usable[cid] = by_c[cid]
    delivered: dict[str, list[int]] = {}
    for r in hourly_rows:
        if (r["cost"] or 0) > 0 or (r["clicks"] or 0) > 0:
            acc = delivered.setdefault(r["campaign_id"], [0, 0])
            acc[0] += 1
            s = usable.get(r["campaign_id"])
            acc[1] += 1 if s is not None and s.state(r["date"], r["hour"]) is not None else 0
    for cid, (n, classified) in sorted(delivered.items()):
        if classified < n:
            chk.partial(f"campaign {cid}: {n - classified} of {n} delivered hours not covered by a usable business "
                        "calendar: left unclassified, not off-hours")
    chk.observe("Business calendars aligned to account time zone", usable_campaigns=sorted(usable),
                unusable_campaigns=sorted(bad), delivered_hours={c: v[0] for c, v in sorted(delivered.items())},
                classified_hours={c: v[1] for c, v in sorted(delivered.items())})
    return usable


# ---------------------------------------------------------------------------------------------- helpers for 2-4
def _objective(ctx, cid: str):
    objectives = ctx.profile.get("campaign_objectives") or {}
    return next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None


def _tolerance(ctx, cid: str):
    obj = _objective(ctx, cid)
    for raw, src in (((obj or {}).get("schedule_efficiency_tolerance") if isinstance(obj, dict) else None,
                      f"profile.campaign_objectives[{cid}].schedule_efficiency_tolerance"),
                     (ctx.profile.get("schedule_efficiency_tolerance"), "profile.schedule_efficiency_tolerance")):
        if raw is not None:
            v = V.num(raw)
            return (v, src) if v is not None and v > 0 else (None, f"{src}={raw!r} is not a positive fraction")
    return None, "no declared profile.schedule_efficiency_tolerance"


def _roas_goal(ctx, cid: str) -> bool:
    obj = _objective(ctx, cid)
    if isinstance(obj, dict) and (V.num(obj.get("target_roas")) or 0) > 0:
        return True
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None)
    return bool(row) and (V.num(row.get("target_roas")) or 0) > 0


def _cohorts(ctx, rows, scheds) -> tuple[dict, list[str]]:
    """(campaign, goal) → {'total', 'cells', 'off', 'open'} over declared goals only."""
    out: dict = {}
    excluded: dict = {}
    declared_by_c: dict[str, list[str]] = {}
    for r in rows:
        cid, goal = r["campaign_id"], r["goal"]
        declared = declared_by_c.setdefault(cid, ctx.goal_ids(cid))
        if goal is None or str(goal) not in declared:
            excluded[cid] = excluded.get(cid, 0) + 1
            continue
        c = out.setdefault((cid, str(goal)), {"total": _Agg(), "cells": {}, "off": _Agg(), "open": _Agg(),
                                              "sched": cid in scheds})
        c["total"].add(r)
        c["cells"].setdefault((r["weekday"], r["hour"]), _Agg()).add(r)
        st = r.get("state")
        if st == "closed":
            c["off"].add(r)
        elif st == "open":
            c["open"].add(r)
    notes = [f"campaign {cid}: {n} rows with unknown or undeclared goal_id (declared {ctx.goal_ids(cid)}) excluded "
             "from like-for-like comparisons" for cid, n in sorted(excluded.items())]
    return out, notes


def _blocks(c: dict):
    """Yield (block_key, block Agg, comparison Agg, comparison label)."""
    for key in sorted(c["cells"]):
        yield key, c["cells"][key], c["total"].minus(c["cells"][key]), "rest of campaign goal"
    if c["sched"] and c["off"].rows:
        yield "off_hours", c["off"], c["open"], "documented open hours"


def _efficiency(agg: _Agg, roas: bool):
    return V.ratio(agg.get("conversion_value"), agg.get("cost")) if roas else V.ratio(agg.get("cost"),
                                                                                      agg.get("conversions"))


# ---------------------------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run hourly window, business calendar, off-hours share, recurring-block, conflict and zero-conversion checks.

    Rules:   Non-account-timezone schedules, DST dates, immature hours and ambiguous calendar rows stay unclassified
             (partial). Off-hours share is Info; efficiency Warning needs a declared tolerance, ctx.mature True and
             min_conversions both sides. Service-conflict Warning only for delivery in a closed live-only hour excluded
             by approved_schedule. Zero-conversion recurring blocks (mature, tracking, cost >= spend_floor) →
             provisional Info + ai_review; never a pause.
    """
    tz_need = {"account": ["time_zone"]}
    window = ctx.check("hourly_window", "Align hourly rows to account time zone; drop incomplete, immature and "
                       "DST-ambiguous hours", {**tz_need, HOURLY: HOURLY_COLS})
    rows, win = _load_hourly(ctx, window) if window.runnable else ([], None)

    calendar = ctx.check("business_calendar", "Align business hours, holidays and time zone with account time zone",
                         {**tz_need, BH: BH_TIME_COLS})
    scheds = _load_schedules(ctx, calendar, rows) if calendar.runnable else {}
    for r in rows:
        s = scheds.get(r["campaign_id"])
        r["state"] = s.state(r["date"], r["hour"]) if s else None

    candidates: dict[str, list[dict]] = {}
    upstream_ok = window.runnable
    _heatmap(ctx, rows, win, scheds, calendar)
    cohorts, goal_notes = _cohorts(ctx, rows, scheds) if upstream_ok else ({}, [])
    _recurring(ctx, cohorts, goal_notes, win, candidates, upstream_ok)
    _conflicts(ctx, rows, win, scheds, candidates, upstream_ok, calendar.runnable)
    _zero_conversion(ctx, cohorts, win, candidates, upstream_ok)
    _controls(ctx, candidates, upstream_ok)


def _heatmap(ctx, rows, win, scheds, calendar) -> None:
    heat = ctx.check("heatmap_off_hours_share", "Weekday/hour heatmap and off-hours share of same-window cost",
                     {HOURLY: HOURLY_COLS})
    if not heat.runnable:
        return
    min_imp = ctx.params.get("min_impressions")
    per_goal: dict = {}
    per_c: dict[str, _Agg] = {}
    for r in rows:
        per_c.setdefault(r["campaign_id"], _Agg()).add(r)
        g = per_goal.setdefault((r["campaign_id"], str(r["goal"])), {})
        g.setdefault((r["weekday"], r["hour"]), _Agg()).add(r)
    for (cid, goal), cells in sorted(per_goal.items()):
        heat.observe(f"Heatmap campaign {cid} goal {goal}", campaign_id=cid, goal_id=goal,
                     window=[win["start"], win["end"]],
                     cells=[{"block": _block_name(k), **cells[k].as_dict()} for k in sorted(cells)])
    if not calendar.runnable:
        heat.partial("off-hours share not computed: business calendar unavailable", calendar.missing)
    for cid in sorted(per_c):
        total = per_c[cid]
        if cid not in scheds:
            if calendar.runnable:
                heat.partial(f"campaign {cid}: off-hours share not computed (no usable business calendar)")
            continue
        off, unclassified = _Agg(), _Agg()
        for r in rows:
            if r["campaign_id"] == cid:
                if r["state"] == "closed":
                    off.add(r)
                elif r["state"] is None:
                    unclassified.add(r)
        share = V.ratio(off.get("cost"), total.get("cost"))
        ev = {"off_hours": off.as_dict(), "campaign_same_window": total.as_dict(),
              "unclassified_cost": unclassified.get("cost"), "off_hours_cost_share": share,
              "window": [win["start"], win["end"]], "min_impressions": min_imp.value,
              "sparse": off.get("impressions") is None or min_imp.value is None
              or off.get("impressions") < min_imp.value}
        if share is None or not off.get("cost"):
            heat.observe(f"Campaign {cid}: no measurable off-hours cost share", campaign_id=cid, **ev)
            continue
        heat.finding("off_hours_share", "Info", {"campaign_id": cid},
                     f"Campaign {cid}: {share:.1%} of same-window cost ({off.get('cost'):.2f} of "
                     f"{total.get('cost'):.2f} {ctx.currency}) fell in documented closed hours",
                     evidence=ev, calculation={"numerator": "off-hours cost", "denominator":
                                               "same retained hourly rows, all hours", "share": share},
                     recommendation="Observation only: confirm whether closed-hour traffic is handled asynchronously "
                                    "before any schedule change; do not treat as waste.",
                     uncertainty="Share alone proves neither lost revenue nor waste; unclassified hours are excluded "
                                 "from the numerator.")


def _recurring(ctx, cohorts, goal_notes, win, candidates, upstream_ok) -> None:
    chk = ctx.check("recurring_block_efficiency", "Recurring blocks vs like-for-like comparison with sample gates",
                    {HOURLY: HOURLY_COLS})
    if not chk.runnable:
        return
    if not upstream_ok:
        return chk.skip("hourly window alignment did not run", [f"{HOURLY} (file)"])
    for n in goal_notes:
        chk.partial(n)
    if ctx.mature is not True:
        chk.partial(f"comparisons disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    min_conv = ctx.params.get("min_conversions")
    if min_conv.value is None:
        chk.partial(f"min_conversions unresolved: {min_conv.reason}")
        return
    compared = gated = 0
    for (cid, goal), c in sorted(cohorts.items()):
        tol, tsrc = _tolerance(ctx, cid)
        roas = _roas_goal(ctx, cid)
        if tol is None or (roas and tol >= 1):
            chk.partial(f"campaign {cid}: client efficiency tolerance unresolved ({tsrc}); no tolerance finding")
            continue
        floor = ctx.params.get("spend_floor", cid)
        for key, blk, comp, label in _blocks(c):
            if len(blk.weeks) < win["recurring_min_weeks"]:
                continue
            b_eff, c_eff = _efficiency(blk, roas), _efficiency(comp, roas)
            if b_eff is None or c_eff is None:
                continue
            miss = b_eff < c_eff * (1 - tol) if roas else b_eff > c_eff * (1 + tol)
            bconv, cconv = blk.get("conversions"), comp.get("conversions")
            name = _block_name(key)
            entity = {"campaign_id": cid, "goal_id": goal, "block": name}
            ev = {"block": blk.as_dict(), "comparison": comp.as_dict(), "comparison_scope": label,
                  "metric": "ROAS" if roas else "CPA", "block_value": b_eff, "comparison_value": c_eff,
                  "tolerance": tol, "tolerance_source": tsrc, "min_conversions": min_conv.value,
                  "window": [win["start"], win["end"]], "recurring_min_weeks": win["recurring_min_weeks"]}
            if bconv is None or cconv is None or bconv < min_conv.value or cconv < min_conv.value:
                gated += 1
                if miss and floor.value is not None and (blk.get("cost") or 0) >= floor.value:
                    chk.finding("sparse_block", "Info", entity,
                                f"Campaign {cid} goal {goal} block {name}: {ev['metric']} {b_eff:.2f} vs {c_eff:.2f} "
                                f"misses tolerance but a side has < {min_conv.value} conversions",
                                evidence={**ev, "spend_floor": floor.value, "spend_floor_source": floor.source},
                                recommendation="Insufficient sample: keep monitoring; no schedule change.",
                                uncertainty="Below the conversion sample gate on at least one side.")
                continue
            compared += 1
            if miss:
                chk.finding("block_misses_efficiency_tolerance", "Warning", entity,
                            f"Campaign {cid} goal {goal} block {name}: {ev['metric']} {b_eff:.2f} vs {label} "
                            f"{c_eff:.2f} misses declared tolerance {tol:g}",
                            evidence=ev, calculation={"rule": "block ROAS < comparison × (1 − tol)" if roas
                                                      else "block CPA > comparison × (1 + tol)"},
                            recommendation="Propose a limited schedule experiment (control step); no fixed "
                                           "modifier on Smart Bidding, no guaranteed savings.",
                            uncertainty="Observational comparison, not causal uplift; assisted and asynchronous "
                                        "conversions may be attributed elsewhere.")
                candidates.setdefault(cid, []).append({"block": name, "goal_id": goal,
                                                       "condition": "block_misses_efficiency_tolerance"})
    chk.observe("Recurring block comparisons", compared=compared, below_sample_gate=gated,
                recurring_min_weeks=win["recurring_min_weeks"], min_conversions=min_conv.value)


def _conflicts(ctx, rows, win, scheds, candidates, upstream_ok, calendar_ok) -> None:
    chk = ctx.check("service_conflict", "Delivery during documented unavailable-service hours (asynchronous "
                    "handling exempt)", {HOURLY: HOURLY_COLS, BH: BH_SERVICE_COLS})
    if not chk.runnable:
        return
    if not upstream_ok or not calendar_ok:
        return chk.skip("hourly window or business calendar alignment did not run")
    per: dict[str, dict] = {}
    for r in rows:
        if not ((r["cost"] or 0) > 0 or (r["clicks"] or 0) > 0):
            continue
        s = scheds.get(r["campaign_id"])
        status = s.service(r["date"], r["hour"]) if s else None
        p = per.setdefault(r["campaign_id"], {"conflict": _Agg(), "async": _Agg(), "undecided": 0, "hours": set(),
                                              "owners": set()})
        if status in ("conflict", "async"):
            p[status].add(r)
            if status == "conflict":
                p["hours"].add((r["date"], r["hour"]))
                p["owners"].add(str((s.row(r["date"]) or {}).get("owner")))
        elif status is None and r["state"] == "closed":
            p["undecided"] += 1
    for cid, p in sorted(per.items()):
        if p["undecided"]:
            chk.partial(f"campaign {cid}: {p['undecided']} closed delivered hours with unknown handling or "
                        "approved_schedule: not judged")
        if p["async"].rows:
            chk.observe(f"Campaign {cid}: closed-hour delivery handled asynchronously (not a conflict)",
                        campaign_id=cid, **p["async"].as_dict())
        if not p["conflict"].rows:
            continue
        agg = p["conflict"].as_dict()
        hours = [f"{d.isoformat()} {h:02d}:00" for d, h in sorted(p["hours"])]
        chk.finding("schedule_service_conflict", "Warning", {"campaign_id": cid},
                    f"Campaign {cid} served {len(hours)} hours outside its approved schedule while service is "
                    f"documented unavailable (cost {agg['cost']} {ctx.currency}, clicks {agg['clicks']})",
                    evidence={**agg, "hours": hours, "owners": sorted(p["owners"]),
                              "window": [win["start"], win["end"]], "time_zone": win["time_zone"]},
                    calculation={"rule": "closed ∧ live-only handling ∧ approved_schedule excludes hour ∧ cost/clicks > 0"},
                    recommendation="Ask the named owner to confirm the restriction, then align the ad schedule or add "
                                   "asynchronous handling; exposure is not guaranteed savings.",
                    uncertainty="Hours are in account time zone; calendar accuracy is owner-supplied.",
                    owner=", ".join(sorted(p["owners"])) or None)
        candidates.setdefault(cid, []).append({"block": "documented_unavailable_hours", "goal_id": None,
                                               "condition": "schedule_service_conflict"})
    chk.observe("Service-conflict screen", campaigns=len(per),
                conflicts=sum(1 for p in per.values() if p["conflict"].rows))


def _zero_conversion(ctx, cohorts, win, candidates, upstream_ok) -> None:
    chk = ctx.check("zero_conversion_blocks", "Zero-conversion recurring blocks above spend_floor (tracking and "
                    "relevance gated)", {HOURLY: HOURLY_COLS})
    if not chk.runnable:
        return
    if not upstream_ok:
        return chk.skip("hourly window alignment did not run", [f"{HOURLY} (file)"])
    if ctx.mature is not True:
        chk.partial(f"zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    screened = 0
    for (cid, goal), c in sorted(cohorts.items()):
        tracking, note = ctx.tracking_for_campaign(cid)
        if tracking is not True:
            chk.partial(f"zero-conversion path disabled: {note}")
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            chk.partial(f"campaign {cid}: spend_floor unresolved ({floor.reason})")
            continue
        for key, blk, comp, label in _blocks(c):
            cost, conv = blk.get("cost"), blk.get("conversions")
            if cost is None or conv != 0 or cost < floor.value or len(blk.weeks) < win["recurring_min_weeks"]:
                continue
            screened += 1
            name = _block_name(key)
            entity = {"campaign_id": cid, "goal_id": goal, "block": name}
            ev = {"block": blk.as_dict(), "comparison": comp.as_dict(), "comparison_scope": label,
                  "spend_floor": floor.value, "spend_floor_source": floor.source, "tracking": note,
                  "window": [win["start"], win["end"]], "recurring_min_weeks": win["recurring_min_weeks"],
                  "objectives": _objective(ctx, cid)}
            prov = chk.finding("zero_conversion_block", "Info", entity,
                               f"Campaign {cid} goal {goal} block {name}: {cost:.2f} {ctx.currency} with 0 "
                               f"conversions across {len(blk.weeks)} weeks (spend_floor {floor.value:g})",
                               evidence=ev, recommendation="Review relevance and handling before any schedule change; "
                                                           "exposure is not savings.",
                               uncertainty="Zero conversions can reflect long cycles, assisted or offline value.")
            chk.review("zero_conversion_block", entity,
                       f"Is the zero-conversion block {name} (campaign {cid}, goal {goal}) serving traffic the "
                       "business cannot or should not convert at that time?",
                       evidence=ev, provisional=prov,
                       outcomes={"unserved_or_irrelevant": {"severity": "Warning", "recommendation":
                                                            "Investigate and propose a limited schedule experiment."},
                                 "explained_keep": {"severity": None, "recommendation":
                                                    "Keep serving; asynchronous handling or role explains it."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the owner about handling."}},
                       guidance="Judge only from profile objectives, business-hours handling and campaign role. Closed "
                                "hours and low CVR do not prove lost revenue.")
            candidates.setdefault(cid, []).append({"block": name, "goal_id": goal, "condition": "zero_conversion_block"})
    chk.observe("Zero-conversion block screen", screened=screened)


def _strategy_class(t) -> str:
    s = str(t or "").strip().upper()
    return "unknown" if not s else "smart" if s in SMART else "manual" if s in MANUAL else "other"


def _controls(ctx, candidates, upstream_ok) -> None:
    chk = ctx.check("control_applicability", "Schedule control applicability and limited experiment proposal",
                    {"campaigns": ["id", "bidding_strategy_type"]})
    if not chk.runnable:
        return
    adj = ctx.table("bid_adjustments")
    sched_mods: dict[str, list] = {}
    if adj is None:
        chk.partial("current schedule modifiers unknown", ["bid_adjustments (file)"])
    elif adj.missing(["campaign_id", "dimension", "modifier"]):
        chk.partial("current schedule modifiers unknown",
                    [f"bid_adjustments:{c}" for c in adj.missing(["campaign_id", "dimension", "modifier"])])
    else:
        for r in ctx.rows("bid_adjustments"):
            if "SCHEDULE" in str(r.get("dimension") or "").upper():
                sched_mods.setdefault(str(r.get("campaign_id")), []).append(
                    {"criterion_id": r.get("criterion_id"), "modifier": r.get("modifier")})
    for mods in sched_mods.values():
        mods.sort(key=lambda m: (str(m["criterion_id"]), str(m["modifier"])))
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns")}
    for cid in sorted(camps):
        cls = _strategy_class(camps[cid].get("bidding_strategy_type"))
        mods = sched_mods.get(cid, [])
        chk.observe(f"Campaign {cid}: schedule control applicability", campaign_id=cid,
                    bidding_strategy_type=camps[cid].get("bidding_strategy_type"), strategy_class=cls,
                    fixed_schedule_modifier_applicable=cls == "manual", current_schedule_modifiers=mods)
    if not upstream_ok:
        chk.partial("no candidate blocks evaluated: hourly evidence unavailable")
    for cid in sorted(candidates):
        row = camps.get(cid)
        if row is None:
            chk.partial(f"campaign {cid}: not in campaigns table; control applicability unknown")
            continue
        cls = _strategy_class(row.get("bidding_strategy_type"))
        blocks = sorted({c["block"] for c in candidates[cid]})
        chk.review("schedule_experiment", {"campaign_id": cid},
                   f"Which limited schedule experiment, if any, should be proposed for campaign {cid}?",
                   evidence={"candidates": sorted(candidates[cid], key=lambda c: (c["block"], c["condition"])),
                             "blocks": blocks, "bidding_strategy_type": row.get("bidding_strategy_type"),
                             "strategy_class": cls, "fixed_schedule_modifier_applicable": cls == "manual",
                             "current_schedule_modifiers": sched_mods.get(cid, []), "controls": list(CONTROLS)},
                   outcomes={"experiment_proposed": {"severity": None, "recommendation":
                                                     "Request the verified limited experiment; no account change here."},
                             "no_change": {"severity": None, "recommendation": "No schedule change proposed."},
                             "uncertain": {"severity": "Info", "recommendation":
                                           "Collect owner handling and objective evidence first."}},
                   guidance="experiment_proposed needs proposal {campaign_id, control: " + "|".join(CONTROLS) +
                            ", blocks: [ids from evidence.blocks], outcome_metric, guardrails, rollback_owner}. "
                            "bid_modifier only when fixed_schedule_modifier_applicable; tCPA device targets are not a "
                            "schedule CPC control.")


# ---------------------------------------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: experiment proposals are complete, scoped to reviewed blocks and never fixed modifiers on non-manual bidding."""
    if item.condition_key != "schedule_experiment" or decision.get("outcome") != "experiment_proposed":
        return []
    p = decision.get("proposal") or {}
    problems = []
    cid = item.entity["campaign_id"]
    if str(p.get("campaign_id") or "") != cid:
        problems.append(f"proposal.campaign_id must be reviewed campaign {cid}")
    control = p.get("control")
    if control not in CONTROLS:
        problems.append(f"proposal.control must be one of {list(CONTROLS)}")
    blocks = p.get("blocks") or []
    if not blocks:
        problems.append("proposal.blocks required")
    problems += [f"block {b!r} not among reviewed blocks" for b in blocks if b not in item.evidence["blocks"]]
    for k in ("outcome_metric", "rollback_owner"):
        if not str(p.get(k) or "").strip():
            problems.append(f"proposal.{k} required")
    if not p.get("guardrails"):
        problems.append("proposal.guardrails required")
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None)
    cls = _strategy_class(row.get("bidding_strategy_type") if row else None)
    if (control == "bid_modifier" or p.get("modifier") is not None) and cls != "manual":
        problems.append(f"fixed schedule modifiers are not applicable to strategy "
                        f"{(row or {}).get('bidding_strategy_type')!r} ({cls}); propose an exclusion or operations test")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
