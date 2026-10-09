"""check.py — skill-010 deterministic Standard Shopping routing inventory and experiment design/result checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-010-campaign-priority-experiments/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #117 Find Duplicate Shopping Targets (Frederick Vallaeys) — clean-room reimplementation of
         detecting one product identity targeted by several Standard Shopping campaigns (Info inventory)
         index #121 Add negative keywords from Google Sheet to Shopping campaigns (peakace) — query-sculpting
         negatives across priority tiers become evidence + verified proposals, never uploads
         index #122 Exact Match Shopping Fencing (Christopher Gutknecht) — exact fencing negatives are
         proposals whose verify() rejects fences that block queries the profile routes to that campaign
rules:   Product identity = merchant_id + feed_label + language + target_country + product_id; join on it,
         never on titles. Routing applies to Standard Shopping only (campaigns.channel_type SHOPPING);
         PMax rows are excluded — priority rules cannot diagnose PMax coexistence.
         Equal priority overlap alone is Info; whether priorities/negatives contradict the approved routing
         intent (profile.shopping_routing_intent) is AI review. Absence of routing (eligible, never included)
         needs a manifest-complete shopping_routing inventory, else partial.
         Experiments: realized allocation = assigned_units share, never click share; arm/campaign mapping
         contradicting the design is a deterministic Warning; realized != planned share (2 decimals) is only a
         review screen. Daily totals are descriptive; NO winner without a matching experiment_inference row.
         Missing inference → Info 'inference_absent' (incomplete results), never a Warning.
         profile.shopping_query_routing {campaign_id: [queries]} lists queries a campaign must keep; verify()
         rejects proposed fencing negatives that block them or brand terms.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks02 | initial deterministic check
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
from adsrun.negatives import blocks, normalize_match  # noqa: E402

SKILL = "skill-010-campaign-priority-experiments"
VERSION = "1.0.0"

ROUTING = "custom/shopping_routing"
DESIGN = "external/experiment_design"
DAILY = "custom/experiment_daily"
INFER = "external/experiment_inference"
ID_COLS = ("merchant_id", "feed_label", "language", "target_country", "product_id")
ROUTING_NEEDS = {ROUTING: ["campaign_id", *ID_COLS, "priority", "included", "eligible", "snapshot_date"],
                 "campaigns": ["id", "channel_type"]}
DESIGN_DOC = ("hypothesis", "change_bundle", "primary_metric", "guardrails", "minimum_detectable_effect",
              "sample_plan", "stopping_rule")
MATCH_FIELDS = ("estimand", "analysis_unit", "statistical_method", "maturity_rule")
INFER_COLS = ["experiment_id", "reference_arm_id", "variant_arm_id", "metric", "estimand", "analysis_unit",
              "statistical_method", "estimate", "ci_lower", "ci_upper", "confidence_level", "analyzed_start",
              "analyzed_end", "goal_scope", "maturity_rule", "source"]
_MEMBER = re.compile(r"^(?P<text>.+?)\s*\((?P<match>EXACT|PHRASE|BROAD)\)$", re.IGNORECASE)


def _scope(ctx) -> None:
    c = ctx.check("scope", "Account, snapshot, currency, window and conversion maturity",
                  {"account": ["customer_id", "currency_code", "date_range_start", "date_range_end", "snapshot_date"]})
    if not c.runnable:
        return
    if None in (ctx.currency, ctx.period_start, ctx.period_end, ctx.snapshot):
        c.partial("account currency/period/snapshot not parseable")
    c.observe("Report scope", account_id=ctx.account_id, currency=ctx.currency, period_start=ctx.period_start,
              period_end=ctx.period_end, snapshot=ctx.snapshot, mature=ctx.mature, maturity_note=ctx.maturity_note,
              conversion_date_basis=ctx.account.get("conversion_date_basis"))


def _norm(v) -> str:
    return V.norm_text(v)


def _campaign_negatives(ctx) -> tuple[dict, list[str]]:
    """campaign_id → [(text, match, ref)] from campaign/account negatives and attached shared lists."""
    out: dict[str, list] = {}
    gaps: list[str] = []
    acct = []
    for r in ctx.rows("negative_keywords"):
        if str(r.get("status") or "").upper() in ("REMOVED", "DELETED"):
            continue
        m = normalize_match(r.get("match_type"))
        level = str(r.get("level") or "").lower()
        if m is None:
            gaps.append(f"negative '{r.get('text')}' has no explicit match type")
        elif level == "campaign":
            out.setdefault(str(r.get("campaign_id")), []).append((str(r.get("text")), m, "campaign"))
        elif level == "account":
            acct.append((str(r.get("text")), m, "account"))
    lists = ctx.table("shared_negative_lists")
    if lists is None:
        gaps.append("shared_negative_lists missing: shared-list protection unknown")
    else:
        for r in lists.rows:
            applied = V.split_list(r.get("campaigns_applied") if "campaigns_applied" in lists.columns
                                   else r.get("campaign_ids"), (";", "|", ","))
            members = []
            if "member_text" in lists.columns:
                m = normalize_match(r.get("member_match_type"))
                if m and r.get("member_text"):
                    members.append((str(r["member_text"]), m))
            else:
                for raw in str(r.get("keywords") or "").split(";"):
                    raw = raw.strip()
                    mm = _MEMBER.match(raw) if raw else None
                    if raw and not mm:
                        gaps.append(f"list {r.get('list_id')} member '{raw}' has no explicit match type")
                    elif mm:
                        members.append((mm.group("text").strip(), mm.group("match").upper()))
            for cid in applied:
                out.setdefault(cid, []).extend((t, m, f"shared list {r.get('list_id')}") for t, m in members)
    return ({cid: acct + v for cid, v in out.items()} | {"*": acct}), sorted(set(gaps))


def run(ctx) -> None:
    """Run Standard Shopping routing inventory plus experiment arm, design, result, inference and readiness checks.

    Rules:   PMax rows are excluded; equal-priority overlap is Info and routing-vs-intent contradictions are ai_review
             only; never-included products need a manifest-complete shopping_routing inventory, else partial.
             Arm/campaign mapping contradicting the design is the only deterministic Warning; allocation drift is a
             review screen. No winner without a matching experiment_inference row — its absence is Info
             'inference_absent', never a Warning.
    """
    _scope(ctx)
    camps = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    standard = {cid for cid, c in camps.items() if str(c.get("channel_type") or "").upper() == "SHOPPING"}
    have_camps = ctx.table("campaigns") is not None
    na = have_camps and not standard
    na_reason = "no Standard Shopping campaigns in campaigns.channel_type; priority routing does not apply (PMax excluded)"

    # step 2 — product identity
    ident = ctx.check("product_identity", "Join product identities (merchant/feed label/language/market/product)",
                      ROUTING_NEEDS, applicable=not na, na_reason=na_reason)
    routes: dict[tuple, dict[str, dict]] = {}
    if ident.runnable:
        excluded_pmax = incomplete = dupes = 0
        for r in ctx.rows(ROUTING):
            cid = str(r.get("campaign_id") or "")
            if cid not in standard:
                excluded_pmax += 1
                continue
            key = tuple(_norm(r.get(c)) for c in ID_COLS)
            if not all(key):
                incomplete += 1
                continue
            slot = routes.setdefault(key, {})
            if cid in slot:
                dupes += 1
                continue
            slot[cid] = {"priority": _norm(r.get("priority")), "included": V.boolean(r.get("included")),
                         "eligible": V.boolean(r.get("eligible")),
                         **{c: r.get(c) for c in ("geo_scope", "schedule", "budget_id") if c in r}}
        if incomplete:
            ident.partial(f"{incomplete} routing rows lack a full product identity; not joined")
        if dupes:
            ident.partial(f"{dupes} duplicate campaign/product rows dropped (fan-out)")
        ident.observe("Product identities joined", identities=len(routes), standard_shopping_campaigns=sorted(standard),
                      non_standard_rows_excluded=excluded_pmax, incomplete_rows=incomplete, duplicate_rows=dupes)

    # step 3 — priority vs effective negatives vs approved routing (+ #117 duplicate targets, #121/#122 sculpting)
    pr = ctx.check("priority_routing", "Priority and effective negatives vs approved query routing",
                   {**ROUTING_NEEDS, "negative_keywords": ["text", "match_type", "level", "campaign_id"],
                    "shared_negative_lists": ["list_id"]}, applicable=not na, na_reason=na_reason)
    if pr.runnable:
        negs, gaps = _campaign_negatives(ctx)
        for g in gaps:
            pr.partial(g)
        intent = ctx.profile.get("shopping_routing_intent")
        groups: dict[tuple, list] = {}
        for key in sorted(routes):
            active = {cid: v for cid, v in routes[key].items() if v["included"] is True and v["eligible"] is True}
            if len(active) >= 2:
                sig = tuple(sorted((cid, v["priority"]) for cid, v in active.items()))
                groups.setdefault(sig, []).append(key)
        for sig in sorted(groups):
            keys = groups[sig]
            entity = {"campaign_ids": [c for c, _ in sig], "priorities": {c: p for c, p in sig}}
            ev = {"products": len(keys), "product_ids_sample": [k[4] for k in keys[:20]],
                  "identity": list(ID_COLS), "snapshot": ctx.snapshot,
                  "effective_negatives": {c: [f"{t} ({m}) [{ref}]" for t, m, ref in sorted(negs.get(c, negs["*"]))]
                                          for c, _ in sig},
                  "routing_intent": intent, "context": {c: {k: v for k, v in routes[keys[0]][c].items()
                                                            if k in ("geo_scope", "schedule", "budget_id")} for c, _ in sig}}
            if len({p for _, p in sig}) == 1:
                pr.finding("same_priority_overlap", "Info", entity,
                           f"{len(keys)} eligible product(s) included in {len(sig)} Standard Shopping campaigns at the "
                           f"same priority '{sig[0][1]}'", evidence=ev,
                           recommendation="Confirm the overlap is intended; equal priority alone is not a conflict.",
                           uncertainty="Inventory overlap does not predict which campaign serves an auction.")
                continue
            pr.review("priority_routing", entity,
                      "Do these priorities and effective negatives contradict the approved query-routing intent for the "
                      "shared products?", evidence=ev,
                      outcomes={"routing_contradicts_strategy": {"severity": "Warning", "recommendation":
                                                                 "Owner review of priorities/negatives; supply fencing proposals."},
                                "consistent": {"severity": None, "recommendation": "No action."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask the owner to state routing intent."}},
                      guidance="Judge only against profile.shopping_routing_intent/objectives; no intent → uncertain. "
                               "Higher priority does not universally require negatives. Optional proposal.negatives: "
                               "[{negative, match_type, campaign_id}] within the reviewed campaigns.")
        pr.observe("Overlapping product groups", groups=len(groups), routing_intent_supplied=intent is not None)

    # step 4 — intended eligible coverage
    cov = ctx.check("eligible_coverage", "Eligible products not routed to any Standard Shopping campaign",
                    ROUTING_NEEDS, applicable=not na, na_reason=na_reason)
    if cov.runnable:
        t = ctx.table(ROUTING)
        if t.complete is not True:
            cov.partial("shopping_routing inventory not certified complete: absence of routing not provable")
        else:
            orphans = sorted(k for k, v in routes.items() if any(x["eligible"] is True for x in v.values())
                             and not any(x["included"] is True for x in v.values()))
            ineligible = sorted(k for k, v in routes.items() if any(x["included"] is True and x["eligible"] is False
                                                                   for x in v.values()))
            cov.observe("Eligible-coverage inventory", eligible_not_included=len(orphans),
                        included_but_ineligible=len(ineligible))
            if orphans:
                cov.review("eligible_not_routed", {"batch": "eligible_not_included"},
                           "Do these eligible products lack routing contrary to the approved eligible-product strategy?",
                           evidence={"products": len(orphans), "product_ids_sample": [k[4] for k in orphans[:50]],
                                     "routing_intent": ctx.profile.get("shopping_routing_intent")},
                           outcomes={"contradicts_strategy": {"severity": "Warning", "recommendation":
                                                              "Owner review of product-group inclusion."},
                                     "intentional_exclusion": {"severity": None, "recommendation": "No action."},
                                     "uncertain": {"severity": "Info", "recommendation": "Confirm the product strategy."}},
                           guidance="Exclusions can be deliberate (margin, stock, PMax ownership). No intent → uncertain.")

    # steps 5-8 — experiments
    design_rows = ctx.rows(DESIGN)
    arms = ctx.check("experiment_arms", "Arm → campaign mapping, dates and realized assigned-unit allocation",
                     {DESIGN: ["experiment_id", "arm_id", "campaign_id", "planned_split", "allocation_unit",
                               "planned_start", "planned_end"],
                      DAILY: ["experiment_id", "arm_id", "campaign_id", "date", "assigned_units"]})
    design: dict[str, dict[str, dict]] = {}
    for r in design_rows:
        design.setdefault(str(r.get("experiment_id")), {})[str(r.get("arm_id"))] = r
    daily: dict[str, dict[str, list[dict]]] = {}
    for r in ctx.rows(DAILY):
        daily.setdefault(str(r.get("experiment_id")), {}).setdefault(str(r.get("arm_id")), []).append(r)
    if arms.runnable:
        for eid in sorted(design):
            planned = {a: V.num(r.get("planned_split")) for a, r in design[eid].items()}
            total_units = 0.0
            units: dict[str, float] = {}
            for aid in sorted(design[eid]):
                d = design[eid][aid]
                rows = daily.get(eid, {}).get(aid, [])
                if not rows:
                    arms.partial(f"{eid}/{aid}: no daily rows; realized allocation unknown")
                    continue
                wrong = sorted({str(r.get("campaign_id")) for r in rows} - {str(d.get("campaign_id"))})
                if wrong:
                    arms.finding("arm_campaign_mismatch", "Warning", {"experiment_id": eid, "arm_id": aid},
                                 f"Arm {aid} of {eid} served through campaign(s) {wrong}; design maps it to "
                                 f"{d.get('campaign_id')}", evidence={"design_campaign": d.get("campaign_id"),
                                                                      "observed_campaigns": wrong, "source": d.get("source")},
                                 recommendation="Owner review of the experiment implementation before reading results.",
                                 uncertainty="Mapping taken from supplied daily report and design capture only.")
                u = [V.num(r.get("assigned_units")) for r in rows]
                if None in u:
                    arms.partial(f"{eid}/{aid}: unknown assigned_units on some days")
                    continue
                units[aid] = sum(u)
                total_units += units[aid]
                dates = sorted(d2 for d2 in (V.parse_date(r.get("date")) for r in rows) if d2)
                ps, pe = V.parse_date(d.get("planned_start")), V.parse_date(d.get("planned_end"))
                if dates and ps and pe and (dates[0] != ps or dates[-1] != pe):
                    arms.finding("duration_differs", "Info", {"experiment_id": eid, "arm_id": aid},
                                 f"Arm {aid} observed {dates[0]}..{dates[-1]} vs planned {ps}..{pe}",
                                 evidence={"observed": [dates[0], dates[-1]], "planned": [ps, pe]},
                                 recommendation="Confirm the effective window before analysis.",
                                 uncertainty="Duration alone neither validates nor invalidates the test.")
            for aid in sorted(set(daily.get(eid, {})) - set(design[eid])):
                arms.partial(f"{eid}: daily arm {aid} not in design")
            if None in planned.values() or abs(sum(v for v in planned.values() if v) - 1) > 0.01:
                arms.partial(f"{eid}: planned splits missing or not summing to 1: {planned}")
                continue
            if len(units) != len(design[eid]) or not total_units:
                continue
            realized = {a: V.ratio(units[a], total_units) for a in sorted(units)}
            arms.observe(f"{eid}: realized assigned-unit shares", experiment_id=eid, planned=planned, realized=realized,
                         assigned_units=units, allocation_unit=next(iter(design[eid].values())).get("allocation_unit"))
            if any(round(realized[a], 2) != round(planned[a], 2) for a in realized):
                arms.review("allocation_vs_design", {"experiment_id": eid},
                            f"Does the realized assigned-unit allocation of {eid} materially contradict the planned split?",
                            evidence={"planned": planned, "realized": realized, "assigned_units": units},
                            outcomes={"material_contradiction": {"severity": "Warning", "recommendation":
                                                                 "Owner review of the allocation before using results."},
                                      "within_design": {"severity": None, "recommendation": "No action."},
                                      "uncertain": {"severity": "Info", "recommendation": "Obtain assignment diagnostics."}},
                            guidance="Summed daily assigned units may count returning units more than once; unequal "
                                     "planned splits are deliberate. Judge against the design's allocation unit.")

    doc = ctx.check("design_documentation", "Hypothesis, change bundle, KPI, guardrails, sample and stopping plan",
                    {DESIGN: ["experiment_id", "arm_id", *DESIGN_DOC]})
    if doc.runnable:
        for eid in sorted(design):
            first = design[eid][sorted(design[eid])[0]]
            missing = [f for f in DESIGN_DOC if not first.get(f)]
            if missing:
                doc.finding("design_incomplete", "Info", {"experiment_id": eid},
                            f"Experiment {eid} design lacks {missing}", evidence={"missing_fields": missing},
                            recommendation="Document the missing design elements before any decision.",
                            uncertainty="Missing documentation does not prove the experiment is invalid.")
            parts = [p for p in re.split(r";|\+|,| and ", str(first.get("change_bundle") or "")) if p.strip()]
            doc.observe(f"{eid}: design elements", experiment_id=eid, primary_metric=first.get("primary_metric"),
                        change_components=len(parts), bundle_note="a bundle is assessed as a whole" if len(parts) > 1 else "",
                        stopping_rule=first.get("stopping_rule"), sample_plan=first.get("sample_plan"))

    out = ctx.check("arm_outcomes", "Mature descriptive arm outcomes from daily totals (no winner)",
                    {DAILY: ["experiment_id", "arm_id", "date", "impressions", "clicks", "cost", "conversions",
                             "conversion_value", "goal_scope"], DESIGN: ["experiment_id", "arm_id"]})
    infer_t = ctx.table(INFER)
    if out.runnable:
        mc = ctx.params.get("min_conversions")
        if ctx.lag_days is None or ctx.snapshot is None:
            out.partial("conversion lag or snapshot unknown: daily conversions not maturity-screened")
        for eid in sorted(design):
            summary, scopes = {}, set()
            for aid in sorted(design[eid]):
                acc = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0}
                immature = 0
                for r in daily.get(eid, {}).get(aid, []):
                    d = V.parse_date(r.get("date"))
                    if d is None or ctx.lag_days is None or ctx.snapshot is None or d > ctx.snapshot - timedelta(days=ctx.lag_days):
                        immature += 1
                        continue
                    scopes.add(_norm(r.get("goal_scope")))
                    for k in acc:
                        v = ctx.money(r.get(k)) if k == "cost" else V.num(r.get(k))
                        acc[k] = None if v is None or acc[k] is None else acc[k] + v
                summary[aid] = {**acc, "immature_days_excluded": immature,
                                "cpa": V.ratio(acc["cost"], acc["conversions"]),
                                "cvr": V.ratio(acc["conversions"], acc["clicks"]),
                                "roas": V.ratio(acc["conversion_value"], acc["cost"])}
            gated = all((s["conversions"] or 0) >= (mc.value or float("inf")) for s in summary.values())
            out.observe(f"{eid}: descriptive arm totals (no uncertainty, no winner)", experiment_id=eid, arms=summary,
                        min_conversions=mc.value, cpa_comparison_sample_ok=gated, goal_scopes=sorted(scopes))
            if len(scopes) > 1:
                out.partial(f"{eid}: arms report different goal scopes {sorted(scopes)}")
            has_inf = infer_t is not None and any(str(r.get("experiment_id")) == eid for r in infer_t.rows)
            if not has_inf:
                out.finding("inference_absent", "Info", {"experiment_id": eid},
                            f"Experiment {eid}: results incomplete — no method-backed inference supplied; no winner declared",
                            evidence={"arms": sorted(design[eid]), "descriptive_only": True,
                                      "design_method": next(iter(design[eid].values())).get("statistical_method")},
                            recommendation="Obtain the platform/analyst contrast with interval matching the design "
                                           "before any owner decision.",
                            uncertainty="Daily totals cannot identify assignment-unit variance; descriptive gaps are not effects.")

    inf = ctx.check("inference_match", "Supplied contrast matches design arms, estimand, unit, method and maturity",
                    {INFER: INFER_COLS, DESIGN: ["experiment_id", "arm_id", *MATCH_FIELDS]})
    if inf.runnable:
        for r in sorted(ctx.rows(INFER), key=lambda r: (str(r.get("experiment_id")), str(r.get("metric")))):
            eid = str(r.get("experiment_id"))
            d = design.get(eid, {})
            problems = []
            if not d:
                problems.append("experiment not in design")
            for a in ("reference_arm_id", "variant_arm_id"):
                if d and str(r.get(a)) not in d:
                    problems.append(f"{a} {r.get(a)} not a design arm")
            first = d[sorted(d)[0]] if d else {}
            for f in MATCH_FIELDS:
                if first and _norm(r.get(f)) != _norm(first.get(f)):
                    problems.append(f"{f} '{r.get(f)}' != design '{first.get(f)}'")
            ae, pe = V.parse_date(r.get("analyzed_end")), V.parse_date(first.get("planned_end"))
            if ae and pe and ae < pe:
                problems.append(f"analyzed_end {ae} before planned_end {pe} (early read)")
            entity = {"experiment_id": eid, "metric": r.get("metric"), "variant_arm_id": r.get("variant_arm_id")}
            ev = {k: r.get(k) for k in INFER_COLS}
            if problems:
                inf.finding("inference_inconclusive", "Info", entity,
                            f"Inference for {eid} does not match the design: inconclusive", evidence={**ev, "problems": problems},
                            recommendation="Re-run the analysis with the pre-declared estimand, unit, method and window.",
                            uncertainty="A mismatched contrast cannot support a winner.")
            else:
                inf.observe(f"{eid}: method-backed contrast consistent with design", **{k: r.get(k) for k in
                            ("metric", "estimate", "ci_lower", "ci_upper", "confidence_level", "statistical_method")})

    dec = ctx.check("decision_readiness", "Lag, sample plan and guardrail status before any owner decision",
                    {DESIGN: ["experiment_id", "planned_end", "sample_plan", "guardrails"]})
    if dec.runnable:
        for eid in sorted(design):
            first = design[eid][sorted(design[eid])[0]]
            pe = V.parse_date(first.get("planned_end"))
            lag_ok = None if pe is None or ctx.snapshot is None or ctx.lag_days is None else \
                (ctx.snapshot - pe).days >= ctx.lag_days
            matched = any(o["check"] == "inference_match" and o["text"].startswith(eid) for o in ctx.result.observations)
            status = "ready_for_owner_decision" if lag_ok and matched else "not_ready"
            dec.observe(f"{eid}: decision status {status}", experiment_id=eid, planned_end=pe, lag_mature=lag_ok,
                        method_backed_inference=matched, sample_plan=first.get("sample_plan"),
                        guardrails=first.get("guardrails"), note="age alone never concludes an experiment")


def verify(ctx, item, decision) -> list[str]:
    """Rules: routing proposals must stay in reviewed campaigns and never block routed queries or brand terms."""
    if item.condition_key != "priority_routing" or decision.get("outcome") != "routing_contradicts_strategy":
        return []
    problems = []
    routed = ctx.profile.get("shopping_query_routing") or {}
    for p in (decision.get("proposal") or {}).get("negatives") or []:
        text, match, cid = str(p.get("negative") or "").strip(), normalize_match(p.get("match_type")), str(p.get("campaign_id") or "")
        if not text or match is None or cid not in item.entity["campaign_ids"]:
            problems.append("each negative needs negative, match_type EXACT|PHRASE|BROAD and a reviewed campaign_id")
            continue
        for q in next((v for k, v in routed.items() if str(k) == cid), None) or []:
            if blocks(text, match, q):
                problems.append(f"'{text}' ({match}) would block '{q}', routed to campaign {cid}")
        for b in ctx.profile.get("brand_terms") or []:
            if blocks(text, match, b):
                problems.append(f"'{text}' ({match}) would block brand term '{b}'")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
