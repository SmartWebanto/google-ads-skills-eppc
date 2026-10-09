---
name: skill-112-return-refund-tracking
description: "Reconcile returns and refunds with the chosen value policy and supported adjustment records."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-071-conversion-tracking-accuracy, skill-076-conversion-action-configuration, skill-080-offline-conversion-import, skill-107-conversion-value-accuracy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 112: Refund and Conversion Adjustment Reconciliation

## Purpose

Reconcile returns and refunds with the chosen value policy and supported adjustment records.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Business outcomes whose chosen value basis includes return/refund effects; gross-value reporting may be intentional.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- Require skill 107's `export/external/conversion_value_policy.csv` for gross/net, refund, currency, and fallback treatment.
- `export/external/refund_ledger.csv`: account_id/action_id/order_token/refund_token grain, from OMS/finance for the purchase cohort through the declared refund-maturity snapshot.
  Columns: purchase_timestamp, refund_timestamp, refund_status, original_value, refunded_value, tax_refund, shipping_refund, fee_treatment, expected_remaining_value, currency, order_status, source_reference.
  Include aggregate evidence of zero refunds when attested complete; no customer/order-identifying payloads.
- `export/external/conversion_adjustments.csv`: account_id/action_id/order_token/adjustment_attempt_id grain, from integration logs and Ads adjustment diagnostics through snapshot.
  Columns: adjustment_type, adjustment_timestamp, submitted_at, processed_at, original_record_match_method, supported_identifier_present, prior_reported_value, restated_total_value, currency, status, rejection_code, retry_of_attempt_id, source_reference.
- `export/external/adjustment_support.csv`: account_id/action_id/source_type/snapshot grain, from current method documentation and action settings.
  Columns: supports_restatement, supports_retraction, accepted_match_method, time_limit_reference, eligibility_status, source_reference, verified_at, owner; unsupported/unknown methods must not be guessed.
- Actual Ads/business count-value reconciliation uses skill 071's rules and daily report schemas; event tokens link local ledgers, not raw click IDs or personal identifiers.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Confirm intended gross/net/profit policy and whether returns are already netted at initial import, modeled upstream, or adjusted afterward. Do not deduct the same refund twice.
2. Deduplicate refund events and distinguish pending, canceled, partial, full, and repeated refunds against the original purchase cohort; align currency and tax/shipping rules.
3. Derive expected remaining value from policy and mature ledger, not industry return rates. Immature return cohorts require uncertainty, not a final ROAS claim.
4. Compare local original/import values and accepted adjustments to expected remaining value. A submitted adjustment is not necessarily accepted or reflected in reporting.
5. Verify action/source support, match method, and current adjustment time limits. GCLID is not universally necessary where a supported order-based method exists; require presence checks only.
6. Distinguish retraction from restatement. A restatement supplies the supported method's new total value, not blindly a negative refund delta; do not recommend negative conversion uploads as a generic replacement.
7. Inspect partial failures, duplicate retries, currency mismatch, unmatched originals, and already-adjusted events before any proposed correction.
8. Quantify residual value differences through 071 on a comparable cohort. ROAS difference = residual value / same attributable spend only with nonzero spend and mature scope; no generic 10–30% overstatement.
9. Recommend owner-reviewed reconciliation or supported adjustment proposal only. Do not submit adjustments or immediately reduce all values by an assumed return rate.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Reconciliation confirms material double deduction, incorrect adjustment, or net-value corruption | Critical |
| Mature refund treatment conflicts with intended policy or supported adjustments repeatedly fail | Warning |
| Business-backed review of gross versus net reporting or refund modeling | Info |
| No return imports alone, gross policy, immature refunds, or unknown adjustment support | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include cohort/order/action tokens, policy basis, expected versus accepted remaining value, matching/support evidence, and pending/rejected counts.
- Report attributable residuals and maturity limits; preserve gross reporting when intended and never infer industry-based overstatement.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
