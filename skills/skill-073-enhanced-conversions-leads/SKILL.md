---
name: skill-073-enhanced-conversions-leads
description: "Assess lead enhancement and CRM matching with sanitized capture and upload evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-070-conversion-tracking-completeness, skill-071-conversion-tracking-accuracy, skill-072-enhanced-conversions-web, skill-075-consent-mode-v2, skill-080-offline-conversion-import, skill-107-conversion-value-accuracy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 073: Enhanced Conversions for Leads

## Purpose

Assess lead enhancement and CRM matching with sanitized capture and upload evidence.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Chosen or proposed Enhanced Conversions for Leads; not universally mandatory for B2B accounts.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/enhanced_leads_config.csv`: account_id/conversion_customer_id/action_id/snapshot grain, from Ads Leads settings and CRM owner.
  Columns: leads_enabled, action_status, lead_stage, expected_stage, matching_method, supported_identifier_types, click_identifier_supported, capture_method, consent_policy_reference, integration_id, owner.
- `export/external/enhanced_leads_qa.csv`: synthetic test_id/action_id/stage/step grain, from current site/CRM deployment QA.
  Columns: tested_at, consent_state, identifier_type_presence, normalization_check, hashing_check, identifier_persistence_check, stage_mapping_check, destination_check, expected_behavior, observed_behavior, trace_reference.
- Pipeline checks require `export/external/offline_outcomes.csv`, `offline_upload_attempts.csv`, and `offline_pipeline_config.csv` under skill 080's exact schemas.
  These supply event/action keys, event-ready/submission/processing timestamps, matching method, outcomes, and intended cadence; settings cannot substitute.
- Optional `export/external/enhanced_leads_diagnostics.csv`: account_id/action_id/window_start/window_end grain, from Ads diagnostics.
  Columns: eligible_records, accepted_records, matched_records_if_reported, match_denominator_if_reported, metric_definition, diagnostic_status, processing_mature, source_reference; unavailable matching remains null.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Verify conversion ownership and Leads settings separately from Web enhancement.
2. Map business stages to actions and intended bidding goals. Form-only tracking may be legitimate; require a business reason before proposing downstream stages.
3. Inspect synthetic capture, persistence, normalization, hashing, destination, and consent evidence. Required field combinations depend on the selected supported method.
4. Missing GCLID is not a universal defect if a supported alternative works; never request real click IDs for this audit.
5. Compare eligible outcomes to accepted/rejected attempts in 080. Distinguish no outcomes, no eligible matching data, failed submission, and pending processing.
6. Separate uploaded, accepted, matched, and attributed counts. Match rates require actual source numerators and denominators, not guessed acceptance ratios.
7. Use event-to-ready, ready-to-submit, and submit-to-process delay in 080; long click-to-sale cycles are not pipeline staleness.
8. Assign capture errors to implementation owner and business-stage/value reconciliation to 071/107. Adoption and new stages remain optional proposals.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Confirmed chosen pipeline failure materially omits required eligible outcomes | Critical |
| Reproducible identifier/stage/routing errors or documented cadence breach | Warning |
| Mature direct diagnostics deteriorate against comparable baseline | Warning |
| Enhancement/stages not chosen, supported alternative matching, or unknown diagnostics | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include stage/action/matching-method inventory and evidence state without identifiers.
- Reference 080 pipeline findings instead of duplicating them; clearly distinguish accepted, matched, and attributed counts.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
