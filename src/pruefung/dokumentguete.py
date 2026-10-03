"""Wie gut passt dieses Dokument überhaupt zur Gliederung?

Die Fundstellensuche ist nicht in jedem Dokument gleich zuverlässig: Wie oft die
von der Referenz zitierte Seite unter den Kandidatenstellen liegt, schwankt
zwischen den Lastenheften erheblich. Ein Bericht über ein schwer erschließbares
Dokument ist etwas anderes wert als einer über ein gut erschließbares, und
bisher sah man ihm das nicht an.

## Der Anzeiger

Vorhersagen lässt sich das aus der mittleren Kosinus-Ähnlichkeit zwischen den
Abschnitten des Dokuments und den Kriterienabfragen. Das ist ein brauchbarer,
aber kein scharfer Anzeiger. Deshalb wird der Wert **eingeordnet statt als
Alarm gesetzt**: Auch ohne Warnung sieht der Leser, wo sein Dokument im Korpus
steht. Eine Ampel, die nur rot oder grün kennt, würde unnötig beunruhigen oder
eine Sicherheit vortäuschen, die der Anzeiger nicht hergibt.

## Warum das überhaupt gebaut wurde

Ein Werkzeug, das immer gleich selbstbewusst auftritt, ist gefährlicher als
eines, das sagt, wann es unsicher ist. Der Anzeiger braucht keine Ground Truth
und keinen zusätzlichen Modellaufruf: Die Ähnlichkeiten fallen bei der Suche
ohnehin an.

Er misst die Passung zwischen Dokument und Einbettungsmodell, nicht eine
Eigenschaft des Dokuments allein. Die Schwellen gelten für
`paraphrase-multilingual-MiniLM-L12-v2` und müssten bei einem Wechsel neu
erhoben werden.
"""

from __future__ import annotations

from dataclasses import dataclass

# Verteilung der mittleren Ähnlichkeit über die Korpusdokumente.
KORPUS_MIN, KORPUS_MEDIAN, KORPUS_MAX = 0.252, 0.331, 0.384

# Unteres Viertel des Korpus. Kein Grenzwert für „unbrauchbar", sondern die
# Linie, ab der die Suche in den Messungen spürbar nachließ.
SCHWELLE_SCHWACH = 0.30
SCHWELLE_MITTEL = 0.32


@dataclass
class Guete:
    wert: float
    stufe: str            # "gut" | "mittel" | "schwach"
    text: str
    abschnitte: int

    @property
    def warnen(self) -> bool:
        return self.stufe == "schwach"


def beurteile(mittlere_aehnlichkeit: float, abschnitte: int) -> Guete:
    """Ordnet die mittlere Ähnlichkeit in den Korpus ein."""
    w = float(mittlere_aehnlichkeit)
    lage = (f"Sprachliche Nähe zur Gliederung: **{w:.2f}** "
            f"(Korpus: {KORPUS_MIN:.2f} bis {KORPUS_MAX:.2f}, "
            f"Median {KORPUS_MEDIAN:.2f}).")

    if w < SCHWELLE_SCHWACH:
        return Guete(w, "schwach", lage + (
            " Das Dokument liegt sprachlich weit von der Gliederung entfernt — "
            "in diesem Bereich hat die Suche im Korpus zwischen einem Drittel "
            "und zwei Dritteln der Belegstellen nicht gefunden. **Die "
            "Einstufungen sind hier deutlich unzuverlässiger als sonst; bitte "
            "gründlicher gegenlesen.** Typisch für sehr lange Normensammlungen "
            "und fremdsprachige Werksnormen."), abschnitte)

    if w < SCHWELLE_MITTEL:
        return Guete(w, "mittel", lage + (
            " Etwas unter dem Korpusdurchschnitt. Die Suche arbeitet hier "
            "erfahrungsgemäß noch zuverlässig, aber nicht so gut wie bei einem "
            "typischen Lastenheft."), abschnitte)

    return Guete(w, "gut", lage + (
        " Im üblichen Bereich des Korpus — die Fundstellensuche arbeitet hier "
        "zuverlässig."), abschnitte)


def aus_statistik(statistik: dict, abschnitte: int) -> Guete | None:
    """Beurteilt ein Dokument aus der Mitschrift der Fundstellensuche.

    Gebraucht wird der Mittelwert über ALLE Abschnitte, nicht über die
    gefundenen Kandidaten. Die Kandidaten sind je Kriterium die ähnlichsten, und
    ihr Mittelwert sieht in jedem Dokument gleich aus — auch dort, wo die Suche
    sehr unterschiedlich gut trifft. Über alle Abschnitte trennen die Dokumente
    dagegen deutlich. Ein Umrechnungsfaktor hilft nicht; es muss der echte
    Mittelwert sein.
    """
    w = statistik.get("mittlere_aehnlichkeit")
    return beurteile(w, abschnitte) if w is not None else None
