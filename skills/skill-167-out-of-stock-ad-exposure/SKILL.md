---
name: skill-167-out-of-stock-ad-exposure
description: "Find active ads, keywords, sitelinks and asset groups sending traffic to out-of-stock destinations, plus stale years in ad text; request-only proposals."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: creative
  kind: analyst
  data_source: external
  markets: all
  related: [skill-034-ad-copy-landing-page-consistency, skill-079-broken-url-monitoring, skill-092-pmax-final-url-expansion-control, skill-149-promotional-extensions-countdown-customizers, skill-083-product-feed-attribute-completeness]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes3 | new recipe: out-of-stock destinations and stale ad dates"
---
# Skill 167: Out-of-Stock Ad Exposure

## Purpose

Identify active serving entities whose destination is unavailable according to supplied, dated stock evidence, the spend observed on those out-of-stock days, and active ad text that states a year or date already past. Stock is never inferred from page wording the profile does not declare. All outputs are request-only pause/redirect/copy proposals; nothing is changed.

## Data Requirements

**Applicability:** Search, Shopping-linked Search and PMax entities with final URLs for retail or bookable inventory, when the client supplies stock evidence. Service-only sites without an inventory concept are not applicable. Final URL expansion traffic belongs to skill-092.

**Required inputs:**
- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md) `export/account` (currency, snapshot_date, date range, units) and `export/campaigns` (id, status); `export/ad_groups` (id, status) to exclude paused parents.
- Entities: `export/ads` (id, campaign_id, ad_group_id, status, final_url or final_urls, headlines, descriptions); `export/keywords` (id, campaign_id, ad_group_id, status, final_url override); `export/assets` (asset_id, type, level, status, campaign_id, ad_group_id, final_urls or final_url) for SITELINK rows; `export/custom/asset_group_urls.csv`, one row per campaign_id + asset_group_id + final_url with status.
- `export/external/merchant_availability.csv`: dated Merchant Center snapshots, one row per snapshot_date + offer_id + target_country; link, availability (in_stock, out_of_stock, preorder, backorder). Manifest must state catalog completeness.
- `export/external/page_stock_checks.csv`: locally saved timestamped page checks, one row per url + checked_at; stock_state (out_of_stock, in_stock, unknown), matched_marker, optional http_status. An out_of_stock row counts only when matched_marker is listed in profile `out_of_stock_markers`.
- Optional exposure: `export/custom/entity_daily.csv`, one row per date + entity_type (ad, keyword, asset_group) + campaign_id + ad_group_id + entity_id; impressions, clicks, cost for the report window.
- Profile: `out_of_stock_markers`, optional `url_ignore_params` (exact names or `prefix*`) and `stock_evidence_max_age_days` (default 0: evidence dated the configuration snapshot day).

**Missing inputs:**

- Without Merchant or page evidence every destination subcheck is skipped with both files named; a missing entity table skips only that entity type.
- Without `entity_daily` exposure is unavailable, never zero; sitelink cost is not attributable per entity.
- Unmatched URLs, stale, conflicting or uncertified stock evidence and undeclared markers leave availability unknown, not in stock.
- Unknown entity or parent status is not active; unknown as_of skips the stale-date subcheck.
- Request the exact missing file:column; never infer stock from the ad or page text.

## Analysis Steps

1. Normalize URLs identically for every source: lowercase scheme and host, drop default ports, fragments and trailing slash, remove only profile `url_ignore_params`, sort remaining query parameters. Join by exact normalized URL; never by product name.
2. Merchant state: per URL and snapshot date, out when every offer mapped to that URL was observed out_of_stock that day, in when all observed offers are orderable (in_stock, preorder, backorder), mixed when both occur, unknown otherwise.
3. Page state: accept out_of_stock only with a profile-declared matched_marker; non-2xx http_status is unknown (route to skill-079).
4. Current state: latest observation per source within `stock_evidence_max_age_days` of the configuration snapshot; differing sources on that basis are a conflict. Older-only evidence is stale.
5. Inventory active entities (entity, campaign and ad group ENABLED) per type: ads, keyword URL overrides, SITELINK assets and asset groups. Match each final URL to its current state.
6. Exposure: sum entity_daily cost, clicks and impressions on dates where the destination was observed out; deduplicate date + entity keys. Days without same-day stock observations are unobserved, not out of stock.
7. Stale dates: in active ad headlines/descriptions flag four-digit years earlier than the as_of year and ISO dates before as_of. Founding years, model years and dated facts are legitimate; relevance is a review.
8. Review each out-of-stock entity: pause, redirect to a destination currently evidenced in stock, or keep (back-order page with alternatives). Redirect targets and material-impact claims are re-verified deterministically.

## Thresholds

| Condition | Severity |
|---|---|
| Out-of-stock destination with observed out-of-stock spend ≥ {{spend_significant}} and review-cited evidence (evidence_ref) of no purchasable alternative | Critical |
| Active entity whose destination is out of stock on current evidence (all mapped offers or a declared marker) | Warning |
| Review-confirmed stale year/date claim in active ad text | Warning |
| Mixed variant availability at one destination | Info |
| Past year/date in active ad text awaiting review | Info |
| Stock evidence stale, conflicting or from an uncertified Merchant catalog for an active entity destination | Info |

{{spend_significant}} resolves per campaign from [PARAMETERS.md](../_resources/PARAMETERS.md); unresolved money parameters remove the Critical outcome, not the Warning. Spend on out-of-stock days is exposure, not recoverable savings: an unavailable page can still convert through alternatives. Thresholds are triage heuristics, not platform rules.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md). Per finding report entity type and IDs, normalized URL, matched offer keys and states, evidence source and dates, `stock_evidence_max_age_days`, exposure cost/clicks/impressions with observed-day count and window, resolved {{spend_significant}} and source, and the proposed pause/redirect/copy change marked request-only.

- Coverage lists unmatched URLs, stale evidence, undeclared markers and entity types without daily metrics.
- Adjacent owners: broken or erroring URLs skill-079, ad/page message consistency skill-034, promotion calendars skill-149, feed attributes skill-083, PMax URL expansion skill-092.
- No automatic pausing, re-enabling or copy rewriting; no restock or uplift forecasts.
