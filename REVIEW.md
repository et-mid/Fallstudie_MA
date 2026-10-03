# Review Lastenheft-Prüfagent (Fallstudie)

Stand: 28.09.2026 · Gelesen: der gesamte Code. `data/` und `output/` sind
nicht versioniert und wurden nur dort herangezogen, wo der Code darauf verweist.

**Schweregrade.** *kritisch*: falsches Ergebnis oder Datenabfluss im Normalbetrieb. *hoch*:
betrifft das Hauptergebnis oder die Bedienung spürbar. *mittel*: echter Fehler mit
begrenzter Reichweite oder spürbare Wartungslast. *niedrig*: Kosmetik, Randfall, Hygiene.

Mit **(Vermutung)** markierte Punkte sind begründet, aber nicht nachgemessen. Die übrigen
Punkte sind am Code belegt, zwei davon zusätzlich per Kurztest (B1, B4).

Einen kritischen Fund gibt es nicht. Die Software ist für ein Forschungsprojekt
ungewöhnlich sorgfältig gebaut: Werkzeugausfälle werden gezählt, Formelzellen im Excel
entschärft und HTML maskiert, und es gibt keine Secrets im Code. Die wichtigsten Punkte
liegen dort, wo die Pipeline über viele Messrunden gewachsen ist:

- Kennzahlen mischen Modellurteil und Markierungen.
- Laufparameter werden nicht gegen den Entscheider geprüft.
- Die Prüfung in der Oberfläche lässt sich durch einen Klick abbrechen.
- Die zentrale Funktion hat 45 Parameter.

---

## Umsetzungsstand

| # | Stand (28.09.2026) |
|---|---|
| B3 | **umgesetzt**: `kennzahlen()` und `vergleiche()` zählen den Modellstatus; neues Feld `markiert`; eigene Kachel in der Oberfläche, Zeile im Excel-Deckblatt, Ausgabe in CLI und Evaluationsbericht; Test umgedreht, Auswertungstest ergänzt; Demo-Lauf neu erzeugt |
| B1 | **umgesetzt**: `zahl(text, einheit)`: Punkt = Tausender, Komma nur bei Zähleinheiten, führende Null immer dezimal; Tests ergänzt. Das Anzeichen „Wert“ ist noch nicht neu gemessen |
| B4 | **umgesetzt**: Verneinung und Auftraggeber im Wortfenster um die Kostenformel |
| B5 | **umgesetzt**: Fundstelle muss unter den vorgelegten Seiten liegen, sonst beste Stelle; Gliederungsnummern zählen nicht als Seite |
| B7 | **umgesetzt** (2. Runde): `src/dateien.py` (schreiben über Zwischendatei, `ersetze` kopiert erst und tauscht dann); Messlauf, Bibliothek, Standard-Import, Archiv, Entscheider, Herstellerhaltung; unlesbarer Zwischenstand bricht ab statt überschrieben zu werden |
| B8 | **umgesetzt**: `pruefen` sichert das JSON direkt nach der Prüfung (ohne `--json-out` nach `output/`); ein scheiternder Praxisabgleich kostet nur das Praxisblatt |
| B2 | **umgesetzt**: `entscheider.laden(…, suche=)` prüft die Einstellungen des Laufs (Fundstellen, Schwelle, Gewicht, englische Begriffe) und nennt die Abweichung |
| U2 | **umgesetzt**: Warnung im Bericht, wenn der Entscheider nicht lief; „Laufbedingungen“ in Oberfläche und Excel-Deckblatt; vierter Prüfpunkt „Entscheider“ in der Seitenleiste |
| U1 | **umgesetzt**: Prüfung als Hintergrundauftrag (`src/pruefung/auftrag.py`, `main.py pruefauftrag`), Lebenszeichen je 5 s, Abbrechen, Wiederanhängen nach Neuladen, Verlauf „Frühere Prüfungen“; mit Ollama Ende zu Ende geprüft |
| B6 | **umgesetzt**: Wiederaufnahme prüft Modell, Schwelle, Fingerabdruck des Musterlastenhefts und Entscheider gegen den Steckbrief jedes übernommenen Ergebnisses und bricht bei Abweichung ab |
| B9 | **umgesetzt**: unbekannter Status und Bewertungen, die kein dict sind, werden angezeigt statt abzustürzen |
| B10 | **umgesetzt**: Warnung „fehlt“ nur, wenn das Standardmodell nicht installiert ist; sonst ein sachlicher Hinweis auf das andere Modell |
| B11 | **umgesetzt**: höchstens 5 Meldungen je Kriterium in der Nachprüfung; Ausfälle je Kriterium in `details`; Fortschritt je Kriterium |
| B12 | **umgesetzt**: einheitliche Rückgabetypen, JSON über `_first_json`, „keine Aussage“ statt 0 %, Steckbrief und Entscheider auch beim Frühausstieg, `KEIN_KANDIDAT` genutzt, Markenvorgabe ohne Werkzeugausfälle |
| B13 | **umgesetzt**: Steuerzeichen werden vor dem Schreiben ins Excel entfernt |
| U7 | **umgesetzt**: Der Hintergrundlauf trägt seine Prozessnummer ein und sendet alle 5 s ein Lebenszeichen, unabhängig vom Fortschritt; Knopf „Abbrechen“ beendet ihn; „läuft noch“ hängt am Lebenszeichen statt an zehn Minuten Stille; hochgeladene Lastenhefte lassen sich einzeln entfernen und werden nur einmal geschrieben, nicht bei jedem Neuaufbau |
| übrige | offen |

## Übersicht nach Priorität

