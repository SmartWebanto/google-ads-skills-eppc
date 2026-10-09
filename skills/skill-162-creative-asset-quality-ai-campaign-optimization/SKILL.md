---
name: skill-162-creative-asset-quality-ai-campaign-optimization
description: "Assess channel-specific asset suitability and contextual quality without arbitrary quotas, universal formats or uplift promises."
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
# Skill 162: Creative Coverage and Quality Evidence Review

## Purpose

Assess channel-specific asset suitability and contextual quality without arbitrary quotas, universal formats or uplift promises.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** PMax, Demand Gen and Search creative at the actual ad/asset-group association grain; channel requirements must be verified for subtype.

**Required inputs:**
- Base `export/` tables: account, campaigns, ad_groups, ads, assets, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/custom/creative_group_inventory.csv`: account_id/campaign_id/group_type/group_id/snapshot_at grain; subtype, status, goal, business_theme, eligibility_status; all Ads groups including groups with zero linked assets.
- `export/custom/creative_quality_assets.csv`: account_id/group_id/ad_id/asset_id/association_id/snapshot_at grain; asset_type, field_role, linked_status, policy_status, text, width, height, duration_seconds, provenance (custom/generated/unknown), source_ref, performance_label, label_date; Ads associations plus actual asset metadata at snapshot.
- `export/custom/creative_label_history.csv`: association_id/observed_at grain; label, impressions, clicks, cost, conversions, conversion_value, reporting_context; dated Ads label/performance exports for claimed review duration; a snapshot does not prove 30 days Low.
- `export/external/creative_requirements.csv`: subtype/format/requirement_id grain; required_or_recommended, supported_asset_spec, official_source_url, checked_at, mandatory_message, brand_rule, evidence_ref, owner; current platform specs and client creative brief.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Left join all groups to asset associations so empty groups remain visible; asset account inventory alone does not prove use in PMax/Demand Gen.

2. Compare actual dimensions/duration with channel/subtype documented minimum requirements, separately from recommended coverage. Do not declare PMax portrait/custom video universally mandatory.

3. Provenance unknown stays unknown; no custom video does not prove auto-generated delivery or poor quality.

4. Normalize text for literal duplicates and annotate qualitative theme review with examples/rubric: same claim, distinct benefit, proof, audience need. Neither fewer than ten headlines nor three same-theme assets is automatically defective.

5. Interpret performance labels within their association/context, not as causal ranks. Persistent-label claims require dated history; low labels alone do not justify replacement.

6. Route detailed RSA text to skill-025/026 and video/image checks to skill-035/036/093. Propose brief-backed creative tests with distinct hypotheses, owner and outcome metric; no count quotas or delivery uplift forecast.

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
| Confirmed required-asset failure materially blocks intended eligible delivery | Critical |
| Actual asset conflicts with documented required spec or approved message constraint | Warning |
| Optional format/custom video missing, contextual Low label or subjective diversity opportunity | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Complete group/association coverage with observed specs versus required/recommended source and date.
- Evidence-backed quality examples, label history/unknown provenance and request-only creative test briefs.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
