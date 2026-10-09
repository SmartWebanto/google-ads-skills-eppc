"""test_check.py — skill-049 boundaries: pacing bounds, hard-cap materiality, MTD completeness, overdelivery, logs.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-049-budget-overspend-underspend-alert-configuration/tests
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
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check049", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

START, END = date(2026, 8, 1), date(2026, 9, 10)


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0]) if rows else ["scope_id"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _dates(a, b):
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def build(root: Path, *, sept_cost=100.0, last_cost=None, cap=3000, kind="cap", bounds=(0.85, 1.15),
          incomplete=(), history_amount=None, rules=None, rules_complete=True, logs=None, drop=()):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                 "date_range_start": START.isoformat(), "date_range_end": END.isoformat(),
                                 "snapshot_date": "2026-09-12", "conversion_lag_days": 1, "money_unit": "currency"}])
    daily = []
    for d in _dates(START, END):
        if d in drop:
            continue
        cost = sept_cost if d.month == 9 else 100.0
        if d == END and last_cost is not None:
            cost = last_cost
        daily.append({"campaign_id": "C1", "date": d.isoformat(), "budget_id": "b1", "cost": cost,
                      "billed_cost_if_available": "", "complete_day": "false" if d in incomplete else "true",
                      "source_ref": "ads"})
    _write(ex / "custom" / "budget_alert_daily.csv", daily)
    plan = [{"scope_id": "acct", "scope_type": "account", "date": d.isoformat(), "approved_month_total": cap,
             "planned_spend": 100, "cap_or_target": kind, "spend_basis": "cost", "timezone": "Europe/Rome",
             "warning_lower_ratio": bounds[0] if bounds else "", "warning_upper_ratio": bounds[1] if bounds else "",
             "owner": "finance", "approved_at": "2026-08-25", "source_ref": "plan"}
            for d in _dates(date(2026, 9, 1), date(2026, 9, 30))]
    _write(ex / "external" / "budget_alert_plan.csv", plan)
    files = {"account.csv": "complete", "custom/budget_alert_daily.csv": "complete",
             "external/budget_alert_plan.csv": "complete"}
    if history_amount is not None:
        _write(ex / "custom" / "budget_history.csv", [{"budget_id": "b1", "effective_from": START.isoformat(),
                                                       "effective_to": "", "amount": history_amount,
                                                       "member_campaign_ids": "C1", "source_ref": "h"}])
        files["custom/budget_history.csv"] = "complete"
    if rules is not None:
        _write(ex / "external" / "budget_alert_rules.csv", rules)
        files["external/budget_alert_rules.csv"] = "complete" if rules_complete else "partial"
    if logs is not None:
        _write(ex / "custom" / "budget_alert_history.csv", logs)
        files["custom/budget_alert_history.csv"] = "complete"
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": c, "truncation": "none"} for f, c in files.items()])
    p = root / "profile.json"
    p.write_text(json.dumps({}))
    return ex, p


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def sev(body, key):
    return sorted(f["severity"] for f in body["findings"] if f["condition_key"] == key)


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


RULE_COLS = dict.fromkeys(["scope_id", "rule_id", "version", "enabled", "cadence", "timezone", "lookback", "data_lag",
                           "condition", "severity", "dedupe_key", "cooldown", "owner_role", "approved_state"], "")


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_on_plan_spend_has_no_finding(self):
        body = run(*build(self.root))
        self.assertEqual(body["findings"], [])
        obs = [o["data"] for o in body["observations"] if o["check"] == "mtd_pacing" and "ratio" in o["data"]][0]
        self.assertAlmostEqual(obs["ratio"], 1.0)
        self.assertEqual(cov(body)["mtd_pacing"], "completed")

    def test_pacing_outside_approved_bounds_is_warning_and_forecast_is_info(self):
        body = run(*build(self.root, sept_cost=150.0))
        self.assertEqual(sev(body, "pacing_outside_approved_bounds"), ["Warning"])
        self.assertEqual(sev(body, "forecast_cap_risk"), ["Info"])
        self.assertEqual(sev(body, "hard_cap_breach"), [])

    def test_unapproved_bounds_never_warn(self):
        body = run(*build(self.root, sept_cost=150.0, bounds=None))
        self.assertEqual(sev(body, "pacing_outside_approved_bounds"), [])
        obs = [o["data"] for o in body["observations"] if o["data"].get("outside_defaults") is not None]
        self.assertTrue(obs[0]["outside_defaults"])

    def test_material_hard_cap_breach_is_critical(self):
        body = run(*build(self.root, sept_cost=150.0, cap=1200))
        self.assertEqual(sev(body, "hard_cap_breach"), ["Critical"])
        f = [f for f in body["findings"] if f["condition_key"] == "hard_cap_breach"][0]
        self.assertAlmostEqual(f["evidence"]["excess"], 300)

    def test_sub_floor_cap_excess_is_warning(self):
        body = run(*build(self.root, sept_cost=150.0, cap=1480))
        self.assertEqual(sev(body, "hard_cap_breach"), ["Warning"])

    def test_target_is_not_a_hard_cap(self):
        body = run(*build(self.root, sept_cost=150.0, cap=1200, kind="target"))
        self.assertEqual(sev(body, "hard_cap_breach"), [])

    def test_incomplete_mtd_day_blocks_monthly_status(self):
        body = run(*build(self.root, sept_cost=150.0, cap=1200, incomplete=(date(2026, 9, 5),)))
        self.assertEqual(sev(body, "hard_cap_breach") + sev(body, "pacing_outside_approved_bounds"), [])
        self.assertEqual(cov(body)["mtd_pacing"], "partial")

    def test_daily_overdelivery_is_info_only(self):
        body = run(*build(self.root, history_amount=80))
        self.assertEqual(sev(body, "daily_overdelivery"), ["Info"])
        self.assertFalse(any(f["severity"] != "Info" for f in body["findings"]))
        body = run(*build(self.root, history_amount=150))
        self.assertEqual(sev(body, "daily_overdelivery"), [])

    def test_weekday_anomaly_goes_to_review(self):
        body = run(*build(self.root, last_cost=400.0))
        items = [r for r in body["ai_review"] if r["condition_key"] == "unexplained_spend_anomaly"]
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["evidence"]["change"], 3.0)
        self.assertEqual(items[0]["outcomes"]["unexplained_material"]["severity"], "Warning")

    def test_anomaly_needs_thirty_prior_days(self):
        body = run(*build(self.root, last_cost=400.0, drop=(date(2026, 8, 20),)))
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "unexplained_spend_anomaly"], [])
        self.assertEqual(cov(body)["weekday_anomaly"], "partial")

    def test_absent_monitoring_needs_complete_inventory(self):
        other = [{**RULE_COLS, "scope_id": "other", "rule_id": "r1", "enabled": "true", "approved_state": "approved"}]
        body = run(*build(self.root, rules=other))
        self.assertEqual(sev(body, "monitoring_absent"), ["Info"])
        body = run(*build(self.root, rules=other, rules_complete=False))
        self.assertEqual(sev(body, "monitoring_absent"), [])
        self.assertEqual(cov(body)["rule_inventory"], "partial")

    def test_undelivered_trigger_and_short_log_window(self):
        logs = [{"scope_id": "acct", "rule_id": "r1", "evaluated_at": "2026-09-09", "condition": "ratio>1.15",
                 "observed_value": 1.2, "threshold": 1.15, "triggered": "true", "notification_status": "FAILED",
                 "resolved_at": ""}]
        body = run(*build(self.root, logs=logs))
        self.assertEqual(sev(body, "alert_notification_undelivered"), ["Info"])
        self.assertEqual(cov(body)["alert_history"], "partial")

    def test_finalize_rejects_mutating_proposal(self):
        ex, prof = build(self.root, last_cost=400.0)
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                         ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "unexplained_material", "rationale": "no log",
                                    "proposal": {"action": "pause campaign C1"}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "unexplained_material", "rationale": "no log",
                                    "proposal": {"action": "notify owner"}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 0)

    def test_missing_plan_is_skipped_not_passed(self):
        ex, prof = build(self.root)
        (ex / "external" / "budget_alert_plan.csv").unlink()
        body = run(ex, prof)
        self.assertEqual(cov(body)["mtd_pacing"], "skipped")
        self.assertEqual(body["findings"], [])


if __name__ == "__main__":
    unittest.main()
