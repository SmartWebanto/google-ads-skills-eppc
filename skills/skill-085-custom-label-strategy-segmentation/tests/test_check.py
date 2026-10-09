"""test_check.py — skill-085 boundaries: dictionary conformance, tree resolution, label-driven exclusions.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-085-custom-label-strategy-segmentation/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | tests for this session's check changes
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
_spec = importlib.util.spec_from_file_location("check085", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = ("customer_id,currency_code,date_range_start,date_range_end,snapshot_date,conversion_lag_days\n"
           "A,EUR,2026-08-01,2026-08-30,2026-09-06,2\n")
PH = "merchant_id,offer_id,target_country,destination,custom_label_0,custom_label_1,custom_label_2,custom_label_3,custom_label_4\n"
PRODUCTS = PH + ("m1,p1,IT,shopping,high,,,,\n"
                 "m1,p1,IT,free_listings,high,,,,\n"
                 "m1,p2,IT,shopping,low,,,,\n"
                 "m1,p3,IT,shopping,hgh,,,,\n"
                 "m1,p4,IT,shopping,,,,,\n")
STRATEGY = ("merchant_id,label_slot,allowed_value,meaning,valid_from,valid_to,approved_at,intended_use,offer_id\n"
            "m1,custom_label_0,high,high margin,2026-01-01,,2026-01-01,selection,\n"
            "m1,custom_label_0,low,low margin,2026-01-01,,2026-01-01,selection,\n")
RULES_HDR = "campaign_id,asset_group_id,node_id,parent_node_id,node_type,inclusion,dimension,dimension_level,value,other_case\n"
TREE = RULES_HDR + ("C1,G1,n0,,subdivision,,,,,false\n"
                    "C1,G1,n1,n0,unit,included,custom_label_0,,high,false\n"
                    "C1,G1,n2,n0,unit,included,custom_label_0,,low,false\n"
                    "C1,G1,n3,n0,unit,excluded,custom_label_0,,,true\n")
MANIFEST = ("filename,completeness,truncation\nexternal/merchant_products.csv,complete,none\n"
            "custom/listing_rules.csv,complete,none\nexternal/label_strategy.csv,complete,none\n")


class Base(unittest.TestCase):
    def make(self, files: dict, profile=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        exp = root / "export"
        files = {"account.csv": ACCOUNT, "table_manifest.csv": MANIFEST, **files}
        for k, v in files.items():
            (exp / k).parent.mkdir(parents=True, exist_ok=True)
            (exp / k).write_text(v)
        prof = root / "profile.json"
        prof.write_text(json.dumps({"objectives": ["purchase"], **(profile or {})}))
        self.root, self.exp, self.prof = root, exp, prof
        return cli.run_once(M.SKILL, M.VERSION, M.run, exp, prof).finish()

    @staticmethod
    def cov(body, check):
        return next(c for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def reviews(body, key):
        return [r for r in body["ai_review"] if r["condition_key"] == key]


class Inventory(Base):
    def test_destination_rows_are_deduplicated_and_cardinality_is_descriptive(self):
        rows = PH + "".join(f"m1,p{i},IT,shopping,v{i},,,,\n" for i in range(12))
        body = self.make({"external/merchant_products.csv": rows})
        obs = next(o for o in body["observations"] if o["data"].get("slot") == "custom_label_0"
                   and "catalog_products" in o["data"])
        self.assertEqual(obs["data"]["catalog_products"], 12)
        self.assertTrue(obs["data"]["more_than_ten_values"])
        self.assertEqual(body["findings"], [])

    def test_missing_feed_skips_everything(self):
        body = self.make({})
        self.assertTrue(all(c["status"] == "skipped" for c in body["coverage"] if c["check"] != "shopping_build_plan"))
        self.assertEqual(self.cov(body, "shopping_build_plan")["status"], "not_applicable")  # opt-in not requested


class Dictionary(Base):
    def test_undeclared_value_is_provisional_info_with_review(self):
        body = self.make({"external/merchant_products.csv": PRODUCTS, "external/label_strategy.csv": STRATEGY})
        r = self.reviews(body, "undeclared_label_meaning")
        self.assertEqual(len(r), 1)
        self.assertEqual(set(r[0]["evidence"]["undeclared"]), {"hgh"})
        self.assertEqual({f["severity"] for f in body["findings"]}, {"Info"})

    def test_expired_value_used_in_rule_gets_review(self):
        strat = STRATEGY.replace("m1,custom_label_0,low,low margin,2026-01-01,,", "m1,custom_label_0,low,low margin,2026-01-01,2026-06-30,")
        body = self.make({"external/merchant_products.csv": PRODUCTS, "external/label_strategy.csv": strat,
                          "custom/listing_rules.csv": TREE})
        self.assertEqual(len(self.reviews(body, "expired_label_value")), 1)

    def test_valid_values_produce_no_dictionary_finding(self):
        rows = PH + "m1,p1,IT,shopping,high,,,,\nm1,p2,IT,shopping,low,,,,\n"
        body = self.make({"external/merchant_products.csv": rows, "external/label_strategy.csv": STRATEGY})
        self.assertEqual([f for f in body["findings"] if f["check"] == "dictionary_conformance"], [])

    def test_product_classification_conflict_is_warning_when_slot_has_current_use(self):
        strat = STRATEGY + "m1,custom_label_0,low,low margin,2026-01-01,,2026-01-01,,p1\n"
        body = self.make({"external/merchant_products.csv": PRODUCTS, "external/label_strategy.csv": strat})
        f = [x for x in body["findings"] if x["condition_key"] == "incorrect_label_value"]
        self.assertEqual([x["severity"] for x in f], ["Warning"])

    def test_matching_classification_is_clean(self):
        strat = STRATEGY + "m1,custom_label_0,high,high margin,2026-01-01,,2026-01-01,,p1\n"
        body = self.make({"external/merchant_products.csv": PRODUCTS, "external/label_strategy.csv": strat})
        self.assertEqual([x for x in body["findings"] if x["condition_key"] == "incorrect_label_value"], [])


class Tree(Base):
    def test_typo_product_excluded_by_other_case_is_flagged(self):
        body = self.make({"external/merchant_products.csv": PRODUCTS, "custom/listing_rules.csv": TREE})
        r = self.reviews(body, "label_rule_mismatch")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["evidence"]["values"], {"hgh": 1})
        self.assertIn("Critical", {o["severity"] for o in r[0]["outcomes"].values()})
        obs = next(o for o in body["observations"] if o["data"].get("group_id") == "G1")
        self.assertEqual((obs["data"]["included"], obs["data"]["excluded"]), (2, 2))

    def test_other_case_included_raises_nothing(self):
        tree = TREE.replace("C1,G1,n3,n0,unit,excluded", "C1,G1,n3,n0,unit,included")
        body = self.make({"external/merchant_products.csv": PRODUCTS, "custom/listing_rules.csv": tree})
        self.assertEqual(self.reviews(body, "label_rule_mismatch"), [])

    def test_unsupported_dimension_is_unresolved_not_all_products(self):
        tree = RULES_HDR + ("C1,G1,n0,,subdivision,,,,,false\n"
                            "C1,G1,n1,n0,unit,included,google_product_category,1,123,false\n"
                            "C1,G1,n2,n0,unit,excluded,google_product_category,1,,true\n")
        body = self.make({"external/merchant_products.csv": PRODUCTS, "custom/listing_rules.csv": tree})
        self.assertEqual(self.cov(body, "listing_label_use")["status"], "partial")
        obs = next(o for o in body["observations"] if o["data"].get("group_id") == "G1")
        self.assertEqual((obs["data"]["included"], obs["data"]["unresolved"]), (0, 4))

    def test_node_selecting_absent_value_in_complete_feed_is_reviewed(self):
        tree = TREE.replace(",custom_label_0,,low,false", ",custom_label_0,,lowe,false")
        body = self.make({"external/merchant_products.csv": PRODUCTS, "custom/listing_rules.csv": tree})
        self.assertTrue(any(r["entity"]["node_id"] == "n2" for r in self.reviews(body, "label_rule_mismatch")))

    def test_item_id_subdivision_resolves(self):
        tree = RULES_HDR + ("C1,G1,n0,,subdivision,,,,,false\n"
                            "C1,G1,n1,n0,unit,included,item_id,,p2,false\n"
                            "C1,G1,n2,n0,unit,excluded,item_id,,,true\n")
        body = self.make({"external/merchant_products.csv": PRODUCTS, "custom/listing_rules.csv": tree})
        obs = next(o for o in body["observations"] if o["data"].get("group_id") == "G1")
        self.assertEqual((obs["data"]["included"], obs["data"]["excluded"]), (1, 3))


class Finalize(Base):
    def _finalize(self, rid, outcome, proposal):
        dec = self.root / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "r", "proposal": proposal}]))
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(self.root / "out")]
        return cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize"] + args + ["--decisions", str(dec)])

    def _run(self, files):
        self.make(files)
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(self.root / "out")]
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        return json.loads((self.root / "out" / "result.json").read_text())

    def test_critical_needs_evidence_ref_and_corrections_need_dictionary_values(self):
        body = self._run({"external/merchant_products.csv": PRODUCTS, "custom/listing_rules.csv": TREE,
                          "external/label_strategy.csv": STRATEGY})
        rid = self.reviews(body, "label_rule_mismatch")[0]["id"]
        self.assertEqual(self._finalize(rid, "excludes_material_intended", {}), 4)
        self.assertEqual(self._finalize(rid, "incorrect_label_conflict",
                                        {"corrections": [{"value": "hgh", "intended_value": "hihg"}]}), 4)
        self.assertEqual(self._finalize(rid, "incorrect_label_conflict",
                                        {"corrections": [{"value": "hgh", "intended_value": "high"}]}), 0)

    def test_segmentation_proposal_only_in_empty_slot(self):
        body = self._run({"external/merchant_products.csv": PRODUCTS})
        rid = self.reviews(body, "segmentation_proposal")[0]["id"]
        full = {k: "x" for k in M.PROPOSAL_FIELDS}
        self.assertEqual(self._finalize(rid, "proposal_supported", {**full, "slot": "custom_label_0"}), 4)
        self.assertEqual(self._finalize(rid, "proposal_supported", {**full, "slot": "custom_label_1", "kind": "margin"}), 4)
        self.assertEqual(self._finalize(rid, "proposal_supported", {**full, "slot": "custom_label_1"}), 0)


BP_HDR = "merchant_id,offer_id,target_country,destination,brand,product_type," + ",".join(M.SLOTS) + "\n"
BP_FEED = BP_HDR + ("m1,p1,IT,shopping,Acme,Tools > Drills,sale,,,,\n"
                    "m1,p2,IT,shopping,Acme,Tools > Saws,,,,,\n"
                    "m1,p3,IT,shopping,Bolt,Tools > Drills,sale,,,,\n"
                    "m1,p4,IT,shopping,Bolt,Garden > Hoses,,,,,\n"
                    "m1,p5,DE,shopping,Acme,Tools > Drills,,,,,\n")
BP_CAMPS = "id,channel_type\nS1,SHOPPING\nS2,SHOPPING\nP1,PERFORMANCE_MAX\n"
BP_REQUEST = {"campaigns": {"S1": {"priority": "high"}, "S2": {"priority": "low"}}, "scope": {"target_country": "IT"},
              "routing": [{"when": {"custom_label_0": "sale"}, "priority": "high"}], "remainder_campaign_id": "S2"}
SALE = {"campaign_id": "S1", "ad_group": "Sale", "key": {"custom_label_0": "sale"}}
SAWS = {"campaign_id": "S2", "ad_group": "Acme saws", "key": {"brand": "acme", "product_type_l2": "saws"}}
REST = {"campaign_id": "S2", "ad_group": "Everything else"}


class BuildPlan(Base):
    _finalize = Finalize._finalize

    def _plan(self, request=BP_REQUEST, manifest=MANIFEST + "campaigns.csv,complete,none\n"):
        self.make({"external/merchant_products.csv": BP_FEED, "campaigns.csv": BP_CAMPS, "table_manifest.csv": manifest},
                  profile={"shopping_build_plan_request": request} if request else None)
        args = ["--export", str(self.exp), "--profile", str(self.prof), "--out", str(self.root / "out")]
        self.assertEqual(cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args), 0)
        body = json.loads((self.root / "out" / "result.json").read_text())
        return body, self.reviews(body, "shopping_build_plan")

    def _problems(self, rid, proposal):
        code = self._finalize(rid, "plan_proposed", proposal)
        final = json.loads((self.root / "out" / "final.json").read_text())
        return code, "; ".join(final["review_log"][0]["problems"]), final

    def test_review_only_when_requested_valid_and_feed_complete(self):
        body, items = self._plan(request=None)
        self.assertEqual((self.cov(body, "shopping_build_plan")["status"], items), ("not_applicable", []))
        body, items = self._plan(manifest=MANIFEST.replace("merchant_products.csv,complete", "merchant_products.csv,partial"))
        self.assertEqual((self.cov(body, "shopping_build_plan")["status"], items), ("partial", []))
        body, items = self._plan(request={**BP_REQUEST, "campaigns": ["S1", "P1"]})
        self.assertEqual((self.cov(body, "shopping_build_plan")["status"], items), ("partial", []))
        body, items = self._plan()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["evidence"]["in_scope_offers"], 4)  # DE offer p5 is out of scope

    def test_valid_plan_accepted_as_info_proposal(self):
        _, items = self._plan()
        code, problems, final = self._problems(items[0]["id"], {"groups": [SALE, SAWS], "remainder": REST})
        self.assertEqual((code, problems), (0, ""))
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "shopping_build_plan"],
                         ["Info"])
        self.assertEqual(self._finalize(items[0]["id"], "no_plan", None), 0)

    def test_invalid_plans_rejected_with_specific_problem(self):
        _, items = self._plan()
        rid = items[0]["id"]
        acme = {"campaign_id": "S2", "ad_group": "Acme", "key": {"brand": "acme"}}
        cases = [
            ({"groups": [SALE, SAWS, acme], "remainder": REST}, "offers assigned more than once"),
            ({"groups": [SALE, SAWS, {**acme, "key": {"brand": "acme", "product_type_l1": "garden"}}],
              "remainder": REST}, "empty group"),
            ({"groups": [SALE, {**acme, "key": {"brand": "makita"}}], "remainder": REST}, "does not exist"),
            ({"groups": [SALE, {**acme, "key": {"item_id": "p5"}}], "remainder": REST}, "does not exist"),
            ({"groups": [SALE, {**acme, "key": {"color": "red"}}], "remainder": REST}, "unsupported or absent"),
            ({"groups": [SALE, {**SAWS, "campaign_id": "P1"}], "remainder": REST}, "not in the requested campaigns"),
            ({"groups": [SALE, SAWS, SAWS], "remainder": REST}, "duplicates another group"),
            ({"groups": [SALE, SAWS]}, "must be explicit"),
            ({"groups": [SALE, SAWS], "remainder": {"exclude": True}}, "not be excluded"),
            ({"groups": [SALE, SAWS], "remainder": {**REST, "campaign_id": "S1"}}, "remainder must go to campaign S2"),
            ({"groups": [{**SALE, "campaign_id": "S2"}, SAWS], "remainder": REST}, "routing[0] requires priority 'high'"),
        ]
        for proposal, expected in cases:
            code, problems, _ = self._problems(rid, proposal)
            self.assertEqual(code, 4, proposal)
            self.assertIn(expected, problems, proposal)

    def test_routing_to_excluded_remainder_is_a_breach(self):
        _, items = self._plan(request={**BP_REQUEST, "remainder_campaign_id": None})
        code, problems, _ = self._problems(items[0]["id"], {"groups": [SAWS], "remainder": {"exclude": True}})
        self.assertEqual(code, 4)
        self.assertIn("→excluded", problems)
        code, _, _ = self._problems(items[0]["id"], {"groups": [SALE, SAWS], "remainder": {"exclude": True}})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
