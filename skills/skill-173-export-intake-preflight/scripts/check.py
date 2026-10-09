"""check.py — skill-173 guided intake: Google Ads UI report downloads → normalized adsrun export + readiness check.

exports: SKILL | VERSION | MAPPING_SCHEMA | REPORTS | BASE_REQUIRED
         run(ctx) -> None | preflight(raw, out, tables=None) -> int | apply(raw, mapping_path, out) -> int
         main(argv=None) -> int | read_ui_file(name, data) -> dict | detect_number_locale(cells) -> dict
used_by: skills/skill-173-export-intake-preflight/SKILL.md → Analysis Steps (preflight → apply → run);
         skills/skill-173-export-intake-preflight/tests/test_check.py
related: skills/_resources/DATA_CONTRACT.md — semantic columns, account row and table_manifest this writes;
         skills/_resources/runtime/adsrun/evidence.py — the loader that reads the export apply produces
rules:   NEVER GUESS. Header synonyms are exact matches after _norm() (casefold, collapsed spaces), never fuzzy;
         they are proposals that become final only through apply with "confirmed": true. Unrecognized,
         ambiguous (one header → several semantics) and conflicting (several headers → one semantic)
         columns get action null and apply REFUSES (exit 2) until each is mapped or explicitly dropped.
         Number locale is DETECTED only from separator evidence (a cell valid in exactly one of IT
         '1.234,56' / EN '1,234.56'); integer-only or '1.234'-style cells are undetermined → question;
         mixed evidence → question. apply parses with the confirmed locale and refuses any cell that
         does not fit it. Rates become fractions; '< 10%' becomes '<0.1' (adsrun reads it as withheld);
         '--' and other V.MISSING_TOKENS become empty; totals rows ('Total:'/'Totale:' as first non-empty
         cell with empty ID cells) are removed and counted, never summed.
         Money stays in source units; account.money_unit is the confirmed answer ('micros' only if
         confirmed) — no rescaling here. IDs are verbatim strings; scientific-notation or digit-grouped
         IDs (spreadsheet damage) are refused. One customer per intake.
         PII: headers like email/telefono/phone number, or >= 50% email/phone-looking cells, are excluded
         and can never be mapped (apply re-detects from the file, not from the mapping); stray
         email/phone-looking cells in kept text columns are blanked and counted.
         apply refuses a mapping whose file sha256 or header list differs from the raw file (re-run
         preflight), and writes only into an empty/new --out. Raw folders and ZIPs are read in memory,
         never extracted. Completeness is 'complete' only when filters.applied is false for that file;
         otherwise 'partial — <description>'. search_terms truncation always declares visible terms only.
         Synonym sources (consulted 2026-09-25): support.google.com/google-ads/answer/2454071 (columns),
         /2472708 (search terms report), /6270625 (conversion columns), /7103314 (impression share),
         /6167118 (Quality Score), /99482 (keyword status), /2549115 (campaign status), /2454072
         (segments), /2375431 (downloads), /11306973 (custom columns), each in hl=en and hl=it.
         Headers found verbatim in those pages are listed in VERIFIED_HEADERS; every other synonym is
         UNVERIFIED (practitioner knowledge of UI downloads) and preflight.md labels it so.
         Every message, question, preflight.md and intake_report.md is ENGLISH. Italian synonyms stay as
         recognized data (header/value dictionaries); a displayed header in ITALIAN_UI_HEADERS carries the
         label "(Italian UI header)" via _col()/_col_md(). Status labels in proposed_mapping.json are English
         (suggested, ambiguous, conflict, unrecognized, table_undecided, pii, derived, unused).
         run(): readiness of an already-normalized export against BASE_REQUIRED; missing tables/columns
         are coverage (skipped), never findings; no severity above Warning.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_intake | initial guided intake, preflight, apply, readiness
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_intake_safety | raw input limits: size, entries, ratio, nested ZIP, symlinks
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_english | all user-facing text English; Italian UI headers labeled
"""
from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[1] / "_resources" / "runtime"):
    if (_p / "adsrun").is_dir():
        sys.path.insert(0, str(_p))
        break
from adsrun import cli  # noqa: E402
from adsrun import values as V  # noqa: E402

SKILL = "skill-173-export-intake-preflight"
VERSION = "1.0.0"
MAPPING_SCHEMA = "eppc-intake-mapping/1"
RAW_SUFFIXES = (".csv", ".tsv", ".txt")
MAX_VALUES = 100  # distinct enum values listed per column

# ----------------------------------------------------------------------------- header dictionary
# Entry: (semantic, kind, header names EN+IT). kind: id|text|int|number|money|rate|date|list|enum:<vocab>.
# A header listed under two semantics of the same report is AMBIGUOUS by construction (e.g. "Stato").


def _h(sem: str, kind: str, *names: str) -> tuple:
    return sem, kind, names


IDS = {
    "customer_id": _h("customer_id", "id", "Customer ID", "ID cliente"),
    "campaign_id": _h("campaign_id", "id", "Campaign ID", "Camp. ID", "ID campagna", "ID camp."),
    "campaign_name": _h("campaign_name", "text", "Campaign", "Campagna"),
    "ad_group_id": _h("ad_group_id", "id", "Ad group ID", "ID gruppo di annunci"),
    "ad_group_name": _h("ad_group_name", "text", "Ad group", "Gruppo di annunci"),
    "keyword_id": _h("keyword_id", "id", "Keyword ID", "Criterion ID", "ID parola chiave", "ID criterio"),
    "ad_id": _h("ad_id", "id", "Ad ID", "ID annuncio"),
}
METRICS = [
    _h("impressions", "int", "Impr.", "Impressions", "Impressioni"),
    _h("clicks", "int", "Clicks", "Clic"),
    _h("cost", "money", "Cost", "Costo"),
    _h("conversions", "number", "Conversions", "Conversioni", "Conv."),
    _h("conversion_value", "money", "Conv. value", "Conversion value", "Valore conv.", "Valore di conversione"),
    _h("all_conversions", "number", "All conv.", "Tutte le conv."),
    _h("all_conversion_value", "money", "All conv. value", "Valore tutte le conv.", "Valore di tutte le conv."),
    _h("conversions_by_conv_time", "number", "Conv. (by conv. time)", "Conv. (per ora conv.)"),
    _h("conversion_value_by_conv_time", "money", "Conv. value (by conv. time)", "Valore conv. (per ora conv.)"),
    _h("interactions", "int", "Interactions", "Interazioni"),
]
SHARE = [
    _h("search_impression_share", "rate", "Search impr. share", "Quota impr. rete di ricerca",
       "Quota impressioni sulla rete di ricerca"),
    _h("search_budget_lost_is", "rate", "Search lost IS (budget)", "QI persa rete di ricerca (budget)"),
    _h("search_rank_lost_is", "rate", "Search lost IS (rank)", "QI persa rete di ricerca (ranking)"),
    _h("top_impression_rate", "rate", "Impr. (Top) %", "Impr. (parte sup.) %"),
    _h("abs_top_impression_rate", "rate", "Impr. (Abs. Top) %", "Impr. (parte sup. ass.) %"),
    _h("search_top_is", "rate", "Search top IS"),
    _h("search_abs_top_is", "rate", "Search abs. top IS"),
]
SEGMENTS = [
    _h("date", "date", "Day", "Giorno"),
    _h("device", "enum:device", "Device", "Dispositivo"),
    _h("network", "enum:network", "Network (with search partners)", "Rete (con partner di ricerca)"),
]
DERIVED = [  # recognized; proposed drop because recipes recompute ratios from summed numerators/denominators
    _h("ctr", "rate", "CTR"),
    _h("avg_cpc", "money", "Avg. CPC", "CPC medio"),
    _h("cost_per_conversion", "money", "Cost / conv.", "Costo/conv."),
    _h("conversion_rate", "rate", "Conv. rate", "Tasso di conv."),
    _h("value_per_cost", "number", "Conv. value / cost", "Valore conv./costo"),
    _h("avg_cost", "money", "Avg. cost", "Costo medio"),
    _h("interaction_rate", "rate", "Interaction rate", "Tasso di interazione"),
    _h("avg_cpm", "money", "Avg. CPM", "CPM medio"),
    _h("value_per_conversion", "money", "Value / conv.", "Valore/conv."),
    _h("cost_per_all_conversions", "money", "Cost / all conv.", "Costo/tutte le conv."),
]
CONTEXT = [  # recognized context columns; proposed drop (not part of the target table)
    _h("status_reasons", "text", "Status reasons", "Motivi dello stato"),
    _h("optimization_score", "text", "Optimization score", "Punteggio di ottimizzazione"),
    _h("currency_code", "text", "Currency code", "Codice valuta"),
    _h("account_name", "text", "Account name", "Nome account"),
]
PARENT_CAMPAIGN_STATUS = _h("parent_campaign_status", "text", "Campaign status", "Stato della campagna",
                            "Stato campagna")
PARENT_AD_GROUP_STATUS = _h("parent_ad_group_status", "text", "Ad group status", "Stato del gruppo di annunci",
                            "Stato gruppo di annunci")
_STATUS_WORDS = ("Status", "Stato")  # set status vs serving status: always ambiguous, the colleague decides

CAMPAIGN_ATTRS = [
    _h("campaign_status", "enum:status", "Campaign status", "Stato della campagna", "Stato campagna", *_STATUS_WORDS),
    _h("serving_status", "text", *_STATUS_WORDS),
    _h("channel_type", "enum:channel_type", "Campaign type", "Tipo di campagna"),
    _h("channel_subtype", "text", "Campaign subtype", "Sottotipo di campagna"),
    _h("bidding_strategy_type", "enum:bidding", "Bid strategy type", "Tipo di strategia di offerta"),
    _h("bidding_strategy_name", "text", "Bid strategy", "Strategia di offerta"),
    _h("daily_budget", "money", "Budget"),
    _h("budget_name", "text", "Budget name", "Nome budget"),
    _h("budget_type", "text", "Budget type", "Tipo di budget"),
    _h("target_cpa", "money", "Target CPA", "CPA target"),
    _h("target_roas", "rate", "Target ROAS", "ROAS target"),
    _h("labels", "list", "Labels", "Etichette"),
    _h("start_date", "date", "Start date", "Data di inizio"),
    _h("end_date", "date", "End date", "Data di fine"),
]
AD_GROUP_ATTRS = [
    _h("ad_group_status", "enum:status", "Ad group status", "Stato del gruppo di annunci", "Stato gruppo di annunci",
       *_STATUS_WORDS),
    _h("serving_status", "text", *_STATUS_WORDS),
    _h("ad_group_type", "text", "Ad group type", "Tipo di gruppo di annunci"),
    _h("default_cpc", "money", "Default max. CPC", "Default Max. CPC", "CPC max predefinito", "CPC max. predefinito"),
]
KEYWORD_ATTRS = [
    _h("keyword_text", "text", "Keyword", "Search keyword", "Parola chiave", "Parola chiave della rete di ricerca"),
    _h("match_type", "enum:match_type", "Match type", "Search keyword match type", "Tipo di corrispondenza"),
    _h("keyword_status", "enum:status", "Keyword status", "Stato parola chiave", "Stato della parola chiave",
       *_STATUS_WORDS),
    _h("serving_status", "text", *_STATUS_WORDS),
    _h("quality_score", "int", "Quality Score", "Punteggio di qualità"),
    _h("expected_ctr", "enum:qs_component", "Exp. CTR", "Expected CTR", "CTR previsto"),
    _h("ad_relevance", "enum:qs_component", "Ad relevance", "Pertinenza annuncio", "Pertinenza dell'annuncio"),
    _h("landing_page_experience", "enum:qs_component", "Landing page exp.", "Landing page experience",
       "Esperienza sulla pagina di destinazione", "Esperienza pagina di destinazione"),
    _h("final_url", "text", "Final URL", "URL finale"),
    _h("cpc_bid", "money", "Max. CPC", "CPC max", "CPC max."),
    _h("first_page_cpc", "money", "Est. first page bid", "Offerta stimata per la prima pagina"),
    _h("top_of_page_cpc", "money", "Est. top of page bid", "Offerta stimata per la parte superiore della pagina"),
]
SEARCH_TERM_ATTRS = [
    _h("search_term", "text", "Search term", "Termine di ricerca"),
    _h("search_term_match_type", "enum:search_term_match", "Match type", "Search terms match type",
       "Tipo di corrispondenza", "Tipo di corrispondenza del termine di ricerca"),
    _h("added_excluded", "enum:added_excluded", "Added/Excluded", "Aggiunto/Escluso"),
    _h("keyword_text", "text", "Keyword", "Parola chiave"),
]
NEGATIVE_ATTRS = [
    _h("negative_text", "text", "Negative keyword", "Parola chiave esclusa"),
    _h("match_type", "enum:match_type", "Match type", "Tipo di corrispondenza"),
    _h("level", "enum:level", "Level", "Livello"),
]
AD_ATTRS = [
    _h("ad_type", "enum:ad_type", "Ad type", "Tipo di annuncio"),
    _h("ad_status", "enum:status", "Ad status", "Stato annuncio", "Stato dell'annuncio", *_STATUS_WORDS),
    _h("serving_status", "text", *_STATUS_WORDS),
    *[_h(f"headline_{i}", "text", f"Headline {i}", f"Titolo {i}") for i in range(1, 16)],
    *[_h(f"description_{i}", "text", f"Description {i}", f"Descrizione {i}") for i in range(1, 5)],
    _h("path1", "text", "Path 1", "Percorso 1"),
    _h("path2", "text", "Path 2", "Percorso 2"),
    _h("final_url", "text", "Final URL", "URL finale"),
    _h("ad_strength", "enum:ad_strength", "Ad strength", "Efficacia dell'annuncio"),
    _h("approval_status", "text", "Approval status", "Stato di approvazione"),
]
CONVERSION_ATTRS = [
    _h("action_name", "text", "Conversion action", "Azione di conversione"),
    _h("action_id", "id", "Conversion action ID", "ID azione di conversione"),
    _h("category", "text", "Conversion category", "Categoria di conversione", "Category", "Categoria"),
    _h("source", "text", "Conversion source", "Origine conversione", "Source", "Origine"),
    _h("action_status", "enum:status", *_STATUS_WORDS),
    _h("tracking_status", "text", "Tracking status", "Stato monitoraggio", *_STATUS_WORDS),
    _h("counting", "enum:counting", "Count", "Conteggio"),
    _h("primary_for_goal", "enum:boolean_primary", "Action optimization", "Ottimizzazione azione"),
    _h("attribution_model", "text", "Attribution model", "Modello di attribuzione"),
    _h("click_window", "text", "Click-through conv. window", "Finestra di conversione clic"),
    _h("value_settings", "text", "Value", "Valore"),
]

