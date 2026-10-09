"""check.py — skill-025 deterministic RSA headline duplication, counts and Ad Strength inventory.

exports: SKILL | VERSION | DRAFT_LIMITS | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-025-rsa-headline-diversity-completeness/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #1 Report Ad Groups that don't have RSAs (nilsrooijmans.com) — clean-room reimplementation of
         enabled ad groups in enabled campaigns lacking an enabled RSA, gated on a manifest-complete ads inventory
         skills/skill-026-rsa-description-optimization/scripts/check.py — same private normalization/width helpers
         index #113 Responsive Search Ads builder (google/responsive-search-ads-builder) — clean-room: its "assemble a
         full RSA per ad group from existing copy" becomes the opt-in rsa_draft review whose proposal verify() checks;
         REFUSED: writing drafts to Sheets, MCC-wide iteration, spend-threshold triggering and blind reuse of
         existing copy without claim/competitor/excluded-term screens (recommend-only library).
         skills/skill-145-prelaunch-compliance-checklist/scripts/check.py — same insertion-token fallback rendering
rules:   Duplicate matching: NFKC + casefold + collapsed whitespace; punctuation/numbers kept. Near-duplicates:
         Jaccard of unique \\w+ token sets > 0.70 (Info); empty token sets are unavailable, never 0.
         Findings only for active RSAs (ad, ad group and campaign ENABLED or parent status unknown); paused
         inventory is counted in observations.
         Unknown Ad Strength is 'UNAVAILABLE' coverage, never Poor; categories are counted, never averaged.
         Headline limits (RSA_LIMITS: 3..15 headlines, 30 display columns; East-Asian wide chars count 2) may be
         replaced by profile.rsa_limits; exported over-limit text is an exporter question, not a live violation.
         Ad groups without an enabled RSA are Info and only provable from a manifest-complete ads table.
         Theme coverage, misleading claims and constraint violations are ai_review; Warning outcomes need
         proposal.evidence_ref; proposed headlines are verified for width and normalized uniqueness.
         Rating/outcome comparisons are observational: ctx.mature True and both cohorts gated.
         rsa_draft is OPT-IN: only profile.rsa_draft_requests (ad_group_id entries, or {campaign_id, scope:
         enabled_ad_groups|all_ad_groups}) creates reviews; otherwise not_applicable, never a finding.
         A requested group without an existing ad/keyword final URL gets no review (partial): final_url must equal
         an existing destination. DRAFT_LIMITS come from support.google.com/google-ads/answer/7684791 (consulted
         2026-09-25): 3..15 headlines <=30, 2..4 descriptions <=90, paths <=15, double-width chars count 2; pins
         headline 1-3, description 1-2; profile.rsa_limits may override a key (recorded in limits_source).
         Insertion syntax: keyword tag keyword|Keyword|KeyWord|KEYWord|KeyWORD
         (answer/6371157), {CUSTOMIZER.Name:default} (answer/10711524 + API RSA customization doc),
         {LOCATION(City|State|Country):default} max 1 per headline / 2 per description (answer/9773001). Every
         token needs a non-empty default and the default-rendered text must fit; COUNTDOWN (no fallback) and
         unknown tokens are rejected; paths accept keyword insertion only; final_url accepts no tokens.
         Competitor terms (profile.competitor_terms) only when campaign brand_policy == competitor_only; literal
         excluded terms = profile.excluded_intent_terms + campaign_objectives[id].excluded_intent_terms (word-
         token phrase match). Keyword insertion needs the ad group keyword inventory and is rejected when an
         insertable keyword carries a forbidden term. With profile.approved_claims every number/percent/price
         (value + unit: '%', currency symbol or the account currency code, else none) in rendered copy must occur
         in an approved claim; without approved_claims numbers are not screened.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | #113 opt-in rsa_draft proposal + verify
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-025-rsa-headline-diversity-completeness"
VERSION = "1.1.0"

RSA_LIMITS = {"headlines_min": 3, "headlines_max": 15, "headline_width": 30}  # support.google.com/.../7684791
DRAFT_LIMITS = {**RSA_LIMITS, "descriptions_min": 2, "descriptions_max": 4, "description_width": 90,
                "path_width": 15}
LIMITS_SOURCE = "https://support.google.com/google-ads/answer/7684791 (consulted 2026-09-25)"
PINS = {"headline": (1, 2, 3), "description": (1, 2)}
KEYWORD_TAGS = ("keyword", "Keyword", "KeyWord", "KEYWord", "KeyWORD")
JACCARD_CUTOFF = 0.70
ADS_NEEDS = {"ads": ["id", "campaign_id", "ad_group_id", "type", "status", "headlines"]}
METRIC_COLS = ["ad_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"]
_TOKEN = re.compile(r"\w+", re.UNICODE)
_BRACE = re.compile(r"\{([^{}]*)\}")
_LOCATION = re.compile(r"LOCATION\((City|State|Country)\)")
_ATTR_NAME = re.compile(r"[^\W_][\w ]*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(v) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(v or "")).casefold().split())


def _width(v) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(v or ""))


def _texts(cell) -> list[str] | None:
    """RSA text array → list of raw strings (JSON list of str/{text} or ' | ' separated); None when unusable."""
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


def _status_maps(ctx):
    groups = {str(r.get("id")): str(r.get("status") or "").upper() for r in ctx.rows("ad_groups")}
    camps = {str(r.get("id")): str(r.get("status") or "").upper() for r in ctx.rows("campaigns")}
    return groups, camps


def _active(ad: dict, groups: dict, camps: dict) -> bool:
    ok = lambda s: s in ("ENABLED", "")
    return (str(ad.get("status") or "").upper() == "ENABLED"
            and ok(groups.get(str(ad.get("ad_group_id")), "")) and ok(camps.get(str(ad.get("campaign_id")), "")))


def _entity(ad: dict) -> dict:
    return {"campaign_id": str(ad.get("campaign_id")), "ad_group_id": str(ad.get("ad_group_id")), "ad_id": str(ad.get("id"))}


# ---------------------------------------------------------------------------------------------- #113 rsa_draft
def _draft_limits(ctx) -> tuple[dict, str]:
    """DRAFT_LIMITS with profile.rsa_limits overrides; returns (limits, source)."""
    lim, over = dict(DRAFT_LIMITS), []
    for k, v in (ctx.profile.get("rsa_limits") or {}).items():
        if k in lim and V.integer(v):
            lim[k] = V.integer(v)
            over.append(k)
    return lim, LIMITS_SOURCE + (f"; profile.rsa_limits overrides {sorted(over)}" if over else "")


def _objective(ctx, cid: str) -> dict:
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    return obj if isinstance(obj, dict) else {}


def _terms(values) -> list[str]:
    return sorted({_norm(t) for t in (values if isinstance(values, list) else []) if _norm(t)})


def _has_term(term: str, text: str) -> bool:
    """Literal word-token phrase containment after NFKC/casefold (punctuation separates words)."""
    t, s = _TOKEN.findall(_norm(term)), _TOKEN.findall(_norm(text))
    return bool(t) and any(s[i:i + len(t)] == t for i in range(len(s) - len(t) + 1))


def _url_key(v) -> str:
    p = urlsplit(str(v or "").strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, p.fragment))


def _urls(cell) -> list[str]:
    if cell is None:
        return []
    s = str(cell).strip()
    if s.startswith("["):
        try:
            return [str(u) for u in json.loads(s) if u]
        except ValueError:
            return []
    return V.split_list(s, (" | ", "|", "\n"))


def _render(text: str, field: str) -> tuple[str, list[str], list[str]]:
    """Replace insertion tokens by their default text → (rendered, token kinds, problems).

    Rules:   see module rules — every token needs a non-empty default; paths allow keyword insertion only.
    """
    problems, kinds = [], []
    if _BRACE.sub("", text).count("{") or _BRACE.sub("", text).count("}"):
        problems.append(f"{field} '{text}': unbalanced or nested braces")

    def repl(m):
        head, sep, default = m.group(1).partition(":")
        kind = ("keyword" if head in KEYWORD_TAGS else
                "customizer" if head.startswith("CUSTOMIZER.") else
                "location" if _LOCATION.fullmatch(head) else
                "countdown" if head.startswith(("COUNTDOWN(", "GLOBAL_COUNTDOWN(")) else "unknown")
        kinds.append(kind)
        if kind == "unknown":
            problems.append(f"{field} '{text}': unsupported insertion token {{{m.group(1)}}}")
        elif kind == "countdown":
            problems.append(f"{field} '{text}': countdown has no fallback text; width not verifiable")
        elif kind == "customizer" and not _ATTR_NAME.fullmatch(head[len("CUSTOMIZER."):]):
            problems.append(f"{field} '{text}': customizer attribute name must not start with '_' or hold symbols")
        elif not sep or not default.strip():
            problems.append(f"{field} '{text}': {{{m.group(1)}}} needs a non-empty default text")
        if field.startswith("path") and kind != "keyword":
            problems.append(f"{field} '{text}': only keyword insertion is allowed in display paths")
        return default if sep else ""

    return _BRACE.sub(repl, text), kinds, problems


def _canon(num: str) -> str:
    """Canonical number text: thousands separators dropped, ',' decimal → '.', trailing zeros removed."""
    s = re.sub(r"[.,](?=\d{3}(?!\d))", "", num).replace(",", ".")
    try:
        return f"{round(float(s), 6):f}".rstrip("0").rstrip(".")
    except ValueError:
        return num


def _claims(text: str, codes: set[str]) -> set[tuple]:
    """Numeric claims as (value, unit) with unit '%', 'price' (currency symbol or code) or ''."""
    out = set()
    for m in _NUMBER.finditer(text):
        before, after = text[:m.start()].rstrip(), text[m.end():].lstrip()
        pre = re.search(r"(?<![A-Za-z])([A-Za-z]{3})$", before)
        post = re.match(r"([A-Za-z]{3})(?![A-Za-z])", after)
        if after.startswith("%"):
            unit = "%"
        elif (before and unicodedata.category(before[-1]) == "Sc") or \
                (after and unicodedata.category(after[0]) == "Sc") or \
                (pre and pre.group(1).upper() in codes) or (post and post.group(1).upper() in codes):
            unit = "price"
        else:
            unit = ""
        out.add((_canon(m.group()), unit))
    return out


def _draft_targets(ctx, req) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve rsa_draft_requests to sorted (campaign_id, ad_group_id); notes list unusable entries."""
    groups = {str(g.get("id")): g for g in ctx.rows("ad_groups")}
    removed = lambda g: str(g.get("status") or "").upper() in ("REMOVED", "DELETED")
    out, notes = set(), []
    if not isinstance(req, list):
        return [], ["profile.rsa_draft_requests must be a list of ad_group_id or {campaign_id, scope}"]
    for e in req:
        if isinstance(e, dict) and e.get("campaign_id") is not None and e.get("ad_group_id") is None:
            cid, scope = str(e["campaign_id"]), str(e.get("scope") or "")
            if scope not in ("enabled_ad_groups", "all_ad_groups"):
                notes.append(f"campaign {cid} request needs explicit scope enabled_ad_groups|all_ad_groups")
                continue
            hit = [gid for gid, g in groups.items() if str(g.get("campaign_id")) == cid and not removed(g)
                   and (scope == "all_ad_groups" or str(g.get("status") or "").upper() == "ENABLED")]
            if not hit:
                notes.append(f"campaign {cid} ({scope}): no matching ad groups in ad_groups")
            out |= {(cid, gid) for gid in hit}
            continue
        gid = str(e.get("ad_group_id") if isinstance(e, dict) else e)
        g = groups.get(gid)
        if g is None or removed(g):
            notes.append(f"requested ad group {gid} not found (or removed) in ad_groups")
            continue
        out.add((str(g.get("campaign_id")), gid))
    return sorted(out), notes


