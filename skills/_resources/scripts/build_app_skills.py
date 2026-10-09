#!/usr/bin/env python3
"""skills/_resources/scripts/build_app_skills.py — Package skill ZIPs: five library packages + command center + per recipe.

Standard library only. Usage:
  python3 skills/_resources/scripts/build_app_skills.py            # writes dist/
  python3 skills/_resources/scripts/build_app_skills.py --only skill-017-negative-keyword-conflict-detection
Produces:
  dist/ads.zip                        ads/ front desk + CATALOG/MERGES/PACKS + _resources + _selftest + its recipes
  dist/ads-<topic>.zip (4)            ads-<topic>/ recipe package: SKILL.md index + skills/_resources (contracts,
                                      adsrun runtime) + its recipes; installed side by side with ads
  dist/google-ads-command-center.zip  google-ads-command-center/ front desk (uses the ads skill at runtime)
  dist/skills/<recipe>.zip            <recipe>/ standalone: SKILL.md (+run section), scripts/check.py,
                                      scripts/adsrun/ (vendored runtime), resources/*.md
  dist/MANIFEST.json                  sha256, size and member count per ZIP

exports: APP_DESC_MAX | NAME_MAX | SHARED_RESOURCES | PACKS | shorten_description(text, limit) -> str
         standalone_skill_md(text, name) -> str | build(root, only) -> list[Path] | main(argv) -> int
used_by: README.md → Claude Team packaging; skills/_resources/scripts/test_build.py
rules:   Anthropic upload contract: ZIP root is ONE folder named exactly like frontmatter `name`, containing SKILL.md;
         name <= 64 chars lowercase-hyphen; description <= 200 chars (raise, never truncate silently).
         Source SKILL.md files are never modified; run instructions are injected into the staged copy only.
         Excluded everywhere: *.zip, dotfiles, __MACOSX, __pycache__, tests/ folders, *.pyc.
         Deterministic archives: sorted members, fixed timestamps, no macOS metadata (zipfile, not `zip`).
         Standalone ZIPs must not reference ../_resources — links are rewritten to resources/.
         Library split: every recipe belongs to exactly ONE package, chosen by its metadata category via PACKS
         (unknown category → ValueError). Every package carries skills/_resources (Markdown contracts + adsrun
         runtime; lint/build scripts only in ads) so each recipe runs from its own package, and every
         ../_resources link in a packaged Markdown file must resolve inside that package (else ValueError).
         The staged ads/SKILL.md gains a generated package section and skills/PACKS.md (recipe → package).
         Upload contract: a ZIP holds EXACTLY ONE SKILL.md, at its root (checked in _write_zip). Inside library
         packages every nested SKILL.md (recipes, _selftest) is packaged as RECIPE.md and Markdown references
         to SKILL.md are rewritten to RECIPE.md (SKILL_SCHEMA.md / SKILL_EXAMPLE.md untouched); repo sources
         keep SKILL.md.
agent:   claude-fable-5-1 | anthropic | 2026-09-15 | s_20260915_cc | initial packaging script
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | folder-root ZIPs, per-recipe standalone packages, vendored runtime
agent:   claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_packs | library split into five side-by-side packages by category
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

APP_DESC_MAX = 200
NAME_MAX = 64
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
SHARED_RESOURCES = ("DATA_CONTRACT.md", "PARAMETERS.md", "OUTPUT_TEMPLATES.md", "CLIENT_PROFILE.md", "RUNTIME.md")
ADS_DESC = (
    "Google Ads audit front desk: waste, keywords, creative, bidding, measurement, "
    "Shopping/PMax, audiences, policy, seasonal. Use for 'audit ads', 'check the "
    "account', 'why did CPA change'."
)
PACKS: dict[str, tuple[str, str, tuple[str, ...]]] = {  # name -> (title, description, categories)
    "ads": ("Ads front desk", ADS_DESC, ("platform", "structure", "compliance", "competitive")),
    "ads-search-keywords": (
        "Search terms, keywords, waste and Quality Score",
        "Google Ads recipe package for the ads front desk: search terms, negatives, keywords, match types, "
        "Quality Score and wasted-spend checks. Recommend-only.",
        ("keywords", "waste", "quality")),
    "ads-creative-audiences": (
        "Creative, assets, audiences and remarketing",
        "Google Ads recipe package for the ads front desk: RSA and asset quality, ad copy, landing-page "
        "consistency, audiences and remarketing checks. Recommend-only.",
        ("creative", "remarketing")),
    "ads-bidding-tracking": (
        "Bidding, budgets and conversion tracking",
        "Google Ads recipe package for the ads front desk: bidding strategies, targets, budgets, pacing, "
        "conversion tracking and measurement checks. Recommend-only.",
        ("bidding", "tracking")),
    "ads-shopping-seasonal": (
        "Shopping, Performance Max, targeting and seasonality",
        "Google Ads recipe package for the ads front desk: Shopping, Performance Max, Merchant feeds, "
        "geo/device/schedule targeting and seasonality checks. Recommend-only.",
        ("shopping_pmax", "seasonal", "targeting")),
}
CATEGORY_RE = re.compile(r"^\s+category:\s*(\S+)\s*$", re.M)
RESOURCE_LINK_RE = re.compile(rb"\.\./_resources/([A-Za-z0-9_./-]+)")
DESC_RE = re.compile(r"^description: >\n(?:  .*\n)+", re.M)
NAME_OK = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RUN_SECTION = """
## Run (Claude Team)

