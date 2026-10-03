"""Schreibt einen Musterlastenheft-Entwurf als Word-Datei im bestehenden Format.

Das Format ist nicht frei gewählt: Es ist genau das, was
`standard_import.musterlastenheft_lesen` versteht. Ein Entwurf, den der eigene
Import nicht zurücklesen kann, wäre wertlos — deshalb prüft
`tests/test_musteraufbau.py` den Rundlauf Feld für Feld.

Aufbau, wie im Druckguss-Musterlastenheft:

    Titel · Gegenstand · Untertitel
    Metadaten-Tabelle (Dokumenttyp, Gegenstand, Ableitungsbasis, …)
    Überschrift 1 „Zweck, Aufbau und Verwendung dieses Dokuments" (ohne Nummer)
    Überschrift 1 „1 Kapitel"
      Überschrift 2 „1.1 Kriterium"
        Kopftabelle:  Einstufung | belegt in N von M | Dokumentkennungen
        Standardanforderungen      — je Anforderung ein Absatz
        Ausprägungen im Korpus     — je Ausprägung ein Absatz
        Projektspezifisch festzulegen — „[A]  ·  [B]"
        Abgleichbegriffe: a · b · c
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Schwellen für Pflicht und Regel als Anteil an der Zahl der Lastenhefte.
PFLICHT_ANTEIL = (14, 18)
REGEL_ANTEIL   = (8, 18)


@dataclass
class Kriterium:
    nr: str
    titel: str
    kapitel_nr: str
    kapitel_titel: str
    belegt_in: list[str] = field(default_factory=list)
    standardanforderungen: list[str] = field(default_factory=list)
    auspraegungen: list[str] = field(default_factory=list)
    platzhalter: list[str] = field(default_factory=list)
    abgleichbegriffe: list[str] = field(default_factory=list)


@dataclass
class Entwurf:
    gegenstand: str                 # Mehrzahl, z. B. „Schaltschränke"
    dokumente: list[str]            # Kennungen der Quelllastenhefte
    kriterien: list[Kriterium]
    stand: str = field(default_factory=lambda: date.today().strftime("%d.%m.%Y"))
    hinweise: list[str] = field(default_factory=list)   # Methodengrenzen fürs Deckblatt


def einstufung(n: int, m: int) -> str:
    """Pflicht / Regel / Optional aus „belegt in n von m" — anteilig wie bei 18."""
    if m <= 0:
        return "Optional"
    if n * PFLICHT_ANTEIL[1] >= PFLICHT_ANTEIL[0] * m:
        return "Pflicht"
    if n * REGEL_ANTEIL[1] >= REGEL_ANTEIL[0] * m:
        return "Regel"
    return "Optional"


def schwellen(m: int) -> tuple[int, int]:
    """Kleinste Belegzahl für Pflicht und für Regel bei m Lastenheften."""
    pflicht = next(n for n in range(m + 1) if einstufung(n, m) == "Pflicht")
    regel = next(n for n in range(m + 1) if einstufung(n, m) in ("Regel", "Pflicht"))
    return pflicht, regel


def kennung(dateiname: str) -> str:
    """Eine Dokumentkennung, die der Import sicher wieder trennt.

    Der Import trennt die Dokumentliste an Kommas, auf die Leerraum oder ein
    Buchstabe folgt — eine Kennung wie „X-13,3“ bleibt erhalten. Ein Komma mit
    Leerzeichen im Dateinamen würde dagegen zerteilt.
    """
    k = Path(dateiname).stem.strip()
    for alt in (", ", ",\t"):
        k = k.replace(alt, "_")
    return k.replace("\n", " ")


def _sauber(text: str) -> str:
    return " ".join(str(text).split())


