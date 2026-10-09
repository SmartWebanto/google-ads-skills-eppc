"""test_check.py — Decision-boundary tests for skill-123 MTD pacing, cap breach and bounded experiments.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-123-budget-pacing-daily-allocation-scripts/tests -t skills/skill-123-budget-pacing-daily-allocation-scripts
rules:   Temp folders only; pins pacing boundaries, cap materiality, shared-budget dedupe and verify, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_123", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

END, SNAP = date(2026, 9, 15), date(2026, 9, 16)
ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           f"1,A,EUR,Europe/Rome,2026-06-17,{END},{SNAP},fraction,currency,interaction_date,2\n")
CAMPS = "id,name,status\nC1,a,ENABLED\nC2,b,ENABLED\nC3,c,PAUSED\n"
HISTORY = ("budget_id,effective_from,effective_to,amount,currency,campaign_ids,change_ref\n"
           "B1,2026-01-01,,60,EUR,C1;C2,h1\nB2,2026-01-01,,70,EUR,C3,h2\n")


def cost(cid: str, d: date) -> float:
    return {"C1": 30.0, "C2": 20.0}.get(cid, 80.0 if d.weekday() >= 5 else 50.0)


def daily() -> str:
    out = ["campaign_id,date,budget_id,goal_id,cost,conversions,conversion_value"]
    d = date(2026, 6, 17)
    while d <= SNAP:  # SNAP row is the incomplete current day and must be ignored
        for cid, b in (("C1", "B1"), ("C2", "B1"), ("C3", "B2")):
            out.append(f"{cid},{d},{b},G1,{9999 if d == SNAP else cost(cid, d)},1,10")
        d += timedelta(days=1)
    return "\n".join(out) + "\n"


MTD = sum(cost(c, date(2026, 9, 1) + timedelta(days=i)) for i in range(15) for c in ("C1", "C2", "C3"))


def plan(b1=50.0, b2=50.0, cap=5000, assumptions="", start=1) -> str:
    out = ["plan_id,budget_id,date,monthly_cap_id,approved_monthly_cap,planned_daily_spend,goal_group,maximum_change,"
           "minimum_roas_or_maximum_cpa,marginal_response_assumptions,owner"]
    for day in range(start, 31):
        for b, v in (("B1", b1), ("B2", b2)):
            out.append(f"P1,{b},2026-09-{day:02d},CAP1,{cap},{v},G1,0.1,,{assumptions},finance lead")
    return "\n".join(out) + "\n"


class Env:
    def __init__(self, files: dict):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "export"
        files = {"account.csv": ACCOUNT, "campaigns.csv": CAMPS, **files}
        manifest = ["filename,completeness"]
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            manifest.append(f"{name},complete")
        (self.root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
        self.profile = Path(self.tmp.name) / "profile.yaml"
        self.profile.write_text("slug: t\n")
        self.out = Path(self.tmp.name) / "out"

    def body(self) -> dict:
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.root, self.profile).finish()

    def cli(self, cmd: str, decisions=None) -> int:
        argv = [cmd, "--export", str(self.root), "--profile", str(self.profile), "--out", str(self.out)]
        if decisions is not None:
            path = Path(self.tmp.name) / "decisions.json"
            path.write_text(json.dumps(decisions))
            argv += ["--decisions", str(path)]
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=argv)


def run(**files) -> dict:
    env = Env({k.replace("__", "/") + ".csv": v for k, v in files.items()})
    try:
        return env.body()
    finally:
        env.tmp.cleanup()


def keys(body, sev=None):
    return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))


class Pacing(unittest.TestCase):
    def test_on_plan_is_quiet_and_dedupes_shared_budget(self):
        planned = MTD / 15 / 2
        body = run(custom__allocation_daily=daily(), custom__budget_history=HISTORY,
                   external__allocation_plan=plan(planned, planned))
        self.assertNotIn("mtd_pacing_deviation", keys(body))
        obs = next(o["data"] for o in body["observations"] if o["text"] == "Cap CAP1: MTD pacing arithmetic")
        self.assertEqual(obs["actual_mtd_cost"], MTD)  # snapshot-day 9999 rows excluded; shared B1 counted once
        self.assertEqual(obs["remaining_planned_active_days"], 15)

    def test_overplan_warning_and_strict_underplan_boundary(self):
        body = run(custom__allocation_daily=daily(), external__allocation_plan=plan(MTD / 15 / 2 / 1.2, MTD / 15 / 2 / 1.2))
        self.assertEqual(keys(body, "Warning"), ["mtd_pacing_deviation"])
        exact = MTD / 15 / 0.8 / 2  # ratio exactly 0.80 → not below
        self.assertNotIn("mtd_pacing_deviation", keys(run(custom__allocation_daily=daily(),
                                                          external__allocation_plan=plan(exact, exact))))

    def test_zero_planned_to_date_is_unknown_not_deviation(self):
        body = run(custom__allocation_daily=daily(), external__allocation_plan=plan(start=20))
        self.assertNotIn("mtd_pacing_deviation", keys(body))
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "mtd_pacing")["status"], "partial")

    def test_missing_plan_skips_pacing(self):
        body = run(custom__allocation_daily=daily())
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "mtd_pacing")["status"], "skipped")
        self.assertEqual(keys(body, "Warning"), [])


class CapBreach(unittest.TestCase):
    def test_material_breach_is_critical(self):
        body = run(custom__allocation_daily=daily(), external__allocation_plan=plan(cap=MTD - 100))
        self.assertIn("approved_cap_breach", keys(body, "Critical"))

    def test_small_breach_needs_review_with_evidence(self):
        env = Env({"custom/allocation_daily.csv": daily(), "external/allocation_plan.csv": plan(cap=MTD - 10)})
        self.addCleanup(env.tmp.cleanup)
        self.assertEqual(env.cli("run"), 0)
        body = json.loads((env.out / "result.json").read_text())
        self.assertEqual(keys(body, "Critical"), [])
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "approved_cap_breach")
        bad = [{"id": rid, "outcome": "material_breach", "rationale": "client says so", "proposal": {}}]
        self.assertEqual(env.cli("finalize", bad), 4)
        good = [{**bad[0], "proposal": {"evidence_ref": "client cap policy v3"}}]
        self.assertEqual(env.cli("finalize", good), 0)
        final = json.loads((env.out / "final.json").read_text())
        self.assertIn("approved_cap_breach", keys(final, "Critical"))


class Weekday(unittest.TestCase):
    def test_pattern_without_assumptions_is_info(self):
        body = run(custom__allocation_daily=daily(), external__allocation_plan=plan())
        self.assertEqual(keys(body), ["weekday_pattern_without_assumptions"])

    def test_experiment_verify_bounds_and_envelope(self):
        env = Env({"custom/allocation_daily.csv": daily(), "external/allocation_plan.csv": plan(assumptions="a1")})
        self.addCleanup(env.tmp.cleanup)
        env.cli("run")
        body = json.loads((env.out / "result.json").read_text())
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "bounded_allocation_experiment")
        base = {"id": rid, "outcome": "propose_bounded_experiment", "rationale": "test"}
        too_big = {**base, "proposal": {"weekday_shifts": {"Mon": 0.2, "Sat": -0.2}, "monitoring": "m", "rollback": "r"}}
        self.assertEqual(env.cli("finalize", [too_big]), 4)
        grows = {**base, "proposal": {"weekday_shifts": {"Mon": 0.1}, "monitoring": "m", "rollback": "r"}}
        self.assertEqual(env.cli("finalize", [grows]), 4)
        ok = {**base, "proposal": {"weekday_shifts": {"Mon": 0.1, "Sat": -0.1}, "monitoring": "m", "rollback": "r"}}
        self.assertEqual(env.cli("finalize", [ok]), 0)

    def test_immature_days_and_missing_lag_block_cohorts(self):
        env = Env({"custom/allocation_daily.csv": daily()})
        self.addCleanup(env.tmp.cleanup)
        (env.root / "account.csv").write_text(ACCOUNT.replace("interaction_date,2", "interaction_date,"))
        body = env.body()
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "weekday_efficiency")["status"], "partial")
        self.assertEqual(keys(body), [])


if __name__ == "__main__":
    unittest.main()
