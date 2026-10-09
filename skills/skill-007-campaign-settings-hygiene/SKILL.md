---
name: skill-007-campaign-settings-hygiene
description: "Check campaign settings against documented delivery requirements without reviving expired promotions or assuming omitted settings."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: external
  related: [skill-005-search-partners-performance, skill-006-display-network-optin, skill-053-location-targeting-method-audit]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 007: Campaign Settings Hygiene

## Purpose

Check campaign settings against documented delivery requirements without reviving expired promotions or assuming omitted settings.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Controls supported by each campaign channel and current bidding strategy; historical settings require effective dates.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/bid_adjustments`, `export/bidding_strategies` and `export/campaign_metrics`.
- Channel/subtype, status, start/end dates, networks, languages, schedule, geo targets/methods,
  device exclusions/modifiers, strategy IDs and snapshot; use account timezone.
- `export/external/campaign_requirements.csv`: one campaign/requirement/effective-window row from owner brief;
  account_id, campaign_id, requirement_type, approved_value, effective_start, effective_end,
  approval_ref, owner. Include service-area, language, promotion dates and device restrictions.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without expected settings report inventory only; without individual control values skip that control rather than infer defaults.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Build a settings matrix by channel and supported controls, distinguishing unknown from false.
   Use UI/Editor settings evidence for fields missing in the export; do not invent GAQL date fields.

3. Compare geo method with the service model and approved area: presence-or-interest can be intentional.
   Refer detailed geographic interpretation to 053 rather than mandate presence everywhere.

4. Compare start/end dates in account timezone to the approved operating/promotion window.
   A past end date may be intentional even if status says enabled.

5. Never remove a promotion end date to restore delivery.
   Request owner confirmation of renewed eligibility, dates, budget and creative before proposing revival.

6. Review language coverage against supported customer languages and actual setting evidence.
   An absent export field is not evidence of no languages configured.

7. Distinguish device exclusions from bid modifiers; verify strategy-specific support.
   Smart Bidding generally does not use ordinary CPC modifiers; tCPA device target behavior is not a CPC adjustment.

8. Delegate network performance to 005/006 and retain only documented requirement mismatches here.
   Prioritize proven delivery blockage, not arbitrary configuration preferences.

## Thresholds

Resolve [PARAMETERS.md](../_resources/PARAMETERS.md) and profile overrides before screening.
Numerical decision cutoffs below are triage heuristics, not platform requirements or causal proof.
Compare CTR only with {{min_impressions}} impressions and conversion rates with {{min_clicks}} clicks
on each side; CPA/ROAS comparisons require {{min_conversions}} mature conversions on each side.
Zero-conversion screening is an exception to the conversion-count gate, not permission to pause:
require working tracking, a mature comparable window, relevance review and {{spend_floor}}.
Do not divide by zero; absent targets use an applicable profile target, otherwise omit target comparisons.

| Condition | Severity |
|-----------|----------|
| Required active delivery is demonstrably blocked by an unintended setting with material impact | Critical |
| Explicit setting conflicts with approved requirement; impact not established | Warning |
| Expired promotion, presence-or-interest or device exclusion without contrary intent | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Show actual/expected values, supporting brief, settings timestamp and proposed owner review.
