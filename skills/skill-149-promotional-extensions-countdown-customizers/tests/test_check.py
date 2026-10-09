"""test_check.py — decision-boundary tests for skill-149 scripts/check.py.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-149-promotional-extensions-countdown-customizers/tests
rules:   stdlib only; temp folders; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial tests
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check149", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

OFFER_COLS = ["offer_id", "campaign_id", "market", "offer_text", "discount_type", "discount_value", "currency",
              "eligibility", "minimum_order", "promo_code", "start_at", "end_at", "timezone",
              "landing_page_snapshot_ref", "approved_by"]
CFG_COLS = ["account_id", "asset_or_ad_id", "association_id", "snapshot_at", "campaign_id", "ad_group_id",
            "linking_level", "status", "policy_status", "configured_discount", "start_date", "end_date", "schedule",
            "countdown_raw_text", "countdown_timezone_mode", "preview_at", "preview_result", "actual_serving_dates"]


def offer(**kw):
    r = {"offer_id": "O1", "campaign_id": "C1", "discount_type": "percent", "discount_value": "20",
         "start_at": "2026-08-10", "end_at": "2026-08-20", "timezone": "Europe/Rome", "approved_by": "marketing",
         "landing_page_snapshot_ref": "lp-1"}
    r.update(kw)
    return r


def cfg(**kw):
    r = {"asset_or_ad_id": "A1", "association_id": "L1", "snapshot_at": "2026-08-30", "campaign_id": "C1",
         "linking_level": "campaign", "status": "ENABLED", "configured_discount": "20%", "start_date": "2026-08-10",
         "end_date": "2026-08-20"}
    r.update(kw)
    return r


class Case:
    def __init__(self, test, cfg_complete="complete"):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = self.root / "export"
        self.completeness = {}
        self.cfg_complete = cfg_complete
        self.write("account", ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date",
                               "conversion_lag_days"],
                   [{"customer_id": "demo", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}])
        self.write("campaigns", ["id", "status", "channel_type"],
                   [{"id": "C1", "status": "ENABLED", "channel_type": "SEARCH"},
                    {"id": "C2", "status": "ENABLED", "channel_type": "SEARCH"}])

    def write(self, key, cols, rows):
        p = self.export / f"{key}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
        self.completeness[f"{key}.csv"] = self.cfg_complete if key == "custom/promotion_config" else "complete"

    def run(self):
        with (self.export / "table_manifest.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "completeness", "truncation"])
            for fn in sorted(self.completeness):
                w.writerow([fn, self.completeness[fn], "none"])
        self.prof = self.root / "profile.json"
        self.prof.write_text("{}")
        self.out = self.root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["run", "--export", str(self.export), "--profile", str(self.prof), "--out", str(self.out)])
        assert code == 0
        return json.loads((self.out / "result.json").read_text())

    def finalize(self, decisions):
        d = self.root / "decisions.json"
        d.write_text(json.dumps(decisions))
        with contextlib.redirect_stdout(io.StringIO()):
            return M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                              ["finalize", "--export", str(self.export), "--profile", str(self.prof), "--out",
                               str(self.out), "--decisions", str(d)])


def cov(body, check):
    return next(c for c in body["coverage"] if c["check"] == check)


def keys(body, key):
    return [f for f in body["findings"] if f["condition_key"] == key]


class CheckTests(unittest.TestCase):
    def run_case(self, offers, cfgs, cfg_complete="complete"):
        c = Case(self, cfg_complete)
        c.write("external/promotion_offers", OFFER_COLS, offers)
        c.write("custom/promotion_config", CFG_COLS, cfgs)
        return c, c.run()

    def test_discount_mismatch_warns_match_does_not(self):
        _, bad = self.run_case([offer()], [cfg(configured_discount="25%")])
        self.assertEqual([f["severity"] for f in keys(bad, "offer_config_conflict")], ["Warning"])
        _, kind = self.run_case([offer()], [cfg(configured_discount="EUR 20")])  # amount vs percent
        self.assertEqual(len(keys(kind, "offer_config_conflict")), 1)
        _, ok = self.run_case([offer()], [cfg()])
        self.assertFalse(ok["findings"])
        self.assertEqual(cov(ok, "offer_terms")["status"], "completed")

    def test_ambiguous_discount_goes_to_review(self):
        _, body = self.run_case([offer()], [cfg(configured_discount="up to 20% or 10 off")])
        self.assertFalse(keys(body, "offer_config_conflict"))
        self.assertEqual(len([r for r in body["ai_review"] if r["condition_key"] == "offer_config_conflict"]), 1)

    def test_multiple_offers_in_campaign_are_not_guessed(self):
        _, body = self.run_case([offer(), offer(offer_id="O2", discount_value="30")], [cfg(configured_discount="30%")])
        self.assertFalse(body["findings"])
        self.assertEqual(cov(body, "offer_terms")["status"], "partial")

    def test_unlinked_asset_proves_no_coverage(self):
        _, body = self.run_case([offer(end_at="2026-09-20")], [cfg(status="REMOVED", configured_discount="50%")])
        self.assertFalse(keys(body, "offer_config_conflict"))
        self.assertEqual(len(keys(body, "absent_optional_feature")), 1)

    def test_configured_window_outside_offer_warns(self):
        _, body = self.run_case([offer()], [cfg(end_date="2026-08-25")])
        self.assertEqual([f["severity"] for f in keys(body, "offer_window_conflict")], ["Warning"])

    def test_countdown_target_boundaries(self):
        _, wrong = self.run_case([offer()], [cfg(countdown_raw_text='{=COUNTDOWN("2026/08/25 23:59:59")}',
                                                 preview_result="rendered")])
        self.assertEqual(len(keys(wrong, "countdown_target_conflict")), 1)
        _, right = self.run_case([offer()], [cfg(countdown_raw_text='{=COUNTDOWN("2026/08/20 23:59:59")}',
                                                 preview_result="rendered")])
        self.assertFalse(right["findings"])
        self.assertEqual([r["condition_key"] for r in right["ai_review"]], ["countdown_timezone_mode"])
        _, start = self.run_case([offer()], [cfg(countdown_raw_text='{=COUNTDOWN("2026/08/10 00:00:00")}',
                                                 preview_result="rendered")])
        self.assertFalse(keys(start, "countdown_target_conflict"))
        self.assertEqual([r["condition_key"] for r in start["ai_review"]], ["countdown_target_conflict"])
        _, nopreview = self.run_case([offer()], [cfg(countdown_raw_text='{=COUNTDOWN("2026/08/20 23:59:59")}')])
        self.assertEqual([f["severity"] for f in keys(nopreview, "countdown_unverified")], ["Info"])

    def test_expired_offer_serving_after_end(self):
        _, served = self.run_case([offer()], [cfg(actual_serving_dates="2026-08-18..2026-08-22")])
        self.assertEqual([f["severity"] for f in keys(served, "serving_after_offer_end")], ["Warning"])
        self.assertTrue(any(o.get("severity") == "Critical" for r in served["ai_review"] for o in r["outcomes"].values()))
        _, stopped = self.run_case([offer()], [cfg(actual_serving_dates="2026-08-18;2026-08-20")])
        self.assertEqual([f["severity"] for f in keys(stopped, "expired_nonserving_config")], ["Info"])
        self.assertFalse(keys(stopped, "serving_after_offer_end"))
        _, unknown = self.run_case([offer()], [cfg()])
        self.assertEqual(cov(unknown, "expired_serving")["status"], "partial")
        self.assertFalse(keys(unknown, "expired_nonserving_config"))

    def test_optional_absence_needs_complete_config(self):
        offers = [offer(), offer(offer_id="O9", campaign_id="C2", end_at="2026-09-30")]
        _, full = self.run_case(offers, [cfg()])
        self.assertEqual([f["entity"]["offer_id"] for f in keys(full, "absent_optional_feature")], ["O9"])
        self.assertEqual(keys(full, "absent_optional_feature")[0]["severity"], "Info")
        _, part = self.run_case(offers, [cfg()], cfg_complete="partial")
        self.assertFalse(keys(part, "absent_optional_feature"))
        self.assertEqual(cov(part, "optional_feature")["status"], "partial")

    def test_critical_requires_evidence_ref(self):
        c, body = self.run_case([offer()], [cfg(actual_serving_dates="2026-08-18..2026-08-22")])
        rid = next(r["id"] for r in body["ai_review"] if r["condition_key"] == "serving_after_offer_end")
        self.assertEqual(c.finalize([{"id": rid, "outcome": "material_live_misleading", "rationale": "served"}]), 4)
        self.assertEqual(c.finalize([{"id": rid, "outcome": "material_live_misleading", "rationale": "served",
                                      "proposal": {"evidence_ref": "delivery-2026-08-22.csv"}}]), 0)
        final = json.loads((c.out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in keys(final, "serving_after_offer_end")], ["Critical"])

    def test_missing_offers_skip_dependent_checks(self):
        c = Case(self)
        c.write("custom/promotion_config", CFG_COLS, [cfg()])
        body = c.run()
        self.assertEqual(cov(body, "association_scope")["status"], "completed")
        for chk in ("offer_terms", "countdown_config", "expired_serving", "optional_feature", "correction_drafts"):
            self.assertEqual(cov(body, chk)["status"], "skipped")
        self.assertFalse(body["findings"])


if __name__ == "__main__":
    unittest.main()
