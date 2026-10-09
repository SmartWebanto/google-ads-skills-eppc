"""check.py — skill-038 deterministic editorial screens and field-referenced review items for ad copy.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-038-spelling-editorial-error-detection/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #86 Check ad copy for typos using Bing spellchecker API (Entazis) — clean-room: the external spell-check
           API call is refused (no network/third-party queries); replaced by client-approved lists
           (profile.editorial_misspellings, editorial_brief preferred spellings) and field-referenced AI review
rules:   Visible copy excludes brace syntax ({KeyWord:..}, {CUSTOMIZER..}, {COUNTDOWN..}); tokens are preserved for
         proposals and verify() rejects corrections that change them.
         Documented style inconsistency (Warning, deterministic): copy contains a brief preferred_spelling
         case-insensitively at word boundaries but with different casing, the brief row is valid at as_of and its
         language matches the ad's campaign language (or is blank).
         profile.editorial_misspellings {wrong: right} hits and all spelling/grammar judgments are ai_review;
         Warning outcomes exist only when an editorial brief covers the ad's language, otherwise Info at most.
         ALL-CAPS screen: alphabetic words of >= 5 letters not in brand_terms / brief exceptions /
         profile.approved_acronyms; repeated punctuation = same mark twice or more. Both are suspicions → review.
         Claim terms come only from profile.claim_terms; hits are Info referrals unless a brief claim_support_ref
         covers the term. Platform policy topics are reported as platform status (Info, owner skill-037).
         Display paths only from custom/ad_editorial_fields; never derived from final URLs.
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

SKILL = "skill-038-spelling-editorial-error-detection"
VERSION = "1.0.0"

FIELDS = "custom/ad_editorial_fields"
BRIEF = "external/editorial_brief"
_BRACE = re.compile(r"\{[^{}]*\}")
_WORD = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
_REPEAT = re.compile(r"([!?.,;:])\1+")
CAPS_MIN = 5


def _cols(ctx, key, spec) -> dict[str, str]:
    t = ctx.table(key)
    present = set(t.columns) if t else set()
    out = {}
    for c in spec:
        alts = (c,) if isinstance(c, str) else c
        out[alts[0]] = next((a for a in alts if a in present), alts[0])
    return out


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


def visible(text: str) -> str:
    return " ".join(_BRACE.sub(" ", text).split())


def _lang(v) -> str:
    return str(v or "").strip().lower().replace("_", "-").split("-")[0]


def _find_ci(text: str, term: str) -> list[str]:
    """Occurrences of term (case-insensitive, word-bounded) as written in text."""
    pat = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
    return [m.group(0) for m in pat.finditer(text)]


def run(ctx) -> None:
    """Run language coverage, spelling, grammar, ALL-CAPS/punctuation, claim and policy-topic screens on ad copy.

    Rules:   Missing ad copy skips all checks; brace tokens are excluded from visible copy and must survive proposals.
             documented_style_inconsistency (brief preferred_spelling, different casing, valid at as_of, language match)
             is the only deterministic Warning. Misspellings, grammar and ALL-CAPS/punctuation suspicions are
             provisional Info + ai_review; Warning outcomes exist only where a brief covers the ad language. Claim terms
             and policy topics are Info referrals.
    """
    ex = ctx.check("text_extraction", "Visible copy by field/index, dynamic syntax separated",
                   {"ads": ["id", "campaign_id", "ad_group_id", "status", "headlines", "descriptions"]})
    later = (("language_resolution", "Language/locale from brief and campaign context"),
             ("spelling_screen", "Brief spellings and approved misspelling list"),
             ("grammar_review", "Spelling/grammar judgment per ad"),
             ("punctuation_casing", "Repeated punctuation and unusual casing"),
             ("claims_separation", "Claims kept separate from editorial errors"),
             ("platform_policy", "Platform-confirmed policy topics"),
             ("display_paths", "Display paths from the editorial field export"),
             ("correction_proposals", "Minimal copy/path corrections"))
    if not ex.runnable:
        for cid, t in later:
            ctx.check(cid, t).skip("ad copy unavailable", ex.missing)
        return
    ads: dict[str, dict] = {}
    dyn = 0
    for a in sorted(ctx.rows("ads"), key=lambda r: str(r.get("id"))):
        if str(a.get("status") or "").upper() != "ENABLED":
            continue
        fields = []
        for fname, col in (("headline", "headlines"), ("description", "descriptions")):
            for i, t in enumerate(_texts(a.get(col))):
                toks = _BRACE.findall(t)
                dyn += len(toks)
                fields.append({"field": fname, "index": i, "raw": t, "visible": visible(t), "dynamic": toks})
        ads[str(a.get("id"))] = {"row": a, "fields": fields, "campaign_id": str(a.get("campaign_id")),
                                 "ad_group_id": str(a.get("ad_group_id"))}
    ex.observe("Enabled ad copy extracted", ads=len(ads), fields=sum(len(x["fields"]) for x in ads.values()),
               dynamic_tokens_separated=dyn)

    def ent(aid, f=None):
        x = ads[aid]
        e = {"campaign_id": x["campaign_id"], "ad_group_id": x["ad_group_id"], "ad_id": aid}
        if f is not None:
            e.update({"field": f["field"], "index": f["index"]})
        return e

    # step 2
    b = _cols(ctx, BRIEF, ["locale", "language", "term_or_rule_id", "preferred_spelling",
                           ("exception", "term_exception", "brand_acronym_industry_term_exception"), "style_rule",
                           "claim_support_ref", "valid_from", "valid_to"])
    lr = ctx.check("language_resolution", later[0][1], {BRIEF: [b["locale"], b["language"], b["term_or_rule_id"]],
                                                         "campaigns": ["id", "languages"]})
    camp_lang = {str(c.get("id")): sorted({_lang(x) for x in V.split_list(c.get("languages"), (" | ", ";", "|", ","))})
                 for c in ctx.rows("campaigns")} if ctx.table("campaigns") and "languages" in ctx.table("campaigns").columns else {}
    as_of = ctx.as_of or ctx.snapshot
    brief = []
    for r in ctx.rows(BRIEF):
        vf, vt = V.parse_date(r.get(b["valid_from"])), V.parse_date(r.get(b["valid_to"]))
        if as_of and ((vf and vf > as_of) or (vt and vt < as_of)):
            continue
        brief.append(r)
    brief_langs = {_lang(r.get(b["language"]) or r.get(b["locale"])) for r in brief} - {""}
    covered: dict[str, bool] = {}
    if lr.runnable:
        for aid, x in sorted(ads.items()):
            langs = camp_lang.get(x["campaign_id"], [])
            covered[aid] = bool(langs) and all(l in brief_langs for l in langs)
        missing = sorted({(ads[a]["campaign_id"], tuple(camp_lang.get(ads[a]["campaign_id"], [])))
                          for a, ok in covered.items() if not ok})
        for cid, langs in missing:
            lr.finding("unsupported_language_review", "Info", {"campaign_id": cid},
                       f"Campaign {cid} languages {list(langs) or 'unknown'} not covered by the editorial brief "
                       f"({sorted(brief_langs)})", evidence={"campaign_languages": list(langs),
                                                             "brief_languages": sorted(brief_langs)},
                       recommendation="Supply brief rows or a reviewer for this language before confirming errors.",
                       uncertainty="Account language does not certify every ad's language.")
        lr.observe("Brief language coverage", brief_languages=sorted(brief_langs), brief_rows_valid=len(brief),
                   ads_covered=sum(1 for v in covered.values() if v), ads_total=len(ads))

    exceptions = {str(t).lower() for t in (ctx.profile.get("brand_terms") or []) if t} | \
                 {str(t).lower() for t in (ctx.profile.get("approved_acronyms") or []) if t} | \
                 {str(r.get(b["preferred_spelling"]) or "").lower() for r in brief if r.get(b["exception"])} - {""}

    # step 3
    sp = ctx.check("spelling_screen", later[1][1])
    bt = ctx.table(BRIEF)
    need = [b["preferred_spelling"], b["language"], b["valid_from"], b["valid_to"]]
    brief_gap = [f"{BRIEF} (file)"] if bt is None else [f"{BRIEF}:{c}" for c in bt.missing(need)]
    miss = ctx.profile.get("editorial_misspellings") or {}
    if brief_gap and not (isinstance(miss, dict) and miss):
        sp.skip("no editorial brief spellings and no profile.editorial_misspellings", brief_gap)
    elif brief_gap:
        sp.partial("editorial brief unavailable: only profile.editorial_misspellings screened", brief_gap)
    if not brief_gap:
        for aid, x in sorted(ads.items()):
            langs = camp_lang.get(x["campaign_id"], [])
            for r in brief:
                term = str(r.get(b["preferred_spelling"]) or "").strip()
                rl = _lang(r.get(b["language"]))
                if not term or (rl and langs and rl not in langs):
                    continue
                for f in x["fields"]:
                    bad = sorted({h for h in _find_ci(f["visible"], term) if h != term})
                    if not bad:
                        continue
                    sp.finding("documented_style_inconsistency", "Warning", {**ent(aid, f), "rule": r.get(b["term_or_rule_id"])},
                               f"Ad {aid} {f['field']} {f['index'] + 1} writes {bad} where the brief prescribes '{term}'",
                               evidence={"original": f["raw"], "found": bad, "preferred_spelling": term,
                                         "rule_id": r.get(b["term_or_rule_id"]), "brief_language": rl or None,
                                         "style_rule": r.get(b["style_rule"])},
                               recommendation=f"Replace with '{term}' after owner confirmation; keep dynamic syntax.",
                               uncertainty="Brief rule applied literally; intentional exceptions need the owner.")
    if isinstance(miss, dict) and miss:
        for aid, x in sorted(ads.items()):
            for f in x["fields"]:
                hits = {w: str(miss[w]) for w in sorted(miss) if _find_ci(f["visible"], str(w))}
                if not hits:
                    continue
                ev = {"original": f["raw"], "suspects": hits, "language_covered_by_brief": covered.get(aid, False),
                      "source": "profile.editorial_misspellings"}
                prov = sp.finding("suspected_misspelling", "Info", ent(aid, f),
                                  f"Ad {aid} {f['field']} {f['index'] + 1}: suspected misspelling {sorted(hits)}",
                                  evidence=ev, recommendation="Confirm in context before correcting.",
                                  uncertainty="List match; proper names and regional variants may be valid.")
                sp.review("confirmed_language_error", ent(aid, f),
                          f"Is {sorted(hits)} in '{f['visible']}' a real spelling error in this locale?",
                          evidence=ev, provisional=prov, outcomes=_error_outcomes(covered.get(aid, False)),
                          guidance="Warning needs proposal {field, index, original, proposed}.")
    elif not brief_gap:
        sp.observe("profile.editorial_misspellings not supplied: brief spellings only")

    # step 4
    gr = ctx.check("grammar_review", later[2][1])
    paths = _paths(ctx)
    for aid, x in sorted(ads.items()):
        gr.review("confirmed_language_error", ent(aid),
                  f"Does ad {aid} contain a confirmed spelling or grammar error (advertising fragments allowed)?",
                  evidence={"fields": [{k: f[k] for k in ("field", "index", "visible", "dynamic")} for f in x["fields"]],
                            "display_paths": paths.get(aid), "campaign_languages": camp_lang.get(x["campaign_id"]),
                            "exceptions": sorted(exceptions), "language_covered_by_brief": covered.get(aid, False)},
                  outcomes=_error_outcomes(covered.get(aid, False)),
                  guidance="Check brand/acronym/regional variants first; short fragments and sentence case can be "
                           "intentional. Warning needs proposal {field, index, original, proposed}.")
    if not covered or not all(covered.values()):
        gr.partial("some ads lack brief language coverage: confirmed-error outcome unavailable (Info at most)")

    # step 5
    pc = ctx.check("punctuation_casing", later[3][1])
    style_rules = [r.get(b["style_rule"]) for r in brief if r.get(b["style_rule"])]
    for aid, x in sorted(ads.items()):
        hits, exempt = [], []
        for f in x["fields"]:
            for m in _REPEAT.finditer(f["visible"]):
                hits.append({"field": f["field"], "index": f["index"], "token": m.group(0), "kind": "repeated_punctuation"})
            for w in _WORD.findall(f["visible"]):
                if len(w) >= CAPS_MIN and w.isupper():
                    (exempt if w.lower() in exceptions else hits).append(
                        {"field": f["field"], "index": f["index"], "token": w, "kind": "all_caps"})
        if exempt:
            pc.observe(f"Ad {aid}: all-caps tokens covered by approved exceptions", ad_id=aid, tokens=exempt)
        if not hits:
            continue
        ev = {"hits": hits, "style_rules": style_rules, "exceptions": sorted(exceptions)}
        prov = pc.finding("suspected_editorial_issue", "Info", ent(aid),
                          f"Ad {aid}: suspected punctuation/casing issue(s) {[h['token'] for h in hits]}", evidence=ev,
                          recommendation="Check against the applicable editorial rule and brand exceptions.",
                          uncertainty="An ALL CAPS acronym or emphatic punctuation may be allowed.")
        pc.review("style_violation", ent(aid), f"Do {[h['token'] for h in hits]} in ad {aid} violate the documented "
                  f"editorial rule without an approved exception?", evidence=ev, provisional=prov,
                  outcomes={**({"style_violation": {"severity": "Warning", "recommendation":
                                                    "Correct per the documented rule."}} if style_rules else {}),
                            "intentional": {"severity": None, "recommendation": "No action; approved exception."},
                            "uncertain": {"severity": "Info", "recommendation": "Ask the brand owner."}},
                  guidance="Warning only with a cited brief style_rule; proposal {field, index, original, proposed}.")

    # step 6
    cs = ctx.check("claims_separation", later[4][1])
    claim_terms = [str(t) for t in (ctx.profile.get("claim_terms") or []) if t]
    if not claim_terms:
        cs.partial("profile.claim_terms not supplied: claim screen not run")
    supported = {str(r.get(b["preferred_spelling"]) or "").lower() for r in brief if r.get(b["claim_support_ref"])}
    for aid, x in sorted(ads.items()):
        for f in x["fields"]:
            for t in claim_terms:
                if not _find_ci(f["visible"], t):
                    continue
                if t.lower() in supported:
                    cs.observe(f"Ad {aid}: claim '{t}' has brief claim support", ad_id=aid, term=t)
                    continue
                cs.finding("unsupported_claim_referral", "Info", {**ent(aid, f), "term": t},
                           f"Ad {aid} {f['field']} {f['index'] + 1} uses claim term '{t}' without brief support",
                           evidence={"original": f["raw"], "term": t, "source": "profile.claim_terms"},
                           recommendation="Refer to the compliance owner; not an editorial error.",
                           uncertainty="Claim support may exist outside the brief.")

    # step 7
    pp = ctx.check("platform_policy", later[5][1], {"ads": ["approval_status", "policy_topics"]})
    if pp.runnable:
        n = 0
        for aid, x in sorted(ads.items()):
            appr = str(x["row"].get("approval_status") or "").upper()
            topics = V.split_list(x["row"].get("policy_topics"), (" | ", ";", "|", ","))
            if appr in ("DISAPPROVED", "APPROVED_LIMITED") and topics:
                n += 1
                pp.finding("platform_policy_topic", "Info", ent(aid),
                           f"Platform reports ad {aid} {appr} for {topics}",
                           evidence={"approval_status": appr, "policy_topics": topics},
                           recommendation="Delivery impact and resolution belong to skill-037.",
                           uncertainty="Platform status, separate from analyst editorial notes.",
                           owner="skill-037-ad-disapproval-monitoring")
        pp.observe("Platform-confirmed policy topics on enabled ads", ads=n)

    # step 1b / paths
    dp = ctx.check("display_paths", later[6][1], {FIELDS: ["ad_id", "path1", "path2", "displayed_domain"]})
    if dp.runnable:
        dp.observe("Display paths joined by ad_id", ads_with_paths=sum(1 for a in ads if a in paths),
                   ads_without_rows=sorted(a for a in ads if a not in paths))

    cp = ctx.check("correction_proposals", later[7][1])
    cp.observe("Corrections are minimal owner proposals; dynamic syntax and destination preserved",
               deterministic_warnings=sum(1 for f in ctx.result.findings if f.severity == "Warning"),
               pending_reviews=len(ctx.result.reviews))


def _error_outcomes(covered: bool) -> dict:
    out = {"no_error": {"severity": None, "recommendation": "No action."},
           "uncertain": {"severity": "Info", "recommendation": "Ask a native reviewer / owner."}}
    if covered:
        out["confirmed_error"] = {"severity": "Warning", "recommendation": "Apply the minimal correction after owner review."}
    else:
        out["suspected_error"] = {"severity": "Info", "recommendation": "Unsupported language: request specialist review."}
    return out


def _paths(ctx) -> dict[str, dict]:
    t = ctx.table(FIELDS)
    if t is None or t.missing(["ad_id", "path1", "path2"]):
        return {}
    return {str(r.get("ad_id")): {"path1": r.get("path1"), "path2": r.get("path2"),
                                  "displayed_domain": r.get("displayed_domain")} for r in ctx.rows(FIELDS)}


def verify(ctx, item, decision) -> list[str]:
    """Rules: Warning corrections must quote the original field text and preserve dynamic tokens."""
    if decision.get("outcome") not in ("confirmed_error", "style_violation"):
        return []
    p = decision.get("proposal") or {}
    orig, prop = str(p.get("original") or ""), str(p.get("proposed") or "")
    if not orig or not prop or orig == prop:
        return ["proposal needs original and a different proposed text"]
    a = next((x for x in ctx.rows("ads") if str(x.get("id")) == str(item.entity.get("ad_id"))), None)
    texts = [] if a is None else _texts(a.get("headlines")) + _texts(a.get("descriptions"))
    problems = []
    if not any(orig in t for t in texts):
        problems.append("proposal.original is not text of this ad")
    if sorted(_BRACE.findall(orig)) != sorted(_BRACE.findall(prop)):
        problems.append("proposed text changes dynamic insertion/customizer syntax")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
