---
name: skill-038-spelling-editorial-error-detection
description: "Review copy and display paths with language, acronym and brand exceptions; distinguish suspected editorial issues from policy decisions."
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
# Skill 038: Spelling and Editorial Review

## Purpose

Offer evidence-grounded editorial corrections without labeling all capitalization, punctuation or spelling anomalies as confirmed policy violations.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Text fields in supplied ads and display paths, in languages the reviewer can assess reliably.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`: stable IDs, full copy, final URLs, status, approval and policy topics.
- `export/custom/ad_editorial_fields.csv`: one account_id/campaign_id/ad_group_id/ad_id/snapshot_at row, ad_type, path1, path2, displayed_domain, source_ref; actual Ads UI/Editor field export, not inferred from final URL.
- `export/external/editorial_brief.csv`: one account_id/locale/term_or_rule_id row, language, preferred_spelling, brand/acronym/industry_term_exception, style_rule, claim_support_ref, reviewer_role and valid_from/to; client style/claim brief.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Missing paths skip path review only. Unknown language/brand exception or claim support produces a review request, not a spelling/policy defect.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Extract text with stable field/index references; keep display paths distinct from destination paths. Separate insertion/customizer syntax from user-visible copy.

2. Determine language/locale from explicit brief and campaign context. Do not assume the account language applies to every ad or auto-correct proper names.

3. Check spelling with brand, acronym, technical vocabulary and regional variants first. Quote suspect token and sentence context, correction proposal and reviewer confidence.

4. Assess grammar with advertising fragments and space constraints in mind; short fragments and sentence case can be intentional.

5. Review repeated punctuation and unusual casing against the current applicable editorial rule and approved brand exceptions. An ALL CAPS acronym is not a blanket violation.

6. Keep unsupported superlatives/claims separate from editorial errors. Refer claim evidence and relevant market policy to the appropriate compliance owner.

7. Use supplied platform policy topics to identify confirmed disapprovals; reviewer suspicion is not a platform decision. Delegate material delivery impact and resolution to 037.

8. Propose minimal copy/path corrections preserving meaning, dynamic syntax, required qualifications and destination. Do not apply changes or promise CTR improvement.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed language error or documented style inconsistency needing owner correction | Warning |
| Suspected policy/editorial issue, unfamiliar term or unsupported language review | Info |
| Capitalized acronym, valid brand spelling or intentional fragment alone | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Exact original/proposed text with field IDs, locale, exception checks and confidence.
- Platform-confirmed policy status kept separate from analyst editorial notes and claim verification.