# Synonyms found as whole phrases in the text of the consulted Google Ads Help pages (hl=en / hl=it, 2026-09-25).
# Generic words (Value/Valore, Stato, Categoria, Origine) are weak evidence: the page mentions them, not always as a
# column. Every synonym NOT in this set is unverified and preflight.md marks it "(unverified)".
VERIFIED_HEADERS = frozenset({
    'Ad ID', 'Ad group', 'Ad relevance', 'Ad status', 'Ad type', 'All conv.', 'All conv. value',
    'Attribution model', 'Avg. CPC', 'Avg. CPM', 'Azione di conversione', 'Bid strategy', 'Bid strategy type',
    'Budget', 'CPA target', 'CPC max', 'CPC max predefinito', 'CPC max.', 'CPC medio', 'CPM medio', 'CTR',
    'CTR previsto', 'Campagna', 'Campaign', 'Campaign status', 'Categoria', 'Categoria di conversione', 'Clic',
    'Clicks', 'Conv.', 'Conv. (by conv. time)', 'Conv. rate', 'Conv. value', 'Conv. value (by conv. time)',
    'Conv. value / cost', 'Conversion action', 'Conversion category', 'Conversion source', 'Conversion value',
    'Conversioni', 'Conversions', 'Cost', 'Cost / all conv.', 'Cost / conv.', 'Costo', 'Costo medio',
    'Costo/conv.', 'Costo/tutte le conv.', 'Customer ID', 'Data di fine', 'Day', 'Default Max. CPC', 'Device',
    'Dispositivo', "Efficacia dell'annuncio", 'Esperienza sulla pagina di destinazione', 'Est. first page bid',
    'Est. top of page bid', 'Exp. CTR', 'Final URL', 'Giorno', 'Gruppo di annunci', 'ID annuncio', 'ID cliente',
    'Impr.', 'Impressioni', 'Impressions', 'Interaction rate', 'Interactions', 'Interazioni', 'Keyword',
    'Keyword status', 'Landing page experience', 'Match type', 'Max. CPC', 'Modello di attribuzione',
    'Negative keyword', 'Network (with search partners)', 'Offerta stimata per la parte superiore della pagina',
    'Offerta stimata per la prima pagina', 'Origine', 'Origine conversione', 'Parola chiave',
    'Parola chiave esclusa', 'Pertinenza annuncio', 'Punteggio di qualità', 'QI persa rete di ricerca (budget)',
    'QI persa rete di ricerca (ranking)', 'Quality Score', 'Quota impr. rete di ricerca',
    'Quota impressioni sulla rete di ricerca', 'ROAS target', 'Rete (con partner di ricerca)',
    'Search impr. share', 'Search lost IS (budget)', 'Search lost IS (rank)', 'Search term',
    'Search terms match type', 'Stato', "Stato dell'annuncio", 'Stato della campagna',
    'Stato della parola chiave', 'Status', 'Strategia di offerta', 'Target CPA', 'Tasso di interazione',
    'Termine di ricerca', 'Tipo di annuncio', 'Tipo di corrispondenza',
    'Tipo di corrispondenza del termine di ricerca', 'Tipo di strategia di offerta', 'Tutte le conv.',
    'URL finale', 'Valore', 'Valore conv.', 'Valore conv./costo', 'Valore di conversione',
    'Valore di tutte le conv.', 'Valore tutte le conv.', 'Valore/conv.', 'Value', 'Value / conv.',
})

_PREFIX = [IDS["customer_id"]]
_METRIC_BLOCK = METRICS + SEGMENTS + DERIVED + CONTEXT

# Report types. "entity": (table, {out_col: semantic}); "metrics": (table, [key semantics]) — metric semantics
# (METRICS/SHARE/SEGMENTS) are appended automatically. A semantic with no route is recognized but proposed "drop".
_PARENTS = [PARENT_CAMPAIGN_STATUS, PARENT_AD_GROUP_STATUS]
REPORTS: dict[str, dict] = {
    "campaigns": {
        "label": "Campaigns",
        "columns": _PREFIX + [IDS["campaign_id"], IDS["campaign_name"]] + CAMPAIGN_ATTRS + SHARE + _METRIC_BLOCK,
        "entity": ("campaigns", {"id": "campaign_id", "name": "campaign_name", "status": "campaign_status",
                                 "serving_status": "serving_status", "channel_type": "channel_type",
                                 "channel_subtype": "channel_subtype", "bidding_strategy_type": "bidding_strategy_type",
                                 "bidding_strategy_name": "bidding_strategy_name", "daily_budget": "daily_budget",
                                 "budget_name": "budget_name", "budget_type": "budget_type", "target_cpa": "target_cpa",
                                 "target_roas": "target_roas", "labels": "labels", "start_date": "start_date",
                                 "end_date": "end_date", "customer_id": "customer_id"}),
        "metrics": ("campaign_metrics", ["customer_id", "campaign_id", "campaign_name"]),
    },
    "ad_groups": {
        "label": "Ad groups",
        "columns": _PREFIX + [IDS["campaign_id"], IDS["campaign_name"], IDS["ad_group_id"], IDS["ad_group_name"]]
        + AD_GROUP_ATTRS + [PARENT_CAMPAIGN_STATUS] + SHARE[:1] + SHARE[2:] + _METRIC_BLOCK,
        "entity": ("ad_groups", {"id": "ad_group_id", "campaign_id": "campaign_id", "campaign_name": "campaign_name",
                                 "name": "ad_group_name", "status": "ad_group_status",
                                 "serving_status": "serving_status", "type": "ad_group_type",
                                 "default_cpc": "default_cpc", "customer_id": "customer_id"}),
        "metrics": ("ad_group_metrics", ["customer_id", "campaign_id", "ad_group_id"]),
    },
    "keywords": {
        "label": "Keywords",
        "columns": _PREFIX + [IDS["campaign_id"], IDS["campaign_name"], IDS["ad_group_id"], IDS["ad_group_name"],
                              IDS["keyword_id"]] + KEYWORD_ATTRS + _PARENTS + SHARE[:1] + SHARE[2:] + _METRIC_BLOCK,
        "entity": ("keywords", {"id": "keyword_id", "campaign_id": "campaign_id", "campaign_name": "campaign_name",
                                "ad_group_id": "ad_group_id", "ad_group_name": "ad_group_name", "text": "keyword_text",
                                "match_type": "match_type", "status": "keyword_status",
                                "serving_status": "serving_status", "quality_score": "quality_score",
                                "expected_ctr": "expected_ctr", "ad_relevance": "ad_relevance",
                                "landing_page_experience": "landing_page_experience", "final_url": "final_url",
                                "cpc_bid": "cpc_bid", "first_page_cpc": "first_page_cpc",
                                "top_of_page_cpc": "top_of_page_cpc", "customer_id": "customer_id"}),
        "metrics": ("keyword_metrics", ["customer_id", "campaign_id", "ad_group_id", "keyword_id"]),
    },
    "search_terms": {
        "label": "Search terms",
        "columns": _PREFIX + [IDS["campaign_id"], IDS["campaign_name"], IDS["ad_group_id"], IDS["ad_group_name"],
                              IDS["keyword_id"]] + SEARCH_TERM_ATTRS + _PARENTS + _METRIC_BLOCK,
        "entity": ("search_terms", {"search_term": "search_term", "campaign_id": "campaign_id",
                                    "campaign_name": "campaign_name", "ad_group_id": "ad_group_id",
                                    "ad_group_name": "ad_group_name", "matched_keyword": "keyword_text",
                                    "matched_keyword_id": "keyword_id", "match_type": "search_term_match_type",
                                    "added_excluded": "added_excluded", "customer_id": "customer_id"}),
        "metrics": None,  # metrics stay on the search_terms rows (their grain includes the term)
    },
    "negative_keywords": {
        "label": "Negative keywords",
        "columns": _PREFIX + [IDS["campaign_id"], IDS["campaign_name"], IDS["ad_group_id"], IDS["ad_group_name"]]
        + NEGATIVE_ATTRS + _PARENTS + CONTEXT,
        "entity": ("negative_keywords", {"text": "negative_text", "match_type": "match_type", "level": "level",
                                         "campaign_id": "campaign_id", "campaign_name": "campaign_name",
                                         "ad_group_id": "ad_group_id", "ad_group_name": "ad_group_name",
                                         "customer_id": "customer_id"}),
        "metrics": None,
    },
    "ads": {
        "label": "Ads",
        "columns": _PREFIX + [IDS["campaign_id"], IDS["campaign_name"], IDS["ad_group_id"], IDS["ad_group_name"],
                              IDS["ad_id"]] + AD_ATTRS + _PARENTS + _METRIC_BLOCK,
        "entity": ("ads", {"id": "ad_id", "campaign_id": "campaign_id", "campaign_name": "campaign_name",
                           "ad_group_id": "ad_group_id", "ad_group_name": "ad_group_name", "type": "ad_type",
                           "status": "ad_status", "serving_status": "serving_status", "headlines": "headline_*",
                           "descriptions": "description_*", "path1": "path1", "path2": "path2",
                           "final_url": "final_url", "ad_strength": "ad_strength",
                           "approval_status": "approval_status", "customer_id": "customer_id"}),
        "metrics": ("ad_metrics", ["customer_id", "campaign_id", "ad_group_id", "ad_id"]),
    },
    "conversion_actions": {
        "label": "Conversion actions",
        "columns": _PREFIX + CONVERSION_ATTRS + METRICS + DERIVED + CONTEXT,
        "entity": ("conversion_actions", {"id": "action_id", "name": "action_name", "category": "category",
                                          "source": "source", "status": "action_status",
                                          "tracking_status": "tracking_status", "counting": "counting",
                                          "primary_for_goal": "primary_for_goal",
                                          "attribution_model": "attribution_model", "click_window": "click_window",
                                          "value_settings": "value_settings", "customer_id": "customer_id"}),
        "metrics": None,  # DATA_CONTRACT: action settings do not supply action metrics
    },
}
DETECT_ORDER = ("search_terms", "negative_keywords", "conversion_actions", "ads", "keywords", "ad_groups", "campaigns")
_EXCLUSIVE = ("search_terms", "negative_keywords", "conversion_actions")
MARKERS = {
    "search_terms": ("Search term", "Termine di ricerca"),
    "negative_keywords": ("Negative keyword", "Parola chiave esclusa"),
    "conversion_actions": ("Conversion action", "Azione di conversione"),
    "ads": ("Ad ID", "ID annuncio", "Ad type", "Tipo di annuncio", "Headline 1", "Titolo 1"),
    "keywords": ("Keyword", "Parola chiave", "Search keyword", "Parola chiave della rete di ricerca", "Keyword ID",
                 "ID parola chiave"),
    "ad_groups": ("Ad group", "Gruppo di annunci", "Ad group ID", "ID gruppo di annunci"),
    "campaigns": ("Campaign", "Campagna", "Campaign ID", "ID campagna", "Camp. ID"),
}
METRIC_SEMS = {e[0] for e in METRICS + SHARE}
SEGMENT_SEMS = {e[0] for e in SEGMENTS}
DERIVED_SEMS = {e[0] for e in DERIVED}
METRIC_ORDER = [e[0] for e in SEGMENTS + METRICS + SHARE]  # output column order for metric tables

