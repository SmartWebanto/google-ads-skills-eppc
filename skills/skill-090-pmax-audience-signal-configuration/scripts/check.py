"""check.py — skill-090 deterministic PMax audience signal inventory, permission and refresh gates.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-090-pmax-audience-signal-configuration/SKILL.md → Analysis Steps (via RUNTIME.md)
related: skills/skill-061-customer-match-list-health — list health owner (match rates, uploads)
         skills/skill-156-first-party-data-collection-activation-strategy — permission/activation owner
rules:   PMax scope = campaigns.channel_type PERFORMANCE_MAX (case-insensitive); campaigns key column `id`,
         alternative `campaign_id` accepted. Joins use campaign_id/asset_group_id/signal_id/
         audience_resource_id/user_list_id=list_id/source_id only — names are never evidence.
         Signal kind: signal_type AUDIENCE | SEARCH_THEME (spaces/hyphens → underscores); otherwise the single
         filled field of audience_resource_id / search_theme_text decides; both/neither → unclassified gap.
         Components: `inclusion_exclusion`, alternative `inclusion`; dedupe on (audience_resource_id,
         component_id, component_type). Provenance from component_type and audience_definitions.source_platform
         (ga4 | customer_match/crm | google_ads/website | youtube | other), never list names.
         Unresolved audience/list references and duplicate conflicting list definitions are evidence gaps
         (partial + observation), never an absent list. Zero-signal groups are provable only when BOTH
         custom/pmax_groups and custom/pmax_signals manifests say complete; they are optional absence, not defects.
         Permission (external/activation_permissions): list-specific rows (list_id) take precedence over
         source rows with empty list_id; rows filtered to profile.market when both sides state a market.
         Approved = permission_status approved|granted|permitted AND consent_coverage_status covered|complete|
         verified AND permitted_destinations contains Google Ads AND restricted_data_review passed|cleared|
         not_required AND policy_eligibility eligible|compliant. denied|revoked → denied; approved status with a
         stated destination list lacking Google Ads → destination_not_permitted; anything else → unknown (blocked).
         Denied/destination_not_permitted on an ENABLED signal whose group/campaign is not paused/removed →
         provisional Info + review; Critical only via unsafe_use_confirmed with proposal.evidence_ref.
         Intended signal = group has external/pmax_signal_intent row(s) and the list source_id is in
         permitted_source_ids (or a row lists none). refresh_sla_days, alternative refresh_SLA_days; with several
         matching rows the most lenient (max) SLA is used for the Warning. Stale = (ctx.snapshot or ctx.as_of) -
         last_successful_refresh_at > SLA days. Ineligible Warning only when every stated network is
         ineligible; unknown linkage/eligibility → Info unverified_eligibility. Match rates are observations only.
         verify(): experiment proposals must name an asset group in the batch and a source/list whose permission
         resolves approved and whose source is permitted by the group's intent.
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

SKILL = "skill-090-pmax-audience-signal-configuration"
VERSION = "1.0.0"

GROUPS = "custom/pmax_groups"
SIGNALS = "custom/pmax_signals"
COMPONENTS = "custom/pmax_audience_components"
DEFINITIONS = "external/audience_definitions"
PERMISSIONS = "external/activation_permissions"
INTENT = "external/pmax_signal_intent"

SIGNAL_COLS = ["campaign_id", "asset_group_id", "signal_id", "signal_type", "audience_resource_id",
               "search_theme_text", "status"]
PERM_COLS = ["source_id", "list_id", "market", "permission_status", "consent_coverage_status",
             "permitted_destinations", "restricted_data_review", "policy_eligibility", "evidence_reference"]
LIST_SEPS = (";", "|", ",")

CHECKS = (
    ("signal_inventory", "Groups, signals, audience components and list definitions joined"),
    ("signal_classification", "Signal provenance classification and offer relevance"),
    ("activation_permission_gate", "First-party list permission gate"),
    ("eligibility_refresh", "Intended signal linkage, eligibility and refresh SLA"),
    ("optional_absence", "Optional signal absence separated from broken signals"),
    ("signal_experiment", "Authorized signal experiment proposals"),
)
TITLES = dict(CHECKS)

_APPROVED_STATUS = {"approved", "granted", "permitted"}
_DENIED_STATUS = {"denied", "revoked"}
_CONSENT_OK = {"covered", "complete", "verified"}
_REVIEW_OK = {"passed", "cleared", "not_required"}
_POLICY_OK = {"eligible", "compliant"}
_LINK_BROKEN = {"broken", "failed", "unlinked", "disconnected"}
_LINK_OK = {"linked", "active", "connected", "ok", "healthy"}
_NET_ELIGIBLE = {"eligible", "serving"}
_NET_INELIGIBLE = {"ineligible", "not_eligible"}
_INACTIVE = {"PAUSED", "REMOVED"}

_TYPE_CLASS = {
    "USER_LIST": "user_list", "CUSTOMER_MATCH": "user_list", "REMARKETING": "user_list", "YOUR_DATA": "user_list",
    "CUSTOM_SEGMENT": "custom_segment", "CUSTOM_AUDIENCE": "custom_segment", "CUSTOM_INTENT": "custom_segment",
    "CUSTOM_AFFINITY": "custom_segment",
    "INTEREST": "interest", "USER_INTEREST": "interest", "AFFINITY": "interest", "IN_MARKET": "interest",
    "LIFE_EVENT": "interest", "DETAILED_DEMOGRAPHIC": "interest",
    "AGE": "demographic", "AGE_RANGE": "demographic", "GENDER": "demographic", "PARENTAL_STATUS": "demographic",
    "INCOME": "demographic", "INCOME_RANGE": "demographic", "DEMOGRAPHIC": "demographic",
}
_PLATFORM = (
    ("ga4", {"ga4", "google_analytics", "google_analytics_4", "analytics"}),
    ("customer_match", {"customer_match", "crm", "customer_list", "data_manager", "upload"}),
    ("youtube", {"youtube"}),
    ("ads_remarketing", {"google_ads", "website", "tag", "google_tag", "ads_tag", "app"}),
)


# ---------------------------------------------------------------------------------------------- helpers
def _norm(v) -> str:
    return V.norm_text(v).replace(" ", "_").replace("-", "_")


def _id(v) -> str:
    return str(v).strip() if v is not None else ""


def _col(table, *names) -> str | None:
    """First column name present in the table (documented alternatives only)."""
    if table is None:
        return None
    return next((n for n in names if n in table.columns), None)


def _gaps(ctx, key: str, cols) -> list[str]:
    """Exact missing 'file'/'file:column' entries for an optional table, without declaring a check."""
    t = ctx.table(key)
    if t is None:
        return [f"{key} (file)"]
    return [f"{key}:{c}" for c in t.missing(cols)]


def _complete(ctx, key: str) -> bool:
    t = ctx.table(key)
    return t is not None and t.complete is True and not t.truncated


def _signal_kind(row) -> str:
    t = _norm(row.get("signal_type")).upper()
    if t in ("AUDIENCE", "AUDIENCE_SIGNAL"):
        return "audience"
    if t in ("SEARCH_THEME", "SEARCH_THEMES"):
        return "search_theme"
    aud, theme = bool(_id(row.get("audience_resource_id"))), bool(_id(row.get("search_theme_text")))
    if aud != theme:
        return "audience" if aud else "search_theme"
    return "unclassified"


def _platform(source_platform) -> str:
    p = _norm(source_platform)
    if not p:
        return "first_party_unknown_source"
    for name, tokens in _PLATFORM:
        if p in tokens:
            return name
    return "first_party_other"


def _destinations_allow_ads(v) -> bool | None:
    """True if a destination names Google Ads, False if destinations are stated without it, None if empty."""
    items = [_norm(x).replace("_", "") for x in V.split_list(v, LIST_SEPS)]
    if not items:
        return None
    return any("googleads" in x for x in items)


def _row_state(r) -> tuple[str, list[str]]:
    """Classify one permission row. Rules: unknown/empty cells are never approval."""
    status = _norm(r.get("permission_status"))
    if status in _DENIED_STATUS:
        return "denied", [f"permission_status={status}"]
    reasons = []
    if status not in _APPROVED_STATUS:
        reasons.append(f"permission_status={status or 'unknown'}")
    dest = _destinations_allow_ads(r.get("permitted_destinations"))
    if dest is False and status in _APPROVED_STATUS:
        return "destination_not_permitted", [f"permitted_destinations={r.get('permitted_destinations')}"]
    if dest is not True:
        reasons.append(f"permitted_destinations={r.get('permitted_destinations') or 'unknown'}")
    for col, ok in (("consent_coverage_status", _CONSENT_OK), ("restricted_data_review", _REVIEW_OK),
                    ("policy_eligibility", _POLICY_OK)):
        val = _norm(r.get(col))
        if val not in ok:
            reasons.append(f"{col}={val or 'unknown'}")
    return ("approved", []) if not reasons else ("unknown", reasons)


def _markets(ctx) -> set[str]:
    m = ctx.profile.get("market")
    vals = m if isinstance(m, list) else V.split_list(m, LIST_SEPS)
    return {_norm(x) for x in vals if _norm(x)}


def _resolve_permission(ctx, list_id: str, source_id: str) -> dict:
    """Permission state for a list (list rows first, else source rows with empty list_id), market-filtered.

    Rules:   any denied → denied; else any destination_not_permitted → that; all approved (>=1 row) → approved;
             otherwise unknown with the failing/unknown fields. No row → unknown (blocked).
    """
    rows = ctx.rows(PERMISSIONS)
    specific = [r for r in rows if list_id and _id(r.get("list_id")) == list_id]
    cand = specific or [r for r in rows if not _id(r.get("list_id")) and source_id and _id(r.get("source_id")) == source_id]
    markets = _markets(ctx)
    if markets:
        cand = [r for r in cand if not V.split_list(r.get("market"), LIST_SEPS)
                or markets & {_norm(x) for x in V.split_list(r.get("market"), LIST_SEPS)}]
    refs = sorted({_id(r.get("evidence_reference")) for r in cand if _id(r.get("evidence_reference"))})
    base = {"list_id": list_id or None, "source_id": source_id or None, "rows": len(cand), "evidence_references": refs,
            "markets": sorted(markets), "matched_on": "list_id" if specific else "source_id" if cand else None,
            "retention_limit_days": sorted({_id(r.get("retention_limit_days")) for r in cand if r.get("retention_limit_days")}),
            "intended_use": sorted({_id(r.get("intended_use")) for r in cand if r.get("intended_use")})}
    if not cand:
        return {**base, "state": "unknown", "reasons": ["no permission row for this list/source and market"]}
    states = [_row_state(r) for r in sorted(cand, key=lambda r: (_id(r.get("list_id")), _id(r.get("market"))))]
    for want in ("denied", "destination_not_permitted"):
        hit = [why for s, why in states if s == want]
        if hit:
            return {**base, "state": want, "reasons": sorted({w for x in hit for w in x})}
    if all(s == "approved" for s, _ in states):
        return {**base, "state": "approved", "reasons": []}
    return {**base, "state": "unknown", "reasons": sorted({w for _, why in states for w in why})}


def _eligibility(v) -> str:
    """'ineligible' only when every stated network is ineligible; 'unverified' when none is known eligible."""
    states = []
    for tok in V.split_list(v, LIST_SEPS):
        status = _norm(tok.split(":", 1)[-1] if ":" in tok else tok)
        states.append(True if status in _NET_ELIGIBLE else False if status in _NET_INELIGIBLE else None)
    if states and all(s is False for s in states):
        return "ineligible"
    if not states or True not in states:
        return "unverified"
    return "eligible" if all(s is True for s in states) else "partially_eligible"


class _Model:
    """Joined PMax inventory shared by all checks (built once per run)."""

    def __init__(self, ctx, camp_key: str):
        self.camp_key = camp_key
        self.campaigns = {}
        for r in sorted(ctx.rows("campaigns"), key=lambda r: _id(r.get(camp_key))):
            cid = _id(r.get(camp_key))
            if cid and _norm(r.get("channel_type")).upper() == "PERFORMANCE_MAX":
                self.campaigns.setdefault(cid, r)
        known = {_id(r.get(camp_key)) for r in ctx.rows("campaigns")}
        self.groups: dict[tuple, dict] = {}
        self.unknown_campaign_groups: list[tuple] = []
        for r in ctx.rows(GROUPS):
            key = (_id(r.get("campaign_id")), _id(r.get("asset_group_id")))
            if not key[1]:
                continue
            if key[0] in self.campaigns:
                self.groups.setdefault(key, r)
            elif key[0] not in known:
                self.unknown_campaign_groups.append(key)
        self.signals: dict[tuple, list[dict]] = {k: [] for k in self.groups}
        self.orphans: list[str] = []
        seen = set()
        for r in sorted(ctx.rows(SIGNALS), key=lambda r: (_id(r.get("campaign_id")), _id(r.get("asset_group_id")),
                                                         _id(r.get("signal_id")))):
            key = (_id(r.get("campaign_id")), _id(r.get("asset_group_id")))
            sk = key + (_id(r.get("signal_id")),)
            if sk in seen:
                continue
            seen.add(sk)
            if key in self.signals:
                self.signals[key].append(r)
            elif key[0] in self.campaigns or key[0] not in known:
                self.orphans.append(f"{key[0]}/{key[1]}/{sk[2]}")
        self.components_ok = not _gaps(ctx, COMPONENTS, ["audience_resource_id", "component_id", "component_type",
                                                         "user_list_id"])
        self.incl_col = _col(ctx.table(COMPONENTS), "inclusion_exclusion", "inclusion")
        self.components: dict[str, list[dict]] = {}
        if self.components_ok:
            dedupe = set()
            for r in sorted(ctx.rows(COMPONENTS), key=lambda r: (_id(r.get("audience_resource_id")),
                                                                _id(r.get("component_id")), _id(r.get("component_type")))):
                k = (_id(r.get("audience_resource_id")), _id(r.get("component_id")), _id(r.get("component_type")))
                if k in dedupe or not k[0]:
                    continue
                dedupe.add(k)
                self.components.setdefault(k[0], []).append(r)
        self.definitions_ok = not _gaps(ctx, DEFINITIONS, ["list_id", "source_id", "source_platform"])
        self.definitions: dict[str, dict] = {}
        self.ambiguous_lists: set[str] = set()
        if self.definitions_ok:
            for r in ctx.rows(DEFINITIONS):
                lid = _id(r.get("list_id"))
                if not lid:
                    continue
                if lid in self.definitions and self.definitions[lid] != r:
                    self.ambiguous_lists.add(lid)
                self.definitions.setdefault(lid, r)
            for lid in self.ambiguous_lists:
                del self.definitions[lid]

    def status(self, key) -> dict:
        g = self.groups[key]
        c = self.campaigns.get(key[0]) or {}
        return {"group_status": g.get("status"), "campaign_status": c.get("status")}

    def active_parent(self, key) -> bool:
        s = self.status(key)
        return _norm(s["group_status"]).upper() not in _INACTIVE and _norm(s["campaign_status"]).upper() not in _INACTIVE

    def live_signals(self, key) -> list[dict]:
        return [s for s in self.signals.get(key, []) if _norm(s.get("status")).upper() != "REMOVED"]

    def enabled_list_uses(self, key) -> dict[str, list[str]]:
        """list_id -> signal_ids for user-list components of ENABLED audience signals in a group."""
        out: dict[str, list[str]] = {}
        for s in self.signals.get(key, []):
            if _norm(s.get("status")).upper() != "ENABLED" or _signal_kind(s) != "audience":
                continue
            for comp in self.components.get(_id(s.get("audience_resource_id")), []):
                lid = _id(comp.get("user_list_id"))
                if lid:
                    out.setdefault(lid, [])
                    if _id(s.get("signal_id")) not in out[lid]:
                        out[lid].append(_id(s.get("signal_id")))
        return out

    def classify(self, comp) -> str:
        cls = _TYPE_CLASS.get(_norm(comp.get("component_type")).upper())
        if cls is None:
            cls = "user_list" if _id(comp.get("user_list_id")) else \
                "custom_segment" if _id(comp.get("custom_segment_id")) else "unclassified"
        if cls != "user_list":
            return cls
        lid = _id(comp.get("user_list_id"))
        if not lid or lid not in self.definitions:
            return "user_list_unresolved"
        return _platform(self.definitions[lid].get("source_platform"))


def _intent(ctx) -> tuple[dict[str, list[dict]], list[str], str | None]:
    """Intent rows by asset_group_id, missing columns, SLA column name."""
    t = ctx.table(INTENT)
    sla = _col(t, "refresh_sla_days", "refresh_SLA_days")
    missing = _gaps(ctx, INTENT, ["asset_group_id", "permitted_source_ids"])
    if t is not None and sla is None:
        missing.append(f"{INTENT}:refresh_sla_days")
    by: dict[str, list[dict]] = {}
    for r in ctx.rows(INTENT) if t is not None else []:
        if _id(r.get("asset_group_id")):
            by.setdefault(_id(r.get("asset_group_id")), []).append(r)
    return by, missing, sla


def _permits(intent_rows: list[dict], source_id: str) -> tuple[bool, list[dict]]:
    """(intended?, matching rows): a row with no permitted_source_ids is unrestricted."""
    match = [r for r in intent_rows if not V.split_list(r.get("permitted_source_ids"), LIST_SEPS)
             or (source_id and source_id in V.split_list(r.get("permitted_source_ids"), LIST_SEPS))]
    return bool(match), match


def _entity(key, list_id=None) -> dict:
    e = {"campaign_id": key[0], "asset_group_id": key[1]}
    if list_id is not None:
        e["list_id"] = list_id
    return e


# ---------------------------------------------------------------------------------------------- checks
def run(ctx) -> None:
    """Run steps 1-6 of skill-090.

    Rules:   every declared check ends with a coverage status; dependent checks are skipped with the
             inventory's missing inputs when the inventory cannot run.
    """
    camp_key = _col(ctx.table("campaigns"), "id", "campaign_id") or "id"
    inv = ctx.check("signal_inventory", TITLES["signal_inventory"],
                    {"campaigns": [camp_key, "channel_type"], GROUPS: ["campaign_id", "asset_group_id", "status"],
                     SIGNALS: SIGNAL_COLS})
    if not inv.runnable:
        for cid, title in CHECKS[1:]:
            ctx.check(cid, title).skip("signal inventory unavailable", inv.missing)
        return
    m = _Model(ctx, camp_key)
    if not m.campaigns:
        inv.not_applicable("no PERFORMANCE_MAX campaigns in campaigns inventory")
        for cid, title in CHECKS[1:]:
            ctx.check(cid, title, applicable=False, na_reason="no PERFORMANCE_MAX campaigns in campaigns inventory")
        return
    _inventory(ctx, inv, m)
    _classification(ctx, m)
    perms = _permission_gate(ctx, m)
    _eligibility_refresh(ctx, m)
    _optional_absence(ctx, m)
    _experiment(ctx, m, perms)


def _inventory(ctx, inv, m: _Model) -> None:
    """Step 1: left-join groups → signals → components → list definitions; gaps are partial, not absence."""
    signals_complete = _complete(ctx, SIGNALS) and _complete(ctx, GROUPS)
    comp_gaps = _gaps(ctx, COMPONENTS, ["audience_resource_id", "component_id", "component_type", "user_list_id"])
    def_gaps = _gaps(ctx, DEFINITIONS, ["list_id", "source_id", "source_platform"])
    if comp_gaps:
        inv.partial("audience components unavailable: audience references unresolved", comp_gaps)
    elif def_gaps:
        inv.partial("list definitions unavailable: user-list components unresolved", def_gaps)
    groups_by_campaign: dict[str, int] = {c: 0 for c in m.campaigns}
    unresolved_refs, unresolved_lists, unclassified, unprovable_empty = [], set(), [], []
    for key in sorted(m.groups):
        groups_by_campaign[key[0]] += 1
        sigs = m.signals[key]
        counts = {"audience": 0, "search_theme": 0, "unclassified": 0}
        by_status: dict[str, int] = {}
        refs, comp_ids, lists, group_unresolved = [], [], set(), []
        for s in sigs:
            kind = _signal_kind(s)
            st = _norm(s.get("status")).upper() or "UNKNOWN"
            by_status[st] = by_status.get(st, 0) + 1
            if st == "REMOVED":
                continue
            counts[kind] += 1
            if kind == "unclassified":
                unclassified.append(f"{key[0]}/{key[1]}/{_id(s.get('signal_id'))}")
            if kind != "audience":
                continue
            ref = _id(s.get("audience_resource_id"))
            refs.append(ref)
            if not m.components_ok:
                continue
            comps = m.components.get(ref)
            if not comps:
                unresolved_refs.append(f"{key[1]}:{ref}")
                group_unresolved.append(ref)
                continue
            for c in comps:
                comp_ids.append(_id(c.get("component_id")))
                lid = _id(c.get("user_list_id"))
                if lid:
                    lists.add(lid)
                    if m.definitions_ok and lid not in m.definitions:
                        unresolved_lists.add(lid)
        if not sigs and not signals_complete:
            unprovable_empty.append(key[1])
        inv.observe(f"Asset group {key[1]} (campaign {key[0]}): signal inventory", campaign_id=key[0],
                    asset_group_id=key[1], **m.status(key), audience_signals=counts["audience"],
                    search_themes=counts["search_theme"], unclassified_signals=counts["unclassified"],
                    signal_rows_by_status=by_status, signal_ids=sorted(_id(s.get("signal_id")) for s in sigs),
                    audience_resource_ids=sorted(set(refs)), component_ids=sorted(set(comp_ids)),
                    constituent_list_ids=sorted(lists),
                    resolved_list_ids=sorted(lists - unresolved_lists) if m.definitions_ok else [],
                    unresolved_audience_refs=sorted(group_unresolved),
                    zero_signal_rows=not sigs, zero_signal_provable=signals_complete)
    for cid in sorted(groups_by_campaign):
        n = groups_by_campaign[cid]
        inv.observe(f"PMax campaign {cid}: {n} asset groups in inventory", campaign_id=cid, asset_groups=n,
                    campaign_status=m.campaigns[cid].get("status"),
                    zero_groups_provable=_complete(ctx, GROUPS) if n == 0 else None)
    if unresolved_refs:
        inv.partial(f"{len(unresolved_refs)} audience signal references have no component rows (evidence gap, "
                    "not an absent list)", [f"{COMPONENTS}:audience_resource_id"])
        inv.observe("Unresolved audience signal references", references=sorted(unresolved_refs))
    if unresolved_lists or m.ambiguous_lists:
        inv.partial(f"{len(unresolved_lists)} component user lists missing and {len(m.ambiguous_lists)} with "
                    "conflicting definitions (evidence gap)", [f"{DEFINITIONS}:list_id"])
        inv.observe("Unresolved or ambiguous list definitions", list_ids=sorted(unresolved_lists),
                    ambiguous_list_ids=sorted(m.ambiguous_lists))
    if unclassified:
        inv.partial(f"{len(unclassified)} signals neither audience nor search theme", [f"{SIGNALS}:signal_type"])
        inv.observe("Unclassified signal rows", signals=sorted(unclassified))
    if m.orphans:
        inv.partial(f"{len(m.orphans)} signal rows reference groups absent from {GROUPS}", [f"{GROUPS}:asset_group_id"])
        inv.observe("Signals without a PMax group row", signals=sorted(m.orphans))
    if m.unknown_campaign_groups:
        inv.partial(f"{len(m.unknown_campaign_groups)} groups reference campaigns absent from campaigns",
                    [f"campaigns:{m.camp_key}"])
    if unprovable_empty:
        inv.partial(f"{len(unprovable_empty)} groups without signal rows: zero-signal state unprovable "
                    "(groups/signals manifest not complete)")


def _classification(ctx, m: _Model) -> None:
    """Step 2: provenance classes from types/definitions; offer relevance is a per-group review."""
    incl = m.incl_col or "inclusion_exclusion"
    chk = ctx.check("signal_classification", TITLES["signal_classification"],
                    {COMPONENTS: ["audience_resource_id", "component_id", "component_type", "user_list_id",
                                  "custom_segment_id", incl, "combination_operator", "definition_text"]})
    if not chk.runnable:
        return
    if not m.definitions_ok:
        chk.partial("user-list provenance unresolved without list definitions",
                    _gaps(ctx, DEFINITIONS, ["list_id", "source_id", "source_platform"]))
    intent, _, _ = _intent(ctx)
    has_theme = "theme" in ctx.table(GROUPS).columns
    has_intent = ctx.table(INTENT) is not None
    not_reviewable = []
    totals: dict[str, int] = {}
    for key in sorted(m.groups):
        live = m.live_signals(key)
        if not live:
            continue
        audiences, themes = [], []
        for s in live:
            kind = _signal_kind(s)
            if kind == "search_theme":
                themes.append(s.get("search_theme_text"))
                continue
            if kind != "audience":
                continue
            ref = _id(s.get("audience_resource_id"))
            comps = []
            for c in m.components.get(ref, []):
                cls = m.classify(c)
                totals[cls] = totals.get(cls, 0) + 1
                d = m.definitions.get(_id(c.get("user_list_id"))) or {}
                comps.append({"component_id": c.get("component_id"), "component_type": c.get("component_type"),
                              "class": cls, "user_list_id": c.get("user_list_id"),
                              "custom_segment_id": c.get("custom_segment_id"), "inclusion": c.get(incl),
                              "combination_operator": c.get("combination_operator"),
                              "definition_text": c.get("definition_text"),
                              "list_definition": d.get("definition_expression"), "entry_event": d.get("entry_event"),
                              "source_platform": d.get("source_platform")})
            audiences.append({"signal_id": s.get("signal_id"), "status": s.get("status"),
                              "audience_resource_id": ref, "components": comps,
                              "resolved": bool(comps)})
        classes = sorted({c["class"] for a in audiences for c in a["components"]})
        chk.observe(f"Asset group {key[1]}: signal provenance classes", campaign_id=key[0], asset_group_id=key[1],
                    classes=classes, audience_signals=len(audiences), search_themes=len(themes),
                    exclusion_components=sum(1 for a in audiences for c in a["components"]
                                             if _norm(c["inclusion"]) in ("exclusion", "exclude", "excluded", "false", "no")))
        theme = m.groups[key].get("theme") if has_theme else None
        rows = intent.get(key[1], [])
        if not _id(theme) and not rows:
            not_reviewable.append(key[1])
            continue
        chk.review("signal_offer_relevance", _entity(key),
                   f"Do the signals of asset group {key[1]} (campaign {key[0]}) fit its declared offer/theme and "
                   "approved signal intent?",
                   evidence={"theme": theme, "intent": [{k: r.get(k) for k in ("signal_role", "business_segment",
                                                                              "desired_characteristics",
                                                                              "source_offer_fit", "owner")}
                                                        for r in rows],
                             "audience_signals": audiences, "search_themes": sorted(_id(t) for t in themes),
                             "profile_objectives": ctx.profile.get("objectives")},
                   outcomes={"fits_offer": {"severity": None, "recommendation": "Keep; signals match the declared offer."},
                             "plausible_experiment": {"severity": "Info", "recommendation":
                                                      "Treat as an optional, permitted experiment; document the hypothesis."},
                             "uncertain": {"severity": "Info", "recommendation":
                                           "Ask the group owner which customer the signals should describe."}},
                   guidance="Judge from definitions, provenance classes and the declared theme/intent only; never from "
                            "audience or list names. Signals are optional guidance, not targeting restrictions.")
    if not_reviewable:
        missing = ([] if has_theme else [f"{GROUPS}:theme"]) + ([] if has_intent else [f"{INTENT} (file)"])
        chk.partial(f"{len(not_reviewable)} groups lack a declared theme and intent: relevance not reviewable",
                    missing or [f"{GROUPS}:theme"])
        chk.observe("Groups with signals but no declared theme/intent", asset_group_ids=sorted(not_reviewable))
    chk.observe("Component provenance totals", **{k: totals[k] for k in sorted(totals)})


def _permission_gate(ctx, m: _Model) -> dict:
    """Step 3: permission for first-party lists in ENABLED signals; returns (group, list) → permission."""
    chk = ctx.check("activation_permission_gate", TITLES["activation_permission_gate"],
                    {COMPONENTS: ["audience_resource_id", "component_type", "user_list_id"], PERMISSIONS: PERM_COLS})
    out: dict[tuple, dict] = {}
    if not chk.runnable:
        return out
    if not m.definitions_ok:
        chk.partial("source-level permission rows unusable without list definitions",
                    _gaps(ctx, DEFINITIONS, ["list_id", "source_id", "source_platform"]))
    counts = {"approved": 0, "unknown": 0, "denied": 0, "destination_not_permitted": 0}
    for key in sorted(m.groups):
        for lid, sig_ids in sorted(m.enabled_list_uses(key).items()):
            d = m.definitions.get(lid) or {}
            p = _resolve_permission(ctx, lid, _id(d.get("source_id")))
            out[(key, lid)] = p
            counts[p["state"]] += 1
            entity = _entity(key, lid)
            ev = {**p, "signal_ids": sorted(sig_ids), **m.status(key),
                  "source_platform": d.get("source_platform"), "definition_resolved": bool(d)}
            if p["state"] == "approved":
                chk.observe(f"List {lid} in group {key[1]}: permission approved", **{**ev, **entity})
            elif p["state"] == "unknown":
                chk.finding("permission_unknown", "Info", entity,
                            f"First-party list {lid} in ENABLED signal(s) of group {key[1]} has no approved permission "
                            f"evidence ({'; '.join(p['reasons'])})", evidence=ev,
                            recommendation="Blocked: propose no reuse, refresh or expansion of this list; refer "
                                           "permission readiness to the authorized owner via skill-156.",
                            uncertainty="Unknown permission is an evidence gap, not proof of unsafe use.")
            elif m.active_parent(key):
                prov = chk.finding("unsafe_first_party_use", "Info", entity,
                                   f"First-party list {lid} is used in ENABLED signal(s) of group {key[1]} while its "
                                   f"permission is {p['state']} ({'; '.join(p['reasons'])})", evidence=ev,
                                   recommendation="Refer to the authorized owner (skill-156) before any further use; "
                                                  "propose no activation.",
                                   uncertainty="Signal usage and permission scope are evidenced; whether the use is "
                                               "materially unsafe needs review.")
                chk.review("unsafe_first_party_use", entity,
                           f"Is the active use of list {lid} in group {key[1]} directly evidenced as materially "
                           "unsafe first-party use contrary to the approved permitted scope?",
                           evidence=ev, provisional=prov,
                           outcomes={"unsafe_use_confirmed": {"severity": "Critical", "recommendation":
                                                              "Escalate to the data owner now; request removal of the "
                                                              "list from the signal after owner review."},
                                     "not_unsafe": {"severity": None, "recommendation":
                                                    "No unsafe use; keep the permission record current."},
                                     "uncertain": {"severity": "Info", "recommendation":
                                                   "Ask the authorized owner (skill-156) to confirm scope."}},
                           guidance="unsafe_use_confirmed requires proposal.evidence_ref citing the supplied permission "
                                    "or definition evidence; list or source names are not evidence.")
            else:
                chk.observe(f"List {lid} in paused/removed group {key[1]}: permission {p['state']} (blocked)",
                            **{**ev, **entity})
    chk.observe("First-party lists in ENABLED signals by permission state", **counts)
    return out


def _eligibility_refresh(ctx, m: _Model) -> None:
    """Step 4: intended signals' linkage, network eligibility and refresh SLA; match rates observed only."""
    intent, intent_missing, sla_col = _intent(ctx)
    chk = ctx.check("eligibility_refresh", TITLES["eligibility_refresh"],
                    {COMPONENTS: ["audience_resource_id", "user_list_id"],
                     DEFINITIONS: ["list_id", "source_id", "linkage_status", "eligibility_by_network",
                                   "last_successful_refresh_at"]})
    if not chk.runnable:
        return
    if intent_missing:
        chk.skip("intended signal roles unavailable", intent_missing)
        return
    ref_date = ctx.snapshot or ctx.as_of
    if ref_date is None:
        chk.partial("reference date unknown: refresh age not computable", ["account:snapshot_date"])
    rates = ctx.table("audiences")
    rate_ok = rates is not None and not rates.missing(["list_id", "match_rate"])
    rate_by = {}
    if rate_ok:
        for r in sorted(rates.rows, key=lambda r: _id(r.get("list_id"))):
            rate_by.setdefault(_id(r.get("list_id")), r)
    evaluated = unresolved = not_intended = 0
    for key in sorted(m.groups):
        rows = intent.get(key[1], [])
        for lid, sig_ids in sorted(m.enabled_list_uses(key).items()):
            d = m.definitions.get(lid)
            if d is None:
                unresolved += 1
                continue
            src = _id(d.get("source_id"))
            intended, match = _permits(rows, src)
            if not intended:
                not_intended += 1
                chk.observe(f"List {lid} in group {key[1]} is not an intended source (no approved intent row)",
                            **_entity(key, lid), source_id=src, intent_rows=len(rows))
                continue
            evaluated += 1
            entity = _entity(key, lid)
            base = {"source_id": src, "signal_ids": sorted(sig_ids), "evidence_reference": d.get("evidence_reference"),
                    "intent_roles": sorted(_id(r.get("signal_role")) for r in match)}
            if lid in rate_by:
                rr = rate_by[lid]
                chk.observe(f"List {lid}: supplied match rate (diagnostic only; health via skill-061)", **entity,
                            match_rate=ctx.rate(rr.get("match_rate")),
                            match_rate_definition=rr.get("match_rate_definition"))
            link = _norm(d.get("linkage_status"))
            elig = _eligibility(d.get("eligibility_by_network"))
            healthy = True
            if link in _LINK_BROKEN:
                healthy = False
                chk.finding("broken_linkage", "Warning", entity,
                            f"Intended signal list {lid} (group {key[1]}) has linkage_status={link}",
                            evidence={**base, "linkage_status": d.get("linkage_status")},
                            recommendation="Ask the list owner to restore the source link; list health via skill-061.",
                            uncertainty="Linkage status is as of the definition snapshot.")
            if elig == "ineligible":
                healthy = False
                chk.finding("ineligible_all_networks", "Warning", entity,
                            f"Intended signal list {lid} (group {key[1]}) is ineligible on every stated network",
                            evidence={**base, "eligibility_by_network": d.get("eligibility_by_network")},
                            recommendation="Review eligibility cause with the list owner (skill-061); no size gate implied.",
                            uncertainty="Eligibility per network as exported; platform thresholds not asserted here.")
            if link not in _LINK_BROKEN | _LINK_OK or elig == "unverified":
                healthy = False
                chk.finding("unverified_eligibility", "Info", entity,
                            f"Intended signal list {lid} (group {key[1]}): linkage/eligibility not verified",
                            evidence={**base, "linkage_status": d.get("linkage_status"),
                                      "eligibility_by_network": d.get("eligibility_by_network"), "eligibility": elig},
                            recommendation="Request current linkage and per-network eligibility evidence.",
                            uncertainty="Unknown is not broken.")
            slas = sorted(x for x in (V.num(r.get(sla_col)) for r in match) if x is not None)
            last = V.parse_date(d.get("last_successful_refresh_at"))
            if not slas or last is None:
                healthy = False
                chk.finding("missing_refresh_evidence", "Info", entity,
                            f"Intended signal list {lid} (group {key[1]}): refresh "
                            f"{'SLA' if not slas else 'date'} missing",
                            evidence={**base, "last_successful_refresh_at": d.get("last_successful_refresh_at"),
                                      "refresh_sla_days": slas, "sla_column": sla_col},
                            recommendation="Request the last successful refresh and the approved refresh SLA.",
                            uncertainty="Freshness unknown, not stale.")
            elif ref_date is not None:
                age = (ref_date - last).days
                if age < 0:
                    chk.partial(f"list {lid}: last_successful_refresh_at {last} after reference date {ref_date}",
                                [f"{DEFINITIONS}:last_successful_refresh_at"])
                    healthy = False
                elif age > slas[-1]:
                    healthy = False
                    chk.finding("stale_refresh_sla", "Warning", entity,
                                f"Intended signal list {lid} (group {key[1]}) last refreshed {age}d before "
                                f"{ref_date}, beyond its approved SLA of {slas[-1]:g}d",
                                evidence=base,
                                calculation={"reference_date": ref_date, "reference_source":
                                             "account.snapshot_date" if ctx.snapshot else "as_of",
                                             "last_successful_refresh_at": last, "age_days": age,
                                             "refresh_sla_days": slas[-1], "sla_candidates": slas,
                                             "sla_source": f"{INTENT}:{sla_col}"},
                                recommendation="Ask the list owner to restore refresh; refresh proposals only after "
                                               "the permission gate passes (skill-156).",
                                uncertainty="Refresh date as exported; membership impact not estimated.")
            if healthy:
                chk.observe(f"Intended signal list {lid} (group {key[1]}): linkage, eligibility and refresh within SLA",
                            **entity, linkage_status=d.get("linkage_status"), eligibility=elig,
                            last_successful_refresh_at=last, refresh_sla_days=slas[-1] if slas else None)
    if unresolved:
        chk.partial(f"{unresolved} list uses without a definition row not evaluated", [f"{DEFINITIONS}:list_id"])
    if not rate_ok:
        chk.observe("Match rates not supplied in audiences (optional; list health owned by skill-061)")
    chk.observe("Intended signal list evaluation totals", evaluated=evaluated, not_intended=not_intended,
                unresolved=unresolved)


