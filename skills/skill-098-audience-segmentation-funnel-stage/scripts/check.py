"""check.py — skill-098 deterministic audience-to-funnel-stage mapping against the approved journey.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-098-audience-segmentation-funnel-stage/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Stage assignment is LITERAL only: audience_definitions.entry_event (split list, norm_text) equal to a
         funnel_plan.qualifying_events token. List names/types are never used to classify a list.
         Associations: custom/audience_associations; mode normalized to TARGETING|OBSERVATION|EXCLUSION;
         only association_status ENABLED/ACTIVE counts as active; unknown status is coverage, not a finding.
         Absence (missing segment) needs a manifest-complete association table AND every row inventory_complete
         true; otherwise partial, no gap finding. Unused lists and empty scopes are observations, never defects.
         Stage/message contradictions are business meaning → ai_review (Warning|None|uncertain Info).
         Critical only via review 'material_block_evidenced' whose verify demands proposal.evidence_ref.
         Opportunities (missing optional segment) need available_event_source (joined to
         activation_permissions.source_id), lifecycle context
         (customer_lifecycle.buying_cycle for the business_segment) AND activation permission
         (permission_status granted + consent_coverage_status covered/not_required + permitted_destinations
         naming Google Ads); anything else is an Info blocked/unassessable finding.
         Membership windows → 099, purchaser exclusions → 103: observed here, never prescribed.
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

SKILL = "skill-098-audience-segmentation-funnel-stage"
VERSION = "1.0.0"

ASSOC = "custom/audience_associations"
DEFS = "external/audience_definitions"
PLAN = "external/funnel_plan"
LIFE = "external/customer_lifecycle"
PERM = "external/activation_permissions"
_BROKEN_LINK = {"failed", "error", "broken", "unlinked", "disconnected", "removed", "closed"}
_UNAVAILABLE = {"none", "unavailable", "not available", "no"}
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
    if "observ" in s:
        return "OBSERVATION"
    if "target" in s:
        return "TARGETING"
    return None


def _active(row) -> bool | None:
    s = _s(row.get("association_status")).upper()
    if s in ("ENABLED", "ACTIVE"):
        return True
    if s in ("", "UNKNOWN"):
        return None
    return False


def _complete(ctx, key: str) -> bool:
    t = ctx.table(key)
    return bool(t) and t.complete is True and not t.truncated


def _permission(ctx, list_id: str, source_id: str) -> tuple[str, str, list]:
    """('permitted'|'denied'|'unknown', reason, evidence_refs) for Google Ads activation of one list/source."""
    t = ctx.table(PERM)
    if t is None:
        return "unknown", f"{PERM} (file) missing", []
    rows = [r for r in t.rows if (list_id and _s(r.get("list_id")) == list_id)
            or (not _s(r.get("list_id")) and source_id and _s(r.get("source_id")) == source_id)]
    if not rows:
        return "unknown", f"no permission row for list {list_id or '-'} / source {source_id or '-'}", []
    refs = sorted({_s(r.get("evidence_reference")) for r in rows if _s(r.get("evidence_reference"))})
    if any(V.norm_text(r.get("permission_status")) in _DENIED for r in rows):
        return "denied", "permission_status denied/revoked", refs
    for r in rows:
        if (V.norm_text(r.get("permission_status")) in _GRANTED
                and V.norm_text(r.get("consent_coverage_status")) in _CONSENT_OK
                and _tokens(r.get("permitted_destinations")) & _ADS_DEST):
            return "permitted", "granted, consent covered, Google Ads destination permitted", refs
    return "unknown", "permission, consent coverage or Google Ads destination not evidenced", refs


def run(ctx) -> None:
    """Run literal funnel-stage mapping, audience association coverage and segment opportunity checks.

    Rules:   Stages only from entry_event tokens equal to funnel_plan.qualifying_events; list names never classify.
             Missing-segment gaps need manifest-complete associations with inventory_complete rows; else partial.
             Stage/message contradictions → ai_review Warning; Critical only via 'material_block_evidenced' +
             evidence_ref. Opportunities need event source, lifecycle and granted activation permission; otherwise Info
             blocked finding.
    """
    inv = ctx.check("scope_inventory", "Join campaign/group scope to audience associations and definitions",
                    {"campaigns": ["id"], "ad_groups": ["id", "campaign_id"], "audiences": ["list_id"],
                     ASSOC: ["campaign_id", "ad_group_id", "list_id", "mode", "association_status",
                             "inventory_complete"]})
    step_titles = (("definition_mapping", "Map actual entry rules to journey stages"),
                   ("role_vs_intent", "Compare targeting/observation roles with approved stage intent"),
                   ("journey_gaps", "Definition contradictions, unavailable events and optional segment gaps"),
                   ("activation_permission", "Permission gate for audience creation/activation proposals"),
                   ("delegated_outputs", "Route membership-window and purchaser-exclusion questions to 099/103"))
    if not inv.runnable:
        for cid, title in step_titles:
            ctx.check(cid, title).skip("audience association scope unavailable", inv.missing)
        return

    campaigns = sorted(_s(r.get("id")) for r in ctx.rows("campaigns") if _s(r.get("id")))
    groups = {_s(r.get("id")): _s(r.get("campaign_id")) for r in ctx.rows("ad_groups") if _s(r.get("id"))}
    lists = sorted({_s(r.get("list_id")) for r in ctx.rows("audiences") if _s(r.get("list_id"))})
    assoc, unknown_status, orphan = [], 0, []
    for r in sorted(ctx.rows(ASSOC), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                                    _s(r.get("list_id")), _s(r.get("criterion_id")))):
        cid, gid = _s(r.get("campaign_id")), _s(r.get("ad_group_id"))
        if cid not in campaigns or (gid and groups.get(gid) != cid):
            orphan.append(f"{cid}/{gid or '-'}")
            continue
        act = _active(r)
        if act is None:
            unknown_status += 1
            continue
        if act:
            assoc.append({"campaign_id": cid, "ad_group_id": gid, "list_id": _s(r.get("list_id")),
                          "criterion_id": _s(r.get("criterion_id")), "mode": _mode(r.get("mode")),
                          "raw_mode": r.get("mode")})
    inventory_ok = _complete(ctx, ASSOC) and all(V.boolean(r.get("inventory_complete")) is True
                                                 for r in ctx.rows(ASSOC))
    if orphan:
        inv.partial(f"{len(orphan)} association rows reference campaigns/groups outside the parent inventory",
                    [f"{ASSOC}:campaign_id"])
    if unknown_status:
        inv.partial(f"{unknown_status} association rows with unknown association_status not evaluated")
    if not inventory_ok:
        inv.partial("association inventory not certified complete (manifest + inventory_complete): "
                    "absence of an association is not provable")
    linked = sorted({a["list_id"] for a in assoc})
    with_assoc = sorted({a["campaign_id"] for a in assoc})
    inv.observe("Audience scope inventory", campaigns=len(campaigns), ad_groups=len(groups),
                available_lists=len(lists), linked_lists=len(linked),
                unused_lists=sorted(set(lists) - set(linked)),
                campaigns_without_active_associations=sorted(set(campaigns) - set(with_assoc)),
                active_associations=len(assoc))

    # -- step 2: definitions → stages (literal entry_event ↔ qualifying_events)
    mapc = ctx.check("definition_mapping", "Map actual entry rules to journey stages",
                     {DEFS: ["list_id", "source_id", "definition_expression", "entry_event", "exclusions",
                             "linkage_status"],
                      PLAN: ["business_segment", "funnel_stage", "campaign_id", "qualifying_events"]})
    defs: dict[str, dict] = {}
    stages: dict[str, set[str]] = {}
    plan_rows = sorted(ctx.rows(PLAN), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("funnel_stage")),
                                                      _s(r.get("ad_group_id")), _s(r.get("business_segment"))))
    if mapc.runnable:
        for r in ctx.rows(DEFS):
            if _s(r.get("list_id")):
                defs[_s(r.get("list_id"))] = r
        stage_events = {}
        for p in plan_rows:
            stage_events.setdefault(_s(p.get("funnel_stage")), set()).update(_tokens(p.get("qualifying_events")))
        undefined, multi = [], []
        for lid in sorted(set(defs) | set(linked)):
            d = defs.get(lid)
            if d is None or not _s(d.get("definition_expression")) or not _s(d.get("entry_event")):
                if lid in linked:
                    undefined.append(lid)
                    uses = [a for a in assoc if a["list_id"] == lid]
                    mapc.finding("definition_unavailable", "Info", {"list_id": lid},
                                 f"Linked list {lid} has no usable definition (definition_expression/entry_event); "
                                 f"stage cannot be assigned",
                                 evidence={"linked_scopes": [f"{a['campaign_id']}/{a['ad_group_id'] or '-'}"
                                                             for a in uses],
                                           "definition_row": d is not None},
                                 recommendation="Supply the audience-manager/GA4/CRM definition; do not classify "
                                                "from the list name.",
                                 uncertainty="Unclear audience rules: stage fit unassessed, not a defect.")
                continue
            hits = sorted(s for s, ev in stage_events.items() if _tokens(d.get("entry_event")) & ev)
            stages[lid] = set(hits)
            if len(hits) > 1:
                multi.append(lid)
            if hits:
                mapc.observe(f"List {lid} mapped by literal entry event", list_id=lid, stages=hits,
                             entry_event=d.get("entry_event"), confidence="literal event match")
            elif lid in linked:
                mapc.review("stage_mapping_contradiction", {"list_id": lid},
                            f"Linked list {lid} enters on '{d.get('entry_event')}', which matches no approved "
                            f"stage's qualifying events. Does its definition contradict the approved journey?",
                            evidence={"definition_expression": d.get("definition_expression"),
                                      "entry_event": d.get("entry_event"), "exclusions": d.get("exclusions"),
                                      "plan_stage_events": {k: sorted(v) for k, v in sorted(stage_events.items())},
                                      "linked_scopes": sorted({f"{a['campaign_id']}/{a['ad_group_id'] or '-'}"
                                                               for a in assoc if a["list_id"] == lid})},
                            outcomes={"stage_contradiction": {"severity": "Warning", "recommendation":
                                                              "Correct the definition or its stage use with the owner."},
                                      "maps_consistently": {"severity": None, "recommendation":
                                                            "Record the stage assignment; no change."},
                                      "uncertain": {"severity": "Info", "recommendation":
                                                    "Ask the owner which stage this list serves."}},
                            guidance="Judge only the supplied definition against funnel_plan stage definitions; "
                                     "names are not definitions.")
        mapc.observe("Stage mapping totals", defined_lists=len(defs), mapped=sum(1 for v in stages.values() if v),
                     multi_stage_lists=multi, linked_without_definition=undefined)
    else:
        for r in ctx.rows(DEFS):
            if _s(r.get("list_id")):
                defs[_s(r.get("list_id"))] = r

    # -- step 3: observed roles vs approved stage intent
    role = ctx.check("role_vs_intent", "Compare targeting/observation roles with approved stage intent",
                     {ASSOC: ["campaign_id", "list_id", "mode"],
                      PLAN: ["funnel_stage", "campaign_id", "ad_group_id", "desired_message", "deliberate_overlap"]})
    if role.runnable and not mapc.runnable:
        role.skip("stage mapping unavailable", mapc.missing)
    elif role.runnable:
        consistent = unplanned = intentional = 0
        for a in assoc:
            if a["mode"] not in ("TARGETING", "OBSERVATION") or not stages.get(a["list_id"]):
                continue
            scoped = [p for p in plan_rows if _s(p.get("campaign_id")) in ("", a["campaign_id"])
                      and _s(p.get("ad_group_id")) in ("", a["ad_group_id"])]
            approved = {_s(p.get("funnel_stage")) for p in scoped}
            if not approved:
                unplanned += 1
                continue
            if stages[a["list_id"]] & approved:
                consistent += 1
                continue
            if any(V.boolean(p.get("deliberate_overlap")) is True for p in scoped):
                intentional += 1
                role.observe(f"Deliberate overlap preserved for list {a['list_id']} in {a['campaign_id']}",
                             list_id=a["list_id"], campaign_id=a["campaign_id"])
                continue
            entity = {"campaign_id": a["campaign_id"], "ad_group_id": a["ad_group_id"] or None,
                      "list_id": a["list_id"], "criterion_id": a["criterion_id"] or None}
            role.review("stage_targeting_contradiction", entity,
                        f"List {a['list_id']} (stages {sorted(stages[a['list_id']])}) is used in {a['mode']} mode "
                        f"where the approved journey covers {sorted(approved)}. Is this a message/targeting "
                        f"contradiction?",
                        evidence={"list_stages": sorted(stages[a["list_id"]]), "approved_stages": sorted(approved),
                                  "mode": a["mode"], "desired_messages": sorted({_s(p.get("desired_message"))
                                                                                 for p in scoped})},
                        outcomes={"contradiction": {"severity": "Warning", "recommendation":
                                                    "Align the list's stage use or message with the approved plan."},
                                  "intentional": {"severity": None, "recommendation":
                                                  "Keep; document as intentional pooled/returning-user use."},
                                  "uncertain": {"severity": "Info", "recommendation":
                                                "Confirm the intended stage with the plan owner."}},
                        guidance="Pooled all-visitor learning, cross-sell, renewal and repeat purchase uses are "
                                 "legitimate; contradiction needs the plan's own stage/message definitions.")
        if unplanned:
            role.partial(f"{unplanned} active associations in scopes without an approved funnel_plan row")
        role.observe("Role comparison totals", consistent=consistent, intentional_overlap=intentional,
                     unplanned_scopes=unplanned)

    # -- step 4: definition errors, unavailable events, optional gaps
    gaps = ctx.check("journey_gaps", "Definition contradictions, unavailable events and optional segment gaps",
                     {PLAN: ["business_segment", "funnel_stage", "campaign_id", "qualifying_events",
                             "available_event_source"],
                      DEFS: ["list_id", "entry_event", "linkage_status"]})
    candidates = []
    if gaps.runnable and not mapc.runnable:
        gaps.skip("stage mapping unavailable", mapc.missing)
    elif gaps.runnable:
        for lid in linked:
            d = defs.get(lid)
            if d is None or V.norm_text(d.get("linkage_status")) not in _BROKEN_LINK:
                continue
            scopes = sorted({a["campaign_id"] for a in assoc if a["list_id"] == lid})
            ev = {"linkage_status": d.get("linkage_status"), "last_successful_refresh_at":
                  d.get("last_successful_refresh_at"), "evidence_reference": d.get("evidence_reference"),
                  "active_campaigns": scopes}
            prov = gaps.finding("definition_linkage_error", "Info", {"list_id": lid},
                                f"Linked list {lid} reports linkage_status '{d.get('linkage_status')}' while "
                                f"actively associated in {len(scopes)} campaign(s)",
                                evidence=ev, recommendation="Have the audience owner verify the source link.",
                                uncertainty="Delivery impact not measured by this evidence.")
            gaps.review("definition_linkage_error", {"list_id": lid},
                        f"Does the broken linkage of list {lid} materially block approved intended audience delivery?",
                        evidence=ev, provisional=prov,
                        outcomes={"material_block_evidenced": {"severity": "Critical", "recommendation":
                                                               "Prioritize the source fix; cite the delivery evidence."},
                                  "not_material": {"severity": "Info", "recommendation": "Fix in normal hygiene."},
                                  "uncertain": {"severity": "Info", "recommendation": "Request delivery diagnostics."}},
                        guidance="Critical needs proposal.evidence_ref to supplied delivery evidence.")
        lifecycle_ok: set[str] = set()
        life = ctx.table(LIFE)
        life_usable = life is not None and not life.missing(["business_segment", "buying_cycle"])
        if not life_usable:
            gaps.partial("lifecycle context unavailable: optional segments not proposed",
                         [f"{LIFE}:{c}" for c in life.missing(["business_segment", "buying_cycle"])]
                         if life is not None else [f"{LIFE} (file)"])
        else:
            lifecycle_ok = {_s(r.get("business_segment")) for r in life.rows if _s(r.get("buying_cycle"))}
        if not inventory_ok:
            gaps.partial("association inventory incomplete: missing-segment gaps not assessed")
        else:
            for p in plan_rows:
                stage, cid, seg = _s(p.get("funnel_stage")), _s(p.get("campaign_id")), _s(p.get("business_segment"))
                covered = any(stage in stages.get(a["list_id"], set()) and a["mode"] in ("TARGETING", "OBSERVATION")
                              and cid in ("", a["campaign_id"]) for a in assoc)
                if covered:
                    continue
                entity = {"business_segment": seg, "funnel_stage": stage, "campaign_id": cid or None}
                source = _s(p.get("available_event_source"))
                ev = {"qualifying_events": sorted(_tokens(p.get("qualifying_events"))), "available_event_source":
                      source or None, "business_priority": p.get("business_priority"), "owner": p.get("owner")}
                if not source or V.norm_text(source) in _UNAVAILABLE:
                    gaps.finding("stage_event_unavailable", "Info", entity,
                                 f"Approved stage '{stage}' has no linked audience and no available event source",
                                 evidence=ev, recommendation="Confirm whether a permitted signal can exist; no "
                                                             "segment is proposed.",
                                 uncertainty="Unavailable events: optional segment not assessable.")
                elif not life_usable:
                    continue
                elif seg not in lifecycle_ok:
                    gaps.finding("stage_lifecycle_unknown", "Info", entity,
                                 f"Approved stage '{stage}' lacks a linked audience; lifecycle context for segment "
                                 f"'{seg}' is missing, so no segment is proposed", evidence=ev,
                                 recommendation="Supply buying-cycle evidence before proposing a segment.",
                                 uncertainty="Lifecycle context missing.")
                else:
                    candidates.append((entity, ev, source))
        gaps.observe("Journey gap totals", plan_rows=len(plan_rows), opportunity_candidates=len(candidates))

    # -- step 5: permission gate for proposals
    perm = ctx.check("activation_permission", "Permission gate for audience creation/activation proposals",
                     {PERM: ["source_id", "list_id", "permission_status", "consent_coverage_status",
                             "permitted_destinations", "evidence_reference"]})
    if not gaps.runnable and perm.runnable:
        perm.skip("no journey gap evaluation to gate", gaps.missing)
    if not perm.runnable:
        if candidates:
            perm.observe("Opportunity candidates blocked: permission evidence unavailable",
                         candidates=[e for e, _, _ in candidates])
        candidates = []
    for entity, ev, source in candidates:
        status, reason, refs = _permission(ctx, "", source)
        ev2 = {**ev, "permission_status": status, "permission_reason": reason, "permission_refs": refs}
        if status == "permitted":
            perm.finding("optional_segment_opportunity", "Info", entity,
                         f"Optional segment for stage '{entity['funnel_stage']}' is supportable from permitted "
                         f"source '{source}'", evidence=ev2,
                         recommendation="Request-only: owner may define the segment; readiness via 156, GA4 "
                                        "provenance via 105; membership window via 099.",
                         uncertainty="No uplift assumed; opportunity, not a defect.")
        else:
            perm.finding("segment_proposal_blocked", "Info", entity,
                         f"Optional segment for stage '{entity['funnel_stage']}' blocked: {reason}", evidence=ev2,
                         recommendation="Obtain authorized permitted-use and consent evidence (skill 156) first.",
                         uncertainty="Permission evidence missing or denied; no activation proposal.")
    if perm.runnable:
        perm.observe("Permission-gated proposals", evaluated=len(candidates))

    # -- step 6: delegation
    dele = ctx.check("delegated_outputs", "Route membership-window and purchaser-exclusion questions to 099/103",
                     {ASSOC: ["list_id", "mode"]})
    if dele.runnable:
        excl = sorted({f"{a['campaign_id']}:{a['list_id']}" for a in assoc if a["mode"] == "EXCLUSION"})
        windows = sorted(lid for lid in linked if defs.get(lid) and _s(defs[lid].get("membership_duration_days")))
        dele.observe("Delegated to skill-103 (exclusions) and skill-099 (membership windows)",
                     exclusion_associations=excl, lists_with_membership_windows=windows)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcome 'material_block_evidenced' requires proposal.evidence_ref."""
    if decision.get("outcome") == "material_block_evidenced" and not _s((decision.get("proposal") or {})
                                                                        .get("evidence_ref")):
        return ["material block needs proposal.evidence_ref pointing at supplied delivery evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
