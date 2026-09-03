# Data contract

Skills read an account export that **you** produce: Google Ads UI reports (CSV), Google Ads Editor exports, or Google Ads API (GAQL) results. Any format works as long as the entities below are present with the listed fields. Nothing is sent to third-party services.

Save each entity as one table (CSV, TSV or Markdown) in an `export/` folder, named as in the **File** column. Keep the account currency and the date range in `export/account`. All metric tables cover the same date range, 30 days unless the client profile says otherwise.

## Entities

| Entity | File | Required fields | Where to get it |
|---|---|---|---|
| **Account** | `account` | customer id, name, currency code, time zone, auto-tagging, conversion tracking status, date range of the export | UI: Admin → Account settings; API: `customer` |
| **Campaigns** | `campaigns` | id, name, status, channel type, bidding strategy type, target CPA/ROAS, daily budget, shared budget flag, search partners, display network, geo targets and targeting method, languages, ad schedule, labels, start/end dates | UI: Campaigns (columns: settings); API: `campaign` |
| **Ad groups** | `ad_groups` | id, campaign, name, status, type, default CPC bid | UI: Ad groups; API: `ad_group` |
| **Keywords** | `keywords` | id, campaign, ad group, text, match type, status, Quality Score, expected CTR, ad relevance, landing page experience, final URL, first page bid estimate | UI: Search keywords (add the Quality Score columns); API: `keyword_view` |
| **Ads** | `ads` | id, campaign, ad group, type, status, headlines, descriptions, pinned positions, final URLs, ad strength, approval status, policy topics | UI: Ads & assets; API: `ad_group_ad` |
| **Negative keywords** | `negative_keywords` | text, match type, level (campaign / ad group), campaign, ad group | UI: Search keywords → Negative keywords; API: `campaign_criterion`, `ad_group_criterion` (negative) |
| **Shared negative lists** | `shared_negative_lists` | list id, name, member count, keywords with match type, campaigns applied | UI: Tools → Shared library → Exclusion lists; API: `shared_set`, `shared_criterion`, `campaign_shared_set` |
| **Conversion actions** | `conversion_actions` | id, name, category, status, type/source, counting, include in "Conversions", primary for goal, value settings, attribution model, click-through window, enhanced conversions flag, last conversion date | UI: Goals → Conversions → Summary; API: `conversion_action` |
| **Bidding strategies** | `bidding_strategies` | id, name, type, target, status, campaigns using it | UI: Tools → Shared library → Bid strategies; API: `bidding_strategy` |
| **Budgets** | `budgets` | id, name, amount, delivery method, shared flag, campaigns | UI: Tools → Shared library → Shared budgets; API: `campaign_budget` |
| **Audiences** | `audiences` | list id, name, type, size (search / display), membership status, membership duration, match rate, campaigns and mode (targeting / observation / exclusion), bid modifier | UI: Audience manager + campaign Audiences tab; API: `user_list`, `campaign_criterion`, `ad_group_criterion` |
| **Bid adjustments** | `bid_adjustments` | campaign, ad group, dimension (device, location, schedule, demographic, audience), value, modifier, exclusions | UI: campaign Devices / Locations / Ad schedule / Demographics; API: `campaign_criterion.bid_modifier`, `ad_group_criterion.bid_modifier` |
| **Assets** | `assets` | id, type (sitelink, callout, structured snippet, call, price, promotion, image, video, lead form), level, text or fields, status, approval, performance label, metrics | UI: Assets; API: `asset`, `campaign_asset`, `customer_asset`, `ad_group_ad_asset_view` |
| **Campaign metrics (30 days)** | `campaign_metrics` | campaign, impressions, clicks, cost, conversions, conversion value, CTR, average CPC, CPA, ROAS, search impression share, budget-lost IS, rank-lost IS, top and absolute-top IS | UI: Campaigns report with those columns; API: `campaign` + `metrics` |
| **Ad group metrics (30 days)** | `ad_group_metrics` | ad group, campaign, impressions, clicks, cost, conversions, conversion value | UI: Ad groups report; API: `ad_group` + `metrics` |
| **Keyword metrics (30 days)** | `keyword_metrics` | keyword, match type, impressions, clicks, cost, conversions, conversion value, Quality Score | UI: Search keywords report; API: `keyword_view` + `metrics` |
| **Ad metrics (30 days)** | `ad_metrics` | ad, impressions, clicks, cost, conversions, conversion value, ad strength | UI: Ads report; API: `ad_group_ad` + `metrics` |
| **Search terms (30 days)** | `search_terms` | search term, campaign, ad group, matched keyword, match type, added/excluded status, impressions, clicks, cost, conversions | UI: Search terms report; API: `search_term_view` |

## Custom queries

Skills marked `data_source: custom_query` need data a basic export does not carry: segments (device, location, hour, day of week, month), historical series, asset-level labels, policy details, impression-share by cause, simulations. Each of those skills states its **Reference GAQL** with the exact resource and fields. Run it through the Google Ads API, or rebuild it as a UI custom report with the same segments and columns, or export it from Google Ads Editor, and save the result under `export/custom/<name>` using the name the skill suggests.

## External data

Skills marked `data_source: external` also need something outside Google Ads: CRM or order data, page-speed or URL tests, Merchant Center, or a configuration review. They say what, and the report states the assumption when it is missing.

## Conventions

- Money columns are in account currency units (if the source gives micros, divide by 1,000,000).
- Rates (CTR, conversion rate, impression share) are fractions or percentages; say which in `export/account`.
- Missing entity → the skill is skipped and named in the report's "Skipped" list. Never fabricate a table.
