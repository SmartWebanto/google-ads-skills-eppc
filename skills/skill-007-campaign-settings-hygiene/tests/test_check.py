"""test_check.py — skill-007 decision boundaries: requirement windows, unknown settings, geo area, delivery blockage.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-007-campaign-settings-hygiene/tests -t skills/skill-007-campaign-settings-hygiene
rules:   Synthetic temp exports only; never reads the self-test oracle; asserts entities/severities/coverage, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | CodeDNA header
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | tests for this session's check changes
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_skill_007", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "111-111-1111", "currency_code": "EUR", "date_range_start": "2026-08-04",
           "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def build(test, tables, profile=None, account=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    export = root / "export"
    tables = {"account": [account or ACCOUNT], **tables}
    for key, rows in tables.items():
        _write(export / f"{key}.csv", rows)
    _write(export / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete", "truncation": "none"}
                                           for k in tables])
    prof = root / "profile.json"
    prof.write_text(json.dumps(profile or {}))
    return root, export, prof


def run(test, tables, profile=None, account=None):
    _, export, prof = build(test, tables, profile, account)
    return cli.run_once(M.SKILL, M.VERSION, M.run, export, prof).finish()


def finalize(test, tables, profile, choose):
    root, export, prof = build(test, tables, profile)
    out = root / "out"
    base = ["--export", str(export), "--profile", str(prof), "--out", str(out)]
    with contextlib.redirect_stdout(io.StringIO()):
        test.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + base), 0)
    dec = root / "decisions.json"
    dec.write_text(json.dumps(choose(json.loads((out / "result.json").read_text()))))
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + base + ["--decisions", str(dec)])
    return code, json.loads((out / "final.json").read_text())


def F(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


def R(body, key):
    return [r for r in body["ai_review"] if r["condition_key"] == key]


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)



REQ = "external/campaign_requirements"


def camp(cid="1", **kw):
    row = {"id": cid, "name": f"C{cid}", "status": "ENABLED", "channel_type": "SEARCH", "bidding_strategy_type": "TARGET_CPA",
           "start_date": "2026-01-01", "end_date": "", "search_partners": "false", "display_network": "false",
           "geo_targets": "Italy", "geo_target_method": "PRESENCE", "languages": "it", "ad_schedule": "all",}
    row.update(kw)
    return row


def req(rtype, value, cid="1", start="2026-01-01", end="2026-12-31"):
    return {"account_id": "111-111-1111", "campaign_id": cid, "requirement_type": rtype, "approved_value": value,
            "effective_start": start, "effective_end": end, "approval_ref": "brief-1", "owner": "ops"}


PROFILE = {"service_area": ["Italy"]}


class SettingsHygiene(unittest.TestCase):
    def test_enabled_campaign_with_past_end_date_is_info_with_revival_guard(self):
        body = run(self, {"campaigns": [camp(end_date="2026-08-31"), camp("2", status="PAUSED", end_date="2026-08-01")]}, PROFILE)
        self.assertEqual([f["entity"]["campaign_id"] for f in F(body, "expired_end_date")], ["1"])
        self.assertEqual([r["entity"]["campaign_id"] for r in R(body, "promotion_revival")], ["1"])
        body = run(self, {"campaigns": [camp(end_date="2026-09-30")]}, PROFILE)
        self.assertEqual(F(body, "expired_end_date"), [])

    def test_missing_end_date_column_is_skipped_not_passed(self):
        c = camp()
        del c["end_date"]
        body = run(self, {"campaigns": [c]}, PROFILE)
        self.assertEqual(cov(body, "date_window")["status"], "skipped")
        self.assertIn("campaigns:end_date", cov(body, "date_window")["missing"])

    def test_explicit_requirement_conflicts_are_warnings_only_inside_window(self):
        reqs = [req("geo_target_method", "PRESENCE"), req("search_partners", "false"), req("language", "it;de")]
        body = run(self, {"campaigns": [camp(geo_target_method="PRESENCE_OR_INTEREST", search_partners="true")], REQ: reqs},
                   PROFILE)
        controls = sorted(f["entity"]["control"] for f in F(body, "setting_conflicts_requirement"))
        self.assertEqual(controls, ["geo_target_method", "languages", "search_partners"])
        old = [req("geo_target_method", "PRESENCE", end="2026-06-30")]
        body = run(self, {"campaigns": [camp(geo_target_method="PRESENCE_OR_INTEREST")], REQ: old}, PROFILE)
        self.assertEqual(F(body, "setting_conflicts_requirement"), [])
        self.assertEqual([f["severity"] for f in F(body, "presence_or_interest")], ["Info"])

    def test_worldwide_outside_service_area_is_warning_subregion_is_review_empty_is_partial(self):
        body = run(self, {"campaigns": [camp(geo_targets="All countries and territories")]}, PROFILE)
        self.assertEqual([f["severity"] for f in F(body, "geo_outside_approved_area")], ["Warning"])
        body = run(self, {"campaigns": [camp(geo_targets="Milan")]}, PROFILE)
        self.assertEqual(F(body, "geo_outside_approved_area"), [])
        self.assertEqual(len(R(body, "geo_outside_approved_area")), 1)
        body = run(self, {"campaigns": [camp(geo_targets="")]}, PROFILE)
        self.assertEqual(cov(body, "geo_targeting")["status"], "partial")
        self.assertEqual(body["counts"]["Warning"], 0)

    def test_unknown_language_cell_is_not_no_languages(self):
        body = run(self, {"campaigns": [camp(languages="")], REQ: [req("language", "it")]}, PROFILE)
        self.assertEqual(F(body, "setting_conflicts_requirement"), [])
        self.assertEqual(cov(body, "languages")["status"], "partial")

    def test_device_exclusion_info_requirement_warning_smart_modifier_observed(self):
        adj = [{"campaign_id": "1", "dimension": "DEVICE", "segment_value": "TABLET", "modifier": "-1"},
               {"campaign_id": "1", "dimension": "DEVICE", "segment_value": "MOBILE", "modifier": "0.2"}]
        body = run(self, {"campaigns": [camp()], "bid_adjustments": adj}, PROFILE)
        self.assertEqual([f["entity"]["control"] for f in F(body, "device_exclusion")], ["device:TABLET"])
        self.assertTrue(any("MOBILE CPC modifier" in o["text"] for o in body["observations"]))
        body = run(self, {"campaigns": [camp()], "bid_adjustments": adj, REQ: [req("device", "TABLET")]}, PROFILE)
        self.assertEqual([f["entity"]["control"] for f in F(body, "setting_conflicts_requirement")], ["device:TABLET"])

    def test_blocked_required_delivery_critical_only_with_evidence_ref(self):
        t = {"campaigns": [camp(end_date="2026-08-31")], REQ: [req("required_delivery", "active")]}
        body = run(self, t, PROFILE)
        self.assertEqual([f["severity"] for f in F(body, "required_delivery_blocked")], ["Warning"])
        self.assertEqual(body["counts"]["Critical"], 0)
        pick = lambda prop: (lambda body: [{"id": R(body, "required_delivery_blocked")[0]["id"],
                                            "outcome": "material_blockage_evidenced", "rationale": "orders lost",
                                            "proposal": prop}])
        self.assertEqual(finalize(self, t, PROFILE, pick({}))[0], 4)
        code, final = finalize(self, t, PROFILE, pick({"evidence_ref": "orders-report"}))
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Critical"], 1)

    def test_revival_never_removes_end_date(self):
        t = {"campaigns": [camp(end_date="2026-08-31")]}
        pick = lambda prop: (lambda body: [{"id": R(body, "promotion_revival")[0]["id"], "outcome": "revival_confirmed",
                                            "rationale": "owner", "proposal": prop}])
        full = {"approval_ref": "a", "new_start": "2026-09-10", "new_end": "2026-10-10", "budget": 30, "creative_confirmed": True}
        self.assertEqual(finalize(self, t, PROFILE, pick(dict(full, action="remove_end_date")))[0], 4)
        self.assertEqual(finalize(self, t, PROFILE, pick({"approval_ref": "a"}))[0], 4)
        self.assertEqual(finalize(self, t, PROFILE, pick(full))[0], 0)


if __name__ == "__main__":
    unittest.main()
