"""Zerlegung entlang der Kapitelnummern des Lastenhefts.

Erprobt und nicht übernommen: kein Gewinn gegenüber der bisherigen Zerlegung.
Nicht angeschlossen.

Die bisherige Zerlegung (`pdf_loader._split_page`) sammelt Zeilen bis rund 500
Zeichen und schneidet am nächsten Zeilenende — egal, ob dort gerade Kapitel 4.6
endet und 4.7 beginnt. Ein Abschnitt kann so das Ende einer Anforderung und den
Anfang der nächsten tragen, und die Suche findet für 4.7 einen Block, der zur
Hälfte von 4.6 handelt.

Hier gilt zusätzlich: **Eine erkannte Kapitelüberschrift beginnt immer einen
neuen Abschnitt.** Alles andere bleibt wie bisher — Seitengrenze als harte
Grenze, dieselben Zielgrößen —, damit ein Vergleich nur die Grenzen misst und
nicht nebenbei die Abschnittslänge.

Die Schwierigkeit ist nicht das Schneiden, sondern das Erkennen. In den
Lastenheften steht vor vielen Zeilen eine Zahl, die keine Überschrift ist:
nummerierte Aufzählungen („1 Spannungsarmglühen …" unter 4.1), Tabellenwerte
(„66 D, SC D/66"), Inhaltsverzeichnisse, bei zweisprachigen Dokumenten dieselbe
Gliederung ein zweites Mal. Deshalb wird eine Nummer nur als Überschrift
angenommen, wenn sie ein **plausibler Nachfolger** der zuletzt angenommenen ist:
nächstes Geschwister, erstes Kind oder nächstes Kapitel einer höheren Ebene.
"""

import re
from pathlib import Path

from src.dokumente.pdf_loader import MAX_CHUNK, MIN_CHUNK, TARGET_CHUNK, DocumentChunk

# Nummer, optional mit Schlusspunkt, dann ein Titel, der mit einem Buchstaben beginnt.
_UEBERSCHRIFT = re.compile(
    r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Za-zÄÖÜäöü].*)$")

# Wie weit darf eine Nummer springen? Lastenhefte lassen Kapitel aus, und die
# Texterkennung verschluckt gelegentlich eine Überschrift.
_SPRUNG = 3


def _nummer(text: str) -> tuple[int, ...]:
    return tuple(int(t) for t in text.split("."))


def ist_nachfolger(alt: tuple[int, ...] | None, neu: tuple[int, ...]) -> bool:
    """Ist `neu` als nächste Überschrift nach `alt` plausibel?

    Erlaubt: nächstes Geschwister (4.6 → 4.7, bis zu _SPRUNG weiter), erstes
    Kind (4.7 → 4.7.1) und nächstes Kapitel einer höheren Ebene (4.7.3 → 4.8
    oder → 5). Nicht erlaubt ist jeder Rücksprung — genau daran scheitern
    Aufzählungen („1 … 2 … 3" unter 4.1) und die zweite Sprachfassung.
    """
    if alt is None:
        # Der Anfang: nur eine flache, kleine Nummer.
        return len(neu) <= 2 and 1 <= neu[0] <= _SPRUNG and all(n >= 1 for n in neu)
    if neu[:len(alt)] == alt and len(neu) == len(alt) + 1:
        return 1 <= neu[-1] <= 2
    for tiefe in range(len(alt), 0, -1):
        if len(neu) != tiefe or neu[:tiefe - 1] != alt[:tiefe - 1]:
            continue
        return alt[tiefe - 1] < neu[tiefe - 1] <= alt[tiefe - 1] + _SPRUNG
    return False


def _titel_plausibel(titel: str) -> bool:
    """Sieht der Rest der Zeile nach einem Titel aus?

    Verworfen werden Verzeichniszeilen (enden auf Punkte oder eine Seitenzahl)
    und Zeilen, in denen kaum Buchstaben stehen (Tabellen, Maße).
    """
    t = titel.strip()
    # Mindestens ein richtiges Wort — „ooF =", „u TH", „mm 18mm" sind OCR-Reste.
    if not re.search(r"[A-Za-zÄÖÜäöüß]{4,}", t):
        return False
    if re.search(r"(\.{3,}|…|\s\d{1,3})\s*$", t):
        return False
    buchstaben = sum(ch.isalpha() for ch in t)
    return buchstaben >= 3 and buchstaben >= 0.6 * len(t.replace(" ", ""))


_VERZEICHNISZEILE = re.compile(r"(\.{3,}|…|\s)\s*\d{1,3}\s*$")


