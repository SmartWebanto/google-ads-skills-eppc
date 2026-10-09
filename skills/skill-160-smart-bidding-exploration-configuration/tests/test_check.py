"""test_check.py — Decision-boundary tests for skill-160 exploration check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-160-smart-bidding-exploration-configuration/tests -t skills/skill-160-smart-bidding-exploration-configuration
rules:   Temp folders only; pins consumer-visible behavior (tROAS scope, tolerance range, effective target vs
approved floor, budget/portfolio coverage, experiment gates, verify rejections), never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
from __future__ import annotations

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
_spec = importlib.util.spec_from_file_location("skill160_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

CFG_COLS = ["account_id", "strategy_id", "campaign_id", "snapshot_at", "availability", "enabled", "target_roas",
            "configured_roas_tolerance_percent", "effective_target_if_reported", "targeting_eligibility",
            "budget_limited", "portfolio_members", "enabled_at", "source_screen", "current_help_url"]
RISK_COLS = ["strategy_id", "campaign_id", "effective_range", "minimum_acceptable_roas", "approved_budget_cap",
             "value_quality_evidence_ref", "business_goal", "maximum_drawdown", "owner", "approval_status"]
EXP_COLS = ["account_id", "experiment_id", "arm_id", "strategy_id", "campaign_id", "date", "assignment_method",
            "traffic_split", "start_date", "end_date", "changed_setting", "cost", "conversions", "conversion_value",
            "qualified_value", "goal_id", "separately_reported_traffic_label"]
CAMPAIGNS = [
    {"id": "10", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_ROAS", "target_roas": "4"},
    {"id": "11", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_CPA", "target_roas": ""},
    {"id": "12", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_ROAS",
     "bidding_strategy_id": "P1"},
    {"id": "13", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "MAXIMIZE_CONVERSION_VALUE",
     "target_roas": "3"},
    {"id": "14", "status": "ENABLED", "channel_type": "SHOPPING", "bidding_strategy_type": "TARGET_ROAS", "target_roas": "5"},
]


def cfg(cid, sid="", **kw):
    base = {"account_id": "1", "strategy_id": sid, "campaign_id": cid, "snapshot_at": "2026-08-30",
            "availability": "available", "enabled": "true", "target_roas": "4",
            "configured_roas_tolerance_percent": "20", "targeting_eligibility": "eligible", "budget_limited": "false"}
    base.update(kw)
    return base


def risk(cid, floor, sid="", **kw):
    base = {"strategy_id": sid, "campaign_id": cid, "effective_range": "2026-01-01..2026-12-31",
            "minimum_acceptable_roas": floor, "approval_status": "approved", "owner": "cfo",
            "value_quality_evidence_ref": "crm/q3"}
    base.update(kw)
    return base


def build(tmp: Path, *, campaigns=CAMPAIGNS, config=None, risks=None, strategies=None, experiment=None,
          snapshot="2026-09-06") -> Path:
    root = tmp / "export"
    files = {
        "account.csv": (["customer_id", "name", "currency_code", "time_zone", "date_range_start", "date_range_end",
                         "snapshot_date", "rates_format", "money_unit", "conversion_date_basis", "conversion_lag_days"],
                        [{"customer_id": "1", "name": "A", "currency_code": "EUR", "time_zone": "Europe/Rome",
                          "date_range_start": "2026-08-01", "date_range_end": "2026-08-30", "snapshot_date": snapshot,
                          "rates_format": "fraction", "money_unit": "currency",
                          "conversion_date_basis": "interaction_date", "conversion_lag_days": "3"}]),
        "campaigns.csv": (["id", "status", "channel_type", "bidding_strategy_type", "target_roas", "bidding_strategy_id"],
                          campaigns),
    }
    if config is not None:
        files["custom/exploration_config.csv"] = (CFG_COLS, config)
    if risks is not None:
        files["external/exploration_risk.csv"] = (RISK_COLS, risks)
    if strategies is not None:
        files["bidding_strategies.csv"] = (["id", "type", "target_roas", "campaign_ids"], strategies)
    if experiment is not None:
        files["custom/exploration_experiment_daily.csv"] = (EXP_COLS, experiment)
    manifest = [{"filename": n, "source": "test", "completeness": "complete", "truncation": "none"} for n in files]
    files["table_manifest.csv"] = (["filename", "source", "completeness", "truncation"], manifest)
    for name, (cols, rows) in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
    return root


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)

    def run_check(self, **kw) -> dict:
        root = build(self.tmp, **kw)
        out = self.tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        self.assertEqual(code, 0)
        self.root, self.out = root, out
        return json.loads((out / "result.json").read_text())

    def finalize(self, decisions) -> tuple[int, dict]:
        d = self.tmp / "decisions.json"
        d.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--out", str(self.out), "--decisions", str(d)])
        return code, json.loads((self.out / "final.json").read_text())


def found(res, check):
    return sorted((f["condition_key"], json.dumps(f["entity"], sort_keys=True)) for f in res["findings"]
                  if f["check"] == check)


def keys(res, check):
    return sorted(f["condition_key"] for f in res["findings"] if f["check"] == check)


def cov(res, check):
    return next(c for c in res["coverage"] if c["check"] == check)


def reviews(res, key):
    return [r for r in res["ai_review"] if r["condition_key"] == key]


class Scope(Base):
    def test_missing_config_is_skipped(self):
        res = self.run_check()
        self.assertEqual(cov(res, "applicability_eligibility")["status"], "skipped")
        self.assertIn("custom/exploration_config (file)", cov(res, "tolerance_record")["missing"])

    def test_no_troas_search_is_not_applicable(self):
        res = self.run_check(campaigns=[CAMPAIGNS[1], CAMPAIGNS[4]], config=[cfg("11")])
        self.assertEqual(cov(res, "applicability_eligibility")["status"], "not_applicable")
        self.assertEqual(res["findings"], [])

    def test_troas_campaigns_without_config_rows_are_unverified(self):
        res = self.run_check(config=[cfg("10")], strategies=[{"id": "P1", "type": "TARGET_ROAS", "campaign_ids": "12"}])
        ents = [json.loads(e)["campaign_id"] for k, e in found(res, "applicability_eligibility")
                if k == "exploration_settings_unverified"]
        self.assertEqual(sorted(ents), ["12", "13"])

    def test_non_search_troas_row_out_of_scope(self):
        res = self.run_check(config=[cfg("14", configured_roas_tolerance_percent="50")])
        self.assertEqual(keys(res, "tolerance_record"), [])


class Tolerance(Base):
    def test_outside_documented_range_is_info(self):
        res = self.run_check(config=[cfg("10", configured_roas_tolerance_percent="40")])
        self.assertEqual(keys(res, "tolerance_record"), ["tolerance_outside_documented_range"])

    def test_in_range_and_percent_sign_accepted(self):
        res = self.run_check(config=[cfg("10", configured_roas_tolerance_percent="30%")])
        self.assertEqual(keys(res, "tolerance_record"), [])

    def test_disabled_and_unknown_states(self):
        res = self.run_check(config=[cfg("10", enabled="false"), cfg("13", enabled="")])
        self.assertEqual(found(res, "tolerance_record"),
                         [("exploration_disabled", '{"campaign_id": "10"}'), ("tolerance_unverified", '{"campaign_id": "13"}')])


class Floor(Base):
    def test_planning_target_below_approved_floor_is_warning(self):
        res = self.run_check(config=[cfg("10")], risks=[risk("10", "3.5")])
        f = [x for x in res["findings"] if x["check"] == "effective_target_vs_floor"]
        self.assertEqual([(x["condition_key"], x["severity"]) for x in f], [("effective_target_below_floor", "Warning")])
        self.assertAlmostEqual(f[0]["calculation"]["planning_effective_target"], 3.2)
        self.assertEqual(f[0]["evidence"]["minimum_acceptable_roas"], 3.5)

    def test_planning_target_at_or_above_floor_no_finding(self):
        res = self.run_check(config=[cfg("10")], risks=[risk("10", "3.2")])
        self.assertEqual(keys(res, "effective_target_vs_floor"), [])

    def test_reported_effective_target_below_floor_is_warning(self):
        res = self.run_check(config=[cfg("10", effective_target_if_reported="2.9")], risks=[risk("10", "3.0")])
        self.assertEqual(keys(res, "effective_target_vs_floor"), ["effective_target_below_floor"])

    def test_unapproved_or_expired_floor_is_partial(self):
        for r in (risk("10", "3.5", approval_status="draft"),
                  risk("10", "3.5", effective_range="2025-01-01..2025-12-31")):
            with self.subTest(r=r):
                res = self.run_check(config=[cfg("10")], risks=[r])
                self.assertEqual(keys(res, "effective_target_vs_floor"), [])
                self.assertEqual(cov(res, "effective_target_vs_floor")["status"], "partial")

    def test_distinct_approved_floors_are_ambiguous(self):
        res = self.run_check(config=[cfg("10")], risks=[risk("10", "3.5"), risk("10", "3.0", effective_range="")])
        self.assertEqual(keys(res, "effective_target_vs_floor"), ["effective_target_below_floor"])
        res = self.run_check(config=[cfg("10")], risks=[risk("10", "3.5"), risk("10", "3.0")])
        self.assertEqual(keys(res, "effective_target_vs_floor"), [])
        self.assertEqual(cov(res, "effective_target_vs_floor")["status"], "partial")

    def test_disabled_exploration_not_compared(self):
        res = self.run_check(config=[cfg("10", enabled="false")], risks=[risk("10", "3.9")])
        self.assertEqual(keys(res, "effective_target_vs_floor"), [])

    def test_finalize_critical_requires_evidence_ref(self):
        res = self.run_check(config=[cfg("10"), cfg("13", target_roas="3")], risks=[risk("10", "3.5"), risk("13", "2.9")])
        items = sorted(reviews(res, "effective_target_below_floor"), key=lambda r: r["entity"]["campaign_id"])
        self.assertEqual(len(items), 2)
        code, final = self.finalize([
            {"id": items[0]["id"], "outcome": "material_failure_evidenced", "rationale": "drawdown"},
            {"id": items[1]["id"], "outcome": "material_failure_evidenced", "rationale": "drawdown",
             "proposal": {"evidence_ref": "external/daily_pnl.csv#2026-08"}}])
        self.assertEqual(code, 4)
        self.assertEqual(final["counts"]["Critical"], 1)
        self.assertEqual(final["counts"]["Warning"], 1)  # accepted Critical supersedes that entity's Warning


class BudgetPortfolio(Base):
    def test_budget_limited_enabled_is_info(self):
        res = self.run_check(config=[cfg("10", budget_limited="true"), cfg("13", budget_limited="false")])
        self.assertEqual(found(res, "budget_and_portfolio"),
                         [("exploration_inactive_budget_limited", '{"campaign_id": "10"}')])

    def test_portfolio_member_gap(self):
        camps = CAMPAIGNS + [{"id": "15", "status": "ENABLED", "channel_type": "SEARCH",
                              "bidding_strategy_type": "TARGET_ROAS", "bidding_strategy_id": "P1"}]
        strat = [{"id": "P1", "type": "TARGET_ROAS", "campaign_ids": "12;15"}]
        res = self.run_check(campaigns=camps, strategies=strat, config=[cfg("", "P1", portfolio_members="12")],
                             risks=[risk("", "3", sid="P1")])
        f = [x for x in res["findings"] if x["condition_key"] == "portfolio_member_coverage_gap"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["evidence"]["not_listed_in_config"], ["15"])

    def test_portfolio_fully_covered(self):
        camps = CAMPAIGNS + [{"id": "15", "status": "ENABLED", "channel_type": "SEARCH",
                              "bidding_strategy_type": "TARGET_ROAS", "bidding_strategy_id": "P1"}]
        strat = [{"id": "P1", "type": "TARGET_ROAS", "campaign_ids": "12;15"}]
        res = self.run_check(campaigns=camps, strategies=strat, config=[cfg("", "P1", portfolio_members="12;15")],
                             risks=[risk("", "3", sid="P1")])
        self.assertEqual(keys(res, "budget_and_portfolio"), [])


def exp_rows(arm, conv, label="exploration", method="randomized", changed=""):
    return [{"account_id": "1", "experiment_id": "E1", "arm_id": arm, "campaign_id": "10", "date": f"2026-08-{d:02d}",
             "assignment_method": method, "changed_setting": changed, "cost": 500, "conversions": conv / 2,
             "conversion_value": 2000, "goal_id": "G1", "separately_reported_traffic_label": label} for d in (10, 11)]


class Experiments(Base):
    def test_missing_labels_block_split_claims(self):
        res = self.run_check(experiment=exp_rows("a", 40, label="") + exp_rows("b", 40, changed="tol 20"))
        self.assertEqual(keys(res, "experiment_evaluation"), ["separate_outcomes_missing"])
        self.assertFalse(any("gated" in o["text"] for o in res["observations"]))

    def test_gated_controlled_mature_comparison(self):
        res = self.run_check(experiment=exp_rows("a", 40, label="core") + exp_rows("b", 40, changed="tol 20"))
        obs = [o for o in res["observations"] if "gated" in o["text"]]
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["data"]["control_arm"], "a")
        self.assertEqual(keys(res, "experiment_evaluation"), [])

    def test_arm_below_min_conversions_is_sparse(self):
        res = self.run_check(experiment=exp_rows("a", 40) + exp_rows("b", 10, changed="tol 20"))
        self.assertEqual(keys(res, "experiment_evaluation"), ["experiment_sparse"])

    def test_immature_is_partial(self):
        res = self.run_check(experiment=exp_rows("a", 40) + exp_rows("b", 40), snapshot="2026-08-31")
        self.assertEqual(cov(res, "experiment_evaluation")["status"], "partial")
        self.assertFalse(any("gated" in o["text"] for o in res["observations"]))


class Proposal(Base):
    def test_proposed_tolerance_must_keep_floor(self):
        res = self.run_check(config=[cfg("10", enabled="false")], risks=[risk("10", "3.5")])
        item = reviews(res, "tolerance_test_or_no_change")[0]
        base = {"assignment": "50/50 search_based", "primary_value_metric": "gross profit", "sample_plan": "6 weeks",
                "stop_criteria": "ROAS < 3.5 for 14d", "owner": "cfo"}
        code, _ = self.finalize([{"id": item["id"], "outcome": "propose_tolerance_test", "rationale": "x",
                                  "proposal": {**base, "tolerance_percent": 20}}])
        self.assertEqual(code, 4)
        code, final = self.finalize([{"id": item["id"], "outcome": "propose_tolerance_test", "rationale": "x",
                                      "proposal": {**base, "tolerance_percent": 10}}])
        self.assertEqual(code, 0)
        self.assertEqual(final["pending_review"], [])

    def test_no_proposal_without_approved_floor(self):
        res = self.run_check(config=[cfg("10")], risks=[risk("10", "3.5", approval_status="pending")])
        self.assertEqual(reviews(res, "tolerance_test_or_no_change"), [])
        self.assertEqual(cov(res, "experiment_proposal")["status"], "partial")


if __name__ == "__main__":
    unittest.main()
