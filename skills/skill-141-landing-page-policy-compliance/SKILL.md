---
name: skill-141-landing-page-policy-compliance
description: "Review policy applicability and supplied page evidence; distinguish technical health from policy findings and legal certification."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: compliance
  kind: analyst
  data_source: external
  related: [skill-034-ad-copy-landing-page-consistency, skill-069-landing-page-experience-assessment, skill-078-landing-page-speed, skill-079-broken-url-monitoring, skill-125-landing-page-health-check-automation]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixOperationsSeasonal | corrected evidence, controls, thresholds and request-only outputs"
---
# Skill 141: Landing Page Policy Evidence Review

## Purpose

Review policy applicability and supplied page evidence; distinguish technical health from policy findings and legal certification.

This is a local evidence review. Recommendations are proposals, not permission to act on an account or disclose client data.

## Data Requirements

**Applicability:** Ad destinations for the specific target market, product, claim and data-collection use case.

**Required inputs:**
- Base `export/` tables: account, campaigns, ads, keywords, assets, using [DATA_CONTRACT](../_resources/DATA_CONTRACT.md).
- Read client objectives, parameter overrides, currency, timezone, snapshot, report completeness, conversion-date basis and lag maturity.
- `export/external/page_policy_evidence.csv`: URL/market/device/captured_at grain; final_url, page_snapshot_ref, visible_business_identity, contact_details, privacy_link_and_text_ref, data_collected, offer_and_claim_text, http_status, tls_result, mobile_task_result, timing_metric/value, test_method; client page snapshots and diagnostics current to review.
- `export/external/page_policy_requirements.csv`: requirement_id/market/product/use_case grain; official_policy_url, checked_at, requirement_text, applicability_reason, authorization_or_certification_ref, reviewer_role; current client policy review with authoritative source references.
- `export/custom/page_policy_status.csv`: account_id/ad_id/policy_topic/snapshot_at grain; campaign_id, approval_status, serving_limitation, affected_url, review_status; Ads policy diagnostics at review time.

Keep original source labels and stable IDs; filenames are suggested local intake paths, not assumed existing files.
Custom/configuration schemas describe UI/export evidence, not a claim of live API field verification.

**Missing inputs:** List exact missing files/columns, source dates and affected subchecks.
Continue independent inventory or arithmetic with available evidence; skip only dependent checks.
Optional evidence gates only its stated deeper comparison, forecast or test-result analysis.
Unknown settings, authorization, coverage or policy applicability are not false/disabled and are not a passed check.

## Analysis Steps

1. Map each active destination to market/product and a concrete policy requirement; do not impose privacy/contact/speed requirements universally without applicability evidence.

2. Inspect supplied page content and diagnostics. A URL or Ads approval status does not prove page privacy, TLS, accessibility or offer accuracy.

3. Separate observed content mismatch, platform-reported disapproval, technical best-practice issue and unresolved policy interpretation.

4. For privacy/authorization requirements, record missing evidence as unknown and request specialist review; do not claim legal compliance or certify lawful collection.

5. Prioritize confirmed user-blocking failures and affected serving scope. Technical speed or mobile concerns do not alone establish policy violation or Quality Score loss.

6. Route URL monitoring to skill-125 and ad/offer mismatch to skill-034; propose evidence-backed remediation with policy and technical owners, without page/account changes.

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
| Confirmed material active destination failure or directly evidenced applicable safety breach | Critical |
| Page evidence conflicts with an applicable documented requirement | Warning |
| Missing page/authorization evidence or technical best-practice opportunity | Info |

Insufficient evidence or sample is Info. Critical requires directly evidenced material delivery, measurement or safety failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a conflicting report format.
Each finding includes skill/entity IDs, condition key, severity, observed values and evidence references, exact window,
sample, resolved threshold, recommendation, uncertainty, responsible owner and dependent skipped subchecks.

- URL/market/requirement matrix with observation, source date, policy versus technical classification and unknowns.
- Internal review conclusions only; no legal certification or guarantee of platform approval.

Separate observations, hypotheses and requested changes. No account writes, rule installation, subscriptions,
notifications, exclusions, feed edits, legal certification or external data transfers occur in this review.
Any implementation request must name exact scope/values, approval owner, monitoring and recovery conditions.
