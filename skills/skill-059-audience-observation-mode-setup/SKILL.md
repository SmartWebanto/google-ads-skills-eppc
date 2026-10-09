---
name: skill-059-audience-observation-mode-setup
description: "Review audience coverage and intended Targeting versus Observation without mandatory adoption."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: export
  related: [skill-060-in-market-custom-intent-layering, skill-061-customer-match-list-health, skill-062-audience-minimum-size-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 059: Audience Observation Mode Setup

## Purpose

Inventory relevant audience observation opportunities without prescribing a standard
mandatory audience set. Distinguish deliberate targeting from accidental reach restriction
using owner-declared campaign intent, not the presence of a Targeting label alone.

## Data Requirements

**Applicability:** Campaign types and audience classes supporting Observation/Targeting.
Performance Max audience signals and other channel-specific signals are not Observation
or hard Targeting; classify their actual mechanism instead of applying Search assumptions.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) base files:
- `account` for window, snapshot, completeness and units.
- `campaigns` and `ad_groups` for the full enabled/paused universe, stable IDs,
  channels/subtypes, goals and relevant settings, including campaigns with no audiences.
- `campaign_metrics` for same-window delivery/cost and `bidding_strategies` for applicability.
- `audiences` for campaign AND ad-group associations: criterion/list ID, parent IDs,
  level, type, status, mode, exclusions, eligibility, membership definition and modifier.
- Client profile business_type, campaign_objectives and customer_lifecycle; identify
  intended prospecting, remarketing, retention, acquisition or research-only campaigns.
- If association/mode fields are absent, request `export/custom/audience_modes.csv`
  from campaign/ad-group Audiences settings UI, one row per account_id/campaign_id/
  ad_group_id/criterion_id/snapshot_date: audience_id, audience_type, scope, mode,
  positive_or_exclusion, status, channel_support, source. Include campaign-level settings
  that establish effective mode; an audience performance query alone is insufficient.

**Missing inputs:** Incomplete campaign inventory prevents missing-audience counts.
Missing mode is unknown; missing business intent blocks claims of accidental restriction.
No list eligibility evidence means no proposal depending on that list's serving readiness.

## Analysis Steps

1. Left-join audience associations to all eligible campaigns and ad groups. Report inactive
   and unsupported entities separately; never use the audience table as the campaign universe.
2. Resolve effective campaign/ad-group settings and exclusions. Preserve both levels,
   inheritance and channel-specific semantics; do not double-count the same association.
3. Match declared intent to actual mechanism. Targeting is legitimate for dedicated
   remarketing or intentional constrained acquisition; Observation is appropriate only
   when measurement without audience reach restriction matches the objective.
4. Flag a mode conflict only with explicit owner intent. To call it a material delivery
   failure, also require observed reach/delivery evidence and a confirmed restrictive path;
   lack of delivery alone cannot establish the audience as the cause.
5. Identify relevant optional segments using documented business audience definitions.
   Candidate remarketing, in-market or affinity audiences must be available, eligible and
   permitted for that campaign; no mandatory all-visitors or past-converters list.
6. Prioritize optional measurement coverage by relevant campaign cost and a clear question
   it would answer. Spend without Observation is not a defect; campaigns can legitimately
   rely on other signals or have no useful eligible audience segmentation.
7. Request-only proposals name exact campaign/ad-group/list IDs, current/proposed mode,
   purpose, eligibility evidence, reach risk, owner and review window. Do not attach lists.
   Ordinary audience bid modifiers are not proposed under Smart Bidding; performance
   comparisons belong to skill-060 and list health to skill-061/062.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Effective audience mode conflicts with explicit owner campaign intent | Warning |
| Confirmed unintended restriction directly causes material delivery failure | Critical |
| Relevant eligible audience absent, with a specific measurement use case | Info |
| Targeting deliberately serves a constrained objective | Info |
| Missing campaign universe, intent, mode, eligibility or channel support | Info |

There is no spend threshold that makes optional audience adoption mandatory.
Any performance claim requires mature comparable samples under [PARAMETERS](../_resources/PARAMETERS.md).
Numerical prioritization is triage only; configured coverage is not incremental performance.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Add full eligible campaign denominator, effective mode by scope, intended mechanism,
association coverage, owner-confirmed conflicts, and optional audience rationale.
