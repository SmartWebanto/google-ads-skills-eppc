"""test_check.py — Decision-boundary tests for skill-066 historical QS transitions.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-066-historical-quality-score-trend/tests -t skills/skill-066-historical-quality-score-trend
rules:   Temp folders only; pins severities/coverage at recipe boundaries, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_066", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402  (path inserted by the check module bootstrap)

HIST_COLS = ["account_id", "campaign_id", "ad_group_id", "criterion_id", "date", "keyword_text", "match_type",
             "keyword_status", "historical_quality_score", "historical_expected_ctr", "historical_ad_relevance",
             "historical_landing_page_experience", "impressions", "clicks", "cost", "conversions",
             "conversion_value", "source", "extracted_at"]


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _series(kid, qs_before, qs_after, cost=100, ag="G1", cid="C1", days=20, ar=("AVERAGE", "AVERAGE"),
            start=date(2026, 8, 1), source="native_historical"):
    rows = []
    for i in range(days):
        d = start + timedelta(days=i)
        late = i >= days // 2
        rows.append({"account_id": "1", "campaign_id": cid, "ad_group_id": ag, "criterion_id": kid, "date": d.isoformat(),
                     "keyword_text": f"kw {kid}", "match_type": "EXACT", "keyword_status": "ENABLED",
                     "historical_quality_score": qs_after if late else qs_before,
                     "historical_expected_ctr": "AVERAGE", "historical_ad_relevance": ar[1] if late else ar[0],
                     "historical_landing_page_experience": "AVERAGE", "impressions": 1000, "clicks": 100,
                     "cost": cost, "conversions": 5, "conversion_value": 300, "source": source,
                     "extracted_at": "2026-09-06"})
    return rows


class Base(unittest.TestCase):
    def run_check(self, hist_rows=None, currency="EUR", lag="2", snapshot_rows=None, manifest=True, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        _write(root / "account.csv", ["customer_id", "currency_code", "time_zone", "date_range_start", "date_range_end",
                                      "snapshot_date", "rates_format", "money_unit", "conversion_lag_days"],
               [{"customer_id": "1", "currency_code": currency, "time_zone": "Europe/Rome",
                 "date_range_start": "2026-08-01", "date_range_end": "2026-08-20", "snapshot_date": "2026-09-06",
                 "rates_format": "fraction", "money_unit": "currency", "conversion_lag_days": lag}])
        _write(root / "campaigns.csv", ["id", "name", "channel_type", "target_cpa"],
               [{"id": "C1", "name": "c1", "channel_type": "SEARCH", "target_cpa": "20"}])
        man = []
        if hist_rows is not None:
            _write(root / "custom" / "quality_score_history.csv", HIST_COLS, hist_rows)
            man.append("custom/quality_score_history.csv")
        if snapshot_rows is not None:
            cols = [c if c != "date" else "snapshot_date" for c in HIST_COLS]
            _write(root / "custom" / "quality_score_snapshots.csv", cols, snapshot_rows)
            man.append("custom/quality_score_snapshots.csv")
        if manifest:
            _write(root / "table_manifest.csv", ["filename", "completeness", "truncation"],
                   [{"filename": f, "completeness": "complete", "truncation": "none"} for f in man])
        prof = None
        if profile:
            prof = Path(tmp.name) / "profile.json"
            prof.write_text(profile)
        ctx = cli.run_once(M.SKILL, M.VERSION, M.run, root, prof)
        return ctx.finish()

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def status(body, check):
        return next(c["status"] for c in body["coverage"] if c["check"] == check)


class Transitions(Base):
    def test_material_two_point_decline_and_component_drop_are_warning(self):
        body = self.run_check(_series("K1", 8, 5, cost=100, ar=("ABOVE_AVERAGE", "BELOW_AVERAGE")))
        self.assertEqual([f["severity"] for f in self.found(body, "qs_point_decline")], ["Warning"])
        comp = self.found(body, "component_became_below_average")
        self.assertEqual([(f["severity"], f["entity"]["component"]) for f in comp],
                         [("Warning", "historical_ad_relevance")])
        self.assertEqual(body["counts"]["Critical"], 0)

    def test_one_point_decline_is_not_a_decline_finding(self):
        body = self.run_check(_series("K1", 8, 7, cost=500))
        self.assertEqual(self.found(body, "qs_point_decline"), [])

    def test_low_exposure_decline_is_info(self):
        # 10 comparison days x 4 EUR = 40 < spend_significant max(100, 2 x 20)
        body = self.run_check(_series("K1", 8, 5, cost=4))
        self.assertEqual([f["severity"] for f in self.found(body, "qs_point_decline")], ["Info"])

    def test_threshold_uses_campaign_target_cpa(self):
        # campaigns.target_cpa 20 wins over the profile (threshold 100): 10 x 15 = 150 is material;
        # C2 has only the profile target 80 (threshold 160): the same cost stays Info
        body = self.run_check(_series("K1", 8, 5, cost=15),
                              profile='{"campaign_objectives": {"C1": {"target_cpa": 80}}}')
        self.assertEqual([f["severity"] for f in self.found(body, "qs_point_decline")], ["Warning"])
        body = self.run_check(_series("K1", 8, 5, cost=15, cid="C2"),
                              profile='{"campaign_objectives": {"C2": {"target_cpa": 80}}}')
        self.assertEqual([f["severity"] for f in self.found(body, "qs_point_decline")], ["Info"])

    def test_below_average_to_below_average_is_not_a_transition(self):
        body = self.run_check(_series("K1", 6, 6, ar=("BELOW_AVERAGE", "BELOW_AVERAGE")))
        self.assertEqual(self.found(body, "component_became_below_average"), [])

    def test_perfect_score_loss_is_info(self):
        body = self.run_check(_series("K1", 10, 9, cost=500))
        self.assertEqual([f["severity"] for f in self.found(body, "perfect_qs_lost")], ["Info"])
        self.assertEqual(self.found(body, "qs_point_decline"), [])


class Cohort(Base):
    def test_entrant_is_not_a_decline(self):
        rows = _series("K1", 8, 8) + [r for r in _series("K2", 9, 3) if r["date"] >= "2026-08-11"]
        body = self.run_check(rows)
        self.assertEqual(self.found(body, "qs_point_decline"), [])
        self.assertEqual(len(self.found(body, "cohort_unmatched")), 1)

    def test_no_carry_over_across_null_comparison(self):
        rows = _series("K1", 8, 5)
        for r in rows[10:]:
            r["historical_quality_score"] = ""
        body = self.run_check(rows)
        self.assertEqual(self.found(body, "qs_point_decline"), [])
        self.assertIn("rated_to_null", self.found(body, "cohort_unmatched")[0]["evidence"])

    def test_conflicting_duplicate_is_excluded_and_reported(self):
        rows = _series("K1", 8, 5)
        dup = dict(rows[-1], historical_quality_score=9)
        body = self.run_check(rows + [dup])
        self.assertEqual(len(self.found(body, "history_conflicting_rows")), 1)
        # the conflicting last date is excluded; the earlier comparison dates still show the decline
        self.assertEqual(self.found(body, "qs_point_decline")[0]["evidence"]["comparison_date"], "2026-08-19")

    def test_identical_duplicates_are_deduplicated(self):
        rows = _series("K1", 8, 5, cost=4)
        body = self.run_check(rows + [dict(rows[-1])])
        self.assertEqual(self.found(body, "history_conflicting_rows"), [])
        self.assertEqual(self.found(body, "qs_point_decline")[0]["evidence"]["comparison_window_cost"], 40)


class Evidence(Base):
    def test_missing_history_skips_without_findings(self):
        body = self.run_check(None)
        self.assertEqual(body["findings"], [])
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))

    def test_wrong_source_rows_are_excluded(self):
        body = self.run_check(_series("K1", 8, 5, source="current_snapshot"))
        self.assertEqual(self.found(body, "qs_point_decline"), [])
        self.assertEqual(self.status(body, "history_source"), "partial")

    def test_snapshots_used_only_without_native_history(self):
        snaps = []
        for d, q in (("2026-08-01", 8), ("2026-08-20", 5)):
            r = _series("K1", q, q, days=1)[0]
            r.update(snapshot_date=d, source="current_snapshot", cost=300)
            snaps.append(r)
        body = self.run_check(None, snapshot_rows=snaps)
        f = self.found(body, "qs_point_decline")
        self.assertEqual(len(f), 1)
        self.assertIn("current_snapshot", f[0]["evidence"]["source"])
        body = self.run_check(_series("K1", 8, 8), snapshot_rows=snaps)
        self.assertEqual(self.found(body, "qs_point_decline"), [])

    def test_unresolved_currency_floor_downgrades_to_info_and_partial(self):
        body = self.run_check(_series("K1", 8, 5, cost=1000), currency="USD")
        self.assertEqual([f["severity"] for f in self.found(body, "qs_point_decline")], ["Info"])
        self.assertEqual(self.status(body, "qs_point_transitions"), "partial")

    def test_immature_window_blocks_conversion_comparisons(self):
        body = self.run_check(_series("K1", 8, 5), lag="30")
        self.assertEqual(self.status(body, "business_metric_comparison"), "partial")
        obs = [o for o in body["observations"] if o["check"] == "business_metric_comparison"]
        self.assertNotIn("cvr", obs[0]["data"])

    def test_missing_manifest_marks_source_partial(self):
        body = self.run_check(_series("K1", 8, 5), manifest=False)
        self.assertEqual(self.status(body, "history_source"), "partial")


if __name__ == "__main__":
    unittest.main()
