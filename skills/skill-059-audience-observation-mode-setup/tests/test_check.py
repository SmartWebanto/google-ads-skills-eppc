"""test_check.py — skill-059 audience mode vs owner intent decision boundaries.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-059-audience-observation-mode-setup/tests
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
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_059", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)
from adsrun import cli  # noqa: E402

ACCOUNT = {"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01", "date_range_end": "2026-08-28",
           "snapshot_date": "2026-09-05", "money_unit": "currency", "conversion_lag_days": "2"}
AUD_COLS = ["list_id", "campaign_id", "ad_group_id", "mode", "status", "eligible"]


def _write(path: Path, rows: list[dict], cols=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(cols or [])
    for r in rows:
        cols += [c for c in r if c not in cols]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Env:
    def __init__(self, test, assoc, profile=None, channel="SEARCH", strategy="MANUAL_CPC", aud_cols=AUD_COLS):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exp = self.root / "export"
        tables = {"account": [ACCOUNT],
                  "campaigns": [{"id": "10", "status": "ENABLED", "channel_type": channel, "bidding_strategy_type": strategy}],
                  "ad_groups": [{"id": "20", "campaign_id": "10", "status": "ENABLED"},
                                {"id": "21", "campaign_id": "10", "status": "ENABLED"}],
                  "campaign_metrics": [{"campaign_id": "10", "impressions": 10, "cost": 300}],
                  "audiences": [{k: v for k, v in zip(AUD_COLS, a) if k in aud_cols} for a in assoc]}
        for key, rows in tables.items():
            _write(self.exp / f"{key}.csv", rows, aud_cols if key == "audiences" else None)
        _write(self.exp / "table_manifest.csv", [{"filename": f"{k}.csv", "completeness": "complete"} for k in tables])
        (self.root / "profile.json").write_text(json.dumps(profile or {}))

    def cli(self, cmd, *extra) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                            [cmd, "--export", str(self.exp), "--profile", str(self.root / "profile.json"),
                             "--out", str(self.root / "out"), *extra])

    def run(self) -> dict:
        assert self.cli("run") == 0
        return json.loads((self.root / "out" / "result.json").read_text())


def intent(mode=None, role=None):
    obj = {k: v for k, v in (("audience_mode", mode), ("role", role)) if v}
    return {"campaign_objectives": {"10": obj}}


def conds(body, sev=None):
    return sorted(f["condition_key"] for f in body["findings"] if sev is None or f["severity"] == sev)


def cov(body):
    return {c["check"]: c["status"] for c in body["coverage"]}


class AudienceModeTests(unittest.TestCase):
    def test_explicit_intent_conflict_vs_match(self):
        body = Env(self, [("L1", "10", "", "TARGETING", "ENABLED", "true")], intent("observation")).run()
        self.assertEqual(conds(body, "Warning"), ["mode_conflicts_owner_intent"])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["unintended_restriction_delivery_failure"])
        body = Env(self, [("L1", "10", "", "OBSERVATION", "ENABLED", "true")], intent("observation")).run()
        self.assertEqual(conds(body), [])

    def test_ad_group_override_and_inheritance(self):
        # ad group 20 overrides with OBSERVATION; ad group 21 inherits campaign TARGETING → still a conflict
        assoc = [("L1", "10", "", "TARGETING", "ENABLED", ""), ("L2", "10", "20", "OBSERVATION", "ENABLED", "")]
        body = Env(self, assoc, intent("observation")).run()
        self.assertEqual(conds(body, "Warning"), ["mode_conflicts_owner_intent"])
        eff = next(o for o in body["observations"] if o["check"] == "effective_mode")["data"]["per_ad_group"]
        self.assertEqual(eff["20"], {"level": "ad_group", "modes": ["OBSERVATION"]})
        self.assertEqual(eff["21"], {"level": "campaign", "modes": ["TARGETING"]})

    def test_pmax_signal_never_mode_conflict(self):
        body = Env(self, [("L1", "10", "", "TARGETING", "ENABLED", "")], intent("observation"),
                   channel="PERFORMANCE_MAX").run()
        self.assertEqual(conds(body), [])
        self.assertEqual(body["ai_review"], [])

    def test_role_only_goes_to_review_and_missing_intent_is_partial(self):
        body = Env(self, [("L1", "10", "", "TARGETING", "ENABLED", "")], intent(role="acquisition")).run()
        self.assertEqual(conds(body), [])
        self.assertEqual([r["condition_key"] for r in body["ai_review"]], ["targeting_vs_role"])
        body = Env(self, [("L1", "10", "", "TARGETING", "ENABLED", "")]).run()
        self.assertEqual(conds(body), [])
        self.assertEqual(cov(body)["intent_match"], "partial")

    def test_missing_mode_column_skips(self):
        body = Env(self, [("L1", "10", "", "TARGETING", "ENABLED", "")],
                   aud_cols=["list_id", "campaign_id", "ad_group_id"]).run()
        self.assertEqual(cov(body)["association_universe"], "skipped")
        self.assertEqual(conds(body), [])

    def test_optional_segment_requires_documented_case_and_eligibility(self):
        prof = {"audience_use_cases": [{"campaign_id": "10", "list_id": "L9", "question": "repeat buyer CVR"}]}
        body = Env(self, [("L9", "99", "", "OBSERVATION", "ENABLED", "true")], prof).run()
        self.assertEqual(conds(body, "Info"), ["optional_measurement_segment"])
        body = Env(self, [("L9", "99", "", "OBSERVATION", "ENABLED", "")], prof).run()
        self.assertEqual(conds(body), [])
        self.assertEqual(cov(body)["optional_segments"], "partial")
        body = Env(self, [("L9", "99", "", "OBSERVATION", "ENABLED", "true")]).run()
        self.assertEqual(conds(body), [])

    def test_finalize_role_conflict_proposal_verified(self):
        env = Env(self, [("L1", "10", "", "TARGETING", "ENABLED", "")], intent(role="acquisition"),
                  strategy="TARGET_CPA")
        rid = env.run()["ai_review"][0]["id"]
        dec = env.root / "d.json"
        bad = {"campaign_id": "10", "proposed_mode": "OBSERVATION", "bid_modifier": 1.2}
        dec.write_text(json.dumps([{"id": rid, "outcome": "conflicts_with_intent", "rationale": "r", "proposal": bad}]))
        self.assertEqual(env.cli("finalize", "--decisions", str(dec)), 4)
        good = {"campaign_id": "10", "proposed_mode": "OBSERVATION"}
        dec.write_text(json.dumps([{"id": rid, "outcome": "conflicts_with_intent", "rationale": "r", "proposal": good}]))
        self.assertEqual(env.cli("finalize", "--decisions", str(dec)), 0)
        self.assertEqual(conds(json.loads((env.root / "out" / "final.json").read_text()), "Warning"), ["targeting_vs_role"])


if __name__ == "__main__":
    unittest.main()
