"""Der Regelteil des Prompts.

Der Prompt ist an `qwen3.5:9b` kalibriert. Seine Verschärfungen korrigieren
denselben Fehler: Das Modell ist zu zurückhaltend und sagt „keine Vorgabe", wo
der Kunde regelt. Sätze wie „Das ist kein Aufruf zur Zurückhaltung" oder „E ist
der Normalfall" sind Gegengewichte gegen genau diese Neigung.

Der Text ist aus Bausteinen zusammengesetzt, damit sich einzelne Schalter
(Schritt 2, Listenpunkte, Fabrikatsbindung, Anwendungsfeld) gezielt umstellen
lassen, ohne den übrigen Wortlaut zu berühren.
"""

from __future__ import annotations

from src.muster import anwendungsfeld
from src.muster.anwendungsfeld import Anwendungsfeld


# ── Der Rumpf ─────────────────────────────────────────────────────────────────
# Die vier Status, die Reihenfolge der Fragen, die Rangfolge der Abweichungsarten,
# der Umgang mit OCR-Schrott.

_SCHRITT_1 = """## Entscheidungsreihenfolge

Gehe strikt in dieser Reihenfolge vor. Die erste Frage entscheidet über N, erst
danach geht es um den Grad.

Schritt 1 — Wird der Sachverhalt des Kriteriums in einer der gezeigten Stellen
überhaupt berührt? Achte dabei nur auf den Sachverhalt, nicht darauf, ob die
Regelung vollständig oder verbindlich ist.
  Nein  -> N. Fertig.
  Ja    -> weiter zu Schritt 2. N ist damit ausgeschlossen.
"""

# ── Schritt 2 in zwei Fassungen ───────────────────────────────────────────────
# Die Prüffrage selbst steht zur Debatte, nicht nur ihre Betonung.
#
# Anlass: Übersehene Abweichungen stuft das Modell meist als E ein, mit
# Begründungen nach demselben Bau: „regelt verbindlich <Tatbestand> … was mit der
# Standardanforderung vereinbar ist". Es nennt den gebundenen Markennamen sogar
# selbst und erklärt ihn im selben Satz für unbedenklich.
#
# Der Fehler steckt in der Frage. „Steht es im Widerspruch zum Standard?" lädt
# dazu ein, nach einem Gegensatz zu suchen. Einen Gegensatz gibt es nicht, wenn
# der Standard schweigt — und genau das Schweigen IST bei Fabrikaten die
# Anforderung. Das Modell liest Schweigen als Zustimmung.
#
# „hinausgehen" dreht die Frage um: nicht „widerspricht es?", sondern „verlangt
# der Kunde etwas, das der Standard nicht verlangt?". Ein Vergleich gegen eine
# Liste statt gegen eine Abwesenheit.

# Der Rahmensatz, nicht die Liste. Die Liste nennt „oder eine Verschärfung -> A"
# seit jeher; überfahren wurde sie von der E-Bedingung darunter, die allein auf
# den Widerspruch abstellte — eine Verschärfung widerspricht nicht, also landete
# sie auf E. Derselbe Bautyp wie beim Fabrikatshinweis:
# Regel in der Liste, Gegenteil im Rahmen.
#
# Geändert ist deshalb NUR die E-Bedingung, nicht die Struktur von Schritt 2.
# Das unterscheidet diese Fassung von `hinausgehen`, das den ganzen Schritt in
# eine Prüfliste umbaute („Bestandteil für Bestandteil", „auch nur einen") und
# damit überall feuerte.
_SCHRITT_2_WIDERSPRUCH = """
Schritt 2 — Vergleiche die Regelung mit der Standardanforderung:
  widersprechende Werte, andere Norm, andere Zuständigkeit, Fabrikatsbindung
  oder eine Verschärfung                                      -> A
  der Punkt ist verbindlich geregelt und bleibt dabei im
  Rahmen der Standardanforderung                              -> E
  der Punkt wird nur beiläufig gestreift oder ausdrücklich
  unverbindlich gehalten („nach Absprache", „sofern möglich",
  „kann", „wird empfohlen")                                   -> T

Verlangt der Kunde mehr als die Standardanforderung, ist das eine Abweichung —
auch ohne Widerspruch. Der Standard schweigt an vielen Stellen; sein Schweigen
ist keine Zustimmung.
"""

