"""test_check.py — skill-026 boundaries: duplicates, no length scoring, limits, context gating, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-026-rsa-description-optimization/tests
rules:   Temp folders only; asserts condition keys/severities and gating, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial tests
"""
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
_spec = importlib.util.spec_from_file_location("check_026", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}
PROFILE = {"intended_offer": "sell power tools", "required_qualifications": ["Prices incl. VAT"]}


def ad(ad_id, descs, status="ENABLED"):
    return {"id": ad_id, "campaign_id": "C1", "ad_group_id": "G1", "type": "RESPONSIVE_SEARCH_AD", "status": status,
            "headlines": "Drills | Saws | Tools", "descriptions": " | ".join(descs)}


class CheckTests(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, ads, profile=PROFILE, parents=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [ACCOUNT])
        self._write(root, "ads", ads)
        if parents:
            self._write(root, "campaigns", [{"id": "C1", "status": "ENABLED"}])
            self._write(root, "ad_groups", [{"id": "G1", "campaign_id": "C1", "status": "ENABLED"}])
        self.prof = Path(tmp.name) / "p.json"
        self.prof.write_text(json.dumps(profile))
        self.root, self.out = root, out
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--profile", str(self.prof), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _finalize(self, decisions):
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--profile", str(self.prof), "--out",
                               str(self.out), "--decisions", str(dec)])

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_duplicate_wording_keeps_price_differences(self):
        body = self._run([ad("A", ["From 79 EUR.", "from  79 eur.", "From 89 EUR."])])
        f = [x for x in body["findings"] if x["condition_key"] == "duplicate_description_wording"]
        self.assertEqual(len(f), 1)
        self.assertEqual(len(f[0]["evidence"]["groups"][0]), 2)

    def test_short_full_copy_is_not_a_finding(self):
        body = self._run([ad("A", ["Buy.", "Go.", "Now.", "Shop."])])
        self.assertEqual(body["findings"], [])

    def test_empty_optional_slot_is_info_only_for_active(self):
        body = self._run([ad("A", ["Buy tools online.", "Fast delivery."]),
                          ad("B", ["Buy tools online.", "Fast delivery."], status="PAUSED")])
        f = [x for x in body["findings"] if x["condition_key"] == "optional_empty_description_slot"]
        self.assertEqual([x["entity"]["ad_id"] for x in f], ["A"])
        self.assertEqual(f[0]["severity"], "Info")

    def test_over_width_export_is_partial_not_violation(self):
        body = self._run([ad("A", ["x" * 91, "Fast delivery.", "Top brands.", "Warranty."])])
        self.assertEqual(body["findings"], [])
        self.assertEqual(self._cov(body)["field_limits"], "partial")

    def test_wide_characters_count_double(self):
        body = self._run([ad("A", ["工" * 46, "Fast delivery.", "Top brands.", "Warranty."])])  # 92 columns
        self.assertEqual(self._cov(body)["field_limits"], "partial")

    def test_no_business_context_removes_warning_path(self):
        body = self._run([ad("A", ["Buy tools online.", "Fast delivery."])], profile={})
        item = [r for r in body["ai_review"] if r["condition_key"] == "description_coherence"][0]
        self.assertNotIn("Warning", {o["severity"] for o in item["outcomes"].values()})
        self.assertEqual(self._cov(body)["alternative_concepts"], "skipped")

    def test_missing_descriptions_skips_everything(self):
        rows = [{k: v for k, v in ad("A", ["x"]).items() if k != "descriptions"}]
        body = self._run(rows)
        self.assertTrue(all(s == "skipped" for s in self._cov(body).values()))

    def test_verify_warning_and_alternatives(self):
        body = self._run([ad("A", ["Buy tools online.", "Fast delivery."])])
        item = [r for r in body["ai_review"] if r["condition_key"] == "description_coherence"][0]
        base = {"id": item["id"], "rationale": "VAT qualifier missing"}
        self.assertEqual(self._finalize([{**base, "outcome": "contradiction_or_missing_qualification"}]), 4)
        self.assertEqual(self._finalize([{**base, "outcome": "coherent",
                                          "proposal": {"descriptions": ["fast  delivery."], "claim_source": "brief"}}]), 4)
        self.assertEqual(self._finalize([{**base, "outcome": "coherent",
                                          "proposal": {"descriptions": ["Prices incl. VAT."]}}]), 4)
        self.assertEqual(self._finalize([{**base, "outcome": "contradiction_or_missing_qualification",
                                          "proposal": {"evidence_ref": "brief#vat",
                                                       "descriptions": ["Prices incl. VAT."],
                                                       "claim_source": "brief#vat"}}]), 0)
        final = json.loads((self.out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["origin"] == "ai_review"], ["Warning"])


if __name__ == "__main__":
    unittest.main()
