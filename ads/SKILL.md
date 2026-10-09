---
name: ads
description: >
  Front desk for Google Ads account audits, waste reviews, keywords, creative,
  bidding, measurement, Shopping/PMax, audiences, policy and seasonal planning.
  Use for vague requests such as "audit ads", "check the account" or "why did CPA
  change". Selects applicable evidence-backed recipes; never changes accounts.
metadata:
  library: eppc-ads-skills@2.0.0
  author: smartweb
  version: "3.1"
  category: engine-frontdesk
  agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | evidence-first routing; gpt-6-astra | openai | 2026-09-07 | s_20260907_context_opt | metadata-first selection and scoped delegation; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | deterministic scripts + ai_review finalize, recipes 163-172; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_english | intake row and step 0 in English; Italian request phrases kept as trigger aliases; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_simple | interview-built profile when none is supplied (objective, ISO market, target type/unit, slug confirmation); claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor | Windsor MCP intake 174: read-only pull exception, routing row, step 0
---

# Ads front desk

The library contains **136** canonical recipes (134 audits + intakes 173 and 174), each with a deterministic `scripts/check.py`; `skills/CATALOG.md` is the inventory and `skills/MERGES.md` records absorbed IDs. Read recipes as analysis procedures against locally supplied evidence, not as instructions to execute platform changes.

## Operating rules

1. **Recommend only.** Never apply account changes, publish ads, upload customer data, create executable change files or grant permissions. Operational output is a proposal, not deployable automation. Repository lint, synthetic self-test commands and each recipe's bundled `scripts/check.py` (local, read-only, no network) are permitted; account mutation/validation commands are not.
2. **Approved data environment.** Read only the supplied local profile, exports and evidence. Do not call external services with account data. One exception: when the user has connected Windsor.ai, `skill-174-windsor-mcp-intake` may fetch the account's own Google Ads data with the Windsor MCP **read** tools (`get_connectors`, `get_options`, `get_fields`, `get_data`) into local files; analysis then runs on those files only. Windsor write tools (`execute_action`, `list_actions`, `create_destination_task`, `create_custom_field`, …) are never used. Public documentation may be consulted without client identifiers. Hosted model inference transmits prompt context: this library does not itself enforce local processing or authorize disclosure. Require an approved environment and sanitized inputs.
3. **Profile and provenance first.** Read the supplied profile's task-relevant fields, account and manifest. Consult `CLIENT_PROFILE.md` only for unfamiliar/ambiguous fields. Read the applicable `DATA_CONTRACT.md` sections below, not every entity schema. Ask only for relevant context unavailable in supplied evidence. Check currency/units, time zone, report/snapshot dates, completeness, grain/IDs, goals and maturity before dependent calculations.
4. **Measurement before performance prescriptions.** Verify applicable goal configuration and usable measurement evidence; read 070/076 only when those questions need analysis, and 071/110 for accuracy/outage diagnosis. Include 075 for applicable EEA/UK consent review. Reuse established evidence with its scope/date, not an unsupported “tracking healthy” summary. Missing/broken measurement blocks dependent prescriptions, not independent inventory checks; no tracking bundle for naming or content-only questions.
5. **Eligibility before execution.** Select by campaign type, market, objective, evidence and user intent. No Shopping feed audit for an account without products; no compulsory PMax, broad-match percentage, micro-conversions, audience modifiers or server-side architecture. Missing an optional tactic is not an account defect.
6. **Evidence states.** Complete parent/child inventories can prove absence; omitted settings cannot. Follow each recipe's Applicability, Required inputs and Missing inputs. Skip only dependent subchecks, name their missing files/fields and continue independent checks. Never claim a whole-skill pass with skipped core checks.
7. **Parameters and comparisons.** Resolve only parameters used by selected checks through `PARAMETERS.md`; reuse once per compatible currency/goal/campaign/window/override context, never across incompatible ones. Use local read-only calculations for joins/rates. Apply maturity, cohort and sample gates; zero-denominator rates are undefined. Zero-conversion spend is guarded review exposure, not automatic waste.
8. **Kinds.** `deterministic` means reproducible checks, `analyst` means declared judgment/hypotheses, `operational` means a request-only configuration proposal. No automation proposal just because a broad full audit was requested.
9. **Severity and causality.** Only Critical, Warning, Info. Critical requires evidenced material failure. Missing evidence and optional experiments are Info. No promised savings from removed historical spend or feature adoption; estimates need explicit model assumptions. No fraud, cannibalization or legal-compliance conclusions from proxies.
10. **One reporting owner.** Dedupe by `(account ID, entity ID, condition key, period)`, not entity alone. Distinct problems on the same campaign remain distinct. Use the more specific recipe and its `related` ownership; never add overlapping exposure estimates together.
11. **Report contract.** Use `OUTPUT_TEMPLATES.md` in `report_language`. Include version, skill IDs, evidence/window, resolved parameters, recommendation and uncertainty. Prioritize confirmed impact before hypotheses. Show coverage, insufficient evidence and Not applicable separately from actual defects.

