---
name: skill-156-first-party-data-collection-activation-strategy
description: "Assess first-party collection and activation only after permitted-use, consent and policy evidence passes."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: platform
  kind: analyst
  data_source: external
  related: [skill-061-customer-match-list-health, skill-072-enhanced-conversions-web, skill-073-enhanced-conversions-leads, skill-080-offline-conversion-import, skill-090-pmax-audience-signal-configuration, skill-105-ga4-advanced-audiences]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 156: First-Party Data Collection and Activation Readiness

## Purpose

Inventory first-party data readiness and determine whether specific collection or activation uses are permitted, technically eligible and useful. Ownership of CRM data is not permission for advertising; this audit does not certify legal compliance or upload records.

## Data Requirements

**Applicability:** Businesses considering or using first-party advertising/measurement data in any market; apply market-specific requirements rather than assuming EEA-only relevance.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/audiences` (including supplied match rates), `export/conversion_actions`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/external/first_party_sources.csv`: current privacy-safe inventory, one row per source_id and business_segment; source_system, data_categories, collection_purpose, notice_version, aggregate_record_count, eligible_record_count with definition, identifier_format_quality_counts, deduplication_method, earliest/latest_collection_at, retention/deletion_status, source_owner and evidence_reference. Never supply raw emails, phone numbers, hashes or customer-level rows.
- `export/external/first_party_capture.csv`: aggregate analytics/CRM intake at source_id, collection_point_id, market and complete date/window for a mature 30-day baseline; eligible_unique_visitors_or_opportunities, denominator_definition, offered_form_count, submitted_count, valid_unique_records, permitted_use_opt_in_count, consent_choice_counts, deduplication_rule and source_reference. Distinguish technical capture from permission for a specific use.
- `export/external/first_party_activation.csv`: current Ads/Data Manager/CRM integration evidence, one row per source_id, destination_account_id, intended_use and pipeline/list/action_id; connection_status, eligibility, last_attempt_at, last_successful_refresh_at, source_updated_at, accepted/rejected_counts, error_codes, permission_filter_status, withdrawal/deletion_sync_status, approved_refresh_SLA and source_reference. Include unsuccessful attempts during the same 30-day window and current last-success evidence.
- `export/external/first_party_use_plan.csv`: current authorized business review, one row per source_id and intended_use; purpose, campaign/measurement objective, permitted_destination, necessary_data_categories, expected_decision_use, current_alternative, retention_requirements, review_owner, approved_at and evidence_reference. Optional economics must declare model/assumptions; no default uplift.

**Missing inputs:** Missing or ambiguous permitted-use, applicable consent, retention or eligibility evidence blocks all dependent collection/activation proposals. Continue read-only inventory and identify the exact evidence owner; do not merely append an Info consent caveat to an upload recommendation. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Inventory sources and present counts as aggregate, deduplicated populations with explicit definitions. Base audiences already may contain match rates, sizes and linkage; use those fields when supplied rather than claiming the base export lacks them.

2. Perform the permission gate before evaluating activation opportunities: match source, market, intended purpose and destination to current permission evidence, applicable consent coverage, restrictions, retention, withdrawal/deletion handling and platform eligibility. Reject assumed permission from data ownership, hashed status, an email signup or a generic CRM consent flag.

3. Assign each source/use readiness as permitted, blocked or unknown, separately from finding severity. Unknown/denied means no upload, audience creation, refresh, tag enablement, data expansion or new capture proposal for that use. Request authorized-owner evidence review only; confirmed active use contrary to restrictions warrants escalation, not legal certification.

4. For uses that pass the gate, assess identifier format, duplicates, last successful refresh and eligibility. An attempted upload is not a refresh; a stale list depends on source change rate and approved SLA, not a universal 30-day cutoff. Match-rate denominators and network-eligible sizes are distinct; defer list-specific diagnosis to 061.

5. Compute capture = valid_unique_records / eligible opportunities only when units/populations align and denominator is nonzero. Compute permission rate separately with its declared population; do not interpret low consent as a defect to bypass. Compare like collection points with min_clicks or a declared appropriate sample rationale, never a universal 3% signup threshold.

6. For permitted, useful uses only, produce a bounded proposal with exact source/destination/purpose, minimum data, readiness prerequisites, accountable owner and measurement method. Enhanced Conversions, offline imports, GA4 lists and PMax signals are optional alternatives: delegate implementation-specific analysis to 072/073/080/105/090. No +5–10% capture promise or instruction to upload every CRM source.

## Thresholds

| Condition | Severity |
|---|---|
| Direct evidence of materially unsafe active data use contrary to approved restrictions or withdrawal/retention requirements | Critical |
| Confirmed eligible active pipeline failure, incorrect filtering or missed approved freshness SLA | Warning |
| Permission/consent/eligibility unknown or denied for a proposed use: activation blocked pending owner review | Info |
| Optional integration absent, low capture/match rate without diagnosed cause or an authorized opportunity | Info |

Use [PARAMETERS.md](../_resources/PARAMETERS.md) and resolved client overrides.
CTR comparisons require {{min_impressions}}, conversion-rate comparisons {{min_clicks}},
and CPA/ROAS comparisons {{min_conversions}} on **both** comparable sides.
Use mature, equal-length windows with matched goals, currency and attribution basis;
exclude incomplete days and conversion lag, and never divide by zero.
Numerical screens without a cited platform requirement are triage heuristics, not proof of harm.
Critical requires directly evidenced material delivery, measurement or safety failure.
Missing evidence and optional-feature absence are Info, not a failed or passed check.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), not a separate competing template.
Report stable entity IDs, condition key, observed evidence/window, sample denominators,
resolved thresholds, recommendation, uncertainty and the owning skill.

- Give a source_id/intended_use/market/destination readiness matrix with permitted/blocked/unknown, exact missing evidence and authorized owner.
- Show capture and permission denominators separately, successful refresh evidence, aggregate quality and eligibility; do not include customer identifiers.
- Only gate-passing rows may contain activation/collection proposals; blocked rows contain evidence-review requests and no operational upload/tag/list recommendation.
- Delegate technical findings to 061/072/073/080/090/105 with stable IDs rather than duplicate contradictory adoption requirements.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
