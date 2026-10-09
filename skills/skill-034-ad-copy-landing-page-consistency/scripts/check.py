"""check.py — skill-034 deterministic ad-promise to landing-page/claim-record evidence mapping.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-034-ad-copy-landing-page-consistency/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #9 Update ad copy with the current year, pause out of stock items (Roy Harmon) — clean-room: stale
           year tokens in eligible ad copy become ai_review items (no copy rewrite, no pausing)
         index #87 Check landing page content for out-of-stock items (Brainlabs) — clean-room: out-of-stock read from
           SUPPLIED snapshot availability (structured out_of_stock) or profile.out_of_stock_markers in visible_text;
           no page fetching
         index #88 Pause ads for out-of-stock items (Dmytro Tonkikh) — detection integrated as review; pausing NOT
           integrated (recommend-only)
rules:   Eligible ad = ad, ad group and campaign ENABLED; unknown status is not eligible and not a defect.
         Snapshots join by exact final URL (query string preserved); a shared hostname is not the same page.
         Current snapshot = captured_at inside [period_start, as_of]; else stale → Info verification request.
         Claim register: an eligible ad whose copy literally contains claim_text while as_of is outside the claim's
         valid_from..valid_to is a deterministic Warning (client record proves the offer is not current).
         Promise-vs-page contradiction, out-of-stock contradiction and stale-year meaning are ai_review judgments;
         Critical only via 'harmful_deceptive' with proposal.evidence_ref; verify() demands verbatim ad/page quotes.
         Out-of-stock markers are profile.out_of_stock_markers (list) — never a hardcoded word list; the structured
         availability value out_of_stock (Merchant vocabulary) is read literally.
         Homepage destination, differing CTA and missing/stale page evidence are Info at most.
         Traffic (ad_metrics) is prioritization context only; a snapshot never attributes a month of spend.
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

SKILL = "skill-034-ad-copy-landing-page-consistency"
VERSION = "1.0.0"

SNAP = "external/landing_page_snapshots"
CLAIMS = "external/ad_claim_register"
SNAP_COLS = ["url", "device", "locale", "captured_at", "resolved_url", "visible_text", "offer_terms", "availability",
             "source_ref"]
CLAIM_COLS = ["ad_id", "claim_id", "claim_text", "valid_from", "valid_to", "verification_state"]
_PROMISE = re.compile(r"(?:[€$£]\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s?(?:EUR|€|USD|GBP)\b|\d+(?:[.,]\d+)?\s?%"
                      r"|\b\d+\s?(?:h|hrs?|hours?|days?|ore|giorni|years?|anni)\b)", re.IGNORECASE)
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _cols(ctx, key, spec) -> dict[str, str]:
    t = ctx.table(key)
    present = set(t.columns) if t else set()
    out = {}
    for c in spec:
        alts = (c,) if isinstance(c, str) else c
        out[alts[0]] = next((a for a in alts if a in present), alts[0])
    return out


def _up(v) -> str:
    return str(v or "").strip().upper()


def _texts(v) -> list[str]:
    """RSA text array: JSON list (strings or {text}) or ' | '-separated cell."""
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


def _urls(v) -> list[str]:
    s = str(v or "").strip()
    if s.startswith("["):
        try:
            return [str(u) for u in json.loads(s)]
        except ValueError:
            pass
    return V.split_list(s, (" | ", ";", "|", ","))


def _homepage(url: str) -> bool:
    base, _, query = url.split("#", 1)[0].partition("?")
    rest = base.split("://", 1)[-1]
    return ("/" not in rest or rest.split("/", 1)[1] == "") and not query


def run(ctx) -> None:
    """Run stale-year, snapshot currency, claim register, promise-vs-page, availability and homepage checks.

    Rules:   Only ENABLED ad/ad group/campaign are evaluated; missing ad/URL mapping skips all checks.
             claim_outside_validity (literal claim_text while as_of is outside valid_from..valid_to) is the only
             deterministic Warning. Stale year, page contradiction and out-of-stock are provisional Info + ai_review;
             Critical only via 'harmful_deceptive'. Stale/missing snapshots and homepage destinations stay Info;
             ad_metrics only prioritize, never attribute spend.
    """
    a = _cols(ctx, "ads", ["id", "campaign_id", "ad_group_id", "status", ("final_url", "final_urls"), "headlines",
                           "descriptions"])
    m = ctx.check("url_mapping", "Stable ad-to-final-URL mapping",
                  {"ads": [a[k] for k in ("id", "campaign_id", "ad_group_id", "status", "final_url")],
                   "campaigns": ["id", "status"], "ad_groups": ["id", "status"]})
    titles = (("promise_extraction", "Factual promises with field/index quotes"),
              ("stale_year_reference", "Past-year references in eligible ad copy"),
              ("snapshot_match", "Current page snapshot per destination"),
              ("claim_validity", "Claim register validity for ad claims"),
              ("claim_classification", "Corroborated / contradicted / ambiguous / unverified"),
              ("availability_offer", "Product availability on the destination"),
              ("homepage_journey", "Homepage destinations"),
              ("prioritization", "Observed traffic for prioritization"),
              ("correction_routing", "Correction proposals vs verification requests"))
    if not m.runnable:
        for cid, t in titles:
            ctx.check(cid, t).skip("ad/URL mapping unavailable", m.missing)
        return
    camp = {str(c.get("id")): _up(c.get("status")) for c in ctx.rows("campaigns")}
    grp = {str(g.get("id")): _up(g.get("status")) for g in ctx.rows("ad_groups")}
    ads: dict[str, dict] = {}
    by_url: dict[str, list[str]] = {}
    for r in sorted(ctx.rows("ads"), key=lambda r: str(r.get(a["id"]))):
        aid = str(r.get(a["id"]))
        st = (_up(r.get(a["status"])), grp.get(str(r.get(a["ad_group_id"])), ""), camp.get(str(r.get(a["campaign_id"])), ""))
        urls = _urls(r.get(a["final_url"]))
        ads[aid] = {"row": r, "urls": urls, "eligible": all(s == "ENABLED" for s in st),
                    "campaign_id": str(r.get(a["campaign_id"])), "ad_group_id": str(r.get(a["ad_group_id"])),
                    "fields": {"headline": _texts(r.get(a["headlines"])), "description": _texts(r.get(a["descriptions"]))}}
        for u in urls:
            by_url.setdefault(u, []).append(aid)
    m.observe("Ad-to-URL mapping", ads=len(ads), eligible_ads=sum(1 for x in ads.values() if x["eligible"]),
              distinct_urls=len(by_url), urls={u: sorted(v) for u, v in sorted(by_url.items())},
              ads_without_url=sorted(k for k, x in ads.items() if not x["urls"]))

    def ent(aid):
        x = ads[aid]
        return {"campaign_id": x["campaign_id"], "ad_group_id": x["ad_group_id"], "ad_id": aid}

    def copy(aid) -> str:
        return " | ".join(t for f in ("headline", "description") for t in ads[aid]["fields"][f])

    # step 2
    pe = ctx.check("promise_extraction", titles[0][1], {"ads": [a["headlines"], a["descriptions"]]})
    promises: dict[str, list[dict]] = {}
    if pe.runnable:
        extra = [str(t).lower() for t in (ctx.profile.get("claim_markers") or []) if t]
        for aid, x in sorted(ads.items()):
            for field, texts in x["fields"].items():
                for i, t in enumerate(texts):
                    hits = [h.group(0) for h in _PROMISE.finditer(t)] + [k for k in extra if k in t.lower()]
                    for h in hits:
                        promises.setdefault(aid, []).append({"field": field, "index": i, "quote": t, "promise": h})
        pe.observe("Factual promise tokens extracted (numbers, prices, percentages, durations, profile claim_markers)",
                   ads_with_promises=len(promises), promises=sum(len(v) for v in promises.values()),
                   claim_markers_source="profile.claim_markers" if extra else None)

    # index #9: stale years
    yr = ctx.check("stale_year_reference", titles[1][1], {"ads": [a["headlines"], a["descriptions"]]})
    if yr.runnable:
        ref = ctx.as_of or ctx.snapshot
        if ref is None:
            yr.partial("as_of/snapshot unknown: current year undecidable")
        else:
            for aid, x in sorted(ads.items()):
                if not x["eligible"]:
                    continue
                hits = [{"field": f, "index": i, "quote": t, "year": int(y.group(1))}
                        for f, texts in x["fields"].items() for i, t in enumerate(texts)
                        for y in _YEAR.finditer(t) if int(y.group(1)) < ref.year]
                if not hits:
                    continue
                prov = yr.finding("stale_year_reference", "Info", ent(aid),
                                  f"Eligible ad {aid} mentions past year(s) {sorted({h['year'] for h in hits})} "
                                  f"as of {ref}", evidence={"hits": hits, "as_of": ref},
                                  recommendation="Check whether the year dates an offer; 'since 1998' is legitimate.",
                                  uncertainty="A year token does not prove an expired offer.")
                yr.review("stale_year_reference", ent(aid), f"Does ad {aid}'s past-year reference present an offer "
                          f"or claim as current that is no longer valid?", evidence={"hits": hits, "as_of": ref},
                          provisional=prov,
                          outcomes={"stale_offer": {"severity": "Warning", "recommendation":
                                                    "Update the dated offer text (owner approval; no auto-rewrite)."},
                                    "legitimate_reference": {"severity": None, "recommendation": "No action."},
                                    "uncertain": {"severity": "Info", "recommendation": "Ask the offer owner."}},
                          guidance="Heritage/founding years and model names are legitimate references.")

    # step 3
    sn = ctx.check("snapshot_match", titles[2][1], {SNAP: SNAP_COLS})
    current: dict[str, list[dict]] = {}
    end = ctx.as_of or ctx.snapshot
    if sn.runnable:
        snaps: dict[str, list[dict]] = {}
        for r in ctx.rows(SNAP):
            snaps.setdefault(str(r.get("url") or "").strip(), []).append(r)
        for url, aids in sorted(by_url.items()):
            eligible = sorted(x for x in aids if ads[x]["eligible"])
            if not eligible:
                continue
            rows = sorted(snaps.get(url, []), key=lambda r: str(r.get("captured_at")))
            cur = [r for r in rows if (d := V.parse_date(r.get("captured_at"))) and ctx.period_start and end
                   and ctx.period_start <= d <= end]
            e = {"final_url": url}
            if cur:
                current[url] = cur
                sn.observe(f"{url}: {len(cur)} current snapshot(s)", final_url=url, ad_ids=eligible,
                           devices=sorted({str(r.get("device")) for r in cur}), locales=sorted({str(r.get("locale")) for r in cur}))
            else:
                key = "page_evidence_stale" if rows else "page_evidence_missing"
                sn.finding(key, "Info", e,
                           f"{url} ({len(eligible)} eligible ad(s)): "
                           + (f"latest snapshot {rows[-1].get('captured_at')} outside {ctx.period_start}..{end}" if rows
                              else "no page snapshot supplied"),
                           evidence={"ad_ids": eligible, "snapshots": len(rows)},
                           recommendation="Capture the destination for the served device/locale/geography.",
                           uncertainty="Missing/stale page evidence is unverifiable, not false.")

    # step 3b: claim register
    cl = ctx.check("claim_validity", titles[3][1], {CLAIMS: CLAIM_COLS})
    claims_by_ad: dict[str, list[dict]] = {}
    if cl.runnable:
        for c in sorted(ctx.rows(CLAIMS), key=lambda r: (str(r.get("ad_id")), str(r.get("claim_id")))):
            aid = str(c.get("ad_id"))
            claims_by_ad.setdefault(aid, []).append(c)
            if aid not in ads or not ads[aid]["eligible"]:
                continue
            text = str(c.get("claim_text") or "").strip()
            if not text or text.lower() not in copy(aid).lower():
                cl.observe(f"Claim {c.get('claim_id')} text not found literally in ad {aid}", ad_id=aid,
                           claim_id=c.get("claim_id"))
                continue
            vf, vt = V.parse_date(c.get("valid_from")), V.parse_date(c.get("valid_to"))
            e = {**ent(aid), "claim_id": c.get("claim_id")}
            ev = {"claim_text": text, "valid_from": vf, "valid_to": vt, "as_of": end,
                  "verification_state": c.get("verification_state"), "supporting_source": c.get("supporting_source")}
            if end and ((vt and vt < end) or (vf and vf > end)):
                cl.finding("claim_outside_validity", "Warning", e,
                           f"Eligible ad {aid} still states '{text}' but the client claim record is valid only "
                           f"{vf}..{vt} (as of {end})", evidence=ev,
                           recommendation="Update or remove the claim text after owner review.",
                           uncertainty="Validity from the client claim register; serving since expiry not measured.")
            elif V.norm_text(c.get("verification_state")) not in ("verified", "approved", "supported"):
                cl.finding("claim_unverified", "Info", e,
                           f"Ad {aid} claim '{text}' has verification_state '{c.get('verification_state')}'",
                           evidence=ev, recommendation="Obtain claim support before relying on it.",
                           uncertainty="Unverified is not false.")

    # step 4
    ad_m = {}
    am_t = ctx.table("ad_metrics")
    if am_t is not None and not am_t.missing(["ad_id", "impressions", "clicks", "cost"]):
        for r in ctx.rows("ad_metrics"):
            k = str(r.get("ad_id"))
            acc = ad_m.setdefault(k, {"impressions": 0.0, "clicks": 0.0, "cost": 0.0})
            for f in acc:
                v = ctx.money(r.get(f)) if f == "cost" else V.num(r.get(f))
                acc[f] = None if v is None or acc[f] is None else acc[f] + v
    kw_by_g: dict[str, list[str]] = {}
    for k in ctx.rows("keywords"):
        kw_by_g.setdefault(str(k.get("ad_group_id")), []).append(str(k.get("text")))
    cc = ctx.check("claim_classification", titles[4][1], {SNAP: ["url", "visible_text", "offer_terms"]})
    if cc.runnable:
        for aid, x in sorted(ads.items()):
            if not x["eligible"]:
                continue
            pages = [r for u in x["urls"] for r in current.get(u, [])]
            if not pages:
                continue
            page_text = " ".join(str(r.get(f) or "") for r in pages for f in ("offer_terms", "visible_text")).lower()
            prom = [{**p, "literal_on_page": p["promise"].lower() in page_text} for p in promises.get(aid, [])]
            cc.review("offer_contradiction", ent(aid),
                      f"Classify ad {aid}'s factual promises against the current page/claim evidence: is any "
                      f"current offer or product contradicted?",
                      evidence={"ad_copy": copy(aid), "promises": prom,
                                "pages": [{k: r.get(k) for k in ("url", "device", "locale", "captured_at", "resolved_url",
                                                                 "offer_terms", "visible_text", "availability", "CTA",
                                                                 "screenshot_or_snapshot_ref", "source_ref")} for r in pages],
                                "claims": [{k: c.get(k) for k in ("claim_id", "claim_text", "valid_from", "valid_to",
                                                                  "qualification", "verification_state")}
                                           for c in claims_by_ad.get(aid, [])],
                                "keywords": sorted(kw_by_g.get(x["ad_group_id"], []))[:20],
                                "traffic": ad_m.get(aid)},
                      outcomes={"contradicted": {"severity": "Warning", "recommendation":
                                                 "Correct the ad claim or destination; quote both sides."},
                                "harmful_deceptive": {"severity": "Critical", "recommendation":
                                                      "Escalate to the compliance owner (skill-141) immediately."},
                                "corroborated": {"severity": None, "recommendation": "No action."},
                                "ambiguous_or_unverified": {"severity": "Info", "recommendation":
                                                            "Request a fuller capture or claim support."}},
                      guidance="Absence in an incomplete snapshot is unverified. Different CTAs can be funnel steps. "
                               "contradicted/harmful_deceptive need proposal {ad_quote, page_quote}; harmful_deceptive "
                               "also proposal.evidence_ref showing user harm.")

    # step 5 (index #87/#88)
    av = ctx.check("availability_offer", titles[5][1], {SNAP: ["url", "availability", "visible_text"]})
    if av.runnable:
        markers = [str(t).lower() for t in (ctx.profile.get("out_of_stock_markers") or []) if t]
        if not markers:
            av.partial("profile.out_of_stock_markers not supplied: only structured availability=out_of_stock read")
        for aid, x in sorted(ads.items()):
            if not x["eligible"]:
                continue
            for u in x["urls"]:
                for r in current.get(u, []):
                    structured = V.norm_text(r.get("availability")).replace(" ", "_") == "out_of_stock"
                    text_hits = [k for k in markers if k in str(r.get("visible_text") or "").lower()]
                    if not structured and not text_hits:
                        continue
                    e = {**ent(aid), "final_url": u, "captured_at": r.get("captured_at")}
                    ev = {"availability": r.get("availability"), "marker_hits": text_hits, "ad_copy": copy(aid),
                          "device": r.get("device"), "locale": r.get("locale"), "source_ref": r.get("source_ref"),
                          "traffic": ad_m.get(aid)}
                    prov = av.finding("out_of_stock_destination", "Info", e,
                                      f"Eligible ad {aid} lands on {u}, captured {r.get('captured_at')} as out of stock",
                                      evidence=ev, recommendation="Check whether the ad promises this product now.",
                                      uncertainty="One capture; availability can change within the period.")
                    av.review("out_of_stock_contradiction", e,
                              f"Does ad {aid} promise the product that the destination shows as out of stock?",
                              evidence=ev, provisional=prov,
                              outcomes={"product_contradiction": {"severity": "Warning", "recommendation":
                                                                  "Propose pausing/redirecting to the owner (no automatic pause)."},
                                        "not_promised": {"severity": None, "recommendation": "No action."},
                                        "uncertain": {"severity": "Info", "recommendation": "Re-capture availability."}},
                              guidance="product_contradiction needs proposal {ad_quote, page_quote}.")

    # step 6
    hp = ctx.check("homepage_journey", titles[6][1])
    for url, aids in sorted(by_url.items()):
        eligible = sorted(x for x in aids if ads[x]["eligible"])
        if eligible and _homepage(url):
            hp.finding("homepage_destination", "Info", {"final_url": url},
                       f"{len(eligible)} eligible ad(s) use the homepage {url}", evidence={"ad_ids": eligible},
                       recommendation="Acceptable when the homepage fulfils the promise; no dedicated page mandated.",
                       uncertainty="URL structure alone says nothing about fit.")

    # step 7
    pr = ctx.check("prioritization", titles[7][1], {"ad_metrics": ["ad_id", "impressions", "clicks", "cost"]})
    if pr.runnable:
        queued = sorted({r.entity.get("ad_id") for r in ctx.result.reviews if r.entity.get("ad_id")} |
                        {f.entity.get("ad_id") for f in ctx.result.findings if f.entity.get("ad_id")})
        rows = sorted(({"ad_id": q, **(ad_m.get(q) or {})} for q in queued),
                      key=lambda d: (-(d.get("impressions") or 0), d["ad_id"]))
        pr.observe("Review/finding queue ordered by observed impressions (context, not impact)", queue=rows,
                   mature=ctx.mature, window=[ctx.period_start, ctx.period_end], currency=ctx.currency)

    rt = ctx.check("correction_routing", titles[8][1])
    rt.observe("Corrections vs verification requests", corrections=sum(1 for f in ctx.result.findings if f.severity == "Warning"),
               verification_requests=sum(1 for f in ctx.result.findings if f.condition_key in
                                         ("page_evidence_missing", "page_evidence_stale", "claim_unverified")),
               pending_reviews=len(ctx.result.reviews),
               routes={"technical_health": "skill-125", "policy": "skill-141"})


def verify(ctx, item, decision) -> list[str]:
    """Rules: contradiction outcomes quote both sides verbatim; Critical needs proposal.evidence_ref."""
    out = decision.get("outcome")
    if out not in ("contradicted", "harmful_deceptive", "product_contradiction"):
        return []
    p = decision.get("proposal") or {}
    ev = item.evidence
    ad_text = str(ev.get("ad_copy") or "").lower()
    page = json.dumps(ev.get("pages") or [], ensure_ascii=False).lower() + " " + str(ev.get("availability") or "").lower() \
        + " " + " ".join(ev.get("marker_hits") or [])
    problems = []
    aq, pq = str(p.get("ad_quote") or "").strip().lower(), str(p.get("page_quote") or "").strip().lower()
    if not aq or aq not in ad_text:
        problems.append("proposal.ad_quote must be quoted verbatim from the ad copy")
    if not pq or pq not in page:
        problems.append("proposal.page_quote must be quoted verbatim from the page evidence")
    if out == "harmful_deceptive" and not p.get("evidence_ref"):
        problems.append("harmful_deceptive needs proposal.evidence_ref showing the message reached users with harm")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
