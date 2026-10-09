---
name: skill-043-daily-budget-to-cpa-ratio-check
description: "Calculate descriptive budget-to-CPA ratios at the correct budget scope without universal minimums or automatic increases."
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
# Skill 043: Daily Budget-to-CPA Diagnostic

## Purpose

Describe budget scale relative to acquisition costs while separating planning ratios from demand, bidding eligibility and profitability.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Acquisition-oriented campaigns or comparable shared pools with a positive CPA target or mature achieved CPA; ROAS campaigns have no universal CPA-ratio equivalent.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/budgets`, `export/bidding_strategies`, `export/campaign_metrics`: budget and strategy IDs, daily amount/unit, targets, mature cost/conversions/value, explicit goal cohorts.
- Client profile: campaign objectives, approved budget constraints, approved CPA/ROAS economics and reporting/lag window.
- Full shared-budget membership and current target source, including embedded/portfolio targets, are required for the relevant scope; unknown member targets remain unknown.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Zero conversions or missing positive targets make the respective CPA ratio unavailable. Missing shared membership prevents pool ratios; do not allocate the entire pool budget to each campaign.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Resolve daily-budget type and budget ID; total/lifetime budgets cannot be labeled daily without an explicit valid schedule. Separate shared from standalone budgets.

2. For standalone budgets calculate target ratio=daily amount/positive effective CPA target and achieved ratio=daily amount/(mature cost/conversions), keeping the two definitions separate.

3. For shared pools deduplicate amount by budget ID and sum mature cost/conversions only across comparable conversion goals and value definitions. Do not sum targets or average incompatible campaign CPAs.

4. Compute a target-based pool ratio only when members genuinely share one target/goal basis; otherwise show per-member targets descriptively with the shared amount and no false campaign capacity.

5. An achieved CPA requires `{{min_conversions}}`; zero conversions yield unavailable. Any zero-conversion spend screen requires mature tracking/relevance review and `{{spend_floor}}`, not division by zero or an automatic pause.

6. Report ratios as descriptors. Remove five-to-ten-times requirements, low-ratio Smart Bidding ineligibility and one-conversion-per-day quotas; a low ratio may be fully intentional.

7. Check business efficiency, actual demand and base budget-lost IS before considering scale review. A high ratio does not imply excellent performance and a low ratio is not itself a delivery failure.

8. If a business need remains unmet, route to 042 and 045 for dated constraints and marginal analysis. Do not multiply CPA by five/ten to produce a required budget or predict daily conversions.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Any ratio alone, including below 2x or above 20x | Info |
| Mature zero-conversion spend above {{spend_floor}} with working tracking and relevance concern | Warning |
| Ratio unavailable because target, comparable pool membership or mature conversions are missing | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Budget-scope target/achieved ratios with source, denominator, shared membership and explicit unavailable cases.
- Business-context review notes; no minimum recommended budget or deterministic conversion capacity.
