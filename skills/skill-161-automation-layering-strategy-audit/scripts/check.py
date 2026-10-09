"""check.py — skill-161 deterministic automation/oversight coverage, run health, write conflicts and cap breaches.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-161-automation-layering-strategy-audit/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Inventory keeps the latest snapshot_at row per automation_id. Controls map to risks ONLY through
         automation IDs listed in automation_risks.required_control / acceptable_manual_alternative; unmapped
         text goes to ai_review, never counted as covered or missing.
         Coverage = approved (approval_ref) risk/entity pairs with an enabled, scope-covering control whose latest
         in-window run succeeded (alert not undelivered) / approved pairs; zero denominator → not_applicable.
         Run window = 30 days ending ctx.as_of. Failed/missed runs and undelivered alerts of REQUIRED controls →
         Warning. Gap-based overdue → Warning only when automation_runs is manifest-complete and a gap exceeds
         2 × cadence interval (overdue under rolling AND calendar readings); otherwise Info/partial.
         Write conflict Warning only from run evidence: same field + overlapping affected scope + overlapping run
         intervals with differing new values, or a same-day reversal; config-only overlap → ai_review.
         Cap breach: parsed '<amount> [CUR] /month|period' caps vs campaign_metrics cost for exactly that period;
         incomplete metrics give a lower bound (breach provable, compliance not). Daily budget overdelivery is
         never a cap breach. Critical only via review outcome 'material_breach_evidenced' + proposal.evidence_ref.
         Proposals are request-only (verify(): owner/cadence/guardrails/fallback, scope within risk scope,
         request_only true, no mandatory script).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import calendar
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

SKILL = "skill-161-automation-layering-strategy-audit"
VERSION = "1.0.0"

INV = "external/automation_inventory"
RUNS = "external/automation_runs"
RISKS = "external/automation_risks"
_OLDNEW = ("old/new_values", "old_new_values")

SUCCESS = {"success", "succeeded", "ok", "completed", "complete", "passed", "no_action", "no_change"}
FAILED = {"failed", "failure", "error", "errored", "timeout", "timed_out", "aborted", "crashed", "exception"}
MISSED = {"missed", "skipped", "not_run", "did_not_run"}
DELIVERED = {"delivered", "sent", "acknowledged"}
UNDELIVERED = {"failed", "bounced", "not_delivered", "undelivered", "rejected", "error"}
GENERATED = {"generated", "pending", "queued"}
NO_ALERT = {"not_applicable", "no_alert", "no_alerts"}
WILDCARD = {"*", "all", "account", "account_wide"}
_CAP = re.compile(r"^\s*([0-9][0-9.,]*)\s*([a-z]{3})?\s*(?:/|per)\s*([a-z_ ]+?)\s*$")
_CADENCE = {"hourly": 1, "daily": 24, "weekly": 168, "biweekly": 336, "fortnightly": 336, "monthly": 720}


def _tok(v) -> str | None:
    s = V.norm_text(v).replace(" ", "_").replace("-", "_")
    return None if s in V.MISSING_TOKENS else s


def _col(table, names: tuple[str, ...]) -> str:
    for n in names:
        if table is not None and n in table.columns:
            return n
    return names[0]


def _scope(v) -> set[str]:
    """Normalized scope tokens: wildcard stays '*'; 'campaign:123' → '123'."""
    out = set()
    for x in V.split_list(v, (";", "|", ",")):
        t = x.strip().lower()
        out.add("*" if t in WILDCARD else t.split(":")[-1])
    return out


def _covers(auto_scope: set[str], risk_scope: set[str], account_id) -> bool:
    if "*" in auto_scope or (account_id and str(account_id).lower() in auto_scope):
        return True
    return bool(risk_scope) and "*" not in risk_scope and risk_scope <= auto_scope


def _overlap(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and ("*" in a or "*" in b or bool(a & b))


def _dt(v) -> datetime | None:
    """ISO timestamp → naive datetime (aware values converted to UTC); date-only → midnight."""
    s = str(v or "").strip()
    if not s or s.lower() in V.MISSING_TOKENS:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        day = V.parse_date(s)
        return datetime.combine(day, time()) if day else None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _interval_hours(v) -> float | None:
    t = _tok(v)
    if t is None:
        return None
    if t in _CADENCE:
        return float(_CADENCE[t])
    m = re.fullmatch(r"(?:every_)?(\d+(?:\.\d+)?)_?(h|hours?|d|days?|w|weeks?)", t)
    if not m:
        return None
    return float(m.group(1)) * {"h": 1, "d": 24, "w": 168}[m.group(2)[0]]


def _fields(v) -> tuple[set[str], set[str]]:
    """read_or_write_fields → (write fields, fields with undeclared access mode)."""
    writes, unknown = set(), set()
    for item in V.split_list(v, (";", "|", ",")):
        mode, _, field = item.partition(":")
        mode = mode.strip().lower()
        if field and mode in ("write", "w", "rw", "read_write"):
            writes.add(field.strip().lower())
        elif field and mode in ("read", "r"):
            continue
        else:
            unknown.add(item.strip().lower())
    return writes, unknown


def _changes(run, oldnew_col) -> dict[str, tuple[str, str]]:
    """Parse 'field:old->new; field2:old->new' (or bare 'old->new' for one changed field)."""
    fields = [f.lower() for f in V.split_list(run.get("changed_fields"), (";", "|", ","))]
    out = {}
    for part in V.split_list(run.get(oldnew_col), (";", "|")):
        field, sep, rest = part.partition(":")
        if not sep or "->" in field:
            field, rest = (fields[0] if len(fields) == 1 else ""), part
        old, arrow, new = rest.partition("->")
        if field and arrow:
            out[field.strip().lower()] = (V.norm_text(old), V.norm_text(new))
    return out


class State:
    """Shared, deduplicated inventory/run/risk evidence for all subchecks."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.account_id = ctx.account_id
        self.inv: dict[str, dict] = {}
        for r in sorted(ctx.rows(INV), key=lambda r: (str(r.get("automation_id")), str(r.get("snapshot_at") or ""))):
            if r.get("automation_id"):
                self.inv[str(r["automation_id"])] = r
        self.end = ctx.as_of
        self.start = self.end - timedelta(days=29) if self.end else None
        self.runs: dict[str, list[dict]] = {}
        self.orphans = 0
        runs_t = ctx.table(RUNS)
        self.runs_complete = bool(runs_t is not None and runs_t.complete is True and not runs_t.truncated)
        for r in ctx.rows(RUNS):
            at = _dt(r.get("started_at")) or _dt(r.get("scheduled_at"))
            if at is None or self.start is None or not (self.start <= at.date() <= self.end):
                continue
            aid = str(r.get("automation_id") or "")
            if aid not in self.inv:
                self.orphans += 1
            self.runs.setdefault(aid, []).append({**r, "_at": at})
        for lst in self.runs.values():
            lst.sort(key=lambda r: (r["_at"], str(r.get("run_id"))))
        self.risks = [r for r in ctx.rows(RISKS)]
        self.risks_loaded = ctx.table(RISKS) is not None
        # required automation id → strictest required cadence (hours) among risks naming it
        self.required: dict[str, float | None] = {}
        for r in self.risks:
            for aid in self.controls(r):
                h = _interval_hours(r.get("required_cadence"))
                prev = self.required.get(aid)
                self.required[aid] = h if prev is None else (prev if h is None else min(prev, h))

    def controls(self, risk) -> list[str]:
        ids = set(V.split_list(risk.get("required_control"), (";", "|", ","))) | \
            set(V.split_list(risk.get("acceptable_manual_alternative"), (";", "|", ",")))
        return sorted(i for i in ids if i in self.inv)

    def health(self, aid: str) -> str:
        """functioning | failed | unknown for one automation in the window."""
        row = self.inv.get(aid) or {}
        enabled = V.boolean(row.get("enabled"))
        if enabled is False:
            return "failed"
        runs = [r for r in self.runs.get(aid, []) if _tok(r.get("result")) not in MISSED]
        if enabled is None or not runs:
            return "unknown"
        last = runs[-1]
        res, alert = _tok(last.get("result")), _tok(last.get("alert_delivery_status"))
        if res in FAILED or alert in UNDELIVERED:
            return "failed"
        return "functioning" if res in SUCCESS else "unknown"

    def pairs(self) -> list[dict]:
        out = []
        for r in sorted(self.risks, key=lambda r: (str(r.get("risk_id")), str(r.get("entity_scope")))):
            scope = _scope(r.get("entity_scope"))
            ctrls = self.controls(r)
            covering = [a for a in ctrls if _covers(_scope(self.inv[a].get("entity_scope_ids")), scope, self.account_id)]
            states = {a: self.health(a) for a in covering}
            if not ctrls:
                state = "unmapped"
            elif "functioning" in states.values():
                state = "covered"
            elif "failed" in states.values():
                state = "failed"
            else:
                state = "unknown"
            out.append({"risk": r, "scope": scope, "controls": ctrls, "covering": covering, "health": states,
                        "state": state, "approved": bool(str(r.get("approval_ref") or "").strip())})
        return out


