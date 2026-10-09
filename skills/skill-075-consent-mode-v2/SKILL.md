---
name: skill-075-consent-mode-v2
description: "Assess consent-state behavior using configuration and traces without certifying legal compliance."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-072-enhanced-conversions-web, skill-073-enhanced-conversions-leads, skill-074-server-side-tagging-assessment, skill-110-conversion-tracking-breakage]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 075: Consent Mode v2 Technical Assessment

## Purpose

Assess consent-state behavior using configuration and traces without certifying legal compliance.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Web/app tagging paths covered by owner-supplied regional consent requirements and chosen basic or advanced mode.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `conversion_actions`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/consent_configuration.csv`: site_id/region_rule_id/deployment_version grain, from sanitized CMP/tag configuration at current snapshot.
  Columns: account_id, platform, cmp_version, chosen_mode_basic_or_advanced, regional_scope, default_ad_storage, default_analytics_storage, default_ad_user_data, default_ad_personalization, default_timing_rule, update_trigger, wait_for_update_ms, withdrawal_behavior, approved_policy_reference, technical_owner, privacy_owner.
- `export/external/consent_traces.csv`: synthetic test_id/site_id/region_rule_id/scenario/sequence grain, from authorized Tag Assistant/network/storage QA of that version.
  Columns: timestamp, relative_ms, event_type, tag_destination, ad_storage, analytics_storage, ad_user_data, ad_personalization, consent_default_or_update, request_class, cookie_read_observed, cookie_write_observed, identifier_present, payload_classification, expected_behavior, observed_behavior, trace_reference.
  Cover fresh visit/no choice, deny, accept, partial choice, withdrawal, return visit, and regional defaults; redact network payloads and all cookie/identifier values.
- Optional `export/external/consent_modeling_diagnostics.csv`: account_id/action_id/window_start/window_end grain, from Ads diagnostics.
  Columns: reported_modeling_status, source_eligibility_message, processing_mature, source_reference; do not infer eligibility from account ownership or a generic traffic count.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Map regional/site scope to the chosen mode and supplied approved technical policy. Do not infer legal obligations or legal approval from traffic geography alone.
2. Verify all four signals, including ad_user_data and ad_personalization, in defaults and updates. Null or absent evidence is unknown, not denied/granted.
3. For basic mode, verify Google tags are blocked until the documented consent decision allows loading and that consent updates are propagated correctly.
4. For advanced mode, Google tags may load with denied defaults and send cookieless pings. Pre-consent tag firing alone is not a defect; inspect signal state, payload class, and prohibited storage/identifier behavior.
5. Check default-before-measurement ordering, asynchronous CMP timing, regional rules, partial consent, repeated updates, and withdrawal against expected behavior. Do not prescribe a universal wait duration.
6. Corroborate a mismatch with reproducible synthetic traces; a conversion-account ownership query cannot verify consent behavior.
7. Report modeling status only from direct diagnostics; low volume or unavailable modeling is not a consent defect and no recovery percentage is guaranteed.
8. Escalate confirmed technical-policy violations to the implementation/privacy owners; do not label the account GDPR/CCPA compliant or noncompliant.
9. Use [Google consent mode concepts](https://developers.google.com/tag-platform/security/concepts/consent-mode) for basic/advanced semantics; implementation behavior does not replace legal review.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Reproducible traces show material prohibited transmission/storage contrary to supplied consent policy | Critical |
| Confirmed missing/misordered required signal or incorrect update creates technical risk | Warning |
| Advanced denied-state cookieless behavior matches declared design | Info |
| Policy/traces unavailable, optional modeling unavailable, or regional applicability unknown | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Report mode, tested region/scenario/version, expected versus observed signals/storage, evidence references, and untested paths.
- Label conclusions technical behavior only; include implementation and privacy owners, never a legal compliance badge.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
