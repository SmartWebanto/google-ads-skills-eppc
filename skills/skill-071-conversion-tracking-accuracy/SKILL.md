---
name: skill-071-conversion-tracking-accuracy
description: "Reconcile comparable business events and values without mistaking attribution differences for faults."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-070-conversion-tracking-completeness, skill-072-enhanced-conversions-web, skill-073-enhanced-conversions-leads, skill-076-conversion-action-configuration, skill-107-conversion-value-accuracy, skill-110-conversion-tracking-breakage, skill-112-return-refund-tracking]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
  merged_from: [skill-108-cross-device-conversion-tracking]
---
# Skill 071: Conversion Reconciliation and Direct Cross-Device Evidence

## Purpose

Reconcile comparable business events and values without mistaking attribution differences for faults.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Accounts with documented business-event mappings; cross-device analysis requires direct measured evidence.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/reconciliation_rules.csv`: account_id/action_id/business_event_id grain, from finance and measurement owners.
  Columns: source_event, counting_unit, eligible_channel_scope, attribution_model, lookback_days, date_basis, timezone, currency, value_basis, tax_shipping_discount_treatment, refund_treatment, maturity_days, tolerance_count_pct, tolerance_value_pct, rationale.
- `export/external/business_events.csv`: event_token/action_id grain, from CRM/OMS for analysis window plus conversion/refund maturity tail.
  Columns: event_timestamp, eligible_scope, stage, deduplication_key_token, gross_value, tax, shipping, discount, refund_value_to_snapshot, expected_value, currency, source_status, attribution_credit_if_available.
- Optional `export/external/ads_event_reconciliation.csv`: event_token/action_id grain, locally prepared tag/import ledger over the same window.
  Columns: expected_send_count, observed_send_count, sent_value, accepted_count, rejected_count, currency, diagnostic_status; not a claimed Ads user-level attribution export.
- `export/custom/ads_reconciliation_daily.csv`: account_id/campaign_id/action_id/date/date_basis grain, from Ads reporting.
  Columns: conversions, all_conversions, conversion_value, all_conversion_value, currency, modeled_included, reporting_mature; do not duplicate campaign totals.
- Optional `export/external/cross_device_measured.csv`: account_id/action_id/window_start/window_end/report_scope grain, from a direct cross-device measurement report.
  Columns: source_metric_name, measured_cross_device_conversions, comparable_total_conversions, total_metric_definition, date_basis, attribution_scope, modeled_included, suppression_status, method, source_reference.
  Accept only an explicitly measured numerator that is a subset of the denominator; no user paths, fingerprints, or identity data.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Align event, channel scope, counting unit, currency, timezone, attribution model/window, and conversion versus interaction date. Total CRM sales need not equal Ads-attributed conversions.
2. Deduplicate business events without merging different funnel stages. Reconcile refunds using the agreed gross/net policy and snapshot, not blanket deductions.
3. Where a local ledger exists, compare expected/observed sends and accepted uploads by token/action. This does not prove individual Ads attribution matches.
4. Otherwise compare aligned aggregate cohorts; identify attribution, modeling, consent, counting, window, and reporting differences before deriving residuals.
5. Count variance = (Ads count - comparable expected count) / comparable expected count. Value variance uses expected value as denominator. Report signed absolute differences; zero denominators make relative variance unavailable.
6. Apply owner tolerances to unexplained residuals only. Corroborate duplicate, missing, or wrong-value events independently before diagnosing a fault; Ads excess alone is not Critical.
7. Use only direct measured cross-device data within source scope and suppression limits. If a metric includes modeling, disclose it and skip any measured-only conclusion that cannot be isolated.
8. Never use conversions versus all_conversions, mobile/desktop totals, or Enhanced Conversions absence as a cross-device-gap proxy. Measured contribution does not estimate missing paths or recovery.
9. Route policy to 107, refunds to 112, attribution settings to 076, tag diagnostics to 072/073; no device bid recommendations from this reconciliation.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Independent reconciliation confirms material duplicate, missing, or incorrect events/values | Critical |
| Comparable mature residual exceeds documented tolerance but cause/materiality remains uncertain | Warning |
| Explained attribution differences or direct cross-device contribution without a demonstrated fault | Info |
| Incomparable cohorts, suppressed/absent direct measurement, or zero denominator | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include matching rules, expected/Ads counts and values, signed residuals, denominators, explained adjustments, unmatched counts, and excluded non-comparable cohorts.
- Cross-device appendix names the direct source metric and observation/modeling limits; no gap or uplift estimate.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
