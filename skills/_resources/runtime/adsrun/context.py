"""context.py — Per-run context: evidence, profile, account scope, maturity, parameters and coverage.

exports: RUNTIME_VERSION | ContextError | load_profile(path) -> dict | Context
used_by: adsrun/cli.py → run_skill; every skill scripts/check.py receives a Context
rules:   Deterministic: 'today' is never read from the clock; as_of = --as-of, profile.reporting_end_date,
         then account.date_range_end. Inputs are fingerprinted by content hash, never absolute paths.
         Conversion maturity: mature iff lag known and (snapshot - period_end) >= lag days; unknown lag →
         ctx.mature is None and performance-driven prescriptions MUST be skipped/partial by callers.
         ctx.check(needs=...) skips the check listing exact 'file:column' gaps — never guesses defaults.
         Profile values override nothing in the export except where CLIENT_PROFILE.md says so
         (lag, targets, reporting_end_date); currency always comes from account.currency_code.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial context
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | one account row per customer; tracking_verified needs verified_from
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from . import values as V
from .evidence import Evidence, Table, load_evidence
from .params import Params
from .result import Check, Result
from .yamlish import parse as parse_profile

RUNTIME_VERSION = "adsrun 1.0.0"


class ContextError(RuntimeError):
    """Fatal input problem (e.g. unreadable profile). Rules: message must name the file."""


def load_profile(path: Path | None) -> tuple[dict, str | None]:
    """Load a profile file and its sha256.

    Rules:   missing/invalid file raises ContextError naming it; None path → ({}, None), never a default profile.
    """
    if path is None:
        return {}, None
    if not path.is_file():
        raise ContextError(f"profile not found: {path}")
    raw = path.read_bytes()
    try:
        return parse_profile(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()
    except ValueError as e:
        raise ContextError(f"{path.name}: {e}") from e


def account_ids(evidence: Evidence) -> list[str]:
    """Distinct customer IDs in file order.

    Rules:   >1 id means callers MUST partition; never pick the first silently.
    """
    t = evidence.get("account")
    out: list[str] = []
    for r in (t.rows if t else []):
        cid = str(r.get("customer_id") or r.get("account_id") or "")
        if cid and cid not in out:
            out.append(cid)
    return out


def _partition(ev: Evidence, account_id: str) -> list[str]:
    """Keep only rows of one account. Rules: tables lacking an account key are dropped, not shared."""
    notes = []
    for key in list(ev.tables):
        t = ev.tables[key]
        col = "customer_id" if "customer_id" in t.columns else "account_id" if "account_id" in t.columns else None
        if col is None:
            if key != "table_manifest":
                del ev.tables[key]
                notes.append(f"{t.filename} has no customer_id column; excluded from account {account_id}")
            continue
        t.rows = [r for r in t.rows if str(r.get(col) or "") == account_id]
    return notes


class Context:
    def __init__(self, skill: str, script_version: str, export_dir: Path, profile_path: Path | None,
                 as_of: date | None = None, account_id: str | None = None):
        self.profile, profile_sha = load_profile(profile_path)
        self.evidence: Evidence = load_evidence(export_dir, self.profile.get("column_map"))
        self.result = Result(skill, script_version, RUNTIME_VERSION)
        self.skill = skill
        ids = account_ids(self.evidence)
        if account_id is not None:
            if account_id not in ids:
                raise ContextError(f"account {account_id} not in account table")
            if len(ids) > 1:
                self.result.errors.extend(_partition(self.evidence, account_id))
        elif len(ids) > 1:
            raise ContextError(f"multi-account export ({len(ids)} accounts): run per account (cli partitions automatically)")
        acct_table = self.evidence.get("account")
        if acct_table and len(acct_table.rows) > 1:
            raise ContextError(f"account table has {len(acct_table.rows)} rows for one account; supply exactly one row per customer_id")
        self.account: dict = dict(acct_table.rows[0]) if acct_table and acct_table.rows else {}
        a = self.account
        self.account_id = a.get("customer_id") or a.get("account_id")
        self.currency = (a.get("currency_code") or "").upper() or None
        self.money_unit = a.get("money_unit") or None
        self.rates_format = a.get("rates_format") or None
        self.period_start = V.parse_date(a.get("date_range_start"))
        self.period_end = V.parse_date(a.get("date_range_end"))
        self.snapshot = V.parse_date(a.get("snapshot_date"))
        self.as_of = as_of or V.parse_date(self.profile.get("reporting_end_date")) or self.period_end
        lag = self.profile.get("conversion_lag_days")
        if lag is None:
            lag = V.integer(a.get("conversion_lag_days"))
        self.lag_days = V.integer(lag) if lag is not None else None
        self.mature, self.maturity_note = self._maturity()
        self.params = Params(self.account, self.profile, self.evidence, self.period_end)
        self._reads: set[str] = set()
        r = self.result
        r.account_id = self.account_id
        r.period = [self.period_start, self.period_end]
        r.errors.extend(self.evidence.errors)
        r.inputs = {
            "profile_sha256": profile_sha,
            "files": {t.filename: {"sha256": t.sha256, "rows": len(t.rows)} for t in self.evidence.tables.values()},
        }
        r.scope = {
            "account_id": self.account_id,
            "account_name": a.get("name"),
            "currency": self.currency,
            "money_unit": self.money_unit,
            "rates_format": self.rates_format,
            "time_zone": a.get("time_zone"),
            "period": [self.period_start, self.period_end],
            "snapshot": self.snapshot,
            "as_of": self.as_of,
            "conversion_date_basis": a.get("conversion_date_basis"),
            "conversion_lag_days": self.lag_days,
            "maturity": {"mature": self.mature, "note": self.maturity_note},
            "manifest_present": self.evidence.get("table_manifest") is not None,
        }
        if not self.account:
            r.errors.append("account table missing: currency, time zone, period and units unknown")

    def _maturity(self) -> tuple[bool | None, str]:
        if self.lag_days is None:
            return None, "conversion lag unknown: descriptive totals only, no performance prescriptions"
        if self.period_end is None or self.snapshot is None:
            return None, "period end or snapshot unknown"
        gap = (self.snapshot - self.period_end).days
        if gap >= self.lag_days:
            return True, f"snapshot {gap}d after period end >= lag {self.lag_days}d"
        return False, f"snapshot only {gap}d after period end < lag {self.lag_days}d"

    # ------------------------------------------------------------------ evidence access
    def table(self, key: str) -> Table | None:
        """Return a table and record it as read.

        Rules:   None means the file was not supplied — callers report coverage, never treat as empty.
        """
        t = self.evidence.get(key)
        if t is not None:
            self._reads.add(t.filename)
        return t

    def rows(self, key: str) -> list[dict]:
        """Rows of a table or [].

        Rules:   [] does not distinguish missing from empty — use table()/ctx.check(needs=) for absence claims.
        """
        t = self.table(key)
        return t.rows if t else []

    def money(self, v) -> float | None:
        """Convert a money cell with the account unit.

        Rules:   the only micros conversion point; unknown → None, never 0.
        """
        return V.money(v, self.money_unit or "currency")

    def rate(self, v) -> float | None:
        """Convert a rate cell to a fraction with the account rates_format.

        Rules:   withheld/bounded cells → None.
        """
        return V.rate(v, self.rates_format or "fraction")

    def goal_ids(self, campaign_id) -> list[str]:
        """Declared goal ids of a campaign.

        Rules:   profile.campaign_objectives wins over campaigns.goal_ids; [] means unknown, never 'all goals'.
        """
        cid = str(campaign_id)
        objectives = self.profile.get("campaign_objectives") or {}
        obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
        if isinstance(obj, dict) and obj.get("goal_ids"):
            return [str(g) for g in obj["goal_ids"]]
        row = next((r for r in self.rows("campaigns") if str(r.get("id")) == cid), None)
        return V.split_list(row.get("goal_ids"), (";", "|", ",")) if row else []

    def tracking_for_campaign(self, campaign_id) -> tuple[bool | None, str]:
        """Is conversion tracking evidenced as working through period end for EVERY goal of this campaign?

        Rules:   Per goal, True only from (a) profile.tracking_verified[goal] = {status: verified,
                 verified_from <= period_start, verified_through >= period_end, source_ref} or (b) an ENABLED action mapped to the goal
                 (id, name or category) whose last_conversion_date is 0..max(lag, 7) days before period end.
                 A goal is False only when every mapped action is disabled/removed.
                 Campaign: any goal False → False; all goals True → True; otherwise None (unknown).
                 Free-text profile notes and account-wide conversions are NOT proof; future dates are ignored.
        """
        goals = self.goal_ids(campaign_id)
        if not goals:
            return None, f"campaign {campaign_id}: no declared goal_ids; tracking health unknown"
        if self.period_end is None:
            return None, "period end unknown"
        window = max(self.lag_days or 0, 7)
        verified = self.profile.get("tracking_verified") or {}
        actions = self.rows("conversion_actions")
        states, notes = [], []
        for g in goals:
            v = verified.get(g) if isinstance(verified, dict) else None
            if isinstance(v, dict) and str(v.get("status") or "").lower() == "verified" and v.get("source_ref"):
                through, since = V.parse_date(v.get("verified_through")), V.parse_date(v.get("verified_from"))
                if through and since and through >= self.period_end and (
                        self.period_start is None or since <= self.period_start):
                    states.append(True)
                    notes.append(f"{g}: verified {since}..{through} ({v.get('source_ref')})")
                    continue
            mapped = [a for a in actions if g.lower() in {str(a.get(k) or "").lower() for k in ("id", "name", "category")}]
            if not mapped:
                states.append(None)
                notes.append(f"{g}: no conversion action mapped")
                continue
            enabled = [a for a in mapped if str(a.get("status") or "").upper() == "ENABLED"]
            if not enabled:
                states.append(False)
                notes.append(f"{g}: all mapped actions disabled/removed")
                continue
            recent = None
            for a in sorted(enabled, key=lambda a: str(a.get("id"))):
                last = V.parse_date(a.get("last_conversion_date"))
                if last and 0 <= (self.period_end - last).days <= window:
                    recent = f"{g}: action {a.get('id')} last conversion {last}"
                    break
            states.append(True if recent else None)
            notes.append(recent or f"{g}: no conversion within {window}d before period end (outage or low volume undetermined)")
        state = False if False in states else True if all(x is True for x in states) else None
        return state, f"campaign {campaign_id}: " + "; ".join(notes)

    def check(self, check_id: str, title: str, needs: dict | None = None, *, applicable: bool = True,
              na_reason: str = "") -> Check:
        """Declare a check and verify its required tables/columns.

        Rules:   needs = {table_key: [columns]}; any gap → status skipped with 'table:column' list.
                 A table whose manifest says partial/truncated → status partial (still runnable).
        """
        c = self.result.check(check_id, title)
        if not applicable:
            return c.not_applicable(na_reason or "not applicable to this account")
        missing: list[str] = []
        for key, cols in (needs or {}).items():
            t = self.table(key)
            if t is None:
                missing.append(f"{key} (file)")
                continue
            missing += [f"{key}:{col}" for col in t.missing(cols)]
        if missing:
            return c.skip("required evidence missing", missing)
        for key in (needs or {}):
            t = self.table(key)
            if t.complete is False or t.truncated:
                c.partial(f"{t.filename}: manifest marks incomplete/truncated coverage")
            elif t.complete is None:
                c.partial(f"{t.filename}: no manifest completeness; absence findings not provable")
        return c

    def finish(self) -> dict:
        """Freeze parameters/reads into the result dict.

        Rules:   call once after run(); output is fingerprinted and must stay byte-stable.
        """
        self.result.parameters = self.params.header()
        self.result.inputs["read"] = sorted(self._reads)
        return self.result.as_dict()
