"""check.py — skill-094 deterministic PMax/Search overlap hypothesis screen.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-094-pmax-cannibalizing-search-detection/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #68 PMax Brand Traffic Analyzer (nilsrooijmans.com / smec) — clean-room reimplementation of the
         brand vs non-brand share of PMax traffic, restricted to literal visible query rows; its "exclude brand"
         follow-up is NOT integrated (recipe forbids prescribing immediate brand exclusions).
rules:   Observational evidence is descriptive: nothing here concludes internal auction competition or lost
         incrementality. Shifts/overlaps are Info hypotheses; Warning only for a DOCUMENTED intent/control
         mismatch (profile campaign_objectives[id].brand_policy in NONBRAND_POLICIES, or a free-text policy the
         AI judges) corroborated by served literal PMax brand queries. No deterministic Critical exists.
         Campaign key: campaigns.id, alternative campaigns.campaign_id. Search = channel_type SEARCH;
         PMax = PERFORMANCE_MAX. Brand = profile.brand_terms as literal phrase inside the query (no fuzzing).
         Literal PMax queries = search_pmax_queries rows whose reported_query_or_category_type is in
         QUERY_TYPES; category/theme rows are counted separately and never treated as queries.
         Intervention date: profile.overlap_intervention_date, else the single distinct
         search_pmax_controls.change_date of current PMax rows; several candidates → partial, no shift.
         Periods: equal-length complete windows either side of the date, post window ending at the last
         lag-mature day (snapshot - lag); rows with complete_day false are excluded; duplicate grain rows skipped.
         Rates: CPA needs min_conversions, CPC min_clicks, IS min_impressions on BOTH periods/channels.
         IS is aggregated via eligible impressions (impressions / IS), never averaged.
         brand_exclusions cell: empty = unknown; none/no_exclusions/[]/0 = known empty.
         verify(): holdout proposals need every HOLDOUT_FIELDS key; supported experiment estimates need
         estimate + interval; control-mismatch decisions need proposal.evidence_ref.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
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
from adsrun.negatives import blocks  # noqa: E402

SKILL = "skill-094-pmax-cannibalizing-search-detection"
VERSION = "1.0.0"

SEARCH, PMAX = "SEARCH", "PERFORMANCE_MAX"
QUERY_TYPES = {"query", "search_term", "search_query", "search term", "literal_query"}
NONBRAND_POLICIES = {"nonbrand_only", "non_brand_only", "no_brand", "brand_excluded", "exclude_brand"}
OPEN_POLICIES = {"brand_only", "mixed", "any", "mixed_intent", "brand_allowed", "mixed intent allowed"}
EMPTY_TOKENS = {"none", "no_exclusions", "[]", "0", "empty", "false"}
HOLDOUT_FIELDS = ("randomized_unit", "primary_outcome", "duration_days", "brand_policy", "budget_constraint",
                  "contamination_checks", "rollback_plan")
DAILY = "custom/search_pmax_daily"
QUERIES = "custom/search_pmax_queries"
CONTROLS = "external/search_pmax_controls"
EXPERIMENT = "external/pmax_overlap_experiment"
_METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def _key_col(ctx) -> str:
    t = ctx.table("campaigns")
    return "campaign_id" if t is not None and "id" not in t.columns and "campaign_id" in t.columns else "id"


def _channels(ctx) -> dict[str, str]:
    col = _key_col(ctx)
    out = {}
    for r in ctx.rows("campaigns"):
        ch = str(r.get("channel_type") or "").upper()
        if ch in (SEARCH, PMAX) and str(r.get("status") or "ENABLED").upper() not in ("REMOVED",):
            out[str(r.get(col))] = ch
    return dict(sorted(out.items()))


def _brand(ctx, q) -> bool:
    return any(blocks(t, "PHRASE", q) is True for t in (ctx.profile.get("brand_terms") or []) if t)


def _objective(ctx, cid) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objs, dict):
        return {}
    o = next((v for k, v in objs.items() if str(k) == cid), None)
    return o if isinstance(o, dict) else {}


def _policy(ctx, cid) -> str:
    return V.norm_text(_objective(ctx, cid).get("brand_policy"))


def _goal_key(ctx, cid) -> tuple:
    return tuple(sorted(ctx.goal_ids(cid)))


def _cost_per(ctx, cost, n):
    return V.ratio(cost, n)


def _sums(rows, ctx) -> dict:
    s = {m: 0.0 for m in _METRICS}
    unknown = {m: 0 for m in _METRICS}
    for r in rows:
        for m in _METRICS:
            v = ctx.money(r.get(m)) if m in ("cost", "conversion_value") else V.num(r.get(m))
            if v is None:
                unknown[m] += 1
            else:
                s[m] += v
    for m in _METRICS:
        if unknown[m]:
            s[m] = None
    return s


def run(ctx) -> None:
    """Run scope, period shift, query overlap, channel comparison, brand exclusion and causal checks.

    Rules:   Without concurrent Search and PMax every check is not applicable (skipped when inventory is missing);
             missing brand_terms or immaturity makes scope partial. Shifts/overlaps are Info hypotheses only. Warning
             only for a documented nonbrand policy contradicted by served literal PMax brand queries; no deterministic
             Critical; rates need min gates on both periods/channels; nothing concludes auction cannibalization.
    """
    kc = _key_col(ctx)
    scope = ctx.check("scope_declaration", "Declare observational/experimental scope and comparable campaigns",
                      {"campaigns": [kc, "channel_type"]})
    ch = _channels(ctx) if scope.runnable else {}
    search = [c for c, t in ch.items() if t == SEARCH]
    pmax = [c for c, t in ch.items() if t == PMAX]
    concurrent = bool(search and pmax)
    if scope.runnable:
        if not concurrent:
            scope.not_applicable("account does not run Search and PMax concurrently in the campaign inventory")
        else:
            mode = ("experimental" if ctx.table(EXPERIMENT) else "observational (daily)" if ctx.table(DAILY)
                    else "aggregate-only descriptive screen")
            if not ctx.profile.get("brand_terms"):
                scope.partial("profile.brand_terms missing: brand shares cannot be measured")
            if ctx.mature is not True:
                scope.partial(f"maturity {ctx.mature}: {ctx.maturity_note}")
            scope.observe("Scope declared before analysis", scope=mode, search_campaign_ids=search,
                          pmax_campaign_ids=pmax, goals={c: list(_goal_key(ctx, c)) for c in search + pmax},
                          brand_terms=list(ctx.profile.get("brand_terms") or []), mature=ctx.mature,
                          maturity_note=ctx.maturity_note, period=[ctx.period_start, ctx.period_end])
    ids = ["period_shift", "query_overlap", "channel_comparison", "brand_exclusion_state", "causal_evaluation"]
    if not concurrent:
        titles = ["Equal mature periods around the intervention", "Directly observed query overlap and brand share",
                  "Total and per-channel comparable-goal outcomes", "PMax brand exclusion state vs objective",
                  "Controlled causal evidence"]
        for cid, title in zip(ids, titles):
            c = ctx.check(cid, title)
            if scope.runnable:
                c.not_applicable("no concurrent Search and PMax campaigns")
            else:
                c.skip("campaign inventory unavailable", scope.missing)
        return
    hypotheses = []
    hypotheses += _period_shift(ctx, ch)
    hypotheses += _query_overlap(ctx, ch)
    hypotheses += _channel_comparison(ctx, ch)
    _brand_exclusions(ctx, ch)
    _causal(ctx, ch, hypotheses)


# ---------------------------------------------------------------------------------------------- step 2
def _intervention(ctx, pmax) -> tuple:
    d = V.parse_date(ctx.profile.get("overlap_intervention_date"))
    if d:
        return d, "profile.overlap_intervention_date"
    t = ctx.table(CONTROLS)
    if t is None or "change_date" not in t.columns:
        return None, "no profile.overlap_intervention_date and no external/search_pmax_controls:change_date"
    cands = sorted({V.parse_date(r.get("change_date")) for r in t.rows
                    if str(r.get("campaign_id")) in pmax and V.parse_date(r.get("change_date"))})
    if len(cands) == 1:
        return cands[0], "external/search_pmax_controls:change_date"
    if not cands:
        return None, "no PMax change_date in external/search_pmax_controls"
    return None, f"ambiguous intervention dates {[str(c) for c in cands]}; set profile.overlap_intervention_date"


def _period_shift(ctx, ch) -> list:
    chk = ctx.check("period_shift", "Equal mature periods around the intervention",
                    {DAILY: ["campaign_id", "date", "goal_set_id", "impressions", "clicks", "cost", "conversions"]})
    if not chk.runnable:
        return []
    pmax = {c for c, t in ch.items() if t == PMAX}
    d, dsrc = _intervention(ctx, pmax)
    if d is None:
        chk.partial(f"intervention date unresolved: {dsrc}")
        return []
    if ctx.lag_days is None or ctx.snapshot is None:
        chk.partial(f"lag maturity unknown ({ctx.maturity_note}): no mature post window")
        return []
    t = ctx.table(DAILY)
    seen, rows, dups, incomplete = set(), [], 0, 0
    has_channel = "channel" in t.columns
    for r in t.rows:
        cid = str(r.get("campaign_id"))
        day = V.parse_date(r.get("date"))
        if cid not in ch or day is None:
            continue
        grain = (cid, day, str(r.get("goal_set_id")), str(r.get("channel")) if has_channel else "")
        if grain in seen:
            dups += 1
            continue
        seen.add(grain)
        if "complete_day" in t.columns and V.boolean(r.get("complete_day")) is not True:
            incomplete += 1
            continue
        rows.append((cid, day, r))
    if dups:
        chk.partial(f"{dups} duplicate rows at campaign/date/goal/channel grain skipped")
    if incomplete:
        chk.partial(f"{incomplete} rows not marked complete_day excluded")
    last_mature = ctx.snapshot - timedelta(days=ctx.lag_days)
    days = sorted({x[1] for x in rows})
    if not days:
        chk.partial("no daily rows for the Search/PMax campaigns")
        return []
    n = min((d - days[0]).days, (min(last_mature, days[-1]) - d).days + 1)
    if n < 1:
        chk.partial(f"no equal mature periods around {d} (data {days[0]}..{days[-1]}, mature through {last_mature})")
        return []
    pre = (d - timedelta(days=n), d - timedelta(days=1))
    post = (d, d + timedelta(days=n - 1))
    missing_days = [str(x) for x in (pre[0] + timedelta(days=i) for i in range(2 * n)) if x not in set(days)]
    if missing_days:
        chk.partial(f"{len(missing_days)} days without rows inside the compared windows; treated as unknown coverage")
    # comparable goals: goal sets shared by Search and PMax
    goal_sets = {}
    for c, typ in ch.items():
        goal_sets.setdefault(_goal_key(ctx, c), {SEARCH: [], PMAX: []})[typ].append(c)
    out = []
    mins = {p: ctx.params.get(p) for p in ("min_clicks", "min_conversions", "min_impressions")}
    for goals, members in sorted(goal_sets.items()):
        if not members[SEARCH] or not members[PMAX]:
            continue
        if not goals:
            chk.partial("campaign goal_ids undeclared: goal matching unverified")
        gset = set(goals)
        res = {}
        for typ in (SEARCH, PMAX):
            for label, (a, b) in (("pre", pre), ("post", post)):
                sel = [r for cid, day, r in rows if cid in members[typ] and a <= day <= b
                       and (not gset or str(r.get("goal_set_id")) in gset)]
                s = _sums(sel, ctx)
                if "search_impression_share" in t.columns and typ == SEARCH:
                    elig, ok = 0.0, True
                    for r in sel:
                        imp, share = V.num(r.get("impressions")), ctx.rate(r.get("search_impression_share"))
                        if imp is None or not share:
                            ok = False
                            break
                        elig += imp / share
                    s["search_impression_share"] = V.ratio(s["impressions"], elig) if ok else None
                res[(typ, label)] = s
        changes = {}
        for typ in (SEARCH, PMAX):
            a, b = res[(typ, "pre")], res[(typ, "post")]
            cpc_ok = all(x["clicks"] is not None and x["clicks"] >= mins["min_clicks"].value for x in (a, b))
            cpa_ok = all(x["conversions"] is not None and x["conversions"] >= mins["min_conversions"].value
                         for x in (a, b))
            cpc = [_cost_per(ctx, x["cost"], x["clicks"]) for x in (a, b)]
            cpa = [_cost_per(ctx, x["cost"], x["conversions"]) for x in (a, b)]
            changes[typ] = {
                "cpc_relative_change": V.ratio(cpc[1], cpc[0]) - 1 if cpc_ok and None not in cpc and cpc[0] else None,
                "cpa_relative_change": V.ratio(cpa[1], cpa[0]) - 1 if cpa_ok and None not in cpa and cpa[0] else None,
                "cpc_gate_passed": cpc_ok, "cpa_gate_passed": cpa_ok,
            }
            if typ == SEARCH and "search_impression_share" in a:
                imp_ok = all(x["impressions"] is not None and x["impressions"] >= mins["min_impressions"].value
                             for x in (a, b))
                sa, sb = a.get("search_impression_share"), b.get("search_impression_share")
                changes[typ]["search_is_pp_change"] = (sb - sa) * 100 if imp_ok and None not in (sa, sb) else None
        tot = {lab: _sums([r for cid, day, r in rows if cid in members[SEARCH] + members[PMAX] and a <= day <= b
                           and (not gset or str(r.get("goal_set_id")) in gset)], ctx)
               for lab, (a, b) in (("pre", pre), ("post", post))}
        alt = sorted({f"{r.get('campaign_id')}:{r.get('setting_id')}@{r.get('effective_from')}"
                      for r in ctx.rows(CONTROLS)
                      if V.parse_date(r.get("effective_from")) and pre[0] <= V.parse_date(r.get("effective_from")) <= post[1]
                      and str(r.get("campaign_id")) in ch})
        entity = {"goal_set": list(goals), "search_campaign_ids": members[SEARCH], "pmax_campaign_ids": members[PMAX]}
        calc = {"pre_window": list(pre), "post_window": list(post), "intervention_date": d,
                "intervention_source": dsrc, "periods": {f"{k[0]}_{k[1]}": v for k, v in res.items()},
                "comparable_total": tot, "changes": changes,
                "gates": {k: {"value": v.value, "source": v.source} for k, v in mins.items()}}
        computed = any(v is not None for c in changes.values() for k, v in c.items() if k.endswith("change"))
        if not computed:
            chk.observe(f"Goal set {list(goals)}: periods compared but no rate passed both-sided sample gates", **calc)
            continue
        f = chk.finding("search_pmax_shift_hypothesis", "Info", entity,
                        f"Search/PMax outcomes shifted around {d} ({n}-day mature periods); descriptive hypothesis "
                        f"only, no controlled causal evidence",
                        evidence={"concurrent_setting_changes": alt, "window_days": n}, calculation=calc,
                        recommendation="Inspect budgets, bids, eligibility, seasonality, tracking and demand before "
                                       "any structural change; a causal question needs a randomized holdout.",
                        uncertainty="Observational before/after comparison; attributed-conversion transfer can coexist "
                                    "with any incrementality.")
        out.append(f)
    chk.observe("Period shift screen", intervention_date=d, intervention_source=dsrc, window_days=n,
                pre=list(pre), post=list(post), last_mature_day=last_mature)
    return out


# ---------------------------------------------------------------------------------------------- step 3
def _query_overlap(ctx, ch) -> list:
    chk = ctx.check("query_overlap", "Directly observed query overlap and brand share",
                    {QUERIES: ["campaign_id", "date", "query_text", "reported_query_or_category_type",
                               "impressions", "clicks", "cost", "conversions"]})
    if not chk.runnable:
        chk.partial("without literal PMax query rows neither query overlap nor PMax brand share is measured")
        return []
    pmax_q: dict[str, dict[str, list]] = {}
    search_q: dict[str, set] = {}
    categories = 0
    for r in ctx.rows(QUERIES):
        cid = str(r.get("campaign_id"))
        typ = V.norm_text(r.get("reported_query_or_category_type"))
        q = V.norm_text(r.get("query_text"))
        if cid not in ch or not q:
            continue
        if typ not in QUERY_TYPES:
            if ch[cid] == PMAX:
                categories += 1
            continue
        if ch[cid] == PMAX:
            pmax_q.setdefault(cid, {}).setdefault(q, []).append(r)
        else:
            search_q.setdefault(q, set()).add(cid)
    search_source = "custom/search_pmax_queries"
    if not search_q:
        st = ctx.table("search_terms")
        if st is not None and not st.missing(["search_term", "campaign_id"]):
            search_source = "search_terms"
            for r in st.rows:
                cid = str(r.get("campaign_id"))
                if ch.get(cid) == SEARCH and r.get("search_term"):
                    search_q.setdefault(V.norm_text(r.get("search_term")), set()).add(cid)
        else:
            chk.partial("no Search query rows", ["search_terms:search_term"])
    metrics = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
    out = []
    for cid in sorted(pmax_q):
        qs = pmax_q[cid]
        tot = _sums([r for rs in qs.values() for r in rs], ctx)
        brand_rows = [r for q, rs in qs.items() if _brand(ctx, q) for r in rs]
        b = _sums(brand_rows, ctx)
        camp_clicks = V.num((metrics.get(cid) or {}).get("clicks"))
        shares = {m: V.ratio(b[m], tot[m]) for m in ("impressions", "clicks", "cost", "conversions")
                  if b[m] is not None and tot[m] is not None}
        chk.observe(f"PMax {cid}: brand share of VISIBLE literal query rows (not of all PMax traffic)",
                    campaign_id=cid, visible_queries=len(qs), brand_queries=len({q for q in qs if _brand(ctx, q)}),
                    brand_totals=b, visible_totals=tot, brand_shares=shares,
                    visible_click_coverage=V.ratio(tot["clicks"], camp_clicks), campaign_clicks=camp_clicks)
        overlap = sorted(q for q in qs if q in search_q)
        if overlap:
            detail = sorted(({"query": q, "search_campaign_ids": sorted(search_q[q]),
                              "pmax": _sums(qs[q], ctx)} for q in overlap),
                            key=lambda x: (-(x["pmax"]["cost"] or 0), x["query"]))
            out.append(chk.finding(
                "observed_query_overlap", "Info", {"pmax_campaign_id": cid},
                f"{len(overlap)} literal queries served by PMax {cid} also appear in Search query reports "
                f"({search_source}); overlap observed, simultaneous eligibility and causality not established",
                evidence={"overlapping_queries": detail[:50], "overlap_count": len(overlap),
                          "search_query_source": search_source},
                calculation={"visible_pmax_queries": len(qs), "overlap_share_of_visible_queries":
                             V.ratio(len(overlap), len(qs))},
                recommendation="Treat as a hypothesis; review routing with 018/002 before changing controls.",
                uncertainty="Visible query rows only; hidden queries and auction eligibility are unobserved."))
        if brand_rows and b["impressions"]:
            policy = _policy(ctx, cid)
            entity = {"pmax_campaign_id": cid}
            ev = {"brand_policy": _objective(ctx, cid).get("brand_policy"), "brand_totals": b,
                  "brand_queries": sorted({V.norm_text(r.get("query_text")) for r in brand_rows})[:50],
                  "brand_terms": list(ctx.profile.get("brand_terms") or [])}
            if policy in NONBRAND_POLICIES:
                chk.finding("brand_intent_control_mismatch", "Warning", entity,
                            f"PMax {cid} has documented brand policy '{policy}' but served "
                            f"{int(b['impressions'])} impressions on literal brand queries",
                            evidence=ev, calculation={"brand_share_of_visible": shares},
                            recommendation="Review brand exclusion scope/close variants with the brand owner (002); "
                                           "exposure is not savings.",
                            uncertainty="Served-query evidence proves the policy was not enforced, not incremental loss.")
            elif policy and policy not in OPEN_POLICIES:
                chk.review("brand_intent_control_mismatch", entity,
                           f"Does the documented brand policy '{policy}' for PMax {cid} exclude the brand queries "
                           f"it served?", evidence=ev,
                           outcomes={"control_mismatch": {"severity": "Warning", "recommendation":
                                                          "Review brand controls with the brand owner (002)."},
                                     "intended_participation": {"severity": None, "recommendation":
                                                                "Keep; brand participation is intended."},
                                     "uncertain": {"severity": "Info", "recommendation":
                                                   "Ask the client to document the PMax brand policy."}},
                           guidance="Judge only the documented policy text; control_mismatch needs proposal.evidence_ref.")
    chk.observe("Query evidence coverage", pmax_campaigns_with_queries=sorted(pmax_q),
                pmax_category_or_theme_rows=categories, search_query_source=search_source,
                search_visible_queries=len(search_q))
    return out


# ---------------------------------------------------------------------------------------------- step 4
def _channel_comparison(ctx, ch) -> list:
    chk = ctx.check("channel_comparison", "Total and per-channel comparable-goal outcomes",
                    {"campaign_metrics": ["campaign_id", "impressions", "clicks", "cost", "conversions"]})
    if not chk.runnable:
        return []
    t = ctx.table("campaign_metrics")
    seg = [c for c in ("goal_set_id", "date", "date_range_start", "date_range_end", "channel") if c in t.columns]
    seen, by = set(), {}
    dups = 0
    for r in t.rows:
        cid = str(r.get("campaign_id"))
        if cid not in ch:
            continue
        grain = (cid,) + tuple(str(r.get(c)) for c in seg)
        if grain in seen:
            dups += 1
            continue
        seen.add(grain)
        by.setdefault(cid, []).append(r)
    if dups:
        chk.partial(f"{dups} duplicate campaign_metrics rows at the same grain skipped")
    groups = {}
    for c, typ in ch.items():
        groups.setdefault(_goal_key(ctx, c), {SEARCH: [], PMAX: []})[typ].append(c)
    mins = ctx.params.get("min_conversions")
    out = []
    for goals, members in sorted(groups.items()):
        if not members[SEARCH] or not members[PMAX]:
            continue
        gset = set(goals)
        if not goals:
            chk.partial("campaign goal_ids undeclared: comparable goals unverified")
        side = {}
        for typ in (SEARCH, PMAX):
            rows = [r for c in members[typ] for r in by.get(c, [])
                    if "goal_set_id" not in t.columns or not gset or str(r.get("goal_set_id")) in gset]
            s = _sums(rows, ctx)
            s["cpa"] = _cost_per(ctx, s["cost"], s["conversions"])
            s["roas"] = V.ratio(s["conversion_value"], s["cost"])
            s["campaigns_with_rows"] = sorted({c for c in members[typ] if by.get(c)})
            side[typ] = s
        total = _sums([r for typ in (SEARCH, PMAX) for c in members[typ] for r in by.get(c, [])
                       if "goal_set_id" not in t.columns or not gset or str(r.get("goal_set_id")) in gset], ctx)
        entity = {"goal_set": list(goals), "search_campaign_ids": members[SEARCH], "pmax_campaign_ids": members[PMAX]}
        gate = all(side[x]["conversions"] is not None and side[x]["conversions"] >= mins.value for x in side)
        calc = {"search": side[SEARCH], "pmax": side[PMAX], "comparable_total": total,
                "window": [ctx.period_start, ctx.period_end], "min_conversions": mins.value,
                "min_conversions_source": mins.source, "both_sides_pass_gate": gate, "mature": ctx.mature}
        if ctx.mature is not True:
            chk.partial(f"maturity {ctx.mature}: descriptive totals only")
            chk.observe(f"Goal set {list(goals)}: descriptive Search/PMax totals (immature window)", **calc)
            continue
        if not gate:
            chk.observe(f"Goal set {list(goals)}: CPA/ROAS comparison withheld (min_conversions not met on both sides)",
                        **calc)
            continue
        out.append(chk.finding(
            "channel_outcome_difference", "Info", entity,
            f"Mature aggregate Search vs PMax outcomes on goals {list(goals)}: Search CPA "
            f"{side[SEARCH]['cpa']:.2f} vs PMax CPA {side[PMAX]['cpa']:.2f} {ctx.currency or ''}; descriptive "
            f"hypothesis screen only",
            evidence={"scope": "aggregate campaign totals, one window; no before/after or query evidence"},
            calculation=calc,
            recommendation="Do not reallocate or exclude on this difference; compare totals over time and, for a "
                           "causal question, design a randomized campaign/geo holdout.",
            uncertainty="Attributed channel CPA differences and Search share are descriptive; overlap and incrementality "
                        "are unmeasured in aggregate-only evidence."))
    return out


# ---------------------------------------------------------------------------------------------- step 5
def _brand_exclusions(ctx, ch) -> None:
    chk = ctx.check("brand_exclusion_state", "PMax brand exclusion state vs objective",
                    {CONTROLS: ["campaign_id", "channel", "brand_exclusions", "effective_from", "effective_to"]})
    if not chk.runnable:
        return
    ref = ctx.as_of or ctx.period_end
    current: dict[str, list] = {}
    for r in ctx.rows(CONTROLS):
        cid = str(r.get("campaign_id"))
        if ch.get(cid) != PMAX:
            continue
        a, b = V.parse_date(r.get("effective_from")), V.parse_date(r.get("effective_to"))
        if ref and ((a and a > ref) or (b and b < ref)):
            continue
        current.setdefault(cid, []).append(r)
    for cid in sorted(c for c, t in ch.items() if t == PMAX):
        rows = current.get(cid)
        if not rows:
            chk.partial(f"PMax {cid}: no current controls row; brand exclusion state unknown")
            continue
        raws = {str(r.get("brand_exclusions") or "").strip() for r in rows}
        if raws == {""}:
            chk.partial(f"PMax {cid}: brand_exclusions blank (unknown, not absent)")
            continue
        known_empty = all(x.lower() in EMPTY_TOKENS for x in raws if x)
        lists = sorted({v for x in raws if x.lower() not in EMPTY_TOKENS for v in V.split_list(x)})
        policy = _policy(ctx, cid)
        if not known_empty:
            chk.observe(f"PMax {cid}: brand exclusions configured", campaign_id=cid, brand_exclusions=lists)
            continue
        conflict = policy in NONBRAND_POLICIES
        chk.finding("pmax_brand_exclusions_absent", "Info", {"pmax_campaign_id": cid},
                    f"PMax {cid} has no brand exclusions" + (
                        f"; documented policy '{policy}' conflicts, corroborate with served-query evidence"
                        if conflict else "; no conflicting approved objective"),
                    evidence={"brand_policy": _objective(ctx, cid).get("brand_policy"), "as_of": ref,
                              "source_reference": sorted({str(r.get("source_reference")) for r in rows})},
                    recommendation="Not a defect by itself; preserve intentional brand participation. Route brand "
                                   "protection mismatches to 002.",
                    uncertainty="Exclusion settings do not show which brand queries PMax actually served.")


# ---------------------------------------------------------------------------------------------- step 6
def _causal(ctx, ch, hypotheses) -> None:
    chk = ctx.check("causal_evaluation", "Controlled causal evidence",
                    {EXPERIMENT: ["experiment_id", "arm", "date", "assignment_method", "estimator",
                                  "uncertainty_method", "analysis_window"]})
    if chk.runnable:
        exps: dict[str, list] = {}
        for r in ctx.rows(EXPERIMENT):
            exps.setdefault(str(r.get("experiment_id")), []).append(r)
        for eid in sorted(exps):
            rs = exps[eid]
            arms = sorted({str(r.get("arm")) for r in rs})
            chk.review("supplied_experiment_estimate", {"experiment_id": eid},
                       f"Does experiment {eid} support a causal estimate of PMax/Search overlap under its own "
                       f"assignment and estimator?",
                       evidence={"arms": arms, "assignment_method": sorted({str(r.get('assignment_method')) for r in rs}),
                                 "estimator": sorted({str(r.get("estimator")) for r in rs}),
                                 "uncertainty_method": sorted({str(r.get("uncertainty_method")) for r in rs}),
                                 "analysis_window": sorted({str(r.get("analysis_window")) for r in rs}),
                                 "rows": len(rs)},
                       outcomes={"supported_estimate": {"severity": "Info", "recommendation":
                                                        "Report the estimate with its interval."},
                                 "inconclusive": {"severity": "Info", "recommendation":
                                                  "Report as inconclusive; no causal claim."},
                                 "invalid_design": {"severity": "Info", "recommendation":
                                                    "Do not use; redesign with randomized assignment."}},
                       guidance="Use only the supplied assignment/estimator; supported_estimate needs proposal "
                                "{estimate, interval}.")
    else:
        chk.partial("no controlled comparison supplied: cannibalization cannot be concluded")
    if hypotheses and not ctx.table(EXPERIMENT):
        chk.review("holdout_design", {"search_campaign_ids": sorted(c for c, t in ch.items() if t == SEARCH),
                                      "pmax_campaign_ids": sorted(c for c, t in ch.items() if t == PMAX)},
                   "Is a randomized campaign/geo holdout warranted to test the observed Search/PMax hypothesis?",
                   evidence={"hypotheses": [f.id for f in hypotheses], "conditions": sorted({f.condition_key for f in hypotheses}),
                             "required_design_fields": list(HOLDOUT_FIELDS)},
                   outcomes={"propose_holdout": {"severity": "Info", "recommendation":
                                                 "Propose the specified holdout (request-only)."},
                             "no_test": {"severity": None, "recommendation": "Monitor descriptively."}},
                   guidance="propose_holdout needs proposal with every required_design_fields key; duration from "
                            "power and lag; never prescribe immediate brand exclusions.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: holdout proposals must be fully specified; estimates need interval; mismatch needs evidence_ref."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if item.condition_key == "holdout_design" and outcome == "propose_holdout":
        miss = [k for k in HOLDOUT_FIELDS if not proposal.get(k)]
        return [f"holdout proposal missing {', '.join(miss)}"] if miss else []
    if item.condition_key == "supplied_experiment_estimate" and outcome == "supported_estimate":
        return [] if proposal.get("estimate") is not None and proposal.get("interval") else [
            "supported_estimate needs proposal.estimate and proposal.interval from the supplied analysis"]
    if item.condition_key == "brand_intent_control_mismatch" and outcome == "control_mismatch":
        return [] if proposal.get("evidence_ref") else ["control_mismatch needs proposal.evidence_ref"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
