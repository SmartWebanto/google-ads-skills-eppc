"""check.py — skill-033 deterministic keyword-insertion token, fallback, rendering and authorization screens.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-033-dynamic-keyword-insertion-review/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   DKI token = {keyword[:fallback]} with a case-insensitive 'keyword' name; other brace syntax
         (CUSTOMIZER., COUNTDOWN(, LOCATION(, =) is counted as another customizer, never as DKI.
         Case variants: keyword=lower, Keyword=sentence, KeyWord=title, KEYWord=first word caps + title,
         KeyWORD=first title + rest caps, KEYWORD=all caps; any other casing is a suspected (not confirmed) error.
         Suspected syntax errors (unbalanced braces, missing/empty fallback, unknown variant) → Info; Warning only
         via ai_review backed by an external/dki_review Ads preview row for that ad.
         Renderings use the triggering KEYWORD text of enabled keywords in the same campaign/ad group — never
         search-query text; broad match alone is not unsafe.
         Field limits: RSA headline 30, description 90, path 15 characters (current RSA limits) unless
         profile.field_char_limits {ad_type: {field: n}} overrides; unknown ad types skip length checks (partial).
         A keyword that does not fit uses the fallback: valid fallback → Info only (expected behavior).
         Competitor/sensitive terms come only from profile.competitor_terms / profile.sensitive_insertion_terms;
         a hit is Info (authorization review); an authorized dki_review row (authorization_ref) clears it.
         verify(): Warning proposals must keep a DKI token with a non-empty fallback that fits the field limit;
         DKI removal or keyword exclusion actions are rejected (recommend-only).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import json
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

SKILL = "skill-033-dynamic-keyword-insertion-review"
VERSION = "1.0.0"

REVIEW = "external/dki_review"
REVIEW_COLS = ["ad_id", "field", "keyword_id", "review_at", "rendered_preview", "fallback_preview", "preview_source",
               "allowed_term_status", "authorization_ref"]
RSA_LIMITS = {"RESPONSIVE_SEARCH_AD": {"headline": 30, "description": 90, "path": 15}}
_BRACE = re.compile(r"\{([^{}]*)\}")
_DKI = re.compile(r"^\s*(keyword)\s*(?::(.*))?$", re.IGNORECASE | re.DOTALL)
VARIANTS = {"keyword": "lower", "Keyword": "sentence", "KeyWord": "title", "KEYWord": "caps_first_title_rest",
            "KeyWORD": "title_first_caps_rest", "KEYWORD": "upper"}


def _texts(v) -> list[str]:
    if isinstance(v, list):
        data = v
    else:
        s = str(v or "").strip()
        if not s:
            return []
        data = None
        if s.startswith("["):
            try:
                data = json.loads(s)
            except ValueError:
                data = None
        if not isinstance(data, list):
            return [p.strip() for p in s.split(" | ") if p.strip()]
    return [str(x.get("text") if isinstance(x, dict) else x) for x in data if x is not None]


def _render_kw(text: str, style: str) -> str:
    words = str(text).lower().split()
    if not words:
        return ""
    if style == "lower":
        return " ".join(words)
    if style == "sentence":
        return " ".join([words[0].capitalize()] + words[1:])
    if style == "title":
        return " ".join(w.capitalize() for w in words)
    if style == "caps_first_title_rest":
        return " ".join([words[0].upper()] + [w.capitalize() for w in words[1:]])
    if style == "title_first_caps_rest":
        return " ".join([words[0].capitalize()] + [w.upper() for w in words[1:]])
    return " ".join(w.upper() for w in words)


def tokens(text: str) -> list[dict]:
    """All brace tokens in one field with DKI classification."""
    out = []
    for m in _BRACE.finditer(text):
        d = _DKI.match(m.group(1))
        if d:
            name = d.group(1)
            out.append({"kind": "dki", "raw": m.group(0), "variant": name, "style": VARIANTS.get(name),
                        "fallback": d.group(2), "span": [m.start(), m.end()]})
        else:
            out.append({"kind": "other_customizer", "raw": m.group(0)})
    return out


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
        if depth < 0 or depth > 1:
            return False
    return depth == 0


def _render(text: str, tok: dict, value: str) -> str:
    s, e = tok["span"]
    return text[:s] + value + text[e:]


def _limit(ctx, ad_type: str, field: str) -> int | None:
    over = ctx.profile.get("field_char_limits") or {}
    lim = (over.get(ad_type) or {}).get(field) if isinstance(over, dict) else None
    if lim is None:
        lim = RSA_LIMITS.get(ad_type, {}).get(field)
    return V.integer(lim)


def _contains(text: str, term: str) -> bool:
    t, q = V.norm_text(term).split(), V.norm_text(text).split()
    return bool(t) and any(q[i:i + len(t)] == t for i in range(len(q) - len(t) + 1))


def run(ctx) -> None:
    """Run DKI extraction, syntax, keyword-join, rendering, length/fallback, message and authorization checks.

    Rules:   Only ENABLED ads are scanned; no DKI token → later checks not applicable. Syntax/length suspicions,
             brand-case changes and unauthorized competitor/sensitive insertions are Info; Warning only via ai_review
             ('confirmed_invalid' needs an external/dki_review row for invalid_template, 'materially_misleading' needs
             a preview). Renderings use enabled keyword text, never queries; no DKI removal/keyword exclusion.
    """
    ex = ctx.check("token_extraction", "Insertion tokens by exact ad field, variant and fallback",
                   {"ads": ["id", "campaign_id", "ad_group_id", "type", "status", "headlines", "descriptions"]})
    later = (("syntax_validity", "Balanced syntax and fallback presence"),
             ("keyword_join", "Eligible triggering keywords in the same ad group"),
             ("capitalization_preview", "Rendered capitalization variants in field context"),
             ("length_fallback", "Oversized insertions and fallback fit"),
             ("rendered_message_review", "Grammar, sensitive claims and relevance of renderings"),
             ("competitor_authorization", "Competitor/sensitive insertion authorization"),
             ("correction_proposals", "Owner-reviewed template/fallback corrections"))
    if not ex.runnable:
        for cid, t in later:
            ctx.check(cid, t).skip("ad templates unavailable", ex.missing)
        return
    ads_t = ctx.table("ads")
    fields_spec = [("headline", "headlines"), ("description", "descriptions")] + \
        [("path", c) for c in ("path1", "path2") if c in ads_t.columns]
    dki: list[dict] = []
    other = 0
    for a in sorted(ctx.rows("ads"), key=lambda r: str(r.get("id"))):
        if str(a.get("status") or "").upper() != "ENABLED":
            continue
        for field, col in fields_spec:
            texts = _texts(a.get(col)) if field != "path" else ([str(a.get(col))] if a.get(col) else [])
            for i, t in enumerate(texts):
                toks = tokens(t)
                other += sum(1 for k in toks if k["kind"] == "other_customizer")
                ds = [k for k in toks if k["kind"] == "dki"]
                if ds or ("{" in t or "}" in t) and not _balanced(t):
                    dki.append({"ad_id": str(a.get("id")), "campaign_id": str(a.get("campaign_id")),
                                "ad_group_id": str(a.get("ad_group_id")), "type": str(a.get("type") or "").upper(),
                                "field": field, "column": col, "index": i, "text": t, "tokens": ds,
                                "balanced": _balanced(t)})
    ex.observe("Keyword-insertion templates extracted", dki_fields=len(dki),
               ads_with_dki=len({d["ad_id"] for d in dki}), other_customizer_tokens=other,
               fields_scanned=[c for _, c in fields_spec])
    if not dki:
        for cid, t in later:
            ctx.check(cid, t, applicable=False, na_reason="no enabled ad contains keyword-insertion syntax")
        return

    rev_t = ctx.table(REVIEW)
    reviews_by_ad: dict[str, list[dict]] = {}
    if rev_t is not None and not rev_t.missing(REVIEW_COLS):
        for r in ctx.rows(REVIEW):
            reviews_by_ad.setdefault(str(r.get("ad_id")), []).append(r)

    def ent(d):
        return {"campaign_id": d["campaign_id"], "ad_group_id": d["ad_group_id"], "ad_id": d["ad_id"],
                "field": d["field"], "index": d["index"]}

    # step 2
    syn = ctx.check("syntax_validity", later[0][1], {"ads": ["headlines", "descriptions"]})
    if not reviews_by_ad:
        syn.partial("no Ads preview/diagnosis rows: suspected errors cannot be confirmed",
                    [f"{REVIEW} (file)"] if rev_t is None else [f"{REVIEW}:{c}" for c in rev_t.missing(REVIEW_COLS)])
    for d in dki:
        issues = []
        if not d["balanced"]:
            issues.append("unbalanced or nested braces")
        for k in d["tokens"]:
            if k["fallback"] is None or not k["fallback"].strip():
                issues.append(f"{k['raw']}: missing/empty fallback")
            if k["style"] is None:
                issues.append(f"{k['raw']}: unsupported case variant '{k['variant']}'")
        if not issues:
            continue
        previews = [{c: r.get(c) for c in REVIEW_COLS} for r in reviews_by_ad.get(d["ad_id"], [])
                    if V.norm_text(r.get("field")) in (d["field"], d["column"], f"{d['field']}{d['index'] + 1}")]
        ev = {"text": d["text"], "issues": issues, "previews": previews}
        prov = syn.finding("suspected_template_error", "Info", ent(d),
                           f"Ad {d['ad_id']} {d['field']} {d['index'] + 1}: suspected insertion syntax issue "
                           f"({'; '.join(issues)})", evidence=ev,
                           recommendation="Confirm with an Ads preview/policy diagnosis before claiming delivery failure.",
                           uncertainty="Parse heuristics; the platform may accept or normalize the template.")
        if previews:
            syn.review("invalid_template", ent(d), f"Does the Ads preview confirm the template in ad {d['ad_id']} "
                       f"{d['field']} {d['index'] + 1} is invalid or renders a broken message?", evidence=ev,
                       provisional=prov,
                       outcomes={"confirmed_invalid": {"severity": "Warning", "recommendation":
                                                       "Correct the template/fallback (see proposal)."},
                                 "valid": {"severity": None, "recommendation": "No action."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request a fresh preview."}},
                       guidance="confirmed_invalid needs proposal {proposed_template} keeping a DKI token and fallback.")

    # step 3
    kj = ctx.check("keyword_join", later[1][1],
                   {"keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type", "status"]})
    kws: dict[tuple[str, str], list[dict]] = {}
    if kj.runnable:
        for k in sorted(ctx.rows("keywords"), key=lambda r: str(r.get("id"))):
            if str(k.get("status") or "").upper() == "ENABLED":
                kws.setdefault((str(k.get("campaign_id")), str(k.get("ad_group_id"))), []).append(k)
        for key in sorted({(d["campaign_id"], d["ad_group_id"]) for d in dki}):
            ks = kws.get(key, [])
            kj.observe(f"Ad group {key[1]}: {len(ks)} enabled triggering keyword(s) for insertion",
                       campaign_id=key[0], ad_group_id=key[1], keywords=len(ks),
                       broad=sum(1 for k in ks if str(k.get("match_type") or "").upper() == "BROAD"),
                       note="DKI inserts the keyword text, not the query" if ks else "fallback always rendered")
        if ctx.table("keywords").complete is not True:
            kj.partial("keywords not manifest-complete: preview matrix may miss keywords")

    # steps 4-5
    cap = ctx.check("capitalization_preview", later[2][1], {"keywords": ["id", "text"]} if not kj.runnable else {})
    ln = ctx.check("length_fallback", later[3][1], {"keywords": ["id", "text"]} if not kj.runnable else {})
    brand_case = [str(b) for b in (ctx.profile.get("brand_case") or []) if b]
    matrix: dict[tuple, list[dict]] = {}
    if kj.runnable:
        unknown_limit = set()
        for d in dki:
            lim = _limit(ctx, d["type"], d["field"])
            if lim is None:
                unknown_limit.add(f"{d['type']}:{d['field']}")
            for tok in d["tokens"]:
                if tok["style"] is None:
                    continue
                rows, over = [], []
                for k in kws.get((d["campaign_id"], d["ad_group_id"]), []):
                    txt = _render(d["text"], tok, _render_kw(k.get("text"), tok["style"]))
                    fits = None if lim is None else len(txt) <= lim
                    rows.append({"keyword_id": k.get("id"), "keyword": k.get("text"), "rendered": txt,
                                 "length": len(txt), "fits": fits})
                    if fits is False:
                        over.append(k.get("id"))
                    for b in brand_case:
                        if b.lower() in txt.lower() and b not in txt:
                            cap.finding("brand_case_altered", "Info", {**ent(d), "keyword_id": k.get("id")},
                                        f"Rendering '{txt}' changes approved brand case '{b}'",
                                        evidence={"template": d["text"], "variant": tok["variant"], "brand_case": b},
                                        recommendation="Consider a case variant that preserves the brand spelling.",
                                        uncertainty="Preview computed locally, not an Ads preview.")
                fb = tok["fallback"]
                fb_txt = _render(d["text"], tok, fb) if fb else None
                matrix[(d["ad_id"], d["field"], d["index"], tok["raw"])] = rows
                cap.observe(f"Ad {d['ad_id']} {d['field']} {d['index'] + 1} {tok['raw']}: {len(rows)} rendering(s)",
                            **ent(d), variant=tok["variant"], style=tok["style"], renderings=rows[:25],
                            fallback_rendering=fb_txt, preview_source="computed (not Ads preview)")
                if not over or lim is None:
                    continue
                fb_fits = fb_txt is not None and len(fb_txt) <= lim
                ev = {"template": d["text"], "limit": lim, "limit_source": "profile.field_char_limits" if
                      (ctx.profile.get("field_char_limits") or {}).get(d["type"]) else "current RSA limit",
                      "oversized_keyword_ids": over, "fallback": fb, "fallback_rendering": fb_txt,
                      "fallback_length": len(fb_txt) if fb_txt else None}
                if fb_fits:
                    ln.finding("oversized_keyword_valid_fallback", "Info", ent(d),
                               f"{len(over)} keyword(s) exceed {lim} chars in ad {d['ad_id']} {d['field']} "
                               f"{d['index'] + 1}; the fallback ({len(fb_txt)} chars) is shown instead",
                               evidence=ev, recommendation="Expected behavior; check the fallback reads coherently.",
                               uncertainty="Character counting ignores platform-specific width rules.")
                else:
                    prov = ln.finding("fallback_exceeds_limit", "Info", ent(d),
                                      f"Ad {d['ad_id']} {d['field']} {d['index'] + 1}: fallback rendering "
                                      f"{'missing' if fb_txt is None else f'{len(fb_txt)} chars'} vs limit {lim}",
                                      evidence=ev, recommendation="Confirm with an Ads preview.",
                                      uncertainty="The platform may reject or truncate; not verified.")
                    ln.review("fallback_exceeds_limit", ent(d), f"Is the fallback of ad {d['ad_id']} {d['field']} "
                              f"{d['index'] + 1} invalid for oversized keywords?", evidence=ev, provisional=prov,
                              outcomes={"confirmed_invalid": {"severity": "Warning", "recommendation":
                                                              "Shorten the fallback (see proposal)."},
                                        "valid": {"severity": None, "recommendation": "No action."},
                                        "uncertain": {"severity": "Info", "recommendation": "Request an Ads preview."}},
                              guidance="confirmed_invalid needs proposal {proposed_template} whose fallback fits.")
        for u in sorted(unknown_limit):
            ln.partial(f"no character limit known for {u}: supply profile.field_char_limits")
    else:
        cap.skip("keywords unavailable", kj.missing)
        ln.skip("keywords unavailable", kj.missing)

    # step 6
    rm = ctx.check("rendered_message_review", later[4][1], {"keywords": ["id", "text"]} if not kj.runnable else {})
    if not kj.runnable:
        rm.skip("keywords unavailable", kj.missing)
    else:
        if not reviews_by_ad:
            rm.partial("no Ads previews: rendered-message issues can only be suspected (Info)")
        for ad_id in sorted({d["ad_id"] for d in dki}):
            ds = [d for d in dki if d["ad_id"] == ad_id]
            examples = {f"{k[1]} {k[2] + 1} {k[3]}": v[:15] for k, v in sorted(matrix.items()) if k[0] == ad_id}
            if not any(examples.values()):
                continue
            has_preview = bool(reviews_by_ad.get(ad_id))
            outcomes = {"acceptable": {"severity": None, "recommendation": "No action."},
                        "uncertain": {"severity": "Info", "recommendation": "Ask the owner / obtain a preview."}}
            if has_preview:
                outcomes["materially_misleading"] = {"severity": "Warning", "recommendation":
                                                     "Correct the fallback/template; keep mandatory qualifications."}
            else:
                outcomes["misleading_suspected"] = {"severity": "Info", "recommendation":
                                                    "Obtain an Ads preview before correcting."}
            rm.review("rendered_message", {"campaign_id": ds[0]["campaign_id"], "ad_group_id": ds[0]["ad_group_id"],
                                           "ad_id": ad_id},
                      f"Do any keyword renderings of ad {ad_id} read ungrammatically, make a sensitive claim or "
                      f"misrepresent the offer?",
                      evidence={"renderings": examples, "previews": reviews_by_ad.get(ad_id, []),
                                "excluded_intents": ctx.profile.get("excluded_intents"),
                                "objectives": ctx.profile.get("objectives")},
                      outcomes=outcomes,
                      guidance="Judge the complete rendered text with literal examples; respect local language, brand "
                               "case and acronyms. Warning outcomes need proposal {field, index, proposed_template}.")

    # step 7
    ca = ctx.check("competitor_authorization", later[5][1], {"keywords": ["id", "text"]} if not kj.runnable else {})
    if not kj.runnable:
        ca.skip("keywords unavailable", kj.missing)
    else:
        comp = [t for t in (ctx.profile.get("competitor_terms") or []) if t]
        sens = [t for t in (ctx.profile.get("sensitive_insertion_terms") or []) if t]
        if ctx.profile.get("competitor_terms") is None:
            ca.partial("profile.competitor_terms not declared: competitor status unknown")
        auth = {(str(r.get("ad_id")), str(r.get("keyword_id"))) for rs in reviews_by_ad.values() for r in rs
                if r.get("authorization_ref") and V.norm_text(r.get("allowed_term_status")) in
                ("authorized", "allowed", "approved")}
        hits = 0
        for d in dki:
            for k in kws.get((d["campaign_id"], d["ad_group_id"]), []):
                terms = [("competitor", t) for t in comp if _contains(k.get("text"), t)] + \
                        [("sensitive", t) for t in sens if _contains(k.get("text"), t)]
                if not terms:
                    continue
                hits += 1
                e = {**ent(d), "keyword_id": k.get("id")}
                if (d["ad_id"], str(k.get("id"))) in auth:
                    ca.observe(f"Keyword {k.get('id')} insertion authorized by dki_review", **e)
                    continue
                ca.finding("potential_restricted_insertion", "Info", e,
                           f"Ad {d['ad_id']} may insert '{k.get('text')}' ({', '.join(f'{a}:{b}' for a, b in terms)})",
                           evidence={"keyword": k.get("text"), "terms": terms, "template": d["text"]},
                           recommendation="Route to the responsible owner for authorization/policy review.",
                           uncertainty="A name match proves neither ownership, prohibition nor legal clearance.")
        ca.observe("Competitor/sensitive term screen over DKI ad groups", hits=hits,
                   competitor_terms=len(comp), sensitive_terms=len(sens))

    cp = ctx.check("correction_proposals", later[6][1])
    cp.observe("Correction proposals are owner-reviewed; no DKI removal or keyword exclusion",
               suspected=sum(1 for f in ctx.result.findings if f.condition_key in
                             ("suspected_template_error", "fallback_exceeds_limit")),
               pending_reviews=len(ctx.result.reviews))


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning proposals keep a DKI token with a fitting fallback."""
    if decision.get("outcome") not in ("confirmed_invalid", "materially_misleading"):
        return []
    p = decision.get("proposal") or {}
    problems = []
    if str(p.get("action") or "").lower() in ("remove_dki", "exclude_keyword", "pause", "remove"):
        problems.append("DKI removal/keyword exclusion is not proposed automatically (recommend-only)")
    tpl = str(p.get("proposed_template") or "")
    if not tpl:
        return problems + ["proposal.proposed_template required"]
    if not _balanced(tpl):
        problems.append("proposed_template has unbalanced braces")
    ds = [k for k in tokens(tpl) if k["kind"] == "dki"]
    if not ds:
        problems.append("proposed_template must keep a keyword-insertion token")
    for k in ds:
        if not (k["fallback"] or "").strip():
            problems.append(f"{k['raw']}: fallback required")
        elif k["style"] is None:
            problems.append(f"{k['raw']}: unsupported case variant")
        else:
            lim = V.integer(item.evidence.get("limit"))
            if lim is not None and len(_render(tpl, k, k["fallback"])) > lim:
                problems.append(f"fallback rendering exceeds {lim} characters")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
