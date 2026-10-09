"""check.py — skill-115 deterministic placement ledger, view-rate denominators and exclusion governance.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-115-display-youtube-placement-performance-review/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #43 Automatic YouTube Placement Exclusion (Google) — clean-room reimplementation of threshold-screened
         placement exclusion candidates as gated zero_conversion_placement reviews with verify()'d request-only proposals
         index #44 TLD negative placement list (Victor Kaugesaar) — clean-room: profile.placement_tld_rules matches become
         profile_rule_match suitability reviews, never automatic exclusions
         index #45 URL-keyword placement cleaner (lipatovdm) — clean-room: profile.placement_url_keywords matches become
         profile_rule_match suitability reviews, never automatic exclusions
         index #73 PMax Placement Exclusion Suggestions (nilsrooijmans.com) — clean-room: PMax placement rows get rule
         suggestions only (no performance claims), scope limited to evidenced supported controls
         index #101 GDN Placement Analysis (Derek Martin) — clean-room: per-placement and cross-campaign roll-up ledger,
         CPA only with a shared goal set, maturity and min_conversions
rules:   Placement rows are windowed to account.date_range_start..end and deduplicated on the declared grain
         (account/campaign/ad_group/date/placement/format); conflicting duplicates are excluded + partial, never summed.
         Unreported campaign cost is unknown inventory, never zero. Unknown cells stay None (group total unknown).
         Inventory class comes only from placement_type API values WEBSITE | MOBILE_APPLICATION | MOBILE_APP_CATEGORY |
         YOUTUBE_VIDEO | YOUTUBE_CHANNEL; anything else is not compared. App categories need category_source.
         View rate = video_views / stated denominator (denominator_name + denominator_count; eligible_video_impressions
         only when no other denominator is named) or native_view_rate. NEVER clicks/impressions, NEVER placement
         impressions. denominator_name=not_applicable → not applicable. Missing basis or native vs computed differing by
         more than 0.001 → Info incomplete_view_evidence.
         PMax (campaigns.channel_type PERFORMANCE_MAX) placement rows never enter performance screens (ledger CPA,
         app/website, zero-conversion, CTR anomaly); they get profile-rule suggestions only.
         Zero-conversion Warning only via review when ctx.mature True AND ctx.tracking_for_campaign(cid)[0] True AND
         placement cost >= spend_floor(cid) AND conversions known 0; else observation + partial.
         CTR anomaly: profile.placement_ctr_anomaly_multiple (number > 1): placement CTR >= multiple x rest of its
         campaign/format cohort, both sides >= min_impressions; Info only, never fraud; absent → partial, no finding.
         Suitability heuristics are client-supplied only: profile.placement_tld_rules (list of TLDs, e.g. [xyz]) and
         profile.placement_url_keywords (list of lowercase substrings); matches → review (Info at most); absent → skipped.
         Approved restriction = external/placement_policy row with policy_id, placement_or_category_id, approved_by,
         evidence_ref, valid_from <= as_of <= valid_to (open end allowed), campaign_scope all|account|* or explicit ids.
         Materiality for Critical = restricted-placement cost since valid_from >= spend_floor(cid). Deterministic Critical
         only with exact placement match, manifest-complete controls with known enabled flags, controls snapshot on/after
         the last delivery and no enabled exclusion; otherwise provisional Info + review whose Critical outcome needs
         proposal.evidence_ref from item.evidence.evidence_refs. No account-level exclusions is an observation; an
         approved restriction with no enabled control and no observed delivery, or an obsolete all-app shortcut
         control, is Info ("No exclusions" row) only.
         verify(): exclusion proposals need placement, scope_type, scope_id, coverage_at_risk, existing_overlap,
         approval_owner, monitoring_plan; placement must match reviewed delivery rows; campaign/ad_group scope must be
         the reviewed campaign/its delivering ad groups; account scope needs cross_campaign_evidence_ref and is refused
         for zero-conversion performance outcomes; PMax needs evidenced campaign-scope support or account scope; refuse
         deliberately included or already fully excluded placements, obsolete all-app shortcuts and (performance)
         scopes containing conversions.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
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

SKILL = "skill-115-display-youtube-placement-performance-review"
VERSION = "1.0.0"

PD = "custom/placement_daily"
PV = "custom/placement_video_metrics"
PC = "custom/placement_controls"
PP = "external/placement_policy"
_GRAIN = ("account_id", "campaign_id", "ad_group_id", "date", "placement_id", "format")
_METRICS = ("impressions", "clicks", "cost", "conversions", "conversion_value")
_MONEY = ("cost", "conversion_value")
_INVENTORY = {"WEBSITE": "website", "MOBILE_APPLICATION": "app", "MOBILE_APP_CATEGORY": "app",
              "YOUTUBE_VIDEO": "youtube", "YOUTUBE_CHANNEL": "youtube"}
_NOT_APPLICABLE = {"not_applicable", "not applicable", "not_view_based"}
_OBSOLETE_ALL_APP = ("adsenseformobileapps.com", "mobileappsbygoogle")
_ACCOUNT_SCOPES = {"account", "customer"}
_ALL_CAMPAIGNS = {"all", "account", "*"}
_PMAX = {"PERFORMANCE_MAX", "PMAX"}
_RATE_TOLERANCE = 0.001
_GRAIN_LABEL = "(campaign/format grain)"
PC_COLS = ["scope_type", "scope_id", "control_id", "snapshot_at", "placement_or_category_id", "enabled",
           "included_or_excluded", "inherited_from"]
PP_COLS = ["policy_id", "placement_or_category_id", "campaign_scope", "evidence_ref", "approved_by", "valid_from",
           "valid_to"]
_PROPOSAL_OUTCOMES = {("zero_conversion_placement", "irrelevant_zero_conversion"): "performance",
                      ("profile_rule_match", "unsuitable_request_exclusion"): "suitability",
                      ("restricted_live_exposure", "confirmed_material_exposure"): "safety"}
_PROPOSAL_FIELDS = ("placement", "scope_type", "scope_id", "coverage_at_risk", "existing_overlap", "approval_owner",
                    "monitoring_plan")
_PROPOSAL_GUIDE = ("proposal {placement: exact placement_id/URL_or_app_id or provenanced app_category_id from evidence, "
                   "scope_type: ad_group|campaign|account, scope_id, coverage_at_risk, existing_overlap, approval_owner, "
                   "monitoring_plan[, cross_campaign_evidence_ref for account scope]}")


# ---------------------------------------------------------------------------------------------- helpers
def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _inventory(row) -> str:
    t = _s(row.get("placement_type")).upper()
    return _INVENTORY.get(t, "other" if t else "unknown")


def _norm_target(v) -> str:
    s = V.norm_text(v)
    for p in ("https://", "http://"):
        if s.startswith(p):
            s = s[len(p):]
    if s.startswith("www."):
        s = s[4:]
    return s.rstrip("/")


def _host(v) -> str:
    return _norm_target(v).split("/", 1)[0]


def _provenanced(row) -> bool:
    src = _s(row.get("category_source")).lower()
    return bool(src) and src not in _NOT_APPLICABLE and src != "unknown"


def _match(target, row) -> str | None:
    """How a control/policy target relates to a delivery row: exact | ambiguous | category | None.

    Rules:   IDs match literally; website URLs also match case-insensitively without scheme/www and on path
             prefixes; a subdomain relation is only 'ambiguous'. 'category' = equal app_category_id (caller checks
             provenance).
    """
    t = _s(target)
    if not t:
        return None
    best = None
    for col in ("placement_id", "URL_or_app_id"):
        v = _s(row.get(col))
        if not v:
            continue
        if v == t:
            return "exact"
        if _inventory(row) == "website":
            a, b = _norm_target(t), _norm_target(v)
            if a and (a == b or b.startswith(a + "/")):
                return "exact"
            if a and "/" not in a and _host(b).endswith("." + a):
                best = "ambiguous"
    if best:
        return best
    if _s(row.get("app_category_id")) == t:
        return "category"
    return None


def _num(ctx, row, m):
    if m not in row:
        return None
    return ctx.money(row.get(m)) if m in _MONEY else V.num(row.get(m))


class _Agg:
    """Sum of metrics; a metric with any unknown cell is unknown (None), never a partial sum."""

    def __init__(self):
        self.sums = dict.fromkeys(_METRICS, 0.0)
        self.unknown = dict.fromkeys(_METRICS, 0)
        self.rows = 0

    def add(self, ctx, row) -> "_Agg":
        self.rows += 1
        for m in _METRICS:
            v = _num(ctx, row, m)
            if v is None:
                self.unknown[m] += 1
            else:
                self.sums[m] += v
        return self

    def get(self, m):
        return None if self.unknown[m] or not self.rows else self.sums[m]

    def as_dict(self) -> dict:
        d = {m: self.get(m) for m in _METRICS}
        d["rows"] = self.rows
        unknown = {m: n for m, n in self.unknown.items() if n}
        if unknown:
            d["unknown_cells"] = unknown
        return d


def _agg(ctx, rows) -> _Agg:
    a = _Agg()
    for r in rows:
        a.add(ctx, r)
    return a


def _load(ctx, key) -> tuple[list[dict], list[tuple[bool, str]]]:
    """Window rows to the report period and drop duplicate grain rows. Returns (rows, [(is_partial, note)])."""
    t = ctx.table(key)
    if t is None:
        return [], []
    notes: list[tuple[bool, str]] = []
    grain = [c for c in _GRAIN if c in t.columns]
    start, end = ctx.period_start, ctx.period_end
    windowed = "date" in t.columns and start is not None and end is not None
    if "date" not in t.columns:
        notes.append((True, f"{t.filename}: no date column; rows cannot be windowed to the report period"))
    elif not windowed:
        notes.append((True, "report period unknown: rows not windowed"))
    first: dict[tuple, dict] = {}
    conflicts: set = set()
    dropped = outside = undated = 0
    for r in t.rows:
        if windowed:
            d = V.parse_date(r.get("date"))
            if d is None:
                undated += 1
                continue
            if not start <= d <= end:
                outside += 1
                continue
        k = tuple(_s(r.get(c)) for c in grain)
        if k in first:
            if first[k] != r:
                conflicts.add(k)
            else:
                dropped += 1
            continue
        first[k] = r
    if outside:
        notes.append((False, f"{t.filename}: {outside} rows outside {start}..{end} excluded"))
    if undated:
        notes.append((True, f"{t.filename}: {undated} rows with unparseable date excluded"))
    if dropped:
        notes.append((False, f"{t.filename}: {dropped} exact duplicate grain rows dropped"))
    if conflicts:
        notes.append((True, f"{t.filename}: {len(conflicts)} grain keys with conflicting duplicate rows excluded "
                            f"({', '.join('/'.join(k) for k in sorted(conflicts)[:5])})"))
    return [r for k, r in first.items() if k not in conflicts], notes


class _Index:
    """Windowed, deduplicated placement_daily rows grouped by (campaign_id, placement_id)."""

    def __init__(self, ctx):
        self.present = ctx.table(PD) is not None
        self.rows, self.notes = _load(ctx, PD)
        self.by_cp: dict[tuple[str, str], list[dict]] = {}
        orphan = 0
        for r in self.rows:
            cid, pid = _s(r.get("campaign_id")), _s(r.get("placement_id"))
            if not cid or not pid:
                orphan += 1
                continue
            self.by_cp.setdefault((cid, pid), []).append(r)
        if orphan:
            self.notes.append((True, f"{orphan} placement rows without campaign_id/placement_id cannot be joined"))

    def apply(self, check, info: bool = False) -> None:
        for partial, text in self.notes:
            if partial:
                check.partial(text)
            elif info:
                check.observe(text)

    def campaigns_of(self, pid) -> list[str]:
        return sorted({c for c, p in self.by_cp if p == pid})


class _Controls:
    """Parsed placement_controls snapshot. Rules: unknown enabled/mode is unknown coverage, never 'not excluded'."""

    def __init__(self, ctx):
        t = ctx.table(PC)
        self.present = t is not None and not t.missing(PC_COLS)
        self.complete = bool(t is not None and t.complete is True and not t.truncated)
        self.table = t
        self.rows: list[dict] = []
        for r in (t.rows if self.present else []):
            self.rows.append({
                "control_id": _s(r.get("control_id")), "scope_type": _s(r.get("scope_type")).lower(),
                "scope_id": _s(r.get("scope_id")), "target": _s(r.get("placement_or_category_id")),
                "enabled": V.boolean(r.get("enabled")), "mode": _s(r.get("included_or_excluded")).upper(),
                "inherited_from": _s(r.get("inherited_from")), "control_type": _s(r.get("control_type")),
                "supported_subtypes": [x.upper() for x in V.split_list(r.get("supported_subtypes"), (";", "|", ","))],
                "snapshot_at": V.parse_date(r.get("snapshot_at"))})
        self.rows.sort(key=lambda c: (c["scope_type"], c["scope_id"], c["control_id"], c["target"]))

    def snapshot(self):
        """Oldest snapshot_at over rows; for a known-empty table the manifest period_end/exported_at."""
        if not self.present:
            return None
        if self.rows:
            dates = [c["snapshot_at"] for c in self.rows]
            return None if any(d is None for d in dates) else min(dates)
        m = self.table.manifest or {}
        return V.parse_date(m.get("period_end")) or V.parse_date(m.get("exported_at"))

    @staticmethod
    def _applies(ctl, cid, gids) -> str | None:
        st = ctl["scope_type"]
        if st in _ACCOUNT_SCOPES:
            return "full"
        if st == "campaign":
            return "full" if ctl["scope_id"] == cid else None
        if st == "ad_group":
            return "partial" if ctl["scope_id"] in gids else None
        return None

    def cover(self, cid, gids, row) -> dict:
        """covered | partial | unknown | uncovered for one delivery row, plus deliberate includes."""
        if not self.present:
            return {"state": "unknown", "note": "placement_controls not supplied"}
        full, part, unknown, included = [], [], [], []
        for ctl in self.rows:
            m = _match(ctl["target"], row)
            scope = self._applies(ctl, cid, gids) if m else None
            if scope is None:
                continue
            ref = f"{ctl['control_id']} ({ctl['scope_type']}:{ctl['scope_id']}"
            ref += f", inherited from {ctl['inherited_from']})" if ctl["inherited_from"] else ")"
            if ctl["mode"].startswith("INCLU"):
                if ctl["enabled"] is not False:
                    included.append(ref)
                continue
            if not ctl["mode"].startswith("EXCLU") or ctl["enabled"] is None:
                unknown.append(ref)
            elif ctl["enabled"]:
                (full if m == "exact" and scope == "full" else part).append(ref)
        state = "covered" if full else "partial" if part else "unknown" if unknown else "uncovered"
        return {"state": state, "excluded_by": full, "partially_or_ambiguously_by": part, "unknown_state": unknown,
                "included_by": included}

    def supports(self, scope_type, subtype_tokens) -> bool:
        return any(c["scope_type"] == scope_type and set(c["supported_subtypes"]) & subtype_tokens for c in self.rows)


def _campaigns(ctx) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in ctx.rows("campaigns"):
        cid = _s(r.get("id") or r.get("campaign_id"))
        if cid:
            out.setdefault(cid, r)
    return out


def _is_pmax(camps, cid) -> bool | None:
    ch = _s((camps.get(cid) or {}).get("channel_type")).upper()
    return (ch in _PMAX) if ch else None


def _channel_gaps(check, idx, camps) -> None:
    """Campaigns whose channel is unknown cannot be separated from PMax: performance claims are partial."""
    gaps = sorted({cid for cid, _ in idx.by_cp if _is_pmax(camps, cid) is None})
    if gaps:
        check.partial(f"campaigns.channel_type unknown for {gaps[:10]}: PMax rows cannot be separated",
                      ["campaigns:channel_type"])


def _policies(ctx) -> tuple[list[dict], list[dict]]:
    """Split external/placement_policy rows into currently valid approved restrictions and rejected rows."""
    ref = ctx.as_of or ctx.period_end
    valid, invalid = [], []
    for r in sorted(ctx.rows(PP), key=lambda r: (_s(r.get("policy_id")), _s(r.get("placement_or_category_id")))):
        p = {"policy_id": _s(r.get("policy_id")), "target": _s(r.get("placement_or_category_id")),
             "approved_by": _s(r.get("approved_by")), "evidence_ref": _s(r.get("evidence_ref")),
             "valid_from": V.parse_date(r.get("valid_from")), "valid_to": V.parse_date(r.get("valid_to")),
             "suitability_rationale": _s(r.get("suitability_rationale")), "campaign_scope_raw": _s(r.get("campaign_scope"))}
        problems = [f"{k} missing" for k in ("policy_id", "target", "approved_by", "evidence_ref") if not p[k]]
        if p["valid_from"] is None:
            problems.append("valid_from missing/unparseable")
        if _s(r.get("valid_to")) and p["valid_to"] is None:
            problems.append("valid_to unparseable")
        if ref is None:
            problems.append("as-of date unknown: validity undecidable")
        else:
            if p["valid_from"] and p["valid_from"] > ref:
                problems.append(f"not yet valid at {ref}")
            if p["valid_to"] and p["valid_to"] < ref:
                problems.append(f"expired {p['valid_to']} before {ref}")
        raw = p["campaign_scope_raw"]
        if raw.lower() in _ALL_CAMPAIGNS:
            p["campaigns"] = None
        elif raw:
            p["campaigns"] = sorted(V.split_list(raw, (";", "|", ",")))
        else:
            problems.append("campaign_scope missing: applicability unknown")
        (invalid if problems else valid).append({**p, "problems": problems})
    return valid, invalid


def _context(ctx, idx, controls, camps, cid, pid) -> dict:
    """Step-6 facts for one candidate: narrow scopes, coverage at risk, existing overlap, cross-campaign presence."""
    rows = idx.by_cp.get((cid, pid), [])
    gids = sorted({_s(r.get("ad_group_id")) for r in rows if _s(r.get("ad_group_id"))})
    rep = rows[0] if rows else {}
    return {
        "placement_type": rep.get("placement_type"), "URL_or_app_id": rep.get("URL_or_app_id"),
        "app_category_id": rep.get("app_category_id"), "category_source": rep.get("category_source"),
        "network": rep.get("network"), "formats": sorted({_s(r.get("format")) for r in rows}),
        "coverage_at_risk": _agg(ctx, rows).as_dict(),
        "narrow_scopes": [f"ad_group:{g}" for g in gids] + [f"campaign:{cid}"],
        "other_campaigns_with_delivery": [c for c in idx.campaigns_of(pid) if c != cid],
        "existing_overlap": controls.cover(cid, set(gids), rep) if rows else {"state": "unknown"},
        "pmax": _is_pmax(camps, cid), "window": [ctx.period_start, ctx.period_end],
    }


# ---------------------------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run Display/YouTube placement windowing, view-rate, performance, CTR anomaly, suitability and restriction checks.

    Rules:   PMax placements never enter performance screens. Zero-conversion Warning only via review with ctx.mature
             True, tracking True, cost >= spend_floor and known 0 conversions. CTR anomaly and TLD/keyword heuristics
             are Info and need profile settings (absent → skipped). Critical for approved restrictions only with exact
             match, complete controls and no enabled exclusion; otherwise provisional Info + review needing
             proposal.evidence_ref.
    """
    idx = _Index(ctx)
    camps = _campaigns(ctx)
    controls = _Controls(ctx)
    _reconcile(ctx, idx, camps)
    _provenance(ctx, idx)
    _ledger(ctx, idx, camps)
    _view_rate(ctx)
    _viewability(ctx)
    _app_vs_website(ctx, idx, camps)
    _zero_conversion(ctx, idx, controls, camps)
    _ctr_anomaly(ctx, idx, camps)
    _rule_screen(ctx, idx, controls, camps)
    _inheritance(ctx, controls)
    valid, invalid = _policies(ctx) if ctx.table(PP) is not None else ([], [])
    delivered = _exposure(ctx, idx, controls, camps, valid)
    _restriction_coverage(ctx, idx, controls, camps, valid, invalid, delivered)
    _proposal_readiness(ctx, controls)


