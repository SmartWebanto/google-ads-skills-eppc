# Parameters

Every monetary or sample-size threshold in the skills is a named parameter written as `{{name}}`. Defaults are in EUR and are floors: the spend-relative formula wins when it is larger. A client profile (`_resources/CLIENT_PROFILE.md`) may override any default.

| Parameter | Default | Definition |
|---|---|---|
| `{{spend_floor}}` | 50 | max(50 {{currency}}, 1 × target CPA). Minimum spend before a zero-conversion entity is flagged. |
| `{{spend_significant}}` | 100 | max(100 {{currency}}, 2 × target CPA). Spend that makes a problem worth a Warning or Critical. |
| `{{spend_material}}` | 200 | max(200 {{currency}}, 3 × target CPA). Spend that makes a weaker signal (QS 4-5, demographics, devices) actionable. |
| `{{spend_high}}` | 500 | max(500 {{currency}}, 5 × target CPA, 5% of 30-day account spend). Spend that makes a Quality Score component or placement class Critical. |
| `{{monthly_spend_significant}}` | 1000 | max(1000 {{currency}}, 10% of 30-day account spend). A campaign large enough to need audiences and allocation review. |
| `{{monthly_spend_large}}` | 5000 | max(5000 {{currency}}, 25% of 30-day account spend). A campaign whose bidding migration is urgent. |
| `{{min_clicks}}` | 100 | Minimum clicks before judging a rate (CTR, conversion rate). |
| `{{min_impressions}}` | 1000 | Minimum impressions before judging CTR or impression share. |
| `{{min_conversions}}` | 15 | Minimum conversions before comparing CPA or ROAS against an average or target. |
| `{{currency}}` | account currency | Always read from `customer.currency_code` (or the export's account summary). Never assumed. |

## Rules

- **Target CPA** is the campaign's target if set, else the account-level target from the client profile, else absent (the EUR floor applies).
- **30-day account spend** is the sum of `metrics.cost_micros` over the report's date range, converted to currency units (divide by 1,000,000).
- **Placeholder-value checks** are written as "valued at exactly 1 {{currency}}"; zero-value checks as "zero value". Never as `$1` or `$0`.
- **Rate-based conditions** apply only above a minimum sample: CTR rows above `{{min_impressions}}` impressions, conversion-rate rows above `{{min_clicks}}` clicks, CPA/ROAS comparisons above `{{min_conversions}}` conversions. Below that, the skill reports "insufficient sample" as Info, never Critical.
- **Report values** are always written in `{{currency}}` with the ISO code or symbol of the account (EUR → €), formatted for `report_language`.
- **Overrides** come from the client profile `parameter_overrides` map, keyed by parameter name without braces.
