"""check.py — skill-072 deterministic Enhanced Conversions for Web settings, diagnostics and synthetic trace checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-072-enhanced-conversions-web/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Web status comes ONLY from external/enhanced_web_config (web_enabled/action_web_status) or an explicitly
         named conversion_actions.enhanced_web_enabled; any Leads flag (enhanced_conversions_for_leads_enabled,
         leads_enabled) and the ambiguous generic 'enhanced_conversions' column are NEVER Web evidence.
         Non-adoption and unknown settings are Info. Enabled status alone does not prove capture.
         Deterministic Warning only from synthetic traces: destination_correct False (incorrect routing) or a FAIL
         normalization/hashing check (reproducible rejected-payload risk) on an eligible action.
         Diagnostic status meaning, deterioration materiality and behavior mismatches are AI review; rates use
         source numerator/denominator, mature windows only, both denominators >= min_conversions; no 25% rule.
         Critical only via ai_review with proposal.evidence_ref (+ proposal.policy_ref for prohibited transmission).
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

SKILL = "skill-072-enhanced-conversions-web"
VERSION = "1.0.0"

CONFIG = "external/enhanced_web_config"
DIAG = "external/enhanced_web_diagnostics"
TRACES = "external/enhanced_web_traces"
_WEB_TYPES = ("WEBSITE", "WEBPAGE", "WEBPAGE_CODELESS", "GOOGLE_TAG", "WEB")
_PASS = ("PASS", "PASSED", "OK", "TRUE")
_FAIL = ("FAIL", "FAILED", "ERROR", "FALSE")


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


def _eligible(ctx) -> dict[str, dict]:
    return {_s(a.get("id")): a for a in ctx.rows("conversion_actions")
            if _u(a.get("status")) == "ENABLED" and _u(a.get("type")) in _WEB_TYPES}


def run(ctx) -> None:
    """Run Web eligibility, settings, diagnostics status/trend and synthetic-trace routing/hashing/behavior checks.

    Rules:   Web status only from external/enhanced_web_config or conversion_actions.enhanced_web_enabled; a conflict
             between them → partial/unknown; Leads flags are never Web evidence; off/unknown settings → Info only.
             Deterministic Warning only for eligible actions: destination_correct False or FAIL normalization/hashing;
             trend compares mature windows only with both denominators >= min_conversions, drops go to ai_review.
             Diagnostic issues, duplicate sends, behavior mismatches, missing identifiers → ai_review; coverage observe-only.
    """
    # -- step 1: eligible actions and ownership
    el = ctx.check("eligible_actions", "Eligible website actions and conversion owner",
                   {"conversion_actions": ["id", "type", "status"]})
    eligible = _eligible(ctx) if el.runnable else {}
    if el.runnable:
        cols = ctx.table("conversion_actions").columns
        owners = sorted({_s(a.get("conversion_customer_id")) or "unknown" for a in eligible.values()})
        el.observe("Eligible Web actions (Leads status is never Web evidence)", eligible=sorted(eligible),
                   conversion_owners=owners, account=ctx.account_id,
                   ignored_columns=[c for c in ("enhanced_conversions", "enhanced_conversions_for_leads_enabled",
                                                "leads_enabled") if c in cols or c in ctx.account])
        if not eligible:
            el.not_applicable("no enabled website conversion action")

    # -- steps 1-2: settings
    st = ctx.check("web_settings", "Web enhancement settings per eligible action",
                   {CONFIG: ["action_id", "web_enabled", "action_web_status", "implementation_method"]})
    config: dict[str, dict] = {}
    if st.runnable:
        for r in _account_rows(ctx, CONFIG):
            config[_s(r.get("action_id"))] = r
        unknown, not_adopted = [], []
        for aid in sorted(eligible):
            r = config.get(aid)
            flag = V.boolean(r.get("web_enabled")) if r else None
            action_flag = V.boolean(eligible[aid].get("enhanced_web_enabled"))
            if flag is not None and action_flag is not None and flag != action_flag:
                st.partial(f"action {aid}: config web_enabled {flag} conflicts with conversion_actions {action_flag}")
                flag = None
            if flag is None:
                unknown.append(aid)
            elif flag is False:
                not_adopted.append(aid)
            st.observe(f"Web settings for action {aid}", action_id=aid, web_enabled=flag,
                       action_web_status=(r or {}).get("action_web_status"),
                       implementation_method=(r or {}).get("implementation_method"),
                       conversion_customer_id=(r or {}).get("conversion_customer_id"),
                       tag_destination_id=(r or {}).get("tag_destination_id"), owner=(r or {}).get("owner"),
                       source=CONFIG)
        if not_adopted:
            st.finding("web_not_adopted", "Info", {"actions": ",".join(not_adopted)},
                       f"{len(not_adopted)} eligible website actions have Enhanced Conversions for Web off",
                       evidence={"actions": not_adopted, "source": CONFIG},
                       recommendation="Optional opportunity for owner review; do not expand personal-data capture.",
                       uncertainty="Non-adoption is not a defect.")
        if unknown:
            st.finding("web_settings_unknown", "Info", {"actions": ",".join(unknown)},
                       f"{len(unknown)} eligible website actions have unknown Web enhancement settings",
                       evidence={"actions": unknown}, recommendation="Supply the Web settings inventory.",
                       uncertainty="Unknown is neither enabled nor disabled.")
    enabled = sorted(a for a in eligible if a in config and V.boolean(config[a].get("web_enabled")) is True)

    # -- step 2: diagnostics status
    dg = ctx.check("diagnostics_status", "Settings joined to action diagnostics",
                   {DIAG: ["action_id", "window_start", "window_end", "diagnostic_code", "diagnostic_status",
                           "processing_mature"]})
    diag: dict[str, list] = {}
    if dg.runnable:
        for r in _account_rows(ctx, DIAG):
            diag.setdefault(_s(r.get("action_id")), []).append(r)
        for aid in enabled:
            rows = sorted(diag.get(aid, []), key=lambda r: (_s(r.get("window_end")), _s(r.get("metric_name"))))
            if not rows:
                dg.partial(f"action {aid}: enabled but no diagnostics; capture/transmission unproven")
                continue
            last = rows[-1]
            code, status = _u(last.get("diagnostic_code")), _u(last.get("diagnostic_status"))
            healthy = code in ("", "NONE") and "NO_ISSUES" in status
            dg.observe(f"Latest diagnostic for action {aid}", action_id=aid, window=[last.get("window_start"),
                       last.get("window_end")], diagnostic_code=code, diagnostic_status=status, healthy=healthy,
                       processing_mature=last.get("processing_mature"), source_reference=last.get("source_reference"))
            if not healthy:
                dg.review("diagnostic_issue", {"action_id": aid, "window_end": _s(last.get("window_end"))},
                          f"Does diagnostic {code or '-'} / {status or '-'} for action {aid} show reproducible "
                          f"rejected payloads in the chosen Web implementation?",
                          evidence={"diagnostic_code": code, "diagnostic_status": status,
                                    "implementation_method": last.get("implementation_method"),
                                    "processing_mature": last.get("processing_mature"),
                                    "source_reference": last.get("source_reference")},
                          outcomes={"reproducible_rejected_payloads": {"severity": "Warning", "recommendation":
                                                                       "Owner-reviewed implementation correction."},
                                    "informational": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Request trace QA."}},
                          guidance="Warning requires proposal.evidence_ref (diagnostic or trace reference).")

    # -- step 6: diagnostic trend
    tr = ctx.check("diagnostics_trend", "Mature source-defined diagnostic rates versus prior window",
                   {DIAG: ["action_id", "window_start", "window_end", "metric_name", "metric_numerator",
                           "metric_denominator", "processing_mature"]})
    if tr.runnable:
        mv = ctx.params.get("min_conversions").value
        series: dict[tuple, list] = {}
        immature = 0
        for aid in enabled:
            for r in diag.get(aid, []) or [x for x in _account_rows(ctx, DIAG) if _s(x.get("action_id")) == aid]:
                if V.boolean(r.get("processing_mature")) is not True:
                    immature += 1
                    continue
                series.setdefault((aid, _s(r.get("metric_name")), _s(r.get("implementation_method"))), []).append(r)
        if immature:
            tr.partial(f"{immature} diagnostic windows not processing-mature excluded")
        for key in sorted(series):
            rows = sorted(series[key], key=lambda r: _s(r.get("window_end")))
            pts = [{"window": [r.get("window_start"), r.get("window_end")], "numerator": V.num(r.get("metric_numerator")),
                    "denominator": V.num(r.get("metric_denominator"))} for r in rows]
            for p in pts:
                p["rate"] = V.ratio(p["numerator"], p["denominator"])
            tr.observe(f"Diagnostic series {key[1]} for action {key[0]}", action_id=key[0], metric_name=key[1],
                       implementation_method=key[2], points=pts)
            if len(pts) < 2:
                continue
            prev, cur = pts[-2], pts[-1]
            if None in (prev["rate"], cur["rate"]) or (prev["denominator"] or 0) < mv or (cur["denominator"] or 0) < mv:
                tr.partial(f"action {key[0]} {key[1]}: comparison needs both denominators >= {mv}")
                continue
            if cur["rate"] < prev["rate"]:
                tr.review("diagnostic_deterioration", {"action_id": key[0], "metric_name": key[1],
                                                       "window_end": _s(cur["window"][1])},
                          f"Is the drop in {key[1]} for action {key[0]} from {prev['rate']:.3f} to {cur['rate']:.3f} a "
                          f"material deterioration against a comparable baseline?",
                          evidence={"baseline": prev, "current": cur, "implementation_method": key[2],
                                    "min_conversions": mv},
                          outcomes={"material_deterioration": {"severity": "Warning", "recommendation":
                                                               "Owner review of recent tag/site changes; QA traces."},
                                    "not_material": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Monitor the next mature window."}},
                          guidance="No universal match-rate threshold; consider seasonality, method or site changes.")

    # -- steps 3/5: traces — routing and duplicates
    traces = []
    rt = ctx.check("trace_routing", "Synthetic traces: destination and duplicate sends",
                   {TRACES: ["test_id", "action_id", "scenario", "destination_correct", "duplicate_send_count",
                             "trace_reference"]})
    if rt.runnable:
        traces = sorted(_account_rows(ctx, TRACES), key=lambda r: (_s(r.get("action_id")), _s(r.get("test_id")),
                                                                    _s(r.get("step"))))
        wrong: dict[str, list] = {}
        for r in traces:
            aid = _s(r.get("action_id"))
            if V.boolean(r.get("destination_correct")) is False:
                wrong.setdefault(aid, []).append({"test_id": r.get("test_id"), "scenario": r.get("scenario"),
                                                  "trace_reference": r.get("trace_reference")})
            dup = V.num(r.get("duplicate_send_count"))
            if dup and dup > 0:
                ent = {"action_id": aid, "test_id": _s(r.get("test_id")), "step": _s(r.get("step"))}
                ev = {"scenario": r.get("scenario"), "duplicate_send_count": dup,
                      "deployment_version": r.get("deployment_version"), "trace_reference": r.get("trace_reference")}
                prov = rt.finding("duplicate_send", "Info", ent,
                                  f"Trace {ent['test_id']} ({r.get('scenario')}) observed {dup:g} duplicate sends",
                                  evidence=ev, recommendation="Diagnose separately from enhancement; route to 071/110.",
                                  uncertainty="Materiality depends on the production share of this scenario.")
                rt.review("duplicate_send", ent,
                          f"Is the duplicate send in trace {ent['test_id']} a reproducible implementation error, and "
                          f"is material measurement failure evidenced?",
                          evidence=ev, provisional=prov,
                          outcomes={"material_measurement_failure": {"severity": "Critical", "recommendation":
                                                                     "Urgent owner fix; cite impact evidence."},
                                    "reproducible_error": {"severity": "Warning", "recommendation": "Owner fix; QA again."},
                                    "expected_behavior": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Repeat the trace."}},
                          guidance="Warning/Critical require proposal.evidence_ref; Critical needs evidenced material impact.")
        for aid in sorted(wrong):
            if aid not in eligible:
                continue
            rt.finding("incorrect_routing", "Warning", {"action_id": aid},
                       f"{len(wrong[aid])} synthetic traces for action {aid} reached an incorrect destination",
                       evidence={"traces": wrong[aid], "tag_destination_id": (config.get(aid) or {}).get("tag_destination_id")},
                       recommendation="Owner-reviewed tag destination correction; re-run the traces.",
                       uncertainty="Synthetic traces cover the tested deployment/browser only.")

    # -- step 3: normalization and hashing
    nh = ctx.check("trace_normalization_hashing", "Synthetic traces: normalization and hashing",
                   {TRACES: ["test_id", "action_id", "normalization_check", "hashing_method", "hashing_check"]})
    if nh.runnable:
        fails: dict[str, list] = {}
        unknown = 0
        for r in traces or _account_rows(ctx, TRACES):
            for col in ("normalization_check", "hashing_check"):
                v = _u(r.get(col))
                if v in _FAIL:
                    fails.setdefault(_s(r.get("action_id")), []).append(
                        {"test_id": r.get("test_id"), "check": col, "hashing_method": r.get("hashing_method"),
                         "trace_reference": r.get("trace_reference")})
                elif v not in _PASS:
                    unknown += 1
        if unknown:
            nh.partial(f"{unknown} normalization/hashing results unknown")
        for aid in sorted(fails):
            if aid not in eligible:
                continue
            nh.finding("hashing_or_normalization_failure", "Warning", {"action_id": aid},
                       f"{len(fails[aid])} synthetic trace checks failed normalization/hashing for action {aid}",
                       evidence={"failures": fails[aid],
                                 "implementation_method": (config.get(aid) or {}).get("implementation_method")},
                       recommendation="Owner-reviewed correction for the chosen method (automatic vs pre-hashed).",
                       uncertainty="Hashing is not anonymization or legal approval.")

    # -- steps 3/7: behavior vs expectation, scenario coverage
    bh = ctx.check("trace_behavior", "Synthetic traces: observed versus expected behavior",
                   {TRACES: ["test_id", "action_id", "scenario", "consent_state", "expected_behavior", "observed_behavior"]})
    if bh.runnable:
        rows = traces or _account_rows(ctx, TRACES)
        by_action: dict[str, set] = {}
        for r in rows:
            aid = _s(r.get("action_id"))
            by_action.setdefault(aid, set()).add(_s(r.get("scenario")).lower())
            exp, obs = V.norm_text(r.get("expected_behavior")), V.norm_text(r.get("observed_behavior"))
            if not obs or obs == exp or "matches expected" in obs:
                continue
            ent = {"action_id": aid, "test_id": _s(r.get("test_id")), "step": _s(r.get("step"))}
            bh.review("trace_behavior_mismatch", ent,
                      f"Trace {ent['test_id']} ({r.get('scenario')}, consent {r.get('consent_state')}) observed "
                      f"'{r.get('observed_behavior')}' vs expected '{r.get('expected_behavior')}'. Which outcome applies?",
                      evidence={"scenario": r.get("scenario"), "consent_state": r.get("consent_state"),
                                "event_trigger": r.get("event_trigger"), "expected_behavior": r.get("expected_behavior"),
                                "observed_behavior": r.get("observed_behavior"),
                                "trace_reference": r.get("trace_reference"),
                                "consent_policy_reference": (config.get(aid) or {}).get("consent_policy_reference")},
                      outcomes={"prohibited_or_material_failure": {"severity": "Critical", "recommendation":
                                                                   "Urgent owner/consent review (075); cite evidence."},
                                "reproducible_error": {"severity": "Warning", "recommendation": "Owner-reviewed fix."},
                                "acceptable": {"severity": None, "recommendation": "No action."},
                                "uncertain": {"severity": "Info", "recommendation": "Repeat the trace."}},
                      guidance="Consent behavior routes to 075. Critical requires proposal.evidence_ref and "
                               "proposal.policy_ref (supplied technical policy) or evidenced material impact.")
        wanted = {"valid", "invalid", "repeated", "accept", "deny"}
        for aid in sorted(by_action):
            bh.observe(f"Scenario coverage for action {aid}", action_id=aid, scenarios=sorted(by_action[aid]),
                       not_tested=sorted(wanted - by_action[aid]), note="'where applicable'; absence is not a defect")

    # -- step 4: identifier coverage
    idc = ctx.check("identifier_coverage", "Identifier field-type coverage versus chosen method",
                    {TRACES: ["test_id", "action_id", "scenario", "consent_state", "identifier_type_presence"]})
    if idc.runnable:
        for r in traces or _account_rows(ctx, TRACES):
            aid = _s(r.get("action_id"))
            presence = V.norm_text(r.get("identifier_type_presence"))
            granted = _s(r.get("consent_state")).lower() in ("granted", "accept", "accepted")
            idc.observe(f"Identifier types in trace {r.get('test_id')}", action_id=aid, test_id=r.get("test_id"),
                        scenario=r.get("scenario"), identifier_type_presence=r.get("identifier_type_presence"),
                        supported_identifier_types=(config.get(aid) or {}).get("supported_identifier_types"),
                        note="optional phone/name absence is not a defect when the method is satisfied")
            if granted and _s(r.get("scenario")).lower() == "valid" and presence in ("none", "absent", "no identifiers"):
                idc.review("identifier_missing", {"action_id": aid, "test_id": _s(r.get("test_id"))},
                           f"A valid granted trace for {aid} captured no identifier. Is this a reproducible capture error "
                           f"for the chosen method?",
                           evidence={"identifier_type_presence": r.get("identifier_type_presence"),
                                     "supported_identifier_types": (config.get(aid) or {}).get("supported_identifier_types"),
                                     "trace_reference": r.get("trace_reference")},
                           outcomes={"reproducible_error": {"severity": "Warning", "recommendation": "Owner fix."},
                                     "method_satisfied": {"severity": None, "recommendation": "No action."},
                                     "uncertain": {"severity": "Info", "recommendation": "Repeat the trace."}},
                           guidance="Warning requires proposal.evidence_ref.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning/Critical outcomes need proposal.evidence_ref; prohibited transmission also policy_ref or impact."""
    outcome = decision.get("outcome")
    spec = item.outcomes.get(outcome) or {}
    if spec.get("severity") not in ("Warning", "Critical") or outcome == "material_deterioration":
        return []
    p = decision.get("proposal") or {}
    problems = [] if _s(p.get("evidence_ref")) else ["proposal.evidence_ref required"]
    if outcome == "prohibited_or_material_failure" and not (_s(p.get("policy_ref")) or _s(p.get("impact_ref"))):
        problems.append("Critical needs proposal.policy_ref (supplied technical policy) or proposal.impact_ref")
    if outcome == "material_measurement_failure" and not _s(p.get("impact_ref")):
        problems.append("Critical needs proposal.impact_ref (evidenced material impact)")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
