"""test_check.py — Decision-boundary tests for skill-121 impression-share loss screening.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-121-impression-share-loss-analysis/tests -t skills/skill-121-impression-share-loss-analysis
rules:   Temp folders only; pins severities, gates and weighting math, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_121", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402  (path set by the check bootstrap)

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-04,2026-09-02,2026-09-06,fraction,currency,interaction_date,{lag}\n")
CAMPS = "id,name,status,channel_type,target_cpa,target_roas\n"
METRICS = ("campaign_id,impressions,clicks,cost,conversions,conversion_value,search_impression_share,"
           "search_budget_lost_is,search_rank_lost_is\n")


def run(files: dict, lag: str = "2", profile: str = "") -> dict:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "export"
    files = {"account.csv": ACCOUNT.format(lag=lag), **files}
    manifest = ["filename,completeness"]
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        manifest.append(f"{name},complete")
    (root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
    prof = Path(tmp.name) / "profile.yaml"
    prof.write_text(profile or "slug: t\n")
    try:
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, prof).finish()
    finally:
        tmp.cleanup()


def found(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)["status"]


class BudgetLost(unittest.TestCase):
    def body(self, cpa_target="40", conv="70", impr="85000", lag="2", bl="0.25"):
        return run({"campaigns.csv": CAMPS + f"10,G,ENABLED,SEARCH,{cpa_target},\n",
                    "campaign_metrics.csv": METRICS + f"10,{impr},3400,2720,{conv},5600,0.6,{bl},0.15\n"}, lag=lag)

    def test_goal_aligned_budget_loss_is_warning(self):
        f = found(self.body(), "budget_lost_is_constraint")
        self.assertEqual([x["severity"] for x in f], ["Warning"])

    def test_cpa_above_target_stays_info(self):
        # CPA 38.86 > target 30: constraint reported, no budget-increase case
        f = found(self.body(cpa_target="30"), "budget_lost_is_constraint")
        self.assertEqual([x["severity"] for x in f], ["Info"])

    def test_no_target_is_info(self):
        f = found(self.body(cpa_target=""), "budget_lost_is_constraint")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertIsNone(f[0]["evidence"]["economics"]["aligned"])

    def test_unknown_lag_blocks_warning(self):
        body = self.body(lag="")
        self.assertEqual([x["severity"] for x in found(body, "budget_lost_is_constraint")], ["Info"])
        self.assertEqual(cov(body, "economics"), "partial")

    def test_low_conversion_sample_blocks_warning(self):
        f = found(self.body(conv="10"), "budget_lost_is_constraint")
        self.assertEqual([x["severity"] for x in f], ["Info"])

    def test_screen_is_strict_at_20_percent(self):
        self.assertEqual(found(self.body(bl="0.20"), "budget_lost_is_constraint"), [])


class RankLost(unittest.TestCase):
    def body(self, rl, impr="30000"):
        return run({"campaigns.csv": CAMPS + "10,R,ENABLED,SEARCH,55,\n20,S,ENABLED,SHOPPING,,4\n",
                    "campaign_metrics.csv": METRICS + f"10,{impr},900,990,21,2100,0.57,0.08,{rl}\n"
                                                      "20,60000,1500,1050,45,5850,0.48,0.12,0.40\n"})

    def test_boundary_and_sample(self):
        self.assertEqual(found(self.body("0.30"), "rank_lost_is_constraint"), [])
        self.assertEqual([f["severity"] for f in found(self.body("0.31"), "rank_lost_is_constraint")], ["Warning"])
        self.assertEqual([f["severity"] for f in found(self.body("0.35", impr="900"), "rank_lost_is_constraint")], ["Info"])

    def test_non_search_campaign_never_screened(self):
        body = self.body("0.10")
        self.assertFalse([f for f in body["findings"] if f["entity"].get("campaign_id") == "20"])


class Censoring(unittest.TestCase):
    def test_censored_share_is_unknown_not_zero(self):
        body = run({"campaigns.csv": CAMPS + "10,G,ENABLED,SEARCH,40,\n",
                    "campaign_metrics.csv": METRICS + "10,85000,3400,2720,70,5600,< 10%,--,0.10\n"})
        self.assertEqual([f["severity"] for f in found(body, "is_censored_or_unavailable")], ["Info"])
        self.assertEqual(found(body, "budget_lost_is_constraint"), [])
        est = [o for o in body["observations"] if o["check"] == "eligible_estimate"]
        self.assertIsNone(est[0]["data"]["eligible_impressions_estimate"])

    def test_multi_row_campaign_uses_eligible_weights(self):
        # eligible 1000 (bl .05) + 2000 (bl .30) → weighted .2167 > .20; a row average (.175) would miss it
        body = run({"campaigns.csv": CAMPS + "10,G,ENABLED,SEARCH,40,\n",
                    "campaign_metrics.csv": METRICS + "10,900,50,40,5,100,0.9,0.05,0.05\n"
                                                      "10,1000,50,40,5,100,0.5,0.30,0.20\n"})
        f = found(body, "budget_lost_is_constraint")
        self.assertEqual(len(f), 1)
        self.assertAlmostEqual(f[0]["evidence"]["budget_lost_is"], 0.216667, places=5)

    def test_missing_metrics_skip_not_pass(self):
        body = run({"campaigns.csv": CAMPS + "10,G,ENABLED,SEARCH,40,\n"})
        self.assertEqual(cov(body, "share_units"), "skipped")
        self.assertEqual(cov(body, "loss_screen"), "skipped")
        self.assertEqual(body["findings"], [])


class Saturation(unittest.TestCase):
    def test_shared_budget_counted_once_per_day(self):
        daily = "campaign_id,date,budget_id,cost,historical_budget_amount\n"
        daily += "10,2026-09-01,B,60,100\n11,2026-09-01,B,60,100\n10,2026-09-02,B,30,100\n11,2026-09-02,B,30,100\n"
        body = run({"campaigns.csv": CAMPS + "10,G,ENABLED,SEARCH,40,\n11,H,ENABLED,SEARCH,40,\n",
                    "campaign_metrics.csv": METRICS + "10,85000,3400,2720,70,5600,0.6,0.25,0.15\n"
                                                      "11,5000,100,100,5,100,0.9,0.05,0.05\n",
                    "custom/is_daily.csv": daily})
        obs = {o["data"]["campaign_id"]: o["data"] for o in body["observations"] if o["check"] == "daily_saturation"}
        self.assertEqual(obs["10"]["saturated_days"], 1)  # 60+60 >= 100 on 09-01; 30+30 < 100 on 09-02
        self.assertEqual(obs["10"]["complete_days"], 2)
        self.assertEqual(cov(body, "daily_saturation"), "partial")  # < 8 complete weeks
        warn = found(body, "budget_lost_is_constraint")[0]
        self.assertEqual(warn["evidence"]["daily_saturation"]["saturated_days"], 1)


if __name__ == "__main__":
    unittest.main()
