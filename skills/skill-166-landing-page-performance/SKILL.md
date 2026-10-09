---
name: skill-166-landing-page-performance
description: "URL-level spend, clicks and conversions from landing-page reports incl. PMax: CVR vs campaign-type baseline, guarded zero-conversion URLs, timestamped URL health."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: custom_query
  markets: all
  related: [skill-069-landing-page-experience-assessment, skill-079-broken-url-monitoring, skill-078-landing-page-speed, skill-092-pmax-final-url-expansion-control, skill-128-performance-max-channel-performance, skill-034-ad-copy-landing-page-consistency]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes2 | new recipe with deterministic check"
---
# Skill 166: Landing Page Performance

## Purpose

Show how spend, clicks, conversions and value are distributed across landing pages, per campaign type including Performance Max. Flag pages whose conversion rate falls well below their campaign-type baseline on a mature, sample-qualified basis, and high-spend pages without conversions after tracking and relevance review. Join timestamped URL health checks without charging a whole month of spend to a failure observed at one moment. A CVR gap is a diagnostic, not proof that the page causes it.

## Data Requirements

**Applicability:** Search, Shopping, Performance Max and other campaign types that appear in the Ads landing-page reports. Only one URL view is compared at a time: unexpanded final URLs (landing_page_view) and expanded final URLs (expanded_landing_page_view) are never added together. URL health is an optional deeper check.

**Required inputs:**

- Base [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `export/account` (currency, period, snapshot, lag, units), `export/campaigns` (`id`, `channel_type`, declared goal_ids when supplied), `export/conversion_actions` for tracking evidence, and manifest completeness per file.
- `export/custom/landing_page_performance.csv`: Ads Landing pages or Expanded landing pages report for the report period. One row per campaign_id + url_view + url, plus date and device when segmented; never totals mixed with segment rows. url_view is `landing_page` or `expanded_landing_page`. Columns: clicks, cost, conversions; optional impressions, conversion_value.
- Optional `export/external/landing_page_checks.csv` (the file skill-069 uses): supplied HTTP or browser checks, one row per requested_url + checked_at. Columns: status_code; optional final_url, access_error, source. Sanitize URLs first.
- Profile, optional: `url_ignore_params`, the query parameters to strip (exact names, or `prefix*` such as `utm_*`), and `campaign_objectives[id].goal_ids`, `tracking_verified` as defined in CLIENT_PROFILE.

**Missing inputs:** Without the URL report, no URL finding is possible: ad final URLs are settings, not served landing pages. Unknown lag or immature data allows only the descriptive totals. Unverified tracking blocks the zero-conversion path. Without URL checks, page health is unassessed, not healthy. Each skipped check names the exact `file:column`.

The URL report is a Google Ads UI or API export; this recipe does not fetch pages or run GAQL. No live GAQL verification is claimed.

## Analysis Steps

1. **Normalize URLs.** Lowercase scheme and host, drop default ports and the fragment, remove only the profile `url_ignore_params`, sort the remaining query parameters and keep the path verbatim (case and trailing slash included; an empty path becomes `/`). Rows with a non-absolute URL or an unknown url_view are excluded and reported.
2. **Aggregate.** Sum clicks, cost, conversions and value per url_view + normalized URL, and per url_view + channel_type + URL. Duplicate rows at the same grain count once. Join channel_type by campaign_id; unknown campaigns stay outside type baselines.
3. **CVR vs campaign-type baseline.** CVR = conversions / clicks. Baseline = the same url_view and channel_type minus this URL. Both the URL and the baseline need clicks >= {{min_clicks}}, the data must be mature, and campaigns of the type must not declare different goal sets.
   A URL with conversions > 0 whose CVR is below half the baseline, with cost >= {{spend_material}} (the highest value among its campaigns), is an Info diagnostic. Review decides whether supplied page or journey evidence shows a defect (Warning) or whether traffic mix explains the gap.
4. **Zero-conversion URLs (guarded).** Cost >= {{spend_floor}} (highest among its campaigns), zero conversions, mature data, and tracking evidenced for every contributing campaign. Only then review relevance and role: an investigation Warning, a non-conversion page (no finding), or uncertain. Otherwise list the candidates as descriptive and mark the check partial.
5. **URL health join.** Normalize requested_url with the same rules. Per URL, order checks by checked_at. A check fails on status >= 400 or an access error; 2xx passes; 3xx or unknown is undetermined.
   Two or more trailing consecutive failures on a spending URL are persistent: Warning, with Critical only through review.
   One trailing failure, or a failure followed by a later success, is Info and routed to skill-079 for repeat checks.
   Window cost is context. With a date segment, cost on failing-check dates is shown as day-level overlap, never as affected spend.
6. Recommend owner review only: page fixes, repeat checks, tracking checks on the page. Speed goes to skill-078, broken-URL incidents to skill-079, PMax URL expansion to skill-092, copy consistency to skill-034.

## Thresholds

| Condition | Severity |
|---|---|
| Reviewed persistent failure with evidence-referenced material exposure during the failure interval | Critical |
| Two or more trailing consecutive failed checks on a URL with spend in the period | Warning |
| Mature zero-conversion URL at {{spend_floor}} with verified tracking, confirmed by relevance review | Warning |
| Reviewed CVR gap with an evidence-referenced page or journey defect | Warning |
| Mature URL CVR below half its campaign-type baseline, both cohorts >= {{min_clicks}}, URL cost >= {{spend_material}} | Info |
| Single trailing failed check, failure followed by success, or zero-conversion URL pending review | Info |

The half-baseline and two-check cutoffs are triage heuristics, not significance tests.
Parameters resolve per campaign from [PARAMETERS](../_resources/PARAMETERS.md), taking the highest value across the URL's campaigns.
Insufficient samples, immature data and missing checks are coverage, not passes.
Critical needs a review decision that cites evidence of paid traffic during the measured failure interval.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format. Add:

- url_view, normalized URL with its raw variants, channel_type and contributing campaign_ids.
- Clicks, conversions and cost for the URL and its baseline, both CVRs and their ratio, and the window.
- Resolved {{min_clicks}}, {{spend_material}} and {{spend_floor}} values with source, plus maturity and tracking notes.
- Check timestamps, status codes, the trailing failure run and any day-level cost overlap, labeled as overlap.
- Recommendation, uncertainty and the adjacent owner (skill-069, 078, 079, 092, 128 or 034) where relevant.

Historical URL spend is exposure, never savings. No uplift forecast, no page or account changes.
