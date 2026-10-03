"""Querverweis-Suche über den Standard.

Der Vergleichsmaßstab je Kriterium kommt aus dem Chunk gleicher Nummer — das ist
garantiert und bleibt so. Eine einschlägige Anforderung kann aber in einem
ANDEREN Abschnitt stehen: „Kühlkreise sind im Formrahmen zu führen" gehört
formal zu 4.2 Formaufbau, ist für 4.10 Temperierung trotzdem relevant.

Dieses Modul durchsucht die Einzelaussagen aller Abschnitte und liefert die
passendsten aus FREMDEN Kriterien. Die eigenen sind über den Direktzugriff schon
im Prompt; sie erneut zu liefern wäre nur Verdopplung.

Bewusst ergänzend, nicht ersetzend: Fällt die Suche aus oder findet nichts,
bleibt die Bewertung genau so möglich wie ohne sie.
"""

from dataclasses import dataclass

import numpy as np

from src.dokumente.vector_store import einbetten, normalize_rows


@dataclass
class Einheit:
    """Eine einzelne Aussage des Standards, mit ihrer Herkunft."""
    nr:    str    # Nummer des Kriteriums, aus dem die Aussage stammt
    titel: str    # dessen Titel, für die Herkunftsangabe im Prompt
    art:   str    # "Anforderung" oder "Ausprägung"
    text:  str
    score: float = 0.0


def einheiten_aus_standard(standard: dict[str, dict]) -> list[Einheit]:
    """Zerlegt den Standard in einzeln durchsuchbare Aussagen.

    Feingranular statt abschnittsweise: Gesucht wird die eine einschlägige
    Anforderung, nicht ein ganzes Kapitel. Platzhalter und Abgleichbegriffe
    bleiben außen vor — das sind Schlagwortlisten ohne Aussagegehalt.
    """
    einheiten: list[Einheit] = []
    for nr, chunk in standard.items():
        titel = chunk.get("abschnitt_titel", "")
        for text in chunk.get("standardanforderungen", []):
            if text.strip():
                einheiten.append(Einheit(nr, titel, "Anforderung", text.strip()))
        for text in chunk.get("auspraegungen_im_korpus", []):
            if text.strip():
                einheiten.append(Einheit(nr, titel, "Ausprägung", text.strip()))
    return einheiten


class Querverweisindex:
    """Embedding-Index über die Einzelaussagen des Standards.

    Wird einmal je Prüflauf gebaut (rund 450 kurze Texte, wenige Sekunden) und
    dann für alle 67 Kriterien wiederverwendet.
    """

    def __init__(self, standard: dict[str, dict]):
        self.einheiten = einheiten_aus_standard(standard)
        if not self.einheiten:
            self._norm = np.empty((0, 0), dtype=np.float32)
            return
        # Über den Zwischenspeicher: Der Standard ändert sich zwischen zwei
        # Prüfläufen nicht, seine 450 Aussagen mussten trotzdem jedes Mal neu
        # eingebettet werden — 3,5 s je Dokument.
        self._norm = normalize_rows(einbetten([e.text for e in self.einheiten]))

    def __len__(self) -> int:
        return len(self.einheiten)

    def suche(self, query_vec: np.ndarray, eigene_nr: str,
              begriffe: list[str] | None = None,
              n: int = 3, min_score: float = 0.45) -> list[Einheit]:
        """Passendste Aussagen aus fremden Kriterien, absteigend sortiert.

        `begriffe` sind die Abgleichbegriffe des bewerteten Kriteriums und
        wirken als harte Bedingung: Eine fremde Aussage gilt nur als einschlägig,
        wenn sie mindestens einen davon wörtlich enthält.

        Grund: Die Kosinus-Ähnlichkeit allein trennt hier nicht — auch fachfremde
        Aussagen erreichen hohe Werte und landeten sonst im Prompt. Die tatsächlich
        einschlägigen Treffer enthielten dagegen durchweg die Abgleichbegriffe des
        Zielkriteriums.
        """
        if not self.einheiten or self._norm.size == 0:
            return []

        q = query_vec / (np.linalg.norm(query_vec) + 1e-10)
        scores = self._norm @ q
        klein  = [b.lower() for b in (begriffe or []) if len(b) >= 4]

        treffer: list[Einheit] = []
        for i in np.argsort(scores)[::-1]:
            if len(treffer) >= n:
                break
            wert = float(scores[i])
            if wert < min_score:
                break                      # absteigend sortiert, ab hier nichts mehr
            einheit = self.einheiten[i]
            if einheit.nr == eigene_nr:
                continue                   # steht bereits über den Direktzugriff im Prompt
            if klein:
                text = einheit.text.lower()
                if not any(b in text for b in klein):
                    continue               # thematisch nicht belegt
            treffer.append(Einheit(einheit.nr, einheit.titel, einheit.art,
                                   einheit.text, wert))
        return treffer


def formatiere_querverweise(treffer: list[Einheit]) -> str:
    """Rendert die Querverweise für den Prompt — mit Herkunft, ohne Score.

    Die Herkunftsnummer ist wesentlich: Das Modell muss erkennen, dass diese
    Anforderungen NICHT zum bewerteten Kriterium gehören. Ohne das Etikett wäre
    der wahrscheinlichste Fehler, eine fremde Anforderung als unerfüllt zu lesen.
    """
    if not treffer:
        return ""
    zeilen = ["", "MÖGLICHERWEISE EINSCHLÄGIG AUS ANDEREN ABSCHNITTEN DES STANDARDS",
              "(gehören NICHT zu diesem Kriterium — nur Zusatzkontext, niemals "
              "allein Grund für eine Einstufung):"]
    for e in treffer:
        zeilen.append(f"- [aus {e.nr} {e.titel}, {e.art}] {e.text}")
    return "\n".join(zeilen)