def ist_verzeichnisseite(text: str) -> bool:
    """Eine Seite, deren Zeilen überwiegend auf eine Seitenzahl enden.

    Ohne diese Prüfung übernimmt die Erkennung die Nummernfolge des
    Inhaltsverzeichnisses, steht danach am Ende der Gliederung und lehnt jede
    echte Überschrift des Dokuments als Rücksprung ab.
    """
    zeilen = [z for z in (text or "").split("\n") if z.strip()]
    treffer = sum(bool(_VERZEICHNISZEILE.search(z)) for z in zeilen)
    return treffer >= 5 and treffer >= 0.3 * len(zeilen)


def ueberschriften(seiten: list[str]) -> list[tuple[int, int, str]]:
    """Alle angenommenen Überschriften als (Seitenindex, Zeilenindex, Nummer+Titel)."""
    gefunden = []
    zuletzt: tuple[int, ...] | None = None
    for s, text in enumerate(seiten):
        if ist_verzeichnisseite(text):
            continue
        for z, zeile in enumerate((text or "").split("\n")):
            m = _UEBERSCHRIFT.match(zeile)
            if not m or not _titel_plausibel(m.group(2)):
                continue
            nr = _nummer(m.group(1))
            if ist_nachfolger(zuletzt, nr):
                gefunden.append((s, z, f"{m.group(1)} {m.group(2).strip()}"))
                zuletzt = nr
    return gefunden


def _stuecke(zeilen: list[str]) -> list[str]:
    """Ein Kapitelstück einer Seite in Abschnitte der gewohnten Größe teilen.

    Dieselben Regeln wie `_split_page`: Leerzeile trennt, ab TARGET_CHUNK am
    Zeilenende trennen, über MAX_CHUNK hart schneiden.
    """
    teile, puffer, laenge = [], [], 0
    for roh in zeilen:
        zeile = roh.strip()
        if not zeile:
            if puffer:
                teile.append(" ".join(puffer))
            puffer, laenge = [], 0
            continue
        puffer.append(zeile)
        laenge += len(zeile) + 1
        if laenge >= TARGET_CHUNK:
            teile.append(" ".join(puffer))
            puffer, laenge = [], 0
    if puffer:
        teile.append(" ".join(puffer))

    gross = []
    for t in teile:
        gross.extend([t] if len(t) <= MAX_CHUNK
                     else [t[i:i + MAX_CHUNK].strip() for i in range(0, len(t), MAX_CHUNK)])
    # Kurze Reste an den Nachbarn im SELBEN Kapitel hängen, nie über die Grenze.
    zusammen: list[str] = []
    for t in gross:
        if zusammen and (len(t) < MIN_CHUNK or len(zusammen[-1]) < MIN_CHUNK):
            zusammen[-1] = f"{zusammen[-1]} {t}".strip()
        else:
            zusammen.append(t)
    return zusammen


def chunks_nach_gliederung(seiten: list[str], path: Path, kind: str = "neu",
                           ueberschrift_voran: bool = False) -> list[DocumentChunk]:
    """Wie `pdf_loader._chunks_from_pages`, aber mit Kapitelgrenzen.

    `ueberschrift_voran` stellt jedem Abschnitt die Überschrift seines Kapitels
    in eckigen Klammern voran — auch auf Folgeseiten. Das ist eine ZWEITE
    Änderung (der Abschnittstext ändert sich) und wird getrennt gemessen.

    Ein kurzer Kapitelrest (etwa eine alleinstehende Überschrift) wird hier
    NICHT verworfen, sondern ans nächste Stück desselben Kapitels gehängt;
    bleibt er allein unter MIN_CHUNK, fällt er wie bisher weg.
    """
    grenzen = {(s, z): titel for s, z, titel in ueberschriften(seiten)}
    chunks: list[DocumentChunk] = []
    kapitel = ""
    for s, text in enumerate(seiten):
        if not text:
            continue
        stueck: list[str] = []
        stuecke: list[tuple[str, list[str]]] = []
        for z, zeile in enumerate(text.split("\n")):
            if (s, z) in grenzen:
                if stueck:
                    stuecke.append((kapitel, stueck))
                kapitel, stueck = grenzen[(s, z)], []
            stueck.append(zeile)
        if stueck:
            stuecke.append((kapitel, stueck))

        for kap, zeilen in stuecke:
            for teil in _stuecke(zeilen):
                if len(teil) < MIN_CHUNK:
                    continue
                if ueberschrift_voran and kap and not teil.startswith(kap[:20]):
                    teil = f"[{kap[:80]}] {teil}"
                chunks.append(DocumentChunk(text=teil, page=s + 1, source_file=path.name,
                                            chunk_index=len(chunks), kind=kind))
    return chunks
