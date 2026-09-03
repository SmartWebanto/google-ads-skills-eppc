---
name: skill-116-mobile-app-placement-exclusion
description: "Exclude mobile app placements, particularly games and children's apps, which typically generate accidental clicks."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-116-mobile-app-placement-exclusion
  category: waste
  kind: deterministic
  data_source: custom_gaql
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 116: Mobile App Placement Exclusion

## Purpose
Exclude mobile app placements, particularly games and children's apps, which typically generate accidental clicks and low-quality traffic with near-zero conversion rates.

## Data Requirements

**Data Source:** Custom GAQL Required

**GAQL Query:**
```sql
SELECT
  detail_placement_view.display_name,
  detail_placement_view.placement,
  detail_placement_view.placement_type,
  detail_placement_view.target_url,
  campaign.name,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.ctr
FROM detail_placement_view
WHERE segments.date DURING LAST_30_DAYS
  AND detail_placement_view.placement_type = 'MOBILE_APPLICATION'
ORDER BY metrics.cost_micros DESC
LIMIT 500
```
Run via `/google-ads:get-custom` with query name `mobile_app_placements`.

**Standard Data:**
- `data/account/campaigns/*/campaign.md` - Identify Display/Video campaigns

## Analysis Steps

1. **Identify Campaigns with App Exposure:** Find Display, Discovery, PMax, Video campaigns
2. **Pull App Placement Data:** Get all mobile app placements and performance
3. **Analyze App Performance:** Compare conversion rates: apps vs. websites
4. **Identify High-Risk Apps:** Games, children's apps, utility apps with high CTR

## Thresholds

| Condition | Severity |
|-----------|----------|
| >{{spend_high}}/month on mobile apps with <1% conversion rate | Critical |
| Game apps with zero conversions | Warning |
| App CTR >3% (likely accidental clicks) | Warning |
| No app exclusions configured | Info |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Mobile App Placement Analysis
**Account:** [name] | **App Spend:** {{currency}} [amount] | **App Conversion Rate:** [%]

### Performance Comparison
| Placement Type | Spend | Conv Rate | CPA |
|----------------|-------|-----------|-----|
| Websites | {{currency}} [amount] | [%] | {{currency}} [amount] |
| Mobile Apps | {{currency}} [amount] | [%] | {{currency}} [amount] |

### Critical
- **Mobile apps underperforming by [X]%** - Consider full exclusion

### Recommendations
1. **Option A:** Exclude all mobile apps - Save {{currency}} [amount]/month
2. **Option B:** Exclude game and children's app categories
3. **Option C:** Exclude specific zero-conversion apps

### High-Risk Apps to Exclude
| App | Category | Spend | Conv | CTR |
|-----|----------|-------|------|-----|
| [name] | Game | {{currency}} [amount] | 0 | [%] |
```

**Detailed adds:**
- Full app placement inventory with performance
- Category-level analysis
- Implementation methods (account vs. campaign level)
- Estimated impact by exclusion option
