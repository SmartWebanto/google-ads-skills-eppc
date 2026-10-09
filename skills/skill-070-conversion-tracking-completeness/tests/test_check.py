"""test_check.py — Decision-boundary tests for skill-070 business-event coverage.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-070-conversion-tracking-completeness/tests -t skills/skill-070-conversion-tracking-completeness
rules:   Temp folders only; pins severities, coverage and verify() gates, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_070", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(c for r in rows for c in r))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _map(event, action, required="true", count=10):
    return {"account_id": "1", "campaign_id": "", "business_event_id": event, "action_id": action,
            "event_definition": "d", "funnel_stage": "purchase", "required_for_objective": required,
            "decision_use": "bidding", "expected_source": "OMS", "intended_bidding_role": "primary",
            "observed_business_count": count, "count_window_start": "2026-08-01", "count_window_end": "2026-08-30",
            "maturity_days": 2, "owner": "ops"}


def _daily(action, conv, mature="true"):
    return [{"account_id": "1", "campaign_id": "C1", "action_id": action,
             "date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(), "date_basis": "interaction_date",
             "conversions": conv, "reporting_mature": mature} for i in range(30)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, maps=None, actions=None, daily=None, journey=None, lag="2", actions_complete=True):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "rates_format": "fraction",
                                       "money_unit": "currency", "conversion_lag_days": lag}])
        _write(root / "conversion_actions.csv", actions or [{"id": "A1", "status": "ENABLED", "primary_for_goal": "true"}])
        files = {"conversion_actions.csv": "complete" if actions_complete else "partial"}
        for key, rows in (("external/business_event_map.csv", maps), ("custom/conversion_action_daily.csv", daily),
                          ("external/journey_coverage.csv", journey)):
            if rows:
                _write(root / key, rows)
                files[key] = "complete"
        _write(root / "table_manifest.csv", [{"filename": f, "completeness": c, "truncation": "none"}
                                             for f, c in files.items()])
        self.profile = self.dir / "profile.json"
        self.profile.write_text("{}")
        self.root = root
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, self.profile).finish()

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def status(body, check):
        return next(c["status"] for c in body["coverage"] if c["check"] == check)


class Mapping(Base):
    def test_required_unmapped_is_warning_with_critical_review(self):
        body = self.build(maps=[_map("E1", "")])
        self.assertEqual([f["severity"] for f in self.found(body, "required_measurement_gap")], ["Warning"])
        self.assertIn("Critical", {o["severity"] for o in body["ai_review"][0]["outcomes"].values()})

    def test_mapped_enabled_or_optional_is_not_a_gap(self):
        body = self.build(maps=[_map("E1", "A1"), _map("E2", "", required="false")])
        self.assertEqual(self.found(body, "required_measurement_gap"), [])

    def test_paused_action_in_complete_inventory_is_gap(self):
        body = self.build(maps=[_map("E1", "A1")], actions=[{"id": "A1", "status": "PAUSED"}])
        self.assertEqual(len(self.found(body, "required_measurement_gap")), 1)

    def test_absent_action_in_incomplete_inventory_is_unknown(self):
        body = self.build(maps=[_map("E1", "A9")], actions_complete=False)
        self.assertEqual(self.found(body, "required_measurement_gap"), [])
        self.assertEqual(self.status(body, "action_mapping"), "partial")

    def test_no_business_count_means_no_critical_review(self):
        body = self.build(maps=[_map("E1", "", count=0)])
        self.assertEqual(len(self.found(body, "required_measurement_gap")), 1)
        self.assertEqual(body["ai_review"], [])

    def test_missing_map_skips_but_journey_runs(self):
        journey = [{"business_event_id": "E1", "stage": "cart", "diagnostic_question": "q", "event_name": "add_to_cart",
                    "downstream_event_id": "E1", "decision_owner": "ops", "intended_bidding_role": "secondary"}]
        body = self.build(journey=journey)
        self.assertEqual(self.status(body, "action_mapping"), "skipped")
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["justified_secondary_event"])

    def test_journey_row_without_question_is_not_reviewed(self):
        journey = [{"business_event_id": "E1", "stage": "cart", "diagnostic_question": "", "event_name": "add_to_cart",
                    "downstream_event_id": "E1", "decision_owner": "ops", "intended_bidding_role": "secondary"}]
        body = self.build(journey=journey)
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(body["findings"], [])


class Volume(Base):
    def test_mature_zero_volume_with_outcomes_is_reviewed(self):
        body = self.build(maps=[_map("E1", "A1")], daily=_daily("A1", 0))
        self.assertEqual([f["severity"] for f in self.found(body, "zero_ads_volume_with_outcomes")], ["Info"])
        self.assertEqual(len(body["ai_review"]), 1)

    def test_nonzero_volume_is_not_flagged(self):
        body = self.build(maps=[_map("E1", "A1")], daily=_daily("A1", 1))
        self.assertEqual(self.found(body, "zero_ads_volume_with_outcomes"), [])

    def test_immature_rows_block_comparison(self):
        body = self.build(maps=[_map("E1", "A1")], daily=_daily("A1", 0, mature="false"))
        self.assertEqual(self.found(body, "zero_ads_volume_with_outcomes"), [])
        self.assertEqual(self.status(body, "volume_vs_business"), "partial")
        body = self.build(maps=[_map("E1", "A1")], daily=_daily("A1", 0), lag="30")
        self.assertEqual(self.found(body, "zero_ads_volume_with_outcomes"), [])


class Finalize(Base):
    def finalize(self, proposal):
        body = self.build(maps=[_map("E1", "")])
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
        dec = self.dir / "d.json"
        dec.write_text(json.dumps([{"id": body["ai_review"][0]["id"], "outcome": "material_outcomes_unmeasured",
                                    "rationale": "r", "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_critical_requires_evidence_ref(self):
        code, final = self.finalize({})
        self.assertEqual((code, final["counts"]["Critical"]), (4, 0))
        code, final = self.finalize({"evidence_ref": "crm-report-2026-08"})
        self.assertEqual((code, final["counts"]["Critical"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
