"""check.py — skill-009 deterministic account defaults, goal selection, links and auto-apply governance.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-009-account-defaults-audit/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #108 Add tracking parameters to URL (Ritwik GA) — clean-room reimplementation of the required
         tracking-parameter comparison (tracking_template / final_url_suffix / url_parameters rows); the
         script's URL rewriting becomes an owner proposal, never an account change
rules:   external/account_controls.control_type tokens: auto_tagging | auto_apply | link | tracking_template |
         final_url_suffix | url_parameters. States normalise to on/off only from explicit tokens; anything
         else is unknown → partial, never 'disabled'.
         A dependency is 'required' ONLY when the controls row names it in `dependency`; without it an absent
         integration is optional (Info) and disabled auto-tagging goes to AI review.
         Approved goals come ONLY from profile.campaign_objectives[cid].goal_ids (never inferred from bidding or
         primary flags); selected goals are matched on goal_id | custom_goal_id | conversion_action_id.
         Observed ≠ expected auto-apply state is a deterministic Warning (policy mismatch → owner review).
         Critical is reachable ONLY through the 'material_failure_evidenced' review, and verify() requires
         proposal.evidence_ref equal to the supplied row evidence_ref (or naming the disabled action ids).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
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

SKILL = "skill-009-account-defaults-audit"
VERSION = "1.0.0"

CONTROLS = "external/account_controls"
GOALS = "custom/campaign_goal_selection"
ON = {"on", "enabled", "true", "yes", "y", "1", "opted_in", "opt_in", "active", "linked", "applied"}
OFF = {"off", "disabled", "false", "no", "n", "0", "opted_out", "opt_out", "inactive", "unlinked", "not_linked",
       "removed", "absent", "none", "not_applied"}
TRACKING_TYPES = ("tracking_template", "final_url_suffix", "url_parameters")
NO_FAILURE = {"", "none", "no", "false", "0", "n/a", "not_observed"}


def _state(v) -> str | None:
    s = V.norm_text(v).replace(" ", "_").replace("-", "_")
    return "on" if s in ON else "off" if s in OFF else None


def _ctype(r) -> str:
    return V.norm_text(r.get("control_type")).replace(" ", "_").replace("-", "_")


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion basis",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature,
              conversion_date_basis=ctx.account.get("conversion_date_basis"),
              conversion_tracking=ctx.account.get("conversion_tracking"))


def _approved_goals(ctx, cid: str) -> list[str]:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    return [str(g) for g in (obj or {}).get("goal_ids") or []] if isinstance(obj, dict) else []


def _controls(ctx, *types) -> list[dict]:
    return sorted((r for r in ctx.rows(CONTROLS) if _ctype(r) in types),
                  key=lambda r: (_ctype(r), str(r.get("control_name")), str(r.get("linked_account_id"))))


def _entity(r) -> dict:
    return {"account_id": r.get("account_id"), "control_type": _ctype(r), "control_name": r.get("control_name"),
            **({"linked_account_id": r.get("linked_account_id")} if r.get("linked_account_id") else {})}


def _ev(r) -> dict:
    return {k: r.get(k) for k in ("observed_value", "expected_value", "authorization_ref", "dependency",
                                  "observed_failure", "evidence_ref", "source", "snapshot_date") if k in r}


def _param_keys(v) -> set[str]:
    s = str(v or "")
    keys = re.findall(r"([A-Za-z0-9_]+)=", s)
    if keys:
        return {k.lower() for k in keys}
    return {t.lower() for t in re.split(r"[;,|&\s]+", s) if t and not t.startswith("{")}


def run(ctx) -> None:
    """Run auto-tagging, goal-selection, counting/value, auto-apply, link, tracking-parameter and failure checks.

    Rules:   Deterministic Warning only for: auto-tagging off vs declared dependency expecting on, no selected action
             in approved goal_ids, auto-apply observed ≠ expected, and required (dependency-named) link/parameter
             gaps; unknown states → partial. Extra goals, counting/value flags and auto-tagging without dependency
             go to ai_review; Critical only via ai_review 'material_failure_evidenced' (row evidence_ref).
    """
    _scope(ctx)

    # step 2 — auto-tagging vs measurement dependency
    at = ctx.check("auto_tagging", "Auto-tagging status vs declared measurement dependency", {"account": ["auto_tagging"]})
    if at.runnable:
        state = _state(ctx.account.get("auto_tagging"))
        rows = _controls(ctx, "auto_tagging")
        ui = [_state(r.get("observed_value")) for r in rows]
        if any(u is not None and state is not None and u != state for u in ui):
            at.partial("account export and UI evidence disagree on auto-tagging; export value used")
        dep = [r for r in rows if r.get("dependency")]
        at.observe("Auto-tagging status", export_value=ctx.account.get("auto_tagging"), state=state,
                   ui_rows=len(rows), declared_dependencies=[r.get("dependency") for r in dep])
        if state is None:
            at.partial("auto-tagging state unknown")
        elif state == "off":
            entity = {"account_id": ctx.account_id, "control": "auto_tagging"}
            ev = {"auto_tagging": ctx.account.get("auto_tagging"), "controls": [_ev(r) for r in rows],
                  "objectives": ctx.profile.get("objectives")}
            if any(_state(r.get("expected_value")) == "on" for r in dep):
                at.finding("auto_tagging_conflicts_dependency", "Warning", entity,
                           "Auto-tagging is off while a declared measurement dependency expects it on",
                           evidence=ev, recommendation="Owner review of the tracking implementation before enabling.",
                           uncertainty="Configuration evidence; runtime click-ID loss not measured here.")
            else:
                at.review("auto_tagging_off", entity,
                          "Auto-tagging is off. Does the chosen measurement implementation depend on it?", evidence=ev,
                          outcomes={"dependent": {"severity": "Warning", "recommendation": "Owner review; plan enablement."},
                                    "not_dependent": {"severity": None, "recommendation": "No action; document the setup."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask the measurement owner."}},
                          guidance="Only supplied integration evidence counts; unknown dependency → uncertain.")

    # step 3 — effective campaign goal selection
    gs = ctx.check("goal_selection", "Effective campaign goal/action selection vs approved goals",
                   {GOALS: ["campaign_id", "goal_id", "custom_goal_id", "conversion_action_id", "selected_for_bidding",
                            "selection_source", "snapshot_date"],
                    "campaigns": ["id", "status"], "conversion_actions": ["id", "primary_for_goal"]})
    if gs.runnable:
        primary = {str(a.get("id")): V.boolean(a.get("primary_for_goal")) for a in ctx.rows("conversion_actions")}
        by_c: dict[str, list[dict]] = {}
        for r in ctx.rows(GOALS):
            by_c.setdefault(str(r.get("campaign_id")), []).append(r)
        for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
            cid = str(c.get("id"))
            if str(c.get("status") or "").upper() not in ("ENABLED", ""):
                continue
            rows = by_c.get(cid, [])
            approved = _approved_goals(ctx, cid)
            if not rows:
                gs.partial(f"campaign {cid}: no goal-selection rows; bidding selection unknown")
                continue
            if not approved:
                gs.partial(f"campaign {cid}: no approved goal_ids in profile.campaign_objectives; no comparison")
                continue
            sel = [r for r in rows if V.boolean(r.get("selected_for_bidding")) is True]
            ids = lambda r: {str(r.get(k)).lower() for k in ("goal_id", "custom_goal_id", "conversion_action_id") if r.get(k)}
            want = {g.lower() for g in approved}
            entity = {"campaign_id": cid}
            ev = {"approved_goal_ids": approved, "selected": [{k: r.get(k) for k in
                  ("goal_id", "custom_goal_id", "conversion_action_id", "selection_source")} for r in sel],
                  "snapshot_date": rows[0].get("snapshot_date")}
            gs.observe(f"Campaign {cid}: goal selection", campaign_id=cid, rows=len(rows), selected=len(sel),
                       approved=approved)
            if not any(ids(r) & want for r in sel):
                gs.finding("selection_misses_approved_goal", "Warning", entity,
                           f"Campaign {cid} bids on no action mapped to its approved goals {approved}", evidence=ev,
                           recommendation="Owner review of campaign goal settings against the approved objective.",
                           uncertainty="Goals UI snapshot only; historical selection not reconstructed.")
            for r in sel:
                if ids(r) & want:
                    continue
                act = str(r.get("conversion_action_id") or "")
                e2 = {**entity, "conversion_action_id": act, "goal_id": r.get("goal_id")}
                if "custom" in V.norm_text(r.get("selection_source")):
                    gs.finding("intentional_custom_goal_selection", "Info", e2,
                               f"Campaign {cid} bids on action {act} through a custom goal "
                               f"(primary_for_goal={primary.get(act)})", evidence={**ev, "row": dict(r)},
                               recommendation="Confirm the custom goal is intended; this is not a contradiction.",
                               uncertainty="Custom-goal inclusion is a deliberate configuration choice.")
                else:
                    gs.review("extra_goal_selected", e2,
                              f"Campaign {cid} bids on action {act}, which is outside its approved goals. Intended?",
                              evidence={**ev, "selection_source": r.get("selection_source")},
                              outcomes={"conflicts_approved_goals": {"severity": "Warning", "recommendation":
                                                                     "Owner review of goal selection."},
                                        "intended": {"severity": None, "recommendation": "Document the approval."},
                                        "uncertain": {"severity": "Info", "recommendation": "Ask the goal owner."}},
                              guidance="Account-default inheritance can be approved; decide only from profile objectives.")

    # step 4 — counting / value / attribution fit
    cva = ctx.check("counting_value_attribution", "Counting, value and attribution vs measured business event",
                    {"conversion_actions": ["id", "category", "status", "counting", "value_settings", "attribution_model"]})
    if cva.runnable:
        for a in sorted(ctx.rows("conversion_actions"), key=lambda r: str(r.get("id"))):
            if str(a.get("status") or "").upper() != "ENABLED" or V.boolean(a.get("primary_for_goal")) is False:
                continue
            cat, cnt = str(a.get("category") or "").upper(), str(a.get("counting") or "").upper()
            one, many = "ONE" in cnt, ("MANY" in cnt or "EVERY" in cnt)
            flags = []
            if "PURCHASE" in cat and one:
                flags.append("purchase counted once per click")
            if any(t in cat for t in ("LEAD", "CONTACT", "SIGNUP", "SIGN_UP")) and many:
                flags.append("lead counted every conversion")
            if "PURCHASE" in cat and V.num(a.get("value_settings")) in (0.0, 1.0):
                flags.append(f"purchase value setting '{a.get('value_settings')}'")
            ev = {k: a.get(k) for k in ("name", "category", "counting", "value_settings", "attribution_model",
                                         "click_window_days", "include_in_conversions", "primary_for_goal")}
            cva.observe(f"Action {a.get('id')} configuration", action_id=a.get("id"), flags=flags, **ev)
            if flags:
                cva.review("measurement_config_fit", {"conversion_action_id": a.get("id")},
                           f"Do counting/value settings of action {a.get('id')} ({a.get('name')}) contradict the business "
                           f"event it measures? Flags: {flags}", evidence={**ev, "business_type": ctx.profile.get("business_type"),
                                                                           "customer_lifecycle": ctx.profile.get("customer_lifecycle")},
                           outcomes={"conflicts_business_event": {"severity": "Warning", "recommendation":
                                                                  "Route detailed fix to tracking specialists (070/076)."},
                                     "fits_business_event": {"severity": None, "recommendation": "No action."},
                                     "uncertain": {"severity": "Info", "recommendation": "Confirm the event definition."}},
                           guidance="Neither last-click nor one-per-click is automatically a defect; judge against the "
                                    "profile business type and lifecycle.")

    ctl_base = ["account_id", "control_type", "control_name", "observed_value", "source", "snapshot_date"]

    # step 5 — auto-apply inventory
    inv = ctx.check("auto_apply_inventory", "Exact auto-apply option labels and observed states", {CONTROLS: ctl_base})
    if inv.runnable:
        rows = _controls(ctx, "auto_apply")
        if not rows:
            inv.partial("no auto_apply rows supplied: auto-apply status unknown (not disabled)")
        for r in rows:
            snap = V.parse_date(r.get("snapshot_date"))
            if snap is None or (ctx.period_end and snap < ctx.period_end):
                inv.partial(f"auto-apply '{r.get('control_name')}': snapshot {r.get('snapshot_date')} not current")
            if _state(r.get("observed_value")) is None:
                inv.partial(f"auto-apply '{r.get('control_name')}': observed state '{r.get('observed_value')}' unknown")
            inv.observe(f"Auto-apply option '{r.get('control_name')}'", state=_state(r.get("observed_value")), **_ev(r))

    # step 6 — auto-apply vs authorised policy
    auth = ctx.check("auto_apply_authority", "Auto-apply states vs authorised operating policy",
                     {CONTROLS: ctl_base + ["expected_value", "authorization_ref"]})
    if auth.runnable:
        for r in _controls(ctx, "auto_apply"):
            obs, exp = _state(r.get("observed_value")), _state(r.get("expected_value"))
            if obs is None or exp is None:
                auth.partial(f"'{r.get('control_name')}': observed/expected state not explicit; no comparison")
                continue
            if obs != exp:
                auth.finding("auto_apply_policy_mismatch", "Warning", _entity(r),
                             f"Auto-apply '{r.get('control_name')}' is {obs} but approved policy expects {exp}",
                             evidence=_ev(r), recommendation="Owner review of the option; no immediate change.",
                             uncertainty="Current UI capture only; past auto-applied changes not reconstructed.")
            elif obs == "on" and not r.get("authorization_ref"):
                auth.partial(f"'{r.get('control_name')}': enabled as expected but no authorization_ref")

    # step 7 — account links
    links = ctx.check("account_links", "Linked accounts for required integrations and approved targets",
                      {CONTROLS: ctl_base + ["linked_account_id", "expected_value", "dependency"]})
    if links.runnable:
        for r in _controls(ctx, "link"):
            obs = _state(r.get("observed_value"))
            required = bool(r.get("dependency"))
            exp_id = str(r.get("expected_value") or "").strip()
            if obs is None:
                links.partial(f"link '{r.get('control_name')}': status '{r.get('observed_value')}' unknown")
                continue
            if obs == "off":
                links.finding("required_link_missing" if required else "optional_integration_absent",
                              "Warning" if required else "Info", _entity(r),
                              f"{r.get('control_name')} link not active" + (f" although required by {r.get('dependency')}"
                                                                            if required else " (optional integration)"),
                              evidence=_ev(r), recommendation="Owner review of the integration." if required else
                              "Optional; link only if the business needs it.",
                              uncertainty="Link presence does not certify data quality.")
            elif exp_id and _state(exp_id) is None and r.get("linked_account_id") and \
                    str(r.get("linked_account_id")).strip() != exp_id:
                links.finding("link_target_mismatch", "Warning" if required else "Info", _entity(r),
                              f"{r.get('control_name')} linked to {r.get('linked_account_id')}, approved target {exp_id}",
                              evidence=_ev(r), recommendation="Owner review of the linked account.",
                              uncertainty="Sanitized identifiers compared literally.")

    # index #108 — tracking parameters
    tp = ctx.check("tracking_parameters", "Required tracking parameters in templates/suffixes",
                   {CONTROLS: ctl_base + ["expected_value", "dependency"]})
    if tp.runnable:
        for r in _controls(ctx, *TRACKING_TYPES):
            need, have = _param_keys(r.get("expected_value")), _param_keys(r.get("observed_value"))
            if not need:
                tp.partial(f"{_ctype(r)} '{r.get('control_name')}': no expected parameters declared")
                continue
            missing = sorted(need - have)
            tp.observe(f"{_ctype(r)} '{r.get('control_name')}' parameters", required=sorted(need), observed=sorted(have),
                       missing=missing)
            if missing:
                req = bool(r.get("dependency"))
                tp.finding("tracking_parameters_missing", "Warning" if req else "Info", _entity(r),
                           f"{_ctype(r)} lacks required parameters {missing}", evidence=_ev(r),
                           calculation={"required": sorted(need), "observed": sorted(have)},
                           recommendation="Propose the template/suffix change to the owner; no automatic URL edits.",
                           uncertainty="Literal parameter keys only; value substitution and redirects not tested.")

    # step 8 — directly evidenced measurement failure
    mf = ctx.check("measurement_failure", "Directly evidenced failure of required measurement",
                   {"conversion_actions": ["id", "status"], "campaigns": ["id"]})
    if mf.runnable:
        if ctx.table(CONTROLS) is None:
            mf.partial("external/account_controls missing: observed failures unknown", [f"{CONTROLS} (file)"])
        for r in ctx.rows(CONTROLS):
            fail = str(r.get("observed_failure") or "").strip()
            if V.norm_text(fail) in NO_FAILURE:
                continue
            required = bool(r.get("dependency"))
            prov = mf.finding("measurement_failure_observed", "Warning" if required else "Info", _entity(r),
                              f"Observed failure on {r.get('control_name')}: {fail}", evidence=_ev(r),
                              recommendation="Tracking specialists diagnose; owner prioritises.",
                              uncertainty="Materiality not established by the script.")
            outcomes = {"not_material": {"severity": "Warning" if required else "Info", "recommendation": "Keep as is."}}
            if r.get("evidence_ref"):
                outcomes["material_failure_evidenced"] = {"severity": "Critical", "recommendation":
                                                          "Prioritise the fix; cite proposal.evidence_ref."}
            mf.review("measurement_failure", _entity(r),
                      "Is there direct evidence that this default/configuration failure materially breaks required "
                      "measurement?", evidence=_ev(r), outcomes=outcomes, provisional=prov,
                      guidance="Critical needs proposal.evidence_ref equal to the row evidence_ref.")
        for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
            cid = str(c.get("id"))
            if not _approved_goals(ctx, cid) or str(c.get("status") or "").upper() not in ("ENABLED", ""):
                continue
            state, note = ctx.tracking_for_campaign(cid)
            if state is False:
                entity = {"campaign_id": cid, "control": "approved_goal_actions"}
                ev = {"tracking_note": note, "approved_goals": _approved_goals(ctx, cid)}
                prov = mf.finding("approved_goal_actions_disabled", "Warning", entity,
                                  f"Every conversion action for campaign {cid}'s approved goals is disabled/removed",
                                  evidence=ev, recommendation="Owner review with tracking specialists.",
                                  uncertainty="Status snapshot; replacement actions outside the export are unknown.")
                mf.review("measurement_failure", entity,
                          "Does this disabled measurement materially break the campaign's required optimisation?",
                          evidence=ev, provisional=prov,
                          outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                                   "Prioritise the fix; cite proposal.evidence_ref."},
                                    "not_material": {"severity": "Warning", "recommendation": "Keep as Warning."}},
                          guidance="Critical needs proposal.evidence_ref naming the supplied evidence.")
            elif state is None:
                mf.partial(note)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref; when the row carries evidence_ref it must match."""
    if decision.get("outcome") != "material_failure_evidenced":
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return ["material failure needs proposal.evidence_ref pointing at supplied evidence"]
    row_ref = str(item.evidence.get("evidence_ref") or "").strip()
    if row_ref and ref != row_ref:
        return [f"proposal.evidence_ref '{ref}' does not match supplied evidence_ref '{row_ref}'"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
