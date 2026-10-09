"""test_check.py — skill-090 decision boundaries: joins, permission gate, refresh SLA, absence, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-090-pmax-audience-signal-configuration/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
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

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check090", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check090"] = mod
_spec.loader.exec_module(mod)

PERM_OK = {"source_id": "S_CRM", "list_id": "", "market": "IT", "intended_use": "pmax_signal",
           "permission_status": "approved", "consent_coverage_status": "covered",
           "permitted_destinations": "Google Ads; Email", "restricted_data_review": "passed",
           "policy_eligibility": "eligible", "retention_limit_days": "540", "evidence_reference": "dpo-2026-07"}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def build(root: Path, *, signals=None, groups=None, definitions=None, permissions=None, intent=None,
          incomplete=(), drop=(), campaigns=None, components=None, market=("IT",)) -> tuple[Path, Path]:
    ex = root / "export"
    tables = {
        "account.csv": [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                         "date_range_end": "2026-08-31", "snapshot_date": "2026-09-05", "conversion_lag_days": 2}],
        "campaigns.csv": campaigns or [{"id": "P1", "status": "ENABLED", "channel_type": "PERFORMANCE_MAX"},
                                       {"id": "S1", "status": "ENABLED", "channel_type": "SEARCH"}],
        "custom/pmax_groups.csv": groups or [
            {"campaign_id": "P1", "asset_group_id": "G1", "name": "Boots", "status": "ENABLED", "theme": "hiking boots"},
            {"campaign_id": "P1", "asset_group_id": "G2", "name": "Tents", "status": "ENABLED", "theme": "tents"}],
        "custom/pmax_signals.csv": signals or [
            {"campaign_id": "P1", "asset_group_id": "G1", "signal_id": "sig1", "signal_type": "AUDIENCE",
             "audience_resource_id": "aud1", "search_theme_text": "", "status": "ENABLED"},
            {"campaign_id": "P1", "asset_group_id": "G1", "signal_id": "sig2", "signal_type": "SEARCH_THEME",
             "audience_resource_id": "", "search_theme_text": "waterproof boots", "status": "ENABLED"}],
        "custom/pmax_audience_components.csv": components or [
            {"audience_resource_id": "aud1", "component_id": "c1", "component_type": "USER_LIST", "user_list_id": "L1",
             "custom_segment_id": "", "inclusion_exclusion": "INCLUDE", "combination_operator": "AND",
             "definition_text": "crm purchasers"},
            {"audience_resource_id": "aud1", "component_id": "c2", "component_type": "IN_MARKET", "user_list_id": "",
             "custom_segment_id": "", "inclusion_exclusion": "INCLUDE", "combination_operator": "AND",
             "definition_text": "outdoor gear"}],
        "external/audience_definitions.csv": definitions or [
            {"list_id": "L1", "source_id": "S_CRM", "source_platform": "customer_match",
             "definition_expression": "purchasers 540d", "linkage_status": "linked",
             "eligibility_by_network": "search:eligible;display:eligible", "last_successful_refresh_at": "2026-09-01",
             "evidence_reference": "crm-def-1"},
            {"list_id": "L2", "source_id": "S_WEB", "source_platform": "website", "definition_expression": "visitors",
             "linkage_status": "linked", "eligibility_by_network": "display:eligible",
             "last_successful_refresh_at": "2026-09-04", "evidence_reference": "web-def-1"}],
        "external/activation_permissions.csv": permissions if permissions is not None else [
            PERM_OK, dict(PERM_OK, source_id="S_WEB", list_id="L2", evidence_reference="dpo-web")],
        "external/pmax_signal_intent.csv": intent or [
            {"asset_group_id": "G1", "signal_role": "prospecting", "business_segment": "hikers",
             "desired_characteristics": "outdoor buyers", "permitted_source_ids": "S_CRM;S_WEB",
             "source_offer_fit": "high", "refresh_sla_days": "7", "owner": "crm"}],
    }
    for name in drop:
        tables.pop(name)
    for name, rows in tables.items():
        _write(ex / name, rows)
    _write(ex / "table_manifest.csv", [{"filename": n, "completeness": "partial" if n in incomplete else "complete",
                                        "truncation": "none"} for n in tables])
    p = root / "profile.json"
    p.write_text(json.dumps({"market": list(market)}))
    return ex, p


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c["status"] for c in body["coverage"]}


def found(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def obs(body: dict, check: str) -> list[dict]:
    return [o for o in body["observations"] if o["check"] == check]


def cli(args: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args)


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_healthy_intended_signal_has_no_defect_and_counts_kinds(self):
        body = run(*build(self.root))
        self.assertEqual(body["counts"], {"Critical": 0, "Warning": 0, "Info": 0})
        g1 = [o["data"] for o in obs(body, "signal_inventory") if o["data"].get("asset_group_id") == "G1"][0]
        self.assertEqual((g1["audience_signals"], g1["search_themes"]), (1, 1))
        self.assertEqual(g1["constituent_list_ids"], ["L1"])
        self.assertEqual(cov(body)["signal_inventory"], "completed")
        self.assertEqual(cov(body)["eligibility_refresh"], "completed")
        # zero-signal G2 is an optional-absence observation, not a finding
        self.assertTrue(any(o["data"].get("asset_group_id") == "G2" for o in obs(body, "optional_absence")))
        classes = [o["data"] for o in obs(body, "signal_classification") if o["data"].get("asset_group_id") == "G1"][0]
        self.assertEqual(classes["classes"], ["customer_match", "interest"])

    def test_unresolved_audience_reference_is_gap_not_finding(self):
        sig = [{"campaign_id": "P1", "asset_group_id": "G1", "signal_id": "sig9", "signal_type": "AUDIENCE",
                "audience_resource_id": "aud9", "search_theme_text": "", "status": "ENABLED"}]
        body = run(*build(self.root, signals=sig))
        self.assertEqual(cov(body)["signal_inventory"], "partial")
        self.assertEqual(body["findings"], [])
        refs = [o["data"]["references"] for o in obs(body, "signal_inventory") if "references" in o["data"]]
        self.assertEqual(refs, [["G1:aud9"]])
        self.assertEqual(cov(body)["optional_absence"], "partial")

    def test_zero_signal_group_unprovable_without_complete_signal_manifest(self):
        body = run(*build(self.root, incomplete=("custom/pmax_signals.csv",)))
        self.assertEqual(cov(body)["optional_absence"], "partial")
        self.assertFalse(any(o["data"].get("asset_group_id") == "G2" for o in obs(body, "optional_absence")))

    def test_permission_unknown_blocks_and_is_info(self):
        body = run(*build(self.root, permissions=[dict(PERM_OK, consent_coverage_status="")]))
        f = found(body, "permission_unknown")
        self.assertEqual([(x["severity"], x["entity"]["list_id"]) for x in f], [("Info", "L1")])
        self.assertIn("consent_coverage_status=unknown", f[0]["evidence"]["reasons"])
        # blocked source is not an experiment candidate
        self.assertFalse(any(r["check"] == "signal_experiment" and
                             any(c["source_id"] == "S_CRM" for g in r["evidence"]["groups"] for c in g["candidates"])
                             for r in body["ai_review"]))

    def test_missing_permission_file_skips_gate_never_passes(self):
        body = run(*build(self.root, drop=("external/activation_permissions.csv",)))
        self.assertEqual(cov(body)["activation_permission_gate"], "skipped")
        self.assertEqual(cov(body)["signal_experiment"], "skipped")
        self.assertEqual(found(body, "permission_unknown"), [])

    def test_market_mismatch_row_does_not_approve(self):
        body = run(*build(self.root, permissions=[dict(PERM_OK, market="DE")]))
        self.assertEqual(len(found(body, "permission_unknown")), 1)

    def test_list_specific_row_overrides_source_row(self):
        perms = [PERM_OK, dict(PERM_OK, list_id="L1", permission_status="revoked")]
        body = run(*build(self.root, permissions=perms))
        self.assertEqual([x["severity"] for x in found(body, "unsafe_first_party_use")], ["Info"])
        item = [r for r in body["ai_review"] if r["condition_key"] == "unsafe_first_party_use"][0]
        self.assertEqual(item["outcomes"]["unsafe_use_confirmed"]["severity"], "Critical")

    def test_destination_not_permitted_on_active_signal_goes_to_review(self):
        body = run(*build(self.root, permissions=[dict(PERM_OK, permitted_destinations="Meta; Email")]))
        self.assertEqual(found(body, "unsafe_first_party_use")[0]["evidence"]["state"], "destination_not_permitted")

    def test_denied_list_in_paused_group_is_not_unsafe_use(self):
        groups = [{"campaign_id": "P1", "asset_group_id": "G1", "status": "PAUSED", "theme": "hiking boots"}]
        body = run(*build(self.root, groups=groups, permissions=[dict(PERM_OK, permission_status="denied")]))
        self.assertEqual(found(body, "unsafe_first_party_use"), [])
        self.assertEqual([r for r in body["ai_review"] if r["condition_key"] == "unsafe_first_party_use"], [])

    def _defs(self, **kw):
        base = {"list_id": "L1", "source_id": "S_CRM", "source_platform": "customer_match", "linkage_status": "linked",
                "eligibility_by_network": "search:eligible", "last_successful_refresh_at": "2026-09-01",
                "definition_expression": "x", "evidence_reference": "d"}
        return [dict(base, **kw)]

    def test_refresh_sla_boundary(self):
        at_sla = run(*build(self.root / "a", definitions=self._defs(last_successful_refresh_at="2026-08-29")))
        self.assertEqual(found(at_sla, "stale_refresh_sla"), [])
        stale = run(*build(self.root / "b", definitions=self._defs(last_successful_refresh_at="2026-08-28")))
        f = found(stale, "stale_refresh_sla")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual((f[0]["calculation"]["age_days"], f[0]["calculation"]["refresh_sla_days"]), (8, 7))

    def test_lenient_sla_used_when_roles_differ(self):
        intent = [{"asset_group_id": "G1", "signal_role": "a", "permitted_source_ids": "S_CRM", "refresh_sla_days": "7"},
                  {"asset_group_id": "G1", "signal_role": "b", "permitted_source_ids": "S_CRM", "refresh_sla_days": "30"}]
        body = run(*build(self.root, intent=intent, definitions=self._defs(last_successful_refresh_at="2026-08-20")))
        self.assertEqual(found(body, "stale_refresh_sla"), [])

    def test_missing_refresh_evidence_is_info_not_stale(self):
        body = run(*build(self.root, definitions=self._defs(last_successful_refresh_at="")))
        self.assertEqual([x["severity"] for x in found(body, "missing_refresh_evidence")], ["Info"])
        self.assertEqual(found(body, "stale_refresh_sla"), [])

    def test_broken_linkage_and_all_network_ineligibility_warn(self):
        body = run(*build(self.root, definitions=self._defs(linkage_status="failed",
                                                            eligibility_by_network="search:ineligible;display:ineligible")))
        self.assertEqual(len(found(body, "broken_linkage")), 1)
        self.assertEqual(len(found(body, "ineligible_all_networks")), 1)

    def test_partial_network_eligibility_is_not_a_warning(self):
        body = run(*build(self.root / "a", definitions=self._defs(eligibility_by_network="search:ineligible;display:eligible")))
        self.assertEqual(found(body, "ineligible_all_networks"), [])
        self.assertEqual(found(body, "unverified_eligibility"), [])
        unknown = run(*build(self.root / "b", definitions=self._defs(eligibility_by_network="")))
        self.assertEqual([x["severity"] for x in found(unknown, "unverified_eligibility")], ["Info"])

    def test_source_outside_intent_is_not_an_intended_signal(self):
        intent = [{"asset_group_id": "G1", "signal_role": "a", "permitted_source_ids": "S_WEB", "refresh_sla_days": "7"}]
        body = run(*build(self.root, intent=intent, definitions=self._defs(linkage_status="broken")))
        self.assertEqual(found(body, "broken_linkage"), [])

    def test_alternative_columns_accepted(self):
        comps = [{"audience_resource_id": "aud1", "component_id": "c1", "component_type": "USER_LIST",
                  "user_list_id": "L1", "custom_segment_id": "", "inclusion": "INCLUDE", "combination_operator": "AND",
                  "definition_text": "crm"}]
        intent = [{"asset_group_id": "G1", "signal_role": "a", "permitted_source_ids": "S_CRM", "refresh_SLA_days": "3"}]
        camps = [{"campaign_id": "P1", "status": "ENABLED", "channel_type": "performance max"}]
        body = run(*build(self.root, components=comps, intent=intent, campaigns=camps))
        self.assertEqual(cov(body)["signal_classification"], "completed")
        self.assertEqual(len(found(body, "stale_refresh_sla")), 1)

    def test_no_pmax_campaign_is_not_applicable(self):
        body = run(*build(self.root, campaigns=[{"id": "S1", "status": "ENABLED", "channel_type": "SEARCH"}]))
        self.assertEqual(set(cov(body).values()), {"not_applicable"})

    def test_finalize_unsafe_critical_requires_evidence_ref(self):
        ex, prof = build(self.root, permissions=[dict(PERM_OK, permission_status="revoked")])
        out = self.root / "out"
        self.assertEqual(cli(["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        item = [r for r in json.loads((out / "result.json").read_text())["ai_review"]
                if r["condition_key"] == "unsafe_first_party_use"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "unsafe_use_confirmed", "rationale": "x"}]))
        self.assertEqual(cli(args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "unsafe_use_confirmed", "rationale": "x",
                                    "proposal": {"evidence_ref": "dpo-2026-07"}}]))
        self.assertEqual(cli(args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "unsafe_first_party_use"],
                         ["Critical"])

    def test_finalize_experiment_needs_authorized_permitted_source(self):
        perms = [PERM_OK, dict(PERM_OK, source_id="S_WEB", list_id="L2"),
                 dict(PERM_OK, source_id="S_OTHER", list_id="L3")]
        ex, prof = build(self.root, permissions=perms)
        out = self.root / "out"
        self.assertEqual(cli(["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        item = [r for r in json.loads((out / "result.json").read_text())["ai_review"]
                if r["condition_key"] == "signal_experiment"][0]
        sources = {c["source_id"] for g in item["evidence"]["groups"] for c in g["candidates"]}
        self.assertEqual(sources, {"S_CRM", "S_WEB"})
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out), "--decisions", str(dec)]
        for exp, code in (({"asset_group_id": "G1", "source_id": "S_OTHER", "list_id": "L3"}, 4),
                          ({"asset_group_id": "G2", "list_id": "L2"}, 4),
                          ({"asset_group_id": "G1", "list_id": "L2"}, 0)):
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "experiment_proposed", "rationale": "x",
                                        "proposal": {"experiments": [exp]}}]))
            self.assertEqual(cli(args), code, exp)


if __name__ == "__main__":
    unittest.main()
