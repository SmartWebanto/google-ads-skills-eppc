"""test_check.py — skill-029 boundaries: association joins, label states, guardrail comparison gates, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-029-rsa-asset-performance-analysis/tests
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
_spec = importlib.util.spec_from_file_location("check_029", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}


def ad(ad_id):
    return {"id": ad_id, "campaign_id": "C1", "ad_group_id": "G1", "type": "RESPONSIVE_SEARCH_AD",
            "status": "ENABLED", "headlines": "H one | H two | H three", "descriptions": "D one | D two"}


def label(ad_id, asset, field="HEADLINE", lab="GOOD", ad_type="RESPONSIVE_SEARCH_AD"):
    return {"account_id": "c1", "campaign_id": "C1", "ad_group_id": "G1", "ad_id": ad_id, "asset_id": asset,
            "field_type": field, "ad_type": ad_type, "text": asset, "performance_label": lab,
            "snapshot_at": "2026-09-05", "source_ref": "ui"}


def full_labels(ad_id, low=()):
    rows = [label(ad_id, f"{ad_id}-h{i}", lab="LOW" if f"{ad_id}-h{i}" in low else "GOOD") for i in range(3)]
    return rows + [label(ad_id, f"{ad_id}-d{i}", "DESCRIPTION") for i in range(2)]


def metric(ad_id, conv, cost, imp=10000, clicks=500):
    return {"ad_id": ad_id, "campaign_id": "C1", "ad_group_id": "G1", "impressions": imp, "clicks": clicks,
            "cost": cost, "conversions": conv, "conversion_value": conv * 50}


class CheckTests(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, ads, labels=None, metrics=None, lag="2", target_cpa="40"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [{**ACCOUNT, "conversion_lag_days": lag}])
        self._write(root, "campaigns", [{"id": "C1", "status": "ENABLED", "target_cpa": target_cpa}])
        self._write(root, "ads", ads)
        if labels is not None:
            self._write(root, "custom/rsa_asset_labels", labels)
        if metrics is not None:
            self._write(root, "ad_metrics", metrics)
        self.root, self.out = root, out
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _finalize(self, decisions):
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", "--export", str(self.root), "--out",
                                                                   str(self.out), "--decisions", str(dec)])

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def _keys(self, body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    def test_low_label_is_info_with_provisional_review(self):
        body = self._run([ad("A")], full_labels("A", low=("A-h1",)))
        f = self._keys(body, "low_label_assets")
        self.assertEqual([(x["severity"], x["entity"]["field_type"]) for x in f], [("Info", "HEADLINE")])
        rv = [r for r in body["ai_review"] if r["condition_key"] == "low_label_assets"]
        self.assertEqual(rv[0]["provisional_finding"], f[0]["id"])

    def test_absent_labels_are_coverage_not_low(self):
        body = self._run([ad("A"), ad("B")], full_labels("A"))
        self.assertEqual(self._keys(body, "low_label_assets"), [])
        self.assertEqual(self._cov(body)["rsa_association_join"], "partial")

    def test_learning_labels_info_and_duplicates_excluded(self):
        rows = [label("A", f"h{i}", lab="LEARNING") for i in range(3)] + [label("A", "h0", lab="LOW")]
        rows += [label("A", "p1", ad_type="RESPONSIVE_DISPLAY_AD", lab="LOW")]
        body = self._run([ad("A")], rows)
        self.assertEqual(len(self._keys(body, "labels_all_learning_or_unrated")), 1)
        self.assertEqual(self._keys(body, "low_label_assets"), [])  # duplicate key and display row dropped
        self.assertEqual(self._cov(body)["association_keys"], "partial")

    def test_missing_labels_file_skips_label_checks_only(self):
        body = self._run([ad("A")], None, [metric("A", 20, 400)])
        cov = self._cov(body)
        self.assertEqual(cov["label_summary"], "skipped")
        self.assertNotEqual(cov["ad_grain_performance"], "skipped")

    def test_guardrail_review_needs_both_qualified_and_maturity(self):
        ads = [ad("A"), ad("B")]
        labels = full_labels("A", low=("A-h0",)) + full_labels("B")
        body = self._run(ads, labels, [metric("A", 20, 1200), metric("B", 20, 500)])  # CPA 60 vs 25; target 40
        rv = [r for r in body["ai_review"] if r["condition_key"] == "guardrail_outcome_copy_issue"]
        self.assertEqual([r["entity"]["ad_id"] for r in rv], ["A"])
        body = self._run(ads, labels, [metric("A", 20, 1200), metric("B", 10, 250)])  # peer below min_conversions
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "guardrail_outcome_copy_issue"], [])
        body = self._run(ads, labels, [metric("A", 20, 1200), metric("B", 20, 500)], lag="")
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "guardrail_outcome_copy_issue"], [])
        self.assertEqual(self._cov(body)["matched_comparison"], "partial")

    def test_no_target_is_partial(self):
        body = self._run([ad("A"), ad("B")], None, [metric("A", 20, 1200), metric("B", 20, 500)], target_cpa="")
        self.assertEqual(self._cov(body)["matched_comparison"], "partial")
        self.assertEqual(body["ai_review"], [])

    def test_verify_copy_issue_requires_low_assets(self):
        ads = [ad("A"), ad("B")]
        labels = full_labels("A", low=("A-h0",)) + full_labels("B")
        body = self._run(ads, labels, [metric("A", 20, 1200), metric("B", 20, 500)])
        item = [r for r in body["ai_review"] if r["condition_key"] == "guardrail_outcome_copy_issue"][0]
        base = {"id": item["id"], "outcome": "corroborated_copy_issue", "rationale": "Low headline contradicts offer"}
        self.assertEqual(self._finalize([{**base}]), 4)
        self.assertEqual(self._finalize([{**base, "proposal": {"asset_ids": ["B-h0"]}}]), 4)
        self.assertEqual(self._finalize([{**base, "proposal": {"asset_ids": ["A-h0"]}}]), 0)
        final = json.loads((self.out / "final.json").read_text())
        self.assertIn("Warning", [f["severity"] for f in final["findings"]])


if __name__ == "__main__":
    unittest.main()
