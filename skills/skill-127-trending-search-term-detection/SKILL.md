---
name: skill-127-trending-search-term-detection
description: "Track changes in reported query traffic without treating first observation as market novelty or demanding keyword additions."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: analyst
  data_source: custom_query
  related: [skill-013-search-term-mining-keywords, skill-014-search-term-mining-negatives]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 127: Observed Search Term Trend Review

## Purpose

Track changes in reported query traffic without treating first observation as market novelty or demanding keyword additions.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Campaigns with comparable dated search-term coverage; privacy-suppressed queries remain unobserved.

**Required inputs:**
- Base `export/` tables: account, campaigns, keywords, negative_keywords, shared_negative_lists, search_terms, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/search_trend_daily.csv`: account_id/campaign_id/ad_group_id/query/date/matched_keyword_id grain; match_type, added_or_excluded, impressions, clicks, cost, conversions, conversion_value, reporting_coverage; Ads search-term report for 8 complete weeks, same filters and conversion basis.
- `export/custom/search_trend_changes.csv`: account_id/campaign_id/change_id grain; occurred_at, changed_field, old_value, new_value, source; Ads targeting/budget/match/reporting changes covering trend dates.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Compare two complete, equal weekday-aligned mature weeks within the 8-week history; normalize text for grouping without losing raw query or matching IDs.

2. Compute growth = current/prior minus 1 only for positive prior counts; first-reported terms use absolute counts and earliest observed date, not infinite growth or true novelty.

3. Use one consistent screen: >50% growth or >30% decline with {{min_impressions}} in both periods for impression trends. Rate/efficiency comparisons obey their own sample gates.

4. Check budget, serving, matching, reporting suppression and tracking changes before interpreting demand. Observed ads query volume is not total market demand.

5. Check existing exact/phrase/broad coverage and shared negatives; no literal keyword does not mean missing reach. Route additions to skill-013 and negatives to skill-014 with intent/goal evidence, rather than adding immediately.

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
| Comparable >30% decline with material exposure and an identified serving risk | Warning |
| Comparable >50% growth suggesting a relevance/coverage review | Info |
| First reported term, sparse history or changed reporting coverage | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Query/campaign/ad-group/keyword IDs, dates, counts, growth branch, coverage and confounders.
- Ranked relevance/coverage hypotheses with linked existing match coverage and canonical handoff.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