| # | Bereich | Schwere | Kurz |
|---|---|---|---|
| B3 | Bug | **hoch** | Kennzahlen und Abweichungsquote zählen markierte Verdachtsfälle als Abweichung |
| U1 | UI/UX | **hoch** | Jeder Klick während einer laufenden Prüfung bricht sie ab |
| Q1 | Qualität | **hoch** | `evaluate_document`: rund 470 Zeilen, 45 Parameter, meist verworfene Experimente |
| B2 | Bug | mittel | Entscheider wird gegen Konstanten geprüft, nicht gegen die tatsächlichen Laufparameter |
| B1 | Bug | mittel | Wertabgleich liest „0,025 mm“ als 25 mm (per Test bestätigt) |
| B4 | Bug | mittel | Kostenfolge erkennt keine Verneinung (per Test bestätigt) |
| B5 | Bug | mittel | Belegpflicht akzeptiert Seitenzahlen, die gar nicht vorgelegt wurden |
| B6 | Bug | mittel | `evaluieren` setzt Läufe mit anderem Modell oder anderer Schwelle stillschweigend fort |
| B7 | Bug | mittel | Nicht atomare Schreibvorgänge; ein Absturz kann eine Stunde Messlauf verwerfen |
| B8 | Bug | mittel | `pruefen` speichert JSON und Excel erst nach dem Praxisabgleich |
| S2 | Sicherheit | mittel | pdfminer.six 20231228 vermutlich von einer bekannten Lücke betroffen (Vermutung) |
| U2 | UI/UX | mittel | Zustand des Entscheiders und Steckbrief sind nirgends sichtbar |
| U3 | UI/UX | mittel | Akzentfarbe verfehlt WCAG-AA-Kontrast (3,7 : 1) |
| P1 | Performance | mittel | Hinweis-Durchgang kostet ~40 s je Dokument und trägt zu keiner Stufe mehr bei |
| Q2, Q3, Q6 | Qualität | mittel | Riesenmodul `kriterien.py`, toter Code, Testlücken |
| übrige | alle | niedrig | siehe unten |

---

## 1 · Bugs und Fehler

### B3 · Kennzahlen zählen markierte Verdachtsfälle als Abweichung — **hoch**
- **Wo:** `src/pruefung/kriterien.py:1517-1522`, `ui/lastenheft.py:716`,
  `src/bericht/excel_report.py` (Deckblatt, Blatt „Abweichungen“), `cli/messung.py:65`
- **Was:** `markieren()` setzt Kriterien mit Anzeichen auf `A`. Erst danach rechnet
  `kennzahlen()` die Kennzahlen. Unter „gründlich“ sind das ~10,6 Markierungen je
  Dokument, von denen laut `markierung.GEMESSEN` im Schnitt unter eine eine
  Referenzabweichung trifft (12 von 16 über 18 Dokumente).
  - Die **Abweichungsquote** auf dem Deckblatt ist deshalb überwiegend ein Maß für
    Markierungen.
  - Das gilt auch für die Kachel „Abweichung — widerspricht dem Musterlastenheft“.
  - `evaluieren` rechnet standardmäßig mit „aus“ (Korrektur: in der ersten Fassung
    dieses Reviews stand „gründlich“). Mit `--markierung gezielt/gruendlich` maß sein
    Exact Match aber die Markierung mit.
- **Auswirkung:** Die Hauptkennzahl des Berichts ist irreführend. Ein Leser hält zehn
  Verdachtsfälle für zehn festgestellte Abweichungen.
- **Vorschlag:**
  - Kennzahlen auf dem Modellurteil (`status_modell` bzw. dem Status vor der Markierung)
    rechnen und „zur Durchsicht markiert: n“ getrennt ausweisen.
  - Alternativ die Markierung als Flag führen (`markiert: true`) statt den Status zu
    überschreiben. `herkunft` und `status_modell` bleiben wie bisher.
  - `evaluieren` sollte Modell- und Markierungskennzahlen getrennt berichten.

### B2 · Entscheider gilt, obwohl die Suche anders lief — mittel
- **Wo:** `src/pruefung/entscheider.py:66-73` (feste Normierung `/30`), `:78-90` (`_suche()`),
  `:130-147` (`laden`); Aufrufer `kriterien.py:1403-1416`
- **Was:** `laden()` vergleicht die Trainingseinstellungen mit den **Modulkonstanten**
  `N_FUNDSTELLEN`, `MIN_SCORE` und `0.35`, nicht mit den Parametern des laufenden Aufrufs.
  Stillschweigend außerhalb der Trainingsverteilung landet das Merkmal in diesen Fällen:
  - `pruefen --min-score 0.4`
  - `skaliere_fundstellen=True` (bis 45 Plätze)
  - ein anderes `lexikalisches_gewicht`

  `merkmale()` normiert zusätzlich fest auf 30 Plätze.
- **Auswirkung:** Der Entscheider hebt `N` auf Basis verschobener Merkmale, und nichts
  weist darauf hin.
- **Vorschlag:** `_suche()` aus den tatsächlichen Laufparametern bilden und an `laden()`
  übergeben. Die Normierung in `merkmale()` auf `n_fundstellen` beziehen.

### B1 · Wertabgleich: Dezimalzahlen mit drei Nachkommastellen werden Tausender — mittel
- **Wo:** `src/pruefung/wertabgleich.py:46-54` (`zahl`), `:57-65` (`werte`); Test
  `tests/test_markierung.py:253` schreibt das Verhalten fest.
- **Beleg:** `werte("Toleranz ±0,025 mm, Ebenheit 0,005 mm")` ergibt
  `[('mm', 25.0, …), ('mm', 5.0, …)]`.
- **Auswirkung:** Toleranzangaben erscheinen um den Faktor 1000 „außerhalb des Belegten“.
  Das Anzeichen „Wert“ wurde gemessen verworfen (55 Meldungen, 0 A). Dieser Fehler
  verfälscht vermutlich genau diese Messung. Im Betrieb wirkt er derzeit nicht, weil „Wert“
  zu keiner Stufe gehört.
