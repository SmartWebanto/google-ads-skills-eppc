"""check.py — skill-131 deterministic change-history coverage, ledger and authorization matching.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-131-change-history-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #57 Change History Alerts (nilsrooijmans.com) — clean-room reimplementation of "changes by actors
         outside a recognized list" as the unrecognized_actors check; e-mail/Sheet alerting is not reproduced.
rules:   Event counts use DISTINCT change_id; field rows are counted separately (step 1).
         A log whose manifest is missing/incomplete/truncated or does not cover the report period is Info
         partial_change_log — never evidence that no other changes happened.
         Joins use campaign_id/budget_id/strategy_id only, never names. A shared-budget change is ONE delta listed
         with all member campaigns (campaigns.budget_id), never multiplied per member.
         Deltas only when old and new are both numeric on the same field; '*_micros' fields are divided by 1e6.
         No approval_ref or an unknown approval_ref = unknown authorization (Info), never "unauthorized".
         Deterministic Warning only for explicit contradictions with a matched authorization row (actor not in
         permitted_actor_ids, client_type not in permitted_source, occurred outside valid_from/valid_to, value
         outside a parseable numeric constraint, compared on the raw exported value) or a register row whose review is overdue (review_status says
         overdue, or pending/required with valid_to before as_of). Free-text constraints and scope/field coverage
         questions go to ai_review. Critical only via review with proposal.evidence_ref.
         Off-hours timing and change volume are never defects.
         #57 recognized actors are profile-supplied: profile.change_recognized_actors (list of actor_id) and optional
         profile.change_recognized_client_types; absent list → the check is skipped, not passed.
         Outcome windows (optional custom/change_outcomes) are descriptive, 7 complete mature days each side,
         sample-gated on both sides and labelled non-causal.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-131-change-history-monitoring"
VERSION = "1.0.0"

CH = "custom/change_history_fields"
AUTH = "external/change_authorizations"
OUT = "custom/change_outcomes"
_SEPS = (" | ", ";", "|", ",")
_WILDCARD = ("*", "any", "all", "account")
_CMP = re.compile(r"^(<=|>=|<|>|==|=)\s*([-+]?\d+(?:\.\d+)?)$")
_RNG = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*(?:\.\.|to)\s*([-+]?\d+(?:\.\d+)?)$", re.I)


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _rows(ctx) -> list[dict]:
    return sorted(ctx.rows(CH), key=lambda r: (_s(r.get("occurred_at")), _s(r.get("change_id")),
                                               _s(r.get("field_path"))))


def _op(v) -> str:
    s = _s(v).upper()
    if s in ("CREATE", "ADD", "ADDED", "CREATED"):
        return "add"
    if s in ("REMOVE", "REMOVED", "DELETE"):
        return "remove"
    if s in ("UPDATE", "UPDATED", "CHANGE"):
        return "update"
    return "unknown"


def _value(field: str, v):
    f = V.num(v)
    if f is None:
        return None
    return f / 1_000_000 if field.endswith("_micros") else f


def _budget_members(ctx) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for c in ctx.rows("campaigns"):
        b = _s(c.get("budget_id"))
        if b:
            out.setdefault(b, set()).add(_s(c.get("id")))
    for b in ctx.rows("budgets"):
        for cid in V.split_list(b.get("campaign_ids"), _SEPS):
            out.setdefault(_s(b.get("id")), set()).add(cid)
    return {k: sorted(v) for k, v in out.items()}


def run(ctx) -> None:
    """Run change-log coverage, delta, authorization, recognized-actor and outcome-window checks.

    Rules:   Incomplete/truncated log → Info partial_change_log, never proof of no changes. Shared-budget deltas counted
             once. Missing/unknown approval_ref → Info unknown authorization, never 'unauthorized'. Deterministic
             Warning only for explicit contradictions with a matched authorization row or overdue review; free-text
             constraints → ai_review; Critical only via review with proposal.evidence_ref. Off-hours/volume never
             defects; actor list absent → skipped.
    """
    _log_coverage(ctx)
    _resource_mapping(ctx)
    _value_deltas(ctx)
    resolved = _authorization(ctx)
    _unrecognized_actors(ctx, resolved)
    _outcomes(ctx)


def _log_coverage(ctx) -> None:
    """Step 1: retention/completeness; distinct change IDs vs field rows."""
    chk = ctx.check("log_coverage", "Change-log retention, completeness and event counts",
                    {CH: ["change_id", "field_path", "occurred_at"]})
    if not chk.runnable:
        return
    t = ctx.table(CH)
    rows = _rows(ctx)
    ids = {_s(r.get("change_id")) for r in rows if _s(r.get("change_id"))}
    keys = [(_s(r.get("change_id")), _s(r.get("field_path"))) for r in rows]
    dupes = len(keys) - len(set(keys))
    dates = sorted({V.parse_date(r.get("occurred_at")) for r in rows} - {None})
    m = t.manifest or {}
    log_start, log_end = V.parse_date(m.get("period_start")), V.parse_date(m.get("period_end"))
    chk.observe("Change-log event and field-row counts", distinct_change_ids=len(ids), field_rows=len(rows),
                duplicate_field_rows=dupes, first_change=dates[0] if dates else None,
                last_change=dates[-1] if dates else None, manifest_window=[log_start, log_end],
                report_period=[ctx.period_start, ctx.period_end])
    if dupes:
        chk.partial(f"{dupes} duplicate change_id/field_path rows; counted once")
    gaps = []
    if t.complete is not True:
        gaps.append("manifest does not certify completeness")
    if t.truncated:
        gaps.append(f"manifest truncation: {m.get('truncation')}")
    if ctx.period_start and ctx.period_end and not (log_start and log_end and log_start <= ctx.period_start
                                                    and log_end >= ctx.period_end):
        gaps.append(f"log window {log_start}..{log_end} does not cover report period {ctx.period_start}..{ctx.period_end}")
    if gaps:
        chk.finding("partial_change_log", "Info", {"file": t.filename},
                    f"Change log cannot establish complete activity: {'; '.join(gaps)}",
                    evidence={"gaps": gaps, "distinct_change_ids": len(ids), "field_rows": len(rows),
                              "manifest": {k: m.get(k) for k in ("completeness", "truncation", "period_start",
                                                                 "period_end", "filters")}},
                    recommendation="Re-export partitioned intervals/resources without truncation, with retention notes.",
                    uncertainty="Unlisted changes may exist.")


def _resource_mapping(ctx) -> None:
    """Step 2: resource → stable IDs; shared budget changes listed once with all members."""
    chk = ctx.check("resource_mapping", "Resource-to-ID mapping and shared-budget members",
                    {CH: ["change_id", "field_path", "resource_name", "campaign_id", "budget_id", "strategy_id"],
                     "campaigns": ["id"]})
    if not chk.runnable:
        return
    if "budget_id" not in ctx.table("campaigns").columns:
        chk.partial("campaigns.budget_id missing: shared-budget members unknown", ["campaigns:budget_id"])
    camps = {_s(c.get("id")) for c in ctx.rows("campaigns")}
    budgets = {_s(b.get("id")) for b in ctx.rows("budgets")}
    strategies = {_s(b.get("id")) for b in ctx.rows("bidding_strategies")}
    if ctx.table("budgets") is None:
        chk.partial("budgets inventory missing: budget IDs checked only via campaigns.budget_id", ["budgets (file)"])
    if ctx.table("bidding_strategies") is None:
        chk.partial("bidding_strategies inventory missing: strategy IDs unverified", ["bidding_strategies (file)"])
    members = _budget_members(ctx)
    budgets |= set(members)
    unmapped, unknown_ids, shared = [], [], {}
    for r in _rows(ctx):
        cid, bid, sid = _s(r.get("campaign_id")), _s(r.get("budget_id")), _s(r.get("strategy_id"))
        ref = f"{_s(r.get('change_id'))}:{_s(r.get('field_path'))}"
        if not (cid or bid or sid):
            unmapped.append(ref)
            continue
        if (cid and cid not in camps) or (bid and bid not in budgets) or \
                (sid and ctx.table("bidding_strategies") is not None and sid not in strategies):
            unknown_ids.append(ref)
        if bid and len(members.get(bid, [])) > 1:
            shared.setdefault((_s(r.get("change_id")), bid), (r, members[bid]))
    for (chg, bid), (r, mem) in sorted(shared.items()):
        chk.observe(f"Shared budget {bid} change {chg}: one delta affecting {len(mem)} campaigns (not multiplied)",
                    change_id=chg, budget_id=bid, member_campaign_ids=mem, field_path=r.get("field_path"),
                    old_value=r.get("old_value"), new_value=r.get("new_value"), occurred_at=r.get("occurred_at"))
    chk.observe("Mapping totals", unmapped_rows=len(unmapped), ids_not_in_inventory=len(unknown_ids),
                shared_budget_changes=len(shared))
    if unmapped:
        chk.partial(f"{len(unmapped)} field rows without campaign/budget/strategy ID: {unmapped[:10]}")
    if unknown_ids:
        chk.partial(f"{len(unknown_ids)} field rows reference IDs absent from inventory (removed or out of scope): "
                    f"{unknown_ids[:10]}")


def _value_deltas(ctx) -> None:
    """Step 3: same-unit numeric deltas; add/remove/update; unknown values and actors."""
    chk = ctx.check("value_ledger", "Field ledger, numeric deltas and actor attribution",
                    {CH: ["change_id", "field_path", "occurred_at", "operation", "old_value", "new_value",
                          "client_type", "actor_id"]})
    if not chk.runnable:
        return
    ops: dict[str, int] = {}
    unknown_values = 0
    no_actor: dict[str, list[dict]] = {}
    for r in _rows(ctx):
        field, op = _s(r.get("field_path")), _op(r.get("operation"))
        ops[op] = ops.get(op, 0) + 1
        old, new = _value(field, r.get("old_value")), _value(field, r.get("new_value"))
        delta = new - old if op == "update" and old is not None and new is not None else None
        if op == "update" and (r.get("old_value") is None or r.get("new_value") is None):
            unknown_values += 1
        chk.observe(f"Change {_s(r.get('change_id'))} {field}", change_id=r.get("change_id"), field_path=field,
                    occurred_at=r.get("occurred_at"), operation=op, resource_name=r.get("resource_name"),
                    campaign_id=r.get("campaign_id"), budget_id=r.get("budget_id"), strategy_id=r.get("strategy_id"),
                    old_value=r.get("old_value"), new_value=r.get("new_value"), delta=delta,
                    unit="currency (micros/1e6)" if field.endswith("_micros") and delta is not None else None,
                    actor_id=r.get("actor_id"), client_type=r.get("client_type"), approval_ref=r.get("approval_ref"))
        if not _s(r.get("actor_id")):
            no_actor.setdefault(_s(r.get("change_id")), []).append(r)
    for chg in sorted(no_actor):
        rs = no_actor[chg]
        chk.finding("unknown_source", "Info", {"change_id": chg, "campaign_id": rs[0].get("campaign_id"),
                                               "budget_id": rs[0].get("budget_id"),
                                               "strategy_id": rs[0].get("strategy_id")},
                    f"Change {chg} has no actor_id (client_type {rs[0].get('client_type')}); source unknown",
                    evidence={"fields": [r.get("field_path") for r in rs], "client_type": rs[0].get("client_type"),
                              "occurred_at": rs[0].get("occurred_at")},
                    recommendation="Match against the client's known-source inventory before any conclusion.",
                    uncertainty="Client type alone does not identify the exact script or person.")
    chk.observe("Operation counts", **{f"operations_{k}": v for k, v in sorted(ops.items())},
                updates_with_unknown_value=unknown_values)


def _scope_ok(scope: str, r: dict) -> bool:
    toks = [x.strip() for x in V.split_list(scope, _SEPS)]
    ids = {_s(r.get(k)) for k in ("resource_name", "campaign_id", "budget_id", "strategy_id", "account_id")} - {""}
    return any(t.lower() in _WILDCARD or t in ids for t in toks)


def _constraint(expr, value) -> bool | None:
    """True = satisfied, False = violated, None = undecidable (free text/unknown value)."""
    e = _s(expr)
    if not e or e.lower() in _WILDCARD:
        return True
    if value is None:
        return None
    v = V.num(value)
    m = _CMP.match(e)
    if m and v is not None:
        op, x = m.group(1), float(m.group(2))
        return {"<=": v <= x, ">=": v >= x, "<": v < x, ">": v > x, "=": v == x, "==": v == x}[op]
    m = _RNG.match(e)
    if m and v is not None:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        return lo <= v <= hi
    return None


def _evaluate(auth: dict, r: dict) -> tuple[list[str], list[str]]:
    violations, undecided = [], []
    actors = V.split_list(auth.get("permitted_actor_ids"), _SEPS)
    actor = _s(r.get("actor_id"))
    if actors and not any(a.lower() in _WILDCARD for a in actors):
        if not actor:
            undecided.append("actor unknown")
        elif actor not in actors:
            violations.append(f"actor {actor} not in permitted_actor_ids {actors}")
    sources = [x.upper() for x in V.split_list(auth.get("permitted_source"), _SEPS)]
    src = _s(r.get("client_type")).upper()
    if sources and not any(x.lower() in _WILDCARD for x in sources):
        if not src:
            undecided.append("client_type unknown")
        elif src not in sources:
            violations.append(f"client_type {src} not in permitted_source {sources}")
    d = V.parse_date(r.get("occurred_at"))
    vf, vt = V.parse_date(auth.get("valid_from")), V.parse_date(auth.get("valid_to"))
    if d is None:
        undecided.append("occurred_at unknown")
    elif (vf and d < vf) or (vt and d > vt):
        violations.append(f"occurred {d} outside validity {vf}..{vt}")
    for col, val in (("old_value_constraint", r.get("old_value")), ("new_value_constraint", r.get("new_value"))):
        ok = _constraint(auth.get(col), val)
        if ok is False:
            violations.append(f"{col.split('_')[0]} value {val} violates '{auth.get(col)}'")
        elif ok is None:
            undecided.append(f"{col} '{auth.get(col)}' not machine-decidable for value {val}")
    return violations, undecided


def _authorization(ctx) -> set[tuple[str, str]]:
    """Step 4: join scope, field, time, actor/source and values to explicit authorization rows."""
    chk = ctx.check("authorization_match", "Changes vs explicit authorization register",
                    {CH: ["change_id", "field_path", "occurred_at", "resource_name", "campaign_id", "budget_id",
                          "strategy_id", "client_type", "actor_id", "old_value", "new_value", "approval_ref"],
                     AUTH: ["approval_ref", "resource_scope", "field", "permitted_actor_ids", "permitted_source",
                            "old_value_constraint", "new_value_constraint", "valid_from", "valid_to", "owner",
                            "review_status"]})
    resolved: set[tuple[str, str]] = set()
    if not chk.runnable:
        return resolved
    register: dict[str, list[dict]] = {}
    for a in ctx.rows(AUTH):
        register.setdefault(_s(a.get("approval_ref")), []).append(a)
    rows = _rows(ctx)
    missing: dict[str, list[dict]] = {}
    counts = {"authorized": 0, "violations": 0, "missing": 0, "review": 0}
    for r in rows:
        chg, field, ref = _s(r.get("change_id")), _s(r.get("field_path")), _s(r.get("approval_ref"))
        if not ref or ref not in register:
            missing.setdefault(chg, []).append(r)
            counts["missing"] += 1
            continue
        resolved.add((chg, field))
        entity = {"change_id": chg, "field_path": field, "approval_ref": ref, "campaign_id": r.get("campaign_id"),
                  "budget_id": r.get("budget_id"), "strategy_id": r.get("strategy_id")}
        later = sum(1 for x in rows if _s(x.get("field_path")) == field
                    and _s(x.get("resource_name")) == _s(r.get("resource_name"))
                    and _s(x.get("occurred_at")) > _s(r.get("occurred_at")))
        change_ev = {k: r.get(k) for k in ("occurred_at", "resource_name", "operation", "actor_id", "client_type",
                                           "old_value", "new_value")}
        change_ev["subsequent_edits_same_field"] = later
        cands = [a for a in register[ref] if _s(a.get("field")) in (field, "*") and _scope_ok(_s(a.get("resource_scope")), r)]
        if not cands:
            counts["review"] += 1
            prov = chk.finding("authorization_scope_unclear", "Info", entity,
                               f"Change {chg} {field} cites {ref}, but no register row matches this field and scope",
                               evidence={"change": change_ev, "register_rows": register[ref]},
                               recommendation="Ask the approval owner whether this field/resource was in scope.",
                               uncertainty="Scope labels may use different identifiers.")
            chk.review("authorization_scope", entity,
                       f"Does approval {ref} cover change {chg} to {field} on {r.get('resource_name')}?",
                       evidence={"change": change_ev, "register_rows": register[ref]},
                       outcomes={"outside_authorization": {"severity": "Warning", "recommendation":
                                                           "Conditional review proposal; inspect current state first."},
                                 "covered": {"severity": None, "recommendation": "Record as authorized."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the approval owner."}},
                       guidance="Use only the register text; no documentation is unknown, not unauthorized.",
                       provisional=prov)
            continue
        results = [(a, *_evaluate(a, r)) for a in cands]
        if any(not v and not u for _, v, u in results):
            counts["authorized"] += 1
            continue
        clean_undecided = [(a, u) for a, v, u in results if not v]
        if clean_undecided:
            counts["review"] += 1
            a, u = clean_undecided[0]
            prov = chk.finding("authorization_constraint_unclear", "Info", entity,
                               f"Change {chg} {field} under {ref}: constraints not machine-decidable ({'; '.join(u)})",
                               evidence={"change": change_ev, "authorization": a, "undecided": u},
                               recommendation="Confirm the constraint meaning with the approval owner.",
                               uncertainty="Free-text constraint.")
            chk.review("authorization_constraint", entity,
                       f"Do the values of change {chg} ({r.get('old_value')} → {r.get('new_value')}) comply with "
                       f"approval {ref}?",
                       evidence={"change": change_ev, "authorization": a, "undecided": u},
                       outcomes={"violates_authorization": {"severity": "Warning", "recommendation":
                                                            "Conditional review proposal; preserve approved changes."},
                                 "complies": {"severity": None, "recommendation": "Record as authorized."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the approval owner."}},
                       guidance="Judge only the documented constraint text against the exact old/new values.",
                       provisional=prov)
            continue
        counts["violations"] += 1
        chk.finding("authorization_violation", "Warning", entity,
                    f"Change {chg} {field} contradicts approval {ref}: "
                    + " | ".join(sorted({x for _, v, _ in results for x in v})),
                    evidence={"change": change_ev, "authorizations": [a for a, _, _ in results],
                              "violations": [v for _, v, _ in results]},
                    recommendation="Conditional review with the approval owner; inspect current state and "
                                   "subsequent edits before any reversal proposal (no automatic reversion).",
                    uncertainty="Delivery impact is not measured by this check.")
        chk.review("authorization_violation_impact", entity,
                   f"Is there direct evidence that change {chg} caused MATERIAL delivery or safety failure?",
                   evidence={"change": change_ev},
                   outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                            "Escalate to the approval owner; cite the evidence."},
                             "not_evidenced": {"severity": None, "recommendation": "Keep the Warning."}},
                   guidance="Critical needs proposal.evidence_ref to supplied delivery/safety evidence.")
    for chg in sorted(missing):
        rs = missing[chg]
        chk.finding("missing_authorization", "Info",
                    {"change_id": chg, "campaign_id": rs[0].get("campaign_id"), "budget_id": rs[0].get("budget_id"),
                     "strategy_id": rs[0].get("strategy_id")},
                    f"Change {chg} ({len(rs)} fields) has no resolvable approval_ref; authorization unknown",
                    evidence={"fields": [x.get("field_path") for x in rs],
                              "approval_refs": sorted({_s(x.get("approval_ref")) for x in rs}),
                              "actor_id": rs[0].get("actor_id"), "client_type": rs[0].get("client_type"),
                              "occurred_at": rs[0].get("occurred_at")},
                    recommendation="Request the client change-register entry; do not treat as unauthorized.",
                    uncertainty="Missing documentation is not confirmed unauthorized behaviour.")
    as_of = ctx.as_of
    for ref in sorted(register):
        for a in register[ref]:
            st = _s(a.get("review_status")).lower()
            vt = V.parse_date(a.get("valid_to"))
            if "overdue" in st or (st in ("pending", "required", "review_required") and vt and as_of and vt < as_of):
                chk.finding("authorization_review_overdue", "Warning",
                            {"approval_ref": ref, "field": a.get("field"), "resource_scope": a.get("resource_scope")},
                            f"Approval {ref} review is overdue (status '{a.get('review_status')}', valid_to {vt}, "
                            f"as of {as_of})",
                            evidence={"authorization": a, "as_of": as_of},
                            recommendation=f"Ask owner {a.get('owner')} to complete the required review.",
                            uncertainty="Due date inferred from valid_to where no explicit due date exists.")
    chk.observe("Authorization join totals", **counts)
    return resolved


def _unrecognized_actors(ctx, resolved: set) -> None:
    """#57 clean-room: changes by actors outside the profile's recognized list, without resolvable approval."""
    chk = ctx.check("unrecognized_actors", "Changes by actors outside the recognized list (#57)",
                    {CH: ["change_id", "field_path", "occurred_at", "actor_id", "client_type", "campaign_id"]})
    if not chk.runnable:
        return
    known = {str(x) for x in (ctx.profile.get("change_recognized_actors") or [])}
    known_types = {str(x).upper() for x in (ctx.profile.get("change_recognized_client_types") or [])}
    if not known:
        chk.skip("no recognized actor list in profile", ["profile.change_recognized_actors"])
        return
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in _rows(ctx):
        actor, ctype = _s(r.get("actor_id")), _s(r.get("client_type")).upper()
        if actor in known or ctype in known_types or not actor:
            continue
        if (_s(r.get("change_id")), _s(r.get("field_path"))) in resolved:
            continue
        groups.setdefault((actor, ctype), []).append(r)
    for (actor, ctype) in sorted(groups):
        rs = groups[(actor, ctype)]
        ids = sorted({_s(r.get("change_id")) for r in rs})
        chk.finding("unrecognized_actor_changes", "Info", {"actor_id": actor, "client_type": ctype},
                    f"Actor {actor} ({ctype or 'unknown client'}) made {len(ids)} changes ({len(rs)} field rows) "
                    f"outside the recognized list without a resolvable approval",
                    evidence={"change_ids": ids, "campaign_ids": sorted({_s(r.get('campaign_id')) for r in rs} - {""}),
                              "first": rs[0].get("occurred_at"), "last": rs[-1].get("occurred_at"),
                              "fields": sorted({_s(r.get("field_path")) for r in rs})},
                    recommendation="Confirm with the account owner whether this source is known; add it to the "
                                   "recognized list or the change register.",
                    uncertainty="Unrecognized is not unauthorized; volume or timing alone is not a defect.")
    chk.observe("Recognized-actor screen", recognized_actors=len(known), unrecognized_actor_groups=len(groups))


