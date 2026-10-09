"""check.py — skill-170 deterministic Google Ad Grants program-rule checks with reviewed keyword/tracking judgments.

exports: SKILL | VERSION | RULES | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-170-ad-grants-compliance/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #79 Check Google Grants accounts for mandatory requirements (suisseo.ch, Vincent Hsu) — clean-room
         reimplementation of single-word keywords, conversion bidding, ad groups/ads per campaign, sitelinks, geo-targeting,
         QS < 3 and 5% CTR checks; spreadsheet/email output and the weekly auto-fetched exception list are refused
         (exceptions are profile.ad_grants_exception_keywords); the 2-ads-per-ad-group rule is Info only (retired).
rules:   Applies ONLY when profile.ad_grants is true; otherwise every check is not_applicable.
         Rule values come from RULES (Google program pages consulted 2026-09-25) or profile.ad_grants_rules overrides;
         invalid overrides leave the rule unresolved and the dependent check partial — never a silent default.
         Serving keyword = keyword, ad group and campaign all ENABLED; unknown parent status is reported as partial.
         Single-word = one alphanumeric token after stripping [ ] " and leading '+'; dashes/periods/special chars are
         not single-word (program text). Brand/exception terms exempt; acronym/medical exceptions are AI review only.
         Genericness is semantic → batch review over candidates (below-average LP experience or profile.ad_grants_generic_terms).
         Absence findings (ad groups, ads, sitelinks, counted conversion actions) need a manifest-complete inventory.
         CTR months must be complete_month=true and end <= ctx.as_of; below min_ctr is Warning only with >= min_impressions.
         Critical only via the deactivation review with proposal.evidence_ref; verify() re-checks every proposal.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes4 | new recipe: Ad Grants program check
"""
from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402
from adsrun.negatives import blocks  # noqa: E402

SKILL = "skill-170-ad-grants-compliance"
VERSION = "1.0.0"

CONSULTED = "2026-09-25"
URL_ACCOUNT = "https://support.google.com/grants/answer/117827"
URL_GUIDE = "https://support.google.com/nonprofits/answer/9314402"
URL_MISSION = "https://support.google.com/nonprofits/answer/4410314"
RULES = {  # name: (default, kind, source)
    "min_ctr": (0.05, "ratio", URL_ACCOUNT),
    "ctr_consecutive_months": (2, "int", URL_ACCOUNT),
    "max_prohibited_qs": (2, "qs", URL_MISSION),
    "min_ad_groups_per_campaign": (2, "int", URL_GUIDE),
    "min_sitelinks": (2, "int", URL_ACCOUNT),
    "min_ads_per_ad_group": (1, "int", f"library default (an ad group needs an enabled ad to serve; 2-ad rule retired) {URL_GUIDE}"),
    "min_monthly_conversions": (1, "int", URL_ACCOUNT),
    "tracking_required_from": ("2018-01-01", "date", URL_ACCOUNT),
    "conversion_bidding_required_from": ("2019-04-22", "date", URL_ACCOUNT),
}
CHECKS = (
    ("program_scope", "Ad Grants applicability and program rule resolution"),
    ("account_ctr", "Monthly account CTR vs program minimum"),
    ("single_word_keywords", "Single-word keywords"),
    ("generic_keywords", "Overly generic keywords (review)"),
    ("low_quality_score", "Keywords with prohibited Quality Score"),
    ("ad_group_minimum", "Enabled ad groups per Search campaign"),
    ("ads_per_ad_group", "Enabled ads per ad group"),
    ("sitelink_minimum", "Unique enabled sitelink assets"),
    ("geo_targeting", "Location targeting present"),
    ("conversion_setup", "Meaningful conversion action counted in Conversions"),
    ("monthly_conversions", "Conversions per complete month"),
    ("bidding_policy", "Conversion-based Smart bidding"),
)
MONTHLY = "custom/grants_monthly_metrics"
CONV_BIDDING = {"MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE", "TARGET_CPA", "TARGET_ROAS"}
ALL_LOCATIONS = {"all", "all countries", "all countries and territories", "all_countries", "worldwide", "world"}
EXCEPTION_BASES = {"brand", "medical_condition", "acronym", "program_exception_list"}
_EVIDENCE_OUTCOMES = ("deactivation_evidenced", "exemption_evidenced")


# ----------------------------------------------------------------------------- helpers
def _status(row) -> str | None:
    s = str(row.get("status") or "").strip().upper()
    return s or None


