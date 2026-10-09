"""check.py — skill-145 deterministic prelaunch readiness checklist over a frozen draft package.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-145-prelaunch-compliance-checklist/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #91 Check campaign settings (SergeyMatrosov/GoogleAds_Check_New_Campaign) — clean-room
         reimplementation of "compare a new campaign's settings with a declared standard" (geo method, networks,
         languages, budget ceiling) as the launch_settings check; its automatic setting changes, labels and
         naming-convention rules are NOT reproduced (proposals only; naming is not a readiness requirement).
         index #114 Ad Optimizer: Post Ads (rfharmon gist) — clean-room: its "post ad copy from a spreadsheet"
         becomes the copy_format pre-upload validation of launch_drafts (limits, counts, duplicates, final URL);
         REFUSED: creating ads, applying labels, deleting sheet rows and name-based account/ad-group lookup.
         skills/skill-025-rsa-headline-diversity-completeness/scripts/check.py — same insertion-token fallback
         rendering and display-width counting (keep semantics identical).
rules:   Package = latest version per (launch_id, draft_id); profile.launch_id restricts scope when set.
         Existing ads/assets are reference only and never establish draft readiness.
         Evidence rows apply to a draft when applicable_market is empty, wildcard or overlaps target_markets
         (exact token match after lowercase); non-overlapping rows are not_applicable.
         review_status maps to met / not_met / not_applicable / unknown; free text → unknown.
         Critical only for a prohibited-class row with reviewer status not_met (directly evidenced);
         restricted/editorial not_met or authorization invalid at launch_at → Warning; everything unresolved,
         missing claim substantiation, page or authorization evidence → Info (never an invented false claim).
         Editorial pattern candidates (repeated !/?, ALL-CAPS words not in profile.editorial_caps_allowlist,
         profile.brand_terms or the account currency code) are ai_review only.
         #91 standard is profile-supplied: profile.launch_settings_standard {geo_target_method, search_partners,
         display_network, languages, max_daily_budget}; deviations are Info, never policy findings.
         Readiness per draft: changes_required | evidence_incomplete | ready_for_owner_review — never APPROVED,
         never legal certification, no launch or submission.
         #114 copy_format needs launch_drafts headlines + descriptions (JSON list of str/{text} or ' | '); path1/2
         optional. Only ad_type RSA / RESPONSIVE_SEARCH_AD is validated (other types: partial, no finding).
         Official limits (support.google.com/google-ads/answer/7684791, consulted 2026-09-25): 3..15 headlines
         <=30, 2..4 descriptions <=90, path <=15; double-width chars count 2; width is measured with keyword/
         CUSTOMIZER/LOCATION tokens rendered as their default (API RSA customization doc), COUNTDOWN → width
         unverifiable (unknown). Exact duplicate values (NFKC + collapsed whitespace, case kept) block the ad
         (support.google.com/sa360/answer/16555674). Final URLs must be absolute http(s) with a host and no
         tokens (adspolicy/answer/6368661 Unacceptable URL; google-ads/answer/6371157). http:// is only an
         observation: answer/6273460 allows HTTP final URLs (HTTPS is required for tracking templates/redirects).
         Violations → deterministic Warning (not_met → changes_required); no structured copy / unparseable →
         unknown; an empty final_urls cell stays the inventory Info (no duplicate finding).
         Warning review outcomes resolve proposal.evidence_ref against the same draft's launch_evidence rows:
         editorial_conflict → applicable editorial requirement_id/official_policy_url; outside_required_authorization
         → certification_or_authorization_ref valid at launch_at.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_checks14 | initial deterministic check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_builders | #114 copy_format pre-upload validation
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_evref | Warning evidence_ref must resolve to the draft's launch_evidence rows
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-145-prelaunch-compliance-checklist"
VERSION = "1.1.0"

LD = "external/launch_drafts"
LE = "external/launch_evidence"
_SEPS = (" | ", ";", "|", ",")
_WILD = ("*", "all", "any")
_MET = ("met", "pass", "passed", "compliant", "ok", "approved_internal")
_NOT_MET = ("not_met", "not met", "fail", "failed", "conflict", "violation", "non_compliant")
_NA = ("not_applicable", "n/a", "na")
_CAPS = re.compile(r"\b[A-Z]{3,}\b")
_PUNCT = re.compile(r"[!?]{2,}")
_BRACE = re.compile(r"\{([^{}]*)\}")
_LOCATION = re.compile(r"LOCATION\((City|State|Country)\)")
_KEYWORD_TAGS = ("keyword", "Keyword", "KeyWord", "KEYWord", "KeyWORD")
RSA_FORMAT = {"headlines": (3, 15, 30), "descriptions": (2, 4, 90), "path": 15}
RSA_SOURCE = "https://support.google.com/google-ads/answer/7684791 (consulted 2026-09-25)"
DUP_SOURCE = "https://support.google.com/sa360/answer/16555674 (consulted 2026-09-25)"
URL_SOURCE = ("https://support.google.com/adspolicy/answer/6368661 Unacceptable URL; "
              "https://support.google.com/google-ads/answer/6371157 (consulted 2026-09-25)")
HTTP_NOTE = ("https://support.google.com/google-ads/answer/6273460 (consulted 2026-09-25): HTTP final URLs are "
             "accepted; tracking templates and redirects need HTTPS")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _toks(v) -> set[str]:
    return {x.lower() for x in V.split_list(v, _SEPS)}


def _status(v) -> str:
    s = _s(v).lower()
    if s in _NOT_MET:
        return "not_met"
    if s in _MET:
        return "met"
    if s in _NA:
        return "not_applicable"
    return "unknown"


def _version_key(v):
    f = V.num(v)
    return (0, f, "") if f is not None else (1, 0.0, _s(v))


class _State:
    def __init__(self):
        self.drafts: dict[tuple[str, str], dict] = {}
        self.marks: dict[tuple[str, str], dict[str, list[str]]] = {}

    def mark(self, key, status: str, note: str) -> None:
        self.marks.setdefault(key, {"met": [], "not_met": [], "unknown": [], "not_applicable": []})[status].append(note)


def _applies(row: dict, draft: dict) -> bool:
    m = _toks(row.get("applicable_market"))
    return not m or bool(m & set(_WILD)) or bool(m & _toks(draft.get("target_markets")))


def _evidence_for(ctx, key) -> list[dict]:
    return sorted((r for r in ctx.rows(LE) if (_s(r.get("launch_id")), _s(r.get("draft_id"))) == key),
                  key=lambda r: _s(r.get("requirement_id")))


def run(ctx) -> None:
    """Run draft inventory, requirement-class, claim, editorial, authorization, settings, copy-format and readiness.

    Rules:   Critical only for a prohibited-class requirement with reviewer status not_met; restricted/editorial
             not_met or authorization invalid at launch_at → Warning; missing evidence/unresolved status → Info.
             Editorial caps/punctuation candidates and authorization market-scope gaps are Info + ai_review only.
             Settings deviations vs profile.launch_settings_standard stay Info; readiness is never APPROVED/launched.
             copy_format: RSA drafts outside official limits/counts, with exact duplicates or unuploadable final
             URLs → Warning (not_met); structured copy absent/unparseable → unknown, never a finding.
    """
    st = _State()
    _inventory(ctx, st)
    _classes(ctx, st)
    _claims(ctx, st)
    _editorial(ctx, st)
    _authorization(ctx, st)
    _settings(ctx, st)
    _copy_format(ctx, st)
    _readiness(ctx, st)


def _inventory(ctx, st: _State) -> None:
    """Step 1: freeze latest version per draft and inventory drafts/assets/targets."""
    chk = ctx.check("package_inventory", "Frozen launch package inventory",
                    {LD: ["launch_id", "draft_id", "version", "proposed_campaign_id", "ad_type", "full_copy",
                          "final_urls", "target_markets", "languages", "network", "launch_at", "owner"]})
    if not chk.runnable:
        return
    scope = _s(ctx.profile.get("launch_id"))
    superseded = 0
    for r in sorted(ctx.rows(LD), key=lambda r: (_s(r.get("launch_id")), _s(r.get("draft_id")),
                                                 _version_key(r.get("version")))):
        key = (_s(r.get("launch_id")), _s(r.get("draft_id")))
        if scope and key[0] != scope:
            continue
        if key in st.drafts:
            superseded += 1
        st.drafts[key] = r
    chk.observe("Frozen package", launch_scope=scope or "all supplied", drafts=len(st.drafts),
                superseded_versions=superseded,
                package=[f"{k[0]}/{k[1]}@{_s(v.get('version'))}" for k, v in sorted(st.drafts.items())])
    for key in sorted(st.drafts):
        d = st.drafts[key]
        gaps = [c for c in ("full_copy", "final_urls", "target_markets", "languages", "launch_at", "owner")
                if not _s(d.get(c))]
        if V.parse_date(d.get("launch_at")) is None and "launch_at" not in gaps:
            gaps.append("launch_at (unparseable)")
        chk.observe(f"Draft {key[1]}@{_s(d.get('version'))}", launch_id=key[0], draft_id=key[1],
                    version=d.get("version"), ad_type=d.get("ad_type"), proposed_campaign_id=d.get("proposed_campaign_id"),
                    target_markets=sorted(_toks(d.get("target_markets"))), languages=sorted(_toks(d.get("languages"))),
                    network=d.get("network"), assets_refs=V.split_list(d.get("assets_refs"), _SEPS),
                    launch_at=d.get("launch_at"))
        if gaps:
            st.mark(key, "unknown", f"draft fields missing: {gaps}")
            chk.finding("draft_evidence_missing", "Info", {"launch_id": key[0], "draft_id": key[1]},
                        f"Draft {key[1]} is missing {', '.join(gaps)}", evidence={"version": d.get("version")},
                        recommendation="Complete the draft before readiness review.",
                        uncertainty="Missing draft content is unknown, not non-compliant.")


def _classes(ctx, st: _State) -> None:
    """Step 2: prohibited vs restricted requirements, separately."""
    chk = ctx.check("prohibited_restricted", "Prohibited vs restricted content requirements",
                    {LE: ["launch_id", "draft_id", "requirement_id", "official_policy_url", "checked_at",
                          "applicable_market", "prohibited_or_restricted_or_editorial", "reviewer_role",
                          "review_status"]})
    if not chk.runnable or not st.drafts:
        if chk.runnable:
            chk.partial("no drafts in scope")
        return
    for key in sorted(st.drafts):
        d = st.drafts[key]
        rows = [r for r in _evidence_for(ctx, key)
                if _s(r.get("prohibited_or_restricted_or_editorial")).lower() in ("prohibited", "restricted")]
        if not _evidence_for(ctx, key):
            st.mark(key, "unknown", "no requirement evidence")
            chk.finding("no_requirement_evidence", "Info", {"launch_id": key[0], "draft_id": key[1]},
                        f"Draft {key[1]} has no requirement evidence rows", evidence={"version": d.get("version")},
                        recommendation="Map the draft to applicable policies with dated official sources.",
                        uncertainty="Applicability unknown.")
            continue
        for r in rows:
            cls = _s(r.get("prohibited_or_restricted_or_editorial")).lower()
            rid = _s(r.get("requirement_id"))
            entity = {"launch_id": key[0], "draft_id": key[1], "requirement_id": rid}
            ev = {k: r.get(k) for k in ("official_policy_url", "checked_at", "applicable_market", "reviewer_role",
                                        "review_status", "scope")}
            ev.update({"class": cls, "version": d.get("version"), "target_markets": d.get("target_markets")})
            if not _applies(r, d):
                st.mark(key, "not_applicable", rid)
                continue
            s = _status(r.get("review_status"))
            st.mark(key, s, f"{cls} {rid}")
            if s == "not_met" and cls == "prohibited":
                chk.finding("prohibited_content", "Critical", entity,
                            f"Draft {key[1]} contains content the reviewer marked not_met against PROHIBITED "
                            f"requirement {rid}", evidence=ev,
                            recommendation="Remove the prohibited content from the draft; no launch.",
                            uncertainty="Internal review record; not a legal or Google determination.")
            elif s == "not_met":
                chk.finding("restricted_requirement_conflict", "Warning", entity,
                            f"Draft {key[1]} conflicts with restricted requirement {rid} (reviewer: not_met)",
                            evidence=ev, recommendation="Meet the market-specific conditions or change the draft.",
                            uncertainty="Restricted content may be allowed once conditions are met.")
            elif s == "unknown":
                chk.finding("unresolved_policy_interpretation", "Info", entity,
                            f"Draft {key[1]}: {cls} requirement {rid} status '{r.get('review_status')}' unresolved",
                            evidence=ev, recommendation="Route to the qualified policy owner.",
                            uncertainty="Unresolved interpretation.")


def _claims(ctx, st: _State) -> None:
    """Step 3: claims vs dated substantiation valid at launch."""
    chk = ctx.check("claim_substantiation", "Claims vs dated substantiation",
                    {LD: ["launch_id", "draft_id", "claims", "launch_at"],
                     LE: ["launch_id", "draft_id", "claim_substantiation_ref", "valid_from", "valid_to",
                          "page_snapshot_ref"]})
    if not chk.runnable:
        return
    for key in sorted(st.drafts):
        d = st.drafts[key]
        claims = V.split_list(d.get("claims"), _SEPS)
        if not claims:
            continue
        launch = V.parse_date(d.get("launch_at"))
        refs = []
        for r in _evidence_for(ctx, key):
            ref = _s(r.get("claim_substantiation_ref"))
            if not ref:
                continue
            vf, vt = V.parse_date(r.get("valid_from")), V.parse_date(r.get("valid_to"))
            valid = launch is not None and (vf is None or vf <= launch) and (vt is None or vt >= launch)
            refs.append({"ref": ref, "valid_from": vf, "valid_to": vt, "valid_at_launch": valid})
        entity = {"launch_id": key[0], "draft_id": key[1]}
        if any(x["valid_at_launch"] for x in refs):
            st.mark(key, "met", "claim substantiation")
            chk.observe(f"Draft {key[1]}: claims have substantiation valid at launch", **entity, claims=claims,
                        substantiation=refs)
            continue
        st.mark(key, "unknown", "claim substantiation")
        chk.finding("claim_substantiation_missing", "Info", entity,
                    f"Draft {key[1]}: {len(claims)} claims without substantiation valid at launch {launch}",
                    evidence={"claims": claims, "substantiation": refs, "launch_at": d.get("launch_at")},
                    recommendation="Request dated substantiation covering the launch date.",
                    uncertainty="Missing substantiation is unresolved, not a confirmed false claim.")


def _editorial(ctx, st: _State) -> None:
    """Step 4: editorial requirements and pattern candidates; destination evidence."""
    chk = ctx.check("editorial_destination", "Editorial issues and destination evidence",
                    {LD: ["launch_id", "draft_id", "full_copy", "final_urls", "languages"],
                     LE: ["launch_id", "draft_id", "requirement_id", "prohibited_or_restricted_or_editorial",
                          "review_status", "page_snapshot_ref", "technical_diagnostics_ref", "applicable_market"]})
    if not chk.runnable:
        return
    allow = {str(x).upper() for x in (ctx.profile.get("editorial_caps_allowlist") or [])}
    for b in ctx.profile.get("brand_terms") or []:
        allow |= {w.upper() for w in str(b).split()}
    if ctx.currency:
        allow.add(ctx.currency)
    for key in sorted(st.drafts):
        d = st.drafts[key]
        entity = {"launch_id": key[0], "draft_id": key[1]}
        ev_rows = _evidence_for(ctx, key)
        for r in ev_rows:
            if _s(r.get("prohibited_or_restricted_or_editorial")).lower() != "editorial" or not _applies(r, d):
                continue
            s = _status(r.get("review_status"))
            st.mark(key, s, f"editorial {r.get('requirement_id')}")
            if s == "not_met":
                chk.finding("editorial_conflict", "Warning", {**entity, "requirement_id": r.get("requirement_id")},
                            f"Draft {key[1]} fails editorial requirement {r.get('requirement_id')} (reviewer: not_met)",
                            evidence={"review_status": r.get("review_status")},
                            recommendation="Revise copy; apply documented language/brand exceptions only.",
                            uncertainty="Internal review record.")
        copy = _s(d.get("full_copy"))
        caps = sorted({w for w in _CAPS.findall(copy) if w not in allow})
        punct = sorted(set(_PUNCT.findall(copy)))
        if caps or punct:
            st.mark(key, "unknown", "editorial candidates")
            prov = chk.finding("editorial_candidate", "Info", entity,
                               f"Draft {key[1]}: editorial candidates caps={caps} punctuation={punct}",
                               evidence={"full_copy": copy, "languages": d.get("languages"),
                                         "allowlist": sorted(allow)},
                               recommendation="Confirm acronym/brand exceptions or revise.",
                               uncertainty="Pattern match only; exceptions may apply.")
            chk.review("editorial_candidate", entity,
                       f"Do the flagged capitals/punctuation in draft {key[1]} breach editorial requirements, "
                       f"or are they documented acronym/brand/language exceptions?",
                       evidence={"full_copy": copy, "caps": caps, "punctuation": punct,
                                 "languages": d.get("languages")},
                       outcomes={"editorial_conflict": {"severity": "Warning", "recommendation": "Revise the copy."},
                                 "exception_ok": {"severity": None, "recommendation": "Record the exception."},
                                 "uncertain": {"severity": "Info", "recommendation": "Ask the policy owner."}},
                       guidance="Acronyms, brand spellings and language conventions are exceptions.",
                       provisional=prov)
        urls = V.split_list(d.get("final_urls"), _SEPS)
        page_refs = [r for r in ev_rows if _s(r.get("page_snapshot_ref")) or _s(r.get("technical_diagnostics_ref"))]
        if urls and not page_refs:
            st.mark(key, "unknown", "destination evidence")
            chk.finding("destination_evidence_missing", "Info", entity,
                        f"Draft {key[1]}: {len(urls)} final URLs without page snapshot or diagnostics evidence",
                        evidence={"final_urls": urls},
                        recommendation="Capture page snapshots/diagnostics for the launch URLs.",
                        uncertainty="Destination functionality unknown.")
        elif urls:
            st.mark(key, "met", "destination evidence supplied")


def _authorization(ctx, st: _State) -> None:
    """Step 5: certification/authorization scope and validity at launch_at."""
    chk = ctx.check("targeting_authorization", "Authorization/certification scope and validity",
                    {LD: ["launch_id", "draft_id", "target_markets", "launch_at"],
                     LE: ["launch_id", "draft_id", "requirement_id", "applicable_market", "applicable_product",
                          "prohibited_or_restricted_or_editorial", "certification_or_authorization_ref", "scope",
                          "valid_from", "valid_to"]})
    if not chk.runnable:
        return
    for key in sorted(st.drafts):
        d = st.drafts[key]
        launch = V.parse_date(d.get("launch_at"))
        markets = _toks(d.get("target_markets"))
        certs = []
        for r in _evidence_for(ctx, key):
            ref = _s(r.get("certification_or_authorization_ref"))
            rid = _s(r.get("requirement_id"))
            entity = {"launch_id": key[0], "draft_id": key[1], "requirement_id": rid}
            restricted = _s(r.get("prohibited_or_restricted_or_editorial")).lower() == "restricted"
            if not ref:
                if restricted and _applies(r, d):
                    st.mark(key, "unknown", f"authorization {rid}")
                    chk.finding("authorization_evidence_missing", "Info", entity,
                                f"Draft {key[1]}: restricted requirement {rid} has no certification/authorization ref",
                                evidence={"scope": r.get("scope"), "applicable_market": r.get("applicable_market")},
                                recommendation="Request the certification/authorization record from the owner.",
                                uncertainty="May not be required; applicability needs the policy owner.")
                continue
            certs.append(r)
            vf, vt = V.parse_date(r.get("valid_from")), V.parse_date(r.get("valid_to"))
            if launch is None:
                st.mark(key, "unknown", f"authorization {rid} validity (launch_at unknown)")
                continue
            if (vf and vf > launch) or (vt and vt < launch):
                st.mark(key, "not_met", f"authorization {rid} invalid at launch")
                chk.finding("authorization_invalid_at_launch", "Warning", entity,
                            f"Draft {key[1]}: authorization {ref} valid {vf}..{vt} does not cover launch {launch}",
                            evidence={"ref": ref, "valid_from": vf, "valid_to": vt, "launch_at": d.get("launch_at"),
                                      "scope": r.get("scope")},
                            recommendation="Renew/obtain authorization before launch or move the launch date.",
                            uncertainty="Internal record; platform certification status may differ.")
            else:
                st.mark(key, "met", f"authorization {rid} valid at launch")
        if certs and markets:
            covered = set().union(*(_toks(r.get("applicable_market")) for r in certs))
            if not covered & set(_WILD):
                uncovered = sorted(markets - covered)
                if uncovered:
                    st.mark(key, "unknown", "authorization market scope")
                    entity = {"launch_id": key[0], "draft_id": key[1]}
                    prov = chk.finding("authorization_market_scope", "Info", entity,
                                       f"Draft {key[1]}: target markets {uncovered} not listed in authorization scope",
                                       evidence={"target_markets": sorted(markets), "authorized_markets": sorted(covered),
                                                 "refs": [r.get("certification_or_authorization_ref") for r in certs]},
                                       recommendation="Confirm scope with the certification owner.",
                                       uncertainty="Market vocabularies may differ.")
                    chk.review("authorization_market_scope", entity,
                               f"Does draft {key[1]} target markets {uncovered} outside the authorization scope?",
                               evidence={"target_markets": sorted(markets), "authorized_markets": sorted(covered),
                                         "rows": [{k: r.get(k) for k in sorted(r)} for r in certs]},
                               outcomes={"outside_required_authorization": {"severity": "Warning", "recommendation":
                                                                            "Narrow targeting or extend authorization."},
                                         "covered": {"severity": None, "recommendation": "Record the scope mapping."},
                                         "uncertain": {"severity": "Info", "recommendation": "Ask the owner."}},
                               guidance="Only documented scope counts; the assistant does not certify.",
                               provisional=prov)


def _settings(ctx, st: _State) -> None:
    """#91 clean-room: configured campaign vs draft targeting and the profile's launch settings standard."""
    chk = ctx.check("launch_settings", "Launch settings vs draft and declared standard (#91)",
                    {LD: ["launch_id", "draft_id", "proposed_campaign_id", "target_markets", "languages", "network"],
                     "campaigns": ["id"]})
    if not chk.runnable:
        return
    std = ctx.profile.get("launch_settings_standard") or {}
    if not isinstance(std, dict) or not std:
        chk.partial("no profile.launch_settings_standard: only draft-vs-configured comparisons run",
                    ["profile.launch_settings_standard"])
        std = {}
    camps = {_s(c.get("id")): c for c in ctx.rows("campaigns")}
    for key in sorted(st.drafts):
        d = st.drafts[key]
        cid = _s(d.get("proposed_campaign_id"))
        c = camps.get(cid)
        if c is None:
            chk.observe(f"Draft {key[1]}: proposed campaign {cid or '-'} not configured yet", launch_id=key[0],
                        draft_id=key[1], proposed_campaign_id=cid)
            continue
        dev = []
        for draft_col, camp_col in (("languages", "languages"), ("target_markets", "geo_targets")):
            a, b = _toks(d.get(draft_col)), _toks(c.get(camp_col))
            if a and b and a != b:
                dev.append({"setting": camp_col, "draft": sorted(a), "configured": sorted(b)})
        net = _s(d.get("network")).lower()
        for flag in ("search_partners", "display_network"):
            conf = V.boolean(c.get(flag))
            if conf is None:
                continue
            wanted = ("partner" if flag == "search_partners" else "display") in net
            if net and conf != wanted:
                dev.append({"setting": flag, "draft_network": d.get("network"), "configured": conf})
            if flag in std and V.boolean(std[flag]) is not None and conf != V.boolean(std[flag]):
                dev.append({"setting": flag, "standard": std[flag], "configured": conf})
        if "geo_target_method" in std and _s(c.get("geo_target_method")) and \
                _s(c.get("geo_target_method")).upper() != _s(std["geo_target_method"]).upper():
            dev.append({"setting": "geo_target_method", "standard": std["geo_target_method"],
                        "configured": c.get("geo_target_method")})
        if "languages" in std and _toks(c.get("languages")) and \
                _toks(c.get("languages")) != {str(x).lower() for x in std["languages"]}:
            dev.append({"setting": "languages", "standard": std["languages"], "configured": c.get("languages")})
        cap, bud = V.num(std.get("max_daily_budget")), ctx.money(c.get("daily_budget"))
        if cap is not None and bud is not None and bud > cap:
            dev.append({"setting": "daily_budget", "standard_max": cap, "configured": bud})
        if dev:
            st.mark(key, "unknown", "configured settings deviate")
            chk.finding("launch_setting_deviation", "Info", {"launch_id": key[0], "draft_id": key[1],
                                                             "campaign_id": cid},
                        f"Draft {key[1]}: configured campaign {cid} deviates on "
                        f"{', '.join(sorted({x['setting'] for x in dev}))}",
                        evidence={"deviations": dev, "standard": std},
                        recommendation="Owner confirms or corrects settings before launch (proposal only).",
                        uncertainty="Settings standard is a client convention, not a policy requirement.")
        else:
            chk.observe(f"Draft {key[1]}: configured campaign {cid} consistent", launch_id=key[0], draft_id=key[1],
                        campaign_id=cid)


