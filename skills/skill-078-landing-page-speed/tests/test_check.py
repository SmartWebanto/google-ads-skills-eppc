"""test_check.py — skill-078 decision boundaries: exposure priority, CWV bands, lab repeatability, testing requests.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-078-landing-page-speed/tests -t skills/skill-078-landing-page-speed
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check078", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check078"] = mod
_spec.loader.exec_module(mod)

URL_A = "https://shop.example/a"
URL_B = "https://shop.example/b"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def _base_tables() -> dict:
    return {
        "account.csv": [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                         "date_range_end": "2026-08-30", "snapshot_date": "2026-09-05", "conversion_lag_days": 2,
                         "money_unit": "currency", "rates_format": "fraction"}],
        "ads.csv": [{"id": "a1", "campaign_id": "c10", "ad_group_id": "g1", "status": "ENABLED", "final_url": URL_A}],
        "keywords.csv": [
            {"id": "k1", "campaign_id": "c10", "ad_group_id": "g1", "status": "ENABLED", "final_url": URL_B,
             "landing_page_experience": "BELOW_AVERAGE"},
            {"id": "k2", "campaign_id": "c10", "ad_group_id": "g1", "status": "ENABLED", "final_url": "",
             "landing_page_experience": "AVERAGE"}],
        "keyword_metrics.csv": [{"keyword_id": "k1", "clicks": 10, "cost": 30.0},
                                {"keyword_id": "k2", "clicks": 50, "cost": 120.0}],
    }


def _dmap(live="ACTIVE", url=URL_A, **extra) -> list[dict]:
    return [{"campaign_id": "c10", "entity_type": "ad", "entity_id": "a1", "url_id": "u1", "final_url_sanitized": url,
             "association_status": live, "mobile_url_sanitized": "", "keyword_override": "false",
             "expansion_status": "none", **extra}]


def _psr(url_id="u1", kind="field", scope="page", pct="75", status="ok", device="mobile", run="r1",
         lcp=2000, inp=100, cls=0.05, **extra) -> dict:
    return {"url_id": url_id, "device_class": device, "source_kind": kind, "run_id": run,
            "page_or_origin_scope": scope, "percentile": pct, "lcp_ms": lcp, "inp_ms": inp, "cls": cls,
            "field_window_start": "2026-08-01", "field_window_end": "2026-08-28", "measurement_status": status,
            "network_profile": "4g", "cpu_profile": "4x", "cache_state": "cold", "sample_size": 900,
            "source_reference": "crux-2026-08", **extra}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_check(self, extra=None, drop=(), profile=None, complete=True) -> dict:
        tables = _base_tables()
        tables.update(extra or {})
        ex = self.root / "export"
        for name, rows in tables.items():
            if name not in drop:
                _write(ex / name, rows)
        comp = "complete for declared rows and columns" if complete else "partial sample"
        _write(ex / "table_manifest.csv", [{"filename": n, "completeness": "complete" if n.count("/") == 0 else comp,
                                            "truncation": "none"} for n in tables if n not in drop])
        prof = self.root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()

    @staticmethod
    def cov(body) -> dict:
        return {c["check"]: c for c in body["coverage"]}

    @staticmethod
    def found(body, key) -> list[dict]:
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def obs(body, check) -> dict:
        return [o for o in body["observations"] if o["check"] == check][0]["data"]

    # -- step 2: export-only priority list
    def test_export_only_run_ranks_urls_and_marks_speed_unassessed(self):
        body = self.run_check()
        dest = self.obs(body, "traffic_priority")["destinations"]
        self.assertEqual([d["url"] for d in dest], [URL_A, URL_B])  # inherited k2 cost 120 > override k1 cost 30
        self.assertEqual(dest[0]["rank_cost"], 120)
        self.assertTrue(all(d["speed_status"] == "unassessed" for d in dest))
        cov = self.cov(body)
        self.assertEqual(cov["field_cwv"]["status"], "skipped")
        self.assertIn("external/page_speed_results (file)", cov["field_cwv"]["missing"])
        self.assertEqual(cov["testing_requests"]["status"], "partial")
        self.assertNotIn("Warning", {f["severity"] for f in body["findings"]})
        self.assertEqual(self.found(body, "untested_destination"), [])

    def test_below_average_rating_is_info_testing_priority_only(self):
        body = self.run_check()
        f = self.found(body, "below_average_lp_testing_priority")
        self.assertEqual([(x["severity"], x["entity"]["url"], x["evidence"]["keyword_ids"]) for x in f],
                         [("Info", URL_B, ["k1"])])

    def test_keyword_and_ad_exposure_are_not_summed(self):
        extra = {"ad_metrics.csv": [{"ad_id": "a1", "clicks": 60, "cost": 150.0}]}
        body = self.run_check(extra)
        a = [d for d in self.obs(body, "traffic_priority")["destinations"] if d["url"] == URL_A][0]
        self.assertEqual(a["entity_exposure_by_type"]["ad"]["cost"], 150)
        self.assertEqual(a["entity_exposure_by_type"]["keyword_inherited"]["cost"], 120)
        self.assertEqual(a["rank_cost"], 150)  # max single type, never 270

    def test_ambiguous_ad_group_destination_is_unallocated_info(self):
        t = _base_tables()
        extra = {"ads.csv": t["ads.csv"] + [{"id": "a2", "campaign_id": "c10", "ad_group_id": "g1",
                                              "status": "ENABLED", "final_url": URL_B}]}
        body = self.run_check(extra)
        f = self.found(body, "unallocated_entity_exposure")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["evidence"]["keyword_ids"], ["k2"])
        self.assertEqual(f[0]["evidence"]["unallocated_entity_cost"]["keyword"], 120)
        a = [d for d in self.obs(body, "traffic_priority")["destinations"] if d["url"] == URL_A][0]
        self.assertEqual(a["inherited_keyword_ids"], [])

    def test_duplicate_metric_rows_are_excluded_not_double_counted(self):
        extra = {"keyword_metrics.csv": [{"keyword_id": "k1", "clicks": 10, "cost": 30.0},
                                         {"keyword_id": "k1", "clicks": 10, "cost": 30.0},
                                         {"keyword_id": "k2", "clicks": 50, "cost": 120.0}]}
        body = self.run_check(extra)
        b = [d for d in self.obs(body, "traffic_priority")["destinations"] if d["url"] == URL_B][0]
        self.assertEqual(b["entity_exposure_by_type"]["keyword_override"]["cost"], 0)
        self.assertEqual(self.cov(body)["traffic_priority"]["status"], "partial")

    def test_observed_url_traffic_preferred_over_entity_exposure(self):
        extra = {"external/destination_map.csv": _dmap(url=URL_B, observed_url_clicks=5, observed_url_cost=500,
                                                       attribution_method="url_report")}
        body = self.run_check(extra)
        dest = self.obs(body, "traffic_priority")["destinations"]
        self.assertEqual(dest[0]["url"], URL_B)
        self.assertEqual(dest[0]["basis"], "observed URL traffic")

    # -- step 4: field CWV boundaries
    def test_field_lcp_just_above_good_is_warning_and_boundary_is_not(self):
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(lcp=2501)]})
        f = self.found(body, "field_cwv_exceeds_boundary")
        self.assertEqual([(x["severity"], x["evidence"]["bands"]["lcp_ms"]) for x in f],
                         [("Warning", "needs_improvement")])
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(lcp=2500, inp=200, cls=0.1)]})
        self.assertEqual(self.found(body, "field_cwv_exceeds_boundary"), [])

    def test_poor_band_above_poor_boundary(self):
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(inp=501, cls=0.26)]})
        bands = self.found(body, "field_cwv_exceeds_boundary")[0]["evidence"]["bands"]
        self.assertEqual((bands["inp_ms"], bands["cls"], bands["lcp_ms"]), ("poor", "poor", "good"))

    def test_null_metric_is_unknown_not_zero_or_defect(self):
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(inp="")]})
        self.assertEqual(self.found(body, "field_cwv_exceeds_boundary"), [])
        self.assertIsNone(self.obs(body, "field_cwv")["within_good"][0]["bands"]["inp_ms"])

    def test_inactive_destination_gets_no_warning(self):
        body = self.run_check({"external/destination_map.csv": _dmap(live="REMOVED"),
                               "external/page_speed_results.csv": [_psr(lcp=5000)]})
        self.assertEqual(self.found(body, "field_cwv_exceeds_boundary"), [])
        self.assertEqual(len(self.obs(body, "field_cwv")["exceeding_but_not_active_destination"]), 1)

    def test_origin_scope_or_non_p75_is_not_evaluated(self):
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(scope="origin", lcp=5000)]})
        self.assertEqual(self.found(body, "field_cwv_exceeds_boundary"), [])
        self.assertEqual(len(self.found(body, "origin_only_evidence")), 1)
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(pct="90", lcp=5000)]})
        self.assertEqual(self.found(body, "field_cwv_exceeds_boundary"), [])
        self.assertEqual(self.cov(body)["field_cwv"]["status"], "partial")

    def test_field_check_without_destination_map_is_skipped(self):
        body = self.run_check({"external/page_speed_results.csv": [_psr(lcp=5000)]})
        self.assertEqual(self.cov(body)["field_cwv"]["status"], "skipped")
        self.assertIn("external/destination_map (file)", self.cov(body)["field_cwv"]["missing"])

    # -- step 5: lab repeatability
    def test_two_comparable_lab_runs_over_poor_lcp_warn(self):
        rows = [_psr(kind="lab", run="r1", lcp=4100), _psr(kind="lab", run="r2", lcp=4300)]
        body = self.run_check({"external/destination_map.csv": _dmap(), "external/page_speed_results.csv": rows})
        self.assertEqual([f["severity"] for f in self.found(body, "repeatable_lab_bottleneck")], ["Warning"])
        reqs = self.obs(body, "engineering_assignment")["requests"]
        self.assertEqual([r["source"] for r in reqs], ["lab"])

    def test_single_or_variable_lab_runs_do_not_warn(self):
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(kind="lab", lcp=6000)]})
        self.assertEqual(self.found(body, "repeatable_lab_bottleneck"), [])
        self.assertEqual(self.cov(body)["lab_repeatability"]["status"], "partial")
        rows = [_psr(kind="lab", run="r1", lcp=4100), _psr(kind="lab", run="r2", lcp=3900)]
        body = self.run_check({"external/destination_map.csv": _dmap(), "external/page_speed_results.csv": rows})
        self.assertEqual(self.found(body, "repeatable_lab_bottleneck"), [])

    def test_runs_under_different_cache_states_are_not_comparable(self):
        rows = [_psr(kind="lab", run="r1", lcp=4100), _psr(kind="lab", run="r2", lcp=4300, cache_state="warm")]
        body = self.run_check({"external/destination_map.csv": _dmap(), "external/page_speed_results.csv": rows})
        self.assertEqual(self.found(body, "repeatable_lab_bottleneck"), [])

    def test_ttfb_judged_only_against_profile_threshold(self):
        rows = [_psr(kind="lab", run="r1", lcp=1000, ttfb_ms=1500), _psr(kind="lab", run="r2", lcp=1000, ttfb_ms=1600)]
        extra = {"external/destination_map.csv": _dmap(), "external/page_speed_results.csv": rows}
        self.assertEqual(self.found(self.run_check(extra), "repeatable_lab_bottleneck"), [])
        body = self.run_check(extra, profile={"lab_thresholds": {"ttfb_ms": 800}})
        f = self.found(body, "repeatable_lab_bottleneck")
        self.assertEqual(list(f[0]["evidence"]["metrics"]), ["ttfb_ms"])

    # -- step 7: render failures
    def test_failed_render_is_info_routed_to_079_never_critical(self):
        body = self.run_check({"external/destination_map.csv": _dmap(),
                               "external/page_speed_results.csv": [_psr(kind="lab", status="not rendered", lcp="")]})
        self.assertEqual([f["severity"] for f in self.found(body, "functional_issue_route_079")], ["Info"])
        self.assertEqual(body["counts"]["Critical"], 0)

    # -- step 8: testing requests
    def test_untested_active_destination_needs_complete_measurement_inventory(self):
        dm = _dmap() + [{**_dmap()[0], "entity_id": "a9", "url_id": "u2", "final_url_sanitized": URL_B}]
        extra = {"external/destination_map.csv": dm, "external/page_speed_results.csv": [_psr()]}
        body = self.run_check(extra)
        self.assertEqual([f["entity"]["url_id"] for f in self.found(body, "untested_destination")], ["u2"])
        body = self.run_check(extra, complete=False)
        self.assertEqual(self.found(body, "untested_destination"), [])
        self.assertEqual(self.cov(body)["testing_requests"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
