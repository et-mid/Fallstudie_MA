"""Eigener Durchgang zur Erkennung von Abweichungen.

Warum getrennt: Abweichungen sind selten. Ein Modell, das aus vier
Möglichkeiten eine wählen soll, greift die seltene fast nie. Eine gezielte
Ja/Nein-Frage nach bereits geklärtem E/T ist für ein kleines Modell leichter.

Die entscheidende Regel: Eine Abweichung liegt nur vor, wenn die Kundenregelung
dem Musterlastenheft WIDERSPRICHT. Das ist keine Formalie — der Standard ist
nicht durchgehend herstellerneutral und verlangt an manchen Kriterien selbst
Vorgaben des Auftraggebers zu Fabrikaten. Ein Herstellername im Kundendokument
ist deshalb für sich genommen kein Befund; er wird erst dort einer, wo der
Standard die Wahl offen lässt.

Der Durchgang läuft bei jedem als geregelt eingestuften Kriterium, mit einem
Aufruf über alle Belegstellen zusammen. Ein lexikalischer Vorfilter war der
naheliegende Weg, trennt aber nichts: Die Auslöserwörter stammten aus den
Begründungen der Referenzlösung, also aus der Sprache des Menschen, der
kategorisiert hat. Im Kundendokument steht nur der Herstellername selbst.

Kosten: deutlich mehr Laufzeit je Dokument.
"""

from dataclasses import dataclass


@dataclass
class Abweichungsbefund:
    ist_abweichung: bool
    art:            str = ""
    begruendung:    str = ""
    fundstelle:     str = ""


ABWEICHUNGS_PROMPT = """Du prüfst eine einzelne Stelle eines Kundenlastenhefts für ein
Druckgießwerkzeug auf eine Abweichung vom Musterlastenheft.

KRITERIUM {nr} — {titel}

WAS DAS MUSTERLASTENHEFT VERLANGT:
{standard}

STELLEN AUS DEM KUNDENLASTENHEFT:
{belegstellen}

## Die einzige Frage

Widerspricht die Kundenregelung dem Musterlastenheft?

Eine Abweichung liegt NUR vor, wenn ein echter Widerspruch besteht. Eine Regelung,
die den Punkt lediglich präziser, ausführlicher oder mit anderen Worten fasst als
das Musterlastenheft, ist KEINE Abweichung.

Diese fünf Arten von Widerspruch kommen vor, nach Häufigkeit:

1  Bindung — Der Kunde schreibt für ein Zukaufteil ein Fabrikat, einen Typ oder
   einen Lieferanten namentlich und ausschließlich vor, WÄHREND das Musterlastenheft
   die Wahl offen lässt oder nur neutrale Merkmale fordert.
   ACHTUNG: Verlangt das Musterlastenheft selbst eine solche Bindung oder eine
   Vorgabe durch den Auftraggeber, ist es KEINE Abweichung.

2  Verschärfung — Der Kunde fordert Pflichten, Kostenübernahmen, Nachweise oder
   Fristen, die das Musterlastenheft nicht vorsieht.

3  Wert — Ein Zahlenwert widerspricht dem Musterlastenheft oder liegt außerhalb der
   dort belegten Spannweite. Achtung: Der Text stammt aus maschineller Texterkennung;
   ein offensichtlich verlesener Zahlenwert ist kein Befund.

4  Zuständigkeit — Verantwortung oder Gewährleistung liegt bei einer anderen Partei
   als im Musterlastenheft.

5  Regelwerk — Es gilt eine andere Norm als im Musterlastenheft. Der bloße Verweis
   auf eine Werk- oder Betriebsnorm des Kunden ist KEINE Abweichung.

@@ZWEIFEL@@

## Ausgabeformat

Gib ausschließlich ein JSON-Objekt zurück, ohne umgebenden Text:

{{"abweichung": false, "art": "", "begruendung": "", "seite": ""}}

Bei einem Widerspruch: abweichung true, art genau einer von Bindung, Verschärfung,
Wert, Zuständigkeit, Regelwerk, seite die Seitenzahl der belegenden Stelle, und
begruendung ein Satz nach dem Muster „<was der Kunde regelt>; das Musterlastenheft
sieht <was> vor"."""


ZWEIFEL_NEIN = """Im Zweifel lautet die Antwort NEIN. Ein zu Unrecht gemeldeter Widerspruch kostet
den Leser mehr Zeit als ein übersehener."""

# Gegenrichtung: Die Meldungen gehen an den Fachbereich zur Durchsicht, eine
# übersehene Abweichung kostet mehr als ein Blick zu viel. Gedacht für wenige,
# vorab ausgewählte Kriterien; erprobt ohne Wirkung.
ZWEIFEL_JA = """Im Zweifel lautet die Antwort JA. Jede gemeldete Abweichung wird von einem
Fachmann durchgesehen; eine übersehene kostet mehr als ein Blick zu viel."""


def formatiere_belegstellen(kandidaten: list[dict]) -> str:
    return "\n\n---\n\n".join(
        f"[Seite {k.get('page', '?')}]\n{k.get('text', '')}" for k in kandidaten)


def pruefe_abweichung(nr: str, titel: str, standard_text: str,
                      kandidaten: list[dict], model: str, chat,
                      num_predict: int = 512,
                      im_zweifel_ja: bool = False) -> Abweichungsbefund:
    """Ein gezielter Aufruf über alle Belegstellen eines Kriteriums.

    `chat` ist die LLM-Funktion aus kriterien.py — hereingegeben statt importiert,
    damit dieses Modul ohne Ollama testbar bleibt.
    """
    if not kandidaten:
        return Abweichungsbefund(False)

    from src.muster.anwendungsfeld import uebertragen

    vorlage = ABWEICHUNGS_PROMPT.replace("@@ZWEIFEL@@", ZWEIFEL_JA if im_zweifel_ja else ZWEIFEL_NEIN)
    prompt = uebertragen(vorlage, format_sicher=True).format(
        nr=nr, titel=titel, standard=standard_text,
        belegstellen=formatiere_belegstellen(kandidaten),
    )

    antwort = chat(model, prompt, num_predict)
    if not antwort.ok:
        return Abweichungsbefund(False)

    from src.pruefung.kriterien import _first_json
    import json

    blob = _first_json(antwort.text)
    if not blob:
        return Abweichungsbefund(False)
    try:
        daten = json.loads(blob)
    except json.JSONDecodeError:
        return Abweichungsbefund(False)
    if not isinstance(daten, dict) or daten.get("abweichung") is not True:
        return Abweichungsbefund(False)

    begruendung = str(daten.get("begruendung", "")).strip()
    if not begruendung:
        # Ohne Begründung keine Umstufung — die Belegpflicht gilt hier genauso.
        return Abweichungsbefund(False)

    # Seitenangabe des Modells nur übernehmen, wenn sie zu einer Belegstelle passt.
    seiten = {str(k.get("page")) for k in kandidaten}
    genannt = str(daten.get("seite", "")).strip().lstrip("Ss")
    seite = genannt if genannt in seiten else str(kandidaten[0].get("page", "?"))

    return Abweichungsbefund(
        True,
        art=str(daten.get("art", "")).strip(),
        begruendung=begruendung,
        fundstelle=f"S{seite}",
    )
