"""Mehr Abweichungen markieren — lieber eine zu viel als eine übersehen.

Die Abweichungen gehen an den Fachbereich zur Durchsicht. Ein Fehlalarm kostet
dort einen Blick, eine übersehene Abweichung kostet Geld. Das Modell selbst
vergibt `A` kaum, und jede schärfere Prüffrage ließ es auf `N` ausweichen statt
genauer hinzusehen.

Dieses Modul setzt deshalb NACH der Prüfung an und hebt Kriterien auf `A`, an
denen es Anzeichen gibt — aus dem, was der Lauf ohnehin erzeugt hat. Kein
zusätzlicher Modellaufruf.

## Die Anzeichen

| Herkunft | woran erkannt |
|---|---|
| Modell | das Modell hat selbst `A` vergeben |
| Hinweis | der Hinweis-Durchgang oder der Begründungsdetektor hat eine Festlegung gefunden |
| Beschaffung | die Begründung nennt Fabrikat, Hersteller, Lieferant … |
| Zahl/Norm | die Begründung nennt einen Wert oder eine Norm (Seitenverweise zählen nicht) |
| Pflicht | die Begründung nennt „nur", „ausschließlich", Kosten, Fristen, Garantie … |
| Wahrscheinlichkeit | unter den je Dokument 5 geregelten Kriterien, bei denen das Modell `A` am nächsten war |
| Statistik | dasselbe ohne Modellwahrscheinlichkeiten: die 5 mit dem höchsten Wert des Rangierers (src/pruefung/entscheider.py) |
| Markenvorgabe | eine Fundstelle schreibt einen Hersteller vor, auch wenn die Begründung ihn nicht nennt (src/pruefung/markenvorgabe.py) |
| Häufung | in den bewerteten Lastenheften ist mindestens ein Drittel der geregelten Fälle dieses Kriteriums eine Abweichung |

| Kostenfolge | ein Satz der Fundstellen legt dem Lieferanten Kosten auf (src/pruefung/kostenfolge.py, Codebook R10) |
| Widerspruch | das Modell schreibt in der eigenen Begründung „widerspricht" und vergibt trotzdem E/T |
| Werkstoff | eine Fundstelle nennt eine Werkstoffnummer, die der Standard zu diesem Kriterium nicht belegt (src/pruefung/wertabgleich.py) |
| Wert | eine Zahl mit Einheit liegt außerhalb der Werte des Standards — in keiner Stufe |
| Gegenteil | das Modell nennt eine Stelle, die einer Standardanforderung (Zuständigkeit, Erlaubnis) entgegensteht, und bestätigt sie einzeln (src/pruefung/gegenteil.py) |

Welche Anzeichen in welcher Stufe tragen, steht in STUFEN unten.

## Die Umkehr: Anzeichen „Häufung"

In einigen Kriterien ist die Abweichung nicht die Ausnahme, sondern die Regel.
Dort wird die Frage umgedreht — geregelt heißt zunächst `A`, und die Durchsicht
stuft zurück. Die Grundrate kommt aus den Referenzbewertungen, mit dem
Entscheider gelernt (`anteil_a_geregelt`), ohne Sprachmodell.

Die Stufen legen fest, welche Anzeichen genügen. Ausgewählt an denselben
Dokumenten, an denen die Wortlisten entstanden sind — also ohne unabhängige
Gegenprobe.

Jedes gehobene Kriterium behält den Status des Modells in `status_modell` und
nennt seine Anzeichen in `herkunft`. Die Durchsicht kann so mit den sicheren
beginnen, und die Auswertung kann das Urteil des Modells weiter getrennt messen.
Kennzahlen und Exact Match zählen unter `status_modell` (kriterien.kennzahlen,
evaluation.vergleiche); die Markierungen stehen getrennt.
"""

from __future__ import annotations

import re

from src.pruefung.hinweise import BINDUNG