## Routing

- **Specific question or skill ID:** use the smallest relevant set; an explicit skill goes directly to its canonical file. Preset membership and `related` links do not authorize reading/running siblings. Add a recipe only for a named unanswered question or dependency; record why.
- **Vague “audit / check the account”:** start a **Triage**, clearly labeled as limited scope. Inspect profile/account/manifest, then the most relevant supported checks for the stated objective or visible blocker. Report what remains unexamined; do not imply a full audit or launch every preset.
- **Explicit “full audit / all skills”:** retain full coverage. Enumerate the entire catalog's selection metadata, classify every non-operational candidate as applicable, confirmed not applicable or unresolved, then read every applicable/unresolved recipe. Group work by evidence/domain with measurement prerequisites first. No arbitrary recipe cap, sampling or silent downgrade to Triage. Operational proposals run only when requested.

Requests in any language route by meaning. Presets below are search domains, not mandatory read/job lists. Search matching catalog rows by ID, description, category and Applicability; refine broad/empty results rather than loading all recipes. The catalog is generated source-derived selection metadata, not a substitute for a selected recipe's full instructions. Do not exclude from the name alone or treat missing evidence as not applicable.

| Request | Preset | Candidate skills |
|---|---|---|
| I downloaded the reports / prepare the data | Intake | 173 first, then the requested preset |
| pull the data from Windsor / Windsor connected | Intake | 174 first, then the requested preset |
| audit / check the account | Triage | Objective/blocker-led selection; limited scope, not Full audit |
| full audit / all skills | Full audit | Every applicable or unresolved non-operational catalog recipe |
| waste | Waste | 005, 006, 013, 014, 015, 020, 023, 054, 056, 057, 115, 117, 118, 119, 121, 167 |
| search terms / query | Search terms | 013, 014, 015, 023, 127; 164 for PMax search terms/categories |
| keyword hygiene / negatives | Keyword hygiene | 004, 012, 016, 017, 018, 020, 022, 024; 039 for manual-bid estimates; 171 for keyword hypotheses |
| ads / RSA / creative / assets | Creative | 025, 026, 028, 029, 030, 031, 032, 033, 034, 035, 036, 037, 038 |
| budget / bidding / CPA / ROAS | Budget and bidding | 039, 040, 041, 042, 043, 044, 045, 046, 048, 050, 051, 052, 121 |
| tracking / conversions / consent | Tracking | 070, 071, 072, 073, 074, 075, 076, 078, 079, 080, 106, 107, 110, 111, 112 |
| Shopping / feed / PMax | PMax and Shopping | 082, 083, 085, 088, 089, 090, 092, 093, 094, 095, 128, 163, 164, 165, 168 |
| audience / geo / device / remarketing | Audience, geo, device | 053, 054, 056, 057, 058, 059, 060, 061, 062, 098, 099, 100, 101, 102, 103, 105 |
| Quality Score / landing page | Quality Score | 064, 065, 066, 067, 068, 069, 166; 078/079 only with site evidence |
| structure / naming / settings | Structure | 001, 002, 003, 004, 005, 006, 007, 008, 009, 010 |
| seasonality / Black Friday | Seasonality | 137, 148, 151, 152, 172; operational 146, 147, 149 only when requested |
| policy / disapprovals / trademark | Compliance | 037, 141, 142; 170 only for declared Ad Grants accounts; operational 145 for requested launch-readiness proposal |
| what changed / change history | Changes | 119, 131; 159, 160, 161, 162 when those features are relevant |
| monthly review / CPA changed | Monthly review | 044, 045, 121, 131, 135, 136, 137, 152, plus applicable measurement diagnosis; 169 for multi-account portfolios |
| launch / pre-launch | Launch review | 001, 002, 003, 004, 007, 012, 016, 025, 030, 053, 070, 076; 145 when readiness review requested |

