"""test_check.py — decision-boundary tests for skill-152 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-152-historical-performance-benchmarking-seasonal-planning/tests
rules:   Temp folders only; stdlib only; assert condition keys, severities and coverage, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill152_check", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-04,2026-09-02,2026-09-06,fraction,currency,interaction_date,2\n")
PLAN_COLS = ("event_id,campaign_id,name,start_at,end_at,timezone,objective,offer,expected_cvr_change,rationale,owner,"
             "approval_status,normal_baseline_dates,historical_campaign_mapping,structural_breaks,"
             "tracking_basis_changes,proposed_cap,growth_assumptions,marginal_cpc_range,marginal_cvr_range,"
             "marginal_value_range,evidence_ref")
DAILY_HEAD = ("campaign_id,date,budget_id,strategy_id,goal_id,impressions,clicks,cost,conversions,conversion_value,"
              "conversion_date_basis,maturity,active_status,budget_lost_is_if_supported\n")
Y1, Y2 = date(2025, 11, 28), date(2024, 11, 29)


def plan_row(**kw):
    row = {"event_id": "bf", "campaign_id": "C1", "name": "BF", "start_at": "2026-11-27", "end_at": "2026-11-30",
           "timezone": "Europe/Rome", "objective": "sales", "offer": "promo", "expected_cvr_change": "",
           "rationale": "", "owner": "ana", "approval_status": "approved", "normal_baseline_dates": "",
           "historical_campaign_mapping": "", "structural_breaks": "", "tracking_basis_changes": "",
           "proposed_cap": "600", "growth_assumptions": "0.1", "marginal_cpc_range": "0.8;1.0;1.2",
           "marginal_cvr_range": "0.04;0.05;0.06", "marginal_value_range": "50;60;70", "evidence_ref": "plan-v1"}
    row.update(kw)
    return ",".join(row[c] for c in PLAN_COLS.split(","))


PAST = [plan_row(start_at="2025-11-28", end_at="2025-12-01"), plan_row(start_at="2024-11-29", end_at="2024-12-02")]


def days(start, cost, conv, value=None, n=4, cid="C1", goal="G", maturity="mature", clicks=100):
    value = conv * 60 if value is None else value
    return "".join(f"{cid},{start + timedelta(days=i)},B1,S1,{goal},1000,{clicks},{cost},{conv},{value},"
                   f"interaction_date,{maturity},ENABLED,0.1\n" for i in range(n))


def build(tmp, *, plan=None, daily=None, budgets=None, campaigns=None, daily_complete="complete", drop=()):
    files = {
        "account.csv": ACCOUNT,
        "campaigns.csv": campaigns or "id,name,status,target_cpa,target_roas\nC1,S,ENABLED,40,\n",
        "budgets.csv": "id,amount,shared,campaign_ids\nB1,200,false,C1\n",
        "external/seasonal_forecast_plan.csv": PLAN_COLS + "\n" + "\n".join(plan or [plan_row()] + PAST) + "\n",
        "custom/seasonal_benchmark_daily.csv": DAILY_HEAD + "".join(daily or []),
        "custom/benchmark_budget_history.csv": "budget_id,effective_from,effective_to,amount,member_campaign_ids\n"
                                               + (budgets or "B1,2024-01-01,,200,C1\n"),
    }
    for d in drop:
        files.pop(d)
    files["table_manifest.csv"] = "filename,completeness\n" + "".join(
        f"{n},{daily_complete if 'benchmark_daily' in n else 'complete'}\n" for n in list(files))
    root = tmp / "export"
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def main(*argv) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return M.cli.main(M.SKILL, M.VERSION, M.run, argv=list(argv))


class Base(unittest.TestCase):
    def run_check(self, **kw) -> dict:
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        ex = build(tmp, **kw)
        self.assertEqual(main("run", "--export", str(ex), "--out", str(tmp / "out")), 0)
        return json.loads((tmp / "out" / "result.json").read_text())

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)


# Y-2: cost 100/day, 5 conv/day → CPA 20 over 20 conversions (>= min_conversions 15)
BASELINE = days(Y2, 100, 5)


class AdverseEfficiency(Base):
    def test_cpa_worsening_over_20_percent_is_warning_and_10_percent_is_not(self):
        bad = self.run_check(daily=[BASELINE, days(Y1, 150, 5)])  # CPA 30: +50%
        self.assertEqual([f["severity"] for f in self.keys(bad, "adverse_yoy_efficiency")], ["Warning"])
        ok = self.run_check(daily=[BASELINE, days(Y1, 110, 5)])  # CPA 22: +10%
        self.assertEqual(self.keys(ok, "adverse_yoy_efficiency"), [])

    def test_min_conversions_gate_applies_to_baseline_side(self):
        body = self.run_check(daily=[days(Y2, 100, 2), days(Y1, 150, 5)])  # 8 baseline conversions < 15
        self.assertEqual(self.keys(body, "adverse_yoy_efficiency"), [])

    def test_goal_change_or_immature_window_blocks_verdict(self):
        goal = self.run_check(daily=[BASELINE, days(Y1, 150, 5, goal="G2")])
        self.assertEqual(self.keys(goal, "adverse_yoy_efficiency"), [])
        immature = self.run_check(daily=[BASELINE, days(Y1, 150, 5, maturity="pending")])
        self.assertEqual(self.keys(immature, "adverse_yoy_efficiency"), [])

    def test_missing_day_makes_window_incomparable(self):
        body = self.run_check(daily=[BASELINE, days(Y1, 200, 7, n=3)])
        self.assertEqual(self.keys(body, "adverse_yoy_efficiency"), [])

    def test_declared_break_routes_to_review_with_provisional_info(self):
        body = self.run_check(plan=[plan_row(structural_breaks="2025-06 campaign split")] + PAST,
                              daily=[BASELINE, days(Y1, 150, 5)])
        self.assertEqual([f["severity"] for f in self.keys(body, "adverse_yoy_efficiency")], ["Info"])
        review = next(r for r in body["ai_review"] if r["condition_key"] == "adverse_yoy_efficiency")
        self.assertEqual(review["outcomes"]["comparable"]["severity"], "Warning")

    def test_roas_goal_uses_value_efficiency(self):
        camps = "id,name,status,target_cpa,target_roas\nC1,S,ENABLED,,4\n"
        bad = self.run_check(campaigns=camps, daily=[days(Y2, 100, 5, value=500), days(Y1, 100, 5, value=300)])
        self.assertEqual([f["severity"] for f in self.keys(bad, "adverse_yoy_efficiency")], ["Warning"])
        # CPA doubles but ROAS holds: no verdict for a ROAS goal
        ok = self.run_check(campaigns=camps, daily=[days(Y2, 100, 5, value=500), days(Y1, 100, 5, value=500)])
        self.assertEqual(self.keys(ok, "adverse_yoy_efficiency"), [])

    def test_unknown_goal_metric_is_partial(self):
        body = self.run_check(campaigns="id,name,status\nC1,S,ENABLED\n", daily=[BASELINE, days(Y1, 150, 5)])
        self.assertEqual(self.keys(body, "adverse_yoy_efficiency"), [])
        self.assertEqual(self.cov(body, "adverse_efficiency")["status"], "partial")


class History(Base):
    def test_no_prior_rows_is_info_only_with_complete_inventory(self):
        body = self.run_check(daily=[days(date(2026, 8, 1), 10, 1)])
        self.assertEqual([f["severity"] for f in self.keys(body, "no_comparable_prior_period")], ["Info"])
        partial = self.run_check(daily=[days(date(2026, 8, 1), 10, 1)], daily_complete="partial export")
        self.assertEqual(self.keys(partial, "no_comparable_prior_period"), [])
        self.assertEqual(self.cov(partial, "yoy_changes")["status"], "partial")

    def test_budget_utilization_counts_only_days_with_all_member_costs(self):
        body = self.run_check(daily=[BASELINE, days(Y1, 150, 5)])
        obs = next(o for o in body["observations"] if o["check"] == "budget_utilization"
                   and o["data"].get("budget_id") == "B1" and o["data"]["window"].startswith("2025"))
        self.assertAlmostEqual(obs["data"]["utilization"], 0.75)
        shared = self.run_check(daily=[BASELINE, days(Y1, 150, 5)], budgets="B1,2024-01-01,,200,C1;C3\n")
        obs = next(o for o in shared["observations"] if o["check"] == "budget_utilization"
                   and o["data"].get("budget_id") == "B1" and o["data"]["window"].startswith("2025"))
        self.assertIsNone(obs["data"]["utilization"])
        self.assertEqual(self.cov(shared, "budget_utilization")["status"], "partial")


class Forecast(Base):
    # Y-1 clicks 400 × 1.1 = 440; base spend 440 × 1.0 = 440; high 528
    HIST = [BASELINE, days(Y1, 110, 5)]

    def test_base_spend_over_approved_cap_is_warning(self):
        body = self.run_check(plan=[plan_row(proposed_cap="400")] + PAST, daily=self.HIST)
        self.assertEqual([f["severity"] for f in self.keys(body, "forecast_exceeds_approved_cap")], ["Warning"])

    def test_within_cap_or_unapproved_is_not_warning(self):
        within = self.run_check(plan=[plan_row(proposed_cap="500")] + PAST, daily=self.HIST)
        self.assertEqual(self.keys(within, "forecast_exceeds_approved_cap"), [])
        draft = self.run_check(plan=[plan_row(proposed_cap="400", approval_status="draft")] + PAST, daily=self.HIST)
        self.assertEqual(self.keys(draft, "forecast_exceeds_approved_cap"), [])

    def test_missing_growth_model_is_info_and_no_scenarios(self):
        body = self.run_check(plan=[plan_row(growth_assumptions="", proposed_cap="100")] + PAST, daily=self.HIST)
        self.assertEqual([f["severity"] for f in self.keys(body, "unspecified_growth_model")], ["Info"])
        self.assertEqual(self.keys(body, "forecast_exceeds_approved_cap"), [])

    def test_unordered_range_is_partial_not_a_forecast(self):
        body = self.run_check(plan=[plan_row(marginal_cpc_range="1.2;1.0;0.8", proposed_cap="100")] + PAST,
                              daily=self.HIST)
        self.assertEqual(self.keys(body, "forecast_exceeds_approved_cap"), [])
        self.assertEqual(self.cov(body, "forecast_scenarios")["status"], "partial")


class Coverage(Base):
    def test_missing_plan_skips_all_checks(self):
        body = self.run_check(drop=("external/seasonal_forecast_plan.csv",))
        self.assertEqual({c["status"] for c in body["coverage"]}, {"skipped"})
        self.assertEqual(body["findings"], [])

    def test_missing_daily_skips_history_checks_but_plan_info_still_runs(self):
        body = self.run_check(plan=[plan_row(growth_assumptions="")] + PAST,
                              drop=("custom/seasonal_benchmark_daily.csv",))
        self.assertEqual(self.cov(body, "yoy_changes")["status"], "skipped")
        self.assertIn("custom/seasonal_benchmark_daily (file)", self.cov(body, "yoy_changes")["missing"])
        self.assertEqual(len(self.keys(body, "unspecified_growth_model")), 1)


if __name__ == "__main__":
    unittest.main()
