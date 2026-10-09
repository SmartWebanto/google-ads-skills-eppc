---
name: skill-012-keyword-match-type-distribution
description: "Describe match-type distribution and comparable outcomes without broad-match adoption quotas or causal mix assumptions."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-022-broad-match-smart-bidding-alignment, skill-023-close-variant-query-expansion-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 012: Keyword Match Type Distribution

## Purpose

Describe match-type distribution and comparable outcomes without broad-match adoption quotas or causal mix assumptions.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search campaigns with explicit keyword match-type fields; not Shopping or keywordless campaigns.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/keywords`, `export/keyword_metrics`, `export/bidding_strategies`.
- Keyword IDs with explicit match type; metric grain account/campaign/ad_group/keyword/window.
- Campaign objectives, goal/value scope and strategy membership; use `export/campaign_metrics` only as separate totals.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without explicit match type keep Unknown; do not derive type from brackets/quotes. Without compatible goals omit pooled performance comparisons.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Parse the explicit BROAD/PHRASE/EXACT field; preserve Unknown values.
   UI punctuation in keyword text is not the authoritative match-type source.

3. Deduplicate IDs at the declared metric grain and aggregate sums within campaign/objective.
   Calculate distinct-keyword count share separately from cost and conversion shares.

4. Derive CTR, CPC, CVR, CPA and ROAS from summed numerators/denominators.
   Separate conversion-count and value-led campaigns; never average row-level CPAs.

5. Apply mature sample gates to both compared types before interpreting disparities.
   Account-wide shares can reflect brand, geography, product and goal mix rather than match-type effects.

6. Review target deviations only with an applicable target or comparable mature benchmark.
   Without either retain descriptive distribution, not an invented target.

7. Delegate strategy/control fit to 022 and query relevance to 023.
   No minimum broad percentage, exact share or mandatory match-type diversification applies.

8. Propose an optional scoped experiment only for a business-defined reach/control question.
   Historical distribution does not establish incremental conversions from another match type.

## Thresholds

Resolve [PARAMETERS.md](../_resources/PARAMETERS.md) and profile overrides before screening.
Numerical decision cutoffs below are triage heuristics, not platform requirements or causal proof.
Compare CTR only with {{min_impressions}} impressions and conversion rates with {{min_clicks}} clicks
on each side; CPA/ROAS comparisons require {{min_conversions}} mature conversions on each side.
Zero-conversion screening is an exception to the conversion-count gate, not permission to pause:
require working tracking, a mature comparable window, relevance review and {{spend_floor}}.
Do not divide by zero; absent targets use an applicable profile target, otherwise omit target comparisons.

| Condition | Severity |
|-----------|----------|
| Mature type CPA >2× an applicable target or comparable benchmark after context review | Warning |
| Single-type concentration, no broad match or unequal spend/conversion shares alone | Info |
| Unknown match type, absent target or insufficient comparable sample | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Show denominators, objective cohorts and descriptive distributions with no adoption score.
