# Canonical skill consolidations

The 2.0.0 library contains 124 canonical recipes. Twenty-one original recipes have been absorbed in total: eight in the initial curation and thirteen in this correction. Absorbed files are removed, not retained as aliases; routing and related references use surviving IDs. `metadata.merged_from` records the full removed names.

## Initial curation

| Canonical | Absorbed | Retained scope |
|---|---|---|
| skill-121-impression-share-loss-analysis | skill-133-impression-share-loss-analysis | Budget/rank visibility diagnosis |
| skill-023-close-variant-query-expansion-monitoring | skill-120-close-variant-match-expansion-monitoring | Observed query expansion and intent |
| skill-061-customer-match-list-health | skill-104-customer-match-list-management | List health and freshness |
| skill-037-ad-disapproval-monitoring | skill-139-ad-disapproval-monitoring | Policy diagnostics and review workflow |
| skill-016-negative-keyword-list-completeness | skill-113-proactive-negative-keyword-list-building | Business-specific negative coverage |
| skill-064-quality-score-distribution-analysis | skill-129-quality-score-monitoring-alert-rules | QS diagnostic exposure, not promised CPC savings |
| skill-054-geographic-performance-analysis | skill-055-underperforming-location-exclusion | Geographic performance and contextual exclusion review |
| skill-029-rsa-asset-performance-analysis | skill-126-rsa-asset-performance-bulk-analysis | Contextual asset/ad analysis with stable keys |

## Evidence-first correction

| Canonical | Absorbed | Retained scope / correction |
|---|---|---|
| skill-001-campaign-type-separation | skill-011-power-pack-assessment | Business-led campaign architecture; no mandatory Power Pack or budget percentages |
| skill-018-duplicate-keyword-detection | skill-019-keyword-cannibalization-analysis | Duplicate inventory and observed query routing; no self-competition or counterfactual CPA claims |
| skill-039-bid-strategy-appropriateness-audit | skill-021-below-first-page-bid | Manual-CPC eligibility and actual platform first-page estimates; no Bid×QS or arbitrary CPC proxy |
| skill-025-rsa-headline-diversity-completeness | skill-027-ad-strength-improvement | Ad Strength as descriptive context; specific copy/pinning findings remain with their owners |
| skill-039-bid-strategy-appropriateness-audit | skill-047-enhanced-cpc-deprecation-migration-check | Date/channel-scoped legacy configuration review; no forced volume-based migration |
| skill-053-location-targeting-method-audit | skill-063-locations-of-interest-exclusion | One location-method owner with explicit business intent/service area |
| skill-076-conversion-action-configuration | skill-077-data-driven-attribution | Current attribution configuration; data-volume recommendations are not DDA eligibility gates |
| skill-070-conversion-tracking-completeness | skill-081-micro-conversion-tracking | Expected business-journey coverage; optional secondary micro-actions are not mandatory goals |
| skill-071-conversion-tracking-accuracy | skill-108-cross-device-conversion-tracking | Directly measured cross-device evidence and reconciliation; no unrelated metric-gap proxy |
| skill-080-offline-conversion-import | skill-109-offline-conversion-freshness | Pipeline freshness from event/upload/acceptance timestamps, not sales-cycle lag |
| skill-115-display-youtube-placement-performance-review | skill-114-account-level-placement-exclusions | Existing exclusion/content governance and measured placement risk |
| skill-115-display-youtube-placement-performance-review | skill-116-mobile-app-placement-exclusion | App-specific evidence within one placement review; no obsolete all-app domain exclusion |
| skill-146-seasonality-bid-adjustment-deployment | skill-150-post-peak-negative-seasonality-adjustment | Exceptional deviation from normal baseline; no routine post-promotion negative compensation |

## Ownership and severity

- The shared three-level severity contract replaces historical four-level reconciliations. Do not preserve a stricter old threshold merely because one of two recipes used it. Critical requires directly evidenced material failure.
- Related skills can use overlapping evidence but report each `(account, entity, condition, period)` once under the most specific owner. Different conditions on one entity remain separate.
- Keep 013/014/015/023/127 as distinct keyword-candidate, negative, pattern, expansion and temporal analyses, but do not sum overlapping query spend or repeat a negative proposal.
- Keep 044/123 distinct as pacing diagnosis versus requested weekday-allocation proposal. Use compatible dated evidence and the same actual budget constraints.
- Keep measurement setup, runtime evidence, reconciled business events and value definitions distinct; missing one evidence source never proves a defect in another.
- Keep page-message, QS-diagnostic, technical-health and policy questions separate, with actual supplied evidence for each. A URL or QS component cannot stand in for a site test.
- Keep 064/065/066/067/068/069 as diagnostic facets with explicit ownership, not multiple automated restructuring recommendations.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | 13 additional clean consolidations and corrected ownership
