"""check.py — skill-167 deterministic out-of-stock destination exposure and stale ad-text dates.

exports: SKILL | VERSION | run(ctx) -> None | verify(ctx, item, decision) -> list[str]
used_by: skills/skill-167-out-of-stock-ad-exposure/SKILL.md → Analysis Steps (via RUNTIME.md)
related: index #30 Inventory management script (Google) — clean-room reimplementation of URL→stock join; pause/re-enable become request-only proposals
         index #9 Update ad copy with current year, pause out of stock items (Roy Harmon) — clean-room past-year detection; no copy rewriting
         index #87 Check landing page content for out-of-stock items (Brainlabs) — clean-room: only profile-declared markers from saved page checks count
         index #88 Pause ads for out-of-stock items (Dmytro Tonkikh) — clean-room: pause becomes a verified review proposal, never executed
rules:   Stock state comes ONLY from external/merchant_availability (Merchant availability per offer + link + date)
         or external/page_stock_checks rows whose matched_marker is listed in profile.out_of_stock_markers.
         Never read page text or infer stock from wording; undeclared markers and non-2xx pages are unknown.
         URLs join after _norm_url (scheme/host lowercase, default port, fragment, trailing slash, profile
         url_ignore_params exact or 'prefix*', sorted query) — never by product name.
         URL out = every offer linked to it that day observed out_of_stock; preorder/backorder are orderable.
         Merchant 'out' needs a manifest-certified complete catalog, else it is 'unverified' (Info only).
         Current = latest observation within profile.stock_evidence_max_age_days (default 0) of ctx.snapshot
         (fallback ctx.as_of); differing sources → conflict; older only → stale.
         Exposure sums entity_daily cost only on dates with a same-day out observation; unobserved days are
         not out; missing daily rows are unknown, never zero. Exposure is never savings.
         Critical is offered only when exposure >= spend_significant(campaign) and verify demands
         proposal.evidence_ref; redirect proposals must target a URL currently evidenced 'in'.
         Stale dates: active ad headline/description years < as_of year or ISO dates < as_of → review.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_newrecipes3 | initial recipe check
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_l2docs | Rules: docstrings for run/verify
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

SKILL = "skill-167-out-of-stock-ad-exposure"
VERSION = "1.0.0"

MERCHANT = "external/merchant_availability"
PAGES = "external/page_stock_checks"
DAILY = "custom/entity_daily"
AG_URLS = "custom/asset_group_urls"
_ORDERABLE = {"in_stock", "preorder", "backorder"}
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_ISO = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


# ----------------------------------------------------------------------------- helpers
def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    return V.split_list(v)


def _ignored(name: str, ignore: list[str]) -> bool:
    return any(name == p or (p.endswith("*") and name.startswith(p[:-1])) for p in ignore)


def _norm_url(raw, ignore: list[str]) -> str | None:
    """Canonical join form of a URL. Rules: strips only profile.url_ignore_params; None for non-absolute URLs."""
    s = str(raw or "").strip()
    if "://" not in s:
        return None
    s = s.split("#", 1)[0]
    base, _, query = s.partition("?")
    scheme, _, rest = base.partition("://")
    host, slash, path = rest.partition("/")
    scheme, host = scheme.lower(), host.lower()
    if (scheme == "http" and host.endswith(":80")) or (scheme == "https" and host.endswith(":443")):
        host = host.rsplit(":", 1)[0]
    if not host:
        return None
    path = ("/" + path).rstrip("/") if slash else ""
    params = sorted(p for p in query.split("&") if p and not _ignored(p.split("=", 1)[0], ignore))
    return f"{scheme}://{host}{path}" + ("?" + "&".join(params) if params else "")


def _upper(v) -> str:
    return str(v or "").strip().upper()


def _url_col(table, names=("final_urls", "final_url")) -> str | None:
    return next((n for n in names if table is not None and n in table.columns), None)


class _Stock:
    """Per-URL, per-date stock observations from Merchant and declared-marker page checks."""

    def __init__(self, ctx):
        prof = ctx.profile
        self.ignore = _as_list(prof.get("url_ignore_params"))
        self.markers = {V.norm_text(m) for m in _as_list(prof.get("out_of_stock_markers"))}
        age = prof.get("stock_evidence_max_age_days")
        self.max_age = V.integer(age) if age is not None else 0
        self.age_note = ""
        if self.max_age is None or self.max_age < 0:
            self.age_note = f"profile.stock_evidence_max_age_days={age!r} invalid; using 0"
            self.max_age = 0
        self.ref = ctx.snapshot or ctx.as_of
        self.merchant: dict[str, dict] = {}   # url -> date -> {"state", "offers"}
        self.pages: dict[str, dict] = {}      # url -> date -> {"state", "checked_at", "marker"}
        self.m_notes: list[str] = []
        self.p_notes: list[str] = []
        self.m_counts: dict = {}
        self.p_counts: dict = {}
        self.m_loaded = self.p_loaded = False
        self._load_merchant(ctx)
        self._load_pages(ctx)

    def _load_merchant(self, ctx) -> None:
        t = ctx.table(MERCHANT)
        cols = ["snapshot_date", "offer_id", "target_country", "link", "availability"]
        if t is None or t.missing(cols):
            return
        self.m_loaded = True
        certified = t.complete is True and not t.truncated
        if not certified:
            self.m_notes.append(f"{t.filename}: catalog completeness not certified; 'all offers out' downgraded to unverified")
        seen: dict = {}
        dup = bad = 0
        per: dict[str, dict] = {}
        for r in sorted(t.rows, key=lambda r: (str(r.get("snapshot_date")), str(r.get("offer_id")),
                                               str(r.get("target_country")))):
            d = V.parse_date(r.get("snapshot_date"))
            url = _norm_url(r.get("link"), self.ignore)
            key = (str(r.get("offer_id") or ""), _upper(r.get("target_country")))
            if d is None or url is None or not key[0]:
                bad += 1
                continue
            avail = str(r.get("availability") or "").strip().lower().replace(" ", "_").replace("-", "_")
            if (key, d) in seen:
                dup += 1
                if seen[(key, d)] != avail:
                    per.setdefault(url, {}).setdefault(d, {})[key] = "conflict"
                continue
            seen[(key, d)] = avail
            per.setdefault(url, {}).setdefault(d, {})[key] = avail
        for url, days in per.items():
            for d, offers in days.items():
                n_out = sum(1 for a in offers.values() if a == "out_of_stock")
                n_in = sum(1 for a in offers.values() if a in _ORDERABLE)
                n_unk = len(offers) - n_out - n_in
                if n_in and n_out:
                    state = "mixed"
                elif n_in:
                    state = "in"
                elif n_out and not n_unk:
                    state = "out" if certified else "unverified"
                else:
                    state = "unknown"
                self.merchant.setdefault(url, {})[d] = {
                    "state": state,
                    "offers": [{"offer_id": k[0], "target_country": k[1], "availability": a}
                               for k, a in sorted(offers.items())]}
        self.m_counts = {"urls": len(self.merchant), "offer_days": len(seen), "duplicate_rows": dup,
                         "unparsed_rows": bad, "catalog_certified": certified}
        if dup:
            self.m_notes.append(f"{dup} duplicate offer/date rows (differing values become unknown)")
        if bad:
            self.m_notes.append(f"{bad} rows without a parseable date, absolute link or offer_id")

    def _load_pages(self, ctx) -> None:
        t = ctx.table(PAGES)
        cols = ["url", "checked_at", "stock_state", "matched_marker"]
        if t is None or t.missing(cols):
            return
        self.p_loaded = True
        if not self.markers:
            self.p_notes.append("profile.out_of_stock_markers not declared: out_of_stock page rows unusable")
        undeclared = non_ok = bad = 0
        for r in sorted(t.rows, key=lambda r: (str(r.get("url")), str(r.get("checked_at")))):
            d = V.parse_date(r.get("checked_at"))
            url = _norm_url(r.get("url"), self.ignore)
            if d is None or url is None:
                bad += 1
                continue
            raw = str(r.get("stock_state") or "").strip().lower().replace(" ", "_")
            marker = r.get("matched_marker")
            status = V.integer(r.get("http_status")) if "http_status" in t.columns else None
            if status is not None and not 200 <= status < 300:
                non_ok += 1
                state = "unknown"
            elif raw == "out_of_stock":
                if V.norm_text(marker) and V.norm_text(marker) in self.markers:
                    state = "out"
                else:
                    undeclared += 1
                    state = "unknown"
            elif raw == "in_stock":
                state = "in"
            else:
                state = "unknown"
            # sorted by checked_at: the latest check of the day wins
            self.pages.setdefault(url, {})[d] = {"state": state, "checked_at": r.get("checked_at"), "marker": marker,
                                                 "http_status": status}
        self.p_counts = {"urls": len(self.pages), "undeclared_marker_rows": undeclared, "non_2xx_rows": non_ok,
                         "unparsed_rows": bad}
        if undeclared:
            self.p_notes.append(f"{undeclared} out_of_stock rows lack a profile-declared marker (treated unknown)")
        if non_ok:
            self.p_notes.append(f"{non_ok} non-2xx page checks treated unknown (skill-079 owns broken URLs)")
        if bad:
            self.p_notes.append(f"{bad} rows without a parseable checked_at or absolute url")

    @property
    def usable(self) -> bool:
        return self.m_loaded or self.p_loaded

    def current(self, url: str) -> dict:
        """Current state of a normalized URL. Rules: latest dated evidence within stock_evidence_max_age_days wins; conflicting same-day evidence → conflict."""
        cur, last = [], []
        for src, data in (("merchant", self.merchant), ("page", self.pages)):
            days = data.get(url) or {}
            if not days:
                continue
            last.append((src, max(days), days[max(days)]["state"]))
            if self.ref is None:
                continue
            ok = [d for d in days if abs((d - self.ref).days) <= self.max_age]
            if ok:
                d = max(ok)
                cur.append({"source": src, "date": d, **days[d]})
        if cur:
            states = {c["state"] for c in cur if c["state"] != "unknown"}
            state = "unknown" if not states else states.pop() if len(states) == 1 else "conflict"
            return {"state": state, "observations": cur}
        if last:
            return {"state": "stale", "last": [{"source": s, "date": d, "state": st} for s, d, st in last]}
        return {"state": "unmatched"}

    def out_days(self, url: str) -> list:
        """Dates with a same-day 'out' observation and no same-day orderable/conflicting observation."""
        days = set(self.merchant.get(url) or {}) | set(self.pages.get(url) or {})
        out = []
        for d in sorted(days):
            states = {x["state"] for x in ((self.merchant.get(url) or {}).get(d), (self.pages.get(url) or {}).get(d))
                      if x is not None} - {"unknown"}
            if states == {"out"}:
                out.append(d)
        return out


def _parents(ctx) -> tuple[dict, dict]:
    camps = {str(r.get("id")): _upper(r.get("status")) for r in ctx.rows("campaigns")}
    groups = {str(r.get("id")): _upper(r.get("status")) for r in ctx.rows("ad_groups")}
    return camps, groups


def _active(status, cid, gid, camps, groups, need_group: bool) -> bool | None:
    """True/False when decidable; None when an entity or parent status is unknown."""
    states = [_upper(status), camps.get(str(cid or "")) or ""]
    if need_group:
        states.append(groups.get(str(gid or "")) or "")
    if any(s and s != "ENABLED" for s in states):
        return False
    return None if any(not s for s in states) else True


def _load_daily(ctx, chk) -> dict | None:
    """(entity_type, campaign_id, ad_group_id, entity_id) -> date -> (cost, clicks, impressions)."""
    if not chk.runnable:
        return None
    t = ctx.table(DAILY)
    lo, hi = ctx.period_start, ctx.period_end
    out: dict = {}
    dup_keys: set = set()
    for r in t.rows:
        d = V.parse_date(r.get("date"))
        if d is None or (lo and d < lo) or (hi and d > hi):
            continue
        key = (str(r.get("entity_type") or "").strip().lower(), str(r.get("campaign_id") or ""),
               str(r.get("ad_group_id") or ""), str(r.get("entity_id") or ""))
        if d in out.get(key, {}):
            dup_keys.add(key)
            continue
        out.setdefault(key, {})[d] = (ctx.money(r.get("cost")), V.num(r.get("clicks")), V.num(r.get("impressions")))
    for k in dup_keys:
        out.pop(k, None)
    if dup_keys:
        chk.partial(f"{len(dup_keys)} entities with duplicate date rows excluded from exposure (no double counting)")
    return out


def _exposure(daily: dict | None, key: tuple, out_days: list) -> dict:
    if daily is None:
        return {"available": False, "reason": f"{DAILY} missing"}
    if key[0] == "sitelink":
        return {"available": False, "reason": "sitelink cost is not attributable per entity in entity_daily"}
    rows = daily.get(key)
    if not rows:
        return {"available": False, "reason": "no daily rows for this entity in the report window"}
    hit = [d for d in out_days if d in rows]
    cost = [rows[d][0] for d in hit]
    if any(c is None for c in cost):
        return {"available": False, "reason": "unknown cost on an out-of-stock day"}
    return {"available": True, "out_of_stock_days_observed": len(out_days), "days_with_metrics": len(hit),
            "cost": sum(cost), "clicks": sum(rows[d][1] or 0 for d in hit),
            "impressions": sum(rows[d][2] or 0 for d in hit),
            "dates": [d.isoformat() for d in hit]}


# ----------------------------------------------------------------------------- entities
def _ads(ctx, camps, groups, ignore):
    t = ctx.table("ads")
    col = _url_col(t)
    for r in sorted(t.rows, key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("id")))):
        yield ("ad", str(r.get("campaign_id") or ""), str(r.get("ad_group_id") or ""), str(r.get("id") or ""),
               _active(r.get("status"), r.get("campaign_id"), r.get("ad_group_id"), camps, groups, True),
               [u for u in (_norm_url(x, ignore) for x in _as_list(r.get(col))) if u])


def _keywords(ctx, camps, groups, ignore):
    t = ctx.table("keywords")
    for r in sorted(t.rows, key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")), str(r.get("id")))):
        urls = [u for u in (_norm_url(x, ignore) for x in _as_list(r.get("final_url"))) if u]
        if not urls:
            continue  # no override: the keyword inherits its ads' URLs
        yield ("keyword", str(r.get("campaign_id") or ""), str(r.get("ad_group_id") or ""), str(r.get("id") or ""),
               _active(r.get("status"), r.get("campaign_id"), r.get("ad_group_id"), camps, groups, True), urls)


def _sitelinks(ctx, camps, groups, ignore):
    t = ctx.table("assets")
    col = _url_col(t)
    for r in sorted(t.rows, key=lambda r: (str(r.get("asset_id")), str(r.get("level")), str(r.get("campaign_id")),
                                           str(r.get("ad_group_id")))):
        if _upper(r.get("type")) != "SITELINK":
            continue
        level = _upper(r.get("level"))
        if level == "ACCOUNT":
            act = True if _upper(r.get("status")) == "ENABLED" else None if not _upper(r.get("status")) else False
        else:
            act = _active(r.get("status"), r.get("campaign_id"), r.get("ad_group_id"), camps, groups,
                          level == "AD_GROUP")
        yield ("sitelink", str(r.get("campaign_id") or ""), str(r.get("ad_group_id") or ""), str(r.get("asset_id") or ""),
               act, [u for u in (_norm_url(x, ignore) for x in _as_list(r.get(col))) if u])


def _asset_groups(ctx, camps, groups, ignore):
    for r in sorted(ctx.rows(AG_URLS), key=lambda r: (str(r.get("campaign_id")), str(r.get("asset_group_id")),
                                                       str(r.get("final_url")))):
        yield ("asset_group", str(r.get("campaign_id") or ""), "", str(r.get("asset_group_id") or ""),
               _active(r.get("status"), r.get("campaign_id"), None, camps, groups, False),
               [u for u in (_norm_url(x, ignore) for x in _as_list(r.get("final_url"))) if u])


def _evaluate(ctx, chk, entities, stock: _Stock, daily) -> None:
    counts = {"active_urls": 0, "in": 0, "out": 0, "mixed": 0, "unknown": 0, "unmatched": 0, "stale": 0,
              "conflict": 0, "unverified": 0, "inactive": 0, "status_unknown": 0}
    seen: set = set()
    for etype, cid, gid, eid, active, urls in entities:
        if active is False:
            counts["inactive"] += 1
            continue
        if active is None:
            counts["status_unknown"] += 1
            continue
        for url in urls:
            if (etype, cid, gid, eid, url) in seen:
                continue
            seen.add((etype, cid, gid, eid, url))
            counts["active_urls"] += 1
            cur = stock.current(url)
            state = cur["state"]
            counts[state] = counts.get(state, 0) + 1
            entity = {"entity_type": etype, "campaign_id": cid, "ad_group_id": gid or None, "entity_id": eid, "url": url}
            base_ev = {"stock": cur, "reference_date": stock.ref, "stock_evidence_max_age_days": stock.max_age}
            if state == "out":
                _out_finding(ctx, chk, entity, base_ev, stock, daily)
            elif state == "mixed":
                chk.finding("mixed_availability", "Info", entity,
                            f"{etype} {eid} points to {url}: some mapped offers out of stock, others orderable",
                            evidence=base_ev, recommendation="Confirm the page defaults to an orderable variant.",
                            uncertainty="Variant-level stock; the landing page may still sell the available variants.")
            elif state in ("stale", "conflict", "unverified"):
                last_out = state != "stale" or any(x["state"] == "out" for x in cur.get("last", []))
                if last_out:
                    chk.finding(f"stock_evidence_{state}", "Info", entity,
                                f"{etype} {eid} destination {url}: stock evidence {state}; availability unknown",
                                evidence=base_ev,
                                recommendation="Request a current, complete stock observation for this URL.",
                                uncertainty="Not a confirmed out-of-stock destination.")
    if counts["unmatched"]:
        chk.partial(f"{counts['unmatched']} active entity URLs have no stock observation (availability unknown)")
    if counts["status_unknown"]:
        chk.partial(f"{counts['status_unknown']} entities with unknown entity/parent status not evaluated")
    chk.observe("Active destination URLs matched to stock evidence", **counts)


def _out_finding(ctx, chk, entity, base_ev, stock, daily) -> None:
    etype, cid, eid, url = entity["entity_type"], entity["campaign_id"], entity["entity_id"], entity["url"]
    key = (etype, cid, entity["ad_group_id"] or "", eid)
    exp = _exposure(daily, key, stock.out_days(url))
    spend = ctx.params.get("spend_significant", cid or None)
    ev = {**base_ev, "exposure": exp, "currency": ctx.currency, "spend_significant": spend.value,
          "spend_significant_source": spend.source or spend.reason}
    calc = {"exposure_rule": "sum entity_daily cost on dates with same-day out observation",
            "window": [ctx.period_start, ctx.period_end]}
    prov = chk.finding("active_entity_out_of_stock", "Warning", entity,
                       f"Active {etype} {eid} (campaign {cid}) sends traffic to {url}, out of stock on current evidence"
                       + (f"; {exp['cost']:.2f} {ctx.currency} spent on {exp['days_with_metrics']} observed "
                          f"out-of-stock days" if exp.get("available") else ""),
                       evidence=ev, calculation=calc,
                       recommendation="Request-only: pause the entity or redirect it to an in-stock destination "
                                      "after the owner confirms restock timing; no account change made.",
                       uncertainty="Exposure is not savings; an out-of-stock page may still sell alternatives.")
    outcomes = {
        "pause_or_redirect": {"severity": "Warning", "recommendation":
                              "Propose pausing or redirecting (proposal.action pause|redirect, redirect_url)."},
        "intentional_keep": {"severity": None, "recommendation":
                             "Keep: owner-approved back-order/alternatives page; document the decision."},
        "uncertain": {"severity": "Warning", "recommendation":
                      "Keep the Warning; ask the owner for restock timing and alternatives."},
    }
    if exp.get("available") and spend.value is not None and exp["cost"] >= spend.value:
        outcomes["no_purchase_path_material"] = {
            "severity": "Critical", "recommendation":
            "Prioritize the pause/redirect proposal; cite evidence that no purchasable alternative existed."}
    chk.review("active_entity_out_of_stock", entity,
               f"Should active {etype} {eid} keep sending traffic to out-of-stock {url}, or be paused/redirected?",
               evidence=ev, outcomes=outcomes, provisional=prov,
               guidance="Use only supplied stock evidence, profile objectives and page alternatives the client "
                        "documented. proposal = {action: pause|redirect, redirect_url (redirect only), "
                        "evidence_ref (Critical only)}. Never claim recoverable savings.")


def _stale_dates(ctx, camps, groups) -> None:
    chk = ctx.check("stale_date_claims", "Past years/dates in active ad text",
                    {"ads": ["id", "campaign_id", "ad_group_id", "status", "headlines", "descriptions"],
                     "campaigns": ["id", "status"], "ad_groups": ["id", "status"]})
    if not chk.runnable:
        return
    if ctx.as_of is None:
        chk.skip("as_of unknown (profile.reporting_end_date / account.date_range_end)", ["account:date_range_end"])
        return
    scanned = flagged = unknown = 0
    for r in sorted(ctx.rows("ads"), key=lambda r: (str(r.get("campaign_id")), str(r.get("ad_group_id")),
                                                    str(r.get("id")))):
        act = _active(r.get("status"), r.get("campaign_id"), r.get("ad_group_id"), camps, groups, True)
        if act is None:
            unknown += 1
        if act is not True:
            continue
        scanned += 1
        tokens = []
        for field in ("headlines", "descriptions"):
            for text in _as_list(r.get(field)):
                for m in _ISO.finditer(text):
                    d = V.parse_date(m.group(1))
                    if d is not None and d < ctx.as_of:
                        tokens.append({"field": field, "text": text, "token": m.group(1)})
                for m in _YEAR.finditer(text):
                    if int(m.group(1)) < ctx.as_of.year:
                        tokens.append({"field": field, "text": text, "token": m.group(1)})
        if not tokens:
            continue
        flagged += 1
        entity = {"campaign_id": str(r.get("campaign_id")), "ad_group_id": str(r.get("ad_group_id")),
                  "ad_id": str(r.get("id"))}
        ev = {"tokens": tokens, "as_of": ctx.as_of}
        prov = chk.finding("past_date_in_ad_text", "Info", entity,
                           f"Active ad {r.get('id')} text contains {len(tokens)} year/date token(s) before {ctx.as_of}",
                           evidence=ev, calculation={"rule": "year < as_of.year or ISO date < as_of"},
                           recommendation="Review whether the text claims a current offer/edition; propose updated copy.",
                           uncertainty="Founding years, model years and dated facts are legitimate.")
        chk.review("stale_date_claim", entity,
                   f"Does active ad {r.get('id')} present a past year/date as current (stale offer, edition, season)?",
                   evidence=ev, provisional=prov,
                   outcomes={"stale_claim": {"severity": "Warning", "recommendation":
                                             "Propose request-only copy update to a verified current claim."},
                             "legitimate_reference": {"severity": None, "recommendation": "No action."},
                             "uncertain": {"severity": "Info", "recommendation": "Ask the owner which claim is current."}},
                   guidance="A year is stale only when the copy presents it as current; founding/model years are not.")
    if unknown:
        chk.partial(f"{unknown} ads with unknown entity/parent status not scanned")
    chk.observe("Active ad text scanned for past years/dates", ads_scanned=scanned, ads_flagged=flagged,
                as_of=ctx.as_of)


# ----------------------------------------------------------------------------- run
def run(ctx) -> None:
    """Run stock-state, destination (ads/keywords/sitelinks/asset groups), OOS exposure and stale-date checks.

    Rules:   Destination checks skip without a final-URL column or usable Merchant/page stock evidence. Active entity
             to a URL currently 'out' → Warning + ai_review (Critical outcome only if exposure >= spend_significant);
             mixed/stale/conflict/unverified stock → Info. Exposure totals are observe-only, never savings; past
             years/dates in active ad text → Info + ai_review, skipped when ctx.as_of is unknown.
    """
    stock = _Stock(ctx)
    m = ctx.check("merchant_stock_state", "Merchant availability per destination URL and date",
                  {MERCHANT: ["snapshot_date", "offer_id", "target_country", "link", "availability"]})
    if m.runnable:
        for n in stock.m_notes:
            m.partial(n)
        m.observe("Merchant availability mapped to URLs", **stock.m_counts)
    p = ctx.check("page_stock_state", "Declared-marker page stock checks",
                  {PAGES: ["url", "checked_at", "stock_state", "matched_marker"]})
    if p.runnable:
        for n in stock.p_notes:
            p.partial(n)
        p.observe("Page stock checks mapped to URLs", markers=sorted(stock.markers), **stock.p_counts)
    if stock.age_note:
        (m if m.runnable else p).partial(stock.age_note)
    if stock.ref is None and stock.usable:
        (m if m.runnable else p).partial("configuration snapshot and as_of unknown: no current stock state")

    exp = ctx.check("oos_spend_exposure", "Spend on observed out-of-stock days",
                    {DAILY: ["date", "entity_type", "campaign_id", "ad_group_id", "entity_id", "cost"]})
    daily = _load_daily(ctx, exp)
    camps, groups = _parents(ctx)
    base = {"campaigns": ["id", "status"]}
    specs = (
        ("ad_destinations", "Active ad final URLs vs stock", {**base, "ad_groups": ["id", "status"],
                                                               "ads": ["id", "campaign_id", "ad_group_id", "status"]},
         "ads", _ads),
        ("keyword_destinations", "Active keyword URL overrides vs stock",
         {**base, "ad_groups": ["id", "status"],
          "keywords": ["id", "campaign_id", "ad_group_id", "status", "final_url"]}, None, _keywords),
        ("sitelink_destinations", "Active sitelink URLs vs stock",
         {**base, "ad_groups": ["id", "status"], "assets": ["asset_id", "type", "level", "status"]}, "assets", _sitelinks),
        ("asset_group_destinations", "Active asset-group URLs vs stock",
         {**base, AG_URLS: ["campaign_id", "asset_group_id", "final_url", "status"]}, None, _asset_groups),
    )
    stock_missing = [f"{MERCHANT} (file)", f"{PAGES} (file)"]
    for cid, title, needs, url_table, gen in specs:
        chk = ctx.check(cid, title, needs)
        if not chk.runnable:
            continue
        if url_table and _url_col(ctx.table(url_table)) is None:
            chk.skip("final URL column missing", [f"{url_table}:final_urls|final_url"])
            continue
        if not stock.usable:
            chk.skip("no usable stock evidence (Merchant availability or page checks)", stock_missing)
            continue
        _evaluate(ctx, chk, gen(ctx, camps, groups, stock.ignore), stock, daily)
    if exp.runnable:
        n = sum(1 for f in ctx.result.findings if f.condition_key == "active_entity_out_of_stock"
                and f.evidence.get("exposure", {}).get("available"))
        total = sum(f.evidence["exposure"]["cost"] for f in ctx.result.findings
                    if f.condition_key == "active_entity_out_of_stock" and f.evidence.get("exposure", {}).get("available"))
        exp.observe("Observed spend on out-of-stock days (exposure, not savings)", entities_with_exposure=n,
                    cost=total, currency=ctx.currency, window=[ctx.period_start, ctx.period_end])
    _stale_dates(ctx, camps, groups)


def verify(ctx, item, decision) -> list[str]:
    """Rules: pause/redirect proposals match the reviewed entity; redirect targets are currently 'in';
    Critical needs proposal.evidence_ref and exposure >= spend_significant from the reviewed evidence."""
    if item.condition_key != "active_entity_out_of_stock":
        return []
    outcome = decision.get("outcome")
    if outcome not in ("pause_or_redirect", "no_purchase_path_material"):
        return []
    proposal = decision.get("proposal") or {}
    problems = []
    action = str(proposal.get("action") or "").lower()
    if action not in ("pause", "redirect"):
        problems.append("proposal.action must be pause or redirect")
    if action == "redirect":
        stock = _Stock(ctx)
        target = _norm_url(proposal.get("redirect_url"), stock.ignore)
        if target is None:
            problems.append("redirect proposal needs an absolute proposal.redirect_url")
        elif target == item.entity.get("url"):
            problems.append("redirect_url is the out-of-stock destination itself")
        elif stock.current(target)["state"] != "in":
            problems.append(f"redirect_url {target} is not evidenced in stock on current evidence "
                            f"(state {stock.current(target)['state']})")
    if outcome == "no_purchase_path_material":
        if not proposal.get("evidence_ref"):
            problems.append("Critical needs proposal.evidence_ref pointing at supplied evidence")
        exp, floor = item.evidence.get("exposure") or {}, item.evidence.get("spend_significant")
        if not exp.get("available") or floor is None or exp.get("cost", 0) < floor:
            problems.append("Critical needs observed out-of-stock exposure >= spend_significant")
    return problems


if __name__ == "__main__":
    sys.exit(cli.main(SKILL, VERSION, run, verify))
