---
name: skill-029-rsa-asset-performance-analysis
description: "Rate RSA headlines and descriptions account-wide using Google's asset performance labels and ad-level metrics; replace Low assets with patterns from Best ones."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-029-rsa-asset-performance-analysis
  category: creative
  kind: deterministic
  data_source: custom_query
  merged_from: [skill-126-rsa-asset-performance-bulk-analysis]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 029: RSA Asset Performance Analysis

## Purpose

Google labels each RSA asset Best, Good, Low, or Learning. Aggregate labels and ad-level performance across the account to find assets to replace, patterns to replicate, and ads whose strength or pinning limits combinations.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include asset-level performance ratings.

**Export data:**
- **Ads** - RSA headlines, descriptions, ad strength

**GAQL Query:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_ad.ad.id,
  ad_group_ad_asset_view.field_type,
  ad_group_ad_asset_view.performance_label,
  asset.text_asset.text,
  asset.type,
  metrics.impressions,
  metrics.clicks
FROM ad_group_ad_asset_view
WHERE ad_group_ad.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
ORDER BY ad_group_ad_asset_view.performance_label DESC
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `asset_performance`.

**GAQL Query (ad-level metrics):**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_ad.ad.responsive_search_ad.headlines,
  ad_group_ad.ad.responsive_search_ad.descriptions,
  ad_group_ad.policy_summary.approval_status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM ad_group_ad
WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
  AND ad_group_ad.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
ORDER BY metrics.impressions DESC
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `rsa_ad_performance`.

## Analysis Steps

1. **Fetch asset labels and ad metrics:** Asset view for labels; ad_group_ad for RSA-level impressions, CTR, conversions, ad strength
2. **Categorize assets by label:** Best (replicate), Good (keep), Low (replace), Learning (wait), Unrated
3. **Aggregate across ads:** Assets reused in many ads; account-wide top and bottom performers
4. **Analyze patterns:** What Best assets share (benefit, CTA, length) that Low assets lack
5. **Flag ads:** Poor strength with spend, multiple Low assets, no Best headline, heavy pinning
6. **Generate replacements:** Based on Best patterns, keeping headline diversity

## Thresholds

| Condition | Severity |
|-----------|----------|
| > 20% of assets rated Low | Critical |
| Low asset in a campaign above {{spend_significant}}/30d | Critical |
| Ad strength Poor with spend above {{spend_significant}}/30d | Critical |
| Multiple Low assets in one ad | Warning |
| Any asset rated Low | Warning |
| No Best-rated headline in an RSA | Warning |
| Heavy pinning (3+ pins) reducing combinations | Info |
| All assets Learning (new RSA, < {{min_impressions}} impressions) | Info |

## Output

**Short (default):**
```
## RSA Asset Performance Audit
**Account:** [Name] | **Assets:** [X] | **Low-rated:** [Y]%

### Replace (Low-rated) ([Count])
- **[Campaign] / [Ad Group]**: "[Low asset text]" -> Suggested: "[replacement based on Best patterns]"

### Top Performers to Replicate
- "[Best asset text]" - [X] campaigns, [Y]% CTR

### Summary
| Rating | Headlines | Descriptions |
|--------|-----------|--------------|
| Best | X | X |
| Good | X | X |
| Low | X | X |
| Learning | X | X |

### Recommendations
1. [Priority replacement action]
```

**Detailed adds:**
- Full table of Low assets with replacement suggestions
- Pattern analysis (what Best assets have that Low assets lack)
- Campaign priority based on spend
- Ad strength distribution and top-performing headlines account-wide
- Pinning strategy assessment