# Base audit requirements on the OUTPUT tables (what recipes read).
BASE_REQUIRED = {
    "campaigns": ["id", "name", "status", "channel_type", "bidding_strategy_type", "daily_budget"],
    "campaign_metrics": ["campaign_id", "impressions", "clicks", "cost", "conversions", "conversion_value"],
    "ad_groups": ["id", "campaign_id", "name", "status"],
    "keywords": ["id", "campaign_id", "ad_group_id", "text", "match_type", "status"],
    "keyword_metrics": ["keyword_id", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"],
    "search_terms": ["search_term", "campaign_id", "ad_group_id", "impressions", "clicks", "cost", "conversions"],
    "ads": ["id", "campaign_id", "ad_group_id", "type", "status", "headlines", "descriptions", "final_url"],
    "negative_keywords": ["text", "match_type", "level", "campaign_id"],
    "conversion_actions": ["id", "name", "status", "category", "counting"],
}
ACCOUNT_REQUIRED = ["customer_id", "currency_code", "time_zone", "date_range_start", "date_range_end",
                    "snapshot_date", "rates_format", "money_unit"]
REPORT_FOR_TABLE = {"campaigns": "campaigns", "campaign_metrics": "campaigns", "ad_groups": "ad_groups",
                    "keywords": "keywords", "keyword_metrics": "keywords", "search_terms": "search_terms",
                    "ads": "ads", "negative_keywords": "negative_keywords",
                    "conversion_actions": "conversion_actions"}
# Synonyms that come from the Italian-language UI (hl=it). Displayed headers in this set are labeled
# "(Italian UI header)"; shared tokens (Impr., Budget, CTR) are not listed.
ITALIAN_UI_HEADERS = frozenset({
    'ID cliente', 'ID campagna', 'ID camp.', 'Campagna', 'ID gruppo di annunci', 'Gruppo di annunci',
    'ID parola chiave', 'ID criterio', 'ID annuncio', 'Impressioni', 'Clic', 'Costo', 'Conversioni', 'Conv.',
    'Valore conv.', 'Valore di conversione', 'Tutte le conv.', 'Valore tutte le conv.', 'Valore di tutte le conv.',
    'Conv. (per ora conv.)', 'Valore conv. (per ora conv.)', 'Interazioni', 'Quota impr. rete di ricerca',
    'Quota impressioni sulla rete di ricerca', 'QI persa rete di ricerca (budget)',
    'QI persa rete di ricerca (ranking)', 'Impr. (parte sup.) %', 'Impr. (parte sup. ass.) %', 'Giorno',
    'Dispositivo', 'Rete (con partner di ricerca)', 'CPC medio', 'Costo/conv.', 'Tasso di conv.',
    'Valore conv./costo', 'Costo medio', 'Tasso di interazione', 'CPM medio', 'Valore/conv.', 'Costo/tutte le conv.',
    'Motivi dello stato', 'Punteggio di ottimizzazione', 'Codice valuta', 'Nome account', 'Stato della campagna',
    'Stato campagna', 'Stato del gruppo di annunci', 'Stato gruppo di annunci', 'Stato', 'Tipo di campagna',
    'Sottotipo di campagna', 'Tipo di strategia di offerta', 'Strategia di offerta', 'Nome budget', 'Tipo di budget',
    'CPA target', 'ROAS target', 'Etichette', 'Data di inizio', 'Data di fine', 'Tipo di gruppo di annunci',
    'CPC max predefinito', 'CPC max. predefinito', 'Parola chiave', 'Parola chiave della rete di ricerca',
    'Tipo di corrispondenza', 'Stato parola chiave', 'Stato della parola chiave', 'Punteggio di qualità',
    'CTR previsto', 'Pertinenza annuncio', "Pertinenza dell'annuncio", 'Esperienza sulla pagina di destinazione',
    'Esperienza pagina di destinazione', 'URL finale', 'CPC max', 'CPC max.', 'Offerta stimata per la prima pagina',
    'Offerta stimata per la parte superiore della pagina', 'Termine di ricerca',
    'Tipo di corrispondenza del termine di ricerca', 'Aggiunto/Escluso', 'Parola chiave esclusa', 'Livello',
    'Tipo di annuncio', 'Stato annuncio', "Stato dell'annuncio", *(f"Titolo {i}" for i in range(1, 16)),
    *(f"Descrizione {i}" for i in range(1, 5)), 'Percorso 1', 'Percorso 2', "Efficacia dell'annuncio",
    'Stato di approvazione', 'Azione di conversione', 'ID azione di conversione', 'Categoria di conversione',
    'Categoria', 'Origine conversione', 'Origine', 'Stato monitoraggio', 'Conteggio', 'Ottimizzazione azione',
    'Modello di attribuzione', 'Finestra di conversione clic', 'Valore',
})


def _hint(en_path: str, en_cols: str, it_path: str, it_cols: str) -> str:
    return (f"{en_path}; columns: {en_cols} (Italian UI: {it_path}; Italian UI headers: {it_cols})")


DOWNLOAD_HINTS = {  # English and Italian UI navigation; menu labels are UNVERIFIED and may differ by account/UI version
    "campaigns": _hint("Campaigns → Campaigns", "Campaign ID, Campaign, Campaign status, Campaign type, Bid strategy "
                       "type, Budget, Impr., Clicks, Cost, Conversions, Conv. value", "Campagne → Campagne",
                       "ID campagna, Campagna, Stato della campagna, Tipo di campagna, Tipo di strategia di offerta, "
                       "Budget, Impr., Clic, Costo, Conversioni, Valore conv."),
    "ad_groups": _hint("Campaigns → Ad groups", "Campaign ID, Ad group ID, Ad group, Ad group status",
                       "Campagne → Gruppi di annunci", "ID campagna, ID gruppo di annunci, Gruppo di annunci, "
                       "Stato del gruppo di annunci"),
    "keywords": _hint("Keywords → Search keywords", "Campaign ID, Ad group ID, Keyword ID, Keyword, Match type, "
                      "Keyword status, Quality Score, Impr., Clicks, Cost, Conversions, Conv. value",
                      "Parole chiave → Parole chiave di ricerca", "ID campagna, ID gruppo di annunci, ID parola "
                      "chiave, Parola chiave, Tipo di corrispondenza, Stato parola chiave, Punteggio di qualità, "
                      "Impr., Clic, Costo, Conversioni, Valore conv."),
    "search_terms": _hint("Keywords → Search terms", "Search term, Match type, Added/Excluded, Campaign ID, Ad group "
                          "ID, Keyword, Impr., Clicks, Cost, Conversions, Conv. value",
                          "Parole chiave → Termini di ricerca", "Termine di ricerca, Tipo di corrispondenza, "
                          "Aggiunto/Escluso, ID campagna, ID gruppo di annunci, Parola chiave, Impr., Clic, Costo, "
                          "Conversioni, Valore conv."),
    "ads": _hint("Ads", "Campaign ID, Ad group ID, Ad ID, Ad type, Ad status, Headline 1-15, Description 1-4, Final "
                 "URL", "Annunci", "ID campagna, ID gruppo di annunci, ID annuncio, Tipo di annuncio, Stato annuncio, "
                 "Titolo 1-15, Descrizione 1-4, URL finale"),
    "negative_keywords": _hint("Keywords → Negative keywords", "Negative keyword, Match type, Level, Campaign ID, Ad "
                               "group ID", "Parole chiave → Parole chiave escluse", "Parola chiave esclusa, Tipo di "
                               "corrispondenza, Livello, ID campagna, ID gruppo di annunci"),
    "conversion_actions": _hint("Goals → Conversions → Summary", "Conversion action ID, Conversion action, "
                                "Category, Status, Count, Action optimization", "Obiettivi → Conversioni → Riepilogo",
                                "ID azione di conversione, Azione di conversione, Categoria, Stato, Conteggio, "
                                "Ottimizzazione azione"),
}

# ----------------------------------------------------------------------------- value vocabularies
_STATUS = {"enabled": "ENABLED", "attiva": "ENABLED", "attivata": "ENABLED", "attivo": "ENABLED",
           "attivato": "ENABLED", "paused": "PAUSED", "in pausa": "PAUSED", "messa in pausa": "PAUSED",
           "messo in pausa": "PAUSED", "removed": "REMOVED", "rimossa": "REMOVED", "rimosso": "REMOVED"}
_MATCH = {"exact": "EXACT", "exact match": "EXACT", "corrispondenza esatta": "EXACT", "phrase": "PHRASE",
          "phrase match": "PHRASE", "corrispondenza a frase": "PHRASE", "broad": "BROAD", "broad match": "BROAD",
          "corrispondenza generica": "BROAD"}
VALUE_SYNONYMS: dict[str, dict[str, str]] = {  # proposals only; every observed value is confirmed in the mapping
    "status": _STATUS,
    "match_type": _MATCH,
    "search_term_match": {**_MATCH, "exact match (close variant)": "NEAR_EXACT",
                          "corrispondenza esatta (variante simile)": "NEAR_EXACT",
                          "phrase match (close variant)": "NEAR_PHRASE",
                          "corrispondenza a frase (variante simile)": "NEAR_PHRASE"},
    "added_excluded": {"added": "ADDED", "aggiunto": "ADDED", "aggiunta": "ADDED", "excluded": "EXCLUDED",
                       "escluso": "EXCLUDED", "esclusa": "EXCLUDED", "added/excluded": "ADDED_EXCLUDED",
                       "aggiunto/escluso": "ADDED_EXCLUDED", "none": "NONE", "nessuno": "NONE"},
    "level": {"campaign": "campaign", "campagna": "campaign", "ad group": "ad_group",
              "gruppo di annunci": "ad_group", "account": "account"},
    "channel_type": {"search": "SEARCH", "rete di ricerca": "SEARCH", "display": "DISPLAY",
                     "rete display": "DISPLAY", "shopping": "SHOPPING", "performance max": "PERFORMANCE_MAX",
                     "video": "VIDEO", "demand gen": "DEMAND_GEN"},
    "bidding": {"manual cpc": "MANUAL_CPC", "cpc manuale": "MANUAL_CPC", "enhanced cpc": "ENHANCED_CPC",
                "cpc ottimizzato": "ENHANCED_CPC", "maximize conversions": "MAXIMIZE_CONVERSIONS",
                "massimizza le conversioni": "MAXIMIZE_CONVERSIONS",
                "maximize conversion value": "MAXIMIZE_CONVERSION_VALUE",
                "massimizza il valore di conversione": "MAXIMIZE_CONVERSION_VALUE", "target cpa": "TARGET_CPA",
                "cpa target": "TARGET_CPA", "target roas": "TARGET_ROAS", "roas target": "TARGET_ROAS",
                "maximize clicks": "TARGET_SPEND", "massimizza i clic": "TARGET_SPEND",
                "target impression share": "TARGET_IMPRESSION_SHARE",
                "quota impressioni target": "TARGET_IMPRESSION_SHARE"},
    "ad_type": {"responsive search ad": "RESPONSIVE_SEARCH_AD",
                "annuncio adattabile della rete di ricerca": "RESPONSIVE_SEARCH_AD",
                "responsive display ad": "RESPONSIVE_DISPLAY_AD", "annuncio display adattabile": "RESPONSIVE_DISPLAY_AD",
                "expanded text ad": "EXPANDED_TEXT_AD", "annuncio di testo espanso": "EXPANDED_TEXT_AD"},
    "qs_component": {"above average": "ABOVE_AVERAGE", "superiore alla media": "ABOVE_AVERAGE",
                     "average": "AVERAGE", "nella media": "AVERAGE", "below average": "BELOW_AVERAGE",
                     "inferiore alla media": "BELOW_AVERAGE"},
    "counting": {"every": "every", "ogni": "every", "one": "one", "una": "one"},
    "boolean_primary": {"primary": "true", "principale": "true", "secondary": "false", "secondaria": "false"},
    "device": {"computers": "DESKTOP", "computer": "DESKTOP", "mobile phones": "MOBILE", "cellulari": "MOBILE",
               "tablets": "TABLET", "tablet": "TABLET", "tv screens": "CONNECTED_TV", "schermi tv": "CONNECTED_TV"},
    "network": {"google search": "SEARCH", "rete di ricerca di google": "SEARCH", "search partners": "SEARCH_PARTNERS",
                "partner di ricerca": "SEARCH_PARTNERS", "display network": "CONTENT", "rete display": "CONTENT"},
    "ad_strength": {"excellent": "EXCELLENT", "eccellente": "EXCELLENT", "good": "GOOD", "buona": "GOOD",
                    "average": "AVERAGE", "media": "AVERAGE", "poor": "POOR", "scarsa": "POOR"},
}
ENUM_ALLOWED: dict[str, frozenset | None] = {  # None = any UPPER_SNAKE token
    "status": frozenset({"ENABLED", "PAUSED", "REMOVED"}),
    "match_type": frozenset({"EXACT", "PHRASE", "BROAD"}),
    "search_term_match": frozenset({"EXACT", "PHRASE", "BROAD", "NEAR_EXACT", "NEAR_PHRASE"}),
    "added_excluded": frozenset({"ADDED", "EXCLUDED", "ADDED_EXCLUDED", "NONE"}),
    "level": frozenset({"account", "campaign", "ad_group"}),
    "qs_component": frozenset({"ABOVE_AVERAGE", "AVERAGE", "BELOW_AVERAGE"}),
    "counting": frozenset({"every", "one"}),
    "boolean_primary": frozenset({"true", "false"}),
    "network": frozenset({"SEARCH", "SEARCH_PARTNERS", "CONTENT", "YOUTUBE", "MIXED"}),
    "channel_type": None, "bidding": None, "ad_type": None, "device": None, "ad_strength": None,
}
_UPPER_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Output columns checked by run(): kind per output column name.
OUTPUT_KINDS = {
    **{c: "int" for c in ("impressions", "clicks", "interactions", "quality_score")},
    **{c: "number" for c in ("conversions", "all_conversions", "conversions_by_conv_time")},
    **{c: "money" for c in ("cost", "conversion_value", "all_conversion_value", "conversion_value_by_conv_time",
                            "daily_budget", "target_cpa", "default_cpc", "cpc_bid", "first_page_cpc",
                            "top_of_page_cpc")},
    **{c: "rate" for c in ("search_impression_share", "search_budget_lost_is", "search_rank_lost_is",
                           "top_impression_rate", "abs_top_impression_rate", "search_top_is", "search_abs_top_is",
                           "target_roas")},
    **{c: "id" for c in ("id", "campaign_id", "ad_group_id", "keyword_id", "ad_id", "matched_keyword_id")},
}
OUTPUT_ENUMS = {
    ("campaigns", "status"): "status", ("ad_groups", "status"): "status", ("keywords", "status"): "status",
    ("ads", "status"): "status", ("keywords", "match_type"): "match_type",
    ("negative_keywords", "match_type"): "match_type", ("search_terms", "match_type"): "search_term_match",
    ("search_terms", "added_excluded"): "added_excluded", ("negative_keywords", "level"): "level",
    ("keywords", "expected_ctr"): "qs_component", ("keywords", "ad_relevance"): "qs_component",
    ("keywords", "landing_page_experience"): "qs_component",
}

SEM_LABEL = {  # English meaning of each candidate semantic; quoted values are Italian UI values
    "campaign_status": "set campaign status: Enabled / Paused / Removed; Italian UI: \"Attivata\" / \"In pausa\" / "
                       "\"Rimossa\"",
    "ad_group_status": "set ad group status: Enabled / Paused / Removed; Italian UI: \"Attivato\" / \"In pausa\" / "
                       "\"Rimosso\"",
    "keyword_status": "set keyword status: Enabled / Paused / Removed; Italian UI: \"Attivata\" / \"In pausa\" / "
                      "\"Rimossa\"",
    "ad_status": "set ad status: Enabled / Paused / Removed; Italian UI: \"Attivato\" / \"In pausa\" / \"Rimosso\"",
    "action_status": "conversion action status: Enabled / Removed; Italian UI: \"Attiva\" / \"Rimossa\"",
    "serving_status": "serving status: Eligible, Limited, Not eligible…; Italian UI: \"Idonea\", \"Limitata\", "
                      "\"Non idonea\"…",
    "tracking_status": "tracking status: Recording conversions, No recent conversions…; Italian UI: \"Registrazione "
                       "conversioni\", \"Nessuna conversione recente\"…",
}

# ----------------------------------------------------------------------------- parsing helpers


def _norm(h: str) -> str:
    return " ".join(str(h or "").replace("\ufeff", "").replace("\u2019", "'").replace("\xa0", " ")
                    .strip().strip('"').casefold().split())


_ITALIAN_NORM = frozenset(_norm(h) for h in ITALIAN_UI_HEADERS)


def _col(h: str) -> str:
    """Quoted header for questions and CLI messages; Italian synonyms get the '(Italian UI header)' label."""
    return f"'{h}'" + (" (Italian UI header)" if _norm(h) in _ITALIAN_NORM else "")


def _col_md(h: str) -> str:
    """Backticked header for preflight.md / intake_report.md; Italian synonyms get the '(Italian UI header)' label."""
    return f"`{h}`" + (" (Italian UI header)" if _norm(h) in _ITALIAN_NORM else "")


def _lookup(report: str) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for sem, kind, names in REPORTS[report]["columns"]:
        for n in names:
            lst = out.setdefault(_norm(n), [])
            if (sem, kind) not in lst:
                lst.append((sem, kind))
    return out


LOOKUPS = {r: _lookup(r) for r in REPORTS}
ALL_HEADERS = frozenset(k for lk in LOOKUPS.values() for k in lk)
_VERIFIED_NORM = frozenset(_norm(h) for h in VERIFIED_HEADERS)
_KIND = {sem: kind for r in REPORTS for sem, kind, _ in REPORTS[r]["columns"]}
ID_HEADERS = frozenset(k for lk in LOOKUPS.values() for k, sems in lk.items() if any(kd == "id" for _, kd in sems))


def _routes(report: str) -> dict[str, list[str]]:
    """semantic → output tables it is written to (empty list = recognized but not routed)."""
    spec = REPORTS[report]
    out: dict[str, list[str]] = {}
    table, cols = spec["entity"]
    for src in cols.values():
        if src.endswith("_*"):
            for sem, _, _ in spec["columns"]:
                if sem.startswith(src[:-1]):
                    out.setdefault(sem, []).append(table)
        else:
            out.setdefault(src, []).append(table)
    if spec["metrics"]:
        mt, keys = spec["metrics"]
        for sem in list(keys) + METRIC_ORDER:
            if mt not in out.setdefault(sem, []):
                out[sem].append(mt)
    elif report == "search_terms":
        for sem in METRIC_ORDER:
            out.setdefault(sem, []).append(table)
    return out


ROUTES = {r: _routes(r) for r in REPORTS}

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"^(\+|00)\d[\d\s().-]{6,}\d$")
_PII_HEADER = re.compile(r"(\be-?mail\b|\bphone\s*(number|no\.?)\b|\btelefono\b|\bcellulare\b|"
                         r"\bnumero di telefono\b|\bcodice fiscale\b)")
