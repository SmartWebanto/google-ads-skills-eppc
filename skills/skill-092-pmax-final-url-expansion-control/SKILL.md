---
name: skill-092-pmax-final-url-expansion-control
description: "Review observed URL expansion settings and destinations without inferring defaults or traffic provenance."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-089-pmax-asset-group-structure, skill-125-landing-page-health-check-automation, skill-141-landing-page-policy-compliance]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 092: Performance Max Final URL Expansion Control

## Purpose

Compare verified final URL controls and actual destinations with campaign intent. Different URLs are not proof of expansion, and noncommercial page paths are not automatically irrelevant or unsafe.

## Data Requirements

**Applicability:** PMax campaigns with locally supplied URL configuration and destination evidence.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/custom/pmax_groups.csv`: complete Ads asset-group UI inventory at snapshot_at; one row per account_id, campaign_id, asset_group_id, including empty and paused groups and campaigns with zero groups via the campaign inventory. Fields: name, status, primary_status, platform_diagnostic, ad_strength, final_urls, final_mobile_urls and declared theme/objective.
- `export/external/pmax_url_settings.csv`: current Ads campaign configuration review, one row per account_id and campaign_id; final_url_expansion_status (enabled/disabled/unknown), observed_setting_label, page_feed_ids, page_feed_usage_mode, product_url_behavior, source_reference and observed_at. Capture actual settings, not a presumed API automation enum.
- `export/external/pmax_url_rules.csv`: complete current exclusion/page-feed inventory, one row per campaign_id, rule_or_feed_entry_id; rule_type, operator, url_or_pattern, feed_id, label, active_status, source_reference and observed_at. Include explicit inventory-complete and no-rules declarations per campaign.
- `export/custom/pmax_landing_pages.csv`: uncapped Ads landing-page report for the mature 30-day window, one row per account_id, campaign_id, date and reported_url; expanded_url when available, provenance (reported/unknown), impressions, clicks, cost, conversions, conversion_value and goal_set_id. Record coverage and report definitions.
- `export/external/pmax_destination_review.csv`: current client-reviewed URL snapshots, one row per campaign_id and canonical_url; tested_at, resolved_url, page_purpose, offer/product facts, approved_objectives, permitted_destination, provenance_evidence, source_reference and review_owner.

**Missing inputs:** Without settings, expansion is unknown; without provenance, label traffic destination-only. Without page evidence, do not diagnose page intent from its path. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Read actual final URL expansion and page-feed controls per campaign. Missing automation fields mean unknown; record settings and exclusions independently. Inventory asset-group, product-feed and page-feed URLs as alternative legitimate sources.

2. Normalize URLs conservatively, retaining parameters that affect content, market or product. Compare report URLs to configured/approved URLs and observed redirects; distinguish unknown origin from platform-reported expansion and preserve unmatched rows.

3. Evaluate destinations using approved objectives and page snapshots: editorial, about or support pages can serve legitimate consideration goals. Identify specific wrong offers, expired content or prohibited destinations, not generic path keywords.

4. Apply full exclusion rules to observed and intended URLs, checking operators, domain boundaries and collisions with valid destinations. Recommend only the minimum supported rule scope for a verified issue; do not blanket-exclude blog/about/privacy pages.

5. For optional performance review aggregate matched goals and comparable traffic; mature zero-conversion spend above {{spend_floor}} triggers relevance/tracking review, not immediate exclusion. Both-sided rate and efficiency sample rules apply; historical destination spend is exposure, not savings.

6. Delegate URL health and policy validation to 125/141. Propose a configuration review or bounded exclusion candidate only when evidence ties the destination problem to a controllable setting; do not disable expansion solely because no exclusions exist.

## Thresholds

| Condition | Severity |
|---|---|
| Confirmed material delivery to a prohibited/unsafe destination with current serving and page evidence | Critical |
| Verified destination/offer mismatch or mature nonconverting exposure above {{spend_floor}} requiring contextual review | Warning |
| Enabled expansion without exclusions, unknown URL origin or optional control opportunity | Info |
| Missing settings/rules/page review, incomplete URL coverage or insufficient sample | Info |

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

- Show campaign IDs and expansion status as enabled/disabled/unknown, plus rule inventory completeness.
- List observed URL, actual origin evidence, intended-use evidence, sample/window and minimal proposed control with protected URLs.
- Do not label every differing URL expanded, label all spend wasted, or duplicate 125/141 findings.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
