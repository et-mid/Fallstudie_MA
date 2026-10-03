"""Neues Lastenheft gegen ein einzelnes historisches — Dokument zu Dokument.

Ohne jeden Bezug zum Musterlastenheft und ohne die Kriterien. Verglichen
werden die Dokumente selbst, Abschnitt für Abschnitt.

Drei Schritte:

1. **Vorauswahl per Retrieval.** Für jeden Abschnitt des neuen Lastenhefts wird
   in jedem historischen Dokument der beste Treffer gesucht; der Dokumentwert
   ist der Mittelwert dieser Bestwerte, in beiden Richtungen gemittelt.
2. **Abschnittspaare.** Zum gewählten Dokument wird je Abschnitt des neuen
   Lastenhefts die passendste Gegenstelle bestimmt.
3. **Urteil je Paar.** Das Sprachmodell bekommt beide Textstellen und sagt, wie
   weit sie übereinstimmen und worin sie sich unterscheiden.

## Was der Ähnlichkeitswert bedeutet

Zwei Zahlen, die getrennt bleiben müssen:

- **Übereinstimmung** — wie ähnlich die vergleichbaren Stellen inhaltlich sind.
  Urteil des Sprachmodells, Mittel über die verglichenen Paare. Das ist der
  Ähnlichkeitswert.
- **Vergleichbare Stellen** — wie viele Abschnitte überhaupt eine Entsprechung
  im anderen Dokument haben. Reine Suche, ohne Modell.

Aus beidem eine einzige Zahl zu machen wäre eine Scheingenauigkeit. Zwei
Lastenhefte verschiedener Kunden sind unabhängig voneinander geschrieben; nur
ein kleiner Teil ihrer Abschnitte hat überhaupt ein Gegenstück. Eine
hohe Übereinstimmung über wenige Stellen sagt etwas über diese Stellen —
nicht über die Dokumente als Ganzes. Wer nur die eine Zahl liest,
soll wenigstens daneben sehen, worauf sie beruht.

## Grenzen der Vorauswahl

Die Rangfolge trifft das ähnlichste Dokument nicht zuverlässig. Ein Teil davon
liegt am Maßstab, an dem sie gemessen wird: Er zählt „beide regeln es nicht“
als Übereinstimmung, und das sieht kein Textvergleich.

Die Rangfolge ist deshalb ein **Vorschlag, kein Befund**. Die Auswahl von Hand
ist nicht Beiwerk, sondern der vorgesehene Weg.
"""

import json
import re
from dataclasses import dataclass, field

import numpy as np

from src.muster.anwendungsfeld import uebertragen
from src.pruefung.kriterien import _chat, _first_json, STANDARD_MODELL
from src.praxis.archiv import Praxisarchiv
from src.dokumente.vector_store import einbetten, normalize_rows

# ── Schrotterkennung ─────────────────────────────────────────────────────────
# Ohne diesen Filter wählt die Paarbildung zuverlässig das Uninteressanteste
# aus: Deckblätter, Schriftfelder und Verzeichniszeilen sind formelhaft und
# passen deshalb hervorragend zueinander und verdrängen die aussagekräftigen
# Paare.
#
# Eine Hub-Korrektur (Abzug der mittleren Ähnlichkeit eines Abschnitts zu allem)
# wurde erprobt und verworfen: Sie drängte auch die echten Anforderungen
# zurück.
_PUNKTREIHE   = re.compile(r"\.{4,}|…{2,}|[.…]\s?[.…]\s?[.…]")
_WIEDERHOLUNG = re.compile(r"([a-zäöü])\1{4,}", re.I)


def ist_schrott(text: str) -> bool:
    """Punktreihe, Buchstabensalat oder überwiegend Kürzel und Zahlen."""
    if _PUNKTREIHE.search(text) or _WIEDERHOLUNG.search(text):
        return True
    tokens = text.split()
    if len(tokens) < 5:
        return True
    kurz = sum(1 for w in tokens if len(w) <= 2) / len(tokens)
    ziffern = sum(c.isdigit() for c in text) / max(len(text), 1)
    return kurz > 0.35 or ziffern > 0.18

