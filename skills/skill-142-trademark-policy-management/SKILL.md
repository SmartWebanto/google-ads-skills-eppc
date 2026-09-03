---
name: skill-142-trademark-policy-management
description: "Monitor trademark usage in ads, track exemptions, and maintain compliance with trademark policies."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-142-trademark-policy-management
  category: compliance
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 142: Trademark Policy Management

## Purpose

Audit ad copy for trademark usage, track authorization status for each trademark, and manage exemption requests. Proper trademark management prevents disapprovals, legal issues, and ensures legitimate use.

## Data Requirements

**Data Source:** Custom query required

**Export data:**
- **Ads** - Ad headlines and descriptions

**GAQL Query (for trademark violations):**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_ad.ad.id,
  ad_group_ad.ad.responsive_search_ad.headlines,
  ad_group_ad.ad.responsive_search_ad.descriptions,
  ad_group_ad.policy_summary.approval_status,
  ad_group_ad.policy_summary.policy_topic_entries
FROM ad_group_ad
WHERE ad_group_ad.status = 'ENABLED'
  AND ad_group_ad.policy_summary.approval_status = 'DISAPPROVED'
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `trademark_violations`.

## Analysis Steps

1. **Scan ad copy:** Identify brand names and potential trademarks in ads
2. **Check disapprovals:** Filter for TRADEMARKS policy violations
3. **Audit authorization:** Verify exemption status for each trademark used
4. **Assess risk:** Flag unauthorized trademark usage
5. **Track exemptions:** Monitor pending and approved exemption requests

## Thresholds

| Condition | Severity |
|-----------|----------|
| Using competitor trademark without exemption | Critical |
| Trademark disapproval on active ad | Critical |
| Exemption expiring within 30 days | Warning |
| Using trademark without documentation | Warning |
| Trademark in display URL path | Info |

## Output

**Short format (default):**
```
## Trademark Policy Audit

**Account:** [Name] | **Trademarks Used:** [X] | **Issues:** [Y]

### Trademark Usage Summary
| Trademark | Ads Using | Authorization | Status |
|-----------|-----------|---------------|--------|
| [Brand A] | [X] | Reseller | Approved |
| [Brand B] | [Y] | None | Risk |
| [Brand C] | [Z] | Pending | Under Review |

### Trademark Violations
- **[Campaign/AdGroup]**: "[Trademark]" in headline → Remove or get exemption

### Exemption Status
| Trademark | Type | Status | Expiration |
|-----------|------|--------|------------|
| [Brand] | Reseller | Active | [Date] |

### Action Items
1. Remove unauthorized trademark from [X] ads
2. Request exemption for [Y] trademarks
3. Renew exemption for [Z] before [Date]

### Recommendations
1. Maintain exemption documentation
2. Create trademark-free ad variants as backup
```

**Detailed adds:**
- Full trademark inventory with authorization status
- Exemption request process guidance
- Trademark-free alternative ad copy suggestions
- Exemption renewal calendar
