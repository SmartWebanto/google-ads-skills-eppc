"""test_check.py — skill-065 QS component decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-065-quality-score-component-breakdown/tests
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
_spec = importlib.util.spec_from_file_location("check_065", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-28", "snapshot_date": "2026-09-05", "money_unit": "currency",
           "conversion_lag_days": "2"}
BA, AV = "BELOW_AVERAGE", "AVERAGE"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(test, tables: dict, profile: dict | None = None) -> dict:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    exp = root / "export"
    for key, rows in tables.items():
        _write(exp / f"{key}.csv", rows)
    _write(exp / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
    prof = root / "profile.json"
    prof.write_text(json.dumps(profile or {}))
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(M.SKILL, M.VERSION, M.run, None,
                        ["run", "--export", str(exp), "--profile", str(prof), "--out", str(root / "out")])
    test.assertEqual(code, 0)
    return json.loads((root / "out" / "result.json").read_text())


def tables(kws, metrics=True):
    """kws: (id, campaign_id, (ectr, rel, lp), cost)."""
    camps = sorted({k[1] for k in kws})
    t = {"account": [ACCOUNT],
         "campaigns": [{"id": c, "status": "ENABLED", "channel_type": "SEARCH"} for c in camps],
         "ad_groups": [{"id": "g" + c, "campaign_id": c, "status": "ENABLED"} for c in camps],
         "keywords": [{"id": i, "campaign_id": c, "ad_group_id": "g" + c, "status": "ENABLED", "quality_score": 5,
                       "expected_ctr": r[0], "ad_relevance": r[1], "landing_page_experience": r[2]} for i, c, r, _ in kws]}
    if metrics:
        t["keyword_metrics"] = [{"keyword_id": i, "campaign_id": c, "ad_group_id": "g" + c, "cost": cost}
                                for i, c, _, cost in kws]
    return t


def keys(body, sev=None):
    return sorted((f["condition_key"], json.dumps(f["entity"], sort_keys=True)) for f in body["findings"]
                  if sev is None or f["severity"] == sev)


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class QSComponentTests(unittest.TestCase):
    OVR = {"parameter_overrides": {"spend_high": 500}}

    def test_spend_high_boundary(self):
        body = run(self, tables([("1", "10", (BA, AV, AV), 500), ("2", "10", (BA, AV, AV), 499.99)]), self.OVR)
        warn = [f for f in body["findings"] if f["severity"] == "Warning"]
        self.assertEqual([f["entity"]["keyword_id"] for f in warn], ["1"])
        info = next(f for f in body["findings"] if f["condition_key"] == "below_average_below_priority")
        self.assertEqual([k["keyword_id"] for k in info["evidence"]["keywords"]], ["2"])

    def test_unresolved_spend_high_uses_only_proven_lower_bound(self):
        body = run(self, tables([("1", "10", (BA, AV, AV), 900), ("2", "10", (BA, AV, AV), 100)]))
        self.assertEqual(keys(body, "Warning"), [])
        self.assertEqual(cov(body)["high_spend_weak"], "partial")
        info = next(f for f in body["findings"] if f["condition_key"] == "below_average_below_priority")
        self.assertEqual([k["keyword_id"] for k in info["evidence"]["keywords"]], ["2"])

    def test_unavailable_component_is_not_below_average(self):
        body = run(self, tables([("1", "10", ("", "--", "UNKNOWN"), 5000)]), self.OVR)
        self.assertEqual(body["findings"], [])
        obs = next(o for o in body["observations"] if o["data"].get("component") == "expected_ctr")
        self.assertEqual(obs["data"]["denominator_rated"], 0)
        self.assertEqual(obs["data"]["counts"]["UNAVAILABLE"], 1)

    def test_union_spend_counts_each_keyword_once(self):
        body = run(self, tables([("1", "10", (BA, BA, BA), 100), ("2", "10", (AV, BA, AV), 50)]), self.OVR)
        u = next(o for o in body["observations"] if o["text"].startswith("Union spend"))
        self.assertEqual(u["data"]["union_cost"], 150)
        multi = next(f for f in body["findings"] if f["condition_key"] == "multiple_below_average")
        self.assertEqual([k["keyword_id"] for k in multi["evidence"]["keywords"]], ["1"])

    def test_widespread_needs_two_campaigns_over_half_and_material_exposure(self):
        kws = [("1", "10", (BA, AV, AV), 150), ("2", "10", (AV, AV, AV), 1),
               ("3", "11", (BA, AV, AV), 60), ("4", "11", (BA, AV, AV), 1), ("5", "11", (AV, AV, AV), 1)]
        # campaign 10 is exactly 50% → not >50%: no pattern
        self.assertEqual([k for k in keys(run(self, tables(kws), self.OVR)) if "widespread" in k[0]], [])
        kws[1] = ("2", "10", (BA, AV, AV), 1)
        body = run(self, tables(kws), self.OVR)
        wide = [f for f in body["findings"] if f["condition_key"] == "widespread_weak_component"]
        self.assertEqual(len(wide), 1)
        self.assertEqual(wide[0]["entity"]["component"], "expected_ctr")
        self.assertEqual(wide[0]["calculation"]["union_cost"], 212)
        low = [(i, c, r, 1) for i, c, r, _ in kws]
        self.assertEqual([k for k in keys(run(self, tables(low), self.OVR)) if "widespread" in k[0]], [])

    def test_missing_metrics_skips_spend_checks(self):
        body = run(self, tables([("1", "10", (BA, AV, AV), 900)], metrics=False), self.OVR)
        c = cov(body)
        self.assertEqual(c["high_spend_weak"], "skipped")
        self.assertEqual(c["widespread_pattern"], "skipped")
        self.assertEqual(c["component_counts"], "completed")
        self.assertEqual(keys(body, "Warning"), [])

    def test_routing_one_lead_per_keyword(self):
        body = run(self, tables([("1", "10", (AV, BA, BA), 1)]), self.OVR)
        r = next(o for o in body["observations"] if o["check"] == "investigation_routing")["data"]["routing"]
        self.assertEqual(r, [{"campaign_id": "10", "keyword_id": "1", "lead": "skill-068", "secondary": ["skill-069"]}])


if __name__ == "__main__":
    unittest.main()
