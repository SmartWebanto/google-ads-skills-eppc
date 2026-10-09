"""check.py — skill-007 deterministic campaign settings vs documented delivery requirements.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-007-campaign-settings-hygiene/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #20 Check accounts for mistakes in setup and settings (Brainlabs) — clean-room reimplementation of
         worldwide/out-of-area geo targeting and settings-matrix screening, gated by the approved service area.
         index #46 Filter campaigns enabled but with end date in the past (kaugesaar) — clean-room reimplementation
         of ENABLED + end_date < as_of detection; reported as Info (possibly intentional), never revived.
         index #91 Check campaign settings (SergeyMatrosov) — clean-room reimplementation of expected-vs-actual
         setting comparison, driven only by external/campaign_requirements rows (no hardcoded expectations).
         index #9 (stale year in ad copy / out-of-stock pausing) NOT integrated: ads and stock evidence are not
         007 inputs and the script mutates ads.
rules:   'today' = ctx.as_of (never the clock); dates compare as account-timezone calendar dates.
         Missing column or empty cell = unknown, never false/disabled/"no languages"; that control is skipped.
         Requirements come only from external/campaign_requirements active at as_of (effective_start..end, open
         bounds allowed; empty or '*' campaign_id = every campaign). Profile service_area is the approved area.
         Deterministic Warning only for an explicit setting that differs from an explicit approved value.
         Geo names other than explicit worldwide values are literal and may be sub-regions → ai_review.
         Delivery-blocking conflicts (status/start/end vs an active 'required delivery' window) queue a Critical
         review; verify() demands proposal.evidence_ref of material impact. Info: expired end date, presence-or-
         interest, device exclusion without contrary requirement. Never propose removing a promotion end date:
         verify() rejects action 'remove_end_date' and revival needs approval_ref, dates, budget and creative.
         Smart Bidding + non-exclusion device CPC modifiers are observations (modifier not applied), not defects.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial deterministic check
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

SKILL = "skill-007-campaign-settings-hygiene"
VERSION = "1.0.0"

REQ = "external/campaign_requirements"
REQ_COLS = ["campaign_id", "requirement_type", "approved_value", "effective_start", "effective_end", "approval_ref", "owner"]
CONTROLS = ("status", "start_date", "end_date", "search_partners", "display_network", "geo_targets", "geo_target_method",
            "languages", "ad_schedule", "bidding_strategy_type")
BOOL_CONTROLS = ("search_partners", "display_network")
WORLDWIDE = {"worldwide", "all", "all countries and territories", "all countries"}
SMART = {"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"}
DEVICES = {"MOBILE", "DESKTOP", "TABLET", "CONNECTED_TV"}
LIST_SEPS = (" | ", ";", "|", ",")


def _cell(row, col):
    v = row.get(col)
    return None if v is None or str(v).strip().lower() in V.MISSING_TOKENS else v


def _list(v) -> list[str]:
    return [x.strip().lower() for x in V.split_list(v, LIST_SEPS)]


def _requirements(ctx, chk) -> dict[str, list[dict]]:
    """campaign_id → active requirement rows at as_of ('*' key = all campaigns)."""
    out: dict[str, list[dict]] = {}
    inactive = 0
    for r in sorted(ctx.rows(REQ), key=lambda r: (str(r.get("campaign_id")), str(r.get("requirement_type")))):
        s, e = V.parse_date(r.get("effective_start")), V.parse_date(r.get("effective_end"))
        if ctx.as_of is None:
            chk.partial("as_of unknown: requirement windows cannot be evaluated")
            return {}
        if (s and s > ctx.as_of) or (e and e < ctx.as_of):
            inactive += 1
            continue
        out.setdefault(str(r.get("campaign_id") or "*").strip() or "*", []).append(r)
    if inactive:
        chk.observe("Requirement rows outside their effective window at as_of", count=inactive, as_of=ctx.as_of)
    return out


def _reqs_for(reqs, cid, rtype) -> list[dict]:
    return [r for r in reqs.get(cid, []) + reqs.get("*", []) if str(r.get("requirement_type") or "").strip().lower() == rtype]


def _ev(r: dict) -> dict:
    return {"requirement_type": r.get("requirement_type"), "approved_value": r.get("approved_value"),
            "effective_start": r.get("effective_start"), "effective_end": r.get("effective_end"),
            "approval_ref": r.get("approval_ref"), "owner": r.get("owner")}


def run(ctx) -> None:
    """Run campaign-setting checks (geo, language, network, dates, status, devices) against as_of requirements.

    Rules:   Missing column/empty cell = unknown → that control is skipped, never treated as false/disabled.
             Deterministic Warning only when an explicit setting differs from an explicit active
             external/campaign_requirements value; geo outside profile service_area → ai_review; expired end date,
             presence-or-interest, device exclusion → Info. Delivery-blocking conflicts queue a Critical review;
             promotion revival is Info review, never 'remove end date'.
    """
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns") if str(c.get("status") or "").upper() != "REMOVED"}
    cols = set(ctx.table("campaigns").columns) if ctx.table("campaigns") else set()
    ts = (ctx.table("campaigns").manifest or {}).get("exported_at") if ctx.table("campaigns") else None
    as_of = ctx.as_of
    service_area = [str(x).strip().lower() for x in (ctx.profile.get("service_area") or [])]

    # -- step 2 (+ #20/#91): settings matrix, unknown distinguished from false
    mat = ctx.check("settings_matrix", "Settings matrix by channel and supported control",
                    {"campaigns": ["id", "channel_type", "status"]})
    if mat.runnable:
        absent = [c for c in CONTROLS if c not in cols]
        if absent:
            mat.partial("controls absent from export are unknown, not disabled", [f"campaigns:{c}" for c in absent])
        for cid in sorted(camps):
            c = camps[cid]
            mat.observe(f"Campaign {cid} settings", campaign_id=cid, channel=c.get("channel_type"),
                        settings={k: (_cell(c, k) if k in cols else "UNKNOWN(absent)") for k in CONTROLS},
                        unknown=[k for k in CONTROLS if k in cols and _cell(c, k) is None], settings_timestamp=ts)

    rq = ctx.check("requirements", "Active documented requirements at as_of", {REQ: REQ_COLS})
    reqs: dict[str, list[dict]] = {}
    if rq.runnable:
        reqs = _requirements(ctx, rq)
        unknown_ids = sorted(k for k in reqs if k != "*" and k not in camps)
        if unknown_ids:
            rq.partial(f"requirements reference campaigns absent from inventory: {unknown_ids}")
        rq.observe("Active requirements", campaigns=sorted(reqs), as_of=as_of,
                   types=sorted({str(r.get("requirement_type")).lower() for v in reqs.values() for r in v}))

    # -- step 3: geo method and approved area (#20 worldwide / out-of-area)
    geo = ctx.check("geo_targeting", "Geo targets and method vs approved area/service model",
                    {"campaigns": ["id", "geo_targets", "geo_target_method"]})
    if geo.runnable:
        if not service_area and not rq.runnable:
            geo.partial("no approved area (profile.service_area or geo requirement): inventory only", ["profile:service_area"])
        for cid in sorted(camps):
            c = camps[cid]
            targets, method = _list(_cell(c, "geo_targets")), str(_cell(c, "geo_target_method") or "").upper()
            entity = {"campaign_id": cid, "control": "geo_targets"}
            geo_reqs = _reqs_for(reqs, cid, "geo_targets")
            area = [x.strip().lower() for r in geo_reqs for x in V.split_list(r.get("approved_value"), LIST_SEPS)] or service_area
            src = "external/campaign_requirements" if geo_reqs else "profile.service_area"
            if not targets:
                geo.partial(f"campaign {cid}: geo_targets unknown (empty is not worldwide)")
            elif area and "worldwide" not in area:
                ww = [t for t in targets if t in WORLDWIDE]
                other = [t for t in targets if t not in WORLDWIDE and t not in area]
                ev = {"actual": targets, "approved_area": area, "approved_source": src, "settings_timestamp": ts,
                      "requirements": [_ev(r) for r in geo_reqs]}
                if ww:
                    geo.finding("geo_outside_approved_area", "Warning", entity,
                                f"Campaign {cid} targets {ww} while the approved area is {area}", evidence=ev,
                                recommendation="Owner reviews geo targets against the approved service area; see skill-053.",
                                uncertainty="Impact on delivery/cost not established.")
                elif other:
                    geo.review("geo_outside_approved_area", entity,
                               f"Are geo targets {other} of campaign {cid} outside the approved area {area} "
                               f"(or sub-regions of it)?", evidence=ev,
                               outcomes={"outside_area": {"severity": "Warning", "recommendation":
                                                          "Owner reviews geo targets; detailed interpretation in skill-053."},
                                         "within_area": {"severity": None, "recommendation": "Sub-region of the approved area."},
                                         "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}},
                               guidance="Literal names only; a city inside an approved country is within_area.")
            m_reqs = _reqs_for(reqs, cid, "geo_target_method")
            m_ent = {"campaign_id": cid, "control": "geo_target_method"}
            if not method:
                geo.partial(f"campaign {cid}: geo_target_method unknown")
            elif m_reqs:
                want = str(m_reqs[0].get("approved_value") or "").strip().upper()
                if want and want != method:
                    geo.finding("setting_conflicts_requirement", "Warning", m_ent,
                                f"Campaign {cid} geo method {method} differs from approved {want}",
                                evidence={"actual": method, **_ev(m_reqs[0]), "settings_timestamp": ts},
                                recommendation="Owner reviews the location option (skill-053 for detail).",
                                uncertainty="Impact not established.")
            elif method == "PRESENCE_OR_INTEREST":
                geo.finding("presence_or_interest", "Info", m_ent,
                            f"Campaign {cid} uses presence-or-interest targeting; no contrary requirement supplied",
                            evidence={"actual": method, "settings_timestamp": ts, "service_area": service_area},
                            recommendation="Confirm the service model; presence-or-interest can be intentional.",
                            uncertainty="No documented requirement; not a defect by itself.")

    # -- step 4 (+ #46): start/end dates vs as_of and approved windows
    dates = ctx.check("date_window", "Start/end dates vs as_of and approved windows",
                      {"campaigns": ["id", "status", "end_date"]})
    expired: list[str] = []
    if dates.runnable:
        if as_of is None:
            dates.skip("as_of unknown", ["account:date_range_end"])
        for cid in sorted(camps) if as_of else []:
            c = camps[cid]
            end, start = V.parse_date(_cell(c, "end_date")), V.parse_date(_cell(c, "start_date"))
            status = str(c.get("status") or "").upper()
            ent = {"campaign_id": cid, "control": "end_date"}
            deliver = _reqs_for(reqs, cid, "required_delivery")
            ends = _reqs_for(reqs, cid, "promotion_end") + _reqs_for(reqs, cid, "end_date")
            if status == "ENABLED" and end and end < as_of:
                expired.append(cid)
                if deliver:
                    _blocked(dates, ctx, cid, "end_date", f"end date {end} < as_of {as_of}", deliver[0], ts)
                else:
                    dates.finding("expired_end_date", "Info", ent,
                                  f"Campaign {cid} is ENABLED but its end date {end} is before as_of {as_of}",
                                  evidence={"status": status, "end_date": end, "as_of": as_of, "settings_timestamp": ts},
                                  recommendation="Confirm the end was intended; never remove a promotion end date to restore delivery.",
                                  uncertainty="A past end date may be intentional.")
            for r in ends:
                want = V.parse_date(r.get("approved_value"))
                if want and end and end != want:
                    dates.finding("setting_conflicts_requirement", "Warning", ent,
                                  f"Campaign {cid} end date {end} differs from approved {want}",
                                  evidence={"actual": end, **_ev(r), "settings_timestamp": ts},
                                  recommendation="Owner confirms the approved end date.", uncertainty="Impact not established.")
                elif want and end is None and "end_date" in cols:
                    dates.partial(f"campaign {cid}: end_date unknown vs approved {want}")
            if deliver and start and start > as_of:
                _blocked(dates, ctx, cid, "start_date", f"start date {start} > as_of {as_of}", deliver[0], ts)
            if deliver and status in ("PAUSED",):
                _blocked(dates, ctx, cid, "status", f"status {status}", deliver[0], ts)
        if "start_date" not in cols:
            dates.partial("start dates unknown", ["campaigns:start_date"])

    # -- step 5: promotion revival guard
    rev = ctx.check("promotion_revival", "Expired promotions: owner confirmation before revival",
                    {"campaigns": ["id", "status", "end_date"]})
    if rev.runnable:
        for cid in expired:
            rev.review("promotion_revival", {"campaign_id": cid},
                       f"Has the owner confirmed renewed eligibility, dates, budget and creative for campaign {cid}?",
                       evidence={"end_date": _cell(camps[cid], "end_date"), "as_of": as_of},
                       outcomes={"revival_confirmed": {"severity": "Info", "recommendation":
                                                       "Propose new approved dates; do not remove the end date."},
                                 "intentional_end": {"severity": None, "recommendation": "No action."}},
                       guidance="revival_confirmed needs proposal {approval_ref, new_start, new_end, budget, creative_confirmed}.")
        rev.observe("Expired enabled campaigns under revival guard", campaigns=expired)

    # -- step 6: languages
    lang = ctx.check("languages", "Language coverage vs approved customer languages", {"campaigns": ["id", "languages"]})
    if lang.runnable:
        for cid in sorted(camps):
            actual = _list(_cell(camps[cid], "languages"))
            lr = _reqs_for(reqs, cid, "language") + _reqs_for(reqs, cid, "languages")
            if not actual:
                lang.partial(f"campaign {cid}: languages unknown (absent value is not 'no languages')")
                continue
            for r in lr:
                want = [x.strip().lower() for x in V.split_list(r.get("approved_value"), LIST_SEPS)]
                missing = sorted(set(want) - set(actual))
                if missing:
                    lang.finding("setting_conflicts_requirement", "Warning", {"campaign_id": cid, "control": "languages"},
                                 f"Campaign {cid} lacks approved languages {missing}",
                                 evidence={"actual": actual, **_ev(r), "settings_timestamp": ts},
                                 recommendation="Owner reviews language targeting.", uncertainty="Impact not established.")
        if not rq.runnable:
            lang.partial("no language requirements supplied: inventory only", rq.missing)

    # -- step 7: device exclusions vs bid modifiers, strategy support
    dev = ctx.check("devices", "Device exclusions vs modifiers and strategy support",
                    {"bid_adjustments": ["campaign_id", "dimension", "segment_value", "modifier"]})
    if dev.runnable:
        for r in sorted(ctx.rows("bid_adjustments"), key=lambda r: (str(r.get("campaign_id")), str(r.get("segment_value")))):
            if str(r.get("dimension") or "").upper() != "DEVICE":
                continue
            cid, seg = str(r.get("campaign_id")), str(r.get("segment_value") or "").upper()
            mod = V.num(r.get("modifier"))
            excluded = V.boolean(r.get("exclusion")) is True or (mod is not None and mod <= -1.0)
            strat = str((camps.get(cid) or {}).get("bidding_strategy_type") or "").upper()
            ent = {"campaign_id": cid, "control": f"device:{seg}"}
            dreq = [x for x in _reqs_for(reqs, cid, "device") if seg in {v.strip().upper() for v in
                                                                         V.split_list(x.get("approved_value"), LIST_SEPS)}]
            if excluded and dreq:
                dev.finding("setting_conflicts_requirement", "Warning", ent,
                            f"Campaign {cid} excludes {seg} although the approved requirement includes it",
                            evidence={"modifier": mod, **_ev(dreq[0])}, recommendation="Owner reviews the device exclusion.",
                            uncertainty="Impact not established.")
            elif excluded:
                dev.finding("device_exclusion", "Info", ent, f"Campaign {cid} excludes device {seg}",
                            evidence={"modifier": mod, "bidding_strategy_type": strat},
                            recommendation="Confirm the exclusion is intended.", uncertainty="No contrary requirement supplied.")
            elif mod not in (None, 0) and strat in SMART:
                dev.observe(f"Campaign {cid}: {seg} CPC modifier {mod} under {strat} (not applied as a CPC adjustment)",
                            campaign_id=cid, segment=seg, modifier=mod, strategy=strat)
            if seg not in DEVICES:
                dev.partial(f"unrecognized device segment '{seg}'")

    # -- step 8 (+ #91): remaining documented requirement mismatches
    other = ctx.check("requirement_mismatches", "Other explicit settings vs approved requirements", {REQ: REQ_COLS})
    if other.runnable:
        for key in sorted(reqs):
            targets = sorted(camps) if key == "*" else [key]
            for r in reqs[key]:
                rtype = str(r.get("requirement_type") or "").strip().lower()
                if rtype not in BOOL_CONTROLS + ("bidding_strategy_type", "ad_schedule"):
                    if rtype not in ("geo_targets", "geo_target_method", "language", "languages", "promotion_end",
                                     "end_date", "required_delivery", "device"):
                        other.partial(f"requirement type '{rtype}' not machine-comparable; owner review")
                    continue
                for cid in targets:
                    if cid not in camps:
                        continue
                    actual = _cell(camps[cid], rtype) if rtype in cols else None
                    if actual is None:
                        other.partial(f"campaign {cid}: {rtype} unknown; requirement not evaluated", [f"campaigns:{rtype}"])
                        continue
                    if rtype in BOOL_CONTROLS:
                        a, w = V.boolean(actual), V.boolean(r.get("approved_value"))
                        differs = a is not None and w is not None and a != w
                    else:
                        differs = V.norm_text(actual) != V.norm_text(r.get("approved_value"))
                    if differs:
                        other.finding("setting_conflicts_requirement", "Warning", {"campaign_id": cid, "control": rtype},
                                      f"Campaign {cid} {rtype}={actual} differs from approved {r.get('approved_value')}",
                                      evidence={"actual": actual, **_ev(r), "settings_timestamp": ts},
                                      recommendation="Owner reviews this setting; network performance belongs to 005/006.",
                                      uncertainty="Impact not established.")


def _blocked(chk, ctx, cid, control, why, req, ts) -> None:
    ent = {"campaign_id": cid, "control": control}
    ev = {"reason": why, **_ev(req), "settings_timestamp": ts, "as_of": ctx.as_of}
    prov = chk.finding("required_delivery_blocked", "Warning", ent,
                       f"Campaign {cid}: {why} while delivery is required ({req.get('effective_start')}..{req.get('effective_end')})",
                       evidence=ev, recommendation="Owner confirms whether the setting is unintended; do not remove end dates.",
                       uncertainty="Material impact not established by the script.")
    chk.review("required_delivery_blocked", ent,
               f"Is there independent evidence that blocked delivery of campaign {cid} has MATERIAL impact and the "
               f"setting is unintended?", evidence=ev, provisional=prov,
               outcomes={"material_blockage_evidenced": {"severity": "Critical", "recommendation":
                                                         "Prioritize the owner fix; cite the impact evidence."},
                         "not_evidenced": {"severity": "Warning", "recommendation": "Keep as Warning."},
                         "intentional": {"severity": None, "recommendation": "Document the intentional setting."}})


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref; end-date removal is refused; revival needs full confirmation."""
    p = decision.get("proposal") or {}
    problems = []
    if str(p.get("action") or "").lower() == "remove_end_date":
        problems.append("removing a promotion end date to restore delivery is never proposed")
    if decision.get("outcome") == "material_blockage_evidenced" and not p.get("evidence_ref"):
        problems.append("material blockage needs proposal.evidence_ref pointing at supplied impact evidence")
    if decision.get("outcome") == "revival_confirmed":
        missing = [k for k in ("approval_ref", "new_start", "new_end", "budget", "creative_confirmed") if not p.get(k)]
        if missing:
            problems.append(f"revival proposal missing {missing}")
        s, e = V.parse_date(p.get("new_start")), V.parse_date(p.get("new_end"))
        if p.get("new_end") and (e is None or (ctx.as_of and e < ctx.as_of) or (s and e < s)):
            problems.append("new_end must be a valid date on/after as_of and new_start")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
