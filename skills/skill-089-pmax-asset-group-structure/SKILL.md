---
name: skill-089-pmax-asset-group-structure
description: "Review complete asset-group structure and resolved product selection against declared business intent."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-085-custom-label-strategy-segmentation, skill-090-pmax-audience-signal-configuration, skill-093-pmax-video-asset-review, skill-128-performance-max-channel-performance, skill-162-creative-asset-quality-ai-campaign-optimization]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 089: Performance Max Asset Group Structure

## Purpose

Review whether asset groups, creatives and product selection coherently represent the intended offers. Group counts, Ad Strength and overlapping product eligibility do not alone demonstrate diluted learning or wasted spend.

## Data Requirements

**Applicability:** All supplied PMax campaigns; product-tree checks apply only to feed-based campaigns.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`, `export/assets`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/custom/pmax_groups.csv`: complete Ads asset-group UI inventory at snapshot_at; one row per account_id, campaign_id, asset_group_id, including empty and paused groups and campaigns with zero groups via the campaign inventory. Fields: name, status, primary_status, platform_diagnostic, ad_strength, final_urls, final_mobile_urls and declared theme/objective.
- `export/custom/pmax_group_assets.csv`: full Ads association export at the same snapshot; one row per account_id, campaign_id, asset_group_id, asset_id and field_type with association_status, asset_type, text_or_media_reference, approval_status and performance_label. Include every asset type; a separate complete group inventory supplies groups with no associations.
- `export/external/merchant_products.csv`: complete Merchant Center processed-product snapshot, including zero-delivery, excluded and disapproved items; one row per merchant_id, channel, content_language, feed_label, offer_id (the product key), target_country and destination. Include snapshot_at, data_source_id, submitted/effective title, description, link, item_group_id, brand, GTIN, MPN, identifier_exists, condition, product_type, submitted/effective google_product_category, color, size, gender, age_group, material, pattern, price, currency, availability, custom_label_0..4 and processing_status; retain submitted versus processed values separately.
- `export/custom/pmax_listing_rules.csv`: complete current listing-filter tree, one row per account_id, campaign_id, asset_group_id and node_id; parent_node_id, node_type, inclusion/exclusion, dimension, level, value, other_case, merchant_id, feed_label, target_country, language and channel. Include root scope and every dimension, subdivision, unit and complement branch.
- `export/external/pmax_group_intent.csv`: one current approved row per campaign_id and asset_group_id; intended product keys or reproducible product predicate, theme, landing_page/offer evidence, target market, business_objective, permitted overlap, business-critical inventory and owner.
- Optional outcomes: `export/custom/pmax_group_daily.csv`, Ads group report at account_id, campaign_id, asset_group_id, date and goal_set_id for the mature 30-day window; impressions, clicks, cost, conversions and conversion_value.

**Missing inputs:** Without the feed or full listing tree skip resolved-product overlap checks; without associations skip asset coverage, never infer missing assets from group rows. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Start with the full campaign/group inventory and left-join asset associations. Keep empty, paused and currently ineligible groups distinct, record campaigns with zero groups, and reconcile parent/association statuses before assessing serving.

2. Map supplied themes to actual asset content, landing pages and intended products. Identify a specific offer contradiction or inability to serve from platform diagnostics; do not turn a mixed theme or a single group into an automatic defect.

3. For retail, evaluate every listing path against complete product attributes: combine ancestor predicates, exclusions and other-case complements within root merchant/market scope. Report unresolved branches instead of assuming all products; deduplicate product-key sets per group.

4. Compute pairwise intersections and uncovered intended sets within eligible comparable scopes. Overlap may intentionally share offers across themes and is not simultaneous auction competition; request rationale only for an observed mismatch to approved intent.

5. Summarize assets and Ad Strength descriptively; do not prescribe minimum headlines or groups. Delegate creative quality to 162, videos to 093, signals to 090 and performance judgments to 128, retaining one finding owner.

6. Propose a specific structural correction only for the evidenced theme/selection problem, with old/new intended product sets and protected inventory. Preserve useful groups and pooling; do not recommend splits solely to increase group count.

## Thresholds

| Condition | Severity |
|---|---|
| Current diagnostic or resolved filter error directly blocks material intended product/group delivery | Critical |
| Verified product-selection or offer/theme contradiction to approved business intent | Warning |
| Overlap without demonstrated intent conflict, optional regrouping, group count or Ad Strength rating alone | Info |
| Incomplete group/asset/filter inventory or insufficient comparable performance data | Info |

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

- Give complete group inventory including zero-asset groups, association coverage and serving-status evidence.
- For selection findings include campaign/group/node IDs, full product keys, intersection/uncovered denominators and intended versus observed sets.
- Cross-reference 090/093/128/162 findings instead of repeating signal, video, asset-count or efficiency prescriptions.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
