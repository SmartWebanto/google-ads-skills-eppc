---
name: skill-131-change-history-monitoring
description: "Track who changed which fields and compare exact values with authorization; incomplete logs cannot establish complete activity."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: competitive
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 131: Change History Governance

## Purpose

Track who changed which fields and compare exact values with authorization; incomplete logs cannot establish complete activity.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Accounts with dated change logs and explicit resource-to-entity mappings.

**Required inputs:**
- Base `export/` tables: account, campaigns, budgets, bidding_strategies, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/change_history_fields.csv`: one row per account_id/change_id/field_path: occurred_at, resource_name, campaign_id, budget_id, strategy_id, operation, client_type, actor_id, old_value, new_value, approval_ref; Ads change-history export for declared 30-day window, partitioned without truncation, with retention/coverage notes.
- `export/external/change_authorizations.csv`: approval_ref/resource_scope/field grain; permitted_actor_ids, permitted_source, old_value_constraint, new_value_constraint, valid_from/to, documented_at, owner, review_status; client change register and known-source inventory for same dates.
- Optional `export/custom/change_outcomes.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; mature pre/post windows around a change for descriptive impact review.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Check exact retention and completeness; export partitioned intervals/resources when needed rather than an arbitrary cap. Count distinct change IDs; field-row counts are separate.

2. Map resource names to stable campaign/budget/strategy IDs. Shared budget changes affect all contemporaneous members; do not duplicate their monetary delta.

3. Compute new-old values only for same-unit supported fields. Separate add/remove/update, unknown values and actor attribution; client type alone may not identify the exact script.

4. Join scope, time and allowed values to authorization. No documentation is unknown authorization, not confirmed unauthorized behavior; off-hours or high volume alone is not a defect.

5. Compare mature outcomes only if supplied and label associations non-causal. Any reversal proposal must inspect current state and subsequent edits and preserve approved changes; route subscription details to skill-119.

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
| Confirmed unauthorized material delivery or safety failure | Critical |
| Changed values violate explicit authorization or required review is overdue | Warning |
| Unknown source, missing authorization or partial log | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Unique-event summary with coverage; full field ledger including resource IDs, old/new values, source and authorization.
- Shared-budget affected members and conditional review proposals, never automatic reversions.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
