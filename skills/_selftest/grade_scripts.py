"""grade_scripts.py — Grade skill check.py outputs against the hidden self-test oracle.

exports: grade_case(case, root, out) -> dict | main(argv) -> int
used_by: skills/_selftest/SKILL.md → "Deterministic script grading"; CI/maintainers
rules:   Coordinator-only: check scripts never read expected.json; this grader only reads their outputs.
         must_contain matches case-insensitively over a finding's entity+summary+evidence JSON.
         reject hit on a deterministic finding at the named severity = FAIL.
         expect satisfied by a deterministic finding = PASS; satisfied only through an ai_review item whose
         declared outcomes can yield that severity = PENDING_AI (the AI step must still decide) — never PASS.
         A case whose skill has no scripts/check.py = NO_SCRIPT (reported, not silently skipped).
         Observations remain semantic and are graded by the Markdown self-test, not here.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial grader
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _text(item: dict) -> str:
    return json.dumps({k: item.get(k) for k in ("entity", "summary", "evidence", "question", "condition_key")},
                      ensure_ascii=False, sort_keys=True).lower()


def _match(item: dict, spec: dict) -> bool:
    t = _text(item)
    if not all(s.lower() in t for s in spec["must_contain"]):
        return False
    return not spec.get("any_of") or any(s.lower() in t for s in spec["any_of"])


def grade_case(case: dict, root: Path, out: Path) -> dict:
    script = root / case["skill"] / "scripts" / "check.py"
    if not script.is_file():
        return {"case": case["case_id"], "verdict": "NO_SCRIPT"}
    fixture = HERE / "fixture"
    export = fixture / case.get("export_path", "export/")
    profile = fixture / case.get("profile_path", "profile.yaml")
    dest = out / case["case_id"]
    proc = subprocess.run([sys.executable, str(script), "run", "--export", str(export), "--profile", str(profile),
                           "--out", str(dest)], capture_output=True, text=True)
    if proc.returncode != 0:
        return {"case": case["case_id"], "verdict": "ERROR", "stderr": proc.stderr.strip()[-500:]}
    body = json.loads((dest / "result.json").read_text())
    findings, reviews = body["findings"], body["ai_review"]
    problems, pending, satisfied = [], [], []
    for spec in case.get("reject", []):
        for f in findings:
            if _match(f, spec) and (spec.get("severity") in (None, f["severity"])):
                problems.append(f"reject hit: {spec['must_contain']} as {f['severity']} ({f['condition_key']})")
    for spec in case.get("expect", []):
        sev = spec.get("severity")
        if any(_match(f, spec) and sev in (None, f["severity"]) for f in findings):
            satisfied.append(spec["must_contain"])
        elif any(_match(r, spec) and any(sev in (None, o.get("severity")) for o in r["outcomes"].values())
                 for r in reviews):
            pending.append(spec["must_contain"])
        else:
            problems.append(f"expected {sev} {spec['must_contain']} not produced")
    verdict = "FAIL" if problems else "PENDING_AI" if pending else "PASS"
    return {"case": case["case_id"], "skill": case["skill"], "verdict": verdict, "problems": problems,
            "pending_ai": pending, "satisfied": satisfied, "counts": body["counts"],
            "coverage": {c["check"]: c["status"] for c in body["coverage"]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=HERE.parent)
    ap.add_argument("--out", type=Path, default=Path("/tmp/adsrun-grade"))
    ap.add_argument("--case", action="append", help="case_id filter (repeatable)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cases = json.loads((HERE / "fixture" / "expected.json").read_text())["cases"]
    if a.case:
        cases = [c for c in cases if c["case_id"] in a.case]
    results = [grade_case(c, a.root, a.out) for c in cases]
    if a.json:
        print(json.dumps(results, indent=1))
    else:
        for r in results:
            extra = "; ".join(r.get("problems") or []) or (f"AI must decide {r['pending_ai']}" if r.get("pending_ai") else "")
            print(f"{r['verdict']:<10} {r['case']:<32} {extra or r.get('stderr', '')}")
    tally = {}
    for r in results:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(" · ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 1 if any(r["verdict"] in ("FAIL", "ERROR") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
