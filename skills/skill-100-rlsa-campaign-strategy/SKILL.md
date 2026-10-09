---
name: skill-100-rlsa-campaign-strategy
description: "Review Search audience intent and actual bid-control applicability without mandatory modifiers or targeting changes."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-048-bid-adjustment-layer-review, skill-061-customer-match-list-health, skill-098-audience-segmentation-funnel-stage, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 100: RLSA Campaign Strategy Review

## Purpose

Review returning-audience use in Search against campaign intent and bidding behavior. Observation does not restrict reach and does not require a bid modifier; dedicated audience targeting can be intentional.

## Data Requirements

**Applicability:** Search campaigns with audience associations or an approved remarketing hypothesis; no account-wide RLSA adoption requirement.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/ad_groups`, `export/audiences`, `export/bid_adjustments`, `export/bidding_strategies`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/custom/rlsa_associations.csv`: complete current Ads audience settings at account_id, campaign_id, ad_group_id (nullable), criterion_id and audience/list_id; scope, association_status, targeting/observation/exclusion mode, combination_logic, modifier, current eligibility, snapshot_at and inventory_complete. Include all campaign and ad-group associations and empty parents through base inventories.
- `export/custom/rlsa_performance.csv`: Ads audience report for the mature 30-day window at account_id, campaign_id, ad_group_id or campaign scope, criterion_id, list_id, date and goal_set_id; impressions, clicks, cost, conversions, conversion_value, mode and segmentation_definition. Optional nonmember/mutually-exclusive comparator rows must identify the actual report source and population.
- `export/external/rlsa_intent_controls.csv`: current approved review at campaign_id/ad_group_id and strategy_id; intended_audience_role, desired_reach, supported_audience_bid_control/effect, control_source_url, checked_at, value/profit objective, target, permitted_test_scope and owner.

**Missing inputs:** Without intended reach do not change Targeting to Observation; without segmented outcomes and supported controls do not size audience bid changes. Permission gaps block audience additions. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Join complete Search parent inventories to campaign/ad-group criteria, checking inheritance and combination semantics. Distinguish list availability, current eligibility, association mode and exclusions; do not infer effective targeting solely from one ad-group view.

2. Compare actual mode to approved reach. Targeting restricts eligible audience reach while Observation does not; preserve dedicated returning-user campaigns and intentional audience-only keyword expansion. Absent audiences or modifiers are not automatically defects.

3. Gate any first-party audience addition, reuse or refresh on current permitted-use/consent evidence and platform eligibility; refer readiness to 156 and list-specific health to 061.

4. Compare outcomes only for mature, goal-comparable populations with both-sided sample gates. Audience rows can overlap and are not additive; account/campaign totals include members and are not a clean nonmember baseline. Do not assume returning visitors convert two to three times better.

5. Check actual strategy/control applicability before proposing modifiers. Do not recommend manual audience CPC adjustments on Smart Bidding merely from audience CPA; do not confuse tCPA device-target behavior with an audience CPC control. Delegate layered modifier mechanics to 048.

6. For a strategy with supported audience controls and credible value evidence, propose a bounded test tied to economic objectives, exact scope and monitoring/rollback criteria. No fixed +20–50% default, broad-keyword mandate or dedicated-RLSA requirement.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed unintended targeting/exclusion error materially blocks approved Search delivery | Critical |
| Verified mode/eligibility mismatch or applicable modifier inconsistent with approved constraints | Warning |
| No RLSA/modifier, deliberate audience-only targeting or permitted audience test opportunity | Info |
| Overlapping/noncomparable metrics, missing control applicability or permission evidence | Info |

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

- Give campaign/ad-group/criterion/list IDs, intended versus observed mode and actual bidding-control effect.
- Include nonadditive-population warnings and matched comparator/goal/sample fields for any efficiency finding.
- Route control, list-health and activation findings to 048/061/156; no blanket Observation conversion or fixed modifiers.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