# Unter diesem Wert gilt ein Abschnitt als ohne Entsprechung.
#
# Die Schwelle muss hoch liegen. Kosinuswerte liegen in diesem Korpus eng und
# hoch beisammen — jeder technische deutsche Satz ähnelt jedem anderen. Bei
# niedrigen Schwellen sind die Paare thematisch nicht besser als zufällig
# gezogen; die gewählte Schwelle trifft überwiegend dasselbe Thema und lässt
# noch genug Paare übrig.
MIN_PAAR_SCORE = 0.75

# Obergrenze für die Zahl der LLM-Aufrufe. Bei der gewählten Schwelle werden
# es selten mehr als 15; die Grenze schützt vor Ausreißern.
N_PAARE = 40

BEWERTUNGEN = ("identisch", "aehnlich", "abweichend", "kein_bezug")

PAAR_PROMPT = """Du vergleichst zwei Textstellen aus zwei Lastenheften für Druckgießwerkzeuge.

STELLE AUS DEM NEUEN LASTENHEFT (Seite {seite_neu}):
{text_neu}

STELLE AUS DEM FRÜHEREN LASTENHEFT {lh_id} (Seite {seite_alt}):
{text_alt}

Beurteile ausschließlich diese beiden Stellen. Kein Vorwissen, keine Annahmen
über den Rest der Dokumente.

Vergib einen Wert von 0 bis 100:
100  gleiche Anforderung, gleicher Inhalt — nur andere Formulierung
 75  gleiche Anforderung, abweichend in Details (Werte, Fristen, Zuständigkeit)
 50  gleiches Thema, aber eine Seite regelt deutlich mehr oder anderes
 25  verwandtes Thema, kaum inhaltliche Überschneidung
  0  die Stellen haben inhaltlich nichts miteinander zu tun

Antworte NUR mit diesem JSON, ohne Vor- oder Nachwort:
{{"wert": <0-100>, "unterschied": "<ein Satz: worin sie sich unterscheiden, oder 'keiner'>"}}"""


@dataclass
class Dokumentwert:
    """Ergebnis der Vorauswahl für ein historisches Lastenheft."""
    lh_id:        str
    wert:         float        # Rangwert (beidseitig, Gegenrichtung normiert), danach sortiert
    vergleichbar: int          # Abschnitte des neuen Lastenhefts mit Entsprechung
    abschnitte:   int          # Umfang des historischen Dokuments
    roh:          float = 0.0  # beidseitiger Mittelwert der Bestwerte ohne Normierung


@dataclass
class Abschnittspaar:
    """Ein Abschnitt des neuen Lastenhefts und seine Gegenstelle."""
    seite_neu:  int
    text_neu:   str
    seite_alt:  int
    text_alt:   str
    score:      float                 # Ähnlichkeit aus der Suche
    wert:       int | None = None     # Urteil des Modells, 0-100
    unterschied: str = ""
    fehler:     str = ""

    @property
    def bewertung(self) -> str:
        if self.wert is None:
            return "kein_bezug"
        if self.wert >= 90:
            return "identisch"
        if self.wert >= 60:
            return "aehnlich"
        if self.wert >= 25:
            return "abweichend"
        return "kein_bezug"


@dataclass
class Vergleichsergebnis:
    lh_id:            str
    uebereinstimmung: float | None  # der Ähnlichkeitswert, 0..1; None ohne bewertetes Paar
    vergleichbar:     int        # Abschnitte mit Entsprechung
    abschnitte_neu:   int
    paare:            list[Abschnittspaar] = field(default_factory=list)
    nicht_bewertet:   int = 0


def _neue_embeddings(neue_chunks: list) -> np.ndarray:
    return normalize_rows(einbetten([c.text for c in neue_chunks]))


def _bestwerte_im_archiv(archiv: Praxisarchiv) -> tuple[np.ndarray, list[str]]:
    """Je Archivabschnitt der beste Treffer in jedem Archivdokument.

    Rückgabe: Matrix (Archivabschnitte × Dokumente) und die Dokumentreihenfolge.
    Als Anfrage zählen, wie im Betrieb, nur die Abschnitte ohne Schrott. Einmal je
    Archiv gerechnet und am Objekt abgelegt; der Schlüssel ist die Einbettungsmatrix,
    damit eine Teilsicht des Archivs nicht die Werte des ganzen erbt.
    """
    ablage = getattr(archiv, "_dv_bestwerte", None)
    if ablage is not None and ablage[0] is archiv._norm:
        return ablage[1], ablage[2]
    dokumente = sorted({m["lh_id"] for m in archiv.meta})
    best = np.empty((len(archiv.meta), len(dokumente)), dtype=np.float32)
    for k, lh in enumerate(dokumente):
        gut = [i for i, m in enumerate(archiv.meta)
               if m["lh_id"] == lh and not ist_schrott(m["text"])]
        best[:, k] = (archiv._norm @ archiv._norm[gut].T).max(axis=1) if gut else np.nan
    archiv._dv_bestwerte = (archiv._norm, best, dokumente)
    return best, dokumente


