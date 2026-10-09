"""test_check.py — skill-017 decision boundaries: literal direction, intent review, converting blocks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-017-negative-keyword-conflict-detection/tests -t skills/skill-017-negative-keyword-conflict-detection
rules:   Temp exports only; asserts entities/severities/coverage, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | pilot tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check017", HERE / "scripts" / "check.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

ACCOUNT = ("customer_id,currency_code,date_range_start,date_range_end,snapshot_date,conversion_lag_days\n"
           "1,EUR,2026-08-01,2026-08-30,2026-09-06,2\n")
BASE = {
    "account.csv": ACCOUNT,
    "ad_groups.csv": "id,campaign_id,status\nG,C,ENABLED\n",
    "keywords.csv": "id,campaign_id,ad_group_id,text,match_type,status\n"
                    "K1,C,G,red shoes,EXACT,ENABLED\nK2,C,G,buy red shoes,EXACT,ENABLED\n"
                    "K3,C,G,shoes red,PHRASE,ENABLED\nK4,C,G,buy red shoes,EXACT,PAUSED\n",
    "negative_keywords.csv": "text,match_type,level,campaign_id,ad_group_id\nbuy red shoes,PHRASE,campaign,C,\n",
    "shared_negative_lists.csv": "list_id,keywords,campaigns_applied\n",
}


def run(files: dict, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name, text in files.items():
        (root / "ex" / name).parent.mkdir(parents=True, exist_ok=True)
        (root / "ex" / name).write_text(text)
    args = ["--export", str(root / "ex"), "--out", str(root / "out")]
    M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
    body = json.loads((root / "out/result.json").read_text())
    if decisions is not None:
        dec = [{"id": decisions[0](body), "outcome": decisions[1], "rationale": "test",
                **({"proposal": decisions[2]} if len(decisions) > 2 else {})}]
        (root / "d.json").write_text(json.dumps(dec))
        code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(root / "d.json")])
        body = json.loads((root / "out/final.json").read_text())
        body["_code"] = code
    tmp.cleanup()
    return body


class Check017(unittest.TestCase):
    def test_only_contained_literal_text_is_blocked(self):
        b = run(BASE)
        blocked = {f["entity"]["keyword_id"] for f in b["findings"]}
        self.assertEqual(blocked, {"K2"})  # K1 shorter, K3 reordered, K4 paused
        self.assertEqual([f["severity"] for f in b["findings"]], ["Info"])

    def test_desired_block_becomes_warning_and_routing_clears_it(self):
        first = lambda b: b["ai_review"][0]["id"]
        self.assertEqual([f["severity"] for f in run(BASE, (first, "desired_blocked"))["findings"]], ["Warning"])
        self.assertEqual(run(BASE, (first, "intentional_routing"))["findings"], [])

    def test_critical_needs_evidence_reference(self):
        files = {**BASE, "custom/query_eligibility.csv":
                 "query,campaign_id,ad_group_id,diagnosis,intended_eligible,checked_at,evidence_ref,negative_id\n"
                 "buy red shoes,C,G,blocked by negative,true,2026-09-05,DIAG-1,N1\n"}
        pick = lambda b: next(r["id"] for r in b["ai_review"] if r["condition_key"] == "diagnosis_confirms_block")
        rejected = run(files, (pick, "material_impact_evidenced"))
        self.assertEqual(rejected["_code"], 4)
        ok = run(files, (pick, "material_impact_evidenced", {"evidence_ref": "DIAG-1"}))
        self.assertIn("Critical", {f["severity"] for f in ok["findings"]})

    def test_missing_negatives_skips_everything(self):
        files = {k: v for k, v in BASE.items() if k != "negative_keywords.csv"}
        b = run(files)
        self.assertEqual(b["findings"], [])
        self.assertTrue(all(c["status"] == "skipped" for c in b["coverage"]))

    def test_converting_query_needs_known_conversions(self):
        files = {**BASE, "search_terms.csv": "search_term,campaign_id,ad_group_id,clicks,conversions\n"
                                             "buy red shoes now,C,G,10,2\nbuy red shoes cheap,C,G,5,\n"}
        b = run(files)
        obs = [r for r in b["ai_review"] if r["condition_key"] == "negative_blocks_converting_query"]
        self.assertEqual([r["entity"]["search_term"] for r in obs], ["buy red shoes now"])
        cov = {c["check"]: c["status"] for c in b["coverage"]}
        self.assertEqual(cov["observed_query_blocks"], "partial")


if __name__ == "__main__":
    unittest.main()
