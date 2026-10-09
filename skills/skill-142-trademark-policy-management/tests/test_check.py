"""test_check.py — decision-boundary tests for skill-142 check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-142-trademark-policy-management/tests
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
_spec = importlib.util.spec_from_file_location("skill142_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

TR, PS = "external/trademark_register", "custom/trademark_policy_status"
ACCOUNT = [{"customer_id": "c1", "name": "T", "currency_code": "EUR", "time_zone": "Europe/Rome",
            "date_range_start": "2026-08-04", "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06",
            "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": "2"}]
CAMPAIGNS = [{"id": "1", "name": "A", "status": "ENABLED", "geo_targets": "Italy"}]


def ad(aid="10", head="Bosch drills in stock", url="https://shop.example/drills", gid="100"):
    return {"id": aid, "campaign_id": "1", "ad_group_id": gid, "status": "ENABLED", "headlines": head,
            "descriptions": "Fast delivery", "final_url": url, "approval_status": "APPROVED", "policy_topics": ""}


def reg(term="bosch", accounts="c1", valid_to="", status="approved", use="ad text", rel="reseller", doc="doc-1"):
    return {"trademark_id": "T1", "market": "IT", "authorization_id": "A1", "term": term, "owner": "Bosch",
            "advertiser_relationship": rel, "permitted_use": use, "permitted_accounts": accounts,
            "permitted_markets": "IT", "supporting_document_ref": doc, "valid_from": "2026-01-01",
            "valid_to_if_documented": valid_to, "request_id": "RQ1", "request_status": status,
            "reviewed_at": "2026-02-01", "legal_owner": "legal"}


def ps(aid, gid="100", appr="DISAPPROVED"):
    return {"account_id": "c1", "ad_id": aid, "topic": "TRADEMARKS_IN_AD_TEXT", "snapshot_at": "2026-09-05",
            "campaign_id": "1", "ad_group_id": gid, "approval_status": appr, "serving_status": "",
            "limitation": "", "request_id_if_known": ""}


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
    def run_check(self, ads, register=None, status=None, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        tables = {"account": ACCOUNT, "campaigns": CAMPAIGNS, "ads": ads}
        if register:
            tables[TR] = register
        if status:
            tables[PS] = status
        build(export, tables)
        prof = root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        self.paths = (export, prof, root / "out")
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))


class Scope(Case):
    def test_valid_authorization_goes_to_context_review_only(self):
        body = self.run_check([ad()], [reg()])
        self.assertEqual(self.keys(body), ["context_dependent_mention"])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["authorization_scope"])

    def test_explicit_conflicts_are_warnings(self):
        for r in (reg(accounts="c9"), reg(valid_to="2026-08-15"), reg(status="denied"), reg(use="keyword")):
            body = self.run_check([ad()], [r])
            self.assertIn("use_conflicts_authorization", self.keys(body, "Warning"), r)

    def test_future_expiry_is_not_a_conflict(self):
        body = self.run_check([ad()], [reg(valid_to="2026-12-31")])
        self.assertNotIn("use_conflicts_authorization", self.keys(body))

    def test_free_text_permitted_use_is_review(self):
        body = self.run_check([ad()], [reg(use="per reseller agreement")])
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertTrue(body["ai_review"][0]["evidence"]["permitted_use_undecidable"])

    def test_pending_without_document_is_info(self):
        body = self.run_check([ad()], [reg(status="pending", doc="")])
        self.assertEqual(self.keys(body), ["pending_or_unknown_permission"])

    def test_own_mark_not_flagged(self):
        body = self.run_check([ad()], [reg(rel="owner")])
        self.assertEqual(self.keys(body), [])


class Usage(Case):
    def test_whole_word_matching(self):
        body = self.run_check([ad(head="Boschetto garden chairs")], [reg()])
        self.assertEqual(self.keys(body), [])

    def test_url_use_detected(self):
        body = self.run_check([ad(head="Drills", url="https://bosch-drills.example/")], [reg(use="ad text")])
        self.assertIn("use_conflicts_authorization", self.keys(body, "Warning"))
        self.assertEqual(body["findings"][0]["entity"]["use_type"], "url")

    def test_unregistered_profile_term_is_unknown_permission(self):
        body = self.run_check([ad(head="Better than Makita")], [reg()], profile={"competitor_terms": ["makita"]})
        self.assertIn("unknown_permission", self.keys(body, "Info"))

    def test_missing_register_skips(self):
        body = self.run_check([ad()])
        cov = next(c for c in body["coverage"] if c["check"] == "term_usage")
        self.assertEqual(cov["status"], "skipped")


class Policy(Case):
    def test_block_only_when_no_other_eligible_ad(self):
        ads = [ad("10"), ad("11", head="Drills")]
        body = self.run_check(ads, [reg()], [ps("10"), ps("11", appr="APPROVED")])
        self.assertNotIn("ad_group_trademark_block", self.keys(body))
        body = self.run_check(ads, [reg()], [ps("10"), ps("11")])
        self.assertIn("ad_group_trademark_block", self.keys(body, "Info"))
        self.assertEqual(self.keys(body, "Critical"), [])


class Finalize(Case):
    def test_scope_conflict_needs_register_ref(self):
        self.run_check([ad()], [reg()])
        export, prof, out = self.paths
        base = [sys.executable, str(SCRIPT)]
        args = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run(base + ["run"] + args, capture_output=True).returncode, 0)
        rid = json.loads((out / "result.json").read_text())["ai_review"][0]["id"]
        dec = out.parent / "d.json"

        def fin(proposal):
            dec.write_text(json.dumps([{"id": rid, "outcome": "conflicts_authorization_scope", "rationale": "x",
                                        "proposal": proposal}]))
            return subprocess.run(base + ["finalize"] + args + ["--decisions", str(dec)], capture_output=True).returncode

        self.assertEqual(fin({"register_ref": "ZZ"}), 4)
        self.assertEqual(fin({"register_ref": "A1"}), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual(final["counts"]["Warning"], 1)


if __name__ == "__main__":
    unittest.main()
