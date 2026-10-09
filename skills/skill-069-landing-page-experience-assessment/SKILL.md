---
name: skill-069-landing-page-experience-assessment
description: "Triage landing-page ratings with defensible URL attribution and separate measured page evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: external
  related: [skill-034-ad-copy-landing-page-consistency, skill-078-landing-page-speed, skill-079-broken-url-monitoring, skill-125-landing-page-health-check-automation, skill-141-landing-page-policy-compliance]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 069: Landing Page Experience Assessment

## Purpose

Use the Search landing-page experience rating to prioritize investigation; it is not a
speed, mobile-usability or broken-page test. Attribute spend to URLs only when routing
supports it. Shared landing pages can correctly serve many keywords and are not defects.
QS is diagnostic, not a direct CPC cause: [Google Ads: About Quality Score](https://support.google.com/google-ads/answer/6167118?hl=en).

## Data Requirements

**Applicability:** Search keyword LP ratings; real page assessments require supplied
external observations. Other channels may have URL metrics but not keyword QS diagnostics.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) `account`,
`campaigns`, `ad_groups`, `keywords`, `keyword_metrics` and `ads` with stable IDs,
LP rating, status/approval, keyword URL overrides, ad final/mobile URLs and mature metrics.
- For exact URL exposure, `export/custom/landing_url_performance.csv` from the Ads
  Landing pages/Expanded landing pages report: one row per account_id/campaign_id/date/
  landing_page_url/expanded_url/device and any explicit report segments. Columns:
  impressions, clicks, cost, conversions, conversion_value, source, attribution_basis,
  reporting_completeness. Do not invent keyword IDs absent from this report.
- If historical keyword-to-URL assignment is claimed, `export/custom/url_routing.csv`
  from ad/keyword URL settings and change history: account_id, campaign_id, ad_group_id,
  criterion_id, ad_id, device, effective_start, effective_end, keyword_override_url,
  ad_final_url, mobile_final_url, resolved_destination, routing_source, source.
  Grain: one eligible criterion/ad/device/destination route per effective interval.
- For actual page findings, `export/external/landing_page_checks.csv` from supplied
  browser checks, URL diagnostics or PageSpeed reports, one row per URL/device/check_id:
  requested_url, final_url, checked_at, source, method, environment, status_code,
  access_error, redirect_chain, mobile_usability_observation, content_excerpt,
  performance_metric_name, performance_metric_value, performance_metric_unit,
  field_or_lab, sample_window, sample_size. Missing metric columns remain unknown.
  Sanitize URLs and page captures to remove private customer data.

**Missing inputs:** Without page checks perform rating triage only; do not claim speed or
mobile tests ran. Missing routing/URL metrics means keyword exposure or ambiguous URL sets,
not fabricated per-URL spend. Missing one check blocks only its dependent conclusion.

## Analysis Steps

1. Inventory rated keywords and Below Average LP diagnostics with current snapshot date,
   metric period and N/A coverage. Review cost >= {{spend_high}} as priority, not Critical.
2. Resolve candidate routes using keyword override precedence, mobile/ad URLs and effective
   dates. Multiple eligible ad URLs, dynamic routing or redirects can make allocation unknown.
   Do not multiply each keyword's full spend by every eligible URL or split it equally by guess.
3. If each keyword has one demonstrably stable destination throughout the metric window,
   assign its cost once and label settings-based attribution. Otherwise retain its cost once
   under an ambiguous destination set, or use actual URL report cost as a separate measure.
4. Deduplicate URL metrics at the supplied grain. Never add expanded and unexpanded report
   versions together; maintain meaningful query parameters and preserve redirect evidence.
   URL report cost cannot be attributed to weak-rated keywords without a defensible join.
5. Review supplied page evidence for observed accessibility, usability, relevant offer/content
   and measured speed. Report field versus lab metrics, device, units and sample context;
   a QS LP rating alone does not diagnose slow load, mobile failure or bounce behavior.
6. Shared-page reuse is acceptable when intents and offers align. Semantic content gaps need
   quoted page/ad/query evidence and analyst judgment, not literal keyword absence.
   Route speed to 078, broken URLs to 079, copy consistency to 034 and policy review to 141.
7. Propose focused page tests where evidence is missing, or owner-reviewed fixes where a
   reproducible defect exists. This recipe does not execute tests or modify pages/accounts.
   Separate diagnostic spend exposure from directly observed delivery failure and causal loss.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Below Average LP rating and cost >= {{spend_high}} | Warning |
| Supplied reproducible usability/content defect affecting intended journey | Warning |
| Directly evidenced inaccessible destination causing material delivery/journey failure | Critical |
| Shared page, rating prevalence, ambiguous routing or absent page tests | Info |
| Low-exposure LP diagnostic or optional performance improvement hypothesis | Info |

Rating/spend cutoffs are triage heuristics, not proof of lost revenue. Business metric
comparisons follow [PARAMETERS](../_resources/PARAMETERS.md): {{min_impressions}} CTR,
{{min_clicks}} CVR, {{min_conversions}} CPA/ROAS on both mature comparable sides.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Add URL attribution basis, candidate/ambiguous routes, non-additive URL versus keyword
exposure, measured page evidence/source/time and explicit tests-not-performed caveats.
