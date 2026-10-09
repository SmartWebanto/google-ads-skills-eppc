"""test_check.py — skill-094 decision boundaries: hypotheses stay Info, documented brand mismatch, gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-094-pmax-cannibalizing-search-detection/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "check.py"
sys.path.insert(0, str(HERE.parents[1] / "_resources" / "runtime"))
_spec = importlib.util.spec_from_file_location("check094", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,currency_code,date_range_start,date_range_end,snapshot_date,conversion_lag_days,money_unit,"
           "rates_format\nA,EUR,2026-08-01,2026-08-30,{snap},2,currency,fraction\n")
CAMPAIGNS = "id,name,status,channel_type,goal_ids\nS1,Search,ENABLED,SEARCH,purchase\nP1,PMax,ENABLED,PERFORMANCE_MAX,purchase\n"


def _csv(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class Base(unittest.TestCase):
    def make(self, files: dict, profile: dict | None = None, snap="2026-09-06"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        exp = root / "export"
        _csv(exp / "account.csv", ACCOUNT.format(snap=snap))
        _csv(exp / "campaigns.csv", CAMPAIGNS)
        for k, v in files.items():
            _csv(exp / k, v)
        prof = root / "profile.json"
        prof.write_text(json.dumps(profile or {"brand_terms": ["acme"]}))
        self.root, self.exp, self.prof = root, exp, prof
        return cli.run_once(M.SKILL, M.VERSION, M.run, exp, prof).finish()

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def keys(body, sev=None):
        return [f["condition_key"] for f in body["findings"] if sev in (None, f["severity"])]


def _metrics(s_conv, p_conv):
    return ("campaign_id,impressions,clicks,cost,conversions,conversion_value\n"
            f"S1,10000,1000,3000,{s_conv},3000\nP1,10000,1000,3000,{p_conv},9000\n")


class ChannelComparison(Base):
    def test_mature_both_sides_gated_is_info_only(self):
        body = self.make({"campaign_metrics.csv": _metrics(30, 100)})
        self.assertIn("channel_outcome_difference", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Warning") + self.keys(body, "Critical"), [])

    def test_one_side_below_min_conversions_withholds_comparison(self):
        body = self.make({"campaign_metrics.csv": _metrics(5, 100)})
        self.assertNotIn("channel_outcome_difference", self.keys(body))

    def test_immature_window_is_partial_without_finding(self):
        body = self.make({"campaign_metrics.csv": _metrics(30, 100)}, snap="2026-08-31")
        self.assertNotIn("channel_outcome_difference", self.keys(body))
        self.assertEqual(self.cov(body, "channel_comparison")["status"], "partial")

    def test_zero_conversions_do_not_divide(self):
        body = self.make({"campaign_metrics.csv": _metrics(0, 0)})
        self.assertNotIn("channel_outcome_difference", self.keys(body))

    def test_missing_pmax_query_evidence_skips_overlap(self):
        body = self.make({"campaign_metrics.csv": _metrics(30, 100)})
        self.assertEqual(self.cov(body, "query_overlap")["status"], "skipped")
        self.assertEqual(self.cov(body, "causal_evaluation")["status"], "skipped")

    def test_no_concurrent_channels_not_applicable(self):
        tmp_files = {"campaign_metrics.csv": _metrics(30, 100)}
        body = self.make(tmp_files)
        self.assertNotEqual(self.cov(body, "scope_declaration")["status"], "not_applicable")
        (self.exp / "campaigns.csv").write_text("id,name,status,channel_type\nS1,Search,ENABLED,SEARCH\n")
        body = cli.run_once(M.SKILL, M.VERSION, M.run, self.exp, self.prof).finish()
        self.assertEqual(self.cov(body, "scope_declaration")["status"], "not_applicable")
        self.assertEqual(body["findings"], [])


QUERIES = ("campaign_id,date,query_text,reported_query_or_category_type,impressions,clicks,cost,conversions\n"
           "P1,2026-08-10,acme drill,query,500,50,40,4\n"
           "P1,2026-08-10,cordless drill,query,800,60,70,2\n"
           "P1,2026-08-10,acme,category,900,90,50,5\n")
SEARCH_TERMS = "search_term,campaign_id,ad_group_id,impressions,clicks,cost,conversions\ncordless drill,S1,G1,300,30,20,1\n"


class QueryOverlap(Base):
    def test_documented_nonbrand_policy_with_served_brand_query_is_warning(self):
        prof = {"brand_terms": ["acme"], "campaign_objectives": {"P1": {"brand_policy": "nonbrand_only"}}}
        body = self.make({"campaign_metrics.csv": _metrics(30, 100), "custom/search_pmax_queries.csv": QUERIES,
                          "search_terms.csv": SEARCH_TERMS}, prof)
        self.assertIn("brand_intent_control_mismatch", self.keys(body, "Warning"))
        self.assertIn("observed_query_overlap", self.keys(body, "Info"))

    def test_mixed_policy_brand_traffic_is_not_a_mismatch(self):
        prof = {"brand_terms": ["acme"], "campaign_objectives": {"P1": {"brand_policy": "mixed"}}}
        body = self.make({"campaign_metrics.csv": _metrics(30, 100), "custom/search_pmax_queries.csv": QUERIES,
                          "search_terms.csv": SEARCH_TERMS}, prof)
        self.assertNotIn("brand_intent_control_mismatch", self.keys(body))
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "brand_intent_control_mismatch"], [])

    def test_category_rows_are_not_literal_brand_queries(self):
        prof = {"brand_terms": ["acme"], "campaign_objectives": {"P1": {"brand_policy": "nonbrand_only"}}}
        q = QUERIES.replace("P1,2026-08-10,acme drill,query,500,50,40,4\n", "")
        body = self.make({"campaign_metrics.csv": _metrics(30, 100), "custom/search_pmax_queries.csv": q}, prof)
        self.assertNotIn("brand_intent_control_mismatch", self.keys(body))


class BrandExclusions(Base):
    HDR = "campaign_id,channel,brand_exclusions,effective_from,effective_to\n"

    def test_blank_cell_is_unknown_not_absent(self):
        body = self.make({"external/search_pmax_controls.csv": self.HDR + "P1,PERFORMANCE_MAX,,2026-01-01,\n"})
        self.assertNotIn("pmax_brand_exclusions_absent", self.keys(body))
        self.assertEqual(self.cov(body, "brand_exclusion_state")["status"], "partial")

    def test_known_empty_exclusions_are_info(self):
        body = self.make({"external/search_pmax_controls.csv": self.HDR + "P1,PERFORMANCE_MAX,none,2026-01-01,\n"})
        self.assertEqual(self.keys(body), ["pmax_brand_exclusions_absent"])
        self.assertEqual(body["findings"][0]["severity"], "Info")


def _daily(intervention: date, n: int, s_pre_cost, s_post_cost):
    lines = ["campaign_id,date,goal_set_id,impressions,clicks,cost,conversions"]
    for i in range(-n, n):
        d = intervention + timedelta(days=i)
        s_cost = s_pre_cost if i < 0 else s_post_cost
        lines.append(f"S1,{d},purchase,1000,20,{s_cost},2")
        lines.append(f"P1,{d},purchase,1000,20,30,2")
    return "\n".join(lines) + "\n"


class PeriodShift(Base):
    def test_equal_mature_periods_produce_info_hypothesis(self):
        d = date(2026, 8, 16)
        prof = {"brand_terms": ["acme"], "overlap_intervention_date": str(d)}
        body = self.make({"custom/search_pmax_daily.csv": _daily(d, 14, 30, 45)}, prof)
        f = [x for x in body["findings"] if x["condition_key"] == "search_pmax_shift_hypothesis"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "Info")
        self.assertAlmostEqual(f[0]["calculation"]["changes"]["SEARCH"]["cpa_relative_change"], 0.5)
        self.assertTrue(any(r["condition_key"] == "holdout_design" for r in body["ai_review"]))

    def test_post_window_never_includes_immature_days(self):
        d = date(2026, 8, 25)  # snapshot 09-06, lag 2 → mature through 09-04; data ends 09-07
        prof = {"brand_terms": ["acme"], "overlap_intervention_date": str(d)}
        body = self.make({"custom/search_pmax_daily.csv": _daily(d, 14, 30, 45)}, prof)
        f = [x for x in body["findings"] if x["condition_key"] == "search_pmax_shift_hypothesis"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["calculation"]["post_window"], ["2026-08-25", "2026-09-04"])
        self.assertEqual(f[0]["calculation"]["pre_window"], ["2026-08-14", "2026-08-24"])

    def test_ambiguous_intervention_is_partial(self):
        d = date(2026, 8, 16)
        ctl = ("campaign_id,channel,brand_exclusions,effective_from,effective_to,change_date\n"
               "P1,PERFORMANCE_MAX,x,2026-01-01,,2026-08-10\nP1,PERFORMANCE_MAX,x,2026-01-01,,2026-08-16\n")
        body = self.make({"custom/search_pmax_daily.csv": _daily(d, 14, 30, 45),
                          "external/search_pmax_controls.csv": ctl})
        self.assertNotIn("search_pmax_shift_hypothesis", self.keys(body))
        self.assertEqual(self.cov(body, "period_shift")["status"], "partial")


class Finalize(Base):
    def test_holdout_proposal_must_be_complete(self):
        self.make({"campaign_metrics.csv": _metrics(30, 100)})
        out = self.root / "out"
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(out)]
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        rid = next(r["id"] for r in json.loads((out / "result.json").read_text())["ai_review"]
                   if r["condition_key"] == "holdout_design")
        dec = self.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "propose_holdout", "rationale": "hypothesis",
                                    "proposal": {"randomized_unit": "geo"}}]))
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)]), 4)
        full = {k: "x" for k in M.HOLDOUT_FIELDS}
        dec.write_text(json.dumps([{"id": rid, "outcome": "propose_holdout", "rationale": "hypothesis",
                                    "proposal": full}]))
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)]), 0)


if __name__ == "__main__":
    unittest.main()
