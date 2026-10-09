---
name: skill-101-dynamic-remarketing-setup
description: "Verify intended dynamic remarketing through active feed linkage, settings and tag-to-item diagnostics."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-083-product-feed-attribute-completeness, skill-098-audience-segmentation-funnel-stage, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 101: Dynamic Remarketing Setup Review

## Purpose

Review actual dynamic remarketing configuration and product/event joins. A Merchant Center ID or audience list is only an inventory clue, not proof that a campaign is dynamic, linked or correctly matching viewed items.

## Data Requirements

**Applicability:** Campaigns explicitly intended/configured for a currently supported dynamic remarketing implementation; generic Display, Shopping and PMax are not automatically dynamic remarketing.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/audiences`, `export/assets`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/dynamic_configuration.csv`: current client/Ads configuration review, one row per account_id and campaign_id; business_vertical, intended_dynamic_use, campaign_subtype, dynamic_status (enabled/disabled/unknown), feed_type, feed_id/merchant_id, actual linked_account_id, link_status, destination, eligibility/diagnostics, applicable_parameter_specification_url, approved_use and observed_at/source_reference. Include intended static alternatives.
- `export/external/dynamic_feed_items.csv`: complete current Merchant Center processed feed for retail or approved business-data feed for other supported verticals; one row per feed_id and full item key (retail merchant_id, channel, language, feed_label, offer_id, country/destination); item_id, item_group_id, product_url, availability, required vertical attributes, eligibility_status, issue_codes and snapshot_at. Include zero-delivery and disapproved items plus feed diagnostic completeness.
- `export/external/dynamic_tag_diagnostics.csv`: client-supplied sanitized Tag Assistant/event diagnostics, one row per test_id, tested_at, page_reference, event_name and item_index; campaign/feed_scope, tag_destination_id, actual_item_id, business_vertical, expected_item_id, value/currency where relevant, consent_state, parameter_names, observed_payload_status, issue and source_reference. Cover representative product, cart, purchase, variant and unavailable-item cases; no customer identifiers.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.

**Missing inputs:** Without active linkage/settings do not certify setup; without tag payloads and complete feed keys skip matching verification. Consent/permission unknown blocks activation or tag-deployment proposals. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Start from the declared dynamic objective, not campaign type alone. Confirm supported vertical, subtype and feed mechanism from the supplied current specification; preserve intentionally static Display and nonretail business-feed setups.

2. Verify actual Ads/feed-account linkage and dynamic enablement independently. A merchant_id value, open audience or feed existence cannot establish active linkage, destination eligibility or dynamic ads configured.

3. Check complete processed-feed status and current diagnostics, including unavailable items and missing required vertical fields. Delegate detailed retail attribute corrections to 083; do not require Merchant Center for every supported nonretail feed implementation.

4. Match actual event item IDs to full feed keys and expected variants using documented namespace/case rules. Keep parent/item-group IDs separate from offer IDs; trace unmapped or wrong-variant events to the feed/tag source without inventing transformations or parameters.

5. Evaluate representative event cases, timestamps and consent states; distinguish a single test failure from production-wide rates. For any production mismatch rate require an explicit sampled-event denominator and selection window, not campaign spend as a proxy.

6. Before proposing linking, tag deployment, list creation or activation, require authorized permitted-use and applicable consent evidence. Refer activation readiness to 156 and audience journey gaps to 098. Propose correction of a confirmed path only; no generic dynamic-ad mandate or claimed 2–3x uplift.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed broken intended dynamic path blocks material delivery, or directly evidenced active unsafe data use | Critical |
| Verified linkage/feed/tag item mismatch in the evidenced scope | Warning |
| Intentional static/no-feed campaign or a permitted business-led dynamic opportunity | Info |
| Missing configuration, representative diagnostics, product join keys or permissions | Info |

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

- Report campaign/feed IDs, intended versus actual dynamic status and independently verified link state.
- List sanitized event test IDs, full expected/actual product keys, diagnostic evidence and tested coverage; do not certify untested production behavior.
- Provide feed/tag/Ads owner correction proposals and 083/098/156 references, never an automatic enablement instruction.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
