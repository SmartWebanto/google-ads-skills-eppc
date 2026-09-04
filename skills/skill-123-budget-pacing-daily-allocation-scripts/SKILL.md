---
name: skill-123-budget-pacing-daily-allocation-scripts
description: "Analyze day-of-week performance to recommend daily budget allocation and monthly pacing strategies."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: waste
  kind: operational
  data_source: custom_query
  related: [skill-044-monthly-budget-pacing-analysis]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 123: Budget Pacing and Daily Allocation

## Purpose

Analyze day-of-week performance patterns to optimize daily budget allocation and ensure proper monthly budget pacing. This helps capture more conversions on high-efficiency days while avoiding under/overspend.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include day-of-week segmented data.

**GAQL Query:**
```sql
SELECT
  campaign.name,
  campaign.id,
  segments.day_of_week,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
  AND campaign.status = 'ENABLED'
ORDER BY campaign.name, segments.day_of_week
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `day_of_week_performance`.

## Analysis Steps

1. **Fetch day-of-week data:** Run custom GAQL query for 90 days of segmented data
2. **Calculate efficiency indices:** Compare CPA/ROAS by day vs weekly average
3. **Identify patterns:** Flag high-efficiency days (low CPA) and low-efficiency days (high CPA)
4. **Design allocation strategy:** Create day-based budget multipliers
5. **Check monthly pacing:** Compare spend-to-date vs budget-to-date

## Thresholds

| Condition | Severity |
|-----------|----------|
| Day CPA > 50% above average | Critical |
| Monthly underpacing > 20% | Warning |
| Monthly overpacing > 10% | Warning |
| Day efficiency variance > 30% | Info |

Sample size: judge CTR rows only above {{min_impressions}} impressions, conversion-rate rows only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short format (default):**
```
## Budget Pacing Audit

**Account:** [Name] | **Monthly Budget:** {{currency}} [X] | **Pacing:** [On Track/Under/Over]

### Day-of-Week Efficiency
| Day | CPA | Efficiency | Recommended Multiplier |
|-----|-----|------------|----------------------|
| Monday | {{currency}} [X] | +20% | 1.2x |
| Saturday | {{currency}} [X] | -30% | 0.7x |

### Pacing Status
- Days remaining: [X]
- Budget remaining: {{currency}} [X]
- Required daily: {{currency}} [X] (current avg: {{currency}} [Y])

### Recommendations
1. Increase [Day] budget by [X]% (best efficiency)
2. Reduce [Day] budget by [X]% (lowest efficiency)
```

**Detailed adds:**
- Full day-of-week performance table by campaign
- Monthly pacing week-by-week breakdown
- Script configuration for automated adjustments
- Seasonal pattern observations
