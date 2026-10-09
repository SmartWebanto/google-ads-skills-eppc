---
name: google-ads-command-center
description: >
  Google Ads Command Center (Ads CC): today's attention, pulse,
  weekly/monthly review, search terms, budget, tracking, change log, experiments. Uses ads
  skill; recommend only.
metadata:
  library: eppc-ads-skills@2.0.0
  author: smartweb
  version: "1.0"
  category: engine-frontdesk
  requires: ads
  agent: claude-fable-5-1 | anthropic | 2026-09-15 | s_20260915_cc | command vocabulary, state sources, severity mapping; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | script execution rule, recipes 163-172; claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_english | translated to English; Italian trigger aliases removed (route by meaning); claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor | Windsor MCP data source via intake 174; write tools forbidden
---

# Google Ads Command Center

Operational front desk on top of the library. It answers **"What changed, why, does it matter, what next?"** — not "what happened". It interprets a command, reads the state (triggers, findings, Notion), and delegates every diagnosis to the **`ads`** skill with the smallest set of recipes. It never makes account changes.

Commands route by meaning: equivalent requests in any language map to the same row.

## State sources (in order of preference)

| Source | Content | How |
|---|---|---|
| Notion — **GACC Findings** DB | open/approved findings, with severity, impact, confidence, evidence | Notion connector: search the database by title, then query |
| Notion — **GACC Change Log** DB | dated account changes | same |
| Notion — **GACC Experiments** DB | hypotheses, pre-specified metrics, verdict | same |
| Attached files / Project | `triggers.json`, `tracking-score.json`, `HOMEPAGE.md`, `findings/*.md`, `export/YYYY-MM-DD/*.csv`, `profile.yaml` | read only the files the command needs |
| Windsor.ai MCP (when connected and no current export exists) | fresh Google Ads data for one account | `ads` → `skill-174-windsor-mcp-intake` (plan → `get_data` saved verbatim → normalize) into `export/YYYY-MM-DD/`, then the command's recipes |

If a source is missing, say so ("no triggers available", "Change Log not connected") and continue with what is there. Never invent state.

Mature windows: exclude the last lag days declared in `profile.yaml` from conversion metrics; if the lag is unknown, declare the metrics immature.

## Commands

Routing: each command opens at most **1–3 recipes** through `ads`; only "monthly review" may require a full audit. Pass `ads` the exact IDs, the scope and only the relevant files — not the whole export.

### Attention

| Command | Action | Recipes via `ads` |
|---|---|---|
| what needs my attention today? | Today's Attention: merge open findings (Notion) and `triggers.json`; sort by severity × impact × confidence | only if a trigger has no diagnosis: 110, 124, 042, 037 |
| pulse | Summarize the last deterministic run; diagnose only the triggers present | 110, 124, 042, 037, 079 |
| is tracking ok? (tracking ok?) | Tracking Confidence Score + failed checks | 110, 071, 076 |

### Performance

| Command | Action | Recipes |
|---|---|---|
| what changed this week / in <market, campaign>? | significant 7v7 deltas, decomposed by campaign/market | 124, 136 |
| 28-day trend | 28v28 on the core metrics | 124, 137 |
| why did CPA go up? / why did conversions drop? | causal triage in order: tracking → budget → auction → creative → LP; stop at the first evidenced cause, list the others as not ruled out | 110, 042, 121, 029, 069 |

### Search terms and keywords

| Command | Recipes |
|---|---|
| search terms to add as negatives | 014, 016, 017 |
| queries that deserve a keyword | 013 |
| brand leakage | 002 |
| search term waste | 014, 015 — exposure hypotheses, never "savings" |
| new queries / trends / competitors | 127; 014 for classification |
| keyword ideas to test | 171 |
| keywords without conversions (keyword senza conversioni) | 020, 122 |
| keywords limited by rank / budget | 121, 039, 042 |
| duplicate keywords | 018 |
| quality score | 064, 065, 066 |
| match type | 012, 022 |

### Budget and bidding

| Command | Recipes |
|---|---|
| pacing | 044 |
| budget-limited campaigns | 042 |
| who deserves more budget? / where do I move €X? | 045, 042 — comparable cohorts, marginal response; "deserves" is a hypothesis for an experiment |
| brand vs generic budget | 002, 045 |
| realistic target CPA/ROAS? | 040 |
| learning phase | 041 |

### Tracking