def _optional_absence(ctx, m: _Model) -> None:
    """Step 5: zero-signal groups and missing GA4/Customer Match coverage are observations, never defects."""
    chk = ctx.check("optional_absence", TITLES["optional_absence"],
                    {GROUPS: ["campaign_id", "asset_group_id"], SIGNALS: ["campaign_id", "asset_group_id", "status"]})
    if not chk.runnable:
        return
    provable = _complete(ctx, SIGNALS) and _complete(ctx, GROUPS)
    empty = [k for k in sorted(m.groups) if not m.live_signals(k)]
    themes_only = [k for k in sorted(m.groups) if m.live_signals(k)
                   and all(_signal_kind(s) == "search_theme" for s in m.live_signals(k))]
    if provable:
        for k in empty:
            chk.observe(f"Asset group {k[1]} has no audience signals or search themes (optional, not a defect)",
                        **_entity(k), **m.status(k))
    elif empty:
        chk.partial(f"{len(empty)} groups without live signal rows: absence unprovable (manifest not complete)")
    for k in themes_only:
        chk.observe(f"Asset group {k[1]} uses search themes only (optional audience signals absent)", **_entity(k))
    classes: set[str] = set()
    refs_ok = m.components_ok and m.definitions_ok and not m.ambiguous_lists
    for k in sorted(m.groups):
        for s in m.live_signals(k):
            if _signal_kind(s) != "audience":
                continue
            comps = m.components.get(_id(s.get("audience_resource_id")), [])
            refs_ok = refs_ok and bool(comps)
            classes |= {m.classify(c) for c in comps}
    claimable = refs_ok and provable and _complete(ctx, COMPONENTS) and "user_list_unresolved" not in classes
    if claimable:
        chk.observe("First-party signal coverage (optional; absence is not a defect)",
                    ga4_components="ga4" in classes, customer_match_components="customer_match" in classes,
                    first_party_classes=sorted(c for c in classes if c not in
                                               ("custom_segment", "interest", "demographic", "unclassified")),
                    classes=sorted(classes))
    else:
        chk.partial("GA4/Customer Match coverage not claimable: components/definitions incomplete or unresolved")


