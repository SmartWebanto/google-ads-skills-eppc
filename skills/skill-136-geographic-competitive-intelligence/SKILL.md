---
name: skill-136-geographic-competitive-intelligence
description: "Describe regional outcomes and service relevance without inventing regional impression share or competition."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: competitive
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 136: Geographic Performance Analysis

## Purpose

Describe regional outcomes and service relevance without inventing regional impression share or competition.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Campaigns with geographic reporting and known service area, location basis and objectives.

**Required inputs:**
- Base `export/` tables: account, campaigns, campaign_metrics, bid_adjustments, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/geographic_daily.csv`: account_id/campaign_id/date/location_id/location_basis grain; location_name, country_id, region_id, device, network, impressions, clicks, cost, conversions, conversion_value, goal_id, unknown_location_flag; Ads geographic report for 8 complete weeks, basis explicitly user-location versus matched-location.
- `export/external/regional_business.csv`: campaign_id/location_id/effective_range grain; service_available, objective, capacity, maximum_cpa_or_minimum_roas, margin_basis_if_used, owner; client service/target plan covering analysis dates.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Keep user and matched-location reports separate and preserve unknown geography; do not sum overlapping country/region hierarchies.

2. Compute regional CTR, CVR, CPA and ROAS from counts with mature comparable samples. ROI requires real margin/profit inputs; ROAS is not ROI.

3. Compare within campaign/goal/device/network where supplied, not arbitrary account averages. Review local availability and value mix before judging performance.

4. No eligible-impression denominator is supplied: do not calculate regional IS. Even measured low IS would not uniquely establish competition, dominance or underserved demand.

5. Trends need aligned complete weeks, not aggregate regional totals. Propose service/creative review or a bounded geography test; manual location CPC modifiers require supported strategy and are not a default under Smart Bidding.

Use matched IDs and declared grain before joining; never multiply entity metrics across many-to-many associations.
For comparisons, align goals, traffic scope and complete periods; exclude incomplete days and conversion reporting lag.
Use {{min_impressions}} for CTR/share, {{min_clicks}} for CVR and {{min_conversions}} for CPA/ROAS, on both comparison sides.
A zero-conversion spend screen may bypass min_conversions only after maturity, working tracking and relevance review at {{spend_floor}}.
Do not divide by zero; preserve censored, suppressed and unknown values rather than treating them as zero.
Historical non-converting cost is exposure, not guaranteed savings; observational changes are not causal uplift.

## Thresholds

Numerical cutoffs here are triage heuristics unless explicitly tied to a sourced platform requirement.
Resolve parameters through [PARAMETERS](../_resources/PARAMETERS.md); business tolerances require a declared value.

| Condition | Severity |
|---|---|
| Observed material delivery into a documented prohibited service region | Critical |
| Mature regional outcomes miss the stated client efficiency tolerance | Warning |
| Sparse/unknown geography or unsupported competition hypothesis | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Region IDs and reporting basis, date windows, goal metrics, sample and service constraints.
- Regional performance hypotheses and supported-control review; no competition matrix or automatic bid percentages.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
