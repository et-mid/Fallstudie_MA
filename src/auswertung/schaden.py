"""Nicht jeder Fehler kostet gleich viel.

Exact Match zählt Treffer. Für die Frage „welches Modell soll laufen" ist das
zu grob: Eine übersehene Fabrikatsbindung landet unbemerkt im Vertrag, eine
Verwechslung von E und T steht so oder so auf der Liste und wird gelesen. Beide
zählen als ein Fehler.

Dieses Modul gewichtet Fehler nach dem, was sie im Arbeitsablauf anrichten.

## Der Arbeitsablauf, aus dem die Gewichte kommen

Der Prüfbericht geht an einen Bearbeiter, der entscheidet, welche Punkte vor
Angebot oder Auftragsannahme geklärt werden müssen. Daraus folgen vier
Fehlerklassen mit sehr verschiedenen Folgen:

1. **Übersehene Abweichung** (Referenz A, Agent E oder N). Der Punkt gilt als
   erledigt und wird nicht angesehen. Die Bindung an ein Fabrikat oder eine
   Verschärfung geht in den Vertrag. Teuerster Fall — und der einzige, der
   nach außen wirkt.
2. **Erfundene Regelung** (Referenz N, Agent E oder T). Der Bearbeiter hält
   einen offenen Punkt für geklärt und spricht ihn beim Kunden nicht an.
   Erzeugt falsche Sicherheit; fällt erst auf, wenn es teuer wird.
3. **Übersehene Regelung** (Referenz E oder T, Agent N). Der Kunde hat etwas
   vorgegeben, der Bericht sagt nichts. Der Bearbeiter wendet den Hausstandard
   an. Da E heißt „mit dem Standard vereinbar", geht das meist gut aus — der
   Verhandlungsstand ist trotzdem falsch abgebildet.
4. **Fehlalarm** (Agent meldet A, Referenz sagt etwas anderes). Kostet eine
   Prüfung, die nichts ergibt. Ärgerlich, aber selbstkorrigierend: Es wird
   hingesehen.

## Warum die Zahlen angreifbar sind — und was dagegen hilft

Die Gewichte unten sind **gesetzt, nicht gemessen**. Sie beruhen auf einer
Einschätzung des Arbeitsablaufs, nicht auf erhobenen Kosten. Wer sie anders
setzt, bekommt andere Zahlen; das ist der Kern der Kritik an jeder gewichteten
Kennzahl.

Zwei Vorkehrungen machen sie trotzdem brauchbar:

* Die Kennzahl ersetzt Exact Match nicht, sie steht daneben. Wo beide dasselbe
  sagen, ist die Aussage robust; wo sie auseinandergehen, ist die Gewichtung
  der Grund und muss diskutiert werden.
* `sensitivitaet()` verschiebt die Gewichte über den ganzen plausiblen Bereich
  und prüft, ob die Rangfolge hält. Eine Rangfolge, die jede Gewichtung
  überlebt, hängt nicht an meiner Setzung. Eine, die kippt, ist kein Ergebnis.

Ohne diese zweite Vorkehrung wäre die Kennzahl nur eine Meinung mit
Nachkommastellen.

## Was sie nicht kann

Die Matrix rechnet **je Kriterium und linear**. Ein Werkzeug, das bei fast
allen Kriterien Alarm schlägt, kostet in Wirklichkeit mehr als die Summe der
Fehlalarme: Es wird abgeschaltet. Dieser Vertrauensverlust ist nichtlinear und
in keiner Zellgewichtung unterzubringen. Deshalb steht `baselines()` daneben —
auch „immer A“ erreicht eine Güte deutlich über null, und diese Zahl ist eine
Warnung an den Leser, nicht ein Lob für die Strategie.

Zweitens belohnt die Gewichtung **sicheres Danebenliegen**. Ein Modell, das im
Zweifel `N` sagt, sammelt billige Fehler (E → N kostet 0,5) statt teurer. Das
ist gewollt — Zurückhaltung ist im Zweifel richtig —, macht die Güte aber
untauglich als alleinige Kennzahl. Sie sagt, wie teuer die Fehler sind, nicht
wie nützlich das Werkzeug ist.
"""

from __future__ import annotations

from collections import Counter

STATUS = ("E", "T", "A", "N")

