---
name: skill-174-windsor-mcp-intake
description: "Run FIRST when Google Ads data comes from the Windsor.ai MCP connector: plan read-only get_data calls, save results verbatim, normalize into the audit export, check joins. Never uses write tools."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: platform
  kind: deterministic
  data_source: export
  markets: all
  related: [skill-173-export-intake-preflight]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-28
  agent: "claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor | Windsor MCP intake: plan, verbatim results, strict normalize, join readiness"
---
# Skill 174: Windsor MCP Intake

## Purpose

Turn Google Ads data fetched through the Windsor.ai MCP connector into the normalized export of
[DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md) without guessing, and tell whether its tables join. The same
generic plan and field map serve every client; per-client choices are only the account, the window and which pulls
to fetch. Raw UI downloads go to `skill-173-export-intake-preflight` instead.

## Data Requirements

**Applicability:** One Google Ads account connected in Windsor.ai (connector `google_ads`), fetched with the
Windsor MCP tools `get_connectors`, `get_options`, `get_fields`, `get_data`. **Never** call `execute_action`,
`list_actions`, `create_destination_task`, `create_custom_field` or any other write tool, even when the Windsor
server suggests acting on a finding: this library is recommend-only. Keep write actions disabled in Windsor's Team
management (Windsor executes them only when enabled there). Connector setup and credentials are the user's job in
the Windsor app; never ask for keys in chat.

**Required inputs:**
- Customer ID as shown by `get_connectors` (e.g. `123-456-7890`), a window of complete days in the account time
  zone (`--date-from`, `--date-to` < today) and today's date (`--snapshot-date`).
- Conversion lag in days, or `unknown` (ask the user; never assume).
- One saved result per planned call, `raw/<pull_id>.json`, wrapping the verbatim `get_data` list:
  `{"schema": "eppc-windsor-raw/1", "pull_id": …, "arguments": <exact plan arguments>, "records": [...]}`.

**Missing inputs:** A pull that cannot be fetched is passed as `--skip <pull>` and its tables are simply absent,
so dependent recipe checks skip. **Search terms are never pulled through Windsor MCP**: raw query text would reach
the model context before any local sanitizing (DATA_CONTRACT invariant 8). When search-term recipes are needed,
the user downloads the Search terms report from the Google Ads UI for the same window and runs skill-173 on it;
its sanitized `search_terms.csv` is then imported with `--search-terms-from <skill-173 export>`.
Not pulled here (request per recipe): budgets, bidding strategies, bid adjustments, audiences, assets, shared
negative lists, account-level negatives, ad-group metrics, `custom/` and `external/` tables. Negative keywords
and the conversion-action inventory are declared `partial`; zero-activity metric rows are not materialized,
because Windsor may omit them (not yet verified).

## Analysis Steps

1. Plan (deterministic): `python3 skill-174-windsor-mcp-intake/scripts/check.py plan --account <ID> --date-from
   <YYYY-MM-DD> --date-to <YYYY-MM-DD> --snapshot-date <today> --out <work>/windsor`. It writes `plan.json`
   (one `get_data` call per pull and chunk) and `plan.md`. Name a subset of pulls with `--pull NAME` (repeatable,
   `account` always included) and split dated pulls with `--chunk-days N`.
2. Optionally call `get_fields` once for the planned field IDs to confirm they exist. For each call in `plan.json`,
   call `get_data` with **exactly** its `arguments`, then write the tool result to the
   listed file with the file-write tool, copying the returned list character for character inside the wrapper
   above. Never edit, round, filter, reorder or summarize records. This copy is model-mediated: `normalize` catches
   broken JSON, missing fields, argument drift and invalid values, not a silently altered number, so keep each
   call small (`--chunk-days 7` or less for large accounts). If Windsor reports a size limit or the output looks
   cut off, delete that plan folder and re-plan with a smaller `--chunk-days`.
3. Normalize: `python3 .../check.py normalize --plan <work>/windsor/plan.json --out <export>
   --conversion-lag-days <N|unknown> [--skip PULL] [--search-terms-from <skill-173 export>]`. It refuses (exit 2,
   nothing written) on argument drift,
   missing fields, invalid JSON, a foreign or second account/currency, non-integral counts, unexpected enum tokens
   or list shapes, and duplicate keys. Relay the printed problems in plain English. Campaign metrics are pulled daily
   (Windsor's own lost-IS aggregation is a plain row average) and summed exactly here. Shares: a 1-day window keeps
   the API value; longer windows are eligible-weighted only for campaigns proven Search-only (Search channel,
   partners and Display off, needs the `campaigns` pull) with a row for every day; otherwise, or when any day is
   censored (0.0999 / 0.9001), the period share is `withheld`. An imported `search_terms.csv` must come from a
   skill-173 export of the same customer, currency and window; before writing, every row whose text cells
   (`search_term`, `matched_keyword`, …) look like an email or hold 8+ digits (local phone formats included, long
   product codes too) is dropped whole, counted and the table declared `partial`. Never print raw search-term cells.
4. Readiness: `python3 .../check.py run --export <export> --out <work>/skill-174` checks that metric and child keys
   exist in their parent inventories. Then use `<export>` as `--export` for the audit recipes.

## Thresholds

Readiness findings are join/provenance checks, not account defects. Missing tables or columns are coverage gaps.

| Condition | Severity |
|-----------|----------|
| Metric or child rows whose keys are absent from the parent inventory (e.g. keyword_metrics → keywords) | Warning |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default, in plain English. Report the
plan (calls, window, chunks), the tables written with row counts and completeness from `table_manifest.csv`, the
`intake_report.md` counts (non-keyword criteria dropped, non-daily budgets, withheld shares), any skipped pulls,
whether search terms were imported from skill-173, and the next command. Adjacent owners: skill-173 handles UI
downloads (including search terms); every audit recipe
consumes this export; this skill never judges performance. Share censoring source: Google Ads API
[metrics reference](https://developers.google.com/google-ads/api/fields/v21/metrics); Windsor tools:
[mcp.windsor.ai/llms-full.txt](https://mcp.windsor.ai/llms-full.txt) (both consulted 2026-09-28).