This skill contains its own deterministic checks. Evidence files follow `resources/DATA_CONTRACT.md`.

1. Put the uploaded exports in one folder (extract a ZIP first) and locate the client profile if supplied.
2. From this skill's folder run:
   `python3 scripts/check.py run --export <evidence folder> --profile <profile.yaml> --out <work folder>`
3. Follow `resources/RUNTIME.md` steps 3–6: read `result.json`, decide each `ai_review` item with one declared
   outcome, validate with `python3 scripts/check.py finalize ... --decisions decisions.json`, then report from
   `final.json` using `resources/OUTPUT_TEMPLATES.md`. Never alter script numbers or invent severities.
"""


def shorten_description(text: str, replacement: str) -> str:
    """Replace a folded YAML description block with a single quoted line.

    Rules:   replacement MUST be <= APP_DESC_MAX chars; raise instead of silently truncating.
    """
    if len(replacement) > APP_DESC_MAX:
        raise ValueError(f"description is {len(replacement)} chars (> {APP_DESC_MAX})")
    new, n = DESC_RE.subn(f'description: "{replacement}"\n', text, count=1)
    if n != 1:
        raise ValueError("no folded description block found")
    return new


def _frontmatter_field(text: str, key: str) -> str:
    m = re.search(rf'^{key}:\s*(?:"(.*)"|(.*))$', text, re.M)
    if m and (m.group(1) or m.group(2) or "").strip() not in ("", ">", "|"):
        return (m.group(1) or m.group(2)).strip()
    m = re.search(rf"^{key}: [>|]\n((?:  .*\n)+)", text, re.M)
    return " ".join(l.strip() for l in m.group(1).splitlines()) if m else ""


def _check_contract(name: str, description: str, where: str) -> None:
    if not NAME_OK.match(name) or len(name) > NAME_MAX:
        raise ValueError(f"{where}: name {name!r} must be lowercase-hyphen and <= {NAME_MAX} chars")
    if not description or len(description) > APP_DESC_MAX:
        raise ValueError(f"{where}: description is {len(description)} chars (must be 1..{APP_DESC_MAX})")


def standalone_skill_md(text: str, name: str) -> str:
    """Staged SKILL.md for a standalone recipe ZIP.

    Rules:   ../_resources/ → resources/; adds compatibility; injects RUN_SECTION after the H1 title.
    """
    text = text.replace("../_resources/", "resources/").replace("skills/_resources/", "resources/")
    if "\ncompatibility:" not in text.split("\n---", 2)[1]:
        text = text.replace("\nmetadata:\n", "\ncompatibility: \"Needs code execution: Python 3.10+ standard library, no network.\"\nmetadata:\n", 1)
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    h1 = next(i for i in range(end + 1, len(lines)) if lines[i].startswith("# "))
    return "\n".join(lines[: h1 + 1] + RUN_SECTION.rstrip("\n").split("\n") + lines[h1 + 1:])


def _skip(rel: Path) -> bool:
    parts = rel.parts
    return (any(p.startswith(".") or p in ("__MACOSX", "__pycache__", "tests") for p in parts)
            or rel.suffix in (".zip", ".pyc"))


def _add_tree(members: dict, src: Path, prefix: str) -> None:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_file() and not _skip(rel):
            members[f"{prefix}/{rel.as_posix()}"] = p.read_bytes()


def _add_resources(members: dict, skills: Path, prefix: str, with_scripts: bool) -> None:
    """skills/_resources into prefix; lint/build scripts only when with_scripts (tests never)."""
    res = skills / "_resources"
    for p in sorted(res.rglob("*")):
        rel = p.relative_to(res)
        if p.is_file() and not _skip(rel) and (with_scripts or rel.parts[0] != "scripts"):
            members[f"{prefix}/{rel.as_posix()}"] = p.read_bytes()


def _recipe_packs(skills: Path) -> dict[str, str]:
    """recipe folder name -> package name. Rules: unknown or missing category raises ValueError."""
    by_cat = {c: name for name, (_, _, cats) in PACKS.items() for c in cats}
    out = {}
    for d in sorted(p for p in skills.iterdir() if p.is_dir() and re.match(r"^skill-\d{3}-", p.name)):
        m = CATEGORY_RE.search((d / "SKILL.md").read_text())
        if not m or m.group(1) not in by_cat:
            raise ValueError(f"{d.name}: category {m.group(1) if m else None!r} is not assigned to a package in PACKS")
        out[d.name] = by_cat[m.group(1)]
    return out


def _packs_md(assign: dict[str, str]) -> str:
    lines = ["# Library packages", "", "Generated by build_app_skills.py. Each recipe lives in exactly one package; "
             "packages are installed side by side (same parent folder).", "", "| recipe | package |", "|---|---|"]
    return "\n".join(lines + [f"| {r} | {p} |" for r, p in sorted(assign.items())]) + "\n"


def _ads_split_section(assign: dict[str, str]) -> str:
    rows = "\n".join(f"- `{name}` — {PACKS[name][0]} ({sum(v == name for v in assign.values())} recipes)"
                     for name in PACKS)
    return f"""
