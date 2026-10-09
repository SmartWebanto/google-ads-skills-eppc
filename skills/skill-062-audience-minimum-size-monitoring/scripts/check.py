"""check.py — skill-062 deterministic audience list eligibility, membership state and weekly size trend.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-062-audience-minimum-size-monitoring/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Platform eligible/status/reason in custom/audience_eligibility is primary evidence; size is never used to
         override it and there is no universal 1,000-member rule. A documented minimum is compared only with an
         exact size plus minimum_source_url and minimum_checked_at.
         audiences associations: list key list_id (documented alternative audience_id), campaign_id, ad_group_id,
         mode ∈ TARGETING|OBSERVATION|EXCLUSION|SIGNAL (exclusion also via exclusion=true). Association status
         ENABLED/ACTIVE/empty counts as active; the campaign must be ENABLED. Eligibility rows match an
         association only when row channel equals campaigns.channel_type (normalized) and use_type equals the
         mode or is 'all'/empty — no channel inference.
         Warning (a) ineligible list with an active hard-TARGETING association (dependence not established);
         (b) comparable weekly decline: consecutive snapshots 6..8 days apart, old_size > 0, and decline > 20%
         even at the worst case of both precisions (exact=0; a number N in size_precision → ±N/2; other text →
         not comparable), on a list with an active association. Critical only via review with evidence_ref.
         Closed membership is reported separately, never as empty/unusable.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks07 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-062-audience-minimum-size-monitoring"
VERSION = "1.0.0"

ELIG = "custom/audience_eligibility"
HIST = "custom/audience_size_history"
DEFS = "custom/audience_definition_history"
DECLINE = -0.20


def _up(v) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def _list_col(ctx) -> str:
    t = ctx.table("audiences")
    return "audience_id" if t is not None and "list_id" not in t.columns and "audience_id" in t.columns else "list_id"


def _mode(row) -> str:
    m = _up(row.get("mode"))
    if m in ("EXCLUSION", "EXCLUDE", "NEGATIVE") or V.boolean(row.get("exclusion")) is True:
        return "EXCLUSION"
    if m in ("TARGETING", "TARGET"):
        return "TARGETING"
    if m in ("OBSERVATION", "BID_ONLY"):
        return "OBSERVATION"
    if m in ("SIGNAL", "AUDIENCE_SIGNAL"):
        return "SIGNAL"
    return "UNKNOWN"


def _associations(ctx) -> dict:
    """list_id -> [assoc dict] for active associations in ENABLED campaigns."""
    camps = {str(r.get("id")): r for r in ctx.rows("campaigns")}
    lc = _list_col(ctx)
    out: dict = {}
    for r in ctx.rows("audiences"):
        if _up(r.get("status")) not in ("ENABLED", "ACTIVE", ""):
            continue
        cid = str(r.get("campaign_id") or "")
        camp = camps.get(cid)
        if camp is None or _up(camp.get("status")) != "ENABLED":
            continue
        out.setdefault(str(r.get(lc)), []).append({
            "campaign_id": cid, "ad_group_id": str(r.get("ad_group_id") or ""), "mode": _mode(r),
            "channel": _up(camp.get("channel_type"))})
    return out


def _precision(v) -> float | None:
    s = str(v or "").strip().lower()
    if s == "exact":
        return 0.0
    m = re.search(r"\d+(\.\d+)?", s.replace(",", ""))
    return float(m.group()) / 2 if m and "suppress" not in s else None


def run(ctx) -> None:
    """Run list-use mapping, platform eligibility, membership state, size-trend and delivery-dependence checks.

    Rules:   Platform eligibility is primary; size never overrides it and no universal member minimum applies. Warning
             only for an ineligible list with an active hard-TARGETING association, or a 6..8-day snapshot decline > 20%
             at worst-case precision on an actively used list; non-restrictive/unknown eligibility → Info. Critical only
             via ai_review 'confirmed_dependency_failure'; closed membership is never reported as empty.
    """
    lu = ctx.check("list_uses", "List inventory, ownership and actual uses",
                   {ELIG: ["list_id", "channel", "use_type", "snapshot_date", "list_type", "eligible"]})
    elig = sorted(ctx.rows(ELIG), key=lambda r: (str(r.get("list_id")), str(r.get("channel")), str(r.get("use_type"))))
    aud = ctx.table("audiences")
    lc = _list_col(ctx)
    aud_missing = ["audiences (file)"] if aud is None else \
        [f"audiences:{c}" for c in aud.missing([lc, "campaign_id", "ad_group_id", "mode"])]
    if aud_missing or ctx.table("campaigns") is None:
        uses = None
        lu.partial("association inventory unavailable: actual uses unknown", aud_missing or ["campaigns (file)"])
    else:
        uses = _associations(ctx)
    lists = sorted({str(r.get("list_id")) for r in elig})
    shared = sorted({str(r.get("list_id")) for r in elig
                     if r.get("owner_account_id") and str(r.get("owner_account_id")) != str(ctx.account_id)})
    if lu.runnable:
        lu.observe("Audience list inventory", lists=len(lists), rows=len(elig), shared_from_other_accounts=shared,
                   by_use={l: sorted({a["mode"] for a in uses.get(l, [])}) for l in lists} if uses is not None else None,
                   unused=[l for l in lists if uses is not None and not uses.get(l)])

    # -- step 2: eligibility
    ce = ctx.check("current_eligibility", "Current platform eligibility vs active uses",
                   {ELIG: ["list_id", "channel", "use_type", "eligible", "eligibility_reason", "reported_size",
                           "size_precision"]})
    targeting_warnings = []
    if ce.runnable:
        if uses is None:
            ce.partial("association inventory unavailable: delivery relevance of ineligible lists unknown", aud_missing)
        unknown, info_lists = [], {}
        for r in elig:
            lid, ch, use = str(r.get("list_id")), _up(r.get("channel")), _up(r.get("use_type"))
            eligible = V.boolean(r.get("eligible"))
            size, prec = V.num(r.get("reported_size")), str(r.get("size_precision") or "")
            minimum = V.num(r.get("documented_minimum_if_applicable"))
            if minimum is not None:
                if _precision(prec) == 0 and size is not None and r.get("minimum_source_url") and r.get("minimum_checked_at"):
                    ce.observe(f"List {lid}/{ch}: size vs documented minimum", list_id=lid, channel=ch, size=size,
                               documented_minimum=minimum, below=size < minimum, source=r.get("minimum_source_url"),
                               checked_at=r.get("minimum_checked_at"), note="status remains primary evidence")
                else:
                    ce.observe(f"List {lid}/{ch}: documented minimum not comparable", list_id=lid,
                               reason="size not exact or minimum source/date missing")
            if eligible is None:
                unknown.append({"list_id": lid, "channel": ch, "use_type": use, "size_precision": prec})
                continue
            if eligible or uses is None:
                continue
            hits = [a for a in uses.get(lid, []) if a["channel"] == ch and (use in ("", "ALL") or use == a["mode"])]
            hard = [a for a in hits if a["mode"] == "TARGETING"]
            entity = {"list_id": lid, "channel": ch, "use_type": use or None}
            ev = {"eligibility_reason": r.get("eligibility_reason"), "reported_size": size, "size_precision": prec,
                  "snapshot_date": r.get("snapshot_date"), "source": r.get("source"),
                  "membership_status": r.get("membership_status")}
            if hard:
                f = ce.finding("ineligible_hard_targeting", "Warning", entity,
                               f"List {lid} is ineligible on {ch} ({r.get('eligibility_reason')}) while used for hard "
                               f"targeting in {len(hard)} active association(s)",
                               evidence={**ev, "targeting_associations": hard},
                               recommendation="Investigate the list source/eligibility with the owner; check whether "
                                              "another eligible targeted list or broad reach preserves delivery.",
                               uncertainty="Status alone does not prove the campaign stopped serving.")
                targeting_warnings.append((f, entity, hard, ev))
            else:
                info_lists.setdefault(lid, []).append({"channel": ch, "use_type": use or None,
                                                       "reason": r.get("eligibility_reason"),
                                                       "uses": sorted({a["mode"] for a in hits})})
        for lid in sorted(info_lists):
            ce.finding("ineligible_non_restrictive", "Info", {"list_id": lid},
                       f"List {lid} is ineligible where it is unused or used only for observation/signal/exclusion",
                       evidence={"rows": info_lists[lid]},
                       recommendation="Review only if a planned activation depends on it.",
                       uncertainty="No delivery restriction from these uses.")
        if unknown:
            ce.finding("eligibility_unknown", "Info", {"account_id": ctx.account_id},
                       f"{len(unknown)} list/channel rows have no reported eligibility status",
                       evidence={"rows": unknown},
                       recommendation="Export current channel eligibility from Audience manager.",
                       uncertainty="Unknown status is not ineligible and not a pass.")

    # -- step 3: membership
    ms = ctx.check("membership_state", "Membership status, duration and processing",
                   {ELIG: ["list_id", "membership_status", "membership_duration_days", "processing_status"]})
    if ms.runnable:
        closed = sorted({str(r.get("list_id")) for r in elig if _up(r.get("membership_status")) == "CLOSED"})
        processing = sorted({str(r.get("list_id")) for r in elig
                             if _up(r.get("processing_status")) not in ("", "COMPLETED", "COMPLETE", "DONE", "SUCCESS")})
        ms.observe("Membership states", closed_lists=closed, processing_not_complete=processing,
                   durations={str(r.get("list_id")): V.num(r.get("membership_duration_days")) for r in elig},
                   note="closed = no new members; not empty or immediately unusable")

    # -- steps 4-5: size trend
    st = ctx.check("size_trend", "Comparable weekly size trend",
                   {HIST: ["list_id", "channel", "use_type", "size_as_of", "reported_size", "size_precision"]})
    defs = ctx.table(DEFS)
    if st.runnable:
        if uses is None:
            st.partial("association inventory unavailable: relevance to active use unknown", aud_missing)
        series: dict = {}
        for r in ctx.rows(HIST):
            d = V.parse_date(r.get("size_as_of"))
            if d is None:
                st.partial(f"history row for list {r.get('list_id')} has no size_as_of timestamp")
                continue
            key = (str(r.get("list_id")), _up(r.get("channel")), _up(r.get("use_type")))
            series.setdefault(key, []).append((d, V.num(r.get("reported_size")), _precision(r.get("size_precision")),
                                               r.get("size_precision")))
        compared, noncomparable = 0, 0
        for key in sorted(series):
            pts = sorted(series[key], key=lambda p: p[0])
            if len(pts) < 2:
                noncomparable += 1
                continue
            (d0, s0, u0, p0), (d1, s1, u1, p1) = pts[-2], pts[-1]
            elapsed = (d1 - d0).days
            if not (6 <= elapsed <= 8) or s0 is None or s1 is None or u0 is None or u1 is None or s0 - u0 <= 0:
                noncomparable += 1
                st.observe(f"List {key[0]}/{key[1]}: latest pair not a comparable weekly observation", list_id=key[0],
                           channel=key[1], elapsed_days=elapsed, old_size=s0, new_size=s1, precision=[p0, p1])
                continue
            compared += 1
            change = V.ratio(s1 - s0, s0)
            worst = V.ratio((s1 + u1) - (s0 - u0), s0 - u0)
            active = uses is not None and any(a["mode"] != "EXCLUSION" for a in uses.get(key[0], []))
            st.observe(f"List {key[0]}/{key[1]}: weekly change", list_id=key[0], channel=key[1], old_size=s0,
                       new_size=s1, old_at=d0, new_at=d1, elapsed_days=elapsed, change=change,
                       least_decline_within_precision=worst, active_use=active)
            if worst is not None and worst < DECLINE and active:
                changes = [r for r in (defs.rows if defs else []) if str(r.get("list_id")) == key[0]
                           and (lambda e: e is not None and d0 <= e <= d1)(V.parse_date(r.get("effective_at")))]
                st.finding("weekly_size_decline", "Warning",
                           {"list_id": key[0], "channel": key[1], "use_type": key[2] or None},
                           f"List {key[0]} on {key[1]} fell {change:.1%} between {d0} and {d1} ({elapsed} days), "
                           f"beyond size precision",
                           evidence={"old_size": s0, "new_size": s1, "precision": [p0, p1],
                                     "active_uses": uses.get(key[0], []), "definition_changes_in_interval": changes},
                           calculation={"numerator": s1 - s0, "denominator": s0, "change": change,
                                        "worst_case_change": worst, "threshold": DECLINE, "elapsed_days": elapsed},
                           recommendation="Check definition, membership expiry, upload/source changes and seasonality "
                                          "before assigning a cause; do not extend retention to inflate size.",
                           uncertainty="Triage heuristic, not a platform minimum or causal diagnosis.")
        st.observe("Size trend coverage", comparable_pairs=compared, not_comparable=noncomparable)

    # -- step 6: delivery dependence (Critical only via review)
    dd = ctx.check("delivery_dependence", "Ineligibility → delivery dependence",
                   {"campaign_metrics": ["campaign_id", "impressions", "cost"]})
    if dd.runnable and not ce.runnable:
        dd.skip("current eligibility unavailable", ce.missing)
    if dd.runnable:
        cm = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
        for f, entity, hard, ev in targeting_warnings:
            cids = sorted({a["campaign_id"] for a in hard})
            others = sorted({l for l, al in (uses or {}).items() if l != entity["list_id"]
                             for a in al if a["mode"] == "TARGETING" and a["campaign_id"] in cids})
            dd.review("ineligible_hard_targeting", entity,
                      f"Is there direct evidence that delivery in campaign(s) {', '.join(cids)} depends on list "
                      f"{entity['list_id']} and failed materially?",
                      evidence={**ev, "campaign_delivery": {c: {"impressions": V.num((cm.get(c) or {}).get("impressions")),
                                                                "cost": ctx.money((cm.get(c) or {}).get("cost"))} for c in cids},
                                "other_targeting_lists_same_campaigns": others},
                      outcomes={"confirmed_dependency_failure": {"severity": "Critical", "recommendation":
                                                                 "Restore eligibility or an eligible targeting path; cite the evidence."},
                                "not_established": {"severity": None, "recommendation": "Keep the Warning."}},
                      guidance="Critical needs observed material delivery failure AND confirmed dependency; supply "
                               "proposal.evidence_ref. Other eligible lists or broad reach may preserve delivery.")
        dd.observe("Ineligible hard-targeting lists queued for dependency review", count=len(targeting_warnings))

    ce2 = ctx.check("cause_evidence", "Definition/membership change evidence",
                    {DEFS: ["list_id", "effective_at", "change_type", "old_value", "new_value"]})
    if ce2.runnable:
        ce2.observe("Definition changes supplied", rows=len(defs.rows),
                    lists=sorted({str(r.get("list_id")) for r in defs.rows}))


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcome requires proposal.evidence_ref pointing at supplied delivery evidence."""
    if decision.get("outcome") == "confirmed_dependency_failure" and not (decision.get("proposal") or {}).get("evidence_ref"):
        return ["confirmed dependency failure needs proposal.evidence_ref"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
