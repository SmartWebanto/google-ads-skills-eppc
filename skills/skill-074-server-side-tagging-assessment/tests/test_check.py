"""test_check.py — decision boundaries of skill-074 server-side tagging checks (stdlib unittest, temp folders).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-074-server-side-tagging-assessment/tests -t skills/skill-074-server-side-tagging-assessment
rules:   Synthetic evidence only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_074", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def main(args) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(M.SKILL, M.VERSION, M.run, M.verify, args)


ACCOUNT = {"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
ARCH_COLS = ["account_id", "site_id", "component_id", "deployment_version", "client_or_server", "event_destinations",
             "hosting_region", "consent_forwarding_design", "retention_policy_reference", "access_control_status",
             "monitoring_owner", "operational_owner", "monthly_cost", "migration_effort_estimate", "currency"]
TRIAL_COLS = ["trial_id", "site_id", "scenario", "variant", "device_class", "run_id", "traffic_assignment_method",
              "browser_class", "network_profile", "cache_state", "consent_scope", "eligible_events", "observed_events",
              "main_thread_ms", "lcp_ms", "sample_size", "confounders", "source_reference"]
REQ_COLS = ["site_id", "requirement_id", "requirement", "success_metric", "accepted_threshold", "alternative_design",
            "operating_capacity", "approved_policy_reference", "owner", "decision_deadline"]


def _write(path: Path, rows, cols) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def comp(site, cid, kind="server", **kw):
    base = {"account_id": "demo", "site_id": site, "component_id": cid, "deployment_version": "v1",
            "client_or_server": kind, "event_destinations": "Google Ads", "consent_forwarding_design": "forward state",
            "retention_policy_reference": "ret-1", "access_control_status": "restricted", "monitoring_owner": "ops",
            "operational_owner": "eng", "monthly_cost": "100", "currency": "EUR", "migration_effort_estimate": "M"}
    return {**base, **kw}


def trial(site, variant, eligible, observed, **kw):
    base = {"trial_id": "T1", "site_id": site, "scenario": "checkout", "variant": variant, "device_class": "mobile",
            "run_id": "1", "traffic_assignment_method": "random split", "browser_class": "chrome",
            "network_profile": "4g", "cache_state": "cold", "consent_scope": "granted", "eligible_events": eligible,
            "observed_events": observed, "main_thread_ms": "100", "sample_size": "1000", "source_reference": "lab-1"}
    return {**base, **kw}


class ServerSideTaggingTests(unittest.TestCase):
    def make(self, arch=None, trials=None, reqs=None, manifest=True) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        exp = self.root / "export"
        _write(exp / "account.csv", [ACCOUNT], list(ACCOUNT))
        _write(exp / "conversion_actions.csv", [{"id": "1", "status": "ENABLED"}], ["id", "status"])
        files = ["account.csv", "conversion_actions.csv"]
        for name, rows, cols in (("tagging_architecture", arch, ARCH_COLS), ("tagging_measurement_trials", trials, TRIAL_COLS),
                                 ("tagging_decision_requirements", reqs, REQ_COLS)):
            if rows is not None:
                _write(exp / "external" / f"{name}.csv", rows, cols)
                files.append(f"external/{name}.csv")
        if manifest:
            _write(exp / "table_manifest.csv", [{"filename": f, "completeness": "complete"} for f in files],
                   ["filename", "completeness"])
        return exp

    def run_check(self, exp) -> dict:
        self.assertEqual(main(["run", "--export", str(exp), "--out", str(self.root / "out")]), 0)
        return json.loads((self.root / "out" / "result.json").read_text())

    @staticmethod
    def keys(body, sev=None):
        return sorted((f["condition_key"], f["entity"].get("site_id")) for f in body["findings"]
                      if sev is None or f["severity"] == sev)

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_client_only_site_is_info_only_with_attested_inventory(self):
        body = self.run_check(self.make([comp("S", "c1", "client")], trials=[]))
        self.assertEqual(self.keys(body), [("no_server_side_deployment", "S")])
        body = self.run_check(self.make([comp("S", "c1", "client")], trials=[], manifest=False))
        self.assertEqual(self.keys(body), [])
        self.assertEqual(self.cov(body)["decision_proposal"], "partial")

    def test_documented_unassigned_owner_warns_named_owner_goes_to_review(self):
        body = self.run_check(self.make([comp("A", "s1", monitoring_owner="unassigned"), comp("B", "s1")]))
        self.assertEqual(self.keys(body, "Warning"), [("ownership_risk", "A")])
        rev = [(r["condition_key"], r["entity"]["site_id"]) for r in body["ai_review"]]
        self.assertIn(("readiness_risk", "B"), rev)
        self.assertNotIn(("readiness_risk", "A"), rev)

    def test_empty_owner_is_unknown_not_a_defect(self):
        body = self.run_check(self.make([comp("A", "s1", monitoring_owner="")]))
        self.assertEqual(self.keys(body, "Warning"), [])
        self.assertEqual(self.cov(body)["operational_readiness"], "partial")

    def test_consent_forwarding_absent_warns(self):
        body = self.run_check(self.make([comp("A", "s1", consent_forwarding_design="not forwarded")]))
        self.assertIn(("consent_propagation_risk", "A"), self.keys(body, "Warning"))

    def test_comparable_trial_difference_is_info_non_comparable_is_descriptive(self):
        ok = [trial("A", "client", "100", "90"), trial("A", "server", "100", "98")]
        bad = [trial("B", "client", "100", "90"), trial("B", "server", "100", "98", network_profile="wifi")]
        body = self.run_check(self.make([comp("A", "s1"), comp("B", "s1")], ok + bad))
        info = self.keys(body, "Info")
        self.assertIn(("measured_trial_supports_evaluation", "A"), info)
        self.assertNotIn(("measured_trial_supports_evaluation", "B"), info)
        self.assertEqual(self.cov(body)["trial_comparability"], "partial")

    def test_shortfall_triggers_review_full_delivery_does_not(self):
        body = self.run_check(self.make([comp("A", "s1")], [trial("A", "client", "100", "80"),
                                                            trial("B", "client", "100", "100")]))
        sites = [r["entity"]["site_id"] for r in body["ai_review"] if r["condition_key"] == "measured_current_problem"]
        self.assertEqual(sites, ["A"])

    def test_zero_eligible_events_is_undefined_not_shortfall(self):
        body = self.run_check(self.make([comp("A", "s1")], [trial("A", "client", "0", "0")]))
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "measured_current_problem"], [])
        obs = next(o["data"] for o in body["observations"] if o["check"] == "measured_problem")
        self.assertIsNone(obs["variants"]["client"]["delivery_rate"])

    def test_mixed_currency_costs_are_not_summed(self):
        body = self.run_check(self.make([comp("A", "s1"), comp("A", "s2", currency="USD", monthly_cost="50")]))
        obs = next(o["data"] for o in body["observations"] if o["check"] == "operating_cost")
        self.assertEqual(obs["monthly_cost"], {"EUR": 100, "USD": 50})
        self.assertEqual(self.cov(body)["operating_cost"], "partial")

    def test_requirements_without_trials_are_unmeasured_info(self):
        reqs = [{"site_id": "A", "requirement_id": "R1", "requirement": "fewer lost events", "owner": "o"}]
        body = self.run_check(self.make([comp("A", "s1")], trials=[trial("Z", "client", "1", "1")], reqs=reqs))
        self.assertIn(("unmeasured_claimed_benefit", "A"), self.keys(body, "Info"))

    def test_missing_architecture_skips(self):
        body = self.run_check(self.make())
        cov = self.cov(body)
        for c in ("architecture_inventory", "operational_readiness", "operating_cost", "decision_proposal"):
            self.assertEqual(cov[c], "skipped")
        self.assertEqual(body["findings"], [])

    def test_finalize_critical_requires_evidence_ref(self):
        exp = self.make([comp("A", "s1")], [trial("A", "client", "100", "50")])
        body = self.run_check(exp)
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "measured_current_problem")
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(exp), "--out", str(self.root / "out"), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": rid, "outcome": "material_failure_evidenced", "rationale": "r"}]))
        self.assertEqual(main(args), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "documented_risk", "rationale": "r"}]))
        self.assertEqual(main(args), 0)


if __name__ == "__main__":
    unittest.main()
