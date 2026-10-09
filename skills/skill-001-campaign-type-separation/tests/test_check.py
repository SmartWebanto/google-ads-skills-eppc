"""test_check.py — skill-001 decision boundaries: overlap, unknown objectives, objective reviews, consolidation gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-001-campaign-type-separation/tests -t skills/skill-001-campaign-type-separation
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
_spec = importlib.util.spec_from_file_location("check_skill_001", SCRIPT)
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


def camp(cid, ch="SEARCH", strat="TARGET_CPA", status="ENABLED", **kw):
    return {"id": cid, "name": f"C{cid}", "status": status, "channel_type": ch, "bidding_strategy_type": strat,
            "geo_targets": "Italy", "languages": "it", "target_cpa": kw.get("target_cpa", ""),
            "target_roas": kw.get("target_roas", ""), "shared_budget": "false", "daily_budget": "10"}


def met(cid, cost=100, conv=5):
    return {"campaign_id": cid, "clicks": 100, "cost": cost, "conversions": conv, "conversion_value": 0}


class CampaignArchitecture(unittest.TestCase):
    def test_shopping_and_pmax_coexistence_is_info_only_when_both_enabled(self):
        prof = {"campaign_objectives": {"1": {"role": "a"}, "2": {"role": "a"}}}
        body = run(self, {"campaigns": [camp("1", "SHOPPING", "TARGET_ROAS"), camp("2", "PERFORMANCE_MAX", "TARGET_ROAS")],
                          "campaign_metrics": [met("1"), met("2")]}, prof)
        self.assertEqual([f["severity"] for f in F(body, "product_overlap_unknown")], ["Info"])
        body = run(self, {"campaigns": [camp("1", "SHOPPING", "TARGET_ROAS"),
                                        camp("2", "PERFORMANCE_MAX", "TARGET_ROAS", status="PAUSED")],
                          "campaign_metrics": [met("1"), met("2")]}, prof)
        self.assertEqual(F(body, "product_overlap_unknown"), [])

    def test_enabled_campaign_without_objective_is_info_and_paused_is_not(self):
        prof = {"campaign_objectives": {"1": {"role": "a"}}}
        body = run(self, {"campaigns": [camp("1"), camp("2"), camp("3", status="PAUSED")],
                          "campaign_metrics": [met("1"), met("2"), met("3")]}, prof)
        self.assertEqual([f["entity"]["campaign_id"] for f in F(body, "objective_unknown")], ["2"])

    def test_missing_objectives_skip_dependent_checks(self):
        body = run(self, {"campaigns": [camp("1")], "campaign_metrics": [met("1")]})
        self.assertEqual(cov(body, "objective_coverage")["status"], "skipped")
        self.assertIn("profile:campaign_objectives", cov(body, "objective_coverage")["missing"])
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_roas_objective_with_cpa_strategy_is_review_not_deterministic_warning(self):
        prof = {"campaign_objectives": {"1": {"role": "sales", "target_roas": 4}}}
        body = run(self, {"campaigns": [camp("1", strat="TARGET_CPA")], "campaign_metrics": [met("1")]}, prof)
        rv = R(body, "setting_contradicts_objective")
        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0]["outcomes"]["contradicts"]["severity"], "Warning")
        self.assertIsNotNone(rv[0]["provisional_finding"])
        self.assertEqual(body["counts"]["Warning"], 0)
        body = run(self, {"campaigns": [camp("1", strat="TARGET_ROAS", target_roas=4)], "campaign_metrics": [met("1")]}, prof)
        self.assertEqual(R(body, "setting_contradicts_objective"), [])

    def test_consolidation_review_requires_maturity_and_compatible_group(self):
        prof = {"campaign_objectives": {"1": {"role": "a", "goal_ids": [9]}, "2": {"role": "a", "goal_ids": [9]},
                                        "3": {"role": "b", "goal_ids": [9]}}}
        tables = {"campaigns": [camp("1"), camp("2"), camp("3")],
                  "campaign_metrics": [met("1", conv=3), met("2", conv=40), met("3", conv=2)]}
        body = run(self, tables, prof)
        rv = R(body, "consolidation_candidate")
        self.assertEqual([r["entity"]["campaigns"] for r in rv], [["1", "2"]])
        immature = dict(ACCOUNT, snapshot_date="2026-09-02")
        body = run(self, tables, prof, account=immature)
        self.assertEqual(R(body, "consolidation_candidate"), [])
        self.assertEqual(cov(body, "separation_rationale")["status"], "partial")

    def test_metric_fanout_rows_are_excluded_not_summed(self):
        prof = {"campaign_objectives": {"1": {"role": "a"}}}
        body = run(self, {"campaigns": [camp("1")], "campaign_metrics": [met("1", cost=100), met("1", cost=50)]}, prof)
        self.assertEqual(cov(body, "scope")["status"], "partial")
        shares = [o for o in body["observations"] if o["check"] == "channel_share" and o["data"].get("objective") == "a"]
        self.assertEqual(shares, [])

    def test_unknown_budget_flags_block_budget_sum(self):
        prof = {"campaign_objectives": {"1": {"role": "a"}}}
        c = dict(camp("1"), shared_budget="")
        body = run(self, {"campaigns": [c], "campaign_metrics": [met("1")]}, prof)
        total = next(o for o in body["observations"] if o["text"].startswith("Daily budget total"))
        self.assertIsNone(total["data"]["daily_budget_total"])

    def test_finalize_rejects_consolidation_outside_reviewed_group(self):
        prof = {"campaign_objectives": {"1": {"role": "a"}, "2": {"role": "a"}}}
        tables = {"campaigns": [camp("1"), camp("2")], "campaign_metrics": [met("1", conv=1), met("2", conv=1)]}
        pick = lambda campaigns: (lambda body: [{"id": R(body, "consolidation_candidate")[0]["id"],
                                                 "outcome": "consolidation_review", "rationale": "same goal",
                                                 "proposal": {"campaigns": campaigns}}])
        code, final = finalize(self, tables, prof, pick(["1", "9"]))
        self.assertEqual(code, 4)
        code, final = finalize(self, tables, prof, pick(["1", "2"]))
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in F(final, "consolidation_candidate")], ["Info"])


if __name__ == "__main__":
    unittest.main()
