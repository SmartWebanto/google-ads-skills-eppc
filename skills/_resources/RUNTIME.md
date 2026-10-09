# Runtime: deterministic checks + AI review

Every recipe ships `scripts/check.py`. The script computes what can be computed; the AI decides only what the script hands over as `ai_review` items. Neither changes the account. The script is standard-library Python 3.10+, so it runs in Claude Team's code-execution sandbox without network access or package installs.

## Running a skill (Claude Team or any shell)

1. Put the evidence in one folder: `account.csv`, `campaigns.csv`, … as named in `DATA_CONTRACT.md`, plus `custom/` and `external/` subfolders. If the user uploaded a ZIP, extract it into a working folder first. The client profile (`profile.yaml` or JSON) is optional but many checks need it.
2. Run the script from the skill folder. Replace `<skill>` with the recipe folder:

   ```bash
   python3 <skill>/scripts/check.py run --export <evidence> --profile <profile.yaml> --out <work>/<skill>
   ```

   The script prints a summary and writes `result.json` and `findings.csv`. For multi-account exports it writes `accounts/<customer_id>/result.json` per account. Each account keeps its own currency and parameters.
3. Read `result.json`:
   - `findings` are deterministic and already have a severity.
   - `ai_review` items are the judgments left to you. Each has a question, the evidence, closed `outcomes` (each outcome maps to a severity or none) and guidance.
   - `coverage` records completed, partial, skipped and not-applicable checks, with the exact missing `file:column` inputs.
   - `parameters` lists the resolved thresholds.
4. For each `ai_review` item, choose one declared outcome using only the recipe's `SKILL.md`, the profile and the item evidence. Write `decisions.json`:

   ```json
   [{"id": "<ai_review id>", "outcome": "<declared outcome>", "rationale": "<why, citing evidence>", "proposal": {}}]
   ```

   If the evidence is insufficient, pick the `uncertain` outcome where one exists. Otherwise leave the item undecided: it stays pending and appears in Coverage.
5. Validate the decisions:

   ```bash
   python3 <skill>/scripts/check.py finalize --export <evidence> --profile <profile.yaml> --out <work>/<skill> --decisions decisions.json
   ```

   Finalize re-runs the checks and handles decisions as follows:
   - It refuses with exit 3 when the evidence, profile or code changed since the reviewed run.
   - It rejects unknown ids, undeclared outcomes and missing rationales.
   - It applies the recipe's own deterministic `verify` checks. For example, a proposed negative must not block a converting desired query.
   - Accepted outcomes replace any provisional finding. The result is written to `final.json`.
6. Render the report from `final.json` with `OUTPUT_TEMPLATES.md`. Never edit, recompute or round away script numbers. Never promote a severity the script or a validated decision did not produce. List `pending_review` items and non-completed coverage in Coverage. If script output contradicts the recipe or the evidence, report a runtime defect for that subcheck in Coverage instead of the finding.

Exit codes:

| Code | Meaning | What to do |
|---|---|---|
| 0 | Outputs written; findings are normal output | Continue |
| 2 | Unusable input | Fix the named file |
| 3 | Stale review | Run again and review again |
| 4 | `final.json` written, but at least one decision was rejected | Read the printed problems, correct those decisions and finalize again |

## Authoring `scripts/check.py`

```python
"""check.py — skill-NNN deterministic <topic>.   (CodeDNA header: exports/used_by/rules/agent)"""
import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p)); break
from adsrun import cli, values as V

SKILL = "skill-NNN-slug"      # equals the folder name
VERSION = "1.0.0"             # bump on behavior change

def run(ctx): ...
def verify(ctx, item, decision) -> list[str]: return []   # optional

if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
```

The bootstrap resolves `adsrun` in both layouts: the repo/bundle layout at `skills/_resources/runtime/`, and the standalone ZIP layout at `scripts/adsrun/`, which the builder vendors.

### API

