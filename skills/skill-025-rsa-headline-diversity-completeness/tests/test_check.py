"""test_check.py — skill-025 boundaries: duplicates, Jaccard cutoff, missing RSA, Ad Strength, verify, rsa_draft.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-025-rsa-headline-diversity-completeness/tests
rules:   Temp folders only; asserts condition keys/severities and gating, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | tests for this session's check changes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | opt-in rsa_draft accept/reject boundaries
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

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_025", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

ACCOUNT = {"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}


def ad(ad_id, headlines, group="G1", status="ENABLED", strength="GOOD"):
    return {"id": ad_id, "campaign_id": "C1", "ad_group_id": group, "type": "RESPONSIVE_SEARCH_AD",
            "status": status, "headlines": " | ".join(headlines), "ad_strength": strength}


class CheckTests(unittest.TestCase):
    def _write(self, root, name, rows):
        path = root / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    def _run(self, ads, groups=("G1",), complete=True, metrics=None, lag="2", profile=None, keywords=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root, out = Path(tmp.name) / "e", Path(tmp.name) / "o"
        self._write(root, "account", [{**ACCOUNT, "conversion_lag_days": lag}])
        self._write(root, "campaigns", [{"id": "C1", "status": "ENABLED", "channel_type": "SEARCH", "languages": "it"}])
        self._write(root, "ad_groups", [{"id": g, "campaign_id": "C1", "status": "ENABLED"} for g in groups])
        self._write(root, "ads", ads)
        names = ["account.csv", "campaigns.csv", "ad_groups.csv", "ads.csv"]
        if metrics:
            self._write(root, "ad_metrics", metrics)
            names.append("ad_metrics.csv")
        if keywords:
            self._write(root, "keywords", keywords)
            names.append("keywords.csv")
        self._write(root, "table_manifest", [{"filename": n, "completeness": "complete" if complete else "partial",
                                              "truncation": "none"} for n in names])
        prof = Path(tmp.name) / "profile.json"
        prof.write_text(json.dumps({"objectives": ["online purchases"], "product_service_taxonomy": ["power tools"],
                                    **(profile or {})}))
        self.prof = prof
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(root), "--profile", str(prof), "--out", str(out)])
        self.assertEqual(code, 0)
        self.root, self.out = root, out
        return json.loads((out / "result.json").read_text())

    def _keys(self, body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    def test_normalized_duplicate_detected_but_punctuation_kept(self):
        body = self._run([ad("A", ["Cordless Drills", "cordless  DRILLS", "Drills!", "Drills"])])
        f = self._keys(body, "normalized_duplicate_headlines")
        self.assertEqual(len(f), 1)
        self.assertEqual(len(f[0]["evidence"]["groups"]), 1)  # "Drills!" and "Drills" stay distinct

    def test_jaccard_boundary(self):
        # 3/4 = 0.75 > 0.70 → near duplicate
        body = self._run([ad("A", ["red cordless drill set", "red cordless drill", "Garden hose"])])
        self.assertEqual(len(self._keys(body, "near_duplicate_headlines")), 1)
        # 2/3 ≈ 0.667 → not flagged
        body = self._run([ad("A", ["cordless drill", "cordless drill sale", "Garden hose"])])
        self.assertEqual(self._keys(body, "near_duplicate_headlines"), [])

    def test_paused_ad_not_a_finding(self):
        body = self._run([ad("A", ["Drills", "drills", "Saws"], status="PAUSED"), ad("B", ["X1", "Y1", "Z1"])])
        self.assertEqual(self._keys(body, "normalized_duplicate_headlines"), [])

    def test_ad_group_without_rsa_needs_complete_inventory(self):
        body = self._run([ad("A", ["X1", "Y1", "Z1"])], groups=("G1", "G2"))
        f = self._keys(body, "ad_group_without_enabled_rsa")
        self.assertEqual([x["entity"]["ad_group_id"] for x in f], ["G2"])
        self.assertEqual(f[0]["severity"], "Info")
        body = self._run([ad("A", ["X1", "Y1", "Z1"])], groups=("G1", "G2"), complete=False)
        self.assertEqual(self._keys(body, "ad_group_without_enabled_rsa"), [])
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["ad_groups_without_rsa"], "partial")

    def test_ad_strength_unknown_is_coverage_not_poor(self):
        body = self._run([ad("A", ["X1", "Y1", "Z1"], strength=""), ad("B", ["X2", "Y2", "Z2"], strength="POOR")])
        f = self._keys(body, "ad_strength_poor_or_average")
        self.assertEqual([x["entity"]["ad_id"] for x in f], ["B"])
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["ad_strength"], "partial")

    def test_missing_headlines_column_skips(self):
        body = self._run([{"id": "A", "campaign_id": "C1", "ad_group_id": "G1", "type": "RESPONSIVE_SEARCH_AD",
                           "status": "ENABLED"}])
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["exact_duplicates"], "skipped")
        self.assertEqual(body["findings"], [])

    def test_rating_outcomes_gated_by_maturity(self):
        metrics = [{"ad_id": "A", "campaign_id": "C1", "ad_group_id": "G1", "impressions": 5000, "clicks": 300,
                    "cost": 100, "conversions": 10}]
        body = self._run([ad("A", ["X1", "Y1", "Z1"])], metrics=metrics, lag="")
        obs = [o["data"] for o in body["observations"] if o["check"] == "rating_outcomes"]
        self.assertIsNone(obs[0]["ctr"])
        cov = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertEqual(cov["rating_outcomes"], "partial")

    def test_theme_gap_verify_rejects_duplicate_and_overwide(self):
        body = self._run([ad("A", ["Cordless Drills", "Top Brands", "Fast Delivery"])])
        item = body["ai_review"][0]
        dec = self.out.parent / "d.json"
        for proposal, code in (({"headlines": ["cordless drills"]}, 4),
                               ({"headlines": ["x" * 31]}, 4),
                               ({"headlines": ["2-Year Warranty"]}, 0)):
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "theme_gap", "rationale": "no proof theme",
                                        "proposal": proposal}]))
            with contextlib.redirect_stdout(io.StringIO()):
                got = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                 ["finalize", "--export", str(self.root), "--profile", str(self.prof), "--out", str(self.out),
                                  "--decisions", str(dec)])
            self.assertEqual(got, code, proposal)

    def test_warning_outcome_requires_evidence_ref(self):
        body = self._run([ad("A", ["Best Price Guaranteed", "Top Brands", "Fast Delivery"])])
        item = body["ai_review"][0]
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "confirmed_claim_or_constraint_violation",
                                    "rationale": "unsupported guarantee"}]))
        with contextlib.redirect_stdout(io.StringIO()):
            got = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                             ["finalize", "--export", str(self.root), "--profile", str(self.prof), "--out", str(self.out),
                                  "--decisions", str(dec)])
        self.assertEqual(got, 4)


DRAFT_PROFILE = {"rsa_draft_requests": ["G1"], "competitor_terms": ["Bosch"],
                 "campaign_objectives": {"C1": {"brand_policy": "nonbrand_only", "excluded_intent_terms": ["free"]}},
                 "approved_claims": ["Save 20% on drills", "Drills from 79 EUR"]}
KEYWORDS = [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "cordless drill", "match_type": "PHRASE",
             "status": "ENABLED"}]
VALID = {"headlines": [{"text": "Cordless Drills", "pin": 1}, {"text": "Save 20% on Drills"},
                       {"text": "{KeyWord:Power Drills}"}, {"text": "Drills from 79 EUR"}],
         "descriptions": [{"text": "Shop cordless drills online with fast delivery.", "pin": 1},
                          {"text": "Compare {CUSTOMIZER.Product:drill} models today."}],
         "path1": "{KeyWord:drills}", "path2": "cordless", "final_url": "https://shop.example/drills/"}


def dad(ad_id, group="G1", url="https://shop.example/drills"):
    return {**ad(ad_id, ["Cordless Drills 18V", "Top Brands", "Fast Delivery"], group),
            "descriptions": "Buy now. | Fast delivery.", "final_url": url}


class DraftTests(unittest.TestCase):
    _write, _run = CheckTests._write, CheckTests._run

    def _items(self, profile=None, keywords=KEYWORDS, ads=None, groups=("G1",)):
        body = self._run(ads or [dad("A")], groups=groups, profile={**DRAFT_PROFILE, **(profile or {})},
                         keywords=keywords)
        return body, [r for r in body["ai_review"] if r["condition_key"] == "rsa_draft"]

    def _finalize(self, rid, outcome, proposal):
        dec = self.out.parent / "d.json"
        dec.write_text(json.dumps([{"id": rid, "outcome": outcome, "rationale": "requested draft",
                                    "proposal": proposal}]))
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.root), "--profile", str(self.prof),
                               "--out", str(self.out), "--decisions", str(dec)])
        final = json.loads((self.out / "final.json").read_text())
        return code, "; ".join(final["review_log"][0]["problems"]), final

    def test_not_applicable_without_request(self):
        body = self._run([dad("A")], keywords=KEYWORDS)
        self.assertEqual({c["check"]: c["status"] for c in body["coverage"]}["rsa_draft"], "not_applicable")
        self.assertFalse(any(r["condition_key"] == "rsa_draft" for r in body["ai_review"]))

    def test_review_only_for_requested_groups_with_existing_destination(self):
        body, items = self._items({"rsa_draft_requests": ["G1", "G2", "G9"]},
                                  ads=[dad("A"), dad("B", group="G2", url="")], groups=("G1", "G2"))
        self.assertEqual([r["entity"]["ad_group_id"] for r in items], ["G1"])
        self.assertEqual(items[0]["evidence"]["existing_final_urls"], ["https://shop.example/drills"])
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "rsa_draft")["status"], "partial")

    def test_campaign_request_needs_explicit_scope(self):
        self.assertEqual(self._items({"rsa_draft_requests": [{"campaign_id": "C1"}]})[1], [])
        _, items = self._items({"rsa_draft_requests": [{"campaign_id": "C1", "scope": "enabled_ad_groups"}]})
        self.assertEqual([r["entity"]["ad_group_id"] for r in items], ["G1"])

    def test_valid_draft_accepted_as_info_proposal(self):
        _, items = self._items()
        code, problems, final = self._finalize(items[0]["id"], "draft_proposed", VALID)
        self.assertEqual((code, problems), (0, ""))
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "rsa_draft"], ["Info"])
        self.assertEqual(self._finalize(items[0]["id"], "no_draft", None)[0], 0)

    def test_invalid_drafts_rejected_with_specific_problem(self):
        _, items = self._items()
        H, D = VALID["headlines"], VALID["descriptions"]
        cases = [
            ({"headlines": H + [{"text": "x" * 31}]}, "columns with default text > 30"),
            ({"headlines": H + [{"text": "{KeyWord:Professional Cordless Drill Sets}"}]}, "columns with default text > 30"),
            ({"headlines": H[:2]}, "allowed 3..15"),
            ({"descriptions": D[:1]}, "allowed 2..4"),
            ({"headlines": H + [{"text": "cordless  DRILLS"}]}, "duplicates headline 1"),
            ({"headlines": H + [{"text": "Top Brands", "pin": 4}]}, "not in positions [1, 2, 3]"),
            ({"descriptions": D[:1] + [{"text": "Fast delivery.", "pin": 3}]}, "not in positions [1, 2]"),
            ({"headlines": H + [{"text": "{KEYWORD:Drills}"}]}, "unsupported insertion token"),
            ({"headlines": H + [{"text": "{KeyWord:}"}]}, "needs a non-empty default"),
            ({"headlines": H + [{"text": "Ends {COUNTDOWN(2026-12-31 23:59:59,5)}"}]}, "countdown"),
            ({"headlines": H + [{"text": "Drills {sale"}]}, "unbalanced"),
            ({"headlines": H + [{"text": "{CUSTOMIZER._Name:drill}"}]}, "customizer attribute name"),
            ({"headlines": H + [{"text": "{LOCATION(City):Rome} {LOCATION(City):Rome}"}]}, "more than 1 location"),
            ({"path1": "cordless-drills-pro"}, "columns > 15"),
            ({"path2": "{CUSTOMIZER.Product:drill}"}, "only keyword insertion"),
            ({"headlines": H + [{"text": "Better than Bosch"}]}, "competitor term 'bosch'"),
            ({"headlines": H + [{"text": "Free Drill Case"}]}, "excluded term 'free'"),
            ({"final_url": "https://other.example/drills"}, "not an existing destination"),
            ({"final_url": "https://shop.example/{KeyWord:drills}"}, "cannot contain insertion tokens"),
            ({"headlines": H + [{"text": "Save 30% on Drills"}]}, "not in profile.approved_claims"),
            ({"headlines": H + [{"text": "Save 20 EUR Today"}]}, "not in profile.approved_claims"),
        ]
        for change, expected in cases:
            code, problems, _ = self._finalize(items[0]["id"], "draft_proposed", {**VALID, **change})
            self.assertEqual(code, 4, change)
            self.assertIn(expected, problems, change)

    def test_policy_and_claims_boundaries(self):
        extra = {"headlines": VALID["headlines"] + [{"text": "Better than Bosch"}, {"text": "Save 30% on Drills"}]}
        _, items = self._items({"campaign_objectives": {"C1": {"brand_policy": "competitor_only"}},
                                "approved_claims": None})
        self.assertEqual(self._finalize(items[0]["id"], "draft_proposed", {**VALID, **extra})[:2], (0, ""))
        bosch_kw = KEYWORDS + [{**KEYWORDS[0], "id": "K2", "text": "bosch drill"}]
        _, items = self._items(keywords=bosch_kw)
        code, problems, _ = self._finalize(items[0]["id"], "draft_proposed", VALID)
        self.assertEqual(code, 4)
        self.assertIn("could insert keyword 'bosch drill'", problems)


if __name__ == "__main__":
    unittest.main()
