"""Evaluation der Agentenausgabe gegen Referenzbewertungen.

Berichtet die im Briefing geforderten Kennzahlen:
- Exact Match über alle Testfälle
- Confusion Matrix 4 × 4 über die Statuswerte
- Precision/Recall/F1 für „geregelt erkannt" (N gegen nicht-N) — laut Briefing
  wichtiger als die Gesamttrefferquote
- Trefferquote getrennt nach Einstufung im Standard
- Abweichung der berechneten Quoten gegenüber der Referenz
- Baselines „immer E" und „immer N"
"""

import json
from collections import Counter
from pathlib import Path

from src.pruefung.kriterien import (STATUS_WERTE, ist_markiert, kennzahlen, load_kriterien,
                                    modellstatus)
from src.verzeichnisse import DATA_DIR as _DATA_DIR, GT_ABGLEICH, GT_TESTFAELLE

DATA_DIR       = _DATA_DIR
TESTFAELLE     = GT_TESTFAELLE
GROUND_TRUTH   = GT_ABGLEICH

# ── Held-out ──────────────────────────────────────────────────────────────────
# Dokumente, an denen nichts justiert werden darf. Sie tragen die einzige
# Aussage über unbekannte Lastenhefte. Die Auswahl ist einmal getroffen und
# festgeschrieben, nach der Klassenverteilung der Referenz, ohne Agentenausgabe.
HELD_OUT = ("LHD-3", "LHD-7", "LHD-15", "LHD-18")

# Feste kleine Auswahl für schnelle Vergleiche zweier Konfigurationen. Sie liegt
# im Trainingsteil und ist nicht repräsentativ — für Vergleiche auf denselben
# Fällen geeignet, nicht als Schätzung der Trefferquote.
STICHPROBE = ("LHD-17,3", "LHD-1", "LHD-9", "LHD-4", "LHD-8")

KORPUSTEILE = ("alle", "training", "held_out", "stichprobe")


def korpus(gt: dict | None = None, teil: str = "alle") -> list[str]:
    """Dokument-IDs für 'alle', 'training' (14), 'held_out' (4) oder
    'stichprobe' (die feste Fünferauswahl aus dem Trainingsteil)."""
    gt = gt if gt is not None else load_ground_truth()
    alle = list(gt["dokumente"])
    if teil == "alle":
        return alle
    if teil == "held_out":
        return [lh for lh in alle if lh in HELD_OUT]
    if teil == "training":
        return [lh for lh in alle if lh not in HELD_OUT]
    if teil == "stichprobe":
        return [lh for lh in alle if lh in STICHPROBE]
    raise ValueError(f"{teil!r} ist kein Korpusteil "
                     f"({', '.join(KORPUSTEILE)})")


def load_testfaelle(path: Path | None = None) -> list[dict]:
    """1.206 Testfälle = 18 Lastenhefte × 67 Kriterien."""
    p = path or TESTFAELLE
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_ground_truth(path: Path | None = None) -> dict:
    """Codebook, Kennzahlen und Bewertungen je Dokument."""
    return json.loads((path or GROUND_TRUTH).read_text(encoding="utf-8"))


