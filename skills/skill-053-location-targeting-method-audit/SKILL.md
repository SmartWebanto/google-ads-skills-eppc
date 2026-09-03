---
name: skill-053-location-targeting-method-audit
description: "Verify that campaigns use the correct location targeting method (\"Presence\" vs \"Presence or Interest\") based on business type."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: targeting
  kind: deterministic
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 053: Location Targeting Method Audit

## Purpose

For local businesses, "Presence" targeting is typically preferred to avoid wasted spend on users who cannot physically visit. This skill verifies campaigns use the correct location targeting method based on business type and flags potentially misconfigured campaigns.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Account** - Account context and business type
- **Campaigns** - Campaign settings including geo targeting type
- **Bid adjustments (campaign level)** - Location targeting details

**Reference GAQL:**
```sql
SELECT
  campaign.id,
  campaign.name,
  campaign.geo_target_type_setting.positive_geo_target_type,
  campaign.geo_target_type_setting.negative_geo_target_type,
  campaign.status
FROM campaign
WHERE campaign.status != 'REMOVED'
```
Run the reference query (API, UI report, or Editor export) if geo target type settings are not in basic account export.

## Analysis Steps

1. **Load campaign data:** Read account summary to understand business type, read each campaign.md for geo targeting settings.

2. **Identify location targeting settings:** Extract positiveGeoTargetType and negativeGeoTargetType values (Presence vs PresenceOrInterest).

3. **Classify by business type:** Local Service/Retail = should use Presence. E-commerce/Travel = can use PresenceOrInterest.

4. **Flag potential issues:** Local business using PresenceOrInterest (wasted spend), e-commerce using Presence only (missing researchers), inconsistent settings across similar campaigns.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Local service business with PresenceOrInterest | Critical |
| Local retail with PresenceOrInterest | High |
| Inconsistent settings across similar campaigns | Warning |
| E-commerce with Presence only | Info |

## Output

**Short (default):**
```
## Location Targeting Method Audit

**Account:** [Name] | **Campaigns Analyzed:** [X] | **Potentially Misconfigured:** [Y]

### Critical ([Count])
- **[Campaign]**: Local business using "Presence or Interest" → Change to "Presence"

### Warnings ([Count])
- **[Campaign]**: Inconsistent with other campaigns → Review for consistency

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- Summary table (total campaigns, using Presence, using PresenceOrInterest, potentially misconfigured)
- Campaign details table (campaign, positive targeting, negative targeting, business fit, flag)
- Best practice guidelines by business type (local service, local retail, e-commerce, travel, B2B)
