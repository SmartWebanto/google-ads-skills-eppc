"""check.py — skill-079 deterministic broken-destination evidence from timestamped HTTP/render checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-079-broken-url-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #80 Check if campaign websites are live and respond fast enough (Siebe Hiemstra gist) — clean-room
           reimplementation of liveness screening from SUPPLIED url_health_checks (no fetching, no e-mail).
         index #81 Check Sitelinks for broken URLs (Vincent Hsu gist) — clean-room reimplementation: sitelink rows of
           destination_map are resolved and checked like any destination; asset existence is not live association.
         index #82 Larger-scale Link Checker (Google) — clean-room reimplementation of "collect every ad, keyword and
           sitelink URL, deduplicate, check each once" (url_dedup) plus bad-status/failure-content classification.
         index #84 Redirect Checker (Nils Rooijmans) — partial, redirect-specific: redirect hops and
           destination_redirects Info from supplied chains; a redirect is never wrong by itself.
         index #89 Advanced Broken URL Checker (Dmytro Tonkikh gist) — clean-room reimplementation of soft-404
           detection (2xx page with rendered_success/expected_content_present False); its ad pausing is refused.
         index #108 Add tracking parameters to URL (Ritwik GA gist) — partial: only tracking-parameter PRESERVATION
           through redirects is checked; appending parameters (a URL mutation) is refused (recommend-only).
         skills/skill-078-landing-page-speed/scripts/check.py — same private URL normaliser / status helpers
rules:   Recommend-only; no network. Evidence = external/destination_map + external/url_health_checks (+ optional
         external/url_incident_windows); export-only runs only list/deduplicate URLs to test (never a pass).
         Live destination = destination_map association_status active/enabled/serving; unknown ≠ live.
         Attempt classes: bot_challenge_observed True, final_status 401/407 or error_class bot/captcha/geo/auth/
         test-env → excluded (not customer-facing, Info); tls_error True, final_status >= 400, or no final status
         with an error_class → hard failure; GET/browser 2xx with rendered_success or expected_content_present
         False → soft 404; conversion_path_available False → conversion-path failure; else success.
         HEAD attempts never confirm a failure (Info head_only_failure). Only GET/browser attempts count.
         Persistence: GET/browser failures at >=2 distinct parsed checked_at and no success → provisional Warning
         persistent_destination_failure; Critical only via review on a live url_id, and verify() demands
         proposal.evidence_ref plus a deterministic materiality basis (per-campaign entity exposure >=
         spend_material, a conversion-path failure, or incident affected_cost >= spend_material).
         Failures at >=2 timestamps plus a success → Warning intermittent_availability; one failure → Info.
         Redirect hops = 3xx statuses in redirect_chain_statuses; >3 → provisional Info + review (Warning needs
         proposal.evidence_ref of measured avoidable overhead). 1-3 hops → Info destination_redirects.
         Tracking keys come ONLY from profile.tracking_parameters (list); never click IDs (sanitized away).
         TLS / no-HTTPS-final at >=2 distinct timestamps → Warning; a single one → Info. Judged on final URL scheme.
         Exposure: per entity type (ad_metrics by ad_id, keyword_metrics by keyword_id), never summed across types;
         incident exposure only from url_incident_windows with cost_allocation_method; never labelled savings.
         Step 8 = owner_review_requests observation; URLs are never edited, paused or replaced.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-079-broken-url-monitoring"
VERSION = "1.0.0"

DMAP = "external/destination_map"
HC = "external/url_health_checks"
INC = "external/url_incident_windows"
DMAP_CORE = ["campaign_id", "entity_type", "entity_id", "url_id", "final_url_sanitized", "association_status"]
DMAP_STEP1 = ["mobile_url_sanitized", "keyword_override", "expansion_status"]
HC_CORE = ["url_id", "check_id", "checked_at", "method", "initial_status", "final_status", "tls_error",
           "rendered_success", "expected_content_present", "bot_challenge_observed", "error_class"]
INC_CORE = ["url_id", "incident_id", "confirmed_start", "confirmed_end", "affected_clicks", "affected_cost",
            "cost_allocation_method"]
MAX_HOPS = 3
_LIVE = {"ENABLED", "ACTIVE", "SERVING", "ELIGIBLE"}
_DEAD = {"PAUSED", "REMOVED", "DISABLED", "INACTIVE", "NOT_SERVING", "ENDED", "SUSPENDED", "DELETED"}
_GET = {"GET", "BROWSER", "HEADLESS", "HEADLESS_BROWSER", "RENDER", "RENDERED", "CHROME"}
_EXCLUDED_ERR = {"bot", "captcha", "challenge", "geo", "geoblock", "geoblocked", "geo_restricted", "auth",
                 "authorization", "unauthorized", "login", "test", "staging", "test_env", "test_environment"}
_FAIL = ("hard_failure", "soft_404", "conversion_path_failure")
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


def _query_keys(u) -> set[str]:
    n = _norm_url(u)
    if not n or "?" not in n:
        return set()
    return {p.split("=", 1)[0] for p in n.split("?", 1)[1].split("&")}


def _state(v) -> bool | None:
    s = str(v or "").strip().upper().replace(" ", "_")
    return True if s in _LIVE else False if s in _DEAD else None


def _ts(v):
    s = str(v or "").strip()
    if not s or s.lower() in V.MISSING_TOKENS:
        return None
    try:
        return datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None


def _method(v) -> str:
    m = "_".join(str(v or "").strip().upper().split())
    return "head" if m == "HEAD" else "get" if m in _GET else "unknown"


def _err_tokens(v) -> set[str]:
    s = str(v or "").lower()
    toks = set(re.split(r"[^a-z0-9]+", s)) - {""}
    return toks | {"_".join(sorted(toks))} | {s.strip()}


def _classify(r) -> str:
    """One attempt → excluded | hard_failure | soft_404 | conversion_path_failure | success | unverified | unknown."""
    fs = V.integer(r.get("final_status"))
    err = r.get("error_class")
    if V.boolean(r.get("bot_challenge_observed")) is True or fs in (401, 407) or \
            (err and _err_tokens(err) & _EXCLUDED_ERR):
        return "excluded"
    if V.boolean(r.get("tls_error")) is True or (fs is not None and fs >= 400):
        return "hard_failure"
    if fs is None:
        return "hard_failure" if err and str(err).strip().lower() not in V.MISSING_TOKENS else "unknown"
    if 200 <= fs < 300:
        if _method(r.get("method")) == "head":
            return "success"
        rendered, content = V.boolean(r.get("rendered_success")), V.boolean(r.get("expected_content_present"))
        if rendered is False or content is False:
            return "soft_404"
        if V.boolean(r.get("conversion_path_available")) is False:
            return "conversion_path_failure"
        return "success" if rendered is True and content is True else "unverified"
    return "unknown"


def _hops(r) -> int | None:
    chain = V.split_list(r.get("redirect_chain_statuses"), (">", ";", "|", ","))
    if not chain:
        init = V.integer(r.get("initial_status"))
        return None if init is None or 300 <= init < 400 else 0
    codes = [V.integer(p.strip(" -")) for p in chain]
    if None in codes:
        return None
    return sum(1 for c in codes if 300 <= c < 400)


def _dmap_index(ctx) -> dict | None:
    t = ctx.table(DMAP)
    if t is None or t.missing(DMAP_CORE):
        return None
    idx: dict[str, dict] = {}
    for r in t.rows:
        uid = str(r.get("url_id") or "")
        if not uid:
            continue
        d = idx.setdefault(uid, {"urls": set(), "campaigns": set(), "states": [], "entities": set(),
                                 "keys": set(), "template": False})
        u = _norm_url(r.get("final_url_sanitized"))
        if u:
            d["urls"].add(u)
            d["keys"] |= _query_keys(u)
        if r.get("campaign_id") is not None:
            d["campaigns"].add(str(r.get("campaign_id")))
        d["states"].append(_state(r.get("association_status")))
        d["entities"].add((str(r.get("entity_type") or "").lower(), str(r.get("entity_id") or ""),
                           str(r.get("campaign_id") or "")))
        d["template"] |= V.boolean(r.get("tracking_template_present")) is True
    for d in idx.values():
        st = d.pop("states")
        d["live"] = True if True in st else False if st and all(x is False for x in st) else None
        d["url"] = sorted(d["urls"])[0] if len(d["urls"]) == 1 else None
    return idx


def _metric_sums(ctx, key: str, id_col: str):
    t = ctx.table(key)
    if t is None or t.missing([id_col, "clicks", "cost"]):
        return None
    seg = [c for c in t.columns if c in _SEGMENTS]
    seen, bad, out = set(), set(), {}
    for r in t.rows:
        eid = str(r.get(id_col) or "")
        g = (eid,) + tuple(str(r.get(c)) for c in seg)
        clicks, cost = V.num(r.get("clicks")), ctx.money(r.get("cost"))
        if g in seen or clicks is None or cost is None:
            bad.add(eid)
        seen.add(g)
        if clicks is not None and cost is not None:
            acc = out.setdefault(eid, [0.0, 0.0])
            acc[0] += clicks
            acc[1] += cost
    for eid in bad:
        out.pop(eid, None)
    return out


def _attempts(ctx) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for r in sorted(ctx.rows(HC), key=lambda r: (str(r.get("url_id")), str(r.get("checked_at")), str(r.get("check_id")))):
        by.setdefault(str(r.get("url_id")), []).append(
            {"row": r, "cls": _classify(r), "method": _method(r.get("method")), "ts": _ts(r.get("checked_at"))})
    return by


# ---------------------------------------------------------------- run
def run(ctx) -> None:
    """Run destination URL dedup, attempt classification, persistence, redirect, TLS and exposure checks (no network).

    Rules:   Export-only runs list URLs to test, never a pass. HEAD attempts and bot/auth-excluded attempts never
             confirm failure. GET/browser failures at >= 2 timestamps with no success → provisional Warning; Critical
             only via review on a live url_id with proposal.evidence_ref + materiality basis. Failures + success →
             Warning intermittent; one → Info. >3 redirect hops → Info + review; TLS at >= 2 timestamps → Warning.
             Exposure is never labelled savings.
    """
    dmap = _dmap_index(ctx)
    _step1_resolution(ctx, dmap)
    _step2_dedup(ctx, dmap)
    attempts = _step3_render(ctx, dmap)
    incidents = _incidents(ctx)
    _step4_persistence(ctx, dmap, attempts, incidents)
    _step5_redirects(ctx, dmap, attempts)
    _step5_tracking(ctx, dmap, attempts)
    _step6_https(ctx, dmap, attempts)
    _step7_incidents(ctx, dmap, incidents)
    _step8_owner(ctx)


def _step1_resolution(ctx, dmap) -> None:
    c = ctx.check("destination_resolution", "Resolve ad, mobile, keyword-override and sitelink destinations",
                  {DMAP: DMAP_CORE})
    if not c.runnable:
        return
    t = ctx.table(DMAP)
    missing = [f"{DMAP}:{x}" for x in t.missing(DMAP_STEP1)]
    if missing:
        c.partial("override/mobile/expansion evidence absent", missing)
    by_type: dict[str, dict[str, int]] = {}
    for r in t.rows:
        et = str(r.get("entity_type") or "unknown").lower()
        st = _state(r.get("association_status"))
        k = "active" if st else "inactive" if st is False else "association_unknown"
        by_type.setdefault(et, {"active": 0, "inactive": 0, "association_unknown": 0})[k] += 1
    mapped = {(et, eid) for d in dmap.values() for et, eid, _ in d["entities"]}
    unmapped = []
    for key, et in (("ads", "ad"), ("keywords", "keyword")):
        kt = ctx.table(key)
        if kt is None or "id" not in kt.columns:
            continue
        for r in sorted(kt.rows, key=lambda r: str(r.get("id"))):
            if _state(r.get("status")) is False:
                continue
            if et == "keyword" and not _norm_url(r.get("final_url")):
                continue  # no override: keyword inherits its ad destination
            if (et, str(r.get("id"))) not in mapped:
                unmapped.append(f"{et}:{r.get('id')}")
    if unmapped:
        c.partial(f"{len(unmapped)} non-paused ads/keyword overrides absent from destination_map: {unmapped}")
    sitelinks = sorted({eid for d in dmap.values() for et, eid, _ in d["entities"] if et == "sitelink"})
    mobile = sorted({_norm_url(r.get("mobile_url_sanitized")) for r in t.rows} - {None}) \
        if "mobile_url_sanitized" in t.columns else []
    known = {d["url"] for d in dmap.values() if d["url"]}
    c.observe("Destinations resolved by IDs", rows=len(t.rows), by_entity_type=by_type, sitelink_ids=sitelinks,
              live_url_ids=sorted(u for u, d in dmap.items() if d["live"] is True),
              association_unknown_url_ids=sorted(u for u, d in dmap.items() if d["live"] is None),
              mobile_urls_without_url_id=sorted(set(mobile) - known),
              note="Asset existence is not proof of active serving association.")


def _step2_dedup(ctx, dmap) -> None:
    c = ctx.check("url_dedup", "Deduplicate equivalent sanitized URLs; keep unresolved and expansion explicit")
    if dmap is not None:
        t = ctx.table(DMAP)
        groups: dict[str, set] = {}
        unresolved = []
        for uid, d in sorted(dmap.items()):
            if d["url"] is None:
                unresolved.append(uid)
                continue
            groups.setdefault(d["url"], set()).add(uid)
        expansion = {}
        if "expansion_status" in t.columns:
            for r in t.rows:
                k = str(r.get("expansion_status") or "unknown").lower()
                expansion[k] = expansion.get(k, 0) + 1
        else:
            c.partial("expansion coverage unknown", [f"{DMAP}:expansion_status"])
        c.observe("Sanitized destination URLs deduplicated (query parameters kept, order-normalised)",
                  url_ids=len(dmap), distinct_urls=len(groups),
                  duplicate_url_ids={u: sorted(ids) for u, ids in sorted(groups.items()) if len(ids) > 1},
                  unresolved_url_ids=unresolved, expansion_status=expansion)
        return
    urls: dict[str, set] = {}
    for key, et in (("ads", "ad"), ("keywords", "keyword"), ("assets", "asset")):
        kt = ctx.table(key)
        col = next((x for x in ("final_url", "final_urls", "url") if kt is not None and x in kt.columns), None)
        if kt is None or col is None or "id" not in kt.columns:
            continue
        for r in kt.rows:
            if _state(r.get("status")) is False:
                continue
            for raw in V.split_list(r.get(col), (" | ", ";", "|")) if col == "final_urls" else [r.get(col)]:
                u = _norm_url(raw)
                if u:
                    urls.setdefault(u, set()).add(f"{et}:{r.get('id')}")
    t = ctx.table(DMAP)
    c.partial("no url_id inventory: export URLs listed as testing candidates only",
              [f"{DMAP} (file)"] if t is None else [f"{DMAP}:{x}" for x in t.missing(DMAP_CORE)])
    if ctx.table("assets") is None:
        c.partial("sitelink/asset destinations not listed", ["assets (file)"])
    c.observe("Export destination URLs to test (each once; untested, availability unassessed)",
              distinct_urls=len(urls), urls={u: sorted(e) for u, e in sorted(urls.items())})


def _step3_render(ctx, dmap) -> dict:
    c = ctx.check("redirect_render", "Classify redirect chains and rendered outcomes per attempt", {HC: HC_CORE})
    if not c.runnable:
        return {}
    t = ctx.table(HC)
    if "conversion_path_available" not in t.columns:
        c.partial("broken purchase paths on 200 pages undetectable", [f"{HC}:conversion_path_available"])
    if "redirect_chain_statuses" not in t.columns:
        c.partial("complete redirect chains not supplied", [f"{HC}:redirect_chain_statuses"])
    by = _attempts(ctx)
    summary = {}
    for uid in sorted(by):
        s: dict[str, int] = {}
        for a in by[uid]:
            k = f"{a['method']}:{a['cls']}"
            s[k] = s.get(k, 0) + 1
        summary[uid] = s
    unknown = sum(1 for v in by.values() for a in v if a["method"] == "unknown")
    if unknown:
        c.partial(f"{unknown} attempts with unknown method treated as unconfirmed")
    if dmap is None:
        c.partial("untested destinations not listable", [f"{DMAP} (file)"] if ctx.table(DMAP) is None
                  else [f"{DMAP}:{x}" for x in ctx.table(DMAP).missing(DMAP_CORE)])
    else:
        provable = t.complete is True and not t.truncated
        untested = [u for u in sorted(dmap) if dmap[u]["live"] is True and u not in by]
        if untested and not provable:
            c.partial(f"{t.filename}: manifest does not certify complete coverage; untested status not provable")
        for uid in (untested if provable else []):
            d = dmap[uid]
            c.finding("untested_destination", "Info", {"url_id": uid, "campaign_ids": sorted(d["campaigns"])},
                      f"Live destination url_id {uid} has no health-check attempt",
                      evidence={"url": d["url"], "url_health_checks": t.filename},
                      calculation={"rule": "active association; no row in complete url_health_checks"},
                      recommendation="Add this URL to GET/browser monitoring (device/location as served).",
                      uncertainty="Untested, not broken.", owner="destination owner")
    c.observe("Attempt classes per url_id (method:class)", classes=summary,
              note="HEAD results never confirm a failure; a 200 page can still be a soft 404.")
    return by


def _incidents(ctx) -> dict[str, list[dict]]:
    t = ctx.table(INC)
    if t is None or t.missing(INC_CORE):
        return {}
    out: dict[str, list[dict]] = {}
    for r in sorted(t.rows, key=lambda r: (str(r.get("url_id")), str(r.get("incident_id")))):
        out.setdefault(str(r.get("url_id")), []).append({
            "incident_id": r.get("incident_id"), "start": r.get("confirmed_start"), "end": r.get("confirmed_end"),
            "affected_clicks": V.num(r.get("affected_clicks")), "affected_cost": ctx.money(r.get("affected_cost")),
            "cost_allocation_method": r.get("cost_allocation_method"), "confidence": r.get("confidence")})
    return out


def _exposure(ctx, d: dict, ad_m, kw_m) -> dict:
    """Per campaign, per entity type exposure of the url's mapped entities (types never summed)."""
    out: dict[str, dict] = {}
    for et, eid, cid in sorted(d["entities"]):
        src = ad_m if et == "ad" else kw_m if et == "keyword" else None
        e = out.setdefault(cid, {})
        if src is None:
            e.setdefault(et, None)
            continue
        acc = e.get(et) or {"clicks": 0.0, "cost": 0.0, "entities": 0}
        if eid in src:
            acc["clicks"] += src[eid][0]
            acc["cost"] += src[eid][1]
            acc["entities"] += 1
        e[et] = acc
    return out


