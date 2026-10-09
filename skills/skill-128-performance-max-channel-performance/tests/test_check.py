"""test_check.py — Decision-boundary tests for skill-128 PMax group/channel review.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-128-performance-max-channel-performance/tests -t skills/skill-128-performance-max-channel-performance
rules:   Temp folders only; pins left-join states, objective/sample/goal gates, channel exclusivity and comparison
alignment, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_128", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,2026-09-06,fraction,currency,interaction_date,2\n")
CAMPS = "id,name,status,channel_type,target_cpa\nP1,pmax,ENABLED,PERFORMANCE_MAX,20\nS1,search,ENABLED,SEARCH,\n"
CM = ("campaign_id,impressions,clicks,cost,conversions,conversion_value\n"
      "P1,90000,3000,3000,100,6000\nS1,20000,1000,1000,50,2000\n")
CA = "id,name,category,status,last_conversion_date\n5001,Purchase,PURCHASE,ENABLED,{last}\n"
PROFILE = ("slug: t\ncampaign_objectives:\n  P1: {goal_ids: [5001], role: acquisition, target_cpa: 20}\n"
           "  S1: {goal_ids: [5001], role: {srole}}\n")
GROUPS = ("campaign_id,asset_group_id,name,status,primary_status,platform_diagnostic,ad_strength,final_urls\n"
          "P1,G1,a,ENABLED,ELIGIBLE,,GOOD,u\nP1,G2,b,ENABLED,ELIGIBLE,,POOR,u\nP1,G3,c,PAUSED,PAUSED,,AVERAGE,u\n"
          "P1,G4,d,ENABLED,ELIGIBLE,,GOOD,u\nP1,G5,e,ENABLED,ELIGIBLE,,GOOD,u\n")


def group_daily(g1_conv=2, mixed=False) -> str:
    out = ["campaign_id,asset_group_id,date,goal_set_id,impressions,clicks,cost,conversions,conversion_value"]
    for i in range(30):
        d = date(2026, 8, 1) + timedelta(days=i)
        goal = "gs2" if mixed and i == 0 else "gs1"
        out += [f"P1,G1,{d},{goal},1000,40,50,{g1_conv},100", f"P1,G3,{d},gs1,0,0,0,0,0",
                f"P1,G4,{d},gs1,300,10,5,0,0", f"P1,G5,{d},gs1,300,10,10,{1 if i % 3 == 0 else 0},20"]
    return "\n".join(out) + "\n"


def run(files: dict, last_conv="2026-08-29", srole="acquisition", camps=CAMPS, profile=None) -> dict:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "export"
    files = {"account.csv": ACCOUNT, "campaigns.csv": camps, "campaign_metrics.csv": CM,
             "conversion_actions.csv": CA.format(last=last_conv), **files}
    manifest = ["filename,completeness"]
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        manifest.append(f"{name},complete")
    (root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
    prof = Path(tmp.name) / "profile.yaml"
    prof.write_text(profile or PROFILE.replace("{srole}", srole))
    try:
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, prof).finish()
    finally:
        tmp.cleanup()


def found(b, key):
    return sorted((f["severity"], f["entity"].get("group") or f["entity"].get("channel")) for f in b["findings"]
                  if f["condition_key"] == key)


class Groups(unittest.TestCase):
    def test_left_join_states(self):
        b = run({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": group_daily()})
        totals = next(o["data"] for o in b["observations"] if o["text"].startswith("Group inventory totals"))
        self.assertEqual((totals["reporting"], totals["zero_performance"], totals["unreported"]), (3, 1, 1))

    def test_objective_miss_needs_sample_and_single_goal(self):
        b = run({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": group_daily()})
        self.assertEqual(found(b, "group_objective_miss"), [("Warning", "G1")])  # CPA 25 > 20; G5 has 10 conv < 15
        b = run({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": group_daily(g1_conv=3)})
        self.assertEqual(found(b, "group_objective_miss"), [])  # CPA 16.67 <= 20
        b = run({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": group_daily(mixed=True)})
        self.assertEqual(found(b, "group_objective_miss"), [])  # mixed goal sets are not ranked

    def test_zero_conversion_spend_review_needs_tracking(self):
        b = run({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": group_daily()})
        self.assertEqual([(r["condition_key"], r["entity"]["group"]) for r in b["ai_review"]], [("zero_conversion_spend", "G4")])
        b = run({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": group_daily()}, last_conv="2026-07-01")
        self.assertEqual(b["ai_review"], [])
        self.assertEqual(found(b, "zero_conversion_spend_gated"), [("Info", "G4")])


CH_HDR = ("campaign_id,date,reported_channel,reported_format,goal_set_id,impressions,interactions,interaction_definition,"
          "clicks,cost,conversions,conversion_value,source_report_name,reporting_version,metric_availability\n")


def channels(shopping_recent=100.0, dup=False, total=False) -> str:
    out = []
    for i in range(30):
        d = date(2026, 8, 1) + timedelta(days=i)
        shop = shopping_recent if d > date(2026, 8, 23) else 100.0
        out.append(f"P1,{d},Shopping,product ads,gs1,1000,30,clicks,30,{shop},1,50,channel report,v1,available")
        out.append(f"P1,{d},Display,image,gs1,5000,5,clicks,5,0,0,0,channel report,v1,available")
    if dup:
        out.append(out[0])
    if total:
        out.append("P1,2026-08-01,Total,all,gs1,6000,35,clicks,35,100,1,50,channel report,v1,available")
    return CH_HDR + "\n".join(out) + "\n"


class Channels(unittest.TestCase):
    def test_duplicates_and_totals_are_not_summed(self):
        b = run({"custom/pmax_channels.csv": channels(dup=True, total=True)})
        obs = next(o["data"] for o in b["observations"] if o["text"].startswith("PMax campaign P1: reported channel"))
        self.assertEqual(obs["channel_cost"], 3000)
        self.assertEqual(obs["reported_coverage"], 1)
        self.assertEqual(next(c for c in b["coverage"] if c["check"] == "channel_reconciliation")["status"], "partial")

    def test_zero_conversion_channel_below_floor_and_objective_miss(self):
        b = run({"custom/pmax_channels.csv": channels()})
        self.assertEqual(found(b, "channel_objective_miss"), [("Warning", "shopping")])  # CPA 100 > 20, 30 mature conv
        self.assertEqual(b["ai_review"], [])  # Display 0 cost: no zero-conversion exposure

    def test_spend_drop_needs_declared_threshold(self):
        files = {"custom/pmax_channels.csv": channels(shopping_recent=40.0)}
        self.assertEqual(found(run(files), "channel_spend_drop"), [])
        prof = PROFILE.replace("{srole}", "acquisition") + "pmax_channel_drop_threshold: 0.5\n"
        self.assertEqual(found(run(files, profile=prof), "channel_spend_drop"), [("Info", "shopping")])


class Comparison(unittest.TestCase):
    SEG = ("campaign_id,date,goal_set_id,market,segment_definition,impressions,clicks,cost,conversions,conversion_value,coverage\n"
           "P1,2026-08,gs1,IT,nonbrand,1000,100,600,20,900,full\nS1,2026-08,gs1,IT,nonbrand,1000,100,400,20,800,full\n")

    def test_aligned_is_observation_unaligned_is_info(self):
        b = run({"custom/pmax_comparison_segments.csv": self.SEG})
        self.assertEqual(found(b, "pmax_search_unaligned_comparison"), [])
        self.assertTrue([o for o in b["observations"] if o["text"].startswith("Aligned PMax")])
        b = run({"custom/pmax_comparison_segments.csv": self.SEG}, srole="brand")
        self.assertEqual(len(found(b, "pmax_search_unaligned_comparison")), 1)

    def test_no_pmax_is_not_applicable(self):
        b = run({}, camps="id,name,status,channel_type,target_cpa\nS1,search,ENABLED,SEARCH,\n")
        self.assertEqual({c["status"] for c in b["coverage"]}, {"not_applicable"})


if __name__ == "__main__":
    unittest.main()
