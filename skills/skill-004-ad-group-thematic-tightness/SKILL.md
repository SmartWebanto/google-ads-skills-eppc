---
name: skill-004-ad-group-thematic-tightness
description: "Compare keyword themes with eligible ad messaging using an explicit analyst rubric, not keyword-count quotas."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: export
  related: [skill-024-keyword-intent-alignment]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 004: Ad Group Thematic Review

## Purpose

Compare keyword themes with eligible ad messaging using an explicit analyst rubric, not keyword-count quotas.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search ad groups with text keywords; keywordless inventory is out of scope.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/ad_groups`, `export/keywords`, `export/ads`, `export/keyword_metrics`.
- Profile product/service taxonomy, intended offer, audience and geography.
- Ads require approval/status, headline/description text and final URLs; QS components are optional diagnostics.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without copy skip message comparison; without taxonomy mark inferred themes tentative. URLs alone do not establish page relevance.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Count distinct enabled keyword IDs by ad-group ID descriptively.
   One keyword or thirty-plus keywords does not establish a structural defect.

3. Assign each keyword a tuple: product/service, task, audience, geography and offer.
   Record supporting words/profile evidence; preserve Unknown and ambiguous assignments.

4. Group themes by identical required tuple fields under the approved taxonomy.
   Show memberships rather than an unexplained semantic-cohesion score.

5. Compare themes to eligible ads: Supported for explicit/approved equivalent offers;
   Contradicted for a different offer/task; Unknown for generic or incomplete copy.

6. Summarize mature keyword metrics by theme without multiplying them by the number of ads.
   Quality Score is diagnostic, not an auction-input KPI or proof structure caused performance.

7. Propose a split only where separate messages or experiences are needed.
   Before merging verify compatible offer, goals, targeting and routing controls.

8. Preserve coherent sparse/large groups and describe messaging hypotheses without promised uplift.
   Landing-page content review belongs to 024, not inference from a URL.

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
| Explicit theme/eligible-copy contradiction with product evidence | Warning |
| Multiple themes, keyword count or lower QS without corroboration | Info |
| Unknown intent or insufficient eligible copy | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include tuple evidence, keyword/ad IDs and owner-reviewed alternatives.
Source: [Quality Score is diagnostic, not an auction input](https://support.google.com/google-ads/answer/6167118?hl=en).
