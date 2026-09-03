---
name: skill-057-ad-schedule-optimization
description: "Analyze performance by hour of day and day of week to optimize ad scheduling and bid adjustments."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: targeting
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 057: Ad Schedule (Dayparting) Optimization

## Purpose

Performance varies by time of day and day of week. This skill analyzes hourly and daily performance patterns, identifies high and low converting periods, and recommends schedule adjustments or bid modifications. Note: For Smart Bidding, only complete schedule exclusions are honored.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include time-segmented performance metrics.

**Export data:**
- **Campaigns** - Current ad schedule settings

**GAQL Queries:**

**Hourly Performance:**
```sql
SELECT
  campaign.name,
  campaign.id,
  segments.hour,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM campaign
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 0
```

**Day of Week Performance:**
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
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 0
```
Run via a custom query (API, UI report, or Editor export) with query names `hourly_performance` and `daily_performance`.

## Analysis Steps

1. **Fetch time-segmented performance data:** Run hourly and day-of-week queries, load current ad schedule settings.

2. **Calculate performance metrics:** CVR, CPA, ROAS per time segment. Efficiency Ratio = Conversion Share / Cost Share.

3. **Identify optimization opportunities:** High-value (Efficiency Ratio >1.2), Low-value (<0.8), Exclusion candidates (zero conversions with spend).

4. **Generate schedule recommendations:** Bid increases/decreases for Manual CPC, potential exclusions for all strategies.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Time period with zero conversions + >{{spend_significant}} spend | Critical |
| Efficiency Ratio <0.50 | High |
| Efficiency Ratio >1.50 | High (increase opportunity) |
| Efficiency Ratio 0.50-0.75 | Warning |
| Efficiency Ratio 1.25-1.50 | Warning (increase opportunity) |
| Efficiency Ratio 0.90-1.10 | Info |

## Output

**Short (default):**
```
## Ad Schedule Audit

**Account:** [Name] | **Campaigns Analyzed:** [X]

### High-Performing Periods
- **[Time Period]**: Efficiency [X], CPA {{currency}} [Y] → Increase bid +[Z]%

### Low-Performing Periods
- **[Time Period]**: Efficiency [X], CPA {{currency}} [Y] → Decrease bid -[Z]%

### Recommendations
1. [Priority schedule adjustment]
2. [Secondary adjustment]

Note: Schedule bid adjustments are ignored on Smart Bidding campaigns (only exclusions work).
```

**Detailed adds:**
- Hourly performance summary table (hour, impressions, clicks, cost, conv, CPA, efficiency ratio)
- Day of week performance table (day, impressions, clicks, cost, conv, CPA, efficiency ratio)
- Recommended schedule adjustments tables (bid increases, bid decreases)
- Visual performance heatmap (hour x day with performance indicators)
