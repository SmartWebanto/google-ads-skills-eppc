---
name: skill-037-ad-disapproval-monitoring
description: "Triage policy and review statuses using complete parent eligibility, dated review evidence and actual delivery impact."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: custom_query
  merged_from: [skill-139-ad-disapproval-monitoring]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixCreativeBidding | evidence-led audit correction"
---
# Skill 037: Ad Disapproval and Eligibility Monitoring

## Purpose

Prioritize genuine policy-related delivery failures while distinguishing limited serving, paused inventory and unknown review duration.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** All supported ad types; active campaign/ad-group/ad eligibility determines operational priority.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/ads`, `export/ad_metrics`, `export/campaign_metrics`: complete status inventory, ad policy topics and mature cost/traffic context.
- `export/custom/ad_policy_status.csv`: one account_id/campaign_id/ad_group_id/ad_id/snapshot_at row, approval_status, review_status, policy_topics, eligible_geographies_or_formats, serving_status/reason and source_ref; Ads UI Policy Manager/status export including zero-impression ads.
- `export/custom/ad_policy_history.csv`: one account_id/ad_id/event_id row, event_at, event_type (submitted/edited/reviewed/appealed/status_observed), prior/new_status, affected_policy_topic and source_ref; full requested review window with completeness declaration.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without all ad types/parent statuses cannot call a group silenced. Without submission/edit events or status history report review duration unknown or lower-bounded, not exact.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Join policy rows to all ads and parent entities; separate enabled eligible scope, paused work queues and removed historical records. Never count paused ads as active delivery blockers.

2. Preserve approval and review statuses separately using supplied platform vocabulary. Limited ads may serve in allowed locations/formats; under-review alone does not prove no delivery.

3. For every active group enumerate all potentially eligible ads, including limited ads and non-RSAs. Zero fully approved ads is not equivalent to zero eligible ads.

4. Confirm a policy delivery block with current serving diagnostics, affected market/format and business delivery requirement. Historical low impressions alone cannot identify the cause.

5. Calculate review age only from the latest relevant submission/edit event or continuous observed history. First observation gives a lower bound; an edit can restart review, and incomplete history cannot establish a seven-day delay.

6. Group repeated policy topics by exact topic and affected entity scope. Prioritize actual blocked business coverage and the affected period, not arbitrary disapproval percentages or total campaign spend.

7. Propose correction, evidence collection or appeal review according to the policy diagnosis. Do not promise approval, prescribe ad-count quotas or submit an appeal automatically.

8. Track owner, proposed next step and required platform evidence; related landing-page/trademark questions remain specialized reviews. Retain the resolution workflow consolidated from 139.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Confirmed material policy-related loss of all eligible delivery in an active required scope | Critical |
| Confirmed disapproval/limitation affecting intended coverage, or evidenced review delay needing follow-up | Warning |
| Paused affected ads, permissible limited serving or unknown review age | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Ad/group eligibility ledger with policy topics, active scope, last relevant event and review-age confidence.
- Resolution queue with evidence and approval owner; historical spend only as prioritization, not lost-revenue calculation.
