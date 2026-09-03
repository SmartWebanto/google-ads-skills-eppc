---
name: skill-039-bid-strategy-appropriateness-audit
description: "Evaluate whether campaigns are using optimal bidding strategies based on goals, conversion volume, and maturity."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: bidding
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 039: Bid Strategy Appropriateness Audit

## Purpose

Different campaign goals and maturity levels require different bidding strategies. This skill audits whether bidding strategies align with stated goals and if campaigns have sufficient conversion data for Smart Bidding. Common issues: Smart Bidding with insufficient conversions, Manual CPC on high-volume campaigns, Target ROAS on lead gen without revenue data.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Campaigns** - Campaign bidding strategy, type, status
- **Bidding strategies** - Portfolio bidding strategies
- **Campaign metrics (30 days)** - Campaign conversions, spend

**Reference GAQL:**
```sql
SELECT
  campaign.id,
  campaign.name,
  campaign.bidding_strategy_type,
  campaign.target_cpa.target_cpa_micros,
  campaign.target_roas.target_roas,
  metrics.conversions,
  metrics.cost_micros,
  metrics.conversions_value,
  campaign.status
FROM campaign
WHERE segments.date DURING LAST_30_DAYS
  AND campaign.status != 'REMOVED'
```
Run the reference query (API, UI report, or Editor export) for detailed bidding strategy analysis.

## Analysis Steps

1. **Inventory bidding strategies:** Classify as Smart Bidding (tCPA, tROAS, Max Conv, Max Conv Value) vs Non-Smart (Manual, ECPC, Max Clicks, Target IS)
2. **Assess campaign goals:** Determine appropriate strategy based on campaign name, type, conversion tracking
3. **Check conversion volume requirements:** tCPA/tROAS need 30-50+ conv/month, Max Conv needs 15-30+
4. **Identify misalignments:** Smart Bidding with <15 conv/month, Manual CPC with >50 conv/month, Target ROAS without values
5. **Evaluate strategy effectiveness:** CPA trends, conversion volume changes, budget utilization

## Thresholds

| Condition | Severity |
|-----------|----------|
| Smart Bidding + <15 conv/month | Critical |
| Smart Bidding + 15-30 conv/month | Warning |
| Manual CPC + >50 conv/month | Warning |
| Target ROAS + no conversion values | Critical |
| ECPC (any campaign) | Warning (deprecated) |
| Max Clicks + conversion goal | Warning |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Bid Strategy Audit
**Account:** [Name] | **Campaigns:** [X] | **Misalignments:** [Y]

### Critical ([Count])
- **[Campaign]**: Target CPA with [X] conv/month (need 30+) -> Switch to Max Clicks or Manual
- **[Campaign]**: Target ROAS but zero conversion values -> Switch to Target CPA or set values

### Warnings ([Count])
- **[Campaign]**: Manual CPC with [X] conv/month -> Upgrade to Smart Bidding
- **[Campaign]**: ECPC (deprecated) -> Migrate to full Smart Bidding

### Strategy Distribution
| Strategy | Campaigns | Monthly Conv | Status |
|----------|-----------|--------------|--------|
| Target CPA | X | X | OK/Issues |
| Target ROAS | X | X | OK/Issues |
| Manual CPC | X | X | Review |

### Recommendations
1. [Priority action]
```

**Detailed adds:**
- Campaign-by-campaign appropriateness assessment
- Volume requirement analysis
- Recommended migration plan
