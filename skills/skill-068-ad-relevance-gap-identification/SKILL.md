---
name: skill-068-ad-relevance-gap-identification
description: "Separate observed ad-relevance ratings from semantic judgment and evidence-led restructuring proposals."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: export
  related: [skill-065-quality-score-component-breakdown, skill-067-expected-ctr-improvement, skill-069-landing-page-experience-assessment]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 068: Ad Relevance Gap Identification

## Purpose

Identify mismatches between intended queries, offers and eligible ad copy. Deterministic
work inventories ratings, IDs and coverage; semantic relevance remains explicit analyst
judgment supported by quotes, not an exact-token rule disguised as truth.
QS is diagnostic, not an auction input or business KPI: [Google Ads: About Quality Score](https://support.google.com/google-ads/answer/6167118?hl=en).

## Data Requirements

**Applicability:** Search keyword/ad-group intent review. A reported component rating
is a prioritization signal, not proof of mismatch for every query or served creative.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) files:
- `account`, `campaigns`, `ad_groups`: stable IDs, statuses, goals and export completeness.
- `keywords`: criterion IDs, text/match type, ad relevance/QS ratings and parent IDs.
- `keyword_metrics`: same-ID/window impressions, clicks, cost, conversions and value.
- `ads`: ad IDs/parents, status/approval, headlines/descriptions, pins and final URLs;
  eligible creative pool and constraints, not a guaranteed served RSA combination.
- Client profile campaign_objectives, brand_terms, competitor_terms and excluded_intents.
- Optional `search_terms` with matched keyword criterion IDs and reported query coverage
  provides observed intent; absence of disclosed terms does not prove no query variation.
- Optional `assets` with inherited associations provides supporting offer/benefit content.
  To make claims about page content, request the external evidence declared in 069;
  an ad final URL alone is not a page-content assessment.

**Missing inputs:** Missing ads blocks semantic ad evaluation but not rating inventory.
Missing owner objectives means desired intent is uncertain; quote alternatives rather than
infer intent from names. Missing query coverage limits query-level conclusions only.

## Analysis Steps

1. Join keywords and eligible ads by account/campaign/ad-group IDs. Separate enabled,
   paused, disapproved and missing ads; a settings join establishes eligibility, not serving.
2. Inventory Below Average, Average, Above Average and unavailable ad relevance. Rank
   weak-rating rows by mature cost exposure with explicit rated/total denominators.
3. Build analyst-reviewed intent themes using keyword meaning, observed search terms and
   declared business objectives. Retain ambiguous, brand, competitor and mixed-intent cases.
   Keyword counts and lexical similarity are discovery aids, never intent classifications.
4. Map each theme to eligible ad promises, product/service coverage and calls to action.
   Quote the keyword/query and exact copy supporting a gap; record the reviewer's reasoning,
   uncertainty and plausible alternative interpretation. Synonyms and paraphrases can fit.
5. Distinguish deterministic observations (rating, missing asset field, ad eligibility,
   literal-token presence) from semantic conclusions (intent mismatch, overly generic copy).
   Missing the exact keyword from headlines/descriptions is not itself an adverse finding.
6. Propose a copy improvement first when the offer is shared. Propose an ad-group split only
   for materially different intent/offer/landing experience needing independent messaging,
   with enough sustained volume and an owner-confirmed operational rationale.
   More than 20 keywords, mixed words or a low rating alone do not require restructuring.
7. Prioritize observed, material mismatches without asserting recoverable spend or QS uplift.
   Recommend an owner-reviewed creative/structure hypothesis with qualified conversion
   guardrails and a mature evaluation window. Keep diagnostic component findings linked
   to 065/067 instead of duplicating their spend exposure as additional loss.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Below Average ad relevance and cost >= {{spend_material}} | Warning |
| Evidence-supported semantic mismatch with material mature exposure | Warning |
| Potential copy/theme improvement requiring owner/analyst confirmation | Info |
| Literal keyword absent, keyword-count heuristic or valid paraphrase | Info |
| Missing ads, intent evidence, ratings or sufficient comparison sample | Info |

No rating, keyword count or literal-match condition is Critical. Monetary gates are triage.
Use [PARAMETERS](../_resources/PARAMETERS.md): {{min_impressions}} for CTR,
{{min_clicks}} for CVR and {{min_conversions}} for CPA/ROAS on both mature comparable sides.
Do not let a semantic review claim causal performance loss from an observational comparison.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Add theme-to-keyword/ad mapping, quoted evidence, deterministic observation versus analyst
judgment, ambiguity, owner intent and explicit split rationale where a split is proposed.
