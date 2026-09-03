---
name: skill-128-performance-max-channel-performance
description: "Analyze Performance Max campaign performance with available channel and placement insights."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: waste
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 128: Performance Max Channel Performance

## Purpose

Extract available performance data from Performance Max campaigns including asset group performance, network distribution, and placement insights. Identify optimization opportunities despite PMax's limited visibility.

## Data Requirements

**Data Source:** Custom query required

Performance Max data requires custom queries for asset group and placement insights.

**GAQL Queries:**

Campaign-level:
```sql
SELECT
  campaign.name,
  campaign.id,
  campaign.status,
  campaign_budget.amount_micros,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM campaign
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND segments.date DURING LAST_30_DAYS
```

Asset Group:
```sql
SELECT
  campaign.name,
  asset_group.name,
  asset_group.status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM asset_group
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND segments.date DURING LAST_30_DAYS
ORDER BY metrics.cost_micros DESC
```

Network Distribution:
```sql
SELECT
  campaign.name,
  segments.ad_network_type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM campaign
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND segments.date DURING LAST_30_DAYS
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor.

## Analysis Steps

1. **Identify PMax campaigns:** Locate all Performance Max campaigns in account
2. **Fetch performance data:** Run GAQL queries for campaign, asset group, and network data
3. **Analyze asset groups:** Compare performance across asset groups
4. **Review network distribution:** Assess spend allocation across networks
5. **Compare to standard campaigns:** Benchmark PMax CPA/ROAS against Search/Display

## Thresholds

| Condition | Severity |
|-----------|----------|
| PMax CPA > 50% above Search campaign CPA | Critical |
| Asset group with "Low" strength and high spend | Warning |
| >70% spend on Display network with poor conversions | Warning |
| No first-party audience signals configured | Info |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short format (default):**
```
## Performance Max Audit

**Account:** [Name] | **PMax Campaigns:** [X] | **Issues:** [Y]

### Campaign Overview
| Campaign | Cost | Conv | CPA | ROAS |
|----------|------|------|-----|------|
| [Name] | {{currency}} [X] | [Y] | {{currency}} [Z] | [%] |

### Asset Group Performance
- **[Asset Group]**: [X] conversions, {{currency}} [Y] CPA → Top performer
- **[Asset Group]**: [X] conversions, {{currency}} [Y] CPA → Review assets

### Network Distribution
| Network | Spend % | Conv % | Efficiency |
|---------|---------|--------|------------|
| Search | [X]% | [Y]% | [Good/Poor] |
| Display | [X]% | [Y]% | [Good/Poor] |

### Recommendations
1. Improve [Asset Group] asset strength
2. Review high Display spend with low conversions
```

**Detailed adds:**
- Full asset group breakdown
- Placement insights (where available)
- PMax vs standard campaign comparison
- Audience signal recommendations
