"""test_check.py — Decision-boundary tests for skill-037 ad policy/eligibility triage.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-037-ad-disapproval-monitoring/tests -t skills/skill-037-ad-disapproval-monitoring
rules:   Temp folders only; pins scope separation, silenced-group gate, review-age confidence and Critical
verification, never wording.
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
_spec = importlib.util.spec_from_file_location("skill037_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,2\n")
SPINE = {
    "campaigns.csv": "id,status\nC1,ENABLED\nC2,PAUSED\n",
    "ad_groups.csv": "id,campaign_id,status\nG1,C1,ENABLED\nG2,C1,ENABLED\nG3,C2,ENABLED\n",
}
ADS_HDR = "id,campaign_id,ad_group_id,type,status,approval_status,policy_topics\n"


def run(test, files, complete=True, profile=None, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    files = {"account.csv": ACCOUNT, **files}
    comp = "complete" if complete else "partial sample"
    files["table_manifest.csv"] = "filename,completeness,truncation\n" + "".join(
        f"{n},{comp if n.startswith('ads') else 'complete'},none\n" for n in list(files))
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


def found(body, key, sev=None):
    return sorted(str(f["entity"].get("ad_group_id")) + "/" + str(f["entity"].get("ad_id", ""))
                  for f in body["findings"] if f["condition_key"] == key and sev in (None, f["severity"]))


def reviews(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


SILENCED_ADS = ADS_HDR + ("A1,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,DISAPPROVED,Misleading content\n"
                          "A2,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,DISAPPROVED,Misleading content\n"
                          "A3,C1,G2,RESPONSIVE_SEARCH_AD,ENABLED,DISAPPROVED,Trademarks\n"
                          "A4,C1,G2,RESPONSIVE_SEARCH_AD,ENABLED,APPROVED_LIMITED,Alcohol\n"
                          "A5,C2,G3,RESPONSIVE_SEARCH_AD,ENABLED,DISAPPROVED,Trademarks\n")


class Eligibility(unittest.TestCase):
    def test_silenced_group_warning_only_when_no_eligible_ad(self):
        _, b = run(self, {**SPINE, "ads.csv": SILENCED_ADS})
        self.assertEqual(found(b, "group_no_eligible_ads", "Warning"), ["G1/"])
        # G2 still has a limited (potentially eligible) ad: disapproval goes to review, not Warning
        self.assertEqual(found(b, "active_disapproval", "Info"), ["G2/A3"])
        self.assertEqual(len(reviews(b, "active_disapproval")), 1)

    def test_paused_parent_is_work_queue_not_blocker(self):
        _, b = run(self, {**SPINE, "ads.csv": SILENCED_ADS})
        self.assertEqual(found(b, "paused_affected_ad"), ["G3/A5"])
        self.assertNotIn("G3/", found(b, "group_no_eligible_ads"))

    def test_incomplete_inventory_cannot_call_group_silenced(self):
        _, b = run(self, {**SPINE, "ads.csv": SILENCED_ADS}, complete=False)
        self.assertEqual(found(b, "group_no_eligible_ads"), [])
        self.assertEqual(cov(b)["group_eligibility"], "partial")

    def test_unknown_approval_blocks_silenced_conclusion(self):
        ads = ADS_HDR + ("A1,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,DISAPPROVED,Misleading content\n"
                         "A2,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,,\n")
        _, b = run(self, {**SPINE, "ads.csv": ads})
        self.assertEqual(found(b, "group_no_eligible_ads"), [])

    def test_limited_active_ad_is_provisional_info_with_review(self):
        _, b = run(self, {**SPINE, "ads.csv": SILENCED_ADS})
        self.assertEqual(found(b, "limited_serving", "Info"), ["G2/A4"])
        self.assertEqual(len(reviews(b, "limited_serving")), 1)

    def test_missing_spine_skips_everything(self):
        rc, b = run(self, {"ads.csv": SILENCED_ADS})
        self.assertEqual(rc, 0)
        self.assertEqual(set(cov(b).values()), {"skipped"})
        self.assertEqual(b["findings"], [])


STATUS_HDR = ("campaign_id,ad_group_id,ad_id,snapshot_at,approval_status,review_status,policy_topics,"
              "eligible_geographies_or_formats,serving_status,source_ref\n")


class CriticalPath(unittest.TestCase):
    FILES = {**SPINE, "ads.csv": SILENCED_ADS, "custom/ad_policy_status.csv": STATUS_HDR + (
        "C1,G1,A1,2026-09-06,DISAPPROVED,REVIEWED,Misleading content,none,NOT_SERVING,pm-1\n"
        "C1,G1,A2,2026-09-06,DISAPPROVED,REVIEWED,Misleading content,none,NOT_SERVING,pm-2\n")}

    def decide(self, proposal):
        def f(body):
            item = reviews(body, "group_no_eligible_ads")[0]
            return [{"id": item["id"], "outcome": "material_loss_confirmed", "rationale": "diagnosis",
                     "proposal": proposal}]
        return f

    def test_critical_requires_supplied_evidence_ref(self):
        rc, final = run(self, self.FILES, decisions=self.decide({}))
        self.assertEqual(rc, 4)
        self.assertEqual(found(final, "group_no_eligible_ads", "Critical"), [])
        self.assertEqual(found(final, "group_no_eligible_ads", "Warning"), ["G1/"])
        rc, _ = run(self, self.FILES, decisions=self.decide({"evidence_ref": "made-up"}))
        self.assertEqual(rc, 4)

    def test_critical_accepted_with_diagnosis_ref(self):
        rc, final = run(self, self.FILES, decisions=self.decide({"evidence_ref": "pm-1"}))
        self.assertEqual(rc, 0)
        self.assertEqual(found(final, "group_no_eligible_ads", "Critical"), ["G1/"])

    def test_no_diagnosis_file_keeps_warning_without_critical_path(self):
        _, b = run(self, {**SPINE, "ads.csv": SILENCED_ADS})
        self.assertEqual(reviews(b, "group_no_eligible_ads"), [])
        self.assertEqual(cov(b)["serving_diagnosis"], "skipped")


HIST_HDR = "ad_id,event_id,event_at,event_type,prior_status,new_status,affected_policy_topic\n"


class ReviewAge(unittest.TestCase):
    def files(self, hist):
        ads = ADS_HDR + "A1,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,UNDER_REVIEW,\n"
        return {**SPINE, "ads.csv": ads, "custom/ad_policy_history.csv": HIST_HDR + hist}

    def test_exact_age_from_submission_goes_to_review(self):
        _, b = run(self, self.files("A1,E1,2026-08-20,submitted,,UNDER_REVIEW,\n"))
        r = reviews(b, "review_delay")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["evidence"]["review_age_days"], 17)
        self.assertEqual(found(b, "review_age_unknown"), [])

    def test_edit_restarts_review_clock(self):
        _, b = run(self, self.files("A1,E1,2026-08-01,submitted,,UNDER_REVIEW,\n"
                                    "A1,E2,2026-09-04,edited,UNDER_REVIEW,UNDER_REVIEW,\n"))
        self.assertEqual(reviews(b, "review_delay")[0]["evidence"]["review_age_days"], 2)

    def test_observation_only_history_is_lower_bound_info(self):
        _, b = run(self, self.files("A1,E1,2026-08-10,status_observed,,UNDER_REVIEW,\n"))
        self.assertEqual(found(b, "review_age_unknown", "Info"), ["G1/A1"])
        self.assertEqual(reviews(b, "review_delay"), [])

    def test_missing_history_is_skip_not_finding(self):
        ads = ADS_HDR + "A1,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,UNDER_REVIEW,\n"
        _, b = run(self, {**SPINE, "ads.csv": ads})
        self.assertEqual(cov(b)["review_age"], "skipped")
        self.assertEqual(found(b, "review_age_unknown"), [])


if __name__ == "__main__":
    unittest.main()
