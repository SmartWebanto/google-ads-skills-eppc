# Command Center — Check Registry

Full inventory of the ~105 checks in the spec, each classified by engine, cadence, required data and recipe coverage.

Legend:

- **Detection** — `R` zero-token rule (Python on CSV) · `AI` judgment needed · `R+AI` the rule filters, the AI classifies/diagnoses only the triggers
- **Cadence** (`Cad.`) — `D` daily · `W` weekly · `M` monthly
- **Data** — `E` base export · `Q` custom query/GAQL · `X` external evidence (LP, GA4, approved plans) · `C` CRM (V3)
- **Recipe** — library recipe used in diagnosis; `new` = code/logic to be built
- **Phase** — roadmap V1–V3

## Summary

| Area | Checks | Rule only (V1) | With recipes (V2) | Needs CRM (V3) |
|---|---|---|---|---|
| Daily Pulse | 11 | 10 | diagnosis | 1 |
| Performance | 12×4 comparisons | 12 | drill-down | qualified* |
| Search Terms | 13 | 5 | 11 | 1 |
| Keywords | 7 | 5 | 6 | 1 |
| Budget | 9 | 5 | 7 | 1 |
| Tracking | 13 + score | 6 | 12 | 2 |
| Lead Quality | 9 metrics | 0 | plumbing | 9 |
| Creative | 12 | 3 | 9 | qualified* |
| Landing Page | 9 | 4 | 7 | qualified* |
| Structure | 11 | 3 | 10 | 0 |

\* the "qualified" variants of existing metrics become available in V3 without new checks: the column changes, not the rule.

---

## Daily Pulse (§2)

| Check | Detection | Cad. | Data | Diagnosis recipe | Phase |
|---|---|---|---|---|---|
| Stopped conversions (0 over N days vs history) | R | D | E | 110 | V1 |
| Apparently broken tracking | R | D | E | 110, 071 | V1 |
| Anomalous conversion drop (lag-aware) | R | D | E | 110, 124 | V1 |
| Spend spike vs 14-day baseline | R | D | E | 124, 049 | V1 |
| CPA spike | R | D | E | 124 | V1 |
| CPC spike | R | D | E | 124 | V1 |
| CVR drop | R | D | E | 124 | V1 |
| Budget exhaustion / lost IS budget | R | D | E | 042 | V1 |
| Spend without results (maturity threshold) | R | D | E | 020, 122 | V1 |
| Important disapprovals | R | D | Q | 037 | V1 |
| Qualified-lead anomalies | R | D | C | new | V3 |

## Performance — What changed? (§3)

The 12 metrics (Spend, Clicks, CPC, CTR, Conv, CPA, CVR, Value, ROAS, Qualified Conv, Qualified CPA, Qualified CVR) × 4 comparisons (WoW, 7v7, 28v28, rolling trend) are **a single parametric check**: delta vs a per-metric significance threshold, with automatic decomposition (account → campaign → market) to answer *what changed*, not *what happened*.

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| Significant deltas on 9 Ads metrics | R | W | E | 124 (baseline), AI drill-down | V1 |
| Delta decomposition (which campaign/market explains the change) | R+AI | W | E | new (script) + area recipe | V2 |
| Delta on 3 qualified metrics | R | W | C | new | V3 |

## Search Terms Intelligence (§4)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| Wasted spend candidates (mature queries, 0 conv, spend > threshold) | R | W | E | 014, 015 — hypothesis, never "guaranteed savings" | V1 |
| Queries without conversions | R | W | E | 014 | V1 |
| Queries without qualified conversions | R | W | C | new + 014 | V3 |
| Negative keyword candidates | R+AI | W | E | 014, 016 | V2 |
| Negative ↔ wanted traffic conflicts | R | W | E | 017 | V1 |
| Keyword opportunities (converting queries that are not keywords) | R+AI | W | E | 013 | V2 |
| Competitor searches | R+AI | W | E | competitor-brand regex tagging + 014 | V2 |
| Brand leakage (brand queries in generic campaigns) | R | W | E | 002 | V1 |
| Informational intent | AI | W | E | 015, 024 | V2 |
| Irrelevant intent | AI | W | E | 014 | V2 |
| Geographic intent mismatch | R+AI | W | E | 014 + 136 (served-area context) | V2 |
| New query trends | R | W | E | 127 | V1 |
| Search intent deterioration | R+AI | M | E | 127, 023 | V2 |

