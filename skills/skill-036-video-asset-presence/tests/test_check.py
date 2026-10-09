"""test_check.py — Decision-boundary tests for skill-036 video coverage/provenance checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-036-video-asset-presence/tests -t skills/skill-036-video-asset-presence
rules:   Temp folders only; pins unknown≠generated, exact-key joins, completeness-gated absence, format
matching and the Critical evidence gate, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | unknown/foreign/stale evidence_ref rejected
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill036_check", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,"
           "2026-09-06,fraction,currency,interaction_date,2\n")
GROUPS = ("account_id,campaign_id,entity_type,entity_id,snapshot_at,subtype,parent_status,entity_status,eligibility,source_ref\n"
          "1,P1,asset_group,AG1,2026-09-06,PERFORMANCE_MAX,ENABLED,ENABLED,ELIGIBLE,ui-1\n"
          "1,P1,asset_group,AG2,2026-09-06,PERFORMANCE_MAX,ENABLED,ENABLED,ELIGIBLE,ui-2\n"
          "1,D1,ad,DG1,2026-09-06,DEMAND_GEN,ENABLED,ENABLED,ELIGIBLE,ui-3\n"
          "1,V1,ad_group,VG1,2026-09-06,VIDEO,ENABLED,ENABLED,NOT_ELIGIBLE: video removed,diag-4\n")
A_HDR = ("account_id,entity_type,entity_id,asset_id,field_type,snapshot_at,linking_level,youtube_video_id,"
         "association_status,approval,provenance,provenance_source,source_ref\n")
ASSOC = A_HDR + ("1,asset_group,AG1,V1,YOUTUBE_VIDEO,2026-09-06,asset_group,yt1,ENABLED,APPROVED,generated,ui,x\n"
                 "1,asset_group,AG2,V2,YOUTUBE_VIDEO,2026-09-06,asset_group,yt2,ENABLED,APPROVED,,,x\n"
                 "1,campaign,D1,V3,YOUTUBE_VIDEO,2026-09-06,campaign,yt3,ENABLED,APPROVED,uploaded,ui,x\n")
R_HDR = ("subtype,ad_format,requirement_id,effective_date,required_or_recommended,duration_min,duration_max,"
         "allowed_ratios,source_url,checked_at\n")
REQS = R_HDR + ("VIDEO,IN_STREAM,VR1,2026-01-01,required,6,180,16:9,u,2026-09-01\n"
                "PERFORMANCE_MAX,YOUTUBE_VIDEO,PV1,2026-01-01,recommended,10,,16:9;1:1;9:16,u,2026-09-01\n"
                "DEMAND_GEN,YOUTUBE_VIDEO,DV1,2026-01-01,required,5,60,16:9;1:1,u,2026-09-01\n")
REV = ("asset_id,review_at,local_video_or_authorized_review_ref,duration_seconds,width_px,height_px,language,audio,captions,"
       "brand_message_review,source_ref\n"
       "V1,2026-09-05,r1,4,1920,1080,it,yes,yes,ok,s1\n"
       "V2,2026-09-05,r2,30,1080,1080,it,yes,no,logo appears only at the end,s2\n")


def run(test, files, complete=True, decisions=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    files = {"account.csv": ACCOUNT, **files}
    files["table_manifest.csv"] = "filename,completeness,truncation\n" + "".join(
        f"{n},{'complete' if complete or not n.startswith('custom') else 'partial'},none\n" for n in list(files))
    for name, text in files.items():
        p = root / "export" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (root / "profile.json").write_text("{}")
    args = ["--export", str(root / "export"), "--profile", str(root / "profile.json"), "--out", str(root / "out")]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
    body = json.loads((root / "out" / "result.json").read_text())
    if decisions is None:
        return rc, body
    (root / "d.json").write_text(json.dumps(decisions(body)))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc2 = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(root / "d.json")])
    return rc2, json.loads((root / "out" / "final.json").read_text())


FILES = {"custom/creative_groups.csv": GROUPS, "custom/video_associations.csv": ASSOC,
         "external/video_format_requirements.csv": REQS, "external/video_review.csv": REV}


def found(body, key, sev=None):
    return sorted(f["entity"]["entity_id"] for f in body["findings"] if f["condition_key"] == key and sev in (None, f["severity"]))


class Provenance(unittest.TestCase):
    def test_unknown_is_not_generated(self):
        self.assertEqual(M.provenance(""), "unknown")
        self.assertEqual(M.provenance("youtube"), "unknown")
        _, b = run(self, FILES)
        self.assertEqual(found(b, "no_custom_video", "Info"), ["AG1"])
        self.assertEqual(found(b, "provenance_unknown", "Info"), ["AG2"])


class Requirements(unittest.TestCase):
    def test_campaign_link_does_not_cover_demand_gen_ad(self):
        _, b = run(self, FILES)
        self.assertIn("DG1", found(b, "required_video_missing", "Info"))

    def test_duration_outside_range_and_optional_format(self):
        _, b = run(self, FILES)
        self.assertEqual(found(b, "format_requirement_not_met"), ["AG1"])  # 4s < 10s recommended
        self.assertEqual(found(b, "optional_format_absent", "Info"), ["AG1"])

    def test_image_only_demand_gen_can_be_intentional(self):
        _, b = run(self, FILES)
        r = next(x for x in b["ai_review"] if x["entity"].get("entity_id") == "DG1")
        self.assertIsNone(r["outcomes"]["intentional_without_video"]["severity"])
        self.assertNotIn("delivery_block_confirmed", r["outcomes"])

    def test_incomplete_inventory_blocks_absence(self):
        _, b = run(self, FILES, complete=False)
        self.assertEqual(found(b, "required_video_missing") + found(b, "optional_format_absent"), [])

    def test_critical_requires_diagnostic_and_evidence_ref(self):
        def decide(prop):
            def f(body):
                item = next(x for x in body["ai_review"] if x["entity"].get("entity_id") == "VG1")
                return [{"id": item["id"], "outcome": "delivery_block_confirmed", "rationale": "diag", "proposal": prop}]
            return f
        rc, _ = run(self, FILES, decisions=decide({}))
        self.assertEqual(rc, 4)
        rc, _ = run(self, FILES, decisions=decide({"evidence_ref": "diag-unknown"}))
        self.assertEqual(rc, 4)
        rc, _ = run(self, FILES, decisions=decide({"evidence_ref": "ui-3"}))  # another entity's row
        self.assertEqual(rc, 4)
        rc, final = run(self, FILES, decisions=decide({"evidence_ref": "diag-4"}))
        self.assertEqual(rc, 0)
        self.assertEqual(found(final, "required_video_missing", "Critical"), ["VG1"])
        stale = dict(FILES, **{"custom/creative_groups.csv": GROUPS.replace("VG1,2026-09-06", "VG1,2026-07-15")})
        rc, _ = run(self, stale, decisions=decide({"evidence_ref": "diag-4"}))  # diagnostic predates the window
        self.assertEqual(rc, 4)


class Coverage(unittest.TestCase):
    def test_media_review_runs_without_spine_and_performance_is_skipped(self):
        rc, b = run(self, {"external/video_review.csv": REV})
        self.assertEqual(rc, 0)
        c = {x["check"]: x["status"] for x in b["coverage"]}
        self.assertEqual(c["media_review"], "completed")
        self.assertEqual(c["video_performance"], "skipped")
        self.assertEqual([r["entity"]["asset_id"] for r in b["ai_review"]], ["V2"])
        self.assertEqual(b["findings"], [])


if __name__ == "__main__":
    unittest.main()
