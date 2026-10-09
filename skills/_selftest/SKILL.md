---
name: ads-selftest
description: >
  Execute canonical Google Ads recipes against synthetic exports and adversarial
  counterexamples. Use after recipe/contract changes or requests to test whether
  the library works. Tests finding behavior, not real-account calibration.
allowed-tools: Read, Grep, Glob, Bash, Agent
metadata:
  library: eppc-ads-skills@2.0.0
  author: smartweb
  version: "2.1"
  category: library-selftest
  agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | grounded counterexamples; gpt-6-astra | openai | 2026-09-07 | s_20260907_context_opt | scoped reads and compact evidence handoffs; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | deterministic script grading section
---

# Library self-test

Proves that the exercised recipe can consume the provided evidence, identify planted defects and avoid the specified false positives. A passing test does not validate every GAQL query, calibrate heuristics on real accounts, or prove causal advertising impact.

## Inputs

- `make_fixture.py`: deterministic synthetic base export and scenario evidence generator. Writes only beneath `fixture/`.
- `fixture/expected.json`: cases, export/profile location overrides, expected and rejected findings, and required observations that prove the core check actually ran.
- Base cases use `fixture/export/` and `fixture/profile.yaml`. A case may name a scenario-local export/profile instead. All domains and identifiers are synthetic.

## Procedure

1. Generate fresh evidence: `python3 skills/_selftest/make_fixture.py`. Do not substitute a manually altered generated export for the generator.
2. Read `fixture/expected.json` as coordinator. A requested full self-test runs every case. For a scoped recipe correction, select all cases for the affected canonical IDs (including consolidated ownership), plus cases whose evidence/contracts changed; state selection and untested scope. Shared-rule changes require representative affected boundaries and an explicit coverage rationale; never label a subset a full self-test.
3. Run each selected case in a fresh analysis agent. Pass only case ID, canonical recipe path, evidence/profile paths and the short prompt below—never expected.json, scenarios.json, generator source, grading predicates or another runner's output. Preserve isolation; do not reuse another case's conclusions. Independent cases may run concurrently once source edits are complete.
4. The runner reads the assigned recipe and task-relevant canonical contract sections, computes locally, and returns one **Worker handoff** per OUTPUT_TEMPLATES. No front desk, catalog, unrelated schemas/language templates or duplicate polished report. Local read-only Read/Grep/Glob/Bash/Python only; no network/account actions. Temporary calculations are not account change files.
5. Grade findings and required observations. A case with only rejected findings cannot pass by skipping everything: its required observations must prove the relevant evidence was inspected and the correct calculation/interpretation was made.
6. Record failures with actual output and missing evidence. Fix the recipe or fixture only when the evidence demonstrates which is wrong; never weaken a behavior expectation to make a broken recipe pass. Rerun affected cases after a correction.

## Runner prompt

```text
Execute case <id>, recipe <canonical path>, profile <path>, evidence <folder>.
Read the complete assigned recipe, not the front desk/catalog/other recipes.
Shared root: skills/_resources/ (not repository root).
From DATA_CONTRACT.md read scope, Files and provenance, Calculation and decision invariants,
and Base entities introduction/used rows. Read Supplemental evidence if needed.
Read PARAMETERS.md for used comparisons/parameters, not unused money thresholds.
From OUTPUT_TEMPLATES.md read Worker handoff and Severity and reporting rules.
Locate/read exact sections, raw/verbatim if needed to avoid expanded table previews.
Consult skills/_resources/CLIENT_PROFILE.md only for ambiguous fields.
Use local read-only calculations; no network, account changes or raw identifiers.
Never read expected.json, scenarios.json, make_fixture.py, other cases or runner reports.
Return Worker handoff: findings, actual nondefect observations/calculations, used parameters,
source/period/maturity, check-level coverage and a read log. No duplicate final report.
Missing evidence is not a pass. Read extra dependencies only when necessary; explain why.
```

## Grading

For each `expect` or `reject` item, `must_contain` strings are case-insensitive evidence/entity matches on genuine handoff findings (or finding bullets), not arbitrary wording or negated nondefects. If `any_of` exists, at least one alternative must also occur. `severity`, when supplied, selects Critical/Warning/Info (plural report headings map to these singular values). A positive match under the wrong severity is a mismatch, not a pass.

`observations` strings describe semantic facts the coordinator verifies in the handoff's observations, calculations and coverage. They are not prompts given to the runner. Record an exact supporting quote/calculation for each. Missing/contrary evidence fails; a clean report or shorter output is not proof of execution. Distinguish missing fixture inputs from a recipe inventing a defect.

Report per case: Expected / Found / Mismatched / Missing / Rejected hits / Observations satisfied / Verdict. Save complete handoffs and grading evidence when numerous cases run. User summaries distinguish tested cases/skills from untested scope. Include recipe/resource reads when evaluating context savings; do not extrapolate word counts into billed token costs.

## Deterministic script grading

`python3 skills/_selftest/grade_scripts.py [--case <id>]` runs each case's recipe `scripts/check.py` on the case evidence. It grades the case against `expected.json` from the coordinator side; scripts never read the oracle.

| Verdict | Meaning |
|---|---|
| PASS | Every expectation is met by a deterministic finding and no rejected finding appears |
| PENDING_AI | An expected severity is reachable only through an `ai_review` outcome; the AI step still has to decide it |
| FAIL / ERROR | A rejected finding appears, an expectation is unreachable, or the script crashed |

`observations` stay semantic and are graded by the procedure above.

## Maintaining cases

- Add both a real defect and a plausible valid setup/counterexample when a decision boundary is uncertain. Pin business behavior, IDs and clear metrics—not decorative wording or a false default mandate.
- Keep schema, window, grain, units, completeness and maturity explicit. Empty inventories have column headers and complete-manifest evidence; missing inputs remain genuinely missing.
- Never let tests see expected answers. Formula-only reimplementation is not a recipe execution test. Scoped reading must preserve source provenance, measurement/maturity, currency/target precedence, sample, privacy and severity gates.
- Optional determinism check: run a case twice and compare entity/condition/severity plus coverage; wording may differ. Use local arithmetic in both runs rather than introducing avoidable numerical error.

## Limits

Fixtures are small and synthetic. They test recipe logic and evidence handling, not export-scale performance, actual account false-positive rates, provider policy approval, or live GAQL compatibility. Those require separate, explicitly documented verification.
