"""test_check.py — Decision-boundary tests for skill-164 PMax search terms and categories.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-164-pmax-search-terms-and-categories/tests -t skills/skill-164-pmax-search-terms-and-categories
rules:   Synthetic temp exports only; assert findings, reviews, coverage and finalize exit codes, never wording.
Every planted defect sits next to a plausible valid counterexample.
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
_spec = importlib.util.spec_from_file_location("skill164_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

PRIOR, CURRENT = "2026-08-05", "2026-08-20"
CAMPAIGNS = ("id,name,status,channel_type,goal_ids\n50,PMax A,ENABLED,PERFORMANCE_MAX,purchase\n"
             "51,PMax B,ENABLED,PERFORMANCE_MAX,purchase\n60,Search,ENABLED,SEARCH,purchase\n")
PROFILE = ("brand_terms: [acme]\ncompetitor_terms: [rivalco]\ncampaign_objectives:\n"
           "  50: {goal_ids: [purchase], brand_policy: nonbrand_only}\n"
           "  51: {goal_ids: [purchase], brand_policy: brand_allowed}\n")
BASE = {
    "conversion_actions.csv": "id,name,status,last_conversion_date\npurchase,Purchase,ENABLED,2026-08-29\n",
    "negative_keywords.csv": "text,match_type,level,campaign_id,status\nfree,PHRASE,account,,ENABLED\n",
    "shared_negative_lists.csv": "list_id,name,keywords,campaign_ids\n",
    "search_terms.csv": "search_term,campaign_id,ad_group_id,clicks,cost,conversions\ncheap hammer set,60,1,10,5,2\n",
    "keywords.csv": "id,campaign_id,ad_group_id,text,match_type,status\nk1,60,1,hammer,BROAD,ENABLED\n",
}


def _account(lag="2"):
    return ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
            f"money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
            f"2026-09-06,fraction,currency,interaction_date,{lag}\n")


def _cats(rows, cost=False):
    hdr = "account_id,campaign_id,category_id,category_label,date,impressions,clicks,conversions,conversion_value"
    return hdr + (",cost" if cost else "") + "\n" + "".join(",".join(["1", *map(str, r)]) + "\n" for r in rows)


def _terms(rows, cost=False):
    hdr = "account_id,campaign_id,category_id,search_term,date,impressions,clicks,conversions,conversion_value"
    return hdr + (",cost" if cost else "") + "\n" + "".join(",".join(["1", *map(str, r)]) + "\n" for r in rows)


class Base(unittest.TestCase):
    def export(self, cats=None, terms=None, *, lag="2", completeness="complete", campaigns=CAMPAIGNS) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        files = {"account.csv": _account(lag), "campaigns.csv": campaigns, **BASE}
        if cats is not None:
            files["custom/pmax_search_categories.csv"] = cats
        if terms is not None:
            files["custom/pmax_search_terms.csv"] = terms
        files["table_manifest.csv"] = "filename,completeness,truncation\n" + "".join(
            f"{f},{completeness},none\n" for f in sorted(files))
        for name, text in files.items():
            p = base / "export" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (base / "profile.yaml").write_text(PROFILE)
        self.profile, self.out = base / "profile.yaml", base / "out"
        return base / "export"

    def run_check(self, root: Path) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--profile", str(self.profile), "--out", str(self.out)])
        self.assertEqual(code, 0)
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, root: Path, decisions: list) -> tuple[int, dict]:
        d = self.out / "decisions.json"
        d.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(root), "--profile", str(self.profile), "--out",
                               str(self.out), "--decisions", str(d)])
        return code, json.loads((self.out / "final.json").read_text())

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def reviews(body, key):
        return [r for r in body["ai_review"] if r["condition_key"] == key]

    @staticmethod
    def severities(review):
        return {o["severity"] for o in review["outcomes"].values()}


class NonConvertingCategories(Base):
    ROWS = [(50, "c1", "cheap tools", PRIOR, 3000, 150, 0, 0), (50, "c2", "power drills", PRIOR, 3000, 150, 3, 90),
            (50, "c3", "ladders", PRIOR, 3000, 50, 0, 0)]

    def test_no_cost_report_caps_review_at_info(self):
        body = self.run_check(self.export(_cats(self.ROWS)))
        rev = self.reviews(body, "zero_conversion_category")
        self.assertEqual([r["entity"]["category"] for r in rev], ["cheap tools"])  # c2 converts, c3 < min_clicks
        self.assertNotIn("Warning", self.severities(rev[0]))
        self.assertEqual(self.cov(body, "nonconverting_categories")["status"], "partial")

    def test_reported_cost_at_floor_opens_warning_path(self):
        rows = [r + (80,) for r in self.ROWS] + [(51, "c9", "garden hoses", PRIOR, 3000, 150, 0, 0, 30)]
        body = self.run_check(self.export(_cats(rows, cost=True)))
        rev = self.reviews(body, "zero_conversion_category")
        self.assertEqual([r["entity"]["category"] for r in rev], ["cheap tools"])  # garden hoses below spend_floor
        self.assertIn("Warning", self.severities(rev[0]))

    def test_immature_window_blocks_screening(self):
        body = self.run_check(self.export(_cats(self.ROWS), lag="10"))
        self.assertEqual(self.reviews(body, "zero_conversion_category"), [])
        self.assertNotIn("zero_conversion_category", {f["condition_key"] for f in body["findings"]})
        self.assertEqual(self.cov(body, "nonconverting_categories")["status"], "partial")

    def test_brand_category_is_never_a_negative_candidate(self):
        body = self.run_check(self.export(_cats([(51, "b1", "acme drills", PRIOR, 3000, 150, 0, 0)])))
        self.assertEqual(self.reviews(body, "zero_conversion_category"), [])


class NonConvertingTerms(Base):
    CATS = _cats([(50, "c1", "tools", PRIOR, 5000, 400, 5, 100)])
    TERMS = _terms([(50, "c1", "cheap tools download", PRIOR, 3000, 150, 0, 0, 90),
                    (50, "c1", "free tools", PRIOR, 3000, 150, 0, 0, 90)], cost=True)

    def test_already_negated_term_is_not_reviewed(self):
        body = self.run_check(self.export(self.CATS, self.TERMS))
        self.assertEqual([r["entity"]["term"] for r in self.reviews(body, "zero_conversion_term")],
                         ["cheap tools download"])

    def test_missing_term_report_skips_only_term_screening(self):
        body = self.run_check(self.export(self.CATS))
        self.assertEqual(self.cov(body, "nonconverting_terms")["status"], "skipped")
        self.assertEqual(self.cov(body, "nonconverting_categories")["status"], "partial")  # no cost column

    def test_negative_proposal_verification(self):
        root = self.export(self.CATS, self.TERMS)
        rid = self.reviews(self.run_check(root), "zero_conversion_term")[0]["id"]

        def decide(outcome, proposal):
            return self.finalize(root, [{"id": rid, "outcome": outcome, "rationale": "r", "proposal": proposal}])[0]

        self.assertEqual(decide("unwanted_intent", {"control": "account_negative", "negative": "cheap",
                                                    "match_type": "PHRASE"}), 4)  # blocks converting Search query
        self.assertEqual(decide("unwanted_intent", {"control": "account_negative", "negative": "drills",
                                                    "match_type": "PHRASE"}), 4)  # does not block reviewed term
        self.assertEqual(decide("unwanted_intent", {"control": "campaign_exclusion_list", "negative": "download"}), 4)
        self.assertEqual(decide("must_not_serve_evidenced", {"control": "account_negative", "negative": "download",
                                                             "match_type": "PHRASE"}), 4)  # no evidence_ref
        code, final = self.finalize(root, [{"id": rid, "outcome": "unwanted_intent", "rationale": "r", "proposal": {
            "control": "account_negative", "negative": "download", "match_type": "PHRASE"}}])
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Warning"], 1)


class BrandPresence(Base):
    ROWS = [(50, "b1", "acme drills", PRIOR, 2000, 40, 4, 100), (50, "c1", "drills", PRIOR, 2000, 60, 4, 100),
            (51, "b1", "acme drills", PRIOR, 2000, 40, 4, 100)]

    def test_review_only_for_documented_nonbrand_policy(self):
        body = self.run_check(self.export(_cats(self.ROWS)))
        rev = self.reviews(body, "brand_traffic_in_nonbrand_pmax")
        self.assertEqual([r["entity"]["campaign_id"] for r in rev], ["50"])
        self.assertEqual(rev[0]["evidence"]["brand_click_share"], 0.4)

    def test_mismatch_proposal_must_name_own_brand(self):
        root = self.export(_cats(self.ROWS))
        rid = self.reviews(self.run_check(root), "brand_traffic_in_nonbrand_pmax")[0]["id"]
        code, _ = self.finalize(root, [{"id": rid, "outcome": "policy_mismatch", "rationale": "r",
                                        "proposal": {"control": "brand_exclusion", "brand": "rivalco"}}])
        self.assertEqual(code, 4)
        code, final = self.finalize(root, [{"id": rid, "outcome": "policy_mismatch", "rationale": "r",
                                            "proposal": {"control": "brand_exclusion", "brand": "Acme"}}])
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Warning"], 1)


class Trends(Base):
    ROWS = [(50, "g", "garden tools", PRIOR, 1000, 10, 0, 0), (50, "g", "garden tools", CURRENT, 2000, 20, 0, 0),
            (50, "d", "drills", PRIOR, 2000, 10, 0, 0), (50, "d", "drills", CURRENT, 1000, 10, 0, 0),
            (50, "f", "files", PRIOR, 2000, 10, 0, 0), (50, "f", "files", CURRENT, 1700, 10, 0, 0),
            (50, "s", "saws", PRIOR, 500, 10, 0, 0), (50, "s", "saws", CURRENT, 100, 10, 0, 0),
            (50, "v", "vices", PRIOR, 1500, 10, 0, 0)]

    def test_qualified_changes_only(self):
        body = self.run_check(self.export(_cats(self.ROWS)))
        keys = {(f["condition_key"], f["entity"]["category"]) for f in body["findings"]}
        self.assertEqual(keys, {("category_growth", "garden tools"), ("category_decline", "drills"),
                                ("category_vanished", "vices")})
        self.assertEqual([r["entity"]["category"] for r in self.reviews(body, "category_growth")], ["garden tools"])

    def test_vanished_needs_certified_report(self):
        body = self.run_check(self.export(_cats(self.ROWS), completeness="partial"))
        self.assertNotIn("category_vanished", {f["condition_key"] for f in body["findings"]})
        self.assertEqual(self.cov(body, "category_trends")["status"], "partial")

    def test_missing_date_skips_trends(self):
        text = _cats(self.ROWS).replace(",date,", ",day,", 1)
        body = self.run_check(self.export(text))
        self.assertEqual(self.cov(body, "category_trends")["status"], "skipped")
        self.assertIn("custom/pmax_search_categories:date", self.cov(body, "category_trends")["missing"])

    def test_search_theme_must_not_be_blocked_by_existing_negative(self):
        root = self.export(_cats(self.ROWS))
        rid = self.reviews(self.run_check(root), "category_growth")[0]["id"]
        code, _ = self.finalize(root, [{"id": rid, "outcome": "relevant_opportunity", "rationale": "r",
                                        "proposal": {"control": "search_theme", "theme": "free garden tools"}}])
        self.assertEqual(code, 4)
        code, _ = self.finalize(root, [{"id": rid, "outcome": "relevant_opportunity", "rationale": "r",
                                        "proposal": {"control": "search_theme", "theme": "garden tools"}}])
        self.assertEqual(code, 0)


class Scope(Base):
    def test_missing_category_report_skips_insight_checks(self):
        body = self.run_check(self.export())
        statuses = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(statuses.pop("control_inventory"), "completed")
        self.assertTrue(all(s == "skipped" for s in statuses.values()))
        self.assertEqual(body["findings"], [])

    def test_non_pmax_rows_are_excluded(self):
        body = self.run_check(self.export(_cats([(60, "c1", "cheap tools", PRIOR, 3000, 150, 0, 0)])))
        self.assertEqual(body["ai_review"], [])

    def test_no_pmax_campaigns_is_not_applicable(self):
        body = self.run_check(self.export(campaigns="id,name,status,channel_type\n60,S,ENABLED,SEARCH\n"))
        self.assertTrue(all(c["status"] == "not_applicable" for c in body["coverage"]))


if __name__ == "__main__":
    unittest.main()
