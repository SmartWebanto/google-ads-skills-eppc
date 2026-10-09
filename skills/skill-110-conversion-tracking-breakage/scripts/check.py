"""check.py — skill-110 deterministic lag-aware conversion anomaly screening and incident confirmation.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-110-conversion-tracking-breakage/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Series grain = campaign_id/action_id/device/channel from custom/tracking_daily; one date_basis per
         series (mixed → series excluded). A missing (series, date) row is UNKNOWN unless the manifest marks the
         table complete and untruncated; only then dates inside the manifest/table extent are true zeros.
         Per-series maturity cutoff = min(period_end, table extent end, snapshot - max(lag_eff, 1) days) with
         lag_eff = max(account/profile lag, ceil(max context expected_reporting_lag_hours / 24)); a date counts
         only when <= cutoff AND its row has reporting_mature=true (manifest zero-filled dates excepted).
         Unknown lag or snapshot → no cutoff → no screening (Info), never an assumed zero lag.
         Baseline: last 7 mature days vs the preceding 4 full weeks (same weekdays, pro-rated); a series failing
         sample gates retries 14 days vs the preceding 8 weeks. Every date in both windows must be known+mature.
         Gates on both sides: min_conversions on baseline conversions; min_clicks on recent AND baseline clicks.
         Traffic is looked up once per campaign/date/device/channel key — never summed per action row.
         >50% conversion drop on gated mature data = Warning screening heuristic, not a fault verdict.
         Causality (fault vs business/reporting) is ai_review; 'explained' needs proposal.evidence_ref naming a
         supplied context source_reference or incident ref. Missing controls → Info, never implied stable demand.
         Confirmed incident = status 'confirmed' + evidence_reference + fault_start → Warning. Critical only via
         review when the incident row carries material_impact_evidence and proposal.evidence_ref cites that row.
         Non-hour timestamp precision supports affected dates only (Info). Confirmed incidents are routed to
         skill-111 as observations; this script never proposes exclusions, tag or upload changes.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import math
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

SKILL = "skill-110-conversion-tracking-breakage"
VERSION = "1.0.0"

DAILY = "custom/tracking_daily"
TRAFFIC = "custom/tracking_traffic_daily"
CONTEXT = "external/tracking_context"
INCIDENTS = "external/tracking_incidents"
DAILY_COLS = ["account_id", "campaign_id", "action_id", "date", "date_basis", "device", "channel",
              "conversions", "conversion_value", "all_conversions", "reporting_mature", "currency"]
TRAFFIC_COLS = ["account_id", "campaign_id", "date", "device", "channel", "impressions", "clicks", "cost", "currency"]
CONTROLS = ["business_outcomes", "eligible_sessions", "expected_weekday_pattern", "promotion_status",
            "site_availability", "deployment_id", "budget_or_goal_change", "consent_change"]
CONTEXT_COLS = ["account_id", "campaign_id", "action_id", "date", *CONTROLS, "expected_reporting_lag_hours",
                "source_reference"]
INCIDENT_CORE = ["incident_id", "account_id", "campaign_id", "action_id", "device", "channel",
                 "status_suspected_or_confirmed", "fault_start", "evidence_reference"]
INCIDENT_COLS = INCIDENT_CORE + ["detected_at", "fault_end", "timezone", "timestamp_precision", "fault_type",
                                 "expected_behavior", "observed_behavior", "material_impact_evidence", "owner"]
RECOVERY_COLS = INCIDENT_CORE + ["recovery_verified_at", "backfill_status"]
WINDOWS = ((7, 4), (14, 8))  # (recent days, baseline weeks): like weekdays by construction
DROP_SCREEN = 0.5
EXACT_PRECISION = {"hour", "minute", "second", "millisecond", "timestamp"}
SETTLED_BACKFILL = {"complete", "completed", "not_needed", "not needed", "none_needed", "not_applicable"}

STEPS = (("action_series", "Per-action campaign/device/channel series with date basis"),
         ("maturity_cutoff", "Exclude incomplete days and immature cohorts"),
         ("like_for_like_baseline", "Mature like-weekday baseline with traffic and context controls"),
         ("drop_screen", "Gated >50% mature conversion drop screen"),
         ("click_conversion_divergence", "Clicks versus conversions divergence"),
         ("cause_attribution", "Fault versus business/reporting explanation"),
         ("incident_confirmation", "Independent incident confirmation and timestamp precision"),
         ("recovery_verification", "Recovery and backfill state"),
         ("route_to_111", "Route confirmed incidents to skill-111"))


def _id(v) -> str:
    return "" if v is None else str(v).strip()


def _acct(v) -> str:
    return _id(v).replace("-", "")


def _seg(v) -> str:
    return V.norm_text(v)


class _Grid:
    """Daily rows by (key, date). Rules: duplicate (key, date) rows conflict → that cell is unknown."""

    def __init__(self, ctx, table, keyfn):
        self.cells: dict = {}
        self.rows_by_key: dict = {}
        self.conflicts: set = set()
        self.bad_dates = self.foreign = 0
        own = _acct(ctx.account_id)
        dates = []
        for r in table.rows:
            if own and r.get("account_id") is not None and _acct(r.get("account_id")) != own:
                self.foreign += 1
                continue
            d = V.parse_date(r.get("date"))
            if d is None:
                self.bad_dates += 1
                continue
            k = keyfn(r)
            dates.append(d)
            self.rows_by_key.setdefault(k, []).append(r)
            cell = self.cells.setdefault(k, {})
            if d in cell:
                self.conflicts.add((k, d))
            else:
                cell[d] = r
        man = table.manifest or {}
        self.start = V.parse_date(man.get("period_start")) or min(dates, default=None)
        self.end = V.parse_date(man.get("period_end")) or max(dates, default=None)
        self.complete = table.complete is True and not table.truncated

    def get(self, k, d):
        """→ ('row', row) | ('zero', None) | ('unknown', reason)."""
        if (k, d) in self.conflicts:
            return "unknown", "duplicate rows"
        r = self.cells.get(k, {}).get(d)
        if r is not None:
            return "row", r
        if self.complete and self.start and self.end and self.start <= d <= self.end:
            return "zero", None
        return "unknown", "no row (table not manifest-complete)" if not self.complete else "outside extent"

    def notes(self, name: str) -> list[str]:
        out = []
        if self.conflicts:
            out.append(f"{name}: {len(self.conflicts)} duplicate key/date cells treated as unknown")
        if self.bad_dates:
            out.append(f"{name}: {self.bad_dates} rows with unparseable date ignored")
        if self.foreign:
            out.append(f"{name}: {self.foreign} rows for another account_id excluded")
        return out


class _Context:
    """external/tracking_context picked per series/date at the most specific grain present."""

    def __init__(self, ctx, table):
        self.by: dict = {}
        own = _acct(ctx.account_id)
        for r in table.rows:
            if own and r.get("account_id") is not None and _acct(r.get("account_id")) != own:
                continue
            d = V.parse_date(r.get("date"))
            if d is not None:
                self.by.setdefault((_id(r.get("campaign_id")), _id(r.get("action_id")), d), []).append(r)
        self.lag_hours: dict = {}
        for (cid, aid, _d), rows in self.by.items():
            for r in rows:
                h = V.num(r.get("expected_reporting_lag_hours"))
                if h is not None and h >= 0:
                    self.lag_hours[(cid, aid)] = max(h, self.lag_hours.get((cid, aid), 0.0))

    def pick(self, cid, aid, d):
        for k in ((cid, aid, d), (cid, "", d), ("", aid, d), ("", "", d)):
            rows = self.by.get(k)
            if rows:
                return (rows[0], False) if len(rows) == 1 else (None, True)
        return None, False

    def max_lag_hours(self, cid, aid):
        vals = [self.lag_hours[k] for k in ((cid, aid), (cid, ""), ("", aid), ("", "")) if k in self.lag_hours]
        return max(vals) if vals else None


def _windows(cut, recent_days, weeks):
    recent = [cut - timedelta(days=i) for i in range(recent_days - 1, -1, -1)]
    b_end = recent[0] - timedelta(days=1)
    base = [b_end - timedelta(days=i) for i in range(7 * weeks - 1, -1, -1)]
    return recent, base


def _sum_known(vals):
    return None if any(v is None for v in vals) else sum(vals)


def run(ctx) -> None:
    """Run series build, maturity cutoff, like-for-like baseline, drop screen, cause review and incident checks.

    Rules:   Unknown lag/snapshot → Info 'maturity_undetermined', no screening; unknown dates are never zeros. > 50%
             drop on mature, gated data (min_conversions baseline, min_clicks both sides) → Warning screen only. Cause
             is ai_review ('explained' needs evidence_ref); confirmed incidents → Warning; Critical only via review
             citing material_impact_evidence. Missing controls/precision limits are Info; never proposes tag or upload
             changes.
    """
    s1 = ctx.check("action_series", STEPS[0][1], {DAILY: DAILY_COLS})
    state = None
    if not s1.runnable:
        traffic = ctx.table(TRAFFIC)
        tmiss = [f"{TRAFFIC} (file)"] if traffic is None else [f"{TRAFFIC}:{c}" for c in traffic.missing(TRAFFIC_COLS)]
        for cid, title in STEPS[1:6]:
            ctx.check(cid, title).skip("tracking daily series unavailable",
                                       s1.missing + (tmiss if cid == "click_conversion_divergence" else []))
    else:
        state = _series(ctx, s1)
        _screen(ctx, state)
    _incidents(ctx, state)


# ---------------------------------------------------------------------------------------------- steps 1-6
def _series(ctx, chk) -> dict:
    daily = ctx.table(DAILY)
    grid = _Grid(ctx, daily, lambda r: (_id(r.get("campaign_id")), _id(r.get("action_id")),
                                        _seg(r.get("device")), _seg(r.get("channel"))))
    for n in grid.notes(DAILY):
        chk.partial(n)
    if not grid.complete:
        chk.partial(f"{daily.filename}: not manifest-complete; missing dates stay unknown, not zero")
    actions = {_id(a.get("id")): a for a in ctx.rows("conversion_actions")}
    if ctx.table("conversion_actions") is None:
        chk.partial("conversion action configuration unavailable", ["conversion_actions (file)"])
    acct_basis = _seg(ctx.account.get("conversion_date_basis")) or None
    series, excluded = {}, []
    for key in sorted(grid.rows_by_key):
        rows = grid.rows_by_key[key]
        bases = sorted({_seg(r.get("date_basis")) or "unknown" for r in rows})
        cid, aid, dev, ch = key
        if len(bases) != 1 or bases[0] == "unknown":
            excluded.append({"campaign_id": cid, "action_id": aid, "device": dev, "channel": ch, "date_basis": bases})
            continue
        a = actions.get(aid)
        meta = {k: a.get(k) for k in ("name", "status", "category", "include_in_conversions", "primary_for_goal")} \
            if a else None
        dates = sorted(V.parse_date(r.get("date")) for r in rows)
        series[key] = {"date_basis": bases[0], "action": meta}
        chk.observe(f"Series {cid}/{aid}/{dev}/{ch}", campaign_id=cid, action_id=aid, device=dev, channel=ch,
                    date_basis=bases[0], account_date_basis=acct_basis, rows=len(rows), first=dates[0],
                    last=dates[-1], conversions_known=sum(V.num(r.get("conversions")) or 0 for r in rows),
                    rows_unknown_conversions=sum(1 for r in rows if V.num(r.get("conversions")) is None),
                    action_config=meta)
    if excluded:
        chk.partial(f"{len(excluded)} series with mixed/unknown date_basis excluded")
        chk.observe("Series excluded for date basis", series=excluded)
    unknown_actions = sorted({k[1] for k in series if actions and k[1] not in actions})
    if unknown_actions:
        chk.partial(f"action ids absent from conversion_actions: {unknown_actions}")
    chk.observe("Series inventory", series=len(series), excluded=len(excluded), manifest_complete=grid.complete,
                extent=[grid.start, grid.end])
    return {"grid": grid, "series": series, "cutoffs": {}}


def _screen(ctx, state) -> None:
    grid, series = state["grid"], state["series"]
    ctab = ctx.table(CONTEXT)
    cmiss = [] if ctab is not None else [f"{CONTEXT} (file)"]
    if ctab is not None:
        cmiss = [f"{CONTEXT}:{c}" for c in ctab.missing(CONTEXT_COLS)]
    cgrid = _Context(ctx, ctab) if ctab is not None and not cmiss else None
    ttab = ctx.table(TRAFFIC)
    tmiss = [f"{TRAFFIC} (file)"] if ttab is None else [f"{TRAFFIC}:{c}" for c in ttab.missing(TRAFFIC_COLS)]
    tgrid = _Grid(ctx, ttab, lambda r: (_id(r.get("campaign_id")), _seg(r.get("device")), _seg(r.get("channel")))) \
        if ttab is not None and not tmiss else None

    # -- step 2: maturity cutoff
    m = ctx.check("maturity_cutoff", STEPS[1][1], {DAILY: DAILY_COLS})
    if ctx.lag_days is None or ctx.snapshot is None:
        why = "conversion lag unknown" if ctx.lag_days is None else "snapshot date unknown"
        m.partial(f"{why}: no maturity cutoff; screening disabled")
        m.finding("maturity_undetermined", "Info", {"table": DAILY},
                  f"Tracking series cannot be screened: {why}",
                  evidence={"lag_days": ctx.lag_days, "snapshot": ctx.snapshot, "period_end": ctx.period_end},
                  recommendation="Supply account/profile conversion_lag_days and snapshot_date, then re-run.",
                  uncertainty="Without a lag model today's partial conversions could be compared with mature days.")
    else:
        if cgrid is None:
            m.partial("reporting-lag controls unavailable: account lag only", cmiss)
        excluded_rows = immature_rows = 0
        for key in sorted(series):
            cid, aid = key[0], key[1]
            hours = cgrid.max_lag_hours(cid, aid) if cgrid else None
            lag_eff = max(ctx.lag_days, math.ceil(hours / 24) if hours is not None else 0)
            cut = ctx.snapshot - timedelta(days=max(lag_eff, 1))
            for bound in (ctx.period_end, grid.end):
                if bound is not None:
                    cut = min(cut, bound)
            state["cutoffs"][key] = cut
            series[key]["lag"] = {"lag_days_effective": lag_eff, "account_lag_days": ctx.lag_days,
                                  "context_lag_hours": hours, "cutoff": cut}
            for r in grid.rows_by_key[key]:
                d = V.parse_date(r.get("date"))
                if d > cut:
                    excluded_rows += 1
                elif V.boolean(r.get("reporting_mature")) is not True:
                    immature_rows += 1
        m.observe("Maturity cutoff applied", snapshot=ctx.snapshot, period_end=ctx.period_end,
                  account_lag_days=ctx.lag_days, account_mature=ctx.mature,
                  cutoffs=sorted({str(c) for c in state["cutoffs"].values()}),
                  rows_after_cutoff=excluded_rows, rows_before_cutoff_not_reporting_mature=immature_rows)

    # -- step 3: like-for-like baseline
    b = ctx.check("like_for_like_baseline", STEPS[2][1], {DAILY: DAILY_COLS})
    minc, mink = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
    if tgrid is None:
        b.partial("traffic unavailable: click samples, traffic mix and conversion rates unknown", tmiss)
    else:
        for n in tgrid.notes(TRAFFIC):
            b.partial(n)
    if cgrid is None:
        b.partial("contextual controls unavailable: demand, promotions, consent, site and deployments unknown", cmiss)
    for p in (minc, mink):
        if p.value is None:
            b.partial(f"{p.name} unresolved: {p.reason}")
    params = {"min_conversions": minc.value, "min_conversions_source": minc.source,
              "min_clicks": mink.value, "min_clicks_source": mink.source, "drop_screen": DROP_SCREEN}
    measures = {}
    if not state["cutoffs"]:
        b.partial("no maturity cutoff: baseline not built")
    for key in sorted(state["cutoffs"]):
        meas = None
        for rd, wk in WINDOWS:
            cand = _measure(ctx, grid, tgrid, cgrid, key, state["cutoffs"][key], rd, wk)
            if meas is None or (cand["status"] == "complete" and _gates(cand, minc.value, mink.value)):
                meas = cand
            if cand["status"] != "complete" or _gates(cand, minc.value, mink.value):
                break
        measures[key] = meas
        cid, aid, dev, ch = key
        b.observe(f"Baseline {cid}/{aid}/{dev}/{ch}", campaign_id=cid, action_id=aid, device=dev, channel=ch,
                  **{k: v for k, v in meas.items() if k != "controls"})
    state["measures"], state["params"] = measures, params

    # -- step 4: drop screen
    s4 = ctx.check("drop_screen", STEPS[3][1], {DAILY: DAILY_COLS})
    if not measures:
        s4.partial("no mature comparable series")
    if tgrid is None:
        s4.partial("click sample gates cannot be applied: traffic unavailable", tmiss)
    screened, counts = {}, {"screened": 0, "no_trigger": 0, "insufficient": 0}
    for key in sorted(measures):
        meas = measures[key]
        ent = _entity(key)
        ev = {**_ev(series[key], meas), **params}
        if meas["status"] != "complete":
            reason = f"incomplete/immature window ({meas['gap_count']} unknown dates)"
        elif minc.value is None or mink.value is None:
            reason = "sample parameters unresolved"
        elif meas["clicks_recent"] is None or meas["clicks_baseline"] is None:
            reason = "clicks unknown: traffic sample gate not applicable"
        elif not _gates(meas, minc.value, mink.value):
            reason = "sample gates not met on both sides"
        else:
            reason = None
        if reason:
            counts["insufficient"] += 1
            s4.finding("insufficient_series_evidence", "Info", ent,
                       f"Series {'/'.join(key)} not screened: {reason}", evidence=ev,
                       recommendation="Use longer mature windows or a coarser aggregation before judging this action.",
                       uncertainty="Sparse, immature or incomplete data cannot support or rule out a tracking fault.")
            continue
        drop = None if meas["conversion_ratio"] is None else 1 - meas["conversion_ratio"]
        if drop is not None and drop > DROP_SCREEN:
            counts["screened"] += 1
            screened[key] = s4.finding(
                "mature_conversion_drop_screen", "Warning", ent,
                f"Series {'/'.join(key)}: {meas['conversions_recent']:g} mature conversions vs "
                f"{meas['expected_recent']:g} expected from the like-weekday baseline ({drop:.0%} drop)",
                evidence={**ev, "drop": drop},
                calculation={"drop": "1 - conversions_recent / (conversions_baseline * recent_days / baseline_days)"},
                recommendation="Screening heuristic only: check tag traces, upload errors, deployments and business "
                               "outcomes before calling it a fault; do not exclude data or change bidding yet.",
                uncertainty="A >50% drop is triage, not a fault verdict; demand, promotions, consent and reporting "
                            "delay can explain it. Modeled-conversion inclusion is not recorded in this export.")
        else:
            counts["no_trigger"] += 1
    s4.observe("Drop screen totals", **counts, **params)
    state["screened"] = screened

    # -- step 5: click/conversion divergence
    s5 = ctx.check("click_conversion_divergence", STEPS[4][1],
                                                           {DAILY: DAILY_COLS, TRAFFIC: TRAFFIC_COLS})
    divergent = []
    if s5.runnable:
        for key in sorted(measures):
            meas = measures[key]
            if meas["status"] != "complete" or not _gates(meas, minc.value, mink.value):
                continue
            s5.observe(f"Click-normalized comparison {'/'.join(key)}", **_entity(key),
                       click_ratio=meas["click_ratio"], conversion_ratio=meas["conversion_ratio"],
                       cvr_recent=meas["cvr_recent"], cvr_baseline=meas["cvr_baseline"], cvr_ratio=meas["cvr_ratio"])
            if key not in screened and meas["cvr_ratio"] is not None and meas["cvr_ratio"] < 1 - DROP_SCREEN:
                divergent.append(key)
        s5.observe("Divergent series (conversion rate fell >50% with gated clicks)", count=len(divergent),
                   series=["/".join(k) for k in divergent])

    # -- step 6: cause attribution
    s6 = ctx.check("cause_attribution", STEPS[5][1], {DAILY: DAILY_COLS})
    if cgrid is None:
        s6.partial("contextual controls unavailable: lower confidence", cmiss)
    itab = ctx.table(INCIDENTS)
    incidents = [r for r in (itab.rows if itab is not None else [])]
    anomalies = sorted(set(screened) | set(divergent))
    for key in anomalies:
        meas = measures[key]
        ent = _entity(key)
        ctrl = meas.get("controls") or {}
        missing = ctrl.get("missing_controls", CONTROLS)
        refs = sorted(set(ctrl.get("source_references", [])))
        scope_inc = [_incident_brief(r) for r in sorted(incidents, key=lambda r: _id(r.get("incident_id")))
                     if _in_scope(r, key)]
        refs = sorted(set(refs) | {x for r in scope_inc for x in (r["incident_id"], r["evidence_reference"]) if x})
        tracking_ok, tracking_note = ctx.tracking_for_campaign(key[0])
        ev = {**_ev(series[key], meas), **params, "controls": ctrl, "missing_controls": missing,
              "incidents_in_scope": scope_inc, "evidence_refs": refs, "goal_tracking_note": tracking_note,
              "anomaly_type": "conversion_drop_screen" if key in screened else "conversion_rate_divergence"}
        if missing:
            s6.finding("missing_contextual_controls", "Info", ent,
                       f"Series {'/'.join(key)}: controls {missing} unavailable for the compared windows",
                       evidence={"missing_controls": missing, "window": meas["window"]},
                       recommendation="Supply aggregate CRM/site, promotion, consent and deployment records for the "
                                      "same dates to separate demand changes from measurement faults.",
                       uncertainty="Missing controls lower confidence; they do not imply stable demand.")
        outcomes = {
            "measurement_fault_suspected": {"severity": "Warning", "recommendation":
                                            "Open a tracking investigation (tag traces, upload errors, deployments) "
                                            "with the owner; confirm before any data exclusion."},
            "business_or_reporting_explained": {"severity": None, "recommendation":
                                                "No tracking action; document the cited explanation."},
            "uncertain": {"severity": "Warning" if key in screened else "Info", "recommendation":
                          "Keep as unconfirmed anomaly; request the missing controls and re-screen when mature."},
        }
        s6.review("anomaly_cause", ent,
                  f"Series {'/'.join(key)}: is the mature conversion anomaly a suspected measurement fault, or is it "
                  "explained by business demand, promotions, consent, goal/budget changes or reporting delay?",
                  evidence=ev, outcomes=outcomes, provisional=screened.get(key),
                  guidance="Stable clicks with fewer conversions is an anomaly, not a diagnosis. Use only the supplied "
                           "controls, incidents and action configuration. 'business_or_reporting_explained' requires "
                           "proposal.evidence_ref equal to one of evidence.evidence_refs. Missing controls → uncertain.")
    s6.observe("Anomalies sent to cause review", count=len(anomalies))


def _gates(meas, minc, mink) -> bool:
    if meas["status"] != "complete" or minc is None or mink is None:
        return False
    cr, cb = meas["clicks_recent"], meas["clicks_baseline"]
    return (meas["conversions_baseline"] >= minc and cr is not None and cb is not None
            and cr >= mink and cb >= mink)


def _measure(ctx, grid, tgrid, cgrid, key, cut, rd, wk) -> dict:
    recent, base = _windows(cut, rd, wk)
    window = {"recent": [recent[0], recent[-1]], "baseline": [base[0], base[-1]], "recent_days": rd,
              "baseline_weeks": wk, "cutoff": cut}
    gaps, agg = [], {}
    for label, dates in (("recent", recent), ("baseline", base)):
        conv, allc, val = [], [], []
        for d in dates:
            kind, r = grid.get(key, d)
            if kind == "unknown":
                gaps.append(f"{d}: {r}")
                continue
            if kind == "zero":
                conv, allc, val = conv + [0.0], allc + [0.0], val + [0.0]
                continue
            if V.boolean(r.get("reporting_mature")) is not True:
                gaps.append(f"{d}: reporting_mature not true")
                continue
            c = V.num(r.get("conversions"))
            if c is None:
                gaps.append(f"{d}: conversions unknown")
                continue
            conv.append(c)
            allc.append(V.num(r.get("all_conversions")))
            cur = _seg(r.get("currency")).upper() or None
            val.append(ctx.money(r.get("conversion_value")) if cur in (None, ctx.currency) else None)
        agg[label] = (_sum_known(conv), _sum_known(allc), _sum_known(val))
    if gaps:
        return {"status": "incomplete", "window": window, "gap_count": len(gaps), "gaps": gaps[:10]}
    traffic = {}
    for label, dates in (("recent", recent), ("baseline", base)):
        clicks, impr, cost = [], [], []
        for d in dates:
            if tgrid is None:
                clicks, impr, cost = clicks + [None], impr + [None], cost + [None]
                continue
            kind, r = tgrid.get((key[0], key[2], key[3]), d)
            if kind == "zero":
                clicks, impr, cost = clicks + [0.0], impr + [0.0], cost + [0.0]
            elif kind == "row":
                clicks.append(V.num(r.get("clicks")))
                impr.append(V.num(r.get("impressions")))
                cur = _seg(r.get("currency")).upper() or None
                cost.append(ctx.money(r.get("cost")) if cur in (None, ctx.currency) else None)
            else:
                clicks, impr, cost = clicks + [None], impr + [None], cost + [None]
        traffic[label] = (_sum_known(clicks), _sum_known(impr), _sum_known(cost))
    scale = rd / (7 * wk)
    cr, cb = agg["recent"][0], agg["baseline"][0]
    kr, kb = traffic["recent"][0], traffic["baseline"][0]
    expected = cb * scale
    cvr_r, cvr_b = V.ratio(cr, kr), V.ratio(cb, kb)
    return {
        "status": "complete", "window": window, "gap_count": 0,
        "conversions_recent": cr, "conversions_baseline": cb, "expected_recent": expected,
        "conversion_ratio": V.ratio(cr, expected),
        "all_conversions_recent": agg["recent"][1], "all_conversions_baseline": agg["baseline"][1],
        "all_conversions_ratio": V.ratio(agg["recent"][1], None if agg["baseline"][1] is None
                                         else agg["baseline"][1] * scale),
        "conversion_value_recent": agg["recent"][2], "conversion_value_baseline": agg["baseline"][2],
        "clicks_recent": kr, "clicks_baseline": kb,
        "click_ratio": V.ratio(kr, None if kb is None else kb * scale),
        "impressions_recent": traffic["recent"][1], "impressions_baseline": traffic["baseline"][1],
        "cost_recent": traffic["recent"][2], "cost_baseline": traffic["baseline"][2],
        "cvr_recent": cvr_r, "cvr_baseline": cvr_b, "cvr_ratio": V.ratio(cvr_r, cvr_b),
        "controls": _controls(cgrid, key, recent, base, scale),
    }


def _controls(cgrid, key, recent, base, scale) -> dict:
    """Aggregate supplied controls per window. Rules: null = unavailable; conflicting rows → unknown date."""
    if cgrid is None:
        return {"available": False, "missing_controls": list(CONTROLS), "source_references": []}
    out = {"available": True, "source_references": set(), "conflict_dates": []}
    seen = {c: False for c in CONTROLS}
    for label, dates in (("recent", recent), ("baseline", base)):
        texts = {c: set() for c in CONTROLS[2:]}
        nums = {c: [] for c in CONTROLS[:2]}
        for d in dates:
            row, conflict = cgrid.pick(key[0], key[1], d)
            if conflict:
                out["conflict_dates"].append(d)
            for c in CONTROLS[:2]:
                nums[c].append(V.num(row.get(c)) if row else None)
            if row is None:
                continue
            if row.get("source_reference"):
                out["source_references"].add(_id(row.get("source_reference")))
            for c in CONTROLS[2:]:
                if row.get(c) is not None:
                    texts[c].add(_id(row.get(c)))
        for c, vals in nums.items():
            known = [v for v in vals if v is not None]
            seen[c] = seen[c] or bool(known)
            out[f"{c}_{label}"] = _sum_known(vals)
            out[f"{c}_{label}_known_days"] = len(known)
        for c, vals in texts.items():
            seen[c] = seen[c] or bool(vals)
            out[f"{c}_{label}"] = sorted(vals)
    for c in CONTROLS[:2]:
        rb = out[f"{c}_baseline"]
        out[f"{c}_ratio"] = V.ratio(out[f"{c}_recent"], None if rb is None else rb * scale)
    out["source_references"] = sorted(out["source_references"])
    out["missing_controls"] = [c for c in CONTROLS if not seen[c]]
    return out


def _entity(key) -> dict:
    return {"campaign_id": key[0], "action_id": key[1], "device": key[2], "channel": key[3]}


def _ev(info, meas) -> dict:
    return {"date_basis": info.get("date_basis"), "action_config": info.get("action"), "lag": info.get("lag"),
            **{k: v for k, v in meas.items() if k != "controls"}}


# ---------------------------------------------------------------------------------------------- steps 7-9
def _confirmed(r) -> bool:
    return (_seg(r.get("status_suspected_or_confirmed")) == "confirmed" and bool(_id(r.get("evidence_reference")))
            and V.parse_date(r.get("fault_start")) is not None)


def _in_scope(r, key) -> bool:
    for col, val in (("campaign_id", key[0]), ("action_id", key[1])):
        if _id(r.get(col)) and _id(r.get(col)) != val:
            return False
    for col, val in (("device", key[2]), ("channel", key[3])):
        if _seg(r.get(col)) and _seg(r.get(col)) != val:
            return False
    return True


def _incident_brief(r) -> dict:
    return {k: r.get(k) for k in ("incident_id", "status_suspected_or_confirmed", "fault_start", "fault_end",
                                  "timestamp_precision", "fault_type", "evidence_reference")}


def _scope_flow(state, r, start, end) -> dict:
    """Mature conversions of in-scope series between start and end (inclusive), cut at each series cutoff."""
    if not state or not state.get("cutoffs"):
        return {"series": 0, "mature_dates": 0, "unknown_dates": 0, "conversions": None}
    grid, n_series, mature, unknown, conv = state["grid"], 0, 0, 0, 0.0
    for key in sorted(state["cutoffs"]):
        if not _in_scope(r, key):
            continue
        n_series += 1
        cut = state["cutoffs"][key]
        d = start
        while d <= min(end, cut):
            kind, row = grid.get(key, d)
            c = 0.0 if kind == "zero" else V.num(row.get("conversions")) if kind == "row" and \
                V.boolean(row.get("reporting_mature")) is True else None
            if c is None:
                unknown += 1
            else:
                mature += 1
                conv += c
            d += timedelta(days=1)
    return {"series": n_series, "mature_dates": mature, "unknown_dates": unknown,
            "conversions": conv if mature else None}


def _incidents(ctx, state) -> None:
    s7 = ctx.check("incident_confirmation", STEPS[6][1], {INCIDENTS: INCIDENT_COLS})
    s8 = ctx.check("recovery_verification", STEPS[7][1], {INCIDENTS: RECOVERY_COLS})
    s9 = ctx.check("route_to_111", STEPS[8][1], {INCIDENTS: INCIDENT_CORE})
    rows = sorted(ctx.rows(INCIDENTS), key=lambda r: _id(r.get("incident_id")))
    own = _acct(ctx.account_id)
    rows = [r for r in rows if not (own and r.get("account_id") is not None and _acct(r.get("account_id")) != own)]
    no_series = state is None or not state.get("cutoffs")
    acct_tz = ctx.account.get("time_zone")

    if s7.runnable:
        if no_series:
            s7.partial("mature tracking series unavailable: affected-scope conversions not quantified",
                       [] if state is not None else [f"{DAILY} (file)"])
        n_conf = 0
        for r in rows:
            iid = _id(r.get("incident_id"))
            ent = {"incident_id": iid, "campaign_id": _id(r.get("campaign_id")) or None,
                   "action_id": _id(r.get("action_id")) or None, "device": _seg(r.get("device")) or None,
                   "channel": _seg(r.get("channel")) or None}
            status = _seg(r.get("status_suspected_or_confirmed"))
            if not _confirmed(r):
                if status == "confirmed":
                    s7.partial(f"incident {iid} marked confirmed without evidence_reference/fault_start: "
                               "treated as suspected")
                s7.observe(f"Incident {iid} not confirmed ({status or 'unknown status'})", **_incident_brief(r))
                continue
            n_conf += 1
            start = V.parse_date(r.get("fault_start"))
            end = V.parse_date(r.get("fault_end"))
            flow = _scope_flow(state, r, start, end or (ctx.period_end or start))
            precision = _seg(r.get("timestamp_precision"))
            tz = r.get("timezone")
            ev = {**_incident_brief(r), "detected_at": r.get("detected_at"), "timezone": tz, "account_time_zone": acct_tz,
                  "timezone_differs": bool(tz and acct_tz and tz != acct_tz), "expected_behavior": r.get("expected_behavior"),
                  "observed_behavior": r.get("observed_behavior"), "material_impact_evidence":
                  r.get("material_impact_evidence"), "owner": r.get("owner"), "affected_scope_flow": flow,
                  "fault_end_open": end is None}
            s7.finding("confirmed_tracking_fault", "Warning", ent,
                       f"Incident {iid}: confirmed {r.get('fault_type') or 'tracking'} fault from {start}"
                       f"{' to ' + str(end) if end else ' (no end recorded)'} ({r.get('evidence_reference')})",
                       evidence=ev, owner=_id(r.get("owner")) or None,
                       recommendation="Owner fixes and re-verifies the event flow; route to skill-111 for data "
                                      "exclusion applicability. No automatic exclusion or bidding change.",
                       uncertainty="Material impact is not established by confirmation alone.")
            if precision not in EXACT_PRECISION:
                s7.finding("timestamp_precision_limit", "Info", ent,
                           f"Incident {iid}: timestamp precision '{precision or 'unknown'}' supports affected dates "
                           "only; the exact silence duration is unknown",
                           evidence={"timestamp_precision": r.get("timestamp_precision"), "fault_start":
                                     r.get("fault_start"), "fault_end": r.get("fault_end"), "timezone": tz},
                           recommendation="Use timestamped tag/upload telemetry for exact start/stop times.",
                           uncertainty="Daily rows cannot prove a 24-hour or partial-day outage length.")
            if r.get("material_impact_evidence"):
                s7.review("material_tracking_failure", ent,
                          f"Incident {iid}: does the cited material_impact_evidence establish MATERIAL tracking "
                          "failure in the affected scope?",
                          evidence=ev,
                          outcomes={"material_failure_confirmed": {"severity": "Critical", "recommendation":
                                                                   "Prioritize the fix and skill-111 review; cite "
                                                                   "the impact evidence."},
                                    "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
                          guidance="Critical requires proposal.evidence_ref equal to this incident's "
                                   "material_impact_evidence or evidence_reference. Do not estimate lost revenue.")
            else:
                s7.observe(f"Incident {iid}: material impact not evidenced; Critical unavailable", incident_id=iid)
        s7.observe("Incident confirmation totals", incidents=len(rows), confirmed=n_conf)

    if s8.runnable:
        if no_series:
            s8.partial("mature tracking series unavailable: restored event flow not verifiable",
                       [] if state is not None else [f"{DAILY} (file)"])
        for r in rows:
            if not _confirmed(r):
                continue
            iid = _id(r.get("incident_id"))
            rec = V.parse_date(r.get("recovery_verified_at"))
            backfill = _seg(r.get("backfill_status")) or None
            late = backfill not in SETTLED_BACKFILL
            if rec is None:
                s8.observe(f"Incident {iid} remains open: recovery not verified", incident_id=iid,
                           backfill_status=backfill, backfill_may_change_incident=late)
                continue
            flow = _scope_flow(state, r, rec + timedelta(days=1), ctx.period_end or rec)
            if not no_series and flow["mature_dates"] == 0:
                s8.finding("recovery_not_yet_mature", "Info",
                           {"incident_id": iid, "campaign_id": _id(r.get("campaign_id")) or None,
                            "action_id": _id(r.get("action_id")) or None},
                           f"Incident {iid}: recovery verified at {rec} but no mature post-recovery reporting yet",
                           evidence={"recovery_verified_at": r.get("recovery_verified_at"), "post_recovery": flow,
                                     "backfill_status": backfill},
                           recommendation="Re-check restored event flow once post-recovery days are lag-mature.",
                           uncertainty="Recovery timing for Smart Bidding is not predictable; no fixed timeline.")
            s8.observe(f"Incident {iid} recovery state", incident_id=iid, recovery_verified_at=rec,
                       post_recovery_flow=flow, backfill_status=backfill, backfill_may_change_incident=late)

    if s9.runnable:
        routed = [r for r in rows if _confirmed(r)]
        for r in routed:
            s9.observe(f"Send incident {_id(r.get('incident_id'))} to skill-111 for applicability and exclusion "
                       "review", incident_id=_id(r.get("incident_id")), campaign_id=r.get("campaign_id"),
                       action_id=r.get("action_id"), fault_start=r.get("fault_start"), fault_end=r.get("fault_end"),
                       evidence_reference=r.get("evidence_reference"))
        s9.observe("Routing totals (unconfirmed anomalies are never routed for exclusion)", routed=len(routed),
                   not_confirmed=len(rows) - len(routed))


def verify(ctx, item, decision) -> list[str]:
    """Rules: explanations and Critical outcomes must cite a reference present in the supplied evidence."""
    outcome = decision.get("outcome")
    ref = _id((decision.get("proposal") or {}).get("evidence_ref"))
    if item.condition_key == "anomaly_cause" and outcome == "business_or_reporting_explained":
        refs = item.evidence.get("evidence_refs") or []
        if not ref:
            return ["explanation needs proposal.evidence_ref naming a supplied context/incident reference"]
        if ref not in refs:
            return [f"evidence_ref {ref!r} not among supplied refs {refs}"]
    if item.condition_key == "material_tracking_failure" and outcome == "material_failure_confirmed":
        if not ref:
            return ["Critical needs proposal.evidence_ref citing the incident's material impact evidence"]
        iid = item.entity.get("incident_id")
        row = next((r for r in ctx.rows(INCIDENTS) if _id(r.get("incident_id")) == iid), None)
        if row is None or not _confirmed(row) or not row.get("material_impact_evidence"):
            return [f"incident {iid} is not a confirmed incident with material_impact_evidence"]
        if ref not in {_id(row.get("material_impact_evidence")), _id(row.get("evidence_reference"))}:
            return [f"evidence_ref {ref!r} does not match incident {iid} evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
