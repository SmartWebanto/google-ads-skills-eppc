"""test_check.py — skill-064 QS distribution decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-064-quality-score-distribution-analysis/tests
rules:   stdlib only; temp folders; no network; asserts decisions, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial tests
"""
from __future__ import annotations

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
_spec = importlib.util.spec_from_file_location("check_064", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-28", "snapshot_date": "2026-09-05", "rates_format": "fraction",
           "money_unit": "currency", "conversion_lag_days": "2"}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(test, tables: dict, profile: dict | None = None, incomplete=()) -> dict:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    exp = root / "export"
    manifest = []
    for key, rows in tables.items():
        _write(exp / f"{key}.csv", rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "partial" if key in incomplete else "complete"})
    _write(exp / "table_manifest.csv", manifest)
    prof = root / "profile.json"
    prof.write_text(json.dumps(profile or {}))
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(M.SKILL, M.VERSION, M.run, None,
                        ["run", "--export", str(exp), "--profile", str(prof), "--out", str(root / "out")])
    test.assertEqual(code, 0)
    return json.loads((root / "out" / "result.json").read_text())


def kw(i, qs, cost, status="ENABLED", comp="AVERAGE", impressions=500, conv=0):
    return ({"id": i, "campaign_id": "10", "ad_group_id": "20", "text": f"kw {i}", "match_type": "EXACT",
             "status": status, "quality_score": qs, "expected_ctr": comp, "ad_relevance": "AVERAGE",
             "landing_page_experience": "AVERAGE"},
            {"keyword_id": i, "campaign_id": "10", "ad_group_id": "20", "impressions": impressions, "clicks": 20,
             "cost": cost, "conversions": conv, "conversion_value": 0})


def tables(*kws, account=None, metrics=True):
    t = {"account": [account or ACCOUNT],
         "campaigns": [{"id": "10", "status": "ENABLED", "channel_type": "SEARCH"},
                       {"id": "11", "status": "ENABLED", "channel_type": "SHOPPING"}],
         "ad_groups": [{"id": "20", "campaign_id": "10", "status": "ENABLED"}],
         "keywords": [k for k, _ in kws]}
    if metrics:
        t["keyword_metrics"] = [m for _, m in kws if m is not None]
    return t


