---
name: skill-159-ai-max-for-search-campaign-assessment
description: "Review real Search AI Max controls and business safeguards; non-adoption is a legitimate choice."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: platform
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 159: AI Max Configuration and Experiment Assessment

## Purpose

Review real Search AI Max controls and business safeguards; non-adoption is a legitimate choice.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Search campaigns with current account-specific AI Max availability/settings; no arbitrary conversion-volume eligibility rule.

**Required inputs:**
- Base `export/` tables: account, campaigns, bidding_strategies, keywords, negative_keywords, shared_negative_lists, ads, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/ai_max_config.csv`: account_id/campaign_id/ad_group_id/snapshot_at grain; availability, ai_max_enabled, search_term_matching_enabled, text_customization_enabled, final_url_expansion_enabled, brand_controls, url_inclusions, url_exclusions, ad_group_overrides, enabled_at, source_screen, supported_control_help_url; current Ads AI Max configuration including disabled and unknown.
- `export/external/ai_max_safeguards.csv`: campaign_id/requirement_id grain; allowed_domain_paths, forbidden_content_or_claims, mandatory_copy, approved_brand_terms, landing_page_snapshot_ref, tracking_evidence_ref, business_goal, owner, approval_status; current client restrictions and page evidence.
- Optional `export/custom/ai_max_experiment_daily.csv`: account_id/experiment_id/arm_id/campaign_id/date grain; assignment_method, traffic_split, start/end_dates, changed_features, impressions, clicks, cost, conversions, conversion_value, qualified_outcomes, goal_id; Ads experiment export for complete mature baseline/test dates.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Inventory actual top-level and per-feature states plus ad-group overrides. Ordinary campaign/strategy metrics cannot reveal AI Max configuration; unknown is not disabled.

2. Check current supported controls and conversion-based Smart Bidding readiness from UI/docs rather than requiring 30/100 conversions. Campaign-level search-term matching must be enabled before ad-group activation is effective; ad-group brand inclusions can override campaign inclusions. AI Max Search is not PMax.

3. Review search-term matching, text customization and final URL expansion separately against brand, query, URL, mandatory-copy and tracking restrictions. A dedicated lead form does not automatically make URL expansion inappropriate.

4. Final URL expansion requires text customization; URL exclusions are campaign-level and URL inclusions ad-group-level. Inspect actual generated/selected-page evidence if supplied. Expanded-page selection or URL inclusions can bypass RSA pins, so mandatory-copy safeguards need explicit review; never assume URL inclusions restrict expansion to only included pages while expansion remains enabled.

5. For enabled campaigns, pre/post changes are descriptive and confounded. A causal claim requires a real controlled experiment with assignment, comparable goals, mature samples and concurrent-change controls.

6. Propose opt-in per-feature experiment or no change: baseline, primary economic metric, client risk floor/cap, allocation method, duration based on detectable effect/lag, stop/recovery conditions and owner. Never enable all features or promise uplift.

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
| Confirmed material live generated-content or destination breach of approved safety restriction | Critical |
| Evidenced feature configuration conflicts with documented business safeguards | Warning |
| Non-adoption, sparse results or unverified availability/settings | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Actual feature/override/safeguard matrix with source snapshot and evidence gaps.
- Controlled-test proposal or justified no-change decision, no mandatory adoption or inferred incremental uplift.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.

[AI Max features](https://support.google.com/google-ads/answer/15910187?hl=en) and [setup controls](https://support.google.com/google-ads/answer/15909989?hl=en).