## Installed packages

The library is split into {len(PACKS)} skills installed side by side in the same parent folder (for example
`~/.claude/skills/`):

{rows}

A recipe `skill-NNN-name` lives at `<parent>/<package>/skills/skill-NNN-name/`; for this skill's own recipes that is
`skills/skill-NNN-name/`. `skills/PACKS.md` maps every recipe to its package and `skills/CATALOG.md` (here) lists
them all. Every package carries an identical copy of `skills/_resources` (contracts and the adsrun runtime), so run a
recipe from its own package. If a package is not installed, report its recipes as not installed in Coverage; never
substitute another recipe. Inside packages each recipe's canonical instructions are `RECIPE.md` (the upload contract
allows one `SKILL.md` per skill, this file).

**Paths.** This skill's folder is `${{CLAUDE_SKILL_DIR}}` (Claude Code expands it; elsewhere it is the folder holding
this file) and `<parent>` is its parent folder. Every command written in a `RECIPE.md` or in `RUNTIME.md` as
`python3 <recipe>/scripts/check.py …` is relative to the recipe's package `skills/` folder: run it from
`<parent>/<package>/skills/` (for this skill `${{CLAUDE_SKILL_DIR}}/skills/`), or prefix that folder, e.g.
`python3 "${{CLAUDE_SKILL_DIR}}/../ads-search-keywords/skills/skill-017-negative-keyword-conflict-detection/scripts/check.py" run …`.
"""


def _pack_skill_md(name: str, recipes: list[tuple[str, str]]) -> str:
    title, desc, _ = PACKS[name]
    items = "\n".join(f"- `{r}` — {d}" for r, d in recipes)
    return f"""---
