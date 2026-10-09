# Google Ads skills library — eppc edition

`eppc-ads-skills@2.0.0` · **136 canonical recipes** (134 audits + intakes: UI export 173, Windsor.ai MCP 174) for Google Ads, each with a deterministic Python check (`scripts/check.py`) and AI judgment limited to declared review items. EUR/EEA defaults and explicit evidence requirements apply throughout. The `ads` front desk selects applicable recipes and produces an English or Italian report. Every package runs in Claude Team's code-execution sandbox or Claude Code. Nothing in this repository applies account changes.

## What this is

A skill specifies applicability, required evidence, analysis, decision gates and reporting. Its `scripts/check.py` runs every decidable step against the supplied exports: joins, units, parameters, maturity and tracking gates, literal matching, thresholds and coverage. The script writes `result.json`. Business intent, relevance, semantics and causality are handed to the AI as closed-outcome `ai_review` items. `finalize` validates the AI decisions deterministically. Proposals are re-checked, and stale evidence or code is refused. See `skills/_resources/RUNTIME.md`. This is not a Google Ads API client and not a certification of account health.

A basic Ads export supports only part of the library. The catalog labels **29 export** (including both intakes), **23 custom_query** and **84 external** recipes. Supplemental reports, Merchant Center inventories, sanitized runtime traces, approved business constraints or experiment evidence must actually be supplied where required. Missing evidence produces partial coverage—not invented defects or a clean pass.

## Layout

```text
ads/SKILL.md              front desk: scope, routing and execution rules
skills/skill-NNN-…/       136 canonical recipes: SKILL.md + scripts/check.py + tests/
skills/_resources/runtime/ adsrun: stdlib runtime shared by every check (vendored into standalone ZIPs)
dist/                     Claude Team ZIPs built by skills/_resources/scripts/build_app_skills.py
skills/CATALOG.md         searchable source-derived descriptions, applicability and metadata
skills/MERGES.md          canonical ownership and absorbed IDs
skills/_resources/        shared contracts, templates, schema and validator
skills/_selftest/         synthetic recipe scenarios, generator and hidden grading oracle
docs/superpowers/         historical curation design and implementation plans
LICENSE                  MIT and retained upstream notice
```

## How to use

1. Create `ads/profile.yaml` from `skills/_resources/CLIENT_PROFILE.md`. Supply approved objectives, relevant constraints and goal/lag context; keep unknown optional facts unknown.
2. Export into `export/` following `skills/_resources/DATA_CONTRACT.md`, including provenance, units, table grains, stable IDs, dates and completeness: raw Google Ads UI downloads through skill-173, or fresh data from a Windsor.ai-connected account through skill-174 (Windsor MCP read tools only). Add only the supplementary evidence needed by the requested checks.
3. Ask a specific question for a narrow check. Generic “audit / check the account” starts a labeled **Triage**, not every preset. Request **“full audit”** to cover every applicable or unresolved non-operational recipe; operational proposals remain opt-in.
4. The front desk searches catalog descriptions/applicability before opening selected recipes. It then runs each recipe's `scripts/check.py`, decides only the `ai_review` items and finalizes. To run one recipe directly: `python3 skills/<recipe>/scripts/check.py run --export export --profile ads/profile.yaml --out work/<recipe>`, then follow `skills/_resources/RUNTIME.md`.

### Claude Team

Build with `python3 skills/_resources/scripts/build_app_skills.py`. Each ZIP has one root folder named like the skill, following Anthropic's upload contract.

- The library ships as **five packages installed together** (split by recipe category; each 0.3–0.6 MB):
  - `dist/ads.zip`: front desk, catalog, `PACKS.md` (recipe → package), intakes 173/174, and the platform, structure, compliance and competitive recipes;
  - `dist/ads-search-keywords.zip`: keywords, waste, Quality Score;
  - `dist/ads-creative-audiences.zip`: creative and remarketing/audiences;
  - `dist/ads-bidding-tracking.zip`: bidding, budgets, tracking;
  - `dist/ads-shopping-seasonal.zip`: Shopping/PMax, targeting, seasonality.

  Every package carries its own `skills/_resources` (contracts and the `adsrun` runtime), so each recipe runs from its own package; the front desk finds recipes in sibling packages through `PACKS.md`.
- `dist/google-ads-command-center.zip` is the command vocabulary on top of `ads`.
- `dist/skills/<recipe>.zip` are standalone single-recipe packages. Each has the runtime vendored under `scripts/adsrun/` and shared contracts under `resources/`.

Organization settings must enable *Cloud code execution and file creation* and *Skills*. Users upload exports (a ZIP is fine) and the profile into the conversation. The scripts need Python 3.10+ standard library only: no network and no package installs.

### Claude Code

