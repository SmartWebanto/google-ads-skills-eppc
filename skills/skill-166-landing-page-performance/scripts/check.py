"""check.py — skill-166 deterministic landing-page performance, guarded URL screens and URL health join.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-166-landing-page-performance/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #71 PMax Low-Performing Landing Page Alerts (nilsrooijmans.com) — clean-room reimplementation of
         "flag landing pages that spend without converting / convert far below average", generalized to every
         campaign type incl. PMax, with both-cohort sample, maturity and tracking gates;
         index #102 Generate Landing Page performance report (github Webmasterei, repo unavailable) — clean-room
         URL-level aggregation of spend/clicks/conversions/value per normalized URL and campaign type.
rules:   URL normalization (_norm_url): lowercase scheme/host, drop default port and fragment, remove ONLY
         profile.url_ignore_params (exact or 'prefix*'), sort remaining query pairs, keep path verbatim
         (empty path → '/'). Same rules for report URLs and health-check URLs; join on normalized URL only.
         url_view landing_page and expanded_landing_page are separate universes — never summed together.
         CVR comparison: URL cohort and baseline (same view+channel_type minus the URL) each >= min_clicks,
         ctx.mature True, no conflicting declared goal sets in the type; zero-conversion URLs never enter it.
         Zero-conversion Warning only via review, and the review is only emitted when ctx.mature is True AND
         ctx.tracking_for_campaign is True for every contributing campaign; else partial + descriptive list.
         Money parameters resolve per contributing campaign; the URL uses the maximum; any unresolved → partial.
         URL health: window cost is context; day-level cost on failing-check dates is 'overlap', never affected spend.
         Critical only via review outcome 'material_failure_evidenced' with proposal.evidence_ref.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes2 | new recipe deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

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

SKILL = "skill-166-landing-page-performance"
VERSION = "1.0.0"

PERF = "custom/landing_page_performance"
CHK = "external/landing_page_checks"
NEEDS = {PERF: ["campaign_id", "url_view", "url", "clicks", "cost", "conversions"], "campaigns": ["id", "channel_type"]}
VIEWS = ("landing_page", "expanded_landing_page")
DEFAULT_PORTS = {"http": 80, "https": 443}
CVR_RATIO = 0.5
PERSISTENT_RUN = 2
TOP = 10


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _ignored(name: str, ignore: list[str]) -> bool:
    return any(name.startswith(p[:-1]) if p.endswith("*") else name == p for p in ignore)


def _norm_url(raw, ignore: list[str]) -> str | None:
    """Canonical join form of a URL (module rules); None for non-absolute or unparseable URLs.

    Rules:   string-only parsing (urllib is lint-forbidden); query pairs stay percent-encoded as supplied,
             so both sides of a join must be normalized by this same function.
    """
    s = _s(raw).split("#", 1)[0]
    scheme, sep, rest = s.partition("://")
    if not sep or not scheme.isascii() or not scheme.replace("+", "").replace("-", "").replace(".", "").isalnum():
        return None
    scheme = scheme.lower()
    cut = min([i for i in (rest.find("/"), rest.find("?")) if i >= 0], default=len(rest))
    netloc, tail = rest[:cut], rest[cut:]
    host = netloc.rpartition("@")[2]
    port = ""
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            return None
        host, port = host[:end + 1], host[end + 1:].lstrip(":")
    elif ":" in host:
        host, port = host.rsplit(":", 1)
    host = host.lower()
    if not host or (port and not port.isdigit()):
        return None
    if port and int(port) == DEFAULT_PORTS.get(scheme):
        port = ""
    path, _q, query = tail.partition("?")
    pairs = []
    for part in query.split("&"):
        if not part:
            continue
        name = part.split("=", 1)[0]
        if not _ignored(name, ignore):
            pairs.append(part)
    q = "&".join(sorted(pairs))
    return f"{scheme}://{host}{':' + port if port else ''}{path or '/'}{'?' + q if q else ''}"


def _dt(v) -> datetime | None:
    s = _s(v)
    if not s or s.lower() in V.MISSING_TOKENS:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _max_param(ctx, name: str, campaigns) -> tuple[float | None, str]:
    """Highest resolved value across contributing campaigns; any unresolved campaign → (None, reason)."""
    best, src = None, ""
    for cid in sorted(campaigns):
        r = ctx.params.get(name, cid)
        if r.value is None:
            return None, f"campaign {cid}: {r.reason}"
        if best is None or r.value > best:
            best, src = r.value, f"campaign {cid}: {r.source}"
    return best, src


def _bucket() -> dict:
    return {"clicks": 0.0, "cost": 0.0, "conversions": 0.0, "value": 0.0, "value_known": True,
            "impressions": None, "campaigns": set(), "raw": set()}


def _add(b: dict, m: dict, cid: str, raw: str) -> None:
    for k in ("clicks", "cost", "conversions"):
        b[k] += m[k]
    if m["value"] is None:
        b["value_known"] = False
    else:
        b["value"] += m["value"]
    if m["impressions"] is not None:
        b["impressions"] = (b["impressions"] or 0.0) + m["impressions"]
    b["campaigns"].add(cid)
    b["raw"].add(raw)


def _public(b: dict) -> dict:
    return {"clicks": b["clicks"], "cost": b["cost"], "conversions": b["conversions"],
            "conversion_value": b["value"] if b["value_known"] else None, "impressions": b["impressions"],
            "campaign_ids": sorted(b["campaigns"]), "raw_variants": sorted(b["raw"])[:TOP]}


class _Agg:
    """URL aggregates at (view,url), (view,type,url) and (view,type); optional daily cost per (view,url,date)."""

    def __init__(self, ctx, check):
        ignore = ctx.profile.get("url_ignore_params") or []
        self.ignore = [str(x) for x in (ignore if isinstance(ignore, list) else [ignore])]
        t = ctx.table(PERF)
        seg = [c for c in ("date", "device") if c in t.columns]
        self.has_date = "date" in t.columns
        channel = {_s(c.get("id")): _s(c.get("channel_type")).upper() or "UNKNOWN" for c in ctx.rows("campaigns")}
        self.url: dict[tuple, dict] = {}
        self.type_url: dict[tuple, dict] = {}
        self.type: dict[tuple, dict] = {}
        self.daily: dict[tuple, float] = {}
        seen, dup, bad_url, bad_view, bad_metric, unknown_camp = set(), 0, 0, 0, 0, set()
        for r in t.rows:
            view = _s(r.get("url_view")).lower()
            cid = _s(r.get("campaign_id"))
            grain = (cid, view, _s(r.get("url"))) + tuple(_s(r.get(c)) for c in seg)
            if grain in seen:
                dup += 1
                continue
            seen.add(grain)
            if view not in VIEWS:
                bad_view += 1
                continue
            url = _norm_url(r.get("url"), self.ignore)
            if url is None:
                bad_url += 1
                continue
            m = {"clicks": V.num(r.get("clicks")), "cost": ctx.money(r.get("cost")),
                 "conversions": V.num(r.get("conversions")), "value": V.num(r.get("conversion_value")),
                 "impressions": V.num(r.get("impressions"))}
            if None in (m["clicks"], m["cost"], m["conversions"]):
                bad_metric += 1
                continue
            ctype = channel.get(cid, "UNKNOWN")
            if cid not in channel:
                unknown_camp.add(cid)
            raw = _s(r.get("url"))
            _add(self.url.setdefault((view, url), _bucket()), m, cid, raw)
            _add(self.type_url.setdefault((view, ctype, url), _bucket()), m, cid, raw)
            _add(self.type.setdefault((view, ctype), _bucket()), m, cid, raw)
            d = V.parse_date(r.get("date")) if self.has_date else None
            if d is not None:
                self.daily[(view, url, d)] = self.daily.get((view, url, d), 0.0) + m["cost"]
        for n, why in ((dup, "duplicate rows at the same grain counted once"),
                       (bad_view, f"rows with url_view outside {list(VIEWS)} excluded"),
                       (bad_url, "rows with non-absolute/unparseable url excluded"),
                       (bad_metric, "rows with unknown clicks/cost/conversions excluded")):
            if n:
                check.partial(f"{n} {why}")
        if unknown_camp:
            check.partial(f"{len(unknown_camp)} campaign ids missing from campaigns: channel_type UNKNOWN, "
                          "kept out of type baselines", ["campaigns:id"])
        self.raw_rows = len(t.rows)


def run(ctx) -> None:
    """Run normalized-URL aggregation, CVR-vs-type baseline, zero-conversion URL and URL-health checks.

    Rules:   landing_page and expanded_landing_page are never summed. CVR comparison needs both cohorts >= min_clicks,
             ctx.mature True and consistent goals → Info + review. Zero-conversion review only when mature and tracking
             True for every contributing campaign, else partial. Persistent health failure → Warning, single/recovered
             failure → Info; Critical only via 'material_failure_evidenced'. Health-date cost is overlap, never affected
             spend.
    """
    agg_c = ctx.check("url_aggregation", "Normalize and aggregate URL performance per view and campaign type", NEEDS)
    titles = (("url_cvr_vs_type_baseline", "URL CVR vs campaign-type baseline"),
              ("zero_conversion_urls", "Guarded zero-conversion URL screening"),
              ("url_health", "Timestamped URL health joined to URL performance"))
    if not agg_c.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("URL performance unavailable", agg_c.missing)
        return
    agg = _Agg(ctx, agg_c)
    for (view, ctype), b in sorted(agg.type.items()):
        urls = sorted(((u, x) for (v, t, u), x in agg.type_url.items() if v == view and t == ctype),
                      key=lambda kv: (-kv[1]["cost"], kv[0]))
        agg_c.observe(f"{view} / {ctype}: URL totals", url_view=view, channel_type=ctype, urls=len(urls),
                      **{k: v for k, v in _public(b).items() if k not in ("raw_variants",)},
                      cvr=V.ratio(b["conversions"], b["clicks"]), window=[ctx.period_start, ctx.period_end],
                      top_urls_by_cost=[{"url": u, "cost": x["cost"], "clicks": x["clicks"],
                                         "conversions": x["conversions"],
                                         "cost_share": V.ratio(x["cost"], b["cost"])} for u, x in urls[:TOP]])
    agg_c.observe("URL normalization", input_rows=agg.raw_rows, normalized_urls=len(agg.url),
                  url_ignore_params=agg.ignore)
    if len({v for v, _ in agg.url}) > 1:
        agg_c.observe("Both url_view universes supplied: analyzed separately, never summed")

    _cvr(ctx, agg)
    _zero(ctx, agg)
    _health(ctx, agg)


def _cvr(ctx, agg: _Agg) -> None:
    c = ctx.check("url_cvr_vs_type_baseline", "URL CVR vs campaign-type baseline", NEEDS)
    if ctx.mature is not True:
        c.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; CVR comparisons not made (descriptive totals only)")
        return
    mc = ctx.params.get("min_clicks")
    if mc.value is None:
        c.partial(f"min_clicks unresolved: {mc.reason}")
        return
    compared = insufficient = below_material = flagged = 0
    for (view, ctype), tot in sorted(agg.type.items()):
        if ctype == "UNKNOWN":
            continue
        goal_sets = {tuple(sorted(ctx.goal_ids(cid))) for cid in tot["campaigns"]}
        goal_sets.discard(())
        if len(goal_sets) > 1:
            c.partial(f"{view} / {ctype}: campaigns declare different goal sets {sorted(goal_sets)}; baseline not comparable")
            continue
        for (v, t, url), u in sorted(agg.type_url.items()):
            if v != view or t != ctype or u["conversions"] == 0:
                continue
            base_clicks, base_conv = tot["clicks"] - u["clicks"], tot["conversions"] - u["conversions"]
            if u["clicks"] < mc.value or base_clicks < mc.value:
                insufficient += 1
                continue
            url_cvr, base_cvr = V.ratio(u["conversions"], u["clicks"]), V.ratio(base_conv, base_clicks)
            rel = V.ratio(url_cvr, base_cvr)
            if rel is None:
                continue
            compared += 1
            if rel >= CVR_RATIO:
                continue
            mat, msrc = _max_param(ctx, "spend_material", u["campaigns"])
            if mat is None:
                c.partial(f"spend_material unresolved for {url}: {msrc}")
                continue
            if u["cost"] < mat:
                below_material += 1
                continue
            flagged += 1
            entity = {"url_view": view, "channel_type": ctype, "url": url}
            ev = {"url": _public(u), "baseline": {"clicks": base_clicks, "conversions": base_conv,
                                                  "definition": "same url_view + channel_type minus this URL"},
                  "url_cvr": url_cvr, "baseline_cvr": base_cvr, "cvr_ratio": rel, "min_clicks": mc.value,
                  "min_clicks_source": mc.source, "spend_material": mat, "spend_material_source": msrc,
                  "goal_sets": sorted(goal_sets), "maturity": ctx.maturity_note,
                  "window": [ctx.period_start, ctx.period_end]}
            prov = c.finding("url_cvr_below_type_baseline", "Info", entity,
                             f"{url} ({ctype}, {view}) converts at {url_cvr:.2%} vs {base_cvr:.2%} for the rest of "
                             f"{ctype} ({rel:.2f}x) with cost {u['cost']:.2f} {ctx.currency}",
                             evidence=ev, calculation={"numerator": u["conversions"], "denominator": u["clicks"],
                                                       "baseline_numerator": base_conv,
                                                       "baseline_denominator": base_clicks,
                                                       "rule": f"url_cvr < {CVR_RATIO} x baseline_cvr"},
                             recommendation="Review the page and journey for this traffic before any change.",
                             uncertainty="Traffic mix, intent and product differ by URL; the gap is not causal proof.")
            c.review("url_cvr_below_type_baseline", entity,
                     f"Does supplied page/journey evidence show a defect on {url}, or does traffic mix explain its lower CVR?",
                     evidence=ev, provisional=prov,
                     outcomes={
                         "page_defect_evidenced": {"severity": "Warning", "recommendation":
                                                   "Owner fix of the cited page/journey defect; re-measure on a mature window."},
                         "traffic_mix_explains": {"severity": None, "recommendation": "No page action."},
                         "uncertain": {"severity": "Info", "recommendation":
                                       "Request page checks or a controlled page test."},
                     },
                     guidance="page_defect_evidenced needs proposal.evidence_ref to supplied page, check or journey "
                              "evidence (skill-069/078/079/034). URL or CVR alone is not a defect.")
    c.observe("CVR comparisons", compared=compared, insufficient_sample=insufficient,
              below_spend_material=below_material, flagged=flagged, min_clicks=mc.value)


def _zero(ctx, agg: _Agg) -> None:
    c = ctx.check("zero_conversion_urls", "Guarded zero-conversion URL screening", NEEDS)
    blocked: list[dict] = []
    reviewed = 0
    for (view, ctype, url), u in sorted(agg.type_url.items()):
        if u["conversions"] != 0 or u["cost"] <= 0:
            continue
        floor, fsrc = _max_param(ctx, "spend_floor", u["campaigns"])
        if floor is None:
            c.partial(f"spend_floor unresolved for {url}: {fsrc}")
            continue
        if u["cost"] < floor:
            continue
        tracking = {cid: ctx.tracking_for_campaign(cid) for cid in sorted(u["campaigns"])}
        gates = []
        if ctx.mature is not True:
            gates.append(f"maturity {ctx.mature}: {ctx.maturity_note}")
        gates += [note for ok, note in tracking.values() if ok is not True]
        entity = {"url_view": view, "channel_type": ctype, "url": url}
        ev = {"url": _public(u), "spend_floor": floor, "spend_floor_source": fsrc,
              "tracking": {cid: note for cid, (_ok, note) in tracking.items()},
              "window": [ctx.period_start, ctx.period_end]}
        if gates:
            blocked.append({**entity, "cost": u["cost"], "clicks": u["clicks"], "blocked_by": gates})
            continue
        reviewed += 1
        prov = c.finding("zero_conversion_url", "Info", entity,
                         f"{url} ({ctype}, {view}) cost {u['cost']:.2f} {ctx.currency} with 0 conversions in a mature "
                         f"window with evidenced tracking (spend_floor {floor:g})", evidence=ev,
                         calculation={"cost": u["cost"], "threshold": floor, "conversions": 0},
                         recommendation="Review the page's role and relevance before any change; exposure is not savings.",
                         uncertainty="Zero conversions can reflect lag, long cycles or a non-conversion page role.")
        c.review("zero_conversion_url", entity,
                 f"Is {url} meant to convert for this {ctype} traffic, so that its zero conversions warrant investigation?",
                 evidence=ev, provisional=prov,
                 outcomes={
                     "relevant_page_investigate": {"severity": "Warning", "recommendation":
                                                   "Investigate page tracking, relevance and journey; no automatic pause."},
                     "non_conversion_role": {"severity": None, "recommendation": "Page has a declared non-conversion role."},
                     "uncertain": {"severity": "Info", "recommendation": "Ask the client for the page's role."},
                 },
                 guidance="Judge only from profile objectives, campaign role and the URL; do not assume waste.")
    if blocked:
        c.partial(f"{len(blocked)} zero-conversion URLs at spend_floor not screened: maturity/tracking gates unmet")
        c.observe("Zero-conversion URLs at spend_floor (descriptive; gates unmet)",
                  urls=sorted(blocked, key=lambda x: (-x["cost"], x["url"]))[:TOP], count=len(blocked))
    c.observe("Zero-conversion screening totals", reviewed=reviewed, blocked=len(blocked))


def _classify(r: dict) -> str:
    code = V.integer(r.get("status_code"))
    if _s(r.get("access_error")) and _s(r.get("access_error")).lower() not in V.MISSING_TOKENS:
        return "fail"
    if code is None:
        return "undetermined"
    if code >= 400:
        return "fail"
    return "ok" if 200 <= code < 300 else "undetermined"


def _health(ctx, agg: _Agg) -> None:
    c = ctx.check("url_health", "Timestamped URL health joined to URL performance",
                  {**NEEDS, CHK: ["requested_url", "checked_at", "status_code"]})
    if not c.runnable:
        return
    checks: dict[str, list] = {}
    bad = 0
    for r in ctx.rows(CHK):
        url, t = _norm_url(r.get("requested_url"), agg.ignore), _dt(r.get("checked_at"))
        if url is None or t is None:
            bad += 1
            continue
        checks.setdefault(url, []).append((t, _classify(r), r))
    if bad:
        c.partial(f"{bad} check rows with unparseable requested_url/checked_at excluded")
    spend: dict[str, dict] = {}
    for (view, url), b in agg.url.items():
        if b["cost"] > 0 or b["clicks"] > 0:
            spend.setdefault(url, {})[view] = {"clicks": b["clicks"], "cost": b["cost"]}
    untested = sorted(u for u in spend if u not in checks)
    if untested:
        c.partial(f"{len(untested)} spending URLs have no health check: unassessed, not healthy")
    for url in sorted(u for u in spend if u in checks):
        rows = sorted(checks[url], key=lambda x: (x[0], _s(x[2].get("status_code"))))
        decisive = [x for x in rows if x[1] in ("ok", "fail")]
        run_ = []
        for x in reversed(decisive):
            if x[1] != "fail":
                break
            run_.append(x)
        run_.reverse()
        any_fail = any(x[1] == "fail" for x in decisive)
        entity = {"url": url}
        hist = [{"checked_at": x[0].isoformat(), "status_code": x[2].get("status_code"),
                 "access_error": x[2].get("access_error"), "final_url": x[2].get("final_url"), "class": x[1]}
                for x in rows[-5:]]
        ev = {"checks_recent": hist, "window_context": spend[url], "window": [ctx.period_start, ctx.period_end],
              "affected_cost": None, "affected_cost_note": "unknown: no traffic measured inside the failure interval"}
        if run_:
            first, last = run_[0][0], run_[-1][0]
            ev["failure_interval"] = [first.isoformat(), last.isoformat()]
            if agg.has_date:
                ev["cost_on_failure_dates_overlap"] = {
                    v: sum(cost for (vv, uu, d), cost in agg.daily.items()
                           if vv == v and uu == url and first.date() <= d <= last.date())
                    for v in sorted(spend[url])}
        if len(run_) >= PERSISTENT_RUN:
            prov = c.finding("url_persistent_failure", "Warning", entity,
                             f"{url} failed its last {len(run_)} checks ({ev['failure_interval'][0]} → "
                             f"{ev['failure_interval'][1]}) and had paid traffic in the period",
                             evidence=ev, calculation={"trailing_failed_checks": len(run_), "rule": ">= 2 trailing fails"},
                             recommendation="Urgent destination-owner review; confirm with repeat browser checks (skill-079).",
                             uncertainty="Window cost is context, not spend during the failure.")
            c.review("url_persistent_failure", entity,
                     f"Is there evidence of material paid traffic to {url} during the measured failure interval?",
                     evidence=ev, provisional=prov,
                     outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                              "Prioritize the fix; cite the traffic-in-interval evidence."},
                               "not_evidenced": {"severity": "Warning", "recommendation": "Keep as Warning."}},
                     guidance="Critical needs proposal.evidence_ref to time-segmented traffic inside the interval.")
        elif run_:
            c.finding("url_single_failed_check", "Info", entity, f"{url} failed its latest check only once in a row",
                      evidence=ev, recommendation="Request a repeat browser check before any action (skill-079).",
                      uncertainty="A single check can be a bot block or transient error.")
        elif any_fail:
            c.finding("url_failure_then_success", "Info", entity,
                      f"{url} failed an earlier check but passed a later one", evidence=ev,
                      recommendation="Ask skill-079 owner whether an incident window is confirmed.",
                      uncertainty="Intermittent failure; exposure during the failure is unmeasured.")
        else:
            c.observe(f"{url}: checks pass or are undetermined", url=url, checks=len(rows),
                      undetermined=sum(1 for x in rows if x[1] == "undetermined"))
    orphan = sorted(u for u in checks if u not in spend)
    c.observe("URL health join", checked_urls=len(checks), spending_urls=len(spend), untested=len(untested),
              checks_without_spend=len(orphan))


def verify(ctx, item, decision) -> list[str]:
    """Rules: evidence-based outcomes (Critical failure, Warning page defect) require proposal.evidence_ref."""
    if decision.get("outcome") in ("material_failure_evidenced", "page_defect_evidenced") \
            and not (decision.get("proposal") or {}).get("evidence_ref"):
        return [f"outcome {decision.get('outcome')} needs proposal.evidence_ref to supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
