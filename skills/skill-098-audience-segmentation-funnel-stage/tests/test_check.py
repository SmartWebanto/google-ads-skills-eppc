"""test_check.py — skill-098 decision boundaries: literal stage mapping, gaps, permission gate, Critical verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-098-audience-segmentation-funnel-stage/tests
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
_spec = importlib.util.spec_from_file_location("check_098", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402  (path inserted by check.py bootstrap)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}


def _write(root: Path, key: str, rows: list[dict]) -> None:
    p = root / f"{key}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0])
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def base_tables() -> dict:
    return {
        "account": [ACCOUNT],
        "campaigns": [{"id": "10", "name": "Search"}, {"id": "20", "name": "Display"}],
        "ad_groups": [{"id": "100", "campaign_id": "10"}, {"id": "200", "campaign_id": "20"}],
        "audiences": [{"list_id": "L1"}, {"list_id": "L2"}, {"list_id": "L3"}],
        "custom/audience_associations": [
            {"campaign_id": "10", "ad_group_id": "", "criterion_id": "c1", "list_id": "L1", "mode": "observation",
             "association_status": "ENABLED", "inventory_complete": "true"},
            {"campaign_id": "20", "ad_group_id": "", "criterion_id": "c2", "list_id": "L2", "mode": "targeting",
             "association_status": "ENABLED", "inventory_complete": "true"}],
        "external/audience_definitions": [
            {"list_id": "L1", "source_id": "S1", "definition_expression": "event=view_item", "entry_event": "view_item",
             "exclusions": "", "linkage_status": "active", "membership_duration_days": "30",
             "last_successful_refresh_at": "2026-09-01", "evidence_reference": "am-1"},
            {"list_id": "L2", "source_id": "S1", "definition_expression": "event=begin_checkout",
             "entry_event": "begin_checkout", "exclusions": "", "linkage_status": "active",
             "membership_duration_days": "", "last_successful_refresh_at": "", "evidence_reference": "am-2"}],
        "external/funnel_plan": [
            {"business_segment": "tools", "funnel_stage": "consideration", "campaign_id": "10", "ad_group_id": "",
             "qualifying_events": "view_item", "desired_message": "range", "deliberate_overlap": "false",
             "available_event_source": "S1", "business_priority": "1", "owner": "mkt"},
            {"business_segment": "tools", "funnel_stage": "intent", "campaign_id": "20", "ad_group_id": "",
             "qualifying_events": "begin_checkout", "desired_message": "offer", "deliberate_overlap": "false",
             "available_event_source": "S1", "business_priority": "1", "owner": "mkt"}],
        "external/customer_lifecycle": [{"business_segment": "tools", "buying_cycle": "7-21 days"}],
        "external/activation_permissions": [
            {"source_id": "S1", "list_id": "", "permission_status": "granted", "consent_coverage_status": "covered",
             "permitted_destinations": "google_ads", "evidence_reference": "perm-1"}],
    }


class CheckTests(unittest.TestCase):
    def build(self, tables: dict, complete: bool = True) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        for key, rows in tables.items():
            _write(root, key, rows)
        _write(root, "table_manifest", [{"filename": f"{k}.csv",
                                         "completeness": "complete" if complete else "partial"} for k in tables])
        return root

    def run_check(self, tables: dict, complete: bool = True) -> dict:
        ctx = cli.run_once(M.SKILL, M.VERSION, M.run, self.build(tables, complete), None)
        return ctx.finish()

    @staticmethod
    def cov(body, cid):
        return next(c for c in body["coverage"] if c["check"] == cid)

    def test_consistent_journey_has_no_contradiction(self):
        body = self.run_check(base_tables())
        self.assertEqual([f for f in body["findings"] if f["severity"] != "Info"], [])
        self.assertFalse([r for r in body["ai_review"] if r["condition_key"] == "stage_targeting_contradiction"])
        self.assertEqual(self.cov(body, "role_vs_intent")["status"], "completed")

    def test_list_used_outside_its_stage_goes_to_review(self):
        t = base_tables()
        t["custom/audience_associations"][1]["list_id"] = "L1"  # consideration list targeted in intent campaign
        body = self.run_check(t)
        items = [r for r in body["ai_review"] if r["condition_key"] == "stage_targeting_contradiction"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["entity"]["campaign_id"], "20")
        self.assertEqual(items[0]["outcomes"]["contradiction"]["severity"], "Warning")

    def test_deliberate_overlap_is_preserved(self):
        t = base_tables()
        t["custom/audience_associations"][1]["list_id"] = "L1"
        t["external/funnel_plan"][1]["deliberate_overlap"] = "true"
        body = self.run_check(t)
        self.assertFalse([r for r in body["ai_review"] if r["condition_key"] == "stage_targeting_contradiction"])

    def test_names_never_classify_a_list(self):
        t = base_tables()
        t["external/audience_definitions"][1].update(definition_expression="", entry_event="")
        body = self.run_check(t)
        f = [x for x in body["findings"] if x["condition_key"] == "definition_unavailable"]
        self.assertEqual([x["entity"]["list_id"] for x in f], ["L2"])
        self.assertEqual(f[0]["severity"], "Info")

    def test_unmapped_linked_list_needs_review(self):
        t = base_tables()
        t["external/audience_definitions"][1]["entry_event"] = "page_view"
        body = self.run_check(t)
        self.assertTrue([r for r in body["ai_review"] if r["condition_key"] == "stage_mapping_contradiction"])

    def test_missing_segment_opportunity_needs_permission(self):
        t = base_tables()
        t["custom/audience_associations"] = t["custom/audience_associations"][:1]
        body = self.run_check(t)
        f = [x for x in body["findings"] if x["condition_key"] == "optional_segment_opportunity"]
        self.assertEqual([x["entity"]["funnel_stage"] for x in f], ["intent"])
        t["external/activation_permissions"][0]["consent_coverage_status"] = "unknown"
        body = self.run_check(t)
        self.assertFalse([x for x in body["findings"] if x["condition_key"] == "optional_segment_opportunity"])
        self.assertTrue([x for x in body["findings"] if x["condition_key"] == "segment_proposal_blocked"])

    def test_incomplete_association_inventory_blocks_gap_claims(self):
        t = base_tables()
        t["custom/audience_associations"] = t["custom/audience_associations"][:1]
        t["custom/audience_associations"][0]["inventory_complete"] = ""
        body = self.run_check(t)
        self.assertFalse([x for x in body["findings"] if x["condition_key"] in
                          ("optional_segment_opportunity", "segment_proposal_blocked")])
        self.assertEqual(self.cov(body, "journey_gaps")["status"], "partial")

    def test_unavailable_event_source_is_info_not_opportunity(self):
        t = base_tables()
        t["custom/audience_associations"] = t["custom/audience_associations"][:1]
        t["external/funnel_plan"][1]["available_event_source"] = "none"
        body = self.run_check(t)
        self.assertEqual([x["condition_key"] for x in body["findings"] if x["entity"].get("funnel_stage") == "intent"],
                         ["stage_event_unavailable"])

    def test_missing_evidence_skips_not_passes(self):
        t = base_tables()
        del t["external/funnel_plan"]
        body = self.run_check(t)
        for cid in ("definition_mapping", "role_vs_intent", "journey_gaps"):
            self.assertEqual(self.cov(body, cid)["status"], "skipped", cid)
        self.assertIn("external/funnel_plan (file)", self.cov(body, "definition_mapping")["missing"])
        self.assertEqual(body["findings"], [])

    def test_critical_requires_evidence_ref_on_finalize(self):
        t = base_tables()
        t["external/audience_definitions"][1]["linkage_status"] = "failed"
        root = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                      ["run", "--export", str(root), "--out", str(out)]), 0)
        body = json.loads((out / "result.json").read_text())
        item = next(r for r in body["ai_review"] if r["condition_key"] == "definition_linkage_error")
        dec = root.parent / "d.json"
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_block_evidenced", "rationale": "x"}]))
        args = ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_block_evidenced", "rationale": "x",
                                    "proposal": {"evidence_ref": "delivery-diag-7"}}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "definition_linkage_error"],
                         ["Critical"])


if __name__ == "__main__":
    unittest.main()
