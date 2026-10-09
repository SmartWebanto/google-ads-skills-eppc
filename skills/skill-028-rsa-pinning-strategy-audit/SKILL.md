---
name: skill-028-rsa-pinning-strategy-audit
description: "Audit occupied RSA positions, valid pinned alternatives and mandatory message guarantees."
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
# Skill 028: RSA Pinning and Mandatory Message Review

## Purpose

Review pinning against actual business constraints and available rendering positions. Several alternatives pinned to one position are valid; number of pins alone is neither a conflict nor a performance defect.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** RSAs with complete headline/description/pinned-position arrays, including deliberately constrained regulated or brand copy.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`: IDs, full text arrays, pinned positions, statuses and approval.
- `export/external/rsa_message_constraints.csv`: one requirement per account_id/campaign_id/ad_group_id/ad_id/requirement_id, text_or_semantic_requirement, allowed_positions, must_always_show, rationale, approver_role, valid_from, valid_to and source_ref; supplied brand/compliance brief valid at snapshot.
- Optional `export/ad_metrics`: ad-level comparable-window performance for descriptive context only.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Missing pin fields are unknown rather than unpinned. Without constraints report combinations but do not recommend unpinning required messages.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Build separate headline and description slot maps. Preserve each asset identity or stable array index and its explicit pin value; flag unknown/unsupported pin values for verification.

2. For an occupied position, treat all assets pinned there as alternatives, not simultaneous occupants or conflicts. Unpinned assets can fill positions permitted by the actual serving rules.

3. Enumerate structurally eligible assignments without reusing one asset in two slots; count possible assignments only as a theoretical upper bound, not impressions, equal probabilities or actual tested combinations.

4. Assess shorter renderings too: headline 3 and description 2 are not guaranteed. A requirement that must always show must not rely only on those optional positions.

5. For every must-always-show requirement, check every allowed alternative in each guaranteed pinned slot and feasible shorter rendering. One compliant alternative does not guarantee the requirement if another alternative omits it.

6. Record mandatory message gaps by requirement ID and exact incompatible alternatives; distinguish exporter ambiguity from a confirmed configuration gap. Do not claim legal certification.

7. Describe flexibility remaining with constraints held fixed. Multiple headlines pinned to H1 can preserve the requirement while allowing alternatives; never prescribe removal of all pins or a universal pin maximum.

8. Compare pinned/unpinned performance only observationally within matched mature cohorts. A pinning-change experiment requires owner approval, preserved safety copy and the controlled design in 032.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed business-required message not guaranteed in valid rendered alternatives | Warning |
| Several assets in one pinned slot, all positions pinned or high pin count alone | Info |
| Unknown pin values, missing constraints or hypothetical combination reduction | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Slot-to-alternative map and requirement-to-rendering coverage, including optional-position caveats.
- Constraint-preserving proposal with business owner; combinations are theoretical, not causal performance forecasts.

Sources: [Google supported pin alternatives and positions](https://support.google.com/google-ads/answer/7684791).
