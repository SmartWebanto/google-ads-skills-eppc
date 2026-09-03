---
name: skill-073-enhanced-conversions-leads
description: "Verify that Enhanced Conversions for Leads is properly configured to match offline CRM data back to Google Ads clicks."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-073-enhanced-conversions-leads
  category: tracking
  kind: deterministic
  data_source: custom_query
  markets: eea_relevant
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 073: Enhanced Conversions for Leads

## Purpose
Verify that Enhanced Conversions for Leads is properly configured to match offline CRM data back to Google Ads clicks. This enables accurate measurement of lead quality and downstream conversions (SQLs, opportunities, closed deals) that occur offline.

## Data Requirements

**Data Source:** Custom query required

A basic account export does not include Enhanced Conversions for Leads status.

**Export data:**
- **Conversion actions** - Conversion action configuration
- **Account** - Account settings including enhanced conversions for leads

**GAQL Query:**
```sql
SELECT
  customer.id,
  customer.descriptive_name,
  customer.conversion_tracking_setting.enhanced_conversions_for_leads_enabled
FROM customer
LIMIT 1
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `enhanced_conversions_leads_status`.

## Analysis Steps

1. **Check Enhanced Conversions for Leads status:** Verify enabled at account level.
2. **Identify lead conversion actions:** Find actions categorized as LEAD, SIGNUP, QUALIFIED_LEAD.
3. **Assess data capture:** Verify email is captured at form submission for matching.
4. **Evaluate CRM integration:** Check if offline conversion import pipeline exists.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Enhanced Conversions for Leads not enabled (B2B/Lead Gen) | Critical |
| Only tracking form fills, no downstream stages | Critical |
| GCLID not captured in CRM | Critical |
| No offline conversion import pipeline | Warning |
| Import match rate < 50% | Warning |
| Import delay > 14 days | Warning |

## Output

**Short (default):**
```
## Enhanced Conversions for Leads Audit

**Account:** [Name] | **Status:** [Enabled/Disabled] | **Issues:** [Y]

### Lead Funnel Tracking
| Stage | Tracked | Import Method |
|-------|---------|---------------|
| Form Submit | [Yes/No] | Website tag |
| SQL | [Yes/No] | [Import/None] |
| Closed Won | [Yes/No] | [Import/None] |

### Critical ([Count])
- **[Issue]**: [Description] -> [Fix]

### Recommendations
1. [Priority action]
2. [Secondary action]
```

**Detailed adds:**
- Lead funnel tracking coverage
- CRM integration assessment
- Import pipeline health
- GCLID capture implementation guidance