name: {name}
description: "{desc}"
---
# Google Ads recipes: {title}

Recipe package of the eppc Google Ads library (`eppc-ads-skills@2.0.0`). Use it through the `ads` front desk
installed alongside: its operating rules, routing, evidence contract and report format apply to every recipe here.
Never change accounts; every output is a recommendation.

Run one recipe: read `skills/<recipe>/RECIPE.md` (its canonical instructions). Its commands, written as `python3
<recipe>/scripts/check.py …`, are relative to this package's `skills/` folder, i.e. `${{CLAUDE_SKILL_DIR}}/skills/`
(Claude Code expands `${{CLAUDE_SKILL_DIR}}`; elsewhere it is the folder holding this file), e.g. `python3
"${{CLAUDE_SKILL_DIR}}/skills/<recipe>/scripts/check.py" run --export <export> --profile <profile.yaml> --out
<work>/<recipe>`. Then follow `skills/_resources/RUNTIME.md` (ai_review decisions, finalize).

## Recipes

{items}
"""


def _check_links(pack: str, members: dict) -> None:
    for m, b in members.items():
        if not m.endswith(".md"):
            continue
        base = m.rsplit("/", 1)[0]
        for target in RESOURCE_LINK_RE.findall(b):
            resolved = f"{base.rsplit('/', 1)[0]}/_resources/{target.decode()}"
            if resolved not in members:
                raise ValueError(f"{pack}: {m} links ../_resources/{target.decode()} missing from the package")


NESTED_SKILL = "RECIPE.md"
_SKILL_REF = re.compile(rb"\bSKILL\.md\b")
PATH_NOTE = (b"\n> Packaged copy: commands below written as `python3 <recipe>/scripts/check.py ...` are relative to "
             b"this package's `skills/` folder (the folder that contains this recipe's folder). Run them from there, "
             b"or prefix that absolute path.\n")


def _single_skill_md(pack: str, members: dict) -> dict:
    """Rename nested SKILL.md → RECIPE.md, rewrite Markdown references and add the path note after the recipe H1;
    the root SKILL.md stays."""
    root_md = f"{pack}/SKILL.md"
    out = {}
    for m, b in members.items():
        nested = m != root_md and m.endswith("/SKILL.md")
        name = m[: -len("SKILL.md")] + NESTED_SKILL if nested else m
        body = _SKILL_REF.sub(NESTED_SKILL.encode(), b) if m.endswith(".md") and m != root_md else b
        if nested and re.match(rf"^{re.escape(pack)}/skills/skill-\d{{3}}-", m):
            body = re.sub(rb"(?m)^(# .*\n)", lambda h: h.group(1) + PATH_NOTE, body, count=1)
        out[name] = body
    if root_md in out:
        out[root_md] = re.sub(rb"(skills/[A-Za-z0-9_./-]*?)SKILL\.md", rb"\1" + NESTED_SKILL.encode(), out[root_md])
    return out


def _write_zip(out: Path, members: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    roots = {m.split("/", 1)[0] for m in members}
    if len(roots) != 1:
        raise ValueError(f"{out.name}: ZIP must have exactly one root folder, found {sorted(roots)}")
    skill_mds = sorted(m for m in members if m.rsplit("/", 1)[-1] == "SKILL.md")
    if skill_mds != [f"{roots.pop()}/SKILL.md"]:
        raise ValueError(f"{out.name}: ZIP must contain exactly one SKILL.md at its root, found {len(skill_mds)}")
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, members[name])
    tmp.replace(out)


def build(root: Path, only: list[str] | None = None) -> list[Path]:
    """Build ZIPs under root/dist and return their paths.

    Rules:   Fails on any contract violation — fix the source, not the script.
             A recipe without scripts/check.py is still packaged standalone (Markdown-only) and reported.
    """
    dist = root / "dist"
    skills = root / "skills"
    runtime = skills / "_resources" / "runtime" / "adsrun"
    outputs: list[Path] = []
    if not only:
        assign = _recipe_packs(skills)
        for pack, (_, desc, _) in PACKS.items():
            _check_contract(pack, desc, f"PACKS[{pack!r}]")
            mine = [r for r, p in assign.items() if p == pack]
            prefix = f"{pack}/skills"
            if pack == "ads":
                ads_text = shorten_description((root / "ads" / "SKILL.md").read_text(), ADS_DESC)
                members = {"ads/SKILL.md": (ads_text.rstrip("\n") + "\n" + _ads_split_section(assign)).encode()}
                for extra in ("CATALOG.md", "MERGES.md"):
                    members[f"{prefix}/{extra}"] = (skills / extra).read_bytes()
                members[f"{prefix}/PACKS.md"] = _packs_md(assign).encode()
                _add_tree(members, skills / "_selftest", f"{prefix}/_selftest")
            else:
                recipes = [(r, _frontmatter_field((skills / r / "SKILL.md").read_text(), "description")) for r in mine]
                members = {f"{pack}/SKILL.md": _pack_skill_md(pack, recipes).encode()}
            _add_resources(members, skills, f"{prefix}/_resources", with_scripts=pack == "ads")
            for r in mine:
                _add_tree(members, skills / r, f"{prefix}/{r}")
            _check_links(pack, members)
            members = _single_skill_md(pack, members)
            _write_zip(dist / f"{pack}.zip", members)
            outputs.append(dist / f"{pack}.zip")

        cc_text = (root / "command-center" / "SKILL.md").read_text()
        cc_name = _frontmatter_field(cc_text, "name")
        _check_contract(cc_name, _frontmatter_field(cc_text, "description"), "command-center/SKILL.md")
        _write_zip(dist / f"{cc_name}.zip", {f"{cc_name}/SKILL.md": cc_text.encode()})
        outputs.append(dist / f"{cc_name}.zip")

    for d in sorted(p for p in skills.iterdir() if p.is_dir() and re.match(r"^skill-\d{3}-", p.name)):
        if only and d.name not in only:
            continue
        text = (d / "SKILL.md").read_text()
        name = _frontmatter_field(text, "name")
        if name != d.name:
            raise ValueError(f"{d.name}: frontmatter name {name!r} must equal folder")
        _check_contract(name, _frontmatter_field(text, "description"), f"{d.name}/SKILL.md")
        members = {f"{name}/SKILL.md": standalone_skill_md(text, name).encode()}
        for res in SHARED_RESOURCES:
            members[f"{name}/resources/{res}"] = (skills / "_resources" / res).read_bytes()
        if (d / "scripts").is_dir():
            _add_tree(members, d / "scripts", f"{name}/scripts")
            _add_tree(members, runtime, f"{name}/scripts/adsrun")
        leftover = [m for m, b in members.items() if m.endswith(".md") and b"../_resources/" in b]
        if leftover:
            raise ValueError(f"{name}: unresolved ../_resources links in {leftover}")
        _write_zip(dist / "skills" / f"{name}.zip", members)
        outputs.append(dist / "skills" / f"{name}.zip")

    manifest = {}
    for p in sorted(outputs):
        with zipfile.ZipFile(p) as z:
            count = len(z.namelist())
        manifest[p.relative_to(dist).as_posix()] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                                    "bytes": p.stat().st_size, "members": count}
    if not only:
        (dist / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return outputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", help="build only this recipe standalone ZIP (repeatable)")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    outs = build(root, args.only)
    no_script = [p.stem for p in outs if p.parent.name == "skills"
                 and not (root / "skills" / p.stem / "scripts" / "check.py").is_file()]
    print(f"{len(outs)} zips in {root / 'dist'}; standalone without scripts: {len(no_script)}")
    for p in outs:
        if p.parent.name != "skills":
            print(f"  {p.relative_to(root)}  {p.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