def _step4_persistence(ctx, dmap, by, incidents) -> None:
    c = ctx.check("failure_persistence", "Persistent vs transient/bot/HEAD-only failures", {HC: HC_CORE})
    if not c.runnable:
        return
    if dmap is None:
        c.partial("live association unknown: Critical path unavailable", [f"{DMAP} (file)"]
                  if ctx.table(DMAP) is None else [f"{DMAP}:{x}" for x in ctx.table(DMAP).missing(DMAP_CORE)])
    ad_m, kw_m = _metric_sums(ctx, "ad_metrics", "ad_id"), _metric_sums(ctx, "keyword_metrics", "keyword_id")
    window = [ctx.period_start, ctx.period_end]
    ok_urls = []
    for uid in sorted(by):
        at = by[uid]
        get = [a for a in at if a["method"] == "get"]
        fails = [a for a in get if a["cls"] in _FAIL]
        oks = [a for a in get if a["cls"] in ("success", "unverified")]
        fail_ts = sorted({a["ts"] for a in fails if a["ts"] is not None}, key=str)
        d = (dmap or {}).get(uid)
        entity = {"url_id": uid, "campaign_ids": sorted(d["campaigns"]) if d else []}
        ev = {"url": d["url"] if d else None, "association_live": d["live"] if d else None,
              "failed_attempts": [{"check_id": a["row"].get("check_id"), "checked_at": a["row"].get("checked_at"),
                                   "class": a["cls"], "final_status": a["row"].get("final_status"),
                                   "error_class": a["row"].get("error_class"),
                                   "source_reference": a["row"].get("source_reference")} for a in fails],
              "successful_get_attempts": len(oks), "distinct_failure_timestamps": [str(x) for x in fail_ts]}
        if len(fails) > len(fail_ts) and len(fail_ts) < 2:
            c.partial(f"url_id {uid}: failure timestamps unparseable or repeated; persistence not provable")
        if len(fail_ts) >= 2 and not oks:
            prov = c.finding("persistent_destination_failure", "Warning", entity,
                             f"url_id {uid} failed GET/browser checks at {len(fail_ts)} distinct times with no success",
                             evidence=ev, calculation={"rule": ">=2 distinct checked_at failures, 0 GET/browser success"},
                             recommendation="Urgent destination-owner review with repeat browser evidence; do not "
                                            "edit, pause or replace URLs automatically.",
                             uncertainty="Material impact not evidenced; failures observed only at check times.",
                             owner="destination owner")
            if d is None or d["live"] is not True:
                c.partial(f"url_id {uid}: association not evidenced live; Critical path unavailable")
                continue
            exposure = _exposure(ctx, d, ad_m, kw_m)
            basis, material = [], {}
            for cid in sorted(d["campaigns"]):
                p = ctx.params.get("spend_material", cid)
                material[cid] = {"value": p.value, "source": p.source, "unresolved": p.reason or None}
                costs = [v["cost"] for v in exposure.get(cid, {}).values() if v]
                if p.value is not None and costs and max(costs) >= p.value:
                    basis.append(f"campaign {cid}: max single-type entity exposure {max(costs):.2f} >= "
                                 f"spend_material {p.value:g}")
                inc_costs = [i["affected_cost"] for i in incidents.get(uid, [])
                             if i["affected_cost"] is not None and i["cost_allocation_method"]]
                if p.value is not None and inc_costs and max(inc_costs) >= p.value:
                    basis.append(f"incident affected_cost {max(inc_costs):.2f} >= spend_material {p.value:g} ({cid})")
            if any(a["cls"] == "conversion_path_failure" for a in fails):
                basis.append("conversion_path_available False on a failing GET/browser attempt")
            c.review("persistent_destination_failure", entity,
                     f"Does url_id {uid}'s reproducible failure block a MATERIALLY exposed live destination or "
                     "conversion path?",
                     evidence={**ev, "live_association": True, "entity_exposure_by_campaign": exposure,
                               "spend_material": material, "materiality_basis": sorted(set(basis)),
                               "incidents": incidents.get(uid, []), "window": window, "currency": ctx.currency,
                               "exposure_note": "current-window entity exposure, unallocated; not waste or savings"},
                     outcomes={"material_live_failure": {"severity": "Critical", "recommendation":
                                                         "Urgent destination-owner fix; cite the evidence_ref."},
                               "uncertain_material_impact": {"severity": "Warning", "recommendation":
                                                             "Owner review; gather repeat browser evidence."}},
                     guidance="Critical needs proposal.evidence_ref and a non-empty materiality_basis.",
                     provisional=prov)
        elif len(fail_ts) >= 2:
            c.finding("intermittent_availability", "Warning", entity,
                      f"url_id {uid} failed at {len(fail_ts)} distinct times and succeeded {len(oks)} time(s)",
                      evidence=ev, calculation={"rule": ">=2 distinct failure timestamps and >=1 GET/browser success"},
                      recommendation="Destination-owner review of intermittent availability; add monitoring cadence.",
                      uncertainty="Material impact uncertain; outage duration between checks unknown.",
                      owner="destination owner")
        elif fails:
            c.finding("unconfirmed_single_failure", "Info", entity,
                      f"url_id {uid} has one unconfirmed GET/browser failure",
                      evidence=ev, calculation={"rule": "failures at <2 distinct timestamps"},
                      recommendation="Request a repeat browser check from the served device/location.",
                      uncertainty="Transient error possible.", owner="destination owner")
        elif any(a["cls"] in _FAIL for a in at if a["method"] == "head"):
            c.finding("head_only_failure", "Info", entity, f"url_id {uid} failed only HEAD checks",
                      evidence={**ev, "head_failures": sum(1 for a in at if a["method"] == "head" and a["cls"] in _FAIL)},
                      calculation={"rule": "HEAD failure without any GET/browser failure"},
                      recommendation="Repeat with GET/browser; HEAD may differ from browser behaviour.",
                      uncertainty="Not a confirmed customer-facing failure.", owner="destination owner")
        elif any(a["cls"] == "excluded" for a in at):
            c.finding("excluded_failure_class", "Info", entity,
                      f"url_id {uid} checks hit bot challenge, geo, authorization or test-environment blocks",
                      evidence={**ev, "error_classes": sorted({str(a["row"].get("error_class")) for a in at
                                                               if a["cls"] == "excluded"})},
                      calculation={"rule": "bot_challenge_observed / 401/407 / excluded error_class"},
                      recommendation="Re-check from a customer-like browser and location.",
                      uncertainty="Not customer-facing evidence.", owner="destination owner")
        elif oks:
            ok_urls.append(uid)
    c.observe("GET/browser checks without failures", url_ids=ok_urls)