def _width(v) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(v or ""))


def _fallback(text: str) -> str | None:
    """Text with keyword/CUSTOMIZER/LOCATION tokens at their default; None when a countdown has no fallback.

    Rules:   unknown or malformed tokens stay literal (measured raw, never shortened).
    """
    unverifiable = False

    def repl(m):
        nonlocal unverifiable
        head, sep, default = m.group(1).partition(":")
        if head in _KEYWORD_TAGS or head.startswith("CUSTOMIZER.") or _LOCATION.fullmatch(head):
            return default if sep else ""
        if head.startswith(("COUNTDOWN(", "GLOBAL_COUNTDOWN(")):
            unverifiable = True
        return m.group(0)

    out = _BRACE.sub(repl, text)
    return None if unverifiable else out


def _copy_list(cell) -> list[str] | None:
    """Headline/description cell → texts ([] when empty); None when a JSON array is unparseable."""
    s = _s(cell)
    if not s:
        return []
    if s.startswith("["):
        try:
            data = json.loads(s)
        except ValueError:
            return None
        out = [e.get("text") if isinstance(e, dict) else e for e in data] if isinstance(data, list) else None
        return None if out is None or any(not isinstance(t, str) for t in out) else out
    return V.split_list(s, (" | ", "|", "\n"))


