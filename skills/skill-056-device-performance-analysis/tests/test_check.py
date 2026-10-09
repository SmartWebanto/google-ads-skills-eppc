"""test_check.py — skill-056 boundaries: efficiency index ±0.2, sample/maturity gates, zero-conversion, controls.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-056-device-performance-analysis/tests
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
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check056", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

DEVICES = {"MOBILE": (1000, 20), "DESKTOP": (1000, 40), "TABLET": (200, 0), "CONNECTED_TV": (100, 0)}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build(root: Path, *, devices=None, snapshot="2026-09-06", tracking=True, controls=None):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-30", "snapshot_date": snapshot,
                                 "conversion_lag_days": 2, "money_unit": "currency"}])
    _write(ex / "campaigns.csv", [{"id": "C1", "status": "ENABLED", "bidding_strategy_type": "MANUAL_CPC",
                                   "target_cpa": 40}])
    _write(ex / "campaign_metrics.csv", [{"campaign_id": "C1", "cost": 2300}])
    if tracking:
        _write(ex / "conversion_actions.csv", [{"id": "g", "name": "Purchase", "category": "PURCHASE",
                                                "status": "ENABLED", "last_conversion_date": "2026-08-29"}])
    rows = []
    for dev, (cost, conv) in (devices or DEVICES).items():
        for i in range(30):
            rows.append({"account_id": "c1", "campaign_id": "C1", "date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(),
                         "device": dev, "impressions": 100, "clicks": 10, "cost": cost / 30, "conversions": conv / 30,
                         "conversion_value": conv * 3, "source": "ui", "window": "2026-08"})
    _write(ex / "custom" / "device_performance.csv", rows)
    if controls:
        _write(ex / "custom" / "device_controls.csv", controls)
    p = root / "profile.json"
    p.write_text(json.dumps({"campaign_objectives": {"C1": {"goal_ids": ["g"]}}}))
    return ex, p


def ctrl(device, ctype, cur, lo=0.1, hi=10.0):
    return {"account_id": "c1", "campaign_id": "C1", "device": device, "snapshot_date": "2026-09-06",
            "control_type": ctype, "current_value": cur, "permitted_min": lo, "permitted_max": hi,
            "strategy_type": "MANUAL_CPC", "support_source_url": "https://support.google.com/google-ads/answer/2732132"}


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def fnd(body, key):
    return sorted((f["entity"]["device"], f["severity"]) for f in body["findings"] if f["condition_key"] == key)


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


def ctrl_obs(body, device):
    return [o["data"] for o in body["observations"] if o["check"] == "control_proposal"
            and o["data"].get("device") == device][0]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_index_thresholds_against_other_devices(self):
        body = run(*build(self.root))
        self.assertEqual(fnd(body, "adverse_device_efficiency"), [("MOBILE", "Warning")])
        self.assertEqual(fnd(body, "device_efficiency_opportunity"), [("DESKTOP", "Info")])
        f = [f for f in body["findings"] if f["condition_key"] == "adverse_device_efficiency"][0]
        self.assertAlmostEqual(f["evidence"]["index"], 30 / 50 - 1, places=5)
        self.assertEqual(len(f["evidence"]["weekly"]), 4)

    def test_connected_tv_is_not_compared(self):
        body = run(*build(self.root))
        self.assertFalse(any(f["entity"]["device"] == "CONNECTED_TV" for f in body["findings"]))

    def test_index_inside_band_is_not_a_finding(self):
        body = run(*build(self.root, devices={"MOBILE": (1100, 40), "DESKTOP": (1000, 40)}))
        self.assertEqual(fnd(body, "adverse_device_efficiency") + fnd(body, "device_efficiency_opportunity"), [])

    def test_sample_gate_on_device_side(self):
        body = run(*build(self.root, devices={"MOBILE": (1000, 10), "DESKTOP": (1000, 40)}))
        self.assertEqual(fnd(body, "adverse_device_efficiency"), [])

    def test_immature_window_blocks_judgments(self):
        body = run(*build(self.root, snapshot="2026-08-31"))
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body)["efficiency_index"], "partial")

    def test_zero_conversion_device_needs_tracking(self):
        body = run(*build(self.root))
        self.assertEqual(fnd(body, "zero_conversion_device"), [("TABLET", "Info")])
        shares = [o["data"] for o in body["observations"] if o["check"] == "device_shares"][0]["devices"]
        self.assertIsNone(shares["TABLET"]["cpa"])
        body = run(*build(self.root, tracking=False))
        self.assertEqual(fnd(body, "zero_conversion_device"), [])
        self.assertEqual(cov(body)["zero_conversion_screen"], "partial")

    def test_manual_cpc_test_value_is_capped_and_clamped(self):
        body = run(*build(self.root, controls=[ctrl("MOBILE", "CPC_multiplier", 1.0)]))
        self.assertAlmostEqual(ctrl_obs(body, "MOBILE")["proposed_value"], 0.9)
        body = run(*build(self.root, controls=[ctrl("MOBILE", "CPC_multiplier", 1.0, lo=0.95)]))
        o = ctrl_obs(body, "MOBILE")
        self.assertAlmostEqual(o["proposed_value"], 0.95)
        self.assertTrue(o["clamped"])

    def test_tcpa_adjustment_describes_target_not_cpc(self):
        body = run(*build(self.root, controls=[ctrl("DESKTOP", "CPA_target_adjustment", 1.2)]))
        o = ctrl_obs(body, "DESKTOP")
        self.assertAlmostEqual(o["effective_device_target"], 48)
        self.assertNotIn("proposed_value", o)

    def test_missing_controls_is_diagnostic_only(self):
        body = run(*build(self.root))
        self.assertEqual(cov(body)["control_proposal"], "skipped")
        body = run(*build(self.root, controls=[ctrl("DESKTOP", "CPC_multiplier", 1.0)]))
        self.assertEqual(cov(body)["control_proposal"], "partial")


if __name__ == "__main__":
    unittest.main()