def _rsa_drafts(ctx) -> None:
    """Step 8 opt-in (#113): one rsa_draft review per requested ad group with copy, keyword and URL evidence.

    Rules:   Only profile.rsa_draft_requests makes this applicable; never a finding without a validated decision.
             Groups lacking an existing ad/keyword final URL get no review (partial) because final_url must equal an
             existing destination. Outcomes: draft_proposed (Info) | no_draft (none).
    """
    req = ctx.profile.get("rsa_draft_requests")
    chk = ctx.check("rsa_draft", "Requested RSA draft proposals (opt-in, index #113)",
                    {**ADS_NEEDS, "ad_groups": ["id", "campaign_id", "status"]}, applicable=bool(req),
                    na_reason="profile.rsa_draft_requests not set (opt-in)")
    if not chk.runnable:
        return
    targets, notes = _draft_targets(ctx, req)
    for n in notes:
        chk.partial(n, ["profile.rsa_draft_requests"])
    lim, source = _draft_limits(ctx)
    kw_t = ctx.table("keywords")
    kw_ok = kw_t is not None and not kw_t.missing(["ad_group_id", "text", "status"])
    if not kw_ok:
        chk.partial("keywords inventory missing: keyword evidence absent and keyword insertion not verifiable",
                    ["keywords:ad_group_id", "keywords:text", "keywords:status"])
    claims = ctx.profile.get("approved_claims")
    if claims is not None and not isinstance(claims, list):
        chk.partial("profile.approved_claims must be a list; numeric claims cannot be approved", ["profile.approved_claims"])
    approved = None if claims is None else [str(c.get("text") or c.get("claim") or "") if isinstance(c, dict)
                                            else str(c) for c in (claims if isinstance(claims, list) else [])]
    live = lambda r: str(r.get("status") or "").upper() not in ("REMOVED", "DELETED")
    queued = []
    for cid, gid in targets:
        ads = sorted((r for r in ctx.rows("ads") if str(r.get("ad_group_id")) == gid and live(r)),
                     key=lambda r: str(r.get("id")))
        kws = sorted((k for k in ctx.rows("keywords") if str(k.get("ad_group_id")) == gid and live(k)),
                     key=lambda k: (_norm(k.get("text")), str(k.get("match_type")))) if kw_ok else []
        dests = sorted({u for r in ads for c in ("final_url", "final_urls") for u in _urls(r.get(c))}
                       | {u for k in kws for c in ("final_url", "final_urls") for u in _urls(k.get(c))})
        if not dests:
            chk.partial(f"ad group {gid}: no existing final URL in ads/keywords; draft final_url not verifiable",
                        ["ads:final_url"])
            continue
        obj = _objective(ctx, cid)
        rsas = [{"ad_id": str(r.get("id")), "status": r.get("status"), "headlines": _texts(r.get("headlines")),
                 "descriptions": _texts(r.get("descriptions")), "pinned_positions": r.get("pinned_positions"),
                 "final_urls": _urls(r.get("final_url") or r.get("final_urls"))}
                for r in ads if str(r.get("type") or "").upper() == "RESPONSIVE_SEARCH_AD"]
        ev = {"campaign_id": cid, "ad_group_id": gid, "current_rsas": rsas,
              "keywords": [{"text": k.get("text"), "match_type": k.get("match_type"), "status": k.get("status")}
                           for k in kws] if kw_ok else None,
              "existing_final_urls": dests, "approved_claims": approved,
              "brand_terms": _terms(ctx.profile.get("brand_terms")),
              "competitor_terms": _terms(ctx.profile.get("competitor_terms")),
              "excluded_terms": _terms(list(ctx.profile.get("excluded_intent_terms") or [])
                                       + list(obj.get("excluded_intent_terms") or [])),
              "brand_policy": str(obj.get("brand_policy") or "").lower() or None,
              "currency": ctx.currency, "limits": lim, "limits_source": source, "pin_positions": PINS}
        chk.review("rsa_draft", {"campaign_id": cid, "ad_group_id": gid},
                   f"Propose a complete RSA draft for ad group {gid} (campaign {cid}) from the supplied copy, keywords, "
                   f"existing final URL and approved claims only, or decline.",
                   evidence=ev,
                   outcomes={"draft_proposed": {"severity": "Info", "recommendation":
                                                "Owner review of the validated RSA draft; nothing is uploaded."},
                             "no_draft": {"severity": None, "recommendation":
                                          "No draft: state which approved messaging or evidence is missing."}},
                   guidance="draft_proposed needs proposal {headlines:[{text, pin?}] 3-15 (<=30 cols), "
                            "descriptions:[{text, pin?}] 2-4 (<=90), path1?/path2? (<=15, keyword insertion only), "
                            "final_url one of existing_final_urls}. Pins: headline 1-3, description 1-2. Tokens need "
                            "a default that fits: {KeyWord:x} (keyword|Keyword|KeyWord|KEYWord|KeyWORD), "
                            "{CUSTOMIZER.Name:x}, {LOCATION(City|State|Country):x}; no COUNTDOWN. No normalized "
                            "duplicates, no competitor terms unless brand_policy competitor_only, no excluded terms; "
                            "with approved_claims every number/percent/price must appear in them. No invented offers.")
        queued.append(gid)
    chk.observe("RSA draft requests resolved", requested_entries=len(req) if isinstance(req, list) else None,
                reviewed_ad_groups=queued, limits=lim, limits_source=source)


