"""test_check.py — Decision-boundary tests for skill-038 editorial checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-038-spelling-editorial-error-detection/tests -t skills/skill-038-spelling-editorial-error-detection
rules:   Temp folders only; pins brief-documented inconsistency, language-gated Warning outcomes, exception
handling, dynamic-syntax separation and correction verification, never wording.
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
_spec = importlib.util.spec_from_file_location("skill038_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,2\n")
BRIEF_HDR = ("account_id,locale,term_or_rule_id,language,preferred_spelling,exception,style_rule,claim_support_ref,"
             "reviewer_role,valid_from,valid_to\n")


def ads(headline, desc="Buy now", approval="APPROVED", topics=""):
    return {"campaigns.csv": "id,languages\nC1,it\n",
            "ads.csv": ("id,campaign_id,ad_group_id,status,headlines,descriptions,approval_status,policy_topics\n"
                        f"A1,C1,G1,ENABLED,{headline},{desc},{approval},{topics}\n")}


def run(test, files, profile=None, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    files = {"account.csv": ACCOUNT, **files}
    files["table_manifest.csv"] = "filename,completeness,truncation\n" + "".join(f"{n},complete,none\n" for n in list(files))
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


def ad_review(body):
    return next(r for r in body["ai_review"] if r["condition_key"] == "confirmed_language_error"
                and "field" not in r["entity"])


class Brief(unittest.TestCase):
    def brief(self, lang="it", valid_to="2027-01-01", term="WiFi"):
        return {"external/editorial_brief.csv": BRIEF_HDR + f"1,it-IT,R1,{lang},{term},,,,editor,2026-01-01,{valid_to}\n"}

    def test_brief_casing_mismatch_is_warning(self):
        _, b = run(self, {**ads("Fast Wifi Drills"), **self.brief()})
        self.assertEqual(keys(b, "Warning"), ["documented_style_inconsistency"])

    def test_exact_preferred_spelling_expired_or_other_language_is_clean(self):
        for files in ({**ads("Fast WiFi Drills"), **self.brief()},
                      {**ads("Fast Wifi Drills"), **self.brief(valid_to="2026-06-01")},
                      {**ads("Fast Wifi Drills"), **self.brief(lang="de")},
                      {**ads("Wifistation Drills"), **self.brief()}):
            _, b = run(self, files)
            self.assertNotIn("documented_style_inconsistency", keys(b))

    def test_warning_outcome_only_with_language_coverage(self):
        _, b = run(self, ads("Fast Drills"))
        self.assertNotIn("Warning", [o["severity"] for o in ad_review(b)["outcomes"].values()])
        _, b = run(self, {**ads("Fast Drills"), **self.brief()})
        self.assertIn("Warning", [o["severity"] for o in ad_review(b)["outcomes"].values()])

    def test_missing_brief_and_list_skips_spelling(self):
        _, b = run(self, ads("Fast Drills"))
        c = {x["check"]: x["status"] for x in b["coverage"]}
        self.assertEqual(c["spelling_screen"], "skipped")
        self.assertEqual(c["language_resolution"], "skipped")


class Screens(unittest.TestCase):
    def test_profile_misspelling_list_is_provisional_review(self):
        _, b = run(self, ads("Recieve Drills Fast"), {"editorial_misspellings": {"recieve": "receive"}})
        self.assertIn("suspected_misspelling", keys(b, "Info"))
        self.assertEqual(keys(b, "Warning"), [])

    def test_all_caps_and_repeated_punctuation_with_exceptions(self):
        _, b = run(self, ads("SUPER DRILLS!! | BOSCH Drills | {KeyWord:WIRELESS} Set"), {"brand_terms": ["bosch"]})
        f = next(x for x in b["findings"] if x["condition_key"] == "suspected_editorial_issue")
        self.assertEqual(sorted(h["token"] for h in f["evidence"]["hits"]), ["!!", "DRILLS", "SUPER"])
        r = next(x for x in b["ai_review"] if x["condition_key"] == "style_violation")
        self.assertNotIn("Warning", [o["severity"] for o in r["outcomes"].values()])  # no brief style rule

    def test_acronym_below_threshold_is_not_flagged(self):
        _, b = run(self, ads("EUR 79 Drills"))
        self.assertNotIn("suspected_editorial_issue", keys(b))

    def test_claim_terms_are_referrals_not_errors(self):
        _, b = run(self, ads("Best Drills"), {"claim_terms": ["best"]})
        self.assertEqual(keys(b, "Info"), ["unsupported_claim_referral"])
        _, b = run(self, {**ads("Best Drills"), "external/editorial_brief.csv": BRIEF_HDR +
                          "1,it-IT,R2,it,best,,,award-2026,legal,2026-01-01,2027-01-01\n"}, {"claim_terms": ["best"]})
        self.assertNotIn("unsupported_claim_referral", keys(b))

    def test_platform_policy_is_info_owned_by_037(self):
        _, b = run(self, ads("Drills", approval="DISAPPROVED", topics="Punctuation"))
        f = next(x for x in b["findings"] if x["condition_key"] == "platform_policy_topic")
        self.assertEqual((f["severity"], f["owner"]), ("Info", "skill-037-ad-disapproval-monitoring"))


class Verify(unittest.TestCase):
    FILES = {**ads("Fast Drils {KeyWord:Tools}"),
             "external/editorial_brief.csv": BRIEF_HDR + "1,it-IT,R1,it,WiFi,,,,editor,2026-01-01,2027-01-01\n"}

    def decide(self, original, proposed):
        def f(body):
            return [{"id": ad_review(body)["id"], "outcome": "confirmed_error", "rationale": "typo",
                     "proposal": {"field": "headline", "index": 0, "original": original, "proposed": proposed}}]
        return f

    def test_correction_must_quote_ad_and_keep_dynamic_syntax(self):
        rc, _ = run(self, self.FILES, decisions=self.decide("Fast Drils {KeyWord:Tools}", "Fast Drills Tools"))
        self.assertEqual(rc, 4)
        rc, _ = run(self, self.FILES, decisions=self.decide("Slow Drils", "Slow Drills"))
        self.assertEqual(rc, 4)
        rc, final = run(self, self.FILES, decisions=self.decide("Drils", "Drills"))
        self.assertEqual(rc, 0)
        self.assertIn("confirmed_language_error", keys(final, "Warning"))

    def test_dynamic_syntax_excluded_from_visible_copy(self):
        self.assertEqual(M.visible("Buy {KeyWord:WIRELESS} now {COUNTDOWN(2026-09-30)}"), "Buy now")


if __name__ == "__main__":
    unittest.main()