# Die frühere Fassung, Zeichen für Zeichen. Sie ist der Kontrollarm jedes A/B
# und die einzige Möglichkeit, die Kennzahlen der Testläufe 1 bis 3 zu
# reproduzieren — dort galt eine Verschärfung ausdrücklich NICHT als Abweichung.
_SCHRITT_2_NUR_WIDERSPRUCH = """
Schritt 2 — Vergleiche die Regelung mit der Standardanforderung:
  widersprechende Werte, andere Norm, andere Zuständigkeit, Fabrikatsbindung
  oder eine Verschärfung                                      -> A
  der Punkt ist verbindlich geregelt und steht nicht im
  Widerspruch zum Standard                                    -> E
  der Punkt wird nur beiläufig gestreift oder ausdrücklich
  unverbindlich gehalten („nach Absprache", „sofern möglich",
  „kann", „wird empfohlen")                                   -> T
"""

# ── Schritt 2, dritte Fassung: die Einschränkung ─────────────────────────────
# Diagnose, die zu diesem Block führte: Bei Fabrikatsbindungen nennt das Modell
# das Herstellerkürzel oft in der eigenen Begründung — es SIEHT die Bindung —
# und stuft trotzdem E oder N ein.
#
# Der Widerspruchs-Block oben führt „Fabrikatsbindung -> A" bereits — als ein
# Wort in einer Liste von sechs, eingerahmt von „steht nicht im Widerspruch zum
# Standard -> E". Die Regel steht da und wird überfahren, weil die Rahmenfrage
# in die Gegenrichtung zieht: Eine Bindung WIDERSPRICHT dem Standard nicht, sie
# verengt ihn. Auf die gestellte Frage antwortet das Modell richtig.
#
# Warum das nicht dasselbe ist wie `hinausgehen`: Jene Fassung fragte nach
# ALLEM, was der Standard nicht verlangt („auch nur ein Bestandteil"). Das
# feuerte überall, und das Modell wich auf N aus. Diese hier fragt NUR nach der
# Erzeugniswahl und nennt
# ausdrücklich den Fall, in dem sie NICHT gilt.
_SCHRITT_2_EINSCHRAENKUNG = """
Schritt 2 — Beantworte zuerst diese eine Frage, bevor du irgendetwas anderes
prüfst:

  NIMMT DER KUNDE EINE WAHL VORWEG, DIE DER STANDARD OFFENLÄSST?

Das ist ein Test in zwei Teilen. Beide müssen zutreffen.

  Teil 1: Die Standardanforderung oben benennt den Gegenstand, legt aber NICHT
          fest, von wem er stammt — sie nennt keinen Hersteller, kein Fabrikat,
          keinen Typ, keine Artikelnummer.
  Teil 2: Das Kundenlastenheft nennt genau das namentlich.

  Beide Teile treffen zu                                       -> A
  Der Standard nennt SELBST einen Hersteller oder verlangt
  Erzeugnisse aus einer freigegebenen Liste — dann nimmt der
  Kunde nichts weg, und dieser Test greift nicht           -> weiter unten

Eine solche Bindung widerspricht dem Standard nicht. Sie verengt ihn: Wo er
kein Fabrikat nennt, ist die Wahl frei, und eine verbindliche Nennung des
Kunden nimmt sie weg. Genau das ist gemeint, wenn hier von Abweichung die Rede
ist — nicht ein Gegensatz.

Erst wenn dieser Test nicht greift, vergleiche wie folgt:
  widersprechende Werte, andere Norm, andere Zuständigkeit
  oder eine Verschärfung                                       -> A
  der Punkt ist verbindlich geregelt                           -> E
  der Punkt wird nur beiläufig gestreift oder ausdrücklich
  unverbindlich gehalten („nach Absprache", „sofern möglich",
  „kann", „wird empfohlen")                                    -> T
"""

