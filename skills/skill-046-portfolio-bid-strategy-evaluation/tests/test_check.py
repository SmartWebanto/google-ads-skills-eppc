"""test_check.py — decision boundaries of skill-046 scripts/check.py (membership, goals, dispersion, guardrails).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-046-portfolio-bid-strategy-evaluation/tests
rules:   Temp folders only; stdlib only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial tests
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

_SPEC = importlib.util.spec_from_file_location("skill046_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
M = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = M
_SPEC.loader.exec_module(M)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}


def _write(root: Path, key: str, rows: list[dict]) -> None:
    path = root / f"{key}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Case:
    def __init__(self, test: unittest.TestCase, tables: dict, profile: dict | None = None, account=None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        tables = {"account": [account or ACCOUNT], **tables}
        for key, rows in tables.items():
            _write(self.export, key, rows)
        _write(self.export, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(profile or goals_profile()))
        self.out = self.root / "out"

    def main(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, list(args))

    def run(self) -> dict:
        assert self.main("run", "--export", str(self.export), "--profile", str(self.profile), "--out", str(self.out)) == 0
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions) -> tuple[int, dict]:
        p = self.root / "decisions.json"
        p.write_text(json.dumps(decisions))
        code = self.main("finalize", "--export", str(self.export), "--profile", str(self.profile), "--out",
                         str(self.out), "--decisions", str(p))
        return code, json.loads((self.out / "final.json").read_text())


def goals_profile(**over):
    obj = {c: {"goal_ids": ["p"]} for c in ("C1", "C2", "C3")}
    for c, v in over.items():
        obj[c] = v
    return {"conversion_lag_days": 2, "campaign_objectives": obj}


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body):
    return sorted((f["condition_key"], f["severity"], f["entity"].get("campaign_id") or f["entity"].get("strategy_id"))
                  for f in body["findings"])


def camp(cid, sid="S1", budget="B1"):
    return {"id": cid, "name": cid, "status": "ENABLED", "bidding_strategy_type": "TARGET_CPA",
            "bidding_strategy_id": sid, "budget_id": budget}


def metric(cid, cost, conv):
    return {"campaign_id": cid, "impressions": 10000, "clicks": 1000, "cost": cost, "conversions": conv,
            "conversion_value": conv * 100}


STRAT = [{"id": "S1", "type": "TARGET_CPA", "target_cpa": "40", "target_roas": "", "status": "ENABLED",
          "campaign_ids": "C1;C2;C3"}]
BALANCED = [metric("C1", 1200, 30), metric("C2", 1000, 25), metric("C3", 800, 20)]


class PortfolioTests(unittest.TestCase):
    def test_balanced_portfolio_has_no_findings(self):
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": BALANCED}).run()
        self.assertEqual(body["findings"], [])
        cv = next(o for o in body["observations"] if o["check"] == "member_dispersion")["data"]["cv"]
        self.assertAlmostEqual(cv, 0.0)
        self.assertEqual(cov(body, "split_evidence")["status"], "partial")

    def test_membership_sources_disagree_and_shared_budget_is_not_membership(self):
        strat = [{**STRAT[0], "campaign_ids": "C1;C2"}]
        camps = [camp("C1"), camp("C2"), camp("C3", sid="S1"), camp("C4", sid="", budget="B1")]
        body = Case(self, {"campaigns": camps, "bidding_strategies": strat, "campaign_metrics": BALANCED}).run()
        self.assertEqual(cov(body, "portfolio_inventory")["status"], "partial")
        members = next(o for o in body["observations"] if o["check"] == "portfolio_inventory")["data"]["members"]
        self.assertEqual(members, ["C1", "C2", "C3"])  # C4 shares a budget, not the strategy

    def test_unknown_goals_are_info(self):
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": BALANCED}, goals_profile(C3={"role": "x"})).run()
        self.assertIn(("unknown_member_goals", "Info", "S1"), keys(body))

    def test_goal_conflict_review_requires_documented_constraint(self):
        profile = goals_profile(C3={"goal_ids": ["lead"], "target_cpa": 30})
        case = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": BALANCED}, profile)
        body = case.run()
        self.assertIn(("portfolio_goal_conflict", "Info", "S1"), keys(body))
        item = next(r for r in body["ai_review"] if r["condition_key"] == "portfolio_goal_conflict")
        self.assertEqual(len(item["evidence"]["conflicts"]), 2)  # goal-set difference + tCPA 40 > approved 30
        code, _ = case.finalize([{"id": item["id"], "outcome": "confirmed_conflict", "rationale": "r"}])
        self.assertEqual(code, 4)
        code, final = case.finalize([{"id": item["id"], "outcome": "confirmed_conflict", "rationale": "r",
                                      "proposal": {"documented_constraint": "profile C3 target_cpa 30"}}])
        self.assertEqual(code, 0)
        self.assertIn(("portfolio_goal_conflict", "Warning", "S1"), keys(final))

    def test_dispersion_and_dominance_triage(self):
        rows = [metric("C1", 1000, 100), metric("C2", 1200, 20), metric("C3", 900, 16)]
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": rows}).run()
        self.assertIn(("member_outcome_dispersion", "Info", "S1"), keys(body))
        self.assertIn(("member_conversion_dominance", "Info", "C1"), keys(body))  # 100/136 > 60%

    def test_low_volume_members_excluded_from_cv(self):
        rows = [metric("C1", 1200, 30), metric("C2", 1000, 25), metric("C3", 500, 2)]
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": rows}).run()
        self.assertEqual(keys(body), [("low_member_volume", "Info", "S1")])
        d = next(o for o in body["observations"] if o["check"] == "member_dispersion")["data"]
        self.assertEqual(d["included"], ["C1", "C2"])

    def test_missing_member_metrics_limit_dominance(self):
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": [metric("C1", 1000, 100), metric("C2", 100, 16)]}).run()
        self.assertNotIn("member_conversion_dominance", [f["condition_key"] for f in body["findings"]])
        self.assertEqual(cov(body, "portfolio_outcomes")["status"], "partial")

    def test_immature_window_blocks_dispersion_and_guardrails(self):
        rows = [metric("C1", 1000, 100), metric("C2", 1200, 20), metric("C3", 900, 16)]
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": rows}, goals_profile(C2={"goal_ids": ["p"], "target_cpa": 40}),
                    account={**ACCOUNT, "snapshot_date": "2026-08-31"}).run()
        self.assertNotIn("member_outcome_dispersion", [f["condition_key"] for f in body["findings"]])
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(cov(body, "member_dispersion")["status"], "partial")

    def test_member_guardrail_breach_is_reviewed(self):
        profile = goals_profile(C2={"goal_ids": ["p"], "target_cpa": 45}, C1={"goal_ids": ["p"], "target_cpa": 45})
        body = Case(self, {"campaigns": [camp("C1"), camp("C2"), camp("C3")], "bidding_strategies": STRAT,
                           "campaign_metrics": [metric("C1", 1200, 30), metric("C2", 1500, 25), metric("C3", 800, 20)]},
                    profile).run()
        self.assertEqual([k for k in keys(body) if k[0] == "member_guardrail_breach"],
                         [("member_guardrail_breach", "Info", "C2")])  # C2 CPA 60 > 45; C1 CPA 40 within


if __name__ == "__main__":
    unittest.main()
