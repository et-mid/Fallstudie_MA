"""Excel-Bericht für die kriterienbasierte Lastenheft-Prüfung (67 Kriterien).

Blätter:
  Deckblatt        — Kennzahlen und Statusverteilung
  Kriterien        — eine Zeile je Kriterium, in der Reihenfolge der Gliederung
  Abweichungen     — nur Status A, mit Fundstelle und Begründung
  Hinweise         — Festlegungen des Kunden an Punkten, die das
                     Musterlastenheft offen lässt; kein Status, keine Kennzahl
  Zusatzanforderungen — Kundenanforderungen ohne Entsprechung in der Gliederung
  Praxisabgleich   — nur mit Archiv: Häufigkeit und Belegstellen aus den
                     historischen Lastenheften

Kennzahlen werden hier gerechnet, nicht vom Modell.
"""

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from src.pruefung.kriterien import (
    EINSTUFUNGEN, STATUS_WERTE, kennzahlen, kennzahlen_je_einstufung,
    load_kriterien, load_standard,
)

# ── Farben ────────────────────────────────────────────────────────────────────
CLR_DARK   = "1A3A5C"
CLR_MID    = "2E6DA4"
CLR_RED    = "C0392B"
CLR_ORANGE = "D68910"
CLR_GREEN  = "1E8449"
CLR_GRAY   = "666666"

CLR_RED_LIGHT    = "FDECEA"
CLR_ORANGE_LIGHT = "FEF9E7"
CLR_GREEN_LIGHT  = "EAFAF1"
CLR_GRAY_LIGHT   = "F2F2F2"
CLR_WHITE        = "FFFFFF"
CLR_HEADER_TXT   = "FFFFFF"

STATUS_LABEL = {
    "E": "E — entspricht",
    "T": "T — teilweise",
    "A": "A — Abweichung",
    "N": "N — keine Vorgabe",
}
STATUS_COLOR = {"E": CLR_GREEN, "T": CLR_ORANGE, "A": CLR_RED, "N": CLR_GRAY}
STATUS_ROW   = {"E": CLR_GREEN_LIGHT, "T": CLR_ORANGE_LIGHT,
                "A": CLR_RED_LIGHT,   "N": CLR_WHITE}
STATUS_ICON  = {"E": "✅", "T": "🟡", "A": "🔴", "N": "○"}

# Statuscode → Feldname in kennzahlen()
ZAEHLER_FELD = {"E": "entspricht", "T": "teilweise",
                "A": "abweichung", "N": "keine_vorgabe"}


# ── Helfer ────────────────────────────────────────────────────────────────────
def _prozent(anteil: float, stellen: int = 1) -> str:
    """„14,1 %" — mit Komma, wie überall sonst in der Anwendung."""
    return f"{anteil * 100:.{stellen}f} %".replace(".", ",")


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _border_thin() -> Border:
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


def _align(h="left", v="center", wrap=False) -> Alignment:
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _cell(ws, row, col, value, bold=False, fg=None, txt_color=None,
          h_align="left", wrap=False, size=10):
    if isinstance(value, str):
        # Steuerzeichen aus defekten PDF-Fonts lehnt openpyxl ab — der Bericht
        # scheiterte sonst am Ende eines vollständigen Laufs.
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
    c = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str):
        # openpyxl schreibt jede Zeichenkette, die mit „=" beginnt, als Formel.
        # Belegtexte aus Lastenheften tun das („= Passungen der Teileinsätze …",
        # 93-mal im Korpus); Excel zeigt dann #NAME? statt des Textes.
        c.data_type = "s"
    c.font      = Font(bold=bold, color=txt_color or "000000", size=size)
    c.alignment = _align(h_align, "center", wrap)
    c.border    = _border_thin()
    if fg:
        c.fill = _fill(fg)
    return c


def _header_row(ws, row: int, headers: list[str], widths: list[int], color=CLR_DARK):
    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        ws.column_dimensions[ws.cell(row=row, column=i).column_letter].width = w
        c = ws.cell(row=row, column=i, value=h)
        c.font      = Font(bold=True, color=CLR_HEADER_TXT, size=10)
        c.fill      = _fill(color)
        c.alignment = _align("center", wrap=True)
        c.border    = _border_thin()
    ws.row_dimensions[row].height = 20


