"""check.py — skill-004 deterministic ad-group theme inventory with AI-judged theme/copy alignment.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-004-ad-group-thematic-tightness/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #78 Account Structure Auditor (Google Ads scripts solutions) — clean-room reimplementation of
         per-ad-group keyword and eligible-ad counts; counts are observations, never defects by themselves.
rules:   Search ad groups with enabled text keywords only; keywordless inventory is out of scope (observed).
         Keyword count, sparse/large groups and low QS are observations; no quota, no deterministic finding.
         Themes are assigned deterministically ONLY from profile.theme_lexicon {theme: [phrases]} (contiguous-token
         phrase hits); otherwise tuple/theme assignment is an ai_review marked tentative.
         Deterministic Info only for 'insufficient_eligible_copy' (keywords but zero ENABLED, non-disapproved ads).
         Theme/copy contradiction (Warning) is an AI outcome; verify() demands keyword_ids of the ad group,
         eligible ad_ids of the ad group and literal product_evidence found in keyword text or taxonomy.
         Keyword metrics join by keyword_id; duplicate keyword_id rows (segments) are excluded, never summed,
         and never multiplied by ad count. CVR/CPA only when ctx.mature is True and both gates pass.
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

SKILL = "skill-004-ad-group-thematic-tightness"
VERSION = "1.0.0"

KW = ["id", "campaign_id", "ad_group_id", "text", "status"]
ADS = ["id", "campaign_id", "ad_group_id", "status", "approval_status", "headlines", "descriptions", "final_url"]
KM = ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"]
SPARSE, LARGE = 2, 30  # descriptive buckets only (recipe: "one keyword or thirty-plus")


def _toks(text) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _phrase(term, text) -> bool:
    n, q = _toks(term), _toks(text)
    return bool(n) and any(q[i:i + len(n)] == n for i in range(len(q) - len(n) + 1))


def _active(row) -> bool:
    return str(row.get("status") or "").upper() in ("ENABLED", "ACTIVE")


def _eligible(ad) -> bool | None:
    """True/False; None when the ad is enabled but its approval status is unknown."""
    if not _active(ad):
        return False
    s = str(ad.get("approval_status") or "").upper()
    if not s:
        return None
    return s not in ("DISAPPROVED", "NOT_ELIGIBLE")


def _search_campaigns(ctx) -> set[str] | None:
    t = ctx.table("campaigns")
    if t is None or "channel_type" not in t.columns:
        return None
    return {str(c.get("id")) for c in t.rows if str(c.get("channel_type") or "").upper() == "SEARCH"
            and str(c.get("status") or "").upper() != "REMOVED"}


def _groups(ctx) -> dict[tuple, list[dict]]:
    """(campaign_id, ad_group_id) → enabled keyword rows (dedupe by keyword id)."""
    search = _search_campaigns(ctx)
    active_groups = {str(g.get("id")) for g in ctx.rows("ad_groups") if str(g.get("status") or "ENABLED").upper() != "REMOVED"}
    out: dict[tuple, dict[str, dict]] = {}
    for k in ctx.rows("keywords"):
        cid, gid = str(k.get("campaign_id")), str(k.get("ad_group_id"))
        if not _active(k) or (search is not None and cid not in search) or gid not in active_groups:
            continue
        out.setdefault((cid, gid), {})[str(k.get("id"))] = k
    return {key: [v[i] for i in sorted(v)] for key, v in sorted(out.items())}


def _lexicon(ctx) -> dict[str, list[str]]:
    lex = ctx.profile.get("theme_lexicon") or {}
    return {str(k): [str(p) for p in (v or [])] for k, v in lex.items()} if isinstance(lex, dict) else {}


def _copy(ad) -> str:
    return " ".join(V.split_list(ad.get("headlines")) + V.split_list(ad.get("descriptions")))


def run(ctx) -> None:
    """Run the ad-group keyword inventory, lexicon theme tuples, copy-alignment review and gated theme metrics.

    Rules:   Only Search ad groups with enabled keywords; counts, sparse/large groups and low QS stay observations (no
             quota). Deterministic findings are Info only: 'multiple_themes' (profile.theme_lexicon hits) and
             'insufficient_eligible_copy'; without a lexicon, theme grouping is a tentative ai_review. Theme/copy
             contradiction (Warning) is ai_review only; CVR/CPA need ctx.mature True plus min_clicks/min_conversions.
    """
    taxonomy = [str(t) for t in (ctx.profile.get("product_service_taxonomy") or [])]
    lex = _lexicon(ctx)
    context = {"product_service_taxonomy": taxonomy, "intended_offer": ctx.profile.get("intended_offer"),
               "audience": ctx.profile.get("audience"), "geography": ctx.profile.get("service_area")}

    # -- step 1: scope, keyword-metric grain and join integrity
    scope = ctx.check("metric_scope", "Keyword metric grain, ID join and maturity",
                      {"keyword_metrics": KM, "keywords": ["id", "campaign_id", "ad_group_id"]})
    metrics: dict[str, dict] = {}
    if scope.runnable:
        rows: dict[str, list[dict]] = {}
        for r in ctx.rows("keyword_metrics"):
            rows.setdefault(str(r.get("keyword_id")), []).append(r)
        inv = {str(k.get("id")): k for k in ctx.rows("keywords")}
        dup = sorted(k for k, v in rows.items() if len(v) > 1)
        orphan = sorted(k for k in rows if k not in inv)
        mism = sorted(k for k, v in rows.items() if k in inv and len(v) == 1 and
                      (str(v[0].get("ad_group_id")) != str(inv[k].get("ad_group_id"))))
        for k, v in rows.items():
            if len(v) == 1 and k in inv and k not in mism:
                metrics[k] = v[0]
        if dup:
            scope.partial(f"{len(dup)} keyword_ids have multiple metric rows (segments): excluded, not summed", [])
        if orphan or mism:
            scope.partial(f"metric rows not joinable by ID to keyword inventory: orphan {orphan}, parent mismatch {mism}")
        scope.observe("Keyword metrics joined by keyword_id", joined=len(metrics), duplicates=dup, orphans=orphan,
                      window=[ctx.period_start, ctx.period_end], mature=ctx.mature, maturity_note=ctx.maturity_note)

    # -- step 2 (+ #78): keyword and eligible-ad counts per ad group
    cnt = ctx.check("keyword_counts", "Enabled keyword and eligible ad counts per ad group",
                    {"keywords": KW, "ad_groups": ["id", "campaign_id"], "campaigns": ["id", "channel_type"]})
    groups: dict[tuple, list[dict]] = {}
    ads_by: dict[tuple, list[dict]] = {}
    if cnt.runnable:
        groups = _groups(ctx)
        if ctx.table("ads") is not None and not ctx.table("ads").missing(["id", "ad_group_id", "status"]):
            for a in ctx.rows("ads"):
                ads_by.setdefault((str(a.get("campaign_id")), str(a.get("ad_group_id"))), []).append(a)
        else:
            cnt.partial("ads inventory missing: eligible-ad counts unknown", ["ads (file)"])
        search = _search_campaigns(ctx) or set()
        keywordless = sorted(str(g.get("id")) for g in ctx.rows("ad_groups")
                             if str(g.get("campaign_id")) in search and
                             (str(g.get("campaign_id")), str(g.get("id"))) not in groups)
        for (cid, gid), kws in groups.items():
            eligible = sum(1 for a in ads_by.get((cid, gid), []) if _eligible(a))
            bucket = "sparse" if len(kws) <= SPARSE else "large" if len(kws) >= LARGE else "typical"
            cnt.observe(f"Ad group {gid}: {len(kws)} enabled keywords", campaign_id=cid, ad_group_id=gid,
                        enabled_keywords=len(kws), eligible_ads=eligible if ads_by or ctx.table("ads") else None,
                        size_bucket=bucket, note="count alone is not a structural defect")
        cnt.observe("Keywordless Search ad groups (out of scope)", ad_groups=keywordless)

    # -- step 3: tuple assignment (deterministic lexicon or AI)
    tup = ctx.check("theme_tuples", "Assign product/task/audience/geo/offer tuples to keywords",
                    {"keywords": KW})
    assigned: dict[str, list[str]] = {}
    if tup.runnable and not groups:
        tup.skip("no in-scope Search ad groups with enabled keywords", cnt.missing)
    elif tup.runnable:
        if not taxonomy:
            tup.partial("profile product_service_taxonomy missing: inferred themes are tentative", ["profile:product_service_taxonomy"])
        for (cid, gid), kws in groups.items():
            for k in kws:
                assigned[str(k.get("id"))] = sorted(t for t, phrases in lex.items() if any(_phrase(p, k.get("text")) for p in phrases))
        unassigned = sorted(k for k, v in assigned.items() if not v)
        tup.observe("Deterministic lexicon assignment", lexicon_themes=sorted(lex), assigned=len(assigned) - len(unassigned),
                    unknown=len(unassigned), ambiguous=sorted(k for k, v in assigned.items() if len(v) > 1))
        if unassigned:
            tup.partial(f"{len(unassigned)} keywords without a profile.theme_lexicon hit: tuple assignment via ai_review")

    # -- step 4: theme grouping per ad group
    grp = ctx.check("theme_grouping", "Theme memberships per ad group", {"keywords": KW})
    if grp.runnable and not assigned:
        grp.skip("tuple assignment unavailable", tup.missing)
    elif grp.runnable:
        for (cid, gid), kws in groups.items():
            members: dict[str, list[str]] = {}
            for k in kws:
                for t in assigned.get(str(k.get("id"))) or ["Unknown"]:
                    members.setdefault(t, []).append(str(k.get("id")))
            known = sorted(t for t in members if t != "Unknown")
            ev = {"keywords": [{"keyword_id": str(k.get("id")), "text": k.get("text"), "lexicon_themes": assigned.get(str(k.get("id")))}
                               for k in kws], "memberships": members, **context}
            grp.observe(f"Ad group {gid} theme memberships", campaign_id=cid, ad_group_id=gid, memberships=members)
            if len(kws) < 2 or (len(known) <= 1 and "Unknown" not in members):
                continue
            prov = None
            if len(known) > 1:
                prov = grp.finding("multiple_themes", "Info", {"campaign_id": cid, "ad_group_id": gid},
                                   f"Ad group {gid} keywords fall into {len(known)} lexicon themes {known}",
                                   evidence=ev, recommendation="Review whether themes need separate messages; no split is implied.",
                                   uncertainty="Lexicon hits are literal; multiple themes alone are not a defect.")
            grp.review("theme_grouping", {"campaign_id": cid, "ad_group_id": gid},
                       f"Assign each keyword of ad group {gid} a (product/service, task, audience, geography, offer) tuple "
                       f"and group identical required fields: how many distinct themes?",
                       evidence=ev, provisional=prov,
                       outcomes={"single_theme": {"severity": None, "recommendation": "Coherent; preserve."},
                                 "multiple_themes": {"severity": "Info", "recommendation":
                                                     "List memberships; propose a split only if messages must differ."},
                                 "unknown": {"severity": "Info", "recommendation": "Intent unknown; ask the owner for taxonomy."}},
                       guidance="Use only the approved taxonomy/profile; preserve Unknown and ambiguous assignments.")

    # -- step 5: theme vs eligible copy
    copy = ctx.check("copy_alignment", "Compare keyword themes with eligible ad copy", {"keywords": KW, "ads": ADS})
    if copy.runnable and not groups:
        copy.skip("no in-scope ad groups", cnt.missing)
    elif copy.runnable:
        for (cid, gid), kws in groups.items():
            ads = sorted((a for a in ads_by.get((cid, gid), []) if _eligible(a) is True), key=lambda a: str(a.get("id")))
            entity = {"campaign_id": cid, "ad_group_id": gid}
            if not ads and any(_eligible(a) is None for a in ads_by.get((cid, gid), [])):
                copy.partial(f"ad group {gid}: enabled ads with unknown approval status; eligibility undetermined",
                             ["ads:approval_status"])
                continue
            if not ads:
                copy.finding("insufficient_eligible_copy", "Info", entity,
                             f"Ad group {gid} has {len(kws)} enabled keywords but no enabled, non-disapproved ad",
                             evidence={"keyword_ids": [str(k.get("id")) for k in kws],
                                       "ads": [{"ad_id": a.get("id"), "status": a.get("status"),
                                                "approval_status": a.get("approval_status")} for a in ads_by.get((cid, gid), [])]},
                             recommendation="Message comparison impossible; confirm eligible copy exists.",
                             uncertainty="Status/approval snapshot only.")
                continue
            text = " ".join(_copy(a) for a in ads)
            literal = {str(k.get("id")): all(t in _toks(text) for t in _toks(k.get("text"))) for k in kws}
            ev = {"keywords": [{"keyword_id": str(k.get("id")), "text": k.get("text"), "literal_in_copy": literal[str(k.get("id"))]}
                               for k in kws],
                  "ads": [{"ad_id": str(a.get("id")), "headlines": V.split_list(a.get("headlines")),
                           "descriptions": V.split_list(a.get("descriptions")), "final_url": a.get("final_url")} for a in ads],
                  "literal_support": f"{sum(literal.values())}/{len(literal)}", **context}
            copy.review("theme_copy_contradiction", entity,
                        f"Do the eligible ads of ad group {gid} support, contradict or leave unknown the keyword themes?",
                        evidence=ev,
                        outcomes={"contradicted": {"severity": "Warning", "recommendation":
                                                   "Owner reviews a split or copy aligned to the named product/service."},
                                  "supported": {"severity": None, "recommendation": "Themes supported by copy; preserve."},
                                  "unknown": {"severity": "Info", "recommendation": "Generic/incomplete copy; review messaging."}},
                        guidance="Supported = explicit or approved-equivalent offer; Contradicted = a different offer/task "
                                 "with product evidence; generic copy → unknown. URLs do not establish page relevance. "
                                 "contradicted needs proposal {keyword_ids, ad_ids, product_evidence, split?:[{keyword_ids, message}]}.")
        copy.observe("Theme/copy reviews queued", ad_groups=len([g for g in groups if any(_eligible(a) for a in ads_by.get(g, []))]))

    # -- step 6: mature metrics by ad group/theme (no multiplication by ads)
    met = ctx.check("theme_metrics", "Keyword metrics summarized per ad group and theme", {"keyword_metrics": KM, "keywords": KW})
    if met.runnable and not (groups and scope.runnable):
        met.skip("inventory or metric join unavailable", cnt.missing + scope.missing)
    elif met.runnable:
        mc, mcl = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
        if ctx.mature is not True:
            met.partial(f"conversion maturity {ctx.mature}: descriptive totals only ({ctx.maturity_note})")
        for (cid, gid), kws in groups.items():
            s = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0}
            unknown, qs = 0, []
            for k in kws:
                m = metrics.get(str(k.get("id")))
                if m is None:
                    unknown += 1
                    continue
                for f in s:
                    v = ctx.money(m.get(f)) if f == "cost" else V.num(m.get(f))
                    if v is None:
                        unknown += 1
                    else:
                        s[f] += v
                q = V.num(k.get("quality_score") if k.get("quality_score") is not None else m.get("quality_score"))
                if q is not None:
                    qs.append(q)
            data = {"campaign_id": cid, "ad_group_id": gid, **s, "missing_cells_or_rows": unknown,
                    "quality_scores": sorted(qs), "window": [ctx.period_start, ctx.period_end]}
            if ctx.mature is True and s["clicks"] >= (mcl.value or 0) and s["conversions"] >= (mc.value or 0):
                data.update(cvr=V.ratio(s["conversions"], s["clicks"]), cpa=V.ratio(s["cost"], s["conversions"]))
            met.observe(f"Ad group {gid} keyword totals (QS diagnostic only)", **data)

    # -- step 7: split/merge proposals only via verified review outcomes
    prop = ctx.check("split_merge_prerequisites", "Split/merge prerequisites for owner review", {"keywords": KW})
    if prop.runnable and not groups:
        prop.skip("no in-scope ad groups", cnt.missing)
    elif prop.runnable:
        by_c: dict[str, list[str]] = {}
        for cid, gid in groups:
            by_c.setdefault(cid, []).append(gid)
        prop.observe("Merge candidates share campaign-level targeting/goals only within one campaign",
                     ad_groups_by_campaign=by_c,
                     note="cross-campaign merges need verified compatible offer, goals, targeting and routing controls")

    # -- step 8: preserve coherent sparse/large groups
    keep = ctx.check("preserve_sparse_large", "Sparse and large ad groups preserved unless themes contradict", {"keywords": KW})
    if keep.runnable and not groups:
        keep.skip("no in-scope ad groups", cnt.missing)
    elif keep.runnable:
        keep.observe("Size buckets are descriptive; no quota applies",
                     sparse=sorted(g for (_, g), k in groups.items() if len(k) <= SPARSE),
                     large=sorted(g for (_, g), k in groups.items() if len(k) >= LARGE))


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'contradicted' needs in-group keyword_ids, eligible in-group ad_ids and literal product evidence."""
    if item.condition_key != "theme_copy_contradiction" or decision.get("outcome") != "contradicted":
        return []
    p = decision.get("proposal") or {}
    kw_ids = {k["keyword_id"] for k in item.evidence.get("keywords", [])}
    ad_ids = {a["ad_id"] for a in item.evidence.get("ads", [])}
    problems = []
    pk, pa = [str(x) for x in p.get("keyword_ids") or []], [str(x) for x in p.get("ad_ids") or []]
    if not pk or not set(pk) <= kw_ids:
        problems.append(f"proposal.keyword_ids must be non-empty keyword IDs of this ad group {sorted(kw_ids)}")
    if not pa or not set(pa) <= ad_ids:
        problems.append(f"proposal.ad_ids must be non-empty eligible ad IDs of this ad group {sorted(ad_ids)}")
    ev = str(p.get("product_evidence") or "").strip()
    texts = [k["text"] for k in item.evidence.get("keywords", []) if k["keyword_id"] in pk]
    sources = texts + list(item.evidence.get("product_service_taxonomy") or [])
    if not ev or not any(_phrase(ev, s) or _phrase(s, ev) for s in sources):
        problems.append("proposal.product_evidence must literally match a cited keyword text or taxonomy entry")
    for part in p.get("split") or []:
        ids = {str(x) for x in (part or {}).get("keyword_ids") or []}
        if not ids or not ids <= kw_ids:
            problems.append("each split part needs keyword_ids from this ad group")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
