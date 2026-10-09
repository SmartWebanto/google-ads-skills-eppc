---
name: skill-014-search-term-mining-negatives
description: "Identify business-inappropriate query exposure and contextual negative proposals after scope and desired-traffic checks."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-013-search-term-mining-keywords, skill-127-trending-search-term-detection, skill-017-negative-keyword-conflict-detection, skill-015-ngram-analysis, skill-023-close-variant-query-expansion-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 014: Search Term Mining for Negatives

## Purpose

Identify business-inappropriate query exposure and contextual negative proposals after scope and desired-traffic checks.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search query data and negative controls supported by the campaign type; never extrapolate to every channel.

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

**Missing inputs:** Without approved excluded intents or relevance context classify uncertain terms as review candidates; missing positive/negative inventory blocks safe exclusion proposals.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

3. Screen mature zero-conversion queries at {{spend_floor}} with working tracking.
   This is exposure for review, not proof of waste; check objective, conversion lag and relevance.

4. Match explicit business exclusions with brand_terms precedence over competitor_terms.
   Jobs, free, research, support and competitors are not universal waste; preserve intentional traffic.

5. Use low CTR only as a sampled engagement diagnostic, never standalone negative justification.
   High CPA comparisons need mature samples and an applicable target/benchmark.

6. Resolve existing campaign/ad-group/attached-list coverage under 017 literal-query semantics.
   Compare metric window to negative effective/snapshot date; current protection may postdate historical exposure.

7. For each proposed negative run a local scope review against active positive texts and observed desirable queries.
   Phrase requires contiguous ordered tokens; exact only literal equality; broad requires all tokens regardless of order.

8. Choose the narrowest justified scope and match type; phrase/shared-list proposals require every affected campaign reviewed.
   Show desired queries that would be blocked, including converting terms; do not recommend removal of intentional routing.

9. Deduplicate proposals with 015/023 by normalized negative, match type and scope.
   014 owns the final negative proposal; economic exposure is the union of affected query rows, not stacked totals.

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
| Confirmed business-excluded query with material observed exposure and reviewed scope | Warning |
| Mature zero-conversion query at {{spend_floor}} after tracking/relevance review | Warning |
| Generic token, low CTR alone, uncertain relevance or insufficient sample | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Report exact blocked/desirable query examples, effective scope and review owner; no guaranteed savings.
