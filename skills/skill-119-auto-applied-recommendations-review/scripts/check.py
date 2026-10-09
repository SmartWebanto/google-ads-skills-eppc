"""check.py — skill-119 deterministic auto-apply subscription, change-source and authorization governance.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-119-auto-applied-recommendations-review/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Subscriptions come only from custom/auto_apply_subscriptions.subscribed at the latest snapshot_at per
         recommendation_type: true/yes/1 → subscribed, false/no/0 → not subscribed, empty/unknown/other/conflicting
         → unknown (Info); the literal 'pending' marks a pending recommendation and is NEVER a subscription (Info).
         Absent categories, absent rows or zero changes never prove disabled status.
         Attribution uses only exported client_type (Google Ads ChangeClientType names, case/space/hyphen-insensitive):
         GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION = subscription-applied (auto-applied); GOOGLE_ADS_RECOMMENDATIONS =
         manually accepted recommendation; GOOGLE_ADS_WEB_CLIENT/EDITOR/API/SCRIPTS/AUTOMATED_RULE/BULK_UPLOAD/
         MOBILE_APP and SEARCH_ADS_360_SYNC/POST = other (non-recommendation) client; OTHER, INTERNAL_TOOL, UNKNOWN,
         UNSPECIFIED, empty, unlisted or conflicting values within one change_id = unknown attribution (never guessed).
         Counts are DISTINCT change_id, never field rows.
         Authorization validity: status active|approved|valid|current = valid; draft|pending|proposed|rejected|denied =
         never valid; revoked|expired|withdrawn|superseded|inactive|suspended|ended = valid only through a DATED
         effective_to and never for current subscriptions. Window effective_from..effective_to inclusive by date;
         effective_to open|open-ended|ongoing|indefinite = no end; empty = unknown.
         authorization.type is matched to subscriptions.recommendation_type (subscription coverage, checked at the
         subscription snapshot_at). Change rows carry no recommendation type, so change coverage uses scope_id (account
         id or literal 'account', else the change's campaign_id/budget_id/strategy_id; unmatched IDs are placed via
         campaigns.id|budget_id|bidding_strategy_id and bidding_strategies.id), allowed_fields ('*', exact field_path
         or 'prefix.*'; separators ; | ,) and allowed_value_ranges.
         allowed_value_ranges format: entries separated by ';' or '|'; 'field_path=min..max' (numeric, raw change-log
         unit, either bound may be empty), 'field_path={A,B}' (literal set), 'min..max' (all fields without a
         field-specific entry), or the whole cell 'any'|'*'|'unrestricted'. Unparseable/absent applicable entry →
         undecidable (batch ai_review), never a Warning.
         Warning ('outside documented authorization') only when EVERY authorization row fails at least one dimension
         for a subscription-applied change field (or a subscribed type) AND the authorization table is
         manifest-complete and untruncated; otherwise Info 'authorization_unconfirmed'. Manually accepted and other
         client changes are inventoried, not judged. Keyword/bidding changes get request-only context, never an
         automatic disable and never a deterministic Critical.
         Critical only via ai_review on a deterministic Warning change; verify() requires proposal.evidence_ref naming a
         supplied evidence table other than the three governance files. Any reverse/revert/restrict/unsubscribe
         proposal must carry current_value, intended_benefit, owner and subsequent_edits listing every later logged
         edit of the same resource field.
         Change window = 30 days ending at ctx.as_of. A complete 30-day count needs manifest period_start..period_end
         covering it AND completeness complete AND truncation none; otherwise covered-window/lower-bound count + Info.
         Outcomes are descriptive only: equal-length contiguous mature day runs before/after the change day (change
         day excluded, days after snapshot - lag excluded), one goal_id and conversion_date_basis, min_impressions
         (CTR), min_clicks (CVR), min_conversions (CPA/ROAS) on both sides; concurrent changes are caveats; no finding
         or causal claim comes from outcomes alone.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks12 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import math
import re
import sys
from datetime import timedelta
from pathlib import Path, PurePosixPath

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-119-auto-applied-recommendations-review"
VERSION = "1.0.0"

SUBS = "custom/auto_apply_subscriptions"
CHG = "custom/auto_apply_changes"
AUTH = "external/auto_apply_authorizations"
OUTC = "custom/auto_apply_outcomes"
GOVERNANCE = (SUBS, CHG, AUTH)

SUB_COLS = ["recommendation_type", "subscribed", "scope", "snapshot_at", "source_screen"]
SRC_COLS = ["change_id", "field_path", "occurred_at", "client_type", "actor_id"]
CHG_AUTH_COLS = ["change_id", "field_path", "occurred_at", "client_type", "resource_name", "campaign_id", "budget_id",
                 "strategy_id", "operation", "old_value", "new_value", "approval_ref"]
AUTH_SUB_COLS = ["approval_ref", "type", "scope_id", "effective_from", "effective_to", "owner", "status",
                 "review_due", "reviewed_at"]
AUTH_CHG_COLS = ["approval_ref", "scope_id", "allowed_fields", "allowed_value_ranges", "effective_from",
                 "effective_to", "owner", "status"]
OUT_COLS = ["campaign_id", "date", "goal_id", "impressions", "clicks", "cost", "conversions", "conversion_value",
            "conversion_date_basis", "maturity"]

SUB_CLIENT = "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION"
MANUAL_CLIENT = "GOOGLE_ADS_RECOMMENDATIONS"
OTHER_CLIENTS = frozenset({"GOOGLE_ADS_WEB_CLIENT", "GOOGLE_ADS_AUTOMATED_RULE", "GOOGLE_ADS_SCRIPTS",
                           "GOOGLE_ADS_BULK_UPLOAD", "GOOGLE_ADS_API", "GOOGLE_ADS_EDITOR", "GOOGLE_ADS_MOBILE_APP",
                           "SEARCH_ADS_360_SYNC", "SEARCH_ADS_360_POST"})
SOURCES = ("subscription_applied", "manual_recommendation", "other_client", "unknown")
RECOMMENDATION_SOURCES = ("subscription_applied", "manual_recommendation")
ACTIVE = frozenset({"active", "approved", "valid", "current"})
NEVER_VALID = frozenset({"draft", "pending", "proposed", "rejected", "denied"})
ENDED = frozenset({"revoked", "expired", "withdrawn", "superseded", "inactive", "suspended", "ended"})
OPEN_END = frozenset({"open", "open-ended", "open_ended", "ongoing", "indefinite"})
ANY_VALUE = frozenset({"any", "*", "unrestricted"})
REVERSAL_ACTIONS = frozenset({"reverse", "revert", "restrict", "unsubscribe", "disable_subscription"})
WINDOW_DAYS = 30
_REQUEST_ONLY = ("Request-only: no account change, subscription change or notification happens in this review. Any "
                 "restriction or reversal request must name exact scope/values, current value, subsequent edits, "
                 "intended benefit, client approval owner, monitoring and recovery conditions.")


# ---------------------------------------------------------------------------------------------- parsing helpers
def _enum(v) -> str | None:
    """Normalize an enum-like cell (client_type, recommendation_type); unknown tokens → None."""
    if v is None or isinstance(v, bool):
        return None
    s = str(v).strip()
    if s.lower() in V.MISSING_TOKENS:
        return None
    return re.sub(r"[\s\-]+", "_", s).upper()


def _txt(v) -> str | None:
    s = "" if v is None else str(v).strip()
    return None if s.lower() in V.MISSING_TOKENS else s


def _when(v) -> tuple | None:
    """Sortable timestamp key (date, normalized ISO text); unparseable → None."""
    d = V.parse_date(v)
    return None if d is None else (d, str(v).strip().replace("T", " "))


def _and(values) -> bool | None:
    vals = list(values)
    if any(x is False for x in vals):
        return False
    return True if all(x is True for x in vals) else None


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _is_account(scope, account_id) -> bool:
    s = str(scope).strip()
    return s.lower() == "account" or (bool(_digits(s)) and _digits(s) == _digits(account_id))


def _source(types: list) -> str:
    distinct = set(types)
    if None in distinct or len(distinct) != 1:
        return "unknown"
    t = distinct.pop()
    if t == SUB_CLIENT:
        return "subscription_applied"
    if t == MANUAL_CLIENT:
        return "manual_recommendation"
    return "other_client" if t in OTHER_CLIENTS else "unknown"


def _changes(ctx) -> tuple[dict[str, dict], int]:
    """Group change-log field rows by change_id. Rules: conflicting timestamps within one change_id → unknown date."""
    out: dict[str, dict] = {}
    no_id = 0
    for r in ctx.rows(CHG):
        cid = _txt(r.get("change_id"))
        if cid is None:
            no_id += 1
            continue
        out.setdefault(cid, {"change_id": cid, "rows": []})["rows"].append(r)
    for c in out.values():
        rows = c["rows"]
        types = [_enum(r.get("client_type")) for r in rows]
        keys = {_when(r.get("occurred_at")) for r in rows}
        c["client_types_raw"] = sorted({str(r.get("client_type")) for r in rows if r.get("client_type") is not None})
        c["source"] = _source(types)
        c["when"] = next(iter(keys)) if len(keys) == 1 else None
        c["day"] = c["when"][0] if c["when"] else None
        c["occurred_at"] = sorted({str(r.get("occurred_at")) for r in rows if r.get("occurred_at") is not None})
        c["ids"] = {lvl: sorted({str(r.get(col)).strip() for r in rows if _txt(r.get(col))})
                    for lvl, col in (("campaign", "campaign_id"), ("budget", "budget_id"), ("strategy", "strategy_id"))}
        c["actor_ids"] = sorted({str(r.get("actor_id")) for r in rows if _txt(r.get("actor_id"))})
    return out, no_id


def _subsequent(changes: dict[str, dict]) -> tuple[dict[str, list[str]], dict[tuple, dict]]:
    """Later logged edits of the same resource_name+field_path, and the last logged value per resource field."""
    by_rf: dict[tuple, list] = {}
    for c in changes.values():
        if c["when"] is None:
            continue
        for r in c["rows"]:
            res, fp = _txt(r.get("resource_name")), _txt(r.get("field_path"))
            if res and fp:
                by_rf.setdefault((res, fp), []).append((c["when"], c["change_id"], r.get("new_value")))
    later: dict[str, list[str]] = {}
    for c in changes.values():
        found = set()
        if c["when"] is not None:
            for r in c["rows"]:
                k = (_txt(r.get("resource_name")), _txt(r.get("field_path")))
                found |= {o for w, o, _ in by_rf.get(k, ()) if o != c["change_id"] and w > c["when"]}
        later[c["change_id"]] = sorted(found)
    last = {}
    for k, entries in by_rf.items():
        w, o, val = max(entries, key=lambda e: (e[0], e[1]))
        last[k] = {"change_id": o, "occurred_at": w[1], "new_value": val}
    return later, last


def _levels(ctx) -> dict[str, set[str]]:
    """Base-table placement of IDs: campaign / budget / strategy (current snapshot linkage only)."""
    lv: dict[str, set[str]] = {}

    def add(v, level):
        s = _txt(v)
        if s:
            lv.setdefault(s, set()).add(level)

    for r in ctx.rows("campaigns"):
        add(r.get("id"), "campaign")
        add(r.get("budget_id"), "budget")
        add(r.get("bidding_strategy_id") or r.get("strategy_id"), "strategy")
    for r in ctx.rows("bidding_strategies"):
        add(r.get("id"), "strategy")
    return lv


def _validity(a: dict, day, *, current: bool) -> tuple[bool | None, str]:
    if day is None:
        return None, "change/snapshot date unknown"
    frm, to = V.parse_date(a.get("effective_from")), V.parse_date(a.get("effective_to"))
    open_end = V.norm_text(a.get("effective_to")) in OPEN_END
    if frm is None:
        window, why = None, "effective_from unknown"
    elif day < frm:
        window, why = False, f"{day} before effective_from {frm}"
    elif open_end:
        window, why = True, ""
    elif to is None:
        window, why = None, "effective_to unknown"
    elif day > to:
        window, why = False, f"{day} after effective_to {to}"
    else:
        window, why = True, ""
    st = V.norm_text(a.get("status"))
    if st in ACTIVE:
        status, swhy = True, ""
    elif st in NEVER_VALID or (st in ENDED and current):
        status, swhy = False, f"status {st}"
    elif st in ENDED:
        status, swhy = (True, "") if to is not None else (None, f"status {st} without dated effective_to")
    else:
        status, swhy = None, f"status {st or 'unknown'}"
    val = _and([window, status])
    return val, "; ".join(x for x in (why, swhy) if x)


def _change_scope(scope_id, ids: dict, account_id, levels: dict) -> tuple[bool | None, str]:
    s = _txt(scope_id)
    if s is None:
        return None, "scope_id unknown"
    if _is_account(s, account_id):
        return True, ""
    if any(s in v for v in ids.values()):
        return True, ""
    placed = levels.get(s)
    if not placed:
        return None, f"scope_id {s} not placeable in campaigns/bidding_strategies"
    if all(ids.get(level) for level in placed):
        return False, f"scope_id {s} ({'/'.join(sorted(placed))}) differs from the change IDs"
    return None, f"change {'/'.join(sorted(placed))} ID unknown for scope_id {s}"


def _sub_scope(sub_scope, scope_id, account_id) -> tuple[bool | None, str]:
    a = _txt(scope_id)
    if a is None:
        return None, "scope_id unknown"
    if _is_account(a, account_id):
        return True, ""
    s = _txt(sub_scope)
    if s is None:
        return None, "subscription scope unknown"
    if V.norm_text(s) == V.norm_text(a):
        return True, ""
    if _is_account(s, account_id):
        return False, f"authorization scope {a} narrower than account-level subscription"
    return None, f"subscription scope {s} vs authorization scope {a} not comparable"


def _field_allowed(raw, field) -> tuple[bool | None, str]:
    items = [V.norm_text(x) for x in V.split_list(raw, (";", "|", ","))]
    if not items:
        return None, "allowed_fields unknown"
    f = V.norm_text(field)
    if not f:
        return None, "field_path unknown"
    for it in items:
        if it == "*" or it == f or (it.endswith(".*") and f.startswith(it[:-1])):
            return True, ""
    return False, f"field {field} not in allowed_fields"


def _parse_ranges(raw) -> list[tuple]:
    """[(field|None, kind 'range'|'set'|'bad', payload, text)] per the module-rules format."""
    out = []
    for part in V.split_list(raw, (";", "|")):
        fld, rhs = part.split("=", 1) if "=" in part else (None, part)
        fld = V.norm_text(fld) if fld is not None else None
        rhs = rhs.strip()
        if ".." in rhs:
            lo_s, hi_s = (x.strip() for x in rhs.split("..", 1))
            lo = V.num(lo_s) if lo_s else -math.inf
            hi = V.num(hi_s) if hi_s else math.inf
            ok = lo is not None and hi is not None and (lo_s or hi_s) and lo <= hi
            out.append((fld, "range", (lo, hi), part) if ok else (fld, "bad", None, part))
        elif fld and rhs.startswith("{") and rhs.endswith("}") and rhs[1:-1].strip():
            out.append((fld, "set", {V.norm_text(x) for x in rhs[1:-1].split(",") if x.strip()}, part))
        else:
            out.append((fld, "bad", None, part))
    return out


def _value_allowed(raw, field, new) -> tuple[bool | None, str]:
    cell = V.norm_text(raw)
    if not cell or cell in V.MISSING_TOKENS:
        return None, "allowed_value_ranges unknown"
    if cell in ANY_VALUE:
        return True, ""
    entries = _parse_ranges(raw)
    f = V.norm_text(field)
    applicable = [e for e in entries if e[0] is not None and e[0] == f] or [e for e in entries if e[0] is None]
    if not applicable:
        return None, f"no documented value range for {field}"
    bad = [e[3] for e in applicable if e[1] == "bad"]
    if bad:
        return None, f"unparseable allowed_value_ranges entry {bad}"
    results = []
    for _, kind, payload, _ in applicable:
        if kind == "range":
            x = V.num(new)
            results.append(None if x is None else payload[0] <= x <= payload[1])
        else:
            results.append(None if _txt(new) is None else V.norm_text(new) in payload)
    if any(r is True for r in results):
        return True, ""
    if results and all(r is False for r in results):
        return False, f"new_value {new} outside {[e[3] for e in applicable]}"
    return None, f"new_value {new!r} not comparable with {[e[3] for e in applicable]}"


def _auth_summary(a: dict, result, dims: dict) -> dict:
    return {"approval_ref": a.get("approval_ref"), "type": a.get("type"), "scope_id": a.get("scope_id"),
            "owner": a.get("owner"), "status": a.get("status"), "allowed_fields": a.get("allowed_fields"),
            "allowed_value_ranges": a.get("allowed_value_ranges"), "effective_from": a.get("effective_from"),
            "effective_to": a.get("effective_to"), "result": result,
            "failed": [f"{k}: {why}" for k, (v, why) in dims.items() if v is False],
            "unknown": [f"{k}: {why}" for k, (v, why) in dims.items() if v is None]}


def _auth_sorted(ctx) -> list[dict]:
    return sorted(ctx.rows(AUTH), key=lambda a: (str(a.get("approval_ref") or ""), str(a.get("type") or ""),
                                                  str(a.get("scope_id") or "")))


def _auth_complete(ctx) -> bool:
    t = ctx.table(AUTH)
    return bool(t) and t.complete is True and not t.truncated


def _check(ctx, check_id: str, title: str, needs: dict):
    """ctx.check plus exact 'file:column' names for absent files (the runtime lists only 'file (file)')."""
    chk = ctx.check(check_id, title, needs)
    if chk.status == "skipped":
        chk.missing += [f"{k}:{c}" for k, cols in needs.items() if ctx.table(k) is None for c in cols]
    return chk


# ---------------------------------------------------------------------------------------------- step 1
def _subscription_inventory(ctx) -> dict | None:
    chk = _check(ctx, "subscription_inventory",
                 "Auto-apply subscriptions inventoried separately from pending recommendations", {SUBS: SUB_COLS})
    if not chk.runnable:
        return None
    t = ctx.table(SUBS)
    ref_day = ctx.snapshot or ctx.as_of
    has_enabled_at = "enabled_at_if_known" in t.columns
    groups: dict[str, list] = {}
    blank = 0
    for r in ctx.rows(SUBS):
        rt = _enum(r.get("recommendation_type"))
        if rt is None:
            blank += 1
            continue
        groups.setdefault(rt, []).append(r)
    types: dict[str, dict] = {}
    stale, undated = [], []
    for rt in sorted(groups):
        keyed = [(_when(r.get("snapshot_at")), r) for r in groups[rt]]
        dated = [k for k, _ in keyed if k]
        latest = max(dated) if dated else None
        current = [r for k, r in keyed if k == latest] if latest else [r for _, r in keyed]
        raw = sorted({str(r.get("subscribed")) for r in current})
        statuses = {_sub_status(r.get("subscribed")) for r in current}
        status = next(iter(statuses)) if len(statuses) == 1 else "unknown"
        conflict = len(statuses) > 1
        if latest is None:
            undated.append(rt)
        elif ref_day is not None and latest[0] < ref_day:
            stale.append(rt)
        row = current[0]
        types[rt] = {"recommendation_type": rt, "status": status, "subscribed_raw": raw, "conflict": conflict,
                     "snapshot_at": latest[1] if latest else None, "snapshot_day": latest[0] if latest else None,
                     "scope": row.get("scope"), "source_screen": row.get("source_screen"),
                     "enabled_at_if_known": row.get("enabled_at_if_known") if has_enabled_at else None}
    for rt, s in types.items():
        entity = {"recommendation_type": rt}
        ev = {k: s[k] for k in ("subscribed_raw", "conflict", "snapshot_at", "scope", "source_screen")}
        if s["status"] == "unknown":
            chk.finding("unknown_subscription_setting", "Info", entity,
                        f"Auto-apply setting for {rt} is unknown ({', '.join(s['subscribed_raw'])}"
                        f"{'; conflicting rows at the latest snapshot' if s['conflict'] else ''})",
                        evidence=ev, calculation={"rule": "subscribed must be true/false at the latest snapshot_at"},
                        recommendation="Export the current auto-apply setting for this category; do not treat it "
                                       "as disabled or as enabled.",
                        uncertainty="Unknown is not disabled; missing settings or zero changes prove nothing.")
        elif s["status"] == "pending":
            chk.finding("pending_recommendation_only", "Info", entity,
                        f"{rt} appears only as a pending recommendation; it is not an auto-apply subscription",
                        evidence=ev, calculation={"rule": "subscribed='pending' is never counted as subscribed"},
                        recommendation="Keep pending recommendations out of the subscription matrix; export the "
                                       "actual auto-apply setting for this category.",
                        uncertainty="A pending recommendation says nothing about whether auto-apply is on or off.")
    matrix = {k: sorted(rt for rt, s in types.items() if s["status"] == k)
              for k in ("subscribed", "not_subscribed", "unknown", "pending")}
    chk.observe("Auto-apply subscription inventory (latest snapshot per recommendation type)",
                recommendation_types=len(types), **matrix, rows=len(ctx.rows(SUBS)),
                snapshots={rt: s["snapshot_at"] for rt, s in sorted(types.items())},
                enabled_at_if_known={rt: s["enabled_at_if_known"] for rt, s in sorted(types.items())}
                if has_enabled_at else "column not supplied")
    if blank:
        chk.partial(f"{blank} subscription rows without recommendation_type not inventoried")
    if undated:
        chk.partial(f"snapshot_at unparseable for {undated}: current status unconfirmed")
    if stale:
        chk.partial(f"latest snapshot_at older than export snapshot {ref_day} for {stale}: current status unconfirmed")
    if t.complete is not True:
        chk.partial("recommendation types absent from the file are unknown, not disabled")
    return types


def _sub_status(v) -> str:
    if V.norm_text(v) == "pending":
        return "pending"
    b = V.boolean(v)
    return "subscribed" if b is True else "not_subscribed" if b is False else "unknown"


# ---------------------------------------------------------------------------------------------- step 2
def _change_sources(ctx, changes: dict, no_id: int) -> None:
    chk = _check(ctx, "change_sources", "Subscription-applied vs manually accepted change sources (distinct IDs)",
                 {CHG: SRC_COLS})
    if not chk.runnable:
        return
    counts = {s: sum(1 for c in changes.values() if c["source"] == s) for s in SOURCES}
    chk.observe("Distinct change IDs by exported client_type source", distinct_change_ids=len(changes),
                field_rows=sum(len(c["rows"]) for c in changes.values()), rows_without_change_id=no_id,
                **counts, mapping={"subscription_applied": [SUB_CLIENT], "manual_recommendation": [MANUAL_CLIENT],
                                   "other_client": sorted(OTHER_CLIENTS)},
                manual_recommendation_actors={cid: c["actor_ids"] for cid, c in sorted(changes.items())
                                              if c["source"] == "manual_recommendation"})
    unknown = sorted(cid for cid, c in changes.items() if c["source"] == "unknown")
    if unknown:
        chk.finding("unknown_change_attribution", "Info", {"table": CHG, "batch": "unknown_attribution"},
                    f"{len(unknown)} distinct change IDs have unknown recommendation attribution",
                    evidence={"change_ids": unknown,
                              "client_types": {cid: changes[cid]["client_types_raw"] for cid in unknown}},
                    calculation={"rule": "missing, unlisted or conflicting client_type within a change_id"},
                    recommendation="Re-export change history with client_type per change; keep these out of "
                                   "subscription-applied and manual counts until attributed.",
                    uncertainty="Subscription-applied and manual counts are lower bounds while attribution is unknown.")
        chk.partial(f"{len(unknown)} change IDs with unknown attribution: source counts are lower bounds")
    if no_id:
        chk.partial(f"{no_id} field rows without change_id cannot be counted as distinct changes")


# ---------------------------------------------------------------------------------------------- step 3a
def _subscription_authorization(ctx, subs: dict | None) -> None:
    chk = _check(ctx, "subscription_authorization", "Subscribed auto-apply types vs documented authorization",
                 {SUBS: SUB_COLS, AUTH: AUTH_SUB_COLS})
    if not chk.runnable:
        return
    auths = _auth_sorted(ctx)
    complete = _auth_complete(ctx)
    auth_types = {_enum(a.get("type")) for a in auths} - {None}
    disjoint = bool(auths) and not (auth_types & set(subs or {}))
    matrix, undecided, unconfirmed = [], [], []
    for rt, s in sorted((subs or {}).items()):
        if s["status"] != "subscribed":
            matrix.append({"recommendation_type": rt, "subscription": s["status"], "authorization": "not_required"
                           if s["status"] == "not_subscribed" else "not_evaluated"})
            continue
        evals = []
        for a in auths:
            if _enum(a.get("type")) != rt:
                continue
            dims = {"validity": _validity(a, s["snapshot_day"], current=True),
                    "scope": _sub_scope(s["scope"], a.get("scope_id"), ctx.account_id)}
            evals.append(_auth_summary(a, _and(v for v, _ in dims.values()), dims))
        if any(e["result"] is True for e in evals):
            verdict = "within"
        elif disjoint:
            verdict = "undecidable"
        elif all(e["result"] is False for e in evals):
            verdict = "outside"
        else:
            verdict = "undecidable"
        row = {"recommendation_type": rt, "subscription": "subscribed", "authorization": verdict,
               "snapshot_at": s["snapshot_at"], "scope": s["scope"], "matching_type_authorizations": evals}
        matrix.append(row)
        if verdict == "undecidable":
            undecided.append(row)
        elif verdict == "outside" and not complete:
            unconfirmed.append(rt)
        elif verdict == "outside":
            chk.finding("outside_documented_authorization", "Warning", {"recommendation_type": rt, "scope": s["scope"]},
                        f"Auto-apply subscription {rt} (scope {s['scope']}) at {s['snapshot_at']} has no valid "
                        f"documented authorization of that type and scope",
                        evidence={"snapshot_at": s["snapshot_at"], "source_screen": s["source_screen"],
                                  "matching_type_authorizations": evals, "authorization_rows": len(auths),
                                  "authorization_inventory_complete": True},
                        calculation={"rule": "every authorization row with type == recommendation_type fails validity "
                                             "at snapshot_at or scope coverage (none present counts as failing)"},
                        recommendation="Ask the client approval owner to document or refuse this auto-apply category. "
                                       + _REQUEST_ONLY,
                        uncertainty="Authorization records may lag real approvals; the subscription itself is not "
                                    "evidence of harm.",
                        owner=", ".join(sorted({str(e["owner"]) for e in evals if e.get("owner")})) or None)
    today = ctx.as_of
    overdue = []
    for a in auths:
        due, done = V.parse_date(a.get("review_due")), V.parse_date(a.get("reviewed_at"))
        if today is not None and due is not None and due < today and (done is None or done < due):
            overdue.append({"approval_ref": a.get("approval_ref"), "type": a.get("type"), "review_due": str(due),
                            "reviewed_at": a.get("reviewed_at"), "owner": a.get("owner")})
    chk.observe("Subscription/approval matrix", matrix=matrix, authorization_rows=len(auths),
                authorization_inventory_complete=complete, review_overdue_as_of=str(today) if today else None,
                overdue_reviews=overdue,
                approved_types_not_subscribed=sorted(auth_types - {rt for rt, s in (subs or {}).items()
                                                                  if s["status"] == "subscribed"}))
    if disjoint:
        chk.partial("authorization.type shares no value with subscriptions.recommendation_type: vocabulary not aligned")
    if unconfirmed:
        chk.finding("authorization_unconfirmed", "Info", {"table": AUTH, "batch": "subscriptions"},
                    f"{len(unconfirmed)} subscribed types lack a matching authorization, but the authorization "
                    f"inventory is not certified complete",
                    evidence={"recommendation_types": unconfirmed, "authorization_rows": len(auths)},
                    calculation={"rule": "absence of authorization is provable only from a manifest-complete, "
                                         "untruncated authorization table"},
                    recommendation="Supply the complete client authorization register with a manifest row.",
                    uncertainty="Unlisted authorizations may exist.")
        chk.partial("authorization inventory not certified complete: absence of approval unproven")
    if undecided:
        chk.review("subscription_authorization_undecidable", {"batch": "subscription_authorization"},
                   "Which of these subscribed auto-apply types fall outside the documented authorization?",
                   evidence={"subscriptions": undecided, "authorization_inventory_complete": complete},
                   outcomes={"some_outside": {"severity": "Warning", "recommendation":
                                              "Request documentation or refusal from the approval owner for the "
                                              "listed types. " + _REQUEST_ONLY},
                             "none_outside": {"severity": None, "recommendation": "Document the approval mapping."},
                             "uncertain": {"severity": "Info", "recommendation":
                                           "Ask the client to restate approvals using recommendation types and dated "
                                           "validity."}},
                   guidance="Use only the listed authorization rows and the profile. For some_outside give "
                            "proposal.recommendation_types (exact values from evidence).")


# ---------------------------------------------------------------------------------------------- step 3b
def _change_authorization(ctx, changes: dict, later: dict, last: dict):
    chk = _check(ctx, "change_authorization", "Subscription-applied changes vs documented authorization",
                 {CHG: CHG_AUTH_COLS, AUTH: AUTH_CHG_COLS})
    if not chk.runnable:
        return chk, []
    auths = _auth_sorted(ctx)
    complete = _auth_complete(ctx)
    levels = _levels(ctx)
    refs = {str(a.get("approval_ref")).strip() for a in auths if _txt(a.get("approval_ref"))}
    confirmed, undecided, unconfirmed, ledger = [], [], [], []
    verdicts = {"within": 0, "outside": 0, "undecidable": 0}
    unplaced: set[str] = set()
    for cid in sorted(changes):
        c = changes[cid]
        if c["source"] not in RECOMMENDATION_SOURCES:
            continue
        rows = sorted(c["rows"], key=lambda r: (str(r.get("resource_name") or ""), str(r.get("field_path") or "")))
        fields = []
        for r in rows:
            k = (_txt(r.get("resource_name")), _txt(r.get("field_path")))
            fields.append({"resource_name": r.get("resource_name"), "field_path": r.get("field_path"),
                           "operation": r.get("operation"), "old_value": r.get("old_value"),
                           "new_value": r.get("new_value"), "approval_ref": r.get("approval_ref"),
                           "last_logged_value": last.get(k)})
        entry = {"change_id": cid, "source": c["source"], "occurred_at": c["occurred_at"],
                 "campaign_ids": c["ids"]["campaign"], "budget_ids": c["ids"]["budget"],
                 "strategy_ids": c["ids"]["strategy"], "actor_ids": c["actor_ids"], "fields": fields,
                 "subsequent_edits": later.get(cid, [])}
        if c["source"] != "subscription_applied":
            ledger.append({**entry, "authorization": "not_compared (manually accepted)"})
            continue
        for f in fields:
            evals = []
            for a in auths:
                dims = {"scope": _change_scope(a.get("scope_id"), c["ids"], ctx.account_id, levels),
                        "validity": _validity(a, c["day"], current=False),
                        "field": _field_allowed(a.get("allowed_fields"), f["field_path"]),
                        "value": _value_allowed(a.get("allowed_value_ranges"), f["field_path"], f["new_value"])}
                if dims["scope"][0] is None and "not placeable" in dims["scope"][1]:
                    unplaced.add(str(a.get("scope_id")))
                evals.append((a, _and(v for v, _ in dims.values()), dims))
            f["verdict"] = ("within" if any(res is True for _, res, _ in evals)
                            else "outside" if all(res is False for _, res, _ in evals) else "undecidable")
            f["in_scope_authorizations"] = [_auth_summary(a, res, d) for a, res, d in evals if d["scope"][0] is not False]
            f["out_of_scope_authorizations"] = sum(1 for _, _, d in evals if d["scope"][0] is False)
            ref = _txt(f["approval_ref"])
            f["cited_ref_documented"] = (ref in refs) if ref else None
        states = {f["verdict"] for f in fields}
        verdict = "outside" if "outside" in states else "undecidable" if "undecidable" in states else "within"
        verdicts[verdict] += 1
        entry["authorization"] = verdict
        ledger.append(entry)
        if verdict == "undecidable":
            undecided.append(entry)
        elif verdict == "outside" and not complete:
            unconfirmed.append(cid)
        elif verdict == "outside":
            outside_fields = [f for f in fields if f["verdict"] == "outside"]
            entity = {"change_id": cid, "campaign_ids": c["ids"]["campaign"],
                      "resource_names": sorted({str(f["resource_name"]) for f in outside_fields})}
            chk.finding("outside_documented_authorization", "Warning", entity,
                        f"Subscription-applied change {cid} at {', '.join(c['occurred_at'])} changed "
                        f"{', '.join(str(f['field_path']) for f in outside_fields)} outside every documented "
                        f"authorization",
                        evidence={**entry, "fields_outside": outside_fields, "authorization_rows": len(auths),
                                  "authorization_inventory_complete": True},
                        calculation={"rule": "every authorization row fails >=1 of scope, validity at occurred_at, "
                                             "allowed_fields, allowed_value_ranges", "authorization_rows": len(auths)},
                        recommendation="Share the changed-field ledger with the approval owner and request the "
                                       "intended benefit; keyword or bidding changes are context for review, not an "
                                       "automatic disable. " + _REQUEST_ONLY,
                        uncertainty="The change log proves the change, not its effect; authorization registers can lag "
                                    "real approvals; current values need a current configuration snapshot.",
                        owner=", ".join(sorted({str(a["owner"]) for f in outside_fields
                                                for a in f["in_scope_authorizations"] if a.get("owner")})) or None)
            confirmed.append(entry)
    chk.observe("Changed-field ledger (recommendation-sourced changes)", changes=ledger,
                current_value_note="last_logged_value is the latest logged new_value, not a verified current value")
    chk.observe("Authorization comparison totals (distinct change IDs)", **verdicts,
                manual_recommendation_not_compared=sum(1 for c in changes.values()
                                                       if c["source"] == "manual_recommendation"),
                other_client_not_compared=sum(1 for c in changes.values() if c["source"] == "other_client"),
                unknown_attribution_not_compared=sum(1 for c in changes.values() if c["source"] == "unknown"),
                authorization_rows=len(auths), authorization_inventory_complete=complete)
    if unplaced:
        missing = [f"{k} (file)" for k in ("campaigns", "bidding_strategies") if ctx.table(k) is None]
        chk.partial(f"scope_id values not placeable in base tables: {sorted(unplaced)}", missing)
    if any(c["source"] == "unknown" for c in changes.values()):
        chk.partial("changes with unknown attribution were not compared (see change_sources)")
    if unconfirmed:
        chk.finding("authorization_unconfirmed", "Info", {"table": AUTH, "batch": "changes"},
                    f"{len(unconfirmed)} subscription-applied changes match no present authorization, but the "
                    f"authorization inventory is not certified complete",
                    evidence={"change_ids": unconfirmed, "authorization_rows": len(auths)},
                    calculation={"rule": "absence of authorization is provable only from a manifest-complete, "
                                         "untruncated authorization table"},
                    recommendation="Supply the complete client authorization register with a manifest row.",
                    uncertainty="Unlisted authorizations may cover these changes.")
        chk.partial("authorization inventory not certified complete: out-of-authorization changes unconfirmed")
    if undecided:
        chk.review("change_authorization_undecidable", {"batch": "change_authorization"},
                   "Which of these subscription-applied changes fall outside the documented authorization "
                   "(scope, validity, allowed fields or value ranges)?",
                   evidence={"changes": undecided, "change_ids": [e["change_id"] for e in undecided],
                             "authorization_inventory_complete": complete},
                   outcomes={"some_outside": {"severity": "Warning", "recommendation":
                                              "Request context and approval-owner review for the listed changes. "
                                              + _REQUEST_ONLY},
                             "none_outside": {"severity": None, "recommendation": "Record the authorization mapping."},
                             "uncertain": {"severity": "Info", "recommendation":
                                           "Ask the client to restate ranges in the documented format."}},
                   guidance="Judge only the listed authorization text (e.g. relative ranges the script cannot parse). "
                            "For some_outside give proposal.change_ids (exact ids from evidence). Keyword or bidding "
                            "changes are context, never automatic disable.")
    return chk, confirmed


# ---------------------------------------------------------------------------------------------- step 4
def _change_log_coverage(ctx, changes: dict, no_id: int) -> None:
    chk = _check(ctx, "change_log_coverage", "Change-log coverage of the declared 30-day window",
                 {CHG: ["change_id", "occurred_at"]})
    if not chk.runnable:
        return
    t = ctx.table(CHG)
    end = ctx.as_of
    if end is None:
        chk.partial("report end unknown: 30-day change window undefined")
        chk.observe("Distinct change IDs (window undefined)", distinct_change_ids=len(changes))
        return
    start = end - timedelta(days=WINDOW_DAYS - 1)
    man = t.manifest or {}
    ps, pe = V.parse_date(man.get("period_start")), V.parse_date(man.get("period_end"))
    reasons = []
    covered = None
    if ps is None or pe is None:
        reasons.append("manifest period_start/period_end absent: covered window unknown")
    else:
        lo, hi = max(ps, start), min(pe, end)
        covered = (lo, hi) if lo <= hi else None
        if covered != (start, end):
            reasons.append(f"declared period {ps}..{pe} covers "
                           f"{f'{lo}..{hi}' if covered else 'none'} of required {start}..{end}")
    if t.complete is not True:
        reasons.append(f"manifest completeness {man.get('completeness')!r} is not complete")
    if t.truncated:
        reasons.append(f"manifest truncation {man.get('truncation')!r}")
    if no_id:
        reasons.append(f"{no_id} field rows without change_id")
    undated = sorted(cid for cid, c in changes.items() if c["day"] is None)
    if undated:
        reasons.append(f"{len(undated)} change IDs with unknown/conflicting occurred_at")
    lo, hi = covered if covered else (start, end)
    in_win = {cid: c for cid, c in changes.items() if c["day"] is not None and lo <= c["day"] <= hi}
    outside = sum(1 for c in changes.values() if c["day"] is not None and not start <= c["day"] <= end)
    has_source = "client_type" in t.columns
    by_source = {s: sum(1 for c in in_win.values() if c["source"] == s) for s in SOURCES} if has_source \
        else "client_type not supplied"
    basis = "complete_30_day_count" if not reasons else "covered_window_count" if covered else "lower_bound_count"
    chk.observe("Distinct change IDs in the declared 30-day window", required_window=[start, end],
                covered_window=[lo, hi] if covered else None, count_basis=basis, distinct_change_ids=len(in_win),
                by_source=by_source, excluded_outside_window=outside, undated_change_ids=undated,
                manifest={k: man.get(k) for k in ("period_start", "period_end", "completeness", "truncation",
                                                  "filters")})
    if reasons:
        chk.finding("incomplete_change_log", "Info", {"table": CHG, "window": f"{start}..{end}"},
                    f"Change log does not prove complete coverage of {start}..{end}: {len(in_win)} distinct change IDs "
                    f"is a {basis.replace('_', ' ')}, not a complete 30-day count",
                    evidence={"reasons": reasons, "covered_window": [lo, hi] if covered else None,
                              "distinct_change_ids": len(in_win), "by_source": by_source},
                    calculation={"required_window": [start, end], "count": "distinct change_id with occurred_at date "
                                                                          "inside the covered window"},
                    recommendation="Re-export change history for the full 30 days, partitioned by date without "
                                   "truncation, with retention/coverage notes in the manifest.",
                    uncertainty="Changes outside the covered window or beyond truncation are unobserved, not zero.")
        chk.partial("; ".join(reasons))


# ---------------------------------------------------------------------------------------------- step 5
def _outcome_comparison(ctx, changes: dict) -> dict[str, dict]:
    chk = _check(ctx, "outcome_comparison", "Descriptive pre/post outcomes around recommendation-sourced changes",
                 {OUTC: OUT_COLS, CHG: ["change_id", "occurred_at", "client_type", "campaign_id"]})
    if not chk.runnable:
        return {}
    cutoff = ctx.snapshot - timedelta(days=ctx.lag_days) if ctx.snapshot and ctx.lag_days is not None else None
    if cutoff is None:
        chk.partial(f"account lag/snapshot unknown ({ctx.maturity_note}): relied on row maturity flags only")
    days: dict[str, dict] = {}
    dups: set = set()
    for r in ctx.rows(OUTC):
        cid, d = _txt(r.get("campaign_id")), V.parse_date(r.get("date"))
        if cid is None or d is None:
            continue
        if d in days.setdefault(cid, {}):
            dups.add((cid, d))
        days[cid][d] = r
    for cid, d in dups:
        days[cid].pop(d, None)
    if dups:
        chk.partial(f"{len(dups)} duplicate campaign/date outcome rows excluded")

    def usable(cid, d):
        r = days.get(cid, {}).get(d)
        mature = r is not None and (V.boolean(r.get("maturity")) is True or V.norm_text(r.get("maturity")) == "mature")
        return mature and (cutoff is None or d <= cutoff)

    gates = {m: ctx.params.get(m) for m in ("min_impressions", "min_clicks", "min_conversions")}
    for m, res in gates.items():
        if res.value is None:
            chk.partial(f"{m} unresolved: {res.reason}")
    out: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for chg_id in sorted(changes):
        c = changes[chg_id]
        if c["source"] not in RECOMMENDATION_SOURCES:
            continue
        camps = c["ids"]["campaign"]
        if c["day"] is None or len(camps) != 1:
            skipped[chg_id] = "change date unknown" if c["day"] is None else "not exactly one campaign_id"
            continue
        cid, d = camps[0], c["day"]
        pre = []
        while usable(cid, d - timedelta(days=len(pre) + 1)):
            pre.append(d - timedelta(days=len(pre) + 1))
        post = []
        while usable(cid, d + timedelta(days=len(post) + 1)):
            post.append(d + timedelta(days=len(post) + 1))
        k = min(len(pre), len(post))
        if k == 0:
            skipped[chg_id] = "no complete mature day on one side of the change"
            continue
        pre_rows = [days[cid][x] for x in pre[:k]]
        post_rows = [days[cid][x] for x in post[:k]]
        goals = {_txt(r.get("goal_id")) for r in pre_rows + post_rows}
        bases = {_txt(r.get("conversion_date_basis")) for r in pre_rows + post_rows}
        lo, hi = d - timedelta(days=k), d + timedelta(days=k)
        concurrent = sorted(o for o, oc in changes.items() if o != chg_id and oc["day"] is not None
                            and lo <= oc["day"] <= hi
                            and any(set(oc["ids"][lvl]) & set(c["ids"][lvl]) for lvl in ("campaign", "budget",
                                                                                         "strategy")))
        undated_related = sorted(o for o, oc in changes.items() if o != chg_id and oc["day"] is None
                                 and set(oc["ids"]["campaign"]) & set(camps))
        rec = {"change_id": chg_id, "source": c["source"], "campaign_id": cid, "change_day": d,
               "pre_window": [pre[k - 1], pre[0]], "post_window": [post[0], post[k - 1]], "days_per_side": k,
               "goal_ids": sorted(g or "unknown" for g in goals),
               "conversion_date_basis": sorted(b or "unknown" for b in bases),
               "concurrent_changes": concurrent, "undated_related_changes": undated_related,
               "caveat": "observational comparison; not causal uplift"
                         + ("; concurrent changes confound the comparison" if concurrent or undated_related else "")}
        if len(goals) != 1 or None in goals or len(bases) != 1 or None in bases:
            rec["comparable"] = False
            rec["reason"] = "goal_id or conversion_date_basis unknown or differs across the windows"
        else:
            rec["comparable"] = True
            rec.update(_side_metrics(ctx, pre_rows, post_rows, gates))
        out[chg_id] = rec
        chk.observe(f"Change {chg_id}: descriptive pre/post outcomes", **rec)
    chk.observe("Outcome comparison coverage", compared=sorted(out), not_compared=skipped)
    if skipped:
        chk.partial(f"{len(skipped)} recommendation-sourced changes without a matched mature pre/post window")
    return out


def _side_metrics(ctx, pre_rows: list, post_rows: list, gates: dict) -> dict:
    def totals(rows):
        t = {}
        for m in ("impressions", "clicks", "conversions", "conversion_value"):
            vals = [V.num(r.get(m)) for r in rows]
            t[m] = None if any(v is None for v in vals) else sum(vals)
        costs = [ctx.money(r.get("cost")) for r in rows]
        t["cost"] = None if any(v is None for v in costs) else sum(costs)
        return t

    pre, post = totals(pre_rows), totals(post_rows)
    specs = {"ctr": ("clicks", "impressions", "min_impressions", "impressions"),
             "cvr": ("conversions", "clicks", "min_clicks", "clicks"),
             "cpa": ("cost", "conversions", "min_conversions", "conversions"),
             "roas": ("conversion_value", "cost", "min_conversions", "conversions")}
    metrics = {}
    for name, (num, den, gate, gate_col) in specs.items():
        g = gates[gate].value
        a, b = pre[gate_col], post[gate_col]
        passed = g is not None and a is not None and b is not None and a >= g and b >= g
        entry = {"gate": f"{gate}={g} on both sides ({gate_col} pre={a}, post={b})", "passed": passed}
        if passed:
            entry["pre"], entry["post"] = V.ratio(pre[num], pre[den]), V.ratio(post[num], post[den])
            if entry["pre"] is not None and entry["post"] is not None:
                entry["relative_change"] = V.ratio(entry["post"] - entry["pre"], entry["pre"])
        metrics[name] = entry
    return {"pre_totals": pre, "post_totals": post, "metrics": metrics}


# ---------------------------------------------------------------------------------------------- run / verify
def run(ctx) -> None:
    """Run change-source, subscription/change authorization, coverage and outcome checks; queue Critical reviews.

    Rules:   Unknown subscription or client_type → Info, never guessed; counts are distinct change_id. Warning only when
             EVERY authorization row fails for a subscription-applied change on a manifest-complete, untruncated table,
             else Info authorization_unconfirmed; manual/other-client changes are inventoried only. Each confirmed
             Warning gets an ai_review whose Critical needs proposal.evidence_ref to a non-governance table.
    """
    changes, no_id = _changes(ctx)
    later, last = _subsequent(changes)
    subs = _subscription_inventory(ctx)
    _change_sources(ctx, changes, no_id)
    _subscription_authorization(ctx, subs)
    auth_chk, confirmed = _change_authorization(ctx, changes, later, last)
    _change_log_coverage(ctx, changes, no_id)
    comparisons = _outcome_comparison(ctx, changes)
    supplied = sorted(k for k in ctx.evidence.tables if k not in GOVERNANCE and k != "table_manifest")
    for entry in confirmed:
        cid = entry["change_id"]
        auth_chk.review("unauthorized_material_failure", {"change_id": cid},
                        f"Did out-of-authorization change {cid} cause a directly evidenced MATERIAL delivery, "
                        f"measurement or safety failure?",
                        evidence={"change": entry, "outcome_comparison": comparisons.get(cid),
                                  "supplied_evidence_tables": supplied},
                        outcomes={"material_failure_evidenced": {"severity": "Critical", "recommendation":
                                                                 "Escalate to the approval owner with the cited "
                                                                 "failure evidence. " + _REQUEST_ONLY},
                                  "not_evidenced": {"severity": None, "recommendation":
                                                    "Keep the Warning; request delivery/safety evidence if concerned."}},
                        guidance="Critical needs proposal.evidence_ref naming a supplied non-governance table "
                                 "('<file>#<locator>'). Pre/post outcomes are observational: a metric change is not "
                                 "proof of harm. A reverse/restrict proposal (proposal.action) needs current_value, "
                                 "subsequent_edits, intended_benefit and owner.")


def _table_for_ref(ctx, ref: str):
    base = ref.split("#", 1)[0].strip()
    for key, t in ctx.evidence.tables.items():
        if base in (key, t.filename, PurePosixPath(t.filename).name):
            return key
    return None


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical needs a supplied non-governance evidence_ref; batch Warnings must list reviewed ids;
    reversal/restriction proposals need current_value, intended_benefit, owner and every later logged edit."""
    outcome = decision.get("outcome")
    spec = item.outcomes.get(outcome) or {}
    proposal = decision.get("proposal") or {}
    problems: list[str] = []
    if spec.get("severity") == "Critical":
        ref = str(proposal.get("evidence_ref") or "").strip()
        key = _table_for_ref(ctx, ref) if ref else None
        if not ref:
            problems.append("Critical needs proposal.evidence_ref pointing at supplied failure evidence")
        elif key is None:
            problems.append(f"evidence_ref {ref!r} names no supplied evidence table")
        elif key in GOVERNANCE:
            problems.append(f"evidence_ref {ref!r} is a governance file; it cannot evidence a delivery/safety failure")
    chosen = []
    if item.condition_key == "change_authorization_undecidable" and outcome == "some_outside":
        listed = set(item.evidence.get("change_ids") or [])
        chosen = [str(x) for x in proposal.get("change_ids") or []]
        if not chosen:
            problems.append("proposal.change_ids required")
        problems += [f"change_id {x} not in the reviewed batch" for x in chosen if x not in listed]
    if item.condition_key == "subscription_authorization_undecidable" and outcome == "some_outside":
        listed = {s["recommendation_type"] for s in item.evidence.get("subscriptions") or []}
        types = [str(x) for x in proposal.get("recommendation_types") or []]
        if not types:
            problems.append("proposal.recommendation_types required")
        problems += [f"recommendation_type {x} not in the reviewed batch" for x in types if x not in listed]
    if str(proposal.get("action") or "").strip().lower() in REVERSAL_ACTIONS:
        for k in ("current_value", "intended_benefit", "owner"):
            if not str(proposal.get(k) or "").strip():
                problems.append(f"{proposal.get('action')} proposal needs {k}")
        if "subsequent_edits" not in proposal:
            problems.append(f"{proposal.get('action')} proposal needs subsequent_edits (list, may be empty)")
        else:
            if item.condition_key == "unauthorized_material_failure":
                expected = set(item.evidence.get("change", {}).get("subsequent_edits") or [])
            else:
                expected = {x for e in item.evidence.get("changes") or [] if e["change_id"] in chosen
                            for x in e.get("subsequent_edits") or []}
            given = {str(x) for x in proposal.get("subsequent_edits") or []}
            problems += [f"subsequent edit {x} not acknowledged" for x in sorted(expected - given)]
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
