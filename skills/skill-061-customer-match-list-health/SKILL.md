---
name: skill-061-customer-match-list-health
description: "Review permitted Customer Match use, actual upload freshness, eligibility and campaign application."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: targeting
  kind: deterministic
  data_source: external
  merged_from: [skill-104-customer-match-list-management]
  related: [skill-062-audience-minimum-size-monitoring, skill-156-first-party-data-collection-activation-strategy]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixTargetingQuality | evidence-led audit corrections"
---
# Skill 061: Customer Match List Health

## Purpose

Audit existing Customer Match operations against the business's permitted use and refresh
requirements. Absence of Customer Match, a low reported size or a low match rate alone
is not a failure; health depends on eligibility, data provenance and intended activation.

## Data Requirements

**Applicability:** Businesses with a declared Customer Match use case and authorized
first-party data. Account eligibility, list type, channel and targeting policy matter.
This recipe consumes sanitized diagnostics only, never raw emails, phones or customer rows.

**Required inputs:** [DATA_CONTRACT](../_resources/DATA_CONTRACT.md) `account`,
`campaigns`, `campaign_metrics` and `audiences` with list IDs and scope/mode associations;
client profile customer_lifecycle, objectives, sales cycle and retention/acquisition intent.
- `export/custom/customer_match_status.csv` from Audience manager list details and
  account Customer Match eligibility UI; key account_id/list_id/channel/snapshot_date.
  Columns: list_type, membership_status, membership_duration_days, reported_size,
  size_precision, eligible, eligibility_reason, account_use_eligible, permitted_use,
  match_rate, match_rate_definition, match_rate_available, source, source_date.
  Preserve missing/suppressed rates; do not guess an API match_rate_percentage field.
- `export/external/customer_match_upload_history.csv` from sanitized upload-job/CRM
  synchronization logs; key account_id/list_id/job_id. Columns: submitted_at,
  completed_at, status, operation (replace/add/remove), source_extract_at,
  submitted_count, accepted_count, rejected_count, matched_count_if_reported,
  error_category, source_system, window_start, window_end. Supply the last 90 days
  or full intended refresh interval if longer; partial/add-only jobs are not full refreshes.
- `export/external/customer_match_policy.csv`: one row per account_id/list_id/purpose
  with intended_campaign_ids, authorized_use_status, aggregate_consent_evidence_ref,
  owner, source, reviewed_at, required_refresh_days, membership_rationale,
  deletion_sync_required, data_scope. Supplied by the responsible business/data owner;
  this is an authorization intake, not legal certification.

**Missing inputs:** No successful upload history means freshness unknown, not stale.
No denominator/definition means match rate unavailable. Missing authorized use or eligibility
blocks activation proposals; inventory can proceed. Customer data is never requested.

## Analysis Steps

1. Inventory all CRM-based lists, including closed, inactive, shared and unused lists.
   Distinguish list ownership and accessible settings from account activation eligibility.
2. Map each list to its declared use case and actual campaign/ad-group association/mode.
   Unapplied lists may be intentional preparation; recent buyers can be valuable retention
   audiences. Do not mandate high-value/lapsed segments or recent-purchaser exclusions.
3. Compute freshness from latest SUCCESSFUL completed job and source_extract_at, not
   list creation date, attempted upload or membership status. Compare with owner refresh
   cadence; label a delta update separately from a fully synchronized population.
4. Review upload failure/rejection categories and pending jobs against intended delivery.
   Accepted upload rows, matched users and channel-active list sizes are different counts;
   do not derive missing match rates by dividing unrelated size and upload totals.
5. Compare rates only across jobs with the same source, identifiers, definition and period.
   A low rate is a diagnostic, not proof of implementation failure; no fixed 30% minimum.
6. Compare source currency, membership duration, lifecycle and deletion synchronization
   requirements. Propose a cadence or segmentation change only with owner rationale;
   no membership extension merely to bypass eligibility/consent requirements.
7. Escalate confirmed failed synchronization on a required active use case. Critical needs
   directly evidenced material delivery failure or unauthorized activation, not a small list.
   Route channel-specific serving eligibility/history to skill-062; do not upload anything.

## Thresholds

| Condition | Severity |
|-----------|----------|
| Required active use case has failed sync or refresh age beyond owner cadence | Warning |
| Active association is platform-ineligible; impact not yet established | Warning |
| Confirmed unauthorized activation or material delivery failure from failed required sync | Critical |
| No Customer Match need, intentional unapplied list or optional missing segment | Info |
| Missing history/rate definition/authorization or privacy-suppressed size | Info |

Cadence is an owner-defined operational requirement, not a universal 30/90-day expiry.
Size and match-rate figures are diagnostics; use actual platform eligibility, not fixed tiers.
Business performance comparisons require mature samples under [PARAMETERS](../_resources/PARAMETERS.md).

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md), not a separate format.
Include stable account/campaign/ad-group/entity IDs, condition key, observed evidence and window,
sample, resolved thresholds, recommendation, uncertainty, and responsible owner.
List exact missing fields and dependent checks skipped; unknown does not mean passed.
Recommendations are request-only proposals; do not modify accounts or export files.
Historical exposure is not savings; no uplift forecast without an explicit counterfactual model.
Include last successful/source-extract dates, job status, intended cadence, actual eligible
channels, consent-evidence reference (no PII), use-mode mapping and responsible data owner.
