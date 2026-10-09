"""check.py — skill-092 deterministic PMax final URL expansion controls, URL origin and destination review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str] | normalize_url(u) -> str
used_by: skills/skill-092-pmax-final-url-expansion-control/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #69 PMax Campaign Settings Alerts (nilsrooijmans.com) — clean-room: final URL expansion status per
         campaign with rule-inventory completeness; "enabled without exclusions" is Info only, never a mandate.
         index #71 PMax Low-Performing Landing Page Alerts (nilsrooijmans.com) — clean-room: landing-page cost vs
         conversions per campaign with spend_floor, maturity, per-campaign tracking and relevance review, plus
         both-side-gated CPA observations; no automatic exclusion or alert email.
rules:   PMax = campaigns.channel_type PERFORMANCE_MAX (key id, alternative campaign_id).
         Expansion status only from pmax_url_settings.final_url_expansion_status (enabled|disabled, anything else
         unknown). Missing settings row = unknown, never disabled.
         pmax_url_rules.rule_type: url_exclusion|exclusion|exclude = exclusion rule; page_feed|page_feed_entry =
         page-feed URL; inventory_complete|no_rules = explicit per-campaign completeness declaration.
         active_status active|enabled = active. Operators equals|contains|starts_with|begins_with only; others
         leave the check partial. Matching runs on normalize_url() strings.
         normalize_url: lowercase scheme/host, drop default port, fragment and tracking params (utm_*, gclid,
         gbraid, wbraid, fbclid, msclkid, dclid); keep every other query param (sorted) and path case.
         Landing-page rows: inside the account period, deduplicated on campaign/date/url/goal_set_id; goal_set_id
         must be in ctx.goal_ids(campaign) when goals are declared.
         Zero-conversion Warning path only via review and only when ctx.mature is True, ctx.tracking_for_campaign
         is True and URL cost >= spend_floor for that campaign. Exposure is never savings.
         Critical only via review with proposal.evidence_ref resolving to the reviewed campaign/URL's
         pmax_destination_review source_reference/provenance_evidence; client review permitted_destination=false
         on a served URL is a deterministic Warning (verified mismatch).
         verify(): a proposed exclusion must match the reviewed URL and must not match any group final URL,
         permitted destination or converting landing page of the campaign.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | Critical evidence_ref must resolve to the reviewed URL's destination review
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

SKILL = "skill-092-pmax-final-url-expansion-control"
VERSION = "1.0.0"

PMAX = "PERFORMANCE_MAX"
GROUPS = "custom/pmax_groups"
SETTINGS = "external/pmax_url_settings"
RULES = "external/pmax_url_rules"
LP = "custom/pmax_landing_pages"
REVIEW = "external/pmax_destination_review"
EXCLUSION_TYPES = {"url_exclusion", "exclusion", "exclude"}
PAGE_FEED_TYPES = {"page_feed", "page_feed_entry"}
DECLARATIONS = {"inventory_complete", "no_rules"}
OPERATORS = {"equals", "contains", "starts_with", "begins_with"}
TRACKING = ("utm_", "gclid", "gbraid", "wbraid", "fbclid", "msclkid", "dclid")
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(u) -> str:
    """Conservative URL normalization (stdlib string ops only). Rules: lowercase scheme/host only; path, query and fragment kept verbatim."""
    s = str(u or "").strip().split("#", 1)[0]
    if not s:
        return ""
    scheme, _, rest = s.partition("://") if "://" in s else ("https", "", s)
    scheme = scheme.lower()
    cut = min([i for i in (rest.find("/"), rest.find("?")) if i >= 0], default=len(rest))
    host, tail = rest[:cut].lower(), rest[cut:]
    if ":" in host and host.rsplit(":", 1)[1] == _DEFAULT_PORTS.get(scheme):
        host = host.rsplit(":", 1)[0]
    path, _, query = tail.partition("?")
    params = sorted(p for p in query.split("&") if p and not p.split("=", 1)[0].lower().startswith(TRACKING))
    return f"{scheme}://{host}{path.rstrip('/') or '/'}" + (f"?{'&'.join(params)}" if params else "")


def _key_col(ctx) -> str:
    t = ctx.table("campaigns")
    return "campaign_id" if t is not None and "id" not in t.columns and "campaign_id" in t.columns else "id"


def _pmax(ctx) -> list[str]:
    kc = _key_col(ctx)
    return sorted(str(r.get(kc)) for r in ctx.rows("campaigns") if str(r.get("channel_type") or "").upper() == PMAX)


def _t(v) -> str:
    return V.norm_text(v).replace(" ", "_").replace("-", "_")


def _rule_matches(op: str, pattern: str, url: str) -> bool | None:
    op, pat = _t(op), normalize_url(pattern) if "://" in str(pattern or "") else str(pattern or "").strip().lower()
    target = url.lower() if "://" not in str(pattern or "") else url
    if op == "equals":
        return target == pat
    if op == "contains":
        return pat in target
    if op in ("starts_with", "begins_with"):
        return target.startswith(pat)
    return None


def _configured(ctx, cid) -> set[str]:
    out = set()
    for g in ctx.rows(GROUPS):
        if str(g.get("campaign_id")) == cid:
            for col in ("final_urls", "final_mobile_urls"):
                out |= {normalize_url(u) for u in V.split_list(g.get(col), (" | ", ";", "|", ","))}
    return out - {""}


def _page_feed(ctx, cid) -> set[str]:
    return {normalize_url(r.get("url_or_pattern")) for r in ctx.rows(RULES)
            if str(r.get("campaign_id")) == cid and _t(r.get("rule_type")) in PAGE_FEED_TYPES
            and r.get("url_or_pattern")}


def _reviews(ctx, cid) -> dict[str, dict]:
    out = {}
    for r in sorted(ctx.rows(REVIEW), key=lambda r: str(r.get("canonical_url"))):
        if str(r.get("campaign_id")) != cid:
            continue
        for col in ("canonical_url", "resolved_url"):
            if r.get(col):
                out.setdefault(normalize_url(r.get(col)), r)
    return out


def _lp_rows(ctx, chk=None) -> dict[str, dict[str, dict]]:
    """campaign -> normalized url -> summed metrics (deduplicated, in period, goal-matched)."""
    t = ctx.table(LP)
    seen, out, dups, off_goal = set(), {}, 0, 0
    for r in sorted(t.rows, key=lambda r: (str(r.get("campaign_id")), str(r.get("date")), str(r.get("reported_url")))):
        cid, d = str(r.get("campaign_id")), V.parse_date(r.get("date"))
        if d is None or (ctx.period_start and d < ctx.period_start) or (ctx.period_end and d > ctx.period_end):
            continue
        g = (cid, d, str(r.get("reported_url")), str(r.get("goal_set_id")))
        if g in seen:
            dups += 1
            continue
        seen.add(g)
        goals = ctx.goal_ids(cid)
        if goals and r.get("goal_set_id") is not None and str(r.get("goal_set_id")) not in goals:
            off_goal += 1
            continue
        url = normalize_url(r.get("reported_url"))
        acc = out.setdefault(cid, {}).setdefault(url, {"impressions": 0.0, "clicks": 0.0, "cost": 0.0,
                                                       "conversions": 0.0, "unknown": set(), "provenance": set(),
                                                       "expanded": set(), "days": set()})
        for m in ("impressions", "clicks", "cost", "conversions"):
            v = ctx.money(r.get(m)) if m == "cost" else V.num(r.get(m))
            if v is None:
                acc["unknown"].add(m)
            else:
                acc[m] += v
        acc["provenance"].add(_t(r.get("provenance")) or "unknown")
        if r.get("expanded_url"):
            acc["expanded"].add(normalize_url(r.get("expanded_url")))
        acc["days"].add(d)
    if chk is not None:
        if dups:
            chk.partial(f"{dups} duplicate landing-page rows skipped")
        if off_goal:
            chk.partial(f"{off_goal} landing-page rows on non-campaign goals excluded")
    return out


def _metrics_out(m: dict) -> dict:
    return {k: (None if k in m["unknown"] else m[k]) for k in ("impressions", "clicks", "cost", "conversions")} | {
        "days": len(m["days"]), "provenance": sorted(m["provenance"])}


def run(ctx) -> None:
    """Run PMax expansion settings, URL origin, destination fit, exclusion, performance and control-proposal checks.

    Rules:   No PERFORMANCE_MAX campaign in a complete inventory → all 6 checks not applicable. Unknown/conflicting
             expansion status or undeclared rule inventory → partial; expansion without exclusions and unknown origin → Info.
             Only permitted_destination=false is a deterministic Warning; zero-conversion ai_review needs ctx.mature,
             tracking and cost >= spend_floor; CPA stays observe-only; control proposals only for reviewed destinations.
    """
    kc = _key_col(ctx)
    pmax = _pmax(ctx)
    ids = [("expansion_settings", "Final URL expansion and page-feed controls per campaign"),
           ("url_origin", "Reported URLs vs configured/approved sources"),
           ("destination_fit", "Destinations vs approved objectives and page reviews"),
           ("exclusion_rules", "Exclusion rules vs observed and intended URLs"),
           ("destination_performance", "Mature destination exposure and zero-conversion review"),
           ("control_proposal", "Minimal evidence-bound control proposals")]
    camps = ctx.table("campaigns")
    if camps is not None and not camps.missing([kc, "channel_type"]) and not pmax:
        for cid, title in ids:
            ctx.check(cid, title).not_applicable("no Performance Max campaigns")
        return

    st = ctx.check(ids[0][0], ids[0][1], {"campaigns": [kc, "channel_type"],
                                          SETTINGS: ["campaign_id", "final_url_expansion_status", "source_reference",
                                                     "observed_at"]})
    if st.runnable:
        _settings(ctx, st, pmax)

    lp_need = {LP: ["campaign_id", "date", "reported_url", "provenance", "impressions", "clicks", "cost",
                    "conversions", "goal_set_id"]}
    og = ctx.check(ids[1][0], ids[1][1], {"campaigns": [kc, "channel_type"], **lp_need,
                                          GROUPS: ["campaign_id", "asset_group_id", "final_urls"]})
    lp = _lp_rows(ctx, og) if og.runnable else {}
    if og.runnable:
        _origin(ctx, og, pmax, lp)

    df = ctx.check(ids[2][0], ids[2][1], {**lp_need, REVIEW: ["campaign_id", "canonical_url", "tested_at",
                                                              "page_purpose", "approved_objectives",
                                                              "permitted_destination", "provenance_evidence"]})
    if df.runnable:
        _destinations(ctx, df, pmax, lp or _lp_rows(ctx))

    ex = ctx.check(ids[3][0], ids[3][1], {RULES: ["campaign_id", "rule_or_feed_entry_id", "rule_type", "operator",
                                                  "url_or_pattern", "active_status"],
                                          GROUPS: ["campaign_id", "asset_group_id", "final_urls"]})
    if ex.runnable:
        _exclusions(ctx, ex, pmax, lp if og.runnable else (_lp_rows(ctx) if ctx.table(LP) else {}))

    perf = ctx.check(ids[4][0], ids[4][1], {"campaigns": [kc, "channel_type"], **lp_need})
    if perf.runnable:
        _performance(ctx, perf, pmax, lp or _lp_rows(ctx))

    prop = ctx.check(ids[5][0], ids[5][1])
    eligible = sorted(r.id for r in ctx.result.reviews if r.condition_key in (
        "destination_offer_mismatch", "destination_objective_fit", "mature_zero_conversion_destination"))
    if not (df.runnable or perf.runnable):
        prop.skip("destination checks unavailable; no verified destination problem", sorted(set(df.missing) | set(perf.missing)))
    elif not eligible:
        prop.not_applicable("no verified destination problem; do not disable expansion only because no exclusions exist")
    else:
        prop.observe("Control proposals allowed only for these reviewed destinations; health/policy go to 125/141",
                     reviews=eligible)


def _settings(ctx, chk, pmax) -> None:
    by = {}
    for r in ctx.rows(SETTINGS):
        by.setdefault(str(r.get("campaign_id")), []).append(r)
    rules_t = ctx.table(RULES)
    for cid in pmax:
        rows = by.get(cid, [])
        states = {_t(r.get("final_url_expansion_status")) for r in rows}
        status = states.pop() if len(states) == 1 else "conflicting" if states else "unknown"
        status = status if status in ("enabled", "disabled", "conflicting") else "unknown"
        rules = [r for r in (rules_t.rows if rules_t else []) if str(r.get("campaign_id")) == cid]
        declared = sorted({_t(r.get("rule_type")) for r in rules} & DECLARATIONS)
        active_excl = [r for r in rules if _t(r.get("rule_type")) in EXCLUSION_TYPES
                       and _t(r.get("active_status")) in ("active", "enabled")]
        page_feeds = sorted({v for r in rows for v in V.split_list(r.get("page_feed_ids"), (";", "|", ","))})
        data = {"campaign_id": cid, "expansion_status": status, "rule_inventory_declared": declared,
                "active_exclusions": len(active_excl), "page_feed_ids": page_feeds,
                "configured_final_urls": len(_configured(ctx, cid)),
                "source_reference": sorted({str(r.get("source_reference")) for r in rows if r.get("source_reference")}),
                "observed_at": sorted({str(r.get("observed_at")) for r in rows if r.get("observed_at")})}
        chk.observe(f"PMax {cid}: final URL expansion {status}", **data)
        if status in ("unknown", "conflicting"):
            chk.partial(f"PMax {cid}: expansion status {status}")
            continue
        if status == "enabled" and not active_excl:
            if not declared:
                chk.partial(f"PMax {cid}: rule inventory not declared complete; absence of exclusions unproven")
                continue
            chk.finding("expansion_enabled_without_exclusions", "Info", {"campaign_id": cid},
                        f"PMax {cid} has final URL expansion enabled and a declared-complete rule inventory with "
                        f"no active URL exclusions", evidence=data,
                        recommendation="Optional control opportunity; add exclusions only for a verified destination "
                                       "problem.",
                        uncertainty="No exclusions is not a defect; expansion may serve the objective.")


def _origin(ctx, chk, pmax, lp) -> None:
    metrics = {str(r.get("campaign_id")): r for r in ctx.rows("campaign_metrics")}
    if ctx.table(LP).complete is not True:
        chk.partial("landing-page report completeness not certified; unmatched rows may be incomplete")
    for cid in pmax:
        urls = lp.get(cid, {})
        if not urls:
            continue
        conf, feed, rev = _configured(ctx, cid), _page_feed(ctx, cid), _reviews(ctx, cid)
        classes: dict = {}
        unknown = []
        for url, m in sorted(urls.items()):
            if url in conf:
                c = "configured_final_url"
            elif url in feed:
                c = "page_feed"
            elif m["expanded"] or "expanded" in m["provenance"]:
                c = "platform_reported_expansion"
            elif url in rev and V.boolean(rev[url].get("permitted_destination")):
                c = "reviewed_permitted_destination"
            else:
                c = "unknown_origin"
            classes.setdefault(c, {"urls": 0, "clicks": 0.0, "cost": 0.0})
            classes[c]["urls"] += 1
            classes[c]["clicks"] += m["clicks"]
            classes[c]["cost"] += m["cost"]
            if c == "unknown_origin":
                unknown.append({"url": url, **_metrics_out(m)})
        lp_clicks = sum(m["clicks"] for m in urls.values())
        camp_clicks = V.num((metrics.get(cid) or {}).get("clicks"))
        chk.observe(f"PMax {cid}: reported URL origin classes", campaign_id=cid, classes=classes,
                    landing_page_clicks=lp_clicks, campaign_clicks=camp_clicks,
                    click_coverage=V.ratio(lp_clicks, camp_clicks), window=[ctx.period_start, ctx.period_end])
        if unknown:
            chk.finding("unknown_url_origin", "Info", {"campaign_id": cid},
                        f"{len(unknown)} reported URLs of PMax {cid} match no configured, page-feed or reviewed "
                        f"source and carry no expansion provenance",
                        evidence={"urls": sorted(unknown, key=lambda x: (-(x["cost"] or 0), x["url"]))[:50]},
                        calculation={"unknown_cost": classes["unknown_origin"]["cost"],
                                     "landing_page_cost": sum(m["cost"] for m in urls.values())},
                        recommendation="Label as destination-only traffic; request provenance before any control.",
                        uncertainty="Unknown origin is not proof of expansion (product-feed links, redirects).")


def _destinations(ctx, chk, pmax, lp) -> None:
    unreviewed = 0
    for cid in pmax:
        rev = _reviews(ctx, cid)
        for url, m in sorted(lp.get(cid, {}).items()):
            if not m["impressions"]:
                continue
            r = rev.get(url)
            if r is None:
                unreviewed += 1
                continue
            entity = {"campaign_id": cid, "url": url}
            ev = {"served": _metrics_out(m), "page_purpose": r.get("page_purpose"),
                  "approved_objectives": r.get("approved_objectives"), "offer_facts": r.get("offer_facts"),
                  "permitted_destination": r.get("permitted_destination"), "tested_at": r.get("tested_at"),
                  "resolved_url": r.get("resolved_url"), "provenance_evidence": r.get("provenance_evidence"),
                  "review_owner": r.get("review_owner"), "window": [ctx.period_start, ctx.period_end]}
            permitted = V.boolean(r.get("permitted_destination"))
            if permitted is False:
                f = chk.finding("destination_offer_mismatch", "Warning", entity,
                                f"Served URL {url} of PMax {cid} is marked not permitted by the client destination review",
                                evidence=ev, recommendation="Review the minimal control (exclusion) for this URL; "
                                                            "delegate policy/health to 141/125.",
                                uncertainty="Review date vs serving window; historical cost is exposure, not savings.")
                chk.review("destination_offer_mismatch", entity,
                           f"Is {url} a prohibited/unsafe destination with MATERIAL current serving?", evidence=ev,
                           provisional=f,
                           outcomes={"prohibited_material": {"severity": "Critical", "recommendation":
                                                             "Prioritize a bounded exclusion; cite the evidence."},
                                     "offer_mismatch": {"severity": "Warning", "recommendation":
                                                        "Propose the minimal exclusion or page fix."}},
                           guidance="prohibited_material needs proposal.evidence_ref. Optional proposal.exclusion "
                                    "{operator, url_or_pattern} is collision-checked.")
            elif permitted is None:
                chk.review("destination_objective_fit", entity,
                           f"Does served URL {url} contradict PMax {cid}'s approved objectives or offer?", evidence=ev,
                           outcomes={"offer_mismatch": {"severity": "Warning", "recommendation":
                                                        "Propose the minimal control after owner review."},
                                     "legitimate": {"severity": None, "recommendation":
                                                    "Keep; editorial/support pages can serve consideration goals."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask the review owner."}},
                           guidance="Judge the page snapshot, not path keywords. Optional proposal.exclusion is "
                                    "collision-checked.")
    if unreviewed:
        chk.partial(f"{unreviewed} served URLs have no destination review; page intent not diagnosed from paths")


def _exclusions(ctx, chk, pmax, lp) -> None:
    unsupported = 0
    collisions = 0
    for cid in pmax:
        rules = [r for r in ctx.rows(RULES) if str(r.get("campaign_id")) == cid
                 and _t(r.get("rule_type")) in EXCLUSION_TYPES and _t(r.get("active_status")) in ("active", "enabled")]
        intended = {u: "configured_final_url" for u in _configured(ctx, cid)}
        for u, r in _reviews(ctx, cid).items():
            if V.boolean(r.get("permitted_destination")):
                intended.setdefault(u, "permitted_destination")
        for rule in sorted(rules, key=lambda r: str(r.get("rule_or_feed_entry_id"))):
            if _t(rule.get("operator")) not in OPERATORS:
                unsupported += 1
                continue
            hits = sorted(u for u in intended if _rule_matches(rule.get("operator"), rule.get("url_or_pattern"), u))
            served = sorted(u for u in lp.get(cid, {}) if lp[cid][u]["impressions"]
                            and _rule_matches(rule.get("operator"), rule.get("url_or_pattern"), u))
            if served:
                chk.observe(f"PMax {cid}: URLs served in window although rule {rule.get('rule_or_feed_entry_id')} "
                            f"now excludes them (rule timing unknown)", campaign_id=cid, urls=served[:50],
                            rule_observed_at=rule.get("observed_at"))
            if not hits:
                continue
            collisions += 1
            entity = {"campaign_id": cid, "rule_id": rule.get("rule_or_feed_entry_id")}
            ev = {"operator": rule.get("operator"), "url_or_pattern": rule.get("url_or_pattern"),
                  "colliding_urls": {u: intended[u] for u in hits}, "source_reference": rule.get("source_reference")}
            prov = chk.finding("exclusion_collides_valid_destination", "Info", entity,
                               f"Active exclusion {rule.get('rule_or_feed_entry_id')} matches {len(hits)} intended "
                               f"destinations of PMax {cid}", evidence=ev,
                               recommendation="Confirm whether the exclusion is deliberate; narrow it if not.",
                               uncertainty="Exclusions mainly govern expansion; configured-URL effect depends on setup.")
            chk.review("exclusion_collides_valid_destination", entity,
                       f"Does exclusion {rule.get('rule_or_feed_entry_id')} unintentionally block valid destinations?",
                       evidence=ev, provisional=prov,
                       outcomes={"unintended_collision": {"severity": "Warning", "recommendation":
                                                          "Narrow the rule to the minimum verified scope."},
                                 "intended_exclusion": {"severity": None, "recommendation": "Keep; document."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the rule owner."}})
        chk.observe(f"PMax {cid}: active exclusion rules evaluated", campaign_id=cid, active_rules=len(rules),
                    intended_urls=len(intended))
    if unsupported:
        chk.partial(f"{unsupported} rules with unsupported operators not evaluated")


def _performance(ctx, chk, pmax, lp) -> None:
    mins = ctx.params.get("min_conversions")
    for cid in pmax:
        urls = lp.get(cid, {})
        if not urls:
            continue
        floor = ctx.params.get("spend_floor", cid)
        tracking, tnote = ctx.tracking_for_campaign(cid)
        zero_ok = ctx.mature is True and tracking is True and floor.value is not None
        if not zero_ok:
            chk.partial(f"PMax {cid}: zero-conversion review disabled (mature={ctx.mature}; {tnote}; "
                        f"spend_floor {floor.value if floor.value is not None else floor.reason})")
        tot_cost = sum(m["cost"] for m in urls.values())
        tot_conv = sum(m["conversions"] for m in urls.values())
        for url, m in sorted(urls.items()):
            if m["unknown"] & {"cost", "conversions"}:
                chk.partial(f"PMax {cid} {url}: unknown cost/conversions")
                continue
            ev = {"metrics": _metrics_out(m), "window": [ctx.period_start, ctx.period_end],
                  "spend_floor": floor.value, "spend_floor_source": floor.source or floor.reason,
                  "tracking": tnote, "mature": ctx.mature}
            if zero_ok and m["conversions"] == 0 and m["cost"] >= floor.value:
                entity = {"campaign_id": cid, "url": url}
                prov = chk.finding("mature_zero_conversion_destination", "Info", entity,
                                   f"{url} spent {m['cost']:.2f} {ctx.currency or ''} with 0 conversions in a mature "
                                   f"window (spend_floor {floor.value:g})", evidence=ev,
                                   recommendation="Review relevance and tracking before any control; exposure is not savings.",
                                   uncertainty="Zero conversions can reflect lag, assisted value or consideration goals.")
                chk.review("mature_zero_conversion_destination", entity,
                           f"Is {url} (PMax {cid}) an irrelevant or mismatched destination for the approved objective?",
                           evidence={**ev, "destination_review": (_reviews(ctx, cid).get(url) or {}).get("page_purpose")},
                           provisional=prov,
                           outcomes={"irrelevant_or_mismatch": {"severity": "Warning", "recommendation":
                                                                "Contextual review; propose a minimal exclusion only "
                                                                "with verified page evidence."},
                                     "relevant_keep": {"severity": None, "recommendation": "Keep serving."},
                                     "uncertain": {"severity": "Info", "recommendation": "Request a page review."}},
                           guidance="Do not judge from path keywords; optional proposal.exclusion is collision-checked.")
            rest_cost, rest_conv = tot_cost - m["cost"], tot_conv - m["conversions"]
            if ctx.mature is True and m["conversions"] >= mins.value and rest_conv >= mins.value:
                chk.observe(f"PMax {cid} {url}: CPA vs rest of campaign landing pages (both sides gated)",
                            campaign_id=cid, url=url, url_cpa=V.ratio(m["cost"], m["conversions"]),
                            rest_cpa=V.ratio(rest_cost, rest_conv), url_conversions=m["conversions"],
                            rest_conversions=rest_conv, min_conversions=mins.value)
        chk.observe(f"PMax {cid}: landing-page totals", campaign_id=cid, urls=len(urls), cost=tot_cost,
                    conversions=tot_conv, cpa=V.ratio(tot_cost, tot_conv))


_PLACEHOLDER_REFS = {"", "none", "n/a", "na", "-", "null"}


def _ref_problem(ctx, item, ref: str) -> str | None:
    """Resolve ref against the destination-review row of the reviewed campaign/URL (tested in or after the window)."""
    cid, url = str(item.entity.get("campaign_id")), item.entity.get("url")
    if V.norm_text(ref) in _PLACEHOLDER_REFS:
        return f"evidence_ref '{ref}' is not a resolvable reference"
    for r in ctx.rows(REVIEW):
        if str(r.get("campaign_id")) != cid or ref not in {str(r.get(c) or "").strip() for c in
                                                           ("source_reference", "provenance_evidence")}:
            continue
        if url not in {normalize_url(r.get(c)) for c in ("canonical_url", "resolved_url") if r.get(c)}:
            continue
        tested = V.parse_date(r.get("tested_at"))
        if tested is None or (ctx.period_start is not None and tested < ctx.period_start):
            return f"evidence_ref {ref} review for {url} was not tested in or after the reviewed window"
        return None
    return f"evidence_ref {ref} not found for campaign {cid} URL {url} in {REVIEW}"


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   prohibited_material (Critical) requires proposal.evidence_ref equal to the source_reference or
             provenance_evidence of an external/pmax_destination_review row for the same campaign whose
             canonical_url/resolved_url normalizes to the reviewed URL and whose tested_at is on/after the period
             start; placeholder refs (none, n/a, -) never resolve. Any proposed exclusion must hit the reviewed URL
             and spare group final URLs, permitted destinations and converting landing pages.
    """
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    problems = []
    if outcome == "prohibited_material":
        ref = str(proposal.get("evidence_ref") or "").strip()
        if not ref:
            problems.append("prohibited_material needs proposal.evidence_ref")
        elif (p := _ref_problem(ctx, item, ref)) is not None:
            problems.append(p)
    excl = proposal.get("exclusion")
    if not excl or "url" not in item.entity:
        return problems
    op, pat = excl.get("operator"), excl.get("url_or_pattern")
    if _t(op) not in OPERATORS or not pat:
        return problems + [f"exclusion needs operator in {sorted(OPERATORS)} and url_or_pattern"]
    cid, url = str(item.entity["campaign_id"]), item.entity["url"]
    if not _rule_matches(op, pat, url):
        problems.append(f"exclusion '{pat}' ({op}) does not match reviewed URL {url}")
    protected = set(_configured(ctx, cid))
    protected |= {u for u, r in _reviews(ctx, cid).items() if V.boolean(r.get("permitted_destination"))}
    if ctx.table(LP) is not None:
        protected |= {u for u, m in _lp_rows(ctx).get(cid, {}).items() if m["conversions"] > 0 and u != url}
    problems += [f"exclusion '{pat}' would also block protected URL {u}" for u in sorted(protected)
                 if u != url and _rule_matches(op, pat, u)]
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
