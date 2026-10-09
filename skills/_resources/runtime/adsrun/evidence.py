"""evidence.py — Load a local export folder (CSV/TSV/JSON/Markdown tables) with manifest provenance.

exports: Table | Evidence | load_evidence(root, column_map) -> Evidence | file_digest(path) -> str
used_by: adsrun/context.py → Context
rules:   Read-only. Never fetches, uploads or writes inside the export folder.
         Table keys are POSIX paths relative to the export root without extension
         ('campaigns', 'custom/budget_alert_daily'); duplicates across formats are an error.
         Empty cells load as None (unknown). A table with headers and zero rows is a KNOWN-EMPTY
         inventory only when its manifest row says it is complete — see Table.complete.
         column_map (profile) renames source → semantic columns explicitly; no fuzzy matching.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial loader
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SUFFIXES = (".csv", ".tsv", ".json", ".md")


def file_digest(path: Path) -> str:
    """sha256 of a file.

    Rules:   content-only; paths never enter fingerprints.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Table:
    """One evidence table. Rules: rows are dicts keyed by semantic column; values str|None or JSON scalars."""

    key: str
    filename: str
    columns: list[str]
    rows: list[dict]
    sha256: str
    manifest: dict | None = None

    def missing(self, columns) -> list[str]:
        """Columns absent from this table.

        Rules:   presence only — a present column may still hold unknown (None) cells.
        """
        return [c for c in columns if c not in self.columns]

    @property
    def complete(self) -> bool | None:
        """Manifest completeness.

        Rules:   None when no manifest row; words partial/incomplete/sample/truncated/top-n → False.
        """
        if not self.manifest:
            return None
        text = str(self.manifest.get("completeness") or "").lower()
        if not text:
            return None
        if any(w in text for w in ("partial", "incomplete", "sample", "truncated", "top-n", "top n")):
            return False
        return "complete" in text

    @property
    def truncated(self) -> bool:
        """Manifest truncation flag.

        Rules:   any value other than none/no/false/0 counts as truncated (e.g. 'visible terms only').
        """
        if not self.manifest:
            return False
        t = str(self.manifest.get("truncation") or "").strip().lower()
        return t not in ("", "none", "no", "false", "0")


@dataclass
class Evidence:
    root: Path
    tables: dict[str, Table] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def get(self, key: str) -> Table | None:
        """Table by key or None.

        Rules:   keys are export-relative paths without extension.
        """
        return self.tables.get(key)


def _read_rows(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        reader = csv.DictReader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ",")
        cols = [c.strip() for c in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            row = {}
            for k, v in raw.items():
                if k is None:
                    raise ValueError(f"{path.name}: row has more cells than headers")
                v = v.strip() if isinstance(v, str) else v
                row[k.strip()] = None if v == "" else v
            rows.append(row)
        return cols, rows
    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            data = data["rows"]
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError(f"{path.name}: JSON must be an object, a list of objects or {{'rows': [...]}}")
        cols: list[str] = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
        rows = [{c: (None if r.get(c) == "" else r.get(c)) for c in cols} for r in data]
        return cols, rows
    if suffix == ".md":
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
        if len(lines) < 2:
            raise ValueError(f"{path.name}: no Markdown table found")
        split = lambda l: [c.strip() for c in l.strip("|").split("|")]
        cols = split(lines[0])
        rows = []
        for l in lines[2:]:
            cells = split(l)
            if len(cells) != len(cols):
                raise ValueError(f"{path.name}: row width differs from header")
            rows.append({c: (None if v == "" else v) for c, v in zip(cols, cells)})
        return cols, rows
    raise ValueError(f"unsupported file type {path.name}")


def load_evidence(root: Path, column_map: dict | None = None) -> Evidence:
    """Load every supported table beneath root.

    Rules:   Unreadable files are recorded in Evidence.errors and skipped — dependent checks
             then report missing input instead of crashing the whole run.
             Manifest rows attach by filename (with or without subfolder).
    """
    ev = Evidence(root=root)
    column_map = column_map or {}
    if not root.is_dir():
        ev.errors.append(f"export folder not found: {root}")
        return ev
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES
                   and not any(part.startswith(".") or part == "__MACOSX" for part in p.relative_to(root).parts))
    for path in paths:
        rel = PurePosixPath(path.relative_to(root).as_posix())
        key = str(rel.with_suffix(""))
        if key in ev.tables:
            ev.errors.append(f"duplicate table {key}: {ev.tables[key].filename} and {rel}")
            continue
        try:
            cols, rows = _read_rows(path)
        except (ValueError, UnicodeDecodeError, csv.Error) as e:
            ev.errors.append(f"{rel}: {e}")
            continue
        mapping = column_map.get(key) or column_map.get(rel.name) or {}
        if mapping:
            reverse = {src: sem for sem, src in mapping.items()}
            cols = [reverse.get(c, c) for c in cols]
            rows = [{reverse.get(k, k): v for k, v in r.items()} for r in rows]
        ev.tables[key] = Table(key=key, filename=str(rel), columns=cols, rows=rows, sha256=file_digest(path))
    manifest = ev.tables.get("table_manifest")
    if manifest:
        by_name = {}
        for r in manifest.rows:
            fn = str(r.get("filename") or "").strip()
            if fn:
                by_name[fn] = r
                by_name[PurePosixPath(fn).name] = r
        for t in ev.tables.values():
            t.manifest = by_name.get(t.filename) or by_name.get(PurePosixPath(t.filename).name)
    return ev
