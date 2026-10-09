---
name: skill-020-low-performing-keyword-pruning
description: "Screen mature keyword exposure and goal-relative outcomes for contextual review rather than immediate pruning or guaranteed savings."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  related: [skill-014-search-term-mining-negatives]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction; gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | portfolio target precedence"
---
# Skill 020: Low-Performing Keyword Review

## Purpose

Screen mature keyword exposure and goal-relative outcomes for contextual review rather than immediate pruning or guaranteed savings.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search keywords with conversion/value objectives; awareness keywords require their own agreed success metrics.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/keywords`, `export/keyword_metrics`, `export/campaign_metrics`,
  `export/bidding_strategies`, `export/search_terms`, `export/conversion_actions`.
- Campaign/profile CPA or ROAS target, objective, strategy, tracking status, conversion lag and maturity.
- Keyword metrics at account/campaign/ad_group/keyword/window; query evidence is a separate relevance breakdown.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without working-tracking evidence or conversion maturity retain exposure inventory but defer pruning; without a target use a comparable mature benchmark only if justified.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Resolve the applicable target through PARAMETERS: campaign target (including an embedded
   Maximize Conversions/Value target), then linked portfolio target, then compatible campaign-objective/
   profile target, else absent. Record its source and use the SAME resolved target for outcome screening
   and money parameters. Keep CPA and ROAS objectives distinct; a profile target cannot override an
   applicable portfolio target. Resolve {{spend_floor}} even without a target; average CPC is not a target.

3. Screen zero-conversion keywords at {{spend_floor}} only after tracking, maturity and relevance checks.
   Above 2×/3× a target may sort exposure but does not create a separate automatic-pause severity.

4. For positive-conversion keywords use one consistent screen: CPA >2× applicable target/benchmark.
   Require {{min_conversions}} on the entity and any empirical comparator; target goals/windows must be compatible.

5. For value-based objectives inspect mature ROAS against an applicable value target and value quality.
   Do not prune high-value traffic just because its CPA is relatively high.

6. Without target or suitable benchmark, omit relative-performance flags; retain mature zero-conversion spend review.
   Do not substitute an unrelated account-wide average.

7. Review actual query relevance, tracking problems, recent changes, learning and intended funnel role.
   Low CTR or Quality Score alone cannot diagnose landing-page failure or justify a pause.

8. Propose monitoring, messaging/query review or an owner-reviewed pause trial with explicit tradeoffs.
   Keyword CPC bid proposals apply only to supported manual controls; do not reduce keyword bids under Smart Bidding.

9. Keep exposure separate from savings and state unknown counterfactual delivery after a pause.
   Route negative opportunities to 014; no immediate account changes.

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
| Mature zero-conversion keyword at {{spend_floor}} after required contextual checks | Warning |
| Mature keyword CPA >2× applicable target or comparable benchmark | Warning |
| Insufficient tracking/maturity, absent benchmark or diagnostic score alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include resolved fallback source, eligibility/strategy, query evidence and review decision; do not label all screened spend waste.
