---
name: skill-015-ngram-analysis
description: "Aggregate deduplicated query patterns within business context to identify hypotheses, not additive savings or automatic phrase exclusions."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-013-search-term-mining-keywords, skill-014-search-term-mining-negatives, skill-017-negative-keyword-conflict-detection]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 015: N-gram Query Pattern Analysis

## Purpose

Aggregate deduplicated query patterns within business context to identify hypotheses, not additive savings or automatic phrase exclusions.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Reported Search queries with consistent tokenization and campaign-specific goals.

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

**Missing inputs:** Without query identity/grain do not aggregate; without positive/negative inventory retain pattern discovery but skip exclusion proposals.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

3. Normalize Unicode/case and whitespace; tokenize using a declared language-aware rule.
   Preserve original query text and order; separate punctuation deliberately and do not silently stem or remove stop words.

4. Generate contiguous 1-, 2- and 3-token sequences as a set per source query row.
   A repeated token/phrase contributes that row only once to the same n-gram, not once per occurrence.

5. Deduplicate duplicate exports at the full query/trigger/segment/window grain before summing.
   Aggregate within campaign/objective; count distinct normalized query strings separately from source-row count.

6. Calculate cost, conversions and value once per row/n-gram membership; derive rates from sums.
   Patterns overlap: union the underlying row IDs for combined exposure, never sum n-gram totals.

7. Screen zero-conversion patterns at {{spend_floor}} after maturity/tracking review.
   Ten zero-conversion terms with negligible spend are not a severe issue; query count is descriptive.

8. For positive patterns apply mature target/benchmark comparisons; no target means no favorable-CPA claim.
   An n-gram can mix desired and undesired meanings; inspect contributing examples and goal context.

9. Before any phrase proposal review ordered containment, existing scope and desirable query/keyword conflicts using 017.
   Route final negative decisions to 014 and keyword additions to 013; do not create duplicate recommendations.

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
| Mature zero-conversion pattern at {{spend_floor}} with relevance review | Warning |
| Pattern supported by mature favorable goal-relative outcomes | Info |
| Pattern frequency, low-spend zero-conversion cluster or unknown context alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Return n-gram, tokenizer rule, campaign/objective, distinct terms, contributing row keys and non-additive exposure.
