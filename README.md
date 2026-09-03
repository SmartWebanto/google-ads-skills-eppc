# Google Ads skills library — eppc edition

`eppc-ads-skills@1.0.0` · 137 Markdown audit skills for Google Ads, curated for EUR/EEA accounts, run by a Claude agent through the `ads` front desk.

## What this is

A skill is a recipe: what data to read, how to analyze it, the thresholds that make a finding, and the output shape. The agent reads a client's Google Ads export, follows the recipe, and writes a report. Nothing here executes changes in Google Ads.

## Provenance and license

Curated from the open-source (MIT) TrueClicks Claude Code plugin `google-ads` v1.8.0 (https://github.com/TrueClicks/claude-plugins). Every skill's frontmatter records `upstream_skill`; `skills/MERGES.md` records the 8 pairs merged into one. Changes vs upstream:

- 145 → 137 skills (8 merges); numbered directories; provenance `metadata` block on every skill
- Every money threshold is a named parameter in account currency (`skills/_resources/PARAMETERS.md`); sample-size rule for rate-based findings
- Output templates in English and Italian with a provenance header (`skills/_resources/OUTPUT_TEMPLATES.md`)
- Client profile with DPA gate (`skills/_resources/CLIENT_PROFILE.md`); Consent Mode v2 always in tracking for EEA accounts
- Skills classified `deterministic` / `analyst` / `operational`; `markets` flag for US-only and EEA-relevant checks
- Broken `/google-ads-get-custom` reference fixed to upstream's `/google-ads:get-custom`
- Lint and catalog generator (`skills/_resources/scripts/lint.py`)

## Layout

```
ads/SKILL.md              front desk: operating rules and routing presets
skills/skill-NNN-…/       137 skills
skills/CATALOG.md         generated table: category, kind, data source, markets
skills/MERGES.md          merged pairs and threshold reconciliation
skills/_resources/        PARAMETERS, OUTPUT_TEMPLATES, CLIENT_PROFILE, SKILL_SCHEMA, scripts/
docs/superpowers/         design spec and implementation plan
```

## How to use

1. In a client repo, create `ads/profile.yaml` from `skills/_resources/CLIENT_PROFILE.md`.
2. Export the account from the Google Ads UI (or `/google-ads:get`, only with a signed DPA).
3. Ask the agent ("audit the account", "dove sto sprecando budget", "verifica il tracciamento"). The front desk picks the preset, runs the skills, and writes the report in `report_language`.
4. To run one skill by hand: read `skills/<id>/SKILL.md`, resolve its `{{parameters}}`, follow it.

Check the library: `python3 skills/_resources/scripts/lint.py` (add `--write-catalog` to regenerate `skills/CATALOG.md`). Tests: `cd skills/_resources/scripts && python3 -m unittest test_lint`.

## Governance

- **Recommend-only.** No skill and no front-desk path applies changes.
- **Data.** Client account data goes to TrueClicks' hosted API only when the client profile has `dpa_signed: true`; otherwise use a manual UI export. Data never goes anywhere else.
- **Provenance.** Every report carries library version, skill id, upstream id, date range, snapshot date, and the parameter values used.
- **EEA.** Consent Mode v2 (skill-075) runs in every tracking workflow for EEA markets; `markets: us_only` sections are skipped.

## Known gaps and out of scope

- No engine and no live API client: the agent runs the recipes.
- No DPA exists yet with TrueClicks; the library only enforces the gate.
- No real account has been run through this library yet. The first calibration run should be a EUR account with a manual UI export and a hand count of false positives.
- 17 upstream numbers are absent (084, 086, 087, 091, 096, 097, 132, 134, 138, 140, 143, 144, 153-155, 157, 158); no Microsoft Ads skills.
- Reference GAQL queries are not validated against the current API version (`gaql_verified: null` everywhere).
- 37 skills need data a period-aggregated export cannot provide (day/hour segments, geographic_view, historical series, simulations, policy topics, external tests); they are `custom_gaql` or `external` in the catalog: 010, 011, 029, 044, 046, 048, 049, 051, 053, 054, 056, 058, 063, 066, 071, 074, 079, 095, 102, 109, 111, 117, 123, 127, 130, 135, 136, 137, 142, 145, 146, 147, 150, 152, 160, 161 (and 055, now merged into 054).
- Upstream's four-level severity (`High`) survives in a few skills; the schema documents three.

## Changelog

- **1.0.0 (2026-09-03)** — first curated release, from upstream 1.8.0. See `docs/superpowers/specs/2026-09-03-google-ads-skills-library-design.md`.
