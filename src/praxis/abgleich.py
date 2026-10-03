"""Praxisabgleich — das geprüfte Lastenheft gegen das historische Archiv.

Die Kriterienprüfung beantwortet: Weicht der Kunde vom Musterlastenheft ab?
Der Praxisabgleich beantwortet eine andere Frage: Ist das, was der Kunde
fordert, im Vergleich zu bisherigen Kunden üblich oder ungewöhnlich?

Beide Antworten stehen NEBENEINANDER. Der Praxisabgleich ändert keine
Einstufung. Das ist Absicht: Häufigkeit ist kein Maßstab. Dass fast alle
Kunden etwas fordern, macht die Forderung nicht richtig — es macht sie
erwartbar. Umgekehrt ist eine seltene Forderung kein Mangel, sondern ein
Punkt, an dem sich genaues Lesen lohnt.

Zwei Quellen:
- Häufigkeit  aus den Standard-Chunks (`geregelt_in_dokumenten`) — ohne
  Zusatzdatei, ohne LLM, deterministisch.
- Textstellen aus dem Praxisarchiv (Retrieval über die historischen
  Dokumente) — damit die Häufigkeitsaussage belegt ist und nicht geglaubt
  werden muss.

Was der Praxisabgleich NICHT leistet: Seltenheit sagt keine Abweichung voraus.
Selten geregelte Punkte weichen nicht häufiger ab als häufig geregelte. Der
Grund ist einsichtig: Eine Abweichung widerspricht dem Musterlastenheft, und das
ist aus dem Korpus gebaut — was fast alle regeln, steht dort ausführlich mit
Werten und Fabrikaten und bietet Angriffsfläche; was wenige regeln, hat einen
dünnen Eintrag, dem kaum zu widersprechen ist. Die Häufigkeit wird deshalb als
das ausgewiesen, was sie ist: eine Einordnung, keine Risikobewertung.
"""

from dataclasses import dataclass, field

import numpy as np

from src.pruefung.kriterien import _kriterium_query, load_kriterien, load_standard
from src.praxis.archiv import MIN_SCORE, Praxisarchiv, Praxisstelle
from src.dokumente.vector_store import einbetten

# Ab hier gilt ein Punkt als etabliert bzw. als Einzelfall. Als Anteil des
# Korpus formuliert, damit die Schwellen ein anderes Archiv überstehen.
#
# Nicht an Trefferquoten kalibriert — es gibt nichts vorherzusagen (siehe
# Modulkopf). Gewählt nach der Länge der entstehenden Liste: Die Schwelle
# liefert eine Liste, die man tatsächlich durchgeht.
ANTEIL_ETABLIERT   = 0.80
ANTEIL_EINZELFALL  = 0.25

EINORDNUNGEN = ("selten", "luecke", "ueblich", "unauffaellig")

LABEL = {
    "selten":       "selten im Korpus",
    "luecke":       "Lücke gegenüber der Praxis",
    "ueblich":      "üblich",
    "unauffaellig": "unauffällig",
}


@dataclass
class Praxisbefund:
    """Einordnung eines Kriteriums gegenüber dem historischen Archiv."""
    nr:            str
    titel:         str
    einstufung:    str
    status:        str                    # Status im geprüften Lastenheft, "" ohne Prüfung
    n_geregelt:    int                    # wie viele historische Dokumente regeln den Punkt
    korpus:        int                    # Größe des Vergleichskorpus
    dokumente:     list[str] = field(default_factory=list)
    verteilung:    dict[str, int] = field(default_factory=dict)  # nur mit Ground Truth
    stellen:       list[Praxisstelle] = field(default_factory=list)
    einordnung:    str = "unauffaellig"
    hinweis:       str = ""

    @property
    def anteil(self) -> float:
        return self.n_geregelt / self.korpus if self.korpus else 0.0

    @property
    def auffaellig(self) -> bool:
        """Kriterien, bei denen sich der Blick ins Archiv lohnt.

        Nicht „riskant" — nur die Punkte, für die ein Beleg aus den
        historischen Lastenheften einen Erkenntnisgewinn bringt.
        """
        return self.einordnung in ("selten", "luecke")


