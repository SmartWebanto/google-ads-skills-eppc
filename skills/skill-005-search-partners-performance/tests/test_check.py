"""test_check.py — skill-005 decision boundaries: 2x CPA screen, gates, maturity, zero-conversion tracking.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-005-search-partners-performance/tests -t skills/skill-005-search-partners-performance
rules:   Synthetic temp exports only; never reads the self-test oracle; asserts severities/coverage, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | evidence_ref rejection tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | CodeDNA header
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
_spec = importlib.util.spec_from_file_location("check_skill_005", SCRIPT)
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



ND = "custom/network_daily"


def nd(cid, net, clicks, cost, conv, value=0, date="2026-08-10", scope="all"):
    return {"account_id": "111-111-1111", "campaign_id": cid, "date": date, "ad_network_type": net, "impressions": clicks * 10,
            "clicks": clicks, "cost": cost, "conversions": conv, "conversion_value": value, "goal_scope": scope,
            "conversion_date_basis": "interaction_date"}


def tables(rows, target_cpa="20", extra=None):
    t = {"campaigns": [{"id": "1", "name": "S1", "status": "ENABLED", "channel_type": "SEARCH", "target_cpa": target_cpa,
                        "search_partners": "true"}],
         "campaign_metrics": [{"campaign_id": "1", "clicks": sum(r["clicks"] for r in rows if r["campaign_id"] == "1"),
                               "cost": sum(r["cost"] for r in rows if r["campaign_id"] == "1")}],
         ND: rows}
    t.update(extra or {})
    return t


def pair(p_conv=20, p_cost=1000, g_conv=50):
    return [nd("1", "SEARCH", 500, 500, g_conv), nd("1", "SEARCH_PARTNERS", 200, p_cost, p_conv)]


class SearchPartners(unittest.TestCase):
    def test_missing_segmented_metrics_skips_everything_but_settings(self):
        t = tables(pair())
        del t[ND]
        body = run(self, t)
        self.assertEqual(cov(body, "partner_settings")["status"], "completed")
        for c in ("network_scope", "partner_cpa_comparison", "partner_zero_conversions"):
            self.assertEqual(cov(body, c)["status"], "skipped")
        self.assertEqual(body["findings"], [])

    def test_partner_cpa_over_2x_and_above_target_is_warning(self):
        body = run(self, tables(pair()))
        w = F(body, "partner_cpa_above_2x")
        self.assertEqual([f["severity"] for f in w], ["Warning"])
        self.assertAlmostEqual(w[0]["evidence"]["cpa_ratio"], 5.0)

    def test_partner_cpa_within_target_is_not_warning(self):
        body = run(self, tables(pair(), target_cpa="60"))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_sample_gate_on_either_side_blocks_verdict(self):
        body = run(self, tables(pair(p_conv=10)))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])
        self.assertEqual([f["severity"] for f in F(body, "partner_comparison_insufficient")], ["Info"])
        body = run(self, tables(pair(g_conv=10)))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])

    def test_immature_window_blocks_warning(self):
        body = run(self, tables(pair()), account=dict(ACCOUNT, snapshot_date="2026-09-03"))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])

    def test_mixed_goal_scope_blocks_comparison(self):
        rows = [nd("1", "SEARCH", 500, 500, 50, scope="purchase"), nd("1", "SEARCH_PARTNERS", 200, 1000, 20, scope="all")]
        body = run(self, tables(rows))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])

    def test_value_led_objective_goes_to_review_not_cpa(self):
        rows = [nd("1", "SEARCH", 500, 500, 50, value=5000), nd("1", "SEARCH_PARTNERS", 200, 1000, 20, value=1000)]
        prof = {"campaign_objectives": {"1": {"target_roas": 4}}}
        body = run(self, tables(rows, target_cpa=""), prof)
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])
        self.assertEqual(len(R(body, "partner_value_underperformance")), 1)

    def test_zero_partner_conversions_need_tracking_evidence(self):
        rows = [nd("1", "SEARCH", 500, 500, 50), nd("1", "SEARCH_PARTNERS", 100, 120, 0)]
        prof = {"campaign_objectives": {"1": {"goal_ids": ["5001"]}}}
        body = run(self, tables(rows), prof)
        self.assertEqual(R(body, "partner_zero_conversions"), [])
        self.assertEqual(cov(body, "partner_zero_conversions")["status"], "partial")
        ca = {"conversion_actions": [{"id": "5001", "name": "Purchase", "category": "PURCHASE", "status": "ENABLED",
                                      "last_conversion_date": "2026-09-01"}]}
        body = run(self, tables(rows, extra=ca), prof)
        rv = R(body, "partner_zero_conversions")
        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0]["outcomes"]["confirmed_after_review"]["severity"], "Warning")
        self.assertEqual([f["severity"] for f in F(body, "partner_zero_conversions")], ["Info"])
        below = [nd("1", "SEARCH", 500, 500, 50), nd("1", "SEARCH_PARTNERS", 100, 30, 0)]
        self.assertEqual(R(run(self, tables(below, extra=ca), prof), "partner_zero_conversions"), [])

    def test_duplicate_grain_excludes_campaign_and_out_of_window_rows_dropped(self):
        rows = pair() + [nd("1", "SEARCH_PARTNERS", 200, 1000, 20)]
        body = run(self, tables(rows))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])
        self.assertEqual(cov(body, "network_scope")["status"], "partial")
        rows = [nd("1", "SEARCH", 500, 500, 50), nd("1", "SEARCH_PARTNERS", 200, 1000, 20, date="2026-07-01")]
        body = run(self, tables(rows))
        self.assertEqual(F(body, "partner_cpa_above_2x"), [])

    def test_finalize_warning_outcome_needs_evidence_ref(self):
        rows = [nd("1", "SEARCH", 500, 500, 50), nd("1", "SEARCH_PARTNERS", 100, 120, 0)]
        prof = {"campaign_objectives": {"1": {"goal_ids": ["5001"]}}}
        ca = {"conversion_actions": [{"id": "5001", "name": "Purchase", "category": "PURCHASE", "status": "ENABLED",
                                      "last_conversion_date": "2026-09-01"}]}
        def pick(make):
            def choose(body):
                item = R(body, "partner_zero_conversions")[0]
                return [{"id": item["id"], "outcome": "confirmed_after_review", "rationale": "leads junk",
                         "proposal": make(item["evidence"]["evidence_refs"][0])}]
            return choose
        self.assertEqual(finalize(self, tables(rows, extra=ca), prof, pick(lambda ref: {}))[0], 4)
        foreign = (lambda ref: {"evidence_ref": "crm-lead-audit"},  # not supplied evidence
                   lambda ref: {"evidence_ref": ref.replace(" 1/", " 2/")},  # another campaign
                   lambda ref: {"evidence_ref": ref.replace("2026-08", "2026-06")})  # another window
        for make in foreign:
            self.assertEqual(finalize(self, tables(rows, extra=ca), prof, pick(make))[0], 4)
        code, final = finalize(self, tables(rows, extra=ca), prof, pick(lambda ref: {"evidence_ref": ref}))
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in F(final, "partner_zero_conversions")], ["Warning"])


if __name__ == "__main__":
    unittest.main()
