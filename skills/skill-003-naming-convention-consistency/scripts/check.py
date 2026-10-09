"""check.py — skill-003 deterministic naming inventory, scoped consistency and verified rename proposals.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-003-naming-convention-consistency/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   The approved convention comes only from profile.naming_convention = {campaign|ad_group: {delimiter,
         fields: [..], allowed: {field: [values]}, exceptions: [entity ids], placeholders: [phrases],
         channel_field, channel_map: {segment: CHANNEL_TYPE}}}. Without it: delimiter/field-count clusters only,
         never compliance failures. Placeholder phrases are profile-supplied, never a hardcoded universal list.
         consistency = conforming / applicable ENABLED entities (documented exceptions excluded); an empty scope is
         undefined (not 100%). < 80% → Info only; paused inventory is reported separately.
         Duplicates: campaigns within account, ad groups within their campaign (same name across campaigns is
         valid); exact vs case/space near-matches kept distinct. Joins by ID; original strings preserved.
         Operational failure (Warning) only via ai_review of external/naming_dependencies rows with an
         observed_failure; verify() requires the row's evidence_ref. name_pattern is a Python regex (re.search).
         verify(): proposed renames must reference listed IDs, conform to the convention and stay unique in scope.
         Label taxonomy is skill-008; renames are never executed.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial deterministic check
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

SKILL = "skill-003-naming-convention-consistency"
VERSION = "1.0.0"

DEP = "external/naming_dependencies"
DEP_COLS = ["consumer_id", "entity_type", "campaign_id", "name_pattern", "expected_behavior", "observed_failure",
            "evidence_ref", "owner", "reviewed_at"]
CONSISTENCY_SCREEN = 0.80
CANDIDATE_DELIMS = (" | ", " - ", " / ", "|", "_", " – ")
TYPES = ("campaign", "ad_group")


def _entities(ctx) -> dict[str, list[dict]]:
    out = {"campaign": [], "ad_group": []}
    for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
        out["campaign"].append({"id": str(c.get("id")), "campaign_id": str(c.get("id")), "name": c.get("name") or "",
                                "status": str(c.get("status") or "").upper(), "channel_type": c.get("channel_type")})
    for g in sorted(ctx.rows("ad_groups"), key=lambda r: str(r.get("id"))):
        out["ad_group"].append({"id": str(g.get("id")), "campaign_id": str(g.get("campaign_id")), "name": g.get("name") or "",
                                "status": str(g.get("status") or "").upper()})
    return out


def _conv(ctx, etype) -> dict | None:
    c = (ctx.profile.get("naming_convention") or {}).get(etype)
    return c if isinstance(c, dict) and c.get("delimiter") and c.get("fields") else None


def conforms(name: str, conv: dict) -> tuple[bool, str]:
    parts = [p.strip() for p in str(name).split(conv["delimiter"])]
    if len(parts) != len(conv["fields"]):
        return False, f"{len(parts)} fields, expected {len(conv['fields'])}"
    allowed = conv.get("allowed") or {}
    for f, v in zip(conv["fields"], parts):
        if not v:
            return False, f"empty field {f}"
        ok = allowed.get(f)
        if ok and v not in [str(x) for x in ok]:
            return False, f"{f}='{v}' not in allowed values"
    return True, ""


def _cluster(name: str) -> str:
    for d in CANDIDATE_DELIMS:
        if d in name:
            return f"'{d}' x{len(name.split(d))}"
    return "no delimiter x1"


def _near(name: str) -> str:
    return " ".join(str(name).lower().split())


def run(ctx) -> None:
    """Run naming inventory, convention parse, consistency, duplicates, placeholders, dependencies, renames.

    Rules:   Without profile.naming_convention: delimiter/field-count clusters + partial only, never compliance
             findings. consistency_below_80 is Info on ENABLED scope only (exceptions excluded; PAUSED observed, never
             flagged); duplicates/near-duplicates, placeholders and channel segments are Info. Warning only via
             ai_review of a naming_dependencies row with observed_failure; rename proposals are ai_review Info, never
             executed.
    """
    # -- steps 1-2: inventory by entity type and status
    inv = ctx.check("inventory", "Campaign/ad-group name inventory by status",
                    {"campaigns": ["id", "name", "status"], "ad_groups": ["id", "campaign_id", "name", "status"]})
    ents = _entities(ctx) if inv.runnable else {}
    if inv.runnable:
        for t in TYPES:
            by: dict[str, int] = {}
            for e in ents[t]:
                by[e["status"] or "UNKNOWN"] = by.get(e["status"] or "UNKNOWN", 0) + 1
            inv.observe(f"{t} inventory by status", entity_type=t, counts=by)
        orphans = sorted(e["id"] for e in ents["ad_group"] if e["campaign_id"] not in {c["id"] for c in ents["campaign"]})
        if orphans:
            inv.partial(f"ad groups whose campaign is absent from inventory: {orphans}")
    else:
        for cid in ("convention_parse", "consistency", "duplicates", "placeholders_segments", "dependencies",
                    "rename_proposals"):
            ctx.check(cid, cid.replace("_", " ")).skip("name inventory unavailable", inv.missing)
        return

    # -- step 3: parse convention or cluster
    parse = ctx.check("convention_parse", "Approved delimiter/fields or inferred clusters")
    convs = {t: _conv(ctx, t) for t in TYPES}
    for t in TYPES:
        if convs[t] is None:
            clusters: dict[str, list[str]] = {}
            for e in ents[t]:
                clusters.setdefault(_cluster(e["name"]), []).append(e["id"])
            parse.observe(f"{t}: inferred delimiter/field-count clusters (no approved convention)", entity_type=t,
                          clusters={k: sorted(v) for k, v in sorted(clusters.items())})
        else:
            parse.observe(f"{t}: approved convention", entity_type=t, **{k: convs[t].get(k) for k in
                                                                         ("delimiter", "fields", "allowed", "exceptions")})
    if not any(convs.values()):
        parse.partial("no approved naming convention: inferred patterns only", ["profile:naming_convention"])

    # -- step 4: scoped consistency
    cons = ctx.check("consistency", "Conforming / applicable entities per type and status")
    nonconforming: list[dict] = []
    for t in TYPES:
        conv = convs[t]
        if conv is None:
            cons.partial(f"{t}: no approved convention, consistency not computed", [f"profile:naming_convention.{t}"])
            continue
        exc = {str(x) for x in conv.get("exceptions") or []}
        for status in ("ENABLED", "PAUSED"):
            scope = [e for e in ents[t] if e["status"] == status and e["id"] not in exc]
            bad = []
            for e in scope:
                ok, why = conforms(e["name"], conv)
                if not ok:
                    bad.append({"entity_type": t, "id": e["id"], "campaign_id": e["campaign_id"], "name": e["name"],
                                "reason": why})
            score = V.ratio(len(scope) - len(bad), len(scope))
            data = {"entity_type": t, "status": status, "conforming": len(scope) - len(bad), "applicable": len(scope),
                    "consistency": score, "exceptions": sorted(exc), "nonconforming": bad}
            cons.observe(f"{t} {status} naming consistency", **data)
            if status != "ENABLED":
                continue
            nonconforming += bad
            if score is not None and score < CONSISTENCY_SCREEN:
                cons.finding("consistency_below_80", "Info", {"entity_type": t, "status": status},
                             f"{t} names: {len(scope) - len(bad)}/{len(scope)} enabled conform ({score:.0%} < 80%)",
                             evidence=data, calculation={"numerator": "conforming", "denominator": "applicable enabled",
                                                         "screen": CONSISTENCY_SCREEN},
                             recommendation="Consider minimal renames (see rename proposals); no operational impact shown.",
                             uncertainty="Consistency is a convention measure, not a performance or reporting failure.")

    # -- step 5: duplicates in the correct scope
    dup = ctx.check("duplicates", "Duplicate campaign names in account and ad-group names in campaign")
    for t in TYPES:
        scope_key = (lambda e: "account") if t == "campaign" else (lambda e: e["campaign_id"])
        groups: dict[tuple, list[dict]] = {}
        for e in ents[t]:
            if e["status"] == "REMOVED":
                continue
            groups.setdefault((scope_key(e), _near(e["name"])), []).append(e)
        for (scope, _), members in sorted(groups.items()):
            if len(members) < 2:
                continue
            exact = len({m["name"] for m in members}) == 1
            dup.finding("duplicate_name" if exact else "near_duplicate_name", "Info",
                        {"entity_type": t, "scope": scope, "ids": sorted(m["id"] for m in members)},
                        f"{len(members)} {t}s share {'the exact' if exact else 'a case/space-equivalent'} name in {scope}",
                        evidence={"names": {m["id"]: m["name"] for m in members}, "statuses": {m["id"]: m["status"] for m in members}},
                        recommendation="Disambiguate names if reports join or filter by name; prefer ID joins.",
                        uncertainty="No consumer failure demonstrated.")

    # -- step 6: placeholders and misleading channel segments (profile-supplied)
    ph = ctx.check("placeholders_segments", "Placeholders and misleading channel segments")
    for t in TYPES:
        conv = convs[t] or (ctx.profile.get("naming_convention") or {}).get(t) or {}
        phrases = [str(p).lower() for p in conv.get("placeholders") or []]
        if not phrases:
            ph.partial(f"{t}: no profile placeholder phrases", [f"profile:naming_convention.{t}.placeholders"])
        for e in ents[t]:
            hits = [p for p in phrases if p and p in e["name"].lower()]
            if hits and e["status"] != "REMOVED":
                ph.finding("placeholder_name", "Info", {"entity_type": t, "id": e["id"], "campaign_id": e["campaign_id"]},
                           f"{t} {e['id']} name '{e['name']}' contains placeholder {hits}", evidence={"name": e["name"], "phrases": hits},
                           recommendation="Propose a descriptive name per the convention.", uncertainty="Naming preference only.")
        field, cmap = conv.get("channel_field"), conv.get("channel_map") or {}
        if t == "campaign" and convs[t] and field in convs[t]["fields"] and cmap:
            idx = convs[t]["fields"].index(field)
            for e in ents[t]:
                parts = [p.strip() for p in e["name"].split(convs[t]["delimiter"])]
                seg = parts[idx] if len(parts) == len(convs[t]["fields"]) else None
                want = cmap.get(seg) if seg is not None else None
                actual = str(e.get("channel_type") or "").upper()
                if want and actual and str(want).upper() != actual:
                    ph.finding("misleading_channel_segment", "Info", {"entity_type": t, "id": e["id"]},
                               f"Campaign {e['id']} name segment '{seg}' implies {want} but channel is {actual}",
                               evidence={"name": e["name"], "segment": seg, "mapped_channel": want, "actual_channel": actual},
                               recommendation="Correct the segment in a proposed rename.", uncertainty="No consumer failure shown.")
        elif t == "campaign" and not cmap:
            ph.partial("no profile channel_map: channel segments not checked")

    # -- step 7: consumer dependencies
    dep = ctx.check("dependencies", "Offending names linked to supplied consumers", {DEP: DEP_COLS})
    if dep.runnable:
        for r in sorted(ctx.rows(DEP), key=lambda r: str(r.get("consumer_id"))):
            t = str(r.get("entity_type") or "").strip().lower().replace("-", "_").replace(" ", "_")
            if t not in TYPES:
                dep.partial(f"consumer {r.get('consumer_id')}: unsupported entity_type {r.get('entity_type')}")
                continue
            try:
                pat = re.compile(str(r.get("name_pattern") or ""))
            except re.error as e:
                dep.partial(f"consumer {r.get('consumer_id')}: invalid name_pattern ({e})")
                continue
            scope_c = str(r.get("campaign_id") or "").strip()
            scope = [e for e in ents[t] if e["status"] == "ENABLED" and (not scope_c or e["campaign_id"] == scope_c)]
            offending = [{"id": e["id"], "campaign_id": e["campaign_id"], "name": e["name"]} for e in scope
                         if not pat.search(e["name"])]
            ev = {"consumer_id": r.get("consumer_id"), "name_pattern": r.get("name_pattern"),
                  "expected_behavior": r.get("expected_behavior"), "observed_failure": r.get("observed_failure"),
                  "evidence_ref": r.get("evidence_ref"), "owner": r.get("owner"), "reviewed_at": r.get("reviewed_at"),
                  "offending": offending, "scope_size": len(scope)}
            dep.observe(f"Consumer {r.get('consumer_id')}: {len(offending)}/{len(scope)} names outside its pattern", **ev)
            if not offending or not str(r.get("observed_failure") or "").strip():
                continue
            ent = {"consumer_id": str(r.get("consumer_id")), "entity_type": t}
            dep.review("naming_consumer_failure", ent,
                       f"Does the observed failure of consumer {r.get('consumer_id')} result from the offending names?",
                       evidence=ev,
                       outcomes={"failure_caused_by_names": {"severity": "Warning", "recommendation":
                                                             "Rename offending entities or switch the consumer to ID joins."},
                                 "unrelated": {"severity": None, "recommendation": "No naming action for this consumer."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the consumer owner."}},
                       guidance="failure_caused_by_names needs proposal.evidence_ref equal to the row's evidence_ref.")

    # -- step 8: minimal rename proposals (verified)
    ren = ctx.check("rename_proposals", "Minimal before/after rename proposals")
    if not any(convs.values()):
        ren.partial("no approved convention: proposals would be a proposed standard only", ["profile:naming_convention"])
    elif nonconforming:
        ren.review("rename_proposals", {"batch": "nonconforming_enabled_names"},
                   "Propose minimal renames for these non-conforming enabled names, preserving meaning and uniqueness.",
                   evidence={"nonconforming": nonconforming},
                   outcomes={"renames_proposed": {"severity": "Info", "recommendation":
                                                  "Owner reviews before/after names and affected consumers; no execution."},
                             "keep_names": {"severity": None, "recommendation": "No renames proposed."}},
                   guidance="proposal.renames = [{entity_type, id, before, after}]; after must conform and stay unique.")
    ren.observe("Non-conforming enabled names eligible for proposals", count=len(nonconforming))


def verify(ctx, item, decision) -> list[str]:
    """Rules: dependency Warning needs the row evidence_ref; renames must conform and stay unique in scope."""
    p = decision.get("proposal") or {}
    if item.condition_key == "naming_consumer_failure" and decision.get("outcome") == "failure_caused_by_names":
        ref = str(item.evidence.get("evidence_ref") or "").strip()
        if not ref or str(p.get("evidence_ref") or "").strip() != ref:
            return ["failure_caused_by_names needs proposal.evidence_ref equal to the consumer row's evidence_ref"]
        return []
    if item.condition_key != "rename_proposals" or decision.get("outcome") != "renames_proposed":
        return []
    listed = {(x["entity_type"], x["id"]): x for x in item.evidence.get("nonconforming", [])}
    ents = _entities(ctx)
    problems = []
    renames = p.get("renames") or []
    if not renames:
        return ["proposal.renames required"]
    final = {(t, e["id"]): e["name"] for t in TYPES for e in ents[t] if e["status"] != "REMOVED"}
    for r in renames:
        key = (str(r.get("entity_type")), str(r.get("id")))
        if key not in listed:
            problems.append(f"{key} not in reviewed non-conforming list")
            continue
        if r.get("before") != listed[key]["name"]:
            problems.append(f"{key}: before must equal the original name '{listed[key]['name']}'")
        ok, why = conforms(str(r.get("after") or ""), _conv(ctx, key[0]))
        if not ok:
            problems.append(f"{key}: after '{r.get('after')}' does not conform ({why})")
        final[key] = str(r.get("after") or "")
    for t in TYPES:
        seen: dict[tuple, str] = {}
        for e in ents[t]:
            if e["status"] == "REMOVED":
                continue
            k = ("account" if t == "campaign" else e["campaign_id"], _near(final[(t, e["id"])]))
            if k in seen and any(str(r.get("id")) in (e["id"], seen[k]) for r in renames):
                problems.append(f"rename makes {t} {e['id']} collide with {seen[k]} in scope {k[0]}")
            seen.setdefault(k, e["id"])
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
