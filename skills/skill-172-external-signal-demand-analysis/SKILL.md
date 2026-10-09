---
name: skill-172-external-signal-demand-analysis
description: "Compare mature performance across profile-defined buckets of a supplied external signal (weather, TV airings) as hypotheses; propose request-only tests or schedule rules."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: seasonal
  kind: analyst
  data_source: external
  markets: all
  related: [skill-146-seasonality-bid-adjustment-deployment, skill-152-historical-performance-benchmarking-seasonal-planning, skill-057-ad-schedule-optimization, skill-054-geographic-performance-analysis, skill-048-bid-adjustment-layer-review]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes5 | new recipe from index #31 and #32"
---
# Skill 172: External Signal Demand Analysis

## Purpose

Check whether performance differs between explicitly bucketed values of a supplied external signal: temperature, rain or a TV airing flag, for example. Compare mature, sample-qualified cohorts. A difference is a correlation to test, never a cause. Proposed experiments or schedule rules are requests only. Nothing fetches live weather or TV data, and nothing changes the account.

## Data Requirements

**Applicability:** Campaigns with daily or hourly performance at the same region grain as a client-supplied signal series. It runs only when explicitly requested with bucket definitions in the profile. No signal or no buckets means not assessed; that is not a defect.

**Required inputs:**
- Base tables per [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account` (period, snapshot, lag) and `export/campaigns` (id, bidding_strategy_type, target_roas) for strategy and control semantics.
- `export/external/external_signals.csv`: one row per signal_name/region/date[/hour], with date, hour (0-23 or empty for daily), region, signal_name, value (numeric; flags are 0/1) and source. The client or provider saves it locally. Effect windows, such as an airing plus one hour, must already be encoded in the series.
- `export/custom/campaign_geo_daily.csv`: one row per campaign_id/region/date, with impressions, clicks, cost, conversions, and optional conversion_value and complete_day. Ads geographic daily report. `region` uses the same keys as the signal series.
- `export/custom/campaign_geo_hourly.csv` (optional): the same columns plus hour, for hourly signals.
- `export/external/signal_rules.csv` (optional): rule_id, signal_name, bucket, campaign_id, action (bid_modifier or pause), modifier (fraction, e.g. 0.2) and status, for existing weather/TV rules.
- Profile `external_signals.<signal_name>`: `bounds` (strictly increasing numbers), `labels` (one more than bounds), `baseline` label and `min_relative_difference` (declared business tolerance, e.g. 0.2). Campaign goals and targets come from `campaign_objectives`.

**Missing inputs:** Without the signal series or bucket definitions, every alignment step is skipped. Without daily or hourly performance, that grain is skipped. A missing tolerance keeps comparisons descriptive. Unknown maturity, or tracking not evidenced for every campaign goal, blocks conversion-based comparisons; CTR remains descriptive. Missing rules skip rule consistency. Missing signal days are unmatched, not a neutral bucket.

## Analysis Steps

1. **Signal series.** Parse dates, hours and values. Drop rows without a source. Identical duplicates collapse. Conflicting values for one signal/region/period are excluded and reported.
2. **Buckets.** Validate the profile bounds, labels and baseline per signal. value < bounds[0] → labels[0]; bounds[i-1] ≤ value < bounds[i] → labels[i]; value ≥ last bound → last label.
3. **Daily alignment.** Keep report-period rows only.
   - Drop rows marked incomplete, rows with unknown metrics and duplicate campaign/region/date keys (all copies).
   - Join on campaign region and date to the daily signal value. Unmatched rows are reported, not bucketed.
   - Per campaign and signal, pool regions into bucket cohorts: periods, weekday mix, impressions, clicks, cost, conversions and value.
   - Compute CTR, CVR, CPA and ROAS as ratios of sums, then relative difference = bucket / baseline − 1.
4. **Hourly alignment.** Same method at date/hour. An hourly signal wins; a daily signal applies to all hours of its date. Hourly signals are never averaged to days.
5. **Gates and hypotheses.**
   - Both cohorts must meet {{min_impressions}} for CTR, {{min_clicks}} for CVR and {{min_conversions}} for CPA/ROAS.
   - Conversion metrics also need `ctx.mature` and tracking evidenced for every campaign goal. ROAS is primary for ROAS objectives; CPA otherwise, with CVR as fallback.
   - A gated difference whose magnitude reaches the tolerance becomes an Info hypothesis. Review weighs confounders: weekday mix, promotions, seasonality and region mix.
   - Only then may review propose a controlled experiment (allocation, metric, duration, stop rule, owner) or a schedule rule.
   - Bid-modifier proposals must match the observed direction and stay within −90%..+900%. They are rejected under Smart Bidding or an unknown strategy, since Smart Bidding ignores these adjustments ([About bid adjustments](https://support.google.com/google-ads/answer/2732132)). Ad-schedule proposals need an hourly-grain difference.
6. **Rule consistency.** Enabled bid_modifier/pause rules are compared with the qualified difference for their campaign, signal and bucket. A raise on an unfavorable bucket, or a cut or pause on a favorable one, goes to review.

## Thresholds

Resolve [PARAMETERS.md](../_resources/PARAMETERS.md); sample gates apply to each cohort, both sides. `min_relative_difference` is a declared business tolerance and a triage heuristic, not a significance test. Rate differences between non-randomized days are observational and never prove causation. A controlled experiment with a predeclared metric, allocation, duration and stop rule is the test.

| Condition | Severity |
|---|---|
| Enabled signal rule's direction contradicts a qualified mature cohort difference, confirmed as unintended | Warning |
| Qualified mature cohort difference at or above the declared tolerance (test hypothesis, not a cause) | Info |
| Unqualified cohorts, unknown maturity or tracking, undeclared tolerance or signal gaps (coverage only) | Info |

No Critical applies: signal correlations cannot evidence a material serving, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
- Bucket table per campaign, signal and grain: periods, weekday mix, impressions, clicks, cost, conversions, value, rates, relative difference against baseline, gate status, tolerance and parameter sources.
- Signal quality: rows, duplicates, conflicts, unmatched performance periods and source.
- Each hypothesis states the correlation, sample sizes, window, maturity and tracking basis. An accepted proposal adds type, scope, metric, allocation or modifier, duration, stop rule and approval owner, and is request-only.

Exposure is not savings, and no uplift is forecast. Seasonality events belong to skill-146, day-hour controls to skill-057, geographic efficiency to skill-054 and modifier layering to skill-048. Live weather/TV APIs are never called; the client supplies the series.
