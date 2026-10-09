---
name: skill-090-pmax-audience-signal-configuration
description: "Review optional PMax audience signals with complete definitions, eligibility and permitted-use evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-061-customer-match-list-health, skill-089-pmax-asset-group-structure, skill-105-ga4-advanced-audiences, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 090: Performance Max Audience Signal Configuration

## Purpose

Inventory optional audience signals and evaluate their business relevance and usability. Signals guide discovery; they are not hard targeting restrictions, and no signals does not mean PMax has no other guidance.

## Data Requirements

**Applicability:** PMax asset groups; first-party signal recommendations require current permitted-use and platform eligibility evidence.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/audiences` (including supplied match rates); client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/custom/pmax_groups.csv`: complete Ads asset-group UI inventory at snapshot_at; one row per account_id, campaign_id, asset_group_id, including empty and paused groups and campaigns with zero groups via the campaign inventory. Fields: name, status, primary_status, platform_diagnostic, ad_strength, final_urls, final_mobile_urls and declared theme/objective.
- `export/custom/pmax_signals.csv`: complete Ads signal snapshot, one row per account_id, campaign_id, asset_group_id and signal_id; signal_type, audience_resource_id or search_theme_text, status and snapshot_at. Keep groups with zero signals via pmax_groups.csv; distinguish search themes from audience signals.
- `export/custom/pmax_audience_components.csv`: current Ads audience-definition export, one row per audience_resource_id, component_id and component_type; user_list_id, custom_segment_id, interest/demographic criterion, inclusion/exclusion, combination_operator, definition_text and snapshot_at. Preserve nested composition; a signal audience reference is not itself a user list.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/external/pmax_signal_intent.csv`: current approved row per asset_group_id and intended signal role; business_segment, desired customer characteristics, permitted source_ids, source-to-offer fit, refresh_SLA_days and owner.

**Missing inputs:** Without complete groups/signals do not identify empty groups; without audience components do not claim first-party or GA4 coverage. Missing permission blocks activation proposals, not the read-only inventory. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Left-join complete groups to signals, then audience resources to all components and list definitions. Count signal audiences separately from constituent lists; flag unresolved references as evidence gaps rather than absent lists.

2. Classify signal content using actual source provenance and definitions, not audience/list names. Preserve composite inclusion/exclusion logic, distinguish optional first-party/custom/interest components and assess relevance to the declared group offer.

3. Before proposing additions, uploads, refreshes or reuse of first-party data, require permission_status, consent coverage, permitted destination/use, retention, restricted-data review and current policy eligibility. Unknown/denied evidence means blocked proposal and referral to the authorized owner, never an upload suggestion.

4. For eligible sources inspect actual network eligibility/linkage, latest successful refresh and declared refresh SLA. Match rates already may be in base audiences; do not confuse uploaded counts, matched population and network-eligible size or impose a universal list-size gate.

5. Separate absent optional signals from broken intended signals. No GA4 list, fewer than three signal types or no Customer Match is not a defect; do not demand full-funnel representation, infer targeting restrictions, or diagnose reliance on auto-targeting.

6. Propose a narrowly justified signal experiment only when authorized and useful to the stated offer. Delegate list-health diagnosis to 061, GA4 definitions to 105 and permission/activation readiness to 156; avoid duplicate recommendations.

## Thresholds

| Condition | Severity |
|---|---|
| Direct evidence of active materially unsafe first-party use contrary to approved permitted scope | Critical |
| An intended signal has confirmed broken linkage, ineligibility or stale source violating its approved refresh SLA | Warning |
| Optional signals absent, plausible permitted signal experiment or low match rate without diagnosed cause | Info |
| Unresolved components, permission unknown, missing refresh evidence or unverified eligibility | Info |

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

- Show every campaign/group, zero-signal groups, signal IDs, audience IDs and resolved component/list IDs.
- For first-party candidates show authorized/blocked readiness and exact evidence references; do not expose identifiers.
- Report list health via 061 and permission readiness via 156, with signal-role proposals only after their gates pass.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
