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
