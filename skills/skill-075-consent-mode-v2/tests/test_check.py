"""test_check.py — decision boundaries of skill-075 consent mode checks (stdlib unittest, temp folders).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-075-consent-mode-v2/tests -t skills/skill-075-consent-mode-v2
rules:   Synthetic evidence only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import io
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_075", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def main(args) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(M.SKILL, M.VERSION, M.run, M.verify, args)


ACCOUNT = {"customer_id": "demo", "currency_code": "EUR", "time_zone": "Europe/Rome", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
CFG_COLS = ["site_id", "region_rule_id", "deployment_version", "account_id", "chosen_mode_basic_or_advanced",
            "regional_scope", "default_ad_storage", "default_analytics_storage", "default_ad_user_data",
            "default_ad_personalization", "approved_policy_reference", "technical_owner", "privacy_owner",
            "wait_for_update_ms"]
TRC_COLS = ["test_id", "site_id", "region_rule_id", "deployment_version", "scenario", "sequence", "relative_ms",
            "consent_default_or_update", "tag_destination", "ad_storage", "analytics_storage", "ad_user_data",
            "ad_personalization", "request_class", "cookie_read_observed", "cookie_write_observed",
            "identifier_present", "payload_classification", "expected_behavior", "observed_behavior", "trace_reference"]
SCEN = ["fresh_no_choice", "deny", "accept", "partial", "withdrawal", "return_denied", "regional_default"]


def _write(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def cfg(site, mode="advanced", **kw):
    base = {"site_id": site, "region_rule_id": "IT", "deployment_version": "v1", "account_id": "demo",
            "chosen_mode_basic_or_advanced": mode, "regional_scope": "IT", "default_ad_storage": "denied",
            "default_analytics_storage": "denied", "default_ad_user_data": "denied",
            "default_ad_personalization": "denied", "approved_policy_reference": "policy-1",
            "technical_owner": "tech", "privacy_owner": "priv", "wait_for_update_ms": "500"}
    return {**base, **kw}


def trace(site, i, scenario, bad=False, **kw):
    granted = scenario == "accept"
    sig = "granted" if granted else "denied"
    leak = bad and not granted
    base = {"test_id": f"{site}-{i}", "site_id": site, "region_rule_id": "IT", "deployment_version": "v1",
            "scenario": scenario, "sequence": str(i), "relative_ms": str(i * 1000),
            "consent_default_or_update": "default" if i == 0 else "update", "tag_destination": "Google Ads",
            "ad_storage": sig, "analytics_storage": "granted" if scenario == "partial" else sig, "ad_user_data": sig,
            "ad_personalization": sig,
            "request_class": "full_identifier_payload" if (granted or leak) else "cookieless_ping",
            "cookie_read_observed": str(granted or leak), "cookie_write_observed": str(granted or leak),
            "identifier_present": str(granted or leak), "trace_reference": f"ref-{site}-{i}",
            "expected_behavior": "x", "observed_behavior": "y"}
    return {**base, **kw}


def site_traces(site, bad=False):
    return [trace(site, i, s, bad) for i, s in enumerate(SCEN)]


class ConsentCheckTests(unittest.TestCase):
    def make(self, configs=None, traces=None, manifest=True) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        exp = root / "export"
        _write(exp / "account.csv", [ACCOUNT], list(ACCOUNT))
        _write(exp / "conversion_actions.csv", [{"id": "purchase", "type": "WEBSITE", "status": "ENABLED"}],
               ["id", "type", "status"])
        files = ["account.csv", "conversion_actions.csv"]
        if configs is not None:
            _write(exp / "external" / "consent_configuration.csv", configs, CFG_COLS)
            files.append("external/consent_configuration.csv")
        if traces is not None:
            _write(exp / "external" / "consent_traces.csv", traces, TRC_COLS)
            files.append("external/consent_traces.csv")
        if manifest:
            _write(exp / "table_manifest.csv", [{"filename": f, "completeness": "complete"} for f in files],
                   ["filename", "completeness"])
        self.root = root
        return exp

    def run_check(self, exp: Path) -> dict:
        out = self.root / "out"
        code = main(["run", "--export", str(exp), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    @staticmethod
    def keys(body, sev=None):
        return sorted((f["condition_key"], f["entity"].get("site_id")) for f in body["findings"]
                      if sev is None or f["severity"] == sev)

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_denied_state_leak_is_warning_with_critical_review_only(self):
        body = self.run_check(self.make([cfg("BAD"), cfg("OK")], site_traces("BAD", bad=True) + site_traces("OK")))
        self.assertIn(("denied_state_storage_or_identifier", "BAD"), self.keys(body, "Warning"))
        self.assertIn(("advanced_cookieless_matches_design", "OK"), self.keys(body, "Info"))
        self.assertNotIn("OK", [k[1] for k in self.keys(body, "Warning")])
        self.assertEqual(body["counts"]["Critical"], 0)
        crit = [r for r in body["ai_review"] if any(o["severity"] == "Critical" for o in r["outcomes"].values())]
        self.assertEqual([r["entity"]["site_id"] for r in crit], ["BAD"])

    def test_single_violating_trace_gets_no_critical_review(self):
        traces = site_traces("ONE")
        traces[1] = trace("ONE", 1, "deny", bad=True)
        body = self.run_check(self.make([cfg("ONE")], traces))
        self.assertIn(("denied_state_storage_or_identifier", "ONE"), self.keys(body, "Warning"))
        self.assertEqual(body["ai_review"], [])

    def test_advanced_prefire_cookieless_is_not_a_defect(self):
        body = self.run_check(self.make([cfg("OK")], site_traces("OK")))
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_unknown_storage_observation_is_partial_not_pass(self):
        traces = site_traces("U")
        traces[1]["cookie_write_observed"] = ""
        body = self.run_check(self.make([cfg("U")], traces))
        self.assertEqual(self.cov(body)["advanced_denied_behavior"], "partial")
        self.assertEqual(self.keys(body), [])

    def test_explicit_missing_signal_warns_but_empty_signal_is_unknown(self):
        body = self.run_check(self.make([cfg("M", default_ad_user_data="not_set"), cfg("E", default_ad_user_data="")],
                                        site_traces("M") + site_traces("E")))
        warn = self.keys(body, "Warning")
        self.assertIn(("required_signal_missing", "M"), warn)
        self.assertNotIn(("required_signal_missing", "E"), warn)
        self.assertEqual(self.cov(body)["signal_completeness"], "partial")

    def test_accept_scenario_recording_denied_is_incorrect_update(self):
        traces = site_traces("UPD")
        traces[2]["ad_personalization"] = "denied"
        body = self.run_check(self.make([cfg("UPD")], traces))
        self.assertIn(("incorrect_consent_update", "UPD"), self.keys(body, "Warning"))

    def test_basic_mode_request_under_denied_storage(self):
        bad = [trace("B", 0, "fresh_no_choice", request_class="cookieless_ping")]
        good = [trace("G", 0, "fresh_no_choice", request_class="blocked")]
        body = self.run_check(self.make([cfg("B", "basic"), cfg("G", "basic")], bad + good))
        warn = self.keys(body, "Warning")
        self.assertIn(("basic_mode_tag_not_blocked", "B"), warn)
        self.assertNotIn(("basic_mode_tag_not_blocked", "G"), warn)

    def test_measurement_before_default_ordering(self):
        traces = site_traces("ORD")
        traces[0]["relative_ms"] = "500"
        traces[1]["relative_ms"] = "100"  # update-row request before the first default
        body = self.run_check(self.make([cfg("ORD")], traces))
        self.assertIn(("measurement_before_default", "ORD"), self.keys(body, "Warning"))

    def test_untested_scenarios_make_coverage_partial(self):
        body = self.run_check(self.make([cfg("S")], site_traces("S")[:3]))
        self.assertEqual(self.cov(body)["ordering_and_scenarios"], "partial")

    def test_missing_traces_skip_dependent_checks(self):
        body = self.run_check(self.make([cfg("X")], None))
        cov = self.cov(body)
        self.assertEqual(cov["scope_mode_map"], "completed")
        for c in ("signal_completeness", "advanced_denied_behavior", "ordering_and_scenarios", "trace_corroboration"):
            self.assertEqual(cov[c], "skipped")
        self.assertEqual(body["findings"], [])

    def test_missing_policy_reference_is_partial(self):
        body = self.run_check(self.make([cfg("P", approved_policy_reference="")], site_traces("P")))
        self.assertEqual(self.cov(body)["scope_mode_map"], "partial")

    def test_finalize_critical_requires_evidence_ref(self):
        exp = self.make([cfg("BAD")], site_traces("BAD", bad=True))
        body = self.run_check(exp)
        rid = body["ai_review"][0]["id"]
        out = self.root / "out"
        dec = self.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "prohibited_material_evidenced", "rationale": "r"}]))
        args = ["finalize", "--export", str(exp), "--out", str(out), "--decisions", str(dec)]
        self.assertEqual(main(args), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "prohibited_material_evidenced", "rationale": "r",
                                    "proposal": {"evidence_ref": "ref-BAD-1"}}]))
        self.assertEqual(main(args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
