"""test_check.py — Decision-boundary tests for skill-161 automation coverage, run health, conflicts and caps.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-161-automation-layering-strategy-audit/tests
rules:   Temp folders only; manifest-complete synthetic evidence unless a test certifies otherwise;
assert conditions/severities/numbers, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_161", _CHECK)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,"
           "rates_format,money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,{start},2026-08-31,2026-09-06,fraction,currency,interaction_date,2\n")
INV_H = ("account_id,automation_id,snapshot_at,type,enabled,owner,entity_scope_ids,read_or_write_fields,conditions,"
         "thresholds,cadence,timezone,approval_ref,review_due,fallback\n")
RUN_H = ("automation_id,run_id,started_at,ended_at,scheduled_at,result,evaluated_scope_ids,affected_scope_ids,"
         "changed_fields,old_new_values,alert_delivery_status,error_summary,evidence_ref\n")
RISK_H = ("risk_id,entity_scope,risk_description,approved_spend_cap_or_service_limit,required_control,"
          "acceptable_manual_alternative,required_cadence,responsible_owner,approval_ref\n")


def inv(aid, scope="campaign:1", fields="read:cost", enabled="true", cadence="daily"):
    return f"1,{aid},2026-09-01,script,{enabled},ops,{scope},{fields},,,{cadence},Europe/Rome,apr-1,,manual check\n"


def runs(aid, days, result="success", alert="not_applicable", hour=6):
    out = ""
    for d in days:
        ts = f"{d.isoformat()}T{hour:02d}:00:00"
        out += f"{aid},{aid}-{d.isoformat()},{ts},{ts},{ts},{result},1,,,,{alert},,ev-{aid}\n"
    return out


def span(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


AUG = span(date(2026, 8, 2), date(2026, 8, 31))


def risk(rid, scope="campaign:1", control="A1", cap="", cadence="daily", approval="apr-r"):
    return f"{rid},{scope},overspend,{cap},{control},,{cadence},ops lead,{approval}\n"


class Base(unittest.TestCase):
    def run_check(self, files: dict, start="2026-08-01", incomplete=()) -> dict:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        files = {"account.csv": ACCOUNT.format(start=start), **files}
        rows = ["filename,completeness,truncation"] + [
            f"{n},{'partial' if n in incomplete else 'complete'},none" for n in sorted(files)]
        files["table_manifest.csv"] = "\n".join(rows) + "\n"
        for name, text in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.export, self.out = root, Path(tmp.name) / "out"
        with redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--out", str(self.out)])
        self.assertEqual(code, 0)
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions: list) -> tuple[int, dict]:
        path = self.out / "decisions.json"
        path.write_text(json.dumps(decisions))
        with redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.export), "--out", str(self.out), "--decisions", str(path)])
        return code, json.loads((self.out / "final.json").read_text())

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)


class Coverage(Base):
    def test_numerator_and_denominator(self):
        files = {"external/automation_inventory.csv": INV_H + inv("A1", "campaign:1;campaign:2") + inv("A2"),
                 "external/automation_runs.csv": RUN_H + runs("A1", AUG) + runs("A2", AUG[:-1]) +
                 runs("A2", AUG[-1:], result="failed"),
                 "external/automation_risks.csv": RISK_H + risk("R1") + risk("R2", control="A2") +
                 risk("R3", approval="") + risk("R4", control="weekly manual review")}
        body = self.run_check(files)
        obs = next(o["data"] for o in body["observations"] if o["check"] == "risk_coverage" and "numerator" in o["data"])
        self.assertEqual((obs["numerator"], obs["denominator"], obs["failed"], obs["unmapped"], obs["excluded_unapproved"]),
                         (1, 3, 1, 1, 1))
        self.assertEqual([r["entity"]["risk_id"] for r in body["ai_review"]
                          if r["condition_key"] == "control_mapping_unresolved"], ["R4"])

    def test_control_outside_risk_scope_does_not_cover(self):
        files = {"external/automation_inventory.csv": INV_H + inv("A1", "campaign:2"),
                 "external/automation_runs.csv": RUN_H + runs("A1", AUG),
                 "external/automation_risks.csv": RISK_H + risk("R1")}
        obs = next(o["data"] for o in self.run_check(files)["observations"]
                   if o["check"] == "risk_coverage" and "numerator" in o["data"])
        self.assertEqual((obs["numerator"], obs["unknown"]), (0, 1))

    def test_zero_denominator_is_not_applicable(self):
        files = {"external/automation_inventory.csv": INV_H + inv("A1"),
                 "external/automation_runs.csv": RUN_H + runs("A1", AUG),
                 "external/automation_risks.csv": RISK_H + risk("R1", approval="")}
        self.assertEqual(self.cov(self.run_check(files), "risk_coverage")["status"], "not_applicable")


class RunHealth(Base):
    def test_failed_run_warning_only_for_required_control(self):
        files = {"external/automation_inventory.csv": INV_H + inv("A1") + inv("A3"),
                 "external/automation_runs.csv": RUN_H + runs("A1", AUG[:5], result="failed") + runs("A1", AUG[5:]) +
                 runs("A3", AUG, result="failed"),
                 "external/automation_risks.csv": RISK_H + risk("R1")}
        f = self.found(self.run_check(files), "required_control_failed_run")
        self.assertEqual([(x["severity"], x["entity"]["automation_id"]) for x in f], [("Warning", "A1")])

    def test_overdue_needs_complete_log_and_gap_over_twice_cadence(self):
        gap = [d for d in AUG if d.day != 11]  # one missed day: gap of exactly 48h is not proven overdue
        base = {"external/automation_inventory.csv": INV_H + inv("A1"),
                "external/automation_risks.csv": RISK_H + risk("R1")}
        body = self.run_check({**base, "external/automation_runs.csv": RUN_H + runs("A1", gap)})
        self.assertEqual(self.found(body, "required_control_overdue"), [])
        stopped = [d for d in AUG if d.day <= 20]
        body = self.run_check({**base, "external/automation_runs.csv": RUN_H + runs("A1", stopped)})
        self.assertEqual([f["severity"] for f in self.found(body, "required_control_overdue")], ["Warning"])
        body = self.run_check({**base, "external/automation_runs.csv": RUN_H + runs("A1", stopped)},
                              incomplete=("external/automation_runs.csv",))
        self.assertEqual(self.found(body, "required_control_overdue"), [])
        self.assertEqual([f["severity"] for f in self.found(body, "run_evidence_unknown")], ["Info"])

    def test_generated_alert_is_not_delivered(self):
        base = {"external/automation_inventory.csv": INV_H + inv("A1"),
                "external/automation_risks.csv": RISK_H + risk("R1")}
        body = self.run_check({**base, "external/automation_runs.csv": RUN_H + runs("A1", AUG, alert="failed")})
        self.assertEqual([f["severity"] for f in self.found(body, "required_alert_not_delivered")], ["Warning"])
        body = self.run_check({**base, "external/automation_runs.csv": RUN_H + runs("A1", AUG, alert="generated")})
        self.assertEqual(self.found(body, "required_alert_not_delivered"), [])
        self.assertEqual([f["severity"] for f in self.found(body, "alert_delivery_unknown")], ["Info"])
        body = self.run_check({**base, "external/automation_runs.csv": RUN_H + runs("A1", AUG, alert="delivered")})
        self.assertEqual(self.found(body, "alert_delivery_unknown") + self.found(body, "required_alert_not_delivered"), [])


class WriteConflicts(Base):
    INV = INV_H + inv("A1", "campaign:1", "write:budget") + inv("A4", "campaign:1;campaign:2", "write:budget;read:cost")

    def test_run_evidenced_conflict_and_critical_needs_evidence_ref(self):
        r = (RUN_H + "A1,a1,2026-08-10T06:00:00,2026-08-10T06:10:00,,success,1,1,budget,budget:100->80,,,e1\n"
                     "A4,a4,2026-08-10T06:05:00,2026-08-10T06:06:00,,success,1,campaign:1,budget,budget:100->150,,,e2\n")
        body = self.run_check({"external/automation_inventory.csv": self.INV, "external/automation_runs.csv": r})
        self.assertEqual([f["severity"] for f in self.found(body, "incompatible_overlapping_writes")], ["Warning"])
        rid = next(x["id"] for x in body["ai_review"] if x["condition_key"] == "incompatible_overlapping_writes")
        code, final = self.finalize([{"id": rid, "outcome": "material_breach_evidenced", "rationale": "x"}])
        self.assertEqual(code, 4)
        code, final = self.finalize([{"id": rid, "outcome": "material_breach_evidenced", "rationale": "x",
                                      "proposal": {"evidence_ref": "e1,e2"}}])
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in self.found(final, "incompatible_overlapping_writes")], ["Critical"])

    def test_same_day_reversal_is_a_conflict_but_sequential_agreement_is_not(self):
        rev = (RUN_H + "A1,a1,2026-08-10T06:00:00,2026-08-10T06:01:00,,success,1,1,budget,budget:100->80,,,e1\n"
                       "A4,a4,2026-08-10T18:00:00,2026-08-10T18:01:00,,success,1,1,budget,budget:80->100,,,e2\n")
        body = self.run_check({"external/automation_inventory.csv": self.INV, "external/automation_runs.csv": rev})
        self.assertEqual(len(self.found(body, "incompatible_overlapping_writes")), 1)
        seq = rev.replace("budget:80->100", "budget:80->70")
        body = self.run_check({"external/automation_inventory.csv": self.INV, "external/automation_runs.csv": seq})
        self.assertEqual(self.found(body, "incompatible_overlapping_writes"), [])
        self.assertEqual([x["condition_key"] for x in body["ai_review"]], ["potential_write_overlap"])

    def test_disjoint_scope_or_read_only_is_not_overlap(self):
        inv_rows = INV_H + inv("A1", "campaign:1", "write:budget") + inv("A4", "campaign:2", "write:budget") + \
            inv("A5", "campaign:1", "read:budget")
        body = self.run_check({"external/automation_inventory.csv": inv_rows})
        self.assertEqual(body["ai_review"], [])


class CapBreach(Base):
    def files(self, cost_1, cost_2, cap="1000 EUR/month"):
        return {"external/automation_risks.csv": RISK_H + risk("R1", scope="account", cap=cap),
                "campaign_metrics.csv": f"campaign_id,cost\n1,{cost_1}\n2,{cost_2}\n"}

    def test_monthly_cap_breach_and_counterexample(self):
        body = self.run_check(self.files(700, 500))
        f = self.found(body, "approved_cap_breach")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual(f[0]["evidence"]["spend"], 1200)
        self.assertEqual(self.found(self.run_check(self.files(500, 400)), "approved_cap_breach"), [])

    def test_non_calendar_period_and_daily_caps_are_not_breaches(self):
        body = self.run_check(self.files(700, 500), start="2026-08-04")
        self.assertEqual(self.found(body, "approved_cap_breach"), [])
        self.assertEqual(self.cov(body, "cap_breach")["status"], "partial")
        body = self.run_check(self.files(700, 500, cap="30 EUR/day"))
        self.assertEqual(self.found(body, "approved_cap_breach"), [])

    def test_incomplete_metrics_prove_breach_but_not_compliance(self):
        body = self.run_check(self.files(700, 500), incomplete=("campaign_metrics.csv",))
        self.assertTrue(self.found(body, "approved_cap_breach")[0]["evidence"]["spend_is_lower_bound"])
        body = self.run_check(self.files(500, 400), incomplete=("campaign_metrics.csv",))
        self.assertFalse(any(o["check"] == "cap_breach" and "utilization" in o["data"] for o in body["observations"]))


class Proposals(Base):
    def test_revision_must_be_request_only_and_in_scope(self):
        files = {"external/automation_inventory.csv": INV_H + inv("A1"),
                 "external/automation_runs.csv": RUN_H + runs("A1", AUG, result="failed"),
                 "external/automation_risks.csv": RISK_H + risk("R1")}
        body = self.run_check(files)
        rid = next(x["id"] for x in body["ai_review"] if x["condition_key"] == "oversight_revision")
        good = {"owner": "ops lead", "cadence": "daily", "guardrails": "max 20% change", "fallback": "manual check",
                "scope_ids": ["campaign:1"], "request_only": True}
        code, _ = self.finalize([{"id": rid, "outcome": "propose_revision", "rationale": "r",
                                  "proposal": {**good, "scope_ids": ["campaign:9"]}}])
        self.assertEqual(code, 4)
        code, _ = self.finalize([{"id": rid, "outcome": "propose_revision", "rationale": "r", "proposal": good}])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
