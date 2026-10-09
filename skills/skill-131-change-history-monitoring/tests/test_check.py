"""test_check.py — decision-boundary tests for skill-131 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-131-change-history-monitoring/tests
rules:   Temp folders only; deterministic; no network.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial tests
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
_spec = importlib.util.spec_from_file_location("skill131_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

CH, AUTH = "custom/change_history_fields", "external/change_authorizations"


def build(root: Path, tables: dict, manifest_extra: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none",
                         "period_start": "", "period_end": "", **manifest_extra.get(key, {})})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation", "period_start", "period_end"])
        w.writeheader()
        w.writerows(manifest)


ACCOUNT = [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
            "date_range_start": "2026-08-04", "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06",
            "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]
CAMPAIGNS = [{"id": "1", "name": "A", "status": "ENABLED", "budget_id": "B1"},
             {"id": "2", "name": "B", "status": "ENABLED", "budget_id": "B1"},
             {"id": "3", "name": "C", "status": "ENABLED", "budget_id": "B3"}]


def change(cid="X1", field="amount_micros", old="10000000", new="15000000", actor="u1", ref="AP1",
           camp="", budget="B1", ctype="GOOGLE_ADS_WEB_CLIENT", when="2026-08-20T10:00:00"):
    return {"account_id": "c1", "change_id": cid, "field_path": field, "occurred_at": when,
            "resource_name": f"customers/c1/campaignBudgets/{budget}" if budget else f"customers/c1/campaigns/{camp}",
            "campaign_id": camp, "budget_id": budget, "strategy_id": "", "operation": "UPDATE",
            "client_type": ctype, "actor_id": actor, "old_value": old, "new_value": new, "approval_ref": ref}


def auth(ref="AP1", field="amount_micros", scope="B1", actors="u1", new_c="<=20000000", valid_to="2026-12-31",
         status="approved"):
    return {"approval_ref": ref, "resource_scope": scope, "field": field, "permitted_actor_ids": actors,
            "permitted_source": "GOOGLE_ADS_WEB_CLIENT", "old_value_constraint": "any",
            "new_value_constraint": new_c, "valid_from": "2026-08-01", "valid_to": valid_to,
            "documented_at": "2026-07-30", "owner": "owner1", "review_status": status}


FULL = {CH: {"period_start": "2026-08-04", "period_end": "2026-09-02"}}


class Case(unittest.TestCase):
    def run_check(self, changes, auths=None, profile=None, manifest=FULL):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        tables = {"account": ACCOUNT, "campaigns": CAMPAIGNS, CH: changes}
        if auths:
            tables[AUTH] = auths
        build(export, tables, manifest)
        prof = root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    @staticmethod
    def obs(body, check):
        return [o for o in body["observations"] if o["check"] == check]


class Coverage(Case):
    def test_complete_covering_log_has_no_gap_finding(self):
        body = self.run_check([change(), change(field="name", old="a", new="b")], [auth(), auth(field="name", new_c="any")])
        self.assertNotIn("partial_change_log", self.keys(body))
        counts = next(o for o in self.obs(body, "log_coverage") if "counts" in o["text"])["data"]
        self.assertEqual((counts["distinct_change_ids"], counts["field_rows"]), (1, 2))

    def test_short_or_incomplete_log_is_info(self):
        for extra in ({CH: {"period_start": "2026-08-20", "period_end": "2026-09-02"}},
                      {CH: {"completeness": "partial", "period_start": "2026-08-04", "period_end": "2026-09-02"}}):
            body = self.run_check([change()], [auth()], manifest=extra)
            self.assertIn("partial_change_log", self.keys(body, "Info"))

    def test_shared_budget_listed_once_with_members(self):
        body = self.run_check([change()], [auth()])
        [o] = [o for o in self.obs(body, "resource_mapping") if "Shared budget" in o["text"]]
        self.assertEqual(o["data"]["member_campaign_ids"], ["1", "2"])

    def test_micros_delta(self):
        body = self.run_check([change()], [auth()])
        [o] = [o for o in self.obs(body, "value_ledger") if o["text"].startswith("Change X1")]
        self.assertEqual(o["data"]["delta"], 5)

    def test_missing_actor_is_unknown_source(self):
        body = self.run_check([change(actor="")], [auth()])
        self.assertIn("unknown_source", self.keys(body, "Info"))


class Authorization(Case):
    def test_no_reference_is_unknown_not_unauthorized(self):
        body = self.run_check([change(ref="")], [auth()])
        self.assertIn("missing_authorization", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Warning"), [])

    def test_compliant_change_has_no_finding(self):
        body = self.run_check([change()], [auth()])
        self.assertEqual(self.keys(body), [])

    def test_actor_or_value_violation_is_warning_with_critical_review(self):
        for ch in (change(actor="u9"), change(new="25000000"), change(when="2027-01-05T10:00:00")):
            body = self.run_check([ch], [auth()], manifest={CH: {"period_start": "2026-08-04",
                                                                 "period_end": "2027-01-31"}})
            self.assertIn("authorization_violation", self.keys(body, "Warning"))
            self.assertTrue(any(r["outcomes"].get("material_failure_evidenced", {}).get("severity") == "Critical"
                                for r in body["ai_review"]))

    def test_free_text_constraint_goes_to_review(self):
        body = self.run_check([change()], [auth(new_c="only during promo if stock ok")])
        self.assertIn("authorization_constraint_unclear", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertIn("violates_authorization", body["ai_review"][0]["outcomes"])

    def test_field_outside_register_goes_to_scope_review(self):
        body = self.run_check([change(field="delivery_method", old="STANDARD", new="ACCELERATED")], [auth()])
        self.assertIn("authorization_scope_unclear", self.keys(body, "Info"))

    def test_review_overdue_boundary(self):
        body = self.run_check([change(when="2026-08-10T10:00:00")], [auth(valid_to="2026-08-31", status="pending")])
        self.assertIn("authorization_review_overdue", self.keys(body, "Warning"))
        body = self.run_check([change()], [auth(valid_to="2026-12-31", status="pending")])
        self.assertNotIn("authorization_review_overdue", self.keys(body))


class RecognizedActors(Case):
    def test_skipped_without_profile_list(self):
        body = self.run_check([change(ref="")], [auth()])
        cov = next(c for c in body["coverage"] if c["check"] == "unrecognized_actors")
        self.assertEqual(cov["status"], "skipped")

    def test_unrecognized_actor_without_approval(self):
        prof = {"change_recognized_actors": ["u1"]}
        body = self.run_check([change(ref="", actor="intern")], [auth()], profile=prof)
        self.assertIn("unrecognized_actor_changes", self.keys(body, "Info"))
        body = self.run_check([change(ref="", actor="u1")], [auth()], profile=prof)
        self.assertNotIn("unrecognized_actor_changes", self.keys(body))


class Finalize(Case):
    def test_critical_needs_evidence_ref(self):
        self.run_check([change(actor="u9")], [auth()])
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = next(r["id"] for r in json.loads((out / "result.json").read_text())["ai_review"]
                   if r["condition_key"] == "authorization_violation_impact")
        dec = out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced", "rationale": "x"}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced", "rationale": "x",
                                    "proposal": {"evidence_ref": "delivery_report.csv"}}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
