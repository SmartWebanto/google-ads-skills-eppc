---
name: skill-110-conversion-tracking-breakage
description: "Detect conversion tag firing drops below expected thresholds indicating tracking breakage."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: remarketing
  kind: deterministic
  data_source: custom_query
  related: [skill-070-conversion-tracking-completeness, skill-071-conversion-tracking-accuracy, skill-081-micro-conversion-tracking, skill-107-conversion-value-accuracy, skill-108-cross-device-conversion-tracking]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 110: Conversion Tracking Breakage Detection

## Purpose
Detect when conversion tracking breaks or degrades. Even brief outages feed incorrect data to Smart Bidding, causing persistent optimization damage that takes weeks to recover.

## Data Requirements

**Data Source:** Custom query required

**Export data:**
- **Campaign metrics (30 days)** - Daily conversion trends

**Reference GAQL - Daily traffic vs conversions:**
```sql
SELECT
  segments.date,
  metrics.conversions,
  metrics.clicks
FROM campaign
WHERE segments.date DURING LAST_14_DAYS
```

**Reference GAQL - Conversions by action:**
```sql
SELECT
  segments.date,
  segments.conversion_action_name,
  metrics.conversions
FROM campaign
WHERE segments.date DURING LAST_14_DAYS
```
Run the reference query (API, UI report, or Editor export) for detailed daily breakdown.

## Analysis Steps

1. **Establish Baselines:** Calculate daily/weekly conversion averages and standard deviation
2. **Identify Anomalies:** Find sudden drops (>50% day-over-day), zero-conversion periods
3. **Cross-Reference Traffic:** Compare clicks trend to conversions - stable clicks + dropped conversions = breakage
4. **Analyze by Conversion Action:** Identify which specific actions are affected

## Thresholds

| Condition | Severity |
|-----------|----------|
| Zero conversions for 24+ hours (with normal traffic) | Critical |
| Conversion drop >50% day-over-day | Critical |
| Conversion rate drops while traffic stable | Warning |
| Specific conversion action goes silent | Warning |

Sample size: judge CTR rows only above {{min_impressions}} impressions, conversion-rate rows only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Conversion Tracking Health Check
**Account:** [name] | **Baseline Conv/Day:** [X] | **Status:** [Healthy/Alert]

### Critical
- **Zero conversions on [date]** - Tracking likely broken
- **[X]% drop on [date]** - Investigate immediately

### Warnings
- **[conversion action] silent for [X] hours** - Check tag implementation

### Recommendations
1. Verify conversion tag in Google Tag Assistant
2. Check for recent website/GTM changes
3. Apply data exclusion for [date range] if breakage confirmed
```

**Detailed adds:**
- Daily conversion trend table with anomaly flags
- Conversion action health by action
- Recovery procedure checklist
- Smart Bidding recovery timeline estimates
