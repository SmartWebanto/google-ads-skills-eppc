"""check.py — skill-078 deterministic landing-page speed evidence and testing priority.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-078-landing-page-speed/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #80 Check if campaign websites are live and respond fast enough (Siebe Hiemstra gist) — clean-room
           reimplementation of response-time screening: supplied lab ttfb_ms compared with the profile-supplied
           profile.lab_thresholds.ttfb_ms over repeated comparable runs (no fetching, no e-mail); liveness is 079's.
         index #106 Mobile Performance from PageSpeed Insights (Google) — clean-room reimplementation of per-URL,
           per-device (mobile evaluated separately) measurement prioritisation from SUPPLIED page_speed_results;
           no PageSpeed API call, and a Lighthouse score is never read as a conversion effect.
         skills/skill-079-broken-url-monitoring/scripts/check.py — same private URL normaliser / status helpers
rules:   Recommend-only; no network. Speed is judged ONLY from external/page_speed_results; an export-only run
         yields the traffic_priority testing list and marks speed unassessed (never a pass, never a finding).
         Destinations: explicit keyword final_url overrides win; keywords without one inherit their ad group's
         enabled-ad URL only when that URL is unique, else their exposure is unallocated (Info per ad group).
         Entity exposure is kept per entity type (ad / keyword override / inherited keyword) and NEVER summed
         across types (keyword and ad metrics describe the same clicks); ranking uses the max single-type cost.
         destination_map observed_url_clicks/cost (+attribution_method) are URL-level: used only when every row
         of a url_id carries one identical tuple; conflicting tuples are not summed (partial).
         Field Warning: source_kind field (CrUX/RUM), page scope, p75, measurement_status ok, on a url_id whose
         destination_map association_status is active; web.dev boundaries good LCP<=2500ms, INP<=200ms,
         CLS<=0.1, poor LCP>4000ms, INP>500ms, CLS>0.25. Null metric = unknown, never zero.
         Lab Warning: >=2 distinct run_ids under identical (url, device, network, cpu, cache, location) conditions
         ALL exceeding lab LCP 4000ms (the CWV poor boundary used as a triage heuristic) or the profile-supplied
         profile.lab_thresholds {tbt_ms, ttfb_ms}; absent profile thresholds → TBT/TTFB not judged.
         Failed/not-rendered measurements are Info routed to 079; Critical is unreachable here (needs 079
         functional evidence). Step 6 is the engineering_assignment observation (source, conditions, scope);
         no universal three-second page-load requirement is applied.
         untested_destination Info only when page_speed_results is manifest-complete; otherwise testing requests
         are an observation and the check is partial.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-078-landing-page-speed"
VERSION = "1.0.0"

DMAP = "external/destination_map"
PSR = "external/page_speed_results"
DMAP_CORE = ["campaign_id", "entity_type", "entity_id", "url_id", "final_url_sanitized", "association_status"]
DMAP_STEP1 = ["mobile_url_sanitized", "keyword_override", "expansion_status"]
OBSERVED = ["observed_url_clicks", "observed_url_cost", "attribution_method"]
GOOD = {"lcp_ms": 2500.0, "inp_ms": 200.0, "cls": 0.1}
POOR = {"lcp_ms": 4000.0, "inp_ms": 500.0, "cls": 0.25}
LAB_LCP_POOR = 4000.0
LAB_COND = ["network_profile", "cpu_profile", "cache_state"]
DEVICES_REQUESTED = ("desktop", "mobile")
TEST_CONDITIONS = ("field: page-scope p75 LCP/INP/CLS from CrUX or RUM with its stated rolling window; "
                   "lab: >=2 repeated runs per device under fixed network, CPU, cache and location profiles")
_LIVE = {"ENABLED", "ACTIVE", "SERVING", "ELIGIBLE"}
_DEAD = {"PAUSED", "REMOVED", "DISABLED", "INACTIVE", "NOT_SERVING", "ENDED", "SUSPENDED", "DELETED"}
_OK = {"ok", "valid", "complete", "completed", "success", "succeeded"}
_FAILED = {"failed", "fail", "error", "not_rendered", "render_failed", "rendering_failed", "timeout", "blocked",
           "unreachable", "crashed"}
_SEGMENTS = ("date", "day", "week", "month", "device", "network", "hour", "segment", "ad_network_type", "slot")


# ---------------------------------------------------------------- helpers
def _norm_url(u) -> str | None:
    """Lowercase scheme+host, drop fragment and default port, keep path, sort (never drop) query params."""
    s = str(u or "").strip()
    if not s or s.lower() in V.MISSING_TOKENS or "://" not in s:
        return None
    s = s.split("#", 1)[0]
    scheme, rest = s.split("://", 1)
    scheme = scheme.lower()
    cut = min([i for i in (rest.find("/"), rest.find("?")) if i >= 0] or [len(rest)])
    host, tail = rest[:cut].lower(), rest[cut:]
    if (scheme, host.rsplit(":", 1)[-1]) in (("http", "80"), ("https", "443")):
        host = host.rsplit(":", 1)[0]
    if not host:
        return None
    path, _, query = tail.partition("?")
    params = sorted(p for p in query.split("&") if p)
    return f"{scheme}://{host}{path or '/'}" + ("?" + "&".join(params) if params else "")


def _state(v) -> bool | None:
    s = str(v or "").strip().upper().replace(" ", "_")
    return True if s in _LIVE else False if s in _DEAD else None


def _tokens(v) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", str(v or "").lower())) - {""}


def _kind(v) -> str | None:
    t = _tokens(v)
    if t & {"field", "crux", "rum"}:
        return "field"
    if t & {"lab", "lighthouse", "webpagetest", "wpt", "synthetic"}:
        return "lab"
    return None


def _scope(v) -> str | None:
    t = _tokens(v)
    if t & {"page", "url"}:
        return "page"
    if t & {"origin", "domain", "site"}:
        return "origin"
    return None


def _mstatus(v) -> str | None:
    parts = [p for p in re.split(r"[^a-z0-9]+", str(v or "").lower()) if p]
    if not parts or " ".join(parts) in V.MISSING_TOKENS:
        return None
    raw = "_".join(parts)
    if raw in _OK:
        return "ok"
    if raw in _FAILED or set(parts) & {"failed", "fail", "error", "timeout", "blocked", "unreachable"}:
        return "failed"
    return "other"


def _is_p75(v) -> bool | None:
    s = str(v or "").strip().lower()
    if not s or s in V.MISSING_TOKENS:
        return None
    f = V.num(s.lstrip("p"))
    return None if f is None else f in (75.0, 0.75)


def _band(metric: str, value: float | None) -> str | None:
    if value is None:
        return None
    return "poor" if value > POOR[metric] else "needs_improvement" if value > GOOD[metric] else "good"


def _live_ids(ctx, key: str) -> dict[str, bool | None]:
    t = ctx.table(key)
    if t is None or "id" not in t.columns or "status" not in t.columns:
        return {}
    return {str(r.get("id")): _state(r.get("status")) for r in t.rows if r.get("id") is not None}


def _metric_sums(ctx, key: str, id_col: str):
    """Per-entity clicks/cost. Rules: duplicate grains (no segment column distinguishes them) are excluded."""
    t = ctx.table(key)
    if t is None:
        return None, [f"{key} (file)"], []
    miss = t.missing([id_col, "clicks", "cost"])
    if miss:
        return None, [f"{key}:{c}" for c in miss], []
    seg = [c for c in t.columns if c in _SEGMENTS]
    seen, dup, unknown, out = set(), set(), set(), {}
    for r in t.rows:
        eid = str(r.get(id_col) or "")
        if not eid:
            continue
        g = (eid,) + tuple(str(r.get(c)) for c in seg)
        if g in seen:
            dup.add(eid)
        seen.add(g)
        clicks, cost = V.num(r.get("clicks")), ctx.money(r.get("cost"))
        if clicks is None or cost is None:
            unknown.add(eid)
            continue
        acc = out.setdefault(eid, [0.0, 0.0])
        acc[0] += clicks
        acc[1] += cost
    notes = []
    for eid in sorted(dup | unknown):
        out.pop(eid, None)
    if dup:
        notes.append(f"{t.filename}: duplicate rows for {sorted(dup)} excluded (grain ambiguous; no fan-out)")
    if unknown:
        notes.append(f"{t.filename}: unknown clicks/cost for {sorted(unknown)} excluded")
    return out, [], notes


def _dmap_index(ctx) -> dict | None:
    """url_id → {url, campaigns, live, entities, observed}. None when the map lacks core columns."""
    t = ctx.table(DMAP)
    if t is None or t.missing(DMAP_CORE):
        return None
    has_obs = not t.missing(OBSERVED)
    idx: dict[str, dict] = {}
    for r in t.rows:
        uid = str(r.get("url_id") or "")
        if not uid:
            continue
        d = idx.setdefault(uid, {"urls": set(), "campaigns": set(), "states": [], "entities": set(), "obs": set()})
        u = _norm_url(r.get("final_url_sanitized"))
        if u:
            d["urls"].add(u)
        if r.get("campaign_id") is not None:
            d["campaigns"].add(str(r.get("campaign_id")))
        d["states"].append(_state(r.get("association_status")))
        d["entities"].add((str(r.get("entity_type") or "").lower(), str(r.get("entity_id") or "")))
        if has_obs and r.get("attribution_method"):
            d["obs"].add((V.num(r.get("observed_url_clicks")), ctx.money(r.get("observed_url_cost")),
                          str(r.get("attribution_method")), r.get("window_start"), r.get("window_end")))
    for d in idx.values():
        st = d.pop("states")
        d["live"] = True if True in st else False if st and all(x is False for x in st) else None
        d["url"] = sorted(d["urls"])[0] if len(d["urls"]) == 1 else None
        obs = d.pop("obs")
        d["observed"] = next(iter(obs)) if len(obs) == 1 else None
        d["observed_conflict"] = len(obs) > 1
    return idx


def _psr_rows(ctx) -> list[dict]:
    return sorted(ctx.rows(PSR), key=lambda r: (str(r.get("url_id")), str(r.get("device_class")),
                                                str(r.get("run_id")), str(r.get("source_kind"))))


# ---------------------------------------------------------------- run
def run(ctx) -> None:
    """Run destination resolution, priority, separation, field CWV, lab, assignment, render and testing-request steps.

    Rules:   Speed only from external/page_speed_results; an export-only run yields a testing list, never a pass or
             finding. Field Warning needs CrUX/RUM page-scope p75 (status ok, active url_id) beyond web.dev poor
             boundaries; lab Warning needs >= 2 run_ids under identical conditions all over LCP 4000ms (TBT/TTFB only
             via profile.lab_thresholds). Render failures are Info routed to 079; no Critical; untested_destination
             needs manifest-complete results.
    """
    dmap = _dmap_index(ctx)
    _step1_resolution(ctx)
    records = _step2_priority(ctx, dmap)
    _step3_separation(ctx)
    field = _step4_field(ctx, dmap)
    lab = _step5_lab(ctx, dmap)
    _step6_assignment(ctx, field, lab)
    _step7_render(ctx, dmap)
    _step8_requests(ctx, dmap, records)


def _step1_resolution(ctx) -> None:
    c = ctx.check("destination_resolution", "Resolve ad, keyword-override, mobile, asset and expansion destinations",
                  {DMAP: DMAP_CORE})
    if not c.runnable:
        return
    t = ctx.table(DMAP)
    missing = [f"{DMAP}:{col}" for col in t.missing(DMAP_STEP1)]
    if missing:
        c.partial("override/mobile/expansion evidence absent: destinations resolved from final URLs only", missing)
    by_type: dict[str, dict[str, int]] = {}
    per_entity: dict[tuple, set] = {}
    unresolved = []
    for r in sorted(t.rows, key=lambda r: (str(r.get("url_id")), str(r.get("entity_type")), str(r.get("entity_id")))):
        et = str(r.get("entity_type") or "unknown").lower()
        st = _state(r.get("association_status"))
        key = "active" if st else "inactive" if st is False else "unknown"
        by_type.setdefault(et, {"active": 0, "inactive": 0, "unknown": 0})[key] += 1
        per_entity.setdefault((et, str(r.get("entity_id"))), set()).add(str(r.get("url_id")))
        if _norm_url(r.get("final_url_sanitized")) is None:
            unresolved.append(str(r.get("url_id")))
    multi = sorted(f"{et}:{eid}" for (et, eid), uids in per_entity.items() if len(uids) > 1)
    mobile = sorted({_norm_url(r.get("mobile_url_sanitized")) for r in t.rows if "mobile_url_sanitized" in t.columns}
                    - {None})
    expansion = {}
    if "expansion_status" in t.columns:
        for r in t.rows:
            k = str(r.get("expansion_status") or "unknown").lower()
            expansion[k] = expansion.get(k, 0) + 1
    mapped_ads = {eid for et, eid in per_entity if et == "ad"}
    unmapped_ads = sorted(aid for aid, st in _live_ids(ctx, "ads").items() if st is not False and aid not in mapped_ads)
    if unmapped_ads:
        c.partial(f"{len(unmapped_ads)} non-paused ads in ads.csv have no destination_map row: {unmapped_ads}")
    c.observe("Destination inventory resolved from destination_map", rows=len(t.rows), by_entity_type=by_type,
              url_ids=len({str(r.get('url_id')) for r in t.rows}), entities_with_multiple_url_ids=multi,
              unresolved_url_ids=sorted(set(unresolved)), mobile_urls=mobile, expansion_status=expansion,
              rule="Entity spend is never spread across every possible URL; multi-URL entities stay unallocated.")


def _step2_priority(ctx, dmap) -> dict:
    ads_t = ctx.table("ads")
    url_col = "final_urls" if ads_t is not None and "final_url" not in ads_t.columns and "final_urls" in ads_t.columns \
        else "final_url"
    c = ctx.check("traffic_priority", "Prioritise destinations by observed URL traffic or unallocated exposure",
                  {"ads": ["id", "campaign_id", "ad_group_id", "status", url_col]})
    if not c.runnable:
        return {}
    camp, groups = _live_ids(ctx, "campaigns"), _live_ids(ctx, "ad_groups")

    def paused(r) -> bool:
        return _state(r.get("status")) is False or camp.get(str(r.get("campaign_id"))) is False \
            or groups.get(str(r.get("ad_group_id"))) is False

    rec: dict[str, dict] = {}

    def slot(u: str) -> dict:
        return rec.setdefault(u, {"url": u, "campaign_ids": set(), "ad_ids": set(), "override_keyword_ids": set(),
                                  "inherited_keyword_ids": set(), "asset_ids": set(), "below_average_keyword_ids": set(),
                                  "ad": [0.0, 0.0], "keyword_override": [0.0, 0.0], "keyword_inherited": [0.0, 0.0]})

    ad_m, ad_miss, ad_notes = _metric_sums(ctx, "ad_metrics", "ad_id")
    kw_m, kw_miss, kw_notes = _metric_sums(ctx, "keyword_metrics", "keyword_id")
    for n in ad_notes + kw_notes:
        c.partial(n)
    if ad_miss:
        c.partial("ad-level exposure unavailable", ad_miss)
    if kw_miss:
        c.partial("keyword-level exposure unavailable", kw_miss)

    group_urls: dict[tuple, set] = {}
    unallocated: dict[tuple, dict] = {}
    unresolved_ads = []
    for r in sorted(ads_t.rows, key=lambda r: str(r.get("id"))):
        if paused(r):
            continue
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id")))
        raw = V.split_list(r.get(url_col), (" | ", ";", "|")) if url_col == "final_urls" else [r.get(url_col)]
        urls = sorted({u for u in (_norm_url(x) for x in raw) if u})
        if not urls:
            unresolved_ads.append(str(r.get("id")))
            continue
        group_urls.setdefault(key, set()).update(urls)
        aid = str(r.get("id"))
        if len(urls) > 1:
            u = unallocated.setdefault(key, {"urls": set(), "ad_ids": set(), "keyword_ids": set(),
                                             "ad_cost": 0.0, "keyword_cost": 0.0})
            u["urls"].update(urls)
            u["ad_ids"].add(aid)
            if ad_m and aid in ad_m:
                u["ad_cost"] += ad_m[aid][1]
            continue
        s = slot(urls[0])
        s["ad_ids"].add(aid)
        s["campaign_ids"].add(key[0])
        if ad_m and aid in ad_m:
            s["ad"][0] += ad_m[aid][0]
            s["ad"][1] += ad_m[aid][1]
    if unresolved_ads:
        c.partial(f"ads with no resolvable final URL: {unresolved_ads}", [f"ads:{url_col}"])

    kw_t = ctx.table("keywords")
    kw_need = ["id", "campaign_id", "ad_group_id", "status", "final_url"]
    below_col = False
    if kw_t is None or kw_t.missing(kw_need):
        c.partial("keyword overrides/inheritance not resolved",
                  ["keywords (file)"] if kw_t is None else [f"keywords:{x}" for x in kw_t.missing(kw_need)])
    else:
        below_col = "landing_page_experience" in kw_t.columns
        if not below_col:
            c.partial("Below Average landing-page ratings unavailable", ["keywords:landing_page_experience"])
        for r in sorted(kw_t.rows, key=lambda r: str(r.get("id"))):
            if paused(r):
                continue
            kid, key = str(r.get("id")), (str(r.get("campaign_id")), str(r.get("ad_group_id")))
            own = _norm_url(r.get("final_url"))
            if own:
                u, kind = own, "keyword_override"
            elif len(group_urls.get(key, ())) == 1:
                u, kind = next(iter(group_urls[key])), "keyword_inherited"
            else:
                if group_urls.get(key):
                    x = unallocated.setdefault(key, {"urls": set(), "ad_ids": set(), "keyword_ids": set(),
                                                     "ad_cost": 0.0, "keyword_cost": 0.0})
                    x["urls"].update(group_urls[key])
                    x["keyword_ids"].add(kid)
                    if kw_m and kid in kw_m:
                        x["keyword_cost"] += kw_m[kid][1]
                continue
            s = slot(u)
            s["override_keyword_ids" if kind == "keyword_override" else "inherited_keyword_ids"].add(kid)
            s["campaign_ids"].add(key[0])
            if kw_m and kid in kw_m:
                s[kind][0] += kw_m[kid][0]
                s[kind][1] += kw_m[kid][1]
            if below_col and "_".join(str(r.get("landing_page_experience") or "").upper().split()) == "BELOW_AVERAGE":
                s["below_average_keyword_ids"].add(kid)

    assets = ctx.table("assets")
    a_col = next((x for x in ("final_url", "final_urls", "url") if assets is not None and x in assets.columns), None)
    if assets is None or a_col is None or "id" not in assets.columns:
        c.partial("asset (e.g. sitelink) destinations not included",
                  ["assets (file)"] if assets is None else [f"assets:{x}" for x in (["id"] if "id" not in assets.columns
                                                                                  else []) + ([] if a_col else ["final_url"])])
    else:
        for r in sorted(assets.rows, key=lambda r: str(r.get("id"))):
            if _state(r.get("status")) is False:
                continue
            for u in sorted({x for x in (_norm_url(v) for v in V.split_list(r.get(a_col), (" | ", ";", "|"))) if x}):
                slot(u)["asset_ids"].add(str(r.get("id")))

    # observed URL traffic from destination_map (URL-level, identical per url_id)
    observed: dict[str, tuple] = {}
    if dmap is not None:
        t = ctx.table(DMAP)
        if not t.missing(OBSERVED):
            for uid, d in sorted(dmap.items()):
                if d["observed_conflict"]:
                    c.partial(f"destination_map url_id {uid}: conflicting observed_url_* values not summed")
                elif d["observed"] and d["url"] and d["observed"][0] is not None and d["observed"][1] is not None:
                    observed[d["url"]] = d["observed"] + (uid,)

    out = []
    for u in sorted(rec):
        s = rec[u]
        types = {k: ({"clicks": s[k][0], "cost": s[k][1]} if (ad_m if k == "ad" else kw_m) is not None else None)
                 for k in ("ad", "keyword_override", "keyword_inherited")}
        known = [v for v in types.values() if v is not None]
        row = {"url": u, "campaign_ids": sorted(s["campaign_ids"]), "ad_ids": sorted(s["ad_ids"]),
               "override_keyword_ids": sorted(s["override_keyword_ids"]),
               "inherited_keyword_ids": sorted(s["inherited_keyword_ids"]), "asset_ids": sorted(s["asset_ids"]),
               "below_average_keyword_ids": sorted(s["below_average_keyword_ids"]),
               "entity_exposure_by_type": types, "speed_status": "unassessed"}
        if u in observed:
            clicks, cost, method, ws, we, uid = observed[u]
            row.update(basis="observed URL traffic", rank_cost=cost, rank_clicks=clicks,
                       observed={"url_id": uid, "clicks": clicks, "cost": cost, "attribution_method": method,
                                 "window": [ws, we]})
        else:
            best = max(known, key=lambda v: (v["cost"], v["clicks"])) if known else None
            row.update(basis="unallocated entity exposure (max single entity type; types overlap, never summed)",
                       rank_cost=best["cost"] if best else None, rank_clicks=best["clicks"] if best else None)
        out.append(row)
    out.sort(key=lambda r: (-(r["rank_cost"] or 0.0), -(r["rank_clicks"] or 0.0), r["url"]))
    for i, r in enumerate(out, 1):
        r["priority"] = i
    window = [ctx.period_start, ctx.period_end]
    c.observe("Testing-priority list (export-derived; speed unassessed until measurements are supplied)",
              destinations=out, window=window, currency=ctx.currency,
              note="Exposure is historical entity exposure, not savings or URL-attributed spend.")

    for r in out:
        if not r["below_average_keyword_ids"]:
            continue
        c.finding("below_average_lp_testing_priority", "Info", {"url": r["url"], "campaign_ids": r["campaign_ids"]},
                  f"{len(r['below_average_keyword_ids'])} enabled keyword(s) rated Below Average landing-page "
                  f"experience point to {r['url']} (priority #{r['priority']})",
                  evidence={"keyword_ids": r["below_average_keyword_ids"], "priority": r["priority"],
                            "entity_exposure_by_type": r["entity_exposure_by_type"], "window": window,
                            "currency": ctx.currency, "source": "keywords.landing_page_experience"},
                  calculation={"rule": "landing_page_experience == BELOW_AVERAGE on enabled keywords resolved to URL"},
                  recommendation="Include this URL in the speed testing request (mobile and desktop); the rating "
                                 "motivates testing only and is not a speed diagnosis.",
                  uncertainty="Quality Score component is a proxy: it can reflect relevance or usability, not speed.",
                  owner="account manager → web engineering")
    for key in sorted(unallocated):
        u = unallocated[key]
        c.finding("unallocated_entity_exposure", "Info", {"campaign_id": key[0], "ad_group_id": key[1]},
                  f"Ad group {key[1]} sends traffic to {len(u['urls'])} candidate URLs; entity exposure cannot be "
                  "allocated to one destination",
                  evidence={"candidate_urls": sorted(u["urls"]), "ad_ids": sorted(u["ad_ids"]),
                            "keyword_ids": sorted(u["keyword_ids"]),
                            "unallocated_entity_cost": {"ad": u["ad_cost"] if ad_m is not None else None,
                                                        "keyword": u["keyword_cost"] if kw_m is not None else None},
                            "window": window, "currency": ctx.currency},
                  calculation={"rule": "keywords without override in a group whose enabled ads resolve to >1 URL, "
                                       "or ads with >1 final URL"},
                  recommendation="Test every candidate URL; request URL-level click evidence (destination_map "
                                 "observed_url_*) before ranking these destinations by spend.",
                  uncertainty="Exposure is unallocated entity cost, not URL spend.", owner="account manager")
    return {r["url"]: r for r in out}


def _step3_separation(ctx) -> None:
    c = ctx.check("evidence_separation", "Separate field/lab, page/origin, device and conditions",
                  {PSR: ["url_id", "device_class", "source_kind", "run_id", "page_or_origin_scope", "percentile",
                         "measurement_status"]})
    if not c.runnable:
        return
    rows = _psr_rows(ctx)
    t = ctx.table(PSR)
    counts: dict[str, int] = {}
    per_url: dict[str, dict] = {}
    unknown_kind = 0
    lab_rows = 0
    for r in rows:
        k, sc = _kind(r.get("source_kind")), _scope(r.get("page_or_origin_scope"))
        dev = str(r.get("device_class") or "unknown").lower()
        if k is None:
            unknown_kind += 1
        lab_rows += k == "lab"
        label = f"{k or 'unknown'}|{sc or 'unknown'}|{dev}"
        counts[label] = counts.get(label, 0) + 1
        d = per_url.setdefault(str(r.get("url_id")), {"field_page": 0, "field_origin": 0, "lab": 0, "devices": set()})
        d["devices"].add(dev)
        if k == "field" and sc == "page":
            d["field_page"] += 1
        elif k == "field" and sc == "origin":
            d["field_origin"] += 1
        elif k == "lab":
            d["lab"] += 1
    if unknown_kind:
        c.partial(f"{unknown_kind} rows with unrecognised source_kind not classified as field or lab")
    if lab_rows and t.missing(LAB_COND):
        c.partial("lab conditions unknown: runs cannot be compared", [f"{PSR}:{x}" for x in t.missing(LAB_COND)])
    for uid in sorted(per_url):
        d = per_url[uid]
        if d["field_origin"] and not d["field_page"]:
            c.finding("origin_only_evidence", "Info", {"url_id": uid},
                      f"url_id {uid} has only origin-scope field evidence; page-level experience is unmeasured",
                      evidence={"origin_rows": d["field_origin"], "lab_rows": d["lab"], "devices": sorted(d["devices"])},
                      calculation={"rule": "field rows present, all page_or_origin_scope == origin"},
                      recommendation="Request page-level CrUX/RUM p75 for this URL before any speed verdict.",
                      uncertainty="Origin aggregates mix many pages; they cannot be attributed to this destination.",
                      owner="web analytics")
    c.observe("Measurement evidence classified (field vs lab, page vs origin, device)", classes=counts,
              url_ids=len(per_url), note="A Lighthouse/lab score is not a measured conversion effect.")


def _step4_field(ctx, dmap) -> list[dict]:
    c = ctx.check("field_cwv", "Field p75 LCP/INP/CLS against Core Web Vitals boundaries",
                  {PSR: ["url_id", "device_class", "source_kind", "page_or_origin_scope", "percentile", "lcp_ms",
                         "inp_ms", "cls", "field_window_start", "field_window_end", "measurement_status"],
                   DMAP: ["url_id", "association_status"]})
    out: list[dict] = []
    if not c.runnable:
        return out
    excluded = {"not_p75": 0, "status_not_ok": 0, "unknown_metric_rows": 0}
    within, not_relevant = [], []
    for r in _psr_rows(ctx):
        if _kind(r.get("source_kind")) != "field" or _scope(r.get("page_or_origin_scope")) != "page":
            continue
        if _is_p75(r.get("percentile")) is not True:
            excluded["not_p75"] += 1
            continue
        if _mstatus(r.get("measurement_status")) != "ok":
            excluded["status_not_ok"] += 1
            continue
        uid, dev = str(r.get("url_id")), str(r.get("device_class") or "unknown").lower()
        vals = {"lcp_ms": V.num(r.get("lcp_ms")), "inp_ms": V.num(r.get("inp_ms")), "cls": V.num(r.get("cls"))}
        bands = {m: _band(m, v) for m, v in vals.items()}
        if None in bands.values():
            excluded["unknown_metric_rows"] += 1
        over = {m: b for m, b in bands.items() if b in ("needs_improvement", "poor")}
        d = (dmap or {}).get(uid)
        if not over:
            within.append({"url_id": uid, "device_class": dev, "bands": bands})
            continue
        if d is None or d["live"] is not True:
            not_relevant.append({"url_id": uid, "device_class": dev, "bands": bands,
                                 "association": None if d is None else d["live"]})
            continue
        window = [r.get("field_window_start"), r.get("field_window_end")]
        entity = {"url_id": uid, "device_class": dev, "run_id": r.get("run_id"), "campaign_ids": sorted(d["campaigns"])}
        ev = {"url": d["url"], "values": vals, "bands": bands, "field_window": window, "percentile": "p75",
              "source_name": r.get("source_name"), "sample_size": V.num(r.get("sample_size")),
              "source_reference": r.get("source_reference"), "thresholds": {"good": GOOD, "poor": POOR},
              "threshold_source": "web.dev Core Web Vitals (recipe step 4)"}
        c.finding("field_cwv_exceeds_boundary", "Warning", entity,
                  f"Field p75 on {dev} for url_id {uid} exceeds the good boundary: "
                  + ", ".join(f"{m} {vals[m]:g} ({b})" for m, b in sorted(over.items())),
                  evidence=ev, calculation={"rule": "metric > good boundary; > poor boundary → poor"},
                  recommendation="Assign to web engineering with the field source, window, device and URL scope; "
                                 "diagnose with repeated lab runs under matching conditions.",
                  uncertainty="Field p75 describes the measured population and window; no conversion uplift implied.",
                  owner="web engineering")
        out.append({"source": "field", "url_id": uid, "url": d["url"], "device_class": dev, "metrics": over,
                    "window": window, "source_reference": r.get("source_reference")})
    if excluded["not_p75"] or excluded["status_not_ok"]:
        c.partial(f"field rows not evaluated: {excluded['not_p75']} not p75, {excluded['status_not_ok']} status not ok")
    c.observe("Field Core Web Vitals evaluated", warnings=len(out), within_good=within,
              exceeding_but_not_active_destination=not_relevant, excluded=excluded,
              note="Null metrics are unknown, not zero.")
    return out


def _step5_lab(ctx, dmap) -> list[dict]:
    c = ctx.check("lab_repeatability", "Repeatable lab bottlenecks under comparable conditions",
                  {PSR: ["url_id", "device_class", "source_kind", "run_id", "lcp_ms", "measurement_status"] + LAB_COND,
                   DMAP: ["url_id", "association_status"]})
    out: list[dict] = []
    if not c.runnable:
        return out
    t = ctx.table(PSR)
    cond_cols = LAB_COND + (["location_class"] if "location_class" in t.columns else [])
    thr = ctx.profile.get("lab_thresholds") if isinstance(ctx.profile.get("lab_thresholds"), dict) else {}
    limits = {"lcp_ms": (LAB_LCP_POOR, "CWV poor LCP boundary used as lab triage heuristic")}
    for m, col in (("tbt_ms", "lab_tbt_ms"), ("ttfb_ms", "ttfb_ms")):
        v = V.num(thr.get(m))
        if v is not None and v > 0 and col in t.columns:
            limits[col] = (v, f"profile.lab_thresholds.{m}")
    if len(limits) == 1:
        c.observe("TBT/TTFB not judged: profile.lab_thresholds {tbt_ms, ttfb_ms} not supplied (or columns absent)")
    groups: dict[tuple, dict] = {}
    for r in _psr_rows(ctx):
        if _kind(r.get("source_kind")) != "lab" or _mstatus(r.get("measurement_status")) != "ok":
            continue
        key = (str(r.get("url_id")), str(r.get("device_class") or "unknown").lower()) + tuple(
            str(r.get(x) or "unknown") for x in cond_cols)
        groups.setdefault(key, {})[str(r.get("run_id"))] = r
    single, variable, inactive = [], [], []
    for key in sorted(groups):
        runs = groups[key]
        uid, dev = key[0], key[1]
        cond = dict(zip(cond_cols, key[2:]))
        if len(runs) < 2:
            single.append({"url_id": uid, "device_class": dev, "conditions": cond})
            continue
        over = {}
        for col, (limit, src) in sorted(limits.items()):
            vals = [V.num(runs[rid].get(col)) for rid in sorted(runs)]
            if None not in vals and all(v > limit for v in vals):
                over[col] = {"values": vals, "limit": limit, "source": src}
        if not over:
            variable.append({"url_id": uid, "device_class": dev, "conditions": cond, "runs": len(runs)})
            continue
        d = (dmap or {}).get(uid)
        if d is None or d["live"] is not True:
            inactive.append({"url_id": uid, "device_class": dev, "metrics": sorted(over)})
            continue
        entity = {"url_id": uid, "device_class": dev, "conditions": cond, "campaign_ids": sorted(d["campaigns"])}
        c.finding("repeatable_lab_bottleneck", "Warning", entity,
                  f"{len(runs)} comparable lab runs on {dev} for url_id {uid} all exceed: " + ", ".join(sorted(over)),
                  evidence={"url": d["url"], "run_ids": sorted(runs), "metrics": over, "conditions": cond,
                            "source_references": sorted({str(runs[x].get('source_reference')) for x in runs})},
                  calculation={"rule": "every run in the comparable-condition group > limit; >=2 runs"},
                  recommendation="Investigate the bottleneck with engineering under the recorded conditions; "
                                 "confirm population impact with field p75 data before prioritising fixes.",
                  uncertainty="Lab runs cannot establish field INP or population experience; heuristic thresholds.",
                  owner="web engineering")
        out.append({"source": "lab", "url_id": uid, "url": d["url"], "device_class": dev, "metrics": sorted(over),
                    "conditions": cond})
    if single:
        c.partial(f"{len(single)} lab condition groups have a single run; repeatability unassessed")
    c.observe("Lab runs grouped by comparable conditions", groups=len(groups), repeat_runs_needed=single,
              variable_or_within_limits=variable, exceeding_but_not_active_destination=inactive,
              devices=sorted({k[1] for k in groups}))
    return out


def _step6_assignment(ctx, field: list, lab: list) -> None:
    f = next(x for x in ctx.result.checks if x.id == "field_cwv")
    lb = next(x for x in ctx.result.checks if x.id == "lab_repeatability")
    c = ctx.check("engineering_assignment", "Assign measured bottlenecks to engineering with source and scope")
    if not f.runnable and not lb.runnable:
        c.skip("no measured bottleneck evidence", sorted(set(f.missing) | set(lb.missing)))
        return
    if f.status == "partial" or lb.status == "partial" or not (f.runnable and lb.runnable):
        c.partial("upstream measurement checks incomplete; assignment list may be incomplete")
    c.observe("Engineering investigation requests (measured bottlenecks only)", requests=field + lab,
              note="No universal three-second page-load requirement is applied; thresholds cite their source.")


def _step7_render(ctx, dmap) -> None:
    c = ctx.check("render_failures", "Measurements that failed to render (route to 079)",
                  {PSR: ["url_id", "device_class", "run_id", "measurement_status"]})
    if not c.runnable:
        return
    failed: dict[str, dict] = {}
    for r in _psr_rows(ctx):
        if _mstatus(r.get("measurement_status")) == "failed":
            d = failed.setdefault(str(r.get("url_id")), {"run_ids": set(), "devices": set(), "statuses": set()})
            d["run_ids"].add(str(r.get("run_id")))
            d["devices"].add(str(r.get("device_class") or "unknown").lower())
            d["statuses"].add(str(r.get("measurement_status")))
    for uid in sorted(failed):
        d = failed[uid]
        m = (dmap or {}).get(uid)
        c.finding("functional_issue_route_079", "Info", {"url_id": uid},
                  f"url_id {uid}: {len(d['run_ids'])} measurement run(s) failed to render; functional check needed",
                  evidence={"url": m["url"] if m else None, "run_ids": sorted(d["run_ids"]),
                            "devices": sorted(d["devices"]), "measurement_status": sorted(d["statuses"]),
                            "association_active": m["live"] if m else None},
                  calculation={"rule": "measurement_status in failed/error/not_rendered/timeout/blocked"},
                  recommendation="Run skill-079 with timestamped GET/browser url_health_checks for this URL; "
                                 "do not score speed from failed runs.",
                  uncertainty="A failed measurement may be a tool/bot block rather than a customer-facing failure.",
                  owner="web engineering")
    c.observe("Failed measurement runs routed to 079", url_ids=sorted(failed))


def _step8_requests(ctx, dmap, records: dict) -> None:
    c = ctx.check("testing_requests", "Scoped testing requests for unmeasured destinations")
    psr = ctx.table(PSR)
    measured: dict[str, set] = {}
    if psr is not None and "url_id" in psr.columns:
        for r in psr.rows:
            if _mstatus(r.get("measurement_status")) == "ok":
                measured.setdefault(str(r.get("url_id")), set()).add(str(r.get("device_class") or "unknown").lower())
    if psr is None:
        c.partial("speed unassessed: no measurements supplied", [f"{PSR} (file)"])
    elif "url_id" not in psr.columns:
        c.partial("measurements cannot be joined to destinations", [f"{PSR}:url_id"])
    requests = []
    if dmap is None:
        c.partial("url_id inventory unavailable; requests listed by export URL",
                  [f"{DMAP} (file)"] if ctx.table(DMAP) is None else
                  [f"{DMAP}:{x}" for x in ctx.table(DMAP).missing(DMAP_CORE)])
        for u, r in records.items():
            requests.append({"url": u, "url_id": None, "priority": r["priority"], "devices": list(DEVICES_REQUESTED),
                             "conditions": TEST_CONDITIONS})
        requests.sort(key=lambda x: (x["priority"], x["url"]))
        c.observe("Testing requests (speed unassessed; no fabricated results)", requests=requests)
        return
    provable = psr is not None and "url_id" in psr.columns and psr.complete is True and not psr.truncated
    if psr is not None and not provable:
        c.partial(f"{psr.filename}: manifest does not certify complete coverage; untested status not provable")
    for uid in sorted(dmap):
        d = dmap[uid]
        if d["live"] is False:
            continue
        need = [x for x in DEVICES_REQUESTED if x not in measured.get(uid, set())]
        if not need:
            continue
        prio = records.get(d["url"], {}).get("priority") if d["url"] else None
        req = {"url": d["url"], "url_id": uid, "priority": prio, "devices": need, "conditions": TEST_CONDITIONS,
               "campaign_ids": sorted(d["campaigns"]), "association_active": d["live"]}
        requests.append(req)
        if provable and d["live"] is True and uid not in measured:
            c.finding("untested_destination", "Info", {"url_id": uid, "campaign_ids": sorted(d["campaigns"])},
                      f"Active destination url_id {uid} has no valid speed measurement",
                      evidence={**req, "page_speed_results": psr.filename},
                      calculation={"rule": "active association in destination_map; no ok row in complete "
                                           "page_speed_results"},
                      recommendation="Request field p75 (CrUX/RUM) or repeated lab runs for the listed devices; "
                                     "speed stays unassessed until then.",
                      uncertainty="Missing test, not a speed defect.", owner="web engineering")
    requests.sort(key=lambda x: (x["priority"] is None, x["priority"] or 0, str(x["url_id"])))
    c.observe("Testing requests (speed unassessed for listed URL/device pairs)", requests=requests)


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
