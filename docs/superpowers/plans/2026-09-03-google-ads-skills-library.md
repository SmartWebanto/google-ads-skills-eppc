# Google Ads Skills Library (eppc edition) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the raw 145-skill TrueClicks harvest in this folder into a curated, versioned, EU-ready library of 137 Markdown skills with provenance, classification, parametric thresholds, localized output, a rewritten front desk, and a lint that proves it.

**Architecture:** Everything is Markdown under `skills/` plus two stdlib-only Python scripts (`lint.py` for checks and catalog, two one-off migration scripts for the bulk edits). No engine. Work is phased so each phase ends with a passing lint and one commit. The spec's frontmatter `metadata` block is the contract every later task reads.

**Tech Stack:** Markdown, Python 3.9+ standard library (`unittest`, `pathlib`, `re`, `argparse`), git.

**Spec:** `docs/superpowers/specs/2026-09-03-google-ads-skills-library-design.md`

## Global Constraints

- Work only inside `/Users/antonio/nuovo_clientes/google-ads-skills-eppc/`. Never touch `studio/`, client repos, `~/.claude/`.
- No TypeScript, no engine, no network calls. Python is stdlib only.
- Library version string everywhere: `eppc-ads-skills@1.0.0`. Upstream string everywhere: `trueclicks/claude-plugins google-ads@1.8.0`. Review date: `2026-09-03`.
- Skill directories are named exactly as the skill `name` (`skill-NNN-slug`), like the upstream plugin.
- Body sections, in order, exactly: `## Purpose`, `## Data Requirements`, `## Analysis Steps`, `## Thresholds`, `## Output`.
- Final counts: 137 skill directories; zero `$` followed by a digit; zero `/google-ads-get` (hyphen form).
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48
  ```
  Use `git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit`.

---

### Task 1: Rename the harvest and build the lint (TDD)

**Files:**
- Rename: `_harvest/` → `skills/` (git mv)
- Create: `skills/_resources/scripts/lint.py`
- Test: `skills/_resources/scripts/test_lint.py`

**Interfaces:**
- Produces: `python3 skills/_resources/scripts/lint.py [--root skills] [--allow-dollars] [--expect-count N] [--write-catalog]`; exit 0 when no errors. Functions `parse_frontmatter(text) -> (dict, body)`, `load_params(path) -> set[str]`, `check_skill(skill_dir, params, merges_text, skill_names, allow_dollars) -> list[str]`, `catalog_rows(root) -> list[dict]`, `render_catalog(rows) -> str`.

- [x] **Step 1: Rename the folder**

```bash
cd /Users/antonio/nuovo_clientes/google-ads-skills-eppc
git mv _harvest skills
mkdir -p skills/_resources/scripts
```

- [x] **Step 2: Write the failing tests**

Create `skills/_resources/scripts/test_lint.py`:

```python
import tempfile
import unittest
from pathlib import Path

import lint

GOOD = """---
name: skill-004-ad-group-thematic-tightness
description: "Evaluate ad group tightness."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-004-ad-group-thematic-tightness
  category: structure
  kind: deterministic
  data_source: standard
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 004: Ad Group Thematic Tightness

## Purpose
Text.

## Data Requirements
**Data Source:** Standard
Use `/google-ads:get-custom` if needed.

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
    d.mkdir(parents=True)
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
        bad = GOOD.replace("/google-ads:get-custom", "/google-ads-get-custom")
        self.assertTrue(any("google-ads-get" in i for i in self.issues(bad)))

    def test_section_order_is_enforced_ignoring_code_fences(self):
        bad = GOOD.replace("## Thresholds\n", "").replace("## Output\n", "## Thresholds\n## Output\n")
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
            self.assertIn("| 004 | skill-004-ad-group-thematic-tightness | structure | deterministic | standard | all |", md)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 3: Run tests to verify they fail**

Run: `cd skills/_resources/scripts && python3 -m unittest test_lint -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lint'`

- [x] **Step 4: Write lint.py**

Create `skills/_resources/scripts/lint.py`:

```python
#!/usr/bin/env python3
"""Lint and catalog generator for the eppc Google Ads skills library.

Standard library only. Usage:
  python3 skills/_resources/scripts/lint.py                # lint skills/
  python3 skills/_resources/scripts/lint.py --write-catalog
  python3 skills/_resources/scripts/lint.py --allow-dollars --expect-count 145
Exit code 1 when any error is found. Warnings never fail the run.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

KINDS = {"deterministic", "analyst", "operational"}
DATA_SOURCES = {"standard", "custom_gaql", "external"}
MARKETS = {"all", "us_only", "eea_relevant"}
CATEGORIES = {
    "structure", "keywords", "creative", "bidding", "targeting", "quality", "tracking",
    "shopping_pmax", "remarketing", "waste", "competitive", "compliance", "seasonal", "platform",
}
SECTIONS = ["## Purpose", "## Data Requirements", "## Analysis Steps", "## Thresholds", "## Output"]
REQUIRED_META = ["library", "upstream", "upstream_skill", "category", "kind", "data_source", "markets", "reviewed"]
NAME_RE = re.compile(r"^skill-(\d{3})-[a-z0-9-]+$")
PARAM_RE = re.compile(r"\{\{([a-z_]+)\}\}")
DOLLAR_DIGIT_RE = re.compile(r"\$\d")
HYPHEN_CMD_RE = re.compile(r"/google-ads-get")
MAX_LINES = 130


