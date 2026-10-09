"""check.py — skill-029 deterministic RSA asset-label joins, label summaries and ad-grain outcome comparisons.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-029-rsa-asset-performance-analysis/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #105 Ad Performance Report (Google) — clean-room reimplementation of per-ad CTR/CVR/CPA reporting at ad grain
         index #5 split-testing winner script (markgrowth), #12 Ad Rotate Analysis & Pause Losing Ads (Brainlabs),
         #13 Analyse Ads and Pause Underperforming Ads (Brainlabs) — clean-room reimplementation of the within-ad-group
         loser/winner decision as a gated guardrail comparison + ai_review; pausing and copy export are NOT done
rules:   Start from the RSA inventory and left-join custom/rsa_asset_labels on campaign/ad group/ad IDs + asset_id +
         field_type; name-only rows, duplicate association keys and non-RSA/non-headline/description rows are
         excluded and reported. Absent labels are UNAVAILABLE coverage, never Low.
         Label vocabulary is preserved as supplied (Learning/Pending/Unrated kept); Low and all-Learning/Unrated
         are Info; 'no Best' is an observation, not a defect.
         Ad metrics stay at ad grain; asset metrics are used only when metric_scope and attribution_definition
         are supplied. An ad CTR is never attributed to one headline.
         Guardrail comparison: ctx.mature True, same ad group, both ads >= min_conversions (CPA/ROAS) and a target
         from ctx.params.target_cpa or a ROAS target; Warning only via ai_review 'corroborated_copy_issue' whose
         proposal cites Low-labelled asset_ids of that ad or an evidence_ref. No significance tests (serving is not
         randomized), no pausing, no account-wide winner list.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks03 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-029-rsa-asset-performance-analysis"
VERSION = "1.0.0"

ADS_NEEDS = {"ads": ["id", "campaign_id", "ad_group_id", "type", "status"]}
LABEL_COLS = ["campaign_id", "ad_group_id", "ad_id", "asset_id", "field_type", "ad_type", "performance_label",
              "snapshot_at"]
METRIC_COLS = ["ad_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"]
_FIELDS = {"HEADLINE": "headlines", "DESCRIPTION": "descriptions"}
_PENDING = {"LEARNING", "PENDING", "UNRATED", "UNAVAILABLE", "UNKNOWN"}


def _texts(cell) -> list | None:
    if cell is None:
        return None
    s = str(cell).strip()
    if s.startswith("["):
        try:
            return list(json.loads(s))
        except ValueError:
            return None
    return V.split_list(s, (" | ", "|", "\n"))


def _key(r) -> tuple:
    return (str(r.get("campaign_id") or ""), str(r.get("ad_group_id") or ""), str(r.get("ad_id") or r.get("id") or ""))


def _roas_target(ctx, cid: str) -> tuple[float | None, str]:
    row = next((r for r in ctx.rows("campaigns") if str(r.get("id")) == cid), None)
    t = V.num(row.get("target_roas")) if row else None
    if t and t > 0:
        return ctx.rate(row.get("target_roas")) if ctx.rates_format == "percent" else t, f"campaigns.target_roas[{cid}]"
    objectives = ctx.profile.get("campaign_objectives") or {}
    obj = next((v for k, v in objectives.items() if str(k) == cid), None) if isinstance(objectives, dict) else None
    t = V.num((obj or {}).get("target_roas")) if isinstance(obj, dict) else None
    return (t, f"profile.campaign_objectives[{cid}].target_roas") if t and t > 0 else (None, "no ROAS target")


def run(ctx) -> None:
    """Run association-key, join, label-vocabulary, label-summary, ad-grain, guardrail and Low-label checks.

    Rules:   Name-only, duplicate and non-RSA association rows are excluded (partial); ads without labels are
             UNAVAILABLE, never Low. Low and all-Learning/Pending/Unrated are Info; 'no Best' is an observation.
             Guardrail review needs ctx.mature True, >= 2 enabled ads in the ad group with >= min_conversions and a
             CPA/ROAS target; Warning only via ai_review 'corroborated_copy_issue'. Nothing is paused.
    """
    join = ctx.check("rsa_association_join", "RSA inventory left-joined to asset associations",
                     {**ADS_NEEDS, "custom/rsa_asset_labels": LABEL_COLS})
    keys = ctx.check("association_keys", "Association keys, duplicates and name-only rows",
                     {"custom/rsa_asset_labels": LABEL_COLS})
    vocab = ctx.check("label_vocabulary", "Supplied label vocabulary and availability states",
                      {"custom/rsa_asset_labels": LABEL_COLS})
    summ = ctx.check("label_summary", "Labels within ad and field type; asset reuse",
                     {**ADS_NEEDS, "custom/rsa_asset_labels": LABEL_COLS})
    ads = []
    if ctx.table("ads") and not ctx.table("ads").missing(ADS_NEEDS["ads"]):
        ads = sorted((r for r in ctx.rows("ads") if str(r.get("type") or "").upper() == "RESPONSIVE_SEARCH_AD"),
                     key=lambda r: str(r.get("id")))
    by_key = {_key(r): r for r in ads}
    assoc: dict[tuple, list[dict]] = {}
    low_by_ad: dict[tuple, dict] = {}
    if keys.runnable:
        seen, dups, missing_ids, other, orphans = set(), [], 0, 0, []
        for r in sorted(ctx.rows("custom/rsa_asset_labels"),
                        key=lambda r: (_key(r), str(r.get("asset_id")), str(r.get("field_type")), str(r.get("snapshot_at")))):
            k = _key(r)
            if not all(k) or not r.get("asset_id"):
                missing_ids += 1
                continue
            if str(r.get("ad_type") or "").upper() != "RESPONSIVE_SEARCH_AD" or \
                    str(r.get("field_type") or "").upper() not in _FIELDS:
                other += 1
                continue
            full = (*k, str(r.get("asset_id")), str(r.get("field_type")).upper(), str(r.get("snapshot_at")))
            if full in seen:
                dups.append(full)
                continue
            seen.add(full)
            if ads and k not in by_key:
                orphans.append(k[2])
                continue
            assoc.setdefault(k, []).append(r)
        if missing_ids:
            keys.partial(f"{missing_ids} association rows lack account/campaign/ad group/ad/asset IDs (name-only joins rejected)",
                         ["custom/rsa_asset_labels:ad_id", "custom/rsa_asset_labels:asset_id"])
        if dups:
            keys.partial(f"{len(dups)} duplicate association keys excluded")
        if orphans:
            keys.partial(f"association rows for ads not in the RSA inventory: {sorted(set(orphans))}")
        keys.observe("Association key audit", kept=sum(len(v) for v in assoc.values()), duplicates=len(dups),
                     missing_ids=missing_ids, non_rsa_or_other_fields=other, orphans=len(orphans))
    if join.runnable:
        no_labels, mismatch = [], []
        for ad in ads:
            k = _key(ad)
            rows = assoc.get(k, [])
            if not rows:
                no_labels.append(k[2])
                continue
            for ft, col in _FIELDS.items():
                arr = _texts(ad.get(col))
                n = sum(1 for r in rows if str(r.get("field_type")).upper() == ft)
                if arr is not None and n != len(arr):
                    mismatch.append({"ad_id": k[2], "field": ft, "associations": n, "array": len(arr)})
        join.observe("RSA to association coverage", rsa_ads=len(ads), ads_with_associations=len(ads) - len(no_labels),
                     count_mismatches=mismatch)
        if no_labels:
            join.partial(f"labels unavailable (not Low) for ads {no_labels}")
        if mismatch:
            join.partial("association counts differ from exported RSA arrays; asset coverage incomplete")
    if vocab.runnable:
        counts: dict[str, int] = {}
        snaps, sources = set(), set()
        for rows in assoc.values():
            for r in rows:
                lab = str(r.get("performance_label") or "").upper() or "UNAVAILABLE"
                counts[lab] = counts.get(lab, 0) + 1
                snaps.add(str(r.get("snapshot_at")))
                sources.add(str(r.get("source_ref")))
        vocab.observe("Label vocabulary as supplied", counts=counts, snapshots=sorted(snaps), sources=sorted(sources),
                      note="no label history supplied → no persistent-downgrade inference")
    if summ.runnable:
        reuse: dict[str, int] = {}
        for k, rows in sorted(assoc.items()):
            ad = by_key.get(k)
            if ad is None or str(ad.get("status") or "").upper() != "ENABLED":
                continue
            for r in rows:
                reuse[str(r.get("asset_id"))] = reuse.get(str(r.get("asset_id")), 0) + 1
            for ft in _FIELDS:
                fr = [r for r in rows if str(r.get("field_type")).upper() == ft and
                      str(r.get("association_status") or "ENABLED").upper() == "ENABLED"]
                if not fr:
                    continue
                labs = [str(r.get("performance_label") or "").upper() or "UNAVAILABLE" for r in fr]
                entity = {"campaign_id": k[0], "ad_group_id": k[1], "ad_id": k[2], "field_type": ft}
                low = [{"asset_id": str(r.get("asset_id")), "text": r.get("text"), "pin": r.get("pin")}
                       for r, lab in zip(fr, labs) if lab == "LOW"]
                ev = {"labels": dict(sorted({l: labs.count(l) for l in labs}.items())), "associations": len(fr),
                      "snapshot_at": sorted({str(r.get("snapshot_at")) for r in fr})}
                if low:
                    f = summ.finding("low_label_assets", "Info", entity,
                                     f"Ad {k[2]} {ft.lower()}s: {len(low)} of {len(fr)} associations labelled Low",
                                     evidence={**ev, "low_assets": low},
                                     recommendation="Review the Low text for a specific copy hypothesis; not an automatic replacement.",
                                     uncertainty="Contextual label for this ad only; not a causal or account-wide ranking.")
                    low_by_ad[(k, ft)] = {"finding": f, "low": low, "ev": ev}
                elif all(l in _PENDING for l in labs):
                    summ.finding("labels_all_learning_or_unrated", "Info", entity,
                                 f"Ad {k[2]} {ft.lower()}s: all {len(fr)} associations are Learning/Pending/Unrated",
                                 evidence=ev, recommendation="Wait for labels; no copy change implied.",
                                 uncertainty="Label availability depends on traffic and platform timing.")
                if "BEST" not in labs:
                    summ.observe(f"Ad {k[2]} {ft.lower()}s have no Best label (not a defect)", **entity)
        summ.observe("Asset reuse across enabled associations", reused_assets={a: n for a, n in sorted(reuse.items()) if n > 1},
                     distinct_assets=len(reuse))

    # -- step 5: ad-grain performance (index #105)
    perf = ctx.check("ad_grain_performance", "Ad-grain outcomes and supplied asset attribution",
                     {**ADS_NEEDS, "ad_metrics": METRIC_COLS})
    metrics: dict[tuple, dict] = {}
    if perf.runnable:
        if ctx.mature is not True:
            perf.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; CVR/CPA not reported")
        dup = set()
        for m in sorted(ctx.rows("ad_metrics"), key=lambda r: _key(r)):
            k = _key(m)
            if k in metrics or k in dup:
                dup.add(k)
                metrics.pop(k, None)
                continue
            metrics[k] = m
        if dup:
            perf.partial(f"duplicate/segmented ad_metrics rows for ads {sorted(x[2] for x in dup)} excluded")
        for ad in ads:
            m = metrics.get(_key(ad))
            if not m:
                continue
            imp, clk, conv = V.num(m.get("impressions")), V.num(m.get("clicks")), V.num(m.get("conversions"))
            cost = ctx.money(m.get("cost"))
            mature = ctx.mature is True
            perf.observe(f"Ad {ad.get('id')} outcomes", ad_id=str(ad.get("id")), ad_group_id=str(ad.get("ad_group_id")),
                         impressions=imp, clicks=clk, cost=cost, conversions=conv if mature else None,
                         ctr=V.ratio(clk, imp), cvr=V.ratio(conv, clk) if mature else None,
                         cpa=V.ratio(cost, conv) if mature else None, currency=ctx.currency,
                         window=[ctx.period_start, ctx.period_end])
        am = ctx.table("custom/rsa_asset_metrics")
        if am is None:
            perf.observe("Asset-attributed metrics not supplied; ad CTR is not a headline CTR")
        elif am.missing(["ad_id", "asset_id", "metric_scope", "attribution_definition"]):
            perf.partial("rsa_asset_metrics lacks attribution fields; not used",
                         [f"custom/rsa_asset_metrics:{c}" for c in am.missing(
                             ["ad_id", "asset_id", "metric_scope", "attribution_definition"])])
        else:
            usable = [r for r in am.rows if r.get("metric_scope") and r.get("attribution_definition")]
            perf.observe("Asset metrics with declared scope/attribution", usable_rows=len(usable),
                         unusable_rows=len(am.rows) - len(usable),
                         scopes=sorted({str(r.get("metric_scope")) for r in usable}))

    # -- step 6: matched guardrail comparison (index #5/#12/#13)
    cmp_ = ctx.check("matched_comparison", "Matched mature ad outcomes vs business guardrail",
                     {**ADS_NEEDS, "ad_metrics": METRIC_COLS})
    if cmp_.runnable:
        min_conv = ctx.params.get("min_conversions")
        if ctx.mature is not True:
            cmp_.partial(f"maturity {ctx.mature}: {ctx.maturity_note}; no outcome comparisons")
        else:
            groups: dict[tuple, list] = {}
            for ad in ads:
                m = metrics.get(_key(ad))
                if m is None or str(ad.get("status") or "").upper() != "ENABLED":
                    continue
                vals = {"cost": ctx.money(m.get("cost")), "conversions": V.num(m.get("conversions")),
                        "value": V.num(m.get("conversion_value")), "clicks": V.num(m.get("clicks")),
                        "impressions": V.num(m.get("impressions"))}
                groups.setdefault(_key(ad)[:2], []).append((str(ad.get("id")), vals))
            unresolved = set()
            for (cid, gid), members in sorted(groups.items()):
                qual = [(a, v) for a, v in members if v["conversions"] is not None and v["cost"] is not None
                        and v["conversions"] >= min_conv.value]
                if len(qual) < 2:
                    cmp_.observe(f"Ad group {gid}: fewer than two ads with >= {min_conv.value} conversions",
                                 campaign_id=cid, ad_group_id=gid, qualified=len(qual), ads=len(members))
                    continue
                cpa_t, cpa_src = ctx.params.target_cpa(cid)
                roas_t, roas_src = (None, "") if cpa_t else _roas_target(ctx, cid)
                if cpa_t is None and roas_t is None:
                    unresolved.add(f"{cid}: {cpa_src}; {roas_src}")
                    continue
                peers = []
                for a, v in qual:
                    cpa = V.ratio(v["cost"], v["conversions"])
                    roas = V.ratio(v["value"], v["cost"]) if v["value"] is not None else None
                    outside = (cpa is not None and cpa > cpa_t) if cpa_t else (roas is not None and roas < roas_t)
                    peers.append({"ad_id": a, **v, "cpa": cpa, "roas": roas, "outside_guardrail": outside})
                inside = [p for p in peers if not p["outside_guardrail"]]
                for p in peers:
                    if not p["outside_guardrail"] or not inside:
                        continue
                    k = (cid, gid, p["ad_id"])
                    lows = [x for (kk, _ft), x in low_by_ad.items() if kk == k]
                    entity = {"campaign_id": cid, "ad_group_id": gid, "ad_id": p["ad_id"]}
                    cmp_.review("guardrail_outcome_copy_issue", entity,
                                f"Ad {p['ad_id']} is outside the business guardrail versus qualified peers in ad group "
                                f"{gid}. Is a specific copy issue corroborated (e.g. Low-labelled text, contradiction)?",
                                evidence={"ad": p, "peers_inside_guardrail": inside,
                                          "guardrail": {"target_cpa": cpa_t, "source": cpa_src} if cpa_t else
                                          {"target_roas": roas_t, "source": roas_src},
                                          "min_conversions": min_conv.value, "window": [ctx.period_start, ctx.period_end],
                                          "low_asset_ids": sorted(a["asset_id"] for x in lows for a in x["low"]),
                                          "currency": ctx.currency},
                                outcomes={"corroborated_copy_issue": {"severity": "Warning", "recommendation":
                                                                      "Brief a controlled copy test via skill-032; no pausing."},
                                          "no_copy_issue": {"severity": None, "recommendation":
                                                            "Outcome gap is not attributed to copy; check other factors."},
                                          "uncertain": {"severity": "Info", "recommendation":
                                                        "Collect asset evidence before any copy change."}},
                                guidance="Serving is not randomized: no significance claims or causal winners. "
                                         "corroborated_copy_issue needs proposal.asset_ids (Low-labelled ids of this ad) "
                                         "or proposal.evidence_ref.")
                cmp_.observe(f"Ad group {gid} guardrail comparison", campaign_id=cid, ad_group_id=gid, peers=peers,
                             target_cpa=cpa_t, target_roas=roas_t, source=cpa_src if cpa_t else roas_src,
                             min_conversions=min_conv.value)
            for u in sorted(unresolved):
                cmp_.partial(f"no business guardrail for campaign {u}")

    # -- step 7: Low-label copy hypotheses
    low = ctx.check("low_label_review", "Copy hypotheses for Low-associated text",
                    {**ADS_NEEDS, "custom/rsa_asset_labels": LABEL_COLS})
    if low.runnable:
        for (k, ft), x in sorted(low_by_ad.items()):
            entity = {"campaign_id": k[0], "ad_group_id": k[1], "ad_id": k[2], "field_type": ft}
            low.review("low_label_assets", entity,
                       f"For ad {k[2]} {ft.lower()}s labelled Low, is there a specific, constraint-preserving copy "
                       f"hypothesis?",
                       evidence={**x["ev"], "low_assets": x["low"], "brand_terms": ctx.profile.get("brand_terms")},
                       outcomes={"copy_hypothesis": {"severity": "Info", "recommendation":
                                                     "Optional controlled test via skill-032 with the stated hypothesis."},
                                 "constrained_keep": {"severity": None, "recommendation":
                                                      "Keep: legal/brand constraint or pin requirement (skill-028)."},
                                 "uncertain": {"severity": "Info", "recommendation": "Keep and re-check with later labels."}},
                       guidance="Best patterns elsewhere are inspiration, not replacement instructions. "
                                "copy_hypothesis needs proposal.hypothesis.",
                       provisional=x["finding"])
        low.observe("Low-label review items", count=len(low_by_ad))

    route = ctx.check("test_brief_routing", "Controlled-test brief and routing", ADS_NEEDS)
    route.observe("Routing and bulk coverage", rsa_ads=len(ads), ads_with_labels=len(assoc),
                  duplication_owner="skill-025/skill-026", pins_owner="skill-028", test_owner="skill-032",
                  note="no automatic pausing or bulk changes")


def verify(ctx, item, decision) -> list[str]:
    """Rules: copy-issue Warning cites this ad's Low asset_ids or an evidence_ref; hypotheses must be stated."""
    outcome, p = decision.get("outcome"), decision.get("proposal") or {}
    if outcome == "corroborated_copy_issue":
        allowed = set(item.evidence.get("low_asset_ids") or [])
        ids = {str(a) for a in p.get("asset_ids") or []}
        if p.get("evidence_ref"):
            return [f"asset_ids not Low-labelled on this ad: {sorted(ids - allowed)}"] if ids - allowed else []
        if not ids:
            return ["corroborated_copy_issue needs proposal.asset_ids or proposal.evidence_ref"]
        if ids - allowed:
            return [f"asset_ids not Low-labelled on this ad: {sorted(ids - allowed)}"]
        return []
    if outcome == "copy_hypothesis" and not str(p.get("hypothesis") or "").strip():
        return ["copy_hypothesis needs proposal.hypothesis"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
