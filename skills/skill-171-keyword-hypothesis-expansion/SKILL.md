---
name: skill-171-keyword-hypothesis-expansion
description: "Draft testable keyword hypotheses from first-party taxonomy, saved page text and converting queries, verified against duplicates, negatives and brand policy."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: export
  markets: all
  related: [skill-013-search-term-mining-keywords, skill-014-search-term-mining-negatives, skill-017-negative-keyword-conflict-detection, skill-018-duplicate-keyword-detection, skill-024-keyword-intent-alignment]
  merged_from: []
  gaql_verified: null
  reviewed: 2026-09-25
  agent: "claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes5 | new recipe from index #15; #109 refused"
---
# Skill 171: Keyword Hypothesis Expansion

## Purpose

Draft new keyword hypotheses for controlled testing, grounded only in supplied first-party evidence: the approved product/service taxonomy, locally saved landing-page text and converting queries or keywords. Hypotheses are proposals, not account changes. They never promise incremental volume, reach or conversions.

## Data Requirements

**Applicability:** Search campaigns with a keyword inventory and a declared `brand_policy` in `profile.campaign_objectives`. Shopping, PMax and keywordless campaigns are not applicable. Reported queries that could become keywords belong to skill-013. This recipe covers unobserved variants only.

**Required inputs:**
- Base tables per [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md): `export/account`, `export/campaigns` (id, channel_type, status), `export/ad_groups` (id, campaign_id, status) and `export/keywords` (id, campaign_id, ad_group_id, text, match_type, status). Include every non-removed keyword so duplicates are provable.
- Effective negatives: `export/negative_keywords` (text, match_type, level, campaign_id, ad_group_id) and `export/shared_negative_lists` with applied campaign IDs.
- Seeds: `export/search_terms` (search_term, campaign_id, ad_group_id, clicks, conversions) for the report window. `export/keyword_metrics` (keyword_id, campaign_id, ad_group_id, conversions) is optional and joins to keywords by ID.
- Optional page evidence: `export/external/landing_page_content.csv`, one row per captured URL: url, captured_at, http_status, title, main_content_excerpt, evidence_ref. Save it locally from a page snapshot. Pages are linked to a campaign only when the URL equals a keyword or ad `final_url`.
- Profile: `product_service_taxonomy` (or campaign `themes`), `brand_terms`, `competitor_terms`, `campaign_objectives[id].brand_policy` (brand_only, nonbrand_only, competitor_only, mixed), and `excluded_intent_terms` (literal phrases, account-wide or per campaign). `excluded_intents` descriptions guide the review only.

**Missing inputs:** Without keywords, ad groups or negatives, the hypothesis review is skipped. Duplicate and negative screens cannot be proven. Without a campaign brand_policy, or brand_terms for brand_only/nonbrand_only campaigns, that campaign is partial. Missing taxonomy skips theme coverage. Missing page text skips page seeds. Missing search terms leave only taxonomy and page seeds. Never fetch pages, autocomplete or third-party suggestion services: sending account data to them violates DATA_CONTRACT rule 8.

## Analysis Steps

1. **Scope.** List active Search campaigns and their active ad groups. Record brand_policy, brand/competitor/excluded-term availability and maturity. Missing policy makes the campaign partial, not permissive.
2. **Query seeds.** Converting reported queries (conversions > 0) per campaign, ordered by conversions then text. The top 25 per campaign are passed to review. When maturity is not confirmed, seeds are descriptive only. Nothing is ranked by CPA.
3. **Keyword seeds.** Converting keywords from keyword_metrics, joined by keyword ID to the active inventory. This covers the "top converting keywords" input of index #15.
4. **Page seeds.** Captured pages with HTTP 200 and an evidence_ref, linked to a campaign by exact final URL. A failed capture is not evidence.
5. **Theme coverage.** For each taxonomy theme, count active Search keywords whose tokens contain every theme token. A zero count in a manifest-complete inventory goes to review: close variants and synonyms may already cover the theme.
6. **Hypothesis review.** Per campaign, the AI proposes candidates {text, match_type, ad_group_id, source: seed_query|seed_keyword|taxonomy|page, evidence_ref}. Deterministic verification rejects a candidate that:
   - repeats normalized text plus match type in the same ad group, or in the proposal itself;
   - equals a reported query in the campaign (owned by skill-013);
   - is blocked by an effective negative, or is undecidable under literal negative rules (adsrun.negatives);
   - violates brand_policy: brand terms in nonbrand_only, no brand term in brand_only, or competitor terms outside competitor_only;
   - contains an explicit excluded-intent term;
   - cites a source reference absent from the reviewed evidence, or carries volume/uplift forecasts.

## Thresholds

Resolve [PARAMETERS.md](../_resources/PARAMETERS.md) for the report header. This recipe prescribes no performance action, so no spend or sample threshold triggers a severity. Hypotheses are triage for testing, not platform requirements or forecasts. Conversions in immature windows are seeds, not efficiency evidence. Candidate tests follow `{{min_clicks}}` and `{{min_conversions}}` gates before anyone reads their results.

| Condition | Severity |
|---|---|
| Verified keyword hypotheses cite first-party evidence and pass the duplicate, negative, brand-policy and excluded-term screens | Info |
| Taxonomy theme without literal keyword coverage in a complete inventory, confirmed as an untested gap | Info |
| Missing taxonomy, page, seed, brand-policy or negative evidence (coverage only) | Info |

No Warning or Critical applies. A hypothesis list is not a defect, and blocked candidates are rejected, not reported as account failures.

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
- Hypothesis table: campaign_id, ad_group_id, candidate text, match type, source and evidence_ref, and the verification status of every screen.
- Theme-coverage table: theme, keyword count, inventory completeness, review outcome.
- Seed tables with conversions, clicks, window and maturity.

Label every candidate as a test hypothesis: no guaranteed incremental volume and no forecast. Route reported-query additions to skill-013, exclusions to skill-014, blocking conflicts to skill-017, duplicates across ad groups to skill-018 and page/intent fit to skill-024. No keywords are added, uploaded or sent to any external suggestion service.
