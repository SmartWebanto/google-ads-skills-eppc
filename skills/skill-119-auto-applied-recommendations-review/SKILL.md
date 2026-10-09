---
name: skill-119-auto-applied-recommendations-review
description: "Audit actual subscriptions and changes against authorization and outcomes, not pending recommendations."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 119: Auto-Applied Recommendation Governance

## Purpose

Audit actual subscriptions and changes against authorization and outcomes, not pending recommendations.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Accounts with current configuration evidence; count history only within complete dated coverage.

**Required inputs:**
- Base `export/` tables: account, campaigns, bidding_strategies, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/auto_apply_subscriptions.csv`: account_id/recommendation_type/snapshot_at grain; subscribed (true/false/unknown), scope, enabled_at_if_known, source_screen; current Ads auto-apply settings, all categories.
- `export/custom/auto_apply_changes.csv`: one row per account_id/change_id/field_path: occurred_at, resource_name, campaign_id, budget_id, strategy_id, operation, client_type, actor_id, old_value, new_value, approval_ref; Ads change-history export for declared 30-day window, partitioned without truncation, with retention/coverage notes.
- `export/external/auto_apply_authorizations.csv`: approval_ref/type/scope_id grain; allowed_fields, allowed_value_ranges, effective_from/to, owner, status, review_due, reviewed_at; client approvals covering subscriptions/history.
- Optional `export/custom/auto_apply_outcomes.csv`: one row per account_id/campaign_id/date: budget_id, strategy_id, goal_id, impressions, clicks, cost, conversions, conversion_value, conversion_date_basis, maturity; Ads UI daily report, account timezone, complete dates including historical inactive campaigns and coverage/suppression notes; matched mature pre/post windows.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Inventory subscriptions separately from pending recommendations. Missing settings or no changes cannot prove disabled status.

2. Distinguish exported subscription-applied and manually accepted recommendation sources; unknown attribution stays unknown. Count distinct change IDs, not field rows.

3. Compare scope and old/new values with authorization. Keyword or bidding changes merit context, not automatic disable or Critical.

4. Report coverage boundaries; a retained subset of 30 days yields a covered-window or lower-bound count, never a complete 30-day count.

5. Use dated outcome comparisons descriptively, controlling lag and concurrent changes. A restriction or reversal proposal needs current values, subsequent edits, intended benefit and client owner approval.

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
| Confirmed unauthorized change causing material delivery or safety failure | Critical |
| Confirmed scope/value outside documented authorization | Warning |
| Unknown settings, incomplete logs or pending recommendations only | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Subscription/approval matrix and distinct change counts for exact windows.
- Changed-field ledger with old/new/current values and contextual request-only proposals.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
