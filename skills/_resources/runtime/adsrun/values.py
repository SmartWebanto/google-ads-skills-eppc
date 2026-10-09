"""values.py — Typed, unit-aware parsing of export cells without guessing missing values.

exports: MISSING_TOKENS | num(v) -> float|None | integer(v) -> int|None | money(v, unit) -> float|None
         rate(v, fmt) -> float|None | boolean(v) -> bool|None | parse_date(v) -> date|None
         split_list(v, seps) -> list[str] | ratio(num, den) -> float|None | norm_text(v) -> str
used_by: adsrun/evidence.py, adsrun/params.py, every skill scripts/check.py
rules:   None means unknown/unavailable — NEVER coerce to 0; zero is only a literal zero cell.
         Numbers accept '.' decimals and ',' thousands groups only; '1.234,5' is ambiguous → None.
         money(): micros are divided by 1e6 exactly once, here; callers never rescale again.
         rate(): 'percent' tables and cells ending with % are divided by 100; '< 10%' style
         bounded values return None (withheld), not the bound.
         ratio(): zero or unknown denominator → None (undefined), never 0 or infinity.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial typed parsing
"""
from __future__ import annotations

import re
from datetime import date

MISSING_TOKENS = {"", "--", "—", "n/a", "na", "null", "none", "unknown", "withheld", " --"}
_PLAIN = re.compile(r"^[-+]?(\d+(\.\d+)?|\.\d+)([eE][-+]?\d+)?$")
_GROUPED = re.compile(r"^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$")


def _clean(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    s = str(v).strip()
    return None if s.lower() in MISSING_TOKENS else s


def num(v) -> float | None:
    """Parse a plain number. Rules: unknown/ambiguous → None; bool is not a number."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = _clean(v)
    if s is None:
        return None
    s = s.replace("\u00a0", "").replace(" ", "")
    for sym in ("€", "EUR", "$", "£"):
        s = s.replace(sym, "")
    if _PLAIN.match(s):
        return float(s)
    if _GROUPED.match(s):
        return float(s.replace(",", ""))
    return None


def integer(v) -> int | None:
    """Integer or None.

    Rules:   non-integral numbers → None, never truncated.
    """
    f = num(v)
    return int(f) if f is not None and f == int(f) else None


def money(v, unit: str | None = "currency") -> float | None:
    """Rules: unit 'micros' divides by 1e6; unknown unit with a value → caller must treat as unresolved."""
    f = num(v)
    if f is None:
        return None
    if unit == "micros":
        return f / 1_000_000
    return f


def rate(v, fmt: str | None = "fraction") -> float | None:
    """Return a fraction (0.25 for 25%). Rules: see module rules; bounded '<'/'>' cells are withheld."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) / 100 if fmt == "percent" else float(v)
    s = _clean(v)
    if s is None or s[0] in "<>":
        return None
    if s.endswith("%"):
        f = num(s[:-1])
        return None if f is None else f / 100
    f = num(s)
    if f is None:
        return None
    return f / 100 if fmt == "percent" else f


def boolean(v) -> bool | None:
    """Parse true/false/yes/no/1/0.

    Rules:   anything else (e.g. 'enabled') → None.
    """
    if isinstance(v, bool):
        return v
    s = _clean(v)
    if s is None:
        return None
    s = s.lower()
    if s in ("true", "yes", "1", "y"):
        return True
    if s in ("false", "no", "0", "n"):
        return False
    return None


def parse_date(v) -> date | None:
    """ISO date or None.

    Rules:   only YYYY-MM-DD prefixes; locale dates → None.
    """
    s = _clean(v)
    if s is None:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def split_list(v, seps: tuple[str, ...] = (" | ", ";", "|")) -> list[str]:
    """Split a multi-value cell on the first separator present. Rules: empty/unknown → []."""
    s = _clean(v)
    if s is None:
        return []
    for sep in seps:
        if sep in s:
            return [p.strip() for p in s.split(sep) if p.strip()]
    return [s]


def ratio(numerator, denominator) -> float | None:
    """numerator/denominator.

    Rules:   zero or unknown denominator → None (undefined).
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def norm_text(v) -> str:
    """Lowercase, collapse whitespace.

    Rules:   punctuation retained; matching rules decide its meaning.
    """
    return " ".join(str(v or "").lower().split())
