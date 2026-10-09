"""check.py — skill-008 deterministic label coverage and declared-policy compliance.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-008-label-organizational-structure/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #52 Add parts of campaign name as label to campaigns (kaugesaar) — clean-room reimplementation as the
         policy eligibility rule 'name_segment:<delimiter>:<index>=<value>'; the script never applies labels.
         index #53 Keyword Labeler (Google Ads scripts solutions) — clean-room reimplementation of rule-based label
         eligibility ('text_contains:' / 'name_contains:' / 'status=' / 'channel=') evaluated as compliance only.
         index #51 Add label to keywords with X conversions of conversion type Y — clean-room reimplementation as the
         opt-in check label_rule_evaluation (profile.label_rules): AND-combined >=/<=/== conditions on conversions /
         conversion_value per conversion action (custom/keyword_conversions_by_action, resolved against
         conversion_actions) or clicks/cost/impressions/all-action conversions (keyword_metrics), report window
         only, mature conversions only; outputs target vs current label set (keywords.labels) and an Info add/remove
         proposal. Refused: applying/removing labels, other entities, OR logic, rolling/date-range windows, e-mail.
rules:   Coverage only for entity types whose base table AND association rows are supplied; any-label coverage
         and policy compliance are separate; ENABLED and PAUSED reported separately; empty scope = undefined.
         Label policy only from external/label_policy. eligibility_rule grammar (deterministic subset):
         all | status=<S> | channel=<CHANNEL> | name_contains:<text> | text_contains:<text> |
         name_segment:<delimiter>:<index>=<value>. Anything else → partial, never guessed.
         required_label_ids: ';' = all required; 'a|b' = exactly one of the group (both present = contradictory).
         Missing/contradictory labels are Info unless the rule row has consumer_id + observed_failure + evidence_ref;
         then ai_review with a Warning outcome whose verify() requires that evidence_ref.
         Unattached-in-export labels are Info only when associations cover all four levels with a complete
         manifest; otherwise an observation. Never deletion; merges/renames list all affected consumers (verify()).
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks01 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_idx051 | opt-in label_rules evaluation (index #51)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-008-label-organizational-structure"
VERSION = "1.1.0"

INV = "custom/label_inventory"
ASSOC = "custom/label_associations"
POL = "external/label_policy"
INV_COLS = ["label_id", "name", "status"]
ASSOC_COLS = ["label_id", "entity_type", "campaign_id", "ad_group_id", "entity_id"]
POL_COLS = ["rule_id", "entity_type", "eligibility_rule", "required_label_ids", "consumer_id", "expected_behavior",
            "observed_failure", "evidence_ref", "owner", "reviewed_at"]
LEVELS = {"campaign": "campaigns", "ad_group": "ad_groups", "keyword": "keywords", "ad": "ads"}
KCA = "custom/keyword_conversions_by_action"
KCA_COLS = ["keyword_id", "campaign_id", "ad_group_id", "conversion_action_id", "conversions", "conversion_value", "window"]
RULE_METRICS = ("conversions", "conversion_value", "clicks", "cost", "impressions")
CONV_METRICS = {"conversions", "conversion_value"}
MONEY_METRICS = {"cost", "conversion_value"}
RULE_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: round(a, 6) == round(b, 6)}


def _etype(v) -> str:
    return str(v or "").strip().lower().replace("-", "_").replace(" ", "_").replace("adgroup", "ad_group")


def _entities(ctx) -> dict[str, dict[str, dict]]:
    """entity type → id → row, only for supplied base tables."""
    out = {}
    for t, table in LEVELS.items():
        if ctx.table(table) is None:
            continue
        rows = {}
        camp_channel = {str(c.get("id")): c.get("channel_type") for c in ctx.rows("campaigns")}
        for r in ctx.rows(table):
            rid = str(r.get("id"))
            rows[rid] = {"id": rid, "status": str(r.get("status") or "").upper(), "name": r.get("name") or "",
                         "text": r.get("text") or "", "campaign_id": str(r.get("campaign_id") or (rid if t == "campaign" else "")),
                         "channel": str((r.get("channel_type") if t == "campaign" else camp_channel.get(str(r.get("campaign_id"))))
                                        or "").upper()}
        out[t] = rows
    return out


def eligible(rule: str, e: dict) -> bool | None:
    """Evaluate the documented rule grammar; None = not machine-evaluable."""
    r = str(rule or "").strip()
    if r.lower() == "all":
        return True
    m = re.fullmatch(r"status=(\w+)", r, re.I)
    if m:
        return e["status"] == m.group(1).upper()
    m = re.fullmatch(r"channel=(\w+)", r, re.I)
    if m:
        return e["channel"] == m.group(1).upper()
    m = re.fullmatch(r"(name|text)_contains:(.+)", r, re.I)
    if m:
        return m.group(2).strip().lower() in str(e[m.group(1).lower()]).lower()
    m = re.fullmatch(r"name_segment:(.+):(\d+)=(.*)", r)
    if m:
        parts = [p.strip() for p in e["name"].split(m.group(1))]
        i = int(m.group(2))
        return i < len(parts) and parts[i] == m.group(3).strip()
    return None


def _norm(name: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(name).lower()))


def _resolve_action(ref, actions: dict[str, str]) -> tuple[str | None, str]:
    """conversion_action (id or exact case-insensitive name) → action id; (None, reason) when unknown/ambiguous."""
    s = str(ref).strip()
    if s in actions:
        return s, ""
    ids = sorted(i for i, n in actions.items() if V.norm_text(n) == V.norm_text(s))
    if len(ids) == 1:
        return ids[0], ""
    return None, (f"conversion_action '{s}' is ambiguous (ids {ids})" if ids else f"unknown conversion_action '{s}'")


def _validate_rule(raw, seen: set[str], actions: dict[str, str] | None) -> tuple[dict | None, list[str], list[str]]:
    """Normalize one profile.label_rules entry → (rule, rejections, missing inputs); rule is None unless valid."""
    if not isinstance(raw, dict):
        return None, ["rule is not a mapping"], []
    rid, label = str(raw.get("rule_id") or "").strip(), str(raw.get("label") or "").strip()
    bad, missing = [], []
    if not rid:
        bad.append("rule_id missing")
    elif rid in seen:
        bad.append(f"duplicate rule_id '{rid}'")
    if not label:
        bad.append("label missing")
    if str(raw.get("entity") or "").strip().lower() != "keyword":
        bad.append(f"entity '{raw.get('entity')}' unsupported (keyword only)")
    if str(raw.get("window") or "").strip().lower() != "report":
        bad.append(f"window '{raw.get('window')}' unsupported (report only)")
    conds = raw.get("conditions")
    if not isinstance(conds, list) or not conds:
        bad.append("conditions must be a non-empty list")
        conds = []
    out = []
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            bad.append(f"condition {i}: not a mapping")
            continue
        metric, op = str(c.get("metric") or "").strip().lower(), str(c.get("op") or "").strip()
        value = None if isinstance(c.get("value"), bool) else V.num(c.get("value"))
        if metric not in RULE_METRICS:
            bad.append(f"condition {i}: unknown metric '{c.get('metric')}'")
        if op not in RULE_OPS:
            bad.append(f"condition {i}: unknown op '{c.get('op')}'")
        if value is None or value != value or value in (float("inf"), float("-inf")):
            bad.append(f"condition {i}: value '{c.get('value')}' is not a finite number")
        aid = None
        if c.get("conversion_action") not in (None, ""):
            if metric not in CONV_METRICS:
                bad.append(f"condition {i}: conversion_action only applies to conversions/conversion_value")
            elif actions is None:
                missing.append("conversion_actions (file)")
            else:
                aid, why = _resolve_action(c.get("conversion_action"), actions)
                if aid is None:
                    bad.append(f"condition {i}: {why}")
        out.append({"metric": metric, "op": op, "value": value, "conversion_action_id": aid})
    if bad or missing:
        return None, bad, missing
    return {"rule_id": rid, "label": label, "conditions": out}, [], []


def _label_rules(ctx) -> None:
    """Opt-in label_rule_evaluation: profile.label_rules → target vs current keyword label sets (index #51)."""
    raw = ctx.profile.get("label_rules")
    chk = ctx.check("label_rule_evaluation", "Declared keyword label rules vs current labels (proposal only)",
                    {"keywords": ["id", "campaign_id", "ad_group_id", "status"]},
                    applicable=bool(raw), na_reason="profile.label_rules not declared")
    if not chk.runnable:
        return
    if not isinstance(raw, list):
        chk.partial("profile.label_rules must be a list; nothing evaluated")
        return
    t_ca = ctx.table("conversion_actions")
    actions = None if t_ca is None or t_ca.missing(["id", "name"]) else {
        str(a.get("id")): str(a.get("name") or "") for a in t_ca.rows if a.get("id") is not None}
    kw_cols = ctx.table("keywords").columns
    inv = {}
    for k in ctx.rows("keywords"):
        if str(k.get("status") or "").upper() != "REMOVED":
            inv[(str(k.get("campaign_id")), str(k.get("ad_group_id")), str(k.get("id")))] = k
    t_km, t_kca = ctx.table("keyword_metrics"), ctx.table(KCA)
    km, km_dup = {}, set()
    if t_km is not None and not t_km.missing(["keyword_id", "campaign_id", "ad_group_id"]):
        for m in ctx.rows("keyword_metrics"):
            key = (str(m.get("campaign_id")), str(m.get("ad_group_id")), str(m.get("keyword_id")))
            if key in km:
                km_dup.add(key)
            else:
                km[key] = m
    period = f"{ctx.period_start}..{ctx.period_end}" if ctx.period_start and ctx.period_end else None
    kca, kca_dup, off_window = {}, set(), 0
    if t_kca is not None and not t_kca.missing(KCA_COLS):
        for r in ctx.rows(KCA):
            w = str(r.get("window") or "").strip().lower()
            if w != "report" and w != period:
                off_window += 1
                continue
            key = (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("keyword_id")),
                   str(r.get("conversion_action_id")))
            if key in kca:
                kca_dup.add(key)
            else:
                kca[key] = r
    if km_dup:
        chk.partial(f"keyword_metrics: {len(km_dup)} keywords with duplicate metric rows; excluded (fan-out)")
    if kca_dup:
        chk.partial(f"{KCA}: {len(kca_dup)} duplicate keyword×action rows; those values excluded (fan-out)")
    if off_window:
        chk.observe("By-action rows outside the report window ignored", rows=off_window, report_window=period)
    km_full = t_km is not None and t_km.complete is True and not t_km.truncated
    kca_full = t_kca is not None and t_kca.complete is True and not t_kca.truncated

    def value(key, c):
        if c["conversion_action_id"] is not None:
            k = key + (c["conversion_action_id"],)
            if k in kca_dup:
                return None
            r = kca.get(k)
            if r is None:
                return 0.0 if kca_full else None
        else:
            if key in km_dup:
                return None
            r = km.get(key)
            if r is None:
                return 0.0 if km_full else None
        v = r.get(c["metric"])
        return ctx.money(v) if c["metric"] in MONEY_METRICS else V.num(v)

    seen: set[str] = set()
    for i, raw_rule in enumerate(raw):
        rule, bad, missing = _validate_rule(raw_rule, seen, actions)
        given = raw_rule.get("rule_id") if isinstance(raw_rule, dict) else None
        rid = rule["rule_id"] if rule else (str(given).strip() if given not in (None, "") else f"#{i}")
        seen.add(rid)
        if bad:
            chk.partial(f"rule {rid} rejected: " + "; ".join(bad))
            continue
        if missing:
            chk.partial(f"rule {rid} not evaluated: conversion actions cannot be resolved", missing)
            continue
        conds = rule["conditions"]
        need = set()
        for c in conds:
            if c["conversion_action_id"] is not None:
                need |= {f"{KCA} (file)"} if t_kca is None else {f"{KCA}:{x}" for x in t_kca.missing(KCA_COLS)}
            else:
                need |= {"keyword_metrics (file)"} if t_km is None else {
                    f"keyword_metrics:{x}" for x in t_km.missing(["keyword_id", "campaign_id", "ad_group_id", c["metric"]])}
        if need:
            chk.partial(f"rule {rid} not evaluated: required evidence missing", sorted(need))
            continue
        if any(c["metric"] in CONV_METRICS for c in conds) and ctx.mature is not True:
            chk.partial(f"rule {rid} not evaluated: conversion conditions need a mature window ({ctx.maturity_note})")
            continue
        target, undetermined, values = [], [], {}
        for key in sorted(inv):
            vals = [value(key, c) for c in conds]
            res = [None if v is None else RULE_OPS[c["op"]](v, c["value"]) for v, c in zip(vals, conds)]
            values[key] = vals
            if False in res:
                continue
            (target if all(x is True for x in res) else undetermined).append(key)
        ref = lambda k: {"campaign_id": k[0], "ad_group_id": k[1], "keyword_id": k[2]}
        label = rule["label"]
        spec = {"rule_id": rid, "label": label, "conditions": conds, "window": period or "report",
                "keywords_evaluated": len(inv), "maturity": ctx.maturity_note}
        if undetermined:
            chk.partial(f"rule {rid}: {len(undetermined)} keywords undetermined (metric rows absent from an "
                        f"incomplete table or unknown cells); excluded from add/remove")
        if "labels" not in kw_cols:
            chk.partial(f"rule {rid}: current keyword labels unknown; diff not computed", ["keywords:labels"])
            chk.observe(f"Rule {rid}: keywords that should carry '{label}'", **spec,
                        should_carry=[ref(k) for k in target], undetermined=[ref(k) for k in undetermined])
            continue
        want = V.norm_text(label)
        current = [k for k in sorted(inv) if want in {V.norm_text(x) for x in V.split_list(inv[k].get("labels"), (";", "|", ","))}]
        tset, cset, uset = set(target), set(current), set(undetermined)
        add = sorted(tset - cset)
        remove = sorted(k for k in cset - tset if k not in uset)
        chk.observe(f"Rule {rid}: {len(target)} should carry '{label}', {len(current)} carry it", **spec,
                    should_carry=[ref(k) for k in target], currently_carry=[ref(k) for k in current],
                    add=[ref(k) for k in add], remove=[ref(k) for k in remove],
                    undetermined=[ref(k) for k in undetermined])
        if not (add or remove):
            continue
        chk.finding("label_rule_diff", "Info", {"rule_id": rid, "label": label},
                    f"Rule {rid}: add '{label}' to {len(add)} keywords, remove it from {len(remove)}",
                    evidence={**spec, "add": [ref(k) for k in add], "remove": [ref(k) for k in remove],
                              "should_carry": len(target), "currently_carry": len(current),
                              "undetermined": len(undetermined)},
                    calculation={"metric_values": [{**ref(k), "values": {
                        f"{c['metric']}@{c['conversion_action_id'] or 'all'}": v for c, v in zip(conds, values[k])}}
                        for k in add + remove],
                        "sources": {"by_action": KCA, "other_metrics": "keyword_metrics", "labels": "keywords:labels"}},
                    recommendation=f"Proposal only: the owner reviews and applies/removes label '{label}' on the "
                                   f"listed keywords; the script never labels.",
                    uncertainty="Rule thresholds are the client's declaration; conversions may still be restated.")


