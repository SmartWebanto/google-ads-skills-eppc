---
name: skill-066-historical-quality-score-trend
description: "Identify trending Quality Score degradation by comparing current QS to historical baselines."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-066-historical-quality-score-trend
  category: quality
  kind: deterministic
  data_source: custom_query
  related: [skill-064-quality-score-distribution-analysis, skill-065-quality-score-component-breakdown, skill-067-expected-ctr-improvement]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 066: Historical Quality Score Trend

## Purpose
Identify trending Quality Score degradation by comparing current QS to historical baselines. Declining QS indicates worsening ad relevance, landing page issues, or competitive pressure that needs attention.

## Data Requirements

**Data Source:** Custom query required

A basic account export provides current QS but not historical snapshots. Google Ads does not store historical QS by default.

**Export data:**
- **Keywords** - Current Quality Score data

**GAQL Query (Current State):**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_criterion.keyword.text,
  ad_group_criterion.quality_info.quality_score,
  ad_group_criterion.quality_info.search_predicted_ctr,
  ad_group_criterion.quality_info.creative_quality_score,
  ad_group_criterion.quality_info.post_click_quality_score,
  metrics.impressions,
  metrics.cost_micros
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND campaign.status = 'ENABLED'
  AND metrics.impressions > 0
  AND segments.date DURING LAST_30_DAYS
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `quality_score_current`.

Note: Historical QS tracking requires external snapshots (Google Ads scripts) since Google does not store QS history.

## Analysis Steps

1. **Establish current baseline:** Calculate weighted average QS and distribution by bucket.
2. **Compare to historical data:** If snapshots available, calculate QS change over time.
3. **Flag declining keywords:** Keywords with QS decline >= 2 points are priority issues.
4. **Investigate systematic declines:** Look for patterns (same ad group, landing page, match type).

## Thresholds

| Condition | Severity |
|-----------|----------|
| Weighted QS dropped >1 point in 30 days | Critical |
| 5+ keywords dropped QS by 2+ points | Critical |
| Landing Page component declined account-wide | Critical |
| Any QS 8-10 dropped to 6 or below | Warning |
| Expected CTR trending down across keywords | Warning |
| Single keyword QS dropped 3+ points | Warning |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Quality Score Trend Audit

**Account:** [Name] | **Keywords Analyzed:** [X] | **Declining:** [Y]

### Current State
- Weighted Avg QS: [X.X]
- % Keywords QS 6+: [X]%

### Critical ([Count])
- **[Keyword]**: QS dropped from [X] to [Y] -> Investigate [component]

### Warnings ([Count])
- **[Keyword]**: [Trend issue] -> [Fix]

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- QS distribution trend over time (if historical data available)
- Component trend analysis
- Systematic decline patterns
- Investigation checklist
