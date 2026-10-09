---
name: skill-010-campaign-priority-experiments
description: "Review Standard Shopping routing and experiment design using product eligibility, arm configuration and declared decision rules."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction; gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | explicit method-backed inference inputs"
---
# Skill 010: Shopping Priority and Experiment Structure

## Purpose

Review Standard Shopping routing and experiment design using product eligibility, arm configuration and declared decision rules.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Priority review applies to Standard Shopping, not PMax; experiments only where supplied platform type supports them.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`, `export/negative_keywords`, `export/shared_negative_lists`.
- `export/custom/shopping_routing.csv`: one account/campaign/product/market/snapshot row from Shopping settings/product report;
  account_id, campaign_id, merchant_id, product_id, feed_label, language, target_country, priority,
  included, eligible, geo_scope, schedule, budget_id, snapshot_date; declare inventory completeness.
- `export/external/experiment_design.csv`: one experiment/arm effective-window row from approved design and UI;
  experiment_id, arm_id, campaign_id, hypothesis, change_bundle, planned_split, allocation_unit,
  primary_metric, guardrails, minimum_detectable_effect, sample_plan, stopping_rule, planned_start,
  planned_end, owner, source, captured_at, estimand, analysis_unit, statistical_method, maturity_rule.
- `export/custom/experiment_daily.csv`: experiment_id, arm_id, campaign_id, date, assigned_units,
  impressions, clicks, cost, conversions, conversion_value, goal_scope; one arm/day from experiment report.
- For inference, `export/external/experiment_inference.csv`: one experiment/contrast/metric/analysis-window
  row from supplied platform experiment results or a documented analyst estimator; experiment_id,
  reference_arm_id, variant_arm_id, metric, estimand, analysis_unit, statistical_method, estimate,
  ci_lower, ci_upper, confidence_level, reference_sample, variant_sample, analyzed_start, analyzed_end,
  goal_scope, maturity_rule, source, extracted_at. Preserve method provenance and censoring.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without product eligibility skip routing conclusions. Without design or arm results assess available configuration only. Without method-backed inference retain descriptive outcomes/allocation checks but no winner.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Join product identities including merchant, feed label, language and market before testing overlap.
   Retain eligibility, targeting, schedule and budget context; equal priority alone is not a conflict.

3. Compare priority and effective negatives with approved query-routing intent.
   Higher priority does not universally require negatives; identical products can intentionally share priority.

4. Identify direct mismatches in intended eligible coverage without predicting auction winners from inventory.
   PMax coexistence cannot be diagnosed by Standard Shopping priority rules.

5. Map experiment arms to campaigns, effective dates and intended allocation unit.
   Unequal splits may be deliberate; compare realized assigned units to the design, not a universal 50/50 quota.

6. Check the documented hypothesis, change bundle, primary KPI, guardrails and stopping/sample plan.
   A bundled test can assess the bundle, not isolate each component.

7. Analyze mature arm outcomes descriptively from daily totals. Those totals alone do not identify
   assignment-unit variance/covariance for CPA/ROAS; never invent uncertainty from them.
   For inference, require the supplied contrast estimate/interval to match the design's arms, estimand,
   analysis unit, method, goals, maturity and stopping rule. Mismatch means inconclusive, not a winner.
   Do not treat click share as assignment share or repeatedly peek until a favorable result appears.

8. Age alone cannot establish validity or a winner; honor lag, sample plan and guardrails.
   Recommend an owner decision only with supported results; never auto-conclude an old experiment.

## Thresholds

Resolve [PARAMETERS.md](../_resources/PARAMETERS.md) and profile overrides before screening.
Numerical decision cutoffs below are triage heuristics, not platform requirements or causal proof.
Compare CTR only with {{min_impressions}} impressions and conversion rates with {{min_clicks}} clicks
on each side; CPA/ROAS comparisons require {{min_conversions}} mature conversions on each side.
Zero-conversion screening is an exception to the conversion-count gate, not permission to pause:
require working tracking, a mature comparable window, relevance review and {{spend_floor}}.
Do not divide by zero; absent targets use an applicable profile target, otherwise omit target comparisons.

| Condition | Severity |
|-----------|----------|
| Observed routing contradicts approved eligible-product strategy | Warning |
| Arm implementation or allocation materially contradicts the approved experiment design | Warning |
| Same priority, unequal planned split, short/long duration or incomplete results alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Separate product-overlap inventory from experimental evidence; include arm IDs, uncertainty and decision-rule status.
