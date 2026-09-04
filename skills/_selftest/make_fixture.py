#!/usr/bin/env python3
"""Generate the self-test fixture: a synthetic Google Ads export with planted defects,
laid out per skills/_resources/DATA_CONTRACT.md, plus the client profile.
Idempotent. Run: python3 skills/_selftest/make_fixture.py
The expected findings live in fixture/expected.json (hand-written, versioned with this file)."""
import csv
import random
from pathlib import Path

FIX = Path(__file__).parent / "fixture"
OUT = FIX / "export"
(OUT / "custom").mkdir(parents=True, exist_ok=True)
random.seed(7)


def w(name, rows, folder=OUT):
    with open(folder / f"{name}.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)


# ---------------------------------------------------------------- account
w("account", [dict(customer_id="123-456-7890", name="Acme Demo Tools", currency_code="EUR", time_zone="Europe/Rome",
                   auto_tagging="true", conversion_tracking="enabled", date_range_start="2026-08-04", date_range_end="2026-09-02",
                   snapshot_date="2026-09-03", brand_terms="acme; acme tools", rates_format="fraction")])

# ---------------------------------------------------------------- campaigns
camps = [
    dict(id=1001, name="Search - Brand", status="ENABLED", channel_type="SEARCH", bidding_strategy_type="TARGET_CPA", target_cpa=20, target_roas="", daily_budget=30, shared_budget="false", search_partners="false", display_network="false", geo_targets="Italy", geo_target_method="PRESENCE", languages="it", ad_schedule="none", labels="brand"),
    dict(id=1002, name="Search - Generic Tools", status="ENABLED", channel_type="SEARCH", bidding_strategy_type="TARGET_CPA", target_cpa=40, target_roas="", daily_budget=50, shared_budget="false", search_partners="true", display_network="false", geo_targets="Italy", geo_target_method="PRESENCE_OR_INTEREST", languages="it", ad_schedule="none", labels="generic"),
    dict(id=1003, name="Search - Repair Services", status="ENABLED", channel_type="SEARCH", bidding_strategy_type="MAXIMIZE_CONVERSIONS", target_cpa="", target_roas="", daily_budget=25, shared_budget="false", search_partners="false", display_network="false", geo_targets="Italy", geo_target_method="PRESENCE", languages="it", ad_schedule="none", labels="generic"),
    dict(id=1004, name="Shopping - All Products", status="ENABLED", channel_type="SHOPPING", bidding_strategy_type="TARGET_ROAS", target_cpa="", target_roas=4.0, daily_budget=40, shared_budget="false", search_partners="false", display_network="false", geo_targets="Italy", geo_target_method="PRESENCE", languages="it", ad_schedule="none", labels="shopping"),
    dict(id=1005, name="PMax - Catalog", status="ENABLED", channel_type="PERFORMANCE_MAX", bidding_strategy_type="MAXIMIZE_CONVERSION_VALUE", target_cpa="", target_roas="", daily_budget=45, shared_budget="false", search_partners="", display_network="", geo_targets="Italy", geo_target_method="PRESENCE", languages="it", ad_schedule="none", labels="pmax"),
]
w("campaigns", camps)

# ---------------------------------------------------------------- ad groups
ags = [
    dict(id=2001, campaign_id=1001, campaign_name="Search - Brand", name="Brand core", status="ENABLED", type="STANDARD", default_cpc=0.5),
    dict(id=2002, campaign_id=1002, campaign_name="Search - Generic Tools", name="Cordless drills", status="ENABLED", type="STANDARD", default_cpc=0.9),
    dict(id=2003, campaign_id=1002, campaign_name="Search - Generic Tools", name="Mixed tools", status="ENABLED", type="STANDARD", default_cpc=0.8),  # defect: 35 keywords, many themes
    dict(id=2004, campaign_id=1003, campaign_name="Search - Repair Services", name="Repair service", status="ENABLED", type="STANDARD", default_cpc=1.1),
    dict(id=2005, campaign_id=1002, campaign_name="Search - Generic Tools", name="Angle grinders", status="ENABLED", type="STANDARD", default_cpc=0.9),  # defect: 2 keywords
]
w("ad_groups", ags)


def kw(kid, ag, text, mt, qs, url="https://acme-tools.example/"):
    a = next(x for x in ags if x["id"] == ag)
    comp = lambda q: "ABOVE_AVERAGE" if q >= 7 else ("AVERAGE" if q >= 5 else "BELOW_AVERAGE")
    return dict(id=kid, campaign_id=a["campaign_id"], campaign_name=a["campaign_name"], ad_group_id=ag, ad_group_name=a["name"],
                text=text, match_type=mt, status="ENABLED", quality_score=qs, expected_ctr=comp(qs), ad_relevance=comp(qs),
                landing_page_experience=comp(qs), final_url=url)


kws = [kw(3001, 2001, "acme", "EXACT", 9), kw(3002, 2001, "acme tools", "PHRASE", 8), kw(3003, 2001, "acme drill", "EXACT", 8)]
for i, (t, mt, q) in enumerate([("cordless drill", "PHRASE", 7), ("cordless drill 18v", "EXACT", 7), ("cordless drill set", "PHRASE", 6),
                                 ("best cordless drill", "BROAD", 5), ("cordless drill battery", "PHRASE", 6), ("cordless drill brushless", "EXACT", 7),
                                 ("cordless drill with case", "PHRASE", 6), ("acme drill", "EXACT", 8)]):  # last: brand keyword in non-brand campaign
    kws.append(kw(3101 + i, 2002, t, mt, q))
MIXED = [("hammer", 6), ("claw hammer", 5), ("circular saw blade", 3), ("saw blade 190mm", 3), ("garden hose 20m", 2), ("garden hose reel", 2),
         ("aluminium ladder", 4), ("step ladder", 4), ("paint roller", 3), ("paint brush set", 3), ("screwdriver set", 5), ("torx screwdriver", 4),
         ("workbench", 3), ("tool chest", 3), ("socket set", 4), ("wrench set", 4), ("pliers", 3), ("tape measure", 5), ("spirit level", 4), ("utility knife", 3),
         ("safety glasses", 2), ("work gloves", 2), ("extension cord", 3), ("drill bits", 6), ("masonry drill bit", 5), ("jigsaw", 4), ("sander", 4),
         ("heat gun", 3), ("glue gun", 3), ("chisel set", 3), ("hand saw", 3), ("hacksaw", 3), ("wheelbarrow", 2), ("pressure washer", 2), ("air compressor", 3)]
for i, (t, q) in enumerate(MIXED):
    kws.append(kw(3201 + i, 2003, t, random.choice(["BROAD", "PHRASE"]), q))
for i, (t, mt, q) in enumerate([("tool repair", "PHRASE", 7), ("drill repair near me", "EXACT", 6), ("power tool repair", "PHRASE", 7), ("tool repair service", "PHRASE", 6)]):
    kws.append(kw(3301 + i, 2004, t, mt, q))
kws += [kw(3401, 2005, "angle grinder", "PHRASE", 6), kw(3402, 2005, "angle grinder 125mm", "EXACT", 6)]
w("keywords", kws)


def ad(aid, ag, heads, descs, strength="GOOD"):
    a = next(x for x in ags if x["id"] == ag)
    return dict(id=aid, campaign_id=a["campaign_id"], campaign_name=a["campaign_name"], ad_group_id=ag, ad_group_name=a["name"], type="RESPONSIVE_SEARCH_AD",
                status="ENABLED", headlines=" | ".join(heads), descriptions=" | ".join(descs), pinned_positions="", final_url="https://acme-tools.example/",
                ad_strength=strength, approval_status="APPROVED", policy_topics="")


w("ads", [
    ad(4001, 2001, ["Acme Tools Official Store", "Acme Tools - Free Shipping", "Acme Drills & More"], ["Buy direct from Acme. Fast delivery in Italy.", "Official Acme store."], "EXCELLENT"),
    ad(4002, 2002, ["Cordless Drills 18V", "Brushless Cordless Drills", "Cordless Drill Sets"], ["Top brands, 2-year warranty.", "Cordless drills from 79 EUR."]),
    ad(4003, 2003, ["Power Tools Sale", "Pro Power Tools", "Save on Power Tools"], ["Big discounts on power tools this month.", "Free delivery over 99 EUR."], "POOR"),  # defect: copy ignores most themes
    ad(4004, 2004, ["Power Tool Repair Service", "Drill Repair Near You", "Tool Repair in 48h"], ["Certified technicians. Free quote.", "Repair or replace, you decide."]),
    ad(4005, 2005, ["Angle Grinders 125mm", "Pro Angle Grinders", "Angle Grinder Deals"], ["From 45 EUR. Fast shipping.", "Top brands in stock."]),
])

# ---------------------------------------------------------------- negatives (no brand negatives anywhere: defect for skill-002)
w("negative_keywords", [
    dict(text="cheap", match_type="PHRASE", level="campaign", campaign_id=1002, campaign_name="Search - Generic Tools", ad_group_id="", ad_group_name=""),
    dict(text="repair", match_type="PHRASE", level="campaign", campaign_id=1002, campaign_name="Search - Generic Tools", ad_group_id="", ad_group_name=""),
    dict(text="cheap", match_type="PHRASE", level="campaign", campaign_id=1003, campaign_name="Search - Repair Services", ad_group_id="", ad_group_name=""),
])
# shared list exists but is applied to the Brand campaign only (defect for skill-016; explains why waste terms still serve elsewhere)
w("shared_negative_lists", [dict(list_id=3001, name="Universal negatives", member_count=10,
                                 keywords="jobs (PHRASE); careers (PHRASE); salary (PHRASE); free (PHRASE); diy (PHRASE); tutorial (PHRASE); how to (PHRASE); login (PHRASE); support (PHRASE); torrent (PHRASE)",
                                 campaigns_applied="Search - Brand")])

# ---------------------------------------------------------------- conversion actions
w("conversion_actions", [
    dict(id=5001, name="Purchase", category="PURCHASE", status="ENABLED", type="WEBSITE", counting="ONE_PER_CLICK", include_in_conversions="true", primary_for_goal="true", value_settings="transaction-specific", attribution_model="DATA_DRIVEN", click_window_days=30, enhanced_conversions="true", last_conversion_date="2026-09-01"),
    dict(id=5002, name="Contact form", category="LEAD", status="ENABLED", type="WEBSITE", counting="ONE_PER_CLICK", include_in_conversions="true", primary_for_goal="true", value_settings="15 EUR", attribution_model="DATA_DRIVEN", click_window_days=30, enhanced_conversions="false", last_conversion_date="2026-08-30"),
    dict(id=5003, name="Page view /catalog", category="PAGE_VIEW", status="ENABLED", type="WEBSITE", counting="MANY_PER_CLICK", include_in_conversions="true", primary_for_goal="false", value_settings="0", attribution_model="LAST_CLICK", click_window_days=30, enhanced_conversions="false", last_conversion_date="2026-09-02"),  # defect for skill-070/076
])

# ---------------------------------------------------------------- metrics
cm = [
    dict(campaign_id=1001, campaign_name="Search - Brand", channel_type="SEARCH", impressions=12000, clicks=1800, cost=540.00, conversions=90, conversion_value=5400, ctr=0.15, avg_cpc=0.30, cpa=6.00, roas=10.0, search_impression_share=0.88, search_budget_lost_is=0.05, search_rank_lost_is=0.02, search_top_is=0.80, search_abs_top_is=0.60),
    dict(campaign_id=1002, campaign_name="Search - Generic Tools", channel_type="SEARCH", impressions=85000, clicks=3400, cost=2720.00, conversions=62, conversion_value=4960, ctr=0.04, avg_cpc=0.80, cpa=43.87, roas=1.82, search_impression_share=0.55, search_budget_lost_is=0.25, search_rank_lost_is=0.10, search_top_is=0.40, search_abs_top_is=0.20),  # defect: budget-lost 25% on a profitable campaign
    dict(campaign_id=1003, campaign_name="Search - Repair Services", channel_type="SEARCH", impressions=30000, clicks=900, cost=990.00, conversions=21, conversion_value=2100, ctr=0.03, avg_cpc=1.10, cpa=47.14, roas=2.12, search_impression_share=0.42, search_budget_lost_is=0.08, search_rank_lost_is=0.35, search_top_is=0.30, search_abs_top_is=0.12),  # defect: rank-lost 35%
    dict(campaign_id=1004, campaign_name="Shopping - All Products", channel_type="SHOPPING", impressions=60000, clicks=1500, cost=1050.00, conversions=45, conversion_value=5850, ctr=0.025, avg_cpc=0.70, cpa=23.33, roas=5.57, search_impression_share=0.30, search_budget_lost_is=0.12, search_rank_lost_is=0.40, search_top_is="", search_abs_top_is=""),
    dict(campaign_id=1005, campaign_name="PMax - Catalog", channel_type="PERFORMANCE_MAX", impressions=200000, clicks=2600, cost=1300.00, conversions=58, conversion_value=6960, ctr=0.013, avg_cpc=0.50, cpa=22.41, roas=5.35, search_impression_share="", search_budget_lost_is="", search_rank_lost_is="", search_top_is="", search_abs_top_is=""),
]
w("campaign_metrics", cm)
w("impression_share_loss", [dict(campaign_name=r["campaign_name"], campaign_id=r["campaign_id"], campaign_status="ENABLED",
                                 campaign_budget_amount=next(c["daily_budget"] for c in camps if c["id"] == r["campaign_id"]),
                                 impressions=r["impressions"], clicks=r["clicks"], cost=r["cost"], conversions=r["conversions"],
                                 search_impression_share=r["search_impression_share"], search_budget_lost_impression_share=r["search_budget_lost_is"],
                                 search_rank_lost_impression_share=r["search_rank_lost_is"], search_top_impression_share=r["search_top_is"],
                                 search_absolute_top_impression_share=r["search_abs_top_is"]) for r in cm if r["channel_type"] == "SEARCH"], OUT / "custom")

km = []
for k in kws:
    base = {2001: (900, 130, 0.30, 0.05), 2002: (2500, 110, 0.85, 0.02), 2003: (400, 12, 0.75, 0.005), 2004: (1200, 40, 1.10, 0.025), 2005: (1500, 60, 0.90, 0.02)}[k["ad_group_id"]]
    imp = int(base[0] * random.uniform(0.5, 1.5)); clk = int(base[1] * random.uniform(0.5, 1.5)); cost = round(clk * base[2] * random.uniform(0.8, 1.2), 2)
    conv = round(clk * base[3] * random.uniform(0.5, 1.5), 1)
    if k["text"] == "circular saw blade": cost, conv = 130.0, 0   # defect for skill-064: QS 3 with cost > spend_significant
    if k["text"] == "garden hose 20m": cost, conv = 110.0, 0
    km.append(dict(keyword_id=k["id"], text=k["text"], match_type=k["match_type"], campaign_name=k["campaign_name"], ad_group_name=k["ad_group_name"],
                   impressions=imp, clicks=clk, cost=cost, conversions=conv, conversion_value=round(conv * 80, 2), quality_score=k["quality_score"]))
w("keyword_metrics", km)


def st(term, ag, matched, mt, imp, clk, cost, conv, status="NONE"):
    a = next(x for x in ags if x["id"] == ag)
    return dict(search_term=term, campaign_id=a["campaign_id"], campaign_name=a["campaign_name"], ad_group_id=ag, ad_group_name=a["name"], matched_keyword=matched,
                match_type=mt, added_excluded=status, impressions=imp, clicks=clk, cost=cost, conversions=conv, conversion_value=conv * 80)


sts = [
    st("acme", 2001, "acme", "EXACT", 5000, 900, 270.0, 50, "ADDED"), st("acme tools", 2001, "acme tools", "PHRASE", 3000, 500, 150.0, 25, "ADDED"),
    st("acme drill", 2001, "acme drill", "EXACT", 1500, 250, 75.0, 10, "ADDED"), st("acme tools shop", 2001, "acme tools", "PHRASE", 900, 120, 36.0, 5),
    st("free cordless drill", 2002, "cordless drill", "PHRASE", 900, 65, 130.0, 0),             # Critical: >= 3 x tCPA 40, conv 0, waste pattern
    st("cordless drill jobs", 2002, "cordless drill", "BROAD", 300, 18, 27.0, 0),              # Warning: waste pattern
    st("cordless drill 18v review", 2002, "best cordless drill", "BROAD", 1400, 52, 93.6, 0),   # Warning: >= 2 x tCPA
    st("drill", 2002, "cordless drill", "PHRASE", 3200, 25, 42.5, 0),                           # Warning: 3,200 impressions, CTR 0.78%, conv 0
    st("best cordless drill 18v", 2002, "best cordless drill", "BROAD", 2100, 110, 99.0, 4),
    st("cordless drill brushless 18v", 2002, "cordless drill brushless", "EXACT", 800, 60, 51.0, 3),
    st("acme cordless drill", 2002, "cordless drill", "PHRASE", 400, 40, 20.0, 3),              # brand term in non-brand campaign: 1.2% of campaign clicks, under 5%
    st("cordless drill set 18v", 2002, "cordless drill set", "PHRASE", 1200, 70, 59.5, 2, "ADDED"),
    st("tool repair jobs", 2004, "tool repair", "PHRASE", 150, 12, 14.0, 0),                     # Warning: waste pattern
    st("how to repair a drill", 2004, "drill repair near me", "EXACT", 600, 30, 33.0, 0),         # Warning: waste pattern
    st("power tool repair milan", 2004, "power tool repair", "PHRASE", 700, 45, 49.5, 2),
    st("drill repair near me", 2004, "drill repair near me", "EXACT", 500, 38, 41.8, 2, "ADDED"),
    st("angle grinder 125mm", 2005, "angle grinder 125mm", "EXACT", 1300, 55, 49.5, 1, "ADDED"),
]
for t, q in MIXED[:20]:
    sts.append(st(f"{t} online", 2003, t, "BROAD", random.randint(80, 400), random.randint(3, 15), round(random.uniform(2, 14), 2), random.choice([0, 0, 0, 1])))
w("search_terms", sts)

(FIX / "profile.yaml").write_text("""slug: acme-demo
report_language: en
market: [IT]
currency_override: null
target_cpa: null          # campaign-level targets are in export/campaigns.csv
target_roas: null
monthly_spend: null       # computed from export/campaign_metrics.csv
brand_terms: [acme, acme tools]
export_path: export/
parameter_overrides: {}
""")
print(f"fixture written to {OUT}: {len(camps)} campaigns, {len(ags)} ad groups, {len(kws)} keywords, {len(sts)} search terms")