def referenz_bewertungen(lh_id: str, gt: dict | None = None) -> dict[str, str]:
    """Referenzstatus je Kriteriumsnummer für ein Dokument."""
    gt = gt if gt is not None else load_ground_truth()
    if lh_id not in gt["dokumente"]:
        raise KeyError(f"{lh_id!r} ist kein Dokument der Ground Truth. "
                       f"Verfügbar: {', '.join(sorted(gt['dokumente']))}")
    return {nr: v["status"] for nr, v in gt["dokumente"][lh_id]["bewertungen"].items()}


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec  = tp / (tp + fn) if tp + fn else 0.0
    f1   = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def vergleiche(ergebnisse: dict[str, dict], kriterien: list[dict] | None = None,
               gt: dict | None = None) -> dict:
    """Vergleicht Agentenausgaben gegen die Referenz.

    ergebnisse — {lh_id: Agentenausgabe}. Auch ein einzelnes Dokument ist zulässig.
    Rückgabe: Kennzahlenobjekt mit Gesamt- und Einzeldokumentwerten.

    Exact Match, Confusion Matrix und Quoten messen das Urteil des Modells (samt
    Entscheider), nicht die Markierung: Ein nachträglich auf `A` gehobenes Kriterium
    zählt unter seinem Modellstatus. Was die Markierung findet, steht getrennt unter
    `markierung` — gefundene Referenz-A (vom Modell oder markiert) und die Zahl der
    Markierungen, also der Durchsichtaufwand.
    """
    kriterien   = kriterien if kriterien is not None else load_kriterien()
    gt          = gt if gt is not None else load_ground_truth()
    reihenfolge = [k["nr"] for k in kriterien]
    einstufung  = {k["nr"]: k["einstufung"] for k in kriterien}

    conf: Counter = Counter()          # (referenz, agent) -> n
    je_einstufung: dict[str, list[int]] = {}   # einstufung -> [treffer, gesamt]
    je_dokument: list[dict] = []
    ref_status_gesamt: Counter = Counter()
    markiert = markiert_a = gefunden_a = 0

    for lh_id, ergebnis in ergebnisse.items():
        ref = referenz_bewertungen(lh_id, gt)
        bew = ergebnis.get("bewertungen", {})

        treffer = 0
        for nr in reihenfolge:
            soll = ref.get(nr)
            ist  = modellstatus(bew.get(nr))
            conf[(soll, ist)] += 1
            if ist_markiert(bew.get(nr)):
                markiert += 1
                markiert_a += soll == "A"
            if soll == "A" and (bew.get(nr) or {}).get("status") == "A":
                gefunden_a += 1
            ref_status_gesamt[soll] += 1

            e = einstufung.get(nr, "?")
            je_einstufung.setdefault(e, [0, 0])
            je_einstufung[e][1] += 1
            if ist == soll:
                treffer += 1
                je_einstufung[e][0] += 1

        # Quotenabweichung gegenüber der Referenz
        # Immer nachgerechnet: Läufe vor dem 28.09.2026 speichern Kennzahlen, in
        # denen markierte Kriterien als A zählen.
        ist_kz  = kennzahlen(ergebnis, kriterien)
        soll_kz = gt["dokumente"][lh_id]["kennzahlen"]
        je_dokument.append({
            "lh_id":         lh_id,
            "exact_match":   treffer / len(reihenfolge),
            "treffer":       treffer,
            "gesamt":        len(reihenfolge),
            "quoten_delta": {
                feld: (None if ist_kz.get(feld) is None or soll_kz.get(feld) is None
                       else round(ist_kz[feld] - soll_kz[feld], 4))
                for feld in ("abweichungsquote", "abdeckungsquote", "konformitaetsquote")
            },
        })

    gesamt  = sum(conf.values())
    treffer = sum(v for (soll, ist), v in conf.items() if soll == ist)

    # Trennschärfe geregelt (E/T/A) gegen nicht geregelt (N)
    tp = sum(v for (soll, ist), v in conf.items()
             if soll not in (None, "N") and ist not in (None, "N"))
    fp = sum(v for (soll, ist), v in conf.items()
             if soll == "N" and ist not in (None, "N"))
    fn = sum(v for (soll, ist), v in conf.items()
             if soll not in (None, "N") and ist in (None, "N"))
    prec, rec, f1 = _prf(tp, fp, fn)

    return {
        "anzahl_dokumente": len(ergebnisse),
        "anzahl_testfaelle": gesamt,
        "exact_match":      treffer / gesamt if gesamt else 0.0,
        "treffer":          treffer,
        "geregelt_erkannt": {"precision": prec, "recall": rec, "f1": f1,
                             "tp": tp, "fp": fp, "fn": fn},
        "confusion":        {f"{soll}->{ist}": v for (soll, ist), v in sorted(
                                conf.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))},
        "je_einstufung":    {e: {"treffer": v[0], "gesamt": v[1],
                                 "quote": v[0] / v[1] if v[1] else 0.0}
                             for e, v in je_einstufung.items()},
        "je_dokument":      je_dokument,
        "baselines": {
            "immer_E": ref_status_gesamt["E"] / gesamt if gesamt else 0.0,
            "immer_N": ref_status_gesamt["N"] / gesamt if gesamt else 0.0,
        },
        "markierung": {
            "referenz_a":   ref_status_gesamt["A"],
            # Referenz-A, die im Ergebnis als A stehen — vom Modell oder markiert.
            "gefunden_a":   gefunden_a,
            "markiert":     markiert,
            "markiert_a":   markiert_a,
            "je_dokument":  markiert / len(ergebnisse) if ergebnisse else 0.0,
        },
        "_conf_raw": conf,
    }


