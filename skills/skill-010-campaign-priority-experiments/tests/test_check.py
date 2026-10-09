"""test_check.py — Decision-boundary tests for skill-010 Shopping routing and experiment checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-010-campaign-priority-experiments/tests
rules:   Temp folders only; stdlib only; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial tests
"""
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
_spec = importlib.util.spec_from_file_location("check_010", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)


def write_export(root: Path, tables: dict, incomplete=()) -> None:
    manifest = []
    for key, rows in tables.items():
        cols, rows = rows if isinstance(rows, tuple) else (list(dict.fromkeys(k for r in rows for k in r)), rows)
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "partial" if key in incomplete else "complete",
                         "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


ACCOUNT = [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
            "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}]


def route(cid, pid, prio, included="true", eligible="true"):
    return {"campaign_id": cid, "merchant_id": "M", "product_id": pid, "feed_label": "IT", "language": "it",
            "target_country": "IT", "priority": prio, "included": included, "eligible": eligible,
            "snapshot_date": "2026-09-06"}


def shopping(routes, negatives=None):
    return {"account": ACCOUNT,
            "campaigns": [{"id": "S1", "channel_type": "SHOPPING"}, {"id": "S2", "channel_type": "SHOPPING"},
                          {"id": "PM", "channel_type": "PERFORMANCE_MAX"}],
            "custom/shopping_routing": routes,
            "negative_keywords": negatives or (["text", "match_type", "level", "campaign_id"], []),
            "shared_negative_lists": (["list_id", "keywords", "campaigns_applied"], [])}


def design_rows(split=("0.5", "0.5"), method="cluster_robust"):
    return [{"experiment_id": "E1", "arm_id": arm, "campaign_id": cid, "hypothesis": "h", "change_bundle": "one ad",
             "planned_split": s, "allocation_unit": "user", "primary_metric": "CPA", "guardrails": "g",
             "minimum_detectable_effect": "0.2", "sample_plan": "1000", "stopping_rule": "fixed", "planned_start": "2026-08-01",
             "planned_end": "2026-08-10", "owner": "o", "source": "ui", "captured_at": "2026-07-31", "estimand": "cpa",
             "analysis_unit": "user", "statistical_method": method, "maturity_rule": "lag"}
            for (arm, cid), s in zip((("A", "CA"), ("B", "CB")), split)]


def daily_rows(units=(100, 100), campaign_b="CB", last_day=10):
    out = []
    for arm, cid, u in (("A", "CA", units[0]), ("B", campaign_b, units[1])):
        for d in range(1, last_day + 1):
            out.append({"experiment_id": "E1", "arm_id": arm, "campaign_id": cid, "date": f"2026-08-{d:02d}",
                        "assigned_units": str(u), "impressions": "1000", "clicks": "50", "cost": "50",
                        "conversions": "2", "conversion_value": "100", "goal_scope": "purchase"})
    return out


def experiment(**kw):
    t = {"account": ACCOUNT, "campaigns": [{"id": "CA", "channel_type": "SEARCH"}, {"id": "CB", "channel_type": "SEARCH"}],
         "external/experiment_design": design_rows(**{k: v for k, v in kw.items() if k in ("split", "method")}),
         "custom/experiment_daily": daily_rows(**{k: v for k, v in kw.items() if k in ("units", "campaign_b", "last_day")})}
    if kw.get("inference"):
        t["external/experiment_inference"] = [{"experiment_id": "E1", "reference_arm_id": "A", "variant_arm_id": "B",
                                               "metric": "CPA", "estimand": "cpa", "analysis_unit": "user",
                                               "statistical_method": kw["inference"], "estimate": "-0.1",
                                               "ci_lower": "-0.2", "ci_upper": "0.0", "confidence_level": "0.95",
                                               "analyzed_start": "2026-08-01", "analyzed_end": "2026-08-10",
                                               "goal_scope": "purchase", "maturity_rule": "lag", "source": "platform"}]
    return t


class CheckTests(unittest.TestCase):
    def run_skill(self, tables, profile=None, incomplete=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_export(self.root / "export", tables, incomplete)
        (self.root / "profile.json").write_text(json.dumps(profile or {}))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.root / "export", self.root / "profile.json").finish()

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    @staticmethod
    def keys(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    def test_same_priority_overlap_is_info_and_different_priority_goes_to_review(self):
        body = self.run_skill(shopping([route("S1", "P1", "high"), route("S2", "P1", "high"), route("PM", "P1", "high")]))
        self.assertEqual(self.keys(body), ["same_priority_overlap"])
        self.assertEqual(body["ai_review"], [])
        body = self.run_skill(shopping([route("S1", "P1", "high"), route("S2", "P1", "low")]))
        self.assertEqual(self.keys(body), [])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["priority_routing"])

    def test_excluded_or_ineligible_duplicate_is_not_overlap(self):
        body = self.run_skill(shopping([route("S1", "P1", "high"), route("S2", "P1", "high", included="false")]))
        self.assertEqual(self.keys(body), [])

    def test_no_standard_shopping_is_not_applicable(self):
        t = shopping([route("PM", "P1", "high")])
        t["campaigns"] = [{"id": "PM", "channel_type": "PERFORMANCE_MAX"}]
        body = self.run_skill(t)
        self.assertEqual(self.cov(body)["priority_routing"], "not_applicable")

    def test_unrouted_eligible_needs_complete_inventory(self):
        rows = [route("S1", "P1", "high", included="false"), route("S1", "P2", "high")]
        body = self.run_skill(shopping(rows))
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["eligible_not_routed"])
        body = self.run_skill(shopping(rows), incomplete=("custom/shopping_routing",))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(self.cov(body)["eligible_coverage"], "partial")

    def test_arm_mapped_to_wrong_campaign_is_warning(self):
        body = self.run_skill(experiment(campaign_b="CA"))
        self.assertIn("arm_campaign_mismatch", self.keys(body, "Warning"))
        body = self.run_skill(experiment())
        self.assertEqual(self.keys(body, "Warning"), [])

    def test_allocation_screen_uses_design_not_fifty_fifty(self):
        body = self.run_skill(experiment(split=("0.7", "0.3"), units=(70, 30)))
        self.assertFalse([r for r in body["ai_review"] if r["condition_key"] == "allocation_vs_design"])
        body = self.run_skill(experiment(units=(70, 30)))
        self.assertTrue([r for r in body["ai_review"] if r["condition_key"] == "allocation_vs_design"])

    def test_no_inference_means_info_and_no_winner(self):
        body = self.run_skill(experiment())
        self.assertEqual(self.keys(body), ["inference_absent"])
        self.assertEqual(self.cov(body)["inference_match"], "skipped")

    def test_inference_must_match_design_method(self):
        body = self.run_skill(experiment(inference="cluster_robust"))
        self.assertEqual(self.keys(body), [])
        body = self.run_skill(experiment(inference="t_test_on_daily_rows"))
        self.assertEqual(self.keys(body), ["inference_inconclusive"])

    def test_immature_days_are_excluded_from_arm_totals(self):
        body = self.run_skill(experiment(last_day=30))  # snapshot 09-06, lag 2: all August days mature
        arms = [o for o in body["observations"] if o["check"] == "arm_outcomes"][0]["data"]["arms"]
        self.assertEqual(arms["A"]["immature_days_excluded"], 0)
        t = experiment(last_day=30)
        t["account"] = [dict(ACCOUNT[0], snapshot_date="2026-08-30")]
        arms = [o for o in self.run_skill(t)["observations"] if o["check"] == "arm_outcomes"][0]["data"]["arms"]
        self.assertEqual(arms["A"]["immature_days_excluded"], 2)

    def test_finalize_rejects_fence_blocking_routed_query(self):
        profile = {"shopping_query_routing": {"S2": ["cordless drill"]}}
        self.run_skill(shopping([route("S1", "P1", "high"), route("S2", "P1", "low")]), profile)
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            rid = json.loads((out / "result.json").read_text())["ai_review"][0]["id"]
            for neg, code in (("cordless drill", 4), ("cordless drill 18v", 0)):
                dec = self.root / "d.json"
                dec.write_text(json.dumps([{"id": rid, "outcome": "routing_contradicts_strategy", "rationale": "r",
                                            "proposal": {"negatives": [{"negative": neg, "match_type": "EXACT",
                                                                        "campaign_id": "S2"}]}}]))
                self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                            ["finalize"] + args + ["--decisions", str(dec)]), code)


if __name__ == "__main__":
    unittest.main()
