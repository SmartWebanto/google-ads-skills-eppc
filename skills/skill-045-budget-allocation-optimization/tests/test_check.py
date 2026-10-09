"""test_check.py — decision boundaries of skill-045 scripts/check.py (cohorts, constraints, marginal response).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-045-budget-allocation-optimization/tests
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

_SPEC = importlib.util.spec_from_file_location("skill045_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
M = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = M
_SPEC.loader.exec_module(M)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}


def _write(root: Path, key: str, rows: list[dict]) -> None:
    path = root / f"{key}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Case:
    def __init__(self, test: unittest.TestCase, tables: dict):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        tables = {"account": [ACCOUNT], **tables}
        for key, rows in tables.items():
            _write(self.export, key, rows)
        _write(self.export, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps({"conversion_lag_days": 2}))
        self.out = self.root / "out"

    def run(self) -> dict:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, None, ["run", "--export", str(self.export), "--profile",
                                                               str(self.profile), "--out", str(self.out)])
        assert code == 0
        return json.loads((self.out / "result.json").read_text())


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body):
    return sorted((f["condition_key"], f["severity"], f["entity"].get("scope_id") or f["entity"].get("cohort_id"),
                   f["entity"].get("constraint")) for f in body["findings"])


def obs(body, check):
    return [o["data"] for o in body["observations"] if o["check"] == check]


def constraint(scope, cohort="acq", lo="", hi="", dates="2026-08-01..2026-08-30", basis="conversions", role="acquisition",
               limit="60", cap=""):
    return {"cohort_id": cohort, "scope_id": scope, "objective": "purchase", "goal_action_ids": "A1",
            "value_basis": basis, "traffic_role": role, "minimum_spend": lo, "maximum_spend": hi,
            "protected_commitment": "false", "total_cap": cap, "approved_CPA_or_ROAS_limit": limit,
            "effective_dates": dates, "owner": "cmo", "source_ref": "brief-1"}


def daily(campaigns=("C1", "C2"), days=30, cost=50, conv=1, mature=True, cohort="acq"):
    start = date(2026, 8, 1)
    return [{"campaign_id": c, "date": (start + timedelta(days=i)).isoformat(), "goal_cohort": cohort, "budget_id": f"B{c}",
             "cost": cost, "clicks": 20, "impressions": 500, "conversions": conv, "value": 100,
             "lag_mature": "true" if mature else "false"} for i in range(days) for c in campaigns]


def response(scope, bs=1000, bo=20, ss=1500, so=30, low=28, state="approved", scenario="S1", model="M1"):
    return {"model_id": model, "scope_id": scope, "scenario_id": scenario, "baseline_window": "2026-08",
            "forecast_window": "2026-10", "baseline_spend": bs, "baseline_outcome": bo, "scenario_spend": ss,
            "scenario_outcome": so, "uncertainty_low": low, "uncertainty_high": so + 2, "response_method": "simulator",
            "assumptions": "stable CVR", "validity_domain": "±50% spend", "source_ref": "sim-1", "approved_state": state}


class AllocationTests(unittest.TestCase):
    def test_mixed_cohort_is_info_and_not_pooled(self):
        body = Case(self, {"external/allocation_constraints": [constraint("C1"), constraint("C2", role="brand")],
                           "custom/allocation_daily": daily()}).run()
        self.assertEqual(keys(body), [("mixed_goal_cohort", "Info", "acq", None)])
        self.assertEqual(obs(body, "pool_ledger"), [])

    def test_pooled_outcomes_are_summed_and_mature_only(self):
        rows = daily() + daily(campaigns=("C1",), cohort="other") + [
            {**daily(days=1)[0], "date": "2026-08-31", "lag_mature": "false", "conversions": 50}]
        body = Case(self, {"external/allocation_constraints": [constraint("C1"), constraint("C2")],
                           "custom/allocation_daily": rows}).run()
        d = obs(body, "pool_ledger")[0]
        self.assertEqual(d["conversions"], 60)
        self.assertAlmostEqual(d["cpa"], 50)
        self.assertEqual(cov(body, "pool_ledger")["status"], "partial")  # immature row excluded

    def test_maximum_breach_is_warning_minimum_waits_for_window_end(self):
        body = Case(self, {"external/allocation_constraints": [constraint("C1", hi="1000"), constraint("C2", lo="2000")],
                           "custom/allocation_daily": daily()}).run()
        self.assertEqual(keys(body), [("allocation_violates_constraint", "Warning", "C1", "maximum_spend"),
                                      ("allocation_violates_constraint", "Warning", "C2", "minimum_spend")])
        open_window = [constraint("C1"), constraint("C2", lo="2000", dates="2026-08-01..2026-09-30")]
        body = Case(self, {"external/allocation_constraints": open_window, "custom/allocation_daily": daily()}).run()
        self.assertEqual(body["findings"], [])

    def test_uncovered_effective_dates_are_partial(self):
        body = Case(self, {"external/allocation_constraints": [constraint("C1", hi="10", dates="2026-07-01..2026-08-30")],
                           "custom/allocation_daily": daily()}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "constraint_inventory")["status"], "partial")

    def test_total_cap_breach(self):
        cons = [constraint("C1", cap="2500"), constraint("C2", cap="2500")]
        body = Case(self, {"external/allocation_constraints": cons, "custom/allocation_daily": daily()}).run()
        self.assertIn(("allocation_violates_constraint", "Warning", "acq", "total_cap"), keys(body))

    def test_marginal_cpa_against_limit(self):
        tables = {"external/allocation_constraints": [constraint("C1"), constraint("C2")], "custom/allocation_daily": daily(),
                  "external/allocation_response": [response("C1"), response("C2", ss=800, so=17)]}
        body = Case(self, tables).run()
        self.assertEqual(keys(body), [("modeled_tradeoff_candidate", "Info", "C1", None)])
        f = body["findings"][0]
        self.assertAlmostEqual(f["calculation"]["marginal"], 50)
        self.assertFalse(f["evidence"]["robust_at_low_bound"])  # 500/8 = 62.5 > 60
        net = obs(body, "net_scenario")[0]
        self.assertEqual(net["net_delta_outcome"], 7)
        tables["external/allocation_constraints"] = [constraint("C1", limit="40"), constraint("C2", limit="40")]
        self.assertEqual(Case(self, tables).run()["findings"], [])

    def test_unapproved_model_or_constraint_violation_is_not_candidate(self):
        base = {"external/allocation_constraints": [constraint("C1", hi="1400"), constraint("C2")],
                "custom/allocation_daily": daily(days=30, cost=40)}
        body = Case(self, {**base, "external/allocation_response": [response("C1")]}).run()
        self.assertNotIn("modeled_tradeoff_candidate", [f["condition_key"] for f in body["findings"]])  # 1500 > max 1400
        body = Case(self, {"external/allocation_constraints": [constraint("C1"), constraint("C2")],
                           "custom/allocation_daily": daily(), "external/allocation_response": [response("C1", state="draft")]}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "marginal_response")["status"], "partial")
        shared = {"external/allocation_constraints": [constraint("C1"), constraint("C2")], "custom/allocation_daily": daily(),
                  "budgets": [{"id": "B1", "amount": "100", "shared": "true", "campaign_ids": "C1;C2"}],
                  "external/allocation_response": [response("C1")]}
        self.assertEqual(Case(self, shared).run()["findings"], [])

    def test_value_cohort_uses_marginal_roas(self):
        cons = [constraint("C1", basis="revenue", limit="3"), constraint("C2", basis="revenue", limit="3")]
        body = Case(self, {"external/allocation_constraints": cons, "custom/allocation_daily": daily(),
                           "external/allocation_response": [response("C1", bo=4000, so=6000, low=5800)]}).run()
        self.assertEqual(keys(body), [("modeled_tradeoff_candidate", "Info", "C1", None)])
        self.assertAlmostEqual(body["findings"][0]["calculation"]["marginal"], 4)
        self.assertTrue(body["findings"][0]["evidence"]["robust_at_low_bound"])


if __name__ == "__main__":
    unittest.main()
