"""skills/_resources/scripts/test_lint.py — test_lint module.

exports: GOOD | make_skill(root, name, text) | class FrontmatterTests | class CheckSkillTests | class CatalogTests
used_by: unittest → structural contract regressions
rules:   Fixtures live in temporary directories; tests defend observable validation failures.
agent:   codedna-cli (no-llm) | codedna-cli | 2026-09-03 | codedna-cli | initial CodeDNA annotation pass
agent:   gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | evidence and routing regression cases
agent:   gpt-6-astra | openai | 2026-09-07 | s_20260907_context_opt | searchable discovery and missing-description boundaries
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | script/test header gate, network and dynamic import regressions
message: 
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import lint

GOOD = """---
name: skill-004-ad-group-thematic-tightness
description: "Evaluate ad group tightness."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
  agent: test | local | 2026-09-06 | regression
---
# Skill 004: Ad Group Thematic Tightness

## Purpose
Text.

## Data Requirements
**Data Source:** Account export
**Applicability:** Search campaigns with mature conversion evidence.
**Required inputs:** Campaigns and campaign_metrics joined by campaign ID over the report period.
**Missing inputs:** Skip performance checks without metrics; report missing fields.
Run the reference query (API, UI report, or Editor export) if needed.

## Analysis Steps
1. Step.

## Thresholds
| Condition | Severity |
|-----------|----------|
| Cost >= {{spend_floor}} | Warning |

## Output
```
## Example Audit
$[X] and {{currency}} [X]
```
"""


VALID_SCRIPT = '''"""check.py — fixture.

exports: run
used_by: test
rules:   none
agent:   test
"""
import sys
SKILL = "skill-004-ad-group-thematic-tightness"
VERSION = "1.0.0"


def run(ctx):
    """Fixture run.

    Rules:   emits nothing; exists only to satisfy the static script contract.
    """
'''


def make_skill(root: Path, name: str, text: str) -> Path:
    """Rules: overwrites any existing SKILL.md — intended for per-test temp dirs only."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text)
    return d


class FrontmatterTests(unittest.TestCase):
    def test_parses_nested_metadata_lists_and_null(self):
        """Rules: defends nested metadata map, inline list, and null scalar parsing in one pass."""
        text = GOOD.replace("markets: all", "markets: all\n  related: [skill-001-a, skill-002-b]")
        fm, body = lint.parse_frontmatter(text)
        self.assertEqual(fm["name"], "skill-004-ad-group-thematic-tightness")
        self.assertEqual(fm["description"], "Evaluate ad group tightness.")
        self.assertEqual(fm["metadata"]["kind"], "deterministic")
        self.assertIsNone(fm["metadata"]["gaql_verified"])
        self.assertEqual(fm["metadata"]["related"], ["skill-001-a", "skill-002-b"])
        self.assertTrue(body.startswith("# Skill 004"))

    def test_folded_description(self):
        """Rules: folded (>) description blocks must join lines with single spaces."""
        text = GOOD.replace('description: "Evaluate ad group tightness."', "description: >\n  Line one\n  line two")
        fm, _ = lint.parse_frontmatter(text)
        self.assertEqual(fm["description"], "Line one line two")


