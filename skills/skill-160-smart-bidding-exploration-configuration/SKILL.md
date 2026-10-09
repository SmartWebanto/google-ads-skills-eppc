---
name: skill-160-smart-bidding-exploration-configuration
description: "Review actual ROAS-tolerance settings and propose constrained experiments, not mandatory exploration adoption."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: platform
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 160: Smart Bidding Exploration Configuration Review

## Purpose

Review actual ROAS-tolerance settings and propose constrained experiments, not mandatory exploration adoption.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Search campaigns/portfolios using supported target ROAS configuration, broad targeting eligibility and current feature availability; not a general tCPA/Maximize Conversions feature.

**Required inputs:**
- Base `export/` tables: account, campaigns, bidding_strategies, budgets, keywords, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/exploration_config.csv`: account_id/strategy_id/campaign_id/snapshot_at grain; availability, enabled, target_roas, configured_roas_tolerance_percent, effective_target_if_reported, targeting_eligibility, budget_limited, portfolio_members, enabled_at, source_screen, current_help_url; actual Ads exploration/strategy settings.
- `export/external/exploration_risk.csv`: strategy_id/campaign_id/effective_range grain; minimum_acceptable_roas, approved_budget_cap, value_quality_evidence_ref, business_goal, maximum_drawdown, owner, approval_status; current client economic policy.
- Optional `export/custom/exploration_experiment_daily.csv`: account_id/experiment_id/arm_id/strategy_id/campaign_id/date grain; assignment_method, traffic_split, start/end_dates, changed_setting, cost, conversions, conversion_value, qualified_value, goal_id, separately_reported_traffic_label; mature Ads experiment results. Omit traffic split claims if exploration/core labels are not actually reported.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Check actual Search/tROAS availability and targeting eligibility from current settings. Broad targeting may be broad keywords, DSA or AI Max; no forced 100% broad adoption or conversion-count threshold.

2. Record the supported numeric ROAS tolerance rather than invented low/balanced/high intensity. Current guidance allows 5-30%; verify current UI range before any proposal.

3. Planning effective target = base target ROAS*(1-tolerance fraction), labeled approximate and distinct from realized ROAS. Compare against the client profitability floor, value quality and cap.

4. Check budget constraint status; guidance says exploration mechanism is disabled when budget-limited. Portfolio scope needs all members and shared risk review.

5. Do not infer separate exploration ROI from aggregate campaign metrics or call new audiences incremental. Pre/post is descriptive; evaluate randomized comparable experiment arms when available.

6. Propose an optional tolerance test with approved economic floor/cap, assignment, primary value metric, lag-aware sample plan, stop/recovery criteria and owner. No change remains valid; never enable or claim guaranteed uplift.

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
| Confirmed material live spending/safety failure against an approved guardrail | Critical |
| Actual configured effective-target tolerance conflicts with documented risk floor | Warning |
| Disabled exploration, unsupported configuration or missing separate outcomes | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Strategy/campaign/portfolio settings table with numeric tolerance, eligibility, effective-target arithmetic and risk floor.
- Request-only controlled experiment or no-change rationale, no fabricated core/exploration outcome split.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.

[About Smart Bidding Exploration](https://support.google.com/google-ads/answer/15489627?hl=en) and [setup](https://support.google.com/google-ads/answer/16294612?hl=en).