_SCHRITT_2_HINAUSGEHEN = """
Schritt 2 — Frage NICHT „widerspricht es dem Standard?". Frage: „Verlangt der
Kunde etwas, das der Standard nicht verlangt?"

Gehe die Regelung des Kunden Bestandteil für Bestandteil durch. Für jeden
Bestandteil prüfst du, ob die oben gezeigte Standardanforderung dasselbe
verlangt. Findest du auch nur einen Bestandteil, der dort nicht steht:

  Der Kunde nennt einen Hersteller, ein Fabrikat, einen Typ, eine
  Artikelnummer oder einen Lieferanten, den der Standard nicht nennt   -> A
  Der Kunde verlangt eine Pflicht, eine Kostenübernahme, einen
  Nachweis oder eine Frist, die der Standard nicht verlangt            -> A
  Der Kunde beruft sich auf eine Norm oder ein Regelwerk, das der
  Standard nicht nennt                                                 -> A
  Ein Zahlenwert liegt außerhalb der belegten Ausprägungen             -> A
  Eine andere Stelle ist zuständig als im Standard                     -> A

  Sonst, und der Punkt ist verbindlich geregelt                        -> E
  Sonst, und der Punkt wird nur beiläufig gestreift oder ausdrücklich
  unverbindlich gehalten („nach Absprache", „sofern möglich", „kann",
  „wird empfohlen")                                                    -> T

Dass der Standard zu einem Punkt SCHWEIGT, ist keine Zustimmung. Er ist aus
@@KORPUS@@ zusammengetragen und bei Zukaufteilen bewusst herstellerneutral
gehalten: Wo er kein Fabrikat nennt, ist die Wahl frei — und eine verbindliche
Nennung des Kunden nimmt sie weg. Das ist der häufigste Abweichungsfall
überhaupt.

Schreibst du in der Begründung ein Fabrikat, eine Typnummer, eine fremde Norm
oder eine zusätzliche Pflicht des Kunden hin, dann ist das der Beleg für A —
nicht für E.
"""

# Der Kopf der A-Definition in zwei Fassungen. Die weite gilt nur mit
# `verschaerfung` — bis zu diesem Umbau stand sie versehentlich fest in _SKALA
# und damit auch in der Vorgabe, obwohl der Schalter aus war.
_A_KOPF_ENG = """A  Abweichung — Die Regelung des Kunden WIDERSPRICHT dem Standard. Nach Häufigkeit
   im Referenzkorpus:"""
_A_KOPF_WEIT = """A  Abweichung — Die Regelung des Kunden WIDERSPRICHT dem Standard ODER GEHT ÜBER
   IHN HINAUS. Beides ist eine Abweichung; für den Werkzeugbau kostet eine
   Mehrforderung genauso Geld wie ein Widerspruch. Nach Häufigkeit im
   Referenzkorpus:"""

