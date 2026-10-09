"""test_check.py — Decision-boundary tests for skill-020 low-performing keyword screening.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-020-low-performing-keyword-pruning/tests
rules:   Temp folders only; stdlib only; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial tests
"""
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
_spec = importlib.util.spec_from_file_location("check_020", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)


def write_export(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        cols, rows = rows if isinstance(rows, tuple) else (list(dict.fromkeys(k for r in rows for k in r)), rows)
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


def base(snapshot="2026-09-06", km=None, campaign=None, strategies=None, last_conv="2026-08-29"):
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": "2",
                     "money_unit": "currency", "rates_format": "fraction"}],
        "campaigns": [campaign or {"id": "C1", "bidding_strategy_type": "TARGET_CPA", "target_cpa": "40",
                                   "strategy_id": "", "goal_ids": "purchase"}],
        "bidding_strategies": strategies or (["id", "type", "target_cpa", "campaign_ids"], []),
        "conversion_actions": [{"id": "purchase", "name": "Purchase", "category": "PURCHASE", "status": "ENABLED",
                                "last_conversion_date": last_conv}],
        "keywords": [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "drill", "match_type": "EXACT",
                      "status": "ENABLED"}],
        "keyword_metrics": km if km is not None else [],
        "search_terms": [{"search_term": "drill", "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": "K1",
                          "clicks": "10", "cost": "30", "conversions": "0"}],
    }


def km_row(cost, conv, kid="K1", value=None):
    return {"keyword_id": kid, "campaign_id": "C1", "ad_group_id": "G1", "impressions": "1000", "clicks": "200",
            "cost": str(cost), "conversions": str(conv), "conversion_value": "" if value is None else str(value),
            "quality_score": "5"}


class CheckTests(unittest.TestCase):
    def run_skill(self, tables, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        write_export(root / "export", tables)
        (root / "profile.json").write_text(json.dumps(profile or {"conversion_lag_days": 2}))
        self.root = root
        ctx = M.cli.run_once(M.SKILL, M.VERSION, M.run, root / "export", root / "profile.json")
        return ctx.finish()

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    @staticmethod
    def keys(body, severity=None):
        return [f["condition_key"] for f in body["findings"] if severity in (None, f["severity"])]

    def test_cpa_over_twice_target_is_warning_but_not_below(self):
        body = self.run_skill(base(km=[km_row(1700, 20)]))  # CPA 85 > 80
        self.assertEqual(self.keys(body, "Warning"), ["cpa_over_2x_target"])
        body = self.run_skill(base(km=[km_row(1500, 20)]))  # CPA 75 <= 80
        self.assertEqual(self.keys(body, "Warning"), [])

    def test_min_conversions_gate_blocks_cpa_flag(self):
        body = self.run_skill(base(km=[km_row(1400, 14)]))  # CPA 100 but 14 < 15 conversions
        self.assertEqual(self.keys(body), [])

    def test_portfolio_target_wins_over_profile_target(self):
        camp = {"id": "C1", "bidding_strategy_type": "MAXIMIZE_CONVERSIONS", "target_cpa": "", "strategy_id": "P1",
                "goal_ids": "purchase"}
        strat = [{"id": "P1", "type": "TARGET_CPA", "target_cpa": "100", "campaign_ids": "C1"}]
        body = self.run_skill(base(km=[km_row(3000, 20)], campaign=camp, strategies=strat),
                              {"conversion_lag_days": 2, "target_cpa": 20})
        self.assertEqual(self.keys(body, "Warning"), [])  # CPA 150 < 2 x 100
        tr = [o for o in body["observations"] if o["check"] == "target_resolution"][0]["data"]
        self.assertEqual((tr["cpa"], tr["spend_floor"]), (100, 100))
        self.assertIn("P1", tr["cpa_source"])

    def test_immature_window_defers_all_prescriptions(self):
        body = self.run_skill(base(snapshot="2026-08-31", km=[km_row(1700, 20), km_row(300, 0, "K2")]))
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.cov(body)["cpa_screen"], "partial")
        self.assertEqual(self.cov(body)["zero_conversion_screen"], "partial")

    def test_zero_conversion_needs_tracking_and_floor(self):
        body = self.run_skill(base(km=[km_row(60, 0), km_row(30, 0, "K2")]))  # floor max(50, 40) = 50
        reviews = [r for r in body["ai_review"] if r["condition_key"] == "zero_conversion_keyword"]
        self.assertEqual([r["entity"]["keyword_id"] for r in reviews], ["K1"])
        self.assertIn("Warning", [o["severity"] for o in reviews[0]["outcomes"].values()])
        self.assertEqual(self.keys(body, "Warning"), [])  # Warning only via review
        stale = self.run_skill(base(km=[km_row(60, 0)], last_conv="2026-07-01"))
        self.assertEqual(stale["ai_review"], [])
        self.assertEqual(self.cov(stale)["zero_conversion_screen"], "partial")

    def test_missing_keyword_metrics_skips_not_passes(self):
        t = base()
        del t["keyword_metrics"]
        body = self.run_skill(t)
        for c in ("zero_conversion_screen", "cpa_screen", "target_resolution"):
            self.assertEqual(self.cov(body)[c], "skipped")
        self.assertEqual(body["findings"], [])

    def test_zero_conversions_denominator_never_yields_cpa(self):
        body = self.run_skill(base(km=[km_row(40, 0)]))  # below floor, zero conversions
        self.assertEqual(body["findings"], [])
        self.assertFalse(any("cpa" in o["data"] and o["check"] == "cpa_screen" and o["data"].get("keyword_id")
                             for o in body["observations"]))

    def test_fan_out_rows_are_excluded(self):
        body = self.run_skill(base(km=[km_row(1700, 20), km_row(10, 1)]))
        self.assertEqual(self.keys(body), [])
        self.assertEqual(self.cov(body)["target_resolution"], "partial")

    def test_finalize_rejects_bid_reduction_under_smart_bidding(self):
        body = self.run_skill(base(km=[km_row(60, 0)]))
        rid = body["ai_review"][0]["id"]
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
            bad = self.root / "bad.json"
            bad.write_text(json.dumps([{"id": rid, "outcome": "low_performer_after_context", "rationale": "irrelevant",
                                        "proposal": {"action": "bid_reduction"}}]))
            self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                        ["finalize"] + args + ["--decisions", str(bad)]), 4)
            good = self.root / "good.json"
            good.write_text(json.dumps([{"id": rid, "outcome": "low_performer_after_context", "rationale": "irrelevant",
                                         "proposal": {"action": "pause_trial"}}]))
            self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                        ["finalize"] + args + ["--decisions", str(good)]), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"]], ["Warning"])


if __name__ == "__main__":
    unittest.main()
