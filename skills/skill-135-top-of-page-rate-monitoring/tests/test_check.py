"""test_check.py — decision-boundary tests for skill-135 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-135-top-of-page-rate-monitoring/tests
rules:   Temp folders only; deterministic; no network.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill135_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

DAILY = "custom/search_prominence_daily"
WEEKLY = "custom/search_prominence_weekly"


def account(snapshot="2026-09-06"):
    return [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
             "date_range_start": "2026-08-03", "date_range_end": "2026-08-30", "snapshot_date": snapshot,
             "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]


def build(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(rows[0]) if rows else []
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def daily_rows(days=14, basis="native", network="GOOGLE_SEARCH", drop_after=7):
    out = []
    for i in range(days):
        d = date(2026, 8, 3) + timedelta(days=i)
        hi = i < drop_after
        out.append({"account_id": "c1", "campaign_id": "P", "ad_group_id": "G", "date": d.isoformat(),
                    "network": network, "impressions": "10000", "clicks": "500", "cost": "500",
                    "conversions": "20", "conversion_value": "2000",
                    "top_impression_rate": "0.9" if hi else "0.6",
                    "absolute_top_impression_rate": "0.5" if hi else "0.3",
                    "search_top_impression_share": "0.8" if hi else "0.4",
                    "search_absolute_top_impression_share": "0.4" if hi else "0.2",
                    "rate_counting_basis": basis, "share_censoring": "uncensored"})
    return out


def week(start: date, top: str, imps="5000", days=6, share="0.5"):
    return {"account_id": "c1", "campaign_id": "P", "ad_group_id": "G", "network": "GOOGLE_SEARCH",
            "period_start": start.isoformat(), "period_end": (start + timedelta(days=days)).isoformat(),
            "impressions": imps, "top_impression_rate": top, "absolute_top_impression_rate": "0.2",
            "search_top_impression_share": share, "search_absolute_top_impression_share": "0.1",
            "share_censoring": "uncensored", "source": "Ads UI", "extracted_at": "2026-09-06"}


BASE = {"campaigns": [{"id": "P", "name": "P", "status": "ENABLED", "channel_type": "SEARCH",
                       "bidding_strategy_type": "TARGET_CPA", "target_cpa": "50"}],
        "campaign_metrics": [{"campaign_id": "P", "impressions": "140000", "clicks": "7000", "cost": "7000",
                              "conversions": "280", "conversion_value": "28000"}]}


class Case(unittest.TestCase):
    def run_check(self, tables, profile=None, snapshot="2026-09-06"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        build(export, {"account": account(snapshot), **BASE, **tables})
        prof = root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        self.paths = (export, prof, root / "out")
        ctx = M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof)
        return ctx.finish()

    @staticmethod
    def cov(body, cid):
        return next(c for c in body["coverage"] if c["check"] == cid)

    @staticmethod
    def keys(body, sev=None):
        return [f["condition_key"] for f in body["findings"] if sev in (None, f["severity"])]


class DailyOnly(Case):
    def test_daily_decline_never_becomes_weekly_warning(self):
        body = self.run_check({DAILY: daily_rows()}, {"visibility_tolerance_percentage_points": 10})
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertIn("weekly_aggregate_unsupported", self.keys(body, "Info"))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.cov(body, "weekly_comparison")["status"], "skipped")

    def test_mixed_counting_bases_is_info(self):
        rows = daily_rows()
        rows[0]["rate_counting_basis"] = "other basis"
        body = self.run_check({DAILY: rows})
        self.assertIn("incompatible_counting_bases", self.keys(body, "Info"))

    def test_single_basis_has_no_basis_finding(self):
        body = self.run_check({DAILY: daily_rows()})
        self.assertNotIn("incompatible_counting_bases", self.keys(body))

    def test_partner_rows_excluded(self):
        body = self.run_check({DAILY: daily_rows(network="SEARCH_PARTNERS")})
        self.assertEqual(self.cov(body, "daily_native_metrics")["status"], "partial")
        self.assertNotIn("weekly_aggregate_unsupported", self.keys(body))

    def test_missing_daily_is_skipped_with_columns(self):
        rows = [{k: v for k, v in r.items() if k != "rate_counting_basis"} for r in daily_rows()]
        body = self.run_check({DAILY: rows})
        c = self.cov(body, "daily_native_metrics")
        self.assertEqual(c["status"], "skipped")
        self.assertIn(f"{DAILY}:rate_counting_basis", c["missing"])
        self.assertEqual(body["findings"], [])


class Weekly(Case):
    W1, W2 = date(2026, 8, 17), date(2026, 8, 24)

    def test_decline_over_tolerance_goes_to_review_with_provisional_info(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.9"), week(self.W2, "0.6")]},
                              {"visibility_tolerance_percentage_points": 10})
        self.assertIn("prominence_decline_exceeds_tolerance", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Warning"), [])
        [item] = body["ai_review"]
        self.assertEqual(item["outcomes"]["conflicts_visibility_goal"]["severity"], "Warning")

    def test_decline_within_tolerance_is_not_flagged(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.65"), week(self.W2, "0.6")]},
                              {"visibility_tolerance_percentage_points": 10})
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["ai_review"], [])

    def test_no_tolerance_is_info_only(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.9"), week(self.W2, "0.6")]})
        self.assertEqual(self.keys(body), ["prominence_decline_no_tolerance"])
        self.assertEqual(body["ai_review"], [])

    def test_min_impressions_gate_on_either_side(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.9", imps="999"), week(self.W2, "0.6")]},
                              {"visibility_tolerance_percentage_points": 10})
        self.assertEqual(body["findings"], [])

    def test_immature_window_disables_review(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.9"), week(self.W2, "0.6")]},
                              {"visibility_tolerance_percentage_points": 10}, snapshot="2026-08-31")
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.cov(body, "weekly_comparison")["status"], "partial")

    def test_incomplete_week_is_rejected(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.9", days=5), week(self.W2, "0.6")]},
                              {"visibility_tolerance_percentage_points": 10})
        self.assertEqual(body["findings"], [])
        self.assertEqual(self.cov(body, "weekly_comparison")["status"], "partial")

    def test_target_gap_info_and_counterexample(self):
        prof = {"campaign_objectives": {"P": {"target_search_top_impression_share": 0.7}}}
        body = self.run_check({WEEKLY: [week(self.W1, "0.6"), week(self.W2, "0.6", share="0.5")]}, prof)
        self.assertIn("below_visibility_target", self.keys(body, "Info"))
        body = self.run_check({WEEKLY: [week(self.W1, "0.6"), week(self.W2, "0.6", share="0.75")]}, prof)
        self.assertNotIn("below_visibility_target", self.keys(body))

    def test_target_gap_skipped_without_profile_target(self):
        body = self.run_check({WEEKLY: [week(self.W1, "0.6"), week(self.W2, "0.6")]})
        self.assertEqual(self.cov(body, "visibility_target_gap")["status"], "skipped")


class Finalize(Case):
    def test_warning_needs_goal_ref(self):
        body = self.run_check({WEEKLY: [week(date(2026, 8, 17), "0.9"), week(date(2026, 8, 24), "0.6")]},
                              {"visibility_tolerance_percentage_points": 10})
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = json.loads((out / "result.json").read_text())["ai_review"][0]["id"]
        dec = out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "conflicts_visibility_goal", "rationale": "goal stated"}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "conflicts_visibility_goal", "rationale": "goal stated",
                                    "proposal": {"goal_ref": "profile.objectives[0]"}}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"]
                          if f["condition_key"] == "prominence_decline_exceeds_tolerance"], ["Warning"])


if __name__ == "__main__":
    unittest.main()