_SKALA = """
## Bewertungsskala

Vergib je Kriterium genau einen dieser vier Werte:

E  entspricht — Der Punkt ist verbindlich geregelt und mit der Standardanforderung
   vereinbar: gleiche Stoßrichtung, keine widersprechenden Werte, Zuständigkeiten wie
   im Standard. Setzt der Kunde für einen Platzhalter einen konkreten, branchenüblichen
   Wert ein, ist das E und keine Abweichung. Eine knappere Formulierung als im Standard
   bleibt E, solange sie verbindlich ist und nicht widerspricht.

T  teilweise — Der Punkt wird nur gestreift: beiläufig in einem Nebensatz erwähnt,
   ausdrücklich unverbindlich gehalten, oder einer späteren Abstimmung überlassen.
   Nicht T ist eine verbindliche Regelung, die lediglich weniger Aspekte nennt als
   die aggregierte Standardanforderung.

A  Abweichung — Die Regelung des Kunden WIDERSPRICHT dem Standard. Nach Häufigkeit
   im Referenzkorpus:
   1. Fabrikats-, Typ- oder Lieferantenbindung bei Zukaufteilen, wo der Standard die
      Wahl offen lässt oder nur neutrale Merkmale fordert — etwa ein namentlich
      genannter Normalienhersteller, Sensorhersteller, Stahllieferant oder Beschichter,
      dessen Erzeugnis ausschließlich zu verwenden ist. Häufigster Fall.
   2. Eine über den Standard hinausgehende Verschärfung: zusätzliche Pflichten,
      Kostenübernahmen oder Nachweise, die der Standard nicht vorsieht.
   3. Ein Zahlenwert, der dem Standard oder den belegten Spannweiten widerspricht.
   4. Eine andere Zuständigkeit als im Standard.
   5. Eine andere Norm oder ein anderes Regelwerk — im Korpus der seltenste Fall.

   Kein A ist es, wenn der Standard dieselbe Bindung selbst vorschreibt, oder wenn der
   Kunde lediglich auf eine eigene Werk- oder Betriebsnorm verweist.

N  keine Vorgabe — Im Lastenheft findet sich zu diesem Kriterium keine Regelung.

N ist kein Mangel und keine Abweichung. Es bedeutet, dass der Kunde zu diesem Punkt
nichts vorgegeben hat. Vermische die beiden Kategorien unter keinen Umständen. Sie
werden getrennt ausgewertet und N fällt aus der Abweichungsquote heraus.

## Belegpflicht

Jede Einstufung außer N braucht eine Fundstelle im geprüften Dokument und eine
Kurzbegründung in einem Satz. Findest du keine Fundstelle, lautet der Status N.

## Fundstellen, die nicht zählen

Ein Stichworttreffer allein begründet keine Regelung. Verwirf Treffer aus
Inhaltsverzeichnissen, Kopf- und Fußzeilen, Abbildungs- und Tabellenverzeichnissen
sowie Treffer, die inhaltlich zu einem anderen Sachverhalt gehören. Ordne eine
Textstelle immer dem Kriterium zu, dessen Sachverhalt sie tatsächlich regelt.
Beispiel: „Die Legierungsbezeichnung ist am Angusskanal einzugravieren" belegt
4.15 Kennzeichnung, nicht 4.8 Gießsystem.
"""

# ── Fabrikatsbindung ist keine Abweichung ────────────────────────────────────
# Schreibt der Kunde für ein Zukaufteil ein Fabrikat, einen Typ oder einen
# Lieferanten vor, konkretisiert er den Punkt — E, nicht A. Die Ersetzungen unten
# nehmen die Bindung als Abweichungsfall heraus; mit `fabrikat_ist_abweichung=True`
# bleibt der frühere Wortlaut.
_OHNE_FABRIKAT = (
    ("  widersprechende Werte, andere Norm, andere Zuständigkeit, Fabrikatsbindung\n"
     "  oder eine Verschärfung                                      -> A",
     "  widersprechende Werte, andere Norm, andere Zuständigkeit\n"
     "  oder eine Verschärfung                                      -> A"),
    ("   1. Fabrikats-, Typ- oder Lieferantenbindung bei Zukaufteilen, wo der Standard die\n"
     "      Wahl offen lässt oder nur neutrale Merkmale fordert — etwa ein namentlich\n"
     "      genannter Normalienhersteller, Sensorhersteller, Stahllieferant oder Beschichter,\n"
     "      dessen Erzeugnis ausschließlich zu verwenden ist. Häufigster Fall.\n"
     "   2. Eine über den Standard hinausgehende Verschärfung: zusätzliche Pflichten,\n"
     "      Kostenübernahmen oder Nachweise, die der Standard nicht vorsieht.\n"
     "   3. Ein Zahlenwert, der dem Standard oder den belegten Spannweiten widerspricht.\n"
     "   4. Eine andere Zuständigkeit als im Standard.\n"
     "   5. Eine andere Norm",
     "   1. Eine über den Standard hinausgehende Verschärfung: zusätzliche Pflichten,\n"
     "      Kostenübernahmen oder Nachweise, die der Standard nicht vorsieht. Häufigster Fall.\n"
     "   2. Ein Zahlenwert, der dem Standard oder den belegten Spannweiten widerspricht.\n"
     "   3. Eine andere Zuständigkeit als im Standard.\n"
     "   4. Eine andere Norm"),
    ("   Kein A ist es, wenn der Standard dieselbe Bindung selbst vorschreibt, oder wenn der\n"
     "   Kunde lediglich auf eine eigene Werk- oder Betriebsnorm verweist.",
     "   Kein A ist es, wenn der Kunde für ein Zukaufteil einen Hersteller, ein Fabrikat,\n"
     "   einen Typ oder einen Lieferanten vorschreibt — das konkretisiert den Punkt und ist E.\n"
     "   Ebenso kein A ist der Verweis auf eine eigene Werk- oder Betriebsnorm."),
)


