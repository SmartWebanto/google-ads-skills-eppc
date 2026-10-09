"""test_check.py — decision-boundary tests for skill-146 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-146-seasonality-bid-adjustment-deployment/tests
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
_spec = importlib.util.spec_from_file_location("skill146_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

DAILY, EVENTS, SETTINGS = "custom/event_cvr_daily", "external/seasonality_events", "custom/seasonality_settings"
SET_COLS = ["account_id", "adjustment_id", "snapshot_at", "name", "scope_type", "campaign_ids", "strategy_ids",
            "device_scope", "start_at", "end_at", "timezone", "cvr_adjustment_percent", "status",
            "supported_control_evidence", "source_screen"]


def build(root: Path, tables: dict, incomplete=()) -> None:
    manifest = []
    for key, (cols, rows) in tables.items():
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "truncation": "none",
                         "completeness": "partial" if key in incomplete else "complete"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def t(rows):
    return (list(rows[0]), rows)


ACCOUNT = t([{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
              "date_range_start": "2026-08-01", "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06",
              "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}])
CAMPAIGNS = t([{"id": "S", "name": "S", "status": "ENABLED", "channel_type": "SEARCH",
                "bidding_strategy_type": "TARGET_CPA", "target_cpa": "50"},
               {"id": "TR", "name": "TR", "status": "ENABLED", "channel_type": "TRAVEL",
                "bidding_strategy_type": "TARGET_CPA", "target_cpa": "50"}])


def daily(clicks=1000, maturity="mature"):
    rows = []
    for i in range(33):
        d = date(2026, 8, 1) + timedelta(days=i)
        role = "event" if d in (date(2026, 8, 29), date(2026, 8, 30)) else "post_event" if d > date(2026, 8, 30) else "normal"
        conv = clicks * (0.15 if role == "event" else 0.10)
        rows.append({"account_id": "c1", "campaign_id": "S", "date": d.isoformat(), "goal_id": "purchase",
                     "impressions": "10000", "clicks": str(clicks), "cost": "1000", "conversions": f"{conv:g}",
                     "conversion_value": "0", "conversion_date_basis": "interaction_date",
                     "maturity": maturity, "period_role": role})
    return t(rows)


def event(eid="SALE", start="2026-08-29T00:00:00+02:00", end="2026-08-31T00:00:00+02:00", change="0.5",
          reason="NONE: return to normal", rng="", baseline="2026-08-01 through 2026-08-28"):
    return {"event_id": eid, "campaign_id": "S", "name": eid, "start_at": start, "end_at": end,
            "timezone": "Europe/Rome", "objective": "purchase", "offer": "x", "expected_cvr_change": change,
            "rationale": "r", "owner": "o", "approval_status": "documented", "normal_baseline_dates": baseline,
            "exceptional_future_reason": reason, "expected_start": "", "expected_end": "",
            "estimate_range": rng, "evidence_ref": "cal"}


def setting(aid="A1", start="2026-08-31", end="2026-09-05", pct="-20", camp="S"):
    return {"account_id": "c1", "adjustment_id": aid, "snapshot_at": "2026-09-06", "name": aid, "scope_type": "CAMPAIGN",
            "campaign_ids": camp, "strategy_ids": "", "device_scope": "ALL", "start_at": start, "end_at": end,
            "timezone": "Europe/Rome", "cvr_adjustment_percent": pct, "status": "ENABLED",
            "supported_control_evidence": "ui", "source_screen": "ui"}


class Case(unittest.TestCase):
    def run_check(self, events, settings=None, dly=None, incomplete=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        tables = {"account": ACCOUNT, "campaigns": CAMPAIGNS, DAILY: dly or daily(), EVENTS: t(events)}
        if settings is not None:
            tables[SETTINGS] = (SET_COLS, settings)
        build(export, tables, incomplete)
        prof = root / "profile.json"
        prof.write_text("{}")
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    @staticmethod
    def cov(body, cid):
        return next(c for c in body["coverage"] if c["check"] == cid)


class PostEvent(Case):
    def test_routine_return_is_info_without_settings(self):
        body = self.run_check([event()], settings=[])
        self.assertEqual(self.keys(body), ["routine_post_event_return"])
        obs = next(o for o in body["observations"] if o["check"] == "normal_baseline")
        self.assertAlmostEqual(obs["data"]["normal"]["cvr"], 0.10)
        self.assertAlmostEqual(obs["data"]["event_vs_normal"], 0.5)
        self.assertAlmostEqual(obs["data"]["post_vs_normal"], 0.0)

    def test_retrospective_negative_setting_is_warning(self):
        body = self.run_check([event()], settings=[setting()])
        self.assertIn("retrospective_negative_adjustment", self.keys(body, "Warning"))

    def test_negative_setting_justified_by_exceptional_event(self):
        exc = event("OUTAGE", start="2026-08-31", end="2026-09-05", change="-0.2",
                    reason="warehouse closure documented", rng="-30 to -10")
        body = self.run_check([event(), exc], settings=[setting()])
        self.assertNotIn("retrospective_negative_adjustment", self.keys(body))
        self.assertNotIn("setting_contradicts_event", self.keys(body))

    def test_settings_unknown_is_partial_not_pass(self):
        body = self.run_check([event()])
        self.assertEqual(self.cov(body, "post_event_return")["status"], "partial")
        self.assertEqual(self.cov(body, "settings_conflicts")["status"], "skipped")


class Settings(Case):
    def test_undocumented_setting_warning_only_on_complete_calendar(self):
        s = setting("A9", start="2026-09-20", end="2026-09-22", pct="30")
        body = self.run_check([event()], settings=[s])
        self.assertIn("no_documented_event", self.keys(body, "Warning"))
        body = self.run_check([event()], settings=[s], incomplete=(EVENTS,))
        self.assertIn("no_documented_event", self.keys(body, "Info"))
        self.assertNotIn("no_documented_event", self.keys(body, "Warning"))

    def test_sign_and_range_contradictions(self):
        fut = event("BF", start="2026-09-20", end="2026-09-22", change="0.4", reason="", rng="20% to 50%")
        body = self.run_check([fut], settings=[setting("A2", "2026-09-20", "2026-09-22", "-30")])
        self.assertIn("setting_contradicts_event", self.keys(body, "Warning"))
        body = self.run_check([fut], settings=[setting("A2", "2026-09-20", "2026-09-22", "40")])
        self.assertNotIn("setting_contradicts_event", self.keys(body))

    def test_travel_scope_unsupported(self):
        s = setting("A3", start="2026-09-20", end="2026-09-22", pct="30", camp="TR")
        body = self.run_check([event()], settings=[s])
        self.assertIn("unsupported_scope", self.keys(body, "Info"))


class Future(Case):
    FUT = dict(eid="BF", start="2026-09-20", end="2026-09-22", change="0.4", reason="", rng="20% to 50%")

    def test_future_event_goes_to_review(self):
        body = self.run_check([event(**self.FUT)], settings=[])
        [item] = [r for r in body["ai_review"] if r["condition_key"] == "future_adjustment"]
        self.assertAlmostEqual(item["evidence"]["implied_adjustment_percent"], 40)

    def test_sparse_or_immature_baseline_is_info_without_review(self):
        for dly in (daily(clicks=3), daily(maturity="immature")):
            body = self.run_check([event(**self.FUT)], settings=[], dly=dly)
            self.assertIn("uncertain_forecast", self.keys(body, "Info"))
            self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "future_adjustment"], [])

    def test_finalize_verifies_proposal(self):
        self.run_check([event(**self.FUT)], settings=[])
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = next(r["id"] for r in json.loads((out / "result.json").read_text())["ai_review"]
                   if r["condition_key"] == "future_adjustment")
        dec = out.parent / "d.json"

        def fin(proposal):
            dec.write_text(json.dumps([{"id": rid, "outcome": "propose_adjustment", "rationale": "documented",
                                        "proposal": proposal}]))
            return subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)], capture_output=True).returncode

        good = {"cvr_adjustment_percent": 40, "start": "2026-09-20", "end": "2026-09-22", "campaign_ids": ["S"]}
        self.assertEqual(fin({**good, "cvr_adjustment_percent": 80}), 4)
        self.assertEqual(fin({**good, "cvr_adjustment_percent": -20}), 4)
        self.assertEqual(fin({**good, "end": "2026-09-30"}), 4)
        self.assertEqual(fin(good), 0)


if __name__ == "__main__":
    unittest.main()
