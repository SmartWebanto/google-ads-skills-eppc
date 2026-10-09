"""check.py — skill-118 deterministic invalid-traffic rate, baseline, hourly and billing-case evidence review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-118-click-fraud-invalid-traffic-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #83 Pause campaigns with high invalid-click percentage (Daniel Hough, github hoofay/autoPauseCampaignsInvalidClicks)
         — clean-room reimplementation of the campaign invalid-click-rate threshold screen as check
         'invalid_rate_alert' (Info + request-only support-review observation); the pause action is refused.
rules:   Native invalid rate = invalid_clicks / (clicks + invalid_clicks); clicks = Ads (paid) clicks. NEVER invalid/paid.
         denominator_definition tokens: NATIVE_DEFS → supplied invalid_click_rate has the native denominator
         (cross-checked; may derive invalid_clicks when the count is empty); PAID_DEFS → supplied rate is
         invalid/paid clicks and is ignored, native rate recomputed from counts; any other value → row unknown (partial).
         Grain campaign_id/date/network: duplicate grain rows are excluded; ALL/TOTAL network rows beside segment rows
         are dropped (no double counting); dates after period_end are incomplete days and excluded.
         Recent window = account period; baseline = the 8 complete weeks (56 days) immediately before period_start,
         weekday-matched per campaign × network (expected = Σ recent weekday denominator × baseline weekday rate).
         Absent cohort-days count as zero only when the manifest certifies invalid_click_daily complete AND every window
         date appears in the file; otherwise the comparison is partial. Cohorts with any excluded row are not compared.
         Sample gates on BOTH sides: min_clicks on the native denominator for invalid rate, min_impressions for CTR.
         Business tolerances are profile-only fractions (absent/invalid → partial, no finding):
           profile.invalid_click_rate_alert  0<x<1 absolute native rate per campaign (index #83),
           profile.invalid_rate_change_alert x>0 relative increase of recent native rate vs weekday baseline,
           profile.ctr_change_alert          x>0 relative increase of recent CTR vs weekday baseline.
         Filtered-invalid / CTR signals are Info only ('Elevated filtered-invalid rate or CTR alone'); filtered clicks are
         not billed fraud; never a pause or exclusion proposal.
         Hourly bursts come only from external/traffic_incidents buckets with 0 < duration <= 60 min and a
         collection_authorization_ref; privacy_safe_source_id that looks like a raw IPv4/IPv6/e-mail → row refused.
         suspicious_behavior is supplied evidence; location_basis never proves bad actors. Daily rows never establish bursts.
         Billing: case grain; account credits are NEVER allocated to campaigns; residual = confirmed_charged_invalid_amount −
         invalid_activity_credit, only for rows in the account currency. Material = residual >= spend_floor (account-level).
         Critical deterministic only when case_status ∈ AUTHORITATIVE, evidence_ref present, checked_at >= service_end,
         credit and confirmed known, confirmed <= billed_cost (when known) and residual material; other confirmed
         cases → review whose Critical outcome needs proposal.case_id = reviewed case and proposal.evidence_ref naming a
         supplied billing evidence_ref.
         Warning deterministic: case_status ∈ UNRESOLVED with a charge link (billed_cost > 0 or an incident charge_link_ref
         naming the case), or a suspicious hourly incident whose charge_link_ref matches no case in a manifest-complete
         billing table. Unlinked suspicious activity / unlinked open cases are Info (insufficient evidence).
         verify(): rejects pause/exclusion/auto-apply/data-transmission proposals anywhere; control proposals need
         request_only true, control_type vendor|ip|geo, scope within pack campaigns, relevance_evidence_ref from supplied
         billing/incident refs (never a location), privacy_review_ref (a supplied collection_authorization_ref for ip/vendor),
         supported_control_ref, approval_owner, monitoring and recovery.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-118-click-fraud-invalid-traffic-monitoring"
VERSION = "1.0.0"

DAILY = "custom/invalid_click_daily"
BILL = "external/invalid_traffic_billing"
INC = "external/traffic_incidents"
DAILY_NEEDS = ["campaign_id", "date", "network", "clicks", "invalid_clicks", "denominator_definition"]
BILL_NEEDS = ["adjustment_or_case_id", "service_start", "service_end", "billed_cost", "invalid_activity_credit",
              "currency", "case_status", "confirmed_charged_invalid_amount", "evidence_ref", "checked_at"]
INC_NEEDS = ["incident_id", "campaign_id", "bucket_start", "bucket_end", "timezone", "clicks", "suspicious_behavior",
             "collection_authorization_ref"]

NATIVE_DEFS = {"clicks_plus_invalid_clicks", "total_clicks_including_invalid", "filtered_plus_unfiltered_clicks",
               "native"}
PAID_DEFS = {"clicks", "paid_clicks", "valid_clicks", "billable_clicks", "charged_clicks"}
TOTAL_NETS = {"all", "total", "all_networks"}
AUTHORITATIVE = {"confirmed", "closed", "resolved", "credited", "closed_confirmed", "confirmed_closed"}
UNRESOLVED = {"open", "pending", "new", "submitted", "in_review", "under_review", "investigating", "escalated",
              "awaiting_response"}
NOT_SUSPICIOUS = {"", "none", "no", "false", "0", "normal"}
BASELINE_DAYS = 56
RATE_TOLERANCE = 0.005  # supplied vs recomputed native rate (fraction); larger gaps mark the row inconsistent
CENT = 0.005
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d+)?$")
_IPV6 = re.compile(r"^[0-9a-f]*:[0-9a-f]*:[0-9a-f:.]*$", re.I)
_FORBIDDEN_ACTIONS = {"pause", "pause_campaign", "pause_campaigns", "exclude", "exclusion", "add_exclusion",
                      "auto_exclude", "block", "remove", "disable"}
_FORBIDDEN_FLAGS = {"pause", "auto_apply", "apply_automatically", "transmit_data", "upload", "send_to_vendor"}


def _token(v) -> str:
    return "_".join(str(v or "").strip().lower().replace("+", " plus ").replace("-", " ").split())


def _definition(v) -> str | None:
    t = _token(v)
    return "native" if t in NATIVE_DEFS else "paid" if t in PAID_DEFS else None


def _dt(v):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _profile_fraction(ctx, key: str, below_one: bool) -> tuple[float | None, str]:
    raw = ctx.profile.get(key)
    if raw is None:
        return None, f"profile.{key} not declared (business tolerance required)"
    v = V.rate(raw, "fraction")
    if v is None or v <= 0 or (below_one and v >= 1):
        return None, f"profile.{key}={raw!r} invalid ({'0<x<1' if below_one else 'x>0'} fraction required)"
    return v, f"profile.{key}"


# ---------------------------------------------------------------------- daily invalid-click report
def _parse_row(ctx, r: dict, has_rate: bool, has_impr: bool) -> dict | str:
    kind = _definition(r.get("denominator_definition"))
    if kind is None:
        return "unknown denominator_definition (native denominator undecidable)"
    clicks, inv = V.num(r.get("clicks")), V.num(r.get("invalid_clicks"))
    supplied = ctx.rate(r.get("invalid_click_rate")) if has_rate else None
    if clicks is None or clicks < 0:
        return "unknown clicks"
    rec = {"kind": kind, "derived": False, "rejected_rate": False, "mismatch": False}
    if inv is None:
        if kind == "native" and supplied is not None and 0 <= supplied < 1:
            inv, rec["derived"] = supplied * clicks / (1 - supplied), True
        else:
            return "unknown invalid_clicks (no native rate to derive it from)"
    if inv < 0:
        return "negative invalid_clicks"
    rate = V.ratio(inv, clicks + inv)
    if supplied is not None:
        if kind == "paid":
            rec["rejected_rate"] = True
        elif not rec["derived"] and rate is not None and abs(supplied - rate) > RATE_TOLERANCE:
            rec["mismatch"] = True
    rec.update(clicks=clicks, inv=inv, den=clicks + inv, impr=V.num(r.get("impressions")) if has_impr else None)
    return rec


def _load_daily(ctx):
    """Parse the daily report. Returns (records, bad cohort-days, exclusion notes, dates present)."""
    t = ctx.table(DAILY)
    has_rate, has_impr = "invalid_click_rate" in t.columns, "impressions" in t.columns
    groups: dict = {}
    notes: Counter = Counter()
    for r in t.rows:
        d, cid, net = V.parse_date(r.get("date")), str(r.get("campaign_id") or ""), str(r.get("network") or "").strip()
        if d is None or not cid or not net:
            notes["rows without campaign_id/date/network excluded"] += 1
            continue
        groups.setdefault((cid, d), {}).setdefault(net, []).append(r)
    records, bad, dates = [], set(), set()
    for (cid, d), nets in sorted(groups.items()):
        if ctx.period_end is not None and d > ctx.period_end:
            notes["rows after period end (incomplete days) excluded"] += sum(len(v) for v in nets.values())
            continue
        dates.add(d)
        segmented = any(_token(n) not in TOTAL_NETS for n in nets)
        for net, rows in sorted(nets.items()):
            if _token(net) in TOTAL_NETS and segmented:
                notes["ALL/TOTAL network rows beside segment rows dropped (double counting)"] += len(rows)
                continue
            if len(rows) > 1:
                notes["duplicate campaign/date/network rows excluded"] += len(rows)
                bad.add((cid, net, d))
                continue
            rec = _parse_row(ctx, rows[0], has_rate, has_impr)
            if isinstance(rec, str):
                notes[rec] += 1
                bad.add((cid, net, d))
                continue
            rec.update(cid=cid, net=net, day=d)
            records.append(rec)
    return records, bad, notes, dates, has_rate, has_impr


def _aggregate(records, key, lo, hi) -> dict:
    out: dict = {}
    for x in records:
        if not (lo <= x["day"] <= hi):
            continue
        a = out.setdefault(key(x), {"clicks": 0.0, "inv": 0.0, "den": 0.0, "impr": 0.0, "impr_unknown": 0,
                                    "days": set(), "wd": {}, "derived": 0, "rejected_rate": 0, "mismatch": 0,
                                    "defs": set()})
        a["clicks"] += x["clicks"]
        a["inv"] += x["inv"]
        a["den"] += x["den"]
        a["days"].add(x["day"])
        a["defs"].add(x["kind"])
        for flag in ("derived", "rejected_rate", "mismatch"):
            a[flag] += 1 if x[flag] else 0
        w = a["wd"].setdefault(x["day"].weekday(), [0.0, 0.0, 0.0, 0.0])
        w[0] += x["inv"]
        w[1] += x["den"]
        w[2] += x["clicks"]
        if x["impr"] is None:
            a["impr_unknown"] += 1
        else:
            a["impr"] += x["impr"]
            w[3] += x["impr"]
    return out


def _tainted(bad, lo, hi, cid, net=None) -> bool:
    return any(b[0] == cid and (net is None or b[1] == net) and lo <= b[2] <= hi for b in bad)


def _expected(recent_wd: dict, base_wd: dict, num_i: int, den_i: int) -> float | None:
    """Weekday-mix-adjusted expectation Σ recent_den[wd] × base_num[wd]/base_den[wd]; None if a weekday lacks a base."""
    exp = 0.0
    for wd, r in sorted(recent_wd.items()):
        if not r[den_i]:
            continue
        b = base_wd.get(wd)
        rate = V.ratio(b[num_i], b[den_i]) if b else None
        if rate is None:
            return None
        exp += r[den_i] * rate
    return exp


def _window_dates(lo, hi) -> set:
    return {lo + timedelta(days=i) for i in range((hi - lo).days + 1)}


# ---------------------------------------------------------------------- external evidence
def _load_incidents(ctx, chk, account_tz):
    """Validated hourly buckets grouped per (incident_id, campaign_id)."""
    t = ctx.table(INC)
    has_link = "charge_link_ref" in t.columns
    if not has_link:
        chk.partial("charge linkage unknown for every incident", [f"{INC}:charge_link_ref"])
    notes: Counter = Counter()
    seen: Counter = Counter((str(r.get("incident_id") or ""), str(r.get("time_bucket") or r.get("bucket_start") or ""),
                             str(r.get("campaign_id") or "")) for r in t.rows)
    groups: dict = {}
    for r in sorted(t.rows, key=lambda r: (str(r.get("incident_id") or ""), str(r.get("campaign_id") or ""),
                                           str(r.get("bucket_start") or ""))):
        iid, cid = str(r.get("incident_id") or ""), str(r.get("campaign_id") or "")
        grain = (iid, str(r.get("time_bucket") or r.get("bucket_start") or ""), cid)
        if not iid or not cid:
            notes["rows without incident_id/campaign_id"] += 1
            continue
        if seen[grain] > 1:
            notes["duplicate incident/time_bucket/campaign rows excluded"] += 1
            continue
        src = str(r.get("privacy_safe_source_id") or "").strip()
        if src and (_IPV4.match(src) or _IPV6.match(src) or "@" in src):
            notes["raw IP/e-mail in privacy_safe_source_id: row refused (no personal data)"] += 1
            continue
        if not r.get("collection_authorization_ref"):
            notes["no collection_authorization_ref: row not used"] += 1
            continue
        start, end = _dt(r.get("bucket_start")), _dt(r.get("bucket_end"))
        try:
            secs = (end - start).total_seconds() if start and end else None
        except TypeError:
            secs = None
        if secs is None or not (0 < secs <= 3600):
            notes["bucket not an hourly observation (unparseable or > 60 min): cannot establish a burst"] += 1
            continue
        clicks = V.num(r.get("clicks"))
        if clicks is None:
            notes["unknown bucket clicks"] += 1
            continue
        tz_ok = bool(account_tz) and str(r.get("timezone") or "") == account_tz
        if not tz_ok:
            notes["bucket timezone differs from/unknown vs account time zone: not aligned to daily report"] += 1
        g = groups.setdefault((iid, cid), {"buckets": [], "clicks": 0.0, "suspicious": set(), "links": set(),
                                           "auth": set(), "locations": set(), "tz_aligned": True})
        g["buckets"].append({"start": start.isoformat(), "end": end.isoformat(), "clicks": clicks,
                             "suspicious_behavior": r.get("suspicious_behavior")})
        g["clicks"] += clicks
        g["tz_aligned"] = g["tz_aligned"] and tz_ok
        g["auth"].add(str(r.get("collection_authorization_ref")))
        if r.get("location_basis"):
            g["locations"].add(str(r.get("location_basis")))
        if _token(r.get("suspicious_behavior")) not in NOT_SUSPICIOUS:
            g["suspicious"].add(str(r.get("suspicious_behavior")))
            if has_link and r.get("charge_link_ref"):
                g["links"].add(str(r.get("charge_link_ref")))
    for n, k in sorted(notes.items()):
        chk.partial(f"{k} {n}")
    return groups, has_link


def _load_cases(ctx, chk):
    t = ctx.table(BILL)
    ids = Counter(str(r.get("adjustment_or_case_id") or "") for r in t.rows)
    cases = {}
    for r in t.rows:
        cid = str(r.get("adjustment_or_case_id") or "")
        if not cid:
            chk.partial("billing row without adjustment_or_case_id excluded")
            continue
        if ids[cid] > 1:
            continue
        status = _token(r.get("case_status"))
        cases[cid] = {
            "case_id": cid, "row": r,
            "status": r.get("case_status"),
            "kind": "authoritative" if status in AUTHORITATIVE else "unresolved" if status in UNRESOLVED else None,
            "billed": ctx.money(r.get("billed_cost")), "credit": ctx.money(r.get("invalid_activity_credit")),
            "confirmed": ctx.money(r.get("confirmed_charged_invalid_amount")),
            "currency_ok": str(r.get("currency") or "").upper() == (ctx.currency or "") and bool(ctx.currency),
            "service_start": V.parse_date(r.get("service_start")), "service_end": V.parse_date(r.get("service_end")),
            "checked_at": V.parse_date(r.get("checked_at")), "evidence_ref": r.get("evidence_ref"),
            "incidents": [],
        }
    for cid in sorted(k for k, n in ids.items() if n > 1 and k):
        chk.partial(f"case {cid}: duplicate rows at case grain excluded")
    return cases


def _complete(t) -> bool:
    return t is not None and t.complete is True and not t.truncated


# ---------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run native invalid-rate, weekday baseline, rate alert, hourly burst, billing and support-pack checks.

    Rules:   Unknown account period skips daily checks. Rate/CTR/baseline alerts need profile tolerances and both-sided
             min_clicks/min_impressions and are Info only; daily rows never create bursts. Warning only for unresolved
             charge-linked cases/incidents (complete billing); Critical only for authoritative material residual >=
             spend_floor, else ai_review. Never pause/exclusion; control proposals only via ai_review, request-only.
    """
    pack: list[dict] = []
    ps, pe = ctx.period_start, ctx.period_end
    min_clicks, min_impr = ctx.params.get("min_clicks"), ctx.params.get("min_impressions")

    # -- step 1: native invalid-click denominator
    native = ctx.check("native_invalid_rate", "Native invalid-click rate per campaign and network", {DAILY: DAILY_NEEDS})
    daily_ok = native.runnable and ps is not None and pe is not None
    if native.runnable and not daily_ok:
        native.skip("account period unknown: recent window undefined", ["account:date_range_start", "account:date_range_end"])
    records, bad, dates, has_impr, recent = [], set(), set(), False, {}
    if daily_ok:
        records, bad, notes, dates, has_rate, has_impr = _load_daily(ctx)
        for k, n in sorted(notes.items()):
            native.partial(f"{k}: {n}")
        if not has_rate:
            native.observe("Supplied invalid_click_rate column absent: native rate recomputed from counts only",
                           missing=f"{DAILY}:invalid_click_rate")
        missing_days = sorted(_window_dates(ps, pe) - dates)
        if missing_days:
            native.partial(f"{len(missing_days)} recent-window dates absent from the report "
                           f"(first {missing_days[0]}): rates cover fewer days")
        recent = _aggregate(records, lambda x: (x["cid"], x["net"]), ps, pe)
        for (cid, net), a in sorted(recent.items()):
            native.observe(f"Campaign {cid} / {net}: native invalid-click rate", campaign_id=cid, network=net,
                           window=[ps, pe], clicks=a["clicks"], invalid_clicks=a["inv"], native_denominator=a["den"],
                           native_invalid_rate=V.ratio(a["inv"], a["den"]), days=len(a["days"]),
                           denominator_definitions=sorted(a["defs"]), derived_invalid_rows=a["derived"],
                           rejected_paid_click_rates=a["rejected_rate"], inconsistent_supplied_rates=a["mismatch"],
                           tainted=_tainted(bad, ps, pe, cid, net))
            if a["rejected_rate"]:
                native.observe(f"Campaign {cid} / {net}: supplied rate used paid clicks as denominator; ignored",
                               campaign_id=cid, network=net, rows=a["rejected_rate"])
            if a["mismatch"]:
                native.partial(f"campaign {cid}/{net}: {a['mismatch']} rows where supplied native rate disagrees "
                               f"with counts by > {RATE_TOLERANCE:g}; counts used")
        camps = ctx.table("campaigns")
        ids = {cid for cid, _ in recent}
        if camps is None or "id" in camps.missing(["id"]):
            native.partial("campaign IDs not joinable to campaign inventory", ["campaigns:id"])
        else:
            unknown = sorted(ids - {str(r.get("id")) for r in camps.rows})
            if unknown:
                native.partial(f"campaign IDs absent from campaigns.csv: {unknown}")
        cm = ctx.table("campaign_metrics")
        if cm is not None and not cm.missing(["campaign_id", "clicks"]) and "date" not in cm.columns:
            per = Counter(str(r.get("campaign_id")) for r in cm.rows)
            for r in sorted(cm.rows, key=lambda r: str(r.get("campaign_id"))):
                cid = str(r.get("campaign_id"))
                if cid in {c for c, _ in recent} and per[cid] == 1:
                    report = sum(a["clicks"] for (c, _), a in recent.items() if c == cid)
                    native.observe(f"Campaign {cid}: invalid-click report clicks vs campaign_metrics clicks",
                                   campaign_id=cid, report_clicks=report, campaign_metrics_clicks=V.num(r.get("clicks")),
                                   click_share=V.ratio(report, V.num(r.get("clicks"))))

    # -- step 2: complete weekday/network baselines
    base = ctx.check("weekday_network_baseline", "Recent vs 8-complete-week weekday/network baseline")
    if not daily_ok:
        base.skip("native invalid-click report unavailable", native.missing or [f"{DAILY} (file)"])
    else:
        _baseline(ctx, base, records, bad, dates, has_impr, recent, min_clicks, min_impr, pack)

    # -- index #83: campaign invalid-click rate above a declared threshold
    alert = ctx.check("invalid_rate_alert", "Campaign native invalid-click rate above declared alert (index #83)")
    if not daily_ok:
        alert.skip("native invalid-click report unavailable", native.missing or [f"{DAILY} (file)"])
    else:
        _rate_alert(ctx, alert, records, bad, min_clicks, pack)

    # -- external evidence (parsed once; emitted by their own checks)
    hourly = ctx.check("hourly_bursts", "Authorized hourly incident buckets", {INC: INC_NEEDS})
    billing = ctx.check("billing_reconciliation", "Case-level billed / credited / confirmed charged-invalid reconciliation",
                        {BILL: BILL_NEEDS})
    groups, has_link = (_load_incidents(ctx, hourly, ctx.account.get("time_zone")) if hourly.runnable else ({}, False))
    cases = _load_cases(ctx, billing) if billing.runnable else {}
    bill_complete = billing.runnable and _complete(ctx.table(BILL))
    refs_to_case = {}
    for cid, c in sorted(cases.items()):
        refs_to_case[cid] = cid
        if c["evidence_ref"]:
            refs_to_case.setdefault(str(c["evidence_ref"]), cid)

    # -- step 3: hourly bursts
    if hourly.runnable:
        _hourly(ctx, hourly, groups, has_link, cases, refs_to_case, billing.runnable, bill_complete, records, pack)
    else:
        hourly.notes.append("daily rows cannot establish hourly bursts; no hourly observations invented")

    # -- step 4: billing reconciliation
    if billing.runnable:
        _billing(ctx, billing, cases, records, pack)

    # -- step 5: support-review pack
    _pack(ctx, pack, groups, cases, [native, base, alert, hourly, billing])


