"""test_check.py — skill-099 boundaries: platform bounds, approved window, retention breach, cohort gates, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-099-membership-duration-optimization/tests
rules:   stdlib only; temp folders; never read the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial tests
"""
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_099", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

MATURE = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
          "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}


def _write(root: Path, key: str, rows: list[dict]) -> None:
    p = root / f"{key}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _cohort(bucket, elig, outc, mature="true"):
    return {"list_id": "L1", "entry_cohort_start": "2025-01-01", "age_since_entry_bucket": bucket,
            "business_segment": "tools", "eligible_people": elig, "qualified_outcomes": outc, "maturity": mature,
            "observation_end": "2026-08-30"}


def base_tables() -> dict:
    return {
        "account": [dict(MATURE)],
        "audiences": [{"list_id": "L1", "campaign_id": "10"}, {"list_id": "L2", "campaign_id": ""}],
        "external/membership_controls": [
            {"list_id": "L1", "source_platform": "Google Ads", "observed_duration": "30", "units": "days",
             "allowed_min": "1", "allowed_max": "540", "nonexpiring_special_value": "", "reset_behavior":
             "resets on qualifying visit", "retention_constraint": "", "intended_role": "retention targeting",
             "approved_duration": "", "checked_at": "2026-09-01", "source_reference": "ui-1"},
            {"list_id": "L2", "source_platform": "Google Ads", "observed_duration": "30", "units": "days",
             "allowed_min": "1", "allowed_max": "540", "nonexpiring_special_value": "", "reset_behavior": "resets",
             "retention_constraint": "", "intended_role": "acquisition suppression", "approved_duration": "",
             "checked_at": "2026-09-01", "source_reference": "ui-2"}],
        "external/audience_definitions": [
            {"list_id": "L1", "source_id": "S1", "entry_event": "purchase", "refresh_behavior": "rolling"},
            {"list_id": "L2", "source_id": "S1", "entry_event": "view_item", "refresh_behavior": "rolling"}],
        "external/audience_age_cohorts": [_cohort("0-30", "1000", "40"), _cohort("31-90", "900", "30"),
                                           _cohort("91-180", "800", "20")],
        "external/customer_lifecycle": [{"business_segment": "tools", "buying_cycle": "14", "repurchase_interval":
                                         "60", "units": "days", "observation_horizon_days": "365",
                                         "maturity": "true"}],
        "external/activation_permissions": [
            {"source_id": "S1", "list_id": "", "permission_status": "granted", "consent_coverage_status": "covered",
             "permitted_destinations": "google_ads", "retention_limit_days": "365", "evidence_reference": "p-1"}],
    }


