---
name: skill-145-prelaunch-compliance-checklist
description: "Review actual launch drafts and evidence for internal readiness, never certify legal compliance or promise platform approval."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: compliance
  kind: operational
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | copy_format validation (index #114)"
---
# Skill 145: Prelaunch Policy Readiness Checklist

## Purpose

Review actual launch drafts and evidence for internal readiness, never certify legal compliance or promise platform approval.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** An explicitly scoped launch package with target markets, product and intended launch dates.

**Required inputs:**
- Base `export/` tables: account, campaigns, ads, assets (existing material is reference only), using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/launch_drafts.csv`: launch_id/draft_id/version grain; proposed_campaign_id, ad_group_or_asset_group_id, ad_type, full_copy, assets_refs, final_urls, product_or_service, claims, target_markets, languages, audiences, network, launch_at, owner; actual current client launch drafts, local temporary IDs allowed.
- `export/external/launch_evidence.csv`: launch_id/draft_id/requirement_id grain; official_policy_url, checked_at, applicable_market/product, prohibited_or_restricted_or_editorial, claim_substantiation_ref, certification_or_authorization_ref, scope, valid_from/to, page_snapshot_ref, technical_diagnostics_ref, reviewer_role, review_status; client claim documents, target settings and page evidence current to proposed launch.
- Optional pre-upload copy validation: `launch_drafts.csv` columns headlines and descriptions (JSON list or ` | `-separated), path1 and path2 for ad_type RSA.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.
Without headlines/descriptions columns the copy-format check is skipped; non-RSA drafts and drafts without structured copy are not format-validated.

## Analysis Steps

1. Freeze package version and inventory every draft/asset/target. Existing approved ads do not establish new-draft readiness.

2. Identify applicable prohibited versus restricted content separately; restricted content can be allowed with market-specific conditions. Do not label all adult/restricted categories prohibited.

3. Check claims against dated evidence, offers and landing-page snapshots. Missing substantiation stays unresolved, not an invented confirmed false claim.

4. Check editorial issues with language, brand and acronym exceptions; verify destination functionality and applicable privacy/data requirements through supplied evidence.
   Before any upload, check RSA copy against [official limits](https://support.google.com/google-ads/answer/7684791) (consulted 2026-09-25), exact duplicate values and uploadable http(s) final URLs; each violation is a confirmed draft conflict (not_met).

5. Check actual targeting and authorization/certification scope and validity. Refer legal or regulated-service interpretation to qualified owners, not assistant certification.

6. Assign each check met/not_met/unknown/not_applicable with evidence. Internal readiness is ready_for_owner_review, changes_required or evidence_incomplete; never APPROVED meaning Google approval. No launch, submission or policy appeal occurs.

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
| Directly evidenced prohibited or material safety issue in the scoped launch package | Critical |
| Confirmed draft conflict with applicable requirement or required scoped authorization | Warning |
| Missing draft/page/claim evidence or unresolved policy interpretation | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Versioned draft-by-requirement checklist with applicability, sources, unknowns and responsible owner.
- Internal readiness decision and blocking prerequisites; explicit not legal certification, not Google approval and no launch execution.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
