"""test_check.py — skill-110 decision boundaries: maturity cutoff, like-weekday drop screen, sample gates, incidents.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-110-conversion-tracking-breakage/tests
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
_spec = importlib.util.spec_from_file_location("check110", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check110"] = mod
_spec.loader.exec_module(mod)

START = date(2026, 7, 20)
END = date(2026, 9, 2)        # period end; snapshot 2026-09-06 with lag 2 → cutoff 2026-09-02
RECENT_START = END - timedelta(days=6)


def _write(path: Path, rows: list[dict], cols=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or (list(rows[0]) if rows else ["id"])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def build(root: Path, *, recent_conv=1, base_conv=4, recent_clicks=50, base_clicks=50, actions=("a1",),
          lag=2, immature_recent=False, silent_recent=False, daily_complete=True, traffic=True, context=None,
          incidents=None) -> tuple[Path, Path]:
    ex = root / "export"
    acct = {"customer_id": "111-222-3333", "currency_code": "EUR", "time_zone": "Europe/Rome",
            "date_range_start": START.isoformat(), "date_range_end": END.isoformat(), "snapshot_date": "2026-09-06",
            "rates_format": "fraction", "money_unit": "currency", "conversion_date_basis": "interaction_date",
            "conversion_lag_days": "" if lag is None else lag}
    _write(ex / "account.csv", [acct])
    _write(ex / "conversion_actions.csv", [{"id": a, "name": f"purchase {a}", "category": "PURCHASE",
                                            "status": "ENABLED"} for a in actions])
    daily, tr = [], []
    for d in _days():
        recent = d >= RECENT_START
        for a in actions:
            if recent and silent_recent:
                continue
            daily.append({"account_id": "111-222-3333", "campaign_id": "1001", "action_id": a, "date": d.isoformat(),
                          "date_basis": "interaction_date", "device": "MOBILE", "channel": "SEARCH",
                          "conversions": recent_conv if recent else base_conv,
                          "conversion_value": 10 * (recent_conv if recent else base_conv),
                          "all_conversions": recent_conv if recent else base_conv,
                          "reporting_mature": "false" if recent and immature_recent else "true", "currency": "EUR"})
        tr.append({"account_id": "111-222-3333", "campaign_id": "1001", "date": d.isoformat(), "device": "MOBILE",
                   "channel": "SEARCH", "impressions": 1000, "clicks": recent_clicks if recent else base_clicks,
                   "cost": 40, "currency": "EUR"})
    _write(ex / "custom" / "tracking_daily.csv", daily, mod.DAILY_COLS)
    files = ["account.csv", "conversion_actions.csv"] + (["custom/tracking_daily.csv"] if daily_complete else [])
    if traffic:
        _write(ex / "custom" / "tracking_traffic_daily.csv", tr)
        files.append("custom/tracking_traffic_daily.csv")
    if context is not None:
        _write(ex / "external" / "tracking_context.csv", context, mod.CONTEXT_COLS)
        files.append("external/tracking_context.csv")
    if incidents is not None:
        _write(ex / "external" / "tracking_incidents.csv", incidents, mod.INCIDENT_COLS + ["recovery_verified_at",
                                                                                          "backfill_status"])
        files.append("external/tracking_incidents.csv")
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none",
                                        "period_start": START.isoformat(), "period_end": END.isoformat()}
                                       for f in files])
    p = root / "profile.json"
    p.write_text(json.dumps({}))
    return ex, p


def full_context(lag_hours=None) -> list[dict]:
    return [{"account_id": "111-222-3333", "campaign_id": "1001", "action_id": "a1", "date": d.isoformat(),
             "business_outcomes": 5, "eligible_sessions": 300, "expected_weekday_pattern": "flat",
             "promotion_status": "none", "site_availability": "up", "deployment_id": "none",
             "budget_or_goal_change": "none", "consent_change": "none",
             "expected_reporting_lag_hours": lag_hours, "source_reference": f"crm-{d.isoformat()}"} for d in _days()]


def incident(iid="inc1", status="confirmed", ref="qa-trace-7", precision="day", material=None, recovered=None,
             backfill="pending") -> dict:
    return {"incident_id": iid, "account_id": "111-222-3333", "campaign_id": "1001", "action_id": "a1",
            "device": "", "channel": "", "status_suspected_or_confirmed": status, "detected_at": "2026-08-30",
            "fault_start": "2026-08-27", "fault_end": "", "timezone": "Europe/Rome", "timestamp_precision": precision,
            "fault_type": "tag_missing", "expected_behavior": "purchase tag fires", "observed_behavior": "no hits",
            "evidence_reference": ref, "material_impact_evidence": material, "owner": "web team",
            "recovery_verified_at": recovered, "backfill_status": backfill}


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def keys(body: dict) -> list[str]:
    return sorted(f["condition_key"] for f in body["findings"])


def cli(args) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args)


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_mature_gated_drop_over_half_is_screening_warning_with_cause_review(self):
        body = run(*build(self.root, recent_conv=1, context=full_context()))
        f = [x for x in body["findings"] if x["condition_key"] == "mature_conversion_drop_screen"]
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertAlmostEqual(f[0]["evidence"]["drop"], 0.75)
        self.assertEqual(f[0]["evidence"]["window"]["recent"], [RECENT_START.isoformat(), END.isoformat()])
        item = [r for r in body["ai_review"] if r["condition_key"] == "anomaly_cause"][0]
        self.assertEqual(item["provisional_finding"], f[0]["id"])
        self.assertEqual(item["outcomes"]["uncertain"]["severity"], "Warning")
        self.assertEqual(cov(body)["drop_screen"], "completed")

    def test_moderate_and_exact_half_drops_do_not_trigger(self):
        for recent in (3, 2):  # 25% drop, exactly 50% drop
            with self.subTest(recent=recent):
                body = run(*build(self.root / str(recent), recent_conv=recent, context=full_context()))
                self.assertNotIn("mature_conversion_drop_screen", keys(body))
                self.assertEqual(body["ai_review"], [])

    def test_sparse_baseline_is_info_not_warning(self):
        body = run(*build(self.root, base_conv=0.5, recent_conv=0, context=full_context()))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        f = [x for x in body["findings"] if x["condition_key"] == "insufficient_series_evidence"]
        self.assertEqual([x["severity"] for x in f], ["Info"])

    def test_click_gate_applies_to_recent_side(self):
        body = run(*build(self.root, recent_conv=0, recent_clicks=10, context=full_context()))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        self.assertIn("insufficient_series_evidence", keys(body))

    def test_immature_recent_rows_block_screen(self):
        body = run(*build(self.root, recent_conv=0, immature_recent=True, context=full_context()))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        self.assertIn("insufficient_series_evidence", keys(body))

    def test_unknown_lag_disables_screen(self):
        body = run(*build(self.root, recent_conv=0, lag=None, context=full_context()))
        self.assertEqual(keys(body), ["maturity_undetermined"])
        self.assertEqual(cov(body)["maturity_cutoff"], "partial")

    def test_context_reporting_lag_moves_cutoff_back(self):
        # 240h lag → cutoff 2026-08-27: the silent recent days are excluded, earlier week is normal.
        body = run(*build(self.root, recent_conv=0, context=full_context(lag_hours=240)))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        obs = [o for o in body["observations"] if o["check"] == "maturity_cutoff"][0]["data"]
        self.assertEqual(obs["cutoffs"], ["2026-08-27"])

    def test_missing_rows_are_zero_only_when_manifest_complete(self):
        body = run(*build(self.root / "c", silent_recent=True, context=full_context()))
        f = [x for x in body["findings"] if x["condition_key"] == "mature_conversion_drop_screen"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["evidence"]["conversions_recent"], 0)
        body = run(*build(self.root / "p", silent_recent=True, daily_complete=False, context=full_context()))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        self.assertEqual(cov(body)["action_series"], "partial")

    def test_traffic_missing_blocks_warning_and_divergence(self):
        body = run(*build(self.root, recent_conv=0, traffic=False, context=full_context()))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        c = {x["check"]: x for x in body["coverage"]}
        self.assertEqual(c["drop_screen"]["status"], "partial")
        self.assertIn("custom/tracking_traffic_daily (file)", c["drop_screen"]["missing"])
        self.assertEqual(c["click_conversion_divergence"]["status"], "skipped")

    def test_traffic_is_not_summed_across_action_rows(self):
        body = run(*build(self.root, recent_conv=1, actions=("a1", "a2"), context=full_context()))
        f = [x for x in body["findings"] if x["condition_key"] == "mature_conversion_drop_screen"]
        self.assertEqual(len(f), 2)
        self.assertEqual({x["evidence"]["clicks_recent"] for x in f}, {350})

    def test_stable_conversions_with_doubled_clicks_is_divergence_review(self):
        body = run(*build(self.root, recent_conv=3, recent_clicks=100, context=full_context()))
        self.assertNotIn("mature_conversion_drop_screen", keys(body))
        item = [r for r in body["ai_review"] if r["condition_key"] == "anomaly_cause"]
        self.assertEqual(len(item), 1)
        self.assertEqual(item[0]["outcomes"]["uncertain"]["severity"], "Info")
        self.assertIsNone(item[0]["provisional_finding"])
        self.assertAlmostEqual(item[0]["evidence"]["cvr_ratio"], 0.375)

    def test_missing_controls_lower_confidence(self):
        body = run(*build(self.root / "n", recent_conv=1))
        self.assertIn("missing_contextual_controls", keys(body))
        self.assertEqual(cov(body)["cause_attribution"], "partial")
        body = run(*build(self.root / "y", recent_conv=1, context=full_context()))
        self.assertNotIn("missing_contextual_controls", keys(body))

    def test_explanation_requires_supplied_reference(self):
        ex, prof = build(self.root, recent_conv=1, context=full_context())
        out = self.root / "out"
        self.assertEqual(cli(["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        item = [r for r in json.loads((out / "result.json").read_text())["ai_review"]
                if r["condition_key"] == "anomaly_cause"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "business_or_reporting_explained",
                                    "rationale": "promo", "proposal": {"evidence_ref": "invented"}}]))
        self.assertEqual(cli(args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "business_or_reporting_explained",
                                    "rationale": "crm shows demand drop", "proposal": {"evidence_ref": "crm-2026-09-01"}}]))
        self.assertEqual(cli(args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertNotIn("mature_conversion_drop_screen", keys(final))

    def test_confirmed_incident_warning_day_precision_and_routing(self):
        body = run(*build(self.root, context=full_context(), incidents=[incident(), incident("inc2", "suspected")]))
        f = {(x["condition_key"], x["entity"]["incident_id"]): x["severity"] for x in body["findings"]
             if "incident_id" in x["entity"]}
        self.assertEqual(f[("confirmed_tracking_fault", "inc1")], "Warning")
        self.assertEqual(f[("timestamp_precision_limit", "inc1")], "Info")
        self.assertNotIn(("confirmed_tracking_fault", "inc2"), f)
        routed = [o["data"] for o in body["observations"] if o["check"] == "route_to_111" and "incident_id" in o["data"]]
        self.assertEqual([o["incident_id"] for o in routed], ["inc1"])
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "material_tracking_failure"], [])

    def test_confirmed_without_evidence_reference_is_not_confirmed(self):
        body = run(*build(self.root, incidents=[incident(ref="", precision="hour")]))
        self.assertNotIn("confirmed_tracking_fault", keys(body))
        self.assertEqual(cov(body)["incident_confirmation"], "partial")

    def test_hour_precision_has_no_precision_limit(self):
        body = run(*build(self.root, incidents=[incident(precision="hour")]))
        self.assertIn("confirmed_tracking_fault", keys(body))
        self.assertNotIn("timestamp_precision_limit", keys(body))

    def test_critical_requires_matching_material_evidence_ref(self):
        ex, prof = build(self.root, context=full_context(), incidents=[incident(material="crm-loss-report-9")])
        out = self.root / "out"
        self.assertEqual(cli(["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        item = [r for r in json.loads((out / "result.json").read_text())["ai_review"]
                if r["condition_key"] == "material_tracking_failure"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_failure_confirmed", "rationale": "big",
                                    "proposal": {"evidence_ref": "other-doc"}}]))
        self.assertEqual(cli(args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_failure_confirmed", "rationale": "big",
                                    "proposal": {"evidence_ref": "crm-loss-report-9"}}]))
        self.assertEqual(cli(args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertIn("Critical", [x["severity"] for x in final["findings"]])

    def test_recovery_after_cutoff_is_not_yet_verifiable(self):
        body = run(*build(self.root, incidents=[incident(recovered="2026-09-02"), incident("inc3", recovered=None)]))
        f = [x for x in body["findings"] if x["condition_key"] == "recovery_not_yet_mature"]
        self.assertEqual([x["entity"]["incident_id"] for x in f], ["inc1"])
        open_obs = [o for o in body["observations"] if o["check"] == "recovery_verification"
                    and o["data"].get("incident_id") == "inc3"]
        self.assertTrue(open_obs[0]["text"].endswith("recovery not verified"))
        body = run(*build(self.root / "r", incidents=[incident(recovered="2026-08-29")]))
        self.assertNotIn("recovery_not_yet_mature", keys(body))

    def test_absent_evidence_is_skipped_never_completed(self):
        ex = self.root / "export"
        _write(ex / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-05",
                                     "conversion_lag_days": 2}])
        body = run(ex, None)
        self.assertEqual(set(cov(body).values()), {"skipped"})
        self.assertEqual(keys(body), [])


if __name__ == "__main__":
    unittest.main()