def _verify_draft(ctx, item, p) -> list[str]:
    """Deterministic re-check of a draft_proposed proposal against the item evidence (see module rules)."""
    ev = item.evidence
    if not isinstance(p, dict):
        return ["proposal must be an object {headlines, descriptions, path1?, path2?, final_url}"]
    lim = ev.get("limits") or DRAFT_LIMITS
    problems: list[str] = []
    rendered: list[str] = []
    uses_keyword = False
    for field, key in (("headline", "headlines"), ("description", "descriptions")):
        items = p.get(key)
        if not isinstance(items, list):
            problems.append(f"proposal.{key} must be a list of {{text, pin?}}")
            continue
        lo, hi, width = lim[f"{key}_min"], lim[f"{key}_max"], lim[f"{field}_width"]
        if not lo <= len(items) <= hi:
            problems.append(f"{len(items)} {key}, allowed {lo}..{hi} per {ev.get('limits_source') or LIMITS_SOURCE}")
        seen: dict[str, int] = {}
        for i, h in enumerate(items):
            text = h.get("text") if isinstance(h, dict) else None
            if not isinstance(text, str) or not text.strip():
                problems.append(f"{field} {i + 1}: needs a non-empty text")
                continue
            out, kinds, issues = _render(text, field)
            problems += issues
            uses_keyword |= "keyword" in kinds
            loc_max = 1 if field == "headline" else 2
            if kinds.count("location") > loc_max:
                problems.append(f"{field} '{text}': more than {loc_max} location insertion(s)")
            if _width(out) > width:
                problems.append(f"{field} '{text}': {_width(out)} columns with default text > {width}")
            pin = h.get("pin")
            if pin is not None and (isinstance(pin, bool) or V.integer(pin) not in PINS[field]):
                problems.append(f"{field} '{text}': pin {pin!r} not in positions {list(PINS[field])}")
            n = _norm(text)
            if n in seen:
                problems.append(f"{field} '{text}' duplicates {field} {seen[n] + 1} after normalization")
            seen.setdefault(n, i)
            rendered.append(out)
    for key in ("path1", "path2"):
        v = p.get(key)
        if v in (None, ""):
            continue
        if not isinstance(v, str):
            problems.append(f"{key} must be text")
            continue
        out, kinds, issues = _render(v, key)
        problems += issues
        uses_keyword |= "keyword" in kinds
        if _width(out) > lim["path_width"]:
            problems.append(f"{key} '{v}': {_width(out)} columns > {lim['path_width']}")
        rendered.append(out)
    url = p.get("final_url")
    if not isinstance(url, str) or not url.strip():
        problems.append("proposal.final_url required")
    elif "{" in url or "}" in url:
        problems.append("final_url cannot contain insertion tokens (answer/6371157)")
    elif _url_key(url) not in {_url_key(u) for u in ev.get("existing_final_urls") or []}:
        problems.append(f"final_url {url} is not an existing destination of ad group {ev.get('ad_group_id')}")
    comp_ok = ev.get("brand_policy") == "competitor_only"
    forbidden = [("excluded", t) for t in ev.get("excluded_terms") or []]
    forbidden += [] if comp_ok else [("competitor", t) for t in ev.get("competitor_terms") or []]
    for text in rendered:
        for kind, t in forbidden:
            if _has_term(t, text):
                problems.append(f"'{text}' contains {kind} term '{t}' (brand_policy {ev.get('brand_policy')})")
    if uses_keyword:
        if ev.get("keywords") is None:
            problems.append("keyword insertion needs the ad group keyword inventory (keywords evidence missing)")
        for k in ev.get("keywords") or []:
            bad = [t for kind, t in forbidden if _has_term(t, str(k.get("text") or ""))]
            if bad:
                problems.append(f"keyword insertion could insert keyword '{k.get('text')}' containing {bad}")
    if ev.get("approved_claims") is not None:
        codes = {ev["currency"]} if ev.get("currency") else set()
        ok = set().union(*(_claims(c, codes) for c in ev["approved_claims"])) if ev["approved_claims"] else set()
        for text in rendered:
            missing = sorted(f"{v}{'%' if u == '%' else ' (price)' if u == 'price' else ''}"
                             for v, u in _claims(text, codes) if (v, u) not in ok)
            if missing:
                problems.append(f"'{text}': numeric claim(s) {missing} not in profile.approved_claims")
    return problems


