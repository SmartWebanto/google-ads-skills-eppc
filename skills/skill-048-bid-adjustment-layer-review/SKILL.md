---
name: skill-048-bid-adjustment-layer-review
description: "Review dated modifier settings using strategy-specific control semantics and comparable segment evidence."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 048: Bid Adjustment Applicability and Layer Review

## Purpose

Identify unintended supported-control settings without assuming all Smart Bidding modifiers behave identically or that old settings need removal.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Only dimensions, levels and controls supported by the actual channel/subtype/strategy at the settings date.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/bidding_strategies`, `export/bid_adjustments`: IDs, dimensions, criterion/segment values, level, modifiers, exclusions and effective strategy.
- `export/custom/modifier_history.csv`: one account_id/entity_id/dimension/criterion_id/effective_from/to row, campaign_id/ad_group_id, old/new_modifier, exclusion_state, changed_at, source_ref; dated Ads settings/history for the reviewed period, including schedule and audience rows.
- `export/custom/modifier_segment_daily.csv`: one account_id/campaign_id/ad_group_id/dimension/segment_id/date row, impressions, clicks, cost, conversions, value, goal_cohort and source_ref; complete mature Ads segment report, with overlap definitions and explicit dates.
- `export/external/modifier_controls.csv`: one channel/subtype/strategy/dimension/level/effective_date row, control_effect (CPC/CPA_target/exclusion/ignored/unsupported), precedence/combination_rule, official_source_url, checked_at, intended_setting/rationale and owner; current platform guidance plus business settings brief.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without supported-control evidence do not recommend modifier changes. Without history no staleness claim; without segmented outcomes no performance-mismatch claim.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Inventory every supplied dimension and both campaign/ad-group levels, not just device/location. Keep omitted rows unknown unless the export explicitly certifies complete settings.

2. Resolve the actual bidding strategy and optional target. Apply the current control matrix; do not label every non-exclusion Smart Bidding modifier inactive or every Manual/ECPC control active.

3. Distinguish tCPA device adjustments that alter device CPA targets from direct CPC adjustments; for a supported +20% device target modifier, effective device target is base tCPA×1.20, not a 20% CPC increase. Verify strategy/subtype support before calculating.

4. Treat device -100% as an exclusion only where supported and review intent; an intentional exclusion is not inherently bad. Do not propose manual keyword/CPC modifier optimization for auction-time Smart Bidding.

5. Resolve inheritance/precedence using the documented rule for that dimension and level. Do not multiply all campaign/ad-group rows blindly or call different values a conflict when one supersedes another.

6. Calculate setting age only from an actual change timestamp or lower-bounded history. More than ninety days is an Info review cue, not proof the setting is stale or should be removed.

7. Use matched mature segment outcomes with the same goals, attribution, dates and strategy regime. Excluded segments lack observed counterfactual outcomes; overlapping audience/dimension rows cannot be summed into distinct lost spend.

8. Propose an intended-control review or controlled adjustment test bounded by business economics; no fixed +/− percentages from raw CPA ratios. Ignored legacy settings may be documented without removal; operational changes require approval.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Supported effective modifier/exclusion contradicts documented business intent | Warning |
| Mature comparable segment issue supports a bounded control review | Warning |
| Old setting, ignored control, valid override or missing applicability/history alone | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Layered setting/effective-control matrix with exact source, dates and exclusion/CPA-target/CPC distinctions.
- Segment evidence and review-only proposals with ownership, uncertainty and no unsupported modifier sizing.

Sources: [Google bid adjustment guidance](https://support.google.com/google-ads/answer/2732132).
