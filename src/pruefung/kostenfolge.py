"""Kostenfolgen im Text des Lastenhefts — ein Anzeichen der Markierung „gründlich".

Kostenklauseln sind ein häufiger Abweichungstyp: Nacharbeit „zu Lasten des
Lieferanten", Bemusterung „in Rechnung gestellt", Korrekturen gegen einen festen
Betrag. Das Modell liest diese Stellen und erklärt sie oft für vereinbar.

Dieses Modul sucht deshalb in den Fundstellen selbst nach Sätzen, die dem Lieferanten
Kosten auferlegen, nach demselben Bau wie src/pruefung/markenvorgabe.py: ein Satz,
ein Kriterium — das, bei dem sein Abschnitt am besten passt. Ausgenommen sind Sätze
über das Angebot („im Angebot gesondert aufzuführen"), die keine Kostenfolge sind.
"""

from __future__ import annotations

import re

from src.pruefung.markenvorgabe import FUNDSTELLEN, saetze

KOSTEN = re.compile(
    r"zu lasten|in rechnung (?:ge)?stellt|weiter(?:be)?rechne|angelastet|nach aktuellem stundensatz|"
    r"kostenpflichtig|(?:fester|pauschal\w*) betrag|vertragsstrafe|pönale|"
    r"kosten\w*\b.{0,60}\b(?:trägt|tragen|übernimmt|übernehmen|gehen)\b|at the expense|charged to",
    re.I)
PARTEI = re.compile(
    r"lieferant|auftragnehmer|formenbauer|werkzeugherstell|hersteller|supplier|contractor|\bdiese[mn]\b",
    re.I)
AUSNAHME = re.compile(r"angebot|kalkul|ausweisen|aufzuführen|quotation", re.I)


# Verneinung und Kostenträger stehen nah an der Kostenformel: „… trägt der Lieferant
# nicht“, „nicht zu Lasten des Lieferanten“, „trägt der Auftraggeber“. Bewusst nur
# dort gesucht und nicht im ganzen Satz — „Werden Termine nicht eingehalten, gehen
# die Kosten zu Lasten des Lieferanten“ ist eine Kostenfolge.
_VERNEINUNG = re.compile(r"^(?:nicht|kein\w*|ohne|weder|not|no|never)$", re.I)
_AUFTRAGGEBER = re.compile(r"^(?:auftraggeber\w*|kunde\w*|kunden|bestell\w*|customer\w*|"
                           r"client\w*|purchaser\w*|buyer\w*)$", re.I)
_WORT = re.compile(r"[\wÄÖÜäöüß]+")
_DAVOR, _DANACH = 3, 4


def _kostenfolge_bei(satz: str, m: re.Match) -> bool:
    """Ob die Kostenformel an dieser Stelle dem Lieferanten Kosten auferlegt."""
    davor = _WORT.findall(satz[:m.start()])[-_DAVOR:]
    # Die letzten Wörter der Formel selbst: „Kosten, die der Lieferant nicht trägt“.
    innen = _WORT.findall(m.group(0))[-3:]
    danach = _WORT.findall(satz[m.end():])[:_DANACH]
    if any(_VERNEINUNG.match(w) for w in davor + innen + danach):
        return False
    # „trägt der Auftraggeber“, „zu Lasten des Kunden“: Kosten beim Auftraggeber.
    return not any(_AUFTRAGGEBER.match(w) for w in danach)


def ist_kostenfolge(satz: str) -> bool:
    if not PARTEI.search(satz) or AUSNAHME.search(satz):
        return False
    return any(_kostenfolge_bei(satz, m) for m in KOSTEN.finditer(satz))


# Kriterien, deren Standardanforderung selbst Kosten, Preise oder Mehraufwände regelt.
# Abgeleitet aus dem Musterlastenheft, nicht aus der Referenz.
_KOSTEN_IM_STANDARD = re.compile(r"kosten|zu lasten|preis|mehraufw", re.I)


def kostenkriterien(standard: dict | None) -> set[str]:
    return {nr for nr, c in (standard or {}).items()
            if _KOSTEN_IM_STANDARD.search(" ".join(c.get("standardanforderungen") or []))}


def zuordnen(details: dict, bevorzugt: set[str] | None = None) -> dict[str, dict]:
    """Kostenfolgen je Kriterium: {nr: {"satz", "fundstelle"}}. Jeder Satz geht an genau
    ein Kriterium — das mit dem höchsten Score seines Abschnitts.

    `bevorzugt` sind die Kostenkriterien des Standards: Steht ein Satz auch unter deren
    Fundstellen, geht er an das beste von ihnen. Sonst landen Kostensätze bei
    Nachbarkriterien.
    """
    bevorzugt = bevorzugt or set()
    beste: dict[str, tuple[str, tuple[bool, float], int]] = {}
    for nr, d in details.items():
        for c in ((d or {}).get("kandidaten") or [])[:FUNDSTELLEN]:
            for satz in saetze(c.get("text", "")):
                if not ist_kostenfolge(satz):
                    continue
                rang = (nr in bevorzugt, float(c.get("score", 0.0)))
                if satz not in beste or rang > beste[satz][1]:
                    beste[satz] = (nr, rang, c.get("page"))
    treffer: dict[str, dict] = {}
    for satz, (nr, _, seite) in beste.items():
        treffer.setdefault(nr, {"satz": satz[:300], "fundstelle": f"S{seite}"})
    return treffer


def eintragen(bewertungen: dict, details: dict, standard: dict | None = None) -> int:
    """Schreibt `kostenfolge` an die Bewertungen. Rückgabe: Zahl der Kriterien.

    Nur an Kriterien, die das Modell tatsächlich bewertet hat: Ein gescheiterter Aufruf
    (`grund` in details) bleibt ein Werkzeugausfall und darf nicht als A erscheinen.
    """
    treffer = zuordnen(details, kostenkriterien(standard))
    n = 0
    for nr, info in treffer.items():
        if nr in bewertungen and not (details.get(nr) or {}).get("grund"):
            bewertungen[nr]["kostenfolge"] = info
            n += 1
    return n
