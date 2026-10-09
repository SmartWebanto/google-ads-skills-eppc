---
name: skill-032-ad-copy-ab-testing
description: "Separate RSA serving inventory from randomized experiment evidence and evaluate pre-specified creative tests."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 032: Controlled Ad Copy Experiment Review

## Purpose

Audit or design a controlled creative experiment without calling ordinary optimized RSA serving an A/B test. Inventory all ad groups, including those with no RSA, without declaring that zero RSAs always means zero eligible ads.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Search creative hypotheses with an eligible experiment mechanism; observational ad reports remain descriptive.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/ad_metrics`: complete ad-group spine, all ad types/statuses and mature ad-level outcomes.
- `export/external/creative_experiment_plan.csv`: one experiment_id row, account_id, hypothesis, eligible_scope_ids, control/treatment_definition, assignment_unit, allocation_method, planned_split, start/end_at, primary_metric/denominator, MDE, alpha, power, target_sample_per_arm, sample_calculation_ref, sequential_or_fixed_method, guardrails, stopping_rules, owner and approval_state.
- `export/custom/creative_experiment_results.csv`: one experiment_id/arm_id/date row, campaign/ad_group/ad IDs, assigned_units, exposed_units, impressions, clicks, cost, conversions, value, variance_or_inference_report_ref, exclusions, source_ref and lag_cutoff; full test dates from Ads experiment reports.
- `export/custom/creative_experiment_changes.csv`: one experiment_id/change_id row, changed_at, entity_id, field, old/new_value and reason; configuration/history evidence over the test dates.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without assignment and plan evidence, label analysis observational. Without variance or valid inference results do not fabricate CPA/ROAS confidence intervals or winners.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Left-join all in-scope ad groups to every ad type; report zero/one/multiple RSA counts descriptively. Delegate confirmed absence of any eligible ad to 037.

2. Distinguish documented randomized experiments from normal ad rotation/optimization. Multiple RSAs and equal observed impressions do not establish random assignment; non-random assignments need a separate causal design.

3. Verify a single pre-specified contrast, randomization unit, persistent assignment where required, traffic split, dates, primary business metric, MDE, power calculation and safety guardrails. No test is mandatory solely because traffic is high.

4. Check arm settings, eligibility, geography, bids, goals and landing pages for unintended differences using change logs. Budget interference, carryover and simultaneous edits can invalidate interpretation.

5. Compare assigned-unit counts with the planned split using the pre-specified sample-ratio-mismatch method; impressions are not assignment counts. Investigate mismatch before outcome inference.

6. Use the registered inference method and actual assignment unit: binomial methods only for binary outcomes with appropriate independent denominators; fractional attributed conversions and CPA/ROAS need valid variance-aware experiment reports or cluster-aware inference, not a naive proportion test.

7. Require planned duration/sample and conversion maturity in both arms; fixed-horizon tests cannot stop on repeated nominal significance. Account for multiple variants/metrics as pre-specified; report effect estimate, interval and guardrail outcome.

8. Recommend adoption only as an approval request when statistical evidence, practical value and guardrails align. Otherwise return inconclusive/invalid and a repair or new-test proposal; never promise uplift from RSA counts.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Documented randomization mismatch, uncontrolled edits or broken primary metric in an active test | Warning |
| Evidence supports business-relevant effect and guardrails; adoption opportunity | Info |
| No formal test, single RSA, underpowered result or unavailable valid inference | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Inventory and experiment status kept separate; experiment IDs, design, samples, interval and uncertainty.
- Decision proposal stating winner-supported, inconclusive or invalid, the exact inference method and owner approval required.

Sources: [RSA recommendations are not experimental randomization](https://support.google.com/google-ads/answer/7684791).
