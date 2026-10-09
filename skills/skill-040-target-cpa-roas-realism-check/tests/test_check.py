"""test_check.py — decision boundaries of skill-040 scripts/check.py (target direction, gates, verify).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-040-target-cpa-roas-realism-check/tests
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
from datetime import date, timedelta
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("skill040_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
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


def camp(cid, stype="TARGET_CPA", cpa="", roas="", sid=""):
    return {"id": cid, "name": cid, "status": "ENABLED", "bidding_strategy_type": stype, "target_cpa": cpa,
            "target_roas": roas, "bidding_strategy_id": sid}


def metric(cid, cost, conv, value, clicks=1000):
    return {"campaign_id": cid, "impressions": 10000, "clicks": clicks, "cost": cost, "conversions": conv,
            "conversion_value": value}


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
        self.profile.write_text(json.dumps(profile or {"conversion_lag_days": 2}))
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


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body):
    return sorted((f["condition_key"], f["severity"], f["entity"].get("campaign_id")) for f in body["findings"])


class TargetRealismTests(unittest.TestCase):
    def base(self, **kw):
        tables = {"campaigns": [camp("C1", cpa="30"), camp("R1", "TARGET_ROAS", roas="3")],
                  "campaign_metrics": [metric("C1", 5000, 100, 25000), metric("R1", 5000, 100, 25000)]}
        tables.update(kw)
        return tables

    def test_tight_cpa_flagged_relaxed_roas_not(self):
        body = Case(self, self.base()).run()
        self.assertEqual(keys(body), [("restrictive_target_gap", "Info", "C1")])
        calc = body["findings"][0]["calculation"]
        self.assertAlmostEqual(calc["restrictiveness"], 0.4)
        self.assertAlmostEqual(calc["achieved"], 50)
        self.assertAlmostEqual(calc["implied_cpc_at_target"], 3.0)  # 30 × (100/1000)
        review = body["ai_review"][0]
        self.assertEqual(review["outcomes"]["corroborated_concern"]["severity"], "Warning")
        self.assertEqual(review["provisional_finding"], body["findings"][0]["id"])

    def test_gap_at_heuristic_boundary_is_not_flagged(self):
        # target 40 vs achieved 50 → restrictiveness exactly 0.20, not > 0.20
        body = Case(self, self.base(campaigns=[camp("C1", cpa="40")],
                                    campaign_metrics=[metric("C1", 5000, 100, 25000)])).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["ai_review"], [])

    def test_sample_gate_blocks_comparison(self):
        body = Case(self, self.base(campaign_metrics=[metric("C1", 5000, 10, 2500), metric("R1", 5000, 10, 2500)])).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "restrictiveness")["status"], "partial")

    def test_zero_conversions_is_unavailable_not_infinite(self):
        body = Case(self, self.base(campaign_metrics=[metric("C1", 5000, 0, 0)])).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "restrictiveness")["status"], "partial")

    def test_immature_window_has_no_performance_finding(self):
        acct = {**ACCOUNT, "snapshot_date": "2026-08-31"}
        body = Case(self, self.base(), account=acct).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "achieved_outcomes")["status"], "partial")

    def test_conflicting_target_sources_are_not_compared(self):
        tables = self.base(campaigns=[camp("C1", cpa="30", sid="S1")],
                           bidding_strategies=[{"id": "S1", "type": "TARGET_CPA", "target_cpa": "35", "campaign_ids": "C1"}])
        body = Case(self, tables).run()
        self.assertEqual(cov(body, "effective_target")["status"], "partial")
        self.assertEqual(body["findings"], [])

    def test_portfolio_target_resolved_by_membership(self):
        tables = self.base(campaigns=[camp("C1")],
                           bidding_strategies=[{"id": "S1", "type": "TARGET_CPA", "target_cpa": "30", "campaign_ids": "C1"}])
        body = Case(self, tables).run()
        self.assertEqual(keys(body), [("restrictive_target_gap", "Info", "C1")])
        self.assertIn("portfolio", body["findings"][0]["entity"]["target_source"])

    def test_relaxed_target_beyond_approved_economics(self):
        profile = {"conversion_lag_days": 2, "campaign_objectives": {"C1": {"goal_ids": ["p"], "target_cpa": 40}}}
        tables = self.base(campaigns=[camp("C1", cpa="60")], campaign_metrics=[metric("C1", 5000, 100, 25000)])
        body = Case(self, tables, profile).run()
        self.assertIn(("relaxed_target_beyond_business_constraint", "Warning", "C1"), keys(body))
        # counterexample: the same relaxed platform target within approved economics
        profile["campaign_objectives"]["C1"]["target_cpa"] = 70
        body = Case(self, tables, profile).run()
        self.assertEqual(body["findings"], [])

    def test_daily_window_respects_regime_change(self):
        end = date(2026, 8, 30)
        daily = []
        for i in range(40):
            d = end - timedelta(days=i)
            daily.append({"campaign_id": "C1", "date": d.isoformat(), "goal_cohort": "p", "strategy_id": "S1",
                          "budget_id": "B1" if i < 35 else "B0", "clicks": 100, "cost": 100, "conversions": 2,
                          "conversion_value": 500, "lag_mature": "true"})
        tables = {"campaigns": [camp("C1", cpa="30")], "custom/target_daily": daily}
        body = Case(self, tables).run()
        f = body["findings"]
        self.assertEqual(keys(body), [("restrictive_target_gap", "Info", "C1")])
        self.assertEqual(f[0]["calculation"]["window"], ["2026-08-01", "2026-08-30"])
        self.assertAlmostEqual(f[0]["calculation"]["achieved"], 50)  # 3000 / 60 summed, not averaged
        # a budget change 10 days ago breaks the stable 30-day window
        for r in daily:
            r["budget_id"] = "B1" if r["date"] >= "2026-08-21" else "B0"
        body = Case(self, {"campaigns": [camp("C1", cpa="30")], "custom/target_daily": daily}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "achieved_outcomes")["status"], "partial")

    def test_shared_pool_utilization_counts_amount_once(self):
        end = date(2026, 8, 30)
        daily = [{"campaign_id": c, "date": (end - timedelta(days=i)).isoformat(), "cost": 30, "conversions": 1,
                  "conversion_value": 10, "lag_mature": "true", "budget_id": "B1"} for i in range(30) for c in ("C1", "C2")]
        hist = [{"budget_id": "B1", "effective_from": "2026-07-01", "effective_to": "", "amount": 100,
                 "amount_unit": "currency", "shared_flag": "true", "member_campaign_ids": "C1;C2"}]
        body = Case(self, {"campaigns": [camp("C1", cpa="30"), camp("C2", cpa="30")], "custom/target_daily": daily,
                           "custom/budget_history": hist}).run()
        obs = next(o for o in body["observations"] if o["check"] == "budget_utilization")
        self.assertAlmostEqual(obs["data"]["utilization"], 0.6)  # 60/day over one 100/day pool
        self.assertEqual(obs["data"]["planned_budget"], 3000)

    def test_finalize_verifies_corroboration_and_bounds(self):
        profile = {"conversion_lag_days": 2, "campaign_objectives": {"C1": {"goal_ids": ["p"], "target_cpa": 45}}}
        case = Case(self, self.base(), profile)
        body = case.run()
        rid = body["ai_review"][0]["id"]
        code, final = case.finalize([{"id": rid, "outcome": "corroborated_concern", "rationale": "volume fell"}])
        self.assertEqual(code, 4)
        code, final = case.finalize([{"id": rid, "outcome": "corroborated_concern", "rationale": "r",
                                      "proposal": {"corroboration": ["budget_pool"], "test_target": 55}}])
        self.assertEqual(code, 4)  # beyond approved 45
        code, final = case.finalize([{"id": rid, "outcome": "corroborated_concern", "rationale": "r",
                                      "proposal": {"corroboration": ["budget_pool"], "test_target": 40}}])
        self.assertEqual(code, 0)
        self.assertIn(("restrictive_target_concern", "Warning", "C1"), keys(final))
        self.assertNotIn(("restrictive_target_gap", "Info", "C1"), keys(final))


if __name__ == "__main__":
    unittest.main()