def _belegstelle(bewertung: dict, kandidaten: list[dict]) -> str:
    """Die Kandidatenstelle auf der genannten Fundstellenseite, sonst die beste.

    Die beste Stelle der Suche ist nicht unbedingt die, auf die sich die
    Begründung stützt — im Bericht stünde dann ein Auszug neben einer
    Seitenangabe, die nicht zu ihm passt.
    """
    if not kandidaten:
        return ""
    seite = "".join(ch for ch in str(bewertung.get("fundstelle") or "") if ch.isdigit())
    for k in kandidaten:
        if seite and str(k.get("page")) == seite:
            return k.get("text", "")
    return kandidaten[0].get("text", "")


def _kapitel_nummern(kriterien: list[dict]) -> dict[str, int]:
    """Kapitelname → laufende Nummer (1–11), in der Reihenfolge der Gliederung."""
    out: dict[str, int] = {}
    for k in kriterien:
        if k["kapitel"] not in out:
            out[k["kapitel"]] = len(out) + 1
    return out


# ── Blatt 1: Deckblatt ────────────────────────────────────────────────────────
def _sheet_deckblatt(wb: Workbook, ergebnis: dict, kz: dict, je_einstufung: dict,
                     basis: str | None):
    ws = wb.active
    ws.title = "Deckblatt"
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16

    row = 1
    ws.merge_cells(f"A{row}:C{row}")
    c = ws.cell(row=row, column=1, value=f"Lastenheft-Prüfbericht — "
                                            f"{len(ergebnis.get('bewertungen') or {})} Kriterien")
    c.font = Font(bold=True, size=18, color=CLR_DARK)
    ws.row_dimensions[row].height = 28
    row += 1

    ws.merge_cells(f"A{row}:C{row}")
    ws.cell(row=row, column=1, value=ILLEGAL_CHARACTERS_RE.sub("", str(ergebnis.get("lh_id", "")))).font = Font(size=10, color=CLR_GRAY)
    row += 1
    if basis:
        ws.merge_cells(f"A{row}:C{row}")
        ws.cell(row=row, column=1, value=ILLEGAL_CHARACTERS_RE.sub("", f"Referenz: {basis}")).font = Font(size=9, color=CLR_GRAY)
        row += 1
    ws.merge_cells(f"A{row}:C{row}")
    ws.cell(row=row, column=1,
            value=f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            ).font = Font(size=9, color=CLR_GRAY)
    row += 2

    # Abweichungsquote als Kopfzahl
    quote = kz["abweichungsquote"] or 0.0
    quote_clr = CLR_RED if quote >= 0.3 else CLR_ORANGE if quote >= 0.1 else CLR_GREEN
    ws.merge_cells(f"A{row}:C{row}")
    c = ws.cell(row=row, column=1,
                value=f"Abweichungsquote: {_prozent(quote)}  "
                      f"(A + 0,5 × T von {kz['geregelt']} geregelten Kriterien)")
    c.font      = Font(bold=True, size=14, color=CLR_HEADER_TXT)
    c.fill      = _fill(quote_clr)
    c.alignment = _align("center")
    c.border    = _border_thin()
    ws.row_dimensions[row].height = 26
    row += 2

    # Statusverteilung
    anzahl = ZAEHLER_FELD  # Statuscode -> Feldname in kennzahlen()
    _header_row(ws, row, ["Status", "Anzahl", "Anteil"], [34, 16, 16])
    row += 1
    gesamt_n = sum(kz[anzahl[s]] for s in STATUS_WERTE) or 1
    for s in STATUS_WERTE:
        n = kz[anzahl[s]]
        _cell(ws, row, 1, STATUS_LABEL[s], fg=STATUS_ROW[s], bold=True,
              txt_color=STATUS_COLOR[s])
        _cell(ws, row, 2, n, fg=STATUS_ROW[s], h_align="center")
        _cell(ws, row, 3, _prozent(n / gesamt_n), fg=STATUS_ROW[s], h_align="center")
        row += 1
    _cell(ws, row, 1, "Gesamt", fg=CLR_GRAY_LIGHT, bold=True)
    _cell(ws, row, 2, gesamt_n, fg=CLR_GRAY_LIGHT, h_align="center", bold=True)
    _cell(ws, row, 3, "100,0 %", fg=CLR_GRAY_LIGHT, h_align="center", bold=True)
    row += 1
    # Die Markierung hebt Verdachtsfälle zur Durchsicht auf A. Verteilung und Quoten
    # zählen sie unter dem Urteil des Modells, das Blatt „Abweichungen“ führt sie auf.
    if kz.get("markiert"):
        ws.merge_cells(f"A{row}:C{row}")
        ws.cell(row=row, column=1,
                value=f"Zusätzlich zur Durchsicht markiert: {kz['markiert']} — im Blatt "
                      f"„Abweichungen“ aufgeführt, oben unter dem Urteil des Modells gezählt."
                ).font = Font(size=9, italic=True, color=CLR_GRAY)
        row += 1
    row += 1

    # Quoten
    _header_row(ws, row, ["Quote", "Wert", "Formel"], [34, 16, 30])
    row += 1
    quoten = [
        ("Abweichungsquote",   kz["abweichungsquote"],   "(A + 0,5 × T) / geregelt"),
        ("Abdeckungsquote",    kz["abdeckungsquote"],    f"geregelt / {gesamt_n}"),
        ("Konformitätsquote",  kz["konformitaetsquote"], "E / geregelt"),
    ]
    for i, (label, wert, formel) in enumerate(quoten):
        bg = CLR_GRAY_LIGHT if i % 2 == 0 else CLR_WHITE
        _cell(ws, row, 1, label, fg=bg, bold=True)
        _cell(ws, row, 2, "—" if wert is None else _prozent(wert),
              fg=bg, h_align="center")
        _cell(ws, row, 3, formel, fg=bg, size=9, txt_color=CLR_GRAY)
        row += 1
    row += 1

    # Womit ist der Bericht entstanden? Vor allem: Lief der Entscheider mit?
    from src.pruefung.steckbrief import laufbedingungen
    bedingungen = laufbedingungen(ergebnis)
    if bedingungen:
        _header_row(ws, row, ["Laufbedingungen", "", ""], [34, 16, 30])
        row += 1
        for label, wert in bedingungen:
            warnung = wert.startswith("NICHT AKTIV")
            _cell(ws, row, 1, label, fg=CLR_GRAY_LIGHT, bold=True)
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
            _cell(ws, row, 2, wert, fg=CLR_GRAY_LIGHT, size=9, wrap=True,
                  txt_color=CLR_RED if warnung else None, bold=warnung)
            row += 1
        row += 1

    # Verteilung je Einstufung — zeigt, ob Lücken bei Pflichtkriterien liegen
    _header_row(ws, row, ["Einstufung", "E", "T"], [34, 16, 16])
    ws.cell(row=row, column=4, value="A").font = Font(bold=True, color=CLR_HEADER_TXT, size=10)
    ws.cell(row=row, column=4).fill = _fill(CLR_DARK)
    ws.cell(row=row, column=4).alignment = _align("center")
    ws.cell(row=row, column=4).border = _border_thin()
    ws.cell(row=row, column=5, value="N").font = Font(bold=True, color=CLR_HEADER_TXT, size=10)
    ws.cell(row=row, column=5).fill = _fill(CLR_DARK)
    ws.cell(row=row, column=5).alignment = _align("center")
    ws.cell(row=row, column=5).border = _border_thin()
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 16
    row += 1

    for e in EINSTUFUNGEN:
        vals = je_einstufung[e]
        bg = CLR_GRAY_LIGHT if e == "Pflicht" else CLR_WHITE
        _cell(ws, row, 1, e, fg=bg, bold=(e == "Pflicht"))
        for i, s in enumerate(STATUS_WERTE, start=2):
            _cell(ws, row, i, vals[s], fg=bg, h_align="center",
                  txt_color=STATUS_COLOR[s] if vals[s] else CLR_GRAY)
        row += 1
    row += 1

    offene_pflicht = je_einstufung["Pflicht"]["N"]
    hinweis = (f"Ohne Vorgabe bei Pflichtkriterien: {offene_pflicht} — "
               "diese Punkte sind vom Fachbereich zu klären.")
    ws.merge_cells(f"A{row}:E{row}")
    ws.cell(row=row, column=1, value=hinweis).font = Font(
        size=9, italic=True, color=CLR_RED if offene_pflicht else CLR_GRAY)
    row += 1

    ws.merge_cells(f"A{row}:E{row}")
    ws.cell(row=row, column=1, value=(
        "N ist kein Mangel: der Kunde hat zu diesem Punkt nichts vorgegeben. "
        "Die Abweichungsquote bezieht sich nur auf geregelte Kriterien (E/T/A)."
    )).font = Font(size=9, italic=True, color=CLR_GRAY)
    row += 2

    ws.merge_cells(f"A{row}:E{row}")
    c = ws.cell(row=row, column=1, value=(
        "Prüfhilfe, kein Prüfergebnis. Die Einstufungen stammen aus einer "
        "maschinellen Analyse und sind fachlich zu verifizieren. Zu jedem Kriterium "
        "sind Fundstelle und Belegtext angegeben, damit jede Einstufung am "
        "Originaldokument nachvollzogen werden kann."))
    c.font      = Font(size=9, bold=True, color=CLR_DARK)
    c.alignment = _align("left", wrap=True)
    c.fill      = _fill(CLR_GRAY_LIGHT)
    c.border    = _border_thin()
    ws.row_dimensions[row].height = 42


