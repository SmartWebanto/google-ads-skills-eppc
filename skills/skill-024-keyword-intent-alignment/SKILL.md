---
name: skill-024-keyword-intent-alignment
description: "Review whether keyword/query intent, approved campaign goals and actual landing-page content support a coherent user task."
allowed-tools: Read, Grep, Glob, Bash
metadata:
  library: eppc-ads-skills@2.0.0
  category: keywords
  kind: analyst
  data_source: external
  related: [skill-013-search-term-mining-keywords, skill-014-search-term-mining-negatives]
  markets: all
  gaql_verified: null
  reviewed: 2026-09-06
  agent: "gpt-6-astra | openai | 2026-09-06 | FixStructureKeywords | evidence-led audit correction"
---
# Skill 024: Keyword Intent and Landing-Page Alignment

## Purpose

Review whether keyword/query intent, approved campaign goals and actual landing-page content support a coherent user task.
Recommendations are review proposals, not account changes or causal forecasts.

## Data Requirements

**Applicability:** Keyword-based Search with supplied business objectives and page evidence; do not infer goals from strategy or content from URLs.

**Required inputs:**
- `export/account` and the base schemas in [DATA_CONTRACT.md](../_resources/DATA_CONTRACT.md).
- `export/campaigns`, `export/keywords`, `export/keyword_metrics`, `export/search_terms`,
  `export/ads`, `export/campaign_metrics`; actual campaign objectives and conversion/value scope.
- `export/external/landing_page_content.csv`: one URL/language/device/capture row from supplied page snapshot;
  url, final_url, language, device, captured_at, source, http_status, title, headings, offer_text,
  main_content_excerpt, cta_text, product_service, supported_audience, evidence_ref.
- Map keyword-specific final URL override or eligible ad final URLs to page evidence; preserve multiple destinations.
- Profile product taxonomy, intended funnel role, excluded_intents and approved service area.
- Client profile: business type, campaign objectives, service area, approved constraints,
  conversion lag and sales cycle, and applicable CPA/ROAS goals; never infer goals from bidding alone.

**Missing inputs:** Without page content skip page fit; without approved objectives skip goal alignment; URL/bidding strategy are not substitutes. Ambiguous query intent remains Unknown.
Skip only dependent subchecks; list missing filenames/columns and retain supported inventory.
Unknown settings are not equivalent to disabled controls; never report an incomplete check as passed.

## Analysis Steps

1. Establish account, snapshot, currency, export window, conversion date basis and reporting coverage.
   Use stable account/campaign/ad-group/entity IDs, not names, for joins; reject metric fan-out.
   Separate current settings from historical performance; exclude incomplete days and immature conversions.

2. Assign intent with evidence: transactional for explicit purchase/action task; navigational for named destination;
   informational for knowledge task; commercial investigation for comparison/evaluation. Retain mixed/Unknown cases.

3. Use brand_terms precedence over competitor_terms and inspect the full query, not generic waste tokens.
   Informational traffic can intentionally support acquisition, education or assisted journeys.

4. Reconcile reported-query clicks/cost with compatible campaign totals and report coverage.
   Privacy-omitted terms and filters limit conclusions; never assume an unreported query has zero traffic.

5. Map each keyword/query to eligible destination candidates using actual URL precedence.
   Where serving destination is unknown, evaluate candidate pages without asserting which page received the click.

6. Review actual content against the requested product/task/audience: Supported, Contradicted or Unknown.
   Cite page excerpt and capture time; a generic-looking URL does not prove mismatch.

7. Compare intent cohorts only within compatible campaign goals using mature metric samples.
   Intent share is descriptive; no maximum informational percentage applies.

8. Investigate zero-conversion exposure above {{spend_floor}} after tracking/maturity/relevance review.
   Zero transactional conversions do not diagnose the page; consider demand, offer, tracking and sales-cycle factors.

9. Propose copy/page/routing review for evidenced contradictions, not automatic negative or funnel reassignment.
   Route exclusions to 014 and keyword additions to 013, preserving owner-approved informational campaigns.

## Thresholds

Resolve [PARAMETERS.md](../_resources/PARAMETERS.md) and profile overrides before screening.
Numerical decision cutoffs below are triage heuristics, not platform requirements or causal proof.
Compare CTR only with {{min_impressions}} impressions and conversion rates with {{min_clicks}} clicks
on each side; CPA/ROAS comparisons require {{min_conversions}} mature conversions on each side.
Zero-conversion screening is an exception to the conversion-count gate, not permission to pause:
require working tracking, a mature comparable window, relevance review and {{spend_floor}}.
Do not divide by zero; absent targets use an applicable profile target, otherwise omit target comparisons.

| Condition | Severity |
|-----------|----------|
| Actual page promise contradicts approved product/task or campaign requirement | Warning |
| Mature zero-conversion exposure at {{spend_floor}} after contextual checks | Warning |
| Informational share, generic URL, ambiguous intent or unavailable page evidence alone | Info |

## Output

Use [OUTPUT_TEMPLATES.md](../_resources/OUTPUT_TEMPLATES.md), Short by default.
For every finding include stable entity IDs, condition key, observed evidence and window,
sample/coverage, resolved thresholds, recommendation, uncertainty and responsible owner.
Separate confirmed observations, analyst interpretation, optional opportunities and skipped checks.
Historical cost is exposure, not guaranteed savings; do not sum overlapping findings as recoverable spend.
Include intent evidence, goal source, candidate destination IDs/URLs and cited content; no causal page diagnosis from performance alone.