def _baseline(ctx, chk, records, bad, dates, has_impr, recent, min_clicks, min_impr, pack) -> None:
    ps, pe = ctx.period_start, ctx.period_end
    lo, hi = ps - timedelta(days=BASELINE_DAYS), ps - timedelta(days=1)
    t = ctx.table(DAILY)
    gaps = sorted((_window_dates(lo, hi) | _window_dates(ps, pe)) - dates)
    if gaps:
        chk.partial(f"{len(gaps)} dates of the 8-week baseline/recent windows absent (first {gaps[0]}): "
                    f"weeks not complete", [f"{DAILY}:date {lo}..{pe}"])
        return
    if not _complete(t):
        chk.partial("manifest does not certify invalid_click_daily complete: absent cohort-days cannot be zero")
        return
    inv_alert, inv_src = _profile_fraction(ctx, "invalid_rate_change_alert", False)
    ctr_alert, ctr_src = _profile_fraction(ctx, "ctr_change_alert", False)
    for a, src in ((inv_alert, inv_src), (ctr_alert, ctr_src)):
        if a is None:
            chk.partial(f"{src}: comparisons reported without a finding")
    if not has_impr:
        chk.partial("CTR baseline unavailable", [f"{DAILY}:impressions"])
    if min_clicks.value is None or min_impr.value is None:
        chk.partial("sample gates unresolved")
        return
    baseline = _aggregate(records, lambda x: (x["cid"], x["net"]), lo, hi)
    for key in sorted(set(recent) | set(baseline)):
        cid, net = key
        if _tainted(bad, lo, pe, cid, net):
            chk.partial(f"campaign {cid}/{net}: excluded rows inside the windows; not compared")
            continue
        r = recent.get(key)
        b = baseline.get(key)
        if r is None or b is None:
            chk.observe(f"Campaign {cid} / {net}: no traffic in one window; no comparison", campaign_id=cid,
                        network=net, recent_denominator=r["den"] if r else 0, baseline_denominator=b["den"] if b else 0)
            continue
        ev = {"recent_window": [ps, pe], "baseline_window": [lo, hi], "weekday_matched": True,
              "recent_native_denominator": r["den"], "baseline_native_denominator": b["den"],
              "recent_invalid_clicks": r["inv"], "baseline_invalid_clicks": b["inv"],
              "min_clicks": min_clicks.value, "min_clicks_source": min_clicks.source}
        exp_inv = _expected(r["wd"], b["wd"], 0, 1)
        obs_rate, exp_rate = V.ratio(r["inv"], r["den"]), V.ratio(exp_inv, r["den"])
        change = None if obs_rate is None or not exp_rate else obs_rate / exp_rate - 1
        inv_gate = r["den"] >= min_clicks.value and b["den"] >= min_clicks.value
        ev.update(recent_native_invalid_rate=obs_rate, weekday_expected_invalid_rate=exp_rate,
                  invalid_rate_relative_change=change, invalid_sample_gate_passed=inv_gate)
        ctr_ev = {}
        if has_impr and not r["impr_unknown"] and not b["impr_unknown"]:
            exp_clicks = _expected(r["wd"], b["wd"], 2, 3)
            obs_ctr, exp_ctr = V.ratio(r["clicks"], r["impr"]), V.ratio(exp_clicks, r["impr"])
            ctr_change = None if obs_ctr is None or not exp_ctr else obs_ctr / exp_ctr - 1
            ctr_gate = r["impr"] >= min_impr.value and b["impr"] >= min_impr.value
            ctr_ev = {"recent_impressions": r["impr"], "baseline_impressions": b["impr"], "recent_ctr": obs_ctr,
                      "weekday_expected_ctr": exp_ctr, "ctr_relative_change": ctr_change, "ctr_sample_gate_passed": ctr_gate,
                      "min_impressions": min_impr.value, "min_impressions_source": min_impr.source}
        elif has_impr:
            chk.partial(f"campaign {cid}/{net}: unknown impressions in a window; CTR not compared")
        chk.observe(f"Campaign {cid} / {net}: weekday baseline comparison", campaign_id=cid, network=net, **ev, **ctr_ev)
        entity = {"campaign_id": cid, "network": net}
        reasons = []
        if inv_alert is not None and inv_gate and change is not None and change >= inv_alert:
            reasons.append(("elevated_filtered_invalid_rate_vs_baseline", "native invalid rate", change, inv_alert, inv_src))
        if ctr_alert is not None and ctr_ev.get("ctr_sample_gate_passed") and ctr_ev.get("ctr_relative_change") is not None \
                and ctr_ev["ctr_relative_change"] >= ctr_alert:
            reasons.append(("elevated_ctr_vs_baseline", "CTR", ctr_ev["ctr_relative_change"], ctr_alert, ctr_src))
        for key_c, label, ch, thr, src in reasons:
            chk.finding(key_c, "Info", entity,
                        f"Campaign {cid} / {net}: {label} {ch:+.1%} vs weekday-matched 8-week baseline "
                        f"(alert {thr:g} from {src})",
                        evidence={**ev, **ctr_ev, "alert": thr, "alert_source": src},
                        calculation={"expected": "Σ recent weekday denominator × baseline weekday rate",
                                     "relative_change": "observed / expected − 1"},
                        recommendation="Check brand terms, promotions and traffic mix for these dates; include in the "
                                       "support-review request if unexplained. No pause or exclusion.",
                        uncertainty="Elevated filtered-invalid rate or CTR alone: filtered clicks are not billed; "
                                    "observational change, not proof of fraud.")
            pack.append({"kind": key_c, "campaign_ids": [cid], "network": net, "dates": [ps, pe],
                         "evidence_refs": [f"{DAILY}.csv {cid}/{net} {ps}..{pe}"], "observed": {label: ch},
                         "uncertainty": "filtered traffic; traffic-mix explanations not excluded"})


