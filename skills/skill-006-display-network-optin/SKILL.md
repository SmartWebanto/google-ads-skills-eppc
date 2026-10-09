---
name: skill-006-display-network-optin
description: "Review Search campaign Display opt-in against approved intent and network outcomes, not a blanket disable rule."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: custom_query
  related: [skill-005-search-partners-performance]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 006: Display Network Opt-In Review

## Purpose

Review Search campaign Display opt-in against approved intent and network outcomes, not a blanket disable rule.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Search campaigns with an exposed content-network control; standalone Display campaigns are not an opt-in defect.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/campaign_metrics`: IDs, channel, network settings, goal and target.
- `export/custom/network_daily.csv` from Campaigns UI report segmented by day/network, bounded to export dates:
  one account_id/campaign_id/date/ad_network_type row; impressions, clicks, cost, conversions,
  conversion_value, goal_scope, conversion_date_basis. Declare units, filters and completeness.
- Distinguish SEARCH, SEARCH_PARTNERS and CONTENT using the export's explicit network mapping.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without the actual setting mark opt-in unknown; without CONTENT metrics do not estimate Display spend or efficiency.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Filter Search campaigns by channel, then inventory explicit content-network settings.
   Do not claim a platform default or infer opt-in from the presence of a separate Display campaign.

3. Ask whether supplemental Display delivery is an approved objective using supplied business constraints.
   Enabled by design is not a failure; unknown intent is an owner-review question.

4. Reconcile CONTENT metrics to network totals and compatible campaign totals by date.
   Display spend share = CONTENT cost / total campaign cost, never daily budget.

5. Compare mature network outcomes using the campaign KPI and compatible goals.
   Lower Display conversion rate alone does not establish inferior economics.

6. Use spend share only for prioritizing review; screen mature zero-conversion exposure at {{spend_floor}}.
   Confirm tracking and relevance before proposing a change.

7. For an evidenced intent mismatch propose review of the supported network setting.
   Consider a separate Display campaign only if independent objectives/budgets justify operational complexity.

8. Do not forecast recovered spend or Search traffic after exclusion.
   Route partner-specific findings to 005 to avoid duplicated recommendations.

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
| Explicit opt-in contradicts approved Search-only delivery requirement | Warning |
| CONTENT zero conversions at {{spend_floor}} after maturity/tracking/relevance checks | Warning |
| CONTENT spend >5% of campaign cost without other evidence | Info |
| Enabled setting alone or insufficient economic evidence | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Show setting timestamp, CONTENT cost, compatible campaign-cost denominator and business intent.
