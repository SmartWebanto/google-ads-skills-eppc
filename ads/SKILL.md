---
name: ads
description: >
  Front desk for Google Ads audits. Use for ANY Google Ads work — account audit,
  structure/keyword/bidding/budget review, conversion tracking, Quality Score,
  Shopping/PMax, audiences/geo/device, compliance/disapprovals, seasonality,
  wasted-spend hunting, "why did CPA/ROAS change", or a campaign launch review —
  including vague requests ("controlla l'account Google Ads", "dove sto sprecando
  budget", "audit ads", "verifica il tracciamento"). Routes the request to the
  skills in this library and enforces its operating rules.
metadata:
  library: eppc-ads-skills@1.0.0
  author: smartweb
  version: "2.0"
  category: engine-frontdesk
---

# Ads front desk

This library holds **137 Google Ads audit skills** under `skills/` (curated from
TrueClicks google-ads@1.8.0; see `README.md`, `skills/CATALOG.md`, `skills/MERGES.md`).
Each skill is a Markdown recipe: data required, analysis steps, thresholds, output.
You run them by reading the client's export and following the recipe. Nothing here
executes changes in Google Ads.

## Operating rules (non-negotiable)

1. **Recommend only.** Every output is a recommendation with a fix. Never apply,
   never write `pending_changes.json`, never call an execute or validate command.
2. **Data intake.** Accept a manual Google Ads UI/Editor export (CSV/TSV) or a
   `/google-ads:get` export directory. `/google-ads:get` and `/google-ads:get-custom`
   send account data to TrueClicks' hosted API: use them **only** when the client
   profile says `dpa_signed: true`. Never send account data anywhere else.
3. **Client profile first.** Read `ads/profile.yaml` (template:
   `skills/_resources/CLIENT_PROFILE.md`). If missing, ask for `report_language`,
   `market`, `target_cpa`/`target_roas`, `brand_terms`, `data_source`, `dpa_signed`.
4. **Currency from the account**, never assumed. Parameters (`skills/_resources/PARAMETERS.md`)
   resolve against target CPA and 30-day spend; state the resolved values in Evidence.
5. **Language.** Write the report in `report_language` using
   `skills/_resources/OUTPUT_TEMPLATES.md`. Skill bodies stay in English.
6. **Provenance.** Every report starts with the header block; every finding names
   its skill id. Never fabricate metrics; if data is missing, say which skill was skipped and why.
7. **No double reporting.** Related skills (`metadata.related`) may see the same
   entity; report it once under the more specific skill.
8. **EEA accounts.** If any `market` is in the EEA, the tracking workflow always
   includes skill-075 (Consent Mode v2); skills marked `markets: us_only` skip their US-only sections.
9. **Kinds.** Run `deterministic` skills as checks and `analyst` skills as guided
   analysis. Run `operational` skills only when the user asks for automation, and
   present their output as a proposal.
10. **Sample size.** Below `{{min_clicks}}` / `{{min_conversions}}`, rate-based
    findings go under "Insufficient sample" as Info.

## Routing

Pick the preset that matches the request; for a vague request run **Full audit**.
Skill ids are directory names under `skills/` (`skill-NNN-…`); `skills/CATALOG.md`
lists kind and data source for each.

| Request | Preset | Skills |
|---|---|---|
| "audit", "controlla l'account", anything vague | Full audit | Every skill with `kind` ≠ operational, in category order (structure → keywords → creative → bidding → targeting → quality → tracking → shopping_pmax → remarketing → waste → competitive → compliance → seasonal → platform) |
| "sprechi", "dove butto budget", waste | Waste | 005, 006, 013, 014, 015, 020, 023, 054, 056, 057, 114, 115, 116, 117, 118, 119, 121 |
| search terms, query | Search terms | 013, 014, 015, 023, 127 |
| keyword hygiene, match types, negatives | Keyword hygiene | 004, 012, 016, 017, 018, 019, 020, 021, 022, 024 |
| annunci, RSA, creatività, estensioni | Creative | 025, 026, 027, 028, 029, 030, 031, 032, 033, 034, 035, 036, 037, 038 |
| budget, bidding, target CPA/ROAS, pacing | Budget and bidding | 039, 040, 041, 042, 043, 044, 045, 046, 047, 048, 050, 051, 052, 121 |
| tracciamento, conversioni, tag, consent | Tracking | 070, 071, 072, 073, 074, 075, 076, 077, 078, 079, 080, 081, 106, 107, 108, 109, 110, 111, 112 |
| Shopping, feed, PMax | PMax and Shopping | 082, 083, 085, 088, 089, 090, 092, 093, 094, 095, 128 |
| audience, geo, device, remarketing | Audience, geo, device | 053, 054, 056, 057, 058, 059, 060, 061, 062, 063, 098, 099, 100, 101, 102, 103, 105 |
| Quality Score, landing page | Quality Score | 064, 065, 066, 067, 068, 069 |
| struttura account, naming, settings | Structure | 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011 |
| stagionalità, picchi, Black Friday | Seasonality | 137, 148, 150, 151, 152 (+ operational 146, 147, 149 on request) |
| policy, disapprovazioni, trademark | Compliance | 037, 141, 142 (+ operational 145 before a launch) |
| "cosa è cambiato", change history, automation | Change history and automation | 119, 131, 159, 160, 161, 162 |
| review mensile, "perché è cambiato il CPA" | Monthly review | 044, 045, 121, 131, 135, 136, 137, 152 |
| lancio campagna, pre-launch | Launch review | 001, 002, 003, 004, 007, 012, 016, 025, 030, 053, 070, 076 (+ operational 145) |

## How to run a preset

1. Load the client profile and the export; note currency, date range, snapshot date.
2. For each skill in the preset: read `skills/<id>/SKILL.md`, gather its Data
   Requirements (skip and say so if unavailable), apply Analysis Steps and
   Thresholds with resolved parameters, collect findings.
3. Dedupe across related skills, group by severity, render with the template in
   `report_language`, header first.
4. End with Recommendations ordered by impact in account currency, and a
   "Skipped" list naming skills not run and why.

## Where things are

- `skills/CATALOG.md` — every skill with category, kind, data source, markets
- `skills/MERGES.md` — the 8 merged pairs and their threshold reconciliation
- `skills/_resources/PARAMETERS.md` — named thresholds and formulas
- `skills/_resources/OUTPUT_TEMPLATES.md` — report templates (en, it) and header
- `skills/_resources/CLIENT_PROFILE.md` — profile template and rules
- `skills/_resources/SKILL_SCHEMA.md` — how a skill is written
