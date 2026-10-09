# Parameters

Thresholds are review heuristics, not statistical significance, platform eligibility or proof of lost profit. A threshold crossing never bypasses applicability, evidence completeness, business goals, conversion maturity or the severity policy. Money is in the account currency, not assumed EUR.

| Parameter | EUR reference default | Definition |
|---|---|---|
| `{{spend_floor}}` | 50 | max(currency floor, 1 × applicable target CPA); mature zero-conversion exposure worth reviewing, not an automatic pause |
| `{{spend_significant}}` | 100 | max(currency floor, 2 × applicable target CPA); materiality screen, not an automatic severity |
| `{{spend_material}}` | 200 | max(currency floor, 3 × applicable target CPA); prioritization of weaker diagnostics |
| `{{spend_high}}` | 500 | max(currency floor, 5 × applicable target CPA, 5% of actual 30-day account spend) |
| `{{monthly_spend_significant}}` | 1000 | max(currency floor, 10% of actual 30-day account spend); scope/prioritization, not a requirement to adopt audiences |
| `{{monthly_spend_large}}` | 5000 | max(currency floor, 25% of actual 30-day account spend); scope/prioritization, not a migration mandate |
| `{{min_clicks}}` | 100 | Minimum mature clicks in each cohort before comparing conversion rates |
| `{{min_impressions}}` | 1000 | Minimum relevant impressions in each cohort before comparing CTR/visibility; use the correct format denominator |
| `{{min_conversions}}` | 15 | Minimum mature conversions in each cohort before CPA/ROAS comparisons; not a Smart Bidding or DDA eligibility rule |
| `{{currency}}` | Account currency | Read `account.currency_code`; never infer from market or profile language |

## Resolution

1. Read currency and units from the export. EUR accounts use the reference floors. Other currencies require explicit `currency_floors` for all six money parameters in the profile, or explicit resolved `parameter_overrides` for those parameters. Do not silently treat 50 EUR as 50 JPY or invent an exchange rate. Missing monetary configuration blocks only dependent money-threshold findings.
2. Resolve applicable target CPA from the campaign (including a target embedded in Maximize Conversions), then a linked portfolio target, then a compatible campaign-objective/account profile target. Zero, negative or unknown targets are absent. Never substitute target ROAS for CPA. Mixed-goal accounts must not inherit an unrelated global target.
3. **30-day account spend** covers exactly 30 complete account-time-zone days ending at the stated report end. Sum daily spend once across all campaigns, including currently paused/removed campaigns that spent in that window; never sum segmented totals twice. A certified total with those exact dates is also usable. A 14- or 90-day report total and a typical `monthly_spend` estimate are not substitutes. If the window is unavailable, percentage-dependent thresholds are unresolved; other thresholds still resolve.
4. `parameter_overrides` supplies the final resolved value for named parameters, not a floor before the max formula. Values must be positive finite numbers; sample parameters must be positive integers. No override can disable evidence or consent gates. Report defaults, currency floors, target, window, overrides and resolved values used.
5. For reports with a different duration, do not annualize/monthly-scale exposure without stating the assumption. Keep observation period, parameter spend window and comparison periods distinct.

## Samples, uncertainty and severity

- Apply sample gates at the finding's entity/cohort grain, not to the entire account to qualify a tiny segment. CTR requires impressions; conversion rate requires clicks; CPA/ROAS requires conversions. Both comparison sides must qualify and use the same goal/value definition and maturity rule.
- A count gate is not a confidence interval or experimental significance test. Controlled comparisons require predeclared allocation, metric, duration/maturity, stopping rule and an appropriate uncertainty method. Do not calculate significance from arbitrary ad-serving allocations as though randomized.
- If a relevant denominator is zero/missing, the rate is undefined. Do not emit infinite CPA, zero ROAS from missing value data, or comparisons against absent targets. Report insufficient evidence as Info.
- **Zero-conversion exception:** min_conversions does not apply to zero-conversion spend screening. Require a mature full window, verified usable tracking for that goal, applicable spend threshold, sufficient exposure, and a relevance/business-role review. Screening produces a Warning recommendation to investigate; pausing/excluding requires separate evidence of irrelevance or unacceptable economics. A tracking outage or long sales cycle can explain zero conversions.
- Missing/uncertain lag maturity blocks performance-driven prescriptions, not reporting descriptive numbers. An explicitly confirmed zero-day lag is different from unknown lag.
- A zero or exactly 1 {{currency}} conversion value is a configuration observation, not inherently an error. Judge it against the declared conversion's economic role and bidding use.
- Critical is reserved for a directly evidenced material serving, measurement or safety failure. Optional feature absence, low QS/Ad Strength, small inventories, low samples and naming preferences are never independently Critical.

agent: gpt-6-astra | openai | 2026-09-06 | s_20260906_fix | actual 30-day window, currency floors and guarded triage
