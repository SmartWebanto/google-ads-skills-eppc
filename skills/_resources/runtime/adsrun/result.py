"""result.py — Deterministic result model: findings, observations, coverage and AI review items.

exports: SCHEMA | SEVERITIES | STATUSES | Finding | ReviewItem | Check | Result
used_by: adsrun/context.py, adsrun/cli.py, adsrun/finalize.py, every skill scripts/check.py
rules:   Severities are exactly Critical/Warning/Info (OUTPUT_TEMPLATES.md). No High tier here.
         Finding identity = sha1(skill, account, entity ids, condition_key, period) — dedupe key
         from ads/SKILL.md rule 10; two conditions on one entity stay distinct.
         Serialization is deterministic: sorted collections, rounded floats, no wall-clock values.
         A check never "passes" silently: every declared check ends completed/partial/skipped/not_applicable.
         ReviewItem outcomes map to severity|None; the AI chooses an outcome, never a free severity.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial result model
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | lossless duplicate-finding merge (_conflicts, _merged_summaries)
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

SCHEMA = "adsrun-result/1"
SEVERITIES = ("Critical", "Warning", "Info")
STATUSES = ("completed", "partial", "skipped", "not_applicable")


def _clean(v):
    """Round floats and normalize containers for byte-stable JSON."""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        r = round(v, 6)
        return int(r) if r == int(r) and abs(r) < 1e15 else r
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, set):
        return sorted(_clean(x) for x in v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _hash(*parts) -> str:
    return hashlib.sha1(json.dumps(_clean(list(parts)), sort_keys=True).encode()).hexdigest()[:12]


_META = ("_conflicts", "_merged_summaries")


def _merge_fields(win: dict, lose: dict) -> dict:
    """Union two evidence/calculation dicts. Rules: winner's value kept; all distinct values of a conflicting key
    (including earlier _conflicts on either side) are listed once, canonical-sorted, under _conflicts[key]."""
    merged = {k: v for k, v in win.items() if k not in _META}
    conflicts: dict = {}
    for side in (win, lose):
        for k, vals in (side.get("_conflicts") or {}).items():
            conflicts.setdefault(k, []).extend(vals)
    for k, v in lose.items():
        if k in _META:
            continue
        if k not in merged:
            merged[k] = v
        elif _clean(merged[k]) != _clean(v):
            conflicts.setdefault(k, []).extend([merged[k], v])
    out_conf = {}
    for k, vals in conflicts.items():
        uniq = {json.dumps(_clean(x), sort_keys=True): x for x in vals}
        if len(uniq) > 1:
            out_conf[k] = [uniq[key] for key in sorted(uniq)]
    if out_conf:
        merged["_conflicts"] = out_conf
    if "_merged_summaries" in win:
        merged["_merged_summaries"] = win["_merged_summaries"]
    return merged


@dataclass
class Finding:
    id: str
    check: str
    condition_key: str
    severity: str
    entity: dict
    summary: str
    evidence: dict = field(default_factory=dict)
    calculation: dict = field(default_factory=dict)
    recommendation: str = ""
    uncertainty: str = ""
    owner: str = ""
    origin: str = "deterministic"

    def as_dict(self) -> dict:
        """Serialize deterministically.

        Rules:   floats rounded via _clean; no wall-clock or path values.
        """
        return _clean(self.__dict__)


@dataclass
class ReviewItem:
    """Judgment the script cannot make. Rules: outcomes are closed; each maps to a severity or None."""

    id: str
    check: str
    condition_key: str
    entity: dict
    question: str
    evidence: dict
    outcomes: dict  # outcome -> {"severity": str|None, "recommendation": str}
    guidance: str = ""
    provisional_finding: str | None = None  # finding id replaced/removed once a decision is accepted

    def as_dict(self) -> dict:
        """Serialize deterministically.

        Rules:   floats rounded via _clean; no wall-clock or path values.
        """
        return _clean(self.__dict__)


class Check:
    """Coverage-tracked unit of work inside one skill run."""

    def __init__(self, result: "Result", check_id: str, title: str):
        self.result, self.id, self.title = result, check_id, title
        self.status: str | None = None
        self.missing: list[str] = []
        self.notes: list[str] = []

    @property
    def runnable(self) -> bool:
        """False once skipped/not_applicable.

        Rules:   callers MUST not emit findings from a non-runnable check.
        """
        return self.status not in ("skipped", "not_applicable")

    def skip(self, reason: str, missing=()) -> "Check":
        """Mark skipped with exact missing inputs.

        Rules:   skipped is never a pass and never a finding.
        """
        self.status = "skipped"
        self.missing += list(missing)
        self.notes.append(reason)
        return self

    def partial(self, reason: str, missing=()) -> "Check":
        """Mark partial (unless already skipped).

        Rules:   record why coverage is incomplete; absence findings need completed status.
        """
        if self.status != "skipped":
            self.status = "partial"
        self.missing += list(missing)
        self.notes.append(reason)
        return self

    def not_applicable(self, reason: str) -> "Check":
        """Mark not applicable with a reason.

        Rules:   only for applicability gates, not for missing evidence.
        """
        self.status = "not_applicable"
        self.notes.append(reason)
        return self

    def finding(self, condition_key: str, severity: str, entity: dict, summary: str, *,
                evidence=None, calculation=None, recommendation="", uncertainty="", owner=None) -> Finding:
        """Record a finding.

        Rules:   severity MUST be Critical/Warning/Info from the recipe table; id = hash(skill, account, entity, condition, period).
        """
        if severity not in SEVERITIES:
            raise ValueError(f"severity {severity!r} not in {SEVERITIES}")
        r = self.result
        fid = _hash(r.skill, r.account_id, entity, condition_key, r.period)
        f = Finding(fid, self.id, condition_key, severity, entity, summary, evidence or {}, calculation or {},
                    recommendation, uncertainty, owner or r.skill)
        r.add_finding(f)
        return f

    def observe(self, text: str, **data) -> None:
        """Record a non-defect calculation.

        Rules:   observations prove execution; they never carry severity.
        """
        self.result.observations.append({"check": self.id, "text": text, "data": _clean(data)})

    def review(self, condition_key: str, entity: dict, question: str, *, evidence=None,
               outcomes: dict, guidance: str = "", provisional: Finding | None = None) -> ReviewItem:
        """Queue an AI judgment with closed outcomes.

        Rules:   outcomes map to severity|None; pass provisional= to let finalize replace/remove a deterministic placeholder.
        """
        for name, spec in outcomes.items():
            sev = spec.get("severity")
            if sev is not None and sev not in SEVERITIES:
                raise ValueError(f"outcome {name}: severity {sev!r} invalid")
        r = self.result
        rid = _hash(r.skill, r.account_id, entity, condition_key, r.period, "review")
        item = ReviewItem(rid, self.id, condition_key, entity, question, evidence or {}, outcomes, guidance,
                          provisional.id if provisional is not None else None)
        if rid not in {x.id for x in r.reviews}:
            r.reviews.append(item)
        return item

    def coverage(self) -> dict:
        """Coverage record.

        Rules:   undeclared status defaults to completed only for runnable checks.
        """
        return _clean({"check": self.id, "title": self.title, "status": self.status or "completed",
                       "missing": sorted(set(self.missing)), "notes": self.notes})


class Result:
    def __init__(self, skill: str, script_version: str, runtime_version: str):
        self.skill, self.script_version, self.runtime_version = skill, script_version, runtime_version
        self.account_id = None
        self.period = None
        self.scope: dict = {}
        self.inputs: dict = {}
        self.parameters: dict = {}
        self.findings: list[Finding] = []
        self.observations: list[dict] = []
        self.reviews: list[ReviewItem] = []
        self.checks: list[Check] = []
        self.errors: list[str] = []

    def check(self, check_id: str, title: str) -> Check:
        """Declare a check.

        Rules:   ids unique per run; every declared check appears in coverage.
        """
        if any(c.id == check_id for c in self.checks):
            raise ValueError(f"duplicate check id {check_id}")
        c = Check(self, check_id, title)
        self.checks.append(c)
        return c

    def remove_finding(self, fid: str) -> None:
        """Drop a finding by id.

        Rules:   only finalize uses this, to resolve a provisional finding after an accepted decision.
        """
        self.findings = [f for f in self.findings if f.id != fid]

    def add_finding(self, f: Finding) -> None:
        """Record a finding, merging duplicates of the same id.

        Rules:   winner = higher severity (tie: the first emitted); its summary/recommendation/uncertainty/origin stay.
                 evidence and calculation are unioned key by key; a key with different values keeps the winner's
                 value and lists every distinct value under <field>['_conflicts'][key]; differing summaries of the
                 loser are kept in evidence['_merged_summaries']. Nothing is silently discarded.
        """
        for i, old in enumerate(self.findings):
            if old.id != f.id:
                continue
            win, lose = (f, old) if SEVERITIES.index(f.severity) < SEVERITIES.index(old.severity) else (old, f)
            for attr in ("evidence", "calculation"):
                setattr(win, attr, _merge_fields(getattr(win, attr), getattr(lose, attr)))
            summaries = {x for x in (win.evidence.get("_merged_summaries") or [])}
            summaries |= set(lose.evidence.get("_merged_summaries") or [])
            if lose.summary != win.summary:
                summaries.add(lose.summary)
            summaries.discard(win.summary)
            if summaries:
                win.evidence["_merged_summaries"] = sorted(summaries)
            self.findings[i] = win
            return
        self.findings.append(f)

    def as_dict(self) -> dict:
        """Serialize deterministically.

        Rules:   floats rounded via _clean; no wall-clock or path values.
        """
        order = {s: i for i, s in enumerate(SEVERITIES)}
        findings = sorted((f.as_dict() for f in self.findings),
                          key=lambda d: (order[d["severity"]], d["check"], d["condition_key"], d["id"]))
        body = {
            "schema": SCHEMA,
            "skill": self.skill,
            "script_version": self.script_version,
            "runtime_version": self.runtime_version,
            "scope": _clean(self.scope),
            "inputs": _clean(self.inputs),
            "parameters": _clean(self.parameters),
            "findings": findings,
            "observations": sorted(self.observations, key=lambda o: (o["check"], o["text"])),
            "ai_review": sorted((x.as_dict() for x in self.reviews), key=lambda d: (d["check"], d["id"])),
            "coverage": [c.coverage() for c in self.checks],
            "errors": sorted(self.errors),
            "counts": {s: sum(1 for f in self.findings if f.severity == s) for s in SEVERITIES},
        }
        body["fingerprint"] = _hash(body)
        return body