def _step5_redirects(ctx, dmap, by) -> None:
    c = ctx.check("redirect_hops", "Redirect chain length and expected redirects",
                  {HC: ["url_id", "method", "initial_status", "redirect_chain_statuses"]})
    if not c.runnable:
        return
    unknown = []
    for uid in sorted(by):
        hops = [(h, a) for a in by[uid] for h in [_hops(a["row"])] if h is not None]
        if len(hops) < len(by[uid]):
            unknown.append(uid)
        if not hops:
            continue
        h, a = max(hops, key=lambda x: (x[0], str(x[1]["row"].get("checked_at"))))
        d = (dmap or {}).get(uid)
        entity = {"url_id": uid, "campaign_ids": sorted(d["campaigns"]) if d else []}
        ev = {"url": d["url"] if d else None, "max_hops": h, "check_id": a["row"].get("check_id"),
              "checked_at": a["row"].get("checked_at"), "redirect_chain_statuses": a["row"].get("redirect_chain_statuses"),
              "redirect_chain_sanitized_urls": a["row"].get("redirect_chain_sanitized_urls"),
              "final_url_sanitized": a["row"].get("final_url_sanitized"), "final_status": a["row"].get("final_status")}
        if h > MAX_HOPS:
            prov = c.finding("redirect_chain_over_three_hops", "Info", entity,
                             f"url_id {uid} redirects through {h} hops (> {MAX_HOPS})", evidence=ev,
                             calculation={"rule": "count of 3xx statuses in redirect_chain_statuses > 3 (heuristic)"},
                             recommendation="Owner review whether hops are avoidable; do not remove redirects that "
                                            "carry attribution, locale or routing.",
                             uncertainty="Heuristic; overhead not measured.", owner="destination owner")
            c.review("redirect_chain_over_three_hops", entity,
                     f"Is there MEASURED avoidable overhead in url_id {uid}'s {h}-hop redirect chain?",
                     evidence=ev,
                     outcomes={"avoidable_overhead_measured": {"severity": "Warning", "recommendation":
                                                               "Owner shortens the chain after routing review."},
                               "expected_routing": {"severity": None, "recommendation": "Keep; document routing."},
                               "uncertain": {"severity": "Info", "recommendation": "Request timing evidence."}},
                     guidance="Warning needs proposal.evidence_ref to measured timing/overhead evidence.",
                     provisional=prov)
        elif h > 0:
            c.finding("destination_redirects", "Info", entity, f"url_id {uid} redirects ({h} hop(s))", evidence=ev,
                      calculation={"rule": "1-3 3xx statuses in the chain"},
                      recommendation="Confirm the redirect is intended; updating the URL directly may break "
                                     "attribution, locale or routing.",
                      uncertainty="A deliberate redirect is not inherently wrong.", owner="destination owner")
    if unknown:
        c.partial(f"redirect chain incomplete/unparseable for url_ids {unknown}")


