"""check.py — skill-031 deterministic sitelink association, destination-evidence and contextual CTR checks.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-031-sitelink-relevance-performance/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #81 Check Sitelinks for broken URLs (Vincent Hsu gist) — clean-room reimplementation of the
           broken-sitelink-URL detection from SUPPLIED timestamped tests (external/sitelink_destinations http_status);
           live URL fetching NOT integrated (no network)
rules:   Sitelinks = assets rows with type SITELINK; associations (asset × level × parent) and unique destinations are
         counted separately. Eligible = association status ENABLED, approval not DISAPPROVED, parent chain ENABLED.
         Broken destination Warning ONLY when a current eligible sitelink's URL/device/locale shows HTTP >= 400 at
         >= 2 distinct check_at times inside [period_start, as_of] with no later success; one failing check →
         Info verification request. Status 0/blank is unknown, never broken.
         Destination evidence joins by asset_id + exact original_url (query string preserved); never by name.
         Wrong-offer is a judgment → ai_review; verify() demands quotes present in the sitelink text and the page's
         offer_terms/visible_text. Stale/missing snapshots → Info verification request, never expired-offer.
         CTR = asset-only (click_scope asset-only) clicks / impressions of the SAME asset/association/segment;
         all-ad clicks stay separate. No universal 0.2% cutoff; low-CTR comparison needs ctx.mature True and
         both cohorts >= min_impressions, then ai_review (business concern) — a homepage/high-value link is never
         removed on CTR alone (verify rejects proposal.action remove for homepage sitelinks).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks04 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-031-sitelink-relevance-performance"
VERSION = "1.0.0"

DEST = "external/sitelink_destinations"
METRICS = "custom/sitelink_metrics"
ASSET_SPEC = [("asset_id", "id"), ("type", "asset_type"), ("association_level", "level"), "campaign_id",
              "ad_group_id", "status"]
TEXT_SPEC = [("link_text", "text"), ("description1", "description_1"), ("description2", "description_2"),
             ("final_url", "final_urls"), ("approval_status", "approval")]
DEST_COLS = ["asset_id", "association_key", "original_url", "resolved_url", "http_status", "device", "locale",
             "check_at"]
OFFER_COLS = ["asset_id", "original_url", "check_at", "visible_text", "offer_terms", "valid_from", "valid_to",
              "screenshot_or_snapshot_ref", "source_ref"]
MET_COLS = ["asset_id", "association_key", "date", "segment", "impressions", "clicks", "click_scope"]


def _cols(ctx, key, spec) -> dict[str, str]:
    """Canonical → actual column; first documented alternative present, else the canonical name (reported)."""
    t = ctx.table(key)
    present = set(t.columns) if t else set()
    out = {}
    for c in spec:
        alts = (c,) if isinstance(c, str) else c
        out[alts[0]] = next((a for a in alts if a in present), alts[0])
    return out


def _up(v) -> str:
    return str(v or "").strip().upper()


def _url_parts(url: str) -> tuple[str, str]:
    """(path, query) of an absolute URL without urllib (network modules are banned by lint)."""
    base = str(url or "").strip().split("#", 1)[0]
    base, _, query = base.partition("?")
    rest = base.split("://", 1)[-1]
    path = "/" + rest.split("/", 1)[1] if "/" in rest else ""
    return path, query


def _homepage(url) -> bool | None:
    s = str(url or "").strip()
    if not s:
        return None
    path, query = _url_parts(s)
    return path in ("", "/") and not query


def _first_url(v) -> str | None:
    urls = V.split_list(v, (" | ", ";", "|", ","))
    return urls[0].strip().strip('[]"\'') if urls else None


def _in_window(ctx, d) -> bool:
    end = ctx.as_of or ctx.snapshot
    return bool(d and ctx.period_start and end and ctx.period_start <= d <= end)


def run(ctx) -> None:
    """Run sitelink inventory, eligibility, destination health, offer consistency and CTR checks.

    Rules:   broken_destination Warning only for HTTP >= 400 at >= 2 distinct check_at in [period_start, as_of] with no
             later success; one failure or stale/missing evidence → Info verification request; status 0/blank is
             unknown. Wrong offer is ai_review (Warning). Low CTR needs ctx.mature True and both cohorts >=
             min_impressions, then review; homepage/high-value sitelinks are never removed on CTR alone. Joins by
             asset_id + exact URL, never name.
    """
    a = _cols(ctx, "assets", ASSET_SPEC)
    spine = ctx.check("association_spine", "Sitelink associations joined to parent eligibility",
                      {"assets": list(a.values()), "campaigns": ["id", "status"], "ad_groups": ["id", "campaign_id", "status"]})
    later = (("text_completeness", "Text, optional descriptions and destination completeness"),
             ("destination_join", "Page evidence joined by exact URL/device/locale/time"),
             ("offer_consistency", "Sitelink promise vs page offer terms"),
             ("destination_errors", "Confirmed HTTP errors with reproduction scope"),
             ("contextual_ctr", "Asset-only CTR per association and segment"),
             ("mature_comparison", "Mature matched-context CTR comparison"),
             ("fix_proposals", "Confirmed mismatches vs verification requests vs optional tests"))
    if not spine.runnable:
        for cid, t in later[:4]:
            ctx.check(cid, t).skip("sitelink association spine unavailable", spine.missing)
        _metric_checks(ctx, later, {}, _cols(ctx, "assets", TEXT_SPEC))
        return
    camp = {str(c.get("id")): _up(c.get("status")) for c in ctx.rows("campaigns")}
    grp = {str(g.get("id")): g for g in ctx.rows("ad_groups")}
    t_map = _cols(ctx, "assets", TEXT_SPEC)
    sitelinks: dict[str, dict] = {}
    assoc = 0
    for r in sorted(ctx.rows("assets"), key=lambda r: (str(r.get(a["asset_id"])), str(r.get(a["association_level"])),
                                                        str(r.get(a["campaign_id"])), str(r.get(a["ad_group_id"])))):
        if _up(r.get(a["type"])) not in ("SITELINK", "SITELINK_ASSET"):
            continue
        assoc += 1
        aid, level = str(r.get(a["asset_id"])), _up(r.get(a["association_level"]))
        cid, gid = str(r.get(a["campaign_id"]) or ""), str(r.get(a["ad_group_id"]) or "")
        if level in ("CUSTOMER", "ACCOUNT"):
            parent = "ENABLED" if any(s == "ENABLED" for s in camp.values()) else ""
        elif level == "CAMPAIGN":
            parent = camp.get(cid, "")
        elif level == "AD_GROUP":
            g = grp.get(gid) or {}
            parent = "ENABLED" if _up(g.get("status")) == "ENABLED" and camp.get(str(g.get("campaign_id"))) == "ENABLED" \
                else _up(g.get("status")) or ""
        else:
            parent = ""
        approval = _up(r.get(t_map["approval_status"]))
        own = _up(r.get(a["status"]))
        eligible = None if not parent or not own else (own == "ENABLED" and parent == "ENABLED" and approval != "DISAPPROVED")
        s = sitelinks.setdefault(aid, {"asset_id": aid, "associations": [], "row": r, "eligible": False,
                                       "eligibility_unknown": False})
        s["associations"].append({"level": level, "campaign_id": cid or None, "ad_group_id": gid or None,
                                  "status": own or None, "parent_status": parent or None, "eligible": eligible})
        s["eligible"] = s["eligible"] or eligible is True
        s["eligibility_unknown"] = s["eligibility_unknown"] or eligible is None
    urls = {str(_first_url(s["row"].get(t_map["final_url"])) or "") for s in sitelinks.values()} - {""}
    spine.observe("Sitelink associations vs unique assets vs unique destinations", associations=assoc,
                  unique_sitelinks=len(sitelinks), unique_destinations=len(urls),
                  eligible_sitelinks=sum(1 for s in sitelinks.values() if s["eligible"]),
                  unknown_eligibility=sorted(k for k, s in sitelinks.items() if s["eligibility_unknown"]))
    if ctx.table("assets").complete is not True:
        spine.partial("assets not manifest-complete: absent associations cannot be concluded")

    # step 2
    txt = ctx.check("text_completeness", later[0][1], {"assets": [t_map["link_text"], t_map["final_url"]]})
    if txt.runnable:
        has_desc = t_map["description1"] in ctx.table("assets").columns
        if not has_desc:
            txt.partial("descriptions not exported", [f"assets:{t_map['description1']}", f"assets:{t_map['description2']}"])
        for aid, s in sorted(sitelinks.items()):
            r = s["row"]
            url = _first_url(r.get(t_map["final_url"]))
            ent = {"asset_id": aid}
            ev = {"link_text": r.get(t_map["link_text"]), "final_url": url, "associations": s["associations"],
                  "description1": r.get(t_map["description1"]), "description2": r.get(t_map["description2"])}
            if _homepage(url):
                txt.finding("homepage_destination", "Info", ent,
                            f"Sitelink {aid} '{r.get(t_map['link_text'])}' points to the homepage {url}",
                            evidence=ev, recommendation="Confirm the homepage fulfils the link promise; it can be the "
                                                        "most relevant destination.",
                            uncertainty="Homepage use alone is not a defect.")
            if has_desc and r.get(t_map["description1"]) is None and r.get(t_map["description2"]) is None:
                txt.finding("optional_descriptions_absent", "Info", ent,
                            f"Sitelink {aid} has no description lines in the export (optional)", evidence=ev,
                            recommendation="Optional: test descriptions where they add a concrete detail.",
                            uncertainty="Empty cells may be unexported rather than absent; descriptions are optional.")
            if url is None:
                txt.partial(f"sitelink {aid}: final URL unknown")

    # step 3
    d_t = ctx.table(DEST)
    dest = ctx.check("destination_join", later[1][1], {DEST: DEST_COLS})
    by_asset: dict[str, list[dict]] = {}
    if dest.runnable:
        for r in ctx.rows(DEST):
            by_asset.setdefault(str(r.get("asset_id")), []).append(r)
        for aid, s in sorted(sitelinks.items()):
            if not s["eligible"]:
                continue
            url = _first_url(s["row"].get(t_map["final_url"]))
            rows = [r for r in by_asset.get(aid, []) if str(r.get("original_url") or "").strip() == (url or "")]
            current = [r for r in rows if _in_window(ctx, V.parse_date(r.get("check_at")))]
            ent = {"asset_id": aid}
            if not current:
                dest.finding("destination_evidence_missing", "Info", ent,
                             f"Eligible sitelink {aid}: no destination test for exact URL {url} within "
                             f"{ctx.period_start}..{ctx.as_of or ctx.snapshot}",
                             evidence={"final_url": url, "tests_any_time": len(rows),
                                       "tests_other_urls": len(by_asset.get(aid, [])) - len(rows)},
                             recommendation="Supply a contemporary URL/device/locale test before any destination claim.",
                             uncertainty="Missing or stale tests are not evidence of a broken page.")
                continue
            for r in current:
                orig, res = str(r.get("original_url") or ""), str(r.get("resolved_url") or "")
                dropped = bool(res) and bool(_url_parts(orig)[1]) and not _url_parts(res)[1]
                dest.observe(f"Sitelink {aid}: destination test {r.get('check_at')} {r.get('device')}/{r.get('locale')}",
                             asset_id=aid, original_url=orig, resolved_url=res or None, http_status=r.get("http_status"),
                             redirected=bool(res) and res != orig, query_dropped_on_redirect=bool(dropped))
    else:
        by_asset = {}

    # step 4
    off = ctx.check("offer_consistency", later[2][1], {DEST: OFFER_COLS, "assets": [t_map["link_text"]]})
    if off.runnable:
        for aid, s in sorted(sitelinks.items()):
            if not s["eligible"]:
                continue
            r0 = s["row"]
            url = _first_url(r0.get(t_map["final_url"]))
            rows = sorted((r for r in by_asset.get(aid, []) if str(r.get("original_url") or "").strip() == (url or "")
                           and _in_window(ctx, V.parse_date(r.get("check_at")))),
                          key=lambda r: str(r.get("check_at")))
            valid = [r for r in rows if (r.get("offer_terms") or r.get("visible_text"))
                     and V.parse_date(r.get("valid_from")) and V.parse_date(r.get("valid_to"))
                     and V.parse_date(r.get("valid_from")) <= (ctx.period_end or ctx.as_of)
                     and V.parse_date(r.get("valid_to")) >= (ctx.period_start or ctx.as_of)]
            ent = {"asset_id": aid}
            if not valid:
                if rows:
                    off.finding("offer_verification_needed", "Info", ent,
                                f"Sitelink {aid}: page snapshot lacks offer text or a validity window covering the period",
                                evidence={"final_url": url, "tests": len(rows)},
                                recommendation="Capture page/offer terms valid for the serving period.",
                                uncertainty="Stale or missing snapshots cannot establish an expired offer.")
                continue
            last = valid[-1]
            ev = {"sitelink_quote": " | ".join(str(x) for x in (r0.get(t_map["link_text"]), r0.get(t_map["description1"]),
                                                                  r0.get(t_map["description2"])) if x),
                  "final_url": url, "page_offer_terms": last.get("offer_terms"), "page_visible_text": last.get("visible_text"),
                  "check_at": last.get("check_at"), "valid": [last.get("valid_from"), last.get("valid_to")],
                  "snapshot_ref": last.get("screenshot_or_snapshot_ref"), "source_ref": last.get("source_ref")}
            off.review("wrong_offer", ent, f"Does sitelink {aid}'s promise contradict the page offer valid for the period?",
                       evidence=ev,
                       outcomes={"wrong_offer": {"severity": "Warning", "recommendation":
                                                 "Correct the sitelink text or destination; quote both sides."},
                                 "consistent": {"severity": None, "recommendation": "No action."},
                                 "uncertain": {"severity": "Info", "recommendation": "Request a fresh page capture."}},
                       guidance="wrong_offer needs proposal {sitelink_quote, page_quote} copied verbatim from evidence.")

    # step 5 (index #81)
    err = ctx.check("destination_errors", later[3][1], {DEST: ["asset_id", "original_url", "http_status", "device",
                                                               "locale", "check_at"]})
    if err.runnable:
        for aid, s in sorted(sitelinks.items()):
            url = _first_url(s["row"].get(t_map["final_url"]))
            scopes: dict[tuple, list] = {}
            for r in by_asset.get(aid, []):
                d = V.parse_date(r.get("check_at"))
                if str(r.get("original_url") or "").strip() != (url or "") or not _in_window(ctx, d):
                    continue
                code = V.integer(r.get("http_status"))
                scopes.setdefault((str(r.get("device")), str(r.get("locale"))), []).append((str(r.get("check_at")), code))
            for (dev, loc), tests in sorted(scopes.items()):
                tests.sort()
                known = [(t, c) for t, c in tests if c]
                if not known or known[-1][1] < 400:
                    continue
                fails = sorted({t for t, c in known if c >= 400 and all(not (t2 > t and c2 < 400) for t2, c2 in known)})
                ent = {"asset_id": aid, "device": dev, "locale": loc}
                ev = {"final_url": url, "tests": [{"check_at": t, "http_status": c} for t, c in tests],
                      "failing_checks_without_later_success": fails, "eligible": s["eligible"],
                      "window": [ctx.period_start, ctx.as_of or ctx.snapshot]}
                if s["eligible"] and len(fails) >= 2:
                    err.finding("broken_destination", "Warning", ent,
                                f"Eligible sitelink {aid} URL {url} returned HTTP {known[-1][1]} in {len(fails)} "
                                f"checks ({dev}/{loc}) with no later success", evidence=ev,
                                recommendation="Fix or replace the destination; route broader URL diagnostics to skill-125.",
                                uncertainty="Reproduced for the tested device/locale only; not all historical traffic.")
                else:
                    err.finding("destination_verification_request", "Info", ent,
                                f"Sitelink {aid} URL {url} failed a destination test (HTTP {known[-1][1]}) "
                                f"without reproduction or current eligibility", evidence=ev,
                                recommendation="Re-test on the affected device/locale before acting.",
                                uncertainty="A single snapshot failure does not establish a broken page.")

    _metric_checks(ctx, later, sitelinks, t_map)


def _metric_checks(ctx, later, sitelinks: dict, t_map: dict) -> None:
    """Steps 6-8: need only the metrics file; eligibility/homepage context is attached when the spine ran."""
    m_t = ctx.table(METRICS)
    ctr = ctx.check("contextual_ctr", later[4][1], {METRICS: MET_COLS})
    cohorts: dict[tuple[str, str], dict[str, dict]] = {}
    if ctr.runnable:
        extra = [c for c in ("conversions", "cost", "attribution_definition") if c not in m_t.columns]
        if extra:
            ctr.partial("conversion context not exported", [f"{METRICS}:{c}" for c in extra])
        excluded = 0
        for r in ctx.rows(METRICS):
            d = V.parse_date(r.get("date"))
            if d is None or (ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end):
                excluded += 1
                continue
            scope = V.norm_text(r.get("click_scope")).replace("_", "-")
            key = (str(r.get("association_key")), str(r.get("segment")))
            acc = cohorts.setdefault(key, {}).setdefault(str(r.get("asset_id")), {
                "impressions": 0.0, "asset_clicks": 0.0, "all_ad_clicks": 0.0, "conversions": 0.0, "unknown": 0})
            imp, clk = V.num(r.get("impressions")), V.num(r.get("clicks"))
            if scope.startswith("asset"):
                if imp is None or clk is None:
                    acc["unknown"] += 1
                else:
                    acc["impressions"] += imp
                    acc["asset_clicks"] += clk
                    acc["conversions"] += V.num(r.get("conversions")) or 0
            elif scope.startswith("all"):
                acc["all_ad_clicks"] += clk or 0
            else:
                acc["unknown"] += 1
        if excluded:
            ctr.partial(f"{excluded} metric rows outside the report window or undated excluded")
        for (ak, seg), assets in sorted(cohorts.items()):
            for aid, m in sorted(assets.items()):
                ctr.observe(f"Sitelink {aid} @ {ak} [{seg}]: asset-only CTR", asset_id=aid, association_key=ak,
                            segment=seg, asset_clicks=m["asset_clicks"], impressions=m["impressions"],
                            ctr=V.ratio(m["asset_clicks"], m["impressions"]), all_ad_clicks_separate=m["all_ad_clicks"],
                            unknown_rows=m["unknown"])

    # step 7
    cmp_ = ctx.check("mature_comparison", later[5][1], {METRICS: MET_COLS})
    if cmp_.runnable:
        mi = ctx.params.get("min_impressions")
        if ctx.mature is not True:
            cmp_.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; no performance prescriptions")
        elif mi.value is None:
            cmp_.partial(f"min_impressions unresolved: {mi.reason}")
        else:
            for (ak, seg), assets in sorted(cohorts.items()):
                for aid, m in sorted(assets.items()):
                    rest_imp = sum(x["impressions"] for k, x in assets.items() if k != aid)
                    rest_clk = sum(x["asset_clicks"] for k, x in assets.items() if k != aid)
                    own, peer = V.ratio(m["asset_clicks"], m["impressions"]), V.ratio(rest_clk, rest_imp)
                    if own is None or peer is None or m["impressions"] < mi.value or rest_imp < mi.value:
                        continue
                    if own >= peer:
                        continue
                    s = sitelinks.get(aid, {})
                    url = _first_url((s.get("row") or {}).get(t_map["final_url"]))
                    cmp_.review("low_contextual_ctr", {"asset_id": aid, "association_key": ak, "segment": seg},
                                f"Is sitelink {aid}'s lower asset-only CTR ({own:.4f} vs peers {peer:.4f}) in "
                                f"{ak}/{seg} a business-performance concern?",
                                evidence={"asset_clicks": m["asset_clicks"], "impressions": m["impressions"], "ctr": own,
                                          "peer_clicks": rest_clk, "peer_impressions": rest_imp, "peer_ctr": peer,
                                          "conversions_asset_scope": m["conversions"], "min_impressions": mi.value,
                                          "min_impressions_source": mi.source, "homepage": _homepage(url),
                                          "window": [ctx.period_start, ctx.period_end]},
                                outcomes={"business_concern": {"severity": "Warning", "recommendation":
                                                               "Test a revised text/destination; do not remove on CTR alone."},
                                          "acceptable": {"severity": None, "recommendation":
                                                         "Keep: low rate coexists with value or a navigational role."},
                                          "uncertain": {"severity": "Info", "recommendation": "Collect downstream outcomes."}},
                                guidance="Compare only within the same association and segment; consider conversions.")

    fx = ctx.check("fix_proposals", later[6][1])
    upstream = [c for c in ctx.result.checks if c.id != "fix_proposals"]
    if all(c.status == "skipped" for c in upstream):
        fx.skip("no upstream sitelink check ran", sorted({m for c in upstream for m in c.missing}))
        return
    counts = {}
    for f in ctx.result.findings:
        counts[f.condition_key] = counts.get(f.condition_key, 0) + 1
    fx.observe("Confirmed findings vs verification requests vs optional opportunities",
               confirmed=counts.get("broken_destination", 0),
               verification_requests=sum(counts.get(k, 0) for k in ("destination_verification_request",
                                                                       "destination_evidence_missing",
                                                                       "offer_verification_needed")),
               optional_opportunities=counts.get("optional_descriptions_absent", 0),
               pending_reviews=len(ctx.result.reviews))


def verify(ctx, item, decision) -> list[str]:
    """Rules: wrong_offer quotes must be verbatim from evidence; homepage links are never removed on CTR."""
    p = decision.get("proposal") or {}
    problems = []
    if item.condition_key == "wrong_offer" and decision.get("outcome") == "wrong_offer":
        sq, pq = str(p.get("sitelink_quote") or "").strip(), str(p.get("page_quote") or "").strip()
        if not sq or sq.lower() not in str(item.evidence.get("sitelink_quote") or "").lower():
            problems.append("proposal.sitelink_quote must be quoted from the sitelink text")
        page = f"{item.evidence.get('page_offer_terms') or ''} {item.evidence.get('page_visible_text') or ''}".lower()
        if not pq or pq.lower() not in page:
            problems.append("proposal.page_quote must be quoted from the page offer_terms/visible_text")
    if item.condition_key == "low_contextual_ctr" and str(p.get("action") or "").lower() == "remove" \
            and item.evidence.get("homepage"):
        problems.append("a homepage sitelink is not removed solely on CTR")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
