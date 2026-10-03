"""Hinweise statt Urteile: Wo legt der Kunde fest, was der Standard offenlässt?

Warum es dieses Modul gibt, obwohl `abweichung.py` bereits existiert:

Der Abweichungspass fragt „widerspricht das dem Musterlastenheft?" mit der
Kalibrierung „im Zweifel nein". Bei Temperatur 0 führt das zwangsläufig
fast immer zu „nein". Und die Regel selbst ist eng: Verschärfungen
widersprechen dem Standard nicht, sondern gehen über ihn hinaus. Sie sind als
`A` per Definition unerreichbar.

Dieses Modul dreht beides um.

**Keine Urteilsfrage, sondern eine Sachfrage.** Nicht „ist das eine Abweichung?",
sondern „legt das Lastenheft hier etwas Konkretes fest?". Das ist eine
Textauskunft, keine Wertung — und damit etwas, das ein 9B-Modell leisten kann.
Die Kalibrierung ist entsprechend die Belegpflicht, nicht „im Zweifel nein".

**Kein Status, sondern ein Hinweis.** Die Ausgabe verändert `E`/`T`/`A`/`N`
nicht. Sie steht daneben und sagt dem Bearbeiter: hier lohnt der Blick. Eine
Prüfhilfe muss nicht recht haben; sie muss die richtige Stelle zeigen.

## Warum nur ein Teil der Kriterien

Der Durchgang läuft nicht überall, sondern nur dort, wo das Musterlastenheft
selbst offen formuliert („vereinbart", „freigegeben", „abgestimmt", „nach
Rücksprache"). Das ist ein Teil der Kriterien, auf den überdurchschnittlich
viele Abweichungen entfallen. Als Detektor wäre das wertlos, als Vorfilter
trägt es. Das Urteil fällt danach das Modell, nicht der Filter.

Ein früherer Versuch, den Filter aus Oberflächenmerkmalen des KUNDENDOKUMENTS
zu bauen („Fa.", „Fabrikat", Name in Klammern), ist gescheitert: Herstellernamen
stehen in Lastenheften überall. Der Auslöser muss deshalb aus dem STANDARD
kommen, nicht aus dem Kundendokument.
"""

import json
import re
from dataclasses import dataclass

# Formulierungen, mit denen das Musterlastenheft eine Festlegung bewusst offen
# lässt. Gesucht wird in `standardanforderungen` und `auspraegungen_im_korpus`;
# beide Felder zusammen ergaben den besseren Vorfilter.
OFFEN = re.compile(
    r"herstellerneutral|nach freigabe|freigegeben|vereinbart|abgestimmt"
    r"|nach r[üu]cksprache|nach absprache", re.I)

FELDER = ("standardanforderungen", "auspraegungen_im_korpus")

# Modelle lassen ein Feld ungern leer und schreiben stattdessen die Verneinung
# aus: „Das Lastenheft legt keine konkreten Werte fest", „Nicht anwendbar",
# „Keine Mehrforderung gefunden". Ohne diesen Filter zählen solche Sätze als
# Befund. Die Verbliste zu verlängern half nicht — Verneinungen stehen an
# beliebiger Stelle im Satz. Entscheidend ist stattdessen die Position: Wer
# einen Befund meldet, verneint nicht im ersten Satzdrittel.
_VERNEINUNG = re.compile(
    r"^.{0,80}?\b(kein\w*|nicht|nichts|nein|n/?a|entf[äa]llt|unklar)\b"
    r"|nicht (anwendbar|zutreffend|relevant)",
    re.I | re.S)


@dataclass
class Hinweis:
    nr:          str
    art:         str   # "Festlegung" / "Mehrforderung" (Modelldurchgang)
                       # "Erzeugniswahl" (Detektor auf den Begründungen)
    text:        str   # was das Lastenheft regelt
    fundstelle:  str   # "S12"
    offene_stelle: str = ""   # die Standardformulierung, die es ausgelöst hat


