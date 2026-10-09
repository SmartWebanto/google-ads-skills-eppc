"""check.py — skill-146 deterministic review of exceptional seasonality adjustment evidence and settings.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-146-seasonality-bid-adjustment-deployment/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Normal CVR = pooled conversions/clicks over mature NON-event days listed in the event's
         normal_baseline_dates (never promotional or post-event days), goal-aligned to the event objective,
         clicks >= min_clicks; otherwise undefined → Info sparse history, no estimate.
         Adjustment % = 100*(expected CVR / normal CVR - 1) = 100*expected_cvr_change (relative fraction);
         historical event deltas are evidence only, never auto-copied into a future setting.
         After a promotion, return to normal needs NO negative adjustment: past events yield Info
         routine_post_event_return; a configured negative setting over post-event dates without a documented
         exceptional_future_reason is Warning (contradicts documented event scope).
         Configured-setting Warnings are deterministic only for explicit contradictions: no documented event on a
         manifest-complete calendar, dates outside the event window, sign opposite to expected change, percent
         outside a parseable estimate_range. Critical only via review with proposal.evidence_ref.
         end_at with a T00:00 time is exclusive (event ends the previous day); date-only end_at is inclusive.
         Supported strategy = TARGET_CPA/TARGET_ROAS (Search/Shopping/Display) or PERFORMANCE_MAX; Maximize*
         strategies and App are unknown (verify eligibility); Travel is unsupported.
         Proposals are request-only; verify() checks scope, dates, sign, estimate range and supported strategy.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
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

SKILL = "skill-146-seasonality-bid-adjustment-deployment"
VERSION = "1.0.0"

DAILY = "custom/event_cvr_daily"
EVENTS = "external/seasonality_events"
SETTINGS = "custom/seasonality_settings"
_SUPPORTED_CHANNELS = ("SEARCH", "SHOPPING", "DISPLAY")
_SUPPORTED_STRATEGIES = ("TARGET_CPA", "TARGET_ROAS")
_UNKNOWN_STRATEGIES = ("MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE")
_NO_REASON = ("", "none", "no", "n/a")
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:through|to|\.\.|/|–)\s*(\d{4}-\d{2}-\d{2})", re.I)


# ---------------------------------------------------------------------------- parsing helpers
def _start_day(v) -> date | None:
    return V.parse_date(v)


def _end_day(v) -> date | None:
    """Inclusive last day. Rules: 'YYYY-MM-DDT00:00…' is an exclusive midnight bound."""
    d = V.parse_date(v)
    if d is None:
        return None
    s = str(v).strip()
    if len(s) > 10 and s[10] in "T " and s[11:16] == "00:00":
        return d - timedelta(days=1)
    return d


def _date_set(text) -> set[date] | None:
    """normal_baseline_dates: ranges 'A through B' / 'A..B' and single dates separated by ';' or ','."""
    s = str(text or "").strip()
    if not s:
        return None
    out: set[date] = set()
    for part in re.split(r"[;,]", s):
        part = part.strip()
        m = _RANGE.search(part)
        if m:
            a, b = V.parse_date(m.group(1)), V.parse_date(m.group(2))
            if a is None or b is None or b < a:
                return None
            out |= {a + timedelta(days=i) for i in range((b - a).days + 1)}
        elif V.parse_date(part):
            out.add(V.parse_date(part))
        elif part:
            return None
    return out or None


def _estimate_range(text) -> tuple[float, float] | None:
    """Two numbers → (low, high) percent. Fractions (both |x|<=1, no '%') are scaled to percent."""
    s = str(text or "")
    nums = [float(x) for x in _NUM.findall(s)]
    if len(nums) != 2:
        return None
    if "%" not in s and all(abs(x) <= 1 for x in nums):
        nums = [x * 100 for x in nums]
    return min(nums), max(nums)


def _exceptional(ev) -> bool:
    r = str(ev.get("exceptional_future_reason") or "").strip().lower()
    return bool(r) and r not in _NO_REASON and not r.startswith("none")


def _mature_day(ctx, row, d: date) -> bool:
    m = str(row.get("maturity") or "").strip().lower()
    if m:
        return m == "mature"
    return ctx.lag_days is not None and ctx.snapshot is not None and (ctx.snapshot - d).days >= ctx.lag_days


# ---------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run strategy support, normal baseline, future estimate, duration, post-event and settings-conflict checks.

    Rules:   Undefined normal CVR (immature/event days, clicks < min_clicks) → Info uncertain_forecast, no estimate.
             Past events → Info routine_post_event_return; a negative post-event setting without
             exceptional_future_reason → Warning. Setting Warnings only for explicit contradictions (no event on a
             complete calendar, dates outside window, opposite sign, outside estimate_range); Critical only via review;
             historical deltas are never auto-copied.
    """
    support = _strategy_support(ctx)
    stats = _normal_baseline(ctx)
    settings = _load_settings(ctx)
    _future_estimates(ctx, stats, support)
    _durations(ctx)
    _post_event(ctx, stats, settings)
    _settings_conflicts(ctx, settings, support)


