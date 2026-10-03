"""Erzeugt den maschinenlesbaren Standard aus dem Musterlastenheft (DOCX).

Das Musterlastenheft ist die einzige Quelle der Wahrheit — die Datei, die ein
Mensch tatsächlich bearbeitet. `Standard_Lastenheft_Chunks.jsonl` und
`struktur_kriterien.json` sind Build-Artefakte, die hier daraus entstehen.

Herkunft der Felder:

    Überschriften        -> abschnitt_nr, abschnitt_titel, kapitel_nr, kapitel_titel
    Kopftabelle          -> einstufung, belegt_in_n_von_18, belegt_laut_haeufigkeitsmatrix
    Abschnittsinhalt     -> standardanforderungen, auspraegungen_im_korpus,
                            platzhalter, abgleichbegriffe
    Ground Truth         -> geregelt_in_dokumenten, geregelt_in_n_von_18
                            (Dokumente mit Status ungleich N)
    daraus zusammengesetzt -> embedding_text

Die Zuordnung ist deterministisch: Die Abschnittsnummer der Überschrift ist die
Kriteriumsnummer. Kein Retrieval, kein Sprachmodell. Bricht die Struktur des
Dokuments, meldet der Parser das — ein stillschweigend halb gelesener Standard
wäre schlimmer als eine klare Fehlermeldung.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.verzeichnisse import DATA_DIR as _DATA_DIR, GT_ABGLEICH, STRUKTUR_NAME

DATA_DIR      = _DATA_DIR
JSONL_ZIEL    = DATA_DIR / "Standard_Lastenheft_Chunks.jsonl"
STRUKTUR_ZIEL = DATA_DIR / STRUKTUR_NAME
GROUND_TRUTH  = GT_ABGLEICH

# Zwischenüberschriften innerhalb eines Abschnitts, in dieser Reihenfolge erwartet.
BLOCK_ANFORDERUNGEN = "standardanforderungen"
BLOCK_AUSPRAEGUNGEN = "ausprägungen im korpus"
BLOCK_PLATZHALTER   = "projektspezifisch festzulegen"
PRAEFIX_BEGRIFFE    = "abgleichbegriffe:"

EINSTUFUNGEN = ("Pflicht", "Regel", "Optional")

_NUMMER    = re.compile(r"^(\d+(?:\.\d+)?)\s+(\S.*)$")
_TIEFER    = re.compile(r"^\d+(?:\.\d+){2,}\.?\s+\S")
_BELEGT    = re.compile(r"belegt\s+in\s+(\d+)\s+von\s+(\d+)", re.IGNORECASE)
_PLATZ     = re.compile(r"\[([^\]]+)\]")
_TRENNER   = re.compile(r"\s*[·•]\s*|\s*;\s*")

# Dokumentkennungen können selbst Kommas enthalten („X-13,3“). Nur trennen, wenn
# auf das Komma Leerraum oder ein Buchstabe folgt — nicht bei einer Ziffer.
_DOKLISTE  = re.compile(r",(?=\s|[A-Za-zÄÖÜ])|\n")


class StandardImportFehler(Exception):
    """Das Musterlastenheft ließ sich nicht als Standard lesen."""


@dataclass
class Importbericht:
    """Was beim Einlesen herauskam — für die Anzeige in der Oberfläche.

    `warnungen` betrifft einzelne Kriterien und ist Alltag: eine fehlende
    Zwischenüberschrift, eine unstimmige Belegzahl. `kritisch` betrifft den
    Standard als Ganzes — hier stimmt eine Grundlage nicht, und das Ergebnis
    wäre unbrauchbar, ohne dass man es ihm ansieht. Zwei Listen, weil das eine
    in einer Klappliste stehen darf und das andere nicht.
    """
    kriterien:  list[dict] = field(default_factory=list)
    warnungen:  list[str]  = field(default_factory=list)
    kritisch:   list[str]  = field(default_factory=list)
    # Wofür das Musterlastenheft gilt — siehe src/muster/anwendungsfeld.py.
    anwendungsfeld: object = None

    @property
    def anzahl(self) -> int:
        return len(self.kriterien)


# ── DOCX lesen ────────────────────────────────────────────────────────────────
def _stil(absatz) -> str:
    return (absatz.style.name if absatz.style is not None else "") or ""


def _ist_ueberschrift(absatz) -> bool:
    return _stil(absatz).lower().startswith(("heading", "überschrift"))


def _abschnitte_lesen(docx_path: Path) -> list[dict]:
    """Zerlegt das Dokument linear in Abschnitte je Überschrift mit Nummer.

    Ein Abschnitt gilt als Kriterium, sobald er eine Kopftabelle besitzt.
    Kapitel 11 ist dadurch mit erfasst: Es trägt seinen Inhalt direkt unter der
    Kapitelüberschrift, ohne eigenen Unterabschnitt.
    """
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(docx_path))

    abschnitte: list[dict] = []
    kapitel_nr = kapitel_titel = ""
    aktuell: dict | None = None

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            absatz = Paragraph(child, doc)
            text   = absatz.text.strip()
            if not text:
                continue

            if _ist_ueberschrift(absatz):
                treffer = _NUMMER.match(text)
                if not treffer and aktuell is not None and _TIEFER.match(text):
                    # „3.3.1 Kernzüge" unter einem Kriterium: eine Gliederung
                    # innerhalb des Abschnitts, kein neues Kriterium. Vorher
                    # beendete sie den Abschnitt, und alles darunter fehlte.
                    aktuell["zeilen"].append((_stil(absatz), text))
                    continue
                if not treffer:
                    # Vorspann wie „Zweck, Aufbau und Verwendung" — beendet den
                    # laufenden Abschnitt, beginnt aber keinen neuen.
                    aktuell = None
                    continue
                nr, titel = treffer.group(1), treffer.group(2).strip()
                if "." not in nr:
                    kapitel_nr, kapitel_titel = nr, titel
                aktuell = {"nr": nr, "titel": titel,
                           "kapitel_nr": kapitel_nr or nr,
                           "kapitel_titel": kapitel_titel or titel,
                           "tabellen": [], "zeilen": []}
                abschnitte.append(aktuell)
                continue

            if aktuell is not None:
                aktuell["zeilen"].append((_stil(absatz), text))

        elif isinstance(child, CT_Tbl) and aktuell is not None:
            tabelle = Table(child, doc)
            aktuell["tabellen"].append(
                [[z.text.strip() for z in reihe.cells] for reihe in tabelle.rows])

    return abschnitte


def _metadaten_lesen(docx_path: Path) -> list[tuple[str, str]]:
    """Die zweispaltigen Tabellenzeilen vor dem ersten Kriterium.

    Das Musterlastenheft beginnt mit einer Steckbrief-Tabelle („Werkzeugtyp“,
    „Ableitungsbasis“, …). Der Abschnittsparser überspringt sie, weil sie vor
    jeder nummerierten Überschrift steht — für das Anwendungsfeld ist sie aber
    die Quelle.
    """
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(docx_path))
    zeilen: list[tuple[str, str]] = []
    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            absatz = Paragraph(child, doc)
            if _ist_ueberschrift(absatz) and _NUMMER.match(absatz.text.strip()):
                break
        elif isinstance(child, CT_Tbl):
            for reihe in Table(child, doc).rows:
                zellen: list[str] = []
                for z in reihe.cells:
                    text = z.text.strip()
                    # Verbundene Zellen liefert python-docx mehrfach.
                    if text and (not zellen or zellen[-1] != text):
                        zellen.append(text)
                if len(zellen) >= 2:
                    zeilen.append((zellen[0], zellen[1]))
    return zeilen


def _korpusgroesse(abschnitte: list[dict]) -> int | None:
    """Das M aus „belegt in N von M“ — die häufigste Angabe über alle Kriterien."""
    from collections import Counter

    zaehler = Counter(int(m.group(2))
                      for a in abschnitte for tabelle in a["tabellen"]
                      for reihe in tabelle for z in reihe
                      for m in [_BELEGT.search(z or "")] if m)
    return zaehler.most_common(1)[0][0] if zaehler else None


def _kopfdaten(abschnitt: dict) -> tuple[str, int, list[str]] | None:
    """Liest Einstufung, Belegzahl und Dokumentliste aus der Kopftabelle."""
    for tabelle in abschnitt["tabellen"]:
        for reihe in tabelle:
            zellen = [z for z in reihe if z]
            if len(zellen) < 2:
                continue
            einstufung = next((e for e in EINSTUFUNGEN
                               if zellen[0].strip().lower() == e.lower()), None)
            if not einstufung:
                continue
            treffer = next((_BELEGT.search(z) for z in zellen if _BELEGT.search(z)), None)
            anzahl  = int(treffer.group(1)) if treffer else 0
            dokumente: list[str] = []
            for z in zellen[1:]:
                if _BELEGT.search(z):
                    continue
                dokumente.extend(t.strip() for t in _DOKLISTE.split(z) if t.strip())
            return einstufung, anzahl, dokumente
    return None


def _bloecke(abschnitt: dict) -> tuple[list[str], list[str], list[str], list[str]]:
    """Trennt den Abschnittstext an den Zwischenüberschriften."""
    anforderungen: list[str] = []
    auspraegungen: list[str] = []
    platzhalter:   list[str] = []
    begriffe:      list[str] = []

    aktueller = None
    for _stilname, text in abschnitt["zeilen"]:
        knapp = text.strip().rstrip(":").lower()

        if knapp == BLOCK_ANFORDERUNGEN:
            aktueller = anforderungen
            continue
        if knapp == BLOCK_AUSPRAEGUNGEN:
            aktueller = auspraegungen
            continue
        if knapp == BLOCK_PLATZHALTER:
            aktueller = platzhalter
            continue
        if text.lower().startswith(PRAEFIX_BEGRIFFE):
            rest = text.split(":", 1)[1]
            begriffe = [t.strip() for t in _TRENNER.split(rest) if t.strip()]
            aktueller = None
            continue

        if aktueller is platzhalter:
            # Zeile der Form „[Schwindmaß in %]  ·  [Lage Formnull]"
            platzhalter.extend(t.strip() for t in _PLATZ.findall(text))
            continue
        if aktueller is not None:
            aktueller.append(text)

    return anforderungen, auspraegungen, platzhalter, begriffe


def _embedding_text(c: dict) -> str:
    """Suchtext je Kriterium — Format wie im bisherigen Standard."""
    return (
        f"{c['abschnitt_nr']} {c['abschnitt_titel']}\n"
        f"Kapitel {c['kapitel_nr']} {c['kapitel_titel']}\n"
        f"Standardanforderungen: {' '.join(c['standardanforderungen'])}\n"
        f"Ausprägungen im Korpus: {' '.join(c['auspraegungen_im_korpus'])}\n"
        f"Projektspezifisch festzulegen: {', '.join(c['platzhalter'])}\n"
        f"Abgleichbegriffe: {', '.join(c['abgleichbegriffe'])}"
    )


def _dok_schluessel(lh_id: str) -> tuple:
    """Sortierschlüssel für Dokumentkennungen: „X-2,1“ vor „X-10“.

    Rein lexikalisch stünde „X-10“ vor „X-2,1“. Die Zahlen werden deshalb als
    Zahlen verglichen.
    """
    teile = re.findall(r"\d+", lh_id)
    return (tuple(int(t) for t in teile), lh_id)


def _geregelt_aus_ground_truth(nr: str, gt: dict | None) -> tuple[list[str], int]:
    """Dokumente, die das Kriterium tatsächlich regeln (Status ungleich N).

    Sortiert, damit der Standard reproduzierbar ist: Ohne Sortierung hinge die
    Reihenfolge an der Schlüsselreihenfolge der Referenzdatei, und zwei Läufe
    über dieselbe Vorlage lieferten unterschiedliche Dateien.
    """
    if not gt:
        return [], 0
    dokumente = sorted(
        (lh for lh, doc in gt["dokumente"].items()
         if doc["bewertungen"].get(nr, {}).get("status") not in (None, "N")),
        key=_dok_schluessel)
    return dokumente, len(dokumente)


def _lade_ground_truth(pfad: Path | None) -> tuple[dict | None, str]:
    """Lädt die Referenzbewertungen. Zweiter Rückgabewert nennt den Grund.

    Der Grund wird gebraucht, weil ein Fehlen sonst folgenlos aussähe: Der
    Import liefe durch, meldete alle Kriterien, und erst der Praxisabgleich zeigte
    Wochen später jedes Kriterium als „nie geregelt“. Ein Ausfall, der wie
    ein gültiges Ergebnis aussieht, ist in diesem Projekt der teuerste
    Fehlertyp.
    """
    if pfad is None:
        return None, "keine Datei angegeben"
    p = Path(pfad)
    if not p.exists():
        return None, f"{p.name} nicht gefunden"
    try:
        gt = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, f"{p.name} nicht lesbar: {e}"
    if not isinstance(gt.get("dokumente"), dict) or not gt["dokumente"]:
        return None, f"{p.name} enthält keine Dokumentbewertungen"
    return gt, ""


_GT_FEHLT = (
    "**Referenzbewertungen fehlen ({grund}).** Die Felder "
    "„geregelt_in_dokumenten\" bleiben leer. Die Prüfung gegen die Kriterien "
    "funktioniert unverändert, aber der Abgleich mit früheren Lastenheften "
    "zeigt dann bei jedem Punkt „nie geregelt\" — jedes Kriterium gälte "
    "als selten, eine Lücke gäbe es nie. Die Datei "
    f"{GT_ABGLEICH.name} gehört nach data/."
)


# ── Hauptfunktion ─────────────────────────────────────────────────────────────
def musterlastenheft_lesen(docx_path: Path,
                           ground_truth: Path | None = GROUND_TRUTH) -> Importbericht:
    """Liest das Musterlastenheft und baut die Kriterienliste auf.

    Wirft StandardImportFehler, wenn sich gar keine Kriterien erkennen lassen —
    dann stimmt die Dokumentstruktur nicht und ein Weitermachen wäre irreführend.
    """
    if docx_path.suffix.lower() != ".docx":
        raise StandardImportFehler(
            f"{docx_path.name} ist keine Word-Datei. Erwartet wird das "
            f"Musterlastenheft als .docx.")

    try:
        abschnitte = _abschnitte_lesen(docx_path)
    except StandardImportFehler:
        raise
    except Exception as e:
        raise StandardImportFehler(
            f"{docx_path.name} konnte nicht gelesen werden: {e}") from None

    gt, gt_grund = _lade_ground_truth(ground_truth)

    bericht = Importbericht()

    from src.muster.anwendungsfeld import ableiten
    try:
        metadaten = _metadaten_lesen(docx_path)
    except Exception:
        metadaten = []
    bericht.anwendungsfeld, meldungen = ableiten(metadaten, _korpusgroesse(abschnitte))
    bericht.warnungen.extend(meldungen)

    # Die Referenzbewertungen gehören zum gemessenen Druckguss-Korpus. Für ein
    # anderes Anwendungsfeld gibt es sie nicht, und ihr Fehlen ist dort kein
    # Mangel — sonst meldete jedes fremde Musterlastenheft einen kritischen Fehler.
    from src.muster.anwendungsfeld import GEMESSEN
    if bericht.anwendungsfeld != GEMESSEN:
        gt = None
    elif gt is None:
        bericht.kritisch.append(_GT_FEHLT.format(grund=gt_grund))

    for abschnitt in abschnitte:
        kopf = _kopfdaten(abschnitt)
        if kopf is None:
            # Kapitelüberschrift ohne eigenen Inhalt — kein Kriterium.
            continue
        einstufung, belegt_n, belegt_docs = kopf
        anforderungen, auspraegungen, platzhalter, begriffe = _bloecke(abschnitt)

        nr = abschnitt["nr"]
        if not anforderungen:
            bericht.warnungen.append(
                f"{nr} {abschnitt['titel']}: keine Standardanforderungen gefunden. "
                f"Fehlt die Zwischenüberschrift „Standardanforderungen\"?")
        if not begriffe:
            bericht.warnungen.append(
                f"{nr} {abschnitt['titel']}: keine Abgleichbegriffe gefunden. "
                f"Die Suche nach Fundstellen wird dadurch schlechter.")
        if belegt_docs and belegt_n and len(belegt_docs) != belegt_n:
            bericht.warnungen.append(
                f"{nr}: Kopfzeile nennt {belegt_n} Dokumente, aufgelistet sind "
                f"{len(belegt_docs)}.")

        geregelt_docs, geregelt_n = _geregelt_aus_ground_truth(nr, gt)

        eintrag = {
            "chunk_id":       f"STD-{nr}",
            "kapitel_nr":     abschnitt["kapitel_nr"],
            "kapitel_titel":  abschnitt["kapitel_titel"],
            "abschnitt_nr":   nr,
            "abschnitt_titel": abschnitt["titel"],
            "einstufung":     einstufung,
            "belegt_in_n_von_18":            belegt_n,
            "belegt_laut_haeufigkeitsmatrix": belegt_docs,
            "geregelt_in_dokumenten":        geregelt_docs,
            "geregelt_in_n_von_18":          geregelt_n,
            "standardanforderungen":  anforderungen,
            "auspraegungen_im_korpus": auspraegungen,
            "platzhalter":            platzhalter,
            "abgleichbegriffe":       begriffe,
        }
        eintrag["embedding_text"] = _embedding_text(eintrag)
        bericht.kriterien.append(eintrag)

    if not bericht.kriterien:
        raise StandardImportFehler(
            f"In {docx_path.name} wurde kein einziges Kriterium erkannt. Erwartet "
            f"werden nummerierte Überschriften (z.B. „3.3 Formnull, "
            f"Koordinatensystem und Schwindung\") mit einer Kopfzeile aus "
            f"Einstufung und Belegzahl.")

    # Die Datei war da und lesbar — trotzdem keine einzige Zuordnung. Dann
    # passen die Kriteriumsnummern der Referenz nicht zu denen des Dokuments.
    if gt is not None and not any(k["geregelt_in_n_von_18"] for k in bericht.kriterien):
        bekannt = sorted({nr for doc in gt["dokumente"].values()
                          for nr in doc.get("bewertungen", {})})[:5]
        bericht.kritisch.append((
            "**Die Referenzbewertungen passen zu keinem Kriterium.** Kein "
            "einziger Punkt bekommt Dokumente zugeordnet — vermutlich sind die "
            "Nummern verschoben. Im Musterlastenheft steht z.B. "
            f"„{bericht.kriterien[0]['abschnitt_nr']}\", in der Referenz "
            f"„{', '.join(bekannt)}\"."))

    return bericht


# ── Vergleich mit dem bisherigen Stand ────────────────────────────────────────
def vergleiche_mit_bestand(neu: list[dict],
                           jsonl_pfad: Path = JSONL_ZIEL) -> dict[str, list[str]]:
    """Was ändert sich gegenüber dem aktuell hinterlegten Standard?

    Wird vor dem Überschreiben angezeigt, damit sichtbar ist, was eine
    Überarbeitung des Musterlastenhefts tatsächlich bewirkt.
    """
    if not jsonl_pfad.exists():
        return {"neu": [f"{c['abschnitt_nr']} {c['abschnitt_titel']}" for c in neu],
                "entfallen": [], "geaendert": [], "unveraendert": []}

    alt = {}
    for zeile in jsonl_pfad.read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            c = json.loads(zeile)
            alt[c["abschnitt_nr"]] = c

    inhaltsfelder = ("abschnitt_titel", "einstufung", "standardanforderungen",
                     "auspraegungen_im_korpus", "platzhalter", "abgleichbegriffe")

    ergebnis: dict[str, list[str]] = {"neu": [], "entfallen": [],
                                      "geaendert": [], "unveraendert": []}
    for c in neu:
        nr = c["abschnitt_nr"]
        if nr not in alt:
            ergebnis["neu"].append(f"{nr} {c['abschnitt_titel']}")
            continue
        abweichend = [f for f in inhaltsfelder if c[f] != alt[nr].get(f)]
        if abweichend:
            ergebnis["geaendert"].append(
                f"{nr} {c['abschnitt_titel']} ({', '.join(abweichend)})")
        else:
            ergebnis["unveraendert"].append(nr)

    neue_nummern = {c["abschnitt_nr"] for c in neu}
    for nr, c in alt.items():
        if nr not in neue_nummern:
            ergebnis["entfallen"].append(f"{nr} {c['abschnitt_titel']}")

    return ergebnis


# ── Schreiben ─────────────────────────────────────────────────────────────────
def schreibe_standard(kriterien: list[dict], jsonl_pfad: Path = JSONL_ZIEL,
                      struktur_pfad: Path = STRUKTUR_ZIEL,
                      anwendungsfeld=None) -> None:
    """Schreibt beide Build-Artefakte. Die Reihenfolge des Dokuments bleibt erhalten."""
    from src.dateien import schreibe_json, schreibe_text

    # Beide Dateien atomar: Eine halb geschriebene Chunk-Datei sähe beim Laden aus
    # wie ein Standard mit weniger Kriterien.
    schreibe_text(jsonl_pfad,
                  "\n".join(json.dumps(c, ensure_ascii=False) for c in kriterien) + "\n")

    struktur = {
        "version": "1.0",
        "anzahl": len(kriterien),
        "hinweis": "Verbindliche Gliederung für den Lastenheft-Abgleich. "
                   "Reihenfolge fix, Nummern sind stabile IDs. "
                   "Erzeugt aus dem Musterlastenheft.",
        "kriterien": [
            {"nr": c["abschnitt_nr"], "titel": c["abschnitt_titel"],
             "kapitel": c["kapitel_titel"], "einstufung": c["einstufung"],
             "abgleichbegriffe": c["abgleichbegriffe"]}
            for c in kriterien
        ],
    }
    # Ohne Angabe bleibt ein vorhandener Eintrag stehen, statt stillschweigend
    # auf das gemessene Feld zurückzufallen.
    if anwendungsfeld is None and struktur_pfad.exists():
        try:
            alt = json.loads(struktur_pfad.read_text(encoding="utf-8"))
            if alt.get("anwendungsfeld"):
                struktur["anwendungsfeld"] = alt["anwendungsfeld"]
        except (OSError, json.JSONDecodeError):
            pass
    elif anwendungsfeld is not None:
        struktur["anwendungsfeld"] = anwendungsfeld.als_dict()
    schreibe_json(struktur_pfad, struktur, indent=1)