def findings(body, key=None):
    return [f for f in body["findings"] if key is None or f["condition_key"] == key]


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class QSDistributionTests(unittest.TestCase):
    def test_low_qs_cost_boundaries(self):
        body = run(self, tables(kw("1", 2, 150), kw("2", 2, 99.99), kw("3", 5, 250), kw("4", 5, 199), kw("5", 8, 900)))
        warned = {f["entity"]["keyword_id"]: f["condition_key"] for f in body["findings"] if f["severity"] == "Warning"}
        self.assertEqual(warned, {"1": "low_qs_1_3_cost", "3": "low_qs_4_5_cost"})
        share = findings(body, "low_qs_share")[0]
        self.assertEqual(share["evidence"]["keyword_ids"], ["2"])

    def test_target_cpa_raises_threshold_per_campaign(self):
        prof = {"campaign_objectives": {"10": {"target_cpa": 80}}}
        body = run(self, tables(kw("1", 2, 150)), prof)  # spend_significant = max(100, 160)
        self.assertEqual(findings(body, "low_qs_1_3_cost"), [])

    def test_na_score_is_never_zero_or_warning(self):
        body = run(self, tables(kw("1", "", 900), kw("2", "--", 10), kw("3", 7, 10)))
        self.assertEqual([f for f in body["findings"] if f["severity"] == "Warning"], [])
        na = findings(body, "qs_unavailable")[0]
        self.assertEqual(na["calculation"], {"numerator": 2, "denominator": 3})
        dist = next(o for o in body["observations"] if o["check"] == "qs_buckets")["data"]
        self.assertEqual(dist["denominator_all"], 3)
        self.assertEqual(dist["denominator_rated"], 1)

    def test_paused_and_non_search_keywords_excluded(self):
        t = tables(kw("1", 1, 900, status="PAUSED"))
        t["keywords"].append({"id": "9", "campaign_id": "11", "ad_group_id": "20", "status": "ENABLED", "quality_score": 1,
                              "expected_ctr": "", "ad_relevance": "", "landing_page_experience": ""})
        body = run(self, t)
        self.assertEqual(findings(body), [])

    def test_weak_component_warning_without_qs_duplicate(self):
        body = run(self, tables(kw("1", 6, 120, comp="BELOW_AVERAGE"), kw("2", 2, 150, comp="BELOW_AVERAGE"),
                                kw("3", 6, 90, comp="BELOW_AVERAGE")))
        by_kw = {}
        for f in body["findings"]:
            if f["severity"] == "Warning":
                by_kw.setdefault(f["entity"]["keyword_id"], []).append(f["condition_key"])
        self.assertEqual(by_kw, {"1": ["weak_component_cost"], "2": ["low_qs_1_3_cost"]})

    def test_missing_metrics_skips_exposure_never_passes(self):
        body = run(self, tables(kw("1", 2, 900), metrics=False))
        c = cov(body)
        self.assertEqual(c["spend_exposure"], "skipped")
        self.assertEqual(c["low_qs_priority"], "skipped")
        self.assertEqual([f for f in body["findings"] if f["severity"] == "Warning"], [])

    def test_unmatched_keyword_cost_unknown_without_complete_manifest(self):
        t = tables(kw("1", 2, 900), (kw("2", 2, 0)[0], None))
        body = run(self, t, incomplete=("keyword_metrics",))
        self.assertEqual(cov(body)["spend_exposure"], "partial")
        obs = next(o for o in body["observations"] if o["text"].startswith("Spend of non-eligible"))
        self.assertEqual(obs["data"]["unknown_cost_keywords"], ["2"])

    def test_duplicate_metric_rows_excluded_not_summed(self):
        t = tables(kw("1", 2, 60))
        t["keyword_metrics"].append(dict(t["keyword_metrics"][0]))
        body = run(self, t)
        self.assertEqual(findings(body, "low_qs_1_3_cost"), [])
        self.assertEqual(cov(body)["spend_exposure"], "partial")

    def test_non_eur_without_floors_unresolved(self):
        acct = dict(ACCOUNT, currency_code="USD")
        body = run(self, tables(kw("1", 2, 5000), account=acct))
        self.assertEqual(findings(body, "low_qs_1_3_cost"), [])
        self.assertEqual(cov(body)["low_qs_priority"], "partial")

    def test_business_outcomes_need_maturity(self):
        acct = dict(ACCOUNT, conversion_lag_days="")
        body = run(self, tables(kw("1", 2, 150, conv=20), account=acct))
        self.assertEqual(cov(body)["business_outcomes"], "partial")
        body = run(self, tables(kw("1", 2, 150, conv=20)))
        obs = [o for o in body["observations"] if o["check"] == "business_outcomes" and o["data"].get("keyword_id")]
        self.assertEqual(obs[0]["data"]["cpa"], 7.5)

    def test_alert_candidate_needs_min_impressions(self):
        body = run(self, tables(kw("1", 3, 10, impressions=1000), kw("2", 3, 10, impressions=999)))
        self.assertEqual([f["entity"]["keyword_id"] for f in findings(body, "low_qs_alert_candidate")], ["1"])

    def test_history_decline_routed_not_duplicated(self):
        t = tables(kw("1", 4, 10))
        t["custom/quality_score_history"] = [
            {"campaign_id": "10", "ad_group_id": "20", "criterion_id": "1", "date": "2026-08-01", "historical_quality_score": 7},
            {"campaign_id": "10", "ad_group_id": "20", "criterion_id": "1", "date": "2026-08-28", "historical_quality_score": 4}]
        body = run(self, t)
        obs = next(o for o in body["observations"] if o["check"] == "alert_plan")
        self.assertEqual(obs["data"]["declines"][0]["keyword_id"], "1")
        self.assertEqual(findings(body), [])


if __name__ == "__main__":
    unittest.main()
