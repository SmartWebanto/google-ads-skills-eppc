"""check.py — skill-069 deterministic landing-page rating triage, URL attribution and supplied page evidence.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-069-landing-page-experience-assessment/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #102 Generate Landing Page performance report (Webmasterei/google_ads_landingpage_cats) — clean-room
         reimplementation of per-landing-page aggregation (impressions/clicks/cost/conversions/value, CTR/CVR/CPA)
         as check url_performance, from the recipe's custom/landing_url_performance at its declared grain.
         index #71 PMax Low-Performing Landing Page Alerts (nilsrooijmans.com) — clean-room reimplementation of
         "landing page with spend but no conversions" as Info hypothesis zero_conversion_landing_page (any channel,
         PMax labeled), gated by maturity, per-campaign tracking, spend_floor, min_clicks and converting peers.
rules:   LP rating is a diagnostic, never a speed/mobile/broken-page test; page claims need external checks.
         Keyword cost is assigned once: to its single settings/routing destination, else to an ambiguous set —
         never multiplied across eligible URLs or split by guess. URL report cost is a separate, non-additive
         measure and is never joined to weak-rated keywords. Expanded and unexpanded rows are never summed.
         Warning (deterministic) = BELOW_AVERAGE LP rating AND keyword cost >= spend_high for ITS campaign, or a
         supplied inaccessible check reproduced on >= 2 distinct checked_at with no later success on an intended
         destination. Critical only via ai_review; verify() demands proposal.evidence_ref and observed exposure.
         URL performance findings are Info at most (recipe has no URL-performance Warning row).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial deterministic check
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

SKILL = "skill-069-landing-page-experience-assessment"
VERSION = "1.0.0"

RATING_COL = "landing_page_experience"
_RATINGS = ("BELOW_AVERAGE", "AVERAGE", "ABOVE_AVERAGE")
_BAD_APPROVAL = ("DISAPPROVED", "NOT_ELIGIBLE", "REJECTED")
_METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
URL_NEEDS = ["campaign_id", "landing_page_url", "impressions", "clicks", "cost", "conversions"]
CHECK_NEEDS = ["requested_url", "final_url", "checked_at", "source", "status_code", "access_error"]


def _s(v) -> str:
    return str(v or "").strip()


def _rating(v) -> str | None:
    s = "_".join(_s(v).upper().replace("-", " ").split())
    return s if s in _RATINGS else None


def _active(row) -> bool:
    return _s(row.get("status")).upper() in ("", "ENABLED", "ACTIVE")


def _url(v) -> str:
    """Lowercase scheme/host, drop fragment, keep path and query parameters."""
    s = _s(v).split("#", 1)[0]
    if "://" in s:
        scheme, rest = s.split("://", 1)
        host, sep, path = rest.partition("/")
        s = f"{scheme.lower()}://{host.lower()}/{path}" if sep else f"{scheme.lower()}://{host.lower()}/"
    return s


def _metric(ctx, col, v):
    return ctx.money(v) if col in ("cost", "conversion_value") else V.num(v)


def _keywords(ctx) -> list[dict]:
    channel = {_s(c.get("id")): _s(c.get("channel_type")).upper() for c in ctx.rows("campaigns")}
    metrics: dict[tuple, dict] = {}
    for m in ctx.rows("keyword_metrics"):
        k = (_s(m.get("campaign_id")), _s(m.get("ad_group_id")), _s(m.get("keyword_id")))
        acc = metrics.setdefault(k, {c: None for c in _METRICS})
        for col in _METRICS:
            v = _metric(ctx, col, m.get(col))
            if v is not None:
                acc[col] = (acc[col] or 0) + v
    out = []
    for k in sorted(ctx.rows("keywords"), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("ad_group_id")), _s(r.get("id")))):
        cid, gid, kid = _s(k.get("campaign_id")), _s(k.get("ad_group_id")), _s(k.get("id"))
        if not _active(k) or channel.get(cid) not in (None, "", "SEARCH"):
            continue
        out.append({"campaign_id": cid, "ad_group_id": gid, "keyword_id": kid, "text": k.get("text"),
                    "rating": _rating(k.get(RATING_COL)), "override": _url(k.get("final_url")),
                    **(metrics.get((cid, gid, kid)) or {c: None for c in _METRICS})})
    return out


def run(ctx) -> None:
    """Run LP-rating exposure, routing, URL performance, accessibility and shared-destination checks.

    Rules:   Deterministic Warning only for BELOW_AVERAGE LP rating with keyword cost >= its campaign's spend_high, or
             an inaccessible check reproduced on >= 2 distinct checked_at with no later success; otherwise Info/partial.
             URL performance and zero-conversion pages are Info (maturity-gated); keyword cost is never multiplied
             across URLs. Critical only via ai_review with proposal.evidence_ref and observed exposure.
    """
    kw_needs = {"keywords": ["id", "campaign_id", "ad_group_id", RATING_COL],
                "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "cost"]}
    # -- step 1: rating inventory
    inv = ctx.check("lp_rating_inventory", "Landing-page experience ratings ranked by cost", kw_needs)
    kws = _keywords(ctx) if inv.runnable else []
    weak = [k for k in kws if k["rating"] == "BELOW_AVERAGE"]
    if inv.runnable:
        unknown = [k for k in kws if k["rating"] is None]
        low, pending, unresolved = {}, {}, set()
        for k in sorted(weak, key=lambda k: (-(k["cost"] or 0), k["campaign_id"], k["keyword_id"])):
            thr = ctx.params.get("spend_high", k["campaign_id"])
            ent = {"campaign_id": k["campaign_id"], "ad_group_id": k["ad_group_id"], "keyword_id": k["keyword_id"]}
            if thr.value is None or k["cost"] is None:
                if thr.value is None:
                    unresolved.add(f"{k['campaign_id']}: {thr.reason}")
                pending.setdefault(k["campaign_id"], []).append({**ent, "cost": k["cost"]})
            elif k["cost"] >= thr.value:
                inv.finding("below_average_lp_high_cost", "Warning", ent,
                            f"Keyword '{k['text']}' has Below Average landing-page experience with cost "
                            f"{k['cost']:.2f} {ctx.currency} >= spend_high {thr.value:g}",
                            evidence={"landing_page_experience": "BELOW_AVERAGE", "cost": k["cost"],
                                      "clicks": k["clicks"], "rating_snapshot": ctx.snapshot,
                                      "metric_window": [ctx.period_start, ctx.period_end]},
                            calculation={"threshold": "spend_high", "threshold_value": thr.value,
                                         "threshold_source": thr.source},
                            recommendation="Priority page investigation with supplied tests (078/079/034/141); "
                                           "no page or account change from the rating alone.",
                            uncertainty="The rating does not diagnose speed, mobile failure or bounce behavior.")
            else:
                low.setdefault(k["campaign_id"], []).append({**ent, "cost": k["cost"], "spend_high": thr.value})
        for u in sorted(unresolved):
            inv.partial(f"spend_high unresolved for campaign {u}")
        for cid in sorted(pending):
            inv.finding("below_average_lp_exposure_unresolved", "Info", {"campaign_id": cid},
                        f"{len(pending[cid])} Below Average LP keywords in campaign {cid} not classified against spend_high",
                        evidence={"keywords": pending[cid]}, recommendation="Resolve spend_high or supply metrics.",
                        uncertainty="Materiality not assessed.")
        for cid in sorted(low):
            inv.finding("low_exposure_lp_diagnostic", "Info", {"campaign_id": cid},
                        f"{len(low[cid])} Below Average LP keywords in campaign {cid} are below spend_high",
                        evidence={"keywords": low[cid]}, recommendation="Low-priority page review hypothesis.",
                        uncertainty="Low-exposure diagnostic only.")
        if unknown:
            inv.finding("lp_rating_unavailable", "Info", {"rating": "unavailable"},
                        f"{len(unknown)} of {len(kws)} active Search keywords have no LP rating",
                        evidence={"keyword_ids": [f"{k['campaign_id']}/{k['ad_group_id']}/{k['keyword_id']}" for k in unknown]},
                        recommendation="Treat as unknown.", uncertainty="N/A is not a failing page.")
        inv.observe("LP rating inventory", active_search_keywords=len(kws), rated=len(kws) - len(unknown),
                    below_average=len(weak), average=sum(1 for k in kws if k["rating"] == "AVERAGE"),
                    above_average=sum(1 for k in kws if k["rating"] == "ABOVE_AVERAGE"),
                    rating_snapshot=ctx.snapshot, metric_window=[ctx.period_start, ctx.period_end])

    # -- steps 2-3: route resolution (cost assigned once)
    route = ctx.check("route_resolution", "Keyword destination routes and attribution basis",
                      {**kw_needs, "ads": ["id", "campaign_id", "ad_group_id", "status", "final_url"]})
    dest_exposure: dict[str, dict] = {}
    routes: dict[tuple, dict] = {}
    if route.runnable:
        if "final_url" not in ctx.table("keywords").columns:
            route.partial("keyword URL overrides unknown", ["keywords:final_url"])
        ads: dict[tuple, set] = {}
        mobile = "mobile_final_url" in ctx.table("ads").columns
        for a in ctx.rows("ads"):
            if _active(a) and _s(a.get("approval_status")).upper() not in _BAD_APPROVAL:
                urls = ads.setdefault((_s(a.get("campaign_id")), _s(a.get("ad_group_id"))), set())
                for u in (_url(a.get("final_url")), _url(a.get("mobile_final_url")) if mobile else ""):
                    if u:
                        urls.add(u)
        hist: dict[tuple, list] = {}
        rt = ctx.table("custom/url_routing")
        rcols = ["campaign_id", "ad_group_id", "criterion_id", "effective_start", "effective_end", "resolved_destination"]
        if rt is not None and not rt.missing(rcols):
            for r in ctx.rows("custom/url_routing"):
                hist.setdefault((_s(r.get("campaign_id")), _s(r.get("ad_group_id")), _s(r.get("criterion_id"))), []).append(r)
        else:
            route.partial("no url_routing history: single destinations are settings-snapshot attributions")
        counts = {"routing_history": 0, "keyword_override": 0, "settings_single": 0, "ambiguous": 0, "unknown": 0}
        for k in kws:
            key = (k["campaign_id"], k["ad_group_id"], k["keyword_id"])
            h = hist.get(key)
            basis, dests = None, []
            if h:
                ds = {_url(r.get("resolved_destination")) for r in h}
                starts = [V.parse_date(r.get("effective_start")) for r in h]
                ends = [V.parse_date(r.get("effective_end")) for r in h]
                known_ends = [e for e in ends if e is not None]
                covers = (None not in starts and ctx.period_start is not None and ctx.period_end is not None
                          and min(starts) <= ctx.period_start
                          and (len(known_ends) < len(ends) or max(known_ends) >= ctx.period_end))
                if len(ds) == 1 and "" not in ds and covers:
                    basis, dests = "routing_history", sorted(ds)
            if basis is None and k["override"]:
                basis, dests = "keyword_override", [k["override"]]
            if basis is None:
                cand = sorted(ads.get(key[:2], set()))
                basis, dests = ("settings_single", cand) if len(cand) == 1 else (("ambiguous", cand) if cand else ("unknown", []))
            counts[basis] += 1
            routes[key] = {"basis": basis, "destinations": dests, "cost": k["cost"], "rating": k["rating"]}
            label = dests[0] if len(dests) == 1 else "AMBIGUOUS{" + " | ".join(dests) + "}" if dests else "UNKNOWN"
            e = dest_exposure.setdefault(label, {"keywords": 0, "ad_groups": set(), "cost": 0.0, "below_average": 0})
            e["keywords"] += 1
            e["ad_groups"].add("/".join(key[:2]))
            e["cost"] += k["cost"] or 0
            e["below_average"] += int(k["rating"] == "BELOW_AVERAGE")
        for label in sorted(dest_exposure):
            e = dest_exposure[label]
            route.observe(f"Keyword cost assigned once to destination {label}", destination=label,
                          keywords=e["keywords"], ad_groups=sorted(e["ad_groups"]), keyword_cost=e["cost"],
                          below_average_keywords=e["below_average"],
                          note="keyword-attributed exposure; not additive with URL report cost")
        route.observe("Attribution basis counts", **counts)
        amb = [{"campaign_id": k[0], "ad_group_id": k[1], "keyword_id": k[2], "candidates": r["destinations"],
                "cost": r["cost"]} for k, r in sorted(routes.items())
               if r["rating"] == "BELOW_AVERAGE" and r["basis"] in ("ambiguous", "unknown")]
        if amb:
            route.finding("ambiguous_routing", "Info", {"cohort": "below_average_lp"},
                          f"{len(amb)} Below Average LP keywords have ambiguous or unknown destinations",
                          evidence={"keywords": amb}, recommendation="Supply url_routing or URL checks before page claims.",
                          uncertainty="Cost is kept once under the ambiguous set; no per-URL split.")

    # -- step 4: URL report (index #102) and zero-conversion pages (index #71)
    urlp = ctx.check("url_performance", "Landing-page URL report (separate, non-additive measure)",
                     {"custom/landing_url_performance": URL_NEEDS})
    url_cost: dict[str, float] = {}
    if urlp.runnable:
        tbl = ctx.table("custom/landing_url_performance")
        grain = [c for c in ("account_id", "campaign_id", "date", "landing_page_url", "expanded_url", "device")
                 if c in tbl.columns]
        rows = ctx.rows("custom/landing_url_performance")
        kinds = {("expanded" in _s(r.get("source")).lower()) for r in rows}
        if kinds == {True, False}:
            rows = [r for r in rows if "expanded" not in _s(r.get("source")).lower()]
            urlp.partial("expanded and unexpanded report rows both supplied: expanded rows excluded, never summed")
        seen: dict[tuple, dict] = {}
        conflicts = 0
        for r in rows:
            g = tuple(_s(r.get(c)) for c in grain)
            if g in seen:
                if seen[g] is not None and seen[g] != r:
                    conflicts += 1
                    seen[g] = None
                continue
            seen[g] = r
        if conflicts:
            urlp.partial(f"{conflicts} conflicting rows at grain {grain} excluded")
        channel = {_s(c.get("id")): _s(c.get("channel_type")).upper() for c in ctx.rows("campaigns")}
        agg: dict[tuple, dict] = {}
        for g, r in sorted(seen.items()):
            if r is None:
                continue
            key = (_s(r.get("campaign_id")), _url(r.get("landing_page_url")))
            acc = agg.setdefault(key, {c: 0.0 for c in _METRICS} | {"unknown": 0})
            for col in _METRICS:
                v = _metric(ctx, col, r.get(col)) if col in tbl.columns else None
                if v is None:
                    acc["unknown"] += 1
                else:
                    acc[col] += v
        mi, mc, mv = (ctx.params.get(n).value for n in ("min_impressions", "min_clicks", "min_conversions"))
        mature = ctx.mature is True
        if not mature:
            urlp.partial(f"CVR/CPA and zero-conversion screening disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        for (cid, u), a in sorted(agg.items()):
            url_cost[u] = url_cost.get(u, 0.0) + a["cost"]
            urlp.observe(f"Landing page {u} in campaign {cid}", campaign_id=cid, landing_page_url=u,
                         channel=channel.get(cid), impressions=a["impressions"], clicks=a["clicks"], cost=a["cost"],
                         conversions=a["conversions"], conversion_value=a["conversion_value"],
                         ctr=V.ratio(a["clicks"], a["impressions"]) if a["impressions"] >= mi else None,
                         cvr=V.ratio(a["conversions"], a["clicks"]) if mature and a["clicks"] >= mc else None,
                         cpa=V.ratio(a["cost"], a["conversions"]) if mature and a["conversions"] >= mv else None,
                         unknown_cells=a["unknown"], attribution_basis="URL report (not keyword-attributed)")
        tracking_notes = set()
        for (cid, u), a in sorted(agg.items()):
            if not mature or a["conversions"] != 0 or a["unknown"] or a["clicks"] < mc:
                continue
            floor = ctx.params.get("spend_floor", cid)
            if floor.value is None or a["cost"] < floor.value:
                continue
            tracked, note = ctx.tracking_for_campaign(cid)
            if tracked is not True:
                tracking_notes.add(f"{cid}: {note}")
                continue
            peers = [(x, b) for x, b in agg.items() if x[0] == cid and x[1] != u]
            pc, pk = sum(b["conversions"] for _, b in peers), sum(b["clicks"] for _, b in peers)
            if pc <= 0 or pk < mc:
                continue
            urlp.finding("zero_conversion_landing_page", "Info", {"campaign_id": cid, "landing_page_url": u},
                         f"Landing page {u} spent {a['cost']:.2f} {ctx.currency} on {a['clicks']:g} clicks with 0 "
                         f"conversions while other pages in campaign {cid} converted ({pc:g}/{pk:g} clicks)",
                         evidence={"channel": channel.get(cid), "clicks": a["clicks"], "cost": a["cost"],
                                   "conversions": 0, "peer_conversions": pc, "peer_clicks": pk,
                                   "peer_cvr": V.ratio(pc, pk), "window": [ctx.period_start, ctx.period_end]},
                         calculation={"spend_floor": floor.value, "spend_floor_source": floor.source,
                                      "min_clicks": mc, "tracking": "verified for every campaign goal"},
                         recommendation="Optional page investigation hypothesis (content/offer/tracking on this "
                                        "page); no URL exclusion from this screen alone.",
                         uncertainty="URL report attribution; intent mix and lag can explain zero conversions.")
        for n in sorted(tracking_notes):
            urlp.partial(f"zero-conversion screening skipped for campaign {n}")

    # -- step 5: supplied page checks
    pc = ctx.check("page_checks", "Supplied page accessibility, usability and speed evidence",
                   {"external/landing_page_checks": CHECK_NEEDS})
    if pc.runnable:
        intended: dict[str, float] = {}
        for r in routes.values():
            for d in r["destinations"]:
                intended[d] = intended.get(d, 0.0) + ((r["cost"] or 0) if len(r["destinations"]) == 1 else 0)
        for u, c in url_cost.items():
            intended[u] = max(intended.get(u, 0.0), c)
        by_url: dict[str, list] = {}
        for r in ctx.rows("external/landing_page_checks"):
            by_url.setdefault(_url(r.get("requested_url")), []).append(r)
        if not routes and not url_cost:
            pc.partial("no route or URL exposure evidence: intended destinations unknown, no defect severity")
        for u in sorted(by_url):
            rs = sorted(by_url[u], key=lambda r: _s(r.get("checked_at")))
            fails, last_ok = [], None
            for r in rs:
                code = V.integer(r.get("status_code"))
                bad = _s(r.get("access_error")) != "" or (code is not None and code >= 400)
                if bad:
                    fails.append(r)
                elif code is not None and 200 <= code < 400:
                    last_ok = _s(r.get("checked_at"))
            perf = [{"metric": r.get("performance_metric_name"), "value": r.get("performance_metric_value"),
                     "unit": r.get("performance_metric_unit"), "field_or_lab": r.get("field_or_lab"),
                     "device": r.get("device"), "sample_window": r.get("sample_window"),
                     "sample_size": r.get("sample_size")} for r in rs if _s(r.get("performance_metric_name"))]
            pc.observe(f"Page checks for {u}", url=u, checks=len(rs), failing=len(fails), intended=u in intended,
                       exposure=intended.get(u), performance_metrics=perf,
                       note="speed → 078, broken URLs → 079, copy → 034, policy → 141")
            if u not in intended:
                continue
            ent = {"landing_page_url": u}
            ev = {"failing_checks": [{"checked_at": r.get("checked_at"), "status_code": r.get("status_code"),
                                      "access_error": r.get("access_error"), "final_url": r.get("final_url"),
                                      "redirect_chain": r.get("redirect_chain"), "source": r.get("source"),
                                      "method": r.get("method"), "environment": r.get("environment")} for r in fails],
                  "last_success_checked_at": last_ok, "exposure": intended.get(u)}
            recent_fail = fails and (last_ok is None or _s(fails[-1].get("checked_at")) > last_ok)
            reproduced = recent_fail and len({_s(r.get("checked_at")) for r in fails}) >= 2
            crit = {"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                   "Owner-reviewed urgent fix of the destination; cite the evidence."}}
            if reproduced:
                pc.finding("inaccessible_destination", "Warning", ent,
                           f"Destination {u} failed {len(fails)} supplied checks with no later success",
                           evidence=ev, recommendation="Owner-reviewed destination fix; route to 079.",
                           uncertainty="Checks cover the recorded times/environments only.")
                pc.review("inaccessible_destination_material", ent,
                          f"Is there direct evidence that the failing destination {u} caused MATERIAL delivery or "
                          f"journey failure (e.g. disapprovals, lost conversions in the failure interval)?",
                          evidence=ev, outcomes={**crit, "not_evidenced": {"severity": None,
                                                                           "recommendation": "Keep as Warning."}},
                          guidance="Critical requires proposal.evidence_ref to supplied evidence and exposure > 0.")
            elif recent_fail:
                prov = pc.finding("inaccessible_destination_unreproduced", "Info", ent,
                                  f"Destination {u} failed a single supplied check",
                                  evidence=ev, recommendation="Re-test on the intended device/environment.",
                                  uncertainty="One failing check may be transient.")
                pc.review("inaccessible_destination_unreproduced", ent,
                          f"Does supplied evidence reproduce the failure of {u} on the intended journey?",
                          evidence=ev, provisional=prov,
                          outcomes={**crit, "reproducible_defect": {"severity": "Warning", "recommendation":
                                                                     "Owner-reviewed fix; route to 079."},
                                    "transient_or_resolved": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Re-test."}},
                          guidance="Warning/Critical require proposal.evidence_ref; Critical also needs exposure > 0.")
            obs = [{"checked_at": r.get("checked_at"), "device": r.get("device"),
                    "mobile_usability_observation": r.get("mobile_usability_observation"),
                    "content_excerpt": r.get("content_excerpt"), "source": r.get("source")}
                   for r in rs if _s(r.get("mobile_usability_observation")) or _s(r.get("content_excerpt"))]
            if obs:
                pc.review("usability_content_defect", ent,
                          f"Do the supplied observations for {u} show a reproducible usability or offer/content "
                          f"defect affecting the intended journey?",
                          evidence={"observations": obs, "exposure": intended.get(u)},
                          outcomes={"reproducible_defect": {"severity": "Warning", "recommendation":
                                                            "Owner-reviewed page fix or focused test."},
                                    "no_defect": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Propose a focused page test."}},
                          guidance="Quote the observation; literal keyword absence is not a content gap. "
                                   "reproducible_defect requires proposal.evidence_ref.")

    # -- step 6: shared destinations (not defects)
    shr = ctx.check("shared_destinations", "Shared landing pages across keywords/ad groups (not defects)")
    if not dest_exposure:
        shr.skip("no resolved routes", route.missing or ["route_resolution unavailable"])
    for label in sorted(dest_exposure):
        e = dest_exposure[label]
        if len(e["ad_groups"]) > 1 and not label.startswith(("AMBIGUOUS", "UNKNOWN")):
            shr.observe(f"Destination {label} serves {len(e['ad_groups'])} ad groups", destination=label,
                        ad_groups=sorted(e["ad_groups"]), keywords=e["keywords"],
                        note="shared pages are acceptable when intents/offers align")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning/Critical page outcomes need proposal.evidence_ref; Critical also needs exposure > 0."""
    outcome = decision.get("outcome")
    if outcome not in ("material_failure_evidenced", "reproducible_defect"):
        return []
    problems = []
    if not _s((decision.get("proposal") or {}).get("evidence_ref")):
        problems.append("proposal.evidence_ref required (supplied check/trace reference)")
    if outcome == "material_failure_evidenced" and not (item.evidence.get("exposure") or 0) > 0:
        problems.append("Critical needs observed exposure > 0 on this destination")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
