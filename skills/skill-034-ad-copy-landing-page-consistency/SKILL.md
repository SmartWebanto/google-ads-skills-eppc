---
name: skill-034-ad-copy-landing-page-consistency
description: "Compare ad promises with dated local landing-page evidence and distinguish confirmed mismatches from missing verification."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: external
  related: [skill-069-landing-page-experience-assessment, skill-078-landing-page-speed, skill-079-broken-url-monitoring, skill-125-landing-page-health-check-automation, skill-141-landing-page-policy-compliance]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 034: Ad Copy-to-Landing Page Message Consistency

## Purpose

Find evidenced promise/destination contradictions without treating absent page content, homepage use or differing CTA wording as automatic defects.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Ads with accessible client-supplied page snapshots for the actual destination/device/locale.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/keywords`, `export/ad_metrics`: IDs, copy, final URLs, intent context and mature traffic for prioritization.
- `export/external/landing_page_snapshots.csv`: one account_id/url/device/locale/captured_at row, resolved_url, title, visible_text, offer_terms, availability, CTA, screenshot_or_snapshot_ref, source_ref. Local supplied snapshots must match campaign geography and offer dates.
- `export/external/ad_claim_register.csv`: one account_id/ad_id/claim_id row, claim_text, supporting_source, market, valid_from/to, qualification, reviewer_role and verification_state; client-provided offer/claim records.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without page/claim evidence perform only URL/promise mapping and list exact missing snapshots or claim support; unverifiable is not false.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Build stable ad-to-final-URL mappings; preserve meaningful parameters, redirect destinations and device-specific URLs. Do not equate a shared hostname with the same page.

2. Extract factual promises, products, prices, conditions, timing and CTAs with exact quotations and field indices. Separate subjective style from factual commitments.

3. Match each promise to a page snapshot and claim record for the same locale/device and valid dates. Dynamic/personalized pages may require more than one capture.

4. Classify matches as corroborated, contradicted, ambiguous or unverified, citing both ad and page text. Absence in an incomplete snapshot is unverified.

5. Check offer qualification and product availability rather than demanding identical words. Different ad/page CTAs may legitimately represent successive funnel steps.

6. A homepage is appropriate when it fulfills the promise and intended journey. Never mandate dedicated landing pages from URL structure alone.

7. Prioritize confirmed mismatches in eligible ads using observed traffic and business materiality. A snapshot cannot attribute an entire month of spend to a temporary failure.

8. Propose precise claim/URL corrections for owner review. Route technical health to 125 and policy judgments to 141; performance improvement remains a test hypothesis.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed current offer/product contradiction in an eligible ad destination | Warning |
| Directly evidenced materially harmful deceptive message reaching users | Critical |
| Missing/stale page evidence, homepage destination or different CTA wording alone | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Claim-to-page evidence map, stable ad IDs, URLs, exact quoted contradictions and validity dates.
- Verification requests separately from correction proposals; no fabricated bounce, QS or conversion impact.
