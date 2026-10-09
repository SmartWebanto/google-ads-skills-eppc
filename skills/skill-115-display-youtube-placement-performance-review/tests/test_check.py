"""test_check.py — skill-115 decision boundaries: denominators, zero-conversion gates, restrictions, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-115-display-youtube-placement-performance-review/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
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
_spec = importlib.util.spec_from_file_location("check115", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["check115"] = mod
_spec.loader.exec_module(mod)

PD_COLS = ["account_id", "campaign_id", "ad_group_id", "date", "placement_id", "format", "placement_type",
           "URL_or_app_id", "app_category_id", "category_source", "network", "objective", "impressions", "clicks",
           "cost", "conversions", "conversion_value"]
PV_COLS = ["account_id", "campaign_id", "ad_group_id", "date", "placement_id", "format", "video_views",
           "native_view_rate", "denominator_name", "denominator_count", "eligible_video_impressions",
           "measurable_impressions", "viewable_impressions", "measurement_definition"]
PC_COLS = ["account_id", "scope_type", "scope_id", "control_id", "snapshot_at", "control_type",
           "placement_or_category_id", "enabled", "included_or_excluded", "inherited_from", "supported_subtypes",
           "source_screen"]
PP_COLS = ["policy_id", "placement_or_category_id", "campaign_scope", "suitability_rationale", "evidence_ref",
           "approved_by", "valid_from", "valid_to"]
CAMPAIGNS = [{"id": "C1", "channel_type": "DISPLAY", "status": "ENABLED", "goal_ids": "purchase", "target_cpa": ""},
             {"id": "V1", "channel_type": "VIDEO", "status": "ENABLED", "goal_ids": "purchase", "target_cpa": ""},
             {"id": "P1", "channel_type": "PERFORMANCE_MAX", "status": "ENABLED", "goal_ids": "purchase",
              "target_cpa": ""}]


def _write(path: Path, rows: list[dict], cols=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or (list(rows[0]) if rows else ["id"])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def drow(cid, pid, **kw) -> dict:
    row = {"account_id": "c1", "campaign_id": cid, "ad_group_id": "G1", "date": "2026-08-10", "placement_id": pid,
           "format": "display", "placement_type": "WEBSITE", "URL_or_app_id": pid, "app_category_id": "",
           "category_source": "", "network": "DISPLAY", "objective": "purchase", "impressions": 1000, "clicks": 10,
           "cost": 10, "conversions": 1, "conversion_value": 50}
    row.update(kw)
    return row


def vrow(cid, pid, **kw) -> dict:
    row = {c: "" for c in PV_COLS}
    row.update({"account_id": "c1", "campaign_id": cid, "ad_group_id": "G1", "date": "2026-08-10", "placement_id": pid,
                "format": "skippable_instream", "measurement_definition": "view-based skippable format"})
    row.update(kw)
    return row


def build(root: Path, *, daily=None, video=None, controls=None, policy=None, metrics=None, profile=None,
          snapshot="2026-09-06", tracking=True, incomplete=()) -> tuple[Path, Path]:
    ex = root / "export"
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                 "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                 "snapshot_date": snapshot, "rates_format": "fraction", "money_unit": "currency",
                                 "conversion_date_basis": "interaction_date", "conversion_lag_days": 2}])
    _write(ex / "campaigns.csv", CAMPAIGNS)
    files = ["account.csv", "campaigns.csv", "campaign_metrics.csv"]
    if metrics is None:
        metrics = {}
        for r in daily or []:
            metrics[r["campaign_id"]] = metrics.get(r["campaign_id"], 0) + float(r["cost"] or 0)
    _write(ex / "campaign_metrics.csv", [{"campaign_id": k, "cost": v} for k, v in sorted(metrics.items())],
           ["campaign_id", "cost"])
    if tracking:
        _write(ex / "conversion_actions.csv", [{"id": "purchase", "name": "Purchase", "category": "PURCHASE",
                                                "status": "ENABLED", "last_conversion_date": "2026-08-29"}])
        files.append("conversion_actions.csv")
    for rel, rows, cols in (("custom/placement_daily.csv", daily, PD_COLS),
                            ("custom/placement_video_metrics.csv", video, PV_COLS),
                            ("custom/placement_controls.csv", controls, PC_COLS),
                            ("external/placement_policy.csv", policy, PP_COLS)):
        if rows is not None:
            _write(ex / rel, rows, cols)
            files.append(rel)
    _write(ex / "table_manifest.csv",
           [{"filename": f, "completeness": "partial" if f in incomplete else "complete", "truncation": "none",
             "period_end": "2026-09-06"} for f in files])
    p = root / "profile.json"
    p.write_text(json.dumps(profile or {}))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def findings(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def reviews(body: dict, key: str) -> list[dict]:
    return [r for r in body["ai_review"] if r["condition_key"] == key]


def obs(body: dict, check: str) -> list[dict]:
    return [o for o in body["observations"] if o["check"] == check]


def ctl(cid, target, *, scope_type="campaign", mode="EXCLUDED", enabled="true", subtypes="DISPLAY"):
    return {"account_id": "c1", "scope_type": scope_type, "scope_id": cid, "control_id": f"k-{scope_type}-{target}",
            "snapshot_at": "2026-09-06", "control_type": "placement", "placement_or_category_id": target,
            "enabled": enabled, "included_or_excluded": mode, "inherited_from": "", "supported_subtypes": subtypes,
            "source_screen": "content suitability"}


POLICY = {"policy_id": "pol1", "placement_or_category_id": "bad.example", "campaign_scope": "all",
          "suitability_rationale": "brand safety", "evidence_ref": "brand-safety-2026", "approved_by": "cmo",
          "valid_from": "2026-07-01", "valid_to": ""}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def finalize(self, ex, prof, decisions) -> int:
        out = self.root / "out"
        dec = self.root / "decisions.json"
        dec.write_text(json.dumps(decisions))
        return subprocess.run([sys.executable, str(SCRIPT), "finalize", "--export", str(ex), "--profile", str(prof),
                               "--out", str(out), "--decisions", str(dec)], capture_output=True, text=True).returncode

    def run_cli(self, ex, prof) -> dict:
        out = self.root / "out"
        proc = subprocess.run([sys.executable, str(SCRIPT), "run", "--export", str(ex), "--profile", str(prof),
                               "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads((out / "result.json").read_text())

    # -------------------------------------------------------------- missing evidence
    def test_missing_placement_evidence_is_skipped_not_passed(self):
        body = run(*build(self.root))
        status = cov(body)
        for check in ("cost_reconciliation", "placement_ledger", "zero_conversion_screen", "video_view_rate",
                      "restricted_exposure", "proposal_readiness"):
            self.assertEqual(status[check], "skipped", check)
        missing = {m for c in body["coverage"] for m in c["missing"]}
        self.assertIn("custom/placement_daily (file)", missing)
        self.assertIn("external/placement_policy (file)", missing)
        self.assertEqual(body["findings"], [])

    # -------------------------------------------------------------- step 1
    def test_reconciliation_reports_share_and_rejects_overcount(self):
        daily = [drow("C1", "a.example", cost=300)]
        body = run(*build(self.root, daily=daily, metrics={"C1": 500}))
        data = obs(body, "cost_reconciliation")[0]["data"]
        self.assertAlmostEqual(data["reported_share"], 0.6)
        self.assertAlmostEqual(data["unreported_cost"], 200)
        self.assertEqual(cov(body)["cost_reconciliation"], "completed")
        body = run(*build(self.root, daily=daily, metrics={"C1": 200}))
        self.assertIsNone(obs(body, "cost_reconciliation")[0]["data"]["reported_share"])
        self.assertEqual(cov(body)["cost_reconciliation"], "partial")

    def test_conflicting_duplicate_grain_rows_are_excluded(self):
        daily = [drow("C1", "a.example", cost=40), drow("C1", "a.example", cost=45), drow("C1", "b.example", cost=5)]
        body = run(*build(self.root, daily=daily, metrics={"C1": 90}))
        data = obs(body, "cost_reconciliation")[0]["data"]
        self.assertEqual(data["placement_cost"], 5)
        self.assertEqual(cov(body)["cost_reconciliation"], "partial")

    # -------------------------------------------------------------- step 2
    def test_view_rate_uses_stated_denominator_never_ctr(self):
        daily = [drow("V1", "YT-1", format="skippable_instream", placement_type="YOUTUBE_VIDEO", impressions=20000,
                      clicks=200, cost=40, conversions=2)]
        video = [vrow("V1", "YT-1", video_views=3000, native_view_rate=0.3, denominator_name="eligible_video_impressions",
                      denominator_count=10000, eligible_video_impressions=10000, measurable_impressions=8000,
                      viewable_impressions=6000)]
        body = run(*build(self.root, daily=daily, video=video))
        vr = obs(body, "video_view_rate")[0]["data"]
        self.assertAlmostEqual(vr["view_rate"], 0.3)
        self.assertEqual((vr["denominator_name"], vr["denominator_count"]), ("eligible_video_impressions", 10000))
        ledger = obs(body, "placement_ledger")[0]["data"]["placements"][0]
        self.assertAlmostEqual(ledger["ctr"], 0.01)
        self.assertAlmostEqual(obs(body, "viewability")[0]["data"]["viewability"], 0.75)
        self.assertEqual(findings(body, "incomplete_view_evidence"), [])

    def test_native_rate_contradicting_denominator_is_info(self):
        base = {"video_views": 3000, "denominator_name": "eligible_video_impressions", "denominator_count": 10000}
        body = run(*build(self.root, video=[vrow("V1", "YT-1", native_view_rate=0.5, **base)]))
        self.assertEqual([f["severity"] for f in findings(body, "incomplete_view_evidence")], ["Info"])
        body = run(*build(self.root, video=[vrow("V1", "YT-1", native_view_rate=0.3005, **base)]))
        self.assertEqual(findings(body, "incomplete_view_evidence"), [])

    def test_views_without_denominator_is_info_but_non_view_format_is_not(self):
        video = [vrow("V1", "YT-1", video_views=3000),
                 vrow("C1", "site", format="responsive_display", denominator_name="not_applicable")]
        body = run(*build(self.root, video=video))
        f = findings(body, "incomplete_view_evidence")
        self.assertEqual([x["entity"]["placement_id"] for x in f], ["YT-1"])
        self.assertTrue(any("not applicable" in o["text"] for o in obs(body, "video_view_rate")))

    def test_named_denominator_is_not_replaced_by_eligible_impressions(self):
        video = [vrow("V1", "YT-1", video_views=3000, denominator_name="trueview_eligible_impressions",
                      eligible_video_impressions=10000)]
        body = run(*build(self.root, video=video))
        self.assertEqual(len(findings(body, "incomplete_view_evidence")), 1)
        self.assertFalse(any("view_rate" in o["data"] for o in obs(body, "video_view_rate")))

    # -------------------------------------------------------------- step 3
    def test_app_vs_website_needs_min_conversions_on_both_sides(self):
        def daily(web_conv):
            return [drow("C1", "mobileapp::1-app", placement_type="MOBILE_APPLICATION", cost=400, conversions=20,
                         clicks=300),
                    drow("C1", "site.example", cost=100, conversions=web_conv, clicks=300)]
        body = run(*build(self.root, daily=daily(14)))
        data = [o for o in obs(body, "app_vs_website") if o["data"].get("campaign_id") == "C1"][0]["data"]
        self.assertFalse(data["comparable"])
        body = run(*build(self.root, daily=daily(15)))
        data = [o for o in obs(body, "app_vs_website") if o["data"].get("campaign_id") == "C1"][0]["data"]
        self.assertTrue(data["comparable"])
        self.assertAlmostEqual(data["app_to_website_cpa"], 3.0)

    # -------------------------------------------------------------- step 4
    def test_zero_conversion_review_starts_at_spend_floor(self):
        body = run(*build(self.root, daily=[drow("C1", "a.example", cost=50, conversions=0)]))
        self.assertEqual(len(reviews(body, "zero_conversion_placement")), 1)
        self.assertEqual([f["severity"] for f in findings(body, "zero_conversion_placement")], ["Info"])
        body = run(*build(self.root, daily=[drow("C1", "a.example", cost=49.99, conversions=0)]))
        self.assertEqual(reviews(body, "zero_conversion_placement"), [])
        body = run(*build(self.root, daily=[drow("C1", "a.example", cost=500, conversions=1)]))
        self.assertEqual(reviews(body, "zero_conversion_placement"), [])

    def test_zero_conversion_needs_maturity_and_goal_tracking(self):
        daily = [drow("C1", "a.example", cost=80, conversions=0)]
        for i, kw in enumerate(({"snapshot": "2026-08-31"}, {"tracking": False})):
            body = run(*build(self.root / str(i), daily=daily, **kw))
            self.assertEqual(reviews(body, "zero_conversion_placement"), [], kw)
            self.assertEqual(body["findings"], [], kw)
            self.assertEqual(cov(body)["zero_conversion_screen"], "partial", kw)

    def test_unknown_conversions_are_not_zero(self):
        body = run(*build(self.root, daily=[drow("C1", "a.example", cost=80, conversions="")]))
        self.assertEqual(reviews(body, "zero_conversion_placement"), [])
        self.assertEqual(cov(body)["zero_conversion_screen"], "partial")

    def test_pmax_placements_never_enter_performance_screens(self):
        body = run(*build(self.root, daily=[drow("P1", "a.example", cost=100, conversions=0)]))
        self.assertEqual(reviews(body, "zero_conversion_placement"), [])
        self.assertEqual(cov(body)["zero_conversion_screen"], "partial")

    def test_ctr_anomaly_needs_declared_multiple_and_stays_info(self):
        daily = [drow("C1", "hot.example", impressions=1000, clicks=50),
                 drow("C1", "calm.example", impressions=2000, clicks=20)]
        body = run(*build(self.root, daily=daily))
        self.assertEqual(findings(body, "ctr_anomaly_alone"), [])
        self.assertEqual(cov(body)["ctr_anomaly_screen"], "partial")
        body = run(*build(self.root, daily=daily, profile={"placement_ctr_anomaly_multiple": 3}))
        f = findings(body, "ctr_anomaly_alone")
        self.assertEqual([(x["entity"]["placement_id"], x["severity"]) for x in f], [("hot.example", "Info")])
        body = run(*build(self.root, daily=daily, profile={"placement_ctr_anomaly_multiple": 6}))
        self.assertEqual(findings(body, "ctr_anomaly_alone"), [])

    # -------------------------------------------------------------- index #44/#45/#73 rule screen
    def test_client_rules_produce_reviews_only(self):
        daily = [drow("C1", "news.xyz"), drow("C1", "xyz.com"),
                 drow("C1", "mobileapp::2-com.fun.game", placement_type="MOBILE_APPLICATION")]
        body = run(*build(self.root, daily=daily))
        self.assertEqual(cov(body)["profile_rule_screen"], "skipped")
        body = run(*build(self.root, daily=daily, profile={"placement_tld_rules": [".xyz"],
                                                           "placement_url_keywords": ["game"]}))
        hits = sorted(r["entity"]["placement_id"] for r in reviews(body, "profile_rule_match"))
        self.assertEqual(hits, ["mobileapp::2-com.fun.game", "news.xyz"])
        self.assertEqual(body["findings"], [])

    # -------------------------------------------------------------- step 5
    def test_no_account_level_exclusions_is_not_a_finding(self):
        body = run(*build(self.root, daily=[drow("C1", "a.example")], controls=[], policy=[]))
        self.assertEqual(body["findings"], [])
        self.assertTrue(any("not a defect" in o["text"] for o in obs(body, "exclusion_inheritance")))

    def test_material_uncovered_restricted_delivery_is_critical(self):
        daily = [drow("C1", "bad.example", cost=60, conversions=3)]
        body = run(*build(self.root, daily=daily, controls=[ctl("C1", "other.example")], policy=[POLICY]))
        self.assertEqual([f["severity"] for f in findings(body, "restricted_live_exposure")], ["Critical"])

    def test_restricted_delivery_below_floor_or_uncertain_coverage_is_review_only(self):
        cases = [dict(daily=[drow("C1", "bad.example", cost=10)], controls=[]),
                 dict(daily=[drow("C1", "bad.example", cost=60)], controls=[],
                      incomplete=("custom/placement_controls.csv",)),
                 dict(daily=[drow("C1", "sub.bad.example", cost=60)], controls=[])]
        for i, kw in enumerate(cases):
            body = run(*build(self.root / str(i), policy=[POLICY], **kw))
            self.assertEqual([f["severity"] for f in findings(body, "restricted_live_exposure")], ["Info"])
            item = reviews(body, "restricted_live_exposure")[0]
            self.assertEqual(item["outcomes"]["confirmed_material_exposure"]["severity"], "Critical")

    def test_enabled_exclusion_or_unapproved_policy_removes_exposure(self):
        daily = [drow("C1", "bad.example", cost=60)]
        body = run(*build(self.root, daily=daily, policy=[POLICY],
                          controls=[ctl("c1", "bad.example", scope_type="account")]))
        self.assertEqual(findings(body, "restricted_live_exposure"), [])
        body = run(*build(self.root, daily=daily, controls=[], policy=[{**POLICY, "approved_by": ""}]))
        self.assertEqual(body["findings"], [])

    def test_uncontrolled_restriction_without_delivery_is_info(self):
        policy = [{**POLICY, "placement_or_category_id": "other.example", "campaign_scope": "C1"}]
        body = run(*build(self.root, daily=[drow("C1", "a.example")], controls=[], policy=policy))
        self.assertEqual([f["severity"] for f in findings(body, "approved_restriction_uncontrolled")], ["Info"])
        body = run(*build(self.root, daily=[drow("C1", "a.example")], controls=[ctl("C1", "other.example")],
                          policy=policy))
        self.assertEqual(findings(body, "approved_restriction_uncontrolled"), [])

    # -------------------------------------------------------------- step 6 / verify
    def test_finalize_zero_conversion_proposal_is_verified(self):
        ex, prof = build(self.root, daily=[drow("C1", "a.example", cost=80, conversions=0),
                                           drow("C1", "a.example", ad_group_id="G2", cost=5, conversions=0)],
                         controls=[])
        body = self.run_cli(ex, prof)
        item = reviews(body, "zero_conversion_placement")[0]
        good = {"placement": "a.example", "scope_type": "campaign", "scope_id": "C1",
                "coverage_at_risk": item["evidence"]["coverage_at_risk"], "existing_overlap": "none",
                "approval_owner": "account lead", "monitoring_plan": "check placement report weekly"}
        dec = lambda p: [{"id": item["id"], "outcome": "irrelevant_zero_conversion", "rationale": "off-topic", "proposal": p}]
        self.assertEqual(self.finalize(ex, prof, dec({**good, "scope_type": "account", "scope_id": "c1",
                                                      "cross_campaign_evidence_ref": "x"})), 4)
        self.assertEqual(self.finalize(ex, prof, dec({**good, "placement": "adsenseformobileapps.com"})), 4)
        self.assertEqual(self.finalize(ex, prof, dec({**good, "monitoring_plan": ""})), 4)
        self.assertEqual(self.finalize(ex, prof, dec({**good, "scope_type": "ad_group", "scope_id": "G9"})), 4)
        self.assertEqual(self.finalize(ex, prof, dec(good)), 0)
        final = json.loads((self.root / "out" / "final.json").read_text())
        self.assertEqual([f["severity"] for f in findings(final, "zero_conversion_placement")], ["Warning"])

    def test_finalize_critical_exposure_needs_supplied_evidence_ref(self):
        ex, prof = build(self.root, daily=[drow("C1", "bad.example", cost=10)], controls=[], policy=[POLICY])
        body = self.run_cli(ex, prof)
        item = reviews(body, "restricted_live_exposure")[0]
        dec = lambda p: [{"id": item["id"], "outcome": "confirmed_material_exposure", "rationale": "r", "proposal": p}]
        self.assertEqual(self.finalize(ex, prof, dec({})), 4)
        self.assertEqual(self.finalize(ex, prof, dec({"evidence_ref": "made-up"})), 4)
        self.assertEqual(self.finalize(ex, prof, dec({"evidence_ref": "brand-safety-2026"})), 0)
        final = json.loads((self.root / "out" / "final.json").read_text())
        self.assertEqual([f["severity"] for f in findings(final, "restricted_live_exposure")], ["Critical"])

    def test_verify_refuses_included_placements_and_unsupported_pmax_scope(self):
        prof_rules = {"placement_url_keywords": ["game"]}
        daily = [drow("C1", "game.example"), drow("P1", "kids-game.example", cost="", conversions="")]
        ex, prof = build(self.root, daily=daily, profile=prof_rules,
                         controls=[ctl("C1", "game.example", mode="INCLUDED")])
        ctx = mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof)
        items = {x.entity["campaign_id"]: x for x in ctx.result.reviews if x.condition_key == "profile_rule_match"}
        base = {"coverage_at_risk": "1000 impressions", "existing_overlap": "none", "approval_owner": "owner",
                "monitoring_plan": "weekly"}
        dec = lambda p: {"outcome": "unsuitable_request_exclusion", "rationale": "r", "proposal": {**base, **p}}
        problems = mod.verify(ctx, items["C1"], dec({"placement": "game.example", "scope_type": "campaign",
                                                     "scope_id": "C1"}))
        self.assertTrue(any("included" in p for p in problems), problems)
        pmax = items["P1"]
        self.assertTrue(mod.verify(ctx, pmax, dec({"placement": "kids-game.example", "scope_type": "campaign",
                                                   "scope_id": "P1"})))
        self.assertEqual(mod.verify(ctx, pmax, dec({"placement": "kids-game.example", "scope_type": "account",
                                                    "scope_id": "c1", "cross_campaign_evidence_ref": "policy-7"})), [])


if __name__ == "__main__":
    unittest.main()
