"""test_check.py — skill-105 boundaries: provenance, event absence, processing window, plan (index #111), verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-105-ga4-advanced-audiences/tests
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
_spec = importlib.util.spec_from_file_location("check_105", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

PROFILE = """ga4_audience_processing_days: 2
ga4_audience_plan:
  - {property_id: P1, ga4_audience_id: A1, membership_days: 30, destination_account_id: 1}
"""


def _write(root: Path, key: str, rows: list[dict]) -> None:
    p = root / f"{key}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def base_tables() -> dict:
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}],
        "campaigns": [{"id": "10"}],
        "audiences": [{"list_id": "U1", "campaign_id": "10", "mode": "observation"},
                      {"list_id": "U9", "campaign_id": "10", "mode": "observation"}],
        "external/ga4_audience_definitions": [
            {"property_id": "P1", "ga4_audience_id": "A1", "definition_expression": "view_item within 30d",
             "expected_event_names": "view_item", "membership_days": "30", "created_at": "2026-07-01",
             "predictive_eligibility_status": "", "intended_use": "observation", "campaign_objective": "sales",
             "privacy_restriction": "", "owner": "analytics"}],
        "external/ga4_audience_sync": [
            {"property_id": "P1", "ga4_audience_id": "A1", "account_id": "1", "user_list_id": "U1", "link_id": "k1",
             "source_property_verified": "true", "destination_account_verified": "true",
             "ads_personalization_setting": "enabled", "sync_status": "active", "last_observed_sync": "2026-09-01",
             "search_size": "0", "display_size": "0", "eligibility_by_network": "search;display",
             "suppression_status": "", "source_reference": "am"}],
        "external/ga4_event_availability": [
            {"property_id": "P1", "event_name": "view_item", "window_start": "2026-08-01", "window_end": "2026-08-30",
             "event_count": "5400", "required_parameter_presence_rate": "0.98", "consent_scope": "granted",
             "processing_mature": "true", "source_reference": "ga4"}],
    }


class CheckTests(unittest.TestCase):
    def build(self, tables: dict, profile: str = PROFILE) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        for key, rows in tables.items():
            _write(root, key, rows)
        _write(root, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        prof = Path(tmp.name) / "profile.yaml"
        prof.write_text(profile)
        return root, prof

    def run_check(self, tables: dict, profile: str = PROFILE) -> dict:
        root, prof = self.build(tables, profile)
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, prof).finish()

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    def test_healthy_intended_audience_and_zero_size_are_clean(self):
        body = self.run_check(base_tables())
        self.assertEqual(body["findings"], [])
        prov = next(o for o in body["observations"] if o["text"] == "GA4 provenance")["data"]
        self.assertEqual((prov["verified_ga4_lists"], prov["unknown_origin_lists"]), (["U1"], ["U9"]))

    def test_unverified_source_property_is_not_ga4_origin(self):
        t = base_tables()
        t["external/ga4_audience_sync"][0]["source_property_verified"] = ""
        prov = next(o for o in self.run_check(t)["observations"] if o["text"] == "GA4 provenance")["data"]
        self.assertEqual(prov["verified_ga4_lists"], [])

    def test_mature_zero_event_warns_but_missing_row_is_info(self):
        t = base_tables()
        t["external/ga4_event_availability"][0]["event_count"] = "0"
        self.assertEqual(len(self.keys(self.run_check(t), "expected_event_absent")), 1)
        t["external/ga4_event_availability"][0]["processing_mature"] = "false"
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "expected_event_absent"))
        self.assertEqual(len(self.keys(body, "event_evidence_incomplete")), 1)

    def test_parameters_never_present_warns(self):
        t = base_tables()
        t["external/ga4_event_availability"][0]["required_parameter_presence_rate"] = "0"
        self.assertEqual(len(self.keys(self.run_check(t), "required_parameter_absent")), 1)

    def test_sync_failure_needs_elapsed_processing_window(self):
        t = base_tables()
        t["external/ga4_audience_sync"][0]["sync_status"] = "failed"
        self.assertEqual(len(self.keys(self.run_check(t), "sync_failed")), 1)
        t["external/ga4_audience_definitions"][0]["created_at"] = "2026-08-29"  # +2d = 08-31 > as_of 08-30
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "sync_failed"))
        self.assertTrue(self.keys(body, "sync_pending_or_unknown"))
        body = self.run_check(base_tables() | {"external/ga4_audience_sync": [
            dict(base_tables()["external/ga4_audience_sync"][0], sync_status="failed")]}, profile="")
        self.assertFalse(self.keys(body, "sync_failed"))

    def test_not_synced_intended_audience_warns_only_when_certified(self):
        t = base_tables()
        t["external/ga4_audience_sync"][0]["account_id"] = "2"
        body = self.run_check(t)
        self.assertEqual(len(self.keys(body, "intended_audience_not_synced")), 1)
        self.assertTrue([r for r in body["ai_review"] if r["condition_key"] == "intended_audience_not_synced"])

    def test_not_intended_audience_is_not_a_defect(self):
        t = base_tables()
        t["external/ga4_audience_definitions"][0]["intended_use"] = "none"
        t["external/ga4_audience_sync"][0]["account_id"] = "2"
        body = self.run_check(t, profile="")
        self.assertEqual(body["findings"], [])

    def test_plan_mismatch_provisional_info_and_missing_planned_audience(self):
        t = base_tables()
        t["external/ga4_audience_definitions"][0]["membership_days"] = "540"
        body = self.run_check(t)
        f = self.keys(body, "planned_definition_differs")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertEqual([r["provisional_finding"] for r in body["ai_review"]], [f[0]["id"]])
        profile = PROFILE + "  - {property_id: P1, ga4_audience_id: A2, membership_days: 7}\n"
        self.assertEqual(len(self.keys(self.run_check(base_tables(), profile), "planned_audience_missing")), 1)

    def test_plan_for_other_account_is_ignored(self):
        profile = PROFILE.replace("destination_account_id: 1", "destination_account_id: 99")
        t = base_tables()
        t["external/ga4_audience_definitions"][0]["membership_days"] = "540"
        self.assertFalse(self.keys(self.run_check(t, profile), "planned_definition_differs"))

    def test_missing_definitions_skip(self):
        t = base_tables()
        del t["external/ga4_audience_definitions"]
        body = self.run_check(t)
        for cid in ("activation_intent", "definition_events", "sync_eligibility"):
            self.assertEqual(next(c for c in body["coverage"] if c["check"] == cid)["status"], "skipped")

    def test_finalize_plan_mismatch_replaces_provisional(self):
        t = base_tables()
        t["external/ga4_audience_definitions"][0]["membership_days"] = "540"
        root, prof = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--profile", str(prof),
                                                            "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = root.parent / "d.json"
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "definition_mismatch", "rationale": "plan approved"}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                      ["finalize", "--export", str(root), "--profile", str(prof), "--out", str(out),
                                       "--decisions", str(dec)]), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "planned_definition_differs"],
                         ["Warning"])


if __name__ == "__main__":
    unittest.main()