def _step5_tracking(ctx, dmap, by) -> None:
    c = ctx.check("tracking_preservation", "Tracking parameters preserved through redirects",
                  {HC: ["url_id", "method", "final_status", "final_url_sanitized"],
                   DMAP: ["url_id", "final_url_sanitized"]})
    if not c.runnable:
        return
    keys = ctx.profile.get("tracking_parameters")
    keys = sorted({str(k).strip().lower() for k in keys if str(k).strip()}) if isinstance(keys, list) else []
    if not keys:
        c.skip("tracking parameter keys not declared", ["profile:tracking_parameters"])
        return
    t = ctx.table(DMAP)
    idx: dict[str, dict] = {}
    for r in t.rows:
        d = idx.setdefault(str(r.get("url_id")), {"keys": set(), "template": False, "campaigns": set()})
        d["keys"] |= {k.lower() for k in _query_keys(r.get("final_url_sanitized"))}
        d["template"] |= V.boolean(r.get("tracking_template_present")) is True
        if r.get("campaign_id") is not None:
            d["campaigns"].add(str(r.get("campaign_id")))
    checked = 0
    for uid in sorted(by):
        cfg = idx.get(uid)
        if not cfg:
            continue
        want = cfg["keys"] & set(keys)
        if not want:
            continue
        for a in by[uid]:
            fs = V.integer(a["row"].get("final_status"))
            if a["method"] != "get" or fs is None or not 200 <= fs < 300 or not a["row"].get("final_url_sanitized"):
                continue
            checked += 1
            lost = sorted(want - {k.lower() for k in _query_keys(a["row"].get("final_url_sanitized"))})
            if not lost:
                continue
            entity = {"url_id": uid, "campaign_ids": sorted(cfg["campaigns"])}
            ev = {"configured_keys": sorted(want), "lost_keys": lost, "check_id": a["row"].get("check_id"),
                  "checked_at": a["row"].get("checked_at"), "final_url_sanitized": a["row"].get("final_url_sanitized"),
                  "tracking_template_present": cfg["template"], "source": "profile.tracking_parameters"}
            prov = c.finding("tracking_parameter_dropped", "Info", entity,
                             f"url_id {uid}: {lost} missing from the final URL after redirects", evidence=ev,
                             calculation={"rule": "key in configured final URL ∩ profile keys, absent in final URL"},
                             recommendation="Owner checks whether attribution relies on these parameters before "
                                            "changing redirects or templates.",
                             uncertainty="Parameters may be consumed server-side or appended at click time.",
                             owner="destination owner + analytics")
            c.review("tracking_parameter_dropped", entity,
                     f"Is the loss of {lost} for url_id {uid} unintended and harmful to attribution?", evidence=ev,
                     outcomes={"tracking_lost": {"severity": "Warning", "recommendation":
                                                 "Owner fixes the redirect to preserve parameters."},
                               "intended": {"severity": None, "recommendation": "Keep; document the routing."},
                               "uncertain": {"severity": "Info", "recommendation": "Ask analytics owner."}},
                     guidance="Tracking template presence means click-time parameters may differ from the check.",
                     provisional=prov)
            break
    c.observe("Tracking preservation evaluated", tracking_keys=keys, successful_get_attempts_checked=checked)


