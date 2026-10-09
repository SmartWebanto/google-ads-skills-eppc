"""test_check.py — Decision-boundary tests for skill-032 creative experiment checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-032-ad-copy-ab-testing/tests -t skills/skill-032-ad-copy-ab-testing
rules:   Temp folders only; pins behavior (observational vs randomized, SRM gate, inference/readiness gates,
winner verification), never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill032_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,{lag}\n")
BASE = {
    "campaigns.csv": "id,status\nC1,ENABLED\n",
    "ad_groups.csv": "id,campaign_id,status\nG1,C1,ENABLED\nG2,C1,ENABLED\nG3,C1,ENABLED\n",
    "ads.csv": "id,campaign_id,ad_group_id,type,status\nA1,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED\n"
               "A2,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED\nA3,C1,G2,RESPONSIVE_SEARCH_AD,ENABLED\n",
    "ad_metrics.csv": "ad_id,campaign_id,ad_group_id,impressions,clicks,cost,conversions\n"
                      "A1,C1,G1,10000,900,800,40\nA2,C1,G1,10000,300,300,5\n",
}
PLAN_HDR = ("experiment_id,hypothesis,eligible_scope_ids,control_definition,treatment_definition,assignment_unit,"
            "allocation_method,planned_split,start_at,end_at,primary_metric,mde,alpha,power,target_sample_per_arm,"
            "sequential_or_fixed_method,guardrails,stopping_rules,owner,approval_state\n")


def plan_row(eid="E1", scope="G1", alloc="randomized cookie split", split="control:50;treatment:50",
             end="2026-08-28", metric="ctr"):
    return (f"{eid},benefit headline lifts CTR,{scope},A1,A2,user,{alloc},{split},2026-08-01,{end},{metric},0.01,"
            f"0.05,0.8,4000,fixed,cpa within 10%,fixed horizon,owner,approved\n")


RES_HDR = ("experiment_id,arm_id,date,assigned_units,impressions,clicks,cost,conversions,"
           "variance_or_inference_report_ref,lag_cutoff\n")


def results(n_c=5000, n_t=5020, ref="ads-exp-report-1"):
    return RES_HDR + (f"E1,control,2026-08-15,{n_c},20000,600,500,30,{ref},2026-08-28\n"
                      f"E1,treatment,2026-08-15,{n_t},20000,700,520,32,{ref},2026-08-28\n")


def run(test, files, profile=None, lag=2, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    files = {"account.csv": ACCOUNT.format(lag=lag), **files}
    names = [n for n in files]
    files["table_manifest.csv"] = "filename,completeness,truncation\n" + "".join(f"{n},complete,none\n" for n in names)
    for name, text in files.items():
        p = root / "export" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (root / "profile.json").write_text(json.dumps(profile or {}))
    args = ["--export", str(root / "export"), "--profile", str(root / "profile.json"), "--out", str(root / "out")]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
    body = json.loads((root / "out" / "result.json").read_text())
    if decisions is None:
        return rc, body
    (root / "d.json").write_text(json.dumps(decisions(body)))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc2 = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(root / "d.json")])
    return rc2, json.loads((root / "out" / "final.json").read_text())


def keys(body, sev=None):
    return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class Observational(unittest.TestCase):
    def test_rotation_without_randomized_plan_is_observational_not_a_winner(self):
        rc, b = run(self, {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(scope="G9")})
        self.assertEqual(rc, 0)
        info = [f for f in b["findings"] if f["condition_key"] == "no_formal_test"]
        self.assertEqual([f["entity"]["ad_group_id"] for f in info], ["G1"])
        self.assertEqual(keys(b, "Warning"), [])
        self.assertEqual(b["ai_review"], [])

    def test_missing_plan_labels_observational_without_finding(self):
        rc, b = run(self, BASE)
        self.assertNotIn("no_formal_test", keys(b))
        c = cov(b)
        self.assertEqual(c["experiment_classification"], "partial")
        self.assertEqual(c["sample_ratio"], "skipped")
        self.assertEqual(c["adoption_decision"], "skipped")

    def test_single_and_zero_rsa_groups(self):
        _, b = run(self, BASE)
        single = [f["entity"]["ad_group_id"] for f in b["findings"] if f["condition_key"] == "single_rsa"]
        self.assertEqual(single, ["G2"])  # G3 has zero ads: delegated to 037, no finding

    def test_non_random_allocation_is_not_a_test(self):
        _, b = run(self, {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(alloc="optimize")})
        self.assertIn("G1", [f["entity"].get("ad_group_id") for f in b["findings"] if f["condition_key"] == "no_formal_test"])

    def test_missing_spine_skips_dependents(self):
        rc, b = run(self, {"ads.csv": BASE["ads.csv"]})
        self.assertEqual(rc, 0)
        c = cov(b)
        self.assertEqual(c["rsa_inventory"], "skipped")
        self.assertEqual(c["experiment_classification"], "skipped")


class SampleRatio(unittest.TestCase):
    def files(self, n_c, n_t):
        return {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(),
                "custom/creative_experiment_results.csv": results(n_c, n_t)}

    def test_prespecified_alpha_flags_mismatch(self):
        _, b = run(self, self.files(5000, 4000), {"srm_alpha": 0.001})
        self.assertIn("randomization_mismatch", keys(b, "Warning"))
        self.assertNotIn("experiment_decision", [r["condition_key"] for r in b["ai_review"]])

    def test_balanced_assignment_passes(self):
        _, b = run(self, self.files(5000, 5020), {"srm_alpha": 0.001})
        self.assertNotIn("randomization_mismatch", keys(b))

    def test_without_prespecified_method_goes_to_review(self):
        _, b = run(self, self.files(5000, 4000))
        self.assertNotIn("randomization_mismatch", keys(b))
        self.assertIn("randomization_mismatch", [r["condition_key"] for r in b["ai_review"]])

    def test_unparseable_split_is_partial(self):
        files = self.files(5000, 5020)
        files["external/creative_experiment_plan.csv"] = PLAN_HDR + plan_row(split="60/40")
        _, b = run(self, files, {"srm_alpha": 0.001})
        self.assertEqual(cov(b)["sample_ratio"], "partial")

    def test_chi_square_tail(self):
        self.assertAlmostEqual(M._chi2_sf(3.841459, 1), 0.05, places=5)
        self.assertAlmostEqual(M._chi2_sf(5.991465, 2), 0.05, places=5)
        import math  # df=5 closed form: erfc(sqrt(x/2)) + sqrt(2x/pi) e^(-x/2) (1 + x/3)
        exact = math.erfc(math.sqrt(15)) + math.sqrt(60 / math.pi) * math.exp(-15) * 11
        self.assertAlmostEqual(M._chi2_sf(30.0, 5), exact, places=10)


class Readiness(unittest.TestCase):
    def test_missing_inference_report_blocks_winner(self):
        files = {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(),
                 "custom/creative_experiment_results.csv": results(ref="")}
        _, b = run(self, files, {"srm_alpha": 0.001})
        self.assertIn("unavailable_valid_inference", keys(b, "Info"))
        self.assertEqual([r for r in b["ai_review"] if r["condition_key"] == "experiment_decision"], [])

    def test_horizon_not_reached_or_immature_is_underpowered(self):
        files = {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(end="2026-12-31"),
                 "custom/creative_experiment_results.csv": results()}
        _, b = run(self, files, {"srm_alpha": 0.001})
        self.assertIn("underpowered_or_immature", keys(b))
        files["external/creative_experiment_plan.csv"] = PLAN_HDR + plan_row()
        _, b = run(self, files, {"srm_alpha": 0.001}, lag=30)
        self.assertIn("underpowered_or_immature", keys(b))

    def test_arm_below_sample_gate_blocks_decision(self):
        files = {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(),
                 "custom/creative_experiment_results.csv": results(n_c=3000, n_t=3010)}
        _, b = run(self, files, {"srm_alpha": 0.001})
        self.assertIn("underpowered_or_immature", keys(b))

    def test_edits_inside_window_only_are_reviewed(self):
        chg = ("experiment_id,change_id,changed_at,entity_id,field,old_value,new_value,reason\n"
               "E1,X1,2026-07-20,A1,cpc,1,2,pre\n")
        files = {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(),
                 "custom/creative_experiment_changes.csv": chg}
        _, b = run(self, files)
        self.assertNotIn("uncontrolled_edit", [r["condition_key"] for r in b["ai_review"]])
        files["custom/creative_experiment_changes.csv"] = chg + "E1,X2,2026-08-10,A2,budget,10,20,ops\n"
        _, b = run(self, files)
        self.assertIn("uncontrolled_edit", [r["condition_key"] for r in b["ai_review"]])


class Finalize(unittest.TestCase):
    FILES = {**BASE, "external/creative_experiment_plan.csv": PLAN_HDR + plan_row(),
             "custom/creative_experiment_results.csv": results()}

    def decide(self, proposal):
        def f(body):
            item = next(r for r in body["ai_review"] if r["condition_key"] == "experiment_decision")
            return [{"id": item["id"], "outcome": "winner_supported", "rationale": "report", "proposal": proposal}]
        return f

    def test_interval_including_zero_rejected(self):
        rc, final = run(self, self.FILES, {"srm_alpha": 0.001}, decisions=self.decide(
            {"inference_ref": "ads-exp-report-1", "effect_estimate": 0.01, "interval": [-0.01, 0.03],
             "guardrails_ok": True}))
        self.assertEqual(rc, 4)
        self.assertNotIn("experiment_decision", keys(final))

    def test_valid_winner_accepted_as_info_opportunity(self):
        rc, final = run(self, self.FILES, {"srm_alpha": 0.001}, decisions=self.decide(
            {"inference_ref": "ads-exp-report-1", "effect_estimate": 0.01, "interval": [0.004, 0.02],
             "guardrails_ok": True}))
        self.assertEqual(rc, 0)
        self.assertIn("experiment_decision", keys(final, "Info"))

    def test_foreign_inference_ref_rejected(self):
        rc, _ = run(self, self.FILES, {"srm_alpha": 0.001}, decisions=self.decide(
            {"inference_ref": "my-z-test", "effect_estimate": 0.01, "interval": [0.004, 0.02], "guardrails_ok": True}))
        self.assertEqual(rc, 4)


if __name__ == "__main__":
    unittest.main()
