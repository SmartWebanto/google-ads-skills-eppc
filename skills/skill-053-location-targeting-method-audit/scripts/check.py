"""check.py — skill-053 deterministic location-method inventory, explicit-intent fit and exclusion coverage checks.

exports: verify(ctx, item, decision) -> list[str] | SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-053-location-targeting-method-audit/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #20 Check accounts for mistakes in setup and settings (Brainlabs) — clean-room reimplementation of
         the "no location targeting / targeting beyond the served area" setup check only; other checks of that
         script (language, ad counts, negatives) belong to other recipes
rules:   Settings come from custom/geo_targeting_methods (preferred, per criterion) or campaigns.geo_targets/
         geo_target_method (positive only; negative method then unknown). Empty cells stay unknown.
         Explicit intent = profile.campaign_objectives[id].remote_buyers (true/false). remote_buyers false +
         PRESENCE_OR_INTEREST, or true + PRESENCE, is a deterministic Warning (method conflicts with explicit
         intent); anything without explicit intent is AI review, never inferred from names or keywords.
         Service-area comparison uses exact normalized text of profile.service_area vs exported location text;
         an exclusion equal to a served area is a deterministic Warning; hierarchy/containment → review.
         "Targets all locations" only when the geo_targeting_methods manifest certifies completeness and the
         campaign has zero positive criteria.
         Every positive criterion ID of an ENABLED campaign also excluded AND 0 impressions in the window →
         provisional Info + review (other causes such as budget/disapproval/schedule are not excluded).
         Critical only via review outcome material_failure_evidenced, whose proposal.evidence_ref must match a row of
         external/owner_serving_evidence.csv (evidence_ref, campaign_id, intended_from, intended_to, material_basis)
         for this campaign whose intended window overlaps the report period and has a non-empty material_basis.
         Optional profile.local_intent_terms (owner-supplied list) only selects evidence for review;
         literal location words never classify intent. Cost is priority context, never waste or savings.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks06 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | Critical only via owner serving evidence
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

SKILL = "skill-053-location-targeting-method-audit"
VERSION = "1.0.0"

_GEO = "custom/geo_targeting_methods"
_GEO_COLS = ["campaign_id", "criterion_id", "criterion_type", "location_or_radius", "excluded",
             "positive_geo_target_type", "negative_geo_target_type"]
_SEPS = (" | ", ";", "|")
_PRESENCE, _INTEREST = "PRESENCE", "PRESENCE_OR_INTEREST"


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _objective(ctx, cid: str) -> dict:
    obj = ctx.profile.get("campaign_objectives") or {}
    o = next((v for k, v in obj.items() if str(k) == cid), None) if isinstance(obj, dict) else None
    return o if isinstance(o, dict) else {}


def _settings(ctx, use_geo: bool) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in sorted(ctx.rows("campaigns"), key=lambda r: _s(r.get("id"))):
        cid = _s(c.get("id"))
        out[cid] = {"status": _s(c.get("status")).upper(), "channel": c.get("channel_type"),
                    "positive_method": _s(c.get("geo_target_method")).upper() or None, "negative_method": None,
                    "include": [], "exclude": [], "source": "campaigns"}
        if not use_geo:
            out[cid]["include"] = [{"criterion_id": None, "name": n} for n in V.split_list(c.get("geo_targets"), _SEPS)]
    if use_geo:
        for r in ctx.rows(_GEO):
            cid = _s(r.get("campaign_id"))
            s = out.setdefault(cid, {"status": "", "channel": None, "positive_method": None, "negative_method": None,
                                     "include": [], "exclude": [], "source": _GEO})
            s["source"] = _GEO
            s["positive_method"] = _s(r.get("positive_geo_target_type")).upper() or s["positive_method"]
            s["negative_method"] = _s(r.get("negative_geo_target_type")).upper() or s["negative_method"]
            loc = {"criterion_id": _s(r.get("criterion_id")) or None, "name": r.get("location_or_radius"),
                   "type": r.get("criterion_type")}
            ex = V.boolean(r.get("excluded"))
            if ex is True:
                s["exclude"].append(loc)
            elif ex is False:
                s["include"].append(loc)
    for r in ctx.rows("bid_adjustments"):
        if _s(r.get("dimension")).upper() in ("LOCATION", "GEO", "PROXIMITY") and V.boolean(r.get("excluded")) is True:
            cid = _s(r.get("campaign_id"))
            if cid in out and not any(x["criterion_id"] == _s(r.get("criterion_id")) for x in out[cid]["exclude"]):
                out[cid]["exclude"].append({"criterion_id": _s(r.get("criterion_id")) or None,
                                            "name": r.get("segment_value"), "type": "bid_adjustments"})
    return out


def run(ctx) -> None:
    """Run per-campaign geo method, explicit-intent, service-area, exclusion and delivery-failure checks.

    Rules:   Empty setting cells stay unknown. Deterministic Warning only for method vs explicit
             profile.campaign_objectives[id].remote_buyers conflicts and exclusions equal to a served area; no explicit
             intent, hierarchy/containment and cross-campaign inconsistency → ai_review. Critical only when every
             positive criterion of an ENABLED campaign is excluded AND campaign_metrics shows 0 impressions. Cost is
             never waste or savings.
    """
    inv = ctx.check("campaign_inventory", "Serving and paused campaigns with geo applicability (step 1)",
                    {"campaigns": ["id", "status", "channel_type"]})
    later = (("method_settings", "Positive vs negative geo methods and criteria (step 2)"),
             ("intent_fit", "Method vs explicit campaign acquisition intent (step 3)"),
             ("local_intent_corroboration", "Keyword/ad corroboration for unknown intent (step 4)"),
             ("coverage_exclusions", "Targets and exclusions vs documented service area (step 5; index #20)"),
             ("same_objective_consistency", "Method consistency among same-objective campaigns (step 5)"),
             ("delivery_failure", "Contradictory geo settings with evidenced delivery failure"),
             ("spend_priority", "Window cost for prioritization and routing to skill-054 (step 6)"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("campaign inventory unavailable", inv.missing)
        return
    geo_t = ctx.table(_GEO)
    use_geo = geo_t is not None and not geo_t.missing(_GEO_COLS)
    settings = _settings(ctx, use_geo)
    inv.observe("Campaign inventory", serving=sorted(k for k, s in settings.items() if s["status"] == "ENABLED"),
                paused_or_other=sorted(k for k, s in settings.items() if s["status"] != "ENABLED"),
                settings_source=_GEO if use_geo else "campaigns")

    ms = ctx.check(later[0][0], later[0][1], {_GEO: _GEO_COLS} if use_geo else {"campaigns": ["id", "geo_target_method",
                                                                                                "geo_targets"]})
    if ms.runnable:
        if not use_geo:
            ms.partial("negative geo method and criterion IDs unknown without custom/geo_targeting_methods",
                       [f"{_GEO}:negative_geo_target_type"])
        unknown = [k for k, s in settings.items() if not s["positive_method"]]
        if unknown:
            ms.partial(f"positive method unknown for {unknown}")
        for cid, s in sorted(settings.items()):
            ms.observe(f"Campaign {cid}: positive {s['positive_method']}, negative {s['negative_method']}",
                       campaign_id=cid, status=s["status"], channel=s["channel"], positive_method=s["positive_method"],
                       negative_method=s["negative_method"], included=s["include"], excluded=s["exclude"],
                       source=s["source"])

    service = [V.norm_text(x) for x in (ctx.profile.get("service_area") or []) if _s(x)]
    fit = ctx.check(later[1][0], later[1][1], {"campaigns": ["id", "geo_target_method"]} if not use_geo
                    else {_GEO: _GEO_COLS})
    unknown_intent: list[str] = []
    if fit.runnable:
        if not service:
            fit.partial("profile.service_area missing: fit unknown")
        for cid, s in sorted(settings.items()):
            m = s["positive_method"]
            if m not in (_PRESENCE, _INTEREST):
                continue
            o = _objective(ctx, cid)
            remote = V.boolean(o.get("remote_buyers"))
            ent = {"campaign_id": cid, "positive_method": m}
            ev = {"positive_method": m, "negative_method": s["negative_method"], "service_area": service,
                  "remote_buyers": o.get("remote_buyers"), "role": o.get("role"),
                  "business_type": ctx.profile.get("business_type"), "included": s["include"], "status": s["status"]}
            if remote is not None:
                conflict = (remote is False and m == _INTEREST) or (remote is True and m == _PRESENCE)
                if conflict:
                    fit.finding("method_conflicts_intent", "Warning", ent,
                                f"Campaign {cid} uses {m} but remote_buyers={remote} is declared",
                                evidence=ev, recommendation=("Propose " + (_PRESENCE if m == _INTEREST else _INTEREST)
                                                             + " to the owner with the visitor-exception trade-off and a "
                                                               "post-change review window; approval required."),
                                uncertainty="Settings cannot quantify interest traffic or savings; see skill-054.")
                else:
                    fit.observe(f"Campaign {cid}: {m} consistent with declared remote_buyers={remote}",
                                campaign_id=cid, **ev)
                continue
            if not service:
                continue
            unknown_intent.append(cid)
            fit.review("method_conflicts_intent", ent,
                       f"Does {m} on campaign {cid} fit the declared service area/objectives, given that remote-buyer "
                       "intent is not explicitly declared?", evidence=ev,
                       outcomes={"conflicts_with_intent": {"severity": "Warning", "recommendation":
                                                           "Propose the alternative method with owner approval."},
                                 "consistent": {"severity": None, "recommendation": "Keep; document intent."},
                                 "uncertain": {"severity": "Info", "recommendation":
                                               "Ask the owner whether distant planners/travelers/remote buyers are customers."}},
                       guidance="Presence is not universally correct and interest is not universally wasteful; use only "
                                "profile objectives/service_area. No declared intent → uncertain.")
        if unknown_intent:
            fit.partial(f"explicit remote_buyers intent missing for {unknown_intent}")

    lc = ctx.check(later[2][0], later[2][1], {"keywords": ["campaign_id", "text"]})
    if lc.runnable:
        terms = [V.norm_text(t) for t in (ctx.profile.get("local_intent_terms") or []) if _s(t)] + service
        if not terms:
            lc.partial("no profile.local_intent_terms or service_area to select evidence")
        for cid in sorted(unknown_intent):
            kws = sorted({_s(k.get("text")) for k in ctx.rows("keywords") if _s(k.get("campaign_id")) == cid
                          and any(t in V.norm_text(k.get("text")) for t in terms)})
            heads = sorted({_s(a.get("headlines")) for a in ctx.rows("ads") if _s(a.get("campaign_id")) == cid
                            and any(t in V.norm_text(a.get("headlines")) for t in terms)})
            if not kws and not heads:
                continue
            lc.review("local_intent_suggested", {"campaign_id": cid},
                      f"Do these keywords/ads of campaign {cid} suggest local intent while owner intent is unknown?",
                      evidence={"keywords": kws[:25], "ad_headlines": heads[:10], "selection_terms": terms},
                      outcomes={"local_intent_suggested": {"severity": "Info", "recommendation":
                                                           "Ask the owner to confirm the campaign's acquisition intent."},
                                "no_local_intent": {"severity": None, "recommendation": "No action."},
                                "uncertain": {"severity": "Info", "recommendation": "Request the owner's intent."}},
                      guidance="Literal location words are corroboration only, never a business classifier.")

    cov = ctx.check(later[3][0], later[3][1], {"campaigns": ["id"]})
    if cov.runnable:
        _coverage(ctx, cov, settings, service, use_geo, geo_t)

    so = ctx.check(later[4][0], later[4][1], {"campaigns": ["id"]})
    if so.runnable:
        groups: dict[tuple, list[str]] = {}
        for cid, s in settings.items():
            o = _objective(ctx, cid)
            if o.get("role") and s["positive_method"] and s["status"] == "ENABLED":
                key = (str(o.get("role")), tuple(sorted(map(str, o.get("goal_ids") or []))))
                groups.setdefault(key, []).append(cid)
        if not groups:
            so.partial("no campaign_objectives roles to group same-objective campaigns")
        for key, cids in sorted(groups.items()):
            methods = {c: settings[c]["positive_method"] for c in sorted(cids)}
            if len(set(methods.values())) <= 1:
                so.observe(f"Objective {key[0]}: consistent methods", role=key[0], goal_ids=list(key[1]), methods=methods)
                continue
            so.review("same_objective_method_inconsistency", {"role": key[0], "goal_ids": list(key[1])},
                      f"Campaigns sharing objective {key[0]} use different location methods {methods}: unintended?",
                      evidence={"methods": methods, "remote_buyers": {c: _objective(ctx, c).get("remote_buyers")
                                                                      for c in sorted(cids)}},
                      outcomes={"inconsistent_unintended": {"severity": "Warning", "recommendation":
                                                            "Ask the owner to resolve the contradiction."},
                                "intentional_exception": {"severity": None, "recommendation": "Document the exception."},
                                "uncertain": {"severity": "Info", "recommendation": "Request per-campaign intent."}},
                      guidance="Consistency is not a goal across different objectives; only same-objective campaigns.")

    df = ctx.check(later[5][0], later[5][1], {_GEO: _GEO_COLS, "campaign_metrics": ["campaign_id", "impressions"]})
    if df.runnable:
        imps = {_s(m.get("campaign_id")): V.num(m.get("impressions")) for m in ctx.rows("campaign_metrics")}
        for cid, s in sorted(settings.items()):
            pos = {x["criterion_id"] for x in s["include"] if x["criterion_id"]}
            neg = {x["criterion_id"] for x in s["exclude"] if x["criterion_id"]}
            both = sorted(pos & neg)
            if not both:
                continue
            ent = {"campaign_id": cid}
            ev = {"included_and_excluded_ids": both, "positive_ids": sorted(pos), "impressions": imps.get(cid),
                  "status": s["status"], "window": [ctx.period_start, ctx.period_end]}
            if pos <= neg and s["status"] == "ENABLED" and imps.get(cid) == 0:
                # Config excludes every included location and nothing served; materiality and causation
                # (vs. budget, disapproval, schedule) need owner evidence → Info + review, Critical only via evidence_ref.
                prov = df.finding("geo_contradiction_delivery_failure", "Info", ent,
                                  f"Enabled campaign {cid} excludes every location it targets and served 0 impressions",
                                  evidence=ev, recommendation="Owner confirms whether the campaign should serve, then "
                                  "resolves the contradictory include/exclude settings.",
                                  uncertainty="Zero delivery may also stem from budget, disapproval or schedule.")
                df.review("geo_contradiction_delivery_failure", ent,
                          f"Campaign {cid} excludes all its targeted locations and served nothing: is this a material "
                          "delivery failure caused by the geo settings?",
                          evidence=ev,
                          outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                                   "Fix the geo contradiction now; cite the evidence."},
                                    "unintended_contradiction": {"severity": "Warning", "recommendation":
                                                                 "Resolve the contradiction against desired coverage."},
                                    "intentional_pause_by_geo": {"severity": None, "recommendation":
                                                                 "Document; prefer pausing the campaign explicitly."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask the owner for intent."}},
                          guidance="Critical needs proposal.evidence_ref showing the campaign was meant to serve in the window.",
                          provisional=prov)
            else:
                df.review("contradictory_geo_settings", ent,
                          f"Campaign {cid} both includes and excludes {both}: does this contradict desired coverage?",
                          evidence=ev,
                          outcomes={"contradicts_coverage": {"severity": "Warning", "recommendation":
                                                             "Owner resolves the contradiction."},
                                    "intentional": {"severity": None, "recommendation": "Document the carve-out."},
                                    "uncertain": {"severity": "Info", "recommendation": "Request the coverage brief."}})

    sp = ctx.check(later[6][0], later[6][1], {"campaign_metrics": ["campaign_id", "cost"]})
    if sp.runnable:
        cost = {_s(m.get("campaign_id")): ctx.money(m.get("cost")) for m in ctx.rows("campaign_metrics")}
        sp.observe("Window cost per campaign for prioritization (not waste)", cost=cost, currency=ctx.currency,
                   window=[ctx.period_start, ctx.period_end],
                   route="Measured geographic performance and out-of-area exposure → skill-054")


def _coverage(ctx, cov, settings, service, use_geo, geo_t) -> None:
    if not service:
        cov.partial("profile.service_area missing: coverage claims skipped")
        return
    certified = use_geo and geo_t.complete is True and not geo_t.truncated
    if not use_geo:
        cov.partial("criterion-level inclusions/exclusions unknown without custom/geo_targeting_methods")
    for cid, s in sorted(settings.items()):
        ent = {"campaign_id": cid}
        conflicts = [x for x in s["exclude"] if V.norm_text(x["name"]) in service]
        if conflicts:
            cov.finding("exclusion_contradicts_coverage", "Warning", ent,
                        f"Campaign {cid} excludes {[x['name'] for x in conflicts]}, listed in the documented service area",
                        evidence={"excluded": conflicts, "service_area": service},
                        recommendation="Owner confirms and removes/narrows the exclusion; approval required.",
                        uncertainty="Exact-name match; radius and child locations not evaluated here.")
        others = [x for x in s["exclude"] if x not in conflicts]
        if others:
            cov.review("exclusion_contradicts_coverage", {**ent, "scope": "unmatched_exclusions"},
                       f"Do exclusions {[x['name'] for x in others]} of campaign {cid} fall inside the served area?",
                       evidence={"excluded": others, "service_area": service},
                       outcomes={"contradicts_coverage": {"severity": "Warning", "recommendation":
                                                          "Owner reviews the exclusion."},
                                 "consistent": {"severity": None, "recommendation": "Keep."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request geo hierarchy."}})
        if not s["include"]:
            if certified and s["status"] == "ENABLED":
                cov.review("targets_beyond_service_area", {**ent, "scope": "all_locations"},
                           f"Campaign {cid} has no positive location criteria (all locations). Is that intended for "
                           f"service area {service}?",
                           evidence={"service_area": service, "positive_method": s["positive_method"],
                                     "remote_buyers": _objective(ctx, cid).get("remote_buyers")},
                           outcomes={"conflicts_with_intent": {"severity": "Warning", "recommendation":
                                                               "Propose explicit targets matching the served area."},
                                     "intentional": {"severity": None, "recommendation": "Document the intent."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}})
            elif s["status"] == "ENABLED":
                cov.partial(f"campaign {cid}: no positive targets listed; inventory not certified (unknown, not all)")
            continue
        beyond = [x for x in s["include"] if V.norm_text(x["name"]) not in service]
        if not beyond:
            cov.observe(f"Campaign {cid}: all positive targets match the service area", **ent, included=s["include"])
            continue
        cov.review("targets_beyond_service_area", ent,
                   f"Are targets {[x['name'] for x in beyond]} of campaign {cid} outside the served area {service}?",
                   evidence={"beyond_exact_match": beyond, "service_area": service,
                             "remote_buyers": _objective(ctx, cid).get("remote_buyers")},
                   outcomes={"conflicts_with_intent": {"severity": "Warning", "recommendation":
                                                       "Owner reviews targeting beyond the served area."},
                             "intentional": {"severity": None, "recommendation": "Keep (e.g. child location or remote buyers)."},
                             "uncertain": {"severity": "Info", "recommendation": "Request geo hierarchy/intent."}},
                   guidance="Exact text differed; a child location of the served area is consistent.")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   material_failure_evidenced (Critical) requires proposal.evidence_ref matching a supplied
             external/owner_serving_evidence row for the campaign with an overlapping intended window and a
             material_basis; every other outcome needs no proposal.
    """
    if decision.get("outcome") != "material_failure_evidenced":
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "")
    if not ref:
        return ["material_failure_evidenced needs proposal.evidence_ref"]
    cid = str(item.entity.get("campaign_id"))
    for r in ctx.rows("external/owner_serving_evidence"):
        if str(r.get("evidence_ref")) != ref or str(r.get("campaign_id")) != cid:
            continue
        start, end = V.parse_date(r.get("intended_from")), V.parse_date(r.get("intended_to"))
        overlaps = start is not None and (ctx.period_end is None or start <= ctx.period_end) and (
            end is None or ctx.period_start is None or end >= ctx.period_start)
        if not overlaps:
            return [f"evidence {ref}: intended serving window does not overlap the report period"]
        if not str(r.get("material_basis") or "").strip():
            return [f"evidence {ref}: material_basis missing"]
        return []
    return [f"evidence_ref {ref} not found for campaign {cid} in external/owner_serving_evidence"]


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