def _step6_https(ctx, dmap, by) -> None:
    c = ctx.check("https_tls", "HTTP-to-HTTPS behaviour and TLS on final URLs",
                  {HC: ["url_id", "checked_at", "method", "tls_error", "final_url_sanitized"]})
    if not c.runnable:
        return
    for uid in sorted(by):
        get = [a for a in by[uid] if a["method"] == "get"]
        tls = sorted({str(a["ts"]) for a in get if V.boolean(a["row"].get("tls_error")) is True and a["ts"]})
        http = sorted({str(a["ts"]) for a in get if a["ts"] and
                       str(_norm_url(a["row"].get("final_url_sanitized")) or "").startswith("http://")})
        d = (dmap or {}).get(uid)
        entity = {"url_id": uid, "campaign_ids": sorted(d["campaigns"]) if d else []}
        for key, ts, what in (("tls_problem", tls, "TLS errors"), ("no_https_final", http, "final URL on plain HTTP")):
            if not ts:
                continue
            sev = "Warning" if len(ts) >= 2 else "Info"
            c.finding(key if sev == "Warning" else f"{key}_single", sev, entity,
                      f"url_id {uid}: {what} at {len(ts)} distinct check time(s)",
                      evidence={"url": d["url"] if d else None, "checked_at": ts},
                      calculation={"rule": ">=2 distinct GET/browser timestamps → Warning; 1 → Info"},
                      recommendation="Destination owner reviews certificate/HTTPS redirect; do not disable tracking "
                                     "templates or remove redirects without review.",
                      uncertainty="Judged on the final URL, not the initial scheme.", owner="destination owner")


