#!/usr/bin/env python3
"""One-off (2026-09-03): the eight merges from docs/superpowers/plans/2026-09-03-google-ads-skills-library.md.
Removes the absorbed directory, renames the canonical where the plan says so, and rewrites the
canonical's frontmatter, Purpose, Analysis Steps, Thresholds, plus the stated Data/Output additions.
Every replacement asserts its anchor exists. Run once from the repo root, after migrate_2026_09_03.py."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("skills")


def sh(*args: str) -> None:
    subprocess.run(args, check=True)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    assert text.count(old) == 1, f"{label}: anchor not found exactly once: {old[:60]!r}"
    return text.replace(old, new)


def replace_section(text: str, heading: str, next_heading: str, new_body: str, label: str) -> str:
    pat = re.compile(rf"(^{re.escape(heading)}\n)(.*?)(?=^{re.escape(next_heading)}\n)", re.S | re.M)
    assert pat.search(text), f"{label}: section {heading} not found"
    return pat.sub(lambda m: m.group(1) + "\n" + new_body.strip("\n") + "\n\n", text, count=1)


def set_frontmatter(text: str, name: str, description: str, merged_from: str, data_source: str, label: str) -> str:
    text = re.sub(r"^name:.*$", f"name: {name}", text, count=1, flags=re.M)
    text = re.sub(r"^description:.*$", f'description: "{description}"', text, count=1, flags=re.M)
    text = re.sub(r"^  data_source:.*$", f"  data_source: {data_source}\n  merged_from: [{merged_from}]", text, count=1, flags=re.M)
    assert f"merged_from: [{merged_from}]" in text, f"{label}: merged_from not set"
    return text


def set_title(text: str, num: str, title: str) -> str:
    return re.sub(rf"^# Skill {num}:.*$", f"# Skill {num}: {title}", text, count=1, flags=re.M)


def set_data_source_line(text: str, value: str) -> str:
    return re.sub(r"^\*\*Data Source:\*\*.*$", f"**Data Source:** {value}", text, count=1, flags=re.M)


M = []  # (canonical_old_dir, canonical_new_dir, absorbed_dir, editor)


# ------------------------------------------------------------------ 121 + 133
def m121(t: str) -> str:
    L = "121"
    t = set_frontmatter(t, "skill-121-impression-share-loss-analysis",
                        "Segment search impression share lost to budget vs ad rank, quantify the opportunity, and route each campaign to a budget or Quality Score fix.",
                        "skill-133-impression-share-loss-analysis", "custom_gaql", L)
    t = set_title(t, "121", "Impression Share Loss Analysis")
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Split impression-share loss into budget-constrained and rank-constrained causes so optimization effort targets the right root cause. Budget loss on a profitable campaign is missed conversions; rank loss points to Quality Score or bids, not budget. Quantify the opportunity per campaign before recommending spend.", L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Fetch impression share data:** Run the GAQL query for search campaigns (IS, budget-lost IS, rank-lost IS, top/absolute-top IS)
2. **Categorize campaigns:** Budget-constrained (budget lost >10%), rank-constrained (rank lost >20%), both (>15% each), or optimized
3. **Calculate opportunity cost:** Missed impressions, clicks and conversions from lost IS using each campaign's CTR and conversion rate
4. **Diagnose root causes:** Budget loss → check exhaustion time and profitability (conversions >= {{min_conversions}}); rank loss → check Quality Score components
5. **Prioritize recommendations:** Rank fixes first (cheaper), then budget increases on profitable campaigns, ordered by recovery value
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| Budget Lost IS > 20% on profitable campaign | Critical |
| Rank Lost IS > 30% | Critical |
| Budget and rank lost > 15% each | Warning |
| Budget Lost IS > 10% | Warning |
| Rank Lost IS > 20% | Warning |
| Any IS loss 5-10% | Info |

Sample size: judge impression share only above {{min_impressions}} impressions in the period.
""", L)
    t = replace_once(t, "**Detailed adds:**\n- Campaign-by-campaign IS breakdown table",
                     "**Detailed adds:**\n- Loss summary by cause (budget / rank / both / optimized) with campaign counts and average loss\n- Campaign-by-campaign IS breakdown table", L)
    return t


