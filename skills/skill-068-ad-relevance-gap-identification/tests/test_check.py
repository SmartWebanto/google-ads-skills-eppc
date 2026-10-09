"""test_check.py — Decision-boundary tests for skill-068 ad-relevance gaps.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-068-ad-relevance-gap-identification/tests -t skills/skill-068-ad-relevance-gap-identification
rules:   Temp folders only; pins severities, coverage and verify() gates, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_068", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(c for r in rows for c in r))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _kw(kid, rating, cost, text=None, gid="G1", clicks=150):
    return ({"id": kid, "campaign_id": "C1", "ad_group_id": gid, "text": text or f"garden hose {kid}",
             "match_type": "PHRASE", "status": "ENABLED", "ad_relevance": rating},
            {"keyword_id": kid, "campaign_id": "C1", "ad_group_id": gid, "impressions": 2000, "clicks": clicks,
             "cost": cost, "conversions": 5})


AD = {"id": "A1", "campaign_id": "C1", "ad_group_id": "G1", "status": "ENABLED", "approval_status": "APPROVED",
      "headlines": "Cordless Drills 18V | Free Shipping", "descriptions": "Top drill brands.", "final_url": "https://x/"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, kws, ads=(AD,), lag="2", target_cpa="", terms=None, ads_complete=True):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "rates_format": "fraction",
                                       "money_unit": "currency", "conversion_lag_days": lag}])
        _write(root / "campaigns.csv", [{"id": "C1", "channel_type": "SEARCH", "target_cpa": target_cpa}])
        _write(root / "keywords.csv", [k for k, _ in kws])
        _write(root / "keyword_metrics.csv", [m for _, m in kws])
        if ads:
            _write(root / "ads.csv", list(ads))
        if terms:
            _write(root / "search_terms.csv", terms)
        _write(root / "table_manifest.csv", [
            {"filename": "keywords.csv", "completeness": "complete", "truncation": "none"},
            {"filename": "keyword_metrics.csv", "completeness": "complete", "truncation": "none"},
            {"filename": "ads.csv", "completeness": "complete" if ads_complete else "partial", "truncation": "none"}])
        self.profile = self.dir / "profile.json"
        self.profile.write_text(json.dumps({"objectives": ["sell drills"]}))
        self.root = root
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, self.profile).finish()

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def status(body, check):
        return next(c["status"] for c in body["coverage"] if c["check"] == check)


class Inventory(Base):
    def test_below_average_at_spend_material_is_warning(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 200)])
        self.assertEqual([f["severity"] for f in self.found(body, "below_average_ad_relevance_material")], ["Warning"])

    def test_campaign_target_raises_threshold(self):
        # 3 x target CPA 100 = 300 > 250
        body = self.build([_kw("K1", "BELOW_AVERAGE", 250)], target_cpa="100")
        self.assertEqual(self.found(body, "below_average_ad_relevance_material"), [])

    def test_average_or_unrated_is_never_warning(self):
        body = self.build([_kw("K1", "AVERAGE", 5000), _kw("K2", "", 5000)])
        self.assertEqual(self.found(body, "below_average_ad_relevance_material"), [])
        self.assertEqual([f["severity"] for f in self.found(body, "ad_relevance_unavailable")], ["Info"])

    def test_missing_rating_column_skips_dependents(self):
        kws = [_kw("K1", "BELOW_AVERAGE", 900)]
        for k, _ in kws:
            del k["ad_relevance"]
        body = self.build(kws)
        self.assertEqual(self.status(body, "ad_relevance_inventory"), "skipped")
        self.assertEqual(self.status(body, "intent_theme_review"), "skipped")
        self.assertEqual(body["ai_review"], [])


class Ads(Base):
    def test_no_eligible_ads_is_info_only_with_complete_inventory(self):
        paused = dict(AD, status="PAUSED")
        body = self.build([_kw("K1", "BELOW_AVERAGE", 900)], ads=(paused,))
        self.assertEqual([f["severity"] for f in self.found(body, "no_eligible_ads")], ["Info"])
        self.assertEqual(body["ai_review"], [])
        body = self.build([_kw("K1", "BELOW_AVERAGE", 900)], ads=(paused,), ads_complete=False)
        self.assertEqual(self.found(body, "no_eligible_ads"), [])
        self.assertEqual(self.status(body, "ad_eligibility_join"), "partial")

    def test_literal_absence_is_observation_not_finding(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 10)])
        self.assertEqual([f for f in body["findings"] if "literal" in f["condition_key"]], [])
        obs = [o for o in body["observations"] if o["check"] == "literal_token_presence"]
        self.assertEqual(obs[0]["data"]["literal_absent"], ["K1"])


class Review(Base):
    TERMS = [{"search_term": "garden hose 30m", "campaign_id": "C1", "ad_group_id": "G1", "matched_keyword_id": "K1",
              "impressions": 100, "clicks": 10, "cost": 30, "conversions": 0}]

    def test_mismatch_warning_needs_material_and_mature(self):
        sev = lambda b: b["ai_review"][0]["outcomes"]["semantic_mismatch_evidenced"]["severity"]
        self.assertEqual(sev(self.build([_kw("K1", "BELOW_AVERAGE", 120), _kw("K2", "BELOW_AVERAGE", 90)])), "Warning")
        self.assertEqual(sev(self.build([_kw("K1", "BELOW_AVERAGE", 120)])), "Info")
        self.assertEqual(sev(self.build([_kw("K1", "BELOW_AVERAGE", 900)], lag="30")), "Info")

    def finalize(self, proposal, kws=None):
        body = self.build(kws or [_kw("K1", "BELOW_AVERAGE", 900, clicks=150)], terms=self.TERMS)
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
        dec = self.dir / "d.json"
        dec.write_text(json.dumps([{"id": body["ai_review"][0]["id"], "outcome": "semantic_mismatch_evidenced",
                                    "rationale": "hose queries vs drill copy", "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    GOOD = {"keyword_ids": ["K1"], "quoted_keyword_or_query": "garden hose 30m", "quoted_copy": ["Cordless Drills 18V"],
            "alternative_interpretation": "none plausible", "action": "copy"}

    def test_finalize_accepts_evidenced_mismatch(self):
        code, final = self.finalize(self.GOOD)
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in self.found(final, "semantic_mismatch")], ["Warning"])

    def test_finalize_rejects_unobserved_query(self):
        code, _ = self.finalize(dict(self.GOOD, quoted_keyword_or_query="cheap hose"))
        self.assertEqual(code, 4)

    def test_split_needs_rationale_and_volume(self):
        code, _ = self.finalize(dict(self.GOOD, action="split"))
        self.assertEqual(code, 4)
        code, _ = self.finalize(dict(self.GOOD, action="split", owner_rationale="separate hose landing page"),
                                kws=[_kw("K1", "BELOW_AVERAGE", 900, clicks=20)])
        self.assertEqual(code, 4)
        code, _ = self.finalize(dict(self.GOOD, action="split", owner_rationale="separate hose landing page"))
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