def _outcomes(ctx) -> None:
    """Step 5: optional mature pre/post outcome association, descriptive and non-causal."""
    chk = ctx.check("outcome_association", "Descriptive pre/post outcomes around changes (non-causal)",
                    {OUT: ["campaign_id", "date", "impressions", "clicks", "cost", "conversions", "maturity"],
                     CH: ["change_id", "occurred_at", "campaign_id", "budget_id"]})
    if not chk.runnable:
        return
    if ctx.mature is not True:
        chk.partial(f"maturity {ctx.mature} ({ctx.maturity_note}): outcome comparison withheld")
        return
    mi, mcl, mc = (ctx.params.get(p) for p in ("min_impressions", "min_clicks", "min_conversions"))
    days: dict[str, dict[date, dict]] = {}
    for r in ctx.rows(OUT):
        d = V.parse_date(r.get("date"))
        if d is not None and _s(r.get("maturity")).lower() == "mature":
            days.setdefault(_s(r.get("campaign_id")), {})[d] = r
    members = _budget_members(ctx)
    pairs: set[tuple[str, date]] = set()
    for r in _rows(ctx):
        d = V.parse_date(r.get("occurred_at"))
        if d is None:
            continue
        targets = {_s(r.get("campaign_id"))} | set(members.get(_s(r.get("budget_id")), []))
        pairs |= {(c, d) for c in targets if c}
    for cid, d in sorted(pairs):
        series = days.get(cid, {})
        pre = [series.get(d - timedelta(days=i)) for i in range(1, 8)]
        post = [series.get(d + timedelta(days=i)) for i in range(1, 8)]
        if any(x is None for x in pre + post):
            chk.observe(f"{cid} {d}: incomplete mature 7-day windows; no comparison", campaign_id=cid, change_date=d)
            continue

        def tot(xs):
            return {k: sum((ctx.money if k == "cost" else V.num)(x.get(k)) or 0 for x in xs)
                    for k in ("impressions", "clicks", "cost", "conversions")}
        a, b = tot(pre), tot(post)
        ok = lambda k, p: p.value is not None and a[k] >= p.value and b[k] >= p.value  # noqa: E731
        chk.observe(f"{cid} around {d}: pre/post association (non-causal)", campaign_id=cid, change_date=d,
                    pre=a, post=b, window_days=7,
                    ctr=[V.ratio(a["clicks"], a["impressions"]), V.ratio(b["clicks"], b["impressions"])]
                    if ok("impressions", mi) else None,
                    cvr=[V.ratio(a["conversions"], a["clicks"]), V.ratio(b["conversions"], b["clicks"])]
                    if ok("clicks", mcl) else None,
                    cpa=[V.ratio(a["cost"], a["conversions"]), V.ratio(b["cost"], b["conversions"])]
                    if ok("conversions", mc) else None)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcome requires proposal.evidence_ref."""
    if decision.get("outcome") == "material_failure_evidenced" and not (decision.get("proposal") or {}).get("evidence_ref"):
        return ["material_failure_evidenced needs proposal.evidence_ref pointing at supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
