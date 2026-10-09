#!/usr/bin/env python3
"""skills/_resources/scripts/lint.py — Lint and catalog generator for the eppc Google Ads skills library.

Standard library only. Usage:
  python3 skills/_resources/scripts/lint.py                # lint skills/
  python3 skills/_resources/scripts/lint.py --write-catalog
  python3 skills/_resources/scripts/lint.py --allow-dollars --expect-count 145
  python3 skills/_resources/scripts/lint.py --allow-missing-scripts   # while authoring a new recipe
Exit code 1 when any error is found. Warnings never fail the run.

exports: FORBIDDEN_IMPORTS | FORBIDDEN_CALLS | check_script(skill_dir, require) | KINDS | DATA_SOURCES | MARKETS | CATEGORIES | SECTIONS | REQUIRED_META | NAME_RE | PARAM_RE | DOLLAR_DIGIT_RE | EXTERNAL_CMD_RE | MAX_LINES | parse_frontmatter(text) | load_params(path) | check_skill(skill_dir, params, merges_text, skill_names, allow_dollars) | warn_skill(skill_dir) | skill_dirs(root) | catalog_rows(root) | render_catalog(rows) | main(argv)
used_by: test_lint.py → contract regression tests; README.md → library validation CLI
rules:   Structural checks do not establish API validity; catalog routing text comes from canonical source, never summaries.
agent:   codedna-cli (no-llm) | codedna-cli | 2026-09-03 | codedna-cli | initial CodeDNA annotation pass
agent:   gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | evidence, severity, routing and consolidation gates
agent:   gpt-6-astra | openai | 2026-09-07 | s_20260907_context_opt | source-derived discovery metadata
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | scripts/check.py static gate (required), 134 recipes
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | test_check.py header gate, dynamic-import ban, urllib.parse allowance
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
REQUIRED_META = ["library", "category", "kind", "data_source", "markets", "reviewed", "agent"]
NAME_RE = re.compile(r"^skill-(\d{3})-[a-z0-9-]+$")
PARAM_RE = re.compile(r"\{\{([a-z_]+)\}\}")
DOLLAR_DIGIT_RE = re.compile(r"\$\d")
EXTERNAL_CMD_RE = re.compile(r"/google-ads[:-]get")  # plugin commands: the library is tool-neutral
MAX_LINES = 160


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


def _requirement(data_section: str, marker: str) -> str:
    """Extract one evidence marker without swallowing adjacent input requirements."""
    value = re.search(rf"\*\*{marker}:\*\*(.*?)(?=\n\*\*|\Z)", data_section, re.DOTALL)
    return value.group(1).strip() if value else ""


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
    if not isinstance(fm.get("metadata"), dict):
        return [f"{skill_dir.name}: metadata must be a map"]

    for key in ("name", "description", "allowed-tools", "metadata"):
        if key not in fm:
            issues.append(f"{skill_dir.name}: frontmatter missing '{key}'")
    if not isinstance(fm.get("description"), str) or not fm["description"].strip():
        issues.append(f"{skill_dir.name}: description must be populated text for catalog selection")
    name = fm.get("name", "")
    if name != skill_dir.name:
        issues.append(f"{skill_dir.name}: name '{name}' does not match directory")
    if not NAME_RE.match(str(name)):
        issues.append(f"{skill_dir.name}: name must look like skill-NNN-slug")

    tools = fm.get("allowed-tools", "")
    tool_names = set(tools) if isinstance(tools, list) else {t.strip() for t in str(tools).split(",")}
    if tool_names != {"Read", "Grep", "Glob", "Bash"}:
        issues.append(f"{skill_dir.name}: allowed-tools must permit local Read, Grep, Glob, Bash only")
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
    if meta.get("library") != "eppc-ads-skills@2.0.0":
        issues.append(f"{skill_dir.name}: library version must be eppc-ads-skills@2.0.0")

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

    prose = _strip_fences(body)
    data_section = prose.partition("## Data Requirements")[2].partition("## Analysis Steps")[0]
    for marker in ("Applicability", "Required inputs", "Missing inputs"):
        if not _requirement(data_section, marker):
            issues.append(f"{skill_dir.name}: Data Requirements missing populated '{marker}'")
    source_labels = {
        "export": "Account export",
        "custom_query": "Custom query required",
        "external": "External (beyond Google Ads data)",
    }
    source = re.search(r"\*\*Data Source:\*\*\s*([^\n]+)", data_section)
    if source and source.group(1).strip() != source_labels.get(meta.get("data_source")):
        issues.append(f"{skill_dir.name}: Data Source label must match metadata.data_source")

    threshold_section = prose.partition("## Thresholds")[2].partition("## Output")[0]
    threshold_rows = 0
    for line in threshold_section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells == ["Condition", "Severity"] or all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
            continue
        threshold_rows += 1
        if len(cells) != 2 or cells[1] not in {"Critical", "Warning", "Info"}:
            issues.append(f"{skill_dir.name}: threshold severity must be exactly Critical, Warning or Info")
    if not threshold_rows:
        issues.append(f"{skill_dir.name}: Thresholds must contain condition/severity rows")
    for query in re.findall(r"```(?:sql|gaql)\s*\n(.*?)```", body, re.DOTALL | re.IGNORECASE):
        for literal in re.findall(r"\bDURING\s+(LAST_90_DAYS|LAST_365_DAYS|THIS_YEAR|THIS_QUARTER)\b", query):
            issues.append(f"{skill_dir.name}: invalid GAQL DURING literal {literal}; use explicit BETWEEN dates")

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
    """Rules: fixture cases reference live skills; expected findings use canonical severities."""
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
                if item.get("severity") not in (None, "Critical", "Warning", "Info"):
                    issues.append(f"_selftest: case {i} ({skill}) has invalid severity")
        tools = case.get("tools")
        if tools is not None and {t.strip() for t in tools.split(",")} != {"Read", "Grep", "Glob", "Bash"}:
            issues.append(f"_selftest: case {i} ({skill}) must allow local computation")
    return issues


FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "requests", "subprocess", "random", "secrets", "ftplib", "smtplib"}
FORBIDDEN_CALLS = re.compile(r"\b(datetime\.now|date\.today|time\.time|datetime\.utcnow)\s*\(")


def check_script(skill_dir: Path, require: bool) -> list[str]:
    """Validate scripts/check.py against RUNTIME.md authoring rules.

    Rules:   Static, best-effort checks only (parse, SKILL constant, CodeDNA headers of check.py and
             tests/test_check.py, specific run/verify Rules:, no network/clock/randomness/dynamic imports);
             the Claude sandbox is the real network boundary; behavior is covered by per-skill tests and the grader.
    """
    import ast

    path = skill_dir / "scripts" / "check.py"
    if not path.exists():
        return [f"{skill_dir.name}: scripts/check.py missing"] if require else []
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{skill_dir.name}: check.py syntax error line {e.lineno}"]
    issues = []
    doc = ast.get_docstring(tree) or ""
    for field in ("exports:", "used_by:", "rules:", "agent:"):
        if field not in doc:
            issues.append(f"{skill_dir.name}: check.py CodeDNA header missing '{field}'")
    consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    if consts.get("SKILL") != skill_dir.name:
        issues.append(f"{skill_dir.name}: check.py SKILL must equal the folder name")
    if not consts.get("VERSION"):
        issues.append(f"{skill_dir.name}: check.py VERSION missing")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        issues.append(f"{skill_dir.name}: check.py must define run(ctx)")
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("run", "verify")):
        rules = (ast.get_docstring(fn) or "").partition("Rules:")[2].strip()
        if len(rules) < 20 or rules.lower().startswith("see module rules"):
            issues.append(f"{skill_dir.name}: {fn.name}() needs a specific 'Rules:' docstring (CodeDNA L2)")
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for full in names:
            if full == "urllib.parse":  # pure string parsing, no network
                continue
            n = full.split(".")[0]
            if n in FORBIDDEN_IMPORTS:
                issues.append(f"{skill_dir.name}: check.py imports forbidden module '{n}'")
            elif n not in sys.stdlib_module_names and n != "adsrun":
                issues.append(f"{skill_dir.name}: check.py imports non-stdlib module '{n}'")
    if FORBIDDEN_CALLS.search(src):
        issues.append(f"{skill_dir.name}: check.py reads the clock; use ctx.as_of/ctx.snapshot")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id in ("__import__", "import_module"))
                or (isinstance(node.func, ast.Attribute) and node.func.attr in ("__import__", "import_module"))):
            issues.append(f"{skill_dir.name}: check.py uses dynamic imports; static stdlib imports only")
            break
    tests = skill_dir / "tests" / "test_check.py"
    if not tests.exists():
        issues.append(f"{skill_dir.name}: tests/test_check.py missing")
    else:
        try:
            tdoc = ast.get_docstring(ast.parse(tests.read_text())) or ""
        except SyntaxError as e:
            tdoc = ""
            issues.append(f"{skill_dir.name}: test_check.py syntax error line {e.lineno}")
        for field in ("exports:", "used_by:", "rules:", "agent:"):
            if field not in tdoc:
                issues.append(f"{skill_dir.name}: test_check.py CodeDNA header missing '{field}'")
    return issues




def warn_skill(skill_dir: Path) -> list[str]:
    """Rules: line count over MAX_LINES is a warning, never an error — must not affect exit code."""
    n = len((skill_dir / "SKILL.md").read_text().split("\n"))
    return [f"{skill_dir.name}: {n} lines (> {MAX_LINES})"] if n > MAX_LINES else []


FRONT_DESKS = ("ads", "command-center")


def _check_routing(root: Path, skill_names: set[str]) -> list[str]:
    """Read-only: explicit front-desk candidates (ads, command-center) must resolve to surviving numeric IDs."""
    known = {NAME_RE.fullmatch(name).group(1) for name in skill_names}
    issues: list[str] = []
    for desk in FRONT_DESKS:
        path = root.parent / desk / "SKILL.md"
        if not path.exists():
            continue
        referenced = {
            number for line in path.read_text().splitlines() if line.startswith("|")
            for number in re.findall(r"\b\d{3}\b", line)
        }
        issues += [f"{desk}/SKILL.md: routing references absent skill-{number}" for number in sorted(referenced - known)]
    return issues


# ----------------------------------------------------------------------------- catalog
def skill_dirs(root: Path) -> list[Path]:
    """Rules: only directories matching NAME_RE count as skills; sorted for deterministic output."""
    return sorted(p for p in root.iterdir() if p.is_dir() and NAME_RE.match(p.name))


def catalog_rows(root: Path) -> list[dict]:
    """Build discovery rows from canonical frontmatter and applicability.

    Rules:   Assumes check_skill passed; retain full applicability, including exclusions.
             Read each recipe once and sort by numeric skill number.
    """
    rows = []
    for d in skill_dirs(root):
        text = (d / "SKILL.md").read_text()
        fm, body = parse_frontmatter(text)
        data_section = _strip_fences(body).partition("## Data Requirements")[2].partition("## Analysis Steps")[0]
        meta = fm.get("metadata") or {}
        rows.append({
            "number": int(NAME_RE.match(d.name).group(1)),
            "name": d.name,
            "category": meta.get("category", ""),
            "kind": meta.get("kind", ""),
            "data_source": meta.get("data_source", ""),
            "markets": meta.get("markets", ""),
            "merged_from": ", ".join(_as_list(meta.get("merged_from"))),
            "lines": len(text.split("\n")),
            "description": fm["description"],
            "applicability": _requirement(data_section, "Applicability"),
        })
    return sorted(rows, key=lambda r: r["number"])


def render_catalog(rows: list[dict]) -> str:
    """Rules: discovery cells stay on one searchable row; preserve exclusions and escape table delimiters."""
    out = [
        "# Skill catalog",
        "",
        f"Generated by `_resources/scripts/lint.py --write-catalog`. {len(rows)} skills.",
        "",
        "Search matching IDs, descriptions or applicability before opening recipes; do not load this whole index for a single check.",
        "Generated selection metadata is not execution authority. Confirm selected recipes; unknown applicability remains unresolved.",
        "",
        "| # | Skill | Category | Kind | Data source | Markets | Merged from | Lines | Description | Applicability |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        description = " ".join(r["description"].split()).replace("|", "&#124;")
        applicability = " ".join(r["applicability"].split()).replace("|", "&#124;")
        out.append(
            f"| {r['number']:03d} | {r['name']} | {r['category']} | {r['kind']} | {r['data_source']} | {r['markets']} | {r['merged_from']} | {r['lines']} | {description} | {applicability} |"
        )
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out += ["", "## Counts by kind", ""] + [f"- {k}: {v}" for k, v in sorted(kinds.items())] + [""]
    sources: dict[str, int] = {}
    for r in rows:
        sources[r["data_source"]] = sources.get(r["data_source"], 0) + 1
    out += ["## Counts by data source", ""] + [f"- {k}: {v}" for k, v in sorted(sources.items())] + [""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    """Rules: exits 1 only on errors; warnings (line counts) never fail the run.
    --expect-count guards against accidental skill deletion or duplication.
    """
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="skills")
    ap.add_argument("--allow-dollars", action="store_true")
    ap.add_argument("--expect-count", type=int, default=136)
    ap.add_argument("--write-catalog", action="store_true")
    ap.add_argument("--allow-missing-scripts", action="store_true", help="authoring only: tolerate recipes without scripts/check.py")
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
        errors += check_script(d, not args.allow_missing_scripts)
        warnings += warn_skill(d)
    if len(dirs) != args.expect_count:
        errors.append(f"expected {args.expect_count} skill directories, found {len(dirs)}")
    errors += check_selftest(root, names)
    errors += _check_routing(root, names)
    numbers = [NAME_RE.fullmatch(name).group(1) for name in names]
    if len(set(numbers)) != len(numbers):
        errors.append("duplicate numeric skill IDs")

    if args.write_catalog and not errors:
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
