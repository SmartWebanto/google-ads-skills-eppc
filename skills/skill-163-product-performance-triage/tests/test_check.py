"""test_check.py — Decision-boundary tests for skill-163 product performance triage.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-163-product-performance-triage/tests -t skills/skill-163-product-performance-triage
rules:   Synthetic temp exports only; assert consumer-visible outcomes (findings, reviews, coverage, finalize codes),
never wording. Every defect has a plausible valid counterexample next to it.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes1 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill163_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

PRODUCT_HDR = "account_id,campaign_id,offer_id,date,impressions,clicks,cost,conversions,conversion_value,goal_set_id\n"
PRIOR, CURRENT = "2026-08-05", "2026-08-20"


def _account(lag="2"):
    return ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
            f"money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
            f"2026-09-06,fraction,currency,interaction_date,{lag}\n")


CAMPAIGNS = ("id,name,status,channel_type,target_cpa,target_roas,goal_ids\n"
             "10,Shopping,ENABLED,SHOPPING,,4.0,purchase\n"
             "20,PMax,ENABLED,PERFORMANCE_MAX,30,,purchase\n"
             "30,Search,ENABLED,SEARCH,30,,purchase\n")
ACTIONS = "id,name,status,last_conversion_date\npurchase,Purchase,ENABLED,2026-08-29\n"


def _row(cid, offer, date, imp, clk, cost, conv, val=0):
    return f"1,{cid},{offer},{date},{imp},{clk},{cost},{conv},{val},purchase\n"


def _manifest(files, completeness="complete for declared rows"):
    return "filename,completeness,truncation\n" + "".join(f"{f},{completeness},none\n" for f in files)


class Base(unittest.TestCase):
    def export(self, product_rows=None, *, lag="2", actions=ACTIONS, merchant=None, completeness="complete",
               campaigns=CAMPAIGNS) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        files = {"account.csv": _account(lag), "campaigns.csv": campaigns}
        if actions:
            files["conversion_actions.csv"] = actions
        if product_rows is not None:
            files["custom/product_daily.csv"] = PRODUCT_HDR + "".join(product_rows)
        if merchant is not None:
            files["external/merchant_products.csv"] = ("offer_id,availability,processing_status,snapshot_at\n"
                                                       + "".join(merchant))
        files["table_manifest.csv"] = _manifest(sorted(files), completeness)
        for name, text in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.out = Path(tmp.name) / "out"
        return root

    def run_check(self, root: Path) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(self.out)])
        self.assertEqual(code, 0)
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, root: Path, decisions: list) -> tuple[int, dict]:
        dpath = self.out / "decisions.json"
        dpath.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(root), "--out", str(self.out), "--decisions", str(dpath)])
        return code, json.loads((self.out / "final.json").read_text())

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def reviews(body, key):
        return [r for r in body["ai_review"] if r["condition_key"] == key]

    @staticmethod
    def findings(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]


class ZeroConversion(Base):
    ROWS = [_row(20, "A", PRIOR, 3000, 150, 80, 0), _row(20, "B", PRIOR, 3000, 150, 80, 1),
            _row(20, "C", PRIOR, 3000, 150, 40, 0), _row(20, "D", PRIOR, 3000, 50, 80, 0)]

    def test_gated_item_gets_review_and_counterexamples_do_not(self):
        body = self.run_check(self.export(self.ROWS))
        items = sorted(r["entity"]["offer_id"] for r in self.reviews(body, "zero_conversion_item"))
        self.assertEqual(items, ["a"])  # B converted, C below spend_floor 50, D below min_clicks
        f = self.findings(body, "zero_conversion_item")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertIn("Warning", {o["severity"] for o in self.reviews(body, "zero_conversion_item")[0]["outcomes"].values()})

    def test_immature_window_blocks_screening(self):
        body = self.run_check(self.export(self.ROWS, lag="10"))
        self.assertEqual(self.reviews(body, "zero_conversion_item"), [])
        self.assertEqual(self.cov(body, "zero_conversion_items")["status"], "partial")

    def test_unknown_tracking_blocks_screening(self):
        body = self.run_check(self.export(self.ROWS, actions=None))
        self.assertEqual(self.findings(body, "zero_conversion_item"), [])
        self.assertEqual(self.cov(body, "zero_conversion_items")["status"], "partial")

    def test_accepted_warning_replaces_provisional(self):
        root = self.export(self.ROWS)
        body = self.run_check(root)
        rid = self.reviews(body, "zero_conversion_item")[0]["id"]
        code, final = self.finalize(root, [{"id": rid, "outcome": "unwanted_or_uneconomic", "rationale": "off-offer"}])
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in self.findings(final, "zero_conversion_item")], ["Warning"])


class MissingEvidence(Base):
    def test_missing_product_report_skips_everything(self):
        body = self.run_check(self.export(None))
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))
        self.assertIn("custom/product_daily (file)", self.cov(body, "product_scope")["missing"])
        self.assertEqual(body["findings"], [])

    def test_item_id_alternative_key_is_accepted(self):
        root = self.export([_row(20, "A", PRIOR, 3000, 150, 80, 0)])
        p = root / "custom" / "product_daily.csv"
        p.write_text(p.read_text().replace("offer_id", "item_id", 1))
        body = self.run_check(root)
        self.assertNotEqual(self.cov(body, "product_scope")["status"], "skipped")
        self.assertEqual(len(self.reviews(body, "zero_conversion_item")), 1)

    def test_no_shopping_or_pmax_is_not_applicable(self):
        only_search = "id,name,status,channel_type\n30,Search,ENABLED,SEARCH\n"
        body = self.run_check(self.export(None, campaigns=only_search))
        self.assertTrue(all(c["status"] == "not_applicable" for c in body["coverage"]))

    def test_zero_cost_denominators_are_undefined(self):
        body = self.run_check(self.export([_row(20, "A", PRIOR, 0, 0, 0, 0)]))
        conc = [o for o in body["observations"] if o["check"] == "spend_concentration"]
        self.assertTrue(conc and all(o["data"]["top1_share"] is None for o in conc))
        self.assertEqual(body["findings"], [])


class TargetGap(Base):
    def test_cpa_above_target_only_with_enough_conversions(self):
        rows = [_row(20, "HIGH", PRIOR, 5000, 400, 800, 20), _row(20, "OK", PRIOR, 5000, 400, 400, 20),
                _row(20, "THIN", PRIOR, 5000, 400, 800, 10)]
        body = self.run_check(self.export(rows))
        self.assertEqual([f["entity"]["offer_id"] for f in self.findings(body, "item_cpa_above_target")], ["high"])
        self.assertTrue(all(f["severity"] == "Info" for f in body["findings"]))

    def test_roas_campaign_uses_roas_not_cpa(self):
        rows = [_row(10, "LOW", PRIOR, 5000, 400, 1000, 20, 2000), _row(10, "GOOD", PRIOR, 5000, 400, 1000, 20, 5000)]
        body = self.run_check(self.export(rows))
        self.assertEqual([f["entity"]["offer_id"] for f in self.findings(body, "item_roas_below_target")], ["low"])
        self.assertEqual(self.findings(body, "item_cpa_above_target"), [])

    def test_immature_window_reports_no_gap(self):
        body = self.run_check(self.export([_row(20, "HIGH", PRIOR, 5000, 400, 800, 20)], lag="10"))
        self.assertEqual(self.findings(body, "item_cpa_above_target"), [])
        self.assertEqual(self.cov(body, "item_target_gap")["status"], "partial")


class Trends(Base):
    def test_decline_growth_and_sample_gate(self):
        rows = [_row(20, "DROP", PRIOR, 2000, 50, 150, 1), _row(20, "DROP", CURRENT, 1000, 20, 60, 1),
                _row(20, "FLAT", PRIOR, 2000, 50, 150, 1), _row(20, "FLAT", CURRENT, 1600, 40, 120, 1),
                _row(20, "UP", PRIOR, 1000, 10, 10, 1), _row(20, "UP", CURRENT, 2000, 20, 20, 1),
                _row(20, "TINY", PRIOR, 500, 10, 10, 1), _row(20, "TINY", CURRENT, 100, 2, 2, 1)]
        body = self.run_check(self.export(rows))
        self.assertEqual([f["entity"]["offer_id"] for f in self.findings(body, "item_impression_decline")], ["drop"])
        self.assertEqual([f["entity"]["offer_id"] for f in self.findings(body, "item_impression_growth")], ["up"])
        self.assertEqual(len(self.reviews(body, "item_impression_decline")), 1)  # prior cost 150 >= spend_significant 100

    def test_immaterial_decline_has_no_review(self):
        rows = [_row(20, "DROP", PRIOR, 2000, 50, 50, 1), _row(20, "DROP", CURRENT, 1000, 20, 20, 1)]
        body = self.run_check(self.export(rows))
        self.assertEqual(len(self.findings(body, "item_impression_decline")), 1)
        self.assertEqual(self.reviews(body, "item_impression_decline"), [])

    def test_stop_needs_certified_complete_report(self):
        rows = [_row(20, "GONE", PRIOR, 2000, 50, 150, 1)]
        body = self.run_check(self.export(rows))
        self.assertEqual(len(self.findings(body, "item_stopped_serving")), 1)
        body = self.run_check(self.export(rows, completeness="partial sample"))
        self.assertEqual(self.findings(body, "item_stopped_serving"), [])
        self.assertEqual(self.cov(body, "item_trends")["status"], "partial")


class Overlap(Base):
    ROWS = [_row(10, "X", PRIOR, 100, 5, 5, 0), _row(20, "X", PRIOR, 100, 5, 5, 0),
            _row(20, "Y", PRIOR, 100, 5, 5, 0), _row(30, "Y", PRIOR, 100, 5, 5, 0),
            _row(10, "Z", PRIOR, 0, 0, 0, 0), _row(20, "Z", PRIOR, 100, 5, 5, 0)]

    def test_only_served_shopping_pmax_pairs_count(self):
        body = self.run_check(self.export(self.ROWS))
        rev = self.reviews(body, "multi_campaign_item_serving")
        self.assertEqual(len(rev), 1)
        self.assertEqual(rev[0]["entity"]["campaign_ids"], ["10", "20"])
        self.assertEqual([i["offer_id"] for i in rev[0]["evidence"]["items"]], ["x"])  # Y: Search; Z: 0 impressions

    def test_finalize_requires_owner_in_pair(self):
        root = self.export(self.ROWS)
        rid = self.reviews(self.run_check(root), "multi_campaign_item_serving")[0]["id"]
        code, _ = self.finalize(root, [{"id": rid, "outcome": "unintended_overlap", "rationale": "r",
                                        "proposal": {"owner_campaign_id": "30"}}])
        self.assertEqual(code, 4)
        code, final = self.finalize(root, [{"id": rid, "outcome": "unintended_overlap", "rationale": "r",
                                            "proposal": {"owner_campaign_id": "20"}}])
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in self.findings(final, "multi_campaign_item_serving")], ["Warning"])


class NonServing(Base):
    ROWS = [_row(20, "SOLD", PRIOR, 100, 5, 5, 0)]
    MERCHANT = ["SOLD,in_stock,approved,2026-09-01\n", "QUIET,in_stock,approved,2026-09-01\n",
                "BLOCKED,in_stock,disapproved,2026-09-01\n", "OOS,out_of_stock,approved,2026-09-01\n"]

    def test_only_approved_in_stock_unserved_items_listed(self):
        body = self.run_check(self.export(self.ROWS, merchant=self.MERCHANT))
        rev = self.reviews(body, "eligible_items_not_serving")
        self.assertEqual(rev[0]["evidence"]["offer_ids"], ["quiet"])

    def test_uncertified_inventory_cannot_prove_absence(self):
        body = self.run_check(self.export(self.ROWS, merchant=self.MERCHANT, completeness="partial"))
        self.assertEqual(self.reviews(body, "eligible_items_not_serving"), [])
        self.assertEqual(self.cov(body, "non_serving_items")["status"], "partial")

    def test_missing_merchant_snapshot_skips_only_that_check(self):
        body = self.run_check(self.export(self.ROWS))
        self.assertEqual(self.cov(body, "non_serving_items")["status"], "skipped")
        self.assertIn("external/merchant_products (file)", self.cov(body, "non_serving_items")["missing"])
        self.assertEqual(self.cov(body, "item_overlap")["status"], "completed")

    def test_critical_requires_evidence_ref_and_listed_offers(self):
        root = self.export(self.ROWS, merchant=self.MERCHANT)
        rid = self.reviews(self.run_check(root), "eligible_items_not_serving")[0]["id"]
        code, _ = self.finalize(root, [{"id": rid, "outcome": "material_serving_failure", "rationale": "r",
                                        "proposal": {"offer_ids": ["quiet"]}}])
        self.assertEqual(code, 4)
        code, _ = self.finalize(root, [{"id": rid, "outcome": "intended_items_not_serving", "rationale": "r",
                                        "proposal": {"offer_ids": ["sold"]}}])
        self.assertEqual(code, 4)
        code, final = self.finalize(root, [{"id": rid, "outcome": "material_serving_failure", "rationale": "r",
                                            "proposal": {"offer_ids": ["quiet"], "evidence_ref": "outage.pdf"}}])
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
