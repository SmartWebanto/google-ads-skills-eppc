---
name: skill-098-audience-segmentation-funnel-stage
description: "Map audience definitions to business journeys while preserving permitted repeat-purchase and intentional targeting setups."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-099-membership-duration-optimization, skill-103-recent-converter-exclusion, skill-105-ga4-advanced-audiences, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 098: Audience Segmentation by Funnel Stage

## Purpose

Assess whether audience definitions express the business journey and intended messaging. Generic lists, overlapping stages and missing cart-abandoner audiences are not inherently defects; no conversion uplift is assumed.

## Data Requirements

**Applicability:** Campaigns with an approved audience-led journey or existing audiences, for commerce or lead generation as appropriate.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/ad_groups`, `export/audiences`; profile business_type and campaign_objectives; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/customer_lifecycle.csv`: client CRM/order cohort summary, one row per business_segment, product_category, cohort_start and cohort_end; new/returning definition, acquisition/retention objective, buying_cycle and repurchase_interval distributions with units, cohort_count, observation_horizon_days, maturity, suppression_policy and rationale, updated_at. Include only aggregate data spanning the relevant sales and repurchase cycles.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/external/funnel_plan.csv`: current client plan, one row per business_segment, funnel_stage and campaign/group scope; stage_definition, qualifying_events, desired_message, conversion/retention_objective, deliberate_overlap, available_event_source, permitted_activation_use, business_priority and owner. Include product/offer context and actual lead stages, not a required ecommerce template.
- `export/custom/audience_associations.csv`: complete current Ads linkage inventory at account_id, campaign_id, ad_group_id (nullable), criterion_id and list_id; level, association_status, targeting/observation/exclusion mode, logical_combination, expansion/optimization settings as observed, snapshot_at and inventory_complete. Parent tables retain campaigns/groups with no associations.

**Missing inputs:** Without definitions do not classify from names; without buying-cycle or funnel intent do not prescribe segments. Permission gaps block creation/activation proposals. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Start with complete campaign/group scope and join all audience associations and definitions. Distinguish available lists from linked lists; retain unused lists and empty parent scopes without treating absence as a defect.

2. Map actual entry rules and exclusions to the supplied journey: awareness, consideration, intent, purchaser/customer or client-specific lead stages. Record ambiguous definitions and multi-stage membership rather than force each list into one exclusive bucket.

3. Compare observed targeting/observation/exclusion roles with approved intent. Preserve dedicated returning-user targeting, pooled all-visitor learning, cross-sell, renewal, repeat purchase and deliberately overlapping stages.

4. Identify genuine definition contradictions, unavailable source events or message-stage mismatches from supplied facts. A missing optional segment is an Info opportunity only when a useful business action and available permitted signal exist.

5. Require current permitted use and applicable consent evidence before proposing audience collection, creation, upload, expansion or activation. Do not assume owning CRM records grants advertising rights; delegate readiness to 156 and GA4 provenance to 105.

6. Delegate all membership-window recommendations to 099 and purchaser-exclusion policy to 103. This skill owns stage/definition/message mapping, not duplicate duration, exclusion or arbitrary bid-modifier outputs.

## Thresholds

| Condition | Severity |
|---|---|
| A verified definition/association error materially blocks the approved intended audience delivery | Critical |
| Confirmed stage-definition or message/targeting contradiction to the approved journey | Warning |
| Missing optional funnel segment, deliberate overlap or generic-list setup without evidenced harm | Info |
| Unclear audience rules, unavailable events, lifecycle context or permission evidence | Info |

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

- Give scope and list IDs, actual rule summary, stage assignment with confidence, linked mode and intentional exceptions.
- Show observed-versus-approved journey gaps with evidence and owner, not a universal full-funnel checklist.
- Reference 099/103/105/156 for dependent findings; no default purchaser exclusion or promised segmentation uplift.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