def _strategy_support(ctx) -> dict[str, str]:
    """Step 1: supported / unknown / unsupported per campaign from strategy and channel."""
    chk = ctx.check("strategy_support", "Campaign strategy and seasonality-control support",
                    {"campaigns": ["id", "channel_type", "bidding_strategy_type"]})
    out: dict[str, str] = {}
    if not chk.runnable:
        return out
    for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
        cid = str(c.get("id"))
        ch = str(c.get("channel_type") or "").upper()
        st = str(c.get("bidding_strategy_type") or "").upper()
        if ch == "TRAVEL":
            status = "unsupported"
        elif ch == "PERFORMANCE_MAX":
            status = "supported"
        elif ch in _SUPPORTED_CHANNELS and st in _SUPPORTED_STRATEGIES:
            status = "supported"
        elif ch == "" or st == "" or st in _UNKNOWN_STRATEGIES or ch in ("MULTI_CHANNEL", "APP"):
            status = "unknown"
        else:
            status = "unsupported"
        out[cid] = status
        chk.observe(f"Campaign {cid}: seasonality control {status}", campaign_id=cid, channel_type=ch,
                    bidding_strategy_type=st, status=status)
    if "unknown" in out.values():
        chk.partial("some campaigns need confirmed control eligibility (Maximize*/App/unknown channel or strategy)")
    return out


def _events(ctx) -> list[dict]:
    return sorted(ctx.rows(EVENTS), key=lambda r: (str(r.get("event_id")), str(r.get("campaign_id"))))


def _event_window(ev) -> tuple[date | None, date | None]:
    return _start_day(ev.get("start_at")), _end_day(ev.get("end_at"))


