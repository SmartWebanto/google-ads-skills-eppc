"""check.py — skill-149 deterministic promotion asset and countdown configuration review.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-149-promotional-extensions-countdown-customizers/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #4 AdWords Countdown Ad Updater (Derek Martin gist), #6 Sale Countdown and #7 Sales Countdown Calendar
         (Google Ads Scripts solutions) — clean-room reimplementation of "countdown targets the sale date" as a
         read-only comparison of the countdown's literal target date with the approved offer dates; no ad-param
         updates. #8 Ad Customizer setup (Google) — refused: it creates customizer sources/ads (account writes);
         only existing customizer/countdown configuration is reviewed here.
rules:   Config rows join offers by campaign_id only when that campaign has exactly one approved offer (per market is
         unknown in config) — otherwise the comparison is ambiguous and partial, never guessed.
         Coverage needs a linked, non-removed association in an eligible campaign; an unlinked asset proves nothing.
         configured_discount is compared numerically with discount_type/discount_value only when both parse
         unambiguously (percent vs amount); anything else goes to ai_review.
         Countdown syntax is never invented: only a single literal YYYY-MM-DD / YYYY/MM/DD date in countdown_raw_text
         is compared with offer end_at (Warning on mismatch; equal to start_at → review). No preview → Info.
         Expired config without dated serving after the offer end is Info; dated serving after end_at is Warning.
         Critical only via review outcome material_live_misleading with proposal.evidence_ref.
         Absence of promotion/countdown is an optional opportunity (Info), and only when promotion_config is
         manifest-complete. Never creates, updates or removes assets.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks15 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-149-promotional-extensions-countdown-customizers"
VERSION = "1.0.0"

OFFERS = "external/promotion_offers"
CONFIG = "custom/promotion_config"
_DEAD = ("REMOVED", "UNLINKED", "DELETED")
_DATE = re.compile(r"(?<!\d)(\d{4})[/-](\d{2})[/-](\d{2})(?!\d)")
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:\.\.|to|/)\s*(\d{4}-\d{2}-\d{2})")
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _linked(r) -> bool:
    return (_s(r.get("status")).upper() not in _DEAD and bool(_s(r.get("status")))
            and bool(_s(r.get("linking_level"))) and bool(_s(r.get("campaign_id"))))


def _serving_dates(v) -> list:
    out = []
    for part in V.split_list(v, (";", "|", ",")):
        m = _RANGE.fullmatch(part.strip())
        if m:
            a, b = V.parse_date(m.group(1)), V.parse_date(m.group(2))
            if a and b and a <= b:
                out += [a + timedelta(i) for i in range((b - a).days + 1)]
            continue
        d = V.parse_date(part)
        if d:
            out.append(d)
    return sorted(set(out))


def _discount(text) -> tuple[str | None, float | None]:
    """('percent'|'amount', value) from a configured discount cell; (None, None) when ambiguous."""
    s = _s(text)
    nums = _NUM.findall(s)
    if len(nums) != 1 or ("," in nums[0] and "." in nums[0]):
        return None, None
    val = float(nums[0].replace(",", "."))
    return ("percent" if "%" in s else "amount"), val


def _offer_kind(r) -> str | None:
    t = _s(r.get("discount_type")).lower()
    if "percent" in t or t in ("%", "pct"):
        return "percent"
    if "amount" in t or "money" in t or "fixed" in t:
        return "amount"
    return None


def _offers_by_campaign(ctx) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in ctx.rows(OFFERS):
        if _s(r.get("approved_by")):
            out.setdefault(_s(r.get("campaign_id")), []).append(r)
    return {k: sorted(v, key=lambda r: _s(r.get("offer_id"))) for k, v in out.items()}


def _cfg_entity(r) -> dict:
    return {"asset_or_ad_id": _s(r.get("asset_or_ad_id")), "association_id": _s(r.get("association_id")),
            "campaign_id": _s(r.get("campaign_id")), "ad_group_id": _s(r.get("ad_group_id"))}


def _critical_review(chk, ent, prov, question, evidence) -> None:
    chk.review(prov.condition_key, ent, question, evidence=evidence, provisional=prov,
               outcomes={"material_live_misleading": {"severity": "Critical", "recommendation":
                                                      "Escalate: stop the misleading offer delivery (request-only)."},
                         "not_material": {"severity": "Warning", "recommendation": "Correct the configuration."},
                         "uncertain": {"severity": "Warning", "recommendation": "Keep as Warning; request delivery proof."}},
               guidance="Critical needs dated live-delivery evidence of the wrong offer; cite it in proposal.evidence_ref.")


def run(ctx) -> None:
    """Run association, offer-term, countdown, expired-serving, optional-feature and correction-draft checks.

    Rules:   Only linked associations whose campaign has exactly one approved offer are compared; else partial.
             Parseable discount/window/countdown-date mismatch or dated serving after end_at → Warning; unparseable
             discounts, start-date countdowns and preview timezone checks → ai_review; Critical only via ai_review
             with dated serving. Missing preview, expired non-serving config and absent features (manifest-complete
             config only) → Info; correction drafts are observe-only.
    """
    cfg_needs = {CONFIG: ["asset_or_ad_id", "association_id", "snapshot_at", "campaign_id", "linking_level", "status"]}
    assoc = ctx.check("association_scope", "Promotion/countdown associations to eligible campaign scope", cfg_needs)
    latest: dict[str, dict] = {}
    if assoc.runnable:
        for r in sorted(ctx.rows(CONFIG), key=lambda r: (_s(r.get("association_id")), _s(r.get("snapshot_at")))):
            latest[_s(r.get("association_id")) or _s(r.get("asset_or_ad_id"))] = r
        camps = {_s(c.get("id")): _s(c.get("status")).upper() for c in ctx.rows("campaigns")}
        inventory = {_s(a.get("id")) for a in ctx.rows("assets")} | {_s(a.get("id")) for a in ctx.rows("ads")}
        unlinked = sorted(k for k, r in latest.items() if not _linked(r))
        ineligible = sorted(k for k, r in latest.items() if _linked(r) and camps
                            and camps.get(_s(r.get("campaign_id"))) not in ("ENABLED", None))
        unknown_camp = sorted(k for k, r in latest.items() if _linked(r) and camps and _s(r.get("campaign_id")) not in camps)
        if not camps:
            assoc.partial("campaigns inventory missing: campaign eligibility unknown", ["campaigns (file)"])
        if inventory:
            orphan = sorted(k for k, r in latest.items() if _s(r.get("asset_or_ad_id")) not in inventory)
            if orphan:
                assoc.partial(f"{len(orphan)} config rows reference IDs absent from assets/ads inventory")
        if unknown_camp:
            assoc.partial(f"{len(unknown_camp)} associations reference campaigns absent from the inventory")
        assoc.observe("Promotion/countdown associations", associations=len(latest), unlinked=unlinked,
                      linked_to_non_enabled_campaigns=ineligible,
                      linked_campaigns=sorted({_s(r.get("campaign_id")) for r in latest.values() if _linked(r)}))
    live = {k: r for k, r in latest.items() if _linked(r)}

    offers_ok = ctx.table(OFFERS) is not None
    terms = ctx.check("offer_terms", "Configured discount and dates versus approved offer",
                      {**cfg_needs, CONFIG: cfg_needs[CONFIG] + ["configured_discount", "start_date", "end_date",
                                                                 "actual_serving_dates"],
                       OFFERS: ["offer_id", "campaign_id", "discount_type", "discount_value", "start_at", "end_at",
                                "approved_by"]})
    by_camp = _offers_by_campaign(ctx) if offers_ok else {}
    conflicts = []
    if terms.runnable and assoc.runnable:
        for k in sorted(live):
            r = live[k]
            offers = by_camp.get(_s(r.get("campaign_id")), [])
            if len(offers) != 1:
                if offers:
                    terms.partial(f"association {k}: {len(offers)} approved offers in campaign; offer not identifiable")
                continue
            o = offers[0]
            ent = {**_cfg_entity(r), "offer_id": _s(o.get("offer_id"))}
            serving = _serving_dates(r.get("actual_serving_dates"))
            ev = {"configured_discount": r.get("configured_discount"), "offer_discount_type": o.get("discount_type"),
                  "offer_discount_value": o.get("discount_value"), "configured_window": [r.get("start_date"), r.get("end_date")],
                  "offer_window": [o.get("start_at"), o.get("end_at")], "offer_timezone": o.get("timezone"),
                  "landing_page_snapshot_ref": o.get("landing_page_snapshot_ref"), "approved_by": o.get("approved_by"),
                  "snapshot_at": r.get("snapshot_at"), "serving_dates_observed": len(serving)}
            if _s(r.get("configured_discount")):
                kind, val = _discount(r.get("configured_discount"))
                okind, oval = _offer_kind(o), V.num(o.get("discount_value"))
                if kind is None or okind is None or oval is None:
                    terms.review("offer_config_conflict", ent,
                                 f"Does configured discount '{_s(r.get('configured_discount'))}' match the approved "
                                 f"{_s(o.get('discount_type'))} {_s(o.get('discount_value'))} offer?",
                                 evidence=ev,
                                 outcomes={"conflicts": {"severity": "Warning", "recommendation":
                                                         "Correct to the approved offer (request-only)."},
                                           "matches": {"severity": None, "recommendation": "No change."},
                                           "uncertain": {"severity": "Info", "recommendation": "Ask the offer owner."}},
                                 guidance="Compare only the literal configured value with the approved offer terms.")
                elif kind != okind or abs(val - oval) > 1e-9:
                    f = terms.finding("offer_config_conflict", "Warning", ent,
                                      f"Configured discount '{_s(r.get('configured_discount'))}' differs from approved "
                                      f"{okind} {oval:g} for offer {_s(o.get('offer_id'))}",
                                      evidence=ev, calculation={"configured": [kind, val], "approved": [okind, oval]},
                                      recommendation=f"Set the discount to the approved {okind} {oval:g} (request-only).",
                                      uncertainty="Snapshot configuration; serving impact depends on eligibility dates.")
                    conflicts.append((f, r, o, "configured_discount", f"{oval:g}{'%' if okind == 'percent' else ''}"))
                    if serving:
                        _critical_review(terms, ent, f, "The conflicting discount has dated serving. Is this a material "
                                                        "live misleading offer delivery?", {**ev, "serving_dates": serving})
            cs, ce = V.parse_date(r.get("start_date")), V.parse_date(r.get("end_date"))
            os_, oe = V.parse_date(o.get("start_at")), V.parse_date(o.get("end_at"))
            if None not in (cs, ce, os_, oe) and (cs < os_ or ce > oe):
                f = terms.finding("offer_window_conflict", "Warning", ent,
                                  f"Configured dates {cs}..{ce} extend outside approved offer window {os_}..{oe}",
                                  evidence=ev, recommendation=f"Set start {os_} and end {oe} (request-only).",
                                  uncertainty="Timezone of configured dates versus offer timezone is not certified.")
                conflicts.append((f, r, o, "start_date/end_date", f"{os_}..{oe}"))
        terms.observe("Associations compared with approved offers", associations=len(live), conflicts=len(conflicts))

    cd = ctx.check("countdown_config", "Countdown target and preview versus intended offer end",
                   {CONFIG: ["asset_or_ad_id", "association_id", "campaign_id", "countdown_raw_text",
                             "countdown_timezone_mode", "preview_at", "preview_result"],
                    OFFERS: ["offer_id", "campaign_id", "start_at", "end_at", "timezone", "approved_by"]})
    if cd.runnable and assoc.runnable:
        n = 0
        for k in sorted(live):
            r = live[k]
            raw = _s(r.get("countdown_raw_text"))
            if not raw:
                continue
            n += 1
            offers = by_camp.get(_s(r.get("campaign_id")), [])
            ent = _cfg_entity(r)
            if not _s(r.get("preview_result")):
                cd.finding("countdown_unverified", "Info", ent, f"Countdown '{raw}' has no supplied preview",
                           evidence={"countdown_raw_text": raw, "timezone_mode": r.get("countdown_timezone_mode")},
                           recommendation="Request a dated preview in the intended timezone mode.",
                           uncertainty="Syntax and rendering are unverified without a preview.")
            if len(offers) != 1:
                cd.partial(f"association {k}: countdown offer not identifiable ({len(offers)} approved offers)")
                continue
            o = offers[0]
            ent = {**ent, "offer_id": _s(o.get("offer_id"))}
            dates = sorted({V.parse_date("-".join(m)) for m in _DATE.findall(raw)} - {None})
            os_, oe = V.parse_date(o.get("start_at")), V.parse_date(o.get("end_at"))
            ev = {"countdown_raw_text": raw, "target_dates": dates, "offer_window": [os_, oe],
                  "offer_timezone": o.get("timezone"), "countdown_timezone_mode": r.get("countdown_timezone_mode"),
                  "preview_at": r.get("preview_at"), "preview_result": r.get("preview_result")}
            outcomes = {"conflicts": {"severity": "Warning", "recommendation": "Correct the countdown target/timezone."},
                        "consistent": {"severity": None, "recommendation": "No change."},
                        "uncertain": {"severity": "Info", "recommendation": "Request a preview from the owner."}}
            if len(dates) == 1 and oe is not None and dates[0] not in (oe, os_):
                f = cd.finding("countdown_target_conflict", "Warning", ent,
                               f"Countdown targets {dates[0]} but the approved offer ends {oe}",
                               evidence=ev, recommendation=f"Point the countdown at the approved end {oe} (request-only).",
                               uncertainty="Account versus viewer timezone mode can shift the shown time, not the date literal.")
                conflicts.append((f, r, o, "countdown_raw_text", f"target {oe}"))
            elif len(dates) == 1 and dates[0] == os_ and os_ != oe:
                cd.review("countdown_target_conflict", ent,
                          f"Countdown targets the offer START {os_}. Is it intentionally counting down to the sale start?",
                          evidence=ev, outcomes=outcomes, guidance="Use the approved offer copy and preview only.")
            elif len(dates) == 1 and _s(r.get("preview_result")):
                cd.review("countdown_timezone_mode", ent,
                          f"Does the preview confirm the countdown ends at {oe} in the intended "
                          f"{_s(o.get('timezone')) or 'offer'} timing with mode '{_s(r.get('countdown_timezone_mode'))}'?",
                          evidence=ev, outcomes=outcomes,
                          guidance="Account-timezone mode ends everywhere at once; viewer mode ends per user timezone.")
            elif len(dates) != 1:
                cd.partial(f"association {k}: countdown target date not literally identifiable; syntax not guessed")
        cd.observe("Countdown configurations reviewed", countdowns=n)

    exp = ctx.check("expired_serving", "Expired offers versus dated serving",
                    {CONFIG: ["asset_or_ad_id", "association_id", "campaign_id", "end_date", "schedule",
                              "actual_serving_dates"],
                     OFFERS: ["offer_id", "campaign_id", "end_at", "approved_by"]})
    if exp.runnable and assoc.runnable:
        for k in sorted(live):
            r = live[k]
            offers = by_camp.get(_s(r.get("campaign_id")), [])
            if len(offers) != 1:
                continue
            o = offers[0]
            oe = V.parse_date(o.get("end_at"))
            if oe is None or ctx.as_of is None or oe >= ctx.as_of:
                continue
            ent = {**_cfg_entity(r), "offer_id": _s(o.get("offer_id"))}
            if not _s(r.get("actual_serving_dates")):
                exp.partial(f"association {k}: offer ended {oe}; dated serving unknown")
                continue
            after = [d for d in _serving_dates(r.get("actual_serving_dates")) if d > oe]
            ev = {"offer_end": oe, "configured_end": r.get("end_date"), "schedule": r.get("schedule"),
                  "serving_dates_after_end": after, "as_of": ctx.as_of}
            if after:
                f = exp.finding("serving_after_offer_end", "Warning", ent,
                                f"Association served on {len(after)} day(s) after the approved offer ended {oe}",
                                evidence=ev, recommendation="Remove or end-date the association (request-only).",
                                uncertainty="Serving days are from supplied delivery data; impressions per day not given.")
                conflicts.append((f, r, o, "end_date", f"{oe}"))
                _critical_review(exp, ent, f, f"Is serving after {oe} a material live misleading offer delivery?", ev)
            else:
                exp.finding("expired_nonserving_config", "Info", ent,
                            f"Offer ended {oe}; the association has no dated serving after end",
                            evidence=ev, recommendation="Optional cleanup of the expired configuration.",
                            uncertainty="An expired setting simply stops eligible serving.")

    opt = ctx.check("optional_feature", "Approved offers without linked promotion/countdown",
                    {**cfg_needs, OFFERS: ["offer_id", "campaign_id", "end_at", "approved_by"]})
    if opt.runnable:
        if ctx.table(CONFIG).complete is not True:
            opt.partial("promotion_config not manifest-complete: absence of associations not provable")
        else:
            linked_camps = {_s(r.get("campaign_id")) for r in live.values()}
            for cid in sorted(by_camp):
                for o in by_camp[cid]:
                    oe = V.parse_date(o.get("end_at"))
                    if cid in linked_camps or oe is None or ctx.as_of is None or oe < ctx.as_of:
                        continue
                    opt.finding("absent_optional_feature", "Info", {"campaign_id": cid, "offer_id": _s(o.get("offer_id"))},
                                f"Approved offer {_s(o.get('offer_id'))} has no linked promotion/countdown in campaign {cid}",
                                evidence={"offer_end": oe, "offer_text": o.get("offer_text")},
                                recommendation="Optional: consider a promotion asset test; not a defect.",
                                uncertainty="No uplift is implied by adding the feature.")

    fix = ctx.check("correction_drafts", "Request-only corrected field values")
    if not (assoc.runnable and terms.runnable):
        fix.skip("no comparable configuration/offer evidence", sorted(set(assoc.missing + terms.missing)))
        return
    for f, r, o, field, value in sorted(conflicts, key=lambda x: (x[0].id, x[3])):
        fix.observe(f"Correction draft for {_s(r.get('asset_or_ad_id'))}", **_cfg_entity(r),
                    offer_id=_s(o.get("offer_id")), field=field, current=r.get(field.split("/")[0]), proposed=value,
                    source_offer_ref=o.get("landing_page_snapshot_ref"), approved_by=o.get("approved_by"),
                    timezone=o.get("timezone"), finding_id=f.id)
    fix.observe("Correction drafts", count=len(conflicts))


def verify(ctx, item, decision) -> list[str]:
    """Rules: 'material_live_misleading' (Critical) requires proposal.evidence_ref to supplied delivery evidence."""
    if decision.get("outcome") == "material_live_misleading" and not _s((decision.get("proposal") or {}).get("evidence_ref")):
        return ["material_live_misleading needs proposal.evidence_ref pointing at supplied delivery evidence"]
    return []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
