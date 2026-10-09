"""check.py — skill-048 deterministic modifier inventory, control semantics, precedence, age and segment gates.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-048-bid-adjustment-layer-review/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #23 Automate your in-market audience bidding (Brainlabs) — clean-room reimplementation of
         audience-segment CPA vs campaign CPA comparison; bid changes become review-only proposals
         index #24 Apply modifiers to in-market audiences based on performance (Brainlabs) — clean-room
         reimplementation of the performance screen only; no modifier is computed or applied
         index #26 Extended Devices, Locations and Audiences Bidding (Brainlabs) — clean-room reimplementation of
         per-dimension segment-vs-baseline comparison with sample gates on BOTH sides; no auto bidding
rules:   bid_adjustments.modifier is an API multiplier (1.2 = +20%, 0 = -100%); cells ending in % are adjustments
         (+20% → 1.2). excluded=true or multiplier 0 = exclusion. Neutral 1.0 is not an active setting.
         Control effect comes ONLY from external/modifier_controls matched on channel/strategy/dimension/level
         (blank/ANY subtype = any) with effective_date <= as_of, latest wins; unmatched/ambiguous = unknown and
         never a recommendation. Smart Bidding is never assumed to ignore or honor a modifier.
         CPA_target controls: effective target = resolved base tCPA × multiplier (not a CPC change).
         Precedence only from the documented combination_rule (override|multiply); unknown rule → partial.
         Age only from modifier_history changed_at (exact) or effective_from (lower bound); > 90 days = Info cue.
         Segment comparisons need ctx.mature True, one goal_cohort, min_conversions (CPA) / min_clicks (CVR) on
         BOTH segment and baseline. Baseline = other segments only for mutually exclusive dimensions
         (_EXCLUSIVE); overlapping dimensions (audiences) compare to campaign_metrics totals only when the segment
         dates equal the account period. Excluded segments have no counterfactual.
         Intent contradiction (Warning) is AI review; verify() demands a reviewed segment/setting id and forbids
         modifier sizing without proposal.economics_ref.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial deterministic check
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

SKILL = "skill-048-bid-adjustment-layer-review"
VERSION = "1.0.0"

_CTRL = "external/modifier_controls"
_HIST = "custom/modifier_history"
_SEG = "custom/modifier_segment_daily"
_EXCLUSIVE = {"DEVICE", "AD_SCHEDULE", "AGE_RANGE", "GENDER", "HOUSEHOLD_INCOME", "PARENTAL_STATUS"}
_SUPPORTED = {"CPC", "CPA_TARGET", "EXCLUSION"}
_AGE_DAYS = 90


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _up(v) -> str:
    return _s(v).upper()


def _mult(v) -> float | None:
    s = _s(v)
    if s.endswith("%"):
        f = V.num(s[:-1])
        return None if f is None else 1 + f / 100
    return V.num(v)


def _strategy(ctx, camp: dict) -> str:
    t = _up(camp.get("bidding_strategy_type"))
    if t:
        return t
    sid = _s(camp.get("bidding_strategy_id") or camp.get("strategy_id"))
    row = next((r for r in ctx.rows("bidding_strategies") if _s(r.get("id")) == sid), None) if sid else None
    return _up(row.get("type")) if row else ""


def _settings(ctx, inv) -> list[dict]:
    camps = {_s(c.get("id")): c for c in ctx.rows("campaigns")}
    groups = {_s(g.get("id")): _s(g.get("campaign_id")) for g in ctx.rows("ad_groups")}
    out = []
    for r in ctx.rows("bid_adjustments"):
        cid, gid = _s(r.get("campaign_id")), _s(r.get("ad_group_id"))
        camp = camps.get(cid)
        if camp is None:
            inv.partial(f"bid adjustment for campaign {cid} not in campaigns inventory")
            continue
        if gid and gid in groups and groups[gid] != cid:
            inv.partial(f"ad group {gid} belongs to campaign {groups[gid]}, not {cid}; row ignored")
            continue
        m = _mult(r.get("modifier"))
        excl = V.boolean(r.get("excluded")) is True or m == 0
        out.append({"campaign_id": cid, "ad_group_id": gid or None, "level": "AD_GROUP" if gid else "CAMPAIGN",
                    "dimension": _up(r.get("dimension")), "criterion_id": _s(r.get("criterion_id")),
                    "segment": r.get("segment_value"), "multiplier": m, "excluded": excl,
                    "channel": _up(camp.get("channel_type")), "subtype": _up(camp.get("channel_subtype")),
                    "strategy": _strategy(ctx, camp), "campaign_status": camp.get("status")})
    return sorted(out, key=lambda s: (s["campaign_id"], s["dimension"], s["criterion_id"], s["level"],
                                      s["ad_group_id"] or ""))


def _control(ctx, s: dict) -> tuple[dict | None, str]:
    cands = []
    for r in ctx.rows(_CTRL):
        if (_up(r.get("channel")), _up(r.get("strategy")), _up(r.get("dimension")), _up(r.get("level"))) != (
                s["channel"], s["strategy"], s["dimension"], s["level"]):
            continue
        sub = _up(r.get("subtype"))
        if sub not in ("", "ANY", "*") and sub != s["subtype"]:
            continue
        d = V.parse_date(r.get("effective_date"))
        if d is None or (ctx.as_of and d > ctx.as_of):
            continue
        cands.append((d, r))
    if not cands:
        return None, "no control row for channel/strategy/dimension/level at as_of"
    latest = max(d for d, _ in cands)
    top = [r for d, r in cands if d == latest]
    if len({_up(r.get("control_effect")) for r in top}) > 1:
        return None, f"conflicting control rows effective {latest}"
    return top[0], ""


def run(ctx) -> None:
    """Run bid-modifier inventory, control-effect mapping, age, segment comparison and intent review.

    Rules:   Control effect only from matching external/modifier_controls; unmatched/ambiguous → unknown, no
             recommendation. Ignored/unsupported settings and > 90-day age are Info. Segment comparisons need ctx.mature
             True, one goal cohort and min_conversions/min_clicks on segment AND baseline; excluded segments have no
             counterfactual. Intent contradiction is Warning only via ai_review; modifier sizing needs
             proposal.economics_ref (verify()).
    """
    inv = ctx.check("setting_inventory", "Inventory every dimension at campaign and ad-group level (step 1)",
                    {"bid_adjustments": ["campaign_id", "dimension", "criterion_id", "modifier"],
                     "campaigns": ["id", "channel_type", "bidding_strategy_type"]})
    later = (("control_semantics", "Effective control per setting from the control matrix (steps 2-3)"),
             ("exclusion_intent", "Supported exclusions and modifiers vs documented intent (step 4)"),
             ("layer_precedence", "Campaign/ad-group precedence by documented rule (step 5)"),
             ("setting_age", "Setting age from dated history (step 6)"),
             ("segment_outcomes", "Matched mature segment outcomes (step 7; index #23/#24/#26)"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("modifier inventory unavailable", inv.missing)
        return
    settings = _settings(ctx, inv)
    unknown = [s for s in settings if s["multiplier"] is None and not s["excluded"]]
    if unknown:
        inv.partial(f"{len(unknown)} settings with unknown modifier value")
    counts: dict[str, int] = {}
    for s in settings:
        k = f"{s['dimension']}@{s['level']}"
        counts[k] = counts.get(k, 0) + 1
    inv.observe("Modifier settings by dimension and level", settings=len(settings), by_dimension_level=counts,
                exclusions=sum(1 for s in settings if s["excluded"]),
                neutral=sum(1 for s in settings if s["multiplier"] == 1 and not s["excluded"]))

    sem = ctx.check(*later[0], {_CTRL: ["channel", "subtype", "strategy", "dimension", "level", "effective_date",
                                        "control_effect", "official_source_url", "checked_at"]})
    for s in settings:
        s["control"], s["control_note"] = (_control(ctx, s) if sem.runnable else (None, "control matrix missing"))
        s["effect"] = _up(s["control"].get("control_effect")) if s["control"] else None
    if sem.runnable:
        unresolved = [s for s in settings if s["effect"] is None]
        if unresolved:
            sem.partial(f"{len(unresolved)} settings without a resolvable control effect; no change recommended")
        for s in settings:
            if s["effect"] is None:
                continue
            ent = {"campaign_id": s["campaign_id"], "ad_group_id": s["ad_group_id"], "dimension": s["dimension"],
                   "criterion_id": s["criterion_id"]}
            src = {"control_effect": s["effect"], "official_source_url": s["control"].get("official_source_url"),
                   "checked_at": s["control"].get("checked_at"), "strategy": s["strategy"], "channel": s["channel"]}
            if s["effect"] == "CPA_TARGET" and s["multiplier"] not in (None, 0):
                base, bsrc = ctx.params.target_cpa(s["campaign_id"])
                sem.observe(f"Campaign {s['campaign_id']} {s['dimension']} {s['criterion_id']}: CPA-target modifier",
                            **ent, **src, multiplier=s["multiplier"], base_target_cpa=base, base_target_source=bsrc,
                            effective_segment_target_cpa=None if base is None else base * s["multiplier"],
                            note="Adjusts the segment CPA target, not CPC.")
            elif s["effect"] in ("IGNORED", "UNSUPPORTED") and (s["excluded"] or s["multiplier"] not in (None, 1)):
                sem.finding("ignored_or_unsupported_setting", "Info", ent,
                            f"{s['dimension']} setting {s['criterion_id']} on campaign {s['campaign_id']} is "
                            f"{s['effect'].lower()} under {s['strategy']} per the supplied control matrix",
                            evidence={**src, "multiplier": s["multiplier"], "excluded": s["excluded"]},
                            recommendation="Document or tidy the legacy setting; removal is optional and needs approval.",
                            uncertainty="Control semantics as of the matrix checked_at date; platform behavior may change.")
            else:
                sem.observe(f"Campaign {s['campaign_id']} {s['dimension']} {s['criterion_id']}: {s['effect']}",
                            **ent, **src, multiplier=s["multiplier"], excluded=s["excluded"])

    intent = ctx.check(*later[1], {_CTRL: ["channel", "strategy", "dimension", "level", "control_effect",
                                           "intended_setting"]})
    if intent.runnable:
        undocumented = 0
        for s in settings:
            active = s["excluded"] or s["multiplier"] not in (None, 1)
            if not active or s["effect"] not in _SUPPORTED:
                continue
            ctrl = s["control"]
            ent = {"campaign_id": s["campaign_id"], "ad_group_id": s["ad_group_id"], "dimension": s["dimension"],
                   "criterion_id": s["criterion_id"]}
            ev = {"multiplier": s["multiplier"], "excluded": s["excluded"], "control_effect": s["effect"],
                  "intended_setting": ctrl.get("intended_setting"), "rationale": ctrl.get("rationale"),
                  "owner": ctrl.get("owner"), "strategy": s["strategy"], "segment_value": s["segment"],
                  "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(s["campaign_id"])}
            if not _s(ctrl.get("intended_setting")) and not s["excluded"]:
                undocumented += 1
                continue
            intent.review("setting_contradicts_intent", ent,
                          f"Does the supported {s['dimension']} {'exclusion' if s['excluded'] else 'modifier'} "
                          f"{s['criterion_id']} on campaign {s['campaign_id']} contradict the documented intent?",
                          evidence=ev,
                          outcomes={"contradicts_intent": {"severity": "Warning", "recommendation":
                                                           "Owner reviews the setting against the brief; change only with approval."},
                                    "intentional": {"severity": None, "recommendation": "Keep; document the intent."},
                                    "uncertain": {"severity": "Info", "recommendation": "Request the settings brief."}},
                          guidance="An intentional exclusion is not a defect. Use only intended_setting/rationale and "
                                   "profile objectives; no performance sizing here.")
        if undocumented:
            intent.partial(f"{undocumented} supported settings without documented intended_setting")

    prec = ctx.check(*later[2], {"bid_adjustments": ["campaign_id", "ad_group_id", "dimension", "criterion_id"],
                                 _CTRL: ["dimension", "level", "combination_rule"]})
    if prec.runnable:
        by_key: dict[tuple, list[dict]] = {}
        for s in settings:
            by_key.setdefault((s["campaign_id"], s["dimension"], s["criterion_id"]), []).append(s)
        for key, rows in sorted(by_key.items()):
            camp = [s for s in rows if s["level"] == "CAMPAIGN"]
            grp = [s for s in rows if s["level"] == "AD_GROUP"]
            if not camp or not grp:
                continue
            for g in grp:
                rule = _s((g["control"] or {}).get("combination_rule")).lower()
                c = camp[0]
                if "overrid" in rule or "supersed" in rule:
                    eff, how = g["multiplier"], "ad-group setting overrides campaign"
                elif "multipl" in rule:
                    eff = None if None in (c["multiplier"], g["multiplier"]) else c["multiplier"] * g["multiplier"]
                    how = "campaign × ad-group"
                else:
                    prec.partial(f"{key}: combination rule unknown; layers not resolved")
                    continue
                prec.observe(f"Campaign {key[0]} {key[1]} {key[2]}: layered setting resolved ({how})",
                             campaign_id=key[0], ad_group_id=g["ad_group_id"], dimension=key[1], criterion_id=key[2],
                             campaign_multiplier=c["multiplier"], ad_group_multiplier=g["multiplier"],
                             effective_multiplier=eff, rule=rule,
                             note="Different values under an override rule are a valid override, not a conflict.")

    age = ctx.check(*later[3], {_HIST: ["campaign_id", "dimension", "criterion_id", "effective_from", "changed_at",
                                        "new_modifier"]})
    if age.runnable:
        if ctx.as_of is None:
            age.skip("as_of unknown")
        else:
            _age(ctx, age, settings)

    seg = ctx.check(*later[4], {_SEG: ["campaign_id", "dimension", "segment_id", "date", "impressions", "clicks",
                                       "cost", "conversions", "goal_cohort"]})
    if seg.runnable:
        _segments(ctx, seg, settings)


def _age(ctx, age, settings) -> None:
    hist: dict[tuple, list[dict]] = {}
    for h in ctx.rows(_HIST):
        key = (_s(h.get("campaign_id")), _s(h.get("ad_group_id")), _up(h.get("dimension")), _s(h.get("criterion_id")))
        hist.setdefault(key, []).append(h)
    unknown = 0
    for s in settings:
        rows = hist.get((s["campaign_id"], s["ad_group_id"] or "", s["dimension"], s["criterion_id"]), [])
        exact = sorted(d for h in rows if (d := V.parse_date(h.get("changed_at"))))
        lower = sorted(d for h in rows if (d := V.parse_date(h.get("effective_from"))))
        if exact:
            since, bound = exact[-1], "exact"
        elif lower:
            since, bound = lower[0], "lower_bound"
        else:
            unknown += 1
            continue
        days = (ctx.as_of - since).days
        ent = {"campaign_id": s["campaign_id"], "ad_group_id": s["ad_group_id"], "dimension": s["dimension"],
               "criterion_id": s["criterion_id"]}
        ev = {"since": since, "age_days": days, "age_basis": bound, "as_of": ctx.as_of, "threshold_days": _AGE_DAYS,
              "multiplier": s["multiplier"], "excluded": s["excluded"]}
        if days > _AGE_DAYS and (s["excluded"] or s["multiplier"] not in (None, 1)):
            age.finding("old_setting_review_cue", "Info", ent,
                        f"{s['dimension']} setting {s['criterion_id']} on campaign {s['campaign_id']} unchanged for "
                        f"{'at least ' if bound == 'lower_bound' else ''}{days} days",
                        evidence=ev, recommendation="Review whether the setting still reflects intent; age alone is "
                                                    "not a reason to remove it.",
                        uncertainty="Age is a review cue, not proof of staleness.")
        else:
            age.observe(f"Setting {s['criterion_id']} age {days}d ({bound})", **ent, **ev)
    if unknown:
        age.partial(f"{unknown} settings without dated history; age unknown")


def _segments(ctx, seg, settings) -> None:
    if ctx.mature is not True:
        seg.partial(f"conversion maturity not established ({ctx.maturity_note}); descriptive totals only")
    min_conv, min_clicks = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
    agg: dict[tuple, dict[str, list]] = {}
    dates: dict[tuple, set] = {}
    unknown = 0
    for r in ctx.rows(_SEG):
        key = (_s(r.get("campaign_id")), _up(r.get("dimension")), _s(r.get("goal_cohort")))
        vals = [V.num(r.get("impressions")), V.num(r.get("clicks")), ctx.money(r.get("cost")),
                V.num(r.get("conversions"))]
        if None in vals or not key[2]:
            unknown += 1
            continue
        a = agg.setdefault(key, {}).setdefault(_s(r.get("segment_id")), [0.0, 0.0, 0.0, 0.0])
        for i, v in enumerate(vals):
            a[i] += v
        dates.setdefault(key, set()).add(_s(r.get("date"))[:10])
    if unknown:
        seg.partial(f"{unknown} segment rows with unknown metrics or goal_cohort excluded")
    by_setting = {(s["campaign_id"], s["dimension"], s["criterion_id"]): s for s in settings if s["level"] == "CAMPAIGN"}
    totals = {_s(m.get("campaign_id")): m for m in ctx.rows("campaign_metrics")}
    period = {str(ctx.period_start), str(ctx.period_end)} if ctx.period_start and ctx.period_end else set()
    for key, segs in sorted(agg.items()):
        cid, dim, goal = key
        exclusive = dim in _EXCLUSIVE
        span = sorted(dates[key])
        full_period = bool(period) and span and span[0] == str(ctx.period_start) and span[-1] == str(ctx.period_end)
        if not exclusive and not (full_period and cid in totals):
            seg.partial(f"campaign {cid} {dim}: overlapping segments need campaign totals for the same dates")
            continue
        rows = []
        for sid, a in sorted(segs.items()):
            if exclusive:
                b = [sum(o[i] for k, o in segs.items() if k != sid) for i in range(4)]
                base_src = "other segments of the same dimension (mutually exclusive)"
            else:
                m = totals[cid]
                b = [V.num(m.get("impressions")), V.num(m.get("clicks")), ctx.money(m.get("cost")),
                     V.num(m.get("conversions"))]
                base_src = "campaign_metrics total for the same period (overlapping dimension)"
                if None in b:
                    continue
            s = by_setting.get((cid, dim, sid))
            cpa_ok = min_conv.value is not None and a[3] >= min_conv.value and b[3] >= min_conv.value
            cvr_ok = min_clicks.value is not None and a[1] >= min_clicks.value and b[1] >= min_clicks.value
            row = {"segment_id": sid, "clicks": a[1], "cost": a[2], "conversions": a[3],
                   "cpa": V.ratio(a[2], a[3]), "cvr": V.ratio(a[3], a[1]),
                   "baseline_clicks": b[1], "baseline_cost": b[2], "baseline_conversions": b[3],
                   "baseline_cpa": V.ratio(b[2], b[3]), "baseline_cvr": V.ratio(b[3], b[1]),
                   "cpa_index": V.ratio(V.ratio(a[2], a[3]), V.ratio(b[2], b[3])) if cpa_ok else None,
                   "cvr_index": V.ratio(V.ratio(a[3], a[1]), V.ratio(b[3], b[1])) if cvr_ok else None,
                   "cpa_sample_ok": cpa_ok, "cvr_sample_ok": cvr_ok,
                   "current_multiplier": s["multiplier"] if s else None, "excluded": s["excluded"] if s else None,
                   "control_effect": s["effect"] if s else None}
            rows.append(row)
        ent = {"campaign_id": cid, "dimension": dim, "goal_cohort": goal}
        window = [span[0], span[-1]] if span else None
        seg.observe(f"Campaign {cid} {dim} ({goal}): {len(rows)} segments vs baseline", **ent, window=window,
                    baseline=base_src if rows else None, segments=rows, min_conversions=min_conv.value,
                    min_clicks=min_clicks.value, currency=ctx.currency)
        cands = [r for r in rows if (r["cpa_sample_ok"] or r["cvr_sample_ok"]) and r["control_effect"] in
                 ("CPC", "CPA_TARGET") and not r["excluded"]]
        if ctx.mature is not True or not cands:
            if rows and not cands:
                seg.observe(f"Campaign {cid} {dim}: no segment with supported control and qualifying samples", **ent)
            continue
        seg.review("segment_supports_control_review", ent,
                   f"Do these mature, sample-qualified {dim} segments of campaign {cid} support a bounded control review?",
                   evidence={"segments": cands, "window": window, "baseline": base_src,
                             "min_conversions": min_conv.value, "min_clicks": min_clicks.value},
                   outcomes={"bounded_review_supported": {"severity": "Warning", "recommendation":
                                                          "Propose an intended-control review or bounded test within business economics."},
                             "no_issue": {"severity": None, "recommendation": "No change."},
                             "uncertain": {"severity": "Info", "recommendation": "Wait for more mature data."}},
                   guidance="Differences can reflect mix, tracking or landing pages. bounded_review_supported needs "
                            "proposal.segment_id from evidence; any modifier value needs proposal.economics_ref.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: segment reviews cite an evidenced segment; modifier sizing needs an economics reference."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    problems = []
    if item.condition_key == "segment_supports_control_review" and outcome == "bounded_review_supported":
        ids = {s["segment_id"] for s in item.evidence.get("segments", [])}
        if _s(proposal.get("segment_id")) not in ids:
            problems.append(f"proposal.segment_id must be one of {sorted(ids)}")
    if outcome in ("bounded_review_supported", "contradicts_intent") and "modifier" in proposal \
            and not _s(proposal.get("economics_ref")):
        problems.append("modifier sizing needs proposal.economics_ref (no fixed +/- from raw CPA ratios)")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
