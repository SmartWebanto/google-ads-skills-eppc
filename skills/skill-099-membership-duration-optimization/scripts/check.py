"""check.py — skill-099 deterministic membership-duration review against controls, retention and entry-age cohorts.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-099-membership-duration-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Durations are compared only within one membership_controls row's `units`; day/week units convert to
         days exactly (1, 7); month/other units stay unconverted → dependent retention/cohort comparison partial.
         observed_duration equal to nonexpiring_special_value = non-expiring (exceeds every finite limit,
         never 'outside platform bounds').
         Retention limit = min(numeric membership_controls.retention_constraint in row units,
         activation_permissions.retention_limit_days). Breach + evidenced active use (audiences row with a
         campaign_id for the list) = deterministic Critical (named safety/retention failure); breach without
         evidenced use = Warning.
         Audience age buckets are days since qualifying entry ('0-30', '31-60', '90+'); click-to-conversion lag
         is never a substitute. Only rows with maturity true/'mature' count; bucket straddling the current
         window is excluded (partial). Cohort review needs ctx.mature True AND min_conversions outcomes on
         BOTH sides of the current window; otherwise Info cohort_evidence_insufficient, no prescription.
         Identical durations or a familiar industry window are observations, never warnings.
         verify(): proposed durations must lie within allowed_min/max, <= retention limit and <= cohort horizon;
         any extension additionally needs activation permission 'permitted'.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
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

SKILL = "skill-099-membership-duration-optimization"
VERSION = "1.0.0"

CTRL = "external/membership_controls"
DEFS = "external/audience_definitions"
COH = "external/audience_age_cohorts"
LIFE = "external/customer_lifecycle"
PERM = "external/activation_permissions"
_UNIT_DAYS = {"day": 1, "days": 1, "d": 1, "week": 7, "weeks": 7, "w": 7}
_GRANTED = {"granted", "approved", "permitted", "verified", "yes", "true"}
_DENIED = {"denied", "revoked", "withdrawn", "rejected", "expired", "no", "false"}
_CONSENT_OK = {"covered", "complete", "verified", "not_required", "not required", "not_applicable", "not applicable"}
_ADS_DEST = {"google ads", "google_ads", "google-ads", "ads"}
_BUCKET = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)|(\+))\s*d?(?:ays?)?\s*$", re.I)


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _tokens(v) -> set[str]:
    return {V.norm_text(x) for x in V.split_list(v)}


def _mature(v) -> bool:
    return V.boolean(v) is True or V.norm_text(v) == "mature"


def _bucket(v) -> tuple[float, float | None] | None:
    """(lower, upper) days; upper None for an open '90+' bucket; None when unparseable."""
    m = _BUCKET.match(_s(v))
    if not m:
        return None
    lo = float(m.group(1))
    return (lo, None) if m.group(3) else (lo, float(m.group(2)))


def _permission(ctx, list_id: str, source_id: str) -> tuple[str, str, list, float | None]:
    """('permitted'|'denied'|'unknown', reason, refs, min retention_limit_days) for one list/source."""
    t = ctx.table(PERM)
    if t is None:
        return "unknown", f"{PERM} (file) missing", [], None
    rows = [r for r in t.rows if (list_id and _s(r.get("list_id")) == list_id)
            or (not _s(r.get("list_id")) and source_id and _s(r.get("source_id")) == source_id)]
    limits = [x for x in (V.num(r.get("retention_limit_days")) for r in rows) if x is not None and x > 0]
    limit = min(limits) if limits else None
    if not rows:
        return "unknown", f"no permission row for list {list_id} / source {source_id or '-'}", [], None
    refs = sorted({_s(r.get("evidence_reference")) for r in rows if _s(r.get("evidence_reference"))})
    if any(V.norm_text(r.get("permission_status")) in _DENIED for r in rows):
        return "denied", "permission_status denied/revoked", refs, limit
    for r in rows:
        if (V.norm_text(r.get("permission_status")) in _GRANTED
                and V.norm_text(r.get("consent_coverage_status")) in _CONSENT_OK
                and _tokens(r.get("permitted_destinations")) & _ADS_DEST):
            return "permitted", "granted, consent covered, Google Ads destination permitted", refs, limit
    return "unknown", "permission, consent coverage or Google Ads destination not evidenced", refs, limit


def run(ctx) -> None:
    """Run duration inventory, reset semantics, age-bucket outcomes, retention and permission-gate checks.

    Rules:   Durations compare only in one row's units (day/week convert; others → partial). Retention breach +
             evidenced active use → Critical, breach alone → Warning; outside platform bounds / approved mismatch →
             Warning. Cohort review needs ctx.mature True and min_conversions on both sides, else Info
             'cohort_evidence_insufficient'. Extensions without 'permitted' activation → Info blocked;
             identical/industry-typical durations are observations.
    """
    inv = ctx.check("duration_inventory", "Inventory lists, observed durations, units and roles",
                    {"audiences": ["list_id"],
                     CTRL: ["list_id", "source_platform", "observed_duration", "units", "intended_role"]})
    titles = (("reset_semantics", "Entry, re-entry and reset clock semantics"),
              ("age_outcomes", "Mature outcomes by audience age versus lifecycle"),
              ("control_contradiction", "Window versus approved role, retention bound and platform limits"),
              ("permission_gate", "Permitted retention/use before extension proposals"),
              ("duration_test_design", "Bounded duration variants for evidence-led tests"))
    if not inv.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("membership control inventory unavailable", inv.missing)
        return
    audience_ids = sorted({_s(r.get("list_id")) for r in ctx.rows("audiences") if _s(r.get("list_id"))})
    controls: dict[str, dict] = {}
    dup = []
    for r in sorted(ctx.rows(CTRL), key=lambda r: (_s(r.get("list_id")), _s(r.get("source_platform")))):
        lid = _s(r.get("list_id"))
        if not lid:
            continue
        if lid in controls:
            dup.append(lid)
            continue
        controls[lid] = r
    if dup:
        inv.partial(f"lists with several control rows (first kept, others unassessed): {sorted(set(dup))}")
    no_ctrl = [lid for lid in audience_ids if lid not in controls]
    if no_ctrl:
        inv.partial(f"{len(no_ctrl)} lists without a membership_controls row: control state unknown",
                    [f"{CTRL}:list_id"])
    by_duration: dict[str, list[str]] = {}
    for lid, r in sorted(controls.items()):
        roles = sorted(_tokens(r.get("intended_role")))
        special = _s(r.get("nonexpiring_special_value")) and _s(r.get("observed_duration")) == _s(
            r.get("nonexpiring_special_value"))
        inv.observe(f"List {lid}: observed duration", list_id=lid, source_platform=r.get("source_platform"),
                    observed_duration=r.get("observed_duration"), units=r.get("units"),
                    nonexpiring=bool(special), roles=roles, role_specific_review=len(roles) > 1)
        by_duration.setdefault(f"{_s(r.get('observed_duration'))} {V.norm_text(r.get('units'))}", []).append(lid)
    shared = {k: v for k, v in sorted(by_duration.items()) if len(v) > 1}
    if shared:
        inv.observe("Identical durations across lists (not a defect)", groups=shared)

    defs = {_s(r.get("list_id")): r for r in ctx.rows(DEFS) if _s(r.get("list_id"))}

    def days(lid: str, raw) -> float | None:
        f = V.num(raw)
        mult = _UNIT_DAYS.get(V.norm_text(controls[lid].get("units")))
        return None if f is None or mult is None else f * mult

    def nonexpiring(lid: str) -> bool:
        r = controls[lid]
        return bool(_s(r.get("nonexpiring_special_value"))) and _s(r.get("observed_duration")) == _s(
            r.get("nonexpiring_special_value"))

    perms = {lid: _permission(ctx, lid, _s((defs.get(lid) or {}).get("source_id"))) for lid in sorted(controls)}

    def retention_limit(lid: str) -> tuple[float | None, list[str]]:
        parts, vals = [], []
        rc = days(lid, controls[lid].get("retention_constraint"))
        if rc is not None and rc > 0:
            vals.append(rc)
            parts.append(f"{CTRL}.retention_constraint={rc:g}d")
        pl = perms[lid][3]
        if pl is not None:
            vals.append(pl)
            parts.append(f"{PERM}.retention_limit_days={pl:g}")
        return (min(vals) if vals else None), parts

    # -- step 2: reset semantics
    rs = ctx.check("reset_semantics", "Entry, re-entry and reset clock semantics",
                   {DEFS: ["list_id", "entry_event", "refresh_behavior"], CTRL: ["list_id", "reset_behavior"]})
    if rs.runnable:
        for lid, r in sorted(controls.items()):
            d = defs.get(lid)
            platform = V.norm_text(r.get("source_platform"))
            clock = "upload refresh/retention" if ("customer match" in platform or "crm" in platform) \
                else "time since qualifying event"
            reset = _s(r.get("reset_behavior")) or _s((d or {}).get("refresh_behavior"))
            if not reset or d is None or not _s(d.get("entry_event")):
                rs.finding("reset_semantics_unresolved", "Info", {"list_id": lid},
                           f"List {lid}: entry/reset semantics unresolved (reset_behavior/refresh_behavior or "
                           f"entry_event missing); no duration proposal is supported",
                           evidence={"clock_type": clock, "reset_behavior": r.get("reset_behavior"),
                                     "definition_row": d is not None,
                                     "entry_event": (d or {}).get("entry_event")},
                           recommendation="Document the qualifying entry event and re-entry/reset rule.",
                           uncertainty="Unresolved clock: aligned-clock comparison impossible.")
            else:
                rs.observe(f"List {lid}: clock semantics", list_id=lid, clock_type=clock, reset_behavior=reset,
                           entry_event=d.get("entry_event"))

    # -- step 3: mature outcomes by audience age
    age = ctx.check("age_outcomes", "Mature outcomes by audience age versus lifecycle",
                    {COH: ["list_id", "age_since_entry_bucket", "business_segment", "eligible_people",
                           "qualified_outcomes", "maturity", "observation_end"],
                     LIFE: ["business_segment", "buying_cycle", "repurchase_interval", "observation_horizon_days"]})
    reviewed: list[str] = []
    if age.runnable:
        min_conv = ctx.params.get("min_conversions")
        if ctx.mature is not True:
            age.partial(f"prescriptions disabled: maturity={ctx.mature} ({ctx.maturity_note})")
        life = {}
        for r in ctx.rows(LIFE):
            life.setdefault(_s(r.get("business_segment")), []).append(
                {k: r.get(k) for k in ("buying_cycle", "repurchase_interval", "units", "observation_horizon_days",
                                       "maturity")})
        cohorts: dict[str, list[dict]] = {}
        for r in ctx.rows(COH):
            cohorts.setdefault(_s(r.get("list_id")), []).append(r)
        for lid in sorted(set(cohorts) & set(controls)):
            cur = None if nonexpiring(lid) else days(lid, controls[lid].get("observed_duration"))
            if cur is None:
                age.partial(f"list {lid}: current window not convertible to days (units "
                            f"{controls[lid].get('units')!r} or non-expiring)")
                continue
            sums = {"within": [0.0, 0.0], "beyond": [0.0, 0.0]}
            immature = straddle = bad = 0
            horizon, censored, segs = 0.0, False, set()
            for r in sorted(cohorts[lid], key=lambda r: (_s(r.get("age_since_entry_bucket")),
                                                         _s(r.get("entry_cohort_start")))):
                b = _bucket(r.get("age_since_entry_bucket"))
                elig, outc = V.num(r.get("eligible_people")), V.num(r.get("qualified_outcomes"))
                if b is None or elig is None or outc is None:
                    bad += 1
                    continue
                if not _mature(r.get("maturity")):
                    immature += 1
                    continue
                segs.add(_s(r.get("business_segment")))
                lo, hi = b
                horizon = max(horizon, hi if hi is not None else lo)
                censored = censored or hi is None
                if hi is not None and hi <= cur:
                    side = "within"
                elif lo >= cur:
                    side = "beyond"
                else:
                    straddle += 1
                    continue
                sums[side][0] += outc
                sums[side][1] += elig
            if bad or straddle:
                age.partial(f"list {lid}: {bad} unparseable and {straddle} window-straddling cohort rows excluded")
            (o_in, e_in), (o_out, e_out) = sums["within"], sums["beyond"]
            lo_lim, lo_src = retention_limit(lid)
            ev = {"current_window_days": cur, "outcomes_within": o_in, "eligible_within": e_in,
                  "rate_within": V.ratio(o_in, e_in), "outcomes_beyond": o_out, "eligible_beyond": e_out,
                  "rate_beyond": V.ratio(o_out, e_out), "immature_rows": immature, "horizon_days": horizon,
                  "open_final_bucket": censored, "min_conversions": min_conv.value,
                  "min_conversions_source": min_conv.source,
                  "lifecycle": {s: life.get(s) for s in sorted(segs)},
                  "allowed_min": V.num(controls[lid].get("allowed_min")),
                  "allowed_max": V.num(controls[lid].get("allowed_max")), "units": controls[lid].get("units"),
                  "unit_days": _UNIT_DAYS.get(V.norm_text(controls[lid].get("units"))),
                  "retention_limit_days": lo_lim, "retention_sources": lo_src,
                  "permission_status": perms[lid][0], "permission_reason": perms[lid][1],
                  "observed_duration": V.num(controls[lid].get("observed_duration"))}
            age.observe(f"List {lid}: outcomes by audience age (observational)", list_id=lid, **{
                k: ev[k] for k in ("current_window_days", "outcomes_within", "eligible_within", "rate_within",
                                   "outcomes_beyond", "eligible_beyond", "rate_beyond", "horizon_days")})
            gate = min_conv.value is not None and o_in >= min_conv.value and o_out >= min_conv.value \
                and e_in > 0 and e_out > 0
            if ctx.mature is not True or not gate or horizon <= cur or not segs & set(life):
                why = ("Ads window immature" if ctx.mature is not True else
                       "cohort horizon does not span beyond the current window" if horizon <= cur else
                       "no lifecycle row for the cohort business segment" if not segs & set(life) else
                       f"fewer than min_conversions={min_conv.value} mature outcomes on a side")
                age.finding("cohort_evidence_insufficient", "Info", {"list_id": lid},
                            f"List {lid}: cohort evidence cannot support a duration change ({why})", evidence=ev,
                            recommendation="Collect mature entry-age cohorts spanning the proposed windows.",
                            uncertainty="Right-censored or thin cohorts do not prove long ages worthless.")
                continue
            reviewed.append(lid)
            age.review("window_vs_lifecycle", {"list_id": lid},
                       f"Do mature entry-age outcomes and the lifecycle show list {lid}'s {cur:g}-day window "
                       f"mismatching its role ({sorted(_tokens(controls[lid].get('intended_role')))})?",
                       evidence=ev,
                       outcomes={"window_mismatch": {"severity": "Warning", "recommendation":
                                                     "Propose the verified duration variants (proposal.durations)."},
                                 "duration_test": {"severity": "Info", "recommendation":
                                                   "Run a bounded duration test (proposal.durations, "
                                                   "proposal.rollback_criteria)."},
                                 "no_change": {"severity": None, "recommendation": "Keep the current window."},
                                 "uncertain": {"severity": "Info", "recommendation": "Collect more mature cohorts."}},
                       guidance="Outcomes by age are observational, not incremental value. Durations in row units; "
                                "verify enforces bounds, retention limit, horizon and permission for extensions.")

    # -- step 4: contradictions with approved role, retention bound and platform limits
    con = ctx.check("control_contradiction", "Window versus approved role, retention bound and platform limits",
                    {CTRL: ["list_id", "observed_duration", "units", "allowed_min", "allowed_max",
                            "retention_constraint", "approved_duration", "intended_role"]})
    extensions: list[str] = []
    if con.runnable:
        aud = ctx.table("audiences")
        use_known = aud is not None and "campaign_id" in aud.columns
        if not use_known:
            con.partial("active use unverifiable: retention breaches capped at Warning", ["audiences:campaign_id"])
        used = {_s(r.get("list_id")): sorted({_s(x.get("campaign_id")) for x in ctx.rows("audiences")
                                               if _s(x.get("list_id")) == _s(r.get("list_id"))
                                               and _s(x.get("campaign_id"))})
                for r in ctx.rows("audiences")} if use_known else {}
        for lid, r in sorted(controls.items()):
            obs, lo, hi = V.num(r.get("observed_duration")), V.num(r.get("allowed_min")), V.num(r.get("allowed_max"))
            ent = {"list_id": lid}
            base = {"observed_duration": obs, "units": r.get("units"), "allowed_min": lo, "allowed_max": hi,
                    "source_reference": r.get("source_reference"), "checked_at": r.get("checked_at")}
            if obs is None:
                con.partial(f"list {lid}: observed_duration unknown")
                continue
            ne = nonexpiring(lid)
            if not ne and ((lo is not None and obs < lo) or (hi is not None and obs > hi)):
                con.finding("outside_platform_bounds", "Warning", ent,
                            f"List {lid}: observed duration {obs:g} {r.get('units')} outside supported "
                            f"[{lo}, {hi}]", evidence=base,
                            recommendation="Correct the control within the documented supported range.",
                            uncertainty="Bounds as supplied at checked_at; platform limits can change.")
            appr = V.num(r.get("approved_duration"))
            if appr is not None and not ne and appr != obs:
                if appr > obs:
                    extensions.append(lid)
                con.finding("approved_duration_mismatch", "Warning", ent,
                            f"List {lid}: observed {obs:g} {r.get('units')} differs from approved {appr:g}",
                            evidence={**base, "approved_duration": appr, "approved_rationale":
                                      r.get("approved_rationale") or r.get("rationale")},
                            recommendation="Align with the approved duration after the permission gate "
                                           "(extensions need permitted retention/use).",
                            uncertainty="Approval as supplied; re-confirm it is current.")
            limit, src = retention_limit(lid)
            cur = float("inf") if ne else days(lid, obs)
            if limit is None or cur is None:
                if limit is not None:
                    con.partial(f"list {lid}: units {r.get('units')!r} not convertible for the retention check")
                continue
            if cur > limit:
                campaigns = used.get(lid, [])
                ev = {**base, "observed_days": "non-expiring" if ne else cur, "retention_limit_days": limit,
                      "retention_sources": src, "active_campaigns": campaigns}
                if campaigns:
                    con.finding("retention_violation_active_use", "Critical", ent,
                                f"List {lid} is used in {len(campaigns)} campaign(s) with membership "
                                f"{'non-expiring' if ne else f'{cur:g} days'} above the approved retention limit "
                                f"{limit:g} days", evidence=ev,
                                recommendation="Reduce the window to the approved retention limit; owner and "
                                               "privacy review via skill 156.",
                                uncertainty="Limit as supplied; confirm the restriction is current.")
                else:
                    con.finding("retention_violation", "Warning", ent,
                                f"List {lid}: membership above the approved retention limit {limit:g} days; no "
                                f"active use evidenced", evidence=ev,
                                recommendation="Reduce the window to the approved retention limit.",
                                uncertainty="Active use not evidenced in audiences.")

    # -- step 5: permission gate for extension/refresh proposals
    pg = ctx.check("permission_gate", "Permitted retention/use before extension proposals",
                   {PERM: ["source_id", "list_id", "permission_status", "consent_coverage_status",
                           "permitted_destinations", "retention_limit_days", "evidence_reference"],
                    DEFS: ["list_id", "source_id"]})
    if pg.runnable:
        for lid in sorted(set(extensions) | set(reviewed)):
            status, reason, refs, limit = perms[lid]
            if status != "permitted":
                pg.finding("extension_blocked_permission", "Info", {"list_id": lid},
                           f"List {lid}: any duration extension/refresh proposal is blocked ({reason})",
                           evidence={"permission_status": status, "permission_refs": refs,
                                     "retention_limit_days": limit},
                           recommendation="Obtain permitted-use, consent and retention evidence (skill 156).",
                           uncertainty="Missing or denied permission; suppression policy stays with 103.")
            else:
                pg.observe(f"List {lid}: extension permitted by evidence", list_id=lid, refs=refs,
                           retention_limit_days=limit)
    elif extensions or reviewed:
        pg.notes.append(f"extension candidates without permission evidence: {sorted(set(extensions) | set(reviewed))}")

    # -- step 6: bounded variants
    td = ctx.check("duration_test_design", "Bounded duration variants for evidence-led tests",
                   {CTRL: ["list_id", "allowed_min", "allowed_max", "units"]})
    if td.runnable:
        for lid in reviewed:
            item = next(x for x in ctx.result.reviews if x.entity == {"list_id": lid})
            e = item.evidence
            lo, hi = e["allowed_min"], e["allowed_max"]
            if lo is None or hi is None:
                td.partial(f"list {lid}: allowed_min/max unknown; no variant range")
                continue
            caps = [hi]
            if e["retention_limit_days"] is not None and e["unit_days"]:
                caps.append(e["retention_limit_days"] / e["unit_days"])
            if e["unit_days"]:
                caps.append(e["horizon_days"] / e["unit_days"])
            td.observe(f"List {lid}: supported variant range", list_id=lid, min=lo, max=min(caps), units=e["units"],
                       note="observational outcomes; randomized eligibility preferred where feasible")


def verify(ctx, item, decision) -> list[str]:
    """Rules: proposed durations within bounds, retention limit and horizon; extensions need permission."""
    if item.condition_key != "window_vs_lifecycle" or decision.get("outcome") not in ("window_mismatch",
                                                                                       "duration_test"):
        return []
    e, p = item.evidence, decision.get("proposal") or {}
    raw = p.get("durations")
    vals = [V.num(x) for x in raw] if isinstance(raw, list) else []
    if not vals or any(v is None or v <= 0 for v in vals):
        return ["proposal.durations must be a non-empty list of positive numbers in the control's units"]
    problems = []
    if e.get("allowed_min") is None or e.get("allowed_max") is None:
        problems.append("allowed_min/allowed_max unknown: no supported variant can be verified")
    unit = e.get("unit_days")
    for v in vals:
        if e.get("allowed_min") is not None and v < e["allowed_min"]:
            problems.append(f"{v:g} below allowed_min {e['allowed_min']:g}")
        if e.get("allowed_max") is not None and v > e["allowed_max"]:
            problems.append(f"{v:g} above allowed_max {e['allowed_max']:g}")
        if unit and e.get("retention_limit_days") is not None and v * unit > e["retention_limit_days"]:
            problems.append(f"{v:g} exceeds retention limit {e['retention_limit_days']:g} days")
        if unit and v * unit > e.get("horizon_days", 0):
            problems.append(f"{v:g} exceeds the mature cohort horizon {e.get('horizon_days')} days")
        if e.get("observed_duration") is not None and v > e["observed_duration"] \
                and e.get("permission_status") != "permitted":
            problems.append(f"extension to {v:g} blocked: permission {e.get('permission_status')}")
    if decision.get("outcome") == "duration_test" and not str(p.get("rollback_criteria") or "").strip():
        problems.append("proposal.rollback_criteria required for a duration test")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
