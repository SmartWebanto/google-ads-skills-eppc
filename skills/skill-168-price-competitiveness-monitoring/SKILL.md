---
name: skill-168-price-competitiveness-monitoring
description: "Monitor item prices from dated Merchant snapshots: change events, sale windows, page mismatches and benchmark gaps, with descriptive before/after windows."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: shopping_pmax
  kind: analyst
  data_source: external
  markets: all
  related: [skill-083-product-feed-attribute-completeness, skill-128-performance-max-channel-performance, skill-124-performance-anomaly-alert-configuration, skill-085-custom-label-strategy-segmentation]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes3 | new recipe: item price monitoring"
---
# Skill 168: Price Competitiveness Monitoring

## Purpose

Describe how each product's own price moved across dated Merchant Center snapshots, whether supplied landing-page prices match the feed, and, when benchmarks are supplied, how far own prices sit from the market benchmark. Performance around a price event is described only with qualified, equal-length before/after windows; it is never a causal estimate, a pricing mandate or an automatic bid change.

## Data Requirements

**Applicability:** Shopping and PMax retail catalogs with dated Merchant Center price evidence. Pricing strategy is a business decision: a price above benchmark is monitoring context, not a defect.

**Required inputs:**
- Base [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md) `export/account` (currency, period, snapshot_date, conversion lag) and `export/campaigns` for parameter resolution.
- `export/external/merchant_price_snapshots.csv`: one row per snapshot_date + offer_id + target_country; price, currency, link; optional sale_price, sale_start, sale_end (ISO dates). Consecutive dated snapshots from Merchant Center exports; state completeness in `table_manifest`.
- Optional `export/external/landing_page_prices.csv`: locally saved timestamped page checks, one row per offer_id + target_country + checked_at; url, page_price, currency, optional http_status. The row's offer_id is asserted by the check author; no fetching during analysis.
- Optional `export/external/price_competitiveness.csv`: Merchant Center price competitiveness report, one row per report_date + offer_id + target_country; price, benchmark_price, currency.
- Optional `export/custom/product_daily.csv`: Google Ads product report, one row per date + campaign_id + offer_id + target_country; impressions, clicks, cost, conversions, conversion_value for the report window.
- Profile: optional `price_change_alert_pct` and `price_gap_alert_pct` (fractions, e.g. 0.1) and `price_event_window_days` (cap for before/after windows).

**Missing inputs:**

- Without price snapshots the event, sale and before/after subchecks are skipped; each optional file skips only its subcheck with the exact file:column.
- Unset alert fractions keep events and gaps as observations; no alert findings are invented.
- Different currencies are never converted; the affected rows are excluded and listed.
- Missing product metrics or maturity leave before/after descriptions unqualified, not neutral.

## Analysis Steps

1. Effective price per offer and snapshot: sale_price when present and its window (open-ended bounds allowed) contains the snapshot date, else price. Deduplicate snapshot_date + offer_id + target_country; conflicting duplicates are excluded.
2. Price events: compare consecutive snapshots of the same offer and currency. An event records old and new effective price, absolute and relative change (V.ratio over the old price), and the interval between the last old-price and first new-price observation; the exact change day inside that interval is unknown. Alert when |change| ≥ `price_change_alert_pct`.
3. Sale windows on each offer's latest snapshot: sale_price not below price, an expired sale window whose sale_price is still submitted, or start after end.
4. Page mismatch: join page checks to the same offer, country and date snapshot; skip non-2xx checks and currency differences. A difference above 0.005 is a mismatch. Variant or timing artifacts are a review judgment.
5. Benchmark gap on each offer's latest report row: (price − benchmark_price) ÷ benchmark_price; zero or missing benchmark is undefined. Alert when gap ≥ `price_gap_alert_pct`.
6. Before/after description per event: before window ends on the last old-price observation, after window starts on the first new-price observation; both lie in the report period, within the span each price was observed, with equal length L = the shorter span (capped by `price_event_window_days`). Sum product_daily across campaigns once per date. Require a mature report period; compare CTR only when both sides have {{min_impressions}}, conversion rate with {{min_clicks}}, CPA/ROAS with {{min_conversions}}.
7. Material mismatch review: offer spend in the report window per campaign against that campaign's {{spend_significant}}; Critical needs review-cited Merchant disapproval/limitation evidence.

## Thresholds

| Condition | Severity |
|---|---|
| Landing-page price mismatch on an offer with ≥ {{spend_significant}} campaign spend and review-cited Merchant disapproval or limitation evidence (evidence_ref) | Critical |
| Same-date landing-page price differs from the feed effective price for the same offer and currency | Warning |
| Effective price change at or beyond profile price_change_alert_pct between consecutive snapshots | Info |
| Own price above benchmark by at least profile price_gap_alert_pct | Info |
| Sale price not below price, expired sale price still submitted, or sale start after end | Info |

Unqualified before/after windows, unmatched page checks and missing benchmarks are reported as observations and Coverage, never as a pass. Alert fractions are client-chosen triage settings, not platform rules or significance tests.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md). Per finding report offer_id, target_country, snapshot or check dates, prices and currency, effective-price rule, change or gap with numerator and denominator, alert fraction and its profile source, and for mismatches the offer spend, resolved {{spend_significant}} and source.

- Before/after rows: event, window dates, L, per-side impressions, clicks, cost, conversions, value, and only the rates whose gates both sides pass, labeled descriptive and non-causal.
- Adjacent owners: Merchant diagnostics and attribute validity skill-083, PMax channel reporting skill-128, alert configuration skill-124.
- Recommendations are request-only: confirm prices with the feed owner, re-check pages, review pricing strategy; no automatic bid, budget or feed changes and no uplift forecasts.