def mcnemar(ergebnisse_a: dict[str, dict], ergebnisse_b: dict[str, dict],
            kriterien: list[dict] | None = None, gt: dict | None = None) -> dict:
    """Vergleicht zwei Läufe auf denselben Testfällen — gepaart.

    Zwei Modelle auf denselben Testfällen unterscheiden sich fast immer um ein paar
    Punkte. Ob das etwas bedeutet, entscheidet nicht die Differenz, sondern die
    Zahl der Fälle, in denen sie tatsächlich auseinanderlaufen.

    Der McNemar-Test betrachtet genau diese: `nur_a` sind Fälle, die nur A
    richtig hat, `nur_b` nur B. Fälle, die beide richtig oder beide falsch
    haben, tragen keine Information über den Unterschied und fallen heraus.

    Verwendet die Stetigkeitskorrektur nach Edwards. Bei wenigen abweichenden
    Fällen (unter 25) ist der exakte Binomialtest angemessener; er wird dann
    zusätzlich berichtet.
    """
    from math import comb

    kriterien = kriterien if kriterien is not None else load_kriterien()
    gt        = gt if gt is not None else load_ground_truth()
    nummern   = [k["nr"] for k in kriterien]

    gemeinsam = sorted(set(ergebnisse_a) & set(ergebnisse_b))
    beide = nur_a = nur_b = keiner = 0
    for lh in gemeinsam:
        ref = referenz_bewertungen(lh, gt)
        ba  = ergebnisse_a[lh].get("bewertungen", {})
        bb  = ergebnisse_b[lh].get("bewertungen", {})
        for nr in nummern:
            soll = ref.get(nr)
            # Ohne Referenzwert gibt es kein Richtig. Bisher galten dann BEIDE
            # als falsch — der Fall wanderte in `beide_falsch` und blähte die
            # Zahl der Testfälle auf, statt herauszufallen. Er trägt nichts
            # zum Unterschied bei und gehört übersprungen.
            if soll is None:
                continue
            a_ok = (ba.get(nr) or {}).get("status") == soll
            b_ok = (bb.get(nr) or {}).get("status") == soll
            if a_ok and b_ok:
                beide += 1
            elif a_ok:
                nur_a += 1
            elif b_ok:
                nur_b += 1
            else:
                keiner += 1

    abweichend = nur_a + nur_b
    if abweichend == 0:
        return {"dokumente": len(gemeinsam), "beide_richtig": beide,
                "nur_a": 0, "nur_b": 0, "beide_falsch": keiner,
                "abweichend": 0, "chi2": 0.0, "p": 1.0, "p_exakt": 1.0,
                "signifikant": False,
                "hinweis": "Die Läufe sind auf jedem Testfall identisch."}

    from scipy.stats import chi2 as _chi2
    # Die Korrektur nach Edwards zieht 1 vom Abstand ab — aber nicht unter
    # null. Ohne die Klammer wird aus einem Abstand von 0 durch das Quadrieren
    # wieder 1, und ein Lauf, der in beide Richtungen gleich oft abweicht,
    # bekäme eine Prüfgröße größer als bei Abstand 1. Praktisch harmlos, weil
    # p dann ohnehin nahe 1 liegt; falsch ist es trotzdem.
    stat = max(0.0, abs(nur_a - nur_b) - 1) ** 2 / abweichend
    p = float(_chi2.sf(stat, 1))

    # Exakter Binomialtest, zweiseitig
    k = min(nur_a, nur_b)
    p_exakt = min(1.0, 2 * sum(comb(abweichend, i) for i in range(k + 1))
                  / 2 ** abweichend)

    return {
        "dokumente": len(gemeinsam),
        "beide_richtig": beide, "nur_a": nur_a, "nur_b": nur_b,
        "beide_falsch": keiner, "abweichend": abweichend,
        "chi2": stat, "p": p, "p_exakt": p_exakt,
        "signifikant": (p_exakt if abweichend < 25 else p) < 0.05,
        "hinweis": ("Wenige abweichende Fälle — der exakte Test ist maßgeblich."
                    if abweichend < 25 else ""),
    }


