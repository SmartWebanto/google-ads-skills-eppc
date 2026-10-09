"""test_check.py — Decision-boundary tests for skill-159 AI Max check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-159-ai-max-for-search-campaign-assessment/tests -t skills/skill-159-ai-max-for-search-campaign-assessment
rules:   Temp folders only; pins consumer-visible behavior (unknown vs disabled, dependency conflicts,
safeguard review routing, experiment gates, verify rejections), never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
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

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill159_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

CFG_COLS = ["account_id", "campaign_id", "ad_group_id", "snapshot_at", "availability", "ai_max_enabled",
            "search_term_matching_enabled", "text_customization_enabled", "final_url_expansion_enabled",
            "brand_controls", "url_inclusions", "url_exclusions", "ad_group_overrides", "enabled_at",
            "source_screen", "supported_control_help_url"]
SAFE_COLS = ["campaign_id", "requirement_id", "allowed_domain_paths", "forbidden_content_or_claims", "mandatory_copy",
             "approved_brand_terms", "landing_page_snapshot_ref", "tracking_evidence_ref", "business_goal", "owner",
             "approval_status"]
EXP_COLS = ["account_id", "experiment_id", "arm_id", "campaign_id", "date", "assignment_method", "traffic_split",
            "start_date", "end_date", "changed_features", "impressions", "clicks", "cost", "conversions",
            "conversion_value", "qualified_outcomes", "goal_id"]


def cfg(cid, gid="", **kw):
    base = {"account_id": "1", "campaign_id": cid, "ad_group_id": gid, "snapshot_at": "2026-09-05",
            "availability": "available", "ai_max_enabled": "true", "search_term_matching_enabled": "true",
            "text_customization_enabled": "true", "final_url_expansion_enabled": "false"}
    base.update(kw)
    return base


def safe(cid, rid="R1", **kw):
    base = {"campaign_id": cid, "requirement_id": rid, "approval_status": "approved", "owner": "client"}
    base.update(kw)
    return base


def build(tmp: Path, *, config=None, safeguards=None, ads=None, experiment=None, snapshot="2026-09-06") -> Path:
    root = tmp / "export"
    files = {
        "account.csv": (["customer_id", "name", "currency_code", "time_zone", "date_range_start", "date_range_end",
                         "snapshot_date", "rates_format", "money_unit", "conversion_date_basis", "conversion_lag_days"],
                        [{"customer_id": "1", "name": "A", "currency_code": "EUR", "time_zone": "Europe/Rome",
                          "date_range_start": "2026-08-01", "date_range_end": "2026-08-30", "snapshot_date": snapshot,
                          "rates_format": "fraction", "money_unit": "currency",
                          "conversion_date_basis": "interaction_date", "conversion_lag_days": "3"}]),
        "campaigns.csv": (["id", "name", "status", "channel_type", "bidding_strategy_type"],
                          [{"id": "10", "name": "S1", "status": "ENABLED", "channel_type": "SEARCH",
                            "bidding_strategy_type": "TARGET_CPA"},
                           {"id": "20", "name": "P", "status": "ENABLED", "channel_type": "PERFORMANCE_MAX",
                            "bidding_strategy_type": "MAXIMIZE_CONVERSION_VALUE"}]),
    }
    if config is not None:
        files["custom/ai_max_config.csv"] = (CFG_COLS, config)
    if safeguards is not None:
        files["external/ai_max_safeguards.csv"] = (SAFE_COLS, safeguards)
    if ads is not None:
        files["ads.csv"] = (["id", "campaign_id", "ad_group_id", "type", "status", "pinned_positions"], ads)
    if experiment is not None:
        files["custom/ai_max_experiment_daily.csv"] = (EXP_COLS, experiment)
    manifest = [{"filename": n, "source": "test", "completeness": "complete", "truncation": "none"} for n in files]
    files["table_manifest.csv"] = (["filename", "source", "completeness", "truncation"], manifest)
    for name, (cols, rows) in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
    return root


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)

    def run_check(self, **kw) -> dict:
        root = build(self.tmp, **kw)
        out = self.tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        self.assertEqual(code, 0)
        self.root, self.out = root, out
        return json.loads((out / "result.json").read_text())

    def finalize(self, decisions) -> tuple[int, dict]:
        d = self.tmp / "decisions.json"
        d.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--out", str(self.out), "--decisions", str(d)])
        return code, json.loads((self.out / "final.json").read_text())


def keys(res, check=None):
    return sorted(f["condition_key"] for f in res["findings"] if check is None or f["check"] == check)


def cov(res, check):
    return next(c for c in res["coverage"] if c["check"] == check)


def reviews(res, key):
    return [r for r in res["ai_review"] if r["condition_key"] == key]


class Inventory(Base):
    def test_missing_config_is_skipped_not_passed(self):
        res = self.run_check()
        c = cov(res, "feature_inventory")
        self.assertEqual(c["status"], "skipped")
        self.assertIn("custom/ai_max_config (file)", c["missing"])
        self.assertEqual(res["findings"], [])

    def test_unknown_state_is_unverified_not_non_adoption(self):
        res = self.run_check(config=[cfg("10", ai_max_enabled="", text_customization_enabled="")])
        self.assertIn("ai_max_settings_unverified", keys(res, "feature_inventory"))
        self.assertNotIn("ai_max_not_adopted", keys(res))
        unv = next(f for f in res["findings"] if f["condition_key"] == "ai_max_settings_unverified")
        self.assertEqual(sorted(unv["evidence"]["unknown_fields"]), ["ai_max_enabled", "text_customization_enabled"])

    def test_explicit_off_is_info_non_adoption(self):
        res = self.run_check(config=[cfg("10", ai_max_enabled="false")])
        self.assertEqual(keys(res, "feature_inventory"), ["ai_max_not_adopted"])
        self.assertTrue(all(f["severity"] == "Info" for f in res["findings"]))

    def test_search_campaign_without_row_is_unverified_and_pmax_ignored(self):
        res = self.run_check(config=[cfg("20")])
        f = [x for x in res["findings"] if x["check"] == "feature_inventory"]
        self.assertEqual([(x["condition_key"], x["entity"]["campaign_id"]) for x in f],
                         [("ai_max_settings_unverified", "10")])

    def test_conflicting_rows_at_same_snapshot_are_partial(self):
        res = self.run_check(config=[cfg("10"), cfg("10", ai_max_enabled="false")])
        self.assertEqual(cov(res, "feature_inventory")["status"], "partial")
        self.assertIn("ai_max_settings_unverified", keys(res, "feature_inventory"))


class Dependencies(Base):
    def test_adgroup_matching_ineffective_when_campaign_off(self):
        res = self.run_check(config=[cfg("10", search_term_matching_enabled="false"),
                                     cfg("10", "100", search_term_matching_enabled="true")])
        self.assertEqual(keys(res, "control_dependencies"), ["adgroup_matching_ineffective"])

    def test_adgroup_matching_effective_when_campaign_on(self):
        res = self.run_check(config=[cfg("10"), cfg("10", "100", search_term_matching_enabled="true")])
        self.assertEqual(keys(res, "control_dependencies"), [])

    def test_unknown_campaign_matching_is_partial(self):
        res = self.run_check(config=[cfg("10", search_term_matching_enabled=""),
                                     cfg("10", "100", search_term_matching_enabled="true")])
        self.assertEqual(keys(res, "control_dependencies"), [])
        self.assertEqual(cov(res, "control_dependencies")["status"], "partial")

    def test_url_expansion_without_text_customization(self):
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true", text_customization_enabled="false")])
        self.assertEqual(keys(res, "url_expansion_controls"), ["url_expansion_without_text_customization"])

    def test_adgroup_inherits_campaign_text_customization(self):
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true"),
                                     cfg("10", "100", final_url_expansion_enabled="true", text_customization_enabled="",
                                         url_inclusions="/shop")])
        self.assertEqual(keys(res, "url_expansion_controls"), [])


class Safeguards(Base):
    def test_allowed_paths_with_expansion_goes_to_review(self):
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true")],
                             safeguards=[safe("10", allowed_domain_paths="/repair")])
        items = reviews(res, "url_expansion_vs_allowed_paths")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["outcomes"]["conflict_evidenced"]["severity"], "Warning")
        self.assertEqual(items[0]["outcomes"]["live_breach_confirmed"]["severity"], "Critical")

    def test_unapproved_safeguard_is_not_used(self):
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true")],
                             safeguards=[safe("10", allowed_domain_paths="/repair", approval_status="draft")])
        self.assertEqual(reviews(res, "url_expansion_vs_allowed_paths"), [])

    def test_mandatory_copy_review_needs_pins(self):
        ads = [{"id": "5", "campaign_id": "10", "ad_group_id": "100", "type": "RSA", "status": "ENABLED",
                "pinned_positions": "H1:Official"}]
        with_pins = self.run_check(config=[cfg("10", final_url_expansion_enabled="true")],
                                   safeguards=[safe("10", mandatory_copy="Official dealer")], ads=ads)
        self.assertEqual(len(reviews(with_pins, "mandatory_copy_pin_bypass")), 1)

    def test_mandatory_copy_without_pins_no_bypass_review(self):
        ads = [{"id": "5", "campaign_id": "10", "ad_group_id": "100", "type": "RSA", "status": "ENABLED",
                "pinned_positions": ""}]
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true")],
                             safeguards=[safe("10", mandatory_copy="Official dealer")], ads=ads)
        self.assertEqual(reviews(res, "mandatory_copy_pin_bypass"), [])

    def test_enabled_feature_without_safeguards_is_partial(self):
        res = self.run_check(config=[cfg("10")], safeguards=[safe("20", forbidden_content_or_claims="cheapest")])
        self.assertEqual(cov(res, "feature_safeguard_review")["status"], "partial")
        self.assertEqual([r for r in res["ai_review"] if r["check"] == "feature_safeguard_review"], [])

    def test_finalize_breach_requires_evidence_ref(self):
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true")],
                             safeguards=[safe("10", allowed_domain_paths="/repair", forbidden_content_or_claims="cheapest")])
        url = reviews(res, "url_expansion_vs_allowed_paths")[0]
        stm = reviews(res, "safeguard_conflict_search_term_matching")[0]
        code, final = self.finalize([
            {"id": url["id"], "outcome": "live_breach_confirmed", "rationale": "served page outside path"},
            {"id": stm["id"], "outcome": "conflict_evidenced", "rationale": "query restriction conflicts"}])
        self.assertEqual(code, 4)
        self.assertEqual({x["id"]: x["status"] for x in final["review_log"]},
                         {url["id"]: "rejected", stm["id"]: "accepted"})
        self.assertEqual(final["counts"]["Critical"], 0)
        self.assertEqual(final["counts"]["Warning"], 1)

    def test_finalize_breach_with_evidence_ref_is_critical(self):
        res = self.run_check(config=[cfg("10", final_url_expansion_enabled="true")],
                             safeguards=[safe("10", allowed_domain_paths="/repair")])
        url = reviews(res, "url_expansion_vs_allowed_paths")[0]
        code, final = self.finalize([{"id": url["id"], "outcome": "live_breach_confirmed", "rationale": "page log",
                                      "proposal": {"evidence_ref": "external/landing_log.csv#row4"}}])
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Critical"], 1)


def exp_rows(arm, conv, clicks=500, impr=5000, method="randomized", goal="G1", changed="", days=2):
    return [{"account_id": "1", "experiment_id": "E1", "arm_id": arm, "campaign_id": "10",
             "date": f"2026-08-{10 + d:02d}", "assignment_method": method, "changed_features": changed,
             "impressions": impr / days, "clicks": clicks / days, "cost": 1000 / days, "conversions": conv / days,
             "conversion_value": 4000 / days, "goal_id": goal} for d in range(days)]


class Experiments(Base):
    def test_both_arms_gated_mature_comparison(self):
        res = self.run_check(experiment=exp_rows("control", 40) + exp_rows("test", 50, changed="text_customization"))
        obs = [o for o in res["observations"] if o["check"] == "experiment_evaluation" and "gated" in o["text"]]
        self.assertEqual(len(obs), 1)
        self.assertEqual(sorted(obs[0]["data"]["metrics"]), ["cpa", "ctr", "cvr", "roas"])
        self.assertEqual(obs[0]["data"]["control_arm"], "control")
        self.assertEqual(keys(res, "experiment_evaluation"), [])

    def test_one_arm_below_min_conversions_blocks_cpa_roas(self):
        res = self.run_check(experiment=exp_rows("control", 40) + exp_rows("test", 10, changed="text_customization"))
        obs = next(o for o in res["observations"] if "gated" in o["text"])
        self.assertEqual(sorted(obs["data"]["metrics"]), ["ctr", "cvr"])
        self.assertIn("cpa", obs["data"]["failed_gates"])

    def test_uncontrolled_assignment_is_not_causal(self):
        res = self.run_check(experiment=exp_rows("pre", 40, method="before_after") + exp_rows("post", 50, method="before_after"))
        self.assertEqual(keys(res, "experiment_evaluation"), ["experiment_not_causal"])
        self.assertFalse(any("gated" in o["text"] for o in res["observations"]))

    def test_goal_mismatch_is_not_causal(self):
        res = self.run_check(experiment=exp_rows("control", 40) + exp_rows("test", 50, goal="G2"))
        self.assertEqual(keys(res, "experiment_evaluation"), ["experiment_not_causal"])

    def test_immature_window_is_partial_descriptive(self):
        res = self.run_check(experiment=exp_rows("control", 40) + exp_rows("test", 50), snapshot="2026-08-31")
        self.assertEqual(cov(res, "experiment_evaluation")["status"], "partial")
        self.assertFalse(any("gated" in o["text"] for o in res["observations"]))


class Proposal(Base):
    def test_proposal_must_be_single_feature_and_specified(self):
        res = self.run_check(config=[cfg("10", ai_max_enabled="false")])
        item = reviews(res, "feature_experiment_or_no_change")[0]
        full = {"feature": "text_customization_enabled", "baseline": "current RSA", "primary_metric": "profit",
                "risk_floor_or_cap": "CPA <= 45", "allocation_method": "50/50 search_based",
                "stop_conditions": "CPA > 60 for 7d", "owner": "client", "duration_days": 42}
        code, final = self.finalize([{"id": item["id"], "outcome": "propose_feature_test", "rationale": "x",
                                      "proposal": {**full, "feature": "all"}}])
        self.assertEqual(code, 4)
        code, final = self.finalize([{"id": item["id"], "outcome": "propose_feature_test", "rationale": "x",
                                      "proposal": full}])
        self.assertEqual(code, 0)
        self.assertEqual(final["pending_review"], [])

    def test_unavailable_campaign_gets_no_proposal(self):
        res = self.run_check(config=[cfg("10", availability="unavailable")])
        self.assertEqual(reviews(res, "feature_experiment_or_no_change"), [])


if __name__ == "__main__":
    unittest.main()