- **Vorschlag:**
  - Im deutschen Text nur `.` als Tausendertrenner werten.
  - `,ddd` nach einer führenden `0` immer als Dezimalstelle lesen.
  - Für `mm`, `%`, `°C`, `bar` und `HRC` gar keine Tausendergruppen annehmen.
  - Test anpassen und das Anzeichen neu messen.

### B4 · Kostenfolge ohne Verneinung und ohne Rollenbezug — mittel
- **Wo:** `src/pruefung/kostenfolge.py:26-38` (`KOSTEN`, `PARTEI`, `ist_kostenfolge`)
- **Beleg:** `ist_kostenfolge("Die Kosten dafür trägt dieser Lieferant nicht.")` ergibt
  `True`. Ebenso triggert ein Satz wie „Die Kosten trägt der Auftraggeber, nicht der
  Lieferant“, weil `PARTEI` irgendwo im Satz genügt.
- **Auswirkung:** Die Kostenfolge gehört zur Stufe „gezielt“. Fehlalarme landen dort
  direkt als `A` (siehe B3).
- **Vorschlag:**
  - Ein Verneinungsfenster um das Verb prüfen (`nicht|kein|ohne` in ±4 Wörtern).
  - Den Auftraggeber als Kostenträger ausschließen (`auftraggeber|kunde|customer` vor
    „trägt/übernimmt“).
  - Beides mit Testfällen absichern.

### B5 · Belegpflicht prüft die Seitenzahl nur formal — mittel
- **Wo:** `src/pruefung/kriterien.py:641-658` (`_erzwinge_belegpflicht`)
- **Was:** Es genügt, dass die Fundstelle eine Ziffer enthält. Eine vom Modell erfundene
  Seite („S97“) wird übernommen, auch wenn keine der vorgelegten Stellen von dort stammt.
  Der Hinweis-Durchgang macht es richtig (`hinweise._seite`, `hinweise.py:214-218`).
- **Auswirkung:** Der Bericht verweist auf eine Seite, auf der nichts steht. Das ist
  genau der „Ausfall, der wie ein gültiges Ergebnis aussieht“.
- **Vorschlag:** Die Seite gegen `{k["page"] for k in kandidaten}` prüfen. Passt sie
  nicht, die Seite des besten Kandidaten nehmen und das in `details` vermerken.

### B6 · Wiederaufnahme mischt Läufe mit anderen Einstellungen — mittel
- **Wo:** `cli/messung.py:151-200` (`lauf_ueber_dokumente`)
- **Was:** Geprüft wird nur `markierung`. Ein fortgesetzter Lauf
  mit anderem `--model`, `--min-score` oder `--entscheider` bzw. nach Tausch des
  Musterlastenhefts übernimmt die alten Dokumente ungeprüft. Der Steckbrief liegt in
  jedem Ergebnis, wird hier aber nicht genutzt.
- **Auswirkung:** Die Kennzahl beruht dann auf zwei Konfigurationen, ohne dass man es ihr
  ansieht.
- **Vorschlag:** Den erwarteten Steckbrief bilden und mit `steckbrief.vergleiche()` gegen
  jedes übernommene Ergebnis prüfen. Bei Abweichung abbrechen, wie bei der Markierung.

### B7 · Nicht atomare Schreibvorgänge — mittel
- **Wo:**
  - `cli/messung.py:227-231` (Zwischenstand des Messlaufs)
  - `src/muster/bibliothek.py:125-135` (`_kopieren` löscht das Ziel vor dem Kopieren)
  - `src/muster/standard_import.py:473-507` (zwei Dateien nacheinander)
  - `src/praxis/archiv.py:155-168`
- **Was:** Ein Absturz oder Strg+C während `write_text` hinterlässt eine halbe Datei. In
  `lauf_ueber_dokumente` führt ein `JSONDecodeError` zu `ergebnisse = {}`. Der nächste
  Aufruf rechnet dann alles neu und überschreibt die Datei. Bei `_kopieren` ist das Ziel
  weg, wenn das Kopieren scheitert.
- **Auswirkung:** Bis zu eine Stunde Messlauf geht verloren, oder ein Musterlastenheft
  ist halb aktiviert.
- **Vorschlag:** Das Muster aus `Arbeitsstand.schreiben` (`musteraufbau.py:158-162`)
  übernehmen: in `.tmp` schreiben, dann `replace()`. Beim Kopieren erst neben das Ziel
  kopieren, dann tauschen. Eine unlesbare Zwischenstandsdatei als Abbruch melden, nicht
  als „leer“ behandeln.

### B8 · `pruefen` speichert das Ergebnis zu spät — mittel
- **Wo:** `cli/pruefung.py:107-122`, `:141-145`
- **Was:** `lade_praxisbefunde` fängt nur `FileNotFoundError`. Eine beschädigte
  `metadata.json` wirft `JSONDecodeError`. Das passiert **nach** dem 10- bis 20-minütigen
  Prüflauf und **vor** dem Schreiben von JSON und Excel.
- **Vorschlag:** Das JSON direkt nach `evaluate_document` sichern. Den Praxisabgleich in
  `try/except Exception` kapseln und einen Fehler dort als Hinweis ausgeben.

### B9 · `print_kennzahlen` stürzt bei unbekanntem Status ab — niedrig
- **Wo:** `cli/pruefung.py:193-198`
- **Was:** `farbe[s]` wirft `KeyError`, wenn `validate` eine Datei mit Status „X“ liest.
  Eine Bewertung, die kein dict ist, wirft `AttributeError`. Beides überdeckt genau die
  Meldung, die `validate` ausgeben wollte.
