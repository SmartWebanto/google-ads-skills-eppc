---
name: skill-127-trending-search-term-detection
description: "Track week-over-week search query volume shifts to identify emerging opportunities and declining terms."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-127-trending-search-term-detection
  category: waste
  kind: deterministic
  data_source: custom_query
  related: [skill-013-search-term-mining-keywords, skill-014-search-term-mining-negatives]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 127: Trending Search Term Detection

## Purpose

Analyze search term data across time periods to identify rising trends (opportunities to add as keywords), declining terms (investigate relevance), and new emerging queries worth capturing.

## Data Requirements

**Data Source:** Custom query required

**Export data:**
- **Search terms (30 days)** - Recent search terms

**GAQL Query (for trend analysis):**
```sql
SELECT
  search_term_view.search_term,
  campaign.name,
  ad_group.name,
  segments.date,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_14_DAYS
  AND metrics.impressions > 0
ORDER BY search_term_view.search_term, segments.date
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `search_term_trends`.

## Analysis Steps

1. **Fetch multi-period data:** Get search term data segmented by date for trend analysis
2. **Calculate week-over-week changes:** Compare this week vs last week impressions/clicks
3. **Identify rising trends:** Terms with >50% impression increase
4. **Flag declining terms:** Terms with >30% impression decrease
5. **Spot new terms:** First-time appearances with conversion potential

## Thresholds

| Condition | Severity |
|-----------|----------|
| New term with conversion, not added as keyword | Critical |
| Rising term (>100% increase) with good CTR | Warning |
| Declining term (>50% drop) with high spend | Warning |
| High-volume term not in keyword list | Info |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short format (default):**
```
## Search Term Trends Audit

**Account:** [Name] | **Period:** Last 14 days | **Trending Terms:** [X]

### Rising Trends - Add as Keywords ([Count])
- **"[Term]"**: +[X]% impressions, [Y] conversions → Add as [match type]
- **"[Term]"**: +[X]% impressions, high CTR → Add as exact match

### New High-Potential Terms ([Count])
- **"[Term]"**: First appearance, [X] conversions → Add immediately

### Declining Terms - Investigate ([Count])
- **"[Term]"**: -[X]% impressions → Check relevance/seasonality

### Recommendations
1. Add [X] rising terms as keywords
2. Investigate [Y] declining terms
3. Monitor [Z] new terms for patterns
```

**Detailed adds:**
- Full trending terms table with metrics
- Week-by-week volume comparison
- Seasonal pattern identification
- Keyword addition recommendations with match types
