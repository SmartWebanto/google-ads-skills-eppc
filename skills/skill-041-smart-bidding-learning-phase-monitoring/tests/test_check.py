"""test_check.py — decision boundaries of skill-041 scripts/check.py (learning intervals, changes, baselines).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-041-smart-bidding-learning-phase-monitoring/tests
rules:   Temp folders only; stdlib only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("skill041_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
M = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = M
_SPEC.loader.exec_module(M)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}
CAMPS = [{"id": "C1", "name": "C1", "status": "ENABLED", "bidding_strategy_type": "TARGET_CPA",
          "bidding_strategy_id": "S1", "budget_id": "B1"}]


def _write(root: Path, key: str, rows: list[dict]) -> None:
    path = root / f"{key}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Case:
    def __init__(self, test: unittest.TestCase, tables: dict, profile: dict | None = None, manifest: dict | None = None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        tables = {"account": [ACCOUNT], **tables}
        for key, rows in tables.items():
            _write(self.export, key, rows)
        _write(self.export, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete",
                                                "period_start": (manifest or {}).get(k, "")} for k in tables])
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(profile or {"conversion_lag_days": 2}))
        self.out = self.root / "out"

    def main(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, list(args))

    def run(self) -> dict:
        assert self.main("run", "--export", str(self.export), "--profile", str(self.profile), "--out", str(self.out)) == 0
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions) -> tuple[int, dict]:
        p = self.root / "decisions.json"
        p.write_text(json.dumps(decisions))
        code = self.main("finalize", "--export", str(self.export), "--profile", str(self.profile), "--out",
                         str(self.out), "--decisions", str(p))
        return code, json.loads((self.out / "final.json").read_text())


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body):
    return sorted((f["condition_key"], f["severity"]) for f in body["findings"])


def status(first_learning: date, last: date, prior_state="not_learning", raw="LEARNING"):
    rows = [{"campaign_id": "C1", "strategy_id": "S1", "observed_at": (first_learning - timedelta(days=3)).isoformat(),
             "raw_status": "ELIGIBLE", "raw_reason": "", "documented_learning_state": prior_state}]
    d = first_learning
    while d <= last:
        rows.append({"campaign_id": "C1", "strategy_id": "S1", "observed_at": d.isoformat(), "raw_status": raw,
                     "raw_reason": "", "documented_learning_state": "learning"})
        d += timedelta(days=1)
    return rows


def daily(start: date, days: int, conv_learning: float, conv_base: float, split: date):
    return [{"campaign_id": "C1", "date": (start + timedelta(days=i)).isoformat(), "goal_cohort": "purchase",
             "cost": 100, "conversions": conv_learning if start + timedelta(days=i) >= split else conv_base,
             "conversion_value": 400, "lag_mature": "true"} for i in range(days)]


class LearningPhaseTests(unittest.TestCase):
    def test_raw_limited_status_is_not_learning(self):
        rows = [{"campaign_id": "C1", "observed_at": f"2026-08-{d:02d}", "raw_status": "LIMITED", "raw_reason": "budget",
                 "documented_learning_state": ""} for d in range(1, 30)]
        body = Case(self, {"campaigns": CAMPS, "custom/learning_status_history": rows}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "learning_status_mapping")["status"], "partial")

    def test_learning_over_21_days_is_reviewed_not_warning(self):
        body = Case(self, {"campaigns": CAMPS, "custom/learning_status_history":
                           status(date(2026, 8, 3), date(2026, 8, 30))}).run()
        self.assertEqual(keys(body), [("learning_over_21_days", "Info")])
        f = body["findings"][0]
        self.assertEqual(f["evidence"]["min_observed_days"], 27)
        self.assertEqual(f["evidence"]["upper_bound_days"], 30)
        review = next(r for r in body["ai_review"] if r["condition_key"] == "learning_over_21_days")
        self.assertEqual(review["outcomes"]["sustained_performance_concern"]["severity"], "Warning")

    def test_21_days_or_interrupted_run_is_not_flagged(self):
        body = Case(self, {"campaigns": CAMPS, "custom/learning_status_history":
                           status(date(2026, 8, 9), date(2026, 8, 30))}).run()
        self.assertEqual(body["findings"], [])
        rows = status(date(2026, 8, 1), date(2026, 8, 30))
        rows.append({"campaign_id": "C1", "observed_at": "2026-08-20", "raw_status": "ELIGIBLE",
                     "raw_reason": "", "documented_learning_state": "not_learning"})
        rows = [r for r in rows if not (r["observed_at"] == "2026-08-20" and r["documented_learning_state"] == "learning")]
        body = Case(self, {"campaigns": CAMPS, "custom/learning_status_history": rows}).run()
        self.assertEqual(body["findings"], [])

    def test_unknown_prior_state_gives_lower_bound_only(self):
        body = Case(self, {"campaigns": CAMPS, "custom/learning_status_history":
                           status(date(2026, 8, 3), date(2026, 8, 30), prior_state="")}).run()
        self.assertEqual(cov(body, "learning_interval")["status"], "partial")
        self.assertIsNone(body["findings"][0]["evidence"].get("upper_bound_days"))

    def test_changes_counted_by_unique_id_in_window_and_joined_by_strategy(self):
        changes = [
            {"change_id": "X1", "changed_at": "2026-08-20", "campaign_id": "C1", "field": "target_cpa", "reason": "test"},
            {"change_id": "X1", "changed_at": "2026-08-20", "campaign_id": "C1", "field": "target_cpa", "reason": "dup"},
            {"change_id": "X2", "changed_at": "2026-08-25", "campaign_id": "", "strategy_id": "S1", "field": "target_cpa"},
            {"change_id": "X3", "changed_at": "2026-07-01", "campaign_id": "C1", "field": "budget_amount"},
            {"change_id": "X4", "changed_at": "2026-08-26", "campaign_id": "C1", "field": "ad_text"},
        ]
        case = Case(self, {"campaigns": CAMPS, "custom/learning_changes": changes},
                    manifest={"custom/learning_changes": "2026-07-01"})
        body = case.run()
        obs = next(o for o in body["observations"] if o["check"] == "change_timeline")
        self.assertEqual(obs["data"]["unique_changes"], 2)
        self.assertEqual(cov(body, "change_timeline")["status"], "completed")
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "repeated_discretionary_changes")
        code, _ = case.finalize([{"id": rid, "outcome": "repeated_discretionary", "rationale": "r",
                                  "proposal": {"discretionary_change_ids": ["X1"]}}])
        self.assertEqual(code, 4)
        code, final = case.finalize([{"id": rid, "outcome": "repeated_discretionary", "rationale": "r",
                                      "proposal": {"discretionary_change_ids": ["X1", "X2"]}}])
        self.assertEqual(code, 0)
        self.assertIn(("repeated_discretionary_changes", "Warning"), keys(final))

    def test_change_window_without_certified_coverage_is_partial(self):
        changes = [{"change_id": "X1", "changed_at": "2026-08-20", "campaign_id": "C1", "field": "target_cpa"}]
        body = Case(self, {"campaigns": CAMPS, "custom/learning_changes": changes}).run()
        self.assertEqual(cov(body, "change_timeline")["status"], "partial")
        self.assertEqual(body["ai_review"], [])  # a single change is not "repeated"

    def test_matched_baseline_needs_both_samples(self):
        split = date(2026, 8, 17)
        st = status(split, date(2026, 8, 30))
        ok = Case(self, {"campaigns": CAMPS, "custom/learning_status_history": st,
                         "custom/learning_daily": daily(date(2026, 8, 3), 28, 2, 3, split)}).run()
        obs = next(o for o in ok["observations"] if o["check"] == "baseline_comparison")
        self.assertEqual(obs["data"]["window_days"], 14)
        self.assertTrue(obs["data"]["both_qualify"])
        self.assertAlmostEqual(obs["data"]["learning"]["cpa"], 50)
        self.assertAlmostEqual(obs["data"]["baseline"]["cpa"], 1400 / 42, places=4)
        low = Case(self, {"campaigns": CAMPS, "custom/learning_status_history": st,
                          "custom/learning_daily": daily(date(2026, 8, 3), 28, 0.5, 3, split)}).run()
        self.assertEqual(cov(low, "baseline_comparison")["status"], "partial")

    def test_weekly_volatility_uses_complete_qualifying_weeks(self):
        split = date(2026, 8, 17)
        rows = daily(date(2026, 8, 3), 28, 3, 3, split)
        for r in rows:
            if r["date"] >= "2026-08-24":
                r["conversions"] = 4
        body = Case(self, {"campaigns": CAMPS, "custom/learning_status_history": status(split, date(2026, 8, 30)),
                           "custom/learning_daily": rows}).run()
        obs = next(o for o in body["observations"] if o["check"] == "weekly_volatility")
        self.assertEqual(obs["data"]["valid_weeks"], 2)
        self.assertAlmostEqual(obs["data"]["cv"], (700 / 21 - 25) / 2 / ((700 / 21 + 25) / 2), places=4)


if __name__ == "__main__":
    unittest.main()
