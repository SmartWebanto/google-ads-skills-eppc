"""test_check.py — Decision-boundary tests for skill-013 search-term keyword mining.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-013-search-term-mining-keywords/tests
rules:   Temp folders only; stdlib only; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial tests
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
_spec = importlib.util.spec_from_file_location("check_013", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)


def write_export(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        cols, rows = rows if isinstance(rows, tuple) else (list(dict.fromkeys(k for r in rows for k in r)), rows)
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def q(term, clicks, cost, conv, kid="K1"):
    return {"search_term": term, "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": kid,
            "match_type": "BROAD", "added_excluded": "NONE", "impressions": "1000", "clicks": str(clicks),
            "cost": str(cost), "conversions": str(conv)}


def tables(queries, negatives=()):
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}],
        "campaigns": [{"id": "C1", "bidding_strategy_type": "TARGET_CPA", "target_cpa": "40", "goal_ids": "purchase"}],
        "conversion_actions": [{"id": "purchase", "status": "ENABLED", "last_conversion_date": "2026-08-29"}],
        "ad_groups": [{"id": "G1", "campaign_id": "C1", "status": "ENABLED"}],
        "keywords": [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "drill", "match_type": "BROAD",
                      "status": "ENABLED"}],
        "negative_keywords": (["text", "match_type", "level", "campaign_id", "ad_group_id"],
                              [{"text": t, "match_type": m, "level": "campaign", "campaign_id": "C1", "ad_group_id": ""}
                               for t, m in negatives]),
        "shared_negative_lists": (["list_id", "keywords", "campaigns_applied"], []),
        "search_terms": queries,
    }


class CheckTests(unittest.TestCase):
    def run_skill(self, t):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_export(self.root / "export", t)
        (self.root / "profile.json").write_text(json.dumps({"conversion_lag_days": 2}))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.root / "export", self.root / "profile.json").finish()

    @staticmethod
    def cands(body):
        return sorted(r["entity"]["normalized_query"] for r in body["ai_review"])

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_candidates_are_uncovered_converting_or_high_volume(self):
        body = self.run_skill(tables([q("drill", 50, 50, 3), q("cordless drill", 20, 30, 1),
                                      q("drill bits", 150, 60, 0), q("drill press", 20, 20, 0)]))
        self.assertEqual(self.cands(body), ["cordless drill", "drill bits"])  # 'drill' covered; 'drill press' low volume
        self.assertTrue(all(f["severity"] == "Info" for f in body["findings"]))

    def test_add_outcome_only_with_favorable_mature_gated_cpa(self):
        body = self.run_skill(tables([q("cordless drill", 200, 600, 20)]))  # CPA 30 <= 40, 20 >= 15
        self.assertIn("add_for_documented_control", body["ai_review"][0]["outcomes"])
        body = self.run_skill(tables([q("cordless drill", 200, 1000, 20)]))  # CPA 50 > 40
        self.assertNotIn("add_for_documented_control", body["ai_review"][0]["outcomes"])
        body = self.run_skill(tables([q("cordless drill", 200, 100, 5)]))  # below min_conversions
        self.assertNotIn("add_for_documented_control", body["ai_review"][0]["outcomes"])

    def test_identical_duplicate_rows_are_counted_once(self):
        body = self.run_skill(tables([q("cordless drill", 20, 30, 1), q("cordless drill", 20, 30, 1)]))
        self.assertEqual(body["ai_review"][0]["evidence"]["clicks"], 20)

    def test_missing_inventory_is_skipped_not_passed(self):
        t = tables([q("cordless drill", 20, 30, 1)])
        del t["keywords"]
        body = self.run_skill(t)
        self.assertEqual(self.cov(body)["relevance_review"], "skipped")
        self.assertEqual(body["ai_review"], [])
        t = tables([])
        del t["search_terms"]
        body = self.run_skill(t)
        self.assertEqual(self.cov(body)["query_aggregation"], "skipped")
        self.assertEqual(self.cov(body)["negative_conflicts"], "skipped")

    def test_finalize_verifies_keyword_proposal(self):
        body = self.run_skill(tables([q("cordless drill", 200, 600, 20)], negatives=[("cordless", "PHRASE")]))
        self.assertTrue(body["ai_review"][0]["evidence"]["blocked_by_current_negatives"])
        rid = body["ai_review"][0]["id"]
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            dec = self.root / "d.json"
            prop = {"keyword": "cordless drill", "match_type": "EXACT", "campaign_id": "C1", "ad_group_id": "G1",
                    "control_need": "landing alignment"}
            dec.write_text(json.dumps([{"id": rid, "outcome": "add_for_documented_control", "rationale": "r",
                                        "proposal": prop}]))
            self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                        ["finalize"] + args + ["--decisions", str(dec)]), 4)  # blocked by negative
        body = self.run_skill(tables([q("cordless drill", 200, 600, 20)]))
        rid = body["ai_review"][0]["id"]
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            for kw, code in (("drill set", 4), ("cordless drill", 0)):
                dec = self.root / "d.json"
                dec.write_text(json.dumps([{"id": rid, "outcome": "add_for_documented_control", "rationale": "r",
                                            "proposal": dict(prop, keyword=kw)}]))
                self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                            ["finalize"] + args + ["--decisions", str(dec)]), code)


if __name__ == "__main__":
    unittest.main()
