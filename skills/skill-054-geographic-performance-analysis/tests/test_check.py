"""test_check.py — skill-054 boundaries: within-campaign CPA/CVR screens, gates, zero-conversion, service area, tests.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-054-geographic-performance-analysis/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check054", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

LOOKUP = [("2380", "Italy", ""), ("1001", "Milan", "2380"), ("1002", "Rome", "2380"), ("3001", "Paris", "2250"),
          ("2250", "France", "")]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def row(cid, crit, name, clicks, cost, conv, basis="user_location"):
    return {"account_id": "c1", "campaign_id": cid, "date": "2026-08-15", "geo_level": "CITY",
            "geo_criterion_id": crit, "location_type": "CITY", "report_basis": basis, "location_name": name,
            "country_criterion_id": "", "impressions": clicks * 10, "clicks": clicks, "cost": cost,
            "conversions": conv, "conversion_value": conv * 100, "source": "ui", "currency": "EUR",
            "reporting_completeness": "complete"}


def build(root: Path, *, milan_conv=20, snapshot="2026-09-06", tracking=True, remote=None, lookup=LOOKUP,
          extra_rows=()):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-30", "snapshot_date": snapshot,
                                 "conversion_lag_days": 2, "money_unit": "currency"}])
    _write(ex / "campaigns.csv", [{"id": "C1", "status": "ENABLED", "bidding_strategy_type": "MANUAL_CPC"},
                                  {"id": "C2", "status": "ENABLED", "bidding_strategy_type": "TARGET_CPA"}])
    _write(ex / "campaign_metrics.csv", [{"campaign_id": "C1", "cost": 2300}, {"campaign_id": "C2", "cost": 0}])
    _write(ex / "bid_adjustments.csv", [{"campaign_id": "C1", "dimension": "LOCATION", "criterion_id": "1001",
                                         "modifier": 1.2, "excluded": ""}])
    if tracking:
        _write(ex / "conversion_actions.csv", [{"id": "g", "name": "Purchase", "category": "PURCHASE",
                                                "status": "ENABLED", "last_conversion_date": "2026-08-29"}])
    _write(ex / "custom" / "geographic_performance.csv",
           [row("C1", "1001", "Milan", 500, 1000, milan_conv), row("C1", "1002", "Rome", 1000, 1000, 40),
            row("C1", "3001", "Paris", 200, 300, 0)] + list(extra_rows))
    if lookup:
        _write(ex / "custom" / "geo_lookup.csv", [{"geo_criterion_id": i, "name": n, "parent_id": p,
                                                   "country_code": "", "geo_level": "", "source": "api",
                                                   "snapshot_date": "2026-09-06"} for i, n, p in lookup])
    obj = {"C1": {"goal_ids": ["g"]}}
    if remote is not None:
        obj["C1"]["remote_buyers"] = remote
    p = root / "profile.json"
    p.write_text(json.dumps({"service_area": ["Italy"], "campaign_objectives": obj}))
    return ex, p


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def fnd(body, key):
    return sorted((f["entity"]["geo_criterion_id"], f["severity"]) for f in body["findings"] if f["condition_key"] == key)


def rev(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_adverse_and_opportunity_against_rest_of_campaign(self):
        body = run(*build(self.root))
        self.assertEqual(fnd(body, "adverse_location_efficiency"), [("1001", "Warning")])
        self.assertEqual(fnd(body, "location_efficiency_opportunity"), [("1002", "Info")])
        f = [f for f in body["findings"] if f["condition_key"] == "adverse_location_efficiency"][0]
        self.assertAlmostEqual(f["evidence"]["cpa_index"], 50 / 32.5, places=4)

    def test_sample_gate_blocks_cpa_comparison(self):
        body = run(*build(self.root, milan_conv=10))
        self.assertEqual(fnd(body, "adverse_location_efficiency"), [])

    def test_immature_window_is_descriptive_only(self):
        body = run(*build(self.root, snapshot="2026-08-31"))
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body)["efficiency_comparison"], "partial")
        self.assertEqual(cov(body)["zero_conversion_screen"], "partial")

    def test_zero_conversion_needs_verified_tracking(self):
        body = run(*build(self.root))
        self.assertEqual(fnd(body, "zero_conversion_location"), [("3001", "Info")])
        self.assertEqual(rev(body, "zero_conversion_location")[0]["outcomes"]["investigate"]["severity"], "Warning")
        body = run(*build(self.root, tracking=False))
        self.assertEqual(fnd(body, "zero_conversion_location"), [])
        self.assertEqual(cov(body)["zero_conversion_screen"], "partial")

    def test_out_of_area_is_review_unless_remote_buyers(self):
        body = run(*build(self.root))
        self.assertEqual([r["entity"]["geo_criterion_id"] for r in rev(body, "non_serviceable_traffic")], ["3001"])
        body = run(*build(self.root, remote=True))
        self.assertEqual(rev(body, "non_serviceable_traffic"), [])

    def test_unresolvable_geography_is_unknown_not_outside(self):
        body = run(*build(self.root, lookup=[l for l in LOOKUP if l[0] != "2250"]))
        self.assertEqual(rev(body, "non_serviceable_traffic"), [])
        self.assertEqual(cov(body)["service_area_mapping"], "partial")

    def test_manual_cpc_test_value_is_capped_and_layered(self):
        body = run(*build(self.root))
        obs = [o["data"] for o in body["observations"] if o["check"] == "modifier_test_proposal"
               and o["data"].get("geo_criterion_id") == "1001"][0]
        self.assertAlmostEqual(obs["capped_incremental"], 0.9)
        self.assertAlmostEqual(obs["proposed_multiplier"], 1.08)

    def test_bases_are_not_summed(self):
        body = run(*build(self.root, extra_rows=[row("C1", "1001", "Milan", 500, 1000, 20, basis="matched_location")]))
        groups = [o["data"]["report_basis"] for o in body["observations"] if o["check"] == "coverage_reconciliation"
                  and "report_basis" in o["data"]]
        self.assertEqual(sorted(groups), ["matched_location", "user_location"])
        user = [o["data"] for o in body["observations"] if o["data"].get("report_basis") == "user_location"
                and o["check"] == "coverage_reconciliation"][0]
        self.assertAlmostEqual(user["geo_cost"], 2300)


if __name__ == "__main__":
    unittest.main()
