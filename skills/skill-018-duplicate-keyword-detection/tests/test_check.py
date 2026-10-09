"""test_check.py — Decision-boundary tests for skill-018 duplicate keywords and query routing.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-018-duplicate-keyword-detection/tests
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
_spec = importlib.util.spec_from_file_location("check_018", SCRIPT)
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


def kw(kid, gid, text, match="EXACT", cid="C1"):
    return {"id": kid, "campaign_id": cid, "ad_group_id": gid, "text": text, "match_type": match, "status": "ENABLED",
            "quality_score": "5", "final_url": "https://x.example/"}


def st(term, gid, kid, conv=1, cid="C1"):
    return {"search_term": term, "campaign_id": cid, "ad_group_id": gid, "matched_keyword_id": kid, "clicks": "10",
            "cost": "20", "conversions": str(conv)}


def tables(keywords, queries=(), geo2="Italy"):
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}],
        "campaigns": [{"id": "C1", "geo_targets": "Italy", "languages": "it", "ad_schedule": "none",
                       "bidding_strategy_type": "TARGET_CPA"},
                      {"id": "C2", "geo_targets": geo2, "languages": "it", "ad_schedule": "none",
                       "bidding_strategy_type": "TARGET_CPA"}],
        "ad_groups": [{"id": g, "campaign_id": c, "status": "ENABLED"} for g, c in (("G1", "C1"), ("G2", "C1"), ("G3", "C2"))],
        "keywords": keywords,
        "negative_keywords": (["text", "match_type", "level", "campaign_id", "ad_group_id"], []),
        "shared_negative_lists": (["list_id", "keywords", "campaigns_applied"], []),
        "audiences": (["id", "campaign_id"], []),
        "bid_adjustments": (["id", "campaign_id"], []),
        "search_terms": list(queries) or (["search_term", "campaign_id", "ad_group_id", "matched_keyword_id", "clicks",
                                           "cost", "conversions"], []),
    }


class CheckTests(unittest.TestCase):
    def run_skill(self, t, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_export(self.root / "export", t)
        (self.root / "profile.json").write_text(json.dumps(profile or {"conversion_lag_days": 2}))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.root / "export", self.root / "profile.json").finish()

    @staticmethod
    def found(body):
        return sorted((f["condition_key"], f["severity"]) for f in body["findings"])

    @staticmethod
    def reviews(body):
        return sorted(r["condition_key"] for r in body["ai_review"])

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_exact_duplicates_vs_match_type_variants(self):
        body = self.run_skill(tables([kw("K1", "G1", "Drill"), kw("K2", "G2", "drill")]))
        self.assertEqual(self.found(body), [("duplicate_keyword_set", "Info")])
        body = self.run_skill(tables([kw("K1", "G1", "drill"), kw("K2", "G2", "drill", "PHRASE")]))
        self.assertEqual(self.found(body), [])

    def test_identical_context_goes_to_consolidation_review_only(self):
        body = self.run_skill(tables([kw("K1", "G1", "drill"), kw("K2", "G3", "drill", cid="C2")]))
        self.assertEqual(self.reviews(body), ["duplicate_control_burden"])
        body = self.run_skill(tables([kw("K1", "G1", "drill"), kw("K2", "G3", "drill", cid="C2")], geo2="Spain"))
        self.assertEqual(self.reviews(body), [])  # deliberate regional copy candidate
        self.assertEqual(self.found(body), [("duplicate_keyword_set", "Info")])

    def test_owner_exception_suppresses_set(self):
        body = self.run_skill(tables([kw("K1", "G1", "drill"), kw("K2", "G2", "drill")]),
                              {"duplicate_keyword_exceptions": ["K1", "K2"]})
        self.assertEqual(self.found(body), [])

    def test_multi_trigger_and_routing_contradiction(self):
        kws = [kw("K1", "G1", "drill", "PHRASE"), kw("K3", "G3", "drill", "BROAD", cid="C2")]
        qs = [st("cordless drill", "G1", "K1"), st("cordless drill", "G3", "K3", cid="C2")]
        body = self.run_skill(tables(kws, qs))
        self.assertIn(("multi_trigger_query", "Info"), self.found(body))
        self.assertEqual(self.reviews(body), [])
        body = self.run_skill(tables(kws, qs), {"intended_routing": {"cordless drill": {"campaign_id": "C1",
                                                                                         "ad_group_id": "G1"}}})
        self.assertEqual(self.reviews(body), ["routing_contradiction"])
        body = self.run_skill(tables(kws, qs[:1]), {"intended_routing": {"cordless drill": {"campaign_id": "C1"}}})
        self.assertEqual(self.reviews(body), [])

    def test_missing_trigger_ids_and_inventory(self):
        qs = [{k: v for k, v in st("drill", "G1", "K1").items() if k != "matched_keyword_id"}]
        body = self.run_skill(tables([kw("K1", "G1", "drill")], qs))
        self.assertEqual(self.cov(body)["multi_trigger_map"], "partial")
        t = tables([])
        del t["keywords"]
        body = self.run_skill(t)
        self.assertEqual(self.cov(body)["duplicate_sets"], "skipped")

    def _finalize(self, rid, outcome, proposal):
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        dec = self.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "r", "proposal": proposal}]))
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)])

    def test_finalize_verifies_requirement_and_cross_negatives(self):
        body = self.run_skill(tables([kw("K1", "G1", "drill"), kw("K2", "G3", "drill", cid="C2")]))
        rid = body["ai_review"][0]["id"]
        self.assertEqual(self._finalize(rid, "redundant_documented", {}), 4)
        self.assertEqual(self._finalize(rid, "redundant_documented", {"requirement_ref": "OPS-12"}), 0)
        kws = [kw("K1", "G1", "drill", "PHRASE"), kw("K3", "G3", "drill", "BROAD", cid="C2")]
        body = self.run_skill(tables(kws, [st("cordless drill", "G1", "K1"), st("cordless drill", "G3", "K3", cid="C2")]),
                              {"intended_routing": {"cordless drill": {"campaign_id": "C1", "ad_group_id": "G1"}}})
        rid = body["ai_review"][0]["id"]
        neg = {"negative": "cordless drill", "match_type": "EXACT", "level": "ad_group", "campaign_id": "C2",
               "ad_group_id": "G3"}
        self.assertEqual(self._finalize(rid, "contradicts_routing", {"negatives": [neg]}), 0)
        self.assertEqual(self._finalize(rid, "contradicts_routing",
                                        {"negatives": [dict(neg, campaign_id="C1", ad_group_id="G1")]}), 4)
        self.assertEqual(self._finalize(rid, "contradicts_routing",
                                        {"negatives": [dict(neg, negative="drill", match_type="PHRASE")]}), 4)


if __name__ == "__main__":
    unittest.main()