- **Vorschlag:** `farbe.get(s, "white")` verwenden und Nicht-dicts überspringen.

### B10 · Falsche Warnung zur Modellwahl — niedrig
- **Wo:** `app.py:71-76`
- **Was:** Die Warnung „qwen3.5:9b fehlt“ erscheint auch, wenn es installiert ist und der
  Nutzer bewusst ein anderes Modell wählt.
- **Vorschlag:** Die Warnung nur bei `STANDARD_MODELL not in available_models` zeigen.
  Sonst sachlich formulieren: „anderes Modell gewählt, Kennzahlen gelten nicht“.

### B11 · Gegenteil-Durchgang: unbegrenzte Aufrufe, stille Ausfälle — niedrig
- **Wo:** `src/pruefung/gegenteil.py:118-131`
- **Was:** Die Zahl der Aufrufe ist Meldungen × Anforderungen und nach oben offen. Ein
  gesprächiges Modell mit 10 Zitaten bei 8 Anforderungen erzeugt 80 Aufrufe je
  Kriterium. Gescheiterte Aufrufe (`a.ok == False`) gelten als „kein Gegenteil“ und
  erscheinen nicht in `nicht_bewertet`. Während des Durchgangs gibt es keinen
  Fortschritt (siehe U4).
- **Vorschlag:** Die Meldungen auf etwa 5 begrenzen. Ausfälle in `details[nr]` vermerken
  und mitzählen. `progress_callback` durchreichen.

### B12 · Kleinere Unstimmigkeiten — niedrig
- `src/praxis/dokumentvergleich.py:239` gibt `[], 0.0` zurück, sonst ist der zweite Wert
  ein `int`.
- `dokumentvergleich._lies_urteil` nutzt `\{.*?\}`. Das scheitert, sobald im
  „unterschied“ eine `}` steht. Besser `kriterien._first_json`.
- `dokumentvergleich.py:322`: Ohne ein einziges bewertetes Paar ist die Übereinstimmung
  `0.0` statt „keine Aussage“. Die Oberfläche zeigt dann „0 %“.
- `kriterien.py:1226-1234`: Der Frühausstieg bei leerem Dokument liefert ein Ergebnis
  ohne `steckbrief` und `entscheider`. Das Schema ist dadurch uneinheitlich.
- `kriterien.py:1285, 1549, 1632`: Der Grund „keine Stelle …“ wird als Zeichenkette
  dreimal wiederholt und per `startswith` ausgewertet. Die Konstante `KEIN_KANDIDAT`
  (`:1527`) existiert, wird aber nirgends benutzt.
- `markenvorgabe.eintragen` (`markenvorgabe.py:87-93`) schreibt auch an Kriterien mit
  Werkzeugausfall. Kostenfolge und Wertabgleich schließen das aus. Derzeit folgenlos,
  weil keine Stufe das Anzeichen nutzt.

### B13 · Excel: Steuerzeichen aus PDFs (Vermutung) — niedrig
- **Wo:** `src/bericht/excel_report.py:77-91`
- **Was:** openpyxl lehnt Steuerzeichen (`\x00`–`\x1f` außer Tab und Zeilenumbruch) mit
  `IllegalCharacterError` ab. pdfplumber liefert solche Zeichen gelegentlich aus
  defekten Fonts. Es gibt keine Bereinigung und keinen Test. Tritt der Fall auf,
  scheitert der Bericht am Ende eines vollständigen Laufs.
- **Vorschlag:** In `_cell` `openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE.sub("", value)`
  anwenden und einen Test mit `\x02` ergänzen.

---

## 2 · Sicherheit

Positiv: keine hartcodierten Zugangsdaten, kein Netzzugriff außer zum lokalen Ollama,
HTML konsequent mit `html.escape` maskiert (`ui/design.py`), Formelzellen im Excel
entschärft, `data/` und `output/` pauschal von Git ausgeschlossen.

### S2 · pdfminer.six 20231228 (Vermutung) — mittel
- **Wo:** `requirements.txt:1` (`pdfplumber==0.11.4` zieht `pdfminer.six==20231228`)
- **Was:** Für pdfminer.six vor 20251107 ist meines Wissens eine Lücke beim Laden von
  CMaps veröffentlicht: Pickle-Deserialisierung, gesteuert über eine präparierte PDF
  (CVE-2025-64512). Kundendokumente sind externe Eingaben. Nicht verifiziert, weil
  `pip-audit` nicht installiert ist und ohne Netz geprüft wurde.
- **Vorschlag:** `pip-audit -r requirements.txt` ausführen und pdfplumber bzw.
  pdfminer.six anheben. Danach die Suche nachmessen, denn eine neue pdfminer-Fassung kann
  den extrahierten Text ändern.

### S3 · Upload-Dateinamen ungeprüft als Pfad — niedrig
- **Wo:** `ui/lastenheft.py:110`, `:228`, `ui/musteraufbau.py:131`
- **Was:** Die Dateien landen unter dem vom Browser gemeldeten Namen. Eine gleichnamige
  Datei, etwa ein gleichnamiges Lastenheft im Archivordner, wird ohne Rückfrage überschrieben.
  Pfadbestandteile im Namen werden nicht entfernt. Das Risiko ist lokal gering.
- **Vorschlag:** `Path(f.name).name` verwenden und bei einer vorhandenen Datei nachfragen
  oder umbenennen.

### S4 · Kundentext in dauerhaften Zwischenspeichern — niedrig
- **Wo:** `src/dokumente/pdf_loader.py:34` (`data/ocr_cache`),
  `src/dokumente/vector_store.py:35` (`data/vektoren`), `ui/lastenheft.py:110`
  (Kopie in `data/muster`)
