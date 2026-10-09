"""test_check.py — skill-165 decision boundaries: item status, spend gate, destination scope, freshness, change rate, expiry.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-165-merchant-feed-freshness-and-item-status/tests
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes2 | initial tests
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

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check165", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

SNAP = "2026-09-03T12:00:00"
SHOP = "Shopping ads"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def item(offer, status, dest=SHOP, country="IT", **extra):
    return {"merchant_id": "m1", "offer_id": offer, "target_country": country, "destination": dest,
            "status": status, "snapshot_at": SNAP, **extra}


def perf(cid, offer, cost, clicks=10, date="2026-08-20", **extra):
    return {"campaign_id": cid, "offer_id": offer, "date": date, "clicks": clicks, "cost": cost, **extra}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def build(self, *, status=None, diag=None, product=None, feeds=None, changes=None, profile=None,
              currency="EUR", complete=True):
        ex = self.root / "export"
        _write(ex / "account.csv", [{"customer_id": "c1", "currency_code": currency, "date_range_start": "2026-08-01",
                                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-03",
                                     "conversion_lag_days": 2, "money_unit": "currency", "rates_format": "fraction"}])
        _write(ex / "campaigns.csv", [{"id": "10", "channel_type": "SHOPPING"},
                                      {"id": "20", "channel_type": "PERFORMANCE_MAX"},
                                      {"id": "30", "channel_type": "SEARCH"}])
        files = {"account.csv": None, "campaigns.csv": None}
        for rel, rows in (("external/merchant_item_status.csv", status), ("external/merchant_diagnostics.csv", diag),
                          ("custom/product_daily.csv", product), ("external/merchant_feeds.csv", feeds),
                          ("external/catalog_changes.csv", changes)):
            if rows is not None:
                _write(ex / rel, rows)
                files[rel] = None
        _write(ex / "table_manifest.csv", [{"filename": f, "completeness": "complete" if complete else "partial sample",
                                            "truncation": "none"} for f in files])
        prof = self.root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        return ex, prof

    def run_check(self, ex, prof) -> dict:
        out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                ["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)])
        self.assertEqual(code, 0)
        return json.loads((out / "result.json").read_text())

    @staticmethod
    def cov(res, cid):
        return next(c for c in res["coverage"] if c["check"] == cid)

    @staticmethod
    def found(res, cond, **entity):
        return [f for f in res["findings"] if f["condition_key"] == cond
                and all(str(f["entity"].get(k)) == str(v) for k, v in entity.items())]

    # ---------------------------------------------------------------- missing evidence
    def test_missing_merchant_evidence_is_skipped_never_pass(self):
        res = self.run_check(*self.build(product=[perf("10", "A", 500)]))
        for cid in ("catalog_status", "issue_codes", "spend_on_affected_items", "feed_freshness",
                    "change_frequency_vs_schedule", "expiring_items"):
            self.assertEqual(self.cov(res, cid)["status"], "skipped", cid)
        self.assertIn("external/merchant_item_status (file)", self.cov(res, "spend_on_affected_items")["missing"])
        self.assertEqual(res["findings"], [])

    # ---------------------------------------------------------------- catalog status
    def test_catalog_counts_conflicts_and_unknown_status(self):
        status = [item("A", "disapproved"), item("B", "approved"), item("C", "limited"),
                  item("D", "approved"), item("D", "disapproved"),  # conflicting key → excluded
                  item("E", "mystery")]
        res = self.run_check(*self.build(status=status))
        f = self.found(res, "destination_items_disapproved", destination=SHOP)
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["calculation"]["numerator"], f[0]["calculation"]["denominator"]), (1, 3))
        self.assertTrue(self.found(res, "destination_items_limited"))
        self.assertEqual(self.cov(res, "catalog_status")["status"], "partial")

    def test_all_approved_catalog_has_no_status_finding(self):
        res = self.run_check(*self.build(status=[item("A", "approved"), item("B", "approved")]))
        self.assertFalse([f for f in res["findings"] if f["check"] == "catalog_status"])
        self.assertEqual(self.cov(res, "catalog_status")["status"], "completed")

    # ---------------------------------------------------------------- spend gate
    def test_spend_gate_boundary_and_destination_scope(self):
        status = [item("A", "disapproved"), item("B", "disapproved"), item("C", "approved"),
                  item("F", "disapproved", dest="Free listings"), item("F", "approved")]
        product = [perf("10", "A", 100.0), perf("20", "B", 99.99), perf("10", "C", 900),
                   perf("10", "F", 900), perf("30", "A", 900)]
        res = self.run_check(*self.build(status=status, product=product))
        warn = self.found(res, "disapproved_item_recent_spend")
        self.assertEqual([(f["entity"]["campaign_id"], f["entity"]["offer_id"]) for f in warn], [("10", "A")])
        self.assertEqual(warn[0]["severity"], "Warning")
        minor = self.found(res, "disapproved_items_minor_spend", campaign_id="20")
        self.assertEqual(minor[0]["severity"], "Info")
        self.assertFalse(self.found(res, "disapproved_item_recent_spend", offer_id="F"))
        self.assertFalse(self.found(res, "disapproved_item_recent_spend", campaign_id="30"))
        obs = next(o for o in res["observations"] if o["check"] == "spend_on_affected_items"
                   and o["data"].get("campaign_id") == "10")
        self.assertAlmostEqual(obs["data"]["disapproved_cost_share"], 100 / 1900, places=5)
        self.assertTrue(any(r["condition_key"] == "disapproved_item_recent_spend" for r in res["ai_review"]))

    def test_country_join_prevents_cross_country_attribution(self):
        status = [item("A", "disapproved", country="DE"), item("A", "approved", country="IT")]
        res = self.run_check(*self.build(status=status, product=[perf("10", "A", 500, target_country="IT")]))
        self.assertFalse(self.found(res, "disapproved_item_recent_spend"))
        res2 = self.run_check(*self.build(status=status, product=[perf("10", "A", 500)]))
        self.assertTrue(self.found(res2, "disapproved_item_recent_spend"))
        self.assertEqual(self.cov(res2, "spend_on_affected_items")["status"], "partial")

    def test_unresolved_money_parameter_blocks_warning(self):
        res = self.run_check(*self.build(status=[item("A", "disapproved")], product=[perf("10", "A", 5000)],
                                         currency="USD"))
        self.assertFalse(self.found(res, "disapproved_item_recent_spend"))
        cov = self.cov(res, "spend_on_affected_items")
        self.assertEqual(cov["status"], "partial")
        self.assertTrue(any("spend_significant unresolved" in n for n in cov["notes"]))

    def test_finalize_critical_requires_evidence_ref(self):
        ex, prof = self.build(status=[item("A", "disapproved")], product=[perf("10", "A", 500)])
        res = self.run_check(ex, prof)
        rid = next(r["id"] for r in res["ai_review"] if r["condition_key"] == "disapproved_item_recent_spend")
        out = self.root / "out"
        for proposal, want in (({}, 4), ({"evidence_ref": "stock.csv#A"}, 0)):
            dec = self.root / "decisions.json"
            dec.write_text(json.dumps([{"id": rid, "outcome": "material_intended_blocked",
                                        "rationale": "in stock, top seller", "proposal": proposal}]))
            with contextlib.redirect_stdout(io.StringIO()):
                code = mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify,
                                    ["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out),
                                     "--decisions", str(dec)])
            self.assertEqual(code, want)
        final = json.loads((out / "final.json").read_text())
        sev = [f["severity"] for f in final["findings"] if f["condition_key"] == "disapproved_item_recent_spend"]
        self.assertEqual(sev, ["Critical"])

    # ---------------------------------------------------------------- issues
    def test_disapproving_issue_code_goes_to_review_demoted_does_not(self):
        diag = [{"merchant_id": "m1", "offer_id": "A", "target_country": "IT", "destination": SHOP,
                 "issue_code": "image_promo_overlay", "platform_severity": "disapproved"},
                {"merchant_id": "m1", "offer_id": "B", "target_country": "IT", "destination": SHOP,
                 "issue_code": "missing_color", "platform_severity": "demoted"}]
        res = self.run_check(*self.build(diag=diag))
        codes = [r["entity"]["issue_code"] for r in res["ai_review"] if r["condition_key"] == "issue_code_policy_meaning"]
        self.assertEqual(codes, ["image_promo_overlay"])
        self.assertFalse([f for f in res["findings"] if f["check"] == "issue_codes"])

    # ---------------------------------------------------------------- freshness
    def test_feed_staleness_boundary_failure_paused_and_unknown_interval(self):
        feeds = [{"merchant_id": "m1", "feed_id": "fresh", "fetch_interval_hours": 24,
                  "last_fetch_at": "2026-09-01T13:00:00", "last_fetch_status": "success", "snapshot_at": SNAP},
                 {"merchant_id": "m1", "feed_id": "stale", "fetch_interval_hours": 24,
                  "last_fetch_at": "2026-09-01T11:00:00", "last_fetch_status": "success", "snapshot_at": SNAP},
                 {"merchant_id": "m1", "feed_id": "failed", "fetch_interval_hours": 24,
                  "last_fetch_at": "2026-09-03T06:00:00", "last_fetch_status": "failure", "snapshot_at": SNAP},
                 {"merchant_id": "m1", "feed_id": "paused", "fetch_interval_hours": 24, "paused": "true",
                  "last_fetch_at": "2026-07-01T06:00:00", "last_fetch_status": "success", "snapshot_at": SNAP},
                 {"merchant_id": "m1", "feed_id": "noint", "fetch_interval_hours": "",
                  "last_fetch_at": "2026-07-01T06:00:00", "last_fetch_status": "success", "snapshot_at": SNAP}]
        res = self.run_check(*self.build(feeds=feeds))
        self.assertEqual([f["entity"]["feed_id"] for f in self.found(res, "feed_stale")], ["stale"])
        self.assertEqual(self.found(res, "feed_fetch_failed")[0]["entity"]["feed_id"], "failed")
        self.assertEqual(self.found(res, "feed_schedule_paused")[0]["severity"], "Info")
        self.assertFalse(self.found(res, "feed_stale", feed_id="noint"))
        self.assertEqual(self.cov(res, "feed_freshness")["status"], "partial")

    # ---------------------------------------------------------------- change frequency
    def _change_inputs(self):
        status = [item("A", "approved", feed_id="f1"), item("B", "approved", feed_id="f1")]
        feeds = [{"merchant_id": "m1", "feed_id": "f1", "fetch_interval_hours": 24,
                  "last_fetch_at": "2026-09-03T06:00:00", "last_fetch_status": "success", "snapshot_at": SNAP}]
        changes = [{"offer_id": "A", "field": "price", "changed_at": "2026-08-10T08:00:00"},
                   {"offer_id": "A", "field": "availability", "changed_at": "2026-08-10T15:00:00"},
                   {"offer_id": "B", "field": "price", "changed_at": "2026-08-10T08:00:00"},
                   {"offer_id": "B", "field": "price", "changed_at": "2026-08-11T08:00:00"}]
        diag = [{"merchant_id": "m1", "offer_id": "A", "target_country": "IT", "destination": SHOP,
                 "issue_code": "price_mismatch", "platform_severity": "disapproved"}]
        return status, feeds, changes, diag

    def test_change_rate_info_without_declared_mismatch_codes(self):
        status, feeds, changes, diag = self._change_inputs()
        res = self.run_check(*self.build(status=status, feeds=feeds, changes=changes, diag=diag))
        f = self.found(res, "change_frequency_exceeds_schedule", feed_id="f1")
        self.assertEqual(f[0]["calculation"]["numerator"], 1)  # only A exceeds 1 fetch/day
        self.assertFalse(self.found(res, "change_frequency_with_mismatch_issues"))
        self.assertEqual(self.cov(res, "change_frequency_vs_schedule")["status"], "partial")

    def test_change_rate_warning_with_declared_mismatch_issue(self):
        status, feeds, changes, diag = self._change_inputs()
        res = self.run_check(*self.build(status=status, feeds=feeds, changes=changes, diag=diag,
                                         profile={"feed_mismatch_issue_codes": ["price_mismatch"]}))
        self.assertEqual(self.found(res, "change_frequency_with_mismatch_issues", feed_id="f1")[0]["severity"], "Warning")

    def test_hourly_schedule_absorbs_same_changes(self):
        status, feeds, changes, diag = self._change_inputs()
        feeds[0]["fetch_interval_hours"] = 1
        res = self.run_check(*self.build(status=status, feeds=feeds, changes=changes, diag=diag,
                                         profile={"feed_mismatch_issue_codes": ["price_mismatch"]}))
        self.assertFalse([f for f in res["findings"] if f["check"] == "change_frequency_vs_schedule"])

    # ---------------------------------------------------------------- expiry
    def test_expiry_window_boundary(self):
        status = [item("A", "approved", expiration_date="2026-09-10"), item("B", "approved", expiration_date="2026-09-11"),
                  item("C", "approved", expiration_date="")]
        res = self.run_check(*self.build(status=status))
        f = self.found(res, "items_expiring_soon")
        self.assertEqual([x["offer_id"] for x in f[0]["evidence"]["sample"]], ["A"])
        self.assertEqual(self.cov(res, "expiring_items")["status"], "partial")


if __name__ == "__main__":
    unittest.main()