Unzip the same ZIPs into `~/.claude/skills/` (personal) or `<project>/.claude/skills/` (project): each ZIP's root folder becomes one skill folder, e.g. `~/.claude/skills/ads/SKILL.md`. Install **all five library packages** (`ads`, `ads-search-keywords`, `ads-creative-audiences`, `ads-bidding-tracking`, `ads-shopping-seasonal`) in the same folder, plus `google-ads-command-center`; standalone recipe ZIPs are optional. For fresh data, connect the Windsor.ai MCP server (`claude mcp add --transport http windsor https://mcp.windsor.ai/`, OAuth sign-in) and keep Windsor write actions **disabled** in Windsor's Team management: skill-174 uses only `get_connectors`, `get_options`, `get_fields` and `get_data`. Each MCP result is copied into a local file by the model before the deterministic `normalize`; keep calls small with `--chunk-days`. Search terms are never pulled through MCP (raw query text would enter the conversation unsanitized): download the UI Search terms report, run skill-173 on it and import it with `normalize --search-terms-from`. The MCP-to-file step has not yet been exercised end-to-end against a live Windsor connection.

A skill's `allowed-tools` only pre-approves tools; it does not restrict them, and `disallowed-tools` cannot be used because claude.ai uploads reject unknown frontmatter keys. To make Windsor writes impossible in Claude Code, add deny rules to `~/.claude/settings.json` (tool names follow `mcp__<server name>__<tool>`; `windsor` is the name used in the command above):

```json
{ "permissions": { "deny": ["mcp__windsor__execute_action", "mcp__windsor__list_actions",
  "mcp__windsor__create_destination_task", "mcp__windsor__create_custom_field"] } }
```

Money parameters use actual spend from an explicit 30-complete-day window—not monthly budget or an arbitrarily long report total. EUR floors are not silently converted to other currencies. Supply approved currency-specific floors or explicit final overrides where needed. CPA and ROAS controls have distinct semantics; null targets are not zero.

### Context and delegation

Installed skills are not a reading list. Presets define search domains; `related` links are not
recursive dependencies. The generated catalog includes complete canonical applicability text,
including exclusions: search matching rows, then confirm selected recipes. Rebuild the catalog
after library edits, not during client audits.

Small checks run inline. Substantial independent slices receive short briefs with exact recipe
paths, scoped evidence, authoritative resource sections and sourced facts. Workers read neither
the front desk nor unrelated recipes, and return a compact **Worker handoff**; one coordinator
renders the final report. Shared rules are reused within an unchanged context, not copied into
every finding. Full audit coverage is never capped merely to save context.

The self-test applies the same scoped reading policy while keeping each case isolated. This
reduces document/output duplication; actual token charges depend on the model, harness and caching.
These repository rules do not change the harness's globally injected skill descriptions.

## Validation and self-test

```bash
python3 skills/_resources/scripts/lint.py
python3 skills/_resources/scripts/lint.py --write-catalog
(cd skills/_resources/scripts && python3 -m unittest test_lint test_build)
python3 -m unittest discover -s skills/_resources/runtime/tests
python3 -m unittest discover -s skills/<recipe>/tests -t skills/<recipe>   # per recipe
python3 skills/_selftest/grade_scripts.py        # scripts vs hidden oracle: PASS / PENDING_AI / FAIL
python3 skills/_selftest/make_fixture.py
```

The validator checks all 134 recipes for schema, evidence markers, version, allowed tools, related/absorbed IDs, routing, supported severity and self-test references. It also checks each `scripts/check.py` statically: SKILL name, CodeDNA header, stdlib-only imports, and no network, clock or randomness. It does not certify advertising logic or live API compatibility. `grade_scripts.py` runs every script against the oracle. A result that needs an AI decision reports PENDING_AI, never PASS.

Ask the agent to execute `skills/_selftest/SKILL.md` after generating fixtures. A **full self-test** runs all **24 cases** (four base cases plus 20 cases in 19 scenario folders). A targeted regression run names affected cases and untested scope. Fresh runners receive only their canonical recipe/evidence paths and shared-section references, never the expected-answer oracle or generator. The coordinator grades compact evidence handoffs against expected/rejected findings and required numerical/configuration observations; an all-skipped output cannot pass. No duplicate polished report is required per worker.

Cases cover brand denominators, theme/count false positives, negative intent and matching direction, impression share, CPA/ROAS direction and portfolio precedence, normalized budget concentration, video rates, valid pin alternatives, RSA serving versus experiments, method-backed inference, advanced consent, Web versus Leads enhancement, DDA volume, offline clocks, historical QS, ordinary post-sale CVR, truthful titles/full product identity, missing feed evidence, partial-day outage exposure, weekly aggregation and PMax causal uncertainty. These are synthetic tests of **23 distinct skills**, not behavioral execution of every recipe or calibration on real accounts.

## Governance

