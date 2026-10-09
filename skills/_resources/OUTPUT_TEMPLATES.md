# Output templates

Recipes specify report content; this file alone governs layout, language and severity. Use the profile's `report_language` (default `en`). Every report includes provenance, coverage and resolved parameters, including the Short format. Do not reproduce the same condition twice across skills.

## Header

```text
## <Audit title> — <Account name>
Account <id> · currency <ISO> · timezone <zone> · data <start–end> · snapshot <date>
Library eppc-ads-skills@2.0.0 · skills <canonical IDs> · profile <slug>
Evidence <source/files, completeness> · conversion basis <basis> · maturity <cutoff/unknown>
Parameters <resolved values and overrides used> · spend window <actual 30-day dates/unknown>
```

Do not invent a parameter value to fill the header. List unresolved values and the blocked checks. Distinguish observed exposure, estimated impact with assumptions, and unquantified impact.

## Short — English

```text
<header>

### Critical (<n>)
- **<entity name + ID>**: <confirmed material failure> → <recommendation> · Evidence <file/row/window, metric/sample> · <condition key> · <skill ID>

### Warnings (<n>)
- **<entity name + ID>**: <evidenced risk> → <contextual review/fix> · Evidence <file/row/window, metric/sample> · <condition key> · <skill ID>

### Info (<n>)
- **<entity name + ID>**: <hypothesis/opportunity/insufficient sample> · <uncertainty and next evidence> · <condition key> · <skill ID>

### Recommendations
1. <Action proposal, business rationale, evidence strength; impact only when supported>

### Coverage
- Completed: <skills/checks and scope>
- Partial/skipped: <skill + subcheck, missing file/fields or maturity, required next evidence>
- Not applicable: <skill + campaign/market/objective reason>
```

## Other report languages

For a `report_language` other than `en`, translate the Short — English headings and labels into that language. Preserve entity IDs, condition keys, skill IDs, ISO currency codes and the three severities exactly; translate only display text.

## Detailed

Use the same header, severity groups and Coverage. Expand each finding instead of changing severity:

- **Observation:** entity IDs, condition key, actual metric/configuration.
- **Evidence:** local source, keys/rows, period, numerator/denominator, maturity and parameter values.
- **Impact:** observed exposure; supported modeled impact with assumptions; or “not quantified”. Historical spend is not promised savings.
- **Recommendation:** proposed action, applicability, business context, verification or experiment required before action.
- **Confidence and limitations:** missing/confounded evidence and alternative explanations.
- **Owner:** canonical skill ID; related checks are cited without duplicating their finding.

A summary may count examined entities and findings, but never inflate confidence by counting missing checks as passed. Info and partial/skipped coverage are present in Detailed as well as Short.

## Worker handoff

For a delegated slice or self-test runner, return one compact evidence record, not a final
language template plus repeated execution narrative. The coordinator owns final rendering.
Keep the severity/reporting rules below; this format changes layout, not evidence standards.

- **Scope/provenance:** canonical IDs, account/entities, source paths/rows, windows, units,
  goal basis, maturity and completeness; reuse one common block rather than repeating it per finding.
- **Parameters:** values actually used, source/overrides and unresolved values that block checks.
- **Findings:** entity IDs, condition key, severity, actual evidence/calculation, recommendation,
  uncertainty and owner. Empty is allowed; “none” is not a whole-skill pass.
- **Observations:** nondefect configuration checks and numerator/denominator calculations that
  show the requested analysis ran. Reference findings rather than duplicating their evidence.
- **Coverage:** each requested check completed/partial/skipped/not applicable, with exact missing
  inputs or applicability reason. Keep different conditions on the same entity separate.
- **Reads:** recipe paths, shared resource sections and evidence files; explain any scope expansion.

Bullets or structured data are both acceptable. Do not copy raw exports, enumerate every passing
entity or reproduce the same calculation in several fields. Include all distinct evidence needed
to verify the decision; no hard output cap that would hide defects or unresolved checks.

## Severity and reporting rules

1. Internal severities are exactly `Critical`, `Warning`, `Info`; translate headings only. No fourth High tier. Missing evidence is a coverage limitation/Info, not proof of an account defect.
2. Critical requires directly evidenced material serving/measurement/safety failure. Warning indicates a supported risk to review. Info covers contextual opportunities, hypotheses and insufficient samples. Passing a heuristic is not proof of profitability.
3. Dedupe by account ID + entity ID + condition key + period. Different conditions on the same entity must remain. Choose the most specific skill for the same condition; never add overlapping exposure totals.
4. Every finding has evidence, a recommendation or exact next-evidence request, and its skill ID. Use stable IDs; names are display labels. Apply `PARAMETERS.md` samples/maturity and do not estimate undefined rates.
5. No fixed uplift promises, automated executions, executable change files or legal/platform approval certificates. Distinguish internal readiness from provider approval.
6. Do not list passing entities. If all applicable required checks completed with no findings: “No issues found in the completed scope”. If any core evidence is missing: “Assessment incomplete”, with exact Coverage gaps. Never call an unexamined account healthy.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | consistent severity, evidence and partial coverage
agent: gpt-6-astra | openai | 2026-09-07 | s_20260907_context_opt | compact evidence handoff without duplicate reports
agent: claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_english | English-only templates; other languages translated at render time
