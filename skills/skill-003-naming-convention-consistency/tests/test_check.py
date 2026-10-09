"""test_check.py — skill-003 decision boundaries: convention scope, duplicates, dependencies, verified renames.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-003-naming-convention-consistency/tests -t skills/skill-003-naming-convention-consistency
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
_spec = importlib.util.spec_from_file_location("check_skill_003", SCRIPT)
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



CONV = {"campaign": {"delimiter": " | ", "fields": ["market", "channel", "theme"],
                     "allowed": {"market": ["IT", "DE"], "channel": ["SRC", "PMX"]}, "exceptions": ["9"],
                     "placeholders": ["copy of"], "channel_field": "channel",
                     "channel_map": {"SRC": "SEARCH", "PMX": "PERFORMANCE_MAX"}}}


def c(i, name, status="ENABLED", ch="SEARCH"):
    return {"id": i, "name": name, "status": status, "channel_type": ch}


def g(i, cid, name, status="ENABLED"):
    return {"id": i, "campaign_id": cid, "name": name, "status": status}


def tables(campaigns, groups=None):
    return {"campaigns": campaigns, "ad_groups": groups or [g("20", "1", "Core")]}


class Naming(unittest.TestCase):
    def test_without_convention_only_clusters_no_compliance_findings(self):
        body = run(self, tables([c("1", "IT - Brand"), c("2", "whatever")]))
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body, "consistency")["status"], "partial")
        self.assertEqual(cov(body, "convention_parse")["status"], "partial")

    def test_consistency_below_80_is_info_with_denominator(self):
        cs = [c("1", "IT | SRC | drills"), c("2", "Brand campaign"), c("3", "FR | SRC | x"), c("9", "legacy")]
        body = run(self, tables(cs), {"naming_convention": CONV})
        f = F(body, "consistency_below_80")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["evidence"]["conforming"], f[0]["evidence"]["applicable"]), (1, 3))
        cs = [c("1", "IT | SRC | drills"), c("2", "DE | SRC | saws"), c("3", "IT | PMX | all", ch="PERFORMANCE_MAX")]
        body = run(self, tables(cs), {"naming_convention": CONV})
        self.assertEqual(F(body, "consistency_below_80"), [])

    def test_empty_enabled_scope_is_undefined_not_100(self):
        body = run(self, tables([c("1", "bad", status="PAUSED")]), {"naming_convention": CONV})
        obs = next(o for o in body["observations"] if o["text"] == "campaign ENABLED naming consistency")
        self.assertIsNone(obs["data"]["consistency"])
        self.assertEqual(F(body, "consistency_below_80"), [])

    def test_duplicates_scoped_correctly(self):
        groups = [g("20", "1", "Core"), g("21", "2", "Core"), g("22", "2", "core "), g("23", "2", "Other")]
        body = run(self, tables([c("1", "A"), c("2", "A"), c("3", "a")], groups))
        camp = [f for f in body["findings"] if f["entity"]["entity_type"] == "campaign"]
        self.assertEqual([(f["condition_key"], f["entity"]["ids"]) for f in camp], [("near_duplicate_name", ["1", "2", "3"])])
        ag = [f for f in body["findings"] if f["entity"]["entity_type"] == "ad_group"]
        self.assertEqual([(f["condition_key"], f["entity"]["ids"]) for f in ag], [("near_duplicate_name", ["21", "22"])])
        body = run(self, tables([c("1", "A"), c("2", "A")]))
        self.assertEqual([f["condition_key"] for f in F(body, "duplicate_name")], ["duplicate_name"])

    def test_placeholder_and_misleading_channel_segment(self):
        cs = [c("1", "IT | PMX | copy of drills"), c("2", "IT | SRC | saws")]
        body = run(self, tables(cs), {"naming_convention": CONV})
        self.assertEqual([f["entity"]["id"] for f in F(body, "placeholder_name")], ["1"])
        self.assertEqual([f["entity"]["id"] for f in F(body, "misleading_channel_segment")], ["1"])

    def test_dependency_warning_requires_matching_evidence_ref(self):
        dep = [{"consumer_id": "dash1", "entity_type": "campaign", "campaign_id": "", "name_pattern": r"^(IT|DE) \|",
                "expected_behavior": "market split", "observed_failure": "campaign 2 missing from IT report",
                "evidence_ref": "ticket-7", "owner": "bi", "reviewed_at": "2026-09-01"}]
        t = dict(tables([c("1", "IT | SRC | a"), c("2", "Brand")]), **{"external/naming_dependencies": dep})
        pick = lambda ref: (lambda body: [{"id": R(body, "naming_consumer_failure")[0]["id"],
                                           "outcome": "failure_caused_by_names", "rationale": "name breaks parser",
                                           "proposal": {"evidence_ref": ref}}])
        code, _ = finalize(self, t, {"naming_convention": CONV}, pick("other"))
        self.assertEqual(code, 4)
        code, final = finalize(self, t, {"naming_convention": CONV}, pick("ticket-7"))
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in F(final, "naming_consumer_failure")], ["Warning"])

    def test_dependency_without_observed_failure_is_not_reviewed(self):
        dep = [{"consumer_id": "dash1", "entity_type": "campaign", "campaign_id": "", "name_pattern": "^IT",
                "expected_behavior": "x", "observed_failure": "", "evidence_ref": "", "owner": "bi", "reviewed_at": ""}]
        body = run(self, dict(tables([c("1", "Brand")]), **{"external/naming_dependencies": dep}))
        self.assertEqual(R(body, "naming_consumer_failure"), [])

    def test_rename_proposals_must_conform_and_stay_unique(self):
        cs = [c("1", "IT | SRC | a"), c("2", "Brand")]
        pick = lambda after: (lambda body: [{"id": R(body, "rename_proposals")[0]["id"], "outcome": "renames_proposed",
                                             "rationale": "align",
                                             "proposal": {"renames": [{"entity_type": "campaign", "id": "2",
                                                                       "before": "Brand", "after": after}]}}])
        self.assertEqual(finalize(self, tables(cs), {"naming_convention": CONV}, pick("Brand IT"))[0], 4)
        self.assertEqual(finalize(self, tables(cs), {"naming_convention": CONV}, pick("IT | SRC | a"))[0], 4)
        self.assertEqual(finalize(self, tables(cs), {"naming_convention": CONV}, pick("IT | SRC | brand"))[0], 0)


if __name__ == "__main__":
    unittest.main()
