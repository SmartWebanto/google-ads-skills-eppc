---
name: skill-027-ad-strength-improvement
description: "Audit RSAs for Ad Strength ratings and identify improvements needed to reach Good or Excellent."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-027-ad-strength-improvement
  category: creative
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 027: Ad Strength Improvement

## Purpose

Ad Strength is Google's assessment of RSA quality based on relevance, quantity, and diversity of assets. RSAs rated Average or Poor receive fewer impressions and miss optimization opportunities. Improving to Good or Excellent can increase impressions by 5-15%.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Ads** - RSA ad strength, headlines, descriptions

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_ad.ad.id,
  ad_group_ad.ad_strength,
  ad_group_ad.ad.responsive_search_ad.headlines,
  ad_group_ad.ad.responsive_search_ad.descriptions,
  ad_group_ad.status,
  metrics.impressions,
  metrics.clicks,
  metrics.conversions
FROM ad_group_ad
WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
  AND ad_group_ad.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
ORDER BY ad_group_ad.ad_strength ASC
```
Run the reference query (API, UI report, or Editor export) for performance correlation analysis.

## Analysis Steps

1. **Categorize by Ad Strength:** Excellent (optimal), Good (acceptable), Average (needs work), Poor (priority fix)
2. **Diagnose issues for each below-Good RSA:** Headline count, description count, duplicates, missing keyword relevance, pinning restrictions
3. **Analyze improvement potential:** Map current assets to requirements, estimate effort vs impact
4. **Correlate with performance:** Compare CTR/conversion rates across Ad Strength levels
5. **Prioritize by campaign importance:** Focus on high-spend campaigns first

## Thresholds

| Condition | Severity |
|-----------|----------|
| Ad Strength = Poor | Critical |
| Ad Strength = Average | Warning |
| >50% of RSAs below Good | Critical |
| High-spend campaign with Poor Ad Strength | Critical |

## Output

**Short (default):**
```
## Ad Strength Audit
**Account:** [Name] | **RSAs:** [X] | **Below Good:** [Y]%

### Critical (Poor) ([Count])
- **[Campaign] / [Ad Group]**: Headlines [X]/15, Descriptions [Y]/4 -> Add [Z] headlines, [W] descriptions

### Warnings (Average) ([Count])
- **[Campaign] / [Ad Group]**: [Specific issue] -> [Fix]

### Distribution
| Ad Strength | Count | % |
|-------------|-------|---|
| Excellent | X | X% |
| Good | X | X% |
| Average | X | X% |
| Poor | X | X% |

### Recommendations
1. [Priority action with time estimate]
```

**Detailed adds:**
- Performance comparison by Ad Strength level
- Specific improvement checklist per RSA
- Quick wins (minor changes to reach Good)
