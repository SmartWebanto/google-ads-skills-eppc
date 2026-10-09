"""test_check.py — skill-100 boundaries: mode vs reach, eligibility, inert modifiers, gated comparisons, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-100-rlsa-campaign-strategy/tests
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
_spec = importlib.util.spec_from_file_location("check_100", _CHECK)
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


def _perf(list_id, seg, clicks, conv, cost="400", goal="G1"):
    return {"campaign_id": "10", "ad_group_id": "", "criterion_id": "", "list_id": list_id, "date": "2026-08-10",
            "goal_set_id": goal, "impressions": "5000", "clicks": clicks, "cost": cost, "conversions": conv,
            "conversion_value": "", "mode": "observation", "segmentation_definition": seg}


def base_tables() -> dict:
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}],
        "campaigns": [{"id": "10", "channel_type": "SEARCH", "bidding_strategy_type": "MANUAL_CPC"},
                      {"id": "20", "channel_type": "DISPLAY", "bidding_strategy_type": "MANUAL_CPC"}],
        "ad_groups": [{"id": "100", "campaign_id": "10"}, {"id": "200", "campaign_id": "20"}],
        "custom/rlsa_associations": [
            {"campaign_id": "10", "ad_group_id": "", "criterion_id": "c1", "list_id": "L1", "association_status":
             "ENABLED", "mode": "observation", "eligibility": "eligible", "modifier": "", "combination_logic": "",
             "inventory_complete": "true"},
            {"campaign_id": "20", "ad_group_id": "", "criterion_id": "c2", "list_id": "L2", "association_status":
             "ENABLED", "mode": "targeting", "eligibility": "eligible", "modifier": "", "combination_logic": "",
             "inventory_complete": "true"}],
        "external/rlsa_intent_controls": [
            {"campaign_id": "10", "ad_group_id": "", "strategy_id": "", "intended_audience_role": "observation",
             "desired_reach": "full", "supported_audience_bid_control": "true", "control_source_url": "doc",
             "checked_at": "2026-09-01", "target": "", "permitted_test_scope": "campaign 10", "owner": "ppc"}],
        "external/audience_definitions": [{"list_id": "L1", "source_id": "S1"}],
        "external/activation_permissions": [
            {"source_id": "S1", "list_id": "", "permission_status": "granted", "consent_coverage_status": "covered",
             "permitted_destinations": "google_ads", "evidence_reference": "p-1"}],
        "custom/rlsa_performance": [_perf("L1", "list members", "300", "30"),
                                    _perf("L1", "nonmember mutually exclusive", "900", "40", "1600")],
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

    def test_matching_observation_is_clean_and_display_ignored(self):
        body = self.run_check(base_tables())
        self.assertEqual([f for f in body["findings"] if f["severity"] != "Info"], [])

    def test_targeting_against_full_reach_warns_with_critical_review(self):
        t = base_tables()
        t["custom/rlsa_associations"][0]["mode"] = "targeting"
        body = self.run_check(t)
        f = self.keys(body, "mode_restricts_approved_reach")
        self.assertEqual([(x["entity"]["list_id"], x["severity"]) for x in f], [("L1", "Warning")])
        self.assertIn("material_block_evidenced",
                      next(r for r in body["ai_review"] if r["condition_key"] == "mode_restricts_approved_reach")
                      ["outcomes"])

    def test_dedicated_targeting_intent_is_preserved(self):
        t = base_tables()
        t["custom/rlsa_associations"][0]["mode"] = "targeting"
        t["external/rlsa_intent_controls"][0].update(intended_audience_role="dedicated returning users",
                                                     desired_reach="audience_only")
        self.assertFalse([f for f in self.run_check(t)["findings"] if f["severity"] == "Warning"])

    def test_unknown_intent_is_partial_not_a_finding(self):
        t = base_tables()
        t["external/rlsa_intent_controls"][0].update(intended_audience_role="", desired_reach="")
        t["custom/rlsa_associations"][0]["mode"] = "targeting"
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "mode_restricts_approved_reach"))
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "mode_vs_reach")["status"], "partial")

    def test_ineligible_targeting_list_warns(self):
        t = base_tables()
        t["custom/rlsa_associations"][0].update(mode="targeting", eligibility="too small")
        t["external/rlsa_intent_controls"][0].update(intended_audience_role="targeting", desired_reach="restricted")
        self.assertEqual(len(self.keys(self.run_check(t), "targeting_ineligible_list")), 1)

    def test_modifier_on_unsupported_control_is_info(self):
        t = base_tables()
        t["custom/rlsa_associations"][0]["modifier"] = "20%"
        t["external/rlsa_intent_controls"][0]["supported_audience_bid_control"] = "false"
        f = self.keys(self.run_check(t), "modifier_without_supported_control")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertAlmostEqual(f[0]["evidence"]["modifier"], 0.2)

    def test_gated_comparison_creates_test_review(self):
        body = self.run_check(base_tables())
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["bounded_audience_test"])

    def test_sample_gate_fails_on_one_side(self):
        t = base_tables()
        t["custom/rlsa_performance"][1]["conversions"] = "10"  # comparator below min_conversions
        self.assertFalse(self.run_check(t)["ai_review"])

    def test_different_goal_sets_never_compare(self):
        t = base_tables()
        t["custom/rlsa_performance"][1]["goal_set_id"] = "G2"
        body = self.run_check(t)
        self.assertFalse(body["ai_review"])
        self.assertFalse([o for o in body["observations"] if "member vs comparator" in o["text"]])

    def test_immature_window_is_descriptive_only(self):
        t = base_tables()
        t["account"][0]["snapshot_date"] = "2026-08-31"
        body = self.run_check(t)
        self.assertFalse(body["ai_review"])
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "segmented_outcomes")["status"], "partial")

    def test_zero_conversion_member_cpa_undefined(self):
        t = base_tables()
        t["custom/rlsa_performance"][0]["conversions"] = "0"
        obs = next(o for o in self.run_check(t)["observations"] if o["text"].startswith("10/L1 members"))
        self.assertIsNone(obs["data"]["cpa"])

    def test_permission_unknown_blocks_test(self):
        t = base_tables()
        t["external/activation_permissions"][0]["permitted_destinations"] = "crm_only"
        self.assertFalse(self.run_check(t)["ai_review"])

    def test_missing_associations_skip_all(self):
        t = base_tables()
        del t["custom/rlsa_associations"]
        body = self.run_check(t)
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))

    def test_finalize_verifies_test_scope(self):
        root = self.build(base_tables())
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = root.parent / "d.json"
        args = ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "test_warranted", "rationale": "r",
                                    "proposal": {"campaign_id": "10", "list_id": "L9", "rollback_criteria": "x"}}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "test_warranted", "rationale": "r",
                                    "proposal": {"campaign_id": "10", "list_id": "L1",
                                                 "rollback_criteria": "stop if CPA > target for 14d"}}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 0)


if __name__ == "__main__":
    unittest.main()
