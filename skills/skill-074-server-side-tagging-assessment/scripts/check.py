"""check.py — skill-074 deterministic server-side tagging assessment from inventory, trials and requirements.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-074-server-side-tagging-assessment/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Client-side-only is a valid architecture: no server component → Info, never a defect; traffic volume is
         never a migration trigger. Conversion origin never identifies infrastructure.
         Trials compare only within (site, trial_id, scenario, device_class) when every variant shares non-empty
         browser_class, network_profile, cache_state, consent_scope and a traffic_assignment_method; otherwise
         differences are descriptive only (partial). Delivery rate = sum(observed)/sum(eligible) via V.ratio.
         Deterministic Warning only for EXPLICITLY documented risk on server/hybrid components: owner cells
         recorded as unassigned/none, or consent forwarding recorded as none/not forwarded. Other readiness
         judgments → review. Critical only via review with proposal.evidence_ref.
         Costs: ctx.money per component deduplicated by (site_id, component_id); never mix currencies; no ROI or
         blocker-loss estimate is computed. Privacy/legal inputs are owner constraints, not certification.
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

SKILL = "skill-074-server-side-tagging-assessment"
VERSION = "1.0.0"

ARCH = "external/tagging_architecture"
TRIAL = "external/tagging_measurement_trials"
REQ = "external/tagging_decision_requirements"
_UNASSIGNED = {"none", "unassigned", "no owner", "not assigned", "vacant"}
_NO_FORWARD = {"none", "not forwarded", "no forwarding", "absent", "not implemented"}
_CONDITIONS = ("browser_class", "network_profile", "cache_state", "consent_scope")


def _raw(v) -> str:
    return V.norm_text(v)


def _is_server(r) -> bool | None:
    s = _raw(r.get("client_or_server"))
    if not s:
        return None
    return "server" in s or "hybrid" in s


def _components(ctx) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in sorted(ctx.rows(ARCH), key=lambda r: (str(r.get("site_id")), str(r.get("component_id")))):
        out.setdefault((str(r.get("site_id")), str(r.get("component_id"))), r)
    return out


def _sites(components) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for (site, _), r in sorted(components.items()):
        out.setdefault(site, []).append(r)
    return out


def _entity(ctx, site, **extra) -> dict:
    return {"account_id": ctx.account_id, "site_id": site, **extra}


def run(ctx) -> None:
    """Run tagging-architecture inventory, delivery-trial comparisons, readiness risks and cost checks.

    Rules:   Client-side-only architecture → Info, never a defect; traffic volume never triggers migration. Trials
             compare only within matched (site, trial, scenario, device) cohorts with shared conditions; else partial.
             Deterministic Warning only for documented unassigned owners or consent not forwarded on server/hybrid
             components; other readiness → review; Critical only via review with proposal.evidence_ref. No ROI, no mixed
             currencies.
    """
    _inventory(ctx)
    components = _components(ctx)
    trials = sorted(ctx.rows(TRIAL), key=lambda r: tuple(str(r.get(k)) for k in
                                                          ("site_id", "trial_id", "scenario", "variant", "device_class", "run_id")))
    _measured_problem(ctx, trials)
    comparable = _comparability(ctx, trials)
    _options(ctx, comparable)
    _readiness(ctx, components)
    _policy(ctx, components)
    _cost(ctx, components)
    _decision(ctx, components, trials)


def _inventory(ctx) -> None:
    chk = ctx.check("architecture_inventory", "Inventory client/server paths, destinations and owners",
                    {ARCH: ["site_id", "component_id", "deployment_version", "client_or_server", "event_destinations",
                            "monitoring_owner", "operational_owner"],
                     "conversion_actions": ["id"]})
    if not chk.runnable:
        return
    comps = _components(ctx)
    if len(comps) < len(ctx.rows(ARCH)):
        chk.partial(f"{len(ctx.rows(ARCH)) - len(comps)} duplicate site/component rows ignored")
    for site, rows in sorted(_sites(comps).items()):
        unknown = [str(r.get("component_id")) for r in rows if _is_server(r) is None]
        if unknown:
            chk.partial(f"site {site}: client_or_server unknown for components {unknown}")
        chk.observe(f"Site {site} tagging inventory", **_entity(ctx, site),
                    server_components=sorted(str(r.get("component_id")) for r in rows if _is_server(r)),
                    client_components=sorted(str(r.get("component_id")) for r in rows if _is_server(r) is False),
                    destinations=sorted({d for r in rows for d in V.split_list(r.get("event_destinations"))}),
                    versions=sorted({str(r.get("deployment_version")) for r in rows}))
    chk.observe("Conversion actions supplied; conversion origin cannot identify tagging infrastructure",
                conversion_actions=len(ctx.rows("conversion_actions")))


def _variant_totals(rows) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        t = out.setdefault(str(r.get("variant")), {"eligible": 0.0, "observed": 0.0, "unknown": 0, "main_thread_ms": [],
                                                   "lcp_ms": [], "sample_size": 0.0, "sources": set()})
        el, ob = V.num(r.get("eligible_events")), V.num(r.get("observed_events"))
        if el is None or ob is None:
            t["unknown"] += 1
        else:
            t["eligible"] += el
            t["observed"] += ob
        for k in ("main_thread_ms", "lcp_ms"):
            x = V.num(r.get(k))
            if x is not None:
                t[k].append(x)
        t["sample_size"] += V.num(r.get("sample_size")) or 0
        if r.get("source_reference"):
            t["sources"].add(str(r.get("source_reference")))
    for t in out.values():
        t["delivery_rate"] = V.ratio(t["observed"], t["eligible"])
        for k in ("main_thread_ms", "lcp_ms"):
            xs = sorted(t[k])
            t[k] = xs[(len(xs) - 1) // 2] if xs else None
    return out


def _measured_problem(ctx, trials) -> None:
    chk = ctx.check("measured_problem", "Directly measured delivery, main-thread or reliability problem",
                    {TRIAL: ["trial_id", "site_id", "variant", "eligible_events", "observed_events", "main_thread_ms",
                             "sample_size", "source_reference"]})
    if not chk.runnable:
        return
    by_site: dict[str, list] = {}
    for r in trials:
        by_site.setdefault(str(r.get("site_id")), []).append(r)
    for site, rows in sorted(by_site.items()):
        totals = _variant_totals(rows)
        short = {v: t for v, t in totals.items() if t["delivery_rate"] is not None and t["delivery_rate"] < 1}
        chk.observe(f"Site {site}: measured delivery per variant (descriptive)", **_entity(ctx, site),
                    variants={v: {"eligible": t["eligible"], "observed": t["observed"], "delivery_rate": t["delivery_rate"],
                                  "median_main_thread_ms": t["main_thread_ms"], "unknown_rows": t["unknown"]}
                              for v, t in sorted(totals.items())})
        if short:
            chk.review("measured_current_problem", _entity(ctx, site),
                       f"Trials on site {site} show observed < eligible events for variants {sorted(short)}. Is this a "
                       f"directly measured current measurement/technical-policy problem?",
                       evidence={"variants": {v: {"eligible": t["eligible"], "observed": t["observed"],
                                                  "delivery_rate": t["delivery_rate"], "sources": sorted(t["sources"])}
                                              for v, t in sorted(short.items())}},
                       outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                                "Escalate to operational owner with the evidence."},
                                 "documented_risk": {"severity": "Warning", "recommendation":
                                                     "Scope a remediation or controlled trial with owners."},
                                 "not_a_problem": {"severity": None, "recommendation": "No action; excluded events explain it."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request a controlled comparison."}},
                       guidance="Missing events cannot be assigned to ad blockers without a measured counterfactual; "
                                "check excluded_events_reason. Critical needs proposal.evidence_ref.")


def _comparability(ctx, trials) -> dict[str, list]:
    chk = ctx.check("trial_comparability", "Trials compared only under equivalent conditions",
                    {TRIAL: ["trial_id", "site_id", "scenario", "variant", "device_class", *_CONDITIONS,
                             "traffic_assignment_method", "eligible_events", "observed_events"]})
    comparable: dict[str, list] = {}
    if not chk.runnable:
        return comparable
    groups: dict[tuple, list] = {}
    for r in trials:
        groups.setdefault(tuple(str(r.get(k)) for k in ("site_id", "trial_id", "scenario", "device_class")), []).append(r)
    for key, rows in sorted(groups.items()):
        site = key[0]
        variants = sorted({str(r.get("variant")) for r in rows})
        conds = {c: sorted({_raw(r.get(c)) for r in rows}) for c in _CONDITIONS}
        assign = sorted({_raw(r.get("traffic_assignment_method")) for r in rows})
        ok = (len(variants) >= 2 and all(len(v) == 1 and v[0] for v in conds.values()) and all(assign))
        totals = _variant_totals(rows)
        entity = _entity(ctx, site, trial_id=key[1], scenario=key[2], device_class=key[3])
        if not ok:
            chk.partial(f"trial {key[1]} ({site}/{key[2]}/{key[3]}): variants/conditions not equivalent; descriptive only")
            chk.observe(f"Trial {key[1]} not comparable", **entity, variants=variants, conditions=conds,
                        assignment=assign)
            continue
        rates = {v: t["delivery_rate"] for v, t in totals.items()}
        mt = {v: t["main_thread_ms"] for v, t in totals.items()}
        comparable.setdefault(site, []).append({"trial_id": key[1], "scenario": key[2], "device_class": key[3],
                                                "delivery_rate": rates, "median_main_thread_ms": mt})
        defined = [x for x in rates.values() if x is not None]
        mts = [x for x in mt.values() if x is not None]
        if (len(defined) >= 2 and max(defined) != min(defined)) or (len(mts) >= 2 and max(mts) != min(mts)):
            chk.finding("measured_trial_supports_evaluation", "Info", entity,
                        f"Controlled trial {key[1]} on {site} measures a difference between variants {variants}",
                        evidence={"delivery_rate": rates, "median_main_thread_ms": mt, "conditions": conds,
                                  "assignment": assign,
                                  "confounders": sorted({str(r.get("confounders")) for r in rows if r.get("confounders")}),
                                  "sample_size": {v: t["sample_size"] for v, t in totals.items()}},
                        recommendation="Evaluate the alternative against the documented success criteria; retain the "
                                       "no-change option.",
                        uncertainty="Measured under stated conditions only; no ROI or recovered-conversion estimate.")
        else:
            chk.observe(f"Trial {key[1]}: no measured difference between variants", **entity, delivery_rate=rates)
    return comparable


def _options(ctx, comparable) -> None:
    chk = ctx.check("options_comparison", "Compare no-change, client optimization, hybrid and server-side options",
                    {REQ: ["site_id", "requirement_id", "requirement", "success_metric", "accepted_threshold",
                           "alternative_design", "owner", "decision_deadline"]})
    if not chk.runnable:
        return
    by_site: dict[str, list] = {}
    for r in sorted(ctx.rows(REQ), key=lambda r: (str(r.get("site_id")), str(r.get("requirement_id")))):
        by_site.setdefault(str(r.get("site_id")), []).append(r)
    for site, reqs in sorted(by_site.items()):
        data = [{k: r.get(k) for k in ("requirement_id", "requirement", "success_metric", "accepted_threshold",
                                        "alternative_design", "owner", "decision_deadline")} for r in reqs]
        chk.observe(f"Site {site}: decision requirements", **_entity(ctx, site), requirements=data,
                    options=["no_change", "client_optimization", "hybrid", "server_side"])
        if site in comparable:
            chk.review("option_meets_criteria", _entity(ctx, site),
                       f"Against the explicit success criteria for site {site}, does the measured trial evidence support "
                       f"evaluating an alternative design rather than no change?",
                       evidence={"requirements": data, "comparable_trials": comparable[site]},
                       outcomes={"alternative_supported": {"severity": "Info", "recommendation":
                                                           "Propose a scoped trial/decision with the owner."},
                                 "no_change": {"severity": None, "recommendation": "Keep the current design."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request missing measurements."}},
                       guidance="Use only accepted_threshold vs measured metrics; never prescribe migration.")
        else:
            chk.partial(f"site {site}: no comparable trial; options cannot be scored against success criteria")


def _readiness(ctx, components) -> None:
    chk = ctx.check("operational_readiness", "Endpoint security, consent propagation, monitoring, retention, ownership",
                    {ARCH: ["site_id", "component_id", "client_or_server", "consent_forwarding_design",
                            "retention_policy_reference", "access_control_status", "monitoring_owner",
                            "operational_owner"]})
    if not chk.runnable:
        return
    fields = ("consent_forwarding_design", "retention_policy_reference", "access_control_status", "monitoring_owner",
              "operational_owner")
    servers = [(k, r) for k, r in sorted(components.items()) if _is_server(r)]
    for (site, comp), r in servers:
        entity = _entity(ctx, site, component_id=comp)
        vals = {f: r.get(f) for f in fields}
        unknown = [f for f, v in vals.items() if not _raw(v)]
        if unknown:
            chk.partial(f"component {site}/{comp}: readiness unknown for {unknown}")
        owners = [f for f in ("monitoring_owner", "operational_owner") if _raw(vals[f]) in _UNASSIGNED]
        if owners:
            chk.finding("ownership_risk", "Warning", entity,
                        f"Server component {comp} on {site} documents no {' / '.join(owners)}",
                        evidence=vals, recommendation="Assign monitoring/operational owners before relying on the path.",
                        uncertainty="Documented inventory state; operational incidents not measured.")
        if _raw(vals["consent_forwarding_design"]) in _NO_FORWARD:
            chk.finding("consent_propagation_risk", "Warning", entity,
                        f"Server component {comp} on {site} documents no consent forwarding",
                        evidence=vals, recommendation="Implementation and privacy owners: design consent propagation "
                                                      "before forwarding events (see skill 075).",
                        uncertainty="Design record only; runtime traces not assessed here.")
        if not owners and _raw(vals["consent_forwarding_design"]) not in _NO_FORWARD and not unknown:
            chk.review("readiness_risk", entity,
                       f"Does the documented readiness of server component {comp} on {site} show reliability, "
                       f"consent-propagation or ownership risk?",
                       evidence=vals,
                       outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                                "Escalate with the evidence reference."},
                                 "documented_risk": {"severity": "Warning", "recommendation": "Close the readiness gap."},
                                 "ready": {"severity": None, "recommendation": "No action."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request sanitized evidence."}},
                       guidance="Use only sanitized inventory values; Critical needs proposal.evidence_ref.")
    chk.observe("Server/hybrid components assessed for readiness", components=len(servers))


def _policy(ctx, components) -> None:
    chk = ctx.check("policy_constraints", "Owner-supplied privacy/legal constraints (no certification)",
                    {REQ: ["site_id", "approved_policy_reference"], ARCH: ["site_id", "client_or_server"]})
    if not chk.runnable:
        return
    refs: dict[str, set] = {}
    for r in ctx.rows(REQ):
        if r.get("approved_policy_reference"):
            refs.setdefault(str(r.get("site_id")), set()).add(str(r.get("approved_policy_reference")))
    for site, rows in sorted(_sites(components).items()):
        if any(_is_server(r) for r in rows) and site not in refs:
            chk.partial(f"site {site}: server path without an owner-supplied policy reference")
        chk.observe(f"Site {site}: policy references", site_id=site, references=sorted(refs.get(site, set())),
                    note="Server-side hosting does not confer compliance or permission to collect denied data.")


def _cost(ctx, components) -> None:
    chk = ctx.check("operating_cost", "Operating cost from supplied costs only",
                    {ARCH: ["site_id", "component_id", "monthly_cost", "currency", "migration_effort_estimate"]})
    if not chk.runnable:
        return
    for site, rows in sorted(_sites(components).items()):
        totals: dict[str, float] = {}
        unknown = []
        for r in rows:
            c, cur = ctx.money(r.get("monthly_cost")), (str(r.get("currency") or "").upper() or None)
            if c is None or cur is None:
                unknown.append(str(r.get("component_id")))
                continue
            totals[cur] = totals.get(cur, 0.0) + c
        if unknown:
            chk.partial(f"site {site}: monthly cost/currency unknown for {unknown}")
        if any(cur != ctx.currency for cur in totals):
            chk.partial(f"site {site}: costs in {sorted(totals)} differ from account currency {ctx.currency}; not mixed")
        chk.observe(f"Site {site}: supplied monthly operating cost by currency", site_id=site, monthly_cost=totals,
                    migration_effort=sorted({str(r.get("migration_effort_estimate")) for r in rows
                                             if r.get("migration_effort_estimate")}),
                    note="No ROI, recovered-conversion or blocker-loss estimate without a measured effect and model.")


def _decision(ctx, components, trials) -> None:
    chk = ctx.check("decision_proposal", "Scoped trial or no-change decision", {ARCH: ["site_id", "client_or_server"]})
    if not chk.runnable:
        return
    complete_arch = ctx.table(ARCH).complete is True
    trial_table = ctx.table(TRIAL)
    complete_trials = trial_table is not None and "site_id" in trial_table.columns and trial_table.complete is True
    if trial_table is None:
        chk.partial("no measurement trials supplied: every claimed benefit is unmeasured",
                    [f"{TRIAL}:site_id"])
    trial_sites = {str(r.get("site_id")) for r in trials}
    req_sites = {str(r.get("site_id")) for r in ctx.rows(REQ)}
    for site, rows in sorted(_sites(components).items()):
        server = any(_is_server(r) for r in rows)
        if not server and all(_is_server(r) is False for r in rows):
            if complete_arch:
                chk.finding("no_server_side_deployment", "Info", _entity(ctx, site),
                            f"Site {site} runs client-side tagging only; a valid architecture",
                            evidence={"components": sorted(str(r.get("component_id")) for r in rows)},
                            recommendation="No change unless a measured problem or requirement justifies a scoped trial.",
                            uncertainty="Traffic volume alone never requires migration.")
            else:
                chk.partial(f"site {site}: architecture completeness not attested")
        if site in req_sites and site not in trial_sites:
            if complete_trials:
                chk.finding("unmeasured_claimed_benefit", "Info", _entity(ctx, site),
                            f"Site {site} has decision requirements but no measurement trial",
                            evidence={"requirements": sorted(str(r.get("requirement_id")) for r in ctx.rows(REQ)
                                                             if str(r.get("site_id")) == site)},
                            recommendation="Propose a scoped, consent-respecting trial before any architecture decision.",
                            uncertainty="Benefits remain hypothetical until measured.")
            else:
                chk.partial(f"site {site}: trial completeness not attested; benefit measurement unknown")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes require proposal.evidence_ref to supplied direct evidence."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") == "Critical" and not str((decision.get("proposal") or {}).get("evidence_ref") or "").strip():
        return ["Critical needs proposal.evidence_ref citing direct measurement/technical-policy evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
