"""test_check.py — Decision-boundary tests for skill-130 event schedule comparison.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-130-campaign-enable-pause-scheduling/tests -t skills/skill-130-campaign-enable-pause-scheduling
rules:   Temp folders only; pins contradiction branches, intentional pauses, precision, delivery proof and verify.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | tests for this session's check changes
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
_spec = importlib.util.spec_from_file_location("check_130", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,2026-09-06,fraction,currency,interaction_date,2\n")
CAMPS = ("id,name,status,start_date,end_date\n"
         "E1,a,PAUSED,2026-09-10,2026-09-20\nE2,b,PAUSED,2026-09-10,2026-09-25\nE3,c,PAUSED,2026-08-25,2026-09-05\n"
         "E4,d,PAUSED,2026-08-25,2026-09-05\nE5,e,PAUSED,2026-07-01,2026-07-15\nE6,f,PAUSED,2026-09-10,2026-09-20\n"
         "E7,g,PAUSED,2026-09-10,2026-09-20\n")
HDR = ("event_id,campaign_id,name,start_at,end_at,timezone,objective,offer,owner,approval_status,campaign_expected_status,"
       "intentional_pause_reason,replacement_campaign_id,replacement_required,start_stop_precision\n")
PLAN = HDR + "".join([
    "EV1,E1,x,2026-09-10T00:00:00,2026-09-20T23:59:00,Europe/Rome,sales,-20%,mkt,approved,PAUSED,,,false,day\n",
    "EV2,E2,x,2026-09-10T00:00:00,2026-09-20T23:59:00,Europe/Rome,sales,-20%,mkt,approved,PAUSED,,E1,true,day\n",
    "EV3,E3,x,2026-08-25T00:00:00,2026-09-05T23:59:00,Europe/Rome,sales,-20%,mkt,approved,ENABLED,stock shortage,,false,day\n",
    "EV4,E4,x,2026-08-25T00:00:00,2026-09-05T23:59:00,Europe/Rome,sales,-20%,mkt,approved,ENABLED,,,false,day\n",
    "EV5,E5,x,2026-07-01T00:00:00,2026-07-15T23:59:00,Europe/Rome,sales,-20%,mkt,approved,PAUSED,,R1,true,day\n",
    "EV6,E6,x,2026-09-10T09:00:00,2026-09-20T18:00:00,Europe/Rome,sales,-20%,mkt,approved,PAUSED,,,false,hour\n",
    "EV7,E7,x,2026-09-10T09:00:00,2026-09-20T18:00:00,Europe/Rome,sales,-20%,mkt,approved,PAUSED,,,false,hour\n",
    "EV8,E1,x,2026-10-01T00:00:00,2026-10-05T23:59:00,Europe/Rome,sales,-20%,mkt,pending,PAUSED,,,false,day\n",
    "EV9,ZZ,x,2026-09-10T00:00:00,2026-09-20T23:59:00,Europe/Rome,sales,-20%,mkt,approved,PAUSED,,,false,day\n"])
RULES = ("campaign_id,rule_id,snapshot_at,enabled,action,scheduled_at,timezone,recurrence,current_start_date,"
         "current_end_date,last_run_at,last_result,source_screen\n"
         "E7,R7,2026-09-06T08:00:00,true,ENABLE,{at},Europe/Rome,,,,,,rules\n")
CM = "campaign_id,impressions,clicks,cost,conversions\nE5,500,20,30,1\nE3,0,0,0,0\n"


class Env:
    def __init__(self, rule_at="2026-09-10T10:30:00", cm=CM):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "export"
        files = {"account.csv": ACCOUNT, "campaigns.csv": CAMPS, "external/campaign_event_plan.csv": PLAN,
                 "custom/campaign_schedule_rules.csv": RULES.format(at=rule_at), "campaign_metrics.csv": cm}
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


def run(**kw):
    env = Env(**kw)
    try:
        return env.body()
    finally:
        env.tmp.cleanup()


def events(b, key):
    return sorted(f["entity"]["event_id"] for f in b["findings"] if f["condition_key"] == key)


class Schedule(unittest.TestCase):
    def test_contradictions_and_counterexamples(self):
        b = run()
        # EV2 end date later than plan, EV4 paused without reason, EV7 ENABLE rule 90 min off an hour-level plan
        self.assertEqual(events(b, "schedule_contradicts_plan"), ["EV2", "EV4", "EV7"])
        self.assertEqual(events(b, "intentional_in_season_pause"), ["EV3"])
        self.assertEqual(events(b, "hour_precision_unverified"), ["EV6"])
        self.assertEqual(events(b, "event_evidence_missing"), ["EV8", "EV9"])
        self.assertNotIn("EV1", {f["entity"]["event_id"] for f in b["findings"]})

    def test_rule_within_precision_is_consistent(self):
        b = run(rule_at="2026-09-10T09:00:30")
        self.assertNotIn("EV7", events(b, "schedule_contradicts_plan"))

    def test_replacement(self):
        b = run()
        self.assertEqual(events(b, "replacement_not_ready"), ["EV5"])  # R1 missing; EV2's E1 starts 09-10


class Delivery(unittest.TestCase):
    def test_period_after_event_proves_delivery_and_critical_needs_evidence(self):
        env = Env()
        self.addCleanup(env.tmp.cleanup)
        self.assertEqual(env.cli("run"), 0)
        res = json.loads((env.out / "result.json").read_text())
        self.assertEqual(events(res, "served_after_event"), ["EV5"])
        rid = next(r["id"] for r in res["ai_review"] if r["condition_key"] == "served_after_event")
        bad = [{"id": rid, "outcome": "invalid_offer_material", "rationale": "expired promo", "proposal": {}}]
        self.assertEqual(env.cli("finalize", bad), 4)
        for ref in ("ad copy 2026-08-10 shows July promo", "external/campaign_event_plan:EV3:E3"):
            self.assertEqual(env.cli("finalize", [{**bad[0], "proposal": {"evidence_ref": ref}}]), 4, ref)
        good = [{**bad[0], "proposal": {"evidence_ref": "external/campaign_event_plan:EV5:E5"}}]
        self.assertEqual(env.cli("finalize", good), 0)
        final = json.loads((env.out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "served_after_event"], ["Critical"])

    def test_zero_delivery_and_overlapping_period_are_not_findings(self):
        b = run(cm="campaign_id,impressions,clicks,cost,conversions\nE5,0,0,0,0\n")
        self.assertEqual(events(b, "served_after_event"), [])

    def test_missing_plan_skips(self):
        env = Env()
        self.addCleanup(env.tmp.cleanup)
        (env.root / "external" / "campaign_event_plan.csv").unlink()
        b = env.body()
        self.assertEqual({c["status"] for c in b["coverage"]}, {"skipped"})


if __name__ == "__main__":
    unittest.main()