def run(ctx) -> None:
    """Run RSA duplicate, near-duplicate, headline count, missing-RSA, theme, Ad Strength, outcome and draft checks.

    Rules:   Findings only for active RSAs; paused inventory is observation. Duplicates, near-duplicates (Jaccard >
             0.70), unfilled capacity, Poor/Average Ad Strength and ad groups without an enabled RSA (manifest-complete
             ads only) are Info. Misleading/constraint-violating copy reaches Warning only via ai_review with
             proposal.evidence_ref. Outcome rates are descriptive, gated on ctx.mature and min_impressions/min_clicks;
             unknown Ad Strength is never Poor. rsa_draft reviews exist only for profile.rsa_draft_requests groups
             with an existing final URL (not_applicable when the key is unset).
    """
    inv = ctx.check("rsa_inventory", "RSA inventory left-joined to parents",
                    {**ADS_NEEDS, "ad_groups": ["id", "campaign_id", "status"], "campaigns": ["id", "status"]})
    later = (("ad_groups_without_rsa", "Enabled ad groups without an enabled RSA"),
             ("exact_duplicates", "Normalized exact duplicate headlines"),
             ("near_duplicates", "Near-duplicate headline token overlap"),
             ("headline_counts", "Supplied/unique headline counts vs current limits"),
             ("theme_review", "Headline theme coverage and claims review"),
             ("ad_strength", "Ad Strength category inventory"),
             ("rating_outcomes", "Observational outcomes by Ad Strength rating"),
             ("headline_proposals", "Headline concept proposals and routing"))
    if not ctx.table("ads") or ctx.table("ads").missing(ADS_NEEDS["ads"]):
        for cid, title in later:
            ctx.check(cid, title, ADS_NEEDS)
        _rsa_drafts(ctx)
        return
    groups, camps = _status_maps(ctx)
    rsas = sorted((r for r in ctx.rows("ads") if str(r.get("type") or "").upper() == "RESPONSIVE_SEARCH_AD"),
                  key=lambda r: str(r.get("id")))
    arrays = {str(r.get("id")): _texts(r.get("headlines")) for r in rsas}
    active = [r for r in rsas if _active(r, groups, camps)]
    if inv.runnable:
        by_status: dict[str, int] = {}
        for r in rsas:
            s = str(r.get("status") or "UNKNOWN").upper()
            by_status[s] = by_status.get(s, 0) + 1
        orphans = sorted(str(r.get("id")) for r in rsas if str(r.get("ad_group_id")) not in groups)
        if orphans:
            inv.partial(f"RSAs whose ad group is not in ad_groups: {orphans}")
        inv.observe("RSA inventory", rsa_total=len(rsas), by_status=by_status, active_rsas=len(active),
                    complete_arrays=sum(1 for v in arrays.values() if v is not None), array_denominator=len(rsas),
                    ad_groups=len(groups), campaigns=len(camps))
    unreadable = sorted(k for k, v in arrays.items() if v is None)

    # -- index #1: ad groups without an enabled RSA (step 1 left join)
    nog = ctx.check("ad_groups_without_rsa", "Enabled ad groups without an enabled RSA",
                    {**ADS_NEEDS, "ad_groups": ["id", "campaign_id", "status"], "campaigns": ["id", "status"]})
    if nog.runnable:
        ads_t = ctx.table("ads")
        if ads_t.complete is not True or ads_t.truncated:
            nog.partial("ads inventory not certified complete: absence of an RSA is not provable")
        else:
            with_rsa = {str(r.get("ad_group_id")) for r in rsas if str(r.get("status") or "").upper() == "ENABLED"}
            channel = {str(r.get("id")): str(r.get("channel_type") or "").upper() for r in ctx.rows("campaigns")}
            n = 0
            for g in sorted(ctx.rows("ad_groups"), key=lambda r: str(r.get("id"))):
                gid, cid = str(g.get("id")), str(g.get("campaign_id"))
                if str(g.get("status") or "").upper() != "ENABLED" or camps.get(cid) != "ENABLED":
                    continue
                if channel.get(cid) not in ("SEARCH", ""):
                    continue
                n += 1
                if gid in with_rsa:
                    continue
                nog.finding("ad_group_without_enabled_rsa", "Info", {"campaign_id": cid, "ad_group_id": gid},
                            f"Enabled ad group {gid} (campaign {cid}) has no enabled RSA in the complete ads inventory",
                            evidence={"rsa_ids_in_group": sorted(str(r.get("id")) for r in rsas
                                                                 if str(r.get("ad_group_id")) == gid),
                                      "ads_manifest": ads_t.manifest.get("completeness") if ads_t.manifest else None},
                            recommendation="Confirm whether the group is meant to serve; draft RSA copy with its owner.",
                            uncertainty="Inventory snapshot only; other ad formats or pending drafts may exist outside it.")
            nog.observe("Enabled Search ad groups checked for an enabled RSA", ad_groups=n)

    # -- step 2: exact normalized duplicates
    dup = ctx.check("exact_duplicates", "Normalized exact duplicate headlines", ADS_NEEDS)
    if unreadable:
        dup.partial(f"unreadable headline arrays for ads {unreadable}", ["ads:headlines"])
    n_dup = 0
    for r in active:
        heads = arrays[str(r.get("id"))]
        if not heads:
            continue
        by_norm: dict[str, list] = {}
        for i, t in enumerate(heads):
            by_norm.setdefault(_norm(t), []).append({"index": i, "text": t})
        groups_ = [v for k, v in sorted(by_norm.items()) if k and len(v) > 1]
        if groups_:
            n_dup += 1
            dup.finding("normalized_duplicate_headlines", "Info", _entity(r),
                        f"Ad {r.get('id')} has {len(groups_)} normalized duplicate headline group(s)",
                        evidence={"groups": groups_, "headlines_supplied": len(heads)},
                        calculation={"normalization": "NFKC, casefold, collapsed whitespace; punctuation kept"},
                        recommendation="Replace one copy with a distinct truthful concept if a business gap exists.",
                        uncertainty="Duplication reduces variety; no serving penalty or uplift is implied.")
    dup.observe("Active RSAs checked for exact duplicates", active_rsas=len(active), with_duplicates=n_dup)

    # -- step 3: near duplicates
    near = ctx.check("near_duplicates", "Near-duplicate headline token overlap", ADS_NEEDS)
    pairs = empty = 0
    for r in active:
        heads = arrays[str(r.get("id"))] or []
        toks = [set(_TOKEN.findall(_norm(t))) for t in heads]
        hits = []
        for i in range(len(heads)):
            for j in range(i + 1, len(heads)):
                if _norm(heads[i]) == _norm(heads[j]):
                    continue
                a, b = toks[i], toks[j]
                if not a or not b:
                    empty += 1
                    continue
                pairs += 1
                inter, union = len(a & b), len(a | b)
                jac = V.ratio(inter, union)
                if jac is not None and jac > JACCARD_CUTOFF:
                    diff = sorted(a ^ b)
                    hits.append({"indexes": [i, j], "texts": [heads[i], heads[j]], "intersection": inter,
                                 "union": union, "jaccard": jac, "differing_tokens": diff,
                                 "numeric_difference": any(any(ch.isdigit() for ch in t) for t in diff)})
        if hits:
            near.finding("near_duplicate_headlines", "Info", _entity(r),
                         f"Ad {r.get('id')} has {len(hits)} headline pair(s) with token overlap above {JACCARD_CUTOFF}",
                         evidence={"pairs": hits, "cutoff": JACCARD_CUTOFF},
                         calculation={"jaccard": "intersection / union of unique normalized \\w+ token sets"},
                         recommendation="Human review: numeric or negation differences may be intentional.",
                         uncertainty="Lexical overlap is a triage heuristic, not semantic sameness.")
    near.observe("Headline pairs compared", pairs=pairs, unavailable_empty_token_pairs=empty, cutoff=JACCARD_CUTOFF)

    # -- step 4: counts vs limits
    cnt = ctx.check("headline_counts", "Supplied/unique headline counts vs current limits", ADS_NEEDS)
    lim = _limits(ctx)
    over = []
    for r in active:
        heads = arrays[str(r.get("id"))]
        if heads is None:
            continue
        uniq = len({_norm(t) for t in heads if _norm(t)})
        wide = [{"index": i, "width": _width(t)} for i, t in enumerate(heads) if _width(t) > lim["headline_width"]]
        cnt.observe(f"Ad {r.get('id')} headline counts", ad_id=str(r.get("id")), supplied=len(heads), unique=uniq,
                    max_width=max((_width(t) for t in heads), default=None), limits=lim)
        if wide or len(heads) > lim["headlines_max"] or len(heads) < lim["headlines_min"]:
            over.append({"ad_id": str(r.get("id")), "supplied": len(heads), "over_width": wide})
        elif len(heads) < lim["headlines_max"]:
            cnt.finding("unfilled_optional_headline_capacity", "Info", _entity(r),
                        f"Ad {r.get('id')} uses {len(heads)} of {lim['headlines_max']} optional headline slots "
                        f"({uniq} unique)",
                        evidence={"supplied": len(heads), "unique": uniq, "limits": lim},
                        recommendation="Optional: add distinct truthful concepts only where a business gap exists.",
                        uncertainty="Fewer than the maximum is not evidence of delivery failure or lost performance.")
    if over:
        cnt.partial(f"exported headline arrays outside current limits (verify exporter/draft state): {over}")
    if unreadable:
        cnt.partial(f"unreadable headline arrays for ads {unreadable}", ["ads:headlines"])

    # -- step 5: theme/claim review
    theme = ctx.check("theme_review", "Headline theme coverage and claims review", ADS_NEEDS)
    context = {k: ctx.profile.get(k) for k in ("objectives", "brand_terms", "product_service_taxonomy",
                                                "intended_offer", "business_type") if ctx.profile.get(k)}
    if not context:
        theme.partial("profile business context missing: theme gaps undecidable", ["profile:objectives",
                                                                                   "profile:product_service_taxonomy"])
    objectives = ctx.profile.get("campaign_objectives") or {}
    for r in active:
        heads = arrays[str(r.get("id"))]
        if not heads:
            continue
        cid = str(r.get("campaign_id"))
        outcomes = {"no_business_gap": {"severity": None, "recommendation": "Keep; no headline change."},
                    "uncertain": {"severity": "Info", "recommendation": "Ask the owner for approved messages."}}
        if context:
            outcomes["theme_gap"] = {"severity": "Info", "recommendation":
                                     "Optional: add the proposed distinct truthful headline concepts."}
            outcomes["confirmed_claim_or_constraint_violation"] = {
                "severity": "Warning", "recommendation": "Owner review of the misleading/constraint-violating copy."}
        theme.review("headline_theme_review", _entity(r),
                     f"Tag the themes of ad {r.get('id')} headlines (brand, benefit, feature, evidence, offer, CTA, "
                     f"other). Is there a business-relevant gap or a confirmed misleading repeated claim?",
                     evidence={"headlines": heads, "final_url": r.get("final_url") or r.get("final_urls"),
                               "campaign_objective": next((v for k, v in objectives.items() if str(k) == cid), None),
                               "profile_context": context, "headline_width_limit": lim["headline_width"]},
                     outcomes=outcomes,
                     guidance="Quote headline text per theme; no universal theme quota. Urgency/social proof need "
                              "truthful business support. theme_gap: proposal.headlines (distinct, within width). "
                              "Warning: proposal.evidence_ref to the supplied constraint or claim evidence.")

    # -- step 6: Ad Strength inventory
    ast = ctx.check("ad_strength", "Ad Strength category inventory", {"ads": ["id", "type", "status", "ad_strength"]})
    if ast.runnable:
        dist: dict[str, int] = {}
        spend = {}
        mt = ctx.table("ad_metrics")
        if mt is not None and not mt.missing(["ad_id", "cost"]):
            for m in mt.rows:
                c = ctx.money(m.get("cost"))
                if c is not None:
                    spend[str(m.get("ad_id"))] = spend.get(str(m.get("ad_id")), 0.0) + c
        spend_by: dict[str, float] = {}
        unavailable = []
        for r in active:
            cat = str(r.get("ad_strength") or "").upper() or "UNAVAILABLE"
            dist[cat] = dist.get(cat, 0) + 1
            if str(r.get("id")) in spend:
                spend_by[cat] = spend_by.get(cat, 0.0) + spend[str(r.get("id"))]
            if cat == "UNAVAILABLE":
                unavailable.append(str(r.get("id")))
            elif cat in ("POOR", "AVERAGE"):
                ast.finding("ad_strength_poor_or_average", "Info", _entity(r),
                            f"Ad {r.get('id')} Ad Strength snapshot is {cat}",
                            evidence={"ad_strength": cat, "snapshot": ctx.snapshot,
                                      "window_cost": spend.get(str(r.get("id")))},
                            recommendation="Treat as a creative diagnostic; do not replace a performing ad for its label.",
                            uncertainty="Ad Strength is not proof of a serving penalty or causal performance.")
        total_spend = sum(spend_by.values())
        ast.observe("Ad Strength distribution (active RSAs)", counts=dist, count_denominator=len(active),
                    count_shares={k: V.ratio(v, len(active)) for k, v in dist.items()},
                    spend=spend_by, spend_denominator=total_spend if spend_by else None,
                    spend_shares={k: V.ratio(v, total_spend) for k, v in spend_by.items()}, snapshot=ctx.snapshot)
        if unavailable:
            ast.partial(f"Ad Strength unavailable for ads {unavailable} (unknown is not Poor)", ["ads:ad_strength"])

    # -- step 7: observational outcomes by rating
    out = ctx.check("rating_outcomes", "Observational outcomes by Ad Strength rating",
                    {"ads": ["id", "ad_strength"], "ad_metrics": METRIC_COLS})
    if out.runnable:
        if ctx.mature is not True:
            out.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; descriptive totals only")
        min_imp, min_clk = ctx.params.get("min_impressions"), ctx.params.get("min_clicks")
        langs = {str(c.get("id")): c.get("languages") for c in ctx.rows("campaigns")}
        by_ad = {str(r.get("id")): r for r in active}
        cohorts: dict[tuple, list] = {}
        seen = set()
        for m in sorted(ctx.rows("ad_metrics"), key=lambda r: str(r.get("ad_id"))):
            aid = str(m.get("ad_id"))
            r = by_ad.get(aid)
            if r is None or aid in seen:
                if aid in seen:
                    out.partial(f"duplicate ad_metrics rows for ad {aid}; excluded")
                continue
            seen.add(aid)
            vals = [V.num(m.get("impressions")), V.num(m.get("clicks")), V.num(m.get("conversions"))]
            if None in vals:
                out.partial(f"ad {aid}: unknown metrics excluded")
                continue
            cid = str(r.get("campaign_id"))
            role = (next((v for k, v in (ctx.profile.get("campaign_objectives") or {}).items() if str(k) == cid), None)
                    or {}).get("role") if isinstance(ctx.profile.get("campaign_objectives"), dict) else None
            key = (str(role), str(langs.get(cid)), str(r.get("ad_strength") or "UNAVAILABLE").upper())
            acc = cohorts.setdefault(key, [0.0, 0.0, 0.0, 0])
            for i, v in enumerate(vals):
                acc[i] += v
            acc[3] += 1
        for (role, lang, cat), (imp, clk, conv, n) in sorted(cohorts.items()):
            out.observe(f"Rating cohort {cat} (role {role}, language {lang})", role=role, language=lang, rating=cat,
                        ads=n, impressions=imp, clicks=clk, conversions=conv,
                        ctr=V.ratio(clk, imp) if ctx.mature is True and imp >= min_imp.value else None,
                        cvr=V.ratio(conv, clk) if ctx.mature is True and clk >= min_clk.value else None,
                        min_impressions=min_imp.value, min_clicks=min_clk.value,
                        note="observational; compare ratings only when both cohorts show a rate")

    # -- step 8: proposals and routing
    prop = ctx.check("headline_proposals", "Headline concept proposals and routing", ADS_NEEDS)
    prop.observe("Proposal routing", theme_reviews=sum(1 for x in ctx.result.reviews
                                                        if x.condition_key == "headline_theme_review"),
                 descriptions_owner="skill-026", pins_owner="skill-028", causal_tests_owner="skill-032")
    _rsa_drafts(ctx)


