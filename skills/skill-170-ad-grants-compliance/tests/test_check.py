"""test_check.py — skill-170 Ad Grants rule boundaries on synthetic temp exports.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-170-ad-grants-compliance/tests -t skills/skill-170-ad-grants-compliance
rules:   Synthetic temp folders only; never reads the self-test oracle. Deterministic, stdlib only.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes4 | initial tests
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill170_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

PROFILE = "slug: np\nad_grants: true\nad_grants_account_created: 2020-01-01\nbrand_terms: [foodbank]\n"


class Export:
    """A compliant Ad Grants export; tests override one table at a time."""

    def __init__(self, test: unittest.TestCase, profile: str = PROFILE, snapshot: str = "2026-09-10"):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        self.profile_text = profile
        self.tables: dict[str, tuple[list, list, bool]] = {}
        self.set("account", ["customer_id", "name", "currency_code", "time_zone", "date_range_start", "date_range_end",
                             "snapshot_date", "rates_format", "money_unit", "conversion_lag_days"],
                 [["900", "Food Bank", "EUR", "Europe/Rome", "2026-08-01", "2026-08-31", snapshot, "fraction",
                   "currency", "2"]])
        self.set("campaigns", ["id", "status", "channel_type", "bidding_strategy_type", "geo_targets"],
                 [["1", "ENABLED", "SEARCH", "MAXIMIZE_CONVERSIONS", "Milano"]])
        self.set("ad_groups", ["id", "campaign_id", "status"], [["11", "1", "ENABLED"], ["12", "1", "ENABLED"]])
        self.set("ads", ["id", "ad_group_id", "status"], [["a1", "11", "ENABLED"], ["a2", "12", "ENABLED"]])
        self.set("keywords", ["id", "campaign_id", "ad_group_id", "text", "match_type", "status", "quality_score",
                              "landing_page_experience"],
                 [["k1", "1", "11", "food bank milano", "PHRASE", "ENABLED", "7", "AVERAGE"]])
        self.set("assets", ["asset_id", "type", "level", "status", "campaign_id", "ad_group_id"],
                 [["s1", "SITELINK", "ACCOUNT", "ENABLED", "", ""], ["s2", "SITELINK", "CAMPAIGN", "ENABLED", "1", ""]])
        self.set("conversion_actions", ["id", "name", "category", "status", "include_in_conversions"],
                 [["9", "Donation", "PURCHASE", "ENABLED", "true"]])
        self.set("custom/grants_monthly_metrics", ["month", "impressions", "clicks", "conversions", "complete_month"],
                 [["2026-07", 20000, 1200, 30, "true"], ["2026-08", 20000, 1300, 25, "true"]])

    def set(self, name, header, rows, complete=True):
        self.tables[name] = (header, rows, complete)
        return self

    def run(self, cmd="run", decisions=None) -> tuple[int, dict]:
        for name, (header, rows, _) in self.tables.items():
            path = self.export / f"{name}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
        with (self.export / "table_manifest.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "completeness", "truncation"])
            w.writerows([[f"{n}.csv", "complete", "none"] for n, (_, _, c) in self.tables.items() if c])
        prof = self.root / "profile.yaml"
        prof.write_text(self.profile_text)
        out = self.root / "out"
        argv = [cmd, "--export", str(self.export), "--profile", str(prof), "--out", str(out)]
        if decisions is not None:
            dp = self.root / "decisions.json"
            dp.write_text(json.dumps(decisions))
            argv += ["--decisions", str(dp)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=argv)
        path = out / ("final.json" if cmd == "finalize" else "result.json")
        return code, (json.loads(path.read_text()) if path.is_file() else {})


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body, severity=None):
    return sorted(f["condition_key"] for f in body["findings"] if severity in (None, f["severity"]))


def review(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


MONTHLY = ["month", "impressions", "clicks", "conversions", "complete_month"]


class ApplicabilityTests(unittest.TestCase):
    def test_not_applicable_without_ad_grants_flag(self):
        code, body = Export(self, profile="slug: x\n").run()
        self.assertEqual(code, 0)
        self.assertEqual({c["status"] for c in body["coverage"]}, {"not_applicable"})
        self.assertEqual(body["findings"], [])

    def test_compliant_account_has_no_findings(self):
        _, body = Export(self).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["counted_conversion_meaning"])
        for check in ("account_ctr", "low_quality_score", "ad_group_minimum", "sitelink_minimum", "geo_targeting",
                      "bidding_policy", "monthly_conversions"):
            self.assertEqual(cov(body, check)["status"], "completed", check)

    def test_missing_monthly_table_is_skipped_with_exact_inputs(self):
        e = Export(self)
        del e.tables["custom/grants_monthly_metrics"]
        _, body = e.run()
        for check in ("account_ctr", "monthly_conversions"):
            self.assertEqual(cov(body, check)["status"], "skipped")
            self.assertIn("custom/grants_monthly_metrics (file)", cov(body, check)["missing"])

    def test_invalid_rule_override_leaves_rule_unresolved(self):
        _, body = Export(self, profile=PROFILE + "ad_grants_rules: {min_ctr: 5}\n").run()
        self.assertEqual(cov(body, "program_scope")["status"], "partial")
        self.assertEqual(cov(body, "account_ctr")["status"], "partial")
        self.assertEqual(keys(body), [])


class CtrTests(unittest.TestCase):
    def test_two_consecutive_low_months_warn_and_queue_deactivation_review(self):
        e = Export(self).set("custom/grants_monthly_metrics", MONTHLY,
                             [["2026-07", 20000, 800, 30, "true"], ["2026-08", 20000, 900, 25, "true"]])
        _, body = e.run()
        self.assertEqual(keys(body, "Warning"), ["ctr_below_program_minimum", "ctr_below_program_minimum",
                                                 "ctr_deactivation_condition"])
        r = review(body, "ctr_deactivation_condition")
        self.assertEqual(r[0]["outcomes"]["deactivation_evidenced"]["severity"], "Critical")
        self.assertEqual(r[0]["entity"]["months"], ["2026-07", "2026-08"])

    def test_single_low_month_is_not_deactivation_condition(self):
        e = Export(self).set("custom/grants_monthly_metrics", MONTHLY,
                             [["2026-06", 20000, 800, 30, "true"], ["2026-07", 20000, 1200, 30, "true"],
                              ["2026-08", 20000, 900, 25, "true"]])
        _, body = e.run()
        self.assertEqual(keys(body), ["ctr_below_program_minimum", "ctr_below_program_minimum"])
        self.assertEqual(review(body, "ctr_deactivation_condition"), [])

    def test_low_sample_month_is_info(self):
        e = Export(self).set("custom/grants_monthly_metrics", MONTHLY, [["2026-08", 500, 10, 2, "true"]])
        _, body = e.run()
        self.assertEqual(keys(body), ["ctr_below_minimum_low_sample"])
        self.assertEqual(keys(body, "Info"), ["ctr_below_minimum_low_sample"])

    def test_incomplete_month_is_excluded(self):
        e = Export(self).set("custom/grants_monthly_metrics", MONTHLY,
                             [["2026-07", 20000, 1200, 30, "true"], ["2026-08", 20000, 100, 25, "false"]])
        _, body = e.run()
        self.assertNotIn("ctr_below_program_minimum", keys(body))
        self.assertEqual(cov(body, "account_ctr")["status"], "partial")

    def test_smart_only_account_is_exempt_from_ctr_rule(self):
        e = Export(self).set("campaigns", ["id", "status", "channel_type", "bidding_strategy_type", "geo_targets"],
                             [["1", "ENABLED", "SMART", "", "Milano"]])
        e.set("custom/grants_monthly_metrics", MONTHLY, [["2026-08", 20000, 100, 25, "true"]])
        _, body = e.run()
        self.assertEqual(cov(body, "account_ctr")["status"], "not_applicable")
        self.assertNotIn("ctr_below_program_minimum", keys(body))


class KeywordTests(unittest.TestCase):
    COLS = ["id", "campaign_id", "ad_group_id", "text", "match_type", "status", "quality_score", "landing_page_experience"]

    def run_keywords(self, rows, profile=PROFILE):
        e = Export(self, profile=profile).set("keywords", self.COLS, rows)
        e.set("ad_groups", ["id", "campaign_id", "status"],
              [["11", "1", "ENABLED"], ["12", "1", "ENABLED"], ["13", "1", "PAUSED"]])
        return e

    def test_single_word_boundaries(self):
        e = self.run_keywords([
            ["k1", "1", "11", "[donate]", "EXACT", "ENABLED", "7", "AVERAGE"],     # single word → review
            ["k2", "1", "11", "e-books", "BROAD", "ENABLED", "7", "AVERAGE"],      # special char: not single-word
            ["k3", "1", "11", "foodbank", "EXACT", "ENABLED", "7", "AVERAGE"],     # brand exempt
            ["k4", "1", "11", "volunteer", "EXACT", "PAUSED", "7", "AVERAGE"],     # paused keyword
            ["k5", "1", "13", "charity", "EXACT", "ENABLED", "7", "AVERAGE"],      # paused ad group
            ["k6", "1", "12", "food donations milan", "PHRASE", "ENABLED", "7", "AVERAGE"],
        ])
        _, body = e.run()
        singles = [f for f in body["findings"] if f["condition_key"] == "single_word_keyword"]
        self.assertEqual([(f["entity"]["keyword_id"], f["severity"]) for f in singles], [("k1", "Info")])
        self.assertEqual(len(review(body, "single_word_keyword")), 1)

    def test_quality_score_boundary_and_unrated_exemption(self):
        e = self.run_keywords([
            ["k1", "1", "11", "food bank milano", "PHRASE", "ENABLED", "2", "AVERAGE"],
            ["k2", "1", "11", "food bank lombardia", "PHRASE", "ENABLED", "3", "AVERAGE"],
            ["k3", "1", "12", "donate food milano", "PHRASE", "ENABLED", "", "AVERAGE"],
        ])
        _, body = e.run()
        qs = [f for f in body["findings"] if f["condition_key"] == "prohibited_quality_score"]
        self.assertEqual([(f["entity"]["keyword_id"], f["severity"]) for f in qs], [("k1", "Warning")])

    def test_generic_candidates_are_batched_for_review_only(self):
        e = self.run_keywords([
            ["k1", "1", "11", "free videos online", "PHRASE", "ENABLED", "6", "BELOW_AVERAGE"],
            ["k2", "1", "11", "things to do", "PHRASE", "ENABLED", "6", "AVERAGE"],
            ["k3", "1", "12", "food bank milano", "PHRASE", "ENABLED", "7", "AVERAGE"],
        ], profile=PROFILE + "ad_grants_generic_terms: [things to do]\n")
        _, body = e.run()
        r = review(body, "generic_keyword_candidates")
        self.assertEqual(sorted(c["keyword_id"] for c in r[0]["evidence"]["candidates"]), ["k1", "k2"])
        self.assertNotIn("generic_keyword_candidates", keys(body))
        self.assertEqual(cov(body, "generic_keywords")["status"], "partial")  # k3 not screened


class StructureTests(unittest.TestCase):
    def test_ad_group_minimum_needs_complete_inventory(self):
        e = Export(self).set("ad_groups", ["id", "campaign_id", "status"], [["11", "1", "ENABLED"], ["12", "1", "PAUSED"]])
        _, body = e.run()
        self.assertIn("ad_group_minimum", keys(body, "Warning"))
        e2 = Export(self).set("ad_groups", ["id", "campaign_id", "status"], [["11", "1", "ENABLED"]], complete=False)
        _, body2 = e2.run()
        self.assertNotIn("ad_group_minimum", keys(body2))
        self.assertEqual(cov(body2, "ad_group_minimum")["status"], "partial")

    def test_ad_group_without_enabled_ads_is_info(self):
        e = Export(self).set("ads", ["id", "ad_group_id", "status"], [["a1", "11", "ENABLED"], ["a2", "12", "PAUSED"]])
        _, body = e.run()
        self.assertEqual(keys(body), ["ads_per_ad_group"])
        self.assertEqual(keys(body, "Info"), ["ads_per_ad_group"])

    def test_sitelinks_count_unique_enabled_approved_assets(self):
        cols = ["asset_id", "type", "level", "status", "campaign_id", "ad_group_id", "approval_status"]
        e = Export(self).set("assets", cols, [["s1", "SITELINK", "ACCOUNT", "ENABLED", "", "", "APPROVED"],
                                              ["s1", "SITELINK", "CAMPAIGN", "ENABLED", "1", "", "APPROVED"],
                                              ["s2", "SITELINK", "CAMPAIGN", "ENABLED", "1", "", "DISAPPROVED"],
                                              ["c1", "CALLOUT", "ACCOUNT", "ENABLED", "", "", "APPROVED"]])
        _, body = e.run()
        f = [x for x in body["findings"] if x["condition_key"] == "sitelink_minimum"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["evidence"]["sitelink_asset_ids"], ["s1"])

    def test_geo_all_locations_warns_and_blank_is_unknown(self):
        cols = ["id", "status", "channel_type", "bidding_strategy_type", "geo_targets"]
        e = Export(self).set("campaigns", cols, [["1", "ENABLED", "SEARCH", "TARGET_CPA", "All countries and territories"],
                                                 ["2", "ENABLED", "SEARCH", "TARGET_CPA", ""]])
        _, body = e.run()
        self.assertEqual([f["entity"]["campaign_id"] for f in body["findings"]
                          if f["condition_key"] == "no_location_targeting"], ["1"])
        self.assertEqual(cov(body, "geo_targeting")["status"], "partial")


class ConversionAndBiddingTests(unittest.TestCase):
    def test_no_counted_action_warns(self):
        e = Export(self).set("conversion_actions", ["id", "name", "category", "status", "include_in_conversions"],
                             [["9", "Time on site", "ENGAGEMENT", "ENABLED", "false"]])
        _, body = e.run()
        self.assertIn("no_counted_conversion_action", keys(body, "Warning"))

    def test_zero_conversion_month_needs_maturity_for_warning(self):
        rows = [["2026-07", 20000, 1200, 30, "true"], ["2026-08", 20000, 1200, 0, "true"]]
        _, mature = Export(self).set("custom/grants_monthly_metrics", MONTHLY, rows).run()
        self.assertEqual(keys(mature), ["month_below_conversion_minimum"])
        _, immature = Export(self, snapshot="2026-09-01").set("custom/grants_monthly_metrics", MONTHLY, rows).run()
        self.assertEqual(keys(immature), ["month_below_conversion_minimum_immature"])
        self.assertEqual(keys(immature, "Info"), ["month_below_conversion_minimum_immature"])

    def test_bidding_rule_depends_on_creation_date_and_smart_exemption(self):
        cols = ["id", "status", "channel_type", "bidding_strategy_type", "geo_targets"]
        rows = [["1", "ENABLED", "SEARCH", "MANUAL_CPC", "Milano"], ["2", "ENABLED", "SMART", "", "Milano"]]
        _, body = Export(self).set("campaigns", cols, rows).run()
        self.assertEqual([f["entity"]["campaign_id"] for f in body["findings"]
                          if f["condition_key"] == "non_conversion_bidding"], ["1"])
        old = PROFILE.replace("2020-01-01", "2018-06-01")
        _, body = Export(self, profile=old).set("campaigns", cols, rows).run()
        self.assertEqual(cov(body, "bidding_policy")["status"], "not_applicable")
        unknown = PROFILE.replace("ad_grants_account_created: 2020-01-01\n", "")
        _, body = Export(self, profile=unknown).set("campaigns", cols, rows).run()
        self.assertNotIn("non_conversion_bidding", keys(body))
        self.assertEqual(cov(body, "bidding_policy")["status"], "partial")


class FinalizeTests(unittest.TestCase):
    def test_verify_rejects_unsupported_decisions(self):
        e = Export(self).set("custom/grants_monthly_metrics", MONTHLY,
                             [["2026-07", 20000, 800, 30, "true"], ["2026-08", 20000, 900, 25, "true"]])
        e.set("keywords", KeywordTests.COLS, [["k1", "1", "11", "donate", "EXACT", "ENABLED", "7", "BELOW_AVERAGE"],
                                              ["k2", "1", "12", "free food today", "PHRASE", "ENABLED", "7", "BELOW_AVERAGE"]])
        _, body = e.run()
        ctr = review(body, "ctr_deactivation_condition")[0]["id"]
        sw = review(body, "single_word_keyword")[0]["id"]
        gen = review(body, "generic_keyword_candidates")[0]["id"]
        bad = [{"id": ctr, "outcome": "deactivation_evidenced", "rationale": "notice"},
               {"id": sw, "outcome": "allowed_exception", "rationale": "acronym"},
               {"id": gen, "outcome": "some_generic", "rationale": "x", "proposal": {"keyword_ids": ["k9"]}}]
        code, final = e.run("finalize", bad)
        self.assertEqual(code, 4)
        self.assertEqual({x["status"] for x in final["review_log"]}, {"rejected"})
        good = [{"id": ctr, "outcome": "deactivation_evidenced", "rationale": "notice",
                 "proposal": {"evidence_ref": "in-product notification 2026-09-03"}},
                {"id": sw, "outcome": "allowed_exception", "rationale": "brand acronym",
                 "proposal": {"exception_basis": "acronym"}},
                {"id": gen, "outcome": "some_generic", "rationale": "no intent", "proposal": {"keyword_ids": ["k2"]}}]
        code, final = e.run("finalize", good)
        self.assertEqual(code, 0)
        self.assertEqual(keys(final, "Critical"), ["ctr_deactivation_condition"])
        self.assertNotIn("single_word_keyword", keys(final))
        self.assertIn("generic_keyword_candidates", keys(final, "Warning"))


if __name__ == "__main__":
    unittest.main()
