"""test_check.py — Decision-boundary tests for skill-012 match-type distribution.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-012-keyword-match-type-distribution/tests
rules:   Temp folders only; stdlib only; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial tests
"""
import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_012", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)


def write_export(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        cols = list(dict.fromkeys(k for r in rows for k in r))
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def tables(kws, snapshot="2026-09-06", campaign=None):
    """kws: list of (id, text, match_type, cost, conversions)."""
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": "2"}],
        "campaigns": [campaign or {"id": "C1", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_CPA",
                                   "target_cpa": "40", "target_roas": ""}],
        "keywords": [{"id": i, "campaign_id": "C1", "ad_group_id": "G1", "text": t, "match_type": m, "status": "ENABLED"}
                     for i, t, m, _, _ in kws],
        "keyword_metrics": [{"keyword_id": i, "campaign_id": "C1", "ad_group_id": "G1", "impressions": "5000",
                             "clicks": "500", "cost": str(c), "conversions": str(v), "conversion_value": str(v * 50)}
                            for i, _, _, c, v in kws],
    }


class CheckTests(unittest.TestCase):
    def run_skill(self, t, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        write_export(root / "export", t)
        (root / "profile.json").write_text(json.dumps(profile or {"conversion_lag_days": 2}))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, root / "export", root / "profile.json").finish()

    @staticmethod
    def found(body):
        return sorted((f["condition_key"], f["severity"]) for f in body["findings"])

    @staticmethod
    def reviews(body):
        return sorted((r["entity"].get("match_type"), r["condition_key"]) for r in body["ai_review"])

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_unknown_type_is_not_inferred_from_brackets(self):
        body = self.run_skill(tables([("K1", "[drill]", "", 10, 1), ("K2", "saw", "EXACT", 10, 1)]))
        self.assertIn(("unknown_match_type", "Info"), self.found(body))
        obs = [o["data"] for o in body["observations"] if o["check"] == "match_type_parse"][0]
        self.assertEqual((obs["EXACT"], obs["UNKNOWN"]), (1, 1))

    def test_single_type_is_info_only(self):
        body = self.run_skill(tables([("K1", "a", "EXACT", 10, 1), ("K2", "b", "EXACT", 10, 1)]))
        self.assertEqual(self.found(body), [("single_type_campaign", "Info")])
        body = self.run_skill(tables([("K1", "a", "EXACT", 10, 1), ("K2", "b", "BROAD", 10, 1)]))
        self.assertEqual(self.found(body), [])

    def test_cpa_over_twice_target_goes_to_review_with_gates(self):
        body = self.run_skill(tables([("K1", "a", "BROAD", 1700, 20), ("K2", "b", "EXACT", 300, 20)]))  # 85 > 80
        self.assertEqual(self.reviews(body), [("BROAD", "type_cpa_over_2x_reference")])
        self.assertEqual(self.found(body), [("type_cpa_over_2x_reference", "Info")])
        body = self.run_skill(tables([("K1", "a", "BROAD", 1500, 20), ("K2", "b", "EXACT", 300, 20)]))  # 75
        self.assertEqual(self.reviews(body), [])
        body = self.run_skill(tables([("K1", "a", "BROAD", 1400, 14), ("K2", "b", "EXACT", 300, 20)]))  # 14 conv
        self.assertEqual(self.reviews(body), [])

    def test_benchmark_needs_both_types_qualified(self):
        camp = {"id": "C1", "channel_type": "SEARCH", "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
                "target_cpa": "", "target_roas": ""}
        body = self.run_skill(tables([("K1", "a", "BROAD", 2100, 20), ("K2", "b", "EXACT", 200, 20)], campaign=camp))
        self.assertEqual(self.reviews(body), [("BROAD", "type_cpa_over_2x_reference")])  # 105 vs 10
        body = self.run_skill(tables([("K1", "a", "BROAD", 2100, 20), ("K2", "b", "EXACT", 20, 2)], campaign=camp))
        self.assertEqual(self.reviews(body), [])

    def test_immature_window_blocks_comparison(self):
        body = self.run_skill(tables([("K1", "a", "BROAD", 1700, 20), ("K2", "b", "EXACT", 300, 20)],
                                     snapshot="2026-08-31"))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.cov(body)["target_deviation"], "partial")

    def test_value_led_campaign_has_no_cpa_screen(self):
        camp = {"id": "C1", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_ROAS", "target_cpa": "",
                "target_roas": "4"}
        body = self.run_skill(tables([("K1", "a", "BROAD", 1700, 20), ("K2", "b", "EXACT", 300, 20)], campaign=camp),
                              {"conversion_lag_days": 2, "target_cpa": 10})
        self.assertEqual(body["ai_review"], [])

    def test_fan_out_and_non_search(self):
        t = tables([("K1", "a", "BROAD", 1700, 20), ("K2", "b", "EXACT", 300, 20)])
        t["keyword_metrics"].append(dict(t["keyword_metrics"][0], cost="5"))
        body = self.run_skill(t)
        self.assertEqual(self.cov(body)["distribution"], "partial")
        self.assertEqual(body["ai_review"], [])
        t = tables([("K1", "a", "BROAD", 10, 1)], campaign={"id": "C1", "channel_type": "SHOPPING"})
        self.assertEqual(self.cov(self.run_skill(t))["distribution"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
