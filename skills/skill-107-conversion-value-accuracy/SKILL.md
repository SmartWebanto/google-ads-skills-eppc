---
name: skill-107-conversion-value-accuracy
description: "Assess value semantics and implementation against declared business objectives and reconciled outcomes."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-070-conversion-tracking-completeness, skill-071-conversion-tracking-accuracy, skill-076-conversion-action-configuration, skill-110-conversion-tracking-breakage, skill-112-return-refund-tracking]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 107: Conversion Value Policy and Accuracy

## Purpose

Assess value semantics and implementation against declared business objectives and reconciled outcomes.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** All conversion value policies; missing or unit values are not defects for legitimate count-based objectives.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`, `bidding_strategies`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/conversion_value_policy.csv`: account_id/action_id/policy_version grain, from business/finance measurement owners.
  Columns: objective, intended_bidding_role, value_type, formula, gross_or_net_basis, tax_treatment, shipping_treatment, discount_treatment, refund_treatment, currency, fx_source, fx_date_rule, rounding_rule, fallback_value, fallback_conditions, validity_start/end, calibration_window, owner.
- `export/external/value_payload_qa.csv`: synthetic test_id/action_id/scenario grain, from authorized tag/import QA of current version.
  Columns: tested_at, policy_version, expected_value, observed_value, currency, value_source, default_used, duplicate_send_count, status, source_reference; scenarios include ordinary, zero, missing, discounted, and refunded outcomes where applicable.
- Actual financial accuracy requires skill 071's `reconciliation_rules.csv`, `business_events.csv`, and `ads_reconciliation_daily.csv` for the same mature window.
  Use optional `ads_event_reconciliation.csv` when locally available; policies and default settings alone cannot establish transaction accuracy.
- Lead/LTV/profit models require `export/external/value_model_calibration.csv`: action_id/model_version/cohort_start/cohort_end/stage grain, from aggregate CRM/finance calibration.
  Columns: cohort_size, mature_outcomes, close_rate, realized_net_value, margin_basis, horizon_days, observed_vs_predicted_value, selection_scope, uncertainty, source_reference; no customer histories.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Map action values to effective campaign goal and count/value strategy. Unit or zero values may intentionally represent counts and do not inherently mean placeholder mistakes.
2. Identify static, dynamic, proxy, profit, or predicted lifetime-value policy from owner definitions, not observed value alone.
3. Compare actual default/always-use-default and payload behavior with the chosen policy; static values may be legitimate and no default fallback is universally required.
4. Verify tax, shipping, discounts, refunds, currency/FX, and rounding are consistently treated as specified. Gross or net is a business choice, not a universal correction.
5. Use 071 for measured count/value reconciliation and signed residuals; do not infer a 15% discrepancy from settings. Link its finding instead of duplicating it.
6. For proxy/lead/LTV values inspect calibration cohort maturity, selection, horizon, and uncertainty. Do not invent close rates, margin percentages, or revenue forecasts.
7. Distinguish a model needing review from confirmed wrong currency, duplicate sends, or material value-policy failure.
8. Coordinate refunds with 112 to prevent double deduction; recommend a scoped value-policy or payload review, never automatic value reduction.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Independent evidence confirms material value corruption or objective failure | Critical |
| Payload/default/currency behavior conflicts with documented value policy | Warning |
| Mature calibration shows material model drift beyond owner tolerance | Warning |
| Count-based zero/unit value, justified static/gross values, or unknown business basis | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include value-policy inventory by action/strategy, policy version, QA comparisons, calibration limits, and linked 071 residuals.
- State gross/net and refund treatment consistently in both findings and recommendations; no unsupported ROAS-gap estimate.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
