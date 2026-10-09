"""check.py — skill-156 deterministic first-party data permission gate, pipeline and capture readiness.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-156-first-party-data-collection-activation-strategy/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Never read customer identifiers: external tables with identifier columns (_IDENTIFIER_COLS) are
         reported in errors and those columns are never used.
         Readiness per permission row = blocked (any explicit denial token) > unknown (any empty/unrecognized
         gate field, future reviewed_at, no evidence_reference) > permitted. Activation/use-plan rows carry no
         market, so they join on (source_id, intended_use) and combine ALL matching market rows the same way.
         blocked/unknown readiness → Info 'activation_blocked_pending_owner_review' only; never an upload proposal.
         Pipeline health (Warning) only for permitted + eligible pipelines; attempts are not refreshes; SLA
         values need an explicit unit (h/d) or an approved_refresh_sla_days column; date granularity is
         resolved conservatively (stale only when age-1 >= SLA days).
         Active use contrary to restrictions → deterministic Warning; Critical only via review outcome
         'material_unsafe_use_evidenced' with proposal.evidence_ref (verify()).
         Capture = valid_unique_records / eligible_unique_visitors_or_opportunities only with a declared
         denominator_definition and nonzero denominator; permission rate kept separate; comparisons need
         ctx.mature True and min_clicks eligible opportunities on BOTH sides and stay Info.
         Match-rate diagnosis of individual lists belongs to skill-061; here only observed.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
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

SKILL = "skill-156-first-party-data-collection-activation-strategy"
VERSION = "1.0.0"

PERM = "external/activation_permissions"
SRC = "external/first_party_sources"
CAP = "external/first_party_capture"
ACT = "external/first_party_activation"
PLAN = "external/first_party_use_plan"

# Recipe headers containing '/' are accepted literally or with '_' (documented alternative names).
_ALT = {
    "withdrawal/deletion_process_status": ("withdrawal/deletion_process_status", "withdrawal_deletion_process_status"),
    "withdrawal/deletion_sync_status": ("withdrawal/deletion_sync_status", "withdrawal_deletion_sync_status"),
    "pipeline/list/action_id": ("pipeline/list/action_id", "pipeline_list_action_id", "pipeline_id"),
    "approved_refresh_SLA": ("approved_refresh_SLA", "approved_refresh_sla", "approved_refresh_sla_days"),
    "earliest/latest_collection_at": ("earliest_collection_at", "earliest/latest_collection_at"),
    "accepted_count": ("accepted_count",),
    "rejected_count": ("rejected_count",),
}
_IDENTIFIER_COLS = {"email", "email_address", "emails", "hashed_email", "sha256_email", "phone", "phone_number",
                    "hashed_phone", "first_name", "last_name", "street_address", "postal_address", "mobile_id",
                    "device_id", "crm_customer_id", "customer_email"}

PERMIT = {"permitted", "granted", "approved", "allowed"}
DENY = {"denied", "blocked", "refused", "withdrawn", "not_permitted", "rejected", "prohibited", "revoked", "expired"}
CONSENT_OK = {"covered", "complete", "sufficient", "verified", "not_required"}
CONSENT_BAD = {"not_covered", "uncovered", "insufficient", "denied", "none"}
ELIGIBLE = {"eligible", "yes", "true", "pass", "passed"}
INELIGIBLE = {"ineligible", "not_eligible", "no", "false", "fail", "failed"}
PROCESS_OK = {"operational", "implemented", "active", "in_place", "verified", "working", "pass", "passed", "ok"}
PROCESS_BAD = {"failed", "failing", "broken", "not_implemented", "absent", "missing", "error"}
REVIEW_OK = {"passed", "cleared", "approved", "not_applicable", "not_required"}
REVIEW_BAD = {"failed", "prohibited", "not_permitted", "rejected"}
CONN_ACTIVE = {"active", "connected", "enabled", "running", "ok", "healthy"}
CONN_FAILED = {"failed", "error", "disconnected", "broken", "expired", "revoked", "auth_error"}


def _tok(v) -> str | None:
    s = V.norm_text(v).replace(" ", "_").replace("-", "_")
    return None if s in ("", "none_supplied") or s in V.MISSING_TOKENS else s


def _col(table, canonical: str) -> str:
    """Column actually present for a recipe field; falls back to the canonical recipe name."""
    for name in _ALT.get(canonical, (canonical,)):
        if table is not None and name in table.columns:
            return name
    return _ALT.get(canonical, (canonical,))[0]


def _ref_date(ctx):
    return ctx.snapshot or ctx.as_of


def _ids(v) -> set[str]:
    return {x.strip() for x in V.split_list(v, (";", "|", ",")) if x.strip()}


def _sla_days(raw, days_column: bool) -> float | None:
    """'24h' → 1.0, '7d' → 7.0; a bare number only in the *_days column; else None (unit unknown)."""
    s = V.norm_text(raw).replace(" ", "")
    if not s:
        return None
    if days_column:
        return V.num(s)
    for suffix, factor in (("hours", 1 / 24), ("hour", 1 / 24), ("h", 1 / 24), ("days", 1.0), ("day", 1.0), ("d", 1.0)):
        if s.endswith(suffix):
            n = V.num(s[: -len(suffix)])
            return None if n is None else n * factor
    if s.startswith("p") and s.endswith("d"):
        return V.num(s[1:-1])
    return None


# ---------------------------------------------------------------------------------------------- readiness
def _grade(row, col, ok, bad, blockers, unknown) -> None:
    v = _tok(row.get(col))
    if v is None:
        unknown.append(f"{PERM}:{col}")
    elif v in bad:
        blockers.append(f"{col}={v}")
    elif v not in ok:
        unknown.append(f"{PERM}:{col} (value {v!r} not a recognized status)")


def _readiness(ctx, row, withdrawal_col) -> dict:
    blockers: list[str] = []
    unknown: list[str] = []
    _grade(row, "permission_status", PERMIT, DENY, blockers, unknown)
    _grade(row, "consent_coverage_status", CONSENT_OK, CONSENT_BAD, blockers, unknown)
    _grade(row, "policy_eligibility", ELIGIBLE, INELIGIBLE, blockers, unknown)
    _grade(row, withdrawal_col, PROCESS_OK, PROCESS_BAD, blockers, unknown)
    _grade(row, "restricted_data_review", REVIEW_OK, REVIEW_BAD, blockers, unknown)
    retention = V.num(row.get("retention_limit_days"))
    if retention is None or retention <= 0:
        unknown.append(f"{PERM}:retention_limit_days")
    dests = sorted(_ids(row.get("permitted_destinations")))
    if not dests:
        unknown.append(f"{PERM}:permitted_destinations")
    if not str(row.get("evidence_reference") or "").strip():
        unknown.append(f"{PERM}:evidence_reference")
    reviewed = V.parse_date(row.get("reviewed_at"))
    ref = _ref_date(ctx)
    if reviewed is None:
        unknown.append(f"{PERM}:reviewed_at")
    elif ref is not None and reviewed > ref:
        unknown.append(f"{PERM}:reviewed_at ({reviewed} after evidence date {ref})")
    status = "blocked" if blockers else "unknown" if unknown else "permitted"
    return {"status": status, "blockers": blockers, "unknown": unknown, "destinations": dests,
            "retention_limit_days": retention, "reviewed_at": reviewed,
            "evidence_reference": row.get("evidence_reference"), "reviewer_role": row.get("reviewer_role")}


def _combine(states: list[dict]) -> str:
    if not states:
        return "unknown"
    s = {x["status"] for x in states}
    return "blocked" if "blocked" in s else "unknown" if "unknown" in s else "permitted"


class Gate:
    """Permission evidence indexed by (source_id, intended_use). Rules: None table → every use unknown."""

    def __init__(self, ctx, runnable: bool):
        self.ctx = ctx
        self.loaded = runnable
        t = ctx.table(PERM)
        self.complete = bool(t is not None and t.complete is True and not t.truncated)
        self.withdrawal_col = _col(t, "withdrawal/deletion_process_status")
        self.rows: dict[tuple[str, str], list[dict]] = {}
        if runnable:
            for r in ctx.rows(PERM):
                key = (str(r.get("source_id") or ""), _tok(r.get("intended_use")) or "")
                st = _readiness(ctx, r, self.withdrawal_col)
                st.update({"market": r.get("market"), "list_id": r.get("list_id"), "row": r})
                self.rows.setdefault(key, []).append(st)

    def lookup(self, source_id, intended_use, list_id=None) -> tuple[str, list[dict]]:
        rows = self.rows.get((str(source_id or ""), _tok(intended_use) or ""), [])
        if list_id is not None and any(r["list_id"] for r in rows):
            rows = [r for r in rows if not r["list_id"] or str(r["list_id"]) == str(list_id)]
        return _combine(rows), rows

    @staticmethod
    def destinations(rows: list[dict]) -> set[str] | None:
        """Intersection of permitted destinations over market rows; None when any row lacks them."""
        sets = [set(r["destinations"]) for r in rows]
        if not sets or any(not s for s in sets):
            return None
        out = sets[0]
        for s in sets[1:]:
            out &= s
        return out


def _dest_ok(dest, allowed: set[str] | None) -> bool | None:
    if allowed is None or dest is None:
        return None
    norm = lambda x: str(x).replace("-", "").strip().lower()
    return norm(dest) in {norm(a) for a in allowed}


# ---------------------------------------------------------------------------------------------- checks
def _identifier_guard(ctx) -> None:
    for key in (PERM, SRC, CAP, ACT, PLAN):
        t = ctx.table(key)
        bad = sorted(c for c in (t.columns if t else []) if c.strip().lower() in _IDENTIFIER_COLS)
        if bad:
            ctx.result.errors.append(f"{t.filename} contains customer-identifier columns {bad}: not read; "
                                     "supply aggregate/redacted evidence only")


def _source_inventory(ctx) -> None:
    c = ctx.check("source_inventory", "Aggregate first-party source inventory (step 1)",
                  {SRC: ["source_id", "business_segment", "source_system", "data_categories", "collection_purpose",
                         "aggregate_record_count", "eligible_record_count", "deduplication_method", "source_owner"]})
    if not c.runnable:
        return
    n = 0
    for r in sorted(ctx.rows(SRC), key=lambda r: (str(r.get("source_id")), str(r.get("business_segment")))):
        n += 1
        agg, elig = V.num(r.get("aggregate_record_count")), V.num(r.get("eligible_record_count"))
        sid = r.get("source_id")
        if agg is not None and elig is not None and elig > agg:
            c.partial(f"source {sid}/{r.get('business_segment')}: eligible_record_count {elig:g} exceeds "
                      f"aggregate_record_count {agg:g}; definitions misaligned")
            share = None
        else:
            share = V.ratio(elig, agg)
        if not str(r.get("deduplication_method") or "").strip():
            c.partial(f"source {sid}: deduplication_method unknown; counts not treated as unique populations",
                      [f"{SRC}:deduplication_method"])
        c.observe(f"Source {sid} ({r.get('business_segment')}) aggregate inventory", source_id=sid,
                  business_segment=r.get("business_segment"), source_system=r.get("source_system"),
                  data_categories=r.get("data_categories"), collection_purpose=r.get("collection_purpose"),
                  aggregate_record_count=agg, eligible_record_count=elig, eligible_share=share,
                  eligible_definition=r.get("eligible_record_definition"),
                  deduplication_method=r.get("deduplication_method"), source_owner=r.get("source_owner"),
                  evidence_reference=r.get("evidence_reference"))
    c.observe("First-party sources inventoried (not summed: sources may overlap)", sources=n)


def _audience_match_rates(ctx) -> None:
    c = ctx.check("audience_match_rates", "Supplied base audience sizes and match rates (step 1)",
                  {"audiences": ["id", "type"]})
    if not c.runnable:
        return
    t = ctx.table("audiences")
    missing = [f"audiences:{col}" for col in ("size", "match_rate") if col not in t.columns]
    if missing:
        c.partial("audience size/match-rate columns not supplied", missing)
    lists = [r for r in ctx.rows("audiences")
             if any(k in (_tok(r.get("type")) or "") for k in ("crm", "customer_match", "customer_list"))]
    for r in sorted(lists, key=lambda r: str(r.get("id"))):
        rate = ctx.rate(r.get("match_rate"))
        c.observe(f"Customer list {r.get('id')}: supplied size and match rate (diagnosis → skill-061)",
                  list_id=r.get("id"), size=V.num(r.get("size")), match_rate=rate,
                  match_rate_denominator=r.get("match_rate_denominator"),
                  denominator_known=bool(str(r.get("match_rate_denominator") or "").strip()))
    c.observe("First-party (customer) lists in base audiences", lists=len(lists))


def _permission_gate(ctx) -> Gate:
    need = ["source_id", "market", "intended_use", "permission_status", "consent_coverage_status",
            "permitted_destinations", "retention_limit_days",
            _col(ctx.table(PERM), "withdrawal/deletion_process_status"), "restricted_data_review",
            "policy_eligibility", "reviewed_at", "evidence_reference"]
    c = ctx.check("permission_gate", "Permission gate and readiness per source/use/market (steps 2-3)", {PERM: need})
    gate = Gate(ctx, c.runnable)
    if not c.runnable:
        return gate
    counts = {"permitted": 0, "blocked": 0, "unknown": 0}
    for key in sorted(gate.rows):
        for st in sorted(gate.rows[key], key=lambda s: (str(s["market"]), str(s["list_id"]))):
            counts[st["status"]] += 1
            entity = {"source_id": key[0], "intended_use": key[1], "market": st["market"], "list_id": st["list_id"]}
            c.observe(f"Readiness {st['status']}: source {key[0]} / {key[1]} / {st['market']}", **entity,
                      readiness=st["status"], blockers=st["blockers"], missing_evidence=st["unknown"],
                      permitted_destinations=st["destinations"], reviewer_role=st["reviewer_role"])
            if st["status"] == "permitted":
                continue
            c.finding("activation_blocked_pending_owner_review", "Info", entity,
                      f"Use '{key[1]}' of source {key[0]} in market {st['market']} is {st['status']}: "
                      "no upload, audience, refresh, tag or new-capture proposal for this use",
                      evidence={"blockers": st["blockers"], "missing_evidence": st["unknown"],
                                "evidence_reference": st["evidence_reference"], "reviewed_at": st["reviewed_at"],
                                "reviewer_role": st["reviewer_role"]},
                      recommendation="Request authorized-owner review of the listed permission/consent/retention/"
                                     "eligibility evidence; this is not legal certification.",
                      uncertainty="Readiness reflects supplied owner evidence only; status vocabularies are matched literally.")
    # proposed or active uses with no permission row at all
    wanted: set[tuple[str, str]] = set()
    for key in (PLAN, ACT):
        for r in ctx.rows(key):
            if r.get("source_id") and r.get("intended_use"):
                wanted.add((str(r["source_id"]), _tok(r["intended_use"]) or ""))
    for sid, use in sorted(wanted - set(gate.rows)):
        if gate.complete:
            c.finding("activation_blocked_pending_owner_review", "Info",
                      {"source_id": sid, "intended_use": use, "market": None, "list_id": None},
                      f"No permission evidence row for proposed/active use '{use}' of source {sid}",
                      evidence={"permissions_manifest": "complete"},
                      recommendation="Request the authorized owner's permitted-use evidence before any activation.",
                      uncertainty="Absence proven only for the manifest-complete permissions file.")
        else:
            c.partial(f"use {sid}/{use} has no permission row; permissions file not manifest-complete")
    c.observe("Readiness matrix totals", **counts, uses_without_permission_row=len(wanted - set(gate.rows)))
    return gate


def _active_use_restrictions(ctx, gate: Gate) -> None:
    t = ctx.table(ACT)
    wcol = _col(t, "withdrawal/deletion_sync_status")
    pcol = _col(t, "pipeline/list/action_id")
    c = ctx.check("active_use_restrictions", "Active use contrary to restrictions or withdrawal/retention (step 3)",
                  {ACT: ["source_id", "destination_account_id", "intended_use", pcol, "connection_status",
                         "permission_filter_status", wcol]})
    if not c.runnable:
        return
    if not gate.loaded:
        c.partial("permission evidence unavailable: denial, destination and retention reasons not evaluated",
                  [f"{PERM} (file)"])
    earliest: dict[str, object] = {}
    scol = _col(ctx.table(SRC), "earliest/latest_collection_at")
    for r in ctx.rows(SRC):
        d = V.parse_date(r.get(scol))
        sid = str(r.get("source_id") or "")
        if d is not None and (sid not in earliest or d < earliest[sid]):
            earliest[sid] = d
    ref = _ref_date(ctx)
    active = 0
    for r in sorted(ctx.rows(ACT), key=lambda r: (str(r.get("source_id")), str(r.get("intended_use")),
                                                   str(r.get(pcol)))):
        if _tok(r.get("connection_status")) not in CONN_ACTIVE:
            continue
        active += 1
        sid, use, pid = str(r.get("source_id") or ""), _tok(r.get("intended_use")) or "", r.get(pcol)
        state, rows = gate.lookup(sid, use, pid) if gate.loaded else ("unknown", [])
        reasons = []
        if gate.loaded and state == "blocked":
            reasons.append("permission gate blocked: " + "; ".join(b for x in rows for b in x["blockers"]))
        if _tok(r.get(wcol)) in PROCESS_BAD:
            reasons.append(f"{wcol}={_tok(r.get(wcol))} while pipeline active")
        if _tok(r.get("permission_filter_status")) in PROCESS_BAD:
            reasons.append(f"permission_filter_status={_tok(r.get('permission_filter_status'))}")
        allowed = Gate.destinations(rows) if gate.loaded else None
        if _dest_ok(r.get("destination_account_id"), allowed) is False:
            reasons.append(f"destination {r.get('destination_account_id')} not in permitted_destinations {sorted(allowed)}")
        limits = [x["retention_limit_days"] for x in rows if x["retention_limit_days"]]
        first = earliest.get(sid)
        if limits and first is not None and ref is not None and (ref - first).days - 1 >= min(limits):
            reasons.append(f"records collected since {first} exceed retention_limit_days {min(limits):g} at {ref}")
        entity = {"source_id": sid, "intended_use": use, "pipeline_id": pid,
                  "destination_account_id": r.get("destination_account_id")}
        ev = {"readiness": state, "connection_status": r.get("connection_status"),
              "withdrawal_deletion_sync_status": r.get(wcol),
              "permission_filter_status": r.get("permission_filter_status"),
              "last_successful_refresh_at": r.get("last_successful_refresh_at"),
              "source_reference": r.get("source_reference"), "evidence_date": ref}
        if reasons:
            c.finding("active_use_contrary_to_restrictions", "Warning", entity,
                      f"Active pipeline {pid} ({sid} → {r.get('destination_account_id')}, {use}) runs against "
                      f"approved restrictions: {'; '.join(reasons)}",
                      evidence={**ev, "reasons": reasons},
                      recommendation="Escalate to the accountable data owner to pause or correct the use through "
                                     "their approved process; request-only, no account change here.",
                      uncertainty="Supplied status evidence at the snapshot; not a legal compliance determination.")
            c.review("active_use_contrary_to_restrictions", entity,
                     "Does supplied evidence show MATERIALLY unsafe active data use (e.g. withdrawn/denied records "
                     "actually sent, retention exceeded on active audiences)?",
                     evidence={**ev, "reasons": reasons},
                     outcomes={"material_unsafe_use_evidenced": {"severity": "Critical", "recommendation":
                               "Escalate immediately to the data owner; cite proposal.evidence_ref."},
                               "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                     guidance="Critical needs proposal.evidence_ref pointing at supplied evidence of material unsafe use.")
        elif gate.loaded and state == "unknown":
            prov = c.finding("active_use_permission_unknown", "Info", entity,
                             f"Active pipeline {pid} ({sid}, {use}) has unknown permission readiness",
                             evidence=ev,
                             recommendation="Request authorized-owner permission evidence for this active use.",
                             uncertainty="Unknown permission is not proof of misuse.")
            c.review("active_use_permission_unknown", entity,
                     "Does supplied evidence show this active use is contrary to approved restrictions?",
                     evidence=ev, provisional=prov,
                     outcomes={"contrary_to_restrictions": {"severity": "Warning", "recommendation":
                               "Escalate to the data owner to correct the use."},
                               "material_unsafe_use_evidenced": {"severity": "Critical", "recommendation":
                               "Escalate immediately; cite proposal.evidence_ref."},
                               "pending_owner_review": {"severity": "Info", "recommendation":
                               "Request owner evidence; no activation proposals meanwhile."}},
                     guidance="Critical needs proposal.evidence_ref; lack of evidence → pending_owner_review.")
    c.observe("Active pipelines screened against restrictions", active_pipelines=active)


def _pipeline_health(ctx, gate: Gate) -> None:
    t = ctx.table(ACT)
    pcol, slacol = _col(t, "pipeline/list/action_id"), _col(t, "approved_refresh_SLA")
    c = ctx.check("pipeline_health", "Eligible permitted pipeline connection and refresh SLA (step 4)",
                  {ACT: ["source_id", "destination_account_id", "intended_use", pcol, "connection_status",
                         "eligibility", "last_attempt_at", "last_successful_refresh_at", "source_updated_at", slacol]})
    if not c.runnable:
        return
    if not gate.loaded:
        c.partial("permission gate unavailable: no pipeline evaluated (activation fixes need a passed gate)",
                  [f"{PERM} (file)"])
        return
    ref = _ref_date(ctx)
    evaluated = gated_out = 0
    acol, rcol = _col(t, "accepted_count"), _col(t, "rejected_count")
    for r in sorted(ctx.rows(ACT), key=lambda r: (str(r.get("source_id")), str(r.get("intended_use")),
                                                   str(r.get(pcol)))):
        sid, use, pid = str(r.get("source_id") or ""), _tok(r.get("intended_use")) or "", r.get(pcol)
        state, _rows = gate.lookup(sid, use, pid)
        if state != "permitted" or _tok(r.get("eligibility")) not in ELIGIBLE:
            gated_out += 1
            continue
        evaluated += 1
        entity = {"source_id": sid, "intended_use": use, "pipeline_id": pid,
                  "destination_account_id": r.get("destination_account_id")}
        last_ok, last_try = V.parse_date(r.get("last_successful_refresh_at")), V.parse_date(r.get("last_attempt_at"))
        acc, rej = V.num(r.get(acol)), V.num(r.get(rcol))
        ev = {"connection_status": r.get("connection_status"), "eligibility": r.get("eligibility"),
              "last_attempt_at": r.get("last_attempt_at"), "last_successful_refresh_at": r.get("last_successful_refresh_at"),
              "source_updated_at": r.get("source_updated_at"), "approved_refresh_SLA": r.get(slacol),
              "error_codes": r.get("error_codes"), "accepted_count": acc, "rejected_count": rej,
              "rejected_share": V.ratio(rej, (acc + rej) if acc is not None and rej is not None else None),
              "attempt_after_last_success": bool(last_try and (last_ok is None or last_try > last_ok)),
              "evidence_date": ref, "source_reference": r.get("source_reference")}
        conn = _tok(r.get("connection_status"))
        if conn in CONN_FAILED:
            c.finding("eligible_pipeline_failure", "Warning", entity,
                      f"Permitted eligible pipeline {pid} ({sid} → {r.get('destination_account_id')}) has "
                      f"connection_status {conn}", evidence=ev,
                      recommendation="Ask the integration owner to restore the connection; delegate specifics to "
                                     "skill-061/072/073/080/105 as applicable.",
                      uncertainty="Status at snapshot; recovery after the snapshot is not visible.")
            continue
        if conn not in CONN_ACTIVE:
            c.observe(f"Pipeline {pid}: connection_status {conn!r} not active; freshness not assessed", **entity)
            continue
        sla = _sla_days(r.get(slacol), slacol.endswith("_days"))
        if sla is None or last_ok is None or ref is None:
            miss = [f"{ACT}:{slacol}"] if sla is None else [f"{ACT}:last_successful_refresh_at"] if last_ok is None else []
            c.partial(f"pipeline {pid}: freshness undecidable (SLA with unit, last success and evidence date needed)", miss)
            continue
        age = (ref - last_ok).days
        src_upd = V.parse_date(r.get("source_updated_at"))
        ev.update({"age_days": age, "sla_days": sla})
        if src_upd is not None and src_upd <= last_ok:
            c.observe(f"Pipeline {pid}: no source change since last successful refresh", **entity, age_days=age, sla_days=sla)
        elif age - 1 >= sla:
            c.finding("missed_refresh_sla", "Warning", entity,
                      f"Pipeline {pid}: last successful refresh {last_ok} is {age}d before {ref}, beyond the "
                      f"approved SLA of {sla:g}d", evidence=ev,
                      calculation={"age_days": f"{ref} - {last_ok}", "rule": "age_days - 1 >= sla_days (date granularity)"},
                      recommendation="Ask the pipeline owner to restore successful refreshes within the approved SLA.",
                      uncertainty=("source_updated_at unknown: source change since refresh not evidenced; "
                                   if src_upd is None else "") + "attempts are not successful refreshes.")
        elif age + 1 > sla:
            c.observe(f"Pipeline {pid}: refresh age at SLA boundary within date granularity", **entity,
                      age_days=age, sla_days=sla)
        else:
            c.observe(f"Pipeline {pid}: refreshed within approved SLA", **entity, age_days=age, sla_days=sla)
    c.observe("Pipelines evaluated after gate", evaluated=evaluated, not_evaluated_gate_or_ineligible=gated_out)


def _capture_rates(ctx) -> None:
    c = ctx.check("capture_rates", "Capture and permission rates by collection point (step 5)",
                  {CAP: ["source_id", "collection_point_id", "market", "eligible_unique_visitors_or_opportunities",
                         "denominator_definition", "valid_unique_records", "permitted_use_opt_in_count"]})
    if not c.runnable:
        return
    min_clicks = ctx.params.get("min_clicks")
    groups: dict[tuple, list[dict]] = {}
    for r in sorted(ctx.rows(CAP), key=lambda r: (str(r.get("source_id")), str(r.get("collection_point_id")),
                                                   str(r.get("market")), str(r.get("window_start") or r.get("date")))):
        den, valid = V.num(r.get("eligible_unique_visitors_or_opportunities")), V.num(r.get("valid_unique_records"))
        opt = V.num(r.get("permitted_use_opt_in_count"))
        definition = V.norm_text(r.get("denominator_definition"))
        window = (r.get("window_start") or r.get("date"), r.get("window_end") or r.get("date"))
        point = {"source_id": r.get("source_id"), "collection_point_id": r.get("collection_point_id"),
                 "market": r.get("market"), "window": list(window)}
        capture = None
        if not definition:
            c.partial(f"collection point {point['collection_point_id']}: denominator_definition missing; capture "
                      "not computed", [f"{CAP}:denominator_definition"])
        elif den is None or valid is None:
            c.partial(f"collection point {point['collection_point_id']}: capture counts unknown")
        elif valid > den:
            c.partial(f"collection point {point['collection_point_id']}: valid records exceed denominator; "
                      "populations misaligned")
        else:
            capture = V.ratio(valid, den)
        permission = V.ratio(opt, valid)
        c.observe(f"Collection point {point['collection_point_id']}: capture and permission rates", **point,
                  capture_rate=capture, capture_numerator=valid, capture_denominator=den,
                  denominator_definition=r.get("denominator_definition"), permission_rate=permission,
                  permission_numerator=opt, permission_population="valid_unique_records",
                  submitted_count=V.num(r.get("submitted_count")), offered_form_count=V.num(r.get("offered_form_count")))
        if capture is not None:
            groups.setdefault((str(r.get("source_id")), str(r.get("market")), definition, window), []).append(
                {**point, "capture": capture, "den": den, "valid": valid})
    comparable = [g for g in groups.values() if len(g) >= 2]
    if not comparable:
        return
    if min_clicks.value is None:
        c.partial(f"min_clicks unresolved: {min_clicks.reason}")
        return
    if ctx.mature is not True:
        c.partial(f"capture comparisons disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    for key in sorted(comparable, key=lambda g: str(sorted(str(p["collection_point_id"]) for p in g))):
        ok = sorted((p for p in key if p["den"] >= min_clicks.value), key=lambda p: (p["capture"], str(p["collection_point_id"])))
        if len(ok) < 2:
            c.observe("Collection points not comparable: fewer than two meet min_clicks", points=[p["collection_point_id"] for p in key],
                      min_clicks=min_clicks.value, min_clicks_source=min_clicks.source)
            continue
        low, high = ok[0], ok[-1]
        if low["capture"] >= high["capture"]:
            continue
        c.finding("capture_rate_gap_undiagnosed", "Info",
                  {"source_id": low["source_id"], "market": low["market"], "collection_point_id": low["collection_point_id"]},
                  f"Collection point {low['collection_point_id']} captures {low['capture']:.2%} vs "
                  f"{high['capture']:.2%} at like point {high['collection_point_id']}",
                  evidence={"low": low, "high": high, "min_clicks": min_clicks.value, "min_clicks_source": min_clicks.source},
                  calculation={"capture": "valid_unique_records / eligible_unique_visitors_or_opportunities"},
                  recommendation="Diagnose the collection experience with the site/CRM owner before any change; "
                                 "no capture uplift is forecast.",
                  uncertainty="Count gate is not significance; cause undiagnosed; permission rate is not a defect to bypass.")


def _activation_proposals(ctx, gate: Gate) -> None:
    c = ctx.check("activation_proposals", "Bounded proposals for permitted, useful uses only (step 6)",
                  {PLAN: ["source_id", "intended_use", "purpose", "permitted_destination", "necessary_data_categories",
                          "review_owner", "approved_at", "evidence_reference"]})
    if not c.runnable:
        return
    if not gate.loaded:
        c.partial("permission gate unavailable: every proposal blocked pending owner evidence", [f"{PERM} (file)"])
        return
    for r in sorted(ctx.rows(PLAN), key=lambda r: (str(r.get("source_id")), str(r.get("intended_use")))):
        sid, use = str(r.get("source_id") or ""), _tok(r.get("intended_use")) or ""
        state, rows = gate.lookup(sid, use)
        allowed = Gate.destinations(rows)
        dest_ok = _dest_ok(r.get("permitted_destination"), allowed)
        entity = {"source_id": sid, "intended_use": use, "destination": r.get("permitted_destination")}
        plan_ok = bool(V.parse_date(r.get("approved_at")) and str(r.get("evidence_reference") or "").strip())
        if state != "permitted" or dest_ok is not True or not plan_ok:
            c.observe(f"Use {sid}/{use}: evidence-review request only (no operational proposal)", **entity,
                      readiness=state, destination_permitted=dest_ok, plan_approved=plan_ok)
            continue
        c.review("authorized_activation_opportunity", entity,
                 f"Is permitted use '{use}' of source {sid} to {r.get('permitted_destination')} useful for the "
                 "declared objective, and what bounded request-only proposal follows?",
                 evidence={"purpose": r.get("purpose"), "objective": r.get("campaign_measurement_objective")
                           or r.get("campaign/measurement_objective"),
                           "necessary_data_categories": sorted(_ids(r.get("necessary_data_categories"))),
                           "permitted_destinations": sorted(allowed or []), "review_owner": r.get("review_owner"),
                           "current_alternative": r.get("current_alternative"),
                           "plan_evidence_reference": r.get("evidence_reference")},
                 outcomes={"authorized_opportunity": {"severity": "Info", "recommendation":
                           "Request-only proposal with exact source/destination/purpose, minimum data, owner and "
                           "measurement method; implementation → 072/073/080/090/105."},
                           "not_useful": {"severity": None, "recommendation": "No proposal."},
                           "uncertain": {"severity": None, "recommendation": "Ask the review owner for the decision use."}},
                 guidance="authorized_opportunity needs proposal {source_id, intended_use, destination (permitted), "
                          "data_categories ⊆ necessary_data_categories, owner, measurement_method}. No uplift promise.")


def run(ctx) -> None:
    """Run the identifier guard, source inventory, permission gate, active-use, pipeline and capture-rate checks.

    Rules:   Identifier columns are never read. blocked/unknown readiness → Info
             'activation_blocked_pending_owner_review', never an upload proposal. Active use contrary to restrictions →
             Warning; Critical only via ai_review 'material_unsafe_use_evidenced'. Pipeline Warnings only for permitted
             + eligible pipelines with explicit SLA units. Capture comparisons need a declared denominator, ctx.mature
             True and min_clicks on both sides; they stay Info.
    """
    _identifier_guard(ctx)
    _source_inventory(ctx)
    _audience_match_rates(ctx)
    gate = _permission_gate(ctx)
    _active_use_restrictions(ctx, gate)
    _pipeline_health(ctx, gate)
    _capture_rates(ctx)
    _activation_proposals(ctx, gate)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes need proposal.evidence_ref; opportunity proposals stay inside the permission gate."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_unsafe_use_evidenced":
        return [] if str(proposal.get("evidence_ref") or "").strip() else \
            ["material unsafe use needs proposal.evidence_ref pointing at supplied evidence"]
    if outcome != "authorized_opportunity":
        return []
    problems = []
    if str(proposal.get("source_id") or "") != item.entity["source_id"]:
        problems.append("proposal.source_id must equal the reviewed source")
    if (_tok(proposal.get("intended_use")) or "") != item.entity["intended_use"]:
        problems.append("proposal.intended_use must equal the reviewed use")
    if _dest_ok(proposal.get("destination"), set(item.evidence.get("permitted_destinations") or [])) is not True:
        problems.append("proposal.destination not in permitted_destinations")
    allowed_cats = set(item.evidence.get("necessary_data_categories") or [])
    cats = proposal.get("data_categories")
    cats = V.split_list(cats, (";", "|", ",")) if isinstance(cats, str) else list(cats or [])
    if not cats or not set(cats) <= allowed_cats:
        problems.append(f"proposal.data_categories must be a non-empty subset of {sorted(allowed_cats)}")
    for f in ("owner", "measurement_method"):
        if not str(proposal.get(f) or "").strip():
            problems.append(f"proposal.{f} required")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
