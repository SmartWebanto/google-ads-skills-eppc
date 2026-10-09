"""test_check.py — skill-166 decision boundaries: URL normalization, view separation, CVR gates, zero-conversion guard, URL health.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-166-landing-page-performance/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes2 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check166", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

SITE = "https://shop.example"
VERIFIED = {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30", "source_ref": "qa-log-7"}}
GOALS = {"10": {"goal_ids": ["g1"]}, "11": {"goal_ids": ["g1"]}, "20": {"goal_ids": ["g1"]}}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def row(cid, path, clicks, conv, cost, view="landing_page", **extra):
    return {"campaign_id": cid, "url_view": view, "url": SITE + path, "clicks": clicks, "cost": cost,
            "conversions": conv, **extra}


def gap_rows(a_clicks=200, b_clicks=800, a_cost=300.0, a_conv=2):
    """URL /a converts 1% vs 5% for the rest of SEARCH (ratio 0.2)."""
    return [row("10", "/a", a_clicks, a_conv, a_cost), row("11", "/b", b_clicks, b_clicks * 0.05, 400.0)]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def build(self, perf=None, checks=None, *, lag=2, profile=None):
        ex = self.root / "export"
        _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-03",
                                     "conversion_lag_days": lag, "money_unit": "currency", "rates_format": "fraction"}])
        _write(ex / "campaigns.csv", [{"id": "10", "channel_type": "SEARCH"}, {"id": "11", "channel_type": "SEARCH"},
                                      {"id": "20", "channel_type": "PERFORMANCE_MAX"}])
        files = ["account.csv", "campaigns.csv"]
        if perf is not None:
            _write(ex / "custom" / "landing_page_performance.csv", perf)
            files.append("custom/landing_page_performance.csv")
        if checks is not None:
            _write(ex / "external" / "landing_page_checks.csv", checks)
            files.append("external/landing_page_checks.csv")
        _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                           for f in files])
        prof = self.root / "profile.json"
        base = {"campaign_objectives": GOALS, "tracking_verified": VERIFIED, "url_ignore_params": ["utm_*", "gclid"]}
        prof.write_text(json.dumps({**base, **(profile or {})}))
        return ex, prof

    def run_check(self, ex, prof) -> dict:
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def finalize(self, ex, prof, decisions) -> int:
        dec = self.root / "decisions.json"
        dec.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                ["finalize", "--export", str(ex), "--profile", str(prof), "--out",
                                 str(self.root / "out"), "--decisions", str(dec)])

    @staticmethod
    def cov(res, cid):
        return next(c for c in res["coverage"] if c["check"] == cid)

    @staticmethod
    def found(res, cond):
        return [f for f in res["findings"] if f["condition_key"] == cond]

    # ---------------------------------------------------------------- normalization / aggregation
    def test_url_normalization_rules(self):
        ign = ["utm_*", "gclid"]
        self.assertEqual(mod._norm_url("HTTPS://Shop.Example:443/Path/?b=2&utm_source=x&a=1&gclid=9#top", ign),
                         "https://shop.example/Path/?a=1&b=2")
        self.assertNotEqual(mod._norm_url("https://shop.example/Path", ign), mod._norm_url("https://shop.example/path", ign))
        self.assertNotEqual(mod._norm_url("https://shop.example/p/", ign), mod._norm_url("https://shop.example/p", ign))
        self.assertEqual(mod._norm_url("https://shop.example", ign), "https://shop.example/")
        self.assertEqual(mod._norm_url("http://shop.example:8080/x?gclidx=1", ign), "http://shop.example:8080/x?gclidx=1")
        self.assertIsNone(mod._norm_url("/relative/path", ign))

    def test_missing_url_report_skips_everything(self):
        res = self.run_check(*self.build())
        self.assertEqual({c["check"]: c["status"] for c in res["coverage"]},
                         {k: "skipped" for k in ("url_aggregation", "url_cvr_vs_type_baseline",
                                                 "zero_conversion_urls", "url_health")})
        self.assertEqual(res["findings"], [])

    def test_views_never_summed_and_variants_merge(self):
        perf = [row("10", "/a?utm_source=x", 10, 1, 5.0), row("10", "/a?utm_source=y", 10, 1, 5.0),
                row("10", "/a", 20, 2, 10.0, view="expanded_landing_page")]
        res = self.run_check(*self.build(perf))
        obs = {o["data"]["url_view"]: o["data"] for o in res["observations"]
               if o["check"] == "url_aggregation" and "url_view" in o["data"]}
        self.assertEqual(obs["landing_page"]["clicks"], 20)
        self.assertEqual(obs["expanded_landing_page"]["clicks"], 20)
        self.assertEqual(obs["landing_page"]["urls"], 1)

    # ---------------------------------------------------------------- CVR vs baseline
    def test_cvr_gap_flagged_as_info_with_review(self):
        res = self.run_check(*self.build(gap_rows()))
        f = self.found(res, "url_cvr_below_type_baseline")
        self.assertEqual([(x["severity"], x["entity"]["url"]) for x in f], [("Info", SITE + "/a")])
        self.assertAlmostEqual(f[0]["evidence"]["cvr_ratio"], 0.2, places=5)
        self.assertTrue(any(r["condition_key"] == "url_cvr_below_type_baseline" for r in res["ai_review"]))

    def test_cvr_sample_gates_on_both_cohorts(self):
        for a, b in ((99, 800), (200, 99)):
            res = self.run_check(*self.build(gap_rows(a_clicks=a, b_clicks=b)))
            self.assertFalse(self.found(res, "url_cvr_below_type_baseline"), (a, b))

    def test_cvr_ratio_boundary_and_spend_material(self):
        res = self.run_check(*self.build(gap_rows(a_conv=5)))  # 2.5% vs 5% → exactly 0.5
        self.assertFalse(self.found(res, "url_cvr_below_type_baseline"))
        res = self.run_check(*self.build(gap_rows(a_cost=199.99)))
        self.assertFalse(self.found(res, "url_cvr_below_type_baseline"))

    def test_cvr_requires_maturity_and_compatible_goals(self):
        res = self.run_check(*self.build(gap_rows(), lag=7))
        self.assertFalse(self.found(res, "url_cvr_below_type_baseline"))
        self.assertEqual(self.cov(res, "url_cvr_vs_type_baseline")["status"], "partial")
        mixed = {"campaign_objectives": {"10": {"goal_ids": ["g1"]}, "11": {"goal_ids": ["g2"]}}}
        res = self.run_check(*self.build(gap_rows(), profile=mixed))
        self.assertFalse(self.found(res, "url_cvr_below_type_baseline"))
        self.assertEqual(self.cov(res, "url_cvr_vs_type_baseline")["status"], "partial")

    def test_page_defect_outcome_needs_evidence_ref(self):
        ex, prof = self.build(gap_rows())
        res = self.run_check(ex, prof)
        rid = next(r["id"] for r in res["ai_review"] if r["condition_key"] == "url_cvr_below_type_baseline")
        self.assertEqual(self.finalize(ex, prof, [{"id": rid, "outcome": "page_defect_evidenced", "rationale": "x"}]), 4)

    # ---------------------------------------------------------------- zero conversion
    def test_zero_conversion_guarded_by_tracking_and_floor(self):
        perf = [row("20", "/z", 40, 0, 60.0), row("20", "/cheap", 40, 0, 49.0), row("20", "/ok", 400, 20, 500.0)]
        res = self.run_check(*self.build(perf))
        urls = [r["entity"]["url"] for r in res["ai_review"] if r["condition_key"] == "zero_conversion_url"]
        self.assertEqual(urls, [SITE + "/z"])
        self.assertEqual([f["severity"] for f in self.found(res, "zero_conversion_url")], ["Info"])
        self.assertFalse(self.found(res, "url_cvr_below_type_baseline"))
        res = self.run_check(*self.build(perf, profile={"tracking_verified": {}}))
        self.assertFalse([r for r in res["ai_review"] if r["condition_key"] == "zero_conversion_url"])
        self.assertFalse(self.found(res, "zero_conversion_url"))
        self.assertEqual(self.cov(res, "zero_conversion_urls")["status"], "partial")

    def test_zero_conversion_blocked_when_immature(self):
        res = self.run_check(*self.build([row("20", "/z", 40, 0, 60.0)], lag=7))
        self.assertFalse(res["ai_review"])
        self.assertEqual(self.cov(res, "zero_conversion_urls")["status"], "partial")

    # ---------------------------------------------------------------- URL health
    def _health(self):
        d = "2026-08-20"
        perf = [row("10", "/down", 50, 1, 80.0, date=d), row("10", "/down", 50, 1, 20.0, date="2026-08-25"),
                row("10", "/flap", 50, 1, 80.0, date=d), row("10", "/once", 50, 1, 80.0, date=d),
                row("10", "/untested", 50, 1, 80.0, date=d)]
        checks = [{"requested_url": SITE + "/down?utm_source=mon", "checked_at": "2026-08-20T08:00:00", "status_code": 500},
                  {"requested_url": SITE + "/down", "checked_at": "2026-08-20T09:00:00", "status_code": 301},
                  {"requested_url": SITE + "/down", "checked_at": "2026-08-21T08:00:00", "status_code": 404},
                  {"requested_url": SITE + "/flap", "checked_at": "2026-08-20T08:00:00", "status_code": 503},
                  {"requested_url": SITE + "/flap", "checked_at": "2026-08-21T08:00:00", "status_code": 200},
                  {"requested_url": SITE + "/once", "checked_at": "2026-08-20T08:00:00", "status_code": 200},
                  {"requested_url": SITE + "/once", "checked_at": "2026-08-21T08:00:00", "status_code": ""}]
        checks[-1]["access_error"] = "timeout"
        return self.build(perf, checks)

    def test_health_classification_and_no_month_spend_attribution(self):
        res = self.run_check(*self._health())
        warn = self.found(res, "url_persistent_failure")
        self.assertEqual([f["entity"]["url"] for f in warn], [SITE + "/down"])
        self.assertEqual(warn[0]["severity"], "Warning")
        self.assertIsNone(warn[0]["evidence"]["affected_cost"])
        self.assertEqual(warn[0]["evidence"]["cost_on_failure_dates_overlap"], {"landing_page": 80.0})
        self.assertEqual([f["entity"]["url"] for f in self.found(res, "url_failure_then_success")], [SITE + "/flap"])
        self.assertEqual([f["entity"]["url"] for f in self.found(res, "url_single_failed_check")], [SITE + "/once"])
        self.assertEqual(self.cov(res, "url_health")["status"], "partial")  # /untested is unassessed

    def test_critical_failure_requires_evidence_ref(self):
        ex, prof = self._health()
        res = self.run_check(ex, prof)
        rid = next(r["id"] for r in res["ai_review"] if r["condition_key"] == "url_persistent_failure")
        base = {"id": rid, "outcome": "material_failure_evidenced", "rationale": "hourly traffic during outage"}
        self.assertEqual(self.finalize(ex, prof, [base]), 4)
        self.assertEqual(self.finalize(ex, prof, [{**base, "proposal": {"evidence_ref": "hourly.csv"}}]), 0)
        final = json.loads((self.root / "out" / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "url_persistent_failure"],
                         ["Critical"])


if __name__ == "__main__":
    unittest.main()
