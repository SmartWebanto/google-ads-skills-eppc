"""test_check.py — decision-boundary tests for skill-136 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-136-geographic-competitive-intelligence/tests
rules:   Temp folders only; deterministic; no network.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | tests for this session's check changes
"""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill136_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

GEO, RB = "custom/geographic_daily", "external/regional_business"


def build(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def account(snapshot="2026-09-06"):
    return [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
             "date_range_start": "2026-08-03", "date_range_end": "2026-08-30", "snapshot_date": snapshot,
             "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]


CAMPAIGNS = [{"id": "C", "name": "C", "status": "ENABLED", "channel_type": "SEARCH",
              "bidding_strategy_type": "MANUAL_CPC"}]


def geo(loc="R1", cost=1000, clicks=500, conv=20, value=0, basis="user_location", region="R1", country="IT",
        unknown="false", d="2026-08-10"):
    return {"account_id": "c1", "campaign_id": "C", "date": d, "location_id": loc, "location_basis": basis,
            "location_name": loc, "country_id": country, "region_id": region, "device": "MOBILE",
            "network": "SEARCH", "impressions": "20000", "clicks": str(clicks), "cost": str(cost),
            "conversions": str(conv), "conversion_value": str(value), "goal_id": "g1",
            "unknown_location_flag": unknown}


def rb(loc="R1", avail="true", tol="cpa<=50", objective="leads", rng="2026-08-01..2026-12-31"):
    return {"campaign_id": "C", "location_id": loc, "effective_range": rng, "service_available": avail,
            "objective": objective, "capacity": "", "maximum_cpa_or_minimum_roas": tol,
            "margin_basis_if_used": "", "owner": "ops"}


class Case(unittest.TestCase):
    def run_check(self, geo_rows, rb_rows=None, snapshot="2026-09-06"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        tables = {"account": account(snapshot), "campaigns": CAMPAIGNS, GEO: geo_rows}
        if rb_rows:
            tables[RB] = rb_rows
        build(export, tables)
        prof = root / "profile.json"
        prof.write_text("{}")
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    @staticmethod
    def cov(body, cid):
        return next(c for c in body["coverage"] if c["check"] == cid)


class Prohibited(Case):
    def test_material_user_location_delivery_is_critical(self):
        body = self.run_check([geo(loc="R9", region="R9", cost=250)], [rb(loc="R9", avail="prohibited")])
        self.assertIn("prohibited_region_delivery", self.keys(body, "Critical"))

    def test_matched_location_cannot_prove_delivery(self):
        body = self.run_check([geo(loc="R9", region="R9", cost=250, basis="matched_location")],
                              [rb(loc="R9", avail="prohibited")])
        self.assertEqual(self.keys(body, "Critical"), [])
        self.assertEqual(self.cov(body, "prohibited_delivery")["status"], "partial")

    def test_non_material_is_info(self):
        body = self.run_check([geo(loc="R9", region="R9", cost=150)], [rb(loc="R9", avail="prohibited")])
        self.assertEqual(self.keys(body, "Critical"), [])
        self.assertIn("unavailable_region_delivery", self.keys(body, "Info"))

    def test_outside_effective_range_ignored(self):
        body = self.run_check([geo(loc="R9", region="R9", cost=250)],
                              [rb(loc="R9", avail="prohibited", rng="2026-09-01..2026-12-31")])
        self.assertNotIn("prohibited_region_delivery", self.keys(body))

    def test_unavailable_region_review_critical_needs_in_window_plan_ref(self):
        self.run_check([geo(loc="R9", region="R9", cost=250), geo(loc="R8", region="R8", cost=250)],
                       [rb(loc="R9", avail="false"), rb(loc="R8", avail="false"),
                        rb(loc="R9", avail="false", rng="2026-09-01..2026-12-31")])
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        body = json.loads((out / "result.json").read_text())
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "unavailable_region_delivery"
                   and r["entity"]["location_id"] == "R9")
        dec = out.parent / "d.json"

        def fin(proposal):
            dec.write_text(json.dumps([{"id": rid, "outcome": "prohibited_material", "rationale": "x",
                                        "proposal": proposal}]))
            return subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                  capture_output=True).returncode

        self.assertEqual(fin({}), 4)
        self.assertEqual(fin({"evidence_ref": "service_plan.pdf"}), 4)
        self.assertEqual(fin({"evidence_ref": f"{RB}:C:R8:2026-08-01..2026-12-31"}), 4)
        self.assertEqual(fin({"evidence_ref": f"{RB}:C:R9:2026-09-01..2026-12-31"}), 4)
        self.assertEqual(fin({"evidence_ref": f"{RB}:C:R9:2026-08-01..2026-12-31"}), 0)


class Efficiency(Case):
    def test_cpa_miss_is_warning_and_counterexample(self):
        body = self.run_check([geo(cost=2000, conv=20)], [rb()])
        self.assertIn("regional_efficiency_miss", self.keys(body, "Warning"))
        body = self.run_check([geo(cost=2000, conv=50)], [rb()])
        self.assertNotIn("regional_efficiency_miss", self.keys(body))

    def test_roas_tolerance(self):
        body = self.run_check([geo(cost=2000, conv=20, value=4000)], [rb(tol="roas>=4")])
        self.assertIn("regional_efficiency_miss", self.keys(body, "Warning"))

    def test_below_min_conversions_is_info(self):
        body = self.run_check([geo(cost=2000, conv=10)], [rb()])
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertIn("insufficient_regional_sample", self.keys(body, "Info"))

    def test_immature_window_no_warning(self):
        body = self.run_check([geo(cost=2000, conv=20)], [rb()], snapshot="2026-08-31")
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertEqual(self.cov(body, "regional_efficiency")["status"], "partial")

    def test_ambiguous_tolerance_not_used(self):
        body = self.run_check([geo(cost=2000, conv=20)], [rb(tol="50", objective="growth")])
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertEqual(self.cov(body, "regional_efficiency")["status"], "partial")

    def test_missing_business_plan_skips(self):
        body = self.run_check([geo(cost=2000, conv=20)])
        self.assertEqual(self.cov(body, "regional_efficiency")["status"], "skipped")
        self.assertIn(f"{RB} (file)", self.cov(body, "regional_efficiency")["missing"])


class Geography(Case):
    def test_parent_rows_not_double_counted(self):
        rows = [geo(loc="R1", cost=100), geo(loc="R2", region="R2", cost=100),
                geo(loc="IT", region="", country="IT", cost=200)]
        body = self.run_check(rows)
        [o] = [o for o in body["observations"] if o["check"] == "location_basis" and "totals" in o["text"]]
        self.assertEqual(o["data"]["cost"], 200)

    def test_unknown_geography_info(self):
        body = self.run_check([geo(), geo(loc="", region="", unknown="true", cost=80)])
        self.assertIn("unknown_geography", self.keys(body, "Info"))
        body = self.run_check([geo(), geo(loc="", region="", unknown="true", cost=10)])
        self.assertNotIn("unknown_geography", self.keys(body))


if __name__ == "__main__":
    unittest.main()
