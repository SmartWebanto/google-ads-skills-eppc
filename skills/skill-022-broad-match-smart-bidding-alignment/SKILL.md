---
name: skill-022-broad-match-smart-bidding-alignment
description: "Review broad-match use against bidding objectives, measurement readiness and observed relevance without prescribing universal migration."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-012-keyword-match-type-distribution, skill-023-close-variant-query-expansion-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 022: Broad Match and Bidding Context

## Purpose

Review broad-match use against bidding objectives, measurement readiness and observed relevance without prescribing universal migration.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search campaigns with explicit match types and resolved campaign/portfolio strategy; historical exports retain their dated platform context.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/keywords`, `export/keyword_metrics`, `export/bidding_strategies`,
  `export/search_terms`, `export/campaign_metrics`, `export/conversion_actions`.
- Campaign objective, selected conversion goals, tracking health, applicable target and portfolio membership.
- Explicit strategy type/effective date and account snapshot; missing goal-selection evidence limits readiness conclusions.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without effective strategy leave classification Unknown; without measurement/goals do not recommend migration; missing query data prevents relevance conclusions.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Resolve campaign strategy through its strategy ID/portfolio membership before classifying controls.
   Conversion/value Smart Bidding includes target CPA/ROAS and maximize conversions/value variants.

3. Distinguish Manual CPC, Maximize Clicks and Target Impression Share by their actual objectives.
   Do not treat non-conversion objectives as incorrectly configured merely because broad match exists.

4. Treat ECPC in old exports as historical evidence: record date, channel and supplied control status.
   Do not recommend enabling ECPC or assume current availability from a legacy strategy label.

5. Inventory broad keyword count and spend within campaign context; distribution belongs to 012.
   Neither high broad share with Manual CPC nor zero broad with Smart Bidding is a quota violation.

6. Inspect mature broad-triggered query relevance and outcomes against approved goals.
   Cross-strategy CPA differences are observational and confounded by brand/product/market mix.

7. Review conversion/value measurement readiness before suggesting a Smart Bidding trial.
   Broken tracking is a measurement issue, not a reason to force automated optimization.

8. Offer optional pairing/match-type tests only for a documented control or reach need with safeguards.
   Preserve legitimate manual and non-conversion setups; never promise improved efficiency from migration.

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
| Mature broad-query exposure contradicts approved relevance/objective requirements | Warning |
| Proposed conversion optimization lacks confirmed measurement readiness | Info |
| Broad/manual combination, any broad share or absence of broad alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Return strategy × objective × match inventory and prerequisites, not a migration score.