# ── Blatt 2: Kriterien ────────────────────────────────────────────────────────
def _sheet_kriterien(wb: Workbook, ergebnis: dict, kriterien: list[dict],
                     details: dict | None):
    ws = wb.create_sheet("Kriterien")
    _header_row(ws, 1, ["Nr", "Kriterium", "Einstufung", "Status",
                        "Begründung", "Fundstelle", "Beleg (Auszug)"],
                [8, 42, 12, 18, 52, 12, 46])
    ws.freeze_panes = "A2"

    kap_nr      = _kapitel_nummern(kriterien)
    bewertungen = ergebnis.get("bewertungen", {})
    letztes_kap = None
    row = 2

    for k in kriterien:
        # Kapitel-Trennzeile
        if k["kapitel"] != letztes_kap:
            letztes_kap = k["kapitel"]
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            c = ws.cell(row=row, column=1, value=f"{kap_nr[k['kapitel']]}  {k['kapitel']}")
            c.font      = Font(bold=True, size=10, color=CLR_HEADER_TXT)
            c.fill      = _fill(CLR_MID)
            c.alignment = _align("left")
            c.border    = _border_thin()
            ws.row_dimensions[row].height = 18
            row += 1

        b      = bewertungen.get(k["nr"], {"status": "N", "begruendung": "", "fundstelle": ""})
        status = b.get("status", "N")
        bg     = STATUS_ROW.get(status, CLR_WHITE)
        clr    = STATUS_COLOR.get(status, CLR_GRAY)

        beleg = ""
        if details and status != "N":
            kand = (details.get(k["nr"]) or {}).get("kandidaten") or []
            beleg = _belegstelle(b, kand)[:300]

        _cell(ws, row, 1, k["nr"], fg=bg, h_align="center", bold=True, size=9)
        _cell(ws, row, 2, k["titel"], fg=bg, wrap=True, size=9)
        _cell(ws, row, 3, k["einstufung"], fg=bg, h_align="center", size=9)
        _cell(ws, row, 4, f"{STATUS_ICON[status]} {status}", fg=bg, h_align="center",
              bold=True, txt_color=clr, size=9)
        _cell(ws, row, 5, b.get("begruendung", ""), fg=bg, wrap=True, size=9)
        _cell(ws, row, 6, b.get("fundstelle", ""), fg=bg, h_align="center", size=9)
        _cell(ws, row, 7, beleg, fg=bg, wrap=True, size=8, txt_color=CLR_GRAY)
        ws.row_dimensions[row].height = 30 if status != "N" else 16
        row += 1


