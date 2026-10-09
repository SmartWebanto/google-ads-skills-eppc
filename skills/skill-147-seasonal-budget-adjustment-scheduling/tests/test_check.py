"""test_check.py — decision-boundary tests for skill-147 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-147-seasonal-budget-adjustment-scheduling/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check147", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

PLAN_COLS = ["event_id", "campaign_id", "name", "start_at", "end_at", "timezone", "objective", "offer", "rationale",
             "owner", "approval_status", "normal_baseline_dates", "budget_id", "approved_total_cap",
             "baseline_daily_budget", "proposed_event_budget", "post_event_budget", "economic_target",
             "response_assumptions", "approval_ref"]
DAILY_COLS = ["account_id", "campaign_id", "date", "budget_id", "strategy_id", "goal_id", "impressions", "clicks",
              "cost", "conversions", "conversion_value", "conversion_date_basis", "maturity"]
RULE_COLS = ["account_id", "budget_id", "rule_id", "snapshot_at", "current_amount", "member_campaign_ids", "action",
             "scheduled_at", "timezone", "enabled", "last_result", "reversion_amount", "manual_override_owner"]


def plan(**kw):
    base = {"event_id": "E1", "campaign_id": "C1", "start_at": "2026-08-10", "end_at": "2026-08-20",
            "timezone": "Europe/Rome", "owner": "ops", "approval_status": "approved", "budget_id": "B1",
            "approved_total_cap": "1000", "baseline_daily_budget": "100", "proposed_event_budget": "100",
            "post_event_budget": "100", "economic_target": "CPA 40", "response_assumptions": "flat",
            "approval_ref": "A-1"}
    base.update(kw)
    return base


def daily(start, days, cost, cid="C1", bid="B1", **kw):
    d0 = date.fromisoformat(start)
    return [{"campaign_id": cid, "budget_id": bid, "date": (d0 + timedelta(i)).isoformat(), "cost": cost,
             "goal_id": kw.get("goal", "g1"), "impressions": kw.get("impr", "1000"), "clicks": kw.get("clicks", "20"),
             "conversions": kw.get("conv", "2"), "conversion_value": "200", "maturity": kw.get("maturity", "mature")}
            for i in range(days)]


class Case:
    def __init__(self, test, snapshot="2026-09-06", daily_complete="complete"):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.completeness = {}
        self.daily_complete = daily_complete
        self.write("account", ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
                               "conversion_lag_days"],
                   [{"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": "2"}])
        self.write("campaigns", ["id", "channel_type", "budget_id"], [{"id": "C1", "channel_type": "SEARCH",
                                                                         "budget_id": "B1"}])
        self.write("budgets", ["id", "amount", "campaign_ids", "shared"],
                   [{"id": "B1", "amount": "100", "campaign_ids": "C1", "shared": "false"}])

    def write(self, key, cols, rows):
        p = self.export / f"{key}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
        self.completeness[f"{key}.csv"] = self.daily_complete if key == "custom/seasonal_budget_daily" else "complete"

    def run(self):
        with (self.export / "table_manifest.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "completeness", "truncation"])
            for fn in sorted(self.completeness):
                w.writerow([fn, self.completeness[fn], "none"])
        prof = self.root / "profile.json"
        prof.write_text("{}")
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, None,
                              ["run", "--export", str(self.export), "--profile", str(prof), "--out", str(out)])
        assert code == 0
        return json.loads((out / "result.json").read_text())


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def _cap(self, cost, completeness="complete", extra=()):
        c = Case(self, daily_complete=completeness)
        c.write("external/seasonal_budget_plan", PLAN_COLS, [plan()])
        c.write("custom/seasonal_budget_daily", DAILY_COLS, daily("2026-08-10", 11, cost) + list(extra))
        return c.run()

    def test_material_breach_is_critical_immaterial_is_info(self):
        crit = keys(self._cap("100"), "approved_cap_breach")  # 1100 vs 1000 → overage 100 >= floor 50
        self.assertEqual([f["severity"] for f in crit], ["Critical"])
        self.assertEqual(crit[0]["calculation"]["overage"], 100)
        info = keys(self._cap("93"), "approved_cap_breach")  # 1023 → overage 23 < 50
        self.assertEqual([f["severity"] for f in info], ["Info"])

    def test_spend_within_cap_completed_only_when_daily_certified(self):
        ok = self._cap("90")
        self.assertFalse(keys(ok, "approved_cap_breach"))
        self.assertEqual(cov(ok, "budget_pool_cap")["status"], "completed")
        partial = self._cap("90", completeness="partial export")
        self.assertEqual(cov(partial, "budget_pool_cap")["status"], "partial")
        # incomplete rows are a lower bound: a breach is still proven
        breach = self._cap("100", completeness="partial export")
        self.assertEqual([f["severity"] for f in keys(breach, "approved_cap_breach")], ["Critical"])

    def test_conflicting_duplicate_daily_rows_void_the_pool_total(self):
        dup = daily("2026-08-10", 1, "500")
        body = self._cap("100", extra=dup)
        self.assertFalse(keys(body, "approved_cap_breach"))
        self.assertEqual(cov(body, "budget_pool_cap")["status"], "partial")

    def test_open_event_headroom_needs_a_stop_control(self):
        def case(manual):
            c = Case(self)
            c.write("external/seasonal_budget_plan", PLAN_COLS, [plan(end_at="2026-09-10", approved_total_cap="2500")])
            c.write("custom/seasonal_budget_daily", DAILY_COLS, daily("2026-08-10", 21, "100"))
            c.write("custom/seasonal_budget_rules", RULE_COLS,
                    [{"budget_id": "B1", "rule_id": "R1", "snapshot_at": "2026-08-30", "current_amount": "100",
                      "enabled": "", "action": "", "manual_override_owner": manual}])
            return c.run()
        # spend 2100, headroom 400 < 11 days x 100
        self.assertEqual(len(keys(case(""), "cap_headroom_without_stop_control")), 1)
        self.assertFalse(keys(case("ops lead"), "cap_headroom_without_stop_control"))

    def _conf(self, snapshot, amount, rule=None, **plan_kw):
        c = Case(self)
        c.write("external/seasonal_budget_plan", PLAN_COLS,
                [plan(proposed_event_budget="150", post_event_budget="100", **plan_kw)])
        r = {"budget_id": "B1", "rule_id": "R1", "snapshot_at": snapshot, "current_amount": amount,
             "timezone": "Europe/Rome"}
        r.update(rule or {})
        c.write("custom/seasonal_budget_rules", RULE_COLS, [r])
        return c.run()

    def test_in_window_amount_conflicts_with_approved_event_budget(self):
        self.assertEqual(len(keys(self._conf("2026-08-15", "120"), "schedule_conflict")), 1)
        self.assertFalse(keys(self._conf("2026-08-15", "150"), "schedule_conflict"))
        # unapproved plans are not compared with configuration
        self.assertFalse(keys(self._conf("2026-08-15", "120", approval_status="draft"), "schedule_conflict"))

    def test_post_event_restoration_conflict_after_end_only(self):
        self.assertEqual(len(keys(self._conf("2026-08-22", "150"), "restoration_conflict")), 1)
        self.assertFalse(keys(self._conf("2026-08-22", "100"), "restoration_conflict"))

    def test_reversion_rule_amount_and_manual_alternative(self):
        wrong = self._conf("2026-08-05", "100", {"reversion_amount": "80", "enabled": "true", "action": "set"})
        self.assertEqual(len(keys(wrong, "restoration_conflict")), 1)
        disabled = self._conf("2026-08-05", "100", {"reversion_amount": "100", "enabled": "false", "action": "set"})
        self.assertEqual(len(keys(disabled, "restoration_conflict")), 1)
        manual = self._conf("2026-08-05", "100", {"reversion_amount": "100", "enabled": "false", "action": "set",
                                                  "manual_override_owner": "ops"})
        self.assertFalse(keys(manual, "restoration_conflict"))
        none = self._conf("2026-08-05", "100")
        self.assertEqual([f["severity"] for f in keys(none, "restoration_control_unknown")], ["Info"])

    def test_increase_without_response_model_is_info_flat_is_valid(self):
        def case(**kw):
            c = Case(self)
            c.write("external/seasonal_budget_plan", PLAN_COLS, [plan(end_at="2026-10-01", **kw)])
            return c.run()
        inc = case(proposed_event_budget="200", response_assumptions="")
        self.assertEqual([f["severity"] for f in keys(inc, "missing_response_model")], ["Info"])
        self.assertFalse(keys(case(proposed_event_budget="100", response_assumptions=""), "missing_response_model"))
        self.assertFalse(keys(case(proposed_event_budget="200"), "missing_response_model"))

    def _perf(self, snapshot="2026-09-06", normal_goal="g1", clicks="20"):
        c = Case(self, snapshot=snapshot)
        c.write("external/seasonal_budget_plan", PLAN_COLS,
                [plan(normal_baseline_dates="2026-08-01..2026-08-07")])
        c.write("custom/seasonal_budget_daily", DAILY_COLS,
                daily("2026-08-01", 7, "50", goal=normal_goal, clicks=clicks, maturity="")
                + daily("2026-08-10", 11, "80", clicks=clicks, maturity=""))
        body = c.run()
        obs = [o for o in body["observations"] if o["check"] == "event_vs_normal"]
        return body, obs

    def test_event_vs_normal_gates(self):
        body, obs = self._perf()
        self.assertTrue(obs[0]["data"]["cvr_comparable"])  # 140 and 220 clicks >= 100
        self.assertFalse(obs[0]["data"]["cpa_roas_comparable"])  # 14 conversions < 15 in normal cohort
        _, low = self._perf(clicks="10")  # 70 normal clicks < 100
        self.assertFalse(low[0]["data"]["cvr_comparable"])
        mixed, mobs = self._perf(normal_goal="g2")
        self.assertEqual(cov(mixed, "event_vs_normal")["status"], "partial")
        self.assertFalse(mobs[0]["data"]["cvr_comparable"])
        immature, iobs = self._perf(snapshot="2026-08-31")  # lag 2 not reached: unlabeled rows excluded
        self.assertFalse(iobs[0]["data"]["cvr_comparable"])
        self.assertEqual(cov(immature, "event_vs_normal")["status"], "partial")

    def test_missing_plan_skips_every_check(self):
        c = Case(self)
        body = c.run()
        for chk in ("budget_pool_cap", "event_vs_normal", "response_scenarios", "schedule_conformance",
                    "schedule_draft"):
            self.assertEqual(cov(body, chk)["status"], "skipped")
        self.assertIn("external/seasonal_budget_plan (file)", cov(body, "schedule_draft")["missing"])
        self.assertFalse(body["findings"])


if __name__ == "__main__":
    unittest.main()
