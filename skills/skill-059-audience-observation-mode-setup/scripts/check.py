"""check.py — skill-059 deterministic audience association coverage, effective mode and owner-intent conflicts.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-059-audience-observation-mode-setup/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Universe = ENABLED/PAUSED campaigns and their ad groups, left-joined to associations; the audience table is
         never the campaign universe. Associations come from custom/audience_modes (settings export; preferred) or
         audiences with list_id|audience_id, campaign_id, ad_group_id, mode. Mode normalizes to
         TARGETING|OBSERVATION|EXCLUSION|SIGNAL|UNKNOWN; duplicates (list, campaign, ad group, mode) count once.
         Ad-group-level positive associations define that ad group's effective mode, else campaign level.
         PERFORMANCE_MAX/DEMAND_GEN associations are signals: never Observation/Targeting conflicts.
         Explicit owner intent = profile.campaign_objectives[id].audience_mode ∈ {targeting, observation}:
         a mismatch with the verified effective mode is a deterministic Warning. With only a role, the mismatch
         is an ai_review. No intent → partial, never a finding. Critical (material delivery failure from an
         unintended restriction) only via ai_review with proposal.evidence_ref.
         Optional segments only from profile.audience_use_cases [{campaign_id, list_id, question}] with the list
         evidenced eligible (audiences.eligible true); spend alone never makes an audience mandatory.
         No audience bid modifiers are proposed for Smart Bidding campaigns (verify rejects them).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial deterministic check
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

SKILL = "skill-059-audience-observation-mode-setup"
VERSION = "1.0.0"

MODES = "custom/audience_modes"
MODES_COLS = ["campaign_id", "ad_group_id", "criterion_id", "audience_id", "scope", "mode", "positive_or_exclusion",
              "status"]
SIGNAL_CHANNELS = ("PERFORMANCE_MAX", "DEMAND_GEN")
MODE_CHANNELS = ("SEARCH", "SHOPPING", "DISPLAY", "VIDEO", "HOTEL")
SMART = ("TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE")


def _up(v) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def _mode(row) -> str:
    m = _up(row.get("mode"))
    pe = _up(row.get("positive_or_exclusion"))
    if pe in ("EXCLUSION", "NEGATIVE") or m in ("EXCLUSION", "EXCLUDE") or V.boolean(row.get("exclusion")) is True:
        return "EXCLUSION"
    return {"TARGETING": "TARGETING", "TARGET": "TARGETING", "OBSERVATION": "OBSERVATION", "BID_ONLY": "OBSERVATION",
            "SIGNAL": "SIGNAL", "AUDIENCE_SIGNAL": "SIGNAL"}.get(m, "UNKNOWN")


def _source(ctx) -> tuple[str | None, str, list[str]]:
    """(table key, list column, missing) for the association source."""
    t = ctx.table(MODES)
    if t is not None and not t.missing(MODES_COLS):
        return MODES, "audience_id", []
    a = ctx.table("audiences")
    if a is not None:
        lc = "list_id" if "list_id" in a.columns or "audience_id" not in a.columns else "audience_id"
        miss = a.missing([lc, "campaign_id", "ad_group_id", "mode"])
        if not miss:
            return "audiences", lc, []
        return None, lc, [f"audiences:{c}" for c in miss] + ([f"{MODES} (file)"] if t is None else
                                                              [f"{MODES}:{c}" for c in t.missing(MODES_COLS)])
    return None, "list_id", ["audiences (file)"] + ([f"{MODES} (file)"] if t is None else
                                                    [f"{MODES}:{c}" for c in t.missing(MODES_COLS)])


def _objective(ctx, cid) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objs.items() if str(k) == cid), None) if isinstance(objs, dict) else None
    return obj if isinstance(obj, dict) else {}


def run(ctx) -> None:
    """Run audience universe join, effective mode, intent match, optional segments and bid-modifier guard checks.

    Rules:   No association source or campaign/ad_group spine skips all checks. Only mode channels are judged;
             PMax/Demand Gen stay signals. Declared audience_mode mismatch → Warning; role-only Targeting → ai_review;
             no intent → partial. Critical only via ai_review material_delivery_failure. Optional segment Info needs
             profile.audience_use_cases and an eligible list; Smart Bidding gets no bid-modifier proposal.
    """
    uni = ctx.check("association_universe", "All campaigns/ad groups left-joined to audience associations",
                    {"campaigns": ["id", "status", "channel_type"], "ad_groups": ["id", "campaign_id", "status"]})
    titles = (("effective_mode", "Effective campaign/ad-group audience mode"),
              ("intent_match", "Declared intent vs actual mechanism"),
              ("optional_segments", "Documented optional measurement segments"),
              ("proposal_guard", "Bid-modifier applicability"))
    src, lc, src_missing = _source(ctx)
    if src is None:
        uni.skip("audience association/mode evidence missing (audiences or custom/audience_modes)", src_missing)
    if not uni.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("association universe unavailable", uni.missing)
        return
    t = ctx.table(src)
    if t.complete is not True:
        uni.partial(f"{t.filename}: association completeness not certified; missing associations not provable")
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns") if _up(r.get("status")) in ("ENABLED", "PAUSED")}
    groups = {str(r.get("id")): r for r in ctx.rows("ad_groups") if str(r.get("campaign_id")) in camps}
    seen, assoc = set(), {}
    orphans = 0
    for r in t.rows:
        cid, gid = str(r.get("campaign_id") or ""), str(r.get("ad_group_id") or "")
        if cid not in camps:
            orphans += 1
            continue
        if _up(r.get("status")) not in ("ENABLED", "ACTIVE", ""):
            continue
        key = (str(r.get(lc)), cid, gid, _mode(r))
        if key in seen:
            continue
        seen.add(key)
        assoc.setdefault(cid, []).append({"list_id": key[0], "ad_group_id": gid or None, "mode": key[3],
                                          "type": r.get("audience_type") or r.get("type"),
                                          "eligible": V.boolean(r.get("eligible"))})
    mech = {cid: ("signal" if _up(c.get("channel_type")) in SIGNAL_CHANNELS else
                  "mode" if _up(c.get("channel_type")) in MODE_CHANNELS else "unsupported_or_unknown")
            for cid, c in camps.items()}
    uni.observe("Campaign universe vs associations", campaigns=len(camps),
                enabled=sorted(c for c in camps if _up(camps[c].get("status")) == "ENABLED"),
                paused=sorted(c for c in camps if _up(camps[c].get("status")) == "PAUSED"),
                with_associations=sorted(assoc), without_associations=sorted(c for c in camps if c not in assoc),
                mechanism=mech, associations_outside_universe=orphans, source=t.filename)

    # -- step 2: effective mode
    em = ctx.check("effective_mode", "Effective campaign/ad-group audience mode")
    effective: dict = {}
    for cid in sorted(camps):
        rows = assoc.get(cid, [])
        camp_level = sorted({a["mode"] for a in rows if a["ad_group_id"] is None and a["mode"] not in ("EXCLUSION",)})
        per_group = {}
        for gid in sorted(g for g, gr in groups.items() if str(gr.get("campaign_id")) == cid):
            own = sorted({a["mode"] for a in rows if a["ad_group_id"] == gid and a["mode"] != "EXCLUSION"})
            per_group[gid] = {"level": "ad_group" if own else "campaign" if camp_level else "none",
                              "modes": own or camp_level}
        modes = sorted({m for g in per_group.values() for m in g["modes"]} | set(camp_level))
        effective[cid] = {"modes": modes, "per_ad_group": per_group,
                          "exclusions": sorted({a["list_id"] for a in rows if a["mode"] == "EXCLUSION"})}
        if "UNKNOWN" in modes:
            em.partial(f"campaign {cid}: association mode unknown")
        em.observe(f"Campaign {cid}: effective audience mode", campaign_id=cid, mechanism=mech[cid], **effective[cid])

    # -- steps 3-4: intent vs mechanism
    im = ctx.check("intent_match", "Declared intent vs actual mechanism")
    cm = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
    no_intent = []
    for cid in sorted(camps):
        if mech[cid] != "mode":
            continue
        modes = set(effective[cid]["modes"])
        obj = _objective(ctx, cid)
        intent = str(obj.get("audience_mode") or "").strip().lower()
        delivery = {"impressions": V.num((cm.get(cid) or {}).get("impressions")),
                    "cost": ctx.money((cm.get(cid) or {}).get("cost")), "window": [ctx.period_start, ctx.period_end]}
        entity = {"campaign_id": cid}
        ev = {"effective_modes": sorted(modes), "per_ad_group": effective[cid]["per_ad_group"],
              "declared_audience_mode": intent or None, "role": obj.get("role"), "delivery": delivery}
        if intent in ("targeting", "observation"):
            conflict = ("TARGETING" in modes) if intent == "observation" else ("TARGETING" not in modes)
            if not conflict:
                im.observe(f"Campaign {cid}: effective mode matches declared intent", campaign_id=cid, intent=intent)
                continue
            im.finding("mode_conflicts_owner_intent", "Warning", entity,
                       f"Campaign {cid} effective audience mode {sorted(modes) or ['none']} conflicts with declared "
                       f"'{intent}' intent",
                       evidence=ev, calculation={"intent_source": f"profile.campaign_objectives[{cid}].audience_mode"},
                       recommendation=f"Request-only: set the audience setting to {intent.upper()} at the listed scope "
                                      "after owner confirmation; do not attach lists.",
                       uncertainty="A mode conflict does not by itself prove lost delivery.")
            if intent == "observation":
                im.review("unintended_restriction_delivery_failure", entity,
                          f"Does the unintended Targeting restriction on campaign {cid} directly cause a material "
                          "delivery failure?",
                          evidence=ev,
                          outcomes={"material_delivery_failure": {"severity": "Critical", "recommendation":
                                                                  "Prioritize switching to Observation; cite the evidence."},
                                    "not_established": {"severity": None, "recommendation": "Keep the Warning."}},
                          guidance="Needs observed reach/delivery evidence AND a confirmed restrictive path; low "
                                   "delivery alone is not proof. Supply proposal.evidence_ref.")
        elif "TARGETING" in modes and obj.get("role"):
            im.review("targeting_vs_role", entity,
                      f"Does Targeting on campaign {cid} deliberately serve its '{obj.get('role')}' objective?",
                      evidence=ev,
                      outcomes={"deliberate_constrained": {"severity": "Info", "recommendation":
                                                           "Document the constrained objective; no change."},
                                "conflicts_with_intent": {"severity": "Warning", "recommendation":
                                                          "Propose Observation at the listed scope for owner review."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask the owner for audience_mode."}},
                      guidance="Targeting is legitimate for dedicated remarketing or intentional constrained "
                               "acquisition. Use only profile role/objectives; for conflicts_with_intent give "
                               "proposal {campaign_id, proposed_mode}.")
        elif "TARGETING" in modes:
            no_intent.append(cid)
    if no_intent:
        im.partial(f"owner intent missing for Targeting campaigns {no_intent}: accidental restriction not assessable")

    # -- steps 5-6: optional segments
    op = ctx.check("optional_segments", "Documented optional measurement segments")
    cases = ctx.profile.get("audience_use_cases") or []
    lists = {}
    for r in t.rows:
        lists.setdefault(str(r.get(lc)), set()).add(V.boolean(r.get("eligible")))
    if not cases:
        op.partial("no profile.audience_use_cases: optional segment relevance not assessable")
        ranked = sorted(((ctx.money((cm.get(c) or {}).get("cost")) or 0.0, c) for c in camps
                         if mech[c] == "mode" and "OBSERVATION" not in effective[c]["modes"]), reverse=True)
        op.observe("Campaigns without Observation audiences by cost (triage only, not a defect)",
                   campaigns=[{"campaign_id": c, "cost": v} for v, c in ranked])
    for case in cases if isinstance(cases, list) else []:
        cid, lid = str(case.get("campaign_id") or ""), str(case.get("list_id") or "")
        if cid not in camps or mech.get(cid) != "mode":
            op.partial(f"use case {cid}/{lid}: campaign not in universe or channel lacks Observation")
            continue
        if any(a["list_id"] == lid for a in assoc.get(cid, [])):
            continue
        if lists.get(lid) != {True}:
            op.partial(f"use case {cid}/{lid}: list eligibility not evidenced; no proposal")
            continue
        op.finding("optional_measurement_segment", "Info", {"campaign_id": cid, "list_id": lid},
                   f"Eligible list {lid} is not observed on campaign {cid} for the documented question",
                   evidence={"question": case.get("question"), "campaign_cost": ctx.money((cm.get(cid) or {}).get("cost"))},
                   recommendation="Request-only: add as OBSERVATION after owner review; name the review window.",
                   uncertainty="Configured coverage is not incremental performance.")

    # -- step 7: modifier applicability
    pg = ctx.check("proposal_guard", "Bid-modifier applicability", {"campaigns": ["bidding_strategy_type"]})
    if pg.runnable:
        smart = sorted(c for c in camps if _up(camps[c].get("bidding_strategy_type")) in SMART)
        pg.observe("Smart Bidding campaigns: no ordinary audience bid modifiers proposed", campaigns=smart,
                   performance_comparisons="skill-060", list_health="skill-061/062")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs evidence_ref; Warning proposals name the reviewed campaign and a valid mode, no modifier
    under Smart Bidding."""
    outcome, prop = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_delivery_failure" and not prop.get("evidence_ref"):
        return ["material delivery failure needs proposal.evidence_ref"]
    if outcome != "conflicts_with_intent":
        return []
    problems = []
    cid = str(prop.get("campaign_id") or "")
    if cid != item.entity["campaign_id"]:
        problems.append(f"proposal.campaign_id must be {item.entity['campaign_id']}")
    if _up(prop.get("proposed_mode")) not in ("OBSERVATION", "TARGETING"):
        problems.append("proposal.proposed_mode must be OBSERVATION or TARGETING")
    camp = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), {})
    if prop.get("bid_modifier") is not None and _up(camp.get("bidding_strategy_type")) in SMART:
        problems.append("no audience bid modifier under Smart Bidding")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
