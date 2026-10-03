"""Gelernter Entscheider: `N` des Modells heben, wenn die Suche dagegen spricht.

Der größte Fehlerposten der Prüfung ist ein `N`, obwohl der Kunde regelt.
Eingriffe am Urteil des Modells haben das nicht behoben. Die Scores der
Fundstellensuche trennen es dagegen gut: Ein logistisches Modell auf den
Suchmerkmalen, gelernt an den Referenzbewertungen, hebt die Trefferquote
deutlich.

## Was es tut — und was nicht

- Es **hebt nur**: Ein `N`, das das Modell nach Ansicht der vorgelegten Stellen
  vergeben hat, wird `E` oder `T`, wenn der Entscheider das für wahrscheinlicher
  hält. Ein `E`, `T` oder `A` des Modells bleibt unberührt. Der volle Entscheider,
  der auch zu `N` herabstuft, schnitt schlechter ab.
- Es liest vom Sprachmodell **nur den Status `N`**. Die Merkmale kommen aus Suche,
  Einstufung und Dokumentlänge. Ein anderes Sprachmodell braucht deshalb kein
  neues Training; ein anderes Musterlastenheft oder Einbettungsmodell schon.
- Ein gehobenes Kriterium hat keine Begründung vom Modell. Es bekommt die beste
  Fundstelle und eine Begründung, die sagt, woher der Status kommt.

## Rangierer für die Abweichungsmarkierung

Die Stufe „gründlich" markiert je Dokument zusätzlich die `E`/`T`, bei denen das
Modell `A` am nächsten war — über die Wahrscheinlichkeiten des Modells. Liefert
ein Modell keine, ersetzt der Rangierer P(A): ein logistisches Modell auf
Kriterium und Standard (offene Erzeugniswahl, offene Formulierung, Anteil `A` in
den bewerteten Lastenheften) und den Suchmerkmalen. Gelernt aus der Referenz,
ohne Sprachmodell, zusammen mit dem Entscheider.

Das gelernte Modell liegt als JSON neben dem Standard (Mittelwerte, Streuungen,
Koeffizienten) — zur Laufzeit reicht numpy. Passt es nicht zum hinterlegten
Standard oder zur Suche, bleibt es aus.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from src.verzeichnisse import DATA_DIR

DATEI = DATA_DIR / "Standard_Entscheider.json"
KLASSEN = ("E", "T", "A", "N")
MERKMALE = ("pflicht", "regel", "optional", "kandidaten", "score_1", "score_3",
            "score_10", "kosinus_1", "lexikalisch_1", "mit_lexik", "starke", "log_abschnitte")
# Regularisierung des Entscheiders.
C = 0.5
RANG_MERKMALE = ("offene_erzeugniswahl", "offene_formulierung", "anteil_a") + MERKMALE


def merkmale(kandidaten: list[dict], einstufung: str, abschnitte: int) -> list[float]:
    """Merkmalsvektor eines Kriteriums. Reihenfolge wie MERKMALE."""
    from src.pruefung.kriterien import STARK

    scores = [float(c["score"]) for c in kandidaten]
    return [
        float(einstufung == "Pflicht"), float(einstufung == "Regel"), float(einstufung == "Optional"),
        len(kandidaten) / 30,
        scores[0] if scores else 0.0,
        sum(scores[:3]) / 3 if scores else 0.0,
        sum(scores[:10]) / 10 if scores else 0.0,
        max((float(c.get("cos", 0.0)) for c in kandidaten), default=0.0),
        max((float(c.get("lex", 0.0)) for c in kandidaten), default=0.0),
        sum(1 for c in kandidaten if c.get("lex", 0) > 0) / 30,
        sum(1 for s in scores if s >= STARK) / 30,
        math.log1p(abschnitte),
    ]


def _suche(n_fundstellen: int | None = None, min_score: float | None = None,
           lexikalisches_gewicht: float | None = None,
           englische_begriffe: bool | None = None) -> dict:
    """Einstellungen der Suche. Weichen die eines Laufs von denen des Trainings ab,
    gilt das Modell nicht.

    Ohne Angaben: die Vorgaben, unter denen `main.py kalibrieren` lernt. Ein Prüflauf
    übergibt seine TATSÄCHLICHEN Werte. Vorher verglich `laden()` nur die Konstanten —
    ein Lauf mit `--min-score 0.4` oder mitwachsender Fundstellenzahl bekam den
    Entscheider trotzdem, auf Merkmalen außerhalb seiner Trainingsverteilung
    (`merkmale()` normiert fest auf 30 Plätze).
    """
    from src.dokumente.vector_store import MODELL_NAME
    from src.pruefung.kriterien import ENGLISCHE_BEGRIFFE, MIN_SCORE, N_FUNDSTELLEN, _KURZER_BEGRIFF
    return {"einbettungsmodell": MODELL_NAME,
            "n_fundstellen": N_FUNDSTELLEN if n_fundstellen is None else int(n_fundstellen),
            "min_score": MIN_SCORE if min_score is None else round(float(min_score), 6),
            "lexikalisches_gewicht": (0.35 if lexikalisches_gewicht is None
                                      else round(float(lexikalisches_gewicht), 6)),
            # Seit dem 18.09.2026 werden kurze Abgleichbegriffe nur als ganzes
            # Wort gesucht; das ändert die Merkmale lexikalisch_1 und mit_lexik.
            # Ein früher trainierter Entscheider gilt dafür nicht.
            "lexik": f"wortgrenze<={_KURZER_BEGRIFF}",
            # Seit dem 26.09.2026 gehen englische Übersetzungen der Abgleichbegriffe in
            # den Wortvergleich ein; ein früher trainierter Entscheider gilt dafür nicht.
            "englische_begriffe": (ENGLISCHE_BEGRIFFE if englische_begriffe is None
                                   else bool(englische_begriffe))}


# ── Training ──────────────────────────────────────────────────────────────────

def trainieren(X: list[list[float]], y: list[str], standard: dict, dokumente: list[str]) -> dict:
    from sklearn.linear_model import LogisticRegression

    from src.pruefung.standardhaltung import fingerabdruck

    X = np.asarray(X, dtype=float)
    mittel, streuung = X.mean(0), X.std(0)
    streuung[streuung == 0] = 1.0
    m = LogisticRegression(max_iter=3000, C=C).fit((X - mittel) / streuung, y)
    koeff = np.zeros((len(KLASSEN), X.shape[1]))
    achse = np.full(len(KLASSEN), -1e9)          # nie gesehene Klasse: nie gewählt
    if len(m.classes_) == 2:                     # sklearn hält dann nur eine Zeile
        koeff[KLASSEN.index(m.classes_[1])], achse[KLASSEN.index(m.classes_[1])] = m.coef_[0], m.intercept_[0]
        achse[KLASSEN.index(m.classes_[0])] = 0.0
    else:
        for i, k in enumerate(m.classes_):
            koeff[KLASSEN.index(k)], achse[KLASSEN.index(k)] = m.coef_[i], m.intercept_[i]
    return {
        "version": 1, "merkmale": list(MERKMALE), "klassen": list(KLASSEN),
        "mittel": mittel.tolist(), "streuung": streuung.tolist(),
        "koeffizienten": koeff.tolist(), "achsenabschnitt": achse.tolist(),
        "standard": fingerabdruck(standard), "suche": _suche(),
        "dokumente": dokumente, "faelle": int(len(y)),
        "erstellt": datetime.now().isoformat(timespec="seconds"),
    }


def speichern(modell: dict, ziel: Path | None = None) -> Path:
    from src.dateien import schreibe_json
    return schreibe_json(ziel or DATEI, modell, indent=1)


# ── Anwenden ──────────────────────────────────────────────────────────────────

def uebertragen(modell: dict, standard: dict, herkunft: str) -> dict:
    """Ein für ein anderes Musterlastenheft trainiertes Modell für `standard` freigeben.

    Für ein neues Anwendungsfeld fehlen anfangs die fünf bewerteten Lastenhefte, die
    `kalibrieren` braucht. Die Merkmale sind feldunabhängig (Suchwerte, Einstufung,
    Dokumentlänge). Die Sucheinstellungen bleiben die des Trainings und werden beim
    Laden weiter geprüft.

    Der Rangierer fällt weg: Er rechnet mit dem Anteil `A` je Kriteriumsnummer des
    Quellmusters, und gleiche Nummern meinen in einem anderen Muster andere Themen.
    """
    from datetime import datetime

    from src.pruefung.standardhaltung import fingerabdruck

    neu = {k: v for k, v in modell.items() if k != "rangierer"}
    neu["standard"] = fingerabdruck(standard)
    neu["uebertragen_von"] = herkunft
    neu["uebertragen"] = datetime.now().isoformat(timespec="seconds")
    return neu


def laden(standard: dict, pfad: Path | None = None,
          suche: dict | None = None) -> tuple[dict | None, str]:
    """Das gelernte Modell, oder None mit Grund.

    `suche` sind die Sucheinstellungen des laufenden Prüfdurchgangs (`_suche(...)`);
    ohne Angabe die Vorgaben.
    """
    from src.pruefung.standardhaltung import fingerabdruck

    p = pfad or DATEI
    if not p.exists():
        return None, "kein Entscheider trainiert (main.py kalibrieren)"
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, f"{p.name} unlesbar"
    if m.get("merkmale") != list(MERKMALE):
        return None, "Entscheider mit anderen Merkmalen trainiert"
    if m.get("standard") != fingerabdruck(standard):
        return None, "Entscheider gehört zu einem anderen Musterlastenheft"
    erwartet = suche if suche is not None else _suche()
    gelernt = m.get("suche") or {}
    if gelernt != erwartet:
        anders = sorted(k for k in set(gelernt) | set(erwartet)
                        if gelernt.get(k) != erwartet.get(k))
        return None, ("Sucheinstellungen weichen vom Training ab ("
                      + ", ".join(f"{k}: trainiert {gelernt.get(k)!r}, jetzt {erwartet.get(k)!r}"
                                  for k in anders) + ")")
    return m, ""


def zustand(ergebnis: dict) -> tuple[str, str]:
    """Stand des Entscheiders in einem Prüfergebnis: (zustand, text).

    zustand ist "aktiv", "nicht_aktiv", "aus" oder "unbekannt" (Ergebnis älter als
    das Feld). Gelesen aus `ergebnis["entscheider"]`, das der Prüflauf schreibt
    („4 gehoben“, „nicht aktiv: <Grund>“, „aus“).
    """
    stand = str(ergebnis.get("entscheider") or "")
    if not stand:
        return "unbekannt", ""
    if stand == "aus":
        return "aus", "abgeschaltet"
    if stand.startswith("nicht aktiv"):
        return "nicht_aktiv", stand.split(":", 1)[-1].strip()
    n = stand.split()[0]
    text = (f"{n} Kriterien statistisch gehoben" if n != "1"
            else "1 Kriterium statistisch gehoben")
    if "übertragen von" in stand:
        text += (f" — Entscheider {stand.split('übertragen von', 1)[1].strip()} übernommen, "
                 f"für dieses Musterlastenheft nicht eigens trainiert")
    return "aktiv", text


def wahrscheinlichkeiten(modell: dict, x: list[float]) -> dict[str, float]:
    z = (np.asarray(x) - np.asarray(modell["mittel"])) / np.asarray(modell["streuung"])
    logits = np.asarray(modell["koeffizienten"]) @ z + np.asarray(modell["achsenabschnitt"])
    logits -= logits.max()
    p = np.exp(logits) / np.exp(logits).sum()
    return {k: round(float(v), 4) for k, v in zip(modell["klassen"], p)}


def heben(bewertungen: dict, details: dict, kriterien: list[dict], abschnitte: int,
          modell: dict) -> int:
    """Hebt `N` des Modells auf `E`/`T`, wo der Entscheider das wahrscheinlicher hält.

    Nur Kriterien, zu denen das Modell befragt wurde: Stellen lagen vor und der
    Aufruf gelang. Ändert `bewertungen` und `details`; Rückgabe: Zahl der gehobenen.
    """
    einstufung = {k["nr"]: k["einstufung"] for k in kriterien}
    gehoben = 0
    for nr, b in bewertungen.items():
        d = details.get(nr) or {}
        kandidaten = d.get("kandidaten") or []
        if b.get("status") != "N" or not kandidaten or d.get("grund"):
            continue
        p = wahrscheinlichkeiten(modell, merkmale(kandidaten, einstufung.get(nr, ""), abschnitte))
        d["entscheider"] = p
        wahl = max(p, key=p.get)
        if wahl not in ("E", "T"):
            continue
        beste = kandidaten[0]
        bewertungen[nr] = {
            **b, "status": wahl, "fundstelle": f"S{beste['page']}",
            "begruendung": (f"Statistisch als {'geregelt' if wahl == 'E' else 'teilweise geregelt'} "
                            f"eingestuft: Die Suche fand passende Stellen (beste Relevanz "
                            f"{float(beste['score']):.0%}), das Modell sah keine Vorgabe. "
                            f"Bitte an der Stelle prüfen."),
            "gehoben": True, "p_entscheider": p[wahl],
        }
        gehoben += 1
    return gehoben


def lernzeilen(ordner: Path, ground_truth: dict, kriterien: list[dict], standard: dict,
               fortschritt=None, zeilen: list | None = None
               ) -> tuple[list[list[float]], list[str], list[str]]:
    """Merkmale und Referenzstatus aus bewerteten Lastenheften. Kein Sprachmodell.

    `ground_truth` ist das Format von GT_ABGLEICH (src/verzeichnisse.py);
    die Dateinamen im Ordner ohne Endung sind die Dokumentkennungen. `zeilen`
    wird, wenn übergeben, mit (Dokument, Kriterium, Merkmale, Status) gefüllt —
    das braucht der Rangierer.
    """
    from src.dokumente.pdf_loader import SUPPORTED_SUFFIXES, load_document
    from src.pruefung.kriterien import fundstellen_je_kriterium, ist_verzeichnis

    dokumente = ground_truth.get("dokumente") or {}
    dateien = sorted(p for p in Path(ordner).iterdir()
                     if p.suffix.lower() in SUPPORTED_SUFFIXES and p.stem in dokumente)
    X, y, genutzt = [], [], []
    for i, pfad in enumerate(dateien, start=1):
        if fortschritt:
            fortschritt(i, len(dateien), pfad.stem)
        alle = load_document(pfad, kind="neu")
        chunks = [c for c in alle if not ist_verzeichnis(c.text)]
        fs, _, _ = fundstellen_je_kriterium(chunks, kriterien, standard,
                                            verzeichnisse_ausschliessen=False)
        bew = dokumente[pfad.stem].get("bewertungen") or {}
        for k in kriterien:
            ref = (bew.get(k["nr"]) or {}).get("status")
            if ref not in KLASSEN:
                continue
            X.append(merkmale(fs[k["nr"]], k["einstufung"], len(alle)))
            y.append(ref)
            if zeilen is not None:
                zeilen.append((pfad.stem, k["nr"], X[-1], ref))
        genutzt.append(pfad.stem)
    return X, y, genutzt


# ── Rangierer für die Abweichungsmarkierung ───────────────────────────────────

def _standard_merkmale(nr: str, standard: dict) -> list[float]:
    from src.pruefung.hinweise import FELDER, OFFEN
    from src.pruefung.kriterien import typ_platzhalter

    chunk = standard.get(nr) or {}
    offen = any(OFFEN.search(str(t)) for f in FELDER for t in (chunk.get(f) or []))
    return [float(bool(typ_platzhalter(chunk))), float(offen)]


def rangierer_trainieren(zeilen: list, standard: dict) -> dict:
    """Aus (Dokument, Kriterium, Merkmale, Status): Ist ein geregelter Fall `A`?

    Der Anteil `A` je Kriterium zählt für jede Trainingszeile ohne ihr eigenes
    Dokument — sonst läse das Modell seine eigene Antwort mit. Gespeichert wird der
    Anteil über alle Dokumente, für neue Lastenhefte.
    """
    from collections import defaultdict

    from sklearn.linear_model import LogisticRegression

    je_kriterium = defaultdict(list)
    for dok, nr, _, ref in zeilen:
        je_kriterium[nr].append((dok, ref))

    def anteil(nr, ohne=None):
        st = [r for d, r in je_kriterium[nr] if d != ohne]
        return st.count("A") / len(st) if st else 0.0

    geregelt = [z for z in zeilen if z[3] in ("E", "T", "A")]
    y = [ref == "A" for *_, ref in geregelt]
    if len(set(y)) < 2:
        raise ValueError("es braucht Referenzfälle mit und ohne Abweichung")
    X = np.asarray([_standard_merkmale(nr, standard) + [anteil(nr, dok)] + list(m)
                    for dok, nr, m, _ in geregelt], dtype=float)
    mittel, streuung = X.mean(0), X.std(0)
    streuung[streuung == 0] = 1.0
    m = LogisticRegression(max_iter=5000, C=C).fit((X - mittel) / streuung, y)
    return {"merkmale": list(RANG_MERKMALE), "mittel": mittel.tolist(),
            "streuung": streuung.tolist(), "koeffizienten": m.coef_[0].tolist(),
            "achsenabschnitt": float(m.intercept_[0]),
            "anteil_a": {nr: round(anteil(nr), 4) for nr in je_kriterium},
            "anteil_a_geregelt": anteil_a_geregelt([(nr, ref) for _, nr, _, ref in zeilen]),
            "faelle": len(y)}


def anteil_a_geregelt(faelle: list[tuple[str, str]]) -> dict[str, float]:
    """Anteil `A` unter den geregelten Referenzfällen (E/T/A) je Kriterium.

    Anders als `anteil_a` ohne die `N` im Nenner: Die Markierung fragt nur nach
    Kriterien, die das Modell als geregelt einstuft — dort ist diese Zahl die
    Grundrate.
    """
    from collections import defaultdict

    je = defaultdict(list)
    for nr, ref in faelle:
        if ref in ("E", "T", "A"):
            je[nr].append(ref)
    return {nr: round(st.count("A") / len(st), 4) for nr, st in je.items()}


def anteil_eintragen(bewertungen: dict, modell: dict) -> int:
    """Schreibt `anteil_a` an jedes `E`/`T` — das Anzeichen „Häufung" der Markierung.

    Rückgabe: Zahl der Kriterien. Ein Entscheider ohne die Anteile (vor dem
    25.09.2026 trainiert) schreibt nichts.
    """
    anteil = (modell.get("rangierer") or {}).get("anteil_a_geregelt") or {}
    n = 0
    for nr, b in bewertungen.items():
        if b.get("status") in ("E", "T") and nr in anteil:
            b["anteil_a"] = anteil[nr]
            n += 1
    return n


def rangieren(bewertungen: dict, details: dict, kriterien: list[dict], standard: dict,
              abschnitte: int, modell: dict) -> int:
    """Schreibt `rang_abweichung` an `E`/`T`, wenn das Ergebnis keine Modellwahrscheinlichkeiten trägt.

    Mit Wahrscheinlichkeiten sortiert die Markierung weiter nach P(A) und hier
    geschieht nichts. Rückgabe: Zahl der bewerteten Kriterien.
    """
    r = modell.get("rangierer")
    if not r or r.get("merkmale") != list(RANG_MERKMALE):
        return 0
    if any(b.get("wahrscheinlichkeit") for b in bewertungen.values()):
        return 0
    einstufung = {k["nr"]: k["einstufung"] for k in kriterien}
    n = 0
    for nr, b in bewertungen.items():
        kandidaten = (details.get(nr) or {}).get("kandidaten") or []
        if b.get("status") not in ("E", "T") or not kandidaten:
            continue
        x = (_standard_merkmale(nr, standard) + [r["anteil_a"].get(nr, 0.0)]
             + merkmale(kandidaten, einstufung.get(nr, ""), abschnitte))
        z = (np.asarray(x) - np.asarray(r["mittel"])) / np.asarray(r["streuung"])
        logit = float(np.asarray(r["koeffizienten"]) @ z + r["achsenabschnitt"])
        b["rang_abweichung"] = round(1 / (1 + math.exp(-max(min(logit, 50.0), -50.0))), 4)
        n += 1
    return n