def _rate_alert(ctx, chk, records, bad, min_clicks, pack) -> None:
    ps, pe = ctx.period_start, ctx.period_end
    thr, src = _profile_fraction(ctx, "invalid_click_rate_alert", True)
    if thr is None:
        chk.partial(f"{src}: no alert findings")
        return
    if min_clicks.value is None:
        chk.partial(f"min_clicks unresolved: {min_clicks.reason}")
        return
    per = _aggregate(records, lambda x: x["cid"], ps, pe)
    for cid, a in sorted(per.items()):
        if _tainted(bad, ps, pe, cid):
            chk.partial(f"campaign {cid}: excluded rows in the window; campaign rate not screened")
            continue
        rate = V.ratio(a["inv"], a["den"])
        ev = {"window": [ps, pe], "days": len(a["days"]), "clicks": a["clicks"], "invalid_clicks": a["inv"],
              "native_denominator": a["den"], "native_invalid_rate": rate, "alert": thr, "alert_source": src,
              "min_clicks": min_clicks.value, "min_clicks_source": min_clicks.source}
        if a["den"] < min_clicks.value or rate is None:
            chk.observe(f"Campaign {cid}: native denominator below min_clicks; not screened", campaign_id=cid, **ev)
            continue
        chk.observe(f"Campaign {cid}: native invalid rate screened against alert", campaign_id=cid, **ev)
        if rate >= thr:
            chk.finding("elevated_filtered_invalid_rate", "Info", {"campaign_id": cid},
                        f"Campaign {cid}: native invalid-click rate {rate:.1%} >= alert {thr:.1%} ({src}) over "
                        f"{a['den']:g} native clicks {ps}..{pe}",
                        evidence=ev, calculation={"native_invalid_rate": "invalid_clicks / (clicks + invalid_clicks)"},
                        recommendation="Add the campaign and dates to the request-only support-review pack; do not "
                                       "pause the campaign on a filtered-invalid rate.",
                        uncertainty="Filtered invalid clicks were not billed; an elevated rate alone does not show "
                                    "charged fraud.")
            chk.observe(f"Campaign {cid}: support-review request (request-only, no pause)", campaign_id=cid,
                        window=[ps, pe], native_invalid_rate=rate, request="ask Google Ads support to review the dates")
            pack.append({"kind": "elevated_filtered_invalid_rate", "campaign_ids": [cid], "dates": [ps, pe],
                         "evidence_refs": [f"{DAILY}.csv {cid} {ps}..{pe}"], "observed": {"native_invalid_rate": rate},
                         "uncertainty": "filtered, unbilled clicks"})


