# PPC skill schema

A skill is an executable analysis recipe, not a list of desirable Google features. Its inputs must support its conclusions. Keep 70–120 lines where practical; over 160 lines is a review warning. Central rules live in `DATA_CONTRACT.md`, `PARAMETERS.md` and `OUTPUT_TEMPLATES.md`; do not create conflicting copies.

## Frontmatter

Use this structure (all top-level keys unindented):

```yaml
---
name: skill-NNN-descriptive-name
description: "The observable question and when this recipe applies."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  markets: all
  related: []
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-06
  agent: model | provider | date | session | change
---
```

Name equals directory. `agent` records the edit context; retain recent history when useful, without claiming another model's work. `merged_from` names removed recipes whose useful checks were incorporated, recorded in `MERGES.md`. `related` points only to surviving canonical names and defines adjacent ownership in the body.

`description` must be populated text. The catalog copies it and the complete `**Applicability:**`
block into searchable rows; keep limits/exclusions explicit, not just in names. Regenerate
`CATALOG.md` with the existing lint command after editing those fields. Do not maintain a
second manually summarized routing taxonomy. Selection metadata narrows reads; selected
recipes still execute their full canonical requirements.

`gaql_verified` remains null unless an actual supported-version API validation happened. Public documentation review is not live query validation. `Bash` is permitted only for local read-only computation on approved evidence, never network transmission or account mutation.

## Body sections

Use one H1 title and exactly these H2 sections, in this order:

### Purpose

State the observable business/configuration question. No fixed uplifts, mandatory tactic adoption, unsupported causal claims or educational boilerplate. Diagnostic labels are not business KPIs.

### Data Requirements

Include these exact labels:

- `**Applicability:**` Supported campaign types, objectives, market/control limits, and whether explicitly requested. Unknown business intent is not a defect.
- `**Required inputs:**` Base files from the data contract, plus explicit supplemental filenames, row grain, stable keys, required columns, window and source. A complete parent inventory is needed to discover missing children. Distinguish required and optional deeper checks.
- `**Missing inputs:**` Which subchecks become partial/skipped/Info and what evidence to request. Missing cannot mean enabled, disabled, noncompliant or no issue.

Metadata classifies the core conclusion; optional external checks are explicitly gated. If a body `**Data Source:**` label is included, it must match metadata: Account export, Custom query required, or External (beyond Google Ads data). Omit the duplicate label when metadata is sufficient. Custom query includes special Google Ads UI/config exports, not necessarily an API query.

**Reference GAQL is optional.** Include a query only when appropriate and defensible for the actual required evidence. A query must select stable IDs, required time/segment grain and actual input fields. A current setting is not historical state; a product title is not a query; a customer account ID is not consent verification. Never invent fields to make an audit seem executable. When no supported API query is established, specify a concrete UI/config/evidence export instead.

Queries execute through the Google Ads API only. UI and Editor can supply equivalent evidence only when their actual export capabilities support the declared fields; they do not execute GAQL. Declare truncation/privacy filtering and omit arbitrary LIMIT from a complete-inventory query. Use valid date literals such as LAST_30_DAYS or explicit BETWEEN dates, never fabricated LAST_90_DAYS/LAST_365_DAYS literals.

### Analysis Steps

Give a short substantive sequence with reproducible joins, formulas and decisions. Separate deterministic calculations from analyst judgments. Define the required business review or uncertainty method rather than saying “check significance”. Local calculations should be computed, not guessed.

All performance comparisons require compatible objectives/values, mature complete periods and the correct cohort sample. Both sides qualify. Handle zero/missing denominators. Separate observations from causes, scenarios from proven impact, and exposure from recoverable savings. Proposals must respect active bid strategy and supported controls.

### Thresholds

Use a two-column Condition/Severity table. Severity cells are **exactly** Critical, Warning or Info. Express money/sample thresholds via defined `{{parameters}}`; explain that discretionary cutoffs are triage heuristics rather than platform mandates or significance tests. Applicable hard platform requirements need an authoritative source and scope.

Critical requires directly evidenced material serving, measurement or safety failure. Optional feature absence, naming, small counts, low QS/Ad Strength and unknown evidence are never independently Critical. Zero-conversion spend is a guarded Warning screening path per `PARAMETERS.md`, not immediate pausing. Use explicit insufficient-evidence handling.

### Output

Reference `../_resources/OUTPUT_TEMPLATES.md`, specifying only the additional evidence/table content this recipe needs. No second full Short/Detailed template with divergent severities. Include entity IDs, condition keys, provenance/window, numerator/denominator/sample, thresholds, proposed action and uncertainty. No invented forecasts or executable change files. State adjacent owners to avoid duplicate reporting.
Delegated slices use the shared **Worker handoff** instead of duplicating a final report;
this changes layout only. All required calculations, valid nondefect observations and coverage remain.

## Executable check

Every recipe folder also contains `scripts/check.py` and `tests/test_check.py`, authored per `RUNTIME.md`. The script implements each Analysis Step as a declared check and assigns only the severities the Thresholds table makes decidable from evidence. Judgments go to closed-outcome `ai_review` items. `SKILL.md` stays the canonical contract, and a behavior change updates both files together. Lint requires the script (`--allow-missing-scripts` only while authoring).

## Kinds and data sources

| Kind | Meaning |
|---|---|
| deterministic | Reproducible calculations/configuration comparisons with explicit inputs |
| analyst | Interpretation, semantic intent, business context or noncausal hypothesis review |
| operational | Explicitly requested rule/script/schedule/configuration proposal; never deployed |

| Data source | Meaning |
|---|---|
| export | Core conclusions supported by listed base tables |
| custom_query | Additional Google Ads segments/history/configuration/export evidence required |
| external | Core conclusions need supplied site/CRM/GA4/Merchant Center/business/authorization evidence |

Markets: all, us_only, eea_relevant. Mark an entire skill us_only only if its entire scope is US-only; gate individual country-specific subsections separately.

Categories: structure, keywords, creative, bidding, targeting, quality, tracking, shopping_pmax, remarketing, waste, competitive, compliance, seasonal, platform. The catalog, not numerical ranges, is authoritative after consolidation.

## Validation and maintenance

`_resources/scripts/lint.py` validates names, metadata, references, evidence-section markers, source labels, severity vocabulary, parameters, routing and self-test references. It cannot prove data sufficiency, business correctness, API compatibility or causal claims. Do not equate a clean lint with account readiness.

`_selftest/SKILL.md` exercises recipes against planted observations and counterexamples. Preserve meaningful false-positive cases, not tests that merely pin old wording or arbitrary default prescriptions. Run the actual recipes; numerical reimplementations alone cannot prove the Markdown was followed. Real-account calibration and supported-version API validation remain distinct evidence.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | one evidence-first schema with honest validation scope
agent: gpt-6-astra | openai | 2026-09-07 | s_20260907_context_opt | canonical discovery text and compact worker output
agent: claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | executable check requirement
