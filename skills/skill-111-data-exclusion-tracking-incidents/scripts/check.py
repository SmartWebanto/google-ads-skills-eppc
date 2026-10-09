"""check.py — skill-111 deterministic data-exclusion review for confirmed tracking incidents.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-111-data-exclusion-tracking-incidents/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Qualifying incident = external/tracking_incidents row with status_suspected_or_confirmed == 'confirmed'
         AND a non-empty evidence_reference; suspected rows are observed and never assessed for exclusion.
         Unit of assessment = (incident_id, campaign_id); rows without campaign_id are unknown scope, never account-wide.
         Eligibility = data_exclusion_eligibility row with control_available true + source_reference + verified_at whose
         channel/strategy type and strategy ID match the campaign snapshot; false → 'unsupported', null/mismatch →
         'unknown' (Info, never eligible). A missing eligibility row is missing evidence (partial), not a finding.
         Click window is ONLY lag-derived from external/incident_click_impact: every row of the unit needs
         lag_distribution_reference, estimation_method, numeric lower_bound <= estimated_impacted_fraction <= upper_bound,
         reporting_mature true; window = interaction dates with upper_bound > 0, all on/before the fault_end date.
         Otherwise the window is 'uncertain' (Info + prerequisite) — never outage timestamps or a universal lookback.
         interaction_date is read in the account time_zone; time comparisons need exclusion/incident/account timezone
         strings to be equal, else the comparison is partial (no conversion across zones). Day grain throughout.
         Existing exclusion overbroad/mis-scoped (Warning) only by interval/set arithmetic against linked confirmed
         incidents (dates outside fault ∪ click window, campaigns or devices outside the documented scope).
         'Defensible exclusion case' and 'material ongoing failure' are judgments → ai_review. Critical only via
         outcome material_ongoing_failure whose proposal.evidence_ref equals the unit's material_impact_evidence.
         verify(): exclusion proposals must use an allowed scope type/device, stay inside the lag-derived window and
         the parseable allowed_date_window, name the account timezone, and document unaffected data, monitoring,
         rollback criteria and UI start/end semantics. Recommend-only: nothing is applied, removed or widened.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
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

SKILL = "skill-111-data-exclusion-tracking-incidents"
VERSION = "1.0.0"

INC = "external/tracking_incidents"
CFG = "external/data_exclusion_config"
ELG = "external/data_exclusion_eligibility"
IMP = "external/incident_click_impact"
REC = "external/incident_recovery_review"

INC_COLS = ["incident_id", "campaign_id", "device", "status_suspected_or_confirmed", "fault_start", "fault_end",
            "timezone", "timestamp_precision", "fault_type", "evidence_reference"]
ELG_COLS = ["campaign_id", "strategy_id", "channel_type", "bidding_strategy_type", "control_available",
            "allowed_scope_types", "supported_device_scope", "allowed_date_window", "source_reference", "verified_at"]
CFG_COLS = ["exclusion_id", "campaign_id", "scope_type", "start_datetime", "end_datetime", "timezone", "status"]
IMP_COLS = ["incident_id", "campaign_id", "device", "interaction_date", "lag_distribution_reference",
            "estimated_impacted_fraction", "estimation_method", "lower_bound", "upper_bound", "reporting_mature"]
REC_COLS = ["incident_id", "campaign_id", "repair_verified", "backfill_complete", "residual_bad_data"]
REC_OPTIONAL = ["repair_verified_at", "backfill_expected", "current_strategy_state", "proposed_control_rationale",
                "exclusion_overlap_risk", "owner"]
INC_OPTIONAL = ["action_id", "channel", "recovery_verified_at", "backfill_status", "material_impact_evidence", "owner"]

ALL = "ALL"
_ALL_TOKENS = {"ALL", "ALL_DEVICES", "ANY"}
_ACCOUNT_SCOPES = {"CUSTOMER", "ACCOUNT"}
_LISTS = (";", "|", ",")


# ---------------------------------------------------------------- parsing helpers
def _s(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return None if s.lower() in V.MISSING_TOKENS else s


def _up(v) -> str:
    return (_s(v) or "").upper()


def _tz(v) -> str | None:
    s = _s(v)
    return s.lower() if s else None


def _devices(*cells) -> set[str] | None:
    """First non-empty cell → upper-case device set; ALL tokens collapse to {'ALL'}; empty → None (unknown)."""
    for c in cells:
        items = {x.upper() for x in V.split_list(c, _LISTS)}
        if items:
            return {ALL} if items & _ALL_TOKENS else items
    return None


def _id_list(v) -> list[str]:
    return sorted(set(V.split_list(v, _LISTS)))


def _absent(ctx, key: str, cols) -> list[str]:
    t = ctx.table(key)
    return [f"{key}:{c}" for c in (t.missing(cols) if t else cols)]


def _dates(a, b):
    return [a, b] if a and b else None


def _window_bounds(text) -> tuple | None:
    """allowed_date_window parsed only as 'YYYY-MM-DD/YYYY-MM-DD' or 'YYYY-MM-DD..YYYY-MM-DD'."""
    s = _s(text)
    if not s:
        return None
    for sep in ("..", "/"):
        if sep in s:
            a, b = (V.parse_date(x.strip()) for x in s.split(sep, 1))
            if a and b and len(s.split(sep, 1)[0].strip()) >= 10:
                return a, b
    return None


# ---------------------------------------------------------------- evidence models
def _incidents(ctx):
    """Group qualifying rows into (incident_id, campaign_id) units; return (units, suspected, unqualified, no_scope)."""
    units: dict[tuple, dict] = {}
    suspected, unqualified, no_scope = [], [], []
    for r in sorted(ctx.rows(INC), key=lambda r: (str(r.get("incident_id")), str(r.get("campaign_id")),
                                                    str(r.get("device")))):
        iid, cid = _s(r.get("incident_id")), _s(r.get("campaign_id"))
        status = (_s(r.get("status_suspected_or_confirmed")) or "").lower()
        if status != "confirmed":
            suspected.append({"incident_id": iid, "campaign_id": cid, "status": status or None})
            continue
        if not _s(r.get("evidence_reference")) or not iid:
            unqualified.append({"incident_id": iid, "campaign_id": cid, "reason": "confirmed without evidence_reference"
                                if iid else "confirmed row without incident_id"})
            continue
        if not cid:
            no_scope.append(iid)
            continue
        u = units.setdefault((iid, cid), {
            "incident_id": iid, "campaign_id": cid, "devices": set(), "device_unknown": False, "rows": 0,
            "fault_start": set(), "fault_end": set(), "fault_start_raw": set(), "fault_end_raw": set(),
            "timezone": set(), "precision": set(), "fault_type": set(), "evidence_reference": set(),
            "material_impact_evidence": set(), "recovery_verified_at": set(), "backfill_status": set(),
            "owner": set(), "action_ids": set(), "fault_end_unknown": False})
        u["rows"] += 1
        dev = _devices(r.get("device"))
        if dev is None:
            u["device_unknown"] = True
        else:
            u["devices"] |= dev
        fs, fe = V.parse_date(r.get("fault_start")), V.parse_date(r.get("fault_end"))
        if fs:
            u["fault_start"].add(fs)
        if fe:
            u["fault_end"].add(fe)
        else:
            u["fault_end_unknown"] = True
        for key, col in (("fault_start_raw", "fault_start"), ("fault_end_raw", "fault_end"), ("precision",
                         "timestamp_precision"), ("fault_type", "fault_type"), ("evidence_reference",
                         "evidence_reference"), ("material_impact_evidence", "material_impact_evidence"),
                         ("recovery_verified_at", "recovery_verified_at"), ("backfill_status", "backfill_status"),
                         ("owner", "owner"), ("action_ids", "action_id")):
            v = _s(r.get(col))
            if v:
                u[key].add(v)
        tz = _tz(r.get("timezone"))
        u["timezone"].add(tz)
    for u in units.values():
        u["start"] = min(u["fault_start"]) if u["fault_start"] else None
        u["end"] = None if u["fault_end_unknown"] or not u["fault_end"] else max(u["fault_end"])
        tzs = u["timezone"]
        u["tz"] = next(iter(tzs)) if len(tzs) == 1 else None
        u["dev"] = None if u["device_unknown"] else (u["devices"] or None)
    return units, suspected, unqualified, sorted(set(no_scope))


def _unit_ev(u: dict) -> dict:
    return {"incident_id": u["incident_id"], "campaign_id": u["campaign_id"],
            "devices": sorted(u["dev"]) if u["dev"] else None, "fault_window": [u["start"], u["end"]],
            "fault_start_raw": sorted(u["fault_start_raw"]), "fault_end_raw": sorted(u["fault_end_raw"]),
            "timezone": u["tz"], "timestamp_precision": sorted(u["precision"]) or None,
            "fault_type": sorted(u["fault_type"]), "evidence_reference": sorted(u["evidence_reference"]),
            "material_impact_evidence": sorted(u["material_impact_evidence"]) or None,
            "recovery_verified_at": sorted(u["recovery_verified_at"]) or None,
            "backfill_status": sorted(u["backfill_status"]) or None, "owner": sorted(u["owner"]) or None,
            "action_ids": sorted(u["action_ids"])}


def _campaign_row(ctx, cid: str) -> dict | None:
    return next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None)


def _eligibility(ctx, units) -> tuple[dict, list[str]]:
    """Per campaign: {'state': eligible|unsupported|unknown|missing, reasons, row fields}."""
    by_c: dict[str, list[dict]] = {}
    for r in ctx.rows(ELG):
        by_c.setdefault(str(_s(r.get("campaign_id"))), []).append(r)
    strategies = ctx.table("bidding_strategies")
    out, notes = {}, []
    for cid in sorted({u["campaign_id"] for u in units.values()}):
        rows = by_c.get(cid, [])
        if not rows:
            out[cid] = {"state": "missing", "reasons": ["no eligibility row"]}
            continue
        latest = max(str(_s(r.get("verified_at")) or "") for r in rows)
        cur = [r for r in rows if str(_s(r.get("verified_at")) or "") == latest]
        r = cur[0]
        reasons = []
        if len(cur) > 1 and len({(_up(x.get("control_available")), _up(x.get("allowed_scope_types")),
                                  _up(x.get("supported_device_scope"))) for x in cur}) > 1:
            reasons.append(f"conflicting eligibility rows verified at {latest or 'unknown'}")
        avail = V.boolean(r.get("control_available"))
        camp = _campaign_row(ctx, cid)
        if camp is None:
            reasons.append("campaign id not in campaigns snapshot")
        else:
            for col in ("channel_type", "bidding_strategy_type"):
                a, b = _up(r.get(col)), _up(camp.get(col))
                if a and b and a != b:
                    reasons.append(f"{col} {a} differs from campaign snapshot {b}")
                elif not a:
                    reasons.append(f"{col} unknown in eligibility row")
            sid, csid = _s(r.get("strategy_id")), _s(camp.get("bidding_strategy_id") or camp.get("strategy_id"))
            if sid and csid and sid != csid:
                reasons.append(f"strategy_id {sid} differs from campaign strategy {csid}")
            if sid and strategies is not None and not csid:
                srow = next((s for s in strategies.rows if str(s.get("id")) == sid), None)
                if srow is None:
                    reasons.append(f"strategy {sid} not in bidding_strategies snapshot")
                elif "campaign_ids" in strategies.columns and cid not in V.split_list(srow.get("campaign_ids"), _LISTS):
                    reasons.append(f"strategy {sid} does not list campaign {cid}")
            elif sid and not csid:
                notes.append(f"campaign {cid}: strategy_id {sid} not cross-checked (no campaign/strategy link)")
        if not _s(r.get("source_reference")) or not _s(r.get("verified_at")):
            reasons.append("source_reference/verified_at missing")
        if avail is False and not reasons:
            state = "unsupported"
            reasons.append("control_available false")
        elif avail is True and not reasons:
            state = "eligible"
        else:
            state = "unknown"
            if avail is None:
                reasons.append("control_available unknown")
        out[cid] = {"state": state, "reasons": reasons, "control_available": avail,
                    "allowed_scope_types": sorted({x.upper() for x in V.split_list(r.get("allowed_scope_types"), _LISTS)}),
                    "supported_device_scope": sorted(_devices(r.get("supported_device_scope")) or []),
                    "allowed_date_window": _s(r.get("allowed_date_window")),
                    "channel_type": _s(r.get("channel_type")), "bidding_strategy_type": _s(r.get("bidding_strategy_type")),
                    "strategy_id": _s(r.get("strategy_id")), "source_reference": _s(r.get("source_reference")),
                    "verified_at": _s(r.get("verified_at"))}
    return out, notes


def _click_windows(ctx, units) -> dict:
    """Per unit: lag-derived window or uncertainty reasons. Rules: unknown lag → uncertainty reason, never a default window."""
    acct_tz = _tz(ctx.account.get("time_zone"))
    rows_by: dict[tuple, list[dict]] = {}
    for r in ctx.rows(IMP):
        rows_by.setdefault((str(_s(r.get("incident_id"))), str(_s(r.get("campaign_id")))), []).append(r)
    out = {}
    for key in sorted(units):
        u = units[key]
        rows = sorted(rows_by.get(key, []), key=lambda r: (str(r.get("interaction_date")), str(r.get("device"))))
        reasons, possible, confident, zero = [], set(), set(), set()
        clicks = cost = 0.0
        clicks_known = cost_known = bool(rows)
        currencies = set()
        refs, methods, devs = set(), set(), set()
        if not rows:
            reasons.append("no click-impact estimate rows")
        for r in rows:
            d = V.parse_date(r.get("interaction_date"))
            lo, est, hi = V.num(r.get("lower_bound")), V.num(r.get("estimated_impacted_fraction")), V.num(r.get("upper_bound"))
            ref, meth = _s(r.get("lag_distribution_reference")), _s(r.get("estimation_method"))
            if d is None:
                reasons.append("interaction_date unparsable")
                continue
            if not ref or not meth:
                reasons.append(f"{d}: lag_distribution_reference/estimation_method missing")
            refs |= {ref} if ref else set()
            methods |= {meth} if meth else set()
            devs |= _devices(r.get("device")) or set()
            if lo is None or hi is None or est is None:
                reasons.append(f"{d}: bounds/estimate missing")
            elif not lo <= est <= hi:
                reasons.append(f"{d}: bounds inconsistent (lower {lo:g}, estimate {est:g}, upper {hi:g})")
            if V.boolean(r.get("reporting_mature")) is not True:
                reasons.append(f"{d}: reporting not mature")
            if hi is not None and hi > 0:
                possible.add(d)
            elif hi is not None:
                zero.add(d)
            if lo is not None and lo > 0:
                confident.add(d)
            c, m = V.num(r.get("affected_clicks")), ctx.money(r.get("affected_cost"))
            clicks_known &= c is not None
            cost_known &= m is not None
            clicks += c or 0
            cost += m or 0
            cur = _up(r.get("currency"))
            if cur:
                currencies.add(cur)
        if rows and not possible and not any("missing" in x for x in reasons):
            reasons.append("no interaction date with upper_bound > 0")
        if u["end"] is None:
            reasons.append("fault_end unknown or incident open: window not closed")
        elif possible and max(possible) > u["end"]:
            reasons.append(f"impact dates after fault_end {u['end']}")
        if u["tz"] is None or acct_tz is None or u["tz"] != acct_tz:
            reasons.append(f"incident timezone {u['tz']} vs account time_zone {acct_tz}: interaction dates not comparable")
        if currencies and currencies != {ctx.currency}:
            cost_known = False
        start, end = (min(possible), max(possible)) if possible else (None, None)
        out[key] = {"defensible": not reasons, "reasons": sorted(set(reasons)), "window": _dates(start, end),
                    "possible_dates": sorted(possible), "confident_dates": sorted(confident),
                    "zero_impact_dates_inside": sorted(d for d in zero if start and start <= d <= end),
                    "rows": len(rows), "lag_distribution_reference": sorted(refs), "estimation_method": sorted(methods),
                    "impact_devices": sorted(devs), "affected_clicks": clicks if clicks_known else None,
                    "affected_cost": cost if cost_known else None, "currency": ctx.currency,
                    "impact_currencies": sorted(currencies)}
    return out


def _exclusions(ctx) -> list[dict]:
    t = ctx.table(CFG)
    has_dev = t is not None and ("affected_devices" in t.columns or "device" in t.columns)
    all_campaigns = {str(r.get("id")) for r in ctx.rows("campaigns") if r.get("id") is not None} or None
    out = []
    for r in sorted(ctx.rows(CFG), key=lambda r: str(r.get("exclusion_id"))):
        scope = _up(r.get("scope_type"))
        if scope == "CAMPAIGN":
            camps = set(_id_list(r.get("campaign_id"))) or None
        elif scope in _ACCOUNT_SCOPES:
            camps = all_campaigns
        else:
            camps = None
        out.append({"exclusion_id": _s(r.get("exclusion_id")), "scope_type": scope or None, "campaigns": camps,
                    "account_scope": scope in _ACCOUNT_SCOPES,
                    "devices": _devices(r.get("affected_devices"), r.get("device")) if has_dev else None,
                    "start": V.parse_date(r.get("start_datetime")), "end": V.parse_date(r.get("end_datetime")),
                    "start_raw": _s(r.get("start_datetime")), "end_raw": _s(r.get("end_datetime")),
                    "tz": _tz(r.get("timezone")), "status": _up(r.get("status")) or None,
                    "source_reference": _s(r.get("source_reference")), "owner": _s(r.get("owner"))})
    return out


def _ex_ev(x: dict) -> dict:
    return {"exclusion_id": x["exclusion_id"], "scope_type": x["scope_type"],
            "campaigns": sorted(x["campaigns"]) if x["campaigns"] else None,
            "devices": sorted(x["devices"]) if x["devices"] else None, "start": x["start_raw"], "end": x["end_raw"],
            "timezone": x["tz"], "status": x["status"], "source_reference": x["source_reference"]}


def _recovery(ctx) -> dict:
    out: dict[tuple, list[dict]] = {}
    for r in ctx.rows(REC):
        out.setdefault((str(_s(r.get("incident_id"))), str(_s(r.get("campaign_id")))), []).append(r)
    return out


# ---------------------------------------------------------------- run
def run(ctx) -> None:
    """Qualify confirmed incidents, then run eligibility, config, click-window, overlap, recovery and proposal checks.

    Rules:   Dependent checks skip if confirmed_incidents is unrunnable; no confirmed unit → n/a (complete inventory) or
             partial. Suspected incidents are observe-only. Unknown/unsupported eligibility and uncertain windows → Info.
             Only interval/set overbreadth of an existing exclusion is a deterministic Warning; unlinked exclusions,
             review cases, material ongoing failure (Critical) → ai_review; proposal/monitoring checks observe-only.
    """
    acct_tz = _tz(ctx.account.get("time_zone"))

    # step 1 — confirmed measurement-fault evidence
    s1 = ctx.check("confirmed_incidents", "Confirmed measurement-fault incidents qualifying for exclusion assessment",
                   {INC: INC_COLS})
    units: dict = {}
    if s1.runnable:
        units, suspected, unqualified, no_scope = _incidents(ctx)
        for u in sorted(units.values(), key=lambda u: (u["incident_id"], u["campaign_id"])):
            s1.observe(f"Confirmed incident {u['incident_id']} affects campaign {u['campaign_id']}", **_unit_ev(u))
        for x in suspected:
            s1.observe(f"Incident {x['incident_id']} is {x['status'] or 'unclassified'}: not assessed for exclusion "
                       "(confirm via skill-110 first)", **x)
        for x in unqualified:
            s1.observe(f"Incident {x['incident_id']} not qualifying: {x['reason']}", **x)
        for iid in no_scope:
            s1.partial(f"confirmed incident {iid} has rows without campaign_id: scope unknown, not assumed account-wide",
                       [f"{INC}:campaign_id"])
        miss = _absent(ctx, INC, INC_OPTIONAL)
        if miss:
            s1.partial("optional incident columns absent: recovery/materiality context unknown", miss)
        s1.observe("Incident qualification totals", confirmed_units=len(units), suspected_rows=len(suspected),
                   unqualified_rows=len(unqualified))
        if not units and ctx.table(INC).complete is not True:
            s1.partial("no qualifying incident in an incident inventory without attested completeness")

    inc_ok = s1.runnable
    inc_complete = inc_ok and ctx.table(INC).complete is True

    def gate(chk, what: str) -> bool:
        """Dependent-check gate: prerequisite missing → skipped; no confirmed incident → n/a or partial."""
        if not inc_ok:
            chk.skip("prerequisite confirmed_incidents not runnable", s1.missing or [f"{INC} (file)"])
            return False
        if not chk.runnable:
            return False
        if not units:
            if inc_complete:
                chk.not_applicable(f"no confirmed incident with evidence: {what} not needed")
            else:
                chk.partial(f"no confirmed incident found, but incident inventory completeness is not attested: {what} "
                            "not assessed")
            return False
        return True

    # step 2 — eligibility
    s2 = ctx.check("exclusion_eligibility", "Campaign/strategy IDs, channel and control eligibility",
                   {ELG: ELG_COLS, "campaigns": ["id", "channel_type", "bidding_strategy_type"]})
    elig: dict = {}
    if gate(s2, "eligibility"):
        elig, notes = _eligibility(ctx, units)
        for n in notes:
            s2.partial(n)
        for cid, e in sorted(elig.items()):
            inc_ids = sorted(u["incident_id"] for u in units.values() if u["campaign_id"] == cid)
            if e["state"] == "missing":
                s2.partial(f"campaign {cid}: no eligibility row", [f"{ELG}:campaign_id={cid}"])
                continue
            ev = {k: v for k, v in e.items() if k != "state"}
            ev["incident_ids"] = inc_ids
            if e["state"] == "eligible":
                s2.observe(f"Campaign {cid}: data-exclusion control available ({e['source_reference']}, "
                           f"verified {e['verified_at']})", campaign_id=cid, **ev)
                continue
            cond = "unsupported_eligibility" if e["state"] == "unsupported" else "unknown_eligibility"
            s2.finding(cond, "Info", {"campaign_id": cid},
                       f"Campaign {cid} ({', '.join(inc_ids)}): data exclusion {e['state']} — "
                       + "; ".join(e["reasons"]), evidence=ev,
                       recommendation="Do not propose an exclusion for this campaign; confirm current control support "
                                      "from direct settings and current documentation first.",
                       uncertainty="Unknown support is not eligibility; platform support can change.")

    # step 3 — existing exclusions
    s3 = ctx.check("existing_exclusions", "Existing data exclusions from actual configuration", {CFG: CFG_COLS})
    exclusions: list[dict] = []
    cfg_complete = False
    if s3.runnable:
        exclusions = _exclusions(ctx)
        t = ctx.table(CFG)
        cfg_complete = t.complete is True and not t.truncated
        if not ("affected_devices" in t.columns or "device" in t.columns):
            s3.partial("device scope of exclusions unknown", [f"{CFG}:affected_devices", f"{CFG}:device"])
        for x in exclusions:
            gaps = [k for k in ("start", "end", "tz", "scope_type") if not x[k]]
            if x["campaigns"] is None:
                gaps.append("campaign set")
            s3.observe(f"Exclusion {x['exclusion_id']} ({x['scope_type']}, {x['status']})", **_ex_ev(x),
                       unresolved=gaps)
            if gaps:
                s3.partial(f"exclusion {x['exclusion_id']}: {', '.join(gaps)} unknown")
        if not exclusions:
            if cfg_complete:
                s3.observe("Complete configuration export lists no data exclusions", exclusions=0)
            else:
                s3.partial("empty exclusion table without attested completeness: existing exclusions unknown")

    # step 4 — lag-derived click window
    s4 = ctx.check("click_window", "Lag-derived affected interaction/click window", {IMP: IMP_COLS})
    windows: dict = {}
    if gate(s4, "click window"):
        windows = _click_windows(ctx, units)
        imp_complete = ctx.table(IMP).complete is True
        for key, w in sorted(windows.items()):
            if w["defensible"]:
                s4.observe(f"Incident {key[0]} campaign {key[1]}: lag-derived click window {w['window'][0]}..{w['window'][1]}",
                           incident_id=key[0], campaign_id=key[1], **w)
            elif w["rows"] == 0 and not imp_complete:
                s4.partial(f"incident {key[0]} campaign {key[1]}: no click-impact rows in an incomplete table",
                           [f"{IMP}:incident_id={key[0]},campaign_id={key[1]}"])
            else:
                s4.observe(f"Incident {key[0]} campaign {key[1]}: no defensible click window", incident_id=key[0],
                           campaign_id=key[1], **w)
        miss = _absent(ctx, IMP, ["affected_clicks", "affected_cost", "currency"])
        if miss:
            s4.partial("impact exposure columns absent", miss)

    # step 5 — uncertainty and timestamp precision
    s5 = ctx.check("click_window_uncertainty", "Impact uncertainty, timestamp precision and click-window prerequisites",
                   {IMP: IMP_COLS, INC: ["timestamp_precision"]})
    if gate(s5, "uncertainty review"):
        imp_complete = ctx.table(IMP).complete is True
        for key, w in sorted(windows.items()):
            u = units[key]
            if not u["precision"]:
                s5.partial(f"incident {key[0]} campaign {key[1]}: timestamp_precision unknown",
                           [f"{INC}:timestamp_precision"])
            if w["defensible"]:
                s5.observe(f"Incident {key[0]} campaign {key[1]}: window bounds and precision", incident_id=key[0],
                           campaign_id=key[1], window=w["window"], confident_dates=w["confident_dates"],
                           possible_dates=w["possible_dates"], timestamp_precision=sorted(u["precision"]) or None)
                continue
            if w["rows"] == 0 and not imp_complete:
                continue
            s5.finding("uncertain_click_window", "Info", {"incident_id": key[0], "campaign_id": key[1]},
                       f"Incident {key[0]} campaign {key[1]}: no defensible lag-derived click window "
                       f"({'; '.join(w['reasons'][:3])})",
                       evidence={**_unit_ev(u), "click_window": w},
                       recommendation="Report the prerequisite (mature lag-distribution estimate with bounds, closed "
                                      "fault window, matching timezone); do not propose broad exclusion dates.",
                       uncertainty="Without a lag-derived window, any exclusion dates would be a guess.")

    # step 6 — overlap of existing exclusions with incident evidence
    s6 = ctx.check("exclusion_overlap", "Existing exclusions vs incident campaigns, devices and windows",
                   {CFG: CFG_COLS, IMP: IMP_COLS})
    if gate(s6, "overlap analysis"):
        _overlap(ctx, s6, units, windows, exclusions, elig, acct_tz, inc_complete, cfg_complete)

    # step 7 — recovery, backfill, materiality → review
    s7 = ctx.check("recovery_assessment", "Repair, backfill, residual data, bidding state and materiality",
                   {REC: REC_COLS})
    candidates: list[tuple] = []
    if gate(s7, "recovery assessment"):
        candidates = _recovery_step(ctx, s7, units, windows, elig, exclusions)

    # step 8 — supported proposal envelope
    s8 = ctx.check("proposal_scope", "Supported scope, timezone-qualified window and unaffected data",
                   {ELG: ELG_COLS, IMP: IMP_COLS})
    if gate(s8, "proposal scope") and s7.runnable:
        if not candidates:
            s8.not_applicable("no eligible confirmed incident with residual data and a defensible click window")
        for key in candidates:
            u, w, e = units[key], windows[key], elig[key[1]]
            narrow = "CAMPAIGN" in e["allowed_scope_types"]
            dev_ok = u["dev"] is not None and (ALL in u["dev"] or u["dev"] <= set(e["supported_device_scope"]))
            unaffected = {"zero_impact_dates_inside_window": w["zero_impact_dates_inside"],
                          "possible_but_unconfirmed_dates": sorted(set(w["possible_dates"]) - set(w["confident_dates"]))}
            if not narrow:
                unaffected["other_campaigns_if_broader_scope"] = sorted(
                    str(r.get("id")) for r in ctx.rows("campaigns") if str(r.get("id")) != key[1])
            if u["dev"] and ALL not in u["dev"] and not dev_ok:
                unaffected["other_devices"] = "supported device scope is broader than the affected devices"
            s8.observe(f"Incident {key[0]} campaign {key[1]}: supported proposal envelope", incident_id=key[0],
                       campaign_id=key[1], window=w["window"], timezone=acct_tz,
                       allowed_scope_types=e["allowed_scope_types"], supported_device_scope=e["supported_device_scope"],
                       allowed_date_window=e["allowed_date_window"], affected_devices=sorted(u["dev"] or []),
                       campaign_scope_supported=narrow, unaffected_data_included=unaffected)
            if _window_bounds(e["allowed_date_window"]) is None and e["allowed_date_window"]:
                s8.partial(f"campaign {key[1]}: allowed_date_window '{e['allowed_date_window']}' not machine-checkable")
    elif s8.runnable and not s7.runnable and inc_ok and units:
        s8.skip("prerequisite recovery_assessment not runnable", s7.missing)

    # step 9 — monitoring and rollback criteria
    s9 = ctx.check("monitoring_rollback", "Owner, monitoring and rollback/review criteria", {REC: REC_COLS})
    if gate(s9, "monitoring criteria"):
        rec_rows = _recovery(ctx)
        if not candidates:
            s9.not_applicable("no exclusion review case: monitoring criteria not needed")
        for key in candidates:
            rows = rec_rows.get(key, [])
            owners = sorted({_s(r.get("owner")) for r in rows if _s(r.get("owner"))} | units[key]["owner"])
            if not owners:
                s9.partial(f"incident {key[0]} campaign {key[1]}: no owner recorded", [f"{REC}:owner"])
            s9.observe(f"Incident {key[0]} campaign {key[1]}: review anchors for owner monitoring", incident_id=key[0],
                       campaign_id=key[1], owners=owners,
                       repair_verified_at=sorted({_s(r.get("repair_verified_at")) for r in rows} - {None}),
                       backfill_expected=[V.boolean(r.get("backfill_expected")) for r in rows],
                       backfill_complete=[V.boolean(r.get("backfill_complete")) for r in rows],
                       note="Proposal must state monitoring and rollback criteria; no recovery duration is guaranteed.")


def _overlap(ctx, chk, units, windows, exclusions, elig, acct_tz, inc_complete, cfg_complete) -> None:
    live = [x for x in exclusions if x["status"] != "REMOVED"]
    all_campaigns = {str(r.get("id")) for r in ctx.rows("campaigns") if r.get("id") is not None}

    def envelope(u, w):
        dates = [d for d in (u["start"], u["end"]) if d] + ([w["window"][0], w["window"][1]] if w["window"] else [])
        return (min(dates), max(dates)) if dates else None

    for x in live:
        if not (x["start"] and x["end"]):
            chk.partial(f"exclusion {x['exclusion_id']}: start/end unknown; overlap undecidable")
            continue
        linked = []
        for key in sorted(units):
            u = units[key]
            env = envelope(u, windows[key])
            in_camp = x["campaigns"] is None or key[1] in x["campaigns"]
            if env and in_camp and x["start"] <= env[1] and env[0] <= x["end"]:
                linked.append(key)
        if not linked:
            if not inc_complete:
                chk.partial(f"exclusion {x['exclusion_id']}: no linked confirmed incident in an incomplete incident "
                            "inventory")
                continue
            chk.review("unlinked_exclusion", {"exclusion_id": x["exclusion_id"]},
                       f"Exclusion {x['exclusion_id']} overlaps no documented confirmed incident. Is it mis-scoped "
                       "relative to the documented incident evidence?",
                       evidence={"exclusion": _ex_ev(x), "confirmed_units": [_unit_ev(units[k]) for k in sorted(units)]},
                       outcomes={"mis_scoped": {"severity": "Warning", "recommendation":
                                                "Owner review of this exclusion's basis; never remove automatically."},
                                 "documented_elsewhere": {"severity": None, "recommendation":
                                                          "Cite the incident record justifying it."},
                                 "uncertain": {"severity": "Info", "recommendation":
                                               "Ask the owner for the incident behind this exclusion."}},
                       guidance="Choose documented_elsewhere only when the owner supplies another incident record; "
                                "a complete incident inventory lists none.")
            continue
        undecidable = []
        tzs = {units[k]["tz"] for k in linked} | {x["tz"], acct_tz}
        if len(tzs) != 1 or None in tzs:
            undecidable.append(f"timezones differ or unknown ({sorted(str(t) for t in tzs)})")
        for k in linked:
            if not windows[k]["defensible"]:
                undecidable.append(f"{k[0]}/{k[1]} click window not defensible")
            if units[k]["end"] is None or units[k]["start"] is None:
                undecidable.append(f"{k[0]}/{k[1]} fault window open/unknown")
        ev = {"exclusion": _ex_ev(x), "linked_units": [f"{k[0]}/{k[1]}" for k in linked]}
        if undecidable:
            chk.partial(f"exclusion {x['exclusion_id']}: overlap undecidable — " + "; ".join(sorted(set(undecidable))))
            chk.observe(f"Exclusion {x['exclusion_id']} overlaps confirmed incidents (scope not decidable)", **ev)
            continue
        envs = [envelope(units[k], windows[k]) for k in linked]
        env_start, env_end = min(e[0] for e in envs), max(e[1] for e in envs)
        days_before = max(0, (env_start - x["start"]).days)
        days_after = max(0, (x["end"] - env_end).days)
        inc_camps = {k[1] for k in units if any(k[0] == lk[0] for lk in linked)}
        extra_camps = None
        if x["campaigns"] is None:
            chk.partial(f"exclusion {x['exclusion_id']}: campaign set unknown for scope {x['scope_type']}")
        elif x["account_scope"] and not all_campaigns:
            chk.partial(f"exclusion {x['exclusion_id']}: account scope but campaigns snapshot missing",
                        ["campaigns (file)"])
        else:
            extra_camps = sorted(x["campaigns"] - inc_camps)
        inc_devs: set | None = set()
        for k in linked:
            if units[k]["dev"] is None:
                inc_devs = None
                break
            inc_devs |= units[k]["dev"]
        extra_devs = None
        if inc_devs is None or x["devices"] is None:
            chk.partial(f"exclusion {x['exclusion_id']}: device scope undecidable (unknown device on one side)")
        elif ALL in inc_devs:
            extra_devs = []
        elif ALL in x["devices"]:
            extra_devs = [f"ALL beyond {sorted(inc_devs)}"]
        else:
            extra_devs = sorted(x["devices"] - inc_devs)
        calc = {"envelope": [env_start, env_end], "exclusion_window": [x["start"], x["end"]],
                "days_before_envelope": days_before, "days_after_envelope": days_after,
                "extra_campaigns": extra_camps, "incident_campaigns": sorted(inc_camps),
                "extra_devices": extra_devs, "incident_devices": sorted(inc_devs) if inc_devs else inc_devs,
                "envelope_basis": "fault window ∪ lag-derived click window (day grain, shared timezone)"}
        if days_before or days_after or extra_camps or extra_devs:
            chk.finding("exclusion_overbroad_or_misscoped", "Warning", {"exclusion_id": x["exclusion_id"]},
                        f"Exclusion {x['exclusion_id']} extends beyond documented incident evidence: "
                        f"{days_before}d before / {days_after}d after the envelope {env_start}..{env_end}"
                        + (f", extra campaigns {extra_camps}" if extra_camps else "")
                        + (f", extra devices {extra_devs}" if extra_devs else ""),
                        evidence=ev, calculation=calc,
                        recommendation="Owner review of the exclusion scope against the incident record; this skill "
                                       "never edits, removes or widens exclusions.",
                        uncertainty="Day-grain comparison; the envelope depends on the supplied lag-derived estimate.")
        else:
            chk.observe(f"Exclusion {x['exclusion_id']} lies within the documented incident envelope", **ev, **calc)

    # gaps and duplication
    for key in sorted(units):
        w = windows[key]
        if not w["defensible"]:
            continue
        u = units[key]
        maybe = [x for x in live if x["campaigns"] is None or key[1] in x["campaigns"]]
        covering = [x for x in maybe if x["campaigns"] is not None
                    and (x["devices"] is None or u["dev"] is None or ALL in x["devices"] or ALL in u["dev"]
                         or bool(x["devices"] & u["dev"]))]
        if any(x["campaigns"] is None for x in maybe) or any(x["tz"] != u["tz"] or not (x["start"] and x["end"])
                                                             for x in covering):
            chk.partial(f"incident {key[0]} campaign {key[1]}: gap analysis undecidable (exclusion campaign set, "
                        "timezone or dates differ or unknown)")
        covering = [x for x in covering if x["tz"] == u["tz"] and x["start"] and x["end"]]
        uncovered = [d for d in w["confident_dates"] if not any(x["start"] <= d <= x["end"] for x in covering)]
        if covering:
            chk.observe(f"Incident {key[0]} campaign {key[1]}: exclusion coverage of confident impact dates (gaps listed)",
                        incident_id=key[0], campaign_id=key[1], uncovered_dates=uncovered,
                        covering_exclusions=[x["exclusion_id"] for x in covering])
        elif cfg_complete and not maybe and elig.get(key[1], {}).get("state") == "eligible":
            chk.finding("no_exclusion_for_confirmed_incident", "Info",
                        {"incident_id": key[0], "campaign_id": key[1]},
                        f"Confirmed incident {key[0]} campaign {key[1]} has no existing exclusion (optional control)",
                        evidence={**_unit_ev(u), "click_window": w["window"], "exclusions_in_config": len(exclusions)},
                        recommendation="Absence of an exclusion alone is not a defect; see the recovery review.",
                        uncertainty="An exclusion is optional; recovery or backfill may make it unnecessary.")
        else:
            chk.observe(f"Incident {key[0]} campaign {key[1]}: no covering exclusion found", incident_id=key[0],
                        campaign_id=key[1], config_complete=cfg_complete)
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if not (a["start"] and a["end"] and b["start"] and b["end"]) or a["campaigns"] is None or b["campaigns"] is None:
                continue
            camps = a["campaigns"] & b["campaigns"]
            devs_overlap = a["devices"] is None or b["devices"] is None or ALL in a["devices"] or ALL in b["devices"] \
                or bool(a["devices"] & b["devices"])
            if camps and devs_overlap and a["start"] <= b["end"] and b["start"] <= a["end"] and a["tz"] == b["tz"]:
                chk.observe(f"Exclusions {a['exclusion_id']} and {b['exclusion_id']} duplicate coverage",
                            exclusions=[a["exclusion_id"], b["exclusion_id"]], campaigns=sorted(camps),
                            overlap=[max(a["start"], b["start"]), min(a["end"], b["end"])])


def _recovery_step(ctx, chk, units, windows, elig, exclusions) -> list[tuple]:
    rec = _recovery(ctx)
    metrics = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
    rec_complete = ctx.table(REC).complete is True
    miss = _absent(ctx, REC, REC_OPTIONAL)
    if miss:
        chk.partial("optional recovery columns absent", miss)
    if not metrics:
        chk.partial("campaign_metrics absent: materiality denominators unknown", ["campaign_metrics (file)"])
    candidates = []
    for key in sorted(units):
        u, w = units[key], windows.get(key)
        rows = rec.get(key, [])
        if not rows:
            chk.partial(f"incident {key[0]} campaign {key[1]}: no recovery review row"
                        + ("" if rec_complete else " (table completeness not attested)"),
                        [f"{REC}:incident_id={key[0]},campaign_id={key[1]}"])
            continue
        r = rows[0]
        if len(rows) > 1:
            chk.partial(f"incident {key[0]} campaign {key[1]}: {len(rows)} recovery rows; first used")
        repair, residual = V.boolean(r.get("repair_verified")), V.boolean(r.get("residual_bad_data"))
        backfill_done, backfill_exp = V.boolean(r.get("backfill_complete")), V.boolean(r.get("backfill_expected"))
        repaired_at = V.parse_date(r.get("repair_verified_at"))
        m = metrics.get(key[1], {})
        m_cost, m_clicks = ctx.money(m.get("cost")), V.num(m.get("clicks"))
        state = elig.get(key[1], {}).get("state", "not assessed")
        ev = {**_unit_ev(u), "repair_verified": repair, "repair_verified_at": _s(r.get("repair_verified_at")),
              "backfill_expected": backfill_exp, "backfill_complete": backfill_done, "residual_bad_data": residual,
              "current_strategy_state": _s(r.get("current_strategy_state")),
              "proposed_control_rationale": _s(r.get("proposed_control_rationale")),
              "exclusion_overlap_risk": _s(r.get("exclusion_overlap_risk")), "recovery_owner": _s(r.get("owner")),
              "eligibility": state, "eligibility_detail": elig.get(key[1]),
              "click_window": w["window"] if w else None, "click_window_defensible": w["defensible"] if w else None,
              "possible_dates": w["possible_dates"] if w else None,
              "elapsed_days_since_fault_end": (ctx.snapshot - u["end"]).days if ctx.snapshot and u["end"] else None,
              "elapsed_days_since_repair": (ctx.snapshot - repaired_at).days if ctx.snapshot and repaired_at else None,
              "affected_clicks": w["affected_clicks"] if w else None, "affected_cost": w["affected_cost"] if w else None,
              "campaign_period_clicks": m_clicks, "campaign_period_cost": m_cost,
              "affected_click_share": V.ratio(w["affected_clicks"], m_clicks) if w else None,
              "affected_cost_share": V.ratio(w["affected_cost"], m_cost) if w else None,
              "materiality_basis": "click-window affected clicks/cost vs campaign_metrics period totals (windows may "
                                   "differ; exposure, not savings)",
              "currency": ctx.currency, "account_timezone": _tz(ctx.account.get("time_zone")),
              "incident_campaigns_eligible": sorted(k[1] for k in units if k[0] == key[0]
                                                    and elig.get(k[1], {}).get("state") == "eligible"),
              "existing_exclusions": [_ex_ev(x) for x in exclusions
                                      if x["campaigns"] is not None and key[1] in x["campaigns"]]}
        entity = {"incident_id": key[0], "campaign_id": key[1]}
        ongoing = repair is False
        if ongoing and u["material_impact_evidence"]:
            chk.review("ongoing_measurement_failure", entity,
                       f"Incident {key[0]} (campaign {key[1]}) is confirmed with repair not verified. Does direct "
                       "evidence confirm a MATERIAL ongoing measurement/control failure?",
                       evidence=ev,
                       outcomes={"material_ongoing_failure": {"severity": "Critical", "recommendation":
                                 "Escalate the repair to the incident owner; cite the material-impact evidence."},
                                 "not_material": {"severity": None, "recommendation":
                                                  "Keep monitoring the repair through the owner."},
                                 "uncertain": {"severity": "Info", "recommendation":
                                               "Request material-impact evidence from the owner."}},
                       guidance="material_ongoing_failure needs proposal.evidence_ref equal to the incident's "
                                "material_impact_evidence. Demand change, seasonality, ordinary lag or a site outage "
                                "without tracking corruption do not qualify.")
        elif ongoing:
            chk.observe(f"Incident {key[0]} campaign {key[1]}: repair not verified, no material-impact evidence",
                        **entity)
        if residual is False or backfill_done is True:
            chk.finding("recovered_data", "Info", entity,
                        f"Incident {key[0]} campaign {key[1]}: data recovered (residual_bad_data={residual}, "
                        f"backfill_complete={backfill_done}); exclusion not indicated",
                        evidence=ev, recommendation="Document a no-change decision; keep monitoring through the owner.",
                        uncertainty="Late backfill or unverified repair can still change reported history.")
            continue
        if residual is None:
            chk.partial(f"incident {key[0]} campaign {key[1]}: residual_bad_data unknown", [f"{REC}:residual_bad_data"])
            continue
        if ongoing:
            continue
        if state != "eligible":
            chk.observe(f"Incident {key[0]} campaign {key[1]}: residual bad data but exclusion eligibility {state}",
                        **entity)
            continue
        if not (w and w["defensible"]):
            chk.observe(f"Incident {key[0]} campaign {key[1]}: residual bad data but no defensible click window",
                        **entity)
            continue
        candidates.append(key)
        chk.review("exclusion_review_case", entity,
                   f"Incident {key[0]} campaign {key[1]}: eligible confirmed incident with residual bad data and no "
                   "completed backfill. Is there a defensible exclusion review case, or is no-change better?",
                   evidence=ev,
                   outcomes={"exclusion_review_case": {"severity": "Warning", "recommendation":
                             "Owner-review proposal for the verified scope/window; never apply automatically."},
                             "no_change": {"severity": None, "recommendation":
                                           "Documented no-change alternative with monitoring criteria."},
                             "uncertain": {"severity": "Info", "recommendation":
                                           "Name the missing repair/backfill/materiality evidence."}},
                   guidance="Choose no_change when fault_type/observed_behavior describe demand change, seasonality, "
                            "ordinary lag or a site outage without tracking corruption. "
                            "Weigh repair, expected backfill, elapsed time, current bidding state and materiality. "
                            "exclusion_review_case requires proposal {scope_type, campaign_ids, devices, start, end, "
                            "timezone, unaffected_data, monitoring, rollback_criteria, ui_semantics_ref}; it is checked "
                            "against allowed scope/devices and the lag-derived window.")
    return candidates


# ---------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs the unit's material_impact_evidence; proposals must fit evidence."""
    outcome = decision.get("outcome")
    p = decision.get("proposal") or {}
    ev = item.evidence
    if outcome == "material_ongoing_failure":
        ref = _s(p.get("evidence_ref"))
        allowed = set(ev.get("material_impact_evidence") or [])
        if not ref:
            return ["material_ongoing_failure needs proposal.evidence_ref"]
        if ref not in allowed:
            return [f"evidence_ref {ref!r} is not this incident's material_impact_evidence {sorted(allowed)}"]
        return []
    if outcome != "exclusion_review_case":
        return []
    problems = []
    elig = ev.get("eligibility_detail") or {}
    allowed_scopes = set(elig.get("allowed_scope_types") or [])
    scope = _up(p.get("scope_type"))
    if scope not in allowed_scopes:
        problems.append(f"scope_type {scope or None} not in allowed_scope_types {sorted(allowed_scopes)}")
    elif scope != "CAMPAIGN" and "CAMPAIGN" in allowed_scopes:
        problems.append(f"scope_type {scope} is wider than the supported CAMPAIGN scope")
    camps = [str(c) for c in (p.get("campaign_ids") or [])] if isinstance(p.get("campaign_ids"), list) \
        else _id_list(p.get("campaign_ids"))
    cid = item.entity["campaign_id"]
    if scope == "CAMPAIGN":
        if cid not in camps:
            problems.append(f"campaign_ids must include reviewed campaign {cid}")
        extra = sorted(set(camps) - set(ev.get("incident_campaigns_eligible") or []))
        if extra:
            problems.append(f"campaign_ids {extra} are not eligible campaigns of incident {item.entity['incident_id']}")
    devs = _devices(";".join(p.get("devices")) if isinstance(p.get("devices"), list) else p.get("devices"))
    supported = set(elig.get("supported_device_scope") or [])
    affected = set(ev.get("devices") or [])
    if devs is None:
        problems.append("proposal.devices required")
    elif ALL not in supported and not devs <= supported:
        problems.append(f"devices {sorted(devs)} outside supported_device_scope {sorted(supported)}")
    elif affected and ALL not in affected:
        if ALL in devs and not affected <= supported:
            pass  # only an all-device control is supported: allowed, unaffected devices must be documented
        elif ALL in devs or not devs <= affected:
            problems.append(f"devices {sorted(devs)} wider than affected devices {sorted(affected)}")
    tz = _tz(p.get("timezone"))
    if not tz or tz != ev.get("account_timezone") or tz != ev.get("timezone"):
        problems.append(f"timezone {tz} must equal account/incident timezone {ev.get('account_timezone')}")
    start, end = V.parse_date(p.get("start")), V.parse_date(p.get("end"))
    win = ev.get("click_window") or [None, None]
    w0, w1 = V.parse_date(win[0]), V.parse_date(win[1])
    if start is None or end is None or start > end:
        problems.append("proposal start/end must be dates with start <= end")
    elif w0 is None or w1 is None:
        problems.append("reviewed click window missing")
    elif start < w0 or end > w1:
        problems.append(f"proposal {start}..{end} exceeds lag-derived click window {w0}..{w1}")
    bounds = _window_bounds(elig.get("allowed_date_window"))
    if bounds and start and end and (start < bounds[0] or end > bounds[1]):
        problems.append(f"proposal {start}..{end} outside allowed_date_window {bounds[0]}..{bounds[1]}")
    for field in ("unaffected_data", "monitoring", "rollback_criteria", "ui_semantics_ref"):
        if not _s(p.get(field)):
            problems.append(f"proposal.{field} required")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
