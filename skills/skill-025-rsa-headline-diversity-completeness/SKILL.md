---
name: skill-025-rsa-headline-diversity-completeness
description: "Inventory RSA headline diversity and descriptive Ad Strength without asset-count quotas or uplift claims."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: export
  merged_from: [skill-027-ad-strength-improvement]
  related: [skill-026-rsa-description-optimization, skill-028-rsa-pinning-strategy-audit, skill-029-rsa-asset-performance-analysis, skill-032-ad-copy-ab-testing]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | rsa_draft opt-in (index #113)"
---
# Skill 025: RSA Headline Diversity and Ad Strength Review

## Purpose

Separate reproducible headline duplication checks from analyst judgments about message coverage. Absorbs Ad Strength inventory from 027; Ad Strength is a creative diagnostic, not proof of a serving penalty, causal performance, or a required optimization target.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Responsive Search Ads; retain parent/ad status and distinguish active coverage from paused inventory.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`: IDs, status, RSA type, full headline/description arrays, pins, approval and Ad Strength snapshot.
- `export/ad_metrics` and `export/campaign_metrics`: IDs, impressions, clicks, cost, conversions and value over the same mature window, only for prioritization/descriptive comparisons.
- Client profile: declared campaign objectives, brand terms and product/service context; never infer these from campaign names.
- Opt-in draft request: `profile.rsa_draft_requests` (ad group IDs, or `{campaign_id, scope: enabled_ad_groups|all_ad_groups}`), with `export/keywords` (ad_group_id, text, status, final_url), ads `final_url`, and optionally `profile.approved_claims`, `competitor_terms`, `excluded_intent_terms` and campaign `brand_policy`.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without complete arrays skip completeness/duplicate counts; unknown Ad Strength is Unavailable, not Poor. Without metrics omit spend ranking, not the copy inventory.
Without `rsa_draft_requests` the draft check is not applicable; a requested ad group without an existing final URL gets no draft review, and without keywords keyword insertion is rejected.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Left-join RSA inventory to parent entities; report included and omitted statuses and the complete-array denominator. Do not infer no ads from a metrics-only report.

2. Preserve raw headline text. For duplicate matching use Unicode NFKC, case folding, trimmed/collapsed whitespace; preserve punctuation and numbers in exact normalized matching. Record original asset index where no asset ID exists.

3. For near-duplicates tokenize normalized words and calculate Jaccard overlap = intersection / union of unique token sets. An overlap above 0.70 is an Info review heuristic; empty sets are unavailable. Retain numeric/negation differences for human review.

4. Count supplied and normalized-unique headlines per RSA. Compare draft validity only with current applicable platform limits; fewer than five or fewer than fifteen is not evidence of delivery failure.

5. Tag themes as brand, benefit, feature, evidence, offer, CTA or other, quoting text and explaining ambiguity. No universal theme quota; urgency and social proof require truthful business support.

6. Inventory every supplied Ad Strength category including Unknown. Report count shares and optional spend shares using their own explicit denominators; do not weight or average ordinal categories numerically.

7. If describing outcomes by rating, stratify by objective, language and traffic role; gate both samples and call results observational. Do not promise impression uplift or replace a performing ad to improve its label.

8. Propose distinct, truthful headline concepts only where a business-relevant gap exists. Route descriptions to 026, mandatory messaging/pins to 028 and causal creative evaluation to 032.

9. Only for ad groups in `profile.rsa_draft_requests`, propose one complete RSA draft from the group's own copy, keywords, existing final URL and approved claims; `finalize` rejects drafts outside [official limits](https://support.google.com/google-ads/answer/7684791) (consulted 2026-09-25), with bad pins or insertion fallbacks, duplicates, competitor/excluded terms, unapproved numbers or a new final URL.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Normalized duplicates or near-duplicate overlap above 0.70; subjective theme gap | Info |
| Poor/Average Ad Strength, unfilled optional capacity, or missing rating | Info |
| Confirmed misleading repeated claim or documented creative constraint violation requiring owner review | Warning |
| Requested RSA draft that passed `finalize` validation (opt-in `rsa_draft_requests`) | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Headline-level normalized duplicate groups, similarity numerator/denominator and analyst theme rationale.
- Ad Strength distribution with snapshot, rating coverage, ad IDs and separate spend-priority context; no promised rating or performance gain.

Sources: [Google RSA guidance](https://support.google.com/google-ads/answer/7684791).
