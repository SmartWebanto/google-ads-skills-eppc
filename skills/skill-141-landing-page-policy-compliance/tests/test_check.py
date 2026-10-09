"""test_check.py — decision-boundary tests for skill-141 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-141-landing-page-policy-compliance/tests
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
_spec = importlib.util.spec_from_file_location("skill141_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

PE, PR, PS = "external/page_policy_evidence", "external/page_policy_requirements", "custom/page_policy_status"
ACCOUNT = [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
            "date_range_start": "2026-08-04", "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06",
            "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]
CAMPAIGNS = [{"id": "1", "name": "A", "status": "ENABLED"}, {"id": "2", "name": "B", "status": "PAUSED"}]
ADS = [{"id": "10", "campaign_id": "1", "ad_group_id": "100", "status": "ENABLED",
        "final_url": "https://Shop.example/offer/", "approval_status": "APPROVED", "policy_topics": ""},
       {"id": "20", "campaign_id": "2", "ad_group_id": "200", "status": "ENABLED",
        "final_url": "https://shop.example/old", "approval_status": "APPROVED", "policy_topics": ""}]


def page(url="https://shop.example/offer", status="200", tls="pass", mobile="pass", when="2026-09-05",
         data="email", privacy="snap-privacy-1", market="IT"):
    return {"final_url": url, "market": market, "device": "MOBILE", "captured_at": when,
            "page_snapshot_ref": "snap-1", "visible_business_identity": "Acme srl", "contact_details": "form",
            "privacy_link_and_text_ref": privacy, "data_collected": data, "offer_and_claim_text": "20% off",
            "http_status": status, "tls_result": tls, "mobile_task_result": mobile, "timing_metric": "LCP",
            "timing_value": "2.1", "test_method": "manual"}


def req(rid="R1", market="IT", reason="lead form collects personal data"):
    return {"requirement_id": rid, "market": market, "product": "leads", "use_case": "lead form",
            "official_policy_url": "https://support.google.com/adspolicy/answer/x", "checked_at": "2026-09-01",
            "requirement_text": "Disclose data use", "applicability_reason": reason,
            "authorization_or_certification_ref": "", "reviewer_role": "policy"}


def status(appr="DISAPPROVED", when="2026-09-05"):
    return {"account_id": "c1", "ad_id": "10", "policy_topic": "DESTINATION_NOT_WORKING", "snapshot_at": when,
            "campaign_id": "1", "approval_status": appr, "serving_limitation": "", "affected_url":
            "https://shop.example/offer", "review_status": "reviewed"}


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


class Case(unittest.TestCase):
    def run_check(self, **tables):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        names = {"pe": PE, "pr": PR, "ps": PS}
        build(export, {"account": ACCOUNT, "campaigns": CAMPAIGNS, "ads": ADS,
                       **{names[k]: v for k, v in tables.items()}})
        prof = root / "profile.json"
        prof.write_text("{}")
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    @staticmethod
    def reviews(body, key):
        return [r for r in body["ai_review"] if r["condition_key"] == key]


class Inventory(Case):
    def test_missing_evidence_for_active_url_only(self):
        body = self.run_check(pe=[page(url="https://other.example")])
        missing = [f["entity"]["final_url"] for f in body["findings"] if f["condition_key"] == "missing_page_evidence"]
        self.assertEqual(missing, ["https://shop.example/offer"])

    def test_normalized_url_join(self):
        body = self.run_check(pe=[page()])
        self.assertNotIn("missing_page_evidence", self.keys(body))


class Diagnostics(Case):
    def test_active_404_goes_to_review_not_deterministic_critical(self):
        body = self.run_check(pe=[page(status="404")])
        self.assertIn("destination_failure", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Critical"), [])
        self.assertEqual(len(self.reviews(body, "destination_failure")), 1)

    def test_superseded_failure_ignored(self):
        body = self.run_check(pe=[page(status="404", when="2026-09-01"), page(status="200", when="2026-09-05")])
        self.assertNotIn("destination_failure", self.keys(body))

    def test_inactive_url_failure_not_flagged(self):
        body = self.run_check(pe=[page(url="https://shop.example/old", status="500")])
        self.assertNotIn("destination_failure", self.keys(body))

    def test_tls_issue_is_technical_info(self):
        body = self.run_check(pe=[page(tls="expired certificate")])
        self.assertEqual(self.keys(body), ["tls_issue"])

    def test_critical_requires_evidence_ref(self):
        self.run_check(pe=[page(status="404")])
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = next(r["id"] for r in json.loads((out / "result.json").read_text())["ai_review"]
                   if r["condition_key"] == "destination_failure")
        dec = out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_destination_failure", "rationale": "x"}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_destination_failure", "rationale": "x",
                                    "proposal": {"evidence_ref": "serving.csv"}}]))
        self.assertEqual(subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)],
                                        capture_output=True).returncode, 0)


class Requirements(Case):
    def test_market_match_required(self):
        body = self.run_check(pe=[page()], pr=[req(), req("R2", market="DE")])
        items = self.reviews(body, "page_requirement_conflict")
        self.assertEqual([r["entity"]["requirement_id"] for r in items], ["R1"])
        self.assertEqual(items[0]["outcomes"]["conflicts_requirement"]["severity"], "Warning")
        self.assertEqual(self.keys(body, "Warning"), [])

    def test_requirement_without_applicability_not_applied(self):
        body = self.run_check(pe=[page()], pr=[req(reason="")])
        self.assertEqual(self.reviews(body, "page_requirement_conflict"), [])
        cov = next(c for c in body["coverage"] if c["check"] == "destination_inventory")
        self.assertEqual(cov["status"], "partial")

    def test_missing_privacy_evidence_is_info(self):
        body = self.run_check(pe=[page(privacy="")], pr=[req()])
        self.assertIn("missing_privacy_evidence", self.keys(body, "Info"))
        body = self.run_check(pe=[page(data="none collected", privacy="")], pr=[req()])
        self.assertNotIn("missing_privacy_evidence", self.keys(body))
        body = self.run_check(pe=[page(data="", privacy="")], pr=[req()])
        self.assertNotIn("missing_privacy_evidence", self.keys(body))


class Platform(Case):
    def test_disapproval_is_platform_reported_info_with_review(self):
        body = self.run_check(ps=[status()])
        self.assertIn("platform_reported_restriction", self.keys(body, "Info"))
        self.assertEqual(len(self.reviews(body, "platform_reported_restriction")), 1)

    def test_approved_latest_status_no_finding(self):
        body = self.run_check(ps=[status(when="2026-09-01"), status(appr="APPROVED", when="2026-09-05")])
        self.assertEqual(self.keys(body), [])


if __name__ == "__main__":
    unittest.main()
