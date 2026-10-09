"""test_check.py — skill-008 decision boundaries: coverage scope, policy rules, unattached labels, dependency-aware proposals.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-008-label-organizational-structure/tests -t skills/skill-008-label-organizational-structure
rules:   Synthetic temp exports only; never reads the self-test oracle; asserts entities/severities/coverage, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | CodeDNA header
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx051 | tests for this session's check changes
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
_spec = importlib.util.spec_from_file_location("check_skill_008", SCRIPT)
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


def build(test, tables, profile=None, account=None, incomplete=()):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    export = root / "export"
    tables = {"account": [account or ACCOUNT], **tables}
    for key, rows in tables.items():
        _write(export / f"{key}.csv", rows)
    _write(export / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "partial" if k in incomplete else "complete",
                                            "truncation": "none"} for k in tables])
    prof = root / "profile.json"
    prof.write_text(json.dumps(profile or {}))
    return root, export, prof


def run(test, tables, profile=None, account=None, incomplete=()):
    _, export, prof = build(test, tables, profile, account, incomplete)
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



INV, ASSOC, POL = "custom/label_inventory", "custom/label_associations", "external/label_policy"


def lab(i, name, status="ENABLED"):
    return {"account_id": "a", "label_id": i, "name": name, "status": status, "snapshot_date": "2026-09-06"}


def assoc(lid, etype, eid, cid="", gid=""):
    return {"account_id": "a", "label_id": lid, "entity_type": etype, "campaign_id": cid, "ad_group_id": gid,
            "entity_id": eid, "snapshot_date": "2026-09-06"}


def rule(rid, etype, elig, req, failure="", ref="", consumer="rep1"):
    return {"rule_id": rid, "entity_type": etype, "eligibility_rule": elig, "required_label_ids": req, "consumer_id": consumer,
            "expected_behavior": "report split", "observed_failure": failure, "evidence_ref": ref, "owner": "bi",
            "reviewed_at": "2026-09-01"}


def base(labels, associations, policy=None):
    t = {"campaigns": [{"id": "1", "name": "IT | Search | Brand", "status": "ENABLED", "channel_type": "SEARCH", "labels": ""},
                       {"id": "2", "name": "IT | Shopping | All", "status": "ENABLED", "channel_type": "SHOPPING", "labels": ""},
                       {"id": "3", "name": "DE | Search | Old", "status": "PAUSED", "channel_type": "SEARCH", "labels": ""}],
         INV: labels, ASSOC: associations}
    if policy is not None:
        t[POL] = policy
    return t


class Labels(unittest.TestCase):
    def test_similar_label_names_info_distinct_names_none(self):
        body = run(self, base([lab("L1", "Brand"), lab("L2", "brand "), lab("L3", "Generic")], [assoc("L1", "campaign", "1")]))
        self.assertEqual([f["entity"]["label_ids"] for f in F(body, "similar_label_names")], [["L1", "L2"]])

    def test_coverage_only_for_levels_with_associations_and_split_by_status(self):
        body = run(self, base([lab("L1", "Brand")], [assoc("L1", "campaign", "1")]))
        obs = {o["text"]: o["data"] for o in body["observations"] if o["check"] == "label_coverage"}
        self.assertEqual((obs["campaign ENABLED any-label coverage"]["labeled"],
                          obs["campaign ENABLED any-label coverage"]["applicable"]), (1, 2))
        self.assertEqual(obs["campaign PAUSED any-label coverage"]["applicable"], 1)
        self.assertEqual(cov(body, "label_coverage")["status"], "partial")
        self.assertEqual(body["counts"], {"Critical": 0, "Warning": 0, "Info": 0})

    def test_policy_missing_label_is_info_and_name_segment_rule(self):
        pol = [rule("r1", "campaign", "name_segment: | :1=Search", "L1")]
        body = run(self, base([lab("L1", "Search")], [assoc("L1", "campaign", "1"), assoc("L1", "campaign", "3")], pol))
        missing = F(body, "policy_label_gap")
        self.assertEqual(missing, [])
        body = run(self, base([lab("L1", "Search")], [assoc("L1", "campaign", "2")], pol))
        gap = F(body, "policy_label_gap")
        self.assertEqual([m["entity_id"] for m in gap[0]["evidence"]["missing"]], ["1", "3"])
        self.assertEqual(gap[0]["severity"], "Info")
        self.assertEqual(R(body, "policy_label_gap"), [])

    def test_exclusive_group_contradiction_and_unevaluable_rule(self):
        pol = [rule("r1", "campaign", "status=ENABLED", "L1|L2")]
        body = run(self, base([lab("L1", "A"), lab("L2", "B")],
                              [assoc("L1", "campaign", "1"), assoc("L2", "campaign", "1"), assoc("L1", "campaign", "2")], pol))
        gap = F(body, "policy_label_gap")[0]
        self.assertEqual([c["entity_id"] for c in gap["evidence"]["contradictory"]], ["1"])
        self.assertEqual(gap["evidence"]["missing"], [])
        pol = [rule("r2", "campaign", "conversions>=5", "L1")]
        body = run(self, base([lab("L1", "A")], [assoc("L1", "campaign", "1")], pol))
        self.assertEqual(cov(body, "policy_compliance")["status"], "partial")
        self.assertEqual(F(body, "policy_label_gap"), [])

    def test_unattached_label_info_only_with_all_levels_complete(self):
        body = run(self, base([lab("L1", "A"), lab("L9", "Idle")], [assoc("L1", "campaign", "1")]))
        self.assertEqual(F(body, "unattached_in_export"), [])
        self.assertEqual(cov(body, "unattached_labels")["status"], "partial")
        t = base([lab("L1", "A"), lab("L9", "Idle")],
                 [assoc("L1", "campaign", "1"), assoc("L1", "ad_group", "10"), assoc("L1", "keyword", "100"), assoc("L1", "ad", "1000")])
        t.update({"ad_groups": [{"id": "10", "campaign_id": "1", "name": "g", "status": "ENABLED"}],
                  "keywords": [{"id": "100", "campaign_id": "1", "ad_group_id": "10", "text": "x", "status": "ENABLED"}],
                  "ads": [{"id": "1000", "campaign_id": "1", "ad_group_id": "10", "status": "ENABLED"}]})
        body = run(self, t)
        self.assertEqual([f["entity"]["label_id"] for f in F(body, "unattached_in_export")], ["L9"])

    def test_finalize_consumer_breakage_requires_rule_evidence_ref(self):
        pol = [rule("r1", "campaign", "channel=SEARCH", "L1", failure="brand rows missing", ref="dash-issue-3")]
        t = base([lab("L1", "Brand")], [assoc("L1", "campaign", "2")], pol)
        pick = lambda ref: (lambda body: [{"id": R(body, "policy_label_gap")[0]["id"], "outcome": "breaks_consumer",
                                           "rationale": "report filters on L1", "proposal": {"evidence_ref": ref}}])
        self.assertEqual(finalize(self, t, {}, pick("guess"))[0], 4)
        code, final = finalize(self, t, {}, pick("dash-issue-3"))
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in F(final, "policy_label_gap")], ["Warning"])

    def test_merge_proposal_must_list_all_consumers(self):
        pol = [rule("r1", "campaign", "all", "L1", consumer="rep1"), rule("r2", "campaign", "all", "L2", consumer="rep2")]
        t = base([lab("L1", "Brand"), lab("L2", "BRAND")],
                 [assoc("L1", "campaign", c) for c in "123"] + [assoc("L2", "campaign", c) for c in "123"], pol)
        pick = lambda cons: (lambda body: [{"id": R(body, "label_merge_proposal")[0]["id"], "outcome": "merge_proposed",
                                            "rationale": "same meaning",
                                            "proposal": {"keep_label_id": "L1", "merge_label_ids": ["L2"], "consumers": cons}}])
        self.assertEqual(finalize(self, t, {}, pick(["rep1"]))[0], 4)
        self.assertEqual(finalize(self, t, {}, pick(["rep1", "rep2"]))[0], 0)


KCA = "custom/keyword_conversions_by_action"


def kw(i, labels=""):
    return {"id": i, "campaign_id": "1", "ad_group_id": "10", "text": f"kw{i}", "status": "ENABLED", "labels": labels}


def km(i, clicks):
    return {"keyword_id": i, "campaign_id": "1", "ad_group_id": "10", "impressions": "500", "clicks": clicks,
            "cost": "12.5", "conversions": "9", "conversion_value": "300"}


def kca(i, action, conv, window="report"):
    return {"keyword_id": i, "campaign_id": "1", "ad_group_id": "10", "conversion_action_id": action,
            "conversions": conv, "conversion_value": str(float(conv) * 40), "window": window}


def rules_tables(by_action=None):
    t = {"campaigns": [{"id": "1", "name": "c", "status": "ENABLED", "channel_type": "SEARCH", "labels": ""}],
         "keywords": [kw("100"), kw("101", "Top Buyer;Brand"), kw("102", "top buyer"), kw("103")],
         "keyword_metrics": [km("100", "20"), km("101", "30"), km("102", "15"), km("103", "40")],
         "conversion_actions": [{"id": "5001", "name": "Purchase", "status": "ENABLED"},
                                {"id": "5002", "name": "Contact form", "status": "ENABLED"}]}
    t[KCA] = by_action if by_action is not None else [kca("100", "5001", "3"), kca("101", "5001", "1"),
                                                      kca("102", "5001", "2"), kca("103", "5002", "5")]
    return t


def label_rule(action="5001", metric="conversions", rid="buyers", extra=()):
    return {"label_rules": [{"rule_id": rid, "label": "Top Buyer", "entity": "keyword", "window": "report",
                             "conditions": [{"metric": metric, "conversion_action": action, "op": ">=", "value": 2},
                                            {"metric": "clicks", "op": ">=", "value": 10}, *extra]}]}


def rule_obs(body):
    return [o["data"] for o in body["observations"] if o["check"] == "label_rule_evaluation" and "rule_id" in o["data"]]


class LabelRules(unittest.TestCase):
    def test_no_profile_key_is_not_applicable(self):
        body = run(self, rules_tables())
        self.assertEqual(cov(body, "label_rule_evaluation")["status"], "not_applicable")
        self.assertEqual(F(body, "label_rule_diff"), [])

    def test_add_remove_diff_by_conversion_action(self):
        body = run(self, rules_tables(), label_rule(action="Purchase"))
        (f,) = F(body, "label_rule_diff")
        self.assertEqual(f["severity"], "Info")
        self.assertEqual([k["keyword_id"] for k in f["evidence"]["add"]], ["100"])
        self.assertEqual([k["keyword_id"] for k in f["evidence"]["remove"]], ["101"])
        (obs,) = rule_obs(body)
        self.assertEqual([k["keyword_id"] for k in obs["should_carry"]], ["100", "102"])
        self.assertEqual([k["keyword_id"] for k in obs["currently_carry"]], ["101", "102"])
        self.assertEqual(cov(body, "label_rule_evaluation")["status"], "completed")
        self.assertEqual(run(self, rules_tables(), label_rule(action="Purchase"))["findings"], body["findings"])

    def test_other_action_and_other_window_do_not_count(self):
        # 103 converts only on 5002; 100's only 5001 row is for a different window → absent from a complete table = 0
        t = rules_tables([kca("100", "5001", "3", window="2026-07-01..2026-07-31"), kca("101", "5001", "1"),
                          kca("102", "5001", "2"), kca("103", "5002", "5")])
        (f,) = F(run(self, t, label_rule()), "label_rule_diff")
        self.assertEqual(f["evidence"]["add"], [])
        self.assertEqual([k["keyword_id"] for k in f["evidence"]["remove"]], ["101"])

    def test_incomplete_by_action_table_leaves_absent_rows_undetermined(self):
        t = rules_tables([kca("100", "5001", "3"), kca("102", "5001", "2")])
        body = run(self, t, label_rule(), incomplete=(KCA,))
        (f,) = F(body, "label_rule_diff")
        self.assertEqual([k["keyword_id"] for k in f["evidence"]["add"]], ["100"])
        self.assertEqual(f["evidence"]["remove"], [])  # 101 carries the label but its value is unknown
        self.assertEqual(f["evidence"]["undetermined"], 2)
        self.assertEqual(cov(body, "label_rule_evaluation")["status"], "partial")

    def test_immature_window_blocks_conversion_rules_only(self):
        acct = {**ACCOUNT, "conversion_lag_days": "10"}
        body = run(self, rules_tables(), label_rule(), account=acct)
        self.assertEqual(F(body, "label_rule_diff"), [])
        self.assertEqual(cov(body, "label_rule_evaluation")["status"], "partial")
        clicks_only = {"label_rules": [{"rule_id": "busy", "label": "Top Buyer", "entity": "keyword", "window": "report",
                                        "conditions": [{"metric": "clicks", "op": ">=", "value": 25}]}]}
        (f,) = F(run(self, rules_tables(), clicks_only, account=acct), "label_rule_diff")
        self.assertEqual([k["keyword_id"] for k in f["evidence"]["add"]], ["103"])
        self.assertEqual([k["keyword_id"] for k in f["evidence"]["remove"]], ["102"])

    def test_unknown_action_or_metric_rejects_rule(self):
        for prof in (label_rule(action="Signup"), label_rule(metric="ctr"), label_rule(action="5001", metric="clicks")):
            body = run(self, rules_tables(), prof)
            c = cov(body, "label_rule_evaluation")
            self.assertEqual(c["status"], "partial")
            self.assertTrue(any("rule buyers rejected" in n for n in c["notes"]), c["notes"])
            self.assertEqual(F(body, "label_rule_diff"), [])
            self.assertEqual(rule_obs(body), [])

    def test_missing_by_action_table_or_labels_column(self):
        t = rules_tables()
        del t[KCA]
        body = run(self, t, label_rule())
        c = cov(body, "label_rule_evaluation")
        self.assertEqual((c["status"], c["missing"]), ("partial", [f"{KCA} (file)"]))
        self.assertEqual(F(body, "label_rule_diff"), [])
        t = rules_tables()
        t["keywords"] = [{k: v for k, v in r.items() if k != "labels"} for r in t["keywords"]]
        body = run(self, t, label_rule())
        self.assertEqual(cov(body, "label_rule_evaluation")["missing"], ["keywords:labels"])
        self.assertEqual(F(body, "label_rule_diff"), [])
        self.assertEqual([k["keyword_id"] for k in rule_obs(body)[0]["should_carry"]], ["100", "102"])


if __name__ == "__main__":
    unittest.main()
