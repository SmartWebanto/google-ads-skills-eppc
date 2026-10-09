---
name: skill-035-image-asset-optimization
description: "Inventory image associations across actual campaign, asset-group and ad scopes; distinguish minimum requirements from recommendations."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 035: Image Asset Coverage and Format Review

## Purpose

Review usable image coverage and verified format constraints without inferring group absence from campaign-only links or image text quality from dimensions.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Image-capable Search, PMax, Demand Gen and Display subtypes, using current format-specific eligibility rather than blanket campaign rules.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/assets`: parent status and known image links.
- `export/custom/creative_groups.csv`: one account_id/campaign_id/entity_type/entity_id/snapshot_at row; ad_group_id, ad_id, asset_group_id as applicable, subtype, parent_status, entity_status, eligibility and source_ref. Complete Ads UI inventory includes zero-asset PMax asset groups and Demand Gen ads.
- `export/custom/image_associations.csv`: one account_id/entity_type/entity_id/asset_id/field_type/snapshot_at row, linking_level, status, approval, width_px, height_px, mime_type, file_size_bytes, source_ref; full Ads image association export across customer/campaign/ad-group/asset-group/ad scopes.
- `export/external/image_review.csv`: one asset_id/review_at row, local_image_ref, visual_or_OCR_evidence, crop_subject_issue, text_review, reviewer_role and rationale; supplied image files/visual review.
- `export/external/image_format_requirements.csv`: one subtype/field_type/requirement_id/effective_date row, required_or_recommended, min_width/height, ratio/tolerance, max_file_bytes, mime_types, source_url and checked_at; supplied current official specification excerpt.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without the complete entity spine/association levels, no absence conclusion. Without current requirements skip compliance checks; without image evidence skip text/crop judgments.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Start from eligible entities, not image-filtered rows. Retain zero-association groups and label incomplete scopes Unknown. Demand Gen ad associations and PMax asset-group associations are not campaign links.

2. Join actual link IDs to reusable assets and parent entities; count associations and unique images separately. Confirm status, approval and format eligibility at the snapshot.

3. Match requirements by subtype, field type and effective date. A recommended high-resolution size is not the minimum; portrait coverage is not universally mandatory.

4. Compute width/height only when both are positive; check ratio with the stated tolerance, MIME/file-size constraints and actual minimum dimensions. Preserve unknowns.

5. Inspect supplied image evidence for cropping, illegibility, branding or text concerns. Dimensions alone cannot establish excessive text, visual quality or a policy violation.

6. Check the asset group/ad has required eligible image roles under its actual configuration, including feed-backed/automatic alternatives where documented; do not assume an image absence silences every campaign.

7. Report optional ratio and creative-variety opportunities in business context without a three-per-ratio minimum or promised CTR uplift.

8. Request replacements only for corroborated defects and route platform policy blockers to 037; reuse existing suitable assets where context allows instead of demanding new uploads.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Verified required role/specification not met with business coverage affected | Warning |
| Confirmed material delivery block attributed by platform diagnostics to missing/invalid images | Critical |
| Missing optional ratio, recommended resolution or unavailable associations/visual evidence | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Complete entity-to-image coverage matrix with required/recommended distinctions, keys and unknown scopes.
- Per-asset observed dimensions and visual evidence references; no unsupported absence or excessive-text claims.
