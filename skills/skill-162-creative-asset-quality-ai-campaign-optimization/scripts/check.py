"""check.py — skill-162 deterministic creative coverage, spec conformance and label-history review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-162-creative-asset-quality-ai-campaign-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Scope = groups whose campaigns.channel_type is PERFORMANCE_MAX, DEMAND_GEN or SEARCH (join on campaign_id);
         unknown channel → partial, kept visible. Groups LEFT JOIN associations on group_id so empty groups stay
         visible; absence (empty group, missing format) is a finding only when BOTH creative_group_inventory and
         creative_quality_assets are manifest-complete. Removed/paused associations do not count as linked;
         unknown linked_status is neither linked nor absent.
         Spec bounds are applied only when supported_asset_spec parses fully under _SPEC_RE
         ([min_|max_]width|height|duration_seconds with >=,<=,>,<,=; ';' or ',' separated); anything else is
         ambiguous → review (required) or partial (recommended). Required conflict → Warning; recommended → Info;
         measured value unknown → partial, never a pass. Requirements match by normalized subtype AND
         format == asset_type or field_role. Critical only via review 'material_block_evidenced' + evidence_ref.
         Provenance outside custom/generated stays unknown; no custom video never implies auto-generated delivery.
         Literal duplicates: lowercase, punctuation → space, collapsed whitespace, within group + field_role → Info.
         Persistent Low needs ≥2 dated creative_label_history rows ending in a Low run in ONE reporting_context.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
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

SKILL = "skill-162-creative-asset-quality-ai-campaign-optimization"
VERSION = "1.0.0"

INV = "custom/creative_group_inventory"
ASSETS = "custom/creative_quality_assets"
HIST = "custom/creative_label_history"
REQ = "external/creative_requirements"
_CHANNELS = {"PERFORMANCE_MAX", "DEMAND_GEN", "SEARCH"}
_LINKED = {"enabled", "active", "linked", "serving"}
_UNLINKED = {"removed", "paused", "unlinked", "disabled", "inactive"}
_GROUP_OFF = {"removed", "paused", "disabled"}
_SPEC_RE = re.compile(r"^(min_|max_)?(width|height|duration_seconds)\s*(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)$")
_BLOCK = "material_block_evidenced"


def _id(v) -> str:
    return "" if v is None else str(v).strip()


def _linked(v) -> bool | None:
    s = V.norm_text(v)
    return True if s in _LINKED else False if s in _UNLINKED else None


def _norm_literal(v) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(v or "").lower()).split())


def _parse_spec(spec) -> list[tuple[str, str, float]] | None:
    """Numeric bounds from supported_asset_spec, [] when empty, None when any part is ambiguous."""
    s = _id(spec)
    if not s:
        return []
    out = []
    for part in re.split(r"[;,]", s):
        part = part.strip().lower()
        if not part:
            continue
        m = _SPEC_RE.match(part)
        if not m:
            return None
        prefix, field, op, val = m.group(1), m.group(2), m.group(3), float(m.group(4))
        if prefix:
            if op != "=":
                return None
            op = ">=" if prefix == "min_" else "<="
        out.append((field, op, val))
    return out


def _violates(value: float, op: str, bound: float) -> bool:
    return not {">=": value >= bound, "<=": value <= bound, ">": value > bound, "<": value < bound,
                "=": value == bound}[op]


def _complete(ctx, *keys) -> bool:
    return all((t := ctx.table(k)) is not None and t.complete is True and not t.truncated for k in keys)


class Groups:
    """In-scope groups (by group_id) with their associations (left join)."""

    def __init__(self, ctx, check):
        channels = {_id(r.get("id")): str(r.get("channel_type") or "").upper() for r in ctx.rows("campaigns")}
        rows: dict[str, list] = {}
        for r in ctx.rows(INV):
            rows.setdefault(_id(r.get("group_id")), []).append(r)
        self.groups: dict[str, dict] = {}
        out_scope, unknown = [], []
        for gid in sorted(rows):
            rs = rows[gid]
            if not gid or any(r != rs[0] for r in rs[1:]):
                check.partial(f"{INV}: group_id '{gid}' missing or listed with differing rows; excluded")
                continue
            ch = channels.get(_id(rs[0].get("campaign_id")), "")
            if ch and ch not in _CHANNELS:
                out_scope.append(gid)
                continue
            if not ch:
                unknown.append(gid)
            self.groups[gid] = rs[0]
        if unknown:
            check.partial(f"campaign channel unknown for groups {unknown}; kept in scope")
        if out_scope:
            check.observe("Groups outside PMax/Demand Gen/Search scope", group_ids=out_scope)
        self.assoc: dict[str, list] = {g: [] for g in self.groups}
        self.orphans = 0
        for a in sorted(ctx.rows(ASSETS), key=lambda a: (_id(a.get("group_id")), _id(a.get("association_id")))):
            g = _id(a.get("group_id"))
            if g in self.assoc:
                self.assoc[g].append(a)
            else:
                self.orphans += 1

    def usable(self, gid: str) -> list[dict]:
        return [a for a in self.assoc[gid] if _linked(a.get("linked_status")) is not False]


def run(ctx) -> None:
    """Run group association coverage, spec conformance, provenance, duplicate text and performance-label checks.

    Rules:   Unknown channel → partial. Absence findings need both inventories manifest-complete. Required format/spec
             conflict → Warning, recommended → Info; unparseable specs → review (required) or partial; unknown measured
             value never passes. Critical only via review 'material_block_evidenced'. Literal duplicates and persistent
             Low labels (>= 2 dated rows in one reporting_context) are Info; unknown provenance never implies
             auto-generated.
    """
    base = {"campaigns": ["id", "channel_type"]}

    # -- step 1: left join groups to associations ----------------------------------------------
    cov = ctx.check("group_association_coverage", "All groups left-joined to asset associations",
                    {**base, INV: ["campaign_id", "group_type", "group_id", "subtype", "status", "eligibility_status"],
                     ASSETS: ["group_id", "association_id", "asset_id", "linked_status"]})
    G = None
    if cov.runnable:
        G = Groups(ctx, cov)
        complete = _complete(ctx, INV, ASSETS)
        if G.orphans:
            cov.partial(f"{G.orphans} associations reference groups absent from {INV}")
        empty = 0
        for gid, g in sorted(G.groups.items()):
            rows = G.assoc[gid]
            linked = sum(1 for a in rows if _linked(a.get("linked_status")) is True)
            unknown = sum(1 for a in rows if _linked(a.get("linked_status")) is None)
            cov.observe(f"Group {gid} associations", group_id=gid, campaign_id=g.get("campaign_id"),
                        group_type=g.get("group_type"), subtype=g.get("subtype"), status=g.get("status"),
                        associations=len(rows), linked=linked, linked_unknown=unknown)
            if linked or unknown:
                continue
            if not complete:
                cov.partial(f"group {gid}: no linked associations seen, but completeness not certified; absence unproven")
                continue
            empty += 1
            entity = {"campaign_id": _id(g.get("campaign_id")), "group_id": gid}
            ev = {"group_type": g.get("group_type"), "subtype": g.get("subtype"), "status": g.get("status"),
                  "eligibility_status": g.get("eligibility_status"), "goal": g.get("goal"),
                  "associations_total": len(rows), "linked": 0, "snapshot_at": g.get("snapshot_at")}
            prov = cov.finding("group_without_linked_assets", "Info", entity,
                               f"Group {gid} ({g.get('group_type')}) has no linked asset associations",
                               evidence=ev, recommendation="Confirm whether the group is meant to serve before adding assets.",
                               uncertainty="Complete inventories prove the empty association set, not its delivery impact.")
            if V.norm_text(g.get("status")) not in _GROUP_OFF:
                cov.review("group_without_linked_assets", entity,
                           f"Does empty group {gid} materially block intended eligible delivery?",
                           evidence=ev, provisional=prov,
                           outcomes={_BLOCK: {"severity": "Critical", "recommendation":
                                              "Supply the required assets per the approved brief; cite the delivery evidence."},
                                     "intentional_or_inactive": {"severity": None, "recommendation": "No action; document."},
                                     "uncertain": {"severity": "Info", "recommendation": "Request delivery/eligibility diagnostics."}},
                           guidance=f"'{_BLOCK}' needs proposal.evidence_ref to supplied eligibility/delivery evidence.")
        cov.observe("Group coverage totals", groups=len(G.groups), empty_groups=empty, orphan_associations=G.orphans)

    # -- step 2: documented required vs recommended specs ----------------------------------------
    spec = ctx.check("required_spec_conformance", "Observed specs versus documented required/recommended specs",
                     {**base, INV: ["campaign_id", "group_id", "subtype", "status"],
                      ASSETS: ["group_id", "association_id", "asset_type", "field_role", "linked_status", "width",
                               "height", "duration_seconds"],
                      REQ: ["subtype", "format", "requirement_id", "required_or_recommended", "supported_asset_spec",
                            "official_source_url", "checked_at"]})
    if spec.runnable:
        G2 = Groups(ctx, spec)
        _specs(ctx, spec, G2)

    # -- step 3: provenance ---------------------------------------------------------------------
    prov = ctx.check("provenance", "Asset provenance (custom/generated/unknown)",
                     {**base, INV: ["campaign_id", "group_id"],
                      ASSETS: ["group_id", "association_id", "asset_type", "linked_status", "provenance"]})
    if prov.runnable:
        G3 = Groups(ctx, prov)
        total_unknown = 0
        for gid in sorted(G3.groups):
            counts: dict[str, dict[str, int]] = {}
            for a in G3.usable(gid):
                p = V.norm_text(a.get("provenance"))
                p = p if p in ("custom", "generated") else "unknown"
                total_unknown += p == "unknown"
                t = counts.setdefault(V.norm_text(a.get("asset_type")) or "unknown_type", {})
                t[p] = t.get(p, 0) + 1
            prov.observe(f"Group {gid} provenance", group_id=gid, by_asset_type=counts)
            for t, c in sorted(counts.items()):
                if "video" in t and not c.get("custom") and c.get("unknown"):
                    prov.observe(f"Group {gid}: video provenance unknown; no custom video evidenced, auto-generated "
                                 "delivery not concluded", group_id=gid, asset_type=t, unknown=c["unknown"])
        if total_unknown:
            prov.partial(f"{total_unknown} associations with unknown provenance stay unknown")

    # -- step 4: literal duplicates and theme review --------------------------------------------
    dup = ctx.check("text_duplicates_and_themes", "Literal duplicate text and qualitative theme diversity",
                    {**base, INV: ["campaign_id", "group_id"],
                     ASSETS: ["group_id", "association_id", "asset_type", "field_role", "linked_status", "text"]})
    if dup.runnable:
        G4 = Groups(ctx, dup)
        dups = 0
        for gid, g in sorted(G4.groups.items()):
            texts = [a for a in G4.usable(gid) if _id(a.get("text"))]
            buckets: dict[tuple, list] = {}
            for a in texts:
                role = V.norm_text(a.get("field_role")) or V.norm_text(a.get("asset_type"))
                buckets.setdefault((role, _norm_literal(a.get("text"))), []).append(a)
            for (role, norm), rows in sorted(buckets.items()):
                if len(rows) < 2 or not norm:
                    continue
                dups += 1
                dup.finding("literal_duplicate_text", "Info",
                            {"campaign_id": _id(g.get("campaign_id")), "group_id": gid, "field_role": role,
                             "normalized_text": norm},
                            f"Group {gid}: {len(rows)} {role} associations share the literal text '{norm}'",
                            evidence={"association_ids": [_id(a.get("association_id")) for a in rows],
                                      "texts": [a.get("text") for a in rows],
                                      "normalization": "lowercase, punctuation to space, collapsed whitespace"},
                            recommendation="Replace one copy with a distinct, brief-backed message; see skill-025/026 for RSA text.",
                            uncertainty="Literal duplication only; no delivery impact estimate.")
            distinct = sorted({(V.norm_text(a.get("field_role")) or V.norm_text(a.get("asset_type")), a.get("text"))
                               for a in texts}, key=lambda x: (x[0], str(x[1])))
            if len(distinct) >= 2:
                dup.review("theme_diversity", {"campaign_id": _id(g.get("campaign_id")), "group_id": gid},
                           f"Do group {gid}'s texts repeat the same claim, or cover distinct benefits, proof and audience needs?",
                           evidence={"texts": [{"field_role": r, "text": t} for r, t in distinct],
                                     "business_theme": g.get("business_theme"), "goal": g.get("goal")},
                           outcomes={"diversity_opportunity": {"severity": "Info", "recommendation":
                                                               "Brief a distinct benefit/proof/audience-need variant for a test."},
                                     "adequate": {"severity": None, "recommendation": "No change."},
                                     "uncertain": {"severity": None, "recommendation": "Request the creative brief."}},
                           guidance="Rubric: same claim / distinct benefit / proof / audience need; cite examples. "
                                    "Fewer than ten headlines or three same-theme assets is not automatically defective.")
        dup.observe("Literal duplicate groups", count=dups)

    # -- step 5: performance labels and dated history -------------------------------------------
    _labels(ctx)

    # -- step 6: routing -------------------------------------------------------------------------
    route = ctx.check("routing", "Route detailed text/image/video checks to specialist skills",
                      {**base, INV: ["campaign_id", "group_id", "group_type"],
                       ASSETS: ["group_id", "association_id", "asset_type", "field_role", "linked_status"]})
    if route.runnable:
        G6 = Groups(ctx, route)
        channels = {_id(r.get("id")): str(r.get("channel_type") or "").upper() for r in ctx.rows("campaigns")}
        routes: dict[str, set] = {}
        for gid, g in sorted(G6.groups.items()):
            ch = channels.get(_id(g.get("campaign_id")), "")
            for a in G6.usable(gid):
                t = V.norm_text(a.get("asset_type")) + " " + V.norm_text(a.get("field_role"))
                if ch == "SEARCH" and "headline" in t:
                    routes.setdefault("skill-025-rsa-headline-diversity-completeness", set()).add(gid)
                elif ch == "SEARCH" and "description" in t:
                    routes.setdefault("skill-026-rsa-description-optimization", set()).add(gid)
                elif "image" in t or "logo" in t:
                    routes.setdefault("skill-035-image-asset-optimization", set()).add(gid)
                elif "video" in t or "youtube" in t:
                    key = "skill-093-pmax-video-asset-review" if ch == "PERFORMANCE_MAX" else "skill-036-video-asset-presence"
                    routes.setdefault(key, set()).add(gid)
        route.observe("Specialist routing (request-only creative test briefs; no count quotas or uplift forecasts)",
                      routes={k: sorted(v) for k, v in sorted(routes.items())})


def _specs(ctx, spec, G: Groups) -> None:
    complete = _complete(ctx, INV, ASSETS)
    text_ok = "text" in (ctx.table(ASSETS).columns if ctx.table(ASSETS) else [])
    if not text_ok:
        spec.partial("mandatory message review skipped", [f"{ASSETS}:text"])
    unknown_measure = 0
    reqs = sorted(ctx.rows(REQ), key=lambda r: (_id(r.get("requirement_id")), V.norm_text(r.get("subtype"))))
    for req in reqs:
        rid, kind = _id(req.get("requirement_id")), V.norm_text(req.get("required_or_recommended"))
        fmt = V.norm_text(req.get("format"))
        bounds = _parse_spec(req.get("supported_asset_spec"))
        src = {"requirement_id": rid, "required_or_recommended": req.get("required_or_recommended"),
               "supported_asset_spec": req.get("supported_asset_spec"), "official_source_url": req.get("official_source_url"),
               "checked_at": req.get("checked_at"), "evidence_ref": req.get("evidence_ref"), "owner": req.get("owner")}
        if kind not in ("required", "recommended"):
            spec.partial(f"requirement {rid}: required_or_recommended '{req.get('required_or_recommended')}' unknown")
            continue
        required = kind == "required"
        groups = [gid for gid, g in sorted(G.groups.items())
                  if V.norm_text(g.get("subtype")) == V.norm_text(req.get("subtype"))
                  and V.norm_text(g.get("status")) not in _GROUP_OFF]
        for gid in groups:
            g = G.groups[gid]
            entity = {"campaign_id": _id(g.get("campaign_id")), "group_id": gid, "requirement_id": rid}
            matching = [a for a in G.usable(gid)
                        if fmt and fmt in (V.norm_text(a.get("asset_type")), V.norm_text(a.get("field_role")))]
            if req.get("mandatory_message") or req.get("brand_rule"):
                if text_ok:
                    texts = [a for a in G.usable(gid) if _id(a.get("text"))]
                    msg = _norm_literal(req.get("mandatory_message"))
                    if texts:
                        spec.review("message_constraint", entity,
                                    f"Do group {gid}'s texts conflict with the approved message constraint of {rid}?",
                                    evidence={**src, "mandatory_message": req.get("mandatory_message"),
                                              "brand_rule": req.get("brand_rule"),
                                              "texts": [{"association_id": a.get("association_id"), "text": a.get("text"),
                                                         "literal_contains_message": bool(msg) and msg in _norm_literal(a.get("text"))}
                                                        for a in texts]},
                                    outcomes={"conflict": {"severity": "Warning", "recommendation":
                                                           "Correct the conflicting asset per the approved brief owner."},
                                              "compliant": {"severity": None, "recommendation": "No change."},
                                              "uncertain": {"severity": "Info", "recommendation": "Ask the brief owner."}},
                                    guidance="Literal containment is a hint, not proof; judge against the approved wording.")
            if not fmt:
                continue
            if not matching:
                if not complete:
                    spec.partial(f"group {gid}: no '{fmt}' association seen; completeness not certified")
                    continue
                if required:
                    prov = spec.finding("required_format_missing", "Warning", entity,
                                        f"Group {gid} has no linked '{fmt}' asset required by {rid}",
                                        evidence={**src, "subtype": g.get("subtype"), "format": fmt},
                                        recommendation="Add a compliant asset per the documented requirement; verify the source is current.",
                                        uncertainty="Requirement validity depends on checked_at and the cited source.")
                    spec.review("required_format_missing", entity,
                                f"Does the missing required '{fmt}' asset materially block intended eligible delivery of group {gid}?",
                                evidence={**src, "eligibility_status": g.get("eligibility_status"), "status": g.get("status")},
                                outcomes={_BLOCK: {"severity": "Critical", "recommendation":
                                                   "Prioritize the required asset; cite the eligibility evidence."},
                                          "not_evidenced": {"severity": None, "recommendation": "Keep as Warning."}},
                                guidance=f"'{_BLOCK}' needs proposal.evidence_ref to supplied eligibility/delivery evidence.")
                else:
                    spec.finding("recommended_format_missing", "Info", entity,
                                 f"Group {gid} has no '{fmt}' asset recommended by {rid}",
                                 evidence={**src, "subtype": g.get("subtype"), "format": fmt},
                                 recommendation="Optional: consider a brief-backed asset; not mandatory.",
                                 uncertainty="Recommended coverage is not a defect or uplift promise.")
                continue
            if bounds is None:
                if required:
                    spec.review("required_spec_ambiguous", entity,
                                f"Do group {gid}'s '{fmt}' assets conflict with required spec '{req.get('supported_asset_spec')}'?",
                                evidence={**src, "assets": [{k: a.get(k) for k in ("association_id", "width", "height",
                                                                                   "duration_seconds")} for a in matching]},
                                outcomes={"conflict": {"severity": "Warning", "recommendation":
                                                       "Replace/resize the non-conforming asset per the cited source."},
                                          "conforms": {"severity": None, "recommendation": "No change."},
                                          "uncertain": {"severity": "Info", "recommendation": "Request a numeric spec."}},
                                guidance="Use only the cited official source and checked_at; do not infer universal formats.")
                else:
                    spec.partial(f"recommended requirement {rid}: spec not machine-readable")
                continue
            for a in matching:
                aid = _id(a.get("association_id"))
                breaches = []
                for field, op, bound in bounds:
                    v = V.num(a.get(field))
                    if v is None:
                        unknown_measure += 1
                        continue
                    if _violates(v, op, bound):
                        breaches.append({"field": field, "observed": v, "rule": f"{op} {bound:g}"})
                if breaches:
                    spec.finding("required_spec_conflict" if required else "recommended_spec_gap",
                                 "Warning" if required else "Info", {**entity, "association_id": aid},
                                 f"Association {aid} ({fmt}) breaches {kind} spec {rid}: "
                                 + "; ".join(f"{b['field']} {b['observed']:g} not {b['rule']}" for b in breaches),
                                 evidence={**src, "breaches": breaches, "asset_id": a.get("asset_id")},
                                 recommendation="Replace with a conforming asset per the cited source." if required
                                 else "Optional improvement toward the recommended spec.",
                                 uncertainty="Spec source currency depends on checked_at.")
    if unknown_measure:
        spec.partial(f"{unknown_measure} spec bound checks with unknown measured width/height/duration")


def _labels(ctx) -> None:
    lab = ctx.check("performance_labels", "Contextual performance labels and dated Low-label history",
                    {"campaigns": ["id", "channel_type"], INV: ["campaign_id", "group_id"],
                     ASSETS: ["group_id", "association_id", "linked_status", "performance_label", "label_date"]})
    if not lab.runnable:
        return
    G = Groups(ctx, lab)
    in_scope = {_id(a.get("association_id")): gid for gid in G.groups for a in G.assoc[gid]}
    low_now = sorted(a for gid in G.groups for a in (_id(x.get("association_id")) for x in G.assoc[gid]
                     if V.norm_text(x.get("performance_label")) == "low"))
    lab.observe("Snapshot Low labels (contextual, not causal ranks; a snapshot proves no duration)",
                associations=low_now)
    hist_t = ctx.table(HIST)
    need = ["association_id", "observed_at", "label", "reporting_context"]
    missing = [f"{HIST} (file)"] if hist_t is None else [f"{HIST}:{c}" for c in hist_t.missing(need)]
    if missing:
        lab.partial("persistent-label claims need dated history", missing)
        return
    gate = ctx.params.get("min_impressions")
    by: dict[str, list] = {}
    undated = 0
    for r in hist_t.rows:
        aid = _id(r.get("association_id"))
        d = V.parse_date(r.get("observed_at"))
        if aid not in in_scope:
            continue
        if d is None:
            undated += 1
            continue
        by.setdefault(aid, []).append((d, r))
    if undated:
        lab.partial(f"{undated} history rows without a parseable observed_at ignored")
    for aid in sorted(by):
        rows = sorted(by[aid], key=lambda x: x[0])
        streak = []
        for d, r in reversed(rows):
            if V.norm_text(r.get("label")) != "low":
                break
            streak.append((d, r))
        streak.reverse()
        if len(streak) < 2 or len({d for d, _ in streak}) < 2:
            continue
        contexts = sorted({V.norm_text(r.get("reporting_context")) for _, r in streak})
        if len(contexts) != 1 or not contexts[0]:
            lab.observe(f"Association {aid}: Low streak spans mixed/unknown reporting contexts; no persistence claim",
                        association_id=aid, contexts=contexts)
            continue
        impr = [V.num(r.get("impressions")) for _, r in streak]
        total = sum(i for i in impr if i is not None) if all(i is not None for i in impr) else None
        first, last = streak[0][0], streak[-1][0]
        lab.finding("persistent_low_label", "Info", {"group_id": in_scope[aid], "association_id": aid},
                    f"Association {aid} labelled Low in {len(streak)} dated observations {first}..{last} "
                    f"({(last - first).days} days, context {contexts[0]})",
                    evidence={"first_observed": first, "last_observed": last, "span_days": (last - first).days,
                              "observations": len(streak), "reporting_context": contexts[0], "impressions": total,
                              "min_impressions": gate.value, "sample_gate_met": (total >= gate.value)
                              if total is not None and gate.value is not None else None},
                    recommendation="Low labels alone do not justify replacement; propose a brief-backed creative test "
                                   "with hypothesis, owner and outcome metric.",
                    uncertainty="Labels are contextual and relative, not causal ranks.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'material_block_evidenced' (Critical) requires proposal.evidence_ref."""
    if decision.get("outcome") == _BLOCK and not str((decision.get("proposal") or {}).get("evidence_ref") or "").strip():
        return ["material delivery block needs proposal.evidence_ref pointing at supplied eligibility/delivery evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
