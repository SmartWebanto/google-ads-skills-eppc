---
name: skill-102-frequency-capping-management
description: "Review supported frequency controls using measured reach and exposure rather than cap absence or universal limits."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: remarketing
  kind: analyst
  data_source: external
  related: [skill-128-performance-max-channel-performance, skill-162-creative-asset-quality-ai-campaign-optimization]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 102: Frequency Capping and Exposure Review

## Purpose

Distinguish configured caps from actual delivered exposure and investigate potential fatigue in context. No explicit cap does not mean unlimited delivered impressions or proven waste.

## Data Requirements

**Applicability:** Display/Video and other campaign subtypes only where current platform evidence exposes frequency reports or supports a relevant control; do not promise PMax per-channel caps.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/frequency_controls.csv`: current Ads configuration review, one row per account_id, campaign_id and cap/control_id; subtype, objective, audience_role, strategy, cap_status (explicit/automatic/not_supported/unknown), event_type (impression/view), entity_level, maximum_count, period, timezone, supported_controls, source_url/reference and observed_at. Preserve all layered caps and supported target-frequency modes.
- `export/custom/frequency_exposure.csv`: actual Ads unique-reach/frequency report for complete matched 7/28-day or supported report windows, one row per account_id, campaign_id, report_start/end, population_scope and reported_frequency_bucket; impressions, unique_users, average_impression_frequency when exposed, reach_by_bucket, report_definition, deduplication_scope, modeled_status, privacy/suppression flags and report_source. Totals are separate rows; do not sum unique users across dates/buckets/campaigns.
- `export/custom/frequency_outcomes.csv`: optional actually available exposure-cohort outcomes, same window/population/bucket keys; exposed_people, clicks, cost, conversions, conversion_value, goal_set_id, attribution_definition and coverage. If no frequency-bucket outcome report is available, use campaign outcomes descriptively, never fabricate it.
- `export/external/frequency_plan.csv`: current client plan at campaign_id and audience_role; approved exposure objective/bounds, creative_rotation, sales_cycle, budget constraint, actual fatigue evidence reference, approved_test_metric and owner.

**Missing inputs:** Without unique reach/exposure no delivered-frequency or excess-impression estimate is possible; without control evidence no cap proposal. Missing outcome cohorts means fatigue is a hypothesis, not a diagnosis. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Inventory subtype, objective and every actual cap including event type, period and level. Distinguish manual cap, automated/target-frequency mode, unsupported control and unknown settings; do not conflate video-view caps with impression caps.

2. Calculate impressions / unique_users only for a matching nonzero deduplicated population/window where the report defines the same quantities. Prefer the platform-reported average when definitions differ. Do not sum daily or cross-campaign unique reach or mechanically convert daily caps into observed weekly exposure.

3. Inspect the actual exposure distribution and modeled/privacy limitations. High average frequency does not show every user overexposed; bucket counts must be nonoverlapping or clearly labeled cumulative before deriving percentages.

4. Compare exposure with the client goal, creative rotation and buying cycle. Repeated exposure can be intentional for awareness or complex purchases; a low cap can limit a stated reach/frequency objective, but no universal 3–5/week benchmark applies.

5. Use matched mature outcomes or documented customer/creative evidence to screen fatigue, controlling for time, audience mix and selection into higher frequency. Correlation between frequency and declining response is not proof additional impressions caused harm; do not compute wasted spend by subtracting a chosen cap.

6. If supported and evidence-led, propose a bounded cap/target-frequency or creative-rotation test with explicit event, level, period, metrics and rollback. Delegate creative critique to 162 and PMax channel diagnostics to 128; do not invent control availability.

## Thresholds

| Condition | Severity |
|---|---|
| Measured exposure contradicts an approved campaign constraint or corroborated fatigue evidence warrants review | Warning |
| No explicit cap, high/low configured cap alone or an intentional repeated-exposure setup | Info |
| Supported bounded exposure/creative test with evidence but no causal harm proof | Info |
| Unavailable reach distribution, suppressed data, insufficient samples or unknown control applicability | Info |

Use [PARAMETERS.md](../_resources/PARAMETERS.md) and resolved client overrides.
CTR comparisons require {{min_impressions}}, conversion-rate comparisons {{min_clicks}},
and CPA/ROAS comparisons {{min_conversions}} on **both** comparable sides.
Use mature, equal-length windows with matched goals, currency and attribution basis;
exclude incomplete days and conversion lag, and never divide by zero.
Numerical screens without a cited platform requirement are triage heuristics, not proof of harm.
Critical requires directly evidenced material delivery, measurement or safety failure.
Missing evidence and optional-feature absence are Info, not a failed or passed check.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), not a separate competing template.
Report stable entity IDs, condition key, observed evidence/window, sample denominators,
resolved thresholds, recommendation, uncertainty and the owning skill.

- Show campaign/control IDs, subtype, event/period/level and explicit/automatic/unsupported/unknown status.
- Report measured average and exposure distribution with population/window/unique-reach denominator and modeling limitations.
- Separate configured caps, delivered exposure and fatigue hypotheses; include applicable proposal details without universal limits or savings estimates.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
