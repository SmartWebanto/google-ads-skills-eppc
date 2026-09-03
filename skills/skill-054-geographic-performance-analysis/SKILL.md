---
name: skill-054-geographic-performance-analysis
description: "Analyze performance by location, recommend bid adjustments for strong and weak areas, and quantify exclusion candidates with zero or very poor conversion."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: targeting
  kind: deterministic
  data_source: custom_query
  merged_from: [skill-055-underperforming-location-exclusion]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 054: Geographic Performance Analysis

## Purpose

Geographic performance varies widely. Compare each location to the account average, propose bid adjustments where volume supports it, and exclude locations that spend without converting or sit outside the service area. Quantify waste and projected savings so exclusions are defensible.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include location-segmented performance metrics.

**Export data:**
- **Bid adjustments (campaign level)** - Current location bid modifiers

**GAQL Query:**
```sql
SELECT
  campaign.name,
  geographic_view.country_criterion_id,
  geographic_view.location_type,
  segments.geo_target_region,
  segments.geo_target_metro,
  segments.geo_target_city,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM geographic_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 0
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `geographic_performance`.
For the exclusion pass, filter to `metrics.cost_micros > 0` and load current exclusions from `bid_adjustments.md`.

## Analysis Steps

1. **Fetch location performance:** Custom GAQL plus current bid modifiers and exclusions
2. **Compute per-location metrics:** CPA, conversion rate, ROAS, cost share, conversion share vs account average
3. **Bid increases:** CPA well below average with >= {{min_conversions}} conversions
4. **Bid decreases:** CPA well above average with >= {{min_clicks}} clicks
5. **Exclusions:** Zero conversions above the spend floor, CPA > 3x average, CVR < 0.5x average with >= {{min_clicks}} clicks, outside the service area
6. **Quantify and prioritize:** 30-day waste, projected annual savings, high/medium/low priority

## Thresholds

| Condition | Severity |
|-----------|----------|
| Location outside service area with any spend | Critical (exclude) |
| Zero conversions with Cost > {{spend_significant}} | Critical (exclude) |
| CPA 40%+ below average with >= {{min_conversions}} conversions | Critical (increase bid) |
| CPA > 3x account average with >= {{min_clicks}} clicks | High (exclude) |
| Zero conversions with Cost {{spend_floor}} to {{spend_significant}} | High (exclude) |
| CPA 50%+ above average | High (decrease bid) |
| CPA 20-40% below or 30-50% above average | Warning (moderate adjustment) |
| CVR < 0.5x average with >= {{min_clicks}} clicks | Warning |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Geographic Performance Audit

**Account:** [Name] | **Locations Analyzed:** [X] | **Optimization Opportunities:** [Y]
**Current Waste:** {{currency}} [X]/month | **Projected Annual Savings:** {{currency}} [Y]

### Bid Increases ([Count])
- **[Location]**: CPA {{currency}} [X] ([Y]% below avg), [Z] conv → Increase to +[%]

### Bid Decreases ([Count])
- **[Location]**: CPA {{currency}} [X] ([Y]% above avg) → Decrease to -[%]

### Exclusion Candidates ([Count])
- **[Location]**: {{currency}} [X] spend, 0 conversions → Exclude

### Recommendations
1. [Priority adjustment]
2. [Secondary adjustment]
```

**Detailed adds:**
- Account performance baseline table (total conversions, average CPA, average ROAS)
- Top performing locations table (location, conversions, CPA, vs avg, current adj, recommended)
- Underperforming locations table (location, cost, conversions, CPA, vs avg, current adj, recommended)
- Exclusion recommendations table (location, cost, conversions, reason)
- Low priority review table (borderline cases to monitor)
