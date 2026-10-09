---
name: skill-149-promotional-extensions-countdown-customizers
description: "Check actual offer alignment and serving configuration; promotion/countdown adoption is optional."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 149: Promotion Asset and Countdown Review

## Purpose

Check actual offer alignment and serving configuration; promotion/countdown adoption is optional.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Time-limited offers with actual linked assets or ad countdown text and known campaign scope.

**Required inputs:**
- Base `export/` tables: account, campaigns, ads, assets, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/promotion_offers.csv`: offer_id/campaign_id/market grain; offer_text, discount_type/value, currency, eligibility, minimum_order, promo_code, start_at, end_at, timezone, landing_page_snapshot_ref, approved_by; current client offer/calendar records.
- `export/custom/promotion_config.csv`: account_id/asset_or_ad_id/association_id/snapshot_at grain; campaign_id, ad_group_id, linking_level, status, policy_status, configured_discount, start/end_dates, schedule, countdown_raw_text, countdown_timezone_mode, preview_at, preview_result, actual_serving_dates; Ads asset/ad settings, previews and dated delivery for event and adjoining dates.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Resolve asset hierarchy and associations to eligible campaign/ad-group scope; an unlinked asset cannot prove coverage.

2. Compare configured discount, currency, code, minimum order, eligibility and destination against actual approved offer.

3. Check countdown syntax using supplied preview, account/user-timezone mode and intended end time; distinguish account-wide and viewer-relative timing. Do not invent platform syntax from a guessed example.

4. An expired setting is not proof of inappropriate serving: check schedules, eligibility and dated delivery. A past countdown may simply stop eligible serving.

5. Absence of promotion assets, countdowns or seasonal copy is an optional creative opportunity, not a defect or proven missed uplift.

6. Draft corrected field values with asset/ad IDs, source offer, scope, timezone, owner and confirmation request; do not create/update/remove assets.

Use matched IDs and declared grain before joining; never multiply entity metrics across many-to-many associations.
For comparisons, align goals, traffic scope and complete periods; exclude incomplete days and conversion reporting lag.
Use {{min_impressions}} for CTR/share, {{min_clicks}} for CVR and {{min_conversions}} for CPA/ROAS, on both comparison sides.
A zero-conversion spend screen may bypass min_conversions only after maturity, working tracking and relevance review at {{spend_floor}}.
Do not divide by zero; preserve censored, suppressed and unknown values rather than treating them as zero.
Historical non-converting cost is exposure, not guaranteed savings; observational changes are not causal uplift.

## Thresholds

Numerical cutoffs here are triage heuristics unless explicitly tied to a sourced platform requirement.
Resolve parameters through [PARAMETERS](../_resources/PARAMETERS.md); business tolerances require a declared value.

| Condition | Severity |
|---|---|
| Confirmed material live misleading or invalid offer delivery | Critical |
| Configured offer or countdown conflicts with approved terms and intended scope | Warning |
| Expired non-serving config or absent optional promotion/countdown feature | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Offer-to-association matrix and countdown preview evidence with date/timezone.
- Actual versus potential exposure, exact request-only field corrections and optional test proposals.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