def _rules(ctx) -> tuple[dict, list[str]]:
    """Resolve RULES with profile.ad_grants_rules overrides. Rules: invalid override → value None + problem."""
    over = ctx.profile.get("ad_grants_rules")
    over = over if isinstance(over, dict) else {}
    out, problems = {}, [f"unknown ad_grants_rules key '{k}'" for k in sorted(over) if k not in RULES]
    for name, (default, kind, src) in RULES.items():
        raw, source = (over[name], "profile.ad_grants_rules") if name in over else (default, f"{src} (consulted {CONSULTED})")
        val = None
        if kind == "date":
            val = V.parse_date(raw)
        else:
            f = V.num(raw)
            if f is not None and math.isfinite(f):
                if kind == "ratio" and 0 < f < 1:
                    val = f
                elif kind == "int" and f == int(f) and f >= 1:
                    val = int(f)
                elif kind == "qs" and f == int(f) and 1 <= f <= 10:
                    val = int(f)
        if val is None:
            problems.append(f"ad_grants_rules.{name}={raw!r} invalid for {kind}")
        out[name] = {"value": val, "source": source}
    return out, problems


def _month(v) -> date | None:
    s = str(v or "").strip()
    return V.parse_date(s + "-01" if len(s) == 7 else s)


def _month_end(m: date) -> date:
    nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _single_token(text) -> str | None:
    t = str(text or "").strip()
    if len(t) >= 2 and ((t[0], t[-1]) in (("[", "]"), ('"', '"'))):
        t = t[1:-1]
    toks = [x[1:] if x.startswith("+") else x for x in t.split()]
    return toks[0] if len(toks) == 1 and toks[0].isalnum() else None


class Scope:
    """Enabled parent inventory. Rules: None status/row = unknown, never enabled."""

    def __init__(self, ctx):
        self.camps = {str(r.get("id")): r for r in ctx.rows("campaigns") if r.get("id") is not None}
        self.ags = {str(r.get("id")): r for r in ctx.rows("ad_groups") if r.get("id") is not None}

    def camp_enabled(self, cid) -> bool | None:
        r = self.camps.get(str(cid))
        return None if r is None or _status(r) is None else _status(r) == "ENABLED"

    def ag_enabled(self, gid) -> bool | None:
        r = self.ags.get(str(gid))
        return None if r is None or _status(r) is None else _status(r) == "ENABLED"

    def serving_keywords(self, ctx, chk) -> list[dict]:
        out, unknown = [], 0
        for kw in sorted(ctx.rows("keywords"), key=lambda r: str(r.get("id"))):
            if _status(kw) != "ENABLED":
                continue
            c, g = self.camp_enabled(kw.get("campaign_id")), self.ag_enabled(kw.get("ad_group_id"))
            if c is False or g is False:
                continue
            if c is None or g is None:
                unknown += 1
                continue
            out.append(kw)
        if unknown:
            chk.partial(f"{unknown} enabled keywords with unknown campaign/ad-group status not evaluated",
                        ["campaigns:status", "ad_groups:status"])
        return out


def _complete(ctx, key) -> bool:
    t = ctx.table(key)
    return t is not None and t.complete is True


def _bidding_type(ctx, camp) -> str | None:
    t = str(camp.get("bidding_strategy_type") or "").strip().upper()
    if t:
        return t
    sid = camp.get("bidding_strategy_id") or camp.get("strategy_id")
    if sid:
        s = next((r for r in ctx.rows("bidding_strategies") if str(r.get("id")) == str(sid)), None)
        if s and str(s.get("type") or "").strip():
            return str(s.get("type")).strip().upper()
    return None


def _list(v) -> list:
    return [x for x in v if x] if isinstance(v, list) else ([v] if isinstance(v, str) and v.strip() else [])


def _created(ctx):
    raw = ctx.profile.get("ad_grants_account_created")
    return V.parse_date(raw), raw


