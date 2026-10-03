"""Wie hält es der Standard selbst mit Herstellern? Einmal lesen, dann merken.

## Wozu

Der Hinweis-Durchgang läuft nicht über alle Kriterien, sondern über die, an
denen eine Fabrikatsbindung des Kunden überhaupt bedeutsam sein kann. Diesen
Vorfilter besorgte bisher ein Regex über den Standardtext
(`hinweise.OFFEN` — „vereinbart", „freigegeben", „abgestimmt").

Hier liest stattdessen das Sprachmodell den Standard und ordnet jeden Abschnitt
in eine von drei Klassen ein (DELEGIERT, VORGESCHRIEBEN, SCHWEIGT). Das Modell
erkennt, ob ein Satz die **Herstellerwahl** delegiert oder irgendetwas anderes
vereinbart. Es wählt deshalb weniger Kriterien und trifft genauer.

## Was das NICHT bringt

Mit beiden Vorfiltern kommen dieselben Abweichungen als Hinweis heraus. Der
Gewinn ist **kürzere Laufzeit bei gleicher Ausbeute**, nicht bessere Erkennung:
Der Engpass ist nicht die Auswahl der Kriterien, sondern das Urteil an der
ausgewählten Stelle.

## Warum die Einordnung eine gute Frage ans Modell ist

Ansätze, die ein Merkmal im **Kundendokument** suchten, scheiterten, weil
Herstellernamen dort überall stehen. Diese Frage geht an **unseren** Standard —
kurze Abschnitte, eine Aussage über einen einzelnen Text statt einer
relationalen über zwei. Genau die Art, die ein kleines Modell kann.

Und sie wird **einmal** bezahlt, nicht je Dokument.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.verzeichnisse import DATA_DIR

DATENDIR = DATA_DIR
HALTUNGSDATEI = DATENDIR / "Standard_Herstellerhaltung.json"

KLASSEN = ("VORGESCHRIEBEN", "DELEGIERT", "SCHWEIGT")

# Nur diese beiden Klassen kommen in den Vorfilter. SCHWEIGT liegt mit 0,46x
# unter der Grundrate und umfasst 58 der 67 Kriterien — als Filter wertlos.
VORFILTER_KLASSEN = ("DELEGIERT", "VORGESCHRIEBEN")

_ERSATZSTELLE = ("Der Standard spricht an dieser Stelle ausdrücklich über die "
                 "Wahl von Hersteller, Fabrikat oder Lieferant.")

PROMPT = """Du liest EINEN Abschnitt aus einem Musterlastenheft für
Druckgießwerkzeuge. Beantworte eine einzige Frage darüber, wie dieser Abschnitt
mit der Wahl von Herstellern, Fabrikaten und Typen umgeht.

Du beurteilst NICHT, ob der Abschnitt gut ist. Du liest nur ab, was dasteht.

ABSCHNITT {nr} — {titel}

{standard}

## Die Frage

Welche der drei Aussagen trifft auf diesen Abschnitt zu?

VORGESCHRIEBEN — Der Abschnitt nennt selbst einen oder mehrere Hersteller,
Fabrikate oder Normteil-Lieferanten, oder verlangt ausdrücklich Erzeugnisse aus
einer freigegebenen Liste.

DELEGIERT — Der Abschnitt sagt ausdrücklich, dass die Wahl beim Auftraggeber
liegt, vereinbart, abgestimmt oder freigegeben wird.

SCHWEIGT — Der Abschnitt beschreibt die Anforderung sachlich und sagt zu
Herstellern oder Fabrikaten überhaupt nichts. Weder nennt er welche, noch
delegiert er die Wahl.

Antworte NUR mit diesem JSON, ohne weiteren Text:

{{"einordnung": "VORGESCHRIEBEN" oder "DELEGIERT" oder "SCHWEIGT", "beleg": "die Wörter aus dem Abschnitt, auf die du dich stützt, oder leer bei SCHWEIGT"}}"""


def fingerabdruck(standard: dict[str, dict]) -> str:
    """Kennung des Standardinhalts — ändert er sich, ist die Einordnung alt.

    Das Musterlastenheft lässt sich in der Oberfläche austauschen. Eine
    Einordnung, die zu einem anderen Standard gehört, wäre schlimmer als keine:
    Sie sähe gültig aus und filterte nach Sätzen, die nicht mehr dort stehen.
    """
    h = hashlib.sha256()
    for nr in sorted(standard):
        h.update(nr.encode("utf-8"))
        h.update(json.dumps(standard[nr], sort_keys=True,
                            ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:16]


def laden(standard: dict[str, dict]) -> dict[str, dict] | None:
    """Die gespeicherte Einordnung — oder None, wenn sie fehlt oder veraltet ist."""
    if not standard or not HALTUNGSDATEI.exists():
        return None
    try:
        daten = json.loads(HALTUNGSDATEI.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if daten.get("fingerabdruck") != fingerabdruck(standard):
        return None
    eintraege = daten.get("kriterien")
    return eintraege if isinstance(eintraege, dict) and eintraege else None


def speichern(standard: dict[str, dict], kriterien: dict[str, dict]) -> None:
    from src.dateien import schreibe_json
    schreibe_json(HALTUNGSDATEI, {
        "fingerabdruck": fingerabdruck(standard),
        "kriterien": kriterien,
    }, indent=1)


def vorfilter(standard: dict[str, dict]) -> dict[str, str] | None:
    """Kriteriumsnummer -> Belegstelle, für DELEGIERT und VORGESCHRIEBEN.

    None heißt: keine brauchbare Einordnung vorhanden. Der Aufrufer nimmt dann
    den Regex-Weg — lieber der schwächere Filter als gar keine Hinweise.
    """
    eintraege = laden(standard)
    if not eintraege:
        return None
    return {nr: (v.get("beleg") or "").strip() or _ERSATZSTELLE
            for nr, v in eintraege.items()
            if v.get("einordnung") in VORFILTER_KLASSEN}


def einordnen(standard: dict[str, dict], kriterien: list[dict],
              model: str, chat, num_predict: int = 200,
              fortschritt=None) -> dict[str, dict]:
    """Ein Aufruf je Kriterium. Ergebnis wird gespeichert und zurückgegeben."""
    from src.muster.anwendungsfeld import uebertragen
    from src.pruefung.kriterien import _first_json, _format_standard

    erg: dict[str, dict] = {}
    for i, k in enumerate(kriterien, start=1):
        nr = k["nr"]
        if fortschritt:
            fortschritt(i, len(kriterien), f"{nr} {k['titel']}")
        antwort = chat(model, uebertragen(PROMPT, format_sicher=True).format(
            nr=nr, titel=k["titel"],
            standard=_format_standard(k, standard.get(nr), "", False)),
            num_predict)
        wert, beleg = "SCHWEIGT", ""
        if antwort.ok:
            blob = _first_json(antwort.text)
            if blob:
                try:
                    d = json.loads(blob)
                    gelesen = str(d.get("einordnung", "")).strip().upper()
                    if gelesen in KLASSEN:
                        wert = gelesen
                        beleg = str(d.get("beleg") or "")[:200]
                except json.JSONDecodeError:
                    pass
        # Ein gescheiterter Aufruf landet als SCHWEIGT und damit AUSSERHALB des
        # Vorfilters. Das ist die vorsichtige Richtung: ein Kriterium zu viel
        # zu übergehen kostet einen möglichen Hinweis, eines zu viel zu fragen
        # kostet Laufzeit bei jedem Dokument.
        erg[nr] = {"einordnung": wert, "beleg": beleg}
    speichern(standard, erg)
    return erg
