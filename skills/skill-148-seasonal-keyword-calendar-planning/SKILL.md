---
name: skill-148-seasonal-keyword-calendar-planning
description: "Plan seasonal query coverage and launch dependencies without fixed lead times or literal-keyword quotas."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 148: Seasonal Query and Keyword Planning

## Purpose

Plan seasonal query coverage and launch dependencies without fixed lead times or literal-keyword quotas.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Search campaigns with relevant planned events and historical/current query evidence.

**Required inputs:**
- Base `export/` tables: account, campaigns, keywords, search_terms, negative_keywords, shared_negative_lists, ads, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/seasonal_keyword_plan.csv`: one row per event_id/campaign_id: name, start_at, end_at, timezone, objective, offer, expected_cvr_change, rationale, owner, approval_status, normal_baseline_dates; client calendar snapshot covering relevant past events and next 60 days; add landing_page_ref, stock_or_capacity, draft_copy_ref, approval_dependencies, planned_launch_at, planned_pause_at.
- `export/custom/seasonal_query_history.csv`: account_id/campaign_id/ad_group_id/query/matched_keyword_id/date grain; match_type, impressions, clicks, cost, conversions, conversion_value, reported_coverage; Ads term reports for prior event/normal periods and current 30 mature days, not only converting rows.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Map approved event offers, service/stock availability and target dates, not generic holidays inferred from names.

2. Identify historical relevant queries and outcome evidence within comparable goals. Distinguish prior event language from obsolete years/offers.

3. Check current exact/phrase/broad/close-variant reach and negative conflicts; absence of literal keyword is not missing query coverage.

4. Review ad/page readiness from actual drafts. A query addition proposal needs campaign/ad-group/match-type scope and intended value, not one historical conversion.

5. Set launch timing from approvals, stock, experiment needs and measured account latency. No universal four-week lead time, Smart Bidding learning duration or Quality Score ramp claim.

6. Route candidate additions to skill-013 and schedule execution proposals to skill-130; never create keywords or ads.

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
| Approved launch blocked by evidenced relevant targeting conflict or unavailable required content | Warning |
| Historical candidate, unsupported coverage hypothesis or incomplete calendar | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Event-query-current-match coverage matrix with IDs, negatives, samples and intent review.
- Request-only keyword/copy readiness calendar and dependencies, no mandatory launch lead time.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
