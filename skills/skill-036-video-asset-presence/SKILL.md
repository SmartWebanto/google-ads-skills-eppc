---
name: skill-036-video-asset-presence
description: "Review complete video associations, actual formats and supplied provenance without mandatory custom-video quotas."
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
# Skill 036: Video Asset Coverage and Provenance Review

## Purpose

Assess video coverage and creative control using real associations and video evidence. No custom upload does not prove an auto-generated video served, and auto-generated does not inherently mean low quality.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** PMax, Demand Gen, Video and other documented video-capable subtypes; image-only Demand Gen setups can be intentional.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/assets`: full parent and known asset inventory.
- `export/custom/creative_groups.csv`: one account_id/campaign_id/entity_type/entity_id/snapshot_at row with ad_group_id/ad_id/asset_group_id as applicable, subtype, parent/entity_status, eligibility and source_ref; all PMax groups and Demand Gen ads including zero videos.
- `export/custom/video_associations.csv`: one account_id/entity_type/entity_id/asset_id/field_type/snapshot_at row, linking_level, youtube_video_id, association_status, approval, provenance (uploaded/generated/unknown), provenance_source and source_ref; complete current Ads associations including ad-level video references.
- `export/external/video_review.csv`: one asset_id/review_at row, local_video_or_authorized_review_ref, duration_seconds, width/height_px, language, audio/captions, brand_message_review and source_ref; supplied media metadata/visual review.
- `export/external/video_format_requirements.csv`: one subtype/ad_format/requirement_id/effective_date row, required_or_recommended, duration_min/max, allowed_ratios, source_url and checked_at; current official format excerpts. Optional association/date performance must declare impressions, views, conversions and attribution.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without group/ad spine skip absence findings; without duration/ratio/provenance skip those subchecks. Unknown video source is not auto-generated.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Left-join the complete eligible entity spine to all video links; do not derive zero-video entities from a video-filtered report. Preserve ad-level Demand Gen and asset-group-level PMax keys.

2. Inventory eligible videos after parent, association, approval and schedule checks. A customer video library item is not proof it is attached to every campaign.

3. Keep asset type and association field type distinct; use actual exported supported values rather than guessing that both equal YOUTUBE_VIDEO.

4. Resolve provenance only from supplied source evidence. Record uploaded, platform-generated and unknown separately; absent custom video is not evidence of generated serving.

5. Check actual duration/aspect ratio against the matching subtype and format requirements. Do not apply a universal 10–60-second rule or require all three aspect ratios.

6. Review branding, comprehensibility, captions and cropping using supplied media. Lack of metadata cannot establish poor creative quality.

7. Report optional custom-video and alternate-format opportunities against campaign intent, production constraints and actual eligibility; preserve legitimate image-only Demand Gen setups.

8. Analyze video performance only with defined views/interaction attribution and mature matched cohorts. Propose a controlled creative test rather than guaranteeing uploaded video will outperform generated content.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Required video missing/ineligible for the intended verified video format | Warning |
| Direct platform evidence of a material delivery block caused by missing/invalid video | Critical |
| No custom video, optional format absent or unknown metadata/provenance | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Complete group/ad video matrix and supplied provenance evidence, with unknown scope retained.
- Format-specific requirement checks and review-only creative-control/test proposals.
