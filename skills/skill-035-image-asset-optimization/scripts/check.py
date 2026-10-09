"""check.py — skill-035 deterministic image coverage matrix and verified format-specification checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-035-image-asset-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Spine = custom/creative_groups (complete UI inventory incl. zero-asset PMax groups/Demand Gen ads); image
         rows never define the spine. Absence findings need BOTH creative_groups and image_associations
         manifest-complete; otherwise partial and no absence finding.
         Joins are exact (entity_type, entity_id). Only SEARCH-subtype ad groups inherit campaign/customer-level
         links; PMax asset-group and Demand Gen ad links are never replaced by campaign links.
         Eligible entity = entity_status and parent_status ENABLED. Eligible image = association status ENABLED and
         approval not DISAPPROVED. Associations and unique images are counted separately.
         Requirements come only from external/image_format_requirements (latest effective_date <= snapshot per
         requirement_id); recommended != required; no three-per-ratio minimum, no blanket portrait rule.
         Dimensions/ratio evaluated only when width and height are both positive; unknown stays unknown.
         Ratio tolerance is RELATIVE: |w/h - target| <= tolerance × target (target "1.91:1", "4:5" or decimal).
         Required-spec failure / missing required role → provisional Info + ai_review (business coverage → Warning);
         Critical only via 'delivery_block_confirmed' with proposal.evidence_ref, offered only when the entity's
         eligibility diagnostic is present; the ref must equal the source_ref of a custom/creative_groups row for the
         same campaign/entity_type/entity_id with a non-eligible diagnostic and snapshot_at in [period_start,
         snapshot]. Visual/text quality judged only from external/image_review rows.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evidref | evidence_ref resolves to the entity's dated diagnostic row
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

SKILL = "skill-035-image-asset-optimization"
VERSION = "1.0.0"

GROUPS = "custom/creative_groups"
ASSOC = "custom/image_associations"
REVIEW = "external/image_review"
REQS = "external/image_format_requirements"
G_COLS = ["campaign_id", "entity_type", "entity_id", "snapshot_at", "subtype", "parent_status", "entity_status",
          "eligibility", "source_ref"]
A_COLS = ["entity_type", "entity_id", "asset_id", "field_type", "snapshot_at", "linking_level", "status", "approval"]
SPEC_COLS = ["width_px", "height_px", "mime_type", "file_size_bytes"]
R_COLS = ["subtype", "field_type", "requirement_id", "effective_date", "required_or_recommended", "min_width",
          "min_height", "ratio", "tolerance", "max_file_bytes", "mime_types", "source_url", "checked_at"]
V_COLS = ["asset_id", "review_at", "local_image_ref", "visual_or_OCR_evidence", "crop_subject_issue", "text_review",
          "reviewer_role", "rationale"]


def _up(v) -> str:
    return str(v or "").strip().upper()


def ratio_value(v) -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    if ":" in s:
        a, _, b = s.partition(":")
        return V.ratio(V.num(a), V.num(b))
    return V.num(s)


def _key(r) -> tuple[str, str]:
    return (str(r.get("entity_type") or "").strip().lower(), str(r.get("entity_id")))


def _eligible_img(a) -> bool:
    return _up(a.get("status")) == "ENABLED" and _up(a.get("approval")) != "DISAPPROVED"


def evaluate(assoc: dict, req: dict) -> tuple[bool | None, list[str]]:
    """(meets, reasons). None = undecidable from supplied metadata."""
    w, h = V.num(assoc.get("width_px")), V.num(assoc.get("height_px"))
    fails, unknown = [], []
    if w is None or h is None or w <= 0 or h <= 0:
        unknown.append("dimensions unknown")
    else:
        mw, mh = V.num(req.get("min_width")), V.num(req.get("min_height"))
        if mw is not None and w < mw:
            fails.append(f"width {w:g} < {mw:g}")
        if mh is not None and h < mh:
            fails.append(f"height {h:g} < {mh:g}")
        target, tol = ratio_value(req.get("ratio")), V.num(req.get("tolerance")) or 0.0
        if target is not None and abs(w / h - target) > tol * target:
            fails.append(f"ratio {w / h:.3f} outside {target:.3f} ± {tol:g}")
    mimes = [m.lower() for m in V.split_list(req.get("mime_types"), (" | ", ";", "|", ","))]
    mt = str(assoc.get("mime_type") or "").lower()
    if mimes:
        if not mt:
            unknown.append("mime unknown")
        elif mt not in mimes:
            fails.append(f"mime {mt} not in {mimes}")
    mx, size = V.num(req.get("max_file_bytes")), V.num(assoc.get("file_size_bytes"))
    if mx is not None:
        if size is None:
            unknown.append("file size unknown")
        elif size > mx:
            fails.append(f"size {size:g} > {mx:g}")
    if fails:
        return False, fails
    return (None, unknown) if unknown else (True, [])


def run(ctx) -> None:
    """Run image inventory, format-requirement and role-coverage checks per creative group.

    Rules:   Absence findings need manifest-complete creative_groups AND image_associations; otherwise partial only.
             Requirements only from external/image_format_requirements; recommended-spec gaps and optional ratios are
             Info. Required-spec/role gaps → provisional Info + ai_review (coverage → Warning); Critical only via
             'delivery_block_confirmed' with proposal.evidence_ref when an eligibility diagnostic exists. Unknown dims
             stay unknown.
    """
    sp = ctx.check("entity_spine", "Eligible creative entities incl. zero-association groups", {GROUPS: G_COLS})
    titles = (("association_join", "Image links joined to entities; associations vs unique images"),
              ("requirement_match", "Requirements by subtype, field type and effective date"),
              ("spec_compliance", "Dimensions, ratio, MIME and file size vs requirements"),
              ("visual_review", "Crop, legibility and text concerns from supplied image evidence"),
              ("required_roles", "Required eligible image roles per entity"),
              ("optional_opportunities", "Optional ratio/variety opportunities"),
              ("replacement_routing", "Corroborated defects and policy blockers routed to 037"))
    if not sp.runnable:
        for cid, t in titles:
            if cid == "visual_review":
                _visual_review(ctx, t, None)
            else:
                ctx.check(cid, t).skip("complete creative entity spine unavailable", sp.missing)
        return
    snap = ctx.snapshot or ctx.as_of
    ents: dict[tuple[str, str], dict] = {}
    for r in sorted(ctx.rows(GROUPS), key=_key):
        ents[_key(r)] = {"row": r, "subtype": _up(r.get("subtype")), "campaign_id": str(r.get("campaign_id")),
                         "eligible": _up(r.get("entity_status")) == "ENABLED" and _up(r.get("parent_status")) == "ENABLED",
                         "eligibility": r.get("eligibility")}
    spine_complete = ctx.table(GROUPS).complete is True
    if not spine_complete:
        sp.partial("creative_groups not manifest-complete: absence conclusions disabled")
    by_sub: dict[str, int] = {}
    for e in ents.values():
        by_sub[e["subtype"]] = by_sub.get(e["subtype"], 0) + 1
    sp.observe("Creative entity spine", entities=len(ents), eligible=sum(1 for e in ents.values() if e["eligible"]),
               by_subtype=by_sub)

    aj = ctx.check("association_join", titles[0][1], {ASSOC: A_COLS})
    links: dict[tuple[str, str], list[dict]] = {}
    assoc_complete = False
    if aj.runnable:
        assoc_complete = ctx.table(ASSOC).complete is True
        raw: dict[tuple[str, str], list[dict]] = {}
        for a in ctx.rows(ASSOC):
            raw.setdefault(_key(a), []).append(a)
        for k, e in sorted(ents.items()):
            own = [dict(x, inherited=False) for x in raw.get(k, [])]
            if e["subtype"] == "SEARCH" and k[0] == "ad_group":
                own += [dict(x, inherited=True) for x in raw.get(("campaign", e["campaign_id"]), [])]
                own += [dict(x, inherited=True) for kk, xs in raw.items() if kk[0] in ("customer", "account") for x in xs]
            links[k] = sorted(own, key=lambda x: (str(x.get("field_type")), str(x.get("asset_id"))))
        orphans = sorted(set(raw) - set(ents) - {k for k in raw if k[0] in ("campaign", "customer", "account")})
        if orphans:
            aj.partial(f"{len(orphans)} association keys not in creative_groups: {orphans[:10]}")
        for k, xs in sorted(links.items()):
            aj.observe(f"{k[0]} {k[1]}: {len(xs)} image association(s)", entity_type=k[0], entity_id=k[1],
                       associations=len(xs), unique_images=len({x.get('asset_id') for x in xs}),
                       eligible_images=len({x.get("asset_id") for x in xs if _eligible_img(x)}),
                       inherited=sum(1 for x in xs if x["inherited"]), eligible_entity=ents[k]["eligible"])
        lib = {str(r.get("id") or r.get("asset_id")) for r in ctx.rows("assets") if _up(r.get("type")) == "IMAGE"}
        linked = {str(x.get("asset_id")) for xs in raw.values() for x in xs}
        if lib:
            aj.observe("Image library items without any association (not proof of attachment)",
                       unattached=sorted(lib - linked))
        if not assoc_complete:
            aj.partial("image_associations not manifest-complete: absence conclusions disabled")
    complete = spine_complete and assoc_complete

    rm = ctx.check("requirement_match", titles[1][1], {REQS: R_COLS})
    reqs: dict[tuple[str, str], list[dict]] = {}
    if rm.runnable:
        latest: dict[tuple[str, str, str], dict] = {}
        for r in sorted(ctx.rows(REQS), key=lambda r: str(r.get("effective_date"))):
            d = V.parse_date(r.get("effective_date"))
            if d is None or (snap and d > snap):
                continue
            latest[(_up(r.get("subtype")), str(r.get("field_type") or "").upper(), str(r.get("requirement_id")))] = r
        for (sub, ft, _), r in sorted(latest.items()):
            reqs.setdefault((sub, ft), []).append(r)
        missing = sorted({e["subtype"] for e in ents.values() if e["eligible"]} - {s for s, _ in reqs})
        if missing:
            rm.partial(f"no current requirement rows for subtypes {missing}: their compliance is unchecked")
        rm.observe("Current requirements matched", pairs=sorted(f"{s}/{f}" for s, f in reqs), as_of=snap)

    def ent_id(k):
        return {"campaign_id": ents[k]["campaign_id"], "entity_type": k[0], "entity_id": k[1]}

    sc = ctx.check("spec_compliance", titles[2][1], {ASSOC: SPEC_COLS, REQS: R_COLS})
    if sc.runnable and aj.runnable and rm.runnable:
        undecided = 0
        for k, xs in sorted(links.items()):
            e = ents[k]
            if not e["eligible"]:
                continue
            for x in xs:
                if not _eligible_img(x):
                    continue
                for r in reqs.get((e["subtype"], str(x.get("field_type") or "").upper()), []):
                    ok, why = evaluate(x, r)
                    if ok is None:
                        undecided += 1
                        continue
                    if ok:
                        continue
                    level = V.norm_text(r.get("required_or_recommended"))
                    fe = {**ent_id(k), "asset_id": x.get("asset_id"), "field_type": x.get("field_type"),
                          "requirement_id": r.get("requirement_id")}
                    ev = {"width_px": x.get("width_px"), "height_px": x.get("height_px"), "mime_type": x.get("mime_type"),
                          "file_size_bytes": x.get("file_size_bytes"), "failures": why, "requirement": dict(r),
                          "level": level}
                    if level == "required":
                        prov = sc.finding("required_spec_not_met", "Info", fe,
                                          f"Image {x.get('asset_id')} on {k[0]} {k[1]} fails required spec "
                                          f"{r.get('requirement_id')}: {'; '.join(why)}", evidence=ev,
                                          recommendation="Reuse a compliant existing image or replace this one.",
                                          uncertainty="Metadata from the export; platform may resize or reject.")
                        sc.review("required_spec_not_met", fe, f"Does the failing image leave {k[0]} {k[1]} without "
                                  f"business coverage for {x.get('field_type')}?", evidence=ev, provisional=prov,
                                  outcomes={"coverage_affected": {"severity": "Warning", "recommendation":
                                                                  "Replace/reuse a compliant image for this role."},
                                            "covered_otherwise": {"severity": "Info", "recommendation":
                                                                  "Other compliant images cover the role; low priority."},
                                            "uncertain": {"severity": "Info", "recommendation": "Confirm with diagnostics."}})
                    else:
                        sc.finding("recommended_spec_not_met", "Info", fe,
                                   f"Image {x.get('asset_id')} misses recommended spec {r.get('requirement_id')}: "
                                   f"{'; '.join(why)}", evidence=ev,
                                   recommendation="Optional improvement; recommended sizes are not minimums.",
                                   uncertainty="No performance impact claimed.")
        if undecided:
            sc.partial(f"{undecided} image/requirement pairs undecidable (unknown dimensions/MIME/size)")
    elif sc.runnable:
        sc.skip("associations or requirements unavailable", aj.missing + rm.missing)

    _visual_review(ctx, titles[3][1], {str(x.get("asset_id")) for xs in links.values() for x in xs})

    rr = ctx.check("required_roles", titles[4][1], {GROUPS: ["eligibility"], REQS: ["required_or_recommended"]})
    op = ctx.check("optional_opportunities", titles[5][1], {REQS: ["required_or_recommended"]})
    if not (aj.runnable and rm.runnable):
        rr.skip("associations or requirements unavailable", aj.missing + rm.missing)
        op.skip("associations or requirements unavailable", aj.missing + rm.missing)
    else:
        if not complete:
            rr.partial("inventory not manifest-complete: missing-role conclusions disabled")
            op.partial("inventory not manifest-complete: absence conclusions disabled")
        for k, e in sorted(ents.items()):
            diag = str(e["eligibility"] or "").strip()
            diagnosed = bool(diag) and _up(diag) not in ("ELIGIBLE", "ENABLED")
            if not (e["eligible"] or diagnosed):
                continue
            for (sub, ft), rs in sorted(reqs.items()):
                if sub != e["subtype"]:
                    continue
                have = [x for x in links.get(k, []) if str(x.get("field_type") or "").upper() == ft and _eligible_img(x)
                        and all(evaluate(x, r)[0] is not False for r in rs)]
                if have or not complete:
                    continue
                level = "required" if any(V.norm_text(r.get("required_or_recommended")) == "required" for r in rs) \
                    else "recommended"
                fe = {**ent_id(k), "field_type": ft}
                ev = {"subtype": sub, "requirements": [r.get("requirement_id") for r in rs],
                      "eligibility": diag or None, "entity_eligible": e["eligible"],
                      "source_ref": e["row"].get("source_ref"), "associations_for_field": len(
                          [x for x in links.get(k, []) if str(x.get("field_type") or "").upper() == ft])}
                if level == "recommended":
                    op.finding("optional_ratio_absent", "Info", fe,
                               f"{k[0]} {k[1]} has no eligible {ft} image (recommended by {ev['requirements']})",
                               evidence=ev, recommendation="Optional variety; weigh against business context.",
                               uncertainty="No CTR uplift promised.")
                    continue
                prov = rr.finding("required_role_missing", "Info", fe,
                                  f"{k[0]} {k[1]} has no compliant eligible {ft} image although {ev['requirements']} "
                                  f"require one", evidence=ev,
                                  recommendation="Check feed-backed/automatic alternatives before requesting uploads.",
                                  uncertainty="Automatic or feed images may satisfy the role.")
                outcomes = {"coverage_affected": {"severity": "Warning", "recommendation":
                                                  "Add or reuse a compliant image for this role."},
                            "automatic_alternative": {"severity": None, "recommendation":
                                                      "Documented feed/automatic images cover the role."},
                            "uncertain": {"severity": "Info", "recommendation": "Request platform diagnostics."}}
                if diagnosed:
                    outcomes["delivery_block_confirmed"] = {"severity": "Critical", "recommendation":
                                                            "Fix the image role first; cite the diagnostic."}
                rr.review("required_role_missing", fe, f"Is business coverage of {k[0]} {k[1]} affected by the missing "
                          f"{ft} image role?", evidence=ev, provisional=prov, outcomes=outcomes,
                          guidance="delivery_block_confirmed needs proposal.evidence_ref to a platform diagnostic "
                                   "attributing the block to images.")

    rt = ctx.check("replacement_routing", titles[6][1], {ASSOC: ["approval"]})
    if rt.runnable:
        dis = sorted({(k[0], k[1], str(x.get("asset_id"))) for k, xs in links.items() for x in xs
                      if _up(x.get("approval")) == "DISAPPROVED"})
        rt.observe("Disapproved image associations routed to skill-037 (policy blockers)",
                   items=[{"entity_type": a, "entity_id": b, "asset_id": c} for a, b, c in dis])


def _visual_review(ctx, title: str, linked: set[str] | None) -> None:
    """Step 5: needs only external/image_review; linked=None when the association spine is unavailable."""
    vr = ctx.check("visual_review", title, {REVIEW: V_COLS})
    if vr.runnable:
        reviewed = set()
        for r in sorted(ctx.rows(REVIEW), key=lambda r: (str(r.get("asset_id")), str(r.get("review_at")))):
            reviewed.add(str(r.get("asset_id")))
            issues = {c: r.get(c) for c in ("crop_subject_issue", "text_review")
                      if r.get(c) and V.norm_text(r.get(c)) not in ("none", "no", "ok", "false")}
            if not issues:
                continue
            vr.review("visual_defect", {"asset_id": r.get("asset_id"), "review_at": r.get("review_at")},
                      f"Is the reported crop/text concern on image {r.get('asset_id')} a corroborated defect?",
                      evidence={**issues, "visual_or_OCR_evidence": r.get("visual_or_OCR_evidence"),
                                "local_image_ref": r.get("local_image_ref"), "reviewer_role": r.get("reviewer_role"),
                                "rationale": r.get("rationale")},
                      outcomes={"replacement_recommended": {"severity": "Info", "recommendation":
                                                            "Request a replacement or reuse a better existing image."},
                                "no_defect": {"severity": None, "recommendation": "No action."}},
                      guidance="Dimensions alone never establish excessive text or policy violation.")
        if linked is not None and linked - reviewed:
            vr.partial(f"{len(linked - reviewed)} linked image(s) without visual evidence: no quality judgment")


def _diagnostic_refs(ctx, entity: dict) -> set[str]:
    """source_refs of creative_groups rows for this exact entity with a non-eligible diagnostic in the window."""
    key = (str(entity.get("entity_type") or "").strip().lower(), str(entity.get("entity_id")))
    snap = ctx.snapshot or ctx.as_of
    refs = set()
    for r in ctx.rows(GROUPS):
        diag = str(r.get("eligibility") or "").strip()
        if _key(r) != key or str(r.get("campaign_id")) != str(entity.get("campaign_id")) or not diag \
                or _up(diag) in ("ELIGIBLE", "ENABLED"):
            continue
        d = V.parse_date(r.get("snapshot_at"))
        if d is None or (snap is not None and d > snap) or (ctx.period_start is not None and d < ctx.period_start):
            continue
        if str(r.get("source_ref") or "").strip():
            refs.add(str(r.get("source_ref")).strip())
    return refs


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   delivery_block_confirmed (Critical) requires proposal.evidence_ref equal to the source_ref of a
             custom/creative_groups row for the item's campaign_id/entity_type/entity_id whose eligibility is a
             non-eligible diagnostic and whose snapshot_at lies in [period_start, snapshot|as_of]; other outcomes
             need no proposal.
    """
    if decision.get("outcome") != "delivery_block_confirmed":
        return []
    ref = str((decision.get("proposal") or {}).get("evidence_ref") or "").strip()
    if not ref:
        return ["delivery_block_confirmed needs proposal.evidence_ref to the platform diagnostic"]
    if ref not in _diagnostic_refs(ctx, item.entity):
        return [f"evidence_ref {ref} is not a dated platform-diagnostic source_ref for "
                f"{item.entity.get('entity_type')} {item.entity.get('entity_id')} in {GROUPS}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
