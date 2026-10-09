---
name: skill-085-custom-label-strategy-segmentation
description: "Review optional product segmentation labels against actual listing rules and approved business definitions."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-089-pmax-asset-group-structure, skill-045-budget-allocation-optimization, skill-151-product-feed-seasonal-keyword-optimization]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | shopping_build_plan opt-in (index #115)"
---
# Skill 085: Custom Label Strategy and Usage

## Purpose

Determine whether existing custom labels implement an intended product-selection or reporting strategy. Labels are optional; missing margin labels do not mean products receive identical bids.

## Data Requirements

**Applicability:** Shopping and retail PMax with a supplied product segmentation objective or existing custom labels.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/merchant_products.csv`: complete Merchant Center processed-product snapshot, including zero-delivery, excluded and disapproved items; one row per merchant_id, channel, content_language, feed_label, offer_id (the product key), target_country and destination. Include snapshot_at, data_source_id, submitted/effective title, description, link, item_group_id, brand, GTIN, MPN, identifier_exists, condition, product_type, submitted/effective google_product_category, color, size, gender, age_group, material, pattern, price, currency, availability, custom_label_0..4 and processing_status; retain submitted versus processed values separately.
- Optional prioritization: `export/custom/product_daily.csv`, Google Ads product report for the same mature 30-day window, one row per account_id, campaign_id, product key, target_country and date; impressions, clicks, cost, conversions, conversion_value and goal_set_id. Preserve report filters, omitted/suppressed rows and unmatched keys; this is a delivered-product sample, not a catalog denominator.
- `export/external/label_strategy.csv`: one row per merchant_id, label_slot and allowed_value with meaning, segment_rule, intended_use, owner, valid_from/to, margin_basis, seasonal_calendar_reference and approved_at; product-level margin/inventory classifications reference product keys and effective dates. Supply only approved aggregate economics, not customer records.
- `export/custom/listing_rules.csv`: complete current Ads listing-tree export, one row per account_id, campaign_id, ad_group_id or asset_group_id, node_id; parent_node_id, subdivision/unit type, included/excluded status, dimension, dimension_level, value, other_case flag, root inventory scope, merchant_id, feed_label, country, channel and language. Include all dimensions and leaves, not label-only rows.
- `export/custom/product_selection.csv`: optional independently exported resolved selection, one row per campaign/group, product key and snapshot_at with included, matched_leaf_id and source_reference; useful for checking the tree resolution.
- Opt-in build plan: `profile.shopping_build_plan_request` with `campaigns` (existing `export/campaigns` IDs of channel_type SHOPPING, optional priority), optional feed `scope`, `routing` rules `{when: {dim: value}, campaign_id | priority}` and `remainder_campaign_id`; needs a manifest-complete merchant_products feed.

**Missing inputs:** Without listing rules do not assert labels are unused; without approved margin/season definitions do not infer them from label names or prices. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.
Without `shopping_build_plan_request` the build-plan check is not applicable; an invalid request or a feed not certified complete gets no plan review.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Inventory all five label slots across the complete scoped feed, including empty values. Count distinct values and coverage; more than ten values is not inherently inconsistent or a platform violation.

2. Compare actual values to the client label dictionary and effective dates. Distinguish unknown meaning, legitimate free-form reporting, true misspellings and expired classifications; seasonal age is meaningful only against the supplied calendar.

3. Resolve full listing trees with parent paths, inclusion/exclusion leaves and other-case complements against the feed. Trace actual label use separately for product selection, reporting and any supported bidding control; an absent listing split does not prove a label unused elsewhere.

4. Reconcile planned versus resolved inclusion, using product_selection when supplied. Show mismatched product keys and business consequence before suggesting label or tree corrections. Delegate general product-overlap architecture to 089.

5. If a new segmentation serves a documented business decision, propose definitions, permitted values, source-of-truth owner, refresh cadence and intended control. Margin tiers require verified margin basis, returns/tax treatment and strategy applicability; do not infer targets or split campaigns from labels alone.

6. Maintain existing labels while proposing a controlled migration with downstream-use inventory and rollback requirements. Do not replace populated values, promise performance tiers improve bidding, or prescribe universal margin labels.

7. Only when `profile.shopping_build_plan_request` is set, propose a Standard Shopping ad-group/product-group plan keyed by item_id, brand, product_type level or custom label; `finalize` accepts it only if every in-scope offer lands in exactly one group or the explicit everything-else remainder, groups are non-empty, keys exist in the feed and routing/priority constraints hold. The plan is a proposal; nothing is created.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed label/rule mismatch directly excludes material intended inventory or includes prohibited inventory | Critical |
| Confirmed incorrect/expired label conflicts with an approved current selection or reporting rule | Warning |
| Missing optional labels, high value cardinality, or potential business-led segmentation | Info |
| Unresolved tree, undeclared label meaning or missing margin/season evidence | Info |

Use [PARAMETERS.md](../_resources/PARAMETERS.md) and resolved client overrides.
CTR comparisons require {{min_impressions}}, conversion-rate comparisons {{min_clicks}},
and CPA/ROAS comparisons {{min_conversions}} on **both** comparable sides.
Use mature, equal-length windows with matched goals, currency and attribution basis;
exclude incomplete days and conversion lag, and never divide by zero.
Numerical screens without a cited platform requirement are triage heuristics, not proof of harm.
Critical requires directly evidenced material delivery, measurement or safety failure.
Missing evidence and optional-feature absence are Info, not a failed or passed check.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), not a separate competing template.
Report stable entity IDs, condition key, observed evidence/window, sample denominators,
resolved thresholds, recommendation, uncertainty and the owning skill.

- Show label-slot/value coverage with catalog denominator, meaning and observed listing/reporting use.
- List rule node and product keys for actual mismatches, affected scope and historical exposure, with corrections addressed to the feed/Ads owner.
- Separate optional strategy proposals from defects; reference 089 for overlap and 045 for economic allocation rather than duplicate outputs.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
