"""test_check.py — decision-boundary tests for skill-082 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-082-product-feed-title-optimization/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
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
_spec = importlib.util.spec_from_file_location("check082", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

MP_COLS = ["merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country", "destination",
           "snapshot_at", "title", "structured_title", "digital_source_type", "brand", "item_group_id", "color",
           "google_product_category"]
REF_COLS = ["merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country",
            "authoritative_title", "verified_brand", "intended_destinations", "evidence_reference", "updated_at"]
MD_COLS = ["merchant_id", "offer_id", "target_country", "destination", "issue_code", "attribute",
           "platform_severity", "eligibility_status", "first_seen_at", "observed_at", "source_reference"]
PD_COLS = ["account_id", "campaign_id", "offer_id", "target_country", "date", "impressions", "clicks"]


def prod(offer, title, **kw):
    base = {"merchant_id": "M1", "channel": "online", "content_language": "it", "feed_label": "IT", "offer_id": offer,
            "target_country": "IT", "destination": "Shopping_ads", "snapshot_at": "2026-09-06", "title": title,
            "brand": "Acme", "google_product_category": "Hardware > Tools"}
    base.update(kw)
    return base


def ref(offer, **kw):
    base = {"merchant_id": "M1", "channel": "online", "content_language": "it", "feed_label": "IT", "offer_id": offer,
            "target_country": "IT", "evidence_reference": f"pim:{offer}", "updated_at": "2026-09-01"}
    base.update(kw)
    return base


def diag(offer, attribute="title", status="disapproved", observed="2026-09-06"):
    return {"merchant_id": "M1", "offer_id": offer, "target_country": "IT", "destination": "Shopping_ads",
            "issue_code": "policy_title", "attribute": attribute, "platform_severity": status,
            "eligibility_status": status, "first_seen_at": "2026-09-01", "observed_at": observed,
            "source_reference": "mc:export"}


class Case:
    def __init__(self, test, snapshot="2026-09-06", campaigns=None):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.files = {}
        self.write("account", ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
                               "conversion_lag_days"],
                   [{"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": "2"}])
        self.write("campaigns", ["id", "channel_type"], campaigns or [{"id": "C1", "channel_type": "SHOPPING"}])

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
        self.prof = self.root / "profile.json"
        self.prof.write_text(json.dumps(profile or {}))
        self.out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(self.export), "--profile", str(self.prof), "--out", str(self.out)])
        assert code == 0
        return json.loads((self.out / "result.json").read_text())

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


def offers(items):
    return sorted(x["entity"].get("offer_id") for x in items)


class CheckTests(unittest.TestCase):
    def test_title_length_boundary_and_unknown_title(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("LONG", "a" * 151), prod("EXACT", "b" * 150), prod("EMPTY", "")])
        body = c.run({"promotional_title_terms": []})
        long_ = by_key(body["findings"], "title_over_150_chars")
        self.assertEqual([(f["entity"]["offer_id"], f["severity"]) for f in long_], [("LONG", "Warning")])
        self.assertEqual(cov(body, "effective_title")["status"], "partial")  # EMPTY is unknown, not zero-length

    def test_structured_title_overrides_title_and_promo_terms_are_word_bounded(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("S", "Acme Drill SALE", structured_title="Acme Drill 18V", digital_source_type="default"),
                 prod("P", "Acme Drill sale"), prod("W", "Acme wholesale drill")])
        body = c.run({"promotional_title_terms": ["sale"]})
        rv = by_key(body["ai_review"], "promotional_title_text")
        self.assertEqual(offers(rv), ["P"])
        self.assertEqual(rv[0]["outcomes"]["promotional_text"]["severity"], "Warning")
        self.assertFalse(by_key(body["findings"], "promotional_title_text"))

    def test_missing_promo_terms_is_partial_not_a_pass(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P", "Acme Drill sale")])
        body = c.run()
        spec = cov(body, "title_spec")
        self.assertEqual(spec["status"], "partial")
        self.assertIn("profile:promotional_title_terms", spec["missing"])
        self.assertIn("external/title_requirements (file)", spec["missing"])

    def test_variant_titles_without_distinction_are_provisional_info(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("R", "Acme Shirt", item_group_id="G1", color="red"),
                 prod("B", "Acme Shirt", item_group_id="G1", color="blue"),
                 prod("X", "Acme Cap", item_group_id="G2", color="red"),
                 prod("Y", "Acme Cap", item_group_id="G2", color="red")])
        body = c.run({"promotional_title_terms": []})
        f = by_key(body["findings"], "variant_distinction_missing")
        self.assertEqual([(x["entity"]["offer_ids"], x["severity"]) for x in f], [(["B", "R"], "Info")])
        rv = by_key(body["ai_review"], "variant_distinction_missing")
        self.assertEqual(rv[0]["provisional_finding"], f[0]["id"])
        self.assertFalse(by_key(body["ai_review"], "shared_title_across_products"))

    def test_title_naming_sibling_variant_is_mismatch_review(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("R", "Acme Shirt Blue", item_group_id="G1", color="red"),
                 prod("B", "Acme Shirt Blue", item_group_id="G1", color="blue")])
        body = c.run({"promotional_title_terms": []})
        self.assertEqual(offers(by_key(body["ai_review"], "variant_title_mismatch")), ["R"])

    def test_repeated_words_and_cross_group_shared_titles_are_reviews(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("REP", "Drill drill Acme"), prod("OK", "Acme Drill 18V"), prod("A", "Tool Set", item_group_id="G1"),
                 prod("B", "Tool Set", item_group_id="G2")])
        body = c.run({"promotional_title_terms": []})
        self.assertEqual(offers(by_key(body["ai_review"], "repeated_title_terms")), ["REP"])
        shared = by_key(body["ai_review"], "shared_title_across_products")
        self.assertEqual([r["entity"]["offer_ids"] for r in shared], [["A", "B"]])
        self.assertFalse(body["findings"])

    def test_reference_brand_and_authoritative_title(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("NOBRAND", "Cordless Drill"), prod("SAME", "acme  cordless drill"), prod("DIFF", "Acme Saw")])
        c.write("external/product_reference", REF_COLS,
                [ref("NOBRAND", verified_brand="Acme", authoritative_title="Cordless Drill"),
                 ref("SAME", verified_brand="Acme", authoritative_title="Acme Cordless Drill"),
                 ref("DIFF", verified_brand="Acme", authoritative_title="Acme Cordless Drill")])
        body = c.run({"promotional_title_terms": []})
        info = by_key(body["findings"], "verified_brand_absent_from_title")
        self.assertEqual([(f["entity"]["offer_id"], f["severity"]) for f in info], [("NOBRAND", "Info")])
        self.assertEqual(offers(by_key(body["ai_review"], "title_differs_from_reference")), ["DIFF"])
        self.assertEqual(cov(body, "revision_support")["status"], "completed")

    def test_unmatched_reference_is_partial(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P1", "Drill")])
        c.write("external/product_reference", REF_COLS, [ref("OTHER", verified_brand="Acme")])
        body = c.run({"promotional_title_terms": []})
        self.assertEqual(cov(body, "revision_support")["status"], "partial")
        self.assertFalse(body["findings"])

    def _cohort(self, snapshot, impressions):
        c = Case(self, snapshot)
        c.write("external/merchant_products", MP_COLS, [prod("LONG", "a" * 151), prod("OK", "Acme Drill")])
        c.write("custom/product_daily", PD_COLS,
                [{"account_id": "demo", "campaign_id": "C1", "offer_id": o, "target_country": "IT",
                  "date": "2026-08-10", "impressions": impressions, "clicks": "20"} for o in ("LONG", "OK")])
        body = c.run({"promotional_title_terms": []})
        return [o["data"] for o in body["observations"] if o["check"] == "title_cohort_ctr" and "category" in o["data"]][0], body

    def test_cohort_ctr_needs_maturity_and_both_samples(self):
        gated, _ = self._cohort("2026-09-06", "1000")
        self.assertTrue(gated["sample_gate_met"])
        self.assertEqual(gated["screened_ctr"], 0.02)
        below, _ = self._cohort("2026-09-06", "999")
        self.assertFalse(below["sample_gate_met"])
        self.assertIsNone(below["screened_ctr"])
        immature, body = self._cohort("2026-08-31", "1000")
        self.assertIsNone(immature["screened_ctr"])
        self.assertEqual(cov(body, "title_cohort_ctr")["status"], "partial")

    def test_title_disapproval_critical_needs_evidence_ref_and_current(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("CUR", "Acme Drill"), prod("OLD", "Acme Saw"),
                                                        prod("GT", "Acme Nail")])
        c.write("external/merchant_diagnostics", MD_COLS,
                [diag("CUR"), diag("OLD", observed="2026-08-01"), diag("GT", attribute="gtin")])
        body = c.run({"promotional_title_terms": []})
        sev = {f["entity"]["offer_id"]: f["severity"] for f in by_key(body["findings"], "title_disapproval")}
        self.assertEqual(sev, {"CUR": "Warning", "OLD": "Info"})
        self.assertFalse([f for f in body["findings"] if f["entity"].get("offer_id") == "GT"])
        items = {r["entity"]["offer_id"]: r["id"] for r in by_key(body["ai_review"], "title_disapproval")}
        crit = {"outcome": "material_intended_delivery_blocked", "rationale": "hero SKU"}
        self.assertEqual(c.finalize([{"id": items["CUR"], **crit}]), 4)
        self.assertEqual(c.finalize([{"id": items["OLD"], **crit, "proposal": {"evidence_ref": "crm:1"}}]), 4)
        self.assertEqual(c.finalize([{"id": items["CUR"], **crit, "proposal": {"evidence_ref": "crm:1"}}]), 0)
        final = json.loads((c.out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in by_key(final["findings"], "title_disapproval")
                          if f["entity"]["offer_id"] == "CUR"], ["Critical"])

    def test_finalize_verifies_proposed_title(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("R", "Acme Shirt sale", item_group_id="G1", color="red"),
                 prod("B", "Acme Shirt Blue", item_group_id="G1", color="blue")])
        body = c.run({"promotional_title_terms": ["sale"]})
        rid = by_key(body["ai_review"], "promotional_title_text")[0]["id"]
        warn = {"id": rid, "outcome": "promotional_text", "rationale": "sale is not a product fact"}
        for bad in ({"proposed_title": "Acme Shirt Red", "fact_reference": ""},
                    {"proposed_title": "Acme Shirt Blue", "fact_reference": "pim:R"},
                    {"proposed_title": "x" * 151, "fact_reference": "pim:R"},
                    {"proposed_title": "Acme Shirt Red", "fact_reference": "pim:R", "ai_generated": True}):
            self.assertEqual(c.finalize([{**warn, "proposal": bad}]), 4, bad)
        good = {"proposed_title": "Acme Shirt Red", "fact_reference": "pim:R", "ai_generated": True,
                "attribute": "structured_title", "digital_source_type": "trained_algorithmic_media"}
        self.assertEqual(c.finalize([{**warn, "proposal": good}]), 0)
        final = json.loads((c.out / "final.json").read_text())
        self.assertEqual([f["origin"] for f in by_key(final["findings"], "promotional_title_text")], ["ai_review"])

    def test_missing_feed_skips_with_exact_inputs(self):
        c = Case(self)
        body = c.run()
        for check in ("catalog_join", "effective_title", "title_spec", "title_clarity", "revision_support"):
            self.assertEqual(cov(body, check)["status"], "skipped")
            self.assertIn("external/merchant_products (file)", cov(body, check)["missing"])
        self.assertFalse(body["findings"])

    def test_no_product_campaigns_in_complete_inventory_is_not_applicable(self):
        c = Case(self, campaigns=[{"id": "S1", "channel_type": "SEARCH"}])
        c.write("external/merchant_products", MP_COLS, [prod("LONG", "a" * 151)])
        body = c.run()
        self.assertEqual({x["status"] for x in body["coverage"]}, {"not_applicable"})
        self.assertFalse(body["findings"])


if __name__ == "__main__":
    unittest.main()