def _reconcile(ctx, idx, camps) -> None:
    c = ctx.check("cost_reconciliation", "Reconcile placement cost to campaign totals by format and objective",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "format", "objective", "cost"],
                   "campaign_metrics": ["campaign_id", "cost"]})
    if not c.runnable:
        return
    idx.apply(c, info=True)
    cm = ctx.table("campaign_metrics")
    dated = "date" in cm.columns
    s, e = ctx.period_start, ctx.period_end
    totals: dict[str, list] = {}
    for r in cm.rows:
        if dated:
            d = V.parse_date(r.get("date"))
            if d is None or (s and e and not s <= d <= e):
                continue
        elif "date_range_start" in cm.columns and (V.parse_date(r.get("date_range_start")) != s
                                                   or V.parse_date(r.get("date_range_end")) != e):
            c.partial(f"campaign_metrics row for {r.get('campaign_id')} covers {r.get('date_range_start')}.."
                      f"{r.get('date_range_end')}, not {s}..{e}")
            totals.setdefault(_s(r.get("campaign_id")), []).append(None)
            continue
        totals.setdefault(_s(r.get("campaign_id")), []).append(ctx.money(r.get("cost")))
    by_c: dict[str, list[dict]] = {}
    for r in idx.rows:
        by_c.setdefault(_s(r.get("campaign_id")), []).append(r)
    for cid in sorted(by_c):
        rows = by_c[cid]
        pmax = _is_pmax(camps, cid)
        pc = _agg(ctx, rows).get("cost")
        costs = totals.get(cid)
        total = None
        if costs is None:
            c.partial(f"campaign {cid}: no campaign_metrics row; placement share unknown")
        elif len(costs) > 1 and not dated:
            c.partial(f"campaign {cid}: {len(costs)} undated campaign_metrics rows; segment totals ambiguous")
        elif any(x is None for x in costs):
            c.partial(f"campaign {cid}: campaign cost unknown for the window")
        else:
            total = sum(costs)
        if pc is None:
            c.partial(f"campaign {cid}: placement rows with unknown cost" +
                      ("; PMax placement reporting lacks cost (partial coverage)" if pmax else ""))
        share = V.ratio(pc, total)
        unreported = total - pc if pc is not None and total is not None and total >= pc else None
        if pc is not None and total is not None and pc > total + 0.01:
            c.partial(f"campaign {cid}: placement cost {pc:.2f} exceeds campaign cost {total:.2f}; window/grain "
                      "mismatch, share invalid")
            share = None
        by_fmt: dict[str, list] = {}
        by_obj: dict[str, list] = {}
        for r in rows:
            by_fmt.setdefault(_s(r.get("format")) or "(unknown)", []).append(r)
            by_obj.setdefault(_s(r.get("objective")) or "(unknown)", []).append(r)
        c.observe(f"Campaign {cid}: placement cost reconciled to campaign total", campaign_id=cid, placement_cost=pc,
                  campaign_cost=total, reported_share=share, unreported_cost=unreported,
                  unreported_meaning="unknown inventory (suppressed/unreported), not zero", pmax=pmax,
                  cost_by_format={k: _agg(ctx, v).get("cost") for k, v in sorted(by_fmt.items())},
                  cost_by_objective={k: _agg(ctx, v).get("cost") for k, v in sorted(by_obj.items())},
                  objectives_kept_separate=len(by_obj) > 1, window=[s, e],
                  days_with_rows=len({_s(r.get("date")) for r in rows}))
    for cid in sorted(set(totals) - set(by_c)):
        c.observe(f"Campaign {cid}: no placement rows in the window (inventory unreported, not zero)", campaign_id=cid)


