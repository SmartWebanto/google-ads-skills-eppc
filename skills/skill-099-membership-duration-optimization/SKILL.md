---
name: skill-099-membership-duration-optimization
description: "Review membership durations using actual list entry/refresh semantics and observed buying or repurchase cycles."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-098-audience-segmentation-funnel-stage, skill-103-recent-converter-exclusion, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 099: Audience Membership Duration Review

## Purpose

Evaluate audience membership windows against their intended role and mature lifecycle evidence. Click-to-conversion lag is not time since audience entry, and a shared duration can be intentional.

## Data Requirements

**Applicability:** Audience types with a supported membership-duration control; distinguish rule-based entry/reset behavior from Customer Match refresh/retention semantics.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/audiences`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/audience_definitions.csv`: current audience-manager/GA4/CRM definition snapshot, one row per account_id and list_id; source_id, source_platform, definition_expression, entry_event, inclusions, exclusions, sequence/time conditions, membership_duration_days, refresh_behavior, created_at, last_successful_refresh_at, eligibility_by_network, linkage_status, owner and evidence_reference. Names are not definitions.
- `export/external/customer_lifecycle.csv`: client CRM/order cohort summary, one row per business_segment, product_category, cohort_start and cohort_end; new/returning definition, acquisition/retention objective, buying_cycle and repurchase_interval distributions with units, cohort_count, observation_horizon_days, maturity, suppression_policy and rationale, updated_at. Include only aggregate data spanning the relevant sales and repurchase cycles.
- `export/external/activation_permissions.csv`: current authorized-owner evidence, one row per source_id, list_id (nullable), market and intended_use; permission_status, applicable_consent_requirements, consent_coverage_status, collection_notice_version, permitted_destinations, retention_limit_days, withdrawal/deletion_process_status, restricted_data_review, policy_eligibility, reviewed_at, reviewer_role and evidence_reference. Use aggregate/redacted records, never customer identifiers; missing or ambiguous permission blocks the dependent activation proposal.
- `export/external/audience_age_cohorts.csv`: privacy-safe first-party cohort evidence, one row per list_id, entry_cohort_start/end, age_since_entry_bucket and business_segment; qualifying_entry/reset_event definition, eligible_people, exposed_people when measured, purchases/qualified_outcomes, net_value, observation_end, maturity, source_reference and attribution_definition. Horizon must span proposed membership windows; do not substitute Ads conversion-lag buckets.
- `export/external/membership_controls.csv`: current Ads/GA4/source setting review, one row per list_id and source_platform; observed_duration, units, allowed_min/max, nonexpiring_special_value if supported, refresh/reset_behavior, retention_constraint, intended_role, approved_duration/rationale, source_url/reference and checked_at.

**Missing inputs:** Without audience-entry cohorts provide configuration/intent review only; without current control/permission evidence do not propose duration extension or retention changes. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Inventory lists and linked uses, preserving exact observed duration, units, special nonexpiring values and source type. A list used for both acquisition suppression and retention targeting needs role-specific review, not one universal window.

2. Read inclusion, re-entry and reset semantics. Distinguish time from qualifying audience event, time from first purchase, repurchase interval and click-to-conversion lag; only aligned clocks support a proposed duration.

3. Compare mature outcome distributions at audience ages with business buying/repurchase cycles and observation horizon. Handle right-censored cohorts and repeated entries; no observed long-age conversion in an immature cohort does not prove that age worthless.

4. Check whether the current window contradicts an approved role, privacy retention bound or supported platform limit. Identical durations, a cart list over 30 days or a B2B list under 60 days are not automatic warnings.

5. Before any extension, membership-rule change or refresh proposal verify permitted retention/use and applicable consent coverage. Preserve intentional repeated-purchase and high-consideration cases; delegate suppression policy to 103 and source permission readiness to 156.

6. If evidence supports an alternative, propose a small set of supported duration variants, approved outcome, comparable randomized eligibility where feasible, horizon spanning the relevant buying cycle, lag allowance and rollback criteria. Outcomes by age are observational and do not prove the incremental value of longer exposure.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed active membership use materially violates an approved safety/retention restriction | Critical |
| Verified window/control mismatch with approved intended audience use or demonstrated mature lifecycle evidence | Warning |
| Identical durations, unfamiliar industry window or eligible duration-test opportunity without evidenced harm | Info |
| Missing entry-clock data, immature cohorts, unresolved reset semantics or permissions | Info |

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

- List IDs, source/role, current duration and reset semantics, evidence horizon and eligible cohort counts.
- Distinguish buying-cycle, repurchase and audience-age evidence; record unsupported/unknown control states.
- Provide only evidence-supported proposed windows within permitted retention and platform bounds; cross-reference 103 for exclusions.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
