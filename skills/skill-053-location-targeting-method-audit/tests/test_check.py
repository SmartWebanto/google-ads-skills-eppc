"""test_check.py — skill-053 boundaries: explicit intent, exclusions vs service area, certified empty targets, Critical.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-053-location-targeting-method-audit/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | Critical only via owner serving evidence
"""
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check053", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def _write(path: Path, rows: list[dict], cols=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


GEO_COLS = ["account_id", "campaign_id", "criterion_id", "criterion_type", "location_or_radius", "excluded",
            "positive_geo_target_type", "negative_geo_target_type", "source", "snapshot_date"]


def geo(cid, crit, name, excluded, method="PRESENCE"):
    return {"account_id": "c1", "campaign_id": cid, "criterion_id": crit, "criterion_type": "LOCATION",
            "location_or_radius": name, "excluded": excluded, "positive_geo_target_type": method,
            "negative_geo_target_type": "PRESENCE", "source": "ui", "snapshot_date": "2026-09-06"}


def build(root: Path, *, campaigns=None, objectives=None, service=("Italy",), geo_rows=None, geo_complete=True,
          impressions=None):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06",
                                 "conversion_lag_days": 2, "money_unit": "currency"}])
    _write(ex / "campaigns.csv", campaigns or [
        {"id": "A", "status": "ENABLED", "channel_type": "SEARCH", "geo_targets": "Italy",
         "geo_target_method": "PRESENCE_OR_INTEREST"}])
    ids = [c["id"] for c in (campaigns or [{"id": "A"}])]
    _write(ex / "campaign_metrics.csv", [{"campaign_id": c, "impressions": (impressions or {}).get(c, 1000),
                                          "cost": 100} for c in ids])
    files = ["account.csv", "campaigns.csv", "campaign_metrics.csv"]
    if geo_rows is not None:
        _write(ex / "custom" / "geo_targeting_methods.csv", geo_rows, GEO_COLS)
        files.append("custom/geo_targeting_methods.csv")
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete" if geo_complete or "geo" not in f
                                        else "partial", "truncation": "none"} for f in files])
    p = root / "profile.json"
    p.write_text(json.dumps({"service_area": list(service), "campaign_objectives": objectives or {}}))
    return ex, p


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def fnd(body, key):
    return [(f["entity"].get("campaign_id"), f["severity"]) for f in body["findings"] if f["condition_key"] == key]