def _url_problem(url: str) -> str | None:
    if "{" in url or "}" in url:
        return "insertion tokens are not allowed in the final URL"
    if any(ch.isspace() for ch in url):
        return "whitespace inside the URL"
    p = urlsplit(url)
    if p.scheme.lower() not in ("http", "https"):
        return "scheme missing or not http/https"
    if not p.hostname:
        return "no host"
    return None


def _copy_format(ctx, st: _State) -> None:
    """#114 clean-room: deterministic RSA copy format validation before any upload."""
    chk = ctx.check("copy_format", "Draft copy format vs official RSA limits before upload (#114)",
                    {LD: ["launch_id", "draft_id", "ad_type", "headlines", "descriptions", "final_urls"]})
    if not chk.runnable:
        return
    if not st.drafts:
        chk.partial("no drafts in scope (package inventory empty or skipped)")
    for key in sorted(st.drafts):
        d = st.drafts[key]
        entity = {"launch_id": key[0], "draft_id": key[1]}
        ad_type = _s(d.get("ad_type")).lower().replace(" ", "_").replace("-", "_")
        if not ad_type:
            st.mark(key, "unknown", "copy format: ad_type missing, limits unknown")
            chk.partial(f"draft {key[1]}: ad_type missing; copy format not validated", [f"{LD}:ad_type"])
            continue
        if ad_type not in ("rsa", "responsive_search_ad"):
            chk.partial(f"draft {key[1]}: no sourced format limits for ad_type '{d.get('ad_type')}'; not validated")
            continue
        texts = {f: _copy_list(d.get(f)) for f in ("headlines", "descriptions")}
        if None in texts.values():
            st.mark(key, "unknown", "copy format: unparseable headline/description array")
            chk.partial(f"draft {key[1]}: unparseable headline/description array")
            continue
        if not texts["headlines"] and not texts["descriptions"]:
            st.mark(key, "unknown", "copy format: structured RSA copy not supplied")
            chk.partial(f"draft {key[1]}: structured RSA copy not supplied; format unverifiable")
            continue
        width, counts, dups, urls, unverifiable = [], [], [], [], []
        for field, items in texts.items():
            lo, hi, limit = RSA_FORMAT[field]
            if not lo <= len(items) <= hi:
                counts.append({"field": field, "supplied": len(items), "min": lo, "max": hi,
                               "required_field_missing": not items})
            seen: dict[str, int] = {}
            for i, t in enumerate(items):
                out = _fallback(t)
                if out is None:
                    unverifiable.append(f"{field}[{i + 1}]")
                elif _width(out) > limit:
                    width.append({"field": field, "index": i + 1, "text": t, "width": _width(out), "limit": limit})
                exact = " ".join(unicodedata.normalize("NFKC", t).split())
                if exact in seen:
                    dups.append({"field": field, "indexes": [seen[exact] + 1, i + 1], "text": t})
                seen.setdefault(exact, i)
        for field in ("path1", "path2"):
            t = _s(d.get(field))
            out = _fallback(t) if t else ""
            if out is None:
                unverifiable.append(field)
            elif _width(out) > RSA_FORMAT["path"]:
                width.append({"field": field, "text": t, "width": _width(out), "limit": RSA_FORMAT["path"]})
        final = V.split_list(d.get("final_urls"), _SEPS)
        for u in final:
            problem = _url_problem(u)
            if problem:
                urls.append({"url": u, "problem": problem})
        plain_http = [u for u in final if urlsplit(u).scheme.lower() == "http"]
        checks = (("copy_character_limit", width, RSA_SOURCE, "text(s) exceed the official RSA character limits"),
                  ("copy_count_limit", counts, RSA_SOURCE, "headline/description count(s) outside official limits"),
                  ("copy_duplicate_text", dups, DUP_SOURCE, "duplicate headline/description value(s)"),
                  ("final_url_format", urls, URL_SOURCE, "final URL(s) not uploadable as written"))
        hit = []
        for cond, rows, source, text in checks:
            if not rows:
                continue
            hit.append(cond)
            chk.finding(cond, "Warning", entity, f"Draft {key[1]}: {len(rows)} {text}",
                        evidence={"violations": rows, "official_source": source, "version": d.get("version"),
                                  "ad_type": d.get("ad_type")},
                        calculation={"width": "display columns, double-width characters count 2; insertion tokens "
                                              "at their default text"},
                        recommendation="Correct the draft before any upload; a violating ad cannot be saved or served.",
                        uncertainty="Format check only; policy review and serving eligibility are separate checks.")
        if unverifiable:
            st.mark(key, "unknown", f"copy format: width unverifiable for {unverifiable} (no fallback text)")
            chk.partial(f"draft {key[1]}: countdown without fallback in {unverifiable}; width unverifiable")
        if hit:
            st.mark(key, "not_met", f"copy format: {hit}")
        elif not unverifiable:
            st.mark(key, "met", "copy format within official RSA limits")
        chk.observe(f"Draft {key[1]}: copy format", **entity, headlines=len(texts["headlines"]),
                    descriptions=len(texts["descriptions"]), violations=hit, non_https_final_urls=plain_http,
                    https_note=HTTP_NOTE if plain_http else None, limits_source=RSA_SOURCE)


