"""check.py — skill-125 deterministic review of supplied URL probes, bounded exposure and request-only monitors.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-125-landing-page-health-check-automation/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #80 Check if campaign websites are live and respond fast enough (Siebe Hiemstra) — clean-room
         reimplementation of HTTP-status and response-time checks over SUPPLIED url_health probes; nothing is fetched
         index #87 Check landing page content for out-of-stock items (Brainlabs) — clean-room reimplementation of marker
         matching over supplied url_health.mobile_task_result using profile.out_of_stock_markers only; review, never pause
rules:   Never fetches a URL. Active destinations = ENABLED ads final_url plus ENABLED keyword final_url overrides, exact
         strings (query strings kept, checkout flows never merged).
         Probe classes: fail = HTTP >= 500, 404/410, other 4xx except 401/403/407/429, or tls_valid false.
         denied = 401/403/407/429, possibly bot denial, never a deterministic Warning. ok = 2xx/3xx with TLS not false.
         Probes are grouped per exact URL + device and ordered by checked_at. A run of >= 2 consecutive failing probes on
         an active destination is a Warning (repeated test failure) unless all failures share one test_region while
         another region passed inside the run (region issue → Info). A single failing probe is Info.
         Critical only via review with proposal.evidence_ref from the run's own probes.
         Performance: load_value_ms > policy performance_limit_ms; >= 2 consecutive violations → Warning, one → Info.
         Redirect: repeated deviation from policy expected_redirects → Warning, a single deviation → Info. Without a
         policy row these checks are skipped for that URL. There is no universal speed limit.
         Exposure: buckets (url_daily, or url_interval when supplied) overlapping the evidenced span [first failed probe,
         first passing probe after] are an UPPER BOUND on potentially affected exposure. Incident-window cost is never
         derived from discrete probes. 30-day prioritization exposure is reported separately.
         Out-of-stock markers come only from profile.out_of_stock_markers (case-insensitive substrings); no defaults.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-125-landing-page-health-check-automation"
VERSION = "1.0.0"

HEALTH = "external/url_health"
DAILY = "custom/url_daily"
INTERVAL = "custom/url_interval"
POLICY = "external/url_monitor_policy"
DENIED = (401, 403, 407, 429)


def _ts(v) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tz(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(str(name)) if name else None
    except Exception:  # noqa: BLE001 — missing tz database → fall back to the timestamp's own offset
        return None


def _local(dt: datetime, tz) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(tz) if tz is not None else dt


def _naive(dt: datetime, tz) -> datetime:
    """Account-local wall time without tzinfo, for comparison with local metric buckets."""
    return _local(dt, tz).replace(tzinfo=None)


def _classify(p: dict) -> str:
    status = V.integer(p.get("http_status"))
    tls = V.boolean(p.get("tls_valid"))
    if tls is False:
        return "fail"
    if status is None:
        return "unknown"
    if status in DENIED:
        return "denied"
    if status >= 400:
        return "fail"
    return "ok" if 200 <= status < 400 else "unknown"


def _scope_match(scope: str, url: str) -> bool:
    scope = str(scope or "").strip()
    if not scope:
        return False
    return url.startswith(scope[:-1]) if scope.endswith("*") else url == scope


def _runs(probes: list[dict], cls: str) -> list[list[dict]]:
    out, cur = [], []
    for p in probes:
        if p["class"] == cls:
            cur.append(p)
        elif p["class"] != "unknown":
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def run(ctx) -> None:
    """Run active-destination probe classification, repeated failure, performance, redirect and out-of-stock checks.

    Rules:   Never fetches URLs. >= 2 consecutive failing probes → Warning unless region-specific (Info); single failure
             → Info; 401/403/407/429 is access-denied Info + review, never deterministic Warning. Critical only via
             review with proposal.evidence_ref from the run's probes. Performance/redirect checks need a policy row
             (else skipped). Out-of-stock only from profile.out_of_stock_markers; exposure is an upper bound, not
             incident cost.
    """
    tzname = ctx.account.get("time_zone")
    tz = _tz(tzname)

    # -- step 1: destination inventory
    inv = ctx.check("destination_inventory", "Active destination associations",
                    {"ads": ["id", "campaign_id", "ad_group_id", "final_url", "status"]})
    active: dict[str, list[dict]] = {}
    if inv.runnable:
        for a in sorted(ctx.rows("ads"), key=lambda r: str(r.get("id"))):
            if str(a.get("status") or "").upper() == "ENABLED" and a.get("final_url"):
                active.setdefault(str(a["final_url"]).strip(), []).append(
                    {"type": "ad", "id": a.get("id"), "campaign_id": a.get("campaign_id"), "ad_group_id": a.get("ad_group_id")})
        kw = ctx.table("keywords")
        if kw is None or kw.missing(["id", "campaign_id", "ad_group_id", "final_url"]):
            inv.partial("keyword final URL overrides unknown", ["keywords (file)"] if kw is None else
                        [f"keywords:{c}" for c in kw.missing(["id", "campaign_id", "ad_group_id", "final_url"])])
        else:
            for k in sorted(kw.rows, key=lambda r: str(r.get("id"))):
                if str(k.get("status") or "ENABLED").upper() == "ENABLED" and k.get("final_url"):
                    active.setdefault(str(k["final_url"]).strip(), []).append(
                        {"type": "keyword", "id": k.get("id"), "campaign_id": k.get("campaign_id"), "ad_group_id": k.get("ad_group_id")})
        for url, ents in sorted(active.items()):
            inv.observe(f"Destination {url}", url=url, entities=ents, campaigns=sorted({str(e["campaign_id"]) for e in ents}))
        inv.observe("Inventory totals", active_urls=len(active), associations=sum(map(len, active.values())),
                    note="A URL inventory cannot prove health.")

    # serving priority (ad_metrics) per URL
    serving: dict[str, dict] = {}
    if ctx.table("ad_metrics") is not None and not ctx.table("ad_metrics").missing(["ad_id", "clicks"]):
        by_ad = {}
        for m in ctx.rows("ad_metrics"):
            key = str(m.get("ad_id"))
            by_ad[key] = (by_ad.get(key, 0.0) or 0.0) + (V.num(m.get("clicks")) or 0.0)
        for url, ents in active.items():
            serving[url] = {"ad_clicks": sum(by_ad.get(str(e["id"]), 0.0) for e in ents if e["type"] == "ad")}

    # -- step 2: dated probe results
    probe = ctx.check("probe_results", "Dated HTTP/TLS/mobile probe results",
                      {HEALTH: ["test_id", "URL", "device", "checked_at", "http_status", "tls_valid", "test_region",
                                "evidence_ref"]})
    perf = ctx.check("redirect_performance", "Redirects and performance against documented requirements",
                     {HEALTH: ["URL", "device", "checked_at", "load_metric_name", "load_value_ms", "redirect_chain"],
                      POLICY: ["monitor_id", "URL_scope", "expected_redirects", "performance_limit_ms"]})
    expo = ctx.check("incident_exposure", "Serving priority and bounded incident exposure",
                     {DAILY: ["campaign_id", "ad_group_id", "ad_or_keyword_id", "URL", "date", "clicks", "cost"]})
    monitor = ctx.check("monitor_draft", "Request-only monitoring checks",
                        {POLICY: ["monitor_id", "URL_scope", "test_cadence", "critical_customer_task", "expected_redirects",
                                  "performance_limit_ms", "owner", "approval_status", "recovery_check"]})
    policies = sorted(ctx.rows(POLICY), key=lambda r: str(r.get("monitor_id")))
    pol_for = lambda url: next((p for p in policies if _scope_match(p.get("URL_scope"), url)), None)
    if tzname and tz is None:
        probe.partial(f"time zone {tzname} unavailable locally: probe dates use their own UTC offset")

    series: dict[tuple, list[dict]] = {}
    if probe.runnable:
        bad = naive = 0
        for r in ctx.rows(HEALTH):
            dt = _ts(r.get("checked_at"))
            if dt is None:
                bad += 1
                continue
            naive += dt.tzinfo is None
            series.setdefault((str(r.get("URL") or "").strip(), str(r.get("device") or "").upper()), []).append(
                {**r, "_dt": dt, "class": _classify(r)})
        if naive:
            probe.partial(f"{naive} naive checked_at timestamps read as account-local time")
        if bad:
            probe.partial(f"{bad} probes without a parseable checked_at")
        for k in series:
            series[k].sort(key=lambda p: (p["_dt"].astimezone(timezone.utc) if p["_dt"].tzinfo else p["_dt"].replace(tzinfo=timezone.utc),
                                          str(p.get("test_id"))))

    # metric buckets for exposure
    buckets: dict[str, list[dict]] = {}
    has_daily_device = False
    if expo.runnable:
        t = ctx.table(DAILY)
        has_daily_device = "device" in t.columns
        for r in t.rows:
            d = V.parse_date(r.get("date"))
            if d is None:
                continue
            buckets.setdefault(str(r.get("URL") or "").strip(), []).append(
                {"start": datetime.combine(d, datetime.min.time()), "end": datetime.combine(d + timedelta(days=1), datetime.min.time()),
                 "cost": ctx.money(r.get("cost")), "clicks": V.num(r.get("clicks")), "device": str(r.get("device") or "").upper(),
                 "grain": "daily", "date": d})
        it = ctx.table(INTERVAL)
        if it is not None and not it.missing(["URL", "interval_start", "interval_end", "clicks", "cost"]):
            fine: dict[str, list[dict]] = {}
            for r in it.rows:
                s, e = _ts(r.get("interval_start")), _ts(r.get("interval_end"))
                if s and e:
                    fine.setdefault(str(r.get("URL") or "").strip(), []).append(
                        {"start": _naive(s, tz), "end": _naive(e, tz), "cost": ctx.money(r.get("cost")),
                         "clicks": V.num(r.get("clicks")), "device": str(r.get("device") or "").upper(), "grain": "interval"})
            buckets.update(fine)
            expo.observe("Finer url_interval buckets replace daily buckets for bounds", urls=sorted(fine))
        else:
            expo.partial("no custom/url_interval: bounds use whole daily buckets")
        end = ctx.as_of
        for url in sorted(buckets):
            recent = [b for b in buckets[url] if b["grain"] == "daily" and end and end - timedelta(days=29) <= b["date"] <= end]
            if recent:
                expo.observe(f"{url}: 30-day prioritization exposure (not incident cost)", url=url,
                             window=[end - timedelta(days=29), end], clicks=sum(b["clicks"] or 0 for b in recent),
                             cost=None if any(b["cost"] is None for b in recent) else sum(b["cost"] for b in recent),
                             ad_clicks_period=(serving.get(url) or {}).get("ad_clicks"))

    def exposure(url: str, device: str, run_: list[dict], after: dict | None) -> dict:
        if not expo.runnable:
            return {"state": "unknown: custom/url_daily missing"}
        start = _naive(run_[0]["_dt"], tz)
        stop = _naive((after or run_[-1])["_dt"], tz)
        rows = [b for b in buckets.get(url, []) if b["start"] <= stop and b["end"] > start
                and (not b["device"] or not device or b["device"] == device)]
        cost = None if any(b["cost"] is None for b in rows) else sum(b["cost"] for b in rows)
        return {"evidenced_span": [start, stop], "span_end": "first passing probe" if after else "last failing probe (not recovered)",
                "start_before_first_failure": "unknown (no earlier passing probe)" if run_[0].get("_prev_ok") is None else
                _naive(run_[0]["_prev_ok"]["_dt"], tz),
                "potentially_affected_exposure_upper_bound": {"cost": cost, "clicks": sum(b["clicks"] or 0 for b in rows),
                                                              "buckets": [[b["start"], b["end"]] for b in rows],
                                                              "bucket_grain": sorted({b["grain"] for b in rows})},
                "incident_window_cost": None,
                "incident_window_note": "not established: discrete probes do not prove a continuous outage; an "
                                        "overlapping bucket is an upper bound, not incident-window cost",
                "device_matched": has_daily_device}

    markers = [str(m).lower() for m in (ctx.profile.get("out_of_stock_markers") or []) if str(m).strip()]
    if probe.runnable and not markers:
        probe.partial("out-of-stock content screen off: profile.out_of_stock_markers not declared")
    totals = {"series": len(series), "failure_runs": 0, "denied_runs": 0, "inactive_urls_tested": 0}
    for (url, device), probes in sorted(series.items()):
        prev_ok = None
        for p in probes:
            p["_prev_ok"] = prev_ok
            if p["class"] == "ok":
                prev_ok = p
        is_active = url in active
        if not is_active:
            totals["inactive_urls_tested"] += 1
            probe.observe(f"{url} [{device}]: tested URL is not an active destination", url=url, device=device,
                          probes=len(probes))
        pol = pol_for(url)
        for cls in ("fail", "denied"):
            for run_ in _runs(probes, cls):
                idx = probes.index(run_[-1])
                after = next((p for p in probes[idx + 1:] if p["class"] == "ok"), None)
                totals["failure_runs" if cls == "fail" else "denied_runs"] += 1
                regions = sorted({str(p.get("test_region") or "") for p in run_})
                span = (run_[0]["_dt"], run_[-1]["_dt"])
                other_ok = [p for p in probes if p["class"] == "ok" and span[0] <= p["_dt"] <= span[1]]
                other_region_ok = [p for (u, _d), ps in series.items() if u == url for p in ps
                                   if p["class"] == "ok" and span[0] <= p["_dt"] <= span[1]
                                   and str(p.get("test_region") or "") not in regions]
                entity = {"url": url, "device": device, "first_failed_test_id": run_[0].get("test_id")}
                ev = {"url": url, "device": device, "active_destination": is_active,
                      "associations": active.get(url, []), "probe_class": cls,
                      "failed_probes": [{"test_id": p.get("test_id"), "checked_at": p.get("checked_at"),
                                         "http_status": p.get("http_status"), "tls_valid": p.get("tls_valid"),
                                         "test_region": p.get("test_region"), "user_agent": p.get("user_agent"),
                                         "mobile_task_result": p.get("mobile_task_result"),
                                         "evidence_ref": p.get("evidence_ref")} for p in run_],
                      "recovery": {"status": "recovered" if after else "not recovered by last probe",
                                   "recovered_at": after.get("checked_at") if after else None,
                                   "recovery_test_id": after.get("test_id") if after else None},
                      "regions": regions, "other_region_passed_during_run": bool(other_region_ok),
                      "policy_monitor_id": pol.get("monitor_id") if pol else None,
                      "critical_customer_task": pol.get("critical_customer_task") if pol else None,
                      "exposure": exposure(url, device, run_, after), "passing_probes_inside_run": len(other_ok)}
                if not is_active:
                    continue
                if cls == "denied":
                    f = probe.finding("access_denied_probe", "Info", entity,
                                      f"{url} [{device}]: {len(run_)} access-denied probe(s) "
                                      f"({', '.join(sorted({str(p.get('http_status')) for p in run_}))}); possible bot denial",
                                      evidence=ev, recommendation="Re-test with a real-user agent before treating as a failure.",
                                      uncertainty="401/403/407/429 often reflect bot protection, not customer blocking.")
                    if len(run_) >= 2:
                        probe.review("access_denied_probe", entity,
                                     f"Do the repeated denials of {url} [{device}] block real customers?",
                                     evidence=ev, provisional=f,
                                     outcomes={"user_blocking": {"severity": "Warning", "recommendation":
                                               "Hand to the technical owner; confirm with a real-user test."},
                                               "bot_denial": {"severity": None, "recommendation": "Allow-list the test agent."},
                                               "uncertain": {"severity": "Info", "recommendation": "Request a real-browser probe."}},
                                     guidance="Use user_agent, mobile_task_result and evidence_ref only.")
                    continue
                if len(run_) == 1:
                    probe.finding("single_failure_probe", "Info", entity,
                                  f"{url} [{device}]: single failed probe {run_[0].get('test_id')} at "
                                  f"{run_[0].get('checked_at')} (HTTP {run_[0].get('http_status')}); "
                                  f"{ev['recovery']['status']}; outage duration uncertain",
                                  evidence=ev,
                                  recommendation="Propose a confirmation retry policy; no incident cost is attributed.",
                                  uncertainty="One discrete probe does not establish a continuous outage; overlapping "
                                              "bucket cost is only an upper bound on potentially affected exposure.")
                    continue
                if other_region_ok and len(regions) == 1:
                    probe.finding("region_specific_failure", "Info", entity,
                                  f"{url} [{device}]: {len(run_)} failures from region {regions[0]} while another region passed",
                                  evidence=ev, recommendation="Check regional CDN/geo rules with the technical owner.",
                                  uncertainty="One test-region issue is not a reproducible user-blocking failure.")
                    continue
                f = probe.finding("repeated_test_failure", "Warning", entity,
                                  f"{url} [{device}]: {len(run_)} consecutive failed probes from "
                                  f"{run_[0].get('checked_at')} to {run_[-1].get('checked_at')}; {ev['recovery']['status']}",
                                  evidence=ev,
                                  recommendation="Repair handoff to the technical owner (skill-079); alert-only monitor with "
                                                 "a confirmation retry. No ads are paused here.",
                                  uncertainty="Probes are discrete; exposure figures are upper bounds.")
                probe.review("repeated_test_failure", entity,
                             f"Does this repeated failure of an active destination materially block the intended customer "
                             f"task ({ev['critical_customer_task'] or 'task not declared'})?",
                             evidence=ev,
                             outcomes={"confirmed_task_block": {"severity": "Critical", "recommendation":
                                       "Escalate to the technical owner now; cite the probe evidence_ref."},
                                       "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
                             guidance="Critical requires proposal.evidence_ref equal to one failed probe's evidence_ref "
                                      "and a documented critical_customer_task.")
        # index #87: out-of-stock markers in supplied task results
        if markers and is_active:
            matched = [p for p in probes if p["class"] == "ok" and any(m in str(p.get("mobile_task_result") or "").lower()
                                                                       for m in markers)]
            if matched:
                entity = {"url": url, "device": device, "content": "out_of_stock_marker"}
                ev = {"url": url, "device": device, "markers": markers, "matched_probes": len(matched),
                      "probes": [{"test_id": p.get("test_id"), "checked_at": p.get("checked_at"),
                                  "mobile_task_result": p.get("mobile_task_result"), "evidence_ref": p.get("evidence_ref")}
                                 for p in matched],
                      "critical_customer_task": pol.get("critical_customer_task") if pol else None}
                f = probe.finding("out_of_stock_content", "Info", entity,
                                  f"{url} [{device}]: {len(matched)} probe(s) report an out-of-stock marker",
                                  evidence=ev, recommendation="Confirm availability with the merchandising owner.",
                                  uncertainty="Marker text match on supplied results only; the page was not fetched.")
                probe.review("out_of_stock_content", entity,
                             f"Do the out-of-stock results for {url} [{device}] block the intended customer task?",
                             evidence=ev, provisional=f,
                             outcomes={"confirmed_task_block": {"severity": "Critical", "recommendation":
                                       "Escalate; request-only ad/URL change with the owner."},
                                       "repeated_task_failure": {"severity": "Warning", "recommendation":
                                       "Hand to merchandising; monitor availability."},
                                       "not_blocking": {"severity": None, "recommendation": "No action."},
                                       "uncertain": {"severity": "Info", "recommendation": "Request a dated availability check."}},
                             guidance="Warning needs >= 2 matched probes; Critical needs proposal.evidence_ref from them.")
    if probe.runnable:
        probe.observe("Probe totals", **totals)

    # -- step 3: redirects and performance against the documented policy
    if perf.runnable:
        checked = 0
        for (url, device), probes in sorted(series.items()):
            pol = pol_for(url)
            if pol is None:
                perf.partial(f"{url}: no url_monitor_policy scope; requirements undocumented")
                continue
            limit = V.num(pol.get("performance_limit_ms"))
            expected = str(pol.get("expected_redirects") or "").strip()
            timed = [p for p in probes if V.num(p.get("load_value_ms")) is not None]
            viol = [p for p in timed if limit is not None and V.num(p["load_value_ms"]) > limit]
            checked += len(timed)
            for p in timed:
                p["class_perf"] = "violation" if p in viol else "ok"
            runs, cur = [], []
            for p in timed:
                if p["class_perf"] == "violation":
                    cur.append(p)
                else:
                    if cur:
                        runs.append(cur)
                    cur = []
            if cur:
                runs.append(cur)
            for run_ in runs:
                sev = "Warning" if len(run_) >= 2 and url in active else "Info"
                perf.finding("performance_violation", sev, {"url": url, "device": device, "first_test_id": run_[0].get("test_id")},
                             f"{url} [{device}]: {len(run_)} consecutive probe(s) above {limit:g} ms "
                             f"({', '.join(str(p.get('load_metric_name')) for p in run_)})",
                             evidence={"limit_ms": limit, "policy_monitor_id": pol.get("monitor_id"), "active_destination": url in active,
                                       "probes": [{"test_id": p.get("test_id"), "checked_at": p.get("checked_at"),
                                                   "metric": p.get("load_metric_name"), "value_ms": V.num(p.get("load_value_ms")),
                                                   "test_region": p.get("test_region")} for p in run_]},
                             recommendation="Hand to skill-078 / technical owner; the limit is the client's documented requirement.",
                             uncertainty="Named lab/field metric only; no Quality Score or conversion claim.")
            if expected:
                none = expected.lower() in ("none", "no", "0", "direct")
                exp_chain = [] if none else V.split_list(expected, (" -> ", ">", ";", "|", ","))
                dev = []
                for p in probes:
                    chain = V.split_list(p.get("redirect_chain"), (" -> ", ">", ";", "|", ","))
                    moved = p.get("resolved_url") and p.get("requested_url") and p["resolved_url"] != p["requested_url"]
                    if chain != exp_chain or (none and moved):
                        dev.append(p)
                if dev:
                    sev = "Warning" if len(dev) >= 2 and url in active else "Info"
                    perf.finding("redirect_mismatch", sev, {"url": url, "device": device},
                                 f"{url} [{device}]: {len(dev)} probe(s) deviate from expected redirects '{expected}'",
                                 evidence={"expected_redirects": expected, "policy_monitor_id": pol.get("monitor_id"),
                                           "probes": [{"test_id": p.get("test_id"), "redirect_chain": p.get("redirect_chain"),
                                                       "requested_url": p.get("requested_url"), "resolved_url": p.get("resolved_url")}
                                                      for p in dev]},
                                 recommendation="Confirm required tracking parameters survive the redirect chain.",
                                 uncertainty="Compared literally against the documented expectation.")
        perf.observe("Timed probes compared with documented limits", probes=checked)

    # -- step 5: request-only monitoring draft
    if monitor.runnable:
        for p in policies:
            missing = [c for c in ("test_cadence", "owner", "recovery_check") if not p.get(c)]
            if missing:
                monitor.partial(f"monitor {p.get('monitor_id')}: missing {', '.join(missing)}")
            monitor.observe(f"Monitor {p.get('monitor_id')}: request-only alert check", monitor_id=p.get("monitor_id"),
                            url_scope=p.get("URL_scope"), cadence=p.get("test_cadence"),
                            expected={"customer_task": p.get("critical_customer_task"), "redirects": p.get("expected_redirects"),
                                      "performance_limit_ms": V.num(p.get("performance_limit_ms"))},
                            confirmation="alert after 2 consecutive failed probes (proposed retry policy)",
                            dedupe="one open alert per URL/device until recovery", recovery=p.get("recovery_check"),
                            owner=p.get("owner"), approval_status=p.get("approval_status"),
                            action="alert only; no ad pause and no external page test is run here")
        uncovered = sorted(u for u in active if pol_for(u) is None)
        monitor.observe("Active destinations without a monitor scope", urls=uncovered)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref from the reviewed probes; repeated content failure needs >= 2 probes."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    ev = item.evidence
    if outcome == "confirmed_task_block":
        refs = {str(p.get("evidence_ref")) for p in (ev.get("failed_probes") or ev.get("probes") or []) if p.get("evidence_ref")}
        ref = str(proposal.get("evidence_ref") or "")
        problems = [] if ref in refs else [f"proposal.evidence_ref must be one of {sorted(refs)}"]
        if not ev.get("critical_customer_task"):
            problems.append("no documented critical_customer_task in url_monitor_policy for this URL")
        return problems
    if outcome == "repeated_task_failure" and (ev.get("matched_probes") or 0) < 2:
        return ["repeated_task_failure needs >= 2 matched probes"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
