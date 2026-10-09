"""check.py — skill-142 deterministic trademark usage inventory, policy status and authorization scope.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-142-trademark-policy-management/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Terms come only from external/trademark_register.term plus profile.competitor_terms (the latter are
         "unregistered supplied terms"); matching is whole-word on normalized ad text/assets/keywords and
         space-less/hyphenated substring on final URL host+path. A match is a mention, not a legal-risk label.
         Use types: text (headlines/descriptions/asset text), url (final_url/display paths), keyword.
         Deterministic Warning (documented use conflicts with supplied authorization scope) only when explicit:
         account_id not in a non-wildcard permitted_accounts, documented valid_to_if_documented before as_of,
         every register row for the term denied, or permitted_use lists recognized use types excluding this one.
         Pending requests / unknown permission / context-dependent mentions → Info (+ review when a register row
         exists but market/context scope needs interpretation). Expiry only from a documented date.
         An ad group is "blocked" only when every ENABLED ad in it is disapproved/not serving at its latest
         trademark-topic snapshot; Critical only via review with proposal.evidence_ref.
         No legal certification, request submission or ad removal.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-142-trademark-policy-management"
VERSION = "1.0.0"

TR = "external/trademark_register"
TPE = "external/trademark_page_evidence"
PS = "custom/trademark_policy_status"
_SEPS = (" | ", ";", "|", ",")
_WILD = ("*", "all", "any")
_USE_WORDS = {"text": ("text", "ad_text", "ad text", "ad copy", "copy", "headline", "description"),
              "url": ("url", "domain", "path", "display_url"),
              "keyword": ("keyword", "keywords")}


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _word_hit(term: str, text) -> bool:
    t = V.norm_text(term)
    return bool(t) and re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", V.norm_text(text)) is not None


def _url_hit(term: str, url) -> bool:
    u = _s(url).lower()
    if not u:
        return False
    p = urlsplit(u)
    hay = p.netloc + p.path
    t = V.norm_text(term)
    return any(v and v in hay for v in (t.replace(" ", ""), t.replace(" ", "-")))


def _terms(ctx) -> dict[str, list[dict]]:
    """normalized term → register rows ([] for unregistered profile competitor terms)."""
    out: dict[str, list[dict]] = {}
    for r in ctx.rows(TR):
        t = V.norm_text(r.get("term"))
        if t:
            out.setdefault(t, []).append(r)
    for t in ctx.profile.get("competitor_terms") or []:
        out.setdefault(V.norm_text(t), [])
    return out


def _matches(ctx, terms) -> list[dict]:
    """Every (term, use_type, entity) mention in active ads, assets and keywords."""
    out = []
    for a in sorted(ctx.rows("ads"), key=lambda r: _s(r.get("id"))):
        if _s(a.get("status")).upper() not in ("ENABLED", ""):
            continue
        base = {"ad_id": _s(a.get("id")), "campaign_id": _s(a.get("campaign_id")),
                "ad_group_id": _s(a.get("ad_group_id")), "final_url": a.get("final_url")}
        text = " | ".join(_s(a.get(c)) for c in ("headlines", "descriptions"))
        for t in sorted(terms):
            if _word_hit(t, text):
                out.append({**base, "term": t, "use_type": "text", "context": text})
            if _url_hit(t, a.get("final_url")) or _word_hit(t, a.get("display_paths")):
                out.append({**base, "term": t, "use_type": "url", "context": a.get("final_url")})
    assets = ctx.table("assets")
    if assets is not None and "text" in assets.columns:
        for a in sorted(assets.rows, key=lambda r: _s(r.get("id"))):
            for t in sorted(terms):
                if _word_hit(t, a.get("text")):
                    out.append({"asset_id": _s(a.get("id")), "campaign_id": _s(a.get("campaign_id")),
                                "ad_group_id": _s(a.get("ad_group_id")), "term": t, "use_type": "text",
                                "context": a.get("text")})
    kws = ctx.table("keywords")
    if kws is not None and not kws.missing(["id", "campaign_id", "ad_group_id", "text"]):
        for k in sorted(kws.rows, key=lambda r: _s(r.get("id"))):
            if _s(k.get("status")).upper() not in ("ENABLED", ""):
                continue
            for t in sorted(terms):
                if _word_hit(t, k.get("text")):
                    out.append({"keyword_id": _s(k.get("id")), "campaign_id": _s(k.get("campaign_id")),
                                "ad_group_id": _s(k.get("ad_group_id")), "term": t, "use_type": "keyword",
                                "context": k.get("text")})
    return out


def _entity(m: dict) -> dict:
    return {k: m[k] for k in ("term", "use_type", "ad_id", "asset_id", "keyword_id", "campaign_id", "ad_group_id")
            if k in m}


def run(ctx) -> None:
    """Run trademark term usage, policy status, authorization scope and request-queue checks.

    Rules:   Matches are mentions, never legal risk. Deterministic Warning only for explicit authorization conflicts
             (non-wildcard permitted_accounts, documented expiry before as_of, all rows denied, excluded use type);
             pending/unknown permission and context-dependent mentions → Info (+ review when scope needs
             interpretation). Ad-group block is Info + ai_review; Critical only via 'material_blockage' with
             proposal.evidence_ref.
    """
    matches = _usage(ctx)
    _policy(ctx)
    _authorization(ctx, matches)
    _queue(ctx, matches)


def _usage(ctx) -> list[dict]:
    """Step 1: term mentions by use type."""
    chk = ctx.check("term_usage", "Trademark term usage in ads, assets and keywords",
                    {"ads": ["id", "campaign_id", "ad_group_id", "status", "headlines", "descriptions", "final_url"],
                     TR: ["trademark_id", "term"]})
    if not chk.runnable:
        return []
    terms = _terms(ctx)
    assets = ctx.table("assets")
    if assets is None or "text" not in assets.columns:
        chk.partial("asset text not scanned", ["assets:text"])
    if ctx.table("keywords") is None:
        chk.partial("keyword targeting not scanned", ["keywords (file)"])
    matches = _matches(ctx, terms)
    by = {}
    for m in matches:
        by.setdefault((m["term"], m["use_type"]), 0)
        by[(m["term"], m["use_type"])] += 1
    for (t, u) in sorted(by):
        chk.observe(f"'{t}' used as {u}", term=t, use_type=u, mentions=by[(t, u)], registered=bool(terms[t]))
    for m in matches:
        if not terms[m["term"]]:
            chk.finding("unknown_permission", "Info", _entity(m),
                        f"Supplied term '{m['term']}' appears as {m['use_type']} with no register/authorization record",
                        evidence={"context": m["context"], "source": "profile.competitor_terms"},
                        recommendation="Request authorization evidence or context review from the trademark specialist.",
                        uncertainty="A competitor mention is not universally prohibited; context decides.")
    chk.observe("Mention totals", mentions=len(matches), terms=len(terms))
    return matches


def _latest_status(ctx) -> dict[tuple[str, str], dict]:
    out = {}
    for r in sorted(ctx.rows(PS), key=lambda r: _s(r.get("snapshot_at"))):
        out[(_s(r.get("ad_id")), _s(r.get("topic")))] = r
    return out


def _restricted(r: dict) -> bool:
    txt = " ".join(_s(r.get(c)).lower() for c in ("approval_status", "serving_status", "limitation"))
    return any(w in txt for w in ("disapproved", "not serving", "not_serving", "not eligible", "not_eligible"))


def _policy(ctx) -> None:
    """Step 2: trademark topics and serving; ad group blocked only when no other eligible ad serves."""
    chk = ctx.check("policy_status", "Trademark policy topics and ad-group serving",
                    {PS: ["ad_id", "topic", "snapshot_at", "campaign_id", "ad_group_id", "approval_status",
                          "serving_status", "limitation", "request_id_if_known"],
                     "ads": ["id", "ad_group_id", "status"]})
    if not chk.runnable:
        return
    latest = _latest_status(ctx)
    restricted_ads = {ad for (ad, topic), r in latest.items() if "trademark" in topic.lower() and _restricted(r)}
    any_restricted = {ad for (ad, _), r in latest.items() if _restricted(r)}
    reported = {ad for ad, _ in latest}
    groups: dict[str, list[str]] = {}
    for a in ctx.rows("ads"):
        if _s(a.get("status")).upper() in ("ENABLED", ""):
            groups.setdefault(_s(a.get("ad_group_id")), []).append(_s(a.get("id")))
    unreported = sorted(ad for ads in groups.values() for ad in ads if ad not in reported)
    if unreported:
        chk.partial(f"{len(unreported)} enabled ads without policy diagnostics; eligibility unknown: {unreported[:10]}")
    for gid in sorted(groups):
        hit = sorted(set(groups[gid]) & restricted_ads)
        if not hit:
            continue
        others = [ad for ad in groups[gid] if ad not in any_restricted]
        rows = [latest[k] for k in sorted(latest) if k[0] in hit and "trademark" in k[1].lower()]
        ev = {"restricted_ads": hit, "other_enabled_ads": sorted(others),
              "others_with_diagnostics": sorted(a for a in others if a in reported),
              "statuses": [{k: r.get(k) for k in ("ad_id", "topic", "snapshot_at", "approval_status",
                                                  "serving_status", "limitation", "request_id_if_known")}
                           for r in rows]}
        entity = {"ad_group_id": gid, "campaign_id": _s(rows[0].get("campaign_id"))}
        if others:
            chk.observe(f"Ad group {gid}: trademark-restricted ads but other enabled ads may serve", **entity, **ev)
            continue
        prov = chk.finding("ad_group_trademark_block", "Info", entity,
                           f"Ad group {gid}: every enabled ad is disapproved/not serving at its latest trademark "
                           f"diagnostic ({', '.join(hit)})", evidence=ev,
                           recommendation="Specialist review of scoped copy alternatives or an authorization request.",
                           uncertainty="Delivery loss magnitude not in the supplied evidence.")
        chk.review("ad_group_trademark_block", entity,
                   f"Is the trademark block of ad group {gid} a MATERIAL delivery blockage?",
                   evidence=ev,
                   outcomes={"material_blockage": {"severity": "Critical", "recommendation":
                                                   "Prioritize specialist review; cite delivery evidence."},
                             "not_material": {"severity": "Info", "recommendation": "Queue for specialist review."}},
                   guidance="Critical needs proposal.evidence_ref to supplied delivery evidence.",
                   provisional=prov)


def _use_allowed(permitted_use, use_type: str) -> bool | None:
    toks = [x.lower() for x in V.split_list(permitted_use, _SEPS)]
    if not toks or any(t in _WILD for t in toks):
        return True
    known = {u for u, words in _USE_WORDS.items() for t in toks if t in words}
    if not known:
        return None
    return use_type in known


def _authorization(ctx, matches: list[dict]) -> None:
    """Step 3: authorization scope, relationship and page context per registered-term mention."""
    chk = ctx.check("authorization_scope", "Documented use vs supplied authorization scope",
                    {TR: ["trademark_id", "market", "authorization_id", "term", "owner", "advertiser_relationship",
                          "permitted_use", "permitted_accounts", "permitted_markets", "supporting_document_ref",
                          "valid_from", "valid_to_if_documented", "request_id", "request_status"]})
    if not chk.runnable:
        return
    terms = _terms(ctx)
    acct = _s(ctx.account_id)
    as_of = ctx.as_of
    pages = {}
    for p in ctx.rows(TPE):
        pages.setdefault(_s(p.get("url")).lower().rstrip("/"), []).append(p)
    if ctx.table(TPE) is None:
        chk.partial("trademark page evidence missing: reseller/informational context unknown", [f"{TPE} (file)"])
    for m in matches:
        regs = terms.get(m["term"]) or []
        if not regs:
            continue
        if any(_s(r.get("advertiser_relationship")).lower() in ("owner", "self", "trademark_owner") for r in regs):
            chk.observe(f"'{m['term']}' is the advertiser's own mark", **_entity(m))
            continue
        entity = _entity(m)
        problems_by_row = []
        for r in regs:
            p = []
            accts = V.split_list(r.get("permitted_accounts"), _SEPS)
            if accts and not any(a.lower() in _WILD for a in accts) and acct and acct not in accts:
                p.append(f"account {acct} not in permitted_accounts {accts}")
            vt = V.parse_date(r.get("valid_to_if_documented"))
            if vt and as_of and vt < as_of:
                p.append(f"documented authorization ended {vt} (as of {as_of})")
            vf = V.parse_date(r.get("valid_from"))
            if vf and as_of and vf > as_of:
                p.append(f"authorization starts {vf}, after {as_of}")
            if _s(r.get("request_status")).lower() in ("denied", "rejected"):
                p.append(f"request {r.get('request_id')} denied")
            if _use_allowed(r.get("permitted_use"), m["use_type"]) is False:
                p.append(f"permitted_use '{r.get('permitted_use')}' excludes {m['use_type']} use")
            problems_by_row.append((r, p))
        page_ctx = pages.get(_s(m.get("final_url")).lower().rstrip("/"), [])
        ev = {"context": m["context"], "account_id": acct, "as_of": as_of,
              "register_rows": [{k: r.get(k) for k in sorted(r)} for r in regs],
              "page_evidence": [{k: p.get(k) for k in sorted(p)} for p in page_ctx]}
        if all(p for _, p in problems_by_row):
            chk.finding("use_conflicts_authorization", "Warning", entity,
                        f"'{m['term']}' {m['use_type']} use conflicts with every supplied authorization: "
                        + " | ".join(sorted({x for _, p in problems_by_row for x in p})),
                        evidence={**ev, "problems": [p for _, p in problems_by_row]},
                        recommendation="Specialist review: scoped copy alternative or authorization request "
                                       "(request-only; nothing submitted or removed).",
                        uncertainty="Not a legal determination.")
            continue
        clean = [r for r, p in problems_by_row if not p]
        statuses = {_s(r.get("request_status")).lower() for r in clean}
        undecidable = any(_use_allowed(r.get("permitted_use"), m["use_type"]) is None for r in clean)
        if statuses and statuses <= {"pending", "submitted", "in_review", ""} and not any(
                _s(r.get("supporting_document_ref")) for r in clean):
            chk.finding("pending_or_unknown_permission", "Info", entity,
                        f"'{m['term']}' {m['use_type']} use: authorization pending or undocumented",
                        evidence=ev, recommendation="Track the request with the legal owner.",
                        uncertainty="Pending is not permission; permission is not platform approval.")
            continue
        prov = chk.finding("context_dependent_mention", "Info", entity,
                           f"'{m['term']}' {m['use_type']} use needs market/context scope review against "
                           f"authorization {', '.join(sorted({_s(r.get('authorization_id')) for r in clean}))}",
                           evidence={**ev, "permitted_use_undecidable": undecidable},
                           recommendation="Specialist scope review; no legal certification.",
                           uncertainty="Market vocabulary and reseller/informational context need interpretation.")
        chk.review("authorization_scope", entity,
                   f"Is the '{m['term']}' {m['use_type']} use within the supplied authorization's markets, use and "
                   f"reseller/informational context?",
                   evidence={**ev, "permitted_use_undecidable": undecidable, "campaign_geo": next((c.get("geo_targets") for c in ctx.rows("campaigns")
                                                         if _s(c.get("id")) == m["campaign_id"]), None)},
                   outcomes={"conflicts_authorization_scope": {"severity": "Warning", "recommendation":
                                                               "Scoped copy alternative or authorization request."},
                             "within_scope": {"severity": None, "recommendation": "Record the authorization used."},
                             "uncertain": {"severity": "Info", "recommendation": "Ask the legal owner."}},
                   guidance="Use only the register, page evidence and campaign targeting; competitor mention "
                            "without exemption is not universally prohibited. conflicts_authorization_scope needs "
                            "proposal.register_ref (authorization_id or trademark_id from evidence).",
                   provisional=prov)


def _queue(ctx, matches: list[dict]) -> None:
    """Step 4: documented request/expiry queue."""
    chk = ctx.check("request_queue", "Documented request and expiry queue",
                    {TR: ["trademark_id", "term", "request_id", "request_status", "reviewed_at",
                          "valid_to_if_documented", "legal_owner"]})
    if not chk.runnable:
        return
    used = {m["term"] for m in matches}
    for r in sorted(ctx.rows(TR), key=lambda r: (_s(r.get("trademark_id")), _s(r.get("request_id")))):
        vt = V.parse_date(r.get("valid_to_if_documented"))
        chk.observe(f"Request {r.get('request_id') or '-'} for '{r.get('term')}': {r.get('request_status') or 'unknown'}",
                    trademark_id=r.get("trademark_id"), term=r.get("term"), request_id=r.get("request_id"),
                    request_status=r.get("request_status"), reviewed_at=r.get("reviewed_at"),
                    documented_expiry=vt, days_to_expiry=(vt - ctx.as_of).days if vt and ctx.as_of else None,
                    term_in_use=V.norm_text(r.get("term")) in used, legal_owner=r.get("legal_owner"))


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs proposal.evidence_ref; scope conflicts must cite a register row of the item."""
    outcome, p = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "material_blockage" and not p.get("evidence_ref"):
        return ["material_blockage needs proposal.evidence_ref"]
    if outcome == "conflicts_authorization_scope":
        refs = {_s(r.get(k)) for r in item.evidence.get("register_rows", [])
                for k in ("authorization_id", "trademark_id")} - {""}
        if _s(p.get("register_ref")) not in refs:
            return [f"proposal.register_ref must be one of {sorted(refs)}"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
