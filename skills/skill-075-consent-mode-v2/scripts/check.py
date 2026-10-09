"""check.py — skill-075 deterministic consent mode v2 technical-behavior screening from config and traces.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-075-consent-mode-v2/SKILL.md → Analysis Steps (via RUNTIME.md)
rules:   Technical behavior only: never a GDPR/CCPA compliance verdict; owners (technical/privacy) ride on every finding.
         Signal cells: granted|denied; explicit not_set/missing/absent/undefined = confirmed missing signal;
         empty/unknown = UNKNOWN (partial), never denied or granted.
         Denied-state storage/identifier: ad_storage denied + cookie read/write observed, or ad_user_data denied +
         identifier_present → deterministic Warning (contradicts consent-mode semantics); advanced-mode pre-consent
         firing alone is NOT a defect. Critical only via review on >=2 distinct violating test_ids, verify demands
         proposal.evidence_ref. Scenario expectations: accept → all four granted; deny/withdrawal/return_denied →
         ad_storage, ad_user_data, ad_personalization denied; fresh_no_choice/regional_default → configured defaults;
         partial and unknown scenarios are not auto-judged. No universal wait duration is prescribed.
         Modeling status only from direct diagnostics; unavailable modeling is never a consent defect.
         Steps 8–9 (escalation to owners, basic/advanced semantics source) are carried in recommendations, not checks.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks09 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-075-consent-mode-v2"
VERSION = "1.0.0"

CFG = "external/consent_configuration"
TRC = "external/consent_traces"
DIAG = "external/consent_modeling_diagnostics"
SIGNALS = ("ad_storage", "analytics_storage", "ad_user_data", "ad_personalization")
AD_SIGNALS = ("ad_storage", "ad_user_data", "ad_personalization")
_MISSING = {"not_set", "not set", "missing", "absent", "undefined"}
_NO_REQUEST = {"none", "blocked", "no_request", "no request", "not_sent"}
EXPECTED_SCENARIOS = ("fresh_no_choice", "deny", "accept", "partial", "withdrawal", "return", "regional_default")


def _signal(v) -> str | None:
    """granted|denied|missing|other:<raw>; None = unknown."""
    s = str(v if v is not None else "").strip().lower()
    if s in ("", "unknown", "n/a", "na", "--", "null"):
        return None
    if s in ("granted", "denied"):
        return s
    if s in _MISSING:
        return "missing"
    return "other:" + s


def _scenario(v) -> str:
    s = V.norm_text(v).replace("-", "_").replace(" ", "_")
    if s in ("fresh", "fresh_visit", "no_choice", "fresh_no_choice"):
        return "fresh_no_choice"
    return s


def _site_key(r) -> tuple[str, str, str]:
    return (str(r.get("site_id") or ""), str(r.get("region_rule_id") or ""), str(r.get("deployment_version") or ""))


def _mode(v) -> str | None:
    s = V.norm_text(v)
    return s if s in ("basic", "advanced") else None


def _owners(cfg: dict | None) -> dict:
    cfg = cfg or {}
    return {"technical_owner": cfg.get("technical_owner"), "privacy_owner": cfg.get("privacy_owner")}


def _cfg_for(configs: dict, r) -> dict | None:
    """Config row for a trace: exact (site, region, version); version-less traces only when unique."""
    key = _site_key(r)
    if key in configs:
        return configs[key]
    if not key[2]:
        hits = [c for k, c in configs.items() if k[:2] == key[:2]]
        return hits[0] if len(hits) == 1 else None
    return None


def _entity(ctx, key) -> dict:
    return {"account_id": ctx.account_id, "site_id": key[0], "region_rule_id": key[1], "deployment_version": key[2]}


def _is_request(r) -> bool | None:
    rc = V.norm_text(r.get("request_class"))
    if not rc:
        return None
    return rc not in _NO_REQUEST


def run(ctx) -> None:
    """Run consent-mode scope/mode map, signal completeness, blocking, denied-state and ordering/scenario checks.

    Rules:   Empty/unknown signal cells → partial, never granted/denied; confirmed missing signals and incorrect updates
             are Warning. Denied-state storage/identifier use and unblocked basic-mode tags are deterministic Warnings;
             advanced-mode pre-consent pings alone are not defects (Info). Critical only via ai_review on >= 2 distinct
             violating test_ids. Never a legal compliance verdict; unavailable modeling is never a consent defect.
    """
    configs: dict[tuple, dict] = {}
    scope = ctx.check("scope_mode_map", "Map site/region scope to chosen mode and approved technical policy",
                      {CFG: ["site_id", "region_rule_id", "deployment_version", "chosen_mode_basic_or_advanced",
                             "regional_scope", "approved_policy_reference"]})
    if scope.runnable:
        for r in sorted(ctx.rows(CFG), key=_site_key):
            key = _site_key(r)
            if key in configs:
                scope.partial(f"duplicate configuration rows for {key}; first row used")
                continue
            configs[key] = r
            mode = _mode(r.get("chosen_mode_basic_or_advanced"))
            if mode is None:
                scope.partial(f"site {key[0]}/{key[1]}: chosen mode unknown; mode-specific checks not evaluated",
                              [f"{CFG}:chosen_mode_basic_or_advanced"])
            if not r.get("approved_policy_reference"):
                scope.partial(f"site {key[0]}/{key[1]}: approved technical policy unavailable; policy mismatch unassessable",
                              [f"{CFG}:approved_policy_reference"])
            if not r.get("regional_scope"):
                scope.partial(f"site {key[0]}/{key[1]}: regional applicability unknown", [f"{CFG}:regional_scope"])
            scope.observe(f"Consent scope {key[0]}/{key[1]} v{key[2] or '?'}: mode {mode or 'unknown'}",
                          **_entity(ctx, key), mode=mode, regional_scope=r.get("regional_scope"),
                          cmp_version=r.get("cmp_version"), platform=r.get("platform"),
                          approved_policy_reference=r.get("approved_policy_reference"), **_owners(r))
        scope.observe("Legal applicability is owner-supplied; traffic geography does not establish legal obligations",
                      configurations=len(configs))

    traces = sorted(ctx.rows(TRC), key=lambda r: (_site_key(r), V.num(r.get("relative_ms")) or 0,
                                                  V.num(r.get("sequence")) or 0, str(r.get("test_id") or "")))
    have_traces = ctx.table(TRC) is not None
    if have_traces and configs:
        orphans = sorted({_site_key(r) for r in traces if _cfg_for(configs, r) is None})
        if orphans:
            scope.partial(f"{len(orphans)} traced site/region/version scopes have no configuration row: {orphans[:5]}")

    _signals(ctx, configs, traces)
    _basic(ctx, configs, traces)
    _advanced(ctx, configs, traces)
    _ordering(ctx, configs, traces)
    _reproducibility(ctx, traces)
    _modeling(ctx)


def _signals(ctx, configs, traces) -> None:
    chk = ctx.check("signal_completeness", "All four signals in defaults and updates; update correctness",
                    {CFG: ["site_id", "region_rule_id", "default_ad_storage", "default_analytics_storage",
                           "default_ad_user_data", "default_ad_personalization"],
                     TRC: ["test_id", "site_id", "region_rule_id", "scenario", "consent_default_or_update", *SIGNALS]})
    if not chk.runnable:
        return
    unknown = 0
    for key, cfg in sorted(configs.items()):
        for s in SIGNALS:
            st = _signal(cfg.get(f"default_{s}"))
            if st is None:
                unknown += 1
            elif st == "missing":
                chk.finding("required_signal_missing", "Warning", {**_entity(ctx, key), "signal": s, "stage": "default"},
                            f"Default for {s} is explicitly not set in configuration {key}",
                            evidence={"cell": f"{CFG}:default_{s}", "value": cfg.get(f"default_{s}"), **_owners(cfg)},
                            recommendation="Ask the technical owner to declare all four defaults before measurement; "
                                           "technical review only, no legal verdict.",
                            uncertainty="Configuration snapshot; runtime traces may differ.")
    checked = 0
    for r in traces:
        cfg = _cfg_for(configs, r)
        key = _site_key(r)
        states = {s: _signal(r.get(s)) for s in SIGNALS}
        unknown += sum(1 for v in states.values() if v is None)
        for s, st in states.items():
            if st == "missing":
                chk.finding("required_signal_missing", "Warning",
                            {**_entity(ctx, key), "signal": s, "stage": str(r.get("consent_default_or_update") or "")},
                            f"Trace {r.get('test_id')} shows {s} not set during {r.get('scenario')}",
                            evidence={"test_id": r.get("test_id"), "trace_reference": r.get("trace_reference"),
                                      **_owners(cfg)},
                            recommendation="Send all four signals in every default and update command.",
                            uncertainty="Single sanitized trace; confirm with a repeat run.")
        sc = _scenario(r.get("scenario"))
        expected: dict[str, str] = {}
        if sc == "accept":
            expected = {s: "granted" for s in SIGNALS}
        elif sc in ("deny", "withdrawal", "return_denied"):
            expected = {s: "denied" for s in AD_SIGNALS}
        elif sc in ("fresh_no_choice", "regional_default") and cfg is not None:
            expected = {s: _signal(cfg.get(f"default_{s}")) for s in SIGNALS}
            expected = {s: v for s, v in expected.items() if v in ("granted", "denied")}
        if not expected:
            continue
        checked += 1
        wrong = {s: {"expected": e, "observed": states[s]} for s, e in sorted(expected.items())
                 if states[s] in ("granted", "denied") and states[s] != e}
        if wrong:
            chk.finding("incorrect_consent_update", "Warning", {**_entity(ctx, key), "test_id": r.get("test_id"),
                                                               "scenario": sc},
                        f"Scenario {sc} ({r.get('test_id')}) records signals contrary to the tested choice: {wrong}",
                        evidence={"mismatch": wrong, "consent_default_or_update": r.get("consent_default_or_update"),
                                  "trace_reference": r.get("trace_reference"), **_owners(cfg)},
                        recommendation="Implementation owner: fix update propagation for this scenario and re-run the "
                                       "synthetic trace; escalate to the privacy owner.",
                        uncertainty="Scenario label defines the tested user choice; technical behavior only.")
    if unknown:
        chk.partial(f"{unknown} signal cells unknown (empty); unknown is not denied or granted")
    chk.observe("Signal completeness evaluated", configurations=len(configs), trace_rows=len(traces),
                scenario_rows_with_expectation=checked)


def _review_critical(chk, ctx, key, cfg, violations, condition) -> None:
    tests = sorted({str(v["test_id"]) for v in violations})
    if len(tests) < 2:
        return
    chk.review(condition, _entity(ctx, key),
               f"Traces {tests} reproduce prohibited-looking storage/transmission for {key[0]}/{key[1]}. Is it contrary "
               f"to the supplied policy '{(cfg or {}).get('approved_policy_reference')}' AND is material impact evidenced?",
               evidence={"violating_tests": tests, "rows": violations,
                         "approved_policy_reference": (cfg or {}).get("approved_policy_reference"), **_owners(cfg)},
               outcomes={"prohibited_material_evidenced": {"severity": "Critical", "recommendation":
                                                           "Escalate to implementation and privacy owners now; cite the "
                                                           "trace and impact evidence. No legal verdict."},
                         "not_evidenced": {"severity": None, "recommendation": "Keep the Warning; request owner review."}},
               guidance="Critical needs the supplied policy to prohibit this behavior AND evidenced material impact; "
                        "give proposal.evidence_ref. Never label the account compliant/noncompliant.")


def _violations(rows) -> tuple[list[dict], int]:
    out, unknown = [], 0
    for r in rows:
        ads, aud = _signal(r.get("ad_storage")), _signal(r.get("ad_user_data"))
        cr, cw, ident = (V.boolean(r.get(c)) for c in ("cookie_read_observed", "cookie_write_observed", "identifier_present"))
        hits = []
        if ads == "denied":
            if cr is None or cw is None:
                unknown += 1
            if cr or cw:
                hits.append("cookie read/write with ad_storage denied")
        if aud == "denied":
            if ident is None:
                unknown += 1
            if ident:
                hits.append("identifier present with ad_user_data denied")
        if hits:
            out.append({"test_id": r.get("test_id"), "scenario": _scenario(r.get("scenario")), "issues": hits,
                        "request_class": r.get("request_class"), "payload_classification": r.get("payload_classification"),
                        "expected_behavior": r.get("expected_behavior"), "observed_behavior": r.get("observed_behavior"),
                        "trace_reference": r.get("trace_reference")})
    return out, unknown


def _by_site(configs, traces, mode) -> dict:
    out: dict[tuple, list] = {}
    for r in traces:
        cfg = _cfg_for(configs, r)
        if cfg is not None and _mode(cfg.get("chosen_mode_basic_or_advanced")) == mode:
            out.setdefault(_site_key(cfg), []).append(r)
    return out


def _basic(ctx, configs, traces) -> None:
    basic_sites = [k for k, c in configs.items() if _mode(c.get("chosen_mode_basic_or_advanced")) == "basic"]
    chk = ctx.check("basic_mode_blocking", "Basic mode: Google tags blocked until consent allows loading",
                    {CFG: ["chosen_mode_basic_or_advanced"],
                     TRC: ["test_id", "site_id", "region_rule_id", "request_class", "tag_destination", "ad_storage",
                           "analytics_storage"]},
                    applicable=bool(basic_sites) or not configs,
                    na_reason="no site declares basic mode")
    if not chk.runnable:
        return
    for key, rows in sorted(_by_site(configs, traces, "basic").items()):
        cfg = configs[key]
        early, unknown = [], 0
        for r in rows:
            denied = _signal(r.get("ad_storage")) == "denied" and _signal(r.get("analytics_storage")) == "denied"
            req = _is_request(r)
            if denied and req is None:
                unknown += 1
            if denied and req:
                early.append({"test_id": r.get("test_id"), "scenario": _scenario(r.get("scenario")),
                              "request_class": r.get("request_class"), "tag_destination": r.get("tag_destination"),
                              "trace_reference": r.get("trace_reference")})
        if unknown:
            chk.partial(f"site {key[0]}: {unknown} denied-state rows with unknown request_class")
        if early:
            chk.finding("basic_mode_tag_not_blocked", "Warning", _entity(ctx, key),
                        f"Basic mode site {key[0]}/{key[1]} sends Google requests while all storage is denied "
                        f"({len(early)} trace rows)", evidence={"rows": early, **_owners(cfg)},
                        recommendation="Implementation owner: block Google tags until the documented consent decision; "
                                       "re-run synthetic traces; privacy owner reviews.",
                        uncertainty="Technical behavior only; materiality and policy meaning need owner review.")
            _review_critical(chk, ctx, key, cfg, early, "basic_mode_prohibited_transmission")
        else:
            chk.observe(f"Basic mode site {key[0]}/{key[1]}: no Google request observed under denied storage",
                        **_entity(ctx, key), trace_rows=len(rows))


def _advanced(ctx, configs, traces) -> None:
    adv_sites = [k for k, c in configs.items() if _mode(c.get("chosen_mode_basic_or_advanced")) == "advanced"]
    chk = ctx.check("advanced_denied_behavior", "Advanced mode: denied-state payload, storage and identifier behavior",
                    {CFG: ["chosen_mode_basic_or_advanced"],
                     TRC: ["test_id", "site_id", "region_rule_id", "ad_storage", "ad_user_data", "request_class",
                           "cookie_read_observed", "cookie_write_observed", "identifier_present",
                           "payload_classification"]},
                    applicable=bool(adv_sites) or not configs, na_reason="no site declares advanced mode")
    if not chk.runnable:
        return
    for key, rows in sorted(_by_site(configs, traces, "advanced").items()):
        cfg = configs[key]
        denied_rows = [r for r in rows if _signal(r.get("ad_storage")) == "denied" or _signal(r.get("ad_user_data")) == "denied"]
        violations, unknown = _violations(denied_rows)
        if violations:
            chk.finding("denied_state_storage_or_identifier", "Warning", _entity(ctx, key),
                        f"Advanced mode site {key[0]}/{key[1]}: {len(violations)} denied-state trace rows show "
                        f"cookie access or identifiers ({len({v['test_id'] for v in violations})} distinct tests)",
                        evidence={"rows": violations, "denied_state_rows": len(denied_rows),
                                  "approved_policy_reference": cfg.get("approved_policy_reference"), **_owners(cfg)},
                        calculation={"violating_rows": len(violations), "denied_state_rows": len(denied_rows)},
                        recommendation="Implementation owner: stop storage/identifier use while denied; re-run the "
                                       "synthetic deny/withdrawal traces; escalate to the privacy owner.",
                        uncertainty="Technical behavior only; not a legal compliance verdict.")
            _review_critical(chk, ctx, key, cfg, violations, "prohibited_transmission_under_denied_state")
            continue
        if unknown:
            chk.partial(f"site {key[0]}: {unknown} denied-state rows with unknown storage/identifier observations")
            continue
        cookieless = [r for r in denied_rows if "cookieless" in V.norm_text(r.get("request_class"))]
        if denied_rows and len(cookieless) == len(denied_rows):
            chk.finding("advanced_cookieless_matches_design", "Info", _entity(ctx, key),
                        f"Advanced mode site {key[0]}/{key[1]}: all {len(denied_rows)} denied-state rows send cookieless "
                        f"pings without storage or identifiers, matching the declared design",
                        evidence={"tests": sorted(str(r.get("test_id")) for r in denied_rows), **_owners(cfg),
                                  "approved_policy_reference": cfg.get("approved_policy_reference")},
                        recommendation="No change; keep periodic synthetic traces per deployment version.",
                        uncertainty="Covers only the traced scenarios and version.")
        else:
            chk.observe(f"Advanced mode site {key[0]}/{key[1]}: no prohibited denied-state behavior observed",
                        **_entity(ctx, key), denied_state_rows=len(denied_rows), cookieless_rows=len(cookieless))


def _ordering(ctx, configs, traces) -> None:
    chk = ctx.check("ordering_and_scenarios", "Default-before-measurement ordering and scenario coverage",
                    {TRC: ["test_id", "site_id", "region_rule_id", "scenario", "sequence", "relative_ms",
                           "consent_default_or_update", "request_class"]})
    if not chk.runnable:
        return
    groups: dict[tuple, list] = {}
    for r in traces:
        groups.setdefault(_site_key(r), []).append(r)
    for key, rows in sorted(groups.items()):
        cfg = _cfg_for(configs, rows[0])
        defaults = [V.num(r.get("relative_ms")) for r in rows if V.norm_text(r.get("consent_default_or_update")) == "default"]
        defaults = [d for d in defaults if d is not None]
        if not defaults:
            chk.partial(f"site {key[0]}/{key[1]}: no consent default observed in traces; ordering unassessed")
        else:
            first = min(defaults)
            early = [r for r in rows if _is_request(r) and (V.num(r.get("relative_ms")) is not None)
                     and V.num(r.get("relative_ms")) < first]
            if early:
                chk.finding("measurement_before_default", "Warning", _entity(ctx, key),
                            f"{len(early)} measurement requests precede the first consent default ({first:g} ms) "
                            f"on {key[0]}/{key[1]}",
                            evidence={"tests": sorted(str(r.get("test_id")) for r in early), "first_default_ms": first,
                                      "wait_for_update_ms": (cfg or {}).get("wait_for_update_ms"),
                                      "default_timing_rule": (cfg or {}).get("default_timing_rule"), **_owners(cfg)},
                            recommendation="Set consent defaults before any measurement command; no universal wait "
                                           "duration is prescribed.",
                            uncertainty="Relative timing from sanitized synthetic traces.")
        seen = {_scenario(r.get("scenario")) for r in rows}
        missing = [s for s in EXPECTED_SCENARIOS if not any(x == s or x.startswith(s) for x in seen)]
        if missing:
            chk.partial(f"site {key[0]}/{key[1]}: untested paths {missing}")
        chk.observe(f"Scenario coverage {key[0]}/{key[1]}", **_entity(ctx, key), scenarios=sorted(seen),
                    untested=missing, wait_for_update_ms=(cfg or {}).get("wait_for_update_ms"))


def _reproducibility(ctx, traces) -> None:
    chk = ctx.check("trace_corroboration", "Reproducible synthetic trace corroboration",
                    {TRC: ["test_id", "site_id", "trace_reference", "expected_behavior", "observed_behavior"]})
    if not chk.runnable:
        return
    no_ref = sorted(str(r.get("test_id")) for r in traces if not r.get("trace_reference"))
    if no_ref:
        chk.partial(f"{len(no_ref)} trace rows lack trace_reference; not reproducible evidence", [f"{TRC}:trace_reference"])
    sites: dict[str, set] = {}
    for r in traces:
        sites.setdefault(str(r.get("site_id")), set()).add(str(r.get("test_id")))
    for s, tests in sorted(sites.items()):
        chk.observe(f"Site {s}: distinct synthetic tests", site_id=s, tests=len(tests))
    chk.observe("Conversion-account ownership queries cannot verify consent behavior; traces are the evidence",
                trace_rows=len(traces))


def _modeling(ctx) -> None:
    chk = ctx.check("modeling_status", "Consent modeling status from direct diagnostics (optional)",
                    {DIAG: ["action_id", "reported_modeling_status", "source_eligibility_message", "processing_mature",
                            "source_reference"],
                     "conversion_actions": ["id"]})
    if not chk.runnable:
        chk.notes.append("optional diagnostics: modeling status reported as unavailable, not as a defect")
        return
    actions = {str(a.get("id")) for a in ctx.rows("conversion_actions")}
    for r in sorted(ctx.rows(DIAG), key=lambda r: str(r.get("action_id"))):
        aid = str(r.get("action_id"))
        if aid not in actions:
            chk.partial(f"diagnostic action {aid} not in conversion_actions")
        chk.observe(f"Action {aid}: reported modeling status {r.get('reported_modeling_status')}", action_id=aid,
                    status=r.get("reported_modeling_status"), message=r.get("source_eligibility_message"),
                    processing_mature=V.boolean(r.get("processing_mature")), source_reference=r.get("source_reference"),
                    note="Unavailable modeling is not a consent defect; no recovery percentage is implied.")


def verify(ctx, item, decision) -> list[str]:
    """Rules: Critical outcomes require proposal.evidence_ref pointing at supplied trace/impact evidence."""
    spec = item.outcomes.get(decision.get("outcome")) or {}
    if spec.get("severity") == "Critical" and not str((decision.get("proposal") or {}).get("evidence_ref") or "").strip():
        return ["Critical needs proposal.evidence_ref citing supplied trace and material-impact evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
