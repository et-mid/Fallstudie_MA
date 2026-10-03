"""Stammt die Begründung aus dem Kundendokument — oder aus dem Prompt?

Anlass: Begründungen enthalten mitunter harte Angaben, die im Kundendokument
nicht vorkommen, wohl aber im Standardblock des Prompts — etwa Fabrikate aus
dem Feld `auspraegungen_im_korpus`.

Der Hinweis-Durchgang fängt so etwas ab (`hinweise._im_dokument_belegt`). Der
Prüfdurchgang tat es nicht: Seine Belegpflicht prüft, DASS eine Begründung da
ist und die Fundstelle eine Ziffer enthält — nie, WOHER der Inhalt stammt.

Zwei Entscheidungen:

**Nur harte Angaben, keine Prosa.** Ein Wortvergleich der ganzen Begründung
misst die Sprache statt der Herkunft: Das Modell begründet immer auf Deutsch,
ein englisches Lastenheft fiele fast immer durch. Zahlen, Normnummern,
Typbezeichnungen und Versalienkürzel überstehen eine Übersetzung — deutsche
Fachwörter nicht. Deshalb wird ausschließlich daran geprüft.

**Kennzeichnen, nicht abwerten.** Der Befund ändert den Status nicht. Eingriffe,
die Urteile verschoben, ließen Richtiges nach N wandern. Eine Markierung
verschiebt nichts, kostet keinen Modellaufruf und lässt jede Kennzahl
unberührt — sie sagt dem Prüfer nur, welcher Satz eine Zweitbetrachtung
verdient.
"""

import re

# Was eine Übersetzung übersteht und als Herkunftsnachweis taugt:
#   Versalienkürzel ab drei Zeichen, mit angehängten Ziffern  ACME · WKZ42
#   Zahlenkennungen ab vier Stellen                           2768 · 1.2312
# Bewusst eng. Zweistellige Kürzel und kurze Zahlen träfen zufällig; ein
# Wortfragment wie „CAD-" steht in fast jedem Standardblock.
_HART = re.compile(r"\b(?:[A-ZÄÖÜ]{3,}[0-9]*|[0-9][0-9.,]{2,}[0-9])\b")

# Kürzel, die überall stehen und deshalb nichts über die Herkunft aussagen.
_ALLTAG = frozenset({
    "DIN", "ISO", "EN", "DE", "PDF", "CAD", "CAM", "CNC", "NC", "STL", "STEP",
    "IGES", "FTP", "SPC", "HRC", "PVD", "CVD", "DER", "DIE", "DAS", "UND",
    "MIT", "VON", "FÜR", "NICHT", "ODER", "ALS", "AUS", "BEI", "NUR",
})


def harte_angaben(text: str) -> list[str]:
    """Die überprüfbaren Angaben einer Begründung, ohne Dubletten."""
    gesehen, treffer = set(), []
    for t in _HART.findall(text or ""):
        if t.upper() in _ALLTAG:
            continue
        if t.upper() in gesehen:
            continue
        gesehen.add(t.upper())
        treffer.append(t)
    return treffer


def echo_angaben(begruendung: str, dokumenttext: str, massstab: str) -> list[str]:
    """Angaben, die im Dokument fehlen und im Maßstabsblock des Prompts stehen.

    `massstab` ist bewusst NUR der Standardblock, nicht der ganze Prompt: Der
    enthält auch die Fundstellen, und die stammen aus dem Dokument. Gegen den
    ganzen Prompt geprüft träfe jede Angabe zu und der Befund wäre wertlos.

    Leere Liste heißt: nichts nachweisbar abgeschrieben. Sie heißt nicht, dass
    die Begründung stimmt — nur, dass sich das Gegenteil hier nicht zeigt.
    """
    if not begruendung:
        return []
    dok = (dokumenttext or "").lower()
    mst = (massstab or "").lower()
    return [a for a in harte_angaben(begruendung)
            if a.lower() not in dok and a.lower() in mst]
