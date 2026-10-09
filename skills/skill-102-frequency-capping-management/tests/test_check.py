"""test_check.py — skill-102 boundaries: dedup/average precedence, distributions, approved bounds, fatigue gates.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-102-frequency-capping-management/tests
rules:   stdlib only; temp folders; never read the self-test oracle.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | tests for this session's check changes
"""
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_102", _CHECK)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402


def _write(root: Path, key: str, rows: list[dict]) -> None:
    p = root / f"{key}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _expo(bucket, impressions="", users="", reach="", avg="", dedup="campaign"):
    return {"campaign_id": "10", "report_start": "2026-08-03", "report_end": "2026-08-09", "population_scope": "all",
            "reported_frequency_bucket": bucket, "impressions": impressions, "unique_users": users,
            "average_impression_frequency": avg, "reach_by_bucket": reach, "report_definition": "reach report",
            "deduplication_scope": dedup, "modeled_status": "modeled", "privacy_flags": "", "report_source": "ui"}


def _out(bucket, clicks, conv, goal="G1"):
    return {"campaign_id": "10", "report_start": "2026-08-03", "report_end": "2026-08-09", "population_scope": "all",
            "reported_frequency_bucket": bucket, "exposed_people": "", "clicks": clicks, "cost": "", "conversions": conv,
            "conversion_value": "", "goal_set_id": goal, "attribution_definition": "dda", "coverage": "full"}


def base_tables() -> dict:
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-10", "conversion_lag_days": "3"}],
        "campaigns": [{"id": "10", "channel_type": "DISPLAY"}, {"id": "20", "channel_type": "PERFORMANCE_MAX"}],
        "external/frequency_controls": [
            {"campaign_id": "10", "control_id": "k1", "cap_status": "explicit", "event_type": "impression",
             "entity_level": "campaign", "maximum_count": "5", "period": "week",
             "supported_controls": "frequency cap;target frequency"}],
        "custom/frequency_exposure": [_expo("total", "40000", "10000"), _expo("1", reach="4000"),
                                      _expo("2-3", reach="4000"), _expo("4+", reach="2000")],
        "external/frequency_plan": [{"campaign_id": "10", "exposure_objective": "consideration",
                                     "approved_min_frequency": "2", "approved_max_frequency": "6",
                                     "bound_window_days": "7", "fatigue_evidence_reference": "", "owner": "brand",
                                     "creative_rotation": "weekly"}],
        "custom/frequency_outcomes": [_out("1", "400", "20"), _out("2-3", "300", "12"), _out("4+", "200", "4")],
    }


