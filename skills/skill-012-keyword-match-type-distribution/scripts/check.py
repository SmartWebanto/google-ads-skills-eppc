"""check.py — skill-012 deterministic keyword match-type distribution and gated per-type outcome comparison.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-012-keyword-match-type-distribution/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #62 Make Phrase match Exact (Brainlabs) — NOT integrated: it adds query-level exact negatives
         (a mutation) and needs search_terms, which this recipe does not declare; query drift belongs to 023
rules:   Match type comes ONLY from keywords.match_type (BROAD/PHRASE/EXACT); anything else is UNKNOWN —
         never parsed from brackets/quotes in the text. Metrics join keywords on (campaign_id, ad_group_id,
         keyword_id); duplicate rows without a segment column are fan-out → excluded + partial.
         Shares/rates come from summed numerators/denominators per campaign; ratio() None = undefined.
         No adoption quota: single-type campaigns are Info only. CPA > 2x target (ctx.params.target_cpa) or
         > 2x a same-campaign benchmark type needs ctx.mature True and >= min_conversions on BOTH sides,
         then Warning only via AI context review (provisional Info). Value-led campaigns skip CPA screens.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-012-keyword-match-type-distribution"
VERSION = "1.0.0"

TYPES = ("BROAD", "PHRASE", "EXACT")
KW = {"keywords": ["id", "campaign_id", "ad_group_id", "match_type"]}
KM = {"keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"]}
SEGMENT_COLS = ("date", "day", "week", "month", "device", "network", "ad_network_type", "segment", "hour")
METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def _pos(v):
    f = V.num(v)
    return f if f is not None and f > 0 else None


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion maturity",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature, maturity_note=ctx.maturity_note,
              conversion_date_basis=ctx.account.get("conversion_date_basis"))


def _mtype(v) -> str:
    s = str(v or "").strip().upper().replace(" MATCH", "")
    return s if s in TYPES else "UNKNOWN"


def _aggregate(ctx, table) -> tuple[dict, list[str]]:
    segs = [c for c in SEGMENT_COLS if c in table.columns]
    groups: dict[tuple, list[dict]] = {}
    for r in table.rows:
        groups.setdefault((str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("keyword_id"))), []).append(r)
    out, notes = {}, []
    for key in sorted(groups):
        rs = groups[key]
        uniq = {tuple(sorted((k, str(v)) for k, v in r.items())) for r in rs}
        if len(uniq) < len(rs):
            notes.append(f"keyword {key[2]}: identical duplicate rows dropped")
            rs = [dict(t) for t in sorted(uniq)]
        if len(rs) > 1 and not segs:
            notes.append(f"keyword {key[2]}: {len(rs)} rows without a segment column (fan-out); excluded")
            continue
        agg = dict.fromkeys(METRICS, 0.0)
        for r in rs:
            for m in METRICS:
                v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
                agg[m] = None if v is None or agg[m] is None else agg[m] + v
        out[key] = agg
    return out, notes


def _value_led(ctx, cid: str) -> bool:
    camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None) or {}
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    return bool(_pos(camp.get("target_roas")) or (isinstance(obj, dict) and _pos(obj.get("target_roas")))
                or "VALUE" in str(camp.get("bidding_strategy_type") or "").upper()
                or "ROAS" in str(camp.get("bidding_strategy_type") or "").upper())


def run(ctx) -> None:
    """Run match-type inventory, per-campaign shares and CPA screens across BROAD/PHRASE/EXACT keywords.

    Rules:   Match type only from keywords.match_type; anything else → unknown_match_type Info, never parsed from text.
             single_type_campaign is Info (no adoption quota). CPA > 2x target/benchmark type needs ctx.mature True and
             min_conversions on BOTH sides → provisional Info + ai_review (Warning only via review); value-led campaigns
             skip CPA screens. Experiments are Info review proposals only; fan-out duplicate rows are excluded +
             partial.
    """
    _scope(ctx)
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    search = {cid for cid, c in camps.items() if str(c.get("channel_type") or "").upper() == "SEARCH"}
    na = ctx.table("campaigns") is not None and not search
    na_reason = "no Search campaigns (campaigns.channel_type)"
    in_scope = (lambda cid: cid in search) if ctx.table("campaigns") is not None else (lambda cid: True)

    # step 2 — explicit match type
    parse = ctx.check("match_type_parse", "Explicit BROAD/PHRASE/EXACT per keyword; Unknown preserved", KW,
                      applicable=not na, na_reason=na_reason)
    inv: dict[tuple, str] = {}
    if parse.runnable:
        if ctx.table("campaigns") is None:
            parse.partial("campaigns missing: channel applicability unverified", ["campaigns (file)"])
        for k in ctx.rows("keywords"):
            cid = str(k.get("campaign_id"))
            if not in_scope(cid) or str(k.get("status") or "").upper() in ("REMOVED", "DELETED"):
                continue
            inv[(cid, str(k.get("ad_group_id")), str(k.get("id")))] = _mtype(k.get("match_type"))
        for cid in sorted({k[0] for k in inv}):
            counts = {t: sum(1 for k, v in inv.items() if k[0] == cid and v == t) for t in TYPES + ("UNKNOWN",)}
            parse.observe(f"Campaign {cid}: keyword count by explicit match type", campaign_id=cid, **counts)
            if counts["UNKNOWN"]:
                parse.finding("unknown_match_type", "Info", {"campaign_id": cid},
                              f"{counts['UNKNOWN']} keyword(s) in campaign {cid} lack an explicit match type",
                              evidence={"unknown_keywords": sorted(k[2] for k, v in inv.items() if k[0] == cid and v == "UNKNOWN")},
                              recommendation="Export the explicit match-type field; do not infer from punctuation.",
                              uncertainty="Unknown types are excluded from type shares.")

    # step 3 — distribution
    dist = ctx.check("distribution", "Keyword-count, cost and conversion shares per campaign", {**KW, **KM},
                     applicable=not na, na_reason=na_reason)
    cohorts: dict[str, dict[str, dict]] = {}
    if dist.runnable:
        metrics, notes = _aggregate(ctx, ctx.table("keyword_metrics"))
        for n in notes:
            dist.partial(n)
        unjoined = sorted(k[2] for k in metrics if k not in inv and in_scope(k[0]))
        if unjoined:
            dist.partial(f"{len(unjoined)} metric rows without a keyword inventory match (by IDs): {unjoined[:10]}")
        for key in sorted(inv):
            t = inv[key]
            c = cohorts.setdefault(key[0], {})
            acc = c.setdefault(t, {"keywords": 0, **dict.fromkeys(METRICS, 0.0), "unknown_metrics": 0})
            acc["keywords"] += 1
            m = metrics.get(key)
            if m is None:
                continue
            for f in METRICS:
                if m[f] is None:
                    acc["unknown_metrics"] += 1 if f == "cost" else 0
                    continue
                acc[f] += m[f]
        for cid in sorted(cohorts):
            c = cohorts[cid]
            tot = {f: sum(v[f] for v in c.values()) for f in ("keywords", "cost", "conversions")}
            known = {t for t in c if t != "UNKNOWN"}
            for t in sorted(c):
                dist.observe(f"Campaign {cid} {t}: shares", campaign_id=cid, match_type=t,
                             keyword_share=V.ratio(c[t]["keywords"], tot["keywords"]),
                             cost_share=V.ratio(c[t]["cost"], tot["cost"]),
                             conversion_share=V.ratio(c[t]["conversions"], tot["conversions"]),
                             keywords=c[t]["keywords"], cost=c[t]["cost"], conversions=c[t]["conversions"],
                             denominators=tot, window=[ctx.period_start, ctx.period_end])
            if len(known) == 1:
                t = next(iter(known))
                dist.finding("single_type_campaign", "Info", {"campaign_id": cid},
                             f"Campaign {cid}: every typed keyword is {t}",
                             evidence={"keywords": c[t]["keywords"], "cost": c[t]["cost"]},
                             recommendation="Descriptive only; no match-type quota or diversification is required.",
                             uncertainty="Concentration reflects structure/goal mix, not a match-type effect.")

    # step 4 — rates from sums
    rates = ctx.check("type_rates", "CTR, CPC, CVR, CPA and ROAS per type from summed metrics", {**KW, **KM},
                      applicable=not na, na_reason=na_reason)
    derived: dict[tuple, dict] = {}
    if rates.runnable:
        for cid in sorted(cohorts):
            value_led = _value_led(ctx, cid)
            for t in sorted(cohorts[cid]):
                a = cohorts[cid][t]
                d = {"ctr": V.ratio(a["clicks"], a["impressions"]), "cpc": V.ratio(a["cost"], a["clicks"]),
                     "cvr": V.ratio(a["conversions"], a["clicks"]),
                     "cpa": None if value_led else V.ratio(a["cost"], a["conversions"]),
                     "roas": V.ratio(a["conversion_value"], a["cost"]) if value_led else None}
                derived[(cid, t)] = {**d, **a, "value_led": value_led}
                rates.observe(f"Campaign {cid} {t}: derived rates", campaign_id=cid, match_type=t,
                              objective="value" if value_led else "count", **d)

    # step 5 — sample gates
    gates = ctx.check("sample_gates", "Mature sample gates for each compared type", {**KW, **KM},
                      applicable=not na, na_reason=na_reason)
    mc, mk, mi = ctx.params.get("min_conversions"), ctx.params.get("min_clicks"), ctx.params.get("min_impressions")
    qualified: set = set()
    if gates.runnable:
        if ctx.mature is not True:
            gates.partial(f"conversion maturity {ctx.mature}: {ctx.maturity_note}; no performance comparison")
        for (cid, t), d in sorted(derived.items()):
            if t == "UNKNOWN":
                continue
            ok = {"cpa": ctx.mature is True and d["conversions"] >= (mc.value or float("inf")),
                  "cvr": ctx.mature is True and d["clicks"] >= (mk.value or float("inf")),
                  "ctr": d["impressions"] >= (mi.value or float("inf"))}
            if ok["cpa"]:
                qualified.add((cid, t))
            gates.observe(f"Campaign {cid} {t}: sample gates", campaign_id=cid, match_type=t, conversions=d["conversions"],
                          clicks=d["clicks"], impressions=d["impressions"], min_conversions=mc.value,
                          min_clicks=mk.value, min_impressions=mi.value, qualifies=ok)

    # step 6 — target / benchmark deviation
    dev = ctx.check("target_deviation", "Mature type CPA > 2x applicable target or comparable type", {**KW, **KM},
                    applicable=not na, na_reason=na_reason)
    if dev.runnable:
        if ctx.mature is not True:
            dev.partial("conversions not lag-mature: deviation screen skipped")
        for (cid, t) in sorted(qualified):
            d = derived[(cid, t)]
            if d["value_led"] or d["cpa"] is None:
                continue
            target, src = ctx.params.target_cpa(cid)
            bench = None
            if target is None:
                others = [(o, derived[(cid, o)]["cpa"]) for o in TYPES if o != t and (cid, o) in qualified
                          and derived[(cid, o)]["cpa"] is not None]
                if others:
                    bench = min(others, key=lambda x: (x[1], x[0]))
            ref = target if target is not None else (bench[1] if bench else None)
            if ref is None:
                dev.observe(f"Campaign {cid} {t}: no applicable target or comparable type", campaign_id=cid,
                            match_type=t, cpa=d["cpa"], target_reason=src)
                continue
            ratio = V.ratio(d["cpa"], ref)
            dev.observe(f"Campaign {cid} {t}: CPA vs reference", campaign_id=cid, match_type=t, cpa=d["cpa"],
                        reference=ref, reference_source=src if target is not None else f"same-campaign {bench[0]} CPA",
                        ratio=ratio)
            if ratio is None or ratio <= 2:
                continue
            entity = {"campaign_id": cid, "match_type": t}
            ev = {"cpa": d["cpa"], "cost": d["cost"], "conversions": d["conversions"], "reference_cpa": ref,
                  "reference_source": src if target is not None else f"same-campaign {bench[0]} CPA ({bench[1]:.2f})",
                  "ratio": ratio, "min_conversions": mc.value, "window": [ctx.period_start, ctx.period_end],
                  "strategy": (camps.get(cid) or {}).get("bidding_strategy_type"),
                  "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(cid)}
            prov = dev.finding("type_cpa_over_2x_reference", "Info", entity,
                               f"Campaign {cid} {t} CPA {d['cpa']:.2f} is {ratio:.2f}x the reference {ref:.2f}",
                               evidence=ev, recommendation="Review context (brand/geo/product/goal mix) before acting.",
                               uncertainty="Type-level CPA reflects keyword mix, not a causal match-type effect.")
            dev.review("type_cpa_over_2x_reference", entity,
                       f"After reviewing brand, product, geo and goal mix, does the {t} CPA in campaign {cid} indicate a "
                       f"real deviation from the applicable target/benchmark?", evidence=ev, provisional=prov,
                       outcomes={"deviation_after_context": {"severity": "Warning", "recommendation":
                                                             "Review keywords of this type with 020/023; no match-type swap mandate."},
                                 "mix_explains": {"severity": None, "recommendation": "No action; document the mix."},
                                 "uncertain": {"severity": "Info", "recommendation": "Collect segment evidence."}},
                       guidance="Account-wide shares reflect mix; use only campaign objective and profile context.")

    # step 7 — delegation
    deleg = ctx.check("strategy_delegation", "Bidding context; strategy fit to 022, query relevance to 023",
                      {"campaigns": ["id", "bidding_strategy_type"]}, applicable=not na, na_reason=na_reason)
    if deleg.runnable:
        for cid in sorted(c for c in cohorts if c in camps):
            deleg.observe(f"Campaign {cid}: bidding context", campaign_id=cid,
                          strategy=camps[cid].get("bidding_strategy_type"),
                          delegated={"strategy_control_fit": "skill-022", "query_relevance": "skill-023"})

    # step 8 — optional scoped experiment
    q = ctx.profile.get("match_type_experiment_question")
    exp = ctx.check("experiment_proposal", "Optional scoped experiment for a business-defined reach/control question",
                    applicable=bool(q) and not na,
                    na_reason="no profile.match_type_experiment_question: no experiment proposed" if not na else na_reason)
    if exp.runnable:
        exp.review("scoped_experiment", {"question": str(q)},
                   "Does the supplied business question justify a scoped match-type experiment?",
                   evidence={"question": q, "cohorts": {c: sorted(v) for c, v in cohorts.items()}},
                   outcomes={"propose_experiment": {"severity": "Info", "recommendation":
                                                    "Owner-approved experiment with predeclared metric and duration."},
                             "not_justified": {"severity": None, "recommendation": "No action."}},
                   guidance="History does not establish incremental conversions from another match type.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: an experiment proposal must name campaign_id, metric and duration."""
    if item.condition_key == "scoped_experiment" and decision.get("outcome") == "propose_experiment":
        p = decision.get("proposal") or {}
        missing = [k for k in ("campaign_id", "primary_metric", "duration_days") if not p.get(k)]
        if missing:
            return [f"experiment proposal needs {missing}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
