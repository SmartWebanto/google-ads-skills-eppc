"""test_check.py — skill-106 boundaries: link identity, auto-tagging, imports, duplicate goals, latency, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-106-ga4-google-ads-integration/tests
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
_spec = importlib.util.spec_from_file_location("check_106", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(root: Path, key: str, rows: list[dict]) -> None:
    p = root / f"{key}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _map(action, source, include, be="purchase", role="secondary", imported="imported", campaign="10"):
    return {"property_id": "P1", "event_name": "purchase", "account_id": "1", "action_id": action,
            "campaign_id": campaign, "business_event_id": be, "source_type": source, "imported_status": imported,
            "primary_for_goal": include, "include_in_conversions": include, "custom_goal_membership": "",
            "intended_bidding_role": role, "counting": "one", "attribution_model": "dda", "lookback_days": "30",
            "date_basis": "interaction", "timezone": "Europe/Rome", "currency": "EUR", "value_basis": "net"}


def base_tables() -> dict:
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "auto_tagging": "enabled",
                     "date_range_start": "2026-08-01", "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10",
                     "conversion_lag_days": "3"}],
        "campaigns": [{"id": "10"}],
        "conversion_actions": [{"id": "A1", "status": "ENABLED"}, {"id": "A2", "status": "ENABLED"}],
        "external/ga4_ads_links": [
            {"property_id": "P1", "account_id": "1", "link_id": "K1", "link_status": "linked",
             "effective_from": "2025-01-01", "ads_personalization_setting": "enabled", "data_sharing_settings": "",
             "auto_tagging_status": "", "intended_flow": "traffic reporting;conversion import;audience activation",
             "expected_latency_hours": "48", "permissions_verified_by_owner": "true", "source_reference": "ga4",
             "owner": "analytics"}],
        "external/ga4_ads_event_mapping": [_map("A1", "website", "true", role="primary"),
                                           _map("A2", "ga4", "false")],
        "external/ga4_ads_flow_checks": [
            {"link_id": "K1", "flow_type": "conversion_import", "entity_id": "A2", "check_id": "q1",
             "tested_at": "2026-09-05T12:00:00", "observation_window_start": "2026-09-01",
             "observation_window_end": "2026-09-05", "expected_behavior": "event imported",
             "observed_behavior": "event imported", "event_or_audience_last_seen": "2026-09-05T00:00:00",
             "parameter_preservation_check": "pass", "destination_property_check": "pass",
             "processing_mature": "true", "diagnostic_code": "", "source_reference": "qa"}],
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

    def test_native_primary_ga4_secondary_is_clean_and_preserved(self):
        body = self.run_check(base_tables())
        self.assertEqual(body["findings"], [])
        obs = next(o for o in body["observations"] if o["text"].startswith("Native primary"))
        self.assertEqual(obs["data"]["business_events"], ["purchase"])

    def test_no_intended_flow_is_not_a_defect(self):
        t = base_tables()
        t["external/ga4_ads_links"][0].update(intended_flow="none", link_status="unlinked")
        self.assertEqual(self.run_check(t)["findings"], [])

    def test_inactive_required_link_warns_unknown_is_info(self):
        t = base_tables()
        t["external/ga4_ads_links"][0]["link_status"] = "unlinked"
        self.assertEqual(len(self.keys(self.run_check(t), "required_link_inactive")), 1)
        t["external/ga4_ads_links"][0]["link_status"] = ""
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "required_link_inactive"))
        self.assertEqual([x["severity"] for x in self.keys(body, "link_state_unknown")], ["Info"])

    def test_other_account_link_is_ignored(self):
        t = base_tables()
        t["external/ga4_ads_links"][0].update(account_id="999", link_status="unlinked")
        self.assertFalse(self.keys(self.run_check(t), "required_link_inactive"))

    def test_auto_tagging_disabled_warns_unknown_partial(self):
        t = base_tables()
        t["external/ga4_ads_links"][0]["auto_tagging_status"] = "disabled"
        self.assertEqual(len(self.keys(self.run_check(t), "auto_tagging_disabled_for_required_flow")), 1)
        t = base_tables()
        t["account"][0]["auto_tagging"] = ""
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "auto_tagging_disabled_for_required_flow"))
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "auto_tagging")["status"], "partial")

    def test_duplicate_bidding_signal_needs_same_business_event_and_inclusion(self):
        t = base_tables()
        t["external/ga4_ads_event_mapping"][1]["include_in_conversions"] = "true"
        f = self.keys(self.run_check(t), "duplicate_bidding_signal")
        self.assertEqual([x["entity"]["business_event_id"] for x in f], ["purchase"])
        t["external/ga4_ads_event_mapping"][1]["business_event_id"] = "lead"
        self.assertFalse(self.keys(self.run_check(t), "duplicate_bidding_signal"))
        t = base_tables()
        t["external/ga4_ads_event_mapping"][1].update(include_in_conversions="true", campaign_id="20")
        self.assertFalse(self.keys(self.run_check(t), "duplicate_bidding_signal"))

    def test_removed_action_does_not_double_count(self):
        t = base_tables()
        t["external/ga4_ads_event_mapping"][1]["include_in_conversions"] = "true"
        t["conversion_actions"][1]["status"] = "REMOVED"
        self.assertFalse(self.keys(self.run_check(t), "duplicate_bidding_signal"))

    def test_required_import_missing(self):
        t = base_tables()
        t["external/ga4_ads_event_mapping"][1].update(intended_bidding_role="primary", imported_status="not_imported")
        self.assertEqual(len(self.keys(self.run_check(t), "required_import_missing")), 1)

    def test_stale_flow_after_latency_boundary(self):
        t = base_tables()
        t["external/ga4_ads_flow_checks"][0]["event_or_audience_last_seen"] = "2026-09-03T12:00:00"  # exactly 48h
        self.assertFalse(self.keys(self.run_check(t), "flow_stale_after_latency"))
        t["external/ga4_ads_flow_checks"][0]["event_or_audience_last_seen"] = "2026-09-03T11:00:00"
        self.assertEqual(len(self.keys(self.run_check(t), "flow_stale_after_latency")), 1)
        t["external/ga4_ads_flow_checks"][0]["processing_mature"] = "false"
        self.assertFalse(self.keys(self.run_check(t), "flow_stale_after_latency"))

    def test_behavior_mismatch_is_review(self):
        t = base_tables()
        t["external/ga4_ads_flow_checks"][0]["observed_behavior"] = "no event"
        body = self.run_check(t)
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["flow_behavior_mismatch"])
        self.assertFalse(body["findings"])

    def test_missing_links_skip(self):
        t = base_tables()
        del t["external/ga4_ads_links"]
        body = self.run_check(t)
        for cid in ("intended_flows", "link_identity", "auto_tagging", "sync_latency"):
            self.assertEqual(next(c for c in body["coverage"] if c["check"] == cid)["status"], "skipped")

    def test_finalize_material_failure_needs_evidence(self):
        t = base_tables()
        t["external/ga4_ads_flow_checks"][0]["observed_behavior"] = "no event"
        root = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = root.parent / "d.json"
        args = ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_failure_evidenced", "rationale": "r"}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "flow_error", "rationale": "r"}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 0)


if __name__ == "__main__":
    unittest.main()
