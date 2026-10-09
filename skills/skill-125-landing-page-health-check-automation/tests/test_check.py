"""test_check.py — Decision-boundary tests for skill-125 URL probe review and bounded exposure.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-125-landing-page-health-check-automation/tests -t skills/skill-125-landing-page-health-check-automation
rules:   Temp folders only; pins failure classes, repetition, region/denial handling, bounds and verify, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_125", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

URL = "https://shop.example/checkout?flow=a"
ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,2026-09-06,fraction,currency,interaction_date,2\n")
ADS = f"id,campaign_id,ad_group_id,status,type,final_url\nA1,C1,G1,ENABLED,RSA,{URL}\nA2,C1,G1,PAUSED,RSA,https://old.example/\n"
KEYWORDS = "id,campaign_id,ad_group_id,final_url,status\n"
HEALTH_HDR = ("test_id,URL,device,checked_at,requested_url,resolved_url,redirect_chain,http_status,tls_valid,tls_error,"
              "load_metric_name,load_value_ms,test_region,user_agent,mobile_task_result,evidence_ref\n")
DAILY = f"account_id,campaign_id,ad_group_id,ad_or_keyword_id,URL,date,clicks,cost,conversions,device\n1,C1,G1,A1,{URL},2026-08-20,1000,1440,40,MOBILE\n"
POLICY = ("monitor_id,URL_scope,test_cadence,critical_customer_task,expected_redirects,performance_limit_ms,owner,"
          "approval_status,recovery_check\n"
          "M1,https://shop.example/*,5 minutes,checkout,none,2500,tech owner,approved for review,passing checkout probe\n")


def probe(tid, hhmm, status, url=URL, region="IT", load="", task="ok", ref=None):
    return (f"{tid},{url},MOBILE,2026-08-20T{hhmm}:00+02:00,{url},{url},,{status},True,,LCP,{load},{region},"
            f"real browser,{task},{ref or 'ref-' + tid}\n")


class Env:
    def __init__(self, files: dict, profile="slug: t\n"):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "export"
        files = {"account.csv": ACCOUNT, "ads.csv": ADS, "keywords.csv": KEYWORDS, **files}
        manifest = ["filename,completeness"]
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            manifest.append(f"{name},complete")
        (self.root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
        self.profile = Path(self.tmp.name) / "profile.yaml"
        self.profile.write_text(profile)
        self.out = Path(self.tmp.name) / "out"

    def body(self):
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.root, self.profile).finish()

    def cli(self, cmd, decisions=None):
        argv = [cmd, "--export", str(self.root), "--profile", str(self.profile), "--out", str(self.out)]
        if decisions is not None:
            p = Path(self.tmp.name) / "d.json"
            p.write_text(json.dumps(decisions))
            argv += ["--decisions", str(p)]
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=argv)


def body(files, **kw):
    env = Env(files, **kw)
    try:
        return env.body()
    finally:
        env.tmp.cleanup()


def sev(b, key):
    return [f["severity"] for f in b["findings"] if f["condition_key"] == key]


class Probes(unittest.TestCase):
    def test_single_probe_is_info_with_upper_bound_only(self):
        b = body({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 503) + probe("P2", "10:05", 200, load=1500),
                  "custom/url_daily.csv": DAILY, "external/url_monitor_policy.csv": POLICY})
        self.assertEqual(sev(b, "single_failure_probe"), ["Info"])
        self.assertFalse([f for f in b["findings"] if f["severity"] != "Info"])
        exp = b["findings"][0]["evidence"]["exposure"]
        self.assertEqual(exp["potentially_affected_exposure_upper_bound"]["cost"], 1440)
        self.assertIsNone(exp["incident_window_cost"])

    def test_interval_buckets_tighten_the_upper_bound(self):
        interval = ("campaign_id,ad_group_id,ad_or_keyword_id,URL,device,interval_start,interval_end,clicks,cost,conversions,"
                    "timezone,source,coverage\n"
                    + "".join(f"C1,G1,A1,{URL},MOBILE,2026-08-20T{h:02d}:00:00+02:00,2026-08-20T{h + 1:02d}:00:00+02:00,"
                              f"10,{c},0,Europe/Rome,ui,complete\n" for h, c in ((9, 50), (10, 60), (11, 70))))
        b = body({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 503) + probe("P2", "10:05", 200),
                  "custom/url_daily.csv": DAILY, "custom/url_interval.csv": interval})
        exp = b["findings"][0]["evidence"]["exposure"]["potentially_affected_exposure_upper_bound"]
        self.assertEqual(exp["cost"], 60)

    def test_repeated_failure_warning_and_evidence_bound_critical(self):
        env = Env({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 503) + probe("P2", "10:05", 502)
                   + probe("P3", "10:10", 200), "external/url_monitor_policy.csv": POLICY})
        self.addCleanup(env.tmp.cleanup)
        self.assertEqual(env.cli("run"), 0)
        res = json.loads((env.out / "result.json").read_text())
        self.assertEqual(sev(res, "repeated_test_failure"), ["Warning"])
        rid = next(r["id"] for r in res["ai_review"] if r["condition_key"] == "repeated_test_failure")
        bad = [{"id": rid, "outcome": "confirmed_task_block", "rationale": "x", "proposal": {"evidence_ref": "other"}}]
        self.assertEqual(env.cli("finalize", bad), 4)
        good = [{**bad[0], "proposal": {"evidence_ref": "ref-P2"}}]
        self.assertEqual(env.cli("finalize", good), 0)
        final = json.loads((env.out / "final.json").read_text())
        self.assertEqual(sev(final, "repeated_test_failure"), ["Critical"])

    def test_inactive_destination_is_not_flagged(self):
        other = "https://old.example/"
        b = body({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 503, url=other) + probe("P2", "10:05", 503, url=other)})
        self.assertEqual(b["findings"], [])

    def test_region_specific_and_denied_runs_stay_info(self):
        b = body({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 503, region="DE")
                  + probe("P2", "10:02", 200, region="IT") + probe("P3", "10:05", 503, region="DE")})
        self.assertEqual(sev(b, "region_specific_failure"), [])  # DE series is interrupted by IT pass → two singles
        b = body({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 503, region="DE")
                  + probe("P3", "10:05", 503, region="DE")
                  + f"P2,{URL},DESKTOP,2026-08-20T10:02:00+02:00,{URL},{URL},,200,True,,LCP,,IT,real browser,ok,r\n"})
        self.assertEqual(sev(b, "region_specific_failure"), ["Info"])
        b = body({"external/url_health.csv": HEALTH_HDR + probe("P1", "10:00", 403) + probe("P2", "10:05", 403)})
        self.assertEqual(sev(b, "access_denied_probe"), ["Info"])
        self.assertEqual([r["condition_key"] for r in b["ai_review"]], ["access_denied_probe"])

    def test_missing_diagnostics_skip(self):
        b = body({"custom/url_daily.csv": DAILY})
        cov = {c["check"]: c["status"] for c in b["coverage"]}
        self.assertEqual(cov["probe_results"], "skipped")
        self.assertEqual(b["findings"], [])


class Performance(unittest.TestCase):
    def test_repeated_violation_warning_single_info_no_policy_skip(self):
        two = HEALTH_HDR + probe("P1", "10:00", 200, load=3000) + probe("P2", "10:05", 200, load=2600)
        self.assertEqual(sev(body({"external/url_health.csv": two, "external/url_monitor_policy.csv": POLICY}),
                             "performance_violation"), ["Warning"])
        one = HEALTH_HDR + probe("P1", "10:00", 200, load=3000) + probe("P2", "10:05", 200, load=2000)
        self.assertEqual(sev(body({"external/url_health.csv": one, "external/url_monitor_policy.csv": POLICY}),
                             "performance_violation"), ["Info"])
        self.assertEqual(sev(body({"external/url_health.csv": two}), "performance_violation"), [])


class OutOfStock(unittest.TestCase):
    def test_markers_are_profile_supplied_and_repeat_is_verified(self):
        health = HEALTH_HDR + probe("P1", "10:00", 200, task="Product sold out") + probe("P2", "10:05", 200)
        self.assertEqual(sev(body({"external/url_health.csv": health}), "out_of_stock_content"), [])
        env = Env({"external/url_health.csv": health}, profile="slug: t\nout_of_stock_markers: [sold out]\n")
        self.addCleanup(env.tmp.cleanup)
        env.cli("run")
        res = json.loads((env.out / "result.json").read_text())
        self.assertEqual(sev(res, "out_of_stock_content"), ["Info"])
        rid = res["ai_review"][0]["id"]
        self.assertEqual(env.cli("finalize", [{"id": rid, "outcome": "repeated_task_failure", "rationale": "x"}]), 4)


if __name__ == "__main__":
    unittest.main()
