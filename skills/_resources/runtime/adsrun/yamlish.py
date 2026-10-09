"""yamlish.py — Parse client profiles written in JSON or the YAML subset used by CLIENT_PROFILE.md.

exports: parse(text) -> dict | ProfileSyntaxError
used_by: adsrun/context.py → load_profile
rules:   Standard library only: Claude Team containers may lack PyYAML and network access.
         Supported: comments, block maps/lists by indentation, flow [..] and {..}, quoted and plain scalars.
         Anchors, tags, multi-document streams and folded blocks are rejected, never guessed.
         null/~/empty are None; unknown stays None — callers must not coerce None to 0 or False.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial parser for Team-runnable checks
"""
from __future__ import annotations

import json
import re

_NUM_INT = re.compile(r"^[-+]?\d+$")
_NUM_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")


class ProfileSyntaxError(ValueError):
    """Raised with a line number when the profile is outside the supported subset."""


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _scalar(tok: str, lineno: int):
    v = tok.strip()
    if v in ("", "~", "null", "Null", "NULL"):
        return None
    if v in ("true", "True", "TRUE"):
        return True
    if v in ("false", "False", "FALSE"):
        return False
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else json.loads(v)
    if v[0] in "&*!|>":
        raise ProfileSyntaxError(f"line {lineno}: unsupported YAML feature {v[0]!r}")
    if _NUM_INT.match(v):
        return int(v)
    if _NUM_FLOAT.match(v):
        return float(v)
    return v


def _split_flow(body: str, lineno: int) -> list[str]:
    parts, depth, quote, cur = [], 0, None, []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if depth or quote:
        raise ProfileSyntaxError(f"line {lineno}: unbalanced flow collection")
    tail = "".join(cur)
    if tail.strip():
        parts.append(tail)
    return [p.strip() for p in parts]


def _split_key(item: str, lineno: int) -> tuple[str, str]:
    quote = None
    for i, ch in enumerate(item):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(item) or item[i + 1] in " \t"):
            key = item[:i].strip()
            if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                key = key[1:-1]
            return key, item[i + 1:].strip()
    raise ProfileSyntaxError(f"line {lineno}: expected 'key: value' in {item!r}")


def _value(tok: str, lineno: int):
    t = tok.strip()
    if t.startswith("["):
        if not t.endswith("]"):
            raise ProfileSyntaxError(f"line {lineno}: unterminated list")
        return [_value(p, lineno) for p in _split_flow(t[1:-1], lineno)]
    if t.startswith("{"):
        if not t.endswith("}"):
            raise ProfileSyntaxError(f"line {lineno}: unterminated map")
        out = {}
        for p in _split_flow(t[1:-1], lineno):
            k, v = _split_key(p, lineno)
            out[k] = _value(v, lineno)
        return out
    return _scalar(t, lineno)


def parse(text: str) -> dict:
    """Parse a profile document into plain dict/list/scalar values.

    Rules:   JSON documents are parsed with json first (scenario profiles are JSON).
             Duplicate keys raise — silently keeping the last value could hide a conflicting target.
             Returns {} for an empty document; top level MUST be a mapping.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return data
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.strip() in ("---", "..."):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ProfileSyntaxError(f"line {n}: tabs are not valid YAML indentation")
        line = _strip_comment(raw)
        if line.strip():
            lines.append((n, len(line) - len(line.lstrip(" ")), line.strip()))
    if not lines:
        return {}
    value, idx = _block(lines, 0, lines[0][1])
    if idx != len(lines):
        raise ProfileSyntaxError(f"line {lines[idx][0]}: unexpected indentation")
    if not isinstance(value, dict):
        raise ProfileSyntaxError("profile top level must be a mapping")
    return value


def _block(lines, idx, indent):
    n, ind, content = lines[idx]
    if content.startswith("- ") or content == "-":
        return _block_list(lines, idx, indent)
    return _block_map(lines, idx, indent)


def _block_map(lines, idx, indent):
    out: dict = {}
    while idx < len(lines):
        n, ind, content = lines[idx]
        if ind < indent:
            break
        if ind > indent:
            raise ProfileSyntaxError(f"line {n}: unexpected indentation")
        if content.startswith("- "):
            raise ProfileSyntaxError(f"line {n}: list item inside mapping")
        key, rest = _split_key(content, n)
        if key in out:
            raise ProfileSyntaxError(f"line {n}: duplicate key {key!r}")
        idx += 1
        if rest == "":
            if idx < len(lines) and lines[idx][1] > indent:
                out[key], idx = _block(lines, idx, lines[idx][1])
            elif idx < len(lines) and lines[idx][1] == indent and lines[idx][2].startswith("- "):
                out[key], idx = _block_list(lines, idx, indent)
            else:
                out[key] = None
        else:
            out[key] = _value(rest, n)
    return out, idx


def _block_list(lines, idx, indent):
    out: list = []
    while idx < len(lines):
        n, ind, content = lines[idx]
        if ind != indent or not (content.startswith("- ") or content == "-"):
            break
        item = content[1:].strip()
        idx += 1
        if item == "":
            if idx < len(lines) and lines[idx][1] > indent:
                val, idx = _block(lines, idx, lines[idx][1])
                out.append(val)
            else:
                out.append(None)
            continue
        if not item.startswith(("[", "{", "\"", "'")) and re.match(r"^[^:]+:(\s|$)", item):
            # "- key: value" opens an inline mapping whose further keys are indented by 2.
            key, rest = _split_key(item, n)
            first = {key: _value(rest, n) if rest else None}
            child_indent = indent + 2
            if idx < len(lines) and lines[idx][1] >= child_indent:
                more, idx = _block_map(lines, idx, lines[idx][1])
                for k, v in more.items():
                    if k in first:
                        raise ProfileSyntaxError(f"line {n}: duplicate key {k!r}")
                    first[k] = v
            out.append(first)
        else:
            out.append(_value(item, n))
    return out, idx
