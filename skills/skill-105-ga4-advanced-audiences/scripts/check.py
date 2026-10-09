"""check.py — skill-105 deterministic GA4 audience provenance, event availability, sync and planned-definition review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-105-ga4-advanced-audiences/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #111 Create remarketing lists in Analytics from Google Sheet (Dmytro Tonkikh, gist) — clean-room
         reimplementation of its planned-list behaviour (name, page/segment rule, membership duration, linked Ads
         account) as READ-ONLY comparison: profile.ga4_audience_plan vs ga4_audience_definitions/sync; creation
         and linking are never performed, only owner-review proposals.
rules:   GA4 origin = ga4_audience_sync row with source_property_verified true; list names/types never prove it.
         Intended audience = ga4_audience_definitions.intended_use not empty/none, OR a profile.ga4_audience_plan
         entry {property_id, ga4_audience_id, membership_days?, destination_account_id?} for this account.
         'After normal processing' = created_at + profile.ga4_audience_processing_days <= ctx.as_of; unknown
         processing window or created_at → Info only (pending/unknown), never Warning.
         Event absence Warning needs a processing_mature row with event_count 0 for the expected event;
         a missing row is Info (unknown). Zero list size alone is an observation, never a failure.
         Plan membership_days ≠ definition → provisional Info + review (Warning outcome); a planned audience
         absent from a manifest-complete definitions table → Info (missing optional audience).
         Critical only via review 'material_block_evidenced' with proposal.evidence_ref.
         Performance rows are descriptive only (overlapping lists, no causal lift, no cross-list sums).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

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

SKILL = "skill-105-ga4-advanced-audiences"
VERSION = "1.0.0"

GDEF = "external/ga4_audience_definitions"
GSYNC = "external/ga4_audience_sync"
GEV = "external/ga4_event_availability"
GPERF = "custom/ga4_audience_performance"
_NOT_INTENDED = {"", "none", "no", "not intended", "not_intended"}
_SYNC_BAD = {"failed", "error", "removed", "closed", "rejected"}
_SUPPRESSED = {"suppressed", "privacy suppressed", "privacy_suppressed", "restricted"}
_ELIGIBLE = {"eligible", "active"}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _acct(v) -> str:
    return _s(v).replace("-", "")


def _mode(v) -> str | None:
    s = V.norm_text(v)
    if "signal" in s:
        return "SIGNAL"
    if "exclu" in s:
        return "EXCLUSION"
    if "observ" in s:
        return "OBSERVATION"
    if "target" in s:
        return "TARGETING"
    return None


def _critical(chk, key, entity, question, ev):
    chk.review(key, entity, question, evidence=ev,
               outcomes={"material_block_evidenced": {"severity": "Critical", "recommendation":
                                                      "Prioritize the sync-owner fix; cite delivery/objective impact."},
                         "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
               guidance="Critical needs proposal.evidence_ref to supplied material-impact evidence.")


def run(ctx) -> None:
    """Run GA4 origin, intent, definition/event, plan-fit, sync, campaign-use, predictive, performance and owner checks.

    Rules:   Definition/event and sync checks are skipped without activation intent. Warning only for mature zero event
             counts or absent parameters, unverified destination, and missing (certified) or failed sync after
             ga4_audience_processing_days; otherwise Info. Plan mismatch, use-vs-intent, Critical impact → ai_review;
             zero list size and performance rows (immature/other-currency excluded) are observe-only.
    """
    me = _acct(ctx.account_id)
    defs: dict[tuple[str, str], dict] = {}
    for r in ctx.rows(GDEF):
        defs.setdefault((_s(r.get("property_id")), _s(r.get("ga4_audience_id"))), r)
    plan = [p for p in (ctx.profile.get("ga4_audience_plan") or []) if isinstance(p, dict)]
    plan_mine = [p for p in plan if not _s(p.get("destination_account_id")) or _acct(p.get("destination_account_id")) == me]
    sync_rows: dict[tuple[str, str], list[dict]] = {}
    for r in ctx.rows(GSYNC):
        sync_rows.setdefault((_s(r.get("property_id")), _s(r.get("ga4_audience_id"))), []).append(r)

    # -- step 1: provenance
    og = ctx.check("ga4_origin", "GA4 origin through verified property/audience/list mappings",
                   {"audiences": ["list_id"],
                    GSYNC: ["property_id", "ga4_audience_id", "account_id", "user_list_id", "source_property_verified"]})
    origin: dict[str, tuple[str, str]] = {}
    if og.runnable:
        for key, rows in sorted(sync_rows.items()):
            for r in rows:
                if _acct(r.get("account_id")) == me and V.boolean(r.get("source_property_verified")) is True \
                        and _s(r.get("user_list_id")):
                    origin[_s(r.get("user_list_id"))] = key
        lists = sorted({_s(r.get("list_id")) for r in ctx.rows("audiences") if _s(r.get("list_id"))})
        og.observe("GA4 provenance", verified_ga4_lists=sorted(origin),
                   unknown_origin_lists=[x for x in lists if x not in origin],
                   note="RULE_BASED/LOGICAL types and names do not establish GA4 origin")

    # -- step 2: activation intent (link state → 106)
    ai = ctx.check("activation_intent", "Desired GA4 audience activation", {GDEF: ["property_id", "ga4_audience_id",
                                                                                 "intended_use"]})
    intended: dict[tuple[str, str], str] = {}
    if ai.runnable:
        for key, r in sorted(defs.items()):
            if V.norm_text(r.get("intended_use")) not in _NOT_INTENDED:
                intended[key] = _s(r.get("intended_use"))
        for p in plan_mine:
            key = (_s(p.get("property_id")), _s(p.get("ga4_audience_id")))
            if key[1]:
                intended.setdefault(key, _s(p.get("intended_use")) or "profile.ga4_audience_plan")
        ai.observe("Activation intent", intended=[f"{k[0]}/{k[1]}" for k in sorted(intended)],
                   not_intended=[f"{k[0]}/{k[1]}" for k in sorted(set(defs) - set(intended))],
                   note="no GA4 linkage is not a defect when GA4 audiences are not intended; link state via 106")

    # -- step 3: definitions and events
    de = ctx.check("definition_events", "Behavioral rules, duration, exclusions and event availability",
                   {GDEF: ["property_id", "ga4_audience_id", "definition_expression", "expected_event_names",
                           "membership_days", "privacy_restriction"],
                    GEV: ["property_id", "event_name", "event_count", "required_parameter_presence_rate",
                          "processing_mature"]})
    flagged: dict[tuple[str, str], list[str]] = {}
    if de.runnable and not ai.runnable:
        de.skip("activation intent unavailable", ai.missing)
    elif de.runnable:
        evrows: dict[tuple[str, str], list[dict]] = {}
        for r in ctx.rows(GEV):
            evrows.setdefault((_s(r.get("property_id")), V.norm_text(r.get("event_name"))), []).append(r)
        for key in sorted(intended):
            d = defs.get(key)
            if d is None:
                continue
            ent = {"property_id": key[0], "ga4_audience_id": key[1]}
            for evn in sorted({V.norm_text(x) for x in V.split_list(d.get("expected_event_names"))}):
                rows = evrows.get((key[0], evn), [])
                mature = [r for r in rows if V.boolean(r.get("processing_mature")) is True]
                counts = [V.num(r.get("event_count")) for r in mature]
                ev = {"event_name": evn, "rows": len(rows), "mature_rows": len(mature), "event_counts": counts,
                      "windows": [[r.get("window_start"), r.get("window_end")] for r in mature],
                      "consent_scope": sorted({_s(r.get("consent_scope")) for r in rows if _s(r.get("consent_scope"))}),
                      "privacy_restriction": d.get("privacy_restriction")}
                e2 = {**ent, "event_name": evn}
                if not mature or any(c is None for c in counts):
                    de.finding("event_evidence_incomplete", "Info", e2,
                               f"Audience {key[1]}: availability of expected event '{evn}' unknown or not yet processed",
                               evidence=ev, recommendation="Supply mature aggregate event diagnostics.",
                               uncertainty="Unknown is not absent.")
                    continue
                if sum(counts) == 0:
                    flagged.setdefault(key, []).append(f"event {evn} absent")
                    de.finding("expected_event_absent", "Warning", e2,
                               f"Audience {key[1]}: expected event '{evn}' recorded 0 times in mature windows",
                               evidence=ev, recommendation="Definition/tag owner to fix the event or the definition.",
                               uncertainty="Aggregate diagnostics; consent scope may limit collection.")
                    continue
                rates = [ctx.rate(r.get("required_parameter_presence_rate")) for r in mature]
                if rates and all(x == 0 for x in rates if x is not None) and any(x is not None for x in rates):
                    flagged.setdefault(key, []).append(f"parameters of {evn} absent")
                    de.finding("required_parameter_absent", "Warning", e2,
                               f"Audience {key[1]}: '{evn}' occurs but required parameters are never present",
                               evidence={**ev, "presence_rates": rates},
                               recommendation="Fix parameter collection or the rule condition.",
                               uncertainty="Parameter presence as aggregated by the source.")
            if not _s(d.get("membership_days")):
                de.partial(f"audience {key[1]}: membership_days unknown")

    # -- step 4: planned definitions (index #111) versus actual
    od = ctx.check("objective_fit", "Required/planned definitions versus actual definitions",
                   {GDEF: ["property_id", "ga4_audience_id", "membership_days", "intended_use", "campaign_objective"]})
    if od.runnable:
        if not plan:
            od.partial("no profile.ga4_audience_plan: objective fit beyond literal intent is not assessed")
        t = ctx.table(GDEF)
        certified = t.complete is True and not t.truncated
        for p in sorted(plan_mine, key=lambda p: (_s(p.get("property_id")), _s(p.get("ga4_audience_id")))):
            key = (_s(p.get("property_id")), _s(p.get("ga4_audience_id")))
            ent = {"property_id": key[0], "ga4_audience_id": key[1]}
            d = defs.get(key)
            if d is None:
                if certified:
                    od.finding("planned_audience_missing", "Info", ent,
                               f"Planned GA4 audience {key[1]} is absent from the certified definition snapshot",
                               evidence={"plan": p}, recommendation="Owner review of whether to define it (no creation "
                                                                    "here; link state via 106).",
                               uncertainty="Missing optional audience; not a defect.")
                else:
                    od.partial(f"planned audience {key[1]} not found; definition inventory not certified complete")
                continue
            want, have = V.num(p.get("membership_days")), V.num(d.get("membership_days"))
            if want is not None and have is not None and want != have:
                ev = {"planned_membership_days": want, "actual_membership_days": have, "plan": p,
                      "owner": d.get("owner")}
                prov = od.finding("planned_definition_differs", "Info", ent,
                                  f"Audience {key[1]}: membership {have:g} days vs planned {want:g}", evidence=ev,
                                  recommendation="Confirm which duration is current with the owner.",
                                  uncertainty="Plan may be stale.")
                od.review("planned_definition_differs", ent,
                          f"Is audience {key[1]}'s {have:g}-day membership a reproducible mismatch with the approved "
                          f"{want:g}-day plan?", evidence=ev, provisional=prov,
                          outcomes={"definition_mismatch": {"severity": "Warning", "recommendation":
                                                            "Owner-reviewed definition correction."},
                                    "intentional_change": {"severity": None, "recommendation": "Update the plan."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}},
                          guidance="Judge only against the plan and profile objectives.")

    # -- step 5: sync and eligibility after processing
    se = ctx.check("sync_eligibility", "Sync and network eligibility after normal processing",
                   {GSYNC: ["property_id", "ga4_audience_id", "account_id", "user_list_id",
                            "destination_account_verified", "sync_status", "last_observed_sync", "search_size",
                            "display_size", "eligibility_by_network", "suppression_status"],
                    GDEF: ["created_at"]})
    if se.runnable and not ai.runnable:
        se.skip("activation intent unavailable", ai.missing)
    elif se.runnable:
        proc = V.integer(ctx.profile.get("ga4_audience_processing_days"))
        if proc is None or proc < 0:
            se.partial("profile.ga4_audience_processing_days unset: sync failures stay Info (normal processing "
                       "window unknown)")
        t = ctx.table(GSYNC)
        certified = t.complete is True and not t.truncated
        for key in sorted(intended):
            d = defs.get(key) or {}
            created = V.parse_date(d.get("created_at"))
            elapsed = (proc is not None and proc >= 0 and created is not None and ctx.as_of is not None
                       and created + timedelta(days=proc) <= ctx.as_of)
            ent = {"property_id": key[0], "ga4_audience_id": key[1]}
            rows = [r for r in sync_rows.get(key, []) if _acct(r.get("account_id")) == me]
            base = {"created_at": d.get("created_at"), "processing_days": proc, "as_of": str(ctx.as_of),
                    "processing_elapsed": elapsed}
            if not rows:
                if elapsed and certified:
                    flagged.setdefault(key, []).append("not synced")
                    se.finding("intended_audience_not_synced", "Warning", ent,
                               f"Intended audience {key[1]} has no sync to account {ctx.account_id} after processing",
                               evidence=base, recommendation="Sync owner to review the link (106) and audience export.",
                               uncertainty="Certified sync snapshot; policy restrictions may apply.")
                    _critical(se, "intended_audience_not_synced", ent,
                              f"Does the missing sync of {key[1]} cause material delivery/objective failure?", base)
                else:
                    se.finding("sync_pending_or_unknown", "Info", ent,
                               f"Intended audience {key[1]}: no sync evidence yet (new, pending or uncertified)",
                               evidence=base, recommendation="Re-check after the processing window.",
                               uncertainty="New or unobserved lists may not be available yet.")
                continue
            for r in sorted(rows, key=lambda r: _s(r.get("user_list_id"))):
                e2 = {**ent, "user_list_id": _s(r.get("user_list_id"))}
                ev = {**base, **{k: r.get(k) for k in ("sync_status", "last_observed_sync", "search_size",
                                                       "display_size", "eligibility_by_network", "suppression_status",
                                                       "destination_account_verified", "source_reference")}}
                status = V.norm_text(r.get("sync_status"))
                if V.boolean(r.get("destination_account_verified")) is False:
                    flagged.setdefault(key, []).append("destination unverified")
                    se.finding("destination_not_verified", "Warning", e2,
                               f"Audience {key[1]} → list {e2['user_list_id']}: destination account not verified",
                               evidence=ev, recommendation="Verify the linked destination account with the owner.",
                               uncertainty="Configuration evidence as supplied.")
                if status in _SYNC_BAD:
                    if elapsed:
                        flagged.setdefault(key, []).append("sync failed")
                        se.finding("sync_failed", "Warning", e2,
                                   f"Audience {key[1]}: sync status '{r.get('sync_status')}' after normal processing",
                                   evidence=ev, recommendation="Sync owner review with diagnostics.",
                                   uncertainty="Status snapshot.")
                        _critical(se, "sync_failed", e2, f"Does the failed sync of {key[1]} cause material "
                                                         f"delivery/objective failure?", ev)
                    else:
                        se.finding("sync_pending_or_unknown", "Info", e2,
                                   f"Audience {key[1]}: sync '{r.get('sync_status')}' within/unknown processing window",
                                   evidence=ev, recommendation="Re-check after processing.",
                                   uncertainty="New list.")
                elif V.norm_text(r.get("suppression_status")) in _SUPPRESSED:
                    se.finding("suppressed_list", "Info", e2, f"Audience {key[1]}: list is privacy-suppressed",
                               evidence=ev, recommendation="No action unless the objective requires it.",
                               uncertainty="Suppression is expected for small/privacy-limited lists.")
                else:
                    se.observe(f"Audience {key[1]} → {e2['user_list_id']}: sync observed", **e2,
                               search_size=V.num(r.get("search_size")), display_size=V.num(r.get("display_size")),
                               note="zero size alone does not prove failure")

    # -- step 6: campaign use
    cu = ctx.check("campaign_use", "Campaign use and targeting/observation/exclusion mode",
                   {"audiences": ["list_id", "campaign_id", "mode"]})
    if cu.runnable:
        for r in sorted(ctx.rows("audiences"), key=lambda r: (_s(r.get("list_id")), _s(r.get("campaign_id")))):
            lid, cid = _s(r.get("list_id")), _s(r.get("campaign_id"))
            if lid not in origin or not cid:
                continue
            key = origin[lid]
            observed = _mode(r.get("mode"))
            want = _mode(intended.get(key, ""))
            cu.observe(f"GA4 list {lid} used in {cid}", list_id=lid, campaign_id=cid, mode=observed,
                       intended_use=intended.get(key))
            if want and observed and want != observed:
                cu.review("use_differs_from_intent", {"list_id": lid, "campaign_id": cid},
                          f"GA4 list {lid} is used as {observed} in {cid} but intended as {want}. Acceptable?",
                          evidence={"observed_mode": observed, "intended_use": intended.get(key)},
                          outcomes={"use_differs_from_intent": {"severity": "Info", "recommendation":
                                                                "Owner to confirm or realign the use."},
                                    "acceptable": {"severity": None, "recommendation": "No change."}},
                          guidance="An audience signal is not a hard targeting restriction.")

    # -- step 7: predictive eligibility
    pr = ctx.check("predictive_eligibility", "Predictive options with actual property eligibility",
                   {GDEF: ["ga4_audience_id", "predictive_eligibility_status"]})
    if pr.runnable:
        for key, d in sorted(defs.items()):
            st = V.norm_text(d.get("predictive_eligibility_status"))
            if not st:
                continue
            ent = {"property_id": key[0], "ga4_audience_id": key[1]}
            if key in intended and st not in _ELIGIBLE:
                pr.finding("predictive_not_eligible", "Info", ent,
                           f"Predictive audience {key[1]} intended but property status '{d.get('predictive_eligibility_status')}'",
                           evidence={"status": d.get("predictive_eligibility_status")},
                           recommendation="Keep as hypothesis until eligibility is met.",
                           uncertainty="Ineligible/new predictive list; no arbitrary thresholds applied.")
            else:
                pr.observe(f"Predictive audience {key[1]}: status {st}", **ent, intended=key in intended)

    # -- step 8: descriptive performance
    pa = ctx.check("performance_appendix", "Descriptive performance appendix (no causal comparison)",
                   {GPERF: ["campaign_id", "user_list_id", "mode", "network", "impressions", "clicks", "cost",
                            "conversions", "conversion_value", "currency", "overlap_known", "reporting_mature"]})
    if pa.runnable:
        if ctx.mature is not True:
            pa.partial(f"descriptive totals only: maturity={ctx.mature}")
        agg: dict[tuple, list[float]] = {}
        skipped = 0
        for r in ctx.rows(GPERF):
            if (_s(r.get("currency")).upper() not in ("", ctx.currency or "")
                    or V.boolean(r.get("reporting_mature")) is not True):
                skipped += 1
                continue
            vals = [V.num(r.get("impressions")), V.num(r.get("clicks")), ctx.money(r.get("cost")),
                    V.num(r.get("conversions"))]
            if any(v is None for v in vals):
                skipped += 1
                continue
            k = (_s(r.get("campaign_id")), _s(r.get("user_list_id")), V.norm_text(r.get("mode")),
                 V.norm_text(r.get("network")))
            acc = agg.setdefault(k, [0.0, 0.0, 0.0, 0.0])
            for i, v in enumerate(vals):
                acc[i] += v
        if skipped:
            pa.partial(f"{skipped} rows excluded (immature, other currency or unknown metrics)")
        for (cid, lid, mode, net), (impr, clicks, cost, conv) in sorted(agg.items()):
            pa.observe(f"{cid}/{lid} {mode}/{net} (overlapping, descriptive)", campaign_id=cid, user_list_id=lid,
                       impressions=impr, clicks=clicks, cost=cost, conversions=conv, ctr=V.ratio(clicks, impr),
                       cvr=V.ratio(conv, clicks), cpa=V.ratio(cost, conv))

    # -- step 9: owner review proposals
    ow = ctx.check("owner_review", "Definition or sync-owner review proposals")
    if not (de.runnable or od.runnable or se.runnable):
        ow.skip("no definition, plan or sync evaluation ran", sorted(set(de.missing + od.missing + se.missing)))
    else:
        ow.observe("Owner review proposals (no creation, linking or publishing)",
                   proposals=[{"property_id": k[0], "ga4_audience_id": k[1], "issues": sorted(set(v)),
                               "owner": (defs.get(k) or {}).get("owner")} for k, v in sorted(flagged.items())])


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcome needs proposal.evidence_ref."""
    if decision.get("outcome") == "material_block_evidenced" and not _s((decision.get("proposal") or {})
                                                                        .get("evidence_ref")):
        return ["material_block_evidenced needs proposal.evidence_ref pointing at supplied impact evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
