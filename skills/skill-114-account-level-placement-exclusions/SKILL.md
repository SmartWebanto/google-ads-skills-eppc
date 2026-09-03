---
name: skill-114-account-level-placement-exclusions
description: "Block low-quality websites, apps, and YouTube channels at the account level to prevent wasted spend."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: waste
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 114: Account-Level Placement Exclusions

## Purpose
Block low-quality websites, apps, and YouTube channels at the account level to prevent wasted spend on Display and Video campaigns. Universal exclusions protect all campaigns automatically.

## Data Requirements

**Data Source:** Custom query required

**GAQL Query:**
```sql
SELECT
  detail_placement_view.display_name,
  detail_placement_view.placement,
  detail_placement_view.placement_type,
  campaign.name,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM detail_placement_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 0
ORDER BY metrics.cost_micros DESC
LIMIT 500
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `placement_performance`.

**Export data:**
- **Campaigns** - Identify Display/Video/PMax campaigns

## Analysis Steps

1. **Identify Display/Video Campaigns:** Find campaigns eligible for placement exclusions
2. **Review Current Exclusions:** Check for existing account/campaign-level exclusions
3. **Identify Recommended Exclusions:** Mobile app categories, low-quality sites, kids content
4. **Analyze Placement Performance:** Find high-spend zero-conversion placements

## Thresholds

| Condition | Severity |
|-----------|----------|
| No account-level placement exclusions | Critical |
| Mobile app placements with zero conversions | Warning |
| High-spend zero-conversion placements | Warning |
| No content category exclusions | Info |

## Output

**Short (default):**
```
## Placement Exclusion Audit
**Account:** [name] | **Display/Video Campaigns:** [count] | **Exclusions:** [count]

### Critical
- **No account-level exclusions** - Add universal placement exclusions

### Warnings
- **Mobile app placements wasting {{currency}} [amount]** - Exclude adsenseformobileapps.com
- **[count] zero-conversion placements** - Add to exclusion list

### Recommendations
1. Add account-level exclusion for all mobile apps (if appropriate)
2. Exclude game and children's app categories
3. Block [count] specific zero-conversion placements
```

**Detailed adds:**
- Display/Video campaign inventory
- Recommended universal exclusions by category
- High-spend zero-conversion placement list
- Content category exclusion recommendations
