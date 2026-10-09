"""test_check.py — decision boundaries of skill-044 scripts/check.py (cutoff, pacing, forecasts, cap breach).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-044-monthly-budget-pacing-analysis/tests
rules:   Temp folders only; stdlib only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | material_breach ref must be the scope/month cap row
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

_SPEC = importlib.util.spec_from_file_location("skill044_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
M = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = M
_SPEC.loader.exec_module(M)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-09-01",
           "date_range_end": "2026-09-15", "snapshot_date": "2026-09-16", "conversion_lag_days": "2",
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
    def __init__(self, test: unittest.TestCase, tables: dict, profile: dict | None = None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        tables = {"account": [ACCOUNT], **tables}
        for key, rows in tables.items():
            _write(self.export, key, rows)
        _write(self.export, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(profile or {"conversion_lag_days": 2, "reporting_end_date": "2026-09-16"}))
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
    return sorted((f["condition_key"], f["severity"], f["entity"].get("scope_id")) for f in body["findings"])


def obs(body, check):
    return [o["data"] for o in body["observations"] if o["check"] == check]


def daily(campaigns=("C1", "C2"), cost=50, start=date(2026, 8, 25), end=date(2026, 9, 16), billed=False, budget="B1"):
    rows = []
    d = start
    while d <= end:
        for c in campaigns:
            r = {"campaign_id": c, "date": d.isoformat(), "budget_id": budget if c != "C3" else "B9", "cost": cost,
                 "currency": "EUR", "complete_day": "false" if d == date(2026, 9, 16) else "true"}
            if billed:
                r["billed_cost_if_available"] = cost
            rows.append(r)
        d += timedelta(days=1)
    return rows


def plan(total, kind="cap", basis="cost", scope=("account", ""), daily_weights=None):
    base = {"scope_type": scope[0], "scope_id": scope[1], "month": "2026-09", "approved_month_total": total,
            "cap_or_target": kind, "spend_basis": basis, "currency": "EUR", "owner": "cfo", "approved_at": "2026-08-20",
            "source_ref": "plan-9"}
    if not daily_weights:
        return [{**base, "date": "", "planned_spend": ""}]
    return [{**base, "date": (date(2026, 9, 1) + timedelta(days=i)).isoformat(), "planned_spend": daily_weights}
            for i in range(30)]


class MonthlyPacingTests(unittest.TestCase):
    def test_cutoff_excludes_partial_day_and_sums_all_campaigns(self):
        body = Case(self, {"custom/monthly_spend_daily": daily()}).run()
        cut = obs(body, "reporting_cutoff")[0]
        self.assertEqual(cut["cutoff"], "2026-09-15")
        self.assertEqual(cut["provisional_spend"], 100)
        self.assertEqual(obs(body, "mtd_spend")[0]["cost"], 1500)
        self.assertEqual(cov(body, "pacing")["status"], "skipped")  # no plan → no pacing pass

    def test_uniform_fallback_pacing_inside_band_is_not_flagged(self):
        body = Case(self, {"custom/monthly_spend_daily": daily(), "external/monthly_budget_plan": plan(3000)}).run()
        self.assertEqual(body["findings"], [])
        p = obs(body, "pacing")[0]
        self.assertAlmostEqual(p["pacing"], 1.0)
        self.assertIn("ASSUMPTION", p["expected_source"])

    def test_over_pacing_against_daily_plan_is_reviewed(self):
        case = Case(self, {"custom/monthly_spend_daily": daily(),
                           "external/monthly_budget_plan": plan(4000, kind="target", daily_weights=60)})
        body = case.run()
        self.assertEqual(keys(body), [("pacing_outside_band", "Info", "account")])
        self.assertAlmostEqual(body["findings"][0]["calculation"]["E"], 900)
        rid = body["ai_review"][0]["id"]
        code, final = case.finalize([{"id": rid, "outcome": "unintentional_deviation", "rationale": "no event planned"}])
        self.assertEqual(code, 0)
        self.assertEqual(keys(final), [("pacing_deviation", "Warning", "account")])

    def test_material_cap_breach_is_critical(self):
        body = Case(self, {"custom/monthly_spend_daily": daily(), "external/monthly_budget_plan": plan(1300)}).run()
        self.assertIn(("approved_cap_exceeded", "Critical", "account"), keys(body))
        f = next(f for f in body["findings"] if f["severity"] == "Critical")
        self.assertEqual(f["evidence"]["excess"], 200)

    def test_small_overage_needs_evidenced_review_for_critical(self):
        rows = plan(1450) + [dict(plan(1450)[0], month="2026-08", source_ref="plan-8"),
                             dict(plan(900, scope=("budget", "B7"))[0], source_ref="plan-b7")]
        case = Case(self, {"custom/monthly_spend_daily": daily(), "external/monthly_budget_plan": rows})
        body = case.run()
        self.assertIn(("approved_cap_exceeded", "Info", "account"), keys(body))
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "approved_cap_exceeded"
                   and r["entity"]["scope_type"] == "account")
        code, _ = case.finalize([{"id": rid, "outcome": "material_breach", "rationale": "r"}])
        self.assertEqual(code, 4)
        for foreign in ("billing-2026-09", "plan-8", "plan-b7"):  # unknown, other month, other scope
            code, _ = case.finalize([{"id": rid, "outcome": "material_breach", "rationale": "r",
                                      "proposal": {"evidence_ref": foreign}}])
            self.assertEqual(code, 4, foreign)
        code, final = case.finalize([{"id": rid, "outcome": "material_breach", "rationale": "r",
                                      "proposal": {"evidence_ref": "plan-9"}}])
        self.assertEqual(code, 0)
        self.assertIn(("approved_cap_exceeded", "Critical", "account"), keys(final))

    def test_billed_basis_without_billed_cost_blocks_cap_claim(self):
        body = Case(self, {"custom/monthly_spend_daily": daily(), "external/monthly_budget_plan": plan(1300, basis="billed")}).run()
        self.assertNotIn("approved_cap_exceeded", [f["condition_key"] for f in body["findings"]])
        self.assertEqual(cov(body, "cap_breach")["status"], "partial")
        body = Case(self, {"custom/monthly_spend_daily": daily(billed=True),
                           "external/monthly_budget_plan": plan(1300, basis="billed")}).run()
        self.assertIn(("approved_cap_exceeded", "Critical", "account"), keys(body))

    def test_month_gap_or_duplicate_blocks_mtd(self):
        rows = [r for r in daily() if r["date"] != "2026-09-03"]
        body = Case(self, {"custom/monthly_spend_daily": rows, "external/monthly_budget_plan": plan(1300)}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "reporting_cutoff")["status"], "partial")
        rows = daily() + [daily()[20]]
        body = Case(self, {"custom/monthly_spend_daily": rows, "external/monthly_budget_plan": plan(1300)}).run()
        self.assertEqual(body["findings"], [])
        self.assertIsNone(obs(body, "mtd_spend")[0]["cost"])

    def test_forecast_cap_risk_with_depletion_date(self):
        body = Case(self, {"custom/monthly_spend_daily": daily(), "external/monthly_budget_plan": plan(2800)}).run()
        self.assertEqual(keys(body), [("forecast_cap_risk", "Info", "account")])
        self.assertEqual(body["findings"][0]["evidence"]["projected_depletion_date"], "2026-09-28")
        self.assertAlmostEqual(body["findings"][0]["evidence"]["linear"], 3000)

    def test_pool_scope_counts_only_pool_members(self):
        tables = {"custom/monthly_spend_daily": daily(campaigns=("C1", "C2", "C3")),
                  "external/monthly_budget_plan": plan(1000, scope=("budget", "B1"))}
        body = Case(self, tables).run()
        self.assertIn(("approved_cap_exceeded", "Critical", "B1"), keys(body))
        f = next(f for f in body["findings"] if f["condition_key"] == "approved_cap_exceeded")
        self.assertEqual(f["evidence"]["actual"], 1500)  # C3 on budget B9 excluded

    def test_profile_budget_without_plan_is_info_only(self):
        profile = {"conversion_lag_days": 2, "reporting_end_date": "2026-09-16", "monthly_budget": 1400}
        body = Case(self, {"custom/monthly_spend_daily": daily()}, profile).run()
        self.assertIn(("profile_cap_exceeded_basis_unverified", "Info", "account"), keys(body))
        self.assertNotIn("Critical", [f["severity"] for f in body["findings"]])


if __name__ == "__main__":
    unittest.main()
