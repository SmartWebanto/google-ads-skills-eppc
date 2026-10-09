"""check.py — skill-032 deterministic RSA inventory and controlled creative-experiment validity checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-032-ad-copy-ab-testing/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #5 Split-testing ad optimizer (blog.markgrowth.com) — clean-room reimplementation of the per-ad-group
           ad comparison as a descriptive, sample-gated ledger; pausing/copying losers NOT integrated (recommend-only)
         index #12 Ad Rotate Analysis & Pause Losing Ads (Brainlabs) — clean-room: winner decision only via a
           registered experiment's valid inference report; pausing NOT integrated
         index #13 Analyse Ads and Pause Underperforming Ads (Brainlabs) — clean-room: same as #12; observational
           serving never yields a loser/pause finding
         index #14 Keep 2 best performing ads enabled (Roy Harmon) — 'keep top 2' quota rule refused: the recipe forbids
           ad-count quotas and winner claims from non-random serving
         index #105 Ad Performance Report (Google) — clean-room reimplementation of the ad-level performance ledger
rules:   Ordinary RSA rotation/optimization is NEVER an A/B test: without a plan row whose allocation_method is
         randomized (contains 'random' or 'split') covering the ad group, ad comparisons are observational only.
         Observational ad metrics produce observations, never winner/loser/pause findings (index #5/#12/#13/#14).
         Missing plan/results files → observational label + partial coverage, never a finding.
         SRM: chi-square goodness-of-fit on assigned_units vs planned_split; deterministic Warning ONLY when the
         profile pre-specifies profile.srm_alpha (the 'pre-specified method'); otherwise an ai_review item.
         planned_split must be 'arm_id:share' pairs, or equal shares ('50/50') — anything else is unparseable.
         Winner decisions only via ai_review outcome 'winner_supported'; verify() demands the experiment's own
         inference ref, an effect estimate, an interval and guardrails_ok true — never a naive proportion test.
         Sample gates (min_impressions/min_clicks/min_conversions) apply per arm; both arms must qualify.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-032-ad-copy-ab-testing"
VERSION = "1.0.0"

RSA = "RESPONSIVE_SEARCH_AD"
PLAN = "external/creative_experiment_plan"
RESULTS = "custom/creative_experiment_results"
CHANGES = "custom/creative_experiment_changes"
PLAN_DESIGN = ["hypothesis", "eligible_scope_ids", "control_definition", "treatment_definition", "assignment_unit",
               "allocation_method", "planned_split", "start_at", "end_at", "primary_metric", "mde", "alpha", "power",
               "target_sample_per_arm", "sequential_or_fixed_method", "guardrails", "stopping_rules", "owner",
               "approval_state"]
RATIO_METRICS = ("cpa", "roas", "cost_per_conversion", "conversion_value", "value", "conversions", "revenue")


def _on(v) -> bool | None:
    s = str(v or "").strip().upper()
    return None if not s else s in ("ENABLED", "ACTIVE")


def _randomized(plan: dict) -> bool:
    m = V.norm_text(plan.get("allocation_method"))
    return "random" in m or "split" in m


def _scope(plan: dict) -> set[str]:
    return set(V.split_list(plan.get("eligible_scope_ids"), (" | ", ";", "|", ",")))


def _split(v, arms: list[str]) -> dict[str, float] | None:
    """Planned share per arm (sums to 1) or None when unparseable/ambiguous."""
    s = str(v or "").strip()
    if not s:
        return None
    parts = [p.strip() for p in s.replace("|", ";").replace(",", ";").split(";") if p.strip()]
    if all(":" in p for p in parts):
        out = {}
        for p in parts:
            k, _, x = p.rpartition(":")
            f = V.num(x.strip().rstrip("%"))
            if f is None or f <= 0:
                return None
            out[k.strip()] = f
    else:
        shares = [V.num(x.strip().rstrip("%")) for x in s.split("/")]
        if len(shares) != len(arms) or any(x is None or x <= 0 for x in shares) or len(set(shares)) != 1:
            return None
        out = {a: shares[0] for a in arms}
    total = sum(out.values())
    if set(out) != set(arms) or total <= 0:
        return None
    return {k: x / total for k, x in out.items()}


def _chi2_sf(x: float, df: int) -> float:
    """Upper tail of the chi-square distribution (regularized upper incomplete gamma Q(df/2, x/2))."""
    a, z = df / 2.0, x / 2.0
    if z <= 0:
        return 1.0
    if z < a + 1:
        term = total = 1.0 / a
        n = a
        for _ in range(500):
            n += 1
            term *= z / n
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, 1.0 - total * math.exp(-z + a * math.log(z) - math.lgamma(a)))
    b, c, d = z + 1 - a, 1e300, 1.0 / (z + 1 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return min(1.0, math.exp(-z + a * math.log(z) - math.lgamma(a)) * h)


def _metric_kind(metric) -> str:
    m = V.norm_text(metric)
    if any(k in m for k in RATIO_METRICS):
        return "ratio"
    if "ctr" in m or "click" in m:
        return "ctr"
    if "cvr" in m or "conversion rate" in m or "conv_rate" in m:
        return "cvr"
    return "unknown"


def _plans(ctx) -> dict[str, dict]:
    return {str(p.get("experiment_id")): p for p in ctx.rows(PLAN) if p.get("experiment_id")}


def run(ctx) -> None:
    """Run RSA inventory, experiment classification, observational ledger and randomized-test validity checks.

    Rules:   Observational ad metrics never yield winner/loser/pause findings; no randomized plan → Info
             'no_formal_test'. Missing plan/results files → partial, never a finding. SRM mismatch is a deterministic
             Warning only when profile.srm_alpha is pre-specified, else ai_review. Per-arm sample gates apply to both
             arms; winner claims only via ai_review 'winner_supported' (Info) backed by the experiment's own inference.
    """
    mi, mc, mv = (ctx.params.get(n) for n in ("min_impressions", "min_clicks", "min_conversions"))
    plans = _plans(ctx)
    plan_t = ctx.table(PLAN)

    # -- step 1: complete ad-group spine left-joined to every ad type
    inv = ctx.check("rsa_inventory", "Ad-group spine with all ad types and RSA counts",
                    {"campaigns": ["id", "status"], "ad_groups": ["id", "campaign_id", "status"],
                     "ads": ["id", "campaign_id", "ad_group_id", "type", "status"]})
    active_groups: dict[str, dict] = {}
    if inv.runnable:
        camp = {str(c.get("id")): _on(c.get("status")) for c in ctx.rows("campaigns")}
        ads_by_g: dict[str, list[dict]] = {}
        for a in ctx.rows("ads"):
            ads_by_g.setdefault(str(a.get("ad_group_id")), []).append(a)
        tally = {"zero": 0, "one": 0, "multiple": 0}
        for g in sorted(ctx.rows("ad_groups"), key=lambda r: str(r.get("id"))):
            gid, cid = str(g.get("id")), str(g.get("campaign_id"))
            ads = sorted(ads_by_g.get(gid, []), key=lambda r: str(r.get("id")))
            enabled = [a for a in ads if _on(a.get("status"))]
            rsas = [a for a in enabled if str(a.get("type") or "").upper() == RSA]
            types = sorted({str(a.get("type") or "UNKNOWN").upper() for a in enabled})
            n = len(rsas)
            tally["zero" if n == 0 else "one" if n == 1 else "multiple"] += 1
            active = _on(g.get("status")) is True and camp.get(cid) is True
            inv.observe(f"Ad group {gid}: {n} enabled RSA(s), {len(enabled)} enabled ad(s) of all types",
                        campaign_id=cid, ad_group_id=gid, enabled_rsas=n, enabled_ads=len(enabled),
                        ad_types=types, active_scope=active)
            if not active:
                continue
            active_groups[gid] = {"campaign_id": cid, "ads": enabled, "rsa_ids": [str(a.get("id")) for a in rsas]}
            if n == 0:
                inv.observe(f"Ad group {gid} has no enabled RSA; eligible-ad absence is delegated to skill-037",
                            campaign_id=cid, ad_group_id=gid, other_enabled_ads=len(enabled))
            elif n == 1 and len(enabled) == 1:
                inv.finding("single_rsa", "Info", {"campaign_id": cid, "ad_group_id": gid, "ad_id": rsas[0].get("id")},
                            f"Ad group {gid} serves a single enabled ad (RSA {rsas[0].get('id')}): no within-group "
                            f"creative comparison exists",
                            evidence={"enabled_rsas": 1, "enabled_ads": 1},
                            recommendation="No test is mandatory; if a creative hypothesis exists, register a "
                                           "controlled experiment (plan, split, metric, power) before adding variants.",
                            uncertainty="Inventory only; says nothing about ad quality or missed uplift.")
        inv.observe("RSA count distribution across ad groups", **tally)

    # -- step 2: randomized experiment vs ordinary rotation (index #5/#12/#13/#105 ledger)
    cls = ctx.check("experiment_classification", "Documented randomized experiments vs ordinary ad rotation",
                    {"ads": ["id", "ad_group_id", "status"]})
    if cls.runnable and not inv.runnable:
        cls.skip("ad-group spine unavailable", inv.missing)
    elif cls.runnable:
        if plan_t is None:
            cls.partial("creative experiment plan missing: every multi-ad comparison is observational",
                        [f"{PLAN} (file)"])
        elif plan_t.missing(["experiment_id", "eligible_scope_ids", "allocation_method"]):
            cls.partial("plan lacks scope/allocation columns",
                        [f"{PLAN}:{c}" for c in plan_t.missing(["experiment_id", "eligible_scope_ids",
                                                                 "allocation_method"])])
        for gid, g in sorted(active_groups.items()):
            if len(g["ads"]) < 2:
                continue
            covering = sorted(e for e, p in plans.items() if {gid, g["campaign_id"]} & _scope(p))
            randomized = [e for e in covering if _randomized(plans[e])]
            ent = {"campaign_id": g["campaign_id"], "ad_group_id": gid}
            if randomized:
                cls.observe(f"Ad group {gid} is covered by randomized experiment(s) {randomized}", **ent,
                            experiments=randomized)
                continue
            if plan_t is None:
                cls.observe(f"Ad group {gid}: {len(g['ads'])} enabled ads under ordinary rotation — observational "
                            f"only (no experiment plan supplied)", **ent, ad_ids=[a.get("id") for a in g["ads"]])
                continue
            cls.finding("no_formal_test", "Info", ent,
                        f"Ad group {gid} rotates {len(g['ads'])} enabled ads without a documented randomized "
                        f"experiment: comparison is observational, not an A/B test",
                        evidence={"ad_ids": [a.get("id") for a in g["ads"]], "covering_plans": covering,
                                  "non_random_plans": [e for e in covering if e not in randomized]},
                        recommendation="Treat ad metrics as descriptive; for a causal decision register a randomized "
                                       "experiment. Do not pause ads from rotation data alone.",
                        uncertainty="Optimized RSA serving and equal impressions do not establish random assignment.")

    ledger = ctx.check("observational_ad_ledger", "Descriptive ad-level performance ledger (non-causal)",
                       {"ad_metrics": ["ad_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost",
                                       "conversions"]})
    if ledger.runnable and not inv.runnable:
        ledger.skip("ad-group spine unavailable", inv.missing)
    elif ledger.runnable:
        if ctx.mature is not True:
            ledger.partial(f"conversion maturity {ctx.mature}: {ctx.maturity_note}; conversion rates descriptive only")
        sums: dict[tuple[str, str], dict] = {}
        unknown = 0
        for r in ctx.rows("ad_metrics"):
            d = V.parse_date(r.get("date")) if "date" in (ctx.table("ad_metrics").columns) else None
            if d and ((ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end)):
                continue
            key = (str(r.get("ad_group_id")), str(r.get("ad_id")))
            acc = sums.setdefault(key, {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0})
            for m in acc:
                v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
                if v is None:
                    acc[m] = None
                    unknown += 1
                elif acc[m] is not None:
                    acc[m] += v
        if unknown:
            ledger.partial(f"{unknown} ad metric cells unknown; affected rates undefined")
        for gid, g in sorted(active_groups.items()):
            rows = []
            for a in g["ads"]:
                m = sums.get((gid, str(a.get("id"))))
                if m is None:
                    rows.append({"ad_id": a.get("id"), "metrics": "not in ad_metrics"})
                    continue
                imp, clk, conv = m["impressions"], m["clicks"], m["conversions"]
                rows.append({"ad_id": a.get("id"), **m, "ctr": V.ratio(clk, imp),
                             "cvr": V.ratio(conv, clk) if ctx.mature is True else None,
                             "cpa": V.ratio(m["cost"], conv) if ctx.mature is True else None,
                             "ctr_sample_ok": imp is not None and mi.value is not None and imp >= mi.value,
                             "cvr_sample_ok": clk is not None and mc.value is not None and clk >= mc.value,
                             "cpa_sample_ok": conv is not None and mv.value is not None and conv >= mv.value})
            ledger.observe(f"Ad group {gid}: descriptive ad ledger (non-random serving; no winner or pause)",
                           campaign_id=g["campaign_id"], ad_group_id=gid, ads=rows,
                           min_impressions=mi.value, min_clicks=mc.value, min_conversions=mv.value,
                           window=[ctx.period_start, ctx.period_end], mature=ctx.mature)

    # -- steps 3-8 require a registered experiment
    exp_checks = (("design_registration", "Pre-registered contrast, unit, split, metric and power"),
                  ("arm_integrity", "Unintended arm differences and edits during the test"),
                  ("sample_ratio", "Assigned-unit counts vs planned split (SRM)"),
                  ("inference_validity", "Registered inference method matches metric and unit"),
                  ("duration_and_power", "Planned duration, per-arm sample and maturity"),
                  ("adoption_decision", "Winner-supported / inconclusive / invalid decision"))
    if plan_t is None or plan_t.missing(["experiment_id"]):
        miss = [f"{PLAN} (file)"] if plan_t is None else [f"{PLAN}:experiment_id"]
        for cid, title in exp_checks:
            ctx.check(cid, title).skip("no creative experiment plan: analysis is observational", miss)
        return
    as_of = ctx.as_of or ctx.snapshot

    des = ctx.check("design_registration", exp_checks[0][1], {PLAN: ["experiment_id"] + PLAN_DESIGN})
    registered: dict[str, bool] = {}
    if des.runnable:
        for eid, p in sorted(plans.items()):
            gaps = [c for c in PLAN_DESIGN if p.get(c) is None]
            ent = {"experiment_id": eid}
            if not _randomized(p):
                registered[eid] = False
                des.finding("no_formal_test", "Info", ent,
                            f"Experiment {eid} allocation '{p.get('allocation_method')}' is not randomized: "
                            f"observational design, needs a separate causal design",
                            evidence={"allocation_method": p.get("allocation_method")},
                            recommendation="Do not interpret as an A/B test; use a randomized experiment split.",
                            uncertainty="Allocation vocabulary read literally from the plan.")
            elif gaps:
                registered[eid] = False
                des.finding("unavailable_valid_inference", "Info", ent,
                            f"Experiment {eid} registration incomplete: {', '.join(gaps)} missing",
                            evidence={"missing_fields": gaps, "approval_state": p.get("approval_state")},
                            recommendation="Complete the pre-registration before interpreting outcomes.",
                            uncertainty="Missing fields may exist outside the supplied plan export.")
            else:
                registered[eid] = True
                des.observe(f"Experiment {eid} registered with a complete design", experiment_id=eid,
                            assignment_unit=p.get("assignment_unit"), planned_split=p.get("planned_split"),
                            primary_metric=p.get("primary_metric"), mde=p.get("mde"), alpha=p.get("alpha"),
                            power=p.get("power"), target_sample_per_arm=p.get("target_sample_per_arm"))

    def active_test(p) -> bool:
        s, e = V.parse_date(p.get("start_at")), V.parse_date(p.get("end_at"))
        return bool(s and as_of and s <= as_of and (e is None or e >= (ctx.period_start or s)))

    chg = ctx.check("arm_integrity", exp_checks[1][1],
                    {CHANGES: ["experiment_id", "change_id", "changed_at", "entity_id", "field", "old_value",
                               "new_value", "reason"], PLAN: ["experiment_id", "start_at", "end_at"]})
    if chg.runnable:
        by_e: dict[str, list[dict]] = {}
        for c in ctx.rows(CHANGES):
            by_e.setdefault(str(c.get("experiment_id")), []).append(c)
        for eid, p in sorted(plans.items()):
            s, e = V.parse_date(p.get("start_at")), V.parse_date(p.get("end_at"))
            if s is None:
                chg.partial(f"experiment {eid}: start_at unknown; test-window edits undecidable")
                continue
            during = []
            for c in sorted(by_e.get(eid, []), key=lambda r: (str(r.get("changed_at")), str(r.get("change_id")))):
                d = V.parse_date(c.get("changed_at"))
                if d is None:
                    chg.partial(f"experiment {eid}: change {c.get('change_id')} has unknown changed_at")
                elif s <= d and (e is None or d <= e):
                    during.append({k: c.get(k) for k in ("change_id", "changed_at", "entity_id", "field",
                                                          "old_value", "new_value", "reason")})
            chg.observe(f"Experiment {eid}: {len(during)} configuration change(s) inside the test window",
                        experiment_id=eid, window=[s, e], changes=len(during))
            if during:
                chg.review("uncontrolled_edit", {"experiment_id": eid},
                           f"Do the {len(during)} change(s) during experiment {eid} create unintended arm "
                           f"differences (bids, budget, goals, geography, landing pages) beyond the treatment?",
                           evidence={"changes": during, "control_definition": p.get("control_definition"),
                                     "treatment_definition": p.get("treatment_definition"),
                                     "active_test": active_test(p)},
                           outcomes={"uncontrolled_edit": {"severity": "Warning", "recommendation":
                                                           "Treat results as potentially invalid; repair or restart."},
                                     "planned_change": {"severity": None, "recommendation":
                                                        "Change is part of the registered treatment; no finding."},
                                     "uncertain": {"severity": "Info", "recommendation":
                                                   "Ask the owner whether the edit touched one arm only."}},
                           guidance="Uncontrolled only if the edit hits one arm or shifts budget/eligibility mid-test; "
                                    "cite change_id(s) in the rationale.")

    res_t = ctx.table(RESULTS)
    arm_totals: dict[str, dict[str, dict]] = {}
    if res_t is not None:
        for r in ctx.rows(RESULTS):
            arm = arm_totals.setdefault(str(r.get("experiment_id")), {}).setdefault(str(r.get("arm_id")), {
                "assigned_units": 0.0, "impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0,
                "refs": set(), "lag_cutoffs": set()})
            for m in ("assigned_units", "impressions", "clicks", "cost", "conversions"):
                if m not in res_t.columns:
                    arm[m] = None
                    continue
                v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
                arm[m] = None if v is None or arm[m] is None else arm[m] + v
            if r.get("variance_or_inference_report_ref"):
                arm["refs"].add(str(r.get("variance_or_inference_report_ref")))
            if r.get("lag_cutoff"):
                arm["lag_cutoffs"].add(str(r.get("lag_cutoff")))

    srm = ctx.check("sample_ratio", exp_checks[2][1],
                    {RESULTS: ["experiment_id", "arm_id", "date", "assigned_units"], PLAN: ["planned_split"]})
    srm_bad: set[str] = set()
    if srm.runnable:
        alpha = V.num(ctx.profile.get("srm_alpha"))
        for eid, p in sorted(plans.items()):
            arms = arm_totals.get(eid)
            if not arms:
                srm.partial(f"experiment {eid}: no result rows")
                continue
            ids = sorted(arms)
            counts = {a: arms[a]["assigned_units"] for a in ids}
            shares = _split(p.get("planned_split"), ids)
            if any(v is None for v in counts.values()) or shares is None or len(ids) < 2:
                srm.partial(f"experiment {eid}: assigned_units unknown or planned_split "
                            f"'{p.get('planned_split')}' not parseable for arms {ids}")
                continue
            total = sum(counts.values())
            if total <= 0:
                srm.partial(f"experiment {eid}: zero assigned units; SRM undefined")
                continue
            chi2 = sum((counts[a] - total * shares[a]) ** 2 / (total * shares[a]) for a in ids)
            pval = _chi2_sf(chi2, len(ids) - 1)
            ev = {"assigned_units": counts, "planned_shares": shares, "chi_square": chi2, "df": len(ids) - 1,
                  "p_value": pval, "method": "chi-square goodness-of-fit on assigned units (not impressions)",
                  "srm_alpha": alpha, "srm_alpha_source": "profile.srm_alpha" if alpha else None}
            ent = {"experiment_id": eid}
            if alpha is not None and 0 < alpha < 1:
                if pval < alpha:
                    srm_bad.add(eid)
                    srm.finding("randomization_mismatch", "Warning", ent,
                                f"Experiment {eid} assigned units deviate from the planned split "
                                f"(chi2 {chi2:.2f}, p {pval:.2g} < srm_alpha {alpha:g})", evidence=ev,
                                calculation={"expected": {a: total * shares[a] for a in ids}, "total_units": total},
                                recommendation="Investigate assignment before any outcome inference.",
                                uncertainty="SRM flags a broken allocation; it does not say which arm is biased.")
                else:
                    srm.observe(f"Experiment {eid}: assigned units consistent with planned split", **ent, **ev)
            else:
                srm.partial("profile.srm_alpha not pre-specified: SRM decision left to review")
                srm.review("randomization_mismatch", ent,
                           f"Under experiment {eid}'s pre-specified SRM method, do assigned units "
                           f"{counts} deviate from the planned split?", evidence=ev,
                           outcomes={"mismatch": {"severity": "Warning", "recommendation":
                                                  "Investigate assignment before outcome inference."},
                                     "no_mismatch": {"severity": None, "recommendation": "Proceed to inference."},
                                     "uncertain": {"severity": "Info", "recommendation":
                                                   "Request the registered SRM method and threshold."}},
                           guidance="Use only the plan's registered SRM method; chi-square is a reference, not the rule.")

    inf = ctx.check("inference_validity", exp_checks[3][1],
                    {RESULTS: ["experiment_id", "arm_id", "variance_or_inference_report_ref"],
                     PLAN: ["primary_metric", "assignment_unit", "sequential_or_fixed_method"]})
    inference_ok: dict[str, list[str]] = {}
    if inf.runnable:
        for eid, p in sorted(plans.items()):
            arms = arm_totals.get(eid) or {}
            refs = sorted(set().union(*(a["refs"] for a in arms.values()))) if arms else []
            kind = _metric_kind(p.get("primary_metric"))
            ent = {"experiment_id": eid}
            if not arms:
                inf.partial(f"experiment {eid}: no result rows")
            elif not refs:
                inf.finding("unavailable_valid_inference", "Info", ent,
                            f"Experiment {eid} has no variance/inference report for primary metric "
                            f"'{p.get('primary_metric')}': no winner or interval can be stated",
                            evidence={"primary_metric": p.get("primary_metric"), "metric_kind": kind,
                                      "assignment_unit": p.get("assignment_unit")},
                            recommendation="Obtain the Ads experiment report or a cluster/variance-aware analysis; "
                                           "do not run a naive proportion test on attributed conversions.",
                            uncertainty="Inference may exist outside the supplied export.")
            else:
                inference_ok[eid] = refs
                inf.observe(f"Experiment {eid}: inference report(s) supplied", experiment_id=eid, refs=refs,
                            metric_kind=kind, method=p.get("sequential_or_fixed_method"))

    dur = ctx.check("duration_and_power", exp_checks[4][1],
                    {RESULTS: ["experiment_id", "arm_id", "assigned_units", "impressions", "clicks", "conversions",
                               "lag_cutoff"], PLAN: ["end_at", "target_sample_per_arm", "primary_metric"]})
    ready: set[str] = set()
    if dur.runnable:
        for eid, p in sorted(plans.items()):
            arms = arm_totals.get(eid)
            if not arms:
                dur.partial(f"experiment {eid}: no result rows")
                continue
            end, target = V.parse_date(p.get("end_at")), V.num(p.get("target_sample_per_arm"))
            kind = _metric_kind(p.get("primary_metric"))
            gate, gname = {"ctr": ("impressions", mi), "cvr": ("clicks", mc)}.get(kind, ("conversions", mv))
            problems = []
            if end is None or as_of is None or end > as_of:
                problems.append(f"planned end {end} not reached by {as_of}")
            if ctx.mature is not True:
                problems.append(f"conversion maturity {ctx.mature} ({ctx.maturity_note})")
            for a in sorted(arms):
                n = arms[a]["assigned_units"]
                if target is None or n is None or n < target:
                    problems.append(f"arm {a}: assigned {n} < target {target}")
                g = arms[a][gate]
                if g is None or gname.value is None or g < gname.value:
                    problems.append(f"arm {a}: {gate} {g} < {gname.name} {gname.value}")
            ev = {"arms": {a: {k: arms[a][k] for k in ("assigned_units", "impressions", "clicks", "conversions")}
                           for a in sorted(arms)}, "end_at": end, "as_of": as_of, "target_sample_per_arm": target,
                  "gate": f"{gate} >= {gname.name} ({gname.value}, {gname.source})", "mature": ctx.mature}
            if problems:
                dur.finding("underpowered_or_immature", "Info", {"experiment_id": eid},
                            f"Experiment {eid} not decision-ready: {'; '.join(problems)}", evidence=ev,
                            recommendation="Wait for the planned horizon and sample; fixed-horizon tests must not "
                                           "stop on repeated nominal significance.",
                            uncertainty="Readiness gate only; not evidence of no effect.")
            else:
                ready.add(eid)
                dur.observe(f"Experiment {eid}: planned horizon, per-arm sample and maturity satisfied",
                            experiment_id=eid, **ev)

    dec = ctx.check("adoption_decision", exp_checks[5][1], {PLAN: ["experiment_id", "owner", "guardrails"]})
    if dec.runnable:
        for eid, p in sorted(plans.items()):
            blockers = [b for b, ok in (("not registered/randomized", registered.get(eid)),
                                        ("no inference report", eid in inference_ok),
                                        ("not decision-ready", eid in ready),
                                        ("sample ratio mismatch", eid not in srm_bad)) if not ok]
            if blockers:
                dec.observe(f"Experiment {eid}: decision withheld ({', '.join(blockers)})", experiment_id=eid)
                continue
            dec.review("experiment_decision", {"experiment_id": eid},
                       f"Does experiment {eid}'s registered inference support a business-relevant effect on "
                       f"'{p.get('primary_metric')}' with guardrails met?",
                       evidence={"inference_refs": inference_ok[eid], "hypothesis": p.get("hypothesis"),
                                 "mde": p.get("mde"), "alpha": p.get("alpha"), "guardrails": p.get("guardrails"),
                                 "method": p.get("sequential_or_fixed_method"), "owner": p.get("owner"),
                                 "arms": {a: {k: v for k, v in x.items() if k not in ("refs", "lag_cutoffs")}
                                          for a, x in sorted(arm_totals[eid].items())}},
                       outcomes={"winner_supported": {"severity": "Info", "recommendation":
                                                      "Adoption opportunity: request owner approval; no uplift promise."},
                                 "inconclusive": {"severity": "Info", "recommendation":
                                                  "Keep current ads; propose a repaired or larger test."},
                                 "invalid_broken_metric": {"severity": "Warning", "recommendation":
                                                           "Primary metric broken during the test: repair and rerun."},
                                 "uncertain": {"severity": "Info", "recommendation":
                                               "Request the full experiment report."}},
                       guidance="winner_supported needs proposal {inference_ref (one of evidence refs), "
                                "effect_estimate, interval [low, high] excluding zero, guardrails_ok: true}.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: winner_supported must cite the experiment's own inference ref, an effect and an interval excluding 0."""
    if item.condition_key != "experiment_decision" or decision.get("outcome") != "winner_supported":
        return []
    p = decision.get("proposal") or {}
    problems = []
    if str(p.get("inference_ref") or "") not in item.evidence.get("inference_refs", []):
        problems.append("proposal.inference_ref must be one of the experiment's supplied inference reports")
    if V.num(p.get("effect_estimate")) is None:
        problems.append("proposal.effect_estimate required")
    iv = p.get("interval")
    if isinstance(iv, str):
        try:
            iv = json.loads(iv)
        except ValueError:
            iv = None
    lo, hi = (V.num(iv[0]), V.num(iv[1])) if isinstance(iv, list) and len(iv) == 2 else (None, None)
    if lo is None or hi is None or lo > hi:
        problems.append("proposal.interval [low, high] required")
    elif lo <= 0 <= hi:
        problems.append("interval includes zero: choose 'inconclusive'")
    if p.get("guardrails_ok") is not True:
        problems.append("proposal.guardrails_ok must be true for an adoption opportunity")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
