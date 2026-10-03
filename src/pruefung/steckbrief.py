"""Unter welchen Bedingungen ist dieses Ergebnis entstanden?

Ein Ergebnis hielt bisher fest, WAS herauskam — nicht, WOMIT. Modell,
Einbettungsmodell, Prompt, Stand des Musterlastenhefts und die
gesetzten Schalter standen allenfalls im Dateinamen. Für eine Arbeit, deren
Kern der Vergleich vieler Läufe ist, ist das die empfindlichste Lücke: Zwei
Zahlen lassen sich nur dann gegeneinanderstellen, wenn belegt ist, dass sich
genau eine Bedingung unterschied.

Das Vorbild ist das Snapshot-Manifest aus DocMind AI (Korpus-Hash,
Konfigurations-Hash, Komponentenversionen). Übernommen ist der Gedanke, nicht
der Umfang: Hier genügt ein flaches Feld im Ergebnis.

Zwei Festlegungen:

**Der Steckbrief geht nicht in die Kennzahlen ein.** Er steht neben dem
Ergebnis, wie die Hinweise. Läufe von vor seiner Einführung bleiben lesbar;
wer ihn nicht findet, weiß nur weniger, bekommt aber keinen Fehler.

**Der Fingerabdruck deckt den Standard ab, nicht die Kundendokumente.** Er
entsteht aus dem Musterlastenheft, das im Repository ohnehin nicht liegt; die
Kennung selbst verrät keinen Inhalt. Kundendaten fasst dieses Modul nicht an.
"""

import hashlib
import platform
import sys
from datetime import datetime, timezone

FASSUNG = 1


def _kurz_hash(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def erstelle(*, modell: str, standard: dict,
             prompt_template: str, schalter: dict,
             n_fundstellen: int, min_score: float,
             lexikalisches_gewicht: float,
             abschnitte: int, einbettungsmodell: str) -> dict:
    """Der Steckbrief eines Laufs.

    Absichtlich flach und aus Zeichenketten und Zahlen aufgebaut: Er soll sich
    in einer Tabelle vergleichen lassen, ohne dass man ihn auspacken muss.
    """
    from src.pruefung.standardhaltung import fingerabdruck

    return {
        "fassung": FASSUNG,
        "zeitpunkt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modell": modell,
        "einbettungsmodell": einbettungsmodell,
        # Die Prompt-Vorlage selbst wandert nicht ins Ergebnis — sie ist lang
        # und steht ohnehin im Code. Der Hash beantwortet die Frage, die man
        # später stellt: War es derselbe Prompt wie im Lauf davor?
        "prompt_hash": _kurz_hash(prompt_template),
        "standard_fingerabdruck": fingerabdruck(standard),
        "kriterien": len(standard),
        # Nur die gesetzten Schalter. Die Vorgabe ist bei allen „aus"; eine
        # Liste von zehn False-Werten verdeckt den einen, auf den es ankommt.
        "schalter": sorted(k for k, v in schalter.items() if v),
        "n_fundstellen": n_fundstellen,
        "min_score": round(float(min_score), 4),
        "lexikalisches_gewicht": round(float(lexikalisches_gewicht), 4),
        "abschnitte": abschnitte,
        "python": platform.python_version(),
        "plattform": sys.platform,
    }


def vergleiche(a: dict, b: dict) -> list[str]:
    """Worin unterscheiden sich zwei Läufe? Feldnamen, sonst nichts.

    Der Sinn ist die Kontrollfrage vor jedem A/B-Vergleich: Hat sich wirklich
    nur die eine Bedingung geändert? Eine leere Liste heißt, die Läufe sind
    unter denselben Bedingungen entstanden — der Zeitpunkt zählt nicht mit.
    """
    egal = {"zeitpunkt", "fassung"}
    felder = (set(a or {}) | set(b or {})) - egal
    return sorted(f for f in felder if (a or {}).get(f) != (b or {}).get(f))


def laufbedingungen(ergebnis: dict) -> list[tuple[str, str]]:
    """Die Bedingungen eines Laufs zum Lesen, als (Bezeichnung, Wert).

    Für Oberfläche und Excel-Bericht dieselben Zeilen: Wer einen Bericht liest,
    soll sehen, womit er entstanden ist — vor allem, ob der Entscheider mitlief.
    Fällt er aus (anderes Musterlastenheft, andere Sucheinstellungen), sinkt die
    Trefferquote spürbar, und bisher stand das nur im Rohergebnis. Ältere
    Ergebnisse ohne Steckbrief liefern, was vorhanden ist.
    """
    from src.pruefung import entscheider as EN
    from src.pruefung.markierung import STUFEN_TEXT

    s = ergebnis.get("steckbrief") or {}
    zeilen: list[tuple[str, str]] = []
    if s.get("modell"):
        zeilen.append(("Sprachmodell", str(s["modell"])))
    if ergebnis.get("markierung"):
        zeilen.append(("Abweichungsmarkierung",
                       STUFEN_TEXT.get(ergebnis["markierung"], ergebnis["markierung"])))
    stand, text = EN.zustand(ergebnis)
    if stand != "unbekannt":
        zeilen.append(("Entscheider", {"aktiv": f"aktiv — {text}",
                                       "nicht_aktiv": f"NICHT AKTIV — {text}",
                                       "aus": "abgeschaltet"}[stand]))
    if s.get("standard_fingerabdruck"):
        zeilen.append(("Musterlastenheft",
                       f"Kennung {s['standard_fingerabdruck']} · {s.get('kriterien', '?')} Kriterien"))
    if s.get("n_fundstellen") is not None:
        zeilen.append(("Suche", f"{s['n_fundstellen']} Fundstellen je Kriterium, Schwelle "
                                f"{s.get('min_score')} · {s.get('einbettungsmodell', '')}"))
    if s.get("zeitpunkt"):
        try:
            zeit = datetime.fromisoformat(s["zeitpunkt"]).astimezone()
            zeilen.append(("Geprüft", zeit.strftime("%d.%m.%Y %H:%M")))
        except ValueError:
            zeilen.append(("Geprüft", str(s["zeitpunkt"])))
    return zeilen
