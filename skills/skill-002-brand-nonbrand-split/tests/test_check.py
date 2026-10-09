"""test_check.py — skill-002 decision boundaries: classification, routing materiality, share gates, verified proposals.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-002-brand-nonbrand-split/tests -t skills/skill-002-brand-nonbrand-split
rules:   Synthetic temp exports only; never reads the self-test oracle; asserts entities/severities/coverage, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | CodeDNA header
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | tests for this session's check changes
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
_spec = importlib.util.spec_from_file_location("check_skill_002", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "111-111-1111", "currency_code": "EUR", "date_range_start": "2026-08-04",
           "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def build(test, tables, profile=None, account=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    export = root / "export"
    tables = {"account": [account or ACCOUNT], **tables}
    for key, rows in tables.items():
        _write(export / f"{key}.csv", rows)
    _write(export / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete", "truncation": "none"}
                                           for k in tables])
    prof = root / "profile.json"
    prof.write_text(json.dumps(profile or {}))
    return root, export, prof


def run(test, tables, profile=None, account=None):
    _, export, prof = build(test, tables, profile, account)
    return cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()


def finalize(test, tables, profile, choose):
    root, export, prof = build(test, tables, profile)
    out = root / "out"
    base = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
    with contextlib.redirect_stdout(io.StringIO()):
        test.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + base), 0)
    dec = root / "decisions.json"
    dec.write_text(json.dumps(choose(json.loads((out / "result.json").read_text()))))
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + base + ["--decisions", str(dec)])
    return code, json.loads((out / "final.json").read_text())


def F(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


def R(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)



PROFILE = {"brand_terms": ["acme"], "competitor_terms": ["rival"],
           "campaign_objectives": {"1": {"role": "brand", "brand_policy": "brand_only", "target_cpa": 20},
                                   "2": {"role": "acq", "brand_policy": "nonbrand_only", "target_cpa": 40},
                                   "3": {"role": "other"}}}


def camps():
    return [{"id": c, "name": f"C{c}", "status": "ENABLED", "channel_type": ch} for c, ch in
            (("1", "SEARCH"), ("2", "SEARCH"), ("3", "SEARCH"), ("4", "PERFORMANCE_MAX"))]


def kw(i, c, g, text):
    return {"id": i, "campaign_id": c, "ad_group_id": g, "text": text, "match_type": "PHRASE", "status": "ENABLED"}


def st(q, c, g, clicks=10, cost=10.0, conv=0):
    return {"search_term": q, "campaign_id": c, "ad_group_id": g, "clicks": clicks, "cost": cost, "conversions": conv,
            "matched_keyword_id": "", "added_excluded": "NONE"}


def tables(queries, negatives=(), keywords=None, clicks=None):
    clicks = clicks or {}
    return {"campaigns": camps(),
            "campaign_metrics": [{"campaign_id": c, "clicks": clicks.get(c, 1000), "cost": 500} for c in ("1", "2", "3", "4")],
            "ad_groups": [{"id": g, "campaign_id": c, "status": "ENABLED"} for c, g in (("1", "11"), ("2", "21"), ("3", "31"))],
            "keywords": keywords if keywords is not None else [kw("k1", "1", "11", "acme"), kw("k2", "2", "21", "drill")],
            "search_terms": queries,
            "negative_keywords": list(negatives) or [{"text": "zzz", "match_type": "EXACT", "level": "campaign", "campaign_id": "3"}],
            "shared_negative_lists": [{"list_id": "L1", "name": "none", "member_count": 0, "keywords": "", "campaigns_applied": ""}]}


class BrandRouting(unittest.TestCase):
    def test_classification_brand_precedes_competitor_and_texts_are_token_bounded(self):
        self.assertEqual(M.classify("acme vs rival", ["acme"], ["rival"]), ("Brand", True))
        self.assertEqual(M.classify("rival drill", ["acme"], ["rival"])[0], "Competitor")
        self.assertEqual(M.classify("acmetools drill", ["acme"], [])[0], "Non-brand")
        self.assertEqual(M.classify('"acme"', ["acme"], [])[0], "Unknown")

    def test_material_unblocked_brand_exposure_in_nonbrand_campaign_is_warning(self):
        body = run(self, tables([st("acme drill", "2", "21", cost=30), st("acme drill set", "2", "21", cost=25)]), PROFILE)
        w = F(body, "routing_contradicts_role")
        self.assertEqual([(f["severity"], f["entity"]["campaign_id"]) for f in w], [("Warning", "2")])
        self.assertEqual(w[0]["evidence"]["visible_exposure_cost"], 55)
        self.assertEqual(w[0]["evidence"]["spend_floor"], 50)

    def test_exposure_below_floor_or_already_blocked_is_not_warning(self):
        body = run(self, tables([st("acme drill", "2", "21", cost=30)]), PROFILE)
        self.assertEqual(F(body, "routing_contradicts_role"), [])
        neg = [{"text": "acme", "match_type": "PHRASE", "level": "campaign", "campaign_id": "2"}]
        body = run(self, tables([st("acme drill", "2", "21", cost=300)], negatives=neg), PROFILE)
        self.assertEqual(F(body, "routing_contradicts_role"), [])
        self.assertEqual(F(body, "brand_protection_absent"), [])

    def test_nonbrand_traffic_in_brand_only_campaign_contradicts_role(self):
        body = run(self, tables([st("cheap drill", "1", "11", cost=80)]), PROFILE)
        self.assertEqual([f["entity"]["campaign_id"] for f in F(body, "routing_contradicts_role")], ["1"])

    def test_brand_keyword_in_nonbrand_campaign_is_info_and_mixed_group_info(self):
        kws = [kw("k1", "2", "21", "acme drill"), kw("k2", "2", "21", "drill")]
        body = run(self, tables([st("drill", "3", "31")], keywords=kws), PROFILE)
        self.assertEqual([f["severity"] for f in F(body, "keyword_contradicts_role")], ["Info"])
        self.assertEqual([f["entity"]["ad_group_id"] for f in F(body, "mixed_keywords")], ["21"])
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_brand_share_screen_needs_min_clicks_and_excludes_brand_campaigns(self):
        q = [st("acme tools", "3", "31", clicks=60), st("acme", "1", "11", clicks=900)]
        body = run(self, tables(q), PROFILE)
        self.assertEqual([f["entity"]["campaign_id"] for f in F(body, "brand_click_share")], ["3"])
        self.assertEqual(len(R(body, "brand_click_share")), 1)
        body = run(self, tables(q, clicks={"3": 90}), PROFILE)
        self.assertEqual(F(body, "brand_click_share"), [])
        body = run(self, tables(q, clicks={"3": 0}), PROFILE)
        self.assertEqual(F(body, "brand_click_share"), [])
        self.assertEqual(cov(body, "brand_share")["status"], "partial")

    def test_without_brand_terms_classification_is_skipped_never_inferred(self):
        prof = dict(PROFILE, brand_terms=[])
        body = run(self, tables([st("acme drill", "2", "21", cost=300)]), prof)
        for c in ("term_rules", "classification", "routing_vs_role"):
            self.assertEqual(cov(body, c)["status"], "skipped", c)
        self.assertEqual(body["findings"], [])

    def test_pmax_without_query_rows_is_partial(self):
        body = run(self, tables([st("drill", "2", "21")]), PROFILE)
        self.assertEqual(cov(body, "pmax_brand_traffic")["status"], "partial")

    def test_finalize_verifies_negative_proposals(self):
        q = [st("acme drill", "2", "21", cost=60), st("drill kit", "2", "21", cost=5, conv=2)]
        pick = lambda prop: (lambda body: [{"id": R(body, "exclusion_proposal")[0]["id"], "outcome": "negative_proposed",
                                            "rationale": "brand in nonbrand campaign", "proposal": prop}])
        bad = {"negative": "drill", "match_type": "BROAD", "level": "campaign", "campaign_id": "2"}
        code, _ = finalize(self, tables(q), PROFILE, pick(bad))
        self.assertEqual(code, 4)
        good = {"negative": "acme", "match_type": "PHRASE", "level": "campaign", "campaign_id": "2"}
        code, final = finalize(self, tables(q), PROFILE, pick(good))
        self.assertEqual(code, 0)
        self.assertEqual([f["origin"] for f in F(final, "exclusion_proposal")], ["ai_review"])


if __name__ == "__main__":
    unittest.main()
