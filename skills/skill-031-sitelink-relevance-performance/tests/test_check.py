"""test_check.py — Decision-boundary tests for skill-031 sitelink destination and CTR checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-031-sitelink-relevance-performance/tests -t skills/skill-031-sitelink-relevance-performance
rules:   Temp folders only; pins reproduction gate, eligibility gate, click-scope separation, maturity/sample
gates and quote verification, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial tests
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

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill031_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,{lag}\n")
SPINE = {
    "campaigns.csv": "id,status\nC1,ENABLED\nC2,PAUSED\n",
    "ad_groups.csv": "id,campaign_id,status\nG1,C1,ENABLED\n",
    "assets.csv": ("asset_id,type,association_level,campaign_id,ad_group_id,status,link_text,description1,description2,"
                   "final_url,approval_status\n"
                   "S1,SITELINK,CAMPAIGN,C1,,ENABLED,Drills Sale,20% off drills,,https://x.example/drills,APPROVED\n"
                   "S2,SITELINK,CAMPAIGN,C2,,ENABLED,Repairs,,,https://x.example/repair,APPROVED\n"
                   "S3,SITELINK,CAMPAIGN,C1,,ENABLED,Home,,,https://x.example/,APPROVED\n"),
}
DEST_HDR = ("asset_id,association_key,original_url,resolved_url,http_status,device,locale,check_at,page_title,"
            "visible_text,offer_terms,valid_from,valid_to,screenshot_or_snapshot_ref,source_ref\n")


def dest(asset, url, status, at, offer="", vfrom="", vto=""):
    return f"{asset},campaign:C1,{url},{url},{status},MOBILE,it-IT,{at},T,page text,{offer},{vfrom},{vto},shot,ref\n"


def run(test, files, lag=2, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    files = {"account.csv": ACCOUNT.format(lag=lag), **files}
    files["table_manifest.csv"] = "filename,completeness,truncation\n" + "".join(f"{n},complete,none\n" for n in list(files))
    for name, text in files.items():
        p = root / "export" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (root / "profile.json").write_text("{}")
    args = ["--export", str(root / "export"), "--profile", str(root / "profile.json"), "--out", str(root / "out")]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
    body = json.loads((root / "out" / "result.json").read_text())
    if decisions is None:
        return rc, body
    (root / "d.json").write_text(json.dumps(decisions(body)))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc2 = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(root / "d.json")])
    return rc2, json.loads((root / "out" / "final.json").read_text())


def found(body, key, sev=None):
    return sorted(f["entity"]["asset_id"] for f in body["findings"] if f["condition_key"] == key and sev in (None, f["severity"]))


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class Destinations(unittest.TestCase):
    def test_reproduced_error_on_eligible_sitelink_is_warning(self):
        d = DEST_HDR + dest("S1", "https://x.example/drills", 404, "2026-08-10") + \
            dest("S1", "https://x.example/drills", 404, "2026-08-20")
        _, b = run(self, {**SPINE, "external/sitelink_destinations.csv": d})
        self.assertEqual(found(b, "broken_destination", "Warning"), ["S1"])

    def test_single_failure_is_verification_request(self):
        d = DEST_HDR + dest("S1", "https://x.example/drills", 500, "2026-08-20")
        _, b = run(self, {**SPINE, "external/sitelink_destinations.csv": d})
        self.assertEqual(found(b, "broken_destination"), [])
        self.assertEqual(found(b, "destination_verification_request", "Info"), ["S1"])

    def test_later_success_clears_error(self):
        d = DEST_HDR + dest("S1", "https://x.example/drills", 404, "2026-08-10") + \
            dest("S1", "https://x.example/drills", 404, "2026-08-12") + dest("S1", "https://x.example/drills", 200, "2026-08-20")
        _, b = run(self, {**SPINE, "external/sitelink_destinations.csv": d})
        self.assertEqual(found(b, "broken_destination") + found(b, "destination_verification_request"), [])

    def test_paused_parent_or_unknown_status_never_warning(self):
        d = DEST_HDR + dest("S2", "https://x.example/repair", 404, "2026-08-10") + \
            dest("S2", "https://x.example/repair", 404, "2026-08-20") + \
            dest("S1", "https://x.example/drills", "", "2026-08-10") + dest("S1", "https://x.example/drills", "", "2026-08-20")
        _, b = run(self, {**SPINE, "external/sitelink_destinations.csv": d})
        self.assertEqual(found(b, "broken_destination"), [])
        self.assertEqual(found(b, "destination_verification_request"), ["S2"])

    def test_stale_or_missing_tests_are_info_not_defect(self):
        d = DEST_HDR + dest("S1", "https://x.example/drills", 404, "2026-06-01") + \
            dest("S1", "https://x.example/drills", 404, "2026-06-02")
        _, b = run(self, {**SPINE, "external/sitelink_destinations.csv": d})
        self.assertEqual(found(b, "broken_destination"), [])
        self.assertEqual(found(b, "destination_evidence_missing", "Info"), ["S1", "S3"])

    def test_homepage_is_info_only(self):
        _, b = run(self, SPINE)
        self.assertEqual(found(b, "homepage_destination", "Info"), ["S3"])
        self.assertEqual(cov(b)["destination_join"], "skipped")


class Offer(unittest.TestCase):
    D = DEST_HDR + dest("S1", "https://x.example/drills", 200, "2026-08-10", offer="10% off drills",
                        vfrom="2026-08-01", vto="2026-08-31")

    def decide(self, page_quote):
        def f(body):
            item = next(r for r in body["ai_review"] if r["condition_key"] == "wrong_offer")
            return [{"id": item["id"], "outcome": "wrong_offer", "rationale": "20 vs 10",
                     "proposal": {"sitelink_quote": "20% off drills", "page_quote": page_quote}}]
        return f

    def test_wrong_offer_needs_verbatim_page_quote(self):
        rc, final = run(self, {**SPINE, "external/sitelink_destinations.csv": self.D}, decisions=self.decide("50% off"))
        self.assertEqual(rc, 4)
        self.assertEqual(found(final, "wrong_offer"), [])
        rc, final = run(self, {**SPINE, "external/sitelink_destinations.csv": self.D}, decisions=self.decide("10% off drills"))
        self.assertEqual(rc, 0)
        self.assertEqual(found(final, "wrong_offer", "Warning"), ["S1"])

    def test_snapshot_without_validity_window_is_verification(self):
        d = DEST_HDR + dest("S1", "https://x.example/drills", 200, "2026-08-10", offer="10% off")
        _, b = run(self, {**SPINE, "external/sitelink_destinations.csv": d})
        self.assertEqual([r for r in b["ai_review"] if r["condition_key"] == "wrong_offer"], [])
        self.assertIn("S1", found(b, "offer_verification_needed", "Info"))


MET_HDR = "asset_id,association_key,date,segment,impressions,clicks,click_scope,conversions,cost,attribution_definition\n"


def met(asset, imp, clk, scope="asset-only", date="2026-08-10"):
    return f"{asset},campaign:C1,{date},MOBILE,{imp},{clk},{scope},1,5,asset\n"


class Ctr(unittest.TestCase):
    def reviews(self, b):
        return sorted(r["entity"]["asset_id"] for r in b["ai_review"] if r["condition_key"] == "low_contextual_ctr")

    def test_low_ctr_review_needs_mature_qualified_cohorts(self):
        m = MET_HDR + met("S1", 2000, 10) + met("S3", 3000, 90) + met("S1", 0, 500, scope="all-ad")
        _, b = run(self, {**SPINE, "custom/sitelink_metrics.csv": m})
        self.assertEqual(self.reviews(b), ["S1"])
        obs = [o for o in b["observations"] if o["check"] == "contextual_ctr" and o["data"]["asset_id"] == "S1"]
        self.assertEqual(obs[0]["data"]["asset_clicks"], 10)  # all-ad clicks kept separate
        self.assertEqual(obs[0]["data"]["all_ad_clicks_separate"], 500)

    def test_small_cohort_or_immature_window_blocks_review(self):
        m = MET_HDR + met("S1", 900, 1) + met("S3", 3000, 90)
        _, b = run(self, {**SPINE, "custom/sitelink_metrics.csv": m})
        self.assertEqual(self.reviews(b), [])
        m = MET_HDR + met("S1", 2000, 10) + met("S3", 3000, 90)
        _, b = run(self, {**SPINE, "custom/sitelink_metrics.csv": m}, lag=30)
        self.assertEqual(self.reviews(b), [])
        self.assertEqual(cov(b)["mature_comparison"], "partial")

    def test_zero_impressions_undefined_and_metrics_run_without_assets(self):
        m = MET_HDR + met("S1", 0, 0) + met("S3", 3000, 90)
        rc, b = run(self, {"custom/sitelink_metrics.csv": m})
        self.assertEqual(rc, 0)
        obs = [o for o in b["observations"] if o["check"] == "contextual_ctr" and o["data"]["asset_id"] == "S1"]
        self.assertIsNone(obs[0]["data"]["ctr"])
        self.assertEqual(cov(b)["association_spine"], "skipped")
        self.assertEqual(cov(b)["contextual_ctr"], "completed")


if __name__ == "__main__":
    unittest.main()
