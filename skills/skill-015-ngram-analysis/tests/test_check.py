"""test_check.py — Decision-boundary tests for skill-015 n-gram pattern analysis.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-015-ngram-analysis/tests
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
_spec = importlib.util.spec_from_file_location("check_015", SCRIPT)
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


def q(term, cost, conv, kid="K1"):
    return {"search_term": term, "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": kid,
            "match_type": "BROAD", "impressions": "100", "clicks": "10", "cost": str(cost), "conversions": str(conv)}


def tables(queries, snapshot="2026-09-06", last_conv="2026-08-29"):
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": "2"}],
        "campaigns": [{"id": "C1", "target_cpa": "40", "goal_ids": "purchase"}],
        "conversion_actions": [{"id": "purchase", "status": "ENABLED", "last_conversion_date": last_conv}],
        "ad_groups": [{"id": "G1", "campaign_id": "C1", "status": "ENABLED"}],
        "keywords": [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "cordless drill", "status": "ENABLED"}],
        "negative_keywords": (["text", "match_type", "level", "campaign_id", "ad_group_id"], []),
        "shared_negative_lists": (["list_id", "keywords", "campaigns_applied"], []),
        "search_terms": queries,
    }


class CheckTests(unittest.TestCase):
    def run_skill(self, t, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_export(self.root / "export", t)
        (self.root / "profile.json").write_text(json.dumps(profile or {"conversion_lag_days": 2, "brand_terms": ["acme"]}))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.root / "export", self.root / "profile.json").finish()

    @staticmethod
    def grams(body, key="zero_conversion_pattern"):
        return sorted(r["entity"]["ngram"] for r in body["ai_review"] if r["condition_key"] == key)

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_row_counts_once_per_ngram_even_with_repeated_tokens(self):
        body = self.run_skill(tables([q("drill drill", 60, 0)]))
        r = body["ai_review"][0]
        self.assertEqual((r["entity"]["ngram"], r["evidence"]["cost"]), ("drill", 60))  # not 120
        self.assertEqual(r["evidence"]["aliases"], ["drill drill"])

    def test_floor_maturity_and_tracking_gate_the_review(self):
        self.assertEqual(self.grams(self.run_skill(tables([q("free drill", 49, 0)]))), [])
        self.assertEqual(self.grams(self.run_skill(tables([q("free drill", 50, 0)]))), ["drill"])
        body = self.run_skill(tables([q("free drill", 80, 0)], snapshot="2026-08-31"))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.cov(body)["zero_conversion_patterns"], "partial")
        body = self.run_skill(tables([q("free drill", 80, 0)], last_conv="2026-06-01"))
        self.assertEqual(body["ai_review"], [])

    def test_brand_ngrams_are_never_candidates(self):
        self.assertEqual(self.grams(self.run_skill(tables([q("acme", 80, 0)]))), [])

    def test_union_exposure_is_not_summed_over_overlapping_ngrams(self):
        body = self.run_skill(tables([q("free drill", 60, 0), q("free saw", 70, 0), q("drill", 10, 1)]))
        self.assertEqual(self.grams(body), ["free", "free drill", "saw"])  # 'free saw' is an alias of 'saw'
        union = [o for o in body["observations"] if o["check"] == "exposure_union"][0]["data"]
        self.assertEqual((union["rows"], union["cost"]), (2, 130))

    def test_favorable_pattern_needs_sample_and_target(self):
        body = self.run_skill(tables([q("cordless drill", 450, 15)]))  # CPA 30 <= 40
        self.assertIn("favorable_pattern", [f["condition_key"] for f in body["findings"]])
        body = self.run_skill(tables([q("cordless drill", 700, 15)]))  # CPA 46.7 > 40
        self.assertNotIn("favorable_pattern", [f["condition_key"] for f in body["findings"]])
        body = self.run_skill(tables([q("cordless drill", 100, 14)]))
        self.assertNotIn("favorable_pattern", [f["condition_key"] for f in body["findings"]])

    def test_missing_queries_skip_every_step(self):
        t = tables([])
        del t["search_terms"]
        body = self.run_skill(t)
        self.assertTrue(all(s == "skipped" for c, s in self.cov(body).items() if c != "scope"))

    def test_finalize_rejects_negative_blocking_converting_query(self):
        body = self.run_skill(tables([q("free drill", 80, 0), q("cordless drill kit", 40, 2)]))
        rid = [r["id"] for r in body["ai_review"] if r["entity"]["ngram"] == "free"][0]
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            for neg, code in (("drill", 4), ("free", 0)):
                dec = self.root / "d.json"
                dec.write_text(json.dumps([{"id": rid, "outcome": "irrelevant_pattern", "rationale": "free requests",
                                            "proposal": {"negative": neg, "match_type": "PHRASE", "level": "campaign",
                                                         "campaign_id": "C1"}}]))
                self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                            ["finalize"] + args + ["--decisions", str(dec)]), code)


if __name__ == "__main__":
    unittest.main()