def rangliste(
    neue_chunks: list,
    archiv: Praxisarchiv,
    min_paar_score: float = MIN_PAAR_SCORE,
    neu_norm: np.ndarray | None = None,
    ohne: str | None = None,
) -> list[Dokumentwert]:
    """Historische Lastenhefte, sortiert nach Ähnlichkeit zum neuen.

    Beidseitig gemittelt: Ein kurzes Dokument, dessen Inhalte alle im neuen
    vorkommen, wäre einseitig gemessen unauffällig; erst die Gegenrichtung
    zeigt, dass es das neue Dokument kaum abdeckt.

    In der Gegenrichtung zählt jeder Abschnitt des alten Dokuments nicht mit seinem
    Bestwert, sondern mit dessen Abstand zu seinem üblichen Bestwert in den übrigen
    Archivdokumenten. Sonst bestimmen zwei Eigenschaften die Reihenfolge, die mit
    Ähnlichkeit nichts zu tun haben: englische Abschnitte finden in deutschen
    Dokumenten durchweg schlechtere Gegenstücke (ein zweisprachiges Dokument rutscht
    nach unten), und formelhafte Abschnitte passen überall (ein breites Dokument
    steht fast immer oben). Die Hinrichtung bleibt roh — ein
    Abzug je Abschnitt des neuen Dokuments wäre für alle Kandidaten gleich.

    `ohne` nimmt ein Archivdokument aus Rangliste und Normierung heraus — das
    geprüfte Lastenheft selbst, falls es im Archiv liegt.
    """
    if not neue_chunks or len(archiv) == 0:
        return []

    neu = _neue_embeddings(neue_chunks) if neu_norm is None else neu_norm
    sim = neu @ archiv._norm.T            # (neue Abschnitte × Archivabschnitte)
    best, dok_reihe = _bestwerte_im_archiv(archiv)

    nach_dok: dict[str, list[int]] = {}
    for i, m in enumerate(archiv.meta):
        if m["lh_id"] != ohne:
            nach_dok.setdefault(m["lh_id"], []).append(i)

    werte: list[Dokumentwert] = []
    for lh, ii in nach_dok.items():
        teil = sim[:, ii]
        hin  = teil.max(axis=1)           # je neuem Abschnitt der beste Treffer
        her  = teil.max(axis=0)           # je Abschnitt des alten Dokuments
        andere = [k for k, d in enumerate(dok_reihe) if d not in (lh, ohne)]
        ueblich = (np.nanmean(best[np.ix_(ii, andere)], axis=1) if andere
                   else np.zeros(len(ii)))
        werte.append(Dokumentwert(
            lh_id=lh,
            wert=float((hin.mean() + (her - ueblich).mean()) / 2),
            vergleichbar=int((hin >= min_paar_score).sum()),
            abschnitte=len(ii),
            roh=float((hin.mean() + her.mean()) / 2),
        ))
    return sorted(werte, key=lambda d: d.wert, reverse=True)


