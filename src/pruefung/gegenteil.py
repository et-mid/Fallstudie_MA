"""Legt der Kunde das Gegenteil einer Standardanforderung fest? Zwei Schritte.

Anlass: Das Modell liest Zuständigkeiten und Verfahren und erklärt sie für
vereinbar, auch wo der Kunde das Gegenteil festlegt. Eine einzige Frage je
Kriterium meldete fast überall etwas. Deshalb zwei Schritte:

1. **Sammeln:** Das Modell nennt Stellen, die einer Anforderung entgegenstehen könnten,
   jede mit wörtlichem Zitat. Der Code prüft das Zitat gegen die Fundstellen.
2. **Nachprüfen:** Jedes belegte Zitat geht einzeln gegen jede Anforderung des
   Kriteriums zurück, als Ja/Nein-Frage. Bestätigt ist es, wenn mindestens eine Antwort
   „Gegenteil“ lautet. Das senkt die Fehlmeldungen deutlich.

Nur an Kriterien, deren Standardanforderungen eine Zuständigkeit oder eine Erlaubnis
nennen (Verantwortung, Genehmigung, zulässig …) — abgeleitet aus dem Musterlastenheft —
und nur an E/T des Modells. Kostet mehrere Aufrufe je Kriterium.
Vorgabe aus, siehe `mit_gegenteil` in src/pruefung/kriterien.py.
"""

from __future__ import annotations

import json
import re

N_STELLEN = 12
# Höchstens so viele Meldungen je Kriterium gehen in die Nachprüfung. Jede kostet
# einen Aufruf je Anforderung; ohne Grenze wächst das mit einem gesprächigen Modell.
MAX_MELDUNGEN = 5
ARTEN = ("partei", "verboten", "vorgeschrieben", "ausgenommen")
_BETROFFEN = re.compile(
    r"verantwort|zuständig|genehmig|zulässig|unzulässig|nur mit|nur nach|untersagt|verboten|"
    r"obliegt|verbleibt|lieferumfang|ausgenommen", re.I)

SAMMELN = """Du vergleichst Stellen aus einem Kundenlastenheft für ein Druckgießwerkzeug mit
den Anforderungen eines Musterlastenhefts.

KRITERIUM {nr} — {titel}

ANFORDERUNGEN DES MUSTERLASTENHEFTS:
{anforderungen}

STELLEN AUS DEM KUNDENLASTENHEFT:
{stellen}

## Die Frage

Legt der Kunde zu einer der Anforderungen das GEGENTEIL fest? Gegenteil heißt genau
eines davon:

  partei          Eine andere Partei ist verantwortlich oder zuständig als in der Anforderung.
  verboten        Der Kunde verbietet oder beschränkt, was die Anforderung zulässt.
  vorgeschrieben  Der Kunde schreibt vor, was die Anforderung nur ausnahmsweise oder nur
                  mit Genehmigung zulässt, oder was sie untersagt.
  ausgenommen     Der Kunde nimmt einen Bestandteil aus, den die Anforderung vorsieht.

KEIN Gegenteil sind: zusätzliche Forderungen, genauere Angaben, konkrete Werte,
Verweise auf eigene Normen, andere Formulierungen derselben Sache.

## Ausgabe

Nur ein JSON-Objekt, ohne weiteren Text:

{{"gegenteil": [{{"art": "<partei|verboten|vorgeschrieben|ausgenommen>", "zitat": "<wörtlich aus den Stellen>"}}]}}

Findest du kein Gegenteil, gib {{"gegenteil": []}} zurück. Das ist die häufigste
richtige Antwort."""

NACHPRUEFEN = """Ein Musterlastenheft für Druckgießwerkzeuge enthält diese Anforderung:

ANFORDERUNG: {anforderung}

Ein Kundenlastenheft enthält diese Stelle:

KUNDENTEXT: {zitat}

Frage: Legt der Kundentext das Gegenteil der Anforderung fest?

Gegenteil heißt: Eine andere Partei ist verantwortlich als in der Anforderung; oder der
Kunde verbietet, was die Anforderung zulässt; oder er schreibt vor, was die Anforderung
nur mit Genehmigung zulässt oder untersagt; oder er nimmt aus, was die Anforderung
vorsieht.

Kein Gegenteil ist: dieselbe Sache in anderen Worten, eine genauere oder zusätzliche
Angabe, eine Abstimmungs- oder Meldepflicht, ein Kundentext zu einem anderen Thema.

Antworte nur mit einem JSON-Objekt: {{"gegenteil": true}} oder {{"gegenteil": false}}"""


