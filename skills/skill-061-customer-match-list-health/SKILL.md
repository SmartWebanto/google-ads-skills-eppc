---
name: skill-061-customer-match-list-health
description: "Audit Customer Match lists for presence, size, match rate, freshness, and application to campaigns."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: targeting
  kind: deterministic
  data_source: custom_query
  merged_from: [skill-104-customer-match-list-management]
  related: [skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 061: Customer Match List Health

## Purpose

Customer Match is the most durable first-party targeting signal. Verify lists exist, are large enough to serve, match well, are refreshed, and are actually applied (targeting, observation, exclusion, or as a lookalike seed). Missing or stale lists silently weaken Smart Bidding and remarketing.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include user list metadata such as size, match rate, or freshness.

**Export data:**
- **Audiences (campaign level)** - Customer Match list usage in campaigns

**GAQL Query:**
```sql
SELECT
  user_list.id,
  user_list.name,
  user_list.type,
  user_list.size_for_search,
  user_list.size_for_display,
  user_list.membership_status,
  user_list.match_rate_percentage,
  user_list.eligible_for_search,
  user_list.eligible_for_display
FROM user_list
WHERE user_list.type = 'CRM_BASED'
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `customer_match_lists`.

## Analysis Steps

1. **Fetch CRM-based lists:** Size for search/display, match rate, membership status, eligibility
2. **Evaluate health:** Size, match rate, days since last upload
3. **Check coverage:** All-customers, high-value, recent and lapsed segments exist
4. **Check application:** Which campaigns use each list and in what mode; flag lists applied nowhere
5. **Recommend:** Refresh cadence, segment structure, and where to apply each list

## Thresholds

| Condition | Severity |
|-----------|----------|
| No Customer Match lists in account | Critical |
| List size < 500 users | Critical |
| Match rate < 30% | Critical |
| Last updated > 90 days | Critical |
| Match rate 30-50% or list size 500-1,000 | Warning |
| Last updated 30-90 days | Warning |
| List applied to no campaign | Warning |
| No high-value, recent or lapsed segment | Info |

## Output

**Short (default):**
```
## Customer Match List Freshness Audit

**Account:** [Name] | **Lists Analyzed:** [X] | **Applied:** [Y] | **Issues:** [Z]

### Critical ([Count])
- **[List Name]**: [Size] users, [Match Rate]%, [Days] days old -> Re-upload current list

### Warnings ([Count])
- **[List Name]**: [Issue] -> [Fix]

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- Full list inventory with all metrics
- Campaign usage mapping
- Match rate optimization tips
- Recommended list types to add
- Recommended list structure (all, high-value, recent, lapsed) and compliance checklist
