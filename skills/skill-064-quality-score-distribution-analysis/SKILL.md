---
name: skill-064-quality-score-distribution-analysis
description: "Monitor Quality Score distribution, flag high-spend low-QS keywords with their weak component, and recommend monitoring alerts."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: quality
  kind: deterministic
  data_source: export
  merged_from: [skill-129-quality-score-monitoring-alert-rules]
  related: [skill-065-quality-score-component-breakdown, skill-066-historical-quality-score-trend, skill-067-expected-ctr-improvement]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 064: Quality Score Distribution Analysis

## Purpose

Low Quality Scores raise CPCs and lower positions. Measure the distribution and impression-weighted average, isolate high-spend keywords at QS 1-5 with the component that drags them (expected CTR, ad relevance, landing page), quantify the spend exposed, and propose alert rules so regressions surface without a manual audit.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Keywords** - Keyword Quality Score data including overall QS and components
- **Keyword metrics (30 days)** - Keyword performance metrics

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.quality_info.quality_score,
  ad_group_criterion.quality_info.creative_quality_score,
  ad_group_criterion.quality_info.post_click_quality_score,
  ad_group_criterion.quality_info.search_predicted_ctr,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND campaign.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) if you need additional metrics or different date ranges.

## Analysis Steps

1. **Load keyword QS data:** Quality Score and the three components per enabled keyword
2. **Calculate distribution:** Keywords by bucket (1-3, 4-5, 6-7, 8-10, N/A) and impression-weighted average (target > 6)
3. **Flag high-spend low QS:** Cost >= {{spend_significant}} at QS 1-3; Cost >= {{spend_material}} at QS 4-5
4. **Identify the weak component:** For every flagged keyword, which component is Below Average
5. **Quantify exposure:** Spend on QS 1-3 keywords as a share of total spend
6. **Recommend alert rules:** QS <= 3 with impressions > {{min_impressions}}; QS drop of 2+ points (operational follow-up)

## Thresholds

| Condition | Severity |
|-----------|----------|
| Keyword QS 1-3 with Cost > {{spend_significant}}/30d | Critical |
| Keyword QS 1-3 with Impressions > {{min_impressions}} | Critical |
| > 20% of keywords have QS 1-3 | Critical |
| Weighted average QS < 5 | Critical |
| Keyword QS 4-5 with Cost > {{spend_material}}/30d | Warning |
| Any component Below Average on a keyword above {{spend_significant}}/30d | Warning |
| Weighted average QS 5-6 | Warning |
| QS dropped 2+ points vs previous snapshot (when history is available) | Warning |

## Output

**Short (default):**
```
## Quality Score Distribution Audit

**Account:** [Name] | **Keywords Analyzed:** [X] | **Weighted Avg QS:** [Y]

### Distribution
| QS Range | Count | % |
|----------|-------|---|
| 8-10 | [X] | [%] |
| 6-7 | [X] | [%] |
| 4-5 | [X] | [%] |
| 1-3 | [X] | [%] |

### Critical ([Count])
- **[Keyword]** in [Ad Group]: QS [X], {{currency}} [Cost] -> [Primary issue component]

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- Full keyword list with QS and components
- QS by campaign breakdown
- Component analysis (CTR, Relevance, LP)
- Estimated CPC savings from QS improvements
- Spend on low-QS keywords by bucket
- Recommended alert rules (Google Ads automated rules configuration)
