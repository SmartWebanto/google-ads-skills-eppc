"""test_check.py — Decision-boundary tests for skill-172 external signal cohorts, gates, rules and proposals.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-172-external-signal-demand-analysis/tests -t skills/skill-172-external-signal-demand-analysis
rules:   Synthetic temp exports only; no network, no clock. Tests pin bucketing, both-sided sample gates,
maturity/tracking gates, exclusion of duplicates/conflicts, rule contradiction and proposal verification.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes5 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill172_check", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402  (path inserted by the check module bootstrap)
from adsrun.context import Context  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,"
           "rates_format,money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,{snap},fraction,currency,interaction_date,2\n")
CAMPAIGNS = "id,name,status,channel_type,bidding_strategy_type,target_roas\n1,M,ENABLED,SEARCH,MANUAL_CPC,\n2,T,ENABLED,SEARCH,TARGET_CPA,\n"
PROFILE = ("campaign_objectives:\n  1: {goal_ids: [g1]}\n  2: {goal_ids: [g1]}\n"
           "tracking_verified:\n  g1: {status: verified, verified_from: 2000-01-01, verified_through: 2026-08-30, source_ref: QA1}\n"
           "external_signals:\n  temperature: {bounds: [15, 25], labels: [cold, mild, hot], baseline: mild, "
           "min_relative_difference: 0.2}\n{extra}")
DAYS = [date(2026, 8, 1) + timedelta(days=i) for i in range(30)]


def _temp(d):  # 10 cold, 10 mild, 10 hot days
    i = DAYS.index(d)
    return 10 if i < 10 else 20 if i < 20 else 30


def signals(rows=None):
    out = ["date,hour,region,signal_name,value,source"]
    out += rows if rows is not None else [f"{d},,north,temperature,{_temp(d)},provider" for d in DAYS]
    return "\n".join(out) + "\n"


def daily(extra=()):
    out = ["campaign_id,date,region,impressions,clicks,cost,conversions,conversion_value"]
    for cid in ("1", "2"):
        for d in DAYS:
            hot = _temp(d) == 30
            clicks, conv = (80, 4) if hot else (100, 10)
            out.append(f"{cid},{d},north,1000,{clicks},{clicks},{conv},{conv * 30}")
    return "\n".join(list(out) + list(extra)) + "\n"


class Base(unittest.TestCase):
    def build(self, files=None, extra_profile="", snap="2026-09-05", drop=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        data = {"account.csv": ACCOUNT.format(snap=snap), "campaigns.csv": CAMPAIGNS,
                "external/external_signals.csv": signals(), "custom/campaign_geo_daily.csv": daily()}
        data.update(files or {})
        for name, text in data.items():
            if name in drop:
                continue
            p = root / "export" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (root / "profile.yaml").write_text(PROFILE.replace("{extra}", extra_profile))
        self.root = root
        return root

    def ctx(self):
        c = Context(M.SKILL, M.VERSION, self.root / "export", self.root / "profile.yaml")
        M.run(c)
        return c

    @staticmethod
    def cov(ctx):
        return {c.id: c.coverage() for c in ctx.result.checks}

    @staticmethod
    def found(ctx, key="signal_bucket_difference"):
        return sorted((f.entity["campaign_id"], f.entity["bucket"]) for f in ctx.result.findings if f.condition_key == key)


class Buckets(unittest.TestCase):
    def test_bounds_are_lower_inclusive(self):
        labels = ["cold", "mild", "hot"]
        self.assertEqual(M.bucket(14.9, [15, 25], labels), "cold")
        self.assertEqual(M.bucket(15, [15, 25], labels), "mild")
        self.assertEqual(M.bucket(25, [15, 25], labels), "hot")


class Alignment(Base):
    def test_qualified_difference_only_where_it_exists(self):
        self.build()
        ctx = self.ctx()
        self.assertEqual(self.found(ctx), [("1", "hot"), ("2", "hot")])   # cold equals baseline → no finding
        f = next(f for f in ctx.result.findings if f.entity["campaign_id"] == "1")
        self.assertEqual(f.severity, "Info")
        self.assertEqual(f.evidence["decisive_metric"], "cpa")
        self.assertAlmostEqual(f.evidence["relative_difference"], 1.0)
        self.assertEqual(f.evidence["direction"], "unfavorable")
        self.assertEqual(f.evidence["bucket_cohort"]["periods"], 10)

    def test_both_cohorts_must_pass_sample_gates(self):
        # mild passes (1000 clicks / 100 conv); hot fails (800 clicks / 40 conv)
        self.build(extra_profile="parameter_overrides: {min_clicks: 900, min_conversions: 60}\n")
        ctx = self.ctx()
        self.assertEqual(self.found(ctx), [])
        self.assertEqual(self.cov(ctx)["daily_alignment"]["status"], "partial")  # no manifest

    def test_undeclared_tolerance_is_descriptive_only(self):
        self.build(files={})
        (self.root / "profile.yaml").write_text(PROFILE.replace(", min_relative_difference: 0.2", "").replace("{extra}", ""))
        ctx = self.ctx()
        self.assertEqual(self.found(ctx), [])
        self.assertIn("profile.external_signals.temperature.min_relative_difference",
                      self.cov(ctx)["bucket_definitions"]["missing"])
        self.assertTrue([o for o in ctx.result.observations if o["check"] == "daily_alignment"])

    def test_immature_window_blocks_conversion_comparisons(self):
        self.build(snap="2026-08-31")
        ctx = self.ctx()
        self.assertEqual(self.found(ctx), [])
        obs = [o["data"] for o in ctx.result.observations if o["check"] == "daily_alignment" and "comparison" in o["data"]]
        self.assertTrue(obs)
        self.assertIsNotNone(obs[0]["comparison"]["ctr"]["baseline"])
        self.assertIsNotNone(obs[0]["comparison"]["cpa"]["gated_out"])

    def test_unverified_tracking_blocks_conversion_comparisons(self):
        self.build()
        (self.root / "profile.yaml").write_text(PROFILE.replace(
            "tracking_verified:\n  g1: {status: verified, verified_from: 2000-01-01, verified_through: 2026-08-30, source_ref: QA1}\n", "")
            .replace("{extra}", ""))
        ctx = self.ctx()
        self.assertEqual(self.found(ctx), [])
        self.assertEqual(self.cov(ctx)["daily_alignment"]["status"], "partial")

    def test_duplicates_conflicts_and_sourceless_rows_excluded(self):
        rows = [f"{d},,north,temperature,{_temp(d)},provider" for d in DAYS]
        rows.append(f"{DAYS[25]},,north,temperature,5,other")           # conflicting value → day excluded
        rows.append(f"{DAYS[0]},,south,temperature,30,")                # no source → excluded
        dup = [f"1,{DAYS[26]},north,1000,80,80,4,120"]                  # duplicate key → both copies excluded
        self.build(files={"external/external_signals.csv": signals(rows), "custom/campaign_geo_daily.csv": daily(dup)})
        ctx = self.ctx()
        notes = " ".join(self.cov(ctx)["signal_series"]["notes"] + self.cov(ctx)["daily_alignment"]["notes"])
        self.assertIn("conflicting", notes)
        f = next(f for f in ctx.result.findings if f.entity["campaign_id"] == "1")
        self.assertEqual(f.evidence["bucket_cohort"]["periods"], 8)     # 10 hot days − conflict − duplicate

    def test_missing_evidence_skips_with_exact_inputs(self):
        self.build(drop=("custom/campaign_geo_daily.csv",))
        cov = self.cov(self.ctx())
        self.assertEqual(cov["daily_alignment"]["status"], "skipped")
        self.assertIn("custom/campaign_geo_daily (file)", cov["daily_alignment"]["missing"])
        self.assertEqual(cov["signal_rule_consistency"]["status"], "skipped")

    def test_invalid_bucket_definition_not_analysed(self):
        self.build()
        (self.root / "profile.yaml").write_text(PROFILE.replace("labels: [cold, mild, hot]", "labels: [cold, hot]")
                                                .replace("{extra}", ""))
        ctx = self.ctx()
        cov = self.cov(ctx)
        self.assertEqual(cov["bucket_definitions"]["status"], "partial")
        self.assertEqual(cov["daily_alignment"]["status"], "skipped")
        self.assertEqual(self.found(ctx), [])

    def test_hourly_signal_never_averaged_into_days(self):
        rows = [f"{d},{h},north,temperature,30,provider" for d in DAYS for h in (20, 21)]
        self.build(files={"external/external_signals.csv": signals(rows)})
        ctx = self.ctx()
        self.assertEqual(self.found(ctx), [])
        self.assertIn("without a signal value", " ".join(self.cov(ctx)["daily_alignment"]["notes"]))


class Rules(Base):
    def test_rule_contradiction_needs_opposite_direction(self):
        rules = ("rule_id,signal_name,bucket,campaign_id,action,modifier,status\n"
                 "R1,temperature,hot,1,bid_modifier,0.3,ENABLED\nR2,temperature,hot,2,bid_modifier,-0.2,ENABLED\n"
                 "R3,temperature,cold,1,bid_modifier,0.3,ENABLED\nR4,temperature,hot,2,bid_modifier,0.5,PAUSED\n")
        self.build(files={"external/signal_rules.csv": rules})
        ctx = self.ctx()
        items = [x for x in ctx.result.reviews if x.condition_key == "signal_rule_contradicted"]
        self.assertEqual([x.entity["rule_id"] for x in items], ["R1"])
        self.assertEqual(items[0].outcomes["rule_contradicted"]["severity"], "Warning")


class Verify(Base):
    def setUp(self):
        self.build()
        self.c = self.ctx()

    def problems(self, campaign, **proposal):
        item = next(x for x in self.c.result.reviews if x.condition_key == "signal_bucket_difference"
                    and x.entity["campaign_id"] == campaign)
        base = {"campaign_id": campaign, "signal": "temperature", "bucket": "hot", "primary_metric": "cpa",
                "duration_days": 28, "stop_rule": "stop at 28 days", "approval_owner": "client"}
        return M.verify(self.c, item, {"outcome": "test_worth_proposing", "proposal": {**base, **proposal}})

    def test_bid_modifier_direction_range_and_strategy(self):
        self.assertEqual(self.problems("1", type="schedule_rule", action="bid_modifier", modifier=-0.2), [])
        self.assertTrue(self.problems("1", type="schedule_rule", action="bid_modifier", modifier=0.2))
        self.assertTrue(self.problems("1", type="schedule_rule", action="bid_modifier", modifier=-0.95))
        self.assertTrue(self.problems("2", type="schedule_rule", action="bid_modifier", modifier=-0.2))
        self.assertTrue(self.problems("1", type="schedule_rule", action="ad_schedule"))   # daily grain

    def test_experiment_requirements(self):
        self.assertEqual(self.problems("2", type="experiment", allocation="50/50 campaign experiment"), [])
        self.assertTrue(self.problems("2", type="experiment"))
        self.assertTrue(self.problems("2", type="experiment", allocation="50/50", stop_rule=""))
        self.assertTrue(self.problems("2", type="experiment", allocation="50/50", bucket="cold"))
        self.assertTrue(self.problems("2", type="experiment", allocation="50/50", expected_uplift=0.3))


class Finalize(Base):
    def _cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=list(args))

    def test_finalize_replaces_provisional_and_rejects_invalid(self):
        root = self.build()
        out = root / "out"
        common = ["--export", str(root / "export"), "--profile", str(root / "profile.yaml"), "--out", str(out)]
        self.assertEqual(self._cli("run", *common), 0)
        body = json.loads((out / "result.json").read_text())
        rid = next(x["id"] for x in body["ai_review"] if x["entity"]["campaign_id"] == "1")
        dec = {"id": rid, "outcome": "confounded_or_not_actionable", "rationale": "promo week overlapped hot days"}
        (root / "d.json").write_text(json.dumps([dec]))
        self.assertEqual(self._cli("finalize", *common, "--decisions", str(root / "d.json")), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["entity"]["campaign_id"] for f in final["findings"]], ["2"])
        dec = {"id": rid, "outcome": "test_worth_proposing", "rationale": "x",
               "proposal": {"type": "schedule_rule", "action": "bid_modifier", "modifier": 0.4}}
        (root / "d.json").write_text(json.dumps([dec]))
        self.assertEqual(self._cli("finalize", *common, "--decisions", str(root / "d.json")), 4)


if __name__ == "__main__":
    unittest.main()
