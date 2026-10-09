"""test_check.py — skill-112 decision boundaries: policy, dedupe, maturity, accepted value, semantics, failures, ROAS.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-112-return-refund-tracking/tests -t skills/skill-112-return-refund-tracking
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check112", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check112"] = mod
_spec.loader.exec_module(mod)

POLICY = "external/conversion_value_policy.csv"
LEDGER = "external/refund_ledger.csv"
ADJ = "external/conversion_adjustments.csv"
SUPPORT = "external/adjustment_support.csv"
DAILY = "custom/ads_reconciliation_daily.csv"


def _write(path: Path, rows: list[dict], cols: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or (list(rows[0]) if rows else ["account_id"])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def P(aid, basis="net", treatment="adjusted_afterward", currency="EUR"):
    return {"account_id": "c1", "action_id": aid, "policy_version": "v1", "gross_or_net_basis": basis,
            "refund_treatment": treatment, "currency": currency, "owner": "finance"}


def L(aid, order, token=None, status=None, refunded=None, E=None, original=100, purchase="2026-08-05",
      ts=None, currency="EUR"):
    return {"account_id": "c1", "action_id": aid, "order_token": order, "refund_token": token,
            "purchase_timestamp": purchase, "refund_timestamp": ts or ("2026-08-20" if token else None),
            "refund_status": status, "original_value": original, "refunded_value": refunded, "tax_refund": None,
            "shipping_refund": None, "expected_remaining_value": E, "currency": currency, "source_reference": "oms"}


def A(aid, order, att, typ="restatement", status="accepted", restated=None, prior=100, retry=None, method="order_id",
      currency="EUR", code=None, submitted="2026-09-10"):
    return {"account_id": "c1", "action_id": aid, "order_token": order, "adjustment_attempt_id": att,
            "adjustment_type": typ, "submitted_at": submitted, "processed_at": None,
            "original_record_match_method": method, "supported_identifier_present": "true",
            "prior_reported_value": prior, "restated_total_value": restated, "currency": currency, "status": status,
            "rejection_code": code, "retry_of_attempt_id": retry, "source_reference": f"log-{att}"}


def S(aid, restate="true", retract="true", methods="order_id"):
    return {"account_id": "c1", "action_id": aid, "source_type": "import", "snapshot": "2026-09-30",
            "supports_restatement": restate, "supports_retraction": retract, "accepted_match_method": methods,
            "eligibility_status": "eligible", "time_limit_reference": None, "source_reference": "doc", "owner": "x"}


def build(root: Path, *, policy=None, ledger=None, adj=None, support=None, daily=None, metrics=None, profile=None,
          unattested=(), snapshot="2026-09-30") -> tuple[Path, Path]:
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                 "date_range_start": "2026-08-01", "date_range_end": "2026-08-31",
                                 "snapshot_date": snapshot, "rates_format": "fraction", "money_unit": "currency",
                                 "conversion_date_basis": "conversion_date", "conversion_lag_days": 2}])
    files = ["account.csv"]
    for name, rows in ((POLICY, policy), (LEDGER, ledger), (ADJ, adj), (SUPPORT, support), (DAILY, daily),
                       ("campaign_metrics.csv", metrics)):
        if rows is not None:
            cols = {LEDGER: list(L("a", "o")), ADJ: list(A("a", "o", "t")), SUPPORT: list(S("a")),
                    POLICY: list(P("a"))}.get(name)
            _write(ex / name, rows, cols)
            files.append(name)
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                       for f in files if f not in unattested])
    p = root / "profile.json"
    p.write_text(json.dumps({"refund_maturity_days": 30, **(profile or {})}))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def found(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def obs(body: dict, check: str, prefix: str = "") -> list[dict]:
    return [o["data"] for o in body["observations"] if o["check"] == check and o["text"].startswith(prefix)]


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    # ------------------------------------------------------------------ missing evidence
    def test_missing_external_files_skip_every_check_without_findings(self):
        body = run(*build(self.root))
        self.assertEqual(set(cov(body).values()), {"skipped"})
        self.assertEqual(body["findings"], [])
        missing = {m for c in body["coverage"] for m in c["missing"]}
        self.assertIn("external/refund_ledger (file)", missing)

    def test_missing_ledger_column_is_named(self):
        ex, prof = build(self.root, policy=[P("a1")], ledger=[L("a1", "o1")])
        rows = [{k: v for k, v in L("a1", "o1").items() if k != "refund_token"}]
        _write(ex / LEDGER, rows)
        body = run(ex, prof)
        dedupe = next(c for c in body["coverage"] if c["check"] == "refund_dedupe")
        self.assertEqual((dedupe["status"], dedupe["missing"]), ("skipped", ["external/refund_ledger:refund_token"]))
        self.assertEqual(cov(body)["expected_remaining_value"], "skipped")

    # ------------------------------------------------------------------ step 1
    def test_gross_policy_is_info_and_never_valued_for_deduction(self):
        body = run(*build(self.root, policy=[P("g1", basis="gross", treatment="")],
                          ledger=[L("g1", "o1", "r1", "full", 100, 0)], adj=[]))
        self.assertEqual([f["severity"] for f in found(body, "gross_policy")], ["Info"])
        self.assertEqual(found(body, "no_return_imports"), [])
        self.assertEqual(obs(body, "expected_remaining_value")[0]["gross_orders_preserved"], 1)

    def test_unrecognized_refund_treatment_is_partial_not_guessed(self):
        body = run(*build(self.root, policy=[P("a1", treatment="sometimes")]))
        self.assertEqual(cov(body)["value_policy"], "partial")
        self.assertEqual(body["findings"], [])

    def test_netted_policy_plus_accepted_retraction_is_double_deduction(self):
        ledger = [L("n1", "o1", "r1", "partial", 40, 60)]
        body = run(*build(self.root, policy=[P("n1", treatment="netted_at_import")], ledger=ledger,
                          adj=[A("n1", "o1", "t1", "retraction", "accepted")]))
        self.assertEqual([f["severity"] for f in found(body, "double_deduction_candidate")], ["Warning"])
        item = next(r for r in body["ai_review"] if r["condition_key"] == "double_deduction_candidate")
        self.assertIn("t1", item["evidence"]["refs"])

    def test_rejected_or_submitted_adjustment_is_not_a_confirmed_double_deduction(self):
        ledger = [L("n1", "o1", "r1", "partial", 40, 60)]
        body = run(*build(self.root, policy=[P("n1", treatment="netted_at_import")], ledger=ledger,
                          adj=[A("n1", "o1", "t1", "retraction", "rejected")]))
        self.assertEqual(found(body, "double_deduction_candidate"), [])
        body = run(*build(self.root, policy=[P("n1", treatment="netted_at_import")], ledger=ledger,
                          adj=[A("n1", "o1", "t1", "retraction", "submitted")]))
        self.assertEqual(found(body, "double_deduction_candidate"), [])
        self.assertEqual([f["severity"] for f in found(body, "double_deduction_candidate_pending")], ["Info"])

    # ------------------------------------------------------------------ step 2
    def test_identical_duplicate_refund_rows_count_once(self):
        ledger = [L("a1", "o1", "r1", "partial", 60, 40)] * 2
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=[]))
        d = obs(body, "refund_dedupe")[0]
        self.assertEqual((d["duplicate_rows_collapsed"], d["over_refund"]), (1, []))
        self.assertEqual(obs(body, "expected_remaining_value", "Action a1")[0]["realized_refunds"], 60)
        self.assertEqual(cov(body)["refund_dedupe"], "completed")

    def test_conflicting_duplicate_refund_token_excludes_order(self):
        ledger = [L("a1", "o1", "r1", "partial", 60, 40), L("a1", "o1", "r1", "full", 100, 0)]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=[]))
        self.assertEqual(cov(body)["refund_dedupe"], "partial")
        self.assertEqual(obs(body, "expected_remaining_value", "Action a1")[0]["excluded_orders"], 1)

    def test_pending_and_canceled_refunds_are_not_realized(self):
        ledger = [L("a1", "o1", "r1", "canceled", 50, 100), L("a1", "o2", "r2", "pending", 50, 50)]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=[]))
        e = obs(body, "expected_remaining_value", "Action a1")[0]
        self.assertEqual((e["mature_orders"], e["immature_orders"], e["realized_refunds"]), (1, 1, 0))
        self.assertEqual(found(body, "immature_refunds")[0]["evidence"]["orders"], ["o2"])

    def test_currency_misaligned_ledger_row_is_excluded(self):
        body = run(*build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "full", 100, 0, currency="USD")],
                          adj=[]))
        self.assertEqual(cov(body)["refund_dedupe"], "partial")
        self.assertEqual(found(body, "no_return_imports"), [])

    # ------------------------------------------------------------------ step 3
    def test_immature_cohort_is_info_and_unresolved_horizon_is_partial(self):
        ledger = [L("a1", "o1", "r1", "full", 100, 0, purchase="2026-09-20")]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=[]))
        self.assertEqual([f["severity"] for f in found(body, "immature_refunds")], ["Info"])
        self.assertEqual(found(body, "no_return_imports"), [])
        ex, prof = build(self.root, policy=[P("a1")], ledger=ledger, adj=[])
        prof.write_text("{}")
        body = run(ex, prof)
        self.assertEqual(cov(body)["expected_remaining_value"], "partial")
        self.assertEqual(found(body, "immature_refunds"), [])

    # ------------------------------------------------------------------ step 4
    def test_accepted_restatement_matching_expected_value_is_clean(self):
        body = run(*build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "partial", 40, 60)],
                          adj=[A("a1", "o1", "t1", restated=60)], support=[S("a1")]))
        self.assertEqual(found(body, "accepted_value_mismatch"), [])
        self.assertEqual(obs(body, "accepted_vs_expected", "Action a1")[0]["matched"], 1)

    def test_accepted_value_differing_from_expected_is_warning(self):
        body = run(*build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "partial", 40, 60)],
                          adj=[A("a1", "o1", "t1", restated=70)], support=[S("a1")]))
        f = found(body, "accepted_value_mismatch")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertAlmostEqual(f[0]["evidence"]["orders"][0]["difference"], 10)

    def test_submitted_only_adjustment_is_pending_not_mismatch(self):
        body = run(*build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "partial", 40, 60)],
                          adj=[A("a1", "o1", "t1", status="submitted", restated=70)]))
        self.assertEqual(found(body, "accepted_value_mismatch"), [])
        self.assertEqual(obs(body, "accepted_vs_expected", "Action a1")[0]["pending_orders"], ["o1"])

    def test_no_return_imports_needs_attested_complete_adjustments(self):
        kw = dict(policy=[P("a1")], ledger=[L("a1", "o1", "r1", "full", 100, 0)], adj=[])
        body = run(*build(self.root, **kw))
        self.assertEqual([f["severity"] for f in found(body, "no_return_imports")], ["Info"])
        body = run(*build(self.root, unattested=(ADJ,), **kw))
        self.assertEqual(found(body, "no_return_imports"), [])
        self.assertEqual(cov(body)["accepted_vs_expected"], "partial")

    # ------------------------------------------------------------------ step 5
    def test_unknown_support_is_info_and_unsupported_method_goes_to_review(self):
        body = run(*build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "partial", 40, 60)],
                          adj=[A("a1", "o1", "t1", restated=60)], support=[]))
        self.assertEqual([f["severity"] for f in found(body, "unknown_adjustment_support")], ["Info"])
        body = run(*build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "partial", 40, 60)],
                          adj=[A("a1", "o1", "t1", restated=60, method="gclid")], support=[S("a1")]))
        self.assertEqual([f["severity"] for f in found(body, "unsupported_method_used")], ["Info"])
        item = next(r for r in body["ai_review"] if r["condition_key"] == "unsupported_method_used")
        self.assertEqual(item["outcomes"]["conflicts_with_supported_method"]["severity"], "Warning")
        self.assertIsNotNone(item["provisional_finding"])

    # ------------------------------------------------------------------ step 6
    def test_restatement_semantics(self):
        ledger = [L("a1", "o1", "r1", "partial", 40, 60), L("a1", "o2", "r2", "full", 100, 0)]
        ok = run(*build(self.root, policy=[P("a1")], ledger=ledger, support=[S("a1")],
                        adj=[A("a1", "o1", "t1", restated=60), A("a1", "o2", "t2", "retraction")]))
        self.assertEqual(found(ok, "retraction_restatement_mismatch"), [])
        bad = run(*build(self.root, policy=[P("a1")], ledger=ledger, support=[S("a1")],
                         adj=[A("a1", "o1", "t1", restated=40), A("a1", "o2", "t2", restated=-100)]))
        f = found(bad, "retraction_restatement_mismatch")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual(sorted(a["attempt"] for a in f[0]["evidence"]["attempts"]), ["t1", "t2"])
        retract = run(*build(self.root, policy=[P("a1")], ledger=ledger[:1], support=[S("a1")],
                             adj=[A("a1", "o1", "t1", "retraction")]))
        self.assertEqual(len(found(retract, "retraction_restatement_mismatch")), 1)

    # ------------------------------------------------------------------ step 7
    def test_repeated_supported_failures_boundary(self):
        ledger = [L("a1", "o1", "r1", "full", 100, 0), L("a1", "o2", "r2", "full", 100, 0)]
        one = [A("a1", "o1", "t1", "retraction", "rejected", code="NO_MATCH")]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=one, support=[S("a1")]))
        self.assertEqual(found(body, "supported_adjustments_repeatedly_fail"), [])
        two = one + [A("a1", "o2", "t2", "retraction", "rejected", code="NO_MATCH")]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=two, support=[S("a1")]))
        self.assertEqual([f["severity"] for f in found(body, "supported_adjustments_repeatedly_fail")], ["Warning"])
        resolved = two + [A("a1", "o1", "t3", "retraction", "accepted", retry="t1"),
                          A("a1", "o2", "t4", "retraction", "accepted", retry="t2")]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=resolved, support=[S("a1")]))
        self.assertEqual(found(body, "supported_adjustments_repeatedly_fail"), [])
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=two))
        self.assertEqual(found(body, "supported_adjustments_repeatedly_fail"), [])
        self.assertEqual([f["severity"] for f in found(body, "repeated_failures_support_unknown")], ["Info"])

    def test_retry_after_accepted_adjustment_blocks_proposal(self):
        ledger = [L("a1", "o1", "r1", "partial", 40, 60)]
        adj = [A("a1", "o1", "t1", restated=70), A("a1", "o1", "t2", status="submitted", restated=60, retry="t1",
                                                   submitted="2026-09-12")]
        body = run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=adj, support=[S("a1")]))
        fail = obs(body, "adjustment_failures", "Action a1")[0]
        self.assertEqual([x["attempt"] for x in fail["already_adjusted"]], ["t2"])
        prop = obs(body, "reconciliation_proposals")[0]
        self.assertEqual(prop["ready_for_owner_review"], [])
        self.assertIn("a1/o1", prop["blocked_until_resolved"])

    # ------------------------------------------------------------------ step 8
    def _roas(self, cost, actions=("a1",), overrides=1):
        ledger = [L("a1", "o1", "r1", "partial", 40, 60)]
        daily = [{"account_id": "c1", "campaign_id": "k1", "action_id": a, "date": "2026-08-10",
                  "conversion_value": 100, "reporting_mature": "true"} for a in actions]
        metrics = [{"campaign_id": "k1", "cost": cost}]
        return run(*build(self.root, policy=[P("a1")], ledger=ledger, adj=[A("a1", "o1", "t1", restated=70)],
                          support=[S("a1")], daily=daily, metrics=metrics,
                          profile={"parameter_overrides": {"min_conversions": overrides}}))

    def test_roas_difference_needs_attributable_nonzero_spend_and_sample(self):
        body = self._roas(20)
        o = obs(body, "residual_roas", "Action a1")[0]
        self.assertAlmostEqual(o["residual_value"], 10)
        self.assertAlmostEqual(o["roas_difference"], 0.5)
        self.assertIsNone(obs(self._roas(0), "residual_roas", "Action a1")[0]["roas_difference"])
        mixed = self._roas(20, actions=("a1", "a9"))
        self.assertIsNone(obs(mixed, "residual_roas", "Action a1")[0]["roas_difference"])
        self.assertEqual(cov(mixed)["residual_roas"], "partial")
        small = self._roas(20, overrides=5)
        self.assertIsNone(obs(small, "residual_roas", "Action a1")[0]["roas_difference"])

    # ------------------------------------------------------------------ verify / finalize
    def test_critical_outcome_requires_known_evidence_ref(self):
        ex, prof = build(self.root, policy=[P("a1")], ledger=[L("a1", "o1", "r1", "partial", 40, 60)],
                         adj=[A("a1", "o1", "t1", restated=70)], support=[S("a1")])
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                          ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        body = json.loads((out / "result.json").read_text())
        item = next(r for r in body["ai_review"] if r["condition_key"] == "accepted_value_mismatch")
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        for ref, code in ((None, 4), ("not-in-evidence", 4), ("log-t1", 0)):
            proposal = {"evidence_ref": ref} if ref else {}
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_confirmed", "rationale": "071 residual",
                                        "proposal": proposal}]))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), code, ref)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "accepted_value_mismatch"],
                         ["Critical"])


if __name__ == "__main__":
    unittest.main()
