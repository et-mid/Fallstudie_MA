"""Referenzbeispiele je Kriterium: zeigen, wo bei GENAU diesem Kriterium die Grenze liegt.

Der größte Fehlerposten ist ein `N`, obwohl der Kunde regelt. Die Nachprüfung
zeigte die eigentliche Schwierigkeit: nicht das Finden der Stelle, sondern die
Grenze zwischen „regelt diesen Sachverhalt" und „berührt ein Nachbarthema".
Diese Grenze kennt das Modell nicht — sie
steckt in den Bewertungen, die ein Fachmann für andere Lastenhefte vergeben hat.

Dieser Baustein legt dem Modell deshalb je Kriterium zwei bis drei Fälle aus
anderen, bewerteten Lastenheften vor: die Stelle, den Status und die Begründung
der Referenz. Anders als allgemeine Abweichungsbeispiele betreffen sie dasselbe
Kriterium.

Quellen, beide lokal:
- Referenzbewertungen (GT_ABGLEICH in src/verzeichnisse.py) — Status,
  Begründung, Fundstelle;
- Praxisarchiv (data/praxis_index/metadata.json) — der Text der zitierten Seite.

Das geprüfte Dokument selbst liefert nie ein Beispiel. Dokumentkennungen werden
entfernt, damit sie nicht in Begründungen wandern.

Im Betrieb kämen die Beispiele aus früher bewerteten Lastenheften der Firma.

Erprobt und verworfen: kein messbarer Effekt. Der Schalter bleibt aus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.verzeichnisse import DATA_DIR, GT_ABGLEICH

GT_DATEI = GT_ABGLEICH
ARCHIV_META = DATA_DIR / "praxis_index" / "metadata.json"

JE_KRITERIUM = 3
MAX_STELLE = 320
MAX_BEGRUENDUNG = 220

KOPF = """
SO WURDE DIESES KRITERIUM IN ANDEREN LASTENHEFTEN EINGESTUFT
(zur Orientierung, wo bei diesem Kriterium die Grenze liegt. Bewerte ausschließlich
die Stellen des geprüften Lastenhefts unten und übernimm keine Inhalte aus diesen
Beispielen.)"""

_KENNUNG = re.compile(r"\(?\bLHD-[\d,]+\)?", re.I)
_REIHENFOLGE = ("E", "T", "A")


def _woerter(text: str) -> set[str]:
    return set(re.findall(r"[a-zäöüß]{5,}", (text or "").lower()))


def _kurz(text: str, n: int) -> str:
    text = " ".join(_KENNUNG.sub("", text or "").split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


class Referenzbeispiele:
    """Lädt einmal je Prüflauf; `block(nr, ohne)` liefert den Prompt-Baustein."""

    def __init__(self, gt_pfad: Path | None = None, archiv_meta: Path | None = None):
        self.dokumente: dict = {}
        self.seiten: dict[tuple[str, int], list[str]] = {}
        try:
            gt = json.loads((gt_pfad or GT_DATEI).read_text(encoding="utf-8"))
            self.dokumente = gt.get("dokumente") or {}
        except (OSError, json.JSONDecodeError):
            pass
        try:
            for m in json.loads((archiv_meta or ARCHIV_META).read_text(encoding="utf-8")):
                self.seiten.setdefault((m["lh_id"], int(m["seite"])), []).append(m["text"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            pass

    def __bool__(self) -> bool:
        return bool(self.dokumente)

    def _stelle(self, lh: str, fundstelle: str, begruendung: str) -> str:
        """Der Abschnitt der zitierten Seite, der der Begründung am nächsten ist."""
        from src.praxis.dokumentvergleich import ist_schrott
        from src.pruefung.kriterien import ist_verzeichnis

        ziel = _woerter(begruendung)
        beste, wert = "", -1
        for seite in re.findall(r"\d+", fundstelle or ""):
            for text in self.seiten.get((lh, int(seite)), []):
                # Verzeichnisse und Zeichenfeld-Reste zeigen die Grenze nicht.
                if ist_verzeichnis(text) or ist_schrott(text):
                    continue
                w = len(ziel & _woerter(text))
                if w > wert:
                    beste, wert = text, w
        return beste if wert > 0 else ""

    def beispiele(self, nr: str, ohne: set[str], n: int = JE_KRITERIUM) -> list[dict]:
        kandidaten = []
        for lh in sorted(self.dokumente):
            if lh in ohne:
                continue
            b = (self.dokumente[lh].get("bewertungen") or {}).get(nr) or {}
            if b.get("status") not in _REIHENFOLGE or not b.get("begruendung"):
                continue
            stelle = self._stelle(lh, b.get("fundstelle", ""), b["begruendung"])
            if stelle:
                kandidaten.append({"status": b["status"], "begruendung": b["begruendung"],
                                   "stelle": stelle})
        # Je Status eines, in der Reihenfolge E, T, A — dann mit E auffüllen.
        gewaehlt = []
        for s in _REIHENFOLGE:
            treffer = next((k for k in kandidaten if k["status"] == s), None)
            if treffer:
                gewaehlt.append(treffer)
        for k in kandidaten:
            if len(gewaehlt) >= n:
                break
            if k not in gewaehlt:
                gewaehlt.append(k)
        return gewaehlt[:n]

    def block(self, nr: str, ohne: set[str]) -> str:
        teile = []
        for i, b in enumerate(self.beispiele(nr, ohne), start=1):
            teile.append(f"\nBeispiel {i} — Status {b['status']}\n"
                         f"Stelle: „{_kurz(b['stelle'], MAX_STELLE)}“\n"
                         f"Einstufung: {_kurz(b['begruendung'], MAX_BEGRUENDUNG)}")
        return (KOPF + "".join(teile) + "\n") if teile else ""
