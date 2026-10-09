---
name: skill-070-conversion-tracking-completeness
description: "Assess coverage against explicit business outcomes and optional journey measurement."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-071-conversion-tracking-accuracy, skill-076-conversion-action-configuration, skill-080-offline-conversion-import, skill-107-conversion-value-accuracy, skill-110-conversion-tracking-breakage]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
  merged_from: [skill-081-micro-conversion-tracking]
---
# Skill 070: Business Event and Journey Coverage

## Purpose

Assess coverage against explicit business outcomes and optional journey measurement.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** All campaign types with declared measurement objectives; calls, offline stages, and micro-conversions are not universally required.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/business_event_map.csv`: one row per account_id/campaign_id/business_event_id/action_id mapping, from business owner and CRM/OMS aggregates.
  Columns: event_definition, funnel_stage, required_for_objective, decision_use, expected_source, intended_bidding_role, observed_business_count, count_window_start/end, maturity_days, owner.
  Cover the export window plus maturity tail; null action_id explicitly identifies an unmapped event.
- `export/custom/conversion_action_daily.csv`: account_id/campaign_id/action_id/date/date_basis grain, from an Ads action-segmented report over the mature analysis window.
  Columns: conversions, all_conversions, conversion_value, currency, primary_goal_membership, reporting_mature; settings are not volume evidence.
- Optional `export/external/journey_coverage.csv`: account_id/business_event_id/stage grain, from tracking plan and aggregate analytics report for the same window.
  Columns: diagnostic_question, event_name, event_count, downstream_event_id, decision_owner, consent_scope, intended_bidding_role; no user paths.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Derive expected outcomes from the business map, not business type or action names. Separate required measurement from optional diagnostics.
2. Join actions by stable IDs, retaining inactive, secondary, and explicitly unmapped actions. One well-chosen action may be complete.
3. Join action metrics without multiplying campaign totals. Compare zero Ads volume with actual business outcomes only after aligning scope and maturity.
4. Flag a required gap only with evidence that the intended path is absent or broken; no observed outcomes may legitimately explain silence.
5. Route count/value disagreement to 071, configuration to 076, pipeline evidence to 080, and suspected incidents to 110.
6. For optional micro-events require a diagnostic question and downstream relationship. Missing add-to-cart, form-start, or engagement events is not a defect.
7. Prefer secondary measurement for diagnostics; check campaign custom goals before asserting secondary events cannot affect bidding. Never invent values or automatically promote weak signals.
8. Return coverage and uncertainty by business event; deduplicate required-gap and journey-opportunity findings.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Required material outcomes demonstrably occur but intended measurement is absent or broken | Critical |
| Required coverage has an evidenced partial gap, materiality unconfirmed | Warning |
| Optional journey question supports a justified secondary event | Info |
| Single action, missing optional micros, or unknown expected outcomes | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Report outcome-to-action mapping, required/optional status, intended bidding role, measured volume, business count, and coverage limits.
- Micro-event proposals include decision use and owner, not a compulsory implementation checklist.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
