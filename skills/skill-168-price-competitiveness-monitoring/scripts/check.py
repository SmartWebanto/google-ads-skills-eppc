"""check.py — skill-168 deterministic item price monitoring from dated Merchant snapshots.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-168-price-competitiveness-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #74 PMax Product Price Alerts (nilsrooijmans.com, reference only; code not verified) — clean-room
         reimplementation of price-change alerting from supplied dated snapshots; no email, no sheet, no bid change
rules:   Prices are item-currency numbers (V.num), never ctx.money; rows with a different currency are
         excluded, never converted. Offer key = (offer_id, target_country); duplicate snapshot rows with
         differing values are dropped as conflicts.
         Effective price = sale_price when present and its window (open bounds allowed) contains the date, else price.
         Events compare consecutive price runs; the change day inside (last old, first new] is unknown.
         Alerts need profile.price_change_alert_pct / price_gap_alert_pct (positive fractions); unset → observations
         only + partial. Benchmark gap uses V.ratio; zero/missing benchmark is undefined.
         Page mismatch = same offer, country, currency and DATE snapshot, |page - feed| > 0.005; non-2xx skipped.
         Critical only via review 'disapproval_evidenced' when some campaign's offer spend >= its
         spend_significant AND verify sees proposal.evidence_ref.
         Before/after: equal length L (capped by profile.price_event_window_days) inside the report period and each
         price's observed span; product_daily summed once per date; days without rows are unknown unless the
         manifest certifies completeness.
         Rates only when ctx.mature is True and BOTH sides pass min_impressions/min_clicks/min_conversions.
         Descriptive only: no causal claims, no findings from before/after windows.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes3 | initial recipe check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-168-price-competitiveness-monitoring"
VERSION = "1.0.0"

SNAP = "external/merchant_price_snapshots"
PAGES = "external/landing_page_prices"
BENCH = "external/price_competitiveness"
DAILY = "custom/product_daily"
SNAP_COLS = ["snapshot_date", "offer_id", "target_country", "price", "currency"]
SALE_COLS = ["sale_price", "sale_start", "sale_end"]
DAILY_COLS = ["date", "campaign_id", "offer_id", "target_country", "impressions", "clicks", "cost", "conversions",
              "conversion_value"]
TOLERANCE = 0.005


def _key(r) -> tuple[str, str]:
    return str(r.get("offer_id") or "").strip(), str(r.get("target_country") or "").strip().upper()


def _cur(v) -> str:
    return str(v or "").strip().upper()


def _alert(ctx, name: str) -> float | None:
    f = V.num(ctx.profile.get(name))
    return f if f is not None and f > 0 else None


def _effective(price, sale, start, end, d):
    if sale is not None and (start is None or start <= d) and (end is None or d <= end):
        return sale, "sale_price"
    return price, "price"


def _snapshots(ctx) -> tuple[dict, list[str]]:
    """offer key -> date-sorted observations. Rules: identical same-date rows collapse; conflicting prices on one date are excluded and reported."""
    t = ctx.table(SNAP)
    has_sale = t is not None and not t.missing(SALE_COLS)
    raw: dict = {}
    bad = 0
    for r in t.rows if t else []:
        d, k = V.parse_date(r.get("snapshot_date")), _key(r)
        if d is None or not k[0]:
            bad += 1
            continue
        price = V.num(r.get("price"))
        sale = V.num(r.get("sale_price")) if has_sale else None
        start = V.parse_date(r.get("sale_start")) if has_sale else None
        end = V.parse_date(r.get("sale_end")) if has_sale else None
        eff, basis = _effective(price, sale, start, end, d)
        obs = {"date": d, "price": price, "sale_price": sale, "sale_start": start, "sale_end": end,
               "currency": _cur(r.get("currency")), "effective": eff, "basis": basis, "link": r.get("link")}
        raw.setdefault(k, {}).setdefault(d, []).append(obs)
    out: dict = {}
    conflicts = 0
    for k in sorted(raw):
        rows = []
        for d in sorted(raw[k]):
            variants = raw[k][d]
            if any(v != variants[0] for v in variants[1:]):
                conflicts += 1
                continue
            rows.append(variants[0])
        out[k] = rows
    notes = []
    if bad:
        notes.append(f"{bad} snapshot rows without parseable snapshot_date or offer_id")
    if conflicts:
        notes.append(f"{conflicts} offer/date snapshot duplicates with differing values excluded")
    return out, notes


def _runs(obs: list[dict]) -> list[dict]:
    """Consecutive observations with the same known effective price and currency."""
    runs: list[dict] = []
    for o in obs:
        last = runs[-1] if runs else None
        if last and o["effective"] is not None and last["price"] == o["effective"] and last["currency"] == o["currency"]:
            last["end"] = o["date"]
            last["n"] += 1
        else:
            runs.append({"price": o["effective"], "basis": o["basis"], "currency": o["currency"],
                         "start": o["date"], "end": o["date"], "n": 1})
    return runs


def _events(snaps: dict) -> tuple[list[dict], int]:
    events, breaks = [], 0
    for k in sorted(snaps):
        runs = _runs(snaps[k])
        for old, new in zip(runs, runs[1:]):
            if old["price"] is None or new["price"] is None:
                continue
            if old["currency"] != new["currency"]:
                breaks += 1
                continue
            change = new["price"] - old["price"]
            events.append({"offer_id": k[0], "target_country": k[1], "currency": old["currency"],
                           "old_price": old["price"], "new_price": new["price"], "change": change,
                           "relative_change": V.ratio(change, old["price"]),
                           "direction": "increase" if change > 0 else "decrease",
                           "old_basis": old["basis"], "new_basis": new["basis"],
                           "old_span": [old["start"], old["end"]], "new_span": [new["start"], new["end"]]})
    return events, breaks


def _daily(ctx, chk) -> tuple[dict, dict] | tuple[None, None]:
    """(offer key) -> date -> summed metrics; (offer key, campaign_id) -> cost in the report period."""
    t = ctx.table(DAILY)
    if t is None or t.missing(DAILY_COLS):
        return None, None
    lo, hi = ctx.period_start, ctx.period_end
    seen: set = set()
    dup_keys: set = set()
    rows = []
    for r in t.rows:
        d = V.parse_date(r.get("date"))
        if d is None or (lo and d < lo) or (hi and d > hi):
            continue
        k = _key(r)
        grain = (d, str(r.get("campaign_id") or ""), k)
        if grain in seen:
            dup_keys.add(k)
            continue
        seen.add(grain)
        rows.append((k, d, str(r.get("campaign_id") or ""), r))
    by_day: dict = {}
    by_camp: dict = {}
    for k, d, cid, r in sorted(rows, key=lambda x: (x[0], x[1], x[2])):
        if k in dup_keys:
            continue
        m = by_day.setdefault(k, {}).setdefault(d, {"impressions": 0.0, "clicks": 0.0, "cost": 0.0,
                                                    "conversions": 0.0, "conversion_value": 0.0, "unknown": 0})
        for col in ("impressions", "clicks", "conversions", "conversion_value"):
            v = V.num(r.get(col))
            if v is None:
                m["unknown"] += 1
            else:
                m[col] += v
        c = ctx.money(r.get("cost"))
        if c is None:
            m["unknown"] += 1
        else:
            m["cost"] += c
            by_camp[(k, cid)] = by_camp.get((k, cid), 0.0) + c
    if dup_keys and chk is not None:
        chk.partial(f"{len(dup_keys)} offers with duplicate date/campaign rows excluded (no double counting)")
    return by_day, by_camp


# ----------------------------------------------------------------------------- checks
def _check_events(ctx, snaps, notes) -> list[dict]:
    chk = ctx.check("price_change_events", "Effective price change events between dated snapshots", {SNAP: SNAP_COLS})
    if not chk.runnable:
        return []
    for n in notes:
        chk.partial(n)
    events, breaks = _events(snaps)
    if breaks:
        chk.partial(f"{breaks} consecutive snapshot pairs change currency: not compared (no conversion)")
    alert = _alert(ctx, "price_change_alert_pct")
    if alert is None:
        chk.partial("profile.price_change_alert_pct not set: events listed as observations, no alerts")
    for e in events:
        entity = {"offer_id": e["offer_id"], "target_country": e["target_country"], "first_new_date": e["new_span"][0]}
        rel = e["relative_change"]
        if alert is not None and rel is not None and abs(rel) >= alert:
            chk.finding("price_change_event", "Info", entity,
                        f"Offer {e['offer_id']} ({e['target_country']}) effective price {e['direction']} "
                        f"{e['old_price']:g} → {e['new_price']:g} {e['currency']} ({rel:+.1%})",
                        evidence=e, calculation={"relative_change": "(new - old) / old",
                                                 "alert_fraction": alert, "alert_source": "profile.price_change_alert_pct"},
                        recommendation="Confirm the change was intended and reflected on the landing page.",
                        uncertainty="Change happened between the two snapshot dates; exact day unknown.")
    chk.observe("Price change events", offers=len(snaps), snapshots=sum(len(v) for v in snaps.values()),
                events=len(events), increases=sum(1 for e in events if e["change"] > 0),
                decreases=sum(1 for e in events if e["change"] < 0), alert_fraction=alert)
    return events


def _check_sales(ctx, snaps) -> None:
    chk = ctx.check("sale_price_windows", "Sale price windows on latest snapshots", {SNAP: SNAP_COLS + SALE_COLS})
    if not chk.runnable:
        return
    active = 0
    for k in sorted(snaps):
        if not snaps[k]:
            continue
        o = snaps[k][-1]
        if o["basis"] == "sale_price":
            active += 1
        if o["sale_price"] is None:
            continue
        entity = {"offer_id": k[0], "target_country": k[1], "snapshot_date": o["date"]}
        ev = {k2: o[k2] for k2 in ("price", "sale_price", "sale_start", "sale_end", "currency", "date")}
        if o["price"] is not None and o["sale_price"] >= o["price"]:
            chk.finding("sale_price_not_below_price", "Info", entity,
                        f"Offer {k[0]} sale_price {o['sale_price']:g} is not below price {o['price']:g}",
                        evidence=ev, recommendation="Ask the feed owner which price is intended.",
                        uncertainty="Internal inconsistency only; displayed price not verified here.")
        if o["sale_start"] and o["sale_end"] and o["sale_start"] > o["sale_end"]:
            chk.finding("invalid_sale_window", "Info", entity,
                        f"Offer {k[0]} sale window starts {o['sale_start']} after it ends {o['sale_end']}",
                        evidence=ev, recommendation="Correct the sale window with the feed owner.")
        elif o["sale_end"] and o["sale_end"] < o["date"]:
            chk.finding("expired_sale_price_submitted", "Info", entity,
                        f"Offer {k[0]} sale window ended {o['sale_end']} but sale_price is still submitted on {o['date']}",
                        evidence=ev, recommendation="Remove or renew the expired sale price.",
                        uncertainty="Expired sale prices are not effective; hygiene only.")
    chk.observe("Offers with an effective sale price on their latest snapshot", offers=len(snaps), active_sales=active)


def _check_pages(ctx, snaps, by_camp) -> None:
    chk = ctx.check("landing_price_mismatch", "Same-date landing-page price vs feed effective price",
                    {PAGES: ["offer_id", "target_country", "checked_at", "url", "page_price", "currency"],
                     SNAP: SNAP_COLS})
    if not chk.runnable:
        return
    t = ctx.table(PAGES)
    by_date = {k: {o["date"]: o for o in v} for k, v in snaps.items()}
    matched = unmatched = skipped = mismatches = 0
    for r in sorted(t.rows, key=lambda r: (_key(r), str(r.get("checked_at")))):
        k, d = _key(r), V.parse_date(r.get("checked_at"))
        status = V.integer(r.get("http_status")) if "http_status" in t.columns else None
        page = V.num(r.get("page_price"))
        if d is None or page is None or (status is not None and not 200 <= status < 300):
            skipped += 1
            continue
        o = by_date.get(k, {}).get(d)
        if o is None or o["effective"] is None:
            unmatched += 1
            continue
        if _cur(r.get("currency")) != o["currency"]:
            skipped += 1
            continue
        matched += 1
        diff = page - o["effective"]
        if abs(diff) <= TOLERANCE:
            continue
        mismatches += 1
        material = []
        for (ok, cid), cost in sorted((by_camp or {}).items()):
            if ok != k:
                continue
            p = ctx.params.get("spend_significant", cid or None)
            if p.value is not None and cost >= p.value:
                material.append({"campaign_id": cid, "cost": cost, "spend_significant": p.value, "source": p.source})
        entity = {"offer_id": k[0], "target_country": k[1], "checked_at": r.get("checked_at")}
        ev = {"url": r.get("url"), "page_price": page, "feed_effective_price": o["effective"], "basis": o["basis"],
              "snapshot_date": o["date"], "currency": o["currency"], "difference": diff, "tolerance": TOLERANCE,
              "offer_spend_available": by_camp is not None, "material_campaigns": material,
              "account_currency": ctx.currency}
        prov = chk.finding("landing_price_mismatch", "Warning", entity,
                           f"Offer {k[0]} ({k[1]}) page price {page:g} differs from feed {o['basis']} "
                           f"{o['effective']:g} {o['currency']} on {d}",
                           evidence=ev, calculation={"difference": "page_price - feed_effective_price"},
                           recommendation="Request-only: ask the feed owner to align feed and page prices and re-check.",
                           uncertainty="A single check; variant or timezone differences can explain it.")
        outcomes = {"mismatch_confirmed": {"severity": "Warning", "recommendation": "Align feed and page prices."},
                    "variant_or_timing_artifact": {"severity": None, "recommendation":
                                                   "No mismatch: page showed another variant/time; document it."},
                    "uncertain": {"severity": "Warning", "recommendation": "Keep the Warning; request a re-check."}}
        if material:
            outcomes["disapproval_evidenced"] = {"severity": "Critical", "recommendation":
                                                 "Prioritize the correction; cite the Merchant disapproval/limitation."}
        chk.review("landing_price_mismatch", entity,
                   f"Is the page/feed price difference for offer {k[0]} a real mismatch, and is there supplied "
                   f"Merchant disapproval or limitation evidence?",
                   evidence=ev, outcomes=outcomes, provisional=prov,
                   guidance="Use only supplied page checks and Merchant diagnostics; disapproval_evidenced needs "
                            "proposal.evidence_ref. Never estimate lost revenue.")
    if unmatched:
        chk.partial(f"{unmatched} page checks without a same-date snapshot for the offer (not compared)")
    if skipped:
        chk.partial(f"{skipped} page checks skipped (non-2xx, unparseable price/date or currency differs)")
    if by_camp is None:
        chk.partial(f"{DAILY} missing: offer spend unknown, Critical path unavailable")
    chk.observe("Landing-page price checks compared", compared=matched, mismatches=mismatches,
                unmatched=unmatched, skipped=skipped)


def _check_benchmark(ctx) -> None:
    chk = ctx.check("benchmark_price_gap", "Own price vs Merchant benchmark",
                    {BENCH: ["report_date", "offer_id", "target_country", "price", "benchmark_price", "currency"]})
    if not chk.runnable:
        return
    alert = _alert(ctx, "price_gap_alert_pct")
    if alert is None:
        chk.partial("profile.price_gap_alert_pct not set: gaps listed as observations, no alerts")
    latest: dict = {}
    for r in ctx.table(BENCH).rows:
        d, k = V.parse_date(r.get("report_date")), _key(r)
        if d is not None and k[0] and (k not in latest or d > latest[k][0]):
            latest[k] = (d, r)
    above = below = undefined = 0
    for k in sorted(latest):
        d, r = latest[k]
        own, bench = V.num(r.get("price")), V.num(r.get("benchmark_price"))
        gap = V.ratio(None if own is None or bench is None else own - bench, bench if bench and bench > 0 else None)
        if gap is None:
            undefined += 1
            continue
        above += gap > 0
        below += gap < 0
        if alert is not None and gap >= alert:
            chk.finding("price_above_benchmark", "Info", {"offer_id": k[0], "target_country": k[1], "report_date": d},
                        f"Offer {k[0]} ({k[1]}) price {own:g} is {gap:.1%} above benchmark {bench:g} {_cur(r.get('currency'))}",
                        evidence={"price": own, "benchmark_price": bench, "currency": _cur(r.get("currency")),
                                  "report_date": d},
                        calculation={"gap": "(price - benchmark_price) / benchmark_price", "alert_fraction": alert,
                                     "alert_source": "profile.price_gap_alert_pct"},
                        recommendation="Share with the pricing owner; pricing is a business decision.",
                        uncertainty="Benchmark is a Merchant estimate; no demand or profit effect is implied.")
    if undefined:
        chk.partial(f"{undefined} offers with missing or zero benchmark/price: gap undefined")
    chk.observe("Benchmark gaps on latest report rows", offers=len(latest), above=above, below=below,
                undefined=undefined, alert_fraction=alert)


def _side(by_day, k, start, end) -> dict:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    rows = [by_day.get(k, {}).get(d) for d in days]
    tot = {c: sum(r[c] for r in rows if r) for c in ("impressions", "clicks", "cost", "conversions", "conversion_value")}
    tot.update({"start": start, "end": end, "days_with_rows": sum(1 for r in rows if r),
                "unknown_cells": sum(r["unknown"] for r in rows if r)})
    return tot


def _check_performance(ctx, events) -> None:
    chk = ctx.check("price_event_performance", "Descriptive before/after windows around price events",
                    {SNAP: SNAP_COLS, DAILY: DAILY_COLS})
    if not chk.runnable:
        return
    if ctx.period_start is None or ctx.period_end is None:
        chk.skip("report period unknown", ["account:date_range_start", "account:date_range_end"])
        return
    by_day, _ = _daily(ctx, chk)
    certified = ctx.table(DAILY).complete is True
    rates_ok = ctx.mature is True
    if not rates_ok:
        chk.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): volumes only, no rate comparisons")
    cap = V.integer(ctx.profile.get("price_event_window_days"))
    gates = {p: ctx.params.get(p).value for p in ("min_impressions", "min_clicks", "min_conversions")}
    lo, hi = ctx.period_start, ctx.period_end
    described = unqualified = 0
    for e in events:
        b_start, b_end = max(e["old_span"][0], lo), min(e["old_span"][1], hi)
        a_start, a_end = max(e["new_span"][0], lo), min(e["new_span"][1], hi)
        length = min((b_end - b_start).days + 1, (a_end - a_start).days + 1)
        if cap is not None and cap > 0:
            length = min(length, cap)
        entity = {"offer_id": e["offer_id"], "target_country": e["target_country"], "first_new_date": e["new_span"][0]}
        if length < 1:
            unqualified += 1
            chk.observe("Price event outside the report period or observed spans: not described", **entity)
            continue
        before = _side(by_day, (e["offer_id"], e["target_country"]), b_end - timedelta(days=length - 1), b_end)
        after = _side(by_day, (e["offer_id"], e["target_country"]), a_start, a_start + timedelta(days=length - 1))
        reasons = []
        if not certified and (before["days_with_rows"] < length or after["days_with_rows"] < length):
            reasons.append("days without product rows and no certified-complete manifest: totals unknown")
        if before["unknown_cells"] or after["unknown_cells"]:
            reasons.append("unknown metric cells in a window")
        rates = {}
        if rates_ok and not reasons:
            pairs = (("ctr", "clicks", "impressions", "min_impressions"),
                     ("conversion_rate", "conversions", "clicks", "min_clicks"),
                     ("cpa", "cost", "conversions", "min_conversions"),
                     ("roas", "conversion_value", "cost", "min_conversions"))
            for name, num, den, gate in pairs:
                basis = "conversions" if gate == "min_conversions" else den
                if before[basis] >= gates[gate] and after[basis] >= gates[gate]:
                    rates[name] = {"before": V.ratio(before[num], before[den]), "after": V.ratio(after[num], after[den])}
                else:
                    rates[name] = {"unqualified": f"{basis} below {gate}={gates[gate]} on a side"}
        if reasons:
            unqualified += 1
        else:
            described += 1
        chk.observe("Before/after description around a price event (descriptive, not causal)", **entity,
                    direction=e["direction"], old_price=e["old_price"], new_price=e["new_price"],
                    window_days=length, before=before, after=after, rates=rates,
                    unqualified=reasons, gates=gates, mature=ctx.mature)
    if unqualified:
        chk.partial(f"{unqualified} price events without qualified before/after windows")
    chk.observe("Price events described", events=len(events), described=described, unqualified=unqualified)


def run(ctx) -> None:
    """Run price-change, sale-window, landing-page mismatch, benchmark gap and before/after performance checks.

    Rules:   Other-currency rows are excluded, never converted; conflicting duplicate snapshots are dropped.
             Price-change/gap alerts (Info) need profile.price_change_alert_pct / price_gap_alert_pct, else observations
             + partial. Same-date page/feed mismatch > 0.005 is a provisional Warning + review; Critical only via
             'disapproval_evidenced' with offer spend >= spend_significant and proposal.evidence_ref. Before/after
             windows are descriptive, never findings.
    """
    snaps, notes = _snapshots(ctx) if ctx.table(SNAP) is not None and not ctx.table(SNAP).missing(SNAP_COLS) else ({}, [])
    events = _check_events(ctx, snaps, notes)
    _check_sales(ctx, snaps)
    by_camp = None
    if ctx.table(DAILY) is not None and not ctx.table(DAILY).missing(DAILY_COLS):
        _, by_camp = _daily(ctx, None)
    _check_pages(ctx, snaps, by_camp)
    _check_benchmark(ctx)
    _check_performance(ctx, events)


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'disapproval_evidenced' needs proposal.evidence_ref and a material campaign in the reviewed evidence."""
    if item.condition_key == "landing_price_mismatch" and decision.get("outcome") == "disapproval_evidenced":
        problems = []
        if not (decision.get("proposal") or {}).get("evidence_ref"):
            problems.append("Critical needs proposal.evidence_ref pointing at supplied Merchant evidence")
        if not item.evidence.get("material_campaigns"):
            problems.append("Critical needs offer spend >= spend_significant in at least one campaign")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