class CheckTests(unittest.TestCase):
    def build(self, tables: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        for key, rows in tables.items():
            _write(root, key, rows)
        _write(root, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        return root

    def run_check(self, tables: dict) -> dict:
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.build(tables), None).finish()

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    def test_identical_durations_are_not_findings(self):
        body = self.run_check(base_tables())
        self.assertEqual([f for f in body["findings"] if f["severity"] != "Info"], [])
        self.assertTrue(any("Identical durations" in o["text"] for o in body["observations"]))

    def test_outside_platform_bounds_warns_but_nonexpiring_does_not(self):
        t = base_tables()
        t["external/membership_controls"][0]["observed_duration"] = "600"
        self.assertEqual([f["entity"]["list_id"] for f in self.keys(self.run_check(t), "outside_platform_bounds")],
                         ["L1"])
        t["external/membership_controls"][0]["nonexpiring_special_value"] = "600"
        self.assertFalse(self.keys(self.run_check(t), "outside_platform_bounds"))

    def test_approved_duration_mismatch_warns(self):
        t = base_tables()
        t["external/membership_controls"][1]["approved_duration"] = "14"
        f = self.keys(self.run_check(t), "approved_duration_mismatch")
        self.assertEqual([(x["entity"]["list_id"], x["severity"]) for x in f], [("L2", "Warning")])

    def test_retention_breach_critical_only_with_active_use(self):
        t = base_tables()
        t["external/membership_controls"][0]["observed_duration"] = "400"
        t["external/membership_controls"][1]["observed_duration"] = "400"
        body = self.run_check(t)
        self.assertEqual([x["entity"]["list_id"] for x in self.keys(body, "retention_violation_active_use")], ["L1"])
        self.assertEqual([x["entity"]["list_id"] for x in self.keys(body, "retention_violation")], ["L2"])
        t["external/membership_controls"][0]["observed_duration"] = "365"
        self.assertFalse(self.keys(self.run_check(t), "retention_violation_active_use"))

    def test_weeks_convert_exactly(self):
        t = base_tables()
        t["external/membership_controls"][0].update(observed_duration="53", units="weeks", allowed_max="100")
        self.assertTrue(self.keys(self.run_check(t), "retention_violation_active_use"))  # 371 days > 365

    def test_cohort_review_needs_both_sides_and_maturity(self):
        body = self.run_check(base_tables())
        self.assertEqual([r["entity"]["list_id"] for r in body["ai_review"]], ["L1"])
        t = base_tables()
        t["external/audience_age_cohorts"][1]["qualified_outcomes"] = "5"
        t["external/audience_age_cohorts"][2]["qualified_outcomes"] = "5"  # beyond side 10 < 15
        body = self.run_check(t)
        self.assertFalse(body["ai_review"])
        self.assertTrue(self.keys(body, "cohort_evidence_insufficient"))
        t = base_tables()
        t["account"][0]["snapshot_date"] = "2026-08-31"  # 1 day < lag 3
        body = self.run_check(t)
        self.assertFalse(body["ai_review"])
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "age_outcomes")["status"], "partial")

    def test_immature_cohort_rows_do_not_count(self):
        t = base_tables()
        for r in t["external/audience_age_cohorts"][1:]:
            r["maturity"] = "false"
        body = self.run_check(t)
        self.assertFalse(body["ai_review"])
        self.assertTrue(self.keys(body, "cohort_evidence_insufficient"))

    def test_zero_eligible_is_undefined_rate(self):
        t = base_tables()
        t["external/audience_age_cohorts"] = [_cohort("0-30", "0", "0"), _cohort("31-90", "0", "0")]
        body = self.run_check(t)
        obs = next(o for o in body["observations"] if o["text"].startswith("List L1: outcomes"))
        self.assertIsNone(obs["data"]["rate_within"])

    def test_missing_controls_skip_everything(self):
        t = base_tables()
        del t["external/membership_controls"]
        body = self.run_check(t)
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))
        self.assertEqual(body["findings"], [])

    def test_unknown_reset_semantics_is_info(self):
        t = base_tables()
        t["external/membership_controls"][1]["reset_behavior"] = ""
        t["external/audience_definitions"][1]["refresh_behavior"] = ""
        f = self.keys(self.run_check(t), "reset_semantics_unresolved")
        self.assertEqual([(x["entity"]["list_id"], x["severity"]) for x in f], [("L2", "Info")])

    def finalize(self, t, proposal, outcome="window_mismatch"):
        root = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = root.parent / "d.json"
        dec.write_text(json.dumps([{"id": item["id"], "outcome": outcome, "rationale": "r", "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", "--export", str(root), "--out",
                                                                   str(out), "--decisions", str(dec)])

    def test_verify_bounds_retention_horizon_and_permission(self):
        self.assertEqual(self.finalize(base_tables(), {"durations": [60, 90]}), 0)
        self.assertEqual(self.finalize(base_tables(), {"durations": [200]}), 4)  # beyond 180-day horizon
        t = base_tables()
        t["external/activation_permissions"][0]["permission_status"] = "pending"
        self.assertEqual(self.finalize(t, {"durations": [60]}), 4)  # extension without permission
        self.assertEqual(self.finalize(t, {"durations": [20]}), 0)  # shortening needs no permission
        self.assertEqual(self.finalize(base_tables(), {"durations": [60]}, "duration_test"), 4)  # no rollback


if __name__ == "__main__":
    unittest.main()