# ── Blatt 3: Abweichungen ─────────────────────────────────────────────────────
def _sheet_abweichungen(wb: Workbook, ergebnis: dict, kriterien: list[dict],
                        details: dict | None):
    ws = wb.create_sheet("Abweichungen")
    _header_row(ws, 1, ["#", "Nr", "Kriterium", "Einstufung", "Begründung",
                        "Fundstelle", "Stelle im Lastenheft", "Standardanforderung",
                        "Herkunft"],
                [5, 8, 34, 12, 46, 12, 46, 46, 22])
    ws.freeze_panes = "A2"

    bewertungen = ergebnis.get("bewertungen", {})
    titel_von   = {k["nr"]: k for k in kriterien}
    reihenfolge = [k["nr"] for k in kriterien]
    standard    = load_standard()

    row = 2
    lfd = 0
    for nr in reihenfolge:
        b = bewertungen.get(nr, {})
        if b.get("status") != "A":
            continue
        lfd += 1
        k = titel_von[nr]
        d = (details or {}).get(nr) or {}
        stelle = _belegstelle(b, d.get("kandidaten") or [])[:400]
        std    = "\n".join(f"• {s}" for s in
                           (standard.get(nr, {}).get("standardanforderungen") or []))[:500] or "—"

        _cell(ws, row, 1, lfd, fg=CLR_RED_LIGHT, h_align="center", bold=True, txt_color=CLR_RED)
        _cell(ws, row, 2, nr, fg=CLR_RED_LIGHT, h_align="center", bold=True, size=9)
        _cell(ws, row, 3, k["titel"], fg=CLR_RED_LIGHT, wrap=True, size=9)
        _cell(ws, row, 4, k["einstufung"], fg=CLR_RED_LIGHT, h_align="center", size=9)
        _cell(ws, row, 5, b.get("begruendung", ""), fg=CLR_RED_LIGHT, wrap=True, size=9)
        _cell(ws, row, 6, b.get("fundstelle", ""), fg=CLR_RED_LIGHT, h_align="center", size=9)
        _cell(ws, row, 7, stelle, fg=CLR_WHITE, wrap=True, size=8)
        _cell(ws, row, 8, std,    fg=CLR_WHITE, wrap=True, size=8, txt_color=CLR_GRAY)
        # Vom Modell vergeben oder nachträglich markiert — die Durchsicht nimmt
        # die sicheren zuerst.
        herkunft = " · ".join(b.get("herkunft") or ["Modell"])
        if b.get("status_modell") and b["status_modell"] != "A":
            herkunft += f" (Modell: {b['status_modell']})"
        _cell(ws, row, 9, herkunft, fg=CLR_WHITE, wrap=True, size=8)
        ws.row_dimensions[row].height = 70
        row += 1

    if lfd == 0:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=9)
        ws.cell(row=2, column=1,
                value="Keine Abweichungen (Status A) festgestellt."
                ).font = Font(size=10, italic=True, color=CLR_GREEN)