- **Was:** Jedes in der Oberfläche geprüfte Dokument hinterlässt den erkannten Volltext,
  die Einbettungen und ggf. eine Kopie. Es gibt keine Aufräumfunktion und keine Frist.
- **Vorschlag:** Einen Knopf „Zwischenspeicher leeren“ bzw. eine Aufbewahrungsfrist
  einführen und das in der README unter Datenschutz nennen.

### S5 · Einbettungsmodell wird beim ersten Start aus dem Netz geladen — niedrig
- **Wo:** `src/dokumente/vector_store.py:92`
- **Was:** `SentenceTransformer(MODELL_NAME)` lädt beim ersten Start von Hugging Face,
  ohne feste Revision. „Läuft vollständig offline“ (README) gilt erst danach. Es gehen
  keine Kundendaten hinaus, aber es besteht eine Lieferkettenabhängigkeit.
- **Vorschlag:** Die Revision festlegen (`revision=`) oder das Modell in einen lokalen
  Pfad legen. `HF_HUB_OFFLINE=1` in `starten.bat` setzen und in der README erwähnen.

---

## 3 · Performance und Optimierung

### P1 · Hinweis-Durchgang ohne Beitrag zur Markierung — mittel
- **Wo:** `src/pruefung/kriterien.py:1093` (`mit_hinweisen=True`), `:1472-1491`
- **Was:** Zusätzliche Modellaufrufe, etwa ein Fünftel der Laufzeit. Das Anzeichen
  „Hinweis“ gehört zu keiner aktuellen Stufe mehr (`STUFEN`).
- **Vorschlag:** Neu bewerten. Trägt der Durchgang nichts, einen Schalter
  „Hinweisliste“ vorsehen, standardmäßig aus.

### P2 · Wortvergleich in Python über alle Abschnitte je Kriterium (Vermutung) — mittel
- **Wo:** `src/praxis/archiv.py:228-231` (Archivsuche), `src/pruefung/kriterien.py:1029`
- **Was:** Je Kriterium läuft `_lexikalischer_score` über jeden Abschnitt. Im Archiv sind
  das ~67 × 7.500 × ~15 Begriffe, also rund 7,5 Mio. Substring-Tests je Praxisabgleich.
- **Vorschlag:** Einmal je Dokument bzw. Archiv eine dünne Term-Matrix bauen (Begriff ×
  Abschnitt, z. B. `scipy.sparse`) und den Score als Matrixprodukt rechnen. Vorher messen.

### P3 · Unbegrenzte Zwischenspeicher — niedrig
- **Wo:** `src/dokumente/vector_store.py:36` (`_zwischenspeicher` im Prozess),
  `data/vektoren`, `data/ocr_cache`
- **Was:** Im Streamlit-Dauerprozess wächst der Speicher mit jedem geprüften Dokument. Auf
  der Platte wird nie aufgeräumt.
- **Vorschlag:** Im Prozess einen LRU-Speicher mit wenigen Einträgen verwenden, auf der
  Platte eine Größen- oder Altersgrenze (siehe S4).

### P4 · Arbeit bei jedem Neuaufbau der Seite — niedrig
- **Wo:** `app.py:63` (`pruefe_alles`: `ollama.list`, `load_standard`, Bibliothek, jedes
  Mal ungecacht), `app.py:114-119` (Agenten-Auftrag mit Gliederung), `bibliothek.eintraege()`
  mehrfach je Durchlauf, jeweils mit `sicherstellen()`
- **Vorschlag:** `st.cache_data(ttl=10)` bzw. ein Cache, der an der Änderungszeit der
  Dateien hängt, wie schon bei `list_ollama_models`.

### P5 · Seiteneffekte beim Import — niedrig
- **Wo:**
  - `src/pruefung/kriterien.py:385-386`: `KRITERIUM_PROMPT` und `AGENT_PROMPT` lesen beim
    Import die Struktur-Datei.
  - `src/verzeichnisse.py:69`: benennt beim Import Dateien um.
- **Was:** Das kostet beim Start Datei-IO. Nach einem Wechsel des Musterlastenhefts im
  laufenden Prozess sind die Werte veraltet. Heute ist das folgenlos, weil nur Tests sie
  lesen.
- **Vorschlag:** Beide Konstanten entfernen oder in Funktionen umwandeln. Die Umbenennung
  in `bibliothek.sicherstellen()` verlagern.

### P6 · Doppelte Dateizugriffe — niedrig
- `standard_import.py:88/148`: das docx wird zweimal geöffnet.
- `pdf_loader.py:410-417`: die PDF wird für Lesen und Schreiben des Caches je einmal
  vollständig gehasht.

  Beides ist nur messbar bei großen Scans. Den Schlüssel einmal berechnen und
  durchreichen.

---

## 4 · Code-Qualität

### Q1 · `evaluate_document` ist nicht mehr wartbar — **hoch**
- **Wo:** `src/pruefung/kriterien.py:1056-1524`
- **Was:** 45 Parameter. Rund 15 davon sind erprobte und verworfene Experimente:
  - `mit_abweichungspass`, `mit_beleglage`
  - `hinausgehen`, `einschraenkung`, `listenpunkte`, `verschaerfung`
  - `erzeugnishinweis_weit`, `mit_n_nachpruefung`, `referenzbeispiele`
  - `neutrales_beispiel`, `regeln_voran`, `skaliere_fundstellen`
  - `fabrikat_ist_abweichung`, `mit_fabrikatshinweis`

  Die Schalterliste für den Steckbrief wird von Hand gepflegt. `englische_begriffe` fehlt
  dort, obwohl es das Ergebnis ändert.
- **Auswirkung:** Jede neue Stufe verlängert Signatur, Steckbrief und CLI. Kombinationen
  sind nicht getestet. Fehler wie B2 entstehen genau hier.
