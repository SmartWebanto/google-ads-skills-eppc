"""test_check.py — skill-095 decision boundaries: mode/intent, recognition, permission gate, B/T/A values, mix, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-095-pmax-new-customer-acquisition/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check095", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check095"] = mod
_spec.loader.exec_module(mod)

SETTINGS = {"campaign_id": "P1", "conversion_tracking_owner_id": "O1", "mode": "new customer value",
            "effective_setting_source": "campaign", "purchase_goal_ids": "9001", "strategy": "MAXIMIZE_CONVERSION_VALUE",
            "raw_value_field_name": "new_customer_value", "raw_value": "80", "units": "currency", "currency": "EUR",
            "additive_or_total_semantics": "additive", "high_value_setting": "", "high_value_semantics": "",
            "recognition_methods": "customer_list;tag", "linked_list_ids": "L1", "linkage_status": "active",
            "eligibility_diagnostics": "eligible", "observed_at": "2026-09-01", "source_reference": "ui-shot-1"}
DEF = {"list_id": "L1", "source_id": "S1", "source_platform": "crm", "definition_expression": "purchasers 540d",
       "linkage_status": "active", "eligibility_by_network": "search:eligible;youtube:eligible",
       "last_successful_refresh_at": "2026-08-28", "evidence_reference": "am-1"}
PERM = {"source_id": "S1", "list_id": "L1", "market": "IT", "intended_use": "lifecycle recognition",
        "permission_status": "approved", "consent_coverage_status": "covered", "permitted_destinations": "Google Ads",
        "restricted_data_review": "passed", "policy_eligibility": "eligible", "reviewed_at": "2026-08-01",
        "evidence_reference": "dpo-7"}
LTV = {"segment": "new", "acquisition_cohort": "2024", "observation_horizon": "24m", "customer_count": "900",
       "baseline_purchase_value": "50", "expected_future_value": "", "discounted_lifetime_value": "130",
       "value_basis": "revenue", "returns_tax_treatment": "net", "lower_bound": "100", "upper_bound": "160",
       "new_existing_definition": "no order 540d", "included_value_components": "baseline_purchase_value;repeat_orders",
       "currency": "EUR", "approval_reference": "fin-2026-07", "as_of": "2026-07-31"}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0]) if rows else ["id"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _daily(new=20, existing=20, unknown=0, cost=True):
    rows = []
    for ctype, n in (("new", new), ("existing", existing), ("unknown", unknown)):
        if n is None:
            continue
        r = {"campaign_id": "P1", "date": "2026-08-10", "conversion_action_id": "9001",
             "reported_customer_type": ctype, "conversions": n, "transaction_value": n * 50,
             "lifecycle_added_value": n * 80 if ctype == "new" else 0,
             "total_reported_value": n * 50 + (n * 80 if ctype == "new" else 0)}
        if cost:
            r["cost"] = n * 10
        rows.append(r)
    return rows


def build(root: Path, *, settings=None, defs=None, perm=None, ltv=None, daily=None, snapshot="2026-09-10",
          profile=None, channel="PERFORMANCE_MAX", drop=()) -> tuple[Path, Path]:
    ex = root / "export"
    tables = {
        "account.csv": [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                         "date_range_end": "2026-08-30", "snapshot_date": snapshot, "conversion_lag_days": 3,
                         "money_unit": "currency", "rates_format": "fraction"}],
        "campaigns.csv": [{"id": "P1", "status": "ENABLED", "channel_type": channel,
                           "bidding_strategy_type": "MAXIMIZE_CONVERSION_VALUE"},
                          {"id": "S1", "status": "ENABLED", "channel_type": "SEARCH",
                           "bidding_strategy_type": "TARGET_CPA"}],
        "conversion_actions.csv": [{"id": "9001", "name": "Purchase", "category": "PURCHASE", "status": "ENABLED",
                                    "last_conversion_date": "2026-08-29"}],
        "external/pmax_acquisition_settings.csv": settings if settings is not None else [dict(SETTINGS)],
        "external/audience_definitions.csv": defs if defs is not None else [dict(DEF)],
        "external/activation_permissions.csv": perm if perm is not None else [dict(PERM)],
        "external/customer_ltv.csv": ltv if ltv is not None else [dict(LTV)],
        "custom/pmax_customer_type_daily.csv": daily if daily is not None else _daily(),
    }
    for name in drop:
        tables.pop(name)
    for name, rows in tables.items():
        _write(ex / name, rows)
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                       for f in tables])
    prof = profile if profile is not None else {
        "market": ["IT"], "objectives": ["acquire new customers profitably"],
        "campaign_objectives": {"P1": {"role": "acquisition", "goal_ids": ["9001"]}}}
    p = root / "profile.json"
    p.write_text(json.dumps(prof))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def keys(body: dict) -> list[str]:
    return sorted(f["condition_key"] for f in body["findings"])


def reviews(body: dict, key: str) -> list[dict]:
    return [r for r in body["ai_review"] if r["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _finalize(self, ex, prof, decisions) -> tuple[int, dict]:
        out = self.root / "out"
        base = ["--export", str(ex), "--profile", str(prof), "--out", str(out)]
        dec = self.root / "d.json"
        dec.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, ["run"] + base), 0)
            code = mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                ["finalize"] + base + ["--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def _result(self, ex, prof) -> dict:
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                         ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        return json.loads((out / "result.json").read_text())

    # ------------------------------------------------------------------ scope and step 1
    def test_missing_settings_skips_dependent_steps_never_passes(self):
        body = run(*build(self.root, drop=("external/pmax_acquisition_settings.csv",)))
        c = {x["check"]: x for x in body["coverage"]}
        for step in ("lifecycle_settings", "recognition", "value_semantics"):
            self.assertEqual(c[step]["status"], "skipped")
            self.assertIn("external/pmax_acquisition_settings (file)", c[step]["missing"])
        self.assertEqual(c["permission_gate"]["status"], "skipped")
        self.assertEqual(c["additive_value"]["status"], "skipped")
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "acquisition_test"], [])

    def test_no_pmax_campaign_in_complete_inventory_is_not_applicable(self):
        body = run(*build(self.root, channel="SHOPPING"))
        self.assertEqual(set(cov(body).values()), {"not_applicable"})
        self.assertEqual(body["findings"], [])

    def test_empty_mode_is_unknown_not_disabled(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "mode": ""}]))
        self.assertNotIn("optional_mode_absent", keys(body))
        self.assertEqual(reviews(body, "mode_intent"), [])
        self.assertEqual(cov(body)["lifecycle_settings"], "partial")

    def test_off_mode_is_info_only_for_declared_acquisition_role(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "mode": "off"}]))
        f = [x for x in body["findings"] if x["condition_key"] == "optional_mode_absent"]
        self.assertEqual([x["severity"] for x in f], ["Info"])
        prof = {"market": ["IT"], "campaign_objectives": {"P1": {"role": "repeat purchases", "goal_ids": ["9001"]}}}
        body = run(*build(self.root, settings=[{**SETTINGS, "mode": "off"}], profile=prof))
        self.assertNotIn("optional_mode_absent", keys(body))

    def test_active_mode_intent_is_reviewed_with_closed_outcomes(self):
        body = run(*build(self.root))
        item = reviews(body, "mode_intent")[0]
        self.assertEqual({k: v["severity"] for k, v in item["outcomes"].items()},
                         {"conflicts_retention_intent": "Warning", "consistent": None, "uncertain": "Info"})
        self.assertTrue(item["evidence"]["purchase_goals"][0]["enabled_purchase"])

    # ------------------------------------------------------------------ step 2
    def test_broken_list_linkage_is_warning_when_active(self):
        body = run(*build(self.root, defs=[{**DEF, "linkage_status": "failed"}]))
        f = [x for x in body["findings"] if x["condition_key"] == "recognition_broken"]
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertNotIn("recognition_broken", keys(run(*build(self.root))))

    def test_partial_network_ineligibility_is_not_broken(self):
        body = run(*build(self.root, defs=[{**DEF, "eligibility_by_network": "search:ineligible;youtube:eligible"}]))
        self.assertNotIn("recognition_broken", keys(body))
        body = run(*build(self.root, defs=[{**DEF, "eligibility_by_network": "search:ineligible;youtube:not eligible"}]))
        self.assertIn("recognition_broken", keys(body))

    def test_broken_linkage_with_mode_off_and_no_acquisition_role_is_observation(self):
        prof = {"market": ["IT"], "objectives": ["retention"]}
        body = run(*build(self.root, settings=[{**SETTINGS, "mode": "off"}],
                          defs=[{**DEF, "linkage_status": "failed"}], profile=prof))
        self.assertNotIn("recognition_broken", keys(body))

    def test_unresolved_list_is_info_and_blocks_test_gate(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "linked_list_ids": "L9"}]))
        f = [x for x in body["findings"] if x["condition_key"] == "recognition_unresolved"]
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertEqual(reviews(body, "acquisition_test"), [])

    def test_no_crm_list_with_other_recognition_is_not_a_defect(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "linked_list_ids": "", "recognition_methods": "tag"}]))
        self.assertFalse({"recognition_broken", "recognition_unresolved", "permission_unknown"} & set(keys(body)))

    # ------------------------------------------------------------------ step 3
    def test_missing_restricted_review_blocks_permission(self):
        body = run(*build(self.root, perm=[{**PERM, "restricted_data_review": ""}]))
        f = [x for x in body["findings"] if x["condition_key"] == "permission_unknown"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["owner"], mod.OWN_156)
        self.assertEqual(reviews(body, "acquisition_test"), [])

    def test_source_level_permission_applies_and_foreign_market_is_ignored(self):
        body = run(*build(self.root, perm=[{**PERM, "list_id": ""}]))
        self.assertNotIn("permission_unknown", keys(body))
        body = run(*build(self.root, perm=[{**PERM, "market": "DE"}]))
        self.assertIn("permission_unknown", keys(body))

    def test_denied_permission_with_active_mode_critical_needs_evidence_ref(self):
        ex, prof = build(self.root, perm=[{**PERM, "permission_status": "revoked"}])
        body = self._result(ex, prof)
        self.assertEqual([f["severity"] for f in body["findings"] if f["condition_key"] == "unsafe_use"], ["Info"])
        rid = reviews(body, "unsafe_use")[0]["id"]
        code, _ = self._finalize(ex, prof, [{"id": rid, "outcome": "unsafe_use_confirmed", "rationale": "x"}])
        self.assertEqual(code, 4)
        code, final = self._finalize(ex, prof, [{"id": rid, "outcome": "unsafe_use_confirmed", "rationale": "x",
                                                 "proposal": {"evidence_ref": "dpo-7"}}])
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "unsafe_use"],
                         ["Critical"])

    def test_denied_permission_with_mode_off_has_no_unsafe_use_review(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "mode": "off"}],
                          perm=[{**PERM, "permission_status": "denied"}]))
        self.assertIn("permission_denied_blocked", keys(body))
        self.assertEqual(reviews(body, "unsafe_use"), [])

    # ------------------------------------------------------------------ step 4
    def test_micros_normalized_once(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "raw_value": "80000000", "units": "micros",
                                                "raw_value_field_name": "value_micros"}]))
        obs = [o for o in body["observations"] if o["check"] == "value_semantics"][0]["data"]
        self.assertEqual(obs["normalized_value"], 80)
        self.assertEqual(keys(body).count("monetary_contradiction"), 0)

    def test_currency_or_micros_field_conflict_is_warning(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "currency": "USD"}]))
        f = [x for x in body["findings"] if x["condition_key"] == "monetary_unit_conflict"]
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual(reviews(body, "double_count") + reviews(body, "monetary_contradiction"), [])
        body = run(*build(self.root, settings=[{**SETTINGS, "raw_value_field_name": "value_micros"}]))
        self.assertIn("monetary_unit_conflict", keys(body))

    def test_unknown_semantics_is_info_and_blocks_comparison(self):
        body = run(*build(self.root, settings=[{**SETTINGS, "additive_or_total_semantics": "", "raw_value": "300"}]))
        self.assertIn("missing_additive_semantics", keys(body))
        self.assertNotIn("monetary_contradiction", keys(body))
        self.assertEqual(cov(body)["additive_value"], "partial")

    # ------------------------------------------------------------------ step 5
    def test_configured_value_inside_approved_range_is_consistent(self):
        body = run(*build(self.root))
        calc = [o for o in body["observations"] if o["check"] == "additive_value"
                and o["data"].get("A") is not None][0]["data"]
        self.assertEqual(calc["A"], 80)
        self.assertEqual(calc["A_bounds"], [50, 110])
        self.assertAlmostEqual(calc["A_over_B"], 1.6)
        self.assertNotIn("monetary_contradiction", keys(body))

    def test_value_at_or_above_total_is_double_count_review(self):
        ex, prof = build(self.root, settings=[{**SETTINGS, "raw_value": "130"}])
        body = self._result(ex, prof)
        self.assertEqual([f["severity"] for f in body["findings"] if f["condition_key"] == "monetary_contradiction"],
                         ["Warning"])
        item = reviews(body, "double_count")[0]
        self.assertEqual(item["outcomes"]["double_count_confirmed"]["severity"], "Critical")
        self.assertEqual(item["outcomes"]["not_double_count"]["severity"], "Warning")
        code, _ = self._finalize(ex, prof, [{"id": item["id"], "outcome": "double_count_confirmed", "rationale": "x"}])
        self.assertEqual(code, 4)
        code, final = self._finalize(ex, prof, [{"id": item["id"], "outcome": "double_count_confirmed",
                                                 "rationale": "x", "proposal": {"evidence_ref": "fin-2026-07"}}])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(f["severity"] for f in final["findings"] if f["condition_key"] == "double_count"),
                         ["Critical"])
        self.assertNotIn("monetary_contradiction", [f["condition_key"] for f in final["findings"]])

    def test_future_component_path_and_no_bounds_goes_to_review(self):
        ltv = [{**LTV, "included_value_components": "repeat_orders", "expected_future_value": "40",
                "discounted_lifetime_value": "", "lower_bound": "", "upper_bound": ""}]
        body = run(*build(self.root, ltv=ltv))
        item = reviews(body, "monetary_contradiction")[0]
        self.assertEqual(item["evidence"]["A"], 40)
        self.assertNotIn("monetary_contradiction", keys(body))
        self.assertEqual(reviews(body, "double_count"), [])

    def test_baseline_overlap_or_total_not_above_baseline_gives_no_value(self):
        for ltv in ([{**LTV, "included_value_components": "baseline;first_purchase;repeat"}],
                    [{**LTV, "discounted_lifetime_value": "50"}]):
            body = run(*build(self.root, ltv=ltv, settings=[{**SETTINGS, "raw_value": "500"}]))
            self.assertNotIn("monetary_contradiction", keys(body))
            self.assertEqual(reviews(body, "double_count"), [])
            self.assertEqual(cov(body)["additive_value"], "partial")

    def test_unapproved_or_foreign_currency_ltv_is_not_used(self):
        for ltv in ([{**LTV, "approval_reference": ""}], [{**LTV, "currency": "USD"}]):
            body = run(*build(self.root, ltv=ltv, settings=[{**SETTINGS, "raw_value": "500"}]))
            self.assertNotIn("monetary_contradiction", keys(body))
            self.assertEqual(cov(body)["additive_value"], "partial")

    # ------------------------------------------------------------------ step 6
    def test_mix_is_info_only_in_mature_window(self):
        body = run(*build(self.root))
        f = [x for x in body["findings"] if x["condition_key"] == "recognized_customer_mix"]
        self.assertEqual(len(f), 1)
        self.assertAlmostEqual(f[0]["evidence"]["by_type"]["new"]["share"], 0.5)
        body = run(*build(self.root, snapshot="2026-08-31"))
        self.assertNotIn("recognized_customer_mix", keys(body))
        self.assertEqual(cov(body)["value_reconciliation"], "partial")

    def test_zero_conversions_have_undefined_shares(self):
        body = run(*build(self.root, daily=_daily(new=0, existing=0)))
        self.assertNotIn("recognized_customer_mix", keys(body))
        obs = [o for o in body["observations"] if o["check"] == "value_reconciliation"
               and "customer mix" in o["text"]][0]["data"]
        self.assertIsNone(obs["unknown_share"])

    def test_type_cpa_needs_cost_and_min_conversions_on_both_sides(self):
        body = run(*build(self.root, daily=_daily(new=20, existing=5)))
        self.assertFalse(any("cpa_new" in o["data"] for o in body["observations"]))
        body = run(*build(self.root))
        cpa = [o["data"] for o in body["observations"] if "cpa_new" in o["data"]][0]
        self.assertEqual(cpa["cpa_new"], 10)
        body = run(*build(self.root, daily=_daily(cost=False)))
        c = {x["check"]: x for x in body["coverage"]}["value_reconciliation"]
        self.assertIn("custom/pmax_customer_type_daily:cost", c["missing"])

    def test_reconciliation_mismatch_is_observation_not_finding(self):
        rows = _daily()
        rows[0]["total_reported_value"] = 1
        body = run(*build(self.root, daily=rows))
        texts = [o["text"] for o in body["observations"] if o["check"] == "value_reconciliation"]
        self.assertTrue(any("MISMATCH" in t for t in texts))
        self.assertEqual([f for f in body["findings"] if f["check"] == "value_reconciliation"
                          and f["condition_key"] != "recognized_customer_mix"], [])

    def test_acquisition_test_verify_bounds_proposal(self):
        ex, prof = build(self.root)
        body = self._result(ex, prof)
        item = reviews(body, "acquisition_test")[0]
        self.assertEqual(item["evidence"]["approved_additive_value_max"], 110)
        bad = {"campaign_id": "P1", "duration_days": 28, "new_customer_value": 150, "currency": "EUR",
               "intent_ref": "profile.objectives"}
        code, _ = self._finalize(ex, prof, [{"id": item["id"], "outcome": "test_proposed", "rationale": "x",
                                             "proposal": bad}])
        self.assertEqual(code, 4)
        code, final = self._finalize(ex, prof, [{"id": item["id"], "outcome": "test_proposed", "rationale": "x",
                                                 "proposal": {**bad, "new_customer_value": 80}}])
        self.assertEqual(code, 0)
        self.assertIn("acquisition_test", [f["condition_key"] for f in final["findings"]])


if __name__ == "__main__":
    unittest.main()
