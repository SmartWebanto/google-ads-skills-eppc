---
name: skill-164-pmax-search-terms-and-categories
description: "Review PMax search-term insight categories and terms: gated non-converting rows, brand/competitor presence and trends, proposing only supported PMax controls."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: custom_query
  markets: all
  related: [skill-002-brand-nonbrand-split, skill-014-search-term-mining-negatives, skill-094-pmax-cannibalizing-search-detection, skill-127-trending-search-term-detection, skill-128-performance-max-channel-performance, skill-163-product-performance-triage]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes1 | new recipe with deterministic check"
---
# Skill 164: PMax Search Terms and Search Categories

## Purpose

Show which search categories and terms PMax actually matched and which of them absorbed clicks without conversions. It also shows where brand or competitor text appears and which categories changed between equal periods. Any proposal is limited to controls PMax supports. Insight reports are privacy-limited: visible rows are not all PMax traffic, and many insight exports carry no cost.

## Data Requirements

**Applicability:** Performance Max campaigns with an exported search-term insight report. Standard Search queries belong to 014/127. Absent brand or competitor terms in the profile make brand/competitor presence partial, not clean.

**Required inputs:**

- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md) tables:
  - `export/account` and `export/campaigns` (`id`, `channel_type`; `brand_policy` where supplied).
  - `export/negative_keywords` and `export/shared_negative_lists` for existing controls.
  - `export/search_terms`, `export/keywords` and `export/conversion_actions` for collision and tracking checks.
  - Optional: `export/campaign_metrics` (`campaign_id`, `clicks`) for visible-share reconciliation.
  - Profile: `brand_terms`, `competitor_terms`, `excluded_intents`, `campaign_objectives` (goal_ids, brand_policy) and `tracking_verified`.
- `export/custom/pmax_search_categories.csv`: Ads PMax search-term insight report.
  - One row per `account_id`, `campaign_id`, `category_id` (the insight id where exported), `category_label` and `date`.
  - Metrics: `impressions`, `clicks`, `conversions`, `conversion_value`. Include `cost` only when the report actually supplies it.
  - It covers the complete account period; record the manifest filters and completeness.
- Optional: `export/custom/pmax_search_terms.csv`, the same report expanded to terms.
  - One row per `account_id`, `campaign_id`, `category_id`, `search_term` (plus `date` where exported).
  - It has the same metrics; `cost` is included only where reported.

**Missing inputs:**

- Without the category report every subcheck is skipped with its exact columns. Without the term report only term screening is skipped.
- Without `date`, trends are skipped.
- A missing `cost` column limits zero-conversion screening to click/impression exposure with at most Info severity.
- Unknown lag or tracking makes screening partial.
- Uncertified tables cannot prove new or vanished categories.

These local intake schemas describe evidence, not asserted API field names. No live GAQL verification is claimed.

## Analysis Steps

1. **Scope** (`insight_scope`):
   - Keep rows whose `campaign_id` is a `PERFORMANCE_MAX` campaign, dates inside the period and one row per campaign/category/date grain.
   - Key categories by `category_id`, falling back to the normalized label.
   - Record whether cost is supplied and the visible click share against `campaign_metrics`.
2. **Non-converting rows** (`nonconverting_categories`, `nonconverting_terms`):
   - Screen campaign×category and campaign×term rows with literal zero conversions and clicks ≥ {{min_clicks}}.
   - The window must be mature and the campaign's goal tracking must be evidenced.
   - When cost is supplied it must also reach {{spend_floor}} for that campaign, which opens the Warning path. Without cost, exposure is clicks/impressions only and the review can reach Info at most.
   - Brand rows and terms already blocked by existing account/campaign/shared-list negatives are observed, not proposed.
3. **Brand and competitor presence** (`brand_competitor_presence`):
   - Match profile `brand_terms`/`competitor_terms` literally (phrase) in labels and terms, and report the visible-report share.
   - Where the campaign's documented brand policy is `nonbrand_only`, brand traffic goes to a review. Otherwise brand participation is observed, not a defect.
4. **Category trends** (`category_trends`):
   - Compare two equal consecutive halves of the period. Report growth above 50% or decline beyond 30% only when both halves reach {{min_impressions}}.
   - New or vanished categories need a certified-complete report.
   - Growth and new categories go to a relevance review. Declines are Info.
5. **Controls** (`control_inventory`):
   - Inventory existing negatives that apply to each PMax campaign.
   - Accepted proposals may use only `account_negative`, `brand_exclusion` or `search_theme`.
   - An account negative must block the reviewed term. It must not block converting PMax/Search terms, active keyword texts or brand terms.
   - A brand exclusion must name a profile brand/competitor term.
   - A search theme must not be blocked by existing negatives or contain competitor text.

## Thresholds

| Condition | Severity |
|---|---|
| Served category/term confirmed as a documented must-not-serve (legal/safety) intent, with a cited evidence reference | Critical |
| Mature zero-conversion category/term with clicks ≥ {{min_clicks}}, reported cost ≥ {{spend_floor}} and verified tracking, judged unwanted after review | Warning |
| Brand traffic in a PMax campaign whose documented policy is `nonbrand_only`, confirmed as a mismatch | Warning |
| Zero-conversion row screened without reported cost, unwanted low-materiality intent, category growth >50%, decline >30% or new/vanished category | Info |
| Brand/competitor presence without a conflicting documented policy, incomplete coverage, immature window, unknown tracking or insufficient sample | Info |

Resolve parameters with [PARAMETERS.md](../_resources/PARAMETERS.md). Both halves must qualify, and zero or unknown denominators are undefined. The 30%/50% screens are triage heuristics.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md). Each finding lists:

- `campaign_id`, the category id/label or term, and the condition key;
- the window or halves, impressions, clicks, conversions and cost where reported;
- the resolved parameters and their sources, plus the tracking/maturity note;
- the verified proposal and its uncertainty.

Show visible-report shares and cost availability as observations.

Route Search queries to 014/127, brand routing to 002, Search overlap to 094 and channel outcomes to 128. Exposure is not savings. No account changes are made.
