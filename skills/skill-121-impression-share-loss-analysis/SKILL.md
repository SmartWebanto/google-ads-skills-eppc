---
name: skill-121-impression-share-loss-analysis
description: "Segment search impression share lost to budget vs ad rank, quantify the opportunity, and route each campaign to a budget or Quality Score fix."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: waste
  kind: deterministic
  data_source: custom_query
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

**Data Source:** Custom query required

A basic account export does not include competitive impression share metrics.

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
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `impression_share_loss`.

## Analysis Steps

1. **Fetch impression share data:** Run the GAQL query for search campaigns (IS, budget-lost IS, rank-lost IS, top/absolute-top IS)
2. **Categorize campaigns:** Budget-constrained (budget lost >10%), rank-constrained (rank lost >20%), both (>15% each), or optimized
3. **Calculate opportunity cost:** Missed impressions, clicks and conversions from lost IS using each campaign's CTR and conversion rate
4. **Diagnose root causes:** Budget loss → confirm the campaign spends its full daily budget (30-day cost ≈ daily budget × days) and is profitable; rank loss → check Quality Score components and bid headroom
5. **Prioritize recommendations:** Rank fixes first (cheaper), then budget increases on profitable campaigns, ordered by recovery value

## Thresholds

| Condition | Severity |
|-----------|----------|
| Budget Lost IS > 20% on profitable campaign | Critical |
| Rank Lost IS > 30% | Critical |
| Budget and rank lost > 15% each | Warning |
| Budget Lost IS > 10% | Warning |
| Rank Lost IS > 20% | Warning |
| Any IS loss between 5% and 10% (inclusive) | Info |

Profitable: conversions >= {{min_conversions}} and CPA at or below the campaign's target CPA (or ROAS at or above target ROAS); without a target, conversions >= {{min_conversions}}.

Sample size: judge impression share only above {{min_impressions}} impressions in the period.

## Output

**Short format (default):**
```
## Impression Share Loss Audit

**Account:** [Name] | **Campaigns:** [X] | **Issues:** [Y]

### Critical ([Count])
- **[Campaign]**: [X]% lost to budget, profitable CPA {{currency}} [Y] → Increase budget by {{currency}} [Z]/day
- **[Campaign]**: [X]% lost to rank, avg QS [Y] → Improve landing page experience

### Warnings ([Count])
- **[Campaign]**: [X]% lost to [cause] → [Fix]

### Recommendations
1. Increase budget on [campaigns] to capture {{currency}} [X] in missed conversions
2. Address QS issues on [campaigns] losing [X]% to rank
```

**Detailed adds:**
- Loss summary by cause (budget / rank / both / optimized) with campaign counts and average loss
- Campaign-by-campaign IS breakdown table
- Opportunity cost calculations (missed impressions, clicks, conversions)
- Root cause analysis for rank-constrained campaigns
- Budget reallocation suggestions between campaigns
