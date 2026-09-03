---
name: skill-031-sitelink-relevance-performance
description: "Evaluate sitelink extensions for relevance, completeness, and performance."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: creative
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 031: Sitelink Relevance and Performance Review

## Purpose

Sitelinks are the most impactful ad extension, potentially increasing CTR by 10-20%. Irrelevant, outdated, or incomplete sitelinks waste this opportunity. This review ensures sitelinks are relevant to user intent, have descriptions, and perform effectively.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Assets: sitelinks** - Sitelink extensions with linking info
- **Campaigns** - Campaign settings for context

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  asset.sitelink_asset.link_text,
  asset.sitelink_asset.description1,
  asset.sitelink_asset.description2,
  asset.final_urls,
  campaign_asset.status,
  metrics.impressions,
  metrics.clicks,
  metrics.conversions
FROM campaign_asset
WHERE campaign_asset.field_type = 'SITELINK'
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) for sitelink performance metrics.

## Analysis Steps

1. **Check sitelink completeness:** All should have link text (25 chars), Description 1 (35 chars), Description 2 (35 chars), working URL
2. **Assess relevance:** Link text matches landing page, descriptions expand on link text, URLs are specific (not homepage)
3. **Review diversity:** Cover different user intents (shopping, information, action, support)
4. **Analyze performance:** CTR by sitelink, identify top/bottom performers
5. **Check for issues:** Broken URLs, outdated content (expired promotions), policy violations

## Thresholds

| Condition | Severity |
|-----------|----------|
| Sitelink without descriptions | Warning |
| Sitelink links to homepage | Warning |
| Sitelink CTR < 0.2% | Warning |
| Fewer than 4 sitelinks | Warning |
| Outdated promotion sitelink | Critical |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short (default):**
```
## Sitelink Audit
**Account:** [Name] | **Sitelinks:** [X] | **Issues:** [Y]

### Critical ([Count])
- **"[Sitelink text]"**: [Issue] -> [Fix]

### Warnings ([Count])
- **[X] sitelinks** missing descriptions -> Add descriptions
- **"[Sitelink]"**: Links to homepage -> Use specific URL

### Performance
| Sitelink | CTR | Conv | Status |
|----------|-----|------|--------|
| [Top] | X% | X | Keep |
| [Bottom] | X% | X | Replace |

### Recommendations
1. [Priority action]
```

**Detailed adds:**
- Full completeness audit table
- Intent diversity analysis
- Campaign-level sitelink recommendations