def _readiness(ctx, st: _State) -> None:
    """Step 6: met/not_met/unknown per draft → internal readiness (never Google approval)."""
    chk = ctx.check("readiness", "Internal readiness decision per draft",
                    {LD: ["launch_id", "draft_id", "version", "owner"]})
    if not chk.runnable:
        return
    if ctx.table(LE) is None:
        chk.partial("launch evidence missing: every draft is evidence_incomplete", [f"{LE} (file)"])
    for key in sorted(st.drafts):
        m = st.marks.get(key, {"met": [], "not_met": [], "unknown": [], "not_applicable": []})
        if ctx.table(LE) is None:
            m["unknown"].append("launch evidence file missing")
        state = "changes_required" if m["not_met"] else "evidence_incomplete" if m["unknown"] or not m["met"] \
            else "ready_for_owner_review"
        chk.observe(f"Draft {key[1]}: {state}", launch_id=key[0], draft_id=key[1],
                    version=st.drafts[key].get("version"), owner=st.drafts[key].get("owner"), readiness=state,
                    **{k: sorted(v) for k, v in m.items()},
                    disclaimer="internal readiness only; not legal certification, not Google approval, no launch")


def _latest_draft(ctx, key) -> dict | None:
    rows = [r for r in ctx.rows(LD) if (_s(r.get("launch_id")), _s(r.get("draft_id"))) == key]
    return max(rows, key=lambda r: _version_key(r.get("version"))) if rows else None


