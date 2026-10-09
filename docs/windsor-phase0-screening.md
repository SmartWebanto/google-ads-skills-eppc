# Windsor.ai → DATA_CONTRACT — Phase 0 screening

Date: 2026-09-28. **Status: preliminary static screening + one live batch.** Nothing here means "supported":
a column is supported only after a REST query with that exact field combination returns the expected grain, units
and values, checked per account. No library code was changed.

## Method

- Needs inventory = union of (a) runtime probe: every recipe run on the selftest fixture and an empty export with
  `Context.check` intercepted; (b) AST extraction of every `ctx.check(..., needs)` literal. Each alone is incomplete:
  (b) left 132 runtime-built `needs` arguments unresolved in 48 recipes, (a) misses branches the fixture does not reach
  (e.g. skill-170 declares needs only when `profile.ad_grants` is true — captured by (b)).
  Residual risk: a branch that is both runtime-built and unreached is still missing.
- Windsor catalog = `GET connectors.windsor.ai/google_ads/fields` (2,746 fields); matching by `upstream_api_request_name`
  (the Google Ads API field) where possible, by field id otherwise.
- Scope: 135 recipe folders (all have `scripts/check.py`); every recipe has at least one declared need.

## Counts (units stated)

- Base tables: **18**; needed **table:column pairs: 128**; unique column names: 73.
- Pair status: match 82, ambiguous 21, adapter 11, tbd 6, missing 5, request 3 (sum 128).
  - match = one Windsor field with one upstream API field; ambiguous = one Windsor id spans several API resources
    (`campaign_id`, `criterion_id`, `keyword_text`…), resolved by the query's other fields — must be verified live;
    adapter/request = computed by the adapter or taken from request metadata; tbd = needs live field exploration; missing = no catalog field.
- Custom tables needed: **129**; external tables: 148 (outside the google_ads connector).

## Live batch 1 (one EUR account, last_7d, read-only GET)

| table.column | observation |
|---|---|
| account.customer_id | verified: 'XXX-XXX-XXXX' (dashed) |
| account.currency_code | verified |
| account.time_zone | verified (IANA name) |
| account.auto_tagging | verified: string 'True' → adapter casts |
| campaigns.id | verified |
| campaigns.name | verified |
| campaigns.status | verified: ENABLED/PAUSED/REMOVED |
| campaigns.channel_type | verified: API enum |
| campaigns.bidding_strategy_type | verified: API enum |
| campaigns.budget_id | verified: resource name customers/…/campaignBudgets/ID → adapter extracts ID |
| campaigns.daily_budget | verified: currency units (float) |
| campaigns.search_partners | verified: bool |
| campaigns.display_network | verified: bool |
| campaigns.geo_target_method | verified: API enum |
| campaigns.labels | returned empty on 20/20 — known-empty vs unsupported NOT distinguishable yet |
| campaigns.end_date | returned empty on 20/20 — unverified |
| campaign_metrics.campaign_id | verified |
| campaign_metrics.impressions | verified: float → adapter casts int |
| campaign_metrics.clicks | verified: float → int |
| campaign_metrics.cost | verified: currency units (cost==spend; cost_micros=cost×1e6) |
| campaign_metrics.conversions | verified |
| campaign_metrics.conversion_value | verified (all 0 in window) |
| campaign_metrics.search_impression_share | verified: fraction 0–1 |
| campaign_metrics.search_budget_lost_is | verified: fraction |
| campaign_metrics.search_rank_lost_is | verified: fraction |

Observations from this one account and window (not yet shown to hold for every account, query or grain): numeric metrics
arrive as floats (adapter casts counts to int); `cost` = currency units (→ `money_unit: currency`); shares are fractions
(→ `rates_format: fraction`); the attribute-only campaign query returned all 20 campaigns including REMOVED; time zone
is per account (date windows must use it).

**Join check (same data, local):** both campaign IDs in `campaign_metrics` exist in the campaign inventory (same string
type), both ENABLED. The inventory has 3 ENABLED campaigns, so exactly one enabled campaign has no metric rows.

**Unverified:** `campaign_metrics` returned 14 rows (2 campaigns × 7 days) while 20 campaigns exist. Whether Windsor
omits zero-activity rows, or the query/grain explains the gap, is NOT established. skill-174 therefore does not
materialize zero rows and its manifest says so; resolve with a known-zero campaign-day before changing that.

