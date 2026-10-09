---
name: skill-173-export-intake-preflight
description: "Run FIRST on raw Google Ads UI CSV/TSV/ZIP downloads (IT or EN): propose table/column/locale mapping, confirm it in plain English, write the normalized export; also checks export readiness."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: platform
  kind: deterministic
  data_source: export
  markets: all
  related: []
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_intake | guided UI-export intake, preflight, apply and readiness check; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_english | intake text and checklist questions in English; Italian UI headers labeled"
---
# Skill 173: Export Intake Preflight

## Purpose

Turn the reports a colleague downloads from the Google Ads interface into the normalized export of
[DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md) without guessing, and tell whether an export is ready for audit.
**Run this intake FIRST whenever raw Google Ads UI exports are supplied** (files with title/date lines, localized or
abbreviated headers such as "Impr." or the Italian UI headers "Costo" and "Termine di ricerca", "Total:"/"Totale:"
rows, UTF-16 TSV or a ZIP). Never pass raw UI files straight to another recipe, and never rename columns or convert
numbers by hand.

## Data Requirements

**Applicability:** Google Ads UI report downloads in Italian or English, one customer account per intake, as CSV/TSV
(UTF-8 or UTF-16) or a ZIP of them; also any already-normalized export folder for the readiness check. Editor and API
exports that already use semantic names skip preflight and go straight to the readiness check.

**Required inputs:**
- Raw folder or ZIP with the UI downloads. Base audit = these UI reports, same date range, with ID columns:
  Campaigns (Campaign ID, Campaign, Campaign status, Campaign type, Bid strategy type, Budget, Impr., Clicks, Cost,
  Conversions, Conv. value); Ad groups (Campaign ID, Ad group ID, Ad group, Status); Search keywords (Campaign /
  Ad group / Keyword ID, Keyword, Match type, Status, Quality Score + metrics); Search terms (Search term, Match
  type, Added/Excluded, Campaign ID, Ad group ID, Keyword + metrics); Ads (Ad ID, Campaign / Ad group ID, Ad type,
  Status, Headline 1–15, Description 1–4, Final URL); Negative keywords (Negative keyword, Match type, Level,
  Campaign ID, Ad group ID); Conversion actions (ID, Conversion action, Category, Status, Count, Action
  optimization). Italian-language UI downloads use the Italian UI headers listed in `scripts/check.py` (e.g. Italian
  UI header "ID campagna" = Campaign ID, "Costo" = Cost, "Valore conv." = Conv. value); `preflight.md` shows both
  in its download hints.
- Colleague answers: customer ID, currency, time zone, report period, download (snapshot) date, filters or row
  limits per file, conversion lag (or "unknown"), conversion date basis, money unit.
- Readiness check: an export folder with `account`, `table_manifest` and the base tables.

**Missing inputs:** A missing report or column is listed in `preflight.md` with the download hint and becomes a
skipped readiness check; it is never filled, defaulted or inferred from names. Unanswered questions block `apply`.
Shared negative lists, assets, audiences and custom tables are outside this intake; request them per recipe.

## Analysis Steps

1. Preflight (deterministic, nothing final):
   `python3 skill-173-export-intake-preflight/scripts/check.py preflight --raw <folder|zip> --out <work>/intake`.
   It reads title/date lines, finds the header row, removes "Total:"/"Totale:" rows, detects each file's table from
   an explicit IT/EN synonym dictionary, proposes column and value mappings, detects the number locale only from
   unambiguous separators, flags e-mail/phone-looking columns as excluded, and writes `proposed_mapping.json` plus
   the English checklist `preflight.md` (Italian headers are marked "(Italian UI header)").
2. Ask the colleague the `preflight.md` questions **in plain English**, a few at a time, in everyday words: no
   JSON, no semantic column names unless needed. Show the detected tables, the unrecognized/ambiguous columns and
   the missing reports. If a file's type was undetected, re-run preflight with `--table "<file>=<type>"`.
3. Write `confirmed_mapping.json`: a copy of the proposal where every answer is the colleague's. Set
   `"confirmed": true` only after all questions are answered. Schema `eppc-intake-mapping/1`:
   - `answers`: `customer_id`, `currency_code`, `time_zone` (IANA), `date_range_start`, `date_range_end`,
     `snapshot_date` (YYYY-MM-DD), `conversion_lag_days` (integer or `"unknown"`), `conversion_date_basis`
     (`interaction_date`, `conversion_date` or `unknown`), `money_unit` (`currency`; `micros` only if confirmed);
     optional `account_name` and `auto_tagging`.
   - Each `files[]` entry: `table` (report type or `"skip"`), `number_locale` (`it` or `en`; `none` only without
     numeric cells), `percent_format`, `date_format`, `filters` `{applied: true|false, description}`, one `columns[]`
     entry per header with `action` `map` or `drop` and `semantic`, and `value_maps` for every observed enum value.
   - "I don't know" is `"unknown"` only where allowed. Never fill a value the colleague did not give.
4. Apply: `python3 .../check.py apply --raw <folder|zip> --mapping confirmed_mapping.json --out <export>`. It refuses
   (exit 2, nothing written) on an unconfirmed or incomplete mapping, a changed raw file, a PII column mapped, a
   number that does not fit the confirmed locale, spreadsheet-damaged IDs or duplicate grain keys. Relay the printed
   problems in plain English. On success it writes normalized CSVs, `account.csv`, `table_manifest.csv` and
   `intake_report.md`.
5. Readiness: `python3 .../check.py run --export <export> --out <work>/skill-173` reports coverage per base table.
   Then use `<export>` as `--export` for the audit recipes.

## Thresholds

Readiness findings are format and provenance checks, not account defects or platform requirements.
Missing tables or columns are coverage gaps (skipped), never findings.

| Condition | Severity |
|-----------|----------|
| Account row field (currency, time zone, period, snapshot, rates format, money unit) is empty | Warning |
| Numeric base column holds cells that are not plain dot-decimal numbers (e.g. `1.234,56`) | Warning |
| Enum base column holds values outside the canonical vocabulary (e.g. the Italian UI value `Attivata`) | Warning |
| ID column in scientific notation or digit-grouped (spreadsheet damage) | Warning |
| Base table without a manifest row, or declared partial or truncated | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default, in plain English.
Report the file → table list, rows kept and totals removed, dropped and PII-excluded columns, completeness per
table, the missing reports/columns with download hints, and the next command. Readiness reports list coverage per
base table. Adjacent owners: every audit recipe consumes this export; this skill never judges performance.
Synonym and column-name sources (consulted 2026-09-25): [About columns](https://support.google.com/google-ads/answer/2454071),
[Search terms report](https://support.google.com/google-ads/answer/2472708) and the pages cited in `scripts/check.py`.
