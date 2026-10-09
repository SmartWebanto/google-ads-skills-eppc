"""test_check.py — Decision-boundary tests for skill-009 account defaults governance.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-009-account-defaults-audit/tests
rules:   Temp folders only; stdlib only; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial tests
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_009", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

CTL_COLS = ["account_id", "control_type", "control_name", "linked_account_id", "observed_value", "expected_value",
            "authorization_ref", "dependency", "observed_failure", "evidence_ref", "source", "snapshot_date"]


def write_export(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        cols, rows = rows if isinstance(rows, tuple) else (list(dict.fromkeys(k for r in rows for k in r)), rows)
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def ctl(ctype, name, observed, expected="", dependency="", **kw):
    return {"account_id": "1", "control_type": ctype, "control_name": name, "linked_account_id": kw.get("linked", ""),
            "observed_value": observed, "expected_value": expected, "authorization_ref": kw.get("auth", ""),
            "dependency": dependency, "observed_failure": kw.get("failure", ""), "evidence_ref": kw.get("ref", ""),
            "source": "Admin UI", "snapshot_date": "2026-09-06"}


def tables(auto_tagging="true", controls=None, goals=None, action_status="ENABLED"):
    t = {"account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                      "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "auto_tagging": auto_tagging,
                      "conversion_lag_days": "2"}],
         "campaigns": [{"id": "C1", "status": "ENABLED"}],
         "conversion_actions": [{"id": "A1", "name": "Purchase", "category": "PURCHASE", "status": action_status,
                                 "counting": "EVERY", "value_settings": "transaction", "attribution_model": "DATA_DRIVEN",
                                 "primary_for_goal": "true", "last_conversion_date": "2026-08-29"},
                                {"id": "A2", "name": "Newsletter", "category": "SIGNUP", "status": "ENABLED",
                                 "counting": "ONE", "value_settings": "", "attribution_model": "LAST_CLICK",
                                 "primary_for_goal": "false", "last_conversion_date": "2026-08-29"}]}
    if controls is not None:
        t["external/account_controls"] = (CTL_COLS, controls)
    if goals is not None:
        t["custom/campaign_goal_selection"] = [
            {"account_id": "1", "campaign_id": "C1", "goal_id": g, "custom_goal_id": cg, "conversion_action_id": a,
             "selected_for_bidding": sel, "selection_source": src, "snapshot_date": "2026-09-06"}
            for g, cg, a, sel, src in goals]
    return t


PROFILE = {"campaign_objectives": {"C1": {"goal_ids": ["A1"]}}, "conversion_lag_days": 2}


class CheckTests(unittest.TestCase):
    def run_skill(self, t, profile=PROFILE):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_export(self.root / "export", t)
        (self.root / "profile.json").write_text(json.dumps(profile))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.root / "export", self.root / "profile.json").finish()

    @staticmethod
    def found(body):
        return sorted((f["condition_key"], f["severity"]) for f in body["findings"])

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_auto_tagging_off_is_warning_only_with_declared_dependency(self):
        body = self.run_skill(tables("false", [ctl("auto_tagging", "Auto-tagging", "off", "on", "GA4 import")]))
        self.assertIn(("auto_tagging_conflicts_dependency", "Warning"), self.found(body))
        body = self.run_skill(tables("false", []))
        self.assertEqual(self.found(body), [])
        self.assertEqual([r["condition_key"] for r in body["ai_review"] if r["check"] == "auto_tagging"], ["auto_tagging_off"])

    def test_auto_apply_policy_mismatch_vs_authorised_and_unknown(self):
        body = self.run_skill(tables(controls=[ctl("auto_apply", "Add broad match keywords", "on", "off")]))
        self.assertIn(("auto_apply_policy_mismatch", "Warning"), self.found(body))
        body = self.run_skill(tables(controls=[ctl("auto_apply", "Add broad match keywords", "on", "on", auth="MEMO-1")]))
        self.assertEqual(self.found(body), [])
        self.assertEqual(self.cov(body)["auto_apply_authority"], "completed")
        body = self.run_skill(tables(controls=[ctl("auto_apply", "Add broad match keywords", "maybe", "off")]))
        self.assertEqual(self.found(body), [])
        self.assertEqual(self.cov(body)["auto_apply_authority"], "partial")

    def test_link_absence_required_vs_optional(self):
        body = self.run_skill(tables(controls=[ctl("link", "Merchant Center", "unlinked", "", "Shopping feed")]))
        self.assertIn(("required_link_missing", "Warning"), self.found(body))
        body = self.run_skill(tables(controls=[ctl("link", "Search Console", "unlinked")]))
        self.assertEqual(self.found(body), [("optional_integration_absent", "Info")])

    def test_goal_selection_against_approved_goals(self):
        body = self.run_skill(tables(goals=[("G2", "", "A2", "true", "account_default")]))
        self.assertIn(("selection_misses_approved_goal", "Warning"), self.found(body))
        body = self.run_skill(tables(goals=[("G1", "", "A1", "true", "account_default"),
                                            ("G2", "CG1", "A2", "true", "custom_goal")]))
        self.assertEqual(self.found(body), [("intentional_custom_goal_selection", "Info")])
        body = self.run_skill(tables(goals=[("G1", "", "A1", "true", "account_default")]), profile={})
        self.assertEqual(self.found(body), [])
        self.assertEqual(self.cov(body)["goal_selection"], "partial")

    def test_tracking_parameters_missing_keys(self):
        c = ctl("final_url_suffix", "Account suffix", "utm_source=google", "utm_source=google&utm_medium=cpc", "CRM")
        self.assertIn(("tracking_parameters_missing", "Warning"), self.found(self.run_skill(tables(controls=[c]))))
        c = ctl("final_url_suffix", "Account suffix", "utm_source=google&utm_medium=cpc", "utm_source; utm_medium", "CRM")
        self.assertEqual(self.found(self.run_skill(tables(controls=[c]))), [])

    def test_missing_controls_are_skipped_not_passed(self):
        body = self.run_skill(tables())
        for c in ("auto_apply_inventory", "auto_apply_authority", "account_links", "tracking_parameters"):
            self.assertEqual(self.cov(body)[c], "skipped")
        self.assertEqual(self.cov(body)["measurement_failure"], "partial")

    def test_disabled_goal_actions_and_critical_needs_evidence_ref(self):
        body = self.run_skill(tables(action_status="REMOVED"))
        self.assertIn(("approved_goal_actions_disabled", "Warning"), self.found(body))
        body = self.run_skill(tables(controls=[ctl("auto_tagging", "Auto-tagging", "on", "on", "GA4",
                                                   failure="gclid stripped by redirect", ref="TRACE-7")]))
        rid = [r["id"] for r in body["ai_review"] if r["condition_key"] == "measurement_failure"][0]
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            for ref, code in (("", 4), ("OTHER", 4), ("TRACE-7", 0)):
                dec = self.root / "d.json"
                dec.write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced", "rationale": "r",
                                            "proposal": {"evidence_ref": ref}}]))
                self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                            ["finalize"] + args + ["--decisions", str(dec)]), code)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
