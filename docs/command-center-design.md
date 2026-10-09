# Google Ads Command Center — Design Doc

Version 1.0 — 2026-09-15 · Architecture draft · No database infrastructure
Mirrors the Notion draft: <https://app.notion.com/p/3dc3b613e22e813386b4f46eac75abb0>

## North Star

A dashboard answers *"What happened in Google Ads?"*. The Command Center answers:

> **What changed, why did it change, does it matter, and what should I do next?**

One question every day: **What needs my attention?**

---

## 1. Core principle — two engines

### Monitoring Engine (zero AI tokens)

A Python script that reads dated CSV exports and compares them with rolling baselines. SQL/rules/thresholds, no AI calls.

Example: `IF conversions today < 60% of 14-day average AND spend > €100 → trigger`

### AI Analysis Engine (triggers only)

The AI steps in only when: an anomaly is detected, an opportunity is identified, a cause is needed, prioritization is needed, or a deep dive is requested.

Not `100 checks → 100 prompts` but `100 checks → 6 triggers → 1 AI analysis`.

AI diagnosis uses the **124 canonical recipes** of the `eppc-ads-skills@2.0.0` library (this repo): explicit applicability, evidence gates, three severities, recommend-only. The front desk (`ads/SKILL.md`) selects the relevant recipes from the catalog — never all of them.

---

## 2. Architecture (no database)

```text
Google Ads → Windsor.ai connector (REST, api_key, _renderer=csv)
        ↓
scheduled curl (launchd) — no manual export, no developer token
        ↓
export/YYYY-MM-DD/  ← dated CSVs = the "time series"
        ↓
scripts/daily_pulse.py  ← zero-token rules, updates baselines.json
        ↓
state/triggers.json  ← only what crossed the thresholds
        ↓
Claude Code + library recipes  ← diagnosis on triggers only
        ↓
findings/*.md  +  Notion sync  ← human layer
```

**Ingestion — Windsor.ai:** endpoint `connectors.windsor.ai/google_ads` with `fields=` per report (campaign, keyword, search terms, ad, conversion action) mapped to DATA_CONTRACT. Free tier: 1 account; multi-account from ~$19/month. CRM/qualified data does NOT go through Windsor: it stays local as external evidence (V3). Fallback: manual UI export or Google Ads Scripts.

### Folder structure

```text
google-ads-command-center/
├── ads/profile.yaml          # approved objectives, constraints, goal/lag context
├── export/
│   ├── 2026-09-15/           # CSV exports per DATA_CONTRACT.md
│   └── 2026-09-08/           # dated folders = history, no tables
├── state/
│   ├── baselines.json        # rolling 14/28-day averages
│   ├── triggers.json         # Daily Pulse output
│   └── tracking-score.json   # Tracking Confidence Score
├── scripts/daily_pulse.py    # the zero-token checks
├── findings/                 # diagnosis output (mirrored to Notion)
├── experiments/              # one file per experiment
├── CHANGELOG.md              # dated important changes
└── HOMEPAGE.md               # regenerated on every run
```

**Why no database:** at a scale of 1–5 accounts, dated CSVs are enough; DuckDB can query them in place with SQL without creating any DB file. Notion is NOT the analytical database: it receives only the output (a few rich records), never the dataset — exactly the token-optimization principle.

---

## 3. Cadences

Full inventory of the ~105 checks (engine, cadence, data, recipe, phase): [command-center-checks.md](command-center-checks.md).

**Decision: the main cadence is weekly.** The daily run is deterministic only; the monthly run is not a separate run but the 4th, extended weekly. A single scheduled AI job.

```
Daily    → deterministic pulse only, zero AI
Weekly   → the core: search terms, keywords, budget, tracking, creative (AI on triggers)
Monthly  → 1st Monday of the month: weekly + strategic section (structure, mix, 28v28, Change Log × outcomes)
```

Reason: search terms, pacing and broken tracking cost money within 7 days — after a month the waste is already spent. Structure, mix and allocation rarely change: looking at them every week is noise.

### Daily Pulse (10–15 checks, zero AI)

Stopped conversions · broken tracking · conversion drop · spend/CPA/CPC spike · CVR drop · budget exhaustion · spend without results · important disapprovals · qualified-lead anomalies.

Output: **Today's Attention** — 🔴 Critical · 🟠 High · 🟡 Monitor · 🟢 No action. The AI is called only if `triggers.json` is not empty.

Thresholds and baselines taken from the recipes: 037 (disapproval), 042 (budget limited), 049 (budget alert), 079 (broken URLs), 110 (tracking breakage, lag-aware), 124 (anomaly baseline).

### Weekly Audit — Monday morning, on the previous 7 complete days

Mature windows: exclude the last 3–7 days from conversion metrics according to the lag declared in `profile.yaml`.

- Performance WoW / 7v7 → *What changed?* with campaign/market decomposition
- Search Terms Intelligence: recipes 013–017, 023, 127
- Keyword Intelligence: 012, 018, 020, 022, 064–069, 121
- Budget: 042–045, 050, 123
- Tracking Health: 070–080, 110–112
- Creative and LP: 025–038, 069, 078, 079

