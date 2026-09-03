---
name: skill-121-impression-share-loss-analysis
description: "Segment search impression share lost to budget vs ad rank, quantify the opportunity, and route each campaign to a budget or Quality Score fix."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-121-impression-share-lost-analysis
  category: waste
  kind: deterministic
  data_source: custom_gaql
  merged_from: [skill-133-impression-share-loss-analysis]
  related: [skill-135-top-of-page-rate-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 121: Impression Share Loss Analysis

## Purpose

Split impression-share loss into budget-constrained and rank-constrained causes so optimization effort targets the right root cause. Budget loss on a profitable campaign is missed conversions; rank loss points to Quality Score or bids, not budget. Quantify the opportunity per campaign before recommending spend.

## Data Requirements

**Data Source:** Custom GAQL Required

The standard export does not include competitive impression share metrics.

**GAQL Query:**
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
  metrics.search_impression_share,
  metrics.search_budget_lost_impression_share,
  metrics.search_rank_lost_impression_share,
  metrics.search_top_impression_share,
  metrics.search_absolute_top_impression_share
FROM campaign
WHERE campaign.status = 'ENABLED'
  AND campaign.advertising_channel_type = 'SEARCH'
  AND segments.date DURING LAST_30_DAYS
```
Run via `/google-ads:get-custom` with query name `impression_share_loss`.

## Analysis Steps

1. **Fetch impression share data:** Run the GAQL query for search campaigns (IS, budget-lost IS, rank-lost IS, top/absolute-top IS)
2. **Categorize campaigns:** Budget-constrained (budget lost >10%), rank-constrained (rank lost >20%), both (>15% each), or optimized
3. **Calculate opportunity cost:** Missed impressions, clicks and conversions from lost IS using each campaign's CTR and conversion rate
4. **Diagnose root causes:** Budget loss → check exhaustion time and profitability (conversions >= {{min_conversions}}); rank loss → check Quality Score components
5. **Prioritize recommendations:** Rank fixes first (cheaper), then budget increases on profitable campaigns, ordered by recovery value

## Thresholds

| Condition | Severity |
|-----------|----------|
| Budget Lost IS > 20% on profitable campaign | Critical |
| Rank Lost IS > 30% | Critical |
| Budget and rank lost > 15% each | Warning |
| Budget Lost IS > 10% | Warning |
| Rank Lost IS > 20% | Warning |
| Any IS loss 5-10% | Info |

Sample size: judge impression share only above {{min_impressions}} impressions in the period.

## Output

**Short format (default):**
```
## Impression Share Loss Audit

**Account:** [Name] | **Campaigns:** [X] | **Issues:** [Y]

### Critical ([Count])
- **[Campaign]**: [X]% lost to budget, profitable CPA $[Y] → Increase budget by $[Z]/day
- **[Campaign]**: [X]% lost to rank, avg QS [Y] → Improve landing page experience

### Warnings ([Count])
- **[Campaign]**: [X]% lost to [cause] → [Fix]

### Recommendations
1. Increase budget on [campaigns] to capture $[X] in missed conversions
2. Address QS issues on [campaigns] losing [X]% to rank
```

**Detailed adds:**
- Loss summary by cause (budget / rank / both / optimized) with campaign counts and average loss
- Campaign-by-campaign IS breakdown table
- Opportunity cost calculations (missed impressions, clicks, conversions)
- Root cause analysis for rank-constrained campaigns
- Budget reallocation suggestions between campaigns