def _hourly(ctx, chk, groups, has_link, cases, refs_to_case, bill_runnable, bill_complete, records, pack) -> None:
    by_day: dict = {}
    for x in records:
        acc = by_day.setdefault((x["cid"], x["day"]), [0.0, 0.0])
        acc[0] += x["clicks"]
        acc[1] += x["inv"]
    suspicious = 0
    for (iid, cid), g in sorted(groups.items()):
        entity = {"incident_id": iid, "campaign_id": cid}
        days = sorted({b["start"][:10] for b in g["buckets"]})
        day_ctx = {d: by_day.get((cid, V.parse_date(d))) for d in days} if g["tz_aligned"] else {}
        ev = {"buckets": g["buckets"], "bucket_clicks": g["clicks"], "suspicious_behavior": sorted(g["suspicious"]),
              "charge_link_refs": sorted(g["links"]), "collection_authorization_refs": sorted(g["auth"]),
              "location_basis": sorted(g["locations"]),
              "ads_day_clicks_invalid": {d: v for d, v in day_ctx.items() if v is not None}}
        chk.observe(f"Incident {iid} / campaign {cid}: authorized hourly buckets", **entity, buckets=len(g["buckets"]),
                    bucket_clicks=g["clicks"], suspicious=bool(g["suspicious"]))
        if not g["suspicious"]:
            continue
        suspicious += 1
        linked = sorted({refs_to_case[r] for r in g["links"] if r in refs_to_case})
        unmatched = sorted(r for r in g["links"] if r not in refs_to_case)
        for case_id in linked:
            cases[case_id]["incidents"].append(iid)
        entry = {"kind": "suspicious_hourly_activity", "campaign_ids": [cid], "incident_id": iid, "dates": days,
                 "evidence_refs": sorted(g["links"] | g["auth"]), "case_ids": linked,
                 "observed": {"bucket_clicks": g["clicks"], "buckets": len(g["buckets"])},
                 "uncertainty": "supplied behavior labels; location does not prove bad actors"}
        pack.append(entry)
        if linked and not unmatched:
            chk.observe(f"Incident {iid}: charge link resolves to billing case(s) {linked}", **entity, case_ids=linked)
            continue
        if unmatched and bill_complete:
            chk.finding("unresolved_billing_linked_suspicious_activity", "Warning", entity,
                        f"Incident {iid} (campaign {cid}): suspicious hourly activity linked to charges {unmatched} "
                        f"with no invalid-traffic case or credit in the complete billing evidence",
                        evidence=ev, recommendation="Open or cite a support/billing case for these dated charges; "
                                                    "request-only, no exclusion.",
                        uncertainty="Charge linkage is supplied evidence; Google may still classify the clicks as valid.")
        elif unmatched:
            chk.partial(f"incident {iid}: charge link {unmatched} cannot be resolved; billing evidence "
                        f"{'incomplete' if bill_runnable else 'missing'}", [] if bill_runnable else [f"{BILL} (file)"])
            chk.finding("suspicious_activity_resolution_unknown", "Info", entity,
                        f"Incident {iid} (campaign {cid}): suspicious hourly activity linked to charges {unmatched}; "
                        f"case resolution not evidenced", evidence=ev,
                        recommendation="Supply the billing/case record for these charges.",
                        uncertainty="Insufficient evidence: unresolved status cannot be proven from absent billing rows.")
        else:
            chk.finding("suspicious_activity_without_charge_link", "Info", entity,
                        f"Incident {iid} (campaign {cid}): suspicious hourly activity with no charge link",
                        evidence=ev, recommendation="Include in the support-review pack; no exclusion.",
                        uncertainty="Insufficient evidence: no billed-charge linkage; suspicion is a hypothesis.")
    chk.observe("Hourly incident totals", incident_groups=len(groups), suspicious_groups=suspicious)


