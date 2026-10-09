---
name: skill-165-merchant-feed-freshness-and-item-status
description: "Merchant Center item status by issue/destination, spend share on disapproved items, feed fetch freshness vs schedule, change frequency and expiring items."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: deterministic
  data_source: external
  markets: all
  related: [skill-083-product-feed-attribute-completeness, skill-088-google-product-category-granularity, skill-128-performance-max-channel-performance, skill-141-landing-page-policy-compliance]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes2 | new recipe with deterministic check"
---
# Skill 165: Merchant Feed Freshness and Item Status

## Purpose

Show which Merchant Center items are disapproved or limited, by issue code and destination; how much of the catalog and of recent Shopping/PMax product spend they represent; and whether feeds are fetched as scheduled and often enough for observed price/availability changes. Status and timestamps are facts. What a policy issue means, and whether a blocked item is intended to sell, is review.

## Data Requirements

**Applicability:** Retail Merchant Center catalogs that feed Shopping or Performance Max campaigns. Item-status checks need a status snapshot; spend shares need product performance; freshness checks need feed schedule evidence. Asset-level PMax disapprovals are out of scope.

**Required inputs:**

- Base [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `export/account` (currency, period, snapshot, units), `export/campaigns` (`id`, `channel_type`), plus manifest completeness for every file below.
- `export/external/merchant_item_status.csv`: Merchant Center product-status snapshot, one row per merchant_id + offer_id + target_country + destination (plus channel, content_language and feed_label when supplied). Columns: status (`approved`, `limited`, `disapproved` or `pending`; other values stay unknown), snapshot_at; optional feed_id and expiration_date. Include approved items: shares need the full snapshot.
- `export/external/merchant_diagnostics.csv` (the file skill-083 uses): one row per merchant_id + offer_id + target_country + destination + issue_code. Columns: platform_severity (`disapproved`, `demoted` or `unaffected`), observed_at; optional attribute, issue_text, source_reference.
- `export/custom/product_daily.csv` (the skill-083 file): Ads product report for the report period. One row per campaign_id + offer_id + date, optionally target_country. Columns: clicks and cost; optional impressions, conversions, conversion_value. This is delivered traffic, not a catalog denominator.
- `export/external/merchant_feeds.csv`: one row per merchant_id + feed_id. Columns: fetch_interval_hours (declared schedule), last_fetch_at, last_fetch_status (`success` or `failure`), snapshot_at; optional feed_name, paused, last_update_at. All timestamps are ISO 8601 in one time zone.
- `export/external/catalog_changes.csv`: from the shop/ERP system. One row per offer_id + field (`price` or `availability`) + changed_at, for the report period.
- Profile, optional: `merchant_ads_destinations` (default `Shopping ads`/`Shopping`), `feed_mismatch_issue_codes` (the issue codes that mean feed/site mismatch for this client).

**Missing inputs:** Each missing file or column skips only its dependent check. The skipped check names the exact `file:column`. Without a manifest-complete status snapshot, catalog shares stay partial and no item absence is inferred. Without product performance, spend shares are not computed, and a disapproval is not called material. Without feed evidence, freshness is unknown, not healthy.

These local intake schemas describe evidence, not asserted API field names. Merchant Center status comes from a supplied export; this recipe does not call the Content API. No live GAQL verification is claimed.

## Analysis Steps

1. **Catalog status.** Deduplicate the product key. A key with conflicting statuses is excluded and reported.
   Per destination and country, count approved, limited, disapproved, pending and unknown items.
   Share = disapproved / known-status items. An incomplete snapshot gives a share of supplied rows only.
2. **Issue codes.** Count distinct items per destination, issue_code and platform_severity.
   For each issue code that disapproves items, review whether it signals a policy violation or a data fix.
   Outcomes: policy violation (Warning), data fix (Info, route to skill-083), or uncertain (Info).
   Landing-page policy questions go to skill-141.
3. **Spend on affected items.** Scope: SHOPPING and PERFORMANCE_MAX campaigns, dates inside the report period.
   Join product_daily to status on offer_id for the ads destination, adding target_country when both files have it.
   An offer counts as affected once; one-to-many rows are never summed twice.
   Record affected cost / total product cost per campaign.
   Items disapproved at the snapshot served earlier while eligible, so this cost is exposure, not loss.
   Each Warning item goes to review: is the item intended to sell, and is the loss material?
   Critical needs a cited evidence reference; an item not intended to sell (discontinued, deliberately withdrawn) drops the finding.
4. **Feed freshness.** Age = snapshot_at − last_fetch_at, in hours. A feed is stale when its age exceeds two declared intervals.
   A failed last fetch is reported on its own. A paused schedule is reported as Info.
   An unknown interval or an unparseable timestamp is coverage, never assumed healthy.
5. **Change frequency vs schedule.** Per feed (via item feed_id), count offers with more price/availability changes
   in one calendar day than 24 / fetch_interval_hours. The feed cannot show every intermediate state for these offers.
   Escalate only when the same feed carries an issue code the profile declares as a mismatch code.
6. **Expiring items.** Report items with expiration_date within 7 days after the snapshot, per destination.
7. Recommend owner actions only: a feed or schedule fix, a manual fetch, a policy appeal, a data correction.
   This recipe never triggers fetches, edits feeds or changes campaigns.

## Thresholds

| Condition | Severity |
|---|---|
| Reviewed intended item blocked, with evidence-referenced material delivery loss | Critical |
| Item disapproved for the ads destination with campaign item cost >= {{spend_significant}} in the period | Warning |
| Last feed fetch failed, or last fetch older than two declared fetch intervals at snapshot | Warning |
| Issue code confirmed by review as a policy violation rather than a data fix | Warning |
| Changes outpace the fetch schedule and the feed carries a profile-declared mismatch issue code | Warning |
| Disapproved items per destination, limited items, sub-threshold disapproved spend, or expiring within 7 days | Info |
| Changes outpace schedule without a declared mismatch issue, or a paused fetch schedule | Info |

The two-interval, 7-day and one-calendar-day cutoffs are triage heuristics, not Merchant Center rules. {{spend_significant}} resolves per campaign from [PARAMETERS](../_resources/PARAMETERS.md). Status findings need no conversion maturity, because no performance comparison is made. Missing or incomplete evidence is coverage, not a pass. Critical needs a review decision that cites evidence the item is intended to sell and that delivery loss is material.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md). Include merchant_id, offer_id, target_country, destination, campaign_id, feed_id and issue_code. Also include status and snapshot/check timestamps, counts with denominators, affected and total cost with window, fetch interval, age in hours, parameter values with source, recommendation and uncertainty. Spend on currently disapproved items is historical exposure, never savings or lost revenue. Attribute completeness is owned by skill-083, category accuracy by skill-088, PMax channel performance by skill-128 and landing-page policy by skill-141.