class CheckSkillTests(unittest.TestCase):
    def setUp(self):
        """Rules: fresh temp dir per test — no state shared across tests."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.params = {"spend_floor", "currency"}

    def tearDown(self):
        self.tmp.cleanup()

    def issues(self, text, name="skill-004-ad-group-thematic-tightness", allow_dollars=False, merges=""):
        """Rules: helper writes the skill then lints it; the names set is recomputed
        per call so merged_from tests see previously created directories."""
        d = make_skill(self.root, name, text)
        names = {p.name for p in self.root.iterdir() if p.is_dir()}
        return lint.check_skill(d, self.params, merges, names, allow_dollars)

    def test_good_skill_has_no_issues(self):
        """Rules: GOOD fixture must stay issue-free — every negative test derives from it."""
        self.assertEqual(self.issues(GOOD), [])

    def test_dollar_digit_is_flagged_but_dollar_bracket_is_not(self):
        """Rules: DOLLAR_DIGIT_RE flags $<digit> only; the $[X] placeholder in GOOD must pass."""
        bad = GOOD.replace("Cost >= {{spend_floor}}", "Cost >= $50")
        self.assertTrue(any("$50" in i or "dollar" in i for i in self.issues(bad)))
        self.assertEqual(self.issues(GOOD), [])  # GOOD contains $[X]

    def test_allow_dollars_flag(self):
        """Rules: --allow-dollars suppresses dollar-literal errors entirely."""
        bad = GOOD.replace("Cost >= {{spend_floor}}", "Cost >= $50")
        self.assertFalse(any("dollar" in i for i in self.issues(bad, allow_dollars=True)))

    def test_plugin_command_reference_is_flagged(self):
        """Rules: any /google-ads[:-]get reference is flagged — the library is tool-neutral."""
        for cmd in ("/google-ads-get-custom", "/google-ads:get-custom", "/google-ads:get"):
            bad = GOOD.replace("Run the reference query", f"Run `{cmd}`")
            self.assertTrue(any("plugin command" in i for i in self.issues(bad)), cmd)

    def test_section_order_is_enforced_ignoring_code_fences(self):
        """Rules: section order is exact-match on SECTIONS; '## ' headings inside code fences are ignored."""
        bad = GOOD.replace("## Analysis Steps\n1. Step.\n\n", "")  # a required section is missing
        self.assertTrue(any("section" in i.lower() for i in self.issues(bad)))
        self.assertEqual(self.issues(GOOD), [])  # "## Example Audit" inside a fence is ignored

    def test_unknown_param_is_flagged(self):
        """Rules: every {{param}} must be defined in PARAMETERS.md."""
        bad = GOOD.replace("{{spend_floor}}", "{{spend_nope}}")
        self.assertTrue(any("spend_nope" in i for i in self.issues(bad)))

    def test_name_must_match_directory(self):
        """Rules: frontmatter name must equal the directory name."""
        self.assertTrue(any("directory" in i for i in self.issues(GOOD, name="skill-004-wrong")))

    def test_merged_from_must_not_exist_and_must_be_in_merges(self):
        """Rules: merged_from entries must not exist as directories and must be documented in MERGES.md."""
        text = GOOD.replace("markets: all", "markets: all\n  merged_from: [skill-133-impression-share-loss-analysis]")
        make_skill(self.root, "skill-133-impression-share-loss-analysis", GOOD.replace("skill-004-ad-group-thematic-tightness", "skill-133-impression-share-loss-analysis"))
        issues = self.issues(text, merges="")
        self.assertTrue(any("still exists" in i for i in issues))
        self.assertTrue(any("MERGES.md" in i for i in issues))

    def test_related_must_exist(self):
        """Rules: related entries must reference existing skill directories."""
        text = GOOD.replace("markets: all", "markets: all\n  related: [skill-999-ghost]")
        self.assertTrue(any("skill-999-ghost" in i for i in self.issues(text)))

    def test_enum_values(self):
        """Rules: kind/data_source/markets/category are closed enums — unknown values are errors."""
        bad = GOOD.replace("kind: deterministic", "kind: magic")
        self.assertTrue(any("kind" in i for i in self.issues(bad)))

    def test_evidence_requirements_and_source_must_agree(self):
        """Rules: missing evidence handling and data-source labeling are consumer contracts."""
        bad = GOOD.replace("**Missing inputs:** Skip performance checks without metrics; report missing fields.\n", "")
        self.assertTrue(any("Missing inputs" in issue for issue in self.issues(bad)))
        bad = GOOD.replace("data_source: export", "data_source: external")
        self.assertTrue(any("Data Source" in issue for issue in self.issues(bad)))

    def test_unsupported_severity_is_rejected(self):
        """Rules: a fourth severity must not silently disappear from three-level reports."""
        bad = GOOD.replace("| Warning |", "| High |")
        self.assertTrue(any("severity" in issue for issue in self.issues(bad)))

    def test_invalid_gaql_date_range_is_rejected(self):
        """Rules: a syntactically plausible but nonexistent GAQL range is not executable."""
        bad = GOOD.replace("Run the reference query", "```sql\nSELECT campaign.id FROM campaign WHERE segments.date DURING LAST_90_DAYS\n```\nRun the reference query")
        self.assertTrue(any("LAST_90_DAYS" in issue for issue in self.issues(bad)))

    def test_metadata_scalar_is_an_error_not_a_crash(self):
        """Rules: malformed input must return a validation finding."""
        bad = GOOD.replace("metadata:\n", "metadata: wrong\n")
        self.assertTrue(any("metadata must be a map" in issue for issue in self.issues(bad)))

    def test_empty_description_cannot_support_catalog_selection(self):
        """Rules: discovery must fail rather than publish an entry with no selection evidence."""
        bad = GOOD.replace('description: "Evaluate ad group tightness."', 'description: ""')
        self.assertTrue(any("description" in issue for issue in self.issues(bad)))

    def test_catalog_generation_refuses_invalid_routing(self):
        """Rules: deleted routed skills must fail and must not overwrite the last valid catalog."""
        root = self.root / "skills"
        root.mkdir()
        make_skill(root, "skill-004-ad-group-thematic-tightness", GOOD)
        resources = root / "_resources"
        resources.mkdir()
        (resources / "PARAMETERS.md").write_text("{{spend_floor}} {{currency}}")
        (self.root / "ads").mkdir()
        (self.root / "ads" / "SKILL.md").write_text("| audit | 004, 063 |\n")
        catalog = root / "CATALOG.md"
        catalog.write_text("last valid catalog")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = lint.main(["--root", str(root), "--expect-count", "1", "--write-catalog"])
        self.assertEqual(result, 1)
        self.assertIn("absent skill-063", output.getvalue())
        self.assertEqual(catalog.read_text(), "last valid catalog")

    def test_cli_accepts_canonical_route_and_generates_catalog(self):
        """Rules: the public CLI accepts complete evidence contracts and live routing IDs."""
        root = self.root / "skills"
        root.mkdir()
        make_skill(root, "skill-004-ad-group-thematic-tightness", GOOD)
        (root / "skill-004-ad-group-thematic-tightness" / "scripts").mkdir()
        (root / "skill-004-ad-group-thematic-tightness" / "scripts" / "check.py").write_text(VALID_SCRIPT)
        (root / "skill-004-ad-group-thematic-tightness" / "tests").mkdir()
        (root / "skill-004-ad-group-thematic-tightness" / "tests" / "test_check.py").write_text(
            '"""t.\n\nexports: x\nused_by: y\nrules:   z\nagent:   a\n"""\n')
        (root / "_resources").mkdir()
        (root / "_resources" / "PARAMETERS.md").write_text("{{spend_floor}} {{currency}}")
        (self.root / "ads").mkdir()
        (self.root / "ads" / "SKILL.md").write_text("| audit | 004 |\n")
        with contextlib.redirect_stdout(io.StringIO()):
            result = lint.main(["--root", str(root), "--expect-count", "1", "--write-catalog"])
        self.assertEqual(result, 0)
        self.assertIn("skill-004-ad-group-thematic-tightness", (root / "CATALOG.md").read_text())

    def test_scripts_are_required_and_statically_safe(self):
        """Rules: missing, clock-reading, networked or misnamed check.py fail; --allow-missing-scripts is authoring-only."""
        d = self.root / "skill-004-ad-group-thematic-tightness"
        d.mkdir()
        self.assertEqual(lint.check_script(d, True), [f"{d.name}: scripts/check.py missing"])
        self.assertEqual(lint.check_script(d, False), [])
        (d / "scripts").mkdir()
        (d / "scripts" / "check.py").write_text(VALID_SCRIPT)
        self.assertIn(f"{d.name}: tests/test_check.py missing", lint.check_script(d, True))
        (d / "tests").mkdir()
        (d / "tests" / "test_check.py").write_text('"""t.\n\nexports: x\nused_by: y\nrules:   z\nagent:   a\n"""\n')
        self.assertEqual(lint.check_script(d, True), [])
        for bad in ("import urllib.request\n", "import urllib.request as u\n", "from urllib import request\n",
                    "import http.client\n", "import socket\n", "m = __import__('socket')\n",
                    "import requests\n", "x = datetime.now()\n"):
            (d / "scripts" / "check.py").write_text(VALID_SCRIPT + bad)
            self.assertTrue(lint.check_script(d, True), bad)
        (d / "scripts" / "check.py").write_text(VALID_SCRIPT + "from urllib.parse import urlsplit\n")
        self.assertEqual(lint.check_script(d, True), [])
        (d / "scripts" / "check.py").write_text(VALID_SCRIPT + "# never call __import__(x) or import_module(x)\nNOTE = 'import_module(y)'\n")
        self.assertEqual(lint.check_script(d, True), [])  # text-only mentions are fine
        for dyn in ("import importlib\nm = importlib.import_module('os')\n", "from importlib import import_module\nm = import_module('os')\n"):
            (d / "scripts" / "check.py").write_text(VALID_SCRIPT + dyn)
            self.assertTrue(any("dynamic imports" in i for i in lint.check_script(d, True)), dyn)
        (d / "scripts" / "check.py").write_text(VALID_SCRIPT.replace("Rules:   emits nothing; exists only to satisfy the static script contract.", "Rules: see module rules"))
        self.assertTrue(lint.check_script(d, True))
        (d / "scripts" / "check.py").write_text(VALID_SCRIPT.replace("skill-004-ad-group-thematic-tightness", "skill-004-x"))
        self.assertTrue(lint.check_script(d, True))


class SelftestTests(unittest.TestCase):
    def test_cases_must_reference_existing_skills_and_carry_must_contain(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "skill-004-ad-group-thematic-tightness", GOOD)
            (root / "_selftest" / "fixture").mkdir(parents=True)
            (root / "_selftest" / "fixture" / "expected.json").write_text(json.dumps({"cases": [
                {"skill": "skill-004-ad-group-thematic-tightness", "expect": [{"severity": "Critical", "must_contain": ["x"]}]},
                {"skill": "skill-999-ghost", "expect": [{"severity": "Critical"}]},
            ]}))
            issues = lint.check_selftest(root, {"skill-004-ad-group-thematic-tightness"})
            self.assertTrue(any("skill-999-ghost" in i for i in issues))
            self.assertTrue(any("without must_contain" in i for i in issues))
            self.assertEqual(len(issues), 2)

    def test_no_selftest_folder_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lint.check_selftest(Path(tmp), set()), [])


class CatalogTests(unittest.TestCase):
    def test_discovery_preserves_exclusions_without_loading_other_sections(self):
        """Rules: multiline applicability remains searchable; examples and required inputs cannot become routing facts."""
        text = GOOD.replace(
            "Search campaigns with mature conversion evidence.",
            "Search | Shopping campaigns.\n  Not PMax; unknown subtype needs confirmation.",
        ).replace(
            "**Data Source:** Account export",
            "```text\n**Applicability:** Decoy in example.\n```\n**Data Source:** Account export",
        ).replace("Evaluate ad group tightness.", "Review Search | Shopping groups.")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "skill-004-ad-group-thematic-tightness", text)
            md = lint.render_catalog(lint.catalog_rows(root))
            matches = [line for line in md.splitlines() if "skill-004-ad-group-thematic-tightness" in line]
            self.assertEqual(len(matches), 1)
            self.assertIn("Review Search &#124; Shopping groups.", matches[0])
            self.assertIn("Search &#124; Shopping campaigns. Not PMax; unknown subtype needs confirmation.", matches[0])
            self.assertNotIn("Decoy", matches[0])
            self.assertNotIn("Campaigns and campaign_metrics", matches[0])


if __name__ == "__main__":
    unittest.main()
