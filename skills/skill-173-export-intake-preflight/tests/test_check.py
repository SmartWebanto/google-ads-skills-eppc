"""test_check.py — skill-173 intake: UI-export parsing, never-guess refusals, normalized export usable by skill-014.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest discover -s skills/skill-173-export-intake-preflight/tests -t skills/skill-173-export-intake-preflight
rules:   Synthetic IT/EN UI-style downloads in temp folders only (title lines, totals rows, IT numbers, UTF-16 TSV).
         Confirmation is simulated by explicit answers; tests assert behavior (exit codes, values, questions,
         coverage), never exact wording. English173 asserts the language contract only: no Italian UI words
         in preflight.md, intake_report.md or CLI output outside quoted/labeled source headers and values.
         The end-to-end test runs the real skill-014 recipe on the applied export.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_intake | initial intake tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_intake_safety | raw input safety tests
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_english | English statuses/messages + no-Italian regression test
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check173", HERE / "scripts" / "check.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
_spec14 = importlib.util.spec_from_file_location("check014_for_173", HERE.parent / "skill-014-search-term-mining-negatives"
                                                 / "scripts" / "check.py")
M14 = importlib.util.module_from_spec(_spec14)
_spec14.loader.exec_module(M14)

TITLE_IT = "1 agosto 2026 - 30 agosto 2026"
IT_FILES = {
    "Rapporto campagne.csv": (
        "Rapporto campagne\n" + TITLE_IT + "\n"
        "Stato della campagna,Campagna,ID campagna,Tipo di campagna,Tipo di strategia di offerta,Budget,Impr.,Clic,"
        "Costo,Conversioni,Valore conv.,CTR,Quota impr. rete di ricerca,Codice valuta\n"
        'Attivata,Trapani,111,Rete di ricerca,CPC manuale,"50,00","12.345","1.200","1.234,56","10,50","2.100,00",'
        '"9,72%","< 10%",EUR\n'
        'In pausa,Brand,112,Rete di ricerca,Massimizza le conversioni,"20,00",800,90,"45,10",3,"300,00","11,25%",'
        '"65,40%",EUR\n'
        'Totale: account,,,,,,"13.145","1.290","1.279,66","13,50","2.400,00","9,81%",--,\n'
        'Totale: campagne,,,,,,"13.145","1.290","1.279,66","13,50","2.400,00","9,81%",--,\n'),
    "Gruppi di annunci.csv": (
        "Rapporto gruppi di annunci\n" + TITLE_IT + "\n"
        "Stato del gruppo di annunci,Gruppo di annunci,ID gruppo di annunci,Campagna,ID campagna\n"
        "Attivato,Trapani a batteria,222,Trapani,111\nAttivato,Brand core,223,Brand,112\n"
        "Totale: account,,,,\n"),
    "Parole chiave.csv": (
        "Rapporto parole chiave\n" + TITLE_IT + "\n"
        "Parola chiave,Tipo di corrispondenza,Stato parola chiave,ID parola chiave,ID gruppo di annunci,ID campagna,"
        "Punteggio di qualità,Impr.,Clic,Costo,Conversioni\n"
        'trapano a batteria,Corrispondenza a frase,Attivata,333,222,111,7,"9.000",900,"1.100,00","9,5"\n'
        'acme,Corrispondenza esatta,Attivata,334,223,112,--,800,90,"45,10",3\n'
        'Totale: account,,,,,,,"9.800",990,"1.145,10","12,5"\n'),
    "Parole chiave escluse.csv": (
        "Parole chiave escluse\n"
        "Parola chiave esclusa,Tipo di corrispondenza,Livello,Campagna,ID campagna\n"
        "[trapano usato],Corrispondenza esatta,Campagna,Trapani,111\n"),
    "Azioni di conversione.csv": (
        "Azioni di conversione\n" + TITLE_IT + "\n"
        "Azione di conversione,ID azione di conversione,Categoria,Stato,Conteggio,Ottimizzazione azione,Tutte le conv.\n"
        'Acquisto,555,Acquisto,Attiva,Ogni,Principale,"13,5"\n'),
}
ST_IT = ("Rapporto termini di ricerca\n" + TITLE_IT + "\n"
         "Termine di ricerca\tTipo di corrispondenza\tAggiunto/Escluso\tCampagna\tID campagna\tID gruppo di annunci\t"
         "Parola chiave\tImpr.\tClic\tCosto\tConversioni\tE-mail contatto\n"
         "trapano gratis\tCorrispondenza a frase\tNessuno\tTrapani\t111\t222\ttrapano a batteria\t500\t65\t130,00\t0,00\t"
         "mario@example.com\n"
         "trapano a batteria prezzo\tCorrispondenza esatta (variante simile)\tNessuno\tTrapani\t111\t222\t"
         "trapano a batteria\t1.500\t300\t450,50\t9,50\tanna@example.com\n"
         "trapano usato\tCorrispondenza a frase\tEscluso\tTrapani\t111\t222\ttrapano a batteria\t40\t5\t9,90\t0\t--\n"
         "Totale: account\t\t\t\t\t\t\t2.040\t370\t590,40\t9,50\t\n")


def utf16(text: str) -> bytes:
    return text.encode("utf-16")  # BOM + little-endian, like the Google Ads UI TSV download


def write_raw(root: Path, files: dict) -> Path:
    raw = root / "raw"
    raw.mkdir()
    for name, content in files.items():
        (raw / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return raw


def it_files() -> dict:
    return {**IT_FILES, "Termini di ricerca.tsv": utf16(ST_IT)}


def quiet(fn, *args):
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = fn(*args)
    return code, err.getvalue()


def preflight(root: Path, files: dict) -> tuple[Path, dict]:
    raw = write_raw(root, files)
    code, err = quiet(M.main, ["preflight", "--raw", str(raw), "--out", str(root / "pre")])
    assert code == 0, err
    return raw, json.loads((root / "pre" / "proposed_mapping.json").read_text(encoding="utf-8"))


ANSWERS = {"customer_id": "123-456-7890", "account_name": "Demo", "currency_code": "EUR",
           "time_zone": "Europe/Rome", "date_range_start": "2026-08-01", "date_range_end": "2026-08-30",
           "snapshot_date": "2026-09-06", "conversion_lag_days": 2, "conversion_date_basis": "interaction_date",
           "money_unit": "currency"}


def confirm(m: dict, resolve: dict | None = None) -> dict:
    """Simulate the colleague's answers: explicit answers, no filters, ambiguous columns resolved by `resolve`."""
    resolve = resolve or {}
    m = json.loads(json.dumps(m))
    m["answers"].update(ANSWERS)
    for f in m["files"]:
        f["filters"] = {"applied": False, "description": ""}
        for c in f["columns"]:
            key = (f["file"], c["header"])
            if key in resolve:
                c["semantic"], c["action"] = resolve[key]
            elif c["action"] is None:
                c["action"] = "drop"
    m["confirmed"] = True
    return m


