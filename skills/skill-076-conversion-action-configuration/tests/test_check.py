"""test_check.py — decision boundaries of skill-076 conversion action configuration checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-076-conversion-action-configuration/tests -t skills/skill-076-conversion-action-configuration
rules:   Synthetic evidence only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_076", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def main(args) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(M.SKILL, M.VERSION, M.run, M.verify, args)


ACCOUNT = {"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
ACT_COLS = ["id", "conversion_customer_id", "name", "category", "status", "type", "counting", "primary_for_goal",
            "include_in_conversions", "value_settings", "attribution_model", "click_window_days",
            "data_driven_model_status"]
CAMP_COLS = ["id", "name", "status", "bidding_strategy_type", "strategy_id", "goal_ids"]


def _write(path: Path, rows, cols) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def action(aid, **kw):
    base = {"id": aid, "conversion_customer_id": "demo", "name": aid, "category": "LEAD", "status": "ENABLED",
            "type": "WEBSITE", "counting": "ONE_PER_CLICK", "primary_for_goal": "true", "include_in_conversions": "true",
            "value_settings": "15", "attribution_model": "DATA_DRIVEN", "click_window_days": "30",
            "data_driven_model_status": "AVAILABLE"}
    return {**base, **kw}


def camp(cid, strategy="MAXIMIZE_CONVERSIONS", goals="A"):
    return {"id": cid, "name": cid, "status": "ENABLED", "bidding_strategy_type": strategy, "strategy_id": "s1",
            "goal_ids": goals}


class ConversionConfigTests(unittest.TestCase):
    def make(self, actions, campaigns, profile=None, act_cols=ACT_COLS) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        exp = self.root / "export"
        _write(exp / "account.csv", [ACCOUNT], list(ACCOUNT))
        _write(exp / "conversion_actions.csv", actions, act_cols)
        files = ["account.csv", "conversion_actions.csv", "campaigns.csv", "campaign_metrics.csv",
                 "bidding_strategies.csv"]
        _write(exp / "table_manifest.csv", [{"filename": f, "completeness": "complete"} for f in files],
               ["filename", "completeness"])
        _write(exp / "campaigns.csv", campaigns, CAMP_COLS)
        _write(exp / "campaign_metrics.csv", [{"campaign_id": c["id"], "conversions": "5"} for c in campaigns],
               ["campaign_id", "conversions"])
        _write(exp / "bidding_strategies.csv", [{"id": "s1", "type": "X"}], ["id", "type"])
        prof = self.root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        return exp, prof

    def run_check(self, exp, prof) -> dict:
        out = self.root / "out"
        self.assertEqual(main(["run", "--export", str(exp), "--profile", str(prof), "--out", str(out)]), 0)
        return json.loads((out / "result.json").read_text())

    @staticmethod
    def found(body, sev=None):
        return sorted((f["condition_key"], f["entity"].get("action_id")) for f in body["findings"]
                      if sev is None or f["severity"] == sev)

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_declared_counting_conflict_warns_and_match_does_not(self):
        prof = {"campaign_objectives": {"C1": {"counting": "Every"}, "C2": {"counting": "Every"}}}
        body = self.run_check(*self.make([action("A", counting="ONE_PER_CLICK"), action("B", counting="EVERY")],
                                         [camp("C1", goals="A"), camp("C2", goals="B")], prof))
        self.assertEqual(self.found(body, "Warning"), [("counting_conflicts_intent", "A")])
        crit = [r for r in body["ai_review"] if r["condition_key"] == "counting_conflicts_intent"]
        self.assertEqual(len(crit), 1)
        self.assertEqual(body["counts"]["Critical"], 0)

    def test_every_lead_without_declared_intent_is_info_only(self):
        body = self.run_check(*self.make([action("A", counting="MANY_PER_CLICK")], [camp("C1")]))
        self.assertEqual(self.found(body), [("every_lead_intent_unconfirmed", "A")])
        self.assertEqual(body["counts"]["Warning"], 0)
        self.assertEqual(self.cov(body)["counting_intent"], "partial")

    def test_value_strategy_with_zero_value_warns_count_strategy_does_not(self):
        body = self.run_check(*self.make([action("A", value_settings="0"), action("B", value_settings="0")],
                                         [camp("V", "TARGET_ROAS", "A"), camp("N", "MAXIMIZE_CONVERSIONS", "B")]))
        self.assertEqual(self.found(body, "Warning"), [("value_strategy_without_value", "A")])

    def test_constant_value_on_value_strategy_goes_to_review(self):
        body = self.run_check(*self.make([action("A", value_settings="unit value 1")],
                                         [camp("V", "MAXIMIZE_CONVERSION_VALUE", "A")]))
        self.assertEqual(self.found(body, "Warning"), [])
        self.assertIn("value_signal_coherence", [r["condition_key"] for r in body["ai_review"]])

    def test_window_declared_conflict_and_cycle_review(self):
        prof = {"sales_cycle_days": 60, "campaign_objectives": {"C1": {"click_window_days": 90}}}
        body = self.run_check(*self.make([action("A", click_window_days="30"), action("B", click_window_days="30")],
                                         [camp("C1", goals="A"), camp("C2", goals="B")], prof))
        self.assertIn(("window_conflicts_intent", "A"), self.found(body, "Warning"))
        rev = [(r["condition_key"], r["entity"]["action_id"]) for r in body["ai_review"]]
        self.assertIn(("window_shorter_than_cycle", "B"), rev)

    def test_window_longer_than_cycle_is_not_flagged(self):
        body = self.run_check(*self.make([action("A")], [camp("C1")], {"sales_cycle_days": 7}))
        self.assertEqual([r for r in body["ai_review"] if r["check"] == "click_window"], [])
        self.assertEqual(self.cov(body)["click_window"], "completed")

    def test_low_volume_dda_is_never_flagged_last_click_is_info(self):
        body = self.run_check(*self.make([action("A"), action("B", attribution_model="LAST_CLICK")],
                                         [camp("C1", goals="A;B")]))
        self.assertEqual(self.found(body), [("non_dda_contextual_review", "B")])
        text = json.dumps(body["findings"]).lower()
        self.assertNotIn("ineligib", text)

    def test_unknown_goal_membership_is_partial_not_pass(self):
        body = self.run_check(*self.make([action("A", counting="EVERY")], [camp("C1", goals="")],
                                         {"campaign_objectives": {"C1": {"counting": "One"}}}))
        self.assertEqual(self.cov(body)["goal_inventory"], "partial")
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_missing_counting_column_skips_check(self):
        cols = [c for c in ACT_COLS if c != "counting"]
        body = self.run_check(*self.make([action("A")], [camp("C1")], act_cols=cols))
        self.assertEqual(self.cov(body)["counting_intent"], "skipped")

    def test_finalize_critical_requires_evidence_ref(self):
        prof = {"campaign_objectives": {"C1": {"counting": "Every"}}}
        exp, p = self.make([action("A")], [camp("C1")], prof)
        body = self.run_check(exp, p)
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "counting_conflicts_intent")
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(exp), "--profile", str(p), "--out", str(self.root / "out"),
                "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced", "rationale": "r"}]))
        self.assertEqual(main(args), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced", "rationale": "r",
                                    "proposal": {"evidence_ref": "skill-071 reconciliation R1"}}]))
        self.assertEqual(main(args), 0)
        final = json.loads((self.root / "out" / "final.json").read_text())
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
