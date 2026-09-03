---
name: skill-122-automated-keyword-pause-rules
description: "Identify keywords exceeding spend thresholds with zero conversions and recommend automated pause rules."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-122-automated-keyword-pause-rules
  category: waste
  kind: operational
  data_source: standard
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 122: Automated Keyword Pause Rules

## Purpose

Identify keywords wasting budget with zero conversions and recommend automated rule configurations to prevent ongoing waste. This analysis calculates appropriate thresholds based on account CPA targets and flags keywords currently meeting pause criteria.

## Data Requirements

**Data Source:** Standard

**Standard Data:**
- `data/performance/campaigns/*/*/keywords_metrics_30_days.md` - Keyword performance metrics
- `data/account/campaigns/*/campaign.md` - Target CPA settings
- `data/account/campaigns/*/*/keywords.md` - Keyword settings

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
ORDER BY metrics.cost_micros DESC
```
Use `/google-ads:get-custom` for different date ranges or additional metrics.

## Analysis Steps

1. **Establish thresholds:** Calculate pause threshold based on 2x target CPA (or account average CPA)
2. **Identify zero-conversion keywords:** Find keywords with spend above threshold and 0 conversions
3. **Flag approaching threshold:** List keywords at 50-100% of threshold with 0 conversions
4. **Exclude brand/strategic keywords:** Note keywords that should be excluded from auto-pause
5. **Generate rule configurations:** Provide specific rule settings for Google Ads

## Thresholds

| Condition | Severity |
|-----------|----------|
| Cost > 2x CPA with 0 conversions | Critical |
| Cost > 1.5x CPA with 0 conversions | Warning |
| Cost > 1x CPA with 0 conversions | Info |
| CTR < 0.5% with 1000+ impressions | Warning |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

**Short format (default):**
```
## Automated Pause Rules Audit

**Account:** [Name] | **Keywords Analyzed:** [X] | **Pause Candidates:** [Y]

### Critical - Pause Now ([Count])
- **[Keyword]** ([Campaign]): {{currency}} [Cost] spent, 0 conversions → Pause immediately
- **[Keyword]**: {{currency}} [Cost] spent, 0 conversions → Pause immediately

### Warning - Approaching Threshold ([Count])
- **[Keyword]**: {{currency}} [Cost] of {{currency}} [Threshold], 0 conversions → Monitor closely

### Recommended Rule Configuration
- Threshold: {{currency}} [2x CPA] (2x target CPA)
- Frequency: Daily
- Exclusions: Brand terms, keywords < 14 days old

### Waste Summary
Total spend on zero-conversion keywords: {{currency}} [Amount]
```

**Detailed adds:**
- Full table of keywords meeting pause criteria
- Rule configuration details for Google Ads setup
- Exclusion list recommendations
- Historical pattern analysis
