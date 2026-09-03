---
name: skill-046-portfolio-bid-strategy-evaluation
description: "Assess whether campaigns grouped under portfolio bidding strategies are appropriately matched for optimal performance."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: bidding
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 046: Portfolio Bid Strategy Evaluation

## Purpose

Portfolio bidding strategies share learnings across campaigns, but poorly matched portfolios can average out performance patterns, constrain high performers, and reduce overall efficiency. This skill evaluates whether campaigns in a portfolio are logically grouped, identifies performance disparity, and recommends restructuring.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Bidding strategies** - Portfolio strategies and linked campaigns
- **Campaigns** - Campaign settings and bidding
- **Campaign metrics (30 days)** - Campaign performance

**Reference GAQL:**
```sql
SELECT
  campaign.id,
  campaign.name,
  bidding_strategy.id,
  bidding_strategy.name,
  bidding_strategy.type,
  bidding_strategy.target_cpa.target_cpa_micros,
  bidding_strategy.target_roas.target_roas,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM campaign
WHERE campaign.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) if you need portfolio-specific metrics.

## Analysis Steps

1. **Inventory portfolio strategies:** Strategy name/type, target settings, number of campaigns, total spend/conversions.

2. **Analyze intra-portfolio performance:** Calculate individual CPA/ROAS, variance from portfolio average, conversion volume contribution, spend distribution.

3. **Identify portfolio issues:** Performance disparity (CPA/ROAS range, coefficient of variation >0.40), volume imbalance (one campaign >60% of conversions), logical grouping issues.

4. **Assess optimization impact:** Determine if targets are appropriate for all campaigns, if one campaign dominates optimization.

5. **Develop restructuring recommendations:** Break portfolio, remove outliers, create new portfolios by criteria, convert to inline strategies.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Campaigns with different goals in same portfolio | Critical |
| Coefficient of variation >0.40 | Critical |
| Single campaign >60% of portfolio volume | High |
| Campaign CPA/ROAS >50% off target | High |
| CV 0.25-0.40 | Warning |
| Portfolio <30 conv/month total | Warning |
| Campaign <10 conv/month in large portfolio | Info |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Portfolio Bid Strategy Audit

**Account:** [Name] | **Portfolios:** [X] | **Issues Found:** [Y]

### Critical ([Count])
- **[Portfolio]**: CV [X], CPA range {{currency}} [Y]-{{currency}} [Z] → Split into [N] portfolios by tier

### Warnings ([Count])
- **[Portfolio]**: [Campaign] dominates ([X]% of volume) → Consider separation

### Recommendations
1. [Priority restructuring action]
2. [Secondary action]
```

**Detailed adds:**
- Portfolio strategy overview table (portfolio, type, target, campaigns, spend, conv, CPA/ROAS, status)
- Intra-portfolio performance analysis per portfolio (campaign, spend, conv, CPA/ROAS, vs target, vs avg)
- Portfolio health assessment (CV score, volume balance, logical grouping, overall health)
- Restructuring recommendations with proposed new portfolio structure