def _billing(ctx, chk, cases, records, pack) -> None:
    floor = ctx.params.get("spend_floor")
    if floor.value is None:
        chk.partial(f"spend_floor unresolved ({floor.reason}): materiality undecidable")
    totals = {"billed": 0.0, "credit": 0.0, "confirmed": 0.0, "residual": 0.0, "suspected_paid_exposure": 0.0,
              "unknown_amounts": 0, "other_currency_cases": 0}
    for case_id, c in sorted(cases.items()):
        entity = {"case_id": case_id}
        residual = None if c["confirmed"] is None or c["credit"] is None else c["confirmed"] - c["credit"]
        ev = {"service_period": [c["service_start"], c["service_end"]], "billed_cost": c["billed"],
              "invalid_activity_credit": c["credit"], "confirmed_charged_invalid_amount": c["confirmed"],
              "residual_after_credits": residual, "case_status": c["status"], "currency": c["row"].get("currency"),
              "account_currency": ctx.currency, "evidence_ref": c["evidence_ref"], "checked_at": c["checked_at"],
              "linked_incidents": sorted(c["incidents"]), "spend_floor": floor.value, "spend_floor_source": floor.source,
              "allocation": "account/case level; credits not allocated to campaigns"}
        if not c["currency_ok"]:
            totals["other_currency_cases"] += 1
            chk.partial(f"case {case_id}: currency {c['row'].get('currency')!r} is not account currency "
                        f"{ctx.currency}; amounts excluded")
        else:
            for k in ("billed", "credit", "confirmed"):
                if c[k] is None:
                    totals["unknown_amounts"] += 1
                else:
                    totals[k] += c[k]
            if residual is not None:
                totals["residual"] += max(residual, 0.0)
            if c["kind"] == "unresolved" and c["billed"] is not None:
                totals["suspected_paid_exposure"] += c["billed"]
        chk.observe(f"Case {case_id}: charged / credited / confirmed reconciliation", **entity, **ev)
        entry = {"kind": "billing_case", "case_id": case_id, "campaign_ids": [], "dates": ev["service_period"],
                 "evidence_refs": [c["evidence_ref"]] if c["evidence_ref"] else [], "observed": {
                     "status": c["status"], "billed": c["billed"], "credit": c["credit"], "confirmed": c["confirmed"],
                     "residual": residual}, "linked_incidents": sorted(c["incidents"]),
                 "uncertainty": "case-level; no campaign allocation"}
        if c["kind"] == "unresolved":
            pack.append(entry)
            if (c["billed"] or 0) > 0 or c["incidents"]:
                chk.finding("unresolved_billing_linked_suspicious_activity", "Warning", entity,
                            f"Case {case_id} ({c['status']}): billing-linked suspicious activity unresolved "
                            f"(billed {c['billed']} {ctx.currency}, credit {c['credit']}, incidents {sorted(c['incidents'])})",
                            evidence=ev, recommendation="Follow up the open case with the dated charges and evidence "
                                                        "pack; request-only.",
                            uncertainty="Unresolved: billed cost is exposure, not a confirmed invalid charge or loss.")
            else:
                chk.finding("unresolved_case_without_charge_link", "Info", entity,
                            f"Case {case_id} ({c['status']}) is open without billed-charge linkage",
                            evidence=ev, recommendation="Attach the dated charges this case concerns.",
                            uncertainty="Insufficient evidence: no billed charge or incident linked.")
            continue
        if c["kind"] is None:
            chk.partial(f"case {case_id}: case_status {c['status']!r} not interpretable")
            if (c["billed"] or 0) > 0 or (c["confirmed"] or 0) > 0:
                pack.append(entry)
                _case_review(chk, entity, ev, unresolved_outcome=True,
                             gaps=[f"case_status {c['status']!r} not in authoritative/unresolved vocabularies"])
            continue
        if not c["confirmed"]:
            chk.observe(f"Case {case_id}: authoritative status without confirmed charged-invalid amount", **entity,
                        confirmed=c["confirmed"])
            continue
        gaps = []
        if not c["evidence_ref"]:
            gaps.append("evidence_ref missing")
        if c["checked_at"] is None or c["service_end"] is None or c["checked_at"] < c["service_end"]:
            gaps.append("checked_at not after service_end: later credits not excluded")
        if c["credit"] is None:
            gaps.append("invalid_activity_credit unknown")
        if c["billed"] is not None and c["confirmed"] > c["billed"] + CENT:
            gaps.append("confirmed amount exceeds billed_cost")
        if not c["currency_ok"]:
            gaps.append("currency differs from account")
        if residual is not None and residual <= CENT and c["credit"] is not None:
            chk.observe(f"Case {case_id}: confirmed charged-invalid amount fully credited", **entity, residual=residual)
            continue
        if floor.value is None:
            pack.append(entry)
            continue
        if residual is not None and residual < floor.value:
            chk.observe(f"Case {case_id}: confirmed residual below spend_floor (not material)", **entity,
                        residual=residual, spend_floor=floor.value)
            pack.append(entry)
            continue
        pack.append(entry)
        if not gaps:
            chk.finding("confirmed_material_charged_invalid_after_credits", "Critical", entity,
                        f"Case {case_id} ({c['status']}): confirmed charged invalid {c['confirmed']:.2f} minus credit "
                        f"{c['credit']:.2f} leaves {residual:.2f} {ctx.currency} >= spend_floor {floor.value:g}",
                        evidence=ev, calculation={"residual": "confirmed_charged_invalid_amount − invalid_activity_credit"},
                        recommendation="Request the outstanding credit citing the case evidence; request-only.",
                        uncertainty="Case-level amount; not allocated to campaigns; later credits after checked_at unknown.")
        else:
            chk.partial(f"case {case_id}: Critical not deterministic ({'; '.join(gaps)})")
            _case_review(chk, entity, ev, unresolved_outcome=False, gaps=gaps)
    chk.observe("Invalid-traffic layers (filtered vs suspected paid vs confirmed charged)",
                filtered_invalid_clicks=sum(x["inv"] for x in records
                                            if ctx.period_start and ctx.period_start <= x["day"] <= ctx.period_end),
                cases=len(cases), billed_total=totals["billed"], credit_total=totals["credit"],
                confirmed_total=totals["confirmed"], residual_after_credits_total=totals["residual"],
                suspected_paid_exposure=totals["suspected_paid_exposure"], unknown_amounts=totals["unknown_amounts"],
                other_currency_cases=totals["other_currency_cases"], currency=ctx.currency,
                note="exposure is not loss or savings")


