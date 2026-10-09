"""test_check.py — skill-051 boundaries: target vs achieved, normalization, marginal deltas, limits, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-051-bid-simulator-analysis-target-changes/tests
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
_spec = importlib.util.spec_from_file_location("check051", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

POINTS = [("P0", 30, 700, 25, "false"), ("P1", 40, 1000, 30, "true"), ("P2", 50, 1400, 35, "false"),
          ("P3", 60, 1500, 34, "false")]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build(root: Path, *, limits=True, changes="none", points=POINTS, end_override=None, context=True):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06",
                                 "conversion_lag_days": 2, "money_unit": "currency"}])
    _write(ex / "campaigns.csv", [{"id": "C1", "status": "ENABLED", "bidding_strategy_type": "TARGET_CPA",
                                   "target_cpa": 40}])
    rows = []
    for pid, tgt, cost, conv, base in points:
        rows.append({"account_id": "c1", "scope_type": "CAMPAIGN", "scope_id": "C1", "simulation_id": "S1",
                     "point_id": pid, "campaign_id": "C1", "strategy_id": "", "simulation_type": "TARGET_CPA",
                     "modification_method": "UNIFORM", "simulation_start_date": "2026-08-24",
                     "simulation_end_date": end_override.get(pid, "2026-08-30") if end_override else "2026-08-30",
                     "generated_at": "2026-09-01", "target_type": "TARGET_CPA", "target_value": tgt,
                     "modeled_cost": cost, "modeled_conversions": conv, "modeled_conversion_value": conv * 100,
                     "currency": "EUR", "baseline_point_flag": base, "source_ref": "sim"})
    _write(ex / "custom" / "bid_simulation_points.csv", rows)
    if context:
        _write(ex / "custom" / "bid_simulation_context.csv", [
            {"account_id": "c1", "simulation_id": "S1", "goal_action_ids": "5001", "value_basis": "revenue",
             "budget_id": "b1", "amount": 200, "strategy_type": "TARGET_CPA", "current_target_at_simulation": 40,
             "material_changes_since": changes, "source_ref": "ctx"}])
    prof = {"budget_constraints": {"C1": {"max_marginal_cpa": 90}}} if limits else {}
    p = root / "profile.json"
    p.write_text(json.dumps(prof))
    return ex, p


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def obs(body, check):
    return [o["data"] for o in body["observations"] if o["check"] == check]


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_target_input_kept_separate_from_modeled_cpa(self):
        body = run(*build(self.root))
        p1 = [p for p in obs(body, "point_metrics")[0]["points"] if p["point_id"] == "P1"][0]
        self.assertEqual(p1["target_value"], 40)
        self.assertAlmostEqual(p1["achieved_cpa"], 1000 / 30, places=5)

    def test_zero_conversion_point_has_no_cpa(self):
        body = run(*build(self.root, points=POINTS + [("P4", 20, 100, 0, "false")]))
        p4 = [p for p in obs(body, "point_metrics")[0]["points"] if p["point_id"] == "P4"][0]
        self.assertIsNone(p4["achieved_cpa"])

    def test_seven_day_equivalent_uses_inclusive_days(self):
        body = run(*build(self.root))
        o = obs(body, "period_normalization")[0]
        self.assertEqual(o["days"], 7)
        self.assertAlmostEqual([w for w in o["seven_day"] if w["point_id"] == "P1"][0]["cost_7d"], 1000)

    def test_marginal_cpa_and_nonmonotonic_increment(self):
        body = run(*build(self.root))
        o = obs(body, "marginal_analysis")[0]
        p2 = [d for d in o["baseline_to_candidate"] if d["to"] == "P2"][0]
        self.assertAlmostEqual(p2["marginal_cpa"], 80)
        self.assertEqual(o["needs_interpretation"], ["P3"])
        p3 = [d for d in o["adjacent"] if d["to"] == "P3"][0]
        self.assertIsNone(p3["marginal_cpa"])

    def test_feasibility_against_documented_limit(self):
        body = run(*build(self.root))
        cands = {c["point_id"]: c["feasible"] for c in obs(body, "business_constraints")[0]["candidates"]}
        self.assertEqual(cands, {"P0": True, "P2": True, "P3": False})
        self.assertEqual(body["findings"], [])

    def test_no_limit_means_no_candidate_review(self):
        body = run(*build(self.root, limits=False))
        self.assertEqual(cov(body)["business_constraints"], "partial")
        self.assertEqual(body["ai_review"], [])

    def test_mixed_dates_are_incomparable(self):
        body = run(*build(self.root, end_override={"P3": "2026-08-31"}))
        self.assertEqual([f["condition_key"] for f in body["findings"]], ["incomparable_simulation"])
        self.assertEqual(obs(body, "marginal_analysis"), [])

    def test_stale_context_blocks_candidates(self):
        body = run(*build(self.root, changes="budget raised 2026-09-03"))
        self.assertIn("stale_simulation_context", [f["condition_key"] for f in body["findings"]])
        self.assertEqual(body["ai_review"], [])

    def test_missing_points_is_explicit_unavailable(self):
        ex, prof = build(self.root)
        (ex / "custom" / "bid_simulation_points.csv").unlink()
        body = run(ex, prof)
        self.assertTrue(all(s == "skipped" for s in cov(body).values()))

    def test_finalize_checks_feasibility_of_outcome(self):
        ex, prof = build(self.root)
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                         ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        for outcome, pid, code in (("evaluate_candidate", "P3", 4), ("evaluate_candidate", "P9", 4),
                                   ("proposed_change_exceeds_constraint", "P2", 4),
                                   ("proposed_change_exceeds_constraint", "P3", 0)):
            dec.write_text(json.dumps([{"id": item["id"], "outcome": outcome, "rationale": "r",
                                        "proposal": {"point_id": pid}}]))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), code, (outcome, pid))
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"]], ["Warning"])


if __name__ == "__main__":
    unittest.main()
