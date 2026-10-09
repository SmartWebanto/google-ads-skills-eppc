---
name: skill-026-rsa-description-optimization
description: "Review RSA description clarity, distinct messaging and validity without mandatory slot filling or length-based quality scores."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: export
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 026: RSA Description Optimization

## Purpose

Identify duplicated or unclear descriptions and useful alternative messages. Short copy and fewer than four descriptions can be intentional; filling optional capacity is not proven to improve effectiveness.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** RSA description fields, with language and parent/ad status preserved.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`: IDs, RSA descriptions, headlines, pins, final URLs, approval and status.
- Client profile: campaign objectives, brand terms and supported product/service propositions.
- Optional `export/ad_metrics`: ad IDs and mature impressions/clicks/cost/conversions/value for prioritization, not asset-level attribution.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Absent description arrays prevent counting; absent business context prevents claim verification and theme recommendations. Metrics are optional.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Inventory description arrays by ad ID and stable array index; separate draft, paused and enabled inventory. Preserve exact text for review.

2. Normalize with Unicode NFKC, case folding and collapsed whitespace for duplicate matching. Do not strip negations, prices or dates; near-duplicate paraphrases remain analyst judgments.

3. Count supplied/unique descriptions and display character lengths, but do not impose an 80–90 character optimum, a minimum copy length or a requirement to fill all four slots.

4. Check field-limit validity against the applicable current RSA format and language counting rules. Missing exported text is not proof that a live ad violates minimum requirements.

5. Read each description with compatible headlines and pins for coherence, unsupported offers and contradictory qualifications. Delegate exact pin guarantees to 028.

6. Identify benefit, action, proof and qualification content with quotations and confidence. CTAs, complete sentences and theme mixes depend on intent; fragments may be legitimate advertising copy.

7. Draft optional alternative concepts grounded in supplied claims, preserving mandatory language and brand style. Do not rewrite legal qualifications or fabricate proof, scarcity or discounts.

8. Prioritize confirmed clarity risks by active business scope; propose a controlled test through 032 for effectiveness claims. Descriptive ad-level performance does not isolate one description.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Duplicate wording, optional empty description slot or short description | Info |
| Confirmed contradictory promise or business-required qualification omitted from valid combinations | Warning |
| Unverified claim or insufficient language/context evidence | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Per-ad description counts, exact duplicate groups, character counts and human-review notes.
- Proposed alternatives with claim source and constraints; no automatic replacements or uplift estimates.

Sources: [Google RSA guidance](https://support.google.com/google-ads/answer/7684791).
