"""check.py — skill-112 deterministic refund / conversion-adjustment reconciliation against the value policy.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-112-return-refund-tracking/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-107-conversion-value-accuracy/SKILL.md — owns external/conversion_value_policy.csv columns
         skills/skill-071-conversion-tracking-accuracy/SKILL.md — owns residual findings; step 8 here only observes
rules:   Policy tokens (normalized lowercase, spaces/hyphens → '_'): gross_or_net_basis 'gross*' → gross,
         'net*'|'profit*' → net (refunds deducted); refund_treatment ∈ netted_at_import | modeled_upstream |
         adjusted_afterward(s) | not_deducted. Anything else is unknown → partial, never guessed.
         Gross policy is intentional: Info only, refunds are never deducted for gross actions.
         Refund status: pending | canceled/cancelled | partial | full; only partial/full are realized refunds.
         Duplicate refund_token rows are counted once when identical; conflicting duplicates exclude the order.
         Double deduction: policy gross, or net with netted_at_import/modeled_upstream, plus an ACCEPTED downward
         adjustment (retraction, or restated < prior) on an order with realized refunds → Warning; in flight → Info.
         Step 6 Warning: negative restated total; retraction while mature E > 0; restated == prior − E (delta) ≠ E.
         Adjustment status: accepted|processed|applied|success → accepted; rejected|failed|error → rejected;
         submitted|pending|queued|in_progress|processing → in flight. Submitted ≠ accepted.
         Refund maturity horizon: external/reconciliation_rules.csv:maturity_days for the action (071), else
         profile.refund_maturity_days (int days). Order mature iff purchase_date + horizon <= account snapshot and
         no pending refund. Unresolved horizon → partial, no maturity claims. No industry return rates.
         Expected remaining value E = ledger expected_remaining_value (latest realized refund row); an order
         without refunds keeps E = original_value. Money equality tolerance 0.01 (rounding only, not materiality).
         'No return imports alone' (no attempts at all) is Info and needs a complete adjustments manifest.
         Repeated failure rule: an action with >= 2 unresolved rejected attempts (no accepted attempt for the
         same order) whose type and match method are evidenced as supported → Warning; support unknown → Info.
         Critical (material double deduction / incorrect adjustment / net-value corruption) only via ai_review;
         verify() requires proposal.evidence_ref naming a ref listed in the item's evidence.refs.
         ROAS difference (step 8) = residual / attributable spend only with ctx.mature True, all in-period
         orders decidable, >= min_conversions orders, single-action campaigns in custom/ads_reconciliation_daily
         and nonzero cost; descriptive observation only (findings belong to 071).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
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

SKILL = "skill-112-return-refund-tracking"
VERSION = "1.0.0"

POLICY = "external/conversion_value_policy"
LEDGER = "external/refund_ledger"
ADJ = "external/conversion_adjustments"
SUPPORT = "external/adjustment_support"
RULES = "external/reconciliation_rules"
DAILY = "custom/ads_reconciliation_daily"

POLICY_NEEDS = {POLICY: ["action_id", "gross_or_net_basis", "refund_treatment"]}
TOL = 0.01
CRITICAL_OUTCOME = "material_confirmed"

_TREATMENTS = {"netted_at_import": "netted_at_import", "modeled_upstream": "modeled_upstream",
               "modelled_upstream": "modeled_upstream", "adjusted_afterward": "adjusted_afterward",
               "adjusted_afterwards": "adjusted_afterward", "not_deducted": "not_deducted"}
_REFUND = {"pending": "pending", "canceled": "canceled", "cancelled": "canceled", "partial": "partial",
           "full": "full"}
_ADJ_STATUS = {**{k: "accepted" for k in ("accepted", "processed", "applied", "success", "succeeded")},
               **{k: "rejected" for k in ("rejected", "failed", "failure", "error")},
               **{k: "in_flight" for k in ("submitted", "pending", "queued", "in_progress", "processing")}}
_ADJ_TYPE = {"retraction": "retraction", "retract": "retraction", "restatement": "restatement", "restate": "restatement"}


def _s(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _tok(v) -> str:
    return V.norm_text(v).replace(" ", "_").replace("-", "_")


def _basis(v) -> str | None:
    t = _tok(v)
    if t == "gross" or t.startswith("gross_"):
        return "gross"
    if t in ("net", "profit") or t.startswith(("net_", "profit_")):
        return "net"
    return None


def _cur(v) -> str | None:
    s = _s(v)
    return s.upper() if s else None


class _State:
    def __init__(self):
        self.policy: dict | None = None          # action_id -> policy dict
        self.policy_missing: list[str] = []
        self.orders: dict | None = None          # (aid, order) -> order dict
        self.ledger_missing: list[str] = []
        self.expected: dict | None = None        # (aid, order) -> {"E", "original", "state", "purchase"}
        self.attempts: list[dict] | None = None
        self.support: dict | None = None
        self.views: dict | None = None           # (aid, order) -> reported value after accepted adjustments
        self.flagged: dict[tuple, set] = {}      # (aid, order) -> {check ids}
        self.blocked: dict[tuple, str] = {}      # (aid, order) -> reason
        self.attempt_conflicts: list[str] = []


def run(ctx) -> None:
    """Run value policy, refund, expected value, double deduction, adjustment, failure, ROAS and proposal checks.

    Rules:   Unknown policy tokens or unresolved refund maturity horizon → partial, never guessed; gross policy is Info
             only. Deterministic Warnings: accepted downward adjustment on pre-netted orders with realized refunds,
             step-6 restatement errors, >= 2 unresolved rejected attempts on evidenced-supported types. In-flight
             adjustments and 'no return imports' (complete manifest) are Info; Critical only via ai_review; residual
             ROAS is descriptive.
    """
    st = _State()
    _value_policy(ctx, st)
    _refund_dedupe(ctx, st)
    _expected_remaining(ctx, st)
    _load_attempts(ctx, st)
    _double_deduction(ctx, st)
    _accepted_vs_expected(ctx, st)
    _adjustment_support(ctx, st)
    _retraction_restatement(ctx, st)
    _adjustment_failures(ctx, st)
    _residual_roas(ctx, st)
    _reconciliation_proposals(ctx, st)


# ---------------------------------------------------------------------------------------------- step 1
def _load_policy(ctx) -> tuple[dict, list[str], list[str]]:
    by: dict[str, list[dict]] = {}
    for r in ctx.rows(POLICY):
        aid = _s(r.get("action_id"))
        if not aid:
            continue
        start, end = V.parse_date(r.get("validity_start")), V.parse_date(r.get("validity_end"))
        if ctx.period_end and start and start > ctx.period_end:
            continue
        if ctx.period_start and end and end < ctx.period_start:
            continue
        by.setdefault(aid, []).append(r)
    out, ambiguous, unknown = {}, [], []
    for aid in sorted(by):
        variants = {(_basis(r.get("gross_or_net_basis")), _TREATMENTS.get(_tok(r.get("refund_treatment"))))
                    for r in by[aid]}
        if len(variants) > 1:
            ambiguous.append(aid)
            continue
        basis, treat = next(iter(variants))
        if basis is None or (basis == "net" and treat is None):
            unknown.append(aid)
            continue
        r = sorted(by[aid], key=lambda x: str(x.get("policy_version") or ""))[-1]
        out[aid] = {"action_id": aid, "basis": basis, "treatment": treat if basis == "net" else None,
                    "policy_version": r.get("policy_version"), "currency": _cur(r.get("currency")),
                    "tax_treatment": r.get("tax_treatment"), "shipping_treatment": r.get("shipping_treatment"),
                    "owner": r.get("owner"), "raw_basis": r.get("gross_or_net_basis"),
                    "raw_refund_treatment": r.get("refund_treatment")}
    return out, ambiguous, unknown


def _value_policy(ctx, st: _State) -> None:
    chk = ctx.check("value_policy", "Intended gross/net policy and refund treatment per action", POLICY_NEEDS)
    if not chk.runnable:
        st.policy_missing = list(chk.missing)
        return
    st.policy, ambiguous, unknown = _load_policy(ctx)
    if ambiguous:
        chk.partial(f"conflicting policy versions valid in the period for actions {ambiguous}; excluded")
    if unknown:
        chk.partial(f"unrecognized gross_or_net_basis/refund_treatment for actions {unknown}; owner mapping needed")
    known_actions = {str(r.get("id")) for r in ctx.rows("conversion_actions") if r.get("id") is not None}
    for aid, p in sorted(st.policy.items()):
        entity = {"account_id": ctx.account_id, "action_id": aid}
        ev = {k: p[k] for k in ("policy_version", "raw_basis", "raw_refund_treatment", "currency", "owner")}
        if p["basis"] == "gross":
            chk.finding("gross_policy", "Info", entity,
                        f"Action {aid}: value policy is gross; refunds are intentionally not deducted",
                        evidence=ev, recommendation="Preserve gross reporting; do not reduce values for refunds.",
                        uncertainty="Gross versus net is a business choice, not a defect.")
        elif p["treatment"] == "not_deducted":
            chk.review("net_policy_without_deduction", entity,
                       f"Action {aid}: policy basis is net/profit but refund_treatment says refunds are not "
                       "deducted. Does the owner need a business review of the gross/net or refund-modeling choice?",
                       evidence=ev, outcomes={
                           "business_review_needed": {"severity": "Info", "recommendation":
                                                      "Ask the value-policy owner to confirm the refund treatment."},
                           "consistent_by_design": {"severity": None, "recommendation": "No action."},
                           "uncertain": {"severity": "Info", "recommendation": "Request the owner's policy rationale."}},
                       guidance="Judge only from the policy row and profile objectives; never infer a return rate.")
        if ctx.currency and p["currency"] and p["currency"] != ctx.currency:
            chk.observe(f"Action {aid}: policy currency differs from account currency", action_id=aid,
                        policy_currency=p["currency"], account_currency=ctx.currency)
    chk.observe("Value policy inventory", actions=len(st.policy),
                gross=sorted(a for a, p in st.policy.items() if p["basis"] == "gross"),
                net_by_treatment={t: sorted(a for a, p in st.policy.items() if p["treatment"] == t)
                                  for t in sorted({p["treatment"] for p in st.policy.values() if p["treatment"]})},
                not_in_conversion_actions=sorted(set(st.policy) - known_actions) if known_actions else None)


# ---------------------------------------------------------------------------------------------- step 2
def _refund_dedupe(ctx, st: _State) -> None:
    chk = ctx.check("refund_dedupe", "Deduplicate refunds, statuses and currency alignment",
                    {LEDGER: ["action_id", "order_token", "refund_token", "refund_status", "refunded_value", "currency"]})
    if not chk.runnable:
        st.ledger_missing = list(chk.missing)
        return
    orders: dict[tuple, dict] = {}
    groups: dict[tuple, list[dict]] = {}
    for r in ctx.rows(LEDGER):
        aid, order = _s(r.get("action_id")), _s(r.get("order_token"))
        if not aid or not order:
            continue
        o = orders.setdefault((aid, order), {"rows": [], "counted": [], "pending": 0, "canceled": 0,
                                             "excluded": None, "currencies": set(), "originals": set()})
        o["rows"].append(r)
        cur = _cur(r.get("currency"))
        if cur:
            o["currencies"].add(cur)
        ov = ctx.money(r.get("original_value"))
        if ov is not None:
            o["originals"].add(round(ov, 2))
        token = _s(r.get("refund_token"))
        if token:
            groups.setdefault((aid, token), []).append(r)
        elif _REFUND.get(_tok(r.get("refund_status"))) in ("partial", "full"):
            o["excluded"] = o["excluded"] or "realized refund row without refund_token"
    dup_rows, conflicts = 0, []
    status_counts: dict[str, dict[str, int]] = {}
    for (aid, token), rows in sorted(groups.items()):
        sigs = {(_s(r.get("order_token")), _REFUND.get(_tok(r.get("refund_status"))),
                 ctx.money(r.get("refunded_value")), _cur(r.get("currency"))) for r in rows}
        orders_hit = sorted({_s(r.get("order_token")) for r in rows})
        if len(sigs) > 1:
            conflicts.append(f"{aid}/{token}")
            for ot in orders_hit:
                orders[(aid, ot)]["excluded"] = "conflicting duplicate refund_token rows"
            continue
        dup_rows += len(rows) - 1
        r = rows[0]
        o = orders[(aid, orders_hit[0])]
        status = _REFUND.get(_tok(r.get("refund_status")))
        sc = status_counts.setdefault(aid, {})
        sc[status or "unknown"] = sc.get(status or "unknown", 0) + 1
        if status is None:
            o["excluded"] = o["excluded"] or f"unrecognized refund_status '{r.get('refund_status')}'"
        elif status == "pending":
            o["pending"] += 1
        elif status == "canceled":
            o["canceled"] += 1
        else:
            val = ctx.money(r.get("refunded_value"))
            if val is None:
                o["excluded"] = o["excluded"] or "realized refund without refunded_value"
            else:
                o["counted"].append({"token": token, "value": val, "status": status, "row": r,
                                     "ts": str(r.get("refund_timestamp") or "")})
    currency_mismatch, over_refund, tax = [], [], {"tax_refund": 0.0, "shipping_refund": 0.0}
    for key in sorted(orders):
        o = orders[key]
        aid = key[0]
        pol_cur = (st.policy or {}).get(aid, {}).get("currency")
        bad = sorted(c for c in o["currencies"] if (ctx.currency and c != ctx.currency) or (pol_cur and c != pol_cur))
        if bad or len(o["currencies"]) > 1:
            currency_mismatch.append({"action_id": aid, "order_token": key[1], "currencies": sorted(o["currencies"]),
                                      "account_currency": ctx.currency, "policy_currency": pol_cur})
            o["excluded"] = o["excluded"] or "currency not aligned with account/policy"
        if len(o["originals"]) > 1:
            o["excluded"] = o["excluded"] or "inconsistent original_value across rows"
        o["original"] = next(iter(o["originals"])) if len(o["originals"]) == 1 else None
        refunded = sum(c["value"] for c in o["counted"])
        o["refunded"] = refunded
        if o["original"] is not None and refunded > o["original"] + TOL:
            over_refund.append({"action_id": aid, "order_token": key[1], "refunded": refunded,
                                "original_value": o["original"]})
            o["excluded"] = o["excluded"] or "realized refunds exceed original_value"
        for col in tax:
            for c in o["counted"]:
                v = ctx.money(c["row"].get(col))
                if v is not None:
                    tax[col] += v
    if conflicts:
        chk.partial(f"conflicting duplicate refund_token rows excluded: {conflicts}")
    if currency_mismatch:
        chk.partial(f"{len(currency_mismatch)} orders excluded for currency misalignment (no FX assumed)")
    if over_refund:
        chk.partial(f"{len(over_refund)} orders excluded: realized refunds exceed original_value")
    excluded = sorted(f"{k[0]}/{k[1]}: {o['excluded']}" for k, o in orders.items() if o["excluded"])
    chk.observe("Refund ledger deduplicated", orders=len(orders), refund_tokens=len(groups),
                duplicate_rows_collapsed=dup_rows, status_counts_by_action=status_counts,
                repeated_refund_orders=sorted(f"{k[0]}/{k[1]}" for k, o in orders.items() if len(o["counted"]) > 1),
                currency_mismatch=currency_mismatch, over_refund=over_refund, excluded_orders=excluded,
                realized_tax_refund=tax["tax_refund"], realized_shipping_refund=tax["shipping_refund"],
                policy_tax_shipping={a: [p.get("tax_treatment"), p.get("shipping_treatment")]
                                     for a, p in sorted((st.policy or {}).items())})
    st.orders = orders


# ---------------------------------------------------------------------------------------------- step 1b
def _double_deduction(ctx, st: _State) -> None:
    """Step 1 (second half): refunds already deducted by policy must not be deducted again by adjustments."""
    chk = ctx.check("double_deduction", "Refunds deducted twice (policy netting plus adjustments)",
                    {**POLICY_NEEDS,
                     LEDGER: ["action_id", "order_token", "refund_token", "refund_status", "refunded_value", "currency"],
                     ADJ: ["action_id", "order_token", "adjustment_attempt_id", "adjustment_type", "status",
                           "prior_reported_value", "restated_total_value"]})
    if not chk.runnable:
        return
    if st.policy is None or st.orders is None or st.attempts is None:
        chk.skip("prerequisite checks not runnable", st.policy_missing + st.ledger_missing)
        return
    refunded = {k for k, o in st.orders.items() if o["counted"] and not o["excluded"]}
    per: dict[str, dict] = {}
    undecidable = 0
    for a in st.attempts:
        key = (a["aid"], a["order"])
        p = st.policy.get(a["aid"])
        if key not in refunded or p is None or a["status"] == "rejected":
            continue
        if p["basis"] == "gross":
            kind = "gross_policy_refund_adjustment"
        elif p["treatment"] in ("netted_at_import", "modeled_upstream"):
            kind = "double_deduction_candidate"
        else:
            continue
        if a["type"] == "retraction":
            down = True
        elif a["type"] == "restatement" and a["restated"] is not None and a["prior"] is not None:
            down = a["restated"] < a["prior"] - TOL
        else:
            undecidable += a["type"] == "restatement"
            continue
        if not down:
            continue
        d = per.setdefault(a["aid"], {"kind": kind, "accepted": [], "in_flight": [], "refs": set()})
        d["accepted" if a["status"] == "accepted" else "in_flight"].append(
            {"order_token": a["order"], "attempt": a["id"], "type": a["type"], "status": a["status"],
             "prior_reported_value": a["prior"], "restated_total_value": a["restated"],
             "realized_refunds": st.orders[key]["refunded"]})
        d["refs"] |= {a["id"], a["order"]} | ({a["source"]} if a["source"] else set())
        d["refs"] |= {c["token"] for c in st.orders[key]["counted"]}
    if undecidable:
        chk.partial(f"{undecidable} restatement attempts lack prior/restated values; direction undecidable")
    for aid, d in sorted(per.items()):
        p = st.policy[aid]
        entity = {"account_id": ctx.account_id, "action_id": aid}
        ev = {"policy_basis": p["raw_basis"], "refund_treatment": p["raw_refund_treatment"],
              "policy_version": p["policy_version"], "accepted": d["accepted"], "in_flight": d["in_flight"],
              "refs": sorted(d["refs"])}
        if d["accepted"]:
            for x in d["accepted"]:
                st.flagged.setdefault((aid, x["order_token"]), set()).add("double_deduction")
            what = ("gross policy intends no refund deduction" if d["kind"] == "gross_policy_refund_adjustment"
                    else f"policy already deducts refunds ({p['treatment']})")
            chk.finding(d["kind"], "Warning", entity,
                        f"Action {aid}: {len(d['accepted'])} accepted downward adjustments on refunded orders "
                        f"although {what}", evidence=ev,
                        calculation={"accepted_downward_adjustments": len(d["accepted"]),
                                     "in_flight_downward_adjustments": len(d["in_flight"])},
                        recommendation="Owner-reviewed reconciliation of the refund path; do not submit further "
                                       "adjustments until the policy owner confirms one deduction route.",
                        uncertainty="Import-time netting is taken from the policy, not from observed import payloads.")
            chk.review(d["kind"], entity,
                       f"Does reconciliation evidence confirm MATERIAL double deduction/incorrect adjustment "
                       f"for action {aid}?", evidence=ev,
                       outcomes={CRITICAL_OUTCOME: {"severity": "Critical", "recommendation":
                                                    "Prioritize owner reconciliation; cite the reconciliation ref."},
                                 "not_material": {"severity": None, "recommendation": "Keep the Warning."},
                                 "uncertain": {"severity": None, "recommendation": "Keep the Warning; request 071 residuals."}},
                       guidance=f"{CRITICAL_OUTCOME} needs proposal.evidence_ref equal to one of evidence.refs "
                                "and supplied evidence of material value impact (e.g. 071 residual).")
        else:
            chk.finding(d["kind"] + "_pending", "Info", entity,
                        f"Action {aid}: {len(d['in_flight'])} submitted (not yet accepted) downward adjustments on "
                        "refunded orders conflict with the refund policy", evidence=ev,
                        recommendation="Business-backed review of the refund-deduction route before acceptance.",
                        uncertainty="Submitted adjustments may still be rejected or not reflected in reporting.")
    chk.observe("Downward adjustments on refunded orders by policy", actions_flagged=sorted(per),
                refunded_orders=len(refunded))


# ---------------------------------------------------------------------------------------------- step 3
def _horizon(ctx, aid: str) -> tuple[int | None, str]:
    t = ctx.table(RULES)
    if t is not None and not t.missing(["action_id", "maturity_days"]):
        vals = {V.integer(r.get("maturity_days")) for r in t.rows if _s(r.get("action_id")) == aid}
        vals.discard(None)
        if len(vals) == 1:
            return vals.pop(), f"{RULES}.csv:maturity_days"
        if len(vals) > 1:
            return None, f"{RULES}.csv: conflicting maturity_days for action {aid}"
    v = V.integer(ctx.profile.get("refund_maturity_days"))
    if v is not None and v >= 0:
        return v, "profile.refund_maturity_days"
    return None, "refund maturity horizon undeclared (reconciliation_rules maturity_days / profile.refund_maturity_days)"


def _expected_value(ctx, o: dict) -> tuple[float | None, str]:
    counted = o["counted"]
    if not counted:
        vals = {round(v, 2) for v in (ctx.money(r.get("expected_remaining_value")) for r in o["rows"]) if v is not None}
        if len(vals) == 1:
            return vals.pop(), "ledger"
        if len(vals) > 1:
            return None, "conflicting expected_remaining_value"
        return (o["original"], "original (no realized refund)") if o["original"] is not None else (None, "no original_value")
    if all(c["ts"] for c in counted):
        last_ts = max(c["ts"] for c in counted)
        rows = [c["row"] for c in counted if c["ts"] == last_ts]
    else:
        rows = [c["row"] for c in counted]
    vals = {round(v, 2) for v in (ctx.money(r.get("expected_remaining_value")) for r in rows) if v is not None}
    if len(vals) == 1:
        return vals.pop(), "ledger (latest realized refund)"
    return None, "expected_remaining_value missing or ambiguous for latest refund"


def _expected_remaining(ctx, st: _State) -> None:
    chk = ctx.check("expected_remaining_value", "Expected remaining value from policy and mature ledger",
                    {**POLICY_NEEDS, LEDGER: ["action_id", "order_token", "purchase_timestamp", "refund_timestamp",
                                              "original_value", "expected_remaining_value"]})
    if not chk.runnable:
        return
    if st.policy is None or st.orders is None:
        chk.skip("prerequisite checks value_policy/refund_dedupe not runnable", st.policy_missing + st.ledger_missing)
        return
    expected: dict[tuple, dict] = {}
    per: dict[str, dict] = {}
    horizons: dict[str, tuple] = {}
    for key in sorted(st.orders):
        aid, order = key
        o = st.orders[key]
        p = st.policy.get(aid)
        a = per.setdefault(aid, {"mature": 0, "immature": [], "unknown": 0, "excluded": 0, "original": 0.0,
                                 "expected": 0.0, "refunded": 0.0, "no_policy": 0, "gross": 0,
                                 "treatment_differences": []})
        if p is None:
            a["no_policy"] += 1
            continue
        if p["basis"] == "gross":
            a["gross"] += 1
            continue
        if o["excluded"]:
            a["excluded"] += 1
            continue
        if aid not in horizons:
            horizons[aid] = _horizon(ctx, aid)
        horizon, hsrc = horizons[aid]
        purchase = V.parse_date(o["rows"][0].get("purchase_timestamp"))
        E, esrc = _expected_value(ctx, o)
        rec = {"E": E, "E_source": esrc, "original": o["original"], "purchase": purchase, "horizon": horizon}
        if horizon is None or purchase is None or ctx.snapshot is None:
            rec["state"] = "unknown"
            a["unknown"] += 1
        elif o["pending"] or (ctx.snapshot - purchase).days < horizon:
            rec["state"] = "immature"
            a["immature"].append(order)
        elif E is None:
            rec["state"] = "unknown"
            a["unknown"] += 1
        else:
            rec["state"] = "mature"
            a["mature"] += 1
            a["original"] += o["original"] or 0.0
            a["expected"] += E
            a["refunded"] += o["refunded"]
            if o["original"] is not None and abs(o["original"] - o["refunded"] - E) > TOL:
                a["treatment_differences"].append({"order_token": order, "original": o["original"],
                                                   "realized_refunds": o["refunded"], "expected_remaining": E})
        expected[key] = rec
    unresolved = sorted({h[1] for h in horizons.values() if h[0] is None})
    for u in unresolved:
        chk.partial(u)
    for aid, a in sorted(per.items()):
        if a["unknown"]:
            chk.partial(f"action {aid}: {a['unknown']} orders with unknown maturity or expected value")
        if a["no_policy"]:
            chk.partial(f"action {aid}: no usable value policy; {a['no_policy']} orders not valued")
        h = horizons.get(aid, (None, ""))
        if a["immature"]:
            chk.finding("immature_refunds", "Info", {"account_id": ctx.account_id, "action_id": aid},
                        f"Action {aid}: {len(a['immature'])} orders have immature refund cohorts or pending refunds",
                        evidence={"orders": a["immature"], "horizon_days": h[0], "horizon_source": h[1],
                                  "snapshot": ctx.snapshot},
                        recommendation="Report with uncertainty; no final ROAS claim until the cohort matures.",
                        uncertainty="Later refunds can still change the remaining value.")
        chk.observe(f"Action {aid}: expected remaining value on mature orders", action_id=aid,
                    mature_orders=a["mature"], immature_orders=len(a["immature"]), unknown_orders=a["unknown"],
                    excluded_orders=a["excluded"], gross_orders_preserved=a["gross"],
                    original_value=a["original"], realized_refunds=a["refunded"], expected_remaining_value=a["expected"],
                    horizon_days=h[0], horizon_source=h[1],
                    tax_shipping_fee_differences=a["treatment_differences"])
    st.expected = expected


# ---------------------------------------------------------------------------------------------- adjustments
def _load_attempts(ctx, st: _State) -> None:
    t = ctx.table(ADJ)
    base = ["action_id", "order_token", "adjustment_attempt_id", "adjustment_type", "status"]
    if t is None or t.missing(base):
        return
    by: dict[tuple, list[dict]] = {}
    for r in t.rows:
        aid, att = _s(r.get("action_id")), _s(r.get("adjustment_attempt_id"))
        if aid and att:
            by.setdefault((aid, att), []).append(r)
    attempts = []
    for (aid, att), rows in sorted(by.items()):
        if len({tuple(sorted((k, str(v)) for k, v in r.items())) for r in rows}) > 1:
            st.attempt_conflicts.append(f"{aid}/{att}")
            continue
        r = rows[0]
        attempts.append({
            "aid": aid, "id": att, "order": _s(r.get("order_token")), "row": r,
            "type": _ADJ_TYPE.get(_tok(r.get("adjustment_type")), _tok(r.get("adjustment_type")) or None),
            "status": _ADJ_STATUS.get(_tok(r.get("status")), "unknown"),
            "restated": ctx.money(r.get("restated_total_value")), "prior": ctx.money(r.get("prior_reported_value")),
            "retry_of": _s(r.get("retry_of_attempt_id")), "currency": _cur(r.get("currency")),
            "rejection_code": _s(r.get("rejection_code")), "method": _s(r.get("original_record_match_method")),
            "identifier": V.boolean(r.get("supported_identifier_present")), "source": _s(r.get("source_reference")),
            "sort": (str(r.get("submitted_at") or r.get("adjustment_timestamp") or ""),
                     str(r.get("processed_at") or ""), att)})
    st.attempts = attempts


def _adj_complete(ctx) -> bool:
    t = ctx.table(ADJ)
    return bool(t is not None and t.complete is True and not t.truncated)


# ---------------------------------------------------------------------------------------------- step 4
def _accepted_vs_expected(ctx, st: _State) -> None:
    chk = ctx.check("accepted_vs_expected", "Accepted adjustments versus expected remaining value",
                    {**POLICY_NEEDS,
                     ADJ: ["action_id", "order_token", "adjustment_attempt_id", "adjustment_type", "status",
                           "restated_total_value"],
                     LEDGER: ["action_id", "order_token", "original_value", "expected_remaining_value"]})
    if not chk.runnable:
        return
    if st.expected is None or st.attempts is None:
        chk.skip("prerequisite expected_remaining_value not runnable", st.policy_missing + st.ledger_missing)
        return
    complete = _adj_complete(ctx)
    if not complete:
        chk.partial(f"{ADJ}.csv not attested complete: orders without attempts are unknown, not 'no import'")
    by_order: dict[tuple, list[dict]] = {}
    for a in st.attempts:
        by_order.setdefault((a["aid"], a["order"]), []).append(a)
    views: dict[tuple, float | None] = {}
    per: dict[str, dict] = {}
    not_comparable: set[str] = set()
    for key in sorted(st.expected):
        rec = st.expected[key]
        aid, order = key
        p = st.policy.get(aid)
        if p is None or p["basis"] != "net":
            continue
        if p["treatment"] != "adjusted_afterward":
            not_comparable.add(aid)
            continue
        a = per.setdefault(aid, {"mismatch": [], "no_import": [], "pending": [], "rejected_only": [], "matched": 0,
                                 "unknown": [], "currency": [], "refs": set(), "E": 0.0, "view": 0.0})
        if rec["state"] != "mature":
            continue
        E = rec["E"]
        atts = [x for x in by_order.get(key, []) if x["type"] in ("retraction", "restatement")]
        accepted = sorted((x for x in atts if x["status"] == "accepted"), key=lambda x: x["sort"])
        view = None
        if accepted:
            last = accepted[-1]
            ledger_cur = next(iter(st.orders[key]["currencies"]), None)
            if last["currency"] and ledger_cur and last["currency"] != ledger_cur:
                a["currency"].append(order)
                continue
            view = 0.0 if last["type"] == "retraction" else last["restated"]
            if view is None:
                a["unknown"].append(order)
                continue
            if abs(view - E) > TOL:
                a["mismatch"].append({"order_token": order, "expected_remaining": E, "accepted_value": view,
                                      "difference": view - E, "attempt": last["id"], "type": last["type"]})
                a["refs"] |= {order, last["id"]} | ({last["source"]} if last["source"] else set())
                st.flagged.setdefault(key, set()).add("accepted_vs_expected")
            else:
                a["matched"] += 1
        elif any(x["status"] == "in_flight" for x in atts):
            a["pending"].append(order)
            continue
        elif atts:
            a["rejected_only"].append(order)
            view = rec["original"]
        elif not complete:
            a["unknown"].append(order)
            continue
        else:
            view = rec["original"]
            if view is not None and abs(view - E) > TOL:
                a["no_import"].append({"order_token": order, "original": view, "expected_remaining": E})
            else:
                a["matched"] += 1
        if view is not None:
            views[key] = view
            a["E"] += E
            a["view"] += view
    for aid in sorted(not_comparable):
        chk.partial(f"action {aid}: refund_treatment '{st.policy[aid]['treatment']}' — import values not in "
                    "evidence; compared only in double_deduction")
    for aid, a in sorted(per.items()):
        entity = {"account_id": ctx.account_id, "action_id": aid}
        if a["unknown"] or a["currency"]:
            chk.partial(f"action {aid}: {len(a['unknown'])} orders undecidable, {len(a['currency'])} currency-misaligned")
        if a["mismatch"]:
            ev = {"orders": a["mismatch"], "tolerance": TOL, "refs": sorted(a["refs"]),
                  "policy_version": st.policy[aid]["policy_version"]}
            chk.finding("accepted_value_mismatch", "Warning", entity,
                        f"Action {aid}: {len(a['mismatch'])} mature orders' accepted adjusted value differs from the "
                        "expected remaining value", evidence=ev,
                        calculation={"sum_expected_remaining": sum(x["expected_remaining"] for x in a["mismatch"]),
                                     "sum_accepted_value": sum(x["accepted_value"] for x in a["mismatch"])},
                        recommendation="Owner-reviewed reconciliation of the listed orders; propose supported "
                                       "restatements only after checking failures and already-adjusted events.",
                        uncertainty="Expected remaining value comes from the supplied ledger and policy.")
            chk.review("accepted_value_mismatch", entity,
                       f"Does reconciliation confirm MATERIAL incorrect adjustment or net-value corruption for {aid}?",
                       evidence=ev,
                       outcomes={CRITICAL_OUTCOME: {"severity": "Critical", "recommendation":
                                                    "Prioritize the reconciliation; cite the confirming ref."},
                                 "not_material": {"severity": None, "recommendation": "Keep the Warning."},
                                 "uncertain": {"severity": None, "recommendation": "Keep the Warning."}},
                       guidance=f"{CRITICAL_OUTCOME} needs proposal.evidence_ref equal to one of evidence.refs and "
                                "evidenced material impact.")
        if a["no_import"]:
            chk.finding("no_return_imports", "Info", entity,
                        f"Action {aid}: {len(a['no_import'])} mature refunded orders have no adjustment attempt",
                        evidence={"orders": a["no_import"]},
                        recommendation="Owner review whether refunds should be imported under the policy.",
                        uncertainty="Absence of return imports alone is not a confirmed defect.")
        chk.observe(f"Action {aid}: accepted versus expected remaining value", action_id=aid, matched=a["matched"],
                    mismatched=len(a["mismatch"]), no_import=len(a["no_import"]), pending_orders=a["pending"],
                    rejected_only_orders=a["rejected_only"], expected_remaining_value=a["E"],
                    reported_value_after_accepted=a["view"], residual=a["view"] - a["E"])
    st.views = views


# ---------------------------------------------------------------------------------------------- step 5
def _adjustment_support(ctx, st: _State) -> None:
    chk = ctx.check("adjustment_support", "Action/source adjustment support and match method",
                    {SUPPORT: ["action_id", "supports_restatement", "supports_retraction", "accepted_match_method"]})
    if not chk.runnable:
        return
    rows: dict[str, list[dict]] = {}
    for r in ctx.rows(SUPPORT):
        aid = _s(r.get("action_id"))
        if aid:
            rows.setdefault(aid, []).append(r)
    support = {}
    for aid, rs in sorted(rows.items()):
        s = {}
        for typ in ("restatement", "retraction"):
            vals = [V.boolean(r.get(f"supports_{typ}")) for r in rs]
            s[typ] = True if True in vals else False if vals and all(v is False for v in vals) else None
        s["methods"] = sorted({_tok(m) for r in rs for m in V.split_list(r.get("accepted_match_method"), (";", "|", ","))})
        s["eligibility"] = sorted({str(r.get("eligibility_status")) for r in rs if r.get("eligibility_status")})
        s["time_limit_reference"] = sorted({str(r.get("time_limit_reference")) for r in rs if r.get("time_limit_reference")})
        s["refs"] = sorted({str(r.get("source_reference")) for r in rs if r.get("source_reference")})
        support[aid] = s
    st.support = support
    scope = {a["aid"] for a in (st.attempts or [])} | {a for a, p in (st.policy or {}).items()
                                                        if p["treatment"] == "adjusted_afterward"}
    if st.attempts is None:
        chk.partial(f"{ADJ}.csv unavailable: method use per attempt not evaluated")
    unsupported: dict[str, list[dict]] = {}
    no_identifier: dict[str, list[str]] = {}
    for aid in sorted(scope):
        s = support.get(aid)
        entity = {"account_id": ctx.account_id, "action_id": aid}
        if s is None or s["restatement"] is None or s["retraction"] is None or not s["methods"]:
            chk.finding("unknown_adjustment_support", "Info", entity,
                        f"Action {aid}: adjustment support is not fully documented",
                        evidence={"support": s}, recommendation="Document supported adjustment types and match "
                                                                "methods from current action settings before any proposal.",
                        uncertainty="Unknown support is not evidence of unsupported methods.")
    for a in st.attempts or []:
        s = support.get(a["aid"])
        if a["identifier"] is False:
            no_identifier.setdefault(a["aid"], []).append(a["id"])
        if s is None or a["type"] not in ("restatement", "retraction"):
            continue
        reasons = []
        if s[a["type"]] is False:
            reasons.append(f"{a['type']} not supported")
        if a["method"] and s["methods"] and _tok(a["method"]) not in s["methods"]:
            reasons.append(f"match method '{a['method']}' not in accepted methods")
        if reasons:
            unsupported.setdefault(a["aid"], []).append({"attempt": a["id"], "order_token": a["order"],
                                                         "status": a["status"], "reasons": reasons})
    for aid, items in sorted(unsupported.items()):
        entity = {"account_id": ctx.account_id, "action_id": aid}
        ev = {"attempts": items, "support": support[aid]}
        prov = chk.finding("unsupported_method_used", "Info", entity,
                           f"Action {aid}: {len(items)} adjustment attempts use a type/method the support record "
                           "does not list", evidence=ev,
                           recommendation="Confirm current support before any further adjustment.",
                           uncertainty="Support documentation may be outdated.")
        chk.review("unsupported_method_used", entity,
                   f"Do these attempts for action {aid} conflict with the supported adjustment method and intended policy?",
                   evidence=ev, provisional=prov,
                   outcomes={"conflicts_with_supported_method": {"severity": "Warning", "recommendation":
                                                                 "Route to owner: align the adjustment path with a supported method."},
                             "support_record_outdated": {"severity": None, "recommendation": "Refresh the support record."},
                             "uncertain": {"severity": "Info", "recommendation": "Request current method documentation."}},
                   guidance="Judge from the support record, verified_at and source_reference only; never guess support.")
    if any(s["time_limit_reference"] for s in support.values()) and st.attempts:
        chk.partial("adjustment time limits are references (time_limit_reference), not machine-checkable windows")
    chk.observe("Adjustment support inventory", actions=sorted(support), scope=sorted(scope),
                attempts_missing_identifier=no_identifier,
                support={a: {k: s[k] for k in ("restatement", "retraction", "methods", "eligibility",
                                               "time_limit_reference")} for a, s in sorted(support.items())})


# ---------------------------------------------------------------------------------------------- step 6
def _retraction_restatement(ctx, st: _State) -> None:
    chk = ctx.check("retraction_restatement", "Retraction versus restatement semantics",
                    {ADJ: ["action_id", "order_token", "adjustment_attempt_id", "adjustment_type", "status",
                           "prior_reported_value", "restated_total_value"]})
    if not chk.runnable:
        return
    if st.attempts is None:
        chk.skip("adjustments not parseable", [])
        return
    if st.expected is None:
        chk.partial("expected remaining value unavailable: only the negative-total rule evaluated",
                    st.policy_missing + st.ledger_missing)
    per: dict[str, list[dict]] = {}
    for a in sorted(st.attempts, key=lambda x: (x["aid"], x["id"])):
        if a["status"] == "rejected" or a["type"] not in ("retraction", "restatement"):
            continue
        key = (a["aid"], a["order"])
        rec = (st.expected or {}).get(key)
        p = (st.policy or {}).get(a["aid"])
        issue = None
        E = rec["E"] if rec and rec["state"] == "mature" and p and p["basis"] == "net" else None
        if a["type"] == "restatement" and a["restated"] is not None and a["restated"] < 0:
            issue = "negative restated_total_value (a restatement supplies the new total, not a negative delta)"
        elif E is not None and a["type"] == "retraction" and E > TOL:
            issue = "retraction removes the conversion although expected remaining value is positive"
        elif (E is not None and a["type"] == "restatement" and a["restated"] is not None and a["prior"] is not None
              and abs(a["restated"] - E) > TOL and abs(a["restated"] - (a["prior"] - E)) <= TOL):
            issue = "restated_total_value equals the refund delta, not the expected remaining total"
        if issue:
            per.setdefault(a["aid"], []).append({"attempt": a["id"], "order_token": a["order"], "type": a["type"],
                                                 "status": a["status"], "prior_reported_value": a["prior"],
                                                 "restated_total_value": a["restated"], "expected_remaining": E,
                                                 "issue": issue})
            st.flagged.setdefault(key, set()).add("retraction_restatement")
    for aid, items in sorted(per.items()):
        chk.finding("retraction_restatement_mismatch", "Warning", {"account_id": ctx.account_id, "action_id": aid},
                    f"Action {aid}: {len(items)} adjustment attempts use retraction/restatement semantics that "
                    "contradict the expected remaining value", evidence={"attempts": items, "tolerance": TOL},
                    recommendation="Owner-reviewed correction via the supported method's new total value; never "
                                   "negative conversion uploads as a generic replacement.",
                    uncertainty="Accepted versus in-flight status is listed per attempt.")
    chk.observe("Retraction/restatement semantics evaluated",
                attempts=sum(1 for a in st.attempts if a["type"] in ("retraction", "restatement")),
                actions_flagged=sorted(per))


# ---------------------------------------------------------------------------------------------- step 7
def _supported(st: _State, a: dict) -> bool | None:
    s = (st.support or {}).get(a["aid"])
    if s is None or a["type"] not in ("restatement", "retraction") or s[a["type"]] is None:
        return None
    if s[a["type"]] is False:
        return False
    if not s["methods"] or not a["method"]:
        return None
    return _tok(a["method"]) in s["methods"]


def _adjustment_failures(ctx, st: _State) -> None:
    chk = ctx.check("adjustment_failures", "Failures, retries, currency, unmatched and already-adjusted events",
                    {ADJ: ["action_id", "order_token", "adjustment_attempt_id", "adjustment_type", "status",
                           "rejection_code", "retry_of_attempt_id", "currency"]})
    if not chk.runnable:
        return
    if st.attempts is None:
        chk.skip("adjustments not parseable", [])
        return
    if st.attempt_conflicts:
        chk.partial(f"conflicting duplicate adjustment_attempt_id rows excluded: {st.attempt_conflicts}")
    if st.support is None:
        chk.partial(f"{SUPPORT}.csv unavailable: repeated failures cannot be classed as supported")
    ids = {(a["aid"], a["id"]): a for a in st.attempts}
    accepted_orders = {(a["aid"], a["order"]) for a in st.attempts if a["status"] == "accepted"}
    per: dict[str, dict] = {}
    for a in sorted(st.attempts, key=lambda x: (x["aid"], x["order"] or "", x["sort"])):
        d = per.setdefault(a["aid"], {"accepted": 0, "rejected": 0, "in_flight": 0, "unknown": 0, "unresolved": [],
                                      "already_adjusted": [], "broken_chain": [], "currency": [], "unmatched": [],
                                      "codes": {}})
        d[a["status"]] += 1
        key = (a["aid"], a["order"])
        if a["status"] == "in_flight":
            st.blocked.setdefault(key, "adjustment in flight")
        if a["status"] == "rejected":
            code = a["rejection_code"] or "unknown"
            d["codes"][code] = d["codes"].get(code, 0) + 1
            if key not in accepted_orders:
                d["unresolved"].append({"attempt": a["id"], "order_token": a["order"], "type": a["type"],
                                        "rejection_code": a["rejection_code"], "retry_of": a["retry_of"],
                                        "supported": _supported(st, a)})
        if a["retry_of"]:
            parent = ids.get((a["aid"], a["retry_of"]))
            if parent is None:
                d["broken_chain"].append(a["id"])
            elif parent["status"] == "accepted":
                d["already_adjusted"].append({"attempt": a["id"], "retry_of": parent["id"], "order_token": a["order"]})
                st.blocked[key] = "retry of an already-accepted adjustment"
        prior_acc = [x for x in st.attempts if x["aid"] == a["aid"] and x["order"] == a["order"]
                     and x["status"] == "accepted" and x["sort"] < a["sort"] and x["type"] == a["type"]]
        if prior_acc and a["retry_of"] is None and a["status"] != "rejected":
            d["already_adjusted"].append({"attempt": a["id"], "after": prior_acc[-1]["id"], "order_token": a["order"]})
            st.blocked[key] = "second adjustment after an accepted one"
        pol_cur = (st.policy or {}).get(a["aid"], {}).get("currency")
        if a["currency"] and ((ctx.currency and a["currency"] != ctx.currency) or (pol_cur and a["currency"] != pol_cur)):
            d["currency"].append({"attempt": a["id"], "currency": a["currency"], "account_currency": ctx.currency,
                                  "policy_currency": pol_cur})
        if st.orders is not None and key not in st.orders:
            d["unmatched"].append(a["id"])
    if st.orders is None:
        chk.partial(f"{LEDGER}.csv unavailable: unmatched originals versus the local ledger not evaluated")
    for aid, d in sorted(per.items()):
        entity = {"account_id": ctx.account_id, "action_id": aid}
        supported = [x for x in d["unresolved"] if x["supported"] is True]
        ev = {"unresolved_rejected": d["unresolved"], "rejection_codes": d["codes"],
              "counts": {k: d[k] for k in ("accepted", "rejected", "in_flight", "unknown")}}
        if len(supported) >= 2:
            chk.finding("supported_adjustments_repeatedly_fail", "Warning", entity,
                        f"Action {aid}: {len(supported)} unresolved rejected attempts with an evidenced supported "
                        "type and match method", evidence=ev, calculation={"rule": ">= 2 unresolved supported rejections",
                                                                          "supported_unresolved": len(supported)},
                        recommendation="Owner review of rejection codes and matching before any retry; no automatic resubmission.",
                        uncertainty="Rejection codes are copied from integration logs.")
        elif len(d["unresolved"]) >= 2 and not any(x["supported"] is False for x in d["unresolved"]):
            chk.finding("repeated_failures_support_unknown", "Info", entity,
                        f"Action {aid}: {len(d['unresolved'])} unresolved rejected attempts; adjustment support unknown",
                        evidence=ev, recommendation="Document support, then review failures.",
                        uncertainty="Without support evidence the failures cannot be classed as supported.")
        chk.observe(f"Action {aid}: adjustment attempt outcomes", action_id=aid,
                    counts=ev["counts"], rejection_codes=d["codes"], unresolved_rejected=len(d["unresolved"]),
                    already_adjusted=d["already_adjusted"], broken_retry_chain=d["broken_chain"],
                    currency_mismatch=d["currency"], unmatched_to_ledger=d["unmatched"])


# ---------------------------------------------------------------------------------------------- step 8
def _residual_roas(ctx, st: _State) -> None:
    chk = ctx.check("residual_roas", "Residual value and ROAS difference on a mature comparable cohort",
                    {"campaign_metrics": ["campaign_id", "cost"],
                     DAILY: ["campaign_id", "action_id", "date", "conversion_value"]})
    if not chk.runnable:
        return
    if st.views is None:
        chk.skip("prerequisite accepted_vs_expected not runnable", st.policy_missing + st.ledger_missing)
        return
    if ctx.mature is not True:
        chk.partial(f"account window not mature ({ctx.maturity_note}): no ROAS difference")
    mc = ctx.params.get("min_conversions")
    if mc.value is None:
        chk.partial(f"min_conversions unresolved: {mc.reason}")
    ps, pe = ctx.period_start, ctx.period_end
    daily_actions: dict[str, set] = {}
    immature_campaigns = set()
    for r in ctx.rows(DAILY):
        d = V.parse_date(r.get("date"))
        if d is None or ps is None or pe is None or not (ps <= d <= pe):
            continue
        cid = _s(r.get("campaign_id"))
        if cid:
            daily_actions.setdefault(cid, set()).add(_s(r.get("action_id")))
            if V.boolean(r.get("reporting_mature")) is False:
                immature_campaigns.add(cid)
    metric_rows: dict[str, list[dict]] = {}
    for r in ctx.rows("campaign_metrics"):
        cid = _s(r.get("campaign_id"))
        if cid:
            metric_rows.setdefault(cid, []).append(r)
    actions = sorted({k[0] for k in st.expected or {} if (st.policy or {}).get(k[0], {}).get("treatment") == "adjusted_afterward"})
    for aid in actions:
        keys = [k for k, rec in st.expected.items() if k[0] == aid and rec["purchase"] and ps and pe
                and ps <= rec["purchase"] <= pe]
        decided = [k for k in keys if k in st.views]
        residual = sum(st.views[k] - st.expected[k]["E"] for k in decided)
        reasons = []
        if len(decided) != len(keys):
            reasons.append(f"{len(keys) - len(decided)} in-period orders undecidable/immature")
        if mc.value is None or len(decided) < mc.value:
            reasons.append(f"{len(decided)} decided orders < min_conversions {mc.value}")
        campaigns = sorted(c for c, acts in daily_actions.items() if aid in acts)
        mixed = [c for c in campaigns if daily_actions[c] != {aid}]
        if not campaigns:
            reasons.append("no campaign reports this action in the period")
        if mixed:
            reasons.append(f"campaigns {mixed} report other actions: spend not attributable to this action alone")
        if immature_campaigns & set(campaigns):
            reasons.append(f"reporting not mature for {sorted(immature_campaigns & set(campaigns))}")
        spend = 0.0
        for c in campaigns:
            rows = metric_rows.get(c, [])
            if len(rows) != 1:
                reasons.append(f"campaign {c}: {len(rows)} campaign_metrics rows (need exactly one period row)")
                continue
            cost = ctx.money(rows[0].get("cost"))
            if cost is None:
                reasons.append(f"campaign {c}: cost unknown")
                continue
            spend += cost
        roas_diff = None
        if not reasons and ctx.mature is True:
            roas_diff = V.ratio(residual, spend)
            if roas_diff is None:
                reasons.append("attributable spend is zero: ROAS difference undefined")
        for r in reasons:
            chk.partial(f"action {aid}: {r}")
        chk.observe(f"Action {aid}: residual value on the in-period cohort (findings live in skill-071)",
                    action_id=aid, in_period_orders=len(keys), decided_orders=len(decided), residual_value=residual,
                    attributable_campaigns=campaigns, attributable_spend=spend if not mixed else None,
                    roas_difference=roas_diff, min_conversions=mc.value, min_conversions_source=mc.source,
                    window=[ps, pe])


# ---------------------------------------------------------------------------------------------- step 9
def _reconciliation_proposals(ctx, st: _State) -> None:
    chk = ctx.check("reconciliation_proposals", "Owner-reviewed reconciliation candidates (request only)",
                    {LEDGER: ["action_id", "order_token"], ADJ: ["action_id", "order_token", "adjustment_attempt_id"]})
    if not chk.runnable:
        return
    if st.expected is None or st.views is None:
        chk.partial("upstream valuation checks not runnable: candidates limited to semantic/double-deduction flags")
    ready = sorted(f"{k[0]}/{k[1]}" for k in st.flagged if k not in st.blocked)
    blocked = {f"{k[0]}/{k[1]}": st.blocked[k] for k in sorted(st.flagged) if k in st.blocked}
    chk.observe("Reconciliation candidates for owner review; no adjustment is submitted", ready_for_owner_review=ready,
                blocked_until_resolved=blocked,
                flags={f"{k[0]}/{k[1]}": sorted(v) for k, v in sorted(st.flagged.items())})


def verify(ctx, item, decision) -> list[str]:
    """Critical outcomes need proposal.evidence_ref naming a ref present in the item's evidence.refs.

    Rules:   Refs are attempt ids, order/refund tokens or source_reference values from the supplied files.
    """
    if decision.get("outcome") != CRITICAL_OUTCOME:
        return []
    ref = (decision.get("proposal") or {}).get("evidence_ref")
    refs = set((item.evidence or {}).get("refs") or [])
    if not ref:
        return [f"{CRITICAL_OUTCOME} needs proposal.evidence_ref pointing at supplied evidence"]
    wanted = ref if isinstance(ref, list) else [ref]
    unknown = [str(r) for r in wanted if str(r) not in refs]
    return [f"evidence_ref {unknown} not among evidence.refs {sorted(refs)}"] if unknown else []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
