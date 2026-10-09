"""test_check.py — decision-boundary tests for skill-117 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-117-ad-schedule-waste-analysis/tests
rules:   stdlib only; temp folders; runs check.py via subprocess with sys.executable; asserts decisions, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check tests
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
START = date(2026, 6, 1)  # Monday; 8 complete weeks to 2026-07-26
DATES = [START + timedelta(days=i) for i in range(56)]
HOURLY_HDR = ["account_id", "campaign_id", "date", "hour", "device", "network", "impressions", "clicks", "cost",
              "conversions", "conversion_value", "goal_id"]
BH_HDR = ["campaign_id", "weekday", "effective_range", "timezone", "open_at", "close_at",
          "live_or_asynchronous_handling", "holiday_override", "approved_schedule", "owner"]


def _load_module():
    spec = importlib.util.spec_from_file_location("skill117_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _csv(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def hrow(cid, d, h, cost, conv, clicks=10, imp=100, goal="g1", device="desktop"):
    return ["1", cid, d.isoformat(), h, device, "search", imp, clicks, cost, conv, conv * 50, goal]


def base_rows(cid="1", weekdays=range(1, 8)):
    """Every retained date (or listed weekdays), hours 9..16: cost 20, 1 conversion → CPA 20."""
    return [hrow(cid, d, h, 20, 1) for d in DATES if d.isoweekday() in weekdays for h in range(9, 17)]


def bh_rows(cid="2", handling="live", tz="Europe/Rome", holiday=None, skip=(), approved="open_hours",
            open_at="09:00", close_at="18:00"):
    out = []
    for wd in range(1, 8):
        if wd in skip:
            continue
        o, c = (open_at, close_at) if wd <= 5 else ("closed", "closed")
        out.append([cid, wd, "2026-01-01..2026-12-31", tz, o, c, handling, holiday if wd == 2 else "", approved,
                    "ops@client"])
    return out


PROFILE = {
    "campaign_objectives": {"1": {"goal_ids": ["g1"], "target_cpa": 30}, "2": {"goal_ids": ["g1"], "target_cpa": 30}},
    "schedule_efficiency_tolerance": 0.25,
    "tracking_verified": {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-07-26", "source_ref": "tag audit"}},
}


class Case:
    def __init__(self, test: unittest.TestCase, hourly=None, bh=None, profile=None, snapshot="2026-08-05",
                 bid_adj=True):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export, self.out = self.root / "export", self.root / "out"
        e = self.export
        _csv(e / "account.csv", ["customer_id", "currency_code", "time_zone", "date_range_start", "date_range_end",
                                 "snapshot_date", "rates_format", "money_unit", "conversion_date_basis",
                                 "conversion_lag_days"],
             [["1", "EUR", "Europe/Rome", "2026-06-01", "2026-07-26", snapshot, "fraction", "currency",
               "interaction_date", 2]])
        _csv(e / "campaigns.csv", ["id", "name", "status", "bidding_strategy_type", "target_cpa", "target_roas"],
             [["1", "Leads tCPA", "ENABLED", "TARGET_CPA", "", ""], ["2", "Leads manual", "ENABLED", "MANUAL_CPC", "", ""]])
        manifest = [["account.csv", "complete", "none", "", ""], ["campaigns.csv", "complete", "none", "", ""]]
        if bid_adj:
            _csv(e / "bid_adjustments.csv", ["campaign_id", "dimension", "criterion_id", "modifier"],
                 [["1", "AD_SCHEDULE", "mon-18", "0.8"]])
            manifest.append(["bid_adjustments.csv", "complete", "none", "", ""])
        if hourly is not None:
            _csv(e / "custom" / "schedule_hourly.csv", HOURLY_HDR, hourly)
            manifest.append(["custom/schedule_hourly.csv", "complete", "none", "2026-06-01", "2026-07-26"])
        if bh is not None:
            _csv(e / "external" / "business_hours.csv", BH_HDR, bh)
            manifest.append(["external/business_hours.csv", "complete", "none", "", ""])
        _csv(e / "table_manifest.csv", ["filename", "completeness", "truncation", "period_start", "period_end"],
             manifest)
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(PROFILE if profile is None else profile))

    def run(self) -> dict:
        p = subprocess.run([sys.executable, str(SCRIPT), "run", "--export", str(self.export), "--profile",
                            str(self.profile), "--out", str(self.out)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr + p.stdout
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions) -> int:
        d = self.root / "decisions.json"
        d.write_text(json.dumps(decisions))
        return subprocess.run([sys.executable, str(SCRIPT), "finalize", "--export", str(self.export), "--profile",
                               str(self.profile), "--out", str(self.out), "--decisions", str(d)],
                              capture_output=True, text=True).returncode


def findings(res, key, cid=None):
    return [f for f in res["findings"] if f["condition_key"] == key
            and (cid is None or f["entity"].get("campaign_id") == cid)]


def status(res, check):
    return next(c for c in res["coverage"] if c["check"] == check)["status"]


def reviews(res, key):
    return [r for r in res["ai_review"] if r["condition_key"] == key]


class EfficiencyTolerance(unittest.TestCase):
    def rows(self, monday18_cost, conv=2, weeks=None):
        mondays = [d for d in DATES if d.isoweekday() == 1][:weeks]
        return base_rows() + [hrow("1", d, 18, monday18_cost, conv) for d in mondays]

    def test_mature_block_beyond_tolerance_is_warning(self):
        res = Case(self, self.rows(100)).run()  # block CPA 50 vs rest 20 × 1.25
        f = findings(res, "block_misses_efficiency_tolerance", "1")
        self.assertEqual([x["entity"]["block"] for x in f], ["mon-18"])
        self.assertEqual(f[0]["severity"], "Warning")
        self.assertEqual(f[0]["evidence"]["block"]["conversions"], 16)

    def test_block_within_tolerance_is_not_flagged(self):
        res = Case(self, self.rows(45)).run()  # block CPA 22.5 <= 25
        self.assertEqual(findings(res, "block_misses_efficiency_tolerance"), [])

    def test_block_below_conversion_gate_is_info_only(self):
        res = Case(self, self.rows(50, conv=1)).run()  # 8 conversions < 15; cost 400 >= spend_floor 50
        self.assertEqual(findings(res, "block_misses_efficiency_tolerance"), [])
        self.assertEqual([f["severity"] for f in findings(res, "sparse_block", "1")], ["Info"])

    def test_single_week_block_is_not_recurring(self):
        res = Case(self, self.rows(800, conv=16, weeks=1)).run()
        self.assertEqual(findings(res, "block_misses_efficiency_tolerance"), [])
        self.assertEqual(findings(res, "sparse_block"), [])

    def test_missing_tolerance_is_partial_without_finding(self):
        profile = {k: v for k, v in PROFILE.items() if k != "schedule_efficiency_tolerance"}
        res = Case(self, self.rows(100), profile=profile).run()
        self.assertEqual(findings(res, "block_misses_efficiency_tolerance"), [])
        self.assertEqual(status(res, "recurring_block_efficiency"), "partial")

    def test_immature_window_blocks_performance_findings(self):
        res = Case(self, self.rows(100), snapshot="2026-07-27").run()
        self.assertEqual(findings(res, "block_misses_efficiency_tolerance"), [])
        self.assertEqual(status(res, "recurring_block_efficiency"), "partial")
        window = next(o for o in res["observations"] if o["check"] == "hourly_window")["data"]
        self.assertGreater(window["dropped_rows"]["immature"], 0)

    def test_undeclared_goal_is_not_compared(self):
        rows = base_rows() + [hrow("1", d, 18, 100, 2, goal="g9") for d in DATES if d.isoweekday() == 1]
        res = Case(self, rows).run()
        self.assertEqual(findings(res, "block_misses_efficiency_tolerance"), [])

    def test_conflicting_duplicate_grain_is_dropped(self):
        rows = self.rows(100) + [hrow("1", START, 18, 999, 0)]
        res = Case(self, rows).run()
        window = next(o for o in res["observations"] if o["check"] == "hourly_window")["data"]
        self.assertEqual(window["dropped_rows"]["duplicate_conflict"], 2)
        self.assertEqual(status(res, "hourly_window"), "partial")


class ZeroConversion(unittest.TestCase):
    def rows(self, cost):
        return base_rows() + [hrow("1", d, 22, cost, 0) for d in DATES if d.isoweekday() == 6]

    def test_material_zero_conversion_block_gets_provisional_info_and_review(self):
        res = Case(self, self.rows(10)).run()  # 80 >= spend_floor 50
        rv = [r for r in reviews(res, "zero_conversion_block") if r["entity"]["block"] == "sat-22"]
        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0]["outcomes"]["unserved_or_irrelevant"]["severity"], "Warning")
        prov = findings(res, "zero_conversion_block", "1")
        self.assertEqual([f["severity"] for f in prov], ["Info"])

    def test_block_below_spend_floor_is_not_screened(self):
        res = Case(self, self.rows(5)).run()  # 40 < 50
        self.assertEqual(reviews(res, "zero_conversion_block"), [])

    def test_unverified_tracking_disables_screen(self):
        profile = {k: v for k, v in PROFILE.items() if k != "tracking_verified"}
        res = Case(self, self.rows(10), profile=profile).run()
        self.assertEqual(reviews(res, "zero_conversion_block"), [])
        self.assertEqual(status(res, "zero_conversion_blocks"), "partial")


class ServiceConflict(unittest.TestCase):
    def rows(self):
        return base_rows("2", weekdays=range(1, 6)) + [hrow("2", d, 20, 15, 0, clicks=3) for d in DATES
                                                       if d.isoweekday() == 1]

    def test_live_only_closed_delivery_is_warning_and_holiday_counts(self):
        res = Case(self, self.rows(), bh_rows(holiday="2026-06-02=closed")).run()
        f = findings(res, "schedule_service_conflict", "2")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        hours = f[0]["evidence"]["hours"]
        self.assertIn("2026-06-01 20:00", hours)
        self.assertIn("2026-06-02 10:00", hours)
        self.assertNotIn("2026-06-09 10:00", hours)
        self.assertEqual(len(hours), 8 + 8)  # 8 Monday evenings + 8 hours on the holiday

    def test_asynchronous_handling_is_not_a_conflict(self):
        res = Case(self, self.rows(), bh_rows(handling="asynchronous")).run()
        self.assertEqual(findings(res, "schedule_service_conflict"), [])

    def test_approved_schedule_covering_the_hour_is_not_a_conflict(self):
        res = Case(self, self.rows(), bh_rows(approved="08:00-22:00")).run()
        self.assertEqual(findings(res, "schedule_service_conflict"), [])

    def test_timezone_mismatch_leaves_hours_unclassified(self):
        res = Case(self, self.rows(), bh_rows(tz="America/New_York")).run()
        self.assertEqual(findings(res, "schedule_service_conflict"), [])
        self.assertEqual(findings(res, "off_hours_share"), [])
        self.assertEqual(status(res, "business_calendar"), "partial")

    def test_missing_weekday_row_is_not_off_hours(self):
        res = Case(self, self.rows(), bh_rows(skip=(1,))).run()
        self.assertEqual(findings(res, "schedule_service_conflict"), [])
        self.assertEqual(findings(res, "off_hours_share"), [])
        self.assertEqual(status(res, "business_calendar"), "partial")

    def test_midnight_inside_documented_hours_is_not_off_hours(self):
        rows = [hrow("2", d, 0, 20, 1) for d in DATES if d.isoweekday() <= 5]
        res = Case(self, rows, bh_rows(open_at="00:00", close_at="24:00")).run()
        self.assertEqual(findings(res, "off_hours_share"), [])
        self.assertEqual(findings(res, "schedule_service_conflict"), [])

    def test_off_hours_share_uses_same_window_campaign_cost(self):
        res = Case(self, self.rows(), bh_rows(handling="asynchronous", holiday="2026-06-02=closed")).run()
        f = findings(res, "off_hours_share", "2")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertAlmostEqual(f[0]["evidence"]["off_hours_cost_share"], (8 * 15 + 8 * 20) / (40 * 8 * 20 + 8 * 15),
                               places=4)


class ControlsAndFinalize(unittest.TestCase):
    PROPOSAL = {"control": "schedule_exclusion", "blocks": ["mon-18"], "outcome_metric": "CPA of goal g1",
                "guardrails": ["weekly conversions >= 90% of baseline"], "rollback_owner": "ops@client"}

    def _case(self):
        rows = base_rows() + [hrow("1", d, 18, 100, 2) for d in DATES if d.isoweekday() == 1]
        case = Case(self, rows)
        res = case.run()
        rid = next(r["id"] for r in reviews(res, "schedule_experiment") if r["entity"]["campaign_id"] == "1")
        return case, rid

    def test_fixed_modifier_on_smart_bidding_is_rejected(self):
        case, rid = self._case()
        bad = {**self.PROPOSAL, "campaign_id": "1", "control": "bid_modifier", "modifier": 0.8}
        self.assertEqual(case.finalize([{"id": rid, "outcome": "experiment_proposed", "rationale": "x",
                                         "proposal": bad}]), 4)

    def test_incomplete_experiment_is_rejected(self):
        case, rid = self._case()
        bad = {**self.PROPOSAL, "campaign_id": "1", "rollback_owner": ""}
        self.assertEqual(case.finalize([{"id": rid, "outcome": "experiment_proposed", "rationale": "x",
                                         "proposal": bad}]), 4)

    def test_complete_exclusion_experiment_is_accepted(self):
        case, rid = self._case()
        self.assertEqual(case.finalize([{"id": rid, "outcome": "experiment_proposed", "rationale": "x",
                                         "proposal": {**self.PROPOSAL, "campaign_id": "1"}}]), 0)

    def test_modifier_allowed_on_manual_cpc(self):
        rows = base_rows("2", weekdays=range(1, 6)) + [hrow("2", d, 20, 15, 0, clicks=3) for d in DATES
                                                       if d.isoweekday() == 1]
        case = Case(self, rows, bh_rows())
        res = case.run()
        rv = next(r for r in reviews(res, "schedule_experiment") if r["entity"]["campaign_id"] == "2")
        proposal = {**self.PROPOSAL, "campaign_id": "2", "control": "bid_modifier",
                    "blocks": ["documented_unavailable_hours"]}
        self.assertEqual(case.finalize([{"id": rv["id"], "outcome": "experiment_proposed", "rationale": "x",
                                         "proposal": proposal}]), 0)


class MissingEvidence(unittest.TestCase):
    def test_absent_custom_and_external_files_skip_dependent_checks(self):
        res = Case(self, bid_adj=False).run()
        for check in ("hourly_window", "business_calendar", "heatmap_off_hours_share", "recurring_block_efficiency",
                      "service_conflict", "zero_conversion_blocks"):
            self.assertEqual(status(res, check), "skipped", check)
        ctrl = next(c for c in res["coverage"] if c["check"] == "control_applicability")
        self.assertEqual(ctrl["status"], "partial")
        self.assertIn("bid_adjustments (file)", ctrl["missing"])
        self.assertEqual(res["findings"], [])

    def test_dst_transition_date_is_detected(self):
        mod = _load_module()
        self.assertEqual(mod._dst_dates("Europe/Rome", [date(2026, 3, 28), date(2026, 3, 29), date(2026, 3, 30)]),
                         {date(2026, 3, 29)})
        self.assertIsNone(mod._dst_dates("Not/AZone", [date(2026, 3, 29)]))


if __name__ == "__main__":
    unittest.main()
