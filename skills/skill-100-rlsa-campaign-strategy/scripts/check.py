"""check.py — skill-100 deterministic RLSA mode/eligibility, control applicability and gated outcome comparison.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-100-rlsa-campaign-strategy/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Scope = campaigns.channel_type SEARCH only; associations from custom/rlsa_associations with
         association_status ENABLED/ACTIVE (unknown status → coverage). mode → TARGETING|OBSERVATION|EXCLUSION.
         Approved intent from external/rlsa_intent_controls (ad-group row first, then campaign row):
         intended_audience_role → TARGETING (targeting/dedicated/audience-only) | OBSERVATION | EXCLUSION;
         desired_reach full/unrestricted/all → FULL, audience_only/restricted/members_only → RESTRICTED.
         Unknown intent → partial, never a mode change (SKILL: no Targeting→Observation without intended reach).
         Literal mode vs literal approved intent = deterministic Warning; Critical only via review
         'material_block_evidenced' with proposal.evidence_ref.
         Audience rows overlap and are NEVER summed across lists; campaign totals are not a nonmember
         baseline. A comparison needs a comparator row whose segmentation_definition names nonmember /
         mutually-exclusive population, the same goal_set_id, ctx.mature True and both-sided min_clicks
         (CVR) / min_conversions (CPA) gates.
         modifier is a signed fractional adjustment (0.2 = +20%; '20%' cells divided by 100). A nonzero
         modifier where supported_audience_bid_control is false → Info (no effect; route 048), never a Smart
         Bidding CPC prescription.
         Test proposals need supported control true, permission 'permitted' and a gated comparison;
         verify() checks scope, rollback criteria and that the list stays the reviewed one.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial deterministic check
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

SKILL = "skill-100-rlsa-campaign-strategy"
VERSION = "1.0.0"

ASSOC = "custom/rlsa_associations"
PERF = "custom/rlsa_performance"
INTENT = "external/rlsa_intent_controls"
DEFS = "external/audience_definitions"
PERM = "external/activation_permissions"
_INELIGIBLE = {"ineligible", "not eligible", "not_eligible", "too small", "too_small", "closed", "disabled"}
_GRANTED = {"granted", "approved", "permitted", "verified", "yes", "true"}
_DENIED = {"denied", "revoked", "withdrawn", "rejected", "expired", "no", "false"}
_CONSENT_OK = {"covered", "complete", "verified", "not_required", "not required", "not_applicable", "not applicable"}
_ADS_DEST = {"google ads", "google_ads", "google-ads", "ads"}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _tokens(v) -> set[str]:
    return {V.norm_text(x) for x in V.split_list(v)}


def _mode(v) -> str | None:
    s = V.norm_text(v)
    if "exclu" in s:
        return "EXCLUSION"
    if "observ" in s or "bid only" in s:
        return "OBSERVATION"
    if "target" in s or "dedicated" in s or "audience only" in s or "audience_only" in s:
        return "TARGETING"
    return None


def _reach(v) -> str | None:
    s = V.norm_text(v).replace("_", " ")
    if s in ("full", "unrestricted", "all", "all searchers", "broad"):
        return "FULL"
    if s in ("audience only", "restricted", "members only"):
        return "RESTRICTED"
    return None


def _modifier(v) -> float | None:
    s = _s(v)
    if not s:
        return None
    return V.rate(s, "fraction")


def _permission(ctx, list_id: str, source_id: str) -> tuple[str, str, list]:
    t = ctx.table(PERM)
    if t is None:
        return "unknown", f"{PERM} (file) missing", []
    rows = [r for r in t.rows if (list_id and _s(r.get("list_id")) == list_id)
            or (not _s(r.get("list_id")) and source_id and _s(r.get("source_id")) == source_id)]
    if not rows:
        return "unknown", f"no permission row for list {list_id} / source {source_id or '-'}", []
    refs = sorted({_s(r.get("evidence_reference")) for r in rows if _s(r.get("evidence_reference"))})
    if any(V.norm_text(r.get("permission_status")) in _DENIED for r in rows):
        return "denied", "permission_status denied/revoked", refs
    for r in rows:
        if (V.norm_text(r.get("permission_status")) in _GRANTED
                and V.norm_text(r.get("consent_coverage_status")) in _CONSENT_OK
                and _tokens(r.get("permitted_destinations")) & _ADS_DEST):
            return "permitted", "granted, consent covered, Google Ads destination permitted", refs
    return "unknown", "permission, consent coverage or Google Ads destination not evidenced", refs


def _critical_review(chk, key, entity, question, ev):
    chk.review(key, entity, question, evidence=ev,
               outcomes={"material_block_evidenced": {"severity": "Critical", "recommendation":
                                                      "Prioritize the correction; cite delivery evidence."},
                         "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
               guidance="Critical needs proposal.evidence_ref to supplied delivery evidence (e.g. lost eligible "
                        "impressions for approved Search reach).")


def run(ctx) -> None:
    """Join Search RLSA associations, then run mode, permission, outcome, control-applicability and test checks.

    Rules:   Missing association inventory → all 6 checks skipped. Warning only for Targeting on an ineligible list or
             mode vs literal approved intent; missing intent → partial. Critical only via 'material_block_evidenced' ai_review.
             Comparisons need a comparator row, ctx.mature and both-sided min_clicks/min_conversions; test ai_review
             (Info max) needs supported control and permission 'permitted'. Denied permission / inert modifier → Info.
    """
    inv = ctx.check("search_inventory", "Join Search parent inventory to audience criteria",
                    {"campaigns": ["id", "channel_type"], "ad_groups": ["id", "campaign_id"],
                     ASSOC: ["campaign_id", "ad_group_id", "criterion_id", "list_id", "association_status", "mode",
                             "eligibility", "inventory_complete"]})
    titles = (("mode_vs_reach", "Observed mode and eligibility versus approved reach"),
              ("permission_gate", "Permitted use for audience additions or reuse"),
              ("segmented_outcomes", "Mature, goal-comparable, both-sided gated outcomes"),
              ("control_applicability", "Bid-control applicability before modifier proposals"),
              ("test_opportunity", "Bounded audience test proposals"))
    if not inv.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("Search audience inventory unavailable", inv.missing)
        return
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}
    search = sorted(c for c, r in camps.items() if V.norm_text(r.get("channel_type")) == "search")
    groups = {_s(r.get("id")): _s(r.get("campaign_id")) for r in ctx.rows("ad_groups")}
    assoc, unknown, non_search, orphan = [], 0, 0, 0
    for r in sorted(ctx.rows(ASSOC), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                                    _s(r.get("list_id")), _s(r.get("criterion_id")))):
        cid, gid = _s(r.get("campaign_id")), _s(r.get("ad_group_id"))
        if cid not in camps or (gid and groups.get(gid) != cid):
            orphan += 1
            continue
        if cid not in search:
            non_search += 1
            continue
        st = _s(r.get("association_status")).upper()
        if st not in ("ENABLED", "ACTIVE"):
            unknown += st in ("", "UNKNOWN")
            continue
        assoc.append({"campaign_id": cid, "ad_group_id": gid, "criterion_id": _s(r.get("criterion_id")),
                      "list_id": _s(r.get("list_id")), "mode": _mode(r.get("mode")), "raw_mode": r.get("mode"),
                      "eligibility": r.get("eligibility"), "modifier": _modifier(r.get("modifier")),
                      "combination_logic": r.get("combination_logic")})
    if orphan:
        inv.partial(f"{orphan} association rows outside the campaign/ad-group inventory", [f"{ASSOC}:campaign_id"])
    if unknown:
        inv.partial(f"{unknown} association rows with unknown association_status not evaluated")
    if not all(V.boolean(r.get("inventory_complete")) is True for r in ctx.rows(ASSOC)):
        inv.partial("association inventory not certified complete: 'no audience' cannot be proven")
    mixed = sorted({a["campaign_id"] for a in assoc if a["ad_group_id"]} & {a["campaign_id"] for a in assoc
                                                                          if not a["ad_group_id"]})
    inv.observe("Search audience inventory", search_campaigns=len(search), active_associations=len(assoc),
                campaigns_without_audiences=sorted(set(search) - {a["campaign_id"] for a in assoc}),
                non_search_rows_ignored=non_search, mixed_level_campaigns=mixed,
                note="absent audiences or modifiers are not defects")
    if mixed:
        inv.partial(f"campaigns with both campaign- and ad-group-level criteria need inheritance review: {mixed}")

    intents: dict[tuple[str, str], dict] = {}
    for r in ctx.rows(INTENT):
        intents.setdefault((_s(r.get("campaign_id")), _s(r.get("ad_group_id"))), r)

    def intent_for(a) -> dict | None:
        return intents.get((a["campaign_id"], a["ad_group_id"])) or intents.get((a["campaign_id"], ""))

    # -- step 2: mode vs approved reach
    mv = ctx.check("mode_vs_reach", "Observed mode and eligibility versus approved reach",
                   {ASSOC: ["mode", "eligibility"],
                    INTENT: ["campaign_id", "ad_group_id", "intended_audience_role", "desired_reach"]})
    if mv.runnable:
        no_intent = set()
        for a in assoc:
            it = intent_for(a)
            entity = {"campaign_id": a["campaign_id"], "ad_group_id": a["ad_group_id"] or None,
                      "criterion_id": a["criterion_id"], "list_id": a["list_id"]}
            role = _mode((it or {}).get("intended_audience_role"))
            reach = _reach((it or {}).get("desired_reach"))
            ev = {"observed_mode": a["mode"], "raw_mode": a["raw_mode"], "eligibility": a["eligibility"],
                  "intended_role": (it or {}).get("intended_audience_role"),
                  "desired_reach": (it or {}).get("desired_reach"), "intent_owner": (it or {}).get("owner"),
                  "checked_at": (it or {}).get("checked_at")}
            if a["mode"] == "TARGETING" and V.norm_text(a["eligibility"]) in _INELIGIBLE:
                mv.finding("targeting_ineligible_list", "Warning", entity,
                           f"Targeting list {a['list_id']} in campaign {a['campaign_id']} is '{a['eligibility']}' "
                           f"for Search: restricted reach may not serve", evidence=ev,
                           recommendation="Check list health (skill 061) before keeping Targeting.",
                           uncertainty="Eligibility as of the snapshot; delivery loss not measured.")
                _critical_review(mv, "targeting_ineligible_list", entity,
                                 f"Does ineligible targeting list {a['list_id']} materially block approved Search "
                                 f"delivery?", ev)
            if it is None or (role is None and reach is None):
                no_intent.add(a["campaign_id"])
                continue
            if a["mode"] == "TARGETING" and (role == "OBSERVATION" or reach == "FULL"):
                key, msg = "mode_restricts_approved_reach", "restricts reach although approved reach is unrestricted"
            elif a["mode"] == "OBSERVATION" and (role == "TARGETING" or reach == "RESTRICTED"):
                key, msg = "mode_wider_than_approved", "observes although the approved role restricts to members"
            elif a["mode"] == "EXCLUSION" and role in ("TARGETING", "OBSERVATION"):
                key, msg = "exclusion_contradicts_intent", "excludes a list the approved role includes"
            else:
                mv.observe(f"{a['campaign_id']}/{a['list_id']}: mode matches approved intent", **entity,
                           mode=a["mode"], role=role, reach=reach)
                continue
            mv.finding(key, "Warning", entity, f"Association {a['criterion_id']} ({a['list_id']}) {msg}",
                       evidence=ev, recommendation="Align the association mode with the approved reach "
                                                   "(owner review; no blanket Observation conversion).",
                       uncertainty="Approved intent as supplied; delivery impact not measured.")
            if key != "mode_wider_than_approved":
                _critical_review(mv, key, entity, f"Does association {a['criterion_id']} materially block approved "
                                                  f"Search delivery?", ev)
        if no_intent:
            mv.partial(f"no approved intent/reach for campaigns {sorted(no_intent)}: mode not judged",
                       [f"{INTENT}:intended_audience_role"])

    # -- step 3: permission for additions/reuse
    pg = ctx.check("permission_gate", "Permitted use for audience additions or reuse",
                   {PERM: ["source_id", "list_id", "permission_status", "consent_coverage_status",
                           "permitted_destinations", "evidence_reference"], DEFS: ["list_id", "source_id"]})
    perms: dict[str, tuple] = {}
    if pg.runnable:
        src = {_s(r.get("list_id")): _s(r.get("source_id")) for r in ctx.rows(DEFS)}
        unknown_lists = []
        for lid in sorted({a["list_id"] for a in assoc if a["mode"] in ("TARGETING", "OBSERVATION")}):
            perms[lid] = _permission(ctx, lid, src.get(lid, ""))
            status, reason, refs = perms[lid]
            if status == "denied":
                pg.finding("list_permission_denied", "Info", {"list_id": lid},
                           f"List {lid} is used in Search while permission evidence is denied", evidence={
                               "reason": reason, "refs": refs},
                           recommendation="Route to skill 156; no reuse/expansion proposal.",
                           uncertainty="Permission record as supplied.")
            elif status == "unknown":
                unknown_lists.append(lid)
        if unknown_lists:
            pg.observe("Lists without permission evidence: additions/reuse proposals blocked", lists=unknown_lists)

    # -- step 4: gated outcome comparison
    so = ctx.check("segmented_outcomes", "Mature, goal-comparable, both-sided gated outcomes",
                   {PERF: ["campaign_id", "list_id", "date", "goal_set_id", "impressions", "clicks", "cost",
                           "conversions", "conversion_value", "segmentation_definition"]})
    comparisons: dict[tuple[str, str], dict] = {}
    if so.runnable:
        agg: dict[tuple, list[float]] = {}
        outside = unknown_metric = 0
        for r in ctx.rows(PERF):
            d = V.parse_date(r.get("date"))
            if d is None or ctx.period_start is None or ctx.period_end is None \
                    or not (ctx.period_start <= d <= ctx.period_end):
                outside += 1
                continue
            vals = [V.num(r.get("clicks")), ctx.money(r.get("cost")), V.num(r.get("conversions")),
                    V.num(r.get("impressions"))]
            if any(v is None for v in vals):
                unknown_metric += 1
                continue
            seg = V.norm_text(r.get("segmentation_definition"))
            side = "comparator" if ("nonmember" in seg or "non-member" in seg or "mutually exclusive" in seg
                                    or "mutually_exclusive" in seg) else "member"
            key = (_s(r.get("campaign_id")), _s(r.get("list_id")), _s(r.get("goal_set_id")), side)
            acc = agg.setdefault(key, [0.0, 0.0, 0.0, 0.0])
            for i, v in enumerate(vals):
                acc[i] += v
        if outside or unknown_metric:
            so.partial(f"{outside} rows outside/undated for the report window and {unknown_metric} rows with "
                       f"unknown metrics excluded")
        min_clicks, min_conv = ctx.params.get("min_clicks"), ctx.params.get("min_conversions")
        gates_ok = min_clicks.value is not None and min_conv.value is not None
        if not gates_ok:
            so.partial(f"sample gates unresolved: {min_clicks.reason or min_conv.reason}; no comparisons")
        if ctx.mature is not True:
            so.partial(f"descriptive only: maturity={ctx.mature} ({ctx.maturity_note})")
        for (cid, lid, goal, side), (clicks, cost, conv, impr) in sorted(agg.items()):
            if side != "member":
                continue
            so.observe(f"{cid}/{lid} members (overlapping, non-additive)", campaign_id=cid, list_id=lid,
                       goal_set_id=goal, clicks=clicks, cost=cost, conversions=conv, impressions=impr,
                       cpa=V.ratio(cost, conv), cvr=V.ratio(conv, clicks))
            comp = agg.get((cid, lid, goal, "comparator"))
            if comp is None or not gates_ok:
                continue
            c_clicks, c_cost, c_conv, _ = comp
            gates = {"cvr_gate": clicks >= min_clicks.value and c_clicks >= min_clicks.value,
                     "cpa_gate": conv >= min_conv.value and c_conv >= min_conv.value}
            row = {"campaign_id": cid, "list_id": lid, "goal_set_id": goal, "member_clicks": clicks,
                   "member_conversions": conv, "member_cost": cost, "member_cvr": V.ratio(conv, clicks),
                   "member_cpa": V.ratio(cost, conv), "comparator_clicks": c_clicks, "comparator_conversions": c_conv,
                   "comparator_cost": c_cost, "comparator_cvr": V.ratio(c_conv, c_clicks),
                   "comparator_cpa": V.ratio(c_cost, c_conv), "min_clicks": min_clicks.value,
                   "min_conversions": min_conv.value, "mature": ctx.mature, **gates,
                   "window": [str(ctx.period_start), str(ctx.period_end)]}
            so.observe(f"{cid}/{lid}: member vs comparator (same goal set {goal})", **row)
            if ctx.mature is True and gates["cpa_gate"] and gates["cvr_gate"]:
                comparisons[(cid, lid)] = row

    # -- step 5: control applicability
    ca = ctx.check("control_applicability", "Bid-control applicability before modifier proposals",
                   {"campaigns": ["id", "bidding_strategy_type"], ASSOC: ["modifier"],
                    INTENT: ["campaign_id", "supported_audience_bid_control", "control_source_url"]})
    supported: dict[str, bool | None] = {}
    if ca.runnable:
        for a in assoc:
            it = intent_for(a)
            sup = V.boolean((it or {}).get("supported_audience_bid_control"))
            supported[a["campaign_id"]] = supported.get(a["campaign_id"]) if sup is None else sup
            if not a["modifier"]:
                continue
            ent = {"campaign_id": a["campaign_id"], "ad_group_id": a["ad_group_id"] or None,
                   "criterion_id": a["criterion_id"], "list_id": a["list_id"]}
            if sup is False:
                ca.finding("modifier_without_supported_control", "Info", ent,
                           f"Audience modifier {a['modifier']:+.0%} on {a['list_id']} where the strategy "
                           f"'{camps[a['campaign_id']].get('bidding_strategy_type')}' has no supported audience "
                           f"bid control", evidence={"modifier": a["modifier"], "bidding_strategy_type":
                                                     camps[a["campaign_id"]].get("bidding_strategy_type"),
                                                     "control_source_url": (it or {}).get("control_source_url")},
                           recommendation="Treat the modifier as inert; layered modifier mechanics via skill 048.",
                           uncertainty="Control support as documented at checked_at.")
            elif sup is None:
                ca.partial(f"control support unknown for campaign {a['campaign_id']}",
                           [f"{INTENT}:supported_audience_bid_control"])

    # -- step 6: bounded test proposals
    to = ctx.check("test_opportunity", "Bounded audience test proposals",
                   {INTENT: ["campaign_id", "supported_audience_bid_control", "permitted_test_scope"]})
    if to.runnable:
        if not so.runnable or not ca.runnable or not pg.runnable:
            to.partial("comparison, control or permission evidence unavailable: no test proposals")
        for (cid, lid), row in sorted(comparisons.items()):
            status = perms.get(lid, ("unknown",))[0]
            if supported.get(cid) is not True or status != "permitted":
                to.observe(f"{cid}/{lid}: test not proposable", control_supported=supported.get(cid),
                           permission=status)
                continue
            it = intents.get((cid, ""), {})
            to.review("bounded_audience_test", {"campaign_id": cid, "list_id": lid},
                      f"Does the gated comparison for list {lid} in campaign {cid} justify a bounded audience test?",
                      evidence={**row, "permitted_test_scope": it.get("permitted_test_scope"),
                                "target": it.get("target"), "value_objective": it.get("value_profit_objective")},
                      outcomes={"test_warranted": {"severity": "Info", "recommendation":
                                                   "Propose the bounded test with scope, metric and rollback."},
                                "not_warranted": {"severity": None, "recommendation": "No test."}},
                      guidance="No fixed +20-50% default. proposal needs campaign_id, list_id, rollback_criteria.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs evidence_ref; test proposals must keep the reviewed scope and state rollback."""
    outcome, p = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_block_evidenced" and not _s(p.get("evidence_ref")):
        return ["material block needs proposal.evidence_ref pointing at supplied delivery evidence"]
    if item.condition_key == "bounded_audience_test" and outcome == "test_warranted":
        problems = []
        if _s(p.get("campaign_id")) != item.entity["campaign_id"] or _s(p.get("list_id")) != item.entity["list_id"]:
            problems.append("proposal campaign_id/list_id must equal the reviewed scope")
        if not _s(p.get("rollback_criteria")):
            problems.append("proposal.rollback_criteria required")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
