"""cli.py — Command line for skill checks: run (per account) and finalize (validate AI decisions).

exports: main(skill, version, run, verify=None, argv=None) -> int | run_once(...) -> Context
used_by: skills/skill-*/scripts/check.py → `python3 scripts/check.py run|finalize ...`
rules:   Exit 0 = outputs written (findings are not errors); 2 = unusable inputs; 3 = stale evidence;
         4 = final.json written but >=1 decision rejected (fix and re-finalize).
         Multi-account exports are partitioned: one Context (own currency/params) per customer ID,
         written to <out>/accounts/<id>/; accounts never share parameters or totals.
         finalize re-runs the deterministic checks and REFUSES decisions if the fingerprint changed
         (evidence/profile/script edited after the AI review) — exit 3.
         Decisions choose a declared outcome only; unknown ids/outcomes are rejected, never coerced.
         Skill verify(ctx, item, decision) hooks re-check proposals deterministically; any problem rejects.
         Writes only inside --out. Never touches the network or Google Ads.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial CLI
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import values as V
from .context import Context, ContextError, account_ids
from .evidence import load_evidence
from .result import SEVERITIES, _clean


def _code_digest(run) -> str:
    """sha256 over the skill check.py and every adsrun module: code edits invalidate prior reviews."""
    import hashlib
    files = [Path(run.__code__.co_filename)] + sorted(Path(__file__).parent.glob("*.py"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def run_once(skill, version, run, export: Path, profile: Path | None, as_of=None, account_id=None) -> Context:
    """Build one Context, fingerprint the code, run the skill.

    Rules:   single execution path for run AND finalize — never construct Context elsewhere or fingerprints diverge.
    """
    ctx = Context(skill, version, export, profile, as_of, account_id)
    ctx.result.inputs["code_sha256"] = _code_digest(run)
    run(ctx)
    return ctx


def _write(out: Path, body: dict, name: str = "result.json") -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(body, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    with (out / name.replace(".json", "_findings.csv").replace("result_findings", "findings")).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["severity", "id", "check", "condition_key", "entity", "summary", "recommendation", "origin"])
        for x in body["findings"]:
            w.writerow([x["severity"], x["id"], x["check"], x["condition_key"],
                        json.dumps(x["entity"], sort_keys=True, ensure_ascii=False), x["summary"],
                        x["recommendation"], x["origin"]])


def _summary(body: dict, path: Path) -> str:
    cov = {}
    for c in body["coverage"]:
        cov[c["status"]] = cov.get(c["status"], 0) + 1
    lines = [
        f"{body['skill']} {body['script_version']} · account {body['scope'].get('account_id')} · "
        f"{body['scope'].get('currency')} · period {body['scope'].get('period')}",
        "findings " + ", ".join(f"{s} {body['counts'][s]}" for s in SEVERITIES)
        + f" · ai_review {len(body['ai_review'])} · coverage " + ", ".join(f"{k} {v}" for k, v in sorted(cov.items())),
    ]
    for c in body["coverage"]:
        if c["status"] != "completed":
            lines.append(f"  - {c['check']}: {c['status']} {'; '.join(c['notes'])}"
                         + (f" missing {', '.join(c['missing'])}" if c["missing"] else ""))
    if body["errors"]:
        lines.append("errors: " + " | ".join(body["errors"]))
    lines.append(f"wrote {path} · fingerprint {body['fingerprint']}")
    return "\n".join(lines)


def _load_decisions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("decisions", [])
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise ContextError(f"{path.name}: decisions must be a list of objects or {{'decisions': [...]}}")
    return data


def _finalize(ctx: Context, stored: dict, decisions: list[dict], verify) -> dict:
    fresh = ctx.finish()
    if fresh["fingerprint"] != stored.get("fingerprint"):
        raise StaleEvidence("evidence, profile or script changed since the reviewed run; re-run and review again")
    items = {x.id: x for x in ctx.result.reviews}
    checks = {c.id: c for c in ctx.result.checks}
    log, seen = [], set()
    for d in decisions:
        rid, outcome = str(d.get("id") or ""), d.get("outcome")
        problems = []
        item = items.get(rid)
        if item is None:
            problems.append("unknown review id")
        elif rid in seen:
            problems.append("duplicate decision")
        elif outcome not in item.outcomes:
            problems.append(f"outcome {outcome!r} not in {sorted(item.outcomes)}")
        elif not str(d.get("rationale") or "").strip():
            problems.append("rationale required")
        elif verify is not None:
            problems += list(verify(ctx, item, d) or [])
        seen.add(rid)
        status = "rejected" if problems else "accepted"
        log.append({"id": rid, "outcome": outcome, "status": status, "problems": problems,
                    "rationale": d.get("rationale")})
        if problems:
            continue
        spec = item.outcomes[outcome]
        if item.provisional_finding:
            ctx.result.remove_finding(item.provisional_finding)
        if spec.get("severity") in SEVERITIES:
            f = checks[item.check].finding(
                item.condition_key, spec["severity"], item.entity, f"{item.question} → {outcome}",
                evidence={**item.evidence, "ai_rationale": d.get("rationale"), "proposal": d.get("proposal")},
                recommendation=spec.get("recommendation", ""),
                uncertainty="Analyst/AI judgment validated against declared outcomes; not deterministic evidence.")
            f.origin = "ai_review"
    body = ctx.result.as_dict()
    body["base_fingerprint"] = stored["fingerprint"]
    body["review_log"] = _clean(log)
    body["pending_review"] = sorted(set(items) - {x["id"] for x in log if x["status"] == "accepted"})
    return body


class StaleEvidence(RuntimeError):
    pass


def main(skill: str, version: str, run, verify=None, argv=None) -> int:
    """Entry point used by every scripts/check.py.

    Rules:   `run` is the default subcommand, so `check.py --export E --profile P --out O` works.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv = ["run"] + argv
    ap = argparse.ArgumentParser(prog=f"{skill} check.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--export", required=True, type=Path, help="folder with account.csv, campaigns.csv, ...")
        p.add_argument("--profile", type=Path, help="client profile (YAML subset or JSON)")
        p.add_argument("--out", required=True, type=Path, help="output folder (created)")
        p.add_argument("--as-of", help="report end date YYYY-MM-DD (default: profile/account)")
        p.add_argument("--account", help="customer ID for multi-account exports")
        if name == "finalize":
            p.add_argument("--decisions", required=True, type=Path, help="JSON AI decisions for ai_review ids")
    a = ap.parse_args(argv)
    as_of = V.parse_date(a.as_of) if a.as_of else None
    if a.as_of and as_of is None:
        print(f"invalid --as-of {a.as_of}", file=sys.stderr)
        return 2
    try:
        ids = [a.account] if a.account else account_ids(load_evidence(a.export))
        multi = len(ids) > 1
        if a.cmd == "run":
            index = []
            for acct in (ids if multi else [None]):
                ctx = run_once(skill, version, run, a.export, a.profile, as_of, acct if multi or a.account else None)
                body = ctx.finish()
                out = a.out / "accounts" / str(acct) if multi else a.out
                _write(out, body)
                print(_summary(body, out / "result.json"))
                index.append({"account_id": body["scope"].get("account_id"), "currency": body["scope"].get("currency"),
                              "counts": body["counts"], "path": f"accounts/{acct}/result.json"})
            if multi:
                (a.out / "result.json").write_text(json.dumps(
                    {"schema": "adsrun-multi/1", "skill": skill, "accounts": index}, indent=1, sort_keys=True) + "\n")
            return 0
        if multi:
            print("finalize needs --account for multi-account exports", file=sys.stderr)
            return 2
        stored_path = a.out / "result.json"
        if not stored_path.is_file():
            print(f"no prior run at {stored_path}; run first", file=sys.stderr)
            return 2
        stored = json.loads(stored_path.read_text())
        ctx = run_once(skill, version, run, a.export, a.profile, as_of, a.account)
        body = _finalize(ctx, stored, _load_decisions(a.decisions), verify)
        _write(a.out, body, "final.json")
        rejected = [x for x in body["review_log"] if x["status"] == "rejected"]
        print(_summary(body, a.out / "final.json"))
        print(f"decisions accepted {len(body['review_log']) - len(rejected)}, rejected {len(rejected)}, "
              f"pending {len(body['pending_review'])}")
        for x in rejected:
            print(f"  rejected {x['id']}: {'; '.join(x['problems'])}")
        return 4 if rejected else 0
    except StaleEvidence as e:
        print(f"STALE: {e}", file=sys.stderr)
        return 3
    except (ContextError, ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
