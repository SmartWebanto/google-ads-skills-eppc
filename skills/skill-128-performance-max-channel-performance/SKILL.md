---
name: skill-128-performance-max-channel-performance
description: "Review available PMax channel and group outcomes with honest reporting coverage and comparable goals."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: analyst
  data_source: custom_query
  related: [skill-089-pmax-asset-group-structure, skill-090-pmax-audience-signal-configuration, skill-093-pmax-video-asset-review, skill-094-pmax-cannibalizing-search-detection, skill-115-display-youtube-placement-performance-review, skill-162-creative-asset-quality-ai-campaign-optimization]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixShoppingAudiences | evidence contracts and contextual decision rules"
---
# Skill 128: Performance Max Channel Performance

## Purpose

Analyze actual PMax campaign, asset-group and available channel reports without claiming unsupported network visibility or causal superiority over Search. Campaign outcomes remain usable when finer reports are unavailable.

## Data Requirements

**Applicability:** PMax campaigns; channel/group/placement subchecks run only at the granularity genuinely available in the account report.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns`, `export/campaign_metrics`; profile campaign_objectives and documented comparable business segments; client objectives and parameter overrides.
- Record export window, account timezone/currency, snapshot time, source, filters, completeness and conversion-date basis.
- `export/custom/pmax_groups.csv`: complete Ads asset-group UI inventory at snapshot_at; one row per account_id, campaign_id, asset_group_id, including empty and paused groups and campaigns with zero groups via the campaign inventory. Fields: name, status, primary_status, platform_diagnostic, ad_strength, final_urls, final_mobile_urls and declared theme/objective.
- For group analysis: `export/custom/pmax_group_daily.csv`, Ads group report at account_id, campaign_id, asset_group_id, date and goal_set_id over the mature 30-day window; impressions, clicks, cost, conversions, conversion_value and report_source/coverage. Include all reportable groups and retain nonreporting groups from pmax_groups.csv.
- For channel analysis: `export/custom/pmax_channels.csv`, actual Ads PMax channel-performance UI report when available, one row per account_id, campaign_id, date (or declared complete report_start/end), reported_channel, reported_format and goal_set_id; impressions, interactions, interaction_definition, clicks, cost, conversions, conversion_value, source_report_name, reporting_version, metric_availability and suppression/coverage notes. Do not substitute ad_network_type aggregates for an unverified full channel report.
- For placement context only: `export/custom/pmax_placements.csv`, actual Ads placement report for the same window at account_id, campaign_id, reported_placement_id/url, placement_type and date/window; impressions and any other genuinely exposed metrics with availability flags, source and coverage. Absence of cost/conversions does not permit allocation from campaign totals.
- For cross-campaign comparison only: `export/custom/pmax_comparison_segments.csv`, Ads reports at campaign_id, date/window, goal_set_id, market and directly reported brand/customer segment; impressions, clicks, cost, conversions, conversion_value, segment_definition and coverage. Unsupported brand/customer breakdowns are unknown; profile-approved role comparability must accompany comparisons.

**Missing inputs:** If group/channel/placement evidence is absent, skip only that layer and retain the campaign summary. Without comparable goal/brand/customer mix do not rank PMax against Search. Skip only the dependent subcheck and list exact missing fields; continue supported inventory. Omitted settings are unknown, not enabled or disabled.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. Identify all PMax campaigns and reconcile campaign outcomes to complete mature windows, currency, attribution and goals. Include spend from currently paused campaigns; use campaign totals as the authoritative campaign layer, not the sum of independently segmented reports.

2. For group analysis left-join the full group inventory to actual metrics. Distinguish zero performance from unreported metrics and empty groups. Ad Strength is descriptive, not an outcome or a Critical/Low-quality diagnosis; delegate structure/creative to 089/162.

3. Use channels exactly as the supplied report defines them, preserving format splits and interaction versus click denominators. Check whether rows are mutually exclusive before summing, reconcile reported coverage to campaign totals and retain unknown/unavailable segments rather than invent a complete distribution.

4. Screen actual channel/group outcomes against the campaign economic objective only with mature sample gates. Zero-conversion spend at {{spend_floor}} requires working tracking and relevance review; no automatic pause or fixed 70% Display allocation rule. Mixed conversion goals cannot be ranked by raw CPA.

5. Compare PMax and Search only within genuinely aligned goals, markets and brand/customer roles; if those cannot be segmented, display separate totals without a performance verdict. Even matched observational CPA differences do not establish marginal return, incrementality or cannibalization; delegate overlap hypotheses to 094.

6. Keep placement impressions as exposure where cost/outcomes are unavailable and delegate placement decisions to 115. Route signals to 090 and video coverage to 093; do not claim their state from campaign/group outcome tables or recommend unsupported per-channel bidding controls.

## Thresholds

| Condition | Severity |
|---|---|
| Mature comparable group/channel outcomes miss an approved economic objective, or zero-conversion spend exceeds {{spend_floor}} after tracking/relevance review | Warning |
| PMax versus Search CPA difference without aligned goals/brand/customer mix | Info |
| Channel allocation share, Ad Strength, optional signal or video absence alone | Info |
| Unsupported reporting dimensions, incomplete coverage or insufficient sample | Info |

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

- Provide campaign summary even when deeper reports are unavailable; show group IDs and every report coverage/missing-field limitation.
- Separate actual channel metrics from placement-only exposure and preserve reported interaction definitions.
- Give economic review proposals with comparable segments and owning-skill references; no reconstructed channel spend, automatic Search superiority or duplicate asset/signal findings.

Recommendations are request-only proposals; do not modify accounts, feeds, tags or audience lists.
Historical spend is exposure, not guaranteed savings. Do not forecast uplift without a stated model or controlled test.