### Monthly section — 1st Monday of the month, added to the weekly

28v28 · markets · campaign mix · budget allocation · qualified-lead trend · search demand · account structure (recipes 001–010, 094) · Change Log × outcomes · experiments. Output: **Keep / Stop / Scale / Test / Investigate**.

Steady-state AI cost: ~4 weekly runs/month (1 extended) + only the daily triggers.

### Event-driven & On-demand

Automatic triggers from the Daily Pulse; direct questions to the AI Analyst in chat (front-desk Triage: question → catalog → 1–3 recipes).

---

## 4. Lead Quality Center (differentiator, phase V3)

Pipeline: Click → Lead → Qualified Lead → Opportunity → Customer → Revenue.

Metrics: Qualified CPA, Qualification Rate, Opportunity CPA, CAC. Useful for cases like:

| | CPA | Qualified CPA | Business verdict |
|---|---|---|---|
| Campaign A | €50 | €400 | reduce |
| Campaign B | €90 | €130 | scale |

**Known gap:** no recipe computes Qualified CPA — it is new code. The library does, however, validate the plumbing: 080 (offline import freshness), 052/107 (value semantics), 073 (Enhanced Conversions for Leads). CRM data is "external evidence" in the data contract: it comes in as sanitized CSVs, never raw identifiers.

---

## 5. Notion — human layer (not an analytical database)

Three databases + homepage. The AI reads/writes via MCP; the engine stays on local files.

### Findings DB (approval queue)

Name (title) · Severity: Critical/High/Medium/Low · Status: Open→In Review→Approved→Applied→Rejected · Category · Entity · Impact € (number) · Confidence: High/Medium/Low · Recommended Action · Reason · Evidence · Recipe (e.g. skill-014) · Source: Daily/Weekly/Monthly/On-demand · Date · Account

### Change Log DB

Change (title) · Date · Type: Budget/Keywords/Ads/Landing Page/Bidding/Structure/Tracking · Entity · Author · Expected effect · Observed effect · Relation → Findings

Answers: *What happened after this change?* · *Which changes in the last 90 days actually improved performance?*

### Experiments DB

Name (title) · Hypothesis · Status: Planned/Running/Concluded · Start/End date · Metrics · Results · Verdict: Keep/Revert/Continue testing/Insufficient data · Relation → Change Log

### Homepage — "What needs my attention today?"

Filtered views: Critical Issues · Opportunities · Active experiments · Monitor. KPIs: Spend, Conversions, CPA, Qualified Leads, Qualified CPA, Revenue.

---

## 5b. `google-ads-command-center` skill — command vocabulary

Second skill in the Claude app (next to `ads`). The CC front desk: it interprets the command, reads local/Notion state, and delegates diagnosis to the recipes. Spoken name: **"Ads CC"**.

Commands route by meaning; equivalent requests in any language map to the same row.

### Attention and pulse

| Command | Does | Source / recipe |
|---|---|---|
| "what needs my attention today?" | Today's Attention sorted by severity × impact | Notion Findings + `triggers.json` |
| "pulse" | Summarizes the last run; diagnosis on triggers only | `triggers.json` → 110, 124, 042, 037 |
| "is tracking ok?" | Tracking Confidence Score + failed checks | `tracking-score.json` → 110, 071, 076 |

### Performance

| Command | Does | Recipe |
|---|---|---|
| "what changed this week?" | Significant 7v7 deltas with campaign/market decomposition | 124 + delta script |
| "what changed in Germany / in campaign X?" | Same decomposition, narrower scope | 124, 136 |
| "28-day trend" | 28v28 for the 9 core metrics (12 with CRM) | 124, 137 |
| "why did CPA go up?" / "why did conversions drop?" | Cause triage: tracking → budget → auction → creative → LP | 110, 042, 121, 029, 069 |

### Search terms

| Command | Does | Recipe |
|---|---|---|
| "search terms to add as negatives" | Negative candidates with verified scope and conflicts | 014, 016, 017 |
| "queries that deserve a keyword" | Converting queries not covered by keywords | 013 |
| "brand leakage" | Brand queries in generic campaigns and vice versa | 002 |
| "search term waste" | Mature 0-conv queries above the spend threshold (hypothesis, not savings) | 014, 015 |
| "new queries / trends" | New queries and volume changes | 127 |
| "competitor queries" | Queries with competitor brands and their outcome | tagging + 014 |

### Keywords

| Command | Does | Recipe |
|---|---|---|
| "keywords without conversions" | Mature, 0 conv, lag respected | 020, 122 |
| "keywords limited by rank / by budget" | Profitable ones with lost IS rank/budget | 121, 039, 042 |
| "duplicate keywords" | Duplicates and multi-triggers, legitimate copies preserved | 018 |
| "quality score" | Distribution, components, trend | 064–068 |
| "match type" | Distribution and alignment with Smart Bidding | 012, 022 |

### Budget

