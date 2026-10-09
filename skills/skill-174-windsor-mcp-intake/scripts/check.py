"""check.py — skill-174 Windsor.ai MCP intake: query plan → saved get_data results → normalized adsrun export.

exports: SKILL | VERSION | PLAN_SCHEMA | RAW_SCHEMA | PULLS | READ_TOOLS | FORBIDDEN_TOOLS
         run(ctx) -> None | make_plan(account, date_from, date_to, snapshot_date, chunk_days=0, pulls=None) -> dict
         plan(out, account, date_from, date_to, snapshot_date, chunk_days=0, pulls=None) -> int
         normalize(plan_path, raw_dir, out, conversion_lag_days, skip=(), search_terms_from=None) -> int
         main(argv=None) -> int
used_by: skills/skill-174-windsor-mcp-intake/SKILL.md → Analysis Steps (plan → MCP get_data → normalize → run);
         skills/skill-174-windsor-mcp-intake/tests/test_check.py
related: skills/skill-173-export-intake-preflight/scripts/check.py — same output tables/vocabularies from UI downloads;
         skills/_resources/DATA_CONTRACT.md — semantic columns, account row and table_manifest written here;
         docs/windsor-phase0-screening.md — catalog screening and live observations behind PULLS
rules:   This script NEVER touches the network: the AI fetches data with the Windsor MCP READ tools only
         (READ_TOOLS) and saves each get_data result verbatim; write tools (FORBIDDEN_TOOLS) are never used.
         One Google Ads account per intake; every record's account_id must equal the plan account (dashes
         ignored) and currency must be single — otherwise normalize REFUSES (exit 2, nothing written).
         Saved arguments must equal the plan arguments exactly; every requested field must be a key in every
         record (null allowed); JSON that does not parse (truncated MCP output) is refused, never repaired.
         Units (live-observed 2026-09-28, one EUR account): cost/budget/value in currency units, shares as
         fractions. Google Ads API censoring: share 0.0999 = "<10%", lost share 0.9001 = ">90%"
         (developers.google.com/google-ads/api/fields/v21/metrics) → never averaged as numbers.
         Windsor aggregates lost-IS as a plain row average (catalog aggregate_formula), so campaign_metrics is
         pulled DAILY and aggregated here: sums for counts/money (Decimal). Shares: 1-day window → API value;
         multi-day → eligible-weighted (IS = Σimpr/Σ(impr/IS_d), lost = Σ(elig·lost_d)/Σelig) ONLY for campaigns
         proven Search-only by the campaigns pull (else impressions include partner/Display traffic) with a row
         for every day; otherwise, or on any censored/unknown day → 'withheld' (adsrun reads it as unknown).
         Enums must already be Google Ads API tokens; UNKNOWN/UNSPECIFIED become empty; anything else unexpected
         is refused with the field name (first live run surfaces format drift instead of corrupting data).
         daily_budget is written only when the budget period is DAILY. Inventory completeness is declared
         'partial' where unverified (conversion_actions inventory; negatives without shared/account lists).
         Zero-activity rows are NOT materialized (whether Windsor omits them is unverified).
         Search terms are NEVER pulled through MCP: the raw query text would reach the model context before any
         local sanitizing (DATA_CONTRACT invariant 8). They enter only via --search-terms-from, a skill-173 export
         folder of the same customer, currency and window with a compatible conversion date basis. Provenance is
         not trusted for privacy: the import re-checks every text cell locally (email-like or 8+ digits, local
         phone formats included) and DROPS such rows whole (table declared partial); cells are never printed. Advertiser text
         (ads, keywords) is kept verbatim. Everything user-facing is
         English. out must be empty or new. No clock reads: the snapshot date is an explicit plan argument.
         run(): readiness joins of a normalized export (metrics→inventory, children→parents); orphans are
         Warning; missing tables/columns are coverage (skipped), never findings; never Critical.
agent:   claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor | initial Windsor MCP intake (plan/normalize/run)
agent:   claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_windsor_b | no MCP search terms; import from skill-173 export
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402

SKILL = "skill-174-windsor-mcp-intake"
VERSION = "1.0.0"
PLAN_SCHEMA = "eppc-windsor-plan/1"
RAW_SCHEMA = "eppc-windsor-raw/1"
CONNECTOR = "google_ads"
READ_TOOLS = ("get_connectors", "get_options", "get_fields", "get_data")
FORBIDDEN_TOOLS = ("execute_action", "list_actions", "create_destination_task", "create_custom_field",
                   "get_connector_authorization_url", "get_connector_connect_info")
CENSORED_LOW, CENSORED_HIGH = 0.0999, 0.9001
WITHHELD = "withheld"

# ----------------------------------------------------------------------------- pull specifications
# kind: account|id|rid (resource name → trailing id)|text|int|number|money|rate|bool|token|date|list|urls|
#       enum:<vocab>. grain: snapshot (no window semantics) | period (aggregated window) | daily (date field).
_ACC = ("account_id", "customer_id", "account")
PULLS: dict[str, dict] = {
    "account": {"grain": "snapshot", "fields": [
        _ACC, ("account_name", "name", "text"), ("account_currency_code", "currency_code", "token"),
        ("account_time_zone", "time_zone", "text"), ("auto_tagging_enabled", "auto_tagging", "bool")]},
    "campaigns": {"grain": "snapshot", "key": ["id"], "fields": [
        _ACC, ("campaign_id", "id", "id"), ("campaign_name", "name", "text"),
        ("campaign_status", "status", "enum:status"), ("advertising_channel_type", "channel_type", "token"),
        ("advertising_channel_sub_type", "channel_subtype", "token"),
        ("bidding_strategy_type", "bidding_strategy_type", "token"), ("budget_id", "budget_id", "rid"),
        ("budget_amount", "budget_amount", "money"), ("period", "budget_period", "token"),
        ("network_settings_target_partner_search_network", "search_partners", "bool"),
        ("network_settings_target_content_network", "display_network", "bool"),
        ("geo_target_type_setting_positive_geo_target_type", "geo_target_method", "token"),
        ("end_date", "end_date", "date")]},
    "campaign_metrics": {"grain": "daily", "key": ["campaign_id"], "fields": [
        _ACC, ("date", "date", "date"), ("campaign_id", "campaign_id", "id"), ("impressions", "impressions", "int"),
        ("clicks", "clicks", "int"), ("cost", "cost", "money"), ("conversions", "conversions", "number"),
        ("conversions_value", "conversion_value", "money"),
        ("search_impression_share", "search_impression_share", "rate"),
        ("search_budget_lost_impression_share", "search_budget_lost_is", "rate"),
        ("search_rank_lost_impression_share", "search_rank_lost_is", "rate")]},
    "ad_groups": {"grain": "snapshot", "key": ["id"], "fields": [
        _ACC, ("campaign_id", "campaign_id", "id"), ("ad_group_id", "id", "id"), ("ad_group_name", "name", "text"),
        ("ad_group_status", "status", "enum:status"), ("ad_group_type", "type", "token")]},
    "keywords": {"grain": "snapshot", "key": ["ad_group_id", "id"], "fields": [
        _ACC, ("campaign_id", "campaign_id", "id"), ("ad_group_id", "ad_group_id", "id"), ("criterion_id", "id", "id"),
        ("ad_group_criterion_keyword_text", "text", "text"),
        ("ad_group_criterion_keyword_match_type", "match_type", "enum:match_type"),
        ("keyword_status", "status", "enum:status"), ("ad_group_criterion_negative", "negative", "bool"),
        ("quality_info_quality_score", "quality_score", "int"),
        ("quality_info_creative_quality_score", "ad_relevance", "enum:qs_component"),
        ("quality_info_post_click_quality_score", "landing_page_experience", "enum:qs_component"),
        ("quality_info_search_predicted_ctr", "expected_ctr", "enum:qs_component")]},
    "keyword_metrics": {"grain": "period", "key": ["ad_group_id", "keyword_id"], "fields": [
        _ACC, ("campaign_id", "campaign_id", "id"), ("ad_group_id", "ad_group_id", "id"),
        ("criterion_id", "keyword_id", "id"), ("ad_group_criterion_keyword_text", "text", "text"),
        ("quality_info_quality_score", "quality_score", "int"), ("impressions", "impressions", "int"),
        ("clicks", "clicks", "int"), ("cost", "cost", "money"), ("conversions", "conversions", "number"),
        ("conversions_value", "conversion_value", "money")]},
    "ads": {"grain": "snapshot", "key": ["ad_group_id", "id"], "fields": [
        _ACC, ("campaign_id", "campaign_id", "id"), ("ad_group_id", "ad_group_id", "id"),
        ("ad_group_ad_ad_id", "id", "id"), ("ad_group_ad_ad_type", "type", "token"),
        ("ad_group_ad_status", "status", "enum:status"),
        ("ad_group_ad_ad_responsive_search_ad_headlines", "headlines", "list"),
        ("ad_group_ad_ad_responsive_search_ad_descriptions", "descriptions", "list"),
        ("ad_group_ad_ad_final_urls", "final_url", "urls"), ("ad_group_ad_ad_strength", "ad_strength", "token"),
        ("ad_group_ad_policy_summary_approval_status", "approval_status", "token"),
        ("ad_group_ad_policy_summary_policy_topic_entries", "policy_topics", "list")]},
    "ad_metrics": {"grain": "period", "key": ["ad_group_id", "ad_id"], "fields": [
        _ACC, ("campaign_id", "campaign_id", "id"), ("ad_group_id", "ad_group_id", "id"),
        ("ad_group_ad_ad_id", "ad_id", "id"), ("impressions", "impressions", "int"), ("clicks", "clicks", "int"),
        ("cost", "cost", "money"), ("conversions", "conversions", "number"),
        ("conversions_value", "conversion_value", "money")]},
    "campaign_negatives": {"grain": "snapshot", "key": ["campaign_id", "text", "match_type"], "fields": [
        _ACC, ("campaign_id", "campaign_id", "id"), ("campaign_criterion_keyword_text", "text", "text"),
        ("campaign_criterion_keyword_match_type", "match_type", "enum:match_type"),
        ("campaign_criterion_negative", "negative", "bool")]},
    "conversion_actions": {"grain": "snapshot", "key": ["id"], "fields": [
        _ACC, ("conversion_action_id", "id", "rid"), ("conversion_action_name", "name", "text"),
        ("conversion_action_category", "category", "token"), ("conversion_action_status", "status", "token"),
        ("conversion_action_type", "type", "token"), ("conversion_action_counting_type", "counting", "enum:counting"),
        ("conversion_action_primary_for_goal", "primary_for_goal", "bool"),
        ("conversion_action_click_through_lookback_window_days", "click_window_days", "int")]},
}
DATED = ("campaign_metrics", "keyword_metrics", "ad_metrics")

VOCAB = {
    "status": {"ENABLED", "PAUSED", "REMOVED"},
    "match_type": {"EXACT", "PHRASE", "BROAD"},
    "qs_component": {"ABOVE_AVERAGE", "AVERAGE", "BELOW_AVERAGE"},
    "counting": {"ONE_PER_CLICK": "one", "MANY_PER_CLICK": "every"},
}
_EMPTY_TOKENS = {"UNKNOWN", "UNSPECIFIED"}
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")
_RID = re.compile(r"^(?:customers/\d+/[A-Za-z]+/)?(\d+)$")
_ID = re.compile(r"^\d+$")
_ACCOUNT = re.compile(r"^\d{3}-?\d{3}-?\d{4}$")

OUTPUT_COLUMNS = {
    "campaigns": ["id", "name", "status", "channel_type", "channel_subtype", "bidding_strategy_type", "budget_id",
                  "daily_budget", "search_partners", "display_network", "geo_target_method", "end_date", "customer_id"],
    "campaign_metrics": ["campaign_id", "impressions", "clicks", "cost", "conversions", "conversion_value",
                         "search_impression_share", "search_budget_lost_is", "search_rank_lost_is", "customer_id"],
    "ad_groups": ["id", "campaign_id", "name", "status", "type", "customer_id"],
    "keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type", "status", "quality_score",
                 "expected_ctr", "ad_relevance", "landing_page_experience", "customer_id"],
    "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions",
                        "conversion_value", "quality_score", "customer_id"],
    "ads": ["id", "campaign_id", "ad_group_id", "type", "status", "headlines", "descriptions", "final_url",
            "ad_strength", "approval_status", "policy_topics", "customer_id"],
    "ad_metrics": ["ad_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions",
                   "conversion_value", "customer_id"],
    "negative_keywords": ["text", "match_type", "level", "campaign_id", "ad_group_id", "customer_id"],
    "conversion_actions": ["id", "name", "category", "status", "type", "counting", "primary_for_goal",
                           "click_window_days", "customer_id"],
}
TABLE_GRAIN = {"campaigns": ["id"], "campaign_metrics": ["campaign_id"], "ad_groups": ["id"],
               "keywords": ["ad_group_id", "id"], "keyword_metrics": ["ad_group_id", "keyword_id"],
               "ads": ["ad_group_id", "id"], "ad_metrics": ["ad_group_id", "ad_id"],
               "negative_keywords": ["level", "campaign_id", "ad_group_id", "text", "match_type"],
               "conversion_actions": ["id"]}
SNAPSHOT_TABLES = ("campaigns", "ad_groups", "keywords", "ads", "negative_keywords", "conversion_actions")
PARTIAL_NOTES = {
    "negative_keywords": "partial — campaign and ad-group negatives only; shared negative lists and account-level "
                         "negatives are not pulled",
    "conversion_actions": "partial — inventory completeness unverified (Windsor conversion_action_id maps to "
                          "segments.conversion_action)",
}
SUM_COLS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


class IntakeError(ValueError):
    """Raw/plan problem that makes normalize refuse. Rules: message is English and names pull/field/value."""


# ----------------------------------------------------------------------------- plan


def _parse_day(s: str, what: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise IntakeError(f"{what} must be YYYY-MM-DD, got {s!r}") from None


def make_plan(account: str, date_from: str, date_to: str, snapshot_date: str, chunk_days: int = 0,
              pulls: list[str] | None = None) -> dict:
    """Build the MCP query plan: one get_data call per pull and date chunk.

    Rules:   Explicit dates only (no presets): date_from <= date_to < snapshot_date so every day is complete in
             the account time zone per the caller. chunk_days > 0 splits DATED pulls into disjoint consecutive
             windows (for MCP size limits); snapshot pulls always use the whole window. Unknown pull names raise.
    """
    if not _ACCOUNT.match(account or ""):
        raise IntakeError(f"account must be a Google Ads customer ID like 123-456-7890, got {account!r}")
    d0, d1, snap = (_parse_day(date_from, "date_from"), _parse_day(date_to, "date_to"),
                    _parse_day(snapshot_date, "snapshot_date"))
    if not d0 <= d1 < snap:
        raise IntakeError("dates must satisfy date_from <= date_to < snapshot_date (complete days only)")
    if chunk_days < 0:
        raise IntakeError("chunk_days must be >= 0")
    names = list(PULLS) if not pulls else ["account"] + [n for n in pulls if n != "account"]
    bad = [n for n in names if n not in PULLS]
    if bad:
        raise IntakeError(f"unknown pulls {bad}; allowed {list(PULLS)}")
    calls = []
    for name in names:
        windows = [(d0, d1)]
        if name in DATED and chunk_days:
            windows, cur = [], d0
            while cur <= d1:
                end = min(d1, cur + timedelta(days=chunk_days - 1))
                windows.append((cur, end))
                cur = end + timedelta(days=1)
        for a, b in windows:
            pid = name if len(windows) == 1 else f"{name}__{a.isoformat()}__{b.isoformat()}"
            calls.append({"pull_id": pid, "pull": name, "file": f"raw/{pid}.json", "tool": "get_data",
                          "arguments": {"connector": CONNECTOR, "accounts": [account],
                                        "fields": [f for f, _, _ in PULLS[name]["fields"]],
                                        "date_from": a.isoformat(), "date_to": b.isoformat()}})
    return {"schema": PLAN_SCHEMA, "skill": SKILL, "version": VERSION, "connector": CONNECTOR, "account": account,
            "date_from": d0.isoformat(), "date_to": d1.isoformat(), "snapshot_date": snap.isoformat(),
            "chunk_days": chunk_days, "read_tools": list(READ_TOOLS), "forbidden_tools": list(FORBIDDEN_TOOLS),
            "calls": calls}


def _plan_md(p: dict) -> str:
    L = ["# Windsor MCP pull plan", "",
         f"Account {p['account']} · window {p['date_from']} → {p['date_to']} · snapshot {p['snapshot_date']}.", "",
         "Use ONLY these Windsor MCP tools: " + ", ".join(f"`{t}`" for t in p["read_tools"]) + ". Never call "
         + ", ".join(f"`{t}`" for t in p["forbidden_tools"]) + " or any other write tool.", "",
         "For each row: call `get_data` with exactly the arguments in `plan.json`, then save the result verbatim as",
         f"`{{\"schema\": \"{RAW_SCHEMA}\", \"pull_id\": …, \"arguments\": …, \"records\": <result list>}}` in the "
         "listed file.", "Never edit, round, filter, summarize or reorder records. If a call fails with a size "
         "limit or the output is cut, re-run `plan` with a smaller `--chunk-days`.", ""]
    L += ["| # | pull_id | file | fields |", "|---|---|---|---|"]
    for i, c in enumerate(p["calls"], 1):
        L.append(f"| {i} | {c['pull_id']} | `{c['file']}` | {len(c['arguments']['fields'])} |")
    return "\n".join(L) + "\n"


def plan(out: Path, account: str, date_from: str, date_to: str, snapshot_date: str, chunk_days: int = 0,
         pulls: list[str] | None = None) -> int:
    """Write plan.json + plan.md into out (created) and an empty raw/ folder.

    Rules:   Exit 2 with an English message on invalid arguments; never overwrites an existing plan.json.
    """
    try:
        p = make_plan(account, date_from, date_to, snapshot_date, chunk_days, pulls)
    except IntakeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if (out / "plan.json").exists():
        print(f"ERROR: {out / 'plan.json'} already exists; use a new folder", file=sys.stderr)
        return 2
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(p, indent=1) + "\n", encoding="utf-8")
    (out / "plan.md").write_text(_plan_md(p), encoding="utf-8")
    print(f"plan: {len(p['calls'])} get_data calls → {out / 'plan.json'} (save results under {out / 'raw'})")
    return 0


# ----------------------------------------------------------------------------- cell conversion


def _dec(x: float) -> str:
    s = repr(float(x))
    if "e" in s or "E" in s:
        s = f"{x:.10f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _num(v, where: str) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise IntakeError(f"{where}: boolean where a number was expected")
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        raise IntakeError(f"{where}: not a plain number") from None


def _items(v, where: str, key_order=("text", "topic")) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, str):
        s = v.strip()
        if not s.startswith("["):
            raise IntakeError(f"{where}: list field arrived as plain text; its separator is unknown")
        try:
            v = json.loads(s)
        except ValueError:
            raise IntakeError(f"{where}: list field is not valid JSON") from None
    if not isinstance(v, list):
        raise IntakeError(f"{where}: expected a list, got {type(v).__name__}")
    out = []
    for it in v:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict) and any(isinstance(it.get(k), str) for k in key_order):
            out.append(next(it[k] for k in key_order if isinstance(it.get(k), str)))
        else:
            raise IntakeError(f"{where}: list item of unexpected shape ({type(it).__name__})")
    return [s for s in (x.strip() for x in out) if s]


def convert(v, kind: str, where: str) -> str:
    """One Windsor cell → normalized text ('' = unknown).

    Rules:   Never guesses: unexpected shapes raise IntakeError naming the pull/field. int must be integral;
             rates stay fractions and censored API values (0.0999/0.9001) are kept verbatim for aggregation;
             tokens must be UPPER_SNAKE (UNKNOWN/UNSPECIFIED → ''); rid keeps the trailing numeric ID.
    """
    if kind in ("int", "number", "money", "rate"):
        f = _num(v, where)
        if f is None:
            return ""
        if kind == "int":
            if f != int(f) or f < 0:
                raise IntakeError(f"{where}: expected a non-negative integer")
            return str(int(f))
        if kind == "rate" and not 0 <= f <= 1:
            raise IntakeError(f"{where}: share outside 0–1 (expected a fraction)")
        return _dec(f)
    if v is None:
        return ""
    if kind == "bool":
        s = str(v).strip().lower()
        if s in ("true", "1"):
            return "true"
        if s in ("false", "0"):
            return "false"
        if s == "":
            return ""
        raise IntakeError(f"{where}: not a boolean")
    if kind in ("list", "urls"):
        if kind == "urls" and isinstance(v, str) and not v.strip().startswith("["):
            s = v.strip()
            if s and (" " in s or not re.match(r"^https?://", s)):
                raise IntakeError(f"{where}: URL field is not a single URL or a JSON list")
            return s
        return " | ".join(_items(v, where))
    s = str(v).strip()
    if s == "":
        return ""
    if kind == "account":
        if not _ACCOUNT.match(s):
            raise IntakeError(f"{where}: not a Google Ads customer ID")
        return s
    if kind == "id":
        if not _ID.match(s):
            raise IntakeError(f"{where}: ID is not a plain integer string")
        return s
    if kind == "rid":
        m = _RID.match(s)
        if not m:
            raise IntakeError(f"{where}: not a numeric ID or Google Ads resource name")
        return m.group(1)
    if kind == "date":
        m = _DATE.match(s)
        if not m:
            raise IntakeError(f"{where}: not a YYYY-MM-DD date")
        return m.group(1)
    if kind == "token" or kind.startswith("enum:"):
        if s in _EMPTY_TOKENS:
            return ""
        if not _TOKEN.match(s):
            raise IntakeError(f"{where}: not a Google Ads API enum token")
        if kind.startswith("enum:"):
            vocab = VOCAB[kind[5:]]
            if s not in vocab:
                raise IntakeError(f"{where}: {s} outside {sorted(vocab)}")
            if isinstance(vocab, dict):
                return vocab[s]
        return s
    return s  # text


# ----------------------------------------------------------------------------- normalize


def _load_raw(path: Path, call: dict) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise IntakeError(f"{call['pull_id']}: saved result {path} is missing (or pass --skip {call['pull']})") \
            from None
    except ValueError:
        raise IntakeError(f"{call['pull_id']}: {path.name} is not valid JSON (truncated tool output?) — re-pull "
                          "with a smaller --chunk-days") from None
    if not isinstance(data, dict) or data.get("schema") != RAW_SCHEMA:
        raise IntakeError(f"{call['pull_id']}: {path.name} lacks the {RAW_SCHEMA} wrapper")
    if data.get("pull_id") != call["pull_id"] or data.get("arguments") != call["arguments"]:
        raise IntakeError(f"{call['pull_id']}: saved pull_id/arguments differ from plan.json — re-run the call "
                          "exactly as planned")
    recs = data.get("records")
    if not isinstance(recs, list) or not all(isinstance(r, dict) for r in recs):
        raise IntakeError(f"{call['pull_id']}: records must be the get_data list of objects")
    fields = call["arguments"]["fields"]
    missing = sorted({f for r in recs for f in fields if f not in r})
    if missing:
        raise IntakeError(f"{call['pull_id']}: requested fields not returned by Windsor: {missing}")
    return recs


def _norm_acc(s: str) -> str:
    return s.replace("-", "")


def _convert_rows(call: dict, recs: list[dict], account: str, stats: dict) -> list[dict]:
    spec = PULLS[call["pull"]]
    rows = []
    for i, r in enumerate(recs):
        o = {}
        for fid, col, kind in spec["fields"]:
            o[col] = convert(r.get(fid), kind, f"{call['pull_id']} record {i + 1} field {fid}")
        if _norm_acc(o["customer_id"]) != _norm_acc(account):
            raise IntakeError(f"{call['pull_id']} record {i + 1}: account {o['customer_id'] or '(empty)'} is not "
                              f"the plan account {account} — one account per intake")
        rows.append(o)
    return rows


def _share_aggregate(days: list[dict], window_days: int, search_only: bool | None) -> dict:
    """Period shares from daily rows.

    Rules:   API value copied only for a 1-day window. Multi-day: eligible-weighted (elig_d = impr_d / IS_d) ONLY
             when the campaign is proven Search-only (channel SEARCH, partners and Display off — otherwise
             impressions include traffic IS does not describe) AND a row exists for every day of the window;
             any censored (0.0999 / 0.9001), zero or missing share → withheld. No shares at all → ''.
    """
    out = {}
    share_cols = ("search_impression_share", "search_budget_lost_is", "search_rank_lost_is")
    if all(d[c] == "" for d in days for c in share_cols):
        return {c: "" for c in share_cols}
    held = {c: WITHHELD for c in share_cols}
    if window_days == 1 and len(days) == 1:
        d = days[0]
        low = {"search_impression_share": CENSORED_LOW}
        return {c: WITHHELD if d[c] == "" or float(d[c]) == low.get(c, CENSORED_HIGH) else d[c] for c in share_cols}
    if search_only is not True or len({d["date"] for d in days}) != window_days:
        return held
    elig, impr_sum, withheld = [], 0, False
    for d in days:
        imp, share = int(d["impressions"] or 0), d["search_impression_share"]
        if share == "" or float(share) == CENSORED_LOW or float(share) == 0:
            withheld = True
            break
        elig.append((d, imp / float(share)))
        impr_sum += imp
    total = sum(e for _, e in elig)
    if withheld or total <= 0:
        return {c: WITHHELD for c in ("search_impression_share", "search_budget_lost_is", "search_rank_lost_is")}
    out["search_impression_share"] = _dec(impr_sum / total)
    for c in ("search_budget_lost_is", "search_rank_lost_is"):
        vals = [(e, d[c]) for d, e in elig]
        if any(v == "" or float(v) == CENSORED_HIGH for _, v in vals):
            out[c] = WITHHELD
        else:
            out[c] = _dec(sum(e * float(v) for e, v in vals) / total)
    return out


def _sum_into(acc: dict, row: dict) -> None:
    for c in SUM_COLS:
        if c not in row:
            continue
        a, b = acc.get(c, ""), row[c]
        if b == "":
            continue
        tot = (Decimal(a) if a != "" else Decimal(0)) + Decimal(b)
        s = format(tot, "f")
        acc[c] = s.rstrip("0").rstrip(".") if "." in s else s


def _build_tables(plan_d: dict, pulled: dict[str, list[list[dict]]], stats: dict) -> dict[str, list[dict]]:
    """Route converted pull rows to output tables. Rules: duplicate keys inside one pull file are refused."""
    tables: dict[str, list[dict]] = {}
    for name, chunks in pulled.items():
        spec = PULLS[name]
        key = spec.get("key")
        for rows in chunks:
            if key and spec["grain"] != "daily":
                seen = set()
                for r in rows:
                    k = tuple(r.get(c, "") for c in key)
                    if k in seen:
                        raise IntakeError(f"{name}: duplicate key {dict(zip(key, k))} inside one pull — unexpected "
                                          "Windsor grain; nothing was written")
                    seen.add(k)
    if "campaigns" in pulled:
        rows = [r for ch in pulled["campaigns"] for r in ch]
        nd = 0
        for r in rows:
            daily = r["budget_period"] == "DAILY"
            nd += (not daily) and r["budget_amount"] != ""
            r["daily_budget"] = r["budget_amount"] if daily else ""
        stats["non_daily_budgets"] = nd
        tables["campaigns"] = rows
    for name in ("ad_groups", "ads", "conversion_actions"):
        if name in pulled:
            tables[name] = [r for ch in pulled[name] for r in ch]
    negs = []
    if "keywords" in pulled:
        kws, dropped = [], 0
        for r in (r for ch in pulled["keywords"] for r in ch):
            if not r["text"]:
                dropped += 1
            elif r["negative"] == "true":
                negs.append({"text": r["text"], "match_type": r["match_type"], "level": "ad_group",
                             "campaign_id": r["campaign_id"], "ad_group_id": r["ad_group_id"],
                             "customer_id": r["customer_id"]})
            else:
                kws.append(r)
        stats["non_keyword_criteria_dropped"] = dropped
        tables["keywords"] = kws
    if "campaign_negatives" in pulled:
        for r in (r for ch in pulled["campaign_negatives"] for r in ch):
            if r["text"] and r["negative"] == "true":
                negs.append({"text": r["text"], "match_type": r["match_type"], "level": "campaign",
                             "campaign_id": r["campaign_id"], "ad_group_id": "", "customer_id": r["customer_id"]})
    if "keywords" in pulled or "campaign_negatives" in pulled:
        tables["negative_keywords"] = negs
    if "campaign_metrics" in pulled:
        by: dict[str, list[dict]] = {}
        seen = set()
        for r in (r for ch in pulled["campaign_metrics"] for r in ch):
            k = (r["campaign_id"], r["date"])
            if k in seen:
                raise IntakeError(f"campaign_metrics: duplicate campaign-day {k} (overlapping chunks?)")
            seen.add(k)
            by.setdefault(r["campaign_id"], []).append(r)
        window_days = (date.fromisoformat(plan_d["date_to"]) - date.fromisoformat(plan_d["date_from"])).days + 1
        search_only = {r["id"]: r["channel_type"] == "SEARCH" and r["search_partners"] == "false"
                       and r["display_network"] == "false"
                       for r in (r for ch in pulled.get("campaigns", []) for r in ch)}
        out = []
        for cid, days in sorted(by.items()):
            acc = {"campaign_id": cid, "customer_id": days[0]["customer_id"]}
            for d in days:
                _sum_into(acc, d)
            acc.update(_share_aggregate(days, window_days, search_only.get(cid)))
            out.append(acc)
        stats["withheld_share_campaigns"] = sum(1 for r in out if r.get("search_budget_lost_is") == WITHHELD
                                                or r.get("search_impression_share") == WITHHELD)
        tables["campaign_metrics"] = out
    for name, drop_empty_text in (("keyword_metrics", True), ("ad_metrics", False)):
        if name not in pulled:
            continue
        key = PULLS[name]["key"]
        agg: dict[tuple, dict] = {}
        dropped = 0
        for r in (r for ch in pulled[name] for r in ch):
            if drop_empty_text and not r.get("text"):
                dropped += 1
                continue
            k = tuple(r.get(c, "") for c in key)
            if k not in agg:
                agg[k] = {c: v for c, v in r.items() if c not in SUM_COLS}
                agg[k]["_qs"] = {r.get("quality_score", "")}
            else:
                agg[k]["_qs"].add(r.get("quality_score", ""))
            _sum_into(agg[k], r)
        rows = []
        for k, v in agg.items():
            qs = v.pop("_qs") - {""}
            if name == "keyword_metrics":
                v["quality_score"] = qs.pop() if len(qs) == 1 else ""
            rows.append(v)
        if drop_empty_text:
            stats[f"{name}_non_keyword_rows_dropped"] = dropped
        tables[name] = rows
    return tables


def _csv_text(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([r.get(c, "") for c in columns])
    return buf.getvalue()


_EMAIL_LIKE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE_LIKE = re.compile(r"(?:\+|\b00)?\d(?:[\s().-]?\d){7,}")  # 8+ digits, separators allowed: local numbers too
_NUMERIC_COLS = frozenset(SUM_COLS) | {  # skill-173 metric/segment semantics (METRICS, SHARE, SEGMENTS)
    "all_conversions", "all_conversion_value", "interactions", "conversions_by_conv_time",
    "conversion_value_by_conv_time", "date", "device", "network", "search_impression_share", "search_budget_lost_is",
    "search_rank_lost_is", "top_impression_rate", "abs_top_impression_rate", "search_top_is", "search_abs_top_is"}


def _personal_like(row: dict) -> bool:
    """True when any text cell (every column except *_id and known metric/segment columns — so a bare number in
    search_term counts) looks like an email or holds 8+ digits."""
    return any(v and not k.endswith("_id") and k not in _NUMERIC_COLS
               and (_EMAIL_LIKE.search(v) or _PHONE_LIKE.search(v)) for k, v in row.items() if isinstance(v, str))


def _import_search_terms(src: Path, account: dict, p: dict) -> tuple[str, dict, int]:
    """search_terms.csv + its manifest row from a skill-173 export folder, re-checked locally for personal data.

    Rules:   Refuses (IntakeError) unless src holds account.csv, search_terms.csv and table_manifest.csv written by
             the skill-173 intake (account manifest note), for the same customer (dashes ignored) and currency, the
             same date_range_start/end as the plan, money_unit currency, and a conversion_date_basis that is empty
             (unknown) or interaction_date. Provenance is not trusted for privacy: a row whose ANY text cell
             (search_term, matched_keyword, …; not *_id columns or plain numbers) holds an email-like string or 8+
             digits (local phone formats included; long product codes too, by design) is DROPPED whole — never left
             with an empty query that recipes would report — and counted; cells are never printed. Metrics are not
             recomputed; the caller declares the table partial when rows were dropped.
    """
    def rows(name: str) -> list[dict]:
        try:
            with open(src / name, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        except OSError:
            raise IntakeError(f"--search-terms-from: {src / name} missing (expects a skill-173 apply output "
                              "folder)") from None
    a173, man = rows("account.csv"), rows("table_manifest.csv")
    text = (src / "search_terms.csv").read_text(encoding="utf-8") if (src / "search_terms.csv").exists() else None
    if text is None:
        raise IntakeError(f"--search-terms-from: {src / 'search_terms.csv'} missing")
    acc_row = next((m for m in man if m.get("filename") == "account.csv"), {})
    st_row = next((m for m in man if m.get("filename") == "search_terms.csv"), None)
    if "skill-173" not in (acc_row.get("notes") or "") or st_row is None or len(a173) != 1:
        raise IntakeError("--search-terms-from: not a skill-173 export (account/manifest provenance missing)")
    a = a173[0]
    problems = []
    if _norm_acc(a.get("customer_id") or "") != _norm_acc(account["customer_id"]):
        problems.append("customer ID differs")
    if (a.get("currency_code") or "") != account["currency_code"]:
        problems.append("currency differs")
    if (a.get("date_range_start"), a.get("date_range_end")) != (p["date_from"], p["date_to"]):
        problems.append(f"window {a.get('date_range_start')} → {a.get('date_range_end')} differs from the plan "
                        f"{p['date_from']} → {p['date_to']}")
    if (a.get("money_unit") or "") != "currency":
        problems.append("money_unit is not currency")
    if (a.get("conversion_date_basis") or "") not in ("", "interaction_date"):
        problems.append("conversion date basis differs (interaction_date here)")
    if problems:
        raise IntakeError("--search-terms-from: " + "; ".join(problems))
    with open(src / "search_terms.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, st_rows = list(reader.fieldnames or []), list(reader)
    if "search_term" not in header:
        raise IntakeError("--search-terms-from: search_terms.csv has no search_term column")
    kept = [r for r in st_rows if not _personal_like(r)]
    dropped = len(st_rows) - len(kept)
    return (_csv_text(header, kept) if dropped else text), st_row, dropped


def normalize(plan_path: Path, raw_dir: Path | None, out: Path, conversion_lag_days: str,
              skip: tuple[str, ...] = (), search_terms_from: Path | None = None) -> int:
    """Validate saved get_data results against plan.json and write the normalized export.

    Rules:   Refuses (exit 2, writes nothing) on: unreadable/foreign plan, out not empty, missing raw file for a
             pull not listed in skip, argument drift, missing fields, invalid cells, foreign account, more than one
             account/currency, duplicate keys, invalid conversion_lag_days (int >= 0 or 'unknown'). Writes normalized
             CSVs, account.csv, table_manifest.csv and intake_report.md. conversion_date_basis is interaction_date
             (metrics.conversions; the by-conversion-date variant is a separate API metric). search_terms_from
             imports a skill-173 search_terms.csv per _import_search_terms (local email/phone re-check; refusal
             writes nothing).
    """
    try:
        p = json.loads(plan_path.read_text(encoding="utf-8"))
        if p.get("schema") != PLAN_SCHEMA:
            raise ValueError
    except (OSError, ValueError):
        print(f"REFUSED: {plan_path} is not a {PLAN_SCHEMA} plan", file=sys.stderr)
        return 2
    if out.exists() and any(out.iterdir()):
        print(f"REFUSED: the output folder {out} is not empty", file=sys.stderr)
        return 2
    lag = conversion_lag_days.strip().lower()
    if lag != "unknown" and not (lag.isdigit()):
        print("REFUSED: --conversion-lag-days must be a whole number of days or 'unknown'", file=sys.stderr)
        return 2
    raw_dir = raw_dir or plan_path.parent
    bad_skip = [s for s in skip if s not in PULLS]
    if bad_skip:
        print(f"REFUSED: unknown --skip {bad_skip}", file=sys.stderr)
        return 2
    stats: dict = {}
    pulled: dict[str, list[list[dict]]] = {}
    sources: dict[str, list[str]] = {}
    try:
        for call in p["calls"]:
            if call["pull"] in skip:
                continue
            recs = _load_raw(raw_dir / call["file"], call)
            rows = _convert_rows(call, recs, p["account"], stats)
            pulled.setdefault(call["pull"], []).append(rows)
            sources.setdefault(call["pull"], []).append(call["pull_id"])
        if "account" not in pulled:
            raise IntakeError("the account pull is required (currency and time zone)")
        acc_rows = {tuple(sorted(r.items())) for ch in pulled["account"] for r in ch}
        if len(acc_rows) != 1:
            raise IntakeError(f"account pull returned {len(acc_rows)} distinct rows; expected exactly one "
                              "(one account, one currency)")
        account = dict(next(iter(acc_rows)))
        if not account["currency_code"] or not account["time_zone"]:
            raise IntakeError("account pull lacks currency_code or time_zone")
        tables = _build_tables(p, {k: v for k, v in pulled.items() if k != "account"}, stats)
        imported = _import_search_terms(search_terms_from, account, p) if search_terms_from else None
    except IntakeError as e:
        print(f"REFUSED — to fix:\n  - {e}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    _write_outputs(out, p, account, tables, sources, stats, "" if lag == "unknown" else lag, imported)
    print(f"normalize: {len(tables)} tables + account.csv + table_manifest.csv → {out}")
    return 0


def _write_outputs(out: Path, p: dict, account: dict, tables: dict, sources: dict, stats: dict, lag: str,
                   imported: tuple[str, dict, int] | None = None) -> None:
    acc = {"customer_id": account["customer_id"], "name": account["name"], "currency_code": account["currency_code"],
           "time_zone": account["time_zone"], "auto_tagging": account["auto_tagging"],
           "date_range_start": p["date_from"], "date_range_end": p["date_to"], "snapshot_date": p["snapshot_date"],
           "rates_format": "fraction", "money_unit": "currency", "conversion_date_basis": "interaction_date",
           "conversion_lag_days": lag}
    (out / "account.csv").write_text(_csv_text(list(acc), [acc]), encoding="utf-8")
    src = f"Windsor.ai MCP get_data (connector {CONNECTOR}, read-only)"
    man_cols = ["filename", "source", "source_files", "exported_at", "period_start", "period_end", "timezone",
                "period_kind", "row_grain", "columns", "row_count", "completeness", "filters", "truncation",
                "conversion_date_basis", "notes"]
    man = [{"filename": "account.csv", "source": src, "source_files": "account", "exported_at": p["snapshot_date"],
            "period_start": p["date_from"], "period_end": p["date_to"], "timezone": account["time_zone"],
            "period_kind": "account_settings", "row_grain": "customer_id", "columns": ";".join(acc), "row_count": "1",
            "completeness": "complete", "filters": "none", "truncation": "none",
            "conversion_date_basis": "interaction_date", "notes": "window and snapshot from plan.json"}]
    pull_of = {"campaigns": ["campaigns"], "campaign_metrics": ["campaign_metrics"], "ad_groups": ["ad_groups"],
               "keywords": ["keywords"], "keyword_metrics": ["keyword_metrics"], "ads": ["ads"],
               "ad_metrics": ["ad_metrics"],
               "negative_keywords": ["keywords", "campaign_negatives"], "conversion_actions": ["conversion_actions"]}
    for table, rows in sorted(tables.items()):
        fn = f"{table}.csv"
        (out / fn).write_text(_csv_text(OUTPUT_COLUMNS[table], rows), encoding="utf-8")
        snap = table in SNAPSHOT_TABLES
        files = [pid for pl in pull_of[table] for pid in sources.get(pl, [])]
        notes = ["money in currency units", "rates as fractions"]
        if table == "campaign_metrics":
            notes.append("aggregated here from daily rows; shares eligible-weighted, censored/unknown → withheld")
        if not snap:
            notes.append("rows only for entities returned by Windsor; zero-activity rows not materialized")
        completeness = PARTIAL_NOTES.get(table, "complete")
        if table == "negative_keywords" and "keywords" in sources and "campaign_negatives" not in sources:
            completeness = "partial — ad-group negatives only"
        man.append({"filename": fn, "source": src, "source_files": "; ".join(files), "exported_at": p["snapshot_date"],
                    "period_start": p["snapshot_date"] if snap else p["date_from"],
                    "period_end": p["snapshot_date"] if snap else p["date_to"], "timezone": account["time_zone"],
                    "period_kind": "configuration_snapshot" if snap else "aggregate_report",
                    "row_grain": ";".join(TABLE_GRAIN[table]), "columns": ";".join(OUTPUT_COLUMNS[table]),
                    "row_count": str(len(rows)), "completeness": completeness, "filters": "none", "truncation": "none",
                    "conversion_date_basis": "not_applicable" if snap else "interaction_date",
                    "notes": "; ".join(notes)})
    if imported:
        text, row, dropped = imported
        stats["search_terms_rows_dropped_personal_like"] = dropped
        (out / "search_terms.csv").write_text(text, encoding="utf-8")
        rec = {c: row.get(c, "") for c in man_cols}
        rec["row_count"] = str(len(list(csv.DictReader(io.StringIO(text)))))
        if dropped:
            rec["completeness"] = f"partial — {dropped} row(s) with email/phone-like text dropped locally"
        rec["notes"] = "; ".join(x for x in (row.get("notes"), "imported from a skill-173 export; "
                                             f"{dropped} row(s) with email/phone-like text dropped locally") if x)
        man.append(rec)
    man.append({"filename": "table_manifest.csv", "source": f"{SKILL} normalize", "source_files": "",
                "exported_at": p["snapshot_date"], "period_start": p["snapshot_date"], "period_end": p["snapshot_date"],
                "timezone": account["time_zone"], "period_kind": "provenance", "row_grain": "filename",
                "columns": ";".join(man_cols), "row_count": str(len(man) + 1), "completeness": "complete",
                "filters": "none", "truncation": "none", "conversion_date_basis": "not_applicable",
                "notes": "one row per exported file"})
    (out / "table_manifest.csv").write_text(_csv_text(man_cols, man), encoding="utf-8")
    L = ["# Windsor intake report — normalized export", "",
         f"Account {acc['customer_id']} · currency {acc['currency_code']} · time zone {acc['time_zone']} · window "
         f"{acc['date_range_start']} → {acc['date_range_end']} · snapshot {acc['snapshot_date']} · conversion lag "
         f"{lag or 'unknown'}.", "", "| table | rows | completeness |", "|---|---|---|"]
    L += [f"| {m['filename']} | {m['row_count']} | {m['completeness']} |" for m in man[1:-1]]
    L += ["", "Counts: " + (", ".join(f"{k} {v}" for k, v in sorted(stats.items())) or "none") + ".", "",
          "Not pulled by this intake (request per recipe): search terms (only via --search-terms-from a skill-173 "
          "export), budgets, bidding strategies, bid adjustments, audiences, assets, shared negative lists, "
          "ad-group metrics, custom/ and external/ tables.",
          "Next: `check.py run --export <this folder>` for join readiness, then the audit recipes."]
    (out / "intake_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- readiness (run)

JOINS = [  # (check id, child table, child cols, parent table, parent cols, what)
    ("join_ad_groups", "ad_groups", ["campaign_id"], "campaigns", ["id"], "ad group → campaign"),
    ("join_campaign_metrics", "campaign_metrics", ["campaign_id"], "campaigns", ["id"], "campaign metrics → campaign"),
    ("join_keywords", "keywords", ["ad_group_id"], "ad_groups", ["id"], "keyword → ad group"),
    ("join_keyword_metrics", "keyword_metrics", ["ad_group_id", "keyword_id"], "keywords", ["ad_group_id", "id"],
     "keyword metrics → keyword"),
    ("join_ad_metrics", "ad_metrics", ["ad_group_id", "ad_id"], "ads", ["ad_group_id", "id"], "ad metrics → ad"),
    ("join_search_terms", "search_terms", ["ad_group_id"], "ad_groups", ["id"], "search term → ad group"),
]


def run(ctx) -> None:
    """Join readiness of a normalized export: every metric/child key must exist in its parent inventory.

    Rules:   One check per JOINS row (needs = child and parent key columns); orphan child rows are one Warning
             per child table with counts and up to 5 example keys; parent rows without child rows are only
             observed (zero activity or omitted rows are indistinguishable). campaign_metrics withheld shares
             are observed, not findings. Missing tables/columns are coverage (skipped). Never Critical.
    """
    for cid, child, ccols, parent, pcols, what in JOINS:
        c = ctx.check(cid, f"Join readiness: {what}", {child: ccols, parent: pcols})
        if not c.runnable:
            continue
        pk = {tuple(str(r.get(x) or "") for x in pcols) for r in ctx.rows(parent)}
        rows = ctx.rows(child)
        keys = [tuple(str(r.get(x) or "") for x in ccols) for r in rows]
        orphans = sorted({k for k in keys if all(k) and k not in pk})
        used = {k for k in keys}
        if orphans:
            c.finding("orphan_child_keys", "Warning", {"table": child, "parent": parent},
                      f"{child}: {len(orphans)} key(s) not found in {parent} — recipe joins drop these rows",
                      evidence={"orphan_keys": len(orphans), "examples": [list(k) for k in orphans[:5]],
                                "child_rows": len(rows), "parent_rows": len(pk)},
                      calculation={"numerator": len(orphans), "denominator": len(set(keys))},
                      recommendation="Re-pull the parent inventory for the same account and snapshot, then "
                                     "re-run normalize.",
                      uncertainty="The parent snapshot may be older/newer than the metrics window.")
        c.observe(f"{child} → {parent}: {len(set(keys))} distinct keys, {len(orphans)} orphan(s), "
                  f"{len(pk - used)} parent(s) without {child} rows", child_rows=len(rows), parent_rows=len(pk),
                  orphans=len(orphans), parents_without_children=len(pk - used))
    w = ctx.check("withheld_shares", "Campaign shares withheld after censoring",
                  {"campaign_metrics": ["campaign_id", "search_impression_share", "search_budget_lost_is"]})
    if w.runnable:
        rows = ctx.rows("campaign_metrics")
        held = [str(r.get("campaign_id")) for r in rows
                if WITHHELD in (str(r.get("search_impression_share") or ""), str(r.get("search_budget_lost_is") or ""))]
        w.observe(f"{len(held)} of {len(rows)} campaigns have withheld shares (censored or unknown days)",
                  campaigns=held[:20], total=len(rows))


# ----------------------------------------------------------------------------- CLI


def main(argv=None) -> int:
    """plan/normalize subcommands; everything else goes to the standard adsrun CLI (run/finalize).

    Rules:   `run` stays reachable through cli.main so lint, grader and RUNTIME.md usage are unchanged.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("plan", "normalize"):
        ap = argparse.ArgumentParser(prog=f"{SKILL} check.py")
        sub = ap.add_subparsers(dest="cmd", required=True)
        p = sub.add_parser("plan", help="write the Windsor MCP get_data plan")
        p.add_argument("--account", required=True, help="Google Ads customer ID, e.g. 123-456-7890")
        p.add_argument("--date-from", required=True)
        p.add_argument("--date-to", required=True, help="last complete day (account time zone)")
        p.add_argument("--snapshot-date", required=True, help="today's date, YYYY-MM-DD")
        p.add_argument("--chunk-days", type=int, default=0, help="split dated pulls into N-day windows")
        p.add_argument("--pull", action="append", default=[], help=f"subset of {list(PULLS)}")
        p.add_argument("--out", required=True, type=Path)
        q = sub.add_parser("normalize", help="validate saved get_data results and write the export")
        q.add_argument("--plan", required=True, type=Path)
        q.add_argument("--raw", type=Path, default=None, help="folder containing raw/ (default: the plan folder)")
        q.add_argument("--out", required=True, type=Path)
        q.add_argument("--conversion-lag-days", required=True, help="whole days or 'unknown'")
        q.add_argument("--skip", action="append", default=[], help="pull deliberately not fetched")
        q.add_argument("--search-terms-from", type=Path, default=None,
                       help="skill-173 export folder whose search_terms.csv is imported")
        a = ap.parse_args(argv)
        if a.cmd == "plan":
            return plan(a.out, a.account, a.date_from, a.date_to, a.snapshot_date, a.chunk_days, a.pull or None)
        return normalize(a.plan, a.raw, a.out, a.conversion_lag_days, tuple(a.skip), a.search_terms_from)
    return cli.main(SKILL, VERSION, run, None, argv)


if __name__ == "__main__":
    sys.exit(main())
