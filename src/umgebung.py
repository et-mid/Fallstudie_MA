"""Prüft die Voraussetzungen und formuliert sie für Menschen ohne IT-Kenntnisse.

Drei Dinge müssen stimmen, damit eine Prüfung funktioniert: das Sprachmodell
muss laufen, die Texterkennung muss installiert sein, und ein Musterlastenheft
muss hinterlegt sein. Fehlt eines davon, soll die Oberfläche nicht mit einem
technischen Fehler abbrechen, sondern sagen, was zu tun ist.
"""

from dataclasses import dataclass

from src.pruefung.kriterien import STANDARD_MODELL, load_kriterien, load_standard
from src.dokumente.pdf_loader import ocr_status


@dataclass
class Pruefpunkt:
    """Ergebnis einer einzelnen Voraussetzungsprüfung."""
    name:     str
    ok:       bool
    meldung:  str
    hinweis:  str = ""      # was der Nutzer tun soll, wenn es nicht ok ist
    blockend: bool = True   # ohne das geht gar nichts


def pruefe_ollama() -> Pruefpunkt:
    """Läuft das Sprachmodell-Programm und ist mindestens ein Modell da?"""
    try:
        import ollama
        antwort = ollama.list()
    except Exception:
        return Pruefpunkt(
            "Sprachmodell", False,
            "Ollama ist nicht erreichbar.",
            "Ollama starten — unter Windows über das Startmenü. "
            "Ohne Ollama kann keine Prüfung laufen.")

    roh = antwort["models"] if isinstance(antwort, dict) else antwort.models
    namen = []
    for m in roh:
        name = getattr(m, "model", None) or getattr(m, "name", None)
        if name is None and isinstance(m, dict):
            name = m.get("model") or m.get("name")
        if name:
            namen.append(name)

    if not namen:
        return Pruefpunkt(
            "Sprachmodell", False,
            "Ollama läuft, aber es ist kein Modell installiert.",
            f"Ein Modell laden, mit dem Befehl: ollama pull {STANDARD_MODELL}")

    return Pruefpunkt("Sprachmodell", True, f"Ollama · {len(namen)} Modell(e)")


def pruefe_ocr() -> Pruefpunkt:
    """Ist Texterkennung für gescannte Lastenhefte möglich?"""
    ok, meldung = ocr_status()
    if ok:
        return Pruefpunkt("Texterkennung", True, meldung)
    return Pruefpunkt(
        "Texterkennung", False,
        "Texterkennung ist nicht verfügbar.",
        meldung + " Ohne sie lassen sich nur Lastenhefte prüfen, die bereits "
                  "Text enthalten — eingescannte Dokumente nicht.",
        blockend=False)


def pruefe_standard() -> Pruefpunkt:
    """Ist ein Musterlastenheft hinterlegt?"""
    standard  = load_standard()
    kriterien = load_kriterien() if standard else []

    if not standard:
        return Pruefpunkt(
            "Musterlastenheft", False,
            "Es ist kein Musterlastenheft hinterlegt.",
            "Im Tab „Musterlastenheft“ die Word-Datei hochladen. "
            "Sie ist der Maßstab, gegen den geprüft wird.")

    if len(standard) != len(kriterien):
        return Pruefpunkt(
            "Musterlastenheft", False,
            f"Musterlastenheft und Gliederung passen nicht zusammen "
            f"({len(standard)} gegenüber {len(kriterien)} Kriterien).",
            "Im Tab „Musterlastenheft“ die Word-Datei erneut hochladen und "
            "übernehmen. Dann werden beide gemeinsam neu erzeugt.")

    from src.muster.bibliothek import aktiver
    eintrag = aktiver()
    name = f"{eintrag.name} · " if eintrag else ""
    return Pruefpunkt("Musterlastenheft", True, f"{name}{len(standard)} Kriterien")


def pruefe_entscheider() -> Pruefpunkt | None:
    """Passt der gelernte Entscheider zum hinterlegten Musterlastenheft?

    Nicht blockierend: Die Prüfung läuft ohne ihn, aber spürbar schlechter. Nach
    einem neuen Import des Musterlastenhefts fällt er still aus —
    das soll man vor dem Start sehen, nicht erst im Rohergebnis. Ohne
    Musterlastenheft entfällt der Punkt (das meldet pruefe_standard).
    """
    standard = load_standard()
    if not standard:
        return None
    from src.pruefung import entscheider as EN
    modell, grund = EN.laden(standard)
    if modell is not None:
        return Pruefpunkt("Entscheider", True,
                          f"trainiert an {len(modell.get('dokumente') or [])} Lastenheften")
    return Pruefpunkt(
        "Entscheider", False, f"Entscheider nicht aktiv — {grund}.",
        "Die Prüfung läuft trotzdem, stuft aber mehr geregelte Punkte als „keine "
        "Vorgabe“ ein. Neu trainieren mit: "
        "python main.py kalibrieren <Ordner mit den bewerteten Lastenheften>",
        blockend=False)


def pruefe_alles() -> list[Pruefpunkt]:
    """Alle Voraussetzungen, blockierende zuerst."""
    punkte = [pruefe_ollama(), pruefe_standard(), pruefe_ocr()]
    entscheider = pruefe_entscheider()
    if entscheider is not None:
        punkte.append(entscheider)
    return sorted(punkte, key=lambda p: (p.ok, not p.blockend))


def bereit(punkte: list[Pruefpunkt]) -> bool:
    """Kann eine Prüfung überhaupt starten?"""
    return all(p.ok for p in punkte if p.blockend)