_TOTAL = re.compile(r"^(total|totale|totali)\s*(:|-|–|$)", re.IGNORECASE)
_SCI_ID = re.compile(r"^\d+(?:[.,]\d+)?[eE][+-]?\d+$")
_GROUPED_ID = re.compile(r"^\d{1,3}([.,]\d{3})+$")
_IT_NUM = re.compile(r"^(\d+(,\d+)?|[1-9]\d{0,2}(\.\d{3})+(,\d+)?)$")
_EN_NUM = re.compile(r"^(\d+(\.\d+)?|[1-9]\d{0,2}(,\d{3})+(\.\d+)?)$")
_CURRENCY = re.compile(r"^(€|\$|£|[A-Z]{3})\s*|\s*(€|\$|£|[A-Z]{3})$")
MONTHS_IT = {m: i + 1 for i, m in enumerate(("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                                             "agosto", "settembre", "ottobre", "novembre", "dicembre"))}
MONTHS_IT.update({m[:3]: i for m, i in list(MONTHS_IT.items())})
MONTHS_IT["sett"] = 9
MONTHS_EN = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july",
                                             "august", "september", "october", "november", "december"))}
MONTHS_EN.update({m[:3]: i for m, i in list(MONTHS_EN.items())})
MONTHS_EN["sept"] = 9
DATE_FORMATS = ("iso", "dd/mm/yyyy", "mm/dd/yyyy", "it_text", "en_text")


def _missing(v) -> bool:
    return v is None or str(v).strip().lower() in V.MISSING_TOKENS


def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16"), "utf-16"
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8"), "utf-8-sig"
    head = data[:2000]
    if head and head.count(b"\x00") * 4 >= len(head):  # UTF-16 without BOM: NUL high/low bytes of ASCII text
        enc = "utf-16-le" if head[1:2] == b"\x00" else "utf-16-be"
        return data.decode(enc), enc
    return data.decode("utf-8"), "utf-8"


def read_ui_file(name: str, data: bytes) -> dict:
    """Parse one Google Ads UI download: encoding, delimiter, preamble, header, data rows, totals rows.

    Rules:   Header row = the row (among the first 15, per delimiter tab/semicolon/comma) with the most cells
             that are known synonyms (>= 2); otherwise the first row of the dominant width. Rows before it are
             the preamble (title, date range). All-empty rows are skipped. Totals rows (first non-empty cell
             'Total:'/'Totale:'/'Totali' …) are removed and their labels returned, never kept as data.
             Width mismatches and undecodable bytes are returned as 'error', never repaired.
    """
    info = {"file": name, "sha256": hashlib.sha256(data).hexdigest(), "encoding": None, "delimiter": None,
            "header_row": None, "preamble": [], "headers": [], "rows": [], "totals": [], "error": None}
    try:
        text, enc = _decode(data)
    except UnicodeDecodeError:
        info["error"] = "unrecognized encoding (UTF-8 or UTF-16 needed): download the file again from the interface"
        return info
    info["encoding"] = enc
    best = None
    parsed = {}
    for d in ("\t", ";", ","):
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=d))
        except csv.Error as e:
            parsed[d] = None
            info["error"] = f"unreadable CSV: {e}"
            continue
        parsed[d] = rows
        for i, r in enumerate(rows[:15]):
            score = sum(1 for c in r if _norm(c) in ALL_HEADERS)
            if score >= 2 and (best is None or score > best[0]):
                best = (score, d, i)
    if best is None:
        for d in ("\t", ";", ","):
            rows = parsed.get(d) or []
            widths = [len(r) for r in rows if len(r) >= 2 and any(c.strip() for c in r)]
            if not widths:
                continue
            dominant = max(sorted(set(widths)), key=widths.count)
            idx = next(i for i, r in enumerate(rows) if len(r) == dominant)
            if best is None or widths.count(dominant) > best[0]:
                best = (widths.count(dominant), d, idx)
    if best is None:
        info["error"] = info["error"] or "no recognizable table (at least 2 columns needed)"
        return info
    info["error"] = None
    _, d, idx = best
    rows = parsed[d]
    info["delimiter"] = d
    info["header_row"] = idx + 1
    info["preamble"] = [d.join(r).strip() for r in rows[:idx] if any(c.strip() for c in r)]
    headers = [c.replace("\ufeff", "").strip() for c in rows[idx]]
    while headers and headers[-1] == "":
        headers.pop()
    info["headers"] = headers
    if len(set(headers)) != len(headers):
        info["error"] = "intestazioni duplicate: " + ", ".join(sorted({h for h in headers if headers.count(h) > 1}))
        return info
    id_cols = [i for i, h in enumerate(headers) if _norm(h) in ID_HEADERS]
    bad = []
    for n, r in enumerate(rows[idx + 1:], start=idx + 2):
        if not any(c.strip() for c in r):
            continue
        cells = [c.strip() for c in r]
        while len(cells) > len(headers) and cells[-1] == "":
            cells.pop()
        if len(cells) != len(headers):
            bad.append(n)
            continue
        first = next((c for c in cells if c), "")
        if _TOTAL.match(first) and all(_missing(cells[i]) for i in id_cols):
            info["totals"].append(first)
            continue
        info["rows"].append(cells)
    if bad:
        info["error"] = f"rows whose cell count differs from the header: {bad[:10]}"
    return info


def _numeric_core(cell: str) -> str | None:
    s = str(cell).replace("\xa0", " ").strip()
    if _missing(s):
        return None
    s = s.lstrip("<>").strip()
    s = _CURRENCY.sub("", s).strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    s = s.replace(" ", "")
    if s[:1] in "+-":
        s = s[1:]
    return s if s and re.fullmatch(r"[\d.,]+", s) else None


def detect_number_locale(cells) -> dict:
    """Classify numeric cells as IT-only, EN-only or ambiguous evidence.

    Rules:   A cell is evidence only if it is valid in exactly one locale (e.g. '1.234,5' → it; '12.5' → en).
             Integers without separators and '1.234'/'1,234' (valid in both) are not evidence. The locale is
             proposed only when evidence exists for exactly one locale; otherwise it is None (ask).
    """
    ev = {"it": 0, "en": 0, "ambiguous": 0, "invalid": 0, "examples": {"it": [], "en": [], "ambiguous": [],
                                                                         "invalid": []}}
    for c in cells:
        s = _numeric_core(c)
        if s is None:
            if not _missing(c) and re.search(r"\d", str(c)):
                ev["invalid"] += 1
                ev["examples"]["invalid"] = (ev["examples"]["invalid"] + [str(c)])[:3]
            continue
        if "." not in s and "," not in s:
            continue
        it, en = bool(_IT_NUM.match(s)), bool(_EN_NUM.match(s))
        key = "ambiguous" if it and en else "it" if it else "en" if en else "invalid"
        ev[key] += 1
        if len(ev["examples"][key]) < 3:
            ev["examples"][key].append(str(c))
    if ev["it"] and not ev["en"]:
        ev["locale"], ev["status"] = "it", "detected"
    elif ev["en"] and not ev["it"]:
        ev["locale"], ev["status"] = "en", "detected"
    elif ev["en"] and ev["it"]:
        ev["locale"], ev["status"] = None, "conflicting"
    else:
        ev["locale"], ev["status"] = None, "undetermined"
    return ev


def _date_candidates(s: str) -> set[str]:
    s = s.strip()
    out = set()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        out.add("iso")
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 31 and b <= 12:
            out.add("dd/mm/yyyy")
        if a <= 12 and b <= 31:
            out.add("mm/dd/yyyy")
    if re.fullmatch(r"\d{1,2} [A-Za-zà]+\.? \d{4}", s) and s.split()[1].rstrip(".").lower() in MONTHS_IT:
        out.add("it_text")
    if re.fullmatch(r"[A-Za-z]+\.? \d{1,2}, \d{4}", s) and s.split()[0].rstrip(".").lower() in MONTHS_EN:
        out.add("en_text")
    return out


def _parse_date(s: str, fmt: str) -> date | None:
    s = s.strip()
    try:
        if fmt == "iso" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
        if m and fmt == "dd/mm/yyyy":
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if m and fmt == "mm/dd/yyyy":
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        p = s.replace(",", "").split()
        if fmt == "it_text" and len(p) == 3 and p[1].rstrip(".").lower() in MONTHS_IT:
            return date(int(p[2]), MONTHS_IT[p[1].rstrip(".").lower()], int(p[0]))
        if fmt == "en_text" and len(p) == 3 and p[0].rstrip(".").lower() in MONTHS_EN:
            return date(int(p[2]), MONTHS_EN[p[0].rstrip(".").lower()], int(p[1]))
    except ValueError:
        return None
    return None


def _preamble_period(lines: list[str]) -> dict | None:
    """Unambiguous 'start - end' date range from title lines, else None."""
    for line in lines:
        parts = re.split(r"\s+[-–]\s+", line.strip().strip('"'))
        if len(parts) != 2:
            continue
        got = []
        for p in parts:
            fmts = _date_candidates(p.strip())
            dates = {_parse_date(p, f) for f in fmts} - {None}
            if len(dates) != 1:
                break
            got.append(dates.pop())
        if len(got) == 2 and got[0] <= got[1]:
            return {"start": got[0].isoformat(), "end": got[1].isoformat(), "line": line}
    return None


def _pii_column(header: str, cells: list[str]) -> bool:
    if _PII_HEADER.search(_norm(header)):
        return True
    vals = [c for c in cells if not _missing(c)]
    if not vals:
        return False
    hits = sum(1 for c in vals if _EMAIL.search(c) or _PHONE.match(c.strip()))
    return hits * 2 >= len(vals)


