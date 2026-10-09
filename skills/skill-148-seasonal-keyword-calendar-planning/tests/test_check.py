"""test_check.py — decision-boundary tests for skill-148 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-148-seasonal-keyword-calendar-planning/tests
rules:   Temp folders only; stdlib only; no wording assertions — assert condition keys, severities and coverage.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill148_check", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
cli = M.cli


def main(*argv) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(M.SKILL, M.VERSION, M.run, argv=list(argv))

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
           "money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-04,2026-09-02,2026-09-06,fraction,currency,interaction_date,{lag}\n")
PLAN_COLS = ("event_id,campaign_id,name,start_at,end_at,timezone,objective,offer,expected_cvr_change,rationale,owner,"
             "approval_status,normal_baseline_dates,landing_page_ref,stock_or_capacity,draft_copy_ref,"
             "approval_dependencies,planned_launch_at,planned_pause_at")


def plan_row(**kw):
    row = {"event_id": "bf", "campaign_id": "C1", "name": "Black Friday", "start_at": "2026-11-27",
           "end_at": "2026-11-30", "timezone": "Europe/Rome", "objective": "sales", "offer": "20% off drills",
           "expected_cvr_change": "", "rationale": "", "owner": "ana", "approval_status": "approved",
           "normal_baseline_dates": "2025-10-01..2025-10-28", "landing_page_ref": "lp-bf",
           "stock_or_capacity": "500", "draft_copy_ref": "draft-1", "approval_dependencies": "",
           "planned_launch_at": "2026-11-20", "planned_pause_at": "2026-12-01"}
    row.update(kw)
    return ",".join(row[c] for c in PLAN_COLS.split(","))


PAST = plan_row(start_at="2025-11-28", end_at="2025-12-01", approval_status="done")
HIST_HEAD = "campaign_id,ad_group_id,query,matched_keyword_id,date,match_type,impressions,clicks,cost,conversions,conversion_value\n"


def hist(query, clicks, conv, date="2025-11-28", gid="G1"):
    return f"C1,{gid},{query},K1,{date},PHRASE,1000,{clicks},{clicks * 0.5},{conv},{conv * 40}\n"


def build(tmp: Path, *, plan=None, history=None, lag="2", ads=None, drop=()) -> Path:
    files = {
        "account.csv": ACCOUNT.format(lag=lag),
        "campaigns.csv": "id,name,status,channel_type\nC1,Search,ENABLED,SEARCH\n",
        "ad_groups.csv": "id,campaign_id,status\nG1,C1,ENABLED\n",
        "keywords.csv": "id,campaign_id,ad_group_id,text,match_type,status\nK1,C1,G1,drill,PHRASE,ENABLED\n",
        "search_terms.csv": "search_term,campaign_id,ad_group_id,clicks\nbest drill,C1,G1,40\n",
        "negative_keywords.csv": "text,match_type,level,campaign_id,ad_group_id\nsale,PHRASE,campaign,C1,\n",
        "shared_negative_lists.csv": "list_id,name,keywords,campaigns_applied\n",
        "ads.csv": ads or "id,campaign_id,ad_group_id,status,approval_status\nA1,C1,G1,ENABLED,APPROVED\n",
        "external/seasonal_keyword_plan.csv": PLAN_COLS + "\n" + "\n".join(plan or [plan_row(), PAST]) + "\n",
        "custom/seasonal_query_history.csv": HIST_HEAD + "".join(history or []),
    }
    for d in drop:
        files.pop(d)
    names = [n for n in files]
    files["table_manifest.csv"] = "filename,completeness,period_end\n" + "".join(
        f"{n},complete,2026-12-31\n" for n in names)
    root = tmp / "export"
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)

    def run_check(self, **kw) -> dict:
        ex = build(self.tmp, **kw)
        out = self.tmp / "out"
        self.assertEqual(main("run", "--export", str(ex), "--out", str(out)), 0)
        return json.loads((out / "result.json").read_text())

    def fresh(self, **kw) -> dict:
        """Run again in a new temp folder (counterexample in the same test)."""
        self.setUp()
        return self.run_check(**kw)

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)


class HistoricalCandidates(Base):
    def test_gated_converting_query_is_candidate_and_thin_query_is_not(self):
        body = self.run_check(history=[hist("black friday drill", 150, 5), hist("cordless drill", 20, 1)])
        cands = self.keys(body, "historical_query_candidate")
        self.assertEqual([f["entity"]["query"] for f in cands], ["black friday drill"])
        self.assertEqual(cands[0]["severity"], "Info")
        self.assertIsNone(cands[0]["evidence"]["cpa"])  # 5 conversions < min_conversions 15

    def test_immature_account_gives_no_candidates_and_partial(self):
        body = self.run_check(history=[hist("black friday drill", 150, 5)], lag="")
        self.assertEqual(self.keys(body, "historical_query_candidate"), [])
        self.assertEqual(self.cov(body, "historical_queries")["status"], "partial")

    def test_obsolete_year_language_is_not_a_candidate(self):
        body = self.run_check(history=[hist("black friday 2025 drill", 150, 5), hist("black friday 2026 drill", 150, 5)])
        self.assertEqual([f["entity"]["query"] for f in self.keys(body, "historical_query_candidate")],
                         ["black friday 2026 drill"])

    def test_rows_outside_prior_window_are_ignored(self):
        body = self.run_check(history=[hist("black friday drill", 150, 5, date="2025-11-01")])
        self.assertEqual(self.keys(body, "historical_query_candidate"), [])

    def test_missing_history_file_skips_dependent_checks_only(self):
        body = self.run_check(drop=("custom/seasonal_query_history.csv",))
        hq = self.cov(body, "historical_queries")
        self.assertEqual(hq["status"], "skipped")
        self.assertIn("custom/seasonal_query_history (file)", hq["missing"])
        self.assertEqual(self.cov(body, "launch_timing")["status"], "completed")


class Coverage(Base):
    def test_negative_blocked_event_query_goes_to_review_with_warning_for_approved_event(self):
        body = self.run_check(history=[hist("black friday sale drill", 150, 5), hist("black friday drill", 150, 5)])
        reviews = [r for r in body["ai_review"] if r["condition_key"] == "event_query_negative_conflict"]
        self.assertEqual([r["entity"]["query"] for r in reviews], ["black friday sale drill"])
        self.assertEqual(reviews[0]["outcomes"]["relevant_blocked"]["severity"], "Warning")
        self.assertEqual({f["severity"] for f in self.keys(body, "event_query_negative_conflict")}, {"Info"})

    def test_unapproved_event_conflict_caps_at_info(self):
        body = self.run_check(plan=[plan_row(approval_status="draft"), PAST],
                              history=[hist("black friday sale drill", 150, 5)])
        review = next(r for r in body["ai_review"] if r["condition_key"] == "event_query_negative_conflict")
        self.assertEqual(review["outcomes"]["relevant_blocked"]["severity"], "Info")

    def test_unreached_candidate_is_coverage_hypothesis_but_literal_or_served_is_not(self):
        body = self.run_check(history=[hist("black friday hammer", 150, 5), hist("black friday drill", 150, 5),
                                       hist("best drill", 150, 5)])
        self.assertEqual([f["entity"]["query"] for f in self.keys(body, "coverage_unverified")],
                         ["black friday hammer"])

    def test_accepted_relevant_block_becomes_warning_on_finalize(self):
        ex = build(self.tmp, history=[hist("black friday sale drill", 150, 5)])
        out = self.tmp / "out"
        main("run", "--export", str(ex), "--out", str(out))
        body = json.loads((out / "result.json").read_text())
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "event_query_negative_conflict")
        dec = self.tmp / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": "relevant_blocked", "rationale": "event offer query"}]))
        code = main("finalize", "--export", str(ex), "--out", str(out), "--decisions", str(dec))
        self.assertEqual(code, 0)
        final = json.loads((out / "final.json").read_text())
        sev = [f["severity"] for f in final["findings"] if f["condition_key"] == "event_query_negative_conflict"]
        self.assertEqual(sev, ["Warning"])


class CalendarReadinessTiming(Base):
    def test_incomplete_row_is_info_and_complete_row_is_clean(self):
        body = self.run_check(plan=[plan_row(offer="", owner=""), PAST])
        f = self.keys(body, "incomplete_calendar")
        self.assertEqual(len(f), 1)
        self.assertEqual(sorted(f[0]["evidence"]["missing_fields"]), ["offer", "owner"])
        self.assertEqual(self.keys(self.fresh(), "incomplete_calendar"), [])

    def test_unknown_campaign_is_incomplete(self):
        body = self.run_check(plan=[plan_row(campaign_id="C9")])
        self.assertEqual(len(self.keys(body, "incomplete_calendar")), 1)

    def test_disapproved_draft_ad_is_warning_approved_ad_is_not(self):
        ads = "id,campaign_id,ad_group_id,status,approval_status\nA1,C1,G1,ENABLED,DISAPPROVED\n"
        body = self.run_check(plan=[plan_row(draft_copy_ref="A1"), PAST], ads=ads)
        self.assertEqual([f["severity"] for f in self.keys(body, "draft_ad_unavailable")], ["Warning"])
        ok = self.fresh(plan=[plan_row(draft_copy_ref="A1"), PAST])
        self.assertEqual(self.keys(ok, "draft_ad_unavailable"), [])

    def test_missing_draft_for_approved_event_is_review_not_deterministic_warning(self):
        body = self.run_check(plan=[plan_row(draft_copy_ref=""), PAST])
        review = [r for r in body["ai_review"] if r["condition_key"] == "launch_content_readiness"]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["outcomes"]["required_content_unavailable"]["severity"], "Warning")
        self.assertEqual(body["counts"]["Warning"], 0)
        draft = self.fresh(plan=[plan_row(draft_copy_ref="", approval_status="draft"), PAST])
        self.assertFalse(any(r["condition_key"] == "launch_content_readiness" for r in draft["ai_review"]))

    def test_launch_after_start_is_info_no_lead_time_rule(self):
        late = self.run_check(plan=[plan_row(planned_launch_at="2026-11-28"), PAST])
        self.assertEqual(len(self.keys(late, "launch_after_event_start")), 1)
        tight = self.fresh(plan=[plan_row(planned_launch_at="2026-11-26"), PAST])
        self.assertEqual([f for f in tight["findings"] if f["check"] == "launch_timing"], [])

    def test_missing_plan_skips_everything_without_findings(self):
        body = self.run_check(drop=("external/seasonal_keyword_plan.csv",))
        self.assertEqual({c["status"] for c in body["coverage"]}, {"skipped"})
        self.assertEqual(body["findings"], [])

    def test_only_past_events_is_not_applicable(self):
        body = self.run_check(plan=[PAST])
        self.assertEqual(self.cov(body, "historical_queries")["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
