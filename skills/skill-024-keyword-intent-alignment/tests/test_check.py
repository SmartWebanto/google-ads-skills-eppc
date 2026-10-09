"""test_check.py — skill-024 boundaries: URL precedence, page evidence, context gating, zero-conversion gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-024-keyword-intent-alignment/tests
rules:   Temp folders only; asserts condition keys/outcomes and gating, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial tests
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

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_024", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
PROFILE = {"brand_terms": ["acme"], "competitor_terms": ["bosch"], "product_service_taxonomy": ["power tools"],
           "campaign_objectives": {"C1": {"goal_ids": ["g1"], "target_cpa": 40}},
           "tracking_verified": {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30", "source_ref": "qa"}}}
PAGE = {"url": "https://Shop.example/drills/", "final_url": "https://shop.example/drills", "captured_at": "2026-09-01",
        "http_status": "200", "title": "Garden hoses", "headings": "Hoses and reels",
        "main_content_excerpt": "We sell garden hoses only.", "evidence_ref": "cap-1"}


class CheckTests(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, profile=PROFILE, pages=(PAGE,), kw_url="", kw_cost=80, kw_conv=0, lag="2"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [{**ACCOUNT, "conversion_lag_days": lag}])
        self._write(root, "campaigns", [{"id": "C1", "status": "ENABLED", "target_cpa": "40"}])
        self._write(root, "keywords", [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "cordless drill",
                                        "match_type": "PHRASE", "status": "ENABLED", "final_url": kw_url}])
        self._write(root, "keyword_metrics", [{"keyword_id": "K1", "campaign_id": "C1", "ad_group_id": "G1",
                                               "clicks": 40, "cost": kw_cost, "conversions": kw_conv}])
        self._write(root, "ads", [{"id": "A1", "ad_group_id": "G1", "status": "ENABLED", "approval_status": "APPROVED",
                                   "final_url": "https://shop.example/drills#top"}])
        self._write(root, "search_terms", [
            {"search_term": "acme bosch drill", "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": "K1",
             "clicks": 10, "cost": 20, "conversions": 0}])
        if pages:
            self._write(root, "external/landing_page_content", list(pages))
        self.prof = Path(tmp.name) / "p.json"
        self.prof.write_text(json.dumps(profile))
        self.root, self.out = root, out
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--profile", str(self.prof), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _finalize(self, decisions):
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--profile", str(self.prof), "--out",
                               str(self.out), "--decisions", str(dec)])

    def _rv(self, body, key):
        return [r for r in body["ai_review"] if r["condition_key"] == key]

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_page_capture_joins_normalized_url_and_offers_warning(self):
        rv = self._rv(self._run(), "page_contradicts_requirement")
        self.assertEqual([r["entity"]["url"] for r in rv], ["https://shop.example/drills"])
        self.assertEqual(rv[0]["outcomes"]["contradicted"]["severity"], "Warning")

    def test_keyword_override_takes_precedence(self):
        body = self._run(kw_url="https://shop.example/other")
        self.assertEqual(self._rv(body, "page_contradicts_requirement"), [])
        self.assertEqual(self._cov(body)["page_fit"], "partial")  # override URL has no capture

    def test_missing_page_file_skips_page_fit(self):
        body = self._run(pages=())
        self.assertEqual(self._cov(body)["page_fit"], "skipped")
        self.assertEqual(self._rv(body, "page_contradicts_requirement"), [])

    def test_no_approved_context_withholds_contradiction(self):
        prof = {k: v for k, v in PROFILE.items() if k not in ("product_service_taxonomy", "campaign_objectives")}
        rv = self._rv(self._run(profile=prof), "page_contradicts_requirement")
        self.assertNotIn("contradicted", rv[0]["outcomes"])

    def test_verify_contradiction_requires_cited_excerpt(self):
        item = self._rv(self._run(), "page_contradicts_requirement")[0]
        base = {"id": item["id"], "outcome": "contradicted", "rationale": "page sells hoses, keyword asks for drills"}
        self.assertEqual(self._finalize([{**base, "proposal": {"evidence_ref": "cap-9", "excerpt": "garden hoses"}}]), 4)
        self.assertEqual(self._finalize([{**base, "proposal": {"evidence_ref": "cap-1", "excerpt": "cordless drills"}}]), 4)
        self.assertEqual(self._finalize([{**base, "proposal": {"evidence_ref": "cap-1",
                                                               "excerpt": "we sell garden hoses only"}}]), 0)

    def test_zero_conversion_keyword_gates(self):
        body = self._run()
        self.assertEqual(len(self._rv(body, "zero_conversion_keyword")), 1)
        self.assertEqual([f["severity"] for f in body["findings"] if f["condition_key"] == "zero_conversion_keyword"],
                         ["Info"])
        self.assertEqual(self._rv(self._run(kw_cost=49.99), "zero_conversion_keyword"), [])  # floor max(50, 40)
        self.assertEqual(self._rv(self._run(kw_conv=1), "zero_conversion_keyword"), [])
        body = self._run(lag="")
        self.assertEqual(self._rv(body, "zero_conversion_keyword"), [])
        self.assertEqual(self._cov(body)["zero_conversion_screen"], "partial")
        prof = {k: v for k, v in PROFILE.items() if k != "tracking_verified"}
        body = self._run(profile=prof)
        self.assertEqual(self._rv(body, "zero_conversion_keyword"), [])
        self.assertEqual(self._cov(body)["zero_conversion_screen"], "partial")

    def test_brand_precedes_competitor(self):
        body = self._run()
        obs = [o["data"] for o in body["observations"] if o["check"] == "brand_competitor_precedence"][0]
        self.assertIn("C1:brand_term", obs["by_campaign_tag"])
        self.assertEqual(obs["brand_and_competitor_queries"], 1)


if __name__ == "__main__":
    unittest.main()