- `ctx.check(id, title, needs={"table": [cols]}, applicable=True, na_reason="")` → `Check`.
  - If any required table or column is missing, it records `skipped` with exact `table:column` names.
  - If the manifest marks a table incomplete, truncated or undeclared, it marks the check `partial`. Absence cannot be proven from such a table.
- `Check` methods:
  - `.finding(condition_key, severity, entity, summary, evidence=, calculation=, recommendation=, uncertainty=)` records a finding.
  - `.observe(text, **data)` records a non-defect calculation.
  - `.review(condition_key, entity, question, evidence=, outcomes=, guidance=, provisional=finding)` queues an AI judgment.
  - `.partial(reason, missing)`, `.skip(...)` and `.not_applicable(reason)` set coverage.
- Evidence access:
  - `ctx.table(key)` / `ctx.rows(key)` read tables. Keys are relative paths without extension, e.g. `custom/budget_history`. Empty cells are `None`, meaning unknown.
  - `ctx.money(v)` and `ctx.rate(v)` apply account units.
  - `adsrun.values` provides `num`, `ratio`, `parse_date`, `split_list`, `boolean` and `norm_text`.
- `ctx.params.get(name, campaign_id=None)` → `Resolved(value|None, source, reason)`. It follows `PARAMETERS.md` exactly. When the value is `None`, the dependent check must be `partial`/`skipped` and name the reason.
- Scope helpers:
  - `ctx.mature` is `True`, `False` or `None`. Performance-driven prescriptions need `True`; otherwise the check is partial and reports only descriptive totals.
  - `ctx.tracking_for_campaign(id)` → `(True|False|None, note)`: goal-specific tracking evidence. It is `True` only when every campaign goal is evidenced, either by `profile.tracking_verified[goal] = {status: verified, verified_from ≤ period start, verified_through ≥ period end, source_ref}` or by an enabled mapped conversion action that converted within `max(lag, 7)` days before period end. Zero-conversion Warning paths require `ctx.mature is True` and `True` here. `ctx.goal_ids(id)` returns the declared goals.
  - Also available: `ctx.currency`, `ctx.period_start/end`, `ctx.snapshot`, `ctx.as_of`, `ctx.profile`, `ctx.account`.
- `adsrun.negatives` provides `blocks()` and `effective_negatives()`: literal negative semantics shared by 014/015/016/017.

### Rules

1. **One check per recipe analysis step or subcheck.** Use stable `id`s. Every declared check ends with a coverage status. Missing evidence is `skipped`/`partial`, never a finding and never a pass.
2. **Deterministic only.**
   - No clock, randomness, network, subprocess or third-party imports.
   - No writing outside `--out`.
   - Iterate in sorted/stable order. Join on IDs, never names.
   - Guard one-to-many joins and zero denominators with `V.ratio`, where zero means undefined.
3. **Severity comes from the recipe's Thresholds table.** A script sets a severity only when the condition is fully decidable from evidence. When the recipe requires business intent, relevance, causality, policy meaning or semantic quality, emit a `review` whose outcomes map one-to-one to the recipe's severity rows (plus `uncertain`/no-finding). Where the recipe allows a lower provisional severity, pass the provisional finding.
4. **Critical findings.**
   - Deterministic Critical is allowed only for a directly evidenced material failure named in the recipe, e.g. a verified hard-cap breach.
   - Otherwise Critical is reachable only through a review outcome, and `verify` must require an evidence reference.
5. **Record the calculation.** Every finding and observation carries numerator, denominator, window and parameter source in `evidence`/`calculation`. Exposure is never labeled savings.
6. **`verify` re-checks proposals deterministically.** Examples: a proposed negative against desired/converting queries; a budget proposal against approved caps. Return problems; never mutate evidence.
7. **Tests.** `skills/<skill>/tests/test_check.py` (unittest, temp folders) covers the recipe's real decision boundaries and counterexamples. Tests are excluded from packages. `skills/_selftest/grade_scripts.py` grades all scripts against the hidden oracle.

agent: claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | runtime contract for Team-runnable checks
agent: claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime_b | exit 4, verified_from, runtime-defect reporting path
