"""check.py — skill-070 deterministic business-event coverage against owner-declared outcomes.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-070-conversion-tracking-completeness/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Expected outcomes come ONLY from external/business_event_map (never business type or action names).
         Actions join by stable IDs; inactive, secondary and explicitly unmapped (null action_id) rows are retained.
         Warning (deterministic) = a REQUIRED event whose map rows are all unmapped, or whose mapped actions are
         all absent from a manifest-complete conversion_actions inventory or not ENABLED (evidenced gap,
         materiality unconfirmed). Critical only via ai_review with proposal.evidence_ref AND an observed
         business count > 0. Zero Ads volume vs business outcomes is compared only when ctx.mature is True and
         every daily row is reporting_mature; its meaning (scope/attribution vs broken path) is AI judgment.
         Daily action rows are deduplicated at account/campaign/action/date/date_basis and summed per action
         once — never multiplied by campaign totals. Micro-events are optional: never a defect when missing.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks08 | initial deterministic check
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

SKILL = "skill-070-conversion-tracking-completeness"
VERSION = "1.0.0"

MAP = "external/business_event_map"
DAILY = "custom/conversion_action_daily"
JOURNEY = "external/journey_coverage"
MAP_NEEDS = ["business_event_id", "action_id", "required_for_objective", "observed_business_count",
             "count_window_start", "count_window_end"]
DAILY_NEEDS = ["action_id", "date", "conversions", "reporting_mature"]


def _s(v) -> str:
    return str(v or "").strip()


def _alnum(v) -> str:
    return "".join(ch for ch in _s(v) if ch.isalnum()).lower()


def _required(v) -> bool | None:
    b = V.boolean(v)
    if b is not None:
        return b
    t = _s(v).lower()
    return True if t == "required" else False if t == "optional" else None


def _account_rows(ctx, key) -> tuple[list[dict], int]:
    acct = _alnum(ctx.account_id)
    keep, other = [], 0
    for r in ctx.rows(key):
        if acct and "account_id" in r and _s(r.get("account_id")) and _alnum(r.get("account_id")) != acct:
            other += 1
            continue
        keep.append(r)
    return keep, other


def _events(rows) -> dict[tuple, dict]:
    """(campaign_id, business_event_id) → merged map info."""
    out: dict[tuple, dict] = {}
    for r in rows:
        k = (_s(r.get("campaign_id")), _s(r.get("business_event_id")))
        e = out.setdefault(k, {"actions": set(), "unmapped_rows": 0, "required": set(), "counts": [],
                               "window": set(), "stage": set(), "role": set(), "decision_use": set(), "owner": set()})
        aid = _s(r.get("action_id"))
        if aid:
            e["actions"].add(aid)
        else:
            e["unmapped_rows"] += 1
        e["required"].add(_required(r.get("required_for_objective")))
        n = V.num(r.get("observed_business_count"))
        if n is not None:
            e["counts"].append(n)
        e["window"].add((V.parse_date(r.get("count_window_start")), V.parse_date(r.get("count_window_end"))))
        for f, col in (("stage", "funnel_stage"), ("role", "intended_bidding_role"),
                       ("decision_use", "decision_use"), ("owner", "owner")):
            if _s(r.get(col)):
                e[f].add(_s(r.get(col)))
    return out

def _journey(ctx) -> None:
    """Steps 6-7: optional micro-event questions; independent of the business event map."""
    jr = ctx.check("journey_micro_events", "Optional journey/micro-event questions",
                   {JOURNEY: ["business_event_id", "stage", "diagnostic_question", "event_name", "downstream_event_id",
                              "decision_owner", "intended_bidding_role"]})
    if jr.runnable:
        jrows, _ = _account_rows(ctx, JOURNEY)
        for r in sorted(jrows, key=lambda r: (_s(r.get("business_event_id")), _s(r.get("stage")), _s(r.get("event_name")))):
            ent = {"business_event_id": _s(r.get("business_event_id")), "stage": _s(r.get("stage")),
                   "event_name": _s(r.get("event_name"))}
            role = _s(r.get("intended_bidding_role")).lower()
            if not (_s(r.get("diagnostic_question")) and _s(r.get("downstream_event_id")) and _s(r.get("decision_owner"))):
                jr.observe(f"Journey event {ent['event_name']} lacks question/downstream/owner (not a defect)", **ent)
                continue
            if role in ("primary", "bidding", "primary_bidding"):
                jr.observe(f"Journey event {ent['event_name']} intended as primary: never auto-promote weak signals; "
                           f"check campaign custom goals", **ent, intended_bidding_role=role)
            jr.review("justified_secondary_event", ent,
                      f"Does the diagnostic question for '{ent['event_name']}' justify a secondary event with a "
                      f"clear downstream relationship and decision owner?",
                      evidence={"diagnostic_question": r.get("diagnostic_question"),
                                "downstream_event_id": r.get("downstream_event_id"),
                                "decision_owner": r.get("decision_owner"), "event_count": r.get("event_count"),
                                "consent_scope": r.get("consent_scope"), "intended_bidding_role": r.get("intended_bidding_role")},
                      outcomes={"justified_secondary": {"severity": "Info", "recommendation":
                                                        "Optional secondary measurement with owner and decision use."},
                                "not_needed": {"severity": None, "recommendation": "No micro-event proposal."}},
                      guidance="Missing add-to-cart/form-start/engagement events are not defects.")


def run(ctx) -> None:
    """Run business-event map vs conversion-action coverage and Ads-volume vs business-outcome checks.

    Rules:   Expected outcomes only from external/business_event_map; micro-events missing are never defects. Warning
             required_measurement_gap for a required event unmapped, absent from a manifest-complete inventory or not
             ENABLED; Critical only via ai_review with proposal.evidence_ref and business count > 0. Zero Ads volume is
             compared only when ctx.mature True and every row reporting_mature, then Info + review.
    """
    # -- step 1: expected outcomes
    exp = ctx.check("expected_outcomes", "Expected outcomes from the business event map", {MAP: MAP_NEEDS})
    later = (("action_mapping", "Required events mapped to existing, enabled actions"),
             ("volume_vs_business", "Mature Ads action volume versus business outcomes"),
             ("coverage_by_event", "Coverage and uncertainty by business event"))
    if not exp.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("business event map unavailable: expected outcomes unknown", exp.missing)
        _journey(ctx)
        return
    rows, other = _account_rows(ctx, MAP)
    if other:
        exp.partial(f"{other} map rows for other accounts excluded")
    events = _events(rows)
    unknown_req = []
    for k in sorted(events):
        e = events[k]
        req = e["required"] - {None}
        e["req"] = True if True in req else (False if req == {False} else None)
        e["count"] = max(e["counts"]) if e["counts"] else None
        e["count_conflict"] = len(set(e["counts"])) > 1
        if e["req"] is None:
            unknown_req.append({"campaign_id": k[0] or None, "business_event_id": k[1]})
        exp.observe(f"Business event {k[1]} (campaign {k[0] or 'account'})", campaign_id=k[0] or None,
                    business_event_id=k[1], required=e["req"], funnel_stage=sorted(e["stage"]),
                    decision_use=sorted(e["decision_use"]), intended_bidding_role=sorted(e["role"]),
                    mapped_actions=sorted(e["actions"]), unmapped_rows=e["unmapped_rows"],
                    observed_business_count=e["count"],
                    count_windows=sorted([str(a), str(b)] for a, b in e["window"]))
    if unknown_req:
        exp.finding("expected_outcome_status_unknown", "Info", {"map": MAP},
                    f"{len(unknown_req)} business events lack a required/optional declaration",
                    evidence={"events": unknown_req}, recommendation="Ask the business owner to classify these events.",
                    uncertainty="Coverage of unclassified events is not judged.")

    # -- step 2 + 4: mapping to actions
    amap = ctx.check("action_mapping", "Required events mapped to existing, enabled actions",
                     {MAP: ["business_event_id", "action_id"], "conversion_actions": ["id", "status"]})
    status: dict[tuple, str] = {}
    if amap.runnable:
        ca = ctx.table("conversion_actions")
        complete = ca.complete is True and not ca.truncated
        actions = {_s(a.get("id")): a for a in ctx.rows("conversion_actions")}
        if not complete:
            amap.partial("conversion_actions not certified complete: absent actions cannot be proven")
        for k in sorted(events):
            e = events[k]
            present = [a for a in sorted(e["actions"]) if a in actions]
            missing = [a for a in sorted(e["actions"]) if a not in actions]
            enabled = [a for a in present if _s(actions[a].get("status")).upper() == "ENABLED"]
            inactive = [a for a in present if a not in enabled]
            secondary = [a for a in enabled if V.boolean(actions[a].get("primary_for_goal")) is False]
            ent = {"campaign_id": k[0] or None, "business_event_id": k[1]}
            ev = {"mapped_actions": sorted(e["actions"]), "unmapped_rows": e["unmapped_rows"],
                  "missing_from_inventory": missing, "inactive": inactive, "enabled": enabled,
                  "secondary_enabled": secondary,
                  "secondary_in_campaign_goals": [a for a in secondary if k[0] and a in ctx.goal_ids(k[0])],
                  "observed_business_count": e["count"],
                  "business_count_conflict": e["count_conflict"], "inventory_complete": complete,
                  "intended_bidding_role": sorted(e["role"])}
            if enabled:
                status[k] = "mapped_enabled"
            elif not e["actions"]:
                status[k] = "unmapped"
            elif missing and not complete:
                status[k] = "unknown"
            else:
                status[k] = "absent_or_inactive"
            amap.observe(f"Mapping for {k[1]} ({k[0] or 'account'})", **ent, status=status[k], **ev)
            if e["req"] is not True or status[k] not in ("unmapped", "absent_or_inactive"):
                continue
            what = ("explicitly unmapped (null action_id)" if status[k] == "unmapped"
                    else "mapped only to actions absent from the complete inventory or not enabled")
            amap.finding("required_measurement_gap", "Warning", ent,
                         f"Required business event {k[1]} is {what}", evidence=ev,
                         recommendation="Owner-reviewed measurement path for this required outcome; configuration "
                                        "→ 076, pipeline → 080, incidents → 110. No account change here.",
                         uncertainty="Materiality unconfirmed; no conversion or revenue loss is estimated.")
            if (e["count"] or 0) > 0:
                amap.review("required_measurement_gap", ent,
                            f"Required event {k[1]} occurred {e['count']:g} times in the owner's window without an "
                            f"intended Ads measurement path. Is MATERIAL impact independently evidenced?",
                            evidence={**ev, "count_windows": sorted([str(a), str(b)] for a, b in e["window"])},
                            outcomes={"material_outcomes_unmeasured": {"severity": "Critical", "recommendation":
                                                                       "Prioritize restoring measurement; cite evidence."},
                                      "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                            guidance="Critical requires proposal.evidence_ref to supplied impact evidence "
                                     "(e.g. bidding/decision use of this outcome).")
        amap.observe("Action inventory summary", actions=len(actions),
                     single_action_account=len(actions) == 1,
                     note="one well-chosen action may be complete coverage")

    # -- step 3: mature Ads volume vs business outcomes
    vol = ctx.check("volume_vs_business", "Mature Ads action volume versus business outcomes",
                    {MAP: MAP_NEEDS, DAILY: DAILY_NEEDS})
    if vol.runnable:
        drows, other = _account_rows(ctx, DAILY)
        grain_cols = [c for c in ("account_id", "campaign_id", "action_id", "date", "date_basis")
                      if c in ctx.table(DAILY).columns]
        seen: dict[tuple, dict | None] = {}
        for r in drows:
            g = tuple(_s(r.get(c)) for c in grain_cols)
            if g in seen and seen[g] is not None and seen[g] != r:
                seen[g] = None
            elif g not in seen:
                seen[g] = r
        conflicts = sum(1 for v in seen.values() if v is None)
        if conflicts:
            vol.partial(f"{conflicts} conflicting daily rows at {grain_cols} excluded")
        clean = [r for r in seen.values() if r is not None]
        immature = sum(1 for r in clean if V.boolean(r.get("reporting_mature")) is not True)
        can_compare = ctx.mature is True and immature == 0
        if not can_compare:
            vol.partial(f"zero-volume comparison disabled: maturity={ctx.mature} ({ctx.maturity_note}); "
                        f"{immature} daily rows not reporting_mature")
        for k in sorted(events):
            e = events[k]
            if e["req"] is not True or status.get(k) != "mapped_enabled":
                continue
            start, end = sorted(e["window"], key=str)[0] if len(e["window"]) == 1 else (None, None)
            start, end = start or ctx.period_start, end or ctx.period_end
            total, days = 0.0, set()
            unknown_cells = 0
            for r in clean:
                d = V.parse_date(r.get("date"))
                if _s(r.get("action_id")) not in e["actions"] or d is None or not (start <= d <= end):
                    continue
                if k[0] and "campaign_id" in r and _s(r.get("campaign_id")) not in ("", k[0]):
                    continue
                c = V.num(r.get("conversions"))
                if c is None:
                    unknown_cells += 1
                    continue
                total += c
                days.add(d)
            ent = {"campaign_id": k[0] or None, "business_event_id": k[1]}
            ev = {"actions": sorted(e["actions"]), "ads_conversions": total, "days_with_rows": len(days),
                  "window": [start, end], "observed_business_count": e["count"], "unknown_cells": unknown_cells,
                  "ads_to_business_ratio": V.ratio(total, e["count"])}
            vol.observe(f"Ads volume for required event {k[1]} ({k[0] or 'account'})", **ent, **ev,
                        note="ratio is descriptive; count/value disagreement routes to 071")
            if can_compare and total == 0 and unknown_cells == 0 and (e["count"] or 0) > 0:
                prov = vol.finding("zero_ads_volume_with_outcomes", "Info", ent,
                                   f"Required event {k[1]}: 0 Ads conversions vs {e['count']:g} business outcomes "
                                   f"in {start}..{end}", evidence=ev,
                                   recommendation="Check scope alignment before diagnosing a broken path.",
                                   uncertainty="Business counts may include outcomes outside Ads-attributable scope.")
                vol.review("zero_ads_volume_with_outcomes", ent,
                           f"Do scope, attribution and date basis align so that 0 Ads conversions for {k[1]} "
                           f"evidence a broken or partial measurement path?",
                           evidence=ev, provisional=prov,
                           outcomes={"path_broken_material": {"severity": "Critical", "recommendation":
                                                              "Restore the measurement path; cite the evidence."},
                                     "partial_gap": {"severity": "Warning", "recommendation":
                                                     "Owner review of the path; route to 110 for incident timing."},
                                     "explained_scope_or_attribution": {"severity": None, "recommendation":
                                                                        "No gap; document the scope difference."},
                                     "uncertain": {"severity": "Info", "recommendation": "Request aligned scope evidence."}},
                           guidance="Only supplied scope/attribution evidence counts. path_broken_material requires "
                                    "proposal.evidence_ref.")

    _journey(ctx)

    # -- step 8: coverage by event (deduplicated)
    cov = ctx.check("coverage_by_event", "Coverage and uncertainty by business event")
    if not amap.runnable:
        cov.partial("action mapping unavailable: coverage status unknown", amap.missing)
    summary = {}
    for k in sorted(events):
        e = events[k]
        st = status.get(k, "unknown")
        summary.setdefault(st if e["req"] else f"optional_or_unknown:{st}", []).append(
            f"{k[0] or 'account'}/{k[1]}")
    cov.observe("Business events by coverage status", **{k: v for k, v in sorted(summary.items())})


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes require proposal.evidence_ref; Critical gaps also need a positive business count."""
    if decision.get("outcome") not in ("material_outcomes_unmeasured", "path_broken_material"):
        return []
    problems = []
    if not _s((decision.get("proposal") or {}).get("evidence_ref")):
        problems.append("proposal.evidence_ref required for Critical")
    if not (item.evidence.get("observed_business_count") or 0) > 0:
        problems.append("Critical needs an observed business count > 0")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
