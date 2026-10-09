"""test_check.py — skill-057 joint day×hour efficiency, alignment, eligibility and proposal boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-057-ad-schedule-optimization/tests
rules:   stdlib only; temp folders; no network; asserts decisions, not wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial tests
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
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_057", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

TZ = "Europe/Rome"
ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "time_zone": TZ, "date_range_start": "2026-08-03",
           "date_range_end": "2026-08-30", "snapshot_date": "2026-09-05", "money_unit": "currency",
           "conversion_lag_days": "2"}
TRACKED = {"campaign_objectives": {"10": {"goal_ids": ["g1"]}},
           "tracking_verified": {"g1": {"status": "verified", "verified_from": "2000-01-01", "verified_through": "2026-08-30", "source_ref": "qa"}}}
DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Env:
    def __init__(self, test, tables, profile=None, account=None, strategy="MANUAL_CPC", channel="SEARCH"):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exp = self.root / "export"
        tables = {"account": [account or ACCOUNT],
                  "campaigns": [{"id": "10", "status": "ENABLED", "channel_type": channel,
                                 "bidding_strategy_type": strategy}], **tables}
        for key, rows in tables.items():
            _write(self.exp / f"{key}.csv", rows)
        _write(self.exp / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        (self.root / "profile.json").write_text(json.dumps(profile or {"event_calendar": []}))

    def cli(self, cmd, *extra) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                            [cmd, "--export", str(self.exp), "--profile", str(self.root / "profile.json"),
                             "--out", str(self.root / "out"), *extra])

    def run(self) -> dict:
        assert self.cli("run") == 0
        return json.loads((self.root / "out" / "result.json").read_text())


def dh(start="2026-08-03", days=28, spec=None, tz=TZ):
    """spec(date, hour) -> (cost, conv, clicks) or None; hours 0..23."""
    rows, d0 = [], date.fromisoformat(start)
    for i in range(days):
        d = d0 + timedelta(days=i)
        for h in range(24):
            v = spec(d, h)
            if v:
                rows.append({"campaign_id": "10", "date": d.isoformat(), "day_of_week": DAYS[d.weekday()], "hour": h,
                             "impressions": 100, "clicks": v[2], "cost": v[0], "conversions": v[1],
                             "conversion_value": v[1] * 30, "timezone": tz, "source": "report"})
    return rows


def hour_spec(d, h):
    return {9: (20, 2, 10), 20: (60, 1, 10)}.get(h)


def sunday_spec(d, h):
    if h != 9:
        return None
    return (100, 4, 30) if d.weekday() == 6 else (20, 4, 10)


def all_day(modifier=1.0, days=range(7), start=0, end=24):
    return [{"campaign_id": "10", "schedule_id": f"s{d}", "effective_start": "2026-01-01", "effective_end": "",
             "day_of_week": DAYS[d], "start_hour": start, "start_minute": 0, "end_hour": end, "end_minute": 0,
             "bid_modifier": modifier, "timezone": TZ, "source": "settings"} for d in days]


def conds(body, sev=None):
    return sorted((f["condition_key"], f["entity"].get("grain"), f["entity"].get("hour"), f["entity"].get("day_of_week"))
                  for f in body["findings"] if sev is None or f["severity"] == sev)


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class AdScheduleTests(unittest.TestCase):
    def test_hour_marginal_efficiency_from_joint_table(self):
        body = Env(self, {"custom/day_hour_performance": dh(spec=hour_spec)}).run()
        self.assertEqual(conds(body, "Warning"), [("adverse_time_window", "hour", 20, None)])
        self.assertIn(("opportunity_time_window", "hour", 9, None), conds(body, "Info"))
        self.assertIn(("sparse_time_windows", None, None, None), conds(body, "Info"))

    def test_fewer_than_four_complete_weeks_blocks_severity(self):
        acct = dict(ACCOUNT, date_range_end="2026-08-29", snapshot_date="2026-09-05")  # 27 days → 3 complete weeks
        body = Env(self, {"custom/day_hour_performance": dh(days=27, spec=hour_spec)}, account=acct).run()
        self.assertEqual(conds(body, "Warning"), [])
        self.assertEqual(cov(body)["efficiency"], "partial")

    def test_misaligned_rows_are_excluded(self):
        body = Env(self, {"custom/day_hour_performance": dh(spec=hour_spec, tz="UTC")}).run()
        self.assertEqual(body["findings"], [])
        self.assertEqual(cov(body)["time_alignment"], "partial")
        rows = dh(spec=hour_spec)
        for r in rows:
            r["day_of_week"] = "MONDAY"
        body = Env(self, {"custom/day_hour_performance": rows}).run()
        self.assertEqual(conds(body, "Warning"), [])

    def test_immature_window_descriptive_only(self):
        body = Env(self, {"custom/day_hour_performance": dh(spec=hour_spec)},
                   account=dict(ACCOUNT, snapshot_date="2026-08-31")).run()
        self.assertEqual(conds(body, "Warning"), [])
        self.assertEqual(cov(body)["efficiency"], "partial")

    def test_bounded_proposal_by_strategy_and_channel(self):
        t = {"custom/day_hour_performance": dh(spec=sunday_spec), "custom/schedule_history": all_day(1.0)}
        body = Env(self, t).run()
        f = next(f for f in body["findings"] if f["condition_key"] == "adverse_time_window")
        self.assertEqual(f["entity"]["day_of_week"], "SUNDAY")
        self.assertEqual((f["evidence"]["proposal"]["type"], f["evidence"]["proposal"]["proposed_modifier"]),
                         ("bounded_bid_test", 0.9))
        f = next(f for f in Env(self, t, strategy="TARGET_CPA").run()["findings"] if f["condition_key"] == "adverse_time_window")
        self.assertEqual(f["evidence"]["proposal"]["type"], "none")
        f = next(f for f in Env(self, t, strategy="MAXIMIZE_CONVERSION_VALUE", channel="PERFORMANCE_MAX").run()["findings"]
                 if f["condition_key"] == "adverse_time_window")
        self.assertEqual(f["evidence"]["proposal"]["type"], "eligibility_test_only")

    def test_zero_conversion_window_needs_tracking(self):
        spec = lambda d, h: {9: (20, 2, 10), 23: (15, 0, 2)}.get(h)  # hour 23: 420 EUR, each dow cell 60 EUR
        body = Env(self, {"custom/day_hour_performance": dh(spec=spec)}).run()
        self.assertEqual(body["ai_review"], [])
        self.assertEqual(cov(body)["zero_conversion"], "partial")
        body = Env(self, {"custom/day_hour_performance": dh(spec=spec)}, profile=TRACKED).run()
        keys = sorted((r["entity"]["grain"], r["entity"]["hour"]) for r in body["ai_review"])
        self.assertEqual(keys, [("hour", 23)])  # cells inside the flagged marginal are not re-flagged

    def test_excluded_hours_are_info_not_zero(self):
        t = {"custom/day_hour_performance": dh(spec=hour_spec),
             "custom/schedule_history": all_day(1.0, days=range(5), start=8, end=21)}
        body = Env(self, t).run()
        ex = next(f for f in body["findings"] if f["condition_key"] == "excluded_hours")
        self.assertEqual(ex["severity"], "Info")
        self.assertIn("SATURDAY 09h", ex["evidence"]["excluded_slots"])
        self.assertEqual(cov(body)["eligibility_states"], "partial")  # weekend traffic in excluded slots

    def test_business_hours_review_and_verify(self):
        bh = [{"campaign_id": "10", "day_of_week": DAYS[d], "opens_at": "09:00", "closes_at": "18:00", "timezone": TZ,
               "after_hours_handling": "none", "valid_from": "2026-01-01", "valid_to": "", "owner_source": "owner"}
              for d in range(5)]
        env = Env(self, {"custom/schedule_history": all_day(1.0), "external/business_hours": bh})
        body = env.run()
        item = next(r for r in body["ai_review"] if r["condition_key"] == "schedule_contradicts_service_hours")
        self.assertIn("SUNDAY 03h", item["evidence"]["eligible_while_closed"])
        dec = env.root / "d.json"
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "contradicts_requirement", "rationale": "r",
                                    "proposal": {"slots": ["MONDAY 10h"], "action": "exclude"}}]))
        self.assertEqual(env.cli("finalize", "--decisions", str(dec)), 4)  # open slot, not a contradiction
        dec.write_text(json.dumps([{"id": item["id"], "outcome": "contradicts_requirement", "rationale": "r",
                                    "proposal": {"slots": ["SUNDAY 03h"], "action": "exclude"}}]))
        self.assertEqual(env.cli("finalize", "--decisions", str(dec)), 0)

    def test_dst_transition_dates_excluded(self):
        acct = dict(ACCOUNT, date_range_start="2026-10-19", date_range_end="2026-11-15", snapshot_date="2026-11-20")
        body = Env(self, {"custom/day_hour_performance": dh(start="2026-10-19", spec=hour_spec)}, account=acct).run()
        obs = next(o for o in body["observations"] if o["check"] == "time_alignment")["data"]
        self.assertEqual(obs["dst_dates"], ["2026-10-25"])
        self.assertEqual(obs["excluded"]["dst"], 2)


if __name__ == "__main__":
    unittest.main()