# Ein Anzeichen bleibt in einer Stufe nur, wenn es deutlich häufiger eine
# Abweichung trifft als die Grundrate. Anzeichen, die per Bauart
# Fabrikatsbindungen erkennen, tragen nicht, weil eine Fabrikatsbindung allein
# keine Abweichung ist. Die übrigen Anzeichen stehen weiter in anzeichen(),
# damit frühere Läufe nachgerechnet werden können.
STUFEN: dict[str, tuple[str, ...]] = {
    "aus": (),
    "gezielt": ("Kostenfolge", "Widerspruch", "Werkstoff", "Gegenteil"),
    "gruendlich": ("Kostenfolge", "Widerspruch", "Werkstoff", "Gegenteil", "Pflicht",
                   "Wahrscheinlichkeit"),
}
# Frühere Stufen, zur Nachrechnung älterer Läufe.
STUFEN_REFERENZ_1_2: dict[str, tuple[str, ...]] = {
    "aus": (),
    "gezielt": ("Häufung", "Widerspruch"),
    "gruendlich": ("Häufung", "Pflicht", "Kostenfolge", "Widerspruch"),
}
# Frühere Stufen, zur Nachrechnung älterer Läufe.
STUFEN_REFERENZ_1_1: dict[str, tuple[str, ...]] = {
    "aus": (),
    "gezielt": ("Häufung",),
    "zurueckhaltend": ("Hinweis", "Häufung"),
    "mittel": ("Hinweis", "Beschaffung", "Häufung"),
    "gruendlich": ("Hinweis", "Beschaffung", "Markenvorgabe", "Wahrscheinlichkeit", "Statistik",
                   "Häufung"),
    "hoch": ("Hinweis", "Beschaffung", "Zahl/Norm", "Pflicht", "Häufung"),
}
# Anzeichen „Häufung": ab diesem Anteil A unter den geregelten Referenzfällen des
# Kriteriums.
SCHWELLE_KRITERIUM = 0.3
# Stufen, für die die Prüfung die Status-Wahrscheinlichkeiten mitschreiben muss.
BRAUCHT_WAHRSCHEINLICHKEIT = {s for s, a in STUFEN.items() if "Wahrscheinlichkeit" in a}
# Stufen, für die die Prüfung den Gegenteil-Durchgang fahren muss (src/pruefung/gegenteil.py).
BRAUCHT_GEGENTEIL = {s for s, a in STUFEN.items() if "Gegenteil" in a}
# Je Dokument so viele E/T-Kriterien mit der höchsten Wahrscheinlichkeit für A.
# Eine feste Zahl statt einer Schwelle: Der Durchsichtaufwand bleibt planbar, auch
# wenn ein anderes Modell seine Wahrscheinlichkeiten anders verteilt.
WAHRSCHEINLICHSTE_JE_DOKUMENT = 5
# Vorgabe „gruendlich": vom Auftraggeber so festgelegt — eine übersehene Abweichung
# kostet mehr als ein Fehlalarm.
VORGABE = "gruendlich"


STUFEN_TEXT = {
    "aus": "Nur das Urteil des Modells",
    "gezielt": "Gezielt",
    "gruendlich": "Gründlich",
}

# Verweise auf Stellen im Dokument sind keine inhaltliche Angabe: „(Seite 9)",
# „S12", „Abschnitt 3.2", „Punkt 4.1.2", „Z. 10.3".
_VERWEIS = re.compile(
    r"\b(?:Seite|Seiten|S\.?|Abschnitt|Kapitel|Punkt|Ziffer|Z\.|Nr\.|Pos\.)\s*\d+(?:[.,]\d+)*"
    r"|\bS\d+\b", re.I)
_ZAHL_NORM = re.compile(r"\b(?:DIN|EN|ISO|VDI|VDA|VDE|SEP|ASTM|IEC)\b|\d")
_PFLICHT = re.compile(
    r"\b(?:nur|ausschlie(?:ß|ss)lich|zwingend|verpflichtet|trägt|übernimmt|Kosten\w*|"
    r"Garantie\w*|Gewährleistung\w*|Frist\w*|innerhalb|spätestens|wöchentlich\w*|"
    r"zusätzlich\w*|mindestens|maximal|max\.|min\.)", re.I)


