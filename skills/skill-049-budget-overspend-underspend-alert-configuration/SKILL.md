---
name: skill-049-budget-overspend-underspend-alert-configuration
description: "Propose auditable budget monitoring rules from complete daily spend, approved caps and actual alert histories."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 049: Budget Pacing Alert Proposal

## Purpose

Design local review-only alerts for financial-plan risk without confusing normal daily overdelivery with cap breaches or transmitting account data to third parties.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Approved account/campaign/budget-pool scopes with a declared spend basis, timezone and monitoring owner.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/budgets`: complete pool membership, including currently paused/removed campaigns with historical spend.
- `export/custom/budget_alert_daily.csv`: one account_id/campaign_id/date row, budget_id, cost, billed_cost_if_available, complete_day, source_ref; all MTD dates and at least thirty prior complete days for baselines.
- `export/custom/budget_history.csv`: one account_id/budget_id/effective_from/to row, amount, amount_unit, shared_flag, member_campaign_ids, source_ref; full analysis window.
- `export/external/budget_alert_plan.csv`: one account_id/scope_id/date row, scope_type, approved_month_total, planned_spend, cap_or_target, spend_basis, timezone, warning_lower/upper_ratio, owner, approved_at and source_ref; client plan. Suggested 0.85/1.15 are optional triage defaults, never approvals.
- `export/custom/budget_alert_history.csv`: one account_id/scope_id/rule_id/evaluated_at row, rule_version, condition, observed_value, threshold, triggered, notification_status, resolved_at and source_ref; complete prior thirty-day local/Ads monitoring logs.
- `export/external/budget_alert_rules.csv`: one account_id/scope_id/rule_id/version row, enabled, cadence/timezone, lookback, data_lag, condition, severity, dedupe_key, cooldown, owner_role, approved_state and source_ref; supplied current local rule inventory.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without plan no cap/pacing alert; without full MTD no monthly status. Missing logs mean alert history unknown, not thirty days without alerts.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Resolve monitored scope, explicit approved cap/target and cost-versus-billed basis. Deduplicate overlapping account/pool/campaign scopes before aggregating exposure.

2. Reconstruct complete-day spend and dated shared budgets including paused entities. A campaign daily amount is an average delivery budget, not a universal hard daily cap.

3. Compute expected MTD=sum(dated planned_spend), actual MTD and ratio=actual/expected for positive expected. Reuse 044 forecast definitions; never substitute current daily budget×calendar days for an approved cap.

4. Evaluate one consistent pacing rule: below approved lower or above upper ratio; optional proposed defaults 0.85/1.15 remain heuristics. Forecast cap risk is distinct from an actual cap breach.

5. Compare daily spend with comparable weekday complete-day baselines only with sufficient dated history. A proposed 30% change screen requires positive baseline and documented seasonality/change exclusions; no implied fraud or automatic escalation.

6. Use logs for first/last trigger, duration, notification delivery and resolution; a first observed trigger only lower-bounds duration. Distinguish historically triggered from currently active incidents.

7. Draft a rule proposal with scope/IDs, condition, sample/window, lag handling, timezone, cadence, dedupe/cooldown, recipient role, escalation and review owner. Rules only notify/propose; they do not pause or alter budgets.

8. Evaluate proposed conditions against supplied historical rows without activating rules, disclosing missing days and false-positive risks. Do not configure rules, send alerts or offer third-party data transfer; request approval for any later implementation.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Verified actual matched-basis spend materially exceeds an explicit approved hard cap | Critical |
| Pacing outside approved bounds or material unexplained spend anomaly | Warning |
| Forecast risk, daily overdelivery alone, absent monitoring or missing history | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Current evidence-backed conditions separated from proposed rule definitions and unverified coverage.
- Rule configuration proposal with exact scope/values, owner, acknowledgement and deduplication; no external side effects.
