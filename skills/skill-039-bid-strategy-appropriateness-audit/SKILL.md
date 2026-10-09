---
name: skill-039-bid-strategy-appropriateness-audit
description: "Assess objective-aligned bidding, channel-dated legacy settings and actual manual-CPC first-page estimates without mandatory migrations."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: analyst
  data_source: external
  merged_from: [skill-021-below-first-page-bid, skill-047-enhanced-cpc-deprecation-migration-check]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 039: Bid Strategy, Legacy Settings and First-Page Estimate Review

## Purpose

Own strategy appropriateness plus the legitimate checks absorbed from 021 and 047. Assess the actual objective and supported controls, not universal monthly conversion quotas or a required progression toward Smart Bidding.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Campaign/strategy types documented as supported at the export date; first-page bidding subcheck only for eligible manual-CPC Search keywords.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/budgets`, `export/conversion_actions`, `export/campaign_metrics`, `export/ad_groups`, `export/keywords`, `export/keyword_metrics`: IDs, actual goals, strategy links, targets and actual first-page estimates.
- `export/custom/bidding_configuration.csv`: one account_id/campaign_id/snapshot_at row, channel/subtype, strategy_id/type, standalone_target_cpa/roas, maximize_conversions_target_cpa, maximize_value_target_roas, effective_target_source, legacy_ecpc_setting, legacy_setting_source, bidding_status/reasons and source_ref; current Ads campaign/portfolio settings export.
- `export/custom/manual_keyword_bids.csv`: one account_id/campaign_id/ad_group_id/keyword_id/snapshot_at row, keyword_cpc_bid, keyword_bid_is_inherited, ad_group_default_cpc, first_page_estimate, estimate_at, estimate_status, eligibility_status/reasons, source_ref; actual Ads Search keyword/default-bid columns.
- `export/external/bidding_constraints.csv`: one campaign_id/constraint_id/effective_date row, account_id, objective, approved_max_cpa, minimum_roas, approved_max_cpc, value_basis, tracking_readiness, applicable_strategy/control, supported_state, channel/subtype, notice_effective_date, official_source_url, checked_at and owner; business brief plus current platform notices/settings evidence.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Missing objective/values prevents strategy suitability judgment. Missing actual estimate or inherited-bid evidence skips that keyword comparison. An absent legacy flag is unknown, not ECPC enabled/disabled.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Join configuration and portfolio membership by IDs. Resolve actual target source, including optional targets embedded in Maximize Conversions/Value; conflicting sources require verification, not arbitrary precedence.

2. Map strategy optimization to explicit campaign goals and effective conversion actions, including custom-goal membership. Manual CPC, clicks and impression-share goals can be valid; low conversion count affects confidence, not universal eligibility.

3. Check tracking readiness and business-value fitness before any strategy proposal. A count threshold alone cannot justify switching to clicks/manual or forcing tROAS; channel/subtype support is mandatory.

4. Inventory legacy flags using actual channel-specific settings. Compare export/snapshot date with the notice scope and effective date; Search/Display notices do not automatically establish Shopping scope. Historical flags can describe past valid configurations.

5. Request a migration review only for confirmed affected current settings. Select only supported replacements aligned to the objective, tracking/value readiness, economics and risk; no automatic Shopping Maximize Conversions recommendation.

6. For manual-CPC Search only resolve effective keyword base bid: explicit non-inherited bid, otherwise the supplied ad-group default. Compare with the actual current platform first-page estimate, not Bid × QS, average CPC multipliers or low impressions.

7. A bid below estimate is an indicative visibility constraint, not a guaranteed auction floor or lost demand. Review keyword eligibility, relevance, demand and estimate age; cap any proposed bid exploration by approved max CPC or justified value-per-click economics. Without business value, request it rather than increase bids.

8. Recommend controlled, owner-approved strategy/bid proposals with guardrails and observation window. Use 040 for target realism, 041 for dated learning, and 051 for modeled marginal outcomes; aggregate metrics cannot support trends.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed current unsupported/deprecated setting within documented channel/date scope | Warning |
| Actual manual-CPC base bid below current first-page estimate with relevance and economic headroom | Info |
| Verified value/goal configuration failure materially corrupting active optimization | Critical |
| Low volume, manual strategy adoption, unknown target/legacy setting or missing estimate alone | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Per-campaign objective/strategy/target-source ledger and dated legacy applicability evidence.
- Keyword actual-estimate comparisons with inheritance, eligibility, business cap and uncertainty; review-only migration plan with rollback criteria.
