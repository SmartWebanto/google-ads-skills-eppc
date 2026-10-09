"""test_check.py — skill-174 Windsor MCP intake: plan, strict normalize, share aggregation, join readiness.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-174-windsor-mcp-intake/tests -t skills/skill-174-windsor-mcp-intake
rules:   Synthetic get_data results in temp folders only (shapes observed live 2026-09-28: floats for counts,
         dashed account IDs, budget resource names, fractions incl. censored 0.0999/0.9001). Tests assert
         behavior (exit codes, values, refusals, coverage), never wording. The consumer test runs the real
         skill-121 recipe on the normalized export; the search-term import test runs the real skill-173
         preflight/apply (its own test fixtures) and imports that export.
agent:   claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor | initial Windsor intake tests
agent:   claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor_b | real skill-173 import; local phone/email blanking
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check174", HERE / "scripts" / "check.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
_spec121 = importlib.util.spec_from_file_location(
    "check121_for_174", HERE.parent / "skill-121-impression-share-loss-analysis" / "scripts" / "check.py")
M121 = importlib.util.module_from_spec(_spec121)
_spec121.loader.exec_module(M121)
_spec173t = importlib.util.spec_from_file_location(
    "test173_for_174", HERE.parent / "skill-173-export-intake-preflight" / "tests" / "test_check.py")
T173 = importlib.util.module_from_spec(_spec173t)
_spec173t.loader.exec_module(T173)

ACC = "123-456-7890"
A = {"account_id": ACC}


def rec(**kw):
    return {**A, **kw}


def base_records() -> dict[str, list[dict]]:
    """One record set per pull, in the value shapes Windsor returned live."""
    day = lambda d, cid, imp, cost, is_, lb, lr: rec(  # noqa: E731
        date=d, campaign_id=cid, impressions=float(imp), clicks=float(imp // 10), cost=cost, conversions=1.0,
        conversions_value=0.0, search_impression_share=is_, search_budget_lost_impression_share=lb,
        search_rank_lost_impression_share=lr)
    return {
        "account": [rec(account_name="Acme", account_currency_code="EUR", account_time_zone="Europe/Rome",
                        auto_tagging_enabled="True")],
        "campaigns": [
            rec(campaign_id="111", campaign_name="Search A", campaign_status="ENABLED",
                advertising_channel_type="SEARCH", advertising_channel_sub_type="UNSPECIFIED",
                bidding_strategy_type="MAXIMIZE_CONVERSIONS", budget_id="customers/1234567890/campaignBudgets/901",
                budget_amount=50.0, period="DAILY", network_settings_target_partner_search_network=False,
                network_settings_target_content_network=False,
                geo_target_type_setting_positive_geo_target_type="PRESENCE", end_date=None),
            rec(campaign_id="222", campaign_name="Display B", campaign_status="PAUSED",
                advertising_channel_type="DISPLAY", advertising_channel_sub_type=None,
                bidding_strategy_type="MANUAL_CPC", budget_id="customers/1234567890/campaignBudgets/902",
                budget_amount=900.0, period="CUSTOM_PERIOD", network_settings_target_partner_search_network=False,
                network_settings_target_content_network=True,
                geo_target_type_setting_positive_geo_target_type="PRESENCE_OR_INTEREST",
                end_date="2037-12-30 23:59:59")],
        "campaign_metrics": [day("2026-09-01", "111", 100, 10.5, 0.5, 0.2, 0.3),
                             day("2026-09-02", "111", 100, 4.5, 0.25, 0.5, 0.25),
                             rec(date="2026-09-01", campaign_id="222", impressions=500.0, clicks=5.0, cost=2.0,
                                 conversions=0.0, conversions_value=0.0, search_impression_share=None,
                                 search_budget_lost_impression_share=None, search_rank_lost_impression_share=None)],
        "ad_groups": [rec(campaign_id="111", ad_group_id="333", ad_group_name="AG", ad_group_status="ENABLED",
                          ad_group_type="SEARCH_STANDARD")],
        "keywords": [
            rec(campaign_id="111", ad_group_id="333", criterion_id="444", ad_group_criterion_keyword_text="red shoes",
                ad_group_criterion_keyword_match_type="PHRASE", keyword_status="ENABLED",
                ad_group_criterion_negative=False, quality_info_quality_score=7.0,
                quality_info_creative_quality_score="ABOVE_AVERAGE", quality_info_post_click_quality_score="AVERAGE",
                quality_info_search_predicted_ctr="UNKNOWN"),
            rec(campaign_id="111", ad_group_id="333", criterion_id="445", ad_group_criterion_keyword_text="free",
                ad_group_criterion_keyword_match_type="BROAD", keyword_status="ENABLED",
                ad_group_criterion_negative=True, quality_info_quality_score=None,
                quality_info_creative_quality_score=None, quality_info_post_click_quality_score=None,
                quality_info_search_predicted_ctr=None),
            rec(campaign_id="111", ad_group_id="333", criterion_id="446", ad_group_criterion_keyword_text=None,
                ad_group_criterion_keyword_match_type=None, keyword_status="ENABLED",
                ad_group_criterion_negative=False, quality_info_quality_score=None,
                quality_info_creative_quality_score=None, quality_info_post_click_quality_score=None,
                quality_info_search_predicted_ctr=None)],
        "keyword_metrics": [rec(campaign_id="111", ad_group_id="333", criterion_id="444",
                                ad_group_criterion_keyword_text="red shoes", quality_info_quality_score=7.0,
                                impressions=150.0, clicks=15.0, cost=12.0, conversions=1.5, conversions_value=0.0)],
        "ads": [rec(campaign_id="111", ad_group_id="333", ad_group_ad_ad_id="555",
                    ad_group_ad_ad_type="RESPONSIVE_SEARCH_AD", ad_group_ad_status="ENABLED",
                    ad_group_ad_ad_responsive_search_ad_headlines=json.dumps(
                        [{"text": "Red shoes", "pinned_field": "HEADLINE_1"}, {"text": "Free delivery"}]),
                    ad_group_ad_ad_responsive_search_ad_descriptions=[{"text": "Shop now."}],
                    ad_group_ad_ad_final_urls='["https://example.com/shoes"]', ad_group_ad_ad_strength="GOOD",
                    ad_group_ad_policy_summary_approval_status="APPROVED",
                    ad_group_ad_policy_summary_policy_topic_entries="[]")],
        "ad_metrics": [rec(campaign_id="111", ad_group_id="333", ad_group_ad_ad_id="555", impressions=200.0,
                           clicks=20.0, cost=15.0, conversions=2.0, conversions_value=0.0)],
        "campaign_negatives": [
            rec(campaign_id="111", campaign_criterion_keyword_text="used", campaign_criterion_keyword_match_type="EXACT",
                campaign_criterion_negative=True),
            rec(campaign_id="111", campaign_criterion_keyword_text=None, campaign_criterion_keyword_match_type=None,
                campaign_criterion_negative=False)],
        "conversion_actions": [rec(conversion_action_id="customers/1234567890/conversionActions/777",
                                   conversion_action_name="Purchase", conversion_action_category="PURCHASE",
                                   conversion_action_status="ENABLED", conversion_action_type="WEBPAGE",
                                   conversion_action_counting_type="MANY_PER_CLICK",
                                   conversion_action_primary_for_goal=True,
                                   conversion_action_click_through_lookback_window_days=30.0)],
    }


def quiet(fn, *a, **kw):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = fn(*a, **kw)
    return code, err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.work = self.tmp / "windsor"
        self.out = self.tmp / "export"

    def make(self, records=None, chunk_days=0, pulls=None, tamper=None, date_from="2026-09-01", date_to="2026-09-02"):
        pulls = list(M.PULLS) if pulls is None else pulls
        code, err = quiet(M.plan, self.work, ACC, date_from, date_to, "2026-09-03", chunk_days, pulls)
        self.assertEqual(code, 0, err)
        p = json.loads((self.work / "plan.json").read_text())
        records = records or base_records()
        for c in p["calls"]:
            recs = records[c["pull"]]
            if c["pull"] in M.DATED and chunk_days:
                recs = [r for r in recs if "date" not in r or c["arguments"]["date_from"] <= r["date"]
                        <= c["arguments"]["date_to"]]
            body = {"schema": M.RAW_SCHEMA, "pull_id": c["pull_id"], "arguments": c["arguments"], "records": recs}
            if tamper:
                body = tamper(c, body)
            if body is not None:
                (self.work / c["file"]).write_text(body if isinstance(body, str) else json.dumps(body))
        return p

    def normalize(self, lag="7", skip=(), search_terms_from=None):
        return quiet(M.normalize, self.work / "plan.json", None, self.out, lag, skip, search_terms_from)

    def export173(self, name="e173", currency="EUR", start="2026-09-01", basis="interaction_date",
                  customer="1234567890", note="confirmed via skill-173 intake", terms=("red shoes cheap",)):
        """Minimal skill-173 apply output: account.csv, search_terms.csv, table_manifest.csv."""
        d = self.tmp / name
        d.mkdir()
        (d / "account.csv").write_text(
            "customer_id,currency_code,date_range_start,date_range_end,money_unit,conversion_date_basis\n"
            f"{customer},{currency},{start},2026-09-02,currency,{basis}\n")
        (d / "search_terms.csv").write_text("search_term,campaign_id,ad_group_id,impressions,clicks,cost,conversions\n"
                                            + "".join(f"{t},111,333,40,4,3,0\n" for t in terms))
        (d / "table_manifest.csv").write_text(
            "filename,source,row_count,completeness,truncation,notes\n"
            f"account.csv,intake answers,1,complete,none,{note}\n"
            "search_terms.csv,Google Ads UI download,1,complete,visible terms only (privacy thresholds),"
            "totals rows removed\n")
        return d

    def table(self, name):
        with open(self.out / f"{name}.csv", newline="") as f:
            return list(csv.DictReader(f))


class Plan174(Base):
    def test_plan_uses_only_get_data_and_always_pulls_account(self):
        p = M.make_plan(ACC, "2026-09-01", "2026-09-10", "2026-09-11", 0, ["ads"])
        self.assertEqual([c["pull"] for c in p["calls"]], ["account", "ads"])
        self.assertTrue(all(c["tool"] == "get_data" for c in p["calls"]))
        self.assertFalse(set(p["read_tools"]) & set(p["forbidden_tools"]))
        self.assertIn("execute_action", p["forbidden_tools"])

    def test_chunks_are_disjoint_and_cover_the_window_for_dated_pulls_only(self):
        p = M.make_plan(ACC, "2026-09-01", "2026-09-10", "2026-09-11", 4)
        st = [c["arguments"] for c in p["calls"] if c["pull"] == "keyword_metrics"]
        self.assertEqual([(a["date_from"], a["date_to"]) for a in st],
                         [("2026-09-01", "2026-09-04"), ("2026-09-05", "2026-09-08"), ("2026-09-09", "2026-09-10")])
        self.assertEqual(sum(c["pull"] == "campaigns" for c in p["calls"]), 1)

    def test_search_terms_can_never_be_planned_through_mcp(self):
        default = M.make_plan(ACC, "2026-09-01", "2026-09-10", "2026-09-11")
        fields = {f for c in default["calls"] for f in c["arguments"]["fields"]}
        self.assertFalse({"search_term", "search_term_view_search_term"} & fields)
        with self.assertRaises(M.IntakeError):
            M.make_plan(ACC, "2026-09-01", "2026-09-10", "2026-09-11", 0, ["search_terms"])

    def test_incomplete_day_or_bad_account_is_rejected(self):
        with self.assertRaises(M.IntakeError):
            M.make_plan(ACC, "2026-09-01", "2026-09-11", "2026-09-11")
        with self.assertRaises(M.IntakeError):
            M.make_plan("1234", "2026-09-01", "2026-09-10", "2026-09-11")


class Normalize174(Base):
    def test_end_to_end_values_units_and_routing(self):
        self.make()
        code, err = self.normalize()
        self.assertEqual(code, 0, err)
        acc = self.table("account")[0]
        self.assertEqual((acc["currency_code"], acc["money_unit"], acc["rates_format"], acc["auto_tagging"],
                          acc["conversion_lag_days"], acc["conversion_date_basis"]),
                         ("EUR", "currency", "fraction", "true", "7", "interaction_date"))
        camps = {r["id"]: r for r in self.table("campaigns")}
        self.assertEqual(camps["111"]["budget_id"], "901")
        self.assertEqual(camps["111"]["daily_budget"], "50")
        self.assertEqual(camps["222"]["daily_budget"], "", "non-daily budget must not become daily_budget")
        self.assertEqual(camps["111"]["channel_subtype"], "")
        self.assertEqual(camps["222"]["end_date"], "2037-12-30")
        kws = self.table("keywords")
        self.assertEqual([k["id"] for k in kws], ["444"], "negatives and non-keyword criteria leave keywords")
        self.assertEqual((kws[0]["quality_score"], kws[0]["ad_relevance"], kws[0]["expected_ctr"]),
                         ("7", "ABOVE_AVERAGE", ""))
        negs = sorted((r["level"], r["text"], r["match_type"]) for r in self.table("negative_keywords"))
        self.assertEqual(negs, [("ad_group", "free", "BROAD"), ("campaign", "used", "EXACT")])
        ads = self.table("ads")[0]
        self.assertEqual((ads["headlines"], ads["descriptions"], ads["final_url"], ads["policy_topics"]),
                         ("Red shoes | Free delivery", "Shop now.", "https://example.com/shoes", ""))
        ca = self.table("conversion_actions")[0]
        self.assertEqual((ca["id"], ca["counting"], ca["primary_for_goal"], ca["click_window_days"]),
                         ("777", "every", "true", "30"))
        km = self.table("keyword_metrics")[0]
        self.assertEqual((km["impressions"], km["quality_score"]), ("150", "7"))
        man = {r["filename"]: r for r in self.table("table_manifest")}
        self.assertTrue(man["negative_keywords.csv"]["completeness"].startswith("partial"))
        self.assertTrue(man["conversion_actions.csv"]["completeness"].startswith("partial"))
        self.assertEqual(man["campaigns.csv"]["completeness"], "complete")
        self.assertFalse((self.out / "search_terms.csv").exists())

    def test_campaign_shares_are_eligible_weighted_not_averaged(self):
        self.make()
        self.assertEqual(self.normalize()[0], 0)
        m = {r["campaign_id"]: r for r in self.table("campaign_metrics")}
        # day1: 100 impr / 0.5 → 200 eligible; day2: 100 / 0.25 → 400 eligible
        self.assertAlmostEqual(float(m["111"]["search_impression_share"]), 200 / 600)
        self.assertAlmostEqual(float(m["111"]["search_budget_lost_is"]), (200 * 0.2 + 400 * 0.5) / 600)
        self.assertAlmostEqual(float(m["111"]["search_rank_lost_is"]), (200 * 0.3 + 400 * 0.25) / 600)
        self.assertEqual((m["111"]["impressions"], m["111"]["cost"]), ("200", "15"))
        self.assertEqual(m["222"]["search_impression_share"], "", "no shares at all stays unknown, not withheld")

    def test_multi_day_shares_withheld_unless_search_only_with_every_day(self):
        r = base_records()
        r["campaigns"][0]["network_settings_target_partner_search_network"] = True  # impressions include partners
        self.make(records=r)
        self.assertEqual(self.normalize()[0], 0)
        m = {x["campaign_id"]: x for x in self.table("campaign_metrics")}
        self.assertEqual(m["111"]["search_impression_share"], "withheld")
        r2 = base_records()
        r2["campaign_metrics"].pop(1)  # one day of the 2-day window has no row
        self.work, self.out = self.tmp / "w2", self.tmp / "e2"
        self.make(records=r2)
        self.assertEqual(self.normalize()[0], 0)
        m2 = {x["campaign_id"]: x for x in self.table("campaign_metrics")}
        self.assertEqual(m2["111"]["search_budget_lost_is"], "withheld")
        r3 = base_records()
        r3["campaign_metrics"] = [x for x in r3["campaign_metrics"] if x["date"] == "2026-09-01"]
        r3["campaign_metrics"][0]["search_rank_lost_impression_share"] = 0.9001
        self.work, self.out = self.tmp / "w3", self.tmp / "e3"
        self.make(records=r3, date_to="2026-09-01")
        self.assertEqual(self.normalize()[0], 0)
        m3 = {x["campaign_id"]: x for x in self.table("campaign_metrics")}
        self.assertEqual((m3["111"]["search_impression_share"], m3["111"]["search_budget_lost_is"],
                          m3["111"]["search_rank_lost_is"]), ("0.5", "0.2", "withheld"))

    def test_censored_day_makes_the_period_share_withheld(self):
        r = base_records()
        r["campaign_metrics"][1]["search_budget_lost_impression_share"] = 0.9001
        self.make(records=r)
        self.assertEqual(self.normalize()[0], 0)
        m = {x["campaign_id"]: x for x in self.table("campaign_metrics")}
        self.assertEqual(m["111"]["search_budget_lost_is"], "withheld")
        self.assertNotEqual(m["111"]["search_rank_lost_is"], "withheld")
        r2 = base_records()
        r2["campaign_metrics"][0]["search_impression_share"] = 0.0999
        self.work, self.out = self.tmp / "w2", self.tmp / "e2"
        self.make(records=r2)
        self.assertEqual(self.normalize()[0], 0)
        m2 = {x["campaign_id"]: x for x in self.table("campaign_metrics")}
        self.assertEqual({m2["111"][c] for c in ("search_impression_share", "search_budget_lost_is")}, {"withheld"})

    def test_chunks_are_summed_and_overlaps_refused(self):
        r = base_records()  # keyword_metrics records carry no date, so each 1-day chunk returns them once
        self.make(records=r, chunk_days=1)
        self.assertEqual(self.normalize()[0], 0)
        self.assertEqual(self.table("keyword_metrics")[0]["impressions"], "300")
        self.assertEqual(self.table("campaign_metrics")[0]["impressions"], "200")
        r2 = base_records()
        r2["campaign_metrics"].append(dict(r2["campaign_metrics"][0]))
        self.work, self.out = self.tmp / "w2", self.tmp / "e2"
        self.make(records=r2)
        code, _ = self.normalize()
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())

    def test_money_sums_are_exact_decimal(self):
        r = base_records()
        r["campaign_metrics"][0]["cost"], r["campaign_metrics"][1]["cost"] = 0.1, 0.2
        self.make(records=r)
        self.assertEqual(self.normalize()[0], 0)
        m = {x["campaign_id"]: x for x in self.table("campaign_metrics")}
        self.assertEqual(m["111"]["cost"], "0.3")

    def test_real_skill173_export_is_imported(self):
        root = self.tmp / "t173"
        root.mkdir()
        raw, m = T173.preflight(root, T173.it_files())
        self.assertEqual(T173.apply(root, raw, T173.confirm(m, T173.RESOLVE_IT))[0], 0)
        a = T173.ANSWERS
        code, err = quiet(M.plan, self.work, a["customer_id"], a["date_range_start"], a["date_range_end"],
                          a["snapshot_date"], 0, ["account"])
        self.assertEqual(code, 0, err)
        c = json.loads((self.work / "plan.json").read_text())["calls"][0]
        recs = [{"account_id": a["customer_id"], "account_name": "Demo", "account_currency_code": "EUR",
                 "account_time_zone": a["time_zone"], "auto_tagging_enabled": True}]
        (self.work / c["file"]).write_text(json.dumps({"schema": M.RAW_SCHEMA, "pull_id": c["pull_id"],
                                                       "arguments": c["arguments"], "records": recs}))
        code, err = self.normalize(search_terms_from=root / "export")
        self.assertEqual(code, 0, err)
        got = self.table("search_terms")
        with open(root / "export" / "search_terms.csv", newline="") as f:
            self.assertEqual(len(got), len(list(csv.DictReader(f))))
        man = {r["filename"]: r for r in self.table("table_manifest")}
        self.assertIn("skill-173", man["search_terms.csv"]["notes"])

    def test_import_drops_rows_with_phone_or_email_in_any_text_column_without_printing(self):
        self.make()
        src = self.export173()
        leaked = ("chiama 02 1234 5678", "3331234567", "info@example.com", "call 06 9876 5432")
        (src / "search_terms.csv").write_text(
            "search_term,matched_keyword,campaign_id,ad_group_id,impressions,clicks,cost,conversions\n"
            "chiama 02 1234 5678,kw,111,333,5,1,1,0\n3331234567,kw,111,333,5,1,1,0\n"
            "info@example.com,kw,111,333,5,1,1,0\nshoes,call 06 9876 5432,111,333,5,1,1,0\n"
            "iphone 15 pro 256gb,kw,111,333,12345678,1,1,0\n")
        code, err = self.normalize(search_terms_from=src)
        self.assertEqual(code, 0, err)
        got = self.table("search_terms")
        self.assertEqual([r["search_term"] for r in got], ["iphone 15 pro 256gb"], "whole rows dropped, no blanks")
        self.assertEqual(got[0]["impressions"], "12345678", "plain-number metric cells are not treated as phones")
        self.assertTrue(all(t not in err for t in leaked))
        man = {r["filename"]: r for r in self.table("table_manifest")}
        self.assertEqual((man["search_terms.csv"]["row_count"], man["search_terms.csv"]["completeness"][:7]),
                         ("1", "partial"))

    def test_search_terms_import_refuses_other_account_currency_window_or_origin(self):
        cases = {"currency": dict(currency="SEK"), "window": dict(start="2026-08-01"),
                 "customer": dict(customer="999-999-9999"), "basis": dict(basis="conversion_date"),
                 "origin": dict(note="hand made")}
        for i, (label, kw) in enumerate(cases.items()):
            with self.subTest(label):
                self.work, self.out = self.tmp / f"w{i}", self.tmp / f"e{i}"
                self.make()
                code, err = self.normalize(search_terms_from=self.export173(name=f"s{i}", **kw))
                self.assertEqual(code, 2, label)
                self.assertFalse(self.out.exists())

    def test_refusals_write_nothing(self):
        def drift(c, b):
            if c["pull"] == "ads":
                b["arguments"] = {**b["arguments"], "date_from": "2026-08-01"}
            return b

        def drop_field(c, b):
            if c["pull"] == "campaigns":
                for x in b["records"]:
                    x.pop("period")
            return b

        def cut(c, b):
            return json.dumps(b)[:-40] if c["pull"] == "keyword_metrics" else b

        def foreign(c, b):
            if c["pull"] == "ad_groups":
                b["records"][0]["account_id"] = "999-999-9999"
            return b

        def frac_impr(c, b):
            if c["pull"] == "ad_metrics":
                b["records"][0]["impressions"] = 1.5
            return b

        def enum(c, b):
            if c["pull"] == "keywords":
                b["records"][0]["keyword_status"] = "Enabled"
            return b

        def plain_list(c, b):
            if c["pull"] == "ads":
                b["records"][0]["ad_group_ad_ad_responsive_search_ad_headlines"] = "Red shoes, Free delivery"
            return b

        def two_accounts(c, b):
            if c["pull"] == "account":
                b["records"].append({**b["records"][0], "account_currency_code": "SEK"})
            return b

        def missing(c, b):
            return None if c["pull"] == "conversion_actions" else b

        for i, t in enumerate((drift, drop_field, cut, foreign, frac_impr, enum, plain_list, two_accounts, missing)):
            with self.subTest(t.__name__):
                self.work, self.out = self.tmp / f"w{i}", self.tmp / f"e{i}"
                self.make(tamper=t)
                code, err = self.normalize()
                self.assertEqual(code, 2, t.__name__)
                self.assertFalse(self.out.exists())
                self.assertTrue(err.strip())

    def test_explicit_skip_allows_a_missing_pull(self):
        self.make(tamper=lambda c, b: None if c["pull"] == "conversion_actions" else b)
        self.assertEqual(self.normalize(skip=("conversion_actions",))[0], 0)
        self.assertFalse((self.out / "conversion_actions.csv").exists())

    def test_bad_lag_is_refused(self):
        self.make()
        self.assertEqual(self.normalize(lag="about a week")[0], 2)


class Run174(Base):
    def _run(self, export: Path, fn=None) -> dict:
        out = self.tmp / "run"
        quiet(fn or M.main, ["run", "--export", str(export), "--out", str(out)])
        return json.loads((out / "result.json").read_text())

    def test_orphan_metric_keys_are_warnings_and_clean_joins_are_not(self):
        self.make()
        self.assertEqual(self.normalize()[0], 0)
        res = self._run(self.out)
        self.assertEqual([f for f in res["findings"] if f["severity"] != "Info"], [])
        with open(self.out / "keyword_metrics.csv", "a", newline="") as f:
            csv.writer(f, lineterminator="\n").writerow(["999", "111", "333", "1", "0", "0", "0", "0", "", ACC])
        res = self._run(self.out)
        keys = [(f["check"], f["severity"]) for f in res["findings"]]
        self.assertIn(("join_keyword_metrics", "Warning"), keys)
        self.assertNotIn("Critical", {f["severity"] for f in res["findings"]})

    def test_missing_tables_are_coverage_not_findings(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        res = self._run(empty)
        self.assertEqual(res["findings"], [])

    def test_real_recipe_reads_the_export_and_treats_withheld_as_censored(self):
        r = base_records()
        r["campaign_metrics"][1]["search_budget_lost_impression_share"] = 0.9001
        self.make(records=r)
        self.assertEqual(self.normalize()[0], 0)
        out = self.tmp / "r121"
        quiet(M.cli.main, M121.SKILL, M121.VERSION, M121.run, getattr(M121, "verify", None),
              ["run", "--export", str(self.out), "--out", str(out)])
        res = json.loads((out / "result.json").read_text())
        self.assertEqual(res["errors"], [])
        text = json.dumps(res)
        self.assertIn("111", text)
        self.assertNotIn("0.9001", text, "censored values must never surface as numbers")


if __name__ == "__main__":
    unittest.main()
