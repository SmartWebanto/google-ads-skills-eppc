---
name: skill-151-product-feed-seasonal-keyword-optimization
description: "Update Shopping/PMax product titles with seasonal keywords before peak periods."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-151-product-feed-seasonal-keyword-optimization
  category: seasonal
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 151: Product Feed Seasonal Keyword Optimization

## Purpose
Identify opportunities to add seasonal keywords to product titles for Shopping and Performance Max campaigns. Product titles are the primary relevance factor in Shopping ads - incorporating seasonal search terms (e.g., "christmas gift," "black friday deal") improves visibility during high-demand windows.

## Data Requirements

**Data Source:** External (beyond Google Ads data)

**Export data:**
- **Campaigns** - Identify Shopping/PMax campaigns
- **Search terms (30 days)** - Seasonal query patterns

**Reference GAQL (Shopping Search Terms):**
```sql
SELECT
  campaign.name,
  campaign.status,
  segments.product_title,
  metrics.impressions,
  metrics.clicks,
  metrics.conversions
FROM shopping_performance_view
WHERE campaign.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 100
```
Run the reference query (API, UI report, or Editor export) to identify seasonal search patterns in Shopping campaigns.

**Note:** Actual feed changes must be made in Google Merchant Center, not Google Ads.

## Analysis Steps

1. **Identify Shopping/PMax campaigns:** Check campaign types in the export
2. **Map seasonal opportunities:** List upcoming events and relevant seasonal modifiers
3. **Analyze search queries:** Review search terms for seasonal patterns driving traffic
4. **Identify title gaps:** Find products without seasonal keywords that match seasonal queries
5. **Plan implementation timeline:** Schedule title updates 2-3 weeks before peak

## Thresholds

| Condition | Severity |
|-----------|----------|
| Major event within 3 weeks, no seasonal title optimization planned | Critical |
| High-volume seasonal queries not reflected in product titles | Warning |
| Products in gift-relevant categories without "gift" modifiers during Q4 | Warning |
| Prior seasonal titles not reverted post-event | Warning |
| Product categories with low seasonal relevance being modified | Info |

## Output

**Short format (default):**
```
## Product Feed Seasonal Audit
**Account:** [Name] | **Shopping/PMax campaigns:** [X] | **Optimization opportunities:** [Y]

### Critical ([Count])
- **[Event]**: [X] products in [category] lack seasonal titles -> Add "[modifier]" prefix

### Warnings ([Count])
- **[Query]**: [X] searches, products don't match -> Update titles with "[keyword]"

### Recommendations
1. [Category] products: Add "[seasonal keyword]" prefix by [date]
   - Implementation: Supplemental feed or feed rule in Merchant Center
```

**Detailed adds:**
- Product category to seasonal modifier mapping
- Supplemental feed or feed rule implementation instructions
- Title update and reversion schedule by event
