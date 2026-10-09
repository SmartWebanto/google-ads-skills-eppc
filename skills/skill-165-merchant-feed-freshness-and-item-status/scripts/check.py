"""check.py — skill-165 deterministic Merchant Center item status, spend exposure and feed freshness.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-165-merchant-feed-freshness-and-item-status/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #119 Disapproved Products Alerts (nilsrooijmans.com) — clean-room reimplementation of
         "disapproved Shopping-destination items that received clicks in the window" as spend-gated findings;
         index #118 Shopping Feed Update Frequency (nilsrooijmans.com) — its hourly fetchnow mutation becomes a
         change-frequency-vs-schedule check plus an owner proposal, never an executed fetch;
         index #70 PMax Disapproved Entities Alerts (nilsrooijmans.com) — partial: product listings served by PMax only;
         index #116 Fetch Merchant Center feeds (gist marthijnhoiting) — input only: feed fetch timestamps/status.
rules:   Read-only: never triggers feed fetches, edits feeds or campaigns; Merchant data comes from supplied files.
         Status vocabulary is closed (approved|limited|disapproved|pending); anything else is 'unknown', never guessed.
         Conflicting statuses for one product key exclude that key and mark the check partial.
         Spend on items disapproved at the snapshot is historical exposure, never loss/savings; an offer joins
         status once (by offer_id [+ target_country]) so one-to-many status rows never multiply cost.
         Warning for a disapproved item needs campaign item cost >= spend_significant resolved for THAT campaign.
         Critical only via review outcome 'material_intended_blocked' whose proposal.evidence_ref is present.
         Timestamps: ISO 8601; mixed naive/aware pairs are undecidable (coverage), never coerced.
         Ads destinations default to Shopping ads/Shopping; profile.merchant_ads_destinations overrides.
         profile.feed_mismatch_issue_codes (client-declared list) is the only source of 'mismatch' issue codes.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes2 | new recipe deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-165-merchant-feed-freshness-and-item-status"
VERSION = "1.0.0"

ST = "external/merchant_item_status"
DG = "external/merchant_diagnostics"
PD = "custom/product_daily"
FD = "external/merchant_feeds"
CH = "external/catalog_changes"
KEY = ("merchant_id", "offer_id", "target_country", "destination")
KEY_OPT = ("channel", "content_language", "feed_label")
STATUSES = ("approved", "limited", "disapproved", "pending")
PRODUCT_CHANNELS = ("SHOPPING", "PERFORMANCE_MAX")
STALE_INTERVALS = 2
EXPIRY_DAYS = 7
SAMPLE = 10


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _alnum(v) -> str:
    return re.sub(r"[^a-z0-9]", "", _s(v).lower())


def _dt(v) -> datetime | None:
    """ISO 8601 datetime or date → datetime; aware values are converted to UTC. Unparseable → None."""
    s = _s(v)
    if not s or s.lower() in V.MISSING_TOKENS:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else d


def _hours(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None or (later.tzinfo is None) != (earlier.tzinfo is None):
        return None
    return (later - earlier).total_seconds() / 3600


def _ads_destinations(ctx) -> set[str]:
    raw = ctx.profile.get("merchant_ads_destinations")
    vals = raw if isinstance(raw, list) else V.split_list(raw, (";", "|", ","))
    return {_alnum(v) for v in vals if _alnum(v)} or {"shoppingads", "shopping"}


def _item_key(row: dict, cols: list[str]) -> tuple:
    return tuple(_s(row.get(c)) for c in KEY) + tuple(_s(row.get(c)) for c in KEY_OPT if c in cols)


def _load_items(ctx, check) -> dict[tuple, dict]:
    """Deduplicated status rows by product key; conflicting statuses are excluded (partial)."""
    t = ctx.table(ST)
    items: dict[tuple, dict] = {}
    conflicts: set[tuple] = set()
    for r in t.rows:
        k = _item_key(r, t.columns)
        st = _s(r.get("status")).lower()
        st = st if st in STATUSES else "unknown"
        row = {**r, "_status": st}
        if k in items and items[k]["_status"] != st:
            conflicts.add(k)
        items.setdefault(k, row)
    for k in conflicts:
        items.pop(k, None)
    if conflicts:
        check.partial(f"{len(conflicts)} product keys with conflicting statuses excluded",
                      [f"{ST}:status"])
    return items


def run(ctx) -> None:
    """Run Merchant item-status, freshness, disapproved-spend and issue-code checks from supplied files.

    Rules:   Closed status vocabulary; others 'unknown'. Conflicting statuses exclude the key + partial; mixed tz →
             coverage. Disapproved-item Warning needs campaign item cost >= spend_significant for THAT campaign; spend
             is historical exposure, never loss. Issue-code meaning → ai_review; Critical only via
             'material_intended_blocked' with proposal.evidence_ref. Mismatch codes only from
             profile.feed_mismatch_issue_codes; never triggers fetches.
    """
    ads_dest = _ads_destinations(ctx)
    items: dict[tuple, dict] = {}

    # -- step 1: catalog status per destination/country
    cat = ctx.check("catalog_status", "Item status by destination and country",
                    {ST: ["merchant_id", "offer_id", "target_country", "destination", "status", "snapshot_at"]})
    if cat.runnable:
        items = _load_items(ctx, cat)
        certified = ctx.table(ST).complete is True
        groups: dict[tuple, dict] = {}
        for k in sorted(items):
            r = items[k]
            g = groups.setdefault((_s(r.get("destination")), _s(r.get("target_country"))),
                                  {s: 0 for s in STATUSES + ("unknown",)} | {"snapshots": set(), "offers": {}})
            g[r["_status"]] += 1
            g["snapshots"].add(_s(r.get("snapshot_at")))
            g["offers"].setdefault(r["_status"], []).append(_s(r.get("offer_id")))
        unknown = sum(g["unknown"] for g in groups.values())
        if unknown:
            cat.partial(f"{unknown} items with status outside {list(STATUSES)} counted as unknown")
        for (dest, country), g in sorted(groups.items()):
            known = sum(g[s] for s in STATUSES)
            counts = {s: g[s] for s in STATUSES + ("unknown",)}
            cat.observe(f"Status counts for destination {dest} / {country}", destination=dest,
                        target_country=country, known_status_items=known, **counts,
                        disapproved_share=V.ratio(g["disapproved"], known), certified_complete=certified)
            for cond, st in (("destination_items_disapproved", "disapproved"), ("destination_items_limited", "limited")):
                if not g[st]:
                    continue
                cat.finding(cond, "Info", {"destination": dest, "target_country": country},
                            f"{g[st]} of {known} known-status items are {st} for {dest} / {country}",
                            evidence={"counts": counts, "snapshot_at": sorted(g["snapshots"]),
                                      "sample_offer_ids": sorted(g["offers"][st])[:SAMPLE],
                                      "snapshot_certified_complete": certified},
                            calculation={"numerator": g[st], "denominator": known,
                                         "share": V.ratio(g[st], known), "formula": f"{st} / known-status items"},
                            recommendation="Prioritize by recent spend (spend_on_affected_items) and issue code; "
                                           "ask the feed owner for corrections.",
                            uncertainty="Share of supplied rows only unless the manifest certifies the full snapshot."
                                        if not certified else "Snapshot status only; no delivery impact implied.")

    # -- step 2: issue codes by destination, policy meaning via review
    iss = ctx.check("issue_codes", "Item issues by issue code and destination",
                    {DG: ["merchant_id", "offer_id", "target_country", "destination", "issue_code", "platform_severity"]})
    mismatch_codes = {_alnum(c) for c in (ctx.profile.get("feed_mismatch_issue_codes") or []) if _alnum(c)}
    mismatch_offers: set[str] = set()
    if iss.runnable:
        seen: set[tuple] = set()
        by_code: dict[tuple, set] = {}
        texts: dict[str, set] = {}
        attrs: dict[str, set] = {}
        for r in sorted(ctx.rows(DG), key=lambda r: tuple(_s(r.get(c)) for c in KEY + ("issue_code",))):
            k = tuple(_s(r.get(c)) for c in KEY) + (_s(r.get("issue_code")),)
            if k in seen:
                continue
            seen.add(k)
            sev = _s(r.get("platform_severity")).lower()
            code = _s(r.get("issue_code"))
            by_code.setdefault((code, _s(r.get("destination")), sev), set()).add(k[:3])
            if r.get("issue_text"):
                texts.setdefault(code, set()).add(_s(r.get("issue_text")))
            if r.get("attribute"):
                attrs.setdefault(code, set()).add(_s(r.get("attribute")))
            if _alnum(code) in mismatch_codes and sev in ("disapproved", "demoted"):
                mismatch_offers.add(_s(r.get("offer_id")))
        disapproving: dict[str, dict] = {}
        for (code, dest, sev), keys in sorted(by_code.items()):
            iss.observe(f"Issue {code} on {dest} ({sev or 'unknown severity'})", issue_code=code, destination=dest,
                        platform_severity=sev, distinct_items=len(keys))
            if sev == "disapproved":
                disapproving.setdefault(code, {})[dest] = sorted(keys)
        for code, per_dest in sorted(disapproving.items()):
            offers = sorted({k[1] for keys in per_dest.values() for k in keys})
            iss.review("issue_code_policy_meaning", {"issue_code": code},
                       f"Does issue code '{code}' signal a Merchant Center policy violation, or a data/attribute fix?",
                       evidence={"items_by_destination": {d: len(v) for d, v in per_dest.items()},
                                 "issue_texts": sorted(texts.get(code, ()))[:3],
                                 "attributes": sorted(attrs.get(code, ())), "sample_offer_ids": offers[:SAMPLE]},
                       outcomes={
                           "policy_violation": {"severity": "Warning", "recommendation":
                                                "Route to the policy owner; confirm the policy and the correction/appeal path."},
                           "data_fix": {"severity": "Info", "recommendation":
                                        "Feed-owner data correction; attribute completeness is owned by skill-083."},
                           "uncertain": {"severity": "Info", "recommendation":
                                         "Ask the Merchant Center owner for the issue documentation."},
                       },
                       guidance="Judge only from the issue code, issue text and cited Merchant Center documentation. "
                                "Do not infer account-level suspension risk without an account-level issue.")
        if not mismatch_codes:
            iss.observe("profile.feed_mismatch_issue_codes not declared: no issue treated as a feed/site mismatch")

    # -- step 3: recent Shopping/PMax spend on affected items
    sp = ctx.check("spend_on_affected_items", "Recent Shopping/PMax spend on disapproved and limited items",
                   {PD: ["campaign_id", "offer_id", "date", "clicks", "cost"], "campaigns": ["id", "channel_type"],
                    ST: ["merchant_id", "offer_id", "target_country", "destination", "status", "snapshot_at"]})
    if sp.runnable:
        _spend(ctx, sp, items if cat.runnable else _load_items(ctx, sp), ads_dest)

    # -- step 4: feed freshness vs declared schedule
    fr = ctx.check("feed_freshness", "Feed last fetch vs declared schedule",
                   {FD: ["merchant_id", "feed_id", "fetch_interval_hours", "last_fetch_at", "last_fetch_status",
                         "snapshot_at"]})
    intervals: dict[str, float] = {}
    if fr.runnable:
        intervals = _freshness(ctx, fr)

    # -- step 5: price/availability change frequency vs schedule
    cf = ctx.check("change_frequency_vs_schedule", "Price/availability change frequency vs fetch schedule",
                   {CH: ["offer_id", "field", "changed_at"], FD: ["feed_id", "fetch_interval_hours"],
                    ST: ["offer_id", "feed_id"]})
    if cf.runnable:
        if not fr.runnable:
            intervals = {_s(r.get("feed_id")): V.num(r.get("fetch_interval_hours")) for r in ctx.rows(FD)}
        _change_frequency(ctx, cf, intervals, mismatch_codes, mismatch_offers, iss.runnable)

    # -- step 6: expiring items
    ex = ctx.check("expiring_items", "Items expiring within 7 days of the snapshot",
                   {ST: ["merchant_id", "offer_id", "target_country", "destination", "status", "snapshot_at",
                         "expiration_date"]})
    if ex.runnable:
        _expiring(ctx, ex, items if cat.runnable else _load_items(ctx, ex))


def _spend(ctx, sp, items: dict, ads_dest: set[str]) -> None:
    has_country = "target_country" in ctx.table(PD).columns
    status_by: dict[tuple, set] = {}
    for r in items.values():
        if _alnum(r.get("destination")) not in ads_dest:
            continue
        status_by.setdefault((_s(r.get("offer_id")), _s(r.get("target_country"))), set()).add(r["_status"])
        status_by.setdefault((_s(r.get("offer_id")), None), set()).add(r["_status"])
    if not status_by:
        sp.partial(f"no status rows for ads destinations {sorted(ads_dest)}", [f"{ST}:destination"])
    if not has_country:
        sp.partial("product_daily has no target_country: an offer counts as affected if disapproved in ANY country",
                   [f"{PD}:target_country"])
    channel = {_s(c.get("id")): _s(c.get("channel_type")).upper() for c in ctx.rows("campaigns")}
    start, end = ctx.period_start, ctx.period_end
    if start is None or end is None:
        sp.partial("report period unknown: every dated row used")
    agg: dict[tuple, list] = {}
    unknown_campaign, bad_rows, out_of_period = set(), 0, 0
    for r in ctx.rows(PD):
        cid = _s(r.get("campaign_id"))
        if cid not in channel:
            unknown_campaign.add(cid)
            continue
        if channel[cid] not in PRODUCT_CHANNELS:
            continue
        d = V.parse_date(r.get("date"))
        cost, clicks = ctx.money(r.get("cost")), V.num(r.get("clicks"))
        if d is None or cost is None or clicks is None:
            bad_rows += 1
            continue
        if start and end and not (start <= d <= end):
            out_of_period += 1
            continue
        k = (cid, _s(r.get("offer_id")), _s(r.get("target_country")) if has_country else None)
        acc = agg.setdefault(k, [0.0, 0.0])
        acc[0] += cost
        acc[1] += clicks
    if unknown_campaign:
        sp.partial(f"{len(unknown_campaign)} campaign ids not in campaigns inventory: channel unknown",
                   ["campaigns:id"])
    if bad_rows:
        sp.partial(f"{bad_rows} product rows with unknown date/cost/clicks excluded")
    per_camp: dict[str, dict] = {}
    minor: dict[str, list] = {}
    unresolved: dict[str, str] = {}
    unmatched = 0
    for (cid, offer, country), (cost, clicks) in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")):
        c = per_camp.setdefault(cid, {"total_cost": 0.0, "disapproved_cost": 0.0, "limited_cost": 0.0,
                                      "unmatched_cost": 0.0, "offers": 0, "disapproved_offers": 0})
        c["total_cost"] += cost
        c["offers"] += 1
        sts = status_by.get((offer, country))
        if not sts:
            unmatched += 1
            c["unmatched_cost"] += cost
            continue
        if "disapproved" not in sts:
            if "limited" in sts:
                c["limited_cost"] += cost
            continue
        c["disapproved_cost"] += cost
        c["disapproved_offers"] += 1
        floor = ctx.params.get("spend_significant", cid)
        entity = {"campaign_id": cid, "offer_id": offer, "target_country": country}
        ev = {"cost": cost, "clicks": clicks, "window": [start, end], "statuses_ads_destinations": sorted(sts),
              "spend_significant": floor.value, "spend_significant_source": floor.source}
        if floor.value is None:
            unresolved[cid] = floor.reason
            continue
        if cost < floor.value:
            if cost > 0 or clicks > 0:
                minor.setdefault(cid, []).append({"offer_id": offer, "target_country": country,
                                                  "cost": cost, "clicks": clicks})
            continue
        prov = sp.finding("disapproved_item_recent_spend", "Warning", entity,
                          f"Offer {offer} is disapproved for an ads destination and cost {cost:.2f} {ctx.currency} "
                          f"in campaign {cid} during the period (spend_significant {floor.value:g})",
                          evidence=ev, calculation={"numerator": cost, "threshold": floor.value,
                                                    "rule": "item cost >= spend_significant(campaign)"},
                          recommendation="Ask the feed owner to fix the disapproval issue; confirm the item is "
                                         "intended to sell before prioritizing.",
                          uncertainty="Snapshot status vs period spend: cost is historical exposure while eligible, "
                                      "not lost revenue.")
        sp.review("disapproved_item_recent_spend", entity,
                  f"Is offer {offer} intended to sell in campaign {cid}, and is its blocked delivery a material loss?",
                  evidence=ev, provisional=prov,
                  outcomes={
                      "material_intended_blocked": {"severity": "Critical", "recommendation":
                                                    "Prioritize the fix; cite the stock/intent and impact evidence."},
                      "intended_blocked": {"severity": "Warning", "recommendation": "Fix the disapproval in the feed."},
                      "not_intended": {"severity": None, "recommendation":
                                       "No action: item discontinued or deliberately withdrawn."},
                      "uncertain": {"severity": "Warning", "recommendation": "Ask the merchant whether the item sells."},
                  },
                  guidance="Critical requires proposal.evidence_ref to supplied stock/intent and impact evidence; "
                           "spend history alone is not material loss.")
    for cid, rows in sorted(minor.items()):
        sp.finding("disapproved_items_minor_spend", "Info", {"campaign_id": cid},
                   f"{len(rows)} disapproved offers had spend below spend_significant in campaign {cid}",
                   evidence={"offers": sorted(rows, key=lambda x: (-x["cost"], x["offer_id"]))[:SAMPLE],
                             "window": [start, end]},
                   calculation={"count": len(rows), "cost": sum(x["cost"] for x in rows)},
                   recommendation="Include in the next feed correction batch.",
                   uncertainty="Below the materiality screen; historical exposure only.")
    for cid, reason in sorted(unresolved.items()):
        sp.partial(f"spend_significant unresolved for campaign {cid}: {reason}")
    if unmatched:
        sp.partial(f"{unmatched} campaign/offer rows have no ads-destination status in the snapshot")
    for cid, c in sorted(per_camp.items()):
        sp.observe(f"Campaign {cid}: product spend share on affected items", campaign_id=cid,
                   channel_type=channel.get(cid), window=[start, end], **c,
                   disapproved_cost_share=V.ratio(c["disapproved_cost"], c["total_cost"]),
                   limited_cost_share=V.ratio(c["limited_cost"], c["total_cost"]))
    if out_of_period:
        sp.observe("Product rows outside the report period ignored", rows=out_of_period)


def _freshness(ctx, fr) -> dict[str, float]:
    feeds: dict[tuple, dict] = {}
    dup = set()
    for r in ctx.rows(FD):
        k = (_s(r.get("merchant_id")), _s(r.get("feed_id")))
        if k in feeds:
            dup.add(k)
        feeds.setdefault(k, r)
    for k in dup:
        feeds.pop(k)
    if dup:
        fr.partial(f"{len(dup)} feeds with duplicate rows excluded")
    intervals: dict[str, float] = {}
    for (mid, fid), r in sorted(feeds.items()):
        entity = {"merchant_id": mid, "feed_id": fid}
        interval = V.num(r.get("fetch_interval_hours"))
        if interval is not None and interval > 0:
            intervals[fid] = interval
        snap, last = _dt(r.get("snapshot_at")), _dt(r.get("last_fetch_at"))
        age = _hours(snap, last)
        upd_age = _hours(snap, _dt(r.get("last_update_at")))
        status = _s(r.get("last_fetch_status")).lower()
        ev = {"feed_name": r.get("feed_name"), "fetch_interval_hours": interval, "last_fetch_at": r.get("last_fetch_at"),
              "last_fetch_status": status or None, "snapshot_at": r.get("snapshot_at"), "age_hours": age,
              "last_update_at": r.get("last_update_at"), "update_age_hours": upd_age}
        if V.boolean(r.get("paused")) is True:
            fr.finding("feed_schedule_paused", "Info", entity, f"Feed {fid} fetch schedule is paused",
                       evidence=ev, recommendation="Confirm the feed is updated by another route (API/upload).",
                       uncertainty="Paused schedule alone does not prove stale items.")
            continue
        if status == "failure":
            fr.finding("feed_fetch_failed", "Warning", entity, f"Last fetch of feed {fid} failed ({r.get('last_fetch_at')})",
                       evidence=ev, recommendation="Ask the feed owner to fix the fetch source and request a manual fetch.",
                       uncertainty="Items keep their previous data until expiry; affected items are not identified here.")
        elif status != "success":
            fr.partial(f"feed {fid}: last_fetch_status '{status}' not success|failure")
        if interval is None or interval <= 0:
            fr.partial(f"feed {fid}: fetch_interval_hours unknown", [f"{FD}:fetch_interval_hours"])
            continue
        if age is None or age < 0:
            fr.partial(f"feed {fid}: fetch age undecidable (timestamps unparseable, mixed zones or future)")
            continue
        limit = STALE_INTERVALS * interval
        if age > limit:
            fr.finding("feed_stale", "Warning", entity,
                       f"Feed {fid} last fetched {age:.1f}h before the snapshot, over {STALE_INTERVALS}x its "
                       f"{interval:g}h schedule", evidence=ev,
                       calculation={"age_hours": age, "limit_hours": limit, "rule": "age > 2 x declared interval"},
                       recommendation="Ask the feed owner why scheduled fetches stopped; request a manual fetch.",
                       uncertainty="Heuristic cutoff; the source file itself may still be current.")
        else:
            fr.observe(f"Feed {fid} fetched within {STALE_INTERVALS} declared intervals", feed_id=fid,
                       age_hours=age, limit_hours=limit)
    return intervals


def _change_frequency(ctx, cf, intervals, mismatch_codes, mismatch_offers, issues_ok) -> None:
    feeds_of: dict[str, set] = {}
    for r in ctx.rows(ST):
        if r.get("feed_id"):
            feeds_of.setdefault(_s(r.get("offer_id")), set()).add(_s(r.get("feed_id")))
    start, end = ctx.period_start, ctx.period_end
    if start is None or end is None:
        cf.partial("report period unknown: every change row used")
    changes: set[tuple] = set()
    bad = 0
    for r in ctx.rows(CH):
        field = _s(r.get("field")).lower()
        if field not in ("price", "availability"):
            continue
        t = _dt(r.get("changed_at"))
        if t is None:
            bad += 1
            continue
        if start and end and not (start <= t.date() <= end):
            continue
        changes.add((_s(r.get("offer_id")), field, t))
    if bad:
        cf.partial(f"{bad} change rows with unparseable changed_at excluded")
    per_day: dict[tuple, int] = {}
    for offer, _field, t in changes:
        per_day[(offer, t.date())] = per_day.get((offer, t.date()), 0) + 1
    max_day: dict[str, int] = {}
    for (offer, _d), n in per_day.items():
        max_day[offer] = max(max_day.get(offer, 0), n)
    unmapped = sorted(o for o in max_day if o not in feeds_of)
    if unmapped:
        cf.partial(f"{len(unmapped)} changed offers have no feed_id in the status snapshot")
    if not mismatch_codes:
        cf.partial("profile.feed_mismatch_issue_codes not declared: Warning path not evaluated")
    elif not issues_ok:
        cf.partial("merchant_diagnostics unavailable: Warning path not evaluated", [f"{DG} (file)"])
    feed_offers: dict[str, set] = {}
    for offer, fids in feeds_of.items():
        for fid in fids:
            feed_offers.setdefault(fid, set()).add(offer)
    for fid in sorted(feed_offers):
        interval = intervals.get(fid)
        if interval is None or interval <= 0:
            cf.partial(f"feed {fid}: fetch_interval_hours unknown")
            continue
        per_day_fetches = 24 / interval
        fast = sorted(o for o in feed_offers[fid] if max_day.get(o, 0) > per_day_fetches)
        changed = sorted(o for o in feed_offers[fid] if o in max_day)
        cf.observe(f"Feed {fid}: offers changing faster than scheduled fetches", feed_id=fid,
                   fetches_per_day=per_day_fetches, offers_in_feed=len(feed_offers[fid]),
                   offers_with_changes=len(changed), offers_exceeding=len(fast))
        if not fast:
            continue
        hits = sorted(o for o in feed_offers[fid] if o in mismatch_offers)
        ev = {"fetch_interval_hours": interval, "fetches_per_day": per_day_fetches,
              "sample_offers": [{"offer_id": o, "max_changes_in_a_day": max_day[o]} for o in fast[:SAMPLE]],
              "mismatch_issue_offers": hits[:SAMPLE], "window": [start, end]}
        calc = {"numerator": len(fast), "denominator": len(feed_offers[fid]),
                "rule": "max daily price/availability changes > 24 / fetch_interval_hours"}
        if hits and mismatch_codes and issues_ok:
            cf.finding("change_frequency_with_mismatch_issues", "Warning", {"feed_id": fid},
                       f"{len(fast)} offers in feed {fid} change more often than its {interval:g}h schedule and "
                       f"{len(hits)} offers carry a declared mismatch issue", evidence=ev, calculation=calc,
                       recommendation="Propose a more frequent schedule or supplemental price/availability updates "
                                      "to the feed owner; do not trigger fetches from Ads scripts without approval.",
                       uncertainty="Co-occurrence, not proven cause; mismatch codes are client-declared.")
        else:
            cf.finding("change_frequency_exceeds_schedule", "Info", {"feed_id": fid},
                       f"{len(fast)} offers in feed {fid} change more often than its {interval:g}h schedule",
                       evidence=ev, calculation=calc,
                       recommendation="Consider a more frequent schedule or supplemental updates with the feed owner.",
                       uncertainty="No declared mismatch issue on this feed; serving impact not evidenced.")


def _expiring(ctx, ex, items: dict) -> None:
    groups: dict[tuple, dict] = {}
    bad = 0
    for k in sorted(items):
        r = items[k]
        snap = _dt(r.get("snapshot_at"))
        exp = _dt(r.get("expiration_date"))
        g = groups.setdefault((_s(r.get("destination")), _s(r.get("target_country"))),
                              {"items": 0, "expiring": [], "expired": 0, "unknown": 0})
        g["items"] += 1
        if snap is None or exp is None:
            g["unknown"] += 1
            bad += snap is None
            continue
        days = (exp.date() - snap.date()).days
        if days < 0:
            g["expired"] += 1
        elif days <= EXPIRY_DAYS:
            g["expiring"].append({"offer_id": _s(r.get("offer_id")), "expiration_date": _s(r.get("expiration_date"))})
    if bad:
        ex.partial(f"{bad} items with unparseable snapshot_at")
    unknown = sum(g["unknown"] for g in groups.values())
    if unknown:
        ex.partial(f"{unknown} items with unknown expiration_date/snapshot_at", [f"{ST}:expiration_date"])
    for (dest, country), g in sorted(groups.items()):
        ex.observe(f"Expiry profile for {dest} / {country}", destination=dest, target_country=country,
                   items=g["items"], expiring_within_7d=len(g["expiring"]), expired_before_snapshot=g["expired"],
                   unknown_expiry=g["unknown"])
        if g["expiring"]:
            ex.finding("items_expiring_soon", "Info", {"destination": dest, "target_country": country},
                       f"{len(g['expiring'])} of {g['items']} items for {dest} / {country} expire within "
                       f"{EXPIRY_DAYS} days of the snapshot",
                       evidence={"sample": sorted(g["expiring"], key=lambda x: (x["expiration_date"], x["offer_id"]))[:SAMPLE]},
                       calculation={"numerator": len(g["expiring"]), "denominator": g["items"],
                                    "rule": f"0 <= expiration_date - snapshot date <= {EXPIRY_DAYS} days"},
                       recommendation="Confirm the next feed update refreshes these items before expiry.",
                       uncertainty="A scheduled fetch normally refreshes expiry; this is a watch item.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'material_intended_blocked' (Critical) requires proposal.evidence_ref to supplied evidence."""
    if decision.get("outcome") == "material_intended_blocked" and not (decision.get("proposal") or {}).get("evidence_ref"):
        return ["Critical needs proposal.evidence_ref to supplied stock/intent and impact evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
