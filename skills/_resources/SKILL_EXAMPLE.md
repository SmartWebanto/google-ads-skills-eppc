# Example: evidence-backed skill and report

Use the live `../skill-030-ad-extension-coverage-audit/SKILL.md` as the asset-coverage recipe and `SKILL_SCHEMA.md` as the authoring contract. Do not copy a second, divergent recipe from this file. Counts of optional assets are not universal requirements, and no fixed CTR uplift is promised.

## Example inputs (synthetic)

- Campaign 1002 sells online-only products; phone sales are not a business objective.
- Complete campaign/ad-group inventory and complete account/campaign/ad-group asset associations are supplied.
- Asset 9001 is linked to campaign 1002. Its promotion text advertises an offer the supplied approved calendar says ended; timestamped serving evidence shows that same stale text still served after the approved end.
- Other assets are usable. The account has no call asset. There is no experiment estimating the cost of the stale message.

## Correct reasoning

1. Absence of a call asset is not a problem for this stated objective; do not prescribe one.
2. A configuration end date alone would not prove stale serving. Here the observed serving interval and authorized offer dates support a stale-message finding.
3. Recommend review/removal of the stale association, not execution. Report observed affected impressions or spend only when the serving evidence contains them; do not call all campaign spend wasted.
4. Assign one canonical owner for the stale-offer condition. Related promotional/configuration checks may cite it but do not duplicate the finding.

## Illustrative short report

```text
## Asset review — Synthetic online retailer
Account demo · currency EUR · timezone Europe/Rome · data 2026-08-04–2026-09-02 · snapshot 2026-09-03
Library eppc-ads-skills@2.0.0 · skills skill-030-ad-extension-coverage-audit · profile demo
Evidence assets + association inventory + approved offer calendar + dated serving log; complete for this condition
Conversion basis interaction date · maturity not used for configuration finding
Parameters none used · spend window not used

### Warnings (1)
- **Campaign 1002 / asset 9001**: expired offer text served after its approved end → review the stale association · Evidence approved calendar and dated serving log; monetary impact not quantified · stale_offer_serving · skill-030-ad-extension-coverage-audit

### Recommendations
1. Confirm the current approved offer and propose correcting the stale association. No account changes made.

### Coverage
- Completed: asset applicability, effective associations and observed offer consistency for campaign 1002.
- Not applicable: phone-asset coverage; profile specifies online-only sales.
```

The example illustrates the evidence/decision distinction, not an additional executable fixture. Actual recipe output uses its declared condition ownership and `OUTPUT_TEMPLATES.md`.

## Counterexamples worth testing

- A complete inventory with no optional feature must not be reported as a critical defect.
- An incomplete inventory must be labeled incomplete, not empty or healthy.
- Two valid alternative headlines pinned to the same position are not conflicting pins.
- Returning to normal after a promotional CVR spike does not justify routine negative seasonality compensation.
- A different ROAS target direction cannot reuse a CPA rule.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | remove prescriptive scaffold and clarify evidence examples
