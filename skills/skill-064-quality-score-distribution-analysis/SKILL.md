---
name: skill-064-quality-score-distribution-analysis
description: "Inventory diagnostic Quality Score coverage and low-score spend exposure without CPC savings claims."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: quality
  kind: deterministic
  data_source: export
  merged_from: [skill-129-quality-score-monitoring-alert-rules]
  related: [skill-065-quality-score-component-breakdown, skill-066-historical-quality-score-trend, skill-067-expected-ctr-improvement]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 064: Quality Score Distribution Analysis

## Purpose

Use keyword Quality Score (QS) to prioritize diagnostic review, not to optimize an account
KPI. QS is not an auction input and does not establish a CPC multiplier or recoverable
savings. Preserve useful inventory, spend exposure and request-only alert planning.
Source: [Google Ads: About Quality Score](https://support.google.com/google-ads/answer/6167118?hl=en).

## Data Requirements

**Applicability:** Search keywords with reported current QS. Do not invent QS for other
channels, excluded entity types or unavailable ratings; preserve null/unknown separately.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md):
- `account`: snapshot, window, units and completeness.
- `campaigns`, `ad_groups` and `keywords`: stable account/campaign/ad-group/criterion
  IDs, statuses, match type, current QS and expected CTR/ad relevance/LP components.
- `keyword_metrics`: matching IDs, window, impressions, clicks, cost, conversions and
  conversion value; missing metric rows are not assumed zero unless export is complete.
- Optional history uses skill-066's `export/custom/quality_score_history.csv` schema;
  never infer historical scores from a current-state query over a historical date range.
- Client profile goals and resolved monetary parameters for prioritization, not QS targets.

**Missing inputs:** Missing QS blocks that keyword's rating check, not spend inventory.
Missing components blocks attribution to a component. Missing historical evidence blocks
trend alerts only. If metrics are absent, report counts without fabricated spend rankings.

## Analysis Steps

1. Define the eligible keyword universe from campaigns/ad groups/keywords, not only metric
   rows with impressions. Separate enabled serving inventory from paused/removed entities.
2. Normalize valid QS 1–10, unavailable and invalid source values. Never turn N/A into 0.
   Count buckets 1–3, 4–5, 6–7, 8–10 and N/A; report full inventory count explicitly.
3. Bucket count share uses all eligible keywords including N/A. A rated-only distribution
   may also be shown but must name its non-null denominator. Report score availability.
   Do not convert a weighted account average into a target or optimization KPI.
4. Join period cost to current rating, labeled CURRENT-SNAPSHOT exposure rather than a
   historical QS time series. Show each bucket's spend share of all eligible keyword cost,
   including an N/A bucket; ensure every criterion's cost is counted only once.
5. Prioritize QS 1–3 with cost >= {{spend_significant}} or QS 4–5 with cost >=
   {{spend_material}}. These are review heuristics, not proof of poor economics.
   Attach observed weak components; multiple weak components do not reveal causal weights.
6. Delegate component ownership to 065 and concrete CTR/relevance/LP review to 067/068/069.
   Preserve profitable low-QS keywords for review rather than pausing them to improve a score.
   Compare business outcomes only with mature comparable goals and sample gates.
7. Recommend request-only monitoring: condition key, stable entity IDs, snapshot cadence,
   owner and review/reset state. QS <=3 with {{min_impressions}} or a 2-point historical
   decline can open a diagnostic review; score-only alerts are never automatic bid/pause rules.
   Route historical changes to 066 so current exposure and historical decline are not duplicate loss.

## Thresholds

| Condition | Severity |
|-----------|----------|
| QS 1–3 and current-snapshot period cost >= {{spend_significant}} | Warning |
| QS 4–5 and current-snapshot period cost >= {{spend_material}} | Warning |
| Weak component with period cost >= {{spend_significant}} | Warning |
| Low-QS keyword count/share, no corroborating cost or business issue | Info |
| Missing score, components, metrics or optional history | Info |

No QS-only condition is Critical. Score boundaries and spend priority are triage heuristics.
Apply [PARAMETERS](../_resources/PARAMETERS.md) to business comparisons: {{min_impressions}}
for CTR, {{min_clicks}} for CVR, {{min_conversions}} for CPA/ROAS on both mature sides.
A score's availability does not make its associated business performance sample sufficient.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Add bucket counts/denominators, N/A coverage, deduplicated spend exposure and snapshot date,
component routing and proposed alert owner/cadence; never estimate CPC savings from QS.
