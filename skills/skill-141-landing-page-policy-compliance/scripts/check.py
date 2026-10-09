"""check.py — skill-141 deterministic landing-page policy evidence inventory and classification.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-141-landing-page-policy-compliance/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Active destination = ads.final_url (and keywords.final_url overrides) of ENABLED ads/keywords in campaigns
         not known to be paused/removed. URLs join after normalization (lowercase scheme/host, no fragment,
         trailing '/' dropped); never by page titles.
         Requirements apply only when requirement.market equals evidence market AND applicability_reason and
         official_policy_url are supplied; no universal privacy/contact/speed rule is imposed.
         Whether page content conflicts with a requirement is policy interpretation → ai_review (Warning outcome).
         Missing page/privacy/authorization evidence is Info (unknown), never a violation or a pass.
         HTTP >= 400 / fetch error on an active destination at its latest capture → Info + review; Critical only
         via review with proposal.evidence_ref (materiality is not in the supplied evidence).
         TLS/mobile/timing issues are technical best-practice (Info), never policy violations or QS loss.
         Platform status: an Ads approval never proves page privacy/TLS/accuracy; disapproval/limitation is
         platform-reported (Info + review), kept separate from observed content mismatch.
         No legal certification, page edits or account changes.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-141-landing-page-policy-compliance"
VERSION = "1.0.0"

PE = "external/page_policy_evidence"
PR = "external/page_policy_requirements"
PS = "custom/page_policy_status"
_OK = ("pass", "passed", "ok", "valid", "success", "true")
_INACTIVE = ("PAUSED", "REMOVED")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _norm_url(u) -> str:
    s = _s(u)
    if not s:
        return ""
    p = urlsplit(s)
    path = p.path.rstrip("/")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def _active_destinations(ctx) -> dict[str, dict]:
    """url → {ad_ids, keyword_ids, campaign_ids} for ENABLED ads/keywords in not-inactive campaigns."""
    camp = {_s(c.get("id")): _s(c.get("status")).upper() for c in ctx.rows("campaigns")}
    out: dict[str, dict] = {}

    def add(url, kind, rid, cid):
        u = _norm_url(url)
        if not u or camp.get(cid, "") in _INACTIVE:
            return
        d = out.setdefault(u, {"ad_ids": set(), "keyword_ids": set(), "campaign_ids": set()})
        d[kind].add(rid)
        d["campaign_ids"].add(cid)

    for a in ctx.rows("ads"):
        if _s(a.get("status")).upper() in ("ENABLED", ""):
            add(a.get("final_url"), "ad_ids", _s(a.get("id")), _s(a.get("campaign_id")))
    kw = ctx.table("keywords")
    if kw is not None and "final_url" in kw.columns:
        for k in kw.rows:
            if _s(k.get("status")).upper() in ("ENABLED", ""):
                add(k.get("final_url"), "keyword_ids", _s(k.get("id")), _s(k.get("campaign_id")))
    return out


def _latest(rows, key_cols, time_col) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: _s(r.get(time_col))):
        out[tuple(_norm_url(r.get(c)) if c in ("final_url", "affected_url") else _s(r.get(c)) for c in key_cols)] = r
    return out


def run(ctx) -> None:
    """Run active-destination, market requirement, page-content, HTTP status and platform-status policy checks.

    Rules:   Requirements apply only with matching market, applicability_reason and official_policy_url; no universal
             rules. Content conflicts → ai_review Warning; missing evidence → Info unknown, never violation or pass.
             HTTP >= 400 at latest capture → Info + review; Critical only via review with proposal.evidence_ref.
             TLS/mobile/timing are Info best-practice; Ads approval never proves page compliance. No legal
             certification.
    """
    dests = _inventory(ctx)
    _diagnostics(ctx, dests)
    _requirements(ctx, dests)
    _platform(ctx)


def _inventory(ctx) -> dict:
    """Step 1: active destinations mapped to page evidence and applicable requirements."""
    chk = ctx.check("destination_inventory", "Active destinations and evidence coverage",
                    {"ads": ["id", "campaign_id", "status", "final_url"], "campaigns": ["id", "status"]})
    if not chk.runnable:
        return {}
    dests = _active_destinations(ctx)
    pe = ctx.table(PE)
    covered = {_norm_url(r.get("final_url")) for r in pe.rows} if pe is not None and "final_url" in pe.columns else None
    if covered is None:
        chk.partial("page evidence missing: destinations cannot be mapped to page content", [f"{PE}:final_url"])
    reqs = ctx.rows(PR)
    if ctx.table(PR) is None:
        chk.partial("requirements missing: no applicable policy requirement is known", [f"{PR} (file)"])
    unusable = [_s(r.get("requirement_id")) for r in reqs
                if not _s(r.get("applicability_reason")) or not _s(r.get("official_policy_url"))]
    if unusable:
        chk.partial(f"requirements without applicability_reason/official_policy_url not applied: {sorted(unusable)}")
    for url in sorted(dests):
        d = dests[url]
        chk.observe(f"Active destination {url}", final_url=url, ad_ids=sorted(d["ad_ids"]),
                    keyword_ids=sorted(d["keyword_ids"]), campaign_ids=sorted(d["campaign_ids"]),
                    page_evidence=None if covered is None else url in covered)
        if covered is not None and url not in covered:
            chk.finding("missing_page_evidence", "Info", {"final_url": url, "campaign_ids": sorted(d["campaign_ids"])},
                        f"Active destination {url} has no supplied page snapshot/diagnostics",
                        evidence={"ad_ids": sorted(d["ad_ids"]), "keyword_ids": sorted(d["keyword_ids"])},
                        recommendation="Capture a dated page snapshot and diagnostics for each market/device.",
                        uncertainty="Unknown page content is not a violation and not a pass.")
    return dests


def _diagnostics(ctx, dests: dict) -> None:
    """Steps 2/5: latest technical diagnostics per URL/market/device."""
    chk = ctx.check("page_diagnostics", "Destination technical diagnostics (latest capture)",
                    {PE: ["final_url", "market", "device", "captured_at", "http_status", "tls_result",
                          "mobile_task_result", "test_method"]})
    if not chk.runnable:
        return
    latest = _latest(ctx.rows(PE), ("final_url", "market", "device"), "captured_at")
    for key in sorted(latest):
        r = latest[key]
        url, market, device = key
        active = url in dests
        entity = {"final_url": url, "market": market, "device": device}
        ev = {"captured_at": r.get("captured_at"), "http_status": r.get("http_status"),
              "tls_result": r.get("tls_result"), "mobile_task_result": r.get("mobile_task_result"),
              "timing_metric": r.get("timing_metric"), "timing_value": r.get("timing_value"),
              "test_method": r.get("test_method"), "page_snapshot_ref": r.get("page_snapshot_ref"),
              "active": active, "ad_ids": sorted(dests.get(url, {}).get("ad_ids", []))}
        status = V.integer(r.get("http_status"))
        failed = (status is not None and status >= 400) or (status is None and _s(r.get("http_status")).lower()
                                                            in ("error", "timeout", "dns_error", "failed"))
        if failed and active:
            prov = chk.finding("destination_failure", "Info", entity,
                               f"Active destination {url} ({market}/{device}) returned {r.get('http_status')} at "
                               f"{r.get('captured_at')}", evidence=ev,
                               recommendation="Route to skill-125 for monitoring and to the page owner for a fix.",
                               uncertainty="Single capture; serving exposure not measured here.")
            chk.review("destination_failure", entity,
                       f"Is the {r.get('http_status')} failure of {url} a confirmed MATERIAL active destination "
                       f"failure (serving ads, persistent)?",
                       evidence=ev,
                       outcomes={"material_destination_failure": {"severity": "Critical", "recommendation":
                                                                  "Prioritize the page fix; cite serving evidence."},
                                 "transient_or_not_material": {"severity": "Info", "recommendation":
                                                               "Recheck at the next capture."},
                                 "uncertain": {"severity": "Info", "recommendation": "Capture again with serving data."}},
                       guidance="Critical needs proposal.evidence_ref to serving/persistence evidence.",
                       provisional=prov)
        elif failed:
            chk.observe(f"{url}: failed capture but not an active destination", **entity, **ev)
        for col, key_ in (("tls_result", "tls_issue"), ("mobile_task_result", "mobile_task_failure")):
            val = _s(r.get(col)).lower()
            if val and val not in _OK and active:
                chk.finding(key_, "Info", entity, f"{url} ({market}/{device}): {col} '{r.get(col)}'",
                            evidence=ev, recommendation="Technical best-practice follow-up with the web owner.",
                            uncertainty="Technical issue alone does not establish a policy violation or QS loss.")
        if not failed:
            chk.observe(f"{url} ({market}/{device}) diagnostics", **entity, **ev)


def _requirements(ctx, dests: dict) -> None:
    """Steps 1/3/4: page evidence vs applicable documented requirements (interpretation → review)."""
    chk = ctx.check("requirement_review", "Page evidence vs applicable documented requirements",
                    {PE: ["final_url", "market", "captured_at", "page_snapshot_ref", "visible_business_identity",
                          "contact_details", "privacy_link_and_text_ref", "data_collected", "offer_and_claim_text"],
                     PR: ["requirement_id", "market", "product", "use_case", "official_policy_url", "checked_at",
                          "requirement_text", "applicability_reason", "authorization_or_certification_ref",
                          "reviewer_role"]})
    if not chk.runnable:
        return
    latest = _latest(ctx.rows(PE), ("final_url", "market"), "captured_at")
    reqs = sorted((r for r in ctx.rows(PR) if _s(r.get("applicability_reason")) and _s(r.get("official_policy_url"))),
                  key=lambda r: _s(r.get("requirement_id")))
    for (url, market) in sorted(latest):
        r = latest[(url, market)]
        if url not in dests:
            continue
        page = {k: r.get(k) for k in ("captured_at", "page_snapshot_ref", "visible_business_identity",
                                      "contact_details", "privacy_link_and_text_ref", "data_collected",
                                      "offer_and_claim_text")}
        collected = _s(r.get("data_collected"))
        if collected and V.boolean(collected) is not False and not collected.lower().startswith("none") \
                and not _s(r.get("privacy_link_and_text_ref")):
            chk.finding("missing_privacy_evidence", "Info", {"final_url": url, "market": market},
                        f"{url} ({market}) collects '{r.get('data_collected')}' but no privacy link/text evidence "
                        f"was supplied", evidence=page,
                        recommendation="Request privacy evidence and specialist review; no legal conclusion.",
                        uncertainty="Missing evidence is unknown, not a confirmed violation.")
        applicable = [q for q in reqs if _s(q.get("market")) == market]
        if not applicable:
            chk.observe(f"{url} ({market}): no applicable documented requirement", final_url=url, market=market)
            continue
        for q in applicable:
            rid = _s(q.get("requirement_id"))
            entity = {"final_url": url, "market": market, "requirement_id": rid}
            chk.review("page_requirement_conflict", entity,
                       f"Does the supplied page evidence for {url} ({market}) conflict with requirement {rid}?",
                       evidence={"page": page, "requirement": {k: q.get(k) for k in sorted(q)},
                                 "ad_ids": sorted(dests[url]["ad_ids"])},
                       outcomes={"conflicts_requirement": {"severity": "Warning", "recommendation":
                                                           "Evidence-backed remediation with policy and page owners."},
                                 "meets_requirement": {"severity": None, "recommendation": "Record; no certification."},
                                 "not_applicable": {"severity": None, "recommendation": "Record the reason."},
                                 "evidence_missing_or_uncertain": {"severity": "Info", "recommendation":
                                                                   "Request missing evidence/specialist review."}},
                       guidance="Judge only supplied snapshot text against the requirement text and its official "
                                "source. No legal certification; missing evidence → evidence_missing_or_uncertain. "
                                "conflicts_requirement needs proposal.page_evidence_ref.")


def _platform(ctx) -> None:
    """Step 3: platform-reported policy status, separate from observed content conflicts."""
    chk = ctx.check("platform_status", "Ads policy diagnostics at review time",
                    {PS: ["ad_id", "policy_topic", "snapshot_at", "campaign_id", "approval_status",
                          "serving_limitation", "affected_url", "review_status"]})
    if not chk.runnable:
        return
    latest = _latest(ctx.rows(PS), ("ad_id", "policy_topic"), "snapshot_at")
    active = {_s(a.get("id")) for a in ctx.rows("ads") if _s(a.get("status")).upper() in ("ENABLED", "")}
    for key in sorted(latest):
        r = latest[key]
        ad, topic = key
        appr, lim = _s(r.get("approval_status")).upper(), _s(r.get("serving_limitation")).lower()
        restricted = "DISAPPROVED" in appr or "LIMITED" in appr or any(
            w in lim for w in ("not serving", "not_serving", "limited", "restricted"))
        ev = {k: r.get(k) for k in ("snapshot_at", "approval_status", "serving_limitation",
                                    "affected_url", "review_status")}
        entity = {"ad_id": ad, "policy_topic": topic, "campaign_id": r.get("campaign_id")}
        if not restricted:
            chk.observe(f"Ad {ad} topic {topic}: {appr or 'unknown'} (approval does not certify page)", **entity, **ev)
            continue
        prov = chk.finding("platform_reported_restriction", "Info", entity,
                           f"Ads reports {appr or lim} for ad {ad} on topic '{topic}' ({r.get('affected_url')})",
                           evidence={**ev, "ad_active_in_inventory": ad in active},
                           recommendation="Compare with page evidence; route ad/offer mismatch to skill-034.",
                           uncertainty="Platform classification, not an observed content finding.")
        chk.review("platform_reported_restriction", entity,
                   f"What does the platform restriction on ad {ad} ('{topic}') establish, given the page evidence?",
                   evidence={**ev, "ad_active_in_inventory": ad in active},
                   outcomes={"material_serving_block": {"severity": "Critical", "recommendation":
                                                        "Prioritize remediation; cite serving-loss evidence."},
                             "requirement_conflict_confirmed": {"severity": "Warning", "recommendation":
                                                                "Remediate the page/ad with the policy owner."},
                             "resolved_or_minor": {"severity": "Info", "recommendation": "Monitor at next snapshot."}},
                   guidance="Critical needs proposal.evidence_ref; requirement_conflict_confirmed needs "
                            "proposal.page_evidence_ref.",
                   provisional=prov)


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes need proposal.evidence_ref; requirement conflicts need proposal.page_evidence_ref."""
    outcome, p = decision.get("outcome"), decision.get("proposal") or {}
    if outcome in ("material_destination_failure", "material_serving_block") and not p.get("evidence_ref"):
        return [f"{outcome} needs proposal.evidence_ref"]
    if outcome in ("conflicts_requirement", "requirement_conflict_confirmed") and not p.get("page_evidence_ref"):
        return [f"{outcome} needs proposal.page_evidence_ref (page snapshot or diagnostics reference)"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
