"""Wofür gilt der Standard? Anwendungsfeld und Korpus, aus dem Musterlastenheft.

Die Prompts nannten bisher fest „ein Druckgießwerkzeug", „18 historische
Lastenhefte" und „67 Kriterien", dazu Häufigkeiten und Beispiele aus dem
Druckguss-Korpus. Wird ein Musterlastenheft für ein anderes Anwendungsfeld
übernommen, stimmten diese Angaben nicht mehr — und sie standen dort, wo das
Modell sein Urteil fällt.

Dieses Modul hält die drei Dinge, die sich je Musterlastenheft ändern:

- **Gegenstand**: Wofür ist das Lastenheft? Gelesen aus der Metadaten-Tabelle
  am Anfang des Dokuments („Werkzeugtyp", „Gegenstand", …).
- **Korpus**: Aus wie vielen Lastenheften ist der Standard abgeleitet? Gelesen
  aus den Kopftabellen der Kriterien („belegt in N von M“).
- **Korpusbefunde**: Dürfen Aussagen im Prompt stehen, die am Druckguss-Korpus
  gemessen wurden — die Häufigkeitsrangfolge der Abweichungsarten, die
  Basisrate der Statuswerte, Beispiele mit Kriteriumsnummern?

## Das gemessene Feld bleibt Zeichen für Zeichen erhalten

Alle dokumentierten Kennzahlen hängen am genauen Wortlaut der Prompts.
`GEMESSEN` beschreibt das Feld, unter dem gemessen wurde, und erzeugt exakt
diesen Wortlaut. Es gilt, wenn

- die Struktur-Datei noch keinen Eintrag zum Anwendungsfeld trägt (Stand vor
  diesem Modul), oder
- das eingelesene Musterlastenheft dasselbe Feld und dieselbe Korpusgröße
  ausweist — ein erneutes Übernehmen des Druckguss-Musterlastenhefts ändert
  also keinen Prompt.

Jedes andere Feld bekommt eine neutrale Fassung: derselbe Aufbau, dieselben
Regeln, aber ohne die Korpusbefunde, die für dieses Feld nicht gemessen sind.
Eine falsche Häufigkeitsangabe im Prompt ist schlimmer als keine — sie steuert
das Urteil in eine Richtung, die niemand belegt hat.
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.verzeichnisse import DATA_DIR, STRUKTUR_NAME

STRUKTUR_FILE = DATA_DIR / STRUKTUR_NAME

SCHLUESSEL = "anwendungsfeld"


@dataclass(frozen=True)
class Anwendungsfeld:
    # Wie der Gegenstand nach „für" im Einzelfall heißt: „ein Druckgießwerkzeug".
    gegenstand: str
    # Die Mehrzahl, für Sätze über viele Lastenhefte: „Druckgießwerkzeuge".
    gegenstand_mehrzahl: str
    # Aus wie vielen Lastenheften der Standard abgeleitet ist. None: unbekannt.
    korpus: int | None
    # Gelten die am Druckguss-Korpus gemessenen Aussagen? Nur für GEMESSEN.
    korpusbefunde: bool = False

    # ── Satzbausteine ─────────────────────────────────────────────────────────
    @property
    def korpus_dativ(self) -> str:
        """„18 Lastenheften" / „mehreren Lastenheften" — nach „aus", „von"."""
        return f"{self.korpus} Lastenheften" if self.korpus else "mehreren Lastenheften"

    def als_dict(self) -> dict:
        return asdict(self)


# Das Feld, unter dem alle dokumentierten Kennzahlen gemessen wurden.
GEMESSEN = Anwendungsfeld(
    gegenstand="ein Druckgießwerkzeug",
    gegenstand_mehrzahl="Druckgießwerkzeuge",
    korpus=18,
    korpusbefunde=True,
)

# Wenn das Musterlastenheft sein Anwendungsfeld nicht ausweist. Grammatisch
# nach „für" und in Mehrzahlsätzen verwendbar, ohne etwas zu behaupten.
UNBEKANNT_GEGENSTAND = "den Gegenstand des Musterlastenhefts"


def aus_dict(d: dict | None) -> Anwendungsfeld:
    if not d:
        return GEMESSEN
    return Anwendungsfeld(
        gegenstand=str(d.get("gegenstand") or UNBEKANNT_GEGENSTAND),
        gegenstand_mehrzahl=str(d.get("gegenstand_mehrzahl") or UNBEKANNT_GEGENSTAND),
        korpus=int(d["korpus"]) if d.get("korpus") else None,
        korpusbefunde=bool(d.get("korpusbefunde")),
    )


def aktuell(pfad: Path | None = None) -> Anwendungsfeld:
    """Das Anwendungsfeld des hinterlegten Standards.

    Fehlt die Struktur-Datei oder trägt sie keinen Eintrag, gilt das gemessene
    Feld — genau der Stand, unter dem die Software bisher lief.
    """
    p = pfad or STRUKTUR_FILE
    try:
        daten = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GEMESSEN
    return aus_dict(daten.get(SCHLUESSEL))


# ── Ableiten beim Einlesen des Musterlastenhefts ─────────────────────────────

# Zeilenköpfe der Metadaten-Tabelle, unter denen das Anwendungsfeld steht. Das
# Druckguss-Musterlastenheft nennt es „Werkzeugtyp"; andere Felder schreiben
# eher „Gegenstand", „Produkt" oder „Bauteil".
_FELD_ZEILE = re.compile(
    r"^\s*(werkzeugtyp|gegenstand|anwendungsfeld|anwendungsbereich|produkt\w*"
    r"|bauteil\w*|anlagentyp|ger[äa]tetyp|typ)\s*:?\s*$", re.I)

_KORPUS_ZEILE = re.compile(r"^\s*(ableitungsbasis|korpus|grundlage)\s*:?\s*$", re.I)
_ERSTE_ZAHL   = re.compile(r"\b(\d{1,4})\b")


def _gegenstand_aus(wert: str) -> str | None:
    """„Druckgießwerkzeuge (Druckguss-Formen), einschließlich …" -> „Druckgießwerkzeuge"."""
    kurz = re.split(r"[(,;:]| einschlie| inkl", wert, maxsplit=1)[0].strip()
    return kurz or None


def ableiten(metadaten: list[tuple[str, str]],
             korpus_aus_kopftabellen: int | None) -> tuple[Anwendungsfeld, list[str]]:
    """Das Anwendungsfeld aus der Metadaten-Tabelle und den Kopftabellen.

    `metadaten` sind die zweispaltigen Zeilen am Dokumentanfang, `(Kopf, Wert)`.
    Rückgabe: das Feld und Meldungen für den Importbericht.
    """
    meldungen: list[str] = []

    gegenstand = next((_gegenstand_aus(w) for k, w in metadaten
                       if _FELD_ZEILE.match(k) and w.strip()), None)

    korpus = korpus_aus_kopftabellen
    if korpus is None:
        korpus = next((int(m.group(1)) for k, w in metadaten
                       if _KORPUS_ZEILE.match(k)
                       for m in [_ERSTE_ZAHL.search(w)] if m), None)

    if gegenstand is None:
        meldungen.append(
            "Das Anwendungsfeld steht nicht in der Metadaten-Tabelle am Anfang "
            "des Musterlastenhefts (Zeile „Gegenstand“ oder „Werkzeugtyp“). Die "
            "Prüfung spricht deshalb neutral vom Gegenstand des Musterlastenhefts.")
    if korpus is None:
        meldungen.append(
            "Die Korpusgröße ist nicht erkennbar (Kopftabellen ohne „belegt in N "
            "von M“). Der Prompt spricht deshalb von „mehreren Lastenheften“.")

    if (gegenstand == GEMESSEN.gegenstand_mehrzahl and korpus == GEMESSEN.korpus):
        return GEMESSEN, meldungen

    feld = Anwendungsfeld(
        gegenstand=gegenstand or UNBEKANNT_GEGENSTAND,
        gegenstand_mehrzahl=gegenstand or UNBEKANNT_GEGENSTAND,
        korpus=korpus,
        korpusbefunde=False,
    )
    if gegenstand is None:
        return feld, meldungen
    meldungen.append(
        f"Anwendungsfeld „{feld.gegenstand_mehrzahl}“ weicht vom gemessenen Feld "
        f"ab. Häufigkeitsangaben und Beispiele aus dem Druckguss-Korpus entfallen "
        f"im Prompt; die dokumentierten Kennzahlen gelten für dieses Feld nicht.")
    return feld, meldungen


# ── Übertragen eines am gemessenen Feld formulierten Textes ──────────────────
#
# Die übrigen Prompts (Kriterium, Auftrag, Zusatzanforderungen, Hinweise,
# Dokumentvergleich) behalten ihren gemessenen Wortlaut als Vorlage. Für ein
# anderes Feld werden genau die Phrasen ersetzt, die Feld, Korpus und
# Kriterienzahl nennen. Für das gemessene Feld ist das eine Nulloperation — der
# Wortlaut der dokumentierten Läufe kann sich dadurch nicht verschieben.

GEMESSENE_KRITERIENZAHL = 67


def anzahl_kriterien(pfad: Path | None = None) -> int:
    """Wie viele Kriterien der hinterlegte Standard hat."""
    p = pfad or STRUKTUR_FILE
    try:
        daten = json.loads(p.read_text(encoding="utf-8"))
        return len(daten["kriterien"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return GEMESSENE_KRITERIENZAHL


def uebertragen(text: str, feld: Anwendungsfeld | None = None,
                anzahl: int | None = None, format_sicher: bool = False) -> str:
    """Setzt Anwendungsfeld, Korpus und Kriterienzahl in einen Prompt ein.

    `format_sicher` verdoppelt geschweifte Klammern in den eingesetzten Werten,
    wenn der Text danach noch durch str.format() läuft.
    """
    feld = feld or aktuell()

    def wert(s: str) -> str:
        return s.replace("{", "{{").replace("}", "}}") if format_sicher else s

    if anzahl is not None and anzahl != GEMESSENE_KRITERIENZAHL:
        for wort in ("Kriterien", "Nummern"):
            text = text.replace(f"{GEMESSENE_KRITERIENZAHL} {wort}", f"{anzahl} {wort}")

    if feld.korpus != GEMESSEN.korpus:
        hist = (f"{feld.korpus} historischen Lastenheften" if feld.korpus
                else "mehreren historischen Lastenheften")
        text = text.replace(f"{GEMESSEN.korpus} historischen Lastenheften", hist)

    if feld.gegenstand != GEMESSEN.gegenstand:
        g = wert(feld.gegenstand)
        text = text.replace("ein Druckgießwerkzeug", g).replace("ein\nDruckgießwerkzeug", g)
    if feld.gegenstand_mehrzahl != GEMESSEN.gegenstand_mehrzahl:
        text = text.replace("Druckgießwerkzeuge", wert(feld.gegenstand_mehrzahl))
    return text
