"""test_check.py — skill-079 decision boundaries: persistence, HEAD/bot exclusions, redirects, tracking, TLS, verify.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-079-broken-url-monitoring/tests -t skills/skill-079-broken-url-monitoring
rules:   stdlib only; temp folders; never touches the shared fixture or expected oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial tests
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check079", HERE.parent / "scripts" / "check.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check079"] = mod
_spec.loader.exec_module(mod)

URL = "https://shop.example/p?utm_source=ads&lang=it"
HC = "external/url_health_checks.csv"
DM = "external/destination_map.csv"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols or ["id"])
        w.writeheader()
        w.writerows(rows)


def _dmap(live="ACTIVE", url=URL) -> list[dict]:
    return [{"campaign_id": "c10", "entity_type": "keyword", "entity_id": "k1", "url_id": "u1",
             "final_url_sanitized": url, "association_status": live, "mobile_url_sanitized": "",
             "keyword_override": "true", "expansion_status": "none", "tracking_template_present": "false"}]


def _hc(check="h1", at="2026-09-01T10:00:00Z", method="GET", final=200, rendered="true", content="true",
        tls="false", bot="false", err="", chain="", initial=None, final_url=URL, **extra) -> dict:
    return {"url_id": "u1", "check_id": check, "checked_at": at, "method": method,
            "initial_status": final if initial is None else initial, "redirect_chain_statuses": chain,
            "final_url_sanitized": final_url, "final_status": final, "tls_error": tls, "rendered_success": rendered,
            "expected_content_present": content, "conversion_path_available": "true", "bot_challenge_observed": bot,
            "error_class": err, "source_reference": f"mon-{check}", **extra}


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def build(self, extra=None, profile=None, kw_cost=250.0, complete=True):
        tables = {
            "account.csv": [{"customer_id": "c1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                             "date_range_end": "2026-08-30", "snapshot_date": "2026-09-05",
                             "conversion_lag_days": 2, "money_unit": "currency", "rates_format": "fraction"}],
            "keywords.csv": [{"id": "k1", "campaign_id": "c10", "ad_group_id": "g1", "status": "ENABLED",
                              "final_url": URL}],
            "keyword_metrics.csv": [{"keyword_id": "k1", "clicks": 80, "cost": kw_cost}],
        }
        tables.update(extra or {})
        ex = self.root / "export"
        for name, rows in tables.items():
            _write(ex / name, rows)
        comp = "complete for declared rows and columns" if complete else "partial sample"
        _write(ex / "table_manifest.csv", [{"filename": n, "completeness": comp, "truncation": "none"} for n in tables])
        prof = self.root / "profile.json"
        prof.write_text(json.dumps(profile or {}))
        return ex, prof

    def run_check(self, extra=None, **kw) -> dict:
        ex, prof = self.build(extra, **kw)
        return mod.cli.run_once(mod.SKILL, mod.VERSION, mod.run, ex, prof).finish()

    @staticmethod
    def keys(body) -> dict:
        return {f["condition_key"]: f["severity"] for f in body["findings"]}

    @staticmethod
    def cov(body) -> dict:
        return {c["check"]: c["status"] for c in body["coverage"]}

    def cli(self, args) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return mod.cli.main(mod.SKILL, mod.VERSION, mod.run, mod.verify, args)

    # -- missing evidence
    def test_missing_health_checks_skip_every_dependent_check(self):
        body = self.run_check({DM: _dmap()})
        cov = self.cov(body)
        for c in ("redirect_render", "failure_persistence", "redirect_hops", "https_tls", "owner_review_requests"):
            self.assertEqual(cov[c], "skipped", c)
        self.assertEqual(body["findings"], [])

    def test_export_only_run_lists_urls_once_without_verdict(self):
        body = self.run_check()
        self.assertEqual(self.cov(body)["url_dedup"], "partial")
        data = [o for o in body["observations"] if o["check"] == "url_dedup"][0]["data"]
        self.assertEqual(data["distinct_urls"], 1)
        self.assertEqual(body["findings"], [])

    def test_untested_live_destination_only_with_complete_inventory(self):
        other = [{**_hc(), "url_id": "u9"}]
        self.assertEqual(self.keys(self.run_check({DM: _dmap(), HC: other})).get("untested_destination"), "Info")
        body = self.run_check({DM: _dmap(), HC: other}, complete=False)
        self.assertNotIn("untested_destination", self.keys(body))
        self.assertEqual(self.cov(body)["redirect_render"], "partial")

    # -- persistence boundaries
    def test_two_distinct_failures_are_persistent_warning_with_review(self):
        rows = [_hc("h1", final=404), _hc("h2", at="2026-09-02T10:00:00Z", final=500)]
        body = self.run_check({DM: _dmap(), HC: rows})
        self.assertEqual(self.keys(body)["persistent_destination_failure"], "Warning")
        item = [r for r in body["ai_review"] if r["condition_key"] == "persistent_destination_failure"][0]
        self.assertEqual(item["evidence"]["materiality_basis"][0][:13], "campaign c10:")

    def test_repeated_timestamp_is_not_persistence(self):
        rows = [_hc("h1", final=404), _hc("h2", final=404)]
        body = self.run_check({DM: _dmap(), HC: rows})
        self.assertEqual(self.keys(body), {"unconfirmed_single_failure": "Info"})
        self.assertEqual(self.cov(body)["failure_persistence"], "partial")

    def test_failures_with_success_are_intermittent(self):
        rows = [_hc("h1", final=503), _hc("h2", at="2026-09-02T10:00:00Z", final=503),
                _hc("h3", at="2026-09-03T10:00:00Z")]
        self.assertEqual(self.keys(self.run_check({DM: _dmap(), HC: rows})), {"intermittent_availability": "Warning"})

    def test_head_only_and_bot_failures_stay_info(self):
        rows = [_hc("h1", method="HEAD", final=405), _hc("h2", at="2026-09-02T10:00:00Z", method="HEAD", final=405)]
        self.assertEqual(self.keys(self.run_check({DM: _dmap(), HC: rows})), {"head_only_failure": "Info"})
        rows = [_hc("h1", final=403, bot="true"), _hc("h2", at="2026-09-02T10:00:00Z", final=403, err="geo_restricted")]
        self.assertEqual(self.keys(self.run_check({DM: _dmap(), HC: rows})), {"excluded_failure_class": "Info"})

    def test_soft_404_on_200_page_counts_as_failure(self):
        rows = [_hc("h1", content="false"), _hc("h2", at="2026-09-02T10:00:00Z", content="false")]
        self.assertEqual(self.keys(self.run_check({DM: _dmap(), HC: rows})),
                         {"persistent_destination_failure": "Warning"})
        rows = [_hc("h1"), _hc("h2", at="2026-09-02T10:00:00Z")]
        self.assertEqual(self.keys(self.run_check({DM: _dmap(), HC: rows})), {})

    def test_inactive_destination_has_no_critical_path(self):
        rows = [_hc("h1", final=404), _hc("h2", at="2026-09-02T10:00:00Z", final=404)]
        body = self.run_check({DM: _dmap(live="PAUSED"), HC: rows})
        self.assertEqual(self.keys(body)["persistent_destination_failure"], "Warning")
        self.assertEqual(body["ai_review"], [])

    def _finalize(self, extra, outcome, proposal, **kw) -> tuple[int, dict]:
        ex, prof = self.build(extra, **kw)
        out = self.root / "out"
        self.assertEqual(self.cli(["run", "--export", str(ex), "--profile", str(prof), "--out", str(out)]), 0)
        body = json.loads((out / "result.json").read_text())
        item = [r for r in body["ai_review"] if outcome in r["outcomes"]][0]
        dec = self.root / "d.json"
        dec.write_text(json.dumps([{"id": item["id"], "outcome": outcome, "rationale": "cited", "proposal": proposal}]))
        code = self.cli(["finalize", "--export", str(ex), "--profile", str(prof), "--out", str(out),
                         "--decisions", str(dec)])
        return code, json.loads((out / "final.json").read_text())

    def test_critical_requires_evidence_ref_and_material_exposure(self):
        rows = {DM: _dmap(), HC: [_hc("h1", final=404), _hc("h2", at="2026-09-02T10:00:00Z", final=404)]}
        code, _ = self._finalize(rows, "material_live_failure", {})
        self.assertEqual(code, 4)
        code, final = self._finalize(rows, "material_live_failure", {"evidence_ref": "mon-h2"})
        self.assertEqual(code, 0)
        self.assertEqual(self.keys(final)["persistent_destination_failure"], "Critical")
        code, _ = self._finalize(rows, "material_live_failure", {"evidence_ref": "mon-h2"}, kw_cost=50.0)
        self.assertEqual(code, 4)  # 50 < spend_material 200: no materiality basis

    # -- redirects and tracking
    def test_redirect_hops_boundary(self):
        body = self.run_check({DM: _dmap(), HC: [_hc(initial=301, chain="301>302>301>200")]})
        self.assertEqual(self.keys(body), {"destination_redirects": "Info"})
        body = self.run_check({DM: _dmap(), HC: [_hc(initial=301, chain="301>302>301>302>200")]})
        self.assertEqual(self.keys(body), {"redirect_chain_over_three_hops": "Info"})
        self.assertEqual(len(body["ai_review"]), 1)

    def test_unknown_chain_after_3xx_is_partial(self):
        body = self.run_check({DM: _dmap(), HC: [_hc(initial=301, chain="")]})
        self.assertEqual(self.cov(body)["redirect_hops"], "partial")

    def test_overhead_warning_needs_evidence_ref(self):
        rows = {DM: _dmap(), HC: [_hc(initial=301, chain="301>302>301>302>200")]}
        code, _ = self._finalize(rows, "avoidable_overhead_measured", {})
        self.assertEqual(code, 4)
        code, final = self._finalize(rows, "avoidable_overhead_measured", {"evidence_ref": "timing.har"})
        self.assertEqual(code, 0)
        self.assertEqual(self.keys(final), {"redirect_chain_over_three_hops": "Warning"})

    def test_tracking_parameter_loss_only_with_profile_keys(self):
        rows = {DM: _dmap(), HC: [_hc(initial=301, chain="301>200", final_url="https://shop.example/p?lang=it")]}
        body = self.run_check(rows)
        self.assertEqual(self.cov(body)["tracking_preservation"], "skipped")
        body = self.run_check(rows, profile={"tracking_parameters": ["utm_source"]})
        f = [x for x in body["findings"] if x["condition_key"] == "tracking_parameter_dropped"]
        self.assertEqual(f[0]["evidence"]["lost_keys"], ["utm_source"])
        kept = {DM: _dmap(), HC: [_hc(initial=301, chain="301>200", final_url="https://shop.example/p?lang=it&utm_source=ads")]}
        body = self.run_check(kept, profile={"tracking_parameters": ["utm_source"]})
        self.assertNotIn("tracking_parameter_dropped", self.keys(body))

    # -- TLS / HTTPS
    def test_tls_error_repeat_is_warning_single_is_info(self):
        body = self.run_check({DM: _dmap(), HC: [_hc("h1", tls="true", final="")]})
        self.assertEqual(self.keys(body).get("tls_problem_single"), "Info")
        body = self.run_check({DM: _dmap(), HC: [_hc("h1", tls="true", final=""),
                                                 _hc("h2", at="2026-09-02T10:00:00Z", tls="true", final="")]})
        self.assertEqual(self.keys(body).get("tls_problem"), "Warning")

    def test_https_judged_on_final_url_not_initial(self):
        dm = _dmap(url="http://shop.example/p")
        rows = [_hc("h1", final_url="https://shop.example/p"), _hc("h2", at="2026-09-02T10:00:00Z",
                                                                   final_url="https://shop.example/p")]
        self.assertNotIn("no_https_final", self.keys(self.run_check({DM: dm, HC: rows})))
        rows = [_hc("h1", final_url="http://shop.example/p"), _hc("h2", at="2026-09-02T10:00:00Z",
                                                                  final_url="http://shop.example/p")]
        self.assertEqual(self.keys(self.run_check({DM: dm, HC: rows})).get("no_https_final"), "Warning")

    # -- incidents
    def test_incident_without_allocation_is_not_quantified(self):
        inc = [{"url_id": "u1", "incident_id": "i1", "confirmed_start": "2026-08-10T00:00:00Z",
                "confirmed_end": "2026-08-10T06:00:00Z", "affected_clicks": 12, "affected_cost": 40,
                "cost_allocation_method": ""}]
        body = self.run_check({DM: _dmap(), HC: [_hc()], "external/url_incident_windows.csv": inc})
        self.assertEqual(self.cov(body)["incident_exposure"], "partial")
        data = [o for o in body["observations"] if o["check"] == "incident_exposure"][0]["data"]
        self.assertEqual(data["incidents"], [])


if __name__ == "__main__":
    unittest.main()
