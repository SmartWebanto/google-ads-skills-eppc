"""check.py — skill-030 deterministic asset association spine, direct/inherited coverage and eligibility.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-030-ad-extension-coverage-audit/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #1 Report Ad Groups that don't have RSAs (nilsrooijmans.com) — clean-room reuse as spine eligibility:
         enabled ad groups without an enabled RSA are marked non-serving in the asset spine (finding owned by skill-025)
rules:   Canonical export/assets only. Columns: asset_id, type|asset_type, level|association_level,
         association_status|status, campaign_id, ad_group_id; optional approval_status|approval, start_date,
         end_date, text. Alternatives are resolved explicitly, never fuzzily.
         Removed links never count as coverage. Account/campaign links are shown as POTENTIAL inherited coverage;
         no universal nearest-level override rule is applied.
         Absence findings (optional_asset_type_absent, Info) require a manifest-complete assets table; the
         evaluated types are profile.intended_asset_types, else types already used in this account's inventory.
         No count quotas (no 'four sitelinks'). Ineligible/disabled intended links (paused/disapproved/expired/
         not-yet-started) are ai_review; the Warning outcome needs proposal.evidence_ref equal to one of the item's
         evidence_refs: documented intent in profile.intended_asset_types (the asset type) or
         profile.campaign_objectives (the entity's campaign). No documented intent → no Warning.
         Parent-paused entities are outside the eligible spine, not asset defects. No CTR uplift forecasts.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | Warning evidence_ref restricted to documented-intent refs
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-030-ad-extension-coverage-audit"
VERSION = "1.0.0"

SPINE_NEEDS = {"campaigns": ["id", "status", "channel_type"], "ad_groups": ["id", "campaign_id", "status"]}
_ALT = {"type": ("type", "asset_type"), "level": ("level", "association_level"),
        "association_status": ("association_status", "status"), "approval": ("approval_status", "approval")}
_LEVELS = {"ACCOUNT": "account", "CUSTOMER": "account", "CAMPAIGN": "campaign", "AD_GROUP": "ad_group",
           "ADGROUP": "ad_group"}
_SUPPORTED_CHANNELS = ("SEARCH",)


def _norm(v) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(v or "")).casefold().split())


def _cols(ctx) -> dict:
    t = ctx.table("assets")
    cols = t.columns if t else []
    return {k: next((c for c in names if c in cols), names[0]) for k, names in _ALT.items()}


def _intent_refs(ctx, typ: str, campaign_id: str | None) -> list[str]:
    """Refs to documented intent for this asset type / campaign in the client profile."""
    refs = []
    if typ in {str(x).upper() for x in (ctx.profile.get("intended_asset_types") or [])}:
        refs.append(f"profile.intended_asset_types:{typ}")
    objs = ctx.profile.get("campaign_objectives") or {}
    if campaign_id and isinstance(objs, dict) and any(str(k) == campaign_id and v for k, v in objs.items()):
        refs.append(f"profile.campaign_objectives:{campaign_id}")
    return refs


def run(ctx) -> None:
    """Run asset spine, direct/inherited coverage, eligibility, completeness, absence and duplicate-text checks.

    Rules:   Missing asset inventory or entity spine skips every check. Removed links never count as coverage;
             account/campaign links are potential inherited coverage only; no count quotas. optional_asset_type_absent
             (Info) needs a manifest-complete assets table and profile.intended_asset_types (else used types).
             Ineligible intended links are ai_review — Warning needs proposal.evidence_ref; duplicate asset text is
             Info.
    """
    spine = ctx.check("entity_spine", "Eligible campaign/ad-group spine", SPINE_NEEDS)
    camps, groups = {}, {}
    if spine.runnable:
        for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
            if str(c.get("status") or "").upper() == "ENABLED" and \
                    str(c.get("channel_type") or "").upper() in _SUPPORTED_CHANNELS:
                camps[str(c.get("id"))] = c
        for g in sorted(ctx.rows("ad_groups"), key=lambda r: str(r.get("id"))):
            if str(g.get("status") or "").upper() == "ENABLED" and str(g.get("campaign_id")) in camps:
                groups[str(g.get("id"))] = g
        no_rsa = None
        ads_t = ctx.table("ads")
        if ads_t is not None and not ads_t.missing(["ad_group_id", "type", "status"]):
            if ads_t.complete is True and not ads_t.truncated:
                serving = {str(a.get("ad_group_id")) for a in ads_t.rows
                           if str(a.get("type") or "").upper() == "RESPONSIVE_SEARCH_AD"
                           and str(a.get("status") or "").upper() == "ENABLED"}
                no_rsa = sorted(g for g in groups if g not in serving)
            else:
                spine.partial("ads inventory not certified complete: ad groups without an RSA unknown")
        else:
            spine.partial("ads inventory unavailable: ad-group serving eligibility unknown", ["ads:ad_group_id", "ads:type",
                                                                                              "ads:status"])
        spine.observe("Eligible spine (enabled Search campaigns and ad groups)", campaigns=sorted(camps),
                      ad_groups=sorted(groups), ad_groups_without_enabled_rsa=no_rsa,
                      excluded_campaigns=sorted(str(c.get("id")) for c in ctx.rows("campaigns")
                                                if str(c.get("id")) not in camps))

    col = _cols(ctx)
    a_needs = {"assets": ["asset_id", col["type"], col["level"], col["association_status"], "campaign_id", "ad_group_id"]}
    inv = ctx.check("association_inventory", "Associations by asset, type, level and entity", a_needs)
    later = (("effective_coverage", "Direct vs potential inherited coverage per entity/type"),
             ("eligibility_intersection", "Association, approval, schedule and parent eligibility"),
             ("inventory_completeness", "Declared inventory completeness per level"),
             ("optional_types", "Optional asset types absent at an eligible entity"),
             ("field_review", "Duplicate text and stale configured dates"),
             ("prioritization", "Owner-review priority of confirmed gaps"))
    if not inv.runnable or not spine.runnable:
        missing = inv.missing + spine.missing
        for cid, title in later:
            ctx.check(cid, title).skip("asset inventory or entity spine unavailable", missing)
        return
    links, unknown_level, removed = [], 0, 0
    for r in sorted(ctx.rows("assets"), key=lambda r: (str(r.get("asset_id")), str(r.get(col["level"])),
                                                       str(r.get("campaign_id")), str(r.get("ad_group_id")))):
        level = _LEVELS.get(str(r.get(col["level"]) or "").upper().replace(" ", "_"))
        if level is None:
            unknown_level += 1
            continue
        status = str(r.get(col["association_status"]) or "").upper()
        if status == "REMOVED":
            removed += 1
            continue
        links.append({"asset_id": str(r.get("asset_id")), "type": str(r.get(col["type"]) or "").upper(),
                      "level": level, "campaign_id": str(r.get("campaign_id") or ""),
                      "ad_group_id": str(r.get("ad_group_id") or ""), "status": status or None,
                      "approval": str(r.get(col["approval"]) or "").upper() or None,
                      "start": V.parse_date(r.get("start_date")), "end": V.parse_date(r.get("end_date")),
                      "text": r.get("text")})
    if unknown_level:
        inv.partial(f"{unknown_level} association rows with unsupported/unknown linking level excluded",
                    [f"assets:{col['level']}"])
    by_type: dict[str, dict] = {}
    for l in links:
        t = by_type.setdefault(l["type"], {"associations": 0, "assets": set(), "levels": {}})
        t["associations"] += 1
        t["assets"].add(l["asset_id"])
        t["levels"][l["level"]] = t["levels"].get(l["level"], 0) + 1
    inv.observe("Association inventory (removed excluded)", removed_links=removed,
                by_type={k: {"associations": v["associations"], "unique_assets": len(v["assets"]),
                             "by_level": v["levels"]} for k, v in sorted(by_type.items())})

    ref = ctx.snapshot or ctx.as_of

    def eligible(l) -> tuple[bool | None, list[str]]:
        why = []
        if l["status"] and l["status"] not in ("ENABLED",):
            why.append(f"association {l['status']}")
        if l["approval"] and ("DISAPPROVED" in l["approval"]):
            why.append(f"approval {l['approval']}")
        if ref and l["end"] and l["end"] < ref:
            why.append(f"ended {l['end']}")
        if ref and l["start"] and l["start"] > ref:
            why.append(f"starts {l['start']}")
        if why:
            return False, why
        return (None if l["status"] is None else True), why

    def direct(entity_level, eid):
        key = "campaign_id" if entity_level == "campaign" else "ad_group_id"
        return [l for l in links if l["level"] == entity_level and l[key] == eid]

    cov = ctx.check("effective_coverage", "Direct vs potential inherited coverage per entity/type", a_needs)
    account_links = [l for l in links if l["level"] == "account"]
    matrix = {}
    for cid in sorted(camps):
        d = direct("campaign", cid)
        matrix[f"campaign:{cid}"] = {t: {"direct": sum(1 for l in d if l["type"] == t and eligible(l)[0] is not False),
                                         "potential_inherited": sum(1 for l in account_links if l["type"] == t
                                                                    and eligible(l)[0] is not False)}
                                     for t in sorted(by_type)}
    for gid, g in sorted(groups.items()):
        d = direct("ad_group", gid)
        up = account_links + direct("campaign", str(g.get("campaign_id")))
        matrix[f"ad_group:{gid}"] = {t: {"direct": sum(1 for l in d if l["type"] == t and eligible(l)[0] is not False),
                                         "potential_inherited": sum(1 for l in up if l["type"] == t
                                                                    and eligible(l)[0] is not False)}
                                     for t in sorted(by_type)}
    cov.observe("Entity × type coverage matrix (potential inherited is not effective serving)", matrix=matrix)
    unknown_status = sum(1 for l in links if l["status"] is None)
    if unknown_status:
        cov.partial(f"{unknown_status} links with unknown association status (unknown is not disabled)")

    # -- step 4: eligibility intersection → review
    elig = ctx.check("eligibility_intersection", "Association, approval, schedule and parent eligibility", a_needs)
    if col["approval"] not in ctx.table("assets").columns:
        elig.partial("approval unavailable: approval eligibility unknown", ["assets:approval_status"])
    if not any(c in ctx.table("assets").columns for c in ("start_date", "end_date")):
        elig.partial("schedule unavailable: date eligibility unknown", ["assets:start_date", "assets:end_date"])
    reviews: dict[tuple, list] = {}
    parent_paused = 0
    for l in links:
        ok, why = eligible(l)
        if ok is not False:
            continue
        if l["level"] == "campaign" and l["campaign_id"] not in camps or \
                l["level"] == "ad_group" and l["ad_group_id"] not in groups:
            parent_paused += 1
            continue
        eid = "account" if l["level"] == "account" else l["campaign_id"] if l["level"] == "campaign" else l["ad_group_id"]
        reviews.setdefault((l["level"], eid, l["type"]), []).append({**l, "reasons": why})
    for (level, eid, typ), bad in sorted(reviews.items()):
        entity = {"level": level, "entity_id": eid, "asset_type": typ}
        if level == "campaign":
            entity["campaign_id"] = eid
        elif level == "ad_group":
            entity["ad_group_id"] = eid
            entity["campaign_id"] = str(groups[eid].get("campaign_id"))
        remaining = matrix.get(f"{level}:{eid}", {}).get(typ) if level != "account" else None
        elig.review("intended_association_ineligible", entity,
                    f"{len(bad)} {typ} link(s) at {level} {eid} are paused/disapproved/out of schedule. Were they "
                    f"intended coverage, and is business coverage affected?",
                    evidence={"links": [{k: v for k, v in b.items() if k != "text"} for b in bad],
                              "remaining_eligible_coverage": remaining, "snapshot": ref,
                              "campaign_objectives": ctx.profile.get("campaign_objectives"),
                              "business_type": ctx.profile.get("business_type"),
                              "evidence_refs": _intent_refs(ctx, typ, entity.get("campaign_id"))},
                    outcomes={"intended_coverage_affected": {"severity": "Warning", "recommendation":
                                                             "Owner review: restore/replace the intended association."},
                              "not_intended": {"severity": None, "recommendation": "No action; valid optional choice."},
                              "uncertain": {"severity": "Info", "recommendation":
                                            "Confirm intended coverage with the owner."}},
                    guidance="An approved asset is not proof of serving; a limited asset may still serve. "
                             "intended_coverage_affected needs proposal.evidence_ref from evidence.evidence_refs "
                             "(documented intent); none listed → uncertain.")
    elig.observe("Ineligible links", review_groups=len(reviews), outside_eligible_spine=parent_paused)

    # -- step 5: completeness per level
    comp = ctx.check("inventory_completeness", "Declared inventory completeness per level", a_needs)
    t = ctx.table("assets")
    state = "complete" if t.complete is True and not t.truncated else "partial" if t.complete is False or t.truncated \
        else "unknown"
    levels_seen = sorted({l["level"] for l in links})
    comp.observe("Assets inventory completeness", manifest_state=state, levels_with_links=levels_seen,
                 per_level={lv: state for lv in ("account", "campaign", "ad_group")},
                 manifest=(t.manifest or {}).get("completeness"), filters=(t.manifest or {}).get("filters"))
    complete = state == "complete"

    # -- step 6: optional types absent
    opt = ctx.check("optional_types", "Optional asset types absent at an eligible entity", a_needs)
    intended = [str(x).upper() for x in (ctx.profile.get("intended_asset_types") or [])]
    types = sorted(set(intended) or set(by_type))
    if not complete:
        opt.partial(f"assets inventory {state}: absence not provable")
    elif not types:
        opt.partial("no evaluated asset types (profile.intended_asset_types empty and no inventory types)",
                    ["profile:intended_asset_types"])
    else:
        for cid in sorted(camps):
            gids = [g for g, row in groups.items() if str(row.get("campaign_id")) == cid]
            for typ in types:
                n = sum(1 for l in links if l["type"] == typ and eligible(l)[0] is not False and (
                    l["level"] == "account" or l["campaign_id"] == cid or l["ad_group_id"] in gids))
                if n:
                    continue
                opt.finding("optional_asset_type_absent", "Info", {"campaign_id": cid, "asset_type": typ},
                            f"No eligible {typ} link at account, campaign {cid} or its ad groups",
                            evidence={"type_source": "profile.intended_asset_types" if intended else "account inventory",
                                      "ad_groups": sorted(gids), "inventory_state": state},
                            recommendation="Assess business usefulness with the owner before adding; optional feature.",
                            uncertainty="Absence is from a complete snapshot; no CTR uplift is implied.")
        opt.observe("Optional-type absence evaluated", types=types, campaigns=len(camps))

    # -- step 7: duplicate text / stale dates
    fld = ctx.check("field_review", "Duplicate text and stale configured dates", {"assets": a_needs["assets"] + ["text"]})
    if fld.runnable:
        buckets: dict[tuple, list] = {}
        for l in links:
            if eligible(l)[0] is False or not _norm(l["text"]):
                continue
            eid = l["campaign_id"] if l["level"] == "campaign" else l["ad_group_id"] if l["level"] == "ad_group" else "account"
            buckets.setdefault((l["level"], eid, l["type"], _norm(l["text"])), []).append(l["asset_id"])
        for (level, eid, typ, text), ids in sorted(buckets.items()):
            if len(set(ids)) < 2:
                continue
            fld.finding("duplicate_asset_text", "Info", {"level": level, "entity_id": eid, "asset_type": typ,
                                                          "text": text},
                        f"{len(set(ids))} {typ} assets at {level} {eid} share the same normalized text",
                        evidence={"asset_ids": sorted(set(ids))},
                        recommendation="Keep one or differentiate the text; route destinations to skill-031.",
                        uncertainty="Exact normalized match only; paraphrases not assessed.")
        stale = sorted({l["asset_id"] for l in links if ref and l["end"] and l["end"] < ref})
        fld.observe("Configured dates before snapshot (reviewed under eligibility_intersection)", assets=stale,
                    snapshot=ref)

    pri = ctx.check("prioritization", "Owner-review priority of confirmed gaps", a_needs)
    pri.observe("Owner review queue", eligibility_reviews=len(reviews),
                absence_findings=sum(1 for f in ctx.result.findings if f.condition_key == "optional_asset_type_absent"),
                destinations_owner="skill-031", policy_owner="skill-037", note="no CTR uplift forecast")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   intended_coverage_affected (Warning) requires proposal.evidence_ref equal to one of
             item.evidence.evidence_refs (profile.intended_asset_types:<TYPE> for the item's asset type or
             profile.campaign_objectives:<campaign_id> for its campaign); unknown or foreign refs are rejected.
             Other outcomes need no proposal.
    """
    if decision.get("outcome") != "intended_coverage_affected":
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return ["intended_coverage_affected needs proposal.evidence_ref to documented intent"]
    allowed = sorted((item.evidence or {}).get("evidence_refs") or [])
    if ref not in allowed:
        return [f"evidence_ref {ref} is not documented intent for this item; allowed {allowed}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
