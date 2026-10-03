"""Mehrere Musterlastenhefte hinterlegen und eines davon aktivieren.

Jedes Anwendungsfeld braucht seinen eigenen Maßstab — und sein eigenes
Praxisarchiv: Frühere Druckguss-Lastenhefte sind kein Vergleich für einen
Schaltschrank-Standard. Die Bibliothek hält deshalb je Musterlastenheft alles
beisammen, was zu ihm gehört.

## Bauform: data/ bleibt die Arbeitskopie des aktiven Eintrags

Prüfung, Import, Praxisarchiv, Kommandozeile und Tests lesen ihre Dateien aus
`data/`. Statt jeden dieser Wege auf einen wechselnden Ordner umzustellen, liegt
das aktive Musterlastenheft weiterhin dort; die Bibliothek kopiert beim
Aktivieren hinein und sichert vorher zurück, was sich im aktiven Stand geändert
hat (ein neu gebautes Archiv, eine Einordnung per `standardhaltung`, ein Import
über die Kommandozeile). Nichts, was bisher lief, muss davon wissen.

    data/standards/aktiv.txt            Schlüssel des aktiven Eintrags
    data/standards/<schlüssel>/
        eintrag.json                    Name, Anwendungsfeld, Kriterien, Stand
        musterlastenheft.docx           die Quelle
        Standard_Lastenheft_Chunks.jsonl
        struktur_kriterien.json
        Standard_Herstellerhaltung.json (falls eingeordnet)
        Standard_Entscheider.json       (falls kalibriert)
        praxis_index/                   (falls aufgebaut)
        historical/                     Ablageordner des Praxisarchivs
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.dateien import ersetze, schreibe_json, schreibe_text
from src.verzeichnisse import DATA_DIR as _DATA_DIR, STRUKTUR_NAME

DATA_DIR = _DATA_DIR
ORDNER = DATA_DIR / "standards"

# Was zu einem Musterlastenheft gehört und im aktiven Zustand in data/ liegt.
DATEIEN = ("Standard_Lastenheft_Chunks.jsonl", STRUKTUR_NAME,
           "Standard_Herstellerhaltung.json", "Standard_Entscheider.json")
VERZEICHNISSE = ("praxis_index",)


@dataclass
class Eintrag:
    schluessel: str
    name: str
    gegenstand: str
    kriterien: int
    stand: str
    aktiv: bool = False

    @property
    def ordner(self) -> Path:
        return _ordner() / self.schluessel

    @property
    def quelle(self) -> Path:
        return self.ordner / "musterlastenheft.docx"

    @property
    def historie(self) -> Path:
        return self.ordner / "historical"


def _ordner() -> Path:
    return ORDNER


def _daten() -> Path:
    return DATA_DIR


def schluessel_fuer(name: str) -> str:
    s = name.strip().lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(alt, neu)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "musterlastenheft"


def _lies(eintrag_ordner: Path, aktiv_schluessel: str | None) -> Eintrag | None:
    try:
        m = json.loads((eintrag_ordner / "eintrag.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return Eintrag(eintrag_ordner.name, m.get("name", eintrag_ordner.name),
                   m.get("gegenstand", ""), int(m.get("kriterien", 0)), m.get("stand", ""),
                   aktiv=eintrag_ordner.name == aktiv_schluessel)


def _aktiv_schluessel() -> str | None:
    try:
        return (_ordner() / "aktiv.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def eintraege() -> list[Eintrag]:
    sicherstellen()
    if not _ordner().exists():
        return []
    aktiv = _aktiv_schluessel()
    liste = [e for p in sorted(_ordner().iterdir()) if p.is_dir()
             for e in [_lies(p, aktiv)] if e]
    return sorted(liste, key=lambda e: e.name.lower())


def aktiver() -> Eintrag | None:
    return next((e for e in eintraege() if e.aktiv), None)


def historie_ordner() -> Path:
    """Ablageordner des Praxisarchivs — je Musterlastenheft ein eigener."""
    e = aktiver()
    ziel = e.historie if e else _daten() / "historical"
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def _kopieren(von: Path, nach: Path) -> None:
    """Datei oder Verzeichnis ersetzen; fehlt die Quelle, verschwindet das Ziel.

    Erst neben das Ziel kopieren, dann tauschen (src/dateien.py): Vorher wurde das
    Ziel zuerst gelöscht, und ein scheiterndes Kopieren ließ gar nichts zurück.
    """
    ersetze(von, nach)


def _meta_schreiben(ordner: Path, name: str) -> None:
    from src.muster.anwendungsfeld import aktuell, anzahl_kriterien

    struktur = ordner / STRUKTUR_NAME
    feld = aktuell(struktur)
    schreibe_json(ordner / "eintrag.json", {
        "name": name, "gegenstand": feld.gegenstand_mehrzahl,
        "kriterien": anzahl_kriterien(struktur),
        "stand": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }, indent=1)


def zuruecksichern() -> None:
    """Den aktiven Stand aus data/ in seinen Eintrag zurückschreiben."""
    schluessel = _aktiv_schluessel()
    if not schluessel or not (_ordner() / schluessel).exists():
        return
    for name in DATEIEN + VERZEICHNISSE:
        _kopieren(_daten() / name, _ordner() / schluessel / name)


def aktivieren(schluessel: str) -> Eintrag:
    ziel = _ordner() / schluessel
    if not (ziel / "eintrag.json").exists():
        raise KeyError(f"Kein hinterlegtes Musterlastenheft „{schluessel}“.")
    if _aktiv_schluessel() != schluessel:
        zuruecksichern()
        for name in DATEIEN + VERZEICHNISSE:
            _kopieren(ziel / name, _daten() / name)
        schreibe_text(_ordner() / "aktiv.txt", schluessel)
    return next(e for e in eintraege() if e.schluessel == schluessel)


def hinterlegen(name: str, kriterien: list[dict], anwendungsfeld, quelle: Path | None,
                aktivieren_danach: bool) -> Eintrag:
    """Legt ein Musterlastenheft unter `name` ab; gleicher Name ersetzt die Fassung.

    Praxisarchiv und Ablageordner eines ersetzten Eintrags bleiben erhalten —
    sie gehören zum Anwendungsfeld, nicht zur Fassung des Dokuments.
    """
    from src.muster.standard_import import schreibe_standard

    sicherstellen()
    schluessel = schluessel_fuer(name)
    ordner = _ordner() / schluessel
    ist_aktiv = _aktiv_schluessel() == schluessel
    if ist_aktiv:
        zuruecksichern()          # Archiv & Co. nicht mit dem alten Stand überschreiben
    ordner.mkdir(parents=True, exist_ok=True)
    schreibe_standard(kriterien, ordner / DATEIEN[0], ordner / DATEIEN[1],
                      anwendungsfeld=anwendungsfeld)
    if quelle is not None and Path(quelle).exists():
        shutil.copy2(quelle, ordner / "musterlastenheft.docx")
    _meta_schreiben(ordner, name.strip())

    if ist_aktiv:
        # Nur die beiden Standard-Dateien; eine Einordnung der alten Fassung
        # verfällt von selbst am Fingerabdruck (src/pruefung/standardhaltung.py).
        for n in DATEIEN[:2]:
            _kopieren(ordner / n, _daten() / n)
    elif aktivieren_danach or not _aktiv_schluessel():
        aktivieren(schluessel)
    return next(e for e in eintraege() if e.schluessel == schluessel)


def entfernen(schluessel: str) -> None:
    if _aktiv_schluessel() == schluessel:
        raise ValueError("Das aktive Musterlastenheft lässt sich nicht entfernen — "
                         "erst ein anderes aktivieren.")
    ziel = _ordner() / schluessel
    if (ziel / "eintrag.json").exists():
        shutil.rmtree(ziel)


def sicherstellen() -> None:
    """Übernimmt beim ersten Start das bisher hinterlegte Musterlastenheft.

    Vor der Bibliothek gab es genau eines, direkt in data/. Es wird zum ersten
    Eintrag und bleibt aktiv — für den Anwender ändert sich nichts.
    """
    if (_ordner() / "aktiv.txt").exists():
        return
    daten = _daten()
    if not (daten / DATEIEN[0]).exists() or not (daten / DATEIEN[1]).exists():
        return
    from src.muster.anwendungsfeld import aktuell

    name = aktuell(daten / DATEIEN[1]).gegenstand_mehrzahl or "Musterlastenheft"
    schluessel = schluessel_fuer(name)
    ordner = _ordner() / schluessel
    ordner.mkdir(parents=True, exist_ok=True)
    for n in DATEIEN + VERZEICHNISSE:
        _kopieren(daten / n, ordner / n)
    muster = sorted((daten / "muster").glob("*.docx"), key=lambda p: p.stat().st_mtime)
    if muster:
        shutil.copy2(muster[-1], ordner / "musterlastenheft.docx")
    alt_historie = daten / "historical"
    if alt_historie.is_dir() and any(alt_historie.iterdir()):
        shutil.copytree(alt_historie, ordner / "historical", dirs_exist_ok=True)
    _meta_schreiben(ordner, name)
    (_ordner() / "aktiv.txt").write_text(schluessel, encoding="utf-8")
