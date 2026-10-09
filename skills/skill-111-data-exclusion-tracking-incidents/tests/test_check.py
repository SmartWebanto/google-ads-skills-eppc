"""test_check.py — skill-111 decision boundaries: incident qualification, eligibility, lag window, overlap, review, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-111-data-exclusion-tracking-incidents/tests
rules:   Temp folders only; stdlib only; never reads the selftest oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check tests
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
_spec = importlib.util.spec_from_file_location("check111", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["check111"] = mod
_spec.loader.exec_module(mod)

TZ = "Europe/Rome"
EXT = "external/"


def _write(path: Path, rows: list[dict], cols: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or (list(rows[0]) if rows else ["id"])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def incident(**kw) -> dict:
    row = {"incident_id": "INC1", "account_id": "c1", "campaign_id": "101", "action_id": "A1", "device": "MOBILE",
           "channel": "SEARCH", "status_suspected_or_confirmed": "confirmed", "detected_at": "2026-08-12T21:00",
           "fault_start": "2026-08-10T08:00", "fault_end": "2026-08-12T20:00", "timezone": TZ,
           "timestamp_precision": "hour", "fault_type": "tag removed in deploy", "expected_behavior": "purchase fires",
           "observed_behavior": "no purchase events", "evidence_reference": "QA-1", "recovery_verified_at": "2026-08-13",
           "backfill_status": "none", "material_impact_evidence": "IMPACT-1", "owner": "ops"}
    row.update(kw)
    return row


def eligibility(**kw) -> dict:
    row = {"account_id": "c1", "campaign_id": "101", "strategy_id": "", "snapshot": "2026-09-10",
           "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_CPA", "control_available": "true",
           "allowed_scope_types": "CAMPAIGN;CUSTOMER", "supported_device_scope": "MOBILE;DESKTOP;TABLET",
           "allowed_date_window": "2026-07-01/2026-09-10", "source_reference": "help-2026-09", "verified_at": "2026-09-09"}
    row.update(kw)
    return row


def impact_rows(**kw) -> list[dict]:
    spec = [("2026-08-08", 0, 0.1, 0.2), ("2026-08-09", 0.1, 0.3, 0.5), ("2026-08-10", 0.5, 0.8, 1),
            ("2026-08-11", 0.5, 0.8, 1), ("2026-08-12", 0.5, 0.8, 1), ("2026-08-13", 0, 0, 0)]
    out = []
    for d, lo, est, hi in spec:
        r = {"incident_id": "INC1", "account_id": "c1", "campaign_id": "101", "action_id": "A1", "device": "MOBILE",
             "interaction_date": d, "expected_conversions": 5, "observed_conversions": 1, "affected_clicks": 40,
             "affected_cost": 60, "lag_distribution_reference": "LAG-Q2", "estimated_impacted_fraction": est,
             "estimation_method": "lag cdf", "lower_bound": lo, "upper_bound": hi, "reporting_mature": "true",
             "currency": "EUR"}
        r.update(kw)
        out.append(r)
    return out


def exclusion(**kw) -> dict:
    row = {"exclusion_id": "X1", "account_id": "c1", "campaign_id": "101", "device": "MOBILE", "scope_type": "CAMPAIGN",
           "strategy_id_if_relevant": "", "start_datetime": "2026-08-08T00:00", "end_datetime": "2026-08-12T23:59",
           "timezone": TZ, "status": "ENABLED", "affected_devices": "MOBILE", "source_reference": "ui-export",
           "created_at": "2026-08-14", "owner": "ops"}
    row.update(kw)
    return row


def recovery(**kw) -> dict:
    row = {"incident_id": "INC1", "account_id": "c1", "campaign_id": "101", "repair_verified": "true",
           "repair_verified_at": "2026-08-13", "backfill_expected": "false", "backfill_complete": "false",
           "residual_bad_data": "true", "current_strategy_state": "learning", "proposed_control_rationale": "bids fell",
           "exclusion_overlap_risk": "low", "owner": "ops"}
    row.update(kw)
    return row


CFG_COLS = list(exclusion())


def build(root: Path, *, incidents=None, elig=None, impact=None, config=None, recov=None, manifest=True,
          unlisted=()) -> tuple[Path, Path]:
    """Complete default scenario: one confirmed eligible incident on campaign 101, no exclusion."""
    ex = root / "export"
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "time_zone": TZ,
                                 "date_range_start": "2026-08-01", "date_range_end": "2026-08-31",
                                 "snapshot_date": "2026-09-10", "rates_format": "fraction", "money_unit": "currency",
                                 "conversion_date_basis": "interaction_date", "conversion_lag_days": 2}])
    _write(ex / "campaigns.csv", [{"customer_id": "c1", "id": c, "status": "ENABLED", "channel_type": "SEARCH",
                                   "bidding_strategy_type": "TARGET_CPA"} for c in ("101", "102", "103")])
    _write(ex / "campaign_metrics.csv", [{"customer_id": "c1", "campaign_id": c, "clicks": 1000, "cost": 2000}
                                         for c in ("101", "102", "103")])
    files = {"account.csv": 1, "campaigns.csv": 1, "campaign_metrics.csv": 1}
    tables = {"tracking_incidents": [incident()] if incidents is None else incidents,
              "data_exclusion_eligibility": [eligibility()] if elig is None else elig,
              "incident_click_impact": impact_rows() if impact is None else impact,
              "data_exclusion_config": [] if config is None else config,
              "incident_recovery_review": [recovery()] if recov is None else recov}
    for name, rows in tables.items():
        if rows is False:
            continue
        _write(ex / "external" / f"{name}.csv", rows, CFG_COLS if name == "data_exclusion_config" and not rows else None)
        if name not in unlisted:
            files[f"external/{name}.csv"] = 1
    if manifest:
        _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                           for f in files])
    prof = root / "profile.json"
    prof.write_text(json.dumps({"conversion_lag_days": 2}))
    return ex, prof


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def findings(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def reviews(body: dict, key: str) -> list[dict]:
    return [r for r in body["ai_review"] if r["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    # ---------------------------------------------------------------- step 1 / missing evidence
    def test_missing_external_files_skip_every_check_without_findings(self):
        body = run(*build(self.root, incidents=False, elig=False, impact=False, config=False, recov=False))
        self.assertEqual(set(cov(body).values()), {"skipped"})
        self.assertEqual(body["findings"], [])
        missing = {c["check"]: c["missing"] for c in body["coverage"]}
        self.assertIn("external/tracking_incidents (file)", missing["exclusion_eligibility"])

    def test_suspected_or_unevidenced_incidents_never_reach_assessment(self):
        body = run(*build(self.root, incidents=[incident(status_suspected_or_confirmed="suspected"),
                                                incident(incident_id="INC2", evidence_reference="")]))
        c = cov(body)
        self.assertEqual(c["confirmed_incidents"], "completed")
        for chk in ("exclusion_eligibility", "click_window", "exclusion_overlap", "recovery_assessment"):
            self.assertEqual(c[chk], "not_applicable", chk)
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["ai_review"], [])

    def test_no_confirmed_incident_in_unattested_inventory_is_partial_not_na(self):
        body = run(*build(self.root, incidents=[incident(status_suspected_or_confirmed="suspected")],
                          unlisted=("tracking_incidents",)))
        self.assertEqual(cov(body)["recovery_assessment"], "partial")
        self.assertEqual(cov(body)["confirmed_incidents"], "partial")

    def test_confirmed_row_without_campaign_is_not_account_wide(self):
        body = run(*build(self.root, incidents=[incident(campaign_id="")]))
        self.assertEqual(cov(body)["confirmed_incidents"], "partial")
        self.assertEqual(body["ai_review"], [])

    # ---------------------------------------------------------------- step 2
    def test_eligible_campaign_has_no_eligibility_finding(self):
        body = run(*build(self.root))
        self.assertEqual(findings(body, "unsupported_eligibility") + findings(body, "unknown_eligibility"), [])

    def test_unsupported_and_unknown_eligibility_are_info(self):
        body = run(*build(self.root, elig=[eligibility(control_available="false")]))
        f = findings(body, "unsupported_eligibility")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertEqual(reviews(body, "exclusion_review_case"), [])
        body = run(*build(self.root, elig=[eligibility(control_available="")]))
        self.assertEqual([x["severity"] for x in findings(body, "unknown_eligibility")], ["Info"])

    def test_stale_channel_or_missing_source_is_unknown_not_eligible(self):
        body = run(*build(self.root, elig=[eligibility(channel_type="PERFORMANCE_MAX")]))
        self.assertEqual(len(findings(body, "unknown_eligibility")), 1)
        body = run(*build(self.root, elig=[eligibility(source_reference="")]))
        self.assertEqual(len(findings(body, "unknown_eligibility")), 1)
        self.assertEqual(reviews(body, "exclusion_review_case"), [])

    def test_missing_eligibility_row_is_partial_without_finding(self):
        body = run(*build(self.root, elig=[eligibility(campaign_id="102")]))
        self.assertEqual(cov(body)["exclusion_eligibility"], "partial")
        self.assertEqual(findings(body, "unknown_eligibility"), [])

    # ---------------------------------------------------------------- steps 4-5
    def test_lag_derived_window_uses_upper_bound_dates(self):
        body = run(*build(self.root))
        obs = [o for o in body["observations"] if o["check"] == "click_window"][0]["data"]
        self.assertEqual(obs["window"], ["2026-08-08", "2026-08-12"])
        self.assertEqual(obs["confident_dates"][0], "2026-08-09")
        self.assertEqual(findings(body, "uncertain_click_window"), [])
        self.assertEqual(cov(body)["click_window"], "completed")

    def test_undefensible_windows_are_info_prerequisites(self):
        cases = {"immature": dict(impact=impact_rows(reporting_mature="false")),
                 "no_bounds": dict(impact=impact_rows(lower_bound="")),
                 "no_lag_ref": dict(impact=impact_rows(lag_distribution_reference="")),
                 "open_fault": dict(incidents=[incident(fault_end="")]),
                 "tz_mismatch": dict(incidents=[incident(timezone="UTC")])}
        for name, kw in cases.items():
            with self.subTest(name):
                body = run(*build(self.root / name, **kw))
                f = findings(body, "uncertain_click_window")
                self.assertEqual([x["severity"] for x in f], ["Info"])
                self.assertEqual(reviews(body, "exclusion_review_case"), [])

    def test_impact_after_fault_end_is_not_defensible(self):
        rows = impact_rows()
        rows[-1].update(lower_bound=0.1, estimated_impacted_fraction=0.2, upper_bound=0.3)
        body = run(*build(self.root, impact=rows))
        self.assertEqual(len(findings(body, "uncertain_click_window")), 1)

    def test_absent_estimate_in_incomplete_table_is_partial_not_finding(self):
        body = run(*build(self.root, impact=impact_rows(campaign_id="102"), unlisted=("incident_click_impact",)))
        self.assertEqual(findings(body, "uncertain_click_window"), [])
        self.assertEqual(cov(body)["click_window"], "partial")

    # ---------------------------------------------------------------- step 3 / 6
    def test_exclusion_matching_evidence_is_not_overbroad(self):
        body = run(*build(self.root, config=[exclusion()]))
        self.assertEqual(findings(body, "exclusion_overbroad_or_misscoped"), [])
        self.assertEqual(cov(body)["exclusion_overlap"], "completed")

    def test_exclusion_beyond_window_is_warning_with_day_counts(self):
        body = run(*build(self.root, config=[exclusion(start_datetime="2026-08-01T00:00",
                                                       end_datetime="2026-08-31T23:59")]))
        f = findings(body, "exclusion_overbroad_or_misscoped")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual(f[0]["calculation"]["days_before_envelope"], 7)
        self.assertEqual(f[0]["calculation"]["days_after_envelope"], 19)

    def test_exclusion_on_extra_campaign_or_all_devices_is_misscoped(self):
        body = run(*build(self.root, config=[exclusion(campaign_id="101;102")]))
        f = findings(body, "exclusion_overbroad_or_misscoped")
        self.assertEqual(f[0]["calculation"]["extra_campaigns"], ["102"])
        body = run(*build(self.root / "d", config=[exclusion(affected_devices="ALL", device="ALL")]))
        self.assertEqual(len(findings(body, "exclusion_overbroad_or_misscoped")), 1)
        body = run(*build(self.root / "a", config=[exclusion(scope_type="CUSTOMER", campaign_id="")]))
        f = findings(body, "exclusion_overbroad_or_misscoped")
        self.assertEqual(f[0]["calculation"]["extra_campaigns"], ["102", "103"])

    def test_timezone_mismatch_makes_overlap_partial(self):
        body = run(*build(self.root, config=[exclusion(timezone="UTC", start_datetime="2026-08-01",
                                                       end_datetime="2026-08-31")]))
        self.assertEqual(findings(body, "exclusion_overbroad_or_misscoped"), [])
        self.assertEqual(findings(body, "no_exclusion_for_confirmed_incident"), [])
        self.assertEqual(cov(body)["exclusion_overlap"], "partial")

    def test_no_exclusion_is_info_only_when_config_complete(self):
        body = run(*build(self.root))
        self.assertEqual([x["severity"] for x in findings(body, "no_exclusion_for_confirmed_incident")], ["Info"])
        body = run(*build(self.root / "u", unlisted=("data_exclusion_config",)))
        self.assertEqual(findings(body, "no_exclusion_for_confirmed_incident"), [])
        self.assertEqual(cov(body)["existing_exclusions"], "partial")

    def test_unlinked_exclusion_goes_to_review_and_duplicates_are_observed(self):
        body = run(*build(self.root, config=[exclusion(exclusion_id="X9", campaign_id="103")]))
        r = reviews(body, "unlinked_exclusion")
        self.assertEqual(len(r), 1)
        self.assertIsNone(r[0]["outcomes"]["documented_elsewhere"]["severity"])
        body = run(*build(self.root / "dup", config=[exclusion(), exclusion(exclusion_id="X2")]))
        self.assertTrue(any("duplicate" in o["text"] for o in body["observations"]))

    # ---------------------------------------------------------------- step 7-9
    def test_residual_bad_data_on_eligible_incident_is_reviewed(self):
        body = run(*build(self.root))
        r = reviews(body, "exclusion_review_case")
        self.assertEqual(len(r), 1)
        sev = {k: v["severity"] for k, v in r[0]["outcomes"].items()}
        self.assertEqual(sev, {"exclusion_review_case": "Warning", "no_change": None, "uncertain": "Info"})
        self.assertEqual(cov(body)["proposal_scope"], "completed")
        self.assertEqual(cov(body)["monitoring_rollback"], "completed")

    def test_recovered_data_is_info_and_not_reviewed(self):
        for i, kw in enumerate((dict(residual_bad_data="false"), dict(backfill_complete="true"))):
            body = run(*build(self.root / str(i), recov=[recovery(**kw)]))
            self.assertEqual([x["severity"] for x in findings(body, "recovered_data")], ["Info"])
            self.assertEqual(reviews(body, "exclusion_review_case"), [])
            self.assertEqual(cov(body)["proposal_scope"], "not_applicable")

    def test_unknown_residual_state_is_partial(self):
        body = run(*build(self.root, recov=[recovery(residual_bad_data="")]))
        self.assertEqual(cov(body)["recovery_assessment"], "partial")
        self.assertEqual(reviews(body, "exclusion_review_case"), [])

    def test_ongoing_failure_offers_critical_only_with_impact_evidence(self):
        body = run(*build(self.root, recov=[recovery(repair_verified="false")]))
        r = reviews(body, "ongoing_measurement_failure")
        self.assertEqual(r[0]["outcomes"]["material_ongoing_failure"]["severity"], "Critical")
        body = run(*build(self.root / "n", incidents=[incident(material_impact_evidence="")],
                          recov=[recovery(repair_verified="false")]))
        self.assertEqual(reviews(body, "ongoing_measurement_failure"), [])
        self.assertEqual(body["counts"]["Critical"], 0)

    # ---------------------------------------------------------------- verify
    @staticmethod
    def _item(body, key):
        r = reviews(body, key)[0]
        return type("Item", (), {"evidence": r["evidence"], "entity": r["entity"]})()

    def good_proposal(self, **kw) -> dict:
        p = {"scope_type": "CAMPAIGN", "campaign_ids": ["101"], "devices": ["MOBILE"], "start": "2026-08-09",
             "end": "2026-08-12", "timezone": TZ, "unaffected_data": "08-09 partially affected",
             "monitoring": "watch CPA for 14 days", "rollback_criteria": "remove if backfill lands",
             "ui_semantics_ref": "UI shows inclusive end"}
        p.update(kw)
        return p

    def test_verify_proposal_boundaries(self):
        body = run(*build(self.root))
        item = self._item(body, "exclusion_review_case")
        ok = mod.verify(None, item, {"outcome": "exclusion_review_case", "proposal": self.good_proposal()})
        self.assertEqual(ok, [])
        bad = {"wider_window": dict(start="2026-08-01"),
               "account_scope_when_campaign_supported": dict(scope_type="CUSTOMER"),
               "unsupported_scope": dict(scope_type="CHANNEL"),
               "other_device": dict(devices=["DESKTOP"]),
               "all_devices": dict(devices=["ALL"]),
               "other_campaign": dict(campaign_ids=["101", "102"]),
               "wrong_tz": dict(timezone="UTC"),
               "no_rollback": dict(rollback_criteria=""),
               "reversed": dict(start="2026-08-12", end="2026-08-09")}
        for name, kw in bad.items():
            with self.subTest(name):
                self.assertTrue(mod.verify(None, item, {"outcome": "exclusion_review_case",
                                                        "proposal": self.good_proposal(**kw)}))

    def test_verify_allows_all_devices_only_when_specific_devices_unsupported(self):
        body = run(*build(self.root, elig=[eligibility(supported_device_scope="ALL")]))
        item = self._item(body, "exclusion_review_case")
        self.assertEqual(mod.verify(None, item, {"outcome": "exclusion_review_case",
                                                 "proposal": self.good_proposal(devices=["ALL"])}), [])

    def test_verify_respects_allowed_date_window(self):
        body = run(*build(self.root, elig=[eligibility(allowed_date_window="2026-08-10/2026-09-10")]))
        item = self._item(body, "exclusion_review_case")
        self.assertTrue(mod.verify(None, item, {"outcome": "exclusion_review_case",
                                                "proposal": self.good_proposal(start="2026-08-09")}))

    def _finalize(self, ex, prof, decisions) -> tuple[int, dict]:
        out = self.root / "out"
        args = [sys.executable, str(SCRIPT)]
        common = ["--export", str(ex), "--profile", str(prof), "--out", str(out)]
        subprocess.run(args + ["run"] + common, check=True, capture_output=True)
        body = json.loads((out / "result.json").read_text())
        dec = self.root / "decisions.json"
        dec.write_text(json.dumps(decisions(body)))
        p = subprocess.run(args + ["finalize"] + common + ["--decisions", str(dec)], capture_output=True, text=True)
        final = json.loads((out / "final.json").read_text()) if (out / "final.json").exists() else {}
        return p.returncode, final

    def test_finalize_critical_requires_matching_impact_evidence(self):
        ex, prof = build(self.root, recov=[recovery(repair_verified="false")])

        def dec(ref):
            return lambda body: [{"id": reviews(body, "ongoing_measurement_failure")[0]["id"],
                                  "outcome": "material_ongoing_failure", "rationale": "orders lost per CRM",
                                  "proposal": {"evidence_ref": ref} if ref else {}}]
        code, _ = self._finalize(ex, prof, dec(None))
        self.assertEqual(code, 4)
        code, _ = self._finalize(ex, prof, dec("QA-other"))
        self.assertEqual(code, 4)
        code, final = self._finalize(ex, prof, dec("IMPACT-1"))
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Critical"], 1)

    def test_finalize_exclusion_case_verifies_proposal(self):
        ex, prof = build(self.root)

        def dec(**kw):
            return lambda body: [{"id": reviews(body, "exclusion_review_case")[0]["id"],
                                  "outcome": "exclusion_review_case", "rationale": "residual corrupted days",
                                  "proposal": self.good_proposal(**kw)}]
        code, _ = self._finalize(ex, prof, dec(end="2026-08-20"))
        self.assertEqual(code, 4)
        code, final = self._finalize(ex, prof, dec())
        self.assertEqual(code, 0)
        self.assertEqual(len([f for f in final["findings"] if f["condition_key"] == "exclusion_review_case"]), 1)


if __name__ == "__main__":
    unittest.main()
