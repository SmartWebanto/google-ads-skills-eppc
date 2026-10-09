---
name: skill-095-pmax-new-customer-acquisition
description: "Review acquisition mode, customer identification and monetary value settings against permitted use and LTV evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-061-customer-match-list-health, skill-071-conversion-tracking-accuracy, skill-103-recent-converter-exclusion, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 095: PMax New Customer Acquisition Review

## Purpose

Assess whether acquisition settings match approved customer economics and recognition methods. Existing-customer conversions can be valuable; acquisition mode is optional and must not suppress an intentional retention or repeat-purchase objective.

## Data Requirements

**Applicability:** PMax campaigns with an acquisition objective or active lifecycle settings; confirm current goal/mode/strategy availability per account.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/conversion_actions`, `export/audiences`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/pmax_acquisition_settings.csv`: current Ads lifecycle configuration, one row per account_id, conversion_tracking_owner_id and campaign_id; mode/status, effective setting source, purchase_goal_ids, strategy, raw_value_field_name, raw_value, units/currency, additive_or_total_semantics, high_value_setting and its semantics, recognition_methods, linked_existing/high_value_list_ids, sharing/linkage status, eligibility/diagnostics, observed_at and source_reference.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/external/customer_lifecycle.csv`: client CRM/order cohort summary, one row per business_segment, product_category, cohort_start and cohort_end; new/returning definition, acquisition/retention objective, buying_cycle and repurchase_interval distributions with units, cohort_count, observation_horizon_days, maturity, suppression_policy and rationale, updated_at. Include only aggregate data spanning the relevant sales and repurchase cycles.
- `export/external/customer_ltv.csv`: CRM/finance approved mature cohort table at segment, acquisition_cohort and observation_horizon; customer_count, baseline_purchase_value, expected_future_value, discounted_lifetime_value, margin/revenue basis, returns/tax treatment, uncertainty bounds, discount assumptions, new/existing definition, included_value_components, currency, approval/evidence reference and as_of. All components must use the same monetary basis.
- `export/custom/pmax_customer_type_daily.csv`: available Ads lifecycle report for the mature 30-day window at account_id, campaign_id, date, conversion_action_id and reported_customer_type (new/existing/unknown/high-value as actually exposed); conversions, transaction_value, lifecycle_added_value and total_reported_value separately where available, customer counts and reported cost attribution. State detection method and unknown coverage; do not invent spend allocation by purchaser type.

**Missing inputs:** Without settings semantics or LTV evidence do not size acquisition values. Without permission evidence block customer-list activation/refresh proposals. Missing customer-type cost prevents type-specific CPA/ROAS. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Inventory effective campaign and conversion-owner lifecycle settings; unknown is not disabled. Confirm selected mode supports the actual strategy and goals using current [lifecycle guidance](https://support.google.com/google-ads/answer/12080169?hl=en) plus account evidence; do not mandate adoption based on existing-customer share.

2. Review all recognition methods, actual linked list definitions, successful refreshes, sharing and diagnostics. No uploaded CRM list alone does not prove no customer recognition: supported autodetection/tag/list methods vary by mode. High-value designation must match the business definition.

3. Before any first-party list proposal require permitted use, applicable consent coverage, retention and platform eligibility from activation_permissions. Preserve denied/unknown states as blocked and delegate to 156; route specific list-health defects to 061.

4. Treat lifecycle value fields as monetary values, not generic multipliers. [Configuration guidance](https://support.google.com/google-ads/answer/16090064?hl=en) says the segment value is added to purchase conversion value and included in reported conversion value. Preserve raw units, normalize documented micros only once, and verify high-value semantics independently rather than adding two settings blindly.

5. For an additive proposal let B be the already-recorded purchase value and T the finance-approved total value on the same horizon/basis: additional value A = T - B only when T exceeds B and contains B once. If finance supplies future value excluding B, A is that approved component, not lifetime value plus B again. A/B is only a derived ratio when B > 0; do not use universal 1.3x–3x defaults or infer profit from revenue LTV.

6. Reconcile transaction, added and reported value before comparing business ROAS; augmented platform value is not cash revenue. Keep unknown customer classification and unavailable cost allocation visible. Propose a supported bounded acquisition test only when objectives, permitted recognition and credible economics agree; delegate transaction reconciliation to 071 and exclusions to 103.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed unit/double-counting or unsafe-use error materially corrupts active optimization/measurement | Critical |
| Verified acquisition mode conflicts with approved retention intent, recognition is broken, or monetary settings contradict approved evidence | Warning |
| Optional mode absent, recognized customer mix or an eligible evidence-backed experiment | Info |
| Missing LTV, additive semantics, permissions, recognition or type-specific cost evidence | Info |

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

- Show campaign/tracking-owner IDs, mode, recognition/list linkage and readiness gates.
- Report raw/normalized monetary settings, B/T/A calculation when justified, component overlap checks and uncertainty; no unsupported multiplier recommendation.
- Separate actual revenue from lifecycle-added value, unknown customer share and proposal ownership under 061/071/103/156.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
