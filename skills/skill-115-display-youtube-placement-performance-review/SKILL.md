---
name: skill-115-display-youtube-placement-performance-review
description: "Review website, YouTube and app placements plus inherited exclusion governance without blanket blocking or fraud claims."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: analyst
  data_source: external
  merged_from: [skill-114-account-level-placement-exclusions, skill-116-mobile-app-placement-exclusion]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 115: Placement Performance and Exclusion Governance

## Purpose

Review website, YouTube and app placements plus inherited exclusion governance without blanket blocking or fraud claims.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Placement-reporting campaigns only where the subtype supports the proposed control; incomplete PMax reporting is partial coverage.

**Required inputs:**
- Base `export/` tables: account, campaigns, campaign_metrics, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/placement_daily.csv`: account_id/campaign_id/ad_group_id/date/placement_id/format grain; placement_type, URL_or_app_id, app_category_id, category_source, network, objective, impressions, clicks, cost, conversions, conversion_value; complete mature 30-day Ads report including websites AND apps, with suppressed coverage stated.
- `export/custom/placement_video_metrics.csv`: same key where supported; video_views, native_view_rate, denominator_name, denominator_count, eligible_video_impressions, measurable_impressions, viewable_impressions, measurement_definition; same-window Ads format report. Preserve campaign/format grain if placement metrics unavailable.
- `export/custom/placement_controls.csv`: account_id/scope_type/scope_id/control_id/snapshot_at grain; control_type, placement_or_category_id, enabled, included_or_excluded, inherited_from, supported_subtypes, source_screen; current Ads content-suitability/exclusion settings including inherited controls.
- `export/external/placement_policy.csv`: policy_id/placement_or_category_id grain; campaign_scope, suitability_rationale, evidence_ref, approved_by, valid_from/to; current client policy and local content-review evidence.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Reconcile reported placement cost to campaign totals, preserving unknown inventory. Separate formats and objectives; app categories require provenance.

2. CTR = clicks/impressions. Video view rate = views/documented format-specific eligible impressions or the native reported rate, NEVER CTR. Active View viewability = viewable/measurable impressions. Do not substitute all impressions for a different view-rate denominator; non-view-based formats are not applicable.

3. Compare apps and websites only within comparable campaign/format/goals and mature samples on both sides. Use CPA/ROAS or qualified outcomes, not CVR alone; games or children categories do not prove waste.

4. Screen zero-conversion placements at {{spend_floor}} after tracking, lag and relevance review. CTR anomalies are not fraud; route billing-linked concerns to skill-118. Historical exposure is not recoverable savings.

5. Resolve account/campaign/list inheritance against approved suitability restrictions. No account-level exclusions is not a defect. Never use the obsolete all-app domain shortcut; propose only documented current app-ID/category controls and supported scope.

6. For each candidate provide narrow scope, useful coverage at risk, existing overlap, rationale, approval owner and monitoring plan; account-wide scope needs cross-campaign suitability evidence.

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
| Confirmed live material exposure contrary to an approved safety restriction | Critical |
| Mature zero-conversion spend above {{spend_floor}} after context review | Warning |
| No exclusions, CTR anomaly alone or incomplete view evidence | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Placement ledger with IDs, format, sample, spend, goal outcomes, CTR, native view rate and exact denominator, viewability and coverage.
- App-versus-website cohorts and category provenance; governance matrix with inheritance, policy evidence and narrow request-only proposals.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
