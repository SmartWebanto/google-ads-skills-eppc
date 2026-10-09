---
name: skill-093-pmax-video-asset-review
description: "Review complete PMax video associations, provenance and actual format evidence without custom-video quotas."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  related: [skill-036-video-asset-presence, skill-089-pmax-asset-group-structure, skill-128-performance-max-channel-performance, skill-162-creative-asset-quality-ai-campaign-optimization]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 093: Performance Max Video Asset Review

## Purpose

Review PMax video coverage, provenance, brand fit and supported format needs. No custom video does not prove automated video was generated or served, and generation provenance does not establish quality.

## Data Requirements

**Applicability:** PMax asset groups including groups with zero video associations; evaluate serving requirements only for their actual configuration.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/assets`; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/custom/pmax_groups.csv`: complete Ads asset-group UI inventory at snapshot_at; one row per account_id, campaign_id, asset_group_id, including empty and paused groups and campaigns with zero groups via the campaign inventory. Fields: name, status, primary_status, platform_diagnostic, ad_strength, final_urls, final_mobile_urls and declared theme/objective.
- `export/custom/pmax_group_assets.csv`: full Ads association export at the same snapshot; one row per account_id, campaign_id, asset_group_id, asset_id and field_type with association_status, asset_type, text_or_media_reference, approval_status and performance_label. Include every asset type; a separate complete group inventory supplies groups with no associations.
- `export/external/pmax_video_details.csv`: current media-library/Ads asset-detail review, one row per account_id and asset_id; youtube_video_id, video_url/reference, width_px, height_px, duration_seconds, language, creation_provenance (advertiser/automated/unknown), provenance_reference, content_review, rights/brand_approval, reviewed_at and source_reference. Do not infer dimensions or provenance from names.
- `export/external/pmax_video_requirements.csv`: current platform configuration/documentation review, one row per campaign_subtype, intended_format and rule_id; supported, required_or_recommended, dimension/aspect/duration limits, requirement_conditions, source_url and checked_at. Separate eligibility constraints from optional coverage.
- Optional outcomes: `export/custom/pmax_video_metrics.csv`, Ads report for the same mature 30-day window at account_id, campaign_id, asset_group_id (only if reported), asset_id, date and format; impressions, video_views, completed_views or reported_completion_rate, rate_denominator_definition, clicks, cost, conversions, conversion_value and attribution_scope. Declare unsupported fields absent; do not allocate campaign metrics to videos.

**Missing inputs:** Without complete groups/associations do not claim missing videos; without media/provenance evidence skip dependent format/source checks. Unavailable video metrics remain unavailable. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Left-join all groups and all asset associations, then classify verified video assets. Distinguish zero associations, removed/disapproved assets, eligible advertiser assets, verified automated assets and unknown provenance; account inventory does not prove group linkage.

2. Inspect supplied media dimensions, duration and provenance references. Derive aspect ratio only from nonzero dimensions; link advertiser rights/brand reviews to actual videos. No custom association does not establish automated creation or delivery.

3. Check applicable requirements using pmax_video_requirements and current diagnostics. Preserve legitimate feed-only or other supported configurations; a missing portrait ratio or fewer than three videos is not inherently a problem.

4. Review actual offer, language, product and brand consistency from media evidence. Treat automated and advertiser-produced video equally; report a concrete mismatch or policy diagnostic rather than assuming auto-generated content is lower quality.

5. Calculate view/completion metrics only with the report-defined eligible denominator. Compare like formats and goals with mature sample gates; performance labels are contextual, and campaign conversions cannot be assigned to one video. Do not use a universal 25% completion cutoff.

6. Propose a specific permitted video/format improvement only for demonstrated brand, requirement or planned-coverage needs. Delegate non-PMax inventory to 036, creative theme critique to 162 and campaign/channel outcomes to 128.

## Thresholds

| Condition | Severity |
|---|---|
| Current video-related diagnostic directly blocks materially required intended serving | Critical |
| Verified video content/rights mismatch or supported requirement failure needing owner review | Warning |
| Optional custom/portrait video opportunity, unknown provenance or low contextual performance label | Info |
| Missing media evidence, unsupported video metrics or incomplete group inventory | Info |

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

- Provide every group including zero-video rows and asset IDs, association status, provenance evidence, dimensions and duration.
- Separate actual required-format failure from optional creative coverage and observed serving from asset availability.
- Give asset-specific proposals with uncertainty and 036/128/162 ownership references; no numerical video-count mandate.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
