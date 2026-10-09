"""test_check.py — decision boundaries of skill-080 offline pipeline checks (stdlib unittest, temp folders).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-080-offline-conversion-import/tests -t skills/skill-080-offline-conversion-import
rules:   Synthetic evidence only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx110 | payload validation tests (index #110)
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | tests for this session's check changes
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_080", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def main(args) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(M.SKILL, M.VERSION, M.run, M.verify, args)


ACCOUNT = {"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
CFG_COLS = ["account_id", "action_id", "integration_id", "expected_business_event", "matching_method",
            "intended_cadence_hours", "ready_to_submit_sla_hours", "processing_expectation_hours",
            "automation_status", "owner"]
OUT_COLS = ["account_id", "action_id", "event_token", "integration_id", "business_event_timestamp",
            "ready_for_upload_timestamp", "eligible_for_upload"]
ATT_COLS = ["account_id", "action_id", "event_token", "attempt_id", "integration_id", "batch_id",
            "submitted_timestamp", "processed_timestamp", "status", "rejection_code", "retry_of_attempt_id",
            "attributed_status_if_reported"]
T0 = "2026-08-20T10:00:00+02:00"


def _write(path: Path, rows, cols) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def outcome(token, eligible="True", ready=T0, biz=T0):
    return {"account_id": "demo", "action_id": "A", "event_token": token, "integration_id": "CRM",
            "business_event_timestamp": biz, "ready_for_upload_timestamp": ready, "eligible_for_upload": eligible}


def attempt(token, aid, submitted, processed, status="ACCEPTED", batch="B1", retry="", code=""):
    return {"account_id": "demo", "action_id": "A", "event_token": token, "attempt_id": aid, "integration_id": "CRM",
            "batch_id": batch, "submitted_timestamp": submitted, "processed_timestamp": processed, "status": status,
            "rejection_code": code, "retry_of_attempt_id": retry, "attributed_status_if_reported": ""}


class OfflinePipelineTests(unittest.TestCase):
    def make(self, outcomes, attempts, cfg=None, manifest=True, with_attempts=True) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        exp = self.root / "export"
        _write(exp / "account.csv", [ACCOUNT], list(ACCOUNT))
        _write(exp / "conversion_actions.csv", [{"id": "A", "type": "UPLOAD_CLICKS", "status": "ENABLED"}],
               ["id", "type", "status"])
        c = {"account_id": "demo", "action_id": "A", "integration_id": "CRM", "expected_business_event": "lead",
             "matching_method": "click id", "intended_cadence_hours": "24", "ready_to_submit_sla_hours": "2",
             "processing_expectation_hours": "4", "automation_status": "automated", "owner": "owner"}
        _write(exp / "external" / "offline_pipeline_config.csv", [{**c, **(cfg or {})}], CFG_COLS)
        _write(exp / "external" / "offline_outcomes.csv", outcomes, OUT_COLS)
        files = ["account.csv", "conversion_actions.csv", "external/offline_pipeline_config.csv",
                 "external/offline_outcomes.csv"]
        if with_attempts:
            _write(exp / "external" / "offline_upload_attempts.csv", attempts, ATT_COLS)
            files.append("external/offline_upload_attempts.csv")
        if manifest:
            _write(exp / "table_manifest.csv", [{"filename": f, "completeness": "complete"} for f in files],
                   ["filename", "completeness"])
        return exp

    def run_check(self, exp) -> dict:
        self.assertEqual(main(["run", "--export", str(exp), "--out", str(self.root / "out")]), 0)
        return json.loads((self.root / "out" / "result.json").read_text())

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev is None or f["severity"] == sev)

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    @staticmethod
    def obs(body, check):
        return [o["data"] for o in body["observations"] if o["check"] == check]

    def test_queue_delay_beyond_sla_warns_fast_event_does_not(self):
        body = self.run_check(self.make(
            [outcome("FAST"), outcome("SLOW")],
            [attempt("FAST", "1", "2026-08-20T11:00:00+02:00", "2026-08-20T12:00:00+02:00"),
             attempt("SLOW", "2", "2026-08-23T10:00:00+02:00", "2026-08-23T11:00:00+02:00", batch="B2")]))
        self.assertEqual(self.keys(body, "Warning"), ["sla_breach"])
        breach = next(f for f in body["findings"] if f["condition_key"] == "sla_breach")
        self.assertEqual([b["event_token"] for b in breach["evidence"]["breaches"]], ["SLOW"])

    def test_within_sla_is_clean(self):
        body = self.run_check(self.make([outcome("FAST")],
                                        [attempt("FAST", "1", "2026-08-20T11:00:00+02:00", "2026-08-20T12:00:00+02:00")]))
        self.assertEqual(body["findings"], [])

    def test_unattempted_eligible_breaches_sla_ineligible_ignored(self):
        body = self.run_check(self.make([outcome("LOST"), outcome("NOPE", eligible="False")], []))
        self.assertEqual(self.keys(body, "Warning"), ["sla_breach"])
        breach = body["findings"][0]["evidence"]["breaches"]
        self.assertEqual([(b["event_token"], b["breach"]) for b in breach], [("LOST", "missing_attempt_age")])
        self.assertIn("material_outcome_loss_unattempted", [r["condition_key"] for r in body["ai_review"]])

    def test_rejection_without_retry_warns_successful_retry_does_not(self):
        body = self.run_check(self.make(
            [outcome("R"), outcome("RETRIED")],
            [attempt("R", "1", "2026-08-20T11:00:00+02:00", "2026-08-20T11:30:00+02:00", "REJECTED", code="BAD_ID"),
             attempt("RETRIED", "2", "2026-08-20T11:00:00+02:00", "2026-08-20T11:30:00+02:00", "REJECTED"),
             attempt("RETRIED", "3", "2026-08-20T11:10:00+02:00", "2026-08-20T11:40:00+02:00", retry="2")]))
        rej = [f for f in body["findings"] if f["condition_key"] == "eligible_events_rejected"]
        self.assertEqual(len(rej), 1)
        self.assertEqual([e["event_token"] for e in rej[0]["evidence"]["rejected_events"]], ["R"])
        acc = self.obs(body, "acceptance_rate")[0]
        self.assertEqual((acc["numerator"], acc["denominator"]), (1, 2))

    def test_no_attempts_acceptance_undefined(self):
        body = self.run_check(self.make([outcome("X", eligible="False")], []))
        acc = self.obs(body, "acceptance_rate")[0]
        self.assertIsNone(acc["acceptance_rate"])

    def test_no_eligible_outcomes_info_only_when_complete(self):
        body = self.run_check(self.make([outcome("X", eligible="False")], []))
        self.assertEqual(self.keys(body), ["no_eligible_outcomes"])
        body = self.run_check(self.make([outcome("X", eligible="False")], [], manifest=False))
        self.assertNotIn("no_eligible_outcomes", self.keys(body))
        self.assertEqual(self.cov(body)["no_outcome_explanation"], "partial")

    def test_naive_timestamps_are_partial_not_pass(self):
        body = self.run_check(self.make([outcome("N", ready="2026-08-20T10:00:00", biz="2026-08-20T10:00:00")], []))
        self.assertEqual(self.cov(body)["freshness_delays"], "partial")
        self.assertNotIn("sla_breach", self.keys(body))

    def test_negative_delay_is_data_quality_partial(self):
        body = self.run_check(self.make([outcome("NEG", biz="2026-08-21T10:00:00+02:00")],
                                        [attempt("NEG", "1", "2026-08-20T10:30:00+02:00", "2026-08-20T11:00:00+02:00")]))
        self.assertEqual(self.cov(body)["freshness_delays"], "partial")

    def test_missing_attempts_file_skips_dependent_checks(self):
        body = self.run_check(self.make([outcome("X")], [], with_attempts=False))
        cov = self.cov(body)
        for c in ("outcome_reconciliation", "freshness_delays", "sla_compliance", "acceptance_rate", "batch_cadence"):
            self.assertEqual(cov[c], "skipped")
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_cadence_gap_with_waiting_event_is_info(self):
        body = self.run_check(self.make(
            [outcome("E1"), outcome("E2")],
            [attempt("E1", "1", "2026-08-20T11:00:00+02:00", "2026-08-20T11:30:00+02:00"),
             attempt("E2", "2", "2026-08-22T11:00:00+02:00", "2026-08-22T11:30:00+02:00", batch="B2")],
            cfg={"ready_to_submit_sla_hours": "100"}))
        self.assertEqual(self.keys(body), ["cadence_review"])

    def test_finalize_loss_review_requires_evidence_ref(self):
        exp = self.make([outcome("R")], [attempt("R", "1", "2026-08-20T11:00:00+02:00", "2026-08-20T11:30:00+02:00",
                                                 "REJECTED")])
        body = self.run_check(exp)
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "material_outcome_loss")
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(exp), "--out", str(self.root / "out"), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_loss_evidenced", "rationale": "r"}]))
        self.assertEqual(main(args), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_loss_evidenced", "rationale": "r",
                                    "proposal": {"evidence_ref": "CRM volume report"}}]))
        self.assertEqual(main(args), 0)


PAY_COLS = ["gclid", "gbraid", "wbraid", "conversion_name", "conversion_time", "conversion_value",
            "conversion_currency", "order_id"]
ACT_COLS = ["id", "name", "status", "type", "click_window_days"]
ACTIONS = [{"id": "OFF1", "name": "Offline purchase", "status": "ENABLED", "type": "UPLOAD_CLICKS",
            "click_window_days": "30"},
           {"id": "OFF2", "name": "Paused import", "status": "PAUSED", "type": "UPLOAD_CLICKS", "click_window_days": "30"},
           {"id": "WEB1", "name": "Web purchase", "status": "ENABLED", "type": "WEBSITE", "click_window_days": "30"}]
CLICK = "2026-08-10T10:00:00+02:00"


def prow(gclid="GCLIDSECRETA1", name="Offline purchase", t="2026-08-20 12:00:00+0200", value="10.50", cur="EUR",
         order="", gbraid="", wbraid=""):
    return {"gclid": gclid, "gbraid": gbraid, "wbraid": wbraid, "conversion_name": name, "conversion_time": t,
            "conversion_value": value, "conversion_currency": cur, "order_id": order}


class PayloadValidationTests(unittest.TestCase):
    """upload_payload_validation: opt-in pre-upload checks; row numbers are spreadsheet rows (first data row = 2)."""

    def make(self, payload=None, clicks=None, actions=None, act_cols=ACT_COLS, as_json=False) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        exp = self.root / "export"
        _write(exp / "account.csv", [ACCOUNT], list(ACCOUNT))
        _write(exp / "conversion_actions.csv", ACTIONS if actions is None else actions, act_cols)
        files = ["account.csv", "conversion_actions.csv"]
        if payload is not None and as_json:
            path = exp / "external" / "offline_upload_payload.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
            files.append("external/offline_upload_payload.json")
        elif payload is not None:
            _write(exp / "external" / "offline_upload_payload.csv", payload, PAY_COLS)
            files.append("external/offline_upload_payload.csv")
        if clicks is not None:
            _write(exp / "custom" / "click_ids.csv", [{"click_id": k, "click_time": v} for k, v in clicks.items()],
                   ["click_id", "click_time"])
            files.append("custom/click_ids.csv")
        _write(exp / "table_manifest.csv", [{"filename": f, "completeness": "complete"} for f in files],
               ["filename", "completeness"])
        return exp

    def run_check(self, exp) -> dict:
        self.assertEqual(main(["run", "--export", str(exp), "--out", str(self.root / "out")]), 0)
        return json.loads((self.root / "out" / "result.json").read_text())

    @staticmethod
    def failing(body) -> dict:
        return {f["condition_key"]: f["evidence"]["sample_rows"] for f in body["findings"]
                if f["check"] == "upload_payload_validation"}

    @staticmethod
    def status(body) -> str:
        return next(c["status"] for c in body["coverage"] if c["check"] == "upload_payload_validation")

    def test_valid_payload_has_zero_findings_and_completes(self):
        rows = [prow(), prow(gclid="GCLIDSECRETA2", t="08/21/2026 09:00:00 +0200", value="", cur="", order="ORD1"),
                prow(gclid="GCLIDSECRETA3", t="2026-08-22T09:00:00+02:00", value="0", order="ORD2")]
        body = self.run_check(self.make(rows, {"GCLIDSECRETA1": CLICK, "GCLIDSECRETA2": CLICK,
                                               "GCLIDSECRETA3": CLICK}))
        self.assertEqual(self.failing(body), {})
        self.assertEqual(self.status(body), "completed")
        obs = next(o["data"] for o in body["observations"] if o["check"] == "upload_payload_validation")
        self.assertEqual((obs["rows_total"], obs["click_time_rules"], obs["click_window_rule"]), (3, 3, 3))

    def test_missing_payload_is_skipped_without_findings(self):
        body = self.run_check(self.make(None))
        self.assertEqual(self.status(body), "skipped")
        self.assertEqual(self.failing(body), {})

    def test_click_id_must_be_exactly_one(self):
        body = self.run_check(self.make([prow(), prow(gclid=""), prow(gbraid="GBRAIDSECRET"),
                                         prow(gclid="", gbraid="GB1", wbraid="WB1")]))
        self.assertEqual(self.failing(body)["payload_click_id_count_invalid"], [3, 4, 5])

    def test_action_exact_name_enabled_and_import_type(self):
        body = self.run_check(self.make([prow(), prow(name="offline purchase"), prow(name="Paused import"),
                                         prow(name="Web purchase")]))
        got = self.failing(body)
        self.assertEqual(got["payload_conversion_action_not_found"], [3])
        self.assertEqual(got["payload_conversion_action_not_enabled"], [4])
        self.assertEqual(got["payload_conversion_action_not_import_type"], [5])
        nf = next(f for f in body["findings"] if f["condition_key"] == "payload_conversion_action_not_found")
        self.assertEqual(nf["evidence"]["conversion_names"], ["offline purchase"])
        self.assertEqual(nf["severity"], "Warning")

    def test_missing_action_columns_is_partial_not_finding(self):
        body = self.run_check(self.make([prow(name="Nope")], actions=[{"id": "OFF1"}], act_cols=["id"]))
        self.assertNotIn("payload_conversion_action_not_found", self.failing(body))
        self.assertEqual(self.status(body), "partial")

    def test_conversion_time_needs_documented_offset_format(self):
        body = self.run_check(self.make([prow(), prow(t="2026-08-20 12:00:00"), prow(t="2026-02-30 12:00:00+0200"),
                                         prow(t="2026-08-20T12:00:00Z"), prow(t="2026-08-20 12:00:00+1600"),
                                         prow(t="08/20/2026 12:00:00 -0500"), prow(t="")]))
        self.assertEqual(self.failing(body)["payload_conversion_time_invalid"], [3, 4, 5, 6, 8])

    def test_time_zone_id_is_partial_not_finding(self):
        body = self.run_check(self.make([prow(t="2026-08-20 12:00:00 Europe/Rome")]))
        self.assertEqual(self.failing(body), {})
        self.assertEqual(self.status(body), "partial")

    def test_future_relative_to_snapshot_day_in_row_offset(self):
        body = self.run_check(self.make([prow(t="2026-09-06 23:59:59+0200"), prow(t="2026-09-07 00:00:00+0200")]))
        self.assertEqual(self.failing(body)["payload_conversion_time_in_future"], [3])

    def test_conversion_before_click_and_outside_window(self):
        clicks = {f"GCLIDSECRET{i}": CLICK for i in range(4)}
        body = self.run_check(self.make([
            prow(gclid="GCLIDSECRET0", t="2026-08-10 10:00:00+0200"),   # at click: valid
            prow(gclid="GCLIDSECRET1", t="2026-08-10 09:59:59+0200"),   # before click
            prow(gclid="GCLIDSECRET2", t="2026-09-09 10:00:00+0200"),   # exactly 30 days: valid
            prow(gclid="GCLIDSECRET3", t="2026-09-09 08:00:01+0000")], clicks))  # 30d + 1s (UTC): outside
        got = self.failing(body)
        self.assertEqual(got["payload_conversion_precedes_click"], [3])
        self.assertEqual(got["payload_outside_click_window"], [5])
        win = next(f for f in body["findings"] if f["condition_key"] == "payload_outside_click_window")
        self.assertEqual((win["calculation"]["numerator"], win["calculation"]["denominator"]), (1, 4))

    def test_missing_click_evidence_is_partial_not_finding(self):
        body = self.run_check(self.make([prow(t="2026-08-01 10:00:00+0200")]))
        self.assertEqual(self.failing(body), {})
        self.assertEqual(self.status(body), "partial")
        body = self.run_check(self.make([prow(t="2026-08-01 10:00:00+0200")], {"OTHER": CLICK}))
        self.assertEqual(self.failing(body), {})
        self.assertEqual(self.status(body), "partial")

    def test_unknown_click_window_is_partial(self):
        acts = [{**ACTIONS[0], "click_window_days": ""}]
        body = self.run_check(self.make([prow(t="2026-09-20 10:00:00+0200")], {"GCLIDSECRETA1": CLICK}, acts))
        self.assertNotIn("payload_outside_click_window", self.failing(body))
        self.assertEqual(self.status(body), "partial")

    def test_value_and_currency(self):
        body = self.run_check(self.make([prow(value="0"), prow(value="-1"), prow(value="abc"), prow(value="1,5"),
                                         prow(value="", cur=""), prow(cur="eur"), prow(cur="EURO")]))
        got = self.failing(body)
        self.assertEqual(got["payload_conversion_value_invalid"], [3, 4, 5])
        self.assertEqual(got["payload_conversion_currency_invalid"], [7, 8])

    def test_duplicate_order_ids_and_click_conversions(self):
        body = self.run_check(self.make([
            prow(order="ORDSECRET1"), prow(gclid="GCLIDSECRETB", order="ORDSECRET1"),
            prow(gclid="GCLIDSECRETC", t="2026-08-20 12:00:00+0200", order="ORDSECRET2"),
            prow(gclid="GCLIDSECRETC", t="2026-08-20 10:00:00+0000", order="ORDSECRET3"),  # same instant
            prow(gclid="GCLIDSECRETC", t="2026-08-20 13:00:00+0200", order="ORDSECRET4")]))  # other time: valid
        got = self.failing(body)
        self.assertEqual(got["payload_duplicate_order_id"], [2, 3])
        self.assertEqual(got["payload_duplicate_click_conversion"], [4, 5])

    def test_identifiers_never_appear_in_outputs(self):
        exp = self.make([prow(gclid="GCLIDSECRETXYZ", order="ORDSECRETXYZ"),
                         prow(gclid="GCLIDSECRETXYZ", order="ORDSECRETXYZ"),
                         prow(gclid="", gbraid="GBRAIDSECRETXYZ", wbraid="WBRAIDSECRETXYZ", value="-5")],
                        {"GCLIDSECRETXYZ": "2026-08-25T10:00:00+02:00"})
        body = self.run_check(exp)
        self.assertGreaterEqual(len(self.failing(body)), 4)
        dec = self.root / "d.json"
        dec.write_text("[]")
        self.assertEqual(main(["finalize", "--export", str(exp), "--out", str(self.root / "out"),
                               "--decisions", str(dec)]), 0)
        outputs = sorted(p for p in (self.root / "out").rglob("*") if p.is_file())
        self.assertTrue(any(p.name == "final.json" for p in outputs))
        for p in outputs:
            text = p.read_text()
            for secret in ("GCLIDSECRETXYZ", "ORDSECRETXYZ", "GBRAIDSECRETXYZ", "WBRAIDSECRETXYZ"):
                self.assertNotIn(secret, text, f"{secret} leaked into {p.name}")

    def test_blank_cells_are_absent_not_errors_csv_and_json(self):
        rows = [prow(value="  ", cur="", order=""),
                prow(gclid="GCLIDSECRETB", gbraid="  ", wbraid="", value="", cur="  ", order="  "),
                prow(gclid="GCLIDSECRETC", order=" "),
                prow(gclid="  ", gbraid="", wbraid=" ")]
        for as_json in (False, True):
            with self.subTest(as_json=as_json):
                body = self.run_check(self.make(rows, as_json=as_json))
                self.assertEqual(self.failing(body), {"payload_click_id_count_invalid": [5]})
        dup = [prow(order=" ORD9 "), prow(gclid="GCLIDSECRETB", order="ORD9")]
        body = self.run_check(self.make(dup, as_json=True))
        self.assertEqual(self.failing(body), {"payload_duplicate_order_id": [2, 3]})


if __name__ == "__main__":
    unittest.main()