def _provenance(ctx, idx) -> None:
    c = ctx.check("category_provenance", "App category provenance and inventory classes",
                  {PD: ["campaign_id", "placement_id", "placement_type", "app_category_id", "category_source"]})
    if not c.runnable:
        return
    idx.apply(c)
    classes: dict[str, int] = {}
    sources: dict[str, int] = {}
    unproven, uncategorized = set(), set()
    for (cid, pid), rows in sorted(idx.by_cp.items()):
        r = rows[0]
        inv = _inventory(r)
        classes[inv] = classes.get(inv, 0) + 1
        if inv != "app":
            continue
        cat = _s(r.get("app_category_id"))
        if not cat:
            uncategorized.add(pid)
        elif _provenanced(r):
            src = _s(r.get("category_source"))
            sources[src] = sources.get(src, 0) + 1
        else:
            unproven.add(f"{pid}:{cat}")
    if unproven:
        c.partial(f"{len(unproven)} app placements carry app_category_id without category_source; excluded from "
                  "category claims")
    c.observe("Placement inventory classes and app category provenance", inventory_classes=classes,
              category_sources=sources, unprovenanced_categories=sorted(unproven),
              uncategorized_apps=sorted(uncategorized),
              note="Inventory class from placement_type API values only; unclassified types are not compared")


