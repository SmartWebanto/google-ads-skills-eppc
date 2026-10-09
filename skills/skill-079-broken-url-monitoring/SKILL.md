---
name: skill-079-broken-url-monitoring
description: "Assess destination availability from timestamped HTTP and rendered-page evidence with bounded exposure."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-034-ad-copy-landing-page-consistency, skill-069-landing-page-experience-assessment, skill-078-landing-page-speed, skill-125-landing-page-health-check-automation, skill-141-landing-page-policy-compliance, skill-110-conversion-tracking-breakage]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 079: Broken Destination Evidence

## Purpose

Assess destination availability from timestamped HTTP and rendered-page evidence with bounded exposure.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Active ad, keyword-override, and asset destinations; current failures do not establish historical wasted spend.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `ads`, `keywords`, `assets`, `ad_metrics`, `keyword_metrics`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/destination_map.csv`: use skill 078's exact entity/url mapping schema, including keyword overrides, mobile URLs, asset associations, and unresolved allocation.
- `export/external/url_health_checks.csv`: url_id/check_id/attempt grain, from authorized client HTTP/browser monitoring for the stated current or historical window.
  Columns: checked_at, method, device_class, browser_class, location_class, consent_scenario, initial_status, redirect_chain_statuses, redirect_chain_sanitized_urls, final_url_sanitized, final_status, tls_error, timeout_ms, rendered_success, expected_content_present, conversion_path_available, bot_challenge_observed, error_class, source_reference.
  Use sanitized URLs and synthetic sessions; no session tokens, form submissions, or private authenticated content.
- Optional `export/external/url_incident_windows.csv`: url_id/incident_id grain, from monitoring and incident owner.
  Columns: confirmed_start, confirmed_end, confidence, affected_device_location_scope, affected_clicks, affected_cost, cost_allocation_method, timezone, owner; only measured overlap may support incident exposure.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Resolve effective ad, mobile, keyword-override, and sitelink destinations by IDs and supported override rules. Asset existence is not proof of active serving association.
2. Deduplicate equivalent sanitized URLs without stripping meaningful routing parameters; keep unresolved destinations and expansion coverage explicit.
3. Evaluate complete redirect chains and rendered outcomes. HEAD failure alone may not reflect GET/browser behavior; a 200 page can be a soft 404 or broken purchase path.
4. Distinguish persistent customer-facing failure from transient errors, bot challenge, geo restriction, authorization, and test-environment issues. Request repeat browser evidence where necessary.
5. Review redirects for functional correctness and tracking preservation. A deliberate 301 is not inherently wrong; updating directly may break attribution, locale, or required routing.
6. Check HTTP-to-HTTPS behavior and TLS, not the initial scheme alone. Do not disable tracking templates or remove redirects without owner review.
7. Link cost only to measured affected URL/time/device scope. Current status cannot label all monthly entity spend wasted, and a broken page does not prove a 100% bounce rate.
8. Propose urgent destination-owner review for confirmed material live failures; do not edit, pause, or replace URLs automatically.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Reproducible customer-facing failure blocks a materially exposed live destination or conversion path | Critical |
| Confirmed intermittent availability, redirect, or TLS problem with uncertain material impact | Warning |
| More than three redirect hops with measured avoidable overhead warrants review; heuristic only | Warning |
| Single bot/HEAD failure, expected redirect, unknown history, or untested destination | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include entity/url IDs, check timestamps, redirect/render outcomes, confirmed incident window, and evidence coverage.
- Label related spend as current/historical exposure with allocation limits, not guaranteed waste or savings.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