# ── Blatt 4: Hinweise ─────────────────────────────────────────────────────────
def _sheet_hinweise(wb: Workbook, ergebnis: dict, kriterien: list[dict]) -> None:
    """Stellen, an denen der Kunde festlegt, was das Musterlastenheft offenlässt.

    Bewusst ein eigenes Blatt und bewusst nach den Abweichungen: Ein Hinweis ist
    keine Einstufung. Er ändert keinen Status und geht in keine Kennzahl ein.
    Nicht jeder Hinweis trifft eine Abweichung — zu wenig für ein Urteil, genug
    für einen Blick.
    """
    ws = wb.create_sheet("Hinweise")
    titel = {k["nr"]: k["titel"] for k in kriterien}
    hinweise = ergebnis.get("hinweise") or []

    ws.merge_cells("A1:F1")
    c = ws.cell(row=1, column=1, value=(
        "Das Musterlastenheft lässt diese Punkte bewusst offen — das Lastenheft "
        "legt sie fest. Das ist keine Abweichung und kein Fehler: Es ist die "
        "Stelle, an der eine Festlegung des Kunden Geld kosten kann. Fachlich "
        "prüfen, nicht abhaken."))
    c.font      = Font(size=9, bold=True, color=CLR_DARK)
    c.alignment = _align("left", wrap=True)
    c.fill      = _fill(CLR_GRAY_LIGHT)
    c.border    = _border_thin()
    ws.row_dimensions[1].height = 40

    # Die Herkunft steht als eigene Spalte, weil die beiden Wege verschieden
    # verlässlich sind: „gelesen" heißt, ein Modell hat das Kundendokument
    # gelesen; „notiert" heißt, die Prüfung hat den Punkt als geregelt
    # eingestuft und dabei selbst ein Fabrikat genannt. Wer den Hinweis
    # einschätzen soll, braucht diesen Unterschied.
    _header_row(ws, 2, ["Nr", "Kriterium", "Seite", "Was das Lastenheft festlegt",
                        "Was das Musterlastenheft offen lässt", "Herkunft"],
                [8, 34, 8, 66, 52, 14])
    ws.freeze_panes = "A3"

    for i, h in enumerate(hinweise, start=1):
        r  = i + 2
        bg = CLR_GRAY_LIGHT if i % 2 else CLR_WHITE
        _cell(ws, r, 1, h.get("nr", ""), fg=bg, h_align="center", size=9)
        _cell(ws, r, 2, titel.get(h.get("nr"), ""), fg=bg, wrap=True, size=9)
        _cell(ws, r, 3, h.get("fundstelle", ""), fg=bg, h_align="center", size=9)
        _cell(ws, r, 4, h.get("text", ""), fg=bg, wrap=True, size=9)
        _cell(ws, r, 5, h.get("offene_stelle", ""), fg=bg, wrap=True, size=8,
              txt_color=CLR_GRAY)
        _cell(ws, r, 6,
              "notiert" if h.get("art") == "Erzeugniswahl" else "gelesen",
              fg=bg, h_align="center", size=8, txt_color=CLR_GRAY)
        ws.row_dimensions[r].height = 32

    if not hinweise:
        ws.cell(row=3, column=2, value=(
            "Keine Festlegungen an den offen formulierten Punkten gefunden."
        )).font = Font(size=10, italic=True, color=CLR_GRAY)

    ws.cell(row=len(hinweise) + 4, column=2, value=(
        "Hinweise ändern keinen Status und gehen nicht in die Kennzahlen ein. "
        "Geprüft werden nur die Kriterien, in denen das Musterlastenheft selbst "
        "offen formuliert."
    )).font = Font(size=9, italic=True, color=CLR_GRAY)


