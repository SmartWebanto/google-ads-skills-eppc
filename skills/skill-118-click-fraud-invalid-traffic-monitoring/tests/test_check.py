"""test_check.py — skill-118 decision boundaries: native denominator, weekday baseline, #83 alert, hourly, billing, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-118-click-fraud-invalid-traffic-monitoring/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial tests
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
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check118", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check118"] = mod
_spec.loader.exec_module(mod)

START, END = date(2026, 8, 17), date(2026, 8, 30)  # recent window: two complete weeks
BASE_START = START - timedelta(days=56)
DAILY_COLS = ["customer_id", "campaign_id", "date", "network", "impressions", "clicks", "cost", "conversions",
              "invalid_clicks", "invalid_click_rate", "denominator_definition"]
BILL_COLS = ["customer_id", "adjustment_or_case_id", "service_start", "service_end", "billed_cost",
             "invalid_activity_credit", "currency", "case_status", "confirmed_charged_invalid_amount", "evidence_ref",
             "checked_at"]
INC_COLS = ["customer_id", "incident_id", "time_bucket", "campaign_id", "bucket_start", "bucket_end", "timezone",
            "clicks", "privacy_safe_source_id", "location_basis", "suspicious_behavior", "charge_link_ref",
            "collection_authorization_ref"]


def _write(path: Path, rows: list[dict], cols=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or (list(rows[0]) if rows else ["id"])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def daily(base=(90, 10, 1000), recent=(90, 10, 1000), defn="clicks_plus_invalid_clicks", rate=True, drop=()):
    rows = []
    d = BASE_START
    while d <= END:
        clicks, inv, impr = recent if d >= START else base
        if d not in drop:
            rows.append({"customer_id": "c1", "campaign_id": "C1", "date": d.isoformat(), "network": "SEARCH",
                         "impressions": impr, "clicks": clicks, "cost": clicks, "conversions": 1,
                         "invalid_clicks": inv,
                         "invalid_click_rate": round(inv / (clicks + inv), 6) if rate is True else rate,
                         "denominator_definition": defn})
        d += timedelta(days=1)
    return rows


def case(cid="K1", status="confirmed", billed=500, credit=100, confirmed=300, ref="stmt-K1", checked="2026-09-01",
         currency="EUR"):
    return {"customer_id": "c1", "adjustment_or_case_id": cid, "service_start": START.isoformat(),
            "service_end": END.isoformat(), "billed_cost": billed, "invalid_activity_credit": credit,
            "currency": currency, "case_status": status, "confirmed_charged_invalid_amount": confirmed,
            "evidence_ref": ref, "checked_at": checked}


def bucket(iid="I1", start="2026-08-20T14:00:00", end="2026-08-20T15:00:00", link="", behavior="rapid_repeat_clicks",
           src="src-hash-1", auth="auth-2026-08"):
    return {"customer_id": "c1", "incident_id": iid, "time_bucket": start, "campaign_id": "C1", "bucket_start": start,
            "bucket_end": end, "timezone": "Europe/Rome", "clicks": 40, "privacy_safe_source_id": src,
            "location_basis": "ip_country", "suspicious_behavior": behavior, "charge_link_ref": link,
            "collection_authorization_ref": auth}


def build(root: Path, *, daily_rows=None, billing=None, incidents=None, profile=None, incomplete=()) -> tuple[Path, Path]:
    ex = root / "export"
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                 "date_range_start": START.isoformat(), "date_range_end": END.isoformat(),
                                 "snapshot_date": "2026-09-02", "rates_format": "fraction", "money_unit": "currency",
                                 "conversion_date_basis": "interaction_date", "conversion_lag_days": 2}])
    _write(ex / "campaigns.csv", [{"customer_id": "c1", "id": "C1", "name": "Search", "status": "ENABLED"}])
    files = ["account.csv", "campaigns.csv"]
    if daily_rows is not None:
        _write(ex / "custom" / "invalid_click_daily.csv", daily_rows, DAILY_COLS)
        files.append("custom/invalid_click_daily.csv")
    if billing is not None:
        _write(ex / "external" / "invalid_traffic_billing.csv", billing, BILL_COLS)
        files.append("external/invalid_traffic_billing.csv")
    if incidents is not None:
        _write(ex / "external" / "traffic_incidents.csv", incidents, INC_COLS)
        files.append("external/traffic_incidents.csv")
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "partial" if f in incomplete else "complete",
                                        "truncation": "none"} for f in files])
    p = root / "profile.json"
    p.write_text(json.dumps(profile or {}))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def found(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def obs(body: dict, check: str, text: str) -> list[dict]:
    return [o["data"] for o in body["observations"] if o["check"] == check and text in o["text"]]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def cli(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, list(args))

    def finalize(self, ex, prof, out, decisions) -> int:
        dec = self.root / "decisions.json"
        dec.write_text(json.dumps(decisions))
        return self.cli("finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec))

    # ------------------------------------------------------------------ missing evidence
    def test_missing_evidence_skips_every_check_and_exits_zero(self):
        ex, prof = build(self.root)
        out = self.root / "out"
        self.assertEqual(self.cli("run", "--export", str(ex), "--profile", str(prof), "--out", str(out)), 0)
        body = json.loads((out / "result.json").read_text())
        self.assertEqual(set(cov(body).values()), {"skipped"})
        self.assertEqual(body["findings"], [])
        pack = [c for c in body["coverage"] if c["check"] == "support_review_pack"][0]
        self.assertIn("external/invalid_traffic_billing (file)", pack["missing"])

    # ------------------------------------------------------------------ step 1 native denominator
    def test_paid_click_rate_is_ignored_and_native_rate_recomputed(self):
        rows = daily(recent=(90, 10, 1000), defn="paid_clicks", rate=round(10 / 90, 6))
        body = run(*build(self.root, daily_rows=rows))
        o = obs(body, "native_invalid_rate", "native invalid-click rate")[0]
        self.assertAlmostEqual(o["native_invalid_rate"], 0.1)
        self.assertEqual(o["native_denominator"], 1400)
        self.assertEqual(o["rejected_paid_click_rates"], 14)

    def test_unknown_denominator_definition_is_partial_without_rate(self):
        body = run(*build(self.root, daily_rows=daily(defn="mixed"),
                          profile={"invalid_click_rate_alert": 0.01}))
        self.assertEqual(cov(body)["native_invalid_rate"], "partial")
        self.assertEqual(obs(body, "native_invalid_rate", "native invalid-click rate"), [])
        self.assertEqual(found(body, "elevated_filtered_invalid_rate"), [])

    def test_native_rate_derives_missing_count_only_from_native_definition(self):
        rows = daily(recent=(90, 10, 1000))
        for r in rows:
            if r["date"] >= START.isoformat():
                r["invalid_clicks"] = ""
        o = obs(run(*build(self.root, daily_rows=rows)), "native_invalid_rate", "native invalid-click rate")[0]
        self.assertAlmostEqual(o["native_invalid_rate"], 0.1)
        self.assertEqual(o["derived_invalid_rows"], 14)
        for r in rows:
            r["denominator_definition"] = "paid_clicks"
        body = run(*build(self.root, daily_rows=rows))
        self.assertEqual(cov(body)["native_invalid_rate"], "partial")
        self.assertEqual(obs(body, "native_invalid_rate", "native invalid-click rate"), [])

    # ------------------------------------------------------------------ index #83 alert
    def test_rate_alert_boundary_and_sample_gate(self):
        prof = {"invalid_click_rate_alert": 0.15}
        body = run(*build(self.root, daily_rows=daily(recent=(80, 20, 1000)), profile=prof))
        f = found(body, "elevated_filtered_invalid_rate")
        self.assertEqual([x["severity"] for x in f], ["Info"])
        self.assertAlmostEqual(f[0]["evidence"]["native_invalid_rate"], 0.2)
        body = run(*build(self.root, daily_rows=daily(recent=(90, 10, 1000)), profile=prof))
        self.assertEqual(found(body, "elevated_filtered_invalid_rate"), [])
        body = run(*build(self.root, daily_rows=daily(recent=(4, 3, 100)), profile=prof))  # 98 native clicks < 100
        self.assertEqual(found(body, "elevated_filtered_invalid_rate"), [])

    def test_rate_alert_without_declared_threshold_is_partial(self):
        body = run(*build(self.root, daily_rows=daily(recent=(50, 50, 1000))))
        self.assertEqual(cov(body)["invalid_rate_alert"], "partial")
        self.assertEqual(found(body, "elevated_filtered_invalid_rate"), [])

    # ------------------------------------------------------------------ step 2 weekday baseline
    def test_baseline_elevation_is_info_and_flat_traffic_is_not(self):
        prof = {"invalid_rate_change_alert": 0.5, "ctr_change_alert": 0.5}
        body = run(*build(self.root, daily_rows=daily(recent=(180, 45, 1000)), profile=prof))
        self.assertEqual(cov(body)["weekday_network_baseline"], "completed")
        inv = found(body, "elevated_filtered_invalid_rate_vs_baseline")
        ctr = found(body, "elevated_ctr_vs_baseline")
        self.assertEqual([x["severity"] for x in inv + ctr], ["Info", "Info"])
        self.assertAlmostEqual(inv[0]["evidence"]["invalid_rate_relative_change"], 1.0)
        self.assertAlmostEqual(ctr[0]["evidence"]["ctr_relative_change"], 1.0)
        body = run(*build(self.root, daily_rows=daily(), profile=prof))
        self.assertEqual(found(body, "elevated_filtered_invalid_rate_vs_baseline") + found(body, "elevated_ctr_vs_baseline"), [])
        self.assertAlmostEqual(obs(body, "weekday_network_baseline", "weekday")[0]["invalid_rate_relative_change"], 0.0)

    def test_baseline_needs_both_sides_above_sample_gate(self):
        rows = daily(base=(4, 1, 50), recent=(60, 40, 1000))  # baseline 280 native clicks, rate 0.2 → 0.4
        prof = {"invalid_rate_change_alert": 0.5, "parameter_overrides": {"min_clicks": 300}}
        body = run(*build(self.root, daily_rows=rows, profile=prof))
        self.assertEqual(found(body, "elevated_filtered_invalid_rate_vs_baseline"), [])
        self.assertFalse(obs(body, "weekday_network_baseline", "weekday")[0]["invalid_sample_gate_passed"])
        prof["parameter_overrides"]["min_clicks"] = 250
        body = run(*build(self.root, daily_rows=rows, profile=prof))
        self.assertEqual(len(found(body, "elevated_filtered_invalid_rate_vs_baseline")), 1)

    def test_baseline_incomplete_weeks_or_manifest_block_comparison(self):
        prof = {"invalid_rate_change_alert": 0.5}
        body = run(*build(self.root, daily_rows=daily(recent=(80, 20, 1000), drop=(BASE_START,)), profile=prof))
        self.assertEqual(cov(body)["weekday_network_baseline"], "partial")
        self.assertEqual(found(body, "elevated_filtered_invalid_rate_vs_baseline"), [])
        body = run(*build(self.root, daily_rows=daily(recent=(80, 20, 1000)), profile=prof,
                          incomplete=("custom/invalid_click_daily.csv",)))
        self.assertEqual(cov(body)["weekday_network_baseline"], "partial")
        self.assertEqual(found(body, "elevated_filtered_invalid_rate_vs_baseline"), [])

    def test_total_network_rows_are_not_double_counted(self):
        rows = daily(recent=(90, 10, 1000))
        rows += [{**r, "network": "ALL"} for r in rows]
        o = obs(run(*build(self.root, daily_rows=rows)), "native_invalid_rate", "native invalid-click rate")
        self.assertEqual([(x["network"], x["native_denominator"]) for x in o], [("SEARCH", 1400)])

    # ------------------------------------------------------------------ step 3 hourly
    def test_hourly_requires_hourly_authorized_privacy_safe_buckets(self):
        rows = [bucket("I1", end="2026-08-20T16:00:00"), bucket("I2", src="203.0.113.7"), bucket("I3", auth="")]
        body = run(*build(self.root, incidents=rows))
        self.assertEqual(cov(body)["hourly_bursts"], "partial")
        self.assertEqual([f for f in body["findings"] if f["check"] == "hourly_bursts"], [])
        self.assertEqual(obs(body, "hourly_bursts", "Hourly incident totals")[0]["incident_groups"], 0)

    def test_suspicious_bucket_without_charge_link_is_info(self):
        body = run(*build(self.root, incidents=[bucket()]))
        self.assertEqual([f["severity"] for f in found(body, "suspicious_activity_without_charge_link")], ["Info"])
        body = run(*build(self.root, incidents=[bucket(behavior="none")]))
        self.assertEqual([f for f in body["findings"] if f["check"] == "hourly_bursts"], [])

    def test_charge_linked_incident_unresolved_depends_on_complete_billing(self):
        inc = [bucket(link="INV-778")]
        body = run(*build(self.root, incidents=inc, billing=[case(credit=300)]))
        self.assertEqual([f["severity"] for f in found(body, "unresolved_billing_linked_suspicious_activity")], ["Warning"])
        body = run(*build(self.root, incidents=inc, billing=[case(credit=300)],
                          incomplete=("external/invalid_traffic_billing.csv",)))
        self.assertEqual(found(body, "unresolved_billing_linked_suspicious_activity"), [])
        self.assertEqual(len(found(body, "suspicious_activity_resolution_unknown")), 1)

    # ------------------------------------------------------------------ step 4 billing
    def test_confirmed_material_residual_after_credits_is_critical(self):
        body = run(*build(self.root, billing=[case()]))
        f = found(body, "confirmed_material_charged_invalid_after_credits")
        self.assertEqual([x["severity"] for x in f], ["Critical"])
        self.assertAlmostEqual(f[0]["evidence"]["residual_after_credits"], 200)

    def test_credited_or_immaterial_confirmed_cases_are_not_critical(self):
        for credit, confirmed in ((300, 300), (100, 120)):
            body = run(*build(self.root, billing=[case(credit=credit, confirmed=confirmed)]))
            self.assertEqual(found(body, "confirmed_material_charged_invalid_after_credits"), [], (credit, confirmed))
            self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "charged_invalid_case_review"], [])

    def test_other_currency_case_is_excluded(self):
        body = run(*build(self.root, billing=[case(currency="USD")]))
        self.assertEqual(found(body, "confirmed_material_charged_invalid_after_credits"), [])
        self.assertEqual(cov(body)["billing_reconciliation"], "partial")

    def test_unresolved_case_warning_needs_charge_link(self):
        body = run(*build(self.root, billing=[case(status="open", confirmed="", credit=0)]))
        self.assertEqual([f["severity"] for f in found(body, "unresolved_billing_linked_suspicious_activity")], ["Warning"])
        body = run(*build(self.root, billing=[case(status="open", billed=0, confirmed="", credit=0)]))
        self.assertEqual(found(body, "unresolved_billing_linked_suspicious_activity"), [])
        self.assertEqual([f["severity"] for f in found(body, "unresolved_case_without_charge_link")], ["Info"])
        body = run(*build(self.root, billing=[case(status="open", billed=0, confirmed="", credit=0)],
                          incidents=[bucket(link="K1")]))
        f = found(body, "unresolved_billing_linked_suspicious_activity")
        self.assertEqual([(x["entity"], x["evidence"]["linked_incidents"]) for x in f], [({"case_id": "K1"}, ["I1"])])

    def test_case_without_evidence_ref_goes_to_verified_review(self):
        ex, prof = build(self.root, billing=[case(ref=""), case("K2", credit=300, confirmed=300, ref="stmt-K2")])
        out = self.root / "out"
        self.assertEqual(self.cli("run", "--export", str(ex), "--profile", str(prof), "--out", str(out)), 0)
        body = json.loads((out / "result.json").read_text())
        self.assertEqual(found(body, "confirmed_material_charged_invalid_after_credits"), [])
        item = [r for r in body["ai_review"] if r["condition_key"] == "charged_invalid_case_review"][0]
        crit = {"id": item["id"], "outcome": "confirmed_material_after_credits", "rationale": "statement"}
        self.assertEqual(self.finalize(ex, prof, out, [{**crit, "proposal": {"case_id": "K1"}}]), 4)
        self.assertEqual(self.finalize(ex, prof, out, [{**crit, "proposal": {"case_id": "K1", "evidence_ref": "made-up"}}]), 4)
        self.assertEqual(self.finalize(ex, prof, out, [{**crit, "proposal": {"case_id": "K1", "evidence_ref": "stmt-K2",
                                                                             "action": "pause_campaign"}}]), 4)
        self.assertEqual(self.finalize(ex, prof, out, [{**crit, "proposal": {"case_id": "K1", "evidence_ref": "stmt-K2"}}]), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "charged_invalid_case_review"],
                         ["Critical"])

    # ------------------------------------------------------------------ step 5 pack + control proposals
    def test_control_proposal_needs_relevance_privacy_and_owner(self):
        ex, prof = build(self.root, incidents=[bucket(link="K1")],
                         billing=[case(status="open", billed=200, confirmed="", credit=0)])
        out = self.root / "out"
        self.assertEqual(self.cli("run", "--export", str(ex), "--profile", str(prof), "--out", str(out)), 0)
        body = json.loads((out / "result.json").read_text())
        items = [o for o in body["observations"] if o["check"] == "support_review_pack" and "Support-review item" in o["text"]]
        self.assertEqual(sorted(o["data"]["kind"] for o in items), ["billing_case", "suspicious_hourly_activity"])
        item = [r for r in body["ai_review"] if r["condition_key"] == "control_proposal_review"][0]
        good = {"control_type": "ip", "request_only": True, "scope_campaign_ids": ["C1"], "relevance_evidence_ref": "K1",
                "privacy_review_ref": "auth-2026-08", "supported_control_ref": "ads-help-ip-exclusions",
                "approval_owner": "client-marketing-lead", "monitoring": "weekly invalid rate", "recovery": "remove if valid"}
        dec = {"id": item["id"], "outcome": "control_review_requested", "rationale": "linked open case"}
        for bad in ({"privacy_review_ref": "dpo-ok"}, {"approval_owner": ""}, {"relevance_evidence_ref": "ip_country"},
                    {"request_only": False}, {"scope_campaign_ids": ["C9"]}):
            self.assertEqual(self.finalize(ex, prof, out, [{**dec, "proposal": {"controls": [{**good, **bad}]}}]), 4, bad)
        self.assertEqual(self.finalize(ex, prof, out, [{**dec, "proposal": {"controls": [good]}}]), 0)


if __name__ == "__main__":
    unittest.main()
