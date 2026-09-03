---
name: skill-045-budget-allocation-optimization
description: "Reallocate budget from low-performing campaigns to high-performing campaigns to maximize overall account ROI."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-045-budget-allocation-optimization
  category: bidding
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 045: Budget Allocation Optimization

## Purpose

Not all campaigns deliver equal value. This skill analyzes campaign efficiency, identifies budget misallocations, and provides data-driven reallocation recommendations to maximize conversions and revenue within a fixed overall budget.

## Data Requirements

**Data Source:** Custom query required

A basic account export lacks impression share metrics needed to identify scale opportunities.

**Export data:**
- **Campaigns** - Current budgets, bidding strategies
- **Campaign metrics (30 days)** - All performance metrics

**GAQL Query:**
```sql
SELECT
  campaign.id,
  campaign.name,
  campaign_budget.amount_micros,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.clicks,
  metrics.impressions,
  metrics.search_budget_lost_impression_share,
  campaign.status
FROM campaign
WHERE campaign.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `budget_allocation`.

## Analysis Steps

1. **Calculate performance metrics:** CPA, ROAS, Conversion Rate, Budget Utilization per campaign.

2. **Rank campaigns by efficiency:** For CPA-focused: rank by CPA (lowest = best). For ROAS-focused: rank by ROAS (highest = best). Weight by conversion volume.

3. **Identify budget misallocations:** Underfunded = top efficiency quartile + budget-limited. Overfunded = bottom quartile + not budget-limited.

4. **Calculate reallocation scenarios:** Conservative (10-15%), Moderate (20-30%), Aggressive (40-50%).

5. **Project impact:** Estimate additional conversions from increased budgets, lost conversions from decreased, net change, blended CPA/ROAS.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Top 25% efficiency + budget limited | Critical |
| >30% of budget in bottom 25% efficiency | Critical |
| Bottom 25% efficiency + >{{monthly_spend_significant}} spend | High |
| Campaign CPA >2x account average | High |
| ROAS <50% of account average | High |
| Budget utilization <60% + poor metrics | High |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Budget Allocation Audit

**Account:** [Name] | **Total Budget:** {{currency}} [X]/day | **Reallocation Opportunity:** {{currency}} [Y]/day

### Critical ([Count])
- **[Campaign]**: [X]% of budget, [Y]% of conversions, CPA {{currency}} [Z] → Reduce budget by [%]
- **[Campaign]**: Best CPA, budget-limited → Increase budget by [%]

### Recommendations
1. Reallocate {{currency}} [X]/day from [Campaign A] to [Campaign B]
2. [Secondary reallocation]
```

**Detailed adds:**
- Campaign efficiency ranking table (rank, spend, conv, CPA, ROAS, budget util, efficiency tier)
- Current allocation vs performance table (% of budget, % of conversions, % of revenue, status)
- Reallocation recommendations table (current budget, recommended, change %, reasoning)
- Projected impact table (scenario, budget change, projected +conv, projected +rev, new CPA/ROAS)
