"""test_check.py — skill-048 boundaries: control semantics, tCPA target effect, precedence, age, segment gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-048-bid-adjustment-layer-review/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check048", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

CTRL = [
    {"channel": "SEARCH", "subtype": "", "strategy": "MANUAL_CPC", "dimension": "DEVICE", "level": "CAMPAIGN",
     "effective_date": "2026-01-01", "control_effect": "CPC", "combination_rule": "", "official_source_url": "u",
     "checked_at": "2026-08-01", "intended_setting": "mobile -30%", "rationale": "mobile UX", "owner": "ppc"},
    {"channel": "SEARCH", "subtype": "", "strategy": "MANUAL_CPC", "dimension": "DEVICE", "level": "AD_GROUP",
     "effective_date": "2026-01-01", "control_effect": "CPC", "combination_rule": "ad group overrides campaign",
     "official_source_url": "u", "checked_at": "2026-08-01", "intended_setting": "", "rationale": "", "owner": "ppc"},
    {"channel": "SEARCH", "subtype": "", "strategy": "TARGET_CPA", "dimension": "DEVICE", "level": "CAMPAIGN",
     "effective_date": "2026-01-01", "control_effect": "CPA_target", "combination_rule": "", "official_source_url": "u",
     "checked_at": "2026-08-01", "intended_setting": "", "rationale": "", "owner": "ppc"},
    {"channel": "SEARCH", "subtype": "", "strategy": "MAXIMIZE_CONVERSION_VALUE", "dimension": "DEVICE",
     "level": "CAMPAIGN", "effective_date": "2026-01-01", "control_effect": "ignored", "combination_rule": "",
     "official_source_url": "u", "checked_at": "2026-08-01", "intended_setting": "", "rationale": "", "owner": "ppc"},
]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build(root: Path, *, controls=True, snapshot="2026-09-06", history=None, segments=None, rule=None,
          adjustments=None):
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-30", "snapshot_date": snapshot,
                                 "conversion_lag_days": 2, "money_unit": "currency"}])
    _write(ex / "campaigns.csv", [
        {"id": "C1", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "MANUAL_CPC", "target_cpa": ""},
        {"id": "C2", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_CPA", "target_cpa": 40},
        {"id": "C3", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "MAXIMIZE_CONVERSION_VALUE",
         "target_cpa": ""}])
    _write(ex / "ad_groups.csv", [{"id": "G1", "campaign_id": "C1"}])
    _write(ex / "bid_adjustments.csv", adjustments or [
        {"campaign_id": "C1", "ad_group_id": "", "dimension": "DEVICE", "criterion_id": "MOBILE", "modifier": 0.7, "excluded": ""},
        {"campaign_id": "C1", "ad_group_id": "", "dimension": "DEVICE", "criterion_id": "TABLET", "modifier": 0, "excluded": ""},
        {"campaign_id": "C1", "ad_group_id": "G1", "dimension": "DEVICE", "criterion_id": "MOBILE", "modifier": 0.9, "excluded": ""},
        {"campaign_id": "C2", "ad_group_id": "", "dimension": "DEVICE", "criterion_id": "MOBILE", "modifier": "+20%", "excluded": ""},
        {"campaign_id": "C3", "ad_group_id": "", "dimension": "DEVICE", "criterion_id": "TABLET", "modifier": 1.3, "excluded": ""}])
    if controls:
        rows = [dict(r) for r in CTRL]
        if rule is not None:
            rows[1]["combination_rule"] = rule
        _write(ex / "external" / "modifier_controls.csv", rows)
    if history:
        _write(ex / "custom" / "modifier_history.csv", history)
    if segments:
        _write(ex / "custom" / "modifier_segment_daily.csv", segments)
    p = root / "profile.json"
    p.write_text("{}")
    return ex, p


def seg_rows(cid, dim, per_segment: dict, days=10):
    out = []
    for i in range(days):
        d = (date(2026, 8, 1) + timedelta(days=i)).isoformat()
        for sid, (clicks, cost, conv) in per_segment.items():
            out.append({"campaign_id": cid, "ad_group_id": "", "dimension": dim, "segment_id": sid, "date": d,
                        "impressions": clicks * 10 / days, "clicks": clicks / days, "cost": cost / days,
                        "conversions": conv / days, "value": 0, "goal_cohort": "purchase", "source_ref": "s"})
    return out


def run(ex, prof) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_tcpa_device_modifier_changes_target_not_cpc(self):
        body = run(*build(self.root))
        obs = [o["data"] for o in body["observations"] if o["data"].get("control_effect") == "CPA_TARGET"]
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0]["effective_segment_target_cpa"], 48.0)

    def test_ignored_control_is_info_only(self):
        body = run(*build(self.root))
        f = [x for x in body["findings"] if x["condition_key"] == "ignored_or_unsupported_setting"]
        self.assertEqual([(x["entity"]["campaign_id"], x["severity"]) for x in f], [("C3", "Info")])
        self.assertFalse(any(x["severity"] in ("Warning", "Critical") for x in body["findings"]))

    def test_without_control_matrix_no_semantics_or_recommendation(self):
        body = run(*build(self.root, controls=False))
        self.assertEqual(cov(body)["control_semantics"], "skipped")
        self.assertEqual(cov(body)["exclusion_intent"], "skipped")
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["ai_review"], [])

    def test_exclusion_goes_to_intent_review(self):
        body = run(*build(self.root))
        items = [r for r in body["ai_review"] if r["condition_key"] == "setting_contradicts_intent"]
        crit = sorted(r["entity"]["criterion_id"] for r in items if r["entity"]["campaign_id"] == "C1")
        self.assertIn("TABLET", crit)
        self.assertTrue(all(r["outcomes"]["intentional"]["severity"] is None for r in items))

    def test_override_rule_resolves_layers_without_conflict(self):
        body = run(*build(self.root))
        obs = [o["data"] for o in body["observations"] if o["check"] == "layer_precedence"]
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0]["effective_multiplier"], 0.9)
        body = run(*build(self.root, rule="multiply"))
        obs = [o["data"] for o in body["observations"] if o["check"] == "layer_precedence"]
        self.assertAlmostEqual(obs[0]["effective_multiplier"], 0.63)
        body = run(*build(self.root, rule="see docs"))
        self.assertEqual(cov(body)["layer_precedence"], "partial")

    def test_setting_age_boundary_and_unknown_history(self):
        hist = [{"campaign_id": "C1", "ad_group_id": "", "dimension": "DEVICE", "criterion_id": "MOBILE",
                 "effective_from": "2026-01-01", "changed_at": "2026-05-01", "new_modifier": 0.7},
                {"campaign_id": "C2", "ad_group_id": "", "dimension": "DEVICE", "criterion_id": "MOBILE",
                 "effective_from": "2026-08-01", "changed_at": "2026-08-01", "new_modifier": 1.2}]
        body = run(*build(self.root, history=hist))
        old = [f["entity"]["campaign_id"] for f in body["findings"] if f["condition_key"] == "old_setting_review_cue"]
        self.assertEqual(old, ["C1"])
        self.assertEqual(cov(body)["setting_age"], "partial")

    def test_segment_review_requires_samples_on_both_sides(self):
        segs = seg_rows("C1", "DEVICE", {"MOBILE": (400, 1200, 20), "DESKTOP": (600, 900, 30)})
        body = run(*build(self.root, segments=segs))
        items = [r for r in body["ai_review"] if r["condition_key"] == "segment_supports_control_review"]
        self.assertEqual(len(items), 1)
        mob = [s for s in items[0]["evidence"]["segments"] if s["segment_id"] == "MOBILE"][0]
        self.assertAlmostEqual(mob["cpa_index"], 60 / 30)
        segs = seg_rows("C1", "DEVICE", {"MOBILE": (40, 1200, 5), "DESKTOP": (60, 900, 10)})
        body = run(*build(self.root, segments=segs))
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "segment_supports_control_review"], [])

    def test_immature_segments_are_descriptive_only(self):
        segs = seg_rows("C1", "DEVICE", {"MOBILE": (400, 1200, 20), "DESKTOP": (600, 900, 30)})
        body = run(*build(self.root, segments=segs, snapshot="2026-08-31"))
        self.assertEqual(cov(body)["segment_outcomes"], "partial")
        self.assertEqual([r for r in body["ai_review"] if r["check"] == "segment_outcomes"], [])

    def test_overlapping_audiences_need_period_totals(self):
        segs = seg_rows("C1", "AUDIENCE", {"inmarket-1": (400, 1200, 20), "inmarket-2": (600, 900, 30)})
        body = run(*build(self.root, segments=segs))
        self.assertEqual(cov(body)["segment_outcomes"], "partial")
        self.assertFalse(any(o["check"] == "segment_outcomes" and "AUDIENCE" in o["text"] for o in body["observations"]))

    def test_finalize_requires_evidenced_segment(self):
        segs = seg_rows("C1", "DEVICE", {"MOBILE": (400, 1200, 20), "DESKTOP": (600, 900, 30)})
        ex, prof = build(self.root, segments=segs)
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                         ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        body = json.loads((out / "result.json").read_text())
        item = [r for r in body["ai_review"] if r["condition_key"] == "segment_supports_control_review"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "bounded_review_supported", "rationale": "r",
                                    "proposal": {"segment_id": "MOBILE", "modifier": 0.5}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "bounded_review_supported", "rationale": "r",
                                    "proposal": {"segment_id": "MOBILE"}}]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertIn("Warning", [f["severity"] for f in final["findings"]
                                  if f["condition_key"] == "segment_supports_control_review"])


if __name__ == "__main__":
    unittest.main()
