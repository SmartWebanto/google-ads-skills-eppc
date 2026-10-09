"""test_check.py — Decision-boundary tests for skill-162 creative check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-162-creative-asset-quality-ai-campaign-optimization/tests -t skills/skill-162-creative-asset-quality-ai-campaign-optimization
rules:   Temp folders only; pins consumer-visible behavior (left join/empty groups, required vs recommended specs,
ambiguous specs, unknown provenance, literal duplicates, dated Low history, verify), never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
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

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill162_check", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

INV_COLS = ["account_id", "campaign_id", "group_type", "group_id", "snapshot_at", "subtype", "status", "goal",
            "business_theme", "eligibility_status"]
ASSET_COLS = ["account_id", "group_id", "ad_id", "asset_id", "association_id", "snapshot_at", "asset_type",
              "field_role", "linked_status", "policy_status", "text", "width", "height", "duration_seconds",
              "provenance", "source_ref", "performance_label", "label_date"]
HIST_COLS = ["association_id", "observed_at", "label", "impressions", "clicks", "cost", "conversions",
             "conversion_value", "reporting_context"]
REQ_COLS = ["subtype", "format", "requirement_id", "required_or_recommended", "supported_asset_spec",
            "official_source_url", "checked_at", "mandatory_message", "brand_rule", "evidence_ref", "owner"]


def grp(gid, cid="30", subtype="pmax_standard", status="ENABLED", gtype="ASSET_GROUP"):
    return {"account_id": "1", "campaign_id": cid, "group_type": gtype, "group_id": gid, "snapshot_at": "2026-09-05",
            "subtype": subtype, "status": status, "eligibility_status": "eligible"}


def asset(gid, aid, atype="IMAGE", **kw):
    base = {"account_id": "1", "group_id": gid, "asset_id": f"A{aid}", "association_id": aid, "asset_type": atype,
            "field_role": "MARKETING_IMAGE" if atype == "IMAGE" else atype, "linked_status": "ENABLED",
            "provenance": "custom", "width": "1200", "height": "628"}
    base.update(kw)
    return base


def req(rid, fmt="image", kind="required", spec_text="min_width=600;min_height=314", **kw):
    base = {"subtype": "pmax_standard", "format": fmt, "requirement_id": rid, "required_or_recommended": kind,
            "supported_asset_spec": spec_text, "official_source_url": "https://support.google.com/x",
            "checked_at": "2026-09-01"}
    base.update(kw)
    return base


def build(tmp: Path, *, groups=None, assets=None, history=None, reqs=None, complete=True) -> Path:
    root = tmp / "export"
    files = {
        "account.csv": (["customer_id", "name", "currency_code", "time_zone", "date_range_start", "date_range_end",
                         "snapshot_date", "rates_format", "money_unit", "conversion_date_basis", "conversion_lag_days"],
                        [{"customer_id": "1", "name": "A", "currency_code": "EUR", "time_zone": "Europe/Rome",
                          "date_range_start": "2026-08-01", "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06",
                          "rates_format": "fraction", "money_unit": "currency",
                          "conversion_date_basis": "interaction_date", "conversion_lag_days": "3"}]),
        "campaigns.csv": (["id", "status", "channel_type"],
                          [{"id": "30", "status": "ENABLED", "channel_type": "PERFORMANCE_MAX"},
                           {"id": "31", "status": "ENABLED", "channel_type": "SEARCH"},
                           {"id": "32", "status": "ENABLED", "channel_type": "SHOPPING"}]),
    }
    if groups is not None:
        files["custom/creative_group_inventory.csv"] = (INV_COLS, groups)
    if assets is not None:
        files["custom/creative_quality_assets.csv"] = (ASSET_COLS, assets)
    if history is not None:
        files["custom/creative_label_history.csv"] = (HIST_COLS, history)
    if reqs is not None:
        files["external/creative_requirements.csv"] = (REQ_COLS, reqs)
    manifest = [{"filename": n, "source": "test",
                 "completeness": "complete" if complete or "creative_quality" not in n else "partial sample",
                 "truncation": "none"} for n in files]
    files["table_manifest.csv"] = (["filename", "source", "completeness", "truncation"], manifest)
    for name, (cols, rows) in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
    return root


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)

    def run_check(self, **kw) -> dict:
        root = build(self.tmp, **kw)
        out = self.tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        self.assertEqual(code, 0)
        self.root, self.out = root, out
        return json.loads((out / "result.json").read_text())

    def finalize(self, decisions) -> tuple[int, dict]:
        d = self.tmp / "decisions.json"
        d.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--out", str(self.out), "--decisions", str(d)])
        return code, json.loads((self.out / "final.json").read_text())


def found(res, check):
    return sorted((f["condition_key"], f["severity"], f["entity"].get("group_id"), f["entity"].get("association_id"))
                  for f in res["findings"] if f["check"] == check)


def cov(res, check):
    return next(c for c in res["coverage"] if c["check"] == check)


def reviews(res, key):
    return [r for r in res["ai_review"] if r["condition_key"] == key]


class Coverage(Base):
    def test_missing_inventory_is_skipped(self):
        res = self.run_check(assets=[asset("G1", "1")])
        self.assertEqual(cov(res, "group_association_coverage")["status"], "skipped")
        self.assertIn("custom/creative_group_inventory (file)", cov(res, "group_association_coverage")["missing"])

    def test_empty_group_visible_with_review(self):
        res = self.run_check(groups=[grp("G1"), grp("G2")],
                             assets=[asset("G1", "1"), asset("G2", "2", linked_status="REMOVED")])
        self.assertEqual(found(res, "group_association_coverage"), [("group_without_linked_assets", "Info", "G2", None)])
        self.assertEqual(len(reviews(res, "group_without_linked_assets")), 1)

    def test_unknown_linked_status_is_not_empty(self):
        res = self.run_check(groups=[grp("G1")], assets=[asset("G1", "1", linked_status="")])
        self.assertEqual(found(res, "group_association_coverage"), [])

    def test_incomplete_assets_cannot_prove_empty(self):
        res = self.run_check(groups=[grp("G1"), grp("G2")], assets=[asset("G1", "1")], complete=False)
        self.assertEqual(found(res, "group_association_coverage"), [])
        self.assertEqual(cov(res, "group_association_coverage")["status"], "partial")

    def test_out_of_scope_channel_excluded(self):
        res = self.run_check(groups=[grp("G9", cid="32")], assets=[])
        self.assertEqual(found(res, "group_association_coverage"), [])

    def test_critical_block_needs_evidence_ref(self):
        res = self.run_check(groups=[grp("G1"), grp("G2")], assets=[asset("G3", "9")])
        items = sorted(reviews(res, "group_without_linked_assets"), key=lambda r: r["entity"]["group_id"])
        code, final = self.finalize([
            {"id": items[0]["id"], "outcome": "material_block_evidenced", "rationale": "not serving"},
            {"id": items[1]["id"], "outcome": "material_block_evidenced", "rationale": "not serving",
             "proposal": {"evidence_ref": "custom/eligibility_diag.csv#G2"}}])
        self.assertEqual(code, 4)
        self.assertEqual(final["counts"]["Critical"], 1)
        self.assertEqual(final["counts"]["Info"], 1)


class Specs(Base):
    def test_required_spec_breach_is_warning_and_conforming_is_not(self):
        res = self.run_check(groups=[grp("G1")], reqs=[req("R1")],
                             assets=[asset("G1", "1", width="500", height="300"), asset("G1", "2")])
        self.assertEqual(found(res, "required_spec_conformance"), [("required_spec_conflict", "Warning", "G1", "1")])

    def test_recommended_breach_is_info(self):
        res = self.run_check(groups=[grp("G1")], reqs=[req("R1", kind="recommended")],
                             assets=[asset("G1", "1", width="500")])
        self.assertEqual(found(res, "required_spec_conformance"), [("recommended_spec_gap", "Info", "G1", "1")])

    def test_unknown_measure_is_partial_not_pass(self):
        res = self.run_check(groups=[grp("G1")], reqs=[req("R1")], assets=[asset("G1", "1", width="")])
        self.assertEqual(found(res, "required_spec_conformance"), [])
        self.assertEqual(cov(res, "required_spec_conformance")["status"], "partial")

    def test_ambiguous_required_spec_goes_to_review(self):
        res = self.run_check(groups=[grp("G1")], reqs=[req("R1", spec_text="1.91:1 landscape, at least 600px wide")],
                             assets=[asset("G1", "1")])
        self.assertEqual(found(res, "required_spec_conformance"), [])
        self.assertEqual(len(reviews(res, "required_spec_ambiguous")), 1)

    def test_missing_required_vs_recommended_format(self):
        res = self.run_check(groups=[grp("G1")], assets=[asset("G1", "1")],
                             reqs=[req("R1", fmt="logo", spec_text=""), req("R2", fmt="video", kind="recommended", spec_text="")])
        self.assertEqual(found(res, "required_spec_conformance"),
                         [("recommended_format_missing", "Info", "G1", None), ("required_format_missing", "Warning", "G1", None)])

    def test_other_subtype_requirement_ignored(self):
        res = self.run_check(groups=[grp("G1", subtype="demand_gen")], assets=[asset("G1", "1", width="10")],
                             reqs=[req("R1")])
        self.assertEqual(found(res, "required_spec_conformance"), [])

    def test_mandatory_message_review(self):
        res = self.run_check(groups=[grp("G1")], reqs=[req("R1", fmt="", spec_text="", mandatory_message="Terms apply")],
                             assets=[asset("G1", "1", atype="TEXT", field_role="HEADLINE", text="Big sale")])
        items = reviews(res, "message_constraint")
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["evidence"]["texts"][0]["literal_contains_message"])


class Text(Base):
    def test_literal_duplicate_after_normalization(self):
        res = self.run_check(groups=[grp("G1")], assets=[
            asset("G1", "1", atype="TEXT", field_role="HEADLINE", text="Fast Delivery!"),
            asset("G1", "2", atype="TEXT", field_role="HEADLINE", text="fast  delivery"),
            asset("G1", "3", atype="TEXT", field_role="DESCRIPTION", text="Fast delivery")])
        f = [x for x in res["findings"] if x["condition_key"] == "literal_duplicate_text"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["evidence"]["association_ids"], ["1", "2"])
        self.assertEqual(len(reviews(res, "theme_diversity")), 1)

    def test_distinct_texts_no_duplicate(self):
        res = self.run_check(groups=[grp("G1")], assets=[
            asset("G1", "1", atype="TEXT", field_role="HEADLINE", text="Fast delivery"),
            asset("G1", "2", atype="TEXT", field_role="HEADLINE", text="Free returns")])
        self.assertEqual(found(res, "text_duplicates_and_themes"), [])

    def test_unknown_provenance_stays_unknown(self):
        res = self.run_check(groups=[grp("G1")], assets=[asset("G1", "1", atype="VIDEO", provenance="")])
        self.assertEqual(cov(res, "provenance")["status"], "partial")
        self.assertEqual(found(res, "provenance"), [])


def hist(aid, day, label="LOW", ctx="pmax", impr="800"):
    return {"association_id": aid, "observed_at": f"2026-08-{day:02d}", "label": label, "impressions": impr,
            "reporting_context": ctx}


class Labels(Base):
    def test_snapshot_low_without_history_is_partial(self):
        res = self.run_check(groups=[grp("G1")], assets=[asset("G1", "1", performance_label="LOW", label_date="2026-09-05")])
        self.assertEqual(found(res, "performance_labels"), [])
        self.assertIn("custom/creative_label_history (file)", cov(res, "performance_labels")["missing"])

    def test_dated_low_run_is_info(self):
        res = self.run_check(groups=[grp("G1")], assets=[asset("G1", "1", performance_label="LOW")],
                             history=[hist("1", 1, "GOOD"), hist("1", 5), hist("1", 30)])
        f = [x for x in res["findings"] if x["condition_key"] == "persistent_low_label"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "Info")
        self.assertEqual(f[0]["evidence"]["span_days"], 25)
        self.assertTrue(f[0]["evidence"]["sample_gate_met"])

    def test_latest_not_low_or_mixed_context_no_claim(self):
        for rows in ([hist("1", 5), hist("1", 30, "GOOD")], [hist("1", 5), hist("1", 30, ctx="search")],
                     [hist("1", 5)]):
            with self.subTest(rows=rows):
                res = self.run_check(groups=[grp("G1")], assets=[asset("G1", "1")], history=rows)
                self.assertEqual(found(res, "performance_labels"), [])


if __name__ == "__main__":
    unittest.main()