def _normal_baseline(ctx) -> dict:
    """Step 2: normal / event / post-event CVR per event×campaign from mature goal-aligned daily rows."""
    chk = ctx.check("normal_baseline", "Normal CVR from mature non-event comparable days",
                    {DAILY: ["campaign_id", "date", "goal_id", "clicks", "conversions", "maturity"],
                     EVENTS: ["event_id", "campaign_id", "start_at", "end_at", "objective", "normal_baseline_dates"]})
    stats: dict = {}
    if not chk.runnable:
        return stats
    mcl = ctx.params.get("min_clicks")
    daily: dict[str, list[tuple[date, dict]]] = {}
    for r in ctx.rows(DAILY):
        d = V.parse_date(r.get("date"))
        if d is not None:
            daily.setdefault(str(r.get("campaign_id")), []).append((d, r))
    event_days: dict[str, set[date]] = {}
    for ev in _events(ctx):
        s, e = _event_window(ev)
        if s and e:
            event_days.setdefault(str(ev.get("campaign_id")), set()).update(
                s + timedelta(days=i) for i in range((e - s).days + 1))
    labelled = DAILY in ctx.evidence.tables and "period_role" in ctx.table(DAILY).columns
    for ev in _events(ctx):
        eid, cid = str(ev.get("event_id")), str(ev.get("campaign_id"))
        s, e = _event_window(ev)
        key = (eid, cid)
        normal_days = _date_set(ev.get("normal_baseline_dates"))
        if s is None or e is None or normal_days is None:
            chk.partial(f"event {eid}/{cid}: unparseable start_at/end_at or normal_baseline_dates")
            continue
        rows = daily.get(cid, [])
        goals = sorted({str(r.get("goal_id")) for _, r in rows if r.get("goal_id")})
        objective = str(ev.get("objective") or "")
        if objective in goals:
            goal = objective
        elif len(goals) == 1:
            goal = goals[0]
        else:
            chk.partial(f"event {eid}/{cid}: objective '{objective}' does not select one goal among {goals}")
            continue

        def pool(pred):
            clicks = conv = 0.0
            days = set()
            unknown = 0
            for d, r in rows:
                if str(r.get("goal_id")) != goal or not pred(d, r):
                    continue
                c, v = V.num(r.get("clicks")), V.num(r.get("conversions"))
                if c is None or v is None:
                    unknown += 1
                    continue
                clicks += c
                conv += v
                days.add(d)
            return {"clicks": clicks, "conversions": conv, "days": len(days),
                    "first": min(days) if days else None, "last": max(days) if days else None,
                    "unknown_rows": unknown,
                    "weekdays": sorted({x.weekday() for x in days}),
                    "cvr": V.ratio(conv, clicks) if mcl.value is not None and clicks >= mcl.value else None}

        other_events = event_days.get(cid, set())
        normal = pool(lambda d, r: d in normal_days and d not in other_events and _mature_day(ctx, r, d)
                      and (not labelled or str(r.get("period_role") or "").lower() in ("normal", "")))
        event = pool(lambda d, r: s <= d <= e and _mature_day(ctx, r, d))
        if labelled:
            post = pool(lambda d, r: d > e and str(r.get("period_role") or "").lower() == "post_event"
                        and _mature_day(ctx, r, d))
        else:
            post = pool(lambda d, r: e < d <= e + timedelta(days=14) and d not in other_events
                        and _mature_day(ctx, r, d))
        rec = {"event_id": eid, "campaign_id": cid, "goal_id": goal, "event_window": [s, e],
               "normal": normal, "event": event, "post_event": post, "min_clicks": mcl.value,
               "min_clicks_source": mcl.source,
               "event_vs_normal": V.ratio(event["cvr"] - normal["cvr"], normal["cvr"])
               if event["cvr"] is not None and normal["cvr"] is not None else None,
               "post_vs_normal": V.ratio(post["cvr"] - normal["cvr"], normal["cvr"])
               if post["cvr"] is not None and normal["cvr"] is not None else None}
        stats[key] = rec
        chk.observe(f"Event {eid}/{cid}: normal/event/post-event CVR (goal {goal})", **rec,
                    period_labels="period_role" if labelled else "derived from event dates")
    return stats


def _load_settings(ctx) -> list[dict] | None:
    t = ctx.table(SETTINGS)
    if t is None or t.missing(["adjustment_id", "campaign_ids", "start_at", "end_at", "cvr_adjustment_percent",
                               "status"]):
        return None
    return sorted((r for r in t.rows if str(r.get("status") or "").upper() not in ("REMOVED",)),
                  key=lambda r: str(r.get("adjustment_id")))


