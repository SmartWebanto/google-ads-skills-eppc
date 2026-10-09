"""test_check.py — skill-061 Customer Match freshness, sync and authorization decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-061-customer-match-list-health/tests
rules:   stdlib only; temp folders; synthetic sanitized aggregates only (no PII); asserts decisions, not wording.
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
_spec = importlib.util.spec_from_file_location("check_061", SCRIPT)
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

    def cli(self, cmd, *extra) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                            [cmd, "--export", str(self.exp), "--profile", str(self.root / "profile.json"),
                             "--out", str(self.root / "out"), *extra])

    def run(self) -> dict:
        assert self.cli("run") == 0
        return json.loads((self.root / "out" / "result.json").read_text())


AUD_COLS = ["list_id", "campaign_id", "ad_group_id", "mode", "status"]


def status(lid="L1", eligible="true", account_ok="true"):
    return {"list_id": lid, "channel": "SEARCH", "snapshot_date": "2026-09-05", "list_type": "CRM_BASED",
            "membership_status": "OPEN", "membership_duration_days": 540, "reported_size": 12000,
            "size_precision": "exact", "eligible": eligible, "eligibility_reason": "", "account_use_eligible": account_ok,
            "match_rate": "", "match_rate_definition": "", "match_rate_available": "false"}


def job(jid, extract, st="SUCCESS", op="REPLACE", lid="L1"):
    return {"list_id": lid, "job_id": jid, "submitted_at": extract, "completed_at": extract, "status": st,
            "operation": op, "source_extract_at": extract, "submitted_count": 100, "accepted_count": 90,
            "rejected_count": 10, "error_category": "FORMAT" if st == "FAILED" else ""}


def policy(lid="L1", auth="AUTHORIZED", campaigns="10", refresh=30):
    return {"list_id": lid, "purpose": "retention", "intended_campaign_ids": campaigns, "authorized_use_status": auth,
            "aggregate_consent_evidence_ref": "consent-2026", "owner": "crm-team", "source": "intake",
            "reviewed_at": "2026-08-01", "required_refresh_days": refresh, "membership_rationale": "repeat buyers",
            "deletion_sync_required": "true", "data_scope": "customers"}


def env(test, jobs, st=None, pol=None, assoc=(("L1", "10"),)):
    return Env(test, {
        "account": [ACCOUNT],
        "campaigns": [{"id": "10", "status": "ENABLED", "channel_type": "SEARCH"},
                      {"id": "11", "status": "ENABLED", "channel_type": "SEARCH"}],
        "campaign_metrics": [{"campaign_id": "10", "impressions": 100, "cost": 20}],
        "audiences": [{"list_id": l, "campaign_id": c, "ad_group_id": "", "mode": "OBSERVATION", "status": "ENABLED"}
                      for l, c in assoc],
        "custom/customer_match_status": st or [status()],
        "external/customer_match_upload_history": jobs,
        "external/customer_match_policy": pol or [policy()]})


def conds(body, sev=None):
    return sorted(f["condition_key"] for f in body["findings"] if sev is None or f["severity"] == sev)


class CustomerMatchTests(unittest.TestCase):
    def test_refresh_age_vs_owner_cadence(self):
        self.assertEqual(conds(env(self, [job("j1", "2026-07-27")]).run(), "Warning"), ["refresh_beyond_cadence"])
        self.assertEqual(conds(env(self, [job("j1", "2026-08-06")]).run(), "Warning"), [])  # exactly 30 days

    def test_delta_is_labelled_and_counts_as_latest_success(self):
        body = env(self, [job("j1", "2026-07-01"), job("j2", "2026-08-20", op="ADD")]).run()
        obs = next(o for o in body["observations"] if o["check"] == "freshness")["data"]
        self.assertEqual((obs["last_operation"], obs["age_days"], obs["last_full_refresh_age_days"]), ("ADD", 16, 66))

    def test_no_successful_job_means_unknown_not_stale(self):
        body = env(self, [job("j1", "2026-06-01", st="PENDING")]).run()
        self.assertEqual(conds(body, "Warning"), [])

    def test_failed_latest_job_on_required_use(self):
        body = env(self, [job("j1", "2026-08-30"), job("j2", "2026-09-01", st="FAILED")]).run()
        self.assertEqual(conds(body, "Warning"), ["failed_required_sync"])
        body = env(self, [job("j1", "2026-09-01", st="FAILED"), job("j2", "2026-09-02")]).run()
        self.assertEqual(conds(body, "Warning"), [])

    def test_stale_list_without_active_use_is_not_warning(self):
        body = env(self, [job("j1", "2026-01-01")], assoc=()).run()
        self.assertEqual(conds(body, "Warning"), [])
        self.assertIn("unapplied_list", conds(body, "Info"))

    def test_platform_ineligible_active_association(self):
        body = env(self, [job("j1", "2026-09-01")], st=[status(account_ok="false")]).run()
        self.assertEqual(conds(body, "Warning"), ["active_association_ineligible"])
        body = env(self, [job("j1", "2026-09-01")], st=[status(), status("L1", eligible="false") | {"channel": "DISPLAY"}]).run()
        self.assertEqual(conds(body, "Warning"), [])

    def test_non_customer_match_lists_ignored(self):
        body = env(self, [job("j1", "2026-09-01")], assoc=(("L1", "10"), ("RMK", "10"))).run()
        self.assertNotIn("authorization_missing", conds(body))

    def test_activation_outside_authorization_needs_evidence_for_critical(self):
        e = env(self, [job("j1", "2026-09-01")], assoc=(("L1", "10"), ("L1", "11")))
        body = e.run()
        self.assertEqual(conds(body, "Info"), ["activation_outside_authorization"])
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "activation_outside_authorization")
        dec = e.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "confirmed_unauthorized", "rationale": "owner said no"}]))
        self.assertEqual(e.cli("finalize", "--decisions", str(dec)), 4)
        dec.write_text(json.dumps([{"id": rid, "outcome": "confirmed_unauthorized", "rationale": "owner said no",
                                    "proposal": {"evidence_ref": "intake-2026-08#L1"}}]))
        self.assertEqual(e.cli("finalize", "--decisions", str(dec)), 0)
        final = json.loads((e.root / "out" / "final.json").read_text())
        self.assertEqual(conds(final, "Critical"), ["activation_outside_authorization"])
        self.assertNotIn("activation_outside_authorization", conds(final, "Info"))

    def test_missing_policy_skips_freshness(self):
        e = Env(self, {"account": [ACCOUNT], "external/customer_match_upload_history": [job("j1", "2026-01-01")],
                       "custom/customer_match_status": [status()]})
        body = e.run()
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["freshness"], "skipped")
        self.assertEqual(conds(body, "Warning"), [])


if __name__ == "__main__":
    unittest.main()