def run(ctx) -> None:
    """Run label inventory, coverage, external/label_policy compliance, unattached-label and merge-proposal checks.

    Rules:   Coverage only where base table AND association rows exist; ENABLED/PAUSED separate; empty scope =
             undefined. Unparseable eligibility_rule → partial. Policy gaps are Info; ai_review (Warning outcome
             'breaks_consumer') only when the rule row has consumer_id + observed_failure + evidence_ref.
             'unattached_in_export' Info needs all four association levels manifest-complete. Never proposes deletion;
             merges are Info reviews. label_rule_evaluation is not_applicable without profile.label_rules; a rule
             with an unknown/ambiguous conversion action, metric or op is rejected (partial); conversion conditions
             need ctx.mature True; absent metric rows count as 0 only from a manifest-complete table; undetermined
             keywords never enter add/remove; output is an Info label_rule_diff proposal, never a label change.
    """
    ents = _entities(ctx)

    # -- step 2: label inventory and near-duplicate names
    inv = ctx.check("label_inventory", "Label inventory and near-duplicate names", {INV: INV_COLS})
    labels: dict[str, dict] = {}
    clusters: dict[str, list[str]] = {}
    if inv.runnable:
        for r in sorted(ctx.rows(INV), key=lambda r: str(r.get("label_id"))):
            labels[str(r.get("label_id"))] = r
            if str(r.get("status") or "").upper() != "REMOVED":
                clusters.setdefault(_norm(r.get("name")), []).append(str(r.get("label_id")))
        inv.observe("Label inventory", labels=len(labels),
                    by_status={s: sum(1 for x in labels.values() if str(x.get("status") or "").upper() == s)
                               for s in sorted({str(x.get("status") or "").upper() for x in labels.values()})})
        for key, ids in sorted(clusters.items()):
            names = sorted({labels[i].get("name") for i in ids})
            if len(ids) > 1:
                inv.finding("similar_label_names", "Info", {"label_ids": sorted(ids)},
                            f"Labels {sorted(ids)} normalize to the same name ({names})",
                            evidence={"names": {i: labels[i].get("name") for i in ids}},
                            recommendation="Review consumers before any merge; similar names can differ in meaning.",
                            uncertainty="Name similarity only; dependencies not reviewed.")

    # -- step 3 (base export fallback): campaign label NAMES from campaigns.labels — no IDs, inventory only
    names = ctx.check("campaign_label_names", "Campaign label names from the campaign export (names, not IDs)",
                      {"campaigns": ["id", "status", "labels"]})
    if names.runnable:
        by_status: dict[str, list] = {}
        per_label: dict[str, list[str]] = {}
        for c in sorted(ctx.rows("campaigns"), key=lambda r: str(r.get("id"))):
            st = str(c.get("status") or "").upper()
            if st == "REMOVED":
                continue
            ls = V.split_list(c.get("labels"), (";", "|", ","))
            by_status.setdefault(st, [0, 0])
            by_status[st][0] += 1 if ls else 0
            by_status[st][1] += 1
            for l in ls:
                per_label.setdefault(l, []).append(str(c.get("id")))
        names.observe("Campaign any-label coverage from label names", coverage={
            s: {"labeled": v[0], "applicable": v[1], "coverage": V.ratio(v[0], v[1])} for s, v in sorted(by_status.items())},
            campaigns_per_label={k: v for k, v in sorted(per_label.items())})
        names.partial("label names only: no label IDs, policy compliance and other levels need label_associations")

    # -- step 3: any-label coverage per supplied entity type
    cov = ctx.check("label_coverage", "Any-label coverage per supplied entity level", {ASSOC: ASSOC_COLS})
    assoc: dict[tuple, set[str]] = {}
    levels_in_assoc: set[str] = set()
    if cov.runnable:
        orphan = 0
        for r in ctx.rows(ASSOC):
            t = _etype(r.get("entity_type"))
            eid = str(r.get("entity_id") or (r.get("campaign_id") if t == "campaign" else r.get("ad_group_id") if t == "ad_group" else "") or "")
            levels_in_assoc.add(t)
            if t not in ents or eid not in ents[t]:
                orphan += 1
                continue
            assoc.setdefault((t, eid), set()).add(str(r.get("label_id")))
        if orphan:
            cov.partial(f"{orphan} associations reference entities/levels absent from supplied inventories")
        for t in sorted(ents):
            if t not in levels_in_assoc:
                cov.partial(f"{t}: no association rows; coverage for this level unknown (not zero)")
                continue
            for status in ("ENABLED", "PAUSED"):
                scope = [i for i, e in ents[t].items() if e["status"] == status]
                labeled = sum(1 for i in scope if assoc.get((t, i)))
                cov.observe(f"{t} {status} any-label coverage", entity_type=t, status=status, labeled=labeled,
                            applicable=len(scope), coverage=V.ratio(labeled, len(scope)))
        for t in sorted(set(LEVELS) - set(ents)):
            cov.partial(f"{t}: base inventory not supplied; level excluded", [f"{LEVELS[t]} (file)"])

    # -- step 4: declared policy compliance
    pol = ctx.check("policy_compliance", "Declared label policies vs associations", {POL: POL_COLS, ASSOC: ASSOC_COLS})
    if pol.runnable:
        for r in sorted(ctx.rows(POL), key=lambda r: str(r.get("rule_id"))):
            rid, t = str(r.get("rule_id")), _etype(r.get("entity_type"))
            if t not in ents or t not in levels_in_assoc:
                pol.partial(f"rule {rid}: {t} inventory or associations not supplied")
                continue
            groups = [[x.strip() for x in g.split("|") if x.strip()] for g in str(r.get("required_label_ids") or "").split(";")]
            groups = [g for g in groups if g]
            undefined = sorted({x for g in groups for x in g} - set(labels)) if labels else []
            missing, contradictory, unknown = [], [], 0
            for eid in sorted(ents[t]):
                e = ents[t][eid]
                if e["status"] == "REMOVED":
                    continue
                ok = eligible(r.get("eligibility_rule"), e)
                if ok is None:
                    unknown += 1
                    break
                if not ok:
                    continue
                have = assoc.get((t, eid), set())
                for g in groups:
                    n = len(have & set(g))
                    if n == 0:
                        missing.append({"entity_id": eid, "campaign_id": e["campaign_id"], "status": e["status"], "required": g})
                    elif len(g) > 1 and n > 1:
                        contradictory.append({"entity_id": eid, "labels": sorted(have & set(g)), "exclusive_group": g})
            if unknown:
                pol.partial(f"rule {rid}: eligibility_rule '{r.get('eligibility_rule')}' not machine-evaluable")
                continue
            ev = {"rule_id": rid, "entity_type": t, "eligibility_rule": r.get("eligibility_rule"),
                  "required_label_ids": groups, "undefined_label_ids": undefined, "missing": missing,
                  "contradictory": contradictory, "consumer_id": r.get("consumer_id"),
                  "expected_behavior": r.get("expected_behavior"), "observed_failure": r.get("observed_failure"),
                  "evidence_ref": r.get("evidence_ref"), "owner": r.get("owner"), "reviewed_at": r.get("reviewed_at")}
            pol.observe(f"Rule {rid}: {len(missing)} missing, {len(contradictory)} contradictory", **{k: ev[k] for k in
                        ("rule_id", "entity_type", "consumer_id")}, missing=len(missing), contradictory=len(contradictory))
            if not (missing or contradictory or undefined):
                continue
            ent = {"rule_id": rid, "entity_type": t}
            prov = pol.finding("policy_label_gap", "Info", ent,
                               f"Rule {rid}: {len(missing)} eligible {t}s lack required labels, {len(contradictory)} contradictory, "
                               f"undefined labels {undefined}", evidence=ev,
                               recommendation="Owner reviews labeling for the declared consumer; no labels are applied.",
                               uncertainty="Consumer impact not established by associations alone.")
            if r.get("consumer_id") and str(r.get("observed_failure") or "").strip() and r.get("evidence_ref"):
                pol.review("policy_label_gap", ent,
                           f"Does the observed failure of consumer {r.get('consumer_id')} result from these missing/"
                           f"contradictory labels?", evidence=ev, provisional=prov,
                           outcomes={"breaks_consumer": {"severity": "Warning", "recommendation":
                                                         "Fix labels for the listed entities after owner review."},
                                     "unrelated": {"severity": "Info", "recommendation": "Keep as a coverage gap."},
                                     "uncertain": {"severity": "Info", "recommendation": "Ask the consumer owner."}},
                           guidance="breaks_consumer needs proposal.evidence_ref equal to the rule's evidence_ref.")

    # -- step 5: unattached labels
    un = ctx.check("unattached_labels", "Labels without associations in the exported scopes", {INV: INV_COLS, ASSOC: ASSOC_COLS})
    if un.runnable:
        used = {lid for s in assoc.values() for lid in s}
        t_assoc = ctx.table(ASSOC)
        full = set(LEVELS) <= levels_in_assoc and t_assoc is not None and t_assoc.complete is True
        idle = sorted(l for l, r in labels.items() if l not in used and str(r.get("status") or "").upper() != "REMOVED")
        if not full:
            un.partial("associations do not cover all four levels with a complete manifest: unattached ≠ unused")
            un.observe("Labels without associations in supplied levels", label_ids=idle, levels=sorted(levels_in_assoc))
        for lid in idle if full else []:
            un.finding("unattached_in_export", "Info", {"label_id": lid},
                       f"Label {lid} '{labels[lid].get('name')}' has no association in any exported level",
                       evidence={"levels": sorted(levels_in_assoc)},
                       recommendation="Review consumer dependencies before any cleanup; never delete from this evidence alone.",
                       uncertainty="Consumers outside Ads may still use it.")

    # -- step 6: consumer dependencies
    dep = ctx.check("consumer_dependencies", "Declared report/rule dependencies per label", {POL: POL_COLS})
    consumers: dict[str, list[str]] = {}
    if dep.runnable:
        for r in ctx.rows(POL):
            for g in str(r.get("required_label_ids") or "").replace("|", ";").split(";"):
                if g.strip() and r.get("consumer_id"):
                    consumers.setdefault(g.strip(), []).append(str(r.get("consumer_id")))
        dep.observe("Consumers per label", consumers={k: sorted(set(v)) for k, v in sorted(consumers.items())})
    else:
        dep.observe("Without policy, labels are optional")

    # -- steps 7-8: taxonomy/merge proposals for similar names, dependency-aware
    prop = ctx.check("merge_proposals", "Owner-review merge/rename proposals", {INV: INV_COLS})
    if prop.runnable:
        if not dep.runnable:
            prop.partial("no label policy: consumers unknown, merges cannot be dependency-checked", dep.missing)
        for key, ids in sorted(clusters.items()):
            if len(ids) < 2:
                continue
            affected = sorted({c for i in ids for c in consumers.get(i, [])})
            prop.review("label_merge_proposal", {"label_ids": sorted(ids)},
                        f"Should labels {sorted(ids)} be merged/renamed, given consumers {affected}?",
                        evidence={"names": {i: labels[i].get("name") for i in ids}, "consumers": affected,
                                  "policy_supplied": dep.runnable},
                        outcomes={"merge_proposed": {"severity": "Info", "recommendation":
                                                     "Owner reviews the merge with every affected consumer."},
                                  "keep_separate": {"severity": None, "recommendation": "Different meanings; keep."}},
                        guidance="merge_proposed needs proposal {keep_label_id, merge_label_ids, consumers}; never deletion.")

    # -- opt-in: profile.label_rules (index #51) — keyword label target set vs current labels
    _label_rules(ctx)


