---
name: skill-130-campaign-enable-pause-scheduling
description: "Compare actual campaign status and schedules with approved event plans; produce request-only start/stop specifications."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: competitive
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 130: Campaign Scheduling Proposals

## Purpose

Compare actual campaign status and schedules with approved event plans; produce request-only start/stop specifications.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Time-bound campaigns identified by client event intent, not campaign names alone.

**Required inputs:**
- Base `export/` tables: account, campaigns, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/campaign_event_plan.csv`: one row per event_id/campaign_id: name, start_at, end_at, timezone, objective, offer, expected_cvr_change, rationale, owner, approval_status, normal_baseline_dates; client calendar snapshot covering relevant past events and next 60 days; add campaign_expected_status, intentional_pause_reason, replacement_campaign_id, replacement_required, start_stop_precision.
- `export/custom/campaign_schedule_rules.csv`: account_id/campaign_id/rule_id/snapshot_at grain; enabled, action, scheduled_at, timezone, recurrence, current_start/end_dates, last_run_at, last_result, source_screen; Ads campaign settings/rules covering past 30 and next 60 days.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Join event IDs to explicit campaign IDs; preserve intentional stock, margin, compliance or capacity pauses.

2. Compare intended timezone-specific windows against campaign date settings and exact-time rules. Date fields do not prove hour-level scheduling.

3. Check whether an expired campaign actually served after the approved event; enabled status alone is not proof of delivery or stale-offer harm.

4. If a replacement is required, verify its approved readiness; no replacement is not a gap for a completed one-off event.

5. Draft explicit entity IDs, desired state, local time/UTC offset, recurrence, prerequisites, manual override, verification time and owner. Do not enable, pause or create rules.

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
| Confirmed material live delivery of an invalid time-bound offer | Critical |
| Configured schedule contradicts approved event plan | Warning |
| Intentional in-season pause, no required replacement or missing event evidence | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Actual-versus-intended event schedule, exact time basis and intentional exceptions.
- Request-only rule specification with replacement dependencies and client owner.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
