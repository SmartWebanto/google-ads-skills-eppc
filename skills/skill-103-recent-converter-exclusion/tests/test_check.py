"""test_check.py — skill-103 boundaries: inheritance, policy vocabulary, exceptions, signals, completeness, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-103-recent-converter-exclusion/tests
rules:   stdlib only; temp folders; never read the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial tests
"""
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_103", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(root: Path, key: str, rows: list[dict]) -> None:
    p = root / f"{key}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _excl(cid, gid, lid, level, mode="exclusion", negative="true", complete="true"):
    return {"campaign_id": cid, "ad_group_id": gid, "criterion_id": f"c-{cid}-{gid}-{lid}", "list_id": lid,
            "level": level, "negative": negative, "association_status": "ENABLED", "mode": mode,
            "supported_exclusion_control": "true", "inventory_complete": complete}


def _plan(cid, reach, exceptions=""):
    return {"business_segment": "tools", "campaign_id": cid, "ad_group_id": "", "qualifying_event": "purchase",
            "objective": "acquisition", "allowed_reach": reach, "repurchase_exceptions": exceptions,
            "intended_duration": "30", "suppression_reset_rule": "resets on purchase", "owner": "crm",
            "approved_at": "2026-06-01"}


def base_tables() -> dict:
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}],
        "campaigns": [{"id": "10"}, {"id": "20"}],
        "ad_groups": [{"id": "101", "campaign_id": "10"}, {"id": "102", "campaign_id": "10"},
                      {"id": "201", "campaign_id": "20"}],
        "custom/converter_exclusions": [_excl("10", "", "BUY", "campaign")],
        "external/audience_definitions": [
            {"list_id": "BUY", "source_id": "S1", "entry_event": "purchase", "definition_expression": "purchase",
             "membership_duration_days": "30"},
            {"list_id": "ACC", "source_id": "S1", "entry_event": "purchase_accessory",
             "definition_expression": "accessory purchase", "membership_duration_days": "30"}],
        "external/converter_suppression_plan": [_plan("10", "new_only"), _plan("20", "converters_allowed")],
        "external/customer_lifecycle": [{"business_segment": "tools", "repurchase_interval": "90", "units": "days",
                                         "maturity": "true"}],
        "external/activation_permissions": [
            {"source_id": "S1", "list_id": "", "permission_status": "granted", "consent_coverage_status": "covered",
             "permitted_destinations": "google_ads", "evidence_reference": "p-1"}],
    }


class CheckTests(unittest.TestCase):
    def build(self, tables: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        for key, rows in tables.items():
            _write(root, key, rows)
        _write(root, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        return root

    def run_check(self, tables: dict) -> dict:
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.build(tables), None).finish()

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    def test_policy_followed_is_clean(self):
        body = self.run_check(base_tables())
        self.assertEqual([f for f in body["findings"] if f["severity"] != "Info"], [])

    def test_ad_group_level_gap_is_missing_suppression(self):
        t = base_tables()
        t["custom/converter_exclusions"] = [_excl("10", "101", "BUY", "ad_group")]
        f = self.keys(self.run_check(t), "required_suppression_missing")
        self.assertEqual(f[0]["evidence"]["scopes_missing"], ["10/102"])

    def test_account_level_inherits_and_contradicts_repeat_policy(self):
        t = base_tables()
        t["custom/converter_exclusions"] = [_excl("", "", "BUY", "account")]
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "required_suppression_missing"))
        f = self.keys(body, "exclusion_contradicts_policy")
        self.assertEqual([x["entity"]["campaign_id"] for x in f], ["20"])
        self.assertTrue([r for r in body["ai_review"] if r["condition_key"] == "exclusion_contradicts_policy"])

    def test_pmax_signal_is_not_an_exclusion(self):
        t = base_tables()
        t["custom/converter_exclusions"] = [_excl("10", "", "BUY", "campaign", mode="new customer acquisition")]
        self.assertEqual(len(self.keys(self.run_check(t), "required_suppression_missing")), 1)

    def test_incomplete_inventory_blocks_absence_claim(self):
        t = base_tables()
        t["custom/converter_exclusions"] = [_excl("10", "101", "BUY", "ad_group", complete="")]
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "required_suppression_missing"))
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "policy_compare")["status"], "partial")

    def test_repurchase_exception_excluded_warns(self):
        t = base_tables()
        t["external/converter_suppression_plan"][0]["repurchase_exceptions"] = "ACC"
        t["custom/converter_exclusions"].append(_excl("10", "", "ACC", "campaign"))
        self.assertEqual(len(self.keys(self.run_check(t), "exception_list_excluded")), 1)

    def test_names_do_not_make_converter_lists(self):
        t = base_tables()
        t["external/audience_definitions"][0]["entry_event"] = "page_view"
        body = self.run_check(t)
        self.assertEqual(len(self.keys(body, "converter_list_unavailable")), 1)
        self.assertFalse(self.keys(body, "required_suppression_missing"))

    def test_unknown_policy_vocabulary_is_partial(self):
        t = base_tables()
        t["external/converter_suppression_plan"][1]["allowed_reach"] = "maybe"
        t["custom/converter_exclusions"].append(_excl("20", "", "BUY", "campaign"))
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "exclusion_contradicts_policy"))
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "policy_compare")["status"], "partial")

    def test_exclusion_without_policy_is_info(self):
        t = base_tables()
        t["external/converter_suppression_plan"] = t["external/converter_suppression_plan"][:1]
        t["custom/converter_exclusions"].append(_excl("20", "", "BUY", "campaign"))
        f = self.keys(self.run_check(t), "exclusion_without_policy")
        self.assertEqual([(x["entity"]["campaign_id"], x["severity"]) for x in f], [("20", "Info")])

    def test_duration_mismatch_and_permission_block(self):
        t = base_tables()
        t["external/audience_definitions"][0]["membership_duration_days"] = "540"
        self.assertEqual(len(self.keys(self.run_check(t), "suppression_duration_mismatch")), 1)
        t = base_tables()
        t["custom/converter_exclusions"] = [_excl("20", "", "ACC", "campaign")]
        t["external/activation_permissions"][0]["consent_coverage_status"] = "unknown"
        self.assertEqual(len(self.keys(self.run_check(t), "suppression_proposal_blocked")), 1)

    def test_missing_plan_skips_policy(self):
        t = base_tables()
        del t["external/converter_suppression_plan"]
        body = self.run_check(t)
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "policy_compare")["status"], "skipped")
        self.assertFalse([f for f in body["findings"] if f["severity"] != "Info"])

    def test_finalize_unsafe_use_needs_evidence(self):
        t = base_tables()
        t["external/activation_permissions"][0]["permission_status"] = "revoked"
        root = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        item = next(r for r in json.loads((out / "result.json").read_text())["ai_review"]
                    if r["condition_key"] == "unsafe_active_use")
        dec = root.parent / "d.json"
        args = ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "unsafe_use_evidenced", "rationale": "r"}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "unsafe_use_evidenced", "rationale": "r",
                                    "proposal": {"evidence_ref": "dpo-review-2"}}]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, args), 0)


if __name__ == "__main__":
    unittest.main()
