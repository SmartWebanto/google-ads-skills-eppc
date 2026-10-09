"""test_check.py — Decision-boundary tests for skill-124 anomaly screening and alert proposals.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-124-performance-anomaly-alert-configuration/tests -t skills/skill-124-performance-anomaly-alert-configuration
rules:   Temp folders only; pins screen branches, policy floor, maturity, exclusions and verify, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_124", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

END = date(2026, 8, 30)  # Sunday
START = END - timedelta(days=62)
POLICY = ("policy_id,entity_scope,metric,relative_threshold,absolute_threshold,minimum_baseline_periods,cadence,cooldown,"
          "recipient_role,owner,approved_spend_cap,confirmation_required\n"
          "P1,*,cost,0.3,{floor},8,daily,24h,account lead,ops,,true\n")
CONTEXT_HDR = "entity_id,event_id,start_at,end_at,event_type,affected_metrics,incident_confirmed,evidence_ref\n"


def daily(overrides=None, ctr_decline=False) -> str:
    out = ["campaign_id,date,impressions,clicks,cost,conversions,conversion_value"]
    d = START
    while d <= END:
        w = (d - START).days // 7
        rows = {"C1": {"impressions": 1000 + 10 * (w % 3), "clicks": 50 + w % 2, "cost": 50 + 2 * (w % 3),
                       "conversions": 5 + w % 2, "conversion_value": 100},
                "C2": {"impressions": 500, "clicks": 20, "cost": 30, "conversions": 2, "conversion_value": 40}}
        if ctr_decline and w >= 5:
            rows["C1"]["clicks"] = 60 - 5 * (w - 5)  # weekly CTR strictly falls over the last four weeks
        for cid, vals in rows.items():
            vals.update((overrides or {}).get((cid, d), {}))
            out.append(f"{cid},{d}," + ",".join(str(vals[k]) for k in ("impressions", "clicks", "cost", "conversions",
                                                                         "conversion_value")))
        d += timedelta(days=1)
    return "\n".join(out) + "\n"


class Env:
    def __init__(self, files: dict, snapshot=END + timedelta(days=3), lag="2"):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "export"
        acct = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
                "money_unit,conversion_date_basis,conversion_lag_days\n"
                f"1,A,EUR,Europe/Rome,{START},{END},{snapshot},fraction,currency,interaction_date,{lag}\n")
        files = {"account.csv": acct, "campaigns.csv": "id,name,status\nC1,a,ENABLED\nC2,b,ENABLED\n", **files}
        manifest = ["filename,completeness"]
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            manifest.append(f"{name},complete")
        (self.root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
        self.profile = Path(self.tmp.name) / "profile.yaml"
        self.profile.write_text("slug: t\n")
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


def hits(b, key, cid, metric=None):
    return [f["severity"] for f in b["findings"] if f["condition_key"] == key and f["entity"].get("campaign_id") == cid
            and metric in (None, f["entity"].get("metric"))]


class Screen(unittest.TestCase):
    spike = {("C1", END): {"cost": 150}}

    def test_both_screens_plus_policy_floor_is_warning(self):
        b = body({"custom/anomaly_daily.csv": daily(self.spike), "external/alert_policy.csv": POLICY.format(floor=20)})
        self.assertEqual(hits(b, "anomaly_screen_met", "C1", "cost"), ["Warning"])

    def test_without_policy_or_below_floor_stays_info(self):
        b = body({"custom/anomaly_daily.csv": daily(self.spike)})
        self.assertEqual(hits(b, "anomaly_screen_met", "C1", "cost"), ["Info"])
        b = body({"custom/anomaly_daily.csv": daily(self.spike), "external/alert_policy.csv": POLICY.format(floor=1000)})
        self.assertEqual(hits(b, "anomaly_screen_met", "C1", "cost"), ["Info"])

    def test_sd_hit_without_relative_change_is_quiet(self):
        b = body({"custom/anomaly_daily.csv": daily({("C1", END): {"cost": 60}}),
                  "external/alert_policy.csv": POLICY.format(floor=5)})
        self.assertEqual(hits(b, "anomaly_screen_met", "C1", "cost"), [])

    def test_degenerate_baseline_is_info_only(self):
        b = body({"custom/anomaly_daily.csv": daily({("C2", END): {"cost": 60}}),
                  "external/alert_policy.csv": POLICY.format(floor=20)})
        self.assertEqual(hits(b, "degenerate_baseline_deviation", "C2", "cost"), ["Info"])
        self.assertEqual(hits(b, "anomaly_screen_met", "C2", "cost"), [])

    def test_documented_events_shrink_baseline_to_sparse(self):
        ctx_rows = CONTEXT_HDR + "".join(f"C1,E{k},{END - timedelta(days=7 * k)},{END - timedelta(days=7 * k)},promotion,cost,false,\n"
                                         for k in range(1, 6))
        b = body({"custom/anomaly_daily.csv": daily(self.spike), "external/alert_policy.csv": POLICY.format(floor=20),
                  "custom/anomaly_context.csv": ctx_rows})
        self.assertEqual(hits(b, "sparse_baseline_deviation", "C1", "cost"), ["Info"])
        self.assertEqual(hits(b, "anomaly_screen_met", "C1", "cost"), [])

    def test_immature_conversion_day_not_screened(self):
        spike = {("C1", END): {"conversions": 40}, ("C1", END - timedelta(days=1)): {"conversions": 40}}
        b = body({"custom/anomaly_daily.csv": daily(spike)}, snapshot=END + timedelta(days=1))
        dates = sorted(f["entity"]["date"] for f in b["findings"]
                       if f["entity"].get("metric") == "conversions" and f["entity"].get("campaign_id") == "C1")
        self.assertEqual(dates, [str(END - timedelta(days=1))])

    def test_missing_daily_skips_everything(self):
        b = body({})
        self.assertEqual({c["status"] for c in b["coverage"]}, {"skipped"})
        self.assertEqual(b["findings"], [])


class ZeroDelivery(unittest.TestCase):
    def test_review_and_evidence_bound_critical(self):
        ctx_rows = CONTEXT_HDR + f"C2,E9,{END},{END},outage,impressions,true,INC-1\n"
        env = Env({"custom/anomaly_daily.csv": daily({("C2", END): {"impressions": 0, "clicks": 0, "cost": 0}}),
                   "custom/anomaly_context.csv": ctx_rows})
        self.addCleanup(env.tmp.cleanup)
        self.assertEqual(env.cli("run"), 0)
        res = json.loads((env.out / "result.json").read_text())
        rid = next(r["id"] for r in res["ai_review"] if r["condition_key"] == "zero_delivery")
        wrong = [{"id": rid, "outcome": "confirmed_delivery_failure", "rationale": "x", "proposal": {"evidence_ref": "INC-2"}}]
        self.assertEqual(env.cli("finalize", wrong), 4)
        right = [{**wrong[0], "proposal": {"evidence_ref": "INC-1"}}]
        self.assertEqual(env.cli("finalize", right), 0)
        final = json.loads((env.out / "final.json").read_text())
        self.assertEqual(hits(final, "zero_delivery", "C2"), ["Critical"])


class WeeklyDecline(unittest.TestCase):
    def test_three_consecutive_weekly_ctr_drops(self):
        b = body({"custom/anomaly_daily.csv": daily(ctr_decline=True)})
        self.assertEqual(hits(b, "declining_ctr_trend", "C1"), ["Info"])
        self.assertEqual(hits(b, "declining_ctr_trend", "C2"), [])

    def test_mixed_grain_rows_are_dropped(self):
        text = daily().replace("campaign_id,date", "campaign_id,ad_group_id,date", 1)
        lines = text.splitlines()
        lines = [lines[0]] + [l.replace(",", ",G1,", 1) if l.startswith("C1") else l.replace(",", ",,", 1) for l in lines[1:]]
        b = body({"custom/anomaly_daily.csv": "\n".join(lines) + "\n"})
        base = next(c for c in b["coverage"] if c["check"] == "baseline_window")
        self.assertEqual(base["status"], "partial")
        self.assertFalse([f for f in b["findings"] if f["entity"].get("campaign_id") == "C2"])


if __name__ == "__main__":
    unittest.main()
