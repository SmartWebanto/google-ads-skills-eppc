---
name: skill-016-negative-keyword-list-completeness
description: "Review business-specific negative protection across effective scopes without universal waste lists or shared-list quotas."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  merged_from: [skill-113-proactive-negative-keyword-list-building]
  related: [skill-014-search-term-mining-negatives, skill-017-negative-keyword-conflict-detection]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx059 | negative_upload_validation inputs/step (index #59)"
---
# Skill 016: Negative Coverage Governance

## Purpose

Review business-specific negative protection across effective scopes without universal waste lists or shared-list quotas.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search and Standard Shopping campaigns where supplied negative controls apply; other channels require separate supported-control evidence.

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
- Optional `export/external/negative_upload_list` (opt-in): customer_id (optional in single-account exports), campaign_id,
  ad_group_id (optional), level campaign|ad_group|shared_list, list_id (for shared_list), text, match_type.

**Missing inputs:** Without approved exclusions no completeness verdict is possible; without list membership/links leave effective shared protection unknown.
Without `external/negative_upload_list` the upload validation is skipped; it is never inferred from other files.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Build an exclusion-intent matrix per eligible campaign from approved business and routing requirements.
   Jobs/free/DIY/research/support/competitors may be desirable depending on the business.

3. Apply approved brand_terms before competitor terms and preserve campaign-specific exceptions.
   A brand/competitor name collision needs review, not a blanket account exclusion.

4. Inventory campaign, ad-group and attached shared negatives with explicit match types.
   Equivalent campaign-level protection can satisfy the requirement without a shared list.

5. For each intended exclusion evaluate literal-query coverage under 017 rules, not substring guesses.
   Exact protects only the exact query; phrase is ordered contiguous containment; broad is all-word matching.

6. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

7. Check observed excluded-intent query exposure against settings effective dates and current protection.
   An observed historical query does not prove a current negative failed.

8. Before suggesting a shared list, evaluate every proposed campaign for desirable-query and active-keyword conflicts.
   Do not apply Search/Shopping findings to all account campaigns or condemn all broad negatives.

9. Offer narrow, owner-reviewed coverage proposals; consolidate final new-negative recommendations under 014.
   No minimum negative count, all-campaign shared list or universal waste category is required.

10. When an upload list is supplied, validate each row for this account only; never upload or push it.
    Require explicit match type and an active target; flag duplicate rows, existing effective duplicates and literal
    blocks of active keyword text, converting reported queries or brand_terms in scope; operators or > 10 words are partial.

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
| Approved exclusion lacks effective protection and has material observed exposure | Warning |
| Missing policy, list associations or reporting coverage | Info |
| No shared lists, low negative count or broad negatives alone | Info |
| Supplied upload negative literally blocks an active keyword, converting query or brand term in its scope | Warning |
| Supplied upload row lacks explicit match type or an active target, or duplicates a row or existing negative | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include exclusion intent × campaign × effective protection matrix and scoped exceptions.
