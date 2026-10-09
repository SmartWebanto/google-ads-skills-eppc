"""check.py — skill-028 deterministic RSA slot maps, pin alternatives and mandatory-message guarantees.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-028-rsa-pinning-strategy-audit/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Pins come only from explicit per-asset keys (pinned_field|pinned_position|pin) in JSON arrays or a
         pinned_positions cell of 'none'/'unpinned' or a JSON {headlines:[...], descriptions:[...]} aligned by
         index; an absent/empty pin source is UNKNOWN (partial), never 'unpinned'.
         Several assets pinned to one position are alternatives, not conflicts; pin counts are observations only.
         Guaranteed positions are HEADLINE_1, HEADLINE_2, DESCRIPTION_1; HEADLINE_3/DESCRIPTION_2 are optional.
         A must_always_show requirement is guaranteed only if EVERY feasible guaranteed-slot assignment shows a
         matching asset in an allowed guaranteed position (exhaustive, no asset reused across slots).
         Matching is literal (NFKC + casefold + collapsed whitespace containment). Literal evidence present but
         not guaranteed → deterministic Warning (constraint file = owner confirmation). No literal match anywhere
         → ai_review (paraphrase may satisfy); verify demands the slot and every alternative in it.
         Assignment counts are theoretical upper bounds, never impressions or tested combinations.
         Pinned/unpinned performance is observational only, both cohorts gated and ctx.mature True.
related: skills/skill-025-rsa-headline-diversity-completeness/scripts/check.py — same private RSA array parser
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

SKILL = "skill-028-rsa-pinning-strategy-audit"
VERSION = "1.0.0"

H_POS = ("HEADLINE_1", "HEADLINE_2", "HEADLINE_3")
D_POS = ("DESCRIPTION_1", "DESCRIPTION_2")
GUARANTEED = ("HEADLINE_1", "HEADLINE_2", "DESCRIPTION_1")
_PIN_ALIASES = {"H1": "HEADLINE_1", "H2": "HEADLINE_2", "H3": "HEADLINE_3", "D1": "DESCRIPTION_1",
                "D2": "DESCRIPTION_2"}
_UNPINNED = ("", "NONE", "UNPINNED", "UNSPECIFIED", "NULL")
_PIN_KEYS = ("pinned_field", "pinned_position", "pin")
_UNKNOWN = "UNKNOWN"
ADS_NEEDS = {"ads": ["id", "campaign_id", "ad_group_id", "type", "status", "headlines", "descriptions"]}
CONSTRAINT_COLS = ["ad_id", "requirement_id", "text_or_semantic_requirement", "allowed_positions",
                   "must_always_show", "valid_from", "valid_to"]


def _norm(v) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(v or "")).casefold().split())


def _pin(raw, field_positions) -> str | None:
    """Normalize one explicit pin value → position, None (unpinned) or UNKNOWN (unsupported value)."""
    s = str(raw or "").strip().upper()
    if s in _UNPINNED:
        return None
    s = _PIN_ALIASES.get(s, s)
    return s if s in field_positions else _UNKNOWN


def _parse_field(cell, pins_cell, field: str, positions) -> tuple[list[dict] | None, str]:
    """RSA array → ([{index, text, pin}], pin_state) with pin_state known|unknown; None when text unusable.

    Rules:   pin UNKNOWN marks an unsupported supplied value; pin_state 'unknown' means no pin source at all.
    """
    if cell is None:
        return None, "unknown"
    items, has_key = [], False
    text = cell if isinstance(cell, list) else str(cell).strip()
    parsed = None
    if isinstance(text, list):
        parsed = text
    elif text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            return None, "unknown"
    if parsed is not None:
        for i, e in enumerate(parsed):
            if isinstance(e, dict):
                key = next((k for k in _PIN_KEYS if k in e), None)
                has_key = has_key or key is not None
                items.append({"index": i, "text": e.get("text"),
                              "pin": _pin(e.get(key), positions) if key else _UNKNOWN, "keyed": key is not None})
            else:
                items.append({"index": i, "text": e, "pin": _UNKNOWN, "keyed": False})
    else:
        items = [{"index": i, "text": t, "pin": _UNKNOWN, "keyed": False}
                 for i, t in enumerate(V.split_list(text, (" | ", "|", "\n")))]
    if parsed is not None and has_key and all(x["keyed"] for x in items):
        return items, "known"
    # fall back to an explicit pinned_positions cell
    pc = str(pins_cell or "").strip()
    if pc.upper() in ("NONE", "UNPINNED", "NO PINS"):
        for x in items:
            x["pin"] = None
        return items, "known"
    if pc.startswith("{"):
        try:
            spec = json.loads(pc)
        except ValueError:
            spec = None
        arr = spec.get(field) if isinstance(spec, dict) else None
        if isinstance(arr, list) and len(arr) == len(items):
            for x, p in zip(items, arr):
                x["pin"] = _pin(p, positions)
            return items, "known"
    return items, "unknown"


def _candidates(assets: list[dict], pos: str) -> list[dict]:
    pinned = [a for a in assets if a["pin"] == pos]
    return pinned if pinned else [a for a in assets if a["pin"] is None]


def _assignments(assets: list[dict], positions, optional=()) -> list[tuple]:
    """All injective slot fillings (index or None). Rules: optional positions may stay empty (shorter render)."""
    out: list[tuple] = []

    def rec(i, used, acc):
        if i == len(positions):
            out.append(tuple(acc))
            return
        pos = positions[i]
        cands = [a for a in _candidates(assets, pos) if a["index"] not in used]
        for a in cands:
            rec(i + 1, used | {a["index"]}, acc + [a["index"]])
        if pos in optional or not cands:
            rec(i + 1, used, acc + [None])

    rec(0, frozenset(), [])
    return out


def _counts(assets: list[dict], positions) -> dict:
    """Theoretical counts: full renderings and renderings with every guaranteed position filled."""
    optional = [p for p in positions if p not in GUARANTEED]
    rows = _assignments(assets, positions, optional)
    guaranteed_idx = [i for i, p in enumerate(positions) if p in GUARANTEED]
    return {"full": sum(1 for t in rows if None not in t),
            "guaranteed_filled": sum(1 for t in rows if all(t[i] is not None for i in guaranteed_idx))}


def _allowed(raw) -> tuple[set[str], list[str]]:
    s = str(raw or "").strip()
    if not s or s.lower() in ("any", "all"):
        return set(H_POS + D_POS), []
    out, bad = set(), []
    for p in V.split_list(s, (";", "|", ",")):
        q = _PIN_ALIASES.get(p.strip().upper(), p.strip().upper())
        (out.add(q) if q in H_POS + D_POS else bad.append(p))
    return out, bad


def _load_ads(ctx) -> list[dict]:
    out = []
    for r in sorted(ctx.rows("ads"), key=lambda r: str(r.get("id"))):
        if str(r.get("type") or "").upper() != "RESPONSIVE_SEARCH_AD":
            continue
        h, hs = _parse_field(r.get("headlines"), r.get("pinned_positions"), "headlines", H_POS)
        d, ds = _parse_field(r.get("descriptions"), r.get("pinned_positions"), "descriptions", D_POS)
        out.append({"row": r, "id": str(r.get("id")), "campaign_id": str(r.get("campaign_id") or ""),
                    "ad_group_id": str(r.get("ad_group_id") or ""), "h": h, "d": d,
                    "pins_known": hs == "known" and ds == "known" and h is not None and d is not None})
    return out


def _slot_map(ad) -> dict:
    return {pos: [a["index"] for a in _candidates(ad["h"] if pos.startswith("H") else ad["d"], pos)]
            for pos in H_POS + D_POS}


def _guarantee(ad, needle: str, allowed: set[str]) -> dict:
    """Exhaustive check over guaranteed-slot assignments. Returns guaranteed flag and a counterexample."""
    match = lambda assets, idx: idx is not None and needle in _norm(assets[idx]["text"])
    res = {}
    for field, assets, positions in (("headlines", ad["h"], ("HEADLINE_1", "HEADLINE_2")),
                                     ("descriptions", ad["d"], ("DESCRIPTION_1",))):
        by_index = {a["index"]: a for a in assets}
        g_allowed = [p for p in positions if p in allowed]
        miss = None
        for t in _assignments(assets, positions):
            if not any(match(by_index, t[positions.index(p)]) for p in g_allowed):
                miss = {p: (by_index[i]["text"] if i is not None else None) for p, i in zip(positions, t)}
                break
        res[field] = miss
    guaranteed = res["headlines"] is None or res["descriptions"] is None
    return {"guaranteed": guaranteed, "counterexample": None if guaranteed else {**res["headlines"], **res["descriptions"]}}


def run(ctx) -> None:
    """Run RSA slot maps, pin alternatives, guaranteed-slot assignment and mandatory-message checks.

    Rules:   Absent/empty pin source → partial (UNKNOWN), unsupported pin value → Info; pin counts are never findings.
             must_always_show with literal evidence but not guaranteed in every feasible assignment → deterministic
             Warning; no literal match anywhere → Info + ai_review (paraphrase may satisfy). Pinned/unpinned performance
             is observation only, both cohorts gated (min_impressions/min_clicks) and ctx.mature True.
    """
    slots = ctx.check("slot_maps", "Headline/description slot maps and explicit pin values", ADS_NEEDS)
    ids = ("alternatives", "assignments", "short_renderings", "mandatory_messages", "gap_classification",
           "flexibility", "pinned_performance")
    titles = ("Pinned alternatives per position", "Structurally eligible assignment upper bound",
              "Shorter renderings and optional positions", "Must-always-show requirement guarantees",
              "Mandatory message gaps vs exporter ambiguity", "Flexibility with constraints held fixed",
              "Observational pinned vs unpinned outcomes")
    if not slots.runnable:
        for cid, title in zip(ids, titles):
            ctx.check(cid, title).skip("RSA inventory unavailable", slots.missing)
        return
    ads = _load_ads(ctx)
    unknown_pin_ads = []
    for ad in ads:
        if ad["h"] is None or ad["d"] is None:
            slots.partial(f"ad {ad['id']}: headline/description array unreadable", ["ads:headlines", "ads:descriptions"])
            continue
        if not ad["pins_known"]:
            unknown_pin_ads.append(ad["id"])
            continue
        bad = [(f, a["index"]) for f, arr in (("headline", ad["h"]), ("description", ad["d"]))
               for a in arr if a["pin"] == _UNKNOWN]
        if bad:
            slots.finding("unknown_pin_value", "Info",
                          {"campaign_id": ad["campaign_id"], "ad_group_id": ad["ad_group_id"], "ad_id": ad["id"]},
                          f"Ad {ad['id']} has {len(bad)} unsupported pin value(s); slot map needs verification",
                          evidence={"assets": [{"field": f, "index": i} for f, i in bad],
                                    "supported": list(H_POS + D_POS)},
                          recommendation="Verify the exporter pin field before any pinning decision.",
                          uncertainty="Exporter ambiguity, not a confirmed configuration gap.")
            ad["pins_known"] = False
            unknown_pin_ads.append(ad["id"])
            continue
        slots.observe(f"Ad {ad['id']} slot map", ad_id=ad["id"], status=ad["row"].get("status"),
                      headlines=len(ad["h"]), descriptions=len(ad["d"]), slot_map=_slot_map(ad))
    if unknown_pin_ads:
        slots.partial(f"pin values unknown for ads {sorted(set(unknown_pin_ads))}: missing pins are not 'unpinned'",
                      ["ads:pinned_positions"])
    known = [a for a in ads if a["pins_known"]]

    alt = ctx.check("alternatives", "Pinned alternatives per position", ADS_NEEDS)
    for ad in known:
        multi = {p: len(i) for p, i in _slot_map(ad).items()
                 if len([a for a in (ad["h"] if p.startswith("H") else ad["d"]) if a["pin"] == p]) > 1}
        pinned = sum(1 for a in ad["h"] + ad["d"] if a["pin"])
        alt.observe(f"Ad {ad['id']} pinned alternatives", ad_id=ad["id"], pinned_assets=pinned,
                    total_assets=len(ad["h"]) + len(ad["d"]), positions_with_several_alternatives=multi,
                    note="several alternatives in one position are valid rotation, not a conflict")
    if not known:
        alt.partial("no ad with known pins")

    asg = ctx.check("assignments", "Structurally eligible assignment upper bound", ADS_NEEDS)
    for ad in known:
        hc, dc = _counts(ad["h"], H_POS), _counts(ad["d"], D_POS)
        asg.observe(f"Ad {ad['id']} theoretical assignment counts", ad_id=ad["id"],
                    headline_full=hc["full"], headline_guaranteed_filled=hc["guaranteed_filled"],
                    description_full=dc["full"], description_guaranteed_filled=dc["guaranteed_filled"],
                    upper_bound_product=hc["guaranteed_filled"] * dc["guaranteed_filled"],
                    note="theoretical upper bound; not impressions, equal probabilities or tested combinations")
    if not known:
        asg.partial("no ad with known pins")

    short = ctx.check("short_renderings", "Shorter renderings and optional positions", ADS_NEEDS)
    for ad in known:
        empty = [p for p in GUARANTEED if not _candidates(ad["h"] if p.startswith("H") else ad["d"], p)]
        optional_only = [a["index"] for a in ad["h"] + ad["d"] if a["pin"] in ("HEADLINE_3", "DESCRIPTION_2")]
        short.observe(f"Ad {ad['id']} guaranteed vs optional positions", ad_id=ad["id"],
                      guaranteed_positions=list(GUARANTEED), unfillable_guaranteed_positions=empty,
                      assets_pinned_to_optional_positions=optional_only)
    if not known:
        short.partial("no ad with known pins")

    req = ctx.check("mandatory_messages", "Must-always-show requirement guarantees",
                    {**ADS_NEEDS, "external/rsa_message_constraints": CONSTRAINT_COLS})
    gap = ctx.check("gap_classification", "Mandatory message gaps vs exporter ambiguity",
                    {**ADS_NEEDS, "external/rsa_message_constraints": CONSTRAINT_COLS})
    flex = ctx.check("flexibility", "Flexibility with constraints held fixed",
                     {**ADS_NEEDS, "external/rsa_message_constraints": CONSTRAINT_COLS})
    results: dict[str, list] = {}
    if req.runnable:
        ref = ctx.snapshot or ctx.as_of
        by_id = {a["id"]: a for a in ads}
        classes: dict[str, int] = {}
        for c in sorted(ctx.rows("external/rsa_message_constraints"),
                        key=lambda r: (str(r.get("ad_id")), str(r.get("requirement_id")))):
            rid = str(c.get("requirement_id") or "")
            if V.boolean(c.get("must_always_show")) is not True:
                req.observe(f"Requirement {rid}: not must-always-show; no guarantee evaluated", requirement_id=rid)
                continue
            vf, vt = V.parse_date(c.get("valid_from")), V.parse_date(c.get("valid_to"))
            if ref is None or (vf and vf > ref) or (vt and vt < ref):
                req.observe(f"Requirement {rid}: not valid at snapshot {ref}", requirement_id=rid,
                            valid_from=vf, valid_to=vt)
                continue
            if c.get("ad_id"):
                targets = [by_id[str(c["ad_id"])]] if str(c["ad_id"]) in by_id else []
                if not targets:
                    req.partial(f"requirement {rid}: ad {c['ad_id']} not in RSA inventory")
            else:
                targets = [a for a in ads if (not c.get("ad_group_id") or a["ad_group_id"] == str(c["ad_group_id"]))
                           and (not c.get("campaign_id") or a["campaign_id"] == str(c["campaign_id"]))]
            allowed, bad = _allowed(c.get("allowed_positions"))
            if bad:
                req.partial(f"requirement {rid}: unsupported allowed_positions {bad}")
            needle = _norm(c.get("text_or_semantic_requirement"))
            for ad in targets:
                if c.get("campaign_id") and ad["campaign_id"] != str(c["campaign_id"]) or \
                        c.get("ad_group_id") and ad["ad_group_id"] != str(c["ad_group_id"]):
                    req.partial(f"requirement {rid}: ad {ad['id']} parent IDs differ from the constraint row")
                    continue
                entity = {"campaign_id": ad["campaign_id"], "ad_group_id": ad["ad_group_id"], "ad_id": ad["id"],
                          "requirement_id": rid}
                base_ev = {"requirement": c.get("text_or_semantic_requirement"),
                           "allowed_positions": sorted(allowed), "approver_role": c.get("approver_role"),
                           "rationale": c.get("rationale"), "source_ref": c.get("source_ref"),
                           "valid_from": vf, "valid_to": vt, "snapshot": ref}
                if not ad["pins_known"]:
                    classes["exporter_ambiguity"] = classes.get("exporter_ambiguity", 0) + 1
                    results.setdefault(ad["id"], []).append((rid, "exporter_ambiguity"))
                    req.partial(f"requirement {rid} on ad {ad['id']}: pin values unknown; guarantee undecidable")
                    continue
                g_allowed = [p for p in GUARANTEED if p in allowed]
                matches = [{"field": f, "index": a["index"], "text": a["text"], "pin": a["pin"]}
                           for f, arr in (("headline", ad["h"]), ("description", ad["d"]))
                           for a in arr if needle and needle in _norm(a["text"])]
                sm = _slot_map(ad)
                ev = {**base_ev, "guaranteed_allowed_positions": g_allowed, "matching_assets": matches,
                      "slot_candidates": {p: sm[p] for p in g_allowed}}
                if not matches:
                    classes["semantic_unresolved"] = classes.get("semantic_unresolved", 0) + 1
                    results.setdefault(ad["id"], []).append((rid, "semantic_unresolved"))
                    prov = req.finding("required_message_literal_absent", "Info", entity,
                                       f"Requirement {rid} text not found literally in any asset of ad {ad['id']}",
                                       evidence=ev, recommendation="Confirm whether an equivalent wording satisfies it.",
                                       uncertainty="Literal matching cannot recognize paraphrases.")
                    req.review("required_message_not_guaranteed", entity,
                               f"Does every alternative in one guaranteed allowed slot of ad {ad['id']} express "
                               f"requirement {rid} ('{c.get('text_or_semantic_requirement')}')?",
                               evidence={**ev, "headlines": ad["h"], "descriptions": ad["d"]},
                               outcomes={"not_guaranteed": {"severity": "Warning", "recommendation":
                                                            "Owner review: pin compliant alternatives to a guaranteed slot."},
                                         "guaranteed_by_equivalent_text": {"severity": None, "recommendation":
                                                                           "No change; document the equivalence."},
                                         "uncertain": {"severity": "Info", "recommendation":
                                                       "Ask the approver whether paraphrases satisfy the requirement."}},
                               guidance="guaranteed_by_equivalent_text needs proposal {slot, alternatives: [every "
                                        "candidate index of that slot]}; no legal certification is implied.",
                               provisional=prov)
                    continue
                g = _guarantee(ad, needle, allowed)
                if g["guaranteed"]:
                    classes["guaranteed"] = classes.get("guaranteed", 0) + 1
                    results.setdefault(ad["id"], []).append((rid, "guaranteed"))
                    req.observe(f"Requirement {rid} guaranteed on ad {ad['id']}", **entity,
                                guaranteed_allowed_positions=g_allowed, matching_assets=matches)
                    continue
                classes["confirmed_gap"] = classes.get("confirmed_gap", 0) + 1
                results.setdefault(ad["id"], []).append((rid, "confirmed_gap"))
                incompatible = sorted({v for v in g["counterexample"].values() if v})
                req.finding("required_message_not_guaranteed", "Warning", entity,
                            f"Must-always-show requirement {rid} ('{c.get('text_or_semantic_requirement')}') is not "
                            f"guaranteed on ad {ad['id']}: matching assets sit only in optional or non-allowed "
                            f"positions or share a slot with non-matching alternatives",
                            evidence={**ev, "counterexample_guaranteed_rendering": g["counterexample"],
                                      "incompatible_alternatives": incompatible},
                            calculation={"method": "exhaustive injective assignment of HEADLINE_1, HEADLINE_2, "
                                                   "DESCRIPTION_1; literal normalized containment"},
                            recommendation="Owner review: pin every alternative of one guaranteed allowed slot to "
                                           "compliant text; keep other pins; route any test to skill-032.",
                            uncertainty="Literal matching; not legal certification. Structural serving rules only.")
        gap.observe("Requirement outcome classes", **classes)
        if not classes:
            gap.observe("No valid must-always-show requirement matched an RSA in scope")
    else:
        gap.skip("constraint evidence unavailable", req.missing)
    if flex.runnable:
        for ad in known:
            hc, dc = _counts(ad["h"], H_POS), _counts(ad["d"], D_POS)
            flex.observe(f"Ad {ad['id']} flexibility with current pins fixed", ad_id=ad["id"],
                         headline_renderings=hc["guaranteed_filled"], description_renderings=dc["guaranteed_filled"],
                         requirement_results=results.get(ad["id"], []),
                         note="no universal pin maximum; multiple H1 alternatives can preserve a requirement")

    perf = ctx.check("pinned_performance", "Observational pinned vs unpinned outcomes",
                     {**ADS_NEEDS, "ad_metrics": ["ad_id", "campaign_id", "ad_group_id", "impressions", "clicks",
                                                  "cost", "conversions"]})
    if perf.runnable:
        if ctx.mature is not True:
            perf.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; descriptive totals only")
        min_imp, min_clk = ctx.params.get("min_impressions"), ctx.params.get("min_clicks")
        pinned = {a["id"]: any(x["pin"] for x in a["h"] + a["d"]) for a in known}
        groups: dict[tuple, dict] = {}
        seen = set()
        for m in sorted(ctx.rows("ad_metrics"), key=lambda r: str(r.get("ad_id"))):
            aid = str(m.get("ad_id"))
            if aid not in pinned:
                continue
            if aid in seen:
                perf.partial(f"duplicate ad_metrics rows for ad {aid}; excluded to avoid fan-out")
                continue
            seen.add(aid)
            vals = [V.num(m.get(col)) for col in ("impressions", "clicks", "conversions")]
            if None in vals:
                perf.partial(f"ad {aid}: unknown impressions/clicks/conversions; excluded (unknown is not zero)")
                continue
            key = (str(m.get("campaign_id")), str(m.get("ad_group_id")))
            g = groups.setdefault(key, {True: [0.0, 0.0, 0.0], False: [0.0, 0.0, 0.0]})
            for i, v in enumerate(vals):
                g[pinned[aid]][i] += v
        for key, g in sorted(groups.items()):
            ctr_ok = ctx.mature is True and all(g[k][0] >= min_imp.value for k in (True, False))
            cvr_ok = ctx.mature is True and all(g[k][1] >= min_clk.value for k in (True, False))
            perf.observe(f"Ad group {key[1]} pinned vs unpinned cohorts", campaign_id=key[0], ad_group_id=key[1],
                         pinned=dict(zip(("impressions", "clicks", "conversions"), g[True])),
                         unpinned=dict(zip(("impressions", "clicks", "conversions"), g[False])),
                         pinned_ctr=V.ratio(g[True][1], g[True][0]) if ctr_ok else None,
                         unpinned_ctr=V.ratio(g[False][1], g[False][0]) if ctr_ok else None,
                         pinned_cvr=V.ratio(g[True][2], g[True][1]) if cvr_ok else None,
                         unpinned_cvr=V.ratio(g[False][2], g[False][1]) if cvr_ok else None,
                         min_impressions=min_imp.value, min_clicks=min_clk.value,
                         ctr_comparable=ctr_ok, cvr_comparable=cvr_ok,
                         note="observational only; a pinning-change experiment belongs to skill-032")


def verify(ctx, item, decision) -> list[str]:
    """Rules: equivalent-text guarantees must name a guaranteed allowed slot and cover every alternative in it."""
    if decision.get("outcome") != "guaranteed_by_equivalent_text":
        return []
    p = decision.get("proposal") or {}
    slot = str(p.get("slot") or "").upper()
    slots = item.evidence.get("slot_candidates") or {}
    if slot not in slots:
        return [f"proposal.slot must be one of the guaranteed allowed positions {sorted(slots)}"]
    need = set(slots[slot])
    got = {V.integer(i) for i in p.get("alternatives") or []}
    if not need:
        return [f"{slot} has no renderable alternative"]
    if got != need:
        return [f"proposal.alternatives must list every candidate index of {slot}: {sorted(need)}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