# ----------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Declare all twelve CHECKS; every one ends not_applicable unless profile.ad_grants is true.

    Rules:   Rule values only from _rules(); findings only from complete, serving-scope evidence.
    """
    grants = ctx.profile.get("ad_grants")
    if grants is not True and V.boolean(grants) is not True:
        for cid, title in CHECKS:
            ctx.check(cid, title, applicable=False,
                      na_reason="profile does not declare ad_grants: true; Ad Grants program rules do not apply")
        return
    rules, problems = _rules(ctx)
    scope_chk = ctx.check(*CHECKS[0])
    for p in problems:
        scope_chk.partial(p)
    scope = Scope(ctx)
    enabled = [c for c in scope.camps.values() if _status(c) == "ENABLED"]
    channels = sorted({str(c.get("channel_type") or "UNKNOWN").upper() for c in enabled})
    smart_only = bool(enabled) and channels == ["SMART"]
    created, raw_created = _created(ctx)
    if raw_created is not None and created is None:
        scope_chk.partial(f"ad_grants_account_created {raw_created!r} is not a date")
    if not scope.camps:
        scope_chk.partial("campaign inventory missing: Smart-only exemption and parent status unknown", ["campaigns (file)"])
    scope_chk.observe("Ad Grants program rules resolved", rules=rules, consulted=CONSULTED,
                      enabled_campaigns=len(enabled), enabled_channels=channels, smart_campaigns_only=smart_only,
                      account_created=created, sources=[URL_ACCOUNT, URL_GUIDE, URL_MISSION],
                      unavailable_source="https://support.google.com/grants/answer/9042207 (no content on 2026-09-25)")
    min_impr = ctx.params.get("min_impressions")
    _account_ctr(ctx, rules, scope, smart_only, min_impr)
    serving = _keywords(ctx, rules, scope)
    _generic(ctx, scope, serving)
    _structure(ctx, rules, scope)
    _sitelinks(ctx, rules, scope)
    _geo(ctx, scope)
    required, why = _tracking_required(ctx, rules, scope, created)
    _conversion_setup(ctx, required, why)
    _monthly_conversions(ctx, rules, required, why)
    _bidding(ctx, rules, scope, created)


def _monthly_rows(ctx, chk) -> list[tuple[date, dict]] | None:
    t = ctx.table(MONTHLY)
    col = next((c for c in ("customer_id", "account_id") if c in t.columns), None)
    out, seen, skipped = [], set(), []
    for r in t.rows:
        if col and ctx.account_id and str(r.get(col) or "") != str(ctx.account_id):
            continue
        m = _month(r.get("month"))
        if m is None:
            skipped.append(str(r.get("month")))
            continue
        if m in seen:
            chk.partial(f"{t.filename}: duplicate rows for {m:%Y-%m}; one account/month row required")
            return None
        seen.add(m)
        if V.boolean(r.get("complete_month")) is not True or (ctx.as_of and _month_end(m) > ctx.as_of):
            skipped.append(f"{m:%Y-%m}")
            continue
        out.append((m, r))
    if skipped:
        chk.partial(f"months not complete or unparseable excluded: {sorted(skipped)}")
    return sorted(out, key=lambda x: x[0])


def _account_ctr(ctx, rules, scope, smart_only, min_impr) -> None:
    chk = ctx.check(*CHECKS[1], {MONTHLY: ["month", "impressions", "clicks", "complete_month"]},
                    applicable=not smart_only,
                    na_reason=f"enabled campaigns are Smart campaigns only: CTR rule exempt ({URL_ACCOUNT})")
    if not chk.runnable:
        return
    min_ctr, n_consec = rules["min_ctr"]["value"], rules["ctr_consecutive_months"]["value"]
    if min_ctr is None or n_consec is None or min_impr.value is None:
        chk.partial("min_ctr, ctr_consecutive_months or min_impressions unresolved: no CTR decision")
        return
    if not scope.camps:
        chk.partial("Smart-only exemption unverifiable without campaigns inventory")
    months = _monthly_rows(ctx, chk)
    if months is None:
        return
    entity_id = ctx.account_id
    below: list[date] = []
    for m, r in months:
        impr, clicks = V.num(r.get("impressions")), V.num(r.get("clicks"))
        ctr = V.ratio(clicks, impr)
        ev = {"month": f"{m:%Y-%m}", "clicks": clicks, "impressions": impr, "ctr": ctr, "min_ctr": min_ctr,
              "min_ctr_source": rules["min_ctr"]["source"], "min_impressions": min_impr.value,
              "min_impressions_source": min_impr.source}
        if ctr is None:
            chk.observe(f"{m:%Y-%m}: CTR undefined (impressions {impr})", **ev)
            continue
        if ctr >= min_ctr:
            chk.observe(f"{m:%Y-%m}: account CTR {ctr:.4f} meets program minimum", **ev)
            continue
        entity = {"customer_id": entity_id, "month": f"{m:%Y-%m}"}
        if impr < min_impr.value:
            chk.finding("ctr_below_minimum_low_sample", "Info", entity,
                        f"{m:%Y-%m} account CTR {ctr:.2%} < {min_ctr:.0%} on only {impr:g} impressions",
                        evidence=ev, calculation={"ctr": "clicks / impressions"},
                        recommendation="Review high-impression low-CTR keywords; sample below the library gate.",
                        uncertainty="Low-volume month; the program still applies its CTR rule.")
            continue
        chk.finding("ctr_below_program_minimum", "Warning", entity,
                    f"{m:%Y-%m} account CTR {ctr:.2%} ({clicks:g}/{impr:g}) is below the program minimum {min_ctr:.0%}",
                    evidence=ev, calculation={"ctr": "clicks / impressions"},
                    recommendation="Propose pausing or rewording high-impression, low-CTR keywords before the next month closes.",
                    uncertainty="Google's own account CTR calculation may differ in scope; confirm in the Grants account.")
        below.append(m)
    runs, cur = [], []
    for m in below:
        if cur and _month_end(cur[-1]) + timedelta(days=1) != m:
            runs.append(cur)
            cur = []
        cur.append(m)
    if cur:
        runs.append(cur)
    for run_months in runs:
        if len(run_months) < n_consec:
            continue
        window = [f"{x:%Y-%m}" for x in run_months[-n_consec:]]
        entity = {"customer_id": entity_id, "months": window}
        ev = {"months": window, "min_ctr": min_ctr, "consecutive_required": n_consec,
              "rule_source": rules["ctr_consecutive_months"]["source"]}
        prov = chk.finding("ctr_deactivation_condition", "Warning", entity,
                           f"Account CTR below {min_ctr:.0%} in {len(window)} consecutive complete months {window}: "
                           f"the program's temporary-deactivation condition",
                           evidence=ev, recommendation="Restore CTR and check the account's Grants status/notifications.",
                           uncertainty="Deactivation itself is not evidenced by metrics alone.")
        chk.review("ctr_deactivation_condition", entity,
                   f"CTR stayed below {min_ctr:.0%} in {window}. Is there evidence the account was deactivated or notified, "
                   f"or that a current program exemption applies?", evidence=ev,
                   outcomes={"deactivation_evidenced": {"severity": "Critical", "recommendation":
                                                         "Fix CTR and other issues, then request reinstatement (owner action)."},
                             "exemption_evidenced": {"severity": None, "recommendation": "Record the exemption source."},
                             "not_evidenced": {"severity": "Warning", "recommendation": "Keep as Warning; monitor status."}},
                   guidance="Critical and exemption both need proposal.evidence_ref (in-product notification, status "
                            "export or program page). Without it choose not_evidenced.",
                   provisional=prov)


def _keywords(ctx, rules, scope) -> list[dict]:
    sw = ctx.check(*CHECKS[2], {"keywords": ["id", "campaign_id", "ad_group_id", "text", "status"]})
    qs = ctx.check(*CHECKS[4], {"keywords": ["id", "campaign_id", "ad_group_id", "text", "status", "quality_score"]})
    if not sw.runnable:
        return []
    serving = scope.serving_keywords(ctx, sw)
    exempt = {V.norm_text(t) for t in _list(ctx.profile.get("brand_terms")) + _list(ctx.profile.get("ad_grants_exception_keywords"))}
    n_single = n_exempt = 0
    for kw in serving:
        tok = _single_token(kw.get("text"))
        if tok is None:
            continue
        n_single += 1
        if V.norm_text(tok) in exempt:
            n_exempt += 1
            continue
        entity = {"campaign_id": str(kw.get("campaign_id")), "ad_group_id": str(kw.get("ad_group_id")),
                  "keyword_id": str(kw.get("id"))}
        ev = {"text": kw.get("text"), "match_type": kw.get("match_type"), "token": tok, "rule_source": URL_MISSION,
              "exempt_lists": "profile.brand_terms + profile.ad_grants_exception_keywords"}
        prov = sw.finding("single_word_keyword", "Info", entity,
                          f"Serving keyword {kw.get('id')} '{kw.get('text')}' is a single word not on the brand/exception lists",
                          evidence=ev, recommendation="Confirm whether an allowed exception applies; otherwise pause or make it specific.",
                          uncertainty="Acronyms and recognized medical conditions are allowed but not decidable from text.")
        sw.review("single_word_keyword", entity,
                  f"Is the single-word keyword '{kw.get('text')}' an allowed Ad Grants exception (own brand, recognized "
                  f"medical condition, acronym, program exception list)?", evidence=ev,
                  outcomes={"prohibited_single_word": {"severity": "Warning", "recommendation":
                                                       "Pause it or replace it with a multi-word mission-specific keyword."},
                            "allowed_exception": {"severity": None, "recommendation": "Keep; record the exception basis."},
                            "uncertain": {"severity": "Info", "recommendation": "Ask the nonprofit which exception applies."}},
                  guidance="allowed_exception needs proposal.exception_basis in brand|medical_condition|acronym|program_exception_list.",
                  provisional=prov)
    sw.observe("Single-word keyword screen", serving_keywords=len(serving), single_word=n_single, exempt=n_exempt)
    if qs.runnable:
        limit = rules["max_prohibited_qs"]["value"]
        if limit is None:
            qs.partial("max_prohibited_qs unresolved")
        else:
            rated = unrated = 0
            for kw in serving:
                q = V.integer(kw.get("quality_score"))
                if q is None:
                    unrated += 1
                    continue
                rated += 1
                if q <= limit:
                    qs.finding("prohibited_quality_score", "Warning",
                               {"campaign_id": str(kw.get("campaign_id")), "ad_group_id": str(kw.get("ad_group_id")),
                                "keyword_id": str(kw.get("id"))},
                               f"Serving keyword {kw.get('id')} '{kw.get('text')}' has Quality Score {q} (program prohibits <= {limit})",
                               evidence={"quality_score": q, "max_prohibited_qs": limit,
                                         "rule_source": rules["max_prohibited_qs"]["source"]},
                               recommendation="Propose pausing or reworking the keyword; diagnose components via skill-064.",
                               uncertainty="Current snapshot score; Google may already have paused it automatically.")
            qs.observe("Quality Score screen", serving_keywords=len(serving), rated=rated, unrated_exempt=unrated,
                       max_prohibited_qs=limit)
    return serving


def _generic(ctx, scope, serving) -> None:
    chk = ctx.check(*CHECKS[3], {"keywords": ["id", "campaign_id", "ad_group_id", "text", "status"]})
    if not chk.runnable:
        return
    terms = _list(ctx.profile.get("ad_grants_generic_terms"))
    has_lp = "landing_page_experience" in ctx.table("keywords").columns
    if not terms and not has_lp:
        chk.partial("no candidate signal: supply keywords:landing_page_experience or profile.ad_grants_generic_terms",
                    ["keywords:landing_page_experience"])
        return
    cands, multi = [], 0
    for kw in serving:
        if _single_token(kw.get("text")) is not None:
            continue  # owned by single_word_keywords
        multi += 1
        reasons = []
        if has_lp and V.norm_text(kw.get("landing_page_experience")).replace(" ", "_") == "below_average":
            reasons.append("landing page experience below average")
        reasons += [f"contains profile generic term '{t}'" for t in terms if blocks(t, "PHRASE", kw.get("text")) is True]
        if reasons:
            cands.append({"keyword_id": str(kw.get("id")), "campaign_id": str(kw.get("campaign_id")),
                          "ad_group_id": str(kw.get("ad_group_id")), "text": kw.get("text"), "signals": reasons})
    if multi > len(cands):
        chk.partial(f"{multi - len(cands)} multi-word serving keywords without a candidate signal were not screened for genericness")
    chk.observe("Generic keyword candidates", multi_word_serving_keywords=multi, candidates=len(cands),
                signals=["landing_page_experience" if has_lp else None, "profile.ad_grants_generic_terms" if terms else None])
    if not cands:
        return
    chk.review("generic_keyword_candidates", {"batch": "generic_keyword_candidates"},
               "Which of these keywords are overly generic under the Ad Grants mission-based policy (no clear searcher "
               "intent, or a place/organization/person name on its own)?",
               evidence={"candidates": cands, "rule_source": URL_MISSION},
               outcomes={"some_generic": {"severity": "Warning", "recommendation":
                                          "Pause or make the listed keywords mission-specific."},
                         "none_generic": {"severity": None, "recommendation": "No action."},
                         "uncertain": {"severity": "Info", "recommendation": "Ask the nonprofit about intent."}},
               guidance="For some_generic list proposal.keyword_ids (ids from evidence.candidates only).")


def _structure(ctx, rules, scope) -> None:
    agc = ctx.check(*CHECKS[5], {"campaigns": ["id", "status", "channel_type"], "ad_groups": ["id", "campaign_id", "status"]})
    adc = ctx.check(*CHECKS[6], {"campaigns": ["id", "status", "channel_type"], "ad_groups": ["id", "campaign_id", "status"],
                                 "ads": ["ad_group_id", "status"]})
    search = sorted(cid for cid, c in scope.camps.items()
                    if _status(c) == "ENABLED" and str(c.get("channel_type") or "").upper() == "SEARCH")
    enabled_ags = {}
    for gid, g in sorted(scope.ags.items()):
        if _status(g) == "ENABLED" and str(g.get("campaign_id")) in search:
            enabled_ags.setdefault(str(g.get("campaign_id")), []).append(gid)
    if agc.runnable:
        limit = rules["min_ad_groups_per_campaign"]["value"]
        complete = _complete(ctx, "ad_groups")
        counts = {cid: len(enabled_ags.get(cid, [])) for cid in search}
        if limit is None:
            agc.partial("min_ad_groups_per_campaign unresolved")
        for cid in search:
            if limit is None or counts[cid] >= limit:
                continue
            if not complete:
                continue
            agc.finding("ad_group_minimum", "Warning", {"campaign_id": cid},
                        f"Enabled Search campaign {cid} has {counts[cid]} enabled ad group(s); program minimum is {limit}",
                        evidence={"enabled_ad_groups": enabled_ags.get(cid, []), "minimum": limit,
                                  "rule_source": rules["min_ad_groups_per_campaign"]["source"]},
                        recommendation="Propose splitting keywords into at least two tightly themed ad groups.",
                        uncertainty="Counts come from the supplied complete ad group inventory.")
        agc.observe("Enabled ad groups per enabled Search campaign", counts=counts, inventory_complete=complete,
                    minimum=limit)
        if not complete:
            agc.partial("ad_groups inventory not manifest-complete: counts are lower bounds, no absence finding")
    if adc.runnable:
        limit = rules["min_ads_per_ad_group"]["value"]
        complete = _complete(ctx, "ads")
        ads: dict[str, int] = {}
        for a in ctx.rows("ads"):
            if _status(a) == "ENABLED":
                ads[str(a.get("ad_group_id"))] = ads.get(str(a.get("ad_group_id")), 0) + 1
        short = []
        for cid in search:
            for gid in enabled_ags.get(cid, []):
                n = ads.get(gid, 0)
                if limit is not None and n < limit:
                    short.append(gid)
                    if complete:
                        adc.finding("ads_per_ad_group", "Info", {"campaign_id": cid, "ad_group_id": gid},
                                    f"Enabled ad group {gid} has {n} enabled ad(s) (< {limit})",
                                    evidence={"enabled_ads": n, "minimum": limit,
                                              "rule_source": rules["min_ads_per_ad_group"]["source"]},
                                    recommendation="Add an enabled responsive search ad or pause the ad group.",
                                    uncertainty="Former two-ad rule no longer enforced; this is serving hygiene.")
        if limit is None:
            adc.partial("min_ads_per_ad_group unresolved")
        if not complete:
            adc.partial("ads inventory not manifest-complete: no absence finding")
        adc.observe("Enabled ads per enabled ad group", ad_groups=sum(len(v) for v in enabled_ags.values()),
                    below_minimum=short, minimum=limit)


def _sitelinks(ctx, rules, scope) -> None:
    chk = ctx.check(*CHECKS[7], {"assets": ["type", "level", "status"]})
    if not chk.runnable:
        return
    t = ctx.table("assets")
    idcol = next((c for c in ("asset_id", "id") if c in t.columns), None)
    if idcol is None:
        chk.skip("required evidence missing", ["assets:asset_id"])
        return
    limit = rules["min_sitelinks"]["value"]
    unique, per_campaign, unknown = set(), {}, 0
    for a in t.rows:
        if str(a.get("type") or "").upper() != "SITELINK" or _status(a) != "ENABLED":
            continue
        if str(a.get("approval_status") or "").upper() == "DISAPPROVED":
            continue
        level = str(a.get("level") or "").upper()
        if level in ("ACCOUNT", "CUSTOMER"):
            linked = True
        elif level == "CAMPAIGN":
            linked = scope.camp_enabled(a.get("campaign_id"))
        elif level == "AD_GROUP":
            linked = scope.ag_enabled(a.get("ad_group_id"))
        else:
            linked = None
        if linked is None:
            unknown += 1
            continue
        if linked:
            unique.add(str(a.get(idcol)))
            key = "account" if level in ("ACCOUNT", "CUSTOMER") else str(a.get("campaign_id")) if level == "CAMPAIGN" else None
            if key:
                per_campaign.setdefault(key, set()).add(str(a.get(idcol)))
    if unknown:
        chk.partial(f"{unknown} sitelink associations with unknown level/parent status not counted")
    complete = t.complete is True
    if limit is None:
        chk.partial("min_sitelinks unresolved")
    elif len(unique) < limit and complete:
        chk.finding("sitelink_minimum", "Warning", {"customer_id": ctx.account_id},
                    f"Account has {len(unique)} unique enabled sitelink asset(s); program minimum is {limit}",
                    evidence={"sitelink_asset_ids": sorted(unique), "minimum": limit,
                              "rule_source": rules["min_sitelinks"]["source"]},
                    recommendation="Propose at least two sitelinks to specific mission pages.",
                    uncertainty="Counts enabled, not disapproved associations to enabled entities.")
    elif not complete:
        chk.partial("assets inventory not manifest-complete: count is a lower bound, no absence finding")
    account_links = per_campaign.get("account", set())
    coverage = {cid: len(account_links | per_campaign.get(cid, set()))
                for cid, c in sorted(scope.camps.items()) if _status(c) == "ENABLED"}
    chk.observe("Unique enabled sitelinks", unique=len(unique), minimum=limit, account_level=len(account_links),
                effective_per_enabled_campaign=coverage)


def _geo(ctx, scope) -> None:
    chk = ctx.check(*CHECKS[8], {"campaigns": ["id", "status", "geo_targets"]})
    if not chk.runnable:
        return
    unknown, specific = [], []
    for cid, c in sorted(scope.camps.items()):
        if _status(c) != "ENABLED":
            continue
        raw = c.get("geo_targets")
        if V.norm_text(raw) == "" or raw is None:
            unknown.append(cid)
            continue
        if V.norm_text(raw) in ALL_LOCATIONS:
            chk.finding("no_location_targeting", "Warning", {"campaign_id": cid},
                        f"Enabled campaign {cid} targets all locations ('{raw}'); the program requires specific geo-targeting",
                        evidence={"geo_targets": raw, "rule_source": URL_ACCOUNT},
                        recommendation="Propose targeting the locations the nonprofit serves; review fit via skill-053.",
                        uncertainty="Relevance of specific targets is not assessed here.")
            continue
        specific.append(cid)
    if unknown:
        chk.partial(f"geo_targets unknown for enabled campaigns {unknown}", ["campaigns:geo_targets"])
    chk.observe("Location targeting present", enabled_with_specific_targets=specific, unknown=unknown)


def _tracking_required(ctx, rules, scope, created) -> tuple[bool | None, str]:
    conv_bid = sorted(cid for cid, c in scope.camps.items()
                      if _status(c) == "ENABLED" and _bidding_type(ctx, c) in CONV_BIDDING)
    cutoff = rules["tracking_required_from"]["value"]
    if conv_bid:
        return True, f"conversion-based bidding on campaigns {conv_bid}"
    if created is not None and cutoff is not None:
        return (created >= cutoff), f"account created {created} vs tracking_required_from {cutoff}"
    return None, "applicability unknown: no conversion-based bidding evidenced and profile.ad_grants_account_created missing"


def _conversion_setup(ctx, required, why) -> None:
    chk = ctx.check(*CHECKS[9], {"conversion_actions": ["id", "status", "category"]},
                    applicable=required is not False, na_reason=f"tracking rule not applicable: {why}")
    if not chk.runnable:
        return
    t = ctx.table("conversion_actions")
    col = next((c for c in ("include_in_conversions", "primary_for_goal") if c in t.columns), None)
    if col is None:
        chk.skip("required evidence missing", ["conversion_actions:include_in_conversions"])
        return
    if required is None:
        chk.partial(why)
    counted, unknown = [], []
    for a in sorted(t.rows, key=lambda r: str(r.get("id"))):
        if _status(a) != "ENABLED":
            continue
        inc = V.boolean(a.get(col))
        if inc is None:
            unknown.append(str(a.get("id")))
        elif inc:
            counted.append({"action_id": str(a.get("id")), "name": a.get("name"), "category": a.get("category"),
                            "counting": a.get("counting"), "last_conversion_date": a.get("last_conversion_date")})
    if unknown:
        chk.partial(f"inclusion flag unknown for enabled actions {unknown}")
    chk.observe("Enabled actions counted in Conversions", counted=[c["action_id"] for c in counted],
                inclusion_column=col, applicability=why)
    if not counted:
        if required is True and not unknown and t.complete is True:
            chk.finding("no_counted_conversion_action", "Warning", {"customer_id": ctx.account_id},
                        "No enabled conversion action is counted in Conversions although the program requires tracking",
                        evidence={"applicability": why, "inclusion_column": col, "rule_source": URL_ACCOUNT},
                        recommendation="Propose a meaningful conversion (donation, sign-up, volunteer form) counted in Conversions.",
                        uncertainty="Settings evidence; tag firing is verified by the tracking skills.")
        elif t.complete is not True:
            chk.partial("conversion_actions inventory not manifest-complete: no absence finding")
        return
    monthly = []
    mt = ctx.table(MONTHLY)
    if mt is not None and not mt.missing(["month", "clicks", "conversions"]):
        for r in mt.rows:
            clicks, conv = V.num(r.get("clicks")), V.num(r.get("conversions"))
            monthly.append({"month": r.get("month"), "clicks": clicks, "conversions": conv,
                            "conversion_rate": V.ratio(conv, clicks)})
    chk.review("counted_conversion_meaning", {"batch": "counted_conversion_actions"},
               "Which counted conversion actions are NOT meaningful for Ad Grants (e.g. time on site, homepage or page "
               "views that the program says must be excluded from Conversions and categorized Other)?",
               evidence={"counted_actions": counted, "monthly": monthly, "rule_source": URL_ACCOUNT,
                         "guide": URL_GUIDE},
               outcomes={"some_non_meaningful": {"severity": "Warning", "recommendation":
                                                 "Exclude the listed actions from Conversions and categorize them Other."},
                         "all_meaningful": {"severity": None, "recommendation": "No action."},
                         "uncertain": {"severity": "Info", "recommendation": "Confirm each action's business meaning."}},
               guidance="Judge by action category/name and the program examples; clicks nearly equal to conversions "
                        "suggests a non-meaningful action. For some_non_meaningful list proposal.action_ids from evidence.")


def _monthly_conversions(ctx, rules, required, why) -> None:
    chk = ctx.check(*CHECKS[10], {MONTHLY: ["month", "conversions", "complete_month"]},
                    applicable=required is not False, na_reason=f"tracking rule not applicable: {why}")
    if not chk.runnable:
        return
    limit = rules["min_monthly_conversions"]["value"]
    if limit is None:
        chk.partial("min_monthly_conversions unresolved")
        return
    if required is None:
        chk.partial(why)
    months = _monthly_rows(ctx, chk)
    if months is None:
        return
    for m, r in months:
        conv = V.num(r.get("conversions"))
        end = _month_end(m)
        mature = (ctx.lag_days is not None and ctx.snapshot is not None and (ctx.snapshot - end).days >= ctx.lag_days)
        ev = {"month": f"{m:%Y-%m}", "conversions": conv, "minimum": limit, "month_end": end, "snapshot": ctx.snapshot,
              "conversion_lag_days": ctx.lag_days, "applicability": why,
              "rule_source": rules["min_monthly_conversions"]["source"]}
        if conv is None:
            chk.partial(f"{m:%Y-%m}: conversions unknown")
            continue
        if conv >= limit:
            chk.observe(f"{m:%Y-%m}: {conv:g} conversions meet the monthly minimum", **ev)
            continue
        entity = {"customer_id": ctx.account_id, "month": f"{m:%Y-%m}"}
        if required is True and mature:
            chk.finding("month_below_conversion_minimum", "Warning", entity,
                        f"{m:%Y-%m} recorded {conv:g} conversions; the program requires at least {limit} per month",
                        evidence=ev, recommendation="Check conversion tracking health and the counted action set.",
                        uncertainty="A tracking outage and low demand look identical in this metric.")
        elif required is True:
            chk.finding("month_below_conversion_minimum_immature", "Info", entity,
                        f"{m:%Y-%m} shows {conv:g} conversions, but conversion lag has not matured",
                        evidence=ev, recommendation="Re-check after the conversion lag has elapsed.",
                        uncertainty=f"maturity: {ctx.maturity_note}")
        else:
            chk.observe(f"{m:%Y-%m}: {conv:g} conversions below minimum; tracking applicability unknown", **ev)


def _bidding(ctx, rules, scope, created) -> None:
    cutoff = rules["conversion_bidding_required_from"]["value"]
    applicable = not (created is not None and cutoff is not None and created < cutoff)
    chk = ctx.check(*CHECKS[11], {"campaigns": ["id", "status", "channel_type"]}, applicable=applicable,
                    na_reason=f"account created {created} before {cutoff}: conversion-bidding rule not applicable")
    if not chk.runnable:
        return
    if created is None or cutoff is None:
        chk.partial("profile.ad_grants_account_created or cutoff unknown: bidding rule applicability unresolved")
    offenders, unknown = [], []
    for cid, c in sorted(scope.camps.items()):
        if _status(c) != "ENABLED" or str(c.get("channel_type") or "").upper() == "SMART":
            continue
        bt = _bidding_type(ctx, c)
        if bt is None:
            unknown.append(cid)
            continue
        if bt in CONV_BIDDING:
            continue
        offenders.append(cid)
        if created is not None and cutoff is not None:
            chk.finding("non_conversion_bidding", "Warning", {"campaign_id": cid},
                        f"Enabled campaign {cid} uses {bt}; accounts created on/after {cutoff} need conversion-based Smart bidding",
                        evidence={"bidding_strategy_type": bt, "account_created": created, "cutoff": cutoff,
                                  "rule_source": rules["conversion_bidding_required_from"]["source"]},
                        recommendation="Propose Maximize conversions once valid tracking exists (Google may switch it automatically).",
                        uncertainty="Portfolio/strategy mapping from the supplied export.")
    if unknown:
        chk.partial(f"bidding strategy type unknown for campaigns {unknown}",
                    ["campaigns:bidding_strategy_type"])
    chk.observe("Bidding strategy screen", non_conversion_bidding=offenders, unknown=unknown, cutoff=cutoff,
                account_created=created)


def verify(ctx, item, decision) -> list[str]:
    """Rules: evidence refs for Critical/exemption; exception basis for allowed single words; batch ids must match."""
    outcome, proposal = decision.get("outcome"), decision.get("proposal") or {}
    if item.condition_key == "ctr_deactivation_condition" and outcome in _EVIDENCE_OUTCOMES:
        if not str(proposal.get("evidence_ref") or "").strip():
            return [f"{outcome} needs proposal.evidence_ref naming the notification/status/program evidence"]
    if item.condition_key == "single_word_keyword" and outcome == "allowed_exception":
        if proposal.get("exception_basis") not in EXCEPTION_BASES:
            return [f"allowed_exception needs proposal.exception_basis in {sorted(EXCEPTION_BASES)}"]
    batches = {"generic_keyword_candidates": ("some_generic", "keyword_ids", "candidates", "keyword_id"),
               "counted_conversion_meaning": ("some_non_meaningful", "action_ids", "counted_actions", "action_id")}
    if item.condition_key in batches:
        want, field, ev_key, id_key = batches[item.condition_key]
        if outcome != want:
            return []
        listed = [str(x) for x in proposal.get(field) or []]
        allowed = {str(x[id_key]) for x in item.evidence.get(ev_key) or []}
        if not listed:
            return [f"{want} needs proposal.{field}"]
        return [f"{x} not in the reviewed batch" for x in listed if x not in allowed]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
