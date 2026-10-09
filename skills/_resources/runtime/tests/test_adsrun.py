"""test_adsrun.py — Regression tests for the adsrun runtime decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/_resources/runtime/tests
rules:   Tests pin consumer-visible behavior (matching semantics, unknown vs zero, parameter precedence,
account isolation, review finalization), never wording. Temp folders only; no network.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial runtime tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime_b | merge, tracking window, account rows, shared-list aliases, import-agnostic regressions
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adsrun import cli, values as V  # noqa: E402
from adsrun.context import Context, ContextError  # noqa: E402
from adsrun.negatives import blocks  # noqa: E402
from adsrun.yamlish import ProfileSyntaxError, parse  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,"
           "rates_format,money_unit,conversion_date_basis,conversion_lag_days\n")


def _export(tmp: Path, files: dict) -> Path:
    root = tmp / "export"
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _acct(cid="1", cur="EUR", end="2026-08-30", lag="2"):
    return f"{cid},A,{cur},Europe/Rome,2026-08-01,{end},2026-09-06,fraction,currency,interaction_date,{lag}\n"


class Matching(unittest.TestCase):
    def test_phrase_is_contiguous_ordered_and_directional(self):
        self.assertTrue(blocks("red shoes", "PHRASE", "buy red shoes"))
        self.assertFalse(blocks("red shoes", "PHRASE", "shoes red"))
        self.assertFalse(blocks("red shoes", "PHRASE", "red running shoes"))
        self.assertFalse(blocks("buy red shoes", "PHRASE", "red shoes"))

    def test_exact_and_broad(self):
        self.assertTrue(blocks("red shoes", "EXACT", "Red  Shoes"))
        self.assertFalse(blocks("red shoes", "EXACT", "red shoe"))
        self.assertTrue(blocks("red shoes", "BROAD", "shoes that are red"))

    def test_undecidable_is_none_not_false(self):
        self.assertIsNone(blocks("a", "PHRASE", " ".join(["a"] * 17)))
        self.assertIsNone(blocks("a", "UNKNOWN", "a"))


class Values(unittest.TestCase):
    def test_unknown_is_not_zero(self):
        self.assertIsNone(V.num(""))
        self.assertIsNone(V.num("--"))
        self.assertEqual(V.num("0"), 0.0)
        self.assertIsNone(V.num("1.234,5"))
        self.assertIsNone(V.ratio(5, 0))

    def test_units(self):
        self.assertEqual(V.money("2500000", "micros"), 2.5)
        self.assertEqual(V.rate("25", "percent"), 0.25)
        self.assertEqual(V.rate("25%", "fraction"), 0.25)
        self.assertIsNone(V.rate("< 10%", "percent"))


class Profile(unittest.TestCase):
    def test_subset(self):
        d = parse("a: 1  # c\nb: [x, 'y z']\nc:\n  1001: {role: brand, goal_ids: [5001], target_cpa: 20}\nd: null\n"
                  "e:\n  - one\n  - k: v\n    k2: 2\n")
        self.assertEqual(d["c"]["1001"]["target_cpa"], 20)
        self.assertEqual(d["b"], ["x", "y z"])
        self.assertIsNone(d["d"])
        self.assertEqual(d["e"], ["one", {"k": "v", "k2": 2}])

    def test_duplicate_key_rejected(self):
        with self.assertRaises(ProfileSyntaxError):
            parse("target_cpa: 1\ntarget_cpa: 2\n")


def _noop(ctx):
    ctx.check("c", "c")


class ParamsAndScope(unittest.TestCase):
    def test_cpa_precedence_and_mixed_goals(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            ex = _export(tmp, {"account.csv": ACCOUNT + _acct(),
                               "campaigns.csv": "id,target_cpa\nC1,80\nC2,\n"})
            prof = tmp / "p.yaml"
            prof.write_text("target_cpa: 30\ncampaign_objectives:\n  C2: {goal_ids: [lead], target_cpa: 40}\n"
                            "  C3: {goal_ids: [sale]}\n")
            ctx = Context("s", "1", ex, prof)
            self.assertEqual(ctx.params.get("spend_floor", "C1").value, 80)  # campaign beats profile
            self.assertEqual(ctx.params.get("spend_significant", "C2").value, 100)  # max(100, 2*40)
            self.assertEqual(ctx.params.get("spend_floor", "C3").value, 50)  # mixed goals: no global CPA
            self.assertIsNone(ctx.params.get("spend_high").value)  # no 30-day window

    def test_portfolio_target_via_strategy_membership(self):
        with tempfile.TemporaryDirectory() as t:
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct(), "campaigns.csv": "id,strategy_id,target_cpa\nC,,\n",
                                   "bidding_strategies.csv": "id,target_cpa,campaign_ids\nS,100,C\n"})
            self.assertEqual(Context("s", "1", ex, None).params.target_cpa("C")[0], 100)

    def test_non_eur_needs_floors(self):
        with tempfile.TemporaryDirectory() as t:
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct(cur="JPY")})
            self.assertIsNone(Context("s", "1", ex, None).params.get("spend_floor").value)

    def test_thirty_day_window_requires_complete_unique_days(self):
        end = date(2026, 8, 30)
        rows = "".join(f"{end - timedelta(days=i)},10,true\n" for i in range(30))
        manifest = ("filename,completeness\naccount_daily_spend.csv,complete\n")
        with tempfile.TemporaryDirectory() as t:
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct(), "table_manifest.csv": manifest,
                                   "account_daily_spend.csv": "date,cost,complete_day\n" + rows})
            self.assertEqual(Context("s", "1", ex, None).params.get("spend_high").value, 500)  # max(500, 5%*300)
        with tempfile.TemporaryDirectory() as t:
            dup = rows + f"{end},10,true\n"
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct(), "table_manifest.csv": manifest,
                                   "account_daily_spend.csv": "date,cost,complete_day\n" + dup})
            self.assertIsNone(Context("s", "1", ex, None).params.get("spend_high").value)

    def test_unknown_lag_is_not_mature(self):
        with tempfile.TemporaryDirectory() as t:
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct(lag="")})
            self.assertIsNone(Context("s", "1", ex, None).mature)

    def test_multi_account_partitions_and_isolates_currency(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            ex = _export(tmp, {"account.csv": ACCOUNT + _acct("1") + _acct("2", cur="USD"),
                               "campaigns.csv": "customer_id,id\n1,A\n2,B\n", "keywords.csv": "id\nK\n"})
            with self.assertRaises(ContextError):
                Context("s", "1", ex, None)
            self.assertEqual(cli.main("s", "1", _noop, argv=["--export", str(ex), "--out", str(tmp / "o")]), 0)
            b = json.loads((tmp / "o/accounts/2/result.json").read_text())
            self.assertEqual(b["scope"]["currency"], "USD")
            self.assertEqual(b["inputs"]["files"]["campaigns.csv"]["rows"], 1)  # rows in this account only
            ctx = Context("s", "1", ex, None, account_id="2")
            self.assertEqual([r["id"] for r in ctx.rows("campaigns")], ["B"])
            self.assertIsNone(ctx.table("keywords"))  # no account key → not shared

    def test_tracking_is_goal_specific_and_free_text_is_not_proof(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            ex = _export(tmp, {"account.csv": ACCOUNT + _acct(),
                               "conversion_actions.csv": "id,name,category,status,last_conversion_date\n"
                                                         "P,Purchase,PURCHASE,ENABLED,2026-08-29\n"
                                                         "L,Lead,LEAD,REMOVED,2026-08-29\n"})
            prof = tmp / "p.yaml"
            prof.write_text("tracking_evidence: all good\ncampaign_objectives:\n  A: {goal_ids: [P]}\n"
                            "  B: {goal_ids: [L]}\n  C: {role: x}\n")
            ctx = Context("s", "1", ex, prof)
            self.assertIs(ctx.tracking_for_campaign("A")[0], True)
            self.assertIs(ctx.tracking_for_campaign("B")[0], False)
            self.assertIsNone(ctx.tracking_for_campaign("C")[0])
            prof.write_text("campaign_objectives:\n  A: {goal_ids: [P, X]}\n  D: {goal_ids: [X]}\n"
                            "tracking_verified:\n  X: 2026-09-30\n")
            ctx = Context("s", "1", ex, prof)
            self.assertIsNone(ctx.tracking_for_campaign("A")[0])  # every goal must be evidenced
            self.assertIsNone(ctx.tracking_for_campaign("D")[0])  # bare date is not provenance
            prof.write_text("campaign_objectives:\n  D: {goal_ids: [X]}\ntracking_verified:\n"
                            "  X: {status: verified, verified_through: 2026-08-30, source_ref: QA-7}\n")
            self.assertIsNone(Context("s", "1", ex, prof).tracking_for_campaign("D")[0])  # no verified_from
            prof.write_text("campaign_objectives:\n  D: {goal_ids: [X]}\ntracking_verified:\n"
                            "  X: {status: verified, verified_from: 2026-08-10, verified_through: 2026-08-30, source_ref: QA-7}\n")
            self.assertIsNone(Context("s", "1", ex, prof).tracking_for_campaign("D")[0])  # starts after period start
            prof.write_text("campaign_objectives:\n  D: {goal_ids: [X]}\ntracking_verified:\n"
                            "  X: {status: verified, verified_from: 2026-07-01, verified_through: 2026-08-30, source_ref: QA-7}\n")
            self.assertIs(Context("s", "1", ex, prof).tracking_for_campaign("D")[0], True)

    def test_account_level_negatives_known_empty_only_with_complete_inventory(self):
        from adsrun.negatives import effective_negatives
        base = {"account.csv": ACCOUNT + _acct(), "ad_groups.csv": "id,campaign_id\nG,C\n",
                "negative_keywords.csv": "text,match_type,level,campaign_id\nfree,PHRASE,campaign,C\n",
                "shared_negative_lists.csv": "list_id,keywords,campaign_ids\n"}
        with tempfile.TemporaryDirectory() as t:
            _, gaps = effective_negatives(Context("s", "1", _export(Path(t), base), None))
            self.assertTrue(any("account" in g for g in gaps))
        with tempfile.TemporaryDirectory() as t:
            files = {**base, "table_manifest.csv": "filename,completeness\nnegative_keywords.csv,complete\n"}
            _, gaps = effective_negatives(Context("s", "1", _export(Path(t), files), None))
            self.assertFalse(any("account" in g for g in gaps))

    def test_duplicate_rows_for_one_account_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct("1") + _acct("1", cur="USD")})
            with self.assertRaises(ContextError):
                Context("s", "1", ex, None)

    def test_shared_list_association_aliases_and_absence(self):
        from adsrun.negatives import effective_negatives
        base = {"account.csv": ACCOUNT + _acct(), "ad_groups.csv": "id,campaign_id\nG,C\n",
                "negative_keywords.csv": "text,match_type,level,campaign_id\n",
                "table_manifest.csv": "filename,completeness\nnegative_keywords.csv,complete\n"}
        for col in ("campaigns_applied", "campaign_ids"):
            with tempfile.TemporaryDirectory() as t:
                files = {**base, "shared_negative_lists.csv": f"list_id,keywords,{col}\nL,free (PHRASE),C\n"}
                scopes, _ = effective_negatives(Context("s", "1", _export(Path(t), files), None))
                self.assertEqual([(n.text, n.level) for n in scopes[("C", "G")]], [("free", "shared_list")], col)
        with tempfile.TemporaryDirectory() as t:
            scopes, gaps = effective_negatives(Context("s", "1", _export(Path(t), base), None))
            self.assertEqual(scopes[("C", "G")], [])
            self.assertTrue(any("shared_negative_lists missing" in g for g in gaps))

    def test_single_account_filter_keeps_tables(self):
        with tempfile.TemporaryDirectory() as t:
            ex = _export(Path(t), {"account.csv": ACCOUNT + _acct("1"), "keywords.csv": "id\nK\n"})
            self.assertIsNotNone(Context("s", "1", ex, None, account_id="1").table("keywords"))


def _reviewing(ctx):
    c = ctx.check("c", "c")
    f = c.finding("k", "Info", {"id": "E"}, "provisional")
    c.review("k", {"id": "E"}, "desired?", outcomes={"bad": {"severity": "Warning"}, "fine": {"severity": None}},
             provisional=f)


class Merge(unittest.TestCase):
    def _result(self):
        from adsrun.result import Result
        r = Result("s", "1", "rt")
        return r, r.check("c", "c")

    def test_same_severity_duplicates_union_evidence_and_keep_conflicts(self):
        r, c = self._result()
        c.finding("k", "Info", {"id": "E"}, "first", evidence={"a": 1, "b": 2})
        c.finding("k", "Info", {"id": "E"}, "second", evidence={"b": 3, "c": 4})
        [f] = r.findings
        self.assertEqual((f.summary, f.evidence["a"], f.evidence["b"], f.evidence["c"]), ("first", 1, 2, 4))
        self.assertEqual(f.evidence["_conflicts"], {"b": [2, 3]})
        self.assertEqual(f.evidence["_merged_summaries"], ["second"])

    def test_higher_severity_wins_and_history_survives_any_order(self):
        def emit(order):
            r, c = self._result()
            for sev, summ, b in order:
                c.finding("k", sev, {"id": "E"}, summ, evidence={"b": b})
            return r.findings[0]
        rows = [("Info", "one", 1), ("Info", "two", 2), ("Warning", "three", 3)]
        a, b = emit(rows), emit(list(reversed(rows)))
        for f in (a, b):
            self.assertEqual((f.severity, f.summary, f.evidence["b"]), ("Warning", "three", 3))
            self.assertEqual(f.evidence["_conflicts"], {"b": [1, 2, 3]})
            self.assertEqual(f.evidence["_merged_summaries"], ["one", "two"])


class ImportAgnostic(unittest.TestCase):
    def test_check_loaded_without_sys_modules_can_run(self):
        import importlib.util
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "mycheck.py").write_text("def run(ctx):\n    ctx.check('c', 'c')\n")
            spec = importlib.util.spec_from_file_location("unregistered_check", tmp / "mycheck.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ex = _export(tmp, {"account.csv": ACCOUNT + _acct()})
            self.assertEqual(cli.main("s", "1", mod.run, argv=["--export", str(ex), "--out", str(tmp / "o")]), 0)


class Finalize(unittest.TestCase):
    def _run(self, tmp, outcome):
        ex = _export(tmp, {"account.csv": ACCOUNT + _acct()})
        out = tmp / "o"
        cli.main("s", "1", _reviewing, argv=["run", "--export", str(ex), "--out", str(out)])
        rid = json.loads((out / "result.json").read_text())["ai_review"][0]["id"]
        (tmp / "d.json").write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "r"}]))
        code = cli.main("s", "1", _reviewing, argv=["finalize", "--export", str(ex), "--out", str(out),
                                                    "--decisions", str(tmp / "d.json")])
        return code, ex, out

    def test_outcomes_replace_provisional_finding(self):
        with tempfile.TemporaryDirectory() as t:
            code, _, out = self._run(Path(t), "fine")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((out / "final.json").read_text())["findings"], [])
        with tempfile.TemporaryDirectory() as t:
            _, _, out = self._run(Path(t), "bad")
            f = json.loads((out / "final.json").read_text())["findings"]
            self.assertEqual([(x["severity"], x["origin"]) for x in f], [("Warning", "ai_review")])

    def test_changed_evidence_is_stale(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _, ex, out = self._run(tmp, "fine")
            (ex / "campaigns.csv").write_text("id\nX\n")
            code = cli.main("s", "1", _reviewing, argv=["finalize", "--export", str(ex), "--out", str(out),
                                                        "--decisions", str(tmp / "d.json")])
            self.assertEqual(code, 3)

    def test_undeclared_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            code, _, out = self._run(Path(t), "Critical")
            self.assertEqual(code, 4)
            body = json.loads((out / "final.json").read_text())
            self.assertEqual(body["review_log"][0]["status"], "rejected")
            self.assertEqual(len(body["pending_review"]), 1)


if __name__ == "__main__":
    unittest.main()