def _ledger(ctx, idx, camps) -> None:
    c = ctx.check("placement_ledger", "Placement ledger: spend, outcomes, CTR and cross-campaign roll-up",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "format", "impressions", "clicks", "cost",
                        "conversions"]})
    if not c.runnable:
        return
    idx.apply(c)
    mi, mc = ctx.params.get("min_impressions"), ctx.params.get("min_conversions")
    mature = ctx.mature is True
    if not mature:
        c.partial(f"CPA/ROAS withheld: maturity={ctx.mature} ({ctx.maturity_note})")
    _channel_gaps(c, idx, camps)

    def gated(a, pmax):
        conv, cost, value = a.get("conversions"), a.get("cost"), a.get("conversion_value")
        if pmax:
            return None, None, "PMax placement metrics are not attributable: no performance claims"
        if not mature:
            return None, None, "immature window"
        if conv is None or cost is None or mc.value is None or conv < mc.value:
            return None, None, f"conversions {conv} < min_conversions {mc.value}"
        return V.ratio(cost, conv), (V.ratio(value, cost) if value is not None else None), "ok"

    groups: dict[tuple[str, str], dict[str, list]] = {}
    for (cid, pid), rows in idx.by_cp.items():
        for r in rows:
            groups.setdefault((cid, _s(r.get("format")) or "(unknown)"), {}).setdefault(pid, []).append(r)
    for (cid, fmt) in sorted(groups):
        pmax = _is_pmax(camps, cid)
        out = []
        for pid, rows in groups[(cid, fmt)].items():
            a = _agg(ctx, rows)
            imp, clk = a.get("impressions"), a.get("clicks")
            cpa, roas, gate = gated(a, pmax)
            out.append({"placement_id": pid, "placement_type": rows[0].get("placement_type"),
                        "URL_or_app_id": rows[0].get("URL_or_app_id"), **a.as_dict(),
                        "ctr": V.ratio(clk, imp), "ctr_definition": "clicks / impressions",
                        "ctr_sample_ok": imp is not None and mi.value is not None and imp >= mi.value,
                        "cpa": cpa, "roas": roas, "cpa_gate": gate})
        out.sort(key=lambda d: (-(d["cost"] or 0), d["placement_id"]))
        c.observe(f"Placement ledger campaign {cid} format {fmt}", campaign_id=cid, format=fmt, pmax=pmax,
                  placements=out, min_impressions=mi.value, min_conversions=mc.value, mature=ctx.mature)
    for pid in sorted({p for _, p in idx.by_cp}):
        cids = idx.campaigns_of(pid)
        if len(cids) < 2:
            continue
        rows = [r for cid in cids for r in idx.by_cp[(cid, pid)]]
        a = _agg(ctx, rows)
        goal_sets = {tuple(sorted(ctx.goal_ids(cid))) for cid in cids}
        same_goal = len(goal_sets) == 1 and () not in goal_sets
        any_pmax = any(_is_pmax(camps, cid) for cid in cids)
        cpa, roas, gate = gated(a, any_pmax)
        if not same_goal:
            cpa, roas, gate = None, None, "campaigns do not share one declared goal set: CPA not pooled"
        c.observe(f"Cross-campaign placement roll-up {pid}", placement_id=pid, campaigns=cids, **a.as_dict(),
                  ctr=V.ratio(a.get("clicks"), a.get("impressions")), cpa=cpa, roas=roas, cpa_gate=gate)


def _view_rate(ctx) -> None:
    c = ctx.check("video_view_rate", "Video view rate on the stated format denominator (never CTR)",
                  {PV: ["campaign_id", "format"]})
    if not c.runnable:
        return
    cols = set(ctx.table(PV).columns)
    paths = ({"video_views", "denominator_name", "denominator_count"}, {"video_views", "eligible_video_impressions"},
             {"native_view_rate"})
    if not any(p <= cols for p in paths):
        c.skip("no view-rate basis: need video_views+denominator_name+denominator_count, "
               "video_views+eligible_video_impressions or native_view_rate",
               [f"{PV}:{x}" for x in sorted(set().union(*paths) - cols)])
        return
    rows, notes = _load(ctx, PV)
    for partial, text in notes:
        if partial:
            c.partial(text)
        else:
            c.observe(text)
    mi = ctx.params.get("min_impressions")
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (_s(r.get("campaign_id")), _s(r.get("format")) or "(unknown)", _s(r.get("placement_id")) or _GRAIN_LABEL)
        g = groups.setdefault(key, {"bases": {}, "native": [], "issues": [], "na": 0, "unstated": 0, "defs": set()})
        if _s(r.get("measurement_definition")):
            g["defs"].add(_s(r.get("measurement_definition")))
        views = V.num(r.get("video_views"))
        dname = _s(r.get("denominator_name"))
        dcount, elig = V.num(r.get("denominator_count")), V.num(r.get("eligible_video_impressions"))
        native = ctx.rate(r.get("native_view_rate"))
        day = _s(r.get("date")) or "row"
        if dname.lower() in _NOT_APPLICABLE:
            g["na"] += 1
            continue
        if views is None and native is None and not dname and dcount is None and elig is None:
            g["unstated"] += 1
            continue
        basis = None
        if views is not None and dname and dcount is not None:
            basis = (dname, dcount)
        elif views is not None and elig is not None and dname in ("", "eligible_video_impressions"):
            basis = ("eligible_video_impressions", elig)
        if basis is not None:
            if basis[1] <= 0 or views > basis[1]:
                g["issues"].append(f"{day}: {views:g} views on {basis[0]} {basis[1]:g}: view rate undefined/invalid")
                continue
            computed = views / basis[1]
            consistent = None if native is None else abs(computed - native) <= _RATE_TOLERANCE
            if consistent is False:
                g["issues"].append(f"{day}: native_view_rate {native:g} differs from {views:g}/{basis[1]:g} "
                                   f"{basis[0]} = {computed:.4f}: denominator basis inconsistent")
            b = g["bases"].setdefault(basis[0], [0.0, 0.0, 0, 0])
            b[0] += views
            b[1] += basis[1]
            b[2] += 1
            b[3] += consistent is True
        elif native is not None:
            g["native"].append({"date": day, "native_view_rate": native, "denominator_name": dname or None})
        else:
            g["issues"].append(f"{day}: incomplete (video_views={views}, denominator_name={dname or None}, "
                               f"denominator_count={dcount}, eligible_video_impressions={elig})")
    na = unstated = 0
    for key in sorted(groups):
        cid, fmt, pid = key
        g = groups[key]
        na += g["na"]
        unstated += g["unstated"]
        ent = {"campaign_id": cid, "format": fmt, "placement_id": pid}
        for name, (views, denom, n, native_ok) in sorted(g["bases"].items()):
            c.observe(f"Video view rate {cid}/{fmt}/{pid}: {views:g} video_views / {denom:g} {name}", **ent,
                      video_views=views, denominator_name=name, denominator_count=denom,
                      view_rate=V.ratio(views, denom), rows=n, native_view_rate_consistent_rows=native_ok,
                      denominator_sample_ok=mi.value is not None and denom >= mi.value,
                      measurement_definition=sorted(g["defs"]))
        if len(g["bases"]) > 1:
            c.observe(f"{cid}/{fmt}/{pid}: several denominators reported separately, never pooled", **ent,
                      denominators=sorted(g["bases"]))
        if len(g["native"]) == 1:
            c.observe(f"Native view rate {cid}/{fmt}/{pid}", **ent, **g["native"][0],
                      measurement_definition=sorted(g["defs"]))
        elif g["native"]:
            c.observe(f"{cid}/{fmt}/{pid}: {len(g['native'])} native-only daily rates cannot be pooled without a "
                      "denominator", **ent, native_rates=g["native"])
        if g["issues"]:
            c.finding("incomplete_view_evidence", "Info", ent,
                      f"Incomplete view evidence for placement {pid} ({fmt}) in campaign {cid}: "
                      f"{len(g['issues'])} rows lack a usable or consistent format denominator",
                      evidence={"issues": g["issues"], "measurement_definition": sorted(g["defs"]),
                                "window": [ctx.period_start, ctx.period_end]},
                      calculation={"view_rate": "video_views / stated denominator_count (or eligible_video_impressions)"
                                                " or native_view_rate; CTR is never a view rate"},
                      recommendation="Supply the documented format-specific denominator (denominator_name + "
                                     "denominator_count) or the native view rate for the same window.",
                      uncertainty="View performance for this placement is unknown, not poor.")
    if na:
        c.observe("Rows of non-view-based formats: view rate not applicable", rows=na)
    if unstated:
        c.partial(f"{unstated} rows state neither view evidence nor denominator_name=not_applicable: view basis "
                  "undetermined")


