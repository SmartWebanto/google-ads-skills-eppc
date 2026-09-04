"""skills/_resources/scripts/test_lint.py — test_lint module.

exports: GOOD | make_skill(root, name, text) | class FrontmatterTests | class CheckSkillTests | class CatalogTests
used_by: none
rules:   none
agent:   codedna-cli (no-llm) | codedna-cli | 2026-09-03 | codedna-cli | initial CodeDNA annotation pass
message: 
"""
import tempfile
import unittest
from pathlib import Path

import lint

GOOD = """---
name: skill-004-ad-group-thematic-tightness
description: "Evaluate ad group tightness."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: structure
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 004: Ad Group Thematic Tightness

## Purpose
Text.

## Data Requirements
**Data Source:** Account export
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
    def test_catalog_row_and_render(self):
        """Rules: row fields and rendered column order are the CATALOG.md contract."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "skill-004-ad-group-thematic-tightness", GOOD)
            rows = lint.catalog_rows(root)
            self.assertEqual(rows[0]["number"], 4)
            self.assertEqual(rows[0]["kind"], "deterministic")
            md = lint.render_catalog(rows)
            self.assertIn("| 004 | skill-004-ad-group-thematic-tightness | structure | deterministic | export | all |", md)


if __name__ == "__main__":
    unittest.main()