| Command | Does | Recipe |
|---|---|---|
| "pacing" | Month-to-date vs plan, over/under forecast | 044 |
| "budget-limited campaigns" | Lost IS budget with economic headroom | 042 |
| "who deserves more budget?" | Comparable cohorts, marginal response | 045 |
| "where do I move €1,000?" | Constrained reallocation scenario | 045, 042 |
| "brand vs generic budget" | Allocation by campaign class | 002 + 045 |

### Tracking and conversions

| Command | Does | Recipe |
|---|---|---|
| "conversions stopped?" | Actions with no events beyond the lag window | 110 |
| "GA4 vs Ads" | Reconciliation, attribution ≠ breakage | 106, 071 |
| "offline import" | Upload freshness and outcomes | 080 |
| "enhanced conversions" | Web vs Leads, status per action | 072, 073 |
| "conversion actions" | Counting, primary/secondary, windows, attribution | 076 |

### Creative and landing pages

| Command | Does | Recipe |
|---|---|---|
| "RSA performance" | Assets by stable IDs, contextual labels | 029 |
| "disapproved ads" | Policy with parent eligibility | 037 |
| "weak assets" | Headline/description diversity, pinning | 025, 026, 028 |
| "worst LPs" | CVR/CPA by final URL | aggregation + 069 |
| "broken LPs" | Availability with timestamps | 079, 125 |
| "ad vs LP" | Promise ↔ page consistency | 034, 024 |
| "page speed" | Field/lab data, not a QS proxy | 078 |

### Structure, PMax, Shopping

| Command | Does | Recipe |
|---|---|---|
| "campaign overlap" | Overlapping campaigns/ad groups/keywords | 001, 004, 018 |
| "PMax vs Search" | Descriptive screening of the interaction | 094 |
| "PMax channels" | Outcome per channel/asset group at the available granularity | 128 |
| "match type / negative conflicts" | Literal blocks and conflicts | 017 |
| "feed titles / attributes" | Merchant Center titles and completeness | 082, 083 |
| "asset group" | PMax structure and product selection | 089 |

### Lead quality (V3)

| Command | Does | Source |
|---|---|---|
| "qualified CPA by campaign" | CPA vs Qualified CPA ranking | local CRM join |
| "campaigns with poor leads" | Qualification rate below baseline | local CRM join |
| "CAC by market" | Customer/Revenue by market | local CRM join |

### Strategy and operations

| Command | Does | Source |
|---|---|---|
| "monthly review" / "what do I do next month?" | Keep / Stop / Scale / Test / Investigate | selective full audit + Change Log + Experiments |
| "what happened after <date / change>?" | Pre/post export comparison around the entry | Notion Change Log + dated exports |
| "which changes worked in the last 90 days?" | Change Log × observed deltas | Notion Change Log |
| "log change: <text>" | New Change Log row | Notion |
| "new experiment: <hypothesis>" | Experiments card with pre-specified metrics | Notion + 032 |
| "approve / reject finding #N" | Changes Status | Notion Findings |

Routing rule: each command opens at most 1–3 recipes; "monthly review" is the only one that may open a full audit. Answers use the §6 contract.

## 6. Prioritization contract (every finding)

Severity · Business Impact (€/conversions/qualified leads) · Confidence · Recommended Action · Reason · Evidence (entity, condition, source, period, parameters, coverage).

This is the output contract the recipes already enforce. Guardrails inherited from the library:

- Observed spend ≠ recoverable savings.
- Optional features ≠ defects.
- Missing evidence = partial coverage, never an invented defect.
- Ad Strength is descriptive: a "Poor" RSA with Qualified CPA −32% → No action.

---

## 7. Token optimization

> Don't send data to the LLM unless the LLM has something useful to do with it.

```text
100+ checks (Python, zero tokens)
 → 14 triggers
 → 6 discarded (duplicates/irrelevant, deduped in the script)
 → 8 analyzed (only relevant recipes + only relevant CSVs)
 → 3 Recommended Actions in Notion
```

---

## 8. Roadmap

### V1 — Monitoring (read-only)

Folders + `daily_pulse.py` + baseline · Daily Pulse on manual exports · findings in Markdown · core KPIs.

### V2 — Intelligence

AI diagnosis with the recipes · Weekly audit · prioritization · Notion sync (3 DBs + homepage) · Change Log · Experiment Center.

### V3 — Business Data

CRM/qualified leads as external evidence · end-to-end Qualified CPA · offline conversions · full Tracking Confidence Score.

### V4 — Action Layer

**AI recommends → Human reviews → Human approves → Change executed.** Never AI → direct change. (This matches the library's governance: recommend-only, operational proposals with approval and rollback.)

---

## 9. Honest limits

- No calibration on real accounts: on the first run, record false positives and missing fields before trusting the thresholds.
- File-based scales well up to ~5 accounts; beyond that, reassess (persistent DuckDB).
- Multi-database SQL queries on Notion need the full version of the MCP; single-DB queries work.
- Scheduling still needs a trigger (launchd/cron or a manual launch).
- The recipes do not certify legal compliance or account health: they produce proposals with evidence.
