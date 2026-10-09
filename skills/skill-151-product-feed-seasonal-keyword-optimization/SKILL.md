---
name: skill-151-product-feed-seasonal-keyword-optimization
description: "Improve truthful product descriptors while keeping promotional messages out of product titles."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence and controls; gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | full product identity joins"
---
# Skill 151: Seasonal Product Descriptor Review

## Purpose

Improve truthful product descriptors while keeping promotional messages out of product titles.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Merchant Center products used by Shopping/PMax with actual feed records and product evidence.

**Required inputs:**
- Base `export/` tables: account, campaigns, search_terms, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/seasonal_feed.csv`: merchant_id/feed_label/language/item_id/snapshot_at grain; title, structured_title_if_used, description, brand, product_type, variant_attributes, product_url, promotion_ids, approval_status; actual current Merchant Center feed export.
- `export/external/product_descriptor_evidence.csv`: merchant_id/feed_label/language/item_id/descriptor grain; genuine_attribute, product_page_snapshot_ref, applicable_season_or_event, truthful_use_rationale, owner; current client product records/pages.
- Optional `export/custom/query_product_evidence.csv`: account_id/campaign_id/query/merchant_id/feed_label/language/item_id/date grain; impressions, clicks, cost, conversions, source_report, mapping_method, coverage; supported observed query-to-product evidence for historical event and current mature period. Product-title reports are NOT search-query reports.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Join the full merchant/feed_label/language/item key rather than titles; distinguish feed title from
   query text. A source missing a key dimension needs an explicit unique full-key mapping. Otherwise
   retain the ambiguity and skip variant/language-specific attribution; never fan one source row out
   across matching feed labels or languages. Record mapping provenance and coverage gaps.

2. Inspect product evidence for genuine seasonal attributes such as a Christmas-pattern sweater; generic gift relevance does not require a gift-title prefix.

3. Use query evidence to prioritize truthful descriptors only when the query/product mapping is genuinely reported. Without mapping, do product-content review but skip product-specific query opportunity claims.

4. Keep title accurate and descriptive. Never insert promotional text such as black friday deal, discount, free shipping or sale urgency; use separately eligible Merchant promotions and supported price fields.

5. Preserve brand, distinguishing product and variant information; avoid keyword stuffing and automatic seasonal prefixes. Any return/revision schedule reflects actual product truth, not mandatory post-event reversion.

6. Propose before/after title text with evidence, language, owner and a controlled feed test; no Merchant Center edits or guaranteed visibility uplift.

Use matched IDs and declared grain before joining; never multiply entity metrics across many-to-many associations.
For comparisons, align goals, traffic scope and complete periods; exclude incomplete days and conversion reporting lag.
Use {{min_impressions}} for CTR/share, {{min_clicks}} for CVR and {{min_conversions}} for CPA/ROAS, on both comparison sides.
A zero-conversion spend screen may bypass min_conversions only after maturity, working tracking and relevance review at {{spend_floor}}.
Do not divide by zero; preserve censored, suppressed and unknown values rather than treating them as zero.
Historical non-converting cost is exposure, not guaranteed savings; observational changes are not causal uplift.

## Thresholds

Numerical cutoffs here are triage heuristics unless explicitly tied to a sourced platform requirement.
Resolve parameters through [PARAMETERS](../_resources/PARAMETERS.md); business tolerances require a declared value.

| Condition | Severity |
|---|---|
| Current title contains evidenced promotional or misleading product text | Warning |
| Truthful descriptor opportunity or missing optional query-product mapping | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Item-keyed current/proposed title, descriptor evidence and title-versus-promotion separation.
- Query mapping provenance where available, policy reason, review owner and request-only test plan.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.

[Merchant Center title requirements](https://support.google.com/merchants/answer/6324415?hl=en).
