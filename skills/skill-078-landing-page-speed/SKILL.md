---
name: skill-078-landing-page-speed
description: "Prioritize landing pages using actual field or controlled lab measurements rather than Quality Score proxies."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-034-ad-copy-landing-page-consistency, skill-069-landing-page-experience-assessment, skill-079-broken-url-monitoring, skill-125-landing-page-health-check-automation, skill-141-landing-page-policy-compliance, skill-074-server-side-tagging-assessment]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 078: Landing Page Speed Evidence

## Purpose

Prioritize landing pages using actual field or controlled lab measurements rather than Quality Score proxies.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Live destinations with supplied performance measurements; export-only runs produce a testing-priority list, not a speed verdict.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `ads`, `keywords`, `assets`, `ad_metrics`, `keyword_metrics`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/destination_map.csv`: account_id/campaign_id/ad_group_id/entity_type/entity_id/url_id grain, from Ads destination inventory at snapshot.
  Columns: final_url_sanitized, mobile_url_sanitized, keyword_override, effective_url_rule, tracking_template_present, expansion_status, association_status, observed_url_clicks, observed_url_cost, attribution_method, window_start/end.
  Strip personal query parameters; unresolved many-to-many destination allocation remains unknown rather than duplicating entity spend.
- `export/external/page_speed_results.csv`: url_id/device_class/source_kind/run_id grain, from client-supplied CrUX/RUM or authorized lab tests.
  Columns: tested_at, field_window_start/end, source_name, page_or_origin_scope, browser_version, network_profile, cpu_profile, cache_state, location_class, navigation_type, consent_scenario, sample_size, percentile, lcp_ms, inp_ms, cls, ttfb_ms, lab_tbt_ms, measurement_status, source_reference.
  Field evidence normally covers its stated rolling window; retain lab runs separately. Unsupported metrics remain null, not zero.
- Optional performance-to-business comparisons use mature matched device/URL cohorts and skill 071 reconciliation; no speed-derived uplift estimate without a controlled model.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Resolve destinations from ads, keyword overrides, mobile URLs, assets, and observed expansion evidence. Do not spread an ad's full spend across every possible URL.
2. Prioritize by observed URL traffic; where allocation is ambiguous use entity exposure labeled unallocated. Below Average landing-page experience only motivates testing, not a speed diagnosis.
3. Separate field and lab evidence, page and origin scope, device classes, and cache/network conditions. A Lighthouse score is not a measured conversion effect.
4. Assess field p75 LCP, INP, and CLS against [Core Web Vitals guidance](https://web.dev/articles/vitals): good LCP <=2.5 s, INP <=200 ms, CLS <=0.1; poor LCP >4 s, INP >500 ms, CLS >0.25.
5. Lab LCP/TBT can guide investigation but cannot establish field p75 INP or population experience. Repeat variable lab runs under comparable conditions before prioritizing.
6. Assign measured bottlenecks to engineering with source, conditions, and URL scope; do not claim a universal official three-second page-load requirement.
7. Treat inability to render as a functional issue requiring 079 evidence, not an automatic critical speed score.
8. If no measurements exist, provide the scoped URL/device/condition testing request and mark speed unassessed; no fabricated test result.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Independent functional evidence confirms material inability to access/complete the intended destination | Critical |
| Valid field data exceeds sourced good/poor Core Web Vitals boundaries on a relevant destination | Warning |
| Repeatable lab bottleneck warrants investigation, population impact unknown | Warning |
| Below Average LP rating, unallocated exposure, missing tests, or origin-only evidence | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Distinguish measured speed findings from URLs awaiting tests; include field/lab provenance, device, percentile, and population scope.
- Provide engineering investigation requests and attributable exposure, never guaranteed conversion gains.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
