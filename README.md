# Google Ads skills library — eppc edition

`eppc-ads-skills@1.1.0` · 137 Markdown audit skills for Google Ads, curated for EUR/EEA accounts, run by a Claude agent through the `ads` front desk. Self-contained: the only input is an export you produce from Google Ads, and nothing is sent to any external tool or service.

## What this is

A skill is a recipe: what data to read, how to analyze it, the thresholds that make a finding, and the output shape. The agent reads a client's Google Ads export, follows the recipe, and writes a report. Nothing here executes changes in Google Ads.

## Layout

```
ads/SKILL.md              front desk: operating rules and routing presets
skills/skill-NNN-…/       137 skills
skills/CATALOG.md         generated table: category, kind, data source, markets
skills/MERGES.md          merged pairs and threshold reconciliation
skills/_resources/        DATA_CONTRACT, PARAMETERS, OUTPUT_TEMPLATES, CLIENT_PROFILE, SKILL_SCHEMA, scripts/
docs/superpowers/         design spec and implementation plan (history of the curation)
LICENSE                   MIT
```

## How to use

1. In a client repo, create `ads/profile.yaml` from `skills/_resources/CLIENT_PROFILE.md`.
2. Export the account from Google Ads (UI reports, Google Ads Editor, or the API) into `export/`, following `skills/_resources/DATA_CONTRACT.md`.
3. Ask the agent ("audit the account", "dove sto sprecando budget", "verifica il tracciamento"). The front desk picks the preset, runs the skills, and writes the report in `report_language`.
4. To run one skill by hand: read `skills/<id>/SKILL.md`, resolve its `{{parameters}}`, follow it.

Check the library: `python3 skills/_resources/scripts/lint.py` (add `--write-catalog` to regenerate `skills/CATALOG.md`). Tests: `cd skills/_resources/scripts && python3 -m unittest test_lint`.

## How a skill is built

- Frontmatter `metadata`: `category`, `kind` (deterministic / analyst / operational), `data_source` (export / custom_query / external), `markets` (all / us_only / eea_relevant), `related`, `merged_from`, `reviewed`.
- Body, always in this order: Purpose, Data Requirements (export tables from the data contract plus a reference GAQL query), Analysis Steps, Thresholds, Output.
- Every money threshold is a named parameter in account currency (`skills/_resources/PARAMETERS.md`, EUR floors, spend-relative formulas); rate-based findings carry a sample-size rule.
- Output templates in English and Italian with a provenance header (`skills/_resources/OUTPUT_TEMPLATES.md`).

## Governance

- **Recommend-only.** No skill and no front-desk path applies changes.
- **Data.** Client account data never leaves the client's or the studio's machines; the export is made from Google Ads directly.
- **Provenance.** Every report carries library version, skill id, date range, snapshot date, and the parameter values used.
- **EEA.** Consent Mode v2 (skill-075) runs in every tracking workflow for EEA markets; `markets: us_only` sections are skipped.

## Known gaps and out of scope

- No engine and no live API client: the agent runs the recipes.
- No real account has been run through this library yet. The first calibration run should be a EUR account with a UI export and a hand count of false positives.
- Skill numbers are not contiguous (17 gaps from the original set, 8 merges); no Microsoft Ads skills.
- Reference GAQL queries are not validated against the current API version (`gaql_verified: null` everywhere).
- 37 skills need data a basic export cannot provide (day/hour segments, geographic view, historical series, simulations, policy topics, external tests); they are `custom_query` or `external` in the catalog.
- A few skills use a four-level severity (`High`); the schema documents three.

## License and origin

MIT, see `LICENSE`. The skill set derives from TrueClicks' open-source `google-ads` Claude Code plugin (v1.8.0), whose copyright notice is retained as the license requires; everything else (merges, parameters, templates, contract, front desk) is this library's own work.

## Changelog

- **1.1.0 (2026-09-03)** — self-contained: no plugin commands, no third-party API, tool-neutral data contract, attribution moved to LICENSE/README.
- **1.0.0 (2026-09-03)** — first curated release.
