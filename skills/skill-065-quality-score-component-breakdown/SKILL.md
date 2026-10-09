---
name: skill-065-quality-score-component-breakdown
description: "Prioritize separate QS component diagnostics with explicit coverage and no automatic restructuring."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: export
  related: [skill-064-quality-score-distribution-analysis, skill-066-historical-quality-score-trend, skill-067-expected-ctr-improvement, skill-068-ad-relevance-gap-identification, skill-069-landing-page-experience-assessment]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 065: Quality Score Component Breakdown

## Purpose

Inventory expected CTR, ad relevance and landing-page experience separately to route
investigation. A component rating identifies a diagnostic review area; it does not prove
causal contribution to CPC, conversion loss or the need for an account restructure.
Source: [Google Ads: About Quality Score](https://support.google.com/google-ads/answer/6167118?hl=en).

## Data Requirements

**Applicability:** Search keywords exposing QS component ratings. Other channels and
unavailable components are not scored; current ratings are snapshots, not period averages.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) files:
- `account` for snapshot, window, metric units and completeness.
- `campaigns`, `ad_groups` and `keywords` with stable IDs, statuses, match type,
  QS, expected CTR, ad relevance and landing-page experience ratings.
- `keyword_metrics` with matching IDs, impressions, clicks, cost, conversions and value
  over the same mature window; profile goals and [PARAMETERS](../_resources/PARAMETERS.md).
- Optional detailed copy/landing evidence is requested by 067/068/069. Current component
  triage does not require page-speed tests or historical reports.
- Optional historical explanation uses 066's `export/custom/quality_score_history.csv`;
  current component snapshots cannot establish when a decline happened.

**Missing inputs:** Missing components remain unknown independently, not Below Average.
Missing cost blocks high-spend classification only; missing history blocks trend claims.
Missing ads/pages prevents a causal remedy, not the component inventory and routing.

## Analysis Steps

1. Build the keyword universe by account/campaign/ad-group/criterion IDs, separate active
   and paused keywords, and join metrics without duplicating spend across rows/segments.
2. For EACH component count Above Average, Average, Below Average and unavailable.
   Report rated and total denominators separately; no cross-component substitution for nulls.
3. Form mutually exclusive rating-combination groups for the three components. A keyword
   may appear in multiple component views, but total exposed spend is the union of IDs;
   never sum overlapping component spend as total loss.
4. Define high spend explicitly as criterion cost >= {{spend_high}} in the declared mature
   period. Report campaign-level cost and keyword coverage before describing a pattern.
   Prefer exact prevalence (affected/rated, affected/all) to an unqualified account-wide label.
5. As a triage convention, call a pattern widespread only when the same weak component
   affects >50% of rated keywords in at least two eligible campaigns and report coverage.
   A single-campaign account can have a within-campaign pattern, not cross-campaign proof.
6. Prioritize weak-component high-spend keywords for focused review. Two or three Below
   Average ratings increase diagnostic breadth but do not justify Critical or full restructure.
   Ratings are not causal weights; do not claim which component mathematically caused QS.
7. Assign one lead investigation per keyword: 067 expected CTR, 068 semantic ad relevance,
   069 landing-page diagnostic. Preserve secondary tags for combined issues and avoid duplicate
   financial impact. Use 064 for distribution/exposure and 066 for actual historical trends.
   Proposals should identify a testable copy/page question, not an automatic structural split.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Any Below Average component and cost >= {{spend_high}} | Warning |
| Widespread weak component with documented material spend exposure | Warning |
| Two or three Below Average components without corroborating business harm | Info |
| Below Average component below spend-priority threshold | Info |
| Missing rating, partial account coverage or insufficient supporting evidence | Info |

The >50%/two-campaign widespread definition and spend cutoffs are triage heuristics.
No component-only condition is Critical. Business metric comparisons require mature
comparable cohorts: {{min_impressions}} for CTR, {{min_clicks}} for CVR and
{{min_conversions}} on both sides for CPA/ROAS; undefined denominators are N/A.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Include rating matrix, each component's denominators, union spend, high-spend definition,
exact pattern scope, diagnostic lead/secondary owners and evidence needed for remedies.