# ---------------------------------------------------------------------------------------------- checks
def _inventory(ctx, st: State) -> None:
    c = ctx.check("oversight_inventory", "Automated and manual oversight inventory (step 1)",
                  {INV: ["automation_id", "type", "enabled", "owner", "entity_scope_ids", "read_or_write_fields",
                         "cadence"]})
    if not c.runnable:
        return
    by_type: dict[str, int] = {}
    for aid, r in sorted(st.inv.items()):
        by_type[_tok(r.get("type")) or "unknown"] = by_type.get(_tok(r.get("type")) or "unknown", 0) + 1
        c.observe(f"Automation {aid}", automation_id=aid, type=r.get("type"), enabled=V.boolean(r.get("enabled")),
                  owner=r.get("owner"), entity_scope_ids=r.get("entity_scope_ids"), cadence=r.get("cadence"),
                  approval_ref=r.get("approval_ref"), fallback=r.get("fallback"), snapshot_at=r.get("snapshot_at"))
    c.observe("Oversight inventory totals (latest snapshot per automation)", automations=len(st.inv), by_type=by_type,
              enabled_unknown=sum(1 for r in st.inv.values() if V.boolean(r.get("enabled")) is None))


def _coverage(ctx, st: State) -> list[dict] | None:
    c = ctx.check("risk_coverage", "Risk/entity coverage by functioning accepted controls (step 2)",
                  {RISKS: ["risk_id", "entity_scope", "required_control", "acceptable_manual_alternative",
                           "required_cadence", "responsible_owner", "approval_ref"],
                   INV: ["automation_id", "enabled", "entity_scope_ids"],
                   RUNS: ["automation_id", "started_at", "result", "alert_delivery_status"]})
    if not c.runnable:
        return None
    if st.end is None:
        c.partial("as_of unknown: run window undefined")
        return None
    pairs = st.pairs()
    eligible = [p for p in pairs if p["approved"]]
    counts = {s: sum(1 for p in eligible if p["state"] == s) for s in ("covered", "failed", "unknown", "unmapped")}
    for p in eligible:
        r = p["risk"]
        c.observe(f"Risk {r.get('risk_id')} / {r.get('entity_scope')}: {p['state']}", risk_id=r.get("risk_id"),
                  entity_scope=r.get("entity_scope"), controls=p["controls"], covering_controls=p["covering"],
                  control_health=p["health"], responsible_owner=r.get("responsible_owner"))
        if p["state"] == "unmapped":
            c.review("control_mapping_unresolved", {"risk_id": r.get("risk_id"), "entity_scope": r.get("entity_scope")},
                     "No inventoried automation ID is named for this risk. Does an inventoried native tool, rule or "
                     "accountable manual review demonstrably cover it?",
                     evidence={"required_control": r.get("required_control"),
                               "acceptable_manual_alternative": r.get("acceptable_manual_alternative"),
                               "required_cadence": r.get("required_cadence"),
                               "inventory_ids": sorted(st.inv)},
                     outcomes={"covered_by_existing_control": {"severity": None, "recommendation":
                               "Record the control ID in the risk matrix."},
                               "no_adequate_control": {"severity": "Info", "recommendation":
                               "Propose owner-approved oversight (script optional)."},
                               "uncertain": {"severity": "Info", "recommendation": "Ask the responsible owner."}},
                     guidance="A missing script is not missing capability; judge only from supplied inventory/manual records.")
    if not eligible:
        c.not_applicable("no approved risk/entity pairs: coverage denominator is zero")
        return pairs
    c.observe("Coverage of approved risk/entity pairs", numerator=counts["covered"], denominator=len(eligible),
              coverage=V.ratio(counts["covered"], len(eligible)), failed=counts["failed"], unknown=counts["unknown"],
              unmapped=counts["unmapped"], excluded_unapproved=len(pairs) - len(eligible),
              window=[st.start, st.end])
    return pairs


