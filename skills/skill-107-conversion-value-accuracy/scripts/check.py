"""check.py — skill-107 deterministic conversion value policy, payload QA, residual and calibration checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-107-conversion-value-accuracy/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-071-conversion-tracking-accuracy — owns reconciliation findings; step 5 only observes linked residuals
         skills/skill-112-return-refund-tracking — owns refund adjustments; step 8 only queues double-deduction review
rules:   Zero/unit values are never defects. Info 'count_based_zero_unit_value' only when EVERY campaign declaring the
         action as a goal (ctx.goal_ids; goal matches action id/name/category) bids count-based (known strategy not in
         TARGET_ROAS/MAXIMIZE_CONVERSION_VALUE and no profile campaign_objectives[id].target_roas).
         Value configuration = conversion_actions.value_settings (documented alternative: value_configuration);
         parsed as dynamic ('transaction'/'dynamic'), or one number → zero/unit/static; anything else → unknown, no finding.
         Current policy = conversion_value_policy row with validity_start <= ctx.as_of <= validity_end (blank bound = open);
         >1 current row per action → ambiguous → partial, no comparison. Absence findings need a manifest-complete table.
         Payload QA compares only rows with policy_version == current version and tested_at >= validity_start; stale QA
         → partial, never a pass. Value tolerance: |observed − expected| > 0.005 currency units (expected_value is the
         owner's policy-computed, already-rounded value; half a minor unit absorbs float formatting only).
         External finance/QA values are plain currency units (V.num); Ads report values use ctx.money.
         Step 5 (071 link) is observation only: mature window = period_start..min(period_end, snapshot − maturity_days),
         Ads rows need reporting_mature true; tolerance_value_pct is percent points (5 = 5%). 071 owns the finding.
         Calibration: mature iff cohort_end + horizon_days <= ctx.snapshot (else ctx.as_of); observed_vs_predicted_value is
         the ratio observed÷predicted (1.0 = calibrated), drift = |ratio − 1| compared with the owner tolerance
         profile.value_calibration_tolerance (fraction, e.g. 0.15); absent → partial, no finding. Sample gate:
         mature_outcomes >= min_conversions.
         Gross/net, tax/shipping/discount/refund/FX treatments are business choices: discrepancies only raise reviews.
         Critical only via review outcomes 'material_value_corruption_confirmed' / 'double_deduction_confirmed'; verify()
         requires proposal.evidence_ref naming a ref listed in the item's evidence.evidence_refs. Never reduce values.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-107-conversion-value-accuracy"
VERSION = "1.0.0"

POLICY = "external/conversion_value_policy"
QA = "external/value_payload_qa"
CALIB = "external/value_model_calibration"
RULES = "external/reconciliation_rules"
EVENTS = "external/business_events"
DAILY = "custom/ads_reconciliation_daily"
LEDGER = "external/ads_event_reconciliation"
ADJ = "external/conversion_adjustments"

VALUE_BIDDING = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
NON_VALUE_BIDDING = {"TARGET_CPA", "MAXIMIZE_CONVERSIONS", "MANUAL_CPC", "ENHANCED_CPC", "MAXIMIZE_CLICKS",
                     "TARGET_SPEND", "TARGET_IMPRESSION_SHARE", "MANUAL_CPM", "MANUAL_CPV", "TARGET_CPM"}
MODEL_TYPE_WORDS = ("proxy", "lead", "ltv", "lifetime", "predict", "profit", "model")
VALUE_TOLERANCE = 0.005
CRITICAL_OUTCOMES = ("material_value_corruption_confirmed", "double_deduction_confirmed")
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_CUR = re.compile(r"\b([A-Z]{3})\b")


# ---------------------------------------------------------------------------- helpers
def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _up(v) -> str | None:
    return _s(v).upper() or None


def _value_class(text) -> tuple[str, float | None, str | None]:
    """(class, numeric default, explicit currency) from a flattened value setting; unknown when ambiguous."""
    raw = _s(text)
    s = V.norm_text(raw)
    if not s:
        return "unknown", None, None
    cur = next(iter(_CUR.findall(raw)), None)
    if "transaction" in s or "dynamic" in s:
        return "dynamic", None, cur
    nums = _NUM.findall(s)
    if len(nums) != 1:
        return "unknown", None, cur
    v = float(nums[0].replace(",", "."))
    return ("zero" if v == 0 else "unit" if v == 1 else "static"), v, cur


def _value_col(ctx) -> str:
    t = ctx.table("conversion_actions")
    if t and "value_settings" not in t.columns and "value_configuration" in t.columns:
        return "value_configuration"
    return "value_settings"


def _active_actions(ctx) -> list[dict]:
    rows = [r for r in ctx.rows("conversion_actions") if r.get("id") is not None
            and _s(r.get("status")).upper() != "REMOVED"]
    return sorted(rows, key=lambda r: str(r.get("id")))


def _objective(ctx, cid: str):
    objs = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objs, dict):
        return None
    return next((v for k, v in objs.items() if str(k) == cid), None)


def _strategy(ctx, camp: dict) -> tuple[str | None, str]:
    t = _up(camp.get("bidding_strategy_type"))
    if t:
        return t, "campaigns.bidding_strategy_type"
    sid = camp.get("bidding_strategy_id") or camp.get("strategy_id")
    if sid:
        srow = next((r for r in ctx.rows("bidding_strategies") if str(r.get("id")) == str(sid)), None)
        if srow and _up(srow.get("type")):
            return _up(srow.get("type")), f"bidding_strategies.type[{sid}]"
    return None, "strategy type unknown"


def _role(ctx, cid: str, stype: str | None) -> str:
    obj = _objective(ctx, cid)
    if stype in VALUE_BIDDING or (isinstance(obj, dict) and obj.get("target_roas") is not None):
        return "value"
    if stype in NON_VALUE_BIDDING:
        return "count"
    return "unknown"


def _action_campaigns(ctx, actions: list[dict]) -> tuple[dict, list[str], list[list[str]]]:
    """action_id -> [{campaign_id, strategy, source, role}] via declared goals; plus unmapped campaigns/goals."""
    out: dict[str, dict[str, dict]] = {}
    no_goal, unmatched = [], []
    camps = sorted((r for r in ctx.rows("campaigns") if r.get("id") is not None
                    and _s(r.get("status")).upper() != "REMOVED"), key=lambda r: str(r.get("id")))
    for camp in camps:
        cid = str(camp.get("id"))
        goals = ctx.goal_ids(cid)
        if not goals:
            no_goal.append(cid)
            continue
        stype, src = _strategy(ctx, camp)
        role = _role(ctx, cid, stype)
        for g in goals:
            gl = str(g).lower()
            matched = [a for a in actions if gl in {_s(a.get(k)).lower() for k in ("id", "name", "category")}]
            if not matched:
                unmatched.append([cid, str(g)])
            for a in matched:
                out.setdefault(str(a.get("id")), {})[cid] = {"campaign_id": cid, "strategy": stype,
                                                             "strategy_source": src, "role": role}
    return {k: [v[c] for c in sorted(v)] for k, v in out.items()}, no_goal, unmatched


def _current_policies(ctx) -> tuple[dict, dict, list[str], dict]:
    """Current policy row per action at ctx.as_of: (current, ambiguous versions, invalid-date notes, all versions)."""
    ref = ctx.as_of or ctx.period_end
    current: dict[str, list[dict]] = {}
    versions: dict[str, list[str]] = {}
    invalid = []
    for r in ctx.rows(POLICY):
        aid = _s(r.get("action_id"))
        if not aid:
            invalid.append("policy row without action_id")
            continue
        versions.setdefault(aid, []).append(_s(r.get("policy_version")) or "?")
        s_raw, e_raw = r.get("validity_start"), r.get("validity_end")
        s, e = V.parse_date(s_raw), V.parse_date(e_raw)
        if (s_raw is not None and s is None) or (e_raw is not None and e is None) or ref is None:
            invalid.append(f"action {aid} version {r.get('policy_version')}: validity undecidable")
            continue
        if (s is None or s <= ref) and (e is None or e >= ref):
            current.setdefault(aid, []).append(r)
    single = {a: rows[0] for a, rows in current.items() if len(rows) == 1}
    ambiguous = {a: sorted(_s(x.get("policy_version")) for x in rows) for a, rows in current.items() if len(rows) > 1}
    return single, ambiguous, invalid, {a: sorted(v) for a, v in versions.items()}


def _applicable(text) -> bool:
    t = V.norm_text(text)
    return bool(t) and not t.startswith(("not applicable", "not_applicable", "n/a"))


def _is_model_type(value_type) -> bool:
    t = V.norm_text(value_type)
    return any(w in t for w in MODEL_TYPE_WORDS)


def _skip_all(ctx, specs, reason, missing) -> None:
    for cid, title in specs:
        ctx.check(cid, title).skip(reason, missing)


# ---------------------------------------------------------------------------- step 1
def _step1_value_map(ctx, state) -> None:
    col = _value_col(ctx)
    c = ctx.check("value_goal_map", "Map action values to campaign goals and count/value bidding",
                  {"conversion_actions": ["id", col], "campaigns": ["id", "bidding_strategy_type"]})
    if not c.runnable:
        return
    actions = _active_actions(ctx)
    mapping, no_goal, unmatched = _action_campaigns(ctx, actions)
    state["mapping"] = mapping
    if no_goal:
        c.partial(f"campaigns without declared goal_ids (action mapping unknown): {no_goal}",
                  ["campaigns:goal_ids (or profile.campaign_objectives[id].goal_ids)"])
    if unmatched:
        c.partial(f"declared goals matching no conversion action: {unmatched}")
    inventory, undecided = [], []
    for a in actions:
        aid = str(a.get("id"))
        cls, num, cur = _value_class(a.get(col))
        state["value_class"][aid] = {"class": cls, "default": num, "currency": cur, "setting": a.get(col)}
        camps = mapping.get(aid, [])
        roles = sorted({x["role"] for x in camps})
        inventory.append({"action_id": aid, "name": a.get("name"), "category": a.get("category"),
                          "status": a.get("status"), "include_in_conversions": a.get("include_in_conversions"),
                          "primary_for_goal": a.get("primary_for_goal"), "value_setting": a.get(col),
                          "value_class": cls, "campaigns": camps})
        if cls not in ("zero", "unit"):
            continue
        if camps and roles == ["count"]:
            c.finding("count_based_zero_unit_value", "Info", {"action_id": aid},
                      f"Action {aid} uses a {cls} value ({a.get(col)}) and every campaign using it as a goal bids on counts",
                      evidence={"value_setting": a.get(col), "value_class": cls, "campaigns": camps},
                      calculation={"rule": "all mapped campaigns have a known non-value strategy and no target_roas"},
                      recommendation="No value change needed for count-based bidding; confirm the count role stays "
                                     "intended before any move to value-based bidding.",
                      uncertainty="Declared goals and strategy snapshot only; business value basis is set by the owner policy.")
        else:
            undecided.append({"action_id": aid, "value_class": cls, "roles": roles or ["unmapped"]})
    c.observe("Value configuration inventory by action and campaign strategy", actions=inventory,
              zero_or_unit_not_count_confirmed=undecided, value_column=f"conversion_actions:{col}")


# ---------------------------------------------------------------------------- step 2
def _step2_policy(ctx, state) -> None:
    c = ctx.check("value_policy_type", "Identify documented value policy per action",
                  {POLICY: ["action_id", "policy_version", "objective", "intended_bidding_role", "value_type",
                            "validity_start", "validity_end"], "conversion_actions": ["id"]})
    if not c.runnable:
        return
    current, ambiguous, invalid, versions = _current_policies(ctx)
    state["policy"], state["policy_ok"] = current, True
    for note in invalid:
        c.partial(note)
    if ambiguous:
        c.partial(f"several current policy versions for actions {ambiguous}: no comparison possible")
    complete = ctx.table(POLICY).complete is True
    known = {str(a.get("id")) for a in _active_actions(ctx)}
    inventory, unproven = [], []
    for aid in sorted(known):
        if aid in ambiguous:
            continue
        p = current.get(aid)
        vc = state["value_class"].get(aid, {})
        value_campaigns = [x["campaign_id"] for x in state["mapping"].get(aid, []) if x["role"] == "value"]
        if p is None or p.get("value_type") is None:
            if not complete:
                unproven.append(aid)
                continue
            reason = "no policy row valid at as_of" if p is None else "current policy has blank value_type"
            c.finding("unknown_business_basis", "Info", {"action_id": aid},
                      f"Action {aid}: {reason}; value business basis is unknown",
                      evidence={"as_of": ctx.as_of, "policy_versions_present": versions.get(aid, []),
                                "value_setting": vc.get("setting"), "value_class": vc.get("class"),
                                "value_bidding_campaigns": value_campaigns},
                      calculation={"current_rule": "validity_start <= as_of <= validity_end (blank = open)"},
                      recommendation="Ask the measurement/finance owner to document objective, value type and "
                                     "bidding role before judging value accuracy.",
                      uncertainty="Missing documentation is not a value defect.")
            continue
        inventory.append({"action_id": aid, "policy_version": p.get("policy_version"), "value_type": p.get("value_type"),
                          "objective": p.get("objective"), "intended_bidding_role": p.get("intended_bidding_role"),
                          "owner": p.get("owner"), "value_class_in_ads": vc.get("class"),
                          "value_bidding_campaigns": value_campaigns})
    if unproven:
        c.partial(f"{ctx.table(POLICY).filename}: completeness not attested; actions {unproven} lack a current "
                  "policy row but absence is not provable")
    orphans = sorted(set(versions) - known)
    c.observe("Current value policy by action", policies=inventory, as_of=ctx.as_of, orphan_policy_actions=orphans)


# ---------------------------------------------------------------------------- step 3
def _qa_row(r) -> dict:
    return {k: r.get(k) for k in ("test_id", "scenario", "tested_at", "policy_version", "expected_value",
                                  "observed_value", "currency", "value_source", "default_used",
                                  "duplicate_send_count", "status", "source_reference")}


def _step3_default(ctx, state) -> None:
    col = _value_col(ctx)
    c = ctx.check("default_policy_config", "Compare configured Ads default value with the documented fallback",
                  {"conversion_actions": ["id", col],
                   POLICY: ["action_id", "policy_version", "currency", "fallback_value", "fallback_conditions",
                            "validity_start", "validity_end"]})
    state["gate_checks"].append(c)
    if not c.runnable:
        return
    current, ambiguous, _, _ = _current_policies(ctx)
    if ambiguous:
        c.partial(f"ambiguous current policies skipped: {sorted(ambiguous)}")
    actions = {str(a.get("id")): a for a in _active_actions(ctx)}
    compared, not_numeric = [], []
    for aid in sorted(current):
        p = current[aid]
        if aid not in actions:
            continue
        setting = actions[aid].get(col)
        cls, dflt, dcur = _value_class(setting)
        pcur, fb = _up(p.get("currency")), V.num(p.get("fallback_value"))
        if cls not in ("zero", "unit", "static"):
            not_numeric.append(aid)
            continue
        compared.append(aid)
        conflicts = []
        if dcur and pcur and dcur != pcur:
            conflicts.append(("default_currency_conflict", f"Ads default currency {dcur} ≠ policy {pcur}"))
        elif fb is not None and abs(dflt - fb) > VALUE_TOLERANCE:
            conflicts.append(("default_value_conflict", f"Ads default {dflt:g} ≠ policy fallback {fb:g}"))
        for key, text in conflicts:
            f = c.finding(key, "Warning", {"action_id": aid, "policy_version": p.get("policy_version")},
                          f"Action {aid}: {text}",
                          evidence={"value_setting": setting, "policy_fallback_value": p.get("fallback_value"),
                                    "policy_currency": pcur, "fallback_conditions": p.get("fallback_conditions")},
                          calculation={"tolerance": VALUE_TOLERANCE, "basis": "configured default vs documented fallback"},
                          recommendation="Review the action default value against the documented fallback; no automatic change.",
                          uncertainty="Flattened value setting; confirm the live default before changing it.")
            state["defects"].setdefault(aid, []).append(
                {"condition": key, "finding_id": f.id,
                 "refs": [ctx.table(POLICY).filename, ctx.table("conversion_actions").filename]})
    c.observe("Configured default vs documented fallback", compared=compared,
              dynamic_or_unparsed_defaults=not_numeric, tolerance=VALUE_TOLERANCE)


def _step3_payload(ctx, state) -> None:
    c = ctx.check("payload_policy_qa", "Compare payload QA behavior with the current value policy",
                  {QA: ["test_id", "action_id", "scenario", "tested_at", "policy_version", "expected_value",
                        "observed_value", "currency", "default_used", "duplicate_send_count"],
                   POLICY: ["action_id", "policy_version", "value_type", "currency", "fallback_value",
                            "fallback_conditions", "discount_treatment", "refund_treatment",
                            "validity_start", "validity_end"]})
    state["gate_checks"].append(c)
    if not c.runnable:
        return
    current, ambiguous, _, _ = _current_policies(ctx)
    qa_by: dict[str, list[dict]] = {}
    for r in ctx.rows(QA):
        qa_by.setdefault(_s(r.get("action_id")), []).append(r)
    compared = 0
    for aid in sorted(qa_by):
        rows = sorted(qa_by[aid], key=lambda r: (_s(r.get("scenario")), _s(r.get("test_id"))))
        p = current.get(aid)
        if p is None:
            c.partial(f"QA rows for action {aid} without a single current policy"
                      + (f" (ambiguous {ambiguous[aid]})" if aid in ambiguous else ""))
            continue
        ver, start = _s(p.get("policy_version")), V.parse_date(p.get("validity_start"))
        fresh, stale = [], []
        for r in rows:
            tested = V.parse_date(r.get("tested_at"))
            if _s(r.get("policy_version")) != ver or (start and (tested is None or tested < start)):
                stale.append(_s(r.get("test_id")))
            else:
                fresh.append(r)
        if stale:
            c.partial(f"action {aid}: QA {stale} not for current policy_version {ver} (stale, not a pass)")
        pcur = _up(p.get("currency"))
        no_fallback = p.get("fallback_value") is None and p.get("fallback_conditions") is None
        hits: dict[str, list[dict]] = {}
        for r in fresh:
            compared += 1
            exp, obs = V.num(r.get("expected_value")), V.num(r.get("observed_value"))
            if exp is not None and obs is not None and abs(obs - exp) > VALUE_TOLERANCE:
                hits.setdefault("payload_value_mismatch", []).append(_qa_row(r))
            elif exp is None or obs is None:
                c.partial(f"action {aid} test {r.get('test_id')}: expected/observed value unknown")
            qcur = _up(r.get("currency"))
            if qcur and pcur and qcur != pcur:
                hits.setdefault("payload_currency_mismatch", []).append(_qa_row(r))
            dup = V.num(r.get("duplicate_send_count"))
            if dup is not None and dup > 1:
                hits.setdefault("duplicate_send", []).append(_qa_row(r))
            if V.boolean(r.get("default_used")) is True and no_fallback:
                hits.setdefault("default_used_without_policy_fallback", []).append(_qa_row(r))
        for key in sorted(hits):
            ev = hits[key]
            f = c.finding(key, "Warning", {"action_id": aid, "policy_version": ver},
                          f"Action {aid}: payload QA conflicts with value policy {ver} ({key}, {len(ev)} test(s))",
                          evidence={"tests": ev, "policy_currency": pcur, "policy_fallback_value": p.get("fallback_value"),
                                    "policy_value_type": p.get("value_type")},
                          calculation={"value_tolerance": VALUE_TOLERANCE,
                                       "basis": "expected_value is owner policy-computed and rounded; |observed-expected|",
                                       "duplicate_rule": "duplicate_send_count > 1"},
                          recommendation="Scope a payload/tag or import review for the failing scenarios; do not "
                                         "reduce or rescale reported values automatically.",
                          uncertainty="Synthetic QA scenarios show implementation behavior, not transaction-level impact.")
            refs = sorted({_s(x.get("test_id")) for x in ev} | {_s(x.get("source_reference")) for x in ev} - {""})
            state["defects"].setdefault(aid, []).append({"condition": key, "finding_id": f.id, "refs": refs})
        required = {"ordinary", "missing"}
        if "dynamic" in V.norm_text(p.get("value_type")) or "transaction" in V.norm_text(p.get("value_type")):
            required.add("zero")
        if _applicable(p.get("discount_treatment")):
            required.add("discounted")
        if _applicable(p.get("refund_treatment")):
            required.add("refunded")
        seen = {V.norm_text(r.get("scenario")) for r in fresh}
        gap = sorted(required - seen)
        if gap:
            c.partial(f"action {aid}: current-version QA lacks required scenarios {gap}")
    untested = sorted(set(current) - set(qa_by))
    if untested:
        c.partial(f"actions with a current policy but no payload QA: {untested}")
    c.observe("Payload QA rows compared with current policy", compared=compared, tolerance=VALUE_TOLERANCE,
              actions_with_qa=sorted(qa_by), actions_without_qa=untested)


# ---------------------------------------------------------------------------- step 4
_TREAT = ("gross_or_net_basis", "tax_treatment", "shipping_treatment", "discount_treatment", "refund_treatment",
          "currency", "fx_source", "fx_date_rule", "rounding_rule")
_RULE_PAIRS = (("gross_or_net_basis", "value_basis"), ("refund_treatment", "refund_treatment"), ("currency", "currency"))
_OUT4 = {"conflict": {"severity": "Warning", "recommendation": "Align treatments with the documented value policy "
                                                                "through the owner; no automatic correction."},
         "justified": {"severity": "Info", "recommendation": "Record the owner's rationale; gross or net is a business choice."},
         "uncertain": {"severity": None, "recommendation": "Request the owner's treatment definitions."}}


def _step4_treatments(ctx, state) -> None:
    c = ctx.check("treatment_consistency", "Tax, shipping, discount, refund, currency/FX and rounding consistency",
                  {POLICY: ["action_id", "policy_version", *_TREAT, "validity_start", "validity_end"]})
    if not c.runnable:
        return
    current, ambiguous, _, _ = _current_policies(ctx)
    if ambiguous:
        c.partial(f"ambiguous current policies skipped: {sorted(ambiguous)}")
    rules = ctx.table(RULES)
    rule_cols = [r for _, r in _RULE_PAIRS]
    rules_ok = rules is not None and not rules.missing(["action_id"]) and any(x in rules.columns for x in rule_cols)
    if not rules_ok:
        c.partial("cross-source comparison with 071 reconciliation rules not run",
                  [f"{RULES} (file)"] if rules is None else [f"{RULES}:{x}" for x in ["action_id", *rule_cols]
                                                            if x not in rules.columns])
    by_rules: dict[str, list[dict]] = {}
    for r in (rules.rows if rules_ok else []):
        by_rules.setdefault(_s(r.get("action_id")), []).append(r)
    inventory = []
    for aid in sorted(current):
        p = current[aid]
        blank = [k for k in _TREAT if p.get(k) is None and k not in ("fx_source", "fx_date_rule")]
        if blank:
            c.partial(f"action {aid}: treatment unspecified (unknown) for {blank}")
        diffs = []
        for r in by_rules.get(aid, []):
            for pk, rk in _RULE_PAIRS:
                a, b = V.norm_text(p.get(pk)), V.norm_text(r.get(rk))
                if a and b and a != b:
                    diffs.append({"policy_field": pk, "policy": p.get(pk), "rules_field": rk, "rules": r.get(rk),
                                  "business_event_id": r.get("business_event_id")})
        pcur = _up(p.get("currency"))
        fx_gap = bool(pcur and ctx.currency and pcur != ctx.currency and p.get("fx_source") is None)
        treat = {k: p.get(k) for k in _TREAT}
        inventory.append({"action_id": aid, "policy_version": p.get("policy_version"), **treat})
        if diffs or fx_gap:
            c.review("treatment_inconsistency", {"action_id": aid, "policy_version": p.get("policy_version")},
                     "Are this action's value treatments consistent with its documented policy and 071 rules?",
                     evidence={"policy_treatments": treat, "rule_differences": diffs, "account_currency": ctx.currency,
                               "fx_source_missing_for_foreign_currency": fx_gap,
                               "rules_tax_shipping_discount": [r.get("tax_shipping_discount_treatment")
                                                               for r in by_rules.get(aid, [])]},
                     outcomes=_OUT4,
                     guidance="Gross vs net is a business choice; 'conflict' only when the same value is defined "
                              "differently for the same scope without an owner rationale.")
    for cid in sorted({x["campaign_id"] for v in state["mapping"].values() for x in v}):
        acts = sorted(a for a, v in state["mapping"].items() if any(x["campaign_id"] == cid for x in v) and a in current)
        bases = {V.norm_text(current[a].get("gross_or_net_basis")) for a in acts} - {""}
        curs = {_up(current[a].get("currency")) for a in acts} - {None}
        if len(bases) > 1 or len(curs) > 1:
            c.review("mixed_value_basis", {"campaign_id": cid},
                     "Do this campaign's goal actions mix value bases or currencies inconsistently?",
                     evidence={"actions": {a: {k: current[a].get(k) for k in ("policy_version", "gross_or_net_basis",
                                                                               "currency", "fx_source")} for a in acts}},
                     outcomes=_OUT4,
                     guidance="Mixed bases in one bidding goal are a conflict only when the owner intends one comparable value.")
    c.observe("Value treatment inventory (current policies)", policies=inventory,
              rules_actions=sorted(by_rules), account_currency=ctx.currency)


# ---------------------------------------------------------------------------- step 5
def _step5_residuals(ctx, state) -> None:
    c = ctx.check("reconciliation_residuals_071", "Linked 071 signed value residuals over the mature window",
                  {RULES: ["action_id", "maturity_days", "tolerance_value_pct", "currency"],
                   EVENTS: ["event_token", "action_id", "event_timestamp", "expected_value", "currency"],
                   DAILY: ["action_id", "date", "conversion_value", "currency", "reporting_mature"]})
    state["gate_checks"].append(c)
    if not c.runnable:
        return
    snap = ctx.snapshot or ctx.as_of
    if snap is None or ctx.period_start is None or ctx.period_end is None:
        c.partial("snapshot or period unknown: mature window undecidable", ["account:snapshot_date"])
        return
    rules: dict[str, list[dict]] = {}
    for r in ctx.rows(RULES):
        rules.setdefault(_s(r.get("action_id")), []).append(r)
    events: dict[str, list[dict]] = {}
    for r in ctx.rows(EVENTS):
        events.setdefault(_s(r.get("action_id")), []).append(r)
    daily: dict[str, list[dict]] = {}
    for r in ctx.rows(DAILY):
        daily.setdefault(_s(r.get("action_id")), []).append(r)
    ledger: dict[str, list[dict]] = {}
    for r in ctx.rows(LEDGER):
        ledger.setdefault(_s(r.get("action_id")), []).append(r)
    rows_out = []
    for aid in sorted(a for a in rules if a):
        rr = rules[aid]
        mats = {V.integer(r.get("maturity_days")) for r in rr}
        tols = {V.num(r.get("tolerance_value_pct")) for r in rr}
        curs = {_up(r.get("currency")) or ctx.currency for r in rr}
        if len(mats) != 1 or None in mats or len(curs) != 1 or None in curs:
            c.partial(f"action {aid}: maturity_days/currency missing or inconsistent across rules {sorted(map(str, mats))}")
            continue
        mat, cur = mats.pop(), curs.pop()
        tol = tols.pop() if len(tols) == 1 else None
        end = min(ctx.period_end, snap - timedelta(days=mat))
        start = ctx.period_start
        base = {"action_id": aid, "window": [start, end], "maturity_days": mat, "currency": cur}
        if end < start:
            c.partial(f"action {aid}: no mature days (snapshot {snap} − {mat}d precedes period start)")
            rows_out.append({**base, "status": "immature"})
            continue
        problems, ads_total, grains = [], 0.0, set()
        excluded = 0
        for r in daily.get(aid, []):
            d = V.parse_date(r.get("date"))
            if d is None or not (start <= d <= end):
                continue
            if V.boolean(r.get("reporting_mature")) is not True:
                excluded += 1
                continue
            g = (r.get("campaign_id"), d, r.get("date_basis"))
            if g in grains:
                problems.append(f"duplicate Ads grain {g[0]} {d}")
                continue
            grains.add(g)
            v = ctx.money(r.get("conversion_value"))
            if v is None or (_up(r.get("currency")) or cur) != cur:
                problems.append(f"Ads value unknown or other currency on {d}")
                continue
            ads_total += v
        if len({r.get("date_basis") for r in daily.get(aid, [])} - {None}) > 1:
            problems.append("mixed Ads date_basis")
        tokens: dict[str, float] = {}
        stages = {r.get("stage") for r in events.get(aid, [])} - {None}
        if len(stages) > 1:
            problems.append(f"several business-event stages {sorted(stages)}: 071 stage alignment required")
        for r in sorted(events.get(aid, []), key=lambda r: _s(r.get("event_token"))):
            d = V.parse_date(r.get("event_timestamp"))
            if d is None or not (start <= d <= end):
                continue
            tok, v = _s(r.get("event_token")), V.num(r.get("expected_value"))
            if v is None or (_up(r.get("currency")) or cur) != cur:
                problems.append(f"event {tok}: expected value unknown or other currency")
                continue
            if tok in tokens and tokens[tok] != v:
                problems.append(f"event {tok}: conflicting duplicate rows")
            tokens[tok] = v
        if excluded:
            c.partial(f"action {aid}: {excluded} Ads rows in window not reporting_mature (excluded)")
        if problems:
            c.partial(f"action {aid}: not comparable — {sorted(set(problems))[:5]}")
            rows_out.append({**base, "status": "not_comparable", "problems": sorted(set(problems))})
            continue
        expected = sum(tokens.values())
        residual = ads_total - expected
        rel = V.ratio(residual, expected)
        beyond = rel is not None and tol is not None and abs(rel) * 100 > tol
        if tol is None:
            c.partial(f"action {aid}: tolerance_value_pct unknown/inconsistent; residual not compared")
        led = ledger.get(aid, [])
        refs = sorted({_s(r.get("event_token")) for r in led
                       if None not in (V.num(r.get("observed_send_count")), V.num(r.get("expected_send_count")))
                       and V.num(r.get("observed_send_count")) != V.num(r.get("expected_send_count"))} - {""})
        row = {**base, "status": "compared", "ads_value": ads_total, "expected_value": expected,
               "signed_residual": residual, "relative_variance": rel, "tolerance_value_pct": tol,
               "beyond_tolerance": beyond, "events": len(tokens), "ads_rows": len(grains),
               "ledger_send_mismatch_tokens": refs}
        rows_out.append(row)
        if beyond:
            state["residuals"][aid] = {**row, "refs": refs + [ctx.table(EVENTS).filename, ctx.table(DAILY).filename]}
    c.observe("Linked 071 value residuals (Ads − expected; denominator expected value)", actions=rows_out,
              snapshot=snap, note="Classification belongs to skill-071; linked here, not duplicated.")


# ---------------------------------------------------------------------------- step 6
def _step6_calibration(ctx, state) -> None:
    title = "Mature calibration drift for proxy/lead/LTV/profit values"
    policies = state.get("policy")
    if (state.get("policy_ok") and policies and ctx.table(POLICY).complete is True
            and not any(_is_model_type(p.get("value_type")) for p in policies.values())):
        ctx.check("calibration_drift", title, applicable=False,
                  na_reason="no current policy uses a proxy, lead, LTV, profit or predicted value model")
        return
    c = ctx.check("calibration_drift", title,
                  {CALIB: ["action_id", "model_version", "cohort_start", "cohort_end", "stage", "cohort_size",
                           "mature_outcomes", "horizon_days", "observed_vs_predicted_value", "selection_scope",
                           "uncertainty"]})
    if not c.runnable:
        return
    ref = ctx.snapshot or ctx.as_of
    tol = V.num(ctx.profile.get("value_calibration_tolerance"))
    if tol is None or tol <= 0:
        tol = None
        c.partial("owner drift tolerance unknown: drift not classified", ["profile:value_calibration_tolerance"])
    mc = ctx.params.get("min_conversions")
    if mc.value is None:
        c.partial(f"min_conversions unresolved: {mc.reason}")
    ledger, immature, small = [], 0, 0
    rows = sorted(ctx.rows(CALIB), key=lambda r: (_s(r.get("action_id")), _s(r.get("model_version")),
                                                  _s(r.get("cohort_end")), _s(r.get("stage"))))
    for r in rows:
        aid = _s(r.get("action_id"))
        end, h = V.parse_date(r.get("cohort_end")), V.integer(r.get("horizon_days"))
        ratio = V.num(r.get("observed_vs_predicted_value"))
        outcomes = V.num(r.get("mature_outcomes"))
        entity = {"action_id": aid, "model_version": r.get("model_version"), "cohort_start": r.get("cohort_start"),
                  "cohort_end": r.get("cohort_end"), "stage": r.get("stage")}
        mature = None if end is None or h is None or ref is None else end + timedelta(days=h) <= ref
        drift = abs(ratio - 1) if ratio is not None else None
        ledger.append({**entity, "mature": mature, "mature_outcomes": outcomes, "ratio": ratio, "drift": drift})
        if mature is not True:
            immature += 1
            continue
        if mc.value is None or outcomes is None or outcomes < mc.value:
            small += 1
            continue
        if tol is None or drift is None or drift <= tol:
            continue
        c.finding("calibration_drift", "Warning", entity,
                  f"Action {aid} model {r.get('model_version')}: mature cohort observed/predicted {ratio:g} "
                  f"(drift {drift:.3f}) exceeds owner tolerance {tol:g}",
                  evidence={"cohort_size": r.get("cohort_size"), "mature_outcomes": outcomes,
                            "close_rate": r.get("close_rate"), "realized_net_value": r.get("realized_net_value"),
                            "margin_basis": r.get("margin_basis"), "selection_scope": r.get("selection_scope"),
                            "uncertainty": r.get("uncertainty"), "source_reference": r.get("source_reference")},
                  calculation={"drift": "|observed_vs_predicted_value - 1|", "tolerance": tol,
                               "tolerance_source": "profile.value_calibration_tolerance",
                               "maturity": f"cohort_end + {h}d <= {ref}", "sample_gate": f"min_conversions={mc.value}"},
                  recommendation="Ask the model owner to review value calibration for this cohort; no automatic "
                                 "value rescaling.",
                  uncertainty="Aggregate cohort; selection scope and stated uncertainty limit generalization.")
        state["drift"].setdefault(aid, []).append(entity)
    if immature:
        c.partial(f"{immature} cohort row(s) immature or with unknown horizon: not classified")
    if small:
        c.partial(f"{small} mature cohort row(s) below min_conversions on mature_outcomes: not classified")
    if policies:
        uncal = sorted(a for a, p in policies.items() if _is_model_type(p.get("value_type"))
                       and a not in {_s(r.get("action_id")) for r in rows})
        if uncal:
            c.partial(f"model-valued actions without calibration rows: {uncal}")
    c.observe("Calibration cohort ledger", cohorts=ledger, as_of=ref, tolerance=tol, min_conversions=mc.value)


# ---------------------------------------------------------------------------- step 7
def _step7_classify(ctx, state) -> None:
    c = ctx.check("failure_classification", "Separate confirmed value defects from models needing review")
    gates = state["gate_checks"]
    if not any(g.runnable for g in gates):
        c.skip("needs default/payload QA (step 3) or 071 residuals (step 5)", [m for g in gates for m in g.missing])
        return
    for chk in gates:
        if not chk.runnable:
            c.partial(f"{chk.id} skipped: its evidence is not classified", chk.missing)
    actions = sorted(set(state["defects"]) | set(state["residuals"]) | set(state["drift"]))
    summary = []
    for aid in actions:
        defects, residual = state["defects"].get(aid, []), state["residuals"].get(aid)
        summary.append({"action_id": aid, "confirmed_defects": sorted(d["condition"] for d in defects),
                        "residual_beyond_071_tolerance": residual is not None,
                        "model_needs_review": state["drift"].get(aid, [])})
        if not defects and residual is None:
            continue
        refs = sorted({x for d in defects for x in d["refs"]} | set((residual or {}).get("refs", [])))
        c.review("material_value_corruption", {"action_id": aid},
                 "Does independent evidence confirm MATERIAL value corruption or objective failure for this action?",
                 evidence={"confirmed_defects": defects, "linked_071_residual": residual,
                           "calibration_drift": state["drift"].get(aid, []), "evidence_refs": refs},
                 outcomes={"material_value_corruption_confirmed": {"severity": "Critical", "recommendation":
                                                                   "Prioritize a scoped payload/value-policy fix; cite the impact evidence."},
                           "defect_not_material": {"severity": None, "recommendation": "Keep the deterministic Warnings."},
                           "model_needs_review": {"severity": None, "recommendation": "Route to model/calibration owner review."},
                           "uncertain": {"severity": None, "recommendation": "Request 071 reconciliation or impact evidence."}},
                 guidance="Critical needs evidenced material impact (proposal.evidence_ref from evidence_refs); "
                          "a residual alone or settings alone are not proof.")
    c.observe("Value failure classification by action", actions=summary)


# ---------------------------------------------------------------------------- step 8
def _step8_refunds(ctx, state) -> None:
    c = ctx.check("refund_double_deduction", "Coordinate refund treatment with 112 adjustments",
                  {POLICY: ["action_id", "policy_version", "refund_treatment", "validity_start", "validity_end"],
                   ADJ: ["action_id", "adjustment_attempt_id", "adjustment_type", "status"]})
    if not c.runnable:
        return
    current, _, _, _ = _current_policies(ctx)
    adj: dict[str, list[dict]] = {}
    for r in ctx.rows(ADJ):
        adj.setdefault(_s(r.get("action_id")), []).append(r)
    ledger = []
    for aid in sorted(adj):
        rows = [r for r in adj[aid] if any(w in _s(r.get("adjustment_type")).upper() for w in ("RETRACT", "RESTATE"))]
        counts: dict[str, int] = {}
        for r in rows:
            k = f"{_up(r.get('adjustment_type'))}/{_up(r.get('status')) or 'UNKNOWN'}"
            counts[k] = counts.get(k, 0) + 1
        ledger.append({"action_id": aid, "retraction_restatement_counts": counts})
        if not rows:
            continue
        p = current.get(aid)
        if p is None:
            c.partial(f"action {aid}: adjustments present but no single current value policy")
            continue
        if p.get("refund_treatment") is None:
            c.partial(f"action {aid}: refund_treatment unspecified; double deduction undecidable")
            continue
        refs = sorted({_s(r.get("adjustment_attempt_id")) for r in rows} | {_s(r.get("source_reference")) for r in rows}
                      - {""})
        c.review("refund_double_deduction_risk", {"action_id": aid, "policy_version": p.get("policy_version")},
                 "Does the policy already net refunds at import while these retractions/restatements deduct them again?",
                 evidence={"refund_treatment": p.get("refund_treatment"), "gross_or_net_basis": p.get("gross_or_net_basis"),
                           "adjustment_counts": counts, "evidence_refs": refs},
                 outcomes={"double_deduction_confirmed": {"severity": "Critical", "recommendation":
                                                          "Scope a value-policy/adjustment review with 112; cite the reconciliation."},
                           "double_deduction_risk": {"severity": "Warning", "recommendation":
                                                     "Review refund treatment vs adjustment flow with 112; no automatic value reduction."},
                           "consistent_with_policy": {"severity": None, "recommendation": "No action."},
                           "uncertain": {"severity": None, "recommendation": "Request 112 refund ledger reconciliation."}},
                 guidance="Critical needs a reconciliation showing the same refund deducted twice (proposal.evidence_ref).")
    c.observe("Retraction/restatement adjustments by action", actions=ledger)


# ---------------------------------------------------------------------------- entry points
def run(ctx) -> None:
    """Run value-configuration, current-policy, payload QA, 071 link and value-calibration checks per conversion action.

    Rules:   Zero/unit values are never defects; count-based zero/unit is Info only when every goal campaign bids on
             counts. >1 current policy row → partial; stale QA (other version or before validity_start) → partial, never
             a pass. Calibration only when mature and mature_outcomes >= min_conversions and profile tolerance exists.
             Gross/net treatments only raise reviews; Critical only via review with a listed proposal.evidence_ref.
             Never reduce values.
    """
    state = {"mapping": {}, "value_class": {}, "policy": None, "policy_ok": False,
             "defects": {}, "residuals": {}, "drift": {}, "gate_checks": []}
    _step1_value_map(ctx, state)
    _step2_policy(ctx, state)
    _step3_default(ctx, state)
    _step3_payload(ctx, state)
    _step4_treatments(ctx, state)
    _step5_residuals(ctx, state)
    _step6_calibration(ctx, state)
    _step7_classify(ctx, state)
    _step8_refunds(ctx, state)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes require proposal.evidence_ref naming a ref present in item evidence_refs."""
    if decision.get("outcome") not in CRITICAL_OUTCOMES:
        return []
    ref = _s((decision.get("proposal") or {}).get("evidence_ref"))
    if not ref:
        return ["Critical outcome needs proposal.evidence_ref pointing at supplied evidence"]
    allowed = set((item.evidence or {}).get("evidence_refs") or [])
    if ref not in allowed:
        return [f"evidence_ref {ref!r} not among supplied evidence refs {sorted(allowed)}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
