---
name: skill-018-duplicate-keyword-detection
description: "Inventory duplicate keywords and multi-trigger reported queries without inferring self-competition, wasted spend or a wrong auction winner."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  merged_from: [skill-019-keyword-cannibalization-analysis]
  related: [skill-017-negative-keyword-conflict-detection]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 018: Duplicate Keywords and Observed Query Routing

## Purpose

Inventory duplicate keywords and multi-trigger reported queries without inferring self-competition, wasted spend or a wrong auction winner.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search keyword campaigns with comparable targeting and goal context; preserve valid geographic/product/goal-specific copies.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/ad_groups`, `export/keywords`, `export/keyword_metrics`, `export/search_terms`.
- `export/campaign_metrics`, `export/negative_keywords`, `export/shared_negative_lists`, `export/audiences`,
  `export/bid_adjustments` where targeting restrictions apply; include geo, language, schedule, goals and strategy.
- Query rows require matched keyword ID and date/segment scope when available; keyword metric grain is separate.
- Profile intended routing/coverage exceptions. Optional `export/custom/keyword_eligibility_history.csv`:
  account_id, campaign_id, ad_group_id, keyword_id, effective_start, effective_end, status, eligibility,
  geo_scope, language_scope, schedule_scope, goal_scope, source; one keyword/context interval from history/UI.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without targeting context report candidate overlap only; without trigger IDs skip keyword-level routing and retain ad-group mappings. Missing history prevents simultaneous-eligibility conclusions.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Normalize keyword case/whitespace conservatively and group same text plus explicit match type.
   Same text across match types is a variant set, not an exact duplicate; retain all stable IDs.

3. Compare every set across geo, language, schedule, audience restrictions, goals, landing experience and negatives.
   Separate deliberate regional, product, lifecycle, budget and experiment copies from unexplained duplication.

4. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

5. Absorb multi-trigger query review by mapping each normalized query to observed keyword/ad-group/campaign IDs.
   Preserve dates and segments; multiple historical triggers do not establish simultaneous auction eligibility.

6. Compare mature performance only within compatible context and from the correct grain.
   Query CPA is query cost/query conversions, not the triggering keyword aggregate CPA.

7. Report lower-QS and higher-CPA instances as context, not proof the wrong keyword won.
   Duplicates do not establish internal auction competition, wasted cost or a counterfactual CPA improvement.

8. Recommend a consolidation/routing review only for redundant goals/controls or a documented routing mismatch.
   Never keep an instance solely because it has highest Quality Score.

9. Before cross-negative proposals run 017 scope/conflict review; preserve valid coverage and owner exceptions.
   Aggregate exposure via distinct source row keys so duplicate-set/query findings are not double-counted.

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
| Observed query routing contradicts approved routing in compatible context | Warning |
| Unexplained duplicate control burden with a documented operational requirement | Warning |
| Same text in multiple locations/types, multiple triggers or QS difference alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include duplicate-set IDs, targeting differences and query-to-trigger map; no cannibalization score or savings.
Source: [Quality Score is diagnostic, not an auction input](https://support.google.com/google-ads/answer/6167118?hl=en).