def _future_estimates(ctx, stats: dict, support: dict) -> None:
    """Step 3: future adjustment estimate only from nonzero normal baseline and a justified forecast."""
    chk = ctx.check("future_estimate", "Future exceptional adjustment estimate",
                    {EVENTS: ["event_id", "campaign_id", "start_at", "end_at", "expected_cvr_change",
                              "exceptional_future_reason", "expected_start", "expected_end", "estimate_range",
                              "evidence_ref", "approval_status", "owner"]})
    if not chk.runnable:
        return
    as_of = ctx.as_of
    if as_of is None:
        chk.partial("as_of unknown: future events cannot be separated from past events")
        return
    n = 0
    for ev in _events(ctx):
        eid, cid = str(ev.get("event_id")), str(ev.get("campaign_id"))
        s = _start_day(ev.get("expected_start")) or _start_day(ev.get("start_at"))
        e = _end_day(ev.get("expected_end")) or _end_day(ev.get("end_at"))
        if s is None or s <= as_of:
            continue
        n += 1
        entity = {"event_id": eid, "campaign_id": cid}
        rec = stats.get((eid, cid))
        chg = V.rate(ev.get("expected_cvr_change"), "fraction")
        normal_cvr = rec["normal"]["cvr"] if rec else None
        ev_data = {"window": [s, e], "duration_days": (e - s).days + 1 if e else None,
                   "expected_cvr_change": chg, "estimate_range": ev.get("estimate_range"),
                   "exceptional_future_reason": ev.get("exceptional_future_reason"),
                   "evidence_ref": ev.get("evidence_ref"), "approval_status": ev.get("approval_status"),
                   "owner": ev.get("owner"), "strategy_support": support.get(cid, "unknown"),
                   "baseline": rec}
        if normal_cvr is None or normal_cvr == 0 or chg is None:
            chk.finding("uncertain_forecast", "Info", entity,
                        f"Future event {eid}/{cid}: no adjustment estimate — "
                        + ("normal CVR undefined or below min_clicks" if not normal_cvr else "expected_cvr_change unknown"),
                        evidence=ev_data, recommendation="Supply a mature normal baseline and a justified forecast.",
                        uncertainty="Sparse history or missing forecast; no proposal drafted.")
            continue
        pct = round(100 * chg, 4)
        ev_data.update({"normal_cvr": normal_cvr, "expected_future_cvr": normal_cvr * (1 + chg),
                        "implied_adjustment_percent": pct,
                        "formula": "100*(expected future CVR / normal CVR - 1)"})
        outcomes = {"propose_adjustment": {"severity": "Info", "recommendation":
                                           "Request-only proposal with owner, approval, monitoring and end check."},
                    "no_adjustment": {"severity": None, "recommendation": "Let Smart Bidding handle it."},
                    "uncertain": {"severity": "Info", "recommendation": "Ask the owner for forecast evidence."}}
        chk.review("future_adjustment", entity,
                   f"Is the {pct:+g}% CVR deviation for future event {eid} ({s}..{e}) independently justified "
                   f"as a short exceptional change from NORMAL baseline?",
                   evidence=ev_data, outcomes=outcomes,
                   guidance="Routine seasonality and post-promotion returns get no adjustment. A negative proposal "
                            "needs a documented exceptional_future_reason. For propose_adjustment supply proposal "
                            "{cvr_adjustment_percent, start, end, campaign_ids}.")
    chk.observe("Future events evaluated", future_events=n, as_of=as_of)


def _durations(ctx) -> None:
    """Step 4: duration context; >14 days may work less well, never Critical by itself."""
    chk = ctx.check("event_duration", "Event and setting duration guidance",
                    {EVENTS: ["event_id", "campaign_id", "start_at", "end_at"]})
    if not chk.runnable:
        return
    for ev in _events(ctx):
        s, e = _event_window(ev)
        days = (e - s).days + 1 if s and e else None
        band = None if days is None else "1-7 intended" if days <= 7 else "8-14" if days <= 14 else ">14 may work less well"
        chk.observe(f"Event {ev.get('event_id')}/{ev.get('campaign_id')}: {days} days ({band})",
                    event_id=ev.get("event_id"), campaign_id=ev.get("campaign_id"), duration_days=days, band=band)


