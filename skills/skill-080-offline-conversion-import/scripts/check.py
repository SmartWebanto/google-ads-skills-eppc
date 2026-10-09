"""check.py — skill-080 deterministic offline conversion pipeline coverage, acceptance and freshness.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-080-offline-conversion-import/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #110 Automatically import offline conversions from Google Sheet (gist kovacsgaborpal) — INTEGRATED as
         read-only pre-upload validation only (check upload_payload_validation of a supplied
         external/offline_upload_payload.csv against conversion_actions and optional custom/click_ids.csv);
         REFUSED: reading the Sheet, uploading/scheduling conversions and any other account mutation or network call.
rules:   Events deduplicate by (action_id, event_token); retries never count twice; batches never count as events.
         Payload/click-id columns hold LOCAL PSEUDONYMS, never raw gclid/gbraid/wbraid: presence, type, duplicates and
         click-time joins only; identifier format and platform matchability are not validated.
         Timestamps MUST carry an explicit UTC offset; naive/unparseable → event excluded and check partial.
         Delays: event_to_ready = ready - business_event; queue = first submitted - ready; processing =
         processed - submitted (accepted attempt); total = processed - business_event. Negative → data-quality note.
         Censored age for unsubmitted/pending events is measured to 00:00 of ctx.snapshot (else ctx.as_of) in the
         event's own offset — conservative, never the clock.
         Warning only against DOCUMENTED config SLAs (ready_to_submit_sla_hours, processing_expectation_hours) or
         an unresolved rejection of an eligible event. Batch cadence gaps are Info. No outcomes → Info.
         Critical (material loss of required eligible outcomes) only via review with proposal.evidence_ref.
         Acceptance = distinct accepted eligible events / attempted eligible events (V.ratio); accepted ≠ matched ≠
         attributed; match rate needs a separate matching denominator (not in this schema → not computed).
         Click-to-conversion lag is attribution delay, never used as upload freshness.
         upload_payload_validation (opt-in: runs only when external/offline_upload_payload.csv is supplied, else
         skipped): per-row Warning rules sourced from Google Ads Help read 2026-09-25 —
         support.google.com/google-ads/answer/7014069 (Conversion Name exact spelling+capitalization; Conversion Time
         yyyy-MM-dd[ T]HH:mm:ss±HHMM or MM/dd/yyyy HH:mm:ss ±HHMM; value optional number; currency optional ISO 4217
         3-char; uniqueness = identifier+name+time), /15081888 (duplicate identifier+name+date+time imported once),
         /13321563 (action source must be "Import from clicks"; conversion can't precede click; older than the
         conversion window fails) plus API ConversionUploadError (GBRAID_WBRAID_BOTH_SET, DUPLICATE_ORDER_ID,
         EXPIRED_EVENT, INVALID_CONVERSION_ACTION_TYPE) and API ±HH:mm offsets. Exactly one of gclid/gbraid/wbraid.
         Raw click ids and order ids NEVER enter outputs — only spreadsheet row numbers (header = row 1) and counts.
         Actions join on exact conversion_name (the template's own key); ambiguous/unknown status/type/window →
         partial, never a finding. Time-zone-ID times are not resolved (partial). Future = conversion at/after 00:00
         of ctx.snapshot+1 day in the row's own offset.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx110 | index #110: pre-upload payload validation
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | payload click references are local pseudonyms, not raw ids
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-080-offline-conversion-import"
VERSION = "1.1.0"

CFG = "external/offline_pipeline_config"
OUT = "external/offline_outcomes"
ATT = "external/offline_upload_attempts"
DAILY = "custom/offline_action_daily"
ACCEPTED = {"accepted", "success", "succeeded", "uploaded", "processed"}
REJECTED = {"rejected", "failed", "failure", "error"}
PENDING = {"pending", "queued", "submitted", "in_progress", "processing"}

PAYLOAD = "external/offline_upload_payload"
CLICKS = "custom/click_ids"
CLICK_ID_COLS = ("gclid", "gbraid", "wbraid")
UPLOAD_CLICK_TYPES = {"upload_clicks", "import from clicks"}
SAMPLE_ROWS = 10
HELP_FORMAT = "https://support.google.com/google-ads/answer/7014069 (read 2026-09-25)"
HELP_GUIDE = "https://support.google.com/google-ads/answer/15081888 (read 2026-09-25)"
HELP_ERRORS = "https://support.google.com/google-ads/answer/13321563 (read 2026-09-25)"
API_ERRORS = ("https://developers.google.com/google-ads/api/reference/rpc/v25/"
              "ConversionUploadErrorEnum.ConversionUploadError (read 2026-09-25)")
API_TIME = "https://developers.google.com/google-ads/api/docs/conversions/upload-offline (read 2026-09-25)"
# condition_key -> (what failed, documented rule, sources)
PAYLOAD_RULES = {
    "payload_click_id_count_invalid": (
        "rows without exactly one click identifier (gclid, gbraid or wbraid)",
        "Each row carries exactly one click identifier; gbraid and wbraid may not both be set.",
        [API_ERRORS + " GBRAID_WBRAID_BOTH_SET"]),
    "payload_conversion_action_not_found": (
        "rows whose conversion_name matches no conversion action exactly",
        "Conversion Name must use the same spelling and capitalization as the action in the account.",
        [HELP_FORMAT, API_ERRORS + " NO_CONVERSION_ACTION_FOUND"]),
    "payload_conversion_action_not_enabled": (
        "rows whose conversion action is not ENABLED",
        "Conversions are imported only into an enabled conversion action.",
        [API_TIME + " (conversion_action.status = 'ENABLED')"]),
    "payload_conversion_action_not_import_type": (
        "rows whose conversion action is not an 'Import from clicks' (UPLOAD_CLICKS) action",
        "The conversion action source must be 'Import from clicks'.",
        [HELP_ERRORS, API_ERRORS + " INVALID_CONVERSION_ACTION_TYPE"]),
    "payload_conversion_time_invalid": (
        "rows whose conversion_time is missing, unparseable or has no UTC offset",
        "Conversion Time needs a supported format with a time zone offset (e.g. yyyy-MM-dd HH:mm:ss+0100); this "
        "payload has no Parameters:TimeZone row.",
        [HELP_FORMAT, API_TIME]),
    "payload_conversion_time_in_future": (
        "rows whose conversion_time is after the snapshot date",
        "A payload row cannot report a conversion that had not happened by the evidence snapshot.",
        ["recipe contract (index #110 pre-upload validation); not a quoted Google rule"]),
    "payload_conversion_precedes_click": (
        "rows whose conversion_time is before the supplied click_time",
        "The offline conversion can't happen before the ad click.",
        [HELP_ERRORS, API_ERRORS + " CONVERSION_PRECEDES_EVENT"]),
    "payload_outside_click_window": (
        "rows whose conversion_time is later than click_time + the action's click-through window",
        "A conversion older than the action's conversion window is not recorded.",
        [HELP_ERRORS, API_ERRORS + " EXPIRED_EVENT"]),
    "payload_conversion_value_invalid": (
        "rows whose conversion_value is not a plain non-negative number",
        "Conversion Value (optional) is a number; blank applies the action default.",
        [HELP_FORMAT]),
    "payload_conversion_currency_invalid": (
        "rows whose conversion_currency is not a 3-letter ISO 4217 code",
        "Conversion Currency (optional) uses 3-character ISO 4217 codes such as USD or JPY.",
        [HELP_FORMAT]),
    "payload_duplicate_order_id": (
        "rows sharing an order_id with another row",
        "Multiple conversions with the same order ID are not processed.",
        [API_ERRORS + " DUPLICATE_ORDER_ID"]),
    "payload_duplicate_click_conversion": (
        "rows repeating the same click identifier, conversion_name and conversion_time",
        "The same identifier + conversion name + date and time is imported only once; duplicates return an error.",
        [HELP_GUIDE, HELP_FORMAT, API_ERRORS + " DUPLICATE_CLICK_CONVERSION_IN_REQUEST"]),
}
_TIME = re.compile(r"^(?:(\d{4})-(\d{2})-(\d{2})|(\d{2})/(\d{2})/(\d{4}))[ T](\d{1,2}):(\d{2}):(\d{2})"
                   r" ?([+-])(\d{2}):?(\d{2})$")
_TIME_ZONE_ID = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})[ T]\d{1,2}:\d{2}:\d{2} [A-Za-z_]+/[A-Za-z_/+-]+$")
_DECIMAL = re.compile(r"^[-+]?(\d+(\.\d+)?|\.\d+)$")
_ISO4217 = re.compile(r"^[A-Z]{3}$")


def _ts(v) -> datetime | None:
    """Offset-aware datetime or None (naive or unparseable timestamps are unusable)."""
    s = str(v or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo is not None else None


def _hours(a: datetime | None, b: datetime | None) -> float | None:
    return None if a is None or b is None else (b - a).total_seconds() / 3600


def _status(v) -> str:
    s = V.norm_text(v).replace(" ", "_")
    return "accepted" if s in ACCEPTED else "rejected" if s in REJECTED else "pending" if s in PENDING else "unknown"


def _pct(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile of a completed cohort."""
    if not values:
        return None
    xs = sorted(values)
    k = max(1, -(-int(q * 100) * len(xs) // 100))
    return xs[min(k, len(xs)) - 1]


def _cutoff(ctx, tz) -> datetime | None:
    d = ctx.snapshot or ctx.as_of
    return datetime.combine(d, time(0), tzinfo=tz) if d and tz else None


class _Event:
    __slots__ = ("action_id", "token", "row", "attempts")

    def __init__(self, action_id, token, row):
        self.action_id, self.token, self.row, self.attempts = action_id, token, row, []

    @property
    def eligible(self) -> bool | None:
        return V.boolean(self.row.get("eligible_for_upload"))

    def state(self) -> str:
        sts = {_status(a.get("status")) for a in self.attempts}
        if not self.attempts:
            return "unattempted"
        for s in ("accepted", "pending", "rejected"):
            if s in sts:
                return s
        return "unknown"

    def first_submitted(self) -> datetime | None:
        ts = [t for t in (_ts(a.get("submitted_timestamp")) for a in self.attempts) if t]
        return min(ts) if ts else None

    def accepted_attempt(self) -> dict | None:
        acc = [a for a in self.attempts if _status(a.get("status")) == "accepted"]
        acc.sort(key=lambda a: (str(a.get("processed_timestamp") or ""), str(a.get("attempt_id"))))
        return acc[0] if acc else None


def _entity(ctx, action_id, integration_id=None) -> dict:
    e = {"account_id": ctx.account_id, "action_id": action_id}
    if integration_id:
        e["integration_id"] = integration_id
    return e


def run(ctx) -> None:
    """Run the offline-import pipeline map, reconciliation, freshness, SLA, cadence and acceptance checks.

    Rules:   Events dedupe by (action_id, event_token); naive/unparseable timestamps → excluded + partial. Warning only
             for breaches of DOCUMENTED config SLAs or unresolved rejections of eligible events; cadence gaps and
             no-outcome periods are Info. Critical only via ai_review 'material_loss_evidenced' with
             proposal.evidence_ref. Censored ages end at ctx.snapshot/as_of midnight (never the clock); match rate is
             never computed. upload_payload_validation runs only on a supplied external/offline_upload_payload.csv:
             deterministic per-error-type Warnings with row numbers, never raw click/order ids, never an upload.
    """
    configs = _pipeline_map(ctx)
    events = _events(ctx)
    _reconcile(ctx, configs, events)
    _no_outcomes(ctx, configs, events)
    _ads_reporting(ctx, events)
    _freshness(ctx, events)
    _sla(ctx, configs, events)
    _cadence(ctx, configs, events)
    _acceptance(ctx, events)
    _payload_validation(ctx)


def _pipeline_map(ctx) -> dict[str, dict]:
    chk = ctx.check("pipeline_map", "Map intended offline outcomes, action ownership/type, integration and matching",
                    {CFG: ["action_id", "integration_id", "expected_business_event", "matching_method",
                           "automation_status", "owner"],
                     "conversion_actions": ["id", "type", "status"]})
    configs: dict[str, dict] = {}
    if not chk.runnable:
        return configs
    actions = {str(a.get("id")): a for a in ctx.rows("conversion_actions")}
    for r in sorted(ctx.rows(CFG), key=lambda r: (str(r.get("action_id")), str(r.get("integration_id")))):
        aid = str(r.get("action_id"))
        if aid in configs:
            chk.partial(f"action {aid}: multiple integration configs; first ({configs[aid].get('integration_id')}) used")
            continue
        configs[aid] = r
        act = actions.get(aid)
        if act is None:
            chk.partial(f"configured action {aid} not in conversion_actions; ownership/type unknown")
        chk.observe(f"Offline pipeline for action {aid}", **_entity(ctx, aid, r.get("integration_id")),
                    action_type=(act or {}).get("type"), action_status=(act or {}).get("status"),
                    expected_business_event=r.get("expected_business_event"), matching_method=r.get("matching_method"),
                    automation_status=r.get("automation_status"), owner=r.get("owner"),
                    note="A source name or store visits alone do not prove a client upload pipeline.")
    return configs


def _events(ctx) -> dict[tuple, _Event]:
    events: dict[tuple, _Event] = {}
    for r in sorted(ctx.rows(OUT), key=lambda r: (str(r.get("action_id")), str(r.get("event_token")))):
        key = (str(r.get("action_id")), str(r.get("event_token")))
        if key not in events:
            events[key] = _Event(key[0], key[1], r)
    for a in sorted(ctx.rows(ATT), key=lambda a: (str(a.get("action_id")), str(a.get("event_token")),
                                                   str(a.get("attempt_id")))):
        ev = events.get((str(a.get("action_id")), str(a.get("event_token"))))
        if ev is not None:
            ev.attempts.append(a)
    return events


def _by_action(events) -> dict[str, list[_Event]]:
    out: dict[str, list[_Event]] = {}
    for (aid, _), ev in sorted(events.items()):
        out.setdefault(aid, []).append(ev)
    return out


def _reconcile(ctx, configs, events) -> None:
    chk = ctx.check("outcome_reconciliation", "Eligible outcomes versus distinct accepted events",
                    {OUT: ["action_id", "event_token", "integration_id", "eligible_for_upload"],
                     ATT: ["action_id", "event_token", "attempt_id", "status", "retry_of_attempt_id", "rejection_code"]})
    if not chk.runnable:
        return
    known = set(events)
    orphans = sorted({(str(a.get("action_id")), str(a.get("event_token"))) for a in ctx.rows(ATT)} - known)
    if orphans:
        chk.partial(f"{len(orphans)} attempted events have no outcome row; excluded from coverage")
    for aid, evs in sorted(_by_action(events).items()):
        counts = {"eligible": 0, "ineligible": 0, "eligibility_unknown": 0, "accepted": 0, "pending": 0,
                  "rejected": 0, "unattempted": 0, "unknown_status": 0, "retried": 0}
        rejected = []
        for ev in evs:
            el = ev.eligible
            if el is None:
                counts["eligibility_unknown"] += 1
                continue
            if not el:
                counts["ineligible"] += 1
                continue
            counts["eligible"] += 1
            counts["retried"] += sum(1 for a in ev.attempts if a.get("retry_of_attempt_id"))
            st = ev.state()
            counts[st if st != "unknown" else "unknown_status"] += 1
            if st == "rejected":
                rejected.append({"event_token": ev.token, "codes": sorted({str(a.get("rejection_code"))
                                                                           for a in ev.attempts if a.get("rejection_code")})})
        integ = (configs.get(aid) or {}).get("integration_id")
        chk.observe(f"Action {aid}: eligible/attempted/accepted breakdown", **_entity(ctx, aid, integ), **counts)
        if counts["eligibility_unknown"] or counts["unknown_status"]:
            chk.partial(f"action {aid}: {counts['eligibility_unknown']} events with unknown eligibility, "
                        f"{counts['unknown_status']} with unclassified attempt status")
        if rejected:
            ev = {"rejected_events": rejected, "eligible": counts["eligible"], "accepted": counts["accepted"],
                  "owner": (configs.get(aid) or {}).get("owner")}
            chk.finding("eligible_events_rejected", "Warning", _entity(ctx, aid, integ),
                        f"{len(rejected)} of {counts['eligible']} eligible events for action {aid} were rejected "
                        f"without a successful retry", evidence=ev,
                        calculation={"numerator": len(rejected), "denominator": counts["eligible"]},
                        recommendation="Integration owner: review rejection codes and mapping; no replay or bulk "
                                       "adjustment from this analysis.",
                        uncertainty="Rejection codes come from supplied diagnostics; business materiality not assessed.")
            chk.review("material_outcome_loss", _entity(ctx, aid, integ),
                       f"Do the {len(rejected)} rejected eligible events of action {aid} represent a confirmed pipeline "
                       f"failure that MATERIALLY loses required business outcomes?",
                       evidence=ev,
                       outcomes={"material_loss_evidenced": {"severity": "Critical", "recommendation":
                                                             "Escalate to the integration owner with the evidence."},
                                 "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                       guidance="Critical requires proposal.evidence_ref to supplied loss evidence (e.g. CRM volume "
                                "vs accepted, required-outcome statement).")


def _no_outcomes(ctx, configs, events) -> None:
    chk = ctx.check("no_outcome_explanation", "No eligible outcomes versus no imports",
                    {CFG: ["action_id"], OUT: ["action_id", "eligible_for_upload"]})
    if not chk.runnable:
        return
    eligible = {}
    for (aid, _), ev in events.items():
        if ev.eligible:
            eligible[aid] = eligible.get(aid, 0) + 1
    complete = ctx.table(OUT).complete is True
    for aid in sorted(configs):
        n = eligible.get(aid, 0)
        if n:
            chk.observe(f"Action {aid}: {n} eligible outcomes in the supplied cohort", action_id=aid, eligible=n)
        elif complete:
            chk.finding("no_eligible_outcomes", "Info", _entity(ctx, aid, configs[aid].get("integration_id")),
                        f"No eligible business outcomes for action {aid} in a complete outcome export; this explains "
                        f"absent imports", evidence={"eligible": 0, "outcomes_complete": True},
                        recommendation="No pipeline action; confirm the outcome definition if imports were expected.",
                        uncertainty="A silence rule is not a failure; only eligible events plus failed processing are.")
        else:
            chk.partial(f"action {aid}: no eligible outcomes but outcome export completeness is not attested")


def _ads_reporting(ctx, events) -> None:
    chk = ctx.check("ads_action_reporting", "Ads offline action reporting for the same mature window",
                    {DAILY: ["action_id", "campaign_id", "date", "date_basis", "conversions", "reporting_mature"]})
    if not chk.runnable:
        return
    tot: dict[str, dict] = {}
    immature = 0
    for r in sorted(ctx.rows(DAILY), key=lambda r: (str(r.get("action_id")), str(r.get("campaign_id")), str(r.get("date")))):
        if V.boolean(r.get("reporting_mature")) is not True:
            immature += 1
            continue
        t = tot.setdefault(str(r.get("action_id")), {"conversions": 0.0, "unknown": 0, "bases": set()})
        c = V.num(r.get("conversions"))
        t["bases"].add(str(r.get("date_basis")))
        if c is None:
            t["unknown"] += 1
        else:
            t["conversions"] += c
    if immature:
        chk.partial(f"{immature} action-day rows not reporting-mature excluded")
    accepted = {}
    for (aid, _), ev in events.items():
        if ev.eligible and ev.state() == "accepted":
            accepted[aid] = accepted.get(aid, 0) + 1
    for aid, t in sorted(tot.items()):
        chk.observe(f"Action {aid}: mature Ads-reported conversions vs accepted uploads (descriptive)", action_id=aid,
                    ads_conversions=t["conversions"], unknown_rows=t["unknown"], date_basis=sorted(t["bases"]),
                    accepted_events=accepted.get(aid, 0),
                    note="Ads conversion-date reporting and upload acceptance are different populations.")


def _freshness(ctx, events) -> None:
    chk = ctx.check("freshness_delays", "Event-to-ready, queue, processing and total freshness with censored ages",
                    {OUT: ["action_id", "event_token", "business_event_timestamp", "ready_for_upload_timestamp"],
                     ATT: ["action_id", "event_token", "submitted_timestamp", "processed_timestamp", "status"]})
    if not chk.runnable:
        return
    for aid, evs in sorted(_by_action(events).items()):
        d = {"event_to_ready": [], "queue": [], "processing": [], "total": []}
        negative, bad_ts, outstanding = [], 0, []
        for ev in evs:
            if not ev.eligible:
                continue
            biz, ready = _ts(ev.row.get("business_event_timestamp")), _ts(ev.row.get("ready_for_upload_timestamp"))
            if biz is None or ready is None:
                bad_ts += 1
                continue
            sub = ev.first_submitted()
            acc = ev.accepted_attempt()
            proc = _ts(acc.get("processed_timestamp")) if acc else None
            acc_sub = _ts(acc.get("submitted_timestamp")) if acc else None
            vals = {"event_to_ready": _hours(biz, ready), "queue": _hours(ready, sub),
                    "processing": _hours(acc_sub, proc), "total": _hours(biz, proc)}
            for k, v in vals.items():
                if v is None:
                    continue
                if v < 0:
                    negative.append({"event_token": ev.token, "delay": k, "hours": v})
                else:
                    d[k].append(v)
            if proc is None:
                since = sub or ready
                cut = _cutoff(ctx, since.tzinfo)
                outstanding.append({"event_token": ev.token, "state": ev.state(),
                                    "age_hours_to_snapshot": _hours(since, cut), "since": "submitted" if sub else "ready"})
        if bad_ts:
            chk.partial(f"action {aid}: {bad_ts} eligible events lack offset-aware business/ready timestamps")
        if negative:
            chk.partial(f"action {aid}: {len(negative)} negative delays (data-quality issue)")
        chk.observe(f"Action {aid}: delay distribution (hours) for completed cohort", action_id=aid,
                    **{f"{k}_n": len(v) for k, v in d.items()},
                    **{f"{k}_median": _pct(v, 0.5) for k, v in d.items()},
                    **{f"{k}_p90": _pct(v, 0.9) for k, v in d.items()},
                    outstanding=outstanding, negative_delays=negative,
                    note="Censored ages measured to 00:00 of the snapshot date in each event's offset.")


def _sla(ctx, configs, events) -> None:
    chk = ctx.check("sla_compliance", "Queue/processing delay and outstanding age versus documented SLA",
                    {CFG: ["action_id", "ready_to_submit_sla_hours", "processing_expectation_hours"],
                     OUT: ["action_id", "event_token", "ready_for_upload_timestamp", "eligible_for_upload"],
                     ATT: ["action_id", "event_token", "submitted_timestamp", "processed_timestamp", "status"]})
    if not chk.runnable:
        return
    for aid, evs in sorted(_by_action(events).items()):
        cfg = configs.get(aid)
        if cfg is None:
            chk.partial(f"action {aid}: no pipeline config; SLA unknown")
            continue
        sla, proc_sla = V.num(cfg.get("ready_to_submit_sla_hours")), V.num(cfg.get("processing_expectation_hours"))
        if sla is None and proc_sla is None:
            chk.partial(f"action {aid}: SLA values unknown", [f"{CFG}:ready_to_submit_sla_hours"])
            continue
        breaches, evaluated = [], 0
        for ev in evs:
            if not ev.eligible:
                continue
            ready = _ts(ev.row.get("ready_for_upload_timestamp"))
            if ready is None:
                continue
            evaluated += 1
            sub = ev.first_submitted()
            acc = ev.accepted_attempt()
            if sla is not None:
                if sub is not None:
                    q = _hours(ready, sub)
                    if q is not None and q > sla:
                        breaches.append({"event_token": ev.token, "breach": "queue_delay", "hours": q, "sla_hours": sla})
                else:
                    age = _hours(ready, _cutoff(ctx, ready.tzinfo))
                    if age is not None and age > sla:
                        breaches.append({"event_token": ev.token, "breach": "missing_attempt_age", "hours": age,
                                         "sla_hours": sla, "censored": True})
            if proc_sla is not None and sub is not None:
                if acc is not None:
                    p = _hours(_ts(acc.get("submitted_timestamp")), _ts(acc.get("processed_timestamp")))
                    if p is not None and p > proc_sla:
                        breaches.append({"event_token": ev.token, "breach": "processing_delay", "hours": p,
                                         "sla_hours": proc_sla})
                elif ev.state() == "pending":
                    age = _hours(sub, _cutoff(ctx, sub.tzinfo))
                    if age is not None and age > proc_sla:
                        breaches.append({"event_token": ev.token, "breach": "pending_age", "hours": age,
                                         "sla_hours": proc_sla, "censored": True})
        entity = _entity(ctx, aid, cfg.get("integration_id"))
        if breaches:
            chk.finding("sla_breach", "Warning", entity,
                        f"{len({b['event_token'] for b in breaches})} of {evaluated} eligible events for action {aid} "
                        f"breach the documented ready-to-submit/processing SLA",
                        evidence={"breaches": breaches, "ready_to_submit_sla_hours": sla,
                                  "processing_expectation_hours": proc_sla, "sla_source": f"{CFG}", "owner": cfg.get("owner"),
                                  "supported_upload_window_reference": cfg.get("supported_upload_window_reference")},
                        calculation={"breaching_events": len({b['event_token'] for b in breaches}),
                                     "evaluated_events": evaluated},
                        recommendation="Integration owner: review cadence/queue for the breaching events; no replay "
                                       "or bulk upload is recommended here.",
                        uncertainty="Business impact of the delay is not measured; click lag is not upload freshness.")
            unattempted = sorted({b["event_token"] for b in breaches if b["breach"] == "missing_attempt_age"})
            if unattempted:
                chk.review("material_outcome_loss_unattempted", entity,
                           f"Do the {len(unattempted)} never-attempted eligible events of action {aid} (older than the "
                           f"{sla:g}h SLA) represent a confirmed pipeline failure that MATERIALLY loses required outcomes?",
                           evidence={"unattempted_events": unattempted, "breaches": breaches, "owner": cfg.get("owner")},
                           outcomes={"material_loss_evidenced": {"severity": "Critical", "recommendation":
                                                                 "Escalate to the integration owner with the evidence."},
                                     "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                           guidance="Critical requires proposal.evidence_ref to supplied loss evidence.")
        else:
            chk.observe(f"Action {aid}: no SLA breach among evaluated eligible events", **entity, evaluated=evaluated,
                        ready_to_submit_sla_hours=sla, processing_expectation_hours=proc_sla)


def _cadence(ctx, configs, events) -> None:
    chk = ctx.check("batch_cadence", "Observed batch timing versus intended cadence",
                    {CFG: ["action_id", "intended_cadence_hours", "automation_status"],
                     ATT: ["action_id", "integration_id", "batch_id", "submitted_timestamp"]})
    if not chk.runnable:
        return
    batches: dict[str, dict[str, datetime]] = {}
    for a in ctx.rows(ATT):
        t = _ts(a.get("submitted_timestamp"))
        if t is None or not a.get("batch_id"):
            continue
        b = batches.setdefault(str(a.get("action_id")), {})
        bid = str(a.get("batch_id"))
        b[bid] = min(b[bid], t) if bid in b else t
    for aid in sorted(set(batches) | set(configs)):
        cfg = configs.get(aid) or {}
        cad = V.num(cfg.get("intended_cadence_hours"))
        times = sorted(batches.get(aid, {}).values())
        gaps = [_hours(a, b) for a, b in zip(times, times[1:])]
        queued = []
        for (eaid, _), ev in sorted(events.items()):
            if eaid == aid and ev.eligible:
                q = _hours(_ts(ev.row.get("ready_for_upload_timestamp")), ev.first_submitted())
                if q is not None and cad is not None and q > cad:
                    queued.append({"event_token": ev.token, "queue_hours": q})
        data = {"batches": len(times), "gaps_hours": gaps, "intended_cadence_hours": cad,
                "automation_status": cfg.get("automation_status")}
        if cad is None:
            chk.partial(f"action {aid}: intended cadence unknown")
            chk.observe(f"Action {aid}: batch timing", action_id=aid, **data)
            continue
        if gaps and max(gaps) > cad and queued:
            chk.finding("cadence_review", "Info", _entity(ctx, aid, cfg.get("integration_id")),
                        f"Action {aid}: max inter-batch gap {max(gaps):.1f}h exceeds the intended {cad:g}h cadence and "
                        f"{len(queued)} events waited longer than one cadence interval",
                        evidence={**data, "events_waiting_longer_than_cadence": queued},
                        recommendation="Contextual cadence review with the integration owner.",
                        uncertainty="Manual or batched uploads are not defects unless they breach requirements.")
        else:
            chk.observe(f"Action {aid}: batch timing within intended cadence", action_id=aid, **data)


def _acceptance(ctx, events) -> None:
    chk = ctx.check("acceptance_rate", "Acceptance of attempted eligible events; matching kept separate",
                    {OUT: ["action_id", "event_token", "eligible_for_upload"],
                     ATT: ["action_id", "event_token", "status", "attributed_status_if_reported"]})
    if not chk.runnable:
        return
    for aid, evs in sorted(_by_action(events).items()):
        attempted = [e for e in evs if e.eligible and e.attempts]
        accepted = [e for e in attempted if e.state() == "accepted"]
        attributed = sum(1 for e in accepted if any(V.norm_text(a.get("attributed_status_if_reported")) == "attributed"
                                                    for a in e.attempts))
        chk.observe(f"Action {aid}: acceptance of attempted eligible events", action_id=aid,
                    numerator=len(accepted), denominator=len(attempted),
                    acceptance_rate=V.ratio(len(accepted), len(attempted)), attributed_reported=attributed,
                    match_rate=None, note="Match rate needs a separately reported matching denominator; accepted "
                                          "uploads need not be attributed.")


def _present(v) -> str | None:
    """Stripped non-empty cell text or None.

    Rules:   Presence = stripped non-empty for every payload cell (JSON may carry '' or whitespace; CSV empties
             already load as None); blank optional cells are never format errors or duplicate keys.
    """
    s = "" if v is None else str(v).strip()
    return s or None


def _payload_time(v) -> tuple[datetime | None, str]:
    """Parse a template Conversion Time: (aware datetime, 'ok') | (None, 'timezone_id' | 'invalid' | 'missing').

    Rules:   Only the documented offset forms (Help 7014069 ±HHMM, API ±HH:mm) parse; offsets beyond ±14:59 and
             impossible dates are 'invalid'. Time-zone-ID forms are recognised but never resolved (no tz database).
    """
    s = str(v or "").strip()
    if not s:
        return None, "missing"
    m = _TIME.match(s)
    if m is None:
        return None, "timezone_id" if _TIME_ZONE_ID.match(s) else "invalid"
    y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(4), m.group(5))
    oh, om = int(m.group(11)), int(m.group(12))
    if oh > 14 or om > 59:
        return None, "invalid"
    off = timedelta(hours=oh, minutes=om) * (-1 if m.group(10) == "-" else 1)
    try:
        return datetime(int(y), int(mo), int(d), int(m.group(7)), int(m.group(8)), int(m.group(9)),
                        tzinfo=timezone(off)), "ok"
    except ValueError:
        return None, "invalid"


def _click_times(ctx, chk) -> dict[str, datetime | None] | None:
    """click id -> single aware click_time (None when ambiguous/unparseable); None when click evidence is absent.

    Rules:   Joins on the exact click id string. Conflicting times for one id → None (unknown), never a guess.
             Click ids stay in memory only; nothing about them is written to outputs.
    """
    t = ctx.table(CLICKS)
    if t is None or t.missing(["click_id", "click_time"]):
        missing = [f"{CLICKS} (file)"] if t is None else [f"{CLICKS}:{c}" for c in t.missing(["click_id", "click_time"])]
        chk.partial("click evidence not supplied: conversion-before-click and click-window rules not evaluated",
                    missing)
        return None
    seen: dict[str, set] = {}
    for r in t.rows:
        cid = _present(r.get("click_id"))
        if cid is None:
            continue
        dt, _ = _payload_time(r.get("click_time"))
        seen.setdefault(str(cid), set()).add(dt or _ts(r.get("click_time")))
    return {k: (next(iter(v)) if len(v) == 1 else None) for k, v in seen.items()}


def _payload_validation(ctx) -> None:
    """Pre-upload validation of a supplied offline click-conversion payload (index #110); never uploads."""
    chk = ctx.check("upload_payload_validation",
                    "Pre-upload validation of the offline conversion payload (no upload)",
                    {PAYLOAD: ["conversion_name", "conversion_time"]})
    if not chk.runnable:
        return
    table = ctx.table(PAYLOAD)
    id_cols = [c for c in CLICK_ID_COLS if c in table.columns]
    if not id_cols:
        chk.skip("payload has no click identifier column", [f"{PAYLOAD}:gclid|gbraid|wbraid"])
        return
    actions: dict[str, list[dict]] | None = None
    act_table = ctx.table("conversion_actions")
    act_missing = (["conversion_actions (file)"] if act_table is None
                   else [f"conversion_actions:{c}" for c in act_table.missing(["name", "status", "type"])])
    if act_missing:
        chk.partial("conversion action existence/status/type rules not evaluated", act_missing)
    else:
        actions = {}
        for a in sorted(act_table.rows, key=lambda a: str(a.get("id"))):
            if a.get("name") is not None:
                actions.setdefault(str(a.get("name")), []).append(a)
        if "click_window_days" not in act_table.columns:
            chk.partial("action click-through window unknown: click-window rule not evaluated",
                        ["conversion_actions:click_window_days"])
    clicks = _click_times(ctx, chk)
    if ctx.snapshot is None:
        chk.partial("snapshot date unknown: future-time rule not evaluated", ["account:snapshot_date"])
    has_value, has_currency = "conversion_value" in table.columns, "conversion_currency" in table.columns
    has_order = "order_id" in table.columns

    failed: dict[str, list[int]] = {k: [] for k in PAYLOAD_RULES}
    unknown = {"ambiguous_action_name": 0, "action_status_unknown": 0, "action_type_unknown": 0,
               "time_zone_id_unresolved": 0, "click_time_unknown": 0, "click_window_unknown": 0}
    names_by_key: dict[str, set] = {k: set() for k in PAYLOAD_RULES}
    evaluated = {"click_time_rules": 0, "click_window_rule": 0}
    orders: dict[str, list[int]] = {}
    dupes: dict[tuple, list[int]] = {}
    rows = table.rows
    for idx, r in enumerate(rows):
        line = idx + 2  # spreadsheet row; header = row 1
        ids = [(c, _present(r.get(c))) for c in id_cols if _present(r.get(c)) is not None]
        click = ids[0] if len(ids) == 1 else None
        if click is None:
            failed["payload_click_id_count_invalid"].append(line)
        name = _present(r.get("conversion_name"))
        action = None
        if actions is not None:
            matches = actions.get(str(name)) if name is not None else None
            if not matches:
                failed["payload_conversion_action_not_found"].append(line)
                names_by_key["payload_conversion_action_not_found"].add("(blank)" if name is None else str(name))
            elif len(matches) > 1:
                unknown["ambiguous_action_name"] += 1
            else:
                action = matches[0]
                status = str(action.get("status") or "").strip().upper()
                if not status:
                    unknown["action_status_unknown"] += 1
                elif status != "ENABLED":
                    failed["payload_conversion_action_not_enabled"].append(line)
                    names_by_key["payload_conversion_action_not_enabled"].add(str(name))
                typ = V.norm_text(action.get("type"))
                if not typ:
                    unknown["action_type_unknown"] += 1
                elif typ not in UPLOAD_CLICK_TYPES:
                    failed["payload_conversion_action_not_import_type"].append(line)
                    names_by_key["payload_conversion_action_not_import_type"].add(str(name))
        conv, kind = _payload_time(r.get("conversion_time"))
        if kind == "timezone_id":
            unknown["time_zone_id_unresolved"] += 1
        elif conv is None:
            failed["payload_conversion_time_invalid"].append(line)
        if conv is not None and ctx.snapshot is not None:
            if conv >= datetime.combine(ctx.snapshot + timedelta(days=1), time(0), tzinfo=conv.tzinfo):
                failed["payload_conversion_time_in_future"].append(line)
        if conv is not None and click is not None and clicks is not None:
            clicked = clicks.get(click[1])
            if clicked is None:
                unknown["click_time_unknown"] += 1
            else:
                evaluated["click_time_rules"] += 1
                if conv < clicked:
                    failed["payload_conversion_precedes_click"].append(line)
                window = V.num(action.get("click_window_days")) if action is not None else None
                if window is None:
                    unknown["click_window_unknown"] += 1
                else:
                    evaluated["click_window_rule"] += 1
                    if conv - clicked > timedelta(days=window):
                        failed["payload_outside_click_window"].append(line)
        value, currency, order = (_present(r.get(c)) for c in ("conversion_value", "conversion_currency", "order_id"))
        if has_value and value is not None and (not _DECIMAL.match(value) or float(value) < 0):
            failed["payload_conversion_value_invalid"].append(line)
        if has_currency and currency is not None and not _ISO4217.match(currency):
            failed["payload_conversion_currency_invalid"].append(line)
        if has_order and order is not None:
            orders.setdefault(order, []).append(line)
        if click is not None and conv is not None and name is not None:
            dupes.setdefault((click[0], click[1], str(name), conv.astimezone(timezone.utc)), []).append(line)
    groups = {"payload_duplicate_order_id": [v for v in orders.values() if len(v) > 1],
              "payload_duplicate_click_conversion": [v for v in dupes.values() if len(v) > 1]}
    for key, gs in groups.items():
        failed[key] = sorted(line for g in gs for line in g)

    for reason, n in unknown.items():
        if n:
            chk.partial(f"{n} payload rows: {reason.replace('_', ' ')} (dependent rules not evaluated)")
    total = len(rows)
    chk.observe("Offline upload payload validated (no upload performed)", account_id=ctx.account_id, rows_total=total,
                click_id_columns=id_cols, value_column=has_value, currency_column=has_currency,
                order_id_column=has_order, click_evidence=clicks is not None, **evaluated, **unknown,
                failing_rows={k: len(v) for k, v in failed.items()},
                note="Row numbers are spreadsheet rows (header = row 1); click and order ids are never echoed.")
    for key, lines in failed.items():
        if not lines:
            continue
        what, rule, sources = PAYLOAD_RULES[key]
        evidence = {"failing_rows": len(lines), "rows_total": total, "sample_rows": lines[:SAMPLE_ROWS],
                    "row_numbering": "spreadsheet row, header = row 1", "rule": rule, "sources": sources}
        if key in groups:
            evidence["duplicate_groups"] = len(groups[key])
        if names_by_key[key]:
            evidence["conversion_names"] = sorted(names_by_key[key])
        calc = {"numerator": len(lines), "denominator": total, "window": "supplied payload rows",
                "parameter_source": "; ".join(sources)}
        if key == "payload_outside_click_window":
            calc.update(denominator=evaluated["click_window_rule"],
                        window="rows with a known click_time and click_window_days",
                        parameter_source="conversion_actions:click_window_days; " + "; ".join(sources))
        elif key == "payload_conversion_precedes_click":
            calc.update(denominator=evaluated["click_time_rules"], window="rows with a known click_time")
        chk.finding(key, "Warning", {"account_id": ctx.account_id, "payload": f"{PAYLOAD}.csv", "error_type": key},
                    f"{len(lines)} of {total} payload {what}",
                    evidence=evidence, calculation=calc,
                    recommendation="Fix these rows in the source sheet before any upload; this recipe validates "
                                   "only and never uploads, replays or schedules conversions.",
                    uncertainty="Format/time-window checks predict platform rejections; they do not prove the "
                                "click is matchable or that accepted rows will be attributed.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes require proposal.evidence_ref to supplied loss evidence."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") == "Critical" and not str((decision.get("proposal") or {}).get("evidence_ref") or "").strip():
        return ["Critical needs proposal.evidence_ref citing supplied material-loss evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
