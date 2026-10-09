"""test_check.py — skill-023 boundaries: lexical classes, spend floor, maturity/tracking gates, negative verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-023-close-variant-query-expansion-monitoring/tests
rules:   Temp folders only; asserts condition keys/outcomes and gating, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx062 | exact_only_restriction opt-in, verify exit 0/4
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
_spec = importlib.util.spec_from_file_location("check_023", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
PROFILE = {"brand_terms": ["acme"], "excluded_intents": ["free product requests"],
           "campaign_objectives": {"C1": {"goal_ids": ["g1"], "target_cpa": 40}},
           "tracking_verified": {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30", "source_ref": "qa"}}}
KEYWORDS = [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "cordless drill", "match_type": "PHRASE",
             "status": "ENABLED"},
            {"id": "K2", "campaign_id": "C1", "ad_group_id": "G1", "text": "drill set", "match_type": "EXACT",
             "status": "ENABLED"}]


def st(q, kid, clicks, cost, conv, added="NONE"):
    return {"search_term": q, "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": kid,
            "match_type": "PHRASE", "added_excluded": added, "impressions": clicks * 10, "clicks": clicks,
            "cost": cost, "conversions": conv}


class _Harness(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, terms, profile=PROFILE, lag="2", shared=True, drop_col=None, keywords=KEYWORDS):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [{**ACCOUNT, "conversion_lag_days": lag}])
        self._write(root, "campaigns", [{"id": "C1", "status": "ENABLED", "target_cpa": "40"}])
        self._write(root, "campaign_metrics", [{"campaign_id": "C1", "clicks": 1000, "cost": 900}])
        self._write(root, "ad_groups", [{"id": "G1", "campaign_id": "C1", "status": "ENABLED"}])
        self._write(root, "keywords", keywords)
        if drop_col:
            terms = [{k: v for k, v in t.items() if k != drop_col} for t in terms]
        self._write(root, "search_terms", terms)
        self._write(root, "negative_keywords", [{"text": "jobs", "match_type": "PHRASE", "level": "campaign",
                                                 "campaign_id": "C1", "ad_group_id": ""}])
        lists = {"list_id": "L1", "name": "u", "member_count": 1, "keywords": "careers (PHRASE)"}
        if shared:
            lists["campaigns_applied"] = "C1"
        self._write(root, "shared_negative_lists", [lists])
        self.prof = Path(tmp.name) / "p.json"
        self.prof.write_text(json.dumps(profile))
        self.root, self.out = root, out
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--profile", str(self.prof), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _finalize(self, decisions):
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--profile", str(self.prof), "--out",
                               str(self.out), "--decisions", str(dec)])

    def _reviews(self, body, key="variant_query_relevance"):
        return {r["entity"]["search_term"]: r for r in body["ai_review"] if r["condition_key"] == key}

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}


class CheckTests(_Harness):
    def test_lexical_classes(self):
        self.assertEqual(M.lexical_class("Cordless  DRILL", "cordless drill"), "Literal")
        self.assertEqual(M.lexical_class("drill cordless", "cordless drill"), "Reorder")
        self.assertEqual(M.lexical_class("cordless drills", "cordless drill"), "Other")
        self.assertIsNone(M.lexical_class("", "cordless drill"))

    def test_mature_tracked_zero_conversion_variant_gets_warning_path(self):
        body = self._run([st("free cordless drill", "K1", 40, 80, 0), st("cordless drill", "K1", 200, 150, 10)])
        rv = self._reviews(body)
        self.assertEqual(sorted(rv), ["free cordless drill"])  # literal query is never reviewed
        item = rv["free cordless drill"]
        self.assertEqual(item["outcomes"]["irrelevant_zero_conversion"]["severity"], "Warning")
        self.assertEqual(item["outcomes"]["excluded_intent"]["severity"], "Warning")
        self.assertTrue(item["provisional_finding"])

    def test_untracked_or_immature_removes_zero_conversion_outcome(self):
        prof = {k: v for k, v in PROFILE.items() if k != "tracking_verified"}
        item = self._reviews(self._run([st("free cordless drill", "K1", 40, 80, 0)], profile=prof))["free cordless drill"]
        self.assertNotIn("irrelevant_zero_conversion", item["outcomes"])
        body = self._run([st("free cordless drill", "K1", 40, 80, 0)], lag="")
        self.assertNotIn("irrelevant_zero_conversion", self._reviews(body)["free cordless drill"]["outcomes"])
        self.assertEqual(self._cov(body)["zero_conversion_screen"], "partial")

    def test_below_spend_floor_goes_to_batch_only(self):
        body = self._run([st("free cordless drill", "K1", 10, 49.99, 0)])  # floor = max(50, 1 x 40)
        self.assertEqual(self._reviews(body), {})
        self.assertEqual(len([r for r in body["ai_review"] if r["condition_key"] == "sub_floor_variant_relevance"]), 1)

    def test_no_relevance_context_has_no_warning_outcome(self):
        body = self._run([st("free cordless drill", "K1", 40, 80, 0)], profile={"brand_terms": ["acme"]})
        item = self._reviews(body)["free cordless drill"]
        self.assertNotIn("Warning", {o["severity"] for o in item["outcomes"].values()})

    def test_variant_share_boundary(self):
        body = self._run([st("cordless drill", "K1", 50, 20, 1), st("cordless drill sale", "K1", 51, 20, 1)])
        f = [x for x in body["findings"] if x["condition_key"] == "variant_share_over_half"]
        self.assertEqual(len(f), 1)
        body = self._run([st("cordless drill", "K1", 50, 20, 1), st("cordless drill sale", "K1", 50, 20, 1)])
        self.assertEqual([x for x in body["findings"] if x["condition_key"] == "variant_share_over_half"], [])

    def test_missing_trigger_ids_skip_dependent_checks(self):
        body = self._run([st("free cordless drill", "K1", 40, 80, 0)], drop_col="matched_keyword_id")
        cov = self._cov(body)
        self.assertEqual(cov["keyword_join"], "skipped")
        self.assertEqual(cov["relevance_review"], "skipped")
        self.assertEqual(body["ai_review"], [])

    def test_verify_negative_proposals(self):
        terms = [st("free cordless drill", "K1", 40, 80, 0), st("free cordless drill case", "K1", 5, 10, 1)]
        body = self._run(terms)
        item = self._reviews(body)["free cordless drill"]
        base = {"id": item["id"], "outcome": "excluded_intent", "rationale": "free product request (excluded intent)"}
        scope = {"level": "campaign", "campaign_id": "C1"}
        self.assertEqual(self._finalize([{**base, "proposal": {**scope, "negative": "free", "match_type": "PHRASE"}}]), 4)
        self.assertEqual(self._finalize([{**base, "proposal": {**scope, "negative": "drill", "match_type": "BROAD"}}]), 4)
        self.assertEqual(self._finalize([{**base, "proposal": {**scope, "negative": "free cordless drill",
                                                               "match_type": "EXACT"}}]), 0)
        final = json.loads((self.out / "final.json").read_text())
        self.assertIn("Warning", [f["severity"] for f in final["findings"]])

    def test_verify_refuses_without_shared_list_links(self):
        body = self._run([st("free cordless drill", "K1", 40, 80, 0)], shared=False)
        item = self._reviews(body)["free cordless drill"]
        self.assertEqual(self._finalize([{"id": item["id"], "outcome": "excluded_intent", "rationale": "free",
                                          "proposal": {"level": "campaign", "campaign_id": "C1",
                                                       "negative": "free cordless drill", "match_type": "EXACT"}}]), 4)


EO_KEYWORDS = KEYWORDS + [{"id": "K3", "campaign_id": "C1", "ad_group_id": "G1", "text": "cordless drills",
                           "match_type": "EXACT", "status": "ENABLED"},
                          {"id": "K4", "campaign_id": "C1", "ad_group_id": "G1", "text": "drill bits",
                           "match_type": "PHRASE", "status": "PAUSED"}]
EO_TERMS = [st("cordless drill", "K1", 100, 20, 5), st("drill cordless", "K1", 10, 5, 0),
            st("cordless drill red", "K1", 8, 4, 0), st("cordless drill kit", "K1", 6, 3, 2),
            st("cordless drills", "K1", 5, 2, 0), st("drill bits", "K4", 3, 1, 0)]
EO_PROFILE = {**PROFILE, "exact_only_keyword_ids": ["K1", "K4"]}


class ExactOnlyTests(_Harness):
    def _eo(self, body):
        return [r for r in body["ai_review"] if r["condition_key"] == "exact_only_restriction"]

    def _decide(self, item, outcome, negatives=None):
        d = {"id": item["id"], "outcome": outcome, "rationale": "owner asked for literal-only serving"}
        if negatives is not None:
            d["proposal"] = {"negatives": negatives}
        code = self._finalize([d])
        log = json.loads((self.out / "final.json").read_text())["review_log"]
        return code, log[0]["problems"], json.loads((self.out / "final.json").read_text())

    @staticmethod
    def _neg(text, **kw):
        return {"text": text, "match_type": "EXACT", "level": "ad_group", "campaign_id": "C1", "ad_group_id": "G1",
                **kw}

    def test_without_profile_key_not_applicable(self):
        for prof in (PROFILE, {**PROFILE, "exact_only_keyword_ids": []}):
            body = self._run(EO_TERMS, profile=prof, keywords=EO_KEYWORDS)
            self.assertEqual(self._cov(body)["exact_only_restriction"], "not_applicable")
            self.assertEqual(self._eo(body), [])

    def test_one_review_per_listed_active_keyword_with_non_literal_queries(self):
        body = self._run(EO_TERMS, profile=EO_PROFILE, keywords=EO_KEYWORDS)
        items = self._eo(body)
        self.assertEqual([i["entity"] for i in items], [{"campaign_id": "C1", "ad_group_id": "G1", "keyword_id": "K1"}])
        q = {v["search_term"]: v["proposable"] for v in items[0]["evidence"]["variant_queries"]}
        self.assertEqual(q, {"drill cordless": True, "cordless drill red": True, "cordless drill kit": False,
                             "cordless drills": False})  # literal query never listed; K4 is PAUSED
        self.assertEqual({k: v["severity"] for k, v in items[0]["outcomes"].items()},
                         {"restrict_to_literal": "Info", "keep_variants": None})
        self.assertEqual(items[0]["evidence"]["variant_exposure_cost"], 14)
        self.assertFalse(any("not found" in n for c in body["coverage"] if c["check"] == "exact_only_restriction"
                             for n in c["notes"]))

    def test_valid_restriction_and_keep_variants_accepted(self):
        item = self._eo(self._run(EO_TERMS, profile=EO_PROFILE, keywords=EO_KEYWORDS))[0]
        code, problems, final = self._decide(item, "restrict_to_literal",
                                             [self._neg("drill cordless"), self._neg("Cordless  Drill Red")])
        self.assertEqual((code, problems), (0, []))
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "exact_only_restriction"],
                         ["Info"])
        code, problems, final = self._decide(item, "keep_variants")
        self.assertEqual((code, problems), (0, []))
        self.assertEqual([f for f in final["findings"] if f["condition_key"] == "exact_only_restriction"], [])

    def test_each_violation_rejected(self):
        item = self._eo(self._run(EO_TERMS, profile=EO_PROFILE, keywords=EO_KEYWORDS))[0]
        cases = {"must be EXACT": [self._neg("drill cordless", match_type="PHRASE")],
                 "must be an ad_group negative": [self._neg("drill cordless", level="campaign")],
                 "ad group G1": [self._neg("drill cordless", ad_group_id="G2")],
                 "not a reported non-literal query": [self._neg("cordless drill blue")],
                 "own literal text": [self._neg("cordless drill")],
                 "converting": [self._neg("cordless drill kit")],
                 "active keyword 'cordless drills'": [self._neg("cordless drills")],
                 "non-empty list": []}
        for needle, negs in cases.items():
            with self.subTest(needle):
                code, problems, final = self._decide(item, "restrict_to_literal", negs)
                self.assertEqual(code, 4)
                self.assertTrue(any(needle in p for p in problems), problems)
                self.assertEqual([f for f in final["findings"] if f["condition_key"] == "exact_only_restriction"], [])
        # one bad entry rejects the whole proposal
        code, _, _ = self._decide(item, "restrict_to_literal", [self._neg("drill cordless"), self._neg("cordless drills")])
        self.assertEqual(code, 4)

    def test_unknown_conversions_block_and_missing_evidence(self):
        terms = EO_TERMS[:1] + [{**st("drill cordless", "K1", 10, 5, 0), "conversions": ""}]
        item = self._eo(self._run(terms, profile=EO_PROFILE, keywords=EO_KEYWORDS))[0]
        self.assertFalse(item["evidence"]["variant_queries"][0]["proposable"])
        self.assertEqual(self._decide(item, "restrict_to_literal", [self._neg("drill cordless")])[0], 4)
        no_status = [{k: v for k, v in kw.items() if k != "status"} for kw in EO_KEYWORDS]
        body = self._run(EO_TERMS, profile=EO_PROFILE, keywords=no_status)
        self.assertEqual(self._cov(body)["exact_only_restriction"], "skipped")
        self.assertEqual(self._eo(body), [])
        body = self._run(EO_TERMS, profile=EO_PROFILE, keywords=EO_KEYWORDS, drop_col="matched_keyword_id")
        self.assertEqual(self._cov(body)["exact_only_restriction"], "skipped")
        body = self._run(EO_TERMS, profile={**PROFILE, "exact_only_keyword_ids": ["K1", "K9"]}, keywords=EO_KEYWORDS)
        notes = [n for c in body["coverage"] if c["check"] == "exact_only_restriction" for n in c["notes"]]
        self.assertTrue(any("K9" in n for n in notes), notes)
        self.assertEqual(len(self._eo(body)), 1)


if __name__ == "__main__":
    unittest.main()
