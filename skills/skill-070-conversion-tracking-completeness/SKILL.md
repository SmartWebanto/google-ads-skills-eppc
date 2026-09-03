---
name: skill-070-conversion-tracking-completeness
description: "Verify that all valuable business actions are being tracked as conversions in Google Ads."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-070-conversion-tracking-completeness
  category: tracking
  kind: deterministic
  data_source: export
  related: [skill-071-conversion-tracking-accuracy, skill-081-micro-conversion-tracking, skill-107-conversion-value-accuracy, skill-108-cross-device-conversion-tracking, skill-110-conversion-tracking-breakage]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 070: Conversion Tracking Completeness

## Purpose
Verify that all valuable business actions are being tracked as conversions in Google Ads. Incomplete tracking leads to missing optimization signals, inaccurate ROAS calculations, and suboptimal Smart Bidding performance.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Conversion actions** - Conversion action settings and configuration
- **Account** - Account-level conversion tracking status
- **Campaign metrics (30 days)** - Conversion data by campaign

**Reference GAQL:**
```sql
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.type,
  conversion_action.category,
  conversion_action.status,
  conversion_action.include_in_conversions_metric,
  conversion_action.counting_type,
  conversion_action.attribution_model_settings.attribution_model
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
```
Run the reference query (API, UI report, or Editor export) to get conversion volume per action.

## Analysis Steps

1. **Inventory conversion actions:** List all active conversion actions with type and category.
2. **Categorize by type:** Purchases, leads, calls, app installs, engagement.
3. **Identify gaps:** Compare tracked actions to expected business value actions.
4. **Check configuration:** Verify counting type, attribution model, primary vs secondary.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Only 1 conversion action configured | Critical |
| No phone call tracking for local business | Critical |
| Primary conversion has no conversions in 30d | Critical |
| Missing micro-conversions (add to cart, form start) | Warning |
| No offline conversion import for B2B | Warning |
| Conversion action active but never recorded | Warning |

## Output

**Short (default):**
```
## Conversion Tracking Completeness Audit

**Account:** [Name] | **Conversion Actions:** [X] | **Issues:** [Y]

### Conversion Action Inventory
| Action | Type | Primary | Last 30d |
|--------|------|---------|----------|
| [Name] | [Type] | [Yes/No] | [Count] |

### Critical ([Count])
- **[Issue]**: [Description] -> [Fix]

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- Full conversion action configuration details
- Business type assessment
- Missing conversion type recommendations
- Implementation guidance
