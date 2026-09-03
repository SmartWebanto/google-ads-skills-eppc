---
name: skill-037-ad-disapproval-monitoring
description: "Find disapproved, limited, and under-review ads, prioritize by business impact (silenced ad groups, high-spend campaigns), and provide a resolution workflow."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-037-ad-disapproval-limited-eligibility
  category: creative
  kind: deterministic
  data_source: custom_query
  merged_from: [skill-139-ad-disapproval-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 037: Ad Disapproval Monitoring

## Purpose

Disapproved ads stop serving; limited ads serve in restricted contexts; ads stuck under review deliver nothing. Find every non-approved ad, extract the policy topic, size the impact (silenced ad groups, spend at risk), and order the fixes.

## Data Requirements

**Data Source:** Custom query required
Standard ads.md gives approval status; policy topic entries need the GAQL query.

**Export data:**
- **Ads** - Ad approval status and policy issues

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_ad.ad.id,
  ad_group_ad.ad.type,
  ad_group_ad.ad.responsive_search_ad.headlines,
  ad_group_ad.ad.final_urls,
  ad_group_ad.policy_summary.approval_status,
  ad_group_ad.policy_summary.review_status,
  ad_group_ad.policy_summary.policy_topic_entries,
  ad_group_ad.status,
  metrics.impressions
FROM ad_group_ad
WHERE ad_group_ad.status != 'REMOVED'
  AND segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) for detailed policy topic entries.

## Analysis Steps

1. **Categorize by approval status:** Approved, Approved Limited, Area of Interest Only, Disapproved, Under Review
2. **Extract policy topics:** For every non-approved ad; group repeated violations
3. **Assess impact:** Ad groups with 0 approved ads (silenced), high-spend campaigns affected, share of ads disapproved
4. **Prioritize resolution:** Silenced ad groups → high-spend campaigns → repeated violations → editorial quick fixes
5. **Plan remediation:** Fix or replace, appeal if wrong, keep 2-3 approved ads per ad group

## Thresholds

| Condition | Severity |
|-----------|----------|
| Ad group with 0 approved ads | Critical |
| > 10% of ads disapproved | Critical |
| Disapproved ad in a campaign above {{spend_significant}}/30d | Critical |
| Any disapproved ad | Warning |
| Multiple ads with the same policy violation | Warning |
| Ad under review > 7 days | Warning |
| Limited eligibility or regional limitation affecting reach | Info |
| Ad under review 3-7 days | Info |

## Output

**Short (default):**
```
## Ad Approval Audit
**Account:** [Name] | **Ads:** [X] | **Disapproved:** [Y]

### Critical ([Count])
- **[Campaign] / [Ad Group]**: ALL ads disapproved (silenced) -> Fix immediately
  - Ad [ID]: [Policy topic] -> [Specific fix]

### Warnings ([Count])
- **[Campaign] / [Ad Group]**: [X] disapproved
  - [Policy topic]: "[ad copy causing issue]" -> [Fix]

### Status Summary
| Status | Count | % |
|--------|-------|---|
| Approved | X | X% |
| Disapproved | X | X% |
| Limited | X | X% |
| Under Review | X | X% |

### Recommendations
1. [Priority action]
```

**Detailed adds:**
- Full disapproval list with policy topics
- Common policy violations and fixes
- Resolution priority queue with estimated fix time
- Resolution workflow by policy type, appeal guidance, prevention checklist
