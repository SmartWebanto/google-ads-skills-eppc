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