def wahrscheinlichste(bewertungen: dict, k: int = WAHRSCHEINLICHSTE_JE_DOKUMENT) -> set[str]:
    """Die k E/T-Kriterien, bei denen das Modell `A` am nächsten war.

    Nur `E`/`T`: Ein `N` hätte keine Fundstelle, die ein `A` belegen könnte, und
    P(A) liegt auf den Abweichungen unter `N` ohnehin nahe null.

    Ohne mitgeschriebene Wahrscheinlichkeiten ordnet der Wert des Rangierers
    (`rang_abweichung`, src/pruefung/entscheider.py) — ähnlich viele
    Treffer. Fehlt auch der (kein Entscheider, älteres Ergebnis): leer.
    """
    geregelt = {nr: b for nr, b in bewertungen.items() if b.get("status") in ("E", "T")}
    if any(b.get("wahrscheinlichkeit") for b in geregelt.values()):
        kandidaten = [(b["wahrscheinlichkeit"].get("A", 0.0), nr)
                      for nr, b in geregelt.items() if b.get("wahrscheinlichkeit")]
    else:
        kandidaten = [(float(b["rang_abweichung"]), nr)
                      for nr, b in geregelt.items() if b.get("rang_abweichung") is not None]
    kandidaten = [(p, nr) for p, nr in kandidaten if p > 0]
    kandidaten.sort(key=lambda x: -x[0])
    return {nr for _, nr in kandidaten[:k]}


_WIDERSPRUCH = re.compile(r"widerspr", re.I)
_KEIN_WIDERSPRUCH = re.compile(
    r"(?:nicht|kein\w*|ohne)\s+(?:\w+\s+){0,3}widerspr|widerspruchsfrei|widerspricht\s+(?:\w+\s+){0,3}nicht",
    re.I)


def anzeichen(bewertung: dict, hinweis: dict | None,
              wahrscheinlich: bool = False) -> list[str]:
    """Alle Anzeichen eines Kriteriums, unabhängig von der Stufe."""
    status = bewertung.get("status", "N")
    gefunden = []
    if status == "A":
        gefunden.append("Modell")
    if hinweis:
        gefunden.append("Hinweis")
    if wahrscheinlich and status in ("E", "T"):
        gefunden.append("Wahrscheinlichkeit" if bewertung.get("wahrscheinlichkeit") else "Statistik")
    if status in ("E", "T") and bewertung.get("markenvorgabe"):
        gefunden.append("Markenvorgabe")
    if status in ("E", "T") and (bewertung.get("anteil_a") or 0.0) >= SCHWELLE_KRITERIUM:
        gefunden.append("Häufung")
    # Kostenfolge aus den Fundstellen (src/pruefung/kostenfolge.py) — auch bei N: Der
    # Satz liefert Begründung und Fundstelle, die Belegpflicht ist erfüllt.
    if status in ("E", "T", "N") and bewertung.get("kostenfolge"):
        gefunden.append("Kostenfolge")
    # Werte und Werkstoffe außerhalb des Belegten (src/pruefung/wertabgleich.py).
    if status in ("E", "T", "N"):
        gefunden += [a for a in ("Wert", "Werkstoff") if a in (bewertung.get("wertabgleich") or {})]
    # Gegenteil einer Standardanforderung, in zwei Schritten bestätigt (src/pruefung/gegenteil.py).
    if status in ("E", "T") and bewertung.get("gegenteil"):
        gefunden.append("Gegenteil")
    # Die Begründung eines vom Entscheider gehobenen Kriteriums schreibt der Code
    # („… beste Relevanz …"), nicht das Modell. Zahl/Norm las darin die
    # Prozentzahl und markierte bei „hoch" jedes gehobene Kriterium.
    if status in ("E", "T") and not bewertung.get("gehoben"):
        text = bewertung.get("begruendung") or ""
        if BINDUNG.search(text):
            gefunden.append("Beschaffung")
        if _ZAHL_NORM.search(_VERWEIS.sub(" ", text)):
            gefunden.append("Zahl/Norm")
        if _PFLICHT.search(text):
            gefunden.append("Pflicht")
        # Das Modell schreibt selbst „widerspricht dem Standard" und vergibt trotzdem
        # E. Der eigene Satz ist der Beleg.
        if _WIDERSPRUCH.search(text) and not _KEIN_WIDERSPRUCH.search(text):
            gefunden.append("Widerspruch")
    return gefunden


