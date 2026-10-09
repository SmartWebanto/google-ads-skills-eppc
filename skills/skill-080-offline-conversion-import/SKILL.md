---
name: skill-080-offline-conversion-import
description: "Assess offline coverage, upload outcomes, and pipeline freshness using business-event and processing timestamps."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-070-conversion-tracking-completeness, skill-071-conversion-tracking-accuracy, skill-073-enhanced-conversions-leads, skill-110-conversion-tracking-breakage, skill-112-return-refund-tracking]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx110 | pre-upload payload validation with pseudonymized click references (index #110)"
  merged_from: [skill-109-offline-conversion-freshness]
---
# Skill 080: Offline Conversion Pipeline and Freshness

## Purpose

Assess offline coverage, upload outcomes, and pipeline freshness using business-event and processing timestamps.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Chosen offline measurement pipelines and explicitly required business outcomes; no business-type mandate for imports.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/offline_pipeline_config.csv`: account_id/action_id/integration_id grain, from CRM/integration owner at current snapshot.
  Columns: expected_business_event, matching_method, intended_cadence_hours, ready_to_submit_sla_hours, processing_expectation_hours, supported_upload_window_reference, conversion_window_days, automation_status, timezone, consent_policy_reference, owner.
- `export/external/offline_outcomes.csv`: account_id/action_id/event_token grain, from sanitized CRM/OMS events covering analysis window plus sales-cycle and processing tail.
  Columns: integration_id, business_event_timestamp, ready_for_upload_timestamp, eligible_for_upload, eligibility_reason, matching_method, supported_identifier_present, expected_value, currency, lifecycle_status, source_recorded_timestamp.
- `export/external/offline_upload_attempts.csv`: account_id/action_id/event_token/attempt_id grain, from uploader logs and Ads upload diagnostics for the same cohort through snapshot.
  Columns: integration_id, batch_id, submitted_timestamp, processed_timestamp, status, rejection_code, retry_of_attempt_id, duplicate_status, accepted_value, currency, attributed_status_if_reported, diagnostic_source, source_reference.
  Include rejected and pending attempts; accepted, matched, and attributed are distinct. Timestamp precision and timezone must be explicit.
- `export/custom/offline_action_daily.csv`: account_id/campaign_id/action_id/date/date_basis grain, from Ads action reporting for the same mature window.
  Columns: conversions, all_conversions, conversion_value, currency, reporting_mature; an action-settings query cannot establish pipeline activity.
- Optional `export/external/offline_upload_payload.csv` (pre-upload payload, one row per conversion; opt-in, absent → check skipped): gclid|gbraid|wbraid holding a stable LOCAL PSEUDONYM of the click identifier (exactly one column filled), conversion_name, conversion_time with UTC offset, conversion_value, conversion_currency, order_id optional (pseudonymized if it identifies a customer).
  Optional `export/custom/click_ids.csv` (click_id = the same pseudonym, click_time with offset) enables before-click and `conversion_actions.click_window_days` window rules. Raw click identifiers are never supplied: presence, type, duplicates and click-time joins work on pseudonyms; identifier format and platform matchability are NOT validated. Pseudonyms are never echoed (row numbers only) and nothing is uploaded.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, raw click IDs, credentials, or user-level browsing histories (click references only as local pseudonyms, above).
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Map intended offline outcomes, action ownership/type, integration, and matching method. Store visits or a source name alone do not prove a client upload pipeline.
2. Compare eligible outcomes with distinct accepted events, retaining ineligible, unattempted, rejected, pending, and retried rows separately. Deduplicate successful retries by event/action, not batch count.
3. No outcomes can explain no imports. A failed pipeline requires actual expected eligible events plus missing/failed processing, not a 30-day silence rule.
4. Calculate event-to-ready = ready - business_event; queue delay = submitted - ready; processing delay = processed - submitted; total freshness = processed - business_event. Negative timestamps are data-quality issues.
5. For unsubmitted/pending events report censored age to snapshot; do not drop them from freshness reporting. Report median/tail delay only for defined completed cohorts alongside outstanding age/count.
6. Compare queue/processing delay with agreed cadence/SLA and current method upload limits. Click-to-conversion lag and conversion_lag_bucket measure attribution delay, not upload-processing freshness.
7. Detect batch timing from actual submitted timestamps. Manual or weekly uploads are not defects unless they violate required cadence/eligibility or cause evidenced harm; long sales cycles are legitimate.
8. Compute acceptance = distinct accepted eligible events / attempted eligible events where denominator is nonzero. Calculate matching only from a separate reported matching denominator; accepted uploads need not be attributed.
9. Propose retry/destination/mapping/cadence review with integration owner. Never replay uploads or recommend immediate bulk adjustments; route lead capture to 073 and reconciliation to 071.
10. If a pre-upload payload is supplied, validate each row against Google's import template rules (click ID count, exact enabled Import-from-clicks action, offset time not after snapshot or before click, click window, value, ISO 4217 currency, duplicate order/click rows); group failures per error type with row numbers. Never upload.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Confirmed pipeline failure materially loses required eligible business outcomes | Critical |
| Rejections, missing attempts, or pending ages breach documented method/SLA requirements | Warning |
| Supplied pre-upload payload rows violate documented import format, action, or time-window rules | Warning |
| Observed batch behavior warrants a contextual cadence review | Info |
| No business outcomes, valid long sales cycle, manual process alone, or unknown diagnostics | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Report per-action eligible/attempted/accepted/rejected/pending counts, separate matching status, and censored outstanding ages.
- Include event-to-ready, queue, and processing delay distributions, SLA/source limits, and owner; no conversion-lag proxy.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
