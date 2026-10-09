---
name: skill-161-automation-layering-strategy-audit
description: "Evaluate evidence-backed risk coverage and conflicting automation; scripts and automated pausing are not mandatory."
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
# Skill 161: Automation Layering and Oversight Review

## Purpose

Evaluate evidence-backed risk coverage and conflicting automation; scripts and automated pausing are not mandatory.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Accounts with complete rule/script/tool/manual oversight inventory and defined business risks.

**Required inputs:**
- Base `export/` tables: account, campaigns, budgets, bidding_strategies, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/automation_inventory.csv`: account_id/automation_id/snapshot_at grain; type, enabled, owner, entity_scope_ids, read_or_write_fields, conditions, thresholds, cadence, timezone, approval_ref, review_due, fallback; current Ads rule/script exports and client tool/manual-review records, no credentials.
- `export/external/automation_runs.csv`: automation_id/run_id grain; started_at, ended_at, scheduled_at, result, evaluated_scope_ids, affected_scope_ids, changed_fields, old/new_values, alert_delivery_status, error_summary, evidence_ref; client local execution/review logs for 30 complete days.
- `export/external/automation_risks.csv`: risk_id/entity_scope grain; risk_description, approved_spend_cap_or_service_limit, required_control, acceptable_manual_alternative, required_cadence, responsible_owner, approval_ref; current client risk/control matrix.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Inventory actual automated and human coverage. A missing script does not prove missing capability if native tools or accountable manual review cover the risk.

2. Define denominator as eligible risk/entity pairs in the approved risk matrix, not all campaigns or tool counts. Coverage = pairs with evidenced functioning accepted controls / eligible pairs; zero denominator is not applicable.

3. Join run logs to schedules and scope; a configured rule is not proven operational. Report unknown runs separately from observed failures and distinguish alert generation from delivered notification.

4. Detect write conflicts only where fields, entity scope and trigger times overlap and actions disagree or undo each other. Similar names/functionality alone are not harmful duplication.

5. Distinguish normal daily overdelivery from an approved monthly/client cap breach; 80% of daily budget is not overspend.

6. Propose risk-prioritized missing/revised oversight with owner, cadence, guardrails and fallback. No mandatory scripts, no installation, no rule execution, no notifications or third-party data transfers.

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
| Confirmed control conflict/failure causing material spending or safety breach | Critical |
| Observed failed/overdue required control or incompatible overlapping writes | Warning |
| Unknown run evidence, no optional script or adequate manual alternative | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Automation/run/risk matrix and transparent coverage numerator/denominator with unknowns.
- Field/time/entity conflict pairs and request-only governance recommendations with owner and fallback.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
