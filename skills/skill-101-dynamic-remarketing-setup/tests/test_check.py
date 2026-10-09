"""test_check.py — skill-101 boundaries: intent scope, linkage, feed certification, item-ID matching, consent.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-101-dynamic-remarketing-setup/tests
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
_spec = importlib.util.spec_from_file_location("check_101", _CHECK)
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


def _tag(test_id, actual, expected, consent="granted", status="sent", scope="F1"):
    return {"test_id": test_id, "tested_at": "2026-09-01", "page_reference": "pdp", "event_name": "view_item",
            "item_index": "0", "feed_scope": scope, "tag_destination_id": "AW-1", "actual_item_id": actual,
            "expected_item_id": expected, "consent_state": consent, "parameter_names": "items",
            "observed_payload_status": status, "issue": "", "source_reference": "ta-1"}


def base_tables() -> dict:
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}],
        "campaigns": [{"id": "10"}, {"id": "20"}],
        "audiences": [{"list_id": "L1", "campaign_id": "10"}],
        "external/dynamic_configuration": [
            {"campaign_id": "10", "business_vertical": "retail", "intended_dynamic_use": "true",
             "campaign_subtype": "display", "dynamic_status": "enabled", "feed_type": "merchant center",
             "feed_id": "F1", "merchant_id": "555", "linked_account_id": "555", "link_status": "linked",
             "destination": "display", "eligibility": "eligible", "observed_at": "2026-09-05",
             "source_reference": "ui"},
            {"campaign_id": "20", "business_vertical": "retail", "intended_dynamic_use": "false",
             "campaign_subtype": "display", "dynamic_status": "disabled", "feed_type": "", "feed_id": "",
             "merchant_id": "", "linked_account_id": "", "link_status": "", "destination": "", "eligibility": "",
             "observed_at": "2026-09-05", "source_reference": "ui"}],
        "external/dynamic_feed_items": [
            {"feed_id": "F1", "item_id": "SKU-1", "item_group_id": "G-1", "availability": "in stock",
             "eligibility_status": "eligible", "snapshot_at": "2026-09-05"},
            {"feed_id": "F1", "item_id": "SKU-2", "item_group_id": "G-1", "availability": "out of stock",
             "eligibility_status": "disapproved", "snapshot_at": "2026-09-05"}],
        "external/dynamic_tag_diagnostics": [_tag("t1", "SKU-1", "SKU-1")],
        "external/audience_definitions": [{"list_id": "L1", "source_id": "S1"}],
        "external/activation_permissions": [
            {"source_id": "S1", "list_id": "", "permission_status": "granted", "consent_coverage_status": "covered",
             "permitted_destinations": "google_ads", "evidence_reference": "p-1"}],
    }


class CheckTests(unittest.TestCase):
    def build(self, tables: dict, complete=True) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        for key, rows in tables.items():
            _write(root, key, rows)
        _write(root, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete" if complete else ""}
                                        for k in tables])
        return root

    def run_check(self, tables: dict, complete=True) -> dict:
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.build(tables, complete), None).finish()

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    def test_correct_path_and_static_campaign_are_clean(self):
        body = self.run_check(base_tables())
        self.assertEqual([f for f in body["findings"] if f["severity"] != "Info"], [])
        self.assertFalse([f for f in body["findings"] if f["entity"].get("campaign_id") == "20"])

    def test_merchant_id_does_not_certify_link(self):
        t = base_tables()
        t["external/dynamic_configuration"][0]["link_status"] = ""
        f = self.keys(self.run_check(t), "setup_not_certified")
        self.assertEqual([x["severity"] for x in f], ["Info"])

    def test_broken_link_and_account_mismatch_warn(self):
        t = base_tables()
        t["external/dynamic_configuration"][0].update(link_status="unlinked", linked_account_id="999")
        body = self.run_check(t)
        self.assertEqual(len(self.keys(body, "link_not_active")), 1)
        self.assertEqual(len(self.keys(body, "linked_account_mismatch")), 1)

    def test_empty_feed_needs_certified_completeness(self):
        t = base_tables()
        t["external/dynamic_configuration"][0]["feed_id"] = "F9"
        self.assertEqual(len(self.keys(self.run_check(t), "feed_has_no_items")), 1)
        self.assertFalse(self.keys(self.run_check(t, complete=False), "feed_has_no_items"))

    def test_no_eligible_items_warns(self):
        t = base_tables()
        t["external/dynamic_feed_items"][0]["eligibility_status"] = "disapproved"
        self.assertEqual(len(self.keys(self.run_check(t), "feed_no_eligible_items")), 1)

    def test_item_id_boundaries(self):
        t = base_tables()
        t["external/dynamic_tag_diagnostics"] = [_tag("t1", "SKU-2", "SKU-1"), _tag("t2", "G-1", "SKU-1"),
                                                 _tag("t3", "SKU-X", "SKU-X"), _tag("t4", "", "SKU-1"),
                                                 _tag("t5", "sku-1", "SKU-1")]
        body = self.run_check(t)
        got = sorted((f["entity"]["test_id"], f["condition_key"]) for f in body["findings"]
                     if f["check"] == "item_id_match")
        self.assertEqual(got, [("t1", "wrong_item_or_variant"), ("t2", "parent_id_sent"),
                               ("t3", "unmapped_item_id"), ("t4", "item_id_missing_in_payload")])
        self.assertTrue([r for r in body["ai_review"] if r["condition_key"] == "case_only_match"])
        obs = next(o for o in body["observations"] if o["text"] == "Sampled item-ID matching")
        self.assertEqual((obs["data"]["tested_rows"], obs["data"]["mismatched_rows"]), (5, 5))

    def test_consent_denied_payload_goes_to_critical_review(self):
        t = base_tables()
        t["external/dynamic_tag_diagnostics"].append(_tag("t9", "SKU-1", "SKU-1", consent="denied"))
        body = self.run_check(t)
        items = [r for r in body["ai_review"] if r["condition_key"] == "consent_denied_payload"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["outcomes"]["unsafe_use_evidenced"]["severity"], "Critical")
        self.assertFalse([f for f in body["findings"] if f["severity"] == "Critical"])

    def test_correction_blocked_without_permission(self):
        t = base_tables()
        t["external/dynamic_configuration"][0]["dynamic_status"] = "disabled"
        self.assertFalse(self.keys(self.run_check(t), "correction_blocked_permission"))
        t["external/activation_permissions"][0]["permission_status"] = "revoked"
        self.assertEqual(len(self.keys(self.run_check(t), "correction_blocked_permission")), 1)

    def test_missing_configuration_skips_everything(self):
        t = base_tables()
        del t["external/dynamic_configuration"]
        body = self.run_check(t)
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))
        self.assertEqual(body["findings"], [])

    def test_empty_actual_and_expected_is_not_a_mismatch(self):
        t = base_tables()
        t["external/dynamic_tag_diagnostics"] = [_tag("t1", "", "")]
        obs = next(o for o in self.run_check(t)["observations"] if o["text"] == "Sampled item-ID matching")
        self.assertEqual(obs["data"]["mismatched_rows"], 0)

    def test_finalize_critical_needs_evidence_ref(self):
        t = base_tables()
        t["external/dynamic_configuration"][0]["dynamic_status"] = "disabled"
        root = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        item = next(r for r in json.loads((out / "result.json").read_text())["ai_review"]
                    if r["condition_key"] == "dynamic_disabled")
        dec = root.parent / "d.json"
        args = ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_block_evidenced", "rationale": "r"}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "not_material", "rationale": "r"}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "dynamic_disabled"],
                         ["Warning"])


if __name__ == "__main__":
    unittest.main()
