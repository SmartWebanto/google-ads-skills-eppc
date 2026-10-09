---
name: skill-142-trademark-policy-management
description: "Inventory trademark usage and platform restrictions against scoped authorization evidence without making legal determinations."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: compliance
  kind: analyst
  data_source: external
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 142: Trademark Use and Authorization Review

## Purpose

Inventory trademark usage and platform restrictions against scoped authorization evidence without making legal determinations.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Ads containing supplied trademark terms or actual trademark policy topics in relevant markets.

**Required inputs:**
- Base `export/` tables: account, campaigns, ads, assets, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/trademark_register.csv`: trademark_id/market/authorization_id grain; term, owner, advertiser_relationship, permitted_use, permitted_accounts, permitted_markets, supporting_document_ref, valid_from, valid_to_if_documented, request_id, request_status, reviewed_at, legal_owner; client authorization/ownership records current at snapshot.
- `export/external/trademark_page_evidence.csv`: URL/market/captured_at grain; page_snapshot_ref, reseller_or_information_context, claim_text, business_identity; local client landing-page evidence for used terms.
- `export/custom/trademark_policy_status.csv`: account_id/ad_id/topic/snapshot_at grain; campaign_id, ad_group_id, approval_status, serving_status, limitation, request_id_if_known; Ads policy diagnostics for all reviewed ads, not only disapproved rows.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Match supplied terms to actual ad text/assets; distinguish text use, domain/path use and keyword targeting. Potential matches require context, not automatic legal-risk labels.

2. Join actual policy topics and serving status; a disapproved ad need not silence an entire ad group if other eligible ads serve.

3. Review market, reseller/informational context and authorization scope; competitor mention without an exemption is not universally prohibited.

4. Track pending/approved/denied requests from records. Only use an expiry date actually documented; do not invent periodic renewal mechanics or equate permission with platform approval.

5. Propose scoped copy alternatives or an evidence-backed review/authorization request to the responsible specialist. Missing documentation is an evidence gap; no legal certification, requests submitted or ad removals.

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
| Confirmed material delivery blockage from platform trademark restrictions | Critical |
| Documented use conflicts with supplied authorization scope | Warning |
| Unknown permission, pending request or context-dependent trademark mention | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- Term/ad/market/authorization matrix and actual policy restriction evidence.
- Documented expiry/request queue only where supported, with specialist owner and request-only next step.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
