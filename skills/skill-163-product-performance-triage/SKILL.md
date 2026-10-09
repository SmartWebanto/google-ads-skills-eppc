---
name: skill-163-product-performance-triage
description: "Triage item-level Shopping/PMax outcomes: non-serving items, gated zero-conversion spend, target gaps, item trends and multi-campaign overlap."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: custom_query
  markets: all
  related: [skill-083-product-feed-attribute-completeness, skill-085-custom-label-strategy-segmentation, skill-089-pmax-asset-group-structure, skill-094-pmax-cannibalizing-search-detection, skill-128-performance-max-channel-performance]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes1 | new recipe with deterministic check"
---
# Skill 163: Product Performance Triage

## Purpose

Show which advertised items actually served, spent, converted and changed across Standard Shopping and feed-based PMax, and which items several campaigns served in the same window. The output is item-level triage for product selection, feed and bidding owners. Observed exposure is not proof of waste, and overlap is not proof of cannibalization.

## Data Requirements

**Applicability:** Standard Shopping and feed-based PMax campaigns with an item-level Ads product report. It does not apply to Search, Display or feedless PMax. Other campaigns stay out of scope without being called defects.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md) tables:
  - `export/account`: currency, units, period, snapshot and conversion lag.
  - `export/campaigns`: `id` and `channel_type`, plus `target_cpa`/`target_roas` and the bidding-strategy link where they exist.
  - Optional: `export/campaign_metrics` (`campaign_id`, `cost`) for coverage reconciliation, `export/conversion_actions` and profile `campaign_objectives`, `tracking_verified` and parameter overrides.
- `export/custom/product_daily.csv`: Ads product report (shopping-performance-style). The fields are:
  - One row per `account_id`, `campaign_id`, `offer_id`, `date`.
  - The report's lower-case `item_id` is an accepted alternative key column. `target_country` and `goal_set_id` are used where present.
  - Metrics: `impressions`, `clicks`, `cost`, `conversions`, `conversion_value`.
  - It covers the complete mature report window. The manifest records filters and completeness. Items the report omits are unobserved, not zero.
- Optional: `export/external/merchant_products.csv`, a Merchant Center processed-product snapshot:
  - One row per `offer_id` (plus `target_country` when present), with `availability` and `processing_status`.
  - It is filtered by the supplier to the Shopping ads destination and advertised countries, with `snapshot_at`.
  - It is used only for non-serving detection and serving-risk context.

**Missing inputs:**

- Without `product_daily.csv`, every item subcheck is skipped with its exact missing columns.
- Without a Merchant snapshot, non-serving detection is skipped.
- If either table lacks certified completeness, non-serving and stopped-serving absence findings are partial.
- An unknown conversion lag or tracking state disables zero-conversion and target-gap prescriptions, leaving descriptive totals only.
- A non-EUR account without `currency_floors` leaves money screens unresolved.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. **Scope** (`product_scope`):
   - Join product rows to `campaigns.id`, keeping only `SHOPPING` and `PERFORMANCE_MAX` channel types.
   - Keep dates inside the account period and drop duplicate rows at the report grain.
   - Count items with rows but zero impressions.
   - Reconcile summed item cost with `campaign_metrics` cost as a coverage share, never as a correction.
2. **Concentration** (`spend_concentration`): per campaign and account, compute the cost share of the top item, the top five items and the top decile of items, plus how many items make up 80% of cost. These are descriptive observations, not defects.
3. **Zero-conversion items** (`zero_conversion_items`): a campaign×item is screened only when all of these hold:
   - literal zero conversions;
   - cost ≥ {{spend_floor}} resolved for its campaign;
   - clicks ≥ {{min_clicks}};
   - `ctx.mature` is true;
   - the campaign's goal tracking is evidenced.

   A screened item gets a provisional Info finding. A relevance/economics review decides whether it becomes a Warning. When a gate fails, the check is partial.
4. **Target gaps** (`item_target_gap`): for items with ≥ {{min_conversions}} mature conversions, compare item CPA or ROAS with the campaign's resolved approved target. This is a descriptive gap and not a per-item bid. The check is skipped for campaigns that mix goals.
5. **Item trends** (`item_trends`): split the period into two equal consecutive halves and flag:
   - impression growth above 50% or decline beyond 30%, only when both halves reach {{min_impressions}};
   - items that stopped serving (prior ≥ {{min_impressions}}, current zero), only when the report is certified complete.

   Declines and stops with prior-half cost ≥ {{spend_significant}} go to a serving-loss review, with the Merchant availability/status attached where supplied.
6. **Overlap** (`item_overlap`): list the same `offer_id` with impressions in two or more Shopping/PMax campaigns, grouped per campaign pair. The only question is whether the overlap is intended routing. There is no cannibalization or auction claim; route structure to 089 and label rules to 085.
7. **Non-serving items** (`non_serving_items`): left-join the certified-complete Merchant snapshot to the product report. Approved/eligible, in-stock items with no Shopping/PMax impressions are listed. A review decides whether they were intended to serve. Critical is reachable only with an evidence reference to a verified serving failure.

Proposals are request-only. Bid, listing-tree or feed edits go to their owners, with no fixed uplift.

## Thresholds

| Condition | Severity |
|---|---|
| Approved intended core inventory directly evidenced as not serving (verified outage/exclusion, cited evidence reference) | Critical |
| Mature item with cost ≥ {{spend_floor}}, clicks ≥ {{min_clicks}}, zero conversions and verified tracking, judged unwanted or uneconomic after review | Warning |
| Approved in-stock items confirmed intended to serve but with no impressions in a certified-complete window | Warning |
| Item decline >30% or stop with prior-half cost ≥ {{spend_significant}}, confirmed as an unintended serving loss | Warning |
| Item served by two or more Shopping/PMax campaigns, confirmed as unintended against documented selection intent | Warning |
| Screened zero-conversion item before review, item CPA/ROAS missing target with ≥ {{min_conversions}}, qualified growth >50%, unreviewed decline/stop or observed overlap | Info |
| Spend concentration, immature window, unknown tracking, incomplete coverage or insufficient sample | Info |

Resolve parameters with [PARAMETERS.md](../_resources/PARAMETERS.md). Both trend halves must pass the sample gate. Zero or unknown denominators are undefined. The 30%/50% screens are triage heuristics, not significance tests.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md). Each finding lists:

- `campaign_id` and `offer_id`/pair and the condition key;
- the window or halves, with impressions, clicks, cost, conversions and value used;
- the resolved parameter and its source, plus the tracking/maturity note;
- the recommendation and its uncertainty.

Show concentration and coverage shares as observations.

Route feed attribute issues to 083, labels to 085, asset-group selection to 089, channel outcomes to 128 and Search overlap hypotheses to 094. Historical spend is exposure, not savings. There are no account, feed or bid changes.
