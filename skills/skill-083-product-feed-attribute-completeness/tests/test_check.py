"""test_check.py — decision-boundary tests for skill-083 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-083-product-feed-attribute-completeness/tests
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
_spec = importlib.util.spec_from_file_location("check083", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

MP_COLS = ["merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country", "destination",
           "snapshot_at", "brand", "gtin", "mpn", "identifier_exists", "condition", "google_product_category",
           "color", "size", "item_group_id"]
REF_COLS = ["merchant_id", "channel", "content_language", "feed_label", "offer_id", "target_country",
            "verified_gtin", "verified_brand", "identifier_assignment_status", "intended_destinations",
            "evidence_reference", "updated_at"]
AR_COLS = ["market", "destination", "category", "condition", "attribute", "required_when", "exceptions",
           "source_url", "checked_at", "accepted_format"]
MD_COLS = ["merchant_id", "offer_id", "target_country", "destination", "issue_code", "attribute",
           "platform_severity", "eligibility_status", "issue_text", "first_seen_at", "observed_at", "source_reference"]
PD_COLS = ["account_id", "campaign_id", "offer_id", "target_country", "date", "impressions", "clicks", "cost"]


def prod(offer, **kw):
    base = {"merchant_id": "M1", "channel": "online", "content_language": "it", "feed_label": "IT", "offer_id": offer,
            "target_country": "IT", "destination": "Shopping_ads", "snapshot_at": "2026-09-06", "brand": "Acme",
            "condition": "new", "google_product_category": "Hardware > Tools", "identifier_exists": "true"}
    base.update(kw)
    return base


def ref(offer, **kw):
    base = {"merchant_id": "M1", "channel": "online", "content_language": "it", "feed_label": "IT", "offer_id": offer,
            "target_country": "IT", "evidence_reference": f"pim:{offer}", "updated_at": "2026-09-01"}
    base.update(kw)
    return base


def req(attribute, category="*", required_when="always", exceptions="", condition="*"):
    return {"market": "IT", "destination": "Shopping_ads", "category": category, "condition": condition,
            "attribute": attribute, "required_when": required_when, "exceptions": exceptions,
            "source_url": "https://support.google.com/merchants", "checked_at": "2026-09-01"}


def diag(offer, attribute="gtin", status="disapproved", observed="2026-09-06", code="invalid_gtin"):
    return {"merchant_id": "M1", "offer_id": offer, "target_country": "IT", "destination": "Shopping_ads",
            "issue_code": code, "attribute": attribute, "platform_severity": status, "eligibility_status": status,
            "first_seen_at": "2026-07-01", "observed_at": observed, "source_reference": "mc:export"}


class Case:
    def __init__(self, test, campaigns=None):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.files = {}
        self.write("account", ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
                               "conversion_lag_days"],
                   [{"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}])
        self.write("campaigns", ["id", "channel_type"],
                   campaigns or [{"id": "C1", "channel_type": "SHOPPING"}, {"id": "P1", "channel_type": "PERFORMANCE_MAX"}])

    def write(self, key, cols, rows, completeness="complete"):
        p = self.export / f"{key}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
        self.files[f"{key}.csv"] = completeness

    def run(self, profile=None):
        with (self.export / "table_manifest.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "completeness", "truncation"])
            for fn in sorted(self.files):
                w.writerow([fn, self.files[fn], "none"])
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
    def test_gtin_check_digit_and_length(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("BAD", gtin="4006381333932"), prod("SHORT", gtin="12345"), prod("OK13", gtin="4006381333931"),
                 prod("OK12", gtin="036000291452"), prod("OK14", gtin="00036000291452")])
        body = c.run()
        bad = by_key(body["findings"], "invalid_gtin")
        self.assertEqual(offers(bad), ["BAD", "SHORT"])
        self.assertEqual({f["severity"] for f in bad}, {"Warning"})

    def test_gtin_copied_across_variants_only_when_variants_differ(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("RED", gtin="4006381333931", color="red"), prod("BLUE", gtin="4006381333931", color="blue"),
                 prod("A", gtin="036000291452", color="red"), prod("B", gtin="036000291452", color="red")])
        body = c.run()
        shared = by_key(body["findings"], "gtin_shared_across_variants")
        self.assertEqual([f["entity"]["offer_ids"] for f in shared], [["BLUE", "RED"]])
        self.assertEqual(shared[0]["severity"], "Warning")

    def test_reference_mismatch_and_zero_padded_equality(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("P1", gtin="036000291452", brand="Acme"), prod("P2", gtin="4006381333931", brand="acme ")])
        c.write("external/product_reference", REF_COLS,
                [ref("P1", verified_gtin="0036000291452", verified_brand="Other"),
                 ref("P2", verified_gtin="4006381333931", verified_brand="Acme")])
        body = c.run()
        mm = by_key(body["findings"], "source_to_feed_mismatch")
        self.assertEqual([(f["entity"]["offer_id"], f["entity"]["attribute"]) for f in mm], [("P1", "brand")])
        self.assertEqual(cov(body, "reference_match")["status"], "completed")

    def test_identifier_exists_false_versus_legitimately_unassigned(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("HID", identifier_exists="false"), prod("UNA", identifier_exists="false")])
        c.write("external/product_reference", REF_COLS,
                [ref("HID", verified_gtin="4006381333931"), ref("UNA", identifier_assignment_status="unassigned")])
        body = c.run()
        self.assertEqual(offers(by_key(body["findings"], "identifier_exists_false_with_assigned_gtin")), ["HID"])
        info = by_key(body["findings"], "identifier_legitimately_unassigned")
        self.assertEqual([(f["entity"]["offer_id"], f["severity"]) for f in info], [("UNA", "Info")])

    def test_unmatched_reference_is_partial_not_a_pass(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P1", brand="Acme")])
        c.write("external/product_reference", REF_COLS, [ref("OTHER", verified_brand="Else")])
        body = c.run()
        self.assertEqual(cov(body, "reference_match")["status"], "partial")
        self.assertFalse(body["findings"])

    def test_strict_requirement_missing_is_warning_only_in_matching_category(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("SHIRT", google_product_category="Apparel & Accessories > Clothing", color=""),
                 prod("DRILL", google_product_category="Hardware > Tools", color=""),
                 prod("HAT", google_product_category="Apparel & Accessories > Hats", color="red")])
        c.write("external/attribute_requirements", AR_COLS, [req("color", category="Apparel & Accessories")])
        body = c.run()
        miss = by_key(body["findings"], "applicable_attribute_missing")
        self.assertEqual([(f["entity"]["offer_id"], f["severity"]) for f in miss], [("SHIRT", "Warning")])
        self.assertFalse(body["ai_review"])
        obs = [o["data"] for o in body["observations"] if o["check"] == "attribute_coverage"]
        self.assertEqual((obs[0]["applicable"], obs[0]["populated"], obs[0]["missing"]), (2, 1, 1))
        self.assertEqual(obs[0]["populated_share"], 0.5)

    def test_exceptions_or_conditional_requirements_go_to_review(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P1", size=""), prod("P2", mpn="")])
        c.write("external/attribute_requirements", AR_COLS,
                [req("size", exceptions="one-size items"), req("mpn", required_when="if_no_gtin")])
        body = c.run()
        self.assertFalse(by_key(body["findings"], "applicable_attribute_missing"))
        rv = by_key(body["ai_review"], "requirement_applicability")
        self.assertEqual(sorted(r["entity"]["attribute"] for r in rv), ["mpn", "size"])
        self.assertEqual(rv[0]["outcomes"]["applicable_missing"]["severity"], "Warning")
        self.assertNotIn("Critical", {o["severity"] for r in rv for o in r["outcomes"].values()})

    def test_identifier_exists_false_blocks_deterministic_gtin_missing(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P1", gtin="", identifier_exists="false"),
                                                        prod("P2", gtin="", identifier_exists="true")])
        c.write("external/attribute_requirements", AR_COLS, [req("gtin")])
        body = c.run()
        self.assertEqual(offers(by_key(body["findings"], "applicable_attribute_missing")), ["P2"])
        rv = by_key(body["ai_review"], "requirement_applicability")
        self.assertEqual([k["offer_id"] for k in rv[0]["evidence"]["product_keys"]], ["P1"])

    def test_unknown_category_is_unresolved_partial(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P1", google_product_category="", color="")])
        c.write("external/attribute_requirements", AR_COLS, [req("color", category="Apparel & Accessories")])
        body = c.run()
        self.assertFalse(body["findings"])
        self.assertEqual(cov(body, "requirement_applicability")["status"], "partial")

    def test_zero_applicable_denominator_and_uncertified_catalog_give_no_share(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("P1", color="n/a")])
        c.write("external/attribute_requirements", AR_COLS, [req("color")])
        body = c.run()
        obs = [o["data"] for o in body["observations"] if o["check"] == "attribute_coverage"][0]
        self.assertEqual((obs["applicable"], obs["exempt"]), (1, 1))
        self.assertIsNone(obs["populated_share"])
        c2 = Case(self)
        c2.write("external/merchant_products", MP_COLS, [prod("P1", color="")], completeness="partial sample")
        c2.write("external/attribute_requirements", AR_COLS, [req("color")])
        body2 = c2.run()
        self.assertEqual(cov(body2, "attribute_coverage")["status"], "partial")
        obs2 = [o["data"] for o in body2["observations"] if o["check"] == "attribute_coverage"][0]
        self.assertIsNone(obs2["populated_share"])

    def test_current_disapproval_is_provisional_warning_stale_is_info(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("CUR"), prod("OLD"), prod("NODIAG")])
        c.write("external/merchant_diagnostics", MD_COLS,
                [diag("CUR"), diag("OLD", observed="2026-08-01"), diag("CUR", attribute="title", code="title_long")])
        body = c.run()
        dis = {f["entity"]["offer_id"]: f["severity"] for f in by_key(body["findings"], "attribute_disapproval")}
        self.assertEqual(dis, {"CUR": "Warning", "OLD": "Info"})
        rv = by_key(body["ai_review"], "attribute_disapproval")
        self.assertEqual(len(rv), 2)
        self.assertEqual(rv[0]["outcomes"]["material_intended_delivery_blocked"]["severity"], "Critical")
        self.assertFalse([f for f in body["findings"] if f["entity"].get("attribute") == "title"])
        self.assertEqual(body["counts"]["Critical"], 0)
        self.assertEqual(cov(body, "diagnostic_blockers")["status"], "partial")  # NODIAG has no diagnostics row

    def test_demoted_current_warning_non_blocking_notice_info(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("DEM"), prod("NOTE")])
        c.write("external/merchant_diagnostics", MD_COLS,
                [diag("DEM", attribute="color", status="demoted"), diag("NOTE", attribute="color", status="unaffected")])
        body = c.run()
        self.assertEqual(offers(by_key(body["findings"], "attribute_diagnostic_issue")), ["DEM"])
        self.assertEqual([f["severity"] for f in by_key(body["findings"], "attribute_diagnostic_notice")], ["Info"])

    def test_finalize_critical_needs_evidence_ref_and_current_diagnostic(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("CUR"), prod("OLD")])
        c.write("external/merchant_diagnostics", MD_COLS, [diag("CUR"), diag("OLD", observed="2026-08-01")])
        c.write("custom/product_daily", PD_COLS,
                [{"account_id": "demo", "campaign_id": "P1", "offer_id": "CUR", "target_country": "IT",
                  "date": "2026-08-10", "impressions": "900", "clicks": "40", "cost": "55"}])
        body = c.run()
        items = {r["entity"]["offer_id"]: r for r in body["ai_review"]}
        self.assertEqual(items["CUR"]["evidence"]["delivered_exposure"]["pmax_campaign_ids"], ["P1"])
        crit = {"outcome": "material_intended_delivery_blocked", "rationale": "top seller"}
        self.assertEqual(c.finalize([{"id": items["CUR"]["id"], **crit, "proposal": {}}]), 4)
        self.assertEqual(c.finalize([{"id": items["OLD"]["id"], **crit, "proposal": {"evidence_ref": "crm:1"}}]), 4)
        self.assertEqual(c.finalize([{"id": items["CUR"]["id"], **crit, "proposal": {"evidence_ref": "crm:1"}}]), 0)
        final = json.loads((c.out / "final.json").read_text())
        sev = {f["entity"]["offer_id"]: f["severity"] for f in by_key(final["findings"], "attribute_disapproval")}
        self.assertEqual(sev["CUR"], "Critical")

    def test_unintended_destination_rejects_critical(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS, [prod("CUR")])
        c.write("external/product_reference", REF_COLS, [ref("CUR", intended_destinations="Free_listings")])
        c.write("external/merchant_diagnostics", MD_COLS, [diag("CUR")])
        body = c.run()
        rid = by_key(body["ai_review"], "attribute_disapproval")[0]["id"]
        self.assertEqual(c.finalize([{"id": rid, "outcome": "material_intended_delivery_blocked", "rationale": "r",
                                      "proposal": {"evidence_ref": "crm:1"}}]), 4)

    def test_conflicting_duplicate_keys_are_excluded(self):
        c = Case(self)
        c.write("external/merchant_products", MP_COLS,
                [prod("DUP", gtin="12345"), prod("DUP", gtin="4006381333931"), prod("SAME", gtin="1"),
                 prod("SAME", gtin="1")])
        body = c.run()
        self.assertEqual(cov(body, "catalog_inventory")["status"], "partial")
        self.assertEqual(offers(by_key(body["findings"], "invalid_gtin")), ["SAME"])

    def test_missing_feed_keeps_ads_sample_descriptive(self):
        c = Case(self)
        c.write("custom/product_daily", ["account_id", "campaign_id", "offer_id", "date", "clicks", "cost"],
                [{"account_id": "demo", "campaign_id": "C1", "offer_id": "X", "date": "2026-08-20", "clicks": "10",
                  "cost": "0"}])
        body = c.run()
        self.assertFalse(body["findings"])
        self.assertFalse(body["ai_review"])
        for check in ("catalog_inventory", "identifier_syntax", "requirement_applicability", "diagnostic_blockers"):
            self.assertEqual(cov(body, check)["status"], "skipped")
        self.assertIn("external/merchant_products (file)", cov(body, "catalog_inventory")["missing"])
        pr = cov(body, "product_prioritization")
        self.assertEqual(pr["status"], "partial")
        self.assertIn("custom/product_daily:target_country", pr["missing"])

    def test_no_product_campaigns_in_complete_inventory_is_not_applicable(self):
        c = Case(self, campaigns=[{"id": "S1", "channel_type": "SEARCH"}])
        c.write("external/merchant_products", MP_COLS, [prod("BAD", gtin="12345")])
        body = c.run()
        self.assertEqual({x["status"] for x in body["coverage"]}, {"not_applicable"})
        self.assertFalse(body["findings"])


if __name__ == "__main__":
    unittest.main()
