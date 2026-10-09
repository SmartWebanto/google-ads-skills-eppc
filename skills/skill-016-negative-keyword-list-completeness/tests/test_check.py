"""test_check.py — Decision-boundary tests for skill-016 negative coverage governance.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-016-negative-keyword-list-completeness/tests
rules:   Temp folders only; stdlib only; no wording assertions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx059 | negative_upload_validation tests (index #59)
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime_b | incomplete ad-group inventory regressions
"""
import contextlib
import csv
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
_spec = importlib.util.spec_from_file_location("check_016", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

NEG_COLS = ["text", "match_type", "level", "campaign_id", "ad_group_id"]
LIST_COLS = ["list_id", "name", "keywords", "campaigns_applied"]


def write_export(root: Path, tables: dict) -> None:
    manifest = []
    for key, rows in tables.items():
        cols, rows = rows if isinstance(rows, tuple) else (list(dict.fromkeys(k for r in rows for k in r)), rows)
        path = root / f"{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        manifest.append({"filename": f"{key}.csv", "completeness": "complete", "truncation": "none"})
    with (root / "table_manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "completeness", "truncation"])
        w.writeheader()
        w.writerows(manifest)


def q(term, cost, gid="G1", conv=0):
    return {"search_term": term, "campaign_id": "C1", "ad_group_id": gid, "clicks": "5", "cost": str(cost),
            "conversions": str(conv)}


def tables(queries, negatives=(), lists=(), groups=("G1",), channel="SEARCH"):
    return {
        "account": [{"customer_id": "1", "currency_code": "EUR", "date_range_start": "2026-08-01",
                     "date_range_end": "2026-08-30", "snapshot_date": "2026-09-06", "conversion_lag_days": "2"}],
        "campaigns": [{"id": "C1", "channel_type": channel, "status": "ENABLED", "target_cpa": ""}],
        "ad_groups": [{"id": g, "campaign_id": "C1", "status": "ENABLED"} for g in groups],
        "keywords": [{"id": "K1", "campaign_id": "C1", "ad_group_id": "G1", "text": "drill", "status": "ENABLED"}],
        "negative_keywords": (NEG_COLS, [dict(zip(NEG_COLS, n)) for n in negatives]),
        "shared_negative_lists": (LIST_COLS, [dict(zip(LIST_COLS, x)) for x in lists]),
        "search_terms": queries,
        "campaign_metrics": [{"campaign_id": "C1", "clicks": "100", "cost": "500"}],
    }


PROFILE = {"excluded_intents": ["employment"], "excluded_intent_terms": {"employment": ["jobs"]},
           "brand_terms": ["acme"], "conversion_lag_days": 2}


class CheckTests(unittest.TestCase):
    def run_skill(self, t, profile=PROFILE):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_export(self.root / "export", t)
        (self.root / "profile.json").write_text(json.dumps(profile))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, self.root / "export", self.root / "profile.json").finish()

    @staticmethod
    def found(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"] if sev in (None, f["severity"]))

    @staticmethod
    def cov(body):
        return {c["check"]: c["status"] for c in body["coverage"]}

    def test_unprotected_material_exposure_is_warning(self):
        body = self.run_skill(tables([q("drill jobs", 30), q("jobs drill", 25)]))  # 55 >= 50
        self.assertEqual(self.found(body, "Warning"), ["approved_exclusion_unprotected"])
        body = self.run_skill(tables([q("drill jobs", 30), q("jobs drill", 19)]))  # 49 < 50
        self.assertEqual(self.found(body, "Warning"), [])

    def test_current_protection_or_exception_prevents_warning(self):
        body = self.run_skill(tables([q("drill jobs", 80)], negatives=[("jobs", "PHRASE", "campaign", "C1", "")]))
        self.assertEqual(self.found(body, "Warning"), [])
        body = self.run_skill(tables([q("drill jobs", 80)]), dict(PROFILE, negative_exceptions={"C1": ["employment"]}))
        self.assertEqual(self.found(body, "Warning"), [])

    def test_partial_ad_group_protection_still_exposed(self):
        t = tables([q("drill jobs", 80, gid="G2")], negatives=[("jobs", "PHRASE", "ad_group", "C1", "G1")],
                   groups=("G1", "G2"))
        body = self.run_skill(t)
        self.assertEqual(self.found(body, "Warning"), ["approved_exclusion_unprotected"])

    def test_no_approved_exclusions_is_skipped_not_passed(self):
        body = self.run_skill(tables([q("drill jobs", 80)]), {"brand_terms": ["acme"]})
        self.assertEqual(self.cov(body)["intent_matrix"], "skipped")
        self.assertEqual(self.cov(body)["observed_exposure"], "skipped")
        self.assertEqual(body["findings"], [])

    def test_master_and_unattached_lists_are_info(self):
        lists = [("L1", "Master", "jobs (PHRASE)", ""), ("L2", "Other", "free (PHRASE)", "C1")]
        body = self.run_skill(tables([], lists=lists), dict(PROFILE, master_negative_lists={"L1": ["C1"]}))
        self.assertEqual(self.found(body, "Info"), ["master_list_association_missing", "unattached_shared_list"])

    def test_non_eligible_channel_is_ignored(self):
        body = self.run_skill(tables([q("drill jobs", 80)], channel="DISPLAY"))
        self.assertEqual(self.found(body, "Warning"), [])

    def test_untermed_intent_batch_review_and_finalize(self):
        profile = {"excluded_intents": ["free requests"], "brand_terms": ["acme"], "conversion_lag_days": 2}
        body = self.run_skill(tables([q("free drill", 40), q("free drill bits", 30), q("drill", 10, conv=1)]), profile)
        item = [r for r in body["ai_review"] if r["condition_key"] == "excluded_intent_exposure"][0]
        out = self.root / "out"
        args = ["--export", str(self.root / "export"), "--profile", str(self.root / "profile.json"), "--out", str(out)]
        cases = (({"intent": "free requests", "queries": ["free drill"]}, 4),  # 40 < floor 50
                 ({"intent": "free requests", "queries": ["free drill", "free drill bits"],
                   "negatives": [{"negative": "drill", "match_type": "PHRASE", "campaign_ids": ["C1"]}]}, 4),
                 ({"intent": "free requests", "queries": ["free drill", "free drill bits"],
                   "negatives": [{"negative": "free", "match_type": "PHRASE", "campaign_ids": ["C1"]}]}, 0))
        with contextlib.redirect_stdout(io.StringIO()):
            M.cli.main(M.SKILL, M.VERSION, M.run, M.verify, ["run"] + args)
            for proposal, code in cases:
                dec = self.root / "d.json"
                dec.write_text(json.dumps([{"id": item["id"], "outcome": "material_unprotected", "rationale": "r",
                                            "proposal": proposal}]))
                self.assertEqual(M.cli.main(M.SKILL, M.VERSION, M.run, M.verify,
                                            ["finalize"] + args + ["--decisions", str(dec)]), code)


UP_COLS = ["customer_id", "campaign_id", "ad_group_id", "level", "list_id", "text", "match_type"]
UP = "external/negative_upload_list"
FIXTURE = Path(__file__).resolve().parents[2] / "_selftest" / "fixture"


def up(text, match="PHRASE", level="campaign", cid="C1", gid="", lid="", cust=""):
    return dict(zip(UP_COLS, (cust, cid, gid, level, lid, text, match)))


class UploadValidationTests(unittest.TestCase):
    def run_upload(self, rows, account_id=None, profile=PROFILE, **kw):
        t = tables(kw.pop("queries", [q("drill jobs", 10)]), **kw)
        t[UP] = (UP_COLS, rows)
        return self._run(t, profile, account_id)

    def _run(self, t, profile=PROFILE, account_id=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        write_export(root / "export", t)
        (root / "profile.json").write_text(json.dumps(profile))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, root / "export", root / "profile.json",
                              account_id=account_id).finish()

    @staticmethod
    def up_found(body, sev=None):
        return sorted(f["condition_key"] for f in body["findings"]
                      if f["check"] == "negative_upload_validation" and sev in (None, f["severity"]))

    @staticmethod
    def up_cov(body):
        return next(c for c in body["coverage"] if c["check"] == "negative_upload_validation")

    def _run_partial_groups(self, rows, groups):
        t = tables([q("drill jobs", 10)], groups=groups)
        t["ad_groups"] = (["id", "campaign_id", "status"], t["ad_groups"])
        t[UP] = (UP_COLS, rows)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        write_export(root / "export", t)
        man = root / "export" / "table_manifest.csv"
        man.write_text(man.read_text().replace("ad_groups.csv,complete", "ad_groups.csv,partial"))
        (root / "profile.json").write_text(json.dumps(PROFILE))
        return M.cli.run_once(M.SKILL, M.VERSION, M.run, root / "export", root / "profile.json").finish()

    def test_incomplete_ad_groups_never_clear_campaign_scope(self):
        # G1 missing from a partial ad_groups export: keyword K1 'drill' (G1) is still found through keywords rows
        body = self._run_partial_groups([up("drill", "PHRASE")], groups=())
        self.assertEqual(self.up_found(body, "Warning"), ["upload_blocks_keyword"])
        self.assertEqual(self.up_cov(body)["status"], "partial")
        # no collision found, but incomplete inventory: coverage stays partial, never completed
        body = self._run_partial_groups([up("jobs")], groups=("G1",))
        self.assertEqual(self.up_found(body, "Warning"), [])
        self.assertEqual(self.up_cov(body)["status"], "partial")

    def test_valid_list_has_no_warning_and_completes(self):
        body = self.run_upload([up("jobs"), up("careers", "EXACT", "ad_group", gid="G1")])
        self.assertEqual(self.up_found(body), [])
        self.assertEqual(self.up_cov(body)["status"], "completed")

    def test_blocks_active_keyword_in_scope_only(self):
        body = self.run_upload([up("drill", "PHRASE")])
        self.assertEqual(self.up_found(body, "Warning"), ["upload_blocks_keyword"])
        # K1 'drill' lives in G1: an ad-group negative on G2 does not touch it
        body = self.run_upload([up("drill", "PHRASE", "ad_group", gid="G2")], groups=("G1", "G2"))
        self.assertEqual(self.up_found(body, "Warning"), [])
        # EXACT 'drill bits' does not block the keyword 'drill'
        body = self.run_upload([up("drill bits", "EXACT")])
        self.assertEqual(self.up_found(body, "Warning"), [])

    def test_blocks_converting_query_but_not_zero_conversion_query(self):
        body = self.run_upload([up("cordless", "BROAD")], queries=[q("cordless drill set", 10, conv=1)])
        self.assertEqual(self.up_found(body, "Warning"), ["upload_blocks_converting_query"])
        body = self.run_upload([up("cordless", "BROAD")], queries=[q("cordless drill set", 10, conv=0)])
        self.assertEqual(self.up_found(body, "Warning"), [])

    def test_blocks_brand_term_unless_campaign_is_nonbrand_only(self):
        body = self.run_upload([up("acme", "BROAD")])
        self.assertEqual(self.up_found(body, "Warning"), ["upload_blocks_brand"])
        prof = dict(PROFILE, campaign_objectives={"C1": {"brand_policy": "nonbrand_only"}})
        body = self.run_upload([up("acme", "BROAD")], profile=prof)
        self.assertEqual(self.up_found(body, "Warning"), [])

    def test_shared_list_scope_uses_attached_campaigns(self):
        lists = [("L1", "Master", "free (PHRASE)", "C1")]
        body = self.run_upload([up("drill", "EXACT", "shared_list", cid="", lid="L1")], lists=lists)
        self.assertEqual(self.up_found(body, "Warning"), ["upload_blocks_keyword"])
        body = self.run_upload([up("free", "PHRASE", "shared_list", cid="", lid="L1")], lists=lists)
        self.assertEqual(self.up_found(body), ["upload_duplicate_existing"])

    def test_duplicates_in_list_and_existing(self):
        body = self.run_upload([up("jobs"), up("Jobs", "phrase")])
        self.assertEqual(self.up_found(body), ["upload_duplicate_row"])
        body = self.run_upload([up("jobs")], negatives=[("jobs", "PHRASE", "campaign", "C1", "")])
        self.assertEqual(self.up_found(body), ["upload_duplicate_existing"])
        # same text, different match type: not a duplicate of the existing negative
        body = self.run_upload([up("jobs", "EXACT")], negatives=[("jobs", "PHRASE", "campaign", "C1", "")])
        self.assertEqual(self.up_found(body), [])

    def test_missing_or_inactive_target_and_match_type(self):
        body = self.run_upload([up("jobs", cid="C9"), up("jobs", "PHRASE", "ad_group", cid="C2", gid="G1"),
                                up("jobs", "PHRASE", "shared_list", lid="L9")])
        self.assertEqual(self.up_found(body), ["upload_target_missing"] * 3)
        t = tables([])
        t["campaigns"][0]["status"] = "REMOVED"
        t[UP] = (UP_COLS, [up("jobs")])
        self.assertEqual(self.up_found(self._run(t)), ["upload_target_missing"])
        body = self.run_upload([up("jobs", match="")])
        self.assertEqual(self.up_found(body), ["upload_match_type_missing"])

    def test_operators_or_long_text_is_partial_not_finding(self):
        for text in ('"jobs"', "+jobs", "one two three four five six seven eight nine ten eleven"):
            body = self.run_upload([up(text)])
            self.assertEqual(self.up_found(body), [], text)
            self.assertEqual(self.up_cov(body)["status"], "partial", text)

    def test_other_account_rows_ignored(self):
        body = self.run_upload([up("drill", cust="2"), up("jobs", cust="1")])
        self.assertEqual(self.up_found(body), [])
        obs = [o["data"] for o in body["observations"] if o["check"] == "negative_upload_validation"][0]
        self.assertEqual((obs["rows_this_account"], obs["rows_other_accounts"]), (1, 1))

    def test_multi_account_isolation(self):
        t = {}
        for acct in ("1", "2"):
            for key, rows in tables([q("cordless drill", 10, conv=1)]).items():
                rows = rows[1] if isinstance(rows, tuple) else rows
                t.setdefault(key, []).extend(dict(r, customer_id=acct) for r in rows)
        t["negative_keywords"] = (NEG_COLS + ["customer_id"], [])
        t["shared_negative_lists"] = (LIST_COLS + ["customer_id"], [])
        t[UP] = (UP_COLS, [up("drill", cust="1"), up("jobs", cust="2")])
        one, two = self._run(t, account_id="1"), self._run(t, account_id="2")
        self.assertEqual(self.up_found(one, "Warning"), ["upload_blocks_converting_query", "upload_blocks_keyword"])
        self.assertEqual(self.up_found(two), [])

    def test_missing_file_is_skipped(self):
        body = self._run(tables([q("drill jobs", 10)]))
        cov = self.up_cov(body)
        self.assertEqual(cov["status"], "skipped")
        self.assertIn("external/negative_upload_list (file)", cov["missing"])

    def test_fixture_run_exits_zero_with_and_without_upload_list(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / "export"
        shutil.copytree(FIXTURE / "export", export)
        for name, extra in (("base", None), ("upload", [up("acme", "PHRASE", cid="1001"), up("jobs", cid="1002"),
                                                        up("jobs", cid="9999")])):
            if extra:
                (export / "external").mkdir(exist_ok=True)
                with (export / f"{UP}.csv").open("w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=UP_COLS)
                    w.writeheader()
                    w.writerows(extra)
            out = root / name
            p = subprocess.run([sys.executable, str(SCRIPT), "run", "--export", str(export), "--profile",
                                str(FIXTURE / "profile.yaml"), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            body = json.loads((out / "result.json").read_text())
            if extra is None:
                self.assertEqual(self.up_cov(body)["status"], "skipped")
            else:
                self.assertEqual(self.up_found(body, "Warning"),
                                 ["upload_blocks_brand", "upload_blocks_converting_query", "upload_blocks_keyword"])
                self.assertIn("upload_target_missing", self.up_found(body, "Info"))


if __name__ == "__main__":
    unittest.main()
