---
name: skill-083-product-feed-attribute-completeness
description: "Audit identifiers and category-specific attributes against complete feed data and Merchant Center diagnostics."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-082-product-feed-title-optimization, skill-088-google-product-category-granularity]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 083: Product Feed Attribute Completeness

## Purpose

Review identifier correctness and applicable product attributes, including products that never served. Completeness is evaluated against product facts, destination/market requirements and actual platform diagnostics, not a universal attribute checklist.

## Data Requirements

**Applicability:** Retail Merchant Center catalogs used by Shopping or PMax; evaluate requirements separately by destination and market.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/merchant_products.csv`: complete Merchant Center processed-product snapshot, including zero-delivery, excluded and disapproved items; one row per merchant_id, channel, content_language, feed_label, offer_id (the product key), target_country and destination. Include snapshot_at, data_source_id, submitted/effective title, description, link, item_group_id, brand, GTIN, MPN, identifier_exists, condition, product_type, submitted/effective google_product_category, color, size, gender, age_group, material, pattern, price, currency, availability, custom_label_0..4 and processing_status; retain submitted versus processed values separately.
- `export/external/merchant_diagnostics.csv`: same snapshot; one row per product key, target_country, destination and issue_code, with attribute, platform_severity, eligibility_status, issue_text, first_seen_at, observed_at and source_reference. Include a completeness manifest and explicit no-issue status; absence of issue rows alone is not proof of approval.
- `export/external/product_reference.csv`: current client catalog, one row per product key and target_country; item_group_id, internal_sku, manufacturer_model, authoritative title/description, verified brand/GTIN/MPN and identifier assignment status, variant attributes, intended destinations, product function, evidence_reference and updated_at. No invented identifiers or attributes.
- Optional prioritization: `export/custom/product_daily.csv`, Google Ads product report for the same mature 30-day window, one row per account_id, campaign_id, product key, target_country and date; impressions, clicks, cost, conversions, conversion_value and goal_set_id. Preserve report filters, omitted/suppressed rows and unmatched keys; this is a delivered-product sample, not a catalog denominator.
- `export/external/attribute_requirements.csv`: current documented requirement matrix, one row per market, destination, category, condition and attribute; required_when, exceptions, source_url, checked_at and accepted_format. Include GTIN/MPN/brand, identifier_exists, color, size, gender, age_group and other category-specific fields.

**Missing inputs:** Missing identifiers in an Ads performance report do not prove missing feed attributes; absent reference identifiers or applicability evidence prevents correctness/requirement judgments. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Build a complete scoped catalog and deduplicate the composite product key before measuring coverage. Separate submitted values, processed values, missing values, explicit not-applicable values and unresolved identifier assignments.

2. For each identifier use manufacturer/catalog assignment evidence. Preserve GTIN leading zeros; check permitted length/check digit and variant correspondence without treating syntax validity as proof of ownership. Do not invent GTIN/MPN, copy one between variants, or set identifier_exists false merely to silence diagnostics.

3. Apply the current [GTIN guidance](https://support.google.com/merchants/answer/6324461?hl=en) and supplied requirement matrix. GTIN can legitimately be unassigned; brand/MPN treatment depends on product circumstances. Do not label every absent GTIN or brand Critical.

4. Evaluate category-specific color, size, gender, age_group and other attributes only where applicable. Check price, availability, links and variant grouping against source facts/diagnostics; unsupported attributes remain unknown, not blank by inference.

5. Calculate populated/applicable coverage per attribute, category and destination, preserving exempt counts. Product_type is merchant-defined; two hierarchy levels are not a requirement. Delegate category accuracy to 088 and title copy to 082.

6. Prioritize current blocked intended inventory using diagnostics and business importance; optional product metrics show historical exposure only. Ask the feed owner for verified corrections and a later processed-feed/diagnostic check, never automatic feed edits.

## Thresholds

| Condition | Severity |
|---|---|
| Current attribute-related disapproval directly blocks material intended product delivery | Critical |
| Confirmed applicable missing/invalid attribute or source-to-feed mismatch without established material blockage | Warning |
| Legitimately unassigned identifier, optional product_type depth, or optional enrichment opportunity | Info |
| Requirement applicability, catalog reference or diagnostics unavailable | Info |

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

- Report each product key, market/destination, attribute, supplied value, verified source value, applicable requirement and diagnostic.
- Include applicable denominator, missing count, exempt count and unresolved count; do not substitute delivered impressions for catalog coverage.
- Give feed-owner correction proposals and delegated 082/088 finding references, without guaranteeing visibility or conversion gains.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