def offene_kriterien(standard: dict[str, dict]) -> dict[str, str]:
    """Kriteriumsnummer -> die offene Formulierung des Standards.

    Nur diese Kriterien bekommen einen Hinweis-Durchgang.

    Zwei Wege, in dieser Reihenfolge:

    1. Die **gelesene Einordnung** aus `standardhaltung`, falls vorhanden und
       zum aktuellen Standard passend. Sie wählt weniger Kriterien und trifft
       dabei genauer — das Modell unterscheidet, ob ein Satz die HERSTELLERWAHL
       delegiert oder irgendetwas anderes vereinbart, was der Regex unten nicht
       kann.

    2. Der **Regex** darunter. Er braucht keinen Modellaufruf und greift immer
       — auch bei frisch übernommenem Musterlastenheft, bevor jemand die
       Einordnung gerechnet hat. Ein schwächerer Vorfilter ist besser als gar
       keine Hinweise.
    """
    from src.pruefung.standardhaltung import vorfilter

    gelesen = vorfilter(standard)
    return gelesen if gelesen else _regex_kriterien(standard)


def _regex_kriterien(standard: dict[str, dict]) -> dict[str, str]:
    """Die Rückfallebene: Signalwörter im Standardtext, ohne Modellaufruf.

    Eigene Funktion, damit sie prüfbar bleibt, wenn oben die gelesene
    Einordnung greift — sonst wäre der Weg, der im Zweifel einspringt, genau
    der, der nie getestet wird.
    """
    treffer = {}
    for nr, chunk in standard.items():
        for feld in FELDER:
            for satz in chunk.get(feld) or []:
                if OFFEN.search(str(satz)):
                    treffer[nr] = str(satz).strip()
                    break
            if nr in treffer:
                break
    return treffer


HINWEIS_PROMPT = """Du liest ein Kundenlastenheft für ein Druckgießwerkzeug und
beantwortest zwei Sachfragen. Du fällst KEIN Urteil darüber, ob etwas richtig
oder falsch ist.

KRITERIUM {nr} — {titel}

DAS MUSTERLASTENHEFT LÄSST HIER ETWAS OFFEN:
{offene_stelle}

VOLLSTÄNDIGE STANDARDANFORDERUNG:
{standard}

STELLEN AUS DEM KUNDENLASTENHEFT:
{belegstellen}

## Frage 1 — Festlegung

Legt das Kundenlastenheft an dieser Stelle etwas KONKRET und VERBINDLICH fest,
das die Standardanforderung offen lässt? Zum Beispiel einen namentlich genannten
Hersteller, ein Fabrikat, einen Typ, einen Lieferanten, eine bestimmte Norm oder
einen festen Zahlenwert.

## Frage 2 — Mehrforderung

Verlangt das Kundenlastenheft an dieser Stelle MEHR als die Standardanforderung?
Zum Beispiel zusätzliche Nachweise, Fristen, Kostenübernahmen, Berichtspflichten
oder Garantien, die dort nicht vorgesehen sind.

## Belegpflicht

Antworte nur, was WÖRTLICH in den Stellen oben steht. Gib zu jeder Antwort die
Seitenzahl an, auf der es steht. Findest du dazu nichts, lass das Feld leer —
ein leeres Feld ist eine richtige Antwort, eine erfundene nicht.

Schreibe die Verneinung NICHT aus. Kein „keine Festlegung gefunden", kein „nicht
anwendbar" — in diesem Fall gehört ein leerer Text in das Feld.

Formuliere knapp und benenne die Sache, nicht deren Bewertung. Übernimm dazu den
Wortlaut aus den Stellen oben — Bauteil, Hersteller, Typ, Wert, so wie es dort
steht. Schreibe NICHT, was der Kunde damit tut oder ob es zulässig ist.

## Ausgabeformat

Gib ausschließlich ein JSON-Objekt zurück, ohne umgebenden Text:

{{"festlegung": "", "seite_festlegung": "", "mehrforderung": "", "seite_mehrforderung": ""}}"""


# Kennungen der Korpusdokumente. Sie stehen im Standardblock des Prompts und
# haben in einem Bericht über ein fremdes Lastenheft nichts verloren — weder
# fachlich noch vertraulich.
_KORPUS_ID = re.compile(r"\bLHD-\d", re.I)