def _run_health(ctx, st: State) -> None:
    c = ctx.check("run_health", "Run logs joined to schedule: failures, overdue runs, alert delivery (step 3)",
                  {RUNS: ["automation_id", "run_id", "started_at", "scheduled_at", "result", "alert_delivery_status"],
                   INV: ["automation_id", "enabled", "cadence"]})
    if not c.runnable:
        return
    if st.end is None:
        c.partial("as_of unknown: 30-day run window undefined")
        return
    if not st.risks_loaded:
        c.partial("risk matrix missing: required status unknown, failures reported as observations only",
                  [f"{RISKS} (file)"])
    if st.orphans:
        c.observe("Runs without an inventoried automation", runs=st.orphans)
    w_end = datetime.combine(st.end + timedelta(days=1), time())
    for aid, row in sorted(st.inv.items()):
        runs = st.runs.get(aid, [])
        required = aid in st.required
        entity = {"automation_id": aid}
        failed = [r for r in runs if _tok(r.get("result")) in FAILED]
        missed = [r for r in runs if _tok(r.get("result")) in MISSED]
        alerts = {k: 0 for k in ("delivered", "undelivered", "generated_only", "unknown", "none")}
        for r in runs:
            a = _tok(r.get("alert_delivery_status"))
            alerts["delivered" if a in DELIVERED else "undelivered" if a in UNDELIVERED else
                   "generated_only" if a in GENERATED else "none" if a in NO_ALERT else "unknown"] += 1
        c.observe(f"Automation {aid}: runs in window", automation_id=aid, required=required if st.risks_loaded else None,
                  runs=len(runs), failed=len(failed), missed=len(missed), alerts=alerts, window=[st.start, st.end])
        base_ev = {"window": [st.start, st.end], "runs": len(runs), "owner": row.get("owner"),
                   "evidence_refs": sorted({str(r.get("evidence_ref")) for r in failed + missed if r.get("evidence_ref")})}
        if not required:
            continue
        if failed:
            c.finding("required_control_failed_run", "Warning", entity,
                      f"Required control {aid} had {len(failed)} failed run(s) of {len(runs)} in the window",
                      evidence={**base_ev, "failed_run_ids": [r.get("run_id") for r in failed],
                                "latest_result": runs[-1].get("result"),
                                "errors": sorted({str(r.get("error_summary")) for r in failed if r.get("error_summary")})},
                      recommendation="Ask the control owner to diagnose the failures and confirm the fallback covered the gap.",
                      uncertainty="A later successful run may have recovered; impact of the failed runs is not measured.")
        if alerts["undelivered"]:
            c.finding("required_alert_not_delivered", "Warning", entity,
                      f"Required control {aid}: {alerts['undelivered']} generated alert(s) were not delivered",
                      evidence={**base_ev, "alerts": alerts},
                      recommendation="Ask the owner to repair the notification route; generation is not delivery.",
                      uncertainty="Delivery status as logged by the client tool.")
        elif alerts["generated_only"] or alerts["unknown"]:
            c.finding("alert_delivery_unknown", "Info", entity,
                      f"Required control {aid}: alert delivery not evidenced for "
                      f"{alerts['generated_only'] + alerts['unknown']} run(s)", evidence={**base_ev, "alerts": alerts},
                      recommendation="Request delivery evidence for generated alerts.",
                      uncertainty="Generated/pending alerts may have been delivered without a log entry.")
        interval = st.required.get(aid) or _interval_hours(row.get("cadence"))
        gaps = []
        if missed:
            gaps.append({"missed_run_ids": [r.get("run_id") for r in missed]})
        if V.boolean(row.get("enabled")) is True and interval is not None:
            limit = timedelta(hours=2 * interval)
            times = [r["_at"] for r in runs if _tok(r.get("result")) not in MISSED]
            if not times and limit < w_end - datetime.combine(st.start, time()):
                gaps.append({"no_run_in_window": True})
            for a, b in zip(times, times[1:] + [w_end]):
                if b - a > limit:
                    gaps.append({"gap_from": a, "gap_to": b, "gap_hours": (b - a).total_seconds() / 3600})
        elif interval is None:
            c.partial(f"automation {aid}: cadence not parseable; overdue check skipped",
                      [f"{RISKS}:required_cadence", f"{INV}:cadence"])
        gap_only = [g for g in gaps if "missed_run_ids" not in g]
        if missed or (gap_only and st.runs_complete):
            c.finding("required_control_overdue", "Warning", entity,
                      f"Required control {aid} did not run at its required cadence ({interval}h) in the window",
                      evidence={**base_ev, "gaps": gaps, "cadence_hours": interval, "rule": "gap > 2 x cadence or logged missed run"},
                      recommendation="Ask the owner to restore the schedule or confirm the fallback review ran.",
                      uncertainty="Automation start date unknown; a control created mid-window can show a leading gap.")
        elif gap_only:
            c.finding("run_evidence_unknown", "Info", entity,
                      f"Required control {aid}: run log not manifest-complete; possible gap is unverified",
                      evidence={**base_ev, "gaps": gaps, "cadence_hours": interval},
                      recommendation="Request a complete 30-day run log for this control.",
                      uncertainty="Missing log rows are unknown runs, not observed failures.")