def _viewability(ctx) -> None:
    c = ctx.check("viewability", "Active View viewability = viewable / measurable impressions",
                  {PV: ["campaign_id", "format", "measurable_impressions", "viewable_impressions"]})
    if not c.runnable:
        return
    rows, notes = _load(ctx, PV)
    for partial, text in notes:
        if partial:
            c.partial(text)
    mi = ctx.params.get("min_impressions")
    groups: dict[tuple, list] = {}
    unknown = invalid = 0
    for r in rows:
        key = (_s(r.get("campaign_id")), _s(r.get("format")) or "(unknown)", _s(r.get("placement_id")) or _GRAIN_LABEL)
        m, v = V.num(r.get("measurable_impressions")), V.num(r.get("viewable_impressions"))
        if m is None or v is None:
            unknown += 1
            continue
        if v > m:
            invalid += 1
            continue
        g = groups.setdefault(key, [0.0, 0.0, 0])
        g[0] += v
        g[1] += m
        g[2] += 1
    for (cid, fmt, pid), (v, m, n) in sorted(groups.items()):
        c.observe(f"Viewability {cid}/{fmt}/{pid}: {v:g} viewable / {m:g} measurable", campaign_id=cid, format=fmt,
                  placement_id=pid, viewable_impressions=v, measurable_impressions=m, viewability=V.ratio(v, m),
                  rows=n, sample_ok=mi.value is not None and m >= mi.value)
    if unknown:
        c.partial(f"{unknown} rows lack measurable/viewable impressions: viewability unknown, not zero")
    if invalid:
        c.partial(f"{invalid} rows report viewable > measurable impressions: excluded as invalid")


def _app_vs_website(ctx, idx, camps) -> None:
    c = ctx.check("app_vs_website", "App vs website cohorts within campaign, format and objective",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "format", "objective", "placement_type",
                        "clicks", "cost", "conversions"]})
    if not c.runnable:
        return
    idx.apply(c)
    mature = ctx.mature is True
    if not mature:
        c.partial(f"CPA/ROAS comparison disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    mcv, mcl = ctx.params.get("min_conversions"), ctx.params.get("min_clicks")
    cohorts: dict[tuple, dict[str, list]] = {}
    pmax_skipped = set()
    _channel_gaps(c, idx, camps)
    for (cid, pid), rows in idx.by_cp.items():
        if _is_pmax(camps, cid):
            pmax_skipped.add(cid)
            continue
        for r in rows:
            side = _inventory(r)
            if side in ("app", "website"):
                key = (cid, _s(r.get("format")) or "(unknown)", _s(r.get("objective")) or "(unknown)")
                cohorts.setdefault(key, {"app": [], "website": []})[side].append(r)
    compared = one_sided = 0
    for key in sorted(cohorts):
        sides = cohorts[key]
        if not sides["app"] or not sides["website"]:
            one_sided += 1
            continue
        out = {}
        for name, rows in sides.items():
            a = _agg(ctx, rows)
            conv, cost, clicks, value = a.get("conversions"), a.get("cost"), a.get("clicks"), a.get("conversion_value")
            ok = mature and conv is not None and cost is not None and mcv.value is not None and conv >= mcv.value
            out[name] = {**a.as_dict(), "cpa": V.ratio(cost, conv) if ok else None,
                         "roas": V.ratio(value, cost) if ok and value is not None else None,
                         "cvr_supporting_only": V.ratio(conv, clicks) if mature and clicks is not None
                         and mcl.value is not None and clicks >= mcl.value else None,
                         "cpa_gate": "ok" if ok else f"conversions {conv} vs min_conversions {mcv.value}, mature={ctx.mature}"}
        cats = {}
        for r in sides["app"]:
            if _s(r.get("app_category_id")):
                cats[_s(r.get("app_category_id"))] = _s(r.get("category_source")) if _provenanced(r) else "unprovenanced"
        comparable = out["app"]["cpa"] is not None and out["website"]["cpa"] is not None
        compared += comparable
        cid, fmt, obj = key
        c.observe(f"App vs website {cid}/{fmt}/{obj}", campaign_id=cid, format=fmt, objective=obj,
                  goal_ids=ctx.goal_ids(cid), app=out["app"], website=out["website"], comparable=comparable,
                  app_to_website_cpa=V.ratio(out["app"]["cpa"], out["website"]["cpa"]) if comparable else None,
                  app_categories=cats, note="CPA/ROAS need min_conversions on both sides; CVR is supporting only; "
                                            "games/children categories do not prove waste")
    if pmax_skipped:
        c.partial(f"PMax campaigns {sorted(pmax_skipped)} excluded: placement metrics not attributable")
    c.observe("App vs website comparison totals", comparable_cohorts=compared, one_sided_cohorts=one_sided,
              min_conversions=mcv.value, min_clicks=mcl.value)


def _zero_conversion(ctx, idx, controls, camps) -> None:
    c = ctx.check("zero_conversion_screen", "Mature zero-conversion placements at spend_floor",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "placement_type", "format", "cost",
                        "conversions"]})
    if not c.runnable:
        return
    idx.apply(c)
    if ctx.mature is not True:
        c.partial(f"zero-conversion Warning path disabled: maturity={ctx.mature} ({ctx.maturity_note})")
    blocked, unknown_conv, unresolved, tracking_gaps = [], [], set(), {}
    sub_floor = pmax = unknown_cost = 0
    _channel_gaps(c, idx, camps)
    for (cid, pid) in sorted(idx.by_cp):
        if _is_pmax(camps, cid):
            pmax += 1
            continue
        a = _agg(ctx, idx.by_cp[(cid, pid)])
        conv, cost = a.get("conversions"), a.get("cost")
        if conv is None:
            unknown_conv.append(f"{cid}/{pid}")
            continue
        if conv > 0:
            continue
        if cost is None:
            unknown_cost += 1
            continue
        if cost == 0:
            continue
        floor = ctx.params.get("spend_floor", cid)
        if floor.value is None:
            unresolved.add(f"{cid}: {floor.reason}")
            continue
        if cost < floor.value:
            sub_floor += 1
            continue
        tracking_ok, tnote = ctx.tracking_for_campaign(cid)
        entity = {"campaign_id": cid, "placement_id": pid}
        ev = {"cost": cost, "conversions": conv, "clicks": a.get("clicks"), "impressions": a.get("impressions"),
              "spend_floor": floor.value, "spend_floor_source": floor.source, "maturity": ctx.maturity_note,
              "tracking": tnote, "goal_ids": ctx.goal_ids(cid),
              "profile_objectives": ctx.profile.get("objectives"),
              **_context(ctx, idx, controls, camps, cid, pid)}
        if ctx.mature is not True or tracking_ok is not True:
            if tracking_ok is not True:
                tracking_gaps[cid] = tnote
            blocked.append({"campaign_id": cid, "placement_id": pid, "cost": cost, "tracking": tracking_ok,
                            "mature": ctx.mature})
            continue
        prov = c.finding("zero_conversion_placement", "Info", entity,
                         f"Placement {pid} spent {cost:.2f} {ctx.currency} with 0 conversions in campaign {cid} "
                         f"(spend_floor {floor.value:g}, mature window, tracking evidenced)",
                         evidence=ev, calculation={"cost": cost, "conversions": conv, "spend_floor": floor.value},
                         recommendation="Review relevance and suitability before any exclusion request; historical "
                                        "cost is exposure, not recoverable savings.",
                         uncertainty="Zero conversions can reflect view-through/assisted value, lag or long cycles.")
        c.review("zero_conversion_placement", entity,
                 f"After context review, is placement {pid} irrelevant to campaign {cid}'s goals so the mature "
                 f"zero-conversion spend of {cost:.2f} {ctx.currency} warrants a narrow exclusion request?",
                 evidence=ev, provisional=prov,
                 outcomes={"irrelevant_zero_conversion": {"severity": "Warning", "recommendation":
                               "Request the verified narrow exclusion with owner and monitoring; exposure is not savings."},
                           "relevant_keep": {"severity": None, "recommendation": "Keep; placement serves the goal."},
                           "uncertain": {"severity": "Info", "recommendation": "Ask the owner; keep monitoring."}},
                 guidance="Judge relevance from campaign goals, objectives and placement content only. Games or "
                          "children categories do not prove waste; CTR is not fraud (billing concerns → skill-118). "
                          "For irrelevant_zero_conversion supply " + _PROPOSAL_GUIDE +
                          " with ad_group or campaign scope only.")
    if blocked:
        c.observe("Zero-conversion placements >= spend_floor with the Warning path disabled", placements=blocked)
    for cid, note in sorted(tracking_gaps.items()):
        c.partial(f"zero-conversion Warning path disabled: {note}")
    for u in sorted(unresolved):
        c.partial(f"spend_floor unresolved for campaign {u}")
    if unknown_conv:
        c.partial(f"{len(unknown_conv)} placements with unknown conversions not screened (unknown is not zero)")
    if unknown_cost:
        c.partial(f"{unknown_cost} zero-conversion placements with unknown cost not screened")
    if pmax:
        c.partial(f"{pmax} PMax placements not screened: placement performance not attributable")
    c.observe("Zero-conversion screening totals", reviews=sum(1 for x in ctx.result.reviews
                                                             if x.condition_key == "zero_conversion_placement"),
              blocked=len(blocked), sub_floor_zero_conversion=sub_floor)


