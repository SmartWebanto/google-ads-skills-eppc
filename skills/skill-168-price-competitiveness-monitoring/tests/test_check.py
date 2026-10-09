"""test_check.py — decision-boundary tests for skill-168 price monitoring check.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-168-price-competitiveness-monitoring/tests
rules:   Synthetic temp exports only; asserts conditions, severities, gates and coverage, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes3 | initial tests
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

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill168_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

COMPLETE = "complete for declared rows and columns"
START, END = date(2026, 8, 4), date(2026, 9, 2)


def _days(a: date, b: date):
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def _csv(path: Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class Export:
    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.snapshot_date = "2026-09-06"
        self.profile = {"price_change_alert_pct": 0.2, "price_gap_alert_pct": 0.1}
        snaps = []
        for d in _days(START, END):
            snaps.append([d.isoformat(), "A1", "IT", "100" if d <= date(2026, 8, 17) else "90", "EUR", "", "", ""])
            snaps.append([d.isoformat(), "B1", "IT", "50", "EUR", "40", "2026-08-01", "2026-08-10"])
        snaps.append([END.isoformat(), "C1", "IT", "55", "EUR", "60", "", ""])
        self.snaps = snaps
        self.pages = [["A1", "IT", "2026-08-10T09:00", "https://s.example/a1", "95", "EUR", "200"],
                      ["A1", "IT", "2026-09-01T09:00", "https://s.example/a1", "90", "EUR", "200"],
                      ["A1", "IT", "2026-09-05T09:00", "https://s.example/a1", "70", "EUR", "200"],
                      ["A1", "IT", "2026-08-11T09:00", "https://s.example/a1", "10", "EUR", "503"]]
        self.bench = [["2026-09-01", "A1", "IT", "90", "75", "EUR"],
                      ["2026-09-01", "B1", "IT", "50", "52", "EUR"],
                      ["2026-09-01", "C1", "IT", "55", "0", "EUR"]]
        self.daily = [[d.isoformat(), "10", "A1", "IT", "1000", "50", "10", "2", "200"] for d in _days(START, END)]
        self.daily_complete = COMPLETE

    def write(self):
        e = self.export
        _csv(e / "account.csv", ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
                                 "money_unit", "conversion_lag_days"],
             [["111", "EUR", START.isoformat(), END.isoformat(), self.snapshot_date, "currency", "2"]])
        _csv(e / "campaigns.csv", ["id", "name", "status"], [["10", "Shopping", "ENABLED"]])
        manifest = [["account.csv", COMPLETE], ["campaigns.csv", COMPLETE]]
        if self.snaps is not None:
            _csv(e / "external" / "merchant_price_snapshots.csv",
                 ["snapshot_date", "offer_id", "target_country", "price", "currency", "sale_price", "sale_start",
                  "sale_end"], self.snaps)
            manifest.append(["external/merchant_price_snapshots.csv", COMPLETE])
        if self.pages is not None:
            _csv(e / "external" / "landing_page_prices.csv",
                 ["offer_id", "target_country", "checked_at", "url", "page_price", "currency", "http_status"], self.pages)
            manifest.append(["external/landing_page_prices.csv", COMPLETE])
        if self.bench is not None:
            _csv(e / "external" / "price_competitiveness.csv",
                 ["report_date", "offer_id", "target_country", "price", "benchmark_price", "currency"], self.bench)
            manifest.append(["external/price_competitiveness.csv", COMPLETE])
        if self.daily is not None:
            _csv(e / "custom" / "product_daily.csv", M.DAILY_COLS, self.daily)
            manifest.append(["custom/product_daily.csv", self.daily_complete])
        _csv(e / "table_manifest.csv", ["filename", "completeness"], manifest)
        (self.root / "profile.json").write_text(json.dumps(self.profile))

    def run(self):
        self.write()
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.export, self.root / "profile.json").finish()

    def cli(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=list(args) + [
                "--export", str(self.export), "--profile", str(self.root / "profile.json"),
                "--out", str(self.root / "out")])


def _f(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


def _cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def _obs(body, check, text_part):
    return [o["data"] for o in body["observations"] if o["check"] == check and text_part in o["text"]]


class PriceEvents(unittest.TestCase):
    def test_alert_only_beyond_profile_fraction_and_sale_end_is_an_event(self):
        body = Export(self).run()
        [summary] = _obs(body, "price_change_events", "events")
        self.assertEqual((summary["events"], summary["increases"], summary["decreases"]), (2, 1, 1))
        # A1 -10% is below the 20% alert; B1 sale end 40 -> 50 is +25%
        [f] = _f(body, "price_change_event")
        self.assertEqual((f["entity"]["offer_id"], f["severity"]), ("B1", "Info"))
        self.assertAlmostEqual(f["evidence"]["relative_change"], 0.25)
        self.assertEqual(f["evidence"]["old_span"], ["2026-08-04", "2026-08-10"])

    def test_no_alert_fraction_means_no_alert_findings(self):
        ex = Export(self)
        ex.profile = {}
        body = ex.run()
        self.assertFalse(_f(body, "price_change_event"))
        self.assertEqual(_cov(body, "price_change_events")["status"], "partial")

    def test_currency_change_is_not_a_price_event(self):
        ex = Export(self)
        ex.snaps = [["2026-08-04", "Z1", "IT", "100", "EUR", "", "", ""],
                    ["2026-08-05", "Z1", "IT", "120", "CHF", "", "", ""]]
        body = ex.run()
        self.assertFalse(_f(body, "price_change_event"))
        self.assertEqual(_obs(body, "price_change_events", "events")[0]["events"], 0)

    def test_missing_snapshots_skip_dependent_checks(self):
        ex = Export(self)
        ex.snaps = None
        body = ex.run()
        for c in ("price_change_events", "sale_price_windows", "landing_price_mismatch", "price_event_performance"):
            self.assertEqual(_cov(body, c)["status"], "skipped")
        self.assertIn("external/merchant_price_snapshots (file)", _cov(body, "price_change_events")["missing"])


class SaleWindows(unittest.TestCase):
    def test_expired_and_not_below_price_are_info(self):
        body = Export(self).run()
        self.assertEqual([f["entity"]["offer_id"] for f in _f(body, "expired_sale_price_submitted")], ["B1"])
        self.assertEqual([f["entity"]["offer_id"] for f in _f(body, "sale_price_not_below_price")], ["C1"])
        self.assertTrue(all(f["severity"] == "Info" for f in body["findings"]
                            if f["check"] == "sale_price_windows"))


class PageMismatch(unittest.TestCase):
    def test_same_date_mismatch_is_warning_match_and_unmatched_are_not(self):
        body = Export(self).run()
        [f] = _f(body, "landing_price_mismatch")
        self.assertEqual(f["severity"], "Warning")
        self.assertEqual(f["evidence"]["feed_effective_price"], 100)
        self.assertEqual(f["evidence"]["difference"], -5)
        self.assertEqual(_cov(body, "landing_price_mismatch")["status"], "partial")  # 09-05 has no snapshot
        [rv] = [r for r in body["ai_review"] if r["condition_key"] == "landing_price_mismatch"]
        self.assertIn("disapproval_evidenced", rv["outcomes"])  # 300 EUR >= spend_significant 100

    def test_sale_effective_price_is_the_comparison_basis(self):
        ex = Export(self)
        ex.pages = [["B1", "IT", "2026-08-06T09:00", "https://s.example/b1", "40", "EUR", "200"]]
        self.assertFalse(_f(ex.run(), "landing_price_mismatch"))

    def test_currency_difference_is_not_compared(self):
        ex = Export(self)
        ex.pages = [["A1", "IT", "2026-08-10T09:00", "https://s.example/a1", "95", "CHF", "200"]]
        self.assertFalse(_f(ex.run(), "landing_price_mismatch"))

    def test_without_product_spend_no_critical_outcome(self):
        ex = Export(self)
        ex.daily = None
        body = ex.run()
        [rv] = [r for r in body["ai_review"] if r["condition_key"] == "landing_price_mismatch"]
        self.assertNotIn("disapproval_evidenced", rv["outcomes"])


class Benchmark(unittest.TestCase):
    def test_gap_alert_and_zero_benchmark_undefined(self):
        body = Export(self).run()
        [f] = _f(body, "price_above_benchmark")
        self.assertEqual((f["entity"]["offer_id"], f["severity"]), ("A1", "Info"))
        [o] = _obs(body, "benchmark_price_gap", "gaps")
        self.assertEqual((o["above"], o["below"], o["undefined"]), (1, 1, 1))
        self.assertEqual(_cov(body, "benchmark_price_gap")["status"], "partial")


class BeforeAfter(unittest.TestCase):
    def _event(self, body, offer):
        return next(o for o in _obs(body, "price_event_performance", "Before/after") if o["offer_id"] == offer)

    def test_equal_windows_and_gated_rates_when_mature(self):
        body = Export(self).run()
        a1 = self._event(body, "A1")
        self.assertEqual(a1["window_days"], 14)
        self.assertEqual((a1["before"]["start"], a1["before"]["end"]), ("2026-08-04", "2026-08-17"))
        self.assertEqual((a1["after"]["start"], a1["after"]["end"]), ("2026-08-18", "2026-08-31"))
        self.assertAlmostEqual(a1["rates"]["ctr"]["before"], 0.05)
        self.assertAlmostEqual(a1["rates"]["cpa"]["after"], 5)
        self.assertFalse([f for f in body["findings"] if f["check"] == "price_event_performance"])

    def test_small_sample_side_leaves_rate_unqualified(self):
        ex = Export(self)
        ex.daily = [[r[0], "10", "A1", "IT", "1000", "50", "10", "0", "0"] for r in ex.daily]
        a1 = self._event(ex.run(), "A1")
        self.assertIn("unqualified", a1["rates"]["cpa"])
        self.assertIn("before", a1["rates"]["ctr"])

    def test_immature_period_reports_volumes_without_rates(self):
        ex = Export(self)
        ex.snapshot_date = "2026-09-03"  # 1 day after period end < 2-day lag
        body = ex.run()
        self.assertEqual(self._event(body, "A1")["rates"], {})
        self.assertEqual(_cov(body, "price_event_performance")["status"], "partial")

    def test_missing_days_in_uncertified_daily_are_unknown(self):
        ex = Export(self)
        ex.daily = [r for r in ex.daily if r[0] != "2026-08-20"]
        ex.daily_complete = "partial"
        a1 = self._event(ex.run(), "A1")
        self.assertTrue(a1["unqualified"])
        self.assertEqual(a1["rates"], {})


class Finalize(unittest.TestCase):
    def test_critical_needs_evidence_ref(self):
        ex = Export(self)
        ex.write()
        self.assertEqual(ex.cli("run"), 0)
        body = json.loads((ex.root / "out" / "result.json").read_text())
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "landing_price_mismatch")
        dec = ex.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "disapproval_evidenced", "rationale": "x", "proposal": {}}]))
        self.assertEqual(ex.cli("finalize", "--decisions", str(dec)), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "disapproval_evidenced", "rationale": "diag export",
                                    "proposal": {"evidence_ref": "merchant_diagnostics.csv#A1"}}]))
        self.assertEqual(ex.cli("finalize", "--decisions", str(dec)), 0)
        final = json.loads((ex.root / "out" / "final.json").read_text())
        self.assertEqual([f["severity"] for f in _f(final, "landing_price_mismatch")], ["Critical"])


if __name__ == "__main__":
    unittest.main()
