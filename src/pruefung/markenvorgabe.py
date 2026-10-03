"""Markenvorgaben im Text des Lastenhefts — Fabrikatsbindungen, die das Modell nicht nennt.

Die Markierung „gründlich" erkennt Fabrikatsbindungen bisher an der Begründung des
Modells (Anzeichen „Beschaffung"). Ein Teil blieb damit unsichtbar: Die
Markenvorgabe stand unter den Fundstellen, das Modell beschrieb aber einen anderen
Teil des Abschnitts.

Dieses Modul sucht deshalb in den Fundstellen selbst nach Sätzen, die einen
Hersteller nennen UND etwas vorschreiben („nur", „zu verwenden", „müssen" …), und
lässt Sätze mit „bevorzugt", „z. B.", „gleichwertig", „andere Lieferanten zulässig"
aus. Zwei Einschränkungen machen den Unterschied:

- **Ein Satz, ein Kriterium.** Derselbe Abschnitt steht oft unter den Fundstellen
  mehrerer Kriterien. Ohne Zuordnung würde derselbe Satz mehrfach gemeldet.
  Zugeordnet wird der Satz dem Kriterium, bei dem sein Abschnitt am besten passt
  (höchster Score).
- **Nur Kriterien für Zukaufteile** (Normalien, Hydraulik, Elektrik, Temperierung,
  Werkstoff, Beschichtung …). Erkannt am Titel; passt kein Titel, gelten alle
  Kriterien.

Die Herstellerliste enthält nur allgemein bekannte Normalien-, Hydraulik-,
Elektrik- und Werkstoffhersteller.
"""

from __future__ import annotations

import re

# Top-k Fundstellen je Kriterium.
FUNDSTELLEN = 30

MARKEN = re.compile(
    r"\b(hasco|meusburger|d-?m-?e|strack|fibro|agathon|euchner|balluff|telemecanique|siemens|square d|"
    r"parker|merkle|roemheld|römheld|hydropneu|hawe|rexroth|festo|st[äa]ubli|harting|weidm[üu]ller|lapp|"
    r"oerlikon|balinit|b[öo]hler|uddeholm|d[öo]rrenberg|kind\s*&\s*co|buderus|loctite|kl[üu]ber|molykote|"
    r"castrol|ermeto|voss|rud|norelem|k[öo]nig|koenig|progressive|regloplas|hb-therm|fondarex)\b", re.I)
VORSCHRIFT = re.compile(
    r"\bnur\b|ausschlie(?:ß|ss)lich|zu verwenden|einzusetzen|eingesetzt werden|zu verschlie|verwenden\b|"
    r"\bmüssen\b|\bmuss\b|\bsind\b.{0,60}\bzu\b|vorgeschrieben|\blieferant\s*:|\bonly\b|\bmust\b|\bshall\b|required",
    re.I)
AUSNAHME = re.compile(
    r"bevorzugt|vorzugsweise|z\.\s?b\.|beispielsweise|gleichwertig|"
    r"andere\s+\w*\s*(?:lieferanten|hersteller)\w*\s+(?:sind\s+)?zul|"
    r"\bkönnen\b|\bkann\b|möglich|e\.g\.|equivalent|prefer|vergleichbar|etc\.", re.I)
ZUKAUFTEIL_TITEL = re.compile(
    r"schieber|auswerfer|führung und zentrierung|entlüftung|vakuum|temperier|hydraulik|elektrik|sensor|"
    r"nachverdicht|squeez|handling|werkstoffauswahl|beschicht|normteil|normalie|ersatz- und verschleiß", re.I)


def saetze(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "")
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\s[•«»>▪]\s|\s-\s|\s[e«]\s(?=[A-ZÄÖÜ])", text)
            if len(s.strip()) > 12]


def ist_markenvorgabe(satz: str) -> bool:
    return bool(MARKEN.search(satz) and VORSCHRIFT.search(satz) and not AUSNAHME.search(satz))


def zuordnen(details: dict, kriterien: list[dict]) -> dict[str, dict]:
    """Markenvorgaben je Kriterium: {nr: {"satz", "fundstelle"}}.

    `details` ist die Rückgabe der Prüfung (je Kriterium „kandidaten" mit text,
    page, score). Jeder Satz geht an genau ein Kriterium.
    """
    bereich = [k["nr"] for k in kriterien if ZUKAUFTEIL_TITEL.search(k.get("titel", ""))] \
        or [k["nr"] for k in kriterien]
    beste: dict[str, tuple[str, float, int]] = {}
    for nr in bereich:
        for c in ((details.get(nr) or {}).get("kandidaten") or [])[:FUNDSTELLEN]:
            for satz in saetze(c.get("text", "")):
                if not ist_markenvorgabe(satz):
                    continue
                score = float(c.get("score", 0.0))
                if satz not in beste or score > beste[satz][1]:
                    beste[satz] = (nr, score, c.get("page"))
    treffer: dict[str, dict] = {}
    for satz, (nr, _, seite) in beste.items():
        treffer.setdefault(nr, {"satz": satz[:300], "fundstelle": f"S{seite}"})
    return treffer


def eintragen(bewertungen: dict, details: dict, kriterien: list[dict]) -> int:
    """Schreibt `markenvorgabe` an die Bewertungen. Rückgabe: Zahl der Kriterien.

    Nur an Kriterien, die das Modell tatsächlich bewertet hat — wie bei
    Kostenfolge und Wertabgleich bleibt ein Werkzeugausfall ohne Anzeichen.
    """
    treffer = zuordnen(details, kriterien)
    n = 0
    for nr, info in treffer.items():
        if nr in bewertungen and not (details.get(nr) or {}).get("grund"):
            bewertungen[nr]["markenvorgabe"] = info
            n += 1
    return n