def _ctr_anomaly(ctx, idx, camps) -> None:
    c = ctx.check("ctr_anomaly_screen", "CTR anomaly screen (Info only; not fraud)",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "format", "impressions", "clicks"]})
    if not c.runnable:
        return
    idx.apply(c)
    mult = V.num(ctx.profile.get("placement_ctr_anomaly_multiple"))
    if mult is None or mult <= 1:
        c.partial("CTR anomaly tolerance not declared: profile.placement_ctr_anomaly_multiple (> 1) required; "
                  "descriptive baselines only", ["profile:placement_ctr_anomaly_multiple"])
        mult = None
    mi = ctx.params.get("min_impressions")
    cohorts: dict[tuple, dict[str, _Agg]] = {}
    for (cid, pid), rows in idx.by_cp.items():
        if _is_pmax(camps, cid):
            continue
        for r in rows:
            cohorts.setdefault((cid, _s(r.get("format")) or "(unknown)"), {}).setdefault(pid, _Agg()).add(ctx, r)
    unknown = 0
    for (cid, fmt) in sorted(cohorts):
        members = cohorts[(cid, fmt)]
        if any(a.get("impressions") is None or a.get("clicks") is None for a in members.values()):
            unknown += 1
            continue
        ti = sum(a.get("impressions") for a in members.values())
        tc = sum(a.get("clicks") for a in members.values())
        c.observe(f"CTR baseline {cid}/{fmt}", campaign_id=cid, format=fmt, impressions=ti, clicks=tc,
                  ctr=V.ratio(tc, ti), placements=len(members), multiple=mult)
        if mult is None or mi.value is None:
            continue
        for pid in sorted(members):
            pi, pc = members[pid].get("impressions"), members[pid].get("clicks")
            ri, rc = ti - pi, tc - pc
            p_ctr, r_ctr = V.ratio(pc, pi), V.ratio(rc, ri)
            if pi < mi.value or ri < mi.value or not r_ctr or p_ctr is None or p_ctr < mult * r_ctr:
                continue
            c.finding("ctr_anomaly_alone", "Info", {"campaign_id": cid, "format": fmt, "placement_id": pid},
                      f"Placement {pid} CTR {p_ctr:.4f} is >= {mult:g}x the rest of {cid}/{fmt} ({r_ctr:.4f})",
                      evidence={"placement_clicks": pc, "placement_impressions": pi, "rest_clicks": rc,
                                "rest_impressions": ri, "multiple": mult,
                                "multiple_source": "profile.placement_ctr_anomaly_multiple",
                                "min_impressions": mi.value, "window": [ctx.period_start, ctx.period_end]},
                      calculation={"placement_ctr": p_ctr, "rest_ctr": r_ctr},
                      recommendation="Check placement content and click quality; route billing-linked invalid "
                                     "traffic concerns to skill-118. Do not exclude on CTR alone.",
                      uncertainty="A CTR anomaly alone is not evidence of fraud or waste.")
    if unknown:
        c.partial(f"{unknown} campaign/format cohorts with unknown impressions/clicks not screened")


def _rule_list(v) -> list[str]:
    items = v if isinstance(v, list) else V.split_list(v, (";", "|", ","))
    return sorted({V.norm_text(x).lstrip(".") for x in items if V.norm_text(x).lstrip(".")})


def _rule_screen(ctx, idx, controls, camps) -> None:
    c = ctx.check("profile_rule_screen", "Client-declared TLD / URL-keyword suitability screens (incl. PMax)",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "placement_type", "URL_or_app_id",
                        "impressions"]})
    tlds = _rule_list(ctx.profile.get("placement_tld_rules"))
    kws = _rule_list(ctx.profile.get("placement_url_keywords"))
    if c.runnable and not tlds and not kws:
        c.skip("no client suitability rules declared", ["profile:placement_tld_rules", "profile:placement_url_keywords"])
    if not c.runnable:
        return
    idx.apply(c)
    matches = excluded = pmax_matches = 0
    for (cid, pid) in sorted(idx.by_cp):
        rows = idx.by_cp[(cid, pid)]
        r = rows[0]
        url = _s(r.get("URL_or_app_id"))
        hits = []
        if _inventory(r) == "website":
            host = _host(url or pid)
            hits += [f"tld:{t}" for t in tlds if host.endswith("." + t)]
        text = f"{V.norm_text(url)} {V.norm_text(pid)}"
        hits += [f"url_keyword:{k}" for k in kws if k in text]
        if not hits:
            continue
        matches += 1
        ctxt = _context(ctx, idx, controls, camps, cid, pid)
        if ctxt["existing_overlap"].get("state") == "covered":
            excluded += 1
            c.observe(f"Rule match {cid}/{pid} already fully excluded", campaign_id=cid, placement_id=pid,
                      rule_hits=hits, overlap=ctxt["existing_overlap"])
            continue
        pmax = ctxt["pmax"]
        pmax_matches += bool(pmax)
        if pmax:
            ctxt["coverage_at_risk"] = {"impressions": ctxt["coverage_at_risk"].get("impressions"),
                                        "note": "PMax placement rows: no performance claims"}
        ev = {"rule_hits": hits, "rule_source": "profile.placement_tld_rules / profile.placement_url_keywords",
              **ctxt}
        c.review("profile_rule_match", {"campaign_id": cid, "placement_id": pid},
                 f"Placement {pid} ({url or 'no URL'}) in campaign {cid} matches client rules {hits}. Is it "
                 "unsuitable for this campaign, so a narrow exclusion request is warranted?",
                 evidence=ev,
                 outcomes={"unsuitable_request_exclusion": {"severity": "Info", "recommendation":
                               "Request the verified narrow exclusion; rule hits are heuristics, not proof."},
                           "suitable_keep": {"severity": None, "recommendation": "Keep; rule hit is a false positive."},
                           "uncertain": {"severity": "Info", "recommendation": "Ask the owner to review the content."}},
                 guidance="Rule lists are client heuristics; judge actual content against profile objectives. "
                          "PMax: suggest only supported controls (account scope with cross_campaign_evidence_ref "
                          "unless placement_controls evidences campaign-level PMax support). For "
                          "unsuitable_request_exclusion supply " + _PROPOSAL_GUIDE + ".")
    c.observe("Client rule screen totals", tld_rules=tlds, url_keywords=kws, matches=matches,
              already_excluded=excluded, pmax_matches=pmax_matches)