# ── Blatt 5: Zusatzanforderungen ──────────────────────────────────────────────
def _sheet_zusatz(wb: Workbook, ergebnis: dict):
    ws = wb.create_sheet("Zusatzanforderungen")
    _header_row(ws, 1, ["#", "Anforderung ohne Entsprechung in der Gliederung"], [5, 110])
    ws.freeze_panes = "A2"

    zusatz = ergebnis.get("zusatzanforderungen") or []
    for i, z in enumerate(zusatz, start=1):
        bg = CLR_GRAY_LIGHT if i % 2 else CLR_WHITE
        _cell(ws, i + 1, 1, i, fg=bg, h_align="center", size=9)
        _cell(ws, i + 1, 2, z, fg=bg, wrap=True, size=9)
        ws.row_dimensions[i + 1].height = 28

    if not zusatz:
        ws.cell(row=2, column=2,
                value="Keine Zusatzanforderungen erkannt."
                ).font = Font(size=10, italic=True, color=CLR_GRAY)

    ws.cell(row=len(zusatz) + 3, column=2, value=(
        "Zusatzanforderungen erzeugen kein Kriterium und gehen nicht in die Kennzahlen ein."
    )).font = Font(size=9, italic=True, color=CLR_GRAY)


# ── Blatt 5: Praxisabgleich ───────────────────────────────────────────────────
EINORDNUNG_FARBE = {
    "luecke":       (CLR_ORANGE_LIGHT, CLR_ORANGE),
    "selten":       (CLR_GRAY_LIGHT,   CLR_MID),
    "ueblich":      (CLR_GREEN_LIGHT,  CLR_GREEN),
    "unauffaellig": (CLR_WHITE,        CLR_GRAY),
}


