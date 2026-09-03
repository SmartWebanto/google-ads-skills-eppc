---
name: skill-062-audience-minimum-size-monitoring
description: "Monitor remarketing and customer lists to ensure they maintain the minimum 1,000+ members required for Search targeting."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-062-audience-minimum-size-monitoring
  category: targeting
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 062: Audience Minimum Size Monitoring

## Purpose
Monitor remarketing and customer lists to ensure they maintain the minimum 1,000+ members required for Search targeting. Audiences below threshold cannot be used for targeting and may affect campaign delivery.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include user list size data.

**Export data:**
- **Audiences (campaign level)** - Audience usage in campaigns

**GAQL Query:**
```sql
SELECT
  user_list.id,
  user_list.name,
  user_list.type,
  user_list.size_for_search,
  user_list.size_for_display,
  user_list.membership_status,
  user_list.membership_life_span,
  user_list.eligible_for_search,
  user_list.eligible_for_display
FROM user_list
WHERE user_list.membership_status = 'OPEN'
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `audience_sizes`.

## Analysis Steps

1. **Fetch all audience lists:** Run custom GAQL to get list sizes and eligibility status.
2. **Categorize by size status:** Healthy (5,000+), Acceptable (1,000-5,000), At Risk (500-999), Below Minimum (<500).
3. **Cross-reference with campaigns:** Identify if undersized lists are used in targeting (vs observation).
4. **Flag critical issues:** Audiences below minimum that are actively used for targeting.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Search audience < 500 users | Critical |
| Audience used for targeting but ineligible | Critical |
| Search audience 500-999 users | Warning |
| Display audience < 100 users | Warning |
| Audience trending down >20% weekly | Warning |

## Output

**Short (default):**
```
## Audience Size Monitoring Audit

**Account:** [Name] | **Audiences:** [X] | **Below Minimum:** [Y]

### Critical ([Count])
- **[Audience Name]**: [Size] users (needs 1,000) -> Extend membership duration or combine lists

### Warnings ([Count])
- **[Audience Name]**: [Size] users, trending down -> [Fix]

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- Full audience inventory by size tier
- Campaign impact analysis
- Membership duration recommendations
- List combination suggestions
