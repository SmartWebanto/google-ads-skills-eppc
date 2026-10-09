---
name: skill-001-campaign-type-separation
description: "Review campaign architecture against business objectives and control needs without prescribing a campaign mix."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: export
  merged_from: [skill-011-power-pack-assessment]
  related: [skill-002-brand-nonbrand-split, skill-003-naming-convention-consistency, skill-005-search-partners-performance, skill-006-display-network-optin]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 001: Business-Led Campaign Architecture

## Purpose

Review campaign architecture against business objectives and control needs without prescribing a campaign mix.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** All campaign types; preserve legitimate single-channel, Standard Shopping and manual-bidding setups.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`, `export/budgets`, `export/bidding_strategies`.
- Objective, channel/subtype, network settings, budget/strategy IDs; metrics at campaign/window grain.
- Optional `export/custom/campaign_features.csv`: account_id, campaign_id, feature_name, status,
  source, snapshot_date; one campaign/feature/snapshot row from settings UI. RSA inventory uses `export/ads`.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without objectives retain inventory only; without feature evidence omit AI Max status and other adoption claims.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Inventory enabled and paused campaigns by explicit type, objective, market, budget and strategy.
   Do not infer campaign features from campaign names.

3. Aggregate cost once per campaign/window and show channel share within comparable objectives.
   Shared-budget membership is not additional spend; allocation is descriptive, not an optimum.

4. Map stated business objectives to eligible campaign coverage and operational constraints.
   An uncovered objective is an opportunity only if the owner confirms it belongs in paid media.

5. Review whether independent budgets, goals, markets or governance justify separation.
   Recommend consolidation only with compatible targeting, goals and controls.

6. Absorb the former Power Pack inventory as optional PMax, Demand Gen and Search-feature context.
   No mandatory adoption, spend allocation, diversification or bidding migration follows from feature absence.

7. Route network outcomes to 005/006, naming to 003 and brand routing to 002.
   Shopping/PMax coexistence does not establish product overlap or competition.

8. Offer business-led alternatives with tradeoffs and missing prerequisites before proposing a test.
   Do not claim improved bidding signals merely from splitting channels.

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
| Setting contradicts an approved objective/control requirement | Warning |
| Any campaign mix, channel share or absence of optional AI features alone | Info |
| Unknown objectives, features or product overlap | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include an objective × channel × budget/strategy matrix; no adoption score or quota.
