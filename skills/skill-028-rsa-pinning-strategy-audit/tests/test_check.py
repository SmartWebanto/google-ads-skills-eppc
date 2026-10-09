"""test_check.py — skill-028 decision boundaries: guaranteed slots, optional positions, unknown pins, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-028-rsa-pinning-strategy-audit/tests
rules:   Temp folders only; never touch the shared fixture. Asserts behavior, not wording.
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
_spec = importlib.util.spec_from_file_location("check_028", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}


def h(*items):
    return json.dumps([{"text": t, "pinned_field": p} for t, p in items])


D = h(("Buy tools online", None), ("Delivery in Italy", None))


def ad(ad_id, headlines, descriptions=D, **extra):
    return {"id": ad_id, "campaign_id": "C", "ad_group_id": "G", "type": "RESPONSIVE_SEARCH_AD",
            "status": "ENABLED", "headlines": headlines, "descriptions": descriptions, **extra}


def req(ad_id, text, allowed="any", **extra):
    return {"ad_id": ad_id, "campaign_id": "C", "ad_group_id": "G", "requirement_id": "R-" + ad_id,
            "text_or_semantic_requirement": text, "allowed_positions": allowed, "must_always_show": "true",
            "valid_from": "2026-01-01", "valid_to": "2027-01-01", "approver_role": "owner",
            "source_ref": "brief", **extra}


class CheckTests(unittest.TestCase):
    def _write(self, root: Path, name: str, rows: list[dict]):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _export(self, ads, constraints=None, manifest=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        self._write(root, "account", [ACCOUNT])
        self._write(root, "ads", ads)
        names = ["account.csv", "ads.csv"]
        if constraints is not None:
            self._write(root, "external/rsa_message_constraints", constraints)
            names.append("external/rsa_message_constraints.csv")
        if manifest:
            self._write(root, "table_manifest", [{"filename": n, "completeness": "complete", "truncation": "none"}
                                                 for n in names])
        return root, Path(tmp.name) / "out"

    def _run(self, root, out, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--out", str(out), *extra])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    def _cov(self, body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def _warnings(self, body):
        return [f for f in body["findings"] if f["severity"] == "Warning"]

    def test_requirement_only_in_optional_h3_is_warning(self):
        root, out = self._export([ad("A", h(("Acme Tools", "HEADLINE_1"), ("Shop", None), ("Terms apply", "HEADLINE_3")))],
                                 [req("A", "Terms apply")])
        w = self._warnings(self._run(root, out))
        self.assertEqual([f["entity"]["ad_id"] for f in w], ["A"])
        self.assertEqual(w[0]["condition_key"], "required_message_not_guaranteed")

    def test_every_h1_alternative_compliant_is_guaranteed(self):
        root, out = self._export([ad("A", h(("Acme Tools", "HEADLINE_1"), ("Acme Store", "HEADLINE_1"), ("Shop", None),
                                           ("Drills", None)))], [req("A", "acme", "HEADLINE_1")])
        body = self._run(root, out)
        self.assertEqual(self._warnings(body), [])
        self.assertEqual(body["ai_review"], [])

    def test_one_noncompliant_alternative_breaks_guarantee(self):
        root, out = self._export([ad("A", h(("Acme Tools", "HEADLINE_1"), ("Big Sale", "HEADLINE_1"), ("Shop", None),
                                           ("Drills", None)))], [req("A", "acme", "HEADLINE_1")])
        w = self._warnings(self._run(root, out))
        self.assertEqual(len(w), 1)
        self.assertIn("Big Sale", w[0]["evidence"]["incompatible_alternatives"])

    def test_unpinned_requirement_not_guaranteed_when_pool_has_other_text(self):
        root, out = self._export([ad("A", h(("Acme", None), ("Shop", None), ("Drills", None)))],
                                 [req("A", "acme")])
        self.assertEqual(len(self._warnings(self._run(root, out))), 1)

    def test_unknown_pins_are_partial_not_a_gap(self):
        plain = ad("A", "Acme Tools | Shop | Terms apply", "Buy online | Delivery")
        root, out = self._export([plain], [req("A", "Terms apply")])
        body = self._run(root, out)
        self.assertEqual(self._warnings(body), [])
        cov = self._cov(body)
        self.assertEqual(cov["slot_maps"], "partial")
        self.assertEqual(cov["mandatory_messages"], "partial")

    def test_missing_constraints_skip_requirement_checks(self):
        root, out = self._export([ad("A", h(("Acme", "HEADLINE_1"), ("Shop", None), ("X", None)))])
        body = self._run(root, out)
        cov = self._cov(body)
        self.assertEqual(cov["mandatory_messages"], "skipped")
        self.assertEqual(cov["gap_classification"], "skipped")
        self.assertEqual(body["findings"], [])

    def test_expired_requirement_is_not_evaluated(self):
        root, out = self._export([ad("A", h(("Acme", "HEADLINE_1"), ("Shop", None), ("Terms", "HEADLINE_3")))],
                                 [req("A", "Terms", valid_to="2026-06-30")])
        self.assertEqual(self._warnings(self._run(root, out)), [])

    def test_unsupported_pin_value_is_info_and_blocks_guarantee(self):
        root, out = self._export([ad("A", h(("Acme", "HEADLINE_9"), ("Shop", None), ("Terms", None)))],
                                 [req("A", "Terms")])
        body = self._run(root, out)
        self.assertEqual([f["condition_key"] for f in body["findings"]], ["unknown_pin_value"])
        self.assertEqual(body["findings"][0]["severity"], "Info")

    def test_semantic_requirement_goes_to_review_and_verify_checks_slot(self):
        ads = [ad("A", h(("Official Acme", "HEADLINE_1"), ("Acme Store", "HEADLINE_1"), ("Shop", None), ("Y", None)))]
        root, out = self._export(ads, [req("A", "brand name", "HEADLINE_1")])
        body = self._run(root, out)
        self.assertEqual(self._warnings(body), [])
        self.assertEqual(len(body["ai_review"]), 1)
        item = body["ai_review"][0]
        self.assertEqual(item["outcomes"]["not_guaranteed"]["severity"], "Warning")
        self.assertTrue(item["provisional_finding"])
        cases = [({"slot": "HEADLINE_1", "alternatives": [0]}, 4),
                 ({"slot": "HEADLINE_2", "alternatives": [2]}, 4),
                 ({"slot": "HEADLINE_1", "alternatives": [0, 1]}, 0)]
        for proposal, expected in cases:
            dec = out.parent / "decisions.json"
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "guaranteed_by_equivalent_text",
                                        "rationale": "both alternatives name the brand", "proposal": proposal}]))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                  ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)])
            self.assertEqual(code, expected, proposal)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual(final["findings"], [])

    def test_pinned_performance_needs_maturity_and_both_cohorts(self):
        ads = [ad("A", h(("Acme", "HEADLINE_1"), ("Shop", None), ("X", None))),
               ad("B", h(("Acme", None), ("Shop", None), ("X", None)))]
        root, out = self._export(ads)
        self._write(root, "ad_metrics", [
            {"ad_id": "A", "campaign_id": "C", "ad_group_id": "G", "impressions": 5000, "clicks": 400, "cost": 300,
             "conversions": 20},
            {"ad_id": "B", "campaign_id": "C", "ad_group_id": "G", "impressions": 500, "clicks": 50, "cost": 40,
             "conversions": 2}])
        body = self._run(root, out)
        obs = [o for o in body["observations"] if o["check"] == "pinned_performance"][0]["data"]
        self.assertFalse(obs["ctr_comparable"])
        self.assertIsNone(obs["pinned_ctr"])


if __name__ == "__main__":
    unittest.main()