- **Recommend only:** proposals require owner review. Operational recipes describe controls and approval/rollback requirements; they do not execute changes.
- **Evidence first:** every finding identifies its entity, condition, source, period, parameters, uncertainty and coverage. Current settings are not historical outcomes; observed spend is not recoverable savings.
- **Three severities:** `Critical`, `Warning`, `Info`. Critical requires directly evidenced material failure. Optional features, heuristic cutoffs and absent evidence are not automatically defects.
- **Privacy:** no recipe calls an external service or requests raw identifiers. Use aggregate, redacted or pseudonymous evidence in an approved environment. A hosted model still receives the context supplied to it; local files alone do not guarantee data remains on the machine.
- **Consent:** recipe 075 checks technical implementation against supplied policy and traces, including basic/advanced behavior. It does not issue legal-compliance certification.

## Migration and limits

Version 2.0 rewrites the former 137 recipes and consolidates 13 overlaps into 124 survivors. `MERGES.md` maps every absorbed ID, including the eight earlier consolidations. Update callers and saved presets to canonical IDs; removed directories are not compatibility aliases. Historical design documents are not the current execution contract.

Supplemental data schemas and metadata have changed. Rebuild exports against current contracts rather than assuming old fixtures or unrelated GAQL queries satisfy them. Reference queries, if any, need validation against the actual supported API version; no live validation is claimed by `gaql_verified: null`.

No real-account calibration, live API integration, causal uplift validation or export-scale performance guarantee is included. A first approved real-account run should record evidence coverage, false positives and missing source fields before treating heuristic thresholds as operating policy.

## License and origin

MIT, see `LICENSE`. The original skill set derives from TrueClicks' open-source `google-ads` Claude Code plugin (v1.8.0); its copyright notice is retained. The shared contracts, front desk, consolidations and corrections are this library's own work.

## Changelog

- **Five-package distribution (2026-09-28)** — the single `ads.zip` (1.8 MB) is replaced by five packages split by recipe category (0.3–0.6 MB each), each with its own `skills/_resources` and runtime; the packaged front desk gains an "Installed packages" section and `skills/PACKS.md`. Upload contract: each ZIP contains exactly one `SKILL.md` (its root); inside packages each recipe's instructions are `RECIPE.md` (sources keep `SKILL.md`). The builder refuses unassigned categories, unresolved `../_resources` links and any extra `SKILL.md`.

- **Windsor.ai MCP intake (2026-09-28)** — `skill-174-windsor-mcp-intake`: deterministic `get_data` plan for one account, verbatim saved results, strict normalize into the DATA_CONTRACT export (units, resource-name IDs, API enums, exact sums; shares eligible-weighted only for proven Search-only campaigns, censored → withheld), join readiness check. Search terms are never pulled through MCP; they are imported only from a sanitized skill-173 export of the same account, currency and window. Front desk and command center route fresh-data requests to 174; Windsor write tools are never used. Catalog screening and live observations: `docs/windsor-phase0-screening.md`.

- **Colleague intake (2026-09-25)** — `skill-173-export-intake-preflight`: raw Google Ads UI downloads (IT/EN) → Italian checklist → confirmed mapping → normalized export; `skills/_resources/profile_template.yaml`; step-by-step guide in Notion.

- **Executable skills (2026-09-25).**
  - Every recipe ships a deterministic stdlib `scripts/check.py` with tests.
  - The `adsrun` runtime covers evidence and profile loading, units, PARAMETERS resolution, goal-specific tracking evidence, per-account partitioning, results and coverage, closed-outcome AI review, and finalize with verify hooks and stale-evidence refusal.
  - Ten new recipes, 163–172, cover gaps from the Google Ads Scripts index: product performance, PMax search terms/categories, Merchant feed freshness and item status, landing-page performance, out-of-stock exposure, price monitoring, multi-account portfolio, Ad Grants, keyword hypotheses, and external-signal demand.
  - Useful detection logic from the index scripts is reimplemented clean-room inside the owning recipes, recorded in each script's `related:` header. Account mutations stay proposals.
  - Claude Team ZIPs now use a folder root, and there are standalone per-recipe packages.

- **Context optimization (2026-09-07)** — source-derived catalog descriptions/applicability; metadata-first narrow routing; explicit Triage versus Full audit; scoped reads, short briefs and compact evidence handoffs. Canonical recipe checks remain unchanged; the 24-case oracle no longer demands an unused money parameter in the portfolio case.
- **2.0.0 (2026-09-06)** — corrected all 137 original audit outcomes through 124 canonical recipes; explicit evidence schemas and partial coverage, 13 new consolidations, three-level severity, truthful impact/privacy claims, stronger validator and 24 adversarial recipe cases. Breaking data/ID contract migration documented above.
- **1.1.0 (2026-09-03)** — self-contained tool-neutral data contract, no plugin commands or third-party API, attribution retained in LICENSE/README.
- **1.0.0 (2026-09-03)** — first curated release.
