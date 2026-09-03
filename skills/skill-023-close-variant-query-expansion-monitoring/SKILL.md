---
name: skill-023-close-variant-query-expansion-monitoring
description: "Monitor the queries triggered by broad/phrase expansion and exact/phrase close variants; flag irrelevant spend, same-meaning drift, and converting queries to add as keywords."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.1.0
  category: keywords
  kind: deterministic
  data_source: export
  merged_from: [skill-120-close-variant-match-expansion-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 023: Close Variant and Query Expansion Monitoring

## Purpose

Google expands every match type: broad and phrase reach related queries, and exact and phrase also match close variants and "same meaning" rewrites. Map each search term to its triggering keyword, judge relevance, and act: negatives for irrelevant spend, new keywords for converting queries, narrower match types for keywords that mostly trigger drift.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Search terms (30 days)** - Actual queries with performance
- **Keywords** - Keywords with match types
- **Negative keywords (campaign level)** - Existing campaign negatives
- **Negative keywords (ad group level)** - Ad group negatives

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  search_term_view.search_term,
  search_term_view.status,
  segments.keyword.info.text,
  segments.keyword.info.match_type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
```
Run the reference query (API, UI report, or Editor export) for different date ranges or to filter by specific campaigns.

## Analysis Steps

1. **Map keywords to search terms:** Group search terms by triggering keyword and match type
2. **Classify each term:** Exact query, close variant (misspelling, reorder, plural), same-meaning rewrite, expanded (broad/phrase), or irrelevant
3. **Compare performance by class:** Conversion rate and CPA of exact queries vs variants vs expansions, per keyword
4. **Find negatives:** Irrelevant or zero-conversion terms above the spend floor
5. **Find keyword candidates:** Converting queries not yet keywords (search_term_view.status = NONE)
6. **Find keywords to narrow:** >= 50% of clicks on irrelevant or drifted terms, or an exact keyword taking > 50% of clicks from variants

## Thresholds

| Condition | Severity |
|-----------|----------|
| Irrelevant or zero-conversion term, Cost >= {{spend_floor}} | Critical |
| Keyword with >= 50% of clicks on irrelevant terms | Critical |
| "Same meaning" variant with different intent | Warning |
| Variant conversion rate < 50% of exact-query rate | Warning |
| Converting query not added as keyword | Warning |
| Exact keyword with > 50% of clicks from variants | Info |
| Broad keyword triggering 30+ unique queries | Info |

Sample size: compare conversion rates only above {{min_clicks}} clicks per class.

## Output

**Short (default):**
```
## Query Expansion Audit
**Account:** [Name] | **Queries:** [X] | **Issues:** [Y]

### Add as Negatives ([Count])
- **"[query]"** from [keyword]: {{currency}} [X] cost, 0 conv -> Add as [match] negative

### Add as Keywords ([Count])
- **"[query]"**: [X] conv at {{currency}} [Y] CPA -> Add as exact match

### Keywords to Narrow ([Count])
- **[keyword]** (broad): [X]% irrelevant queries -> Convert to phrase

### Recommendations
1. [Priority action]
```

**Detailed adds:**
- Match analysis table: exact queries vs close variants vs expansions (conversion rate, CPA)
- Query expansion summary by match type
- Full table of queries requiring action with triggering keyword
- Relevance score breakdown and waste analysis