# ----------------------------------------------------------------------------- frontmatter
def _scalar(raw: str):
    v = raw.strip()
    if v == "" or v == "null" or v == "~":
        return None
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [] if not inner else [_scalar(x) for x in inner.split(",")]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the YAML subset used by SKILL.md files: scalars, inline lists, one nested map, folded text."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter start")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("missing frontmatter end") from None
    fm: dict = {}
    target = fm
    i = 1
    while i < end:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, rest = line.strip().partition(":")
        rest = rest.strip()
        if indent == 0:
            target = fm
        if rest in (">", "|"):
            block = []
            i += 1
            while i < end and (lines[i].startswith("  ") or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            target[key] = " ".join(b for b in block if b)
            continue
        if rest == "" and indent == 0:
            fm[key] = {}
            target = fm[key]
        else:
            target[key] = _scalar(rest)
        i += 1
    body = "\n".join(lines[end + 1:])
    return fm, body


# ----------------------------------------------------------------------------- helpers
def load_params(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(PARAM_RE.findall(path.read_text()))


def _strip_fences(body: str) -> str:
    out, fenced = [], False
    for line in body.split("\n"):
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


# ----------------------------------------------------------------------------- checks
def check_skill(skill_dir: Path, params: set[str], merges_text: str, skill_names: set[str], allow_dollars: bool) -> list[str]:
    issues: list[str] = []
    path = skill_dir / "SKILL.md"
    if not path.exists():
        return [f"{skill_dir.name}: SKILL.md missing"]
    text = path.read_text()
    try:
        fm, body = parse_frontmatter(text)
    except ValueError as e:
        return [f"{skill_dir.name}: frontmatter: {e}"]

    for key in ("name", "description", "allowed-tools", "metadata"):
        if key not in fm:
            issues.append(f"{skill_dir.name}: frontmatter missing '{key}'")
    name = fm.get("name", "")
    if name != skill_dir.name:
        issues.append(f"{skill_dir.name}: name '{name}' does not match directory")
    if not NAME_RE.match(str(name)):
        issues.append(f"{skill_dir.name}: name must look like skill-NNN-slug")

    meta = fm.get("metadata") or {}
    for key in REQUIRED_META:
        if key not in meta or meta[key] in (None, ""):
            issues.append(f"{skill_dir.name}: metadata missing '{key}'")
    if meta.get("kind") not in KINDS:
        issues.append(f"{skill_dir.name}: metadata.kind '{meta.get('kind')}' not in {sorted(KINDS)}")
    if meta.get("data_source") not in DATA_SOURCES:
        issues.append(f"{skill_dir.name}: metadata.data_source '{meta.get('data_source')}' not in {sorted(DATA_SOURCES)}")
    if meta.get("markets") not in MARKETS:
        issues.append(f"{skill_dir.name}: metadata.markets '{meta.get('markets')}' not in {sorted(MARKETS)}")
    if meta.get("category") not in CATEGORIES:
        issues.append(f"{skill_dir.name}: metadata.category '{meta.get('category')}' not in schema table")

    for m in _as_list(meta.get("merged_from")):
        if m in skill_names:
            issues.append(f"{skill_dir.name}: merged_from '{m}' still exists as a directory")
        if m not in merges_text:
            issues.append(f"{skill_dir.name}: merged_from '{m}' not documented in MERGES.md")
    for r in _as_list(meta.get("related")):
        if r not in skill_names:
            issues.append(f"{skill_dir.name}: related '{r}' does not exist")

    headings = [l.strip() for l in _strip_fences(body).split("\n") if l.startswith("## ")]
    if headings != SECTIONS:
        issues.append(f"{skill_dir.name}: sections are {headings}, expected {SECTIONS} (section order)")

    if not allow_dollars:
        for m in DOLLAR_DIGIT_RE.finditer(text):
            snippet = text[m.start(): m.start() + 12].split("\n")[0]
            issues.append(f"{skill_dir.name}: dollar literal '{snippet}' (use a {{{{parameter}}}})")
    if HYPHEN_CMD_RE.search(text):
        issues.append(f"{skill_dir.name}: broken command reference /google-ads-get… (upstream form is /google-ads:get…)")
    for p in set(PARAM_RE.findall(text)):
        if p not in params:
            issues.append(f"{skill_dir.name}: parameter '{{{{{p}}}}}' not defined in PARAMETERS.md")
    return issues


def warn_skill(skill_dir: Path) -> list[str]:
    n = len((skill_dir / "SKILL.md").read_text().split("\n"))
    return [f"{skill_dir.name}: {n} lines (> {MAX_LINES})"] if n > MAX_LINES else []


# ----------------------------------------------------------------------------- catalog
def skill_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and NAME_RE.match(p.name))


def catalog_rows(root: Path) -> list[dict]:
    rows = []
    for d in skill_dirs(root):
        fm, _ = parse_frontmatter((d / "SKILL.md").read_text())
        meta = fm.get("metadata") or {}
        rows.append({
            "number": int(NAME_RE.match(d.name).group(1)),
            "name": d.name,
            "category": meta.get("category", ""),
            "kind": meta.get("kind", ""),
            "data_source": meta.get("data_source", ""),
            "markets": meta.get("markets", ""),
            "merged_from": ", ".join(_as_list(meta.get("merged_from"))),
            "lines": len((d / "SKILL.md").read_text().split("\n")),
        })
    return sorted(rows, key=lambda r: r["number"])


def render_catalog(rows: list[dict]) -> str:
    out = [
        "# Skill catalog",
        "",
        f"Generated by `_resources/scripts/lint.py --write-catalog`. {len(rows)} skills.",
        "",
        "| # | Skill | Category | Kind | Data source | Markets | Merged from | Lines |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r['number']:03d} | {r['name']} | {r['category']} | {r['kind']} | {r['data_source']} | {r['markets']} | {r['merged_from']} | {r['lines']} |"
        )
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out += ["", "## Counts by kind", ""] + [f"- {k}: {v}" for k, v in sorted(kinds.items())] + [""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="skills")
    ap.add_argument("--allow-dollars", action="store_true")
    ap.add_argument("--expect-count", type=int, default=137)
    ap.add_argument("--write-catalog", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root)
    params = load_params(root / "_resources" / "PARAMETERS.md")
    merges_path = root / "MERGES.md"
    merges_text = merges_path.read_text() if merges_path.exists() else ""
    dirs = skill_dirs(root)
    names = {d.name for d in dirs}

    errors, warnings, seen_upstream = [], [], {}
    for d in dirs:
        errors += check_skill(d, params, merges_text, names, args.allow_dollars)
        warnings += warn_skill(d)
        try:
            fm, _ = parse_frontmatter((d / "SKILL.md").read_text())
            up = (fm.get("metadata") or {}).get("upstream_skill")
            if up in seen_upstream:
                errors.append(f"{d.name}: upstream_skill '{up}' also used by {seen_upstream[up]}")
            seen_upstream[up] = d.name
        except ValueError:
            pass
    if len(dirs) != args.expect_count:
        errors.append(f"expected {args.expect_count} skill directories, found {len(dirs)}")

    if args.write_catalog:
        (root / "CATALOG.md").write_text(render_catalog(catalog_rows(root)))
        print(f"wrote {root / 'CATALOG.md'}")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"{len(dirs)} skills, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd skills/_resources/scripts && python3 -m unittest test_lint -v`
Expected: all 12 tests PASS.

- [x] **Step 6: Run the lint on the raw library to see the expected baseline failures**

Run: `cd /Users/antonio/nuovo_clientes/google-ads-skills-eppc && python3 skills/_resources/scripts/lint.py --allow-dollars --expect-count 145 | tail -3`
Expected: `0 skills, 1 errors` (directories are not yet numbered so none match `skill-NNN-`; the count error is the only line). This proves the lint runs; Task 2 makes it meaningful.

- [x] **Step 7: Commit**

```bash
git add -A
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "chore: rename _harvest to skills; add lint + catalog script with tests

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

### Task 2: Phase 1 — numbered directories, provenance frontmatter, command fix

**Files:**
- Create: `skills/_resources/scripts/migrate_2026_09_03.py` (one-off, kept for reproducibility)
- Modify: all 145 `skills/*/SKILL.md`; rename all 145 directories to `skill-NNN-slug`
- Modify: `docs/superpowers/specs/2026-09-03-google-ads-skills-library-design.md` (one sentence)

**Interfaces:**
- Consumes: `lint.py` from Task 1.
- Produces: every SKILL.md has the `metadata` block of spec section 4; body `**Data Source:**` line is one of `Standard`, `Custom GAQL Required`, `External (beyond Google Ads data)`; every command reference is `/google-ads:get-custom` or `/google-ads:get`.

- [x] **Step 1: Amend the spec so directory naming is explicit**

In the spec, section 4, replace the sentence `` `name` keeps the upstream number and directory slug, except where a merge renames the canonical (section 6). `` with `` `name` keeps the upstream number and slug, and every skill directory is renamed to that full name (`skill-NNN-slug`, as in the upstream plugin), except where a merge renames the canonical (section 6). ``

- [x] **Step 2: Write the migration script**

Create `skills/_resources/scripts/migrate_2026_09_03.py`:

```python
#!/usr/bin/env python3
"""One-off migration (2026-09-03): number the directories, add provenance metadata,
canonicalize the Data Source line, fix the broken command reference.
Idempotent: skips files that already carry `metadata:`. Run from the repo root."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("skills")
LIBRARY = "eppc-ads-skills@1.0.0"
UPSTREAM = "trueclicks/claude-plugins google-ads@1.8.0"
REVIEWED = "2026-09-03"

CATEGORY_RANGES = [
    (1, 11, "structure"), (12, 24, "keywords"), (25, 38, "creative"), (39, 52, "bidding"),
    (53, 63, "targeting"), (64, 69, "quality"), (70, 81, "tracking"), (82, 95, "shopping_pmax"),
    (96, 112, "remarketing"), (113, 129, "waste"), (130, 138, "competitive"), (139, 145, "compliance"),
    (146, 152, "seasonal"), (153, 162, "platform"),
]
OPERATIONAL = {49, 122, 123, 124, 125, 130, 145, 146, 147, 149}
ANALYST = {3, 11, 24, 34, 38, 71, 74, 78, 79, 141, 156, 161}
US_ONLY = {58}
EEA_RELEVANT = {72, 73, 75, 156}
RELATED_GROUPS = [
    {44, 123}, {13, 14, 127}, {70, 71, 107, 108, 110, 81}, {34, 69, 78, 79, 125, 141},
    {64, 65, 66, 67}, {121, 135}, {61, 156},
]


def category_for(num: int) -> str:
    for lo, hi, cat in CATEGORY_RANGES:
        if lo <= num <= hi:
            return cat
    raise ValueError(num)


def data_source_for(line: str) -> tuple[str, str]:
    """Return (metadata value, canonical body text) from the raw Data Source line."""
    raw = line.split("**Data Source:**", 1)[1].strip()
    low = raw.lower()
    if any(w in low for w in ("external", "merchant center", "configuration review", "for comparison", "business data")):
        return "external", "External (beyond Google Ads data)"
    if "custom gaql" in low:
        return "custom_gaql", "Custom GAQL Required"
    return "standard", "Standard"


def thresholds_have_numbers(body: str) -> bool:
    m = re.search(r"## Thresholds(.*?)## Output", body, re.S)
    rows = [l for l in (m.group(1) if m else "").split("\n") if l.startswith("|")][2:]
    return any(re.search(r"\d", r.split("|")[1]) for r in rows if len(r.split("|")) > 2)


def kind_for(num: int, data_source: str, body: str) -> str:
    if num in OPERATIONAL:
        return "operational"
    if num in ANALYST or data_source == "external" or not thresholds_have_numbers(body):
        return "analyst"
    return "deterministic"


def markets_for(num: int) -> str:
    if num in US_ONLY:
        return "us_only"
    if num in EEA_RELEVANT:
        return "eea_relevant"
    return "all"


def related_for(num: int, by_number: dict[int, str]) -> list[str]:
    out = []
    for g in RELATED_GROUPS:
        if num in g:
            out += [by_number[n] for n in sorted(g) if n != num and n in by_number]
    return out


def migrate(path: Path, by_number: dict[int, str]) -> None:
    text = path.read_text()
    if "\nmetadata:\n" in text.split("\n---\n", 1)[0] + "\n":
        return
    text = text.replace("/google-ads-get-custom", "/google-ads:get-custom").replace("/google-ads-get`", "/google-ads:get`")
    name = re.search(r"^name:\s*(\S+)", text, re.M).group(1)
    num = int(re.match(r"skill-(\d{3})-", name).group(1))
    ds_line = re.search(r"^\*\*Data Source:\*\*.*$", text, re.M)
    ds_value, ds_text = data_source_for(ds_line.group(0))
    text = text.replace(ds_line.group(0), f"**Data Source:** {ds_text}")
    body = text.split("\n---\n", 1)[1]
    kind = kind_for(num, ds_value, body)
    meta = [
        "metadata:",
        f"  library: {LIBRARY}",
        f"  upstream: {UPSTREAM}",
        f"  upstream_skill: {name}",
        f"  category: {category_for(num)}",
        f"  kind: {kind}",
        f"  data_source: {ds_value}",
    ]
    rel = related_for(num, by_number)
    if rel:
        meta.append(f"  related: [{', '.join(rel)}]")
    meta += [f"  markets: {markets_for(num)}", "  gaql_verified: null", f"  reviewed: {REVIEWED}"]
    text = re.sub(r"^(allowed-tools:.*)$", lambda m: m.group(1) + "\n" + "\n".join(meta), text, count=1, flags=re.M)
    path.write_text(text)


def main() -> int:
    # 1. number the directories (git mv) so dir name == skill name
    by_number: dict[int, str] = {}
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")):
        name = re.search(r"^name:\s*(\S+)", (d / "SKILL.md").read_text(), re.M).group(1)
        by_number[int(re.match(r"skill-(\d{3})-", name).group(1))] = name
        if d.name != name:
            subprocess.run(["git", "mv", str(d), str(ROOT / name)], check=True)
    # 2. rewrite every file
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith("skill-")):
        migrate(d / "SKILL.md", by_number)
    print(f"migrated {len(by_number)} skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 3: Run the migration**

Run: `cd /Users/antonio/nuovo_clientes/google-ads-skills-eppc && python3 skills/_resources/scripts/migrate_2026_09_03.py`
Expected: `migrated 145 skills`; `ls skills | head -3` shows `_resources`, `skill-001-campaign-type-separation`, `skill-002-brand-nonbrand-split`.

- [x] **Step 4: Verify with the lint and greps**

Run:
```bash
python3 skills/_resources/scripts/lint.py --allow-dollars --expect-count 145 | tail -1
grep -rl 'google-ads-get' skills | wc -l
grep -h '^\*\*Data Source' skills/*/SKILL.md | sort | uniq -c
grep -h '^  kind:' skills/*/SKILL.md | sort | uniq -c
```
Expected: `145 skills, 0 errors, 0 warnings`; `0`; exactly three Data Source strings (Standard 61, Custom GAQL Required 77, External 7); kind counts roughly deterministic ≈115, analyst ≈20, operational 10. Spot-check `skills/skill-058-demographic-performance-analysis/SKILL.md` shows `markets: us_only` and `skills/skill-044-monthly-budget-pacing-analysis/SKILL.md` shows `related: [skill-123-budget-pacing-daily-allocation-scripts]`.

- [x] **Step 5: Commit**

```bash
git add -A
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "feat(skills): number directories, add provenance metadata, canonical data source, fix command refs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

### Task 3: Phase 2 — the eight merges

**Files:**
- Create: `skills/MERGES.md`
- Modify (canonical, rewritten): 8 `SKILL.md` files listed below; 4 directory renames
- Delete: 8 absorbed directories

**Interfaces:**
- Consumes: metadata block from Task 2.
- Produces: 137 skill directories; each canonical carries `merged_from`; `MERGES.md` names every absorbed skill (lint check).

General procedure for every merge (the per-merge blocks below give only what changes; everything not mentioned is kept verbatim from the canonical file):

1. `git rm -r skills/<absorbed>`; if the canonical is renamed, `git mv skills/<old> skills/<new>` and update `name:` and the `# Skill NNN:` title line.
2. Frontmatter: replace `description`, add `  merged_from: [<absorbed name>]` right after `data_source`, set `data_source` and the body `**Data Source:**` line as stated.
3. Replace `## Purpose` text, `## Analysis Steps` list and `## Thresholds` table with the blocks given.
4. Keep the canonical `## Data Requirements` and `## Output`, applying only the additions stated.
5. Money literals inside the new thresholds are already parameters; keep `$[X]`-style output placeholders (Task 4 rewrites them globally).

- [x] **Step 1: Merge 121 + 133 → `skill-121-impression-share-loss-analysis`**

```bash
git rm -r -q skills/skill-133-impression-share-loss-analysis
git mv skills/skill-121-impression-share-lost-analysis skills/skill-121-impression-share-loss-analysis
```
Frontmatter: `name: skill-121-impression-share-loss-analysis`; `description: "Segment search impression share lost to budget vs ad rank, quantify the opportunity, and route each campaign to a budget or Quality Score fix."`; `merged_from: [skill-133-impression-share-loss-analysis]`; data_source stays `custom_gaql`. Title: `# Skill 121: Impression Share Loss Analysis`.

Purpose:
```
Split impression-share loss into budget-constrained and rank-constrained causes so optimization effort targets the right root cause. Budget loss on a profitable campaign is missed conversions; rank loss points to Quality Score or bids, not budget. Quantify the opportunity per campaign before recommending spend.
```
Analysis Steps:
```
1. **Fetch impression share data:** Run the GAQL query for search campaigns (IS, budget-lost IS, rank-lost IS, top/absolute-top IS)
2. **Categorize campaigns:** Budget-constrained (budget lost >10%), rank-constrained (rank lost >20%), both (>15% each), or optimized
3. **Calculate opportunity cost:** Missed impressions, clicks and conversions from lost IS using each campaign's CTR and conversion rate
4. **Diagnose root causes:** Budget loss → check exhaustion time and profitability (conversions >= {{min_conversions}}); rank loss → check Quality Score components
5. **Prioritize recommendations:** Rank fixes first (cheaper), then budget increases on profitable campaigns, ordered by recovery value
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| Budget Lost IS > 20% on profitable campaign | Critical |
| Rank Lost IS > 30% | Critical |
| Budget and rank lost > 15% each | Warning |
| Budget Lost IS > 10% | Warning |
| Rank Lost IS > 20% | Warning |
| Any IS loss 5-10% | Info |

Sample size: judge impression share only above {{min_impressions}} impressions in the period.
```
Output: keep 121's; in **Detailed adds** insert as first bullet `- Loss summary by cause (budget / rank / both / optimized) with campaign counts and average loss`.

- [x] **Step 2: Merge 023 + 120 → `skill-023-close-variant-query-expansion-monitoring`**

```bash
git rm -r -q skills/skill-120-close-variant-match-expansion-monitoring
git mv skills/skill-023-close-variant-broad-match-monitoring skills/skill-023-close-variant-query-expansion-monitoring
```
Frontmatter: `name: skill-023-close-variant-query-expansion-monitoring`; `description: "Monitor the queries triggered by broad/phrase expansion and exact/phrase close variants; flag irrelevant spend, same-meaning drift, and converting queries to add as keywords."`; `merged_from: [skill-120-close-variant-match-expansion-monitoring]`; data_source `standard`. Title: `# Skill 023: Close Variant and Query Expansion Monitoring`.

Purpose:
```
Google expands every match type: broad and phrase reach related queries, and exact and phrase also match close variants and "same meaning" rewrites. Map each search term to its triggering keyword, judge relevance, and act: negatives for irrelevant spend, new keywords for converting queries, narrower match types for keywords that mostly trigger drift.
```
Analysis Steps:
```
1. **Map keywords to search terms:** Group search terms by triggering keyword and match type
2. **Classify each term:** Exact query, close variant (misspelling, reorder, plural), same-meaning rewrite, expanded (broad/phrase), or irrelevant
3. **Compare performance by class:** Conversion rate and CPA of exact queries vs variants vs expansions, per keyword
4. **Find negatives:** Irrelevant or zero-conversion terms above the spend floor
5. **Find keyword candidates:** Converting queries not yet keywords (search_term_view.status = NONE)
6. **Find keywords to narrow:** >= 50% of clicks on irrelevant or drifted terms, or an exact keyword taking > 50% of clicks from variants
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| Irrelevant or zero-conversion term, Cost >= {{spend_floor}} | Critical |
| Keyword with >= 50% of clicks on irrelevant terms | Critical |
| "Same meaning" variant with different intent | Warning |
| Variant conversion rate < 50% of exact-query rate | Warning |
| Converting query not added as keyword | Warning |
| Exact keyword with > 50% of clicks from variants | Info |
| Broad keyword triggering 30+ unique queries | Info |

Sample size: compare conversion rates only above {{min_clicks}} clicks per class.
```
Output: keep 023's; in **Detailed adds** insert `- Match analysis table: exact queries vs close variants vs expansions (conversion rate, CPA)`.

- [x] **Step 3: Merge 061 + 104 → `skill-061-customer-match-list-health`**

```bash
git rm -r -q skills/skill-104-customer-match-list-management
git mv skills/skill-061-customer-match-list-freshness skills/skill-061-customer-match-list-health
```
Frontmatter: `name: skill-061-customer-match-list-health`; `description: "Audit Customer Match lists for presence, size, match rate, freshness, and application to campaigns."`; `merged_from: [skill-104-customer-match-list-management]`; data_source `custom_gaql`. Title: `# Skill 061: Customer Match List Health`. Keep `related: [skill-156-first-party-data-collection-activation-strategy]`.

Purpose:
```
Customer Match is the most durable first-party targeting signal. Verify lists exist, are large enough to serve, match well, are refreshed, and are actually applied (targeting, observation, exclusion, or as a lookalike seed). Missing or stale lists silently weaken Smart Bidding and remarketing.
```
Analysis Steps:
```
1. **Fetch CRM-based lists:** Size for search/display, match rate, membership status, eligibility
2. **Evaluate health:** Size, match rate, days since last upload
3. **Check coverage:** All-customers, high-value, recent and lapsed segments exist
4. **Check application:** Which campaigns use each list and in what mode; flag lists applied nowhere
5. **Recommend:** Refresh cadence, segment structure, and where to apply each list
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| No Customer Match lists in account | Critical |
| List size < 500 users | Critical |
| Match rate < 30% | Critical |
| Last updated > 90 days | Critical |
| Match rate 30-50% or list size 500-1,000 | Warning |
| Last updated 30-90 days | Warning |
| List applied to no campaign | Warning |
| No high-value, recent or lapsed segment | Info |
```
Output: keep 061's; change the header line to `**Account:** [Name] | **Lists Analyzed:** [X] | **Applied:** [Y] | **Issues:** [Z]`; in **Detailed adds** append `- Recommended list structure (all, high-value, recent, lapsed) and compliance checklist`.

- [x] **Step 4: Merge 037 + 139 → `skill-037-ad-disapproval-monitoring`**

```bash
git rm -r -q skills/skill-139-ad-disapproval-monitoring
git mv skills/skill-037-ad-disapproval-limited-eligibility skills/skill-037-ad-disapproval-monitoring
```
Frontmatter: `name: skill-037-ad-disapproval-monitoring`; `description: "Find disapproved, limited, and under-review ads, prioritize by business impact (silenced ad groups, high-spend campaigns), and provide a resolution workflow."`; `merged_from: [skill-139-ad-disapproval-monitoring]`; `data_source: custom_gaql`; body line `**Data Source:** Custom GAQL Required` followed by the sentence `Standard ads.md gives approval status; policy topic entries need the GAQL query.` Title: `# Skill 037: Ad Disapproval Monitoring`.

Purpose:
```
Disapproved ads stop serving; limited ads serve in restricted contexts; ads stuck under review deliver nothing. Find every non-approved ad, extract the policy topic, size the impact (silenced ad groups, spend at risk), and order the fixes.
```
Analysis Steps:
```
1. **Categorize by approval status:** Approved, Approved Limited, Area of Interest Only, Disapproved, Under Review
2. **Extract policy topics:** For every non-approved ad; group repeated violations
3. **Assess impact:** Ad groups with 0 approved ads (silenced), high-spend campaigns affected, share of ads disapproved
4. **Prioritize resolution:** Silenced ad groups → high-spend campaigns → repeated violations → editorial quick fixes
5. **Plan remediation:** Fix or replace, appeal if wrong, keep 2-3 approved ads per ad group
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| Ad group with 0 approved ads | Critical |
| > 10% of ads disapproved | Critical |
| Disapproved ad in a campaign above {{spend_significant}}/30d | Critical |
| Any disapproved ad | Warning |
| Multiple ads with the same policy violation | Warning |
| Ad under review > 7 days | Warning |
| Limited eligibility or regional limitation affecting reach | Info |
| Ad under review 3-7 days | Info |
```
Output: keep 037's; in **Detailed adds** append `- Resolution workflow by policy type, appeal guidance, prevention checklist`.

- [x] **Step 5: Merge 016 + 113 → `skill-016-negative-keyword-list-completeness`**

```bash
git rm -r -q skills/skill-113-proactive-negative-keyword-list-building
```
Frontmatter: `description: "Verify shared negative lists exist, cover the universal waste categories, are applied to every campaign, and are backed by search-term evidence."`; `merged_from: [skill-113-proactive-negative-keyword-list-building]`; data_source `standard`.

Purpose:
```
Shared negative lists are the cheapest waste prevention: build them proactively for universal waste (jobs, free, DIY, research, competitors), apply them everywhere, then confirm with search terms that nothing leaks through.
```
Data Requirements: keep 016's block and, after its `Reference GAQL` block, add a second block titled `**Reference GAQL (search terms):**` containing 113's `search_term_view` query verbatim.

Analysis Steps:
```
1. **Inventory existing lists:** Names, keyword counts, campaign assignments
2. **Check universal categories:** Jobs/careers, free/DIY/tutorial, research/informational, support/login, competitor terms
3. **Verify application:** Every active Search and Shopping campaign has the universal list
4. **Gap analysis:** Search terms with waste patterns not blocked; high-spend zero-conversion terms
5. **Assess match types:** Phrase preferred; flag broad negatives (over-blocking risk)
6. **Recommend:** Universal (shared) vs campaign-specific negatives, with terms and match types
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| No shared negative lists exist | Critical |
| Universal waste category not covered (jobs, free/DIY, research, support) | Warning |
| Shared list not applied to all campaigns | Warning |
| Waste terms found in search terms not blocked | Warning |
| Zero-conversion terms with Cost >= {{spend_floor}} not blocked | Warning |
| Broad match negatives present | Info |
| < 50 negative keywords in total | Info |
```
Output: keep 016's; change the header line to `**Account:** [Name] | **Shared Lists:** [X] | **Total Negatives:** [Y] | **Gaps:** [Z]`; in **Detailed** adds append `- Recommended universal list with match types`.

- [x] **Step 6: Merge 064 + 129 → `skill-064-quality-score-distribution-analysis`**

```bash
git rm -r -q skills/skill-129-quality-score-monitoring-alert-rules
```
Frontmatter: `description: "Monitor Quality Score distribution, flag high-spend low-QS keywords with their weak component, and recommend monitoring alerts."`; `merged_from: [skill-129-quality-score-monitoring-alert-rules]`; data_source `standard`.

Purpose:
```
Low Quality Scores raise CPCs and lower positions. Measure the distribution and impression-weighted average, isolate high-spend keywords at QS 1-5 with the component that drags them (expected CTR, ad relevance, landing page), quantify the spend exposed, and propose alert rules so regressions surface without a manual audit.
```
Analysis Steps:
```
1. **Load keyword QS data:** Quality Score and the three components per enabled keyword
2. **Calculate distribution:** Keywords by bucket (1-3, 4-5, 6-7, 8-10, N/A) and impression-weighted average (target > 6)
3. **Flag high-spend low QS:** Cost >= {{spend_significant}} at QS 1-3; Cost >= {{spend_material}} at QS 4-5
4. **Identify the weak component:** For every flagged keyword, which component is Below Average
5. **Quantify exposure:** Spend on QS 1-3 keywords as a share of total spend
6. **Recommend alert rules:** QS <= 3 with impressions > {{min_impressions}}; QS drop of 2+ points (operational follow-up)
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| Keyword QS 1-3 with Cost > {{spend_significant}}/30d | Critical |
| Keyword QS 1-3 with Impressions > {{min_impressions}} | Critical |
| > 20% of keywords have QS 1-3 | Critical |
| Weighted average QS < 5 | Critical |
| Keyword QS 4-5 with Cost > {{spend_material}}/30d | Warning |
| Any component Below Average on a keyword above {{spend_significant}}/30d | Warning |
| Weighted average QS 5-6 | Warning |
| QS dropped 2+ points vs previous snapshot (when history is available) | Warning |
```
Output: keep 064's; in **Detailed adds** append `- Spend on low-QS keywords by bucket` and `- Recommended alert rules (Google Ads automated rules configuration)`.

- [x] **Step 7: Merge 054 + 055 → `skill-054-geographic-performance-analysis`**

```bash
git rm -r -q skills/skill-055-underperforming-location-exclusion
```
Frontmatter: `description: "Analyze performance by location, recommend bid adjustments for strong and weak areas, and quantify exclusion candidates with zero or very poor conversion."`; `merged_from: [skill-055-underperforming-location-exclusion]`; data_source `custom_gaql`.

Purpose:
```
Geographic performance varies widely. Compare each location to the account average, propose bid adjustments where volume supports it, and exclude locations that spend without converting or sit outside the service area. Quantify waste and projected savings so exclusions are defensible.
```
Data Requirements: keep 054's; after `Run via ...` add the line `For the exclusion pass, filter to `metrics.cost_micros > 0` and load current exclusions from `bid_adjustments.md`.`

Analysis Steps:
```
1. **Fetch location performance:** Custom GAQL plus current bid modifiers and exclusions
2. **Compute per-location metrics:** CPA, conversion rate, ROAS, cost share, conversion share vs account average
3. **Bid increases:** CPA well below average with >= {{min_conversions}} conversions
4. **Bid decreases:** CPA well above average with >= {{min_clicks}} clicks
5. **Exclusions:** Zero conversions above the spend floor, CPA > 3x average, CVR < 0.5x average with >= {{min_clicks}} clicks, outside the service area
6. **Quantify and prioritize:** 30-day waste, projected annual savings, high/medium/low priority
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| Location outside service area with any spend | Critical (exclude) |
| Zero conversions with Cost > {{spend_significant}} | Critical (exclude) |
| CPA 40%+ below average with >= {{min_conversions}} conversions | Critical (increase bid) |
| CPA > 3x account average with >= {{min_clicks}} clicks | High (exclude) |
| Zero conversions with Cost {{spend_floor}} to {{spend_significant}} | High (exclude) |
| CPA 50%+ above average | High (decrease bid) |
| CPA 20-40% below or 30-50% above average | Warning (moderate adjustment) |
| CVR < 0.5x average with >= {{min_clicks}} clicks | Warning |
```
Output: keep 054's; after the header line add `**Current Waste:** $[X]/month | **Projected Annual Savings:** $[Y]`; in **Detailed adds** append `- Low priority review table (borderline cases to monitor)`.

- [x] **Step 8: Merge 029 + 126 → `skill-029-rsa-asset-performance-analysis`**

```bash
git rm -r -q skills/skill-126-rsa-asset-performance-bulk-analysis
```
Frontmatter: `description: "Rate RSA headlines and descriptions account-wide using Google's asset performance labels and ad-level metrics; replace Low assets with patterns from Best ones."`; `merged_from: [skill-126-rsa-asset-performance-bulk-analysis]`; data_source `custom_gaql`.

Purpose:
```
Google labels each RSA asset Best, Good, Low, or Learning. Aggregate labels and ad-level performance across the account to find assets to replace, patterns to replicate, and ads whose strength or pinning limits combinations.
```
Data Requirements: keep 029's; add `**Standard Data:**` bullet `` - `data/account/campaigns/*/*/ads.md` - RSA headlines, descriptions, ad strength `` before the GAQL, and after 029's query add a second block `**GAQL Query (ad-level metrics):**` containing 126's `ad_group_ad` query verbatim, followed by `Run via `/google-ads:get-custom` with query name `rsa_ad_performance`.`

Analysis Steps:
```
1. **Fetch asset labels and ad metrics:** Asset view for labels; ad_group_ad for RSA-level impressions, CTR, conversions, ad strength
2. **Categorize assets by label:** Best (replicate), Good (keep), Low (replace), Learning (wait), Unrated
3. **Aggregate across ads:** Assets reused in many ads; account-wide top and bottom performers
4. **Analyze patterns:** What Best assets share (benefit, CTA, length) that Low assets lack
5. **Flag ads:** Poor strength with spend, multiple Low assets, no Best headline, heavy pinning
6. **Generate replacements:** Based on Best patterns, keeping headline diversity
```
Thresholds:
```
| Condition | Severity |
|-----------|----------|
| > 20% of assets rated Low | Critical |
| Low asset in a campaign above {{spend_significant}}/30d | Critical |
| Ad strength Poor with spend above {{spend_significant}}/30d | Critical |
| Multiple Low assets in one ad | Warning |
| Any asset rated Low | Warning |
| No Best-rated headline in an RSA | Warning |
| Heavy pinning (3+ pins) reducing combinations | Info |
| All assets Learning (new RSA, < {{min_impressions}} impressions) | Info |
```
Output: keep 029's; in **Detailed adds** append `- Ad strength distribution and top-performing headlines account-wide` and `- Pinning strategy assessment`.

- [x] **Step 9: Write `skills/MERGES.md`**

```markdown
# Merges (2026-09-03)

Eight upstream skills checked the same condition on the same data as another skill. Each pair became one canonical skill; the absorbed skill's directory was removed. `metadata.merged_from` on the canonical records the absorbed name; `metadata.upstream_skill` keeps the canonical's original upstream name.

| Canonical | Absorbed | Why |
|---|---|---|
| skill-121-impression-share-loss-analysis | skill-133-impression-share-loss-analysis | Identical GAQL and thresholds on search IS lost to budget vs rank |
| skill-023-close-variant-query-expansion-monitoring | skill-120-close-variant-match-expansion-monitoring | Same search-term-to-keyword mapping; one covered broad/phrase expansion, the other exact/phrase close variants |
| skill-061-customer-match-list-health | skill-104-customer-match-list-management | Same `user_list` query; freshness vs coverage were two halves of one check |
| skill-037-ad-disapproval-monitoring | skill-139-ad-disapproval-monitoring | Same `ad_group_ad.policy_summary` data; monitoring vs resolution workflow |
| skill-016-negative-keyword-list-completeness | skill-113-proactive-negative-keyword-list-building | Same shared-list inventory and universal waste categories |
| skill-064-quality-score-distribution-analysis | skill-129-quality-score-monitoring-alert-rules | Same QS distribution; 129 added alert rules, now one operational step in 064 |
| skill-054-geographic-performance-analysis | skill-055-underperforming-location-exclusion | Same `geographic_view` query; exclusion is the low-performer branch of the analysis |
| skill-029-rsa-asset-performance-analysis | skill-126-rsa-asset-performance-bulk-analysis | Same asset performance labels; 126 added ad-level metrics, now a second query in 029 |

## Threshold reconciliation notes

- **121/133:** 133's "any IS loss > 10%: Info" conflicted with 121's "budget lost > 10%: Warning"; the stricter Warning was kept and 133's "both > 15%: Warning" row added.
- **023/120:** the two `$50` zero-conversion rows became one row on `{{spend_floor}}`.
- **061/104:** 104's "not updated > 90 days: Warning" became Critical (061's severity). 104's "< 1,000 users: Warning" and 061's "500-1,000: Warning" merged into one row.
- **037/139:** "under review" reconciled to Info at 3-7 days and Warning above 7 days. 139's "high-spend campaign" became `{{spend_significant}}`.
- **016/113:** 113's "high-spend zero-conversion terms" got the explicit `{{spend_floor}}` threshold.
- **064/129:** 129's `$50` floor folded into 064's `{{spend_significant}}` row; 129's "QS dropped 2+ points" kept with the note that it needs a previous snapshot.
- **054/055:** "outside service area" raised from High to Critical (it is pure waste). 055's two zero-conversion rows became `{{spend_significant}}` (Critical) and `{{spend_floor}}` to `{{spend_significant}}` (High). Upstream's four-level severity (High) was kept where it existed.
- **029/126:** 126's "Poor strength with significant spend" got `{{spend_significant}}`; "All assets Learning" got `{{min_impressions}}`.