def _detect_report(headers: list[str]) -> tuple[str | None, list[str]]:
    hs = {_norm(h) for h in headers}
    present = [r for r in DETECT_ORDER if hs & {_norm(m) for m in MARKERS[r]}]
    exclusive = [r for r in present if r in _EXCLUSIVE]
    if len(exclusive) > 1:
        return None, exclusive
    if exclusive:
        return exclusive[0], present
    if "ads" in present and "keywords" in present:
        return None, present
    if not present:
        return None, []
    top = present[0]
    recognized = sum(1 for h in hs if h in LOOKUPS[top])
    return (top if recognized >= 2 else None), present


# ----------------------------------------------------------------------------- preflight


MAX_ARCHIVE_BYTES = 50 * 1024 * 1024      # uploaded ZIP size
MAX_FILE_BYTES = 50 * 1024 * 1024         # one CSV/TSV (plain or unpacked)
MAX_TOTAL_BYTES = 200 * 1024 * 1024       # all raw bytes read in one intake
MAX_ENTRIES = 500                         # members in one ZIP
MAX_RATIO = 100                           # uncompressed/compressed per ZIP member


class RawLimitError(ValueError):
    """Raw input refused for safety (size, entry count, compression ratio, link or special file)."""


def _raw_files(raw: Path) -> list[tuple[str, bytes]]:
    """(display name, bytes) for every CSV/TSV/TXT in a folder or ZIP, sorted.

    Rules:   Refuses (RawLimitError) symlinks, special files, nested ZIPs inside ZIPs, ZIPs over MAX_ARCHIVE_BYTES or
             MAX_ENTRIES, any member/file over MAX_FILE_BYTES, compression ratio over MAX_RATIO, and total raw bytes
             over MAX_TOTAL_BYTES. Sizes are checked from headers before reading and enforced again while
             streaming, so a lying ZIP header cannot bypass them. Folder walks never follow symlinks.
    """
    out: list[tuple[str, bytes]] = []
    total = [0]

    def account(n: int, label: str) -> None:
        total[0] += n
        if total[0] > MAX_TOTAL_BYTES:
            raise RawLimitError(f"{label}: total data over {MAX_TOTAL_BYTES // 2**20} MB")

    def read_plain(p: Path, label: str) -> bytes:
        if p.is_symlink() or not p.is_file():
            raise RawLimitError(f"{label}: symbolic link or special file not accepted")
        size = p.stat().st_size
        if size > MAX_FILE_BYTES:
            raise RawLimitError(f"{label}: {size} bytes over the {MAX_FILE_BYTES // 2**20} MB limit")
        account(size, label)
        return p.read_bytes()

    def from_zip(label: str, p: Path) -> None:
        if p.is_symlink() or not p.is_file():
            raise RawLimitError(f"{label}: symbolic link or special file not accepted")
        if p.stat().st_size > MAX_ARCHIVE_BYTES:
            raise RawLimitError(f"{label}: archive over {MAX_ARCHIVE_BYTES // 2**20} MB")
        try:
            z = zipfile.ZipFile(p)
        except zipfile.BadZipFile as e:
            raise RawLimitError(f"{label}: invalid ZIP ({e})") from e
        with z:
            infos = z.infolist()
            if len(infos) > MAX_ENTRIES:
                raise RawLimitError(f"{label}: {len(infos)} entries, over the {MAX_ENTRIES} limit")
            for info in sorted(infos, key=lambda i: i.filename):
                parts = PurePosixPath(info.filename).parts
                if info.is_dir() or any(x.startswith(".") or x == "__MACOSX" for x in parts):
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode and mode != 0o100000:
                    raise RawLimitError(f"{label}:{info.filename}: symbolic link or special file not accepted")
                suffix = PurePosixPath(info.filename).suffix.lower()
                if suffix == ".zip":
                    raise RawLimitError(f"{label}:{info.filename}: nested ZIPs not accepted")
                if suffix not in RAW_SUFFIXES:
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    raise RawLimitError(f"{label}:{info.filename}: over {MAX_FILE_BYTES // 2**20} MB")
                if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                    raise RawLimitError(f"{label}:{info.filename}: suspicious compression ratio")
                buf = bytearray()
                with z.open(info) as fh:
                    while chunk := fh.read(1 << 20):
                        buf += chunk
                        if len(buf) > MAX_FILE_BYTES:
                            raise RawLimitError(f"{label}:{info.filename}: over {MAX_FILE_BYTES // 2**20} MB")
                account(len(buf), f"{label}:{info.filename}")
                out.append((f"{label}:{info.filename}", bytes(buf)))

    if raw.is_symlink():
        raise RawLimitError(f"{raw.name}: symbolic link not accepted")
    if raw.is_file():
        if raw.suffix.lower() == ".zip":
            from_zip(raw.name, raw)
        elif raw.suffix.lower() in RAW_SUFFIXES:
            out.append((raw.name, read_plain(raw, raw.name)))
        return out
    stack = [raw]
    paths: list[Path] = []
    while stack:
        d = stack.pop()
        for p in d.iterdir():
            if p.is_symlink():
                raise RawLimitError(f"{p.relative_to(raw).as_posix()}: symbolic link not accepted")
            if p.is_dir():
                stack.append(p)
            else:
                paths.append(p)
    for p in sorted(paths):
        rel = p.relative_to(raw)
        if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts):
            continue
        if p.suffix.lower() == ".zip":
            from_zip(rel.as_posix(), p)
        elif p.suffix.lower() in RAW_SUFFIXES:
            out.append((rel.as_posix(), read_plain(p, rel.as_posix())))
    return out


def _column_cells(info: dict, i: int) -> list[str]:
    return [r[i] for r in info["rows"]]


def _propose_columns(info: dict, report: str | None) -> list[dict]:
    cols = []
    for i, h in enumerate(info["headers"]):
        cells = _column_cells(info, i)
        entry = {"header": h, "semantic": None, "action": None, "status": "unrecognized"}
        n = _norm(h)
        if _pii_column(h, cells):
            entry.update(status="pii", action="drop", reason="looks like personal data: excluded")
        elif report is None:
            cands = sorted({s for r in REPORTS for s, _ in LOOKUPS[r].get(n, [])})
            entry.update(status="table_undecided", candidates=cands)
        else:
            sems = LOOKUPS[report].get(n, [])
            if len(sems) > 1:
                entry.update(status="ambiguous", candidates=[s for s, _ in sems])
            elif sems:
                sem = sems[0][0]
                entry["semantic"] = sem
                entry["verified_synonym"] = n in _VERIFIED_NORM
                if ROUTES[report].get(sem):
                    entry.update(status="suggested", action="map")
                elif sem in DERIVED_SEMS:
                    entry.update(status="derived", action="drop",
                                 reason="derived metric: recipes recompute it from the totals")
                else:
                    entry.update(status="unused", action="drop", reason="recognized but not used by this table")
        cols.append(entry)
    mapped: dict[str, list[dict]] = {}
    for c in cols:
        if c["action"] == "map":
            mapped.setdefault(c["semantic"], []).append(c)
    for sem, lst in mapped.items():
        if len(lst) > 1:
            for c in lst:
                c.update(status="conflict", action=None, candidates=[sem],
                         reason=f"several columns propose the same field '{sem}'")
    return cols


def _value_maps(info: dict, cols: list[dict]) -> dict:
    """Distinct raw values → proposed canonical value (None = ask) for mapped or undecided enum columns."""
    maps = {}
    for i, c in enumerate(cols):
        if c["action"] == "map":
            sems = [c["semantic"]]
        elif c["status"] in ("ambiguous", "conflict"):
            sems = c.get("candidates") or []
        else:
            continue
        vocab = next((_KIND[s].split(":", 1)[1] for s in sems if _KIND.get(s, "").startswith("enum:")), None)
        if vocab is None:
            continue
        values = sorted({v for v in _column_cells(info, i) if not _missing(v)})
        maps[c["header"]] = {v: VALUE_SYNONYMS.get(vocab, {}).get(_norm(v)) for v in values[:MAX_VALUES]}
    return maps


def _kind_cells(info: dict, cols: list[dict], kinds: tuple[str, ...]) -> list[str]:
    cells = []
    for i, c in enumerate(cols):
        sem = c["semantic"] or next(iter(c.get("candidates") or []), None)
        if sem and _KIND.get(sem, "text") in kinds:
            cells += _column_cells(info, i)
    return cells


def _output_columns(report: str, sems: set[str]) -> dict[str, list[str]]:
    spec = REPORTS[report]
    out = {}
    table, cols = spec["entity"]
    out[table] = [c for c, s in cols.items() if (s in sems or (s.endswith("_*") and any(x.startswith(s[:-1])
                                                                                        for x in sems)))]
    if report == "search_terms":
        out[table] += [s for s in METRIC_ORDER if s in sems]
    if spec["metrics"]:
        mt, keys = spec["metrics"]
        out[mt] = [k for k in keys if k in sems] + [s for s in METRIC_ORDER if s in sems]
    return out


def _file_proposal(info: dict, forced: str | None) -> dict:
    detected, cands = _detect_report(info["headers"])
    report = forced or detected
    cols = _propose_columns(info, report)
    numeric_cells = [v for v in _kind_cells(info, cols, ("int", "number", "money", "rate")) if not _missing(v)]
    num = detect_number_locale(numeric_cells)
    if not numeric_cells:
        num["locale"], num["status"] = "none", "not applicable (no numeric column)"
    rate_cells = [v for v in _kind_cells(info, cols, ("rate",)) if not _missing(v)]
    if not rate_cells:
        pct = "none"
    elif all(v.strip().endswith("%") for v in rate_cells):
        pct = "percent_sign"
    else:
        pct = None
    date_cells = [v for v in _kind_cells(info, cols, ("date",)) if not _missing(v)]
    if not date_cells:
        dfmt = "none"
    else:
        common = set(DATE_FORMATS)
        for v in date_cells:
            common &= _date_candidates(v)
        dfmt = common.pop() if len(common) == 1 else None
    customers = sorted({info["rows"][r][i] for i, c in enumerate(cols) if c["semantic"] == "customer_id"
                        for r in range(len(info["rows"])) if not _missing(info["rows"][r][i])})
    currencies = sorted({r[i] for i, h in enumerate(info["headers"]) if _norm(h) in (_norm("Currency code"),
                                                                                     _norm("Codice valuta"))
                         for r in info["rows"] if not _missing(r[i])})
    names = sorted({r[i] for i, h in enumerate(info["headers"]) if _norm(h) in (_norm("Account name"),
                                                                                _norm("Nome account"))
                    for r in info["rows"] if not _missing(r[i])})
    return {
        "file": info["file"], "sha256": info["sha256"], "encoding": info["encoding"],
        "delimiter": {"\t": "tab", ";": "semicolon", ",": "comma"}.get(info["delimiter"]),
        "header_row": info["header_row"], "preamble": info["preamble"],
        "detected_period": _preamble_period(info["preamble"]),
        "table": report, "table_detected": detected, "table_candidates": cands,
        "number_locale": num["locale"], "number_locale_evidence": num,
        "percent_format": pct, "date_format": dfmt,
        "filters": {"applied": None, "description": ""},
        "rows": {"data": len(info["rows"]), "totals_removed": len(info["totals"]), "totals_labels": info["totals"]},
        "columns": cols, "value_maps": _value_maps(info, cols),
        "seen": {"customer_ids": customers, "currencies": currencies, "account_names": names},
    }


def _base_gaps(files: list[dict]) -> dict[str, list[str] | None]:
    """Output table → missing required columns (None = no file supplies the table)."""
    have: dict[str, set[str]] = {}
    for f in files:
        if f["table"] not in REPORTS:
            continue
        sems = {c["semantic"] for c in f["columns"] if c["action"] == "map"}
        spec = REPORTS[f["table"]]
        for table, cols in _output_columns(f["table"], sems).items():
            if table == spec["entity"][0] and spec["metrics"] and sems & SEGMENT_SEMS:
                continue  # apply skips snapshot tables from segmented files
            have.setdefault(table, set()).update(cols)
    return {t: (sorted(set(req) - have[t]) if t in have else None) for t, req in BASE_REQUIRED.items()}


