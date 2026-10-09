---
name: skill-170-ad-grants-compliance
description: "Check Google Ad Grants program rules (account CTR, keywords, structure, sitelinks, geo, conversions, bidding) only when the profile declares ad_grants: true."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: compliance
  kind: deterministic
  data_source: custom_query
  markets: all
  related: [skill-030-ad-extension-coverage-audit, skill-053-location-targeting-method-audit, skill-064-quality-score-distribution-analysis, skill-076-conversion-action-configuration, skill-145-prelaunch-compliance-checklist]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes4 | new Ad Grants program recipe with scripted check"
---
# Skill 170: Google Ad Grants Program Compliance

## Purpose

Check whether a Google Ad Grants account meets the program's published account-management and mission-based keyword rules, so the nonprofit can fix gaps before Google pauses keywords or deactivates the account. This is internal readiness, not a Google determination. Rules come from the [Account management policy](https://support.google.com/grants/answer/117827), the [Policy Compliance Guide](https://support.google.com/nonprofits/answer/9314402) and [Mission-based campaigns](https://support.google.com/nonprofits/answer/4410314), all consulted 2026-09-25. The requested page `support.google.com/grants/answer/9042207` returned no content that day. Re-verify the rules before each review; the program can change them.

## Data Requirements

**Applicability:** Only when the profile declares `ad_grants: true`; otherwise every check is not applicable. The CTR rule does not apply to accounts running only Smart campaigns. Other exemptions apply only when the profile cites a current program source. Keyword relevance to the mission remains a human review.

**Required inputs:**
- Base tables: `account`, `campaigns` (id, status, channel_type, bidding_strategy_type or bidding_strategy_id, geo_targets), `ad_groups`, `keywords` (id, campaign_id, ad_group_id, text, status, quality_score, landing_page_experience), `ads`, `assets` (asset_id, type, level, status, campaign_id, ad_group_id; approval_status when exported) and `conversion_actions` (id, name, category, status, include_in_conversions or primary_for_goal). Full parent inventories with manifest completeness support absence findings.
- `export/custom/grants_monthly_metrics.csv`: one customer_id/month row from the account report segmented by month, all campaign types; month (YYYY-MM), impressions, clicks, conversions, complete_month.
- Profile: `ad_grants`, `ad_grants_account_created` (YYYY-MM-DD) and `brand_terms`. `ad_grants_exception_keywords` holds program-list, acronym or medical terms the client confirmed. `ad_grants_generic_terms` is a client-approved list for generic screening. `ad_grants_rules` holds overrides: min_ctr 0.05, ctr_consecutive_months 2, max_prohibited_qs 2, min_ad_groups_per_campaign 2, min_sitelinks 2, min_ads_per_ad_group 1, min_monthly_conversions 1, tracking_required_from 2018-01-01, conversion_bidding_required_from 2019-04-22.

**Missing inputs:** A missing monthly table skips the CTR and monthly-conversion checks. An incomplete inventory leaves counts as lower bounds with no absence finding. An unknown creation date makes the bidding rule and date-based tracking applicability partial. Null QS is "—", which the program exempts. Unknown is never compliant.

## Analysis Steps

1. **Program scope (`program_scope`).** Confirm `ad_grants: true` and resolve each rule value with its source (program URL and consulted date, or profile override). Record whether the enabled campaigns are Smart-only.
2. **Account CTR (`account_ctr`).** For each complete month, CTR = clicks ÷ impressions at account level. Below `min_ctr` with ≥ {{min_impressions}} impressions is Warning; with fewer impressions it is Info. `ctr_consecutive_months` consecutive qualifying months meet the program's deactivation condition. Review decides Critical, and only with cited evidence.
3. **Single-word keywords (`single_word_keywords`).** A serving keyword is enabled, in an enabled ad group and campaign. Strip match punctuation and `+`. The keyword is single-word when one alphanumeric token remains. Dashes, periods and special characters are not single-word per the program. Brand and exception terms are exempt. Each remaining keyword gets Info plus a review: acronyms and medical conditions are exceptions only by judgment.
4. **Generic keywords (`generic_keywords`).** Candidates are serving keywords with below-average landing page experience (the program's indicator) or containing a profile generic term. One batch review decides which are overly generic. Keywords outside the candidates are not certified specific.
5. **Low Quality Score (`low_quality_score`).** Serving keyword with QS ≤ `max_prohibited_qs`: Warning.
6. **Ad groups (`ad_group_minimum`).** Enabled Search campaign with fewer than `min_ad_groups_per_campaign` enabled ad groups, from a complete inventory: Warning.
7. **Ads (`ads_per_ad_group`).** Enabled ad group in an enabled Search campaign with fewer than `min_ads_per_ad_group` enabled ads: Info. The former two-ad rule no longer applies.
8. **Sitelinks (`sitelink_minimum`).** Unique enabled, not disapproved sitelink assets linked at account level or to enabled campaigns/ad groups. Fewer than `min_sitelinks`: Warning. Per-campaign effective coverage is an observation.
9. **Geo-targeting (`geo_targeting`).** Enabled campaign whose geo_targets explicitly means all locations: Warning. An empty cell is unknown. Route location relevance to skill-053.
10. **Conversion setup (`conversion_setup`).** Tracking is required when the account was created on/after `tracking_required_from` or uses conversion-based bidding. No enabled action counted in Conversions (complete inventory): Warning. A batch review judges whether included actions are meaningful; clicks nearly equal to conversions is evidence.
11. **Monthly conversions (`monthly_conversions`).** Complete, lag-mature month below `min_monthly_conversions` where tracking is required: Warning. A month not yet mature: Info.
12. **Bidding (`bidding_policy`).** For accounts created on/after `conversion_bidding_required_from`: enabled non-Smart campaign without Maximize conversions, Maximize conversion value, Target CPA or Target ROAS: Warning.

## Thresholds

The rule values are Google program requirements as of the consulted date, overridable in the profile when the program changes. {{min_impressions}} is the library's sample gate, not a program rule.

| Condition | Severity |
|---|---|
| Deactivation condition from step 2 met, and review cites a deactivation notice or account-status evidence | Critical |
| Complete month below the minimum CTR with ≥ {{min_impressions}} impressions; consecutive months pending review | Warning |
| Serving keyword with QS 1–2, or a single-word/generic keyword review confirms is not an exception | Warning |
| Search campaign below the ad-group minimum, account below the sitelink minimum, or campaign targeting all locations | Warning |
| No counted conversion action, non-meaningful counted action, mature month below the conversion minimum, or required conversion-based bidding missing | Warning |
| Low-impression month below the CTR minimum, keyword candidate awaiting review, ad group below the ad minimum, or immature zero-conversion month | Info |

Missing or incomplete evidence is coverage, not compliance. Critical requires directly evidenced material serving failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md). Add:

- The resolved rule table with source URL, consulted date and overrides.
- Monthly CTR rows with numerator and denominator.
- Keyword IDs with text, QS and exception basis.
- Campaign and ad group counts, labeled complete or lower bound.
- Sitelink asset IDs.
- Geo cells and conversion action IDs with inclusion flags.
- Bidding types and the account creation date used.

Proposals only: pause or reword keywords, add ad groups or sitelinks, set specific locations, fix conversion actions or bidding. No reinstatement requests, automated rules, emails or account changes. Route QS diagnosis to skill-064, sitelink quality to skill-030, location intent to skill-053 and action settings to skill-076.
