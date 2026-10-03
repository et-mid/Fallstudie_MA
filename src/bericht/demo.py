"""Demo-Modus: einen aufgezeichneten Lauf abspielen statt zu rechnen.

Zweck ist das Vorführen ohne Ollama — auf einem Rechner, auf dem kein Modell
läuft, und ohne dass ein Kundendokument geöffnet werden muss.

Drei Festlegungen, die den Demo-Modus ehrlich halten:

**Es ist ein echter Lauf.** `demo/beispiellauf.json` entsteht aus
`demo/erzeuge_lauf.py`, das die reguläre Prüfung über ein erfundenes
Lastenheft laufen lässt. Bewertungen, Kennzahlen, Hinweise und der komplette
Mitschnitt stammen aus diesem Lauf. Am Ergebnis wird nichts nachbearbeitet —
fällt eine Einstufung anders aus als gewünscht, wird das Beispieldokument
geändert, nie die Ausgabe.

**Der Inhalt ist erfunden.** Firma, Werknormen, Fabrikate und Werte im
Beispieldokument sind ausgedacht. Es enthält keinen Satz aus einem
Kundenlastenheft und darf deshalb überall gezeigt werden.

**Es wird dieselbe Anzeige benutzt.** Der Demo-Modus ruft `_render_bericht`
auf, also genau die Funktion, die auch ein gerechneter Lauf benutzt. Eine
nachgebaute Ansicht würde irgendwann etwas anderes zeigen als die Software.
"""

import json
from pathlib import Path

from src.verzeichnisse import DEMO_DIR

DEMODATEI = DEMO_DIR / "beispiellauf.json"


def verfuegbar() -> bool:
    """Liegt ein aufgezeichneter Lauf vor?"""
    return DEMODATEI.exists()


def laden() -> dict | None:
    """Der aufgezeichnete Lauf, oder None wenn er fehlt oder unlesbar ist.

    Ein beschädigter Mitschnitt darf die Anwendung nicht abbrechen: Ohne Demo
    ist sie vollständig benutzbar, mit einer Ausnahme beim Start nicht.
    """
    if not DEMODATEI.exists():
        return None
    try:
        daten = json.loads(DEMODATEI.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(daten, dict) or "ergebnis" not in daten:
        return None
    daten.setdefault("details", {})
    return daten


def abschnitte(daten: dict) -> int:
    """Wie viele Textabschnitte lagen dem Lauf zugrunde?

    Aus dem Mitschnitt gezählt statt mitgespeichert: Die Fundstellen sind die
    einzige Quelle, die auch dann stimmt, wenn der Lauf aus einer früheren
    Fassung stammt.
    """
    gesehen = set()
    for d in (daten.get("details") or {}).values():
        for k in (d.get("kandidaten") or []):
            gesehen.add((k.get("page"), (k.get("text") or "")[:40]))
    return len(gesehen)
