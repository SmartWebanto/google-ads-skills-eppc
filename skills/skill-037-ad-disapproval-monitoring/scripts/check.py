"""check.py — skill-037 deterministic ad policy/eligibility triage with dated review evidence.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-037-ad-disapproval-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #2 Disapproved Ads Alerts (nilsrooijmans.com) — clean-room reimplementation of detecting disapproved
           ads in enabled scope; emails/alerts NOT integrated (recommend-only, no sending)
         index #3 Past Violations Alert (nilsrooijmans.com) — clean-room: past DISAPPROVED events per policy topic
           from custom/ad_policy_history, reported as observations
         index #17 Email alerts for policy issues on ads and ad extensions (Aaron Weiner) — ad-level policy issues
           integrated; extension/asset policy refused: 037 declares no assets input
         index #18 MCC Level check for Disapproved Ads (Google) — MCC scope via adsrun per-account partitioning only
         index #70 PMax Disapproved Entities Alerts (nilsrooijmans.com) — PMax ads in export/ads are covered; asset-group
           entities refused: the 037 policy grain is ad_id
rules:   Paused/removed scope is a work queue, never an active delivery blocker (Info at most).
         approval_status and review_status stay separate; APPROVED_LIMITED/AREA_OF_INTEREST_ONLY may serve.
         Potentially eligible = enabled ad whose approval is APPROVED, limited or under review; unknown approval
         blocks the silenced-group conclusion. Silenced group (Warning) needs a manifest-complete ads inventory.
         Critical only via ai_review 'material_loss_confirmed' with proposal.evidence_ref (serving diagnosis).
         Review age: exact only from the latest submitted/edited event in a manifest-complete history; otherwise a
         lower bound → Info; missing history file → observation only. No fixed seven-day rule.
         Policy source: custom/ad_policy_status when present (Policy Manager incl. zero-impression ads), else
         export/ads approval_status/policy_topics (coverage partial).
         Historical spend is prioritization context only; never lost revenue. No appeal/pause actions proposed
         as automatic (verify rejects proposal.action submit_appeal|pause|remove).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial deterministic check
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

SKILL = "skill-037-ad-disapproval-monitoring"
VERSION = "1.0.0"

STATUS = "custom/ad_policy_status"
HISTORY = "custom/ad_policy_history"
STATUS_COLS = ["campaign_id", "ad_group_id", "ad_id", "snapshot_at", "approval_status", "review_status",
               "policy_topics", "eligible_geographies_or_formats", "serving_status", "source_ref"]
HIST_COLS = ["ad_id", "event_id", "event_at", "event_type", "prior_status", "new_status", "affected_policy_topic"]
LIMITED = ("APPROVED_LIMITED", "AREA_OF_INTEREST_ONLY", "LIMITED")
UNDER_REVIEW = ("REVIEW_IN_PROGRESS", "UNDER_REVIEW", "UNDER_APPEAL", "ELIGIBLE_MAY_SERVE")
FORBIDDEN_ACTIONS = ("submit_appeal", "pause", "remove")


def _up(v) -> str:
    return str(v or "").strip().upper()


def _scope(*statuses) -> str:
    s = [_up(x) for x in statuses]
    if any(not x for x in s):
        return "unknown"
    if any(x == "REMOVED" for x in s):
        return "removed"
    if all(x == "ENABLED" for x in s):
        return "active"
    return "paused"


def _approval_class(approval: str, review: str) -> str:
    if approval == "DISAPPROVED":
        return "disapproved"
    if approval in LIMITED:
        return "limited"
    if approval == "APPROVED":
        return "approved"
    if approval in UNDER_REVIEW or review in UNDER_REVIEW:
        return "under_review"
    return "unknown"


def _topics(v) -> list[str]:
    return sorted(set(V.split_list(v, (" | ", ";", "|", ","))))


def run(ctx) -> None:
    """Run ad policy triage: status spine, limited serving, silenced groups, serving diagnosis, review age, queue.

    Rules:   Missing campaigns/ad_groups/ads spine skips all 7 checks; no policy status skips group/topic/queue.
             Paused/removed disapproved/limited ads → Info only; group_no_eligible_ads Warning needs zero eligible,
             zero unknown approvals and complete ads+ad_groups manifests; Critical only via ai_review
             material_loss_confirmed. Review age Warning only via ai_review on an exact complete-history age; else Info.
    """
    spine = ctx.check("scope_join", "Policy rows joined to all ads and parent statuses",
                      {"campaigns": ["id", "status"], "ad_groups": ["id", "campaign_id", "status"],
                       "ads": ["id", "campaign_id", "ad_group_id", "type", "status"]})
    names = ("status_vocabulary", "group_eligibility", "serving_diagnosis", "review_age", "topic_grouping",
             "resolution_queue", "owner_tracking")
    titles = ("Approval and review statuses kept separate", "Potentially eligible ads per active ad group",
              "Serving diagnosis for silenced scope", "Review age from submission/edit history",
              "Repeated policy topics by exact topic and scope", "Correction/evidence/appeal-review queue",
              "Owner, next step and required platform evidence")
    if not spine.runnable:
        for cid, t in zip(names, titles):
            ctx.check(cid, t).skip("ad/parent status spine unavailable", spine.missing)
        return
    camp = {str(c.get("id")): c for c in ctx.rows("campaigns")}
    groups = {str(g.get("id")): g for g in ctx.rows("ad_groups")}
    ads = {str(a.get("id")): a for a in ctx.rows("ads")}
    ads_complete = ctx.table("ads").complete is True and ctx.table("ad_groups").complete is True

    # policy source
    pol_t = ctx.table(STATUS)
    use_custom = pol_t is not None and not pol_t.missing(["ad_id", "approval_status", "review_status", "policy_topics"])
    policy: dict[str, dict] = {}
    if use_custom:
        for r in sorted(ctx.rows(STATUS), key=lambda r: (str(r.get("ad_id")), str(r.get("snapshot_at")))):
            policy[str(r.get("ad_id"))] = r  # latest snapshot per ad wins (sorted ascending)
    else:
        for aid, a in ads.items():
            policy[aid] = {"approval_status": a.get("approval_status"), "review_status": a.get("review_status"),
                           "policy_topics": a.get("policy_topics")}

    ledger: dict[str, dict] = {}
    orphans = sorted(set(policy) - set(ads))
    for aid in sorted(ads):
        a = ads[aid]
        gid, cid = str(a.get("ad_group_id")), str(a.get("campaign_id"))
        g, c = groups.get(gid), camp.get(cid)
        p = policy.get(aid, {})
        approval, review = _up(p.get("approval_status")), _up(p.get("review_status"))
        ledger[aid] = {"ad_id": aid, "ad_group_id": gid, "campaign_id": cid, "type": a.get("type"),
                       "scope": _scope(a.get("status"), (g or {}).get("status"), (c or {}).get("status")),
                       "approval_status": approval or None, "review_status": review or None,
                       "class": _approval_class(approval, review), "topics": _topics(p.get("policy_topics")),
                       "serving_status": p.get("serving_status"), "serving_reason": p.get("serving_reason"),
                       "eligible_geographies_or_formats": p.get("eligible_geographies_or_formats"),
                       "source_ref": p.get("source_ref"), "snapshot_at": p.get("snapshot_at")}
    by_scope: dict[str, int] = {}
    for x in ledger.values():
        by_scope[x["scope"]] = by_scope.get(x["scope"], 0) + 1
    spine.observe("Ad eligibility ledger by parent scope", **by_scope, orphan_policy_rows=len(orphans),
                  policy_source=STATUS if use_custom else "ads.approval_status/policy_topics")
    if orphans:
        spine.partial(f"{len(orphans)} policy rows without a matching ad in export/ads: {orphans[:10]}")
    for aid, x in sorted(ledger.items()):
        if x["scope"] in ("paused", "removed") and x["class"] in ("disapproved", "limited"):
            spine.finding("paused_affected_ad", "Info", {"campaign_id": x["campaign_id"], "ad_group_id": x["ad_group_id"],
                                                        "ad_id": aid},
                          f"{x['scope'].capitalize()} ad {aid} is {x['approval_status']} ({', '.join(x['topics']) or 'no topic'}): "
                          f"work queue, not an active delivery blocker",
                          evidence={"scope": x["scope"], "approval_status": x["approval_status"], "topics": x["topics"]},
                          recommendation="Fix only if the ad is planned for reactivation.",
                          uncertainty="Paused inventory does not serve; no delivery impact inferred.")

    # step 2
    vocab_needs = ({STATUS: ["ad_id", "approval_status", "review_status", "policy_topics"]} if use_custom
                   else {"ads": ["approval_status"]})
    voc = ctx.check("status_vocabulary", titles[0], vocab_needs)
    if voc.runnable:
        if not use_custom:
            miss = [f"{STATUS} (file)"] if pol_t is None else [
                f"{STATUS}:{c}" for c in pol_t.missing(["ad_id", "approval_status", "review_status", "policy_topics"])]
            miss += [f"ads:{c}" for c in ctx.table("ads").missing(["policy_topics"])]
            voc.partial("Policy Manager status export missing/unusable: review status and zero-impression coverage "
                        "unknown; using export/ads approval_status", miss)
        tally: dict[str, int] = {}
        for x in ledger.values():
            k = f"{x['approval_status']}|{x['review_status']}"
            tally[k] = tally.get(k, 0) + 1
        voc.observe("Approval|review status combinations (platform vocabulary preserved)", combinations=tally)
        for aid, x in sorted(ledger.items()):
            if x["scope"] != "active" or x["class"] != "limited":
                continue
            ent = {"campaign_id": x["campaign_id"], "ad_group_id": x["ad_group_id"], "ad_id": aid}
            ev = {"approval_status": x["approval_status"], "topics": x["topics"],
                  "eligible_geographies_or_formats": x["eligible_geographies_or_formats"],
                  "service_area": ctx.profile.get("service_area"), "market": ctx.profile.get("market"),
                  "source_ref": x["source_ref"]}
            prov = voc.finding("limited_serving", "Info", ent,
                               f"Active ad {aid} is {x['approval_status']} for {', '.join(x['topics']) or 'unstated topic'}: "
                               f"may still serve in allowed locations/formats", evidence=ev,
                               recommendation="Check whether the restriction removes intended markets or formats.",
                               uncertainty="Limited serving can be permissible.")
            voc.review("limited_serving", ent,
                       f"Does the limitation on ad {aid} remove intended coverage (markets/formats in the profile)?",
                       evidence=ev, provisional=prov,
                       outcomes={"coverage_affected": {"severity": "Warning", "recommendation":
                                                       "Correct the policy issue or add a compliant ad for the lost scope."},
                                 "permissible": {"severity": None, "recommendation": "No action; limited serving is acceptable."},
                                 "uncertain": {"severity": "Info", "recommendation": "Confirm intended markets with the owner."}},
                       guidance="Compare eligible_geographies_or_formats with approved service_area/market only.")

    # step 3
    grp = ctx.check("group_eligibility", titles[1],
                    {"ads": ["id", "ad_group_id", "status"], "ad_groups": ["id", "status"]})
    silenced: dict[str, dict] = {}
    if grp.runnable and not voc.runnable:
        grp.skip("policy status unavailable", voc.missing)
    elif grp.runnable:
        if not ads_complete:
            grp.partial("ads/ad_groups inventory not manifest-complete: a group cannot be called silenced")
        by_g: dict[str, list[dict]] = {}
        for x in ledger.values():
            by_g.setdefault(x["ad_group_id"], []).append(x)
        for gid in sorted(groups):
            g = groups[gid]
            cid = str(g.get("campaign_id"))
            if _scope(g.get("status"), (camp.get(cid) or {}).get("status")) != "active":
                continue
            active = [x for x in by_g.get(gid, []) if x["scope"] == "active"]
            counts = {k: sum(1 for x in active if x["class"] == k) for k in
                      ("approved", "limited", "under_review", "disapproved", "unknown")}
            eligible = counts["approved"] + counts["limited"] + counts["under_review"]
            grp.observe(f"Ad group {gid}: {eligible} potentially eligible of {len(active)} enabled ads",
                        campaign_id=cid, ad_group_id=gid, **counts, ad_types=sorted({str(x["type"]) for x in active}))
            ent = {"campaign_id": cid, "ad_group_id": gid}
            dis = [x for x in active if x["class"] == "disapproved"]
            if not dis:
                continue
            ev = {"enabled_ads": len(active), **counts, "disapproved_ads": [x["ad_id"] for x in dis],
                  "topics": sorted({t for x in dis for t in x["topics"]}), "inventory_complete": ads_complete}
            if eligible == 0 and counts["unknown"] == 0 and ads_complete:
                silenced[gid] = {**ent, **ev}
                grp.finding("group_no_eligible_ads", "Warning", ent,
                            f"Active ad group {gid}: all {len(active)} enabled ads are DISAPPROVED — no potentially "
                            f"eligible ad in a complete inventory", evidence=ev,
                            recommendation="Correct the disapproved ads or add a compliant ad; see resolution queue.",
                            uncertainty="Status snapshot only; material impact needs a serving diagnosis (Critical path).")
            else:
                for x in dis:
                    aent = {**ent, "ad_id": x["ad_id"]}
                    aev = {**ev, "ad_topics": x["topics"], "source_ref": x["source_ref"]}
                    prov = grp.finding("active_disapproval", "Info", aent,
                                       f"Enabled ad {x['ad_id']} in active group {gid} is DISAPPROVED "
                                       f"({', '.join(x['topics']) or 'no topic'}); {eligible} other ad(s) potentially eligible",
                                       evidence=aev, recommendation="Review whether the ad carries unique coverage.",
                                       uncertainty="Other eligible ads may cover the same queries and messages.")
                    grp.review("active_disapproval", aent,
                               f"Does the disapproval of ad {x['ad_id']} remove intended coverage "
                               f"(unique offer, market, format) not served by the {eligible} other eligible ad(s)?",
                               evidence=aev, provisional=prov,
                               outcomes={"coverage_affected": {"severity": "Warning", "recommendation":
                                                               "Correct or replace the disapproved ad."},
                                         "redundant": {"severity": "Info", "recommendation":
                                                       "Low priority: other ads cover the scope."},
                                         "uncertain": {"severity": "Info", "recommendation":
                                                       "Ask the owner what the ad uniquely covers."}},
                               guidance="Unknown approvals count as unresolved, not as eligible.")

    # step 4
    diag = ctx.check("serving_diagnosis", titles[2], {STATUS: ["ad_id", "serving_status",
                                                               "eligible_geographies_or_formats", "source_ref"]})
    if diag.runnable:
        cm = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
        am = {(str(r.get("ad_group_id")), str(r.get("ad_id"))): r for r in ctx.rows("ad_metrics")} \
            if ctx.table("ad_metrics") and not ctx.table("ad_metrics").missing(["ad_id", "ad_group_id"]) else {}
        for gid, s in sorted(silenced.items()):
            rows = [ledger[a] for a in s["disapproved_ads"]]
            refs = sorted({str(x["source_ref"]) for x in rows if x["source_ref"]})
            m = cm.get(s["campaign_id"], {})
            diag.review("group_no_eligible_ads", {"campaign_id": s["campaign_id"], "ad_group_id": gid},
                        f"Does current serving diagnosis prove MATERIAL loss of all eligible delivery for required "
                        f"scope in ad group {gid}?",
                        evidence={"serving": [{k: x[k] for k in ("ad_id", "serving_status", "serving_reason",
                                                                 "eligible_geographies_or_formats", "snapshot_at")}
                                              for x in rows], "source_refs": refs,
                                  "ad_metrics": {x["ad_id"]: {k: (am.get((gid, x["ad_id"])) or {}).get(k)
                                                              for k in ("impressions", "clicks", "cost")} for x in rows},
                                  "campaign_context": {k: m.get(k) for k in ("impressions", "clicks", "cost")},
                                  "window": [ctx.period_start, ctx.period_end]},
                        outcomes={"material_loss_confirmed": {"severity": "Critical", "recommendation":
                                                              "Prioritize correction; cite the diagnosis and business scope."},
                                  "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
                        guidance="Low historical impressions alone cannot identify cause. material_loss_confirmed needs "
                                 "proposal.evidence_ref (one of source_refs) and the required business scope.")
        diag.observe("Silenced groups sent to serving-diagnosis review", groups=sorted(silenced))
        if not silenced:
            diag.observe("No manifest-complete silenced group requires a Critical diagnosis")

    # step 5 (index #3 past violations)
    age = ctx.check("review_age", titles[3], {HISTORY: HIST_COLS})
    if age.runnable:
        as_of = ctx.snapshot or ctx.as_of
        hist_complete = ctx.table(HISTORY).complete is True
        events: dict[str, list[dict]] = {}
        for e in ctx.rows(HISTORY):
            events.setdefault(str(e.get("ad_id")), []).append(e)
        past: dict[str, list[str]] = {}
        for aid in sorted(events):
            for e in events[aid]:
                if _up(e.get("new_status")) == "DISAPPROVED" and aid in ledger and ledger[aid]["class"] != "disapproved":
                    past.setdefault(str(e.get("affected_policy_topic") or "unstated"), []).append(aid)
        for topic, aids in sorted(past.items()):
            age.observe(f"Past violation history: topic '{topic}' on {len(set(aids))} currently non-disapproved ad(s)",
                        topic=topic, ad_ids=sorted(set(aids)))
        for aid, x in sorted(ledger.items()):
            if x["class"] != "under_review" and x["review_status"] not in UNDER_REVIEW:
                continue
            evs = sorted(events.get(aid, []), key=lambda e: (str(e.get("event_at")), str(e.get("event_id"))))
            subs = [e for e in evs if str(e.get("event_type") or "").lower() in ("submitted", "edited")]
            ent = {"campaign_id": x["campaign_id"], "ad_group_id": x["ad_group_id"], "ad_id": aid}
            last = V.parse_date(subs[-1].get("event_at")) if subs else None
            if last and hist_complete and as_of:
                days = (as_of - last).days
                ev = {"review_age_days": days, "basis": f"latest {subs[-1].get('event_type')} event "
                      f"{subs[-1].get('event_id')} at {last}", "as_of": as_of, "confidence": "exact",
                      "scope": x["scope"], "followup_days_profile": ctx.profile.get("policy_review_followup_days")}
                age.observe(f"Ad {aid} under review for {days} day(s) (exact)", **ent, **ev)
                age.review("review_delay", ent, f"Is the {days}-day review of ad {aid} an evidenced delay needing follow-up?",
                           evidence=ev,
                           outcomes={"delay_needs_followup": {"severity": "Warning", "recommendation":
                                                              "Follow up via support/appeal review with the event history."},
                                     "within_expected": {"severity": None, "recommendation": "Keep monitoring."},
                                     "uncertain": {"severity": "Info", "recommendation": "Re-check at next snapshot."}},
                           guidance="Only paused scope is never urgent; no universal seven-day rule.")
                continue
            obs = [V.parse_date(e.get("event_at")) for e in evs if V.parse_date(e.get("event_at"))]
            lower = (as_of - obs[0]).days if obs and as_of else None
            age.finding("review_age_unknown", "Info", ent,
                        f"Ad {aid} under review; age unknown"
                        + (f", at least {lower} day(s) since first observation" if lower is not None else ""),
                        evidence={"lower_bound_days": lower, "submission_or_edit_events": len(subs),
                                  "history_complete": hist_complete, "scope": x["scope"]},
                        recommendation="Supply submission/edit events for an exact age before escalating.",
                        uncertainty="An edit can restart review; incomplete history cannot establish a delay.")

    # step 6
    top = ctx.check("topic_grouping", titles[4], {"ads": ["id"]} if not voc.runnable else {})
    if not voc.runnable:
        top.skip("policy status unavailable", voc.missing)
    else:
        am_t = ctx.table("ad_metrics")
        if am_t is None or am_t.missing(["ad_id", "ad_group_id", "impressions", "cost"]):
            top.partial("ad_metrics unavailable: prioritization context omitted",
                        ["ad_metrics (file)"] if am_t is None else
                        [f"ad_metrics:{c}" for c in am_t.missing(["ad_id", "ad_group_id", "impressions", "cost"])])
        cost = {}
        for r in ctx.rows("ad_metrics"):
            k = (str(r.get("ad_group_id")), str(r.get("ad_id")))
            c = ctx.money(r.get("cost"))
            cost[k] = None if c is None or cost.get(k, 0) is None else cost.get(k, 0) + c
        groups_t: dict[str, dict] = {}
        for x in ledger.values():
            if x["class"] not in ("disapproved", "limited"):
                continue
            for t in x["topics"] or ["(no topic exported)"]:
                acc = groups_t.setdefault(t, {"active_ads": set(), "paused_or_removed_ads": set(), "ad_groups": set(),
                                              "campaigns": set(), "active_cost": 0.0})
                (acc["active_ads"] if x["scope"] == "active" else acc["paused_or_removed_ads"]).add(x["ad_id"])
                acc["ad_groups"].add(x["ad_group_id"])
                acc["campaigns"].add(x["campaign_id"])
                if x["scope"] == "active" and acc["active_cost"] is not None:
                    c = cost.get((x["ad_group_id"], x["ad_id"]))
                    acc["active_cost"] = None if c is None else acc["active_cost"] + c
        for t, acc in sorted(groups_t.items()):
            top.observe(f"Policy topic '{t}': {len(acc['active_ads'])} active, {len(acc['paused_or_removed_ads'])} "
                        f"paused/removed ad(s)", topic=t, **acc, currency=ctx.currency,
                        note="active_cost is historical exposure for prioritization, not lost revenue")

    # steps 7-8
    q = ctx.check("resolution_queue", titles[5], {})
    own = ctx.check("owner_tracking", titles[6], {})
    if not voc.runnable:
        q.skip("policy status unavailable", voc.missing)
        own.skip("policy status unavailable", voc.missing)
        return
    queue = []
    for aid, x in sorted(ledger.items()):
        if x["scope"] != "active" or x["class"] not in ("disapproved", "limited"):
            continue
        step = ("await appeal outcome" if x["review_status"] == "UNDER_APPEAL" else
                "collect policy diagnosis" if not x["topics"] else
                "correct copy/destination or prepare appeal review for " + ", ".join(x["topics"]))
        queue.append({"ad_id": aid, "ad_group_id": x["ad_group_id"], "campaign_id": x["campaign_id"],
                      "approval_status": x["approval_status"], "next_step": step,
                      "evidence_needed": "Policy Manager diagnosis" if not use_custom else "current serving status"})
    q.observe("Resolution queue (review-only; no automatic appeal or pause)", items=queue)
    owner = ctx.profile.get("policy_owner") or ctx.profile.get("owner")
    if queue and not owner:
        own.partial("no profile.policy_owner: responsible approval owner unassigned")
    own.observe("Queue owner and required evidence", owner=owner, items=len(queue),
                related_reviews={"landing_page": "skill-125", "trademark_policy": "skill-141"})


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref from the item's source_refs; no automatic actions."""
    p = decision.get("proposal") or {}
    problems = []
    if str(p.get("action") or "").lower() in FORBIDDEN_ACTIONS:
        problems.append(f"proposal.action '{p.get('action')}' is an account change; recommend-only")
    if decision.get("outcome") == "material_loss_confirmed":
        ref = str(p.get("evidence_ref") or "")
        refs = item.evidence.get("source_refs") or []
        if not ref:
            problems.append("material loss needs proposal.evidence_ref pointing at the serving diagnosis")
        elif refs and ref not in refs:
            problems.append(f"proposal.evidence_ref '{ref}' not among supplied source_refs {refs}")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
