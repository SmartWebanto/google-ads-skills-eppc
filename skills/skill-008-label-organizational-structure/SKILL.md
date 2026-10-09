---
name: skill-008-label-organizational-structure
description: "Review label coverage and dependencies against an approved operating taxonomy, preserving optional and intentionally unused labels."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: external
  related: [skill-003-naming-convention-consistency]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx051 | label_rule_evaluation inputs/step (index #51)"
---
# Skill 008: Label Governance Review

## Purpose

Review label coverage and dependencies against an approved operating taxonomy, preserving optional and intentionally unused labels.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Campaign, ad-group, keyword and ad labels only for entity levels actually supplied.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/ad_groups`, `export/keywords`, `export/ads` for scoped denominators.
- `export/custom/label_inventory.csv`: account_id, label_id, name, status, snapshot_date; one label/snapshot.
- `export/custom/label_associations.csv`: account_id, label_id, entity_type, campaign_id, ad_group_id,
  entity_id, snapshot_date; one association from UI/API exports covering all declared levels.
- `export/external/label_policy.csv`: one rule/consumer row at review snapshot; rule_id, entity_type,
  eligibility_rule, required_label_ids, consumer_id, expected_behavior, observed_failure, evidence_ref,
  owner, reviewed_at from reporting/automation configuration. Creation dates are optional, not assumed.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.
- Optional opt-in `profile.label_rules` (rule_id, label, entity: keyword, window: report, AND conditions {metric, op quoted ">=" "<=" "==", value, conversion_action?}) with `export/custom/keyword_conversions_by_action.csv`: keyword_id, campaign_id, ad_group_id, conversion_action_id, conversions, conversion_value, window (report or period), plus `export/keyword_metrics`, `export/conversion_actions` and `keywords.labels`.

**Missing inputs:** Without associations skip that entity-level coverage; without policy labels are optional; without all levels and dependencies do not call a label globally unused.
Without `profile.label_rules` rule evaluation is not applicable; unknown actions/metrics reject the rule; immature windows leave conversion rules partial.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Inventory labels and normalize names only for near-duplicate suggestions; preserve original IDs.
   Similar names can have different consumers or meanings.

3. Compute coverage per supplied entity type: applicable entities with required labels / applicable entities.
   Separate any-label coverage from policy compliance and enabled from paused inventory.

4. Validate each declared policy against associations; record missing required labels and contradictory labels.
   Zero labels is not an inherent account defect.

5. Review attached entity IDs and exported scopes before describing an unattached label.
   No campaign associations does not prove no ad-group, keyword, ad or consumer use.

6. Inspect declared report/rule dependencies for concrete operational effects.
   Do not infer importance from spend or newness without supplied metrics or creation history.

7. Suggest a small business-specific taxonomy only when reporting/automation needs justify it.
   No fixed campaign/ad-group coverage quota applies universally.

8. Return owner-review proposals for merges/renames, including all affected consumers.
   Never recommend deletion from campaign-only evidence; unused candidates need complete dependency review.
9. Evaluate each declared `profile.label_rules` rule per keyword ID; report target vs current label sets and add/remove lists as a proposal, never labeling.

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
| Missing/contradictory label breaks an evidenced required consumer | Warning |
| Unlabeled entities, low coverage or zero labels absent an approved requirement | Info |
| Similar names or unattached-in-export labels pending dependency review | Info |
| Keyword labels differ from a declared `profile.label_rules` target set | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include coverage denominator per entity level and dependency-aware label proposals.
