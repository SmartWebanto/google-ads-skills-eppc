---
name: skill-106-ga4-google-ads-integration
description: "Assess actual GA4 linkage, required data flows, and conversion-goal overlap without mandating a single source."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-071-conversion-tracking-accuracy, skill-076-conversion-action-configuration, skill-105-ga4-advanced-audiences]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 106: GA4 and Ads Integration Evidence

## Purpose

Assess actual GA4 linkage, required data flows, and conversion-goal overlap without mandating a single source.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Accounts with intended GA4/Ads integration; native Ads-only measurement is a legitimate alternative.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `audiences`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/ga4_ads_links.csv`: property_id/account_id/link_id/snapshot grain, from GA4 product links and Ads Data Manager/settings.
  Columns: link_status, effective_from, ads_personalization_setting, data_sharing_settings, auto_tagging_status, intended_flow, expected_latency_hours, permissions_verified_by_owner, source_reference, owner.
- `export/external/ga4_ads_event_mapping.csv`: property_id/event_name/account_id/action_id/campaign_id grain, from key-event/action and goal configuration.
  Columns: business_event_id, source_type, imported_status, primary_for_goal, include_in_conversions, custom_goal_membership, intended_bidding_role, counting, attribution_model, lookback_days, date_basis, timezone, currency, value_basis.
- `export/external/ga4_ads_flow_checks.csv`: link_id/flow_type/entity_id/check_id grain, from sanitized integration diagnostics and synthetic URL/tag QA.
  Columns: tested_at, observation_window_start/end, expected_behavior, observed_behavior, event_or_audience_last_seen, parameter_preservation_check, destination_property_check, processing_mature, diagnostic_code, source_reference.
- Audience-specific provenance/definition checks use skill 105's `ga4_audience_definitions.csv` and `ga4_audience_sync.csv`; imported action source alone cannot verify a live link.
- Actual business-event duplication and count/value differences use skill 071's reconciliation schemas, not raw totals from two platforms.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Establish intended flows separately: Ads traffic reporting, selected conversion imports, audience activation. Do not require vague bidirectional sharing for every account.
2. Verify exact property/account/link identities and settings from configuration evidence. Native conversion origin cannot prove linkage, sharing, or sync.
3. Check auto-tagging and sanitized parameter-preservation traces against the intended flow. Unknown is not disabled; disabled alone is not Critical without relevant requirements and observed failure.
4. Review only required key-event imports. A native Ads primary conversion plus GA4 secondary diagnostic measurement may be intentional and useful.
5. Map shared business events and effective campaign goals, including custom goals. Flag overlapping bidding signals only with actual simultaneous goal inclusion and business-event semantics; two measurement sources alone do not prove duplicates.
6. Preserve independent analytics measurement; do not recommend GA4 as a universal sole conversion source or delete native tracking indiscriminately.
7. Assess audience and event synchronization after the source's expected latency, separating new links, policy restrictions, absent events, and actual flow errors.
8. Reconcile discrepancies through 071 after aligning attribution model, date basis, scope, timezones, and values; different platform totals alone do not mean integration failure.
9. Propose a scoped owner-reviewed flow/goal correction with monitoring criteria; no permission grants, linking, imports, or configuration changes.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Direct evidence confirms material failure of an explicitly required measurement/activation flow | Critical |
| Required link/flow setting or effective bidding-goal selection conflicts with declared design | Warning |
| Optional integration/import or source consolidation warrants business review | Info |
| Native primary plus GA4 secondary, no intended GA4 use, or unknown link state | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Report property/account/link IDs and each intended flow's configured, observed, pending, or unknown state.
- Show event-to-action effective goal mapping and preserve justified primary/secondary parallel measurement.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
