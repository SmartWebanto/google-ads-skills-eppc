---
name: skill-072-enhanced-conversions-web
description: "Assess Web enhancement using action-specific settings and sanitized implementation diagnostics."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-071-conversion-tracking-accuracy, skill-073-enhanced-conversions-leads, skill-075-consent-mode-v2, skill-110-conversion-tracking-breakage]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 072: Enhanced Conversions for Web

## Purpose

Assess Web enhancement using action-specific settings and sanitized implementation diagnostics.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Eligible website actions with a chosen or proposed enhancement method; Leads enablement is not Web status.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `conversion_actions`, `campaigns`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/enhanced_web_config.csv`: account_id/conversion_customer_id/action_id/snapshot grain, from Ads Web settings and implementation inventory.
  Columns: web_enabled, action_web_status, implementation_method, tag_destination_id, supported_identifier_types, consent_policy_reference, owner; null means unknown.
- `export/external/enhanced_web_diagnostics.csv`: account_id/action_id/window_start/window_end/implementation_method grain, from Ads diagnostics.
  Columns: eligible_events, enhanced_events, accepted_events, diagnostic_code, diagnostic_status, metric_name, metric_numerator, metric_denominator, processing_mature, source_reference.
- `export/external/enhanced_web_traces.csv`: synthetic test_id/action_id/scenario/step grain, from authorized tag QA of current deployment.
  Columns: tested_at, deployment_version, browser_class, consent_state, event_trigger, destination_correct, identifier_type_presence, normalization_check, hashing_method, hashing_check, duplicate_send_count, expected_behavior, observed_behavior, trace_reference.
  Include valid/invalid/repeated submission and accept/deny scenarios where applicable. Supply field types and checks only, not identifier values or hashes.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Identify eligible actions and conversion-owning account. Never use enhanced_conversions_for_leads_enabled as Web evidence.
2. Join actual Web settings to action diagnostics; enabled status alone does not prove capture or transmission.
3. Compare synthetic traces to intended event trigger and destination. Check normalization and hashing for the chosen method, including automatic versus already-hashed inputs.
4. Verify supported identifier combinations available with permission. Missing email or optional phone/name alone is not a defect if method requirements are satisfied.
5. Diagnose duplicate sends or wrong destinations separately from enhancement; route material baseline tracking faults to 071/110.
6. Interpret rates using source-defined eligible denominators, processing maturity, and comparable historical evidence. There is no universal 25% match-rate defect threshold.
7. Route consent behavior to 075. Hashing is not anonymization or legal approval; do not expand personal-data capture just to improve diagnostic scores.
8. Non-adoption is an optional opportunity, not Critical. Propose owner-reviewed correction only for corroborated implementation errors.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Traces confirm material measurement failure or prohibited transmission under supplied technical policy | Critical |
| Chosen Web implementation has reproducible rejected payloads or incorrect routing | Warning |
| Mature source-defined diagnostics materially deteriorate against comparable baseline | Warning |
| Web not adopted, optional fields absent, or settings unknown | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Report Web account/action state with source, explicitly separate from Leads status.
- Include field-type coverage, synthetic scenario outcomes, diagnostic denominators, and implementation/consent owners.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
