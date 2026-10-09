"""check.py — skill-042 deterministic budget-constraint evidence, pool saturation and scale screening.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-042-budget-limited-campaign-identification/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Budget-constraint evidence = a dated budget_specific_diagnostic True, or a positive, unbounded Search
         budget-lost IS (SEARCH/SHOPPING channels only, impressions >= min_impressions). Generic "Limited" alone is Info only.
         Pool spend is summed once per budget/day across dated members (paused members included) against the
         dated amount; near-budget day shares (>=90%/>=100%) are heuristics, not billing violations.
         Economics compare mature sums (ctx.mature True, >= min_conversions) with the profile's approved
         campaign_objectives target_cpa/target_roas — never the platform target, never extrapolated.
         Lost IS is never converted into lost impressions/conversions/revenue.
         Scale candidates are Info. Warning only via review when >= 1 dated budget-specific diagnostic meets a
         profile.budget_constraints entry; verify() demands >= 2 dated diagnostics and proposal.commitment_ref.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks05 | initial deterministic check
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

SKILL = "skill-042-budget-limited-campaign-identification"
VERSION = "1.0.0"

DAILY = "custom/budget_constraint_daily"
STATUS = "custom/budget_constraint_status"
HISTORY = "custom/budget_history"
DAILY_COLS = ["campaign_id", "date", "budget_id", "cost"]
STATUS_COLS = ["campaign_id", "observed_at", "primary_status", "raw_reasons", "budget_specific_diagnostic"]
HISTORY_COLS = ["budget_id", "effective_from", "effective_to", "amount", "member_campaign_ids"]
METRIC_COLS = ["campaign_id", "cost", "conversions", "conversion_value"]
SEPS = (";", "|", ",")
NEAR = 0.9
IS_CHANNELS = ("SEARCH", "SHOPPING")  # channels reporting search impression-share metrics


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _pos(v) -> float | None:
    f = V.num(v)
    return f if f is not None and f > 0 else None


def _missing(ctx, key: str, cols: list[str]) -> list[str]:
    t = ctx.table(key)
    return [f"{key} (file)"] if t is None else [f"{key}:{c}" for c in t.missing(cols)]


def _has(ctx, key, cols) -> bool:
    t = ctx.table(key)
    return t is not None and not t.missing(cols)


def _approved(ctx, cid: str) -> tuple[str | None, float | None, str]:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    if isinstance(obj, dict):
        if _pos(obj.get("target_cpa")) is not None:
            return "CPA", _pos(obj.get("target_cpa")), f"profile.campaign_objectives[{cid}].target_cpa"
        if _pos(obj.get("target_roas")) is not None:
            return "ROAS", _pos(obj.get("target_roas")), f"profile.campaign_objectives[{cid}].target_roas"
    if not objectives:
        for kind, col in (("CPA", "target_cpa"), ("ROAS", "target_roas")):
            if _pos(ctx.profile.get(col)) is not None:
                return kind, _pos(ctx.profile.get(col)), f"profile.{col}"
    return None, None, f"no approved CPA/ROAS limit for campaign {cid}"


def _amount(ctx, r) -> float | None:
    unit = _s(r.get("amount_unit")).lower()
    if unit in ("micros", "micro"):
        return V.money(r.get("amount"), "micros")
    if unit == "":
        return ctx.money(r.get("amount"))
    if unit in ("currency", (ctx.currency or "").lower()):
        return V.num(r.get("amount"))
    return None


def _dated(rows, d):
    hits = [r for r in rows if V.parse_date(r.get("effective_from")) and V.parse_date(r.get("effective_from")) <= d
            and (V.parse_date(r.get("effective_to")) is None or V.parse_date(r.get("effective_to")) >= d)]
    return hits[0] if len(hits) == 1 else None


def _budget_key(ctx, cid: str) -> str | None:
    """Budget ID by stable IDs: campaigns.budget_id, else budgets.campaign_ids, else the latest dated membership."""
    camp = next((r for r in ctx.rows("campaigns") if _s(r.get("id")) == cid), {})
    if _s(camp.get("budget_id")):
        return _s(camp.get("budget_id"))
    hit = next((b for b in sorted(ctx.rows("budgets"), key=lambda b: _s(b.get("id")))
                if cid in V.split_list(b.get("campaign_ids"), SEPS)), None)
    if hit:
        return _s(hit.get("id")) or None
    rows = sorted((r for r in ctx.rows(HISTORY) if cid in V.split_list(r.get("member_campaign_ids"), SEPS)),
                  key=lambda r: _s(r.get("effective_from")))
    return (_s(rows[-1].get("budget_id")) or None) if rows else None


def _commitment(ctx, cid: str) -> tuple[str | None, object]:
    bc = ctx.profile.get("budget_constraints") or {}
    if not isinstance(bc, dict):
        return None, None
    bid = _budget_key(ctx, cid)
    for key in (cid, bid):
        if key is None:
            continue
        hit = next((v for k, v in bc.items() if str(k) == key), None)
        if hit is not None:
            return f"profile.budget_constraints[{key}]", hit
    return None, None


def run(ctx) -> None:
    """Run budget-constraint evidence, pool saturation, mature economics, scale-candidate and commitment checks.

    Rules:   Generic 'Limited' status is Info only; evidence = dated budget-specific diagnostic or positive
             Search/Shopping budget-lost IS with impressions >= min_impressions. Economics need ctx.mature and >=
             min_conversions against profile campaign_objectives targets, else partial; lost IS is never converted into
             lost volume/revenue. Scale candidates are Info; Warning only via review against a
             profile.budget_constraints commitment.
    """
    camps = {_s(r.get("id")): r for r in ctx.rows("campaigns") if _s(r.get("id"))}
    min_conv, min_imp = ctx.params.get("min_conversions"), ctx.params.get("min_impressions")

    # step 1 — pools
    pm = ctx.check("pool_membership", "Budget pools and dated membership (step 1)", {"campaigns": ["id"]})
    hist: dict[str, list] = {}
    if pm.runnable:
        if _has(ctx, HISTORY, HISTORY_COLS):
            for r in ctx.rows(HISTORY):
                if _s(r.get("budget_id")):
                    hist.setdefault(_s(r.get("budget_id")), []).append(r)
            for bid, rows in sorted(hist.items()):
                members = sorted({m for r in rows for m in V.split_list(r.get("member_campaign_ids"), SEPS)})
                pm.observe(f"Budget {bid}: {len(rows)} dated intervals, members {members}", budget_id=bid,
                           members=members, intervals=len(rows), shared=len(members) > 1)
        elif _has(ctx, "budgets", ["id", "amount", "campaign_ids"]):
            pm.partial("no dated budget history: current membership only, no persistence claims",
                       _missing(ctx, HISTORY, HISTORY_COLS))
            for b in sorted(ctx.rows("budgets"), key=lambda r: _s(r.get("id"))):
                pm.observe(f"Budget {b.get('id')}: current snapshot membership", budget_id=_s(b.get("id")),
                           members=V.split_list(b.get("campaign_ids"), SEPS), amount=ctx.money(b.get("amount")))
        else:
            pm.partial("budget pools unknown", _missing(ctx, HISTORY, HISTORY_COLS) + _missing(ctx, "budgets", ["id", "amount", "campaign_ids"]))

    # step 2 — budget-specific evidence
    ev = ctx.check("budget_constraint_evidence", "Budget-specific diagnostic or budget-lost IS (step 2)", {"campaigns": ["id"]})
    evidence: dict[str, dict] = {}
    if ev.runnable:
        have_status = _has(ctx, STATUS, STATUS_COLS)
        have_is = _has(ctx, "campaign_metrics", ["campaign_id", "impressions", "search_budget_lost_is"])
        if not have_status:
            ev.partial("no dated diagnostics: constraint dates unknown", _missing(ctx, STATUS, STATUS_COLS))
        if not have_is:
            ev.partial("base budget-lost IS unavailable", _missing(ctx, "campaign_metrics", ["campaign_id", "impressions", "search_budget_lost_is"]))
        if not have_status and not have_is:
            ev.skip("no budget-constraint evidence source")
        diags: dict[str, list] = {}
        generic: dict[str, list] = {}
        for r in sorted(ctx.rows(STATUS) if have_status else [], key=lambda r: (_s(r.get("campaign_id")), _s(r.get("observed_at")))):
            cid, d = _s(r.get("campaign_id")), V.parse_date(r.get("observed_at"))
            if not cid or d is None or (ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end):
                continue
            if V.boolean(r.get("budget_specific_diagnostic")) is True:
                diags.setdefault(cid, []).append({"observed_at": d, "primary_status": r.get("primary_status"),
                                                  "raw_reasons": r.get("raw_reasons"), "source_ref": r.get("source_ref")})
            elif "limited" in V.norm_text(r.get("primary_status")):
                generic.setdefault(cid, []).append(d)
        metrics = {_s(m.get("campaign_id")): m for m in ctx.rows("campaign_metrics")} if have_is else {}
        for cid in sorted(set(camps) | set(diags) | set(generic) | set(metrics)):
            m = metrics.get(cid)
            channel = _s((camps.get(cid) or {}).get("channel_type") or (m or {}).get("channel_type")).upper()
            lost = imp = None
            censored = False
            if m and channel in IS_CHANNELS:
                raw = m.get("search_budget_lost_is")
                lost, imp = ctx.rate(raw), V.num(m.get("impressions"))
                censored = raw is not None and lost is None
            is_ok = lost is not None and lost > 0 and imp is not None and min_imp.value is not None and imp >= min_imp.value
            dated = diags.get(cid, [])
            info = {"dated_diagnostics": dated, "budget_lost_is": lost, "impressions": imp, "censored_is": censored,
                    "channel": channel or None, "is_scope": "Search budget-lost IS over the report period" if m else None,
                    "min_impressions": min_imp.value}
            if dated or is_ok:
                evidence[cid] = info
                ev.observe(f"Campaign {cid}: budget-specific constraint evidence", campaign_id=cid, **info)
            elif generic.get(cid):
                ev.finding("generic_limited_not_budget_evidence", "Info", {"campaign_id": cid},
                           f"Campaign {cid}: 'Limited' status on {len(generic[cid])} dates without a budget-specific diagnostic",
                           evidence={**info, "limited_dates": generic[cid]},
                           recommendation="Do not treat as budget-limited; check rank, demand, policy and tracking causes.",
                           uncertainty="Generic Limited has several possible causes.")
            if censored:
                ev.partial(f"campaign {cid}: budget-lost IS withheld/bounded; not used")

    # step 3 — saturation
    sat = ctx.check("pool_saturation", "Pool spend vs dated budget on complete days (step 3)", {DAILY: DAILY_COLS, HISTORY: HISTORY_COLS})
    saturation: dict[str, dict] = {}
    if sat.runnable:
        cost: dict[tuple, float | None] = {}
        for r in ctx.rows(DAILY):
            cid, d = _s(r.get("campaign_id")), V.parse_date(r.get("date"))
            if not cid or d is None or (ctx.period_end and d > ctx.period_end):
                continue
            if (cid, d) in cost:
                sat.partial(f"duplicate daily row {cid} {d}: day excluded")
                cost[(cid, d)] = None
                continue
            cost[(cid, d)] = ctx.money(r.get("cost"))
        dates = sorted({d for _, d in cost})
        for bid, rows in sorted(hist.items()):
            near = full = n = 0
            spent = planned = 0.0
            for d in dates:
                h = _dated(rows, d)
                if h is None:
                    continue
                amt, members = _amount(ctx, h), V.split_list(h.get("member_campaign_ids"), SEPS)
                vals = [cost.get((m, d)) for m in members]
                if amt is None or amt <= 0 or not members or any(v is None for v in vals):
                    continue
                s = sum(vals)
                n += 1
                spent += s
                planned += amt
                near += s >= NEAR * amt
                full += s >= amt
            if n == 0:
                sat.partial(f"budget {bid}: no complete day with dated amount and member spend")
                continue
            saturation[bid] = {"days": n, "days_near_budget": near, "days_at_or_over_budget": full,
                               "share_near": V.ratio(near, n), "share_at_or_over": V.ratio(full, n),
                               "pool_spend": spent, "dated_budget_sum": planned, "utilization": V.ratio(spent, planned),
                               "near_threshold": NEAR}
            sat.observe(f"Budget {bid}: {near}/{n} complete days at >= {NEAR:.0%} of dated budget (heuristic)",
                        budget_id=bid, **saturation[bid])
            if n < 30:
                sat.partial(f"budget {bid}: only {n} complete days (<30)")

    # step 4 — economics
    eco = ctx.check("mature_economics", "Mature efficiency vs approved business limits (step 4)", {"campaign_metrics": METRIC_COLS})
    acceptable: dict[str, dict] = {}
    if eco.runnable:
        if ctx.mature is not True:
            eco.partial(f"outcomes not mature: {ctx.maturity_note}; descriptive totals only")
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: _s(r.get("campaign_id"))):
            cid = _s(m.get("campaign_id"))
            c, n, v = ctx.money(m.get("cost")), V.num(m.get("conversions")), ctx.money(m.get("conversion_value"))
            kind, limit, src = _approved(ctx, cid)
            row = {"cost": c, "conversions": n, "conversion_value": v, "cpa": V.ratio(c, n), "roas": V.ratio(v, c),
                   "limit_type": kind, "limit": limit, "limit_source": src, "min_conversions": min_conv.value}
            eco.observe(f"Campaign {cid}: mature outcomes", campaign_id=cid, **row)
            if ctx.mature is not True:
                continue
            if limit is None:
                eco.partial(src)
                continue
            if n is None or min_conv.value is None or n < min_conv.value:
                eco.partial(f"campaign {cid}: conversions {n} below min_conversions {min_conv.value}")
                continue
            achieved = row["cpa"] if kind == "CPA" else row["roas"]
            if achieved is None:
                eco.partial(f"campaign {cid}: achieved {kind} unavailable")
                continue
            if (achieved <= limit) if kind == "CPA" else (achieved >= limit):
                acceptable[cid] = row

    # step 5 — lost IS scope
    lis = ctx.check("lost_is_scope", "Budget-lost IS scope and censoring (step 5)",
                    {"campaign_metrics": ["campaign_id", "impressions", "search_budget_lost_is"]})
    if lis.runnable:
        for m in sorted(ctx.rows("campaign_metrics"), key=lambda r: _s(r.get("campaign_id"))):
            cid = _s(m.get("campaign_id"))
            channel = _s((camps.get(cid) or {}).get("channel_type") or m.get("channel_type")).upper()
            if channel not in IS_CHANNELS:
                lis.observe(f"Campaign {cid}: Search IS not applicable to channel {channel or 'unknown'}", campaign_id=cid)
                continue
            raw, imp = m.get("search_budget_lost_is"), V.num(m.get("impressions"))
            lost = ctx.rate(raw)
            lis.observe(f"Campaign {cid}: budget-lost IS reported as a share, not lost impressions", campaign_id=cid,
                        budget_lost_is=lost, rank_lost_is=ctx.rate(m.get("search_rank_lost_is")), impressions=imp,
                        censored=raw is not None and lost is None,
                        gate_passed=imp is not None and min_imp.value is not None and imp >= min_imp.value)

    # step 6 — recipients/donors
    rd = ctx.check("scale_candidates", "Budget-constrained campaigns with acceptable economics (step 6)",
                   {"campaign_metrics": METRIC_COLS})
    candidates = []
    if rd.runnable:
        if not evidence:
            rd.partial("no campaign with budget-specific constraint evidence")
        for cid in sorted(evidence):
            if cid not in acceptable:
                continue
            candidates.append(cid)
            e, a = evidence[cid], acceptable[cid]
            rd.finding("budget_constrained_scale_candidate", "Info", {"campaign_id": cid},
                       f"Campaign {cid}: budget-specific constraint with mature {a['limit_type']} within the approved limit",
                       evidence={**e, **a, "budget_id": _budget_key(ctx, cid)},
                       calculation={"cpa": a["cpa"], "roas": a["roas"], "limit": a["limit"], "limit_source": a["limit_source"],
                                    "window": [ctx.period_start, ctx.period_end]},
                       recommendation="Consider a guarded, owner-capped budget experiment; size via 051/045.",
                       uncertainty="Unmet demand is not verified; efficiency at higher spend is unknown; no lost-revenue projection.")
        goals = {cid: tuple(sorted(ctx.goal_ids(cid))) for cid in camps}
        for cid in candidates:
            donors = sorted(o for o in camps if o != cid and goals.get(o) and goals.get(o) == goals.get(cid)
                            and o not in evidence)
            rd.observe(f"Campaign {cid}: same-goal campaigns without budget constraint (possible donors, not overfunded)",
                       campaign_id=cid, goal_ids=list(goals.get(cid) or []), possible_donors=donors)

    # Warning path — documented constraint vs approved commitment
    dc = ctx.check("delivery_commitment", "Persistent constraint vs approved delivery commitment",
                   {STATUS: STATUS_COLS})
    if dc.runnable:
        for cid in sorted(evidence):
            dated = evidence[cid]["dated_diagnostics"]
            src, commit = _commitment(ctx, cid)
            if not dated:
                continue
            if commit is None:
                dc.partial(f"campaign {cid}: no profile.budget_constraints entry; commitment conflict not assessable")
                continue
            dc.review("constraint_conflicts_commitment", {"campaign_id": cid},
                      f"Does campaign {cid}'s documented budget constraint conflict with the approved delivery commitment?",
                      evidence={"dated_diagnostics": dated, "commitment": commit, "commitment_source": src,
                                "saturation": saturation.get(_budget_key(ctx, cid) or ""), "economics": acceptable.get(cid)},
                      outcomes={"conflicts_commitment": {"severity": "Warning", "recommendation":
                                                         "Owner review of pool budget within approved caps; no automatic increase."},
                                "no_conflict": {"severity": None, "recommendation": "No finding."},
                                "uncertain": {"severity": "Info", "recommendation": "Request the commitment definition."}},
                      guidance="conflicts_commitment needs persistence (>=2 dated diagnostics) and proposal.commitment_ref.")

    # steps 7-8 — sizing route
    sz = ctx.check("sizing_route", "Sizing evidence and owner caps for candidates (steps 7-8)")
    for cid in candidates:
        src, commit = _commitment(ctx, cid)
        sz.observe(f"Campaign {cid}: sizing requires 051/045 or a guarded experiment", campaign_id=cid,
                   owner_cap_source=src, owner_cap=commit)
        if commit is None:
            sz.partial(f"campaign {cid}: no owner-defined cap; no sized increase")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning requires persistence (>= 2 dated diagnostics) and a commitment reference."""
    if item.condition_key == "constraint_conflicts_commitment" and decision.get("outcome") == "conflicts_commitment":
        problems = []
        dates = {d.get("observed_at") for d in item.evidence.get("dated_diagnostics") or []}
        if len(dates) < 2:
            problems.append("persistence not documented: fewer than 2 dated budget-specific diagnostics")
        if not (decision.get("proposal") or {}).get("commitment_ref"):
            problems.append("proposal.commitment_ref required")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