def _covers(setting, cid: str, days: tuple[date, date]) -> bool:
    s, e = _start_day(setting.get("start_at")), _end_day(setting.get("end_at"))
    ids = set(V.split_list(setting.get("campaign_ids"), (" | ", ";", "|", ",")))
    return bool(s and e and cid in ids and s <= days[1] and e >= days[0])


def _justified(setting, cid: str, events: list[dict]) -> bool:
    """A negative setting is justified only by a documented exceptional event of the same campaign whose
    window contains the setting window."""
    s, e = _start_day(setting.get("start_at")), _end_day(setting.get("end_at"))
    for ev in events:
        es, ee = _event_window(ev)
        if (str(ev.get("campaign_id")) == cid and _exceptional(ev) and s and e and es and ee
                and es <= s and e <= ee):
            return True
    return False


def _post_event(ctx, stats: dict, settings: list[dict] | None) -> None:
    """Step 5: past promotions return to normal — no negative adjustment, no retrospective compensation."""
    chk = ctx.check("post_event_return", "Post-promotion return to normal baseline",
                    {EVENTS: ["event_id", "campaign_id", "start_at", "end_at", "exceptional_future_reason"]})
    if not chk.runnable:
        return
    if settings is None:
        chk.partial("seasonality settings unavailable: configured post-event adjustments unknown",
                    [f"{SETTINGS} (file)"])
    as_of = ctx.as_of
    events = _events(ctx)
    for ev in events:
        eid, cid = str(ev.get("event_id")), str(ev.get("campaign_id"))
        s, e = _event_window(ev)
        if e is None or as_of is None or e >= as_of:
            continue
        entity = {"event_id": eid, "campaign_id": cid}
        rec = stats.get((eid, cid))
        post_window = (e + timedelta(days=1), e + timedelta(days=14))
        negative = [st for st in (settings or []) if _covers(st, cid, post_window)
                    and (V.num(st.get("cvr_adjustment_percent")) or 0) < 0
                    and not _justified(st, cid, events)]
        ev_data = {"event_name": ev.get("name"), "event_window": [s, e], "post_window_checked": list(post_window),
                   "baseline": rec, "post_vs_normal": rec.get("post_vs_normal") if rec else None,
                   "exceptional_future_reason": ev.get("exceptional_future_reason"),
                   "settings_known": settings is not None,
                   "guidance_ref": "https://support.google.com/google-ads/answer/10369906"}
        for st in negative:
            chk.finding("retrospective_negative_adjustment", "Warning",
                        {**entity, "adjustment_id": st.get("adjustment_id")},
                        f"Setting {st.get('adjustment_id')} applies {st.get('cvr_adjustment_percent')}% after "
                        f"promotion {eid} ended {e}; post-event return to normal needs no negative adjustment",
                        evidence={**ev_data, "setting": {k: st.get(k) for k in sorted(st)}},
                        recommendation="Request owner review to remove/narrow the post-event negative setting; "
                                       "no retrospective compensation.",
                        uncertainty="An independently documented exceptional future event would change this.")
        if negative:
            continue
        chk.finding("routine_post_event_return", "Info", entity,
                    f"Promotion {eid} ('{ev.get('name')}') for campaign {cid} ended {e}: return to normal baseline "
                    f"is expected and needs NO negative seasonality adjustment"
                    + (f" (post-event CVR vs normal {rec['post_vs_normal']:+.1%})"
                       if rec and rec.get("post_vs_normal") is not None else ""),
                    evidence=ev_data,
                    recommendation="No adjustment; do not compensate retrospectively or infer overbidding from CPC.",
                    uncertainty="Only an independently justified exceptional future period merits a negative proposal.")


