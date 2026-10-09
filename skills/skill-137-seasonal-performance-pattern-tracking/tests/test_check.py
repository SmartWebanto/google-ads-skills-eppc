"""test_check.py — decision-boundary tests for skill-137 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-137-seasonal-performance-pattern-tracking/tests
rules:   Temp folders only; deterministic; no network.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial tests
"""
from __future__ import annotations

import calendar
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill137_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

MONTHLY, CONTEXT = "custom/seasonal_monthly", "external/seasonal_context"
ACCOUNT = [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
            "date_range_start": "2024-01-01", "date_range_end": "2025-12-31", "snapshot_date": "2026-01-10",
            "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]
CAMPAIGNS = [{"id": "C", "name": "C", "status": "ENABLED"}]
CONTEXT_ROWS = [{"campaign_id": "C", "event_id": "BF24", "date_range": "2024-11-25..2024-11-30",
                 "event_type": "promotion", "promotion_dates": "2024-11-25..2024-11-30", "inventory_constraint": "",
                 "tracking_change": "", "structural_change": "", "market_calendar": "IT", "evidence_ref": "cal"}]


def monthly(conv=None, clicks=None, basis=None, impressions=None):
    conv, clicks, basis, impressions = conv or {}, clicks or {}, basis or {}, impressions or {}
    rows = []
    for y in (2024, 2025):
        for m in range(1, 13):
            ym = f"{y}-{m:02d}"
            rows.append({"account_id": "c1", "campaign_id": "C", "year_month": ym, "goal_id": "g1",
                         "impressions": str(impressions.get(ym, 20000)), "clicks": str(clicks.get(ym, 1000)),
                         "cost": "1000", "conversions": str(conv.get(ym, 100)), "conversion_value": "5000",
                         "active_days": str(calendar.monthrange(y, m)[1]),
                         "tracking_basis": basis.get(ym, "gtag purchase"), "search_is_if_available": "< 10%",
                         "is_censoring": "bounded"})
    return rows


def build(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


class Case(unittest.TestCase):
    def run_check(self, rows, context=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        tables = {"account": ACCOUNT, "campaigns": CAMPAIGNS, MONTHLY: rows}
        if context:
            tables[CONTEXT] = CONTEXT_ROWS
        build(export, tables)
        prof = root / "profile.json"
        prof.write_text("{}")
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))


class Decline(Case):
    def test_recurring_decline_goes_to_review(self):
        body = self.run_check(monthly(conv={"2024-07": 60, "2025-07": 60}))
        self.assertIn("recurring_cvr_decline", self.keys(body, "Info"))
        [item] = [r for r in body["ai_review"] if r["condition_key"] == "recurring_cvr_decline"]
        self.assertEqual(item["outcomes"]["material_goal_risk"]["severity"], "Warning")
        self.assertEqual(self.keys(body, "Warning"), [])

    def test_one_cycle_decline_is_info(self):
        body = self.run_check(monthly(conv={"2025-07": 60}))
        self.assertIn("single_cycle_decline", self.keys(body, "Info"))
        self.assertEqual(body["ai_review"], [])

    def test_decline_at_or_below_threshold_ignored(self):
        body = self.run_check(monthly(conv={"2024-07": 75, "2025-07": 75}))
        self.assertNotIn("recurring_cvr_decline", self.keys(body))
        self.assertNotIn("single_cycle_decline", self.keys(body))

    def test_min_clicks_gate_on_season_side(self):
        body = self.run_check(monthly(conv={"2024-07": 3, "2025-07": 3}, clicks={"2024-07": 50, "2025-07": 50}))
        self.assertNotIn("recurring_cvr_decline", self.keys(body))

    def test_without_context_no_review(self):
        body = self.run_check(monthly(conv={"2024-07": 60, "2025-07": 60}), context=False)
        self.assertEqual(body["ai_review"], [])
        self.assertIn("single_cycle_decline", self.keys(body, "Info"))
        cov = next(c for c in body["coverage"] if c["check"] == "recurring_cvr_decline")
        self.assertEqual(cov["status"], "partial")

    def test_finalize_requires_goal_ref(self):
        self.run_check(monthly(conv={"2024-07": 60, "2025-07": 60}))
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = json.loads((out / "result.json").read_text())["ai_review"][0]["id"]
        dec = out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_goal_risk", "rationale": "x"}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 4)


class Cycles(Case):
    def test_two_complete_cycles_no_single_cycle_finding(self):
        body = self.run_check(monthly())
        self.assertNotIn("single_cycle", self.keys(body))

    def test_structural_break_reduces_cycles(self):
        body = self.run_check(monthly(basis={"2024-03": "old tag"}))
        self.assertIn("structural_break", self.keys(body, "Info"))
        self.assertIn("single_cycle", self.keys(body, "Info"))

    def test_censored_is_preserved(self):
        body = self.run_check(monthly())
        [o] = [o for o in body["observations"] if o["check"] == "is_context"]
        self.assertIsNone(o["data"]["series"][0]["search_is"])
        self.assertEqual(o["data"]["series"][0]["raw"], "< 10%")


class ConsecutiveCtr(Case):
    def test_three_declines_flagged_and_counterexample(self):
        imps = {"2025-09": 20000, "2025-10": 25000, "2025-11": 30000, "2025-12": 40000}
        body = self.run_check(monthly(impressions=imps))
        self.assertIn("consecutive_ctr_decline", self.keys(body, "Info"))
        imps["2025-11"] = 50000
        body = self.run_check(monthly(impressions=imps))
        self.assertNotIn("consecutive_ctr_decline", self.keys(body))


if __name__ == "__main__":
    unittest.main()
