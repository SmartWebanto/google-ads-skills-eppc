"""test_check.py — skill-089 boundaries: inventory absence proofs, diagnostics, resolved selection vs intent.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-089-pmax-asset-group-structure/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | Critical ref must be one of the item's evidence_refs
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "check.py"
sys.path.insert(0, str(HERE.parents[1] / "_resources" / "runtime"))
_spec = importlib.util.spec_from_file_location("check089", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,currency_code,date_range_start,date_range_end,snapshot_date,conversion_lag_days\n"
           "A,EUR,2026-08-01,2026-08-30,2026-09-06,2\n")
CAMPAIGNS = "id,name,status,channel_type\nP1,PMax A,ENABLED,PERFORMANCE_MAX\nP2,PMax B,ENABLED,PERFORMANCE_MAX\n"
GROUPS = ("campaign_id,asset_group_id,name,status,primary_status,platform_diagnostic,ad_strength,final_urls,theme\n"
          "P1,G1,Acme,ENABLED,ELIGIBLE,,GOOD,https://x.it/acme,acme tools\n"
          "P1,G2,Drills,ENABLED,NOT_ELIGIBLE,policy,POOR,https://x.it/drills,drills\n"
          "P1,G3,Old,PAUSED,NOT_ELIGIBLE,,POOR,https://x.it/old,old\n")
ASSOC = ("campaign_id,asset_group_id,asset_id,field_type,association_status,asset_type,text_or_media_reference,"
         "approval_status,performance_label\nP1,G1,a1,HEADLINE,ENABLED,TEXT,Acme tools,APPROVED,GOOD\n")
PRODUCTS = ("merchant_id,offer_id,target_country,brand\n"
            "m1,p1,IT,acme\nm1,p2,IT,acme\nm1,p3,IT,bosch\nm1,p4,IT,acme\n")
RH = "campaign_id,asset_group_id,node_id,parent_node_id,node_type,inclusion,dimension,level,value,other_case\n"
TREES = RH + ("P1,G1,r,,subdivision,,,,,false\nP1,G1,a,r,unit,included,brand,,acme,false\n"
              "P1,G1,o,r,unit,excluded,brand,,,true\n"
              "P1,G2,r,,subdivision,,,,,false\nP1,G2,a,r,unit,included,item_id,,p3,false\n"
              "P1,G2,o,r,unit,excluded,item_id,,,true\n")
IH = "campaign_id,asset_group_id,intended_product_keys,permitted_overlap,business_critical_inventory,theme,owner\n"
MANIFEST = ("filename,completeness,truncation\ncustom/pmax_groups.csv,complete,none\n"
            "custom/pmax_group_assets.csv,complete,none\nexternal/merchant_products.csv,complete,none\n")


class Base(unittest.TestCase):
    def make(self, files: dict):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        exp = root / "export"
        files = {"account.csv": ACCOUNT, "campaigns.csv": CAMPAIGNS, "table_manifest.csv": MANIFEST, **files}
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

    def sel_files(self, intent):
        return {"custom/pmax_groups.csv": GROUPS, "external/merchant_products.csv": PRODUCTS,
                "custom/pmax_listing_rules.csv": TREES, "external/pmax_group_intent.csv": IH + intent}


class Inventory(Base):
    def test_zero_groups_and_zero_associations_need_complete_manifests(self):
        body = self.make({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_assets.csv": ASSOC})
        p2 = next(o for o in body["observations"] if o["data"].get("campaign_id") == "P2")
        self.assertIs(p2["data"]["zero_groups"], True)
        p1 = next(o for o in body["observations"] if o["data"].get("campaign_id") == "P1" and "groups" in o["data"])
        self.assertEqual(p1["data"]["zero_association_groups"], ["G2", "G3"])
        body = self.make({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_assets.csv": ASSOC,
                          "table_manifest.csv": "filename,completeness\n"})
        p2 = next(o for o in body["observations"] if o["data"].get("campaign_id") == "P2")
        self.assertIsInstance(p2["data"]["zero_groups"], str)
        self.assertEqual(self.cov(body, "group_inventory")["status"], "partial")

    def test_no_pmax_is_not_applicable(self):
        body = self.make({"campaigns.csv": "id,name,status,channel_type\nS1,S,ENABLED,SEARCH\n",
                          "custom/pmax_groups.csv": GROUPS})
        self.assertTrue(all(c["status"] == "not_applicable" for c in body["coverage"]))


class Diagnostics(Base):
    def test_enabled_blocked_group_is_reviewed_paused_is_not(self):
        body = self.make({"custom/pmax_groups.csv": GROUPS})
        r = self.reviews(body, "group_serving_diagnostic")
        self.assertEqual([x["entity"]["asset_group_id"] for x in r], ["G2"])
        self.assertEqual([f["severity"] for f in self.found(body, "group_serving_diagnostic")], ["Info"])


class Selection(Base):
    def test_intended_offer_not_selected_is_warning_with_critical_review(self):
        body = self.make(self.sel_files("P1,G1,p1;p2;p3,true,p3,acme,o\n"))
        f = self.found(body, "intended_products_not_selected")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual(f[0]["evidence"]["uncovered_offers"], ["p3"])
        self.assertEqual(len(self.reviews(body, "intended_products_not_selected")), 1)
        extra = self.reviews(body, "unintended_products_selected")
        self.assertEqual(extra[0]["evidence"]["selected_not_intended"], ["p4"])

    def test_fully_covered_intent_is_clean(self):
        body = self.make(self.sel_files("P1,G1,p1;p2;p4,true,p1,acme,o\n"))
        self.assertEqual(self.found(body, "intended_products_not_selected"), [])
        self.assertEqual(self.reviews(body, "unintended_products_selected"), [])

    def test_unresolved_branch_is_partial_not_warning(self):
        tree = RH + ("P1,G1,r,,subdivision,,,,,false\nP1,G1,a,r,unit,included,google_product_category,1,5,false\n"
                     "P1,G1,o,r,unit,excluded,google_product_category,1,,true\n")
        files = self.sel_files("P1,G1,p1;p2,true,,acme,o\n")
        files["custom/pmax_listing_rules.csv"] = tree
        body = self.make(files)
        self.assertEqual(self.found(body, "intended_products_not_selected"), [])
        self.assertEqual(self.cov(body, "selection_vs_intent")["status"], "partial")

    def test_forbidden_overlap_is_warning_permitted_is_observation(self):
        tree = TREES.replace("P1,G2,a,r,unit,included,item_id,,p3", "P1,G2,a,r,unit,included,item_id,,p1")
        files = self.sel_files("P1,G1,p1;p2;p4,false,,acme,o\nP1,G2,p1,true,,drills,o\n")
        files["custom/pmax_listing_rules.csv"] = tree
        body = self.make(files)
        self.assertEqual(len(self.found(body, "overlap_contradicts_intent")), 1)
        files["external/pmax_group_intent.csv"] = IH + "P1,G1,p1;p2;p4,true,,acme,o\nP1,G2,p1,true,,drills,o\n"
        body = self.make(files)
        self.assertEqual(self.found(body, "overlap_contradicts_intent"), [])
        self.assertTrue(any(o["data"].get("intersection") == 1 for o in body["observations"]))

    def test_missing_listing_tree_skips_selection(self):
        files = self.sel_files("P1,G1,p1,true,,acme,o\n")
        del files["custom/pmax_listing_rules.csv"]
        body = self.make(files)
        self.assertEqual(self.cov(body, "selection_vs_intent")["status"], "skipped")


class Finalize(Base):
    def test_structural_proposal_must_protect_critical_inventory(self):
        self.make(self.sel_files("P1,G1,p1;p2;p3,true,p3,acme,o\n"))
        out = self.root / "out"
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(out)]
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        body = json.loads((out / "result.json").read_text())
        rid = self.reviews(body, "intended_products_not_selected")[0]["id"]
        dec = self.root / "d.json"

        def fin(outcome, proposal):
            dec.write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "r", "proposal": proposal}]))
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)])

        self.assertEqual(fin("material_block", {}), 4)
        for ref in ("crm-audit", "external/pmax_group_intent.csv P1/G2"):  # unknown, another group
            self.assertEqual(fin("material_block", {"evidence_ref": ref}), 4, ref)
        self.assertEqual(fin("material_block", {"evidence_ref": "external/pmax_group_intent.csv P1/G1"}), 0)
        base = {"old_intended_keys": ["p1"], "new_intended_keys": ["p1", "p3"]}
        self.assertEqual(fin("confirmed_not_material", {**base, "protected_inventory": ["p1"]}), 4)
        self.assertEqual(fin("confirmed_not_material", {**base, "new_intended_keys": ["zz"], "protected_inventory": ["p3"]}), 4)
        self.assertEqual(fin("confirmed_not_material", {**base, "protected_inventory": ["p3"]}), 0)

    def test_serving_critical_ref_must_be_reviewed_group_window(self):
        daily = "campaign_id,asset_group_id,date,goal_set_id,cost\nP1,G2,2026-08-10,g,40\nP1,G1,2026-08-10,g,10\n"
        self.make({"custom/pmax_groups.csv": GROUPS, "custom/pmax_group_daily.csv": daily,
                   "external/pmax_group_intent.csv": IH + "P1,G2,p3,true,p3,drills,o\n"})
        out = self.root / "out"
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        item = self.reviews(json.loads((out / "result.json").read_text()), "group_serving_diagnostic")[0]
        self.assertIn("custom/pmax_group_daily.csv P1/G2 2026-08-01..2026-08-30", item["evidence"]["evidence_refs"])
        dec = self.root / "d.json"
        cases = (("custom/pmax_groups.csv P1/G1", 4), ("custom/pmax_group_daily.csv P1/G2 2026-06-01..2026-06-30", 4),
                 ("external/pmax_group_intent.csv P1/G2", 0), ("custom/pmax_group_daily.csv P1/G2 2026-08-01..2026-08-30", 0))
        for ref, want in cases:
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_intended_blocked", "rationale": "r",
                                        "proposal": {"evidence_ref": ref}}]))
            with contextlib.redirect_stdout(io.StringIO()):
                got = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)])
            self.assertEqual(got, want, ref)


if __name__ == "__main__":
    unittest.main()
