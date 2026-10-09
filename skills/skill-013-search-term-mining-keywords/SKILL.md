---
name: skill-013-search-term-mining-keywords
description: "Identify relevant reported queries where an explicit keyword may improve control, without claiming incremental reach or mandated expansion."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-014-search-term-mining-negatives, skill-127-trending-search-term-detection, skill-015-ngram-analysis, skill-023-close-variant-query-expansion-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 013: Search Term Mining for New Keywords

## Purpose

Identify relevant reported queries where an explicit keyword may improve control, without claiming incremental reach or mandated expansion.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search campaigns with reported queries and known keyword inventory.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`, `export/ad_groups`, `export/keywords`, `export/search_terms`.
- `export/negative_keywords`, `export/shared_negative_lists`, including effective scope and list links.
- Query metrics at account/campaign/ad_group/query/matched_keyword/window plus declared segments;
  use matched keyword ID, explicit keyword match type and report match classification where available.
- Profile brand_terms, competitor_terms, excluded_intents and campaign-specific goals; reporting filters/completeness.
- `export/keyword_metrics` is optional contextual evidence, never substituted for a query's metrics.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Missing keyword IDs permits only ad-group-level candidates; absent goals/targets prevents economic ranking, not descriptive mining.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

3. Normalize case/spacing and deduplicate query rows only at their complete reported grain.
   Aggregate query metrics within the intended campaign/ad-group objective; preserve distinct trigger mappings.

4. Use reported added/excluded status as a hint, then check active keywords by ID/text/match/scope.
   Distinguish exact existing text, observed close-variant coverage and uncertain semantic coverage.

5. Classify relevance against the approved offer, brand strategy and exclusions before ranking.
   Conversions alone do not establish a query is strategically desirable.

6. For CPA ranking use campaign target, applicable profile target, or a mature same-goal benchmark.
   Without one show observed metrics; three conversions never justify a Critical finding or broad expansion.

7. Describe the specific control benefit: reporting, message/landing alignment or intended routing.
   The query already served; adding it does not itself create new reach or guarantee which keyword serves.

8. Check effective negatives using 017 and coordinate with 014/015/023 before any candidate proposal.
   A keyword proposal conflicting with desired exclusions needs owner resolution.

9. Suggest match type contextually; exact is not immune to close variants and broader reach needs a hypothesis.
   Smart Bidding does not create keyword-level CPC control; no automatic keyword bid recommendations.

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
| Relevant unadded query with mature favorable goal-relative outcomes and a documented control need | Info |
| Converting or high-volume reported query without established incremental/control benefit | Info |
| Unknown relevance, missing inventory or insufficient sample | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Use candidate key campaign_id/ad_group_id/normalized_query/proposed_match_type; assign additions to 013 only.
