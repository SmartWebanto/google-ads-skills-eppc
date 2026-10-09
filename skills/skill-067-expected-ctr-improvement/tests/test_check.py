"""test_check.py — Decision-boundary tests for skill-067 expected-CTR triage.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-067-expected-ctr-improvement/tests -t skills/skill-067-expected-ctr-improvement
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
_spec = importlib.util.spec_from_file_location("check_067", _PATH)
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


def _kw(kid, rating, cost, gid="G1", cid="C1", impressions=2000, clicks=150, conv=20):
    return ({"id": kid, "campaign_id": cid, "ad_group_id": gid, "text": f"cordless drill {kid}", "match_type": "PHRASE",
             "status": "ENABLED", "expected_ctr": rating},
            {"keyword_id": kid, "campaign_id": cid, "ad_group_id": gid, "impressions": impressions, "clicks": clicks,
             "cost": cost, "conversions": conv})


AD = {"id": "A1", "campaign_id": "C1", "ad_group_id": "G1", "status": "ENABLED", "approval_status": "APPROVED",
      "headlines": "Pro Drills 18V | Fast Delivery", "descriptions": "Two-year warranty on every tool.",
      "pinned_positions": "", "final_url": "https://x.example/"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, kws, ads=(AD,), lag="2", channel="SEARCH", profile=None, assets=None, spend_high=500):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "rates_format": "fraction",
                                       "money_unit": "currency", "conversion_lag_days": lag}])
        _write(root / "campaigns.csv", [{"id": "C1", "channel_type": channel}])
        _write(root / "keywords.csv", [k for k, _ in kws])
        _write(root / "keyword_metrics.csv", [m for _, m in kws])
        files = ["keywords.csv", "keyword_metrics.csv"]
        if ads:
            _write(root / "ads.csv", list(ads))
            files.append("ads.csv")
        if assets:
            _write(root / "assets.csv", assets)
            files.append("assets.csv")
        _write(root / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                             for f in files])
        prof = dict(profile or {})
        if spend_high is not None:
            prof["parameter_overrides"] = {"spend_high": spend_high}
        self.profile = self.dir / "profile.json"
        self.profile.write_text(json.dumps(prof))
        self.root = root
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, self.profile).finish()

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def status(body, check):
        return next(c["status"] for c in body["coverage"] if c["check"] == check)


class Inventory(Base):
    def test_below_average_at_spend_high_is_warning(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 500)])
        self.assertEqual([f["severity"] for f in self.found(body, "below_average_ectr_high_cost")], ["Warning"])

    def test_below_threshold_or_average_is_not_warning(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 499.99), _kw("K2", "AVERAGE", 5000)])
        self.assertEqual(self.found(body, "below_average_ectr_high_cost"), [])
        self.assertEqual(self.found(body, "below_average_ectr_exposure_unresolved"), [])

    def test_missing_rating_is_unknown_not_low(self):
        body = self.build([_kw("K1", "", 9000)])
        self.assertEqual(self.found(body, "below_average_ectr_high_cost"), [])
        self.assertEqual([f["severity"] for f in self.found(body, "ectr_rating_unavailable")], ["Info"])

    def test_unresolved_spend_high_is_info_and_partial(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 9000)], spend_high=None)
        self.assertEqual(self.found(body, "below_average_ectr_high_cost"), [])
        self.assertEqual([f["severity"] for f in self.found(body, "below_average_ectr_exposure_unresolved")], ["Info"])
        self.assertEqual(self.status(body, "ectr_inventory"), "partial")

    def test_non_search_campaign_is_excluded(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 9000)], channel="DISPLAY")
        self.assertEqual(body["findings"], [])

    def test_missing_metrics_file_skips_everything(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 9000)])
        (self.root / "keyword_metrics.csv").unlink()
        body = cli.run_once(M.SKILL, M.VERSION, M.run, self.root, self.profile).finish()
        self.assertEqual(body["findings"], [])
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))

    def test_ctr_without_segments_is_descriptive_partial(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 10)])
        self.assertEqual(self.status(body, "ctr_context"), "partial")


class Review(Base):
    def outcomes(self, body):
        return {k: v["severity"] for k, v in body["ai_review"][0]["outcomes"].items()}

    def test_copy_gap_warning_needs_material_mature_exposure(self):
        self.assertEqual(self.outcomes(self.build([_kw("K1", "BELOW_AVERAGE", 600)]))["documented_copy_gap"], "Warning")
        self.assertEqual(self.outcomes(self.build([_kw("K1", "BELOW_AVERAGE", 100)]))["documented_copy_gap"], "Info")
        self.assertEqual(self.outcomes(self.build([_kw("K1", "BELOW_AVERAGE", 600)], lag="30"))["documented_copy_gap"],
                         "Info")

    def test_no_eligible_ad_blocks_review_and_reports_pool(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 600)], ads=(dict(AD, approval_status="DISAPPROVED"),))
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(len(self.found(body, "no_eligible_ad_pool")), 1)

    def finalize(self, proposal, outcome="documented_copy_gap"):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 600)])
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args]), 0)
        dec = self.dir / "decisions.json"
        dec.write_text(json.dumps([{"id": body["ai_review"][0]["id"], "outcome": outcome, "rationale": "r",
                                    "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_finalize_rejects_invented_quote(self):
        code, final = self.finalize({"keyword_ids": ["K1"], "quoted_copy": ["Cheapest drills anywhere"],
                                     "hypothesis": "h", "success_metric": "CTR with CPA guardrail"})
        self.assertEqual(code, 4)
        self.assertEqual(self.found(final, "contextual_copy_gap"), [])

    def test_finalize_accepts_verbatim_quote(self):
        code, final = self.finalize({"keyword_ids": ["K1"], "quoted_copy": ["Fast Delivery"],
                                     "hypothesis": "h", "success_metric": "CTR with CPA guardrail"})
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in self.found(final, "contextual_copy_gap")], ["Warning"])

    def test_no_gap_needs_no_proposal(self):
        code, final = self.finalize({}, outcome="copy_relevant_no_gap")
        self.assertEqual(code, 0)
        self.assertEqual(self.found(final, "contextual_copy_gap"), [])


class Assets(Base):
    ASSETS = [{"asset_id": "S1", "type": "SITELINK", "level": "account", "campaign_id": "", "ad_group_id": "",
               "status": "ENABLED", "approval_status": "APPROVED"},
              {"asset_id": "X1", "type": "CALLOUT", "level": "campaign", "campaign_id": "C1", "ad_group_id": "",
               "status": "ENABLED", "approval_status": "DISAPPROVED"}]

    def test_inherited_asset_counts_and_disapproved_is_absent(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 10)], assets=self.ASSETS,
                          profile={"expected_asset_types": ["SITELINK", "CALLOUT"]})
        f = self.found(body, "optional_asset_opportunity")
        self.assertEqual([x["evidence"]["absent_types"] for x in f], [["CALLOUT"]])
        self.assertEqual(f[0]["severity"], "Info")

    def test_without_profile_types_no_absence_claim(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 10)], assets=self.ASSETS)
        self.assertEqual(self.found(body, "optional_asset_opportunity"), [])
        self.assertEqual(self.status(body, "asset_review"), "partial")


if __name__ == "__main__":
    unittest.main()
