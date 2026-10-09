"""test_check.py — Decision-boundary tests for skill-071 conversion reconciliation.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-071-conversion-tracking-accuracy/tests -t skills/skill-071-conversion-tracking-accuracy
rules:   Temp folders only; pins comparability, dedup, tolerance, maturity and verify() gates, never wording.
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
_spec = importlib.util.spec_from_file_location("check_071", _PATH)
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


def _rule(currency="EUR", tol=10, maturity=2):
    return {"account_id": "1", "action_id": "A1", "business_event_id": "B1", "source_event": "order_paid",
            "counting_unit": "order", "eligible_channel_scope": "paid search", "attribution_model": "DATA_DRIVEN",
            "lookback_days": 30, "date_basis": "interaction_date", "timezone": "Europe/Rome", "currency": currency,
            "value_basis": "net", "tax_shipping_discount_treatment": "excl", "refund_treatment": "net",
            "maturity_days": maturity, "tolerance_count_pct": tol, "tolerance_value_pct": tol, "rationale": "r"}


def _events(n, dup=0, stage="order_paid"):
    rows = [{"event_token": f"T{i}", "action_id": "A1", "event_timestamp": f"2026-08-{(i % 28) + 1:02d}T10:00:00",
             "eligible_scope": "paid search", "stage": stage, "deduplication_key_token": f"D{i}",
             "gross_value": 60, "expected_value": 50, "refund_value_to_snapshot": 0, "currency": "EUR"} for i in range(n)]
    rows += [dict(rows[i], event_token=f"X{i}") for i in range(dup)]
    return rows


def _daily(total, mature="true"):
    per = [total // 30 + (1 if i < total % 30 else 0) for i in range(30)]
    return [{"account_id": "1", "campaign_id": "C1", "action_id": "A1",
             "date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(), "date_basis": "interaction_date",
             "conversions": per[i], "conversion_value": per[i] * 50, "currency": "EUR", "modeled_included": "false",
             "reporting_mature": mature} for i in range(30)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, rules=None, events=None, daily=None, ledger=None, xdev=None, lag="2"):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "rates_format": "fraction", "money_unit": "currency",
                                       "conversion_date_basis": "interaction_date", "conversion_lag_days": lag}])
        _write(root / "conversion_actions.csv", [{"id": "A1", "status": "ENABLED", "attribution_model": "DATA_DRIVEN",
                                                  "click_window_days": 30}])
        files = []
        for key, rows in (("external/reconciliation_rules.csv", rules), ("external/business_events.csv", events),
                          ("custom/ads_reconciliation_daily.csv", daily),
                          ("external/ads_event_reconciliation.csv", ledger),
                          ("external/cross_device_measured.csv", xdev)):
            if rows:
                _write(root / key, rows)
                files.append(key)
        _write(root / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                             for f in files])
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


class Variance(Base):
    def test_residual_beyond_tolerance_is_provisional_warning_with_review(self):
        body = self.build([_rule()], _events(20), _daily(30))  # +50% vs tolerance 10%
        self.assertEqual([f["severity"] for f in self.found(body, "residual_exceeds_tolerance")], ["Warning"])
        outcomes = body["ai_review"][0]["outcomes"]
        self.assertEqual(outcomes["explained_difference"]["severity"], "Info")
        self.assertEqual(outcomes["confirmed_fault_material"]["severity"], "Critical")

    def test_within_tolerance_is_clean(self):
        body = self.build([_rule()], _events(20), _daily(21))  # +5%
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])
        self.assertEqual(body["ai_review"], [])

    def test_duplicate_business_events_are_deduplicated(self):
        body = self.build([_rule()], _events(20, dup=5), _daily(21))
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])
        obs = [o for o in body["observations"] if o["check"] == "business_event_dedup"][0]["data"]
        self.assertEqual((obs["distinct_events"], obs["duplicates_removed"]), (20, 5))

    def test_other_stage_events_are_not_merged(self):
        body = self.build([_rule()], _events(20) + _events(20, stage="lead"), _daily(21))
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])

    def test_currency_mismatch_is_incomparable_info(self):
        body = self.build([_rule(currency="USD")], _events(20), _daily(40))
        self.assertEqual([f["severity"] for f in self.found(body, "incomparable_cohort")], ["Info"])
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])

    def test_zero_denominator_is_info_not_variance(self):
        body = self.build([_rule()], _events(3, stage="lead"), _daily(10))
        self.assertEqual([f["severity"] for f in self.found(body, "zero_denominator")], ["Info"])

    def test_maturity_and_sample_gates(self):
        body = self.build([_rule(maturity=10)], _events(20), _daily(30))
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])
        self.assertEqual(self.status(body, "aggregate_variance"), "partial")
        body = self.build([_rule()], _events(20), _daily(30, mature="false"))
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])
        body = self.build([_rule()], _events(10), _daily(20))  # 10 < min_conversions 15
        self.assertEqual(self.found(body, "residual_exceeds_tolerance"), [])

    def test_missing_rules_skip_everything_but_cross_device(self):
        body = self.build(None, _events(20), _daily(30))
        self.assertEqual(body["findings"], [])
        self.assertEqual(self.status(body, "aggregate_variance"), "skipped")


class Ledger(Base):
    def test_ledger_beyond_tolerance_is_warning(self):
        ledger = [{"event_token": f"T{i}", "action_id": "A1", "expected_send_count": 1,
                   "observed_send_count": 2 if i < 5 else 1, "accepted_count": 1, "rejected_count": 0}
                  for i in range(20)]
        body = self.build([_rule()], ledger=ledger)
        self.assertEqual([f["severity"] for f in self.found(body, "ledger_residual_exceeds_tolerance")], ["Warning"])
        ledger = [dict(r, observed_send_count=1) for r in ledger]
        body = self.build([_rule()], ledger=ledger)
        self.assertEqual(self.found(body, "ledger_residual_exceeds_tolerance"), [])


class CrossDevice(Base):
    ROW = {"account_id": "1", "action_id": "A1", "window_start": "2026-08-01", "window_end": "2026-08-30",
           "report_scope": "account", "source_metric_name": "cross_device_conversions",
           "measured_cross_device_conversions": 12, "comparable_total_conversions": 80,
           "total_metric_definition": "conversions", "modeled_included": "false", "suppression_status": "none"}

    def test_measured_subset_is_info(self):
        body = self.build(xdev=[self.ROW])
        self.assertEqual([f["severity"] for f in self.found(body, "direct_cross_device_contribution")], ["Info"])

    def test_modeled_or_invalid_numerator_is_not_concluded(self):
        body = self.build(xdev=[dict(self.ROW, modeled_included="true")])
        self.assertEqual(self.found(body, "direct_cross_device_contribution"), [])
        self.assertEqual(self.status(body, "cross_device_direct"), "partial")
        body = self.build(xdev=[dict(self.ROW, measured_cross_device_conversions=90)])
        self.assertEqual(self.found(body, "direct_cross_device_contribution"), [])


class Finalize(Base):
    def finalize(self, outcome, proposal):
        body = self.build([_rule()], _events(20), _daily(30))
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
        dec = self.dir / "d.json"
        dec.write_text(json.dumps([{"id": body["ai_review"][0]["id"], "outcome": outcome, "rationale": "r",
                                    "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_critical_needs_corroboration(self):
        code, final = self.finalize("confirmed_fault_material", {"evidence_ref": "e"})
        self.assertEqual(code, 4)
        self.assertEqual(final["counts"]["Critical"], 0)
        code, final = self.finalize("confirmed_fault_material", {"evidence_ref": "e", "corroboration_ref": "tag-trace-3"})
        self.assertEqual((code, final["counts"]["Critical"]), (0, 1))

    def test_explained_replaces_provisional_warning(self):
        code, final = self.finalize("explained_difference", {})
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in self.found(final, "residual_exceeds_tolerance")], ["Info"])


if __name__ == "__main__":
    unittest.main()