## Execution

0. **Data intake.** Raw Google Ads UI downloads (IT/EN CSV/TSV/ZIP with titles, totals rows or localized numbers) go to `skill-173-export-intake-preflight` first: run `preflight`, ask the colleague the checklist questions in plain English, write the confirmed mapping only from their answers, `apply`, then audit the resulting export. When the account is connected in Windsor.ai and no export was supplied, use `skill-174-windsor-mcp-intake`: `plan`, the planned `get_data` calls saved verbatim, `normalize`, `run`, then audit the resulting export. Search terms never come through Windsor MCP (raw query text would enter the conversation unsanitized): for search-term recipes, ask for the UI Search terms report, run 173 on it and import it into 174 with `--search-terms-from`. Never audit raw UI files or raw Windsor results directly.
1. Establish scope, approved evidence and the profile. Record unavailable or inapplicable prerequisites. **No profile supplied?** Do not ask the user to edit YAML. Ask only the questions the requested checks need, one short message at a time, in plain language: client name (show the derived `slug`, lowercase-hyphen, for confirmation); countries served (confirm the ISO codes you derive, e.g. "Italy → IT"); type of business (online shop, leads, local); main objective (sales, leads, …); brand names; whether they have a target and which kind: CPA as an amount in the account currency, or ROAS as a ratio (4 = 400%), never both inferred from one number; roughly how many days between click and conversion. "I don't know" is a valid answer and is written as `null`, never guessed. Write `profile.yaml` from the confirmed answers (fields per `skills/_resources/profile_template.yaml`), show a one-line summary for confirmation, and offer it as a download so the next analysis for this client starts by uploading it.
2. Shortlist from catalog metadata before opening bodies. Read selected recipes fully and verify applicability/inputs; metadata uncertainty requires inspection, not silent exclusion. If the index is absent, stale or lacks selection fields, inspect candidate frontmatter and Applicability only, then fully read selected recipes; never regenerate the catalog during a client audit. Resolve only used parameters and record their sources.
3. Run each selected recipe's `scripts/check.py` exactly as `skills/_resources/RUNTIME.md` describes, into one work folder per recipe. Its `findings`, calculations, parameters and `coverage` are authoritative for the deterministic steps: never recompute, round away or override them. Decide only its `ai_review` items, choosing a declared outcome with a cited rationale, then `finalize`. Exit 3 means stale; re-run. Exit 4 means rejected decisions; fix them. "Authoritative" means numbers are never silently rewritten, not that code is infallible. If a script result contradicts the recipe or the supplied evidence, or the script crashes, do not report that subcheck's finding. Keep the output, list the subcheck in Coverage as a runtime defect with the evidence, and flag it for library maintenance. Use local calculations yourself only for recipe steps the script reports as not implemented, and label them analyst calculations. No guessed configuration, missing-table fallback or unexplained extrapolation.
4. Dedupe, render the shared template, and order recommendations by evidenced business impact and confidence. An unquantified issue stays unquantified rather than acquiring a fabricated currency value.
5. End with Coverage: completed/partial/skipped/not applicable, exact missing evidence and follow-up measurement or controlled experiments. No account changes.