- **Vorschlag:**
  - Eine `@dataclass Pruefkonfiguration` mit benannten Voreinstellungen einführen
    (`PRODUKTIV`, `REFERENZ_1_1`, …). Der Steckbrief entsteht automatisch aus
    `asdict(konfig)`.
  - Die Pipeline in Stufen zerlegen: `suchen → bewerten → anzeichen_eintragen →
    entscheider → markieren → kennzahlen`.
  - Experimente in ein eigenes Paket `src/experimente/` verschieben. Ihre Reproduktion
    über Git-Tags sichern statt über Dauerschalter.

### Q2 · `kriterien.py` mischt sieben Zuständigkeiten — mittel
- **Wo:** `src/pruefung/kriterien.py` (1.776 Zeilen)
- **Was:** Die Datei enthält Prompt-Vorlagen, den Ollama-Client, JSON-Parsing, den
  Verzeichnisfilter, die hybride Suche, die Pipeline, Kennzahlen und die Validierung.
  Andere Module importieren private Namen daraus (`_first_json`, `_format_standard`,
  `_lexikalischer_score`, `_chat`, `_KURZER_BEGRIFF`).
- **Vorschlag:** Aufteilen in:
  - `llm.py` (`_chat`, `LLMAntwort`, `_first_json`)
  - `suche.py` (Filter, Wortvergleich, `fundstellen_je_kriterium`)
  - `prompts.py`
  - `pipeline.py`
  - `kennzahlen.py` (Kennzahlen, Validierung)

  Die gemeinsam genutzten Funktionen werden öffentlich.

### Q3 · Toter und nur noch messhistorischer Code — mittel
- **Nur aus Tests erreichbar:** `src/dokumente/gliederung.py` (vollständig),
  `_KRITERIUM_VORLAGE_REGELN_VORAN`, `KRITERIUM_PROMPT`, `AGENT_PROMPT`,
  `fundstellen_zahl`, `erzeugnis_platzhalter(weit=True)`.
- **Nur hinter Aus-Schaltern:** `abweichung.py`, `nachpruefung.py`, `beispiele.py`,
  `referenzbeispiele.py`, `_beleglage`.
- **Berechnet, aber in keiner Stufe wirksam:**
  - `markenvorgabe.eintragen` läuft bei jeder Prüfung.
  - Anzeichen „Wert“, „Häufung“, „Beschaffung“, „Zahl/Norm“, „Statistik“.
  - `STUFEN_REFERENZ_1_1` und `STUFEN_REFERENZ_1_2`.
- **Kleinere Dopplungen:**
  - `STATUS_WERTE` und `_STATUSWERTE` (`kriterien.py:113/444`).
  - `FUNDSTELLEN = 30` (`markenvorgabe.py:34`) doppelt zu `N_FUNDSTELLEN`.
  - Das Gewicht `0.35` steht dreimal (`kriterien.py:981/1062`, `entscheider.py:83`).
  - Die Auswertung der Modellliste steht doppelt (`app.py:18-32`, `umgebung.py:37-44`).
  - `kostenfolge` und `wertabgleich` holen `saetze()` aus `markenvorgabe`. Das ist eine
    fachfremde Abhängigkeit.
- **Vorschlag:** Wie in Q1 auslagern bzw. löschen. Gemeinsame Hilfen wie `saetze` und die
  Statuswerte kommen in ein kleines `textwerkzeuge.py` bzw. `status.py`.

### Q6 · Testlücken an den neuen Stellen — mittel
- **Wo:** `tests/` (28 Prüfskripte, eigener Runner `tests/run.py`)
- **Was fehlt:**
  - Verneinung bei der Kostenfolge (B4).
  - Dezimalzahlen im Wertabgleich (B1). Der vorhandene Test schreibt den Fehler fest.
  - Abweichende Laufparameter beim Entscheider (B2).
  - Ausfall im Gegenteil-Durchgang (B11).
  - Wiederaufnahme mit fremdem Steckbrief (B6).
  - Seitenprüfung der Belegpflicht (B5).
  - Steuerzeichen im Excel (B13).

  Außerdem gibt es keine Messung der Abdeckung und keine CI.
- **Vorschlag:**
  - Tests für die genannten Fälle ergänzen.
  - Mittelfristig auf `pytest` umstellen: Die Skripte sind schon funktionsweise
    aufgebaut, die Prozesstrennung bleibt über `pytest-forked` erhalten oder über den
    vorhandenen Runner.
  - `coverage` und eine GitHub Action mit den datenunabhängigen Tests einrichten.

### Q7 · Kleinere Punkte — niedrig
- `print()` in Bibliothekscode (`pdf_loader.py:376-378`). Im Streamlit-Betrieb landet es
  in der Konsole. Stattdessen `logging` verwenden.
- `assert` als Laufzeitprüfung (`promptprofil.py` `neutralisiere`, `kriterien.py:359, 365`).
  Unter `python -O` entfällt sie. Besser ein `ValueError`.
- `DocumentChunk.kind` ist als `"muster" | "historisch" | "norm"` dokumentiert, benutzt
  wird `"neu"` (`pdf_loader.py:223`). Ein `Literal`-Typ wäre sinnvoll.
- Stil uneinheitlich: Umlaute mal ausgeschrieben, mal als ae/oe/ue in Kommentaren
  (`gliederung.py`, `kriterien.py:1136-1137`); englische Docstrings in `pdf_loader.py`;
  eine überlange Signaturzeile in `cli/messung.py:73`.
- Es gibt keine Typprüfung (mypy/pyright) und keinen Formatierer (ruff). Die Annotationen
  sind großteils vorhanden, eine Prüfung würde sich lohnen.