M.append(("skill-121-impression-share-lost-analysis", "skill-121-impression-share-loss-analysis", "skill-133-impression-share-loss-analysis", m121))


# ------------------------------------------------------------------ 023 + 120
def m023(t: str) -> str:
    L = "023"
    t = set_frontmatter(t, "skill-023-close-variant-query-expansion-monitoring",
                        "Monitor the queries triggered by broad/phrase expansion and exact/phrase close variants; flag irrelevant spend, same-meaning drift, and converting queries to add as keywords.",
                        "skill-120-close-variant-match-expansion-monitoring", "standard", L)
    t = set_title(t, "023", "Close Variant and Query Expansion Monitoring")
    t = replace_section(t, "## Purpose", "## Data Requirements",
        'Google expands every match type: broad and phrase reach related queries, and exact and phrase also match close variants and "same meaning" rewrites. Map each search term to its triggering keyword, judge relevance, and act: negatives for irrelevant spend, new keywords for converting queries, narrower match types for keywords that mostly trigger drift.', L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Map keywords to search terms:** Group search terms by triggering keyword and match type
2. **Classify each term:** Exact query, close variant (misspelling, reorder, plural), same-meaning rewrite, expanded (broad/phrase), or irrelevant
3. **Compare performance by class:** Conversion rate and CPA of exact queries vs variants vs expansions, per keyword
4. **Find negatives:** Irrelevant or zero-conversion terms above the spend floor
5. **Find keyword candidates:** Converting queries not yet keywords (search_term_view.status = NONE)
6. **Find keywords to narrow:** >= 50% of clicks on irrelevant or drifted terms, or an exact keyword taking > 50% of clicks from variants
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| Irrelevant or zero-conversion term, Cost >= {{spend_floor}} | Critical |
| Keyword with >= 50% of clicks on irrelevant terms | Critical |
| "Same meaning" variant with different intent | Warning |
| Variant conversion rate < 50% of exact-query rate | Warning |
| Converting query not added as keyword | Warning |
| Exact keyword with > 50% of clicks from variants | Info |
| Broad keyword triggering 30+ unique queries | Info |

Sample size: compare conversion rates only above {{min_clicks}} clicks per class.
""", L)
    t = replace_once(t, "**Detailed adds:**\n- Query expansion summary by match type",
                     "**Detailed adds:**\n- Match analysis table: exact queries vs close variants vs expansions (conversion rate, CPA)\n- Query expansion summary by match type", L)
    return t


M.append(("skill-023-close-variant-broad-match-monitoring", "skill-023-close-variant-query-expansion-monitoring", "skill-120-close-variant-match-expansion-monitoring", m023))


# ------------------------------------------------------------------ 061 + 104
def m061(t: str) -> str:
    L = "061"
    t = set_frontmatter(t, "skill-061-customer-match-list-health",
                        "Audit Customer Match lists for presence, size, match rate, freshness, and application to campaigns.",
                        "skill-104-customer-match-list-management", "custom_gaql", L)
    t = set_title(t, "061", "Customer Match List Health")
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Customer Match is the most durable first-party targeting signal. Verify lists exist, are large enough to serve, match well, are refreshed, and are actually applied (targeting, observation, exclusion, or as a lookalike seed). Missing or stale lists silently weaken Smart Bidding and remarketing.", L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Fetch CRM-based lists:** Size for search/display, match rate, membership status, eligibility
2. **Evaluate health:** Size, match rate, days since last upload
3. **Check coverage:** All-customers, high-value, recent and lapsed segments exist
4. **Check application:** Which campaigns use each list and in what mode; flag lists applied nowhere
5. **Recommend:** Refresh cadence, segment structure, and where to apply each list
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| No Customer Match lists in account | Critical |
| List size < 500 users | Critical |
| Match rate < 30% | Critical |
| Last updated > 90 days | Critical |
| Match rate 30-50% or list size 500-1,000 | Warning |
| Last updated 30-90 days | Warning |
| List applied to no campaign | Warning |
| No high-value, recent or lapsed segment | Info |
""", L)
    t = replace_once(t, "**Account:** [Name] | **Lists Analyzed:** [X] | **Issues:** [Y]",
                     "**Account:** [Name] | **Lists Analyzed:** [X] | **Applied:** [Y] | **Issues:** [Z]", L)
    t = replace_once(t, "- Recommended list types to add",
                     "- Recommended list types to add\n- Recommended list structure (all, high-value, recent, lapsed) and compliance checklist", L)
    return t


