"""test_check.py — skill-119 decision boundaries: subscription status, attribution, authorization, coverage, outcomes.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-119-auto-applied-recommendations-review/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check119", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["check119"] = mod
_spec.loader.exec_module(mod)

SUB, MAN = "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION", "GOOGLE_ADS_RECOMMENDATIONS"
BUDGET = "campaign.campaign_budget.amount_micros"
TCPA = "campaign.maximize_conversions.target_cpa_micros"
ACCOUNT = {"customer_id": "111-222-3333", "currency_code": "EUR", "time_zone": "Europe/Rome",
           "date_range_start": "2026-08-04", "date_range_end": "2026-09-02", "snapshot_date": "2026-09-06",
           "rates_format": "fraction", "money_unit": "currency", "conversion_date_basis": "interaction_date",
           "conversion_lag_days": 2}
CAMPAIGNS = [{"id": "1001", "status": "ENABLED", "budget_id": "B1", "bidding_strategy_id": "S1"},
             {"id": "1002", "status": "ENABLED", "budget_id": "B2", "bidding_strategy_id": ""}]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def build(root: Path, files: dict, manifest: dict | None = None, unmanifested=()) -> Path:
    ex = root / "export"
    tables = {"account": [ACCOUNT], "campaigns": CAMPAIGNS, **files}
    for name, rows in tables.items():
        _write(ex / f"{name}.csv", rows)
    man = []
    for name in tables:
        if name in unmanifested:
            continue
        row = {"filename": f"{name}.csv", "completeness": "complete", "truncation": "none",
               "period_start": "2026-08-04", "period_end": "2026-09-02"}
        row.update((manifest or {}).get(name, {}))
        man.append(row)
    _write(ex / "table_manifest.csv", man)
    return ex


def sub(rt, subscribed, snap="2026-09-06 08:00", scope="account"):
    return {"recommendation_type": rt, "subscribed": subscribed, "scope": scope, "snapshot_at": snap,
            "source_screen": "Recommendations > Auto-apply"}


def chg(cid, field=BUDGET, new="60", when="2026-08-20 10:00:00", client=SUB, camp="1001", budget="B1",
        strategy="", old="50", ref="", res=None):
    return {"change_id": cid, "field_path": field, "occurred_at": when, "resource_name": res or f"customers/1/r/{camp}",
            "campaign_id": camp, "budget_id": budget, "strategy_id": strategy, "operation": "UPDATE",
            "client_type": client, "actor_id": "auto-apply" if client == SUB else "user@client", "old_value": old,
            "new_value": new, "approval_ref": ref}


def auth(ref="A1", type_="CAMPAIGN_BUDGET", scope="1001", fields=BUDGET, ranges=f"{BUDGET}=0..80",
         frm="2026-01-01", to="open", status="active"):
    return {"approval_ref": ref, "type": type_, "scope_id": scope, "allowed_fields": fields,
            "allowed_value_ranges": ranges, "effective_from": frm, "effective_to": to, "owner": "client-cmo",
            "status": status, "review_due": "2027-01-01", "reviewed_at": "2026-06-01"}


SUBS, CHG, AUTH, OUTC = ("custom/auto_apply_subscriptions", "custom/auto_apply_changes",
                         "external/auto_apply_authorizations", "custom/auto_apply_outcomes")


def outcomes(camp, first: date, last: date, clicks=30, immature_from: date | None = None, goal="5001"):
    rows, d = [], first
    while d <= last:
        rows.append({"campaign_id": camp, "date": d.isoformat(), "budget_id": "B1", "strategy_id": "S1",
                     "goal_id": goal, "impressions": 1000, "clicks": clicks, "cost": 50, "conversions": 3,
                     "conversion_value": 200, "conversion_date_basis": "interaction_date",
                     "maturity": "false" if immature_from and d >= immature_from else "true"})
        d += timedelta(days=1)
    return rows


def run(ex: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, None).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c for c in body["coverage"]}


def found(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def obs(body: dict, check: str, prefix: str) -> dict:
    return [o for o in body["observations"] if o["check"] == check and o["text"].startswith(prefix)][0]["data"]


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    # ---- missing evidence
    def test_missing_evidence_skips_every_check_with_exact_columns(self):
        body = run(build(self.root, {}))
        c = cov(body)
        self.assertEqual({k: v["status"] for k, v in c.items()},
                         {k: "skipped" for k in ("subscription_inventory", "change_sources", "subscription_authorization",
                                                 "change_authorization", "change_log_coverage", "outcome_comparison")})
        self.assertIn(f"{SUBS}:subscribed", c["subscription_inventory"]["missing"])
        self.assertIn(f"{AUTH}:allowed_value_ranges", c["change_authorization"]["missing"])
        self.assertIn(f"{OUTC}:maturity", c["outcome_comparison"]["missing"])
        self.assertEqual(body["findings"], [])

    def test_missing_column_skips_only_dependent_check(self):
        rows = [{k: v for k, v in chg("c1").items() if k != "new_value"}]
        body = run(build(self.root, {CHG: rows}))
        c = cov(body)
        self.assertEqual(c["change_sources"]["status"], "completed")
        self.assertEqual(c["change_authorization"]["status"], "skipped")
        self.assertIn(f"{CHG}:new_value", c["change_authorization"]["missing"])

    # ---- step 1
    def test_unknown_and_pending_settings_are_info_never_subscriptions(self):
        body = run(build(self.root, {SUBS: [sub("A", "false", "2026-08-01"), sub("A", "true"), sub("B", "false"),
                                           sub("C", "unknown"), sub("D", "pending"), sub("E", "true"),
                                           sub("E", "false")]}))
        m = obs(body, "subscription_inventory", "Auto-apply subscription inventory")
        self.assertEqual(m["subscribed"], ["A"])
        self.assertEqual(m["not_subscribed"], ["B"])
        self.assertEqual(m["pending"], ["D"])
        self.assertEqual(sorted(f["entity"]["recommendation_type"] for f in found(body, "unknown_subscription_setting")),
                         ["C", "E"])
        self.assertEqual([f["entity"]["recommendation_type"] for f in found(body, "pending_recommendation_only")], ["D"])
        self.assertTrue(all(f["severity"] == "Info" for f in body["findings"]))
        self.assertEqual(cov(body)["subscription_inventory"]["status"], "completed")

    def test_unmanifested_or_stale_settings_are_partial(self):
        body = run(build(self.root, {SUBS: [sub("A", "true")]}, unmanifested=(SUBS,)))
        self.assertEqual(cov(body)["subscription_inventory"]["status"], "partial")
        body = run(build(self.root, {SUBS: [sub("A", "true", "2026-08-01")]}))
        self.assertEqual(cov(body)["subscription_inventory"]["status"], "partial")

    # ---- step 2
    def test_distinct_change_ids_and_unknown_attribution(self):
        rows = [chg("c1"), chg("c1", field=TCPA), chg("c2", client=MAN), chg("c3", client="Google Ads web client"),
                chg("c4", client="OTHER"), chg("c5"), chg("c5", field=TCPA, client=MAN)]
        body = run(build(self.root, {CHG: rows}))
        o = obs(body, "change_sources", "Distinct change IDs")
        self.assertEqual((o["distinct_change_ids"], o["field_rows"]), (5, 7))
        self.assertEqual((o["subscription_applied"], o["manual_recommendation"], o["other_client"], o["unknown"]),
                         (1, 1, 1, 2))
        f = found(body, "unknown_change_attribution")
        self.assertEqual(f[0]["evidence"]["change_ids"], ["c4", "c5"])
        self.assertEqual(cov(body)["change_sources"]["status"], "partial")

    # ---- step 3b
    def _auth_run(self, changes, auths, manifest=None, extra=None):
        return run(build(self.root, {CHG: changes, AUTH: auths, **(extra or {})}, manifest))

    def test_field_outside_allowed_fields_is_warning_allowed_field_is_not(self):
        body = self._auth_run([chg("c1"), chg("c2", field=TCPA, new="25")], [auth()])
        w = found(body, "outside_documented_authorization")
        self.assertEqual([x["entity"]["change_id"] for x in w], ["c2"])
        self.assertEqual(w[0]["severity"], "Warning")
        crit = [r for r in body["ai_review"] if r["condition_key"] == "unauthorized_material_failure"]
        self.assertEqual([r["entity"]["change_id"] for r in crit], ["c2"])
        self.assertFalse(any(f["severity"] == "Critical" for f in body["findings"]))

    def test_value_range_boundary_is_inclusive(self):
        body = self._auth_run([chg("c1", new="80"), chg("c2", new="80.5")], [auth()])
        self.assertEqual([x["entity"]["change_id"] for x in found(body, "outside_documented_authorization")], ["c2"])

    def test_validity_window_and_status_at_change_time(self):
        auths = [auth(to="2026-08-10")]
        body = self._auth_run([chg("c1", when="2026-08-05 09:00"), chg("c2", when="2026-08-20 09:00")], auths)
        self.assertEqual([x["entity"]["change_id"] for x in found(body, "outside_documented_authorization")], ["c2"])
        body = run(build(self.root, {CHG: [chg("c1", when="2026-08-05 09:00")],
                                     AUTH: [auth(to="2026-08-10", status="revoked")]}))
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        body = run(build(self.root, {CHG: [chg("c1")], AUTH: [auth(status="draft")]}))
        self.assertEqual(len(found(body, "outside_documented_authorization")), 1)

    def test_scope_mismatch_account_scope_and_unplaceable_scope(self):
        body = self._auth_run([chg("c1")], [auth(scope="1002")])
        self.assertEqual(len(found(body, "outside_documented_authorization")), 1)
        body = run(build(self.root, {CHG: [chg("c1")], AUTH: [auth(scope="1112223333")]}))
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        body = run(build(self.root, {CHG: [chg("c1")], AUTH: [auth(scope="X9")]}))
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["change_authorization_undecidable"])

    def test_unparseable_range_is_review_not_warning(self):
        body = self._auth_run([chg("c1")], [auth(ranges=f"{BUDGET}=+20%")])
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        item = [r for r in body["ai_review"] if r["condition_key"] == "change_authorization_undecidable"][0]
        self.assertEqual(item["evidence"]["change_ids"], ["c1"])
        self.assertEqual(item["outcomes"]["some_outside"]["severity"], "Warning")

    def test_literal_value_set(self):
        body = self._auth_run([chg("c1", field="campaign.status", new="PAUSED"),
                               chg("c2", field="campaign.status", new="ENABLED")],
                              [auth(fields="campaign.*", ranges="campaign.status={ENABLED}")])
        self.assertEqual([x["entity"]["change_id"] for x in found(body, "outside_documented_authorization")], ["c1"])

    def test_complete_empty_register_leaves_changes_outside(self):
        ex = build(self.root, {CHG: [chg("c1")], AUTH: [auth()]})
        (ex / f"{AUTH}.csv").write_text(",".join(auth()) + "\n")
        body = run(ex)
        self.assertEqual(cov(body)["change_authorization"]["status"], "completed")
        self.assertEqual([x["entity"]["change_id"] for x in found(body, "outside_documented_authorization")], ["c1"])

    def test_manual_and_unknown_changes_are_not_judged(self):
        body = self._auth_run([chg("c1", field=TCPA, client=MAN), chg("c2", field=TCPA, client="UNKNOWN")], [auth()])
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        t = obs(body, "change_authorization", "Authorization comparison totals")
        self.assertEqual((t["manual_recommendation_not_compared"], t["unknown_attribution_not_compared"]), (1, 1))

    def test_incomplete_authorization_register_downgrades_to_info(self):
        body = self._auth_run([chg("c1", field=TCPA)], [auth()], manifest={AUTH: {"completeness": "partial"}})
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        info = found(body, "authorization_unconfirmed")
        self.assertEqual(info[0]["evidence"]["change_ids"], ["c1"])
        self.assertEqual(info[0]["severity"], "Info")
        self.assertEqual(cov(body)["change_authorization"]["status"], "partial")

    # ---- step 3a
    def test_subscribed_type_without_authorization_is_warning(self):
        files = {SUBS: [sub("CAMPAIGN_BUDGET", "true"), sub("KEYWORD", "true"), sub("TARGET_CPA_OPT_IN", "false")],
                 AUTH: [auth(scope="account")]}
        body = run(build(self.root, files))
        w = found(body, "outside_documented_authorization")
        self.assertEqual([x["entity"]["recommendation_type"] for x in w], ["KEYWORD"])
        files[AUTH] = [auth(scope="1001")]
        body = run(build(self.root / "narrow", files))
        self.assertEqual(sorted(x["entity"]["recommendation_type"] for x in found(body, "outside_documented_authorization")),
                         ["CAMPAIGN_BUDGET", "KEYWORD"])

    def test_disjoint_type_vocabulary_is_review_not_warning(self):
        body = run(build(self.root, {SUBS: [sub("KEYWORD", "true")], AUTH: [auth(type_="campaign", scope="account")]}))
        self.assertEqual(found(body, "outside_documented_authorization"), [])
        self.assertEqual(cov(body)["subscription_authorization"]["status"], "partial")
        self.assertIn("subscription_authorization_undecidable", [r["condition_key"] for r in body["ai_review"]])

    # ---- step 4
    def test_complete_window_count_excludes_out_of_window_changes(self):
        body = run(build(self.root, {CHG: [chg("c1"), chg("c1", field=TCPA), chg("c2", when="2026-07-01 10:00")]}))
        o = obs(body, "change_log_coverage", "Distinct change IDs in the declared")
        self.assertEqual((o["count_basis"], o["distinct_change_ids"], o["excluded_outside_window"]),
                         ("complete_30_day_count", 1, 1))
        self.assertEqual(found(body, "incomplete_change_log"), [])
        self.assertEqual(cov(body)["change_log_coverage"]["status"], "completed")

    def test_retained_subset_or_truncation_is_lower_bound_info(self):
        rows = [chg("c1", when="2026-08-10 10:00"), chg("c2", when="2026-08-25 10:00")]
        body = run(build(self.root, {CHG: rows}, {CHG: {"period_start": "2026-08-20"}}))
        o = obs(body, "change_log_coverage", "Distinct change IDs in the declared")
        self.assertEqual((o["count_basis"], o["distinct_change_ids"]), ("covered_window_count", 1))
        self.assertEqual(found(body, "incomplete_change_log")[0]["severity"], "Info")
        body = run(build(self.root / "t", {CHG: rows}, {CHG: {"truncation": "row limit 10000"}}))
        self.assertEqual(len(found(body, "incomplete_change_log")), 1)
        self.assertEqual(cov(body)["change_log_coverage"]["status"], "partial")

    # ---- step 5
    def _outcome_body(self, changes, out_rows):
        return run(build(self.root, {CHG: changes, OUTC: out_rows}))

    def test_matched_windows_and_both_side_gates(self):
        d = date(2026, 8, 20)
        body = self._outcome_body([chg("c1")], outcomes("1001", d - timedelta(days=10), d + timedelta(days=10)))
        rec = obs(body, "outcome_comparison", "Change c1")
        self.assertEqual(rec["days_per_side"], 10)
        self.assertTrue(rec["metrics"]["cvr"]["passed"])
        self.assertAlmostEqual(rec["metrics"]["cvr"]["pre"], 0.1)
        self.assertTrue(rec["metrics"]["cpa"]["passed"])
        self.assertAlmostEqual(rec["metrics"]["cpa"]["pre"], 500 / 30, places=5)
        self.assertEqual(body["findings"], [])

    def test_low_click_side_blocks_cvr_and_immature_days_shrink_window(self):
        d = date(2026, 8, 20)
        rows = outcomes("1001", d - timedelta(days=10), d - timedelta(days=1), clicks=30) + \
            outcomes("1001", d, d + timedelta(days=10), clicks=5, immature_from=d + timedelta(days=4))
        body = self._outcome_body([chg("c1"), chg("c9", client="GOOGLE_ADS_WEB_CLIENT", when="2026-08-21 09:00")], rows)
        rec = obs(body, "outcome_comparison", "Change c1")
        self.assertEqual(rec["days_per_side"], 3)
        self.assertFalse(rec["metrics"]["cvr"]["passed"])
        self.assertNotIn("pre", rec["metrics"]["cvr"])
        self.assertEqual(rec["concurrent_changes"], ["c9"])

    def test_goal_change_across_windows_is_not_comparable(self):
        d = date(2026, 8, 20)
        rows = outcomes("1001", d - timedelta(days=5), d - timedelta(days=1)) + \
            outcomes("1001", d + timedelta(days=1), d + timedelta(days=5), goal="5002")
        rec = obs(self._outcome_body([chg("c1")], rows), "outcome_comparison", "Change c1")
        self.assertFalse(rec["comparable"])
        self.assertNotIn("metrics", rec)

    # ---- finalize / verify
    def _cli(self, *args) -> int:
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True).returncode

    def test_critical_requires_supplied_failure_evidence_and_complete_reversal(self):
        d = date(2026, 8, 20)
        changes = [chg("c2", field=TCPA, new="25", res="customers/1/campaigns/1001"),
                   chg("c3", field=TCPA, new="30", client="GOOGLE_ADS_WEB_CLIENT", when="2026-08-25 09:00",
                       res="customers/1/campaigns/1001")]
        ex = build(self.root, {CHG: changes, AUTH: [auth()],
                               OUTC: outcomes("1001", d - timedelta(days=5), d + timedelta(days=5))})
        out = self.root / "out"
        self.assertEqual(self._cli("run", "--export", str(ex), "--out", str(out)), 0)
        body = json.loads((out / "result.json").read_text())
        item = [r for r in body["ai_review"] if r["condition_key"] == "unauthorized_material_failure"][0]
        self.assertEqual(item["evidence"]["change"]["subsequent_edits"], ["c3"])
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--out", str(out), "--decisions", str(dec)]

        def decide(proposal):
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_failure_evidenced",
                                        "rationale": "delivery stopped", "proposal": proposal}]))
            return self._cli(*args)

        self.assertEqual(decide({}), 4)
        self.assertEqual(decide({"evidence_ref": "custom/delivery_log.csv#1001"}), 4)
        self.assertEqual(decide({"evidence_ref": "external/auto_apply_authorizations.csv"}), 4)
        ok_ref = "custom/auto_apply_outcomes.csv#campaign_id=1001"
        self.assertEqual(decide({"evidence_ref": ok_ref, "action": "reverse", "current_value": "30",
                                 "intended_benefit": "restore volume", "owner": "client-cmo",
                                 "subsequent_edits": []}), 4)
        self.assertEqual(decide({"evidence_ref": ok_ref, "action": "reverse", "current_value": "30",
                                 "intended_benefit": "restore volume", "owner": "client-cmo",
                                 "subsequent_edits": ["c3"]}), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "unauthorized_material_failure"],
                         ["Critical"])

    def test_batch_warning_must_name_reviewed_change_ids(self):
        ex = build(self.root, {CHG: [chg("c1")], AUTH: [auth(ranges=f"{BUDGET}=+20%")]})
        out = self.root / "out"
        self.assertEqual(self._cli("run", "--export", str(ex), "--out", str(out)), 0)
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = self.root / "d.json"
        args = ["finalize", "--export", str(ex), "--out", str(out), "--decisions", str(dec)]
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "some_outside", "rationale": "+20% exceeded",
                                    "proposal": {"change_ids": ["zz"]}}]))
        self.assertEqual(self._cli(*args), 4)
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "some_outside", "rationale": "+20% exceeded",
                                    "proposal": {"change_ids": ["c1"]}}]))
        self.assertEqual(self._cli(*args), 0)
        final = json.loads((out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"]
                          if f["condition_key"] == "change_authorization_undecidable"], ["Warning"])


if __name__ == "__main__":
    unittest.main()