RESOLVE_IT = {("Azioni di conversione.csv", "Stato"): ("action_status", "map")}


def apply(root: Path, raw: Path, mapping: dict, out="export") -> tuple[int, str]:
    (root / "m.json").write_text(json.dumps(mapping), encoding="utf-8")
    return quiet(M.main, ["apply", "--raw", str(raw), "--mapping", str(root / "m.json"), "--out", str(root / out)])


def read_csv(path: Path) -> list[dict]:
    import csv
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Preflight173(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_detects_tables_locale_totals_and_utf16(self):
        _, m = preflight(self.root, it_files())
        by = {f["file"]: f for f in m["files"]}
        self.assertEqual({k: v["table"] for k, v in by.items()},
                         {"Rapporto campagne.csv": "campaigns", "Gruppi di annunci.csv": "ad_groups",
                          "Parole chiave.csv": "keywords", "Parole chiave escluse.csv": "negative_keywords",
                          "Azioni di conversione.csv": "conversion_actions", "Termini di ricerca.tsv": "search_terms"})
        st = by["Termini di ricerca.tsv"]
        self.assertEqual((st["encoding"], st["delimiter"], st["header_row"]), ("utf-16", "tab", 3))
        self.assertEqual(st["rows"], {"data": 3, "totals_removed": 1, "totals_labels": ["Totale: account"]})
        self.assertEqual(by["Rapporto campagne.csv"]["rows"]["totals_removed"], 2)
        self.assertEqual(by["Rapporto campagne.csv"]["number_locale"], "it")
        self.assertEqual(by["Rapporto campagne.csv"]["percent_format"], "percent_sign")
        self.assertEqual(by["Rapporto campagne.csv"]["detected_period"]["start"], "2026-08-01")
        self.assertEqual((m["answers"]["currency_code"], m["answers"]["date_range_end"]), ("EUR", "2026-08-30"))
        self.assertFalse(m["confirmed"])

    def test_checklist_lists_ambiguous_unmapped_missing_and_questions(self):
        _, m = preflight(self.root, it_files())
        conv = next(f for f in m["files"] if f["table"] == "conversion_actions")
        stato = next(c for c in conv["columns"] if c["header"] == "Stato")
        self.assertEqual((stato["status"], stato["action"]), ("ambiguous", None))
        self.assertEqual(set(stato["candidates"]), {"action_status", "tracking_status"})
        camp = next(f for f in m["files"] if f["table"] == "campaigns")
        ctr = next(c for c in camp["columns"] if c["header"] == "CTR")
        self.assertEqual(ctr["action"], "drop")  # derived metric: proposed drop, still shown
        self.assertIsNone(m["base_gaps"]["ads"])  # no ads download
        self.assertEqual(m["base_gaps"]["campaigns"], [])
        self.assertEqual(m["base_gaps"]["conversion_actions"], ["status"])  # pending the ambiguous 'Stato'
        ids = {q["id"] for q in m["questions"]}
        for needed in ("time_zone", "snapshot_date", "conversion_lag_days", "period", "currency_code",
                       "Rapporto campagne.csv:filters", "Azioni di conversione.csv:Stato"):
            self.assertIn(needed, ids)
        md = (self.root / "pre" / "preflight.md").read_text(encoding="utf-8")
        self.assertIn("`ads`", md)
        self.assertIn("E-mail contatto", md)

    def test_unknown_header_is_listed_not_dropped(self):
        files = {"c.csv": "Campagna,ID campagna,Costo,Colonna strana\nA,1,\"1,50\",x\n"}
        _, m = preflight(self.root, files)
        col = next(c for c in m["files"][0]["columns"] if c["header"] == "Colonna strana")
        self.assertEqual((col["status"], col["action"]), ("unrecognized", None))
        self.assertIn("c.csv:Colonna strana", {q["id"] for q in m["questions"]})

    def test_ambiguous_locale_is_asked_not_guessed(self):
        files = {"c.csv": "Campagna,ID campagna,Impr.,Clic\nA,1,1.234,12\nB,2,900,1.500\n"}
        raw, m = preflight(self.root, files)
        f = m["files"][0]
        self.assertIsNone(f["number_locale"])
        self.assertEqual(f["number_locale_evidence"]["ambiguous"], 2)
        self.assertIn("c.csv:numbers", {q["id"] for q in m["questions"]})
        code, err = apply(self.root, raw, confirm(m))
        self.assertEqual(code, 2)
        self.assertIn("number_locale", err)
        self.assertFalse((self.root / "export").exists())
        confirmed = confirm(m)
        confirmed["files"][0]["number_locale"] = "it"
        self.assertEqual(apply(self.root, raw, confirmed)[0], 0)
        self.assertEqual([r["impressions"] for r in read_csv(self.root / "export" / "campaign_metrics.csv")],
                         ["1234", "900"])

    def test_detect_number_locale_boundaries(self):
        self.assertEqual(M.detect_number_locale(["1.234,5", "12"])["locale"], "it")
        self.assertEqual(M.detect_number_locale(["1,234.5", "0.5"])["locale"], "en")
        self.assertIsNone(M.detect_number_locale(["1.234", "1,234", "7"])["locale"])
        self.assertEqual(M.detect_number_locale(["1.234,5", "12.5"])["status"], "conflicting")


class RawSafety173(unittest.TestCase):
    def _pre(self, raw):
        return quiet(M.main, ["preflight", "--raw", str(raw), "--out", str(Path(self.tmp.name) / "pre")])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _zip(self, name, members, compress=zipfile.ZIP_DEFLATED, attrs=None):
        p = self.root / name
        with zipfile.ZipFile(p, "w", compress) as z:
            for n, data in members.items():
                zi = zipfile.ZipInfo(n)
                zi.compress_type = compress
                if attrs and n in attrs:
                    zi.external_attr = attrs[n] << 16
                z.writestr(zi, data)
        return p

    def test_valid_zip_is_accepted(self):
        p = self._zip("ok.zip", {"Campagne.csv": IT_FILES[next(iter(IT_FILES))]})
        self.assertEqual(self._pre(p)[0], 0)

    def test_zip_bomb_ratio_is_refused(self):
        p = self._zip("bomb.zip", {"a.csv": "a,b\n" + "0,0\n" * 400000})
        code, err = self._pre(p)
        self.assertEqual(code, 2)
        self.assertIn("compression ratio", err)

    def test_too_many_entries_and_nested_zip_are_refused(self):
        with patch.object(M, "MAX_ENTRIES", 3):
            p = self._zip("many.zip", {f"f{i}.csv": "a\n1\n" for i in range(5)})
            self.assertEqual(self._pre(p)[0], 2)
        p = self._zip("nested.zip", {"inner.zip": b"PK\x05\x06" + b"\0" * 18})
        self.assertIn("nested", self._pre(p)[1])

    def test_oversize_file_and_total_are_refused(self):
        raw = self.root / "raw"
        raw.mkdir()
        (raw / "big.csv").write_text("a,b\n" + "1,2\n" * 1000)
        with patch.object(M, "MAX_FILE_BYTES", 100):
            self.assertEqual(self._pre(raw)[0], 2)
        with patch.object(M, "MAX_TOTAL_BYTES", 100):
            self.assertEqual(self._pre(raw)[0], 2)

    def test_symlinks_are_refused(self):
        raw = self.root / "raw"
        raw.mkdir()
        outside = self.root / "secret.csv"
        outside.write_text("a,b\n1,2\n")
        (raw / "link.csv").symlink_to(outside)
        code, err = self._pre(raw)
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err)
        p = self._zip("link.zip", {"l.csv": "../secret.csv"}, attrs={"l.csv": 0o120777})
        self.assertIn("symbolic link", self._pre(p)[1])


