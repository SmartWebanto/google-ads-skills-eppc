---
name: skill-122-automated-keyword-pause-rules
description: "Screen mature zero-conversion exposure and draft human-reviewed rule specifications, never install or execute pausing."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: waste
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 122: Keyword Pause Rule Proposals

## Purpose

Screen mature zero-conversion exposure and draft human-reviewed rule specifications, never install or execute pausing.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Search keywords with complete mature metric windows, working conversion tracking and known strategic exceptions.

**Required inputs:**
- Base `export/` tables: account, campaigns, keywords, keyword_metrics, conversion_actions, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/keyword_lifecycle.csv`: account_id/campaign_id/ad_group_id/keyword_id grain; created_at, last_enabled_at, last_material_change_at, tracking_incident_dates, source; Ads history/lifecycle snapshot matching the metric window. Unknown creation time is not an age estimate.
- `export/external/keyword_rule_policy.csv`: rule_id/campaign_id grain; objective, approved_lookback_days, lag_buffer_days, minimum_active_age_days, strategic_keyword_ids, brand_terms, target_cpa, owner, approval_status, review_cadence, rule_cap; client policy at snapshot.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Resolve {{spend_floor}} and policy lookback/lag before screening. Use a complete window ending before the lag buffer; re-export if base metrics do not match it.

2. Eligible zero-conversion keywords at cost >= {{spend_floor}} become review candidates, not immediate pause instructions. min_conversions does not apply to this zero-conversion screen; tracking/relevance/maturity still do.

3. Exclude documented brand/strategic tests and keywords younger than the approved age. Unknown lifecycle blocks the age-dependent automatic-rule proposal, not the exposure inventory.

4. Check matched intent and working conversion actions; do not substitute account average CPA when goals differ. Sparse CTR uses {{min_impressions}}, never a fixed 1000 threshold.

5. Draft alert/review-first rule: entity IDs, metric window, lag, spend threshold, exclusions, evaluation cadence, maximum affected scope, owner, approval requirement and recovery condition. Any pause remains a request-only proposal.

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
| Mature relevant zero-conversion exposure >= {{spend_floor}} | Warning |
| Lifecycle, tracking, strategic scope or mature window unknown | Info |
| Low CTR alone or candidate approaching the floor | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Keyword candidate ledger with exact floor, dates, maturity and exceptions; historical exposure not savings.
- Complete review-first rule specification and false-positive/rollback safeguards.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
