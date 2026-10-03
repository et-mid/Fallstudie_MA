"""Die Prüfung als Hintergrundauftrag — unabhängig von der Browserseite.

Vorher lief die Prüfung im Streamlit-Skript selbst, 10 bis 20 Minuten lang. Jede
Bedienung währenddessen — ein anderes Auswahlfeld, ein Klick im Nachbarreiter —
löste einen Neuaufbau der Seite aus, und Streamlit beendete das laufende Skript
beim nächsten Fortschrittsbalken. Die Arbeit war ohne jede Meldung verloren.

Jetzt legt die Oberfläche einen Auftrag an und startet dafür einen eigenen
Prozess (`python main.py pruefauftrag <ordner>`), wie beim Musteraufbau. Die Seite
liest nur noch den Fortschritt. Sie darf neu aufgebaut, geschlossen und wieder
geöffnet werden; das Ergebnis liegt danach im Auftragsordner und lässt sich
jederzeit wieder öffnen — ein Verlauf früherer Prüfungen ohne Neurechnung.

    output/pruefungen/<zeit>_<datei>/
        einstellungen.json   Modell, Schwelle, Markierung, Dateiname
        eingabe.<endung>     Kopie des Kundenlastenhefts, nach dem Lauf gelöscht
        fortschritt.json     Zustand, Schritt, Text, Prozesskennung
        puls                 Lebenszeichen des Prozesses, alle paar Sekunden
        ergebnis.json        Ergebnis, Mitschnitt, Suchstatistik
        protokoll.txt        Ausgaben des Prozesses

Ob der Prozess noch lebt, sagt das Lebenszeichen, nicht der Fortschritt: Die
Texterkennung eines langen Scans meldet minutenlang keinen Schritt. Ein eigener
Faden schreibt deshalb unabhängig vom Fortschritt die Uhrzeit mit.

`output/` ist nicht versioniert: Die Ergebnisse enthalten Auszüge aus dem
Kundendokument (siehe .gitignore).
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from src.dateien import schreibe_bytes, schreibe_json, schreibe_text
from src.verzeichnisse import BASIS, OUTPUT_DIR

AUFTRAEGE_DIR = OUTPUT_DIR / "pruefungen"

# Lebenszeichen: alle PULS_TAKT Sekunden. Bleibt es länger als PULS_GRENZE aus,
# gilt der Prozess als beendet. Bis zum ersten Lebenszeichen darf der Start
# ANLAUF Sekunden dauern — Python lädt vorher torch und das Einbettungsmodell.
PULS_TAKT = 5
PULS_GRENZE = 60
ANLAUF = 180

LAUFEND = ("wartet", "laeuft")


@dataclass(frozen=True)
class Auftrag:
    ordner: Path

    @property
    def name(self) -> str:
        return self.ordner.name

    @property
    def einstellungen(self) -> Path:
        return self.ordner / "einstellungen.json"

    @property
    def fortschritt(self) -> Path:
        return self.ordner / "fortschritt.json"

    @property
    def puls(self) -> Path:
        return self.ordner / "puls"

    @property
    def ergebnis(self) -> Path:
        return self.ordner / "ergebnis.json"

    @property
    def protokoll(self) -> Path:
        return self.ordner / "protokoll.txt"

    def eingabe(self) -> Path | None:
        return next(iter(sorted(self.ordner.glob("eingabe.*"))), None)

    def lesen(self, pfad: Path, vorgabe=None):
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return vorgabe


def _sicherer_name(dateiname: str) -> str:
    stamm = Path(dateiname).stem
    return re.sub(r"[^\w,.-]+", "_", stamm).strip("._")[:60] or "lastenheft"


def anlegen(dateiname: str, daten: bytes, einstellungen: dict) -> Auftrag:
    """Legt einen Auftrag an. Gestartet wird er mit `starten` (oder `ausfuehren`)."""
    basis = AUFTRAEGE_DIR
    stamm = f"{time.strftime('%Y%m%d-%H%M%S')}_{_sicherer_name(dateiname)}"
    ordner, n = basis / stamm, 1
    while ordner.exists():
        n += 1
        ordner = basis / f"{stamm}_{n}"
    ordner.mkdir(parents=True)
    auftrag = Auftrag(ordner)
    endung = Path(dateiname).suffix.lower() or ".pdf"
    schreibe_bytes(ordner / f"eingabe{endung}", daten)
    schreibe_json(auftrag.einstellungen, {**einstellungen, "datei": Path(dateiname).name,
                                          "angelegt": time.time()})
    melden(auftrag, zustand="wartet", text="Wird gestartet …", schritt=0, gesamt=1)
    return auftrag


def melden(auftrag: Auftrag, **felder) -> None:
    stand = auftrag.lesen(auftrag.fortschritt, {}) or {}
    stand.update(felder, aktualisiert=time.time())
    schreibe_json(auftrag.fortschritt, stand)


def starten(auftrag: Auftrag) -> subprocess.Popen:
    """Startet den Auftrag als eigenen Prozess. Kehrt sofort zurück."""
    with auftrag.protokoll.open("a", encoding="utf-8") as protokoll:
        return subprocess.Popen(
            [sys.executable, str(BASIS / "main.py"), "pruefauftrag", str(auftrag.ordner)],
            cwd=str(BASIS), stdout=protokoll, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt")


def _fortschrittstext(schritt: int, gesamt: int, label: str) -> str:
    # Nach den Kriterien zählen Hinweis-Durchgang und Zusatzanforderungen neu;
    # eine Fortschrittsangabe über die Kriterien wäre dort falsch.
    if label.startswith(("Hinweise", "Zusatzanforderungen", "Nachprüfung")):
        return f"{label} ({schritt} von {gesamt})"
    return f"Kriterium {schritt} von {gesamt} — {label}"


def ausfuehren(auftrag: Auftrag) -> bool:
    """Führt den Auftrag in DIESEM Prozess aus. Rückgabe: ob ein Ergebnis entstand.

    Der Hintergrundprozess ruft das über `main.py pruefauftrag` auf; die Tests
    rufen es direkt, damit die Attrappe des Sprachmodells greift.
    """
    from src.dokumente.pdf_loader import TextExtraktionsFehler, load_document
    from src.pruefung.kriterien import (MIN_SCORE, STANDARD_MODELL, evaluate_document,
                                        load_kriterien)

    halt = threading.Event()

    def pulsschlag():
        while not halt.is_set():
            try:
                schreibe_text(auftrag.puls, str(time.time()))
            except OSError:
                pass
            halt.wait(PULS_TAKT)

    faden = threading.Thread(target=pulsschlag, daemon=True)
    faden.start()
    e = auftrag.lesen(auftrag.einstellungen, {}) or {}
    melden(auftrag, zustand="laeuft", pid=os.getpid(), text="Lese das Lastenheft …")
    try:
        eingabe = auftrag.eingabe()
        if eingabe is None:
            raise TextExtraktionsFehler("Die Eingabedatei des Auftrags fehlt.")
        chunks = load_document(eingabe, kind="neu")
        for c in chunks:
            c.source_file = e.get("datei", eingabe.name)
        kriterien = load_kriterien()
        stem = Path(e.get("datei", eingabe.name)).stem
        statistik: dict = {}

        def fortschritt(schritt: int, gesamt: int, label: str = "") -> None:
            melden(auftrag, schritt=schritt, gesamt=gesamt,
                   text=_fortschrittstext(schritt, gesamt, label))

        ergebnis, details = evaluate_document(
            chunks, lh_id=stem, model=e.get("modell") or STANDARD_MODELL,
            min_score=e.get("min_score", MIN_SCORE), kriterien=kriterien,
            prompt_template=e.get("custom_prompt"), statistik=statistik,
            markierung=e.get("markierung", "gruendlich"),
            progress_callback=fortschritt)
        schreibe_json(auftrag.ergebnis, {
            "datei": e.get("datei"), "stem": stem, "ergebnis": ergebnis,
            "details": details, "kriterien": kriterien, "statistik": statistik,
            "abschnitte": len(chunks)}, indent=None)
        melden(auftrag, zustand="fertig", text="Fertig")
        return True
    except (TextExtraktionsFehler, ValueError) as fehler:
        melden(auftrag, zustand="fehler", fehler=str(fehler))
    except Exception as fehler:          # noqa: BLE001 — jeder Ausfall muss ankommen
        with auftrag.protokoll.open("a", encoding="utf-8") as p:
            p.write(traceback.format_exc())
        melden(auftrag, zustand="fehler", fehler=f"{type(fehler).__name__}: {fehler}")
    finally:
        halt.set()
        faden.join(timeout=2)
        _eingabe_loeschen(auftrag)
    return False


def _eingabe_loeschen(auftrag: Auftrag) -> None:
    """Die Kopie des Kundendokuments wird nach dem Lauf nicht mehr gebraucht."""
    eingabe = auftrag.eingabe()
    if eingabe is not None:
        try:
            eingabe.unlink()
        except OSError:
            pass


def _lebt(auftrag: Auftrag, stand: dict) -> bool:
    try:
        puls = float(auftrag.puls.read_text(encoding="utf-8"))
        return time.time() - puls < PULS_GRENZE
    except (OSError, ValueError):
        angelegt = float((auftrag.lesen(auftrag.einstellungen, {}) or {}).get("angelegt") or 0)
        return time.time() - angelegt < ANLAUF


def zustand(auftrag: Auftrag) -> dict:
    """Der Stand zum Anzeigen. `zustand` ist wartet, laeuft, fertig, fehler,
    abgebrochen oder abgestuerzt (lief, gibt aber kein Lebenszeichen mehr)."""
    stand = dict(auftrag.lesen(auftrag.fortschritt, {}) or {})
    stand.setdefault("zustand", "fehler")
    if stand["zustand"] in LAUFEND and not _lebt(auftrag, stand):
        stand["zustand"] = "abgestuerzt"
        stand["fehler"] = (f"Der Prüfprozess gibt seit über {PULS_GRENZE} s kein "
                           f"Lebenszeichen mehr. Protokoll: {auftrag.protokoll}")
    stand["laeuft"] = stand["zustand"] in LAUFEND
    return stand


def abbrechen(auftrag: Auftrag) -> None:
    """Beendet den Prozess eines laufenden Auftrags und vermerkt den Abbruch."""
    stand = zustand(auftrag)
    pid = stand.get("pid")
    if stand["laeuft"] and pid and int(pid) != os.getpid():
        try:
            os.kill(int(pid), signal.SIGTERM)    # unter Windows: TerminateProcess
        except OSError:
            pass
    melden(auftrag, zustand="abgebrochen", fehler="Vom Nutzer abgebrochen.")
    _eingabe_loeschen(auftrag)


def ergebnis_laden(auftrag: Auftrag) -> dict | None:
    daten = auftrag.lesen(auftrag.ergebnis)
    return daten if isinstance(daten, dict) and "ergebnis" in daten else None


def liste(n: int = 10) -> list[Auftrag]:
    """Die jüngsten Aufträge, neueste zuerst."""
    if not AUFTRAEGE_DIR.is_dir():
        return []
    ordner = sorted((p for p in AUFTRAEGE_DIR.iterdir() if p.is_dir()), reverse=True)
    return [Auftrag(p) for p in ordner[:n]]


def laufender() -> Auftrag | None:
    """Der jüngste Auftrag, der gerade läuft — zum Wiederanhängen nach einem Neuladen."""
    return next((a for a in liste(20) if zustand(a)["laeuft"]), None)