def _ref_problem(ctx, item, outcome: str, ref: str) -> str | None:
    """Resolve ref against this draft's launch_evidence rows of the class/window the outcome depends on."""
    key = (_s(item.entity.get("launch_id")), _s(item.entity.get("draft_id")))
    d = _latest_draft(ctx, key) or {}
    rows = _evidence_for(ctx, key)
    if outcome == "editorial_conflict":
        if any(_s(r.get("prohibited_or_restricted_or_editorial")).lower() == "editorial" and _applies(r, d)
               and ref in (_s(r.get("requirement_id")), _s(r.get("official_policy_url"))) for r in rows):
            return None
        return (f"evidence_ref {ref} is not the requirement_id/official_policy_url of an editorial launch_evidence "
                f"row applying to draft {key[1]}")
    certs = [r for r in rows if _s(r.get("certification_or_authorization_ref")) == ref]
    if not certs:
        return f"evidence_ref {ref} is not a certification_or_authorization_ref of draft {key[1]}"
    launch = V.parse_date(d.get("launch_at"))
    for r in certs:
        vf, vt = V.parse_date(r.get("valid_from")), V.parse_date(r.get("valid_to"))
        if launch is None or not ((vf and vf > launch) or (vt and vt < launch)):
            return None
    return f"evidence_ref {ref} authorization is not valid at launch {launch} of draft {key[1]}"


def verify(ctx, item, decision) -> list[str]:
    """Deterministic re-check of AI decisions.

    Rules:   editorial_conflict (Warning) requires proposal.evidence_ref equal to the requirement_id or
             official_policy_url of an editorial-class launch_evidence row of the same launch_id/draft_id that
             applies to the draft's target_markets. outside_required_authorization (Warning) requires the
             certification_or_authorization_ref of a launch_evidence row of the same draft whose valid_from/valid_to
             covers the latest draft version's launch_at (unchecked only when launch_at is unparseable).
             Unknown refs and refs of other drafts are rejected; other outcomes need no proposal.
    """
    outcome = decision.get("outcome")
    if outcome not in ("editorial_conflict", "outside_required_authorization"):
        return []
    ref = _s((decision.get("proposal") or {}).get("evidence_ref"))
    if not ref:
        return [f"{outcome} needs proposal.evidence_ref to the requirement or scope document"]
    problem = _ref_problem(ctx, item, outcome, ref)
    return [problem] if problem else []


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
