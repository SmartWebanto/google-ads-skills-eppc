"""test_check.py — skill-050 decision boundaries: HHI regimes, membership gaps, starvation gates, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-050-shared-budget-appropriateness-check/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check050", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check050"] = mod
_spec.loader.exec_module(mod)

START = date(2026, 8, 1)
DAYS = 10


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0]) if rows else ["id"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def build(root: Path, costs: dict, *, lag=2, snapshot="2026-08-20", limited=(), members=None, constraints=None,
          drop_member=None, conversions=None, extra=None) -> tuple[Path, Path]:
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    end = START + timedelta(days=DAYS - 1)
    members = members or sorted(costs)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": START.isoformat(),
                                 "date_range_end": end.isoformat(), "snapshot_date": snapshot,
                                 "conversion_lag_days": lag, "money_unit": "currency", "rates_format": "fraction"}])
    _write(ex / "budgets.csv", [{"budget_id": "b1", "amount": 100, "shared": "true", "campaign_ids": ";".join(members)}])
    _write(ex / "campaigns.csv", [{"id": m, "budget_id": "b1", "status": "ENABLED"} for m in members])
    _write(ex / "custom" / "budget_history.csv", [{"budget_id": "b1", "effective_from": START.isoformat(),
                                                   "effective_to": end.isoformat(), "amount": 100,
                                                   "member_campaign_ids": ";".join(members), "source_ref": "h"}])
    daily = []
    for i in range(DAYS):
        d = (START + timedelta(days=i)).isoformat()
        for m in members:
            if m == drop_member:
                continue
            daily.append({"budget_id": "b1", "campaign_id": m, "date": d, "cost": costs[m] / DAYS,
                          "impressions": 100, "clicks": 10, "conversions": (conversions or {}).get(m, 2),
                          "value": 50, "budget_lost_IS": 0.3 if m in limited else 0,
                          "budget_specific_reason": "NONE", "eligibility_status": "ELIGIBLE",
                          "goal_cohort": "purchase", "lag_mature": "true", "source_ref": "d"})
    _write(ex / "custom" / "shared_budget_daily.csv", daily)
    for name, rows in (extra or {}).items():
        _write(ex / name, rows)
    files = ["account.csv", "budgets.csv", "campaigns.csv", "custom/budget_history.csv",
             "custom/shared_budget_daily.csv"] + list(extra or {})
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"} for f in files])
    prof = {"campaign_objectives": {m: {"role": "sales", "goal_ids": ["p"]} for m in members}}
    if constraints:
        prof["budget_constraints"] = constraints
    p = root / "profile.json"
    p.write_text(json.dumps(prof))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    ctx = mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof)
    return ctx.finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def keys(body: dict) -> list[str]:
    return sorted(f["condition_key"] for f in body["findings"])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_equal_two_member_split_is_not_a_finding(self):
        body = run(*build(self.root, {"A": 500, "B": 500}))
        self.assertEqual(keys(body), [])
        obs = [o for o in body["observations"] if o["check"] == "concentration"][0]["data"]
        self.assertAlmostEqual(obs["hhi"], 0.5)
        self.assertAlmostEqual(obs["normalized_concentration"], 0.0)
        self.assertEqual(cov(body)["concentration"], "completed")

    def test_concentrated_pool_is_info_cue_only(self):
        body = run(*build(self.root, {"A": 950, "B": 50}))
        f = [x for x in body["findings"] if x["condition_key"] == "concentration_review_cue"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "Info")
        self.assertGreater(f[0]["evidence"]["normalized_concentration"], 0.5)

    def test_member_without_rows_blocks_concentration(self):
        body = run(*build(self.root, {"A": 950, "B": 50, "C": 0}, drop_member="C"))
        self.assertNotIn("concentration_review_cue", keys(body))
        self.assertEqual(cov(body)["concentration"], "partial")

    def test_zero_spend_pool_is_unavailable(self):
        body = run(*build(self.root, {"A": 0, "B": 0}))
        self.assertEqual(keys(body), [])
        texts = [o["text"] for o in body["observations"] if o["check"] == "concentration"]
        self.assertTrue(any("unavailable" in t for t in texts))

    def test_single_member_has_no_normalized_concentration(self):
        body = run(*build(self.root, {"A": 300}))
        obs = [o for o in body["observations"] if o["check"] == "concentration"][0]["data"]
        self.assertIsNone(obs["normalized_concentration"])
        self.assertEqual(keys(body), [])

    def test_constraint_without_limitation_is_not_starvation(self):
        body = run(*build(self.root, {"A": 900, "B": 100}, constraints={"b1": {"min_share": {"B": 0.3}}}))
        self.assertNotIn("budget_constrained_pool", keys(body))
        self.assertEqual([r for r in body["ai_review"] if r["check"] == "starvation_evidence"], [])

    def test_limited_pool_without_commitment_stays_info(self):
        body = run(*build(self.root, {"A": 900, "B": 100}, limited=("A",)))
        self.assertIn("budget_constrained_pool", keys(body))
        self.assertEqual(cov(body)["starvation_evidence"], "partial")
        self.assertFalse(any(o.get("severity") == "Warning" for r in body["ai_review"] for o in r["outcomes"].values()))

    def test_commitment_conflict_warning_requires_evidence_ref(self):
        ex, prof = build(self.root, {"A": 900, "B": 100}, limited=("A",), constraints={"b1": {"min_share": {"B": 0.3}}})
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                          ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        body = json.loads((out / "result.json").read_text())
        item = [r for r in body["ai_review"] if r["condition_key"] == "allocation_commitment_conflict"][0]
        self.assertEqual(item["evidence"]["below_equal_share_members"], ["B"])
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "commitment_conflict_corroborated",
                                    "rationale": "x", "proposal": {"campaign_id": "A"}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "commitment_conflict_corroborated", "rationale": "x",
                                    "proposal": {"campaign_id": "B", "evidence_ref": "crm-demand-2026-08"}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 0)
        final = json.loads((out / "final.json").read_text())
        sev = [f["severity"] for f in final["findings"] if f["condition_key"] == "allocation_commitment_conflict"]
        self.assertEqual(sev, ["Warning"])
        self.assertNotIn("budget_constrained_pool", [f["condition_key"] for f in final["findings"]])

    def test_immature_window_blocks_efficiency_comparison(self):
        body = run(*build(self.root, {"A": 500, "B": 500}, snapshot="2026-08-10", conversions={"A": 20, "B": 20}))
        self.assertEqual(cov(body)["cohort_efficiency"], "partial")
        obs = [o for o in body["observations"] if o["check"] == "cohort_efficiency"][0]["data"]
        self.assertEqual(obs["comparable_members"], [])

    def test_efficiency_needs_min_conversions_on_both_members(self):
        body = run(*build(self.root, {"A": 500, "B": 500}, conversions={"A": 2, "B": 0.5}))
        obs = [o for o in body["observations"] if o["check"] == "cohort_efficiency"][0]["data"]
        self.assertEqual(obs["comparable_members"], [])
        body = run(*build(self.root, {"A": 500, "B": 500}, conversions={"A": 2, "B": 2}))
        obs = [o for o in body["observations"] if o["check"] == "cohort_efficiency"][0]["data"]
        self.assertEqual(obs["comparable_members"], ["A", "B"])

    def test_non_shared_budget_is_not_applicable(self):
        ex, prof = build(self.root, {"A": 500, "B": 500})
        _write(ex / "budgets.csv", [{"budget_id": "b1", "amount": 100, "shared": "false", "campaign_ids": "A;B"}])
        body = run(ex, prof)
        self.assertEqual(cov(body)["concentration"], "not_applicable")

    def test_missing_response_model_is_skipped_not_passed(self):
        body = run(*build(self.root, {"A": 500, "B": 500}))
        self.assertEqual(cov(body)["separation_response"], "skipped")


if __name__ == "__main__":
    unittest.main()