class Apply173(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_refuses_unconfirmed_and_incomplete_mappings(self):
        raw, m = preflight(self.root, it_files())
        self.assertEqual(apply(self.root, raw, m)[0], 2)  # confirmed false
        no_answer = confirm(m, RESOLVE_IT)
        no_answer["answers"]["time_zone"] = None
        self.assertEqual(apply(self.root, raw, no_answer)[0], 2)
        unresolved = confirm(m, RESOLVE_IT)
        next(c for f in unresolved["files"] for c in f["columns"] if c["header"] == "Stato")["action"] = None
        self.assertEqual(apply(self.root, raw, unresolved)[0], 2)
        no_filters = confirm(m, RESOLVE_IT)
        no_filters["files"][0]["filters"] = {"applied": None}
        self.assertEqual(apply(self.root, raw, no_filters)[0], 2)
        bad_value = confirm(m, RESOLVE_IT)
        conv = next(f for f in bad_value["files"] if f["table"] == "conversion_actions")
        conv["value_maps"]["Stato"] = {}
        code, err = apply(self.root, raw, bad_value)
        self.assertEqual(code, 2)
        self.assertIn("Attiva", err)
        self.assertFalse((self.root / "export").exists())

    def test_pii_column_cannot_be_mapped(self):
        raw, m = preflight(self.root, it_files())
        st = next(f for f in m["files"] if f["table"] == "search_terms")
        email = next(c for c in st["columns"] if c["header"] == "E-mail contatto")
        self.assertEqual((email["status"], email["action"]), ("pii", "drop"))
        forced = confirm(m, {**RESOLVE_IT, ("Termini di ricerca.tsv", "E-mail contatto"): ("keyword_id", "map")})
        code, err = apply(self.root, raw, forced)
        self.assertEqual(code, 2)
        self.assertIn("E-mail contatto", err)

    def test_confirmed_apply_normalizes_values_and_writes_provenance(self):
        raw, m = preflight(self.root, it_files())
        confirmed = confirm(m, RESOLVE_IT)
        next(f for f in confirmed["files"] if f["table"] == "negative_keywords")["filters"] = {
            "applied": True, "description": "solo campagne attive"}
        code, err = apply(self.root, raw, confirmed)
        self.assertEqual(code, 0, err)
        ex = self.root / "export"
        cm = read_csv(ex / "campaign_metrics.csv")
        self.assertEqual([r["campaign_id"] for r in cm], ["111", "112"])  # totals rows removed
        self.assertEqual((cm[0]["cost"], cm[0]["impressions"], cm[0]["conversions"], cm[0]["conversion_value"]),
                         ("1234.56", "12345", "10.5", "2100"))
        self.assertEqual((cm[0]["search_impression_share"], cm[1]["search_impression_share"]), ("<0.1", "0.654"))
        self.assertNotIn("ctr", cm[0])
        camps = {r["id"]: r for r in read_csv(ex / "campaigns.csv")}
        self.assertEqual((camps["111"]["status"], camps["111"]["channel_type"], camps["112"]["bidding_strategy_type"],
                          camps["111"]["daily_budget"]), ("ENABLED", "SEARCH", "MAXIMIZE_CONVERSIONS", "50"))
        kw = {r["id"]: r for r in read_csv(ex / "keywords.csv")}
        self.assertEqual((kw["333"]["match_type"], kw["334"]["quality_score"]), ("PHRASE", ""))
        neg = read_csv(ex / "negative_keywords.csv")[0]
        self.assertEqual((neg["text"], neg["match_type"], neg["level"]), ("trapano usato", "EXACT", "campaign"))
        st = read_csv(ex / "search_terms.csv")
        self.assertEqual([r["match_type"] for r in st], ["PHRASE", "NEAR_EXACT", "PHRASE"])
        self.assertEqual(st[1]["cost"], "450.5")
        self.assertNotIn("E-mail contatto", st[0])
        self.assertFalse(any("@" in v for r in st for v in r.values()))
        acc = read_csv(ex / "account.csv")[0]
        self.assertEqual((acc["customer_id"], acc["rates_format"], acc["money_unit"], acc["conversion_lag_days"]),
                         ("123-456-7890", "fraction", "currency", "2"))
        man = {r["filename"]: r for r in read_csv(ex / "table_manifest.csv")}
        self.assertEqual(man["campaigns.csv"]["completeness"], "complete")
        self.assertEqual(man["negative_keywords.csv"]["completeness"], "partial — solo campagne attive")
        self.assertIn("visible terms", man["search_terms.csv"]["truncation"])
        self.assertTrue((ex / "intake_report.md").is_file())

    def test_readiness_run_and_skill014_run_on_applied_export(self):
        raw, m = preflight(self.root, it_files())
        self.assertEqual(apply(self.root, raw, confirm(m, RESOLVE_IT))[0], 0)
        ex = self.root / "export"
        code, _ = quiet(M.main, ["run", "--export", str(ex), "--out", str(self.root / "ready")])
        self.assertEqual(code, 0)
        ready = json.loads((self.root / "ready" / "result.json").read_text())
        cov = {c["check"]: c["status"] for c in ready["coverage"]}
        self.assertEqual(cov["table_search_terms"], "partial")  # visible terms only
        self.assertEqual(cov["table_ads"], "skipped")
        self.assertNotIn("Warning", {f["severity"] for f in ready["findings"]})
        code, err = quiet(M14.cli.main, M14.SKILL, M14.VERSION, M14.run, M14.verify,
                          ["run", "--export", str(ex), "--out", str(self.root / "s014")])
        self.assertEqual(code, 0, err)
        body = json.loads((self.root / "s014" / "result.json").read_text())
        self.assertIn("search_terms.csv", body["inputs"]["read"])
        self.assertEqual(body["scope"]["currency"], "EUR")
        s14 = {c["check"]: c["status"] for c in body["coverage"]}
        self.assertNotEqual(s14["query_review"], "skipped")
        self.assertNotEqual(s14["query_coverage"], "skipped")

    def test_readiness_flags_unnormalized_cells(self):
        ex = self.root / "ex"
        ex.mkdir()
        (ex / "account.csv").write_text("customer_id,currency_code,time_zone,date_range_start,date_range_end,"
                                        "snapshot_date,rates_format,money_unit\n1,EUR,,2026-08-01,2026-08-30,"
                                        "2026-09-06,fraction,currency\n")
        (ex / "campaign_metrics.csv").write_text('campaign_id,impressions,clicks,cost,conversions,conversion_value\n'
                                                 '1,100,10,"1.234,56",1,5\n')
        code, _ = quiet(M.main, ["run", "--export", str(ex), "--out", str(self.root / "o")])
        self.assertEqual(code, 0)
        b = json.loads((self.root / "o" / "result.json").read_text())
        got = {(f["condition_key"], f["entity"].get("column")) for f in b["findings"] if f["severity"] == "Warning"}
        self.assertEqual(got, {("unparsed_numeric_cells", "cost"), ("account_field_unknown", "time_zone")})

    def test_english_zip_with_totals_and_en_numbers(self):
        en = ("Campaign report\nAugust 1, 2026 - August 30, 2026\n"
              "Campaign status,Campaign,Campaign ID,Impr.,Clicks,Cost,Conversions,Conv. value,Search impr. share\n"
              'Enabled,Drills,9,"1,234",120,"1,050.25",4.5,"900.00",45.50%\n'
              'Total: Account,,,"1,234",120,"1,050.25",4.5,"900.00",--\n')
        raw = self.root / "raw"
        raw.mkdir()
        with zipfile.ZipFile(raw / "download.zip", "w") as z:
            z.writestr("Campaign report.csv", en)
            z.writestr("__MACOSX/._Campaign report.csv", "junk")
        code, err = quiet(M.main, ["preflight", "--raw", str(raw), "--out", str(self.root / "pre")])
        self.assertEqual(code, 0, err)
        m = json.loads((self.root / "pre" / "proposed_mapping.json").read_text())
        self.assertEqual([f["file"] for f in m["files"]], ["download.zip:Campaign report.csv"])
        f = m["files"][0]
        self.assertEqual((f["table"], f["number_locale"], f["rows"]["totals_removed"]), ("campaigns", "en", 1))
        self.assertEqual(f["detected_period"]["end"], "2026-08-30")
        self.assertEqual(apply(self.root, raw, confirm(m))[0], 0)
        cm = read_csv(self.root / "export" / "campaign_metrics.csv")
        self.assertEqual([(r["impressions"], r["cost"], r["search_impression_share"]) for r in cm],
                         [("1234", "1050.25", "0.455")])

    def test_refuses_changed_file_and_spreadsheet_damaged_ids(self):
        files = {"c.csv": "Campagna,ID campagna,Costo\nA,1.23457E+10,\"1,50\"\n"}
        raw, m = preflight(self.root, files)
        code, err = apply(self.root, raw, confirm(m))
        self.assertEqual(code, 2)
        self.assertIn("1.23457E+10", err)
        (raw / "c.csv").write_text("Campagna,ID campagna,Costo\nA,12345678901,\"1,50\"\n")
        self.assertEqual(apply(self.root, raw, confirm(m))[0], 2)  # sha256 differs from the preflighted file


# Italian UI words that must never appear in generated English text outside quoted/labeled source headers/values.
ITALIAN_DENYLIST = re.compile(r"\b(domand\w*|rifiutat\w*|errore|cartella|colonn[ae]|file non|mancant\w*|suggerit\w*|"
                              r"riconosciut\w*|righe|riga|tabella|mappatura|intestazion\w*|scarica\w*|non è|valuta|"
                              r"fuso|oppure|ignorato|nessun\w*)\b", re.IGNORECASE)
EN_FILES = {
    "Campaign report.csv": (
        "Campaign report\nAugust 1, 2026 - August 30, 2026\n"
        "Campaign status,Campaign,Campaign ID,Impr.,Clicks,Cost,Conversions,Conv. value,Search impr. share,Odd col\n"
        'Enabled,Drills,9,"1,234",120,"1,050.25",4.5,"900.00",45.50%,x\n'
        'Total: Account,,,"1,234",120,"1,050.25",4.5,"900.00",--,\n'),
    "Conversion actions.csv": ("Conversion action,Conversion action ID,Category,Status,Count,Action optimization\n"
                               "Purchase,77,Purchase,Enabled,Every,Primary\n"),
}


def english_only(text: str, names) -> str:
    """Return Italian-looking words left after removing quoted/labeled source text and raw file names."""
    for n in sorted(names, key=len, reverse=True):
        text = text.replace(n, "")
    text = re.sub(r"\(Italian UI:[^()]*\)", "", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = re.sub(r'"[^"\n]*"', "", text)
    text = re.sub(r"(?<!\w)'[^'\n]*'(?!\w)", "", text)
    return ", ".join(sorted({m.group(0) for m in ITALIAN_DENYLIST.finditer(text)}))


class English173(unittest.TestCase):
    STATUSES = {"suggested", "ambiguous", "conflict", "unrecognized", "table_undecided", "pii", "derived", "unused"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _cli(self, argv) -> tuple[int, str]:
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = M.main(argv)
        return code, out.getvalue() + err.getvalue()

    def _roundtrip(self, files: dict, resolve: dict, skip=()) -> list[str]:
        raw = write_raw(self.root, files)
        texts = []
        code, txt = self._cli(["preflight", "--raw", str(raw), "--out", str(self.root / "pre")])
        self.assertEqual(code, 0, txt)
        texts.append(txt)
        texts.append((self.root / "pre" / "preflight.md").read_text(encoding="utf-8"))
        m = json.loads((self.root / "pre" / "proposed_mapping.json").read_text(encoding="utf-8"))
        self.assertLessEqual({c["status"] for f in m["files"] for c in f["columns"]}, self.STATUSES)
        self.assertTrue(all(set(q) == {"id", "question", "answer_in"} for q in m["questions"]))
        mp = self.root / "m.json"
        refusals = [m, confirm(m, resolve)]  # unconfirmed; confirmed but incomplete (bad answers, unresolved value)
        refusals[1]["answers"].update(time_zone="Rome", snapshot_date="06/09/2026", conversion_lag_days=-1)
        for f in refusals[1]["files"]:
            f["table"] = f["table"] or "campaigns"
            for vm in f["value_maps"].values():
                vm.clear()
        for bad in refusals:
            mp.write_text(json.dumps(bad), encoding="utf-8")
            code, txt = self._cli(["apply", "--raw", str(raw), "--mapping", str(mp), "--out", str(self.root / "x")])
            self.assertEqual(code, 2, txt)
            texts.append(txt)
        good = confirm(m, resolve)
        for f in good["files"]:
            if f["file"] in skip:
                f["table"] = "skip"
        mp.write_text(json.dumps(good), encoding="utf-8")
        code, txt = self._cli(["apply", "--raw", str(raw), "--mapping", str(mp), "--out", str(self.root / "ex")])
        self.assertEqual(code, 0, txt)
        texts.append(txt)
        texts.append((self.root / "ex" / "intake_report.md").read_text(encoding="utf-8"))
        texts.append(self._cli(["preflight", "--raw", str(self.root / "missing"), "--out", str(self.root / "p2")])[1])
        texts.append(self._cli(["preflight", "--raw", str(raw), "--out", str(self.root / "p3"), "--table",
                                "x.csv=campagne"])[1])
        for t in texts:
            self.assertEqual(english_only(t, files), "", t)
        return texts

    def test_italian_ui_export_yields_english_text_with_labeled_italian_headers(self):
        files = {**it_files(), "Rotto.csv": b"\x80\x81abc,def\n"}
        texts = self._roundtrip(files, RESOLVE_IT, skip=("Rotto.csv",))
        pre, report = texts[1], texts[5]
        self.assertIn("`Costo` (Italian UI header) → `cost`", pre)
        self.assertIn("`Stato` (Italian UI header) →", pre)
        self.assertIn("(Italian UI header)", report)
        self.assertIn("Italian UI headers:", pre)  # download hint for the missing ads report

    def test_english_ui_export_yields_english_text_without_italian_labels(self):
        texts = self._roundtrip(EN_FILES, {("Conversion actions.csv", "Status"): ("action_status", "map")})
        self.assertIn("`Cost` → `cost`", texts[1])
        self.assertNotIn("`Cost` (Italian UI header)", texts[1])

    def test_italian_ui_header_list_only_names_known_synonyms(self):
        self.assertEqual(sorted(M._norm(h) for h in M.ITALIAN_UI_HEADERS if M._norm(h) not in M.ALL_HEADERS), [])


if __name__ == "__main__":
    unittest.main()
