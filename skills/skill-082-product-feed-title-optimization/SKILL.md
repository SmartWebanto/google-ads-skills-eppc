---
name: skill-082-product-feed-title-optimization
description: "Review complete Merchant Center titles against product facts and applicable editorial requirements."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-083-product-feed-attribute-completeness, skill-151-product-feed-seasonal-keyword-optimization]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 082: Product Feed Title Optimization

## Purpose

Identify inaccurate or ambiguous product titles using complete feed and catalog evidence. Separate platform requirements from merchandising hypotheses; brand-first ordering and title length alone are not performance diagnoses.

## Data Requirements

**Applicability:** Retail Shopping and feed-based PMax products in the supplied markets/destinations; not service-only campaigns.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/external/merchant_products.csv`: complete Merchant Center processed-product snapshot, including zero-delivery, excluded and disapproved items; one row per merchant_id, channel, content_language, feed_label, offer_id (the product key), target_country and destination. Include snapshot_at, data_source_id, submitted/effective title, description, link, item_group_id, brand, GTIN, MPN, identifier_exists, condition, product_type, submitted/effective google_product_category, color, size, gender, age_group, material, pattern, price, currency, availability, custom_label_0..4 and processing_status; retain submitted versus processed values separately.
- `export/external/merchant_diagnostics.csv`: same snapshot; one row per product key, target_country, destination and issue_code, with attribute, platform_severity, eligibility_status, issue_text, first_seen_at, observed_at and source_reference. Include a completeness manifest and explicit no-issue status; absence of issue rows alone is not proof of approval.
- `export/external/product_reference.csv`: current client catalog, one row per product key and target_country; item_group_id, internal_sku, manufacturer_model, authoritative title/description, verified brand/GTIN/MPN and identifier assignment status, variant attributes, intended destinations, product function, evidence_reference and updated_at. No invented identifiers or attributes.
- Optional prioritization: `export/custom/product_daily.csv`, Google Ads product report for the same mature 30-day window, one row per account_id, campaign_id, product key, target_country and date; impressions, clicks, cost, conversions, conversion_value and goal_set_id. Preserve report filters, omitted/suppressed rows and unmatched keys; this is a delivered-product sample, not a catalog denominator.
- `export/external/title_requirements.csv`: one row per market, destination, product_category and rule_id; requirement_or_recommendation, requirement_text, source_url, checked_at, exceptions and applicability. Use current Merchant Center title guidance; include title-generation provenance and structured_title digital_source_type from the feed producer.

**Missing inputs:** Without a complete feed, report only the supplied product sample and no catalog percentages; without catalog facts, do not invent title corrections. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Join by the complete product key and market/destination, not title text or offer_id alone. Count distinct offers within each declared scope; separate unique products from destination rows and document unresolved joins.

2. Determine the effective submitted title when title and structured_title coexist. Check actual product/variant correspondence, required variant distinctions and applicable title/structured-title provenance requirements against catalog evidence.

3. Use the [Merchant Center title specification](https://support.google.com/merchants/answer/6324415?hl=en): title/content allows 1–150 characters; overlong titles may be truncated with a warning. Promotional sale/shipping text is not a genuine product descriptor. AI-generated proposals require the prescribed structured_title provenance treatment.

4. Screen repeated keywords, ambiguous generic wording and missing distinguishing facts for analyst review. Preserve legitimate model numbers, short but precise titles, unbranded items, brand positioning, localized grammar and required business wording; do not mandate Brand + Type + Attributes ordering.

5. For each proposed revision cite the supporting product facts and preserve the variant identity. Compare optional CTR only within comparable categories, markets and delivery periods with sample gates; title cohorts are descriptive, not causal evidence of lift. Delegate attribute defects to 083 and seasonal merchandising to 151.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed title-related disapproval blocks materially important intended product delivery, supported by current diagnostics and scope | Critical |
| Documented product mismatch, applicable editorial issue, or observed title truncation requiring correction | Warning |
| Short title, absent nonessential brand, alternative ordering, or a fact-supported clarity opportunity without demonstrated harm | Info |
| Incomplete catalog, unverified product facts or insufficient performance sample | Info |

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

- Give product-key coverage and explicit complete-catalog versus delivered-sample denominators.
- List current/effective title, factual issue, diagnostic code, proposed title and provenance/attribute destination; do not fabricate SKUs or product claims.
- Keep objective requirements separate from optional title hypotheses; cross-reference 083/151 rather than duplicate their findings.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
