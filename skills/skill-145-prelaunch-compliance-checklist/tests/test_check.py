"""test_check.py — decision-boundary tests for skill-145 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-145-prelaunch-compliance-checklist/tests
rules:   Temp folders only; deterministic; no network.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | #114 copy_format boundaries
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
_spec = importlib.util.spec_from_file_location("skill145_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

LD, LE = "external/launch_drafts", "external/launch_evidence"
ACCOUNT = [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
            "date_range_start": "2026-08-04", "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06",
            "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]


def camp(method="PRESENCE", partners="false"):
    return [{"id": "N1", "name": "New", "status": "PAUSED", "channel_type": "SEARCH", "daily_budget": "50",
             "search_partners": partners, "display_network": "false", "geo_targets": "IT",
             "geo_target_method": method, "languages": "it"}]


def draft(version="2", copy="Cordless drills from 79 EUR", claims="", draft_id="D1"):
    return {"launch_id": "L1", "draft_id": draft_id, "version": version, "proposed_campaign_id": "N1",
            "ad_group_or_asset_group_id": "tmp-1", "ad_type": "RSA", "full_copy": copy, "assets_refs": "",
            "final_urls": "https://shop.example/drills", "product_or_service": "drills", "claims": claims,
            "target_markets": "IT", "languages": "it", "audiences": "", "network": "SEARCH",
            "launch_at": "2026-10-01", "owner": "pm"}


def ev(rid="R1", cls="restricted", status="met", market="IT", cert="", vt="", claim="", page="snap-1"):
    return {"launch_id": "L1", "draft_id": "D1", "requirement_id": rid,
            "official_policy_url": "https://support.google.com/adspolicy/x", "checked_at": "2026-09-01",
            "applicable_market": market, "applicable_product": "drills", "prohibited_or_restricted_or_editorial": cls,
            "claim_substantiation_ref": claim, "certification_or_authorization_ref": cert, "scope": "IT",
            "valid_from": "2026-01-01" if (cert or claim) else "", "valid_to": vt, "page_snapshot_ref": page,
            "technical_diagnostics_ref": "", "reviewer_role": "policy", "review_status": status}


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
    def run_check(self, drafts, evidence=None, profile=None, campaigns=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        tables = {"account": ACCOUNT, "campaigns": campaigns or camp(), LD: drafts}
        if evidence:
            tables[LE] = evidence
        build(export, tables)
        prof = root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    @staticmethod
    def readiness(body):
        return {o["data"]["draft_id"]: o["data"]["readiness"] for o in body["observations"] if o["check"] == "readiness"}


class Classes(Case):
    def test_prohibited_not_met_is_critical_restricted_is_warning(self):
        body = self.run_check([draft()], [ev(cls="prohibited", status="not_met")])
        self.assertIn("prohibited_content", self.keys(body, "Critical"))
        body = self.run_check([draft()], [ev(cls="restricted", status="not_met")])
        self.assertEqual(self.keys(body, "Critical"), [])
        self.assertIn("restricted_requirement_conflict", self.keys(body, "Warning"))
        self.assertEqual(self.readiness(body), {"D1": "changes_required"})

    def test_met_or_other_market_has_no_finding(self):
        body = self.run_check([draft()], [ev(cls="prohibited", status="met"),
                                          ev(rid="R2", cls="prohibited", status="not_met", market="DE")])
        self.assertEqual(self.keys(body), [])
        self.assertEqual(self.readiness(body), {"D1": "ready_for_owner_review"})

    def test_unresolved_status_is_info(self):
        body = self.run_check([draft()], [ev(status="awaiting legal")])
        self.assertIn("unresolved_policy_interpretation", self.keys(body, "Info"))
        self.assertEqual(self.readiness(body), {"D1": "evidence_incomplete"})

    def test_latest_version_frozen(self):
        body = self.run_check([draft(version="1", copy="OLD!!"), draft(version="2")], [ev()])
        pkg = next(o for o in body["observations"] if o["text"] == "Frozen package")["data"]
        self.assertEqual(pkg["package"], ["L1/D1@2"])
        self.assertNotIn("editorial_candidate", self.keys(body))


class ClaimsEditorial(Case):
    def test_claim_substantiation_boundary(self):
        body = self.run_check([draft(claims="best price in Italy")], [ev()])
        self.assertIn("claim_substantiation_missing", self.keys(body, "Info"))
        body = self.run_check([draft(claims="best price in Italy")], [ev(claim="study-1", vt="2026-09-15")])
        self.assertIn("claim_substantiation_missing", self.keys(body, "Info"))
        body = self.run_check([draft(claims="best price in Italy")], [ev(claim="study-1", vt="2026-12-31")])
        self.assertNotIn("claim_substantiation_missing", self.keys(body))

    def test_editorial_candidate_review_and_brand_exception(self):
        body = self.run_check([draft(copy="BEST drills!!")], [ev()])
        self.assertIn("editorial_candidate", self.keys(body, "Info"))
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["editorial_candidate"])
        body = self.run_check([draft(copy="ACME drills")], [ev()], profile={"brand_terms": ["acme"]})
        self.assertNotIn("editorial_candidate", self.keys(body))

    def test_missing_destination_evidence(self):
        body = self.run_check([draft()], [ev(page="")])
        self.assertIn("destination_evidence_missing", self.keys(body, "Info"))


class Authorization(Case):
    def test_validity_at_launch(self):
        body = self.run_check([draft()], [ev(cert="cert-1", vt="2026-09-20")])
        self.assertIn("authorization_invalid_at_launch", self.keys(body, "Warning"))
        body = self.run_check([draft()], [ev(cert="cert-1", vt="2026-12-31")])
        self.assertNotIn("authorization_invalid_at_launch", self.keys(body))

    def test_restricted_without_authorization_is_info(self):
        body = self.run_check([draft()], [ev()])
        self.assertIn("authorization_evidence_missing", self.keys(body, "Info"))


class Settings(Case):
    STD = {"launch_settings_standard": {"geo_target_method": "PRESENCE", "search_partners": False}}

    def test_standard_deviation_is_info_only(self):
        body = self.run_check([draft()], [ev()], profile=self.STD, campaigns=camp(method="PRESENCE_OR_INTEREST"))
        self.assertIn("launch_setting_deviation", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Warning"), [])

    def test_consistent_settings_no_finding(self):
        body = self.run_check([draft()], [ev()], profile=self.STD)
        self.assertNotIn("launch_setting_deviation", self.keys(body))

    def test_missing_evidence_file_is_incomplete(self):
        body = self.run_check([draft()])
        self.assertEqual(self.readiness(body), {"D1": "evidence_incomplete"})
        cov = next(c for c in body["coverage"] if c["check"] == "readiness")
        self.assertEqual(cov["status"], "partial")


def rsa(heads=("Cordless Drills", "Fast Delivery", "Top Brands"), descs=("Shop drills online.", "Free returns."),
        url="https://shop.example/drills", path1="drills", ad_type="RSA"):
    return {**draft(), "ad_type": ad_type, "headlines": json.dumps(list(heads)),
            "descriptions": " | ".join(descs), "path1": path1, "path2": "", "final_urls": url}


class CopyFormat(Case):
    OK = [ev(cls="prohibited", status="met")]

    def copy_keys(self, body):
        return sorted(f["condition_key"] for f in body["findings"] if f["check"] == "copy_format")

    def test_skipped_without_structured_copy_columns_keeps_readiness(self):
        body = self.run_check([draft()], self.OK)
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "copy_format")["status"], "skipped")
        self.assertEqual(self.readiness(body), {"D1": "ready_for_owner_review"})

    def test_valid_copy_is_met_and_fallback_rendered(self):
        body = self.run_check([rsa(heads=("Cordless Drills", "{KeyWord:Drills} Sale Today Only", "Top Brands"))],
                              self.OK)
        self.assertEqual(self.copy_keys(body), [])
        self.assertEqual(self.readiness(body), {"D1": "ready_for_owner_review"})

    def test_violations_are_warnings_and_require_changes(self):
        cases = [
            (rsa(heads=("x" * 31, "B", "C")), "copy_character_limit"),
            (rsa(heads=("{KeyWord:Professional Cordless Drill Sets}", "B", "C")), "copy_character_limit"),
            (rsa(heads=("日本語" * 6, "B", "C")), "copy_character_limit"),
            (rsa(path1="x" * 16), "copy_character_limit"),
            (rsa(heads=("A", "B")), "copy_count_limit"),
            (rsa(descs=()), "copy_count_limit"),
            (rsa(heads=("Drills", "Drills", "Saws")), "copy_duplicate_text"),
            (rsa(url="shop.example/drills"), "final_url_format"),
            (rsa(url="https://shop.example/{KeyWord:drills}"), "final_url_format"),
        ]
        for row, key in cases:
            body = self.run_check([row], self.OK)
            self.assertEqual(self.copy_keys(body), [key], row)
            self.assertEqual({f["severity"] for f in body["findings"] if f["check"] == "copy_format"}, {"Warning"})
            self.assertEqual(self.readiness(body), {"D1": "changes_required"}, row)
        body = self.run_check([rsa(descs=())], self.OK)
        f = next(x for x in body["findings"] if x["condition_key"] == "copy_count_limit")
        self.assertTrue(f["evidence"]["violations"][0]["required_field_missing"])

    def test_non_violations(self):
        body = self.run_check([rsa(heads=("Drills", "drills", "Saws"), url="http://shop.example/drills")], self.OK)
        self.assertEqual(self.copy_keys(body), [])
        obs = next(o for o in body["observations"] if o["check"] == "copy_format")
        self.assertEqual(obs["data"]["non_https_final_urls"], ["http://shop.example/drills"])

    def test_missing_copy_or_other_type_is_not_a_finding(self):
        body = self.run_check([rsa(heads=(), descs=())], self.OK)
        self.assertEqual(self.copy_keys(body), [])
        self.assertEqual(self.readiness(body), {"D1": "evidence_incomplete"})
        body = self.run_check([rsa(heads=("x" * 40,), ad_type="PMAX")], self.OK)
        self.assertEqual(self.copy_keys(body), [])
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "copy_format")["status"], "partial")


class Finalize(Case):
    def finalize(self, key, outcome, proposal):
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        if not (out / "result.json").exists():
            self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = next(r["id"] for r in json.loads((out / "result.json").read_text())["ai_review"]
                   if r["condition_key"] == key)
        dec = out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "x", "proposal": proposal}]))
        return subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)], capture_output=True).returncode

    def test_editorial_warning_needs_applicable_editorial_row_of_the_draft(self):
        other = {**ev(rid="E9", cls="editorial"), "draft_id": "D2", "official_policy_url": "https://p/d2"}
        self.run_check([draft(copy="BEST drills!!")],
                       [ev(), ev(rid="E1", cls="editorial"), {**ev(rid="E2", cls="editorial", market="FR"),
                                                              "official_policy_url": "https://p/fr"}, other])
        for ref in (None, "editorial policy", "R1", "E2", "https://p/fr", "E9", "https://p/d2"):
            self.assertEqual(self.finalize("editorial_candidate", "editorial_conflict",
                                           {"evidence_ref": ref} if ref else {}), 4, ref)
        self.assertEqual(self.finalize("editorial_candidate", "editorial_conflict", {"evidence_ref": "E1"}), 0)

    def test_scope_warning_needs_draft_authorization_valid_at_launch(self):
        d = {**draft(), "target_markets": "IT,FR"}
        self.run_check([d], [ev(rid="A1", cert="cert-1", vt="2026-12-31"),
                             ev(rid="A2", cert="cert-old", vt="2026-09-20"),
                             {**ev(rid="A9", cert="cert-d2", vt="2026-12-31"), "draft_id": "D2"}])
        for ref in ("scope doc", "cert-old", "cert-d2"):
            self.assertEqual(self.finalize("authorization_market_scope", "outside_required_authorization",
                                           {"evidence_ref": ref}), 4, ref)
        self.assertEqual(self.finalize("authorization_market_scope", "outside_required_authorization",
                                       {"evidence_ref": "cert-1"}), 0)


if __name__ == "__main__":
    unittest.main()
