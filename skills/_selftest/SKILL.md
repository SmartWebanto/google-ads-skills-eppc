---
name: ads-selftest
description: >
  Self-test of the Google Ads skills library. Runs chosen skills as fresh sub-agents
  against a synthetic export with planted defects and grades their findings against
  the expected ones. Use after editing skills, parameters, templates or the data
  contract, or when asked "le skill funzionano?", "testa le skill", "self-test",
  "smoke test della libreria".
allowed-tools: Read, Grep, Glob, Bash, Agent
metadata:
  library: eppc-ads-skills@1.1.0
  author: smartweb
  version: "1.0"
  category: library-selftest
---

# Library self-test

Proves that a skill recipe is executable by an agent and yields the planted findings,
nothing more. It does not prove thresholds are right for a real account: only a
real export does that.

## What is here

- `make_fixture.py` — generates `fixture/export/` (12 CSV tables + `custom/impression_share_loss.csv`, per `_resources/DATA_CONTRACT.md`) and `fixture/profile.yaml`. Deterministic (seeded). The planted defects are commented in the script.
- `fixture/expected.json` — the cases: which skill to run, which tools the runner may use, the findings that must appear (`expect`) and those that must not (`reject`).

## Procedure

1. **Regenerate the fixture** so it matches the generator: `python3 skills/_selftest/make_fixture.py`.
2. **Read `fixture/expected.json`.** Run every case, or only the cases the user names.
3. **Run each case in a fresh sub-agent**, all cases in parallel, with this prompt (fill the placeholders; keep the tool restriction exactly as the case says, it mirrors the skill's `allowed-tools`):

   ```
   You are a Google Ads audit agent running ONE skill from a Markdown skill library against a client's export. Follow the recipe literally.
   Library root: <absolute repo root>
   Read, in this order: ads/SKILL.md (operating rules; ignore routing), skills/_resources/PARAMETERS.md, skills/_resources/DATA_CONTRACT.md, skills/_resources/OUTPUT_TEMPLATES.md, then the skill: skills/<skill>/SKILL.md
   Client profile: <repo>/skills/_selftest/fixture/profile.yaml
   Export folder: <repo>/skills/_selftest/fixture/export/ (CSV tables named per the data contract; custom query results under export/custom/)
   TOOL RESTRICTION: you may ONLY use <tools>. Do not run anything else; do every count and calculation yourself. Do not open any file outside the library root, the profile and the export folder; in particular never open expected.json or make_fixture.py.
   Deliverable: (1) the Short report in English exactly per OUTPUT_TEMPLATES.md, header first, findings grouped Critical / Warnings / Info, every finding line ending with the skill id, then Recommendations; (2) a section "## Execution notes": parameter values resolved and how, tables used, anything ambiguous, missing or unexecutable in the recipe, and a 1-5 confidence score on your numbers with the reason.
   Never invent data. If a table the skill needs is missing, say so and skip that step.
   ```

4. **Grade each report.** A finding line is a bullet under a severity heading (`### Critical`, `### Warnings`, `### Info`). An `expect` item is **found** when a line in that section contains every `must_contain` string (case-insensitive) and, if `any_of` is present, at least one of those. It is a **severity mismatch** when such a line exists only under another heading, and **missing** otherwise. A `reject` item **fails** when a matching line exists in the named section (any section if `severity` is absent). Verdict per case: **pass** when nothing is missing, nothing mismatched and nothing rejected; otherwise **fail**.
5. **Report** a table, then the details:

   ```
   | Case | Expected | Found | Mismatched | Missing | Rejected hits | Agent confidence | Verdict |
   ```
   For every failure quote the offending or absent finding and the agent's execution notes. Reproduce the "Execution notes" of every run in full under a heading per case: they are the recipe feedback (ambiguities, missing data, unreachable rows) and the reason this test exists.
6. **Never edit a skill from inside this test.** List the recipe fixes the notes suggest; the user decides.

## Determinism check (optional)

Run one case twice, or once with the case's tools and once with `Bash` added (so the runner can use Python over the CSVs), and diff the two sets of (severity, entity) pairs. Identical sets mean the recipe is executable by hand at this table size; a difference shows where mental arithmetic breaks and a computed pass is needed.

## Adding a case

1. Plant the defect in `make_fixture.py` with a comment naming the skill it targets; regenerate.
2. Add the case to `fixture/expected.json` with `expect` items that a correct run must produce and `reject` items that a sloppy run would produce (false positives, wrong denominators, out-of-scope campaigns).
3. Keep `must_contain` to entity names and unmistakable numbers; put wording alternatives in `any_of`.
4. Run the case once with its tools and once with Bash before trusting it.

## Known limits

- The fixture is small (5 campaigns, 52 keywords, 37 search terms): it tests recipe logic and wording, not scale. Real search-term reports are 100x larger, where a runner without Bash will lose precision.
- The grading is textual. A run that finds the defect but names the entity differently is reported as missing: read the quoted lines before concluding the recipe is broken.
- Runs cost sub-agent time; four cases take a few minutes.