def _step7_incidents(ctx, dmap, incidents) -> None:
    c = ctx.check("incident_exposure", "Measured exposure within confirmed incident windows", {INC: INC_CORE})
    if not c.runnable:
        return
    rows, unalloc = [], []
    for uid in sorted(incidents):
        for i in incidents[uid]:
            if not i["cost_allocation_method"] or i["affected_cost"] is None:
                unalloc.append(f"{uid}:{i['incident_id']}")
                continue
            rows.append({"url_id": uid, **i, "association_live": (dmap or {}).get(uid, {}).get("live")})
    if unalloc:
        c.partial(f"incidents without measured cost allocation not quantified: {unalloc}")
    c.observe("Measured incident exposure (historical exposure, not waste or savings)", incidents=rows,
              currency=ctx.currency,
              note="Current failures never establish historical wasted spend; overlapping incidents are not summed.")


def _step8_owner(ctx) -> None:
    p = next(x for x in ctx.result.checks if x.id == "failure_persistence")
    c = ctx.check("owner_review_requests", "Destination-owner review requests (no automatic edits)")
    if not p.runnable:
        c.skip("no failure evidence evaluated", p.missing)
        return
    keys = ("persistent_destination_failure", "intermittent_availability", "tls_problem", "no_https_final")
    reqs = [{"url_id": f.entity.get("url_id"), "condition": f.condition_key, "severity": f.severity}
            for f in ctx.result.findings if f.condition_key in keys]
    c.observe("Urgent destination-owner review requests", requests=sorted(reqs, key=lambda r: (r["url_id"], r["condition"])),
              note="Propose owner review only; never edit, pause or replace URLs automatically.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref + a deterministic materiality basis on a live url;
    measured-overhead Warning needs proposal.evidence_ref."""
    out = decision.get("outcome")
    ref = (decision.get("proposal") or {}).get("evidence_ref")
    problems = []
    if out == "material_live_failure":
        if not ref:
            problems.append("material_live_failure needs proposal.evidence_ref pointing at supplied evidence")
        if item.evidence.get("live_association") is not True:
            problems.append("url_id is not evidenced as a live destination")
        if not item.evidence.get("materiality_basis"):
            problems.append("no deterministic materiality basis (exposure/incident >= spend_material or "
                            "conversion-path failure)")
    if out == "avoidable_overhead_measured" and not ref:
        problems.append("avoidable_overhead_measured needs proposal.evidence_ref to measured overhead")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