def _inheritance(ctx, controls) -> None:
    c = ctx.check("exclusion_inheritance", "Account/campaign/list exclusion inheritance matrix", {PC: PC_COLS})
    if not c.runnable:
        return
    matrix: dict[str, int] = {}
    inherited = unknown = 0
    lists = set()
    for ctl in controls.rows:
        k = f"{ctl['scope_type'] or '(unknown)'}|{ctl['mode'] or '(unknown)'}|enabled={ctl['enabled']}"
        matrix[k] = matrix.get(k, 0) + 1
        inherited += bool(ctl["inherited_from"])
        unknown += ctl["enabled"] is None or not ctl["mode"]
        if ctl["scope_type"] not in _ACCOUNT_SCOPES | {"campaign", "ad_group"}:
            lists.add(f"{ctl['scope_type']}:{ctl['scope_id']}")
        if any(tok in _norm_target(ctl["target"]) for tok in _OBSOLETE_ALL_APP) and ctl["mode"].startswith("EXCLU"):
            c.finding("obsolete_all_app_shortcut", "Info",
                      {"control_id": ctl["control_id"], "scope_type": ctl["scope_type"], "scope_id": ctl["scope_id"]},
                      f"Control {ctl['control_id']} relies on the obsolete all-app domain shortcut "
                      f"'{ctl['target']}'; it does not provide documented app exclusion coverage",
                      evidence={"control": {k: ctl[k] for k in ("target", "enabled", "mode", "inherited_from",
                                                                  "control_type")}},
                      recommendation="If apps must be restricted, request documented app-ID or app-category controls "
                                     "at the supported scope; do not rely on this entry.",
                      uncertainty="Actual app delivery depends on current platform controls; see placement report.")
    account_excl = sum(1 for x in controls.rows if x["scope_type"] in _ACCOUNT_SCOPES and x["mode"].startswith("EXCLU")
                       and x["enabled"] is True)
    if unknown:
        c.partial(f"{unknown} controls with unknown enabled/included_or_excluded state: coverage unknown, not absent")
    if lists:
        c.partial(f"list-level controls without campaign/account application rows: {sorted(lists)}")
    c.observe("Exclusion inheritance matrix", matrix=matrix, inherited_rows=inherited,
              account_level_exclusions=account_excl, controls=len(controls.rows), snapshot=controls.snapshot())
    if account_excl == 0:
        c.observe("No account-level exclusions: not a defect (restrictions are judged against approved policy)",
                  manifest_complete=controls.complete)


def _scope_campaigns(policy, idx, camps) -> list[str]:
    if policy["campaigns"] is None:
        return sorted(set(camps) | {c for c, _ in idx.by_cp})
    return policy["campaigns"]


def _exposure(ctx, idx, controls, camps, valid) -> set:
    """Returns {(policy_id, campaign_id)} pairs with observed delivery on restricted placements."""
    c = ctx.check("restricted_exposure", "Live delivery contrary to an approved suitability restriction",
                  {PD: ["campaign_id", "ad_group_id", "date", "placement_id", "URL_or_app_id", "impressions", "cost"],
                   PC: PC_COLS, PP: PP_COLS})
    delivered: set = set()
    if not c.runnable:
        return delivered
    idx.apply(c)
    snap = controls.snapshot()
    for pol in valid:
        scope = set(_scope_campaigns(pol, idx, camps))
        for (cid, pid) in sorted(idx.by_cp):
            if cid not in scope:
                continue
            kinds, rows = set(), []
            for r in idx.by_cp[(cid, pid)]:
                d = V.parse_date(r.get("date"))
                if d is None or d < pol["valid_from"] or (pol["valid_to"] and d > pol["valid_to"]):
                    continue
                k = _match(pol["target"], r)
                if k == "category" and not _provenanced(r):
                    k = "category_unprovenanced"
                if k:
                    kinds.add(k)
                    rows.append(r)
            if not rows:
                continue
            a = _agg(ctx, rows)
            imp, cost = a.get("impressions"), a.get("cost")
            if not (imp or cost) and imp is not None and cost is not None:
                continue
            delivered.add((pol["policy_id"], cid))
            gids = {_s(r.get("ad_group_id")) for r in rows}
            cover = controls.cover(cid, gids, rows[0])
            entity = {"campaign_id": cid, "placement_id": pid, "policy_id": pol["policy_id"]}
            last = max(V.parse_date(r.get("date")) for r in rows)
            floor = ctx.params.get("spend_floor", cid)
            refs = sorted({pol["policy_id"], pol["evidence_ref"], f"placement_daily:{cid}:{pid}"}
                          | {x.split(" ", 1)[0] for k in ("excluded_by", "partially_or_ambiguously_by", "unknown_state")
                             for x in cover.get(k, [])})
            ev = {"policy": {k: pol[k] for k in ("policy_id", "target", "approved_by", "evidence_ref", "valid_from",
                                                 "valid_to", "suitability_rationale", "campaign_scope_raw")},
                  "match_kinds": sorted(kinds), "delivery_since_valid_from": a.as_dict(),
                  "first_date": min(V.parse_date(r.get("date")) for r in rows), "last_date": last,
                  "controls_snapshot": snap, "controls_manifest_complete": controls.complete, "coverage": cover,
                  "spend_floor": floor.value, "spend_floor_source": floor.source or floor.reason,
                  "materiality_rule": "cost since valid_from >= spend_floor(campaign)", "evidence_refs": refs,
                  **{k: v for k, v in _context(ctx, idx, controls, camps, cid, pid).items()
                     if k in ("narrow_scopes", "other_campaigns_with_delivery", "placement_type", "URL_or_app_id",
                              "pmax")}}
            if cover["state"] == "covered":
                c.observe(f"Restricted placement {pid} in {cid} delivered but is now fully excluded "
                          "(exposure predates or bypassed the control)", **entity, coverage=cover, last_date=last,
                          delivery=a.as_dict())
                continue
            blockers = []
            if kinds != {"exact"}:
                blockers.append(f"match not exact placement-level: {sorted(kinds)}")
            if cover["state"] != "uncovered":
                blockers.append(f"control coverage {cover['state']}")
            if not controls.complete:
                blockers.append("placement_controls not manifest-complete")
            if snap is None or snap < last:
                blockers.append(f"controls snapshot {snap} not on/after last delivery {last}")
            if cost is None:
                blockers.append("delivery cost unknown")
            if floor.value is None:
                blockers.append(f"spend_floor unresolved: {floor.reason}")
            elif cost is not None and cost < floor.value:
                blockers.append(f"cost {cost:.2f} below materiality spend_floor {floor.value:g}")
            ev["deterministic_blockers"] = blockers
            summary = (f"Placement {pid} delivered in campaign {cid} ({imp} impressions, cost {cost}) contrary to "
                       f"approved restriction {pol['policy_id']} with no enabled exclusion")
            if not blockers:
                c.finding("restricted_live_exposure", "Critical", entity, summary + " (material, live)", evidence=ev,
                          calculation={"cost_since_valid_from": cost, "spend_floor": floor.value},
                          recommendation="Request an exclusion at the policy scope with the approval owner; verify "
                                         "delivery stops in the next placement report. Exposure is not savings.",
                          uncertainty="Content suitability meaning comes from the approved policy, not this script.")
                continue
            prov = c.finding("restricted_live_exposure", "Info", entity, summary + " (materiality/liveness unconfirmed)",
                             evidence=ev, recommendation="Confirm coverage and materiality before escalating.",
                             uncertainty="; ".join(blockers))
            c.review("restricted_live_exposure", entity,
                     f"Is the delivery of {pid} in campaign {cid} a confirmed, live and material exposure contrary to "
                     f"approved restriction {pol['policy_id']}?", evidence=ev, provisional=prov,
                     outcomes={"confirmed_material_exposure": {"severity": "Critical", "recommendation":
                                   "Escalate to the approval owner and request the verified exclusion."},
                               "not_contrary_or_immaterial": {"severity": None, "recommendation":
                                   "Record why the restriction does not apply or the exposure is immaterial."},
                               "uncertain": {"severity": "Info", "recommendation": "Request current controls/"
                                             "policy evidence."}},
                     guidance="Critical needs proposal.evidence_ref naming one of evidence.evidence_refs and direct "
                              "evidence resolving deterministic_blockers. An optional exclusion request uses " +
                              _PROPOSAL_GUIDE + ".")
    if not valid:
        c.observe("No currently valid approved restrictions to test against delivery")
    return delivered


