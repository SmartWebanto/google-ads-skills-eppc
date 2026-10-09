"""test_check.py — skill-169 decision boundaries on synthetic temp exports.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-169-account-portfolio-summary/tests -t skills/skill-169-account-portfolio-summary
rules:   Synthetic temp folders only; never reads the self-test oracle. Deterministic, stdlib only.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes4 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | status evidence ref tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | owner/billing/policy status evidence tests
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
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill169_check", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

START, END = date(2026, 8, 4), date(2026, 9, 2)
ACCOUNT_COLS = ["customer_id", "name", "currency_code", "time_zone", "date_range_start", "date_range_end",
                "snapshot_date", "rates_format", "money_unit", "conversion_lag_days"]


def account_row(cid="111", currency="EUR", lag="2"):
    return [cid, f"Acct {cid}", currency, "Europe/Rome", START.isoformat(), END.isoformat(), "2026-09-06",
            "fraction", "currency", lag]


class Export:
    def __init__(self, test: unittest.TestCase):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.export = self.root / "export"
        self.export.mkdir()
        self.manifest: list[str] = []
        self.profile_text = "slug: t\n"

    def table(self, name: str, header: list[str], rows: list[list], complete: bool = True):
        path = self.export / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        if complete:
            self.manifest.append(f"{name}.csv")
        return self

    def run(self, cmd="run", decisions=None, account=None) -> tuple[int, dict]:
        if self.manifest:
            with (self.export / "table_manifest.csv").open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["filename", "completeness", "truncation"])
                w.writerows([[m, "complete", "none"] for m in self.manifest])
        prof = self.root / "profile.yaml"
        prof.write_text(self.profile_text)
        out = self.root / "out"
        argv = [cmd, "--export", str(self.export), "--profile", str(prof), "--out", str(out)]
        if account:
            argv += ["--account", account]
        if decisions is not None:
            dp = self.root / "decisions.json"
            dp.write_text(json.dumps(decisions))
            argv += ["--decisions", str(dp)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=argv)
        name = "final.json" if cmd == "finalize" else "result.json"
        path = out / name
        return code, (json.loads(path.read_text()) if path.is_file() else {})


def daily_rows(start: date, end: date, impressions, cost_per_impr=0.1, cid=None, complete=None):
    """impressions: int or callable(date)->int|None."""
    rows, d = [], start
    while d <= end:
        imp = impressions(d) if callable(impressions) else impressions
        row = [d.isoformat(), imp, None if imp is None else round(imp * cost_per_impr, 2), imp and imp // 20,
               imp and imp // 400, imp and imp // 10]
        if cid is not None:
            row = [cid] + row
        if complete is not None:
            row.append(complete(d))
        rows.append(row)
        d += timedelta(days=1)
    return rows


DAILY_COLS = ["date", "impressions", "cost", "clicks", "conversions", "conversion_value"]


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def findings(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


def obs(body, check):
    return [o for o in body["observations"] if o["check"] == check]


class OfflineTests(unittest.TestCase):
    def base(self, impressions, end=END, complete=None):
        e = Export(self)
        e.table("account", ACCOUNT_COLS, [account_row()])
        cols = DAILY_COLS + (["complete_day"] if complete else [])
        e.table("custom/account_daily_metrics", cols, daily_rows(date(2026, 6, 1), end, impressions, complete=complete))
        return e

    def test_zero_run_after_steady_baseline_is_warning_with_review(self):
        e = self.base(lambda d: 0 if d >= date(2026, 9, 1) else 100)
        code, body = e.run()
        self.assertEqual(code, 0)
        f = findings(body, "account_offline")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "Warning")
        self.assertEqual(f[0]["evidence"]["zero_run_days"], 2)
        self.assertEqual(f[0]["evidence"]["baseline_impressions"], 2800)
        review = next(r for r in body["ai_review"] if r["condition_key"] == "account_offline")
        self.assertEqual(review["outcomes"]["unplanned_stop_evidenced"]["severity"], "Critical")
        self.assertEqual(review["provisional_finding"], f[0]["id"])

    def test_sporadic_account_with_longer_baseline_zero_run_is_info(self):
        gap = {date(2026, 8, 20), date(2026, 8, 21), date(2026, 8, 22)}
        e = self.base(lambda d: 0 if d >= date(2026, 9, 1) or d in gap else 100)
        _, body = e.run()
        self.assertEqual(findings(body, "account_offline"), [])
        info = findings(body, "account_offline_unqualified")
        self.assertEqual([x["severity"] for x in info], ["Info"])
        self.assertEqual(info[0]["evidence"]["longest_baseline_zero_run"], 3)

    def test_baseline_below_min_impressions_is_info(self):
        e = self.base(lambda d: 0 if d == END else 30)  # 28 * 30 = 840 < 1000
        _, body = e.run()
        self.assertEqual(findings(body, "account_offline"), [])
        self.assertEqual(len(findings(body, "account_offline_unqualified")), 1)

    def test_missing_latest_days_are_unknown_not_zero(self):
        e = self.base(100, end=date(2026, 8, 31))
        _, body = e.run()
        self.assertEqual([f for f in body["findings"] if f["check"] == "account_offline"], [])
        c = cov(body, "account_offline")
        self.assertEqual(c["status"], "partial")
        self.assertTrue(any("later days unknown" in n for n in c["notes"]))

    def test_incomplete_last_day_is_excluded(self):
        e = self.base(lambda d: 0 if d == END else 100, complete=lambda d: "false" if d == END else "true")
        _, body = e.run()
        self.assertEqual([f for f in body["findings"] if f["check"] == "account_offline"], [])
        self.assertEqual(cov(body, "account_offline")["status"], "partial")

    def test_missing_daily_table_is_skipped_with_exact_inputs(self):
        e = Export(self)
        e.table("account", ACCOUNT_COLS, [account_row()])
        _, body = e.run()
        for check in ("account_offline", "period_over_period"):
            c = cov(body, check)
            self.assertEqual(c["status"], "skipped")
            self.assertIn("custom/account_daily_metrics (file)", c["missing"])

    STATUS_COLS = ["evidence_ref", "customer_id", "status_type", "cause", "from_date", "to_date", "source"]

    def test_finalize_critical_requires_owner_status_evidence(self):
        e = self.base(lambda d: 0 if d >= date(2026, 9, 1) else 100)
        e.table("campaigns", ["id", "status"], [["C1", "PAUSED"]])
        e.table("external/account_status_evidence", self.STATUS_COLS, [
            ["BILL-1", "111", "unplanned_stop", "card declined", "2026-09-01", "", "billing notice"],
            ["PAUSE-1", "111", "planned_pause", "seasonal", "2026-09-01", "2026-09-30", "owner email"],
            ["OLD-1", "111", "unplanned_stop", "old outage", "2026-06-01", "2026-06-03", "billing"],
            ["NOSRC", "111", "unplanned_stop", "x", "2026-09-01", "", ""],
            ["OTHER", "222", "unplanned_stop", "x", "2026-09-01", "", "billing"]])
        _, body = e.run()
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "account_offline")

        def fin(outcome, proposal):
            return e.run("finalize", [{"id": rid, "outcome": outcome, "rationale": "status", "proposal": proposal}])

        for ref in ("campaigns:111:C1", "OLD-1", "NOSRC", "OTHER", "PAUSE-1"):  # status row, window, source, account, type
            self.assertEqual(fin("unplanned_stop_evidenced", {"evidence_ref": ref})[0], 4, ref)
        self.assertEqual(fin("planned_pause", {"evidence_ref": "BILL-1"})[0], 4)
        code, final = fin("unplanned_stop_evidenced", {"evidence_ref": "BILL-1"})
        self.assertEqual(code, 0)
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "account_offline"],
                         ["Critical"])
        code, final = fin("planned_pause", {"evidence_ref": "PAUSE-1"})
        self.assertEqual((code, findings(final, "account_offline")), (0, []))

    def test_multi_account_ref_must_belong_to_reviewed_account(self):
        e = Export(self)
        e.table("account", ACCOUNT_COLS, [account_row("111"), account_row("222")])
        offline = lambda d: 0 if d >= date(2026, 9, 1) else 100  # noqa: E731
        e.table("custom/account_daily_metrics", ["customer_id"] + DAILY_COLS,
                daily_rows(date(2026, 6, 1), END, offline, cid="111")
                + daily_rows(date(2026, 6, 1), END, offline, cid="222"))
        e.table("external/account_status_evidence", self.STATUS_COLS, [
            ["P111", "111", "planned_pause", "seasonal", "2026-09-01", "", "owner"],
            ["P222", "222", "planned_pause", "seasonal", "2026-09-01", "", "owner"]])
        self.assertEqual(e.run()[0], 0)
        out = e.root / "out" / "accounts" / "111"
        rid = next(r["id"] for r in json.loads((out / "result.json").read_text())["ai_review"]
                   if r["condition_key"] == "account_offline")
        dp = e.root / "d.json"

        def fin(ref):
            dp.write_text(json.dumps([{"id": rid, "outcome": "planned_pause", "rationale": "paused",
                                       "proposal": {"evidence_ref": ref}}]))
            argv = ["finalize", "--export", str(e.export), "--profile", str(e.root / "profile.yaml"),
                    "--out", str(out), "--account", "111", "--decisions", str(dp)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=argv)

        self.assertEqual(fin("P222"), 4)
        self.assertEqual(fin("P111"), 0)


class KpiAndDeltaTests(unittest.TestCase):
    CM_COLS = ["campaign_id", "channel_type", "impressions", "clicks", "cost", "conversions", "conversion_value",
               "search_impression_share", "search_budget_lost_is", "search_rank_lost_is"]

    def export(self, goals: dict, lag="2", cm_rows=None):
        e = Export(self)
        e.table("account", ACCOUNT_COLS, [account_row(lag=lag)])
        e.table("campaigns", ["id", "channel_type", "goal_ids"], [[c, "SEARCH", g] for c, g in goals.items()])
        e.table("campaign_metrics", self.CM_COLS, cm_rows or [
            ["1", "SEARCH", 10000, 500, 400.0, 20, 2000, 0.5, 0.2, 0.3],
            ["2", "SEARCH", 6000, 300, 200.0, 10, 800, "< 10%", 0.1, 0.8],
        ])
        return e

    def kpis(self, body):
        return obs(body, "account_kpis")[0]["data"]

    def test_cpa_only_when_converting_campaigns_share_one_goal_set(self):
        _, mixed = self.export({"1": "g1", "2": "g2"}).run()
        self.assertIsNone(self.kpis(mixed)["cpa"])
        self.assertEqual(cov(mixed, "account_kpis")["status"], "partial")
        _, same = self.export({"1": "g1", "2": "g1"}).run()
        self.assertAlmostEqual(self.kpis(same)["cpa"], 20.0)
        self.assertAlmostEqual(self.kpis(same)["roas"], 2800 / 600, places=5)

    def test_censored_impression_share_stays_unknown(self):
        _, body = self.export({"1": "g1", "2": "g1"}).run()
        c = cov(body, "impression_share_summary")
        self.assertEqual(c["status"], "partial")
        data = obs(body, "impression_share_summary")[0]["data"]
        self.assertEqual(data["campaigns"], 1)  # the '< 10%' row is excluded, not counted as 0
        self.assertAlmostEqual(data["impression_share"], 0.5)

    def test_zero_impressions_has_undefined_ctr(self):
        e = self.export({"1": "g1"}, cm_rows=[["1", "SEARCH", 0, 0, 0, 0, 0, None, None, None]])
        _, body = e.run()
        self.assertIsNone(self.kpis(body)["ctr"])
        self.assertIsNone(self.kpis(body)["cpa"])

    def test_duplicate_grain_stops_totals(self):
        row = ["1", "SEARCH", 100, 5, 4.0, 1, 10, 0.5, 0.1, 0.1]
        _, body = self.export({"1": "g1"}, cm_rows=[row, row]).run()
        self.assertEqual(obs(body, "account_kpis"), [])
        self.assertEqual(cov(body, "account_kpis")["status"], "partial")

    def test_period_deltas_respect_gates_and_maturity(self):
        e = self.export({"1": "g1", "2": "g1"})
        prev_start = START - timedelta(days=30)
        e.table("custom/account_daily_metrics", DAILY_COLS, daily_rows(prev_start, END, 100))
        _, body = e.run()
        deltas = obs(body, "period_over_period")[0]["data"]
        self.assertEqual(deltas["previous_window"], [prev_start.isoformat(), (START - timedelta(days=1)).isoformat()])
        self.assertIn("ctr", deltas["deltas"])            # 3000 impressions each side >= 1000
        self.assertIn("conversion_rate", deltas["deltas"])  # 150 clicks each side >= 100
        self.assertNotIn("cpa", deltas["deltas"])         # 0 conversions per window < min_conversions

    def test_unknown_lag_withholds_conversion_deltas(self):
        e = self.export({"1": "g1", "2": "g1"}, lag="")
        e.table("custom/account_daily_metrics", DAILY_COLS, daily_rows(START - timedelta(days=30), END, 100))
        _, body = e.run()
        d = obs(body, "period_over_period")[0]["data"]["deltas"]
        self.assertIn("impressions", d)
        self.assertNotIn("conversions", d)
        self.assertNotIn("conversion_rate", d)
        self.assertEqual(cov(body, "period_over_period")["status"], "partial")

    def test_incomplete_prior_period_blocks_comparison(self):
        e = self.export({"1": "g1"})
        e.table("custom/account_daily_metrics", DAILY_COLS, daily_rows(START - timedelta(days=10), END, 100))
        _, body = e.run()
        self.assertEqual(obs(body, "period_over_period"), [])
        self.assertEqual(cov(body, "period_over_period")["status"], "partial")


class PortfolioTests(unittest.TestCase):
    CM = ["customer_id", "campaign_id", "impressions", "clicks", "cost", "conversions", "conversion_value"]

    def export(self, profile="", rates=None):
        e = Export(self)
        e.table("account", ACCOUNT_COLS, [account_row("111", "EUR"), account_row("222", "USD")])
        e.table("campaign_metrics", self.CM, [["111", "1", 1000, 100, 50.0, 5, 200],
                                              ["222", "2", 2000, 200, 100.0, 10, 500]])
        if rates is not None:
            e.table("external/exchange_rates", ["date", "from", "to", "rate", "source"], rates, complete=False)
        e.profile_text = "slug: t\n" + profile
        return e

    def load(self, e, acct):
        return json.loads((e.root / "out" / "accounts" / acct / "result.json").read_text())

    def test_multi_account_groups_by_currency_and_never_sums_across(self):
        e = self.export()
        code, index = e.run()
        self.assertEqual(code, 0)
        self.assertEqual(index["schema"], "adsrun-multi/1")
        anchor, other = self.load(e, "111"), self.load(e, "222")
        groups = [o["data"] for o in obs(anchor, "portfolio_totals") if "currency" in o["data"]]
        self.assertEqual(sorted(g["currency"] for g in groups), ["EUR", "USD"])
        self.assertEqual({g["currency"]: g["totals"]["cost"] for g in groups}, {"EUR": 50, "USD": 100})
        self.assertEqual(cov(other, "portfolio_totals")["status"], "not_applicable")
        self.assertEqual(cov(anchor, "currency_conversion")["status"], "not_applicable")
        self.assertEqual(obs(other, "account_kpis")[0]["data"]["cost"], 100)  # partitioned per account

    def test_conversion_needs_rate_dated_at_report_end(self):
        wrong = self.export("portfolio: {reporting_currency: EUR}\n",
                            rates=[["2026-08-01", "USD", "EUR", "0.9", "ECB"]])
        wrong.run()
        body = self.load(wrong, "111")
        self.assertEqual(cov(body, "currency_conversion")["status"], "partial")
        self.assertFalse(any("Portfolio total converted" in o["text"] for o in obs(body, "currency_conversion")))
        right = self.export("portfolio: {reporting_currency: EUR}\n",
                            rates=[[END.isoformat(), "USD", "EUR", "0.9", "ECB reference"]])
        right.run()
        body = self.load(right, "111")
        total = next(o["data"] for o in obs(body, "currency_conversion") if "Portfolio total" in o["text"])
        self.assertAlmostEqual(total["cost"], 50 + 100 * 0.9)
        self.assertEqual(cov(body, "currency_conversion")["status"], "completed")

    def test_conflicting_or_unsourced_rates_block_conversion(self):
        for rates in ([[END.isoformat(), "USD", "EUR", "0.9", "a"], [END.isoformat(), "USD", "EUR", "0.95", "b"]],
                      [[END.isoformat(), "USD", "EUR", "0.9", ""]]):
            e = self.export("portfolio: {reporting_currency: EUR}\n", rates=rates)
            e.run()
            body = self.load(e, "111")
            self.assertEqual(cov(body, "currency_conversion")["status"], "partial")

    def test_missing_rates_file_is_skipped(self):
        e = self.export("portfolio: {reporting_currency: EUR}\n")
        e.run()
        c = cov(self.load(e, "111"), "currency_conversion")
        self.assertEqual(c["status"], "skipped")
        self.assertIn("external/exchange_rates (file)", c["missing"])


if __name__ == "__main__":
    unittest.main()
