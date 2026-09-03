---
name: skill-160-smart-bidding-exploration-configuration
description: "Review Smart Bidding Exploration settings that use flexible ROAS targets to explore new traffic."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-160-smart-bidding-exploration-configuration
  category: platform
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 160: Smart Bidding Exploration Configuration

## Purpose
Audit Smart Bidding Exploration settings to ensure campaigns are leveraging flexible targets to discover new converting audiences. Exploration allows Smart Bidding to temporarily bid on traffic outside strict targets, enabling discovery of new audiences. Campaigns see average 19% increase in conversions from previously untapped segments.

## Data Requirements

**Data Source:** Custom query required

A basic account export shows bid strategies; custom query needed for exploration-specific settings.

**Export data:**
- **Campaigns** - Bid strategy settings
- **Bidding strategies** - Portfolio bid strategy configuration
- **Campaign metrics (30 days)** - Performance data

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  campaign.bidding_strategy_type,
  campaign.target_cpa.target_cpa_micros,
  campaign.target_roas.target_roas,
  metrics.conversions,
  metrics.cost_micros,
  metrics.conversions_value
FROM campaign
WHERE campaign.status = 'ENABLED'
  AND campaign.bidding_strategy_type IN ('TARGET_CPA', 'TARGET_ROAS', 'MAXIMIZE_CONVERSIONS', 'MAXIMIZE_CONVERSION_VALUE')
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) to get exploration configuration status.

## Analysis Steps

1. **Identify Smart Bidding campaigns:** List campaigns using Target CPA, Target ROAS, or Maximize strategies
2. **Check exploration status:** Determine if exploration is enabled and at what intensity
3. **Evaluate readiness:** Verify sufficient conversion volume (50+/month), stable baseline, budget headroom
4. **Analyze exploration performance:** For enabled campaigns, assess exploration ROI
5. **Review portfolio settings:** Check shared exploration configuration across portfolios

## Thresholds

| Condition | Severity |
|-----------|----------|
| Campaign with >100 conv/month, exploration disabled | Critical |
| Exploration enabled but CPA >30% above baseline | Warning |
| Campaign with 50-100 conv/month, exploration disabled | Warning |
| Exploration intensity too aggressive for budget | Warning |
| Campaign with <50 conv/month (exploration not recommended) | Info |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short format (default):**
```
## Smart Bidding Exploration Audit
**Account:** [Name] | **Smart Bidding campaigns:** [X] | **Exploration enabled:** [Y]

### Critical ([Count])
- **[Campaign]**: [X] conv/mo, exploration disabled -> Enable at balanced intensity

### Warnings ([Count])
- **[Campaign]**: Exploration CPA +[X]% above baseline -> Reduce intensity or review

### Exploration Status
| Campaign | Strategy | Conv/Mo | Exploration | Intensity |
|----------|----------|---------|-------------|-----------|
| [Name] | [Type] | X | [On/Off] | [Level] |

### Recommendations
1. Enable exploration on [Campaign] - Expected +15-20% incremental conversions
```

**Detailed adds:**
- Exploration ROI calculation by campaign
- Intensity adjustment recommendations
- Exploration vs. core traffic performance comparison
- New audience segment insights from exploration
