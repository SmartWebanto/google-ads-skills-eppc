---
name: skill-062-audience-minimum-size-monitoring
description: "Monitor actual list-channel eligibility and comparable history rather than blanket minimum sizes."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: custom_query
  related: [skill-061-customer-match-list-health]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 062: Audience Eligibility and Size Monitoring

## Purpose

Monitor list-channel serving readiness and trends using actual platform status, including
inactive and closed lists. There is no universal 1,000-member rule across all list types,
uses and channels; raw reported size is not equivalent to serving eligibility.

## Data Requirements

**Applicability:** Audience lists used or planned for targeting, observation, exclusions or
signals. Distinguish Customer Match, website, app, combined and shared lists by channel.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) `account`,
`campaigns`, `ad_groups`, `campaign_metrics` and `audiences` with list IDs, association
scope/mode, definitions, membership duration/status and intended campaign objectives.
- `export/custom/audience_eligibility.csv` from Audience manager/current channel
  eligibility diagnostics, one row per account_id/list_id/channel/use_type/snapshot_date.
  Columns: list_type, owner_account_id, reported_size, size_precision, size_as_of,
  membership_status, membership_duration_days, eligible, eligibility_reason,
  processing_status, documented_minimum_if_applicable, minimum_source_url,
  minimum_checked_at, source. Include closed/ineligible/shared lists, not OPEN-only rows.
- `export/custom/audience_size_history.csv` from saved Audience manager snapshots:
  same keys and columns as eligibility, at least two observations approximately a week
  apart for a weekly comparison and preferably four complete weekly observations.
  Use actual collection timestamps; declare gaps, changed definitions and size rounding.
- Optional cause investigation: `export/custom/audience_definition_history.csv` from
  Ads change-history/list settings: account_id, list_id, effective_at, change_type,
  old_value, new_value, source; one row per definition/membership/source change.
  For Customer Match upload freshness, use skill-061's explicitly declared log schemas.

**Missing inputs:** Missing historical snapshots blocks trend alerts only, not current
eligibility checks. No channel-specific status/rule means eligibility unknown. Suppressed
or rounded sizes are not exact zeros. Missing definitions blocks causal trend explanation.

## Analysis Steps

1. Enumerate all accessible lists and map ownership plus actual campaign/ad-group uses.
   Separate planned, inactive, observation, exclusion and hard-targeting associations;
   a signal or observation list does not impose the same delivery restriction as targeting.
2. Use current reported eligible/status/reason as primary evidence. If a current documented
   minimum exists, compare the correctly defined active population for that list/channel/use.
   Raw total members may differ from active eligible users; do not override status by guess.
3. Retain closed membership status separately: closed can mean no new members, not an
   empty or immediately unusable list. Review membership duration and processing state.
4. Join history by stable list/channel/use keys. Weekly relative change = (new_size -
   old_size) / old_size with positive old_size and comparable measurement precision.
   Record actual elapsed days; do not call an arbitrary interval a weekly decline.
5. Review >20% decline over comparable seven-day observations as a triage warning only
   when beyond rounding/suppression uncertainty and relevant to an active planned use.
   Check definition, membership expiry, upload/source changes and seasonality before cause.
6. Map ineligibility to delivery dependence. Another eligible targeted list or broad reach
   may preserve delivery; a platform status alone cannot prove the whole campaign stopped.
   Critical requires observed material delivery failure and confirmed dependency evidence.
7. Propose source/eligibility investigation or a business-appropriate membership review.
   Do not automatically combine unrelated lists or extend retention to inflate size.
   Check permission and campaign intent before any activation/exclusion proposal.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Active hard-targeting list ineligible; delivery dependence not established | Warning |
| Comparable weekly size decline >20% beyond measurement uncertainty | Warning |
| Confirmed required targeting dependency causes material delivery failure | Critical |
| Ineligible unused/optional observation/signal list without delivery impact | Info |
| History absent, status unknown, size suppressed or minimum source unavailable | Info |

The 20% trend screen is a triage heuristic, not a platform minimum or causal diagnosis.
Current eligibility and dated rule sources outrank remembered blanket list-size thresholds.
Business performance comparisons use [PARAMETERS](../_resources/PARAMETERS.md) maturity/sample gates.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Include list/channel/use keys, eligible status/reason/source date, dependency evidence,
size precision, two snapshot timestamps, denominator, actual interval and owner proposal.
