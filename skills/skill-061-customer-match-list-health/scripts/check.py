"""check.py — skill-061 deterministic Customer Match inventory, use mapping, freshness and sync health.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-061-customer-match-list-health/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Sanitized diagnostics only: never read or request raw emails/phones/customer rows; evidence carries
         counts, dates, categories and references only.
         Freshness = reference date (ctx.snapshot, else ctx.as_of) − source_extract_at of the latest SUCCESSFUL
         completed job (status SUCCESS|SUCCEEDED|COMPLETED|DONE); REPLACE is a full refresh, ADD/REMOVE a delta and
         both are labelled. No successful job → freshness unknown, never stale.
         "Required active use case" = policy row with authorized_use_status AUTHORIZED|APPROVED, required_refresh_days
         and an active association (ENABLED campaign, association status ENABLED/ACTIVE/empty).
         Warning: (a) required active use with refresh age > required_refresh_days or latest job failed with no later
         success; (b) active association on a list the platform marks ineligible (eligible=false on the campaign's
         channel or account_use_eligible=false). Unauthorized activation and material delivery failure are
         Critical only via ai_review with proposal.evidence_ref (verify enforces).
         Match rates are compared only within one match_rate_definition; never derived from size/upload counts.
         No fixed 30/90-day expiry, 30% match-rate minimum or list-size tier.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial deterministic check
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

SKILL = "skill-061-customer-match-list-health"
VERSION = "1.0.0"

STATUS = "custom/customer_match_status"
UPLOADS = "external/customer_match_upload_history"
POLICY = "external/customer_match_policy"
_OK = ("SUCCESS", "SUCCEEDED", "COMPLETED", "COMPLETE", "DONE")
_FAIL = ("FAILED", "FAILURE", "ERROR", "REJECTED", "CANCELLED")
_AUTH = ("AUTHORIZED", "AUTHORISED", "APPROVED")


def _up(v) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def _list_col(ctx) -> str:
    t = ctx.table("audiences")
    return "audience_id" if t is not None and "list_id" not in t.columns and "audience_id" in t.columns else "list_id"


def _associations(ctx) -> dict | None:
    """list_id -> active associations in ENABLED campaigns; None when inventory is unavailable."""
    t, lc = ctx.table("audiences"), _list_col(ctx)
    if t is None or t.missing([lc, "campaign_id", "ad_group_id", "mode"]) or ctx.table("campaigns") is None:
        return None
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns")}
    out: dict = {}
    for r in t.rows:
        camp = camps.get(str(r.get("campaign_id") or ""))
        if _up(r.get("status")) not in ("ENABLED", "ACTIVE", "") or camp is None or _up(camp.get("status")) != "ENABLED":
            continue
        out.setdefault(str(r.get(lc)), []).append({"campaign_id": str(r.get("campaign_id")),
                                                   "ad_group_id": str(r.get("ad_group_id") or ""),
                                                   "mode": _up(r.get("mode")), "channel": _up(camp.get("channel_type"))})
    return out


def _missing(ctx, key, cols) -> list[str]:
    t = ctx.table(key)
    return [f"{key} (file)"] if t is None else [f"{key}:{c}" for c in t.missing(cols)]


def _ts(v):
    return V.parse_date(v)


def run(ctx) -> None:
    """Run Customer Match list freshness, authorization, eligibility, sync and match-rate checks.

    Rules:   Sanitized diagnostics only; never read raw emails/phones. No successful job → freshness unknown, never
             stale. Warning: required active use past required_refresh_days or failed with no later success, or active
             association on an ineligible list. Unauthorized activation / material delivery failure → Critical only via
             ai_review with proposal.evidence_ref. Match rates compared within one definition only; no fixed expiry,
             rate or size tier.
    """
    ref = ctx.snapshot or ctx.as_of
    assoc = _associations(ctx)
    assoc_missing = _missing(ctx, "audiences", [_list_col(ctx), "campaign_id", "ad_group_id", "mode"]) + \
        ([] if ctx.table("campaigns") else ["campaigns (file)"])
    policy = {}
    for r in ctx.rows(POLICY):
        policy.setdefault(str(r.get("list_id")), []).append(r)

    # -- step 1: inventory
    inv = ctx.check("list_inventory", "Customer Match list inventory (incl. closed/unused)",
                    {STATUS: ["list_id", "channel", "snapshot_date", "list_type", "membership_status", "reported_size",
                              "size_precision", "eligible", "account_use_eligible"]})
    status = sorted(ctx.rows(STATUS), key=lambda r: (str(r.get("list_id")), str(r.get("channel"))))
    lists = sorted({str(r.get("list_id")) for r in status})
    if inv.runnable:
        if assoc is None:
            inv.partial("association inventory unavailable: unused lists unknown", assoc_missing)
        suppressed = sorted({str(r.get("list_id")) for r in status
                             if V.num(r.get("reported_size")) is None or "suppress" in str(r.get("size_precision") or "").lower()})
        inv.observe("Customer Match inventory", lists=len(lists),
                    membership_status={l: sorted({_up(r.get("membership_status")) for r in status if str(r.get("list_id")) == l})
                                       for l in lists},
                    unused=[l for l in lists if assoc is not None and not assoc.get(l)],
                    account_use_ineligible=sorted({str(r.get("list_id")) for r in status
                                                   if V.boolean(r.get("account_use_eligible")) is False}))
        if suppressed:
            inv.finding("size_suppressed", "Info", {"account_id": ctx.account_id},
                        f"{len(suppressed)} Customer Match lists have a suppressed/unknown reported size",
                        evidence={"list_ids": suppressed},
                        recommendation="Use platform eligibility, not size, for readiness.",
                        uncertainty="Suppressed size is not zero.")

    # -- step 2: use mapping
    um = ctx.check("use_mapping", "Declared use vs actual association/mode",
                   {POLICY: ["list_id", "purpose", "intended_campaign_ids", "authorized_use_status", "owner"]})
    required: dict = {}
    if assoc is None:
        um.skip("association inventory unavailable", assoc_missing)
    if um.runnable:
        no_policy, unapplied = [], []
        for lid in sorted(set(policy) | set(lists)):
            rows = policy.get(lid, [])
            active = assoc.get(lid, [])
            intended = {c for r in rows for c in V.split_list(r.get("intended_campaign_ids"), (";", "|", ","))}
            authorized = any(_up(r.get("authorized_use_status")) in _AUTH for r in rows)
            if active and not rows:
                no_policy.append(lid)
            if rows and not active:
                unapplied.append({"list_id": lid, "intended_campaign_ids": sorted(intended),
                                  "purpose": [r.get("purpose") for r in rows]})
            if authorized and active and any(r.get("required_refresh_days") for r in rows):
                required[lid] = {"campaigns": sorted({a["campaign_id"] for a in active}), "policy": rows}
            outside = sorted({a["campaign_id"] for a in active if a["campaign_id"] not in intended})
            if active and rows and (not authorized or outside):
                entity = {"list_id": lid, "campaign_ids": outside or sorted({a["campaign_id"] for a in active})}
                ev = {"authorized_use_status": [r.get("authorized_use_status") for r in rows],
                      "intended_campaign_ids": sorted(intended), "active_associations": active,
                      "aggregate_consent_evidence_ref": [r.get("aggregate_consent_evidence_ref") for r in rows],
                      "owner": [r.get("owner") for r in rows], "reviewed_at": [r.get("reviewed_at") for r in rows]}
                prov = um.finding("activation_outside_authorization", "Info", entity,
                                  f"List {lid} is active outside its recorded authorized use",
                                  evidence=ev, recommendation="Confirm authorization with the data owner.",
                                  uncertainty="Authorization intake is not legal certification.")
                um.review("activation_outside_authorization", entity,
                          f"Is the activation of Customer Match list {lid} in campaign(s) {', '.join(entity['campaign_ids'])} "
                          f"confirmed unauthorized?",
                          evidence=ev, provisional=prov,
                          outcomes={"confirmed_unauthorized": {"severity": "Critical", "recommendation":
                                                               "Owner to stop the unauthorized use; cite the record."},
                                    "authorized_elsewhere": {"severity": None, "recommendation":
                                                             "Update the policy intake with the authorizing record."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask the data owner."}},
                          guidance="Critical requires proposal.evidence_ref naming the authorization record/review.")
        if no_policy:
            um.finding("authorization_missing", "Info", {"account_id": ctx.account_id},
                       f"{len(no_policy)} actively used lists have no policy/authorization intake",
                       evidence={"list_ids": no_policy},
                       recommendation="Request the owner's customer_match_policy row; no activation proposals meanwhile.",
                       uncertainty="Missing intake is not proof of unauthorized use.")
        if unapplied:
            um.finding("unapplied_list", "Info", {"account_id": ctx.account_id},
                       f"{len(unapplied)} lists with a declared purpose are not currently applied",
                       evidence={"lists": unapplied},
                       recommendation="Confirm whether this is intentional preparation.",
                       uncertainty="Unapplied lists may be intentional.")

    ae = ctx.check("association_eligibility", "Active associations on platform-ineligible lists",
                   {STATUS: ["list_id", "channel", "eligible", "eligibility_reason", "account_use_eligible"]})
    if assoc is None:
        ae.skip("association inventory unavailable", assoc_missing)
    if ae.runnable:
        for lid in sorted(l for l in assoc if l in lists):
            for a in assoc[lid]:
                bad = [r for r in status if str(r.get("list_id")) == lid and (
                    V.boolean(r.get("account_use_eligible")) is False or
                    (_up(r.get("channel")) == a["channel"] and V.boolean(r.get("eligible")) is False))]
                if not bad:
                    continue
                ae.finding("active_association_ineligible", "Warning",
                           {"list_id": lid, "campaign_id": a["campaign_id"], "ad_group_id": a["ad_group_id"] or None},
                           f"List {lid} is associated ({a['mode'] or 'mode unknown'}) in campaign {a['campaign_id']} "
                           f"but the platform marks it ineligible",
                           evidence={"status_rows": [{k: r.get(k) for k in ("channel", "eligible", "eligibility_reason",
                                                                            "account_use_eligible", "snapshot_date")}
                                                     for r in bad]},
                           recommendation="Resolve eligibility with the owner before relying on this activation.",
                           uncertainty="Delivery impact not yet established.")
        ae.observe("Active associations checked against platform eligibility",
                   associations=sum(len(assoc.get(l, [])) for l in lists))

    # -- step 3: freshness
    fr = ctx.check("freshness", "Refresh age vs owner cadence",
                   {UPLOADS: ["list_id", "job_id", "completed_at", "status", "operation", "source_extract_at"],
                    POLICY: ["list_id", "required_refresh_days"]})
    jobs: dict = {}
    for r in ctx.rows(UPLOADS):
        jobs.setdefault(str(r.get("list_id")), []).append(r)
    stale_or_failed = []
    if fr.runnable:
        if ref is None:
            fr.skip("reference date unknown (account snapshot_date/as_of)")
        elif not um.runnable:
            fr.partial("use mapping unavailable: required active use cases unknown", um.missing)
    if fr.runnable:
        for lid in sorted(set(jobs) | set(policy)):
            ok = sorted((j for j in jobs.get(lid, []) if _up(j.get("status")) in _OK and _ts(j.get("completed_at"))
                         and _ts(j.get("source_extract_at"))), key=lambda j: (_ts(j.get("source_extract_at")), str(j.get("job_id"))))
            cadence = min((V.num(r.get("required_refresh_days")) for r in policy.get(lid, [])
                           if V.num(r.get("required_refresh_days"))), default=None)
            if not ok:
                fr.observe(f"List {lid}: no successful completed job in supplied history (freshness unknown)", list_id=lid,
                           jobs=len(jobs.get(lid, [])), required_refresh_days=cadence)
                continue
            last = ok[-1]
            full = [j for j in ok if _up(j.get("operation")) == "REPLACE"]
            age = (ref - _ts(last.get("source_extract_at"))).days
            age_full = (ref - _ts(full[-1].get("source_extract_at"))).days if full else None
            data = {"list_id": lid, "last_success_job": last.get("job_id"), "last_operation": _up(last.get("operation")),
                    "source_extract_at": last.get("source_extract_at"), "completed_at": last.get("completed_at"),
                    "age_days": age, "last_full_refresh_age_days": age_full, "required_refresh_days": cadence,
                    "reference_date": ref}
            fr.observe(f"List {lid}: freshness", **data)
            if lid in required and cadence is not None and age > cadence:
                entity = {"list_id": lid}
                fr.finding("refresh_beyond_cadence", "Warning", entity,
                           f"List {lid} (required active use) was last refreshed from a {last.get('source_extract_at')} "
                           f"extract: {age} days > owner cadence {cadence:g}",
                           evidence={**data, "campaigns": required[lid]["campaigns"],
                                     "delta_only": _up(last.get("operation")) != "REPLACE"},
                           calculation={"age_days": age, "required_refresh_days": cadence, "reference_date": ref},
                           recommendation="Owner to restore the agreed synchronization; do not upload from here.",
                           uncertainty="Delivery impact not established by age alone.")
                stale_or_failed.append((entity, data))

    # -- step 4: failures/pending
    uf = ctx.check("upload_failures", "Failed/pending jobs and rejection categories",
                   {UPLOADS: ["list_id", "job_id", "submitted_at", "status", "error_category", "accepted_count",
                              "rejected_count"]})
    if uf.runnable:
        if not um.runnable:
            uf.partial("use mapping unavailable: failure relevance unknown", um.missing)
        for lid in sorted(jobs):
            js = sorted(jobs[lid], key=lambda j: (_ts(j.get("submitted_at")) or _ts(j.get("completed_at")) or date.min,
                                                  str(j.get("job_id"))))
            cats: dict = {}
            for j in js:
                if _up(j.get("status")) in _FAIL or (V.num(j.get("rejected_count")) or 0) > 0:
                    c = str(j.get("error_category") or "unspecified")
                    cats[c] = cats.get(c, 0) + 1
            pending = [j.get("job_id") for j in js if _up(j.get("status")) in ("PENDING", "RUNNING", "IN_PROGRESS")]
            uf.observe(f"List {lid}: job outcomes", list_id=lid, jobs=len(js), failure_categories=cats,
                       pending_jobs=pending)
            latest = js[-1] if js else None
            if latest is not None and _up(latest.get("status")) in _FAIL and lid in required:
                entity = {"list_id": lid, "job_id": latest.get("job_id")}
                ev = {"status": latest.get("status"), "error_category": latest.get("error_category"),
                      "submitted_at": latest.get("submitted_at"), "campaigns": required[lid]["campaigns"]}
                uf.finding("failed_required_sync", "Warning", entity,
                           f"Latest job {latest.get('job_id')} for required list {lid} failed "
                           f"({latest.get('error_category') or 'unspecified'}) with no later success",
                           evidence=ev, recommendation="Owner to fix the pipeline error category and re-sync.",
                           uncertainty="Material delivery impact not yet established.")
                stale_or_failed.append((entity, ev))

    # -- step 5: match rates
    mr = ctx.check("match_rate", "Match-rate diagnostics within one definition",
                   {STATUS: ["list_id", "match_rate", "match_rate_definition", "match_rate_available"]})
    if mr.runnable:
        by_def: dict = {}
        unavailable = []
        for r in status:
            rate = ctx.rate(r.get("match_rate"))
            if V.boolean(r.get("match_rate_available")) is not True or rate is None or not r.get("match_rate_definition"):
                unavailable.append(str(r.get("list_id")))
                continue
            by_def.setdefault(str(r.get("match_rate_definition")), []).append({"list_id": r.get("list_id"), "rate": rate})
        mr.observe("Match rates grouped by definition (diagnostic only)", by_definition=by_def,
                   unavailable=sorted(set(unavailable)))

    # -- step 6: cadence/lifecycle
    cl = ctx.check("cadence_lifecycle", "Membership duration, lifecycle and deletion sync",
                   {POLICY: ["list_id", "required_refresh_days", "deletion_sync_required", "membership_rationale"],
                    STATUS: ["list_id", "membership_duration_days"]})
    if cl.runnable:
        for lid in sorted(policy):
            rows = policy[lid]
            deletion = any(V.boolean(r.get("deletion_sync_required")) for r in rows)
            ops = sorted({_up(j.get("operation")) for j in jobs.get(lid, []) if _up(j.get("status")) in _OK})
            cl.observe(f"List {lid}: lifecycle", list_id=lid, deletion_sync_required=deletion,
                       successful_operations=ops, deletion_sync_evidenced=bool({"REPLACE", "REMOVE"} & set(ops)) if deletion else None,
                       membership_duration_days=sorted({V.num(r.get("membership_duration_days")) for r in status
                                                        if str(r.get("list_id")) == lid and r.get("membership_duration_days")}),
                       membership_rationale=[r.get("membership_rationale") for r in rows],
                       customer_lifecycle=ctx.profile.get("customer_lifecycle"),
                       sales_cycle_days=ctx.profile.get("sales_cycle_days"))

    # -- step 7: escalation
    es = ctx.check("escalation", "Material delivery failure escalation",
                   {"campaign_metrics": ["campaign_id", "impressions", "cost"]})
    if es.runnable and not (fr.runnable or uf.runnable):
        es.skip("freshness and upload history unavailable", fr.missing + uf.missing)
    if es.runnable:
        cm = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
        for entity, ev in stale_or_failed:
            cids = ev.get("campaigns") or required.get(entity["list_id"], {}).get("campaigns", [])
            es.review("required_sync_delivery_failure", entity,
                      f"Is there direct evidence that the failed/stale sync of list {entity['list_id']} caused a material "
                      f"delivery failure on a required use?",
                      evidence={**ev, "campaign_delivery": {c: {"impressions": V.num((cm.get(c) or {}).get("impressions")),
                                                                "cost": ctx.money((cm.get(c) or {}).get("cost"))} for c in cids}},
                      outcomes={"material_delivery_failure": {"severity": "Critical", "recommendation":
                                                              "Escalate to the data owner with the cited evidence."},
                                "not_established": {"severity": None, "recommendation": "Keep the Warning."}},
                      guidance="A small list or low match rate is not material failure; supply proposal.evidence_ref.")
        es.observe("Escalation candidates", count=len(stale_or_failed))


def verify(ctx, item, decision) -> list[str]:
    """Rules: every Critical outcome needs proposal.evidence_ref (no PII; a record/report reference)."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") == "Critical" and not (decision.get("proposal") or {}).get("evidence_ref"):
        return ["Critical outcome needs proposal.evidence_ref pointing at supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