def ohne_fabrikatsbindung(text: str) -> str:
    """Nimmt die Fabrikatsbindung als Abweichungsfall aus dem Regelteil."""
    for alt, neu in _OHNE_FABRIKAT:
        assert alt in text, f"Regelteil geändert — Ersetzung passt nicht mehr: {alt[:60]!r}"
        text = text.replace(alt, neu)
    return text


_SCHLUSS = """
## Unsauberer Text

Die Stellen stammen aus maschinell erschlossenen Scans. Rechtschreibfehler,
zerrissene Wörter und verlorene Tabellenstruktur sind normal und sprechen nicht
gegen eine Regelung. Beurteile den erkennbaren Inhalt, nicht die Textqualität.

## Unsichere Zahlenwerte

Die geprüften Dokumente sind teilweise gescannt und per OCR erschlossen. Zahlenwerte
aus Tabellen und Zeichnungsköpfen sind unzuverlässig. Werte, die offensichtlich
verlesen sind, dürfen nicht als harte Abweichung gewertet werden."""


# ── Gegengewichte gegen zu viel N ─────────────────────────────────────────────
# E ausdrücklich zum Normalfall erklären, damit Unvollständigkeit gegenüber dem
# Aggregat nicht als T oder N endet.
_NACH_SCHRITT_1 = """
E ist der Normalfall für geregelte Punkte. Die Standardanforderung ist aus
@@KORPUS@@ zusammengetragen; KEIN einzelnes Lastenheft enthält sie
vollständig. Regelt der Kunde den Punkt verbindlich und ohne Widerspruch, ist das
E — auch wenn seine Formulierung kürzer ausfällt als die Standardanforderung oder
nur einen der dort aufgezählten Aspekte nennt. Unvollständigkeit gegenüber dem
Aggregat ist KEIN Grund für T.

T ist die Ausnahme für unverbindliche oder beiläufige Erwähnungen — nicht die
Verlegenheitsantwort für „nicht alles abgedeckt".

N heißt ausschließlich: Der Kunde sagt zu diesem Sachverhalt nichts.
"""

# Der Nachsatz verhindert, dass der Verwerfungsabschnitt darüber als generelle
# Erlaubnis zum Zweifeln gelesen wird.
_NACH_FUNDSTELLEN = """
Das ist kein Aufruf zur Zurückhaltung: Verwirf eine Stelle nur, wenn sie einen
ANDEREN Sachverhalt regelt oder aus einem Verzeichnis stammt — nicht, weil sie
knapp, unvollständig oder unverbindlich formuliert ist. Solche Stellen sind T.
"""


