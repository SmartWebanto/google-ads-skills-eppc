---
name: skill-088-google-product-category-granularity
description: "Review category assignments against current taxonomy and verified product function, not depth quotas."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-083-product-feed-attribute-completeness, skill-085-custom-label-strategy-segmentation]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 088: Google Product Category Accuracy

## Purpose

Identify demonstrably inaccurate Google product categories and supported, more-specific mappings. Taxonomy depth is descriptive, not a quality score; accurate automatic categorization need not be overridden.

## Data Requirements

**Applicability:** Merchant Center products with category assignments or category-dependent requirements/selection.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/merchant_products.csv`: complete Merchant Center processed-product snapshot, including zero-delivery, excluded and disapproved items; one row per merchant_id, channel, content_language, feed_label, offer_id (the product key), target_country and destination. Include snapshot_at, data_source_id, submitted/effective title, description, link, item_group_id, brand, GTIN, MPN, identifier_exists, condition, product_type, submitted/effective google_product_category, color, size, gender, age_group, material, pattern, price, currency, availability, custom_label_0..4 and processing_status; retain submitted versus processed values separately.
- `export/external/merchant_diagnostics.csv`: same snapshot; one row per product key, target_country, destination and issue_code, with attribute, platform_severity, eligibility_status, issue_text, first_seen_at, observed_at and source_reference. Include a completeness manifest and explicit no-issue status; absence of issue rows alone is not proof of approval.
- `export/external/product_reference.csv`: current client catalog, one row per product key and target_country; item_group_id, internal_sku, manufacturer_model, authoritative title/description, verified brand/GTIN/MPN and identifier assignment status, variant attributes, intended destinations, product function, evidence_reference and updated_at. No invented identifiers or attributes.
- Optional prioritization: `export/custom/product_daily.csv`, Google Ads product report for the same mature 30-day window, one row per account_id, campaign_id, product key, target_country and date; impressions, clicks, cost, conversions, conversion_value and goal_set_id. Preserve report filters, omitted/suppressed rows and unmatched keys; this is a delivered-product sample, not a catalog denominator.
- `export/external/google_taxonomy.csv`: complete current official Google taxonomy downloaded by the client, one row per category_id; full_path, parent_id, language, source_url, fetched_at and published_version/date when present, otherwise content_hash. Do not invent a taxonomy version. Preserve a submitted-version mapping if older categories are used.
- `export/external/category_usage.csv`: current Ads/merchant configuration review, one row per product scope and usage_id; campaign_id, category_id, market, destination, category-specific requirement or listing_rule_reference, override_reason, source_reference and snapshot_at.

**Missing inputs:** Without taxonomy and product-function evidence, report assignments only; a shallow category is not a defect. Missing effective category does not mean no automatic category exists. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Join the complete feed to product facts and taxonomy by category ID; preserve submitted text/ID, effective platform category and older-to-current translation separately. Do not use truncated performance rows to count catalog categories.

2. Apply the [Google product category guidance](https://support.google.com/merchants/answer/6324436?hl=en): the attribute is optional, products are automatically categorized and overrides have specific supported purposes. Validate that any proposed override is applicable rather than universally requiring manual GPC.

3. Classify products by their main function, handling bundles and category-specific exceptions with source evidence. Traverse candidate descendants in the current taxonomy; choose the most specific accurate category, not the deepest branch in an unrelated category.

4. Flag an invalid ID or apparent obsolete mapping for review of platform translation before declaring invalid delivery. If no category describes the product, preserve uncertainty and consider merchant product_type rather than fabricate a category.

5. Compare similar products only when their functions and variant contexts are genuinely equivalent. A depth distribution or inconsistent-looking path alone is Info; a source-supported miscategorizaton is a correction candidate.

6. Trace any affected category-specific requirements and listing selections to diagnostics/category_usage. Delegate missing attribute findings to 083 and merchant label design to 085; do not infer CTR improvement from depth correlations.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed category error directly causes material intended delivery blockage or an evidenced safety failure | Critical |
| Verified wrong product-function assignment or invalid current mapping needing review | Warning |
| Shallow but accurate category, accurate automatic assignment or optional specificity opportunity | Info |
| Missing current taxonomy, effective mapping or product reference | Info |

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

- Report taxonomy source, fetched_at/version or hash, scope and complete-catalog denominator.
- Provide product key, submitted/effective category, proposed ID/path, function evidence, override applicability and affected diagnostic/rule.
- Retain depth distribution as descriptive context only; never recommend universal L4+ or automatic overrides.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
