"""test_check.py — skill-060 exclusive-cohort comparison and bounded modifier decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-060-in-market-custom-intent-layering/tests
rules:   stdlib only; temp folders; no network; asserts decisions, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial tests
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
_spec = importlib.util.spec_from_file_location("check_060", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01", "date_range_end": "2026-08-28",
           "snapshot_date": "2026-09-05", "money_unit": "currency", "conversion_lag_days": "2"}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Env:
    def __init__(self, test, tables, profile=None, account=None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exp = self.root / "export"
        tables = {"account": [account or ACCOUNT], **tables}
        for key, rows in tables.items():
            _write(self.exp / f"{key}.csv", rows)
        _write(self.exp / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        (self.root / "profile.json").write_text(json.dumps(profile or {}))

    def cli(self, cmd, *extra) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                            [cmd, "--export", str(self.exp), "--profile", str(self.root / "profile.json"),
                             "--out", str(self.root / "out"), *extra])

    def run(self) -> dict:
        assert self.cli("run") == 0
        return json.loads((self.root / "out" / "result.json").read_text())

    def finalize(self, decisions) -> int:
        p = self.root / "d.json"
        p.write_text(json.dumps(decisions))
        return self.cli("finalize", "--decisions", str(p))


def cohort(cid, cost, conv, value=None, resolved="true"):
    return {"campaign_id": "10", "ad_group_id": "20", "cohort_id": cid, "definition": f"cohort {cid}",
            "date": "2026-08-10", "impressions": 5000, "clicks": 300, "cost": cost, "conversions": conv,
            "conversion_value": value if value is not None else conv * 50, "assignment_method": "report split",
            "overlap_resolved": resolved}


def tables(cohorts, strategy="MANUAL_CPC", modifier="1.0", aud_type="IN_MARKET"):
    return {"campaigns": [{"id": "10", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": strategy}],
            "campaign_metrics": [{"campaign_id": "10", "cost": 1000, "conversions": 40}],
            "audiences": [{"list_id": "A1", "campaign_id": "10", "ad_group_id": "20", "mode": "OBSERVATION",
                           "type": aud_type, "status": "ENABLED", "bid_modifier": modifier}],
            "custom/audience_exclusive_cohorts": cohorts}


def conds(body):
    return sorted((f["condition_key"], f["entity"]["cohort_id"], f["severity"]) for f in body["findings"])


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class SegmentLayeringTests(unittest.TestCase):
    def test_cpa_ratio_boundaries(self):
        body = Env(self, tables([cohort("A", 600, 20, 1200), cohort("B", 400, 20, 800)])).run()  # CPA 1.5 exactly
        self.assertEqual([c for c in conds(body) if c[2] == "Warning"], [])
        body = Env(self, tables([cohort("A", 620, 20, 1240), cohort("B", 400, 20, 800)])).run()
        self.assertEqual(conds(body), [("adverse_exclusive_cohort", "A", "Warning"),
                                       ("opportunity_exclusive_cohort", "B", "Info")])

    def test_roas_ratio_adverse(self):
        body = Env(self, tables([cohort("A", 500, 20, value=600), cohort("B", 500, 20, value=1000)])).run()
        self.assertEqual(conds(body), [("adverse_exclusive_cohort", "A", "Warning")])

    def test_sample_gate_both_sides(self):
        body = Env(self, tables([cohort("A", 900, 20), cohort("B", 100, 14)])).run()
        self.assertEqual(conds(body), [])

    def test_unresolved_overlap_and_immaturity_block(self):
        body = Env(self, tables([cohort("A", 900, 20, resolved="false"), cohort("B", 300, 20)])).run()
        self.assertEqual(conds(body), [])
        self.assertEqual(cov(body)["exclusive_comparison"], "partial")
        acct = dict(ACCOUNT, conversion_lag_days="")
        body = Env(self, tables([cohort("A", 900, 20), cohort("B", 300, 20)]), account=acct).run()
        self.assertEqual(conds(body), [])
        self.assertEqual(cov(body)["exclusive_comparison"], "partial")

    def test_campaign_baseline_is_descriptive_only(self):
        t = tables([])
        del t["custom/audience_exclusive_cohorts"]
        t["custom/audience_segment_performance"] = [
            {"campaign_id": "10", "ad_group_id": "20", "audience_id": "A1", "criterion_id": "c1", "date": "2026-08-10",
             "mode": "OBSERVATION", "impressions": 100, "clicks": 50, "cost": 900, "conversions": 1,
             "conversion_value": 10, "audience_type": "IN_MARKET", "reporting_completeness": "complete"}]
        body = Env(self, t).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body)["modifier_tests"], "skipped")
        obs = next(o for o in body["observations"] if o["check"] == "descriptive_metrics")["data"]
        self.assertEqual(obs["cpa_vs_campaign_context"], 36)

    def test_modifier_proposal_verified(self):
        env = Env(self, tables([cohort("A", 620, 20), cohort("B", 400, 20)]))
        body = env.run()
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "bounded_modifier_test"
                   and r["entity"]["cohort_id"] == "B")
        dec = lambda m: [{"id": rid, "outcome": "propose_bounded_test", "rationale": "B is A1",
                          "proposal": {"campaign_id": "10", "audience_id": "A1", "multiplier": m}}]
        self.assertEqual(env.finalize(dec(1.2)), 4)   # beyond 1.1 × current
        self.assertEqual(env.finalize(dec(0.95)), 4)  # wrong direction (B is cheaper)
        self.assertEqual(env.finalize(dec(1.1)), 0)

    def test_modifier_rejected_without_current_value_or_manual_cpc(self):
        env = Env(self, tables([cohort("A", 620, 20), cohort("B", 400, 20)], modifier=""))
        rid = next(r["id"] for r in env.run()["ai_review"] if r["condition_key"] == "bounded_modifier_test")
        self.assertEqual(env.finalize([{"id": rid, "outcome": "propose_bounded_test", "rationale": "x",
                                        "proposal": {"campaign_id": "10", "audience_id": "A1", "multiplier": 1.0}}]), 4)
        body = Env(self, tables([cohort("A", 620, 20), cohort("B", 400, 20)], strategy="TARGET_CPA")).run()
        self.assertFalse(any(r["condition_key"] == "bounded_modifier_test" for r in body["ai_review"]))

    def test_intent_review_needs_definitions_and_profile(self):
        prof = {"business_type": "ecommerce", "objectives": ["sales"]}
        body = Env(self, tables([], aud_type="CUSTOM_AUDIENCE"), prof).run()
        self.assertFalse(any(r["condition_key"] == "segment_use_contradicts_intent" for r in body["ai_review"]))
        self.assertEqual(cov(body)["segment_inventory"], "partial")
        body = Env(self, tables([]), prof).run()
        self.assertTrue(any(r["condition_key"] == "segment_use_contradicts_intent" for r in body["ai_review"]))
        body = Env(self, tables([])).run()
        self.assertEqual(body["ai_review"], [])


if __name__ == "__main__":
    unittest.main()
