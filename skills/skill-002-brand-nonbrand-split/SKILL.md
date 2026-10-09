---
name: skill-002-brand-nonbrand-split
description: "Classify brand traffic and review whether observed routing matches the business-defined brand strategy."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: export
  related: [skill-017-negative-keyword-conflict-detection]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 002: Brand and Non-Brand Routing Review

## Purpose

Classify brand traffic and review whether observed routing matches the business-defined brand strategy.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search keyword/query reporting; other channels require their own brand-control evidence.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`, `export/keywords`, `export/search_terms`.
- `export/negative_keywords`, `export/shared_negative_lists`, including list members and campaign links.
- Profile `brand_terms`, `competitor_terms`, approved aliases and intended campaign brand roles.
- Query rows require campaign/ad_group IDs and matched keyword ID where available; totals use the same scope.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without brand_terms do not infer brand from account name; leave classification unknown. Without negative associations skip protection conclusions.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Normalize case/whitespace while preserving token boundaries and multiword order.
   Apply brand_terms before competitor_terms; flag collisions and ambiguous names. Do not invent misspellings.

3. Classify keywords and reported queries as Brand, Competitor, Non-brand or Unknown.
   Names provide hints; only approved campaign roles establish intended routing.

4. Inventory mixed keywords without prescribing separation; review independent reporting/budget needs.
   Mixed inventory does not prove bidding distortion.

5. Calculate observed brand clicks / compatible campaign clicks and brand clicks / reported-query clicks.
   Report query click/cost coverage against campaign totals; hidden terms preclude a complete leakage estimate.

6. Resolve campaign, ad-group and attached shared-list negatives using 017 matching semantics.
   Exact negatives block only literal queries; phrase protection requires contiguous ordered tokens.

7. Compare observed routing with approved intent and settings timing.
   Traffic predating the current negative does not prove it failed.

8. Before exclusion proposals, review desired queries and active keywords in every proposed scope.
   Prefer narrower scope or separate reporting when brand traffic is intentional elsewhere.

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
| Observed routing contradicts approved role with material exposure | Warning |
| Brand clicks >5% of compatible campaign clicks with {{min_clicks}} campaign clicks, pending intent review | Info |
| Mixed keywords or absence of shared brand list alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include approved classification terms, intended role, numerator/denominator and coverage.