def betroffen(standard: dict) -> set[str]:
    """Kriterien, deren Standardanforderungen eine Zuständigkeit oder Erlaubnis nennen."""
    return {nr for nr, c in (standard or {}).items()
            if _BETROFFEN.search(" ".join(c.get("standardanforderungen") or []))}


def _json(text: str):
    from src.pruefung.kriterien import _first_json
    blob = _first_json(text or "")
    try:
        return json.loads(blob) if blob else None
    except json.JSONDecodeError:
        return None


def pruefen(nr: str, titel: str, chunk: dict, kandidaten: list[dict], model: str, chat,
            ausfaelle: list | None = None) -> dict | None:
    """Erster bestätigter Befund {"satz", "fundstelle", "anforderung", "art"} oder None.

    Gescheiterte Aufrufe landen in `ausfaelle` — sie sind kein „kein Gegenteil".
    """
    ausfaelle = ausfaelle if ausfaelle is not None else []
    from src.pruefung.nachpruefung import zitat_belegt

    anforderungen = chunk.get("standardanforderungen") or []
    stellen = (kandidaten or [])[:N_STELLEN]
    if not anforderungen or not stellen:
        return None
    a = chat(model, SAMMELN.format(
        nr=nr, titel=titel,
        anforderungen="\n".join(f"- {s}" for s in anforderungen),
        stellen="\n\n---\n\n".join(f"[Seite {c.get('page')}]\n{c.get('text', '')}" for c in stellen)),
        num_predict=600)
    if not a.ok:
        ausfaelle.append("sammeln")
    daten = _json(a.text) if a.ok else None
    meldungen = (daten or {}).get("gegenteil") if isinstance(daten, dict) else None
    for g in (meldungen or [])[:MAX_MELDUNGEN]:
        if not isinstance(g, dict) or g.get("art") not in ARTEN:
            continue
        zitat = str(g.get("zitat", ""))
        seite = zitat_belegt(zitat, stellen)
        if not seite:
            continue
        for anf in anforderungen:
            b = chat(model, NACHPRUEFEN.format(anforderung=anf, zitat=zitat), num_predict=60)
            if not b.ok:
                ausfaelle.append("nachpruefen")
            antwort = _json(b.text) if b.ok else None
            if isinstance(antwort, dict) and antwort.get("gegenteil") is True:
                return {"satz": zitat[:300], "fundstelle": seite, "anforderung": anf,
                        "art": g["art"]}
    return None


def eintragen(bewertungen: dict, details: dict, kriterien: list[dict], standard: dict,
              model: str, chat, progress_callback=None) -> int:
    """Schreibt `gegenteil` an bestätigte E/T der betroffenen Kriterien.

    Gescheiterte Aufrufe stehen je Kriterium in `details[nr]["gegenteil_ausfaelle"]`.
    """
    titel = {k["nr"]: k["titel"] for k in kriterien}
    offen = [nr for nr in sorted(betroffen(standard))
             if isinstance(bewertungen.get(nr), dict)
             and bewertungen[nr].get("status") in ("E", "T")
             and not (details.get(nr) or {}).get("grund")]
    n = 0
    for i, nr in enumerate(offen, start=1):
        if progress_callback:
            progress_callback(i, len(offen), f"Gegenteil {nr}")
        b, d = bewertungen[nr], details.get(nr) or {}
        ausfaelle: list[str] = []
        befund = pruefen(nr, titel.get(nr, nr), standard[nr], d.get("kandidaten") or [],
                         model, chat, ausfaelle)
        if ausfaelle and nr in details:
            details[nr]["gegenteil_ausfaelle"] = len(ausfaelle)
        if befund:
            b["gegenteil"] = befund
            n += 1
    return n