---

## 5 · UI und UX

### U1 · Laufende Prüfung bricht bei jeder Bedienung ab — **hoch**
- **Wo:** `ui/lastenheft.py:602-640`, `:927-929`
- **Was:** Die Prüfung läuft synchron im Streamlit-Skript, 10 bis 20 Minuten. Jede
  Bedienung während des Laufs löst einen Neuaufbau aus: ein Tab-Wechsel mit Widget, das
  Umschalten der Markierungsstufe, ein Klick im Musterlastenheft-Reiter. Streamlit
  beendet dann das laufende Skript am nächsten `progress()`-Aufruf. Der Hinweis „Fenster
  offen lassen“ deckt das nicht ab.
- **Auswirkung:** Minutenlange Arbeit geht ohne Meldung verloren.
- **Vorschlag:**
  - Die Prüfung wie den Musteraufbau als Hintergrundprozess starten: `subprocess` plus
    Fortschrittsdatei plus `st.fragment(run_every=…)`. Das Ergebnis in
    `output/<datei>_<zeit>.json` ablegen, die Oberfläche lädt es nach. Damit entsteht
    nebenbei ein Verlauf früherer Prüfungen.
  - Übergangsweise während des Laufs alle Eingaben sperren (`disabled=`) und das in der
    Oberfläche sagen.

### U2 · Entscheider und Laufbedingungen unsichtbar — mittel
- **Wo:** `kriterien.py:1403-1416` (schreibt `ergebnis["entscheider"]`),
  `ui/lastenheft.py` und `excel_report.py` (lesen ihn nicht)
- **Was:** Der Entscheider hebt die Trefferquote spürbar. Nach einem erneuten
  Import des Musterlastenhefts ändert sich der Fingerabdruck, schon weil die Ground-
  Truth-Felder neu berechnet werden. Der Entscheider ist dann „nicht aktiv“. Das steht
  nur im JSON, nicht in Oberfläche oder Excel. Auch der Steckbrief (Modell,
  Prompt-Hash, Standard) fehlt im Bericht.
- **Vorschlag:**
  - Eine Statuszeile über dem Bericht: „Entscheider aktiv, 4 gehoben“ bzw. als Warnung
    „nicht aktiv: … → `main.py kalibrieren`“.
  - Im Excel-Deckblatt einen Block „Laufbedingungen“ aus dem Steckbrief.
  - In der Seitenleiste die Voraussetzung „Entscheider“ als vierten Prüfpunkt, nicht
    blockierend.

### U3 · Kontrast der Akzentfarbe — mittel
- **Wo:** `ui/design.py:229` (`--color-accent: #5980a6`), `:514` (Primärknopf), `:554`
  (aktiver Tab), `.streamlit/config.toml` (`primaryColor`)
- **Was:** #5980a6 auf #f2f2f3 ergibt **3,71 : 1**. WCAG AA verlangt für normalen Text
  4,5 : 1. Betroffen sind die Beschriftung der Primärknöpfe (Schrift in Hintergrundfarbe
  auf Akzent) und der aktive Reiter (17 px). Die Stufen `accent-600` (4,83 : 1) und
  `accent-700` (6,62 : 1) bestehen.
- **Vorschlag:** Für Text und Knopfflächen `accent-600` oder `accent-700` verwenden. Den
  hellen Akzent nur für Flächen ohne Text und für Linien.

### U4 · Fortschritt und Rückmeldung während der Prüfung — mittel
- **Wo:** `ui/lastenheft.py:610-619`, `kriterien.py:1393-1416`
- **Was:**
  - Der Balken springt pro Phase auf 0 zurück: Kriterien, Hinweise, Zusatz.
  - Gegenteil-Durchgang, Entscheider, Markierung und Excel-Erzeugung melden nichts. Die
    Seite wirkt dann eingefroren.
  - Es gibt keine Restzeitschätzung und keinen Abbrechen-Knopf.
- **Vorschlag:**
  - Eine Phasenanzeige („Schritt 2 von 5 · Hinweise · 7/18“) mit einem durchgehenden
    Gesamtbalken, gewichtet nach Aufrufzahl.
  - Aus den ersten Kriterien eine Restzeit schätzen.
  - Mit U1 zusammen einen echten Abbruch vorsehen.

### U5 · Auswahl der Markierungsstufe — mittel
- **Wo:** `ui/lastenheft.py:880-898`
- **Was:** Der Hilfetext ist ein Absatz von ~900 Zeichen in einem Tooltip. Die Kacheln
  zeigen die Folge nicht an: rund 11 Markierungen je Dokument bei „gründlich“, 1,4 bei
  „gezielt“.
- **Vorschlag:** Ein Segment-Schalter mit drei Optionen und darunter eine Zeile:
  „Gründlich: ~11 Stellen zur Durchsicht je Lastenheft, findet gemessen 3 von 4
  Abweichungen“. Die Details in einen Expander „Was wird markiert?“.

### U6 · Barrierefreiheit im Detail — niedrig
- `ui/design.py:115`: Das „?“ der Kennzahlen ist ein `title`-Tooltip und per Tastatur
  oder Touch nicht erreichbar. Besser ein `<button>` mit `aria-describedby` oder
  `st.metric(help=…)`.
- Die Seitenleiste zeigt den Status nur über Emoji (✅/❌/⚠️, `app.py:53-57`).
  Screenreader lesen „Häkchen“. Besser ein Textstatus wie „bereit / fehlt“ mit dem
  Symbol als Beiwerk.
- `<details>` in `kriterium_block` ist mit der Tastatur bedienbar. Dass A als einziges
  gefülltes Etikett ohne Rot/Grün auskommt, ist vorbildlich.