class CheckTests(unittest.TestCase):
    def build(self, tables: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "export"
        for key, rows in tables.items():
            _write(root, key, rows)
        _write(root, "table_manifest", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        return root

    def run_check(self, tables: dict) -> dict:
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.build(tables), None).finish()

    @staticmethod
    def keys(body, key):
        return [f for f in body["findings"] if f["condition_key"] == key]

    @staticmethod
    def obs(body, prefix):
        return next(o for o in body["observations"] if o["text"].startswith(prefix))

    def test_within_bounds_no_warning(self):
        body = self.run_check(base_tables())
        self.assertFalse([f for f in body["findings"] if f["severity"] == "Warning"])
        self.assertEqual(self.obs(body, "Campaign 10: delivered")["data"]["measured_frequency"], 4.0)

    def test_platform_average_wins_and_breach_warns(self):
        t = base_tables()
        t["custom/frequency_exposure"][0]["average_impression_frequency"] = "7.5"
        f = self.keys(self.run_check(t), "exposure_above_approved_bound")
        self.assertEqual([x["severity"] for x in f], ["Warning"])
        self.assertEqual(f[0]["evidence"]["measured_frequency"], 7.5)

    def test_below_min_warns(self):
        t = base_tables()
        t["custom/frequency_exposure"][0]["impressions"] = "15000"
        self.assertEqual(len(self.keys(self.run_check(t), "exposure_below_approved_bound")), 1)

    def test_window_length_mismatch_is_not_compared(self):
        t = base_tables()
        t["custom/frequency_exposure"][0]["average_impression_frequency"] = "30"
        t["external/frequency_plan"][0]["bound_window_days"] = "28"
        body = self.run_check(t)
        self.assertFalse(self.keys(body, "exposure_above_approved_bound"))
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "exposure_vs_plan")["status"], "partial")

    def test_cross_campaign_dedup_and_zero_users_give_no_ratio(self):
        t = base_tables()
        t["custom/frequency_exposure"][0]["deduplication_scope"] = "daily"
        body = self.run_check(t)
        self.assertFalse([o for o in body["observations"] if o["text"].startswith("Campaign 10: delivered")])
        t = base_tables()
        t["custom/frequency_exposure"][0]["unique_users"] = "0"
        body = self.run_check(t)
        self.assertIsNone(self.obs(body, "Campaign 10: delivered")["data"]["measured_frequency"])
        self.assertFalse(self.keys(body, "exposure_below_approved_bound"))

    def test_distribution_nonoverlapping_and_cumulative(self):
        body = self.run_check(base_tables())
        d = self.obs(body, "Campaign 10: exposure distribution")["data"]
        self.assertEqual((d["kind"], d["shares"]["4+"]), ("non-overlapping", 0.2))
        t = base_tables()
        t["custom/frequency_exposure"][1:] = [_expo("1+", reach="10000"), _expo("2+", reach="6000"),
                                             _expo("4+", reach="2000")]
        d = self.obs(self.run_check(t), "Campaign 10: exposure distribution")["data"]
        self.assertEqual((d["kind"], d["shares"]["2+"]), ("cumulative", 0.6))

    def test_fatigue_hypothesis_is_review_not_finding(self):
        body = self.run_check(base_tables())
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["fatigue_hypothesis"])
        self.assertFalse(self.keys(body, "fatigue_hypothesis"))
        self.assertEqual(len(self.keys(body, "bounded_exposure_test_opportunity")), 1)

    def test_fatigue_needs_min_clicks_on_both_sides(self):
        t = base_tables()
        t["custom/frequency_outcomes"] = [_out("1", "400", "20"), _out("4+", "50", "0")]
        self.assertFalse(self.run_check(t)["ai_review"])

    def test_fatigue_needs_maturity(self):
        t = base_tables()
        t["account"][0]["snapshot_date"] = "2026-08-31"
        body = self.run_check(t)
        self.assertFalse(body["ai_review"])
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "fatigue_screen")["status"], "partial")

    def test_missing_exposure_skips_delivery(self):
        t = base_tables()
        del t["custom/frequency_exposure"]
        body = self.run_check(t)
        self.assertEqual(next(c for c in body["coverage"] if c["check"] == "delivered_frequency")["status"],
                         "skipped")
        self.assertNotEqual(next(c for c in body["coverage"] if c["check"] == "exposure_vs_plan")["status"],
                            "completed")

    def test_finalize_corroborated_fatigue_needs_campaign_plan_evidence(self):
        t = base_tables()
        t["external/frequency_plan"][0]["fatigue_evidence_reference"] = "creative-survey-3"
        t["external/frequency_plan"].append({**t["external/frequency_plan"][0], "campaign_id": "20",
                                             "fatigue_evidence_reference": "pmax-survey-9"})
        root = self.build(t)
        out = root.parent / "out"
        with redirect_stdout(io.StringIO()):
            cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run", "--export", str(root), "--out", str(out)])
        item = json.loads((out / "result.json").read_text())["ai_review"][0]
        dec = root.parent / "d.json"
        args = ["finalize", "--export", str(root), "--out", str(out), "--decisions", str(dec)]

        def fin(proposal):
            dec.write_text(json.dumps([{"id": item["id"], "outcome": "corroborated_fatigue", "rationale": "r",
                                        "proposal": proposal}]))
            with redirect_stdout(io.StringIO()):
                return cli.main(M.SKILL, M.VERSION, M.run, M.verify, args)

        self.assertEqual(fin({}), 4)
        self.assertEqual(fin({"evidence_ref": "made-up"}), 4)
        self.assertEqual(fin({"evidence_ref": "pmax-survey-9"}), 4)
        self.assertEqual(fin({"evidence_ref": "creative-survey-3"}), 0)


if __name__ == "__main__":
    unittest.main()