def _questions(files: list[dict], answers: dict) -> list[dict]:
    q = []

    def add(qid, text, path):
        q.append({"id": qid, "question": text, "answer_in": path})

    seen_c = sorted({c for f in files for c in f["seen"]["customer_ids"]})
    if len(seen_c) == 1:
        add("customer_id", f"Confirm the account's customer ID: {seen_c[0]} (read from the files).",
            "answers.customer_id")
    elif len(seen_c) > 1:
        add("customer_id", f"The files contain more than one account ({', '.join(seen_c)}): this intake handles "
                           "one account at a time. Which account are we analyzing? Download the reports of one "
                           "account only.",
            "answers.customer_id")
    else:
        add("customer_id", "What is the Google Ads account's customer ID? (format 123-456-7890, top right of the "
                           "interface)", "answers.customer_id")
    cur = sorted({c for f in files for c in f["seen"]["currencies"]})
    if len(cur) == 1:
        add("currency_code", f"Confirm the account currency: {cur[0]} (read from the currency column).",
            "answers.currency_code")
    else:
        add("currency_code", "What currency is the account in? 3-letter code, e.g. EUR (Admin → Account settings).",
            "answers.currency_code")
    add("time_zone", "What is the account time zone? E.g. Europe/Rome (Admin → Account settings).",
        "answers.time_zone")
    periods = {(f["detected_period"]["start"], f["detected_period"]["end"]) for f in files if f["detected_period"]}
    if len(periods) == 1:
        s, e = next(iter(periods))
        partial = any(not f["detected_period"] for f in files if f["table"] != "skip")
        add("period", f"Confirm the report period: from {s} to {e} (read from the title lines of "
                      f"{'some files; the others do not show it' if partial else 'the files'}).",
            "answers.date_range_start / answers.date_range_end")
    elif len(periods) > 1:
        add("period", "The files cover different periods (" + "; ".join(f"{s} → {e}" for s, e in sorted(periods)) +
            "). Download them all again with the same date range, then re-run the preflight.",
            "answers.date_range_start / answers.date_range_end")
    else:
        add("period", "Which date range did you select when you downloaded the reports? (start and end date, "
                      "e.g. 2026-08-01 → 2026-08-31)", "answers.date_range_start / answers.date_range_end")
    add("snapshot_date", "On what date did you download the files? (e.g. 2026-09-06; it is used as the snapshot date)",
        "answers.snapshot_date")
    add("conversion_lag_days", "How many days usually pass between the click and the conversion? If you don't know, "
                               "answer 'I don't know': it is recorded as unknown, not as zero.",
        "answers.conversion_lag_days")
    if answers.get("conversion_date_basis") == "interaction_date":
        add("conversion_date_basis", "Confirm: conversions come from the standard 'Conversions' column (Italian UI "
                                     "header 'Conversioni'), attributed to the click date, not from the "
                                     "'(by conv. time)' columns.",
            "answers.conversion_date_basis")
    else:
        add("conversion_date_basis", "Are the conversions in the reports by click date ('Conversions' column; Italian "
                                     "UI header 'Conversioni') or by conversion date ('Conv. (by conv. time)'; "
                                     "Italian UI header 'Conv. (per ora conv.)')? If you are not sure: "
                                     "'I don't know'.",
            "answers.conversion_date_basis")
    add("money_unit", "Confirm: amounts (Cost, Budget, Conv. value) are in currency units, not micros. Reports "
                      "downloaded from the interface are in currency units.", "answers.money_unit")
    for f in files:
        for c in f.get("columns") or []:
            if c["semantic"] == "daily_budget" and c["action"] == "map":
                add(f"{f['file']}:budget", f"'{f['file']}', column {_col(c['header'])}: confirm it is the DAILY "
                                           "budget (if some campaigns have a total budget, drop the column).",
                    f"files[{files.index(f)}].columns[{c['header']}]")
    for n, f in enumerate(files):
        p = f"files[{n}]"
        name = f["file"]
        if f.get("error"):
            add(f"{name}:error", f"The file '{name}' cannot be read ({f['error']}). Download it again or exclude it.",
                f"{p}.table = \"skip\"")
            continue
        if f["table"] is None:
            add(f"{name}:table", f"Which report is '{name}'? Campaigns, ad groups, keywords, search terms, ads, "
                                 "negative keywords, conversion actions, or 'skip'. (Then re-run the preflight with "
                                 "--table.)", f"{p}.table")
        add(f"{name}:filters", f"'{name}': did you apply filters (e.g. 'All but removed', enabled only, one campaign "
                               "type), segments or row/top-N limits? If yes, describe them.", f"{p}.filters")
        if f["number_locale"] is None:
            ev = f["number_locale_evidence"]
            ex = ", ".join(ev["examples"]["ambiguous"] + ev["examples"]["it"] + ev["examples"]["en"]) or "integers only"
            add(f"{name}:numbers", f"'{name}': number format {ev['status']} (examples: {ex}). Was the interface in "
                                   "Italian (1.234,56) or in English (1,234.56)?", f"{p}.number_locale")
        if f["percent_format"] is None:
            add(f"{name}:percent", f"'{name}': some percentages have no % sign. Are they percentages "
                                   "(12.5 = 12.5%) or fractions (0.125)?", f"{p}.percent_format")
        if f["date_format"] is None:
            add(f"{name}:date", f"'{name}': the dates are ambiguous. Is the format day/month/year or month/day/year?",
                f"{p}.date_format")
        for c in f["columns"]:
            if c["action"] is not None:
                continue
            if c["status"] == "ambiguous":
                opts = " or ".join(f"'{s}' ({SEM_LABEL.get(s, s)})" for s in c["candidates"])
                add(f"{name}:{c['header']}", f"'{name}', column {_col(c['header'])}: is it {opts}? Or should it be "
                                             "dropped?", f"{p}.columns[{c['header']}]")
            elif c["status"] == "conflict":
                add(f"{name}:{c['header']}", f"'{name}', column {_col(c['header'])}: {c['reason']}. Which one should "
                                             "be kept?", f"{p}.columns[{c['header']}]")
            elif c["status"] in ("unrecognized", "table_undecided"):
                add(f"{name}:{c['header']}", f"'{name}', column {_col(c['header'])} is not recognized: which field "
                                             "does it match, or should it be dropped?", f"{p}.columns[{c['header']}]")
        mapped = {c["header"] for c in f["columns"] if c["action"] == "map"}
        for h, vm in f["value_maps"].items():
            for raw, canon in vm.items():
                if canon is None and h in mapped:
                    add(f"{name}:{h}={raw}", f"'{name}', column {_col(h)}: which standard value does '{raw}' "
                                             "match? (or empty = unknown)", f"{p}.value_maps[{h}][{raw}]")
    return q


def preflight(raw: Path, out: Path, tables: dict | None = None) -> int:
    """Scan raw UI downloads and write proposed_mapping.json + preflight.md (English checklist). Nothing is final.

    Rules:   Writes only proposed_mapping.json and preflight.md inside out; returns 2 when raw has no readable
             CSV/TSV. Proposals never fill answers the files do not evidence: currency/customer/period are
             proposed only from explicit columns or unambiguous title lines; "confirmed" is always false.
    """
    tables = tables or {}
    if not raw.exists():
        print(f"ERROR: folder/file not found: {raw}", file=sys.stderr)
        return 2
    files = []
    try:
        raw_items = _raw_files(raw)
    except RawLimitError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    for name, data in raw_items:
        info = read_ui_file(name, data)
        if info["error"] and not info["headers"]:
            files.append({"file": name, "sha256": info["sha256"], "error": info["error"], "table": None,
                          "columns": [], "value_maps": {}, "detected_period": None,
                          "seen": {"customer_ids": [], "currencies": [], "account_names": []}})
            continue
        prop = _file_proposal(info, tables.get(name))
        if info["error"]:
            prop["error"] = info["error"]
        files.append(prop)
    if not files:
        print(f"ERROR: no CSV/TSV in {raw}", file=sys.stderr)
        return 2
    seen_c = sorted({c for f in files for c in f["seen"]["customer_ids"]})
    cur = sorted({c for f in files for c in f["seen"]["currencies"]})
    names = sorted({c for f in files for c in f["seen"]["account_names"]})
    periods = {(f["detected_period"]["start"], f["detected_period"]["end"]) for f in files if f["detected_period"]}
    conv_std = any(c["semantic"] == "conversions" and c["action"] == "map" for f in files for c in f["columns"])
    answers = {
        "customer_id": seen_c[0] if len(seen_c) == 1 else None,
        "account_name": names[0] if len(names) == 1 else None,
        "currency_code": cur[0] if len(cur) == 1 else None,
        "time_zone": None,
        "date_range_start": next(iter(periods))[0] if len(periods) == 1 else None,
        "date_range_end": next(iter(periods))[1] if len(periods) == 1 else None,
        "snapshot_date": None,
        "conversion_lag_days": None,
        "conversion_date_basis": "interaction_date" if conv_std else None,
        "money_unit": "currency",
    }
    mapping = {"schema": MAPPING_SCHEMA, "skill": SKILL, "version": VERSION, "confirmed": False,
               "answers": answers, "files": files, "base_gaps": _base_gaps(files),
               "questions": _questions(files, answers)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "proposed_mapping.json").write_text(json.dumps(mapping, indent=1, ensure_ascii=False, sort_keys=False)
                                               + "\n", encoding="utf-8")
    (out / "preflight.md").write_text(_preflight_md(mapping), encoding="utf-8")
    print(f"preflight: {len(files)} file(s), {len(mapping['questions'])} questions → {out / 'preflight.md'}")
    return 0


def _preflight_md(m: dict) -> str:
    L = ["# Google Ads export preflight — TO CONFIRM", "",
         "Nothing is final: answer the questions at the end; the mapping is applied only after confirmation.",
         "Column synonyms are proposals: those marked *(unverified)* do not appear in the Google Help pages "
         "consulted. Headers marked (Italian UI header) come from the Italian-language interface.", "",
         "## Files analyzed", "",
         "| File | Detected table | Data rows | Totals rows removed | Encoding | Separator | Numbers | "
         "Percentages | Period in title lines |", "|---|---|---|---|---|---|---|---|---|"]
    for f in m["files"]:
        if f.get("error") and not f.get("columns"):
            L.append(f"| {f['file']} | ERROR: {f['error']} | | | | | | | |")
            continue
        per = f["detected_period"]
        L.append(f"| {f['file']} | {f['table'] or 'to choose (' + ', '.join(f['table_candidates']) + ')'} | "
                 f"{f['rows']['data']} | {f['rows']['totals_removed']} | {f['encoding']} | {f['delimiter']} | "
                 f"{f['number_locale'] or f['number_locale_evidence']['status']} | "
                 f"{f['percent_format'] or 'to clarify'} | "
                 f"{(per['start'] + ' → ' + per['end']) if per else 'none'} |")
    for f in m["files"]:
        if not f.get("columns"):
            continue
        L += ["", f"## {f['file']}", ""]
        if f.get("error"):
            L.append(f"- ERROR: {f['error']}")
        groups = {"suggested": [], "ambiguous": [], "conflict": [], "unrecognized": [], "table_undecided": [],
                  "pii": [], "derived": [], "unused": []}
        for c in f["columns"]:
            groups.setdefault(c["status"], []).append(c)
        if groups["suggested"]:
            L.append("- Mapped (proposed): " + "; ".join(
                f"{_col_md(c['header'])} → `{c['semantic']}`"
                + ("" if c.get("verified_synonym") else " *(unverified)*")
                for c in groups["suggested"]))
        for key, label in (("ambiguous", "Ambiguous (to decide)"), ("conflict", "Conflicting (to decide)")):
            if groups[key]:
                L.append(f"- {label}: " + "; ".join(f"{_col_md(c['header'])} → {' / '.join(c['candidates'])}"
                                                    for c in groups[key]))
        unk = groups["unrecognized"] + groups["table_undecided"]
        if unk:
            L.append("- Not recognized (map or drop explicitly): " + ", ".join(_col_md(c["header"]) for c in unk))
        if groups["pii"]:
            L.append("- Excluded for privacy (personal data): "
                     + ", ".join(_col_md(c["header"]) for c in groups["pii"]))
        if groups["derived"] or groups["unused"]:
            L.append("- Proposed to drop: " + ", ".join(f"{_col_md(c['header'])} ({c['reason']})"
                                                        for c in groups["derived"] + groups["unused"]))
        for h, vm in f["value_maps"].items():
            L.append(f"- Values of {_col_md(h)}: " + ", ".join(f"\"{k}\" → {v or '?'}" for k, v in vm.items()))
        if f["rows"]["totals_labels"]:
            L.append("- Totals rows removed: " + ", ".join(f"\"{t}\"" for t in f["rows"]["totals_labels"]))
    L += ["", "## Tables and columns missing for the base audit", ""]
    gaps = False
    for t, miss in m["base_gaps"].items():
        if miss is None:
            gaps = True
            L.append(f"- `{t}`: no file. Download: {DOWNLOAD_HINTS[REPORT_FOR_TABLE[t]]}.")
        elif miss:
            gaps = True
            L.append(f"- `{t}`: missing {', '.join(f'`{c}`' for c in miss)} (add the columns and download again, or "
                     "resolve the ambiguous columns).")
    if not gaps:
        L.append("- None: every base table has the required columns (after confirmation).")
    L += ["", "If the interface table does not offer the ID columns, use Reports → Report editor and add the ID "
              "dimensions (Italian UI: Rapporti → Editor report; path unverified).", "", "## Questions for you", ""]
    L += [f"{i}. {q['question']}" for i, q in enumerate(m["questions"], 1)]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- apply


class IntakeError(ValueError):
    """Mapping/raw problem that makes apply refuse. Rules: message is English and names file/column/value."""


