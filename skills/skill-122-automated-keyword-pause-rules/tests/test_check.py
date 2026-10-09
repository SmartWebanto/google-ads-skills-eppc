"""test_check.py — Decision-boundary tests for skill-122 zero-conversion keyword screening.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-122-automated-keyword-pause-rules/tests -t skills/skill-122-automated-keyword-pause-rules
rules:   Temp folders only; pins gates, exclusions and floors, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_122", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-04,2026-09-02,{snap},fraction,currency,interaction_date,2\n")
CAMPS = "id,name,status,channel_type,target_cpa\n10,G,ENABLED,SEARCH,\n11,H,ENABLED,SEARCH,80\n"
KW = ("id,campaign_id,ad_group_id,text,match_type,status\n"
      "K1,10,G1,garden hose,BROAD,ENABLED\nK2,10,G1,acme hose,PHRASE,ENABLED\nK3,10,G1,step ladder,BROAD,ENABLED\n"
      "K4,11,G2,paint roller,BROAD,ENABLED\nK5,10,G1,tool chest,BROAD,ENABLED\nK9,10,G1,workbench,BROAD,ENABLED\n")
KM = ("keyword_id,campaign_id,ad_group_id,impressions,clicks,cost,conversions\n"
      "K1,10,G1,500,15,110,0\nK2,10,G1,500,15,120,0\nK3,10,G1,500,15,49.99,0\nK4,11,G2,500,15,70,0\n"
      "K5,10,G1,500,15,90,\nK9,10,G1,500,15,95,0\n")
CA = "id,name,category,status,last_conversion_date\n5001,Purchase,PURCHASE,ENABLED,2026-09-01\n"
POLICY = ("rule_id,campaign_id,objective,approved_lookback_days,lag_buffer_days,minimum_active_age_days,"
          "strategic_keyword_ids,brand_terms,target_cpa,owner,approval_status,review_cadence,rule_cap\n"
          "R1,*,sales,{look},3,14,K9,,,ops lead,approved for review,weekly,5\n")
PROFILE = "slug: t\nbrand_terms: [acme]\ncampaign_objectives:\n  10: {goal_ids: [5001]}\n  11: {goal_ids: [5001]}\n"


def run(snap="2026-09-06", look="30", policy=True, lifecycle=None, profile=PROFILE, ca=CA) -> dict:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "export"
    files = {"account.csv": ACCOUNT.format(snap=snap), "campaigns.csv": CAMPS, "keywords.csv": KW,
             "keyword_metrics.csv": KM, "conversion_actions.csv": ca}
    if policy:
        files["external/keyword_rule_policy.csv"] = POLICY.format(look=look)
    if lifecycle:
        files["custom/keyword_lifecycle.csv"] = lifecycle
    manifest = ["filename,completeness"]
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        manifest.append(f"{name},complete")
    (root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
    prof = Path(tmp.name) / "profile.yaml"
    prof.write_text(profile)
    try:
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, prof).finish()
    finally:
        tmp.cleanup()


def kids(items, key):
    return sorted(x["entity"]["keyword_id"] for x in items if x["condition_key"] == key)


class Screen(unittest.TestCase):
    def test_all_gates_pass_offers_warning_review_only_for_eligible(self):
        body = run()
        self.assertEqual(kids(body["ai_review"], "zero_conversion_candidate"), ["K1"])
        review = body["ai_review"][0]
        self.assertEqual(review["outcomes"]["unexplained_zero_conversion"]["severity"], "Warning")
        self.assertEqual(kids(body["findings"], "zero_conversion_candidate"), ["K1"])
        self.assertFalse([f for f in body["findings"] if f["severity"] != "Info"])

    def test_brand_strategic_subfloor_unknown_and_campaign_floor_excluded(self):
        body = run()
        flagged = {f["entity"]["keyword_id"] for f in body["findings"]}
        # K2 brand, K9 strategic, K3 below 50, K5 unknown conversions, K4 below campaign floor 80 (target CPA)
        self.assertEqual(flagged & {"K2", "K9", "K3", "K5", "K4"}, set())

    def test_missing_policy_blocks_warning_path(self):
        body = run(policy=False)
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(kids(body["findings"], "zero_conversion_candidate_gated"), ["K1", "K9"])
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "rule_draft")["status"], "skipped")

    def test_immature_window_blocks_warning_path(self):
        body = run(snap="2026-09-03")
        self.assertEqual(body["ai_review"], [])
        gated = [f for f in body["findings"] if f["condition_key"] == "zero_conversion_candidate_gated"]
        self.assertFalse(gated[0]["evidence"]["gates"]["mature"])

    def test_lookback_mismatch_blocks_warning_path(self):
        body = run(look="28")
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(kids(body["findings"], "zero_conversion_candidate_gated"), ["K1"])

    def test_unverified_tracking_blocks_warning_path(self):
        stale = "id,name,category,status,last_conversion_date\n5001,Purchase,PURCHASE,ENABLED,2026-07-01\n"
        body = run(ca=stale)
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(kids(body["findings"], "zero_conversion_candidate_gated"), ["K1"])

    def test_lifecycle_age_and_incidents(self):
        life = ("campaign_id,ad_group_id,keyword_id,created_at,last_enabled_at,last_material_change_at,"
                "tracking_incident_dates,source\n"
                "10,G1,K1,2026-08-25,,,,ads history\n")
        body = run(lifecycle=life)
        self.assertEqual(kids(body["findings"], "zero_conversion_candidate"), [])  # 8d old < 14d minimum
        life = life.replace("2026-08-25,,,", "2026-01-01,,,2026-08-20")
        body = run(lifecycle=life)
        self.assertEqual(kids(body["findings"], "zero_conversion_candidate_gated"), ["K1"])  # tracking incident

    def test_near_floor_needs_declared_ratio(self):
        self.assertEqual(kids(run()["findings"], "zero_conversion_near_floor"), [])
        body = run(profile=PROFILE + "keyword_pause_near_floor_ratio: 0.8\n")
        self.assertEqual(kids(body["findings"], "zero_conversion_near_floor"), ["K3", "K4"])


if __name__ == "__main__":
    unittest.main()
