"""check.py — skill-148 deterministic seasonal query calendar, coverage and launch-readiness checks.

exports: SKILL | VERSION | PLAN | HIST | run(ctx) -> None
used_by: skills/skill-148-seasonal-keyword-calendar-planning/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Plan = external/seasonal_keyword_plan; an event is upcoming when end_at is unknown or >= ctx.as_of, past
         when end_at < ctx.as_of. Prior occurrences = past plan rows sharing the SAME event_id (actual moving-holiday
         dates); none → weekday-aligned 364-day shift, flagged in coverage. Never join events by name.
         approved means approval_status == 'approved' (case-insensitive); anything else, blank included, is not approved.
         normal_baseline_dates accepts 'YYYY-MM-DD..YYYY-MM-DD' (or '/') ranges separated by ';', '|' or ','; else partial.
         History candidates (Info, routed to skill-013) need ctx.mature True, prior-window clicks >= min_clicks and
         conversions > 0; CPA/ROAS only when conversions >= min_conversions. Queries whose 4-digit year differs from
         the event start year are obsolete-year language, never candidates. Rows younger than lag days are excluded.
         Negative conflicts use adsrun.negatives literal semantics in the history ad group's effective scope (or every
         active ad group of the campaign when that group is not in inventory). Whether the blocked query is desired
         traffic is ai_review; Warning only through that review for an APPROVED upcoming event.
         Absence of a literal keyword is never a coverage finding; 'coverage_unverified' is Info for gate-passing
         candidates with no literal keyword containment, no current served row and no negative block.
         Deterministic Warning only when a draft_copy_ref equals an ads.id that is REMOVED or DISAPPROVED for an
         approved upcoming event (directly evidenced unavailable content). No fixed lead time is ever applied.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
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
from adsrun.negatives import blocks, effective_negatives  # noqa: E402

SKILL = "skill-148-seasonal-keyword-calendar-planning"
VERSION = "1.0.0"

PLAN = "external/seasonal_keyword_plan"
HIST = "custom/seasonal_query_history"
PLAN_KEY = ["event_id", "campaign_id", "start_at", "end_at", "approval_status"]
PLAN_CALENDAR = ["name", "start_at", "end_at", "timezone", "objective", "offer", "owner", "approval_status",
                 "normal_baseline_dates", "stock_or_capacity"]
PLAN_OPTIONAL = ["expected_cvr_change", "rationale"]
HIST_NEEDS = ["campaign_id", "ad_group_id", "query", "date", "impressions", "clicks", "cost", "conversions"]
HIST_OPTIONAL = ["account_id", "matched_keyword_id", "match_type", "conversion_value", "reported_coverage"]
_YEAR = re.compile(r"^(19|20)\d\d$")
_INACTIVE = ("REMOVED", "DELETED", "PAUSED")


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _ranges(v) -> list[tuple] | None:
    """Parse normal_baseline_dates; [] when empty, None when any part is unparseable."""
    out = []
    for part in V.split_list(v, (";", "|", ",")):
        bits = part.split("..") if ".." in part else part.split("/")
        if len(bits) != 2:
            return None
        a, b = V.parse_date(bits[0].strip()), V.parse_date(bits[1].strip())
        if a is None or b is None or b < a:
            return None
        out.append((a, b))
    return out


def _events(ctx) -> list[dict]:
    out = []
    for i, r in enumerate(ctx.rows(PLAN)):
        out.append({"line": i + 2, "event_id": _s(r.get("event_id")), "campaign_id": _s(r.get("campaign_id")),
                    "start": V.parse_date(r.get("start_at")), "end": V.parse_date(r.get("end_at")),
                    "approved": _s(r.get("approval_status")).lower() == "approved", "raw": r})
    return sorted(out, key=lambda e: (e["event_id"], e["campaign_id"], str(e["start"]), e["line"]))


def _upcoming(ctx, e) -> bool:
    return e["end"] is None or e["end"] >= ctx.as_of


def _prior_windows(events, e) -> tuple[list[tuple], str]:
    """Prior occurrences of the same event_id (actual dates) or a 364-day weekday-aligned shift."""
    anchor = e["start"]
    past = sorted({(p["start"], p["end"]) for p in events
                   if p is not e and p["event_id"] == e["event_id"] and p["start"] and p["end"]
                   and anchor is not None and p["end"] < anchor}, reverse=True)
    if past:
        return past, "actual prior dates of the same event_id"
    if e["start"] and e["end"]:
        return [(e["start"] - timedelta(days=364), e["end"] - timedelta(days=364))], \
            "364-day weekday-aligned shift (moving-holiday alignment unverified)"
    return [], "event dates unknown"


def _in(d, windows) -> bool:
    return d is not None and any(a <= d <= b for a, b in windows)


def _event_entity(e) -> dict:
    return {"event_id": e["event_id"], "campaign_id": e["campaign_id"]}


def _aggregate(ctx, campaign_id, windows, cutoff) -> tuple[dict, dict]:
    """Sum history rows for one campaign inside windows → {(ad_group_id, query): metrics}, plus stats."""
    agg: dict = {}
    stats = {"rows": 0, "duplicates": 0, "immature": 0}
    seen = set()
    for r in ctx.rows(HIST):
        if _s(r.get("campaign_id")) != campaign_id:
            continue
        d = V.parse_date(r.get("date"))
        if not _in(d, windows):
            continue
        if cutoff is not None and d > cutoff:
            stats["immature"] += 1
            continue
        grain = (_s(r.get("ad_group_id")), V.norm_text(r.get("query")), _s(r.get("matched_keyword_id")), d)
        if grain in seen:
            stats["duplicates"] += 1
            continue
        seen.add(grain)
        stats["rows"] += 1
        acc = agg.setdefault(grain[:2], {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0,
                                         "conversion_value": 0.0, "query": _s(r.get("query")),
                                         "match_types": set(), "keyword_ids": set()})
        for col, parse in (("impressions", V.num), ("clicks", V.num), ("cost", ctx.money),
                           ("conversions", V.num), ("conversion_value", ctx.money)):
            val = parse(r.get(col))
            acc[col] = None if val is None or acc[col] is None else acc[col] + val
        if r.get("match_type"):
            acc["match_types"].add(_s(r.get("match_type")).upper())
        if r.get("matched_keyword_id"):
            acc["keyword_ids"].add(_s(r.get("matched_keyword_id")))
    return agg, stats


def run(ctx) -> None:
    """Run the seasonal event calendar, historical candidates, negative conflicts, coverage and readiness checks.

    Rules:   Events join by event_id only; approved means approval_status 'approved'. History candidates need ctx.mature
             True, clicks >= min_clicks and conversions > 0 → Info routed to skill-013; obsolete-year queries excluded.
             Negative conflicts are Info + ai_review (Warning only for APPROVED upcoming events). Deterministic Warning
             only for a draft_copy_ref ad REMOVED/DISAPPROVED; missing literal keywords are never coverage findings, no
             fixed lead time.
    """
    cal = ctx.check("event_calendar", "Approved event offers, availability and target dates (step 1)",
                    {PLAN: PLAN_KEY, "campaigns": ["id"]})
    steps = (("historical_queries", "Historical event queries and outcome evidence (step 2)", {HIST: HIST_NEEDS}),
             ("current_coverage", "Current reach and negative conflicts for event queries (step 3)", {
                 HIST: HIST_NEEDS, "keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type", "status"],
                 "search_terms": ["search_term", "campaign_id", "ad_group_id", "clicks"],
                 "negative_keywords": ["text", "match_type", "level", "campaign_id"],
                 "ad_groups": ["id", "campaign_id"]}),
             ("ad_page_readiness", "Ad/page readiness from actual drafts (step 4)",
              {PLAN: ["draft_copy_ref", "landing_page_ref"]}),
             ("launch_timing", "Launch timing from approvals and stock, no fixed lead time (step 5)",
              {PLAN: ["planned_launch_at", "planned_pause_at", "approval_dependencies"]}),
             ("routing", "Route candidates to skill-013 and schedules to skill-130 (step 6)", {}))
    if not cal.runnable or ctx.as_of is None:
        if ctx.as_of is None:
            cal.skip("as-of date unknown: upcoming vs past events undecidable", ["account:date_range_end"])
        for cid, title, needs in steps:
            ctx.check(cid, title, needs).skip("seasonal plan or as-of date unavailable", cal.missing)
        return
    plan_t = ctx.table(PLAN)
    events = _events(ctx)
    campaigns = {_s(r.get("id")): r for r in ctx.rows("campaigns")}
    upcoming = [e for e in events if _upcoming(ctx, e)]
    absent_cal = plan_t.missing(PLAN_CALENDAR + PLAN_OPTIONAL)
    if absent_cal:
        cal.partial("declared plan columns absent; per-row completeness not assessed for them",
                    [f"{PLAN}:{c}" for c in absent_cal])
    horizon = ctx.as_of + timedelta(days=60)
    m_end = V.parse_date((plan_t.manifest or {}).get("period_end"))
    if m_end is None or m_end < horizon:
        cal.partial(f"calendar snapshot does not certify coverage through {horizon} (manifest period_end {m_end})")
    keys = {}
    for e in events:
        keys.setdefault((e["event_id"], e["campaign_id"], e["start"]), []).append(e["line"])
    for k, lines in sorted(keys.items(), key=lambda kv: str(kv[0])):
        if len(lines) > 1:
            cal.partial(f"duplicate plan rows for event {k[0]} campaign {k[1]} start {k[2]}: lines {lines}")
    search_events = []
    for e in upcoming:
        r, ent = e["raw"], _event_entity(e)
        camp = campaigns.get(e["campaign_id"])
        if camp is not None and camp.get("channel_type") and _s(camp.get("channel_type")).upper() != "SEARCH":
            cal.observe(f"Event {e['event_id']} targets non-Search campaign {e['campaign_id']}: outside scope",
                        **ent, channel_type=camp.get("channel_type"))
            continue
        present = [c for c in PLAN_CALENDAR if c not in absent_cal]
        missing = [c for c in present if not _s(r.get(c))]
        problems = []
        if camp is None:
            problems.append(f"campaign_id {e['campaign_id'] or '(blank)'} not in campaigns inventory")
        for col, val in (("start_at", e["start"]), ("end_at", e["end"])):
            if _s(r.get(col)) and val is None:
                problems.append(f"{col} '{r.get(col)}' is not a date")
        if e["start"] and e["end"] and e["end"] < e["start"]:
            problems.append(f"end_at {e['end']} before start_at {e['start']}")
        if "normal_baseline_dates" not in absent_cal and _s(r.get("normal_baseline_dates")) \
                and _ranges(r.get("normal_baseline_dates")) is None:
            problems.append(f"normal_baseline_dates '{r.get('normal_baseline_dates')}' unparseable")
        tz = _s(r.get("timezone"))
        if tz and ctx.account.get("time_zone") and tz != _s(ctx.account.get("time_zone")):
            cal.observe(f"Event {e['event_id']} timezone {tz} differs from account {ctx.account.get('time_zone')}",
                        **ent)
        if missing or problems:
            cal.finding("incomplete_calendar", "Info", ent,
                        f"Event {e['event_id']} (campaign {e['campaign_id']}) plan row {e['line']} is incomplete: "
                        + "; ".join([f"missing {', '.join(missing)}"] * bool(missing) + problems),
                        evidence={"plan_file": plan_t.filename, "line": e["line"], "missing_fields": missing,
                                  "problems": problems, "approval_status": r.get("approval_status"),
                                  "owner": r.get("owner")},
                        recommendation="Complete the approved offer, availability, dates and owner in the client "
                                       "calendar before planning coverage or launch.",
                        uncertainty="Plan completeness only; not a statement about account delivery.",
                        owner=_s(r.get("owner")) or None)
        if camp is not None:
            search_events.append(e)
    cal.observe("Seasonal calendar mapped", as_of=ctx.as_of, plan_rows=len(events), upcoming=len(upcoming),
                past=len(events) - len(upcoming), approved_upcoming=sum(e["approved"] for e in upcoming),
                search_upcoming=len(search_events))

    if not search_events:
        for cid, title, _ in steps:
            ctx.check(cid, title, applicable=False, na_reason="no upcoming Search-campaign event rows in the plan")
        return
    checks = [ctx.check(cid, title, needs) for cid, title, needs in steps]
    candidates = _historical(ctx, checks[0], events, search_events)
    _coverage(ctx, checks[1], events, search_events, candidates, checks[0])
    _readiness(ctx, checks[2], search_events)
    _timing(ctx, checks[3], search_events)
    _routing(ctx, checks[4], search_events, candidates)


def _historical(ctx, chk, events, search_events) -> dict:
    """Step 2: returns {(event_id, campaign_id): {(ad_group_id, query): metrics+flags}} of relevant queries."""
    out: dict = {}
    if not chk.runnable:
        return out
    absent = ctx.table(HIST).missing(HIST_OPTIONAL)
    if absent:
        chk.partial("optional history columns absent", [f"{HIST}:{c}" for c in absent])
    min_clicks, min_conv = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
    if min_clicks.value is None or min_conv.value is None:
        chk.partial(f"sample parameters unresolved: {min_clicks.reason or min_conv.reason}")
        return out
    if ctx.mature is not True:
        chk.partial(f"candidate prescriptions disabled: maturity={ctx.mature} ({ctx.maturity_note}); descriptive only")
    cutoff = ctx.snapshot - timedelta(days=ctx.lag_days) if ctx.snapshot and ctx.lag_days is not None else None
    for e in search_events:
        windows, method = _prior_windows(events, e)
        ent = _event_entity(e)
        if not windows:
            chk.partial(f"event {e['event_id']}/{e['campaign_id']}: no prior window ({method})")
            continue
        if not method.startswith("actual"):
            chk.partial(f"event {e['event_id']}/{e['campaign_id']}: {method}")
        agg, stats = _aggregate(ctx, e["campaign_id"], windows, cutoff)
        if stats["duplicates"]:
            chk.partial(f"event {e['event_id']}: {stats['duplicates']} duplicate history rows at declared grain ignored")
        if stats["immature"]:
            chk.partial(f"event {e['event_id']}: {stats['immature']} history rows after {cutoff} excluded as immature")
        normal = _ranges(e["raw"].get("normal_baseline_dates")) or []
        normal_agg = _aggregate(ctx, e["campaign_id"], normal, cutoff)[0] if normal else {}
        year = e["start"].year if e["start"] else None
        relevant = {}
        n_cand = n_obsolete = 0
        for key in sorted(agg, key=lambda k: (k[0], k[1])):
            m = agg[key]
            clicks, conv = m["clicks"], m["conversions"]
            years = {t for t in key[1].split() if _YEAR.match(t)}
            obsolete = bool(year and years and years != {str(year)})
            if not ((conv is not None and conv > 0) or (clicks is not None and clicks >= min_clicks.value)):
                continue
            nm = normal_agg.get(key, {})
            cvr = V.ratio(conv, clicks) if clicks is not None and clicks >= min_clicks.value else None
            n_cvr = V.ratio(nm.get("conversions"), nm.get("clicks")) \
                if (nm.get("clicks") or 0) >= min_clicks.value else None
            gated_conv = conv is not None and conv >= min_conv.value
            ev = {"prior_windows": [f"{a}..{b}" for a, b in windows], "alignment": method,
                  "impressions": m["impressions"], "clicks": clicks, "cost": m["cost"], "conversions": conv,
                  "conversion_value": m["conversion_value"], "cvr": cvr,
                  "cpa": V.ratio(m["cost"], conv) if gated_conv else None,
                  "roas": V.ratio(m["conversion_value"], m["cost"]) if gated_conv else None,
                  "normal_windows": [f"{a}..{b}" for a, b in normal], "normal_clicks": nm.get("clicks"),
                  "normal_cvr": n_cvr, "event_vs_normal_cvr": V.ratio(cvr, n_cvr),
                  "match_types": sorted(m["match_types"]), "matched_keyword_ids": sorted(m["keyword_ids"]),
                  "min_clicks": min_clicks.value, "min_clicks_source": min_clicks.source,
                  "min_conversions": min_conv.value, "min_conversions_source": min_conv.source,
                  "currency": ctx.currency}
            if obsolete:
                n_obsolete += 1
                chk.observe(f"'{m['query']}' carries year {sorted(years)} ≠ event year {year}: obsolete-year language",
                            **ent, ad_group_id=key[0], clicks=clicks, conversions=conv)
                continue
            candidate = ctx.mature is True and cvr is not None and conv is not None and conv > 0
            relevant[key] = {**m, "evidence": ev, "candidate": candidate}
            if not candidate:
                continue
            n_cand += 1
            chk.finding("historical_query_candidate", "Info", {**ent, "ad_group_id": key[0], "query": m["query"]},
                        f"'{m['query']}' drew {clicks:g} clicks and {conv:g} conversions in prior event windows of "
                        f"campaign {e['campaign_id']} (CVR {cvr:.4f})",
                        evidence=ev,
                        calculation={"cvr": "conversions / clicks (pooled prior windows)",
                                     "cpa_roas_gate": f"conversions >= min_conversions {min_conv.value}"},
                        recommendation="Route to skill-013 as a request with campaign/ad-group/match-type scope and "
                                       "intended value; confirm the offer still applies.",
                        uncertainty="Observational; historical outcomes are not a forecast. Goal comparability of the "
                                    "history rows is not declared in the query report.")
        out[(e["event_id"], e["campaign_id"])] = relevant
        chk.observe(f"Event {e['event_id']} campaign {e['campaign_id']}: prior-window query history",
                    **ent, windows=[f"{a}..{b}" for a, b in windows], alignment=method, rows=stats["rows"],
                    queries=len(agg), relevant=len(relevant), candidates=n_cand, obsolete_year=n_obsolete)
    return out


def _coverage(ctx, chk, events, search_events, relevant, hist_c) -> None:
    if not chk.runnable:
        return
    if not hist_c.runnable or not relevant:
        chk.partial("no relevant historical queries available from step 2")
        return
    scopes, gaps = effective_negatives(ctx)
    for g in gaps:
        chk.partial(g)
    kws = sorted((k for k in ctx.rows("keywords") if _s(k.get("status")).upper() not in _INACTIVE),
                 key=lambda k: _s(k.get("id")))
    served: dict = {}
    for st in ctx.rows("search_terms"):
        k = (_s(st.get("campaign_id")), V.norm_text(st.get("search_term")))
        served[k] = (served.get(k) or 0) + (V.num(st.get("clicks")) or 0)
    by_event = {(e["event_id"], e["campaign_id"]): e for e in search_events}
    undecided = 0
    for ek in sorted(relevant):
        e = by_event[ek]
        cid = e["campaign_id"]
        for key in sorted(relevant[ek]):
            m = relevant[ek][key]
            gid, q = key
            group_scopes = [(cid, gid)] if (cid, gid) in scopes else sorted(k for k in scopes if k[0] == cid)
            blocked_by, n_blocked = [], 0
            for sk in group_scopes:
                hits = []
                for neg in scopes[sk]:
                    h = blocks(neg.text, neg.match, q)
                    if h is None:
                        undecided += 1
                    elif h:
                        hits.append(f"{neg.text} ({neg.match}, {neg.ref})")
                if hits:
                    n_blocked += 1
                    blocked_by.extend(h for h in hits if h not in blocked_by)
            literal = [_s(k.get("id")) for k in kws if _s(k.get("campaign_id")) == cid
                       and blocks(k.get("text"), k.get("match_type"), q) is True]
            served_clicks = served.get((cid, q))
            status = ("no_scope" if not group_scopes else "blocked" if n_blocked == len(group_scopes)
                      else "partially_blocked" if n_blocked else "not_blocked")
            ent = {**_event_entity(e), "ad_group_id": gid, "query": m["query"]}
            row = {"negative_status": status, "blocking_negatives": blocked_by,
                   "scopes_evaluated": [f"{a}/{b}" for a, b in group_scopes],
                   "literal_keyword_ids": literal, "current_served_clicks": served_clicks,
                   "historical": m["evidence"], "approved_event": e["approved"]}
            chk.observe(f"Coverage matrix: '{m['query']}' in campaign {cid}", **ent,
                        negative_status=status, literal_keyword_ids=literal, current_served_clicks=served_clicks)
            if status == "blocked":
                prov = chk.finding("event_query_negative_conflict", "Info", ent,
                                   f"Historical event query '{m['query']}' is literally blocked by "
                                   f"{', '.join(blocked_by)} in campaign {cid}",
                                   evidence=row,
                                   recommendation="Confirm whether the query is desired event traffic before "
                                                  "narrowing the negative (skill-017).",
                                   uncertainty="Literal negative semantics; relevance is not decided by the script.")
                chk.review("event_query_negative_conflict", ent,
                           f"Is '{m['query']}' relevant desired traffic for event {e['event_id']} "
                           f"({_s(e['raw'].get('offer')) or 'offer unknown'}) in campaign {cid}, or is the "
                           "negative an intentional exclusion?",
                           evidence={**row, "offer": e["raw"].get("offer"), "objective": e["raw"].get("objective"),
                                     "excluded_intents": ctx.profile.get("excluded_intents")},
                           outcomes={
                               "relevant_blocked": {"severity": "Warning" if e["approved"] else "Info",
                                                    "recommendation": "Request narrowing of the blocking negative "
                                                                      "(skill-017) before the approved launch."},
                               "intentional_exclusion": {"severity": None, "recommendation": "Keep; document routing."},
                               "uncertain": {"severity": "Info", "recommendation": "Ask the event owner."},
                           },
                           guidance="Judge only against the approved offer, profile objectives and excluded intents. "
                                    "Warning is available only for an approved event.",
                           provisional=prov)
            elif status == "not_blocked" and m["candidate"] and not literal and not served_clicks:
                chk.finding("coverage_unverified", "Info", ent,
                            f"Candidate '{m['query']}' has no literal keyword containment and no current served row "
                            f"in campaign {cid}; current reach is unverified",
                            evidence=row,
                            recommendation="Check eligibility with a query diagnosis before proposing a keyword "
                                           "(skill-013); broad/close-variant reach may already exist.",
                            uncertainty="Query reporting is privacy-limited; absence of a served row is not proof "
                                        "of missing coverage.")
    if undecided:
        chk.partial(f"{undecided} query/negative pairs beyond literal rules (operators or >16 words)")


def _readiness(ctx, chk, search_events) -> None:
    if not chk.runnable:
        return
    ads_t = ctx.table("ads")
    ad_missing = ["ads (file)"] if ads_t is None else [f"ads:{c}" for c in ads_t.missing(["id", "status",
                                                                                              "approval_status"])]
    if ad_missing:
        chk.partial("draft ad references cannot be resolved against the ads inventory", ad_missing)
    ads = {} if ad_missing else {_s(a.get("id")): a for a in ads_t.rows}
    for e in (x for x in search_events if x["approved"] and _upcoming(ctx, x)):
        r, ent = e["raw"], _event_entity(e)
        refs = V.split_list(r.get("draft_copy_ref"), (";", "|", ","))
        for ref in refs:
            ad = ads.get(ref)
            if ad is None:
                chk.observe(f"Event {e['event_id']}: draft ref '{ref}' is external; content not inspected", **ent)
                continue
            status, appr = _s(ad.get("status")).upper(), _s(ad.get("approval_status")).upper()
            if status in ("REMOVED", "DELETED") or appr == "DISAPPROVED":
                chk.finding("draft_ad_unavailable", "Warning", {**ent, "ad_id": ref},
                            f"Approved event {e['event_id']} relies on ad {ref}, which is {status}/{appr}",
                            evidence={"ad_id": ref, "status": status, "approval_status": appr,
                                      "policy_topics": ad.get("policy_topics"),
                                      "planned_launch_at": r.get("planned_launch_at")},
                            recommendation="Request a compliant replacement draft (skill-130 schedule) before launch.",
                            uncertainty="Ad snapshot at export time; appeals or edits after the snapshot are unseen.",
                            owner=_s(r.get("owner")) or None)
        missing = [c for c in ("draft_copy_ref", "landing_page_ref") if not _s(r.get(c))]
        if not missing:
            continue
        launch = V.parse_date(r.get("planned_launch_at"))
        ev = {"missing_refs": missing, "planned_launch_at": r.get("planned_launch_at"),
              "days_from_as_of_to_launch": (launch - ctx.as_of).days if launch else None,
              "start_at": r.get("start_at"), "offer": r.get("offer"),
              "stock_or_capacity": r.get("stock_or_capacity"), "owner": r.get("owner")}
        prov = chk.finding("launch_content_readiness", "Info", ent,
                           f"Approved event {e['event_id']} has no {' / '.join(missing)} in the plan",
                           evidence=ev, recommendation="Attach the actual draft copy and landing page references.",
                           uncertainty="The content may exist outside the supplied plan.",
                           owner=_s(r.get("owner")) or None)
        chk.review("launch_content_readiness", ent,
                   f"Is required ad/page content unavailable for approved event {e['event_id']} "
                   f"(missing {', '.join(missing)})?",
                   evidence=ev,
                   outcomes={"required_content_unavailable": {"severity": "Warning", "recommendation":
                                                              "Hold the launch request until content is approved."},
                             "content_available_elsewhere": {"severity": None, "recommendation":
                                                             "Record the reference in the plan."},
                             "uncertain": {"severity": "Info", "recommendation": "Ask the event owner."}},
                   guidance="Use only supplied plan/profile evidence. Do not apply a fixed lead time.",
                   provisional=prov)


def _timing(ctx, chk, search_events) -> None:
    if not chk.runnable:
        return
    for e in search_events:
        r, ent = e["raw"], _event_entity(e)
        launch, pause = V.parse_date(r.get("planned_launch_at")), V.parse_date(r.get("planned_pause_at"))
        issues = []
        if launch is None:
            issues.append(("launch_timing_undefined", "planned_launch_at missing or not a date"))
        if launch and e["start"] and launch > e["start"]:
            issues.append(("launch_after_event_start", f"planned_launch_at {launch} after start_at {e['start']}"))
        if launch and pause and pause < launch:
            issues.append(("pause_before_launch", f"planned_pause_at {pause} before planned_launch_at {launch}"))
        if launch and launch <= ctx.as_of and not e["approved"]:
            issues.append(("launch_date_reached_unapproved",
                           f"planned_launch_at {launch} reached by {ctx.as_of} without approval "
                           f"(status {r.get('approval_status')})"))
        ev = {"planned_launch_at": r.get("planned_launch_at"), "planned_pause_at": r.get("planned_pause_at"),
              "start_at": r.get("start_at"), "end_at": r.get("end_at"), "approval_status": r.get("approval_status"),
              "approval_dependencies": r.get("approval_dependencies"), "stock_or_capacity": r.get("stock_or_capacity"),
              "as_of": ctx.as_of}
        for key, text in issues:
            chk.finding(key, "Info", ent, f"Event {e['event_id']}: {text}", evidence=ev,
                        recommendation="Set launch/pause from approvals, stock and measured account latency; "
                                       "no universal lead time applies.",
                        uncertainty="Calendar consistency only.", owner=_s(r.get("owner")) or None)
        chk.observe(f"Event {e['event_id']} launch timing", **ent,
                    days_to_launch=(launch - ctx.as_of).days if launch else None,
                    dependencies=V.split_list(r.get("approval_dependencies"), (";", "|")))


def _routing(ctx, chk, search_events, relevant) -> None:
    for e in search_events:
        rel = relevant.get((e["event_id"], e["campaign_id"]), {})
        cands = sorted(m["query"] for m in rel.values() if m["candidate"])
        chk.observe(f"Event {e['event_id']} routing", **_event_entity(e), approved=e["approved"],
                    skill_013_candidates=cands,
                    skill_130_schedule=bool(e["approved"] and V.parse_date(e["raw"].get("planned_launch_at"))))


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
