"""test_check.py — skill-088 decision boundaries: taxonomy joins, completeness gates, reviews, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-088-google-product-category-granularity/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check088", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check088"] = mod
_spec.loader.exec_module(mod)

MP = "external/merchant_products.csv"
TAX = "external/google_taxonomy.csv"
REF = "external/product_reference.csv"
DIAG = "external/merchant_diagnostics.csv"
USE = "external/category_usage.csv"
DAILY = "custom/product_daily.csv"
TAXONOMY = [("1", "Apparel & Accessories", ""), ("2", "Apparel & Accessories > Clothing", "1"),
            ("3", "Apparel & Accessories > Clothing > Shirts & Tops", "2"), ("4", "Home & Garden", ""),
            ("5", "Home & Garden > Kitchen & Dining", "4")]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def product(offer, sub, eff, group="", lang="en", dest="Shopping ads", title="t"):
    return {"merchant_id": "m1", "channel": "online", "content_language": lang, "feed_label": "IT", "offer_id": offer,
            "target_country": "IT", "destination": dest, "submitted_google_product_category": sub,
            "effective_google_product_category": eff, "item_group_id": group, "title": title, "product_type": "pt"}


def default_products():
    return [product("A", "", "2", "G1", title="Linen shirt"), product("A", "", "2", "G1", dest="Free listings"),
            product("B", "3", "3", "G1"), product("C", "Home & Garden > Kitchen & Dining", "5", "G2"),
            product("D", "999", "2")]


def build(root: Path, *, products=None, incomplete=(), drop=(), drop_cols=None, refs=None) -> tuple[Path, Path]:
    ex = root / "export"
    shutil.rmtree(ex, ignore_errors=True)
    _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                                 "date_range_end": "2026-08-30", "snapshot_date": "2026-09-05",
                                 "conversion_lag_days": 2, "money_unit": "currency", "rates_format": "fraction"}])
    tables = {
        MP: products if products is not None else default_products(),
        TAX: [{"category_id": i, "full_path": p, "parent_id": par, "language": "en-US", "fetched_at": "2026-09-01",
               "published_version": "2021-09-21"} for i, p, par in TAXONOMY],
        REF: refs if refs is not None else [
            {"offer_id": o, "target_country": "IT", "product_function": f, "evidence_reference": f"pim:{o}"}
            for o, f in (("A", "shirt"), ("B", "shirt"), ("C", "kettle"), ("D", "shirt"))],
        DIAG: [{"offer_id": "D", "target_country": "IT", "destination": "Shopping ads", "issue_code": "incorrect_category",
                "attribute": "google_product_category", "platform_severity": "error", "eligibility_status": "Disapproved",
                "source_reference": "mc:1"},
               {"offer_id": "B", "target_country": "IT", "destination": "Shopping ads", "issue_code": "missing_color",
                "attribute": "color", "platform_severity": "error", "eligibility_status": "disapproved",
                "source_reference": "mc:2"},
               {"offer_id": "C", "target_country": "IT", "destination": "Shopping ads", "issue_code": "category_hint",
                "attribute": "google product category", "platform_severity": "warning",
                "eligibility_status": "eligible_limited", "source_reference": "mc:3"}],
        USE: [{"usage_id": "U1", "campaign_id": "k1", "category_id": "5", "listing_rule_reference": "lr1"},
              {"usage_id": "U2", "campaign_id": "k1", "category_id": "777", "listing_rule_reference": "lr2"}],
        DAILY: [{"campaign_id": "k1", "offer_id": "D", "target_country": "IT", "date": "2026-08-10", "impressions": 100,
                 "clicks": 5, "cost": 10, "conversions": 0},
                {"campaign_id": "k1", "offer_id": "D", "target_country": "IT", "date": "2026-08-10", "impressions": 100,
                 "clicks": 5, "cost": 10, "conversions": 0},
                {"campaign_id": "k2", "offer_id": "D", "target_country": "IT", "date": "2026-08-11", "impressions": 50,
                 "clicks": 2, "cost": 5, "conversions": 1},
                {"campaign_id": "k1", "offer_id": "D", "target_country": "IT", "date": "2026-07-01", "impressions": 50,
                 "clicks": 2, "cost": 99, "conversions": 0}],
    }
    files = ["account.csv"]
    for name, rows in tables.items():
        if name in drop:
            continue
        if drop_cols and name in drop_cols:
            rows = [{k: v for k, v in r.items() if k not in drop_cols[name]} for r in rows]
        _write(ex / name, rows)
        files.append(name)
    _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "partial" if f in incomplete else "complete",
                                        "truncation": "none"} for f in files])
    prof = root / "profile.json"
    prof.write_text(json.dumps({}))
    return ex, prof


def run(ex: Path, prof: Path) -> dict:
    return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()


def cov(body: dict) -> dict:
    return {c["check"]: c for c in body["coverage"]}


def findings(body: dict, key: str) -> list[dict]:
    return [f for f in body["findings"] if f["condition_key"] == key]


def obs(body: dict, check: str, prefix: str) -> dict:
    return [o for o in body["observations"] if o["check"] == check and o["text"].startswith(prefix)][0]["data"]


def cli(*args) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, [str(a) for a in args])


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def finalize(self, ex, prof, decisions) -> tuple[int, dict]:
        out = self.root / "out"
        dec = self.root / "decisions.json"
        dec.write_text(json.dumps(decisions))
        code = cli("finalize", "--export", ex, "--profile", prof, "--out", out, "--decisions", dec)
        return code, json.loads((out / "final.json").read_text())

    def first_run(self, ex, prof) -> dict:
        out = self.root / "out"
        self.assertEqual(cli("run", "--export", ex, "--profile", prof, "--out", out), 0)
        return json.loads((out / "result.json").read_text())

    def test_destinations_collapse_and_depth_stays_descriptive(self):
        body = run(*build(self.root))
        inv = obs(body, "category_inventory", "Catalog category inventory")
        self.assertEqual(inv["products"], 4)
        self.assertEqual(inv["destination_rows_collapsed"], 1)
        self.assertEqual(inv["submitted_equals_effective"], 2)
        self.assertEqual(inv["submitted_vs_effective_undetermined"], 1)
        depth = obs(body, "category_inventory", "Taxonomy source")
        self.assertEqual(depth["effective_depth_distribution"], {"2": 3, "3": 1})
        self.assertEqual(depth["taxonomy"]["published_version"], ["2021-09-21"])
        self.assertEqual([f for f in body["findings"] if f["check"] in ("category_inventory", "override_applicability")], [])
        self.assertEqual(cov(body)["category_inventory"]["status"], "completed")

    def test_automatic_categorization_is_not_a_finding(self):
        body = run(*build(self.root))
        o = obs(body, "override_applicability", "Category assignment basis")
        self.assertEqual((o["automatic_submitted_empty"], o["manual_submitted"]), (1, 3))
        self.assertEqual(o["manual_matches_effective"], 2)

    def test_unknown_id_is_warning_only_with_certified_taxonomy(self):
        body = run(*build(self.root))
        inv = findings(body, "invalid_current_mapping")
        self.assertEqual(sorted((f["check"], f["severity"], json.dumps(f["entity"], sort_keys=True)) for f in inv), [
            ("requirement_trace", "Warning", json.dumps({"campaign_id": "k1", "category_id": "777", "usage_id": "U2"},
                                                        sort_keys=True)),
            ("taxonomy_validity", "Warning", json.dumps({"category_value": "999",
                                                         "field": "submitted_google_product_category"}, sort_keys=True))])
        body = run(*build(self.root, incomplete=(TAX,)))
        self.assertEqual(findings(body, "invalid_current_mapping"), [])
        self.assertEqual(cov(body)["taxonomy_validity"]["status"], "partial")
        self.assertEqual(cov(body)["requirement_trace"]["status"], "partial")
        values = obs(body, "taxonomy_validity", "Category values not found")["values"]
        self.assertEqual([v["category_value"] for v in values], ["999"])

    def test_text_path_in_uncovered_language_is_undecidable(self):
        prods = default_products() + [product("E", "Haus & Garten > Küche", "5", lang="de")]
        body = run(*build(self.root, products=prods))
        vals = [f["entity"]["category_value"] for f in findings(body, "invalid_current_mapping")
                if f["check"] == "taxonomy_validity"]
        self.assertEqual(vals, ["999"])
        self.assertEqual(obs(body, "taxonomy_validity", "Taxonomy validity screen")["undecidable_values"], 1)
        self.assertEqual(cov(body)["taxonomy_validity"]["status"], "partial")

    def test_one_function_review_per_distinct_category_function_pair(self):
        body = run(*build(self.root))
        items = [r for r in body["ai_review"] if r["check"] == "function_accuracy"]
        self.assertEqual(sorted((r["entity"]["effective_category_id"], r["entity"]["product_function"]) for r in items),
                         [("2", "shirt"), ("3", "shirt"), ("5", "kettle")])
        pair = [r for r in items if r["entity"]["effective_category_id"] == "2"][0]
        self.assertEqual(pair["evidence"]["product_count"], 2)
        self.assertEqual(pair["outcomes"]["wrong_function"]["severity"], "Warning")
        self.assertIsNone(pair["outcomes"]["accurate"]["severity"])
        self.assertEqual(findings(body, "category_function_fit"), [])

    def test_missing_function_evidence_skips_not_passes(self):
        body = run(*build(self.root, drop=(REF,)))
        c = cov(body)["function_accuracy"]
        self.assertEqual((c["status"], c["missing"]), ("skipped", ["external/product_reference (file)"]))
        body = run(*build(self.root, refs=[{"offer_id": "A", "target_country": "IT", "product_function": "",
                                            "evidence_reference": "x"}]))
        self.assertEqual(cov(body)["function_accuracy"]["status"], "partial")
        self.assertEqual([r for r in body["ai_review"] if r["check"] == "function_accuracy"], [])

    def test_missing_effective_column_skips_dependent_checks(self):
        body = run(*build(self.root, drop_cols={MP: ("effective_google_product_category",)}))
        c = cov(body)
        self.assertEqual(c["function_accuracy"]["status"], "skipped")
        self.assertIn("external/merchant_products:effective_google_product_category", c["function_accuracy"]["missing"])
        self.assertEqual(c["variant_consistency"]["status"], "skipped")
        self.assertEqual(c["category_inventory"]["status"], "partial")

    def test_category_proposals_are_verified_against_taxonomy(self):
        ex, prof = build(self.root)
        body = self.first_run(ex, prof)
        items = {(r["check"], r["entity"].get("effective_category_id")): r for r in body["ai_review"]}
        shallow, specific = items[("function_accuracy", "2")], items[("function_accuracy", "3")]
        ok = {"override_purpose": "more_specific_accurate_category", "evidence_reference": "pim:A"}
        code, final = self.finalize(ex, prof, [
            {"id": shallow["id"], "outcome": "more_specific_available", "rationale": "r",
             "proposal": {**ok, "category_id": "5"}},
            {"id": specific["id"], "outcome": "wrong_function", "rationale": "r",
             "proposal": {"category_id": "5", "override_purpose": "correct_inaccurate_category"}}])
        self.assertEqual(code, 4)
        self.assertEqual({x["status"] for x in final["review_log"]}, {"rejected"})
        code, final = self.finalize(ex, prof, [
            {"id": shallow["id"], "outcome": "more_specific_available", "rationale": "r",
             "proposal": {**ok, "category_id": "3"}},
            {"id": specific["id"], "outcome": "wrong_function", "rationale": "r",
             "proposal": {"category_id": "5", "override_purpose": "correct_inaccurate_category",
                          "evidence_reference": "pim:B"}}])
        self.assertEqual(code, 0)
        sev = sorted((f["entity"]["effective_category_id"], f["severity"]) for f in findings(final, "category_function_fit"))
        self.assertEqual(sev, [("2", "Info"), ("3", "Warning")])

    def test_variant_divergence_is_provisional_info(self):
        ex, prof = build(self.root)
        body = self.first_run(ex, prof)
        f = findings(body, "variant_category_divergence")
        self.assertEqual([(x["entity"]["item_group_id"], x["severity"]) for x in f], [("G1", "Info")])
        item = [r for r in body["ai_review"] if r["check"] == "variant_consistency"][0]
        self.assertEqual(item["provisional_finding"], f[0]["id"])
        code, final = self.finalize(ex, prof, [{"id": item["id"], "outcome": "legitimately_different", "rationale": "r"}])
        self.assertEqual(code, 0)
        self.assertEqual(findings(final, "variant_category_divergence"), [])
        prods = [p if p["offer_id"] != "B" else {**p, "effective_google_product_category": "2"} for p in default_products()]
        body = run(*build(self.root, products=prods))
        self.assertEqual(findings(body, "variant_category_divergence"), [])

    def test_blocking_category_diagnostic_warning_and_critical_gate(self):
        ex, prof = build(self.root)
        body = self.first_run(ex, prof)
        f = findings(body, "category_diagnostic_blockage")
        self.assertEqual([(x["entity"]["offer_id"], x["severity"]) for x in f], [("D", "Warning")])
        exposure = f[0]["evidence"]["exposure"]
        self.assertEqual((exposure["cost"], exposure["clicks"], exposure["conversions"]), (15, 7, 1))
        trace = obs(body, "requirement_trace", "Diagnostics traced")
        self.assertEqual((trace["non_blocking_category_issues"], trace["other_attribute_issues_delegated_to_skill_083"]),
                         (1, 1))
        item = [r for r in body["ai_review"] if r["condition_key"] == "category_diagnostic_blockage"][0]
        code, _ = self.finalize(ex, prof, [{"id": item["id"], "outcome": "material_blockage", "rationale": "r",
                                            "proposal": {}}])
        self.assertEqual(code, 4)
        code, final = self.finalize(ex, prof, [{"id": item["id"], "outcome": "material_blockage", "rationale": "r",
                                                "proposal": {"evidence_ref": "mc:1"}}])
        self.assertEqual(code, 0)
        self.assertEqual([x["severity"] for x in findings(final, "category_diagnostic_blockage")], ["Critical"])

    def test_trace_runs_without_catalog_and_skips_without_trace_inputs(self):
        body = run(*build(self.root, drop=(MP,)))
        c = cov(body)
        self.assertEqual(c["function_accuracy"]["status"], "skipped")
        self.assertEqual(c["requirement_trace"]["status"], "partial")
        self.assertEqual(len(findings(body, "category_diagnostic_blockage")), 1)
        body = run(*build(self.root, drop=(DIAG, USE)))
        c = cov(body)["requirement_trace"]
        self.assertEqual((c["status"], c["missing"]), ("skipped", ["external/category_usage (file)",
                                                                   "external/merchant_diagnostics (file)"]))


if __name__ == "__main__":
    unittest.main()