### U7 · Musteraufbau: kein Abbrechen, keine Dateiverwaltung — niedrig
- **Wo:** `ui/musteraufbau.py:27-39`, `:125-135`; `src/muster/musteraufbau.py:173-184`
- **Was:**
  - Ein gestarteter Hintergrundlauf lässt sich nicht abbrechen.
  - Hochgeladene Lastenhefte lassen sich nicht entfernen.
  - (Vermutung) `laeuft()` gilt nach 600 s ohne Meldung als beendet. Liest
    `quellen_laden` einen langen Scan per OCR, meldet es sich zwischen zwei Dokumenten
    ggf. länger nicht. Die Oberfläche gibt dann „Vorschlagen“ wieder frei, und ein
    zweiter Prozess schreibt in dieselben Dateien.
- **Vorschlag:**
  - Die PID in `fortschritt.json` ablegen. Das ermöglicht Abbrechen und eine echte
    Prüfung, ob der Prozess noch lebt.
  - Eine Dateiliste mit Entfernen-Knopf.
  - Aus der OCR je Seite melden.

### U8 · Kleinere Punkte — niedrig
- Die Kachel „Abweichung — widerspricht dem Musterlastenheft“ (`ui/lastenheft.py:716`)
  zählt Markierungen mit (siehe B3).
- Dokumentvergleich: „0 %“, wenn kein Paar bewertet wurde (siehe B12).
- Uploads überschreiben ohne Rückfrage (S3). Das hochgeladene Musterlastenheft wird bei
  jedem Neuaufbau erneut nach `data/muster` geschrieben (`ui/lastenheft.py:110`).

### U9 · Vorschläge für eine modernere, intuitivere Oberfläche
1. **Durchsicht statt Liste:** eine Arbeitsansicht mit nur den markierten und den `A`-
   Kriterien. Links steht die Stelle im Lastenheft (Seitenbild bzw. Text), rechts das
   Musterlastenheft. Knöpfe „Abweichung bestätigen / verwerfen / Notiz“, der Stand wird
   gespeichert und exportiert. Das ist der eigentliche Arbeitsschritt des Fachbereichs,
   und die Oberfläche bildet ihn bisher nicht ab.
2. **Filter über der Kriterienliste:** nach Status, Herkunft (Modell / markiert /
   statistisch), Einstufung und Kapitel. Dazu eine Suche.
3. **Verlauf:** Liste früherer Prüfungen mit Datum, Modell und Musterlastenheft, wieder
   öffnen ohne Neurechnung (folgt aus U1).
4. **Klarere Informationsarchitektur:** Die drei Reiter mischen Einrichtung
   (Musterlastenheft, Archiv) und Arbeit (Prüfung). Besser eine Seite „Prüfen“ und eine
   Seite „Einstellungen“, über `st.navigation`.
5. **Seitenvorschau:** Bei PDF-Fundstellen die Seite als Bild einblenden. pdfplumber
   rendert das bereits für die OCR.

---

## 6 · Ideen zur Steigerung der Gesamtqualität

1. **Konfigurationsobjekt und Voreinstellungen** (siehe Q1): ein Objekt statt 45
   Parametern. Aus ihm entstehen Steckbrief, CLI-Optionen und Wiederaufnahmeprüfung (B6).
   Experimente werden reproduzierbar über Git-Tags statt über Dauerschalter.
2. **Auftragsarchitektur für lange Läufe:** Prüfung, Evaluation und Musteraufbau über
   dieselbe Mechanik aus Hintergrundprozess, Fortschrittsdatei und atomaren
   Zwischenständen (U1, B7, U7). Das vereinheitlicht Abbruch, Wiederaufnahme und Verlauf.
3. **Rückkanal aus der Durchsicht:** Bestätigte und verworfene Markierungen aus U9.1
   sammeln (lokal, anonymisiert). Das ist die einzige Quelle für neue, unberührte
   Referenzfälle und für eine ehrliche Precision je Anzeichen im Betrieb.
4. **Logging:** das `logging`-Modul mit einem Laufprotokoll je Prüfung, das Steckbrief,
   Dauer je Phase, Aufrufzahl und Ausfälle enthält. Heute verteilt sich das auf
   `print`, `console.print` und `details`.
5. **Abhängigkeiten und Qualitätssicherung:**
   - Eine Sperrdatei (`uv lock` oder `pip-tools`); `torch`, `transformers`, `ollama` und
     `scikit-learn` sind heute unfixiert.
   - `pip-audit`, `ruff` und `mypy` in einer GitHub Action zusammen mit den
     datenunabhängigen Tests.
6. **Start und Betrieb:**
   - `starten.bat` prüft, ob `venv`, Ollama und das Standardmodell vorhanden sind, und
     startet Ollama bei Bedarf.
   - `HF_HUB_OFFLINE=1` setzen (S5).
   - Der Port stimmt nicht überein: `config.toml` 8501, `.claude/launch.json` 8502. Das
     ist bewusst so, sollte aber kommentiert werden.
7. **Pipeline straffen:** Nicht mehr wirksame Anzeichen nicht mehr berechnen
   (Markenvorgabe, Wert, Häufung, P1). Die aktiven Anzeichen als Registry organisieren,
   `name → (erkennen, beleg, zulässige Status)`. Dann entfallen die verstreuten
   `eintragen`-Aufrufe in `evaluate_document` und die Sonderfälle in `markieren`.

---

## Testlauf

`python tests/run.py` am 28.09.2026: **28 bestanden · 0 übersprungen · 0 fehlgeschlagen** (ohne Ollama, mit lokalem `data/`). Die Suite ist grün. Die oben genannten Fehler B1, B2, B4 bis B8 und B11 sind nicht abgedeckt; B1 ist im Test sogar als erwartetes Verhalten festgeschrieben.
