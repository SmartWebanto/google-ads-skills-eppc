"""params.py — Resolve PARAMETERS.md thresholds per currency, target and 30-day spend window.

exports: EUR_DEFAULTS | MONEY_PARAMS | SAMPLE_PARAMS | Resolved | Params
used_by: adsrun/context.py → Context.params; skill scripts/check.py via ctx.params.get()
rules:   Mirrors skills/_resources/PARAMETERS.md — change both together.
         Currency comes only from account.currency_code. Non-EUR money floors need
         profile.currency_floors for ALL six money params or explicit parameter_overrides; else unresolved.
         Target CPA precedence: campaign → linked portfolio (campaigns.bidding_strategy_id|strategy_id or
         bidding_strategies.campaign_ids membership) → profile campaign_objectives[id] →
         profile.target_cpa only when campaign_objectives is empty or campaign has no goal_ids conflict.
         Zero/negative/unknown targets are absent. target ROAS is NEVER used as a CPA substitute.
         30-day spend: exactly 30 complete days ending at the report end, from a daily table or a
         certified account total with matching dates; otherwise percent-based params are unresolved.
         Overrides are FINAL values (not floors); must be positive finite; sample params positive ints.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial resolver
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from . import values as V

EUR_DEFAULTS = {
    "spend_floor": 50.0,
    "spend_significant": 100.0,
    "spend_material": 200.0,
    "spend_high": 500.0,
    "monthly_spend_significant": 1000.0,
    "monthly_spend_large": 5000.0,
    "min_clicks": 100,
    "min_impressions": 1000,
    "min_conversions": 15,
}
MONEY_PARAMS = ("spend_floor", "spend_significant", "spend_material", "spend_high",
                "monthly_spend_significant", "monthly_spend_large")
SAMPLE_PARAMS = ("min_clicks", "min_impressions", "min_conversions")
_CPA_MULT = {"spend_floor": 1, "spend_significant": 2, "spend_material": 3, "spend_high": 5}
_PCT_30D = {"spend_high": 0.05, "monthly_spend_significant": 0.10, "monthly_spend_large": 0.25}
_DAILY_ALLOWED = {"date", "cost", "customer_id", "account_id", "campaign_id", "campaign_name",
                  "complete_day", "source_ref", "budget_id", "currency_code"}


@dataclass(frozen=True)
class Resolved:
    """A resolved parameter. Rules: value None means unresolved; 'reason' then names the blocker."""

    name: str
    value: float | int | None
    source: str
    reason: str = ""


class Params:
    def __init__(self, account: dict | None, profile: dict, evidence, report_end: date | None):
        self.account = account or {}
        self.profile = profile or {}
        self.ev = evidence
        self.report_end = report_end
        self.currency = (self.account.get("currency_code") or "").strip().upper() or None
        self.overrides = self.profile.get("parameter_overrides") or {}
        self.used: dict[str, Resolved] = {}
        self._spend30 = self._resolve_spend_30d()

    # ------------------------------------------------------------------ inputs
    def _resolve_spend_30d(self) -> tuple[float | None, str]:
        """Rules: manifest-complete, duplicate-free, complete-day daily rows only; else unresolved."""
        end = self.report_end
        if end is None:
            return None, "report end date unknown"
        start = end - timedelta(days=29)
        unit = self.account.get("money_unit") or "currency"
        daily = self.ev.get("custom/account_daily_spend") or self.ev.get("account_daily_spend")
        if daily is None:
            daily = self.ev.get("custom/campaign_daily") or self.ev.get("campaign_daily")
        if daily is not None and not daily.missing(["date", "cost"]):
            if daily.complete is not True:
                return None, f"{daily.filename}: manifest does not certify complete rows"
            segments = [c for c in daily.columns if c not in _DAILY_ALLOWED]
            if segments:
                return None, f"{daily.filename}: extra segment columns {segments} risk double counting"
            days: dict[date, float] = {}
            seen: set = set()
            for r in daily.rows:
                d = V.parse_date(r.get("date"))
                if d is None or not (start <= d <= end):
                    continue
                grain = (r.get("customer_id") or r.get("account_id"), r.get("campaign_id"), d)
                if grain in seen:
                    return None, f"{daily.filename}: duplicate rows at grain {grain[:2]} {d}"
                seen.add(grain)
                if "complete_day" in daily.columns and V.boolean(r.get("complete_day")) is not True:
                    return None, f"{daily.filename}: {d} not marked complete_day"
                c = V.money(r.get("cost"), unit)
                if c is None:
                    return None, f"{daily.filename}: unknown cost on {d}"
                days[d] = days.get(d, 0.0) + c
            if len(days) == 30:
                return sum(days.values()), f"{daily.filename} {start}..{end}"
            return None, f"{daily.filename} covers {len(days)} of 30 days {start}..{end}"
        total = V.money(self.account.get("spend_30d"), unit)
        s, e = V.parse_date(self.account.get("spend_30d_start")), V.parse_date(self.account.get("spend_30d_end"))
        if total is not None and s == start and e == end:
            return total, f"account.spend_30d certified {start}..{end}"
        return None, "no daily spend table or certified 30-day total for the exact window"

    def target_cpa(self, campaign_id=None) -> tuple[float | None, str]:
        """Resolve the applicable target CPA for a campaign (or account when None).

        Rules:   precedence in module rules; ROAS objectives return None with reason; zero/negative targets are absent.
        """
        def pos(v):
            """Positive number or None.

            Rules:   0 and negatives are treated as absent targets.
            """
            f = V.num(v)
            return f if f is not None and f > 0 else None

        cid = None if campaign_id is None else str(campaign_id)
        objectives = self.profile.get("campaign_objectives") or {}
        if cid is not None:
            camps = self.ev.get("campaigns")
            row = next((r for r in (camps.rows if camps else []) if str(r.get("id")) == cid), None)
            if row:
                t = pos(row.get("target_cpa"))
                if t:
                    return t, f"campaigns.target_cpa[{cid}]"
                sid = row.get("bidding_strategy_id") or row.get("strategy_id")
                strategies = self.ev.get("bidding_strategies")
                if strategies:
                    srow = next((r for r in strategies.rows if sid and str(r.get("id")) == str(sid)), None)
                    if srow is None:  # membership listed on the strategy side
                        srow = next((r for r in strategies.rows if cid in V.split_list(r.get("campaign_ids"), (";", "|", ","))), None)
                        sid = srow.get("id") if srow else sid
                    t = pos(srow.get("target_cpa")) if srow else None
                    if t:
                        return t, f"bidding_strategies.target_cpa[{sid}]"
            obj = objectives.get(cid) if isinstance(objectives, dict) else None
            if obj is None and isinstance(objectives, dict):
                obj = next((v for k, v in objectives.items() if str(k) == cid), None)
            if isinstance(obj, dict):
                t = pos(obj.get("target_cpa"))
                if t:
                    return t, f"profile.campaign_objectives[{cid}].target_cpa"
                if obj.get("target_roas") is not None:
                    return None, f"campaign {cid} has a ROAS objective; CPA not substitutable"
        t = pos(self.profile.get("target_cpa"))
        if t:
            goal_sets = {tuple(sorted(map(str, (v or {}).get("goal_ids") or []))) for v in objectives.values()} \
                if isinstance(objectives, dict) else set()
            if len(goal_sets) > 1:
                return None, "mixed-goal account: global target_cpa not inherited"
            return t, "profile.target_cpa"
        return None, "no applicable target CPA"

    # ------------------------------------------------------------------ resolve
    def get(self, name: str, campaign_id=None) -> Resolved:
        """Resolve one parameter; records it for the result header.

        Rules:   Returns Resolved(value=None, reason=...) instead of raising when unresolved.
        """
        key = f"{name}@{campaign_id}" if campaign_id is not None and name in _CPA_MULT else name
        if key in self.used:
            return self.used[key]
        res = self._resolve(name, campaign_id)
        self.used[key] = res
        return res

    def _resolve(self, name: str, campaign_id) -> Resolved:
        if name not in EUR_DEFAULTS:
            raise KeyError(f"unknown parameter {name}")
        if name in self.overrides:
            v = self.overrides[name]
            f = V.num(v)
            if f is None or not math.isfinite(f) or f <= 0:
                return Resolved(name, None, "override", f"invalid override {v!r}")
            if name in SAMPLE_PARAMS:
                if f != int(f):
                    return Resolved(name, None, "override", "sample override must be a positive integer")
                return Resolved(name, int(f), "profile.parameter_overrides")
            return Resolved(name, f, "profile.parameter_overrides")
        if name in SAMPLE_PARAMS:
            return Resolved(name, EUR_DEFAULTS[name], "PARAMETERS.md default")
        if self.currency is None:
            return Resolved(name, None, "", "account.currency_code unknown")
        if self.currency == "EUR":
            floor, fsrc = EUR_DEFAULTS[name], "EUR reference floor"
        else:
            floors = self.profile.get("currency_floors") or {}
            if not all(p in floors for p in MONEY_PARAMS):
                return Resolved(name, None, "", f"{self.currency} account needs currency_floors for all money parameters")
            floor, fsrc = V.num(floors[name]), f"profile.currency_floors ({self.currency})"
            if floor is None:
                return Resolved(name, None, "", f"currency_floors.{name} not numeric")
        candidates, parts = [floor], [f"{fsrc}={floor:g}"]
        if name in _CPA_MULT:
            cpa, csrc = self.target_cpa(campaign_id)
            if cpa is not None:
                candidates.append(_CPA_MULT[name] * cpa)
                parts.append(f"{_CPA_MULT[name]}x target CPA {cpa:g} ({csrc})")
        if name in _PCT_30D:
            spend, ssrc = self._spend30
            if spend is None:
                return Resolved(name, None, "", f"30-day account spend unresolved: {ssrc}")
            candidates.append(_PCT_30D[name] * spend)
            parts.append(f"{_PCT_30D[name]:.0%} of 30-day spend {spend:.2f} ({ssrc})")
        return Resolved(name, round(max(candidates), 2), "max(" + "; ".join(parts) + ")")

    def header(self) -> dict:
        """Resolved parameters for the result header.

        Rules:   unresolved values carry their reason; never filled with defaults.
        """
        return {k: {"value": r.value, "source": r.source, **({"unresolved": r.reason} if r.value is None else {})}
                for k, r in sorted(self.used.items())}
