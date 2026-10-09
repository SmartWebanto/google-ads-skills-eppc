---
name: skill-125-landing-page-health-check-automation
description: "Review supplied timestamped URL diagnostics and propose monitoring without assigning month-long spend to a snapshot failure."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: operational
  data_source: external
  related: [skill-034-ad-copy-landing-page-consistency, skill-069-landing-page-experience-assessment, skill-078-landing-page-speed, skill-079-broken-url-monitoring, skill-141-landing-page-policy-compliance]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence and controls; gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | bounded outage exposure"
---
# Skill 125: Landing Page Health Monitoring Proposals

## Purpose

Review supplied timestamped URL diagnostics and propose monitoring without assigning month-long spend to a snapshot failure.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Active destinations with known ad/keyword associations; technical tests only for supplied local evidence.

**Required inputs:**
- Base `export/` tables: account, campaigns, ads, keywords, ad_metrics, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/url_health.csv`: test_id/URL/device/checked_at grain; requested_url, resolved_url, redirect_chain, http_status, tls_valid, tls_error, load_metric_name, load_value_ms, test_region, user_agent, mobile_task_result, evidence_ref; client-provided diagnostics covering incident and recovery timestamps.
- `export/custom/url_daily.csv`: account_id/campaign_id/ad_group_id/ad_or_keyword_id/URL/date grain; clicks, cost, conversions, device; Ads destination metrics covering reported incident dates and 30-day prioritization, attribution/coverage stated.
- Optional `export/custom/url_interval.csv`: the same entity/URL/device key plus interval_start,
  interval_end, clicks, cost, conversions, timezone, source and coverage; supplied finer-grained
  destination report. Its bucket boundaries, not assumed uniform hourly delivery, govern attribution.
- `export/external/url_monitor_policy.csv`: monitor_id/URL_scope grain; test_cadence, critical_customer_task, expected_redirects, performance_limit_ms, owner, approval_status, recovery_check; client current monitoring requirements.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Inventory exact destination associations, including keyword overrides; preserve query strings that affect behavior and do not merge distinct checkout flows.

2. Read dated HTTP/TLS/redirect/mobile results; distinguish reproducible user-blocking failure from bot-denial or one test-region issue. A URL inventory cannot prove health.

3. Compare redirects against required tracking and performance against the named metric and client limit; avoid universal speed/policy or Quality Score claims.

4. Prioritize by observed serving and clicks. Attribute incident cost only from metric buckets wholly
   within an independently evidenced failure interval, or finer-grained observations proving delivery
   during it. A daily bucket partly overlapping a five-minute outage is only an upper bound on potentially
   affected exposure, not incident-window cost. Discrete failed probes do not establish continuous outage.
   Label any prorating as a model with assumptions/uncertainty; keep 30-day prioritization exposure separate.

5. Draft alert-only checks with cadence, expected behavior, retries as a proposed confirmation policy, dedupe, recovery and technical owner. Existing destination diagnosis belongs to related URL-health skills; never pause ads or run external page tests here.

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
| Confirmed active destination failure materially blocks the intended customer task | Critical |
| Repeated test failure or performance violation against documented requirements | Warning |
| Missing diagnostics, uncertain outage duration or single unexplained probe | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- URL/entity/test ID matrix with exact timestamps, device, failure evidence and recovery status.
- Historical exposure, evidenced incident-window cost and partially overlapping upper bounds, kept distinct; request-only monitoring and repair handoff.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
