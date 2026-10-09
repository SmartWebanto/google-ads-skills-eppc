---
name: skill-103-recent-converter-exclusion
description: "Review converter suppression only against permitted use and approved acquisition or repeat-purchase objectives."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-095-pmax-new-customer-acquisition, skill-098-audience-segmentation-funnel-stage, skill-099-membership-duration-optimization, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 103: Recent Converter Exclusion Review

## Purpose

Check whether converter exclusions match an approved lifecycle policy. Recent customers can be valuable for repeat purchases, accessories, renewals and upsell; missing purchaser exclusions are not universally wasted spend.

## Data Requirements

**Applicability:** Campaigns with existing converter exclusions or an explicit acquisition/suppression objective; review only audience exclusions supported by the actual campaign subtype.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/ad_groups`, `export/audiences`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/customer_lifecycle.csv`: client CRM/order cohort summary, one row per business_segment, product_category, cohort_start and cohort_end; new/returning definition, acquisition/retention objective, buying_cycle and repurchase_interval distributions with units, cohort_count, observation_horizon_days, maturity, suppression_policy and rationale, updated_at. Include only aggregate data spanning the relevant sales and repurchase cycles.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/custom/converter_exclusions.csv`: complete current Ads audience inclusion/exclusion inventory at account_id, campaign_id, ad_group_id (nullable), criterion_id and list_id; level, positive/negative flag, association_status, mode, inherited_scope, supported_exclusion_control, source_reference and snapshot_at. Include all relevant levels and explicit inventory completeness; separate PMax lifecycle recognition settings from literal audience exclusions.
- `export/external/converter_suppression_plan.csv`: approved current policy, one row per business_segment, campaign/group scope and qualifying_conversion_action_id; acquisition/retention objective, actual buyer/lead-stage definition, qualifying_event, suppression_start/reset_rule, intended_duration, repurchase/cross-sell exceptions, allowed_reach, owner and approved_at.
- Optional outcome context: `export/external/returning_customer_outcomes.csv`, aggregate CRM/Ads cohort evidence at campaign_id when attributable, product_category, new/returning class and cohort/window; customer_count, purchases/qualified_outcomes, net_value, maturity, attributable_cost when genuinely measured, source and allocation_method. Do not fabricate customer-class CPA from campaign spend.

**Missing inputs:** Without complete association levels do not claim no effective exclusion; without a policy and lifecycle evidence do not prescribe one. Permission gaps block any new list/use proposal. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Inventory converter audiences from actual event/CRM definitions, not purchaser-like names. Distinguish purchase, lead submission, qualified sale, repeat purchase and renewal; a micro-conversion does not establish an existing customer.

2. Resolve effective association scope across account-supported, campaign and ad-group levels using actual inheritance. Keep inclusion/targeting versus exclusion distinct, and do not mistake a PMax signal or new-customer recognition list for a hard audience exclusion.

3. Compare observed exclusions to approved suppression policy and campaign intent. Preserve recent-buyer cross-sell, consumables, subscription renewal, loyalty and returning-audience campaigns; asymmetry between campaigns can be correct.

4. Assess qualifying event, duration and reset behavior using mature repurchase distributions and valid control limits. Buying cycle before first purchase is not automatically a post-purchase suppression duration. Route detailed duration optimization to 099.

5. Before proposing a list, extension, refresh or reuse, verify current advertising permission, applicable consent, retention and platform eligibility. Unknown or denied means blocked activation proposal, even if the use is an exclusion; delegate to 156.

6. Propose only the minimal approved-scope correction for an evidenced mismatch, preserving identified repeat-purchase exceptions. Historical returning-user spend is not waste or guaranteed savings. Delegate acquisition mode decisions to 095 and stage mapping to 098.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed unintended exclusion materially blocks approved retention/other intended delivery, or directly evidenced unsafe use | Critical |
| Verified exclusion or missing required suppression contradicts a current approved business policy | Warning |
| No optional converter exclusions, asymmetric coverage or intentional repeat-purchase targeting | Info |
| Unknown policy, incomplete levels, unresolved lifecycle clock or missing permission evidence | Info |

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

- Show campaign/group/criterion/list IDs, effective exclusion scope, qualifying event and observed window.
- Record the approved policy, repurchase exceptions and evidence for every proposed scope/window correction.
- Keep no-change intentional setups visible, label authorization-blocked proposals, and cross-reference 095/098/099/156.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
