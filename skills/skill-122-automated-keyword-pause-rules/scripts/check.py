"""check.py — skill-122 deterministic zero-conversion keyword screen and review-first pause-rule draft.

exports: SKILL | VERSION | run(ctx) -> None
used_by: skills/skill-122-automated-keyword-pause-rules/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Candidates: ENABLED keyword (keyword_metrics joined to keywords on campaign/ad-group/keyword IDs) with literal
         conversions == 0 and cost >= spend_floor resolved for ITS campaign. min_conversions never applies here.
         Warning only through ai_review outcome 'unexplained_zero_conversion', offered ONLY when ctx.mature is True,
         the policy window matches (approved_lookback_days == period length, snapshot - period_end >= lag_buffer_days),
         ctx.tracking_for_campaign is True with no lifecycle tracking incident in the window, and a policy row gives
         strategic scope. Otherwise the candidate is an Info finding naming the unmet gates.
         Brand (profile.brand_terms + policy brand_terms, literal phrase containment) and policy strategic_keyword_ids
         are excluded before screening. Keywords younger than minimum_active_age_days are excluded too.
         Unknown lifecycle blocks only the age-dependent rule proposal, never the exposure inventory.
         Optional profile heuristics (no universal defaults): keyword_pause_near_floor_ratio (0<r<1) enables the
         'approaching the floor' Info screen; keyword_low_ctr_threshold (fraction) enables the 'low CTR alone' Info
         screen, gated by min_impressions.
         Output is a request-only rule specification; no pause, rule installation or notification.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks13 | initial deterministic check
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
from adsrun.negatives import blocks  # noqa: E402

SKILL = "skill-122-automated-keyword-pause-rules"
VERSION = "1.0.0"

POLICY = "external/keyword_rule_policy"
LIFECYCLE = "custom/keyword_lifecycle"
_ALL = ("", "*", "all", "account")


def _policy_for(ctx, cid: str) -> dict | None:
    rows = ctx.rows(POLICY)
    exact = [r for r in rows if str(r.get("campaign_id") or "").strip() == cid]
    if exact:
        return sorted(exact, key=lambda r: str(r.get("rule_id")))[0]
    generic = [r for r in rows if str(r.get("campaign_id") or "").strip().lower() in _ALL]
    return sorted(generic, key=lambda r: str(r.get("rule_id")))[0] if generic else None


def _window(ctx, pol: dict | None) -> tuple[bool | None, str]:
    if pol is None:
        return None, "no keyword_rule_policy row: lookback/lag buffer unknown"
    look, buf = V.integer(pol.get("approved_lookback_days")), V.integer(pol.get("lag_buffer_days"))
    if look is None or buf is None or ctx.period_start is None or ctx.period_end is None or ctx.snapshot is None:
        return None, "approved_lookback_days, lag_buffer_days, period or snapshot unknown"
    days = (ctx.period_end - ctx.period_start).days + 1
    gap = (ctx.snapshot - ctx.period_end).days
    problems = []
    if days != look:
        problems.append(f"metric window {days}d != approved lookback {look}d (re-export)")
    if gap < buf:
        problems.append(f"window ends {gap}d before snapshot < lag buffer {buf}d")
    return (False, "; ".join(problems)) if problems else (True, f"{days}d window ending {gap}d before snapshot (buffer {buf}d)")


def _terms(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x]
    return V.split_list(v, (";", "|", ","))


def run(ctx) -> None:
    """Run policy window, zero-conversion exposure screen, exclusions, tracking gates and rule-draft checks.

    Rules:   Candidates: ENABLED keyword, conversions == 0, cost >= spend_floor of its campaign (min_conversions never
             applies). Brand/strategic/too-young keywords are excluded first. Warning only via ai_review
             'unexplained_zero_conversion', offered when mature, policy window matches, tracking True without incident
             and a policy row exists; otherwise Info naming unmet gates. Near-floor/low-CTR screens are Info and only
             with profile thresholds. No pause or rule install.
    """
    kw_needs = {"keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "cost", "conversions"],
                "keywords": ["id", "campaign_id", "ad_group_id", "text", "status"]}

    # -- step 1: policy lookback / lag buffer and per-campaign spend floor
    pw = ctx.check("policy_window", "Resolve spend floor and policy lookback/lag buffer",
                   {POLICY: ["rule_id", "campaign_id", "approved_lookback_days", "lag_buffer_days"]})
    policy_ok = pw.runnable

    screen = ctx.check("exposure_screen", "Mature zero-conversion exposure at the spend floor", kw_needs)
    excl = ctx.check("exclusions", "Brand/strategic and minimum-age exclusions")
    track = ctx.check("tracking_intent", "Working conversion tracking and CTR sample", {"conversion_actions": ["id", "status"]})
    draft = ctx.check("rule_draft", "Review-first rule specification",
                      {POLICY: ["rule_id", "campaign_id", "owner", "approval_status", "review_cadence", "rule_cap",
                                "minimum_active_age_days"]})
    if not screen.runnable:
        for c in (excl, track, draft):
            if c.runnable:
                c.skip("keyword exposure inventory unavailable", screen.missing)
        if pw.runnable:
            pw.observe("Policy rows read; no keyword inventory to screen", rows=len(ctx.rows(POLICY)))
        return
    if ctx.mature is not True:
        screen.partial(f"zero-conversion Warning path disabled: maturity {ctx.mature} ({ctx.maturity_note})")

    # -- join metrics to keywords by IDs
    kws = {(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id"))): k for k in ctx.rows("keywords")}
    agg: dict[tuple, dict] = {}
    unmatched = 0
    for r in ctx.rows("keyword_metrics"):
        key = (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("keyword_id")))
        if key not in kws:
            unmatched += 1
            continue
        a = agg.setdefault(key, {"cost": 0.0, "conversions": 0.0, "impressions": 0.0, "clicks": 0.0, "rows": 0,
                                 "unknown": set()})
        a["rows"] += 1
        for col in ("cost", "conversions", "impressions", "clicks"):
            v = ctx.money(r.get(col)) if col == "cost" else V.num(r.get(col))
            if v is None:
                a["unknown"].add(col)
            else:
                a[col] += v
    if unmatched:
        screen.partial(f"{unmatched} keyword_metrics rows without an ID match in keywords")
    if any(a["rows"] > 1 for a in agg.values()):
        screen.partial("some keywords have several metric rows; summed as disjoint segments")

    brand = _terms(ctx.profile.get("brand_terms"))
    life_rows = {}
    if ctx.table(LIFECYCLE) is not None and not ctx.table(LIFECYCLE).missing(["campaign_id", "ad_group_id", "keyword_id"]):
        life_rows = {(str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("keyword_id"))): r
                     for r in ctx.rows(LIFECYCLE)}
    else:
        excl.partial("keyword lifecycle unknown: age-dependent rule proposal blocked; exposure inventory continues",
                     [f"{LIFECYCLE} (file)"] if ctx.table(LIFECYCLE) is None else
                     [f"{LIFECYCLE}:{c}" for c in ctx.table(LIFECYCLE).missing(["campaign_id", "ad_group_id", "keyword_id"])])
    if not policy_ok:
        excl.partial("strategic keyword scope unknown (no keyword_rule_policy)", pw.missing)

    near_ratio = V.num(ctx.profile.get("keyword_pause_near_floor_ratio"))
    near_ratio = near_ratio if near_ratio is not None and 0 < near_ratio < 1 else None
    if near_ratio is None:
        screen.partial("approaching-floor screen off: profile.keyword_pause_near_floor_ratio not declared (0<r<1)")
    low_ctr = ctx.rate(ctx.profile.get("keyword_low_ctr_threshold")) if ctx.profile.get("keyword_low_ctr_threshold") is not None else None
    min_impr = ctx.params.get("min_impressions")
    if low_ctr is None:
        track.partial("low-CTR screen off: profile.keyword_low_ctr_threshold not declared")

    windows: dict[str, tuple] = {}
    tracking: dict[str, tuple] = {}
    unresolved_floor: set[str] = set()
    candidates: dict[str, list[str]] = {}
    excluded = {"brand": 0, "strategic": 0, "young": 0, "not_enabled": 0}
    ctr_screened = 0
    for key in sorted(agg):
        cid, gid, kid = key
        k, a = kws[key], agg[key]
        if str(k.get("status") or "").upper() != "ENABLED":
            excluded["not_enabled"] += 1
            continue
        text = str(k.get("text") or "")
        pol = _policy_for(ctx, cid) if policy_ok else None
        entity = {"campaign_id": cid, "ad_group_id": gid, "keyword_id": kid}
        pol_brand = _terms(pol.get("brand_terms")) if pol else []
        if any(blocks(b, "PHRASE", text) is True for b in brand + pol_brand):
            excluded["brand"] += 1
            excl.observe(f"Keyword {kid} excluded: brand term", **entity, keyword_text=text)
            continue
        if pol and kid in _terms(pol.get("strategic_keyword_ids")):
            excluded["strategic"] += 1
            excl.observe(f"Keyword {kid} excluded: documented strategic keyword", **entity, rule_id=pol.get("rule_id"))
            continue
        life = life_rows.get(key)
        start = V.parse_date(life.get("last_enabled_at")) or V.parse_date(life.get("created_at")) if life else None
        min_age = V.integer(pol.get("minimum_active_age_days")) if pol else None
        age = (ctx.period_end - start).days if start and ctx.period_end else None
        if age is not None and min_age is not None and age < min_age:
            excluded["young"] += 1
            excl.observe(f"Keyword {kid} excluded: active age {age}d < {min_age}d", **entity, active_since=start)
            continue
        cost, conv = (None if "cost" in a["unknown"] else a["cost"]), (None if "conversions" in a["unknown"] else a["conversions"])
        impr, clicks = (None if "impressions" in a["unknown"] else a["impressions"]), (None if "clicks" in a["unknown"] else a["clicks"])
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            unresolved_floor.add(f"{cid}: {floor.reason}")
            continue
        ctr = V.ratio(clicks, impr)
        if conv != 0 or cost is None:
            if low_ctr is not None and impr is not None and min_impr.value and impr >= min_impr.value \
                    and ctr is not None and ctr < low_ctr:
                ctr_screened += 1
                track.finding("low_ctr_only", "Info", entity,
                              f"Keyword {kid} CTR {ctr:.2%} below the declared {low_ctr:.2%} with {impr:g} impressions",
                              evidence={"text": text, "impressions": impr, "clicks": clicks, "ctr": ctr,
                                        "threshold": low_ctr, "threshold_source": "profile.keyword_low_ctr_threshold",
                                        "min_impressions": min_impr.value, "conversions": conv},
                              recommendation="Review ad/keyword relevance; low CTR alone is not a pause reason.",
                              uncertainty="CTR depends on position, format and query mix.")
            continue
        if cost < floor.value:
            if near_ratio is not None and cost >= near_ratio * floor.value:
                screen.finding("zero_conversion_near_floor", "Info", entity,
                               f"Keyword {kid} spent {cost:.2f} {ctx.currency} with 0 conversions, approaching the "
                               f"{floor.value:g} floor",
                               evidence={"text": text, "cost": cost, "spend_floor": floor.value,
                                         "spend_floor_source": floor.source, "near_floor_ratio": near_ratio,
                                         "window": [ctx.period_start, ctx.period_end]},
                               recommendation="Monitor only; below the review floor.",
                               uncertainty="Sub-floor zero-conversion exposure is expected noise.")
            continue
        if cid not in windows:
            windows[cid] = _window(ctx, pol)
            tracking[cid] = ctx.tracking_for_campaign(cid)
        win_ok, win_note = windows[cid]
        tr_ok, tr_note = tracking[cid]
        raw_incidents = _terms(life.get("tracking_incident_dates")) if life else []
        incidents = [d for d in (V.parse_date(x) for x in raw_incidents)
                     if d and ctx.period_start and ctx.period_start <= d <= ctx.period_end]
        changed = V.parse_date(life.get("last_material_change_at")) if life else None
        gates = {"mature": ctx.mature is True, "policy_window": win_ok is True, "tracking": tr_ok is True and not incidents,
                 "strategic_scope_known": pol is not None,
                 "stable_in_window": not (changed and ctx.period_start and changed > ctx.period_start)}
        ev = {"text": text, "match_type": k.get("match_type"), "cost": cost, "conversions": conv, "clicks": clicks,
              "impressions": impr, "ctr": ctr, "ctr_sample_ok": impr is not None and bool(min_impr.value) and impr >= min_impr.value,
              "spend_floor": floor.value, "spend_floor_source": floor.source,
              "window": [ctx.period_start, ctx.period_end], "maturity": ctx.maturity_note, "policy_window": win_note,
              "tracking": tr_note, "tracking_incidents_in_window": incidents, "last_material_change_at": changed,
              "active_age_days": age, "minimum_active_age_days": min_age, "rule_id": pol.get("rule_id") if pol else None,
              "gates": gates}
        candidates.setdefault(cid, []).append(kid)
        unmet = sorted(g for g, ok in gates.items() if not ok)
        if unmet:
            screen.finding("zero_conversion_candidate_gated", "Info", entity,
                           f"Keyword {kid} spent {cost:.2f} {ctx.currency} with 0 conversions (floor {floor.value:g}); "
                           f"Warning path blocked: {', '.join(unmet)}",
                           evidence=ev,
                           recommendation="Resolve the named gates (maturity, policy window, tracking, strategic scope) "
                                          "before any rule proposal; exposure is not savings.",
                           uncertainty="Zero conversions can reflect lag, tracking gaps, long sales cycles or assisted value.")
            continue
        prov = screen.finding("zero_conversion_candidate", "Info", entity,
                              f"Keyword {kid} spent {cost:.2f} {ctx.currency} with 0 conversions in a mature window "
                              f"(floor {floor.value:g})", evidence=ev,
                              recommendation="Relevance/business-role review before any rule proposal.",
                              uncertainty="Historical non-converting cost is exposure, not guaranteed savings.")
        screen.review("zero_conversion_candidate", entity,
                      f"Is the zero-conversion exposure of keyword '{text}' ({kid}, campaign {cid}) unexplained by its "
                      f"approved role, intent or sales cycle?",
                      evidence={**ev, "objectives": ctx.profile.get("objectives"),
                                "campaign_objective": (ctx.profile.get("campaign_objectives") or {}).get(cid),
                                "policy_objective": pol.get("objective")},
                      outcomes={"unexplained_zero_conversion": {"severity": "Warning", "recommendation":
                                "Include in the review-first rule draft; any pause stays a request-only proposal."},
                                "explained_by_role_or_cycle": {"severity": None, "recommendation":
                                "Keep; document the role/sales-cycle reason as a rule exclusion."},
                                "uncertain": {"severity": "Info", "recommendation": "Ask the client for the keyword's role."}},
                      guidance="Judge only with the profile objectives, policy objective and matched intent. Assisted "
                               "value, long sales cycles and upper-funnel roles are not waste.",
                      provisional=prov)
    for u in sorted(unresolved_floor):
        screen.partial(f"spend_floor unresolved for campaign {u}")
    screen.observe("Zero-conversion screen totals", keywords_evaluated=len(agg), candidates=sum(map(len, candidates.values())),
                   excluded=excluded, reviews=sum(1 for x in ctx.result.reviews if x.condition_key == "zero_conversion_candidate"))
    excl.observe("Exclusion totals", **excluded, lifecycle_rows=len(life_rows))
    if track.runnable:
        for cid in sorted(tracking):
            track.observe(f"Campaign {cid}: tracking evidence", campaign_id=cid, working=tracking[cid][0],
                          note=tracking[cid][1], goal_ids=ctx.goal_ids(cid))
            if tracking[cid][0] is not True:
                track.partial(tracking[cid][1])
        track.observe("CTR screen totals", low_ctr_findings=ctr_screened, min_impressions=min_impr.value,
                      threshold=low_ctr)
    if pw.runnable:
        for cid in sorted(windows):
            pw.observe(f"Campaign {cid}: policy window", campaign_id=cid, window_ok=windows[cid][0], note=windows[cid][1],
                       spend_floor=ctx.params.get("spend_floor", cid).value)
            if windows[cid][0] is not True:
                pw.partial(f"campaign {cid}: {windows[cid][1]}")

    # -- step 5: review-first rule specification (request-only)
    if draft.runnable:
        for pol in sorted(ctx.rows(POLICY), key=lambda r: (str(r.get("rule_id")), str(r.get("campaign_id")))):
            pcid = str(pol.get("campaign_id") or "").strip()
            scope = sorted(candidates.get(pcid, [])) if pcid.lower() not in _ALL else \
                sorted(k for c, ks in candidates.items() if _policy_for(ctx, c) is pol for k in ks)
            cap = V.integer(pol.get("rule_cap"))
            missing = [c for c in ("owner", "approval_status", "review_cadence", "rule_cap") if not pol.get(c)]
            if missing:
                draft.partial(f"rule {pol.get('rule_id')}: missing {', '.join(missing)}")
            unknown_age = sorted(k for k in scope if not any(key[2] == k and key in life_rows for key in agg))
            floor = ctx.params.get("spend_floor", pcid) if pcid.lower() not in _ALL else ctx.params.get("spend_floor")
            draft.observe(f"Rule {pol.get('rule_id')}: request-only review-first specification",
                          rule_id=pol.get("rule_id"), campaign_scope=pcid or "account", candidate_keyword_ids=scope,
                          blocked_by_unknown_lifecycle=unknown_age,
                          metric_window=[ctx.period_start, ctx.period_end],
                          lookback_days=V.integer(pol.get("approved_lookback_days")),
                          lag_buffer_days=V.integer(pol.get("lag_buffer_days")), spend_threshold=floor.value,
                          condition="conversions == 0 AND cost >= spend_threshold AND not brand/strategic AND "
                                    "active age >= minimum_active_age_days",
                          exclusions={"strategic_keyword_ids": _terms(pol.get("strategic_keyword_ids")),
                                      "brand_terms": sorted(set(_terms(ctx.profile.get("brand_terms")) + _terms(pol.get("brand_terms"))))},
                          minimum_active_age_days=V.integer(pol.get("minimum_active_age_days")),
                          evaluation_cadence=pol.get("review_cadence"), maximum_affected_scope=cap,
                          scope_exceeds_cap=cap is not None and len(scope) > cap, owner=pol.get("owner"),
                          approval_status=pol.get("approval_status"), action="alert and human review first; pause is request-only",
                          recovery_condition="re-enable when the keyword converts or its role is documented as strategic")


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run))
