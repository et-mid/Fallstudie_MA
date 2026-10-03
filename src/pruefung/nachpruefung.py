"""Nachprüfung der `N`: ein zweiter, anders gestellter Blick auf dieselben Stellen.

Der größte Fehlerposten der Prüfung ist ein `N`, obwohl der Kunde regelt. Jede
schärfere Prüffrage im Hauptprompt ließ das Modell eher noch öfter auf `N`
ausweichen. Die Wahrscheinlichkeiten am Status-Token trennen die falschen `N`
nicht verlässlich.

Dieser Durchgang ändert deshalb nicht die Frage, sondern die Aufgabe. Statt eines
Urteils „geregelt oder nicht" verlangt er zuerst eine Sachauskunft: **die Stelle
wörtlich zitieren**, die den Sachverhalt regelt. Erst danach zwei kurze
Einordnungen — verbindlich oder nicht, widerspricht es dem Standard.

Der Code entscheidet, nicht das Modell:

- Kein Zitat, oder das Zitat steht nicht in den vorgelegten Stellen → bleibt `N`.
  Ein erfundenes oder aus dem Standardblock abgeschriebenes Zitat fällt hier heraus.
- Belegt und eine Abweichung benannt → `A`.
- Belegt und verbindlich → `E`, sonst `T`.

Läuft nur für `N`, zu denen das Modell tatsächlich befragt wurde (Stellen lagen
vor, der Aufruf gelang). Etliche zusätzliche Aufrufe je Dokument.

Erprobt und verworfen: Das Modell findet fast immer ein Zitat und zerstört
dabei mehr richtige `N`, als es falsche korrigiert. Der Schalter bleibt aus.
"""

from __future__ import annotations

import json
import re

PROMPT = """Du liest Stellen aus einem Kundenlastenheft für ein Druckgießwerkzeug.

KRITERIUM @@NR@@ — @@TITEL@@

@@STANDARD@@

STELLEN AUS DEM KUNDENLASTENHEFT:
@@STELLEN@@

## Aufgabe 1 — Zitat

Suche die Stelle, an der das Kundenlastenheft den Sachverhalt dieses Kriteriums
regelt oder erwähnt. Kopiere dazu einen zusammenhängenden Satz oder Satzteil
WÖRTLICH aus den Stellen oben, so wie er dort steht, und nenne die Seite.

Gehört keine Stelle zu diesem Sachverhalt, lass „zitat" leer. Stellen aus
Inhaltsverzeichnissen und Stellen, die einen anderen Sachverhalt regeln, zählen
nicht.

## Aufgabe 2 — Einordnung des Zitats

verbindlich: "ja", wenn die Stelle den Punkt als Pflicht festlegt; "nein", wenn sie
ihn nur beiläufig erwähnt oder offen lässt („nach Absprache", „sofern möglich",
„kann").

abweichung: Widerspricht die Stelle der Standardanforderung — anderer Wert,
andere Zuständigkeit, andere Norm, ein vorgeschriebenes Fabrikat, wo der Standard
keines vorschreibt, oder eine zusätzliche Pflicht? Dann benenne den Unterschied in
einem Satz. Sonst leer lassen.

## Ausgabeformat

Gib ausschließlich ein JSON-Objekt zurück, ohne umgebenden Text:

{"zitat": "", "seite": "", "verbindlich": "", "abweichung": ""}"""

# Ein Zitat unter dieser Länge ist meist nur das Stichwort des Kriteriums.
MIN_ZITAT_ZEICHEN = 25
MIN_ZITAT_WOERTER = 4
# Anteil der Zitatwörter, die in den Stellen stehen müssen. OCR-Text und
# Silbentrennung verhindern einen reinen Teilstringvergleich.
MIN_WORTANTEIL = 0.8

_VERNEINUNG = re.compile(r"^\s*(kein\w*|nicht|nichts|nein|n/?a|entf[äa]llt|-)\b", re.I)


def _woerter(text: str) -> list[str]:
    text = re.sub(r"-\s*\n\s*", "", text or "")
    return re.findall(r"[0-9a-zäöüß]{3,}", text.lower())


