# Lastenheft-Prüfagent

Lokaler Agent, der ein eingehendes Kundenlastenheft gegen ein Musterlastenheft prüft
und mit früheren Lastenheften vergleicht. Entwickelt für Druckgießwerkzeuge, über das
Musterlastenheft auf andere Anwendungsfelder übertragbar. Läuft vollständig offline mit
Ollama als Sprachmodell; kein Dokumentinhalt verlässt den Rechner.

## Zwei Funktionen

1. **Prüfung gegen das Musterlastenheft.** Das Kundenlastenheft wird Kriterium für
   Kriterium gegen den Standard bewertet. Teil des Prüfberichts ist der
   **Praxisabgleich**: Zu jedem Kriterium zeigt er, wie frühere Lastenhefte den Punkt
   geregelt haben.
2. **Vergleich mit früheren Lastenheften.** Ohne Musterlastenheft und ohne Kriterien:
   Welches frühere Lastenheft ähnelt dem neuen, und wo stimmen die Abschnitte überein?

## Prüfung gegen das Musterlastenheft

Die Prüfung folgt der Gliederung des Musterlastenhefts. Je Kriterium vergibt der
Agent genau einen Status:

| Status | Bedeutung |
|---|---|
| `E` | entspricht — geregelt und mit der Standardanforderung vereinbar |
| `T` | teilweise — berührt, aber nur in Teilen oder unverbindlich geregelt |
| `A` | Abweichung — anders geregelt als im Standard |
| `N` | keine Vorgabe — der Kunde sagt zu diesem Punkt nichts |

`N` ist **kein Mangel**. Es fällt aus der Abweichungsquote heraus und wird getrennt
ausgewertet. Jede Einstufung außer `N` braucht Fundstelle und Kurzbegründung — ohne
Fundstelle lautet der Status `N` (Belegpflicht).

Die Einstufung eines Kriteriums (`Pflicht` / `Regel` / `Optional`) gibt an, wie
verbreitet es in den Lastenheften ist, aus denen der Standard abgeleitet wurde. Sie
beeinflusst die Bewertung nicht, nur die Gewichtung eines Befunds: Ein fehlendes
Pflichtkriterium ist ein Prüfhinweis an den Fachbereich, ein fehlendes
Optionalkriterium normalerweise nicht.

### Ablauf

Ein Aufruf des Sprachmodells **pro Kriterium**, nicht pro Textabschnitt:

1. Das Lastenheft wird eingelesen (PDF oder Word, gescannte Seiten per Texterkennung),
   in Abschnitte zerlegt und eingebettet. Inhaltsverzeichnisse werden ausgesondert.
2. Der Vergleichsmaßstab kommt direkt aus dem Abschnitt des Musterlastenhefts mit
   derselben Nummer.
3. Die Fundstellen im Lastenheft findet eine **hybride Suche**: Kosinus-Ähnlichkeit der
   Einbettungen plus ein Bonus für Treffer der Abgleichbegriffe.
4. Liegt keine Stelle über der Relevanzschwelle, ist der Status `N` — ohne
   Modellaufruf.
5. Sonst bewertet das Modell dieses eine Kriterium und gibt
   `{"status", "begruendung", "fundstelle"}` zurück.
6. Ein gelernter **Entscheider** hebt ein `N` des Modells auf `E`/`T`, wenn die Suche
   deutlich dagegen spricht. Er braucht kein Sprachmodell, nur Suchmerkmale.
7. Kennzahlen rechnet der Code, nicht das Modell.

Abschnitte, die keinem Kriterium zugeordnet wurden, werden als
`zusatzanforderungen` gesammelt. Sie gehen nicht in die Kennzahlen ein.

### Hinweise und Abweichungsmarkierung

Neben den Einstufungen steht eine **Hinweisliste**: Festlegungen des Kunden an Punkten,
die das Musterlastenheft offen lässt. Sie ändert keinen Status — sie zeigt, wo der
fachliche Blick lohnt.

Die **Abweichungsmarkierung** hebt Kriterien mit Anzeichen einer Abweichung zur
Durchsicht auf `A` (Stufen „aus“, „gezielt“, „gründlich“). Markierte Kriterien zählen in
den Kennzahlen weiter unter dem Urteil des Modells und werden getrennt ausgewiesen.

### Kennzahlen

```
geregelt          = E + T + A
Abweichungsquote  = (A + 0,5 × T) / geregelt
Abdeckungsquote   = geregelt / Zahl der Kriterien
Konformitätsquote = E / geregelt
```

