"""test_check.py — skill-014 boundaries: materiality, maturity/tracking gates, brand precedence, proposal verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-014-search-term-mining-negatives/tests -t skills/skill-014-search-term-mining-negatives
rules:   Temp exports only; asserts entities/severities/outcomes, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | pilot tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime_b | batch proposal structure and coverage regressions
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check014", HERE / "scripts" / "check.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def files(lag="2", action_last="2026-08-29"):
    return {
        "account.csv": "customer_id,currency_code,date_range_start,date_range_end,snapshot_date,conversion_lag_days\n"
                       f"1,EUR,2026-08-01,2026-08-30,2026-09-06,{lag}\n",
        "campaigns.csv": "id,target_cpa\nC,40\n",
        "ad_groups.csv": "id,campaign_id\nG,C\n",
        "keywords.csv": "id,campaign_id,ad_group_id,text,match_type,status\nK,C,G,cordless drill,PHRASE,ENABLED\n",
        "negative_keywords.csv": "text,match_type,level,campaign_id,ad_group_id\n",
        "shared_negative_lists.csv": "list_id,keywords,campaigns_applied\n",
        "conversion_actions.csv": f"id,name,status,last_conversion_date\nP,Purchase,ENABLED,{action_last}\n",
        "search_terms.csv": "search_term,campaign_id,ad_group_id,clicks,cost,conversions\n"
                            "free cordless drill,C,G,65,130,0\n"
                            "cordless drill jobs,C,G,18,27,0\n"
                            "acme cordless drill,C,G,40,80,0\n"
                            "best cordless drill,C,G,50,99,3\n",
    }


PROFILE = "brand_terms: [acme]\ncampaign_objectives:\n  C: {goal_ids: [P], target_cpa: 40}\n"


def run(fs, profile=PROFILE, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name, text in fs.items():
        (root / "ex" / name).parent.mkdir(parents=True, exist_ok=True)
        (root / "ex" / name).write_text(text)
    (root / "p.yaml").write_text(profile)
    args = ["--export", str(root / "ex"), "--profile", str(root / "p.yaml"), "--out", str(root / "out")]
    M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
    body = json.loads((root / "out/result.json").read_text())
    if decisions:
        dec = [d(body) for d in decisions]
        (root / "d.json").write_text(json.dumps(dec))
        body = {"_code": M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                    ["finalize", *args, "--decisions", str(root / "d.json")]),
                **json.loads((root / "out/final.json").read_text())}
    tmp.cleanup()
    return body


def review_for(term):
    return lambda b: next(r for r in b["ai_review"] if r["entity"].get("search_term") == term)


class Check014(unittest.TestCase):
    def test_material_zero_conversion_gets_warning_path_brand_is_protected(self):
        b = run(files())
        r = review_for("free cordless drill")(b)
        self.assertIn("irrelevant_zero_conversion", r["outcomes"])
        self.assertEqual({f["entity"]["search_term"] for f in b["findings"]}, {"free cordless drill"})
        terms = {x["entity"].get("search_term") for x in b["ai_review"]}
        self.assertNotIn("acme cordless drill", terms)  # brand precedence
        batch = next(x for x in b["ai_review"] if x["entity"].get("batch"))
        self.assertEqual([q["search_term"] for q in batch["evidence"]["queries"]], ["cordless drill jobs"])

    def test_unknown_lag_or_stale_tracking_disables_zero_conversion_path(self):
        for fs in (files(lag=""), files(action_last="2026-07-01")):
            b = run(fs)
            self.assertNotIn("irrelevant_zero_conversion", review_for("free cordless drill")(b)["outcomes"])
            self.assertEqual(b["findings"], [])

    def test_proposal_must_block_query_and_spare_protected_traffic(self):
        def dec(outcome, proposal):
            return lambda b: {"id": review_for("free cordless drill")(b)["id"], "outcome": outcome,
                              "rationale": "free requests excluded", "proposal": proposal}
        good = run(files(), decisions=[dec("business_excluded",
                                           {"negative": "free", "match_type": "PHRASE", "level": "campaign",
                                            "campaign_id": "C"})])
        self.assertEqual(good["_code"], 0)
        self.assertEqual([f["severity"] for f in good["findings"]], ["Warning"])
        for bad in ({"negative": "cordless drill", "match_type": "PHRASE", "level": "campaign", "campaign_id": "C"},
                    {"negative": "free", "match_type": "PHRASE", "level": "campaign", "campaign_id": "OTHER"},
                    {"negative": "gratis", "match_type": "PHRASE", "level": "campaign", "campaign_id": "C"}):
            self.assertEqual(run(files(), decisions=[dec("business_excluded", bad)])["_code"], 4, bad)

    def test_sub_floor_batch_needs_structured_queries_and_covering_negatives(self):
        batch = lambda b: next(x for x in b["ai_review"] if x["entity"].get("batch"))
        jobs = {"search_term": "cordless drill jobs", "campaign_id": "C", "ad_group_id": "G"}
        neg = {"negative": "jobs", "match_type": "PHRASE", "level": "campaign", "campaign_id": "C"}

        def dec(proposal):
            return lambda b: {"id": batch(b)["id"], "outcome": "some_excluded", "rationale": "employment", "proposal": proposal}
        self.assertEqual(run(files(), decisions=[dec({"queries": [jobs], "negatives": [neg]})])["_code"], 0)
        for bad in ({"queries": [jobs]},                                             # no negatives
                    {"queries": ["cordless drill jobs"], "negatives": [neg]},          # text-only reference
                    {"queries": [{**jobs, "campaign_id": "X"}], "negatives": [neg]},   # other campaign
                    {"queries": [jobs], "negatives": [{**neg, "negative": "careers"}]},  # does not cover the query
                    {"queries": [jobs], "negatives": [neg, {**neg, "negative": "cordless drill"}]}):  # collision
            self.assertEqual(run(files(), decisions=[dec(bad)])["_code"], 4, bad)

    def test_missing_search_terms_skips(self):
        fs = files()
        del fs["search_terms.csv"]
        b = run(fs)
        self.assertEqual({c["status"] for c in b["coverage"]}, {"skipped"})


if __name__ == "__main__":
    unittest.main()
