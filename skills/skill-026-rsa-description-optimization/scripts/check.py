"""check.py — skill-026 deterministic RSA description inventory, duplicates and field-limit validity.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-026-rsa-description-optimization/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #10 / #11 Ad Copy Length Analysis (Brainlabs) — REFUSED as scoring: the recipe rejects length-based
         quality scores and optimum lengths; only descriptive display-width counts are reported
         skills/skill-025-rsa-headline-diversity-completeness/scripts/check.py — same private normalization/width helpers
rules:   Duplicate matching: NFKC + casefold + collapsed whitespace; negations, prices and dates are never stripped.
         Character counts are descriptive only: no 80-90 optimum, no minimum length, no 'fill all four' rule.
         An empty optional slot (< RSA_LIMITS descriptions_max) is Info; short copy is never a finding.
         Limits (RSA_LIMITS: 2..4 descriptions, 90 display columns, East-Asian wide chars count 2) may be
         replaced by profile.rsa_limits; exported over-limit text is an exporter/draft question → partial.
         Findings only for active RSAs (ad, ad group, campaign ENABLED or parent unknown).
         Coherence, contradictory promises and omitted business-required qualifications (profile
         required_qualifications, intended_offer, product_service_taxonomy) are ai_review; the Warning outcome
         needs proposal.evidence_ref. Proposed alternative descriptions need claim_source, must fit the width
         and must not duplicate existing descriptions after normalization.
         ad_metrics prioritizes review order only; it never attributes performance to one description.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import json
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

SKILL = "skill-026-rsa-description-optimization"
VERSION = "1.0.0"

RSA_LIMITS = {"descriptions_min": 2, "descriptions_max": 4, "description_width": 90}  # support.google.com/.../7684791
ADS_NEEDS = {"ads": ["id", "campaign_id", "ad_group_id", "type", "status", "descriptions"]}
_CONTEXT_KEYS = ("objectives", "intended_offer", "product_service_taxonomy", "supported_propositions",
                 "required_qualifications", "brand_terms")


def _norm(v) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(v or "")).casefold().split())


def _width(v) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(v or ""))


def _texts(cell) -> list[str] | None:
    """RSA text array → raw strings (JSON list of str/{text} or ' | ' separated); None when unusable."""
    if cell is None:
        return None
    s = str(cell).strip()
    if s.startswith("["):
        try:
            data = json.loads(s)
        except ValueError:
            return None
        out = [e.get("text") if isinstance(e, dict) else e for e in data]
        return None if any(not isinstance(t, str) for t in out) else out
    return V.split_list(s, (" | ", "|", "\n"))


def _limits(ctx) -> dict:
    lim = dict(RSA_LIMITS)
    for k, v in (ctx.profile.get("rsa_limits") or {}).items():
        if k in lim and V.integer(v):
            lim[k] = V.integer(v)
    return lim


def _entity(ad: dict) -> dict:
    return {"campaign_id": str(ad.get("campaign_id")), "ad_group_id": str(ad.get("ad_group_id")), "ad_id": str(ad.get("id"))}


def run(ctx) -> None:
    """Run RSA description inventory, duplicate wording, empty-slot and coherence review for active RSAs.

    Rules:   Findings only for active RSAs (ad/ad group/campaign ENABLED or parent unknown); character length is never a
             finding. Duplicate wording (NFKC+casefold+whitespace) and empty optional slots are Info; over-limit export
             → partial. Coherence/contradictions/missing qualifications are ai_review whose Warning needs
             proposal.evidence_ref; ad_metrics only orders review, never attributes performance to one description.
    """
    inv = ctx.check("description_inventory", "Description arrays by ad ID and array index", ADS_NEEDS)
    later = (("exact_duplicates", "Normalized exact duplicate descriptions"),
             ("description_counts", "Supplied/unique counts and display widths"),
             ("field_limits", "Field-limit validity vs current RSA format"),
             ("coherence_review", "Description coherence with headlines and pins"),
             ("content_roles", "Benefit/action/proof/qualification content"),
             ("alternative_concepts", "Grounded alternative description concepts"),
             ("prioritization", "Active-scope review priority"))
    if not inv.runnable:
        for cid, title in later:
            ctx.check(cid, title).skip("RSA description inventory unavailable", inv.missing)
        return
    groups = {str(r.get("id")): str(r.get("status") or "").upper() for r in ctx.rows("ad_groups")}
    camps = {str(r.get("id")): str(r.get("status") or "").upper() for r in ctx.rows("campaigns")}
    if not groups or not camps:
        inv.partial("parent status unknown (ad_groups/campaigns missing): active scope uses ad status only",
                    [k for k, v in (("ad_groups (file)", groups), ("campaigns (file)", camps)) if not v])
    rsas = sorted((r for r in ctx.rows("ads") if str(r.get("type") or "").upper() == "RESPONSIVE_SEARCH_AD"),
                  key=lambda r: str(r.get("id")))
    ok = lambda s: s in ("ENABLED", "")
    active = [r for r in rsas if str(r.get("status") or "").upper() == "ENABLED"
              and ok(groups.get(str(r.get("ad_group_id")), "")) and ok(camps.get(str(r.get("campaign_id")), ""))]
    arrays = {str(r.get("id")): _texts(r.get("descriptions")) for r in rsas}
    unreadable = sorted(k for k, v in arrays.items() if v is None)
    by_status: dict[str, int] = {}
    for r in rsas:
        s = str(r.get("status") or "UNKNOWN").upper()
        by_status[s] = by_status.get(s, 0) + 1
    inv.observe("RSA description inventory", rsa_total=len(rsas), by_status=by_status, active=len(active),
                readable_arrays=len(rsas) - len(unreadable))
    if unreadable:
        inv.partial(f"unreadable description arrays for ads {unreadable}", ["ads:descriptions"])

    dup = ctx.check("exact_duplicates", "Normalized exact duplicate descriptions", ADS_NEEDS)
    for r in active:
        descs = arrays[str(r.get("id"))] or []
        by_norm: dict[str, list] = {}
        for i, t in enumerate(descs):
            if _norm(t):
                by_norm.setdefault(_norm(t), []).append({"index": i, "text": t})
        grp = [v for _, v in sorted(by_norm.items()) if len(v) > 1]
        if grp:
            dup.finding("duplicate_description_wording", "Info", _entity(r),
                        f"Ad {r.get('id')} repeats {len(grp)} description text(s) after normalization",
                        evidence={"groups": grp, "supplied": len(descs)},
                        calculation={"normalization": "NFKC, casefold, collapsed whitespace; nothing stripped"},
                        recommendation="Replace a repeat with a distinct grounded message if one exists.",
                        uncertainty="Near-duplicate paraphrases remain analyst judgments.")
    dup.observe("Active RSAs checked for duplicate descriptions", active=len(active))

    lim = _limits(ctx)
    cnt = ctx.check("description_counts", "Supplied/unique counts and display widths", ADS_NEEDS)
    val = ctx.check("field_limits", "Field-limit validity vs current RSA format", ADS_NEEDS)
    invalid = []
    for r in active:
        descs = arrays[str(r.get("id"))]
        if descs is None:
            continue
        widths = [_width(t) for t in descs]
        uniq = len({_norm(t) for t in descs if _norm(t)})
        cnt.observe(f"Ad {r.get('id')} description counts", ad_id=str(r.get("id")), supplied=len(descs),
                    unique=uniq, display_widths=widths,
                    note="descriptive only; no optimum or minimum length applies")
        over = [{"index": i, "width": w} for i, w in enumerate(widths) if w > lim["description_width"]]
        if over or not (lim["descriptions_min"] <= len(descs) <= lim["descriptions_max"]):
            invalid.append({"ad_id": str(r.get("id")), "status": r.get("status"), "supplied": len(descs),
                            "over_width": over})
        elif len(descs) < lim["descriptions_max"]:
            cnt.finding("optional_empty_description_slot", "Info", _entity(r),
                        f"Ad {r.get('id')} fills {len(descs)} of {lim['descriptions_max']} optional description slots",
                        evidence={"supplied": len(descs), "unique": uniq, "limits": lim},
                        recommendation="Optional: add a distinct grounded message only if it serves the intent.",
                        uncertainty="Filling optional capacity is not proven to improve effectiveness.")
    val.observe("Field-limit check", checked=len([r for r in active if arrays[str(r.get("id"))] is not None]),
                outside_limits=invalid, limits=lim,
                counting_rule="display columns; East-Asian wide/full-width characters count 2")
    if invalid:
        val.partial("exported descriptions outside current limits: verify exporter/draft state; "
                    "missing or odd export text is not proof a live ad violates requirements")
    if unreadable:
        cnt.partial(f"unreadable description arrays for ads {unreadable}", ["ads:descriptions"])
        val.partial(f"unreadable description arrays for ads {unreadable}", ["ads:descriptions"])

    context = {k: ctx.profile.get(k) for k in _CONTEXT_KEYS if ctx.profile.get(k)}
    objectives = ctx.profile.get("campaign_objectives") or {}
    coh = ctx.check("coherence_review", "Description coherence with headlines and pins",
                    {"ads": ADS_NEEDS["ads"] + ["headlines"]})
    if coh.runnable:
        if not context:
            coh.partial("profile business context missing: claims unverifiable", ["profile:intended_offer",
                                                                                   "profile:required_qualifications"])
        for r in active:
            descs = arrays[str(r.get("id"))]
            if not descs:
                continue
            cid = str(r.get("campaign_id"))
            outcomes = {"coherent": {"severity": None, "recommendation": "No change."},
                        "unverified_claim": {"severity": "Info", "recommendation": "Ask the owner for claim support."},
                        "insufficient_context": {"severity": "Info", "recommendation":
                                                 "Supply language/business context before judging."}}
            if context:
                outcomes["contradiction_or_missing_qualification"] = {
                    "severity": "Warning", "recommendation":
                    "Owner review: fix the contradictory promise or restore the required qualification."}
            coh.review("description_coherence", _entity(r),
                       f"Read ad {r.get('id')} descriptions with its headlines and pins: any contradictory promise, "
                       f"unsupported offer or business-required qualification omitted from valid combinations?",
                       evidence={"descriptions": descs, "headlines": _texts(r.get("headlines")),
                                 "pinned_positions": r.get("pinned_positions"),
                                 "final_url": r.get("final_url") or r.get("final_urls"),
                                 "campaign_objective": next((v for k, v in objectives.items() if str(k) == cid), None)
                                 if isinstance(objectives, dict) else None,
                                 "profile_context": context, "description_width_limit": lim["description_width"]},
                       outcomes=outcomes,
                       guidance="Quote the text. Fragments can be legitimate copy; exact pin guarantees belong to "
                                "skill-028. Warning needs proposal.evidence_ref. Optional alternatives: "
                                "proposal.descriptions + proposal.claim_source; never rewrite legal qualifications "
                                "or invent proof, scarcity or discounts.")

    roles = ctx.check("content_roles", "Benefit/action/proof/qualification content", ADS_NEEDS)
    batch = [{"ad_id": str(r.get("id")), "descriptions": arrays[str(r.get("id"))]} for r in active
             if arrays[str(r.get("id"))]]
    if batch:
        roles.review("description_content_roles", {"batch": "active_rsa_descriptions"},
                     "Tag benefit, action, proof and qualification content in these descriptions with quotations and "
                     "confidence. Is the language/business context sufficient to do so?",
                     evidence={"ads": batch, "profile_context": context, "report_language": ctx.profile.get("report_language")},
                     outcomes={"tagged": {"severity": None, "recommendation": "Use tags in the report; no quota."},
                               "insufficient_language_or_context": {"severity": "Info", "recommendation":
                                                                    "Request language or proposition context."}},
                     guidance="CTAs, full sentences and theme mixes depend on intent; tags are descriptive, not scores.")
    else:
        roles.partial("no readable active RSA descriptions")

    alt = ctx.check("alternative_concepts", "Grounded alternative description concepts", ADS_NEEDS)
    if not context:
        alt.skip("business context missing: no theme recommendations", ["profile:supported_propositions",
                                                                         "profile:intended_offer"])
    else:
        alt.observe("Alternatives are accepted only via coherence_review proposals, verified for width, uniqueness "
                    "and claim_source", context_keys=sorted(context))

    pri = ctx.check("prioritization", "Active-scope review priority",
                    {**ADS_NEEDS, "ad_metrics": ["ad_id", "impressions", "clicks", "cost", "conversions"]})
    if pri.runnable:
        if ctx.mature is not True:
            pri.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; spend order only")
        metrics = {}
        for m in ctx.rows("ad_metrics"):
            aid = str(m.get("ad_id"))
            if aid in metrics:
                pri.partial(f"duplicate ad_metrics rows for ad {aid}; excluded")
                metrics[aid] = None
                continue
            metrics[aid] = m
        order = []
        for r in active:
            m = metrics.get(str(r.get("id")))
            cost = ctx.money(m.get("cost")) if m else None
            order.append({"ad_id": str(r.get("id")), "cost": cost, "clicks": V.num(m.get("clicks")) if m else None})
        order.sort(key=lambda x: (x["cost"] is None, -(x["cost"] or 0), x["ad_id"]))
        pri.observe("Review order by window cost (not description attribution)", order=order,
                    window=[ctx.period_start, ctx.period_end], currency=ctx.currency,
                    effectiveness_tests_owner="skill-032")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning needs proposal.evidence_ref; proposed descriptions need claim_source, width and uniqueness."""
    p = decision.get("proposal") or {}
    problems = []
    if decision.get("outcome") == "contradiction_or_missing_qualification" and not p.get("evidence_ref"):
        problems.append("Warning outcome needs proposal.evidence_ref to supplied evidence")
    descs = p.get("descriptions")
    if descs:
        if not str(p.get("claim_source") or "").strip():
            problems.append("proposed descriptions need proposal.claim_source")
        width = item.evidence.get("description_width_limit") or RSA_LIMITS["description_width"]
        existing = {_norm(t) for t in item.evidence.get("descriptions") or []}
        seen = set()
        for d in descs:
            if not isinstance(d, str) or not d.strip():
                problems.append("proposed descriptions must be non-empty strings")
                continue
            if _width(d) > width:
                problems.append(f"'{d}' exceeds {width} display columns")
            if _norm(d) in existing or _norm(d) in seen:
                problems.append(f"'{d}' duplicates an existing or proposed description")
            seen.add(_norm(d))
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