## Reviewed and kept separate

Linked with `metadata.related` instead: 044/123 (monthly pacing vs day-of-week allocation), 013/014/127 (keyword mining, negative mining, trend detection), the conversion-tracking cluster (070, 071, 081, 107, 108, 110), the landing-page cluster (034, 069, 078, 079, 125, 141), and 064/065/066/067 (Quality Score facets).
```

- [x] **Step 10: Verify**

Run:
```bash
ls -d skills/skill-* | wc -l
python3 skills/_resources/scripts/lint.py --allow-dollars | tail -1
grep -l 'merged_from' skills/*/SKILL.md | wc -l
```
Expected: `137`; `137 skills, 0 errors, 0 warnings`; `8`. Open each of the 8 canonical files and confirm the title, name, five sections, and that no `## ` heading was lost.

- [x] **Step 11: Commit**

```bash
git add -A
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "feat(skills): merge 8 duplicate pairs into canonical skills (145 -> 137), document in MERGES.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

### Task 4: Phase 3 — parameters replace every dollar literal

**Files:**
- Create: `skills/_resources/PARAMETERS.md`
- Create: `skills/_resources/scripts/parametrize_2026_09_03.py` (one-off)
- Modify: the skills listed in the mapping plus every file containing `$[`

**Interfaces:**
- Consumes: lint check 4 and 6.
- Produces: `PARAMETERS.md` whose first table column defines every `{{name}}`; no `$<digit>` left in `skills/`.

- [x] **Step 1: Write PARAMETERS.md**

```markdown
# Parameters

Every monetary or sample-size threshold in the skills is a named parameter written as `{{name}}`. Defaults are in EUR and are floors: the spend-relative formula wins when it is larger. A client profile (`_resources/CLIENT_PROFILE.md`) may override any default.

| Parameter | Default | Definition |
|---|---|---|
| `{{spend_floor}}` | 50 | max(50 {{currency}}, 1 × target CPA). Minimum spend before a zero-conversion entity is flagged. |
| `{{spend_significant}}` | 100 | max(100 {{currency}}, 2 × target CPA). Spend that makes a problem worth a Warning or Critical. |
| `{{spend_material}}` | 200 | max(200 {{currency}}, 3 × target CPA). Spend that makes a weaker signal (QS 4-5, demographics, devices) actionable. |
| `{{spend_high}}` | 500 | max(500 {{currency}}, 5 × target CPA, 5% of 30-day account spend). Spend that makes a Quality Score component or placement class Critical. |
| `{{monthly_spend_significant}}` | 1000 | max(1000 {{currency}}, 10% of 30-day account spend). A campaign large enough to need audiences and allocation review. |
| `{{monthly_spend_large}}` | 5000 | max(5000 {{currency}}, 25% of 30-day account spend). A campaign whose bidding migration is urgent. |
| `{{min_clicks}}` | 100 | Minimum clicks before judging a rate (CTR, conversion rate). |
| `{{min_impressions}}` | 1000 | Minimum impressions before judging CTR or impression share. |
| `{{min_conversions}}` | 15 | Minimum conversions before comparing CPA or ROAS against an average or target. |
| `{{currency}}` | account currency | Always read from `customer.currency_code` (or the export's account summary). Never assumed. |

## Rules

- **Target CPA** is the campaign's target if set, else the account-level target from the client profile, else absent (the EUR floor applies).
- **30-day account spend** is the sum of `metrics.cost_micros` over the report's date range, converted to currency units (divide by 1,000,000).
- **Placeholder-value checks** are written as "valued at exactly 1 {{currency}}"; zero-value checks as "zero value". Never as `$1` or `$0`.
- **Rate-based conditions** (CTR, CVR, CPA vs average, ROAS) apply only above `{{min_clicks}}` clicks, and CPA/ROAS comparisons only above `{{min_conversions}}` conversions. Below that, the skill reports "insufficient sample" as Info, never Critical.
- **Report values** are always written in `{{currency}}` with the ISO code or symbol of the account (EUR → €), formatted for `report_language`.
- **Overrides** come from the client profile `parameter_overrides` map, keyed by parameter name without braces.
```

- [x] **Step 2: Write the parametrization script**

Create `skills/_resources/scripts/parametrize_2026_09_03.py`:

```python
#!/usr/bin/env python3
"""One-off (2026-09-03): replace dollar literals with {{parameters}}, rewrite $[X]
placeholders as {{currency}} [X], and add the sample-size note to rate-based skills.
Run from the repo root after the merges. Idempotent."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("skills")

# (skill dir, old substring, new substring). Exact, one occurrence each unless noted.
REPLACEMENTS = [
    ("skill-117-ad-schedule-waste-analysis", ">$100 spend", ">{{spend_significant}} spend"),
    ("skill-057-ad-schedule-optimization", ">$100 spend", ">{{spend_significant}} spend"),
    ("skill-068-ad-relevance-gap-identification", "Cost > $200/30d", "Cost > {{spend_material}}/30d"),
    ("skill-059-audience-observation-mode-setup", ">$1000/mo spend", ">{{monthly_spend_significant}}/mo spend"),
    ("skill-107-conversion-value-accuracy", "All conversions valued at $1 (placeholder)", "All conversions valued at exactly 1 {{currency}} (placeholder)"),
    ("skill-107-conversion-value-accuracy", "All conversions at $1", "All conversions at exactly 1 {{currency}}"),
    ("skill-039-bid-strategy-appropriateness-audit", "$0 conversion values", "zero conversion values"),
    ("skill-045-budget-allocation-optimization", ">$1000 spend", ">{{monthly_spend_significant}} spend"),
    ("skill-006-display-network-optin", ">$50 spend", ">{{spend_floor}} spend"),
    ("skill-067-expected-ctr-improvement", "Cost > $500/30d", "Cost > {{spend_high}}/30d"),
    ("skill-052-conversion-value-based-bidding", "with $0 value", "with zero value"),
    ("skill-052-conversion-value-based-bidding", "$0 value assigned → Set value to $[X]", "zero value assigned → Set value to {{currency}} [X]"),
    ("skill-115-display-youtube-placement-performance-review", ">$100 spend", ">{{spend_significant}} spend"),
    ("skill-058-demographic-performance-analysis", ">$200 spend", ">{{spend_material}} spend"),
    ("skill-056-device-performance-analysis", ">$200 spend", ">{{spend_material}} spend"),
    ("skill-020-low-performing-keyword-pruning", "or fixed $50 minimum", "or {{spend_floor}} minimum"),
    ("skill-020-low-performing-keyword-pruning", "Cost >= $100", "Cost >= {{spend_significant}}"),
    ("skill-047-enhanced-cpc-deprecation-migration-check", ">$5000/month spend", ">{{monthly_spend_large}}/month spend"),
    ("skill-015-ngram-analysis", "Cost >= $50 AND Conversions = 0", "Cost >= {{spend_floor}} AND Conversions = 0"),
    ("skill-015-ngram-analysis", "N-gram Cost >= $100 AND Conv = 0", "N-gram Cost >= {{spend_significant}} AND Conv = 0"),
    ("skill-015-ngram-analysis", "N-gram Cost >= $50 AND Conv = 0", "N-gram Cost >= {{spend_floor}} AND Conv = 0"),
    ("skill-092-pmax-final-url-expansion-control", ">$100 spend", ">{{spend_significant}} spend"),
    ("skill-069-landing-page-experience-assessment", "Cost > $500/30d", "Cost > {{spend_high}}/30d"),
    ("skill-116-mobile-app-placement-exclusion", ">$500/month on mobile apps", ">{{spend_high}}/month on mobile apps"),
    ("skill-014-search-term-mining-negatives", "or $20 minimum", "or {{spend_floor}} minimum"),
    ("skill-005-search-partners-performance", ">$100 spend", ">{{spend_significant}} spend"),
]
RATE_WORDS = re.compile(r"\b(CTR|CVR|conversion rate|CPA|ROAS)\b", re.I)
NOTE = (
    "\nSample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, "
    "and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "
    "\"insufficient sample\" as Info.\n"
)


def main() -> int:
    missing = []
    for skill, old, new in REPLACEMENTS:
        p = ROOT / skill / "SKILL.md"
        t = p.read_text()
        if old in t:
            p.write_text(t.replace(old, new))
        elif new not in t:
            missing.append((skill, old))
    changed = 0
    for p in sorted(ROOT.glob("skill-*/SKILL.md")):
        t = p.read_text()
        new = re.sub(r"\$(?=\[)", "{{currency}} ", t)
        m = re.search(r"(## Thresholds\n)(.*?)(\n## Output)", new, re.S)
        if m and RATE_WORDS.search(m.group(2)) and "Sample size:" not in m.group(2):
            table = m.group(2).rstrip("\n")
            new = new[: m.start(2)] + table + "\n" + NOTE + new[m.end(2):]
        if new != t:
            p.write_text(new)
            changed += 1
    print(f"changed {changed} files")
    for skill, old in missing:
        print(f"MISSING {skill}: {old!r}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 3: Run it and verify**

Run:
```bash
python3 skills/_resources/scripts/parametrize_2026_09_03.py
grep -rnE '\$[0-9]' skills/skill-*/SKILL.md | wc -l
grep -rn '\$' skills/skill-*/SKILL.md | grep -v '{{currency}}' | head
python3 skills/_resources/scripts/lint.py | tail -1
```
Expected: `changed N files` with no `MISSING` lines; `0`; the second grep shows only lines where `$` is not a money literal (expected: none, or `$` inside GAQL comments — inspect and fix by hand if any); `137 skills, 0 errors, 0 warnings`.

- [x] **Step 4: Commit**

```bash
git add -A
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "feat(skills): parametric thresholds in account currency, sample-size rule, PARAMETERS.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

### Task 5: Phase 4 — output templates, client profile, schema

**Files:**
- Create: `skills/_resources/OUTPUT_TEMPLATES.md`
- Create: `skills/_resources/CLIENT_PROFILE.md`
- Modify: `skills/_resources/SKILL_SCHEMA.md`
- Modify: `skills/_resources/SKILL_EXAMPLE.md`
- Modify: `skills/_resources/README.md` (one banner line)

- [x] **Step 1: Write OUTPUT_TEMPLATES.md**

```markdown
# Output templates

Skill bodies stay in English. The report is written in the client's `report_language` (`it` or `en`). Every report starts with the header block; every finding line names the skill that produced it. Never report the same entity and condition twice across related skills: the more specific skill wins.

## Header (both languages, always first)

```
## <Skill title> — <Account name>
Account <id> · currency <CUR> · data <date range> · snapshot <YYYY-MM-DD>
Library eppc-ads-skills@1.0.0 · skill <skill-id> (upstream <upstream_skill>@1.8.0) · profile <client slug or "defaults">
```

## Short — English (default)

```
<header>

### Critical (<n>)
- **<Entity>**: <issue> → <fix> · <skill-id>

### Warnings (<n>)
- **<Entity>**: <issue> → <fix> · <skill-id>

### Info (<n>)
- **<Entity>**: <note> · <skill-id>

### Recommendations
1. <priority action> (<estimated impact in CUR>)
2. <secondary action>
```

Other report languages (for example `it`) are translated from the English templates at render time.

## Detailed — English

```
<header>

### What was checked
- <aspect>

### Critical issues (<n>)
1. **<Entity>**: <issue> · <skill-id>
   - Impact: <what it causes, in CUR where possible>
   - Evidence: <data, with the parameter values used, e.g. spend_significant = 120 EUR>
   - Fix: <specific action>

### Warnings (<n>)
1. **<Entity>**: <issue> · <skill-id>
   - Fix: <specific action>

### Summary
| Metric | Value |
|--------|-------|
| Entities analyzed | <n> |
| Issues found | <n> |
| Critical | <n> |
| Warnings | <n> |
| Insufficient sample (skipped) | <n> |

### Recommendations
1. **<priority action>** — <rationale>
```

Other report languages are translated at render time.

## No issues

English: `No issues found. <n> entities pass the audit criteria.` (other report languages are translated at render time) The header block is still required.

## Rules

1. Never list passed entities individually.
2. Group by severity: Critical → Warnings → Info.
3. Name the exact entity (campaign, ad group, keyword, list).
4. Every issue carries a fix and the skill id.
5. Quantify impact in the account currency; state the parameter values used when a threshold was parametric.
6. Rate-based judgments below `{{min_clicks}}` / `{{min_conversions}}` go under "Insufficient sample", as Info.
7. No educational content.
```

- [x] **Step 2: Write CLIENT_PROFILE.md**

```markdown
# Client profile

The front desk reads `ads/profile.yaml` from the client repository when it exists, otherwise it asks for these values before running any skill. Nothing here is sent anywhere.

```yaml
slug: eppcdigital                 # client identifier
report_language: it               # it | en
market: [IT]                      # ISO country codes the account serves; drives EEA rules and us_only skips
currency_override: null           # normally null: currency comes from the account (customer.currency_code)
target_cpa: null                  # account-level target CPA in account currency, if the client has one
target_roas: null                 # account-level target ROAS, if the client has one
monthly_spend: null               # typical 30-day spend in account currency; computed from the export when null
brand_terms: []                   # brand and product names, for brand/non-brand skills
data_source: ui_export            # ui_export | plugin_export (plugin_export requires dpa_signed: true)
dpa_signed: false                 # data-processing agreement covering TrueClicks' hosted API
parameter_overrides: {}           # e.g. { spend_floor: 30, min_conversions: 10 }
```

Rules:

- `data_source: plugin_export` with `dpa_signed: false` is refused by the front desk.
- If any `market` is in the EEA, the tracking workflow always includes skill-075 (Consent Mode v2) and skills marked `markets: us_only` skip their US-only sections.
- `parameter_overrides` keys are parameter names from `PARAMETERS.md` without braces.
```

- [x] **Step 3: Update SKILL_SCHEMA.md**

Apply these edits:

1. Under `## SKILL.md Structure`, replace the frontmatter code block with:
```yaml
---
name: skill-XXX-descriptive-name
description: "One-line description of what this skill checks."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-XXX-descriptive-name     # exact upstream name
  category: keywords                             # from the category table below
  kind: deterministic                            # deterministic | analyst | operational
  data_source: standard                          # standard | custom_gaql | external
  merged_from: []                                # optional: absorbed upstream skills (see MERGES.md)
  related: []                                    # optional: skills covering adjacent facets
  markets: all                                   # all | us_only | eea_relevant
  gaql_verified: null                            # API version the queries were checked against, or null
  reviewed: 2026-09-03
---
```
   and add after it: `Directory name equals `name`. `_resources/scripts/lint.py` enforces this block.`
2. In `#### 3. Data Requirements`, replace the `**Data Source Values:**` list with:
```
- `Standard` - The `/google-ads:get` export contains all required data (`metadata.data_source: standard`)
- `Custom GAQL Required` - Must run `/google-ads:get-custom` (`custom_gaql`)
- `External (beyond Google Ads data)` - Needs data outside Google Ads: site tests, CRM, Merchant Center, configuration review (`external`)
```
   and replace every `/google-ads-get-custom` and `/google-ads-get` in the file with `/google-ads:get-custom` and `/google-ads:get`.
3. In `#### 5. Thresholds`, append after the bullet list:
```
- Money thresholds are parameters from `PARAMETERS.md`, written `{{spend_floor}}` etc. Never a currency literal.
- Rate-based rows get the sample-size note (`Sample size: ...`) after the table.
```
4. Rename `#### 6. Output Schema` to `#### 6. Output` and change the code block heading `## Output Schema` to `## Output`. Replace the section's bullets with:
```
- Short by default, Detailed on request; both rendered from `OUTPUT_TEMPLATES.md` in the client's `report_language`
- Every report starts with the provenance header; every finding names the skill id
- Never show "OK" or "Pass" items
```
5. In `## OUTPUT Schema (What Claude Should Report)`, insert at the top: `The canonical templates, in English (other report languages are translated at render time), live in `OUTPUT_TEMPLATES.md`; the examples below are the English short/detailed forms.` Replace every `$` money literal in the examples (`$[X]`) with `{{currency}} [X]`.
6. Add a new section before `## Skill Categories`:
```
## Kinds

| Kind | Meaning | How it runs |
|---|---|---|
| deterministic | Thresholds computable from Google Ads data | Run as a check; findings follow the table |
| analyst | Needs external data or judgment (CRM, site tests, intent, naming) | Run as guided analysis; state assumptions in Evidence |
| operational | Deliverable is a configuration to deploy (rule, script, alert, schedule) | Run only when the user asks for automation; output is a proposal, never applied |
```
7. In `## Skill Categories`, change the table header note to `Category keys used in `metadata.category`:` and add a key column: structure, keywords, creative, bidding, targeting, quality, tracking, shopping_pmax, remarketing (096-112), waste, competitive, compliance, seasonal, platform. Add a line: `17 upstream numbers are absent (084, 086, 087, 091, 096, 097, 132, 134, 138, 140, 143, 144, 153-155, 157, 158) and 8 more were merged (see MERGES.md).`

- [x] **Step 4: Update SKILL_EXAMPLE.md**

In the "After" example: add the `metadata` block from Step 3 (with `name: skill-030-ad-extension-coverage-audit`, `category: creative`, `kind: deterministic`, `data_source: standard`), replace `/google-ads-get-custom` with `/google-ads:get-custom`, rename `## Output Schema` to `## Output`, and prefix the "Output Example" with the provenance header:
```
## Ad Extension Coverage Audit — TrueClicks - Dev Test
Account 123-456-7890 · currency EUR · data LAST_30_DAYS · snapshot 2026-09-03
Library eppc-ads-skills@1.0.0 · skill skill-030-ad-extension-coverage-audit (upstream skill-030-ad-extension-coverage-audit@1.8.0) · profile defaults
```

- [x] **Step 5: Mark the upstream README and commands as upstream**

Prepend to `skills/_resources/README.md`: `> Upstream document from TrueClicks google-ads@1.8.0, kept for reference. The commands under `commands/` call TrueClicks' hosted API (api.claudeppc.ai): use them only for a client with a signed DPA (see the root README).` Leave `commands/*.md` untouched.

- [x] **Step 6: Verify and commit**

Run: `python3 skills/_resources/scripts/lint.py | tail -1 && grep -c 'google-ads-get' skills/_resources/SKILL_SCHEMA.md skills/_resources/SKILL_EXAMPLE.md`
Expected: `137 skills, 0 errors, 0 warnings`; both counts `0`.

```bash
git add -A
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "feat(resources): bilingual output templates with provenance header, client profile, schema update

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

### Task 6: Phase 5 — rewrite the front desk

**Files:**
- Modify: `ads/SKILL.md` (full replacement)

- [x] **Step 1: Replace `ads/SKILL.md` with**

````markdown
---
name: ads
description: >
  Front desk for Google Ads audits. Use for ANY Google Ads work — account audit,
  structure/keyword/bidding/budget review, conversion tracking, Quality Score,
  Shopping/PMax, audiences/geo/device, compliance/disapprovals, seasonality,
  wasted-spend hunting, "why did CPA/ROAS change", or a campaign launch review —
  including vague requests ("check the Google Ads account", "where am I wasting
  budget", "audit ads", "check the tracking"). Routes the request to the
  skills in this library and enforces its operating rules.
metadata:
  library: eppc-ads-skills@1.0.0
  author: smartweb
  version: "2.0"
  category: engine-frontdesk
---

# Ads front desk

This library holds **137 Google Ads audit skills** under `skills/` (curated from
TrueClicks google-ads@1.8.0; see `README.md`, `skills/CATALOG.md`, `skills/MERGES.md`).
Each skill is a Markdown recipe: data required, analysis steps, thresholds, output.
You run them by reading the client's export and following the recipe. Nothing here
executes changes in Google Ads.

## Operating rules (non-negotiable)

1. **Recommend only.** Every output is a recommendation with a fix. Never apply,
   never write `pending_changes.json`, never call an execute or validate command.
2. **Data intake.** Accept a manual Google Ads UI/Editor export (CSV/TSV) or a
   `/google-ads:get` export directory. `/google-ads:get` and `/google-ads:get-custom`
   send account data to TrueClicks' hosted API: use them **only** when the client
   profile says `dpa_signed: true`. Never send account data anywhere else.
3. **Client profile first.** Read `ads/profile.yaml` (template:
   `skills/_resources/CLIENT_PROFILE.md`). If missing, ask for `report_language`,
   `market`, `target_cpa`/`target_roas`, `brand_terms`, `data_source`, `dpa_signed`.
4. **Currency from the account**, never assumed. Parameters (`skills/_resources/PARAMETERS.md`)
   resolve against target CPA and 30-day spend; state the resolved values in Evidence.
5. **Language.** Write the report in `report_language` using
   `skills/_resources/OUTPUT_TEMPLATES.md`. Skill bodies stay in English.
6. **Provenance.** Every report starts with the header block; every finding names
   its skill id. Never fabricate metrics; if data is missing, say which skill was skipped and why.
7. **No double reporting.** Related skills (`metadata.related`) may see the same
   entity; report it once under the more specific skill.
8. **EEA accounts.** If any `market` is in the EEA, the tracking workflow always
   includes skill-075 (Consent Mode v2); skills marked `markets: us_only` skip their US-only sections.
9. **Kinds.** Run `deterministic` skills as checks and `analyst` skills as guided
   analysis. Run `operational` skills only when the user asks for automation, and
   present their output as a proposal.
10. **Sample size.** Below `{{min_clicks}}` / `{{min_conversions}}`, rate-based
    findings go under "Insufficient sample" as Info.

## Routing

Pick the preset that matches the request; for a vague request run **Full audit**.
Skill ids are directory names under `skills/` (`skill-NNN-…`); `skills/CATALOG.md`
lists kind and data source for each.

| Request | Preset | Skills |
|---|---|---|
| "audit", "check the account", anything vague | Full audit | Every skill with `kind` ≠ operational, in category order (structure → keywords → creative → bidding → targeting → quality → tracking → shopping_pmax → remarketing → waste → competitive → compliance → seasonal → platform) |
| "wasted spend", "where am I throwing budget away", waste | Waste | 005, 006, 013, 014, 015, 020, 023, 054, 056, 057, 114, 115, 116, 117, 118, 119, 121 |
| search terms, query | Search terms | 013, 014, 015, 023, 127 |
| keyword hygiene, match types, negatives | Keyword hygiene | 004, 012, 016, 017, 018, 019, 020, 021, 022, 024 |
| ads, RSA, creatives, extensions | Creative | 025, 026, 027, 028, 029, 030, 031, 032, 033, 034, 035, 036, 037, 038 |
| budget, bidding, target CPA/ROAS, pacing | Budget and bidding | 039, 040, 041, 042, 043, 044, 045, 046, 047, 048, 050, 051, 052, 121 |
| tracking, conversions, tag, consent | Tracking | 070, 071, 072, 073, 074, 075, 076, 077, 078, 079, 080, 081, 106, 107, 108, 109, 110, 111, 112 |
| Shopping, feed, PMax | PMax and Shopping | 082, 083, 085, 088, 089, 090, 092, 093, 094, 095, 128 |
| audience, geo, device, remarketing | Audience, geo, device | 053, 054, 056, 057, 058, 059, 060, 061, 062, 063, 098, 099, 100, 101, 102, 103, 105 |
| Quality Score, landing page | Quality Score | 064, 065, 066, 067, 068, 069 |
| account structure, naming, settings | Structure | 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011 |
| seasonality, peaks, Black Friday | Seasonality | 137, 148, 150, 151, 152 (+ operational 146, 147, 149 on request) |
| policy, disapprovals, trademark | Compliance | 037, 141, 142 (+ operational 145 before a launch) |
| "what changed", change history, automation | Change history and automation | 119, 131, 159, 160, 161, 162 |
| monthly review, "why did CPA change" | Monthly review | 044, 045, 121, 131, 135, 136, 137, 152 |
| campaign launch, pre-launch | Launch review | 001, 002, 003, 004, 007, 012, 016, 025, 030, 053, 070, 076 (+ operational 145) |

## How to run a preset

1. Load the client profile and the export; note currency, date range, snapshot date.
2. For each skill in the preset: read `skills/<id>/SKILL.md`, gather its Data
   Requirements (skip and say so if unavailable), apply Analysis Steps and
   Thresholds with resolved parameters, collect findings.
3. Dedupe across related skills, group by severity, render with the template in
   `report_language`, header first.
4. End with Recommendations ordered by impact in account currency, and a
   "Skipped" list naming skills not run and why.

## Where things are

- `skills/CATALOG.md` — every skill with category, kind, data source, markets
- `skills/MERGES.md` — the 8 merged pairs and their threshold reconciliation
- `skills/_resources/PARAMETERS.md` — named thresholds and formulas
- `skills/_resources/OUTPUT_TEMPLATES.md` — report templates (en, it) and header
- `skills/_resources/CLIENT_PROFILE.md` — profile template and rules
- `skills/_resources/SKILL_SCHEMA.md` — how a skill is written
````

- [x] **Step 2: Verify**

Run: `grep -c 'ads-OS\|pending_changes' ads/SKILL.md; for n in $(grep -oE '\b[0-9]{3}\b' ads/SKILL.md | sort -u); do ls -d skills/skill-$n-* >/dev/null 2>&1 || echo "no skill $n"; done`
Expected: `0`; no `no skill` lines (every three-digit id in the front desk resolves to a directory; `1.8.0`/`2.0` are not three-digit tokens).

- [x] **Step 3: Commit**

```bash
git add ads/SKILL.md
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "feat(ads): rewrite front desk for the curated library (routing presets, operating rules, DPA gate)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

### Task 7: Phase 6 — catalog, README, final verification

**Files:**
- Create: `README.md`
- Create (generated): `skills/CATALOG.md`

- [x] **Step 1: Generate the catalog and review the classification**

Run: `python3 skills/_resources/scripts/lint.py --write-catalog && sed -n '1,12p' skills/CATALOG.md && grep -c '| analyst |' skills/CATALOG.md && grep -c '| operational |' skills/CATALOG.md`
Expected: catalog written; operational count `10`; analyst count between 15 and 25. Read the analyst rows: each must be a skill that needs external data or judgment. If one is a plain threshold check, change its `kind` in the SKILL.md to `deterministic` and regenerate.

- [x] **Step 2: Write README.md**

````markdown
# Google Ads skills library — eppc edition

`eppc-ads-skills@1.0.0` · 137 Markdown audit skills for Google Ads, curated for EUR/EEA accounts, run by a Claude agent through the `ads` front desk.

## What this is

A skill is a recipe: what data to read, how to analyze it, the thresholds that make a finding, and the output shape. The agent reads a client's Google Ads export, follows the recipe, and writes a report. Nothing here executes changes in Google Ads.

## Provenance and license

Curated from the open-source (MIT) TrueClicks Claude Code plugin `google-ads` v1.8.0 (https://github.com/TrueClicks/claude-plugins). Every skill's frontmatter records `upstream_skill`; `skills/MERGES.md` records the 8 pairs merged into one. Changes vs upstream:

- 145 → 137 skills (8 merges); numbered directories; provenance `metadata` block on every skill
- Every money threshold is a named parameter in account currency (`skills/_resources/PARAMETERS.md`); sample-size rule for rate-based findings
- Output templates in English and Italian with a provenance header (`skills/_resources/OUTPUT_TEMPLATES.md`)
- Client profile with DPA gate (`skills/_resources/CLIENT_PROFILE.md`); Consent Mode v2 always in tracking for EEA accounts
- Skills classified `deterministic` / `analyst` / `operational`; `markets` flag for US-only and EEA-relevant checks
- Broken `/google-ads-get-custom` reference fixed to upstream's `/google-ads:get-custom`
- Lint and catalog generator (`skills/_resources/scripts/lint.py`)

## Layout

```
ads/SKILL.md              front desk: operating rules and routing presets
skills/skill-NNN-…/       137 skills
skills/CATALOG.md         generated table: category, kind, data source, markets
skills/MERGES.md          merged pairs and threshold reconciliation
skills/_resources/        PARAMETERS, OUTPUT_TEMPLATES, CLIENT_PROFILE, SKILL_SCHEMA, scripts/
docs/superpowers/         design spec and implementation plan
```

## How to use

1. In a client repo, create `ads/profile.yaml` from `skills/_resources/CLIENT_PROFILE.md`.
2. Export the account from the Google Ads UI (or `/google-ads:get`, only with a signed DPA).
3. Ask the agent ("audit the account", "where am I wasting budget", "check the tracking"). The front desk picks the preset, runs the skills, and writes the report in `report_language`.
4. To run one skill by hand: read `skills/<id>/SKILL.md`, resolve its `{{parameters}}`, follow it.

Check the library: `python3 skills/_resources/scripts/lint.py` (add `--write-catalog` to regenerate `skills/CATALOG.md`). Tests: `cd skills/_resources/scripts && python3 -m unittest test_lint`.

## Governance

- **Recommend-only.** No skill and no front-desk path applies changes.
- **Data.** Client account data goes to TrueClicks' hosted API only when the client profile has `dpa_signed: true`; otherwise use a manual UI export. Data never goes anywhere else.
- **Provenance.** Every report carries library version, skill id, upstream id, date range, snapshot date, and the parameter values used.
- **EEA.** Consent Mode v2 (skill-075) runs in every tracking workflow for EEA markets; `markets: us_only` sections are skipped.

## Known gaps and out of scope

- No engine and no live API client: the agent runs the recipes.
- No DPA exists yet with TrueClicks; the library only enforces the gate.
- No real account has been run through this library yet. The first calibration run should be a EUR account with a manual UI export and a hand count of false positives.
- 17 upstream numbers are absent (084, 086, 087, 091, 096, 097, 132, 134, 138, 140, 143, 144, 153-155, 157, 158); no Microsoft Ads skills.
- Reference GAQL queries are not validated against the current API version (`gaql_verified: null` everywhere).
- 37 skills need data a period-aggregated export cannot provide (day/hour segments, geographic_view, historical series, simulations, policy topics, external tests); they are `custom_gaql` or `external` in the catalog: 010, 011, 029, 044, 046, 048, 049, 051, 053, 054, 056, 058, 063, 066, 071, 074, 079, 095, 102, 109, 111, 117, 123, 127, 130, 135, 136, 137, 142, 145, 146, 147, 150, 152, 160, 161 (and 055, now merged into 054).
- Upstream's four-level severity (`High`) survives in a few skills; the schema documents three.

## Changelog

- **1.0.0 (2026-09-03)** — first curated release, from upstream 1.8.0. See `docs/superpowers/specs/2026-09-03-google-ads-skills-library-design.md`.
````

- [x] **Step 3: Final verification (the spec's done criteria)**

Run:
```bash
python3 skills/_resources/scripts/lint.py | tail -1
ls -d skills/skill-* | wc -l
grep -rnE '\$[0-9]' skills ads README.md | wc -l
grep -rn 'google-ads-get' skills ads README.md | wc -l
grep -L '^metadata:' skills/skill-*/SKILL.md | wc -l
grep -c 'ads-OS' ads/SKILL.md
test -f skills/CATALOG.md && test -f skills/MERGES.md && test -f README.md && echo files-ok
cd skills/_resources/scripts && python3 -m unittest test_lint 2>&1 | tail -1
```
Expected: `137 skills, 0 errors, 0 warnings`; `137`; `0`; `0`; `0`; `0`; `files-ok`; `OK`.

- [x] **Step 4: Commit**

```bash
git add -A
git -c user.name="antonio" -c user.email="montingelliantonio@gmail.com" commit -m "docs: README, generated catalog; library eppc-ads-skills@1.0.0

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VjnJxS7dAa1HQnYHVhvR48"
```

---

## Self-review

- **Spec coverage:** §3 layout → Tasks 1, 5, 7. §4 frontmatter and command fix → Task 2. §5 classification → Task 2 (rule) and Task 7 step 1 (review). §6 merges → Task 3. §7 parameters → Task 4. §8 output, provenance, language, profile → Task 5. §9 front desk → Task 6. §10 lint → Task 1 (all 11 checks: 1-3, 7-9 in `check_skill`; 4-6 in `check_skill`; 10 in `warn_skill`; 11 in `main`). §11 README → Task 7. §12 phases and done criteria → one task per phase, final check in Task 7 step 3.
- **Placeholder scan:** none; every file's content is given in full or as exact edits.
- **Consistency:** parameter names in Task 3 and Task 4 match the `PARAMETERS.md` table (`spend_floor`, `spend_significant`, `spend_material`, `spend_high`, `monthly_spend_significant`, `monthly_spend_large`, `min_clicks`, `min_impressions`, `min_conversions`, `currency`). Directory names used in Task 4's mapping are the post-migration numbered names; the merged skills' new thresholds are written directly with parameters so the mapping does not reference them. `MERGES.md` contains every `merged_from` name (lint check 8).