def _im_dokument_belegt(text: str, kandidaten: list[dict],
                        mindestanteil: float = 0.30) -> bool:
    """Stammt der Hinweis aus dem Kundendokument — oder aus dem Prompt?

    Anlass: Hinweise können aus dem Prompt selbst stammen — aus dem Standardblock
    (die dort mitgeführten Fabrikate aus den bekannten Ausprägungen) oder aus
    einem Beispiel im Prompt, das wörtlich zurückgegeben wird. Diese Prüfung
    fängt das ab.

    Geprüft wird der Anteil der Inhaltswörter, die in den Belegstellen
    vorkommen. Die Schwelle ist bewusst niedrig: Eine Zusammenfassung in
    eigenen Worten soll bestehen, ein abgeschriebener Standardsatz nicht.
    """
    if _KORPUS_ID.search(text):
        return False
    woerter = [w for w in re.findall(r"\w{4,}", text.lower())]
    if not woerter:
        return False
    beleg = " ".join(str(k.get("text", "")) for k in kandidaten).lower()
    treffer = sum(1 for w in woerter if w in beleg)
    return treffer / len(woerter) >= mindestanteil


def _seite(genannt, kandidaten: list[dict]) -> str:
    """Seitenangabe des Modells nur übernehmen, wenn sie zu einer Stelle passt."""
    seiten = {str(k.get("page")) for k in kandidaten}
    g = str(genannt or "").strip().lstrip("Ss")
    return f"S{g}" if g in seiten else f"S{kandidaten[0].get('page', '?')}"


def pruefe_hinweise(nr: str, titel: str, standard_text: str, offene_stelle: str,
                    kandidaten: list[dict], model: str, chat,
                    num_predict: int = 512, feld=None) -> list[Hinweis]:
    """Ein Aufruf je Kriterium, liefert null bis zwei Hinweise."""
    if not kandidaten:
        return []

    from src.pruefung.abweichung import formatiere_belegstellen
    from src.pruefung.kriterien import _first_json

    from src.muster.anwendungsfeld import uebertragen

    antwort = chat(model, uebertragen(HINWEIS_PROMPT, feld, format_sicher=True).format(
        nr=nr, titel=titel, standard=standard_text,
        offene_stelle=offene_stelle,
        belegstellen=formatiere_belegstellen(kandidaten),
    ), num_predict)
    if not antwort.ok:
        return []

    blob = _first_json(antwort.text)
    if not blob:
        return []
    try:
        daten = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if not isinstance(daten, dict):
        return []

    gefunden = []
    for feld, art in (("festlegung", "Festlegung"),
                      ("mehrforderung", "Mehrforderung")):
        text = str(daten.get(feld) or "").strip()
        # Leere Felder sind der Normalfall — und eine ausgeschriebene Verneinung
        # ist dasselbe wie ein leeres Feld, nur wortreicher.
        if len(text) < 8 or _VERNEINUNG.search(text):
            continue
        # Belegpflicht: Was im Kundendokument nicht steht, ist kein Hinweis
        # darauf, was der Kunde festlegt.
        if not _im_dokument_belegt(text, kandidaten):
            continue
        gefunden.append(Hinweis(
            nr=nr, art=art, text=text,
            fundstelle=_seite(daten.get(f"seite_{feld}"), kandidaten),
            offene_stelle=offene_stelle,
        ))
    return gefunden


# ── Zweiter Weg: der Detektor auf den Begründungen des Agenten ────────────────
#
# Frühere Detektoren suchten im KUNDENDOKUMENT oder in der Sprache der
# REFERENZLÖSUNG. Beides scheiterte: Herstellernamen stehen in Lastenheften
# überall, und die Urteilswörter der Referenz kommen im Quelltext nicht vor.
#
# Die dritte Quelle ist die EIGENE AUSGABE DES AGENTEN: Oft nennt das Modell
# das Herstellerkürzel in der eigenen Begründung — es sieht die Bindung und
# stuft trotzdem `E` ein. Die Begründung liegt bereits vor; der Durchgang kostet
# keinen zusätzlichen Modellaufruf.
#
# Er ändert keinen Status. Ein Hinweis ist kein Urteil — siehe das Modul oben.

