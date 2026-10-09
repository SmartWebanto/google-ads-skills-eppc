"""check.py — skill-103 deterministic converter-exclusion scope versus approved suppression policy.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-103-recent-converter-exclusion/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   A converter list is one whose audience_definitions.entry_event equals (norm_text, split list) a plan
         qualifying_event; names never classify lists.
         Effective exclusion: custom/converter_exclusions rows with association_status ENABLED/ACTIVE and
         negative true (or mode containing 'exclu'); level account → every campaign, campaign → every ad group,
         ad_group → that group. PMax signals / new-customer lifecycle rows (mode signal|lifecycle|new customer)
         and supported_exclusion_control false are NEVER hard exclusions.
         Policy vocabulary (converter_suppression_plan.allowed_reach): new_only = converters must be excluded;
         converters_allowed / converters_only = converters must not be excluded; anything else → partial.
         Empty plan campaign_id = every campaign in the inventory; repurchase_exceptions = list IDs never excluded.
         'Missing required suppression' needs a manifest-complete exclusion table AND every row
         inventory_complete true; otherwise partial, no finding.
         Deterministic Warning for literal policy contradictions; Critical only via review with
         proposal.evidence_ref (material retention block or denied-permission active use).
         New list/use proposals need activation permission 'permitted'; otherwise Info blocked.
         Returning-customer outcomes (external/returning_customer_outcomes: campaign_id, customer_class = the
         new/returning class, customer_count, qualified_outcomes, net_value, maturity) are descriptive only;
         no customer-class CPA from campaign spend.
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

SKILL = "skill-103-recent-converter-exclusion"
VERSION = "1.0.0"

EXCL = "custom/converter_exclusions"
PLAN = "external/converter_suppression_plan"
DEFS = "external/audience_definitions"
LIFE = "external/customer_lifecycle"
PERM = "external/activation_permissions"
RCO = "external/returning_customer_outcomes"
_SUPPRESS = {"new_only", "new only"}
_ALLOW = {"converters_allowed", "converters allowed", "converters_only", "converters only"}
_GRANTED = {"granted", "approved", "permitted", "verified", "yes", "true"}
_DENIED = {"denied", "revoked", "withdrawn", "rejected", "expired", "no", "false"}
_CONSENT_OK = {"covered", "complete", "verified", "not_required", "not required", "not_applicable", "not applicable"}
_ADS_DEST = {"google ads", "google_ads", "google-ads", "ads"}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _tokens(v) -> set[str]:
    return {V.norm_text(x) for x in V.split_list(v)}


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


def _critical(chk, key, entity, question, ev):
    chk.review(key, entity, question, evidence=ev,
               outcomes={"material_block_evidenced": {"severity": "Critical", "recommendation":
                                                      "Prioritize the scoped correction; cite the evidence."},
                         "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
               guidance="Critical needs proposal.evidence_ref to supplied delivery/retention evidence.")


def run(ctx) -> None:
    """Run converter-list inventory, effective exclusion scope, policy comparison and permission-gate checks.

    Rules:   Converter lists only by entry_event = plan qualifying_event; PMax signals/lifecycle rows are never
             exclusions. Literal plan contradictions (missing required suppression, excluded exception list, duration
             mismatch) → Warning; 'missing' needs manifest-complete exclusions with every row inventory_complete, else
             partial. Unknown vocabulary → partial. Critical only via ai_review with proposal.evidence_ref; proposals
             without 'permitted' → Info blocked.
    """
    defs = {_s(r.get("list_id")): r for r in ctx.rows(DEFS) if _s(r.get("list_id"))}
    plan = sorted(ctx.rows(PLAN), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                                 _s(r.get("business_segment")), _s(r.get("qualifying_event"))))

    # -- step 1: converter inventory from definitions
    ci = ctx.check("converter_inventory", "Converter audiences from actual event definitions",
                   {DEFS: ["list_id", "source_id", "entry_event", "definition_expression", "membership_duration_days"],
                    PLAN: ["qualifying_event"]})
    converters: dict[str, set[str]] = {}  # qualifying event → list ids
    if ci.runnable:
        events = sorted({e for p in plan for e in _tokens(p.get("qualifying_event"))})
        for ev in events:
            converters[ev] = {lid for lid, d in defs.items() if ev in _tokens(d.get("entry_event"))}
        undefined = sorted(lid for lid, d in defs.items() if not _s(d.get("entry_event")))
        ci.observe("Converter lists by qualifying event", lists={k: sorted(v) for k, v in sorted(converters.items())},
                   lists_without_entry_event=undefined, note="list names are not definitions")

    # -- step 2: effective exclusion scope
    es = ctx.check("effective_scope", "Effective exclusion scope across levels",
                   {"campaigns": ["id"], "ad_groups": ["id", "campaign_id"],
                    EXCL: ["campaign_id", "ad_group_id", "criterion_id", "list_id", "level", "negative",
                           "association_status", "mode", "supported_exclusion_control", "inventory_complete"]})
    campaigns = sorted({_s(r.get("id")) for r in ctx.rows("campaigns") if _s(r.get("id"))})
    groups: dict[str, list[str]] = {}
    for r in ctx.rows("ad_groups"):
        groups.setdefault(_s(r.get("campaign_id")), []).append(_s(r.get("id")))
    eff: dict[tuple[str, str], set[str]] = {}
    rows_by_scope: dict[tuple[str, str, str], list[dict]] = {}
    inventory_ok = False
    if es.runnable:
        t = ctx.table(EXCL)
        inventory_ok = t.complete is True and not t.truncated and all(
            V.boolean(r.get("inventory_complete")) is True for r in t.rows)
        if not inventory_ok:
            es.partial("exclusion inventory not certified complete: absence of an exclusion is not provable")
        signals = unsupported = unknown = 0
        for r in sorted(t.rows, key=lambda r: (_s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                               _s(r.get("list_id")), _s(r.get("criterion_id")))):
            mode = V.norm_text(r.get("mode"))
            if any(w in mode for w in ("signal", "lifecycle", "new customer", "new_customer")):
                signals += 1
                continue
            is_excl = V.boolean(r.get("negative")) is True or "exclu" in mode
            if not is_excl:
                continue
            st = _s(r.get("association_status")).upper()
            if st not in ("ENABLED", "ACTIVE"):
                unknown += st in ("", "UNKNOWN")
                continue
            if V.boolean(r.get("supported_exclusion_control")) is False:
                unsupported += 1
                continue
            level, cid, gid, lid = (V.norm_text(r.get("level")), _s(r.get("campaign_id")), _s(r.get("ad_group_id")),
                                    _s(r.get("list_id")))
            if level == "account":
                targets = [(c, g) for c in campaigns for g in (groups.get(c) or [""])]
            elif level == "campaign":
                targets = [(cid, g) for g in (groups.get(cid) or [""])]
            elif level in ("ad_group", "ad group", "adgroup"):
                targets = [(cid, gid)]
            else:
                es.partial(f"criterion {r.get('criterion_id')}: level '{r.get('level')}' unknown")
                continue
            for k in targets:
                eff.setdefault(k, set()).add(lid)
            rows_by_scope.setdefault((cid, gid, lid), []).append(r)
        if unknown:
            es.partial(f"{unknown} exclusion rows with unknown association_status not evaluated")
        es.observe("Effective exclusions", scopes_with_exclusions=len(eff), signal_or_lifecycle_rows=signals,
                   unsupported_exclusion_rows=unsupported,
                   note="PMax signals / new-customer recognition are not hard exclusions")

    # -- step 3: compare with approved policy
    pc = ctx.check("policy_compare", "Observed exclusions versus approved suppression policy",
                   {PLAN: ["business_segment", "campaign_id", "ad_group_id", "qualifying_event", "objective",
                           "allowed_reach", "repurchase_exceptions", "owner", "approved_at"]})
    missing_supp: list[tuple[dict, str, set[str]]] = []
    covered_by_plan: set[str] = set()
    if pc.runnable and not (ci.runnable and es.runnable):
        pc.skip("converter inventory or effective scope unavailable", ci.missing + es.missing)
    elif pc.runnable:
        for p in plan:
            reach = V.norm_text(p.get("allowed_reach"))
            pcid, pgid = _s(p.get("campaign_id")), _s(p.get("ad_group_id"))
            scope_camps = [pcid] if pcid else campaigns
            covered_by_plan.update(scope_camps)
            lists = set().union(*[converters.get(e, set()) for e in _tokens(p.get("qualifying_event"))])
            base = {"qualifying_event": p.get("qualifying_event"), "allowed_reach": p.get("allowed_reach"),
                    "objective": p.get("objective"), "business_segment": p.get("business_segment"),
                    "owner": p.get("owner"), "approved_at": p.get("approved_at"), "converter_lists": sorted(lists)}
            for cid in scope_camps:
                scopes = [(cid, pgid)] if pgid else [(cid, g) for g in (groups.get(cid) or [""])]
                ent = {"campaign_id": cid, "ad_group_id": pgid or None,
                       "qualifying_event": _s(p.get("qualifying_event"))}
                hit = {k: sorted(eff.get(k, set()) & lists) for k in scopes}
                exc_hit = {k: sorted(eff.get(k, set()) & set(V.split_list(p.get("repurchase_exceptions"))))
                           for k in scopes}
                if any(exc_hit.values()):
                    ev = {**base, "excluded_exception_lists": {f"{k[0]}/{k[1] or '-'}": v
                                                               for k, v in exc_hit.items() if v}}
                    pc.finding("exception_list_excluded", "Warning", ent,
                               f"Campaign {cid}: a repurchase/cross-sell exception list is excluded", evidence=ev,
                               recommendation="Remove only the exception list's exclusion in the approved scope.",
                               uncertainty="Policy as approved at approved_at.")
                    _critical(pc, "exception_list_excluded", ent, f"Does excluding the exception list in {cid} "
                                                                  f"materially block approved retention delivery?", ev)
                if reach in _SUPPRESS:
                    if not lists:
                        pc.finding("converter_list_unavailable", "Info", ent,
                                   f"Campaign {cid}: policy requires suppression of '{p.get('qualifying_event')}' "
                                   f"converters but no list is defined on that event", evidence=base,
                                   recommendation="Define the list only after permission evidence (156).",
                                   uncertainty="Qualifying-event list absent from definitions.")
                        continue
                    gaps = sorted(f"{k[0]}/{k[1] or '-'}" for k, v in hit.items() if not v)
                    if not gaps:
                        pc.observe(f"Campaign {cid}: required suppression present", campaign_id=cid)
                    elif inventory_ok:
                        missing_supp.append((ent, cid, lists))
                        pc.finding("required_suppression_missing", "Warning", ent,
                                   f"Campaign {cid}: approved new_only policy lacks an effective converter exclusion "
                                   f"in {len(gaps)} of {len(scopes)} scopes", evidence={**base, "scopes_missing": gaps},
                                   recommendation="Add the minimal exclusion in the missing scopes after the permission "
                                                  "gate; duration via 099.",
                                   uncertainty="Returning-user spend is exposure, not guaranteed savings.")
                    else:
                        pc.partial(f"campaign {cid}: suppression gap not provable (inventory incomplete)")
                elif reach in _ALLOW:
                    excluded = {f"{k[0]}/{k[1] or '-'}": v for k, v in hit.items() if v}
                    if excluded:
                        ev = {**base, "excluded_in": excluded}
                        pc.finding("exclusion_contradicts_policy", "Warning", ent,
                                   f"Campaign {cid}: converters are excluded although policy is "
                                   f"'{p.get('allowed_reach')}'", evidence=ev,
                                   recommendation="Remove the contradicting exclusion in the approved scope only.",
                                   uncertainty="Policy as approved at approved_at.")
                        _critical(pc, "exclusion_contradicts_policy", ent,
                                  f"Does the converter exclusion in {cid} materially block approved retention "
                                  f"delivery?", ev)
                    else:
                        pc.observe(f"Campaign {cid}: converters reachable as approved", campaign_id=cid)
                else:
                    pc.partial(f"allowed_reach '{p.get('allowed_reach')}' outside new_only|converters_allowed|"
                               f"converters_only")
        for cid in sorted({k[0] for k, v in eff.items() if v} - covered_by_plan):
            pc.finding("exclusion_without_policy", "Info", {"campaign_id": cid},
                       f"Campaign {cid} has audience exclusions but no approved suppression policy",
                       evidence={"excluded_lists": sorted(set().union(*[v for k, v in eff.items() if k[0] == cid]))},
                       recommendation="Record the intended policy before changing anything.",
                       uncertainty="Unknown policy; asymmetry across campaigns can be correct.")

    # -- step 4: duration and reset vs lifecycle
    dr = ctx.check("duration_reset", "Qualifying event, duration and reset behaviour",
                   {PLAN: ["qualifying_event", "intended_duration", "suppression_reset_rule", "business_segment"],
                    DEFS: ["list_id", "membership_duration_days"],
                    LIFE: ["business_segment", "repurchase_interval", "units", "maturity"]})
    if dr.runnable and not ci.runnable:
        dr.skip("converter inventory unavailable", ci.missing)
    elif dr.runnable:
        life = {_s(r.get("business_segment")): r for r in ctx.rows(LIFE)}
        seen = set()
        for p in plan:
            intended = V.num(p.get("intended_duration"))
            seg = _s(p.get("business_segment"))
            lr = life.get(seg)
            lists = set().union(*[converters.get(e, set()) for e in _tokens(p.get("qualifying_event"))])
            used = sorted(lid for lid in lists if any(lid in v for v in eff.values()))
            for lid in used:
                if (lid, seg) in seen:
                    continue
                seen.add((lid, seg))
                cur = V.num(defs[lid].get("membership_duration_days"))
                ent = {"list_id": lid, "business_segment": seg}
                ev = {"membership_duration_days": cur, "intended_duration_days": intended,
                      "reset_rule": p.get("suppression_reset_rule"),
                      "repurchase_interval": (lr or {}).get("repurchase_interval"), "units": (lr or {}).get("units"),
                      "lifecycle_maturity": (lr or {}).get("maturity")}
                if cur is None or intended is None or not _s(p.get("suppression_reset_rule")):
                    dr.finding("lifecycle_clock_unresolved", "Info", ent,
                               f"List {lid}: duration or reset rule unresolved against the approved policy",
                               evidence=ev, recommendation="Document duration/reset; optimization via 099.",
                               uncertainty="Unresolved lifecycle clock.")
                elif cur != intended:
                    dr.finding("suppression_duration_mismatch", "Warning", ent,
                               f"Excluded converter list {lid}: {cur:g}-day membership vs approved {intended:g} days",
                               evidence=ev, recommendation="Align with the approved duration (skill 099 owns tuning).",
                               uncertainty="Buying cycle before first purchase is not a suppression duration.")
                if lr is None or not (V.boolean(lr.get("maturity")) is True or V.norm_text(lr.get("maturity"))
                                      == "mature"):
                    dr.partial(f"segment '{seg}': lifecycle evidence missing or immature")

    # -- step 5: permission gate
    pg = ctx.check("permission_gate", "Permission before list/use proposals and active-use safety",
                   {PERM: ["source_id", "list_id", "permission_status", "consent_coverage_status",
                           "permitted_destinations", "evidence_reference"], DEFS: ["list_id", "source_id"]})
    if pg.runnable:
        for ent, cid, lists in missing_supp:
            res = {lid: _permission(ctx, lid, _s(defs[lid].get("source_id")))[:2] for lid in sorted(lists)}
            if not any(v[0] == "permitted" for v in res.values()):
                pg.finding("suppression_proposal_blocked", "Info", ent,
                           f"Campaign {cid}: suppression proposal blocked pending permission evidence",
                           evidence={"lists": res}, recommendation="Obtain permission/consent evidence via 156.",
                           uncertainty="Authorization-blocked proposal (exclusions are also uses).")
        for lid in sorted({lid for v in eff.values() for lid in v}):
            status, reason, refs = _permission(ctx, lid, _s((defs.get(lid) or {}).get("source_id")))
            if status == "denied":
                ent = {"list_id": lid}
                ev = {"permission_reason": reason, "refs": refs,
                      "campaigns": sorted({k[0] for k, v in eff.items() if lid in v})}
                pg.finding("excluded_list_permission_denied", "Info", ent,
                           f"List {lid} is actively used as an exclusion while permission is denied", evidence=ev,
                           recommendation="Route to skill 156 for use review.", uncertainty="Record as supplied.")
                pg.review("unsafe_active_use", ent, f"Is the active use of list {lid} with denied permission directly "
                                                    f"evidenced unsafe use?", evidence=ev,
                          outcomes={"unsafe_use_evidenced": {"severity": "Critical", "recommendation":
                                                             "Stop the use via the owner; cite evidence."},
                                    "not_unsafe": {"severity": None, "recommendation": "Keep as Info."},
                                    "uncertain": {"severity": "Info", "recommendation": "Request the permission record."}},
                          guidance="Critical needs proposal.evidence_ref.")

    # -- step 6: minimal correction summary + descriptive outcomes
    mc = ctx.check("minimal_correction", "Minimal approved-scope corrections and descriptive outcomes")
    corr = sorted({f["entity"]["campaign_id"] for f in (x.as_dict() for x in ctx.result.findings)
                   if f["severity"] == "Warning" and f["entity"].get("campaign_id")})
    if not pc.runnable:
        mc.partial("policy comparison did not run: no correction proposals derived", pc.missing)
    else:
        mc.observe("Campaigns with scoped correction proposals (095 acquisition mode, 098 stages, 099 duration)",
                   campaigns=corr)
    rco = ctx.table(RCO)
    need = ["campaign_id", "customer_class", "customer_count", "qualified_outcomes", "net_value", "maturity"]
    if rco is None or rco.missing(need):
        mc.partial("optional returning_customer_outcomes unavailable",
                   [f"{RCO} (file)"] if rco is None else [f"{RCO}:{c}" for c in rco.missing(need)])
    else:
        for r in sorted(rco.rows, key=lambda r: (_s(r.get("campaign_id")), _s(r.get("customer_class")))):
            mc.observe(f"Outcomes {r.get('campaign_id')} / {r.get('customer_class')} (descriptive)",
                       campaign_id=r.get("campaign_id"), customer_class=r.get("customer_class"),
                       customers=V.num(r.get("customer_count")), outcomes=V.num(r.get("qualified_outcomes")),
                       net_value=ctx.money(r.get("net_value")), maturity=r.get("maturity"),
                       outcomes_per_customer=V.ratio(V.num(r.get("qualified_outcomes")), V.num(r.get("customer_count"))))


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes need proposal.evidence_ref."""
    if decision.get("outcome") in ("material_block_evidenced", "unsafe_use_evidenced") and not _s(
            (decision.get("proposal") or {}).get("evidence_ref")):
        return ["Critical outcome needs proposal.evidence_ref pointing at supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