def _settings_conflicts(ctx, settings: list[dict] | None, support: dict) -> None:
    """Step 6: configured scope/date/sign/range contradictions and overlaps."""
    chk = ctx.check("settings_conflicts", "Configured seasonality settings vs documented events",
                    {SETTINGS: ["adjustment_id", "scope_type", "campaign_ids", "device_scope", "start_at", "end_at",
                                "timezone", "cvr_adjustment_percent", "status"],
                     EVENTS: ["event_id", "campaign_id", "start_at", "end_at", "expected_cvr_change",
                              "estimate_range"]})
    if not chk.runnable or settings is None:
        return
    if not settings:
        chk.observe("No current/future seasonality adjustments configured",
                    known_empty=ctx.table(SETTINGS).complete is True)
        return
    calendar_complete = ctx.table(EVENTS).complete is True
    tz = ctx.account.get("time_zone")
    events = _events(ctx)
    for st in settings:
        aid = str(st.get("adjustment_id"))
        s, e = _start_day(st.get("start_at")), _end_day(st.get("end_at"))
        pct = V.num(st.get("cvr_adjustment_percent"))
        ids = sorted(set(V.split_list(st.get("campaign_ids"), (" | ", ";", "|", ","))))
        base = {"setting": {k: st.get(k) for k in sorted(st)}, "account_time_zone": tz}
        if s is None or e is None or pct is None:
            chk.partial(f"setting {aid}: unparseable dates or percent")
            continue
        if st.get("timezone") and tz and str(st.get("timezone")) != str(tz):
            chk.finding("timezone_mismatch", "Info", {"adjustment_id": aid},
                        f"Setting {aid} timezone {st.get('timezone')} differs from account {tz}",
                        evidence=base, recommendation="Confirm the exact local start/end hours.",
                        uncertainty="Offset may shift the window by hours only.")
        for cid in ids:
            entity = {"adjustment_id": aid, "campaign_id": cid}
            if support.get(cid) == "unsupported":
                chk.finding("unsupported_scope", "Info", entity,
                            f"Setting {aid} includes campaign {cid} whose strategy/channel is unsupported",
                            evidence=base, recommendation="Remove from scope or confirm eligibility.",
                            uncertainty="Support list may change; verify in Ads.")
            matches = [ev for ev in events if str(ev.get("campaign_id")) == cid
                       and _event_window(ev)[0] and _event_window(ev)[1]
                       and _event_window(ev)[0] <= e and _event_window(ev)[1] >= s]
            if not matches:
                sev = "Warning" if calendar_complete else "Info"
                prov = chk.finding("no_documented_event", sev, entity,
                                   f"Setting {aid} ({s}..{e}, {pct:+g}%) on campaign {cid} matches no documented event",
                                   evidence={**base, "calendar_manifest_complete": calendar_complete},
                                   recommendation="Request the owner's event justification or removal review.",
                                   uncertainty="" if calendar_complete else "Event calendar completeness not certified.")
                _harm_review(chk, entity, base, prov)
                continue
            for ev in matches:
                es, ee = _event_window(ev)
                chg = V.rate(ev.get("expected_cvr_change"), "fraction")
                rng = _estimate_range(ev.get("estimate_range"))
                problems = []
                if s < es or e > ee:
                    problems.append(f"dates {s}..{e} extend beyond event window {es}..{ee}")
                if chg is not None and chg != 0 and pct != 0 and (chg > 0) != (pct > 0):
                    problems.append(f"sign {pct:+g}% opposite to expected change {chg:+.2%}")
                if rng is not None and not (rng[0] <= pct <= rng[1]):
                    problems.append(f"{pct:+g}% outside estimate_range {rng[0]:g}..{rng[1]:g}")
                if not problems:
                    chk.observe(f"Setting {aid} consistent with event {ev.get('event_id')} for {cid}",
                                adjustment_id=aid, campaign_id=cid, event_id=ev.get("event_id"))
                    continue
                ent = {**entity, "event_id": ev.get("event_id")}
                prov = chk.finding("setting_contradicts_event", "Warning", ent,
                                   f"Setting {aid} contradicts documented event {ev.get('event_id')}: "
                                   + "; ".join(problems),
                                   evidence={**base, "event": {k: ev.get(k) for k in sorted(ev)},
                                             "estimate_range_parsed": rng, "problems": problems},
                                   recommendation="Request owner review to align dates/scope/percent with the event.",
                                   uncertainty="Delivery impact not measured here.")
                _harm_review(chk, ent, base, prov)
    by_c: dict[str, list] = {}
    for st in settings:
        s, e = _start_day(st.get("start_at")), _end_day(st.get("end_at"))
        if s and e:
            for cid in V.split_list(st.get("campaign_ids"), (" | ", ";", "|", ",")):
                by_c.setdefault(cid, []).append((s, e, str(st.get("adjustment_id")), str(st.get("device_scope") or "")))
    for cid in sorted(by_c):
        items = sorted(by_c[cid])
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if b[0] <= a[1] and (a[3] == b[3] or "" in (a[3], b[3]) or "ALL" in (a[3].upper(), b[3].upper())):
                    entity = {"campaign_id": cid, "adjustment_ids": [a[2], b[2]]}
                    prov = chk.finding("overlapping_adjustments", "Info", entity,
                                       f"Settings {a[2]} and {b[2]} overlap on campaign {cid} ({b[0]}..{min(a[1], b[1])})",
                                       evidence={"windows": [a[:2], b[:2]], "device_scopes": [a[3], b[3]]},
                                       recommendation="Confirm intended stacking with the owner.",
                                       uncertainty="Combined effect depends on platform stacking rules.")
                    _harm_review(chk, entity, {"windows": [a[:2], b[:2]]}, prov)


