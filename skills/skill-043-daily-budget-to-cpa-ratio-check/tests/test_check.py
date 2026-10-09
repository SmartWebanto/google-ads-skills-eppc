"""test_check.py — decision boundaries of skill-043 scripts/check.py (budget scope, ratios, zero-conversion gate).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-043-daily-budget-to-cpa-ratio-check/tests
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

_SPEC = importlib.util.spec_from_file_location("skill043_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
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
        self.profile.write_text(json.dumps(profile or {"conversion_lag_days": 2}))
        self.out = self.root / "out"

    def main(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, None, list(args))

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
    return sorted((f["condition_key"], f["severity"], f["entity"].get("campaign_id"), f["entity"].get("ratio"))
                  for f in body["findings"])


def obs(body, check, cid=None, budget=None):
    return [o["data"] for o in body["observations"] if o["check"] == check
            and (cid is None or o["data"].get("campaign_id") == cid) and (budget is None or o["data"].get("budget_id") == budget)]


def camp(cid, daily="90", cpa="40", stype="TARGET_CPA", shared="false", budget=""):
    return {"id": cid, "name": cid, "status": "ENABLED", "bidding_strategy_type": stype, "target_cpa": cpa,
            "target_roas": "", "daily_budget": daily, "shared_budget": shared, "budget_id": budget}


def metric(cid, cost=2720, conv=70):
    return {"campaign_id": cid, "impressions": 10000, "clicks": 1000, "cost": cost, "conversions": conv,
            "conversion_value": 1000, "search_budget_lost_is": "0.1"}


class BudgetRatioTests(unittest.TestCase):
    def test_ratios_are_descriptors_not_findings(self):
        body = Case(self, {"campaigns": [camp("C1"), camp("C2", daily="1000", cpa="40")],
                           "campaign_metrics": [metric("C1"), metric("C2")]}).run()
        self.assertEqual(body["findings"], [])  # 2.25x and 25x are both descriptors only
        d = obs(body, "standalone_ratios", "C1")[0]
        self.assertAlmostEqual(d["target_ratio"], 2.25)
        self.assertAlmostEqual(d["achieved_ratio"], 90 / (2720 / 70), places=4)

    def test_zero_or_low_conversions_make_achieved_ratio_unavailable(self):
        for conv in (0, 10):
            body = Case(self, {"campaigns": [camp("C1", cpa="")], "campaign_metrics": [metric("C1", cost=40, conv=conv)]}).run()
            self.assertIn(("ratio_unavailable", "Info", "C1", "achieved_ratio"), keys(body))
            self.assertIn(("ratio_unavailable", "Info", "C1", "target_ratio"), keys(body))

    def test_immature_window_blocks_achieved_ratio(self):
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1")]},
                    account={**ACCOUNT, "snapshot_date": "2026-08-31"}).run()
        self.assertEqual(keys(body), [("ratio_unavailable", "Info", "C1", "achieved_ratio")])
        self.assertEqual(cov(body, "standalone_ratios")["status"], "partial")

    def test_roas_campaign_has_no_cpa_ratio(self):
        body = Case(self, {"campaigns": [camp("C1", cpa="", stype="TARGET_ROAS")], "campaign_metrics": [metric("C1")]}).run()
        self.assertEqual(body["findings"], [])
        self.assertIsNone(obs(body, "standalone_ratios", "C1")[0].get("target_ratio"))

    def test_shared_pool_amount_counted_once_with_comparable_goals(self):
        profile = {"conversion_lag_days": 2, "campaign_objectives": {"C1": {"goal_ids": ["p"]}, "C2": {"goal_ids": ["p"]}}}
        tables = {"campaigns": [camp("C1", shared="true", budget="B1"), camp("C2", shared="true", budget="B1")],
                  "budgets": [{"id": "B1", "amount": "100", "shared": "true", "campaign_ids": "C1;C2"}],
                  "campaign_metrics": [metric("C1", 1000, 20), metric("C2", 1000, 30)]}
        body = Case(self, tables, profile).run()
        d = obs(body, "shared_pool_achieved", budget="B1")[0]
        self.assertAlmostEqual(d["achieved_cpa"], 40)
        self.assertAlmostEqual(d["achieved_ratio"], 2.5)  # 100 once, not 200
        t = obs(body, "shared_pool_target", budget="B1")[0]
        self.assertAlmostEqual(t["target_ratio"], 2.5)
        # mixed goals and targets → pool ratios unavailable, per-member targets descriptive
        profile["campaign_objectives"]["C2"]["goal_ids"] = ["lead"]
        tables["campaigns"][1]["target_cpa"] = "60"
        body = Case(self, tables, profile).run()
        self.assertIn(("ratio_unavailable", "Info", "C1", "pool_achieved_ratio"), keys(body))
        self.assertIn(("ratio_unavailable", "Info", "C1", "pool_target_ratio"), keys(body))

    def test_shared_without_membership_or_lifetime_budget_is_unavailable(self):
        body = Case(self, {"campaigns": [camp("C1", shared="true")], "campaign_metrics": [metric("C1")]}).run()
        self.assertIn(("ratio_unavailable", "Info", "C1", "budget_scope"), keys(body))
        body = Case(self, {"campaigns": [camp("C1", budget="B1")], "campaign_metrics": [metric("C1")],
                           "budgets": [{"id": "B1", "amount": "3000", "period": "LIFETIME", "campaign_ids": "C1"}]}).run()
        self.assertIn(("ratio_unavailable", "Info", "C1", "budget_scope"), keys(body))
        self.assertEqual(obs(body, "standalone_ratios"), [])

    def test_zero_conversion_spend_needs_tracking_and_floor(self):
        verified = {"conversion_lag_days": 2, "campaign_objectives": {"C1": {"goal_ids": ["p"]}},
                    "tracking_verified": {"p": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30", "source_ref": "qa-1"}}}
        case = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", cost=120, conv=0)]}, verified)
        body = case.run()
        self.assertIn(("zero_conversion_spend", "Info", "C1", None), keys(body))
        rid = next(r["id"] for r in body["ai_review"])
        code, final = case.finalize([{"id": rid, "outcome": "relevance_concern", "rationale": "offer mismatch"}])
        self.assertEqual(code, 0)
        self.assertIn(("zero_conversion_spend", "Warning", "C1", None), keys(final))
        self.assertNotIn(("zero_conversion_spend", "Info", "C1", None), keys(final))
        # unknown tracking → partial; below spend_floor → nothing
        body = Case(self, {"campaigns": [camp("C1")], "campaign_metrics": [metric("C1", cost=120, conv=0)]}).run()
        self.assertNotIn("zero_conversion_spend", [f["condition_key"] for f in body["findings"]])
        self.assertEqual(cov(body, "zero_conversion_spend")["status"], "partial")
        body = Case(self, {"campaigns": [camp("C1", cpa="")], "campaign_metrics": [metric("C1", cost=30, conv=0)]}, verified).run()
        self.assertNotIn("zero_conversion_spend", [f["condition_key"] for f in body["findings"]])


if __name__ == "__main__":
    unittest.main()