def _restriction_coverage(ctx, idx, controls, camps, valid, invalid, delivered) -> None:
    c = ctx.check("restriction_coverage", "Approved suitability restrictions resolved against current controls",
                  {PC: PC_COLS, PP: PP_COLS})
    if not c.runnable:
        return
    for p in invalid:
        c.observe(f"Policy row {p['policy_id'] or '(no id)'} not usable as an approved restriction",
                  policy_id=p["policy_id"], target=p["target"], problems=p["problems"])
    if not idx.present:
        c.partial("placement_daily missing: delivery against restrictions unobserved", [f"{PD} (file)"])
    for pol in valid:
        probe = {"placement_id": pol["target"], "URL_or_app_id": pol["target"], "app_category_id": pol["target"],
                 "placement_type": "WEBSITE" if "." in pol["target"] and "::" not in pol["target"] else ""}
        uncontrolled = []
        for cid in _scope_campaigns(pol, idx, camps):
            cover = controls.cover(cid, set(), probe)
            ent = {"policy_id": pol["policy_id"], "campaign_id": cid}
            if cover["state"] == "covered":
                c.observe(f"Restriction {pol['policy_id']} enforced in {cid}", **ent, coverage=cover)
            elif cover["state"] in ("partial", "unknown"):
                c.partial(f"restriction {pol['policy_id']} coverage in {cid} is {cover['state']}")
                c.observe(f"Restriction {pol['policy_id']} coverage {cover['state']} in {cid}", **ent, coverage=cover)
            elif (pol["policy_id"], cid) not in delivered:
                uncontrolled.append(cid)
        if uncontrolled:
            c.finding("approved_restriction_uncontrolled", "Info", {"policy_id": pol["policy_id"]},
                      f"Approved restriction {pol['policy_id']} ({pol['target']}) has no enabled exclusion covering "
                      f"{len(uncontrolled)} in-scope campaigns; no delivery on it observed there in the window",
                      evidence={"campaigns_without_control": uncontrolled, "target": pol["target"],
                                "policy_evidence_ref": pol["evidence_ref"], "approved_by": pol["approved_by"],
                                "campaign_scope": pol["campaign_scope_raw"],
                                "controls_manifest_complete": controls.complete, "placement_report_present": idx.present},
                      recommendation="Confirm with the approval owner whether a control is required at the narrowest "
                                     "supported scope; include monitoring.",
                      uncertainty="No observed delivery; unreported inventory may still serve.")
    c.observe("Approved restrictions evaluated", valid=len(valid), rejected_rows=len(invalid))


def _proposal_readiness(ctx, controls) -> None:
    c = ctx.check("proposal_readiness", "Candidate scope, coverage at risk, overlap, owner and monitoring",
                  {PD: ["campaign_id", "ad_group_id", "placement_id"]})
    if not c.runnable:
        return
    keys = {k for k, _ in _PROPOSAL_OUTCOMES}
    cands = [x for x in ctx.result.reviews if x.condition_key in keys]
    if cands and not controls.present:
        c.partial("placement_controls missing: existing overlap unknown for every candidate", [f"{PC} (file)"])
    c.observe("Exclusion request candidates handed to review", candidates=[
        {"review_id": x.id, "condition_key": x.condition_key, **x.entity,
         "narrow_scopes": x.evidence.get("narrow_scopes"),
         "other_campaigns_with_delivery": x.evidence.get("other_campaigns_with_delivery"),
         "coverage_at_risk": x.evidence.get("coverage_at_risk"),
         "overlap_state": (x.evidence.get("existing_overlap") or x.evidence.get("coverage") or {}).get("state")}
        for x in sorted(cands, key=lambda x: (x.condition_key, x.id))],
        requirement="verify(): exact evidenced placement, narrow scope, coverage_at_risk, existing_overlap, "
                    "approval_owner, monitoring_plan; account scope needs cross_campaign_evidence_ref")


# ---------------------------------------------------------------------------------------------- verify
def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs a supplied evidence_ref; exclusion requests are re-checked."""
    kind = _PROPOSAL_OUTCOMES.get((item.condition_key, decision.get("outcome")))
    if kind is None:
        return []
    p = decision.get("proposal") or {}
    problems = []
    if kind == "safety":
        ref, allowed = _s(p.get("evidence_ref")), item.evidence.get("evidence_refs") or []
        if not ref:
            problems.append("confirmed_material_exposure needs proposal.evidence_ref")
        elif ref not in allowed:
            problems.append(f"evidence_ref {ref!r} is not among supplied refs {allowed}")
        if not p.get("placement"):
            return problems
    return problems + _check_exclusion(ctx, item, p, kind)


def _check_exclusion(ctx, item, p, kind) -> list[str]:
    problems = [f"proposal.{f} required" for f in _PROPOSAL_FIELDS if p.get(f) in (None, "", [], {})]
    cid, pid = _s(item.entity.get("campaign_id")), _s(item.entity.get("placement_id"))
    target = _s(p.get("placement"))
    if any(tok in target.lower() for tok in _OBSOLETE_ALL_APP):
        problems.append("obsolete all-app domain shortcut is not a valid control; propose documented app-ID/category "
                        "controls")
    idx, controls, camps = _Index(ctx), _Controls(ctx), _campaigns(ctx)
    rows = idx.by_cp.get((cid, pid), [])
    matched = []
    for r in rows:
        k = _match(target, r) if target else None
        if k == "exact" or (k == "category" and _provenanced(r)):
            matched.append(r)
    if target and not matched:
        problems.append(f"placement {target!r} matches no delivery row of {pid} in campaign {cid} "
                        "(exact ID/URL or provenanced app category required)")
    st, sid = _s(p.get("scope_type")).lower(), _s(p.get("scope_id"))
    pmax = _is_pmax(camps, cid)
    gids = {_s(r.get("ad_group_id")) for r in rows}
    if st == "campaign":
        if sid != cid:
            problems.append(f"campaign scope {sid!r} differs from reviewed campaign {cid}")
        if pmax and not controls.supports("campaign", _PMAX):
            problems.append("PMax: campaign-level placement control support not evidenced in placement_controls."
                            "supported_subtypes; use account scope with cross_campaign_evidence_ref")
    elif st == "ad_group":
        if pmax:
            problems.append("PMax has no ad-group placement scope")
        elif sid not in gids:
            problems.append(f"ad group {sid!r} did not deliver {pid} in campaign {cid}")
    elif st == "account":
        if kind == "performance":
            problems.append("account-wide scope cannot rest on one campaign's zero-conversion performance")
        if not _s(p.get("cross_campaign_evidence_ref")):
            problems.append("account-wide scope needs proposal.cross_campaign_evidence_ref")
    else:
        problems.append("scope_type must be ad_group, campaign or account")
    if matched and controls.present:
        rep = matched[0]
        if st == "account":
            inc = [x["control_id"] for x in controls.rows if x["mode"].startswith("INCLU") and x["enabled"] is not False
                   and _match(x["target"], rep)]
            full = [x["control_id"] for x in controls.rows if x["scope_type"] in _ACCOUNT_SCOPES and x["enabled"] is True
                    and x["mode"].startswith("EXCLU") and _match(x["target"], rep) == "exact"]
        else:
            cover = controls.cover(cid, {sid} if st == "ad_group" else gids, rep)
            inc, full = cover.get("included_by", []), cover.get("excluded_by", [])
        if inc:
            problems.append(f"placement is deliberately included by {inc}; exclusion would conflict")
        if full:
            problems.append(f"already excluded by enabled control(s) {full}; no new control needed")
    if kind == "performance":
        scoped = [r for r in rows if st != "ad_group" or _s(r.get("ad_group_id")) == sid]
        conv = _agg(ctx, scoped).get("conversions") if scoped else None
        if conv is None or conv > 0:
            problems.append(f"proposed scope has conversions {conv}: zero-conversion basis not met")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
