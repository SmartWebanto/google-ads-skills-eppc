---
name: skill-111-data-exclusion-tracking-incidents
description: "Assess whether a confirmed measurement incident warrants a precisely scoped data-exclusion proposal."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-076-conversion-action-configuration, skill-080-offline-conversion-import, skill-110-conversion-tracking-breakage]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 111: Tracking Incident Data Exclusion Review

## Purpose

Assess whether a confirmed measurement incident warrants a precisely scoped data-exclusion proposal.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Confirmed conversion-data incidents affecting currently supported Smart Bidding campaign types; exclusions are optional controls, not automatic incident treatment.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`, `bidding_strategies`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/tracking_incidents.csv`: use skill 110's exact schema including confirmed status, affected campaign/action/device/channel, fault times, precision, evidence, recovery, backfill, and owner.
- `export/external/data_exclusion_config.csv`: exclusion_id/account_id/campaign_id/device grain, from the actual Ads exclusion settings at current snapshot.
  Columns: scope_type, strategy_id_if_relevant, start_datetime, end_datetime, timezone, status, affected_devices, source_reference, created_at, owner; explicit complete empty export may establish no exclusions.
- `export/external/data_exclusion_eligibility.csv`: account_id/campaign_id/strategy_id/snapshot grain, from current Ads control availability and supported-help reference.
  Columns: channel_type, bidding_strategy_type, control_available, allowed_scope_types, supported_device_scope, allowed_date_window, source_reference, verified_at; unknown support is not eligibility.
- `export/external/incident_click_impact.csv`: incident_id/account_id/campaign_id/action_id/device/interaction_date grain, from incident attribution analysis using mature pre-incident conversion-delay distribution.
  Columns: expected_conversions, observed_conversions, affected_clicks, affected_cost, lag_distribution_reference, estimated_impacted_fraction, estimation_method, lower_bound, upper_bound, reporting_mature, currency.
- `export/external/incident_recovery_review.csv`: incident_id/campaign_id grain, from incident/bidding owner through current snapshot.
  Columns: repair_verified, repair_verified_at, backfill_expected, backfill_complete, residual_bad_data, current_strategy_state, proposed_control_rationale, exclusion_overlap_risk, owner.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Require confirmed measurement-fault evidence before exclusion assessment. Demand changes, seasonality, ordinary conversion lag, or a site outage without tracking corruption are not automatically qualifying incidents.
2. Verify exact campaign and strategy IDs, channel/control eligibility, device scope, and currently supported date restrictions from direct settings and current documentation.
3. Inspect existing exclusions using actual configuration; omitted files or null fields cannot establish that none exist.
4. Translate conversion-event outage times into potentially affected interaction/click dates using pre-incident lag distribution. Do not merely copy outage timestamps or add a universal lookback duration.
5. Keep estimated impact uncertainty and timestamp precision explicit. If a defensible click window cannot be derived, report the prerequisite rather than propose broad exclusion dates.
6. Compare proposed campaign/device/click windows with existing exclusions; identify gaps, duplication, and overbroad scope without assuming strategy-level controls are supported.
7. Assess repair, backfill, elapsed time, current bidding state, materiality, and control restrictions. Not every confirmed incident benefits from exclusion; use a documented no-change alternative.
8. Propose only supported scope and precise timezone-qualified window with start/end semantics confirmed against the UI. Explain which unaffected data would also be excluded.
9. Provide monitoring and rollback/review criteria for the owner; never apply, remove, or widen an exclusion, and do not guarantee a recovery duration.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Direct evidence confirms a material ongoing measurement/control failure | Critical |
| Eligible confirmed incident has residual corrupted data and a defensible exclusion review case | Warning |
| Existing exclusion appears overbroad or mis-scoped relative to documented incident evidence | Warning |
| No exclusion alone, unsupported/unknown eligibility, recovered data, or uncertain click window | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include incident/campaign/strategy IDs, actual exclusion IDs/configuration, supported controls, lag-derived click window, device scope, and overlap analysis.
- Output an owner-review proposal or reasoned no-change decision with uncertainty and recovery state, never an execution instruction.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
