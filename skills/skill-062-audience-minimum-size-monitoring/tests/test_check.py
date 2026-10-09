"""test_check.py — skill-062 audience eligibility and weekly size-trend decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-062-audience-minimum-size-monitoring/tests
rules:   stdlib only; temp folders; no network; asserts decisions, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial tests
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_062", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01", "date_range_end": "2026-08-28",
           "snapshot_date": "2026-09-05", "money_unit": "currency", "conversion_lag_days": "2"}


def _write(path: Path, rows: list[dict], cols=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(cols or [])
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Env:
    def __init__(self, test, tables: dict):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exp = self.root / "export"
        for key, rows in tables.items():
            _write(self.exp / f"{key}.csv", rows, AUD_COLS if key == "audiences" else None)
        _write(self.exp / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        (self.root / "profile.json").write_text("{}")

    def cli(self, *extra) -> int:
        cmd = extra[0]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                            [cmd, "--export", str(self.exp), "--profile", str(self.root / "profile.json"),
                             "--out", str(self.root / "out"), *extra[1:]])

    def run(self) -> dict:
        assert self.cli("run") == 0
        return json.loads((self.root / "out" / "result.json").read_text())


AUD_COLS = ["list_id", "campaign_id", "ad_group_id", "mode", "status"]


def elig(lid, channel="SEARCH", eligible="false", use="TARGETING"):
    return {"list_id": lid, "channel": channel, "use_type": use, "snapshot_date": "2026-09-05", "list_type": "REMARKETING",
            "reported_size": 500, "size_precision": "exact", "membership_status": "OPEN", "membership_duration_days": 30,
            "eligible": eligible, "eligibility_reason": "TOO_SMALL", "processing_status": "COMPLETED",
            "owner_account_id": "1"}


def base(elig_rows, assoc, camp_status="ENABLED", history=None):
    t = {"account": [ACCOUNT],
         "campaigns": [{"id": "10", "status": camp_status, "channel_type": "SEARCH"}],
         "campaign_metrics": [{"campaign_id": "10", "impressions": 100, "cost": 50}],
         "audiences": [{"list_id": l, "campaign_id": "10", "ad_group_id": "20", "mode": m, "status": "ENABLED"}
                       for l, m in assoc],
         "custom/audience_eligibility": elig_rows}
    if history is not None:
        t["custom/audience_size_history"] = history
    return t


def hist(lid, pts, prec="exact"):
    return [{"list_id": lid, "channel": "SEARCH", "use_type": "TARGETING", "size_as_of": d, "reported_size": s,
             "size_precision": prec} for d, s in pts]


def conds(body, sev=None):
    return sorted((f["condition_key"], f["entity"].get("list_id")) for f in body["findings"]
                  if sev is None or f["severity"] == sev)


class AudienceEligibilityTests(unittest.TestCase):
    def test_ineligible_hard_targeting_vs_observation(self):
        body = Env(self, base([elig("A"), elig("B")], [("A", "TARGETING"), ("B", "OBSERVATION")])).run()
        self.assertEqual(conds(body, "Warning"), [("ineligible_hard_targeting", "A")])
        self.assertIn(("ineligible_non_restrictive", "B"), conds(body, "Info"))
        self.assertEqual(len(body["ai_review"]), 1)

    def test_channel_mismatch_and_paused_campaign_are_not_warnings(self):
        body = Env(self, base([elig("A", channel="DISPLAY")], [("A", "TARGETING")])).run()
        self.assertEqual(conds(body, "Warning"), [])
        body = Env(self, base([elig("A")], [("A", "TARGETING")], camp_status="PAUSED")).run()
        self.assertEqual(conds(body, "Warning"), [])

    def test_unknown_status_is_info_not_pass(self):
        body = Env(self, base([elig("A", eligible="")], [("A", "TARGETING")])).run()
        self.assertEqual(conds(body), [("eligibility_unknown", None)])

    def test_weekly_decline_boundaries(self):
        cases = {
            "exact_30pct": (hist("A", [("2026-08-29", 1000), ("2026-09-05", 700)]), True),
            "rounded_within_uncertainty": (hist("A", [("2026-08-29", 1000), ("2026-09-05", 790)], "rounded to 100"), False),
            "not_weekly": (hist("A", [("2026-08-26", 1000), ("2026-09-05", 500)]), False),
            "zero_old": (hist("A", [("2026-08-29", 0), ("2026-09-05", 0)]), False),
            "exactly_20pct": (hist("A", [("2026-08-29", 1000), ("2026-09-05", 800)]), False),
        }
        for name, (h, expect) in cases.items():
            with self.subTest(name):
                body = Env(self, base([elig("A", eligible="true")], [("A", "OBSERVATION")], history=h)).run()
                self.assertEqual(("weekly_size_decline", "A") in conds(body, "Warning"), expect)

    def test_decline_on_unused_list_not_warning(self):
        h = hist("A", [("2026-08-29", 1000), ("2026-09-05", 500)])
        body = Env(self, base([elig("A", eligible="true")], [], history=h)).run()
        self.assertEqual(conds(body, "Warning"), [])
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["size_trend"], "completed")

    def test_missing_history_blocks_only_trend(self):
        body = Env(self, base([elig("A")], [("A", "TARGETING")])).run()
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["size_trend"], "skipped")
        self.assertEqual(cov["current_eligibility"], "completed")

    def test_finalize_critical_requires_evidence_ref(self):
        env = Env(self, base([elig("A")], [("A", "TARGETING")]))
        rid = env.run()["ai_review"][0]["id"]
        dec = env.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "confirmed_dependency_failure", "rationale": "x"}]))
        self.assertEqual(env.cli("finalize", "--decisions", str(dec)), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "confirmed_dependency_failure", "rationale": "x",
                                    "proposal": {"evidence_ref": "delivery.csv#10"}}]))
        self.assertEqual(env.cli("finalize", "--decisions", str(dec)), 0)
        final = json.loads((env.root / "out" / "final.json").read_text())
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
