---
name: skill-023-close-variant-query-expansion-monitoring
description: "Map reported queries to triggering keywords and review lexical differences separately from business relevance."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  merged_from: [skill-120-close-variant-match-expansion-monitoring]
  related: [skill-013-search-term-mining-keywords, skill-014-search-term-mining-negatives, skill-015-ngram-analysis, skill-017-negative-keyword-conflict-detection]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx062 | exact_only_restriction inputs/step (index #62)"
---
# Skill 023: Close Variant and Query Expansion Review

## Purpose

Map reported queries to triggering keywords and review lexical differences separately from business relevance.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search queries with explicit keyword IDs/report match classifications; do not infer close-variant origin solely from spelling.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`, `export/ad_groups`, `export/keywords`, `export/search_terms`.
- `export/negative_keywords`, `export/shared_negative_lists`, including effective scope and list links.
- Query metrics at account/campaign/ad_group/query/matched_keyword/window plus declared segments;
  use matched keyword ID, explicit keyword match type and report match classification where available.
- Profile brand_terms, competitor_terms, excluded_intents and campaign-specific goals; reporting filters/completeness.
- `export/keyword_metrics` is optional contextual evidence, never substituted for a query's metrics.
- Opt-in literal-only request: `profile.exact_only_keyword_ids` (list of keyword IDs) with `export/keywords` `status` and `export/search_terms` `matched_keyword_id`/`conversions`.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without trigger IDs keep ad-group-level analysis only; without relevance context mark Unknown; missing shared-list links blocks safe negative proposals.
Without `exact_only_keyword_ids` the literal-only check is not applicable; without keyword `status` or trigger IDs it is skipped.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

3. Join by keyword ID and preserve keyword match type separately from report query-match classification.
   Deduplicate only complete source-row keys; keyword aggregates cannot replace query metrics.

4. Classify lexical relation reproducibly: Literal = normalized token sequence equal;
   Reorder = same token multiset/different order; Other lexical difference = remaining cases. Preserve supplied platform classification.

5. Separately assess relevance: Supported = profile offer/task match; Excluded = explicit excluded intent;
   Ambiguous = multiple plausible tasks; Unknown = missing context. Record evidence phrase and analyst rationale.

6. Misspelling/plural/same-meaning labels require supplied classification or documented analyst evidence.
   Do not present subjective relevance scores or lexical similarity as deterministic intent truth.

7. Aggregate mature query metrics by class within keyword/campaign/objective, with both-sided sample gates.
   Report irrelevant share among reported clicks plus total campaign reporting coverage; hidden terms remain unknown.

8. Screen explicit excluded-intent or mature zero-conversion exposure contextually, never as automatic Critical.
   Compare class CPA/ROAS as well as CVR; lower CVR alone is not an economic defect.

9. Route negative proposals to 014 after 017 active-positive/shared-list scope review; additions belong to 013.
   Pattern opportunities belong to 015; dedupe by scope + normalized candidate + match type.

10. For broad/phrase narrowing propose a controlled relevance hypothesis, not a guaranteed cure.
   Exact cannot be narrowed to a stricter positive match type and can still serve close variants.

11. Only for keywords in `profile.exact_only_keyword_ids`, propose ad-group EXACT negatives for their reported non-literal queries; `finalize` rejects any negative that is not EXACT at the reviewed ad group, is not a listed query, or blocks the keyword's literal text, a converting query or another active keyword.

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
| Explicit excluded-intent reported traffic has material observed exposure | Warning |
| Mature zero-conversion query at {{spend_floor}} after tracking/relevance review | Warning |
| Many variants, >50% variant share, converting unadded queries or low CVR alone | Info |
| Owner-requested literal-only restriction (`exact_only_keyword_ids`) whose EXACT negatives passed `finalize` | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include lexical class, platform classification, relevance evidence, coverage and canonical proposal owner.
