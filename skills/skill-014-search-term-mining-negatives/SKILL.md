---
name: skill-014-search-term-mining-negatives
description: "Identify irrelevant, wasteful, or poor-performing search queries that should be added as negative keywords to prevent future spend waste."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  upstream: trueclicks/claude-plugins google-ads@1.8.0
  upstream_skill: skill-014-search-term-mining-negatives
  category: keywords
  kind: deterministic
  data_source: export
  related: [skill-013-search-term-mining-keywords, skill-127-trending-search-term-detection]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 014: Search Term Mining for Negative Keywords

## Purpose
Identify irrelevant, wasteful, or poor-performing search queries that should be added as negative keywords to prevent future spend waste. Proactive negative keyword management reclaims budget for better-performing queries.

## Data Requirements

**Data Source:** Account export

**Export data:**
- **Search terms (30 days)** - Search query performance
- **Negative keywords (campaign level)** - Existing campaign negatives
- **Negative keywords (ad group level)** - Existing ad group negatives
- **Shared negative lists** - Shared negative keyword lists
- **Keywords** - Active keywords (to avoid conflicts)

**Reference GAQL:**
```sql
SELECT
  campaign.name,
  ad_group.name,
  search_term_view.search_term,
  search_term_view.status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.cost_micros > 0
```
Run the reference query (API, UI report, or Editor export) if you need different date ranges.

## Analysis Steps

1. **Find high-spend zero-conversion terms:** Filter Conversions = 0, Cost >= 2x target CPA or {{spend_floor}} minimum
2. **Identify low-engagement terms:** CTR < 1% AND Impressions >= 100 OR Clicks >= 10 AND Conv = 0
3. **Detect waste patterns:** Scan for "jobs", "free", "how to", "login", "support", competitor research terms
4. **Check against existing negatives:** Verify candidates not already blocked
5. **Recommend negative level:** Account-wide patterns → shared list; campaign-specific → campaign negative

## Thresholds

| Condition | Severity |
|-----------|----------|
| Cost >= 3x Target CPA AND Conv = 0 | Critical |
| Cost >= 2x Target CPA AND Conv = 0 | Warning |
| Clicks >= 20 AND Conv = 0 AND CTR < 1% | Warning |
| Contains waste pattern ("free", "jobs") AND Conv = 0 | Warning |

Sample size: apply rate-based rows (CTR, CVR, CPA, ROAS) only above {{min_clicks}} clicks, and CPA/ROAS comparisons only above {{min_conversions}} conversions; below that, report "insufficient sample" as Info.

## Output

Use **Short** format by default. Use **Detailed** if user requests comprehensive analysis.

**Short:**
```
## Negative Keyword Mining Audit
**Account:** [Name] | **Search Terms:** [X] | **Negatives Needed:** [Y]

### Critical ([Count])
- **"[search term]"**: {{currency}} [X] spent, 0 conversions → Add as [phrase] negative

### Warnings ([Count])
- **"[pattern]" pattern**: [X] terms, {{currency}} [Y] wasted → Add "[pattern]" to shared negative list

### Recommendations
1. Add [X] negative keywords (saves ~{{currency}} [Y]/month)
2. Create shared list for "[pattern]" terms
```

**Detailed** adds:
- What Was Checked (spend thresholds, waste patterns)
- High-spend zero-conversion table (Term, Campaign, Cost, Clicks, CTR, Recommendation)
- Waste pattern summary (Pattern, Terms Found, Total Cost, Action)
- Recommended negatives list (Keyword, Match Type, Level, Wasted Spend)