def _harm_review(chk, entity, evidence, provisional) -> None:
    chk.review("configured_scope_harm", entity,
               "Is there direct evidence that this configured scope/date conflict caused MATERIAL delivery harm?",
               evidence=evidence,
               outcomes={"material_delivery_harm": {"severity": "Critical", "recommendation":
                                                    "Prioritize owner review; cite the delivery evidence."},
                         "no_material_harm": {"severity": provisional.severity, "recommendation":
                                              "Keep the deterministic severity."}},
               guidance="Critical needs proposal.evidence_ref to supplied delivery evidence.",
               provisional=provisional)


# ---------------------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs evidence_ref; proposals must fit event scope, window, sign and estimate range."""
    outcome = decision.get("outcome")
    p = decision.get("proposal") or {}
    if outcome == "material_delivery_harm":
        return [] if p.get("evidence_ref") else ["material_delivery_harm needs proposal.evidence_ref"]
    if item.condition_key != "future_adjustment" or outcome != "propose_adjustment":
        return []
    ev = item.evidence
    problems = []
    pct = V.num(p.get("cvr_adjustment_percent"))
    s, e = V.parse_date(p.get("start")), V.parse_date(p.get("end"))
    ids = [str(x) for x in (p.get("campaign_ids") or [])]
    if pct is None or s is None or e is None or not ids:
        return ["proposal needs cvr_adjustment_percent, start, end, campaign_ids"]
    if ids != [item.entity["campaign_id"]]:
        problems.append(f"campaign_ids {ids} differ from reviewed campaign {item.entity['campaign_id']}")
    ws, we = (V.parse_date(x) for x in ev["window"])
    if ws and we and (s < ws or e > we or e < s):
        problems.append(f"proposal {s}..{e} outside documented window {ws}..{we}")
    chg = ev.get("expected_cvr_change")
    if chg is not None and pct != 0 and (chg > 0) != (pct > 0):
        problems.append("proposal sign contradicts expected_cvr_change")
    if pct < 0 and not _exceptional(ev):
        problems.append("negative proposal needs a documented exceptional_future_reason")
    rng = _estimate_range(ev.get("estimate_range"))
    if rng is not None and not (rng[0] <= pct <= rng[1]):
        problems.append(f"{pct:+g}% outside estimate_range {rng[0]:g}..{rng[1]:g}")
    if ev.get("strategy_support") == "unsupported":
        problems.append("campaign strategy/channel does not support seasonality adjustments")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