def _sheet_praxis(wb: Workbook, befunde: list) -> None:
    """Häufigkeit im historischen Korpus, mit Belegstellen.

    Bewusst ein eigenes Blatt: Die Einordnung ist keine Einstufung und darf
    neben E/T/A/N nicht wie eine zweite Bewertung aussehen.
    """
    from src.praxis.abgleich import LABEL

    ws = wb.create_sheet("Praxisabgleich")
    korpus = befunde[0].korpus if befunde else 0

    ws.merge_cells("A1:H1")
    c = ws.cell(row=1, column=1, value=(
        f"Abgleich gegen {korpus} frühere Lastenhefte. Häufigkeit ist keine "
        "Bewertung: Selten geregelte Punkte weichen nicht häufiger ab als häufig "
        "geregelte. Die Spalte „Einordnung“ sagt, wo ein "
        "Blick ins Archiv lohnt — nicht, wo ein Risiko liegt."))
    c.font      = Font(size=9, bold=True, color=CLR_DARK)
    c.alignment = _align("left", wrap=True)
    c.fill      = _fill(CLR_GRAY_LIGHT)
    c.border    = _border_thin()
    ws.row_dimensions[1].height = 40

    _header_row(ws, 2, ["Nr", "Kriterium", "Status", "regeln den Punkt",
                        "Einordnung", "Dokumente", "Belegstellen aus dem Archiv"],
                [8, 38, 10, 16, 24, 30, 74])
    ws.freeze_panes = "A3"

    row = 3
    # Auffällige zuerst — der Rest ist Nachschlagematerial.
    sortiert = sorted(befunde, key=lambda b: (not b.auffaellig, b.anteil))
    for b in sortiert:
        bg, clr = EINORDNUNG_FARBE.get(b.einordnung, (CLR_WHITE, CLR_GRAY))
        belege = "\n\n".join(
            f"[{s.lh_id}, S. {s.seite}, Relevanz {s.score * 100:.0f} %]\n"
            f"{s.text[:300]}" for s in b.stellen[:3]) or "—"

        _cell(ws, row, 1, b.nr, fg=bg, h_align="center", bold=True, size=9)
        _cell(ws, row, 2, b.titel, fg=bg, wrap=True, size=9)
        _cell(ws, row, 3, f"{STATUS_ICON[b.status]} {b.status}", fg=bg,
              h_align="center", size=9, txt_color=STATUS_COLOR[b.status])
        _cell(ws, row, 4, f"{b.n_geregelt} von {b.korpus}", fg=bg,
              h_align="center", size=9)
        _cell(ws, row, 5, LABEL.get(b.einordnung, b.einordnung), fg=bg,
              h_align="center", size=9, bold=b.auffaellig, txt_color=clr)
        _cell(ws, row, 6, ", ".join(b.dokumente) or "—", fg=bg, wrap=True,
              size=8, txt_color=CLR_GRAY)
        _cell(ws, row, 7, belege, fg=CLR_WHITE, wrap=True, size=8)
        ws.row_dimensions[row].height = 74 if b.stellen else 20
        row += 1


# ── Haupt-Funktion ────────────────────────────────────────────────────────────
def generate_excel(ergebnis: dict, details: dict | None = None,
                   kriterien: list[dict] | None = None,
                   basis: str | None = None,
                   praxis: list | None = None) -> bytes:
    """Erzeugt den Prüfbericht als XLSX-Bytes.

    ergebnis — das JSON-Objekt des Agenten (lh_id, bewertungen, zusatzanforderungen)
    details  — optionale Belegtexte je Kriteriumsnummer aus evaluate_document()
    praxis   — optionale Praxisbefunde aus praxisabgleich(); ohne sie entfällt
               das Blatt vollständig, statt leer im Bericht zu stehen
    """
    kriterien = kriterien if kriterien is not None else load_kriterien()
    kz  = ergebnis.get("kennzahlen") or kennzahlen(ergebnis, kriterien)
    kje = kennzahlen_je_einstufung(ergebnis, kriterien)

    wb = Workbook()
    _sheet_deckblatt(wb, ergebnis, kz, kje, basis)
    _sheet_kriterien(wb, ergebnis, kriterien, details)
    _sheet_abweichungen(wb, ergebnis, kriterien, details)
    _sheet_hinweise(wb, ergebnis, kriterien)
    _sheet_zusatz(wb, ergebnis)
    if praxis:
        _sheet_praxis(wb, praxis)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
