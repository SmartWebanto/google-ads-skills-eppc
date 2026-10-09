"""test_check.py — skill-093 decision boundaries for PMax video inventory, specs, requirements and review.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-093-pmax-video-asset-review/tests
rules:   stdlib only; temp folders; never touches the network or the selftest oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
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

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR.parent / "_resources" / "runtime"))
from adsrun import cli  # noqa: E402

_spec = importlib.util.spec_from_file_location("skill093_check", SKILL_DIR / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

ASSOC_H = ["campaign_id", "asset_group_id", "asset_id", "field_type", "association_status", "asset_type",
           "approval_status", "performance_label"]
DETAIL_H = ["asset_id", "youtube_video_id", "width_px", "height_px", "duration_seconds", "language",
            "creation_provenance", "provenance_reference", "content_review", "rights_brand_approval",
            "reviewed_at", "source_reference"]
REQ_H = ["campaign_subtype", "intended_format", "rule_id", "supported", "required_or_recommended", "min_width_px",
         "min_height_px", "aspect_ratio", "min_duration_seconds", "max_duration_seconds", "requirement_conditions",
         "source_url", "checked_at"]
METRIC_H = ["campaign_id", "asset_group_id", "asset_id", "date", "format", "impressions", "video_views",
            "completed_views", "rate_denominator_definition", "clicks", "cost", "conversions"]


def _account(snapshot="2026-09-06"):
    return (["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
             "conversion_lag_days"], [["1", "EUR", "2026-08-01", "2026-08-30", snapshot, "2"]])


def _base():
    """Planted defects plus valid counterexamples in one PMax campaign."""
    return {
        "account": _account(),
        "campaigns": (["id", "name", "status", "channel_type", "channel_subtype", "languages"],
                      [["10", "PMax", "ENABLED", "PERFORMANCE_MAX", "standard", "it"],
                       ["20", "Search", "ENABLED", "SEARCH", "", "it"]]),
        "custom/pmax_groups": (["campaign_id", "asset_group_id", "name", "status", "primary_status",
                                "platform_diagnostic", "ad_strength", "final_urls", "theme"],
                               [["10", "G1", "Tools", "ENABLED", "ELIGIBLE", "", "GOOD", "https://x/t", "hand tools"],
                                ["10", "G2", "Ladders", "ENABLED", "ELIGIBLE", "", "AVERAGE", "https://x/l", "ladders"],
                                ["10", "G3", "Old", "PAUSED", "PAUSED", "", "", "https://x/o", "old"],
                                ["20", "S1", "NotPmax", "ENABLED", "", "", "", "", ""]]),
        "custom/pmax_group_assets": (ASSOC_H, [
            ["10", "G1", "V1", "YOUTUBE_VIDEO", "ENABLED", "YOUTUBE_VIDEO", "APPROVED", "LOW"],
            ["10", "G1", "V2", "YOUTUBE_VIDEO", "ENABLED", "YOUTUBE_VIDEO", "DISAPPROVED", ""],
            ["10", "G1", "V3", "YOUTUBE_VIDEO", "ENABLED", "YOUTUBE_VIDEO", "APPROVED", "GOOD"],
            ["10", "G1", "V4", "YOUTUBE_VIDEO", "ENABLED", "YOUTUBE_VIDEO", "APPROVED", "BEST"],
            ["10", "G1", "V5", "YOUTUBE_VIDEO", "ENABLED", "YOUTUBE_VIDEO", "APPROVED", ""],
            ["10", "G1", "H1", "HEADLINE", "ENABLED", "TEXT", "APPROVED", "LOW"],
            ["10", "G2", "H2", "HEADLINE", "ENABLED", "TEXT", "APPROVED", ""],
            ["20", "S1", "V9", "YOUTUBE_VIDEO", "ENABLED", "YOUTUBE_VIDEO", "DISAPPROVED", ""]]),
        "external/pmax_video_details": (DETAIL_H, [
            ["V1", "y1", "1920", "1080", "30", "it", "advertiser", "lib#1", "shows hand tools", "approved", "2026-09-01", "s"],
            ["V2", "y2", "1920", "1080", "30", "it", "advertiser", "lib#2", "", "approved", "2026-09-01", "s"],
            ["V3", "y3", "1920", "1080", "90", "it", "advertiser", "lib#3", "ladder promo", "expired", "2026-09-01", "s"],
            ["V4", "y4", "1080", "1080", "20", "it", "automated", "", "", "approved", "2026-09-01", "s"],
            ["V5", "y5", "854", "480", "30", "it", "advertiser", "lib#5", "", "approved", "2026-09-01", "s"]]),
        "external/pmax_video_requirements": (REQ_H, [
            ["any", "landscape", "R1", "true", "required", "1280", "", "16:9", "", "", "", "https://doc", "2026-09-01"],
            ["", "", "R2", "true", "recommended", "", "", "", "", "60", "", "https://doc", "2026-09-01"],
            ["any", "portrait", "R3", "true", "required", "", "1080", "9:16", "", "", "", "https://doc", "2026-09-01"],
            ["feed_only", "", "R4", "true", "required", "5000", "", "", "", "", "", "https://doc", "2026-09-01"]]),
        "assets": (["asset_id", "type"], [["V1", "YOUTUBE_VIDEO"], ["V7", "YOUTUBE_VIDEO"], ["H1", "TEXT"]]),
    }


def _write(root: Path, tables: dict, complete=True) -> None:
    manifest = []
    for key, (head, rows) in tables.items():
        p = root / f"{key}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
        manifest.append([f"{key}.csv", "complete for declared rows"])
    if complete:
        with (root / "table_manifest.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "completeness"])
            w.writerows(manifest)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_check(self, tables, complete=True) -> dict:
        exp = self.root / "export"
        _write(exp, tables, complete)
        return cli.run_once(mod.SKILL, mod.VERSION, mod.run, exp, None).finish()

    @staticmethod
    def cov(body, cid):
        return next(c for c in body["coverage"] if c["check"] == cid)

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]


class PlantedDefects(Base):
    def setUp(self):
        super().setUp()
        self.body = self.run_check(_base())

    def test_required_rule_failure_only_for_undersized_video(self):
        f = self.found(self.body, "requirement_failure")
        self.assertEqual([(x["entity"]["asset_id"], x["entity"]["rule_id"], x["severity"]) for x in f],
                         [("V5", "R1", "Warning")])
        # 854x480 is 16:9 within pixel-rounding tolerance: only the width limit fails
        self.assertEqual([v["limit"] for v in f[0]["evidence"]["violations"]], ["min_width_px"])

    def test_missing_portrait_and_other_subtype_rules_never_fire(self):
        rules = {f["entity"]["rule_id"] for f in self.body["findings"] if "rule_id" in f["entity"]}
        self.assertNotIn("R3", rules)
        self.assertNotIn("R4", rules)  # campaign subtype 'standard' != feed_only

    def test_recommended_duration_gap_is_info(self):
        f = self.found(self.body, "recommended_spec_gap")
        self.assertEqual([(x["entity"]["asset_id"], x["severity"]) for x in f], [("V3", "Info")])

    def test_rights_mismatch_only_for_denied_active_video(self):
        f = self.found(self.body, "rights_mismatch")
        self.assertEqual([(x["entity"]["asset_id"], x["severity"]) for x in f], [("V3", "Warning")])

    def test_unknown_provenance_without_reference(self):
        self.assertEqual([x["entity"]["asset_id"] for x in self.found(self.body, "unknown_provenance")], ["V4"])

    def test_disapproved_video_is_provisional_info_with_review(self):
        f = self.found(self.body, "video_disapproval_diagnostic")
        self.assertEqual([(x["entity"]["asset_id"], x["severity"]) for x in f], [("V2", "Info")])
        r = [x for x in self.body["ai_review"] if x["condition_key"] == "video_disapproval_diagnostic"]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["provisional_finding"], f[0]["id"])
        self.assertEqual(r[0]["outcomes"]["blocks_required_serving"]["severity"], "Critical")

    def test_non_pmax_rows_are_excluded(self):
        ids = {f["entity"].get("asset_id") for f in self.body["findings"]}
        self.assertNotIn("V9", ids)

    def test_low_label_only_on_video(self):
        f = self.found(self.body, "low_performance_label")
        self.assertEqual([x["entity"]["asset_id"] for x in f], ["V1"])

    def test_content_review_without_provenance(self):
        r = [x for x in self.body["ai_review"] if x["condition_key"] == "video_content_mismatch"]
        self.assertEqual(sorted(x["entity"]["asset_id"] for x in r), ["V1", "V3"])
        self.assertNotIn("creation_provenance", r[0]["evidence"])
        self.assertEqual(r[0]["outcomes"]["mismatch"]["severity"], "Warning")

    def test_proposal_batch_only_enabled_group_without_eligible_video(self):
        r = [x for x in self.body["ai_review"] if x["condition_key"] == "video_coverage_need"]
        self.assertEqual(len(r), 1)
        self.assertEqual([g["asset_group_id"] for g in r[0]["evidence"]["groups"]], ["G2"])

    def test_no_critical_without_review(self):
        self.assertEqual(self.body["counts"]["Critical"], 0)

    def test_metrics_missing_is_partial_not_pass(self):
        c = self.cov(self.body, "video_metrics")
        self.assertEqual(c["status"], "partial")
        self.assertIn("custom/pmax_video_metrics (file)", c["missing"])

    def test_inventory_proves_zero_video_group_but_not_account_linkage(self):
        self.assertEqual(self.cov(self.body, "video_inventory")["status"], "completed")
        obs = {o["data"].get("asset_group_id"): o for o in self.body["observations"]
               if o["check"] == "video_inventory" and "asset_group_id" in o["data"]}
        self.assertEqual(obs["G2"]["data"]["videos"], [])
        self.assertTrue(obs["G2"]["data"]["inventory_complete"])
        unlinked = [o["data"]["unlinked"] for o in self.body["observations"] if "unlinked" in o["data"]]
        self.assertEqual(unlinked, [["V7"]])


class MissingEvidence(Base):
    def test_no_manifest_blocks_absence_claims(self):
        body = self.run_check(_base(), complete=False)
        self.assertEqual(self.cov(body, "video_proposal")["status"], "partial")
        self.assertFalse([x for x in body["ai_review"] if x["condition_key"] == "video_coverage_need"])
        self.assertEqual(self.cov(body, "video_inventory")["status"], "partial")

    def test_without_details_dependent_checks_skip(self):
        t = _base()
        del t["external/pmax_video_details"]
        body = self.run_check(t)
        self.assertEqual(self.cov(body, "media_specs")["status"], "skipped")
        self.assertIn("external/pmax_video_details (file)", self.cov(body, "media_specs")["missing"])
        self.assertEqual(self.cov(body, "content_consistency")["status"], "skipped")
        req = self.cov(body, "requirements")
        self.assertEqual(req["status"], "partial")
        self.assertIn("external/pmax_video_details (file)", req["missing"])
        for key in ("requirement_failure", "rights_mismatch", "unknown_provenance"):
            self.assertFalse(self.found(body, key))

    def test_without_associations_everything_skips(self):
        t = _base()
        del t["custom/pmax_group_assets"]
        body = self.run_check(t)
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"]))
        self.assertEqual(body["findings"], [])

    def test_zero_dimensions_give_no_ratio_or_failure(self):
        t = _base()
        t["external/pmax_video_details"][1][4] = ["V5", "y5", "0", "0", "30", "it", "advertiser", "lib#5", "",
                                                  "approved", "2026-09-01", "s"]
        body = self.run_check(t)
        self.assertFalse(self.found(body, "requirement_failure"))
        self.assertEqual(self.cov(body, "requirements")["status"], "partial")


class Metrics(Base):
    def _run(self, rows, snapshot="2026-09-06"):
        t = _base()
        t["account"] = _account(snapshot)
        t["custom/pmax_video_metrics"] = (METRIC_H, rows)
        return self.run_check(t)

    def _obs(self, body, text):
        return [o for o in body["observations"] if o["check"] == "video_metrics" and text in o["text"]]

    def test_completion_needs_definition_and_nonzero_views(self):
        body = self._run([
            ["10", "G1", "V1", "2026-08-10", "in_stream", "2000", "0", "0", "views", "", "", ""],
            ["10", "G1", "V3", "2026-08-10", "in_stream", "2000", "100", "40", "", "", "", ""]])
        by = {o["data"]["asset_id"]: o["data"] for o in self._obs(body, "metrics")}
        self.assertIsNone(by["V1"]["completion_rate"])  # zero denominator
        self.assertIsNone(by["V3"]["completion_rate"])  # no denominator definition

    def test_comparison_requires_maturity_and_sample_on_both_sides(self):
        rows = [["10", "G1", "V1", "2026-08-10", "in_stream", "1500", "100", "50", "views", "", "", ""],
                ["10", "G1", "V3", "2026-08-10", "in_stream", "1200", "100", "20", "views", "", "", ""]]
        mature = self._run(rows)
        comp = self._obs(mature, "like-format")
        self.assertEqual([r["asset_id"] for r in comp[0]["data"]["ranking"]], ["V1", "V3"])
        immature = self._run(rows, snapshot="2026-08-31")
        self.assertFalse(self._obs(immature, "like-format"))
        self.assertEqual(self.cov(immature, "video_metrics")["status"], "partial")
        small = [r[:] for r in rows]
        small[1][5] = "999"
        self.assertFalse(self._obs(self._run(small), "like-format"))
        self.assertFalse([f for f in mature["findings"] if f["check"] == "video_metrics"
                          and f["condition_key"] != "low_performance_label"])


class Finalize(Base):
    def _cli(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, list(args))

    def _decide(self, decisions) -> tuple[int, dict]:
        exp, out = self.root / "export", self.root / "out"
        if not exp.exists():
            _write(exp, _base())
            self.assertEqual(self._cli("run", "--export", str(exp), "--out", str(out)), 0)
        stored = json.loads((out / "result.json").read_text())
        ids = {x["condition_key"]: x["id"] for x in stored["ai_review"]}
        dec = [{**d, "id": ids[d["id"]]} for d in decisions]
        p = self.root / "decisions.json"
        p.write_text(json.dumps(dec))
        code = self._cli("finalize", "--export", str(exp), "--out", str(out), "--decisions", str(p))
        return code, json.loads((out / "final.json").read_text())

    def test_critical_requires_evidence_ref(self):
        code, _ = self._decide([{"id": "video_disapproval_diagnostic", "outcome": "blocks_required_serving",
                                 "rationale": "diagnostic says blocked", "proposal": {}}])
        self.assertEqual(code, 4)
        code, final = self._decide([{"id": "video_disapproval_diagnostic", "outcome": "blocks_required_serving",
                                     "rationale": "diagnostic says blocked", "proposal": {"evidence_ref": "diag#7"}}])
        self.assertEqual(code, 0)
        crit = [f for f in final["findings"] if f["severity"] == "Critical"]
        self.assertEqual([f["entity"]["asset_id"] for f in crit], ["V2"])
        self.assertFalse([f for f in final["findings"] if f["condition_key"] == "video_disapproval_diagnostic"
                          and f["severity"] == "Info"])

    def test_coverage_need_requires_planning_reference_and_batch_groups(self):
        base = {"id": "video_coverage_need", "outcome": "coverage_need_documented", "rationale": "brief asks video"}
        code, _ = self._decide([{**base, "proposal": {"planning_reference": "brief-3", "asset_group_ids": ["G1"]}}])
        self.assertEqual(code, 4)
        code, _ = self._decide([{**base, "proposal": {"asset_group_ids": ["G2"]}}])
        self.assertEqual(code, 4)
        code, final = self._decide([{**base, "proposal": {"planning_reference": "brief-3", "asset_group_ids": ["G2"]}}])
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "video_coverage_need"],
                         ["Info"])


if __name__ == "__main__":
    unittest.main()
