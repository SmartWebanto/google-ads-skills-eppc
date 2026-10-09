"""test_check.py — Decision-boundary tests for skill-127 search-term trend screening.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-127-trending-search-term-detection/tests -t skills/skill-127-trending-search-term-detection
rules:   Temp folders only; pins growth/decline boundaries, first-reported branch, gates and verify, never wording.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_127", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

START, END = date(2026, 7, 6), date(2026, 8, 30)
CUR = END - timedelta(days=6)
# query: (prior impressions/day, current impressions/day, cost/day, first reported in current week)
SPECS = {"garden hose": (200, 400, 5, False), "step ladder": (450, 150, 20, False), "paint roller": (450, 150, 1, False),
         "tool chest": (0, 300, 5, True), "workbench": (50, 10, 1, False), "hammer": (200, 300, 5, False)}


def trend(coverage_current="full") -> str:
    out = ["campaign_id,ad_group_id,query,date,matched_keyword_id,match_type,added_or_excluded,impressions,clicks,cost,"
           "conversions,conversion_value,reporting_coverage"]
    d = START
    while d <= END:
        for q, (prior, cur, cost, first) in SPECS.items():
            if first and d < CUR:
                continue
            impr = cur if d >= CUR else prior
            raw = "Garden  Hose" if q == "garden hose" and d.day % 2 else q
            cov = coverage_current if d >= CUR else "full"
            out.append(f"C1,G1,{raw},{d},K1,BROAD,NONE,{impr},{impr // 20},{cost},0,0,{cov}")
        d += timedelta(days=1)
    return "\n".join(out) + "\n"


class Env:
    def __init__(self, files: dict, lag="2"):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "export"
        acct = ("customer_id,name,currency_code,time_zone,date_range_start,date_range_end,snapshot_date,rates_format,"
                "money_unit,conversion_date_basis,conversion_lag_days\n"
                f"1,A,EUR,Europe/Rome,{START},{END},2026-09-02,fraction,currency,interaction_date,{lag}\n")
        files = {"account.csv": acct, "campaigns.csv": "id,name,status\nC1,a,ENABLED\n",
                 "ad_groups.csv": "id,campaign_id,status\nG1,C1,ENABLED\n",
                 "keywords.csv": "id,campaign_id,ad_group_id,text,match_type,status\nK1,C1,G1,garden hose,PHRASE,ENABLED\n",
                 "negative_keywords.csv": "text,match_type,level,campaign_id,ad_group_id\nladder,PHRASE,campaign,C1,\n",
                 "shared_negative_lists.csv": "list_id,name,member_count,keywords,campaigns_applied\n", **files}
        manifest = ["filename,completeness"]
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            manifest.append(f"{name},complete")
        (self.root / "table_manifest.csv").write_text("\n".join(manifest) + "\n")
        self.profile = Path(self.tmp.name) / "profile.yaml"
        self.profile.write_text("slug: t\n")
        self.out = Path(self.tmp.name) / "out"

    def body(self):
        return cli.run_once(M.SKILL, M.VERSION, M.run, self.root, self.profile).finish()

    def cli(self, cmd, decisions=None):
        argv = [cmd, "--export", str(self.root), "--profile", str(self.profile), "--out", str(self.out)]
        if decisions is not None:
            p = Path(self.tmp.name) / "d.json"
            p.write_text(json.dumps(decisions))
            argv += ["--decisions", str(p)]
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify, argv=argv)


def body(files, **kw):
    env = Env(files, **kw)
    try:
        return env.body()
    finally:
        env.tmp.cleanup()


def by_key(b, items="findings"):
    out = {}
    for f in b[items]:
        out.setdefault(f["condition_key"], []).append(f["entity"].get("query"))
    return {k: sorted(v) for k, v in out.items()}


CHANGES = ("campaign_id,change_id,occurred_at,changed_field,old_value,new_value,source\n"
           "C1,CH1,2026-08-24,budget,100,40,change history\n")


class Trends(unittest.TestCase):
    def test_branches_and_boundaries(self):
        b = body({"custom/search_trend_daily.csv": trend(), "custom/search_trend_changes.csv": CHANGES})
        keys = by_key(b)
        self.assertEqual(keys["query_growth"], ["garden hose"])  # hammer is exactly +50%: not flagged
        self.assertEqual(keys["first_reported_term"], ["tool chest"])
        self.assertEqual(keys["query_decline"], ["paint roller", "step ladder"])  # workbench below min_impressions
        self.assertEqual(by_key(b, "ai_review"), {"query_decline": ["step ladder"]})  # paint roller immaterial
        growth = next(f for f in b["findings"] if f["condition_key"] == "query_growth")
        self.assertEqual(len(growth["evidence"]["raw_queries"]), 2)
        self.assertTrue(growth["evidence"]["existing_coverage"]["literal_keyword_coverage"])
        self.assertFalse([f for f in b["findings"] if f["severity"] != "Info"])

    def test_changed_coverage_and_unknown_lag_block_decline_review(self):
        b = body({"custom/search_trend_daily.csv": trend(coverage_current="partial")})
        self.assertEqual(b["ai_review"], [])
        self.assertIn("reporting_coverage_changed", by_key(b))
        b = body({"custom/search_trend_daily.csv": trend()}, lag="")
        self.assertEqual(b["ai_review"], [])

    def test_serving_risk_must_cite_listed_change_or_negative(self):
        env = Env({"custom/search_trend_daily.csv": trend(), "custom/search_trend_changes.csv": CHANGES})
        self.addCleanup(env.tmp.cleanup)
        env.cli("run")
        res = json.loads((env.out / "result.json").read_text())
        item = res["ai_review"][0]
        self.assertTrue(item["evidence"]["existing_coverage"]["blocking_negatives"])
        base = {"id": item["id"], "outcome": "serving_risk_identified", "rationale": "x"}
        self.assertEqual(env.cli("finalize", [{**base, "proposal": {"change_id": "NOPE"}}]), 4)
        self.assertEqual(env.cli("finalize", [{**base, "proposal": {"change_id": "CH1"}}]), 0)
        final = json.loads((env.out / "final.json").read_text())
        self.assertEqual([f["severity"] for f in final["findings"] if f["condition_key"] == "query_decline"
                          and f["entity"]["query"] == "step ladder"], ["Warning"])

    def test_missing_trend_file_skips(self):
        b = body({})
        self.assertEqual({c["status"] for c in b["coverage"]}, {"skipped"})


if __name__ == "__main__":
    unittest.main()
