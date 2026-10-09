"""test_check.py — skill-058 demographic efficiency, gates and bounded modifier decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-058-demographic-performance-analysis/tests
rules:   stdlib only; temp folders; aggregate synthetic rows only; asserts decisions, not wording.
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
_spec = importlib.util.spec_from_file_location("check_058", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01", "date_range_end": "2026-08-28",
           "snapshot_date": "2026-09-05", "money_unit": "currency", "conversion_lag_days": "2"}
TRACKED = {"campaign_objectives": {"10": {"goal_ids": ["g1"]}},
           "tracking_verified": {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-28", "source_ref": "qa-1"}}}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(test, tables, profile=None, account=None) -> dict:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    exp = root / "export"
    tables = {"account": [account or ACCOUNT], **tables}
    for key, rows in tables.items():
        _write(exp / f"{key}.csv", rows)
    _write(exp / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
    (root / "profile.json").write_text(json.dumps(profile or {}))
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                        ["run", "--export", str(exp), "--profile", str(root / "profile.json"), "--out", str(root / "out")])
    test.assertEqual(code, 0)
    return json.loads((root / "out" / "result.json").read_text())


def seg(value, cost, conv, clicks=200, date="2026-08-10"):
    return {"campaign_id": "10", "ad_group_id": "20", "criterion_id": value, "date": date, "segment_value": value,
            "impressions": 5000, "clicks": clicks, "cost": cost, "conversions": conv, "conversion_value": conv * 40,
            "reporting_completeness": "complete"}


def control(segment, supported="true", current=1.0):
    return {"campaign_id": "10", "ad_group_id": "20", "dimension": "gender", "segment": segment, "criterion_id": segment,
            "control_type": "bid_modifier", "current_value": current, "permitted_min": 0.1, "permitted_max": 10,
            "supported": supported, "snapshot_date": "2026-09-05", "market": "IT", "source_url": "ui"}


def tables(gender, strategy="MANUAL_CPC", controls=None, **extra):
    t = {"campaigns": [{"id": "10", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": strategy}],
         "campaign_metrics": [{"campaign_id": "10", "cost": 1000, "clicks": 600, "conversions": 60}],
         "custom/demographic_gender": gender}
    if controls is not None:
        t["custom/demographic_controls"] = controls
    t.update(extra)
    return t


def conds(body, sev=None):
    return sorted((f["condition_key"], f["entity"].get("segment")) for f in body["findings"]
                  if sev is None or f["severity"] == sev)


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class DemographicTests(unittest.TestCase):
    def test_efficiency_warning_and_opportunity(self):
        body = run(self, tables([seg("MALE", 600, 20), seg("FEMALE", 400, 40)]))
        self.assertEqual(conds(body), [("high_efficiency_segment", "FEMALE"), ("low_efficiency_segment", "MALE")])
        self.assertEqual(conds(body, "Warning"), [("low_efficiency_segment", "MALE")])

    def test_exact_boundary_is_not_warning(self):
        body = run(self, tables([seg("MALE", 500, 35), seg("FEMALE", 500, 65)]))  # efficiency 0.7 / 1.3
        self.assertEqual(conds(body), [])

    def test_rest_side_must_pass_sample_gate(self):
        body = run(self, tables([seg("MALE", 600, 20), seg("FEMALE", 400, 14)]))
        self.assertEqual(conds(body), [("sparse_segments", None)])

    def test_unknown_segment_never_warning(self):
        body = run(self, tables([seg("UNDETERMINED", 600, 20), seg("FEMALE", 400, 40)]))
        self.assertEqual(conds(body, "Warning"), [])
        self.assertIn(("unknown_segment_low_efficiency", "UNDETERMINED"), conds(body, "Info"))

    def test_immature_window_is_descriptive_only(self):
        body = run(self, tables([seg("MALE", 600, 20), seg("FEMALE", 400, 40)]),
                   account=dict(ACCOUNT, snapshot_date="2026-08-29"))
        self.assertEqual([c for c in conds(body) if c[0] != "sparse_segments"], [])
        self.assertEqual(cov(body)["efficiency"], "partial")

    def test_zero_conversion_needs_tracking_evidence(self):
        g = [seg("MALE", 100, 0), seg("FEMALE", 900, 60)]
        body = run(self, tables(g))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(cov(body)["efficiency"], "partial")
        body = run(self, tables(g), TRACKED)
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["zero_conversion_segment"])
        self.assertIn(("zero_conversion_segment", "MALE"), conds(body, "Info"))

    def test_rows_outside_period_excluded(self):
        body = run(self, tables([seg("MALE", 600, 20), seg("FEMALE", 400, 40), seg("MALE", 5000, 0, date="2026-09-03")]))
        self.assertIn(("low_efficiency_segment", "MALE"), conds(body))
        self.assertEqual(cov(body)["reconcile"], "partial")

    def test_bounded_modifier_proposals(self):
        g = [seg("MALE", 600, 20), seg("FEMALE", 400, 40)]
        body = run(self, tables(g, controls=[control("MALE"), control("FEMALE", supported="false")]))
        obs = next(o for o in body["observations"] if o["check"] == "modifier_tests")["data"]
        self.assertEqual([(p["segment"], p["proposed"]) for p in obs["proposals"]], [("MALE", 0.9)])
        body = run(self, tables(g, strategy="TARGET_CPA", controls=[control("MALE")]))
        obs = next(o for o in body["observations"] if o["check"] == "modifier_tests")["data"]
        self.assertEqual(obs["proposals"], [])

    def test_policy_sensitivity_withholds_proposals(self):
        g = [seg("MALE", 600, 20), seg("FEMALE", 400, 40)]
        body = run(self, tables(g, controls=[control("MALE")]), {"policy_sensitive_categories": ["health"]})
        self.assertEqual(cov(body)["modifier_tests"], "not_applicable")
        self.assertIn(("policy_uncertainty", None), conds(body, "Info"))

    def test_missing_dimension_blocks_only_that_dimension(self):
        t = tables([seg("MALE", 600, 20), seg("FEMALE", 400, 40)])
        t["custom/demographic_age"] = t.pop("custom/demographic_gender")
        body = run(self, t)
        self.assertEqual(cov(body)["reconcile"], "partial")
        self.assertEqual(conds(body, "Warning"), [("low_efficiency_segment", "MALE")])
        self.assertEqual({f["entity"]["dimension"] for f in body["findings"]}, {"age"})


if __name__ == "__main__":
    unittest.main()