M.append(("skill-061-customer-match-list-freshness", "skill-061-customer-match-list-health", "skill-104-customer-match-list-management", m061))


# ------------------------------------------------------------------ 037 + 139
def m037(t: str) -> str:
    L = "037"
    t = set_frontmatter(t, "skill-037-ad-disapproval-monitoring",
                        "Find disapproved, limited, and under-review ads, prioritize by business impact (silenced ad groups, high-spend campaigns), and provide a resolution workflow.",
                        "skill-139-ad-disapproval-monitoring", "custom_gaql", L)
    t = set_title(t, "037", "Ad Disapproval Monitoring")
    t = set_data_source_line(t, "Custom GAQL Required\nStandard ads.md gives approval status; policy topic entries need the GAQL query.")
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Disapproved ads stop serving; limited ads serve in restricted contexts; ads stuck under review deliver nothing. Find every non-approved ad, extract the policy topic, size the impact (silenced ad groups, spend at risk), and order the fixes.", L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Categorize by approval status:** Approved, Approved Limited, Area of Interest Only, Disapproved, Under Review
2. **Extract policy topics:** For every non-approved ad; group repeated violations
3. **Assess impact:** Ad groups with 0 approved ads (silenced), high-spend campaigns affected, share of ads disapproved
4. **Prioritize resolution:** Silenced ad groups → high-spend campaigns → repeated violations → editorial quick fixes
5. **Plan remediation:** Fix or replace, appeal if wrong, keep 2-3 approved ads per ad group
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| Ad group with 0 approved ads | Critical |
| > 10% of ads disapproved | Critical |
| Disapproved ad in a campaign above {{spend_significant}}/30d | Critical |
| Any disapproved ad | Warning |
| Multiple ads with the same policy violation | Warning |
| Ad under review > 7 days | Warning |
| Limited eligibility or regional limitation affecting reach | Info |
| Ad under review 3-7 days | Info |
""", L)
    t = replace_once(t, "- Resolution priority queue with estimated fix time",
                     "- Resolution priority queue with estimated fix time\n- Resolution workflow by policy type, appeal guidance, prevention checklist", L)
    return t


M.append(("skill-037-ad-disapproval-limited-eligibility", "skill-037-ad-disapproval-monitoring", "skill-139-ad-disapproval-monitoring", m037))


# ------------------------------------------------------------------ 016 + 113
SEARCH_TERM_GAQL = """**Reference GAQL (search terms):**
```sql
SELECT
  campaign.name,
  ad_group.name,
  search_term_view.search_term,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.clicks > 0
ORDER BY metrics.cost_micros DESC
LIMIT 5000
```
"""


def m016(t: str) -> str:
    L = "016"
    t = set_frontmatter(t, "skill-016-negative-keyword-list-completeness",
                        "Verify shared negative lists exist, cover the universal waste categories, are applied to every campaign, and are backed by search-term evidence.",
                        "skill-113-proactive-negative-keyword-list-building", "standard", L)
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Shared negative lists are the cheapest waste prevention: build them proactively for universal waste (jobs, free, DIY, research, competitors), apply them everywhere, then confirm with search terms that nothing leaks through.", L)
    t = replace_once(t, "Use `/google-ads:get-custom` if you need detailed shared set membership.\n",
                     "Use `/google-ads:get-custom` if you need detailed shared set membership.\n\n" + SEARCH_TERM_GAQL, L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Inventory existing lists:** Names, keyword counts, campaign assignments
2. **Check universal categories:** Jobs/careers, free/DIY/tutorial, research/informational, support/login, competitor terms
3. **Verify application:** Every active Search and Shopping campaign has the universal list
4. **Gap analysis:** Search terms with waste patterns not blocked; high-spend zero-conversion terms
5. **Assess match types:** Phrase preferred; flag broad negatives (over-blocking risk)
6. **Recommend:** Universal (shared) vs campaign-specific negatives, with terms and match types
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| No shared negative lists exist | Critical |
| Universal waste category not covered (jobs, free/DIY, research, support) | Warning |
| Shared list not applied to all campaigns | Warning |
| Waste terms found in search terms not blocked | Warning |
| Zero-conversion terms with Cost >= {{spend_floor}} not blocked | Warning |
| Broad match negatives present | Info |
| < 50 negative keywords in total | Info |
""", L)
    t = replace_once(t, "**Account:** [Name] | **Shared Lists:** [X] | **Gaps:** [Y]",
                     "**Account:** [Name] | **Shared Lists:** [X] | **Total Negatives:** [Y] | **Gaps:** [Z]", L)
    t = replace_once(t, "- Recommended shared list structure",
                     "- Recommended shared list structure\n- Recommended universal list with match types", L)
    return t


