"""check.py — skill-106 deterministic GA4↔Ads link identity, required flows, imports and bidding-goal overlap.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-106-ga4-google-ads-integration/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Only ga4_ads_links rows whose account_id equals this account (dashes ignored) are this account's links.
         intended_flow tokens → traffic_reporting (traffic/reporting), conversion_import (conversion/import),
         audience_activation (audience); none/native → no GA4 flow. No intended flow = legitimate native-only.
         Unknown is never disabled: unknown link/auto-tagging state → Info/partial, never Warning.
         Required import = ga4_ads_event_mapping.intended_bidding_role primary|bidding; secondary/diagnostic
         roles are preserved parallel measurement (observation).
         Duplicate bidding signal = >=2 distinct action_ids with the SAME business_event_id, include_in_conversions
         true on rows of the SAME campaign_id (empty = account-default goal scope), and conversion_actions.status
         ENABLED; two measurement sources alone never prove duplication. Row include_in_conversions is the
         effective per-campaign goal inclusion (custom goals resolved upstream; custom_goal_membership is evidence).
         Stale flow = processing_mature true AND (tested_at − event_or_audience_last_seen) > expected_latency_hours
         of the link. Free-text expected/observed behaviour differences are ai_review.
         Critical only via review with proposal.evidence_ref. Platform total differences route to skill 071.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-106-ga4-google-ads-integration"
VERSION = "1.0.0"

LINKS = "external/ga4_ads_links"
MAP = "external/ga4_ads_event_mapping"
FLOW = "external/ga4_ads_flow_checks"
_LINK_BAD = {"unlinked", "removed", "failed", "disabled", "revoked", "rejected", "inactive"}
_LINK_OK = {"linked", "active", "enabled"}
_DISABLED = {"disabled", "off", "false", "no"}
_ENABLED = {"enabled", "on", "true", "yes"}
_NOT_IMPORTED = {"not_imported", "not imported", "missing", "removed", "failed", "disabled"}
_FAIL = {"fail", "failed", "stripped", "lost", "dropped"}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _acct(v) -> str:
    return _s(v).replace("-", "")


def _flows(v) -> set[str]:
    out = set()
    for t in V.split_list(v):
        n = V.norm_text(t)
        if "audience" in n:
            out.add("audience_activation")
        elif "conversion" in n or "import" in n:
            out.add("conversion_import")
        elif "traffic" in n or "reporting" in n:
            out.add("traffic_reporting")
    return out


def _ts(v) -> datetime | None:
    s = _s(v)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        d = V.parse_date(s)
        return datetime(d.year, d.month, d.day) if d else None


def _critical(chk, key, entity, question, ev):
    chk.review(key, entity, question, evidence=ev,
               outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                        "Prioritize the owner-reviewed flow fix; cite the evidence."},
                         "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
               guidance="Critical needs proposal.evidence_ref to supplied material-failure evidence.")


def run(ctx) -> None:
    """Run GA4 link, auto-tagging, required import, goal duplication, staleness and behaviour-review checks.

    Rules:   Only links whose account_id matches this account count; no intended flow = legitimate native-only. Unknown
             link/auto-tagging state → Info/partial, never Warning. Deterministic Warnings: required link inactive,
             personalization off for audience flow, auto-tagging off, click ID lost, required import missing, duplicate
             bidding signal, stale flow beyond latency. Free-text differences are ai_review; Critical only with
             proposal.evidence_ref.
    """
    me = _acct(ctx.account_id)
    links = {}
    for r in sorted(ctx.rows(LINKS), key=lambda r: (_s(r.get("link_id")), _s(r.get("property_id")))):
        if _acct(r.get("account_id")) == me and _s(r.get("link_id")):
            links.setdefault(_s(r.get("link_id")), r)

    # -- step 1: intended flows
    fl = ctx.check("intended_flows", "Intended flows per link", {LINKS: ["link_id", "property_id", "account_id",
                                                                        "intended_flow"]})
    flows = {lid: _flows(r.get("intended_flow")) for lid, r in links.items()}
    if fl.runnable:
        fl.observe("Intended GA4 flows for this account", links={k: sorted(v) for k, v in sorted(flows.items())},
                   note="no intended GA4 flow is a legitimate native Ads-only design" if not any(flows.values())
                   else "flows are assessed separately; no bidirectional-sharing mandate")
    warned: list[str] = []

    # -- step 2: link identity and settings
    li = ctx.check("link_identity", "Exact property/account/link identities and settings",
                   {LINKS: ["property_id", "account_id", "link_id", "link_status", "ads_personalization_setting",
                            "permissions_verified_by_owner"]})
    if li.runnable:
        for lid, r in sorted(links.items()):
            need = flows[lid]
            if not need:
                continue
            ent = {"link_id": lid, "property_id": _s(r.get("property_id"))}
            ev = {k: r.get(k) for k in ("link_status", "effective_from", "ads_personalization_setting",
                                        "data_sharing_settings", "permissions_verified_by_owner", "source_reference",
                                        "owner")} | {"intended_flows": sorted(need)}
            st = V.norm_text(r.get("link_status"))
            if st in _LINK_BAD:
                warned.append(lid)
                li.finding("required_link_inactive", "Warning", ent,
                           f"Link {lid} is '{r.get('link_status')}' although flows {sorted(need)} are intended",
                           evidence=ev, recommendation="Owner-reviewed link correction; no linking performed here.",
                           uncertainty="Configuration snapshot; failure impact via flow checks.")
                _critical(li, "required_link_inactive", ent, f"Does inactive link {lid} cause a material failure of "
                                                             f"an explicitly required flow?", ev)
            elif st not in _LINK_OK:
                li.finding("link_state_unknown", "Info", ent, f"Link {lid}: status '{r.get('link_status')}' unknown/pending",
                           evidence=ev, recommendation="Supply current link configuration evidence.",
                           uncertainty="Unknown link state is not a failure.")
            if "audience_activation" in need and V.norm_text(r.get("ads_personalization_setting")) in _DISABLED:
                warned.append(lid)
                li.finding("personalization_disabled_for_audience_flow", "Warning", ent,
                           f"Link {lid}: ads personalization disabled while audience activation is intended",
                           evidence=ev, recommendation="Owner/privacy review of the setting against the design.",
                           uncertainty="Setting may be deliberately restricted by policy.")

    # -- step 3: auto-tagging and parameter preservation
    at = ctx.check("auto_tagging", "Auto-tagging and click-ID preservation for intended flows",
                   {LINKS: ["link_id", "auto_tagging_status", "intended_flow"]})
    if at.runnable:
        flow_rows = ctx.rows(FLOW)
        ft = ctx.table(FLOW)
        if ft is None or ft.missing(["link_id", "parameter_preservation_check", "processing_mature"]):
            at.partial("parameter-preservation traces unavailable",
                       [f"{FLOW} (file)"] if ft is None else [f"{FLOW}:{c}" for c in
                                                             ft.missing(["link_id", "parameter_preservation_check",
                                                                         "processing_mature"])])
            flow_rows = []
        for lid, r in sorted(links.items()):
            need = flows[lid] & {"traffic_reporting", "conversion_import"}
            if not need:
                continue
            ent = {"link_id": lid}
            raw = r.get("auto_tagging_status") if _s(r.get("auto_tagging_status")) else ctx.account.get("auto_tagging")
            status = V.norm_text(raw)
            if status in _DISABLED:
                warned.append(lid)
                at.finding("auto_tagging_disabled_for_required_flow", "Warning", ent,
                           f"Link {lid}: auto-tagging disabled while {sorted(need)} are intended",
                           evidence={"auto_tagging_status": raw, "intended_flows": sorted(need)},
                           recommendation="Owner review of auto-tagging against the design.",
                           uncertainty="Disabled alone is not Critical without an observed failure.")
            elif status not in _ENABLED:
                at.partial(f"link {lid}: auto-tagging state unknown")
            for fr in sorted((x for x in flow_rows if _s(x.get("link_id")) == lid),
                             key=lambda x: _s(x.get("check_id"))):
                if V.norm_text(fr.get("parameter_preservation_check")) in _FAIL \
                        and V.boolean(fr.get("processing_mature")) is True:
                    warned.append(lid)
                    e2 = {"link_id": lid, "check_id": _s(fr.get("check_id"))}
                    ev = {k: fr.get(k) for k in ("flow_type", "tested_at", "parameter_preservation_check",
                                                 "diagnostic_code", "source_reference")}
                    at.finding("click_id_not_preserved", "Warning", e2,
                               f"Check {e2['check_id']}: click-ID parameters not preserved on link {lid}",
                               evidence=ev, recommendation="Fix redirects/URL handling with the site owner.",
                               uncertainty="Sanitized synthetic trace; scope limited to tested URLs.")
                    _critical(at, "click_id_not_preserved", e2, f"Does the lost click ID in check {e2['check_id']} "
                                                                f"materially break a required flow?", ev)

    # -- step 4: required imports
    ri = ctx.check("required_imports", "Required key-event imports",
                   {MAP: ["property_id", "event_name", "action_id", "imported_status", "intended_bidding_role",
                          "source_type"]})
    if ri.runnable:
        optional = 0
        for r in sorted(ctx.rows(MAP), key=lambda r: (_s(r.get("event_name")), _s(r.get("action_id")),
                                                      _s(r.get("campaign_id")))):
            role = V.norm_text(r.get("intended_bidding_role"))
            if role not in ("primary", "bidding"):
                optional += 1
                continue
            if V.norm_text(r.get("imported_status")) in _NOT_IMPORTED:
                ent = {"property_id": _s(r.get("property_id")), "event_name": _s(r.get("event_name")),
                       "action_id": _s(r.get("action_id")) or None}
                ri.finding("required_import_missing", "Warning", ent,
                           f"Key event '{r.get('event_name')}' is intended for bidding but import status is "
                           f"'{r.get('imported_status')}'", evidence={k: r.get(k) for k in (
                               "imported_status", "intended_bidding_role", "source_type", "campaign_id")},
                           recommendation="Owner-reviewed import correction; no imports performed here.",
                           uncertainty="Mapping snapshot.")
        ri.observe("Non-bidding GA4 imports preserved as diagnostic measurement", rows=optional)

    # -- step 5: effective goal overlap
    go = ctx.check("goal_overlap", "Shared business events in effective bidding goals",
                   {MAP: ["campaign_id", "action_id", "business_event_id", "include_in_conversions",
                          "primary_for_goal", "custom_goal_membership", "source_type"],
                    "conversion_actions": ["id", "status"]})
    if go.runnable:
        status = {_s(r.get("id")): V.norm_text(r.get("status")) for r in ctx.rows("conversion_actions")}
        groups: dict[tuple[str, str], dict[str, dict]] = {}
        unknown_actions = set()
        for r in ctx.rows(MAP):
            be, aid = _s(r.get("business_event_id")), _s(r.get("action_id"))
            if not be or not aid or V.boolean(r.get("include_in_conversions")) is not True:
                continue
            if aid not in status:
                unknown_actions.add(aid)
                continue
            if status[aid] != "enabled":
                continue
            groups.setdefault((_s(r.get("campaign_id")), be), {})[aid] = r
        if unknown_actions:
            go.partial(f"mapped actions absent from conversion_actions: {sorted(unknown_actions)}",
                       ["conversion_actions:id"])
        for (cid, be), acts in sorted(groups.items()):
            if len(acts) < 2:
                continue
            ent = {"campaign_id": cid or None, "business_event_id": be}
            go.finding("duplicate_bidding_signal", "Warning", ent,
                       f"{len(acts)} included actions ({sorted(acts)}) represent business event {be} in "
                       f"{'campaign ' + cid if cid else 'the account-default goal'}",
                       evidence={"actions": {a: {k: r.get(k) for k in ("source_type", "primary_for_goal",
                                                                       "custom_goal_membership", "counting")}
                                             for a, r in sorted(acts.items())}},
                       recommendation="Keep one bidding source for the event; keep the other as secondary.",
                       uncertainty="Business-event identity as supplied; reconcile counts via 071.")

    # -- step 6: preserve independent measurement
    im = ctx.check("independent_measurement", "Preserve native primary plus GA4 secondary measurement",
                   {MAP: ["business_event_id", "source_type", "include_in_conversions"]})
    if im.runnable:
        by_be: dict[str, set[tuple[str, bool]]] = {}
        for r in ctx.rows(MAP):
            src = "ga4" if "ga4" in V.norm_text(r.get("source_type")) or "analytics" in V.norm_text(
                r.get("source_type")) else "native"
            by_be.setdefault(_s(r.get("business_event_id")), set()).add(
                (src, V.boolean(r.get("include_in_conversions")) is True))
        parallel = sorted(be for be, s in by_be.items() if be and ("native", True) in s and ("ga4", False) in s)
        im.observe("Native primary + GA4 secondary pairs preserved (not a defect)", business_events=parallel)

    # -- step 7: sync after expected latency
    sl = ctx.check("sync_latency", "Event/audience flow after expected latency",
                   {FLOW: ["link_id", "flow_type", "check_id", "tested_at", "expected_behavior", "observed_behavior",
                           "event_or_audience_last_seen", "processing_mature", "diagnostic_code"],
                    LINKS: ["link_id", "expected_latency_hours", "effective_from"]})
    if sl.runnable:
        for fr in sorted(ctx.rows(FLOW), key=lambda x: (_s(x.get("link_id")), _s(x.get("check_id")))):
            lid = _s(fr.get("link_id"))
            if lid not in links:
                continue
            ent = {"link_id": lid, "check_id": _s(fr.get("check_id")), "flow_type": _s(fr.get("flow_type"))}
            ev = {k: fr.get(k) for k in ("tested_at", "observation_window_start", "observation_window_end",
                                         "expected_behavior", "observed_behavior", "event_or_audience_last_seen",
                                         "diagnostic_code", "source_reference")}
            if V.boolean(fr.get("processing_mature")) is not True:
                sl.observe(f"Check {ent['check_id']}: within processing/new-link window", **ent)
                continue
            lat = V.num(links[lid].get("expected_latency_hours"))
            t_test, t_seen = _ts(fr.get("tested_at")), _ts(fr.get("event_or_audience_last_seen"))
            age = (t_test - t_seen).total_seconds() / 3600 if t_test and t_seen else None
            ev.update(expected_latency_hours=lat, hours_since_last_seen=age)
            if lat is not None and age is not None and age > lat:
                warned.append(lid)
                sl.finding("flow_stale_after_latency", "Warning", ent,
                           f"Check {ent['check_id']}: last seen {age:.0f}h before test, beyond expected {lat:g}h",
                           evidence=ev, recommendation="Owner review of the flow with diagnostics.",
                           uncertainty="Single diagnostic; policy restrictions can suppress flows.")
                _critical(sl, "flow_stale_after_latency", ent, f"Is the stale {ent['flow_type']} flow a material "
                                                               f"failure of an explicitly required flow?", ev)
            elif lat is None or age is None:
                sl.partial(f"check {ent['check_id']}: latency or timestamps unknown")
            if V.norm_text(fr.get("expected_behavior")) != V.norm_text(fr.get("observed_behavior")):
                sl.review("flow_behavior_mismatch", ent,
                          f"Check {ent['check_id']}: observed '{fr.get('observed_behavior')}' vs expected "
                          f"'{fr.get('expected_behavior')}'. Is this an actual flow error?", evidence=ev,
                          outcomes={"flow_error": {"severity": "Warning", "recommendation": "Owner-reviewed fix."},
                                    "material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                                   "Prioritize; cite material impact."},
                                    "pending_or_policy": {"severity": "Info", "recommendation":
                                                          "New link or policy restriction; re-check later."},
                                    "equivalent": {"severity": None, "recommendation": "Wording only."}},
                          guidance="Critical needs proposal.evidence_ref.")

    # -- step 8: discrepancy routing
    dr = ctx.check("discrepancy_routing", "Align bases before reconciling via skill 071",
                   {MAP: ["business_event_id", "attribution_model", "lookback_days", "date_basis", "timezone",
                          "currency"]})
    if dr.runnable:
        bases: dict[str, set[tuple]] = {}
        for r in ctx.rows(MAP):
            bases.setdefault(_s(r.get("business_event_id")), set()).add(tuple(
                V.norm_text(r.get(k)) for k in ("attribution_model", "lookback_days", "date_basis", "timezone",
                                                "currency")))
        mixed = sorted(be for be, s in bases.items() if be and len(s) > 1)
        dr.observe("Business events with misaligned measurement bases (route to 071, not integration failure)",
                   business_events=mixed)

    # -- step 9: owner-reviewed proposals
    op = ctx.check("owner_proposals", "Scoped owner-reviewed flow/goal corrections")
    if not (li.runnable or at.runnable or go.runnable or sl.runnable or ri.runnable):
        op.skip("no link, flow or goal evaluation ran", sorted(set(li.missing + go.missing + sl.missing)))
    else:
        op.observe("Links needing owner-reviewed correction (no permission grants, linking or imports)",
                   links=sorted(set(warned)))


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcome needs proposal.evidence_ref."""
    if decision.get("outcome") == "material_failure_evidenced" and not _s((decision.get("proposal") or {})
                                                                          .get("evidence_ref")):
        return ["material_failure_evidenced needs proposal.evidence_ref pointing at supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