def zitat_belegt(zitat: str, kandidaten: list[dict]) -> str | None:
    """Seite der Stelle, in der das Zitat steht — sonst None."""
    from src.pruefung.kriterien import ist_verzeichnis

    woerter = _woerter(zitat)
    if len(zitat.strip()) < MIN_ZITAT_ZEICHEN or len(woerter) < MIN_ZITAT_WOERTER:
        return None
    if ist_verzeichnis(zitat):
        return None
    beste, anteil_bester = None, 0.0
    for k in kandidaten:
        vorrat = set(_woerter(k.get("text", "")))
        anteil = sum(1 for w in woerter if w in vorrat) / len(woerter)
        if anteil > anteil_bester:
            beste, anteil_bester = k, anteil
    if beste is None or anteil_bester < MIN_WORTANTEIL:
        return None
    return f"S{beste.get('page', '?')}"


def pruefe(nr: str, titel: str, standard_text: str, kandidaten: list[dict],
           model: str, chat, num_predict: int = 512, feld=None) -> dict:
    """Ein Aufruf für ein `N`. Rückgabe: neue Bewertung oder das `N`, dazu Rohdaten."""
    from src.muster.anwendungsfeld import uebertragen
    from src.pruefung.abweichung import formatiere_belegstellen
    from src.pruefung.kriterien import _first_json

    leer = {"status": "N", "begruendung": "", "fundstelle": ""}
    prompt = (uebertragen(PROMPT, feld)
              .replace("@@NR@@", nr).replace("@@TITEL@@", titel)
              .replace("@@STANDARD@@", standard_text)
              .replace("@@STELLEN@@", formatiere_belegstellen(kandidaten)))
    antwort = chat(model, prompt, num_predict)
    roh = {"raw": antwort.text if antwort.ok else "", "grund": "" if antwort.ok else antwort.grund}
    if not antwort.ok:
        return {"bewertung": leer, **roh}

    blob = _first_json(antwort.text)
    try:
        daten = json.loads(blob) if blob else {}
    except json.JSONDecodeError:
        daten = {}
    if not isinstance(daten, dict):
        daten = {}

    zitat = " ".join(str(daten.get("zitat") or "").split())
    fundstelle = zitat_belegt(zitat, kandidaten) if zitat else None
    roh.update(zitat=zitat, belegt=bool(fundstelle))
    if not fundstelle:
        return {"bewertung": leer, **roh}

    abweichung = " ".join(str(daten.get("abweichung") or "").split())
    kurz = zitat if len(zitat) <= 160 else zitat[:157].rstrip() + " …"
    if len(abweichung) >= 12 and not _VERNEINUNG.search(abweichung):
        return {"bewertung": {"status": "A", "fundstelle": fundstelle,
                              "begruendung": f"{abweichung} (Stelle: „{kurz}“)"}, **roh}
    verbindlich = str(daten.get("verbindlich") or "").strip().lower().startswith(("ja", "true"))
    return {"bewertung": {"status": "E" if verbindlich else "T", "fundstelle": fundstelle,
                          "begruendung": f"Geregelt: „{kurz}“"}, **roh}


def nachpruefen(ergebnis: dict, details: dict, kriterien: list[dict], standard: dict,
                model: str, chat, num_predict: int = 512, feld=None,
                progress_callback=None) -> int:
    """Prüft alle vom Modell vergebenen `N` nach. Ändert `ergebnis` und `details`.

    Rückgabe: Zahl der umgestuften Kriterien. Umgestufte tragen
    `status_vor_nachpruefung`, der Mitschnitt steht unter details[nr]["nachpruefung"].
    """
    from src.pruefung.kriterien import _format_standard

    titel = {k["nr"]: k for k in kriterien}
    offen = [nr for nr, b in ergebnis["bewertungen"].items()
             if b.get("status") == "N" and (details.get(nr) or {}).get("kandidaten")
             and not (details.get(nr) or {}).get("grund")]
    geaendert = 0
    for i, nr in enumerate(offen, start=1):
        if progress_callback:
            progress_callback(i, len(offen), f"Nachprüfung {nr}")
        k = titel.get(nr, {"titel": nr, "abgleichbegriffe": []})
        massstab = _format_standard(k, standard.get(nr), mit_fabrikatshinweis=True, feld=feld)
        erg = pruefe(nr, k["titel"], massstab, details[nr]["kandidaten"], model, chat,
                     num_predict, feld)
        details[nr]["nachpruefung"] = {s: v for s, v in erg.items() if s != "bewertung"}
        neu = erg["bewertung"]
        if neu["status"] != "N":
            alt = ergebnis["bewertungen"][nr]
            ergebnis["bewertungen"][nr] = {**neu, "status_vor_nachpruefung": "N",
                                           **({"wahrscheinlichkeit": alt["wahrscheinlichkeit"]}
                                              if alt.get("wahrscheinlichkeit") else {})}
            geaendert += 1
    return geaendert