M.append(("skill-016-negative-keyword-list-completeness", "skill-016-negative-keyword-list-completeness", "skill-113-proactive-negative-keyword-list-building", m016))


# ------------------------------------------------------------------ 064 + 129
def m064(t: str) -> str:
    L = "064"
    t = set_frontmatter(t, "skill-064-quality-score-distribution-analysis",
                        "Monitor Quality Score distribution, flag high-spend low-QS keywords with their weak component, and recommend monitoring alerts.",
                        "skill-129-quality-score-monitoring-alert-rules", "standard", L)
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Low Quality Scores raise CPCs and lower positions. Measure the distribution and impression-weighted average, isolate high-spend keywords at QS 1-5 with the component that drags them (expected CTR, ad relevance, landing page), quantify the spend exposed, and propose alert rules so regressions surface without a manual audit.", L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Load keyword QS data:** Quality Score and the three components per enabled keyword
2. **Calculate distribution:** Keywords by bucket (1-3, 4-5, 6-7, 8-10, N/A) and impression-weighted average (target > 6)
3. **Flag high-spend low QS:** Cost >= {{spend_significant}} at QS 1-3; Cost >= {{spend_material}} at QS 4-5
4. **Identify the weak component:** For every flagged keyword, which component is Below Average
5. **Quantify exposure:** Spend on QS 1-3 keywords as a share of total spend
6. **Recommend alert rules:** QS <= 3 with impressions > {{min_impressions}}; QS drop of 2+ points (operational follow-up)
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| Keyword QS 1-3 with Cost > {{spend_significant}}/30d | Critical |
| Keyword QS 1-3 with Impressions > {{min_impressions}} | Critical |
| > 20% of keywords have QS 1-3 | Critical |
| Weighted average QS < 5 | Critical |
| Keyword QS 4-5 with Cost > {{spend_material}}/30d | Warning |
| Any component Below Average on a keyword above {{spend_significant}}/30d | Warning |
| Weighted average QS 5-6 | Warning |
| QS dropped 2+ points vs previous snapshot (when history is available) | Warning |
""", L)
    t = replace_once(t, "- Estimated CPC savings from QS improvements",
                     "- Estimated CPC savings from QS improvements\n- Spend on low-QS keywords by bucket\n- Recommended alert rules (Google Ads automated rules configuration)", L)
    return t


M.append(("skill-064-quality-score-distribution-analysis", "skill-064-quality-score-distribution-analysis", "skill-129-quality-score-monitoring-alert-rules", m064))


# ------------------------------------------------------------------ 054 + 055
def m054(t: str) -> str:
    L = "054"
    t = set_frontmatter(t, "skill-054-geographic-performance-analysis",
                        "Analyze performance by location, recommend bid adjustments for strong and weak areas, and quantify exclusion candidates with zero or very poor conversion.",
                        "skill-055-underperforming-location-exclusion", "custom_gaql", L)
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Geographic performance varies widely. Compare each location to the account average, propose bid adjustments where volume supports it, and exclude locations that spend without converting or sit outside the service area. Quantify waste and projected savings so exclusions are defensible.", L)
    t = replace_once(t, "Run via `/google-ads:get-custom` with query name `geographic_performance`.\n",
                     "Run via `/google-ads:get-custom` with query name `geographic_performance`.\nFor the exclusion pass, filter to `metrics.cost_micros > 0` and load current exclusions from `bid_adjustments.md`.\n", L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Fetch location performance:** Custom GAQL plus current bid modifiers and exclusions
2. **Compute per-location metrics:** CPA, conversion rate, ROAS, cost share, conversion share vs account average
3. **Bid increases:** CPA well below average with >= {{min_conversions}} conversions
4. **Bid decreases:** CPA well above average with >= {{min_clicks}} clicks
5. **Exclusions:** Zero conversions above the spend floor, CPA > 3x average, CVR < 0.5x average with >= {{min_clicks}} clicks, outside the service area
6. **Quantify and prioritize:** 30-day waste, projected annual savings, high/medium/low priority
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| Location outside service area with any spend | Critical (exclude) |
| Zero conversions with Cost > {{spend_significant}} | Critical (exclude) |
| CPA 40%+ below average with >= {{min_conversions}} conversions | Critical (increase bid) |
| CPA > 3x account average with >= {{min_clicks}} clicks | High (exclude) |
| Zero conversions with Cost {{spend_floor}} to {{spend_significant}} | High (exclude) |
| CPA 50%+ above average | High (decrease bid) |
| CPA 20-40% below or 30-50% above average | Warning (moderate adjustment) |
| CVR < 0.5x average with >= {{min_clicks}} clicks | Warning |
""", L)
    t = replace_once(t, "**Account:** [Name] | **Locations Analyzed:** [X] | **Optimization Opportunities:** [Y]\n",
                     "**Account:** [Name] | **Locations Analyzed:** [X] | **Optimization Opportunities:** [Y]\n**Current Waste:** $[X]/month | **Projected Annual Savings:** $[Y]\n", L)
    t = replace_once(t, "- Exclusion recommendations table (location, cost, conversions, reason)",
                     "- Exclusion recommendations table (location, cost, conversions, reason)\n- Low priority review table (borderline cases to monitor)", L)
    return t