def abschnittspaare(
    neue_chunks: list,
    archiv: Praxisarchiv,
    lh_id: str,
    n_paare: int = N_PAARE,
    min_paar_score: float = MIN_PAAR_SCORE,
    neu_norm: np.ndarray | None = None,
) -> tuple[list[Abschnittspaar], int]:
    """Bildet Abschnittspaare zum gewählten Dokument.

    Rückgabe: (Paare, Zahl der vergleichbaren Abschnitte). Die zweite Zahl
    zählt über ALLE Abschnitte des neuen Lastenhefts, nicht nur über die
    verglichenen — sonst verschwiege die Kennzahl genau die Stellen, für die es
    kein Gegenstück gibt.
    """
    ii = [i for i, m in enumerate(archiv.meta) if m["lh_id"] == lh_id]
    if not ii or not neue_chunks:
        return [], 0

    neu = _neue_embeddings(neue_chunks) if neu_norm is None else neu_norm
    sim = neu @ archiv._norm[ii].T

    # Vor dem Schrottfilter gezählt: Die Zahl beantwortet, wie viel des neuen
    # Lastenhefts im historischen wiederzufinden ist, und darf nicht davon
    # abhängen, welche Stellen wir zum Vergleich auswählen.
    vergleichbar = int((sim.max(axis=1) >= min_paar_score).sum())

    schrott_alt = np.array([ist_schrott(archiv.meta[i]["text"]) for i in ii])
    brauchbar = sim.copy()
    brauchbar[:, schrott_alt] = -1.0

    beste = brauchbar.argmax(axis=1)
    werte = brauchbar.max(axis=1)
    for j, c in enumerate(neue_chunks):
        if ist_schrott(c.text):
            werte[j] = -1.0

    paare: list[Abschnittspaar] = []
    for j in np.argsort(werte)[::-1]:
        if len(paare) >= n_paare or werte[j] < min_paar_score:
            break
        m = archiv.meta[ii[int(beste[j])]]
        paare.append(Abschnittspaar(
            seite_neu=neue_chunks[j].page, text_neu=neue_chunks[j].text,
            seite_alt=m["seite"], text_alt=m["text"], score=float(werte[j])))
    return paare, vergleichbar


def _lies_urteil(text: str) -> tuple[int | None, str, str]:
    """Wert und Unterschied aus der Modellantwort. Gibt den Grund bei Fehlschlag."""
    blob = _first_json(text or "")
    if not blob:
        return None, "", "keine JSON-Antwort"
    try:
        d = json.loads(blob)
    except json.JSONDecodeError as e:
        return None, "", f"JSON unlesbar: {e}"
    if not isinstance(d, dict):
        return None, "", "kein JSON-Objekt"
    try:
        wert = int(round(float(d.get("wert"))))
    except (TypeError, ValueError):
        return None, "", "kein Zahlenwert"
    return max(0, min(100, wert)), str(d.get("unterschied", ""))[:400], ""


def vergleiche_abschnitte(
    paare: list[Abschnittspaar],
    lh_id: str,
    model: str = STANDARD_MODELL,
    num_predict: int = 200,
    progress_callback=None,
) -> list[Abschnittspaar]:
    """Lässt das Sprachmodell jedes Paar beurteilen. Ändert die Paare in place."""
    for i, p in enumerate(paare, start=1):
        if progress_callback:
            progress_callback(i, len(paare), f"Seite {p.seite_neu}")
        prompt = uebertragen(PAAR_PROMPT, format_sicher=True).format(
            seite_neu=p.seite_neu, text_neu=p.text_neu[:1500],
            lh_id=lh_id, seite_alt=p.seite_alt, text_alt=p.text_alt[:1500])
        antwort = _chat(model, prompt, num_predict=num_predict)
        if not antwort.ok:
            p.fehler = antwort.grund
            continue
        p.wert, p.unterschied, p.fehler = _lies_urteil(antwort.text)
    return paare


def auswerten(paare: list[Abschnittspaar], vergleichbar: int, lh_id: str,
              abschnitte_neu: int) -> Vergleichsergebnis:
    """Fasst die Einzelurteile zusammen.

    Gescheiterte Aufrufe gehen NICHT als Null in den Mittelwert ein — ein
    abgestürzter Aufruf ist keine Aussage über Unähnlichkeit. Ihre Zahl steht
    getrennt in `nicht_bewertet`.
    """
    bewertet = [p for p in paare if p.wert is not None]
    return Vergleichsergebnis(
        lh_id=lh_id,
        uebereinstimmung=(sum(p.wert for p in bewertet) / len(bewertet) / 100
                          if bewertet else None),
        vergleichbar=vergleichbar,
        abschnitte_neu=abschnitte_neu,
        paare=paare,
        nicht_bewertet=len(paare) - len(bewertet),
    )


def zusammenfassung(ergebnis: Vergleichsergebnis) -> dict:
    z = {b: 0 for b in BEWERTUNGEN}
    for p in ergebnis.paare:
        if p.wert is not None:
            z[p.bewertung] += 1
    return z