**Lost-IS aggregation (catalog):** Windsor's `aggregate_formula` for `search_budget_lost_impression_share` and
`search_rank_lost_impression_share` is `sum(x)/length(x)` — a plain average of rows, which violates DATA_CONTRACT
invariant 1 over multi-day windows. skill-174 pulls campaign metrics daily and aggregates shares itself
(eligible-weighted; Google's censored 0.0999 / 0.9001 → `withheld`, per the API metrics reference).

## Design principle: generic core, per-client configuration

The adapter is account-agnostic: one versioned field map (Windsor field → DATA_CONTRACT column) and one normalizer,
identical for every client. Nothing client-specific lives in code. Per-client choices are adapter arguments, not
`profile.yaml` fields: the account, the date window, the pulls to fetch and the chunk size are `skill-174 plan`
arguments; the conversion lag is a `normalize` argument. `profile.yaml` keeps its existing role (objectives,
targets, lag context, currency floors). Client-specific findings from live checks update the shared map only when
they hold generally.

## Missing in catalog (5 pairs)

`conversion_actions.include_in_conversions`, `.attribution_model`, `.value_settings`; `search_terms.matched_keyword_id`
(only matched keyword text + match type exist: recipes 020, 022, 023); `keywords.final_url`.

## Base column map

| table | column | Windsor field | upstream API field | catalog status |
|---|---|---|---|---|
| account | auto_tagging | auto_tagging_enabled | customer.auto_tagging_enabled | match |
| account | currency_code | account_currency_code | customer.currency_code | match |
| account | customer_id | account_id | account_id | match |
| account | date_range_end | @request |  | request |
| account | date_range_start | @request |  | request |
| account | money_unit | @adapter |  | adapter |
| account | rates_format | @adapter |  | adapter |
| account | snapshot_date | @request |  | request |
| account | time_zone | account_time_zone | customer.time_zone | match |
| ad_groups | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| ad_groups | id | ad_group_id | ad_group.id | match |
| ad_groups | name | ad_group_name | ad_group.name | match |
| ad_groups | status | ad_group_status | ad_group.status | match |
| ad_metrics | ad_group_id | ad_group_id | ad_group.id | match |
| ad_metrics | ad_id | ad_group_ad_ad_id | ad_group_ad.ad.id | match |
| ad_metrics | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| ad_metrics | clicks | clicks | metrics.clicks | match |
| ad_metrics | conversions | conversions | metrics.conversions | match |
| ad_metrics | cost | cost | metrics.cost_micros | match |
| ad_metrics | impressions | impressions | metrics.impressions | match |
| ads | ad_group_id | ad_group_id | ad_group.id | match |
| ads | ad_strength | ad_group_ad_ad_strength | ad_group_ad.ad_strength | match |
| ads | approval_status | ad_group_ad_policy_summary_approval_status | ad_group_ad.policy_summary.approval_status | match |
| ads | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| ads | descriptions | ad_group_ad_ad_responsive_search_ad_descriptions | ad_group_ad.ad.responsive_search_ad.descriptions | match |
| ads | final_url | ad_group_ad_ad_final_urls | ad_group_ad.ad.final_urls | match |
| ads | headlines | ad_group_ad_ad_responsive_search_ad_headlines | ad_group_ad.ad.responsive_search_ad.headlines | match |
| ads | id | ad_group_ad_ad_id | ad_group_ad.ad.id | match |
| ads | policy_topics | ad_group_ad_policy_summary_policy_topic_entries | ad_group_ad.policy_summary.policy_topic_entries | match |
| ads | status | ad_group_ad_status | ad_group_ad.status | match |
| ads | type | ad_group_ad_ad_type | ad_group_ad.ad.type | match |
| assets | ad_group_id | ad_group_id | ad_group.id | match |
| assets | asset_id | asset_id | asset.id | match |
| assets | association_level | @adapter |  | adapter |
| assets | association_status | @tbd |  | tbd |
| assets | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| assets | level | @adapter |  | adapter |
| assets | status | @tbd |  | tbd |
| assets | type | asset_type | asset.type | match |
| audiences | ad_group_id | ad_group_id | ad_group.id | match |
| audiences | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| audiences | id | @tbd |  | tbd |
| audiences | list_id | @tbd |  | tbd |
| audiences | mode | @tbd |  | tbd |
| audiences | type | @tbd |  | tbd |
| bid_adjustments | ad_group_id | ad_group_id | ad_group.id | match |
| bid_adjustments | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| bid_adjustments | criterion_id | criterion_id | ad_group_criterion.criterion_id,campaign_criterion.criterion_id | ambiguous |
| bid_adjustments | dimension | @adapter |  | adapter |
| bid_adjustments | modifier | bid_modifier | ad_group_criterion.bid_modifier,campaign_criterion.bid_modifier | ambiguous |
| bid_adjustments | segment_value | @adapter |  | adapter |
| bidding_strategies | campaign_ids | @adapter |  | adapter |
| bidding_strategies | id | accessible_bidding_strategy_id | accessible_bidding_strategy.id | match |
| bidding_strategies | type | accessible_bidding_strategy_type | accessible_bidding_strategy.type | match |
| budgets | amount | amount_micros | campaign_budget.amount_micros | match |
| budgets | budget_id | campaign_budget_id | campaign_budget.id | match |
| budgets | campaign_ids | @adapter |  | adapter |
| budgets | shared | explicitly_shared | campaign_budget.explicitly_shared | match |
| campaign_metrics | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| campaign_metrics | clicks | clicks | metrics.clicks | match |
| campaign_metrics | conversion_value | conversions_value | metrics.conversions_value | match |
| campaign_metrics | conversions | conversions | metrics.conversions | match |
| campaign_metrics | cost | cost | metrics.cost_micros | match |
| campaign_metrics | impressions | impressions | metrics.impressions | match |
| campaign_metrics | search_budget_lost_is | search_budget_lost_impression_share | metrics.search_budget_lost_impression_share | match |
| campaign_metrics | search_impression_share | search_impression_share | metrics.search_impression_share | match |
| campaign_metrics | search_rank_lost_is | search_rank_lost_impression_share | metrics.search_rank_lost_impression_share | match |
| campaigns | ad_schedule | ad_schedule_day_of_week | campaign_criterion.ad_schedule.day_of_week | match |
| campaigns | bidding_strategy_type | bidding_strategy_type | campaign.bidding_strategy_type,bidding_strategy.type | ambiguous |
| campaigns | budget_id | budget_id | campaign.campaign_budget | match |
| campaigns | channel_type | advertising_channel_type | campaign.advertising_channel_type | match |
| campaigns | daily_budget | budget_amount | campaign.campaign_budget.amount_micros | match |
| campaigns | display_network | network_settings_target_content_network | campaign.network_settings.target_content_network | match |
| campaigns | end_date | end_date | campaign.end_date_time | match |
| campaigns | geo_target_method | geo_target_type_setting_positive_geo_target_type | campaign.geo_target_type_setting.positive_geo_target_type | match |
| campaigns | geo_targets | campaign_criterion_location_geo_target_constant | campaign_criterion.location.geo_target_constant | match |
| campaigns | id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| campaigns | labels | campaign_labels | campaign.labels | match |
| campaigns | languages | campaign_criterion_language_language_constant | campaign_criterion.language.language_constant | match |
| campaigns | name | campaign_name | campaign.name | match |
| campaigns | search_partners | network_settings_target_partner_search_network | campaign.network_settings.target_partner_search_network | match |
| campaigns | status | campaign_status | campaign.status | match |
| conversion_actions | attribution_model | — |  | missing |
| conversion_actions | category | conversion_action_category | segments.conversion_action_category,conversion_action.category | ambiguous |
| conversion_actions | click_window_days | conversion_action_click_through_lookback_window_days | conversion_action.click_through_lookback_window_days | match |
| conversion_actions | counting | conversion_action_counting_type | conversion_action.counting_type | match |
| conversion_actions | id | conversion_action_id | segments.conversion_action | match |
| conversion_actions | include_in_conversions | — |  | missing |
| conversion_actions | name | conversion_action_name | segments.conversion_action_name,conversion_action.name | ambiguous |
| conversion_actions | primary_for_goal | conversion_action_primary_for_goal | conversion_action.primary_for_goal | match |
| conversion_actions | status | conversion_action_status | conversion_action.status | match |
| conversion_actions | type | conversion_action_type | conversion_action.type | match |
| conversion_actions | value_settings | — |  | missing |
| keyword_metrics | ad_group_id | ad_group_id | ad_group.id | match |
| keyword_metrics | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| keyword_metrics | clicks | clicks | metrics.clicks | match |
| keyword_metrics | conversion_value | conversions_value | metrics.conversions_value | match |
| keyword_metrics | conversions | conversions | metrics.conversions | match |
| keyword_metrics | cost | cost | metrics.cost_micros | match |
| keyword_metrics | impressions | impressions | metrics.impressions | match |
| keyword_metrics | keyword_id | criterion_id | ad_group_criterion.criterion_id,campaign_criterion.criterion_id | ambiguous |
| keyword_metrics | quality_score | quality_info_quality_score | ad_group_criterion.quality_info.quality_score | match |
| keywords | ad_group_id | ad_group_id | ad_group.id | match |
| keywords | ad_relevance | quality_info_creative_quality_score | ad_group_criterion.quality_info.creative_quality_score | match |
| keywords | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| keywords | expected_ctr | quality_info_search_predicted_ctr | ad_group_criterion.quality_info.search_predicted_ctr | match |
| keywords | final_url | — |  | missing |
| keywords | id | criterion_id | ad_group_criterion.criterion_id,campaign_criterion.criterion_id | ambiguous |
| keywords | landing_page_experience | quality_info_post_click_quality_score | ad_group_criterion.quality_info.post_click_quality_score | match |
| keywords | match_type | ad_group_criterion_keyword_match_type | ad_group_criterion.keyword.match_type | match |
| keywords | quality_score | quality_info_quality_score | ad_group_criterion.quality_info.quality_score | match |
| keywords | status | keyword_status | ad_group_criterion.status | match |
| keywords | text | ad_group_criterion_keyword_text | ad_group_criterion.keyword.text | match |
| negative_keywords | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| negative_keywords | level | @adapter |  | adapter |
| negative_keywords | match_type | keyword_match_type | ad_group_criterion.keyword.match_type,campaign_criterion.keyword.match_type,campaign.keyword_match_type | ambiguous |
| negative_keywords | text | keyword_text | ad_group_criterion.keyword.text,campaign_criterion.keyword.text | ambiguous |
| search_terms | ad_group_id | search_term_view_ad_group_id | search_term_view.ad_group | match |
| search_terms | campaign_id | campaign_id | campaign.id,ad_group.campaign | ambiguous |
| search_terms | clicks | clicks | metrics.clicks | match |
| search_terms | conversions | conversions | metrics.conversions | match |
| search_terms | cost | cost | metrics.cost_micros | match |
| search_terms | impressions | impressions | metrics.impressions | match |
| search_terms | matched_keyword_id | — |  | missing |
| search_terms | search_term | search_term | search_term_view.search_term | match |
| shared_negative_lists | list_id | shared_set_id | shared_set.id | match |
| table_manifest | completeness | @adapter |  | adapter |
| table_manifest | filename | @adapter |  | adapter |

## Recipe screening (static — NOT coverage)

Classes: base candidates found; also needs custom/external: 77, no base needs: 22, base-only, all candidates found: 18, base gaps: 18.

| recipe | screening class | base pairs with candidates | base gaps | custom/external tables |
|---|---|---|---|---|
| skill-001-campaign-type-separation | base candidates found; also needs custom/external | 13 |  | custom/campaign_features |
| skill-002-brand-nonbrand-split | base-only, all candidates found | 23 |  |  |
| skill-003-naming-convention-consistency | base candidates found; also needs custom/external | 7 |  | external/naming_dependencies |
| skill-004-ad-group-thematic-tightness | base-only, all candidates found | 24 |  |  |
| skill-005-search-partners-performance | base candidates found; also needs custom/external | 6 |  | custom/network_daily |
| skill-006-display-network-optin | base candidates found; also needs custom/external | 3 |  | custom/network_daily |
| skill-007-campaign-settings-hygiene | base candidates found; also needs custom/external | 11 |  | external/campaign_requirements |
| skill-008-label-organizational-structure | base candidates found; also needs custom/external | 7 |  | custom/label_associations, custom/label_inventory, external/label_policy |
| skill-009-account-defaults-audit | base gaps | 13 | conversion_actions.value_settings(missing), conversion_actions.attribution_model(missing) | custom/campaign_goal_selection, external/account_controls |
| skill-010-campaign-priority-experiments | base candidates found; also needs custom/external | 12 |  | custom/experiment_daily, custom/shopping_routing, external/experiment_design, external/experiment_inference |
| skill-012-keyword-match-type-distribution | base-only, all candidates found | 18 |  |  |
| skill-013-search-term-mining-keywords | base-only, all candidates found | 28 |  |  |
| skill-014-search-term-mining-negatives | base-only, all candidates found | 9 |  |  |
| skill-015-ngram-analysis | base-only, all candidates found | 25 |  |  |
| skill-016-negative-keyword-list-completeness | base candidates found; also needs custom/external | 29 |  | external/negative_upload_list |
| skill-017-negative-keyword-conflict-detection | base candidates found; also needs custom/external | 16 |  | custom/query_eligibility |
| skill-018-duplicate-keyword-detection | base-only, all candidates found | 31 |  |  |
| skill-020-low-performing-keyword-pruning | base gaps | 22 | search_terms.matched_keyword_id(missing) |  |
| skill-022-broad-match-smart-bidding-alignment | base gaps | 24 | search_terms.matched_keyword_id(missing) |  |
| skill-023-close-variant-query-expansion-monitoring | base gaps | 26 | search_terms.matched_keyword_id(missing) |  |
| skill-024-keyword-intent-alignment | base candidates found; also needs custom/external | 25 |  | external/landing_page_content |
| skill-025-rsa-headline-diversity-completeness | base-only, all candidates found | 19 |  |  |
| skill-026-rsa-description-optimization | base-only, all candidates found | 12 |  |  |
| skill-028-rsa-pinning-strategy-audit | base candidates found; also needs custom/external | 14 |  | external/rsa_message_constraints |
| skill-029-rsa-asset-performance-analysis | base candidates found; also needs custom/external | 12 |  | custom/rsa_asset_labels |
| skill-030-ad-extension-coverage-audit | base gaps | 11 | assets.association_status(tbd) |  |
| skill-031-sitelink-relevance-performance | base gaps | 10 | assets.status(tbd) | custom/sitelink_metrics, external/sitelink_destinations |
| skill-032-ad-copy-ab-testing | base candidates found; also needs custom/external | 17 |  | custom/creative_experiment_changes, custom/creative_experiment_results, external/creative_experiment_plan |
| skill-033-dynamic-keyword-insertion-review | base-only, all candidates found | 13 |  |  |
| skill-034-ad-copy-landing-page-consistency | base candidates found; also needs custom/external | 15 |  | external/ad_claim_register, external/landing_page_snapshots |
| skill-035-image-asset-optimization | no base needs | 0 |  | custom/creative_groups, custom/image_associations, external/image_format_requirements, external/image_review |
| skill-036-video-asset-presence | no base needs | 0 |  | custom/creative_groups, custom/video_associations, external/video_format_requirements, external/video_review |
| skill-037-ad-disapproval-monitoring | base candidates found; also needs custom/external | 11 |  | custom/ad_policy_history, custom/ad_policy_status |
| skill-038-spelling-editorial-error-detection | base candidates found; also needs custom/external | 10 |  | custom/ad_editorial_fields, external/editorial_brief |
| skill-039-bid-strategy-appropriateness-audit | base gaps | 5 | conversion_actions.value_settings(missing) | custom/bidding_configuration, custom/manual_keyword_bids, external/bidding_constraints |
| skill-040-target-cpa-roas-realism-check | base candidates found; also needs custom/external | 6 |  | custom/budget_history, custom/target_daily, custom/target_history |
| skill-041-smart-bidding-learning-phase-monitoring | no base needs | 0 |  | custom/learning_changes, custom/learning_daily, custom/learning_status_history |
| skill-042-budget-limited-campaign-identification | base candidates found; also needs custom/external | 7 |  | custom/budget_constraint_daily, custom/budget_constraint_status, custom/budget_history |
| skill-043-daily-budget-to-cpa-ratio-check | base-only, all candidates found | 5 |  |  |
| skill-044-monthly-budget-pacing-analysis | no base needs | 0 |  | custom/budget_history, custom/monthly_spend_daily, external/monthly_budget_plan |
| skill-045-budget-allocation-optimization | base candidates found; also needs custom/external | 4 |  | custom/allocation_daily, external/allocation_constraints, external/allocation_response |
| skill-046-portfolio-bid-strategy-evaluation | base-only, all candidates found | 8 |  |  |
| skill-048-bid-adjustment-layer-review | base candidates found; also needs custom/external | 8 |  | custom/modifier_history, custom/modifier_segment_daily, external/modifier_controls |
| skill-049-budget-overspend-underspend-alert-configuration | no base needs | 0 |  | custom/budget_alert_daily, custom/budget_alert_history, custom/budget_history, external/budget_alert_plan, external/budget_alert_rules |
| skill-050-shared-budget-appropriateness-check | base candidates found; also needs custom/external | 7 |  | custom/budget_history, custom/shared_budget_response |
| skill-051-bid-simulator-analysis-target-changes | no base needs | 0 |  | custom/bid_simulation_context, custom/bid_simulation_points |
| skill-052-conversion-value-based-bidding | base gaps | 4 | conversion_actions.value_settings(missing) | custom/conversion_value_action_daily, external/business_value_policy, external/business_value_reconciliation |
| skill-053-location-targeting-method-audit | base candidates found; also needs custom/external | 10 |  | custom/geo_targeting_methods |
| skill-054-geographic-performance-analysis | base candidates found; also needs custom/external | 8 |  | custom/geo_lookup, custom/geographic_performance |
| skill-056-device-performance-analysis | base candidates found; also needs custom/external | 2 |  | custom/device_controls, custom/device_performance |
| skill-057-ad-schedule-optimization | base candidates found; also needs custom/external | 3 |  | custom/day_hour_performance, custom/schedule_history, external/business_hours |
| skill-058-demographic-performance-analysis | base candidates found; also needs custom/external | 8 |  | custom/demographic_controls |
| skill-059-audience-observation-mode-setup | base-only, all candidates found | 7 |  |  |
| skill-060-in-market-custom-intent-layering | base gaps | 8 | audiences.mode(tbd), audiences.list_id(tbd), audiences.type(tbd) | custom/audience_exclusive_cohorts, custom/audience_segment_performance |
| skill-061-customer-match-list-health | base candidates found; also needs custom/external | 3 |  | custom/customer_match_status, external/customer_match_policy, external/customer_match_upload_history |
| skill-062-audience-minimum-size-monitoring | base candidates found; also needs custom/external | 3 |  | custom/audience_definition_history, custom/audience_eligibility, custom/audience_size_history |
| skill-064-quality-score-distribution-analysis | base-only, all candidates found | 21 |  |  |
| skill-065-quality-score-component-breakdown | base-only, all candidates found | 17 |  |  |
| skill-066-historical-quality-score-trend | base candidates found; also needs custom/external | 4 |  | custom/quality_change_history, custom/quality_score_history |
| skill-067-expected-ctr-improvement | base-only, all candidates found | 17 |  |  |
| skill-068-ad-relevance-gap-identification | base-only, all candidates found | 17 |  |  |
| skill-069-landing-page-experience-assessment | base candidates found; also needs custom/external | 13 |  | custom/landing_url_performance, external/landing_page_checks |
| skill-070-conversion-tracking-completeness | base candidates found; also needs custom/external | 2 |  | custom/conversion_action_daily, external/business_event_map, external/journey_coverage |
| skill-071-conversion-tracking-accuracy | no base needs | 0 |  | custom/ads_reconciliation_daily, external/ads_event_reconciliation, external/business_events, external/cross_device_measured, external/reconciliation_rules |
| skill-072-enhanced-conversions-web | base candidates found; also needs custom/external | 3 |  | external/enhanced_web_config, external/enhanced_web_diagnostics, external/enhanced_web_traces |
| skill-073-enhanced-conversions-leads | no base needs | 0 |  | external/enhanced_leads_config, external/enhanced_leads_diagnostics, external/enhanced_leads_qa, external/offline_outcomes, external/offline_pipeline_config, external/offline_upload_attempts |
| skill-074-server-side-tagging-assessment | base candidates found; also needs custom/external | 1 |  | external/tagging_architecture, external/tagging_decision_requirements, external/tagging_measurement_trials |
| skill-075-consent-mode-v2 | base candidates found; also needs custom/external | 1 |  | external/consent_configuration, external/consent_modeling_diagnostics, external/consent_traces |
| skill-076-conversion-action-configuration | base gaps | 7 | conversion_actions.value_settings(missing), conversion_actions.include_in_conversions(missing), conversion_actions.attribution_model(missing) |  |
| skill-078-landing-page-speed | base candidates found; also needs custom/external | 5 |  | external/destination_map, external/page_speed_results |
| skill-079-broken-url-monitoring | no base needs | 0 |  | external/destination_map, external/url_health_checks, external/url_incident_windows |
| skill-080-offline-conversion-import | base candidates found; also needs custom/external | 3 |  | custom/offline_action_daily, external/offline_outcomes, external/offline_pipeline_config, external/offline_upload_attempts, external/offline_upload_payload |
| skill-082-product-feed-title-optimization | no base needs | 0 |  | custom/product_daily, external/merchant_diagnostics, external/merchant_products, external/product_reference |
| skill-083-product-feed-attribute-completeness | no base needs | 0 |  | custom/product_daily, external/attribute_requirements, external/merchant_diagnostics, external/merchant_products, external/product_reference |
| skill-085-custom-label-strategy-segmentation | base candidates found; also needs custom/external | 2 |  | custom/listing_rules, external/label_strategy, external/merchant_products |
| skill-088-google-product-category-granularity | no base needs | 0 |  | external/google_taxonomy, external/merchant_products, external/product_reference |
| skill-089-pmax-asset-group-structure | base candidates found; also needs custom/external | 2 |  | custom/pmax_group_assets, custom/pmax_groups, custom/pmax_listing_rules, external/merchant_products, external/pmax_group_intent |
| skill-090-pmax-audience-signal-configuration | base candidates found; also needs custom/external | 2 |  | custom/pmax_audience_components, custom/pmax_groups, custom/pmax_signals, external/activation_permissions, external/audience_definitions |
| skill-092-pmax-final-url-expansion-control | base candidates found; also needs custom/external | 2 |  | custom/pmax_groups, custom/pmax_landing_pages, external/pmax_destination_review, external/pmax_url_rules, external/pmax_url_settings |
| skill-093-pmax-video-asset-review | base candidates found; also needs custom/external | 1 |  | custom/pmax_group_assets, custom/pmax_groups, external/pmax_video_details |
| skill-094-pmax-cannibalizing-search-detection | base candidates found; also needs custom/external | 7 |  | custom/search_pmax_daily, custom/search_pmax_queries, external/pmax_overlap_experiment, external/search_pmax_controls |
| skill-095-pmax-new-customer-acquisition | base candidates found; also needs custom/external | 1 |  | custom/pmax_customer_type_daily, external/activation_permissions, external/customer_ltv, external/pmax_acquisition_settings |
| skill-098-audience-segmentation-funnel-stage | base gaps | 3 | audiences.list_id(tbd) | custom/audience_associations, external/activation_permissions, external/audience_definitions, external/funnel_plan |
| skill-099-membership-duration-optimization | base gaps | 0 | audiences.list_id(tbd) | external/activation_permissions, external/audience_age_cohorts, external/audience_definitions, external/customer_lifecycle, external/membership_controls |
| skill-100-rlsa-campaign-strategy | base candidates found; also needs custom/external | 5 |  | custom/rlsa_associations, custom/rlsa_performance, external/activation_permissions, external/audience_definitions, external/rlsa_intent_controls |
| skill-101-dynamic-remarketing-setup | base gaps | 2 | audiences.list_id(tbd) | external/activation_permissions, external/audience_definitions, external/dynamic_configuration, external/dynamic_feed_items, external/dynamic_tag_diagnostics |
| skill-102-frequency-capping-management | base candidates found; also needs custom/external | 2 |  | custom/frequency_exposure, custom/frequency_outcomes, external/frequency_controls, external/frequency_plan |
| skill-103-recent-converter-exclusion | base candidates found; also needs custom/external | 3 |  | custom/converter_exclusions, external/activation_permissions, external/audience_definitions, external/converter_suppression_plan, external/customer_lifecycle |
| skill-105-ga4-advanced-audiences | base gaps | 1 | audiences.mode(tbd), audiences.list_id(tbd) | custom/ga4_audience_performance, external/ga4_audience_definitions, external/ga4_audience_sync, external/ga4_event_availability |
| skill-106-ga4-google-ads-integration | base candidates found; also needs custom/external | 2 |  | external/ga4_ads_event_mapping, external/ga4_ads_flow_checks, external/ga4_ads_links |
| skill-107-conversion-value-accuracy | base gaps | 3 | conversion_actions.value_settings(missing) | custom/ads_reconciliation_daily, external/business_events, external/conversion_adjustments, external/conversion_value_policy, external/reconciliation_rules, external/value_model_calibration, external/value_payload_qa |
| skill-110-conversion-tracking-breakage | no base needs | 0 |  | custom/tracking_daily, custom/tracking_traffic_daily, external/tracking_incidents |
| skill-111-data-exclusion-tracking-incidents | base candidates found; also needs custom/external | 3 |  | external/data_exclusion_config, external/data_exclusion_eligibility, external/incident_click_impact, external/incident_recovery_review, external/tracking_incidents |
| skill-112-return-refund-tracking | base candidates found; also needs custom/external | 2 |  | custom/ads_reconciliation_daily, external/adjustment_support, external/conversion_adjustments, external/conversion_value_policy, external/refund_ledger |
| skill-115-display-youtube-placement-performance-review | base candidates found; also needs custom/external | 2 |  | custom/placement_controls, custom/placement_daily, custom/placement_video_metrics, external/placement_policy |
| skill-117-ad-schedule-waste-analysis | base candidates found; also needs custom/external | 3 |  | custom/schedule_hourly, external/business_hours |
| skill-118-click-fraud-invalid-traffic-monitoring | no base needs | 0 |  | custom/invalid_click_daily, external/invalid_traffic_billing, external/traffic_incidents |
| skill-119-auto-applied-recommendations-review | no base needs | 0 |  | custom/auto_apply_changes, custom/auto_apply_outcomes, custom/auto_apply_subscriptions, external/auto_apply_authorizations |
| skill-121-impression-share-loss-analysis | base candidates found; also needs custom/external | 16 |  | custom/is_daily, external/is_scenarios |
| skill-122-automated-keyword-pause-rules | base candidates found; also needs custom/external | 12 |  | external/keyword_rule_policy |
| skill-123-budget-pacing-daily-allocation-scripts | no base needs | 0 |  | custom/allocation_daily, custom/budget_history, external/allocation_plan |
| skill-124-performance-anomaly-alert-configuration | no base needs | 0 |  | custom/anomaly_context, custom/anomaly_daily, external/alert_policy |
| skill-125-landing-page-health-check-automation | base candidates found; also needs custom/external | 5 |  | custom/url_daily, external/url_health, external/url_monitor_policy |
| skill-127-trending-search-term-detection | base candidates found; also needs custom/external | 10 |  | custom/search_trend_changes, custom/search_trend_daily |
| skill-128-performance-max-channel-performance | base candidates found; also needs custom/external | 8 |  | custom/pmax_channels, custom/pmax_group_daily, custom/pmax_groups, custom/pmax_placements |
| skill-130-campaign-enable-pause-scheduling | base candidates found; also needs custom/external | 5 |  | external/campaign_event_plan |
| skill-131-change-history-monitoring | base candidates found; also needs custom/external | 1 |  | custom/change_history_fields, custom/change_outcomes, external/change_authorizations |
| skill-135-top-of-page-rate-monitoring | base candidates found; also needs custom/external | 5 |  | custom/position_outcomes, custom/search_prominence_daily, custom/search_prominence_weekly |
| skill-136-geographic-competitive-intelligence | base candidates found; also needs custom/external | 5 |  | custom/geographic_daily, external/regional_business |
| skill-137-seasonal-performance-pattern-tracking | no base needs | 0 |  | custom/seasonal_budget_history, custom/seasonal_monthly, external/seasonal_context |
| skill-141-landing-page-policy-compliance | base candidates found; also needs custom/external | 6 |  | custom/page_policy_status, external/page_policy_evidence, external/page_policy_requirements |
| skill-142-trademark-policy-management | base candidates found; also needs custom/external | 7 |  | custom/trademark_policy_status, external/trademark_register |
| skill-145-prelaunch-compliance-checklist | base candidates found; also needs custom/external | 1 |  | external/launch_drafts, external/launch_evidence |
| skill-146-seasonality-bid-adjustment-deployment | base candidates found; also needs custom/external | 3 |  | custom/event_cvr_daily, custom/seasonality_settings, external/seasonality_events |
| skill-147-seasonal-budget-adjustment-scheduling | base candidates found; also needs custom/external | 3 |  | custom/seasonal_budget_daily, custom/seasonal_budget_rules, external/seasonal_budget_plan |
| skill-148-seasonal-keyword-calendar-planning | base candidates found; also needs custom/external | 17 |  | custom/seasonal_query_history, external/seasonal_keyword_plan |
| skill-149-promotional-extensions-countdown-customizers | no base needs | 0 |  | custom/promotion_config, external/promotion_offers |
| skill-151-product-feed-seasonal-keyword-optimization | base candidates found; also needs custom/external | 2 |  | custom/query_product_evidence, external/product_descriptor_evidence, external/seasonal_feed |
| skill-152-historical-performance-benchmarking-seasonal-planning | no base needs | 0 |  | custom/benchmark_budget_history, custom/seasonal_benchmark_daily, external/seasonal_forecast_plan |
| skill-156-first-party-data-collection-activation-strategy | base gaps | 0 | audiences.type(tbd), audiences.id(tbd) | external/activation_permissions, external/first_party_activation, external/first_party_capture, external/first_party_sources, external/first_party_use_plan |
| skill-159-ai-max-for-search-campaign-assessment | base candidates found; also needs custom/external | 3 |  | custom/ai_max_config, custom/ai_max_experiment_daily, external/ai_max_safeguards |
| skill-160-smart-bidding-exploration-configuration | base candidates found; also needs custom/external | 3 |  | custom/exploration_config, custom/exploration_experiment_daily, external/exploration_risk |
| skill-161-automation-layering-strategy-audit | base candidates found; also needs custom/external | 2 |  | external/automation_inventory, external/automation_risks, external/automation_runs |
| skill-162-creative-asset-quality-ai-campaign-optimization | base candidates found; also needs custom/external | 2 |  | custom/creative_group_inventory, custom/creative_quality_assets, external/creative_requirements |
| skill-163-product-performance-triage | base candidates found; also needs custom/external | 2 |  | custom/product_daily |
| skill-164-pmax-search-terms-and-categories | base candidates found; also needs custom/external | 5 |  | custom/pmax_search_categories, custom/pmax_search_terms |
| skill-165-merchant-feed-freshness-and-item-status | base candidates found; also needs custom/external | 2 |  | custom/product_daily, external/catalog_changes, external/merchant_diagnostics, external/merchant_feeds, external/merchant_item_status |
| skill-166-landing-page-performance | base candidates found; also needs custom/external | 2 |  | custom/landing_page_performance, external/landing_page_checks |
| skill-167-out-of-stock-ad-exposure | base gaps | 17 | keywords.final_url(missing), assets.status(tbd) | custom/asset_group_urls, custom/entity_daily, external/merchant_availability, external/page_stock_checks |
| skill-168-price-competitiveness-monitoring | no base needs | 0 |  | custom/product_daily, external/landing_page_prices, external/merchant_price_snapshots, external/price_competitiveness |
| skill-169-account-portfolio-summary | base candidates found; also needs custom/external | 6 |  | custom/account_daily_metrics |
| skill-170-ad-grants-compliance | base gaps | 20 | assets.status(tbd) | custom/grants_monthly_metrics |
| skill-171-keyword-hypothesis-expansion | base candidates found; also needs custom/external | 25 |  | external/landing_page_content |
| skill-172-external-signal-demand-analysis | no base needs | 0 |  | custom/campaign_geo_daily, custom/campaign_geo_hourly, external/external_signals, external/signal_rules |
| skill-173-export-intake-preflight | base-only, all candidates found | 63 |  |  |

## Custom tables — name screening (129 tables)

Share of a table's columns whose name equals a Windsor field id (or a listed alias). Name equality is not semantic
equality (e.g. a history table needs dated snapshots, not today's value).

| custom table | name hits | recipes | columns without a name hit |
|---|---|---|---|
| account_daily_metrics | 5/5 | 169 |  |
| anomaly_daily | 6/6 | 124 |  |
| asset_group_urls | 4/4 | 167 |  |
| budget_constraint_daily | 4/4 | 042 |  |
| campaign_geo_daily | 7/7 | 172 |  |
| campaign_geo_hourly | 8/8 | 172 |  |
| device_performance | 8/8 | 056 |  |
| label_inventory | 3/3 | 008 |  |
| network_daily | 7/7 | 005, 006 |  |
| pmax_placements | 3/3 | 128 |  |
| pmax_search_terms | 5/5 | 164 |  |
| quality_score_history | 7/7 | 066 |  |
| tracking_traffic_daily | 9/9 | 110 |  |
| day_hour_performance | 9/10 | 057 | timezone |
| schedule_hourly | 9/10 | 117 | goal_id |
| pmax_group_daily | 8/9 | 128 | goal_set_id |
| product_daily | 8/9 | 082, 083, 163, 165, 168 | target_country |
| rsa_asset_labels | 7/8 | 029 | snapshot_at |
| seasonal_query_history | 7/8 | 148 | query |
| change_outcomes | 6/7 | 131 | maturity |
| pmax_group_assets | 6/7 | 089, 093 | association_status |
| search_pmax_daily | 6/7 | 094 | goal_set_id |
| invalid_click_daily | 5/6 | 118 | denominator_definition |
| landing_url_performance | 5/6 | 069 | landing_page_url |
| learning_daily | 5/6 | 041 | lag_mature |
| pmax_groups | 5/6 | 089, 090, 092, 093, 128 | platform_diagnostic |
| pmax_search_categories | 5/6 | 164 | category_label |
| target_daily | 5/6 | 040 | lag_mature |
| search_prominence_daily | 9/11 | 135 | rate_counting_basis, share_censoring |
| budget_alert_daily | 4/5 | 049 | complete_day |
| grants_monthly_metrics | 4/5 | 170 | complete_month |
| is_daily | 4/5 | 121 | historical_budget_amount |
| search_prominence_weekly | 8/10 | 135 | period_end, period_start |
| seasonal_budget_daily | 8/10 | 147 | goal_id, maturity |
| position_outcomes | 7/9 | 135 | position_segment, segment_definition |
| audience_segment_performance | 10/13 | 060 | audience_type, mode, reporting_completeness |
| ad_editorial_fields | 3/4 | 038 | displayed_domain |
| ga4_audience_performance | 9/12 | 105 | mode, overlap_known, reporting_mature |
| monthly_spend_daily | 3/4 | 044 | complete_day |
| search_pmax_queries | 6/8 | 094 | query_text, reported_query_or_category_type |
| tracking_daily | 9/12 | 110 | action_id, date_basis, reporting_mature |
| geographic_performance | 8/11 | 054 | geo_criterion_id, geo_level, report_basis |
| seasonal_benchmark_daily | 8/11 | 152 | conversion_date_basis, goal_id, maturity |
| ads_reconciliation_daily | 5/7 | 071, 107, 112 | action_id, reporting_mature |
| search_trend_daily | 5/7 | 127 | matched_keyword_id, query |
| url_daily | 5/7 | 125 | URL, ad_or_keyword_id |
| auto_apply_outcomes | 7/10 | 119 | conversion_date_basis, goal_id, maturity |
| rlsa_performance | 7/10 | 100 | goal_set_id, list_id, segmentation_definition |
| audience_exclusive_cohorts | 8/12 | 060 | assignment_method, cohort_id, definition, overlap_resolved |
| campaign_features | 4/6 | 001 | feature_name, snapshot_date |
| conversion_value_action_daily | 4/6 | 052 | action_id, lag_mature |
| entity_daily | 4/6 | 167 | entity_id, entity_type |
| event_cvr_daily | 4/6 | 146 | goal_id, maturity |
| landing_page_performance | 4/6 | 166 | url, url_view |
| modifier_segment_daily | 6/9 | 048 | dimension, goal_cohort, segment_id |
| pmax_landing_pages | 6/9 | 092 | goal_set_id, provenance, reported_url |
| ai_max_experiment_daily | 7/11 | 159 | arm_id, assignment_method, experiment_id, goal_id |
| experiment_daily | 7/11 | 010 | arm_id, assigned_units, experiment_id, goal_scope |
| geographic_daily | 9/15 | 136 | country_id, goal_id, location_basis, location_id, region_id, unknown_location_flag |
| label_associations | 3/5 | 008 | entity_id, entity_type |
| seasonal_monthly | 7/12 | 137 | active_days, goal_id, is_censoring, search_is_if_available, tracking_basis |
| placement_daily | 8/14 | 115 | URL_or_app_id, app_category_id, category_source, format, objective, placement_id |
| pmax_channels | 4/7 | 128 | goal_set_id, reported_channel, reported_format |
| sitelink_metrics | 4/7 | 031 | association_key, click_scope, segment |
| allocation_daily | 5/9 | 045, 123 | goal_cohort, goal_id, lag_mature, value |
| trademark_policy_status | 5/9 | 142 | limitation, request_id_if_known, snapshot_at, topic |
| ad_policy_status | 2/4 | 037 | eligible_geographies_or_formats, source_ref |
| conversion_action_daily | 2/4 | 070 | action_id, reporting_mature |
| exploration_experiment_daily | 5/10 | 160 | arm_id, assignment_method, experiment_id, goal_id, separately_reported_traffic_label |
| offline_action_daily | 3/6 | 080 | action_id, date_basis, reporting_mature |
| pmax_customer_type_daily | 4/8 | 095 | lifecycle_added_value, reported_customer_type, total_reported_value, transaction_value |
| query_product_evidence | 4/8 | 151 | coverage, item_id, mapping_method, query |
| creative_experiment_results | 4/9 | 032 | arm_id, assigned_units, experiment_id, lag_cutoff, variance_or_inference_report_ref |
| pmax_signals | 3/7 | 090 | audience_resource_id, search_theme_text, signal_id, signal_type |
| auto_apply_subscriptions | 2/5 | 119 | snapshot_at, source_screen, subscribed |
| benchmark_budget_history | 2/5 | 152 | effective_from, effective_to, member_campaign_ids |
| bidding_configuration | 2/5 | 039 | legacy_ecpc_setting, legacy_setting_source, snapshot_at |
| budget_constraint_status | 2/5 | 042 | budget_specific_diagnostic, observed_at, raw_reasons |
| converter_exclusions | 4/10 | 103 | association_status, inventory_complete, level, list_id, mode, supported_exclusion_control |
| quality_change_history | 2/5 | 066 | changed_at, criterion_id_or_ad_id, field |
| seasonal_budget_history | 2/5 | 137 | effective_from, effective_to, member_campaign_ids |
| frequency_outcomes | 3/8 | 102 | goal_set_id, population_scope, report_end, report_start, reported_frequency_bucket |
| page_policy_status | 3/8 | 141 | affected_url, policy_topic, review_status, serving_limitation, snapshot_at |
| audience_associations | 2/6 | 098 | association_status, inventory_complete, list_id, mode |
| budget_history | 2/6 | 040, 042, 044, 049, 050, 123 | campaign_ids, effective_from, effective_to, member_campaign_ids |
| creative_group_inventory | 2/6 | 162 | eligibility_status, group_id, group_type, subtype |
| frequency_exposure | 3/9 | 102 | deduplication_scope, population_scope, reach_by_bucket, report_end, report_start, reported_frequency_bucket |
| modifier_history | 2/6 | 048 | changed_at, dimension, effective_from, new_modifier |
| pmax_audience_components | 1/3 | 090 | audience_resource_id, component_type |
| rlsa_associations | 3/9 | 100 | association_status, eligibility, inventory_complete, list_id, mode, modifier |
| demographic_controls | 3/10 | 058 | control_type, current_value, dimension, permitted_max, permitted_min, segment, supported |
| exploration_config | 3/10 | 160 | availability, budget_limited, configured_roas_tolerance_percent, portfolio_members, snapshot_at, strategy_id, targeting_eligibility |
| manual_keyword_bids | 3/10 | 039 | ad_group_default_cpc, eligibility_status, estimate_at, estimate_status, first_page_estimate, keyword_bid_is_inherited, keyword_cpc_bid |
| shopping_routing | 3/10 | 010 | eligible, feed_label, included, language, priority, snapshot_date, target_country |
| campaign_goal_selection | 2/7 | 009 | custom_goal_id, goal_id, selected_for_bidding, selection_source, snapshot_date |
| geo_targeting_methods | 2/7 | 053 | criterion_type, excluded, location_or_radius, negative_geo_target_type, positive_geo_target_type |
| pmax_listing_rules | 2/7 | 089 | dimension, node_id, other_case, parent_node_id, value |
| schedule_history | 3/11 | 057 | effective_end, effective_start, end_hour, end_minute, schedule_id, start_hour, start_minute, timezone |
| promotion_config | 4/15 | 149 | actual_serving_dates, asset_or_ad_id, association_id, configured_discount, countdown_raw_text, countdown_timezone_mode, linking_level, preview_at, preview_result, schedule, snapshot_at |
| geo_lookup | 1/4 | 054 | geo_criterion_id, geo_level, parent_id |
| image_associations | 3/12 | 035 | approval, entity_id, entity_type, file_size_bytes, height_px, linking_level, mime_type, snapshot_at, width_px |
| learning_changes | 1/4 | 041 | change_id, changed_at, field |
| placement_video_metrics | 1/4 | 115 | format, measurable_impressions, viewable_impressions |
| query_eligibility | 1/4 | 017 | diagnosis, intended_eligible, query |
| auto_apply_changes | 3/13 | 119 | actor_id, approval_ref, change_id, client_type, field_path, new_value, occurred_at, old_value, operation, strategy_id |
| change_history_fields | 3/13 | 131 | actor_id, approval_ref, change_id, client_type, field_path, new_value, occurred_at, old_value, operation, strategy_id |
| creative_quality_assets | 3/13 | 162 | association_id, duration_seconds, field_role, group_id, height, label_date, linked_status, provenance, text, width |
| device_controls | 2/9 | 056 | control_type, current_value, permitted_max, permitted_min, snapshot_date, strategy_type, support_source_url |
| learning_status_history | 1/5 | 041 | documented_learning_state, observed_at, raw_reason, raw_status |
| seasonal_budget_rules | 2/10 | 147 | action, current_amount, manual_override_owner, reversion_amount, rule_id, scheduled_at, snapshot_at, timezone |
| ai_max_config | 2/11 | 159 | ai_max_enabled, availability, brand_controls, final_url_expansion_enabled, search_term_matching_enabled, snapshot_at, text_customization_enabled, url_exclusions, url_inclusions |
| video_associations | 2/11 | 036 | approval, association_status, entity_id, entity_type, linking_level, provenance, provenance_source, snapshot_at, youtube_video_id |
| audience_eligibility | 2/12 | 062 | eligibility_reason, eligible, list_id, list_type, membership_duration_days, processing_status, reported_size, size_precision, snapshot_date, use_type |
| audience_size_history | 1/6 | 062 | list_id, reported_size, size_as_of, size_precision, use_type |
| listing_rules | 1/6 | 085 | dimension, node_id, other_case, parent_node_id, value |
| search_trend_changes | 1/6 | 127 | change_id, changed_field, new_value, occurred_at, old_value |
| ad_policy_history | 1/7 | 037 | affected_policy_topic, event_at, event_id, event_type, new_status, prior_status |
| bid_simulation_context | 1/7 | 051 | current_target_at_simulation, goal_action_ids, material_changes_since, simulation_id, strategy_type, value_basis |
| customer_match_status | 2/14 | 061 | account_use_eligible, eligibility_reason, eligible, list_id, list_type, match_rate, match_rate_available, match_rate_definition, membership_duration_days, reported_size, size_precision, snapshot_date |
| placement_controls | 1/8 | 115 | control_id, included_or_excluded, inherited_from, placement_or_category_id, scope_id, scope_type, snapshot_at |
| creative_groups | 1/9 | 035, 036 | eligibility, entity_id, entity_status, entity_type, parent_status, snapshot_at, source_ref, subtype |
| seasonality_settings | 1/9 | 146 | adjustment_id, campaign_ids, cvr_adjustment_percent, device_scope, end_at, scope_type, start_at, timezone |
| shared_budget_response | 1/10 | 050 | model_id, modeled_conversions, modeled_cost, modeled_value, period_end, period_start, scenario_id, source_ref, source_type |
| anomaly_context | 0/8 | 124 | affected_metrics, end_at, entity_id, event_id, event_type, evidence_ref, incident_confirmed, start_at |
| audience_definition_history | 0/5 | 062 | change_type, effective_at, list_id, new_value, old_value |
| bid_simulation_points | 0/15 | 051 | baseline_point_flag, generated_at, modeled_conversion_value, modeled_conversions, modeled_cost, modification_method, point_id, scope_id, scope_type, simulation_end_date, simulation_id, simulation_start_date, simulation_type, target_type, target_value |
| budget_alert_history | 0/9 | 049 | condition, evaluated_at, notification_status, observed_value, resolved_at, rule_id, scope_id, threshold, triggered |
| creative_experiment_changes | 0/8 | 032 | change_id, changed_at, entity_id, experiment_id, field, new_value, old_value, reason |
| target_history | 0/6 | 040 | effective_from, effective_to, entity_id, entity_type, target_type, target_value |

## External tables — other Windsor connectors (existence only)

`GET connectors.windsor.ai/list_connectors` (public, 360 connectors) lists `google_merchant`, `googleanalytics4`,
`searchconsole`, `google_pagespeed`, `hubspot`, `salesforce`. They are candidates for some `external/` tables
(Merchant products/diagnostics, GA4 reconciliation, page speed). Fields, grain and permissions are NOT checked.
CRM data stays local and sanitized per DATA_CONTRACT invariant 8 and `docs/command-center-design.md` (not via Windsor).

## Pending — first live MCP run of skill-174

skill-174 implements the pulls whose fields were matched above; its normalizer refuses unexpected shapes, so the
first real run through the Windsor MCP (`plan` → `get_data` → `normalize`) is the verification. Still to confirm on
live data: the value shapes of `period`, `end_date`, list fields (headlines/descriptions/final URLs/policy topics),
`conversion_action_id`, the resource each ambiguous pair resolves to, and whether zero-activity rows are omitted;
then repeat on a non-EUR account. Not yet pulled by skill-174: budgets, bidding strategies, bid adjustments,
audiences, assets, shared negative lists, account-level negatives and the custom tables that passed name screening.
Search terms are deliberately never pulled through MCP (raw query text would reach the model context before any
sanitizing, DATA_CONTRACT invariant 8); skill-174 imports them only from a skill-173 export of the same window.
(The REST key used for batch 1 must be rotated; the MCP path uses Windsor OAuth instead.)
