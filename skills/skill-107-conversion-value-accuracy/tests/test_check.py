"""test_check.py — skill-107 decision boundaries: count-based values, policy currency, payload QA, 071 link,

calibration maturity/tolerance, refund coordination and Critical verification.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-107-conversion-value-accuracy/tests
rules:   stdlib only, temp folders, no wording assertions; each deterministic condition has a planted defect and a
plausible valid counterexample.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial tests
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

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check107", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["check107"] = mod
_spec.loader.exec_module(mod)
FIXTURE = HERE.parents[1] / "_selftest" / "fixture"

POLICY = "external/conversion_value_policy.csv"
QA = "external/value_payload_qa.csv"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def pol(aid, version="v2", **kw) -> dict:
    row = {"account_id": "c1", "action_id": aid, "policy_version": version, "objective": "sales",
           "intended_bidding_role": "value", "value_type": "dynamic", "formula": "order net value",
           "gross_or_net_basis": "net", "tax_treatment": "excluded", "shipping_treatment": "excluded",
           "discount_treatment": "deducted", "refund_treatment": "restated after refund", "currency": "EUR",
           "fx_source": "ECB", "fx_date_rule": "order date", "rounding_rule": "2dp", "fallback_value": None,
           "fallback_conditions": None, "validity_start": "2026-07-01", "validity_end": None,
           "calibration_window": None, "owner": "finance"}
    row.update(kw)
    return row


def qa(tid, aid, scenario, expected, observed, **kw) -> dict:
    row = {"test_id": tid, "action_id": aid, "scenario": scenario, "tested_at": "2026-08-15", "policy_version": "v2",
           "expected_value": expected, "observed_value": observed, "currency": "EUR", "value_source": "tag",
           "default_used": "false", "duplicate_send_count": 1, "status": "pass", "source_reference": f"qa-{tid}"}
    row.update(kw)
    return row


def full_qa(aid, **kw) -> list[dict]:
    """All scenarios required by a dynamic policy with discount and refund treatments."""
    return [qa(f"{aid}-{s}", aid, s, 100, 100, **kw) for s in ("ordinary", "zero", "missing", "discounted", "refunded")]


ACTIONS = [{"id": "A1", "name": "Purchase", "category": "PURCHASE", "status": "ENABLED",
            "value_settings": "transaction-specific"},
           {"id": "L1", "name": "Lead", "category": "LEAD", "status": "ENABLED", "value_settings": "1"}]
CAMPAIGNS = [{"id": "C1", "status": "ENABLED", "bidding_strategy_type": "MAXIMIZE_CONVERSIONS", "goal_ids": "L1"},
             {"id": "C2", "status": "ENABLED", "bidding_strategy_type": "TARGET_ROAS", "goal_ids": "A1"}]


def build(root: Path, *, actions=None, campaigns=None, extra=None, unattested=(), profile=None) -> tuple[Path, Path]:
    ex = root / "export"
    tables = {
        "account.csv": [{"customer_id": "c1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                         "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                         "snapshot_date": "2026-09-10", "rates_format": "fraction", "money_unit": "currency",
                         "conversion_date_basis": "conversion_date", "conversion_lag_days": 2}],
        "conversion_actions.csv": actions if actions is not None else ACTIONS,
        "campaigns.csv": campaigns if campaigns is not None else CAMPAIGNS,
        **(extra or {}),
    }
    for name, rows in tables.items():
        _write(ex / name, rows)
    _write(ex / "table_manifest.csv", [{"filename": n, "completeness": "complete", "truncation": "none"}
                                       for n in tables if n not in unattested])
    p = root / "profile.json"
    p.write_text(json.dumps(profile or {}))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def found(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def reviews(body: dict, key: str) -> list[dict]:
    return [r for r in body["ai_review"] if r["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    # ---------------------------------------------------------------- step 1
    def test_unit_value_under_count_bidding_is_info_only(self):
        body = run(*build(self.root))
        f = found(body, "count_based_zero_unit_value")
        self.assertEqual([x["entity"]["action_id"] for x in f], ["L1"])
        self.assertEqual(f[0]["severity"], "Info")
        self.assertEqual(body["counts"]["Warning"], 0)
        self.assertEqual(cov(body)["value_goal_map"], "completed")

    def test_unit_value_feeding_value_bidding_is_not_labelled_count_based(self):
        camps = CAMPAIGNS + [{"id": "C3", "status": "ENABLED", "bidding_strategy_type": "MAXIMIZE_CONVERSION_VALUE",
                              "goal_ids": "L1"}]
        body = run(*build(self.root, campaigns=camps))
        self.assertEqual(found(body, "count_based_zero_unit_value"), [])

    def test_unknown_strategy_or_missing_goals_blocks_count_claim(self):
        camps = [{"id": "C1", "status": "ENABLED", "bidding_strategy_type": None, "goal_ids": "L1"},
                 {"id": "C9", "status": "ENABLED", "bidding_strategy_type": "TARGET_CPA", "goal_ids": None}]
        body = run(*build(self.root, campaigns=camps))
        self.assertEqual(found(body, "count_based_zero_unit_value"), [])
        self.assertEqual(cov(body)["value_goal_map"], "partial")

    # ---------------------------------------------------------------- step 2
    def test_action_without_current_policy_is_unknown_basis_info(self):
        extra = {POLICY: [pol("A1"), pol("L1", "v1", validity_end="2026-07-31")]}
        body = run(*build(self.root, extra=extra))
        f = found(body, "unknown_business_basis")
        self.assertEqual([x["entity"]["action_id"] for x in f], ["L1"])
        self.assertEqual(f[0]["severity"], "Info")

    def test_policy_absence_not_provable_without_manifest(self):
        extra = {POLICY: [pol("A1")]}
        body = run(*build(self.root, extra=extra, unattested=(POLICY,)))
        self.assertEqual(found(body, "unknown_business_basis"), [])
        self.assertEqual(cov(body)["value_policy_type"], "partial")

    def test_two_current_versions_are_ambiguous_not_compared(self):
        extra = {POLICY: [pol("A1"), pol("A1", "v3"), pol("L1")],
                 QA: [qa("t1", "A1", "ordinary", 100, 50)]}
        body = run(*build(self.root, extra=extra))
        self.assertEqual(found(body, "payload_value_mismatch"), [])
        self.assertEqual(cov(body)["value_policy_type"], "partial")
        self.assertEqual(cov(body)["payload_policy_qa"], "partial")

    # ---------------------------------------------------------------- step 3 default config
    def test_default_value_vs_policy_fallback(self):
        acts = [{"id": "L1", "name": "Lead", "category": "LEAD", "status": "ENABLED", "value_settings": "15 EUR"}]
        body = run(*build(self.root, actions=acts, extra={POLICY: [pol("L1", value_type="static", fallback_value=20)]}))
        self.assertEqual(len(found(body, "default_value_conflict")), 1)
        body = run(*build(self.root / "ok", actions=acts,
                          extra={POLICY: [pol("L1", value_type="static", fallback_value=15)]}))
        self.assertEqual(found(body, "default_value_conflict"), [])
        self.assertEqual(cov(body)["default_policy_config"], "completed")

    def test_default_currency_conflict(self):
        acts = [{"id": "L1", "name": "Lead", "category": "LEAD", "status": "ENABLED", "value_settings": "15 USD"}]
        body = run(*build(self.root, actions=acts, extra={POLICY: [pol("L1", value_type="static", fallback_value=15)]}))
        self.assertEqual(len(found(body, "default_currency_conflict")), 1)

    # ---------------------------------------------------------------- step 3 payload QA
    def test_value_mismatch_tolerance_boundary(self):
        rows = full_qa("A1")
        rows[0] = qa("A1-ordinary", "A1", "ordinary", 100, 100.004)
        body = run(*build(self.root, extra={POLICY: [pol("A1"), pol("L1")], QA: rows}))
        self.assertEqual(found(body, "payload_value_mismatch"), [])
        rows[0] = qa("A1-ordinary", "A1", "ordinary", 100, 90)
        body = run(*build(self.root / "bad", extra={POLICY: [pol("A1"), pol("L1")], QA: rows}))
        f = found(body, "payload_value_mismatch")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "Warning")

    def test_currency_and_duplicate_sends(self):
        rows = full_qa("A1")
        rows[0] = qa("A1-ordinary", "A1", "ordinary", 100, 100, currency="USD", duplicate_send_count=2)
        body = run(*build(self.root, extra={POLICY: [pol("A1"), pol("L1")], QA: rows}))
        self.assertEqual(len(found(body, "payload_currency_mismatch")), 1)
        self.assertEqual(len(found(body, "duplicate_send")), 1)
        body = run(*build(self.root / "ok", extra={POLICY: [pol("A1"), pol("L1")], QA: full_qa("A1")}))
        self.assertEqual(found(body, "payload_currency_mismatch") + found(body, "duplicate_send"), [])

    def test_default_used_only_conflicts_without_fallback(self):
        rows = full_qa("A1")
        rows[2] = qa("A1-missing", "A1", "missing", 50, 50, default_used="true")
        body = run(*build(self.root, extra={POLICY: [pol("A1"), pol("L1")], QA: rows}))
        self.assertEqual(len(found(body, "default_used_without_policy_fallback")), 1)
        body = run(*build(self.root / "ok", extra={POLICY: [pol("A1", fallback_value=50), pol("L1")], QA: rows}))
        self.assertEqual(found(body, "default_used_without_policy_fallback"), [])

    def test_stale_policy_version_qa_is_partial_not_pass_or_defect(self):
        rows = [dict(r, policy_version="v1") for r in full_qa("A1")]
        rows[0]["observed_value"] = 10
        body = run(*build(self.root, extra={POLICY: [pol("A1"), pol("L1")], QA: rows}))
        self.assertEqual(found(body, "payload_value_mismatch"), [])
        self.assertEqual(cov(body)["payload_policy_qa"], "partial")

    def test_missing_required_scenarios_partial(self):
        body = run(*build(self.root, extra={POLICY: [pol("A1")], QA: full_qa("A1")[:1]}))
        self.assertEqual(cov(body)["payload_policy_qa"], "partial")
        body = run(*build(self.root / "ok", extra={POLICY: [pol("A1")], QA: full_qa("A1")}))
        self.assertEqual(cov(body)["payload_policy_qa"], "completed")

    # ---------------------------------------------------------------- step 4
    def test_policy_vs_071_rule_basis_difference_is_review(self):
        rules = [{"action_id": "A1", "business_event_id": "b1", "value_basis": "gross", "refund_treatment":
                  "restated after refund", "currency": "EUR", "tax_shipping_discount_treatment": "excluded"}]
        body = run(*build(self.root, extra={POLICY: [pol("A1")], "external/reconciliation_rules.csv": rules}))
        r = reviews(body, "treatment_inconsistency")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["outcomes"]["conflict"]["severity"], "Warning")
        self.assertEqual(body["counts"]["Warning"] + body["counts"]["Critical"], 0)
        rules[0]["value_basis"] = "net"
        body = run(*build(self.root / "ok", extra={POLICY: [pol("A1")], "external/reconciliation_rules.csv": rules}))
        self.assertEqual(reviews(body, "treatment_inconsistency"), [])

    def test_campaign_mixing_gross_and_net_goals_is_review(self):
        camps = [{"id": "C2", "status": "ENABLED", "bidding_strategy_type": "TARGET_ROAS", "goal_ids": "A1;L1"}]
        body = run(*build(self.root, campaigns=camps,
                          extra={POLICY: [pol("A1"), pol("L1", gross_or_net_basis="gross")]}))
        self.assertEqual([r["entity"] for r in reviews(body, "mixed_value_basis")], [{"campaign_id": "C2"}])
        body = run(*build(self.root / "ok", campaigns=camps, extra={POLICY: [pol("A1"), pol("L1")]}))
        self.assertEqual(reviews(body, "mixed_value_basis"), [])

    # ---------------------------------------------------------------- step 5 + 7
    def _reco(self, ads_value, maturity=7):
        return {"external/reconciliation_rules.csv": [{"action_id": "A1", "business_event_id": "b1",
                                                        "maturity_days": maturity, "tolerance_value_pct": 5,
                                                        "currency": "EUR"}],
                "external/business_events.csv": [
                    {"event_token": "e1", "action_id": "A1", "event_timestamp": "2026-08-10T10:00:00",
                     "expected_value": 500, "currency": "EUR"},
                    {"event_token": "e2", "action_id": "A1", "event_timestamp": "2026-08-11T10:00:00",
                     "expected_value": 500, "currency": "EUR"}],
                "custom/ads_reconciliation_daily.csv": [
                    {"account_id": "c1", "campaign_id": "C2", "action_id": "A1", "date": "2026-08-10",
                     "date_basis": "conversion_date", "conversion_value": ads_value, "currency": "EUR",
                     "reporting_mature": "true"}]}

    def test_residual_beyond_071_tolerance_queues_critical_review(self):
        body = run(*build(self.root, extra=self._reco(1200)))
        obs = [o for o in body["observations"] if o["check"] == "reconciliation_residuals_071"][0]["data"]
        self.assertAlmostEqual(obs["actions"][0]["signed_residual"], 200)
        self.assertAlmostEqual(obs["actions"][0]["relative_variance"], 0.2)
        r = reviews(body, "material_value_corruption")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["outcomes"]["material_value_corruption_confirmed"]["severity"], "Critical")
        self.assertEqual(body["counts"]["Warning"] + body["counts"]["Critical"], 0)
        body = run(*build(self.root / "ok", extra=self._reco(1040)))
        self.assertEqual(reviews(body, "material_value_corruption"), [])

    def test_immature_reconciliation_window_is_partial(self):
        body = run(*build(self.root, extra=self._reco(1200, maturity=60)))
        self.assertEqual(reviews(body, "material_value_corruption"), [])
        self.assertEqual(cov(body)["reconciliation_residuals_071"], "partial")

    # ---------------------------------------------------------------- step 6
    def _calib(self, ratio=0.8, outcomes=20, cohort_end="2026-07-31", horizon=30) -> dict:
        return {"external/value_model_calibration.csv": [
            {"action_id": "L1", "model_version": "m1", "cohort_start": "2026-06-01", "cohort_end": cohort_end,
             "stage": "sql", "cohort_size": 200, "mature_outcomes": outcomes, "close_rate": 0.1,
             "realized_net_value": 5000, "margin_basis": "net", "horizon_days": horizon,
             "observed_vs_predicted_value": ratio, "selection_scope": "all leads", "uncertainty": "±10%",
             "source_reference": "crm-cal-1"}]}

    def test_mature_drift_beyond_owner_tolerance_is_warning(self):
        prof = {"value_calibration_tolerance": 0.1}
        body = run(*build(self.root, extra=self._calib(0.8), profile=prof))
        f = found(body, "calibration_drift")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "Warning")
        body = run(*build(self.root / "ok", extra=self._calib(0.95), profile=prof))
        self.assertEqual(found(body, "calibration_drift"), [])

    def test_calibration_gates_block_drift_finding(self):
        prof = {"value_calibration_tolerance": 0.1}
        cases = {"immature": (self._calib(0.5, cohort_end="2026-08-25"), prof),
                 "small": (self._calib(0.5, outcomes=5), prof),
                 "no_tolerance": (self._calib(0.5), {})}
        for name, (extra, p) in cases.items():
            body = run(*build(self.root / name, extra=extra, profile=p))
            self.assertEqual(found(body, "calibration_drift"), [], name)
            self.assertEqual(cov(body)["calibration_drift"], "partial", name)

    def test_calibration_not_applicable_when_no_model_valued_policy(self):
        body = run(*build(self.root, extra={POLICY: [pol("A1"), pol("L1")]}))
        self.assertEqual(cov(body)["calibration_drift"], "not_applicable")
        body = run(*build(self.root / "lead", extra={POLICY: [pol("A1"), pol("L1", value_type="proxy lead value")]}))
        self.assertEqual(cov(body)["calibration_drift"], "skipped")

    # ---------------------------------------------------------------- step 8
    def test_refund_adjustments_with_policy_treatment_queue_review(self):
        adj = [{"account_id": "c1", "action_id": "A1", "order_token": "o1", "adjustment_attempt_id": "adj1",
                "adjustment_type": "RETRACTION", "status": "ACCEPTED", "source_reference": "log-1"}]
        body = run(*build(self.root, extra={POLICY: [pol("A1", refund_treatment="netted at import")],
                                           "external/conversion_adjustments.csv": adj}))
        r = reviews(body, "refund_double_deduction_risk")
        self.assertEqual(len(r), 1)
        self.assertIn("adj1", r[0]["evidence"]["evidence_refs"])
        self.assertEqual(body["counts"]["Warning"] + body["counts"]["Critical"], 0)
        adj[0]["adjustment_type"] = "ENHANCEMENT"
        body = run(*build(self.root / "ok", extra={POLICY: [pol("A1", refund_treatment="netted at import")],
                                                  "external/conversion_adjustments.csv": adj}))
        self.assertEqual(reviews(body, "refund_double_deduction_risk"), [])

    # ---------------------------------------------------------------- missing evidence / CLI
    def test_base_fixture_skips_external_checks_and_exits_zero(self):
        out = self.root / "out"
        p = subprocess.run([sys.executable, str(SCRIPT), "run", "--export", str(FIXTURE / "export"),
                            "--profile", str(FIXTURE / "profile.yaml"), "--out", str(out)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        body = json.loads((out / "result.json").read_text())
        c = {x["check"]: x for x in body["coverage"]}
        self.assertEqual(c["payload_policy_qa"]["status"], "skipped")
        self.assertIn("external/value_payload_qa (file)", c["payload_policy_qa"]["missing"])
        self.assertEqual(c["failure_classification"]["status"], "skipped")
        self.assertNotIn("completed", {c[k]["status"] for k in c if k != "value_goal_map"})

    def test_finalize_critical_requires_supplied_evidence_ref(self):
        rows = full_qa("A1")
        rows[0] = qa("A1-ordinary", "A1", "ordinary", 100, 90)
        ex, prof = build(self.root, extra={POLICY: [pol("A1"), pol("L1")], QA: rows})
        out = self.root / "out"
        base = ["--export", str(ex), "--profile", str(prof), "--out", str(out)]
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), "run", *base], capture_output=True).returncode, 0)
        rid = reviews(json.loads((out / "result.json").read_text()), "material_value_corruption")[0]["id"]

        def finalize(proposal):
            d = self.root / "decisions.json"
            d.write_text(json.dumps([{"id": rid, "outcome": "material_value_corruption_confirmed",
                                      "rationale": "finance ledger shows material loss", "proposal": proposal}]))
            return subprocess.run([sys.executable, str(SCRIPT), "finalize", *base, "--decisions", str(d)],
                                  capture_output=True, text=True).returncode

        self.assertEqual(finalize({}), 4)
        self.assertEqual(finalize({"evidence_ref": "invented-ref"}), 4)
        self.assertEqual(finalize({"evidence_ref": "A1-ordinary"}), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