def _experiment(ctx, m: _Model, perms: dict) -> None:
    """Step 6: one batch review over permission-approved sources permitted by each group's intent."""
    intent, intent_missing, _ = _intent(ctx)
    chk = ctx.check("signal_experiment", TITLES["signal_experiment"], {PERMISSIONS: PERM_COLS})
    if not chk.runnable:
        return
    if intent_missing:
        chk.skip("approved signal intent unavailable: no proposal basis", intent_missing)
        return
    approved = []
    seen = set()
    for r in sorted(ctx.rows(PERMISSIONS), key=lambda r: (_id(r.get("source_id")), _id(r.get("list_id")))):
        k = (_id(r.get("source_id")), _id(r.get("list_id")))
        if k in seen or not (k[0] or k[1]):
            continue
        seen.add(k)
        src = k[0] or _id((m.definitions.get(k[1]) or {}).get("source_id"))
        p = _resolve_permission(ctx, k[1], src)
        if p["state"] == "approved":
            approved.append({"source_id": src or None, "list_id": k[1] or None,
                             "evidence_references": p["evidence_references"]})
    groups = []
    no_intent = []
    for key in sorted(m.groups):
        rows = intent.get(key[1], [])
        if not rows:
            no_intent.append(key[1])
            continue
        used = set(m.enabled_list_uses(key))
        cands = [dict(c, already_in_group=bool(c["list_id"] and c["list_id"] in used))
                 for c in approved if _permits(rows, c["source_id"] or "")[0]]
        if cands:
            groups.append({"campaign_id": key[0], "asset_group_id": key[1], "theme": m.groups[key].get("theme"),
                           "intent": [{k: r.get(k) for k in ("signal_role", "business_segment", "desired_characteristics",
                                                            "source_offer_fit", "permitted_source_ids", "owner")}
                                      for r in rows],
                           "candidates": cands})
    if no_intent:
        chk.observe("Groups without approved signal intent: no experiment proposed", asset_group_ids=sorted(no_intent))
    blocked = sorted({f"{k[0][1]}:{lid}" for (k, lid), p in perms.items() if p["state"] != "approved"})
    chk.observe("Experiment candidate screening", approved_sources=len(approved), groups_with_candidates=len(groups),
                blocked_list_uses=blocked)
    if not groups:
        return
    chk.review("signal_experiment", {"batch": "authorized_signal_experiments"},
               "Is a narrowly justified signal experiment useful for any of these groups' stated offers, using only "
               "the listed authorized sources?",
               evidence={"groups": groups},
               outcomes={"experiment_proposed": {"severity": "Info", "recommendation":
                                                 "Request-only experiment proposal; owner approves before any change."},
                         "no_proposal": {"severity": None, "recommendation": "No experiment."}},
               guidance="For experiment_proposed give proposal.experiments=[{asset_group_id, source_id and/or list_id, "
                        "hypothesis}] drawn only from each group's candidates. Do not duplicate list-health (061), "
                        "GA4 definition (105) or permission (156) recommendations; no uplift forecast.")


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   unsafe_use_confirmed needs proposal.evidence_ref. experiment_proposed needs proposal.experiments whose
             asset group is in the batch and whose list/source resolves approved and is intent-permitted.
    """
    outcome = decision.get("outcome")
    proposal = decision.get("proposal") or {}
    if outcome == "unsafe_use_confirmed":
        if not _id(proposal.get("evidence_ref")):
            return ["unsafe_use_confirmed needs proposal.evidence_ref pointing at supplied evidence"]
        return []
    if item.condition_key != "signal_experiment" or outcome != "experiment_proposed":
        return []
    exps = proposal.get("experiments")
    if isinstance(proposal.get("asset_group_id"), str) and not exps:
        exps = [proposal]
    if not exps:
        return ["experiment_proposed needs proposal.experiments=[{asset_group_id, source_id|list_id}]"]
    batch = {g["asset_group_id"]: g for g in item.evidence.get("groups", [])}
    intent, _, _ = _intent(ctx)
    defs = {_id(r.get("list_id")): r for r in ctx.rows(DEFINITIONS)} if ctx.table(DEFINITIONS) else {}
    problems = []
    for e in exps:
        gid, lid, src = _id(e.get("asset_group_id")), _id(e.get("list_id")), _id(e.get("source_id"))
        if gid not in batch:
            problems.append(f"asset group {gid or '?'} not in reviewed batch")
            continue
        if not lid and not src:
            problems.append(f"{gid}: proposal needs source_id or list_id")
            continue
        def_src = _id((defs.get(lid) or {}).get("source_id")) if lid else ""
        if lid and def_src and src and def_src != src:
            problems.append(f"{gid}: list {lid} belongs to source {def_src}, not {src}")
            continue
        src = def_src or src
        p = _resolve_permission(ctx, lid, src)
        if p["state"] != "approved":
            problems.append(f"{gid}: {lid or src} permission is {p['state']} ({'; '.join(p['reasons'])})")
        if not _permits(intent.get(gid, []), src)[0]:
            problems.append(f"{gid}: source {src or 'unknown'} not in the group's permitted_source_ids")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
