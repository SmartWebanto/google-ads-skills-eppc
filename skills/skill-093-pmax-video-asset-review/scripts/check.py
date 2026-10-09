"""check.py — skill-093 deterministic PMax video association, media spec and requirement review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-093-pmax-video-asset-review/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-089-pmax-asset-group-structure/SKILL.md — same pmax_groups/pmax_group_assets intake
rules:   PMax scope = campaigns.channel_type PERFORMANCE_MAX (key campaigns.id, alternative campaigns.campaign_id);
         groups come ONLY from custom/pmax_groups joined on (campaign_id, asset_group_id); groups whose campaign
         is a known non-PMax campaign are dropped. assets.csv is account inventory and never proves group linkage.
         Video association = pmax_group_assets.asset_type or field_type containing VIDEO (case-insensitive).
         Association state order: REMOVED → removed; approval DISAPPROVED → disapproved; PAUSED → paused;
         ENABLED/ACTIVE + approval APPROVED/APPROVED_LIMITED/ELIGIBLE → eligible; anything else → unknown.
         Zero-video/zero-eligible claims require BOTH pmax_groups and pmax_group_assets manifest-complete.
         Aspect ratio/orientation only from nonzero width_px/height_px; 1% relative tolerance absorbs pixel
         rounding (854x480 = 16:9); square when |w/h - 1| <= 1%. Never infer dims/provenance from names.
         Provenance verified only when creation_provenance is advertiser|automated AND provenance_reference is
         present; else Info unknown_provenance. Provenance never changes any other outcome.
         rights_brand_approval denied/rejected/expired/revoked/not_approved on an ENABLED/ACTIVE association →
         Warning rights_mismatch; empty → observation only.
         Requirement rows: campaign_subtype empty/any/all = every PMax campaign, else literal case-insensitive
         match to campaigns.channel_subtype (alternatives channel_sub_type, advertising_channel_sub_type,
         campaign_subtype); intended_format empty/any/all = every orientation, landscape|horizontal,
         portrait|vertical, square; other formats are not applied (partial). Only supported=true rows apply
         limits; a required violation → Warning requirement_failure, recommended → Info recommended_spec_gap.
         Limit cells empty = no limit; non-numeric limit cells are malformed (partial), never "no limit".
         Missing portrait video or fewer than N videos is NEVER a finding.
         Disapproved video in an ENABLED group of a non-paused campaign → provisional Info + review; Critical only
         via blocks_required_serving with proposal.evidence_ref (verify).
         Completion rate only with rate_denominator_definition: sum(completed_views)/sum(video_views) or a single-row
         reported_completion_rate (row rates are never averaged). Like-format comparisons need ctx.mature True
         and min_impressions on both sides and produce observations only (no universal cutoff).
         Campaign conversions are never allocated to videos. performance_label LOW → Info low_performance_label.
         Coverage-need proposals (step 6) are a batch review; verify requires proposal.planning_reference and
         proposal.asset_group_ids drawn from the batch. Non-PMax video → 036, creative critique → 162,
         channel outcomes → 128.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
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

SKILL = "skill-093-pmax-video-asset-review"
VERSION = "1.0.0"

GROUPS = "custom/pmax_groups"
ASSOCS = "custom/pmax_group_assets"
DETAILS = "external/pmax_video_details"
REQS = "external/pmax_video_requirements"
METRICS = "custom/pmax_video_metrics"

ASSOC_COLS = ["campaign_id", "asset_group_id", "asset_id", "field_type", "association_status",
              "asset_type", "approval_status"]
GROUP_COLS = ["campaign_id", "asset_group_id", "status"]
REQ_COLS = ["campaign_subtype", "intended_format", "rule_id", "supported", "required_or_recommended",
            "min_width_px", "min_height_px", "aspect_ratio", "min_duration_seconds", "max_duration_seconds"]
SUBTYPE_COLS = ("channel_subtype", "channel_sub_type", "advertising_channel_sub_type", "campaign_subtype")

_ACTIVE = {"ENABLED", "ACTIVE"}
_APPROVED = {"APPROVED", "APPROVED_LIMITED", "ELIGIBLE"}
_RIGHTS_DENIED = {"denied", "rejected", "expired", "revoked", "not_approved", "not approved"}
_RIGHTS_OK = {"approved", "granted", "cleared"}
_ANY = {"", "any", "all"}
_FORMATS = {"landscape": "landscape", "horizontal": "landscape", "portrait": "portrait",
            "vertical": "portrait", "square": "square"}
_TOL = 0.01
_DELEGATION = "Non-PMax video inventory → skill-036; creative theme critique → skill-162; channel outcomes → skill-128."


# ---------------------------------------------------------------------------- small helpers
def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _u(v) -> str:
    return _s(v).upper()


def _missing(ctx, key: str, cols) -> list[str]:
    t = ctx.table(key)
    if t is None:
        return [f"{key} (file)"]
    return [f"{key}:{c}" for c in t.missing(cols)]


def _complete(ctx, key: str) -> bool:
    t = ctx.table(key)
    return t is not None and t.complete is True and not t.truncated


def _is_video(a: dict) -> bool:
    return "VIDEO" in _u(a.get("asset_type")) or "VIDEO" in _u(a.get("field_type"))


def _state(a: dict) -> str:
    st, ap = _u(a.get("association_status")), _u(a.get("approval_status"))
    if st == "REMOVED":
        return "removed"
    if ap == "DISAPPROVED":
        return "disapproved"
    if st == "PAUSED":
        return "paused"
    if st in _ACTIVE and ap in _APPROVED:
        return "eligible"
    return "unknown"


def _active(a: dict) -> bool:
    return _u(a.get("association_status")) in _ACTIVE


def _ratio_value(raw) -> tuple[float | None, bool]:
    """Parse '16:9', '16x9', '16/9' or a decimal. Returns (value, ok); empty/any → (None, True)."""
    s = _s(raw).lower().replace(" ", "")
    if s in _ANY:
        return None, True
    for sep in (":", "x", "/"):
        if sep in s:
            a, b = (V.num(p) for p in s.split(sep, 1))
            return (a / b, True) if a and b and a > 0 and b > 0 else (None, False)
    f = V.num(s)
    return (f, True) if f and f > 0 else (None, False)


def _spec(d: dict) -> dict:
    """Media facts from one pmax_video_details row. Rules: ratio only from nonzero positive dimensions."""
    w, h, dur = V.num(d.get("width_px")), V.num(d.get("height_px")), V.num(d.get("duration_seconds"))
    ratio = V.ratio(w, h) if w and h and w > 0 and h > 0 else None
    orient = None
    if ratio is not None:
        orient = "square" if abs(ratio - 1) <= _TOL else "landscape" if ratio > 1 else "portrait"
    return {"width_px": w, "height_px": h, "duration_seconds": dur, "aspect_ratio": ratio, "orientation": orient}


def _provenance(d: dict) -> tuple[str | None, bool]:
    p = _s(d.get("creation_provenance")).lower()
    p = p if p in ("advertiser", "automated") else None
    return p, bool(p and _s(d.get("provenance_reference")))


class _Model:
    """Joined PMax inventory. Rules: built once; every collection keyed by IDs and iterated sorted."""

    def __init__(self, ctx):
        self.notes: list[str] = []
        self.non_pmax_rows = 0
        self.missing: list[str] = []
        self.camps: dict[str, dict] = {}
        ct = ctx.table("campaigns")
        idcol = None
        if ct is not None:
            idcol = "id" if "id" in ct.columns else "campaign_id" if "campaign_id" in ct.columns else None
            if idcol is None:
                self.missing.append("campaigns:id")
        self.subtype_col = next((c for c in SUBTYPE_COLS if ct is not None and c in ct.columns), None)
        for r in (ct.rows if ct is not None and idcol else []):
            cid = _s(r.get(idcol))
            if cid and cid not in self.camps:
                self.camps[cid] = r
        self.pmax = {c for c, r in self.camps.items() if _u(r.get("channel_type")) == "PERFORMANCE_MAX"}
        self.groups: dict[tuple[str, str], dict] = {}
        dup = non_pmax = 0
        for r in ctx.rows(GROUPS):
            key = (_s(r.get("campaign_id")), _s(r.get("asset_group_id")))
            if not all(key):
                continue
            if key[0] in self.camps and key[0] not in self.pmax:
                non_pmax += 1
                continue
            if key in self.groups:
                dup += 1
                continue
            self.groups[key] = r
        if dup:
            self.notes.append(f"{GROUPS}: {dup} duplicate (campaign_id, asset_group_id) rows ignored")
        self.non_pmax_rows = non_pmax
        unknown_c = sorted({k[0] for k in self.groups if k[0] not in self.camps})
        if unknown_c:
            self.notes.append(f"campaigns lacks campaign(s) {unknown_c} referenced by {GROUPS}; their status/languages unknown")
        self.videos: list[dict] = []
        seen: set = set()
        dup = 0
        for a in ctx.rows(ASSOCS):
            cid, gid, aid = _s(a.get("campaign_id")), _s(a.get("asset_group_id")), _s(a.get("asset_id"))
            if not (cid and gid and aid) or not _is_video(a):
                continue
            if cid in self.camps and cid not in self.pmax:
                continue
            k = (cid, gid, aid, _u(a.get("field_type")))
            if k in seen:
                dup += 1
                continue
            seen.add(k)
            self.videos.append({**a, "_cid": cid, "_gid": gid, "_aid": aid, "_state": _state(a)})
        self.videos.sort(key=lambda a: (a["_cid"], a["_gid"], a["_aid"], _u(a.get("field_type"))))
        if dup:
            self.notes.append(f"{ASSOCS}: {dup} duplicate video association rows ignored")
        orphans = sorted({(a["_cid"], a["_gid"]) for a in self.videos if (a["_cid"], a["_gid"]) not in self.groups})
        if orphans:
            self.notes.append(f"{ASSOCS}: video associations reference {len(orphans)} group(s) absent from {GROUPS}: "
                              f"{[f'{c}/{g}' for c, g in orphans]}")
        self.by_group: dict[tuple[str, str], list[dict]] = {}
        for a in self.videos:
            self.by_group.setdefault((a["_cid"], a["_gid"]), []).append(a)

    def serving(self, key: tuple[str, str]) -> bool | None:
        """True when group ENABLED and campaign ENABLED; False when either is explicitly not enabled."""
        g = self.groups.get(key)
        gs = _u(g.get("status")) if g else ""
        if gs and gs != "ENABLED":
            return False
        cs = _u((self.camps.get(key[0]) or {}).get("status"))
        if cs and cs != "ENABLED":
            return False
        return True if gs == "ENABLED" and cs == "ENABLED" else None

    def counts(self, key) -> dict:
        out = {s: 0 for s in ("eligible", "disapproved", "removed", "paused", "unknown")}
        for a in self.by_group.get(key, []):
            out[a["_state"]] += 1
        return out


def _details(ctx) -> tuple[dict[str, dict], list[str]]:
    rows: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for r in ctx.rows(DETAILS):
        aid = _s(r.get("asset_id"))
        if not aid:
            continue
        if aid in rows and rows[aid] != r:
            ambiguous.add(aid)
        rows.setdefault(aid, r)
    for aid in ambiguous:
        rows.pop(aid, None)
    return rows, sorted(ambiguous)


def _base_check(ctx, cid: str, title: str, needs: dict, model_box: list):
    """Declare a check; skip it when the shared campaign key is unusable. Returns (check, model|None)."""
    c = ctx.check(cid, title, needs)
    if not c.runnable:
        return c, None
    if not model_box:
        model_box.append(_Model(ctx))
    m = model_box[0]
    if m.missing:
        c.skip("campaign key column unavailable", m.missing)
        return c, None
    return c, m


# ---------------------------------------------------------------------------- steps
def run(ctx) -> None:
    """Six recipe steps as checks: inventory, media specs, requirements, content, metrics, proposal.

    Rules:   Group linkage only from custom/pmax_groups + pmax_group_assets; zero-video/zero-eligible claims need both
             manifests complete; custom-video absence is never a defect by itself; every check ends with coverage.
    """
    box: list = []
    camp_needs = {"campaigns": ["channel_type"]}
    base = {**camp_needs, GROUPS: GROUP_COLS, ASSOCS: ASSOC_COLS}

    _inventory(ctx, *_base_check(ctx, "video_inventory", "Group-level video association inventory", base, box))
    details, ambiguous = _details(ctx)
    _media(ctx, *_base_check(ctx, "media_specs", "Media dimensions, duration, provenance and rights",
                             {**base, DETAILS: ["asset_id", "width_px", "height_px", "duration_seconds",
                                                "creation_provenance", "provenance_reference",
                                                "rights_brand_approval"]}, box), details, ambiguous)
    _requirements(ctx, *_base_check(ctx, "requirements", "Applicable video requirements and current diagnostics",
                                    {**camp_needs, GROUPS: GROUP_COLS + ["platform_diagnostic", "primary_status"],
                                     ASSOCS: ASSOC_COLS}, box), details, ambiguous)
    _content(ctx, *_base_check(ctx, "content_consistency", "Offer, language and brand consistency of media",
                               {**base, DETAILS: ["asset_id", "content_review", "language"]}, box), details)
    _metrics(ctx, *_base_check(ctx, "video_metrics", "Video view/completion metrics and performance labels",
                               base, box))
    _proposal(ctx, *_base_check(ctx, "video_proposal", "Demonstrated video coverage needs", base, box))


def _inventory(ctx, chk, m) -> None:
    if m is None:
        return
    for n in m.notes:
        chk.partial(n)
    if m.non_pmax_rows:
        chk.observe("Non-PMax rows in pmax_groups dropped (skill-036 scope)", rows=m.non_pmax_rows)
    complete = _complete(ctx, GROUPS) and _complete(ctx, ASSOCS)
    if not complete:
        chk.partial("pmax_groups/pmax_group_assets not both manifest-complete: zero-video groups cannot be proven")
    details, _ = _details(ctx)
    if ctx.table(DETAILS) is None:
        chk.partial("provenance classification unavailable", [f"{DETAILS} (file)"])
    for key in sorted(m.groups):
        g, vids = m.groups[key], m.by_group.get(key, [])
        rows = []
        for a in vids:
            d = details.get(a["_aid"])
            prov, verified = _provenance(d) if d else (None, False)
            rows.append({"asset_id": a["_aid"], "field_type": a.get("field_type"), "state": a["_state"],
                         "association_status": a.get("association_status"),
                         "approval_status": a.get("approval_status"),
                         "provenance": (prov if verified else "unknown") if d else "no_details",
                         **({k: v for k, v in _spec(d).items()} if d else {})})
        label = ("zero video associations" if complete else "no video association observed (absence unproven)") \
            if not vids else f"{len(vids)} video association(s)"
        chk.observe(f"Group {key[0]}/{key[1]}: {label}", campaign_id=key[0], asset_group_id=key[1],
                    group_status=g.get("status"), serving=m.serving(key), counts=m.counts(key), videos=rows,
                    inventory_complete=complete)
    grouped = {k[0] for k in m.groups}
    for cid in sorted(m.pmax - grouped):
        chk.observe(f"PMax campaign {cid}: no asset group in {GROUPS}"
                    + ("" if _complete(ctx, GROUPS) else " (absence unproven)"), campaign_id=cid)
    at = ctx.table("assets")
    if at is None:
        chk.partial("account asset inventory unavailable (context only; never proves linkage)", ["assets (file)"])
    else:
        idc = "asset_id" if "asset_id" in at.columns else "id" if "id" in at.columns else None
        tc = "type" if "type" in at.columns else "asset_type" if "asset_type" in at.columns else None
        if idc is None or tc is None:
            chk.partial("assets.csv lacks asset id/type columns", [x for x, ok in
                        (("assets:asset_id", idc), ("assets:type", tc)) if not ok])
        else:
            linked = {a["_aid"] for a in m.videos}
            acct = sorted({_s(r.get(idc)) for r in at.rows if "VIDEO" in _u(r.get(tc)) and _s(r.get(idc))})
            chk.observe("Account video assets without any PMax group association (inventory is not linkage)",
                        account_video_assets=len(acct), unlinked=[a for a in acct if a not in linked])
    chk.observe("PMax video inventory", pmax_campaigns=len(m.pmax), groups=len(m.groups),
                video_associations=len(m.videos),
                groups_without_video=sum(1 for k in m.groups if not m.by_group.get(k)))


def _media(ctx, chk, m, details, ambiguous) -> None:
    if m is None:
        return
    if ambiguous:
        chk.partial(f"{DETAILS}: conflicting duplicate rows for asset(s) {ambiguous}; not evaluated")
    linked: dict[str, list[dict]] = {}
    for a in m.videos:
        if a["_state"] != "removed":
            linked.setdefault(a["_aid"], []).append(a)
    no_detail, no_dims, no_rights = [], [], []
    for aid in sorted(linked):
        assocs = linked[aid]
        groups = [f"{a['_cid']}/{a['_gid']}" for a in assocs]
        d = details.get(aid)
        if d is None:
            if aid not in ambiguous:
                no_detail.append(aid)
            continue
        spec = _spec(d)
        if spec["aspect_ratio"] is None:
            no_dims.append(aid)
        if spec["duration_seconds"] is None:
            no_dims.append(aid)
        prov, verified = _provenance(d)
        chk.observe(f"Video {aid}: media facts", asset_id=aid, groups=groups, **spec,
                    creation_provenance=d.get("creation_provenance"), provenance_verified=verified,
                    youtube_video_id=d.get("youtube_video_id"), reviewed_at=d.get("reviewed_at"),
                    source_reference=d.get("source_reference"))
        entity = {"asset_id": aid, "asset_group_ids": groups}
        if not verified:
            chk.finding("unknown_provenance", "Info", entity,
                        f"Video {aid} provenance is not verified (declared {d.get('creation_provenance')!r}, "
                        f"reference {d.get('provenance_reference')!r})",
                        evidence={"creation_provenance": d.get("creation_provenance"),
                                  "provenance_reference": d.get("provenance_reference"), "groups": groups},
                        recommendation="Record advertiser/automated provenance with a reference from the media "
                                       "library or Ads asset detail; do not infer it from names.",
                        uncertainty="Unknown provenance says nothing about quality or delivery.")
        rights = _s(d.get("rights_brand_approval")).lower()
        active = [a for a in assocs if _active(a)]
        if not rights:
            no_rights.append(aid)
        elif rights in _RIGHTS_DENIED and active:
            ag = [f"{a['_cid']}/{a['_gid']}" for a in active]
            chk.finding("rights_mismatch", "Warning", {**entity, "asset_group_ids": ag},
                        f"Video {aid} has rights/brand approval '{rights}' but is actively associated with {len(ag)} group(s)",
                        evidence={"rights_brand_approval": d.get("rights_brand_approval"),
                                  "reviewed_at": d.get("reviewed_at"), "source_reference": d.get("source_reference"),
                                  "active_associations": [{"group": f"{a['_cid']}/{a['_gid']}",
                                                           "field_type": a.get("field_type"),
                                                           "association_status": a.get("association_status")}
                                                          for a in active]},
                        recommendation="Owner review: confirm the rights status and, if confirmed, request removal "
                                       "or replacement of the association (recommend-only).",
                        uncertainty="Rights status is as recorded at reviewed_at; renewals after that date are unseen.")
        elif rights not in _RIGHTS_OK and rights not in _RIGHTS_DENIED:
            chk.observe(f"Video {aid}: rights/brand approval value not decidable", value=rights)
    if no_detail:
        chk.partial(f"{len(no_detail)} linked video(s) lack a {DETAILS} row: {no_detail}", [f"{DETAILS}:asset_id"])
    if no_dims:
        chk.partial(f"dimensions or duration unknown for {sorted(set(no_dims))}; ratio/duration not derived")
    if no_rights:
        chk.observe("Linked videos without a rights/brand review", asset_ids=no_rights)
    unlinked = sorted(set(details) - set(linked))
    chk.observe("Media-library videos reviewed", linked=len(linked), details_rows=len(details),
                details_without_group_link=unlinked)


def _rule_eval(rule: dict, spec: dict) -> tuple[list[dict], list[str]]:
    """Return (violations, undecidable) of one supported rule for one video spec."""
    viol, und = [], []
    for col, key, op in (("min_width_px", "width_px", "min"), ("min_height_px", "height_px", "min"),
                         ("min_duration_seconds", "duration_seconds", "min"),
                         ("max_duration_seconds", "duration_seconds", "max")):
        raw = rule.get(col)
        if _s(raw) == "":
            continue
        lim = V.num(raw)
        if lim is None:
            und.append(f"{col} malformed {raw!r}")
            continue
        obs = spec[key]
        if obs is None:
            und.append(f"{key} unknown")
        elif (op == "min" and obs < lim) or (op == "max" and obs > lim):
            viol.append({"limit": col, "required": lim, "observed": obs})
    want, ok = _ratio_value(rule.get("aspect_ratio"))
    if not ok:
        und.append(f"aspect_ratio malformed {rule.get('aspect_ratio')!r}")
    elif want is not None:
        if spec["aspect_ratio"] is None:
            und.append("aspect ratio unknown")
        elif abs(spec["aspect_ratio"] - want) / want > _TOL:
            viol.append({"limit": "aspect_ratio", "required": rule.get("aspect_ratio"),
                         "observed": round(spec["aspect_ratio"], 4)})
    return viol, und


def _requirements(ctx, chk, m, details, ambiguous) -> None:
    if m is None:
        return
    # -- current diagnostics (always evaluable from groups + associations)
    unknown_serving = 0
    for a in m.videos:
        if a["_state"] != "disapproved":
            continue
        key = (a["_cid"], a["_gid"])
        serving = m.serving(key)
        if serving is None:
            unknown_serving += 1
            continue
        if not serving:
            continue
        g = m.groups.get(key, {})
        entity = {"campaign_id": key[0], "asset_group_id": key[1], "asset_id": a["_aid"],
                  "field_type": a.get("field_type")}
        ev = {"approval_status": a.get("approval_status"), "association_status": a.get("association_status"),
              "group_status": g.get("status"), "primary_status": g.get("primary_status"),
              "platform_diagnostic": g.get("platform_diagnostic"), "group_video_counts": m.counts(key)}
        prov = chk.finding("video_disapproval_diagnostic", "Info", entity,
                           f"Video {a['_aid']} is disapproved in enabled group {key[0]}/{key[1]}",
                           evidence=ev, recommendation="Check the policy detail and whether the group still serves "
                                                       "its intended formats; replace or appeal (recommend-only).",
                           uncertainty="Disapproval of one asset does not by itself prove blocked serving.")
        chk.review("video_disapproval_diagnostic", entity,
                   f"Does the disapproval of video {a['_aid']} directly block materially required intended serving "
                   f"of group {key[0]}/{key[1]}?",
                   evidence=ev, provisional=prov,
                   outcomes={"blocks_required_serving": {"severity": "Critical", "recommendation":
                                                         "Prioritize a compliant replacement or appeal; cite the diagnostic."},
                             "not_blocking": {"severity": None, "recommendation": "No action beyond normal asset hygiene."},
                             "uncertain": {"severity": "Info", "recommendation":
                                           "Collect the current policy/diagnostic detail for this group."}},
                   guidance="Critical only with a current platform diagnostic proving blocked required serving; "
                            "supply proposal.evidence_ref to that diagnostic. Fewer videos or no portrait video "
                            "is not blocking.")
    for key in sorted(m.groups):
        g = m.groups[key]
        text = f"{_s(g.get('platform_diagnostic'))} {_s(g.get('primary_status'))}".lower()
        if "video" in text and m.serving(key) is True:
            entity = {"campaign_id": key[0], "asset_group_id": key[1]}
            chk.review("video_group_diagnostic", entity,
                       f"Does the current video-related diagnostic of group {key[0]}/{key[1]} directly block "
                       "materially required intended serving?",
                       evidence={"platform_diagnostic": g.get("platform_diagnostic"),
                                 "primary_status": g.get("primary_status"), "group_video_counts": m.counts(key)},
                       outcomes={"blocks_required_serving": {"severity": "Critical", "recommendation":
                                                             "Resolve the diagnostic; cite it in the proposal."},
                                 "not_blocking": {"severity": None, "recommendation": "No action."},
                                 "uncertain": {"severity": "Info", "recommendation": "Obtain the full diagnostic detail."}},
                       guidance="Literal 'video' mention only; judge the diagnostic meaning. Critical needs "
                                "proposal.evidence_ref.")
    if unknown_serving:
        chk.partial(f"{unknown_serving} disapproved video association(s) in groups/campaigns with unknown status")
    # -- supplied requirement rows
    miss = _missing(ctx, REQS, REQ_COLS) + _missing(ctx, DETAILS, ["asset_id", "width_px", "height_px",
                                                                    "duration_seconds"])
    if miss:
        chk.partial("requirement rules not evaluated", miss)
        return
    rules = sorted(ctx.rows(REQS), key=lambda r: (_s(r.get("rule_id")), _s(r.get("campaign_subtype")),
                                                   _s(r.get("intended_format"))))
    und_notes: set[str] = set()
    evaluated = 0
    unsupported = []
    for rule in rules:
        rid = _s(rule.get("rule_id"))
        sub, fmt = _s(rule.get("campaign_subtype")).lower(), _s(rule.get("intended_format")).lower()
        kind = _s(rule.get("required_or_recommended")).lower()
        supported = V.boolean(rule.get("supported"))
        if fmt not in _ANY and fmt not in _FORMATS:
            und_notes.add(f"rule {rid}: intended_format '{fmt}' is not an orientation; not applied")
            continue
        if supported is None:
            und_notes.add(f"rule {rid}: supported unknown; not applied")
            continue
        if kind not in ("required", "recommended") and supported:
            und_notes.add(f"rule {rid}: required_or_recommended '{kind}' undecidable")
            continue
        for a in m.videos:
            if not _active(a) or a["_state"] == "removed":
                continue
            if sub not in _ANY:
                csub = _s((m.camps.get(a["_cid"]) or {}).get(m.subtype_col)).lower() if m.subtype_col else ""
                if not csub:
                    und_notes.add(f"rule {rid}: campaign {a['_cid']} subtype unknown"
                                  + ("" if m.subtype_col else " (campaigns:channel_subtype absent)"))
                    continue
                if csub != sub:
                    continue
            d = details.get(a["_aid"])
            if d is None:
                und_notes.add(f"asset {a['_aid']}: no unambiguous {DETAILS} row")
                continue
            spec = _spec(d)
            if fmt not in _ANY:
                if spec["orientation"] is None:
                    und_notes.add(f"rule {rid}: asset {a['_aid']} orientation unknown")
                    continue
                if spec["orientation"] != _FORMATS[fmt]:
                    continue
            if not supported:
                unsupported.append({"rule_id": rid, "campaign_id": a["_cid"], "asset_group_id": a["_gid"],
                                    "asset_id": a["_aid"]})
                continue
            evaluated += 1
            viol, und = _rule_eval(rule, spec)
            for u in und:
                und_notes.add(f"rule {rid}, asset {a['_aid']}: {u}")
            if not viol:
                continue
            entity = {"campaign_id": a["_cid"], "asset_group_id": a["_gid"], "asset_id": a["_aid"], "rule_id": rid}
            ev = {"violations": viol, "rule": {k: rule.get(k) for k in REQ_COLS},
                  "requirement_conditions": rule.get("requirement_conditions"), "source_url": rule.get("source_url"),
                  "checked_at": rule.get("checked_at"), "media": spec, "media_source": d.get("source_reference")}
            if kind == "required":
                chk.finding("requirement_failure", "Warning", entity,
                            f"Video {a['_aid']} in group {a['_cid']}/{a['_gid']} fails required rule {rid}",
                            evidence=ev, recommendation="Owner review: supply a compliant version of this video for "
                                                        "the affected format (recommend-only).",
                            uncertainty="Valid for the rule as documented at checked_at and the recorded media facts.")
            else:
                chk.finding("recommended_spec_gap", "Info", entity,
                            f"Video {a['_aid']} in group {a['_cid']}/{a['_gid']} misses recommended rule {rid}",
                            evidence=ev, recommendation="Optional: consider a version meeting the recommendation.",
                            uncertainty="Recommendation, not an eligibility constraint.")
    if unsupported:
        chk.observe("Active videos matching rows marked supported=false (configuration context, not a failure)",
                    matches=unsupported)
    for n in sorted(und_notes):
        chk.partial(n)
    chk.observe("Requirement rules applied", rules=len(rules), video_rule_pairs=evaluated,
                note="Missing portrait ratio or video count is never a requirement failure.")


def _languages(camp: dict | None) -> list[str]:
    return [x.lower() for x in V.split_list((camp or {}).get("languages"), (";", "|", ","))]


def _content(ctx, chk, m, details) -> None:
    if m is None:
        return
    has_theme = ctx.table(GROUPS) is not None and "theme" in ctx.table(GROUPS).columns
    ct = ctx.table("campaigns")
    has_lang = ct is not None and "languages" in ct.columns
    if not has_theme:
        chk.partial("group theme unknown", [f"{GROUPS}:theme"])
    if not has_lang:
        chk.partial("campaign languages unknown", ["campaigns:languages"])
    no_review = set()
    for a in m.videos:
        if not _active(a) or a["_state"] in ("removed", "disapproved"):
            continue
        d = details.get(a["_aid"])
        if d is None or not _s(d.get("content_review")):
            no_review.add(a["_aid"])
            continue
        key = (a["_cid"], a["_gid"])
        camp = m.camps.get(key[0])
        langs = _languages(camp) if has_lang else []
        vlang = _s(d.get("language")).lower()
        literal = (vlang in langs) if vlang and langs else None
        entity = {"campaign_id": key[0], "asset_group_id": key[1], "asset_id": a["_aid"]}
        chk.review("video_content_mismatch", entity,
                   f"Is video {a['_aid']} consistent with the offer, language, product and brand of group "
                   f"{key[0]}/{key[1]}?",
                   evidence={"content_review": d.get("content_review"), "video_language": d.get("language"),
                             "campaign_languages": langs or None, "language_literal_match": literal,
                             "group_theme": (m.groups.get(key) or {}).get("theme") if has_theme else None,
                             "group_name": (m.groups.get(key) or {}).get("name"),
                             "final_urls": (m.groups.get(key) or {}).get("final_urls"),
                             "rights_brand_approval": d.get("rights_brand_approval"),
                             "reviewed_at": d.get("reviewed_at"),
                             "intended_offer": ctx.profile.get("intended_offer")},
                   outcomes={"mismatch": {"severity": "Warning", "recommendation":
                                          "Owner review of the concrete mismatch; request a matching video (recommend-only)."},
                             "consistent": {"severity": None, "recommendation": "No action."},
                             "uncertain": {"severity": "Info", "recommendation": "Obtain a content review of this video."}},
                   guidance="Judge only the recorded content review against group theme, campaign languages and "
                            "profile offer. Creation provenance (advertiser vs automated) MUST NOT influence the "
                            "outcome and is deliberately omitted. language_literal_match is a literal code "
                            "comparison, not proof. Creative theme critique belongs to skill-162.")
    if no_review:
        chk.partial(f"{len(no_review)} active video(s) without content_review: {sorted(no_review)}",
                    [f"{DETAILS}:content_review"])


def _metrics(ctx, chk, m) -> None:
    if m is None:
        return
    # -- contextual performance labels
    if ctx.table(ASSOCS) is not None and "performance_label" in ctx.table(ASSOCS).columns:
        for a in m.videos:
            if _u(a.get("performance_label")) != "LOW" or not _active(a):
                continue
            entity = {"campaign_id": a["_cid"], "asset_group_id": a["_gid"], "asset_id": a["_aid"],
                      "field_type": a.get("field_type")}
            chk.finding("low_performance_label", "Info", entity,
                        f"Video {a['_aid']} carries the contextual performance label LOW in group {a['_cid']}/{a['_gid']}",
                        evidence={"performance_label": a.get("performance_label"),
                                  "association_status": a.get("association_status")},
                        recommendation="Review in context with like-format metrics before any replacement request; "
                                       "channel outcomes belong to skill-128.",
                        uncertainty="Platform labels are relative and contextual; not proof of harm.")
    else:
        chk.partial("performance labels unavailable", [f"{ASSOCS}:performance_label"])
    # -- optional metrics report
    miss = _missing(ctx, METRICS, ["campaign_id", "asset_id", "date", "format", "impressions", "video_views",
                                   "rate_denominator_definition"])
    mt = ctx.table(METRICS)
    if mt is not None and "completed_views" not in mt.columns and "reported_completion_rate" not in mt.columns:
        miss.append(f"{METRICS}:completed_views")
    if miss:
        chk.partial("video metrics unavailable (never allocated from campaign totals)", miss)
        return
    if ctx.period_start is None or ctx.period_end is None:
        chk.partial("report period unknown; metrics not aggregated", ["account:date_range_start", "account:date_range_end"])
        return
    if mt.complete is not True:
        chk.partial(f"{mt.filename}: completeness not certified; totals are observed subsets")
    video_ids = {a["_aid"] for a in m.videos}
    seen, aggs = set(), {}
    dup = outside = other = 0
    for r in mt.rows:
        cid, aid = _s(r.get("campaign_id")), _s(r.get("asset_id"))
        d = V.parse_date(r.get("date"))
        if d is None or not (ctx.period_start <= d <= ctx.period_end):
            outside += 1
            continue
        if aid not in video_ids or (cid in m.camps and cid not in m.pmax):
            other += 1
            continue
        gid, fmt = _s(r.get("asset_group_id")), _s(r.get("format")).lower()
        grain = (cid, gid, aid, d, fmt)
        if grain in seen:
            dup += 1
            continue
        seen.add(grain)
        acc = aggs.setdefault((cid, gid, aid, fmt), {"rows": [], "defs": set()})
        acc["rows"].append(r)
        acc["defs"].add(_s(r.get("rate_denominator_definition")))
    if dup:
        chk.partial(f"{dup} duplicate metric rows at (campaign, group, asset, date, format) ignored")
    if outside:
        chk.partial(f"{outside} metric rows outside {ctx.period_start}..{ctx.period_end} or undated excluded")
    if other:
        chk.observe("Metric rows for non-video or non-PMax assets ignored", rows=other)
    res = ctx.params.get("min_impressions")
    has_completed = "completed_views" in mt.columns
    summary = []
    for key in sorted(aggs):
        rows, defs = aggs[key]["rows"], aggs[key]["defs"]

        def total(col):
            vals = [V.num(r.get(col)) for r in rows] if col in mt.columns else [None]
            return None if any(v is None for v in vals) else sum(vals)

        impr, views = total("impressions"), total("video_views")
        definition = next(iter(defs)) if len(defs) == 1 else ""
        rate, basis = None, None
        if not definition:
            basis = "rate_denominator_definition missing or inconsistent: completion undefined"
        elif has_completed and total("completed_views") is not None:
            rate, basis = V.ratio(total("completed_views"), views), "sum(completed_views)/sum(video_views)"
        elif "reported_completion_rate" in mt.columns and len(rows) == 1:
            rate, basis = ctx.rate(rows[0].get("reported_completion_rate")), "reported_completion_rate (single row)"
        else:
            basis = "row rates not averaged; completion undefined"
        rec = {"campaign_id": key[0], "asset_group_id": key[1] or None, "asset_id": key[2], "format": key[3],
               "impressions": impr, "video_views": views, "completion_rate": rate, "basis": basis,
               "rate_denominator_definition": definition or None, "days": len(rows),
               "reported_conversions": total("conversions"),
               "attribution_scope": sorted({_s(r.get("attribution_scope")) for r in rows} - {""}) or None}
        summary.append(rec)
        chk.observe(f"Video {key[2]} {key[3] or 'unspecified format'} metrics {ctx.period_start}..{ctx.period_end}",
                    **rec, note="Reported per-asset conversions only; campaign conversions are never allocated.")
    # -- like-format comparisons
    if res.value is None:
        chk.partial(f"min_impressions unresolved: {res.reason}; no comparisons")
        return
    if ctx.mature is not True:
        chk.partial(f"like-format comparisons withheld: maturity={ctx.mature} ({ctx.maturity_note})")
        return
    cohorts: dict[tuple, list[dict]] = {}
    for rec in summary:
        if rec["completion_rate"] is not None and rec["format"]:
            cohorts.setdefault((rec["campaign_id"], rec["format"], rec["rate_denominator_definition"]), []).append(rec)
    for ck in sorted(cohorts):
        ok = [r for r in cohorts[ck] if r["impressions"] is not None and r["impressions"] >= res.value]
        if len(ok) < 2:
            continue
        ok.sort(key=lambda r: (-r["completion_rate"], r["asset_id"]))
        chk.observe(f"Campaign {ck[0]} {ck[1]}: like-format completion comparison",
                    campaign_id=ck[0], format=ck[1], definition=ck[2], min_impressions=res.value,
                    min_impressions_source=res.source,
                    ranking=[{"asset_id": r["asset_id"], "asset_group_id": r["asset_group_id"],
                              "completion_rate": r["completion_rate"], "impressions": r["impressions"]} for r in ok],
                    note="Descriptive only; no universal completion cutoff.")


def _proposal(ctx, chk, m) -> None:
    if m is None:
        return
    if not (_complete(ctx, GROUPS) and _complete(ctx, ASSOCS)):
        chk.partial("zero-eligible-video groups not provable: pmax_groups/pmax_group_assets not manifest-complete")
        return
    batch, unknown = [], []
    for key in sorted(m.groups):
        serving = m.serving(key)
        c = m.counts(key)
        if serving is False or c["eligible"]:
            continue
        if serving is None or c["unknown"]:
            unknown.append(f"{key[0]}/{key[1]}")
            continue
        g = m.groups[key]
        batch.append({"campaign_id": key[0], "asset_group_id": key[1], "name": g.get("name"),
                      "theme": g.get("theme"), "ad_strength": g.get("ad_strength"),
                      "final_urls": g.get("final_urls"), "video_counts": c})
    if unknown:
        chk.partial(f"groups with unknown serving status or association state not assessed: {unknown}")
    chk.observe("Enabled groups without an eligible video association", groups=len(batch),
                note="Zero videos alone is not a defect; automated video may exist without a custom association.")
    if not batch:
        return
    chk.review("video_coverage_need", {"batch": "groups_without_eligible_video"},
               "For which of these groups is a specific video/format need demonstrated by brand, requirement or "
               "planned-coverage evidence?",
               evidence={"groups": batch, "objectives": ctx.profile.get("objectives")},
               outcomes={"coverage_need_documented": {"severity": "Info", "recommendation":
                                                      "Request the specific permitted video/format for the listed groups."},
                         "no_need": {"severity": None, "recommendation": "No action; no video-count mandate."}},
               guidance="Choose coverage_need_documented only with a planning/brief reference: supply "
                        "proposal.planning_reference and proposal.asset_group_ids (from this batch). Never argue "
                        "from video counts or missing portrait alone. " + _DELEGATION)


def verify(ctx, item, decision) -> list[str]:
    """Deterministic checks on accepted proposals.

    Rules:   blocks_required_serving needs proposal.evidence_ref; coverage_need_documented needs
             proposal.planning_reference and non-empty proposal.asset_group_ids all from the reviewed batch.
    """
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "blocks_required_serving" and not _s(proposal.get("evidence_ref")):
        return ["Critical needs proposal.evidence_ref pointing at the current platform diagnostic"]
    if item.condition_key == "video_coverage_need" and outcome == "coverage_need_documented":
        problems = []
        if not _s(proposal.get("planning_reference")):
            problems.append("proposal.planning_reference required")
        ids = proposal.get("asset_group_ids")
        ids = [ids] if isinstance(ids, str) else ids
        if not isinstance(ids, list) or not ids:
            problems.append("proposal.asset_group_ids required (non-empty list)")
        else:
            batch = {_s(g["asset_group_id"]) for g in item.evidence.get("groups", [])}
            problems += [f"asset group {x} not in reviewed batch" for x in ids if _s(x) not in batch]
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
