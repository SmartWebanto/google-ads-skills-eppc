# Client profile

The front desk reads `ads/profile.yaml` in the client repository. Unknown values remain unknown; do not infer business objectives, service areas, customer lifecycles or consent from account/campaign/list names. Ask only for missing information needed by the requested checks. Campaign-level objectives take precedence over compatible account defaults.

```yaml
slug: eppcdigital
report_language: it               # en | it
market: [IT]                      # ISO served-market codes; traffic evidence may add markets
export_path: export/
reporting_end_date: null          # otherwise complete report end from account; account timezone
business_type: null               # e.g. ecommerce, lead_generation; not inferred from names
objectives: []                    # expected business events, bidding purpose and value definitions
campaign_objectives: {}           # campaign ID -> goal IDs, role, target, brand policy, intent
service_area: []                  # explicit served locations and travel/remote-service exceptions
brand_terms: []                   # approved brand aliases; ambiguous/product-generic terms need review
competitor_terms: []              # identification only, not automatic negatives or policy violations
excluded_intents: []              # business-confirmed irrelevant intents; not universal waste tokens
customer_lifecycle: null          # purchase/repurchase cycle, acquisition vs retention/upsell policies
sales_cycle_days: null            # sales cycle is not upload-processing delay
conversion_lag_days: null         # measured goal-specific maturity; null is not zero
monthly_budget: null              # approved account spending cap, not daily budget * calendar days
budget_constraints: {}           # campaign/shared-pool caps, priorities and approved commitments
experiment_constraints: null     # accepted risk, allocation, primary metric, horizon and stop rules
target_cpa: null                  # compatible account-level business target, in account currency
target_roas: null                 # ratio: 4.0 means 400%; never a substitute for CPA
currency_floors: {}               # required money floors for non-EUR unless final overrides supplied
parameter_overrides: {}           # final values by parameter name without braces
tracking_verified: {}             # goal ID -> {status: verified, verified_from, verified_through, source_ref}; must cover the report window; free text is not proof
column_map: {}                    # table -> {semantic column: source column}; explicit renames for scripts, no fuzzy matching
```

## Rules

- Currency always comes from `account.currency_code`; no currency override. Typical monthly spending is not the actual 30-day parameter window. Follow `PARAMETERS.md` for currency floors, targets and overrides.
- A campaign objective entry can declare `goal_ids`, `role`, `target_cpa`, `target_roas`, `brand_policy`, relevant product/service themes and allowed/excluded intents. The source/owner of a decision must be recorded; unknown intent is not permission to restructure.
- Consent review is required when serving EEA/UK markets or applicable traffic is evidenced, including tracking prerequisites for other presets. These rules are technical measurement checks, not legal certification. Country-specific subsections run only for supported markets; age/gender review is not US-only merely because household-income data is market-limited.
- Calendars, offer claims, authorization records, approved automation inventories and campaign-specific lifecycle/value definitions are supplied when the relevant skill requests them. They are not fabricated from a generic profile.
- Do not store raw customer records, credentials, emails or phone numbers in the profile. Provide sanitized diagnostic evidence and pseudonymous reconciliation keys as required by the data contract. Availability of records is not authorization to upload them.
- Confirm the analysis environment is approved for the supplied evidence. A remote language model receives its prompt context even if no third-party tool is called.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | explicit business, maturity and authorization context
agent: claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | tracking_verified (verified_from/through, source_ref) and column_map fields
