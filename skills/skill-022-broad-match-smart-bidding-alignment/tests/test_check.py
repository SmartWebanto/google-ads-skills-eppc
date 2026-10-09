"""test_check.py — skill-022 boundaries: portfolio precedence, broad/manual Info, readiness, relevance gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-022-broad-match-smart-bidding-alignment/tests
rules:   Temp folders only; asserts condition keys/outcomes and gating, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial tests
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

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_022", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
VERIFIED = {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30", "source_ref": "qa"}}


def camp(cid, typ, **extra):
    return {"id": cid, "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": typ, **extra}


class CheckTests(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, campaigns, profile=None, strategies=None, terms=None, lag="2", kw_match="BROAD"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [{**ACCOUNT, "conversion_lag_days": lag}])
        self._write(root, "campaigns", campaigns)
        if strategies:
            self._write(root, "bidding_strategies", strategies)
        self._write(root, "keywords", [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "drill",
                                        "match_type": kw_match, "status": "ENABLED"}])
        self._write(root, "keyword_metrics", [{"keyword_id": "K1", "campaign_id": "C1", "ad_group_id": "G1",
                                               "cost": 120}])
        self._write(root, "conversion_actions", [{"id": "g1", "status": "ENABLED"}])
        if terms:
            self._write(root, "search_terms", terms)
        prof = Path(tmp.name) / "p.json"
        prof.write_text(json.dumps(profile or {}))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, None,
                              ["run", "--export", str(root), "--profile", str(prof), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _keys(self, body):
        return sorted(f["condition_key"] for f in body["findings"])

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_broad_with_manual_is_info_not_with_smart_bidding(self):
        body = self._run([camp("C1", "MANUAL_CPC")])
        self.assertIn("broad_with_non_conversion_strategy", self._keys(body))
        self.assertTrue(all(f["severity"] == "Info" for f in body["findings"]))
        body = self._run([camp("C1", "TARGET_CPA")])
        self.assertNotIn("broad_with_non_conversion_strategy", self._keys(body))
        self.assertEqual(self._cov(body)["non_conversion_objectives"], "not_applicable")

    def test_portfolio_strategy_takes_precedence(self):
        body = self._run([camp("C1", "MANUAL_CPC", bidding_strategy_id="S1")],
                         strategies=[{"id": "S1", "type": "TARGET_CPA", "campaign_ids": "C1"}])
        self.assertNotIn("broad_with_non_conversion_strategy", self._keys(body))
        obs = [o["data"] for o in body["observations"] if o["check"] == "strategy_resolution"][0]
        self.assertEqual(obs["strategy_class"], "conversion_smart_bidding")

    def test_ecpc_is_historical_observation_only(self):
        body = self._run([camp("C1", "ENHANCED_CPC")])
        self.assertIn(self._cov(body)["legacy_ecpc"], ("completed", "partial"))
        self.assertNotIn("legacy_ecpc", {f["check"] for f in body["findings"]})

    def test_readiness_info_only_without_confirmed_tracking(self):
        body = self._run([camp("C1", "MANUAL_CPC")])
        self.assertIn("conversion_optimization_readiness_unconfirmed", self._keys(body))
        body = self._run([camp("C1", "MANUAL_CPC")], profile={"campaign_objectives": {"C1": {"goal_ids": ["g1"]}},
                                                             "tracking_verified": VERIFIED})
        self.assertNotIn("conversion_optimization_readiness_unconfirmed", self._keys(body))

    def test_relevance_review_needs_broad_trigger_floor_and_maturity(self):
        prof = {"campaign_objectives": {"C1": {"goal_ids": ["g1"], "role": "acquisition"}}}
        terms = [{"search_term": "drill jobs", "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": "K1",
                  "clicks": 30, "cost": 60, "conversions": 0},
                 {"search_term": "drill bits", "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": "K1",
                  "clicks": 5, "cost": 10, "conversions": 0}]
        body = self._run([camp("C1", "TARGET_CPA")], prof, terms=terms)
        rv = {r["entity"].get("search_term"): r for r in body["ai_review"]
              if r["condition_key"] == "broad_query_contradicts_objective"}
        self.assertEqual(sorted(rv), ["drill jobs"])
        self.assertEqual(rv["drill jobs"]["outcomes"]["contradicts_objective"]["severity"], "Warning")
        self.assertEqual(self._run([camp("C1", "TARGET_CPA")], prof, terms=terms, kw_match="PHRASE")["ai_review"], [])
        body = self._run([camp("C1", "TARGET_CPA")], prof, terms=terms, lag="")
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self._cov(body)["broad_query_relevance"], "partial")

    def test_no_objective_withholds_warning(self):
        terms = [{"search_term": "drill jobs", "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": "K1",
                  "clicks": 30, "cost": 60, "conversions": 0}]
        body = self._run([camp("C1", "TARGET_CPA")], terms=terms)
        item = [r for r in body["ai_review"] if r["condition_key"] == "broad_query_contradicts_objective"][0]
        self.assertNotIn("contradicts_objective", item["outcomes"])

    def test_missing_strategy_column_skips(self):
        body = self._run([{"id": "C1", "status": "ENABLED", "channel_type": "SEARCH"}])
        self.assertTrue(all(s == "skipped" for k, s in self._cov(body).items() if k != "window_scope"))
        self.assertEqual(body["findings"], [])


if __name__ == "__main__":
    unittest.main()
