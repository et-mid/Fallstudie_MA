"""Werte und Werkstoffe außerhalb dessen, was das Musterlastenheft belegt (Codebook R7).

Regel der Referenz: Weicht ein bezifferter Wert von der im Standard dokumentierten
Spannweite ab, gilt A; liegt er darin, gilt E. Das Modell prüft das nicht
zuverlässig — weder abweichende Zahlenwerte noch Werkstoffe, die im Korpus sonst
nicht vorkommen.

Dieses Modul vergleicht deshalb im Code, ohne Modellaufruf:

- **Wert:** Zahlen mit Einheit in den Fundstellen gegen die Zahlen derselben Einheit,
  die der Standard zu diesem Kriterium nennt (Anforderungen und Ausprägungen). Liegt
  ein Wert außerhalb von kleinstem und größtem belegten Wert, ist das ein Anzeichen.
- **Werkstoff:** Werkstoffnummern (1.xxxx) in den Fundstellen gegen die Liste des
  Standards, wenn er zu dem Kriterium mindestens drei Werkstoffe nennt.

Beides nur an den besten Fundstellen (Texterkennung verliest Ziffern; je weiter unten
eine Stelle steht, desto öfter gehört sie zu einem anderen Sachverhalt).
"""

from __future__ import annotations

import re

from src.pruefung.markenvorgabe import saetze

FUNDSTELLEN = 10

# Einheit -> Normalform. Schuss, Abgüsse und Gießzyklen zählen dasselbe; Hübe gehören
# zu Entgratwerkzeugen und bleiben getrennt.
_EINHEITEN = (
    (r"schuss|abg(?:ü|u)ss\w*|castings?|shots?|gießzyklen|zyklen", "schuss"),
    (r"hübe|hub\b|strokes?", "hübe"),
    (r"hrc", "hrc"),
    (r"khz", "khz"),
    (r"bar\b", "bar"),
    (r"°\s?c", "°c"),
    (r"mm\b", "mm"),
    (r"%", "%"),
)
_ZAHL = r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
_MUSTER = [(re.compile(_ZAHL + r"\s*(?:" + m + r")", re.I), name) for m, name in _EINHEITEN]
_WERKSTOFF = re.compile(r"\b1\.\d{4}\b")


# Einheiten, die zählen statt messen. Nur bei ihnen ist „150,000“ eine englisch
# geschriebene Tausendergruppe; bei Maßen ist „0,025 mm“ eine Dezimalzahl.
_ZAEHLEINHEITEN = {"schuss", "hübe"}


def zahl(text: str, einheit: str | None = None) -> float | None:
    """„150.000“ -> 150000; „0,7“ -> 0.7; „0,025“ -> 0.025.

    Der Punkt trennt Tausender (deutsche Schreibweise), außer nach einer führenden
    Null („0.025“ ist englisch geschrieben dezimal). Das Komma mit drei Ziffern
    dahinter ist nur bei Zähleinheiten ein Tausendertrenner („150,000 shots“), sonst
    ein Dezimalkomma: Vorher wurde aus „±0,025 mm“ ein Wert von 25 mm.
    """
    t = text.strip()
    if re.fullmatch(r"0[.,]\d+", t):
        return float(t.replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return float(t.replace(".", ""))
    if einheit in _ZAEHLEINHEITEN and re.fullmatch(r"\d{1,3}(?:,\d{3})+", t):
        return float(t.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}", t):
        return float(t.replace(",", ""))        # „1,500,000“ ist nie dezimal
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def werte(text: str) -> list[tuple[str, float, str]]:
    """Alle (Einheit, Zahl, Fundtext) eines Texts."""
    out = []
    for muster, name in _MUSTER:
        for m in muster.finditer(text or ""):
            z = zahl(m.group(1), name)
            if z is not None:
                out.append((name, z, m.group(0)))
    return out


def standard_spannen(chunk: dict | None) -> dict[str, tuple[float, float]]:
    """Kleinster und größter belegter Wert je Einheit im Standard zu einem Kriterium."""
    if not chunk:
        return {}
    text = " ".join((chunk.get("standardanforderungen") or [])
                    + (chunk.get("auspraegungen_im_korpus") or []))
    je: dict[str, list[float]] = {}
    for name, z, _ in werte(text):
        je.setdefault(name, []).append(z)
    return {name: (min(zs), max(zs)) for name, zs in je.items()}


def standard_werkstoffe(chunk: dict | None) -> set[str]:
    if not chunk:
        return set()
    text = " ".join((chunk.get("standardanforderungen") or [])
                    + (chunk.get("auspraegungen_im_korpus") or []))
    liste = set(_WERKSTOFF.findall(text))
    return liste if len(liste) >= 3 else set()


def pruefen(chunk: dict | None, kandidaten: list[dict]) -> dict[str, dict]:
    """{"Wert": {...}, "Werkstoff": {...}} — jeweils der erste Befund, sonst fehlt der Schlüssel."""
    spannen, liste = standard_spannen(chunk), standard_werkstoffe(chunk)
    befund: dict[str, dict] = {}
    for c in (kandidaten or [])[:FUNDSTELLEN]:
        for satz in saetze(c.get("text", "")):
            if "Wert" not in befund:
                for name, z, fund in werte(satz):
                    if name in spannen and not (spannen[name][0] <= z <= spannen[name][1]):
                        lo, hi = spannen[name]
                        befund["Wert"] = {"satz": satz[:300], "fundstelle": f"S{c.get('page')}",
                                          "wert": fund, "belegt": f"{lo:g}–{hi:g} {name}"}
                        break

        # Werkstoffnummern im ganzen Abschnitt, nicht satzweise: In Werkstofflisten
        # (Nummer direkt hinter „usw.“) schneidet die Satztrennung die
        # Nummer als zu kurzes Bruchstück ab.
        if liste and "Werkstoff" not in befund:
            text = re.sub(r"\s+", " ", c.get("text", ""))
            for m in _WERKSTOFF.finditer(text):
                if m.group(0) not in liste:
                    befund["Werkstoff"] = {
                        "satz": text[max(0, m.start() - 80):m.end() + 80].strip(),
                        "fundstelle": f"S{c.get('page')}", "wert": m.group(0),
                        "belegt": ", ".join(sorted(liste))}
                    break
    return befund


def eintragen(bewertungen: dict, details: dict, standard: dict) -> int:
    """Schreibt `wertabgleich` an die Bewertungen. Nur an Kriterien, die das Modell
    bewertet hat — ein gescheiterter Aufruf bleibt ein Werkzeugausfall."""
    n = 0
    for nr, b in bewertungen.items():
        d = details.get(nr) or {}
        if d.get("grund"):
            continue
        befund = pruefen(standard.get(nr), d.get("kandidaten") or [])
        if befund:
            b["wertabgleich"] = befund
            n += 1
    return n
