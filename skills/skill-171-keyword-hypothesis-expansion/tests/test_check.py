"""test_check.py — Decision-boundary tests for skill-171 keyword hypothesis evidence and verification.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-171-keyword-hypothesis-expansion/tests -t skills/skill-171-keyword-hypothesis-expansion
rules:   Synthetic temp exports only; no network. Tests pin verification boundaries (duplicate scope, negative
blocks, brand policy, excluded terms, evidence citation) and missing-evidence coverage, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes5 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("skill171_check", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402  (path inserted by the check module bootstrap)
from adsrun.context import Context  # noqa: E402

ACCOUNT = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,"
           "rates_format,money_unit,conversion_date_basis,conversion_lag_days\n"
           "1,A,EUR,Europe/Rome,2026-08-01,2026-08-30,{snap},fraction,currency,interaction_date,2\n")
BASE = {
    "campaigns.csv": "id,name,status,channel_type\n1,Generic,ENABLED,SEARCH\n2,Brand,ENABLED,SEARCH\n3,Shop,ENABLED,SHOPPING\n",
    "ad_groups.csv": "id,campaign_id,name,status\n11,1,Drills,ENABLED\n12,1,Hammers,ENABLED\n21,2,Brand,ENABLED\n",
    "keywords.csv": ("id,campaign_id,ad_group_id,text,match_type,status,final_url\n"
                     "101,1,11,cordless drill,PHRASE,ENABLED,https://x.example/drills/\n"
                     "102,1,12,claw hammer,BROAD,ENABLED,https://x.example/hammers\n"
                     "201,2,21,acme,EXACT,ENABLED,https://x.example/\n"),
    "negative_keywords.csv": "text,match_type,level,campaign_id,ad_group_id\ncheap,PHRASE,campaign,1,\n",
    "shared_negative_lists.csv": "list_id,name,member_count,keywords,campaigns_applied\nL1,U,1,jobs (PHRASE),1\n",
    "search_terms.csv": ("search_term,campaign_id,ad_group_id,clicks,conversions\n"
                         "cordless drill 18v,1,11,50,5\nclaw hammer steel,1,12,20,0\nacme shop,2,21,30,3\n"),
    "keyword_metrics.csv": "keyword_id,campaign_id,ad_group_id,conversions\n101,1,11,7\n102,1,12,0\n",
}
PROFILE = ("brand_terms: [acme]\ncompetitor_terms: [rivalco]\nexcluded_intent_terms: [repair manual]\n"
           "product_service_taxonomy: [cordless drills, claw hammer]\n"
           "campaign_objectives:\n  1: {brand_policy: nonbrand_only, goal_ids: [g1]}\n"
           "  2: {brand_policy: brand_only, goal_ids: [g1]}\n")


def _manifest(files) -> str:
    lines = ["filename,completeness,truncation"]
    lines += [f"{n},complete,none" for n in sorted(files) if n != "table_manifest.csv"]
    return "\n".join(lines) + "\n"


class Base(unittest.TestCase):
    def build(self, drop=(), extra=None, profile=PROFILE, snap="2026-09-05", manifest=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        files = {k: v for k, v in BASE.items() if k not in drop}
        files.update(extra or {})
        files["account.csv"] = ACCOUNT.format(snap=snap)
        if manifest:
            files["table_manifest.csv"] = _manifest(files)
        for name, text in files.items():
            p = root / "export" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (root / "profile.yaml").write_text(profile)
        self.root = root
        return root

    def run_ctx(self):
        ctx = Context(M.SKILL, M.VERSION, self.root / "export", self.root / "profile.yaml")
        M.run(ctx)
        return ctx

    @staticmethod
    def cov(ctx):
        return {c.id: c.coverage() for c in ctx.result.checks}

    @staticmethod
    def item(ctx, key, entity):
        return next(x for x in ctx.result.reviews if x.condition_key == key and x.entity == entity)

    def problems(self, ctx, candidates, campaign="1"):
        item = self.item(ctx, "keyword_hypotheses", {"campaign_id": campaign})
        return M.verify(ctx, item, {"outcome": "hypotheses_proposed", "proposal": {"candidates": candidates}})


def cand(text, match="PHRASE", gid="11", source="taxonomy", ref="cordless drills", **kw):
    return {"text": text, "match_type": match, "ad_group_id": gid, "source": source, "evidence_ref": ref, **kw}


class Verification(Base):
    def setUp(self):
        self.build()
        self.ctx = self.run_ctx()

    def test_valid_candidate_accepted(self):
        self.assertEqual(self.problems(self.ctx, [cand("brushless cordless drill kit")]), [])

    def test_duplicate_needs_same_text_match_and_ad_group(self):
        self.assertTrue(self.problems(self.ctx, [cand("Cordless  Drill", "PHRASE", "11")]))
        self.assertEqual(self.problems(self.ctx, [cand("cordless drill", "EXACT", "11")]), [])
        self.assertEqual(self.problems(self.ctx, [cand("cordless drill", "PHRASE", "12")]), [])
        self.assertTrue(self.problems(self.ctx, [cand("drill bits"), cand("drill bits")]))

    def test_effective_negatives_block_candidates(self):
        self.assertTrue(self.problems(self.ctx, [cand("cheap cordless drill")]))   # campaign negative
        self.assertTrue(self.problems(self.ctx, [cand("drill jobs")]))            # shared list member
        self.assertEqual(self.problems(self.ctx, [cand("cheapest cordless drill")]), [])  # no close variants

    def test_brand_and_competitor_policy(self):
        self.assertTrue(self.problems(self.ctx, [cand("acme cordless drill")]))           # nonbrand_only
        self.assertTrue(self.problems(self.ctx, [cand("rivalco cordless drill")]))        # competitor
        brand = {"gid": "21", "source": "seed_query", "ref": "acme shop"}
        self.assertEqual(self.problems(self.ctx, [cand("acme drills online", **brand)], "2"), [])
        self.assertTrue(self.problems(self.ctx, [cand("drills online", **brand)], "2"))   # brand_only

    def test_excluded_terms_reported_queries_and_citations(self):
        self.assertTrue(self.problems(self.ctx, [cand("cordless drill repair manual")]))
        self.assertTrue(self.problems(self.ctx, [cand("cordless drill 18v", "EXACT")]))   # skill-013 owns it
        self.assertTrue(self.problems(self.ctx, [cand("garden hose", ref="garden supplies")]))
        self.assertEqual(self.problems(self.ctx, [cand("cordless drill case", source="seed_keyword",
                                                       ref="cordless drill")]), [])
        self.assertTrue(self.problems(self.ctx, [cand("cordless drill case", source="seed_keyword",
                                                      ref="claw hammer")]))                # zero-conversion keyword
        self.assertTrue(self.problems(self.ctx, [cand("cordless drill case", gid="21")]))  # other campaign's group
        self.assertTrue(self.problems(self.ctx, [cand("cordless drill case", expected_clicks=40)]))
        self.assertTrue(self.problems(self.ctx, [cand("[cordless drill case]")]))


class Coverage(Base):
    def test_unknown_brand_policy_is_partial_not_reviewed(self):
        self.build(profile=PROFILE.replace("{brand_policy: nonbrand_only, goal_ids: [g1]}", "{goal_ids: [g1]}"))
        ctx = self.run_ctx()
        cov = self.cov(ctx)
        self.assertEqual(cov["campaign_scope"]["status"], "partial")
        self.assertIn("profile.campaign_objectives[1].brand_policy", cov["campaign_scope"]["missing"])
        ids = {x.entity.get("campaign_id") for x in ctx.result.reviews if x.condition_key == "keyword_hypotheses"}
        self.assertEqual(ids, {"2"})

    def test_brand_only_without_brand_terms_is_partial(self):
        self.build(profile=PROFILE.replace("brand_terms: [acme]\n", ""))
        ctx = self.run_ctx()
        self.assertIn("profile.brand_terms", self.cov(ctx)["campaign_scope"]["missing"])
        self.assertFalse([x for x in ctx.result.reviews if x.condition_key == "keyword_hypotheses"])

    def test_missing_negatives_skip_hypothesis_review(self):
        self.build(drop=("negative_keywords.csv",))
        ctx = self.run_ctx()
        cov = self.cov(ctx)["hypothesis_review"]
        self.assertEqual(cov["status"], "skipped")
        self.assertIn("negative_keywords (file)", cov["missing"])
        self.assertFalse([x for x in ctx.result.reviews if x.condition_key == "keyword_hypotheses"])

    def test_missing_search_terms_keeps_other_seeds(self):
        self.build(drop=("search_terms.csv",))
        ctx = self.run_ctx()
        self.assertEqual(self.cov(ctx)["query_seeds"]["status"], "skipped")
        self.assertEqual(self.problems(ctx, [cand("cordless drill case", source="seed_keyword",
                                                  ref="cordless drill")]), [])

    def test_immature_window_marks_seeds_partial(self):
        self.build(snap="2026-08-31")
        ctx = self.run_ctx()
        self.assertEqual(self.cov(ctx)["query_seeds"]["status"], "partial")
        self.assertIs(ctx.mature, False)
        self.assertEqual(self.cov(ctx)["keyword_seeds"]["status"], "partial")

    def test_no_search_campaign_is_not_applicable(self):
        self.build(extra={"campaigns.csv": "id,name,status,channel_type\n3,Shop,ENABLED,SHOPPING\n"})
        ctx = self.run_ctx()
        self.assertEqual(self.cov(ctx)["hypothesis_review"]["status"], "not_applicable")
        self.assertFalse(ctx.result.reviews)


class ThemeCoverage(Base):
    def test_uncovered_theme_reviewed_only_with_complete_inventory(self):
        self.build()
        ctx = self.run_ctx()
        themes = {x.entity["theme"] for x in ctx.result.reviews if x.condition_key == "theme_without_keyword_coverage"}
        self.assertEqual(themes, {"cordless drills"})   # 'claw hammer' covered; 'drills' plural not literal
        self.build(manifest=False)
        ctx = self.run_ctx()
        self.assertFalse([x for x in ctx.result.reviews if x.condition_key == "theme_without_keyword_coverage"])
        self.assertEqual(self.cov(ctx)["theme_coverage"]["status"], "partial")

    def test_missing_taxonomy_skips(self):
        self.build(profile=PROFILE.replace("product_service_taxonomy: [cordless drills, claw hammer]\n", ""))
        ctx = self.run_ctx()
        cov = self.cov(ctx)["theme_coverage"]
        self.assertEqual(cov["status"], "skipped")
        self.assertIn("profile.product_service_taxonomy", cov["missing"])


class PageSeeds(Base):
    PAGES = ("url,captured_at,http_status,title,main_content_excerpt,evidence_ref\n"
             "https://x.example/drills,2026-09-01,200,Drills,Brushless drills,P1\n"
             "https://x.example/hammers,2026-09-01,404,,,P2\n"
             "https://x.example/other,2026-09-01,200,Other,Text,P3\n")

    def test_only_linked_http_200_pages_are_citable(self):
        self.build(extra={"external/landing_page_content.csv": self.PAGES})
        ctx = self.run_ctx()
        self.assertEqual(self.problems(ctx, [cand("brushless drill driver", source="page", ref="P1")]), [])
        self.assertTrue(self.problems(ctx, [cand("brushless drill driver", source="page", ref="P2")]))
        self.assertTrue(self.problems(ctx, [cand("brushless drill driver", source="page", ref="P3")]))
        self.assertEqual(self.cov(ctx)["page_seeds"]["status"], "partial")


class Finalize(Base):
    def _cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=list(args))

    def test_finalize_accepts_verified_and_rejects_blocked(self):
        root = self.build()
        out = root / "out"
        common = ["--export", str(root / "export"), "--profile", str(root / "profile.yaml"), "--out", str(out)]
        self.assertEqual(self._cli("run", *common), 0)
        body = json.loads((out / "result.json").read_text())
        rid = next(x["id"] for x in body["ai_review"] if x["entity"] == {"campaign_id": "1"})
        good = [{"id": rid, "outcome": "hypotheses_proposed", "rationale": "taxonomy theme",
                 "proposal": {"candidates": [cand("brushless cordless drill kit")]}}]
        (root / "d.json").write_text(json.dumps(good))
        self.assertEqual(self._cli("finalize", *common, "--decisions", str(root / "d.json")), 0)
        final = json.loads((out / "final.json").read_text())
        hit = [f for f in final["findings"] if f["entity"] == {"campaign_id": "1"}]
        self.assertEqual([(f["severity"], f["origin"]) for f in hit], [("Info", "ai_review")])
        good[0]["proposal"]["candidates"].append(cand("cheap cordless drill"))
        (root / "d.json").write_text(json.dumps(good))
        self.assertEqual(self._cli("finalize", *common, "--decisions", str(root / "d.json")), 4)


if __name__ == "__main__":
    unittest.main()
