"""check.py — skill-095 deterministic PMax new-customer acquisition settings, recognition and value review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-095-pmax-new-customer-acquisition/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-098-audience-segmentation-funnel-stage/scripts/check.py — shares audience_definitions /
         activation_permissions semantics (this recipe uses the stricter shared approval rule below)
rules:   Scope = campaigns.channel_type PERFORMANCE_MAX, status != REMOVED; campaigns key `id`, alternative
         `campaign_id` accepted. Settings rows for other campaign ids are ignored with a coverage note.
         Mode (pmax_acquisition_settings.mode): empty/unknown → unknown (NEVER disabled); off set = off,
         disabled, none, not enabled, inactive, bid equally[...]; active = text containing 'new customer',
         'acquisition' or 'high value', or exactly on/enabled/active; anything else = unrecognized → unknown.
         Rows of one campaign with different modes → unknown ('conflicting'). Intent conflict is AI judgment
         (review mode_intent). Explicit off + literal acquisition role in profile.campaign_objectives[id].role →
         Info optional_mode_absent; otherwise off is an observation, never a defect.
         Recognition: linked_list_ids (split ; | ,) resolve in external/audience_definitions by list_id.
         linkage_status in {failed,error,broken,unlinked,disconnected,removed,closed} or eligibility cells whose
         EVERY token says ineligible/not eligible → recognition_broken (Warning only when mode active or role is
         acquisition; else observation → 061). Unresolved list or unknown recognition_methods while active →
         Info recognition_unresolved. No CRM list alone is not a defect. Base `audiences:list_id` is optional context.
         Permission (external/activation_permissions): row by list_id, else source_id row with empty list_id;
         rows whose market is set and not in profile.market are ignored. Approved = permission_status in
         {approved,granted,permitted} AND consent_coverage_status in {covered,complete,verified} AND
         permitted_destinations token google ads AND restricted_data_review in {passed,cleared,not_required} AND
         policy_eligibility in {eligible,compliant}. Denied = permission_status in {denied,revoked,withdrawn,rejected}
         (any matching row). Else unknown → Info permission_unknown (owner 156, blocks list proposals).
         Denied + mode active + list linked → provisional Info unsafe_use + review; Critical needs proposal.evidence_ref.
         Values: raw_value normalized ONCE — units in {micros,micro,micros_of_currency,currency_micros} → /1e6;
         {currency,currency_units,units,standard,major,major_units,account_currency} or the account currency code →
         as is; else unnormalizable (partial). raw_value_field_name containing 'micros' with non-micros units, or
         an explicit currency != account.currency_code → Warning monetary_unit_conflict. additive_or_total_semantics
         additive set {additive,added,add,incremental,additional}, total set {total,replace,replacement,absolute},
         else Info missing_additive_semantics. high_value_setting is recorded separately, never summed.
         LTV (external/customer_ltv, currency units, V.num not ctx.money): approved = approval_reference present AND
         currency == account currency. Row per campaign via profile.campaign_objectives[id].ltv_segment == segment,
         else the single approved row; several without mapping → partial. included_value_components (split ; | ,):
         exactly one baseline token (baseline, baseline_purchase[_value], first_purchase[_value],
         initial_purchase[_value]) → T = discounted_lifetime_value, A = T - B only when T > B, bounds →
         [lower_bound - B, upper_bound - B]; no baseline token and non-empty components → A = expected_future_value,
         bounds as given; >1 baseline token = overlap → unresolved. A/B only when B > 0. No 1.3x–3x defaults.
         Bounds present and configured value outside → Warning monetary_contradiction; configured >= T with
         additive semantics → review double_count (Critical only when mode active, verify needs evidence_ref);
         no bounds and |configured - A| > 0.005 (rounding only) → review monetary_contradiction.
         Reconciliation (custom/pmax_customer_type_daily, ctx.money): rows inside account period, deduplicated on
         (campaign_id, date, conversion_action_id, reported_customer_type); tx + added vs total is an observation
         (mismatch → 071). Mix finding and type CPA need ctx.mature True; CPA also needs per-type cost with no
         unknown cells and min_conversions on BOTH new and existing. Cost is never allocated.
         Test review acquisition_test only when gates mode_known, intent_evidence, recognition_ok, permission_ok,
         ltv_ok are all True; verify re-checks gates and bounds the proposed value by the approved additive value.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks10 | initial deterministic check
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

SKILL = "skill-095-pmax-new-customer-acquisition"
VERSION = "1.0.0"

SET = "external/pmax_acquisition_settings"
DEFS = "external/audience_definitions"
PERM = "external/activation_permissions"
LIFE = "external/customer_lifecycle"
LTV = "external/customer_ltv"
DAILY = "custom/pmax_customer_type_daily"
OWN_061 = "skill-061-customer-match-list-health"
OWN_071 = "skill-071-conversion-tracking-accuracy"
OWN_103 = "skill-103-recent-converter-exclusion"
OWN_156 = "skill-156-first-party-data-collection-activation-strategy"

STEPS = (("lifecycle_settings", "Inventory effective lifecycle mode, strategy and goals per PMax campaign"),
         ("recognition", "Customer recognition methods and linked list health"),
         ("permission_gate", "Activation permission gate for linked first-party lists"),
         ("value_semantics", "Normalize lifecycle monetary value settings and semantics"),
         ("additive_value", "Configured additive value vs approved LTV evidence (B/T/A)"),
         ("value_reconciliation", "Reconcile transaction, added and reported value; customer mix; test gate"))

_LIST_SEPS = (";", "|", ",")
_OFF_MODES = {"off", "disabled", "none", "not enabled", "not_enabled", "inactive", "false", "no", "bid equally",
              "bid_equally", "bid equally for new and existing customers"}
_ACTIVE_WORDS = ("new customer", "new_customer", "acquisition", "high value", "high_value")
_ACTIVE_EXACT = {"on", "enabled", "active", "true", "yes"}
_UNKNOWN_TEXT = {"", "unknown", "n/a", "na", "--", "null", "none reported"}
_BROKEN = {"failed", "error", "broken", "unlinked", "disconnected", "removed", "closed"}
_PERM_OK = {"approved", "granted", "permitted"}
_DENIED = {"denied", "revoked", "withdrawn", "rejected"}
_CONSENT_OK = {"covered", "complete", "verified"}
_RDR_OK = {"passed", "cleared", "not_required", "not required"}
_POLICY_OK = {"eligible", "compliant"}
_ADS_DEST = {"google ads", "google_ads", "google-ads", "googleads"}
_MICROS = {"micros", "micro", "micros_of_currency", "currency_micros"}
_UNITS = {"currency", "currency_units", "units", "standard", "major", "major_units", "account_currency"}
_ADDITIVE = {"additive", "added", "add", "incremental", "additional"}
_TOTAL = {"total", "replace", "replacement", "absolute"}
_BASELINE = {"baseline", "baseline_purchase", "baseline_purchase_value", "first_purchase", "first_purchase_value",
             "initial_purchase", "initial_purchase_value"}
_TYPES = {"new": "new", "new_customer": "new", "new_customers": "new", "existing": "existing",
          "returning": "existing", "existing_customer": "existing", "existing_customers": "existing",
          "high_value": "high_value", "high_value_customer": "high_value", "high_value_customers": "high_value",
          "unknown": "unknown", "unclassified": "unknown", "undetermined": "unknown"}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _tok(v) -> str:
    return V.norm_text(v).replace(" ", "_").replace("-", "_")


def _tokens(v) -> list[str]:
    return [V.norm_text(x) for x in V.split_list(v, _LIST_SEPS) if V.norm_text(x)]


def _camp_obj(ctx, cid: str) -> dict:
    objs = ctx.profile.get("campaign_objectives") or {}
    if not isinstance(objs, dict):
        return {}
    obj = next((v for k, v in objs.items() if str(k) == cid), None)
    return obj if isinstance(obj, dict) else {}


def _acq_role(ctx, cid: str) -> bool:
    role = V.norm_text(_camp_obj(ctx, cid).get("role"))
    return "acquisition" in role or "new customer" in role


def _mode(v) -> tuple[str, str]:
    """('active'|'off'|'unknown', kind). Rules: unknown/unrecognized text is unknown, never off."""
    t = V.norm_text(v)
    if t in _UNKNOWN_TEXT:
        return "unknown", "not reported"
    if t in _OFF_MODES:
        return "off", "off"
    if t in _ACTIVE_EXACT or any(w in t for w in _ACTIVE_WORDS):
        return "active", "new_customers_only" if "only" in t else "new_customer_value"
    return "unknown", f"unrecognized mode text '{_s(v)}'"


def _ineligible(v) -> bool:
    """True only when every eligibility token explicitly says ineligible/not eligible."""
    toks = _tokens(v)
    return bool(toks) and all("ineligible" in t or "not eligible" in t or "not_eligible" in t for t in toks)


def _markets(ctx) -> set[str]:
    m = ctx.profile.get("market")
    vals = m if isinstance(m, list) else V.split_list(m, _LIST_SEPS) if m else []
    return {_s(x).upper() for x in vals if _s(x)}


def _permission(ctx, list_id: str, source_id: str) -> tuple[str, list[dict]]:
    """('approved'|'denied'|'unknown', matched rows) for Google Ads use of one list.

    Rules:   list_id rows first, else source_id rows with empty list_id; foreign-market rows dropped;
             any explicit denial wins; unknown/empty fields never approve.
    """
    markets = _markets(ctx)
    rows = []
    for r in ctx.rows(PERM):
        mk = _s(r.get("market")).upper()
        if mk and mk not in ("ALL", "*", "GLOBAL") and markets and mk not in markets:
            continue
        rows.append(r)
    hit = [r for r in rows if _s(r.get("list_id")) == list_id]
    if not hit and source_id:
        hit = [r for r in rows if not _s(r.get("list_id")) and _s(r.get("source_id")) == source_id]
    hit.sort(key=lambda r: (_s(r.get("source_id")), _s(r.get("list_id")), _s(r.get("market")),
                            _s(r.get("intended_use"))))
    ev = [{k: r.get(k) for k in ("source_id", "list_id", "market", "intended_use", "permission_status",
                                 "consent_coverage_status", "permitted_destinations", "restricted_data_review",
                                 "policy_eligibility", "reviewed_at", "evidence_reference")} for r in hit]
    if any(V.norm_text(r.get("permission_status")) in _DENIED for r in hit):
        return "denied", ev
    for r in hit:
        if (V.norm_text(r.get("permission_status")) in _PERM_OK
                and V.norm_text(r.get("consent_coverage_status")) in _CONSENT_OK
                and set(_tokens(r.get("permitted_destinations"))) & _ADS_DEST
                and V.norm_text(r.get("restricted_data_review")) in _RDR_OK
                and V.norm_text(r.get("policy_eligibility")) in _POLICY_OK):
            return "approved", ev
    return "unknown", ev


def _normalize_value(ctx, r) -> dict:
    """Normalize one configured lifecycle value exactly once. Rules: micros converted once via ctx.money; unknown stays None, never 0."""
    raw = V.num(r.get("raw_value"))
    units = _tok(r.get("units"))
    field = V.norm_text(r.get("raw_value_field_name"))
    cur = _s(r.get("currency")).upper() or None
    out = {"raw_value": raw, "raw_value_field_name": r.get("raw_value_field_name"), "units": r.get("units"),
           "currency": cur, "account_currency": ctx.currency, "normalized_value": None, "conflicts": [],
           "notes": []}
    if raw is None:
        out["notes"].append("raw_value empty/unknown")
        return out
    if "micros" in field and units not in _MICROS:
        out["conflicts"].append(f"field '{r.get('raw_value_field_name')}' is micros but units='{r.get('units')}'")
    elif units in _MICROS:
        out["normalized_value"] = raw / 1_000_000
    elif units in _UNITS or (ctx.currency and units == ctx.currency.lower()):
        out["normalized_value"] = raw
    else:
        out["notes"].append(f"units '{r.get('units')}' not a documented monetary unit; value not normalized")
    if cur and ctx.currency and cur != ctx.currency:
        out["conflicts"].append(f"setting currency {cur} differs from account currency {ctx.currency}")
    elif not cur:
        out["notes"].append("setting currency unknown: not comparable with approved evidence")
    elif not ctx.currency:
        out["notes"].append("account currency unknown")
    return out


def _semantics(v) -> str:
    t = _tok(v)
    return "additive" if t in _ADDITIVE else "total" if t in _TOTAL else "unknown"


def _ltv_calc(r) -> tuple[dict | None, str, dict]:
    """B/T/A from one approved LTV row. Rules: A = T - B only if T > B and B counted once; else future-only."""
    b = V.num(r.get("baseline_purchase_value"))
    t = V.num(r.get("discounted_lifetime_value"))
    f = V.num(r.get("expected_future_value"))
    lo, hi = V.num(r.get("lower_bound")), V.num(r.get("upper_bound"))
    toks = [_tok(x) for x in V.split_list(r.get("included_value_components"), _LIST_SEPS) if _tok(x)]
    base_hits = [x for x in toks if x in _BASELINE]
    calc = {"segment": r.get("segment"), "acquisition_cohort": r.get("acquisition_cohort"),
            "observation_horizon": r.get("observation_horizon"), "value_basis": r.get("value_basis"),
            "returns_tax_treatment": r.get("returns_tax_treatment"), "B": b, "T": t, "expected_future_value": f,
            "included_value_components": toks, "lower_bound": lo, "upper_bound": hi,
            "approval_reference": r.get("approval_reference"), "as_of": r.get("as_of")}
    if len(base_hits) > 1:
        return None, f"components list the baseline purchase {len(base_hits)} times (overlap)", calc
    if base_hits:
        if t is None or b is None:
            return None, "T (discounted_lifetime_value) or B (baseline_purchase_value) unknown", calc
        if t <= b:
            return None, f"T {t:g} does not exceed B {b:g}: no additive value supported", calc
        a, path = t - b, "A = T - B (T contains B once)"
        bounds = (lo - b, hi - b) if lo is not None and hi is not None else None
    elif toks and f is not None:
        a, path = f, "A = expected_future_value (components exclude B)"
        bounds = (lo, hi) if lo is not None and hi is not None else None
    else:
        return None, "included_value_components do not establish whether B is contained", calc
    if a <= 0:
        return None, f"approved additive component {a:g} is not positive", calc
    if bounds is not None and bounds[0] > bounds[1]:
        calc["bounds_note"] = "lower_bound > upper_bound: bounds ignored"
        bounds = None
    calc.update({"A": a, "path": path, "A_bounds": list(bounds) if bounds else None,
                 "A_over_B": V.ratio(a, b) if b is not None and b > 0 else None})
    return calc, "", calc


def _ctype(v) -> str:
    t = _tok(v)
    if not t:
        return "unknown"
    return _TYPES.get(t, t)


def run(ctx) -> None:
    """Run the six recipe steps. Rules: acquisition-mode findings need permitted-use and customer-list evidence; value/LTV judgments go to ai_review; no causal lift claims."""
    camps = ctx.table("campaigns")
    key = None
    if camps is not None:
        key = "id" if "id" in camps.columns else "campaign_id" if "campaign_id" in camps.columns else None
    if camps is None or key is None or "channel_type" not in camps.columns:
        missing = ["campaigns (file)"] if camps is None else (
            (["campaigns:id"] if key is None else []) + (["campaigns:channel_type"]
                                                         if "channel_type" not in camps.columns else []))
        for cid, title in STEPS:
            ctx.check(cid, title).skip("campaign inventory unavailable", missing)
        return
    pmax = sorted({_s(r.get(key)) for r in camps.rows
                   if _s(r.get("channel_type")).upper() == "PERFORMANCE_MAX"
                   and _s(r.get("status")).upper() != "REMOVED" and _s(r.get(key))})
    if not pmax:
        for cid, title in STEPS:
            c = ctx.check(cid, title)
            if camps.complete is True and not camps.truncated:
                c.not_applicable("no non-removed PERFORMANCE_MAX campaign in a complete campaigns inventory")
            else:
                c.skip("no PERFORMANCE_MAX campaign found; campaigns inventory completeness not proven")
        return
    camp_rows = {_s(r.get(key)): r for r in camps.rows}

    # ---------------------------------------------------------------- step 1: lifecycle settings
    s1 = ctx.check("lifecycle_settings", STEPS[0][1], {"campaigns": ["channel_type"], SET: ["campaign_id", "mode"]})
    settings: dict[str, list[dict]] = {}
    modes: dict[str, tuple[str, str]] = {}
    if s1.runnable:
        ignored = set()
        for r in ctx.rows(SET):
            cid = _s(r.get("campaign_id"))
            if cid in pmax:
                settings.setdefault(cid, []).append(r)
            elif cid:
                ignored.add(cid)
        for cid in settings:
            settings[cid].sort(key=lambda r: (_s(r.get("conversion_tracking_owner_id")), _s(r.get("observed_at"))))
        if ignored:
            s1.partial(f"settings rows for non-PMax/unknown campaigns ignored: {sorted(ignored)}")
        actions = {_s(a.get("id")): a for a in ctx.rows("conversion_actions")}
        life = sorted(ctx.rows(LIFE), key=lambda r: (_s(r.get("business_segment")), _s(r.get("product_category")),
                                                      _s(r.get("cohort_start"))))
        life_ev = [{k: r.get(k) for k in ("business_segment", "product_category", "cohort_start", "cohort_end",
                                          "objective", "new_returning_definition", "buying_cycle",
                                          "repurchase_interval", "cohort_count", "maturity", "updated_at")}
                   for r in life]
        if ctx.table(LIFE) is None:
            s1.partial("external/customer_lifecycle (file) missing: intent review relies on profile only",
                       [f"{LIFE} (file)"])
        for cid in pmax:
            rows = settings.get(cid, [])
            if not rows:
                modes[cid] = ("unknown", "no settings row")
                s1.observe(f"Campaign {cid}: no lifecycle settings row; mode unknown (not disabled)", campaign_id=cid)
                s1.partial(f"campaign {cid}: no {SET} row; mode unknown, not disabled")
                continue
            parsed = {_mode(r.get("mode")) for r in rows}
            if len({p[0] for p in parsed}) > 1:
                modes[cid] = ("unknown", "conflicting modes across owner rows")
                s1.partial(f"campaign {cid}: conflicting modes across settings rows {sorted(p[1] for p in parsed)}")
            else:
                modes[cid] = sorted(parsed)[0]
            state, kind = modes[cid]
            if state == "unknown":
                s1.partial(f"campaign {cid}: mode unknown ({kind})")
            goals, goal_notes = [], []
            for r in rows:
                for g in V.split_list(r.get("purchase_goal_ids"), _LIST_SEPS):
                    a = actions.get(_s(g))
                    if a is None:
                        goal_notes.append(f"goal {g} not found in conversion_actions")
                        continue
                    goals.append({"id": _s(g), "category": a.get("category"), "status": a.get("status"),
                                  "enabled_purchase": _s(a.get("category")).upper() == "PURCHASE"
                                  and _s(a.get("status")).upper() == "ENABLED"})
            if goal_notes:
                s1.partial(f"campaign {cid}: " + "; ".join(sorted(set(goal_notes))))
            crow = camp_rows.get(cid) or {}
            strategies = sorted({_s(r.get("strategy")) for r in rows if _s(r.get("strategy"))})
            ev = {"mode_raw": [r.get("mode") for r in rows], "mode_state": state, "mode_kind": kind,
                  "conversion_tracking_owner_ids": [r.get("conversion_tracking_owner_id") for r in rows],
                  "effective_setting_source": [r.get("effective_setting_source") for r in rows],
                  "settings_strategy": strategies, "campaign_bidding_strategy_type": crow.get("bidding_strategy_type"),
                  "purchase_goals": goals, "goal_notes": sorted(set(goal_notes)),
                  "observed_at": [r.get("observed_at") for r in rows],
                  "source_reference": [r.get("source_reference") for r in rows]}
            s1.observe(f"Campaign {cid}: lifecycle mode {state} ({kind})", campaign_id=cid, **ev)
            entity = {"campaign_id": cid}
            if state == "off" and _acq_role(ctx, cid):
                s1.finding("optional_mode_absent", "Info", entity,
                           f"Campaign {cid} has an approved acquisition role but lifecycle acquisition mode is off",
                           evidence={**ev, "campaign_objective": _camp_obj(ctx, cid)},
                           recommendation="Optional: evaluate a bounded acquisition test once recognition, "
                                          "permission and LTV gates pass; do not mandate adoption.",
                           uncertainty="Mode is optional; existing-customer conversions can be valuable.")
            if state == "active":
                s1.review("mode_intent", entity,
                          f"Does the active acquisition mode ({kind}) of campaign {cid} conflict with an approved "
                          f"retention/repeat-purchase intent?",
                          evidence={**ev, "profile_objectives": ctx.profile.get("objectives"),
                                    "profile_customer_lifecycle": ctx.profile.get("customer_lifecycle"),
                                    "campaign_objective": _camp_obj(ctx, cid), "customer_lifecycle_rows": life_ev},
                          outcomes={
                              "conflicts_retention_intent": {"severity": "Warning", "recommendation":
                                                             "Align mode with the approved retention objective "
                                                             "(request-only); keep existing-customer value visible."},
                              "consistent": {"severity": None, "recommendation": "No change."},
                              "uncertain": {"severity": "Info", "recommendation":
                                            "Ask the client to confirm acquisition vs retention intent."},
                          },
                          guidance="Use only approved profile objectives, campaign role and customer_lifecycle "
                                   "objective rows. Existing-customer share alone is not a conflict.")
    else:
        for cid in pmax:
            modes[cid] = ("unknown", "settings evidence missing")

    # ---------------------------------------------------------------- step 2: recognition
    s2 = ctx.check("recognition", STEPS[1][1],
                   {SET: ["campaign_id", "recognition_methods", "linked_list_ids", "linkage_status"]})
    linked: dict[str, list[str]] = {}
    defs: dict[str, dict] = {}
    broken: set[str] = set()
    recog_known: set[str] = set()
    unresolved_c: set[str] = set()
    if not s1.runnable:
        if s2.runnable:
            s2.skip("lifecycle settings unavailable", s1.missing)
    elif s2.runnable:
        defs_t = ctx.table(DEFS)
        if defs_t is None:
            s2.partial("list definitions missing: linked lists unresolved", [f"{DEFS} (file)"])
        else:
            for c in ("list_id", "linkage_status", "eligibility_by_network", "last_successful_refresh_at"):
                if c not in defs_t.columns:
                    s2.partial(f"{DEFS}:{c} missing", [f"{DEFS}:{c}"])
            defs = {_s(r.get("list_id")): r for r in defs_t.rows if _s(r.get("list_id"))}
        aud = ctx.table("audiences")
        aud_ids = {_s(r.get("list_id")) for r in aud.rows} if aud is not None and "list_id" in aud.columns else None
        for cid in pmax:
            rows = settings.get(cid, [])
            if not rows:
                continue
            state = modes[cid][0]
            material = state == "active" or _acq_role(ctx, cid)
            lids = sorted({_s(x) for r in rows for x in V.split_list(r.get("linked_list_ids"), _LIST_SEPS) if _s(x)})
            linked[cid] = lids
            methods = sorted({m for r in rows for m in _tokens(r.get("recognition_methods"))})
            if methods:
                recog_known.add(cid)
            problems, unresolved, list_ev = [], [], []
            for r in rows:
                if V.norm_text(r.get("linkage_status")) in _BROKEN:
                    problems.append(f"settings linkage_status '{r.get('linkage_status')}'")
                if _ineligible(r.get("eligibility_diagnostics")):
                    problems.append(f"settings diagnostics '{r.get('eligibility_diagnostics')}'")
            for lid in lids:
                d = defs.get(lid)
                if d is None:
                    unresolved.append(lid)
                    continue
                last = V.parse_date(d.get("last_successful_refresh_at"))
                list_ev.append({"list_id": lid, "source_id": d.get("source_id"), "source_platform":
                                d.get("source_platform"), "linkage_status": d.get("linkage_status"),
                                "eligibility_by_network": d.get("eligibility_by_network"),
                                "last_successful_refresh_at": d.get("last_successful_refresh_at"),
                                "refresh_age_days": (ctx.as_of - last).days if last and ctx.as_of else None,
                                "in_ads_audiences": (lid in aud_ids) if aud_ids is not None else None})
                if V.norm_text(d.get("linkage_status")) in _BROKEN:
                    problems.append(f"list {lid} linkage_status '{d.get('linkage_status')}'")
                if _ineligible(d.get("eligibility_by_network")):
                    problems.append(f"list {lid} ineligible on every reported network")
            ev = {"mode_state": state, "recognition_methods": methods, "linked_list_ids": lids,
                  "lists": list_ev, "unresolved_list_ids": unresolved,
                  "settings_linkage_status": [r.get("linkage_status") for r in rows],
                  "eligibility_diagnostics": [r.get("eligibility_diagnostics") for r in rows]}
            s2.observe(f"Campaign {cid}: recognition inventory", campaign_id=cid, **ev)
            entity = {"campaign_id": cid}
            if problems:
                broken.add(cid)
                if material:
                    s2.finding("recognition_broken", "Warning", entity,
                               f"Campaign {cid}: customer recognition broken ({'; '.join(sorted(problems))})",
                               evidence={**ev, "problems": sorted(problems)},
                               recommendation="Restore linkage/eligibility before relying on new-vs-existing "
                                              "classification; list-health fixes owned by skill-061.",
                               uncertainty="Status reflects the settings/definition snapshot, not live serving.")
                else:
                    s2.observe(f"Campaign {cid}: broken recognition while mode is {state} → skill-061",
                               campaign_id=cid, problems=sorted(problems))
            if unresolved:
                unresolved_c.add(cid)
            if (unresolved and defs_t is not None) or (state == "active" and not methods):
                s2.finding("recognition_unresolved", "Info", entity,
                           f"Campaign {cid}: recognition evidence incomplete"
                           + (f"; lists without definitions {unresolved}" if unresolved else "")
                           + ("; recognition_methods unknown" if state == "active" and not methods else ""),
                           evidence=ev, recommendation="Supply audience_definitions rows / recognition methods; "
                                                       "absence of a CRM list alone is not a defect.",
                           uncertainty="Autodetection or tag-based recognition may still operate.")
            if not lids and methods:
                s2.observe(f"Campaign {cid}: no linked CRM list; recognition via {methods} (not a defect)",
                           campaign_id=cid)

    # ---------------------------------------------------------------- step 3: permission gate
    s3 = ctx.check("permission_gate", STEPS[2][1],
                   {PERM: ["source_id", "list_id", "market", "permission_status", "consent_coverage_status",
                           "permitted_destinations", "restricted_data_review", "policy_eligibility",
                           "evidence_reference"]})
    perm_ok: dict[str, bool] = {}
    if not s2.runnable or not s1.runnable:
        if s3.runnable:
            s3.skip("linked list inventory unavailable", s2.missing or s1.missing)
    elif s3.runnable:
        n_lists = 0
        for cid in pmax:
            if cid not in linked:
                continue
            state = modes[cid][0]
            statuses = {}
            for lid in linked[cid]:
                n_lists += 1
                src = _s((defs.get(lid) or {}).get("source_id"))
                status, rows = _permission(ctx, lid, src)
                statuses[lid] = status
                entity = {"campaign_id": cid, "list_id": lid}
                ev = {"list_id": lid, "source_id": src or None, "mode_state": state, "permission_rows": rows,
                      "profile_market": sorted(_markets(ctx))}
                if status == "unknown":
                    s3.finding("permission_unknown", "Info", entity,
                               f"List {lid} linked to campaign {cid} has no approved Google Ads activation permission",
                               evidence=ev, owner=OWN_156,
                               recommendation="Block list activation/refresh proposals; obtain permission evidence "
                                              "via skill-156.",
                               uncertainty="Permission may exist but was not evidenced in activation_permissions.")
                elif status == "denied" and state == "active":
                    prov = s3.finding("unsafe_use", "Info", entity,
                                      f"List {lid} is linked to active lifecycle mode of campaign {cid} although "
                                      f"permission is explicitly denied/revoked",
                                      evidence=ev, owner=OWN_156,
                                      recommendation="Stop proposing any use of this list; escalate to the data owner.",
                                      uncertainty="Denial may concern a different intended use.")
                    s3.review("unsafe_use", entity,
                              f"Does the explicit denial for list {lid} cover its use for lifecycle recognition in "
                              f"campaign {cid}, making current use unsafe?",
                              evidence=ev, provisional=prov,
                              outcomes={
                                  "unsafe_use_confirmed": {"severity": "Critical", "recommendation":
                                                           "Escalate to the data owner; request unlinking review "
                                                           "(no account change by this skill)."},
                                  "denial_scope_differs": {"severity": "Info", "recommendation":
                                                           "Permission for this use remains unevidenced (skill-156)."},
                                  "uncertain": {"severity": "Info", "recommendation": "Ask the data owner."},
                              },
                              guidance="unsafe_use_confirmed requires proposal.evidence_ref citing the permission "
                                       "record; compare intended_use and market literally.")
                elif status == "denied":
                    s3.finding("permission_denied_blocked", "Info", entity,
                               f"List {lid} (campaign {cid}) permission explicitly denied; mode is {state}",
                               evidence=ev, owner=OWN_156,
                               recommendation="Keep list proposals blocked; delegate to skill-156.",
                               uncertainty="Mode not verified active; current use not established.")
                else:
                    s3.observe(f"List {lid} (campaign {cid}): approved activation permission", campaign_id=cid,
                               **ev)
            perm_ok[cid] = all(v == "approved" for v in statuses.values())
        s3.observe("Permission gate evaluated", linked_lists=n_lists,
                   campaigns_without_lists=sorted(c for c in linked if not linked[c]))

    # ---------------------------------------------------------------- step 4: value semantics
    s4 = ctx.check("value_semantics", STEPS[3][1],
                   {SET: ["campaign_id", "mode", "raw_value", "units", "currency", "additive_or_total_semantics"]})
    values: dict[tuple[str, str], dict] = {}
    if not s1.runnable:
        if s4.runnable:
            s4.skip("lifecycle settings unavailable", s1.missing)
    elif s4.runnable:
        for cid in pmax:
            for r in settings.get(cid, []):
                owner = _s(r.get("conversion_tracking_owner_id"))
                entity = {"campaign_id": cid, "conversion_tracking_owner_id": owner or None}
                nv = _normalize_value(ctx, r)
                sem = _semantics(r.get("additive_or_total_semantics"))
                nv.update({"semantics": sem, "semantics_raw": r.get("additive_or_total_semantics"),
                           "high_value_setting": r.get("high_value_setting"),
                           "high_value_semantics": r.get("high_value_semantics"), "mode_state": modes[cid][0]})
                if nv["raw_value"] is None and not _s(r.get("high_value_setting")):
                    s4.observe(f"Campaign {cid}: no configured lifecycle value", campaign_id=cid, **nv)
                    continue
                values[(cid, owner)] = nv
                s4.observe(f"Campaign {cid}: configured lifecycle value", campaign_id=cid, **nv)
                for note in nv["notes"]:
                    s4.partial(f"campaign {cid}: {note}")
                if nv["conflicts"]:
                    s4.finding("monetary_unit_conflict", "Warning", entity,
                               f"Campaign {cid}: lifecycle value units/currency contradict evidence "
                               f"({'; '.join(nv['conflicts'])})",
                               evidence=nv, calculation={"raw_value": nv["raw_value"], "units": nv["units"]},
                               recommendation="Correct the unit/currency documentation or setting before any "
                                              "value comparison (request-only).",
                               uncertainty="Export mapping error is possible; confirm in the Ads UI.")
                if nv["raw_value"] is not None and sem == "unknown":
                    s4.finding("missing_additive_semantics", "Info", {**entity, "field": "lifecycle_value"},
                               f"Campaign {cid}: additive vs total semantics of the lifecycle value unknown",
                               evidence=nv, recommendation="Document whether the value is added to purchase value.",
                               uncertainty="Without semantics no acquisition value can be sized.")
                if _s(r.get("high_value_setting")) and _semantics(r.get("high_value_semantics")) == "unknown":
                    s4.finding("missing_additive_semantics", "Info", {**entity, "field": "high_value_setting"},
                               f"Campaign {cid}: high-value setting semantics unknown; not added to the new-customer "
                               f"value", evidence=nv,
                               recommendation="Verify high-value semantics independently before any sizing.",
                               uncertainty="Settings may overlap; never summed blindly.")

    # ---------------------------------------------------------------- step 5: additive value vs LTV
    s5 = ctx.check("additive_value", STEPS[4][1],
                   {LTV: ["segment", "baseline_purchase_value", "expected_future_value", "discounted_lifetime_value",
                          "included_value_components", "lower_bound", "upper_bound", "currency",
                          "approval_reference"]})
    approved_a: dict[str, dict] = {}
    if not s4.runnable:
        if s5.runnable:
            s5.skip("configured value semantics unavailable", s4.missing)
    elif s5.runnable:
        ltv_rows = sorted(ctx.rows(LTV), key=lambda r: (_s(r.get("segment")), _s(r.get("acquisition_cohort")),
                                                         _s(r.get("observation_horizon"))))
        approved = [r for r in ltv_rows if _s(r.get("approval_reference"))
                    and ctx.currency and _s(r.get("currency")).upper() == ctx.currency]
        if len(approved) < len(ltv_rows):
            s5.partial(f"{len(ltv_rows) - len(approved)} LTV rows lack approval_reference or account currency")
        for cid in pmax:
            seg = _s(_camp_obj(ctx, cid).get("ltv_segment"))
            rows = [r for r in approved if V.norm_text(r.get("segment")) == V.norm_text(seg)] if seg else approved
            if len(rows) != 1:
                s5.partial(f"campaign {cid}: {len(rows)} approved LTV rows match "
                           f"{'segment ' + seg if seg else 'without profile ltv_segment mapping'}")
                continue
            calc, why, raw = _ltv_calc(rows[0])
            if calc is None:
                s5.observe(f"Campaign {cid}: no additive value derivable ({why})", campaign_id=cid, **raw)
                s5.partial(f"campaign {cid}: {why}")
                continue
            approved_a[cid] = calc
            s5.observe(f"Campaign {cid}: approved additive value A={calc['A']:g} ({calc['path']})",
                       campaign_id=cid, **calc)
            for (vcid, owner), nv in sorted(values.items()):
                if vcid != cid:
                    continue
                cfg = nv["normalized_value"]
                if cfg is None or nv["conflicts"] or not nv["currency"]:
                    s5.partial(f"campaign {cid}: configured value not comparable (units/currency unresolved)")
                    continue
                if nv["semantics"] != "additive":
                    s5.partial(f"campaign {cid}: comparison needs additive semantics (is {nv['semantics']})")
                    continue
                entity = {"campaign_id": cid, "conversion_tracking_owner_id": owner or None}
                bounds = calc["A_bounds"]
                ev = {"configured_normalized_value": cfg, "configured_raw_value": nv["raw_value"],
                      "units": nv["units"], "currency": nv["currency"], "mode_state": nv["mode_state"], **calc}
                prov = None
                if bounds and not (bounds[0] <= cfg <= bounds[1]):
                    prov = s5.finding("monetary_contradiction", "Warning", entity,
                                      f"Campaign {cid}: configured added value {cfg:g} {ctx.currency} outside the "
                                      f"approved additive range [{bounds[0]:g}, {bounds[1]:g}]",
                                      evidence=ev, calculation={"A": calc["A"], "B": calc["B"], "T": calc["T"],
                                                                "path": calc["path"], "A_bounds": bounds},
                                      recommendation="Align the lifecycle value with the approved additive "
                                                     "component (request-only); no multiplier defaults.",
                                      uncertainty="Approved bounds reflect finance uncertainty on the same basis.")
                elif bounds:
                    s5.observe(f"Campaign {cid}: configured value within approved range", campaign_id=cid, **ev)
                t = calc["T"]
                if calc["path"].startswith("A = T - B") and t is not None and cfg >= t:
                    active = nv["mode_state"] == "active"
                    outcomes = {
                        "not_double_count": {"severity": "Warning" if prov else None, "recommendation":
                                             "Keep the range finding only." if prov else "No change."},
                        "uncertain": {"severity": "Warning" if prov else "Info", "recommendation":
                                      "Ask finance whether the configured value already includes B."},
                    }
                    outcomes["double_count_confirmed"] = {
                        "severity": "Critical" if active else "Warning", "recommendation":
                        "Replace the total with the additive component A (request-only); re-baseline ROAS."}
                    s5.review("double_count", entity,
                              f"Campaign {cid}: configured added value {cfg:g} >= approved total T {t:g}, which "
                              f"already contains B {calc['B']:g}. Is the baseline purchase counted twice?",
                              evidence=ev, outcomes=outcomes, provisional=prov,
                              guidance="double_count_confirmed requires proposal.evidence_ref to the settings/"
                                       "finance record; Critical only because the mode is active.")
                elif not bounds and abs(cfg - calc["A"]) > 0.005:
                    s5.review("monetary_contradiction", entity,
                              f"Campaign {cid}: configured added value {cfg:g} differs from approved A "
                              f"{calc['A']:g} with no approved bounds. Does it contradict approved evidence?",
                              evidence=ev,
                              outcomes={"contradicts_approved_evidence": {"severity": "Warning", "recommendation":
                                                                          "Align with approved A (request-only)."},
                                        "consistent_with_evidence": {"severity": None, "recommendation": "No change."},
                                        "uncertain": {"severity": "Info", "recommendation":
                                                      "Ask finance for bounds on the same basis."}},
                              guidance="Use only the approved LTV row, value_basis and horizon.")

    # ---------------------------------------------------------------- step 6: reconciliation, mix, test gate
    s6 = ctx.check("value_reconciliation", STEPS[5][1],
                   {DAILY: ["campaign_id", "date", "conversion_action_id", "reported_customer_type", "conversions",
                            "transaction_value", "lifecycle_added_value", "total_reported_value"]})
    if not s6.runnable:
        return
    if ctx.mature is not True:
        s6.partial(f"comparisons disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    has_cost = "cost" in ctx.table(DAILY).columns
    windowed = ctx.period_start is not None and ctx.period_end is not None
    if not windowed:
        s6.partial("account period unknown: customer-type rows not window-filtered")
    seen, dupes, outside, foreign = set(), 0, 0, set()
    agg: dict[str, dict[str, dict]] = {}
    for r in sorted(ctx.rows(DAILY), key=lambda r: (_s(r.get("campaign_id")), _s(r.get("date")),
                                                     _s(r.get("conversion_action_id")),
                                                     _s(r.get("reported_customer_type")))):
        cid = _s(r.get("campaign_id"))
        if cid not in pmax:
            foreign.add(cid)
            continue
        d = V.parse_date(r.get("date"))
        if windowed and (d is None or not ctx.period_start <= d <= ctx.period_end):
            outside += 1
            continue
        k = (cid, _s(r.get("date")), _s(r.get("conversion_action_id")), _ctype(r.get("reported_customer_type")))
        if k in seen:
            dupes += 1
            continue
        seen.add(k)
        a = agg.setdefault(cid, {}).setdefault(k[3], {"conversions": 0.0, "transaction_value": 0.0,
                                                    "lifecycle_added_value": 0.0, "total_reported_value": 0.0,
                                                    "cost": 0.0, "unknown_cells": 0, "unknown_cost": 0,
                                                    "rec_rows": 0, "rec_diff": 0.0, "rows": 0})
        a["rows"] += 1
        conv = V.num(r.get("conversions"))
        tx, add, tot = (ctx.money(r.get(c)) for c in ("transaction_value", "lifecycle_added_value",
                                                        "total_reported_value"))
        for name, v in (("conversions", conv), ("transaction_value", tx), ("lifecycle_added_value", add),
                        ("total_reported_value", tot)):
            if v is None:
                a["unknown_cells"] += 1
            else:
                a[name] += v
        if tx is not None and add is not None and tot is not None:
            a["rec_rows"] += 1
            a["rec_diff"] += tot - (tx + add)
        cost = ctx.money(r.get("cost")) if has_cost else None
        if cost is None:
            a["unknown_cost"] += 1
        else:
            a["cost"] += cost
    if foreign:
        s6.partial(f"rows for non-PMax/unknown campaigns ignored: {sorted(foreign)}")
    if outside:
        s6.partial(f"{outside} rows outside the account period ignored")
    if dupes:
        s6.partial(f"{dupes} duplicate campaign/date/action/type rows ignored")
    metrics = {_s(m.get("campaign_id")): m for m in ctx.rows("campaign_metrics")}
    for cid in pmax:
        types = agg.get(cid)
        if not types:
            s6.partial(f"campaign {cid}: no customer-type rows in window")
            continue
        tot = {n: sum(t[n] for t in types.values()) for n in ("conversions", "transaction_value",
                                                              "lifecycle_added_value", "total_reported_value")}
        rec_rows = sum(t["rec_rows"] for t in types.values())
        rows_n = sum(t["rows"] for t in types.values())
        diff = sum(t["rec_diff"] for t in types.values())
        m = metrics.get(cid) or {}
        s6.observe(f"Campaign {cid}: transaction + added vs reported value"
                   + (" MISMATCH → skill-071" if abs(diff) > 0.01 else ""),
                   campaign_id=cid, transaction_value=tot["transaction_value"],
                   lifecycle_added_value=tot["lifecycle_added_value"], total_reported_value=tot["total_reported_value"],
                   reconciled_rows=rec_rows, rows=rows_n, difference=diff, owner=OWN_071,
                   added_value_share=V.ratio(tot["lifecycle_added_value"], tot["total_reported_value"]),
                   campaign_metrics_cost=ctx.money(m.get("cost")), campaign_metrics_conversions=V.num(m.get("conversions")),
                   campaign_metrics_conversion_value=ctx.money(m.get("conversion_value")),
                   note="lifecycle-added value is platform value, not cash revenue")
        if rec_rows < rows_n:
            s6.partial(f"campaign {cid}: {rows_n - rec_rows} rows with unknown value components not reconciled")
        mix = {t: {"conversions": v["conversions"], "share": V.ratio(v["conversions"], tot["conversions"])}
               for t, v in sorted(types.items())}
        unknown_share = V.ratio(types.get("unknown", {}).get("conversions", 0.0), tot["conversions"])
        mix_ev = {"window": [ctx.period_start, ctx.period_end], "total_conversions": tot["conversions"],
                  "by_type": mix, "unknown_share": unknown_share,
                  "unknown_conversion_cells": sum(t["unknown_cells"] for t in types.values())}
        if ctx.mature is True and tot["conversions"] > 0:
            s6.finding("recognized_customer_mix", "Info", {"campaign_id": cid},
                       f"Campaign {cid}: reported customer mix over {tot['conversions']:g} conversions "
                       f"(unknown share {unknown_share if unknown_share is not None else 'n/a'})",
                       evidence=mix_ev, calculation={"denominator": tot["conversions"]},
                       recommendation="Report mix as context; do not mandate acquisition mode from "
                                      "existing-customer share; exclusions owned by skill-103.",
                       uncertainty="Classification depends on the platform's recognition methods.")
        else:
            s6.observe(f"Campaign {cid}: customer mix (descriptive)", campaign_id=cid, **mix_ev)
        new, ex = types.get("new"), types.get("existing")
        mc = ctx.params.get("min_conversions", cid)
        if not has_cost:
            s6.partial(f"campaign {cid}: type-specific CPA unavailable", [f"{DAILY}:cost"])
        elif new is None or ex is None or new["unknown_cost"] or ex["unknown_cost"]:
            s6.partial(f"campaign {cid}: type-specific cost not reported for both new and existing")
        elif mc.value is None:
            s6.partial(f"campaign {cid}: min_conversions unresolved ({mc.reason})")
        elif ctx.mature is not True:
            pass
        elif new["conversions"] < mc.value or ex["conversions"] < mc.value:
            s6.observe(f"Campaign {cid}: type CPA not compared (min_conversions {mc.value:g})", campaign_id=cid,
                       new_conversions=new["conversions"], existing_conversions=ex["conversions"],
                       min_conversions=mc.value, min_conversions_source=mc.source)
        else:
            s6.observe(f"Campaign {cid}: reported type-specific CPA", campaign_id=cid,
                       cpa_new=V.ratio(new["cost"], new["conversions"]),
                       cpa_existing=V.ratio(ex["cost"], ex["conversions"]), cost_new=new["cost"],
                       cost_existing=ex["cost"], new_conversions=new["conversions"],
                       existing_conversions=ex["conversions"], min_conversions=mc.value,
                       min_conversions_source=mc.source)

        # -- optional bounded acquisition test (gated)
        intent = bool(ctx.profile.get("objectives") or _camp_obj(ctx, cid) or ctx.rows(LIFE))
        gates = {"mode_known": modes.get(cid, ("unknown",))[0] != "unknown",
                 "intent_evidence": intent,
                 "recognition_ok": cid in linked and cid not in broken and cid not in unresolved_c
                 and (cid in recog_known or bool(linked.get(cid))),
                 "permission_ok": perm_ok.get(cid) is True or (cid in linked and not linked[cid]),
                 "ltv_ok": cid in approved_a}
        if not all(gates.values()):
            s6.observe(f"Campaign {cid}: acquisition test not proposable", campaign_id=cid, gates=gates)
            continue
        calc = approved_a[cid]
        cap = calc["A_bounds"][1] if calc["A_bounds"] else calc["A"]
        s6.review("acquisition_test", {"campaign_id": cid},
                  f"Campaign {cid}: objectives, permitted recognition and approved economics are evidenced. "
                  f"Propose a bounded acquisition test?",
                  evidence={"gates": gates, "mode": modes[cid], "approved_additive_value": calc["A"],
                            "approved_additive_value_max": cap, "currency": ctx.currency, "ltv": calc,
                            "profile_objectives": ctx.profile.get("objectives"),
                            "campaign_objective": _camp_obj(ctx, cid), "customer_mix": mix_ev},
                  outcomes={"test_proposed": {"severity": "Info", "recommendation":
                                              "Request-only bounded test; exclusions via skill-103, "
                                              "reconciliation via skill-071."},
                            "no_test": {"severity": None, "recommendation": "No test proposed."}},
                  guidance="Choose test_proposed only if intent is acquisition-consistent. proposal = {campaign_id, "
                           "duration_days (int > 0), new_customer_value (<= approved_additive_value_max, account "
                           "currency), currency, intent_ref}. No uplift forecast.")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-checks of AI decisions.

    Rules:   Critical outcomes (double_count_confirmed, unsafe_use_confirmed) need proposal.evidence_ref.
             test_proposed needs every gate True and a bounded proposal in account currency.
    """
    outcome = decision.get("outcome")
    proposal = decision.get("proposal") or {}
    if outcome in ("double_count_confirmed", "unsafe_use_confirmed"):
        if not _s(proposal.get("evidence_ref")):
            return [f"{outcome} needs proposal.evidence_ref pointing at supplied evidence"]
        return []
    if outcome != "test_proposed":
        return []
    problems = []
    gates = item.evidence.get("gates") or {}
    failed = sorted(k for k, v in gates.items() if v is not True)
    if not gates or failed:
        problems.append(f"test gates not satisfied: {failed or 'none recorded'}")
    if _s(proposal.get("campaign_id")) != _s(item.entity.get("campaign_id")):
        problems.append("proposal.campaign_id must equal the reviewed campaign")
    days = proposal.get("duration_days")
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        problems.append("proposal.duration_days must be a positive integer")
    val = V.num(proposal.get("new_customer_value"))
    cap = item.evidence.get("approved_additive_value_max")
    if val is None or val <= 0:
        problems.append("proposal.new_customer_value must be a positive number")
    elif cap is None or val > cap:
        problems.append(f"proposal.new_customer_value {val:g} exceeds approved additive value max {cap}")
    if _s(proposal.get("currency")).upper() != _s(item.evidence.get("currency")).upper():
        problems.append("proposal.currency must equal the account currency")
    if not _s(proposal.get("intent_ref")):
        problems.append("proposal.intent_ref must cite the approved acquisition objective")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