def _dec_str(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _convert(cell: str, kind: str, locale: str, pct: str) -> str:
    """Normalize one numeric cell to plain dot-decimal text; raises IntakeError on anything not provably valid."""
    s = cell.replace("\xa0", " ").strip()
    if _missing(s):
        return ""
    bound = ""
    if s[:1] in "<>":
        if kind != "rate":
            raise IntakeError(f"bounded value '{cell}' in a non-percentage column")
        bound, s = s[0], s[1:].strip()
    if kind == "money":
        s = _CURRENCY.sub("", s).strip()
    has_pct = s.endswith("%")
    if kind == "rate":
        if pct == "percent_sign" and not has_pct:
            raise IntakeError(f"'{cell}' has no % but the confirmed format is percent_sign")
        if pct in ("percent_number", "fraction") and has_pct:
            raise IntakeError(f"'{cell}' has % but the confirmed format is {pct}")
    elif has_pct:
        raise IntakeError(f"'{cell}' has the % sign in a non-percentage column")
    if has_pct:
        s = s[:-1].strip()
    s = s.replace(" ", "")
    sign = ""
    if s[:1] in "+-":
        sign, s = ("-" if s[0] == "-" else ""), s[1:]
    rx = _IT_NUM if locale == "it" else _EN_NUM
    if not rx.match(s):
        raise IntakeError(f"'{cell}' is not a valid number in the {locale.upper()} format")
    plain = s.replace(".", "").replace(",", ".") if locale == "it" else s.replace(",", "")
    try:
        d = Decimal(sign + plain)
    except InvalidOperation as e:
        raise IntakeError(f"'{cell}' is not a number") from e
    if kind == "rate" and pct in ("percent_sign", "percent_number"):
        d = d / Decimal(100)
    if kind == "int" and d != d.to_integral_value():
        raise IntakeError(f"'{cell}' should be an integer")
    return bound + _dec_str(d)


def _strip_wrapper(text: str, match: str) -> tuple[str, bool]:
    """Remove UI match-type punctuation only when it agrees with the explicit match type; (text, conflict)."""
    t = text.strip()
    wrapped_exact = t.startswith("[") and t.endswith("]")
    wrapped_phrase = len(t) > 1 and t.startswith('"') and t.endswith('"')
    if match == "EXACT" and wrapped_exact or match == "PHRASE" and wrapped_phrase:
        return t[1:-1].strip(), False
    if wrapped_exact or wrapped_phrase or (match != "BROAD" and t.startswith("+")):
        return t, True
    return t, False


def _require(cond: bool, problems: list[str], msg: str) -> bool:
    if not cond:
        problems.append(msg)
    return cond


def _valid_answers(a: dict, problems: list[str]) -> None:
    need = ("customer_id", "currency_code", "time_zone", "date_range_start", "date_range_end", "snapshot_date",
            "conversion_lag_days", "conversion_date_basis", "money_unit")
    for k in need:
        _require(k in a and a[k] not in (None, ""), problems, f"missing answer: answers.{k}")
    if problems:
        return
    _require(bool(re.fullmatch(r"\d{3}-?\d{3}-?\d{4}", str(a["customer_id"]))), problems,
             "answers.customer_id must use the format 123-456-7890")
    _require(bool(re.fullmatch(r"[A-Z]{3}", str(a["currency_code"]))), problems,
             "answers.currency_code must be a 3-letter uppercase code (e.g. EUR)")
    _require(bool(re.fullmatch(r"UTC|[A-Za-z_]+(/[A-Za-z0-9_+\-]+)+", str(a["time_zone"]))), problems,
             "answers.time_zone must be an IANA time zone (e.g. Europe/Rome)")
    ds = {k: V.parse_date(a[k]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(a[k])) else None
          for k in ("date_range_start", "date_range_end", "snapshot_date")}
    for k, v in ds.items():
        _require(v is not None, problems, f"answers.{k} must be a YYYY-MM-DD date")
    if all(ds.values()):
        _require(ds["date_range_start"] <= ds["date_range_end"] <= ds["snapshot_date"], problems,
                 "inconsistent dates: start <= end <= download date is required")
    lag = a["conversion_lag_days"]
    _require(lag == "unknown" or (isinstance(lag, int) and not isinstance(lag, bool) and 0 <= lag <= 365), problems,
             "answers.conversion_lag_days must be an integer 0–365 or \"unknown\"")
    _require(a["conversion_date_basis"] in ("interaction_date", "conversion_date", "unknown"), problems,
             "answers.conversion_date_basis must be interaction_date, conversion_date or unknown")
    _require(a["money_unit"] in ("currency", "micros"), problems, "answers.money_unit must be currency or micros")
    if "auto_tagging" in a and a["auto_tagging"] is not None:
        _require(a["auto_tagging"] in ("true", "false", "unknown"), problems,
                 "answers.auto_tagging must be true, false or unknown")


def _check_file_entry(f: dict, info: dict, problems: list[str]) -> str | None:
    """Validate one confirmed file entry against the raw file; return the report type or None (skip/invalid)."""
    name = f.get("file")
    table = f.get("table")
    if table == "skip":
        return None
    if not _require(table in REPORTS, problems, f"{name}: 'table' must be one of {sorted(REPORTS)} or \"skip\""):
        return None
    if info.get("error"):
        problems.append(f"{name}: {info['error']}")
        return None
    _require(f.get("sha256") == info["sha256"], problems,
             f"{name}: the file changed after the preflight (different sha256): re-run the preflight")
    headers = [c.get("header") for c in f.get("columns") or []]
    _require(headers == info["headers"], problems,
             f"{name}: the mapping columns do not match the file columns: re-run the preflight")
    filt = f.get("filters") or {}
    if _require(isinstance(filt.get("applied"), bool), problems,
                f"{name}: filters.applied must be true or false (the colleague's answer)"):
        _require(not filt["applied"] or bool(str(filt.get("description") or "").strip()), problems,
                 f"{name}: filters.description is required when filters.applied is true")
    routes = ROUTES[table]
    kinds_present = set()
    seen_sem: dict[str, str] = {}
    for i, c in enumerate(f.get("columns") or []):
        h, action, sem = c.get("header"), c.get("action"), c.get("semantic")
        cells = _column_cells(info, i) if i < len(info["headers"]) else []
        if _pii_column(h or "", cells):
            _require(action == "drop", problems, f"{name}: column {_col(h)} contains personal data and cannot be "
                                                 "mapped")
            continue
        if action == "drop":
            continue
        if not _require(action == "map", problems, f"{name}: column {_col(h)} unresolved (action must be map or drop)"):
            continue
        if not _require(bool(routes.get(sem)), problems,
                        f"{name}: column {_col(h)} → '{sem}' is not a valid field for table {table}"):
            continue
        if not _require(sem not in seen_sem, problems,
                        f"{name}: {_col(h)} and {_col(seen_sem.get(sem))} both point to '{sem}'"):
            continue
        seen_sem[sem] = h
        kind = _KIND.get(sem, "text")
        kinds_present.add(kind.split(":")[0])
        if kind.startswith("enum:"):
            vocab = kind.split(":", 1)[1]
            vm = (f.get("value_maps") or {}).get(h) or {}
            allowed = ENUM_ALLOWED.get(vocab)
            unmapped = []
            for raw_v in sorted({v for v in cells if not _missing(v)}):
                canon = vm.get(raw_v)
                if canon is None:
                    unmapped.append(raw_v)
                elif canon != "":
                    ok = canon in allowed if allowed is not None else bool(_UPPER_TOKEN.match(str(canon)))
                    _require(ok, problems, f"{name}: column {_col(h)}, '{raw_v}' → '{canon}' is not an allowed value")
            _require(not unmapped, problems, f"{name}: column {_col(h)}, {len(unmapped)} value(s) without a "
                                             f"confirmed match in value_maps: {unmapped[:10]}")
    numeric = any(_KIND.get(c.get("semantic"), "text") in ("int", "number", "money", "rate")
                  and c.get("action") == "map" and any(not _missing(v) for v in _column_cells(info, i))
                  for i, c in enumerate(f.get("columns") or []) if i < len(info["headers"]))
    _require(f.get("number_locale") in (("it", "en") if numeric else ("it", "en", "none")), problems,
             f"{name}: number_locale must be \"it\" or \"en\"")
    pct = f.get("percent_format")
    if "rate" in kinds_present:
        _require(pct in ("percent_sign", "percent_number", "fraction"), problems,
                 f"{name}: percent_format must be percent_sign, percent_number or fraction")
    else:
        _require(pct in ("percent_sign", "percent_number", "fraction", "none"), problems,
                 f"{name}: percent_format missing")
    dfmt = f.get("date_format")
    if "date" in kinds_present:
        _require(dfmt in DATE_FORMATS, problems, f"{name}: date_format must be one of {list(DATE_FORMATS)}")
    else:
        _require(dfmt in DATE_FORMATS + ("none",), problems, f"{name}: date_format missing")
    return table


def _normalize_rows(f: dict, info: dict, report: str, answers: dict, problems: list[str], stats: dict) -> list[dict]:
    """Semantic rows for one file; cell-level errors go to problems (apply refuses)."""
    name, locale, pct, dfmt = f["file"], f["number_locale"], f["percent_format"], f.get("date_format")
    mapped = [(i, c) for i, c in enumerate(f["columns"]) if c.get("action") == "map"]
    rows = []
    errors = 0
    for rn, r in enumerate(info["rows"], start=1):
        row: dict[str, str] = {}
        for i, c in mapped:
            sem, kind, cell = c["semantic"], _KIND.get(c["semantic"], "text"), r[i]
            try:
                if _missing(cell):
                    row[sem] = ""
                elif kind in ("int", "number", "money", "rate"):
                    row[sem] = _convert(cell, kind, locale, pct)
                elif kind == "id":
                    v = cell.strip()
                    if _SCI_ID.match(v) or _GROUPED_ID.match(v):
                        raise IntakeError(f"ID '{v}' damaged by a spreadsheet (scientific notation or separators): "
                                          "download the file again without opening it in Excel")
                    row[sem] = v
                elif kind == "date":
                    d = _parse_date(cell, dfmt)
                    if d is None:
                        raise IntakeError(f"date '{cell}' is not valid in the format {dfmt}")
                    row[sem] = d.isoformat()
                elif kind.startswith("enum:"):
                    row[sem] = f["value_maps"][c["header"]][cell.strip()]
                else:
                    v = cell.strip()
                    if _EMAIL.search(v) or _PHONE.match(v):
                        stats["redacted"] = stats.get("redacted", 0) + 1
                        v = ""
                    row[sem] = v
            except IntakeError as e:
                errors += 1
                if errors <= 20:
                    problems.append(f"{name}: data row {rn}, column {_col(c['header'])}: {e}")
        rows.append(row)
    if errors > 20:
        problems.append(f"{name}: {errors - 20} more conversion errors")
    for key in ("keyword_text", "negative_text") if report in ("keywords", "negative_keywords") else ():
        for row in rows:
            if row.get(key) and row.get("match_type"):
                row[key], conflict = _strip_wrapper(row[key], row["match_type"])
                if conflict:
                    stats.setdefault("wrapper_conflicts", []).append(f"{name}: '{row[key]}' ({row['match_type']})")
    cids = sorted({row["customer_id"] for row in rows if row.get("customer_id")})
    _require(all(c == answers.get("customer_id") for c in cids), problems,
             f"{name}: customer ID in the file ({', '.join(cids)}) differs from answers.customer_id")
    cur_idx = [i for i, h in enumerate(info["headers"]) if _norm(h) in (_norm("Currency code"), _norm("Codice valuta"))]
    curs = sorted({r[i] for r in info["rows"] for i in cur_idx if not _missing(r[i])})
    _require(all(c == answers.get("currency_code") for c in curs), problems,
             f"{name}: currency in the file ({', '.join(curs)}) differs from answers.currency_code")
    per = _preamble_period(info["preamble"])
    if per:
        _require((per["start"], per["end"]) == (answers.get("date_range_start"), answers.get("date_range_end")),
                 problems, f"{name}: the period in the title lines ({per['start']} → {per['end']}) differs from the "
                           "confirmed period")
    return rows


def _project(rows: list[dict], cols: list[str], mapping: dict[str, str]) -> list[dict]:
    out = []
    for r in rows:
        o = {}
        for c in cols:
            src = mapping.get(c, c)
            if src.endswith("_*"):
                prefix = src[:-1]
                parts = sorted(((int(k[len(prefix):]), v) for k, v in r.items()
                                if k.startswith(prefix) and k[len(prefix):].isdigit() and v), key=lambda x: x[0])
                o[c] = " | ".join(v for _, v in parts)
            else:
                o[c] = r.get(src, "")
        out.append(o)
    return out


GRAIN = {  # duplicate keys → refuse (prevents double counting); search_terms duplicates are reported only
    "campaigns": ["id"], "ad_groups": ["id"], "keywords": ["ad_group_id", "id"], "ads": ["ad_group_id", "id"],
    "conversion_actions": ["id"], "campaign_metrics": ["campaign_id"], "ad_group_metrics": ["ad_group_id"],
    "keyword_metrics": ["ad_group_id", "keyword_id"], "ad_metrics": ["ad_group_id", "ad_id"],
}


def apply(raw: Path, mapping_path: Path, out: Path) -> int:
    """Apply a CONFIRMED mapping: write normalized CSVs, account.csv, table_manifest.csv, intake_report.md into out.

    Rules:   Refuses (exit 2, writes nothing) unless mapping.confirmed is true, schema matches, every answer
             and every file entry is explicit (table/locale/percent/date format/filters), every column is
             map|drop with a routable semantic, every enum value is confirmed, PII columns stay dropped,
             file hashes and headers match the raw files, IDs are undamaged, grain keys are unique, and out
             is empty or new. Snapshot tables are skipped when a segment (date/device/network) is mapped.
    """
    problems: list[str] = []
    try:
        m = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"REFUSED: unreadable mapping: {e}", file=sys.stderr)
        return 2
    if not isinstance(m, dict) or m.get("schema") != MAPPING_SCHEMA:
        print(f"REFUSED: mapping schema differs from {MAPPING_SCHEMA}", file=sys.stderr)
        return 2
    if m.get("confirmed") is not True:
        print("REFUSED: the mapping is not confirmed (\"confirmed\": true after the colleague's answers)",
              file=sys.stderr)
        return 2
    if out.exists() and any(out.iterdir()):
        print(f"REFUSED: the output folder {out} is not empty", file=sys.stderr)
        return 2
    answers = m.get("answers") or {}
    _valid_answers(answers, problems)
    try:
        raw_by_name = {name: data for name, data in _raw_files(raw)} if raw.exists() else {}
    except RawLimitError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    entries = m.get("files") or []
    listed = [f.get("file") for f in entries]
    for name in sorted(set(raw_by_name) - set(listed)):
        problems.append(f"{name}: present in the folder but missing from the mapping (re-run the preflight or use "
                        "table \"skip\")")
    tables: dict[str, dict] = {}
    stats: dict = {}
    report_rows = []
    for f in entries:
        name = f.get("file")
        if name not in raw_by_name:
            problems.append(f"{name}: file not found in {raw}")
            continue
        info = read_ui_file(name, raw_by_name[name])
        before = len(problems)
        report = _check_file_entry(f, info, problems)
        if report is None:
            report_rows.append((name, "skipped", 0, 0, "", ""))
            continue
        if len(problems) > before:
            continue
        rows = _normalize_rows(f, info, report, answers, problems, stats)
        sems = {c["semantic"] for c in f["columns"] if c.get("action") == "map"}
        segmented = bool(sems & SEGMENT_SEMS)
        spec = REPORTS[report]
        filt = f["filters"]
        completeness = "complete" if filt["applied"] is False else f"partial — {filt['description'].strip()}"
        written = []
        for table, cols in _output_columns(report, sems).items():
            is_entity = table == spec["entity"][0]
            if is_entity and segmented and spec["metrics"]:
                stats.setdefault("skipped_snapshots", []).append(f"{name}: {table} (segmented file)")
                continue
            if not cols:
                continue
            proj = _project(rows, cols, spec["entity"][1] if is_entity else {})
            t = tables.setdefault(table, {"columns": [], "rows": [], "sources": [], "completeness": [],
                                          "filters": [], "segmented": False})
            for c in cols:
                if c not in t["columns"]:
                    t["columns"].append(c)
            t["rows"] += proj
            t["sources"].append(name)
            t["completeness"].append(completeness)
            t["filters"].append("none" if filt["applied"] is False else filt["description"].strip())
            t["segmented"] = t["segmented"] or segmented
            written.append(table)
        report_rows.append((name, ", ".join(written) or "no table", len(rows),
                            len(info["totals"]), completeness,
                            ", ".join(_col_md(c["header"]) for c in f["columns"] if c.get("action") == "drop")))
    for table, t in sorted(tables.items()):
        keys = GRAIN.get(table)
        if not keys:
            continue
        seg = [c for c in ("date", "device", "network") if c in t["columns"]]
        seen, dups = set(), set()
        for r in t["rows"]:
            k = tuple(r.get(c, "") for c in keys + seg)
            if not all(k[:len(keys)]):
                continue
            if k in seen:
                dups.add(k)
            seen.add(k)
        if dups:
            problems.append(f"{table}: duplicate rows for the key {keys + seg}: {sorted(dups)[:5]} (overlapping "
                            f"files? {', '.join(t['sources'])})")
    if problems:
        print("REFUSED — to fix:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    _write_outputs(out, tables, answers, report_rows, stats)
    print(f"apply: {len(tables)} normalized tables + account.csv + table_manifest.csv → {out}")
    return 0


def _csv_text(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([r.get(c, "") for c in columns])
    return buf.getvalue()


def _write_outputs(out: Path, tables: dict, a: dict, report_rows: list, stats: dict) -> None:
    lag = "" if a["conversion_lag_days"] == "unknown" else str(a["conversion_lag_days"])
    basis = "" if a["conversion_date_basis"] == "unknown" else a["conversion_date_basis"]
    auto = a.get("auto_tagging")
    account = {"customer_id": str(a["customer_id"]), "name": a.get("account_name") or "",
               "currency_code": a["currency_code"], "time_zone": a["time_zone"],
               "auto_tagging": "" if auto in (None, "unknown") else auto,
               "date_range_start": a["date_range_start"], "date_range_end": a["date_range_end"],
               "snapshot_date": a["snapshot_date"], "rates_format": "fraction", "money_unit": a["money_unit"],
               "conversion_date_basis": basis, "conversion_lag_days": lag}
    (out / "account.csv").write_text(_csv_text(list(account), [account]), encoding="utf-8")
    man_cols = ["filename", "source", "source_files", "exported_at", "period_start", "period_end", "timezone",
                "period_kind", "row_grain", "columns", "row_count", "completeness", "filters", "truncation",
                "conversion_date_basis", "notes"]
    manifest = [{"filename": "account.csv", "source": "intake answers (colleague) + Google Ads UI",
                 "source_files": "", "exported_at": a["snapshot_date"], "period_start": a["date_range_start"],
                 "period_end": a["date_range_end"], "timezone": a["time_zone"], "period_kind": "account_settings",
                 "row_grain": "customer_id", "columns": ";".join(account), "row_count": "1",
                 "completeness": "complete", "filters": "none", "truncation": "none",
                 "conversion_date_basis": basis, "notes": "confirmed via skill-173 intake"}]
    for table, t in sorted(tables.items()):
        fn = f"{table}.csv"
        (out / fn).write_text(_csv_text(t["columns"], t["rows"]), encoding="utf-8")
        snapshot = table in ("campaigns", "ad_groups", "keywords", "ads", "negative_keywords", "conversion_actions")
        partial = [c for c in t["completeness"] if c != "complete"]
        manifest.append({
            "filename": fn, "source": "Google Ads UI download", "source_files": "; ".join(t["sources"]),
            "exported_at": a["snapshot_date"],
            "period_start": a["snapshot_date"] if snapshot else a["date_range_start"],
            "period_end": a["snapshot_date"] if snapshot else a["date_range_end"], "timezone": a["time_zone"],
            "period_kind": "configuration_snapshot" if snapshot else (
                "segmented_report" if t["segmented"] else "aggregate_report"),
            "row_grain": ";".join(GRAIN.get(table, ["search_term", "campaign_id", "ad_group_id"]
                                            if table == "search_terms" else ["text", "level"])
                                  + [c for c in ("date", "device", "network") if c in t["columns"]]),
            "columns": ";".join(t["columns"]), "row_count": str(len(t["rows"])),
            "completeness": partial[0] if partial else "complete",
            "filters": "; ".join(sorted(set(t["filters"]))),
            "truncation": "visible terms only (privacy thresholds)" if table == "search_terms" else "none",
            "conversion_date_basis": "not_applicable" if snapshot else basis,
            "notes": "totals rows removed; rates as fractions; money in " + a["money_unit"]})
    manifest.append({"filename": "table_manifest.csv", "source": "skill-173 intake apply", "source_files": "",
                     "exported_at": a["snapshot_date"], "period_start": a["snapshot_date"],
                     "period_end": a["snapshot_date"], "timezone": a["time_zone"], "period_kind": "provenance",
                     "row_grain": "filename", "columns": ";".join(man_cols), "row_count": str(len(manifest) + 1),
                     "completeness": "complete", "filters": "none", "truncation": "none",
                     "conversion_date_basis": "not_applicable", "notes": "one row per exported file"})
    (out / "table_manifest.csv").write_text(_csv_text(man_cols, manifest), encoding="utf-8")
    (out / "intake_report.md").write_text(_intake_md(tables, a, report_rows, stats), encoding="utf-8")


def _intake_md(tables: dict, a: dict, report_rows: list, stats: dict) -> str:
    L = ["# Intake report — normalized export", "",
         f"Account {a['customer_id']} · currency {a['currency_code']} · time zone {a['time_zone']} · period "
         f"{a['date_range_start']} → {a['date_range_end']} · downloaded on {a['snapshot_date']} · conversion lag "
         f"{a['conversion_lag_days']}.", "",
         "| Source file | Tables written | Rows | Totals removed | Completeness | Dropped columns |",
         "|---|---|---|---|---|---|"]
    for name, written, n, tot, comp, dropped in report_rows:
        cells = [name, written, n, tot, comp or "-", dropped or "-"]
        L.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")  # one well-formed table
    L += ["", "## Notes", ""]
    L.append("- Numbers converted to the 1234.56 format; percentages to fractions (12.5% → 0.125); '--' → empty "
             "(unknown, not zero).")
    if stats.get("redacted"):
        L.append(f"- {stats['redacted']} cells that look like e-mail/phone blanked for privacy.")
    for s in stats.get("skipped_snapshots", []):
        L.append(f"- Entity table not written: {s}; also download the report without segments.")
    for s in stats.get("wrapper_conflicts", [])[:10]:
        L.append(f"- Punctuation conflicts with the match type, text left unchanged: {s}.")
    gaps = []
    for t, req in BASE_REQUIRED.items():
        if t not in tables:
            gaps.append(f"- `{t}`: no file ({DOWNLOAD_HINTS[REPORT_FOR_TABLE[t]]}).")
        else:
            miss = [c for c in req if c not in tables[t]["columns"]]
            if miss:
                gaps.append(f"- `{t}`: missing {', '.join(miss)}.")
    L += ["", "## Still missing for the base audit", ""] + (gaps or ["- Nothing."])
    L += ["", "Next step: check with `check.py run --export <this folder>`, then use this folder as `--export` for "
              "the recipes."]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- run (readiness)


def run(ctx) -> None:
    """Readiness of an already-normalized export: account row, manifest, and each base table's columns and values.

    Rules:   One check per base table (needs = BASE_REQUIRED) plus account_row and manifest; a missing file or
             column is coverage 'skipped' with exact table:column names, never a finding. Findings: Warning for
             account fields unknown, numeric cells that do not parse with adsrun.values, enum cells outside the
             canonical vocabulary, scientific-notation/grouped IDs; Info for base tables without a manifest row or
             declared partial/truncated. Never Critical; never inspects raw UI files.
    """
    acc = ctx.check("account_row", "Account row: currency, time zone, period, snapshot, units",
                    {"account": ACCOUNT_REQUIRED})
    if acc.runnable:
        for f in ACCOUNT_REQUIRED:
            if _missing(ctx.account.get(f)):
                acc.finding("account_field_unknown", "Warning", {"table": "account", "column": f},
                            f"account.{f} is empty: dependent recipe checks will skip or stay partial",
                            evidence={"column": f}, recommendation="Answer the intake question and re-run apply.",
                            uncertainty="Unknown is not a default value.")
        acc.observe("Account scope", currency=ctx.currency, period=[ctx.period_start, ctx.period_end],
                    snapshot=ctx.snapshot, conversion_lag_days=ctx.lag_days, maturity=ctx.mature)
    man = ctx.check("manifest", "table_manifest rows and completeness for base tables",
                    {"table_manifest": ["filename", "completeness"]})
    if man.runnable:
        for table in sorted(BASE_REQUIRED):
            t = ctx.evidence.get(table)
            if t is None:
                continue
            if t.manifest is None:
                man.finding("manifest_row_missing", "Info", {"table": table},
                            f"{t.filename} has no table_manifest row: absence findings cannot be proven",
                            evidence={"filename": t.filename}, recommendation="Add provenance via the intake apply.")
            elif t.complete is not True or t.truncated:
                man.finding("table_declared_partial", "Info", {"table": table},
                            f"{t.filename} is declared {t.manifest.get('completeness')!r}, truncation "
                            f"{t.manifest.get('truncation')!r}: dependent absence checks stay partial",
                            evidence={"completeness": t.manifest.get("completeness"),
                                      "truncation": t.manifest.get("truncation")})
    for table in sorted(BASE_REQUIRED):
        c = ctx.check(f"table_{table}", f"Base table {table}: required columns and value formats",
                      {table: BASE_REQUIRED[table]})
        if not c.runnable:
            continue
        t = ctx.table(table)
        for col in t.columns:
            kind = OUTPUT_KINDS.get(col)
            vocab = OUTPUT_ENUMS.get((table, col))
            bad = []
            for r in t.rows:
                v = r.get(col)
                if _missing(v):
                    continue
                s = str(v).strip()
                if kind == "id" and (_SCI_ID.match(s) or _GROUPED_ID.match(s)):
                    bad.append(s)
                elif kind in ("int", "number", "money") and V.num(s) is None:
                    bad.append(s)
                elif kind == "rate" and s[0] not in "<>" and V.rate(s, ctx.rates_format or "fraction") is None:
                    bad.append(s)
                elif vocab and s not in (ENUM_ALLOWED[vocab] or ()):
                    bad.append(s)
            if not bad:
                continue
            key = ("id_damaged" if kind == "id" else "non_canonical_values" if vocab else "unparsed_numeric_cells")
            c.finding(key, "Warning", {"table": table, "column": col},
                      f"{table}.{col}: {len(bad)} cell(s) not in normalized form (e.g. {sorted(set(bad))[:3]})",
                      evidence={"cells": len(bad), "examples": sorted(set(bad))[:5], "rows": len(t.rows)},
                      calculation={"numerator": len(bad), "denominator": len(t.rows)},
                      recommendation="Re-run the skill-173 intake (preflight → apply) instead of editing cells.",
                      uncertainty="Recipes read these cells as unknown.")
        c.observe(f"{table}: {len(t.rows)} rows", rows=len(t.rows), columns=len(t.columns),
                  complete=t.complete, truncated=t.truncated)


# ----------------------------------------------------------------------------- CLI


def main(argv=None) -> int:
    """preflight/apply subcommands; everything else goes to the standard adsrun CLI (run/finalize).

    Rules:   `run` stays reachable through cli.main so lint, grader and RUNTIME.md usage are unchanged;
             --table FILE=TYPE (repeatable) records the colleague's answer for an undetected report type.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("preflight", "apply"):
        ap = argparse.ArgumentParser(prog=f"{SKILL} check.py")
        sub = ap.add_subparsers(dest="cmd", required=True)
        p = sub.add_parser("preflight", help="scan raw Google Ads UI downloads (folder or ZIP)")
        p.add_argument("--raw", required=True, type=Path)
        p.add_argument("--out", required=True, type=Path)
        p.add_argument("--table", action="append", default=[], help="FILE=TYPE answered by the colleague")
        q = sub.add_parser("apply", help="write the normalized export from a confirmed mapping")
        q.add_argument("--raw", required=True, type=Path)
        q.add_argument("--mapping", required=True, type=Path)
        q.add_argument("--out", required=True, type=Path)
        a = ap.parse_args(argv)
        if a.cmd == "preflight":
            forced = {}
            for item in a.table:
                name, _, typ = item.rpartition("=")
                if typ not in REPORTS or not name:
                    print(f"ERROR: --table {item}: allowed types {sorted(REPORTS)}", file=sys.stderr)
                    return 2
                forced[name] = typ
            return preflight(a.raw, a.out, forced)
        return apply(a.raw, a.mapping, a.out)
    return cli.main(SKILL, VERSION, run, None, argv)


if __name__ == "__main__":
    sys.exit(main())
