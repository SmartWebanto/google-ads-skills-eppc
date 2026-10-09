"""test_check.py — Decision-boundary tests for skill-156 first-party permission gate and pipeline checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-156-first-party-data-collection-activation-strategy/tests
rules:   Temp folders only; manifest-complete synthetic evidence; assert conditions/severities, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_156", _CHECK)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,"
           "rates_format,money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-04,2026-09-02,2026-09-06,fraction,currency,interaction_date,{lag}\n")
PERM_H = ("source_id,list_id,market,intended_use,permission_status,consent_coverage_status,permitted_destinations,"
          "retention_limit_days,withdrawal_deletion_process_status,restricted_data_review,policy_eligibility,"
          "reviewed_at,reviewer_role,evidence_reference\n")
PERM_OK = "crm,,IT,customer_match,permitted,covered,111-222-3333,540,operational,passed,eligible,2026-08-01,DPO,ref-1\n"
ACT_H = ("source_id,destination_account_id,intended_use,pipeline_id,connection_status,eligibility,last_attempt_at,"
         "last_successful_refresh_at,source_updated_at,accepted_count,rejected_count,error_codes,"
         "permission_filter_status,withdrawal_deletion_sync_status,approved_refresh_SLA,source_reference\n")


def _act(conn="active", attempt="2026-09-05", success="2026-09-04", src="2026-09-05", sla="7d", filt="operational",
         wd="operational"):
    return (f"crm,111-222-3333,customer_match,p1,{conn},eligible,{attempt},{success},{src},900,100,,{filt},{wd},"
            f"{sla},log-1\n")


CAP_H = ("source_id,collection_point_id,market,window_start,window_end,eligible_unique_visitors_or_opportunities,"
         "denominator_definition,valid_unique_records,permitted_use_opt_in_count\n")
PLAN_H = ("source_id,intended_use,purpose,permitted_destination,necessary_data_categories,review_owner,approved_at,"
          "evidence_reference\n")


class Base(unittest.TestCase):
    def build(self, files: dict, lag: int = 2) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        files = {"account.csv": ACCOUNT.format(lag=lag), **files}
        rows = ["filename,completeness,truncation"] + [f"{n},complete,none" for n in sorted(files)]
        files["table_manifest.csv"] = "\n".join(rows) + "\n"
        for name, text in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.out = Path(tmp.name) / "out"
        return root

    def run_check(self, files: dict, lag: int = 2) -> dict:
        self.export = self.build(files, lag)
        with redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(self.export), "--out", str(self.out)])
        self.assertEqual(code, 0)
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions: list) -> tuple[int, dict]:
        path = self.out / "decisions.json"
        path.write_text(json.dumps(decisions))
        with redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.export), "--out", str(self.out), "--decisions", str(path)])
        return code, json.loads((self.out / "final.json").read_text())

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]


class PermissionGate(Base):
    def test_denied_and_unknown_block_but_permitted_passes(self):
        denied = "crm,,DE,customer_match,denied,covered,111-222-3333,540,operational,passed,eligible,2026-08-01,DPO,ref-2\n"
        unknown = "crm,,FR,customer_match,permitted,,111-222-3333,540,operational,passed,eligible,2026-08-01,DPO,ref-3\n"
        body = self.run_check({"external/activation_permissions.csv": PERM_H + PERM_OK + denied + unknown})
        blocked = {f["entity"]["market"]: f for f in self.found(body, "activation_blocked_pending_owner_review")}
        self.assertEqual(set(blocked), {"DE", "FR"})
        self.assertTrue(all(f["severity"] == "Info" for f in blocked.values()))
        self.assertIn("external/activation_permissions:consent_coverage_status",
                      blocked["FR"]["evidence"]["missing_evidence"])

    def test_future_review_date_is_not_permission(self):
        future = PERM_OK.replace("2026-08-01", "2026-12-01")
        body = self.run_check({"external/activation_permissions.csv": PERM_H + future})
        self.assertEqual(len(self.found(body, "activation_blocked_pending_owner_review")), 1)

    def test_missing_permissions_blocks_dependents_without_findings(self):
        body = self.run_check({"external/first_party_activation.csv": ACT_H + _act(success="2026-07-01"),
                               "external/first_party_use_plan.csv": PLAN_H +
                               "crm,customer_match,retention,111-222-3333,email,CRM lead,2026-08-01,plan-1\n"})
        self.assertEqual(self.cov(body, "permission_gate")["status"], "skipped")
        self.assertEqual(self.cov(body, "pipeline_health")["status"], "partial")
        self.assertEqual(self.found(body, "missed_refresh_sla"), [])
        self.assertEqual(body["ai_review"], [])

    def test_identifier_columns_are_reported(self):
        body = self.run_check({"external/first_party_sources.csv":
                               "source_id,business_segment,email\ncrm,retail,x\n"})
        self.assertTrue(any("customer-identifier" in e for e in body["errors"]))


class PipelineHealth(Base):
    def files(self, **kw):
        return {"external/activation_permissions.csv": PERM_H + PERM_OK,
                "external/first_party_activation.csv": ACT_H + _act(**kw)}

    def test_missed_sla_despite_recent_attempt(self):
        body = self.run_check(self.files(attempt="2026-09-05", success="2026-08-20"))
        f = self.found(body, "missed_refresh_sla")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertTrue(f[0]["evidence"]["attempt_after_last_success"])

    def test_fresh_pipeline_is_not_flagged(self):
        body = self.run_check(self.files(success="2026-09-01"))
        self.assertEqual(self.found(body, "missed_refresh_sla"), [])

    def test_sla_boundary_is_conservative(self):
        stale = self.run_check(self.files(success="2026-08-29"))  # 8 days before snapshot, SLA 7d
        self.assertEqual(len(self.found(stale, "missed_refresh_sla")), 1)
        edge = self.run_check(self.files(success="2026-08-30"))  # 7 days: undecidable at date granularity
        self.assertEqual(self.found(edge, "missed_refresh_sla"), [])

    def test_unitless_sla_is_partial_not_a_finding(self):
        body = self.run_check(self.files(success="2026-07-01", sla="7"))
        self.assertEqual(self.found(body, "missed_refresh_sla"), [])
        self.assertEqual(self.cov(body, "pipeline_health")["status"], "partial")

    def test_unchanged_source_is_not_stale(self):
        body = self.run_check(self.files(success="2026-08-01", src="2026-07-30"))
        self.assertEqual(self.found(body, "missed_refresh_sla"), [])

    def test_failed_connection_on_permitted_pipeline(self):
        body = self.run_check(self.files(conn="failed"))
        self.assertEqual([f["severity"] for f in self.found(body, "eligible_pipeline_failure")], ["Warning"])


class RestrictedUse(Base):
    def test_withdrawal_sync_failure_warning_and_critical_needs_evidence_ref(self):
        body = self.run_check({"external/activation_permissions.csv": PERM_H + PERM_OK,
                               "external/first_party_activation.csv": ACT_H + _act(wd="failed")})
        f = self.found(body, "active_use_contrary_to_restrictions")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "active_use_contrary_to_restrictions")
        code, final = self.finalize([{"id": rid, "outcome": "material_unsafe_use_evidenced", "rationale": "x"}])
        self.assertEqual(code, 4)
        self.assertEqual([x["severity"] for x in self.found(final, "active_use_contrary_to_restrictions")], ["Warning"])
        code, final = self.finalize([{"id": rid, "outcome": "material_unsafe_use_evidenced", "rationale": "x",
                                      "proposal": {"evidence_ref": "log-1 row 4"}}])
        self.assertEqual(code, 0)
        self.assertEqual([x["severity"] for x in self.found(final, "active_use_contrary_to_restrictions")], ["Critical"])

    def test_denied_permission_with_active_pipeline(self):
        denied = PERM_OK.replace(",permitted,", ",denied,")
        body = self.run_check({"external/activation_permissions.csv": PERM_H + denied,
                               "external/first_party_activation.csv": ACT_H + _act()})
        self.assertEqual(len(self.found(body, "active_use_contrary_to_restrictions")), 1)
        self.assertEqual(self.found(body, "missed_refresh_sla"), [])

    def test_unknown_permission_active_is_info_provisional(self):
        unknown = PERM_OK.replace(",covered,", ",,")
        body = self.run_check({"external/activation_permissions.csv": PERM_H + unknown,
                               "external/first_party_activation.csv": ACT_H + _act()})
        self.assertEqual(self.found(body, "active_use_contrary_to_restrictions"), [])
        self.assertEqual([f["severity"] for f in self.found(body, "active_use_permission_unknown")], ["Info"])

    def test_paused_pipeline_is_not_active_use(self):
        denied = PERM_OK.replace(",permitted,", ",denied,")
        body = self.run_check({"external/activation_permissions.csv": PERM_H + denied,
                               "external/first_party_activation.csv": ACT_H + _act(conn="paused", wd="failed")})
        self.assertEqual(self.found(body, "active_use_contrary_to_restrictions"), [])


class Capture(Base):
    def test_like_points_compared_only_when_both_meet_min_clicks(self):
        rows = ("crm,form_a,IT,2026-08-04,2026-09-02,1000,sessions on product pages,50,20\n"
                "crm,form_b,IT,2026-08-04,2026-09-02,1000,sessions on product pages,20,5\n")
        body = self.run_check({"external/first_party_capture.csv": CAP_H + rows})
        f = self.found(body, "capture_rate_gap_undiagnosed")
        self.assertEqual([(x["severity"], x["entity"]["collection_point_id"]) for x in f], [("Info", "form_b")])
        small = rows.replace("crm,form_b,IT,2026-08-04,2026-09-02,1000", "crm,form_b,IT,2026-08-04,2026-09-02,99")
        self.assertEqual(self.found(self.run_check({"external/first_party_capture.csv": CAP_H + small}),
                                    "capture_rate_gap_undiagnosed"), [])

    def test_zero_denominator_is_undefined_and_immature_is_partial(self):
        rows = ("crm,form_a,IT,2026-08-04,2026-09-02,0,sessions,0,0\n"
                "crm,form_b,IT,2026-08-04,2026-09-02,1000,sessions,20,5\n"
                "crm,form_c,IT,2026-08-04,2026-09-02,1000,sessions,40,5\n")
        body = self.run_check({"external/first_party_capture.csv": CAP_H + rows}, lag=10)
        obs = {o["data"]["collection_point_id"]: o["data"] for o in body["observations"]
               if o["check"] == "capture_rates" and "collection_point_id" in o["data"]}
        self.assertIsNone(obs["form_a"]["capture_rate"])
        self.assertEqual(self.found(body, "capture_rate_gap_undiagnosed"), [])
        self.assertEqual(self.cov(body, "capture_rates")["status"], "partial")


class Proposals(Base):
    def test_proposal_must_stay_inside_gate(self):
        plan = "crm,customer_match,retention,111-222-3333,email;purchase_value,CRM lead,2026-08-01,plan-1\n"
        body = self.run_check({"external/activation_permissions.csv": PERM_H + PERM_OK,
                               "external/first_party_use_plan.csv": PLAN_H + plan})
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "authorized_activation_opportunity")
        good = {"source_id": "crm", "intended_use": "customer_match", "destination": "111-222-3333",
                "data_categories": ["email"], "owner": "CRM lead", "measurement_method": "holdout"}
        code, _ = self.finalize([{"id": rid, "outcome": "authorized_opportunity", "rationale": "r",
                                  "proposal": {**good, "destination": "999-999-9999"}}])
        self.assertEqual(code, 4)
        code, final = self.finalize([{"id": rid, "outcome": "authorized_opportunity", "rationale": "r",
                                      "proposal": good}])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.found(final, "authorized_activation_opportunity")), 1)

    def test_blocked_use_gets_no_proposal_review(self):
        plan = "crm,customer_match,retention,111-222-3333,email,CRM lead,2026-08-01,plan-1\n"
        denied = PERM_OK.replace(",permitted,", ",denied,")
        body = self.run_check({"external/activation_permissions.csv": PERM_H + denied,
                               "external/first_party_use_plan.csv": PLAN_H + plan})
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "authorized_activation_opportunity"], [])


if __name__ == "__main__":
    unittest.main()