def korpus_ids(standard: dict[str, dict] | None = None) -> set[str]:
    """Kennungen der Dokumente, aus denen der Standard zusammengetragen wurde.

    Aus den Chunks abgeleitet statt fest verdrahtet: Wird das
    Musterlastenheft auf einer anderen Grundlage neu gebaut, stimmt die Liste
    weiterhin. Dient zugleich als Filter beim Anlegen des Archivs — das
    Musterlastenheft selbst gehört nicht hinein.
    """
    standard = standard if standard is not None else load_standard()
    alle: set[str] = set()
    for chunk in standard.values():
        alle.update(chunk.get("geregelt_in_dokumenten") or [])
        alle.update(chunk.get("belegt_laut_haeufigkeitsmatrix") or [])
    return alle


def korpusgroesse(standard: dict[str, dict]) -> int:
    """Zahl der Dokumente, aus denen der Standard zusammengetragen wurde."""
    return len(korpus_ids(standard))


def _einordnen(status: str, n_geregelt: int, korpus: int,
               anteil_etabliert: float, anteil_einzelfall: float) -> tuple[str, str]:
    """Vergleicht den Status des geprüften Dokuments mit der Häufigkeit im Archiv."""
    if not korpus:
        return "unauffaellig", ""
    anteil = n_geregelt / korpus

    if status == "N":
        if anteil >= anteil_etabliert:
            return "luecke", (
                f"{n_geregelt} von {korpus} bisherigen Lastenheften regeln diesen "
                f"Punkt, dieses nicht. Kein Mangel des Kunden — aber ein Punkt, der "
                f"erfahrungsgemäß geklärt wird, bevor er im Projekt auftaucht."
            )
        return "unauffaellig", ""

    if anteil <= anteil_einzelfall:
        return "selten", (
            f"Nur {n_geregelt} von {korpus} bisherigen Lastenheften regeln diesen "
            f"Punkt — für diesen Kunden gibt es also wenig Erfahrungswerte. Das ist "
            f"kein Hinweis auf eine Abweichung: Seltene Punkte weichen in der "
            f"Referenz seltener ab als häufige."
        )
    if anteil >= anteil_etabliert:
        return "ueblich", (
            f"{n_geregelt} von {korpus} bisherigen Lastenheften regeln diesen Punkt "
            f"ebenfalls."
        )
    return "unauffaellig", ""


