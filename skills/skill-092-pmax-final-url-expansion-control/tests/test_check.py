"""test_check.py — skill-092 boundaries: expansion status, URL origin, destination review, exclusions, zero-conv gate.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-092-pmax-final-url-expansion-control/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | tests for this session's check changes
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "check.py"
sys.path.insert(0, str(HERE.parents[1] / "_resources" / "runtime"))
_spec = importlib.util.spec_from_file_location("check092", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,currency_code,date_range_start,date_range_end,snapshot_date,conversion_lag_days\n"
           "A,EUR,2026-08-01,2026-08-30,{snap},2\n")
CAMPAIGNS = "id,name,status,channel_type,goal_ids\nP1,PMax,ENABLED,PERFORMANCE_MAX,purchase\n"
CONV = "id,name,category,status,last_conversion_date\npurchase,Purchase,PURCHASE,ENABLED,2026-08-29\n"
GROUPS = "campaign_id,asset_group_id,status,final_urls\nP1,G1,ENABLED,https://Shop.it/Tools/?utm_source=x\n"
SETTINGS_H = "campaign_id,final_url_expansion_status,page_feed_ids,source_reference,observed_at\n"
RULES_H = "campaign_id,rule_or_feed_entry_id,rule_type,operator,url_or_pattern,active_status\n"
LP_H = "campaign_id,date,reported_url,provenance,impressions,clicks,cost,conversions,goal_set_id\n"
REVIEW_H = ("campaign_id,canonical_url,tested_at,resolved_url,page_purpose,approved_objectives,permitted_destination,"
            "provenance_evidence,review_owner\n")


class Base(unittest.TestCase):
    def make(self, files: dict, snap="2026-09-06", conv=CONV):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        exp = root / "export"
        files = {"account.csv": ACCOUNT.format(snap=snap), "campaigns.csv": CAMPAIGNS,
                 "conversion_actions.csv": conv, **files}
        for k, v in files.items():
            (exp / k).parent.mkdir(parents=True, exist_ok=True)
            (exp / k).write_text(v)
        prof = root / "profile.json"
        prof.write_text("{}")
        self.root, self.exp, self.prof = root, exp, prof
        return cli.run_once(M.SKILL, M.VERSION, M.run, exp, prof).finish()

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def reviews(body, key):
        return [r for r in body["ai_review"] if r["condition_key"] == key]


class Normalize(unittest.TestCase):
    def test_tracking_params_dropped_content_params_kept(self):
        self.assertEqual(M.normalize_url("HTTPS://Shop.IT:443/Tools/?utm_source=a&gclid=b&lang=it#x"),
                         "https://shop.it/Tools?lang=it")
        self.assertNotEqual(M.normalize_url("https://shop.it/p?id=1"), M.normalize_url("https://shop.it/p?id=2"))


class Settings(Base):
    def test_enabled_with_declared_empty_rules_is_info(self):
        body = self.make({"external/pmax_url_settings.csv": SETTINGS_H + "P1,enabled,,ui,2026-09-06\n",
                          "external/pmax_url_rules.csv": RULES_H + "P1,d1,no_rules,,,\n"})
        self.assertEqual([f["severity"] for f in self.found(body, "expansion_enabled_without_exclusions")], ["Info"])

    def test_undeclared_rule_inventory_is_partial(self):
        body = self.make({"external/pmax_url_settings.csv": SETTINGS_H + "P1,enabled,,ui,2026-09-06\n"})
        self.assertEqual(self.found(body, "expansion_enabled_without_exclusions"), [])
        self.assertEqual(self.cov(body, "expansion_settings")["status"], "partial")

    def test_missing_settings_row_is_unknown_not_disabled(self):
        body = self.make({"external/pmax_url_settings.csv": SETTINGS_H + "OTHER,disabled,,ui,2026-09-06\n"})
        obs = next(o for o in body["observations"] if o["data"].get("campaign_id") == "P1")
        self.assertEqual(obs["data"]["expansion_status"], "unknown")


class Origin(Base):
    def test_configured_url_matches_after_normalization_unknown_is_info(self):
        lp = LP_H + ("P1,2026-08-10,https://shop.it/Tools?utm_medium=y,reported,100,10,5,1,purchase\n"
                     "P1,2026-08-10,https://shop.it/about,unknown,100,10,5,0,purchase\n")
        body = self.make({"custom/pmax_groups.csv": GROUPS, "custom/pmax_landing_pages.csv": lp})
        f = self.found(body, "unknown_url_origin")
        self.assertEqual([u["url"] for u in f[0]["evidence"]["urls"]], ["https://shop.it/about"])


class Destinations(Base):
    def test_not_permitted_served_url_is_warning_with_critical_review(self):
        lp = LP_H + "P1,2026-08-10,https://shop.it/old-offer,unknown,100,10,5,0,purchase\n"
        rev = REVIEW_H + "P1,https://shop.it/old-offer,2026-09-01,,expired promo,purchase,false,none,client\n"
        body = self.make({"custom/pmax_landing_pages.csv": lp, "external/pmax_destination_review.csv": rev})
        self.assertEqual([f["severity"] for f in self.found(body, "destination_offer_mismatch")], ["Warning"])
        r = self.reviews(body, "destination_offer_mismatch")
        self.assertIn("Critical", {o["severity"] for o in r[0]["outcomes"].values()})

    def test_permitted_editorial_page_is_not_flagged_and_unreviewed_is_partial(self):
        lp = LP_H + ("P1,2026-08-10,https://shop.it/blog/guide,unknown,100,10,5,0,purchase\n"
                     "P1,2026-08-10,https://shop.it/x,unknown,100,10,5,0,purchase\n")
        rev = REVIEW_H + "P1,https://shop.it/blog/guide,2026-09-01,,guide,consideration,true,none,client\n"
        body = self.make({"custom/pmax_landing_pages.csv": lp, "external/pmax_destination_review.csv": rev})
        self.assertEqual(body["findings"], [])
        self.assertEqual(self.cov(body, "destination_fit")["status"], "partial")


class Exclusions(Base):
    def test_rule_colliding_with_final_url_is_reviewed(self):
        rules = RULES_H + "P1,r1,url_exclusion,contains,/tools,active\nP1,r2,url_exclusion,contains,/careers,active\n"
        body = self.make({"custom/pmax_groups.csv": GROUPS, "external/pmax_url_rules.csv": rules})
        self.assertEqual([r["entity"]["rule_id"] for r in self.reviews(body, "exclusion_collides_valid_destination")], ["r1"])

    def test_unknown_operator_is_partial(self):
        rules = RULES_H + "P1,r1,url_exclusion,regex,.*,active\n"
        body = self.make({"custom/pmax_groups.csv": GROUPS, "external/pmax_url_rules.csv": rules})
        self.assertEqual(self.cov(body, "exclusion_rules")["status"], "partial")


ZERO = LP_H + ("P1,2026-08-10,https://shop.it/careers,unknown,900,80,60,0,purchase\n"
               "P1,2026-08-10,https://shop.it/tools,unknown,900,80,60,3,purchase\n"
               "P1,2026-08-11,https://shop.it/faq,unknown,900,80,20,0,purchase\n")


class ZeroConversion(Base):
    def test_mature_tracked_above_floor_is_reviewed_below_floor_is_not(self):
        body = self.make({"custom/pmax_landing_pages.csv": ZERO})
        r = self.reviews(body, "mature_zero_conversion_destination")
        self.assertEqual([x["entity"]["url"] for x in r], ["https://shop.it/careers"])
        self.assertIn("Warning", {o["severity"] for o in r[0]["outcomes"].values()})
        self.assertEqual({f["severity"] for f in self.found(body, "mature_zero_conversion_destination")}, {"Info"})

    def test_immature_window_disables_zero_conversion_path(self):
        body = self.make({"custom/pmax_landing_pages.csv": ZERO}, snap="2026-08-31")
        self.assertEqual(self.reviews(body, "mature_zero_conversion_destination"), [])
        self.assertEqual(self.cov(body, "destination_performance")["status"], "partial")

    def test_unverified_tracking_disables_zero_conversion_path(self):
        conv = "id,name,category,status,last_conversion_date\npurchase,Purchase,PURCHASE,ENABLED,2026-07-01\n"
        body = self.make({"custom/pmax_landing_pages.csv": ZERO}, conv=conv)
        self.assertEqual(self.reviews(body, "mature_zero_conversion_destination"), [])


class Finalize(Base):
    def test_exclusion_proposal_must_not_block_valid_destinations(self):
        self.make({"custom/pmax_landing_pages.csv": ZERO, "custom/pmax_groups.csv": GROUPS})
        out = self.root / "out"
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(out)]
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        body = json.loads((out / "result.json").read_text())
        rid = self.reviews(body, "mature_zero_conversion_destination")[0]["id"]
        dec = self.root / "d.json"

        def fin(pattern, op="contains"):
            dec.write_text(json.dumps([{"id": rid, "outcome": "irrelevant_or_mismatch", "rationale": "jobs page",
                                        "proposal": {"exclusion": {"operator": op, "url_or_pattern": pattern}}}]))
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)])

        self.assertEqual(fin("shop.it/"), 4)
        self.assertEqual(fin("/faq"), 4)
        self.assertEqual(fin("/careers"), 0)

    def test_critical_evidence_ref_must_resolve_to_reviewed_url_review(self):
        lp = LP_H + ("P1,2026-08-10,https://shop.it/old-offer,unknown,100,10,5,0,purchase\n"
                     "P1,2026-08-10,https://shop.it/other,unknown,100,10,5,0,purchase\n")
        rev = ("campaign_id,canonical_url,tested_at,resolved_url,page_purpose,approved_objectives,"
               "permitted_destination,provenance_evidence,source_reference,review_owner\n"
               "P1,https://shop.it/old-offer,2026-09-01,,expired promo,purchase,false,none,REV-1,client\n"
               "P1,https://shop.it/other,2026-09-01,,banned,purchase,false,none,REV-2,client\n"
               "P1,https://shop.it/old-offer,2026-07-01,,old promo,purchase,false,none,REV-OLD,client\n")
        self.make({"custom/pmax_landing_pages.csv": lp, "external/pmax_destination_review.csv": rev})
        out = self.root / "out"
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(out)]
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        body = json.loads((out / "result.json").read_text())
        rid = next(r["id"] for r in self.reviews(body, "destination_offer_mismatch")
                   if r["entity"]["url"] == "https://shop.it/old-offer")
        dec = self.root / "d.json"

        def fin(ref):
            dec.write_text(json.dumps([{"id": rid, "outcome": "prohibited_material", "rationale": "unsafe",
                                        "proposal": {"evidence_ref": ref}}]))
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)])

        self.assertEqual(fin("MADE-UP"), 4)
        self.assertEqual(fin("none"), 4)
        self.assertEqual(fin("REV-2"), 4)
        self.assertEqual(fin("REV-OLD"), 4)
        self.assertEqual(fin("REV-1"), 0)


if __name__ == "__main__":
    unittest.main()
