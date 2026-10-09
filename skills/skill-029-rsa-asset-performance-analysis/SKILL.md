---
name: skill-029-rsa-asset-performance-analysis
description: "Join RSA asset associations and ad outcomes by stable IDs; use contextual labels as review evidence, not account-wide rankings."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: custom_query
  merged_from: [skill-126-rsa-asset-performance-bulk-analysis]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 029: Contextual RSA Asset Performance Analysis

## Purpose

Find context-specific copy hypotheses from RSA asset reports without treating Low as an automatic replacement rule or Best as universal creative quality.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** RSA headline/description associations only; never pool PMax, display or unrelated asset types into RSA label rankings.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/ad_metrics`: complete RSA inventory and ad-ID keyed mature metrics.
- `export/custom/rsa_asset_labels.csv`: one association snapshot per account_id/campaign_id/ad_group_id/ad_id/asset_id/field_type/snapshot_at; ad_type, text, pin, association_status, performance_label, label_availability_reason, source_ref. Use a current Ads UI asset report or supported API export; keep unavailable labels explicit.
- Optional `export/custom/rsa_asset_metrics.csv`: one association/date/segment row keyed by the same IDs plus date and segment_keys; impressions, clicks, cost, conversions, conversion_value, metric_scope and attribution_definition. Window matches ad metrics; unsupported metrics remain null.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without ad ID or association keys skip label-to-ad joins; absent labels are unavailable, not Low. Without label history never infer a persistent downgrade.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Start from all in-scope RSA ads, then left-join association snapshots. Require ad_type=RESPONSIVE_SEARCH_AD and headline/description field types; reconcile asset coverage to full RSA arrays.

2. Join by account, campaign, ad group and ad ID plus asset/field identity. Reject name-only joins and duplicate association keys; the same text can have different IDs and context-specific labels.

3. Use the current supplied label vocabulary; preserve Learning, Pending, Unrated and unknown availability states rather than inventing Best/Low values. Record observation date and source.

4. Summarize labels within ad and field type. Count reused assets once per association in context summaries and once per asset in reuse summaries; do not sum overlapping ad metrics into asset totals.

5. Ad performance stays at ad grain. Only use asset-attributed metrics if their definitions and denominators are supplied; an ad CTR is not the CTR of each headline.

6. Compare outcomes only for matched goals, language, traffic role and mature samples. Normal serving and contextual labels cannot identify causal winners across ads.

7. Review Low-associated text for a specific copy hypothesis, keeping legal/brand constraints. Best patterns elsewhere are inspiration, not universal replacement instructions; no Best label is not a defect.

8. Produce an optional controlled-test brief through 032; route duplication to 025/026 and pin constraints to 028. Preserve bulk coverage inherited from 126 without automatic bulk changes.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Low labels, no Best asset or all Learning/Unrated | Info |
| Matched mature ad outcomes outside business guardrail plus corroborated copy issue | Warning |
| Missing association IDs, labels or metric attribution | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Association-level label table, source/snapshot/coverage and non-duplicated ad performance context.
- Review candidates with hypotheses and constraint-preserving test proposals; no account-wide asset winner list.
