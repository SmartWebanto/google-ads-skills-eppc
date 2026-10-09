"""negatives.py — Literal Google Ads negative keyword matching and effective-scope resolution.

exports: MAX_QUERY_WORDS | tokens(text) -> list[str] | normalize_match(v) -> str|None
         blocks(neg_text, neg_match, query) -> bool|None | Negative | effective_negatives(ctx) -> (dict, list[str])
used_by: skill-014/016/017/015 scripts/check.py
rules:   Direction is negative → query: EXACT = identical token sequence; PHRASE = negative tokens
         contiguous and in order inside the query; BROAD = every negative token present, any order.
         No synonym/plural/misspelling expansion — negatives do not match close variants.
         Queries over MAX_QUERY_WORDS words or containing operators return None (uncertain), not False.
         Match type comes only from an explicit column; bracket/quote punctuation is NOT inferred.
         Effective scope for an ad group = its ad-group negatives + campaign negatives + attached
         shared-list members + account-level rows (zero account rows = known-empty only when the
         negative_keywords manifest certifies completeness); removed entities are excluded.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial matcher from skill-017 semantics
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUERY_WORDS = 16
_OPERATOR = re.compile(r"[+\[\]\"]")
_LIST_MEMBER = re.compile(r"^(?P<text>.+?)\s*\((?P<match>EXACT|PHRASE|BROAD)\)$", re.IGNORECASE)


def tokens(text: str) -> list[str]:
    """Lowercase whitespace tokens.

    Rules:   punctuation kept; no stemming or synonym expansion.
    """
    return str(text or "").lower().split()


def normalize_match(v) -> str | None:
    """EXACT/PHRASE/BROAD or None.

    Rules:   only explicit match-type values; never inferred from brackets/quotes.
    """
    s = str(v or "").strip().upper().replace(" MATCH", "")
    return s if s in ("EXACT", "PHRASE", "BROAD") else None


def blocks(neg_text: str, neg_match: str, query: str) -> bool | None:
    """True if the negative blocks the literal query; None when local literal rules cannot decide.

    Rules:   see module rules — direction negative→query, >16 words or operators → None.
    """
    match = normalize_match(neg_match)
    if match is None:
        return None
    q, n = tokens(query), tokens(neg_text)
    if not n or not q:
        return None
    if len(q) > MAX_QUERY_WORDS or _OPERATOR.search(query or ""):
        return None
    if match == "EXACT":
        return q == n
    if match == "PHRASE":
        k = len(n)
        return any(q[i:i + k] == n for i in range(len(q) - k + 1))
    return set(n).issubset(q)


@dataclass(frozen=True)
class Negative:
    text: str
    match: str
    level: str  # account | campaign | ad_group | shared_list
    source_id: str  # list id, campaign id or ad group id
    ref: str  # human-readable provenance


def _inactive(row: dict) -> bool:
    return str(row.get("status") or "").upper() in ("REMOVED", "DELETED")


def effective_negatives(ctx) -> tuple[dict, list[str]]:
    """Map (campaign_id, ad_group_id) → list[Negative] for every ad group in ad_groups.

    Rules:   Returns (scopes, gaps). gaps lists evidence limits (no account-level table,
             unparseable list members, missing list associations); callers report them as coverage.
    """
    gaps: list[str] = []
    groups = [r for r in ctx.rows("ad_groups") if not _inactive(r)]
    by_campaign: dict[str, list[Negative]] = {}
    by_group: dict[str, list[Negative]] = {}
    account_level: list[Negative] = []
    for r in ctx.rows("negative_keywords"):
        if _inactive(r):
            continue
        m = normalize_match(r.get("match_type"))
        if m is None:
            gaps.append(f"negative '{r.get('text')}' has no explicit match type")
            continue
        level = str(r.get("level") or "").lower().replace("-", "_").replace(" ", "_")
        neg = Negative(str(r.get("text") or ""), m, level or "unknown", "", "")
        if level in ("ad_group", "adgroup"):
            gid = str(r.get("ad_group_id") or "")
            by_group.setdefault(gid, []).append(Negative(neg.text, m, "ad_group", gid, f"ad group {gid}"))
        elif level == "campaign":
            cid = str(r.get("campaign_id") or "")
            by_campaign.setdefault(cid, []).append(Negative(neg.text, m, "campaign", cid, f"campaign {cid}"))
        elif level == "account":
            account_level.append(Negative(neg.text, m, "account", "", "account"))
        else:
            gaps.append(f"negative '{neg.text}' has unknown level '{r.get('level')}'")
    lists = ctx.table("shared_negative_lists")
    if lists is None:
        gaps.append("shared_negative_lists missing: shared-list coverage unknown")
    else:
        for r in lists.rows:
            lid = str(r.get("list_id") or "")
            applied_raw = r.get("campaigns_applied") if "campaigns_applied" in lists.columns else r.get("campaign_ids")
            applied = [c.strip() for c in re.split(r"[;|,]", str(applied_raw or "")) if c.strip()]
            members = []
            if "member_text" in lists.columns:  # flattened: one member per row
                m = normalize_match(r.get("member_match_type"))
                if m and r.get("member_text"):
                    members.append((str(r["member_text"]), m))
            else:
                for raw in re.split(r";", str(r.get("keywords") or "")):
                    raw = raw.strip()
                    if not raw:
                        continue
                    mm = _LIST_MEMBER.match(raw)
                    if not mm:
                        gaps.append(f"list {lid} member '{raw}' has no explicit match type")
                        continue
                    members.append((mm.group("text").strip(), mm.group("match").upper()))
            declared = V_int(r.get("member_count"))
            if declared is not None and "member_text" not in lists.columns and declared != len(members):
                gaps.append(f"list {lid} declares {declared} members but {len(members)} parsed")
            for cid in applied:
                for text, m in members:
                    by_campaign.setdefault(cid, []).append(
                        Negative(text, m, "shared_list", lid, f"shared list {lid} ({r.get('name')})"))
    neg_table = ctx.table("negative_keywords")
    if neg_table is not None and neg_table.complete is not True and not account_level:
        # DATA_CONTRACT: negative_keywords carries account/campaign/ad-group scope; zero account rows are
        # known-empty only when the manifest certifies the inventory complete.
        gaps.append("negative_keywords not certified complete: account-level scope unknown")
    scopes = {}
    for g in groups:
        cid, gid = str(g.get("campaign_id") or ""), str(g.get("id") or "")
        scopes[(cid, gid)] = account_level + by_campaign.get(cid, []) + by_group.get(gid, [])
    return scopes, sorted(set(gaps))


def V_int(v):
    """Parse an int or None.

    Rules:   used only for declared member counts; non-integers → None.
    """
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None