| Command | Recipes |
|---|---|
| conversions stopped? | 110 |
| GA4 vs Ads | 106, 071 |
| offline import | 080 |
| enhanced conversions | 072, 073 |
| conversion actions | 076 |
| consent | 075 |

### Creative, landing pages, structure, PMax/Shopping

| Command | Recipes |
|---|---|
| RSA performance / weak assets (asset deboli) | 029, 025, 026, 028 |
| disapproved ads | 037 |
| worst LPs / broken LPs / ad vs LP / page speed | 069, 079, 034, 078 |
| campaign overlap | 001, 004, 018 |
| PMax vs Search / PMax channels / asset group (PMax canali) | 094, 128, 089 |
| prepare the data / I downloaded the reports | 173 (guided intake, then the other recipes) |
| pull fresh data from Windsor / refresh the export | 174 (Windsor MCP intake, then the other recipes) |
| feed titles / attributes | 082, 083 |
| products that spend / trending products / not served | 163 |
| PMax search terms / categories (search terms / categorie PMax) | 164 |
| is the feed up to date? / disapproved products | 165 |
| performance by landing page | 166 |
| ads on out-of-stock products / old years in ad text | 167 |
| changed prices / price competitiveness | 168 |
| match type / negative conflicts (conflitti match type / negative) | 017 |

### Strategy and operations

| Command | Action |
|---|---|
| weekly | 7v7 performance + search terms + keywords + budget + tracking + creative; AI only on significant deltas/triggers |
| monthly review / what do I do next month? | weekly + 28v28, structure (001–010, 094), mix, Change Log × outcomes, Experiments; output **Keep / Stop / Scale / Test / Investigate** |
| MCC summary / all accounts / stalled account? | 169 (each account in its own currency; conversion only with supplied exchange rates) |
| Ad Grants requirements | 170 (declared Grants accounts only) |
| weather / TV / external signals vs performance | 172 (hypotheses, never causality) |
| what happened after <date or change>? | find the Change Log entry, compare pre/post exports over equal mature windows; 131 if the platform change history is needed |
| which changes worked in the last 90 days? | Change Log × observed deltas per entity; correlation declared, not causality |
| log change: <text> | new row in GACC Change Log (date, type, entity, author, expected effect) |
| new experiment: <hypothesis> | new card in GACC Experiments with pre-specified metrics and date; 032 for the design |
| approve / reject finding #N | update the finding's Status |

## Rules

1. **Recommend only.** Inherited in full from `ads`: no account changes, no data uploads, no executable files. Every recipe runs through its own `scripts/check.py` (run → `ai_review` decisions → finalize, see `skills/_resources/RUNTIME.md` in the `ads` bundle): deterministic numbers and severities are never recomputed. With Windsor connected, only its read tools are used (via 174); never `execute_action` or other Windsor write tools, even when a finding recommends a change.
2. **Severity mapping.** `ads` produces Critical / Warning / Info. The CC shows Critical / High / Medium / Low: Critical→Critical; Warning→High if impact is quantified and confidence is High, otherwise Medium; Info→Low. Always report the original severity too.
3. **Every finding** carries: Severity, Business Impact (€ / conversions / qualified leads, or "not quantified"), Confidence, Recommended Action, Reason, Evidence (entity, condition, source, period, parameters, coverage), Recipe.
4. **Notion writes** only on an explicit command (log change, new experiment, approve/reject) or after the user confirms syncing a run's findings. Before creating a finding, search for an open one with the same `(account, entity, condition, period)` key: update it, do not duplicate.
5. **Raw data.** Do not paste whole exports into reasoning or answers; use aggregates and evidence rows. Never personal identifiers (raw CRM): qualified data arrives already aggregated.
6. **Language.** Answer in the language of the request; output templates in that language.

## Output formats

**Today's Attention**

```text
🔴 Critical (n)   — entity · condition · impact · action · recipe
🟠 High (n)
🟡 Monitor (n)
🟢 No action — covered: <checks run>; not covered: <missing sources>
KPI (latest mature window): Spend · Conv · CPA · [Qualified Leads · Qualified CPA] · Value/ROAS
```

**What changed**

```text
Metric · window A vs B · delta · significant? · explained by: <campaign/market with share of the delta> · evidenced cause / hypothesis · recipe
```

**Monthly review**: five lists Keep / Stop / Scale / Test / Investigate; every row with evidence and confidence; Test = proposed experiment with pre-specified metrics.

Every answer ends with **Coverage**: what was checked, what is missing (source/file), what is immature.
