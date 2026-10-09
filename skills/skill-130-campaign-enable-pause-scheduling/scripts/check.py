"""check.py — skill-130 deterministic comparison of campaign status/schedules with approved event plans.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-130-campaign-enable-pause-scheduling/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Events join to campaigns only by explicit campaign_id; names are never matched. Only approval_status starting
         'approved' counts as an approved plan. Other rows and unknown campaign IDs are Info (missing event evidence).
         Intended windows are read in the plan row's timezone, campaign date settings in the account time zone.
         Configuration is compared only with each campaign's governing event: active at as_of, else the next upcoming,
         else the latest completed (status only). Date fields never prove hour-level scheduling. A plan with
         start_stop_precision hour/minute needs an enabled non-recurring exact-time rule within that precision;
         otherwise it is Info (unverified).
         Warning 'schedule_contradicts_plan' when the configured start/end date, an enabled ENABLE/PAUSE rule, or the
         snapshot status contradicts the approved window or campaign_expected_status. A PAUSED campaign whose plan
         gives intentional_pause_reason is Info. A missing stop mechanism is a Warning only when
         campaign_schedule_rules is manifest-complete.
         Post-event delivery comes only from campaign_metrics: dated rows after the event end, or a report period
         wholly after it. Enabled status alone is never delivery. Served-after-event → Warning; Critical only via review
         with proposal.evidence_ref (invalid, material offer) equal to the review evidence_refs entry
         'external/campaign_event_plan:<event_id>:<campaign_id>', emitted only when that plan row names an offer.
         Replacement: replacement_required true needs the replacement campaign present and ENABLED or starting (date or
         ENABLE rule) by the day after the old event end; else Warning. No replacement for a completed one-off event is
         not a gap. Output is a request-only schedule specification; nothing is enabled, paused or created.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | Critical evidence_ref must be the reviewed event's offer-plan ref
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

SKILL = "skill-130-campaign-enable-pause-scheduling"
VERSION = "1.0.0"

PLAN = "external/campaign_event_plan"
RULES = "custom/campaign_schedule_rules"
_PRECISION = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1)}


def _tz(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(str(name)) if name else None
    except Exception:  # noqa: BLE001 — unknown zone or no tz database
        return None


def _ts(v, tzname=None) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        tz = _tz(tzname)
        return dt.replace(tzinfo=tz) if tz is not None else dt
    return dt


def _local_date(dt: datetime, acct_tz) -> date:
    return dt.astimezone(acct_tz).date() if dt.tzinfo is not None and acct_tz is not None else dt.date()


def _approved(v) -> bool:
    s = V.norm_text(v)
    return s.startswith("approved")


def _rules_by_campaign(ctx) -> dict[str, list[dict]]:
    """Latest snapshot rows per campaign."""
    out: dict[str, list[dict]] = {}
    for r in ctx.rows(RULES):
        out.setdefault(str(r.get("campaign_id")), []).append(r)
    for cid, rows in out.items():
        latest = max(str(r.get("snapshot_at") or "") for r in rows)
        out[cid] = sorted((r for r in rows if str(r.get("snapshot_at") or "") == latest), key=lambda r: str(r.get("rule_id")))
    return out


def _offer_refs(row: dict) -> list[str]:
    """Ref of the approved plan row that documents dated offer terms; empty when the plan names no offer."""
    if not str(row.get("offer") or "").strip():
        return []
    return [f"{PLAN}:{row.get('event_id')}:{row.get('campaign_id')}"]


def run(ctx) -> None:
    """Run event join, schedule window, post-event delivery and replacement checks.

    Rules:   Join only by explicit campaign_id on 'approved*' plans; unmatched events → Info event_evidence_missing.
             Warning schedule_contradicts_plan for date/rule/status contradictions; missing stop mechanism only with
             manifest-complete rules; hour precision unverified → Info. served_after_event needs dated campaign_metrics
             after end (Critical only via review + evidence_ref); replacement_not_ready is Warning. Nothing is enabled
             or paused.
    """
    acct_tz = _tz(ctx.account.get("time_zone"))
    join = ctx.check("event_join", "Join approved events to explicit campaign IDs",
                     {PLAN: ["event_id", "campaign_id", "start_at", "end_at", "timezone", "owner", "approval_status"],
                      "campaigns": ["id", "status"]})
    window = ctx.check("window_compare", "Intended windows versus campaign dates and exact-time rules",
                       {PLAN: ["event_id", "campaign_id", "start_at", "end_at", "timezone", "campaign_expected_status",
                               "start_stop_precision"]})
    delivery = ctx.check("post_event_delivery", "Delivery after the approved event end",
                         {PLAN: ["event_id", "campaign_id", "end_at", "timezone"],
                          "campaign_metrics": ["campaign_id", "impressions", "cost"]})
    repl = ctx.check("replacement_readiness", "Required replacement readiness",
                     {PLAN: ["event_id", "campaign_id", "end_at", "replacement_required", "replacement_campaign_id"]})
    draft = ctx.check("rule_draft", "Request-only start/stop specification",
                      {PLAN: ["event_id", "campaign_id", "start_at", "end_at", "timezone", "owner"]})
    if not join.runnable:
        for c in (window, delivery, repl, draft):
            if c.runnable:
                c.skip("event plan or campaign inventory unavailable", join.missing)
        return
    if ctx.account.get("time_zone") and acct_tz is None:
        join.partial(f"time zone {ctx.account.get('time_zone')} unavailable locally: dates use timestamp offsets")
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    rules_t = ctx.table(RULES)
    rules_ok = rules_t is not None and not rules_t.missing(["campaign_id", "rule_id", "snapshot_at", "enabled", "action",
                                                           "scheduled_at", "timezone"])
    rules = _rules_by_campaign(ctx) if rules_ok else {}
    if not rules_ok:
        window.partial("campaign_schedule_rules unavailable: exact-time rules and configured dates unknown",
                       [f"{RULES} (file)"] if rules_t is None else [f"{RULES}:{c}" for c in rules_t.missing(
                           ["campaign_id", "rule_id", "snapshot_at", "enabled", "action", "scheduled_at", "timezone"])])
    as_of = ctx.as_of

    events = []
    for r in sorted(ctx.rows(PLAN), key=lambda r: (str(r.get("event_id")), str(r.get("campaign_id")))):
        cid, eid = str(r.get("campaign_id") or ""), str(r.get("event_id"))
        s, e = _ts(r.get("start_at"), r.get("timezone")), _ts(r.get("end_at"), r.get("timezone"))
        entity = {"event_id": eid, "campaign_id": cid}
        ev = {"event_name": r.get("name"), "start_at": r.get("start_at"), "end_at": r.get("end_at"), "timezone": r.get("timezone"),
              "approval_status": r.get("approval_status"), "owner": r.get("owner"), "offer": r.get("offer"),
              "campaign_status": (camps.get(cid) or {}).get("status")}
        if cid not in camps:
            join.finding("event_evidence_missing", "Info", entity, f"Event {eid}: campaign {cid or '(none)'} not in campaigns",
                         evidence=ev, recommendation="Map the event to an explicit campaign ID.",
                         uncertainty="Campaign names are never matched to events.")
            continue
        if not _approved(r.get("approval_status")) or s is None or e is None:
            join.finding("event_evidence_missing", "Info", entity,
                         f"Event {eid} (campaign {cid}): plan not approved or window unparseable", evidence=ev,
                         recommendation="Obtain an approved, timezone-explicit event window.",
                         uncertainty="Unapproved or undated plans cannot be compared with configuration.")
            continue
        if s.tzinfo is None or e.tzinfo is None:
            join.partial(f"event {eid}: timezone {r.get('timezone')} unresolved; window read as naive local time")
        events.append({"row": r, "cid": cid, "eid": eid, "start": s, "end": e, "entity": entity, "ev": ev})
    join.observe("Event plan join", approved_events=len(events), plan_rows=len(ctx.rows(PLAN)))

    # -- step 2: windows versus configuration
    if window.runnable:
        governing: dict[str, dict] = {}
        for x in events:
            x["s_d"], x["e_d"] = _local_date(x["start"], acct_tz), _local_date(x["end"], acct_tz)
        for cid in sorted({x["cid"] for x in events}):
            mine = [x for x in events if x["cid"] == cid]
            live = sorted((x for x in mine if as_of is not None and x["e_d"] >= as_of), key=lambda x: (x["s_d"], x["eid"]))
            past = sorted((x for x in mine if x not in live), key=lambda x: (x["e_d"], x["eid"]))
            governing[cid] = live[0] if live else past[-1]
            for x in mine:
                if x is not governing[cid]:
                    window.observe(f"Event {x['eid']}: not the governing event for campaign {cid} at {as_of}",
                                   event_id=x["eid"], campaign_id=cid, governing_event=governing[cid]["eid"])
        for cid, x in sorted(governing.items()):
            r, camp = x["row"], camps[cid]
            s_d, e_d = x["s_d"], x["e_d"]
            crules = rules.get(cid, [])
            enabled = [q for q in crules if V.boolean(q.get("enabled")) is True]
            cfg_start = V.parse_date(next((q.get("current_start_date") for q in crules if q.get("current_start_date")), None)) \
                or V.parse_date(camp.get("start_date"))
            cfg_end = V.parse_date(next((q.get("current_end_date") for q in crules if q.get("current_end_date")), None)) \
                or V.parse_date(camp.get("end_date"))
            precision = V.norm_text(r.get("start_stop_precision")) or "day"
            status = str(camp.get("status") or "").upper()
            expected = str(r.get("campaign_expected_status") or "").upper()
            completed = as_of is not None and e_d < as_of
            problems = []
            if not completed:
                if cfg_end and cfg_end != e_d:
                    problems.append(f"configured end date {cfg_end} != event end {e_d}")
                if cfg_start and (cfg_start > s_d or (as_of is not None and cfg_start > as_of and cfg_start != s_d)):
                    problems.append(f"configured start date {cfg_start} != event start {s_d}")
                tol = _PRECISION.get(precision)
                for action, target in (("ENABLE", x["start"]), ("PAUSE", x["end"])):
                    fixed = [q for q in enabled if str(q.get("action") or "").upper() == action and not q.get("recurrence")]
                    times = [t for t in (_ts(q.get("scheduled_at"), q.get("timezone")) for q in fixed) if t is not None]
                    if not times:
                        continue
                    try:
                        match = any((abs(t - target) < tol) if tol else _local_date(t, acct_tz) == _local_date(target, acct_tz)
                                    for t in times)
                    except TypeError:
                        window.partial(f"campaign {cid}: naive/aware rule timestamps not comparable")
                        continue
                    if not match:
                        problems.append(f"enabled {action} rule(s) at {sorted(t.isoformat() for t in times)} miss plan "
                                        f"{target.isoformat()} ({precision} precision)")
                if not cfg_end and not any(str(q.get("action") or "").upper() == "PAUSE" for q in enabled):
                    if rules_ok and rules_t.complete is True:
                        problems.append("no configured end date or enabled PAUSE rule for the approved end")
                    else:
                        window.partial(f"event {x['eid']}: stop mechanism unknown (rules not certified complete)")
            if expected and status and status != expected:
                if status == "PAUSED" and r.get("intentional_pause_reason"):
                    window.finding("intentional_in_season_pause", "Info", x["entity"],
                                   f"Campaign {cid} paused during event {x['eid']}: {r.get('intentional_pause_reason')}",
                                   evidence={**x["ev"], "expected_status": expected},
                                   recommendation="Keep; confirm the resume condition with the owner.",
                                   uncertainty="Intentional stock, margin, compliance or capacity pause.")
                else:
                    problems.append(f"status {status} at snapshot != planned {expected}")
            exact_rules = [q for q in enabled if str(q.get("action") or "").upper() in ("ENABLE", "PAUSE")]
            ev = {**x["ev"], "intended_local_dates": [s_d, e_d], "configured_start": cfg_start, "configured_end": cfg_end,
                  "enabled_rules": [{"rule_id": q.get("rule_id"), "action": q.get("action"), "scheduled_at": q.get("scheduled_at"),
                                     "timezone": q.get("timezone"), "recurrence": q.get("recurrence"),
                                     "last_result": q.get("last_result")} for q in enabled],
                  "precision": precision, "expected_status": expected, "status": status, "event_completed": completed}
            if problems:
                window.finding("schedule_contradicts_plan", "Warning", x["entity"],
                               f"Event {x['eid']} / campaign {cid}: " + "; ".join(problems), evidence=ev,
                               recommendation="Request-only correction of dates/rules/status to the approved plan; owner approves.",
                               uncertainty="Configuration snapshot only; delivery is checked separately.")
            elif precision in _PRECISION and not completed and not exact_rules:
                window.finding("hour_precision_unverified", "Info", x["entity"],
                               f"Event {x['eid']} needs {precision}-level start/stop but only date fields are configured",
                               evidence=ev, recommendation="Specify exact-time rules in the request.",
                               uncertainty="Date fields do not prove hour-level scheduling.")
            else:
                window.observe(f"Event {x['eid']} / campaign {cid}: configuration consistent with plan", **ev)

    # -- step 3: actual delivery after the approved end
    if delivery.runnable:
        cm = ctx.table("campaign_metrics")
        dated = "date" in cm.columns
        for x in events:
            e_d = _local_date(x["end"], acct_tz)
            if as_of is None or e_d >= as_of:
                continue
            rows = [m for m in cm.rows if str(m.get("campaign_id")) == x["cid"]]
            if dated:
                after = [m for m in rows if (V.parse_date(m.get("date")) or date.min) > e_d]
                basis = f"dated campaign_metrics after {e_d}"
            elif ctx.period_start and ctx.period_start > e_d:
                after = rows
                basis = f"report period {ctx.period_start}..{ctx.period_end} wholly after event end {e_d}"
            else:
                delivery.partial(f"event {x['eid']}: report period overlaps the event end; delivery after end unknown",
                                 ["campaign_metrics:date"])
                continue
            impr = [V.num(m.get("impressions")) for m in after]
            cost = [ctx.money(m.get("cost")) for m in after]
            if any(v is None for v in impr):
                delivery.partial(f"event {x['eid']}: unknown impressions after end")
                continue
            served, spend = sum(impr), None if any(v is None for v in cost) else sum(cost)
            ev = {**x["ev"], "event_end_local": e_d, "basis": basis, "impressions_after_end": served, "cost_after_end": spend}
            if served > 0:
                window_f = delivery.finding("served_after_event", "Warning", x["entity"],
                                            f"Campaign {x['cid']} served {served:g} impressions after event {x['eid']} ended {e_d}",
                                            evidence=ev, recommendation="Request-only stop/replacement per the approved plan.",
                                            uncertainty="Delivery is proven; whether the offer became invalid is not.")
                delivery.review("served_after_event", x["entity"],
                                f"Did campaign {x['cid']} deliver an INVALID time-bound offer after event {x['eid']}, materially?",
                                evidence={**ev, "evidence_refs": _offer_refs(x["row"])},
                                outcomes={"invalid_offer_material": {"severity": "Critical", "recommendation":
                                          "Escalate to the owner; request an immediate stop with evidence."},
                                          "offer_not_invalid": {"severity": None, "recommendation": f"Keep as {window_f.severity}."}},
                                guidance="Critical needs proposal.evidence_ref equal to one of evidence.evidence_refs "
                                         "(the approved plan row carrying the dated offer terms) showing invalidity.")
            else:
                delivery.observe(f"Campaign {x['cid']}: no delivery after event {x['eid']}", **ev)

    # -- step 4: replacement readiness
    if repl.runnable:
        for x in events:
            r = x["row"]
            req = V.boolean(r.get("replacement_required"))
            rid = str(r.get("replacement_campaign_id") or "")
            e_d = _local_date(x["end"], acct_tz)
            if req is not True:
                repl.observe(f"Event {x['eid']}: no replacement required", event_id=x["eid"], replacement_required=req)
                continue
            rc = camps.get(rid)
            starts = [V.parse_date(rc.get("start_date"))] if rc else []
            starts += [_local_date(t, acct_tz) for q in rules.get(rid, []) if V.boolean(q.get("enabled")) is True
                       and str(q.get("action") or "").upper() == "ENABLE" for t in [_ts(q.get("scheduled_at"), q.get("timezone"))] if t]
            ready = rc is not None and (str(rc.get("status") or "").upper() == "ENABLED"
                                        or any(d and d <= e_d + timedelta(days=1) for d in starts))
            ev = {**x["ev"], "replacement_campaign_id": rid or None, "replacement_status": (rc or {}).get("status"),
                  "replacement_starts": starts, "old_event_end_local": e_d}
            if not ready:
                repl.finding("replacement_not_ready", "Warning", x["entity"],
                             f"Event {x['eid']}: required replacement {rid or '(none)'} not present or not scheduled by {e_d + timedelta(days=1)}",
                             evidence=ev, recommendation="Request-only readiness plan for the replacement with its owner.",
                             uncertainty="Readiness from configuration only; creative/approval readiness not evidenced.")
            else:
                repl.observe(f"Event {x['eid']}: replacement {rid} ready", **ev)

    # -- step 5: request-only rule specification
    if draft.runnable:
        for x in events:
            r = x["row"]
            spec = []
            for state, t in (("ENABLED", x["start"]), ("PAUSED", x["end"])):
                off = t.utcoffset() if t.tzinfo else None
                spec.append({"desired_state": state, "local_time": t.isoformat(), "timezone": r.get("timezone"),
                             "utc_offset": None if off is None else f"{off.total_seconds() / 3600:+g}h",
                             "verification_time": (t + timedelta(hours=1)).isoformat()})
            draft.observe(f"Event {x['eid']}: request-only schedule specification", event_id=x["eid"], campaign_id=x["cid"],
                          transitions=spec, recurrence=next((q.get("recurrence") for q in rules.get(x["cid"], [])
                                                             if q.get("recurrence")), None),
                          prerequisites={"replacement_campaign_id": r.get("replacement_campaign_id"),
                                         "replacement_required": r.get("replacement_required")},
                          manual_override="owner may pause/enable manually; rule must not re-enable an intentional pause",
                          owner=r.get("owner"), action="request only; no status change or rule creation here")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   'invalid_offer_material' (Critical) requires proposal.evidence_ref equal to one of the reviewed item's
             evidence.evidence_refs, i.e. the approved campaign_event_plan row of this event_id/campaign_id with a
             non-empty offer (built by _offer_refs); unknown refs or refs of other events/campaigns are rejected.
             offer_not_invalid needs no proposal.
    """
    if decision.get("outcome") != "invalid_offer_material":
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return ["Critical needs proposal.evidence_ref to dated offer terms/ad copy showing invalidity"]
    if ref not in (item.evidence.get("evidence_refs") or []):
        return [f"evidence_ref {ref} is not an offer-terms reference of event {item.entity.get('event_id')} / "
                f"campaign {item.entity.get('campaign_id')} (allowed: {item.evidence.get('evidence_refs') or 'none'})"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
