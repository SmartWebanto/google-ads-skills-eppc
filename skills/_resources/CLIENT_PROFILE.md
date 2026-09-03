# Client profile

The front desk reads `ads/profile.yaml` from the client repository when it exists, otherwise it asks for these values before running any skill. Nothing here is sent anywhere.

```yaml
slug: eppcdigital                 # client identifier
report_language: it               # it | en
market: [IT]                      # ISO country codes the account serves; drives EEA rules and us_only skips
currency_override: null           # normally null: currency comes from the account export
target_cpa: null                  # account-level target CPA in account currency, if the client has one
target_roas: null                 # account-level target ROAS, if the client has one
monthly_spend: null               # typical 30-day spend in account currency; computed from the export when null
brand_terms: []                   # brand and product names, for brand/non-brand skills
export_path: export/              # folder holding the tables described in DATA_CONTRACT.md
parameter_overrides: {}           # e.g. { spend_floor: 30, min_conversions: 10 }
```

Rules:

- The export is produced by the client or the studio from Google Ads (UI reports, Editor, or API) following `DATA_CONTRACT.md`. No third-party service is involved.
- If any `market` is in the EEA, the tracking workflow always includes skill-075 (Consent Mode v2) and skills marked `markets: us_only` skip their US-only sections.
- `parameter_overrides` keys are parameter names from `PARAMETERS.md` without braces.