# Schadenspunkte je (Referenz, Agent). 0 = richtig, 1 = schlimmstmöglich.
#
# Zeile A ist die teure: Eine Abweichung, die als E oder N durchgeht, ist der
# einzige Fehler, der das Haus verlässt. A -> T bekommt 0,5, weil der Punkt
# immerhin als klärungsbedürftig auf der Liste steht und angesehen wird.
#
# Zeile N ist die zweitteuerste: Erfundene Regelungen erzeugen falsche
# Sicherheit. N -> T ist etwas milder als N -> E, weil „teilweise" ohnehin zur
# Nachfrage auffordert.
#
# Zeile E ist die billigste: E heißt, der Kunde regelt vereinbar mit dem
# Hausstandard. Wird das übersehen, wendet der Bearbeiter den Standard an und
# kommt am selben Ort heraus. Der Schaden ist der falsche Verhandlungsstand,
# nicht das falsche Werkzeug.
SCHADEN: dict[tuple[str, str], float] = {
    ("E", "E"): 0.0, ("E", "T"): 0.2, ("E", "A"): 0.4, ("E", "N"): 0.5,
    ("T", "E"): 0.3, ("T", "T"): 0.0, ("T", "A"): 0.3, ("T", "N"): 0.6,
    ("A", "E"): 1.0, ("A", "T"): 0.5, ("A", "A"): 0.0, ("A", "N"): 1.0,
    ("N", "E"): 0.7, ("N", "T"): 0.6, ("N", "A"): 0.4, ("N", "N"): 0.0,
}

# Wie die vier Klassen aus der Kopfdokumentation auf Zellen abbilden — für die
# Aufschlüsselung im Bericht und für die Sensitivitätsanalyse.
KLASSEN: dict[str, tuple[tuple[str, str], ...]] = {
    "übersehene Abweichung": (("A", "E"), ("A", "N"), ("A", "T")),
    "erfundene Regelung":    (("N", "E"), ("N", "T")),
    "übersehene Regelung":   (("E", "N"), ("T", "N")),
    "Fehlalarm":             (("E", "A"), ("T", "A"), ("N", "A")),
    "Grad verwechselt":      (("E", "T"), ("T", "E")),
}


def _zellen(conf: Counter | dict) -> dict[tuple[str, str], int]:
    """Nur die Zellen mit gültigen Status. Nicht bewertete Kriterien (Agent
    None) fallen heraus — sie sind Werkzeugversagen und werden getrennt
    berichtet, nicht in die Schadensrechnung gemischt."""
    return {(s, i): n for (s, i), n in conf.items()
            if s in STATUS and i in STATUS}


def bewerte(conf: Counter | dict,
            matrix: dict[tuple[str, str], float] | None = None) -> dict:
    """Schadensrechnung über eine Konfusionsmatrix.

    `conf` ist das `_conf_raw` aus evaluation.vergleiche(): (Referenz, Agent)
    -> Anzahl.

    Rückgabe unter anderem:
      schaden_je_kriterium  0 = fehlerfrei. Die Hauptzahl.
      guete                 1 - Schaden/Höchstschaden, damit sie sich wie
                            Exact Match liest: höher ist besser.
      je_klasse             wo der Schaden entsteht
    """
    m = matrix or SCHADEN
    zellen = _zellen(conf)
    n = sum(zellen.values())
    if not n:
        return {"n": 0, "schaden": 0.0, "schaden_je_kriterium": 0.0,
                "guete": 0.0, "je_klasse": {}, "hoechstschaden": 0.0}

    schaden = sum(m[(s, i)] * k for (s, i), k in zellen.items())

    # Höchstschaden: Wenn jedes Kriterium die für seine Referenz teuerste
    # falsche Antwort bekäme. Nur so ist die Güte über Dokumente vergleichbar —
    # ein Dokument mit vielen A hat mehr zu verlieren als eines ohne.
    ref = Counter()
    for (s, _), k in zellen.items():
        ref[s] += k
    hoechst = sum(max(m[(s, i)] for i in STATUS) * k for s, k in ref.items())

    je_klasse = {}
    for name, felder in KLASSEN.items():
        anzahl = sum(zellen.get(f, 0) for f in felder)
        punkte = sum(m[f] * zellen.get(f, 0) for f in felder)
        if anzahl:
            je_klasse[name] = {"anzahl": anzahl, "punkte": round(punkte, 2),
                               "anteil": punkte / schaden if schaden else 0.0}

    return {
        "n": n,
        "schaden": schaden,
        "schaden_je_kriterium": schaden / n,
        "hoechstschaden": hoechst,
        "guete": 1 - schaden / hoechst if hoechst else 1.0,
        "je_klasse": je_klasse,
    }


