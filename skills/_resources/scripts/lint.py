#!/usr/bin/env python3
"""skills/_resources/scripts/lint.py — Lint and catalog generator for the eppc Google Ads skills library.

Standard library only. Usage:
  python3 skills/_resources/scripts/lint.py                # lint skills/
  python3 skills/_resources/scripts/lint.py --write-catalog
  python3 skills/_resources/scripts/lint.py --allow-dollars --expect-count 145
Exit code 1 when any error is found. Warnings never fail the run.

exports: KINDS | DATA_SOURCES | MARKETS | CATEGORIES | SECTIONS | REQUIRED_META | NAME_RE | PARAM_RE | DOLLAR_DIGIT_RE | EXTERNAL_CMD_RE | MAX_LINES | parse_frontmatter(text) | load_params(path) | check_skill(skill_dir, params, merges_text, skill_names, allow_dollars) | warn_skill(skill_dir) | skill_dirs(root) | catalog_rows(root) | render_catalog(rows) | main(argv)
used_by: none
rules:   none
agent:   codedna-cli (no-llm) | codedna-cli | 2026-09-03 | codedna-cli | initial CodeDNA annotation pass
message: 
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KINDS = {"deterministic", "analyst", "operational"}
DATA_SOURCES = {"export", "custom_query", "external"}
MARKETS = {"all", "us_only", "eea_relevant"}
CATEGORIES = {
    "structure", "keywords", "creative", "bidding", "targeting", "quality", "tracking",
    "shopping_pmax", "remarketing", "waste", "competitive", "compliance", "seasonal", "platform",
}
SECTIONS = ["## Purpose", "## Data Requirements", "## Analysis Steps", "## Thresholds", "## Output"]
REQUIRED_META = ["library", "category", "kind", "data_source", "markets", "reviewed"]
NAME_RE = re.compile(r"^skill-(\d{3})-[a-z0-9-]+$")
PARAM_RE = re.compile(r"\{\{([a-z_]+)\}\}")
DOLLAR_DIGIT_RE = re.compile(r"\$\d")
EXTERNAL_CMD_RE = re.compile(r"/google-ads[:-]get")  # plugin commands: the library is tool-neutral
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
    """Parse the YAML subset used by SKILL.md files: scalars, inline lists, one nested map, folded text.

    Rules:   NOT a YAML parser — supports exactly one nesting level (metadata:);
             an indent-0 line resets the write target to the top-level dict.
             Folded blocks (> or |) are joined with single spaces.
             Raises ValueError when either --- fence is missing.
    """
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
    """Collect defined {{param}} names from PARAMETERS.md.

    Rules:   Missing file returns an empty set — every {{param}} in skills is then flagged.
    """
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
    """Validate one skill directory and return human-readable issue strings.

    Rules:   Returns early on missing SKILL.md or unparseable frontmatter.
             Section order compares against SECTIONS exactly, after stripping
             code fences ('## ' lines inside fences must not count).
             merged_from entries must NOT exist as directories and MUST appear in MERGES.md.
             DOLLAR_DIGIT_RE only matches $<digit> — $[X] placeholders are legal.
    """
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
    if EXTERNAL_CMD_RE.search(text):
        issues.append(f"{skill_dir.name}: external plugin command reference (describe the query, not a tool; see DATA_CONTRACT.md)")
    for p in set(PARAM_RE.findall(text)):
        if p not in params:
            issues.append(f"{skill_dir.name}: parameter '{{{{{p}}}}}' not defined in PARAMETERS.md")
    return issues


def check_selftest(root: Path, skill_names: set[str]) -> list[str]:
    """Every case in _selftest/fixture/expected.json must point at an existing skill."""
    path = root / "_selftest" / "fixture" / "expected.json"
    if not path.exists():
        return []
    try:
        cases = json.loads(path.read_text()).get("cases", [])
    except (ValueError, AttributeError) as e:
        return [f"_selftest: expected.json unreadable: {e}"]
    issues = []
    for i, case in enumerate(cases):
        skill = case.get("skill")
        if skill not in skill_names:
            issues.append(f"_selftest: case {i} references unknown skill '{skill}'")
        for key in ("expect", "reject"):
            for item in case.get(key, []):
                if not item.get("must_contain"):
                    issues.append(f"_selftest: case {i} ({skill}) has a {key} item without must_contain")
    return issues


def warn_skill(skill_dir: Path) -> list[str]:
    """Rules: line count over MAX_LINES is a warning, never an error — must not affect exit code."""
    n = len((skill_dir / "SKILL.md").read_text().split("\n"))
    return [f"{skill_dir.name}: {n} lines (> {MAX_LINES})"] if n > MAX_LINES else []


# ----------------------------------------------------------------------------- catalog
def skill_dirs(root: Path) -> list[Path]:
    """Rules: only directories matching NAME_RE count as skills; sorted for deterministic output."""
    return sorted(p for p in root.iterdir() if p.is_dir() and NAME_RE.match(p.name))


def catalog_rows(root: Path) -> list[dict]:
    """Build catalog rows from skill frontmatter.

    Rules:   Assumes check_skill passed — parse_frontmatter may raise on broken skills.
             Sorted by numeric skill number, not directory name.
    """
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
    """Rules: column order is asserted by tests and committed as CATALOG.md — keep the table shape stable."""
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
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out += ["", "## Counts by kind", ""] + [f"- {k}: {v}" for k, v in sorted(kinds.items())] + [""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    """Rules: exits 1 only on errors; warnings (line counts) never fail the run.
    --expect-count guards against accidental skill deletion or duplication.
    """
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

    errors, warnings = [], []
    for d in dirs:
        errors += check_skill(d, params, merges_text, names, args.allow_dollars)
        warnings += warn_skill(d)
    if len(dirs) != args.expect_count:
        errors.append(f"expected {args.expect_count} skill directories, found {len(dirs)}")
    errors += check_selftest(root, names)

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
