"""test_check.py — Decision-boundary tests for skill-035 image coverage/specification checks.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-035-image-asset-optimization/tests -t skills/skill-035-image-asset-optimization
rules:   Temp folders only; pins completeness-gated absence, exact-key joins (Search inheritance only),
spec evaluation with unknowns, required vs recommended and the Critical evidence gate, never wording.
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
_spec = importlib.util.spec_from_file_location("skill035_check", _SCRIPT)
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
          "1,P1,asset_group,AG3,2026-09-06,PERFORMANCE_MAX,ENABLED,PAUSED,,ui-3\n"
          "1,P1,asset_group,AG4,2026-09-06,PERFORMANCE_MAX,ENABLED,ENABLED,NOT_ELIGIBLE: missing images,diag-4\n"
          "1,S1,ad_group,G1,2026-09-06,SEARCH,ENABLED,ENABLED,ELIGIBLE,ui-5\n")
A_HDR = ("account_id,entity_type,entity_id,asset_id,field_type,snapshot_at,linking_level,status,approval,width_px,"
         "height_px,mime_type,file_size_bytes,source_ref\n")
ASSOC = A_HDR + ("1,asset_group,AG1,I1,LANDSCAPE_MARKETING_IMAGE,2026-09-06,asset_group,ENABLED,APPROVED,1200,628,image/jpeg,100000,x\n"
                 "1,asset_group,AG1,I2,SQUARE_MARKETING_IMAGE,2026-09-06,asset_group,ENABLED,APPROVED,1200,1200,image/png,100000,x\n"
                 "1,asset_group,AG2,I1,LANDSCAPE_MARKETING_IMAGE,2026-09-06,asset_group,ENABLED,APPROVED,1200,628,image/jpeg,100000,x\n"
                 "1,asset_group,AG2,I3,SQUARE_MARKETING_IMAGE,2026-09-06,asset_group,ENABLED,APPROVED,1200,900,image/png,100000,x\n"
                 "1,campaign,S1,I2,SQUARE_MARKETING_IMAGE,2026-09-06,campaign,ENABLED,APPROVED,1200,1200,image/png,100000,x\n")
R_HDR = ("subtype,field_type,requirement_id,effective_date,required_or_recommended,min_width,min_height,ratio,tolerance,"
         "max_file_bytes,mime_types,source_url,checked_at\n")
REQS = R_HDR + ("PERFORMANCE_MAX,SQUARE_MARKETING_IMAGE,SQ,2026-01-01,required,300,300,1:1,0.01,5120000,image/png;image/jpeg,u,2026-09-01\n"
                "PERFORMANCE_MAX,LANDSCAPE_MARKETING_IMAGE,LS,2026-01-01,required,600,314,1.91:1,0.01,5120000,,u,2026-09-01\n"
                "PERFORMANCE_MAX,PORTRAIT_MARKETING_IMAGE,PT,2026-01-01,recommended,480,600,4:5,0.01,,,u,2026-09-01\n"
                "SEARCH,SQUARE_MARKETING_IMAGE,SSQ,2026-01-01,recommended,300,300,1:1,0.01,,,u,2026-09-01\n"
                "SEARCH,LANDSCAPE_MARKETING_IMAGE,SLS,2027-01-01,required,600,314,1.91:1,0.01,,,u,2026-09-01\n")


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


FILES = {"custom/creative_groups.csv": GROUPS, "custom/image_associations.csv": ASSOC,
         "external/image_format_requirements.csv": REQS}


def found(body, key, sev=None):
    return sorted(f"{f['entity']['entity_id']}/{f['entity'].get('field_type', f['entity'].get('asset_id'))}"
                  for f in body["findings"] if f["condition_key"] == key and sev in (None, f["severity"]))


class Spec(unittest.TestCase):
    def test_evaluate_boundaries(self):
        req = {"min_width": "300", "min_height": "300", "ratio": "1:1", "tolerance": "0.01", "mime_types": "image/png"}
        self.assertEqual(M.evaluate({"width_px": "302", "height_px": "300", "mime_type": "image/png"}, req)[0], True)
        self.assertEqual(M.evaluate({"width_px": "320", "height_px": "300", "mime_type": "image/png"}, req)[0], False)
        self.assertIsNone(M.evaluate({"width_px": "0", "height_px": "300", "mime_type": "image/png"}, req)[0])
        self.assertIsNone(M.evaluate({"width_px": "300", "height_px": "300"}, req)[0])

    def test_required_spec_failure_is_provisional_with_review(self):
        _, b = run(self, FILES)
        self.assertEqual(found(b, "required_spec_not_met", "Info"), ["AG2/SQUARE_MARKETING_IMAGE"])
        self.assertIn("required_spec_not_met", [r["condition_key"] for r in b["ai_review"]])


class Roles(unittest.TestCase):
    def test_missing_required_role_and_optional_ratio(self):
        _, b = run(self, FILES)
        # AG2 square image fails spec → role missing; AG4 has no images; AG3 paused ignored
        self.assertEqual(found(b, "required_role_missing", "Info"),
                         ["AG2/SQUARE_MARKETING_IMAGE", "AG4/LANDSCAPE_MARKETING_IMAGE", "AG4/SQUARE_MARKETING_IMAGE"])
        self.assertIn("AG1/PORTRAIT_MARKETING_IMAGE", found(b, "optional_ratio_absent", "Info"))
        self.assertNotIn("AG3", " ".join(found(b, "required_role_missing") + found(b, "optional_ratio_absent")))

    def test_search_inherits_campaign_links_and_future_requirement_ignored(self):
        _, b = run(self, FILES)
        self.assertNotIn("G1/SQUARE_MARKETING_IMAGE", found(b, "optional_ratio_absent"))
        self.assertNotIn("G1/LANDSCAPE_MARKETING_IMAGE", found(b, "required_role_missing"))

    def test_incomplete_inventory_blocks_absence(self):
        _, b = run(self, FILES, complete=False)
        self.assertEqual(found(b, "required_role_missing") + found(b, "optional_ratio_absent"), [])
        self.assertEqual({c["check"]: c["status"] for c in b["coverage"]}["required_roles"], "partial")

    def test_critical_only_for_diagnosed_entity_with_evidence_ref(self):
        _, b = run(self, FILES)
        crit = {r["entity"]["entity_id"] for r in b["ai_review"] if "delivery_block_confirmed" in r["outcomes"]}
        self.assertEqual(crit, {"AG4"})

        def decide(prop):
            def f(body):
                item = next(r for r in body["ai_review"] if r["entity"].get("entity_id") == "AG4"
                            and r["entity"].get("field_type") == "SQUARE_MARKETING_IMAGE")
                return [{"id": item["id"], "outcome": "delivery_block_confirmed", "rationale": "diag", "proposal": prop}]
            return f
        rc, _ = run(self, FILES, decisions=decide({}))
        self.assertEqual(rc, 4)
        rc, _ = run(self, FILES, decisions=decide({"evidence_ref": "diag-unknown"}))
        self.assertEqual(rc, 4)
        rc, _ = run(self, FILES, decisions=decide({"evidence_ref": "ui-1"}))  # another entity's (eligible) row
        self.assertEqual(rc, 4)
        rc, final = run(self, FILES, decisions=decide({"evidence_ref": "diag-4"}))
        self.assertEqual(rc, 0)
        self.assertEqual(found(final, "required_role_missing", "Critical"), ["AG4/SQUARE_MARKETING_IMAGE"])
        stale = dict(FILES, **{"custom/creative_groups.csv": GROUPS.replace("2026-09-06,PERFORMANCE_MAX,ENABLED,ENABLED,"
                                                                            "NOT_ELIGIBLE", "2026-07-15,PERFORMANCE_MAX,"
                                                                            "ENABLED,ENABLED,NOT_ELIGIBLE")})
        rc, _ = run(self, stale, decisions=decide({"evidence_ref": "diag-4"}))  # diagnostic predates the window
        self.assertEqual(rc, 4)


class Coverage(unittest.TestCase):
    def test_missing_spine_skips_but_visual_review_runs(self):
        rev = ("asset_id,review_at,local_image_ref,visual_or_OCR_evidence,crop_subject_issue,text_review,reviewer_role,rationale\n"
               "I1,2026-09-05,img/1.jpg,ocr,product cropped,none,designer,cut\n")
        rc, b = run(self, {"external/image_review.csv": rev})
        self.assertEqual(rc, 0)
        c = {x["check"]: x["status"] for x in b["coverage"]}
        self.assertEqual(c["entity_spine"], "skipped")
        self.assertEqual(c["visual_review"], "completed")
        self.assertEqual([r["condition_key"] for r in b["ai_review"]], ["visual_defect"])
        self.assertEqual(b["findings"], [])


if __name__ == "__main__":
    unittest.main()
