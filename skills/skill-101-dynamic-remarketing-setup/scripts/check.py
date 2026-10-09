"""check.py — skill-101 deterministic dynamic remarketing linkage, feed status and tag item-ID matching.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-101-dynamic-remarketing-setup/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Scope = campaigns whose dynamic_configuration.intended_dynamic_use is boolean true; false = intentional
         static (observation, never a gap); unknown = coverage. Campaign type alone never implies dynamic.
         merchant_id/feed/list presence never certifies linkage: dynamic_status and link_status are read
         independently; unknown → Info setup_not_certified, never a pass.
         Item matching is EXACT on dynamic_feed_items.item_id within the diagnostic row's feed_scope
         (split list of feed_ids). item_group_id hits are 'parent_id_sent'; a case-only hit is ai_review
         (documented case rule?), never silently accepted. No transformations are invented.
         Test rows are sampled diagnostics: rates carry the tested-row denominator and never stand for a
         production-wide rate or campaign spend.
         Absence (feed without items) is a finding only when the feed table's manifest certifies completeness.
         Critical only via review (material delivery block or consent-denied payload) with proposal.evidence_ref.
         Correction proposals (link/tag/list) need activation permission 'permitted' for the campaign's linked
         lists (audiences.list_id+campaign_id → audience_definitions.source_id); else Info blocked.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks11 | initial deterministic check
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

SKILL = "skill-101-dynamic-remarketing-setup"
VERSION = "1.0.0"

CFG = "external/dynamic_configuration"
FEED = "external/dynamic_feed_items"
TAG = "external/dynamic_tag_diagnostics"
DEFS = "external/audience_definitions"
PERM = "external/activation_permissions"
_LINK_BAD = {"unlinked", "not linked", "not_linked", "failed", "rejected", "removed", "disconnected", "revoked"}
_LINK_OK = {"linked", "active", "enabled", "approved"}
_ELIGIBLE = {"eligible", "approved", "active"}
_DISAPPROVED = {"disapproved", "not eligible", "not_eligible", "ineligible"}
_OOS = {"out of stock", "out_of_stock", "outofstock"}
_CONSENT_DENIED = {"denied", "declined", "rejected", "granted=false"}
_SENT = {"sent", "ok", "received", "fired", "valid"}
_GRANTED = {"granted", "approved", "permitted", "verified", "yes", "true"}
_DENIED = {"denied", "revoked", "withdrawn", "rejected", "expired", "no", "false"}
_CONSENT_OK = {"covered", "complete", "verified", "not_required", "not required", "not_applicable", "not applicable"}
_ADS_DEST = {"google ads", "google_ads", "google-ads", "ads"}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _tokens(v) -> set[str]:
    return {V.norm_text(x) for x in V.split_list(v)}


def _permission(ctx, list_id: str, source_id: str) -> tuple[str, str, list]:
    t = ctx.table(PERM)
    if t is None:
        return "unknown", f"{PERM} (file) missing", []
    rows = [r for r in t.rows if (list_id and _s(r.get("list_id")) == list_id)
            or (not _s(r.get("list_id")) and source_id and _s(r.get("source_id")) == source_id)]
    if not rows:
        return "unknown", f"no permission row for list {list_id} / source {source_id or '-'}", []
    refs = sorted({_s(r.get("evidence_reference")) for r in rows if _s(r.get("evidence_reference"))})
    if any(V.norm_text(r.get("permission_status")) in _DENIED for r in rows):
        return "denied", "permission_status denied/revoked", refs
    for r in rows:
        if (V.norm_text(r.get("permission_status")) in _GRANTED
                and V.norm_text(r.get("consent_coverage_status")) in _CONSENT_OK
                and _tokens(r.get("permitted_destinations")) & _ADS_DEST):
            return "permitted", "granted, consent covered, Google Ads destination permitted", refs
    return "unknown", "permission, consent coverage or Google Ads destination not evidenced", refs


def _critical(chk, key, entity, question, ev):
    chk.review(key, entity, question, evidence=ev,
               outcomes={"material_block_evidenced": {"severity": "Critical", "recommendation":
                                                      "Prioritize the correction; cite the delivery evidence."},
                         "not_material": {"severity": None, "recommendation": "Keep as Warning."}},
               guidance="Critical needs proposal.evidence_ref to supplied delivery/diagnostic evidence.")


def run(ctx) -> None:
    """Run dynamic scope, linkage, feed item, item-match, consent review and correction-permission checks.

    Rules:   Scope only where intended_dynamic_use is true; false = intentional static, unknown → partial. Unknown
             link/dynamic status → Info setup_not_certified, never a pass. Feed without (eligible) items → Warning only
             with a manifest-certified feed table, else partial; item mismatches and case-only hits are ai_review.
             Critical only via review with proposal.evidence_ref; corrections without 'permitted' activation → Info
             blocked.
    """
    scope = ctx.check("intent_scope", "Declared dynamic objective versus intentional static setups",
                      {"campaigns": ["id"], CFG: ["campaign_id", "intended_dynamic_use", "business_vertical",
                                                  "campaign_subtype"]})
    titles = (("linkage_enablement", "Independent Ads/feed linkage and dynamic enablement"),
              ("feed_status", "Processed feed status for intended dynamic feeds"),
              ("item_id_match", "Event item IDs versus full feed keys"),
              ("diagnostic_coverage", "Representative diagnostic cases and consent states"),
              ("activation_permission", "Permission gate for link/tag/list correction proposals"))
    if not scope.runnable:
        for cid, title in titles:
            ctx.check(cid, title).skip("dynamic configuration unavailable", scope.missing)
        return
    camp_ids = {_s(r.get("id")) for r in ctx.rows("campaigns")}
    cfg: dict[str, dict] = {}
    for r in sorted(ctx.rows(CFG), key=lambda r: _s(r.get("campaign_id"))):
        cid = _s(r.get("campaign_id"))
        if cid not in camp_ids:
            scope.partial(f"configuration row for campaign {cid} outside the campaign inventory",
                          [f"{CFG}:campaign_id"])
            continue
        cfg.setdefault(cid, r)
    intended = sorted(c for c, r in cfg.items() if V.boolean(r.get("intended_dynamic_use")) is True)
    static = sorted(c for c, r in cfg.items() if V.boolean(r.get("intended_dynamic_use")) is False)
    unknown = sorted(c for c, r in cfg.items() if V.boolean(r.get("intended_dynamic_use")) is None)
    if unknown:
        scope.partial(f"intended_dynamic_use unknown for campaigns {unknown}")
    scope.observe("Dynamic intent scope", intended_dynamic=intended, intentional_static=static,
                  unknown_intent=unknown, campaigns_without_configuration=len(camp_ids - set(cfg)),
                  note="static Display/Shopping/PMax are not automatically dynamic remarketing")
    needs_fix: set[str] = set()

    # -- step 2: linkage and enablement
    link = ctx.check("linkage_enablement", "Independent Ads/feed linkage and dynamic enablement",
                     {CFG: ["campaign_id", "dynamic_status", "feed_type", "feed_id", "merchant_id",
                            "linked_account_id", "link_status"]})
    if link.runnable:
        for cid in intended:
            r = cfg[cid]
            ent = {"campaign_id": cid, "feed_id": _s(r.get("feed_id")) or None}
            ev = {k: r.get(k) for k in ("dynamic_status", "link_status", "feed_type", "merchant_id",
                                        "linked_account_id", "destination", "eligibility", "observed_at",
                                        "source_reference")}
            status, ls = V.norm_text(r.get("dynamic_status")), V.norm_text(r.get("link_status"))
            problems = []
            if status == "disabled":
                problems.append(("dynamic_disabled", "dynamic ads are disabled although dynamic use is intended"))
            if ls in _LINK_BAD:
                problems.append(("link_not_active", f"feed/account link is '{r.get('link_status')}'"))
            mid, lid = _s(r.get("merchant_id")), _s(r.get("linked_account_id"))
            if mid and lid and mid != lid:
                problems.append(("linked_account_mismatch", f"linked account {lid} differs from feed merchant {mid}"))
            for key, msg in problems:
                needs_fix.add(cid)
                link.finding(key, "Warning", ent, f"Campaign {cid}: {msg}", evidence=ev,
                             recommendation="Owner-reviewed correction of the verified path; no automatic enablement.",
                             uncertainty="Configuration as observed; delivery impact not measured here.")
                _critical(link, key, ent, f"Does '{key}' for campaign {cid} materially block intended dynamic "
                                          f"delivery?", ev)
            if not problems and (status not in ("enabled",) or ls not in _LINK_OK):
                link.finding("setup_not_certified", "Info", ent,
                             f"Campaign {cid}: dynamic_status '{r.get('dynamic_status')}' / link_status "
                             f"'{r.get('link_status')}' cannot certify the dynamic setup", evidence=ev,
                             recommendation="Supply current Ads/feed linkage and enablement evidence.",
                             uncertainty="Unknown is not disabled.")
            elif not problems:
                link.observe(f"Campaign {cid}: enabled and linked (item matching still required)", campaign_id=cid)

    # -- step 3: processed feed status
    feed_rows: dict[str, list[dict]] = {}
    for r in ctx.rows(FEED):
        feed_rows.setdefault(_s(r.get("feed_id")), []).append(r)
    fs = ctx.check("feed_status", "Processed feed status for intended dynamic feeds",
                   {FEED: ["feed_id", "item_id", "availability", "eligibility_status"],
                    CFG: ["campaign_id", "feed_id"]})
    if fs.runnable:
        t = ctx.table(FEED)
        certified = t.complete is True and not t.truncated
        for cid in intended:
            fid = _s(cfg[cid].get("feed_id"))
            ent = {"campaign_id": cid, "feed_id": fid or None}
            if not fid:
                fs.partial(f"campaign {cid}: feed_id unknown", [f"{CFG}:feed_id"])
                continue
            items = feed_rows.get(fid, [])
            if not items:
                if certified:
                    needs_fix.add(cid)
                    fs.finding("feed_has_no_items", "Warning", ent,
                               f"Feed {fid} for intended dynamic campaign {cid} has no items in the certified feed",
                               evidence={"feed_rows": 0, "manifest_complete": True},
                               recommendation="Feed owner to restore the processed feed/link.",
                               uncertainty="Snapshot-only evidence.")
                    _critical(fs, "feed_has_no_items", ent, f"Does the empty feed {fid} materially block delivery?",
                              {"feed_id": fid})
                else:
                    fs.partial(f"feed {fid}: no rows and completeness not certified")
                continue
            elig = sum(1 for r in items if V.norm_text(r.get("eligibility_status")) in _ELIGIBLE)
            disap = sum(1 for r in items if V.norm_text(r.get("eligibility_status")) in _DISAPPROVED)
            unk = len(items) - elig - disap
            oos = sum(1 for r in items if V.norm_text(r.get("availability")) in _OOS)
            ev = {"items": len(items), "eligible": elig, "disapproved": disap, "unknown_status": unk,
                  "out_of_stock": oos, "eligible_share": V.ratio(elig, len(items)),
                  "snapshot_at": sorted({_s(r.get("snapshot_at")) for r in items if _s(r.get("snapshot_at"))})}
            fs.observe(f"Feed {fid} status (retail attribute detail → skill 083)", feed_id=fid, **ev)
            if elig == 0 and unk == 0:
                needs_fix.add(cid)
                fs.finding("feed_no_eligible_items", "Warning", ent,
                           f"Feed {fid}: 0 of {len(items)} items eligible for intended dynamic campaign {cid}",
                           evidence=ev, recommendation="Resolve item issues (skill 083) before relying on dynamic ads.",
                           uncertainty="Eligibility as of snapshot.")
                _critical(fs, "feed_no_eligible_items", ent, f"Do 0 eligible items in feed {fid} materially block "
                                                             f"delivery?", ev)
            elif unk:
                fs.partial(f"feed {fid}: {unk} items with unknown eligibility")

    # -- step 4: item-ID matching
    im = ctx.check("item_id_match", "Event item IDs versus full feed keys",
                   {TAG: ["test_id", "item_index", "event_name", "feed_scope", "actual_item_id", "expected_item_id"],
                    FEED: ["feed_id", "item_id", "item_group_id"]})
    tested = mismatched = 0
    if im.runnable:
        intended_feeds = sorted({_s(cfg[c].get("feed_id")) for c in intended if _s(cfg[c].get("feed_id"))})
        no_scope = 0
        for r in sorted(ctx.rows(TAG), key=lambda r: (_s(r.get("test_id")), _s(r.get("item_index")))):
            feeds = sorted({_s(x) for x in V.split_list(r.get("feed_scope"))}) or intended_feeds
            if not V.split_list(r.get("feed_scope")):
                no_scope += 1
            ids = {_s(i.get("item_id")) for f in feeds for i in feed_rows.get(f, []) if _s(i.get("item_id"))}
            groups = {_s(i.get("item_group_id")) for f in feeds for i in feed_rows.get(f, [])
                      if _s(i.get("item_group_id"))}
            actual, expected = _s(r.get("actual_item_id")), _s(r.get("expected_item_id"))
            ent = {"test_id": _s(r.get("test_id")), "item_index": _s(r.get("item_index")) or None,
                   "event_name": _s(r.get("event_name"))}
            ev = {"actual_item_id": actual or None, "expected_item_id": expected or None, "feed_scope": feeds,
                  "tested_at": r.get("tested_at"), "page_reference": r.get("page_reference"),
                  "source_reference": r.get("source_reference")}
            tested += 1
            key = None
            if not actual:
                if expected:
                    key, msg = "item_id_missing_in_payload", "payload carries no item ID"
            elif actual in ids:
                if expected and actual != expected:
                    key, msg = "wrong_item_or_variant", f"sent {actual}, expected {expected}"
            elif actual in groups:
                key, msg = "parent_id_sent", f"sent item_group_id {actual} instead of an offer/item ID"
            elif actual.lower() in {i.lower() for i in ids}:
                mismatched += 1
                im.review("case_only_match", ent, f"Test {ent['test_id']}: '{actual}' matches a feed ID only "
                                                  f"case-insensitively. Is a documented case rule in force?",
                          evidence=ev, outcomes={"mismatch": {"severity": "Warning", "recommendation":
                                                              "Align tag and feed ID casing at the source."},
                                                 "documented_rule": {"severity": None, "recommendation":
                                                                     "Cite the rule; no change."},
                                                 "uncertain": {"severity": "Info", "recommendation":
                                                               "Confirm the namespace/case rule with the spec."}},
                          guidance="Only the supplied applicable_parameter_specification counts as documentation.")
                continue
            else:
                key, msg = "unmapped_item_id", f"sent {actual}, absent from feed(s) {feeds}"
            if key:
                mismatched += 1
                im.finding(key, "Warning", ent, f"Test {ent['test_id']} ({ent['event_name']}): {msg}", evidence=ev,
                           recommendation="Trace to the feed/tag source; correct the item ID mapping.",
                           uncertainty="Single sampled test; not a production-wide rate.")
                for c in intended:
                    if _s(cfg[c].get("feed_id")) in feeds:
                        needs_fix.add(c)
        if no_scope:
            im.partial(f"{no_scope} diagnostic rows without feed_scope matched against all intended feeds")
        im.observe("Sampled item-ID matching", tested_rows=tested, mismatched_rows=mismatched,
                   mismatch_rate_of_tested=V.ratio(mismatched, tested))

    # -- step 5: representative diagnostics and consent
    dc = ctx.check("diagnostic_coverage", "Representative diagnostic cases and consent states",
                   {TAG: ["test_id", "tested_at", "event_name", "consent_state", "observed_payload_status",
                          "actual_item_id"]})
    if dc.runnable:
        rows = ctx.rows(TAG)
        events = sorted({_s(r.get("event_name")) for r in rows if _s(r.get("event_name"))})
        consents = sorted({V.norm_text(r.get("consent_state")) for r in rows if _s(r.get("consent_state"))})
        ev = {"tests": len({_s(r.get("test_id")) for r in rows}), "rows": len(rows), "events": events,
              "consent_states": consents, "tested_rows": tested, "mismatched_rows": mismatched,
              "tested_window": [min((_s(r.get("tested_at")) for r in rows), default=None),
                                max((_s(r.get("tested_at")) for r in rows), default=None)]}
        dc.observe("Diagnostic coverage (sampled, not production)", **ev)
        if rows:
            dc.review("diagnostic_coverage", {"scope": "dynamic_tag_diagnostics"},
                      "Do the sampled diagnostics cover product, cart, purchase, variant and unavailable-item cases "
                      "for every intended dynamic vertical?", evidence=ev,
                      outcomes={"representative": {"severity": None, "recommendation": "Coverage adequate."},
                                "coverage_gaps": {"severity": "Info", "recommendation":
                                                  "Add the missing representative cases before certifying."}},
                      guidance="Event naming differs by vertical; judge against the supplied parameter specification.")
        for r in sorted(rows, key=lambda r: (_s(r.get("test_id")), _s(r.get("item_index")))):
            if (V.norm_text(r.get("consent_state")) in _CONSENT_DENIED and _s(r.get("actual_item_id"))
                    and V.norm_text(r.get("observed_payload_status")) in _SENT):
                ent = {"test_id": _s(r.get("test_id")), "item_index": _s(r.get("item_index")) or None}
                dc.review("consent_denied_payload", ent,
                          f"Test {ent['test_id']} sent item data with consent '{r.get('consent_state')}'. Is this "
                          f"directly evidenced unsafe data use?",
                          evidence={k: r.get(k) for k in ("consent_state", "observed_payload_status", "parameter_names",
                                                          "tag_destination_id", "source_reference", "tested_at")},
                          outcomes={"unsafe_use_evidenced": {"severity": "Critical", "recommendation":
                                                             "Stop the unsafe path via the tag owner; skill 075/156."},
                                    "consent_mode_compliant": {"severity": None, "recommendation":
                                                               "Documented consent-mode behaviour; no change."},
                                    "uncertain": {"severity": "Info", "recommendation": "Request a consent trace."}},
                          guidance="Cookieless/modeled pings can be compliant; Critical needs proposal.evidence_ref.")

    # -- step 6: permission gate for corrections
    ap = ctx.check("activation_permission", "Permission gate for link/tag/list correction proposals",
                   {PERM: ["source_id", "list_id", "permission_status", "consent_coverage_status",
                           "permitted_destinations", "evidence_reference"],
                    "audiences": ["list_id", "campaign_id"], DEFS: ["list_id", "source_id"]})
    if ap.runnable:
        src = {_s(r.get("list_id")): _s(r.get("source_id")) for r in ctx.rows(DEFS)}
        for cid in sorted(needs_fix):
            lists = sorted({_s(r.get("list_id")) for r in ctx.rows("audiences")
                            if _s(r.get("campaign_id")) == cid and _s(r.get("list_id"))})
            res = {lid: _permission(ctx, lid, src.get(lid, "")) for lid in lists}
            if lists and all(v[0] == "permitted" for v in res.values()):
                ap.observe(f"Campaign {cid}: correction proposals permitted", lists=lists)
                continue
            ap.finding("correction_blocked_permission", "Info", {"campaign_id": cid},
                       f"Campaign {cid}: link/tag/list correction proposals are blocked pending permission evidence",
                       evidence={"lists": {k: v[:2] for k, v in res.items()} or "no linked lists evidenced"},
                       recommendation="Obtain permitted-use and consent evidence (skill 156) before any proposal.",
                       uncertainty="Missing or denied permission.")
    elif needs_fix:
        ap.notes.append(f"correction proposals blocked (permission evidence unavailable): {sorted(needs_fix)}")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes need proposal.evidence_ref."""
    if decision.get("outcome") in ("material_block_evidenced", "unsafe_use_evidenced") and not _s(
            (decision.get("proposal") or {}).get("evidence_ref")):
        return ["Critical outcome needs proposal.evidence_ref pointing at supplied evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
