"""test_check.py — Decision-boundary tests for skill-034 ad-to-page consistency checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-034-ad-copy-landing-page-consistency/tests -t skills/skill-034-ad-copy-landing-page-consistency
rules:   Temp folders only; pins claim validity, snapshot currency, profile-supplied OOS markers, stale-year
review and verbatim-quote verification, never wording.
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
_spec = importlib.util.spec_from_file_location("skill034_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,2\n")
BASE = {
    "campaigns.csv": "id,status\nC1,ENABLED\n",
    "ad_groups.csv": "id,campaign_id,status\nG1,C1,ENABLED\nG2,C1,PAUSED\n",
    "ads.csv": ("id,campaign_id,ad_group_id,status,final_url,headlines,descriptions\n"
                "A1,C1,G1,ENABLED,https://x.example/drills?c=1,Drills 20% Off | Summer Sale 2025,Free delivery in 48h\n"
                "A2,C1,G2,ENABLED,https://x.example/drills?c=1,Drills 20% Off,Old copy\n"
                "A3,C1,G1,ENABLED,https://x.example/,Acme Since 1998,Tools shop\n"),
}
SNAP_HDR = "url,device,locale,captured_at,resolved_url,title,visible_text,offer_terms,availability,CTA,screenshot_or_snapshot_ref,source_ref\n"
CLAIM_HDR = "account_id,ad_id,claim_id,claim_text,supporting_source,market,valid_from,valid_to,qualification,reviewer_role,verification_state\n"


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


def found(body, key, sev=None, field="ad_id"):
    return sorted(str(f["entity"].get(field)) for f in body["findings"]
                  if f["condition_key"] == key and sev in (None, f["severity"]))


def reviews(body, key):
    return sorted(r["entity"].get("ad_id") for r in body["ai_review"] if r["condition_key"] == key)


class Claims(unittest.TestCase):
    def test_expired_claim_in_eligible_ad_is_warning(self):
        c = CLAIM_HDR + ("1,A1,K1,20% Off,brief,IT,2026-06-01,2026-07-31,,legal,verified\n"
                         "1,A2,K2,20% Off,brief,IT,2026-06-01,2026-07-31,,legal,verified\n")
        _, b = run(self, {**BASE, "external/ad_claim_register.csv": c})
        self.assertEqual(found(b, "claim_outside_validity", "Warning"), ["A1"])  # A2 paused group

    def test_valid_or_absent_claim_text_is_not_a_finding(self):
        c = CLAIM_HDR + ("1,A1,K1,20% Off,brief,IT,2026-06-01,2026-12-31,,legal,verified\n"
                         "1,A3,K3,30% Off,brief,IT,2026-06-01,2026-07-31,,legal,verified\n")
        _, b = run(self, {**BASE, "external/ad_claim_register.csv": c})
        self.assertEqual(found(b, "claim_outside_validity"), [])

    def test_unverified_claim_is_info(self):
        c = CLAIM_HDR + "1,A1,K1,20% Off,brief,IT,2026-06-01,2026-12-31,,legal,pending\n"
        _, b = run(self, {**BASE, "external/ad_claim_register.csv": c})
        self.assertEqual(found(b, "claim_unverified", "Info"), ["A1"])


class Snapshots(unittest.TestCase):
    def test_missing_and_stale_snapshots_are_info_requests(self):
        s = SNAP_HDR + "https://x.example/,MOBILE,it,2026-05-01,,T,home,,in_stock,Shop,shot,ref\n"
        _, b = run(self, {**BASE, "external/landing_page_snapshots.csv": s})
        self.assertEqual(found(b, "page_evidence_missing", "Info", "final_url"), ["https://x.example/drills?c=1"])
        self.assertEqual(found(b, "page_evidence_stale", "Info", "final_url"), ["https://x.example/"])
        self.assertEqual(reviews(b, "offer_contradiction"), [])

    def test_exact_url_join_preserves_query(self):
        s = SNAP_HDR + "https://x.example/drills,MOBILE,it,2026-08-10,,T,drills,10% off,in_stock,Buy,shot,ref\n"
        _, b = run(self, {**BASE, "external/landing_page_snapshots.csv": s})
        self.assertEqual(reviews(b, "offer_contradiction"), [])

    def decide(self, outcome, proposal):
        def f(body):
            item = next(r for r in body["ai_review"] if r["condition_key"] == "offer_contradiction")
            return [{"id": item["id"], "outcome": outcome, "rationale": "20 vs 10", "proposal": proposal}]
        return f

    def test_contradiction_requires_verbatim_quotes_and_critical_evidence(self):
        files = {**BASE, "external/landing_page_snapshots.csv": SNAP_HDR +
                 "https://x.example/drills?c=1,MOBILE,it,2026-08-10,,T,drills page,10% off drills,in_stock,Buy,shot,ref\n"}
        self.assertEqual(reviews(run(self, files)[1], "offer_contradiction"), ["A1"])
        rc, _ = run(self, files, decisions=self.decide("contradicted", {"ad_quote": "20% off", "page_quote": "50% off"}))
        self.assertEqual(rc, 4)
        rc, _ = run(self, files, decisions=self.decide("harmful_deceptive", {"ad_quote": "20% off",
                                                                             "page_quote": "10% off drills"}))
        self.assertEqual(rc, 4)
        rc, final = run(self, files, decisions=self.decide("contradicted", {"ad_quote": "20% off",
                                                                            "page_quote": "10% off drills"}))
        self.assertEqual(rc, 0)
        self.assertEqual(found(final, "offer_contradiction", "Warning"), ["A1"])


class Availability(unittest.TestCase):
    def test_structured_out_of_stock_goes_to_review(self):
        s = SNAP_HDR + "https://x.example/drills?c=1,MOBILE,it,2026-08-10,,T,drills,,out_of_stock,Buy,shot,ref\n"
        _, b = run(self, {**BASE, "external/landing_page_snapshots.csv": s})
        self.assertEqual(found(b, "out_of_stock_destination", "Info"), ["A1"])
        self.assertEqual(reviews(b, "out_of_stock_contradiction"), ["A1"])

    def test_text_markers_only_from_profile(self):
        s = SNAP_HDR + "https://x.example/drills?c=1,MOBILE,it,2026-08-10,,T,Prodotto esaurito,,,Buy,shot,ref\n"
        files = {**BASE, "external/landing_page_snapshots.csv": s}
        _, b = run(self, files)
        self.assertEqual(found(b, "out_of_stock_destination"), [])
        _, b = run(self, files, {"out_of_stock_markers": ["esaurito"]})
        self.assertEqual(found(b, "out_of_stock_destination"), ["A1"])


class CopyChecks(unittest.TestCase):
    def test_past_year_reviewed_current_year_not(self):
        _, b = run(self, BASE)
        # A1 has 2025 (review), A3 has 1998 (also past: review decides legitimacy), A2 paused
        self.assertEqual(reviews(b, "stale_year_reference"), ["A1", "A3"])

    def test_homepage_info_only_for_root_url(self):
        _, b = run(self, BASE)
        self.assertEqual(found(b, "homepage_destination", "Info", "final_url"), ["https://x.example/"])

    def test_missing_ads_skip_all(self):
        rc, b = run(self, {"campaigns.csv": BASE["campaigns.csv"]})
        self.assertEqual(rc, 0)
        self.assertEqual({c["status"] for c in b["coverage"]}, {"skipped"})


if __name__ == "__main__":
    unittest.main()
