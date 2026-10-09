---
name: skill-067-expected-ctr-improvement
description: "Prioritize expected-CTR diagnostics and contextual copy/asset review without literal keyword rules."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: export
  related: [skill-064-quality-score-distribution-analysis, skill-065-quality-score-component-breakdown, skill-066-historical-quality-score-trend, skill-068-ad-relevance-gap-identification]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 067: Expected CTR Improvement

## Purpose

Review Below Average expected CTR as a diagnostic signal and propose relevant creative
investigation. Expected CTR is not observed CTR; QS is not an auction input or direct CPC
savings formula. Literal keyword absence from a headline does not establish poor relevance.
Source: [Google Ads: About Quality Score](https://support.google.com/google-ads/answer/6167118?hl=en).

## Data Requirements

**Applicability:** Search keywords with expected-CTR ratings and eligible ads. Asset
availability and useful types depend on campaign, business objectives and policy.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) base files:
- `account`, `campaigns` and `ad_groups`: IDs, status/channel/goals, dates and completeness.
- `keywords` and `keyword_metrics`: criterion IDs, text/match type, expected CTR,
  impressions, clicks, cost, conversions and value over the same mature window.
- `ads` and `ad_metrics`: ad IDs, parent IDs, copy, pins, status/approval, final URLs
  and observed metrics; an eligible RSA asset pool is not a known rendered impression.
- For asset-gap review, `assets` with account/campaign/ad-group associations,
  asset IDs/type, status/approval and eligibility; inherited account/campaign assets count.
- Optional `search_terms` with query-to-criterion joins and disclosure coverage for intent.
  Client profile brand_terms, campaign_objectives and excluded_intents inform contextual review.
- For segmented CTR comparison if base segments are absent, request
  `export/custom/keyword_ctr_context.csv` from Google Ads keyword reporting:
  account_id, campaign_id, ad_group_id, criterion_id, date, device, network, impressions,
  clicks, cost, conversions, conversion_value, source; one row per full listed key.
  Use the same mature window and retain all segments, not an arbitrary top-N sample.

**Missing inputs:** Missing asset associations blocks absence claims, not expected-CTR
inventory. Missing segmented context permits descriptive CTR only, not a fair peer verdict.
Missing search terms leaves query intent partially observed; missing ratings are not low CTR.

## Analysis Steps

1. Select reported Below Average expected CTR and rank by current-snapshot cost exposure.
   Include unknown ratings separately and report eligible/rated keyword denominators.
2. Calculate actual CTR = clicks/impressions without confusing it with Google's expected
   CTR rating. Compare only same-goal, brand/nonbrand, network/device and similar query
   contexts; use both sample gates. There is no universal 1% Search CTR failure threshold.
3. Map keywords to eligible ad pools by stable ad-group IDs, considering status, approval
   and pins. Do not claim every keyword served every ad or every RSA asset combination.
4. Review benefit specificity, user intent, differentiation, calls to action and permitted
   claims. Quote evidence and label semantic conclusions as analyst judgment. Synonyms,
   brand-led copy and paraphrases can be relevant without literal keyword insertion.
5. Review applicable asset types across effective account/campaign/ad-group associations.
   Distinguish unavailable, disapproved and absent from eligible inherited assets; ordinary
   optional asset absence is an opportunity, not an account failure or guaranteed CTR gain.
6. Prioritize a concrete copy hypothesis when a weak rating and mature cost warrant review.
   Describe proposed creative alternatives and success metric; do not force keyword insertion,
   automatic restructuring or a CTR-maximizing change that harms qualified conversions.
7. Request an owner-reviewed comparison with conversion-quality guardrails and a defined
   mature review window. Ordinary ad rotation is not a randomized causal experiment.
   Route semantic theme review to 068 and component/distribution summaries to 065/064.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Below Average expected CTR and cost >= {{spend_high}} | Warning |
| Documented contextual copy gap with material mature exposure | Warning |
| Optional relevant asset opportunity or untested copy hypothesis | Info |
| Literal keyword absence, low raw CTR without context or unavailable associations | Info |
| Missing rating/context or insufficient business comparison sample | Info |

No expected-CTR-only or keyword-text condition is Critical. Cost cutoffs are triage heuristics.
Apply {{min_impressions}} to both CTR sides, {{min_clicks}} to CVR and
{{min_conversions}} to CPA/ROAS under [PARAMETERS](../_resources/PARAMETERS.md).
Exclude reporting lag and incomplete days; undefined ratios are N/A, never a failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Add expected versus actual CTR, comparator context, ad/asset IDs and inheritance,
quoted copy evidence, analyst judgment label and an owner-reviewed creative hypothesis.