Nicht geregelte Kriterien fallen aus dem Nenner der Abweichungsquote heraus; die
Abdeckungsquote weist die Lücken getrennt aus.

### Ausgabeformat

```json
{
  "lh_id": "Beispiel",
  "bewertungen": {
    "1.1": {"status": "E", "begruendung": "Kopfzeile trägt Revisionsindex.", "fundstelle": "S3"},
    "1.2": {"status": "N", "begruendung": "", "fundstelle": ""}
  },
  "zusatzanforderungen": ["Werkzeug in einem vorgegebenen Farbton lackieren (S9)"],
  "kennzahlen": {
    "entspricht": 20, "teilweise": 16, "abweichung": 4, "keine_vorgabe": 27,
    "geregelt": 40, "abweichungsquote": 0.3, "abdeckungsquote": 0.597015,
    "konformitaetsquote": 0.5
  }
}
```

### Excel-Bericht

| Blatt | Inhalt |
|---|---|
| Deckblatt | Abweichungsquote, Statusverteilung, Verteilung je Einstufung, Laufbedingungen |
| Kriterien | eine Zeile je Kriterium, nach Kapiteln gegliedert, mit Beleg |
| Abweichungen | nur Status `A`, mit Stelle im Lastenheft und Standardanforderung |
| Hinweise | Festlegungen an offen gelassenen Punkten, mit Herkunft |
| Zusatzanforderungen | Kundenanforderungen ohne Entsprechung in der Gliederung |
| Praxisabgleich | nur mit Archiv: Häufigkeit und Belegstellen aus früheren Lastenheften |

## Vergleich mit früheren Lastenheften

Die früheren Lastenhefte liegen zerlegt und eingebettet in einem eigenen Archiv
(`data/praxis_index/`).

- **Rangliste:** Für jeden Abschnitt des neuen Lastenhefts wird in jedem früheren
  Dokument der beste Treffer gesucht und umgekehrt; der Rangwert mittelt beide
  Richtungen. Kein Sprachmodell, Ergebnis in Sekunden. Die Reihenfolge ist ein
  **Vorschlag**, das Vergleichsdokument frei wählbar.
- **Abschnittsvergleich:** Für das gewählte Dokument werden vergleichbare Stellen
  gepaart und vom Sprachmodell beurteilt — Wert von 0 bis 100 und ein Satz zum
  Unterschied.

Der Ähnlichkeitswert steht nie ohne seine Basis: Ausgewiesen wird immer auch, wie viele
Abschnitte überhaupt ein Gegenstück haben.

## Datendateien

Kundendokumente und alle daraus abgeleiteten Inhalte sind **nicht im Repository**
(`data/` und `output/` stehen in der `.gitignore`). Vor dem ersten Lauf gehören nach
`data/`:

| Datei in `data/` | Rolle |
|---|---|
| `struktur_kriterien.json` | die Gliederung des Musterlastenhefts |
| `Standard_Lastenheft_Chunks.jsonl` | der Vergleichsmaßstab, ein Abschnitt je Kriterium |
| Referenzbewertungen (Dateinamen in `src/verzeichnisse.py`) | nur für Auswertung und Training des Entscheiders |

Beide Standarddateien werden aus dem Musterlastenheft (Word) erzeugt, nicht von Hand
gepflegt — beim Hochladen in der Oberfläche oder über den Import. Ohne
`struktur_kriterien.json` startet die Anwendung nicht.

## Voraussetzungen

