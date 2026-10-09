"""test_check.py — decision-boundary tests for skill-151 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-151-product-feed-seasonal-keyword-optimization/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check151", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

FEED_COLS = ["merchant_id", "feed_label", "language", "item_id", "snapshot_at", "title", "structured_title_if_used",
             "description", "brand", "product_type", "variant_attributes", "product_url", "promotion_ids",
             "approval_status"]
DESC_COLS = ["merchant_id", "feed_label", "language", "item_id", "descriptor", "genuine_attribute",
             "product_page_snapshot_ref", "applicable_season_or_event", "truthful_use_rationale", "owner"]
QPE_COLS = ["account_id", "campaign_id", "query", "merchant_id", "feed_label", "language", "item_id", "date",
            "impressions", "clicks", "cost", "conversions", "source_report", "mapping_method", "coverage"]


def feed(item, title, label="IT", lang="it", brand="Acme"):
    return {"merchant_id": "M1", "feed_label": label, "language": lang, "item_id": item, "snapshot_at": "2026-09-06",
            "title": title, "brand": brand, "variant_attributes": "medium"}


def desc(item, d, genuine, label="IT", lang="it"):
    return {"merchant_id": "M1", "feed_label": label, "language": lang, "item_id": item, "descriptor": d,
            "genuine_attribute": genuine, "owner": "catalog"}


class Case:
    def __init__(self, test, snapshot="2026-09-06"):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.files = {}
        self.write("account", ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
                               "conversion_lag_days"],
                   [{"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": "2"}])
        self.write("campaigns", ["id", "channel_type"], [{"id": "C1", "channel_type": "SHOPPING"}])

    def write(self, key, cols, rows):
        p = self.export / f"{key}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
        self.files[f"{key}.csv"] = True

    def run(self, profile=None):
        with (self.export / "table_manifest.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "completeness", "truncation"])
            for fn in sorted(self.files):
                w.writerow([fn, "complete", "none"])
        prof = self.root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(self.export), "--profile", str(prof), "--out", str(out)])
        assert code == 0
        self.prof, self.out = prof, out
        return json.loads((out / "result.json").read_text())

    def finalize(self, decisions):
        d = self.root / "decisions.json"
        d.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.export), "--profile", str(self.prof), "--out",
                               str(self.out), "--decisions", str(d)])


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def by_key(items, key):
    return [x for x in items if x["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def test_non_genuine_descriptor_in_title_warns_genuine_does_not(self):
        c = Case(self)
        c.write("external/seasonal_feed", FEED_COLS, [feed("P1", "Black Friday Deal Acme Drill"),
                                                      feed("P2", "Acme Christmas-pattern sweater")])
        c.write("external/product_descriptor_evidence", DESC_COLS,
                [desc("P1", "Black Friday Deal", "false"), desc("P2", "Christmas-pattern", "true")])
        body = c.run()
        warn = by_key(body["findings"], "promotional_title_text")
        self.assertEqual([(f["severity"], f["entity"]["item_id"]) for f in warn], [("Warning", "P1")])
        self.assertFalse([f for f in body["findings"] if f["entity"].get("item_id") == "P2"])
        self.assertEqual(len(by_key(body["ai_review"], "promotional_title_text")), 1)

    def test_genuine_descriptor_absent_from_title_is_info_opportunity(self):
        c = Case(self)
        c.write("external/seasonal_feed", FEED_COLS, [feed("P2", "Acme sweater")])
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P2", "Christmas-pattern", "true")])
        body = c.run()
        opp = by_key(body["findings"], "truthful_descriptor_opportunity")
        self.assertEqual([f["severity"] for f in opp], ["Info"])
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_unknown_genuine_flag_is_partial_not_a_pass(self):
        c = Case(self)
        c.write("external/seasonal_feed", FEED_COLS, [feed("P2", "Acme sweater")])
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P2", "Christmas-pattern", "")])
        body = c.run()
        self.assertEqual(cov(body, "descriptor_evidence")["status"], "partial")
        self.assertFalse(body["findings"])

    def test_locale_less_evidence_is_never_fanned_out(self):
        c = Case(self)
        c.write("external/seasonal_feed", FEED_COLS, [feed("R", "Acme maglione"), feed("R", "Acme pull", "FR", "fr"),
                                                      feed("U", "Black Friday Acme Pull", "FR", "fr")])
        c.write("external/product_descriptor_evidence", DESC_COLS,
                [desc("R", "Christmas pattern", "true", "", ""), desc("U", "Black Friday", "false", "", "")])
        body = c.run()
        amb = by_key(body["findings"], "ambiguous_product_key")
        self.assertEqual([(f["severity"], f["entity"]["item_id"]) for f in amb], [("Info", "R")])
        self.assertFalse(by_key(body["findings"], "truthful_descriptor_opportunity"))
        # unique merchant+item mapping resolves without locale columns
        self.assertEqual([f["entity"]["item_id"] for f in by_key(body["findings"], "promotional_title_text")], ["U"])
        self.assertEqual(cov(body, "product_key_join")["status"], "partial")

    def test_missing_feed_skips_with_exact_inputs(self):
        c = Case(self)
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P2", "x", "true")])
        body = c.run()
        self.assertEqual(cov(body, "product_key_join")["status"], "skipped")
        self.assertIn("external/seasonal_feed (file)", cov(body, "product_key_join")["missing"])
        self.assertEqual(cov(body, "promotional_title_text")["status"], "skipped")
        self.assertFalse(body["findings"])

    def test_no_product_campaigns_in_complete_inventory_is_not_applicable(self):
        c = Case(self)
        c.write("campaigns", ["id", "channel_type"], [{"id": "S1", "channel_type": "SEARCH"}])
        c.write("external/seasonal_feed", FEED_COLS, [feed("P1", "Black Friday Deal Acme Drill")])
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P1", "Black Friday Deal", "false")])
        body = c.run()
        self.assertEqual(cov(body, "promotional_title_text")["status"], "not_applicable")
        self.assertFalse(body["findings"])

    def _query_case(self, snapshot, impressions):
        c = Case(self, snapshot)
        c.write("external/seasonal_feed", FEED_COLS, [feed("P2", "Acme sweater")])
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P2", "Christmas pattern", "true")])
        c.write("custom/query_product_evidence", QPE_COLS,
                [{"query": "christmas pattern sweater", "merchant_id": "M1", "feed_label": "IT", "language": "it",
                  "item_id": "P2", "date": "2026-08-20", "impressions": impressions, "clicks": "10",
                  "conversions": "1", "mapping_method": "full key", "coverage": "complete"}])
        return c.run()

    def test_query_prioritization_needs_maturity_and_impression_gate(self):
        mature = self._query_case("2026-09-06", "1500")
        self.assertEqual(len(by_key(mature["findings"], "query_supported_descriptor")), 1)
        below = self._query_case("2026-09-06", "999")
        self.assertFalse(by_key(below["findings"], "query_supported_descriptor"))
        immature = self._query_case("2026-08-31", "1500")
        self.assertFalse(by_key(immature["findings"], "query_supported_descriptor"))
        self.assertEqual(cov(immature, "query_mapping")["status"], "partial")

    def test_profile_promo_term_is_review_not_finding(self):
        c = Case(self)
        c.write("external/seasonal_feed", FEED_COLS, [feed("P3", "Acme Discount Drill")])
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P3", "cordless", "true")])
        body = c.run({"promotional_title_terms": ["discount"]})
        self.assertFalse(by_key(body["findings"], "promotional_title_text"))
        rv = [r for r in body["ai_review"] if r["entity"].get("term") == "discount"]
        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0]["outcomes"]["promotional_text"]["severity"], "Warning")

    def test_finalize_verifies_proposed_title(self):
        c = Case(self)
        c.write("external/seasonal_feed", FEED_COLS, [feed("P1", "Black Friday Deal Acme Drill")])
        c.write("external/product_descriptor_evidence", DESC_COLS, [desc("P1", "Black Friday Deal", "false")])
        body = c.run()
        rid = body["ai_review"][0]["id"]
        bad = [{"id": rid, "outcome": "proposal_drafted", "rationale": "r",
                "proposal": {"proposed_title": "Drill Black Friday Deal", "owner": "catalog"}}]
        self.assertEqual(c.finalize(bad), 4)
        good = [{"id": rid, "outcome": "proposal_drafted", "rationale": "r",
                 "proposal": {"proposed_title": "Acme Cordless Drill 18V", "owner": "catalog", "test_plan": "feed test"}}]
        self.assertEqual(c.finalize(good), 0)
        final = json.loads((c.out / "final.json").read_text())
        warn = by_key(final["findings"], "promotional_title_text")
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0]["origin"], "ai_review")


if __name__ == "__main__":
    unittest.main()
