---
name: skill-022-broad-match-smart-bidding-alignment
description: "Verify that broad match keywords are paired with Smart Bidding strategies."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: keywords
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 022: Broad Match + Smart Bidding Alignment Check

## Purpose

Google recommends using broad match keywords with Smart Bidding because the algorithm can adjust bids in real-time based on conversion likelihood. Broad match without Smart Bidding creates high risk of overpaying for irrelevant queries. This skill identifies misalignments where broad match lacks proper bid optimization.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Campaigns** - Campaign bidding strategy
- **Keywords** - Keyword match types
- **Bidding strategies** - Portfolio bidding strategies
- **Keyword metrics (30 days)** - Performance by match type

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  campaign.bidding_strategy_type,
  ad_group.name,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  metrics.impressions,
  metrics.conversions,
  metrics.cost_micros
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) if you need to analyze performance differences by match type.

## Analysis Steps

1. **Classify campaign bidding strategies:** Smart Bidding (tCPA, tROAS, Max Conv, Max Conv Value) vs Non-Smart (Manual CPC, ECPC, Max Clicks, Target Impression Share)
2. **Inventory match types by campaign:** Count broad, phrase, exact keywords and calculate percentages
3. **Flag misalignments:** Broad + Manual CPC, Smart Bidding + 0% broad, Heavy broad (>50%) + Manual CPC
4. **Assess performance impact:** Compare efficiency (CPA/ROAS) of broad match across bidding strategies

## Thresholds

| Condition | Severity |
|-----------|----------|
| Broad >= 50% AND Manual CPC | Critical |
| Any broad AND Manual CPC | Warning |
| Smart Bidding AND Broad < 20% | Info |
| Smart Bidding AND Broad = 0% | Info |
| ECPC + Broad match | Warning |

## Output

**Short (default):**
```
## Broad Match + Smart Bidding Audit
**Account:** [Name] | **Campaigns:** [X] | **Misalignments:** [Y]

### Critical ([Count])
- **[Campaign]**: [X]% broad match + Manual CPC ([Y] keywords) -> Switch to Smart Bidding or narrow match types

### Warnings ([Count])
- **[Campaign]**: [Issue] -> [Fix]

### Recommendations
1. [Priority action]
```

**Detailed adds:**
- Campaign-level alignment matrix (bidding strategy vs match type %)
- Performance comparison table (broad in Smart Bidding vs Manual)
- Specific keyword counts affected per campaign