- Python 3.11+
- [Ollama](https://ollama.com) installiert und gestartet
- Das Sprachmodell `qwen3.5:9b` in Ollama
- Optional [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki) mit
  Sprachpaketen `deu`+`eng` — nötig für gescannte oder geschwärzte PDFs

## Installation

```bash
pip install -r requirements.txt
```

```bash
ollama pull qwen3.5:9b
```

## Verwendung

### Oberfläche

```bash
streamlit run app.py
```

Unter Windows genügt `starten.bat`.

- **Musterlastenheft** — die Word-Datei hochladen. Vor dem Übernehmen zeigt die
  Oberfläche, wie viele Kriterien erkannt wurden; geschrieben wird erst auf
  Bestätigung. Mehrere Musterlastenhefte lassen sich hinterlegen, eines ist aktiv.
  Darunter: ein neues Musterlastenheft aus mehreren Lastenheften erstellen.
- **Praxisarchiv** — frühere Kundenlastenhefte hochladen und „Archiv aufbauen“.
  Optional; ohne Archiv fehlen nur Praxisabgleich und Dokumentvergleich.
- **Prüfung** — das Kundenlastenheft hochladen und starten. Die Prüfung läuft im
  Hintergrund weiter, auch wenn die Seite neu geladen oder geschlossen wird. Fertige
  Prüfungen lassen sich ohne Neurechnung wieder öffnen. Daneben „Ähnliche suchen“ für
  den Vergleich mit früheren Lastenheften.

### Kommandozeile

```bash
python main.py pruefen pfad/zum/lastenheft.pdf --excel --json-out bewertung.json
python main.py validate bewertung.json
python main.py praxis-index "pfad/zu/frueheren/lastenheften"
python main.py vergleichen pfad/zum/lastenheft.pdf
python main.py kalibrieren "pfad/zu/bewerteten/lastenheften"
python main.py entscheider-uebertragen <bibliothekseintrag>
python main.py muster-vorschlag --gegenstand "Schaltschränke"
python main.py muster-aufbauen
python main.py evaluieren "pfad/zu/bewerteten/lastenheften" --json-out lauf.json
python main.py modellvergleich "pfad/zu/bewerteten/lastenheften" --model qwen3.5:9b --model mistral
python main.py list-models
```

- `kalibrieren` trainiert den Entscheider aus bewerteten Lastenheften neu (kein
  Sprachmodell nötig). `entscheider-uebertragen` übernimmt ihn von einem anderen
  hinterlegten Musterlastenheft, solange für ein neues Feld keine bewerteten
  Lastenhefte vorliegen.
- `evaluieren` misst den Agenten gegen Referenzbewertungen (Exact Match,
  Konfusionsmatrix, Precision/Recall für „geregelt“, Güte nach Schadensgewichtung) und
  sichert nach jedem Dokument; `--ground-truth` wählt andere Referenzbewertungen.
- `modellvergleich` vergleicht mehrere lokale Modelle auf denselben Lastenheften, mit
  Modellprüfung vorweg und gepaartem Signifikanztest.

## Andere Anwendungsfelder

Die Software ist nicht an Druckgießwerkzeuge gebunden. Was im Prompt vom Feld abhängt,
kommt aus dem Musterlastenheft ([src/muster/anwendungsfeld.py](src/muster/anwendungsfeld.py)):
der Gegenstand („Kundenlastenheft für …“), die Zahl der Lastenhefte, aus denen der
Standard abgeleitet ist, und die Zahl der Kriterien. Für ein neues Feld erzeugt die
Software einen **Entwurf** des Musterlastenhefts aus mehreren Kundenlastenheften:

1. Lastenhefte hochladen, Anwendungsfeld eintragen, Gliederung vorschlagen lassen.
2. Gliederung in der Oberfläche prüfen und bearbeiten.
3. Inhalte je Kriterium erzeugen lassen, als Word-Datei herunterladen, überarbeiten
   und hochladen.

Alles lokal, nur mit dem lokalen Sprachmodell.

## Sprachmodell

`qwen3.5:9b` ist die Vorgabe in Oberfläche und Kommandozeile; der Name steht an einer
Stelle in [src/pruefung/kriterien.py](src/pruefung/kriterien.py). Andere lokale Modelle
laufen ebenfalls. Das Modell läuft mit Temperatur 0 und festem Seed. Reasoning-Modelle
brauchen `think=False`; der Code schaltet das ab, sofern die installierte
`ollama`-Bibliothek den Parameter kennt.

## Projektstruktur

```
├── app.py                 ← Oberfläche (streamlit run app.py)
├── main.py                ← Kommandozeile (python main.py <befehl>)
├── cli/                   ← Befehle: pruefung, messung, muster, praxis
├── ui/                    ← Streamlit-Seiten
├── src/
│   ├── dokumente/         ← PDF-/Word-Lesen mit Texterkennung, Einbettungen
│   ├── pruefung/          ← Prüfung gegen das Musterlastenheft
│   ├── muster/            ← Musterlastenheft: Import, Bibliothek, Anwendungsfeld, Musteraufbau
│   ├── praxis/            ← frühere Lastenhefte: Archiv, Praxisabgleich, Dokumentvergleich
│   ├── auswertung/        ← Auswertung gegen Referenzbewertungen, Modellprüfung
│   └── bericht/           ← Excel-Bericht
├── docs/
│   └── verworfene-ansaetze.md  ← erprobte und verworfene Ansätze in Kurzform
├── data/                  ← nicht im Repository
└── output/                ← nicht im Repository
```

## Erprobte und verworfene Ansätze

Eine Kurzübersicht, was getestet wurde, was es gebracht hat und warum es nicht
übernommen wurde, steht in [docs/verworfene-ansaetze.md](docs/verworfene-ansaetze.md).
