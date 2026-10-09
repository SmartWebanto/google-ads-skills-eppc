---
name: skill-030-ad-extension-coverage-audit
description: "Inventory eligible asset coverage across account, campaign and ad-group associations without mandatory feature counts."
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
# Skill 030: Ad Asset Association Coverage Audit

## Purpose

Identify verified asset association and eligibility gaps while preserving valid optional-feature choices. Account-level absence does not imply no coverage at campaign or ad-group level.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Asset types supported by the campaign subtype and intended business function; calls, prices, promotions and lead forms are not universal requirements.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/assets`: full asset inventory, asset_id, type, fields, association level, account/campaign/ad_group/entity IDs, association status, approval, schedule and source when supplied.
- Client profile: campaign objectives, business type and applicable call/offer/service context.
- `export/assets` completeness/filter declarations must explicitly include all account-, campaign- and ad-group-level associations, including paused and zero-impression entries.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Missing linking levels, entity IDs or applicability/settings prevent absence and effective-coverage findings at that scope. Unknown schedules and eligibility are not disabled.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Read the canonical `export/assets` table, not ext_*.md files. Construct the entity spine from all eligible campaigns/ad groups before joining asset links.

2. Inventory each association by asset ID, type, linking level and linked entity ID. Distinguish unique reusable assets from association counts and exclude removed links from active coverage.

3. For each entity/type show direct and potential inherited links separately. Resolve effective eligibility only using documented type-specific serving/association rules and supplied settings, not a universal nearest-level override rule.

4. Intersect association status, parent status, asset approval, schedule and campaign eligibility. An approved asset is not proof of actual serving; a limited asset may still serve in eligible contexts.

5. Declare complete/partial/unknown inventory at every level. A missing account-level sitelink is not an issue if appropriate campaign/ad-group coverage exists.

6. Assess business usefulness before proposing optional types. Do not require four sitelinks/callouts, every type or universal account-level coverage.

7. Review supplied fields for obvious duplicate text or stale configured dates; missing descriptions are an optional enrichment opportunity unless a documented requirement applies. Route destinations to 031 and policy triage to 037.

8. Prioritize confirmed intended-coverage gaps for owner review; retain alternate layouts and do not forecast a percentage CTR uplift from adding assets.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Intended asset association is confirmed ineligible/disabled and business coverage is affected | Warning |
| No optional asset type or recommended count not met | Info |
| Incomplete hierarchy, eligibility or schedule evidence | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Entity/type matrix showing direct, potential inherited, effective/unknown associations with asset and parent IDs.
- Owner-approved opportunity list and explicit exclusions from the inventory; no blanket account-level absence findings.
