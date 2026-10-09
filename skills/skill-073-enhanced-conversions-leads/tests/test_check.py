"""test_check.py — Decision-boundary tests for skill-073 Enhanced Conversions for Leads.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-073-enhanced-conversions-leads/tests -t skills/skill-073-enhanced-conversions-leads
rules:   Temp folders only; pins settings, stage, QA, pipeline, cadence and diagnostic boundaries, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | evidence_ref must resolve to action attempt/diag/QA refs
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_073", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(c for r in rows for c in r))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _config(enabled="true", stage="qualified_lead", expected="qualified_lead", click="false"):
    return {"account_id": "1", "conversion_customer_id": "1", "action_id": "L1", "leads_enabled": enabled,
            "action_status": "ENABLED", "lead_stage": stage, "expected_stage": expected, "matching_method": "email",
            "supported_identifier_types": "email", "click_identifier_supported": click, "capture_method": "form",
            "consent_policy_reference": "p", "integration_id": "crm", "owner": "ops"}


def _qa(check="PASS"):
    return {"test_id": "Q1", "action_id": "L1", "stage": "form", "step": 1, "tested_at": "2026-09-06",
            "consent_state": "granted", "identifier_type_presence": "email", "normalization_check": "PASS",
            "hashing_check": check, "identifier_persistence_check": "PASS", "stage_mapping_check": "PASS",
            "destination_check": "PASS", "expected_behavior": "stored", "observed_behavior": "matches expected behavior",
            "trace_reference": "qa-1"}


def _outcome(t, ready="2026-08-10T10:00:00+02:00"):
    return {"account_id": "1", "action_id": "L1", "event_token": t, "integration_id": "crm",
            "business_event_timestamp": "2026-08-05T10:00:00+02:00", "ready_for_upload_timestamp": ready,
            "eligible_for_upload": "true", "matching_method": "email", "supported_identifier_present": "true"}


def _attempt(t, status, submitted="2026-08-10T20:00:00+02:00"):
    return {"account_id": "1", "action_id": "L1", "event_token": t, "attempt_id": f"a-{t}-{status}",
            "submitted_timestamp": submitted, "processed_timestamp": "", "status": status}


def _diag(end, eligible, accepted, mature="true"):
    return {"account_id": "1", "action_id": "L1", "window_start": end[:8] + "01", "window_end": end,
            "eligible_records": eligible, "accepted_records": accepted, "matched_records_if_reported": "",
            "match_denominator_if_reported": "", "metric_definition": "accepted", "diagnostic_status": "OK",
            "processing_mature": mature, "source_reference": "d"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, config=None, qa=None, outcomes=None, attempts=None, pipe=None, diag=None):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}])
        _write(root / "conversion_actions.csv", [{"id": "L1", "status": "ENABLED", "type": "UPLOAD_CLICKS"}])
        files = []
        for key, rows in (("external/enhanced_leads_config.csv", config), ("external/enhanced_leads_qa.csv", qa),
                          ("external/offline_outcomes.csv", outcomes), ("external/offline_upload_attempts.csv", attempts),
                          ("external/offline_pipeline_config.csv", pipe),
                          ("external/enhanced_leads_diagnostics.csv", diag)):
            if rows:
                _write(root / key, rows)
                files.append(key)
        _write(root / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                             for f in files])
        self.profile = self.dir / "profile.json"
        self.profile.write_text("{}")
        self.root = root
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, self.profile).finish()

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def status(body, check):
        return next(c["status"] for c in body["coverage"] if c["check"] == check)


class Settings(Base):
    def test_not_chosen_is_info_and_missing_click_id_is_not_defect(self):
        body = self.build(config=[_config(enabled="false")])
        self.assertEqual([f["severity"] for f in self.found(body, "leads_not_chosen")], ["Info"])
        body = self.build(config=[_config(click="false")])
        self.assertEqual(body["findings"], [])

    def test_stage_mismatch_is_warning_missing_expectation_is_not(self):
        body = self.build(config=[_config(stage="form_submit", expected="qualified_lead")])
        self.assertEqual([f["severity"] for f in self.found(body, "stage_mapping_error")], ["Warning"])
        body = self.build(config=[_config(expected="")])
        self.assertEqual(self.found(body, "stage_mapping_error"), [])

    def test_qa_failure_is_warning_unknown_is_partial(self):
        body = self.build(config=[_config()], qa=[_qa("FAIL")])
        self.assertEqual([f["severity"] for f in self.found(body, "reproducible_capture_error")], ["Warning"])
        body = self.build(config=[_config()], qa=[_qa("")])
        self.assertEqual(self.found(body, "reproducible_capture_error"), [])
        self.assertEqual(self.status(body, "qa_capture"), "partial")


class Pipeline(Base):
    def test_all_eligible_rejected_is_provisional_warning(self):
        body = self.build(config=[_config()], outcomes=[_outcome("E1"), _outcome("E2")],
                          attempts=[_attempt("E1", "REJECTED")])
        self.assertEqual([f["severity"] for f in self.found(body, "pipeline_omits_eligible_outcomes")], ["Warning"])
        self.assertEqual(len(body["ai_review"]), 1)

    def test_pending_or_retry_success_is_not_failure(self):
        body = self.build(config=[_config()], outcomes=[_outcome("E1"), _outcome("E2")],
                          attempts=[_attempt("E1", "REJECTED"), _attempt("E1", "ACCEPTED"), _attempt("E2", "REJECTED")])
        self.assertEqual(self.found(body, "pipeline_omits_eligible_outcomes"), [])
        body = self.build(config=[_config()], outcomes=[_outcome("E1")], attempts=[_attempt("E1", "PENDING")])
        self.assertEqual(self.found(body, "pipeline_omits_eligible_outcomes"), [])

    def test_not_chosen_pipeline_is_descriptive(self):
        body = self.build(config=[_config(enabled="false")], outcomes=[_outcome("E1")], attempts=[_attempt("E1", "REJECTED")])
        self.assertEqual(self.found(body, "pipeline_omits_eligible_outcomes"), [])
        self.assertEqual(self.status(body, "pipeline_outcomes"), "partial")

    def test_cadence_breach_uses_documented_sla(self):
        pipe = [{"account_id": "1", "action_id": "L1", "integration_id": "crm", "ready_to_submit_sla_hours": 24}]
        body = self.build(config=[_config()], outcomes=[_outcome("E1")], attempts=[_attempt("E1", "ACCEPTED")], pipe=pipe)
        self.assertEqual(self.found(body, "documented_cadence_breach"), [])  # 10h queue delay
        body = self.build(config=[_config()], outcomes=[_outcome("E1")],
                          attempts=[_attempt("E1", "ACCEPTED", submitted="2026-08-12T10:00:00+02:00")], pipe=pipe)
        self.assertEqual([f["severity"] for f in self.found(body, "documented_cadence_breach")], ["Warning"])
        body = self.build(config=[_config()], outcomes=[_outcome("E1")], attempts=[_attempt("E1", "ACCEPTED")],
                          pipe=[dict(pipe[0], ready_to_submit_sla_hours="")])
        self.assertEqual(self.status(body, "pipeline_cadence"), "partial")

    def finalize(self, outcome, proposal, **tables):
        body = self.build(config=[_config()], **tables)
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
        dec = self.dir / "d.json"
        dec.write_text(json.dumps([{"id": body["ai_review"][0]["id"], "outcome": outcome,
                                    "rationale": "r", "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_critical_requires_resolvable_evidence_ref(self):
        tables = {"outcomes": [_outcome("E1"), dict(_outcome("X1"), eligible_for_upload="false")],
                  "attempts": [dict(_attempt("E1", "REJECTED"), source_reference="upl-E1"),
                               dict(_attempt("X1", "REJECTED"), source_reference="upl-X1"),
                               dict(_attempt("E9", "REJECTED"), action_id="L2", source_reference="upl-L2")],
                  "diag": [_diag("2026-08-30", 10, 0, mature="false"),
                           dict(_diag("2026-06-30", 10, 0, mature="false"), source_reference="d-june")]}
        code, final = self.finalize("material_required_omitted", {}, **tables)
        self.assertEqual((code, final["counts"]["Critical"]), (4, 0))
        # unknown, ineligible outcome's attempt, another action, diagnostics window outside the report period
        for ref in ("crm-required-stage", "upl-X1", "upl-L2", "d-june"):
            code, final = self.finalize("material_required_omitted", {"evidence_ref": ref}, **tables)
            self.assertEqual((code, final["counts"]["Critical"]), (4, 0), ref)
        for ref in ("upl-E1", "d"):
            code, final = self.finalize("material_required_omitted", {"evidence_ref": ref}, **tables)
            self.assertEqual((code, final["counts"]["Critical"]), (0, 1), ref)

    def test_qa_error_ref_must_be_reviewed_trace(self):
        qa = [dict(_qa(), observed_behavior="dropped at CRM"),
              dict(_qa(), test_id="Q2", trace_reference="qa-2")]
        for ref, want in (("qa-x", 4), ("qa-2", 4), ("qa-1", 0)):
            code, _ = self.finalize("reproducible_error", {"evidence_ref": ref}, qa=qa)
            self.assertEqual(code, want, ref)


class Diagnostics(Base):
    def test_mature_drop_is_reviewed_small_is_not(self):
        body = self.build(diag=[_diag("2026-07-31", 100, 95), _diag("2026-08-30", 100, 60)])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["diagnostic_deterioration"])
        body = self.build(diag=[_diag("2026-07-31", 10, 9), _diag("2026-08-30", 10, 2)])
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.status(body, "leads_diagnostics"), "partial")

    def test_unreported_match_rate_stays_unknown(self):
        body = self.build(diag=[_diag("2026-08-30", 100, 60)])
        pts = [o for o in body["observations"] if o["check"] == "leads_diagnostics"][0]["data"]["points"]
        self.assertIsNone(pts[0]["match_rate"])


if __name__ == "__main__":
    unittest.main()
