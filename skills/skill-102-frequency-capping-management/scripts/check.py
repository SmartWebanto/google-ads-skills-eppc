"""check.py — skill-102 deterministic frequency caps, delivered exposure, approved bounds and fatigue screening.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-102-frequency-capping-management/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Scope = campaigns.channel_type DISPLAY | VIDEO | DEMAND_GEN | DISCOVERY; PMax/Search are not capped here.
         Delivered frequency uses ONE total row (reported_frequency_bucket total/all/empty) per campaign +
         report_start/end + population_scope with a campaign-level deduplication_scope; platform
         average_impression_frequency wins over impressions/unique_users. Unique users are NEVER summed
         across dates, buckets or campaigns.
         Bucket shares: labels all 'k+' = cumulative (share = reach_k / reach_1+); single values/ranges with at
         most a final open 'k+' = non-overlapping (share = reach / sum); anything else → partial.
         Approved bounds (external/frequency_plan approved_min_frequency / approved_max_frequency over
         bound_window_days) are compared only when the report window length equals bound_window_days;
         a breach is a deterministic Warning (the table has no Critical row). No universal 3-5/week limit.
         Fatigue: ctx.mature True, same goal_set_id, lowest vs highest bucket both >= min_clicks; a lower CVR at
         high frequency is a HYPOTHESIS → ai_review; 'corroborated_fatigue' (Warning) needs proposal.evidence_ref
         matching the campaign's frequency_plan.fatigue_evidence_reference.
         Never computes wasted spend or excess impressions by subtracting a cap.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | fatigue evidence_ref must resolve to the campaign's plan reference
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

SKILL = "skill-102-frequency-capping-management"
VERSION = "1.0.0"

CTRL = "external/frequency_controls"
EXPO = "custom/frequency_exposure"
OUT = "custom/frequency_outcomes"
PLAN = "external/frequency_plan"
_SCOPE = {"display", "video", "demand_gen", "demand gen", "discovery"}
_TOTAL = {"", "total", "all"}
_LABEL = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)|(\+))?\s*$")
_CAP_CONTROLS = ("frequency", "cap", "target frequency")


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _label(v) -> tuple[int, int | None, bool] | None:
    """(low, high, open) for '3', '3-4', '5+'; None when unparseable."""
    m = _LABEL.match(_s(v))
    if not m:
        return None
    lo = int(m.group(1))
    if m.group(3):
        return lo, None, True
    return lo, int(m.group(2)) if m.group(2) else lo, False


def _window(r) -> tuple[str, str, int | None]:
    a, b = V.parse_date(r.get("report_start")), V.parse_date(r.get("report_end"))
    return _s(r.get("report_start")), _s(r.get("report_end")), ((b - a).days + 1 if a and b else None)


def run(ctx) -> None:
    """Run delivered-frequency, bucket-share, approved-bound and fatigue-hypothesis checks for Display/Video/Demand Gen.

    Rules:   One total row per campaign/window/population; unique users never summed across dates, buckets or campaigns.
             Bound breach is a deterministic Warning only when the report window equals bound_window_days; no universal
             cap. Fatigue needs ctx.mature True, one goal_set_id and min_clicks on both buckets → ai_review (Warning
             needs proposal.evidence_ref). Never computes wasted spend by subtracting a cap.
    """
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}
    inv = ctx.check("cap_inventory", "Inventory subtype, objective and every configured cap",
                    {"campaigns": ["id", "channel_type"],
                     CTRL: ["campaign_id", "control_id", "cap_status", "event_type", "entity_level", "maximum_count",
                            "period"]})
    in_scope = sorted(c for c, r in camps.items() if V.norm_text(r.get("channel_type")) in _SCOPE)
    controls: dict[str, list[dict]] = {}
    if inv.runnable:
        for r in sorted(ctx.rows(CTRL), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("control_id")))):
            controls.setdefault(_s(r.get("campaign_id")), []).append(r)
        for cid in in_scope:
            rows = controls.get(cid, [])
            if not rows:
                inv.partial(f"campaign {cid}: no control rows; cap state unknown (not 'uncapped')")
                continue
            inv.observe(f"Campaign {cid}: configured controls", campaign_id=cid,
                        channel_type=camps[cid].get("channel_type"),
                        controls=[{k: r.get(k) for k in ("control_id", "cap_status", "event_type", "entity_level",
                                                         "maximum_count", "period")} for r in rows])
        ignored = sorted(set(controls) - set(in_scope))
        if ignored:
            inv.observe("Control rows outside cap-supporting channels ignored", campaigns=ignored)

    # -- step 2: delivered average frequency
    dfq = ctx.check("delivered_frequency", "Impressions per deduplicated unique user for matched windows",
                    {EXPO: ["campaign_id", "report_start", "report_end", "population_scope",
                            "reported_frequency_bucket", "impressions", "unique_users", "deduplication_scope"]})
    measured: dict[tuple, dict] = {}
    if dfq.runnable:
        totals: dict[tuple, list[dict]] = {}
        for r in ctx.rows(EXPO):
            if V.norm_text(r.get("reported_frequency_bucket")) in _TOTAL:
                key = (_s(r.get("campaign_id")), *_window(r)[:2], _s(r.get("population_scope")))
                totals.setdefault(key, []).append(r)
        for key, rows in sorted(totals.items()):
            cid = key[0]
            if len(rows) > 1:
                dfq.partial(f"campaign {cid} {key[1]}..{key[2]}: {len(rows)} total rows for one population; ambiguous")
                continue
            r = rows[0]
            if "campaign" not in V.norm_text(r.get("deduplication_scope")):
                dfq.partial(f"campaign {cid}: deduplication_scope '{r.get('deduplication_scope')}' is not "
                            f"campaign-level; no ratio")
                continue
            impr, users = V.num(r.get("impressions")), V.num(r.get("unique_users"))
            computed = V.ratio(impr, users)
            platform = V.num(r.get("average_impression_frequency"))
            value = platform if platform is not None else computed
            flags = {"modeled_status": r.get("modeled_status"), "privacy_flags": r.get("privacy_flags"),
                     "report_definition": r.get("report_definition"), "report_source": r.get("report_source")}
            rec = {"campaign_id": cid, "report_start": key[1], "report_end": key[2], "window_days": _window(r)[2],
                   "population_scope": key[3], "impressions": impr, "unique_users": users,
                   "computed_frequency": computed, "platform_average": platform, "measured_frequency": value,
                   "source": "platform average" if platform is not None else "impressions / unique_users", **flags}
            dfq.observe(f"Campaign {cid}: delivered frequency {key[1]}..{key[2]}", **rec)
            if value is not None:
                measured[key] = rec
            else:
                dfq.partial(f"campaign {cid}: unique_users zero/unknown; frequency undefined")

    # -- step 3: exposure distribution
    dist = ctx.check("exposure_distribution", "Exposure distribution and privacy/modeling limits",
                     {EXPO: ["campaign_id", "report_start", "report_end", "population_scope",
                             "reported_frequency_bucket", "reach_by_bucket"]})
    if dist.runnable:
        groups: dict[tuple, list[tuple]] = {}
        for r in ctx.rows(EXPO):
            if V.norm_text(r.get("reported_frequency_bucket")) in _TOTAL:
                continue
            key = (_s(r.get("campaign_id")), *_window(r)[:2], _s(r.get("population_scope")))
            groups.setdefault(key, []).append((_label(r.get("reported_frequency_bucket")),
                                               V.num(r.get("reach_by_bucket")), r))
        for key, rows in sorted(groups.items()):
            labels = [x[0] for x in rows]
            if any(lbl is None for lbl in labels) or any(x[1] is None for x in rows):
                dist.partial(f"campaign {key[0]}: unparseable bucket labels or suppressed reach")
                continue
            rows.sort(key=lambda x: x[0][0])
            opens = [lbl for lbl in labels if lbl[2]]
            if len(opens) == len(labels) and len(labels) > 1:
                base = next((x[1] for x in rows if x[0][0] == 1), None)
                kind = "cumulative"
                shares = {f"{x[0][0]}+": V.ratio(x[1], base) for x in rows}
            elif len(opens) <= 1 and (not opens or rows[-1][0][2]):
                base = sum(x[1] for x in rows)
                kind = "non-overlapping"
                shares = {(f"{x[0][0]}+" if x[0][2] else f"{x[0][0]}-{x[0][1]}"): V.ratio(x[1], base) for x in rows}
            else:
                dist.partial(f"campaign {key[0]}: mixed cumulative/non-overlapping labels; no percentages")
                continue
            flags = sorted({_s(x[2].get("privacy_flags")) for x in rows if _s(x[2].get("privacy_flags"))})
            if flags:
                dist.partial(f"campaign {key[0]}: privacy/suppression flags {flags}")
            dist.observe(f"Campaign {key[0]}: exposure distribution {key[1]}..{key[2]}", campaign_id=key[0],
                         kind=kind, denominator=base, shares=shares, privacy_flags=flags,
                         note="high average frequency does not mean every user is overexposed")

    # -- step 4: exposure vs approved bounds
    plan = {}
    for r in ctx.rows(PLAN):
        plan.setdefault(_s(r.get("campaign_id")), r)
    evp = ctx.check("exposure_vs_plan", "Measured exposure versus approved campaign bounds",
                    {PLAN: ["campaign_id", "exposure_objective", "approved_min_frequency", "approved_max_frequency",
                            "bound_window_days"]})
    flagged: set[str] = set()
    if evp.runnable and not measured:
        evp.partial("no measured delivered frequency to compare", dfq.missing or [f"{EXPO}:unique_users"])
    if evp.runnable:
        for key, rec in sorted(measured.items()):
            p = plan.get(rec["campaign_id"])
            if p is None:
                evp.partial(f"campaign {rec['campaign_id']}: no approved exposure plan")
                continue
            lo, hi, wd = (V.num(p.get("approved_min_frequency")), V.num(p.get("approved_max_frequency")),
                          V.num(p.get("bound_window_days")))
            if wd is None or rec["window_days"] is None or wd != rec["window_days"]:
                evp.partial(f"campaign {rec['campaign_id']}: report window {rec['window_days']}d differs from "
                            f"bound window {wd}; not comparable")
                continue
            ent = {"campaign_id": rec["campaign_id"], "report_start": rec["report_start"],
                   "report_end": rec["report_end"], "population_scope": rec["population_scope"]}
            ev = {**rec, "approved_min_frequency": lo, "approved_max_frequency": hi, "bound_window_days": wd,
                  "exposure_objective": p.get("exposure_objective"), "plan_owner": p.get("owner")}
            f = rec["measured_frequency"]
            key2 = ("exposure_above_approved_bound", f"above approved max {hi:g}") if hi is not None and f > hi else \
                ("exposure_below_approved_bound", f"below approved min {lo:g}") if lo is not None and f < lo else None
            if key2 is None:
                evp.observe(f"Campaign {rec['campaign_id']}: exposure within approved bounds", **ent, frequency=f)
                continue
            flagged.add(rec["campaign_id"])
            evp.finding(key2[0], "Warning", ent,
                        f"Campaign {rec['campaign_id']}: measured frequency {f:.2f} per {wd:g} days is {key2[1]}",
                        evidence=ev, recommendation="Review cap/target-frequency or rotation with the plan owner.",
                        uncertainty="Measured average; modeled/privacy-limited reach can bias it; not proof of harm.")

    # -- step 5: fatigue screen
    fat = ctx.check("fatigue_screen", "Matched mature outcomes by frequency bucket",
                    {OUT: ["campaign_id", "report_start", "report_end", "population_scope",
                           "reported_frequency_bucket", "clicks", "conversions", "goal_set_id"]})
    if fat.runnable:
        min_clicks = ctx.params.get("min_clicks")
        if ctx.mature is not True or min_clicks.value is None:
            fat.partial(f"fatigue screening disabled: maturity={ctx.mature} ({ctx.maturity_note}); "
                        f"min_clicks {min_clicks.value} {min_clicks.reason}")
        else:
            grp: dict[tuple, list[tuple]] = {}
            for r in ctx.rows(OUT):
                lbl = _label(r.get("reported_frequency_bucket"))
                clicks, conv = V.num(r.get("clicks")), V.num(r.get("conversions"))
                if lbl is None or clicks is None or conv is None:
                    continue
                key = (_s(r.get("campaign_id")), *_window(r)[:2], _s(r.get("population_scope")),
                       _s(r.get("goal_set_id")))
                grp.setdefault(key, []).append((lbl, clicks, conv))
            for key, rows in sorted(grp.items()):
                ok = sorted((x for x in rows if x[1] >= min_clicks.value), key=lambda x: x[0][0])
                if len(ok) < 2:
                    fat.observe(f"Campaign {key[0]}: fewer than two buckets meet min_clicks", campaign_id=key[0],
                                min_clicks=min_clicks.value)
                    continue
                low, high = ok[0], ok[-1]
                cvr_low, cvr_high = V.ratio(low[2], low[1]), V.ratio(high[2], high[1])
                ev = {"low_bucket": low[0][0], "low_clicks": low[1], "low_conversions": low[2], "low_cvr": cvr_low,
                      "high_bucket": high[0][0], "high_clicks": high[1], "high_conversions": high[2],
                      "high_cvr": cvr_high, "goal_set_id": key[4], "min_clicks": min_clicks.value,
                      "min_clicks_source": min_clicks.source, "window": [key[1], key[2]],
                      "fatigue_evidence_reference": (plan.get(key[0]) or {}).get("fatigue_evidence_reference"),
                      "creative_rotation": (plan.get(key[0]) or {}).get("creative_rotation")}
                fat.observe(f"Campaign {key[0]}: CVR by frequency bucket", campaign_id=key[0], **ev)
                if cvr_high is not None and cvr_low is not None and cvr_high < cvr_low:
                    flagged.add(key[0])
                    fat.review("fatigue_hypothesis", {"campaign_id": key[0], "goal_set_id": key[4],
                                                      "report_start": key[1], "report_end": key[2]},
                               f"Campaign {key[0]}: CVR {cvr_high:.2%} at {high[0][0]}+ exposures vs {cvr_low:.2%} at "
                               f"{low[0][0]}. Is fatigue corroborated beyond selection into higher frequency?",
                               evidence=ev,
                               outcomes={"corroborated_fatigue": {"severity": "Warning", "recommendation":
                                                                  "Propose a bounded cap/rotation test with rollback."},
                                         "hypothesis_only": {"severity": "Info", "recommendation":
                                                             "Record as hypothesis; collect creative/customer evidence."},
                                         "no_fatigue": {"severity": None, "recommendation": "No action."}},
                               guidance="Correlation is not causation; corroborated_fatigue needs proposal.evidence_ref "
                                        "(documented customer/creative evidence).")

    # -- step 6: bounded test proposals
    tp = ctx.check("test_proposal", "Supported bounded cap/target-frequency or rotation tests",
                   {CTRL: ["campaign_id", "supported_controls"]})
    if tp.runnable:
        for cid in sorted(flagged):
            sup = " ".join(V.norm_text(r.get("supported_controls")) for r in controls.get(cid, []) or
                           [r for r in ctx.rows(CTRL) if _s(r.get("campaign_id")) == cid])
            if not sup.strip():
                tp.partial(f"campaign {cid}: supported_controls unknown; no control proposal")
                continue
            if not any(t in sup for t in _CAP_CONTROLS):
                tp.observe(f"Campaign {cid}: no supported frequency control; rotation-only options", campaign_id=cid)
                continue
            tp.finding("bounded_exposure_test_opportunity", "Info", {"campaign_id": cid},
                       f"Campaign {cid}: supported frequency control allows a bounded exposure/creative test",
                       evidence={"supported_controls": sup.strip(), "trigger": "approved-bound breach or fatigue "
                                                                               "hypothesis in this run"},
                       recommendation="Define event, level, period, metric, duration and rollback; creative via 162.",
                       uncertainty="No causal harm proof; no savings estimate.")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   corroborated_fatigue (Warning) requires proposal.evidence_ref equal to a non-empty
             fatigue_evidence_reference of an external/frequency_plan row for the reviewed campaign_id; refs of
             other campaigns or absent from the plan are rejected (the plan carries no window, so none is checked).
             Other outcomes need no proposal.
    """
    if decision.get("outcome") != "corroborated_fatigue":
        return []
    ref = _s((decision.get("proposal") or {}).get("evidence_ref"))
    if not ref:
        return ["corroborated_fatigue needs proposal.evidence_ref to documented customer/creative evidence"]
    cid = _s(item.entity.get("campaign_id"))
    if any(_s(r.get("campaign_id")) == cid and _s(r.get("fatigue_evidence_reference")) == ref
           for r in ctx.rows(PLAN)):
        return []
    return [f"evidence_ref {ref} is not a fatigue_evidence_reference for campaign {cid} in {PLAN}"]


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
