---
name: skill-076-conversion-action-configuration
description: "Review counting, bidding goals, values, windows, and current attribution against business intent."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: tracking
  kind: analyst
  data_source: export
  related: [skill-070-conversion-tracking-completeness, skill-071-conversion-tracking-accuracy, skill-107-conversion-value-accuracy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTracking | evidence-led audit correction"
  merged_from: [skill-077-data-driven-attribution]
---
# Skill 076: Conversion Action Configuration and Attribution

## Purpose

Review counting, bidding goals, values, windows, and current attribution against business intent.
Recommendations are review requests only; do not change accounts, tags, uploads, or configuration.

## Data Requirements

**Applicability:** All supplied conversion actions and campaign goals; configuration recommendations depend on objective and current supported controls.

**Required inputs:**
- Base files in `export/`, following [DATA_CONTRACT](../_resources/DATA_CONTRACT.md): `account`, `campaigns`, `conversion_actions`, `campaign_metrics`, `bidding_strategies`.
- Use account timezone, currency, window, snapshot, completeness/filters, and conversion date basis.
- Client profile supplies business objectives, campaign objectives, sales cycle, and conversion/reporting lag where relevant.
- `conversion_actions` must include stable action and conversion-customer IDs, source/type, status, counting, primary_for_goal, include_in_conversions, value/default settings, attribution_model, and click-through window.
- `campaigns` must supply actual goal selection including custom goals, action memberships where available, objective, strategy_id, and bidding strategy type.
- Client profile supplies event/counting intent, value or count optimization objective, sales_cycle_days, conversion_lag_days, and rationale for attribution/window choices.
- If a required setting is absent, request a sanitized Ads settings export with the same account/action/campaign keys and snapshot; do not infer it from action names.
- Observed duplicates or revenue accuracy require skill 071 evidence; configuration alone cannot establish them.
- Optional attribution status requires the action-level current UI status and source timestamp; no click/conversion volume field is required to determine DDA eligibility.
- Supplemental files must record source, extraction timestamp, window start/end, timezone, filters, and completeness.
- Use sanitized settings and aggregate diagnostics; no emails, phones, addresses, cookies, click IDs, credentials, or user-level browsing histories.
- Business-event tokens must be synthetic or locally pseudonymized; never supply reversible mappings or hashed personal identifiers.

**Missing inputs:** Omitted fields are unknown, never false or disabled. Name missing files/columns and skip only dependent checks.
Do not call missing evidence a defect or full pass. An empty table proves absence only when its completeness is attested.

## Analysis Steps

1. Inventory actions, conversion ownership, and actual campaign goal membership. Primary/secondary labels alone may not resolve custom-goal bidding behavior.
2. Compare counting against the business event: repeated purchases and distinct leads may justify Every; One may fit unique lead objectives. Every does not prove duplicate lead submissions.
3. Flag a counting mismatch as configuration risk unless independent event reconciliation confirms material overcounting.
4. Compare value settings to strategy/objective. Count-based optimization can legitimately use no monetary value or a unit proxy; value-based optimization needs a coherent stated value signal.
5. Review dynamic/default values in 107; do not mandate static lead or dynamic purchase values without intent, and do not invent a fallback value.
6. Align click-through windows with observed sales cycle and intended reporting, within current source-supported settings. Neither 90 days nor a short cycle alone proves a defect.
7. Review actual attribution model and status. [Google DDA guidance](https://support.google.com/google-ads/answer/6394265) states all conversion actions are eligible regardless of volume; old 3,000-click/300-conversion gates must not be used.
8. Eligibility does not compel adoption or guarantee uplift. Discuss Last Click versus DDA using documented measurement intent and current action UI support; low volume is uncertainty, not ineligibility.
9. For a proposed attribution change, describe reporting comparability, baseline and mature monitoring window, and business owner approval; no account changes.

## Thresholds

Use [PARAMETERS](../_resources/PARAMETERS.md); resolve overrides before classifying findings.
Numerical cutoffs are triage heuristics unless explicitly sourced as platform guidance, not causal-loss estimates.
| Condition | Severity |
|---|---|
| Independent evidence links incorrect action/goal configuration to material measurement or bidding-objective failure | Critical |
| Observed configuration conflicts with declared counting/value/window/goal intent | Warning |
| Alternative attribution model merits contextual review | Info |
| Last Click, Every leads, zero/unit values for count objectives, or unknown settings alone | Info |

Apply `{{min_impressions}}` to CTR, `{{min_clicks}}` to conversion rates, and `{{min_conversions}}` to CPA/ROAS comparisons on both sides.
Compare mature, complete, like-for-like windows and goals; exclude incomplete days/reporting lag. Never divide by zero.
Direct trace/configuration evidence needs no rate comparison, but Critical additionally needs evidenced material impact.
Historical spend is exposure, not savings; do not invent recovery, revenue, match-rate, or conversion uplift.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md); do not duplicate its format.
Include stable account/campaign/action or other entity IDs, condition key, evidence/window, sample, resolved thresholds, recommendation, uncertainty, and owner.
- Include action/campaign/strategy IDs, counting and goal intent, actual membership, value basis, window, attribution model/status, and evidence state.
- Explain that DDA has no volume eligibility gate; preserve justified alternative configurations.
Separate confirmed defects, contextual risks, optional opportunities, and unassessed checks.
No account writes, legal certification, or automatic remediation are authorized.
