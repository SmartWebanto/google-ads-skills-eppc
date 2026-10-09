---
name: skill-017-negative-keyword-conflict-detection
description: "Detect literal-query blocks and potential desired-traffic conflicts with correct negative match semantics and scope."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-014-search-term-mining-negatives, skill-016-negative-keyword-list-completeness]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 017: Negative Keyword Conflict Detection

## Purpose

Detect literal-query blocks and potential desired-traffic conflicts with correct negative match semantics and scope.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Supported Search/Shopping negative scopes; positive keyword conflict review applies to keyword-based Search.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/ad_groups`, `export/keywords`, `export/negative_keywords`,
  `export/shared_negative_lists`, including complete members, match types and campaign associations.
- Profile approved desired/excluded intents and routing exceptions; keyword/negative IDs and entity statuses.
- Optional `export/search_terms`, `export/campaign_metrics` for observed exposure, not blocked-traffic estimation.
- For confirmed current blockage: `export/custom/query_eligibility.csv`, one query/scope/check-time row
  from supplied Ads diagnosis UI; account_id, campaign_id, ad_group_id, keyword_id, query,
  checked_at, negative_id, diagnosis, intended_eligible, evidence_ref. No inferred lost impressions.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Missing associations prevents complete scope evaluation; missing desired-query intent means potential conflict only. Without diagnosis/material impact do not claim total suppression.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Resolve effective negatives per eligible ad group: its negatives, parent campaign negatives and attached shared-list members.
   Include account-level negatives if supplied; otherwise explicitly limit coverage. Removed/inactive entities are separate.

3. Normalize case and whitespace while retaining original punctuation/language evidence.
   Do not expand to synonyms/plurals; Google documents casing/misspelling handling, but a local literal matcher cannot reproduce that service.

4. Evaluate a concrete query q against a negative n: EXACT requires equal complete token sequence;
   PHRASE requires the entire n sequence contiguously inside q in the same order; BROAD requires all n words in q in any order.

5. Containment goes from negative into query, not the reverse: phrase “red shoes” blocks “buy red shoes”,
   not “shoes red” or “red running shoes”; phrase “buy red shoes” does not block literal “red shoes”.

6. Apply these literal rules only to supported Search-style matching.
   Queries beyond 16 words, symbols/operators and spelling variants need the documented platform rules or current diagnosis; report uncertain coverage rather than guaranteed blocks.

7. Use each active positive keyword text as a hypothetical literal query, not its entire eligible query set.
   A negative [red shoes] blocks literal “red shoes”, but does not prove a positive phrase/broad keyword is wholly suppressed.

8. Distinguish observed desired-query block, literal positive-text conflict, partial coverage and intentional routing.
   Even an exact positive can serve close variants; same-text negative/positive pairs alone do not prove complete loss.

9. Before proposing any removal/narrowing check whether the negative intentionally routes traffic elsewhere.
   Shared-list changes require reviewing all attached campaigns and exclusion obligations.

10. Use current diagnosis only for the checked query/time/scope and report any material impact evidence separately.
   Historical served-query metrics cannot measure the traffic that a negative prevented.

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
| Current diagnosis confirms unintended block of required traffic with independently evidenced material impact | Critical |
| Literal desired query is blocked in applicable scope; full impact not established | Warning |
| Positive-text match only, partial coverage, intentional routing or uncertain semantics | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include negative ID/list/scope, query tokens, rule used, positive match type and classification; no automatic removal.
Source: [Google negative keyword match rules](https://support.google.com/google-ads/answer/2453972?hl=en).