# ── Listenpunkte ──────────────────────────────────────────────────────────────
# Viele Lastenhefte im Korpus sind nummerierte Anforderungslisten, keine
# Fließtexte. Die Referenz zählt einen solchen Punkt als Regelung — Aufbau:
# Gliederungsnummer, Nominalphrase, oft eine Klammer mit Ausführungsvarianten,
# kein Verb.
#
# Das Beispiel unten ist ERFUNDEN und bewusst kein Zitat aus einem
# Kundenlastenheft. Für den Zweck — dem Modell die Bauform zeigen — genügt ein
# Beispiel derselben Form. Erprobt ohne messbaren Effekt; der Schalter ist aus.
#
# Der Prompt sagte bisher das Gegenteil — „Ein Stichworttreffer allein
# begründet keine Regelung." Das Modell befolgte die Anweisung und sagte N, wo
# die Referenz E oder T führt.
#
# Der Auftraggeber hat die Frage beantwortet: Ein benannter Punkt auf einer
# Spezifikationsliste IST eine Vorgabe. Der Zusatz unten setzt das um, ohne
# den Schutz gegen Inhaltsverzeichnisse aufzugeben — der Unterschied ist die
# Seitenzahl: Ein Verzeichniseintrag verweist auf eine andere Stelle, ein
# Listenpunkt verlangt dort etwas.
_LISTENPUNKTE = """
Nicht ausformuliert heißt nicht ungeregelt. Viele Lastenhefte sind als
nummerierte Anforderungslisten geschrieben. Benennt ein Punkt einen
Sachverhalt, den der Auftragnehmer festzulegen, darzustellen oder auszuführen
hat, ist das eine Vorgabe — auch ohne Verb und ohne vollständigen Satz.

  „4.3 Art der Werkzeugkühlung (Anschlussart: Steckkupplung, oder dgl.)"
  ist eine Vorgabe zur Werkzeugkühlung, kein bloßer Stichworttreffer.

Entscheidend ist, ob der Punkt zum Gegenstand des Kriteriums etwas verlangt,
nicht wie ausführlich er formuliert ist. Über den Grad entscheidet weiterhin
Schritt 2: verbindlich benannt ist E, ausdrücklich unverbindlich gehalten ist T.

Davon unberührt bleiben Verzeichnisse. Ein Eintrag, der mit einer Seitenzahl
oder Punktreihe auf eine ANDERE Stelle verweist, ist ein Wegweiser dorthin und
keine Regelung.
"""


def regeln(hinausgehen: bool = False,
           listenpunkte: bool = False, einschraenkung: bool = False,
           verschaerfung: bool = False, feld: "Anwendungsfeld | None" = None,
           fabrikat_ist_abweichung: bool = False) -> str:
    """Der Regelteil des Prompts.

    `fabrikat_ist_abweichung` stellt den früheren Wortlaut wieder her
    („Fabrikatsbindung -> A"). Vorgabe aus: Eine Fabrikatsbindung ist eine
    Konkretisierung (E). `hinausgehen` und `einschraenkung` tragen ihre eigenen
    Schritt-2-Blöcke, die auf Fabrikate zielen; sie bleiben unverändert.

    Drei Fassungen von Schritt 2, die sich gegenseitig ausschließen:

    * Vorgabe — „widerspricht es dem Standard?"
    * `hinausgehen` — „verlangt der Kunde etwas, das der Standard nicht
      verlangt?". Erprobt und schlechter, weil die Frage auf alles zutrifft und
      das Modell auf N auswich.
    * `einschraenkung` — „nimmt der Kunde eine Wahl vorweg, die der Standard
      offenlässt?". Eng auf die Erzeugniswahl begrenzt, mit ausdrücklicher
      Ausnahme, wenn der Standard selbst ein Fabrikat nennt.

    `verschaerfung` (Vorgabe an) sagt, dass eine Mehrforderung eine Abweichung
    ist, auch ohne Widerspruch — die Festlegung des Auftraggebers. Sie ändert
    den Rahmensatz, nicht den Aufbau von Schritt 2, und gilt nur für die
    Vorgabefassung: `hinausgehen` und `einschraenkung` bringen eigene
    Schritt-2-Blöcke mit.

    Auf False gesetzt, steht wieder die frühere, engere Regel („nur ein
    Widerspruch ist eine Abweichung"). Das ist der Kontrollarm jedes A/B.
    """
    if hinausgehen and einschraenkung:
        raise ValueError("hinausgehen und einschraenkung schließen sich aus — "
                         "beide ersetzen Schritt 2.")
    schritt2 = (_SCHRITT_2_EINSCHRAENKUNG if einschraenkung
                else _SCHRITT_2_HINAUSGEHEN if hinausgehen
                else _SCHRITT_2_WIDERSPRUCH if verschaerfung
                else _SCHRITT_2_NUR_WIDERSPRUCH)
    # Der Listenpunkt-Zusatz steht direkt hinter dem Verwerfungsabschnitt, den
    # er einschraenkt — sonst laesst er sich als allgemeine Erlaubnis lesen.
    liste = _LISTENPUNKTE if listenpunkte else ""

    feld = feld or anwendungsfeld.aktuell()
    # `hinausgehen` und `einschraenkung` bringen eigene Schritt-2-Blöcke mit; der
    # Schalter gilt nur für die Vorgabe.
    weit  = verschaerfung and not (hinausgehen or einschraenkung)
    skala = _A_KOPF_WEIT.join(_SKALA.split(_A_KOPF_ENG)) if weit else _SKALA
    text = (_SCHRITT_1 + schritt2 + _NACH_SCHRITT_1 + skala + liste
            + _NACH_FUNDSTELLEN + _SCHLUSS)
    if not fabrikat_ist_abweichung and not (hinausgehen or einschraenkung):
        text = ohne_fabrikatsbindung(text)
    if not feld.korpusbefunde:
        text = neutralisiere(text)
    return text.replace("@@KORPUS@@", feld.korpus_dativ)


