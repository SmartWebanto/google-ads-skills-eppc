"""check.py — skill-073 deterministic Enhanced Conversions for Leads settings, QA, pipeline and diagnostics checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-073-enhanced-conversions-leads/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Leads status comes ONLY from external/enhanced_leads_config.leads_enabled; Web flags are never Leads evidence.
         Not chosen / unknown settings are Info. Missing click identifiers are not a defect when a supported
         matching_method exists; real click IDs are never requested.
         Deterministic Warning: owner expected_stage differs from configured lead_stage; a FAIL synthetic QA check;
         a documented ready_to_submit_sla_hours breach (queue delay or censored age of unsubmitted eligible events).
         Pipeline (080 schemas): distinct event_token per action; accepted/matched/attributed kept separate; a chosen
         action whose eligible outcomes are ALL rejected/unattempted (none pending/accepted) is a provisional Warning
         whose Critical upgrade needs ai_review + proposal.evidence_ref resolving to a source_reference of that
         action's upload attempts for eligible outcomes or of its diagnostics window overlapping the report period;
         reproducible_error refs must equal the reviewed QA row's trace_reference. Long click-to-sale cycles are not
         staleness. Match rates only from reported matched/denominator columns; diagnostic trends need
         processing-mature windows with both eligible denominators >= min_conversions; materiality is AI review.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | evidence_ref resolves to action-scoped attempt/diagnostic/QA refs
"""
from __future__ import annotations

import sys
from datetime import datetime, time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-073-enhanced-conversions-leads"
VERSION = "1.0.0"

CONFIG = "external/enhanced_leads_config"
QA = "external/enhanced_leads_qa"
OUTCOMES = "external/offline_outcomes"
ATTEMPTS = "external/offline_upload_attempts"
PIPE = "external/offline_pipeline_config"
DIAG = "external/enhanced_leads_diagnostics"
QA_CHECKS = ("normalization_check", "hashing_check", "identifier_persistence_check", "stage_mapping_check",
             "destination_check")
_PASS = ("PASS", "PASSED", "OK", "TRUE")
_FAIL = ("FAIL", "FAILED", "ERROR", "FALSE")
_ACCEPTED = ("ACCEPTED", "SUCCESS", "SUCCEEDED", "PROCESSED", "OK")
_PENDING = ("PENDING", "PROCESSING", "QUEUED", "SUBMITTED", "IN_PROGRESS")


def _s(v) -> str:
    return str(v or "").strip()


def _u(v) -> str:
    return "_".join(_s(v).upper().replace("-", " ").split())


def _alnum(v) -> str:
    return "".join(ch for ch in _s(v) if ch.isalnum()).lower()


def _account_rows(ctx, key) -> list[dict]:
    acct = _alnum(ctx.account_id)
    return [r for r in ctx.rows(key)
            if not (acct and _s(r.get("account_id")) and _alnum(r.get("account_id")) != acct)]


def _ts(v) -> datetime | None:
    s = _s(v)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None


def _hours(a: datetime | None, b: datetime | None) -> float | None:
    """b - a in hours; None when unknown or naive/aware timestamps are mixed."""
    if a is None or b is None or (a.tzinfo is None) != (b.tzinfo is None):
        return None
    return (b - a).total_seconds() / 3600


