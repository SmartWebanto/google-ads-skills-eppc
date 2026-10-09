# Data contract

Skills analyze locally supplied evidence; they do not fetch account data or change accounts. The single acquisition exception is `skill-174-windsor-mcp-intake`: before analysis, it fetches one account's Google Ads data with the Windsor.ai MCP read tools, saves the results verbatim and normalizes them into this contract, declaring provenance and partial inventories in `table_manifest`. Google Ads UI reports, Editor exports and API results have different capabilities: a GAQL query is executable only through the API, not by pasting it into Editor or the UI. Additional UI, Merchant Center, GA4, site and CRM evidence is requested where needed. A URL or account flag is not a substitute for that evidence.

## Files and provenance

Save base entities as CSV, TSV, JSON or Markdown tables under `export/`, named below. Each custom/external table has the filename and schema specified by its skill, normally `export/custom/` or `export/external/`. Formats may differ, but explicitly map source column names to the semantic fields; never infer missing values.

`account` contains `customer_id`, name, `currency_code`, `time_zone`, auto-tagging, conversion-tracking configuration, `date_range_start`, `date_range_end`, `snapshot_date`, `rates_format` (fraction or percent), `money_unit` (currency or micros), `conversion_date_basis` (interaction date or conversion date), and `conversion_lag_days` or an explicit unknown. Dates and completed days use the account time zone. ROAS is a ratio unless the source explicitly says percent.

Supply `table_manifest` with one row per file: filename, source (UI/API/Editor/CRM/etc.), API version if applicable, export timestamp, period start/end, row grain, primary/join keys, filters, completeness, and any truncation/privacy suppression. A query with LIMIT or a top-N report is a sample, not the full universe. Absent provenance limits dependent findings; request it rather than assume coverage.

A base 30-day metric table may instead cover the requested report period if its manifest says so. The separate **30-day account spend** used for parameters must still cover exactly 30 complete days ending at the report end. For longer/shorter reports supply daily account spend for that window, or a certified 30-day total with window metadata. Never relabel report-period spend as 30-day spend.

## Base entities

These are semantic schemas, not guarantees that every field is available from one resource or export. Keys include customer ID where multiple accounts occur. Source adapters may flatten nested settings and arrays; preserve linkage and nulls. A field required by a subcheck but absent from a table makes that subcheck incomplete.

| Entity / file | Row grain and keys | Required evidence for relevant checks |
|---|---|---|
| Account / `account` | One account snapshot, customer ID | Provenance/settings above; configuration does not certify runtime tracking health |
| Campaigns / `campaigns` | Campaign snapshot, customer ID + campaign ID | Name, status, channel/subtype, strategy type and ID, embedded or portfolio targets, budget ID, daily budget, shared flag, network settings, geo targets/method, languages, schedule, labels, start/end dates, declared campaign goals when supplied |
| Ad groups / `ad_groups` | Ad group snapshot, campaign ID + ad group ID | Name, status, type, default CPC; include groups with no ads or keywords |
| Keywords / `keywords` | Criterion snapshot, campaign/ad group/criterion IDs | Text, explicit match type, status, current QS/components (nullable), final URL overrides, keyword CPC/inheritance, actual first-page estimate and eligibility when available |
| Ads / `ads` | Ad snapshot, campaign/ad group/ad IDs | Type, status, headline/description arrays, pinned positions, display paths, final URLs, strength, approval and policy topics |
| Negative keywords / `negative_keywords` | Criterion and scope IDs | Text, match type, account/campaign/ad-group scope and IDs; no match-type inference from punctuation |
| Shared negative lists / `shared_negative_lists` | List/member/application IDs, flattened if needed | List ID/name, member text and match type, applied campaign IDs; inventory includes unused lists |
| Conversion actions / `conversion_actions` | Action snapshot, action ID and owner account | Name, category, status, source, counting, primary/include flag, value configuration, attribution model/status, windows, separately named Web/Leads enhancement settings when available; settings do not supply action metrics |
| Bidding strategies / `bidding_strategies` | Strategy snapshot, strategy ID | Type, targets, status, campaign IDs; historical status requires dated snapshots |
| Budgets / `budgets` | Budget snapshot, budget ID | Amount, shared flag, linked campaign IDs; deduplicate shared amounts before totals |
| Audiences / `audiences` | List and association IDs, flattened if needed | List ID/name/type, definition/source, current size and platform eligibility by network, membership status/duration, matched-user rate with denominator if supplied, linked campaign/ad-group IDs, mode/exclusion and modifier. Missing upload dates or historical sizes cannot be reconstructed |
| Bid adjustments / `bid_adjustments` | Criterion ID and parent IDs | Dimension, segment value, modifier/exclusion, applicable strategy/control; update timestamps only if actually provided |
| Assets / `assets` | Asset ID plus association level and parent IDs | Type, fields/text, URLs, status/approval, specifications/provenance if exported. Include account, campaign, ad-group, ad and asset-group links separately. Strength and contextual performance labels are not interchangeable |
| Campaign metrics / `campaign_metrics` | Campaign ID + period or date + explicit segments | Impressions, clicks, cost, conversions, conversion value; Search IS and budget/rank-lost IS only for supported channel/grain; served top-rate and eligible top-share must be distinct fields |
| Ad group metrics / `ad_group_metrics` | Campaign/ad-group IDs + period/segments | Impressions, clicks, cost, conversions, value |
| Keyword metrics / `keyword_metrics` | Campaign/ad-group/criterion IDs + period/segments | Impressions, clicks, cost, conversions, value; join to keyword inventory by IDs, not text |
| Ad metrics / `ad_metrics` | Campaign/ad-group/ad IDs + period/segments | Impressions, clicks, cost, conversions, value; asset metrics require their own asset/context keys |
| Search terms / `search_terms` | Campaign/ad-group/matched-criterion IDs + term + period/segments | Explicit match/added-excluded status, impressions, clicks, cost, conversions, value when available. Query reporting is privacy-limited; visible terms are not all account traffic |