def verify(ctx, item, decision) -> list[str]:
    """Rules: consumer Warning needs the rule's evidence_ref; merges must list every affected consumer."""
    p = decision.get("proposal") or {}
    if item.condition_key == "policy_label_gap" and decision.get("outcome") == "breaks_consumer":
        if str(p.get("evidence_ref") or "") != str(item.evidence.get("evidence_ref") or "") or not p.get("evidence_ref"):
            return ["breaks_consumer needs proposal.evidence_ref equal to the rule's evidence_ref"]
    if item.condition_key == "label_merge_proposal" and decision.get("outcome") == "merge_proposed":
        ids = set(item.entity["label_ids"])
        problems = []
        if not item.evidence.get("policy_supplied"):
            problems.append("no label policy supplied: dependency review incomplete, merge cannot be proposed")
        keep, merge = str(p.get("keep_label_id") or ""), {str(x) for x in p.get("merge_label_ids") or []}
        if keep not in ids or not merge or not merge <= ids or keep in merge:
            problems.append("keep_label_id and merge_label_ids must partition labels of this cluster")
        missing = sorted(set(item.evidence.get("consumers") or []) - {str(c) for c in p.get("consumers") or []})
        if missing:
            problems.append(f"proposal.consumers must include every affected consumer: missing {missing}")
        if str(p.get("action") or "").lower() == "delete":
            problems.append("deletion is never proposed")
        return problems
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