def verify(ctx, item, decision) -> list[str]:
    """Re-check AI proposals for theme gaps, Warning evidence and requested RSA drafts.

    Rules:   Warning needs proposal.evidence_ref; theme_gap headlines must fit the width and be new/distinct.
             rsa_draft draft_proposed must pass every DRAFT_LIMITS, pin, insertion-token, duplicate, final-URL,
             competitor/excluded-term and approved-claims rule (module rules); no_draft needs only a rationale.
    """
    outcome, p = decision.get("outcome"), decision.get("proposal") or {}
    if item.condition_key == "rsa_draft":
        return _verify_draft(ctx, item, decision.get("proposal")) if outcome == "draft_proposed" else []
    if outcome == "confirmed_claim_or_constraint_violation":
        return [] if p.get("evidence_ref") else ["Warning outcome needs proposal.evidence_ref to supplied evidence"]
    if outcome != "theme_gap":
        return []
    heads = p.get("headlines") or []
    if not heads or not all(isinstance(h, str) and h.strip() for h in heads):
        return ["theme_gap needs proposal.headlines (non-empty strings)"]
    width = item.evidence.get("headline_width_limit") or RSA_LIMITS["headline_width"]
    existing = {_norm(t) for t in item.evidence.get("headlines") or []}
    problems, seen = [], set()
    for h in heads:
        n = _norm(h)
        if _width(h) > width:
            problems.append(f"'{h}' exceeds {width} display columns")
        if n in existing or n in seen:
            problems.append(f"'{h}' duplicates an existing or proposed headline after normalization")
        seen.add(n)
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