def format_mcnemar(m: dict, name_a: str, name_b: str) -> str:
    """Rendert den gepaarten Vergleich als Text."""
    if not m["abweichend"]:
        return f"{name_a} gegen {name_b}: {m['hinweis']}"
    p = m["p_exakt"] if m["abweichend"] < 25 else m["p"]
    urteil = ("unterscheiden sich statistisch" if m["signifikant"]
              else "sind statistisch nicht unterscheidbar")
    z = [f"{name_a} gegen {name_b} — {urteil} (p = {p:.4f})",
         f"   nur {name_a} richtig: {m['nur_a']}   ·   "
         f"nur {name_b} richtig: {m['nur_b']}",
         f"   beide richtig: {m['beide_richtig']}   ·   "
         f"beide falsch: {m['beide_falsch']}"]
    if m["hinweis"]:
        z.append(f"   {m['hinweis']}")
    return "\n".join(z)


def format_bericht(ev: dict) -> str:
    """Rendert das Ergebnis von vergleiche() als Textbericht."""
    conf = ev["_conf_raw"]
    z = []
    z.append(f"Dokumente: {ev['anzahl_dokumente']}  ·  Testfälle: {ev['anzahl_testfaelle']}")
    z.append("")
    z.append(f"Exact Match            {ev['treffer']}/{ev['anzahl_testfaelle']} "
             f"= {ev['exact_match']:.1%}")
    g = ev["geregelt_erkannt"]
    z.append(f"Geregelt erkannt       Precision {g['precision']:.1%} · "
             f"Recall {g['recall']:.1%} · F1 {g['f1']:.1%}")
    z.append(f"                       TP {g['tp']}  FP {g['fp']}  FN {g['fn']}")
    z.append(f"Baseline immer E       {ev['baselines']['immer_E']:.1%}")
    z.append(f"Baseline immer N       {ev['baselines']['immer_N']:.1%}")
    m = ev.get("markierung") or {}
    if m.get("markiert") or m.get("gefunden_a"):
        z.append(f"Abweichungen gefunden  {m['gefunden_a']} von {m['referenz_a']} Referenz-A "
                 f"(Modell und Markierung)")
        z.append(f"   markiert            {m['markiert']} ({m['je_dokument']:.1f} je Dokument), "
                 f"davon {m['markiert_a']} Referenz-A — in Exact Match und Matrix unter "
                 f"dem Modellstatus")
    z.append("")

    # Kostengewichtete Sicht daneben, nicht statt. Wo beide dasselbe sagen, ist
    # die Aussage robust; wo sie auseinandergehen, liegt es an der Gewichtung
    # und gehört besprochen — siehe src/auswertung/schaden.py.
    from src.auswertung.schaden import baselines as _sch_base, bewerte as _bewerte
    s = _bewerte(conf)
    if s["n"]:
        b = _sch_base(conf)
        boden = max(b.values())
        z.append(f"Güte (kostengewichtet) {s['guete']:.1%}   "
                 f"· Schaden {s['schaden_je_kriterium']:.3f} je Kriterium")
        z.append(f"   stumpfe Strategien   {min(b.values()):.1%}–{boden:.1%} "
                 f"— darunter ist die Güte wertlos")
        for k, v in sorted(s["je_klasse"].items(), key=lambda x: -x[1]["punkte"]):
            z.append(f"   {k:<22}{v['anzahl']:>4} Fälle · {v['punkte']:>6.1f} P "
                     f"· {v['anteil']:>4.0%} des Schadens")
        z.append("")

    z.append("Confusion Matrix (Zeile = Referenz, Spalte = Agent)")
    z.append("       " + "".join(f"{s:>7}" for s in STATUS_WERTE) + "   fehlt")
    for soll in STATUS_WERTE:
        zeile = "".join(f"{conf[(soll, ist)]:7d}" for ist in STATUS_WERTE)
        z.append(f"   {soll}  {zeile}{conf[(soll, None)]:8d}")
    z.append("")

    z.append("Trefferquote je Einstufung")
    for e in ("Pflicht", "Regel", "Optional"):
        if e in ev["je_einstufung"]:
            v = ev["je_einstufung"][e]
            z.append(f"   {e:<10} {v['treffer']:>4}/{v['gesamt']:<4} = {v['quote']:.1%}")
    z.append("")

    z.append("Je Dokument")
    for d in sorted(ev["je_dokument"], key=lambda x: x["exact_match"], reverse=True):
        delta = d["quoten_delta"]["abweichungsquote"]
        dtxt  = "—" if delta is None else f"{delta:+.3f}"
        z.append(f"   {d['lh_id']:<10} {d['treffer']:>3}/{d['gesamt']} = "
                 f"{d['exact_match']:6.1%}   Δ Abweichungsquote {dtxt}")

    return "\n".join(z)