## Context and delegation

- Work inline for one small check. Delegate only substantial independent slices; never one agent per catalog row by default. A full audit can group recipes sharing evidence, with explicit IDs and coverage ownership.
- Each context reads shared rules once, then reuses them while version, source and scope stay unchanged. No rereading the front desk in workers, no full catalog for one check, no recursive `related` traversal and no schema/example/merge-history documents unless that task actually needs them.
- Read `DATA_CONTRACT.md`: opening scope, **Files and provenance**, **Calculation and decision invariants**; **Base entities** introduction plus only rows for used tables; **Supplemental evidence** only for a required non-base source/ambiguous source classification. A reference to a whole file is not a demand to load unrelated sections.
- Shared files are under `skills/_resources/`; pass exact paths, not root-level filenames. Locate headings/rows, then use narrow ranges (raw/verbatim mode where available) if the reader expands Markdown tables. Do not broaden reads merely for convenience; inspect truncated selection metadata before ruling out a candidate.
- Read `PARAMETERS.md` for actual threshold/rate comparisons, preserving its resolution and uncertainty rules; omit unused monetary resolution on inventory-only checks. Read `OUTPUT_TEMPLATES.md`: opening scope, **Header**, chosen language/format and **Severity and reporting rules** for final reporting; workers use **Worker handoff** instead of all final templates.
- Give workers a short brief: objective, exact recipe IDs/paths, relevant profile/evidence paths or verbatim sourced excerpts, shared-section references, inherited facts with source/window, permitted tools and the expected handoff. Do not paste catalog, session history, other domains or full exports. Unresolved facts stay unresolved; summaries never replace authoritative gates.
- Workers return **Worker handoff**, not a polished report plus a duplicate narrative. One coordinator deduplicates and renders the final report. Preserve evidence/calculations for valid nondefects, coverage gaps and conflicting parameters; brevity must not hide them.
- If a worker needs more evidence/context, it reads only the named dependency and records why. Track loaded recipe IDs and resource sections in the handoff; do not promise token/currency savings without measured usage.

Brief pattern (fill paths/sections, not entire documents):

```text
Objective: <one question; explicit scope and non-goals>.
Recipes: <exact canonical paths>. Evidence/profile: <local scoped paths>.
Shared root: skills/_resources/. Read assigned recipes; DATA_CONTRACT.md scope,
provenance/invariants and used schemas; PARAMETERS.md if used;
OUTPUT_TEMPLATES.md Worker handoff + severity rules. Prefer exact section reads.
Run each recipe's scripts/check.py per RUNTIME.md; decide only its ai_review items,
finalize, and hand off final.json findings/coverage unchanged.
Known facts: <only sourced, dated facts; unknowns explicit>.
Read-only local analysis; no network/account changes/raw identifiers. No catalog,
front desk, unrelated recipes or other workers' reports. Read extra dependencies only
when needed and explain why. Return Worker handoff with calculations and coverage.
```

## Resources

`skills/_resources/`: `DATA_CONTRACT.md`, `PARAMETERS.md`, `OUTPUT_TEMPLATES.md` (read the sections a task needs); `RUNTIME.md` for running recipe scripts and deciding `ai_review` items; `CLIENT_PROFILE.md` for ambiguous profile fields; `SKILL_SCHEMA.md` for authoring only. `skills/CATALOG.md`: generated selection index — search it, do not load it whole. `skills/MERGES.md`: consolidation history, consulted for absorbed IDs. `skills/_selftest/SKILL.md`: synthetic recipe execution and counterexamples; not real-account calibration; `skills/_selftest/grade_scripts.py` grades the scripts against its oracle.
