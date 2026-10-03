# Erprobte und verworfene Ansätze

Jeder Ansatz wurde gegen die Referenzbewertungen gemessen und nicht übernommen,
weil er die Prüfgüte nicht verbessert oder an anderer Stelle mehr gekostet als
gebracht hat. Die Angaben sind gerundet und beziehen sich auf den damaligen Stand.

## Prüffrage und Prompt

| Ansatz | Was getestet wurde | Ergebnis | Entscheidung |
|---|---|---|---|
| Abweichungsfrage umgedreht | Das Modell soll jede Kundenregelung Bestandteil für Bestandteil gegen den Standard prüfen | weniger richtige Urteile, keine zusätzlich erkannte Abweichung | verworfen |
| Verschärfung als Abweichung | „Was über den Standard hinausgeht, ist eine Abweichung“ als Regel im Prompt | keine zusätzliche Abweichung, rund 4 Punkte weniger Trefferquote | verworfen |
| Einschränkung der Wahl | Prüffrage „Nimmt der Kunde eine Wahl vorweg, die der Standard offenlässt?“ | keine zusätzliche Abweichung, rund 4 Punkte weniger Trefferquote | verworfen |
| Pflichtenabgleich | Frage zerlegt: „Was verlangt der Kunde, das der Standard nicht deckt?“ | schlägt bei Abweichungen und unauffälligen Fällen gleich oft an | nicht gebaut |
| Gegenteil als Sachfrage | je Standardanforderung: „Legt der Kunde das Gegenteil fest?“ | trifft Zielfälle, schlägt aber auch bei rund zwei Dritteln der Kontrollfälle an | nicht gebaut |
| Gehobene Anzeichen und Verschärfungsfrage | Zusatzsignale für statistisch gehobene Kriterien; Frage „verlangt der Kunde spürbar mehr?“ | praktisch keine Treffer, trennt nicht | verworfen |
| Beispiele im Prompt | vorgemachte Beispiele für Abweichungen statt zusätzlicher Regeln | keine zusätzliche Abweichung | verworfen |
| Zweistufige Frage „berührt?“ | erst fragen, ob ein Punkt berührt wird, dann bewerten | rund 12 Punkte weniger Trefferquote, viele richtige „keine Vorgabe“ verloren | verworfen |
| Listenpunkte als Vorgabe | Stichpunkte ohne Verb ausdrücklich als Vorgabe werten lassen | kein messbarer Effekt | verworfen |
| „Im Zweifel ja“ | Abweichungsdurchgang auf „im Zweifel Abweichung“ umgestellt | schlug nicht an | verworfen |
| Neutrales Formatbeispiel | Antwortbeispiel im Prompt ohne konkreten Status | kein messbarer Effekt | verworfen |
| Regeln voran | Regelteil vor das Kriterium gestellt, damit das Sprachmodell ihn zwischenspeichert | rund 6 Punkte weniger Trefferquote, nur 6 % schneller | verworfen |
| Prompt-Echo | Beispielwerte aus dem Korpus aus dem Prompt genommen | etwas weniger Hinweise, kein Gewinn | verworfen |
| Fabrikatshinweis an weiteren Kriterien | Hinweis auf offene Erzeugniswahl an sechs weiteren Kriterien | wenige zusätzliche Treffer, unter der festgelegten Mindestwirkung | verworfen |

## Abweichungserkennung ohne Modellurteil

| Ansatz | Was getestet wurde | Ergebnis | Entscheidung |
|---|---|---|---|
| Platzhalter-Abgleich | Modell zieht Angaben heraus, der Code entscheidet über die Abweichung | auf Zufallsniveau | verworfen |
| Namenserkennung | Modell erkennt Firmen- und Produktnamen, daraus Abweichungssignal | findet Fabrikatsnennungen zuverlässig, Abweichungen aber kaum | verworfen |

## Suche, Zerlegung und Nachprüfung

| Ansatz | Was getestet wurde | Ergebnis | Entscheidung |
|---|---|---|---|
| Abschnitt statt Kriterium | Modell liest jeden Abschnitt und ordnet ihn Kriterien zu, statt je Kriterium zu suchen | erkennt mehr geregelte Punkte, meldet aber viel zu viele | verworfen |
| Zerlegung nach Kapitelnummern | Dokument nach Kapiteln statt nach Länge zerlegen | kein Gewinn | verworfen |
| Nachprüfung von „keine Vorgabe“ | jedes N mit einem eigenen Zitat-Durchgang prüfen | rund 8 Punkte weniger Trefferquote, das Modell findet fast immer ein Zitat | verworfen |
| Referenzbeispiele | bewertete Fälle aus anderen Lastenheften je Kriterium in den Prompt | kein messbarer Effekt | verworfen |
| Hinweis-Durchgang weglassen | eigener Modelldurchgang für Hinweise abgeschaltet | ein Fünftel schneller, aber weniger gefundene Abweichungen | Durchgang bleibt |

## Entscheider und Modelle

| Ansatz | Was getestet wurde | Ergebnis | Entscheidung |
|---|---|---|---|
| Zusatzmerkmale für den Entscheider | Häufigkeit je Kriterium und Ähnlichkeit zu Referenzstellen als weitere Merkmale | keine Änderung | verworfen |
| Zweites Modell als Merkmal | Urteil eines zweiten lokalen Modells als Merkmal des Entscheiders | keine Verbesserung | verworfen |
| Gegenmittel für schwache Dokumente | Suchmerkmale relativ zum Dokument, strengere Schwelle für kurze Dokumente | keine Änderung | verworfen |
| Feintuning | ein kleines lokales Modell an den bewerteten Lastenheften nachtrainiert | leicht höhere Trefferquote, aber weder „teilweise“ noch Abweichungen erkannt | verworfen |
