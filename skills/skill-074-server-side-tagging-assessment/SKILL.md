---
name: skill-074-server-side-tagging-assessment
description: "Evaluate server-side tagging against measured needs, alternatives, operational cost, and technical readiness."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: external
  related: [skill-071-conversion-tracking-accuracy, skill-075-consent-mode-v2, skill-078-landing-page-speed]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
---
# Skill 074: Server-Side Tagging Assessment

## Purpose

Evaluate server-side tagging against measured needs, alternatives, operational cost, and technical readiness.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** Accounts considering or operating server-side tagging; client-side-only is a valid architecture and not evidence of noncompliance.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `conversion_actions`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `export/external/tagging_architecture.csv`: account_id/site_id/component_id grain, from sanitized infrastructure inventory at current snapshot.
  Columns: deployment_version, client_or_server, event_destinations, hosting_region, endpoint_domain, consent_forwarding_design, retention_policy_reference, access_control_status, monitoring_owner, operational_owner, monthly_cost, migration_effort_estimate, currency.
- `export/external/tagging_measurement_trials.csv`: trial_id/site_id/scenario/variant/device_class/run_id grain, from authorized synthetic or aggregate comparative measurements.
  Columns: tested_at, tag_set, traffic_assignment_method, browser_class, network_profile, cache_state, eligible_events, observed_events, excluded_events_reason, main_thread_ms, lcp_ms, sample_size, consent_scope, confounders, source_reference.
  Compare equivalent payloads and permitted events; no bypass of consent or blockers. Without a controlled counterfactual, event differences are descriptive only.
- `export/external/tagging_decision_requirements.csv`: site_id/requirement_id grain, from engineering/business/privacy owners for the planned window.
  Columns: requirement, success_metric, accepted_threshold, alternative_design, operating_capacity, approved_policy_reference, owner, decision_deadline; no credentials or infrastructure access required.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Inventory current client/server paths, destinations, owners, and requirements; conversion origin alone cannot identify infrastructure.
2. Check whether a current problem is directly measured: event delivery, main-thread cost, reliability, or destination governance. High traffic alone does not require migration.
3. Compare trials only under equivalent device/network/cache/tag/consent conditions. Missing events cannot be assigned to ad blockers without a defensible measured counterfactual.
4. Compare client-side optimization, hybrid, server-side, and no-change options against explicit success criteria.
5. Review capacity for endpoint security, consent propagation, monitoring, retention, deployment rollback, and ongoing ownership using sanitized evidence.
6. Treat privacy/legal requirements as owner-supplied constraints, not a certification task. Server-side hosting does not inherently confer compliance or permission to collect denied data.
7. Calculate operating cost only from supplied costs. Any benefit/ROI scenario must name assignment method, measured effect, uncertainty, horizon, and assumptions; otherwise omit it.
8. Propose a scoped trial or no-change decision. Do not prescribe migration, guaranteed recovered conversions, or estimates of blocker loss from an Ads export.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Direct evidence confirms material current measurement or technical-policy failure | Critical |
| Chosen architecture has documented reliability, consent-propagation, or ownership risk | Warning |
| Measured trial supports evaluation of an alternative | Info |
| No server-side deployment, high traffic alone, or unmeasured claimed benefits | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Provide current/alternative design comparison, measured needs, readiness gaps, costs, and decision owner.
- Distinguish verified measurement from hypothetical ROI and explicitly retain the no-change option.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