# Beschaffungsvokabular, kein Fachvokabular eines Anwendungsfelds. Diese Wörter
# stehen in einem Lastenheft für Druckgießwerkzeuge so wie in einem für
# Schaltschränke oder Prüfstände; der Detektor trägt damit in ein anderes
# Anwendungsfeld mit.
#
# Die Wortstämme stehen ohne Wortgrenze, „Fabrikat" trifft also auch
# „Fabrikatsbindung" und „fabrikatsgebunden". Das ist hier richtig, und zwar
# aus einem Grund, der beim ersten Detektor noch umgekehrt lag:
#
# Jener suchte mit den Urteilswörtern der Referenz („fabrikatsgebunden",
# „typscharf") im KUNDENDOKUMENT. Dort stehen sie nicht — es ist die Sprache
# des Menschen, der kategorisiert hat, nicht die des Verfassers. Dieser hier
# liest die Begründung des AGENTEN, und der schreibt „was eine
# Fabrikatsbindung darstellt" durchaus selbst. Es gibt keinen Pfad, über den
# Referenzsprache in den gelesenen Text geraten könnte; der Einwand von damals
# greift an dieser Quelle nicht.
#
# `typscharf` stand kurzzeitig ausdrücklich in der Liste und ist wieder raus:
# Gegengeprüft über alle Begründungen der neun Dokumente kommt es null-mal vor.
# Ein Auslöser, der nie auslöst, täuscht Abdeckung vor.
BINDUNG = re.compile(
    r"\bFa\.|\bFirma\b|Fabrikat|Hersteller|Lieferant|\bMarke\b"
    r"|Typenbezeichnung", re.I)


def bindungsverdacht(begruendung: str) -> list[str]:
    """Die Auslöser in einer Begründung — leer, wenn keiner anschlägt."""
    return sorted({m.group(0).lower()
                   for m in BINDUNG.finditer(begruendung or "")})


def aus_begruendungen(ergebnis: dict, standard: dict[str, dict],
                      fundstellen: dict[str, list[dict]],
                      schon_gemeldet: set[str] | None = None) -> list[Hinweis]:
    """Hinweise aus den Begründungen, die der Agent selbst geschrieben hat.

    Zwei Bedingungen, beide aus dem STANDARD abgeleitet und keine aus der
    Referenzlösung — sonst wäre der Detektor an den Testfällen angepasst:

    1. Das Kriterium lässt die Erzeugniswahl offen (`typ_platzhalter`, also das
       Feld `platzhalter` des Musterlastenhefts).
    2. Die Begründung einer `E`-Einstufung nennt Beschaffungsvokabular.

    Nur `E`: Dort liegt der Fehler. Bei `N` ist die Begründung nach der
    Belegpflicht leer, es gibt also nichts zu lesen. `T` bleibt draußen.

    Die Fallzahl, an der das erprobt wurde, ist klein — eine belegte Spur, kein
    gesichertes Ergebnis.
    """
    from src.pruefung.kriterien import typ_platzhalter

    schon = schon_gemeldet or set()
    gefunden: list[Hinweis] = []

    for nr, bewertung in (ergebnis.get("bewertungen") or {}).items():
        if nr in schon:
            # Zu diesem Kriterium hat der Modelldurchgang schon etwas gemeldet.
            # Ein zweiter Eintrag zur selben Stelle ist im Bericht Rauschen.
            continue
        if not isinstance(bewertung, dict) or bewertung.get("status") != "E":
            continue

        offen = typ_platzhalter(standard.get(nr))
        if not offen:
            continue

        begruendung = str(bewertung.get("begruendung") or "").strip()
        ausloeser = bindungsverdacht(begruendung)
        if not ausloeser:
            continue

        # Belegpflicht — aber NICHT dieselbe wie beim Modelldurchgang.
        #
        # Dort muss der Hinweis den Wortlaut des Dokuments übernehmen. Eine Begründung
        # ist etwas anderes: eine Paraphrase mit Wörtern wie „regelt" und
        # „verbindlich", die im Kundendokument nicht vorkommen. Eine Schwelle auf den
        # Wortanteil trennt hier nicht und bleibt deshalb weg.
        #
        # Was bleibt, ist die Prüfung, für die es einen Grund gibt: Kennungen fremder
        # Kundendokumente dürfen nicht in einen Bericht geraten, der an einen Kunden
        # geht. Sie deckt den Fall ab, in dem ein Modell den Standardblock
        # nachplappert.
        kandidaten = fundstellen.get(nr) or []
        if not kandidaten or _KORPUS_ID.search(begruendung):
            continue

        gefunden.append(Hinweis(
            nr=nr, art="Erzeugniswahl", text=begruendung,
            fundstelle=_seite(str(bewertung.get("fundstelle") or "").lstrip("Ss"),
                              kandidaten),
            offene_stelle=(
                f"Der Standard macht zu {', '.join(offen)} keine Fabrikats- "
                f"oder Herstellervorgabe. Die Prüfung hat den Punkt als "
                f"geregelt eingestuft und dabei {', '.join(ausloeser)} genannt."),
        ))
    return gefunden