# Anzeichen, die ihren Beleg selbst aus den Fundstellen mitbringen.
_AUS_DEN_FUNDSTELLEN = {"Kostenfolge", "Wert", "Werkstoff", "Gegenteil"}


def _beleg(b: dict, herkunft: list[str]) -> tuple[str, str]:
    for a in herkunft:
        if a == "Kostenfolge" and b.get("kostenfolge"):
            return f"Kostenfolge im Lastenheft: {b['kostenfolge']['satz']}", b["kostenfolge"]["fundstelle"]
        if a == "Gegenteil" and b.get("gegenteil"):
            g = b["gegenteil"]
            return (f"Gegenteil der Standardanforderung „{g['anforderung']}“: {g['satz']}",
                    g["fundstelle"])
        w = (b.get("wertabgleich") or {}).get(a)
        if w:
            art = "Wert" if a == "Wert" else "Werkstoff"
            return (f"{art} außerhalb des im Standard Belegten ({w['wert']}; belegt: {w['belegt']}): "
                    f"{w['satz']}", w["fundstelle"])
    return b.get("begruendung", ""), b.get("fundstelle", "")


def markieren(ergebnis: dict, stufe: str = VORGABE) -> dict:
    """Hebt Kriterien mit Anzeichen der gewählten Stufe auf `A`. Ändert `ergebnis`.

    Ein `N` wird nur über einen Hinweis oder eine Kostenfolge gehoben — dann gibt es
    eine belegte Stelle, die Begründung und Fundstelle liefert (Belegpflicht R1).
    Ohne sie wäre ein `A` auf einem ungeregelten Punkt eine Behauptung ohne Beleg.
    Ist die Kostenfolge der einzige Grund, steht ihr Satz in der Begründung; die des
    Modells („… mit dem Standard vereinbar") bleibt in `begruendung_modell`.
    """
    if stufe not in STUFEN:
        raise ValueError(f"Unbekannte Stufe „{stufe}“ — erlaubt: {', '.join(STUFEN)}")
    reicht = set(STUFEN[stufe])
    hinweise: dict[str, dict] = {}
    for h in ergebnis.get("hinweise") or []:
        hinweise.setdefault(h.get("nr"), h)

    bewertungen = ergebnis.get("bewertungen") or {}
    nah: set[str] = set()
    if "Wahrscheinlichkeit" in reicht:
        # Die k kommen ZU den übrigen Anzeichen hinzu: Was schon aus anderem Grund
        # gehoben wird, belegt keinen der k Plätze.
        ohnehin = {nr for nr, b in bewertungen.items()
                   if set(anzeichen(b, hinweise.get(nr))) & (reicht | {"Modell"})}
        nah = wahrscheinlichste({nr: b for nr, b in bewertungen.items() if nr not in ohnehin})
    for nr, b in bewertungen.items():
        gefunden = anzeichen(b, hinweise.get(nr), nr in nah)
        b["herkunft"] = [a for a in gefunden if a == "Modell" or a in reicht]
        if b.get("status") == "A" or not (set(gefunden) & reicht):
            if b.get("status") != "A":
                b.pop("herkunft", None)
            continue
        b["status_modell"] = b.get("status", "N")
        h = hinweise.get(nr) if "Hinweis" in b["herkunft"] else None
        if b["status_modell"] == "N" and h:
            b["begruendung"] = f"Festlegung im Lastenheft: {h.get('text', '')}"
            b["fundstelle"] = h.get("fundstelle", "")
        elif b["status_modell"] == "N" or set(b["herkunft"]) <= _AUS_DEN_FUNDSTELLEN:
            # Kein eigenes Urteil des Modells trägt die Markierung: Der Satz aus den
            # Fundstellen wird Begründung und Beleg, die des Modells bleibt daneben.
            if b.get("begruendung"):
                b["begruendung_modell"] = b["begruendung"]
            b["begruendung"], b["fundstelle"] = _beleg(b, b["herkunft"])
        b["status"] = "A"
    ergebnis["markierung"] = stufe
    return ergebnis
