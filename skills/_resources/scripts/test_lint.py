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
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text)
    return d


class FrontmatterTests(unittest.TestCase):
    def test_parses_nested_metadata_lists_and_null(self):
        text = GOOD.replace("markets: all", "markets: all\n  related: [skill-001-a, skill-002-b]")
        fm, body = lint.parse_frontmatter(text)
        self.assertEqual(fm["name"], "skill-004-ad-group-thematic-tightness")
        self.assertEqual(fm["description"], "Evaluate ad group tightness.")
        self.assertEqual(fm["metadata"]["kind"], "deterministic")
        self.assertIsNone(fm["metadata"]["gaql_verified"])
        self.assertEqual(fm["metadata"]["related"], ["skill-001-a", "skill-002-b"])
        self.assertTrue(body.startswith("# Skill 004"))

    def test_folded_description(self):
        text = GOOD.replace('description: "Evaluate ad group tightness."', "description: >\n  Line one\n  line two")
        fm, _ = lint.parse_frontmatter(text)
        self.assertEqual(fm["description"], "Line one line two")


class CheckSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.params = {"spend_floor", "currency"}

    def tearDown(self):
        self.tmp.cleanup()

    def issues(self, text, name="skill-004-ad-group-thematic-tightness", allow_dollars=False, merges=""):
        d = make_skill(self.root, name, text)
        names = {p.name for p in self.root.iterdir() if p.is_dir()}
        return lint.check_skill(d, self.params, merges, names, allow_dollars)

    def test_good_skill_has_no_issues(self):
        self.assertEqual(self.issues(GOOD), [])

    def test_dollar_digit_is_flagged_but_dollar_bracket_is_not(self):
        bad = GOOD.replace("Cost >= {{spend_floor}}", "Cost >= $50")
        self.assertTrue(any("$50" in i or "dollar" in i for i in self.issues(bad)))
        self.assertEqual(self.issues(GOOD), [])  # GOOD contains $[X]

    def test_allow_dollars_flag(self):
        bad = GOOD.replace("Cost >= {{spend_floor}}", "Cost >= $50")
        self.assertFalse(any("dollar" in i for i in self.issues(bad, allow_dollars=True)))

    def test_hyphen_command_is_flagged(self):
        bad = GOOD.replace("Run the reference query", "Run `/google-ads-get-custom`")
        self.assertTrue(any("google-ads-get" in i for i in self.issues(bad)))

    def test_section_order_is_enforced_ignoring_code_fences(self):
        bad = GOOD.replace("## Analysis Steps\n1. Step.\n\n", "")  # a required section is missing
        self.assertTrue(any("section" in i.lower() for i in self.issues(bad)))
        self.assertEqual(self.issues(GOOD), [])  # "## Example Audit" inside a fence is ignored

    def test_unknown_param_is_flagged(self):
        bad = GOOD.replace("{{spend_floor}}", "{{spend_nope}}")
        self.assertTrue(any("spend_nope" in i for i in self.issues(bad)))

    def test_name_must_match_directory(self):
        self.assertTrue(any("directory" in i for i in self.issues(GOOD, name="skill-004-wrong")))

    def test_merged_from_must_not_exist_and_must_be_in_merges(self):
        text = GOOD.replace("markets: all", "markets: all\n  merged_from: [skill-133-impression-share-loss-analysis]")
        make_skill(self.root, "skill-133-impression-share-loss-analysis", GOOD.replace("skill-004-ad-group-thematic-tightness", "skill-133-impression-share-loss-analysis"))
        issues = self.issues(text, merges="")
        self.assertTrue(any("still exists" in i for i in issues))
        self.assertTrue(any("MERGES.md" in i for i in issues))

    def test_related_must_exist(self):
        text = GOOD.replace("markets: all", "markets: all\n  related: [skill-999-ghost]")
        self.assertTrue(any("skill-999-ghost" in i for i in self.issues(text)))

    def test_enum_values(self):
        bad = GOOD.replace("kind: deterministic", "kind: magic")
        self.assertTrue(any("kind" in i for i in self.issues(bad)))


class CatalogTests(unittest.TestCase):
    def test_catalog_row_and_render(self):
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
