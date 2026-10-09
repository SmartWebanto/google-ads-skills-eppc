"""test_check.py — skill-030 boundaries: complete-inventory absence, removed links, eligibility review, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-030-ad-extension-coverage-audit/tests
rules:   Temp folders only; asserts condition keys/severities and gating, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | Warning ref must be listed documented intent
"""
import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_030", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
CAMPAIGNS = [{"id": "C1", "status": "ENABLED", "channel_type": "SEARCH"},
             {"id": "C2", "status": "ENABLED", "channel_type": "SEARCH"}]
GROUPS = [{"id": "G1", "campaign_id": "C1", "status": "ENABLED"}, {"id": "G2", "campaign_id": "C2", "status": "ENABLED"},
          {"id": "G3", "campaign_id": "C2", "status": "PAUSED"}]


def link(asset, typ, level, cid="", gid="", status="ENABLED", approval="APPROVED", text=None, end=""):
    return {"asset_id": asset, "type": typ, "level": level, "campaign_id": cid, "ad_group_id": gid,
            "association_status": status, "approval_status": approval, "text": text or asset, "end_date": end}


class CheckTests(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, assets, complete=True, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [ACCOUNT])
        self._write(root, "campaigns", CAMPAIGNS)
        self._write(root, "ad_groups", GROUPS)
        names = ["account.csv", "campaigns.csv", "ad_groups.csv"]
        if assets is not None:
            self._write(root, "assets", assets)
            names.append("assets.csv")
        self._write(root, "table_manifest", [{"filename": n, "completeness": "complete" if complete or n != "assets.csv"
                                              else "partial", "truncation": "none"} for n in names])
        self.args = ["--export", str(root), "--out", str(out)]
        if profile is not None:
            (Path(tmp.name) / "profile.json").write_text(json.dumps(profile))
            self.args += ["--profile", str(Path(tmp.name) / "profile.json")]
        self.root, self.out = root, out
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *self.args])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _absent(self, body):
        return sorted((f["entity"]["campaign_id"], f["entity"]["asset_type"]) for f in body["findings"]
                      if f["condition_key"] == "optional_asset_type_absent")

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_account_level_link_covers_campaigns_and_absence_needs_complete_inventory(self):
        assets = [link("s1", "SITELINK", "ACCOUNT"), link("c1", "CALLOUT", "AD_GROUP", "C2", "G2")]
        self.assertEqual(self._absent(self._run(assets)), [("C1", "CALLOUT")])
        body = self._run(assets, complete=False)
        self.assertEqual(self._absent(body), [])
        self.assertEqual(self._cov(body)["optional_types"], "partial")

    def test_removed_link_is_not_coverage(self):
        assets = [link("s1", "SITELINK", "CAMPAIGN", "C1"), link("s2", "SITELINK", "CAMPAIGN", "C2", status="REMOVED")]
        self.assertEqual(self._absent(self._run(assets)), [("C2", "SITELINK")])

    def test_alternative_column_names(self):
        rows = [{"asset_id": "s1", "asset_type": "SITELINK", "association_level": "CAMPAIGN", "campaign_id": "C1",
                 "ad_group_id": "", "status": "ENABLED"}]
        body = self._run(rows)
        self.assertEqual(self._cov(body)["association_inventory"], "completed")
        self.assertEqual(self._absent(body), [("C2", "SITELINK")])

    def test_disapproved_link_goes_to_review_and_verify_needs_intent(self):
        assets = [link("s1", "SITELINK", "CAMPAIGN", "C1", approval="DISAPPROVED"), link("s2", "SITELINK", "CAMPAIGN", "C2")]
        profile = {"intended_asset_types": ["SITELINK"], "campaign_objectives": {"C2": {"goal": "leads"}}}
        body = self._run(assets, profile=profile)
        rv = [r for r in body["ai_review"] if r["condition_key"] == "intended_association_ineligible"]
        self.assertEqual([r["entity"]["entity_id"] for r in rv], ["C1"])
        self.assertEqual(rv[0]["outcomes"]["intended_coverage_affected"]["severity"], "Warning")
        self.assertEqual([f for f in body["findings"] if f["severity"] == "Warning"], [])
        # unknown ref, another campaign's intent, another asset type's intent → rejected; listed intent → accepted
        cases = (({}, 4), ({"evidence_ref": "brief#sitelinks"}, 4),
                 ({"evidence_ref": "profile.campaign_objectives:C2"}, 4),
                 ({"evidence_ref": "profile.intended_asset_types:CALLOUT"}, 4),
                 ({"evidence_ref": "profile.intended_asset_types:SITELINK"}, 0))
        for proposal, code in cases:
            self.assertEqual(self._finalize(rv[0]["id"], proposal), code, proposal)
        rv = self._run(assets)["ai_review"]  # no documented intent in the profile → Warning unreachable
        self.assertEqual(self._finalize(rv[0]["id"], {"evidence_ref": "profile.intended_asset_types:SITELINK"}), 4)

    def _finalize(self, rid, proposal):
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "intended_coverage_affected",
                                    "rationale": "only sitelink disapproved", "proposal": proposal}]))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *self.args, "--decisions", str(dec)])

    def test_expired_link_reviewed_but_paused_parent_ignored(self):
        assets = [link("s1", "SITELINK", "CAMPAIGN", "C1", end="2026-08-01"),
                  link("s2", "SITELINK", "AD_GROUP", "C2", "G3", status="PAUSED"),
                  link("s3", "SITELINK", "CAMPAIGN", "C2")]
        rv = self._run(assets)["ai_review"]
        self.assertEqual([r["entity"]["entity_id"] for r in rv], ["C1"])

    def test_duplicate_text_info(self):
        assets = [link("c1", "CALLOUT", "CAMPAIGN", "C1", text="Free Delivery"),
                  link("c2", "CALLOUT", "CAMPAIGN", "C1", text="free  delivery"),
                  link("c3", "CALLOUT", "CAMPAIGN", "C2", text="Free Delivery")]
        f = [x for x in self._run(assets)["findings"] if x["condition_key"] == "duplicate_asset_text"]
        self.assertEqual([(x["severity"], x["entity"]["entity_id"]) for x in f], [("Info", "C1")])

    def test_missing_assets_skips_dependent_checks(self):
        body = self._run(None)
        cov = self._cov(body)
        self.assertEqual(cov["association_inventory"], "skipped")
        self.assertEqual(cov["optional_types"], "skipped")
        self.assertEqual(body["findings"], [])


if __name__ == "__main__":
    unittest.main()