def run(ctx) -> None:
    """Run Leads status, stage mapping, QA, pipeline, cadence and diagnostic-trend checks.

    Rules:   Leads status only from enhanced_leads_config.leads_enabled; not chosen/unknown → Info; missing click IDs
             are no defect. Deterministic Warnings: stage mismatch, FAIL QA check, documented SLA breach; an
             all-rejected/unattempted chosen action is a provisional Warning whose Critical upgrade needs ai_review +
             proposal.evidence_ref. Trends need processing-mature windows with both denominators >= min_conversions;
             materiality is ai_review.
    """
    # -- step 1: settings and ownership
    st = ctx.check("leads_settings", "Enhanced Conversions for Leads settings and ownership",
                   {CONFIG: ["action_id", "leads_enabled", "action_status", "matching_method"]})
    config: dict[str, dict] = {}
    chosen: list[str] = []
    if st.runnable:
        actions = {_s(a.get("id")): a for a in ctx.rows("conversion_actions")}
        not_chosen, unknown = [], []
        for r in sorted(_account_rows(ctx, CONFIG), key=lambda r: _s(r.get("action_id"))):
            aid = _s(r.get("action_id"))
            config[aid] = r
            flag = V.boolean(r.get("leads_enabled"))
            owner = _s(r.get("conversion_customer_id"))
            if owner and _alnum(owner) != _alnum(ctx.account_id):
                st.partial(f"action {aid}: conversions owned by {owner}; settings there govern")
            if actions and aid not in actions:
                st.partial(f"action {aid} not in conversion_actions")
            if flag is True:
                chosen.append(aid)
            elif flag is False:
                not_chosen.append(aid)
            else:
                unknown.append(aid)
            st.observe(f"Leads settings for action {aid}", action_id=aid, leads_enabled=flag,
                       action_status=r.get("action_status"), matching_method=r.get("matching_method"),
                       click_identifier_supported=V.boolean(r.get("click_identifier_supported")),
                       capture_method=r.get("capture_method"), integration_id=r.get("integration_id"),
                       owner=r.get("owner"), note="Web enhancement status is never Leads evidence")
            if V.boolean(r.get("click_identifier_supported")) is False and _s(r.get("matching_method")):
                st.observe(f"Action {aid} matches via {r.get('matching_method')} without click IDs (supported "
                           f"alternative, not a defect)", action_id=aid)
        if not_chosen:
            st.finding("leads_not_chosen", "Info", {"actions": ",".join(not_chosen)},
                       f"{len(not_chosen)} actions do not use Enhanced Conversions for Leads",
                       evidence={"actions": not_chosen}, recommendation="Optional; adopt only with a business reason.",
                       uncertainty="Not universally required.")
        if unknown:
            st.finding("leads_settings_unknown", "Info", {"actions": ",".join(unknown)},
                       f"{len(unknown)} actions have unknown Leads enablement",
                       evidence={"actions": unknown}, recommendation="Supply the Leads settings export.",
                       uncertainty="Unknown is neither enabled nor disabled.")

    # -- step 2: stage mapping
    sm = ctx.check("stage_mapping", "Configured lead stage versus owner-expected stage",
                   {CONFIG: ["action_id", "lead_stage", "expected_stage"]})
    if sm.runnable:
        for aid in sorted(config):
            r = config[aid]
            got, want = _u(r.get("lead_stage")), _u(r.get("expected_stage"))
            if not want:
                sm.observe(f"Action {aid}: no owner-expected stage (form-only tracking may be legitimate)", action_id=aid,
                           lead_stage=got or None)
                continue
            if got and got != want:
                sm.finding("stage_mapping_error", "Warning", {"action_id": aid},
                           f"Action {aid} is configured for stage {got} but the owner expects {want}",
                           evidence={"lead_stage": got, "expected_stage": want, "owner": r.get("owner"),
                                     "leads_enabled": V.boolean(r.get("leads_enabled"))},
                           recommendation="Owner-reviewed stage/action mapping; value reconciliation → 071/107.",
                           uncertainty="Configuration evidence; no conversion-loss estimate.")
            elif not got:
                sm.partial(f"action {aid}: configured lead_stage unknown")

    # -- steps 3-4: synthetic QA
    qa = ctx.check("qa_capture", "Synthetic capture, persistence, normalization, hashing and destination QA",
                   {QA: ["test_id", "action_id", "stage", *QA_CHECKS, "trace_reference"]})
    if qa.runnable:
        fails: dict[str, list] = {}
        unknown = 0
        for r in sorted(_account_rows(ctx, QA), key=lambda r: (_s(r.get("action_id")), _s(r.get("test_id")),
                                                               _s(r.get("step")))):
            aid = _s(r.get("action_id"))
            for col in QA_CHECKS:
                v = _u(r.get(col))
                if v in _FAIL:
                    fails.setdefault(aid, []).append({"test_id": r.get("test_id"), "stage": r.get("stage"), "check": col,
                                                      "consent_state": r.get("consent_state"),
                                                      "trace_reference": r.get("trace_reference")})
                elif v not in _PASS:
                    unknown += 1
            exp, obs = V.norm_text(r.get("expected_behavior")), V.norm_text(r.get("observed_behavior"))
            if obs and obs != exp and "matches expected" not in obs:
                qa.review("qa_behavior_mismatch", {"action_id": aid, "test_id": _s(r.get("test_id")),
                                                   "step": _s(r.get("step"))},
                          f"QA {r.get('test_id')} observed '{r.get('observed_behavior')}' vs expected "
                          f"'{r.get('expected_behavior')}'. Is this a reproducible capture/stage/routing error?",
                          evidence={"stage": r.get("stage"), "consent_state": r.get("consent_state"),
                                    "trace_reference": r.get("trace_reference")},
                          outcomes={"reproducible_error": {"severity": "Warning", "recommendation": "Owner fix; re-run QA."},
                                    "acceptable": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Repeat the QA."}},
                          guidance="Consent behavior → 075. reproducible_error requires proposal.evidence_ref.")
        if unknown:
            qa.partial(f"{unknown} QA check results unknown")
        for aid in sorted(fails):
            qa.finding("reproducible_capture_error", "Warning", {"action_id": aid},
                       f"{len(fails[aid])} synthetic QA checks failed for action {aid}",
                       evidence={"failures": fails[aid], "matching_method": (config.get(aid) or {}).get("matching_method")},
                       recommendation="Assign to the implementation owner; re-run QA after correction.",
                       uncertainty="QA covers the tested deployment and scenarios only.")

    # -- step 5: pipeline outcomes vs attempts (080 schemas, referenced not duplicated)
    pl = ctx.check("pipeline_outcomes", "Eligible outcomes versus accepted/rejected/pending attempts",
                   {OUTCOMES: ["action_id", "event_token", "eligible_for_upload", "supported_identifier_present"],
                    ATTEMPTS: ["action_id", "event_token", "attempt_id", "status"]})
    outcomes_by: dict[str, dict] = {}
    attempts_by: dict[tuple, list] = {}
    if pl.runnable:
        if not chosen:
            pl.partial("no action with leads_enabled true: pipeline assessed descriptively only")
        for r in _account_rows(ctx, OUTCOMES):
            outcomes_by.setdefault(_s(r.get("action_id")), {})[_s(r.get("event_token"))] = r
        for r in _account_rows(ctx, ATTEMPTS):
            attempts_by.setdefault((_s(r.get("action_id")), _s(r.get("event_token"))), []).append(r)
        for aid in sorted(set(outcomes_by) | {k[0] for k in attempts_by}):
            evs = outcomes_by.get(aid, {})
            eligible = {t for t, r in evs.items() if V.boolean(r.get("eligible_for_upload")) is True}
            no_ident = {t for t in eligible if V.boolean(evs[t].get("supported_identifier_present")) is False}
            acc, rej, pend, unatt = set(), set(), set(), set()
            for t in sorted(eligible):
                sts = {_u(a.get("status")) for a in attempts_by.get((aid, t), [])}
                if not sts:
                    unatt.add(t)
                elif sts & set(_ACCEPTED):
                    acc.add(t)
                elif sts & set(_PENDING):
                    pend.add(t)
                else:
                    rej.add(t)
            attempted = len(eligible) - len(unatt)
            ev = {"outcomes": len(evs), "eligible": len(eligible), "eligible_without_supported_identifier": len(no_ident),
                  "attempted": attempted, "accepted": len(acc), "rejected_only": len(rej), "pending": len(pend),
                  "unattempted": len(unatt), "acceptance_rate": V.ratio(len(acc), attempted),
                  "leads_enabled": aid in chosen, "note": "accepted ≠ matched ≠ attributed; see 080 for detail"}
            state = ("no_outcomes" if not evs else "no_eligible_outcomes" if not eligible
                     else "accepted" if acc else "pending_processing" if pend else "failed_or_missing_submission")
            pl.observe(f"Pipeline state for action {aid}: {state}", action_id=aid, state=state, **ev)
            if aid in chosen and state == "failed_or_missing_submission":
                prov = pl.finding("pipeline_omits_eligible_outcomes", "Warning", {"action_id": aid},
                                  f"Action {aid}: none of {len(eligible)} eligible outcomes was accepted "
                                  f"({len(rej)} rejected, {len(unatt)} never attempted, 0 pending)",
                                  evidence=ev, recommendation="Owner review with the integration owner; pipeline "
                                                              "detail and SLA → 080. No replay/bulk upload.",
                                  uncertainty="Materiality depends on whether these outcomes are required.")
                pl.review("pipeline_omits_eligible_outcomes", {"action_id": aid},
                          f"Are the {len(eligible)} unaccepted eligible outcomes for {aid} REQUIRED and is material "
                          f"omission evidenced?",
                          evidence=ev, provisional=prov,
                          outcomes={"material_required_omitted": {"severity": "Critical", "recommendation":
                                                                  "Prioritize pipeline repair; cite evidence."},
                                    "pipeline_error": {"severity": "Warning", "recommendation": "Owner fix via 080."},
                                    "explained": {"severity": None, "recommendation": "Document the reason."},
                                    "uncertain": {"severity": "Warning", "recommendation": "Keep as pipeline error."}},
                          guidance="material_required_omitted requires proposal.evidence_ref (business requirement "
                                   "and impact evidence).")

    # -- step 7: documented cadence (ready → submit SLA)
    cd = ctx.check("pipeline_cadence", "Ready-to-submit delay versus documented SLA",
                   {PIPE: ["action_id", "ready_to_submit_sla_hours"],
                    OUTCOMES: ["action_id", "event_token", "eligible_for_upload", "ready_for_upload_timestamp"],
                    ATTEMPTS: ["action_id", "event_token", "submitted_timestamp"]})
    if cd.runnable:
        if not outcomes_by:
            for r in _account_rows(ctx, OUTCOMES):
                outcomes_by.setdefault(_s(r.get("action_id")), {})[_s(r.get("event_token"))] = r
            for r in _account_rows(ctx, ATTEMPTS):
                attempts_by.setdefault((_s(r.get("action_id")), _s(r.get("event_token"))), []).append(r)
        sla = {_s(r.get("action_id")): V.num(r.get("ready_to_submit_sla_hours")) for r in _account_rows(ctx, PIPE)}
        as_of = datetime.combine(ctx.snapshot or ctx.as_of, time.min) if (ctx.snapshot or ctx.as_of) else None
        for aid in sorted(outcomes_by):
            limit = sla.get(aid)
            if limit is None:
                cd.partial(f"action {aid}: no documented ready_to_submit_sla_hours")
                continue
            delays, censored, breaches, bad = [], [], [], 0
            for t, r in sorted(outcomes_by[aid].items()):
                if V.boolean(r.get("eligible_for_upload")) is not True:
                    continue
                ready = _ts(r.get("ready_for_upload_timestamp"))
                subs = sorted(x for x in (_ts(a.get("submitted_timestamp")) for a in attempts_by.get((aid, t), []))
                              if x is not None and ready is not None and (x.tzinfo is None) == (ready.tzinfo is None))
                if subs:
                    h = _hours(ready, subs[0])
                    if h is None or h < 0:
                        bad += 1
                        continue
                    delays.append(h)
                    if h > limit:
                        breaches.append({"event_token": t, "queue_delay_hours": round(h, 2)})
                else:
                    ref = as_of.replace(tzinfo=ready.tzinfo) if as_of and ready else None
                    h = _hours(ready, ref)
                    if h is None or h < 0:
                        bad += 1
                        continue
                    censored.append(h)
                    if h > limit:
                        breaches.append({"event_token": t, "censored_age_hours": round(h, 2), "unsubmitted": True})
            if bad:
                cd.partial(f"action {aid}: {bad} events with unknown/negative/mixed-timezone timestamps")
            cd.observe(f"Queue delay for action {aid}", action_id=aid, sla_hours=limit, completed=len(delays),
                       max_delay_hours=max(delays) if delays else None, outstanding=len(censored),
                       max_censored_age_hours=max(censored) if censored else None, breaches=len(breaches),
                       note="click-to-sale lag is attribution delay, not pipeline staleness")
            if breaches:
                cd.finding("documented_cadence_breach", "Warning", {"action_id": aid},
                           f"Action {aid}: {len(breaches)} eligible outcomes exceeded the documented "
                           f"{limit:g}h ready-to-submit SLA", evidence={"breaches": breaches, "sla_hours": limit,
                                                                         "censored_reference": as_of},
                           recommendation="Cadence review with the integration owner (080); no replay.",
                           uncertainty="Censored ages use the snapshot date start as reference.")

    # -- step 6: direct diagnostics
    dg = ctx.check("leads_diagnostics", "Direct Leads diagnostics: acceptance, reported matching and trend",
                   {DIAG: ["action_id", "window_start", "window_end", "eligible_records", "accepted_records",
                           "processing_mature"]})
    if dg.runnable:
        mv = ctx.params.get("min_conversions").value
        series: dict[str, list] = {}
        for r in _account_rows(ctx, DIAG):
            series.setdefault(_s(r.get("action_id")), []).append(r)
        for aid in sorted(series):
            pts = []
            for r in sorted(series[aid], key=lambda r: _s(r.get("window_end"))):
                el, ac = V.num(r.get("eligible_records")), V.num(r.get("accepted_records"))
                mn, md = V.num(r.get("matched_records_if_reported")), V.num(r.get("match_denominator_if_reported"))
                pts.append({"window": [r.get("window_start"), r.get("window_end")], "eligible": el, "accepted": ac,
                            "acceptance_rate": V.ratio(ac, el), "match_rate": V.ratio(mn, md),
                            "mature": V.boolean(r.get("processing_mature")) is True,
                            "diagnostic_status": r.get("diagnostic_status")})
            dg.observe(f"Leads diagnostics for action {aid}", action_id=aid, points=pts,
                       note="match rate only where the source reports its own denominator")
            mature = [p for p in pts if p["mature"]]
            if len(mature) < len(pts):
                dg.partial(f"action {aid}: {len(pts) - len(mature)} windows not processing-mature excluded")
            if len(mature) < 2:
                continue
            prev, cur = mature[-2], mature[-1]
            if None in (prev["acceptance_rate"], cur["acceptance_rate"]) or (prev["eligible"] or 0) < mv \
                    or (cur["eligible"] or 0) < mv:
                dg.partial(f"action {aid}: trend needs both eligible denominators >= {mv}")
                continue
            if cur["acceptance_rate"] < prev["acceptance_rate"]:
                dg.review("diagnostic_deterioration", {"action_id": aid, "window_end": _s(cur["window"][1])},
                          f"Is the acceptance drop for {aid} from {prev['acceptance_rate']:.3f} to "
                          f"{cur['acceptance_rate']:.3f} a material deterioration against a comparable baseline?",
                          evidence={"baseline": prev, "current": cur, "min_conversions": mv},
                          outcomes={"material_deterioration": {"severity": "Warning", "recommendation":
                                                               "Owner review of recent capture/CRM changes."},
                                    "not_material": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Monitor the next mature window."}},
                          guidance="No universal acceptance or match-rate threshold.")


def _pipeline_refs(ctx, aid: str) -> set[str]:
    """source_reference of the action's attempts on eligible outcomes and of its diagnostics overlapping the period."""
    eligible = {_s(r.get("event_token")) for r in _account_rows(ctx, OUTCOMES)
                if _s(r.get("action_id")) == aid and V.boolean(r.get("eligible_for_upload")) is True}
    refs = {_s(r.get("source_reference")) for r in _account_rows(ctx, ATTEMPTS)
            if _s(r.get("action_id")) == aid and _s(r.get("event_token")) in eligible}
    for r in _account_rows(ctx, DIAG):
        start, end = V.parse_date(r.get("window_start")), V.parse_date(r.get("window_end"))
        if _s(r.get("action_id")) != aid or start is None or end is None:
            continue
        if (ctx.period_end is None or start <= ctx.period_end) and (ctx.period_start is None or end >= ctx.period_start):
            refs.add(_s(r.get("source_reference")))
    return refs - {""}


def _qa_refs(ctx, entity: dict) -> set[str]:
    """trace_reference of the QA row(s) at the item's action_id/test_id/step."""
    key = (_s(entity.get("action_id")), _s(entity.get("test_id")), _s(entity.get("step")))
    return {_s(r.get("trace_reference")) for r in _account_rows(ctx, QA)
            if (_s(r.get("action_id")), _s(r.get("test_id")), _s(r.get("step"))) == key} - {""}


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   material_required_omitted (Critical) requires proposal.evidence_ref equal to a source_reference of
             external/offline_upload_attempts for the item's action_id on an eligible outcome token, or of
             external/enhanced_leads_diagnostics for that action whose window overlaps the report period.
             reproducible_error (Warning) requires proposal.evidence_ref equal to the trace_reference of the reviewed
             external/enhanced_leads_qa row (same action_id/test_id/step). Other outcomes need no proposal.
    """
    outcome = decision.get("outcome")
    if outcome == "material_required_omitted":
        allowed, where = _pipeline_refs(ctx, _s(item.entity.get("action_id"))), f"{ATTEMPTS}/{DIAG}"
    elif outcome == "reproducible_error":
        allowed, where = _qa_refs(ctx, item.entity), QA
    else:
        return []
    ref = _s((decision.get("proposal") or {}).get("evidence_ref"))
    if not ref:
        return ["proposal.evidence_ref required"]
    if ref not in allowed:
        return [f"evidence_ref {ref} not found for action {item.entity.get('action_id')} in {where}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
