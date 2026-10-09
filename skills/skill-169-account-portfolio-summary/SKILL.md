---
name: skill-169-account-portfolio-summary
description: "Summarize per-account KPIs across a manager portfolio in native currencies, flag accounts that stopped serving and convert totals only with supplied dated rates."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: platform
  kind: deterministic
  data_source: custom_query
  markets: all
  related: [skill-042-budget-limited-campaign-identification, skill-044-monthly-budget-pacing-analysis, skill-121-impression-share-loss-analysis, skill-124-performance-anomaly-alert-configuration]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes4 | new portfolio summary recipe with scripted check; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | account_status_evidence input"
---
# Skill 169: Account Portfolio Summary

## Purpose

Describe what each account in a manager (MCC) portfolio delivered in the report window, in its own currency, which accounts stopped serving, and what a cross-account total is when, and only when, dated exchange rates are supplied. This is a descriptive portfolio view: no ranking of accounts with unlike goals, no composite health score, no forecast. Recommendations are proposals; nothing is sent, scheduled or changed.

## Data Requirements

**Applicability:** One or more Google Ads accounts supplied in one export, typically the child accounts of a manager account. Each account keeps its own currency, time zone, units, maturity and parameters. Money is totaled only within one currency or through supplied dated rates. CPA/ROAS only for an account whose converting campaigns share one declared goal set. Not a substitute for per-account audits.

**Required inputs:**
- `export/account`: one row per `customer_id`; currency_code, time_zone, money_unit, rates_format, date_range_start/end, snapshot_date, conversion_lag_days (unknown allowed).
- `export/campaign_metrics`: customer_id + campaign_id at the report-period grain (explicit segments such as date/device keep their columns); channel_type, impressions, clicks, cost, conversions, conversion_value; `search_impression_share`, `search_budget_lost_is`, `search_rank_lost_is` where the channel reports them. `export/campaigns` and profile `campaign_objectives` supply goal IDs.
- `export/custom/account_daily_metrics.csv`: one customer_id/date row from an account-level Google Ads report segmented by day in the account time zone, no other segments; date, impressions, clicks, cost, conversions, conversion_value, complete_day. Cover the report period, an equal-length prior period and baseline days before the latest complete day.
- Optional `export/external/exchange_rates.csv`: one date/from/to row; date, from, to, rate (units of `to` per one `from`), source. Used only when the profile sets `portfolio.reporting_currency`; the rate date must equal the account's report end.
- Optional `export/external/account_status_evidence.csv`: evidence_ref, customer_id, status_type (unplanned_stop / planned_pause), cause, from_date, to_date, source. Owner, billing or policy records; campaign status alone never proves intent or cause. Required for a Critical offline outcome or a planned-pause dismissal.
- Profile `portfolio`: reporting_currency, offline_min_days (default 1 complete day), offline_baseline_days (default 28). Multi-account files must carry customer_id; `table_manifest` declares completeness.

**Missing inputs:** Without campaign metrics, KPIs and totals are skipped. Without the daily table, offline detection and period-over-period deltas are skipped: missing day rows are unknown, never zero serving. Unknown goals block CPA/ROAS only. Missing, undated or conflicting rates block only the converted total; native-currency totals remain. Unknown lag withholds conversion deltas.

## Analysis Steps

1. **Account KPIs (`account_kpis`).** Sum campaign rows once per grain; duplicate grain rows stop the sum. Report impressions, clicks, cost, conversions and value; CTR, CPC and conversion rate as ratios of sums. CPA and ROAS only when every converting campaign has the same declared goal set. Label maturity and whether {{min_impressions}}, {{min_clicks}} and {{min_conversions}} are met.
2. **Impression-share summary (`impression_share_summary`).** Per channel, estimate eligible impressions as impressions ÷ IS for each campaign with a reported share. Account IS = Σ impressions ÷ Σ eligible; budget- and rank-lost IS are eligible-weighted. Censored or withheld shares stay unknown and make the summary partial. Name the campaigns with the highest lost shares among those with {{min_impressions}}. Economic interpretation belongs to skill-121 and skill-042.
3. **Offline detection (`account_offline`).** From the daily table, take complete days up to the report end. Count the consecutive days, ending at the latest complete day, with impressions = 0 and cost = 0. The baseline is the preceding `offline_baseline_days`, which must all be present. The account qualifies when the zero run is at least `offline_min_days`, is longer than any zero-impression run in the baseline, and baseline impressions reach {{min_impressions}}. Otherwise the zero run is Info. An AI review decides whether the stop was planned. Only cited outage, billing, policy or status evidence supports Critical.
4. **Period over period (`period_over_period`).** Compare the report period with the equal-length prior period. Both periods need every complete day. Report deltas for impressions, clicks and cost. Conversion and value deltas need `ctx.mature`. CTR, CVR and CPA/ROAS deltas need both periods to pass {{min_impressions}}, {{min_clicks}} and {{min_conversions}} respectively, plus compatible goals. Deltas are descriptive, not causes.
5. **Native portfolio totals (`portfolio_totals`).** Group accounts by currency and report period, then total within each group. Never add different currencies or periods. Report no portfolio CPA/ROAS: account goals and value definitions differ unless proven.
6. **Reporting-currency conversion (`currency_conversion`).** Convert an account's cost and value only with one positive, sourced rate for (report end, account currency → reporting currency). Same-currency accounts use 1. Report a converted portfolio total only when every account converts and all periods match; otherwise list the exact missing rate rows.

For multi-account exports the runtime writes one result per account. Steps 5–6 appear once, in the result of the lowest customer ID. The other results mark them not applicable and point there.

## Thresholds

Offline triage uses the account's own baseline, not a universal traffic floor; the zero-run rule is a review heuristic.

| Condition | Severity |
|---|---|
| Account offline per step 3, and review cites evidence of an unplanned stop (billing, policy, suspension or status) | Critical |
| Zero impressions and zero cost on ≥ `offline_min_days` consecutive complete days ending at the latest complete day, longer than any zero run in a complete baseline with ≥ {{min_impressions}} impressions | Warning |
| Zero-serving run at the report end whose baseline is incomplete, below {{min_impressions}} or contains an equal or longer zero run | Info |

KPIs, impression share, deltas and totals are observations, not findings. Insufficient samples, unknown goals and missing rates are coverage limits. Critical requires directly evidenced material serving failure.

## Output

Use [OUTPUT_TEMPLATES](../_resources/OUTPUT_TEMPLATES.md). Add:

- Per-account KPI rows with customer ID, currency, period, maturity, sample flags and goal basis.
- Channel IS summaries with the eligible-impression denominator and censored campaign IDs.
- Offline evidence: zero-run dates, baseline window, baseline impressions, longest baseline zero run and the parameter sources.
- Delta tables that name the gates that passed.
- Native totals per currency/period group.
- Conversion rows with rate, date, source and converted values. The exact missing rate rows when conversion is blocked.

Exposure and deltas are not savings or causal effects. Route budget causes to skill-042/044, rank causes to skill-121 and alert design to skill-124. No spreadsheets, emails, rate fetches or account changes.
