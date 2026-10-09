---
name: skill-009-account-defaults-audit
description: "Review account tracking, goal selection, account links and auto-apply settings against approved measurement and operating requirements."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 009: Account Defaults and Governance

## Purpose

Review account tracking, goal selection, account links and auto-apply settings against approved measurement and operating requirements.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Account/campaign defaults only where integrations and controls are relevant to the stated business objective.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/account`, `export/campaigns`, `export/conversion_actions`, `export/bidding_strategies`.
- `export/custom/campaign_goal_selection.csv`: account_id, campaign_id, goal_id, custom_goal_id,
  conversion_action_id, selected_for_bidding, selection_source, snapshot_date; one action/campaign from Goals UI.
- `export/external/account_controls.csv`: one account/control/link/snapshot row from supplied Admin/Goals UI review;
  account_id, control_type, control_name, linked_account_id, observed_value, expected_value,
  authorization_ref, dependency, observed_failure, evidence_ref, source, snapshot_date.
  Include exact displayed auto-apply options, links/status, auto-tagging and approved owners; sanitize private identifiers.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without current UI evidence leave auto-apply/link status unknown; without campaign/custom goals do not infer bidding selection from primary flags alone.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Inventory auto-tagging and measurement status, respecting the intended analytics integration.
   Disabled auto-tagging is a risk only where the chosen measurement implementation depends on it.

3. Resolve effective campaign goal/action selection, including custom goals and account-default inheritance.
   A secondary action intentionally included in a custom goal can be used for bidding; do not call that contradictory.

4. Compare counting, value and attribution configuration with the business event being measured.
   Neither last-click nor absence of a preferred integration is automatically a defect.

5. Review exact auto-apply option labels and observed opt-in states from current supplied UI evidence.
   Do not invent a budget-increase option, claim API coverage, or assume unknown options are enabled.

6. Match auto-apply states to authorized operating policy; distinguish approved automation from policy mismatch.
   Propose owner review, not immediate disabling or account changes.

7. Review linked-account presence/status only for required integrations and approved target IDs.
   GA4, Merchant Center, YouTube and Search Console are not mandatory for every account.

8. Escalate directly evidenced material measurement failure; otherwise state risk or missing evidence.
   Tracking specialists own detailed action diagnostics; this recipe owns defaults and dependency inventory.

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
| Directly evidenced material failure of required measurement due to account/default configuration | Critical |
| Observed link/auto-apply/default conflicts with approved dependency or authority | Warning |
| Optional integration absent, intentional custom-goal selection or missing evidence | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Report actual/expected settings and goal-selection provenance; no legal or tracking-completeness certification.
