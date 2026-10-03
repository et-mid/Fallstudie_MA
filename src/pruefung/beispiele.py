"""Dem Modell eine Abweichung ZEIGEN, statt sie ihm zu beschreiben.

Neun Anläufe zur Abweichungserkennung sind gescheitert, und alle neun haben
dem Modell etwas **gesagt**: schärfere Prüffrage, zusätzliche Regel, eigener
Durchgang, Vorfilter. Das Ergebnis war jedes Mal dasselbe — das Modell wurde
vorsichtiger statt genauer (`hinausgehen` 34-mal `E → N`, `einschraenkung`
18-mal, je null zusätzliche `A`).

Keiner hat ihm eine Abweichung vorgemacht. Im Prüf-Prompt steht bis heute kein
einziges Beispiel für ein `A`.

Zwei Fassungen, damit eine Frage nebenbei beantwortet wird, die für den
Datenschutz zählt: **Muss man dem Modell echte Kundeninhalte zeigen, oder
genügt die Form?**

`ERFUNDEN`  Beispiele in der Form der echten, aber mit ausgedachten Fabrikaten
            und Werten. Stehen im Quelltext, tragen keine Kundeninhalte.
`aus_referenz()`  Beispiele wörtlich aus der Referenzannotation, aus
            Dokumenten AUSSERHALB der Messmenge. Entstehen erst zur Laufzeit
            aus `data/`, das nicht im Repository liegt.

Der bekannte Fehlermodus ist das Prompt-Echo: Ein Beispiel im Prompt ist ein
Abschreibangebot. Im Hinweis-Prompt stand früher ein Positivbeispiel, das
wörtlich zurückkam und deshalb entfernt wurde. Neu ist, dass sich das messen
lässt — `herkunft.echo_angaben()` gegen den Beispielblock geprüft macht aus der
Sorge eine Kennzahl.
"""

_KOPF = """
## Beispiele für Abweichungen

So sieht ein A aus. Die Beispiele stammen aus anderen Lastenheften und
betreffen andere Kriterien; übernimm die Form, nicht den Inhalt. Prüfe
ausschließlich die oben vorgelegten Stellen.
"""

# Erfunden, mit Absicht: Die Fabrikate gibt es nicht, die Werte sind
# ausgedacht. Die FORM folgt den Referenzbegründungen — Gegenstand, dann
# „fabrikatsgebunden vorgeschrieben", dann was der Standard stattdessen offen
# lässt.
ERFUNDEN = [
    ("Standard nennt den Gegenstand ohne Hersteller, der Kunde nennt einen.",
     "Die Temperieranschlüsse sind als Verschraubung des Herstellers ACME, "
     "Typ TK-40, vorgeschrieben; der Standard lässt die Erzeugniswahl offen."),
    ("Der Kunde verlangt mehr, als der Standard verlangt.",
     "Gefügeproben werden an jedem formgebenden Teil dreifach verlangt; der "
     "Standard verlangt sie nur bei Bauteilen über einer Massegrenze."),
    ("Der Kunde kehrt eine Regelung des Standards um.",
     "Abweichungen werden nicht genehmigt, sondern als kostenpflichtige "
     "Zusatzleistung abgerechnet; der Standard sieht ein Genehmigungsverfahren "
     "vor."),
]


def block(paare: list[tuple[str, str]]) -> str:
    """Der Beispielblock für den Prompt. Leere Liste heißt: kein Block.

    Die geschweiften Klammern des Beispiel-JSON sind VERDOPPELT: Der Block
    wird in die Prompt-Vorlage eingesetzt, bevor `.format()` darüberläuft.
    Einfache Klammern werden dort als Platzhalter gelesen und werfen einen
    KeyError — evaluate_document warnt eigens davor.
    """
    if not paare:
        return ""
    zeilen = [_KOPF]
    for i, (lage, begruendung) in enumerate(paare, start=1):
        # Eine Begründung mit Klammern käme sonst als Platzhalter durch.
        sicher = begruendung.replace("{", "{{").replace("}", "}}")
        zeilen.append(f"{i}. {lage}")
        zeilen.append(f'   {{{{"status": "A", "begruendung": "{sicher}"}}}}')
    return "\n".join(zeilen) + "\n"


def aus_referenz(gt: dict, ausser: set[str], n: int = 3) -> list[tuple[str, str]]:
    """Echte Abweichungsbegründungen aus Dokumenten außerhalb der Messmenge.

    `ausser` sind die Dokumente, auf denen gemessen wird — aus ihnen darf kein
    Beispiel stammen, sonst zeigt man dem Modell die Lösung der Prüfung.

    Sortiert nach Kriteriumsnummer, damit die Auswahl reproduzierbar ist und
    nicht von der Reihenfolge im JSON abhängt.
    """
    kandidaten = []
    for lh in sorted(gt.get("dokumente", {})):
        if lh in ausser:
            continue
        for nr, b in sorted(gt["dokumente"][lh].get("bewertungen", {}).items()):
            if b.get("status") != "A":
                continue
            grund = (b.get("begruendung") or "").strip()
            if len(grund) > 40:
                kandidaten.append((nr, grund))

    # Je Kriterium höchstens eines: Drei Beispiele zum selben Kriterium zeigen
    # dem Modell eine Kriteriumsnummer, keine Denkweise.
    gesehen, gewaehlt = set(), []
    for nr, grund in kandidaten:
        if nr in gesehen:
            continue
        gesehen.add(nr)
        gewaehlt.append((f"Kriterium {nr} in einem anderen Lastenheft.", grund))
        if len(gewaehlt) >= n:
            break
    return gewaehlt