# ── Fassung für ein anderes Anwendungsfeld ────────────────────────────────────
# Der Regelteil enthält Aussagen, die am Druckguss-Korpus gemessen sind: die
# Rangfolge der Abweichungsarten („Häufigster Fall", „seltenste Fall"),
# Beispiele aus dem Werkzeugbau und eine Zuordnung mit Kriteriumsnummern. Für ein
# anderes Feld stimmen sie nicht und steuern das Urteil trotzdem.
#
# Ersetzt wird deshalb gezielt, nicht umgeschrieben: dieselben Regeln, derselbe
# Aufbau, nur ohne das, was für das neue Feld niemand belegt hat. Jede Stelle
# muss vorhanden sein — ändert jemand den gemessenen Wortlaut, fällt es hier auf
# statt still eine halb neutrale Fassung zu erzeugen.
_NEUTRAL = (
    ("Nach Häufigkeit\n   im Referenzkorpus:", "Typische Fälle:"),
    ("Nach Häufigkeit im\n   Referenzkorpus:", "Typische Fälle:"),
    ("für den Werkzeugbau kostet", "für den Auftragnehmer kostet"),
    ("genannter Normalienhersteller, Sensorhersteller, Stahllieferant oder Beschichter,\n"
     "      dessen Erzeugnis ausschließlich zu verwenden ist. Häufigster Fall.",
     "genannter Hersteller oder Lieferant, dessen Erzeugnis ausschließlich zu\n"
     "      verwenden ist."),
    ("Kostenübernahmen oder Nachweise, die der Standard nicht vorsieht. Häufigster Fall.",
     "Kostenübernahmen oder Nachweise, die der Standard nicht vorsieht."),
    (" — im Korpus der seltenste Fall.", "."),
    ("\nBeispiel: „Die Legierungsbezeichnung ist am Angusskanal einzugravieren\" belegt\n"
     "4.15 Kennzeichnung, nicht 4.8 Gießsystem.", ""),
    (" Das ist der häufigste Abweichungsfall\nüberhaupt.", ""),
)


def neutralisiere(text: str) -> str:
    """Entfernt die Korpusbefunde des gemessenen Felds aus einem Regeltext."""
    getroffen = 0
    for alt, neu in _NEUTRAL:
        if alt in text:
            text = text.replace(alt, neu)
            getroffen += 1
    # Mindestens Kopf, Beispiele und Rangfolge der Skala müssen gegriffen haben;
    # sonst hat sich der Wortlaut verschoben und die Neutralisierung ist leer.
    assert getroffen >= 4, (
        f"nur {getroffen} Korpusbefunde gefunden — der Regelteil hat sich "
        f"verschoben, _NEUTRAL anpassen")
    assert "Häufigster Fall" not in text and "Referenzkorpus" not in text
    return text
