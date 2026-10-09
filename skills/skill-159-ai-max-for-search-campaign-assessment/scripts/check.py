"""check.py — skill-159 deterministic AI Max for Search feature, dependency and safeguard review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-159-ai-max-for-search-campaign-assessment/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Feature states come ONLY from custom/ai_max_config; campaign metrics never reveal AI Max settings.
         Empty/unparseable state = unknown (None), never disabled; unknown → Info 'unverified', never a pass.
         Config rows: campaign scope = empty ad_group_id; latest snapshot_at per (campaign, ad group) wins;
         two differing rows at the same latest snapshot = conflict → scope treated as unknown (partial).
         Documented dependencies are deterministic Info: ad-group search-term matching needs campaign-level
         matching; final URL expansion needs text customization; URL inclusions never restrict expansion.
         Whether an enabled feature conflicts with an APPROVED safeguard is AI review (Warning outcome);
         Critical only via review outcome 'live_breach_confirmed' whose verify demands proposal.evidence_ref.
         Safeguards count only with approval_status 'approved' and an exact campaign_id match.
         Experiment arms are compared only with controlled assignment (_CONTROLLED tokens), identical goal
         sets, ctx.mature True and both arms passing the metric's sample gate; pre/post stays descriptive.
         Proposals: one feature per test with baseline/metric/risk/allocation/duration/stop/owner (verify).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-159-ai-max-for-search-campaign-assessment"
VERSION = "1.0.0"

CFG = "custom/ai_max_config"
SAFE = "external/ai_max_safeguards"
EXP = "custom/ai_max_experiment_daily"
FEATURES = ("search_term_matching_enabled", "text_customization_enabled", "final_url_expansion_enabled")
_TRUE = {"true", "yes", "y", "1", "enabled", "on", "active"}
_FALSE = {"false", "no", "n", "0", "disabled", "off", "paused", "inactive", "not_enabled"}
_AVAILABLE = {"available", "eligible", "true", "yes", "1"}
_UNAVAILABLE = {"unavailable", "not_available", "not available", "ineligible", "false", "no", "0"}
_CONTROLLED = {"randomized", "randomised", "random_split", "cookie_based", "search_based", "ads_experiment"}
_CONV_BIDDING = {"TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"}
_PROPOSAL_FIELDS = ("baseline", "primary_metric", "risk_floor_or_cap", "allocation_method", "stop_conditions", "owner")
_BREACH = "live_breach_confirmed"


def _id(v) -> str:
    return "" if v is None else str(v).strip()


def _state(v) -> bool | None:
    s = V.norm_text(v)
    return True if s in _TRUE else False if s in _FALSE else None


def _avail(v) -> bool | None:
    s = V.norm_text(v)
    return True if s in _AVAILABLE else False if s in _UNAVAILABLE else None


def _latest(rows: list[dict]) -> tuple[dict, list]:
    """Latest config row per (campaign_id, ad_group_id); differing rows at the same latest snapshot conflict."""
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((_id(r.get("campaign_id")), _id(r.get("ad_group_id"))), []).append(r)
    out, conflicts = {}, []
    for key in sorted(groups):
        rs = groups[key]
        best = max(V.parse_date(r.get("snapshot_at")) or date.min for r in rs)
        top = [r for r in rs if (V.parse_date(r.get("snapshot_at")) or date.min) == best]
        if any(r != top[0] for r in top[1:]):
            conflicts.append(key)
            continue
        out[key] = top[0]
    return out, conflicts


def _optional(ctx, key: str, cols: list[str]) -> tuple[list[dict] | None, list[str]]:
    t = ctx.table(key)
    if t is None:
        return None, [f"{key} (file)"]
    miss = [f"{key}:{c}" for c in t.missing(cols)]
    return (None, miss) if miss else (t.rows, [])


def _search_campaigns(ctx) -> dict[str, dict]:
    return {_id(r.get("id")): r for r in ctx.rows("campaigns")
            if str(r.get("channel_type") or "").upper() == "SEARCH" and str(r.get("status") or "").upper() != "REMOVED"}


def _approved_safeguards(rows: list[dict] | None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in sorted(rows or [], key=lambda r: (_id(r.get("campaign_id")), _id(r.get("requirement_id")))):
        if V.norm_text(r.get("approval_status")) == "approved" and _id(r.get("campaign_id")):
            out.setdefault(_id(r.get("campaign_id")), []).append(r)
    return out


def _breach_outcomes(what: str) -> dict:
    return {
        "conflict_evidenced": {"severity": "Warning", "recommendation":
                               f"Request a scoped change (disable or constrain {what}) naming owner, monitoring and recovery."},
        _BREACH: {"severity": "Critical", "recommendation":
                  "Escalate the confirmed live breach to the safeguard owner; cite the generated-content/page evidence."},
        "compatible": {"severity": None, "recommendation": "No conflict; keep the safeguard under monitoring."},
        "uncertain": {"severity": "Info", "recommendation": "Request generated-asset/selected-page evidence before judging."},
    }


def run(ctx) -> None:
    """Run AI Max inventory, dependency, safeguard, URL-expansion, experiment and proposal checks for Search campaigns.

    Rules:   States come only from custom/ai_max_config; unknown/missing settings, dependency gaps, non-adoption and
             non-causal/sparse experiments → Info, never pass. Enabled features vs approved safeguards go to ai_review
             (Warning; Critical only live_breach_confirmed). Arm metrics compared only with ctx.mature True, controlled
             assignment, same goals and min_impressions/min_clicks/min_conversions; test proposals are ai_review only.
    """
    search = _search_campaigns(ctx)
    conf: dict = {}

    # -- step 1: feature inventory ------------------------------------------------------------
    inv = ctx.check("feature_inventory", "AI Max top-level, per-feature and ad-group override inventory",
                    {"campaigns": ["id", "channel_type"],
                     CFG: ["campaign_id", "ad_group_id", "snapshot_at", "availability", "ai_max_enabled", *FEATURES]})
    if inv.runnable:
        conf, conflicts = _latest(ctx.rows(CFG))
        for key in conflicts:
            inv.partial(f"{CFG}: differing rows at latest snapshot for campaign {key[0]} ad group {key[1] or '-'}; state unknown")
        non_search = sorted({k[0] for k in conf if k[0] and k[0] not in search})
        if non_search:
            inv.observe("Config rows outside Search campaigns ignored (AI Max for Search is not PMax)", campaign_ids=non_search)
        adopted = 0
        for cid in sorted(search):
            crow = conf.get((cid, ""))
            overrides = sorted(g for (c, g) in conf if c == cid and g)
            entity = {"campaign_id": cid}
            if crow is None:
                inv.finding("ai_max_settings_unverified", "Info", entity,
                            f"Search campaign {cid} has no campaign-level AI Max config row: availability and settings unknown",
                            evidence={"unknown_fields": ["availability", "ai_max_enabled", *FEATURES],
                                      "ad_group_rows": overrides},
                            recommendation="Export the campaign's AI Max settings screen (including disabled) before any proposal.",
                            uncertainty="Unknown is not disabled; no adoption conclusion is possible.")
                continue
            avail, enabled = _avail(crow.get("availability")), _state(crow.get("ai_max_enabled"))
            states = {f: _state(crow.get(f)) for f in FEATURES}
            unknown = ([] if avail is not None else ["availability"]) + ([] if enabled is not None else ["ai_max_enabled"]) + \
                      [f for f, s in states.items() if s is None]
            ev = {"snapshot_at": crow.get("snapshot_at"), "source_screen": crow.get("source_screen"),
                  "availability": crow.get("availability"), "ai_max_enabled": crow.get("ai_max_enabled"),
                  **{f: crow.get(f) for f in FEATURES}, "ad_group_rows": overrides,
                  "ad_group_overrides": crow.get("ad_group_overrides"), "enabled_at": crow.get("enabled_at")}
            inv.observe(f"AI Max matrix: campaign {cid}", campaign_id=cid, availability=avail, ai_max_enabled=enabled,
                        features=states, ad_group_rows=len(overrides), snapshot_at=crow.get("snapshot_at"))
            if unknown:
                inv.finding("ai_max_settings_unverified", "Info", entity,
                            f"Campaign {cid}: AI Max fields unknown: {', '.join(unknown)}",
                            evidence={**ev, "unknown_fields": unknown},
                            recommendation="Re-export the current AI Max settings; unknown values are not disabled.",
                            uncertainty="Dependent dependency and safeguard checks cannot pass on unknown states.")
            if avail is True and enabled is False:
                inv.finding("ai_max_not_adopted", "Info", entity,
                            f"Campaign {cid}: AI Max available but not enabled (non-adoption)",
                            evidence=ev,
                            recommendation="No change required; non-adoption is legitimate. Consider only an opt-in per-feature test.",
                            uncertainty="No performance expectation can be inferred for a feature that is off.")
            if enabled is True:
                adopted += 1
        inv.observe("AI Max inventory totals", search_campaigns=len(search), enabled_campaigns=adopted,
                    config_rows=len(conf))

    # -- step 2: supported controls and dependencies -------------------------------------------
    dep = ctx.check("control_dependencies", "Campaign/ad-group control dependencies and bidding readiness",
                    {"campaigns": ["id", "channel_type", "bidding_strategy_type"],
                     CFG: ["campaign_id", "ad_group_id", "search_term_matching_enabled", "brand_controls"]})
    if dep.runnable:
        if not conf:
            conf, _ = _latest(ctx.rows(CFG))
        for (cid, gid), row in sorted(conf.items()):
            if not gid or cid not in search:
                continue
            crow = conf.get((cid, ""))
            entity = {"campaign_id": cid, "ad_group_id": gid}
            camp_stm = _state(crow.get("search_term_matching_enabled")) if crow else None
            if _state(row.get("search_term_matching_enabled")) is True:
                if camp_stm is False:
                    dep.finding("adgroup_matching_ineffective", "Info", entity,
                                f"Ad group {gid} enables search-term matching while campaign {cid} has it disabled: "
                                "the ad-group activation is ineffective",
                                evidence={"ad_group_value": row.get("search_term_matching_enabled"),
                                          "campaign_value": crow.get("search_term_matching_enabled"),
                                          "rule": "campaign-level search-term matching must be enabled first"},
                                recommendation="Decide deliberately: enable at campaign level only via an approved test, or clear the override.",
                                uncertainty="Based on the exported snapshot; verify in the current UI.")
                elif camp_stm is None:
                    dep.partial(f"campaign {cid}: campaign-level search-term matching unknown; ad group {gid} effectiveness undetermined")
            gb, cb = V.norm_text(row.get("brand_controls")), V.norm_text(crow.get("brand_controls")) if crow else ""
            if gb and gb != cb:
                dep.observe(f"Ad group {gid} brand controls differ from campaign {cid}: ad-group brand inclusions can "
                            "override campaign inclusions", campaign_id=cid, ad_group_id=gid,
                            ad_group_brand_controls=row.get("brand_controls"),
                            campaign_brand_controls=crow.get("brand_controls") if crow else None)
        for cid in sorted(search):
            crow = conf.get((cid, ""))
            bid = str(search[cid].get("bidding_strategy_type") or "").upper() or None
            dep.observe(f"Campaign {cid} bidding readiness (from settings, no conversion-count rule)", campaign_id=cid,
                        bidding_strategy_type=bid, conversion_based_smart_bidding=(bid in _CONV_BIDDING) if bid else None,
                        supported_control_help_url=crow.get("supported_control_help_url") if crow else None)

    # -- step 3: search-term matching and text customization vs safeguards --------------------
    saf_cols = ["campaign_id", "requirement_id", "forbidden_content_or_claims", "mandatory_copy",
                "approved_brand_terms", "tracking_evidence_ref", "approval_status"]
    rev = ctx.check("feature_safeguard_review", "Search-term matching and text customization against approved safeguards",
                    {CFG: ["campaign_id", "ad_group_id", "search_term_matching_enabled", "text_customization_enabled"],
                     SAFE: saf_cols})
    if rev.runnable:
        if not conf:
            conf, _ = _latest(ctx.rows(CFG))
        approved = _approved_safeguards(ctx.rows(SAFE))
        unapproved = sorted({_id(r.get("requirement_id")) for r in ctx.rows(SAFE)
                             if V.norm_text(r.get("approval_status")) != "approved"})
        if unapproved:
            rev.observe("Safeguard rows not approved are not used as documented restrictions", requirement_ids=unapproved)
        relevant = {"search_term_matching_enabled": ("approved_brand_terms", "forbidden_content_or_claims"),
                    "text_customization_enabled": ("forbidden_content_or_claims", "mandatory_copy", "approved_brand_terms")}
        reviewed = 0
        for cid in sorted(search):
            crow = conf.get((cid, ""))
            if crow is None:
                continue
            for feat, fields in relevant.items():
                st = _state(crow.get(feat))
                ag_on = sorted(g for (c, g), r in conf.items() if c == cid and g and _state(r.get(feat)) is True)
                if st is None:
                    rev.partial(f"campaign {cid}: {feat} unknown; safeguard review not possible")
                    continue
                if st is not True and not ag_on:
                    continue
                guards = [{"requirement_id": g.get("requirement_id"), **{f: g.get(f) for f in fields},
                           "tracking_evidence_ref": g.get("tracking_evidence_ref"), "owner": g.get("owner"),
                           "landing_page_snapshot_ref": g.get("landing_page_snapshot_ref")}
                          for g in approved.get(cid, []) if any(g.get(f) for f in fields)]
                if not guards:
                    rev.partial(f"campaign {cid}: {feat} enabled but no approved safeguard with {'/'.join(fields)}")
                    continue
                reviewed += 1
                tracking, note = ctx.tracking_for_campaign(cid)
                rev.review(f"safeguard_conflict_{feat.removesuffix('_enabled')}", {"campaign_id": cid, "feature": feat},
                           f"Does enabled {feat} in campaign {cid} conflict with the approved safeguards listed?",
                           evidence={"campaign_value": crow.get(feat), "ad_groups_enabled": ag_on, "safeguards": guards,
                                     "snapshot_at": crow.get("snapshot_at"), "tracking_state": tracking, "tracking_note": note},
                           outcomes=_breach_outcomes(feat),
                           guidance="Judge only against approved safeguard text and supplied generated-asset/page evidence. "
                                    f"'{_BREACH}' needs proposal.evidence_ref to supplied delivery evidence.")
        rev.observe("Feature/safeguard pairs sent to review", count=reviewed)

    # -- step 4: final URL expansion controls ---------------------------------------------------
    url = ctx.check("url_expansion_controls", "Final URL expansion dependency, URL inclusion/exclusion scope and RSA pins",
                    {CFG: ["campaign_id", "ad_group_id", "text_customization_enabled", "final_url_expansion_enabled",
                           "url_inclusions", "url_exclusions"]})
    if url.runnable:
        if not conf:
            conf, _ = _latest(ctx.rows(CFG))
        saf_rows, saf_miss = _optional(ctx, SAFE, ["campaign_id", "requirement_id", "allowed_domain_paths",
                                                   "mandatory_copy", "approval_status"])
        if saf_miss:
            url.partial("safeguard review for URL expansion skipped: approved safeguards missing", saf_miss)
        ad_rows, ad_miss = _optional(ctx, "ads", ["campaign_id", "pinned_positions"])
        if ad_miss:
            url.partial("RSA pin bypass review skipped: pins unknown", ad_miss)
        approved = _approved_safeguards(saf_rows)
        pins: dict[str, list] = {}
        for a in sorted(ad_rows or [], key=lambda a: (_id(a.get("campaign_id")), _id(a.get("id")))):
            if a.get("pinned_positions") and str(a.get("status") or "ENABLED").upper() == "ENABLED":
                pins.setdefault(_id(a.get("campaign_id")), []).append(_id(a.get("id")))
        expanding: dict[str, list] = {}
        for (cid, gid), row in sorted(conf.items()):
            if cid not in search:
                continue
            crow = conf.get((cid, "")) or {}
            fue = _state(row.get("final_url_expansion_enabled"))
            if fue is None and gid:
                fue = _state(crow.get("final_url_expansion_enabled"))
            tc = _state(row.get("text_customization_enabled"))
            if tc is None and gid:
                tc = _state(crow.get("text_customization_enabled"))
            entity = {"campaign_id": cid, **({"ad_group_id": gid} if gid else {})}
            if not gid and row.get("url_inclusions"):
                url.observe(f"Campaign {cid}: URL inclusions exported at campaign scope; inclusions are ad-group-level",
                            campaign_id=cid, url_inclusions=row.get("url_inclusions"))
            if gid and row.get("url_exclusions"):
                url.observe(f"Ad group {gid}: URL exclusions exported at ad-group scope; exclusions are campaign-level",
                            campaign_id=cid, ad_group_id=gid, url_exclusions=row.get("url_exclusions"))
            if fue is None:
                url.partial(f"campaign {cid} ad group {gid or '-'}: final URL expansion state unknown")
                continue
            if fue is not True:
                continue
            expanding.setdefault(cid, []).append(gid or "campaign")
            explicit = not gid or _state(row.get("final_url_expansion_enabled")) is not None or \
                _state(row.get("text_customization_enabled")) is not None
            if tc is False and explicit:
                url.finding("url_expansion_without_text_customization", "Info", entity,
                            f"Final URL expansion is enabled while text customization is disabled ({cid}/{gid or '-'}); "
                            "expansion requires text customization, so the exported state is inconsistent or inactive",
                            evidence={"final_url_expansion_enabled": row.get("final_url_expansion_enabled"),
                                      "text_customization_enabled": row.get("text_customization_enabled"),
                                      "campaign_text_customization": crow.get("text_customization_enabled"),
                                      "snapshot_at": row.get("snapshot_at")},
                            recommendation="Confirm the live setting in the UI before relying on either state.",
                            uncertainty="Exported snapshot may lag the UI.")
            if gid and row.get("url_inclusions"):
                url.observe(f"Ad group {gid}: URL inclusions do not restrict expansion to the included pages while "
                            "expansion stays enabled", campaign_id=cid, ad_group_id=gid, url_inclusions=row.get("url_inclusions"))
        for cid in sorted(expanding):
            crow = conf.get((cid, "")) or {}
            scopes = expanding[cid]
            incl = sorted({str(r.get("url_inclusions")) for (c, g), r in conf.items() if c == cid and g and r.get("url_inclusions")})
            base = {"expanding_scopes": scopes, "url_inclusions": incl, "url_exclusions": crow.get("url_exclusions"),
                    "rule": "URL inclusions never restrict expansion to only included pages while expansion is enabled"}
            for g in approved.get(cid, []):
                ent = {"campaign_id": cid, "requirement_id": _id(g.get("requirement_id"))}
                ev = {**base, "landing_page_snapshot_ref": g.get("landing_page_snapshot_ref"), "owner": g.get("owner")}
                if g.get("allowed_domain_paths"):
                    url.review("url_expansion_vs_allowed_paths", ent,
                               f"Can final URL expansion in campaign {cid} select destinations outside the approved "
                               f"paths '{g.get('allowed_domain_paths')}' given the exclusions supplied?",
                               evidence={**ev, "allowed_domain_paths": g.get("allowed_domain_paths")},
                               outcomes=_breach_outcomes("final URL expansion"),
                               guidance="Exclusions must cover every disallowed path; inclusions do not restrict. "
                                        f"'{_BREACH}' needs proposal.evidence_ref to a selected-page record.")
                if g.get("mandatory_copy") and pins.get(cid):
                    url.review("mandatory_copy_pin_bypass", ent,
                               f"Campaign {cid} relies on RSA pins ({', '.join(pins[cid])}) while final URL expansion is "
                               f"enabled; can expanded-page selection bypass the mandatory copy '{g.get('mandatory_copy')}'?",
                               evidence={**ev, "mandatory_copy": g.get("mandatory_copy"), "pinned_ad_ids": pins[cid]},
                               outcomes=_breach_outcomes("final URL expansion/text customization"),
                               guidance="Pins are not a guarantee under expansion. "
                                        f"'{_BREACH}' needs proposal.evidence_ref to a served asset without the copy.")
        url.observe("Final URL expansion scopes", campaigns=len(expanding),
                    scopes=sum(len(v) for v in expanding.values()))

    # -- step 5: experiment evaluation (pre/post descriptive only) -----------------------------
    _experiments(ctx, conf, search)

    # -- step 6: opt-in per-feature test or no change -------------------------------------------
    prop = ctx.check("experiment_proposal", "Opt-in per-feature experiment or justified no change",
                     {CFG: ["campaign_id", "ad_group_id", "availability", "ai_max_enabled", *FEATURES]})
    if prop.runnable:
        if not conf:
            conf, _ = _latest(ctx.rows(CFG))
        saf_rows, saf_miss = _optional(ctx, SAFE, ["campaign_id", "business_goal", "owner", "approval_status"])
        if saf_miss:
            prop.partial("client risk floor/goal/owner unknown for proposals", saf_miss)
        approved = _approved_safeguards(saf_rows)
        n = 0
        for cid in sorted(search):
            crow = conf.get((cid, ""))
            if crow is None or _avail(crow.get("availability")) is not True:
                continue
            n += 1
            prop.review("feature_experiment_or_no_change", {"campaign_id": cid},
                        f"Should campaign {cid} run an opt-in single-feature AI Max test, or keep the current configuration?",
                        evidence={"ai_max_enabled": crow.get("ai_max_enabled"), **{f: crow.get(f) for f in FEATURES},
                                  "maturity": {"mature": ctx.mature, "note": ctx.maturity_note, "lag_days": ctx.lag_days},
                                  "safeguards": [{"requirement_id": g.get("requirement_id"), "business_goal": g.get("business_goal"),
                                                  "owner": g.get("owner")} for g in approved.get(cid, [])]},
                        outcomes={"propose_feature_test": {"severity": None, "recommendation":
                                                           "Request-only single-feature test; no uplift promise."},
                                  "no_change": {"severity": None, "recommendation": "Keep the current configuration; document why."}},
                        guidance="propose_feature_test needs proposal {feature (one of " + ", ".join(FEATURES) + "), "
                                 + ", ".join(_PROPOSAL_FIELDS) + ", duration_days}. Never enable all features.")
        prop.observe("Campaigns with evidenced availability offered a test/no-change decision", count=n)


def _arm_totals(rows: list[dict], ctx) -> dict:
    t = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0, "conversion_value": 0.0}
    unknown: set[str] = set()
    for r in rows:
        for k in t:
            v = ctx.money(r.get(k)) if k == "cost" else V.num(r.get(k))
            if v is None:
                unknown.add(k)
            else:
                t[k] += v
    return {k: (None if k in unknown else v) for k, v in t.items()}


def _experiments(ctx, conf: dict, search: dict) -> None:
    exp = ctx.check("experiment_evaluation", "Controlled experiment arms (pre/post is descriptive only)",
                    {EXP: ["experiment_id", "arm_id", "campaign_id", "date", "assignment_method", "impressions",
                           "clicks", "cost", "conversions", "conversion_value", "goal_id"]})
    for cid in sorted(search):
        crow = conf.get((cid, "")) or {}
        if crow.get("enabled_at"):
            exp.observe(f"Campaign {cid}: AI Max enabled_at {crow.get('enabled_at')}; any pre/post change is "
                        "descriptive and confounded", campaign_id=cid, enabled_at=crow.get("enabled_at"))
    if not exp.runnable:
        return
    if ctx.mature is not True:
        exp.partial(f"arm comparison disabled: maturity={ctx.mature} ({ctx.maturity_note}); descriptive totals only")
    gates = {k: ctx.params.get(k) for k in ("min_impressions", "min_clicks", "min_conversions")}
    by_exp: dict[str, dict[str, list]] = {}
    excluded = 0
    for r in ctx.rows(EXP):
        d = V.parse_date(r.get("date"))
        if d is None or ctx.period_end is None or d > ctx.period_end:
            excluded += 1
            continue
        by_exp.setdefault(_id(r.get("experiment_id")), {}).setdefault(_id(r.get("arm_id")), []).append(r)
    if excluded:
        exp.partial(f"{excluded} experiment rows with unknown date or after period end excluded")
    for eid in sorted(by_exp):
        arms = by_exp[eid]
        totals = {a: _arm_totals(arms[a], ctx) for a in sorted(arms)}
        methods = sorted({V.norm_text(r.get("assignment_method")) for rs in arms.values() for r in rs})
        goals = {a: sorted({_id(r.get("goal_id")) for r in arms[a]}) for a in sorted(arms)}
        controlled = bool(methods) and all(m in _CONTROLLED for m in methods)
        same_goals = len({tuple(g) for g in goals.values()}) == 1 and all(all(x for x in g) for g in goals.values())
        control = [a for a in sorted(arms) if not any(r.get("changed_features") for r in arms[a])]
        entity = {"experiment_id": eid}
        exp.observe(f"Experiment {eid} arm totals (descriptive)", experiment_id=eid, arms=totals,
                    assignment_methods=methods, goals=goals)
        reasons = ([] if len(arms) >= 2 else ["fewer than two arms"]) + \
                  ([] if controlled else [f"assignment {methods} is not a controlled split"]) + \
                  ([] if same_goals else ["arms use different or unknown goal_ids"])
        if reasons:
            exp.finding("experiment_not_causal", "Info", entity,
                        f"Experiment {eid} cannot support a causal AI Max claim: {'; '.join(reasons)}",
                        evidence={"arms": totals, "assignment_methods": methods, "goals": goals},
                        recommendation="Treat results as descriptive; design a controlled per-feature test if needed.",
                        uncertainty="Concurrent changes and allocation bias are uncontrolled.")
            continue
        if ctx.mature is not True:
            continue
        metrics = {"ctr": ("clicks", "impressions", "min_impressions"),
                   "cvr": ("conversions", "clicks", "min_clicks"),
                   "cpa": ("cost", "conversions", "min_conversions"),
                   "roas": ("conversion_value", "cost", "min_conversions")}
        compared, failed = {}, {}
        for m, (num, den, gate) in metrics.items():
            g = gates[gate].value
            basis = "conversions" if gate == "min_conversions" else den
            ok = g is not None and all((totals[a][basis] or 0) >= g and totals[a][basis] is not None for a in totals)
            if not ok:
                failed[m] = {a: totals[a][basis] for a in totals} | {"gate": g, "gate_param": gate}
                continue
            compared[m] = {a: V.ratio(totals[a][num], totals[a][den]) for a in totals}
        if not compared:
            exp.finding("experiment_sparse", "Info", entity,
                        f"Experiment {eid}: no metric passes the sample gate on every arm",
                        evidence={"failed_gates": failed, "window_end": ctx.period_end},
                        recommendation="Extend the test or accept a no-change decision; do not claim uplift.",
                        uncertainty="Count gates are not significance tests.")
            continue
        rel = {}
        if len(control) == 1:
            c = control[0]
            rel = {m: {a: V.ratio((v[a] or 0) - (v[c] or 0), v[c]) if v[a] is not None and v[c] is not None else None
                       for a in v if a != c} for m, v in compared.items()}
        exp.observe(f"Experiment {eid}: gated arm comparison", experiment_id=eid, metrics=compared,
                    relative_to_control=rel, control_arm=control[0] if len(control) == 1 else None,
                    gates={k: {"value": r.value, "source": r.source} for k, r in gates.items()}, failed_gates=failed)


def verify(ctx, item, decision) -> list[str]:
    """Rules: live breaches need proposal.evidence_ref; test proposals are single-feature and fully specified."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == _BREACH and not str(proposal.get("evidence_ref") or "").strip():
        return ["live breach needs proposal.evidence_ref pointing at supplied generated-content/page evidence"]
    if outcome == "propose_feature_test":
        problems = []
        feat = proposal.get("feature")
        if not isinstance(feat, str) or feat not in FEATURES:
            problems.append(f"proposal.feature must be exactly one of {list(FEATURES)}")
        missing = [f for f in _PROPOSAL_FIELDS if not str(proposal.get(f) or "").strip()]
        if missing:
            problems.append(f"proposal missing {missing}")
        dur = V.num(proposal.get("duration_days"))
        if dur is None or dur <= 0:
            problems.append("proposal.duration_days must be a positive number")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
