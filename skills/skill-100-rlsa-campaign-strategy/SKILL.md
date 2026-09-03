---
name: skill-100-rlsa-campaign-strategy
description: "Audit Remarketing Lists for Search Ads (RLSA) campaigns for proper audience targeting and bid adjustments."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-100-rlsa-campaign-strategy
  category: remarketing
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 100: RLSA Campaign Strategy

## Purpose
Audit RLSA implementation in Search campaigns. Returning visitors convert at 2-3x the rate of new visitors, enabling broader keywords with controlled risk through audience-based bid adjustments.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Campaigns** - Campaign types
- **Audiences (campaign level)** - Audience targeting mode
- **Audiences (ad group level)** - Ad group audiences
- **Bid adjustments (campaign level)** - Bid modifiers

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_criterion.user_list.user_list,
  ad_group_criterion.bid_modifier,
  ad_group_criterion.type
FROM ad_group_audience_view
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) for performance by audience segment.

## Analysis Steps

1. **Inventory RLSA Usage:** Identify Search campaigns with audience targeting
2. **Classify Audience Mode:** Observation (bid only) vs. Targeting (RLSA-only)
3. **Evaluate Coverage:** Check if all Search campaigns have audiences applied
4. **Assess Bid Adjustments:** Verify meaningful adjustments by audience value

## Thresholds

| Condition | Severity |
|-----------|----------|
| No audiences on any Search campaign | Critical |
| Search campaigns without any RLSA | Warning |
| Audiences applied but no bid adjustments | Warning |
| Negative bid adjustments on high-value audiences | Warning |
| No dedicated RLSA campaigns for broad capture | Info |

## Output

**Short (default):**
```
## RLSA Campaign Strategy Audit
**Account:** [name] | **Search Campaigns:** [count] | **With RLSA:** [count] | **Issues:** [count]

### Critical
- **[count] Search campaigns have no audience targeting** - Add observation audiences

### Warnings
- **Audiences applied without bid adjustments** - Add +20-50% for high-intent
- **Cart abandoners at +0%** - Increase to +30-40%

### Recommendations
1. Add all website visitors (observation) to all Search campaigns
2. Apply +30% adjustment for cart abandoners
3. Consider dedicated RLSA campaign for broader keywords
```

**Detailed adds:**
- RLSA coverage matrix by campaign
- Bid adjustment table by audience type
- Recommended bid adjustment structure
- RLSA-only campaign opportunities
