"""test_check.py — skill-004 decision boundaries: eligible copy, theme reviews, metric grain, verified contradictions.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-004-ad-group-thematic-tightness/tests -t skills/skill-004-ad-group-thematic-tightness
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
_spec = importlib.util.spec_from_file_location("check_skill_004", SCRIPT)
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



PROFILE = {"product_service_taxonomy": ["power tools", "garden supplies"],
           "theme_lexicon": {"power tools": ["drill", "saw"], "garden supplies": ["hose"]}}


def kw(i, g, text, c="1"):
    return {"id": i, "campaign_id": c, "ad_group_id": g, "text": text, "match_type": "PHRASE", "status": "ENABLED"}


def ad(i, g, headlines, status="ENABLED", approval="APPROVED", c="1"):
    return {"id": i, "campaign_id": c, "ad_group_id": g, "status": status, "approval_status": approval,
            "headlines": headlines, "descriptions": "Fast delivery", "final_url": "https://x.example/"}


def km(i, g, conv=1, c="1"):
    return {"keyword_id": i, "campaign_id": c, "ad_group_id": g, "impressions": 100, "clicks": 60, "cost": 30, "conversions": conv}


def tables(keywords, ads, metrics=None):
    return {"campaigns": [{"id": "1", "status": "ENABLED", "channel_type": "SEARCH"},
                          {"id": "2", "status": "ENABLED", "channel_type": "SHOPPING"}],
            "ad_groups": [{"id": g, "campaign_id": c, "status": "ENABLED"} for c, g in (("1", "10"), ("1", "11"), ("2", "20"))],
            "keywords": keywords, "ads": ads,
            "keyword_metrics": metrics if metrics is not None else [km(k["id"], k["ad_group_id"], c=k["campaign_id"]) for k in keywords]}


class Themes(unittest.TestCase):
    def test_no_eligible_ad_is_info_but_unknown_approval_is_partial(self):
        k = [kw("a", "10", "cordless drill"), kw("b", "11", "saw blade")]
        body = run(self, tables(k, [ad("x", "10", "Drills", approval="DISAPPROVED"), ad("y", "11", "Saws", approval="")]), PROFILE)
        self.assertEqual([f["entity"]["ad_group_id"] for f in F(body, "insufficient_eligible_copy")], ["10"])
        self.assertEqual(cov(body, "copy_alignment")["status"], "partial")

    def test_keyword_count_alone_never_produces_a_finding(self):
        k = [kw(f"k{i}", "10", f"drill model {i}") for i in range(35)]
        body = run(self, tables(k, [ad("x", "10", "Drill models")]), PROFILE)
        self.assertEqual(body["findings"], [])
        large = next(o for o in body["observations"] if o["text"].startswith("Size buckets"))
        self.assertEqual(large["data"]["large"], ["10"])

    def test_copy_contradiction_is_review_only(self):
        k = [kw("a", "10", "garden hose"), kw("b", "10", "hose reel")]
        body = run(self, tables(k, [ad("x", "10", "Power Tools Sale")]), PROFILE)
        rv = R(body, "theme_copy_contradiction")
        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0]["outcomes"]["contradicted"]["severity"], "Warning")
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_lexicon_multiple_themes_info_single_theme_no_review(self):
        mixed = [kw("a", "10", "cordless drill"), kw("b", "10", "garden hose")]
        body = run(self, tables(mixed, [ad("x", "10", "Tools")]), PROFILE)
        self.assertEqual([f["severity"] for f in F(body, "multiple_themes")], ["Info"])
        self.assertIsNotNone(R(body, "theme_grouping")[0]["provisional_finding"])
        single = [kw("a", "10", "cordless drill"), kw("b", "10", "circular saw")]
        body = run(self, tables(single, [ad("x", "10", "Tools")]), PROFILE)
        self.assertEqual(F(body, "multiple_themes"), [])
        self.assertEqual(R(body, "theme_grouping"), [])

    def test_non_search_ad_groups_out_of_scope(self):
        k = [kw("a", "20", "drill", c="2")]
        body = run(self, tables(k, [ad("x", "20", "Drills", c="2")]), PROFILE)
        self.assertEqual(R(body, "theme_copy_contradiction"), [])
        self.assertEqual(cov(body, "copy_alignment")["status"], "skipped")

    def test_duplicate_metric_rows_excluded_and_immature_totals_descriptive(self):
        k = [kw("a", "10", "drill"), kw("b", "10", "saw")]
        metrics = [km("a", "10", conv=20), km("a", "10", conv=20), km("b", "10", conv=20)]
        body = run(self, tables(k, [ad("x", "10", "Drill saw")], metrics), PROFILE)
        self.assertEqual(cov(body, "metric_scope")["status"], "partial")
        tot = next(o for o in body["observations"] if o["check"] == "theme_metrics")
        self.assertEqual(tot["data"]["conversions"], 20)
        imm = dict(ACCOUNT, snapshot_date="2026-09-03")
        body = run(self, tables(k, [ad("x", "10", "Drill saw")]), PROFILE, account=imm)
        self.assertEqual(cov(body, "theme_metrics")["status"], "partial")
        tot = next(o for o in body["observations"] if o["check"] == "theme_metrics")
        self.assertNotIn("cpa", tot["data"])

    def test_without_taxonomy_themes_are_tentative(self):
        body = run(self, tables([kw("a", "10", "drill")], [ad("x", "10", "Drill")]), {})
        self.assertEqual(cov(body, "theme_tuples")["status"], "partial")
        self.assertIn("profile:product_service_taxonomy", cov(body, "theme_tuples")["missing"])

    def test_finalize_contradiction_requires_ids_and_literal_product_evidence(self):
        k = [kw("a", "10", "garden hose"), kw("b", "10", "hose reel")]
        t = tables(k, [ad("x", "10", "Power Tools Sale")])
        pick = lambda prop: (lambda body: [{"id": R(body, "theme_copy_contradiction")[0]["id"], "outcome": "contradicted",
                                            "rationale": "hose vs power tools copy", "proposal": prop}])
        code, _ = finalize(self, t, PROFILE, pick({"keyword_ids": ["a"], "ad_ids": ["x"], "product_evidence": "ladders"}))
        self.assertEqual(code, 4)
        code, final = finalize(self, t, PROFILE, pick({"keyword_ids": ["a"], "ad_ids": ["x"], "product_evidence": "garden hose"}))
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in F(final, "theme_copy_contradiction")], ["Warning"])


if __name__ == "__main__":
    unittest.main()