def schreiben(entwurf: Entwurf, ziel: Path) -> Path:
    from docx import Document
    from docx.shared import Pt

    m = len(entwurf.dokumente)
    doc = Document()

    doc.add_paragraph("Standard-Lastenheft").runs[0].font.size = Pt(24)
    doc.add_paragraph(_sauber(entwurf.gegenstand)).runs[0].font.size = Pt(18)
    doc.add_paragraph("Referenz- und Vergleichsdokument für den Abgleich eingehender "
                      "Kundenlastenhefte — automatisch erzeugter Entwurf")

    meta = [
        ("Dokumenttyp", "Abgeleitetes Standard-/Referenzlastenheft (kein Vertragsdokument), "
                        "automatisch erzeugter Entwurf"),
        ("Gegenstand", _sauber(entwurf.gegenstand)),
        ("Ableitungsbasis", f"{m} Kundenlastenhefte ({', '.join(entwurf.dokumente)})"),
        ("Verarbeitung", "Vollständig lokal; keine Übertragung von Dokumentinhalten an "
                         "externe Dienste"),
        ("Stand", f"{entwurf.stand} – Entwurf"),
    ]
    tabelle = doc.add_table(rows=0, cols=2)
    tabelle.style = "Table Grid"
    for kopf, wert in meta:
        zellen = tabelle.add_row().cells
        zellen[0].text, zellen[1].text = kopf, wert

    doc.add_heading("Zweck, Aufbau und Verwendung dieses Dokuments", level=1)
    doc.add_paragraph(
        f"Dieses Dokument ist kein Kundenlastenheft und kein Vertragsdokument. Es ist "
        f"ein aus {m} Kundenlastenheften automatisch abgeleiteter Entwurf eines "
        f"Standards. Vor der Verwendung als Maßstab ist er fachlich zu prüfen und zu "
        f"überarbeiten.")
    for h in entwurf.hinweise:
        doc.add_paragraph(_sauber(h))

    doc.add_heading("Aufbau eines Abschnitts", level=2)
    aufbau = doc.add_table(rows=0, cols=2)
    aufbau.style = "Table Grid"
    for kopf, wert in (
        ("Statuszeile", "Einstufung des Abschnitts (Pflicht / Regel / Optional) und "
                        "Anzahl der Lastenhefte, die das Thema regeln"),
        ("Standardanforderungen", "Konsolidierte Formulierung der wiederkehrenden "
                                  "Anforderungen"),
        ("Ausprägungen im Korpus", "Konkrete Werte, Normen und Ausreißer aus den "
                                   "Originalen, mit Dokumentkennung"),
        ("Projektspezifisch festzulegen", "Platzhalter für Angaben, die je Projekt "
                                          "festzulegen sind"),
        ("Abgleichbegriffe", "Schlagworte für die Zuordnung eingehender Lastenhefte"),
    ):
        zellen = aufbau.add_row().cells
        zellen[0].text, zellen[1].text = kopf, wert

    doc.add_heading("Einstufung der Abschnitte", level=2)
    pflicht, regel = schwellen(m)
    stufen = doc.add_table(rows=1, cols=3)
    stufen.style = "Table Grid"
    for z, t in zip(stufen.rows[0].cells, ("Einstufung", "Kriterium", "Bedeutung für den Abgleich")):
        z.text = t
    for stufe, krit, bedeutung in (
        ("Pflicht", f"in {pflicht} bis {m} der {m} Lastenhefte belegt",
         "Fehlt das Thema in einem eingehenden Lastenheft, ist das ein Prüfhinweis."),
        ("Regel", f"in {regel} bis {max(regel, pflicht - 1)} der {m} Lastenhefte belegt",
         "Das Thema wird von der Mehrheit, aber nicht durchgängig geregelt."),
        ("Optional", f"in {max(regel - 1, 0)} oder weniger Lastenheften belegt",
         "Kundenspezifische Regelung."),
    ):
        zellen = stufen.add_row().cells
        zellen[0].text, zellen[1].text, zellen[2].text = stufe, krit, bedeutung

    letztes_kapitel = None
    for k in entwurf.kriterien:
        if k.kapitel_nr != letztes_kapitel:
            doc.add_heading(f"{k.kapitel_nr} {_sauber(k.kapitel_titel)}", level=1)
            letztes_kapitel = k.kapitel_nr
        doc.add_heading(f"{k.nr} {_sauber(k.titel)}", level=2)

        belegt = sorted(set(k.belegt_in), key=entwurf.dokumente.index
                        if all(d in entwurf.dokumente for d in k.belegt_in) else str)
        kopf = doc.add_table(rows=1, cols=3)
        kopf.style = "Table Grid"
        z = kopf.rows[0].cells
        z[0].text = einstufung(len(belegt), m)
        z[1].text = f"belegt in {len(belegt)} von {m}"
        z[2].text = ", ".join(belegt)

        doc.add_paragraph("Standardanforderungen")
        for s in k.standardanforderungen:
            doc.add_paragraph(_sauber(s), style="List Paragraph")
        doc.add_paragraph("Ausprägungen im Korpus")
        for a in k.auspraegungen:
            doc.add_paragraph(_sauber(a))
        doc.add_paragraph("Projektspezifisch festzulegen")
        platz = [_sauber(p).replace("[", "(").replace("]", ")") for p in k.platzhalter if _sauber(p)]
        if platz:
            doc.add_paragraph("  ·  ".join(f"[{p}]" for p in platz))
        begriffe = [_sauber(b).replace("·", " ").replace(";", ",") for b in k.abgleichbegriffe]
        doc.add_paragraph("Abgleichbegriffe: " + " · ".join(b for b in begriffe if b))

    ziel.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ziel))
    return ziel
