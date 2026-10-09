"""check.py — skill-036 deterministic video coverage matrix, provenance ledger and format-requirement checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-036-video-asset-presence/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Spine = custom/creative_groups (all PMax asset groups and Demand Gen ads incl. zero videos); video rows never
         define the spine. Absence findings need creative_groups AND video_associations manifest-complete.
         Joins are exact (entity_type, entity_id): ad-level Demand Gen and asset-group-level PMax keys are kept;
         a customer video library item (assets) is never proof of attachment.
         Eligible video = association_status ENABLED and approval not DISAPPROVED on an eligible entity
         (entity_status and parent_status ENABLED).
         Provenance only from video_associations.provenance (+provenance_source): uploaded / generated / unknown;
         blank or other values are unknown — unknown is NEVER treated as auto-generated.
         Requirements only from external/video_format_requirements (latest effective_date <= snapshot per
         requirement_id); ad_format matches association field_type literally, or 'any'/'all'/blank for every field.
         No universal 10-60 s rule, no all-three-ratios rule. allowed_ratios like '16:9;1:1;9:16' with 2% relative
         tolerance. Duration/ratio evaluated only from external/video_review metadata; unknown stays unknown.
         Required video missing/non-compliant → provisional Info + ai_review (Warning); image-only Demand Gen can be
         intentional (no-finding outcome). Critical only via 'delivery_block_confirmed' with proposal.evidence_ref,
         offered only when the entity carries an eligibility diagnostic; the ref must equal the source_ref of a
         custom/creative_groups row for the same campaign/entity_type/entity_id with a non-eligible diagnostic and
         snapshot_at in [period_start, snapshot].
         Video performance: the recipe declares no performance file name → check skipped, never inferred.
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

SKILL = "skill-036-video-asset-presence"
VERSION = "1.0.0"

GROUPS = "custom/creative_groups"
ASSOC = "custom/video_associations"
REVIEW = "external/video_review"
REQS = "external/video_format_requirements"
G_COLS = ["campaign_id", "entity_type", "entity_id", "snapshot_at", "subtype", "parent_status", "entity_status",
          "eligibility", "source_ref"]
A_COLS = ["entity_type", "entity_id", "asset_id", "field_type", "snapshot_at", "linking_level", "youtube_video_id",
          "association_status", "approval", "provenance", "provenance_source"]
R_COLS = ["subtype", "ad_format", "requirement_id", "effective_date", "required_or_recommended", "duration_min",
          "duration_max", "allowed_ratios", "source_url", "checked_at"]
RV_COLS = ["asset_id", "review_at", "duration_seconds", "width_px", "height_px", "brand_message_review", "source_ref"]
RATIO_TOL = 0.02


def _up(v) -> str:
    return str(v or "").strip().upper()


def _key(r) -> tuple[str, str]:
    return (str(r.get("entity_type") or "").strip().lower(), str(r.get("entity_id")))


def _ratio(v) -> float | None:
    s = str(v or "").strip()
    if ":" in s:
        a, _, b = s.partition(":")
        return V.ratio(V.num(a), V.num(b))
    return V.num(s)


def provenance(v) -> str:
    s = V.norm_text(v)
    if s in ("uploaded", "custom", "advertiser_uploaded"):
        return "uploaded"
    if s in ("generated", "auto_generated", "auto-generated", "platform_generated"):
        return "generated"
    return "unknown"


def evaluate(meta: dict | None, req: dict) -> tuple[bool | None, list[str]]:
    if not meta:
        return None, ["no video metadata"]
    fails, unknown = [], []
    d = V.num(meta.get("duration_seconds"))
    lo, hi = V.num(req.get("duration_min")), V.num(req.get("duration_max"))
    if lo is not None or hi is not None:
        if d is None:
            unknown.append("duration unknown")
        elif (lo is not None and d < lo) or (hi is not None and d > hi):
            fails.append(f"duration {d:g}s outside [{lo}, {hi}]")
    allowed = [r for r in (_ratio(x) for x in V.split_list(req.get("allowed_ratios"), (" | ", ";", "|", ","))) if r]
    if allowed:
        w, h = V.num(meta.get("width_px")), V.num(meta.get("height_px"))
        if w is None or h is None or w <= 0 or h <= 0:
            unknown.append("dimensions unknown")
        elif not any(abs(w / h - r) <= RATIO_TOL * r for r in allowed):
            fails.append(f"ratio {w / h:.3f} not in {[round(r, 3) for r in allowed]}")
    if fails:
        return False, fails
    return (None, unknown) if unknown else (True, [])


def _applies(req: dict, field_type: str) -> bool:
    f = _up(req.get("ad_format"))
    return f in ("", "ANY", "ALL") or f == _up(field_type)


def run(ctx) -> None:
    """Run the video coverage spine, eligible inventory, provenance, format-requirement and required-video checks.

    Rules:   Absence findings need creative_groups AND video_associations manifest-complete; library assets never prove
             attachment. Unknown provenance is Info, never auto-generated. Format checks use only
             external/video_format_requirements and external/video_review metadata (unknown → partial). Required video
             missing → provisional Info + ai_review (Warning); Critical only via 'delivery_block_confirmed'. Video
             performance is always skipped (no declared file).
    """
    sp = ctx.check("entity_spine", "Complete eligible entity spine left-joined to video links", {GROUPS: G_COLS})
    titles = (("eligible_inventory", "Eligible videos after parent/association/approval checks"),
              ("type_field_distinct", "Asset type vs association field type"),
              ("provenance", "Uploaded / generated / unknown provenance"),
              ("format_compliance", "Duration and aspect ratio vs subtype/format requirements"),
              ("media_review", "Branding, captions and cropping from supplied media"),
              ("required_video", "Required vs optional video formats per entity"),
              ("video_performance", "Defined-view, mature matched-cohort video performance"))
    if not sp.runnable:
        for cid, t in titles:
            if cid == "media_review":
                _media_review(ctx, t)
            else:
                ctx.check(cid, t).skip("complete creative entity spine unavailable", sp.missing)
        return
    snap = ctx.snapshot or ctx.as_of
    ents: dict[tuple[str, str], dict] = {}
    for r in sorted(ctx.rows(GROUPS), key=_key):
        ents[_key(r)] = {"row": r, "subtype": _up(r.get("subtype")), "campaign_id": str(r.get("campaign_id")),
                         "eligible": _up(r.get("entity_status")) == "ENABLED" and _up(r.get("parent_status")) == "ENABLED",
                         "eligibility": str(r.get("eligibility") or "").strip()}
    spine_complete = ctx.table(GROUPS).complete is True
    if not spine_complete:
        sp.partial("creative_groups not manifest-complete: absence conclusions disabled")

    inv = ctx.check("eligible_inventory", titles[0][1], {ASSOC: A_COLS})
    links: dict[tuple[str, str], list[dict]] = {}
    assoc_complete = False
    if inv.runnable:
        assoc_complete = ctx.table(ASSOC).complete is True
        raw: dict[tuple[str, str], list[dict]] = {}
        for a in ctx.rows(ASSOC):
            raw.setdefault(_key(a), []).append(a)
        for k in sorted(ents):
            links[k] = sorted(raw.get(k, []), key=lambda x: (str(x.get("field_type")), str(x.get("asset_id"))))
        orphans = sorted(set(raw) - set(ents))
        if orphans:
            inv.partial(f"{len(orphans)} video association keys not in creative_groups: {orphans[:10]}")
        if not assoc_complete:
            inv.partial("video_associations not manifest-complete: absence conclusions disabled")
        lib = {str(r.get("id") or r.get("asset_id")) for r in ctx.rows("assets") if "VIDEO" in _up(r.get("type"))}
        attached = {str(x.get("asset_id")) for xs in raw.values() for x in xs}
        for k, xs in sorted(links.items()):
            e = ents[k]
            ok = [x for x in xs if _up(x.get("association_status")) == "ENABLED" and _up(x.get("approval")) != "DISAPPROVED"]
            inv.observe(f"{k[0]} {k[1]} ({e['subtype']}): {len(ok)} eligible of {len(xs)} video link(s)",
                        entity_type=k[0], entity_id=k[1], campaign_id=e["campaign_id"], eligible_entity=e["eligible"],
                        links=len(xs), eligible_videos=len({x.get("asset_id") for x in ok}),
                        youtube_ids=sorted({str(x.get("youtube_video_id")) for x in ok if x.get("youtube_video_id")}))
            e["videos"] = ok if e["eligible"] else []
        if lib:
            inv.observe("Library videos without any association (not proof of attachment)", unattached=sorted(lib - attached))
    complete = spine_complete and assoc_complete

    tf = ctx.check("type_field_distinct", titles[1][1], {ASSOC: ["asset_id", "field_type"]})
    if tf.runnable:
        types = {str(r.get("id") or r.get("asset_id")): _up(r.get("type")) for r in ctx.rows("assets")}
        pairs: dict[str, int] = {}
        blank = 0
        for xs in links.values():
            for x in xs:
                if not x.get("field_type"):
                    blank += 1
                k = f"{types.get(str(x.get('asset_id')), 'UNKNOWN_ASSET_TYPE')}|{_up(x.get('field_type')) or 'UNKNOWN'}"
                pairs[k] = pairs.get(k, 0) + 1
        if blank:
            tf.partial(f"{blank} association(s) without field_type: format matching undecidable")
        tf.observe("Asset type | association field type pairs as exported", pairs=pairs)

    pv = ctx.check("provenance", titles[2][1], {ASSOC: ["provenance", "provenance_source"]})
    if pv.runnable and inv.runnable:
        for k, e in sorted(ents.items()):
            vids = e.get("videos") or []
            if not e["eligible"] or not vids:
                continue
            kinds = {x.get("asset_id"): provenance(x.get("provenance")) for x in vids}
            counts = {p: sum(1 for v in kinds.values() if v == p) for p in ("uploaded", "generated", "unknown")}
            pv.observe(f"{k[0]} {k[1]}: provenance ledger", entity_id=k[1], **counts,
                       sources=sorted({str(x.get("provenance_source")) for x in vids if x.get("provenance_source")}))
            ent = {"campaign_id": e["campaign_id"], "entity_type": k[0], "entity_id": k[1]}
            if counts["uploaded"] == 0 and counts["unknown"] == 0:
                pv.finding("no_custom_video", "Info", ent,
                           f"{k[0]} {k[1]}: all {counts['generated']} eligible video(s) are platform-generated per supplied "
                           f"provenance", evidence={"provenance": kinds},
                           recommendation="Optional: test a custom video against campaign intent and production limits.",
                           uncertainty="Generated video is not inherently low quality; no uplift promised.")
            elif counts["uploaded"] == 0:
                pv.finding("provenance_unknown", "Info", ent,
                           f"{k[0]} {k[1]}: {counts['unknown']} video(s) with unknown provenance", evidence={"provenance": kinds},
                           recommendation="Supply provenance evidence before any creative-control conclusion.",
                           uncertainty="Unknown source is not auto-generated.")
    elif pv.runnable:
        pv.skip("video associations unavailable", inv.missing)

    meta: dict[str, dict] = {}
    for r in sorted(ctx.rows(REVIEW), key=lambda r: str(r.get("review_at"))):
        meta[str(r.get("asset_id"))] = r  # latest review per asset
    rq = ctx.table(REQS)
    reqs: dict[str, list[dict]] = {}
    if rq is not None and not rq.missing(R_COLS):
        latest: dict[tuple[str, str], dict] = {}
        for r in sorted(ctx.rows(REQS), key=lambda r: str(r.get("effective_date"))):
            d = V.parse_date(r.get("effective_date"))
            if d is not None and (snap is None or d <= snap):
                latest[(_up(r.get("subtype")), str(r.get("requirement_id")))] = r
        for (sub, _), r in sorted(latest.items()):
            reqs.setdefault(sub, []).append(r)

    fc = ctx.check("format_compliance", titles[3][1], {REQS: R_COLS, REVIEW: ["asset_id", "duration_seconds",
                                                                               "width_px", "height_px"]})
    if fc.runnable and inv.runnable:
        undecided = 0
        for k, e in sorted(ents.items()):
            for x in e.get("videos") or []:
                for r in reqs.get(e["subtype"], []):
                    if not _applies(r, x.get("field_type")):
                        continue
                    ok, why = evaluate(meta.get(str(x.get("asset_id"))), r)
                    if ok is None:
                        undecided += 1
                        continue
                    if ok:
                        continue
                    fe = {"campaign_id": e["campaign_id"], "entity_type": k[0], "entity_id": k[1],
                          "asset_id": x.get("asset_id"), "requirement_id": r.get("requirement_id")}
                    ev = {"failures": why, "requirement": dict(r), "metadata_ref": (meta.get(str(x.get("asset_id"))) or {}).get("source_ref")}
                    fc.finding("format_requirement_not_met", "Info", fe,
                               f"Video {x.get('asset_id')} on {k[0]} {k[1]} misses {r.get('required_or_recommended')} "
                               f"requirement {r.get('requirement_id')}: {'; '.join(why)}", evidence=ev,
                               recommendation="Use a compliant cut for this format; see required_video for coverage.",
                               uncertainty="Metadata from supplied review; platform may crop or letterbox.")
        if undecided:
            fc.partial(f"{undecided} video/requirement pairs undecidable (no duration/dimension metadata)")
    elif fc.runnable:
        fc.skip("video associations unavailable", inv.missing)

    _media_review(ctx, titles[4][1])

    rv = ctx.check("required_video", titles[5][1], {REQS: R_COLS})
    if rv.runnable and inv.runnable:
        if not complete:
            rv.partial("inventory not manifest-complete: missing-video conclusions disabled")
        for k, e in sorted(ents.items()):
            diagnosed = bool(e["eligibility"]) and _up(e["eligibility"]) not in ("ELIGIBLE", "ENABLED")
            if not (e["eligible"] or diagnosed) or not complete:
                continue
            for r in reqs.get(e["subtype"], []):
                have = [x for x in e.get("videos") or [] if _applies(r, x.get("field_type"))
                        and evaluate(meta.get(str(x.get("asset_id"))), r)[0] is not False]
                if have:
                    continue
                fe = {"campaign_id": e["campaign_id"], "entity_type": k[0], "entity_id": k[1],
                      "requirement_id": r.get("requirement_id")}
                ev = {"subtype": e["subtype"], "ad_format": r.get("ad_format"), "eligibility": e["eligibility"] or None,
                      "entity_eligible": e["eligible"], "source_ref": e["row"].get("source_ref"),
                      "linked_videos": len(links.get(k, [])), "requirement_source": r.get("source_url")}
                if V.norm_text(r.get("required_or_recommended")) != "required":
                    rv.finding("optional_format_absent", "Info", fe,
                               f"{k[0]} {k[1]} has no compliant video for optional format {r.get('ad_format') or 'any'}",
                               evidence=ev, recommendation="Optional; weigh against intent and production constraints.",
                               uncertainty="No performance claim.")
                    continue
                prov = rv.finding("required_video_missing", "Info", fe,
                                  f"{k[0]} {k[1]} lacks an eligible compliant video for required format "
                                  f"{r.get('ad_format') or 'any'} ({r.get('requirement_id')})", evidence=ev,
                                  recommendation="Confirm the intended format before requesting production.",
                                  uncertainty="Image-only setups can be intentional; requirement scope from supplied excerpt.")
                outcomes = {"intended_format_blocked": {"severity": "Warning", "recommendation":
                                                        "Add/attach a compliant video for the intended format."},
                            "intentional_without_video": {"severity": None, "recommendation":
                                                          "Legitimate image-only/alternative setup; no action."},
                            "uncertain": {"severity": "Info", "recommendation": "Ask the owner which formats are intended."}}
                if diagnosed:
                    outcomes["delivery_block_confirmed"] = {"severity": "Critical", "recommendation":
                                                            "Fix the video requirement first; cite the diagnostic."}
                rv.review("required_video_missing", fe, f"Is {r.get('ad_format') or 'video'} an intended, verified format "
                          f"for {k[0]} {k[1]} that the missing video now blocks?", evidence=ev, provisional=prov,
                          outcomes=outcomes, guidance="delivery_block_confirmed needs proposal.evidence_ref to a platform "
                                                      "diagnostic attributing the block to video.")
    elif rv.runnable:
        rv.skip("video associations unavailable", inv.missing)

    perf = ctx.check("video_performance", titles[6][1])
    perf.skip("recipe declares no association/date video performance file; supply one declaring impressions, "
              "views, conversions and attribution", ["video performance (association/date: impressions, views, "
                                                     "conversions, attribution)"])


def _media_review(ctx, title: str) -> None:
    """Step 6: supplied media review only; lack of metadata never establishes poor quality."""
    mr = ctx.check("media_review", title, {REVIEW: ["asset_id", "review_at", "brand_message_review", "source_ref"]})
    if not mr.runnable:
        return
    t = ctx.table(REVIEW)
    cap_col = next((c for c in ("captions", "audio_captions") if c in t.columns), None)
    if cap_col is None:
        mr.partial("captions not exported", [f"{REVIEW}:captions"])
    for r in sorted(ctx.rows(REVIEW), key=lambda r: (str(r.get("asset_id")), str(r.get("review_at")))):
        note = r.get("brand_message_review")
        if not note or V.norm_text(note) in ("ok", "none", "pass", "approved"):
            continue
        mr.review("media_quality", {"asset_id": r.get("asset_id"), "review_at": r.get("review_at")},
                  f"Does the supplied review of video {r.get('asset_id')} corroborate a branding/comprehension/caption issue?",
                  evidence={"brand_message_review": note, "captions": r.get(cap_col) if cap_col else None,
                            "language": r.get("language"), "ref": r.get("local_video_or_authorized_review_ref"),
                            "source_ref": r.get("source_ref")},
                  outcomes={"creative_issue": {"severity": "Info", "recommendation":
                                               "Propose a controlled creative test or re-cut; no uplift promise."},
                            "no_issue": {"severity": None, "recommendation": "No action."}},
                  guidance="Judge only from the supplied media review.")


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
