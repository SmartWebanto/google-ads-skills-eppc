---
name: skill-092-pmax-final-url-expansion-control
description: "Audit Performance Max Final URL Expansion settings to ensure appropriate control over landing page selection."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: shopping_pmax
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 092: Performance Max Final URL Expansion Control

## Purpose
Audit Performance Max Final URL Expansion settings to ensure appropriate control over landing page selection. URL expansion allows Google to dynamically select landing pages, which can be beneficial or problematic depending on business goals and website structure.

## Data Requirements

**Data Source:** Custom query required

**Export data:**
- **Campaigns** — The `Asset Automation Settings` field shows opt-in/opt-out status per automation type. Check for `FinalUrlExpansionTextAssetAutomation` to determine URL expansion status. If not listed, defaults apply (opted in).

**GAQL Query - Asset Group Final URLs:**
```sql
SELECT
  campaign.name,
  asset_group.name,
  asset_group.final_urls,
  asset_group.final_mobile_urls,
  asset_group.status
FROM asset_group
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
```

**GAQL Query - Landing Page Performance:**
```sql
SELECT
  campaign.name,
  campaign.advertising_channel_type,
  landing_page_view.unexpanded_final_url,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM landing_page_view
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND segments.date DURING LAST_30_DAYS
ORDER BY metrics.clicks DESC
LIMIT 100
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `pmax_url_expansion`.

## Analysis Steps

1. **Check URL Expansion Status:** Read `Asset Automation Settings` from `campaign.md` for each PMax campaign. Look for `FinalUrlExpansionTextAssetAutomation: OptedOut`. If absent, URL expansion is enabled (default)
2. **Analyze Landing Page Distribution:** Compare intended URLs vs. actual URLs receiving traffic
3. **Assess URL Quality:** Identify non-commercial pages, outdated content, policy-risk pages
4. **Evaluate Business Impact:** Calculate conversion rate by landing page; identify wasted spend

## Thresholds

| Condition | Severity |
|-----------|----------|
| Non-commercial pages receiving traffic | Critical |
| >20% spend on expanded URLs with low conversion | Warning |
| Zero-conversion expanded URLs with >{{spend_significant}} spend | Warning |
| URL expansion ON with no exclusion rules | Info |

## Output

**Short (default):**
```
## PMax URL Expansion Audit
**Account:** [name] | **URL Expansion:** [On/Off] | **Exclusion Rules:** [count] | **Issues:** [count]

### Critical
- **Non-commercial pages receiving traffic**: /careers ({{currency}} [amount]), /about ({{currency}} [amount])

### Warnings
- **[count] expanded URLs with zero conversions** - {{currency}} [amount] wasted
- **No exclusion rules configured** - Add patterns for /blog, /careers, /terms

### Recommendations
1. Add exclusions: /careers, /blog, /about, /terms, /privacy
2. Exclude [count] zero-conversion expanded URLs
3. Estimated monthly savings: {{currency}} [amount]
```

**Detailed adds:**
- Landing page distribution table (intended vs. expanded)
- Problematic URLs list with spend and conversion data
- Recommended exclusion patterns
- Performance comparison: intended vs. expanded URLs