## Keyword Intelligence (§5)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| Traffic but no conversions (maturity + lag) | R | W | E | 020, 122 | V1 |
| Conversions but poor leads | R | W | C | new | V3 |
| Profitable but limited by rank (lost IS rank) | R | W | E | 121, 039 | V1 |
| Profitable but limited by budget (lost IS budget) | R | W | E | 121, 042 | V1 |
| Keywords without traffic | R | W | E | pure rule (no dedicated recipe) | V1 |
| Cannibalized / duplicate keywords | R+AI | W | E | 018 — legitimate geo/product copies preserved | V2 |
| Queries that deserve a dedicated exact keyword | R+AI | W | E | 013 | V2 |
| Match type distribution | R | M | E | 012, 022 | V2 |
| Quality Score: distribution, components, trend | R | M | E/Q | 064, 065, 066, 067, 068 | V2 |

## Budget Command Center (§6)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| Monthly pacing vs approved plan | R | D | E+X | 044 | V1 |
| Overspend / underspend forecast | R | D | E+X | 044, 123 — explicit assumptions, not prophecies | V1 |
| Budget limited campaigns | R | D | E | 042 | V1 |
| Inefficient campaigns with too much budget | R+AI | W | E | 045 | V2 |
| Efficient campaigns without enough budget | R+AI | W | E | 045, 042 | V2 |
| Allocation across markets | AI | M | E | 045, 136 | V2 |
| Brand/Generic/Competitor/AI allocation | R+AI | M | E | 002 (classification) + 045 | V2 |
| Shared budget appropriateness | R | M | Q | 050 | V2 |
| Qualified CPA per € invested | R | W | C | new | V3 |

045 guardrail: "deserves more budget" requires cohorts with comparable objectives and evidence of marginal response — the claim "qCPA −38% ⇒ scale" is a hypothesis for an experiment (§13), not an automatic rule.

## Conversion & Tracking Health (§7)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| Conversion action stopped | R | D | E | 110 | V1 |
| Conversion spike / drop | R | D | E | 110, 124 | V1 |
| Duplicate conversions | R+AI | W | E | 071, 076 | V2 |
| Primary/secondary changes | R | W | Q | 076, 131 | V2 |
| Conversion value changes | R | W | E | 107, 112 | V2 |
| Attribution changes | R | W | Q | 076, 131 | V2 |
| GA4 vs Google Ads discrepancies | R+AI | W | X | 106, 071 — attribution differences ≠ breakage | V2 |
| Google Ads vs CRM discrepancies | R+AI | W | C | 071 | V3 |
| Conversion lag (maturity windows) | R | W | E | 110 + profile.yaml | V1 |
| Enhanced conversions (Web/Leads) | AI | M | X | 072, 073 | V2 |
| GCLID availability | R | W | C/X | 073, 080 | V3 |
| Offline import freshness/outcomes | R | W | X | 080 | V2 |
| Post-incident data exclusion | AI | event | X | 111 | V2 |
| **Tracking Confidence Score** (weighted aggregate of the checks above) | R | D | — | new (formula) | V2 |

## Lead Quality Center (§8)

No check is covered by the recipes: **entirely new, V3**. The recipes only validate the plumbing (080, 052, 107, 073). Metrics to compute from a sanitized GCLID/CRM join: Leads, Qualified Leads, Qualification Rate, Qualified CPA, Opportunities, Opportunity CPA, Customers, CAC, Revenue — at campaign, keyword, query and LP level.

