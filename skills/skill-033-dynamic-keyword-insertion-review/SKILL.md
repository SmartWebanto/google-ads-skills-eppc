---
name: skill-033-dynamic-keyword-insertion-review
description: "Review DKI syntax, keyword insertions and fallback text with explicit brand and authorization context."
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
# Skill 033: Dynamic Keyword Insertion Review

## Purpose

Detect credible insertion/fallback risks without assuming oversized keywords overflow or broad match inserts the user query.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Ads containing supported keyword insertion syntax; distinguish other customizers and countdown syntax.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/keywords`: full text templates, final URLs, keyword text/match/status and stable IDs.
- Client profile: brand_terms, competitor_terms, excluded_intents and campaign objectives.
- `export/external/dki_review.csv`: one account_id/ad_id/field/keyword_id/review_at row, language, rendered_preview, fallback_preview, preview_source, allowed_term_status, authorization_ref, reviewer_role and rationale; client-provided Ads preview/brand review current at snapshot.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Missing keyword coverage limits preview completeness. Unknown competitor status or authorization is a request for specialist review, not a proven trademark violation.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Extract insertion tokens and record exact ad field, syntax variant and fallback text; do not classify every brace-delimited customizer as DKI.

2. Check balanced syntax and fallback presence against current supported insertion format. Suspected parse errors need an Ads preview or policy diagnosis before claiming delivery failure.

3. Join eligible keyword text within the same campaign/ad group. DKI uses the triggering keyword, not arbitrary search-query text; broad match alone does not establish unsafe inserted content.

4. Preview capitalization variants in the actual field context. Respect local language, brand case and acronym exceptions rather than universally rejecting capitals.

5. When an insertion cannot fit the field, assess whether the fallback fits and remains coherent. A long keyword with a valid fallback is expected behavior, not automatic overflow.

6. Review keyword and fallback combinations for grammar, sensitive claims and business relevance with literal examples. Check the complete rendered text, not token length alone.

7. Use explicit competitor terms and supplied authorization/context. Potential trademark or policy questions go to the responsible owner; never infer ownership, prohibition or legal clearance from a name.

8. Propose corrected fallback/template wording preserving the intended offer and any mandatory qualification. Unsupported previews remain hypotheses; no automatic keyword exclusions or DKI removals.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed invalid template/fallback or materially misleading rendered message | Warning |
| Potential competitor/sensitive insertion requiring authorization review | Info |
| Oversized keyword with valid fallback, broad match alone or uppercase acronym | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Template/keyword/fallback preview matrix keyed by ad field and keyword ID, with evidence timestamps.
- Owner-reviewed corrections and explicit unverified preview/authorization items, not policy certification.
