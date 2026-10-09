"""test_check.py — skill-006 decision boundaries: approved Search-only intent, CONTENT share, zero-conversion gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-006-display-network-optin/tests -t skills/skill-006-display-network-optin
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
_spec = importlib.util.spec_from_file_location("check_skill_006", SCRIPT)
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



ND = "custom/network_daily"


def nd(cid, net, clicks, cost, conv, date="2026-08-10"):
    return {"campaign_id": cid, "date": date, "ad_network_type": net, "impressions": clicks * 10, "clicks": clicks,
            "cost": cost, "conversions": conv, "conversion_value": 0, "goal_scope": "all",
            "conversion_date_basis": "interaction_date"}


def camp(cid, optin="true", ch="SEARCH"):
    return {"id": cid, "name": f"C{cid}", "status": "ENABLED", "channel_type": ch, "display_network": optin}


def tables(camps, rows=None, extra=None):
    t = {"campaigns": camps}
    if rows is not None:
        t[ND] = rows
        t["campaign_metrics"] = [{"campaign_id": c["id"], "cost": sum(r["cost"] for r in rows if r["campaign_id"] == c["id"])}
                                 for c in camps]
    t.update(extra or {})
    return t


class DisplayOptIn(unittest.TestCase):
    def test_search_only_requirement_with_optin_is_warning(self):
        body = run(self, tables([camp("1")]), {"campaign_objectives": {"1": {"search_only": True}}})
        self.assertEqual([f["severity"] for f in F(body, "optin_contradicts_search_only")], ["Warning"])
        body = run(self, tables([camp("1", optin="false")]), {"campaign_objectives": {"1": {"search_only": True}}})
        self.assertEqual(body["findings"], [])

    def test_unknown_intent_gives_provisional_info_and_review(self):
        body = run(self, tables([camp("1"), camp("2", ch="DISPLAY")]))
        self.assertEqual([f["entity"]["campaign_id"] for f in F(body, "optin_enabled_intent_unknown")], ["1"])
        rv = R(body, "optin_contradicts_search_only")
        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0]["outcomes"]["search_only_required"]["severity"], "Warning")

    def test_unknown_setting_is_partial_not_disabled(self):
        body = run(self, tables([camp("1", optin="")]))
        self.assertEqual(cov(body, "optin_inventory")["status"], "partial")
        self.assertEqual(body["findings"], [])

    def test_content_share_above_5_percent_is_info(self):
        rows = [nd("1", "SEARCH", 900, 900, 30), nd("1", "CONTENT", 300, 100, 2)]
        body = run(self, tables([camp("1")], rows), {"campaign_objectives": {"1": {"search_only": False}}})
        f = F(body, "content_spend_share")
        self.assertEqual(len(f), 1)
        self.assertAlmostEqual(f[0]["evidence"]["content_share"], 0.1)
        rows = [nd("1", "SEARCH", 900, 1000, 30), nd("1", "CONTENT", 300, 50, 2)]
        body = run(self, tables([camp("1")], rows), {"campaign_objectives": {"1": {"search_only": False}}})
        self.assertEqual(F(body, "content_spend_share"), [])

    def test_missing_content_metrics_skip_spend_checks(self):
        body = run(self, tables([camp("1")]))
        for c in ("network_scope", "content_share", "content_zero_conversions"):
            self.assertEqual(cov(body, c)["status"], "skipped")

    def test_zero_content_conversions_gated_by_tracking_and_maturity(self):
        rows = [nd("1", "SEARCH", 900, 900, 30), nd("1", "CONTENT", 300, 80, 0)]
        prof = {"campaign_objectives": {"1": {"search_only": False, "goal_ids": ["g"]}}}
        ca = {"conversion_actions": [{"id": "g", "name": "Lead", "category": "LEAD", "status": "ENABLED",
                                      "last_conversion_date": "2026-09-01"}]}
        body = run(self, tables([camp("1")], rows, ca), prof)
        self.assertEqual(len(R(body, "content_zero_conversions")), 1)
        body = run(self, tables([camp("1")], rows), prof)
        self.assertEqual(R(body, "content_zero_conversions"), [])
        body = run(self, tables([camp("1")], rows, ca), prof, account=dict(ACCOUNT, snapshot_date="2026-09-02"))
        self.assertEqual(R(body, "content_zero_conversions"), [])

    def test_finalize_search_only_outcome_requires_evidence_ref(self):
        pick = lambda prop: (lambda body: [{"id": R(body, "optin_contradicts_search_only")[0]["id"],
                                            "outcome": "search_only_required", "rationale": "brief", "proposal": prop}])
        self.assertEqual(finalize(self, tables([camp("1")]), {}, pick({}))[0], 4)
        code, final = finalize(self, tables([camp("1")]), {}, pick({"evidence_ref": "brief-2026"}))
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in F(final, "optin_contradicts_search_only")], ["Warning"])
        self.assertEqual(F(final, "optin_enabled_intent_unknown"), [])


if __name__ == "__main__":
    unittest.main()
