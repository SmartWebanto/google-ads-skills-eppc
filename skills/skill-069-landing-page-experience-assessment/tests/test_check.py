"""test_check.py — Decision-boundary tests for skill-069 landing-page experience triage.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-069-landing-page-experience-assessment/tests -t skills/skill-069-landing-page-experience-assessment
rules:   Temp folders only; pins severities, attribution invariants, coverage and verify() gates, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial tests
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_069", _PATH)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(c for r in rows for c in r))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _kw(kid, rating, cost, override=""):
    return ({"id": kid, "campaign_id": "C1", "ad_group_id": "G1", "text": f"kw {kid}", "status": "ENABLED",
             "landing_page_experience": rating, "final_url": override},
            {"keyword_id": kid, "campaign_id": "C1", "ad_group_id": "G1", "clicks": 100, "cost": cost})


def _ad(aid, url, status="ENABLED"):
    return {"id": aid, "campaign_id": "C1", "ad_group_id": "G1", "status": status, "approval_status": "APPROVED",
            "final_url": url}


def _url_row(url, clicks, cost, conv, source="landing_page_view"):
    return {"campaign_id": "C1", "date": "2026-08-10", "landing_page_url": url, "expanded_url": "", "device": "",
            "impressions": 5000, "clicks": clicks, "cost": cost, "conversions": conv, "conversion_value": conv * 50,
            "source": source}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def build(self, kws, ads=(), lag="2", urls=None, checks=None, verified=True, spend_high=500):
        root = self.dir / "export"
        _write(root / "account.csv", [{"customer_id": "1", "currency_code": "EUR", "time_zone": "Europe/Rome",
                                       "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
                                       "snapshot_date": "2026-09-06", "rates_format": "fraction",
                                       "money_unit": "currency", "conversion_lag_days": lag}])
        _write(root / "campaigns.csv", [{"id": "C1", "channel_type": "SEARCH", "goal_ids": "purchase"}])
        _write(root / "keywords.csv", [k for k, _ in kws])
        _write(root / "keyword_metrics.csv", [m for _, m in kws])
        _write(root / "ads.csv", list(ads) or [_ad("A0", "https://x.example/a", status="PAUSED")])
        files = ["keywords.csv", "keyword_metrics.csv", "ads.csv"]
        if urls:
            _write(root / "custom" / "landing_url_performance.csv", urls)
            files.append("custom/landing_url_performance.csv")
        if checks:
            _write(root / "external" / "landing_page_checks.csv", checks)
            files.append("external/landing_page_checks.csv")
        _write(root / "table_manifest.csv", [{"filename": f, "completeness": "complete", "truncation": "none"}
                                             for f in files])
        prof = {"parameter_overrides": {"spend_high": spend_high}}
        if verified:
            prof["tracking_verified"] = {"purchase": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30",
                                                      "source_ref": "qa-1"}}
        self.profile = self.dir / "profile.json"
        self.profile.write_text(json.dumps(prof))
        self.root = root
        return cli.run_once(M.SKILL, M.VERSION, M.run, root, self.profile).finish()

    @staticmethod
    def found(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def status(body, check):
        return next(c["status"] for c in body["coverage"] if c["check"] == check)

    @staticmethod
    def obs(body, check):
        return [o for o in body["observations"] if o["check"] == check]


class Rating(Base):
    def test_below_average_at_spend_high_is_warning_else_low_exposure_info(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 500), _kw("K2", "BELOW_AVERAGE", 10), _kw("K3", "AVERAGE", 9000)])
        self.assertEqual([f["entity"]["keyword_id"] for f in self.found(body, "below_average_lp_high_cost")], ["K1"])
        self.assertEqual([f["severity"] for f in self.found(body, "low_exposure_lp_diagnostic")], ["Info"])

    def test_missing_rating_column_skips_inventory(self):
        kws = [_kw("K1", "BELOW_AVERAGE", 900)]
        del kws[0][0]["landing_page_experience"]
        body = self.build(kws)
        self.assertEqual(self.status(body, "lp_rating_inventory"), "skipped")
        self.assertEqual(body["findings"], [])


class Routing(Base):
    def test_multiple_ad_urls_keep_cost_once_under_ambiguous_set(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 300)],
                          ads=(_ad("A1", "https://x.example/a"), _ad("A2", "https://x.example/b")))
        dests = {o["data"]["destination"]: o["data"]["keyword_cost"] for o in self.obs(body, "route_resolution")
                 if "destination" in o["data"]}
        self.assertEqual(list(dests.values()), [300])
        self.assertTrue(next(iter(dests)).startswith("AMBIGUOUS"))
        self.assertEqual(len(self.found(body, "ambiguous_routing")), 1)

    def test_keyword_override_is_single_destination(self):
        body = self.build([_kw("K1", "BELOW_AVERAGE", 300, override="https://X.example/p#frag")],
                          ads=(_ad("A1", "https://x.example/a"), _ad("A2", "https://x.example/b")))
        self.assertEqual(self.found(body, "ambiguous_routing"), [])
        dests = [o["data"]["destination"] for o in self.obs(body, "route_resolution") if "destination" in o["data"]]
        self.assertEqual(dests, ["https://x.example/p"])


class UrlReport(Base):
    def test_expanded_and_unexpanded_rows_are_not_summed(self):
        urls = [_url_row("https://x.example/a", 200, 100, 5), _url_row("https://x.example/a", 200, 100, 5, "expanded")]
        body = self.build([_kw("K1", "AVERAGE", 1)], urls=urls)
        costs = [o["data"]["cost"] for o in self.obs(body, "url_performance") if "landing_page_url" in o["data"]]
        self.assertEqual(costs, [100])
        self.assertEqual(self.status(body, "url_performance"), "partial")

    def zero_conv(self, **kw):
        urls = [_url_row("https://x.example/dead", 150, 120, 0), _url_row("https://x.example/ok", 300, 200, 12)]
        return self.build([_kw("K1", "AVERAGE", 1)], urls=urls, **kw)

    def test_zero_conversion_page_is_info_when_gated(self):
        f = self.found(self.zero_conv(), "zero_conversion_landing_page")
        self.assertEqual([(x["severity"], x["entity"]["landing_page_url"]) for x in f],
                         [("Info", "https://x.example/dead")])

    def test_zero_conversion_needs_maturity_and_tracking(self):
        body = self.zero_conv(lag="30")
        self.assertEqual(self.found(body, "zero_conversion_landing_page"), [])
        self.assertEqual(self.status(body, "url_performance"), "partial")
        body = self.zero_conv(verified=False)
        self.assertEqual(self.found(body, "zero_conversion_landing_page"), [])
        self.assertEqual(self.status(body, "url_performance"), "partial")


class PageChecks(Base):
    def check_row(self, at, code, err=""):
        return {"requested_url": "https://x.example/a", "final_url": "https://x.example/a", "checked_at": at,
                "source": "browser", "status_code": code, "access_error": err, "method": "GET",
                "mobile_usability_observation": "", "content_excerpt": ""}

    def run_checks(self, rows):
        return self.build([_kw("K1", "BELOW_AVERAGE", 300)], ads=(_ad("A1", "https://x.example/a"),), checks=rows)

    def test_reproduced_failure_is_warning_with_critical_review(self):
        body = self.run_checks([self.check_row("2026-09-01T10:00", 404), self.check_row("2026-09-02T10:00", 404)])
        self.assertEqual([f["severity"] for f in self.found(body, "inaccessible_destination")], ["Warning"])
        self.assertIn("Critical", {o["severity"] for o in body["ai_review"][0]["outcomes"].values()})

    def test_later_success_or_single_failure_is_not_warning(self):
        body = self.run_checks([self.check_row("2026-09-01T10:00", 404), self.check_row("2026-09-02T10:00", 404),
                                self.check_row("2026-09-03T10:00", 200)])
        self.assertEqual([f for f in body["findings"] if "inaccessible" in f["condition_key"]], [])
        body = self.run_checks([self.check_row("2026-09-01T10:00", 500)])
        self.assertEqual([f["severity"] for f in self.found(body, "inaccessible_destination_unreproduced")], ["Info"])

    def finalize(self, outcome, proposal):
        rows = [self.check_row("2026-09-01T10:00", 404), self.check_row("2026-09-02T10:00", 404)]
        body = self.run_checks(rows)
        out = self.dir / "out"
        args = ["--export", str(self.root), "--profile", str(self.profile), "--out", str(out)]
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", *args])
        dec = self.dir / "d.json"
        dec.write_text(json.dumps([{"id": body["ai_review"][0]["id"], "outcome": outcome, "rationale": "r",
                                    "proposal": proposal}]))
        with redirect_stdout(io.StringIO()):
            code = cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["finalize", *args, "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_critical_requires_evidence_ref(self):
        code, final = self.finalize("material_failure_evidenced", {})
        self.assertEqual(code, 4)
        self.assertEqual(final["counts"]["Critical"], 0)
        code, final = self.finalize("material_failure_evidenced", {"evidence_ref": "incident-7"})
        self.assertEqual(code, 0)
        self.assertEqual(final["counts"]["Critical"], 1)


if __name__ == "__main__":
    unittest.main()