def praxisabgleich(
    ergebnis: dict | None = None,
    archiv: Praxisarchiv | None = None,
    kriterien: list[dict] | None = None,
    standard: dict[str, dict] | None = None,
    ground_truth: dict | None = None,
    n_stellen: int = 4,
    min_score: float = MIN_SCORE,
    nur_auffaellige_belegen: bool = False,
    ohne_dokument: str | None = None,
    anteil_etabliert: float = ANTEIL_ETABLIERT,
    anteil_einzelfall: float = ANTEIL_EINZELFALL,
    progress_callback=None,
) -> list[Praxisbefund]:
    """Ordnet jedes Kriterium gegenüber dem historischen Archiv ein.

    `ergebnis` ist optional. Ohne Prüflauf gibt es keinen Status, und ohne
    Status keine Einordnung — dann bleiben Häufigkeit und Belegstellen. Der
    Abgleich ist eine eigene Funktion und darf keinen Prüflauf voraussetzen;
    fehlende Bewertungen als `N` zu behandeln, hieße jedes Kriterium
    fälschlich als Lücke zu melden.

    Die Gegenüberstellung mit dem Wortlaut eines EINZELNEN früheren
    Lastenhefts leistet `src/praxis/dokumentvergleich.py` — hier geht es um den
    Korpus als Ganzes.

    `archiv` ist optional: Ohne Archiv entfallen die Textstellen, die
    Häufigkeitsaussage bleibt. Der Abgleich soll auch dann etwas liefern, wenn
    das Archiv noch nicht angelegt ist.

    `nur_auffaellige_belegen` beschränkt das Retrieval auf die auffälligen
    Kriterien. Standardmäßig aus: Die Suche braucht kein LLM und läuft für
    alle 67 Kriterien in wenigen Sekunden, und im Detailblatt ist der Blick
    „wie haben andere Kunden das formuliert?" gerade bei den unauffälligen
    Punkten nützlich.

    `ohne_dokument` blendet ein Dokument aus der Häufigkeitszählung aus. Nötig,
    wenn ein Dokument des Korpus selbst geprüft wird — sonst zählt es sich
    selbst mit und der Vergleich wäre geschönt.
    """
    kriterien = kriterien if kriterien is not None else load_kriterien()
    standard  = standard  if standard  is not None else load_standard()
    bewertungen = (ergebnis or {}).get("bewertungen", {})
    mit_status  = bool(bewertungen)

    ids = korpus_ids(standard)
    if ohne_dokument:
        ids.discard(ohne_dokument)
    korpus = len(ids)

    befunde: list[Praxisbefund] = []
    for k in kriterien:
        nr    = k["nr"]
        chunk = standard.get(nr) or {}
        docs  = [d for d in (chunk.get("geregelt_in_dokumenten") or [])
                 if d != ohne_dokument]
        status = (bewertungen.get(nr) or {}).get("status", "N") if mit_status else ""

        verteilung: dict[str, int] = {}
        if ground_truth:
            for lh in docs:
                s = ((ground_truth["dokumente"].get(lh) or {})
                     .get("bewertungen", {}).get(nr) or {}).get("status")
                if s:
                    verteilung[s] = verteilung.get(s, 0) + 1

        # Ohne Prüflauf keine Einordnung: „Lücke" und „selten" setzen einen
        # Status voraus. Häufigkeit und Belegstellen stehen trotzdem.
        if mit_status:
            art, hinweis = _einordnen(status, len(docs), korpus,
                                      anteil_etabliert, anteil_einzelfall)
        else:
            art, hinweis = "unauffaellig", ""

        befunde.append(Praxisbefund(
            nr=nr, titel=k["titel"], einstufung=k["einstufung"], status=status,
            n_geregelt=len(docs), korpus=korpus, dokumente=docs,
            verteilung=verteilung, einordnung=art, hinweis=hinweis,
        ))

    if archiv is None or len(archiv) == 0:
        return befunde

    zu_belegen = [b for b in befunde
                  if not nur_auffaellige_belegen or b.auffaellig]
    if not zu_belegen:
        return befunde

    von_nr  = {k["nr"]: k for k in kriterien}
    queries = [_kriterium_query(von_nr[b.nr], standard.get(b.nr)) for b in zu_belegen]
    vecs    = einbetten(queries)

    for i, (b, vec) in enumerate(zip(zu_belegen, vecs), start=1):
        if progress_callback:
            progress_callback(i, len(zu_belegen), f"{b.nr} {b.titel}")
        begriffe = (standard.get(b.nr) or von_nr[b.nr]).get("abgleichbegriffe") or []
        stellen = archiv.suche(vec, begriffe=begriffe, n=n_stellen,
                               min_score=min_score, max_je_dokument=1)
        if ohne_dokument:
            stellen = [s for s in stellen if s.lh_id != ohne_dokument]
        b.stellen = stellen

    return befunde


def zusammenfassung(befunde: list[Praxisbefund]) -> dict:
    """Zählwerte für die Kopfzeile des Berichts."""
    z = {a: 0 for a in EINORDNUNGEN}
    for b in befunde:
        z[b.einordnung] += 1
    return {
        **z,
        "auffaellig": sum(1 for b in befunde if b.auffaellig),
        "belegt":     sum(1 for b in befunde if b.stellen),
        "mit_status": any(b.status for b in befunde),
        "korpus":     befunde[0].korpus if befunde else 0,
    }
