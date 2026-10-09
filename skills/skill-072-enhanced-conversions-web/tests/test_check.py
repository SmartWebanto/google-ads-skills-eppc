"""test_check.py — Decision-boundary tests for skill-072 Enhanced Conversions for Web.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-072-enhanced-conversions-web/tests -t skills/skill-072-enhanced-conversions-web
rules:   Temp folders only; pins Web-vs-Leads separation, trace severities, gates and verify(), never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial tests
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
_spec = importlib.util.spec_from_file_location("check_072", _PATH)
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


CONFIG = {"account_id": "1", "conversion_customer_id": "1", "action_id": "W1", "snapshot": "2026-09-06",
          "web_enabled": "true", "action_web_status": "ACTIVE", "implementation_method": "Google tag automatic",
          "tag_destination_id": "d1", "supported_identifier_types": "email", "consent_policy_reference": "p",
          "owner": "qa"}


def _diag(start, end, num, den, status="ACTIVE_NO_ISSUES", code="NONE", mature="true"):
    return {"account_id": "1", "action_id": "W1", "window_start": start, "window_end": end,
            "implementation_method": "Google tag automatic", "eligible_events": den, "enhanced_events": num,
            "accepted_events": num, "diagnostic_code": code, "diagnostic_status": status,
            "metric_name": "accepted_eligible_events", "metric_numerator": num, "metric_denominator": den,
            "processing_mature": mature, "source_reference": "diag"}


def _trace(tid, scenario="valid", dest="true", norm="PASS", hashing="PASS", dup=0, observed="matches expected behavior",
           presence="email only"):
    return {"test_id": tid, "action_id": "W1", "scenario": scenario, "step": 1, "tested_at": "2026-09-06",
            "deployment_version": "v1", "browser_class": "Chromium", "consent_state": "granted",
            "event_trigger": "purchase", "destination_correct": dest, "identifier_type_presence": presence,
            "normalization_check": norm, "hashing_method": "automatic", "hashing_check": hashing,
            "duplicate_send_count": dup, "expected_behavior": "one enhanced request", "observed_behavior": observed,
            "trace_reference": f"trace-{tid}"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, config=(CONFIG,), diag=(), traces=(), leads_flag="false"):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
                                       "enhanced_conversions_for_leads_enabled": leads_flag}])
        _write(root / "conversion_actions.csv", [{"id": "W1", "conversion_customer_id": "1", "name": "Purchase",
                                                  "status": "ENABLED", "type": "WEBSITE"}])
        files = ["conversion_actions.csv"]
        for key, rows in (("external/enhanced_web_config.csv", config), ("external/enhanced_web_diagnostics.csv", diag),
                          ("external/enhanced_web_traces.csv", traces)):
            if rows:
                _write(root / key, list(rows))
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
    def test_healthy_web_with_leads_off_is_clean(self):
        body = self.build(diag=[_diag("2026-08-01", "2026-08-30", 100, 100)], traces=[_trace("T1")])
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["ai_review"], [])

    def test_web_off_is_info_never_warning(self):
        body = self.build(config=[dict(CONFIG, web_enabled="false")])
        self.assertEqual([f["severity"] for f in self.found(body, "web_not_adopted")], ["Info"])

    def test_leads_flag_is_not_web_evidence(self):
        body = self.build(config=(), leads_flag="true")
        self.assertEqual(self.status(body, "web_settings"), "skipped")
        self.assertEqual(body["findings"], [])

    def test_unknown_setting_is_info(self):
        body = self.build(config=[dict(CONFIG, web_enabled="")])
        self.assertEqual([f["severity"] for f in self.found(body, "web_settings_unknown")], ["Info"])


class Traces(Base):
    def test_wrong_destination_is_warning(self):
        body = self.build(traces=[_trace("T1", dest="false")])
        self.assertEqual([f["severity"] for f in self.found(body, "incorrect_routing")], ["Warning"])

    def test_hashing_failure_is_warning_unknown_is_partial(self):
        body = self.build(traces=[_trace("T1", hashing="FAIL")])
        self.assertEqual([f["severity"] for f in self.found(body, "hashing_or_normalization_failure")], ["Warning"])
        body = self.build(traces=[_trace("T1", hashing="")])
        self.assertEqual(self.found(body, "hashing_or_normalization_failure"), [])
        self.assertEqual(self.status(body, "trace_normalization_hashing"), "partial")

    def test_optional_identifier_absence_is_not_reviewed(self):
        body = self.build(traces=[_trace("T1", presence="email only; phone and name absent")])
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "identifier_missing"], [])
        body = self.build(traces=[_trace("T1", presence="none")])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["identifier_missing"])

    def test_behavior_mismatch_is_reviewed(self):
        body = self.build(traces=[_trace("T1", scenario="deny", observed="enhanced request sent after deny")])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["trace_behavior_mismatch"])

    def finalize(self, outcome, proposal):
        body = self.build(traces=[_trace("T1", scenario="repeated", dup=1)])
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "duplicate_send")
        dec = self.dir / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "r", "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_duplicate_send_critical_needs_impact(self):
        code, final = self.finalize("material_measurement_failure", {"evidence_ref": "trace-T1"})
        self.assertEqual((code, final["counts"]["Critical"]), (4, 0))
        code, final = self.finalize("material_measurement_failure", {"evidence_ref": "trace-T1", "impact_ref": "rec-9"})
        self.assertEqual((code, final["counts"]["Critical"]), (0, 1))


class Diagnostics(Base):
    def test_mature_drop_with_samples_is_reviewed(self):
        body = self.build(diag=[_diag("2026-07-01", "2026-07-31", 95, 100), _diag("2026-08-01", "2026-08-30", 60, 100)])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["diagnostic_deterioration"])

    def test_small_or_immature_windows_are_not_compared(self):
        body = self.build(diag=[_diag("2026-07-01", "2026-07-31", 9, 10), _diag("2026-08-01", "2026-08-30", 2, 10)])
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.status(body, "diagnostics_trend"), "partial")
        body = self.build(diag=[_diag("2026-07-01", "2026-07-31", 95, 100),
                                _diag("2026-08-01", "2026-08-30", 60, 100, mature="false")])
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "diagnostic_deterioration"], [])

    def test_unhealthy_status_is_reviewed(self):
        body = self.build(diag=[_diag("2026-08-01", "2026-08-30", 50, 100, status="NEEDS_ATTENTION", code="HASH_ERR")])
        self.assertIn("diagnostic_issue", [r["condition_key"] for r in body["ai_review"]])


if __name__ == "__main__":
    unittest.main()
