"""test_check.py — decision-boundary tests for skill-167 out-of-stock exposure check.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-167-out-of-stock-ad-exposure/tests
rules:   Synthetic temp exports only; no network; asserts behavior (conditions, severities, coverage), not wording.
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
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill167_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

URL = "https://shop.example/p/drill"
ALT = "https://shop.example/p/drill-pro"
COMPLETE = "complete for declared rows and columns"


def _csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class Export:
    """Builder for a minimal synthetic export; tests override pieces."""

    def __init__(self, test: unittest.TestCase):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.profile = {"out_of_stock_markers": ["esaurito"], "url_ignore_params": ["utm_*"]}
        self.campaign_status = "ENABLED"
        self.ads = [["1", "10", "100", "ENABLED", URL + "/?utm_source=x", "Buy drills", "Fast shipping"]]
        self.merchant = [["2026-09-06", "A1", "IT", URL, "out of stock"],
                         ["2026-08-30", "A1", "IT", URL, "out of stock"],
                         ["2026-08-31", "A1", "IT", URL, "out of stock"],
                         ["2026-09-06", "B1", "IT", ALT, "in stock"]]
        self.merchant_complete = COMPLETE
        self.pages = None
        self.daily = [["2026-08-30", "ad", "10", "100", "1", "60", "30", "900"],
                      ["2026-08-31", "ad", "10", "100", "1", "60", "30", "900"],
                      ["2026-09-01", "ad", "10", "100", "1", "500", "90", "3000"]]
        self.extra: list[tuple] = []

    def write(self) -> None:
        e = self.export
        _csv(e / "account.csv", ["customer_id", "name", "currency_code", "time_zone", "date_range_start",
                                 "date_range_end", "snapshot_date", "rates_format", "money_unit", "conversion_lag_days"],
             [["111", "T", "EUR", "Europe/Rome", "2026-08-04", "2026-09-02", "2026-09-06", "fraction", "currency", "2"]])
        _csv(e / "campaigns.csv", ["id", "name", "status"], [["10", "C", self.campaign_status]])
        _csv(e / "ad_groups.csv", ["id", "campaign_id", "status"], [["100", "10", "ENABLED"]])
        _csv(e / "ads.csv", ["id", "campaign_id", "ad_group_id", "status", "final_url", "headlines", "descriptions"],
             self.ads)
        manifest = [["account.csv", COMPLETE, "none"], ["campaigns.csv", COMPLETE, "none"],
                    ["ad_groups.csv", COMPLETE, "none"], ["ads.csv", COMPLETE, "none"]]
        if self.merchant is not None:
            _csv(e / "external" / "merchant_availability.csv",
                 ["snapshot_date", "offer_id", "target_country", "link", "availability"], self.merchant)
            manifest.append(["external/merchant_availability.csv", self.merchant_complete, "none"])
        if self.pages is not None:
            _csv(e / "external" / "page_stock_checks.csv",
                 ["url", "checked_at", "stock_state", "matched_marker", "http_status"], self.pages)
            manifest.append(["external/page_stock_checks.csv", COMPLETE, "none"])
        if self.daily is not None:
            _csv(e / "custom" / "entity_daily.csv",
                 ["date", "entity_type", "campaign_id", "ad_group_id", "entity_id", "cost", "clicks", "impressions"],
                 self.daily)
            manifest.append(["custom/entity_daily.csv", COMPLETE, "none"])
        for name, header, rows in self.extra:
            _csv(e / f"{name}.csv", header, rows)
            manifest.append([f"{name}.csv", COMPLETE, "none"])
        _csv(e / "table_manifest.csv", ["filename", "completeness", "truncation"], manifest)
        (self.root / "profile.json").write_text(json.dumps(self.profile))

    def run(self) -> dict:
        self.write()
        ctx = M.cli.run_once(M.SKILL, M.VERSION, M.run, self.export, self.root / "profile.json")
        return ctx.finish()

    def cli(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=list(args) + [
                "--export", str(self.export), "--profile", str(self.root / "profile.json"),
                "--out", str(self.root / "out")])


def _findings(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


def _cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


class OutOfStockDestination(unittest.TestCase):
    def test_active_ad_to_out_of_stock_url_is_warning_with_bounded_exposure(self):
        body = Export(self).run()
        [f] = _findings(body, "active_entity_out_of_stock")
        self.assertEqual(f["severity"], "Warning")
        self.assertEqual(f["entity"]["entity_id"], "1")
        exp = f["evidence"]["exposure"]
        # 09-01 has spend but no same-day stock observation: not counted as out-of-stock exposure
        self.assertEqual(exp["cost"], 120)
        self.assertEqual(exp["days_with_metrics"], 2)
        [rv] = [r for r in body["ai_review"] if r["condition_key"] == "active_entity_out_of_stock"]
        self.assertIn("no_purchase_path_material", rv["outcomes"])  # 120 >= spend_significant 100 EUR
        self.assertEqual(rv["provisional_finding"], f["id"])

    def test_exposure_below_spend_significant_offers_no_critical(self):
        ex = Export(self)
        ex.daily = [["2026-08-30", "ad", "10", "100", "1", "20", "5", "100"]]
        body = ex.run()
        [rv] = [r for r in body["ai_review"] if r["condition_key"] == "active_entity_out_of_stock"]
        self.assertNotIn("no_purchase_path_material", rv["outcomes"])
        self.assertEqual(_findings(body, "active_entity_out_of_stock")[0]["evidence"]["exposure"]["cost"], 20)

    def test_missing_daily_metrics_keeps_warning_but_exposure_unknown(self):
        ex = Export(self)
        ex.daily = None
        body = ex.run()
        [f] = _findings(body, "active_entity_out_of_stock")
        self.assertFalse(f["evidence"]["exposure"]["available"])
        self.assertEqual(_cov(body, "oos_spend_exposure")["status"], "skipped")
        [rv] = [r for r in body["ai_review"] if r["condition_key"] == "active_entity_out_of_stock"]
        self.assertNotIn("no_purchase_path_material", rv["outcomes"])

    def test_orderable_sibling_offer_makes_mixed_info_not_warning(self):
        ex = Export(self)
        ex.merchant.append(["2026-09-06", "A2", "IT", URL, "in stock"])
        body = ex.run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))
        self.assertEqual([f["severity"] for f in _findings(body, "mixed_availability")], ["Info"])

    def test_preorder_is_orderable(self):
        ex = Export(self)
        ex.merchant[0][4] = "preorder"
        body = ex.run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))

    def test_paused_campaign_is_not_flagged(self):
        ex = Export(self)
        ex.campaign_status = "PAUSED"
        body = ex.run()
        self.assertFalse(body["findings"])

    def test_uncertified_catalog_downgrades_to_info(self):
        ex = Export(self)
        ex.merchant_complete = "partial sample"
        body = ex.run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))
        self.assertEqual(len(_findings(body, "stock_evidence_unverified")), 1)
        self.assertEqual(_cov(body, "merchant_stock_state")["status"], "partial")

    def test_stale_stock_evidence_is_info_until_profile_allows_age(self):
        ex = Export(self)
        ex.merchant = [r for r in ex.merchant if r[0] != "2026-09-06"]
        body = ex.run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))
        self.assertEqual(len(_findings(body, "stock_evidence_stale")), 1)
        ex2 = Export(self)
        ex2.merchant = [r for r in ex2.merchant if r[0] != "2026-09-06"]
        ex2.profile["stock_evidence_max_age_days"] = 6
        self.assertEqual(len(_findings(ex2.run(), "active_entity_out_of_stock")), 1)

    def test_unmatched_url_is_partial_coverage_not_a_pass(self):
        ex = Export(self)
        ex.ads = [["1", "10", "100", "ENABLED", "https://shop.example/p/other", "Buy", "Now"]]
        body = ex.run()
        self.assertFalse(body["findings"])
        self.assertEqual(_cov(body, "ad_destinations")["status"], "partial")

    def test_no_stock_evidence_skips_destination_checks(self):
        ex = Export(self)
        ex.merchant = None
        body = ex.run()
        cov = _cov(body, "ad_destinations")
        self.assertEqual(cov["status"], "skipped")
        self.assertIn("external/merchant_availability (file)", cov["missing"])
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))

    def test_keyword_sitelink_and_asset_group_destinations(self):
        ex = Export(self)
        ex.ads = [["1", "10", "100", "ENABLED", ALT, "Buy", "Now"]]
        ex.extra = [
            ("keywords", ["id", "campaign_id", "ad_group_id", "status", "final_url"],
             [["7", "10", "100", "ENABLED", URL], ["8", "10", "100", "ENABLED", ""]]),
            ("assets", ["asset_id", "type", "level", "status", "campaign_id", "ad_group_id", "final_urls"],
             [["55", "SITELINK", "ACCOUNT", "ENABLED", "", "", URL], ["56", "CALLOUT", "ACCOUNT", "ENABLED", "", "", URL]]),
            ("custom/asset_group_urls", ["campaign_id", "asset_group_id", "final_url", "status"],
             [["10", "900", URL, "ENABLED"]]),
        ]
        # keyword criterion 7 spends in ad group 100; same criterion id in another ad group must not join
        ex.daily = [["2026-08-30", "keyword", "10", "100", "7", "30", "3", "90"],
                    ["2026-08-30", "keyword", "10", "999", "7", "400", "40", "900"],
                    ["2026-08-31", "asset_group", "10", "", "900", "15", "2", "50"]]
        body = ex.run()
        by = {f["entity"]["entity_type"]: f for f in _findings(body, "active_entity_out_of_stock")}
        self.assertEqual(sorted(by), ["asset_group", "keyword", "sitelink"])
        self.assertEqual(by["keyword"]["evidence"]["exposure"]["cost"], 30)
        self.assertEqual(by["asset_group"]["evidence"]["exposure"]["cost"], 15)
        self.assertFalse(by["sitelink"]["evidence"]["exposure"]["available"])


class PageChecks(unittest.TestCase):
    def _ex(self, rows):
        ex = Export(self)
        ex.merchant = None
        ex.pages = rows
        return ex

    def test_declared_marker_counts_as_out_of_stock(self):
        body = self._ex([[URL, "2026-09-06T08:00:00", "out_of_stock", "Esaurito", "200"]]).run()
        self.assertEqual(len(_findings(body, "active_entity_out_of_stock")), 1)

    def test_undeclared_marker_is_unknown(self):
        body = self._ex([[URL, "2026-09-06T08:00:00", "out_of_stock", "sold out soon", "200"]]).run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))
        self.assertEqual(_cov(body, "page_stock_state")["status"], "partial")

    def test_non_2xx_page_is_unknown(self):
        body = self._ex([[URL, "2026-09-06T08:00:00", "out_of_stock", "esaurito", "404"]]).run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))

    def test_merchant_page_disagreement_is_conflict(self):
        ex = Export(self)
        ex.pages = [[URL, "2026-09-06T08:00:00", "in_stock", "", "200"]]
        body = ex.run()
        self.assertFalse(_findings(body, "active_entity_out_of_stock"))
        self.assertEqual(len(_findings(body, "stock_evidence_conflict")), 1)


class StaleDates(unittest.TestCase):
    def test_past_year_goes_to_review_current_year_does_not(self):
        ex = Export(self)
        ex.merchant = None
        ex.ads = [["1", "10", "100", "ENABLED", URL, "Best deals 2025 | Since 1998", "Offer ends 2026-08-01"],
                  ["2", "10", "100", "ENABLED", URL, "New 2026 range", "Order by 2026-12-01"]]
        body = ex.run()
        flagged = _findings(body, "past_date_in_ad_text")
        self.assertEqual([f["entity"]["ad_id"] for f in flagged], ["1"])
        self.assertEqual(flagged[0]["severity"], "Info")
        self.assertEqual({t["token"] for t in flagged[0]["evidence"]["tokens"]}, {"2025", "1998", "2026-08-01"})
        [rv] = [r for r in body["ai_review"] if r["condition_key"] == "stale_date_claim"]
        self.assertEqual(rv["outcomes"]["stale_claim"]["severity"], "Warning")
        self.assertIsNone(rv["outcomes"]["legitimate_reference"]["severity"])


class Finalize(unittest.TestCase):
    def _reviewed(self):
        ex = Export(self)
        ex.write()
        self.assertEqual(ex.cli("run"), 0)
        body = json.loads((ex.root / "out" / "result.json").read_text())
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "active_entity_out_of_stock")
        return ex, rid

    def _finalize(self, ex, decisions):
        (ex.root / "d.json").write_text(json.dumps(decisions))
        code = ex.cli("finalize", "--decisions", str(ex.root / "d.json"))
        return code, json.loads((ex.root / "out" / "final.json").read_text())

    def test_redirect_to_in_stock_url_accepted(self):
        ex, rid = self._reviewed()
        code, final = self._finalize(ex, [{"id": rid, "outcome": "pause_or_redirect", "rationale": "restock unknown",
                                           "proposal": {"action": "redirect", "redirect_url": ALT + "/"}}])
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in _findings(final, "active_entity_out_of_stock")], ["Warning"])

    def test_redirect_to_out_of_stock_url_rejected(self):
        ex, rid = self._reviewed()
        code, _ = self._finalize(ex, [{"id": rid, "outcome": "pause_or_redirect", "rationale": "x",
                                       "proposal": {"action": "redirect", "redirect_url": URL}}])
        self.assertEqual(code, 4)

    def test_critical_requires_evidence_ref(self):
        ex, rid = self._reviewed()
        code, _ = self._finalize(ex, [{"id": rid, "outcome": "no_purchase_path_material", "rationale": "x",
                                       "proposal": {"action": "pause"}}])
        self.assertEqual(code, 4)
        code, final = self._finalize(ex, [{"id": rid, "outcome": "no_purchase_path_material", "rationale": "x",
                                           "proposal": {"action": "pause", "evidence_ref": "stock_log.csv#A1"}}])
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
