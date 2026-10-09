---
name: skill-031-sitelink-relevance-performance
description: "Review sitelink destinations and attributable performance using supplied page and click evidence."
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
# Skill 031: Sitelink Relevance and Performance Review

## Purpose

Assess real destination/message mismatches and contextual sitelink outcomes. A homepage URL, optional missing descriptions or low CTR alone is not a defect.

Recommendations are review-only; this recipe never changes an account.

## Data Requirements

**Applicability:** Sitelink associations eligible for the audited campaigns and dates, at every supported association level.

**Required inputs:**
- Read `../_resources/DATA_CONTRACT.md`, `../_resources/PARAMETERS.md` and the supplied client profile.
- `export/account`, `export/campaigns`, `export/ad_groups`, `export/assets`: sitelink IDs, linking entities/status, text, descriptions, final URLs, approval and schedule.
- `export/external/sitelink_destinations.csv`: one URL/device/locale/check_at row; account_id, asset_id, association_key, original_url, resolved_url, http_status, page_title, visible_text, offer_terms, valid_from/to, screenshot_or_snapshot_ref, source_ref. Client-supplied page/URL tests contemporary with serving evidence.
- `export/custom/sitelink_metrics.csv`: one account_id/asset_id/association_key/date/segment row; impressions, clicks, click_type, click_scope (asset-only or all-ad), conversions, cost, conversion_value, attribution_definition and report_source; mature matching window from Ads asset reports.

Use account currency, timezone, export window, snapshot and completeness declarations.
Keep missing values distinct from zero and disabled; join on stable IDs, never names.

**Missing inputs:** Without destination tests skip broken-link/offer verification. Without click scope or matching association denominators skip CTR comparisons; do not infer a broken page from the URL.
Skip only the dependent subcheck; report its exact missing file/columns and coverage.
Do not treat absent evidence as a defect or a passed check.

## Analysis Steps

1. Join assets to full association hierarchy and parent eligibility. Keep unique destinations distinct from link associations to avoid double counting.

2. List text, optional descriptions and destination completeness. Character limits depend on the current type/language; do not mistake recommended capacity for required messaging.

3. Join page evidence by exact URL, device, locale and timestamp. Preserve relevant query parameters and redirects; a present homepage can be the most relevant destination.

4. Compare quoted sitelink promise with quoted page/offer terms valid for the same period. Stale or missing snapshots produce a verification request, not an expired-offer finding.

5. Use confirmed HTTP errors with reproduction scope to identify destination risk; a snapshot failure does not establish that all historical traffic failed. Delegate broader URL diagnostics to 125.

6. Compute asset click-through rate only as attributable sitelink clicks / matching asset impressions. Keep all-ad clicks separate; conversion metrics must state association/interaction attribution.

7. Compare mature samples within matched intent, linking context, device and objective. Remove the universal 0.2% cutoff; a low rate can coexist with valuable downstream outcomes.

8. Propose specific destination/text fixes for confirmed mismatches and optional description tests for opportunities. Do not remove a homepage or high-value link solely on CTR.

## Thresholds

Numerical screens are triage heuristics, not platform requirements or causal proof.
Use resolved `{{min_impressions}}` for CTR/IS, `{{min_clicks}}` for CVR and
`{{min_conversions}}` for CPA/ROAS comparisons; both comparison cohorts must qualify.
Use mature, comparable goals/windows; exclude incomplete days and conversion lag.
A zero denominator yields unavailable, never infinity or an invented zero rate.

| Condition | Severity |
|---|---|
| Current eligible sitelink with reproduced broken destination or confirmed wrong offer | Warning |
| Low contextual CTR with mature samples and business-performance concern | Warning |
| Homepage URL, absent optional descriptions, or incomplete page/click evidence | Info |

Critical requires directly evidenced material delivery, measurement or safety failure.
Historical spend is exposure, not guaranteed savings; any forecast requires an explicit model.

## Output

Use `../_resources/OUTPUT_TEMPLATES.md`; do not create a competing report format.
Include stable entity IDs, condition key, observed evidence/window, sample, resolved
thresholds, recommendation, uncertainty and the responsible owner.
Separate confirmed findings, opportunities, insufficient evidence and not-applicable checks.
- Association-level evidence table containing click attribution, denominator and exact page quote/check timestamp.
- Confirmed mismatch proposals separated from destination verification and optional creative experiments.
