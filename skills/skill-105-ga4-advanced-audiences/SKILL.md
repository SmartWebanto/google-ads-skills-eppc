---
name: skill-105-ga4-advanced-audiences
description: "Assess GA4 audience definitions and observed Ads availability against explicit activation goals."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-106-ga4-google-ads-integration]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 105: GA4 Audience Definition and Use

## Purpose

Assess GA4 audience definitions and observed Ads availability against explicit activation goals.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Accounts choosing GA4 audience activation; optional behavioral/predictive audiences are not universally required.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `audiences`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/ga4_audience_definitions.csv`: property_id/ga4_audience_id/snapshot grain, from GA4 audience configuration.
  Columns: definition_expression, inclusion_conditions, exclusion_conditions, sequence_scope, membership_days, created_at, predictive_eligibility_status, expected_event_names, intended_use, campaign_objective, privacy_restriction, owner.
- `export/external/ga4_audience_sync.csv`: property_id/ga4_audience_id/account_id/user_list_id/snapshot grain, from GA4/Ads linked-product and Audience Manager evidence.
  Columns: link_id, source_property_verified, destination_account_verified, ads_personalization_setting, sync_status, last_observed_sync, search_size, display_size, eligibility_by_network, suppression_status, source_reference.
- `export/external/ga4_event_availability.csv`: property_id/event_name/window_start/window_end grain, from aggregate GA4 event diagnostics over the definition's relevant window.
  Columns: event_count, required_parameter_presence_rate, consent_scope, processing_mature, source_reference; no user/event payloads.
- Performance comparisons, if requested, require `export/custom/ga4_audience_performance.csv` at account_id/campaign_id/ad_group_id/user_list_id/date/mode/network grain.
  Columns: impressions, clicks, cost, conversions, conversion_value, objective, currency, overlap_known, date_basis, reporting_mature; source Ads reports. No nonoverlap or causal lift assumed.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Identify GA4 origin through property/audience/list mappings; list names and RULE_BASED/LOGICAL types do not establish provenance.
2. Check desired activation and link status through 106. No GA4 linkage is not a defect when GA4 audiences are not part of the intended design.
3. Inspect actual behavioral/sequence rules, membership duration, exclusions, event availability, and declared privacy restrictions; do not infer intent from audience names.
4. Compare required definitions with supplied objectives. Pricing visits or engagement depth can be useful hypotheses, not universal missing-audience warnings.
5. Review sync and network eligibility using direct diagnostics and processing window. Newly created or privacy-suppressed lists may not be immediately available; zero reported size alone does not prove failure.
6. Inspect campaign use and targeting/observation/exclusion mode, not just list existence. Do not presume an audience signal is a hard targeting restriction.
7. Assess predictive options only with actual property eligibility status and business suitability; do not require arbitrary session counts or membership windows.
8. If performance data exists, apply mature comparable samples, mode/channel scope, overlap caveats, and source attribution. No universal 50–100% conversion uplift or causal comparison from overlapping lists.
9. Propose definition or sync-owner review with an explicit decision use; no creation, linking, permissions, or publishing.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Confirmed required audience activation failure causes material delivery/objective failure | Critical |
| Intended audience has reproducible definition/event/sync mismatch after normal processing | Warning |
| Business-backed optional behavioral or predictive audience hypothesis | Info |
| Missing optional audience, unknown origin, or suppressed/ineligible/new list | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include property/audience/list/campaign IDs, actual definitions, intended use, sync/eligibility evidence, and unassessed conditions.
- Any performance appendix is descriptive unless a valid controlled comparison is supplied.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
