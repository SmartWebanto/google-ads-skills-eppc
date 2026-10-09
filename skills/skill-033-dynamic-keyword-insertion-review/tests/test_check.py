"""test_check.py — Decision-boundary tests for skill-033 keyword insertion checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-033-dynamic-keyword-insertion-review/tests -t skills/skill-033-dynamic-keyword-insertion-review
rules:   Temp folders only; pins token classification, fallback/limit logic, preview-gated Warning,
profile-supplied competitor terms and proposal verification, never wording.
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
_spec = importlib.util.spec_from_file_location("skill033_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,2\n")
ADS_HDR = "id,campaign_id,ad_group_id,type,status,headlines,descriptions\n"
KW_HDR = "id,campaign_id,ad_group_id,text,match_type,status\n"
REV_HDR = ("account_id,ad_id,field,keyword_id,review_at,language,rendered_preview,fallback_preview,preview_source,"
           "allowed_term_status,authorization_ref,reviewer_role,rationale\n")


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
    (root / "profile.json").write_text(json.dumps(profile if profile is not None else {"competitor_terms": []}))
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


def rkeys(body):
    return sorted(r["condition_key"] for r in body["ai_review"])


def files(headline, keywords=("cordless drill",), extra=None):
    kw = KW_HDR + "".join(f"K{i},C1,G1,{t},BROAD,ENABLED\n" for i, t in enumerate(keywords)) + \
        "KX,C1,G2,a very very long other group keyword,EXACT,ENABLED\n"
    return {"ads.csv": ADS_HDR + f"A1,C1,G1,RESPONSIVE_SEARCH_AD,ENABLED,{headline} | Plain headline,Buy now\n",
            "keywords.csv": kw, **(extra or {})}


class Tokens(unittest.TestCase):
    def test_only_keyword_tokens_are_dki(self):
        kinds = [(t["kind"], t.get("fallback")) for t in
                 M.tokens("{KeyWord:Drills} {CUSTOMIZER.price:10} {LOCATION(City)} {keyword}")]
        self.assertEqual(kinds, [("dki", "Drills"), ("other_customizer", None), ("other_customizer", None),
                                 ("dki", None)])

    def test_case_variants(self):
        self.assertEqual(M._render_kw("cordless drill set", "title"), "Cordless Drill Set")
        self.assertEqual(M._render_kw("cordless drill set", "sentence"), "Cordless drill set")
        self.assertEqual(M._render_kw("cordless drill set", "caps_first_title_rest"), "CORDLESS Drill Set")

    def test_customizer_only_ads_not_applicable(self):
        _, b = run(self, files("Price {CUSTOMIZER.price:10}"))
        self.assertEqual({c["check"]: c["status"] for c in b["coverage"]}["syntax_validity"], "not_applicable")


class Syntax(unittest.TestCase):
    def test_missing_fallback_is_suspected_info_without_preview(self):
        _, b = run(self, files("Buy {KeyWord}"))
        self.assertEqual(keys(b), ["suspected_template_error"])
        self.assertNotIn("invalid_template", rkeys(b))

    def test_preview_row_enables_warning_review(self):
        rev = REV_HDR + "1,A1,headline,K0,2026-09-05,it,Buy,Buy,Ads preview,,,,x\n"
        _, b = run(self, files("Buy {KeyWord}", extra={"external/dki_review.csv": rev}))
        self.assertIn("invalid_template", rkeys(b))

    def test_valid_template_has_no_syntax_finding(self):
        _, b = run(self, files("Buy {KeyWord:Drills}"))
        self.assertNotIn("suspected_template_error", keys(b))


class Length(unittest.TestCase):
    def test_oversized_keyword_with_fitting_fallback_is_info(self):
        _, b = run(self, files("Buy {KeyWord:Drills} Now", keywords=("cordless drill", "professional cordless drill set")))
        self.assertIn("oversized_keyword_valid_fallback", keys(b, "Info"))
        self.assertNotIn("fallback_exceeds_limit", keys(b))

    def test_other_group_keywords_are_not_rendered(self):
        _, b = run(self, files("Buy {KeyWord:Drills} Now"))
        self.assertNotIn("oversized_keyword_valid_fallback", keys(b))

    def decide(self, template):
        def f(body):
            item = next(r for r in body["ai_review"] if r["condition_key"] == "fallback_exceeds_limit")
            return [{"id": item["id"], "outcome": "confirmed_invalid", "rationale": "too long",
                     "proposal": {"proposed_template": template}}]
        return f

    def test_long_fallback_review_and_proposal_verification(self):
        f = files("{KeyWord:Professional Cordless Drill Sets} X", keywords=("professional cordless drill set",))
        _, b = run(self, f)
        self.assertIn("fallback_exceeds_limit", rkeys(b))
        rc, _ = run(self, f, decisions=self.decide("Professional Drills"))  # drops DKI
        self.assertEqual(rc, 4)
        rc, final = run(self, f, decisions=self.decide("{KeyWord:Drill Sets} X"))
        self.assertEqual(rc, 0)
        self.assertIn("fallback_exceeds_limit", keys(final, "Warning"))


class Authorization(unittest.TestCase):
    def test_profile_competitor_term_is_info(self):
        f = files("Buy {KeyWord:Drills}", keywords=("bosch drill",))
        _, b = run(self, f, {"competitor_terms": ["bosch"]})
        self.assertIn("potential_restricted_insertion", keys(b, "Info"))
        _, b = run(self, f, {"competitor_terms": []})
        self.assertNotIn("potential_restricted_insertion", keys(b))

    def test_authorized_review_row_clears(self):
        rev = REV_HDR + "1,A1,headline,K0,2026-09-05,it,x,x,Ads preview,authorized,auth-1,legal,ok\n"
        f = files("Buy {KeyWord:Drills}", keywords=("bosch drill",), extra={"external/dki_review.csv": rev})
        _, b = run(self, f, {"competitor_terms": ["bosch"]})
        self.assertNotIn("potential_restricted_insertion", keys(b))

    def test_rendered_review_warning_only_with_preview(self):
        _, b = run(self, files("Buy {KeyWord:Drills}"))
        r = next(x for x in b["ai_review"] if x["condition_key"] == "rendered_message")
        self.assertNotIn("Warning", [o["severity"] for o in r["outcomes"].values()])

    def test_missing_keywords_skip_rendering(self):
        f = files("Buy {KeyWord:Drills}")
        del f["keywords.csv"]
        rc, b = run(self, f)
        self.assertEqual(rc, 0)
        c = {x["check"]: x["status"] for x in b["coverage"]}
        self.assertEqual(c["length_fallback"], "skipped")
        self.assertEqual(c["rendered_message_review"], "skipped")


if __name__ == "__main__":
    unittest.main()
