---
name: skill-005-search-partners-performance
description: "Compare Search Partners outcomes with Google Search within comparable campaigns without treating conversion rate as profitability."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 005: Search Partners Performance Review

## Purpose

Compare Search Partners outcomes with Google Search within comparable campaigns without treating conversion rate as profitability.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search campaigns with partner eligibility and explicit network evidence.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`: IDs, channel, network settings, goal and target.
- `export/custom/network_daily.csv` from Campaigns UI report segmented by day/network, bounded to export dates:
  one account_id/campaign_id/date/ad_network_type row; impressions, clicks, cost, conversions,
  conversion_value, goal_scope, conversion_date_basis. Declare units, filters and completeness.
- Distinguish SEARCH, SEARCH_PARTNERS and CONTENT using the export's explicit network mapping.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without segmented metrics retain settings inventory only; without comparable conversion/value scope omit economic comparisons.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Reconcile summed network cost/clicks to the same campaign/date totals.
   Explain omitted networks and report completeness; unknown network values remain separate.

3. Within each campaign compute cost/click, conversions/click, cost/conversion and value/cost from sums.
   Zero denominators are unavailable, not zero; exclude immature days consistently.

4. Compare partner and Google Search outcomes against the campaign objective and approved target.
   Lower conversion rate may coexist with better CPA or ROAS; do not rank networks on CVR alone.

5. Use a 2× CPA ratio only as a contextual review screen after both sides meet mature conversion gates.
   For value-led objectives prioritize ROAS and value quality; do not pool unrelated campaigns.

6. Screen zero partner conversions only at {{spend_floor}} with working tracking and relevance review.
   Investigate lead quality, conversion lag and network mix rather than prescribe immediate exclusion.

7. Offer monitoring or an owner-approved network-setting test if economic underperformance is sustained.
   Verify the control applies to this campaign; separate temporal change from a randomized test.

8. Retain profitable/strategically useful partner traffic; absence of partner adoption is not a defect.
   Historical network cost is exposure, not savings from switching it off.

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
| Mature partner CPA >2× comparable Google CPA and worse than applicable objective benchmark | Warning |
| Zero partner conversions at {{spend_floor}} after tracking/maturity/relevance checks | Warning |
| Lower CVR alone, no benchmark, or insufficient sample | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include a network metric table, objective, exact ratios and covered date range.