def rev(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_explicit_local_intent_conflicts_with_interest(self):
        body = run(*build(self.root, objectives={"A": {"remote_buyers": False}}))
        self.assertEqual(fnd(body, "method_conflicts_intent"), [("A", "Warning")])

    def test_explicit_remote_intent_is_consistent_with_interest(self):
        body = run(*build(self.root, objectives={"A": {"remote_buyers": True}}))
        self.assertEqual(fnd(body, "method_conflicts_intent"), [])
        self.assertEqual(rev(body, "method_conflicts_intent"), [])

    def test_unknown_intent_goes_to_review_never_finding(self):
        body = run(*build(self.root))
        self.assertEqual(fnd(body, "method_conflicts_intent"), [])
        self.assertEqual(len(rev(body, "method_conflicts_intent")), 1)
        self.assertEqual(cov(body)["intent_fit"], "partial")

    def test_missing_service_area_blocks_fit_and_coverage(self):
        body = run(*build(self.root, service=()))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(cov(body)["intent_fit"], "partial")
        self.assertEqual(cov(body)["coverage_exclusions"], "partial")

    def test_excluding_a_served_area_is_warning(self):
        rows = [geo("A", "1", "Milan", "false"), geo("A", "2", "Italy", "true"), geo("A", "3", "Rome", "true")]
        body = run(*build(self.root, geo_rows=rows, service=("Italy", "Milan")))
        self.assertEqual(fnd(body, "exclusion_contradicts_coverage"), [("A", "Warning")])
        self.assertEqual(len(rev(body, "exclusion_contradicts_coverage")), 1)

    def test_all_locations_only_when_inventory_certified(self):
        camps = [{"id": "A", "status": "ENABLED", "channel_type": "SEARCH", "geo_targets": "",
                  "geo_target_method": "PRESENCE"},
                 {"id": "B", "status": "ENABLED", "channel_type": "SEARCH", "geo_targets": "",
                  "geo_target_method": "PRESENCE"}]
        rows = [geo("B", "1", "Italy", "false")]
        body = run(*build(self.root, campaigns=camps, geo_rows=rows))
        self.assertEqual([r["entity"]["campaign_id"] for r in rev(body, "targets_beyond_service_area")], ["A"])
        body = run(*build(self.root, campaigns=camps, geo_rows=rows, geo_complete=False))
        self.assertEqual(rev(body, "targets_beyond_service_area"), [])
        self.assertEqual(cov(body)["coverage_exclusions"], "partial")

    def test_target_beyond_service_area_is_review(self):
        camps = [{"id": "A", "status": "ENABLED", "channel_type": "SEARCH",
                  "geo_targets": "Italy;All countries and territories", "geo_target_method": "PRESENCE"}]
        body = run(*build(self.root, campaigns=camps))
        items = rev(body, "targets_beyond_service_area")
        self.assertEqual([x["name"] for x in items[0]["evidence"]["beyond_exact_match"]],
                         ["All countries and territories"])

    def test_full_contradiction_with_zero_delivery_needs_evidence_for_critical(self):
        rows = [geo("A", "1", "Italy", "false"), geo("A", "1", "Italy", "true")]
        ex, prof = build(self.root, geo_rows=rows, impressions={"A": 0})
        (ex / "external").mkdir(exist_ok=True)
        (ex / "external" / "owner_serving_evidence.csv").write_text(
            "evidence_ref,campaign_id,intended_from,intended_to,material_basis\n"
            "PLAN-7,A,2026-08-01,2026-08-31,always-on lead campaign\nOLD-1,A,2026-01-01,2026-02-01,x\n")
        body = run(ex, prof)
        self.assertEqual(fnd(body, "geo_contradiction_delivery_failure"), [("A", "Info")])  # cause/materiality unproven
        rid = rev(body, "geo_contradiction_delivery_failure")[0]["id"]
        out = self.root / "out"
        mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                     ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        for proposal, code, sev in (({}, 4, "Info"), ({"evidence_ref": "NOPE"}, 4, "Info"),
                                    ({"evidence_ref": "OLD-1"}, 4, "Info"), ({"evidence_ref": "PLAN-7"}, 0, "Critical")):
            (self.root / "d.json").write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced",
                                                           "rationale": "t", "proposal": proposal}]))
            got = mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                               ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out),
                                "--decisions", str(self.root / "d.json")])
            self.assertEqual(got, code)
            final = json.loads((out / "final.json").read_text())
            self.assertEqual([f["severity"] for f in final["findings"]
                              if f["condition_key"] == "geo_contradiction_delivery_failure"], [sev])
        body = run(*build(self.root, geo_rows=rows, impressions={"A": 500}))
        self.assertEqual(fnd(body, "geo_contradiction_delivery_failure"), [])
        self.assertEqual(len(rev(body, "contradictory_geo_settings")), 1)

    def test_same_objective_inconsistency_is_review(self):
        camps = [{"id": "A", "status": "ENABLED", "channel_type": "SEARCH", "geo_targets": "Italy",
                  "geo_target_method": "PRESENCE"},
                 {"id": "B", "status": "ENABLED", "channel_type": "SEARCH", "geo_targets": "Italy",
                  "geo_target_method": "PRESENCE_OR_INTEREST"},
                 {"id": "C", "status": "ENABLED", "channel_type": "SEARCH", "geo_targets": "Italy",
                  "geo_target_method": "PRESENCE_OR_INTEREST"}]
        objectives = {"A": {"role": "leads", "goal_ids": ["g"]}, "B": {"role": "leads", "goal_ids": ["g"]},
                      "C": {"role": "brand", "goal_ids": ["g"]}}
        body = run(*build(self.root, campaigns=camps, objectives=objectives))
        items = rev(body, "same_objective_method_inconsistency")
        self.assertEqual([sorted(i["evidence"]["methods"]) for i in items], [["A", "B"]])


if __name__ == "__main__":
    unittest.main()
