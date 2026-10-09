---
name: skill-003-naming-convention-consistency
description: "Inventory campaign and ad-group names with reproducible consistency scoring and safe rename proposals."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: structure
  kind: analyst
  data_source: external
  related: [skill-008-label-organizational-structure]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 003: Naming Convention Consistency

## Purpose

Inventory campaign and ad-group names with reproducible consistency scoring and safe rename proposals.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Campaign/ad-group naming; enforce a standard only where the owner supplies an approved convention.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/ad_groups`: IDs, parent IDs, names and status.
- Profile naming convention: entity type, delimiter, ordered fields, allowed values and exceptions.
- Optional `export/external/naming_dependencies.csv`: one consumer/rule at review snapshot;
  consumer_id, entity_type, account_id, campaign_id, name_pattern, expected_behavior, observed_failure,
  evidence_ref, owner, reviewed_at from supplied reporting/automation configuration.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without a convention report inferred patterns only; without consumer evidence omit operational-failure claims.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Separate campaigns from ad groups and enabled from paused/archived inventory.
   Preserve original strings and IDs for any rename proposal.

3. Parse the approved delimiter, ordered fields and allowed values.
   Without a standard show delimiter/field-count clusters, not compliance failures.

4. Define consistency = conforming applicable entities / applicable entities, excluding documented exceptions.
   Show the denominator; an empty scope is not 100% compliance.

5. Check duplicate campaign names within account and ad-group names within campaign.
   Identical ad-group names across campaigns are valid; distinguish exact and case/space near-matches.

6. Review placeholders and misleading channel/market segments against the approved convention.
   Arbitrary 100-character preferences are not platform limits.

7. Link offending names to supplied report/parser dependencies before claiming breakage.
   Identify affected consumers and prefer ID-based joins; do not execute renames.

8. Propose minimal before/after names preserving meaning and uniqueness.
   Label taxonomy belongs to 008; this recipe does not audit labels from names alone.

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
| Naming mismatch causes a demonstrated consumer/reporting failure | Warning |
| Consistency below 80% without proven operational impact | Info |
| Duplicate in correct scope, placeholder or proposed standard | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Report scoped consistency counts, proposed names and dependency owners.