def _case_review(chk, entity, ev, unresolved_outcome: bool, gaps: list[str]) -> None:
    outcomes = {
        "confirmed_material_after_credits": {"severity": "Critical", "recommendation":
                                             "Request the outstanding credit; cite proposal.evidence_ref."},
        "not_confirmed_or_not_material": {"severity": None, "recommendation": "No charged-invalid finding."},
        "uncertain": {"severity": "Info", "recommendation": "Obtain the authoritative case outcome and credit statement."},
    }
    if unresolved_outcome:
        outcomes["unresolved_billing_linked"] = {"severity": "Warning", "recommendation": "Follow up the open case."}
    chk.review("charged_invalid_case_review", entity,
               f"Does supplied evidence authoritatively confirm material charged invalid activity after credits for "
               f"case {entity['case_id']}? Gaps: {'; '.join(gaps)}",
               evidence={**ev, "gaps": gaps}, outcomes=outcomes,
               guidance="Critical needs proposal {case_id, evidence_ref} where evidence_ref is a supplied billing "
                        "evidence_ref; a support reply without an amount or credit statement is uncertain.")


def _pack(ctx, pack, groups, cases, upstream) -> None:
    chk = ctx.check("support_review_pack", "Request-only support-review evidence pack")
    if all(c.status == "skipped" for c in upstream):
        chk.skip("no invalid-traffic evidence to assemble", sorted({m for c in upstream for m in c.missing}))
        return
    open_checks = sorted(c.id for c in upstream if c.status not in (None, "completed"))
    for i, e in enumerate(pack):
        chk.observe(f"Support-review item {i + 1:02d}: {e['kind']} (request-only)", **e)
    campaigns = sorted({c for e in pack for c in e.get("campaign_ids", [])})
    chk.observe("Support-review pack summary", items=len(pack), campaign_ids=campaigns,
                non_completed_subchecks=open_checks, account_id=ctx.account_id,
                note="request-only: no account writes, exclusions, notifications or data transfers")
    if open_checks:
        chk.partial(f"pack depends on non-completed subchecks: {open_checks}")
    charged = [e for e in pack if e["kind"] in ("suspicious_hourly_activity", "billing_case")]
    if not charged:
        return
    refs = sorted({str(r) for e in charged for r in e.get("evidence_refs", []) if r}
                  | {str(c["evidence_ref"]) for c in cases.values() if c["evidence_ref"]}
                  | {str(r) for g in groups.values() for r in g["links"]})
    auth = sorted({a for g in groups.values() for a in g["auth"]})
    chk.review("control_proposal_review", {"batch": "invalid_traffic_controls"},
               "Is any vendor, IP or geographic control justified for owner review, with independent relevance, "
               "current supported controls and privacy review?",
               evidence={"items": charged, "campaign_ids": sorted({c for e in charged for c in e["campaign_ids"]}),
                         "evidence_refs": refs, "collection_authorization_refs": auth,
                         "location_basis": sorted({l for g in groups.values() for l in g["locations"]}),
                         "note": "location does not prove bad actors"},
               outcomes={"control_review_requested": {"severity": "Info", "recommendation":
                                                      "Send the verified control request to the named approval owner."},
                         "no_control_proposal": {"severity": None, "recommendation": "Support review only."},
                         "uncertain": {"severity": "Info", "recommendation": "Collect relevance/privacy evidence first."}},
               guidance="control_review_requested needs proposal.controls: [{control_type vendor|ip|geo, request_only: "
                        "true, scope_campaign_ids, relevance_evidence_ref (from evidence_refs), privacy_review_ref "
                        "(collection_authorization_ref for ip/vendor), supported_control_ref, approval_owner, "
                        "monitoring, recovery}]. No pause, automatic exclusion or data transmission.")


