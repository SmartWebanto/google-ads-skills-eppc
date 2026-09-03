# Merges (2026-09-03)

Eight upstream skills checked the same condition on the same data as another skill. Each pair became one canonical skill; the absorbed skill's directory was removed. `metadata.merged_from` on the canonical records the absorbed name; `metadata.upstream_skill` keeps the canonical's original upstream name.

| Canonical | Absorbed | Why |
|---|---|---|
| skill-121-impression-share-loss-analysis | skill-133-impression-share-loss-analysis | Identical GAQL and thresholds on search IS lost to budget vs rank |
| skill-023-close-variant-query-expansion-monitoring | skill-120-close-variant-match-expansion-monitoring | Same search-term-to-keyword mapping; one covered broad/phrase expansion, the other exact/phrase close variants |
| skill-061-customer-match-list-health | skill-104-customer-match-list-management | Same `user_list` query; freshness vs coverage were two halves of one check |
| skill-037-ad-disapproval-monitoring | skill-139-ad-disapproval-monitoring | Same `ad_group_ad.policy_summary` data; monitoring vs resolution workflow |
| skill-016-negative-keyword-list-completeness | skill-113-proactive-negative-keyword-list-building | Same shared-list inventory and universal waste categories |
| skill-064-quality-score-distribution-analysis | skill-129-quality-score-monitoring-alert-rules | Same QS distribution; 129 added alert rules, now one operational step in 064 |
| skill-054-geographic-performance-analysis | skill-055-underperforming-location-exclusion | Same `geographic_view` query; exclusion is the low-performer branch of the analysis |
| skill-029-rsa-asset-performance-analysis | skill-126-rsa-asset-performance-bulk-analysis | Same asset performance labels; 126 added ad-level metrics, now a second query in 029 |

Canonicals renamed in the merge (directory and `name`; `upstream_skill` keeps the old name): 121 `impression-share-lost-analysis` → `impression-share-loss-analysis`; 023 `close-variant-broad-match-monitoring` → `close-variant-query-expansion-monitoring`; 061 `customer-match-list-freshness` → `customer-match-list-health`; 037 `ad-disapproval-limited-eligibility` → `ad-disapproval-monitoring`.

## Threshold reconciliation notes

- **121/133:** 133's "any IS loss > 10%: Info" conflicted with 121's "budget lost > 10%: Warning"; the stricter Warning was kept and 133's "both > 15%: Warning" row added.
- **023/120:** the two `$50` zero-conversion rows became one row on `{{spend_floor}}`.
- **061/104:** 104's "not updated > 90 days: Warning" became Critical (061's severity). 104's "< 1,000 users: Warning" and 061's "500-1,000: Warning" merged into one row.
- **037/139:** "under review" reconciled to Info at 3-7 days and Warning above 7 days. 139's "high-spend campaign" became `{{spend_significant}}`.
- **016/113:** 113's "high-spend zero-conversion terms" got the explicit `{{spend_floor}}` threshold.
- **064/129:** 129's `$50` floor folded into 064's `{{spend_significant}}` row; 129's "QS dropped 2+ points" kept with the note that it needs a previous snapshot.
- **054/055:** "outside service area" raised from High to Critical (it is pure waste). 055's two zero-conversion rows became `{{spend_significant}}` (Critical) and `{{spend_floor}}` to `{{spend_significant}}` (High). Upstream's four-level severity (High) was kept where it existed.
- **029/126:** 126's "Poor strength with significant spend" got `{{spend_significant}}`; "All assets Learning" got `{{min_impressions}}`.

## Reviewed and kept separate

Linked with `metadata.related` instead: 044/123 (monthly pacing vs day-of-week allocation), 013/014/127 (keyword mining, negative mining, trend detection), the conversion-tracking cluster (070, 071, 081, 107, 108, 110), the landing-page cluster (034, 069, 078, 079, 125, 141), and 064/065/066/067 (Quality Score facets).