M.append(("skill-054-geographic-performance-analysis", "skill-054-geographic-performance-analysis", "skill-055-underperforming-location-exclusion", m054))


# ------------------------------------------------------------------ 029 + 126
AD_LEVEL_GAQL = """
**GAQL Query (ad-level metrics):**
```sql
SELECT
  campaign.name,
  ad_group.name,
  ad_group_ad.ad.responsive_search_ad.headlines,
  ad_group_ad.ad.responsive_search_ad.descriptions,
  ad_group_ad.policy_summary.approval_status,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM ad_group_ad
WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
  AND ad_group_ad.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
ORDER BY metrics.impressions DESC
```
Run via `/google-ads:get-custom` with query name `rsa_ad_performance`.
"""


def m029(t: str) -> str:
    L = "029"
    t = set_frontmatter(t, "skill-029-rsa-asset-performance-analysis",
                        "Rate RSA headlines and descriptions account-wide using Google's asset performance labels and ad-level metrics; replace Low assets with patterns from Best ones.",
                        "skill-126-rsa-asset-performance-bulk-analysis", "custom_gaql", L)
    t = replace_section(t, "## Purpose", "## Data Requirements",
        "Google labels each RSA asset Best, Good, Low, or Learning. Aggregate labels and ad-level performance across the account to find assets to replace, patterns to replicate, and ads whose strength or pinning limits combinations.", L)
    t = replace_once(t, "Standard export does not include asset-level performance ratings.\n",
                     "Standard export does not include asset-level performance ratings.\n\n**Standard Data:**\n- `data/account/campaigns/*/*/ads.md` - RSA headlines, descriptions, ad strength\n", L)
    t = replace_once(t, "Run via `/google-ads:get-custom` with query name `asset_performance`.\n",
                     "Run via `/google-ads:get-custom` with query name `asset_performance`.\n" + AD_LEVEL_GAQL, L)
    t = replace_section(t, "## Analysis Steps", "## Thresholds", """
1. **Fetch asset labels and ad metrics:** Asset view for labels; ad_group_ad for RSA-level impressions, CTR, conversions, ad strength
2. **Categorize assets by label:** Best (replicate), Good (keep), Low (replace), Learning (wait), Unrated
3. **Aggregate across ads:** Assets reused in many ads; account-wide top and bottom performers
4. **Analyze patterns:** What Best assets share (benefit, CTA, length) that Low assets lack
5. **Flag ads:** Poor strength with spend, multiple Low assets, no Best headline, heavy pinning
6. **Generate replacements:** Based on Best patterns, keeping headline diversity
""", L)
    t = replace_section(t, "## Thresholds", "## Output", """
| Condition | Severity |
|-----------|----------|
| > 20% of assets rated Low | Critical |
| Low asset in a campaign above {{spend_significant}}/30d | Critical |
| Ad strength Poor with spend above {{spend_significant}}/30d | Critical |
| Multiple Low assets in one ad | Warning |
| Any asset rated Low | Warning |
| No Best-rated headline in an RSA | Warning |
| Heavy pinning (3+ pins) reducing combinations | Info |
| All assets Learning (new RSA, < {{min_impressions}} impressions) | Info |
""", L)
    t = replace_once(t, "- Campaign priority based on spend",
                     "- Campaign priority based on spend\n- Ad strength distribution and top-performing headlines account-wide\n- Pinning strategy assessment", L)
    return t


M.append(("skill-029-rsa-asset-performance-analysis", "skill-029-rsa-asset-performance-analysis", "skill-126-rsa-asset-performance-bulk-analysis", m029))


# ------------------------------------------------------------------ related links that pointed at renamed canonicals
RELATED_FIX = {
    "skill-135-top-of-page-rate-monitoring": ("skill-121-impression-share-lost-analysis", "skill-121-impression-share-loss-analysis"),
    "skill-156-first-party-data-collection-activation-strategy": ("skill-061-customer-match-list-freshness", "skill-061-customer-match-list-health"),
}


def main() -> int:
    for old, new, absorbed, edit in M:
        sh("git", "rm", "-r", "-q", str(ROOT / absorbed))
        if old != new:
            sh("git", "mv", str(ROOT / old), str(ROOT / new))
        p = ROOT / new / "SKILL.md"
        p.write_text(edit(p.read_text()))
        print(f"merged {absorbed} -> {new}")
    for skill, (old, new) in RELATED_FIX.items():
        p = ROOT / skill / "SKILL.md"
        p.write_text(replace_once(p.read_text(), old, new, skill))
        print(f"relinked {skill}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