# ---------------------------------------------------------------------- verify
def _forbidden(proposal) -> list[str]:
    out: list[str] = []

    def walk(p):
        if isinstance(p, dict):
            for k, v in sorted(p.items(), key=lambda kv: str(kv[0])):
                kt = _token(k)
                if kt in ("action", "operation", "change") and _token(v) in _FORBIDDEN_ACTIONS:
                    out.append(f"'{v}' is an account mutation; this review is request-only (no pause/exclusion)")
                if kt in _FORBIDDEN_FLAGS and V.boolean(v) is True:
                    out.append(f"'{k}' not allowed: no pause, automatic change or data transmission")
                walk(v)
        elif isinstance(p, list):
            for x in p:
                walk(x)

    walk(proposal)
    return out


def verify(ctx, item, decision) -> list[str]:
    """Rules: request-only guard everywhere, Critical needs a supplied evidence_ref, controls
    need relevance/privacy/owner fields."""
    proposal = decision.get("proposal") or {}
    problems = _forbidden(proposal)
    outcome = decision.get("outcome")
    spec = item.outcomes.get(outcome) or {}
    if item.condition_key == "charged_invalid_case_review" and spec.get("severity") == "Critical":
        known = {str(r.get("evidence_ref")) for r in ctx.rows(BILL) if r.get("evidence_ref")}
        ref = str(proposal.get("evidence_ref") or "")
        if not ref:
            problems.append("Critical needs proposal.evidence_ref naming supplied billing evidence")
        elif ref not in known:
            problems.append(f"evidence_ref {ref!r} not present in {BILL}")
        if str(proposal.get("case_id") or "") != item.entity.get("case_id"):
            problems.append(f"proposal.case_id must equal reviewed case {item.entity.get('case_id')}")
    if item.condition_key == "control_proposal_review" and outcome == "control_review_requested":
        controls = proposal.get("controls")
        if not isinstance(controls, list) or not controls:
            return problems + ["proposal.controls (non-empty list) required"]
        scope_ok = set(item.evidence.get("campaign_ids") or [])
        refs, auth = set(item.evidence.get("evidence_refs") or []), set(item.evidence.get("collection_authorization_refs") or [])
        for i, c in enumerate(controls):
            c = c if isinstance(c, dict) else {}
            kind = _token(c.get("control_type"))
            p = f"controls[{i}]"
            if kind not in ("vendor", "ip", "geo"):
                problems.append(f"{p}: control_type must be vendor|ip|geo")
            if V.boolean(c.get("request_only")) is not True:
                problems.append(f"{p}: request_only must be true")
            scope = [str(x) for x in (c.get("scope_campaign_ids") or [])]
            if not scope or not set(scope) <= scope_ok:
                problems.append(f"{p}: scope_campaign_ids must be a non-empty subset of {sorted(scope_ok)}")
            if str(c.get("relevance_evidence_ref") or "") not in refs:
                problems.append(f"{p}: relevance_evidence_ref must be a supplied billing/incident ref (location is not proof)")
            priv = str(c.get("privacy_review_ref") or "")
            if not priv or (kind in ("ip", "vendor") and priv not in auth):
                problems.append(f"{p}: privacy_review_ref required"
                                + (" and must be a supplied collection_authorization_ref" if kind in ("ip", "vendor") else ""))
            for f in ("supported_control_ref", "approval_owner", "monitoring", "recovery"):
                if not str(c.get(f) or "").strip():
                    problems.append(f"{p}: {f} required")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
