"""test_check.py — decision boundaries of skill-042 scripts/check.py (budget evidence, economics, saturation).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-042-budget-limited-campaign-identification/tests
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

_SPEC = importlib.util.spec_from_file_location("skill042_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
M = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = M
_SPEC.loader.exec_module(M)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}
PROFILE = {"conversion_lag_days": 2, "campaign_objectives": {"C1": {"goal_ids": ["p"], "target_cpa": 40},
                                                             "C2": {"goal_ids": ["p"], "target_cpa": 40}}}


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
        self.profile.write_text(json.dumps(profile if profile is not None else PROFILE))
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


def camp(cid, channel="SEARCH", budget="B1"):
    return {"id": cid, "name": cid, "status": "ENABLED", "channel_type": channel, "budget_id": budget}


def metric(cid, cost=2000, conv=60, lost="0.2", imp=20000):
    return {"campaign_id": cid, "impressions": imp, "clicks": 1000, "cost": cost, "conversions": conv,
            "conversion_value": 5000, "search_budget_lost_is": lost, "search_rank_lost_is": "0.1"}


class BudgetLimitedTests(unittest.TestCase):
    def test_budget_lost_is_with_acceptable_economics_is_info_candidate(self):
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1")]}).run()
        self.assertEqual(keys(body), [("budget_constrained_scale_candidate", "Info", "C1")])
        self.assertAlmostEqual(body["findings"][0]["calculation"]["cpa"], 2000 / 60, places=4)

    def test_economics_above_limit_or_non_search_is_not_candidate(self):
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", cost=3000)]}).run()
        self.assertEqual(body["findings"], [])  # CPA 50 > approved 40
        body = Case(self, {"campaigns": [camp("C1", channel="DISPLAY")], "campaign_metrics": [metric("C1")]}).run()
        self.assertEqual(body["findings"], [])

    def test_generic_limited_is_not_budget_evidence(self):
        status = [{"campaign_id": "C1", "observed_at": "2026-08-10", "primary_status": "LIMITED",
                   "raw_reasons": "LIMITED_BY_RANK", "budget_specific_diagnostic": "false"}]
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", lost="0")],
                           "custom/budget_constraint_status": status}).run()
        self.assertEqual(keys(body), [("generic_limited_not_budget_evidence", "Info", "C1")])

    def test_censored_is_and_small_samples_block_candidates(self):
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", lost="< 10%")]}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "budget_constraint_evidence")["status"], "partial")
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", conv=10, cost=300)]}).run()
        self.assertEqual(body["findings"], [])
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", imp=500)]}).run()
        self.assertEqual(body["findings"], [])

    def test_immature_window_blocks_candidates(self):
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1")]},
                    account={**ACCOUNT, "snapshot_date": "2026-08-31"}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "mature_economics")["status"], "partial")

    def test_shared_pool_saturation_sums_members_once(self):
        end = date(2026, 8, 30)
        daily = [{"campaign_id": c, "date": (end - timedelta(days=i)).isoformat(), "budget_id": "B1",
                  "cost": 50 if c == "C1" else (45 if i < 10 else 20)} for i in range(30) for c in ("C1", "C2")]
        hist = [{"budget_id": "B1", "effective_from": "2026-07-01", "effective_to": "", "amount": 100,
                 "amount_unit": "currency", "shared_flag": "true", "member_campaign_ids": "C1;C2"}]
        body = Case(self, {"campaigns": [camp("C1"), camp("C2")], "custom/budget_constraint_daily": daily,
                           "custom/budget_history": hist}).run()
        obs = next(o for o in body["observations"] if o["check"] == "pool_saturation")
        self.assertEqual(obs["data"]["days"], 30)
        self.assertEqual(obs["data"]["days_near_budget"], 10)
        self.assertEqual(obs["data"]["days_at_or_over_budget"], 0)
        self.assertEqual(obs["data"]["dated_budget_sum"], 3000)

    def test_commitment_conflict_needs_persistence_and_reference(self):
        profile = {**PROFILE, "budget_constraints": {"B1": {"committed_daily_delivery": 100}}}
        one = [{"campaign_id": "C1", "observed_at": "2026-08-10", "primary_status": "LIMITED",
                "raw_reasons": "BUDGET", "budget_specific_diagnostic": "true", "source_ref": "diag-1"}]
        case = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1")],
                           "custom/budget_constraint_status": one}, profile)
        rid = next(r["id"] for r in case.run()["ai_review"])
        code, _ = case.finalize([{"id": rid, "outcome": "conflicts_commitment", "rationale": "r",
                                  "proposal": {"commitment_ref": "brief-3"}}])
        self.assertEqual(code, 4)
        two = one + [{**one[0], "observed_at": "2026-08-20"}]
        case = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1")],
                           "custom/budget_constraint_status": two}, profile)
        rid = next(r["id"] for r in case.run()["ai_review"])
        code, final = case.finalize([{"id": rid, "outcome": "conflicts_commitment", "rationale": "r",
                                      "proposal": {"commitment_ref": "brief-3"}}])
        self.assertEqual(code, 0)
        self.assertIn(("constraint_conflicts_commitment", "Warning", "C1"), keys(final))


if __name__ == "__main__":
    unittest.main()