## Ads & Creative Intelligence (§9)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| RSA/asset performance (join on stable IDs) | R | W | Q | 029 | V2 |
| Headline/description diversity and validity | R+AI | M | E | 025, 026 | V2 |
| Pinning audit | R | M | X | 028 | V2 |
| Descriptive Ad Strength (never a quota) | R | W | E | 025 — "Poor" + good qCPA ⇒ no action | V1 |
| Message patterns / CTA / USP | AI | M | E | new (semantic analysis on asset export) | V2 |
| Creative fatigue (CTR decay over windows) | R | W | E | new (rule) + 029 | V2 |
| Duplicated messaging | R+AI | M | E | 025 partial + new | V2 |
| DKI review | AI | M | E | 033 | V2 |
| Disapproval / policy | R | D | Q | 037 | V1 |
| Editorial errors | AI | M | E | 038 | V2 |
| Ad ↔ landing page consistency | AI | M | X | 034 | V2 |
| Creative A/B (serving ≠ experiment) | AI | M | X | 032 | V2 |

## Landing Page Intelligence (§10)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| CVR/CPA by LP × campaign/keyword/intent | R | W | E | aggregation rule (final URL) | V1 |
| Qualified CVR/CPA by LP | R | W | C | new | V3 |
| LP mismatch (intent ↔ content) | AI | M | X | 024, 034 | V2 |
| LP deterioration (CVR trend by LP) | R | W | E | new (rule) + 069 | V2 |
| Campaigns pointing to inefficient LPs | R | W | E | rule + 069 | V2 |
| Page speed (field/lab data, not a QS proxy) | R | M | X | 078 | V2 |
| Broken URLs / availability | R | D | X | 079, 125 | V1 |
| Engagement (GA4) | R | W | X | 106 (plumbing) + rule | V2 |
| A/B test opportunities | AI | M | X | 032 | V2 |

## Campaign Structure (§11)

| Check | Detection | Cad. | Data | Recipe | Phase |
|---|---|---|---|---|---|
| Campaign/ad group overlap | R+AI | M | E | 001, 004 | V2 |
| Keyword overlap | R | M | E | 018 | V1 |
| Brand cannibalization | R+AI | M | E | 002 | V2 |
| Generic cannibalization | R+AI | M | E | 018 | V2 |
| PMax ↔ Search interaction | R+AI | M | X | 094 — descriptive screening, never a causal claim from aggregates | V2 |
| Match type conflicts | R | M | E | 017, 012 | V1 |
| Country/language overlap | R | M | E | 007, 053 | V2 |
| Unnecessary fragmentation | AI | M | E | 001, 046 | V2 |
| Low-volume campaigns | R | M | E | rule + 001 | V1 |
| Naming consistency | R | M | E | 003 | V2 |
| Settings hygiene / defaults | AI | M | X | 007, 009, 119 | V2 |

## Cross-cutting (§12–§16)

| Component | Detection | Cad. | Recipe | Phase |
|---|---|---|---|---|
| Monthly Strategic Review (Keep/Stop/Scale/Test/Investigate) | AI | M | selective full audit from the catalog | V2 |
| Experiment Center (verdicts on pre-specified metrics) | R+AI | event | 032, 010 | V2 |
| Change Log → "what happened after?" | R+AI | on-demand | 131 + pre/post export comparison | V2 |
| AI Analyst (chat on already-filtered data) | AI | on-demand | front-desk Triage | V2 |
| Prioritization Engine (dedup, impact, confidence) | R+AI | every run | recipe output contract + dedup script | V2 |

---

## Totals

~105 distinct checks. **~45 detectable in V1 with rules on exports alone** (the full Daily Pulse plus half of the weekly). **~50 diagnoses covered by existing recipes** in V2. **~12 need CRM** (V3) — all the "qualified" ones. The purely `new` checks are few and concentrated: delta decomposition, creative fatigue/patterns, LP deterioration, Tracking Confidence Score, and the whole Lead Quality Center.
