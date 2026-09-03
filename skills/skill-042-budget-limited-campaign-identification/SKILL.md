---
name: skill-042-budget-limited-campaign-identification
description: "Find campaigns showing \"Limited by budget\" status and quantify missed opportunity from budget constraints."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: bidding
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 042: Budget-Limited Campaign Identification

## Purpose

Budget-limited campaigns leave conversions and revenue on the table. This skill identifies campaigns with active budget constraints, quantifies lost impression share and estimated missed conversions, and finds reallocation opportunities from underperforming campaigns.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include impression share metrics or campaign primary status.

**Export data:**
- **Campaigns** - Campaign settings, budget, bidding
- **Campaign metrics (30 days)** - Spend, conversions

**GAQL Query:**
```sql
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  campaign_budget.amount_micros,
  campaign_budget.explicitly_shared,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.search_impression_share,
  metrics.search_budget_lost_impression_share,
  metrics.search_rank_lost_impression_share,
  campaign.primary_status,
  campaign.primary_status_reasons
FROM campaign
WHERE campaign.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `budget_limited_campaigns`.

## Analysis Steps

1. **Identify budget-limited campaigns:** Check for primary status = "LIMITED", Budget Lost IS% > 0%, or daily spend consistently at budget.

2. **Quantify budget impact:** Calculate lost impressions, estimate lost conversions (Lost Impressions * CTR * Conv Rate), estimate lost revenue.

3. **Assess campaign performance:** Determine if CPA/ROAS is within target and if budget increase is warranted.

4. **Find reallocation sources:** Identify underperforming campaigns not spending full budget, poor CPA/ROAS, or low conversion volume.

5. **Calculate budget recommendations:** Determine recommended daily budget, expected additional conversions, and projected efficiency at new budget.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Budget Lost IS >20% + CPA below target | Critical |
| Spending 100% budget + strong ROAS | Critical |
| Budget Lost IS >20% + CPA at/above target | High |
| Shared budget limiting multiple campaigns | High |
| Budget Lost IS 10-20% | Warning |
| Budget Lost IS 5-10% | Info |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Budget-Limited Campaign Audit

**Account:** [Name] | **Campaigns Analyzed:** [X] | **Budget-Limited:** [Y]

### Critical ([Count])
- **[Campaign]**: [X]% Budget Lost IS, CPA {{currency}} [Y] (below target) → Increase budget to {{currency}} [Z]/day

### Warnings ([Count])
- **[Campaign]**: [X]% Budget Lost IS, CPA at target → Evaluate efficiency before increase

### Recommendations
1. [Priority action with estimated conversions gained]
2. [Reallocation opportunity]
```

**Detailed adds:**
- Budget-limited campaigns table with budget, spend, Budget Lost IS%, conv, CPA, status
- Lost opportunity analysis with estimated lost impressions, clicks, conversions, revenue
- Budget reallocation opportunities (from/to campaigns)
- Budget increase recommendations with projected impact