def baselines(conf: Counter | dict,
              matrix: dict[tuple[str, str], float] | None = None) -> dict[str, float]:
    """Was bekäme ein Modell, das gar nicht prüft?

    Ohne diese Zahlen ist die Güte nicht lesbar. Die stumpfen Strategien liegen
    deutlich über null; ein Wert knapp darüber bedeutet „so gut wie gar nicht
    geprüft“, nicht „fast die Hälfte richtig“.

    Die Referenzverteilung wird aus `conf` gezogen, damit die Baselines zum
    jeweiligen Dokumentsatz passen.
    """
    m = matrix or SCHADEN
    ref: Counter = Counter()
    for (s, _), k in _zellen(conf).items():
        ref[s] += k
    werte = {}
    for immer in STATUS:
        werte[f"immer_{immer}"] = bewerte(
            Counter({(s, immer): k for s, k in ref.items()}), m)["guete"]
    return werte


# ── Sensitivitätsanalyse ──────────────────────────────────────────────────────
# Die eigentliche Absicherung. Geprüft wird nicht, ob die Gewichte „richtig"
# sind — das lässt sich nicht entscheiden —, sondern ob die Rangfolge von ihnen
# abhängt.

def _variante(faktor_a: float, faktor_n: float) -> dict[tuple[str, str], float]:
    """Eine Gewichtsfassung mit anderer Betonung.

    faktor_a skaliert die Zeile A (übersehene Abweichungen), faktor_n die
    Zeile N (erfundene Regelungen). Alles über 1,0 wird auf 1,0 gedeckelt —
    schlimmer als der schlimmste Fall gibt es nicht.
    """
    m = dict(SCHADEN)
    for i in STATUS:
        if i != "A":
            m[("A", i)] = min(1.0, SCHADEN[("A", i)] * faktor_a)
        if i != "N":
            m[("N", i)] = min(1.0, SCHADEN[("N", i)] * faktor_n)
    return m


def sensitivitaet(laeufe: dict[str, Counter | dict],
                  spanne: tuple[float, ...] = (0.5, 0.75, 1.0, 1.5, 2.0),
                  ) -> dict:
    """Hält die Rangfolge, wenn die Gewichte verschoben werden?

    `laeufe` ist {Name: Konfusionsmatrix}. Durchgespielt wird das Kreuzprodukt
    aus Betonung der A-Zeile und der N-Zeile. Zurück kommt die Rangfolge je
    Fassung und die Feststellung, ob sie überall dieselbe ist.
    """
    rangfolgen: dict[tuple[float, float], list[str]] = {}
    for fa in spanne:
        for fn in spanne:
            m = _variante(fa, fn)
            werte = {name: bewerte(c, m)["guete"] for name, c in laeufe.items()}
            rangfolgen[(fa, fn)] = [n for n, _ in
                                    sorted(werte.items(), key=lambda x: -x[1])]

    eindeutig = {tuple(r) for r in rangfolgen.values()}
    # Wie oft steht welches Modell auf Platz 1?
    sieger = Counter(r[0] for r in rangfolgen.values())
    return {
        "fassungen": len(rangfolgen),
        "verschiedene_rangfolgen": len(eindeutig),
        "stabil": len(eindeutig) == 1,
        "sieger": dict(sieger),
        "rangfolgen": {f"A×{a} N×{n}": r for (a, n), r in rangfolgen.items()},
    }


def format_bericht(s: dict, name: str = "") -> str:
    """Kurzfassung für die Konsole."""
    if not s["n"]:
        return "keine bewertbaren Kriterien"
    z = [f"{name + ': ' if name else ''}"
         f"Güte {s['guete'] * 100:.1f} % · Schaden {s['schaden']:.1f} Punkte "
         f"({s['schaden_je_kriterium']:.3f} je Kriterium, {s['n']} Kriterien)"]
    for k, v in sorted(s["je_klasse"].items(), key=lambda x: -x[1]["punkte"]):
        z.append(f"   {k:<24}{v['anzahl']:>4} Fälle · {v['punkte']:>6.1f} Punkte "
                 f"· {v['anteil'] * 100:>4.0f} % des Schadens")
    return "\n".join(z)
