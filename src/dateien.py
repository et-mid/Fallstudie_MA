"""Dateien so schreiben, dass nie eine halbe Datei liegen bleibt.

Ein Absturz, Strg+C oder ein voller Datenträger während `write_text` hinterließ
bisher eine abgeschnittene Datei. Beim Messlauf war das besonders teuer: Der
nächste Aufruf las den Zwischenstand als unlesbar, begann von vorn und
überschrieb eine Stunde Arbeit.

Deshalb wird erst neben das Ziel geschrieben und dann in einem Schritt ersetzt
(`os.replace` ist auf Windows wie auf POSIX atomar, solange beide Pfade auf
demselben Laufwerk liegen — hier immer derselbe Ordner). Das Vorbild ist
`Arbeitsstand.schreiben` im Musteraufbau.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _tmp(pfad: Path) -> Path:
    return pfad.with_name(f".{pfad.name}.{os.getpid()}.tmp")


def schreibe_bytes(pfad: Path, daten: bytes) -> Path:
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(pfad)
    try:
        with open(tmp, "wb") as f:
            f.write(daten)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pfad)
    finally:
        if tmp.exists():
            tmp.unlink()
    return pfad


def schreibe_text(pfad: Path, text: str) -> Path:
    return schreibe_bytes(pfad, text.encode("utf-8"))


def schreibe_json(pfad: Path, daten, indent: int | None = 2) -> Path:
    return schreibe_text(pfad, json.dumps(daten, ensure_ascii=False, indent=indent))


def speichere_npy(pfad: Path, matrix) -> Path:
    """numpy-Array atomar ablegen (np.save hängt sonst eigenmächtig .npy an)."""
    import io

    import numpy as np

    puffer = io.BytesIO()
    np.save(puffer, matrix)
    return schreibe_bytes(pfad, puffer.getvalue())


def ersetze(von: Path, nach: Path) -> None:
    """Datei oder Verzeichnis `nach` durch eine Kopie von `von` ersetzen.

    Fehlt `von`, verschwindet `nach`. Erst wird neben das Ziel kopiert, dann
    getauscht: Scheitert das Kopieren, bleibt das bisherige Ziel unberührt.
    """
    von, nach = Path(von), Path(nach)
    if von.is_dir():
        neu = nach.with_name(f".{nach.name}.neu")
        alt = nach.with_name(f".{nach.name}.alt")
        for rest in (neu, alt):
            if rest.exists():
                shutil.rmtree(rest)
        shutil.copytree(von, neu)
        if nach.is_dir():
            nach.rename(alt)
        elif nach.exists():
            nach.unlink()
        neu.rename(nach)
        if alt.exists():
            shutil.rmtree(alt, ignore_errors=True)
    elif von.exists():
        nach.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp(nach)
        try:
            shutil.copy2(von, tmp)
            if nach.is_dir():
                shutil.rmtree(nach)
            os.replace(tmp, nach)
        finally:
            if tmp.exists():
                tmp.unlink()
    else:
        if nach.is_dir():
            shutil.rmtree(nach)
        elif nach.exists():
            nach.unlink()