def _write_conflicts(ctx, st: State) -> None:
    runs_t = ctx.table(RUNS)
    oldnew = _col(runs_t, _OLDNEW)
    c = ctx.check("write_conflicts", "Overlapping incompatible writes (step 4)",
                  {INV: ["automation_id", "enabled", "entity_scope_ids", "read_or_write_fields"]})
    if not c.runnable:
        return
    run_cols = ["automation_id", "started_at", "ended_at", "affected_scope_ids", "changed_fields", oldnew]
    have_runs = runs_t is not None and not runs_t.missing(run_cols)
    if not have_runs:
        c.partial("run change evidence unavailable: overlaps go to review only",
                  [f"{RUNS}:{x}" for x in run_cols] if runs_t is None else [f"{RUNS}:{x}" for x in runs_t.missing(run_cols)])
    writers = {}
    for aid, r in sorted(st.inv.items()):
        w, unk = _fields(r.get("read_or_write_fields"))
        if unk:
            c.partial(f"automation {aid}: fields without read/write mode {sorted(unk)} not compared")
        en = V.boolean(r.get("enabled"))
        if en is None:
            c.partial(f"automation {aid}: enabled unknown; not compared")
        if w and en is True:
            writers[aid] = (w, _scope(r.get("entity_scope_ids")))
    ids = sorted(writers)
    pairs = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            fields = writers[a][0] & writers[b][0]
            if not fields or not _overlap(writers[a][1], writers[b][1]):
                continue
            pairs += 1
            entity = {"automation_a": a, "automation_b": b, "fields": sorted(fields)}
            proof = _run_conflicts(st, a, b, fields, oldnew) if have_runs else []
            ev = {"shared_write_fields": sorted(fields), "scope_a": sorted(writers[a][1]), "scope_b": sorted(writers[b][1]),
                  "cadence_a": st.inv[a].get("cadence"), "cadence_b": st.inv[b].get("cadence"),
                  "conditions_a": st.inv[a].get("conditions"), "conditions_b": st.inv[b].get("conditions"),
                  "window": [st.start, st.end]}
            if proof:
                c.finding("incompatible_overlapping_writes", "Warning", entity,
                          f"{a} and {b} wrote {sorted(fields)} on the same entities in overlapping runs with "
                          "disagreeing values", evidence={**ev, "run_evidence": proof},
                          recommendation="Ask both owners to agree precedence/sequencing for the shared field; request-only.",
                          uncertainty="Run logs show the collision; spend or safety impact is not measured.")
                c.review("incompatible_overlapping_writes", entity,
                         "Does supplied evidence show this write conflict caused a MATERIAL spending or safety breach?",
                         evidence={**ev, "run_evidence": proof},
                         outcomes={"material_breach_evidenced": {"severity": "Critical", "recommendation":
                                   "Escalate to both owners; cite proposal.evidence_ref."},
                                   "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                         guidance="Critical needs proposal.evidence_ref pointing at supplied breach evidence.")
            else:
                c.review("potential_write_overlap", entity,
                         "Both automations write the same field on overlapping scope. Do their trigger times overlap "
                         "and their actions disagree or undo each other?",
                         evidence=ev,
                         outcomes={"incompatible_overlapping_writes": {"severity": "Warning", "recommendation":
                                   "Agree precedence/sequencing with both owners."},
                                   "compatible_or_sequenced": {"severity": None, "recommendation": "No conflict."},
                                   "uncertain": {"severity": "Info", "recommendation": "Request trigger schedules/run logs."}},
                         guidance="Similar names or functions alone are not harmful duplication.")
    c.observe("Write-field overlap screening", enabled_writers=len(writers), overlapping_pairs=pairs)


def _run_conflicts(st: State, a: str, b: str, fields: set[str], oldnew: str) -> list[dict]:
    out = []
    for ra in st.runs.get(a, []):
        ca = _changes(ra, oldnew)
        for rb in st.runs.get(b, []):
            if not _overlap(_scope(ra.get("affected_scope_ids")), _scope(rb.get("affected_scope_ids"))):
                continue
            cb = _changes(rb, oldnew)
            a0, a1 = ra["_at"], _dt(ra.get("ended_at")) or ra["_at"]
            b0, b1 = rb["_at"], _dt(rb.get("ended_at")) or rb["_at"]
            for f in sorted(fields & set(ca) & set(cb)):
                (oa, na), (ob, nb) = ca[f], cb[f]
                concurrent = a0 <= b1 and b0 <= a1 and na != nb
                reversal = a0.date() == b0.date() and na == ob and nb == oa and na != nb
                if concurrent or reversal:
                    out.append({"field": f, "run_a": ra.get("run_id"), "run_b": rb.get("run_id"),
                                "a": [oa, na], "b": [ob, nb], "started_a": a0, "started_b": b0,
                                "kind": "concurrent" if concurrent else "same_day_reversal"})
    return out


def _parse_cap(v) -> tuple[float, str | None, str] | None:
    m = _CAP.match(V.norm_text(v))
    if not m:
        return None
    amount = V.num(m.group(1))
    return (amount, (m.group(2) or "").upper() or None, m.group(3).strip().replace(" ", "_")) if amount else None


def _cap_breach(ctx, st: State) -> None:
    c = ctx.check("cap_breach", "Approved monthly/client cap breach vs normal daily overdelivery (step 5)",
                  {RISKS: ["risk_id", "entity_scope", "approved_spend_cap_or_service_limit", "approval_ref"],
                   "campaign_metrics": ["campaign_id", "cost"]})
    if not c.runnable:
        return
    ps, pe = ctx.period_start, ctx.period_end
    whole_month = bool(ps and pe and ps.day == 1 and ps.month == pe.month and ps.year == pe.year
                       and pe.day == calendar.monthrange(pe.year, pe.month)[1])
    metrics = ctx.table("campaign_metrics")
    complete = metrics.complete is True and not metrics.truncated
    spend: dict[str, float | None] = {}
    seen = set()
    duplicate = False
    for r in metrics.rows:
        d = V.parse_date(r.get("date")) if "date" in metrics.columns else None
        if d is not None and ps and pe and not (ps <= d <= pe):
            continue
        cid = str(r.get("campaign_id") or "")
        if (cid, d) in seen:
            duplicate = True
        seen.add((cid, d))
        cost = ctx.money(r.get("cost"))
        spend[cid] = None if cost is None or spend.get(cid, 0.0) is None else spend.get(cid, 0.0) + cost
    if duplicate:
        c.partial("campaign_metrics has repeated campaign/date rows (segments): spend not summed")
        return
    caps = 0
    for r in sorted(st.risks, key=lambda r: (str(r.get("risk_id")), str(r.get("entity_scope")))):
        raw = r.get("approved_spend_cap_or_service_limit")
        if raw is None or not str(r.get("approval_ref") or "").strip():
            continue
        cap = _parse_cap(raw)
        rid = r.get("risk_id")
        if cap is None:
            c.observe(f"Risk {rid}: limit '{raw}' is not a parseable spend cap; not assessed", risk_id=rid)
            continue
        amount, cur, period = cap
        if cur and ctx.currency and cur != ctx.currency:
            c.partial(f"risk {rid}: cap currency {cur} differs from account {ctx.currency}")
            continue
        if period in ("day", "daily"):
            c.observe(f"Risk {rid}: daily cap; daily overdelivery is normal and not assessed from aggregate data",
                      risk_id=rid, cap=amount)
            continue
        if not ((period in ("month", "monthly") and whole_month) or period in ("period", "report_period")):
            c.partial(f"risk {rid}: cap period '{period}' does not equal the report period {ps}..{pe}")
            continue
        scope = _scope(r.get("entity_scope"))
        ids = sorted(spend) if "*" in scope or (ctx.account_id and str(ctx.account_id).lower() in scope) else sorted(scope)
        known = [spend[i] if i in spend else (0.0 if complete else None) for i in ids]
        lower_bound = not complete or any(x is None for x in known)
        total = sum(x for x in known if x is not None)
        if not ids:
            c.partial(f"risk {rid}: entity_scope names no campaign", [f"{RISKS}:entity_scope"])
            continue
        if lower_bound and total <= amount:
            c.partial(f"risk {rid}: spend unknown for some scoped campaigns; cap compliance undecidable",
                      ["campaign_metrics:cost"])
            continue
        caps += 1
        ev = {"cap": amount, "cap_period": period, "cap_currency": cur or ctx.currency, "spend": total,
              "campaign_ids": ids, "period": [ps, pe], "spend_is_lower_bound": lower_bound,
              "approval_ref": r.get("approval_ref"), "responsible_owner": r.get("responsible_owner")}
        entity = {"risk_id": rid, "entity_scope": r.get("entity_scope")}
        if total > amount:
            c.finding("approved_cap_breach", "Warning", entity,
                      f"Spend {total:.2f} {ctx.currency} exceeded approved {period} cap {amount:.2f} for risk {rid}",
                      evidence=ev, calculation={"spend": "sum campaign_metrics.cost over scoped campaigns",
                                                "utilization": V.ratio(total, amount)},
                      recommendation="Ask the responsible owner to review the cap control and approve corrective guardrails.",
                      uncertainty="Exposure above cap is not recoverable savings; daily overdelivery alone is not a breach.")
            c.review("approved_cap_breach", entity,
                     "Does supplied evidence show a control conflict/failure CAUSED this material cap breach?",
                     evidence=ev,
                     outcomes={"material_breach_evidenced": {"severity": "Critical", "recommendation":
                               "Escalate to the cap owner; cite proposal.evidence_ref."},
                               "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                     guidance="Critical needs proposal.evidence_ref linking a control failure to the breach.")
        else:
            c.observe(f"Risk {rid}: spend within approved {period} cap", **entity, **ev,
                      utilization=V.ratio(total, amount))
    c.observe("Spend caps assessed", caps=caps, report_period_is_calendar_month=whole_month)


def _proposals(ctx, pairs: list[dict] | None) -> None:
    c = ctx.check("oversight_proposals", "Risk-prioritized request-only oversight proposals (step 6)",
                  {RISKS: ["risk_id", "entity_scope", "required_control", "required_cadence", "responsible_owner"]})
    if not c.runnable:
        return
    if pairs is None:
        c.partial("coverage states unavailable: proposals not drafted", [f"{INV} (file)", f"{RUNS} (file)"])
        return
    for p in pairs:
        if not p["approved"] or p["state"] == "covered":
            continue
        r = p["risk"]
        c.review("oversight_revision", {"risk_id": r.get("risk_id"), "entity_scope": r.get("entity_scope")},
                 f"Risk {r.get('risk_id')} coverage is {p['state']}. Which request-only oversight revision fits?",
                 evidence={"state": p["state"], "controls": p["controls"], "control_health": p["health"],
                           "required_cadence": r.get("required_cadence"), "responsible_owner": r.get("responsible_owner"),
                           "risk_scope": sorted(p["scope"])},
                 outcomes={"propose_revision": {"severity": "Info", "recommendation":
                           "Request-only proposal with owner, cadence, guardrails and fallback."},
                           "no_change_needed": {"severity": None, "recommendation": "Document why coverage suffices."},
                           "uncertain": {"severity": "Info", "recommendation": "Ask the responsible owner."}},
                 guidance="proposal {owner, cadence, guardrails, fallback, scope_ids ⊆ risk_scope, request_only: true}; "
                          "scripts optional, no installation/execution/notifications.")


def run(ctx) -> None:
    """Run automation inventory, risk-control coverage, run health, write-conflict and cap-breach checks.

    Rules:   Controls map to risks only via listed automation IDs; unmapped text → ai_review, never covered or missing.
             Failed/missed runs and undelivered alerts of REQUIRED controls → Warning; gap-overdue Warning needs a
             manifest-complete run table, else Info/partial. Write conflicts Warning only from run evidence (config-only
             → review). Critical only via 'material_breach_evidenced' + evidence_ref; proposals are request-only.
    """
    st = State(ctx)
    _inventory(ctx, st)
    pairs = _coverage(ctx, st)
    _run_health(ctx, st)
    _write_conflicts(ctx, st)
    _cap_breach(ctx, st)
    _proposals(ctx, pairs)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref; oversight proposals must be complete, in-scope and request-only."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_breach_evidenced":
        return [] if str(proposal.get("evidence_ref") or "").strip() else \
            ["material breach needs proposal.evidence_ref pointing at supplied evidence"]
    if outcome != "propose_revision":
        return []
    problems = [f"proposal.{f} required" for f in ("owner", "cadence", "guardrails", "fallback")
                if not str(proposal.get(f) or "").strip()]
    if proposal.get("request_only") is not True:
        problems.append("proposal.request_only must be true")
    if V.boolean(proposal.get("mandatory_script")) is True:
        problems.append("scripts are optional; mandatory_script not allowed")
    risk_scope = set(item.evidence.get("risk_scope") or [])
    ids = proposal.get("scope_ids")
    ids = _scope(ids) if isinstance(ids, str) else {str(x).lower().split(":")[-1] for x in ids or []}
    if not ids or ("*" not in risk_scope and not ids <= risk_scope):
        problems.append(f"proposal.scope_ids must be a non-empty subset of {sorted(risk_scope)}")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
