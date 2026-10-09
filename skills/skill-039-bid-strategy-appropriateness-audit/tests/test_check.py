"""test_check.py — decision boundaries of skill-039 scripts/check.py (legacy scope, first-page bids, verify).

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-039-bid-strategy-appropriateness-audit/tests
rules:   Temp folders only; stdlib only; never reads the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial tests
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

_SPEC = importlib.util.spec_from_file_location("skill039_check", Path(__file__).resolve().parents[1] / "scripts" / "check.py")
M = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = M
_SPEC.loader.exec_module(M)

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2",
           "rates_format": "fraction", "money_unit": "currency"}


def _write(root: Path, key: str, rows: list[dict]) -> None:
    path = root / f"{key}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Case:
    def __init__(self, test: unittest.TestCase, tables: dict, profile: dict | None = None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        tables = {"account": [ACCOUNT], **tables}
        for key, rows in tables.items():
            _write(self.export, key, rows)
        _write(self.export, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(profile or {"conversion_lag_days": 2}))
        self.out = self.root / "out"

    def main(self, *args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, list(args))

    def run(self) -> dict:
        assert self.main("run", "--export", str(self.export), "--profile", str(self.profile), "--out", str(self.out)) == 0
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions) -> tuple[int, dict]:
        p = self.root / "decisions.json"
        p.write_text(json.dumps(decisions))
        code = self.main("finalize", "--export", str(self.export), "--profile", str(self.profile), "--out",
                         str(self.out), "--decisions", str(p))
        return code, json.loads((self.out / "final.json").read_text())


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body):
    return sorted((f["condition_key"], f["severity"], f["entity"].get("keyword_id") or f["entity"].get("campaign_id"))
                  for f in body["findings"])


def camp(cid, stype="MANUAL_CPC", channel="SEARCH", cpa=""):
    return {"id": cid, "name": cid, "status": "ENABLED", "channel_type": channel, "bidding_strategy_type": stype,
            "target_cpa": cpa, "target_roas": ""}


def cfg(cid, legacy="enabled", channel="SEARCH", snapshot="2026-09-06", **kw):
    return {"campaign_id": cid, "snapshot_at": snapshot, "channel": channel, "subtype": "", "strategy_id": "",
            "strategy_type": "MANUAL_CPC", "standalone_target_cpa": "", "maximize_conversions_target_cpa": "",
            "effective_target_source": "", "legacy_ecpc_setting": legacy, "legacy_setting_source": "settings export",
            "source_ref": "cfg-1", **kw}


def notice(cid, channel="SEARCH", effective="2026-03-01", **kw):
    return {"campaign_id": cid, "constraint_id": "N1", "effective_date": "2026-01-01", "objective": "leads",
            "approved_max_cpc": "", "supported_state": "deprecated", "channel": channel, "subtype": "",
            "notice_effective_date": effective, "official_source_url": "https://support.google.example/notice",
            "applicable_strategy": "MAXIMIZE_CONVERSIONS;TARGET_CPA", "owner": "ops", "checked_at": "2026-09-05", **kw}


def bid(kid, kw_bid="", inherited="true", default="0.5", est="0.9", status="current", elig="eligible"):
    return {"campaign_id": "C1", "ad_group_id": "G1", "keyword_id": kid, "snapshot_at": "2026-09-06",
            "keyword_cpc_bid": kw_bid, "keyword_bid_is_inherited": inherited, "ad_group_default_cpc": default,
            "first_page_estimate": est, "estimate_at": "2026-09-05", "estimate_status": status,
            "eligibility_status": elig, "source_ref": "kw-export"}


class BidStrategyTests(unittest.TestCase):
    def test_legacy_flag_in_documented_scope_is_warning(self):
        body = Case(self, {"campaigns": [camp("C1")], "custom/bidding_configuration": [cfg("C1")],
                           "external/bidding_constraints": [notice("C1")]}).run()
        self.assertIn(("deprecated_setting_in_scope", "Warning", "C1"), keys(body))
        self.assertEqual(len([r for r in body["ai_review"] if r["condition_key"] == "legacy_migration_plan"]), 1)

    def test_legacy_flag_outside_channel_or_date_scope_is_info(self):
        for kw in ({"channel": "SHOPPING"}, {"effective": "2026-10-01"}):
            n = notice("C1", **kw)
            body = Case(self, {"campaigns": [camp("C1")], "custom/bidding_configuration": [cfg("C1")],
                               "external/bidding_constraints": [n]}).run()
            self.assertIn(("legacy_setting_scope_unverified", "Info", "C1"), keys(body))
            self.assertNotIn("Warning", [f["severity"] for f in body["findings"]])

    def test_absent_legacy_flag_is_unknown_not_a_finding(self):
        body = Case(self, {"campaigns": [camp("C1")], "custom/bidding_configuration": [cfg("C1", legacy="")],
                           "external/bidding_constraints": [notice("C1")]}).run()
        self.assertEqual([f for f in body["findings"] if f["check"] == "legacy_setting_scope"], [])
        self.assertEqual(cov(body, "legacy_setting_scope")["status"], "partial")

    def test_inherited_default_below_estimate_with_headroom(self):
        rows = [bid("K1"), bid("K2", default="1.0"), bid("K3", inherited="")]
        body = Case(self, {"campaigns": [camp("C1")], "custom/manual_keyword_bids": rows,
                           "external/bidding_constraints": [notice("C1", approved_max_cpc="1.2")]}).run()
        below = [k for k in keys(body) if k[0] == "bid_below_first_page_estimate"]
        self.assertEqual(below, [("bid_below_first_page_estimate", "Info", "K1")])  # K2 at/above estimate
        self.assertEqual(cov(body, "effective_keyword_bid")["status"], "partial")  # K3 inheritance unknown
        f = next(f for f in body["findings"] if f["condition_key"] == "bid_below_first_page_estimate")
        self.assertEqual(f["evidence"]["bid_source"], "ad_group_default_cpc (inherited)")

    def test_no_headroom_or_unknown_cap_is_not_a_finding(self):
        body = Case(self, {"campaigns": [camp("C1")], "custom/manual_keyword_bids": [bid("K1", est="2.0")],
                           "external/bidding_constraints": [notice("C1", approved_max_cpc="1.2")]}).run()
        self.assertNotIn("bid_below_first_page_estimate", [f["condition_key"] for f in body["findings"]])
        body = Case(self, {"campaigns": [camp("C1")], "custom/manual_keyword_bids": [bid("K1")]}).run()
        self.assertEqual([f for f in body["findings"] if f["check"] == "below_first_page_estimate"], [])
        self.assertEqual(cov(body, "below_first_page_estimate")["status"], "partial")

    def test_explicit_bid_above_approved_max_cpc(self):
        rows = [bid("K1", kw_bid="2.0", inherited="false"), bid("K2", kw_bid="1.1", inherited="false")]
        body = Case(self, {"campaigns": [camp("C1")], "custom/manual_keyword_bids": rows,
                           "external/bidding_constraints": [notice("C1", approved_max_cpc="1.2")]}).run()
        self.assertEqual([k for k in keys(body) if k[0] == "manual_bid_above_approved_max_cpc"],
                         [("manual_bid_above_approved_max_cpc", "Info", "K1")])

    def test_first_page_not_applicable_without_manual_search(self):
        body = Case(self, {"campaigns": [camp("C1", "TARGET_CPA", cpa="20")],
                           "custom/manual_keyword_bids": [bid("K1")]}).run()
        self.assertEqual(cov(body, "below_first_page_estimate")["status"], "not_applicable")

    def test_target_source_conflict(self):
        body = Case(self, {"campaigns": [camp("C1", "MAXIMIZE_CONVERSIONS", cpa="20")],
                           "custom/bidding_configuration": [cfg("C1", legacy="", maximize_conversions_target_cpa="25")]}).run()
        self.assertIn(("target_source_conflict", "Info", "C1"), keys(body))

    def test_critical_value_failure_requires_evidence_ref(self):
        profile = {"conversion_lag_days": 2, "campaign_objectives": {"C1": {"goal_ids": ["A1"], "role": "sales"}}}
        tables = {"campaigns": [camp("C1", "TARGET_ROAS")],
                  "conversion_actions": [{"id": "A1", "name": "Purchase", "category": "PURCHASE", "status": "ENABLED",
                                          "value_settings": "0", "last_conversion_date": "2026-08-29"}]}
        case = Case(self, tables, profile)
        body = case.run()
        item = next(r for r in body["ai_review"] if r["condition_key"] == "value_goal_configuration")
        code, _ = case.finalize([{"id": item["id"], "outcome": "material_config_failure", "rationale": "zero values"}])
        self.assertEqual(code, 4)
        code, final = case.finalize([{"id": item["id"], "outcome": "material_config_failure", "rationale": "zero values",
                                      "proposal": {"evidence_ref": "diag-7"}}])
        self.assertEqual(code, 0)
        self.assertIn(("value_goal_configuration", "Critical", "C1"), keys(final))

    def test_verify_caps_bid_and_migration_replacement(self):
        case = Case(self, {"campaigns": [camp("C1")], "custom/bidding_configuration": [cfg("C1")],
                           "custom/manual_keyword_bids": [bid("K1")],
                           "external/bidding_constraints": [notice("C1", approved_max_cpc="1.2")]})
        body = case.run()
        fp = next(r for r in body["ai_review"] if r["condition_key"] == "first_page_bid_relevance")
        mig = next(r for r in body["ai_review"] if r["condition_key"] == "legacy_migration_plan")
        code, final = case.finalize([
            {"id": fp["id"], "outcome": "relevant_with_headroom", "rationale": "r", "proposal": {"proposed_bid": 1.5}},
            {"id": mig["id"], "outcome": "supported_replacement", "rationale": "r",
             "proposal": {"replacement": "MAXIMIZE_CONVERSION_VALUE", "rollback": "CPA +20%"}}])
        self.assertEqual(code, 4)
        self.assertEqual({x["status"] for x in final["review_log"]}, {"rejected"})
        code, final = case.finalize([
            {"id": fp["id"], "outcome": "relevant_with_headroom", "rationale": "r", "proposal": {"proposed_bid": 1.0}},
            {"id": mig["id"], "outcome": "supported_replacement", "rationale": "r",
             "proposal": {"replacement": "TARGET_CPA", "rollback": "CPA +20% for 14 days"}}])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
