"""test_check.py — skill-052 boundaries: goal mapping, aligned reconciliation tolerance, zero values, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-052-conversion-value-based-bidding/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check052", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build(root: Path, *, ads_value=12000, business_value=10000, status="aligned", lag=3, tolerance="10%",
          daily_value=100.0, goals=True, snapshot="2026-09-06"):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-31", "snapshot_date": snapshot,
                                 "conversion_lag_days": 2, "money_unit": "currency"}])
    _write(ex / "campaigns.csv", [{"id": "V1", "status": "ENABLED", "bidding_strategy_type": "TARGET_ROAS"},
                                  {"id": "C1", "status": "ENABLED", "bidding_strategy_type": "TARGET_CPA"}])
    _write(ex / "conversion_actions.csv", [
        {"id": "a1", "status": "ENABLED", "primary_for_goal": "true", "value_settings": "transaction-specific"},
        {"id": "a2", "status": "ENABLED", "primary_for_goal": "true", "value_settings": "10 EUR"}])
    _write(ex / "external" / "business_value_policy.csv", [
        {"action_id": "a1", "value_cohort": "all", "effective_from": "2026-01-01", "effective_to": "",
         "business_objective": "revenue", "value_basis": "gross revenue", "static_or_dynamic_intent": "dynamic",
         "currency": "EUR", "close_rate": "", "contribution_per_closed_customer": "", "horizon": "",
         "approved_value": "", "tolerance": tolerance, "owner": "finance", "source_ref": "pol"},
        {"action_id": "a2", "value_cohort": "all", "effective_from": "2026-01-01", "effective_to": "",
         "business_objective": "lead contribution", "value_basis": "expected contribution",
         "static_or_dynamic_intent": "dynamic", "currency": "EUR", "close_rate": "0.2",
         "contribution_per_closed_customer": 500, "horizon": "12 months", "approved_value": "",
         "tolerance": tolerance, "owner": "sales", "source_ref": "pol"}])
    _write(ex / "external" / "business_value_reconciliation.csv", [
        {"action_id": "a1", "value_cohort": "all", "period": "2026-08", "business_event_count": 100,
         "comparable_business_value": business_value, "ads_count": 100, "ads_value": ads_value, "exclusions": "",
         "expected_lag": lag, "source_ref": "crm", "reconciliation_status": status}])
    daily = []
    for d in range(1, 21):
        day = f"2026-08-{d:02d}"
        daily.append({"campaign_id": "V1", "action_id": "a1", "date": day, "conversions": 2,
                      "conversion_value": daily_value, "lag_mature": "true", "source_ref": "ads"})
        daily.append({"campaign_id": "C1", "action_id": "a2", "date": day, "conversions": 1,
                      "conversion_value": 0, "lag_mature": "true", "source_ref": "ads"})
    if daily_value is None:
        for i, r in enumerate(daily):
            if r["action_id"] == "a1":
                r["conversion_value"] = 50 + i
    _write(ex / "custom" / "conversion_value_action_daily.csv", daily)
    prof = {"campaign_objectives": {"V1": {"goal_ids": ["a1"]}, "C1": {"goal_ids": ["a2"]}} if goals else {}}
    p = root / "profile.json"
    p.write_text(json.dumps(prof))
    return ex, p


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def keys(body, sev=None):
    return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


def reviews(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_discrepancy_outside_tolerance_is_warning_with_critical_review(self):
        body = run(*build(self.root))
        self.assertEqual(keys(body, "Warning"), ["value_discrepancy_outside_tolerance"])
        self.assertEqual(len(reviews(body, "material_value_corruption")), 1)
        self.assertEqual(keys(body, "Critical"), [])

    def test_within_tolerance_is_not_a_finding(self):
        body = run(*build(self.root, ads_value=10500))
        self.assertEqual(keys(body, "Warning"), [])

    def test_unaligned_or_immature_reconciliation_is_descriptive(self):
        for kw in ({"status": "pending"}, {"lag": 10}, {"tolerance": ""}):
            body = run(*build(self.root, **kw))
            self.assertEqual(keys(body, "Warning"), [], kw)
            self.assertEqual(cov(body)["reconciliation"], "partial", kw)

    def test_zero_business_value_has_no_percent_variance(self):
        body = run(*build(self.root, business_value=0))
        self.assertEqual(keys(body, "Warning"), [])
        obs = [o["data"] for o in body["observations"] if o["check"] == "reconciliation"][0]
        self.assertIsNone(obs["value_variance"])
        self.assertEqual(obs["abs_value_diff"], 12000)

    def test_equal_values_in_value_bidding_go_to_review_only(self):
        body = run(*build(self.root, daily_value=100.0))
        items = reviews(body, "zero_or_equal_values_in_value_bidding")
        self.assertEqual([r["entity"]["campaign_id"] for r in items], ["V1"])
        self.assertIsNone(items[0]["outcomes"]["intentional_valid"]["severity"])
        body = run(*build(self.root, daily_value=None))
        self.assertEqual(reviews(body, "zero_or_equal_values_in_value_bidding"), [])

    def test_count_bidding_zero_values_are_not_reviewed_as_defect(self):
        body = run(*build(self.root))
        self.assertFalse(any(r["entity"].get("campaign_id") == "C1"
                             for r in reviews(body, "zero_or_equal_values_in_value_bidding")))

    def test_missing_goals_blocks_optimizing_set(self):
        body = run(*build(self.root, goals=False))
        self.assertEqual(cov(body)["goal_mapping"], "partial")
        self.assertEqual(reviews(body, "material_value_corruption"), [])

    def test_lead_value_model_is_close_rate_times_contribution(self):
        body = run(*build(self.root))
        obs = [o["data"] for o in body["observations"] if o["check"] == "lead_value_model"]
        self.assertAlmostEqual(obs[0]["expected_contribution_per_lead"], 100)

    def test_value_bidding_opportunity_needs_maturity(self):
        body = run(*build(self.root))
        self.assertEqual(len(reviews(body, "value_bidding_opportunity")), 1)
        body = run(*build(self.root, snapshot="2026-09-01"))
        self.assertEqual(reviews(body, "value_bidding_opportunity"), [])
        self.assertEqual(cov(body)["value_bidding_opportunity"], "partial")

    def test_finalize_critical_requires_evidence_ref(self):
        ex, prof = build(self.root)
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                         ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        item = reviews(json.loads((out / "result.json").read_text()), "material_value_corruption")[0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_corruption_evidenced", "rationale": "r"}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_corruption_evidenced", "rationale": "r",
                                    "proposal": {"evidence_ref": "finance-recon-2026-08"}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertIn("Critical", [f["severity"] for f in final["findings"]])


if __name__ == "__main__":
    unittest.main()