## Supplemental evidence

Each skill declares exact columns, IDs, grain, date window and local filename for additional evidence. The following are **not** silently part of a basic export:

- Daily/hourly and joint day-hour segments; historical QS, list-size, budget, status and change-event records; simulator points and their modeled window.
- Full parent inventories plus asset-group, asset, signal and listing-filter trees. Child-only rows cannot prove that a parent has no children.
- Actual feature settings, recommendation subscriptions, experiments with allocation and outcome definitions, and current platform diagnostics/eligibility.
- Merchant Center feed item/variant IDs, attributes, availability, taxonomy version and item issues; Shopping performance samples do not describe the full catalog.
- Locally saved page content and timestamped URL/TLS/speed tests, including tested device, final destination and failure interval. URLs and QS cannot certify page performance.
- Consent defaults/updates and sanitized tag traces across grant/deny/withdrawal; enhanced-conversion diagnostics; pipeline event/upload/acceptance timestamps and error categories.
- Pseudonymous business-event/order/refund reconciliation, value definitions and attribution windows; authorization records, event calendars, approved budgets and business objectives.

`data_source: export` means the listed base tables support the core check. `custom_query` means additional Google Ads report/configuration evidence is needed; a real GAQL query is optional. `external` means a core conclusion requires evidence outside Ads. Optional deeper checks must say which extra inputs they need and skip only those checks when missing.

## Calculation and decision invariants

1. Convert micros exactly once; never mix currencies, ratio/percentage units, attribution bases, goals or periods. Use ratios of summed numerators/denominators, not averages of row rates. Zero/absent denominator means undefined, not zero.
2. Use stable IDs; preserve grain. Prevent one-to-many joins from multiplying spend, totals from being added to their segment rows, and overlapping audiences/n-grams from being summed as disjoint populations.
3. Compare complete, lag-mature periods and compatible objectives, brand/customer mix and conversion definitions. Missing maturity evidence permits descriptive totals but not performance-driven exclusions, pruning or causal claims. Inventory checks do not require conversion volume.
4. Follow `PARAMETERS.md` for samples and spend thresholds. Both comparison cohorts must qualify. Zero-conversion screening is a separate, guarded triage path; no fabricated CPA or guaranteed waste.
5. Settings missing from an incomplete export are unknown. Distinguish known empty, zero, not applicable, withheld and unavailable. Only a complete parent inventory and complete child associations support absence findings.
6. Missing evidence → identify exact skipped subchecks and requested files/fields. Never treat missing evidence as an account defect or claim a complete pass. Partial usable checks may still run.
7. Observed exposure is not recoverable savings. Incremental impact requires a stated scenario/model or controlled evidence, with uncertainty. Correlation is a hypothesis, not causation.
8. Never request raw emails, phone numbers, customer lists, credentials or unredacted personal data. Use aggregates, pseudonymous event keys and sanitized diagnostics. No uploads or third-party queries during analysis. A hosted model still receives its context: use an approved processing environment; these Markdown rules do not enforce local inference.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | explicit evidence, grains, provenance and missing-data behavior
agent: claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor | Windsor MCP intake as the single read-only acquisition path
