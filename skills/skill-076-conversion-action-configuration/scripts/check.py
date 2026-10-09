"""check.py — skill-076 deterministic conversion action configuration and attribution review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-076-conversion-action-configuration/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Campaign goals come from ctx.goal_ids (profile.campaign_objectives[id].goal_ids, then campaigns.goal_ids);
         a goal maps to actions by id, name or category (same rule as ctx.tracking_for_campaign).
         Declared intent is structured only: profile.campaign_objectives[id].counting (every|one) and
         .click_window_days (number). Free-text objectives never produce a deterministic conflict → review.
         Warning only when observed configuration conflicts with declared intent or when a value-based strategy
         (TARGET_ROAS / MAXIMIZE_CONVERSION_VALUE / declared target_roas) optimizes a goal action with zero/no value.
         Last Click, Every on leads without declared intent, unit/zero values on count objectives → Info or
         observation; unknown settings → partial. Critical only via review with proposal.evidence_ref.
         DDA: no volume eligibility gate (Google guidance); never use 3,000-click/300-conversion gates or call low
         volume ineligible. No action names are used to infer settings.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
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

SKILL = "skill-076-conversion-action-configuration"
VERSION = "1.0.0"

VALUE_STRATEGIES = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
_NO_VALUE = {"none", "no value", "no_value", "not set", "do not use a value", "dont use a value", "don't use a value"}
_EVERY = {"every", "many_per_click", "every_conversion", "many per click"}
_ONE = {"one", "one_per_click", "one per click", "one_conversion"}


def _counting(v) -> str | None:
    s = V.norm_text(v)
    return "every" if s in _EVERY else "one" if s in _ONE else None


def _objective(ctx, cid) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objs, dict):
        return {}
    o = next((v for k, v in objs.items() if str(k) == str(cid)), None)
    return o if isinstance(o, dict) else {}


def _value_kind(v) -> str | None:
    """zero|constant|dynamic|None(unknown) from a value_settings cell."""
    s = V.norm_text(v)
    if not s:
        return None
    n = V.num(v)
    if s in _NO_VALUE or n == 0:
        return "zero"
    if n is not None or s.startswith("unit") or "default" in s and "transaction" not in s:
        return "constant"
    if any(w in s for w in ("transaction", "dynamic", "specific")):
        return "dynamic"
    if s.split()[0].replace(".", "", 1).isdigit():
        return "constant"
    return None


def _actions_for(actions: list[dict], goal: str) -> list[dict]:
    g = goal.lower()
    return [a for a in actions if g in {str(a.get(k) or "").lower() for k in ("id", "name", "category")}]


def _strategy(c: dict) -> str:
    return str(c.get("bidding_strategy_type") or "").upper()


def _campaigns(ctx) -> list[dict]:
    return sorted((c for c in ctx.rows("campaigns") if str(c.get("status") or "").upper() != "REMOVED"),
                  key=lambda c: str(c.get("id")))


def _goal_map(ctx, chk) -> dict[str, list[dict]]:
    """campaign id -> distinct mapped goal actions; unknown membership recorded as partial."""
    actions = sorted(ctx.rows("conversion_actions"), key=lambda a: str(a.get("id")))
    out: dict[str, list[dict]] = {}
    for c in _campaigns(ctx):
        cid = str(c.get("id"))
        goals = ctx.goal_ids(cid)
        if not goals:
            chk.partial(f"campaign {cid}: goal membership unknown (profile.campaign_objectives goal_ids / campaigns.goal_ids)")
            continue
        seen: dict[str, dict] = {}
        for g in goals:
            hits = _actions_for(actions, g)
            if not hits:
                chk.partial(f"campaign {cid}: goal {g} maps to no supplied conversion action")
            for a in hits:
                seen[str(a.get("id"))] = a
        out[cid] = [seen[k] for k in sorted(seen)]
    return out


def _critical_review(chk, entity, condition, evidence) -> None:
    chk.review(condition, entity,
               "Does INDEPENDENT evidence (e.g. skill 071 event reconciliation, bidding diagnostics) link this "
               "configuration conflict to a material measurement or bidding-objective failure?",
               evidence=evidence,
               outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                        "Prioritize owner review of this action/goal; cite the evidence."},
                         "not_evidenced": {"severity": None, "recommendation": "Keep as Warning (configuration risk)."}},
               guidance="Configuration alone cannot establish overcounting or revenue error; Critical needs "
                        "proposal.evidence_ref to supplied reconciliation evidence.")


def run(ctx) -> None:
    """Inventory goal membership, then run counting, value, click-window and attribution configuration checks.

    Rules:   Warning only when counting/click_window_days conflict with profile.campaign_objectives declared intent, or
             a value-based strategy optimizes a zero/no-value goal action; each Warning also opens a Critical ai_review.
             Undeclared intent, unknown settings, missing ownership/bidding_strategies → partial; constant values and
             windows shorter than sales_cycle_days → ai_review; non-DDA → Info; conversion volume never gates DDA.
    """
    inv = ctx.check("goal_inventory", "Inventory actions, ownership and actual campaign goal membership",
                    {"conversion_actions": ["id", "status", "primary_for_goal", "include_in_conversions"],
                     "campaigns": ["id", "bidding_strategy_type"]})
    goal_map: dict[str, list[dict]] = {}
    if inv.runnable:
        acts = ctx.table("conversion_actions")
        if "conversion_customer_id" not in acts.columns:
            inv.partial("conversion ownership unknown", ["conversion_actions:conversion_customer_id"])
        if ctx.table("bidding_strategies") is None:
            inv.partial("portfolio strategy snapshot not supplied", ["bidding_strategies (file)"])
        goal_map = _goal_map(ctx, inv)
        for c in _campaigns(ctx):
            cid = str(c.get("id"))
            if cid not in goal_map:
                continue
            if c.get("custom_goal_id"):
                inv.partial(f"campaign {cid}: custom goal {c.get('custom_goal_id')}; primary labels may not resolve bidding")
            inv.observe(f"Campaign {cid} goal membership", campaign_id=cid, strategy=_strategy(c),
                        strategy_id=c.get("strategy_id") or c.get("bidding_strategy_id"),
                        goal_ids=ctx.goal_ids(cid), actions=[
                            {"id": a.get("id"), "status": a.get("status"), "category": a.get("category"),
                             "primary_for_goal": V.boolean(a.get("primary_for_goal")),
                             "include_in_conversions": V.boolean(a.get("include_in_conversions")),
                             "owner": a.get("conversion_customer_id")} for a in goal_map[cid]])
        inv.observe("Conversion actions inventoried", actions=len(ctx.rows("conversion_actions")),
                    campaigns_with_known_goals=len(goal_map))

    _counting_check(ctx, goal_map)
    _value_check(ctx, goal_map)
    _window_check(ctx, goal_map)
    _attribution_check(ctx, goal_map)


def _counting_check(ctx, goal_map) -> None:
    chk = ctx.check("counting_intent", "Counting versus declared business event intent",
                    {"conversion_actions": ["id", "counting"], "campaigns": ["id"]})
    if not chk.runnable:
        return
    for cid, actions in sorted(goal_map.items()):
        declared = _counting(_objective(ctx, cid).get("counting"))
        if declared is None:
            chk.partial(f"campaign {cid}: counting intent undeclared (profile.campaign_objectives[{cid}].counting)")
        for a in actions:
            aid = str(a.get("id"))
            observed = _counting(a.get("counting"))
            entity = {"campaign_id": cid, "action_id": aid}
            if observed is None:
                chk.partial(f"action {aid}: counting unknown ({a.get('counting')!r})")
                continue
            if declared and observed != declared:
                ev = {"observed_counting": a.get("counting"), "declared_counting": declared,
                      "declared_source": f"profile.campaign_objectives[{cid}].counting", "category": a.get("category")}
                chk.finding("counting_conflicts_intent", "Warning", entity,
                            f"Action {aid} counts '{a.get('counting')}' but campaign {cid} declares '{declared}' counting",
                            evidence=ev,
                            recommendation="Owner review of counting for this goal; no account change. Reconcile events "
                                           "in skill 071 before claiming overcounting.",
                            uncertainty="Configuration risk only; actual duplicate volume is not measured here.")
                _critical_review(chk, entity, "counting_conflicts_intent", ev)
            elif declared is None and observed == "every" and V.norm_text(a.get("category")) in ("lead", "submit_lead_form",
                                                                                               "qualified_lead"):
                chk.finding("every_lead_intent_unconfirmed", "Info", entity,
                            f"Lead action {aid} counts Every without a declared counting intent for campaign {cid}",
                            evidence={"counting": a.get("counting"), "category": a.get("category")},
                            recommendation="Confirm whether distinct leads per click are intended; Every alone is not a defect.",
                            uncertainty="Every does not prove duplicate lead submissions.")
            else:
                chk.observe(f"Action {aid} counting consistent with campaign {cid} intent", **entity,
                            counting=observed, declared=declared)


def _is_value_based(ctx, c) -> bool:
    return _strategy(c) in VALUE_STRATEGIES or _objective(ctx, c.get("id")).get("target_roas") is not None


def _value_check(ctx, goal_map) -> None:
    chk = ctx.check("value_alignment", "Value settings versus strategy/objective",
                    {"conversion_actions": ["id", "value_settings"], "campaigns": ["id", "bidding_strategy_type"]})
    if not chk.runnable:
        return
    camps = {str(c.get("id")): c for c in _campaigns(ctx)}
    for cid, actions in sorted(goal_map.items()):
        c = camps.get(cid) or {}
        value_based = _is_value_based(ctx, c)
        for a in actions:
            aid = str(a.get("id"))
            kind = _value_kind(a.get("value_settings"))
            entity = {"campaign_id": cid, "action_id": aid}
            ev = {"strategy": _strategy(c), "value_settings": a.get("value_settings"), "value_kind": kind,
                  "declared_value_policy": _objective(ctx, cid).get("value_policy")}
            if kind is None:
                chk.partial(f"action {aid}: value setting unknown/unclassified ({a.get('value_settings')!r})")
                continue
            if value_based and kind == "zero":
                chk.finding("value_strategy_without_value", "Warning", entity,
                            f"Value-based strategy {_strategy(c) or 'target_roas objective'} on campaign {cid} optimizes "
                            f"goal action {aid} whose value setting is zero/none",
                            evidence=ev, recommendation="Owner review of the value signal for this goal (dynamic/default "
                                                        "values belong to skill 107); no invented fallback value.",
                            uncertainty="Configuration conflict; realized values not reconciled here.")
                _critical_review(chk, entity, "value_strategy_without_value", ev)
            elif value_based and kind == "constant":
                chk.review("value_signal_coherence", entity,
                           f"Is the constant value '{a.get('value_settings')}' of action {aid} a coherent value signal "
                           f"for value-based campaign {cid}?",
                           evidence={**ev, "objectives": ctx.profile.get("objectives")},
                           outcomes={"incoherent_for_value_objective": {"severity": "Warning", "recommendation":
                                                                        "Review value definitions with the owner (107)."},
                                     "coherent": {"severity": None, "recommendation": "Keep."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask for the value definition."}},
                           guidance="Judge only against declared objectives/value_policy; unknown → uncertain.")
            else:
                chk.observe(f"Action {aid} value setting fits campaign {cid} strategy class", **entity, **ev,
                            value_based=value_based,
                            note="Count optimization may legitimately use zero or unit values.")


def _window_check(ctx, goal_map) -> None:
    chk = ctx.check("click_window", "Click-through window versus sales cycle and declared window",
                    {"conversion_actions": ["id", "click_window_days"]})
    if not chk.runnable:
        return
    cycle = V.num(ctx.profile.get("sales_cycle_days"))
    if cycle is None:
        chk.partial("profile.sales_cycle_days unknown: window alignment only against declared windows")
    for cid, actions in sorted(goal_map.items()):
        declared = V.num(_objective(ctx, cid).get("click_window_days"))
        for a in actions:
            aid = str(a.get("id"))
            win = V.num(a.get("click_window_days"))
            entity = {"campaign_id": cid, "action_id": aid}
            if win is None:
                chk.partial(f"action {aid}: click_window_days unknown")
                continue
            ev = {"click_window_days": win, "sales_cycle_days": cycle, "declared_window_days": declared}
            if declared is not None and win != declared:
                chk.finding("window_conflicts_intent", "Warning", entity,
                            f"Action {aid} uses a {win:g}-day click window; campaign {cid} declares {declared:g} days",
                            evidence=ev, recommendation="Align the window with the declared reporting intent after owner "
                                                        "review; note reporting comparability.",
                            uncertainty="Window changes affect future reporting comparability.")
                _critical_review(chk, entity, "window_conflicts_intent", ev)
            elif declared is None and cycle is not None and win < cycle:
                chk.review("window_shorter_than_cycle", entity,
                           f"Action {aid} window {win:g}d is shorter than the {cycle:g}d sales cycle. Does this conflict "
                           f"with the intended reporting for campaign {cid}?",
                           evidence=ev,
                           outcomes={"conflicts_intent": {"severity": "Warning", "recommendation":
                                                          "Review the window within supported settings with the owner."},
                                     "justified": {"severity": None, "recommendation": "Keep; document the rationale."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask for window rationale."}},
                           guidance="A short cycle or 90 days alone proves nothing; judge declared reporting intent.")
            else:
                chk.observe(f"Action {aid} window consistent with known cycle/intent", **entity, **ev)


def _attribution_check(ctx, goal_map) -> None:
    chk = ctx.check("attribution_model", "Attribution model and status (no volume eligibility gate)",
                    {"conversion_actions": ["id", "attribution_model"]})
    if not chk.runnable:
        return
    acts = ctx.table("conversion_actions")
    if "data_driven_model_status" not in acts.columns:
        chk.partial("attribution status unknown", ["conversion_actions:data_driven_model_status"])
    conv_by_c = {}
    for m in ctx.rows("campaign_metrics"):
        conv_by_c.setdefault(str(m.get("campaign_id")), []).append(V.num(m.get("conversions")))
    goal_actions: dict[str, list[str]] = {}
    for cid, actions in goal_map.items():
        for a in actions:
            goal_actions.setdefault(str(a.get("id")), []).append(cid)
    for a in sorted(ctx.rows("conversion_actions"), key=lambda a: str(a.get("id"))):
        aid = str(a.get("id"))
        in_goal = aid in goal_actions or (not goal_map and V.boolean(a.get("primary_for_goal")) is True)
        if not in_goal or str(a.get("status") or "").upper() in ("REMOVED", "HIDDEN"):
            continue
        model = str(a.get("attribution_model") or "").upper().replace(" ", "_")
        cids = sorted(goal_actions.get(aid, []))
        volume = {c: conv_by_c.get(c) for c in cids}
        ev = {"attribution_model": a.get("attribution_model"), "status": a.get("data_driven_model_status"),
              "source_timestamp": a.get("source_timestamp"), "campaigns": cids, "campaign_conversions_context": volume}
        if not model:
            chk.partial(f"action {aid}: attribution model unknown")
        elif model in ("DATA_DRIVEN", "DDA", "GOOGLE_ADS_DATA_DRIVEN"):
            chk.observe(f"Action {aid} uses data-driven attribution; all actions are eligible regardless of volume",
                        action_id=aid, **ev, note="Low volume is uncertainty, not ineligibility.")
        else:
            chk.finding("non_dda_contextual_review", "Info", {"action_id": aid},
                        f"Action {aid} uses {a.get('attribution_model')}; an alternative model merits contextual review",
                        evidence=ev,
                        recommendation="Discuss Last Click vs DDA with the business owner: reporting comparability, "
                                       "baseline, mature monitoring window and approval; no account change.",
                        uncertainty="Eligibility does not compel adoption or guarantee uplift.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes require proposal.evidence_ref to supplied independent evidence."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") == "Critical" and not str((decision.get("proposal") or {}).get("evidence_ref") or "").strip():
        return ["Critical needs proposal.evidence_ref citing independent reconciliation/bidding evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
