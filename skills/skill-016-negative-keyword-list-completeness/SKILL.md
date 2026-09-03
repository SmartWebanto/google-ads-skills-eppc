---
name: skill-016-negative-keyword-list-completeness
description: "Verify shared negative lists exist, cover the universal waste categories, are applied to every campaign, and are backed by search-term evidence."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-016-negative-keyword-list-completeness
  category: keywords
  kind: deterministic
  data_source: standard
  merged_from: [skill-113-proactive-negative-keyword-list-building]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 016: Negative Keyword List Completeness Audit

## Purpose

Shared negative lists are the cheapest waste prevention: build them proactively for universal waste (jobs, free, DIY, research, competitors), apply them everywhere, then confirm with search terms that nothing leaks through.

## Data Requirements

**Data Source:** Standard

**Standard Data:**
- `data/account/shared_negative_lists.md` - Shared negative keyword lists
- `data/account/campaigns/*/negative_keywords.md` - Campaign-level negatives
- `data/account/campaigns/*/*/negative_keywords.md` - Ad group-level negatives
- `data/performance/campaigns/*/*/search_terms_metrics_30_days.md` - To validate leakage
- `data/account/campaigns/*/campaign.md` - Campaign list for coverage check

**Reference GAQL:**
```sql
SELECT
  shared_set.id,
  shared_set.name,
  shared_set.type,
  shared_set.member_count
FROM shared_set
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
```
Use `/google-ads:get-custom` if you need detailed shared set membership.

**Reference GAQL (search terms):**
```sql
SELECT
  campaign.name,
  ad_group.name,
  search_term_view.search_term,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.clicks > 0
ORDER BY metrics.cost_micros DESC
LIMIT 5000
```

## Analysis Steps

1. **Inventory existing lists:** Names, keyword counts, campaign assignments
2. **Check universal categories:** Jobs/careers, free/DIY/tutorial, research/informational, support/login, competitor terms
3. **Verify application:** Every active Search and Shopping campaign has the universal list
4. **Gap analysis:** Search terms with waste patterns not blocked; high-spend zero-conversion terms
5. **Assess match types:** Phrase preferred; flag broad negatives (over-blocking risk)
6. **Recommend:** Universal (shared) vs campaign-specific negatives, with terms and match types

## Thresholds

| Condition | Severity |
|-----------|----------|
| No shared negative lists exist | Critical |
| Universal waste category not covered (jobs, free/DIY, research, support) | Warning |
| Shared list not applied to all campaigns | Warning |
| Waste terms found in search terms not blocked | Warning |
| Zero-conversion terms with Cost >= {{spend_floor}} not blocked | Warning |
| Broad match negatives present | Info |
| < 50 negative keywords in total | Info |

## Output

Use **Short** format by default. Use **Detailed** if user requests comprehensive analysis.

**Short:**
```
## Negative List Completeness Audit
**Account:** [Name] | **Shared Lists:** [X] | **Total Negatives:** [Y] | **Gaps:** [Z]

### Critical ([Count])
- **No shared lists**: All negatives at campaign level → Create shared lists

### Warnings ([Count])
- **Missing category**: "[Jobs/Careers]" not covered, $[X] wasted → Create list
- **Incomplete coverage**: "[List]" not applied to [X] campaigns → Apply to all

### Recommendations
1. Create shared list for "[category]" waste
2. Apply existing lists to all campaigns
```

**Detailed** adds:
- What Was Checked (list inventory, category coverage, application)
- List inventory table (Name, Keywords, Campaigns Applied, Coverage %)
- Waste category coverage table (Category, Covered?, List Name, Sample Keywords, Gap?)
- Campaigns missing coverage table
- Recommended shared list structure
- Recommended universal list with match types
