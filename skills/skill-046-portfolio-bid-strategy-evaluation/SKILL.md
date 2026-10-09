---
name: skill-046-portfolio-bid-strategy-evaluation
description: "Review portfolio goals and outcome dispersion without inferring harm from pooling or automatically splitting outliers."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: bidding
  kind: analyst
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 046: Portfolio Bid Strategy Evaluation

## Purpose

Assess whether portfolio configuration serves explicit business goals while preserving legitimate pooling and campaign diversity. Dispersion and dominance are descriptive diagnostics, not proof of optimization harm.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Campaigns using shared portfolio bid strategies, with strategy identity distinct from budget identity.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/bidding_strategies`, `export/budgets`, `export/conversion_actions`, `export/campaign_metrics`: full strategy membership, effective targets, actual goal/action sets and mature outcomes.
- Client profile: campaign objectives, value basis, customer-lifecycle/traffic role and approved campaign/portfolio CPA or ROAS guardrails.
- Full portfolio membership and export completeness are required, including campaigns with zero outcomes; cross-account strategies require complete authorized aggregate member evidence or explicitly partial scope.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Unknown goals or partial strategy membership prevent compatibility verdicts. Missing mature member outcomes limits dispersion; missing change/response data prevents trend or separation-uplift claims.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Inventory portfolio IDs, types, targets and linked campaign IDs. Do not infer portfolio membership from shared budgets or identical strategy names.

2. Map every member’s effective conversion goals, value definitions and business role. Different campaign labels or products can be compatible; identify actual contradictions in approved target/economic requirements.

3. Calculate portfolio outcomes from summed cost, conversions and value. Report member spend/conversion shares with denominator and coverage; dominance is not starvation or harmful signal dilution.

4. Within genuinely comparable mature member cohorts calculate CPA/ROAS values and descriptive dispersion. If using CV, state unweighted population standard deviation / positive mean, included members and exclusions; n<2 or nonpositive mean is unavailable.

5. Treat CV>0.40 or a member above 60% of conversions only as Info triage heuristics. Do not declare a low-volume member harmful to a large portfolio or impose thirty-conversion eligibility.

6. Check each explicit member guardrail and pooled goal performance. Heterogeneous outcomes may reflect intentional role/value differences; goal conflict needs owner review rather than automatic Critical.

7. Document alternative explanations and benefits of retaining pooling. A split proposal requires a business constraint and measured/modelled response with learning/budget risks; base aggregates alone cannot size benefits.

8. Recommend targeted configuration/goal review or a controlled portfolio experiment when justified. No automatic removal of outliers, forced inline strategies or newly invented minimum portfolio size.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed portfolio configuration conflicts with documented business goals or economic constraints | Warning |
| CV>0.40, one member >60% of conversions or low member volume alone | Info |
| Unknown goals, incomplete membership or insufficient comparable samples | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Strategy/member ledger with goal/action sets, effective target, outcomes and sample coverage.
- Descriptive CV/share calculations and review rationale; preserve pooling unless independently justified change is approved.
